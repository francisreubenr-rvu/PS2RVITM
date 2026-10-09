"""persona: pre-launch prediction from synthetic personas, and the optimizer. Contract in PLAN.md.

Every payload carries LABEL. The personas are the seeded synthetic customers from
counter_voice_final_dataset.zip (data/customers.json, copied to data/personas.synthetic.json). A score is an
agnes-3.0-flash opinion given a persona sheet, a proxy for reaction before launch and never a measured result.
"""
from __future__ import annotations

from app.agnes import text_ready

import asyncio
import json
import random
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request

from app import plan, review
from app.agnes import AgnesError
from app.db import Database
from app.media import fail
from app.service import Service, now
from app.worker import parse_json_object, spawn, start_jobs

router = APIRouter()

LABEL = "Pre-launch prediction from synthetic personas"
DATA_FILE = Path(__file__).parent / "data" / "personas.synthetic.json"
DIMENSIONS = ("clarity", "appeal", "trust", "local_feel", "call_to_action")
PERSONAS_PER_ASSET = 5
TARGET_MEAN = 7.0
MAX_LOOPS = 2
# Seconds between checks while the optimizer waits for a rewrite to pass the validator and meaning check.
WAIT_POLL = 1.0
WAIT_TIMEOUT = 900.0

# Plan audience -> dataset segments. Dataset segments: young_family, retired_regular, neighbour_homemaker,
# it_professional, remote_freelancer, college_student, foodie_influencer, north_indian_migrant.
# An audience with no entry here (a custom one) matches nothing; if no audience matches, a seeded pick is used.
AUDIENCE_SEGMENTS = {
    "students": ("college_student",),
    "office_workers": ("it_professional", "remote_freelancer"),
    "families": ("young_family",),
    "regulars": ("retired_regular", "neighbour_homemaker"),
    "tourists": ("north_indian_migrant", "foodie_influencer"),
    "nearby_residents": ("neighbour_homemaker", "retired_regular"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  content TEXT NOT NULL,
  mean REAL NOT NULL,
  dimensions TEXT NOT NULL,
  personas TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(asset_id, seq)
);
CREATE TABLE IF NOT EXISTS optimization (
  asset_id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  status TEXT NOT NULL,
  loops INTEGER NOT NULL DEFAULT 0,
  detail TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prediction_campaign ON prediction(campaign_id);
"""


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


@lru_cache(maxsize=1)
def load_personas() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(DATA_FILE.read_text(encoding="utf-8")))


def _slug(value: str) -> str:
    return str(value).strip().lower().replace(" ", "_")


def covers(language_pref: str, lang: str) -> bool:
    """language_pref "hi-en" covers hi and en, "kn-en" covers kn and en, "en" covers en only."""
    return lang in language_pref.split("-")


def pick_personas(campaign_id: str, asset: dict[str, Any], audiences: list[str]) -> list[dict[str, Any]]:
    """Five personas for one asset. Each copy carries match: "segment", "language" or "language_fallback".

    Language comes first: only personas whose language_pref covers the asset's language are used while five exist,
    and among them audience-segment matches go first. If fewer than five cover the language, the rest come from
    the closest match (personas who read English) and are marked "language_fallback", never mixed in unmarked.
    When no audience maps to a segment, the order inside each language tier is a seeded shuffle per campaign and language.
    """
    segments = {segment for audience in audiences for segment in AUDIENCE_SEGMENTS.get(_slug(audience), ())}
    seed = f"{asset['id']}" if segments else f"{campaign_id}:{asset['lang']}"
    shuffled = random.Random(seed).sample(list(load_personas()), len(load_personas()))

    def tier(person: dict[str, Any]) -> int:
        if covers(person["language_pref"], asset["lang"]):
            return 0
        return 1 if covers(person["language_pref"], "en") else 2

    shuffled.sort(key=lambda person: (tier(person), person["segment"] not in segments))
    chosen = []
    for person in shuffled[:PERSONAS_PER_ASSET]:
        if tier(person) > 0:
            match = "language_fallback"
        else:
            match = "segment" if person["segment"] in segments else "language"
        chosen.append({**person, "match": match})
    return chosen


def _asset_extra(asset: dict[str, Any]) -> dict[str, Any]:
    raw = asset.get("extra")
    if not raw:
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def score_messages(asset: dict[str, Any], personas: list[dict[str, Any]], business: dict[str, Any]) -> list[dict[str, str]]:
    request = {
        "business": business,
        "asset": {
            "channel": asset["channel"],
            "language_code": asset["lang"],
            "text": asset["content"],
            "extra_fields": _asset_extra(asset),
        },
        "personas": [
            {key: persona[key] for key in (
                "id", "name", "segment", "age", "language_pref", "primary_channel", "avg_spend_inr",
                "visits_per_month", "veg", "cares_about", "offer_sensitivity", "pet_peeves", "preferred_days",
            )}
            for persona in personas
        ],
    }
    shape = {
        "scores": [
            {"persona_id": "<id from personas>", **{dim: {"score": "<integer 1-10>", "reason": "<one short sentence>"} for dim in DIMENSIONS}}
        ]
    }
    return [
        {
            "role": "system",
            "content": (
                "You simulate how synthetic customer personas react to one marketing message before it is sent. "
                "For every persona, score the message from 1 to 10 on clarity, appeal, trust, local_feel and "
                "call_to_action, with a one-sentence reason each that points at the message text and the persona's own "
                "traits or pet peeves. Judge as that person reading the text in the asset's language_code: use their language_pref "
                "to decide how natural, readable and trustworthy it feels to them. Be critical: 7 means good, 10 is rare, and a message that ignores a persona's "
                "pet peeve or language preference scores low. Judge only the text given; do not assume anything about the "
                "business that is not in the input. If you cannot judge a Kannada or Hindi phrase or dialect, say that in the reason "
                "and score it 5; never name a dialect or invent word meanings. Return one JSON object only, exactly in the shape: "
                + json.dumps(shape)
            ),
        },
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ]


def parse_scores(raw: str, personas: list[dict[str, Any]], match_by_id: dict[str, str] | None = None) -> list[dict[str, Any]]:
    match_by_id = match_by_id or {}
    payload = parse_json_object(raw)
    by_id = {persona["id"]: persona for persona in personas}
    results = []
    for item in payload.get("scores") or []:
        persona = by_id.get(item.get("persona_id")) if isinstance(item, dict) else None
        if persona is None:
            continue
        scores: dict[str, dict[str, Any]] = {}
        for dim in DIMENSIONS:
            cell = item.get(dim)
            value = cell.get("score") if isinstance(cell, dict) else None
            reason = cell.get("reason") if isinstance(cell, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 10:
                scores = {}
                break
            scores[dim] = {"score": int(round(value)), "reason": str(reason or "").strip()}
        if scores:
            results.append(
                {
                    "id": persona["id"],
                    "name": persona["name"],
                    "segment": persona["segment"],
                    "language_pref": persona["language_pref"],
                    "match": match_by_id.get(persona["id"]),
                    "synthetic": True,
                    "scores": scores,
                }
            )
    if not results:
        raise ValueError("The model returned no valid persona scores")
    return results


def summarize(results: list[dict[str, Any]]) -> tuple[float, dict[str, float]]:
    dimensions = {
        dim: round(sum(r["scores"][dim]["score"] for r in results) / len(results), 2) for dim in DIMENSIONS
    }
    return round(sum(dimensions.values()) / len(dimensions), 2), dimensions


def latest_prediction(db: Database, asset_id: str) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM prediction WHERE asset_id = ? ORDER BY seq DESC LIMIT 1", (asset_id,))


async def run_predict_job(app: FastAPI, job_id: str) -> bool:
    """Score one asset with its personas. Returns True when a prediction was stored."""
    db = app.state.db
    job = db.job_get(job_id)
    if not job or job["status"] != "queued" or job["kind"] != "predict":
        return False
    payload = json.loads(job["payload"])
    db.job_update(job_id, now(), status="running", detail="Scoring with synthetic personas.")
    try:
        asset = db.asset_get(job["asset_id"])
        if asset is None or not asset["content"]:
            raise ValueError("asset has no copy to score")
        everyone = {persona["id"]: persona for persona in load_personas()}
        personas = [everyone[pid] for pid in payload["persona_ids"]]
        campaign_plan = plan.get_plan(db, job["campaign_id"]) or {}
        business = campaign_plan.get("business") or {}
        messages = score_messages(asset, personas, business)
        try:
            raw = await app.state.agnes.chat(messages, cache_kind="predict", max_tokens=4000)
            results = parse_scores(raw, personas, payload.get("matches"))
        except (ValueError, json.JSONDecodeError):
            # Malformed JSON happens now and then: ask once more with a stricter reminder before giving up.
            retry = messages + [{"role": "user", "content": "Your last reply was not valid JSON. Reply again with one JSON object only, short reasons, no line breaks inside strings."}]
            raw = await app.state.agnes.chat(retry, cache_kind="predict_retry", max_tokens=4000)
            results = parse_scores(raw, personas, payload.get("matches"))
        mean, dimensions = summarize(results)
        db.execute("DELETE FROM prediction WHERE asset_id = ? AND seq = ?", (asset["id"], payload["seq"]))
        db.execute(
            """
            INSERT INTO prediction (id, asset_id, campaign_id, seq, content, mean, dimensions, personas, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                asset["id"],
                job["campaign_id"],
                payload["seq"],
                asset["content"],
                mean,
                json.dumps(dimensions),
                json.dumps(results, ensure_ascii=False),
                now(),
            ),
        )
        db.job_update(job_id, now(), status="completed", detail=f"Mean {mean} of 10.")
        return True
    except (AgnesError, ValueError, KeyError, json.JSONDecodeError) as exc:
        db.job_update(job_id, now(), status="failed", detail=str(exc)[:500])
        return False


def queue_predict(db: Database, asset: dict[str, Any], audiences: list[str], seq: int) -> dict[str, Any]:
    personas = pick_personas(asset["campaign_id"], asset, audiences)
    return Service(db).queue_job(
        asset,
        "predict",
        has_key=True,
        payload={
            "seq": seq,
            "persona_ids": [persona["id"] for persona in personas],
            "matches": {persona["id"]: persona["match"] for persona in personas},
        },
        detail="Queued for persona scoring.",
    )


def _plan_audiences(db: Database, campaign_id: str) -> list[str]:
    return list((plan.get_plan(db, campaign_id) or {}).get("audiences") or [])


def _scorable(asset: dict[str, Any]) -> str | None:
    """Reason an asset cannot be scored, or None."""
    if not asset["content"]:
        return "not_written"
    if asset["status"] not in ("pending", "approved"):
        return f"status_{asset['status']}"
    meaning = json.loads(asset["review"]) if asset.get("review") else {}
    if meaning.get("status") in review.BLOCKS_APPROVAL:
        return f"meaning_{meaning['status']}"
    return None


def _require_campaign(db: Database, campaign_id: str) -> None:
    if db.campaign_get(campaign_id) is None:
        raise fail("not_found", "No campaign with that id.", 404)


def _require_key(request: Request) -> None:
    if not text_ready(request.app):
        raise fail("brain_not_configured", "Groq Qwen is off or has no server key.", 503)


@router.post("/campaign/{campaign_id}/predict")
async def predict(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    _require_campaign(db, campaign_id)
    _require_key(request)
    audiences = _plan_audiences(db, campaign_id)
    queued: list[str] = []
    skipped: list[dict[str, str]] = []
    for asset in db.assets_for(campaign_id):
        reason = _scorable(asset)
        latest = latest_prediction(db, asset["id"])
        if reason is None and latest and latest["content"] == asset["content"]:
            reason = "already_scored"
        if reason is None and db.job_open_for_asset(asset["id"], "predict"):
            reason = "already_queued"
        if reason:
            skipped.append({"asset_id": asset["id"], "reason": reason})
            continue
        job = queue_predict(db, asset, audiences, 0 if latest is None else latest["seq"] + 1)
        spawn(request.app, run_predict_job(request.app, job["id"]))
        queued.append(asset["id"])
    return {"label": LABEL, "queued": queued, "skipped": skipped}


def feedback_issues(prediction: dict[str, Any]) -> list[str]:
    """The lowest persona reasons, worst first, as problems for the rewrite prompt."""
    found = []
    for persona in json.loads(prediction["personas"]):
        for dim, cell in persona["scores"].items():
            if cell["score"] < TARGET_MEAN and cell["reason"]:
                found.append((cell["score"], f"{dim} {cell['score']}/10 ({persona['segment']} persona): {cell['reason']}"))
    found.sort(key=lambda pair: pair[0])
    return [text for _, text in found[:6]]


def _set_optimization(db: Database, asset: dict[str, Any], status: str, loops: int, detail: str | None) -> None:
    db.execute(
        """
        INSERT INTO optimization (asset_id, campaign_id, status, loops, detail, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_id) DO UPDATE SET status = excluded.status, loops = excluded.loops,
          detail = excluded.detail, updated_at = excluded.updated_at
        """,
        (asset["id"], asset["campaign_id"], status, loops, detail, now()),
    )


async def wait_for_checks(db: Database, asset_id: str, previous: str) -> str | None:
    """Wait until the rewrite and its follow-up jobs settle. Returns None when it passed, else why it did not."""
    waited = 0.0
    while db.job_open_for_asset(asset_id, "copy") or db.job_open_for_asset(asset_id, "review"):
        if waited >= WAIT_TIMEOUT:
            return "the rewrite checks did not finish in time"
        await asyncio.sleep(WAIT_POLL)
        waited += WAIT_POLL
    asset = db.asset_get(asset_id)
    if asset is None or not asset["content"]:
        return "the asset has no copy"
    if asset["content"] == previous:
        return "the rewrite produced no change"
    reason = _scorable(asset)
    if reason is not None or asset["status"] != "pending":
        return f"the rewrite did not pass the checks ({reason or asset['status']})"
    return None


async def optimize_asset(app: FastAPI, asset_id: str) -> None:
    """Up to MAX_LOOPS rewrites of one asset with persona feedback. Each must pass the checks before it is re-scored."""
    db = app.state.db
    service = Service(db)
    audiences = _plan_audiences(db, db.asset_get(asset_id)["campaign_id"])
    row = db.query_one("SELECT loops FROM optimization WHERE asset_id = ?", (asset_id,))
    loops = row["loops"] if row else 0
    while True:
        asset = db.asset_get(asset_id)
        latest = latest_prediction(db, asset_id)
        if latest["mean"] >= TARGET_MEAN:
            _set_optimization(db, asset, "done", loops, f"Mean {latest['mean']} reached the target of {TARGET_MEAN:g}.")
            return
        if loops >= MAX_LOOPS:
            _set_optimization(db, asset, "done", loops, f"Stopped after {MAX_LOOPS} loops at mean {latest['mean']}.")
            return
        loops += 1
        _set_optimization(db, asset, "running", loops, f"Loop {loops}: rewriting with persona feedback.")
        previous = asset["content"]
        job = service.queue_job(
            asset,
            "copy",
            has_key=True,
            payload={"attempt": 0, "source": "optimize", "feedback": {"previous": previous, "issues": feedback_issues(latest)}},
            detail=f"Optimizer loop {loops}: rewriting with persona feedback.",
        )
        start_jobs(app, [job])
        problem = await wait_for_checks(db, asset_id, previous)
        if problem is not None:
            restored, jobs = service.write_content(asset_id, previous, has_key=True)
            start_jobs(app, jobs)
            _set_optimization(db, asset, "stopped", loops, f"Loop {loops}: {problem}. The previous copy was restored.")
            return
        scoring = queue_predict(db, db.asset_get(asset_id), audiences, latest["seq"] + 1)
        if not await run_predict_job(app, scoring["id"]):
            _set_optimization(db, asset, "stopped", loops, f"Loop {loops}: the rewrite could not be re-scored.")
            return


@router.post("/campaign/{campaign_id}/optimize")
async def optimize(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    _require_campaign(db, campaign_id)
    _require_key(request)
    started: list[str] = []
    skipped: list[dict[str, str]] = []
    for asset in db.assets_for(campaign_id):
        latest = latest_prediction(db, asset["id"])
        state = db.query_one("SELECT * FROM optimization WHERE asset_id = ?", (asset["id"],))
        if latest is None:
            reason = "not_scored"
        elif latest["mean"] >= TARGET_MEAN:
            reason = "target_reached"
        elif asset["status"] == "approved":
            reason = "approved_asset_not_rewritten"
        elif state and state["status"] == "running":
            reason = "already_running"
        elif state and state["loops"] >= MAX_LOOPS:
            reason = "loops_exhausted"
        elif latest["content"] != asset["content"]:
            reason = "copy_changed_since_scoring"
        elif db.job_open_for_asset(asset["id"], "copy") or db.job_open_for_asset(asset["id"], "review"):
            reason = "asset_busy"
        else:
            reason = None
        if reason:
            if latest is not None:
                skipped.append({"asset_id": asset["id"], "reason": reason})
            continue
        _set_optimization(db, asset, "running", state["loops"] if state else 0, "Waiting to start.")
        spawn(request.app, optimize_asset(request.app, asset["id"]))
        started.append(asset["id"])
    if not started and not skipped:
        raise fail("no_predictions", "Run the prediction before optimizing.", 409)
    return {"label": LABEL, "started": started, "skipped": skipped}


def prediction_payload(db: Database, asset: dict[str, Any]) -> dict[str, Any] | None:
    rows = db.query("SELECT * FROM prediction WHERE asset_id = ? ORDER BY seq", (asset["id"],))
    if not rows:
        return None
    latest = rows[-1]
    state = db.query_one("SELECT * FROM optimization WHERE asset_id = ?", (asset["id"],))
    return {
        "label": LABEL,
        "asset_id": asset["id"],
        "channel": asset["channel"],
        "lang": asset["lang"],
        "seq": latest["seq"],
        "mean": latest["mean"],
        "dimensions": json.loads(latest["dimensions"]),
        "personas": json.loads(latest["personas"]),
        "history": [
            {"seq": r["seq"], "mean": r["mean"], "dimensions": json.loads(r["dimensions"]), "content": r["content"]}
            for r in rows
        ],
        "optimization": None
        if state is None
        else {"status": state["status"], "loops": state["loops"], "detail": state["detail"]},
    }


def predictions_for_campaign(db: Database, campaign_id: str) -> dict[str, dict[str, Any]]:
    out = {}
    for asset in db.assets_for(campaign_id):
        payload = prediction_payload(db, asset)
        if payload:
            out[asset["id"]] = payload
    return out


@router.get("/campaign/{campaign_id}/predictions")
def predictions(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    _require_campaign(db, campaign_id)
    return {"label": LABEL, "items": list(predictions_for_campaign(db, campaign_id).values())}

