"""panel: a review panel of specialists per asset, with a referee that only reports what a human must look at.

Four reviewers look at each written asset independently:
  facts    deterministic: the validator against the locked offer facts (no model)
  meaning  the existing blind back-translation check (Kannada and Hindi), read from the asset
  tone     a model judges the copy against the tone the owner chose; a concern needs a quote that is really in the copy
  claims   a model lists risky promises (best, guaranteed, health, urgency the facts do not support); each needs a real quote
The referee is code. It merges the verdicts: `clear` when every reviewer agrees the asset is fine, `review` when someone raised a
verified concern, `blocked` when facts or meaning block. It lists disagreements (for example facts fine but a claims concern) so
the owner reads only what needs a human. Model reviewers that fail or return unquotable concerns count as "not checked", never
as approval.
"""
from __future__ import annotations

from app.agnes import text_ready

import asyncio
import json
import re
from typing import Any

from fastapi import APIRouter, FastAPI, Request

from app import plan, review
from app.agnes import AgnesError
from app.db import Database
from app.media import fail
from app.schemas import OfferFacts
from app.service import now
from app.validator import validate_content
from app.worker import parse_json_object, spawn

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS panel_review (
  asset_id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  result TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_panel_campaign ON panel_review(campaign_id);
"""
REVIEWERS = ("facts", "meaning", "tone", "claims")


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _quoted(quote: Any, text: str) -> bool:
    return isinstance(quote, str) and len(quote.strip()) >= 2 and _squash(quote) in _squash(text)


def verdict(reviewer: str, status: str, reason: str = "", quote: str = "") -> dict[str, str]:
    return {"reviewer": reviewer, "verdict": status, "reason": reason, "quote": quote}


def facts_review(content: str, facts: OfferFacts) -> dict[str, str]:
    result = validate_content(content, facts)
    if result.ok:
        return verdict("facts", "ok", "Prices, dates and weekdays match the lock.")
    return verdict("facts", "block", result.issues[0].message)


def meaning_review(asset: dict[str, Any]) -> dict[str, str]:
    raw = asset.get("review")
    state = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    status = state.get("status")
    if status in (review.OK, review.NOT_NEEDED):
        return verdict("meaning", "ok", "Meaning matches the offer." if status == review.OK else "English copy needs no back-translation.")
    if status == review.FLAGGED:
        issues = state.get("issues") or state.get("language_problems") or []
        return verdict("meaning", "block", str(issues[0]) if issues else "The back-translation did not match the offer.")
    return verdict("meaning", "unchecked", "The meaning check has not finished or could not run.")


def _messages(kind: str, content: str, extra_text: str, tone: str, facts: OfferFacts, lang: str) -> list[dict[str, str]]:
    shapes = {
        "tone": {"verdict": "ok | concern", "reason": "<one sentence>", "quote": "<exact phrase from the copy that is off, or empty>"},
        "claims": {"concerns": [{"quote": "<exact risky phrase from the copy>", "type": "superlative|guarantee|health|urgency|comparison|other",
                                 "reason": "<one sentence>"}]},
    }
    tasks = {
        "tone": f"You review marketing copy for TONE. The owner asked for a '{tone}' voice. Say ok unless the copy clearly clashes "
                "with that voice (pushy, stiff, gimmicky, wrong register). A concern must quote the exact phrase that clashes.",
        "claims": "You review marketing copy for RISKY CLAIMS: unprovable superlatives (best, number one), guarantees, health or "
                  "medical claims, urgency or scarcity the facts do not state (only today, last chance, limited stock), and "
                  "comparisons with others. List each with the exact phrase from the copy. If there are none, return an empty list. "
                  "Do not flag the offer facts themselves.",
    }
    return [
        {"role": "system", "content": tasks[kind] + f" The copy is in language code '{lang}'. If you cannot read a phrase in that "
         "language, do not flag it. Return one JSON object only, in this shape: " + json.dumps(shapes[kind])},
        {"role": "user", "content": json.dumps({"copy": content + (" " + extra_text if extra_text else ""), "locked_facts": facts.model_dump()},
                                               ensure_ascii=False)},
    ]


def parse_tone(raw: str, text: str) -> dict[str, str]:
    try:
        parsed = parse_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        return verdict("tone", "unchecked", "The tone reviewer's reply was not usable.")
    if parsed.get("verdict") == "ok":
        return verdict("tone", "ok", str(parsed.get("reason") or "Fits the chosen tone.")[:200])
    quote = parsed.get("quote")
    if parsed.get("verdict") == "concern" and _quoted(quote, text):
        return verdict("tone", "concern", str(parsed.get("reason") or "")[:200], quote.strip())
    # A concern with no real quote cannot be checked, so it is not shown as a finding.
    return verdict("tone", "unchecked", "The tone reviewer raised a concern it could not point to in the copy, so it was ignored.")


def parse_claims(raw: str, text: str) -> dict[str, str]:
    try:
        parsed = parse_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        return verdict("claims", "unchecked", "The claims reviewer's reply was not usable.")
    found = [c for c in (parsed.get("concerns") or []) if isinstance(c, dict) and _quoted(c.get("quote"), text)]
    if not found:
        return verdict("claims", "ok", "No risky promises found.")
    first = found[0]
    more = f" (+{len(found) - 1} more)" if len(found) > 1 else ""
    return verdict("claims", "concern", f"{str(first.get('type') or 'claim')}: {str(first.get('reason') or '')[:160]}{more}", first["quote"].strip())


def referee(verdicts: list[dict[str, str]]) -> dict[str, Any]:
    """Merge reviewer verdicts. Pure code: no model decides who is right."""
    kinds = {v["verdict"] for v in verdicts}
    if "block" in kinds:
        status = "blocked"
    elif "concern" in kinds:
        status = "review"
    elif "unchecked" in kinds:
        status = "incomplete"
    else:
        status = "clear"
    disagreements = []
    for a in verdicts:
        for b in verdicts:
            if a["reviewer"] < b["reviewer"] and {a["verdict"], b["verdict"]} & {"block", "concern"} and {a["verdict"], b["verdict"]} & {"ok"}:
                bad, good = (a, b) if a["verdict"] in ("block", "concern") else (b, a)
                disagreements.append(f"{bad['reviewer']} raised a {bad['verdict']} that {good['reviewer']} did not see")
    return {"status": status, "needs_human": status != "clear", "disagreements": disagreements}


def _extra_text(asset: dict[str, Any]) -> str:
    raw = asset.get("extra")
    try:
        extra = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        extra = {}
    return " ".join(str(extra[k]) for k in ("subject", "headline", "subline", "title") if extra.get(k))


async def review_asset(agnes: Any, asset: dict[str, Any], facts: OfferFacts, tone: str) -> dict[str, Any]:
    content = asset["content"] or ""
    full = content + " " + _extra_text(asset)

    async def ask(kind: str, parse) -> dict[str, str]:
        try:
            raw = await agnes.chat(_messages(kind, content, _extra_text(asset), tone, facts, asset["lang"]),
                                   cache_kind=f"panel_{kind}", temperature=0, max_tokens=700)
        except AgnesError as exc:
            return verdict(kind, "unchecked", f"Reviewer unavailable: {str(exc)[:80]}")
        return parse(raw, full)

    tone_v, claims_v = await asyncio.gather(ask("tone", parse_tone), ask("claims", parse_claims))
    verdicts = [facts_review(content, facts), meaning_review(asset), tone_v, claims_v]
    return {"verdicts": verdicts, **referee(verdicts)}


async def run_panel(app: FastAPI, campaign_id: str) -> None:
    db: Database = app.state.db
    data = plan.get_plan(db, campaign_id)
    if not data:
        return
    facts = OfferFacts.model_validate(data["offer_facts"])
    for asset in db.assets_for(campaign_id):
        if not asset["content"]:
            continue
        digest = review.content_hash(asset["content"] + _extra_text(asset))
        try:
            result = await review_asset(app.state.agnes, asset, facts, data.get("tone") or "friendly")
            status = result["status"]
        except Exception as exc:  # noqa: BLE001 one bad asset must not stop the rest
            result, status = {"verdicts": [], "status": "incomplete", "needs_human": True, "disagreements": [], "error": str(exc)[:120]}, "incomplete"
        db.execute(
            "INSERT INTO panel_review (asset_id, campaign_id, content_hash, status, result, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(asset_id) DO UPDATE SET content_hash=excluded.content_hash, status=excluded.status, result=excluded.result, updated_at=excluded.updated_at",
            (asset["id"], campaign_id, digest, status, json.dumps(result, ensure_ascii=False), now()))


def panel_for(db: Database, campaign_id: str) -> dict[str, Any]:
    rows = {r["asset_id"]: r for r in db.query("SELECT * FROM panel_review WHERE campaign_id = ?", (campaign_id,))}
    items = []
    for asset in db.assets_for(campaign_id):
        row = rows.get(asset["id"])
        if not asset["content"]:
            continue
        stale = bool(row) and row["content_hash"] != review.content_hash(asset["content"] + _extra_text(asset))
        items.append({"asset_id": asset["id"], "channel": asset["channel"], "lang": asset["lang"],
                      "reviewed": row is not None and not stale, "stale": stale,
                      **(json.loads(row["result"]) if row and not stale else {"verdicts": [], "status": "not_run", "needs_human": True, "disagreements": []})})
    done = [i for i in items if i["reviewed"]]
    return {"items": items, "summary": {
        "assets": len(items), "reviewed": len(done), "clear": sum(1 for i in done if i["status"] == "clear"),
        "needs_human": sum(1 for i in done if i["needs_human"])}}


@router.post("/campaign/{campaign_id}/panel")
async def start_panel(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    if db.campaign_get(campaign_id) is None:
        raise fail("not_found", "No campaign with that id.", 404)
    if not plan.get_plan(db, campaign_id):
        raise fail("no_plan", "No plan for this campaign.", 409)
    if not text_ready(request.app):
        raise fail("brain_not_configured", "Groq Qwen is off or has no server key.", 503)
    spawn(request.app, run_panel(request.app, campaign_id))
    return {"started": True}


@router.get("/campaign/{campaign_id}/panel")
def get_panel(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    if db.campaign_get(campaign_id) is None:
        raise fail("not_found", "No campaign with that id.", 404)
    return panel_for(db, campaign_id)
