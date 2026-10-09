"""agent: from a described idea to an approved campaign, as a visible workflow the owner can steer.

The owner describes the idea in their own words (typed or spoken). The agent
  1. reads the idea into a brief, where every field is an exact span of the owner's words (anything else is dropped),
  2. answers the scripted interview with those spans, so the same grounding checks apply as in Talk,
  3. stops at human gates (questions it cannot answer from the idea, locking the plan, approving assets, sending),
  4. and in between observes real state (plan, jobs, checks, forecast) and acts: budget check, write Campaign 0,
     run checks, forecast, persona opinions, and offers an optimize step only if the opinions say copy is weak.

It never locks facts, approves assets or sends anything. Each tick looks at the database, decides what is next and does
at most the work that is ready, so a run can be stopped, resumed or steered at any point. Steps call the app's own
routes, so they obey exactly the same rules as the screens.
"""
from __future__ import annotations

from app.agnes import text_ready

from app import languages

import asyncio
import json
import re
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import forecast as forecast_mod
from app import learn as learn_mod
from app import panel as panel_mod
from app import scout as scout_mod
from app import persona, plan
from app.db import Database
from app.media import fail
from app.service import now
from app.worker import parse_json_object

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_run (
  id TEXT PRIMARY KEY,
  idea TEXT NOT NULL,
  lang TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
"""
INTERVIEW_FIELDS = (
    "business_name", "business_type", "area", "goal", "offer_item", "offer_type", "discount_percent", "price_amount",
    "start_date", "end_date", "days", "time_window", "terms", "audiences", "languages", "channels", "cta",
    "email_recipients", "tone",
)
LOCKS: dict[str, asyncio.Lock] = {}
PLANNER_LIMITS = {"time_s": 300, "money_inr": 50, "review_s": 600}
WEAK_MEAN = persona.TARGET_MEAN

# id, title, kind, tool, why. `kind` says who does it: ai, rule (code), human, mixed.
STEPS = (
    ("understand", "Read your idea", "ai", "agnes-3.0-flash",
     "Turns your words into a brief. Every field must be an exact phrase you said; anything else is thrown away."),
    ("interview", "Fill the gaps", "mixed", "interview + grounding",
     "Answers the standard questions from your phrases. Whatever you did not say, it asks you."),
    ("scout", "Check the timing", "rule", "occasion calendar",
     "Looks for fixed-date occasions and events you added near your offer dates. It does not look at competitors or the web."),
    ("plan_lock", "Lock the plan", "human", "plan",
     "You read the plan with your own quotes under each line and lock it. Nothing is written before this."),
    ("budget", "Check it fits", "rule", "knapsack planner",
     "Works out whether your channels and languages fit the time, money and review limits."),
    ("write", "Write Campaign 0", "ai", "copy, validator, meaning check",
     "Writes every channel and language, then checks prices, dates and weekdays against the lock and the meaning in back-translation."),
    ("panel", "Review panel", "mixed", "facts, meaning, tone, claims + referee",
     "Four reviewers read each asset on their own. A code referee shows you only what needs a human."),
    ("forecast", "Forecast and test", "rule", "history forecast + personas",
     "Expected redemptions from past campaigns, plus synthetic customers saying what works."),
    ("optimize", "Improve weak copy", "mixed", "persona feedback",
     "Only offered when the persona opinions say some copy is weak. Rewrites it, checks it again, at most twice."),
    ("approve", "Approve assets", "human", "campaign board",
     "You approve each asset. Only approved assets can be shared."),
    ("send", "Share it", "human", "outreach",
     "Copy, share to WhatsApp, send email, download. Tracked links count real clicks."),
    ("results", "Log what happened", "human", "your numbers",
     "After the offer runs, enter how many people each asset reached and how many redeemed. The app never guesses these."),
    ("learn", "Learn from it", "rule", "forecast vs actual",
     "Compares your numbers with its own forecast, says where it was wrong, and adjusts later forecasts with your real rates."),
    ("next", "Draft the next campaign", "mixed", "agent",
     "Writes the next idea from facts you already locked, best channels first. You approve it like any other."),
)


class RunIn(BaseModel):
    idea: str = Field(min_length=8, max_length=2000)
    lang: str = Field(default="en", pattern=languages.LANG_PATTERN)


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent.internal", timeout=120)


def _load(db: Database, run_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM agent_run WHERE id = ?", (run_id,))
    if row is None:
        raise fail("not_found", "No agent run with that id.", 404)
    return {**row, "state": json.loads(row["state"])}


def _save(db: Database, run: dict[str, Any]) -> None:
    db.execute("UPDATE agent_run SET state = ?, updated_at = ? WHERE id = ?",
               (json.dumps(run["state"], ensure_ascii=False), now(), run["id"]))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def ground_brief(idea: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields whose value is an exact span of the owner's words. Returns {fields, dropped}."""
    haystack = _norm(idea)
    fields, dropped = {}, []
    source = raw.get("fields") if isinstance(raw.get("fields"), dict) else raw
    for name in INTERVIEW_FIELDS:
        value = source.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        if _norm(value) in haystack:
            fields[name] = value.strip()
        else:
            dropped.append(name)
    budget = raw.get("budget_inr", source.get("budget_inr"))
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0 and str(int(budget)) in re.sub(r"[,\s]", "", idea):
        fields["_budget_inr"] = float(budget)
    return {"fields": fields, "dropped": dropped}


FIELD_HELP = {
    "business_name": "the shop's name", "business_type": "what kind of business (cafe, bakery, salon, gym ...)",
    "area": "locality and city", "goal": "what the owner wants (promote an offer, launch, more walk-ins ...)",
    "offer_item": "the product or service the offer is on", "offer_type": "the kind of offer (percent off, fixed price, buy one get one, free item)",
    "discount_percent": "the percentage", "price_amount": "the offer price in rupees", "start_date": "when it starts",
    "end_date": "when it ends", "days": "WHICH WEEKDAYS it runs (weekend, Saturday and Sunday, every day)",
    "time_window": "HOURS OF THE DAY it runs (8 am to 11 am), never weekdays", "terms": "conditions such as dine-in only",
    "audiences": "who it is for", "languages": "languages for the posts", "channels": "where to promote it",
    "cta": "phone, link or handle customers should use", "email_recipients": "people to email", "tone": "the voice of the posts",
}


def understand_messages(idea: str) -> list[dict[str, str]]:
    shape = {"fields": {name: f"<{FIELD_HELP[name]}: exact phrase from the idea, or omit>" for name in INTERVIEW_FIELDS},
             "budget_inr": "<number or omit>"}
    return [
        {"role": "system", "content": (
            "You read a small business owner's description of a marketing idea and pull out facts for a form. For each field, "
            "return the SHORTEST exact phrase copied character for character from the owner's text that answers it, for example "
            "business_name 'Brew Bandi Cafe', discount_percent '20%', audiences 'students and families', channels "
            "'WhatsApp and Instagram'. Never rephrase, translate, calculate or guess. If the owner did not say it, omit the "
            "field. One phrase may serve several fields. Return one JSON object only, in this shape: " + json.dumps(shape))},
        {"role": "user", "content": idea},
    ]


async def _understand(app, run: dict[str, Any]) -> None:
    raw = await app.state.agnes.chat(understand_messages(run["idea"]), cache_kind="agent_brief", temperature=0, max_tokens=1500)
    grounded = ground_brief(run["idea"], parse_json_object(raw))
    run["state"]["brief"] = grounded


async def _feed_interview(app, client: httpx.AsyncClient, run: dict[str, Any]) -> dict[str, Any]:
    """Answer scripted questions with the owner's phrases until one cannot be answered. Returns the step outcome."""
    st = run["state"]
    fields = st["brief"]["fields"]
    if not st.get("session_id"):
        r = await client.post("/interview/start", json={"lang": run["lang"]})
        r.raise_for_status()
        st["session_id"] = r.json()["id"]
    sid = st["session_id"]
    session = (await client.get(f"/interview/{sid}")).json()
    for _ in range(40):
        q = session.get("question")
        if q is None:
            break
        phrase = fields.get(q["field"])
        if phrase is None and not q["required"]:
            phrase = "skip"
        if phrase is None:
            return {"status": "needs_you", "detail": f"Needs you: {q['prompt']}", "action": {"screen": "voice", "id": sid},
                    "waiting_on": q["field"]}
        r = await client.post(f"/interview/{sid}/answer", json={"text": phrase, "source": "typed"})
        if r.status_code >= 400:
            return {"status": "failed", "detail": r.text[:200]}
        session = r.json()
        if session.get("clarify"):
            return {"status": "needs_you", "detail": f"Needs you: {session['clarify']['reason']}",
                    "action": {"screen": "voice", "id": sid}, "waiting_on": session["clarify"]["field"]}
    if session["status"] == "complete":
        done = await client.post(f"/interview/{sid}/finish", json={})
        if done.status_code >= 400:
            return {"status": "failed", "detail": done.text[:200]}
        st["campaign_id"] = done.json()["campaign_id"]
        return {"status": "done", "detail": "Interview complete from your words and your answers."}
    return {"status": "needs_you", "detail": "Waiting for your answers.", "action": {"screen": "voice", "id": sid}}


def _jobs_open(db: Database, campaign_id: str, kinds: tuple[str, ...]) -> int:
    marks = ",".join("?" for _ in kinds)
    row = db.query_one(f"SELECT COUNT(*) AS n FROM job WHERE campaign_id = ? AND kind IN ({marks}) AND status IN ('queued','running')",
                       (campaign_id, *kinds))
    return row["n"] if row else 0


def _set(steps: dict[str, dict[str, Any]], key: str, status: str, detail: str = "", **extra: Any) -> None:
    steps[key].update({"status": status, "detail": detail, **extra})


async def tick(app, run: dict[str, Any]) -> dict[str, Any]:
    """Observe the state, do the next ready work, return the run view. Idempotent."""
    db: Database = app.state.db
    st = run["state"]
    steps = {s[0]: {"id": s[0], "title": s[1], "kind": s[2], "tool": s[3], "why": s[4], "status": "pending", "detail": "",
                    "action": None} for s in STEPS}
    client = _client(app)
    try:
        # 1 understand
        if "brief" not in st:
            try:
                _set(steps, "understand", "running", "Reading your idea.")
                await _understand(app, run)
            except Exception as exc:  # noqa: BLE001 report in the step, never crash the run
                _set(steps, "understand", "failed", f"Could not read the idea: {str(exc)[:160]}")
                return _view(run, steps)
        brief = st["brief"]
        kept = len(brief["fields"]) - (1 if "_budget_inr" in brief["fields"] else 0)
        _set(steps, "understand", "done", f"Found {kept} facts in your own words."
             + (f" Dropped {len(brief['dropped'])} that were not exact quotes." if brief["dropped"] else ""))

        # 2 interview
        if not st.get("campaign_id"):
            out = await _feed_interview(app, client, run)
            _save(db, run)
            steps["interview"].update(out)
            if out["status"] != "done":
                return _view(run, steps)
        _set(steps, "interview", "done", "Interview complete.", action={"screen": "voice", "id": st.get("session_id")})
        cid = st["campaign_id"]

        # 3 timing notes (information only)
        plan_data = plan.get_plan(db, cid)
        try:
            from datetime import date as _date
            ds = [d for d in (scout_mod._parse(x) for x in (plan_data["offer_facts"]["dates"] if plan_data else [])) if d]
            win = (min(ds), max(ds)) if ds else None
            today = _date.today()
            notes = scout_mod.advise(win, plan_data["audiences"] if plan_data else [],
                                     scout_mod.occasions(today) + scout_mod._owner_events(db), today)
            _set(steps, "scout", "done", notes[0]["note"] if notes else "No fixed-date occasion near your dates. Add local events on the Plan screen.",
                 action={"screen": "plan", "id": cid})
        except Exception as exc:  # noqa: BLE001 timing notes must never stop the run
            _set(steps, "scout", "skipped", f"Timing notes were not available: {str(exc)[:80]}")

        # 3b plan lock (human)
        if not plan_data or plan_data["status"] != "locked":
            _set(steps, "plan_lock", "needs_you", "Read the plan and lock it. Nothing is written until you do.",
                 action={"screen": "plan", "id": cid})
            return _view(run, steps)
        _set(steps, "plan_lock", "done", "Plan locked.", action={"screen": "plan", "id": cid})

        # 4 budget
        wanted = [{"lang": lang, "channel": ch, "audience_id": aud}
                  for lang in plan_data["languages"] for ch in plan_data["channels"] for aud in plan_data["audiences"]]
        limits = dict(PLANNER_LIMITS)
        if "_budget_inr" in brief["fields"]:
            limits["money_inr"] = brief["fields"]["_budget_inr"]
        from app.extras import latest_calibration
        from app.lab.domain.planner import solve
        result = solve({"wanted": wanted, "limits": limits}, latest_calibration(), poster_uses_photo=False)
        st["budget"] = {"feasible": result["feasible"], "cost": result.get("cost"), "dropped": len(result["dropped"])}
        if result["feasible"] and not result["dropped"]:
            c = result["cost"]
            _set(steps, "budget", "done", f"Everything fits: about {round(c['time_s'])} s, Rs {c['money_inr']}, "
                 f"{round(c['review_s'] / 60, 1)} min of your review.", action={"screen": "planner", "id": None})
        else:
            _set(steps, "budget", "done", f"{result['dropped'] and len(result['dropped'])} item(s) would not fit your limits. "
                 "Campaign 0 still writes the whole plan; trim channels or languages in Talk to fit.", action={"screen": "planner", "id": None})

        # 5 write
        assets = db.assets_for(cid)
        if not assets:
            if not st.get("write_started"):
                r = await client.post("/campaign/generate", json={"campaign_id": cid})
                if r.status_code >= 400:
                    _set(steps, "write", "failed", r.text[:200])
                    return _view(run, steps)
                st["write_started"] = True
                _save(db, run)
            _set(steps, "write", "running", "Writing every channel and language.", action={"screen": "campaign", "id": cid})
            return _view(run, steps)
        open_jobs = _jobs_open(db, cid, ("copy", "review"))
        blocked = sum(1 for a in assets if a["status"] == "blocked")
        if open_jobs:
            _set(steps, "write", "running", f"{len(assets)} assets, {open_jobs} checks or rewrites still running.",
                 action={"screen": "campaign", "id": cid})
            return _view(run, steps)
        _set(steps, "write", "done",
             f"{len(assets)} assets written and checked." + (f" {blocked} blocked by a check and rewritten or held for you." if blocked else ""),
             action={"screen": "campaign", "id": cid})

        # 5b review panel
        if not st.get("panel_started"):
            await client.post(f"/campaign/{cid}/panel")
            st["panel_started"] = True
            _save(db, run)
        pv = panel_mod.panel_for(db, cid)
        ps = pv["summary"]
        if ps["reviewed"] < ps["assets"]:
            _set(steps, "panel", "running", f"{ps['reviewed']} of {ps['assets']} assets reviewed by the panel.", action={"screen": "dashboard", "id": cid})
            return _view(run, steps)
        flagged = [i for i in pv["items"] if i["needs_human"]]
        st["panel_flagged"] = len(flagged)
        _set(steps, "panel", "done", f"{ps['clear']} of {ps['assets']} assets clear." + (f" {len(flagged)} need your eyes: "
             + "; ".join(f"{i['channel'].replace('_', ' ')} ({i['lang']}) {next((v['reason'] for v in i['verdicts'] if v['verdict'] in ('block', 'concern')), i['status'])[:70]}" for i in flagged[:2]) + "." if flagged else ""),
             action={"screen": "dashboard", "id": cid})

        # 6 forecast and personas
        fc = forecast_mod.campaign_forecast(db, cid)
        if not st.get("predict_started"):
            await client.post(f"/campaign/{cid}/predict")
            st["predict_started"] = True
            _save(db, run)
        predicting = _jobs_open(db, cid, ("predict",))
        totals = fc["totals"]
        line = (f"Expected {totals['mid']} redemptions (likely {totals['low']} to {totals['high']}) at typical reach. "
                if totals else "No channel here has history to forecast. ")
        line += " ".join(fc["notes"])
        if predicting:
            _set(steps, "forecast", "running", line + " Personas are reading the copy.", action={"screen": "dashboard", "id": cid})
            return _view(run, steps)
        _set(steps, "forecast", "done", line.strip(), action={"screen": "dashboard", "id": cid})

        # 7 optimize (only if personas found weak copy)
        preds = list(persona.predictions_for_campaign(db, cid).values())
        weak = [p for p in preds if p["mean"] < WEAK_MEAN and p.get("optimization") is None]
        optimizing = any((p.get("optimization") or {}).get("status") == "running" for p in preds)
        if st.get("optimize_skipped"):
            _set(steps, "optimize", "skipped", "You skipped it.")
        elif optimizing:
            _set(steps, "optimize", "running", "Rewriting weak copy and checking it again.", action={"screen": "dashboard", "id": cid})
            return _view(run, steps)
        elif st.get("optimize_confirmed"):
            _set(steps, "optimize", "done", "Weak copy rewritten. See before and after on the dashboard.", action={"screen": "dashboard", "id": cid})
        elif weak:
            names = ", ".join(sorted({f"{p['channel'].replace('_', ' ')} ({p['lang']})" for p in weak}))
            _set(steps, "optimize", "needs_you", f"Personas found {len(weak)} weak asset(s): {names}. Rewrite them?",
                 gate="confirm", can_skip=True)
            return _view(run, steps)
        else:
            _set(steps, "optimize", "skipped", "No copy scored under 7, nothing to improve.")

        # 8 approve (human)
        approvable = [a for a in db.assets_for(cid) if a["status"] != "blocked"]
        pending = [a for a in approvable if a["status"] != "approved"]
        if pending:
            _set(steps, "approve", "needs_you", f"{len(pending)} of {len(approvable)} assets wait for your approval."
                 + (f" The panel flagged {st['panel_flagged']}." if st.get("panel_flagged") else ""),
                 action={"screen": "campaign", "id": cid})
            return _view(run, steps)
        _set(steps, "approve", "done", f"All {len(approvable)} assets approved.", action={"screen": "campaign", "id": cid})

        # 9 send (human, optional)
        dash = (await client.get(f"/campaign/{cid}/dashboard")).json()
        sent = dash["totals"]["distributed"]
        if sent:
            _set(steps, "send", "done", f"{sent} asset(s) shared, {dash['totals']['clicks']} click(s) so far.", action={"screen": "dashboard", "id": cid})
        elif st.get("send_skipped"):
            _set(steps, "send", "skipped", "You skipped it.")
        else:
            _set(steps, "send", "needs_you", "Copy, share or email the approved assets. Nothing is sent for you.",
                 action={"screen": "campaign", "id": cid}, can_skip=True)
            return _view(run, steps)

        # 10 results (human, optional): real numbers typed by the owner
        learned = learn_mod.learning(db, cid)
        n = learned["summary"]["assets_with_results"]
        if not n:
            if st.get("results_skipped"):
                _set(steps, "results", "skipped", "You skipped it. The agent will not learn from this campaign.")
                _set(steps, "learn", "skipped", "No results to learn from.")
                _set(steps, "next", "skipped", "Needs results first.")
                return _view(run, steps)
            _set(steps, "results", "needs_you", "When the offer has run, enter people reached and redeemed per asset.",
                 action={"screen": "dashboard", "id": cid}, can_skip=True)
            return _view(run, steps)
        _set(steps, "results", "done", f"{n} asset(s) logged: {learned['summary']['total_redemptions']} redeemed of {learned['summary']['total_reached']} reached.",
             action={"screen": "dashboard", "id": cid})

        # 11 learn
        s = learned["summary"]
        gap = f" Typical gap from the forecast: {s['mean_abs_gap_points']} points." if s["mean_abs_gap_points"] is not None else ""
        head = f"{s['within']} of {s['judged']} assets landed inside the forecast range.{gap}" if s["judged"] else "No logged channel has history to judge against."
        _set(steps, "learn", "done", head + (" " + learned["lessons"][0] if learned["lessons"] else ""), action={"screen": "dashboard", "id": cid})

        # 12 next
        if st.get("next_run_id"):
            _set(steps, "next", "done", "Next campaign drafted. It waits at its own plan lock.", next_run_id=st["next_run_id"])
        elif learned["next_idea"]:
            _set(steps, "next", "needs_you", "Draft the next campaign from what worked? You still lock it, write it and approve it.",
                 gate="confirm", can_skip=False, next_idea=learned["next_idea"])
        return _view(run, steps)
    finally:
        await client.aclose()


def _view(run: dict[str, Any], steps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    st = run["state"]
    ordered = [steps[s[0]] for s in STEPS]
    waiting = next((s for s in ordered if s["status"] == "needs_you"), None)
    failed = next((s for s in ordered if s["status"] == "failed"), None)
    live = next((s for s in ordered if s["status"] == "running"), None)
    if failed:
        status = "failed"
    elif waiting:
        status = "needs_you"
    elif live:
        status = "working"
    elif all(s["status"] in ("done", "skipped") for s in ordered):
        status = "done"
    else:
        status = "working"
    return {
        "id": run["id"], "idea": run["idea"], "lang": run["lang"], "status": status,
        "brief": st.get("brief"), "steps": ordered, "campaign_id": st.get("campaign_id"), "session_id": st.get("session_id"),
        "next": {"step": waiting["id"], "message": waiting["detail"]} if waiting else None,
        "budget": st.get("budget"), "created_at": run["created_at"],
    }


def _lock(run_id: str) -> asyncio.Lock:
    return LOCKS.setdefault(run_id, asyncio.Lock())


def _require_key(request: Request) -> None:
    if not text_ready(request.app):
        raise fail("brain_not_configured", "Groq Qwen is off or has no server key.", 503)


@router.post("/agent/runs")
async def create_run(body: RunIn, request: Request) -> dict:
    _require_key(request)
    db: Database = request.app.state.db
    run_id = uuid.uuid4().hex
    db.execute("INSERT INTO agent_run (id, idea, lang, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
               (run_id, body.idea.strip(), body.lang, "{}", now(), now()))
    run = _load(db, run_id)
    async with _lock(run_id):
        view = await tick(request.app, run)
        _save(db, run)
    return view


@router.get("/agent/runs")
def list_runs(request: Request) -> dict:
    rows = request.app.state.db.query("SELECT id, idea, lang, state, created_at FROM agent_run ORDER BY created_at DESC LIMIT 30")
    return {"runs": [{"id": r["id"], "idea": r["idea"][:120], "lang": r["lang"], "created_at": r["created_at"],
                      "campaign_id": json.loads(r["state"]).get("campaign_id")} for r in rows]}


@router.post("/agent/runs/{run_id}/tick")
async def tick_run(run_id: str, request: Request) -> dict:
    db: Database = request.app.state.db
    run = _load(db, run_id)
    async with _lock(run_id):
        run = _load(db, run_id)  # state may have moved while waiting for the lock
        view = await tick(request.app, run)
        _save(db, run)
    return view


@router.post("/agent/runs/{run_id}/steps/{step}/confirm")
async def confirm(run_id: str, step: str, request: Request) -> dict:
    """Owner says yes to a gated step the agent may then perform. Only 'optimize' has a confirm gate."""
    if step not in ("optimize", "next"):
        raise fail("not_confirmable", "Only the optimize and next steps need a confirmation.", 422)
    db: Database = request.app.state.db
    async with _lock(run_id):
        run = _load(db, run_id)
        cid = run["state"].get("campaign_id")
        if not cid:
            raise fail("too_early", "No campaign yet.", 409)
        if step == "next":
            idea = learn_mod.learning(db, cid)["next_idea"]
            if not idea:
                raise fail("too_early", "Log results first.", 409)
            nid = uuid.uuid4().hex
            db.execute("INSERT INTO agent_run (id, idea, lang, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (nid, idea, run["lang"], "{}", now(), now()))
            new_run = _load(db, nid)
            async with _lock(nid):
                new_view = await tick(request.app, new_run)
                _save(db, new_run)
            run["state"]["next_run_id"] = nid
            _save(db, run)
            view = await tick(request.app, run)
            return {**view, "new_run": new_view}
        client = _client(request.app)
        try:
            r = await client.post(f"/campaign/{cid}/optimize")
        finally:
            await client.aclose()
        if r.status_code >= 400:
            raise fail("optimize_failed", r.text[:200], 409)
        run["state"]["optimize_confirmed"] = True
        _save(db, run)
        return await tick(request.app, run)


@router.post("/agent/runs/{run_id}/steps/{step}/skip")
async def skip(run_id: str, step: str, request: Request) -> dict:
    if step not in ("optimize", "send", "results"):
        raise fail("not_skippable", "Only optimize, send and results can be skipped.", 422)
    db: Database = request.app.state.db
    async with _lock(run_id):
        run = _load(db, run_id)
        run["state"][f"{step}_skipped"] = True
        _save(db, run)
        return await tick(request.app, run)
