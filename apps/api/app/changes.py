"""changes: change by voice. Propose (classify, ground, dry-run), then apply only after the owner confirms."""
from __future__ import annotations

from app.agnes import text_ready

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import plan as plan_module
from app import speech
from app.agnes import AgnesError
from app.config import CHANNELS, LANGS
from app.db import Database
from app.reply import DEMO_CAMPAIGN_PREFIX
from app.schemas import OfferFacts
from app.service import Service, ServiceError, now
from app.worker import parse_json_object, start_jobs

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS change_proposal (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  data TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

TONE_WORDS = ("funnier", "funny", "warmer", "warm", "formal", "casual", "shorter", "longer", "friendlier", "playful",
              "emoji", "tone", "rewrite", "rephrase", "simpler", "polite", "excited", "serious", "catchy")
SCOPE_VERBS = ("add", "also", "include", "remove", "drop", "skip", "stop", "without", "no more", "delete", "don't need", "dont need")
REMOVE_VERBS = ("remove", "drop", "skip", "stop", "without", "no more", "delete", "don't need", "dont need")
CHANNEL_WORDS = {
    "cold_email": ["email", "e-mail"],
    "instagram_post": ["instagram post", "insta post"],
    "instagram_story": ["story", "stories"],
    "blog_post": ["blog"],
    "whatsapp": ["whatsapp", "whats app"],
    "poster": ["poster"],
    "google_business_post": ["google"],
    "reel": ["reel"],
}
from app import languages

LANG_WORDS = {l["code"]: [l["name"].lower()] for l in languages.LANGUAGES}


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


class ProposeIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _mentioned(text: str, words: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return [key for key, items in words.items() if any(w in low for w in items)]


def _sentence_after_verb(text: str, verbs: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(v in low for v in verbs)


def deterministic_fact_patch(text: str, time_window: str | None) -> tuple[dict[str, Any], str | None]:
    """Number and day changes read straight from the owner's words. Returns (patch, problem)."""
    patch: dict[str, Any] = {}
    last = speech.segments(text)[-1]
    low = last.lower()
    pct = speech.percents(last)
    money = speech.rupees(last)
    if len(set(pct)) > 1 or len(set(money)) > 1:
        return {}, "I heard more than one number. Say it once more."
    if pct:
        patch["discount_percent"] = pct[0]
    if money:
        patch["price_amount"] = money[0]
    if not patch:
        bare = sorted(set(speech.numbers(last)))
        if bare and any(w in low for w in ("price", "cost", "rate", "ಬೆಲೆ", "कीमत", "दाम")):
            if len(bare) > 1:
                return {}, "I heard more than one number. Say it once more."
            patch["price_amount"] = bare[0]
        elif bare and any(w in low for w in ("discount", "off", "ರಿಯಾಯಿತಿ", "छूट")):
            if len(bare) > 1:
                return {}, "I heard more than one number. Say it once more."
            patch["discount_percent"] = bare[0]
        elif bare:
            return {}, "Is that number a price or a percent? Say it again with the word."
    days = speech.read_days(last)
    if days:
        phrase = speech.days_phrase(days)
        patch["timings"] = f"{phrase}, {time_window}" if time_window else phrase
    return patch, None


def deterministic_kind(text: str) -> str | None:
    low = text.lower()
    has_number = bool(speech.numbers(text)) or bool(speech.read_days(text))
    words = _mentioned(text, CHANNEL_WORDS) + _mentioned(text, LANG_WORDS)
    if any(w in low for w in TONE_WORDS) and not has_number:
        return "tone"
    if words and _sentence_after_verb(text, SCOPE_VERBS) and not has_number:
        return "scope"
    if has_number and not any(w in low for w in ("don't touch", "dont touch", "do not touch")):
        return "fact"
    if any(w in low for w in TONE_WORDS):
        return "tone"
    if has_number:
        return "fact"
    return None


def deterministic_scope(text: str) -> dict[str, list[str]]:
    scope = {"add_channels": [], "remove_channels": [], "add_languages": [], "remove_languages": []}
    remove = _sentence_after_verb(text, REMOVE_VERBS)
    for channel in _mentioned(text, CHANNEL_WORDS):
        scope["remove_channels" if remove else "add_channels"].append(channel)
    for lang in _mentioned(text, LANG_WORDS):
        scope["remove_languages" if remove else "add_languages"].append(lang)
    return scope


def classify_messages(text: str) -> list[dict[str, str]]:
    request = {"owner_said": text, "channels": list(CHANNELS), "languages": list(LANGS)}
    return [
        {
            "role": "system",
            "content": (
                "A small business owner asks to change a live campaign. Classify the request. "
                "kind is fact (a price, percent discount or offer weekdays changes), tone (rewrite the wording of "
                "existing posts, no fact changes), scope (add or remove a channel or language), or unclear. "
                "Use only what the owner said; never invent a number or weekday. If they say not to touch a price, it is not a fact change. "
                "Return only JSON with keys: kind, discount_percent (number or null), price_amount (number or null), "
                "days (array from mon,tue,wed,thu,fri,sat,sun,weekend,weekdays,every_day, or null), "
                "target_lang (en|kn|hi or null, for tone), target_channel (a channel or null, for tone), "
                "add_channels, remove_channels, add_languages, remove_languages (arrays, empty when none)."
            ),
        },
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ]


def _ground_patch(ai: dict[str, Any], text: str, time_window: str | None) -> tuple[dict[str, Any], bool]:
    """Keep only the values the owner's words contain. Returns (patch, every proposed value was grounded)."""
    patch: dict[str, Any] = {}
    ok = True
    for key in ("discount_percent", "price_amount"):
        value = ai.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            ok = False
            continue
        if speech.number_grounded(number, text):
            patch[key] = number
        else:
            ok = False
    days = ai.get("days")
    if days:
        if isinstance(days, list) and set(days) <= set(speech.read_days(text)):
            phrase = speech.days_phrase(days)
            patch["timings"] = f"{phrase}, {time_window}" if time_window else phrase
        else:
            ok = False
    return patch, ok


def _filter(values: Any, allowed: tuple[str, ...]) -> list[str]:
    return [v for v in values if v in allowed] if isinstance(values, list) else []


def _tone_targets(db: Database, campaign_id: str, text: str, lang: str | None, channel: str | None) -> list[str]:
    langs = [lang] if lang in LANGS else _mentioned(text, LANG_WORDS)
    chans = [channel] if channel in CHANNELS else _mentioned(text, CHANNEL_WORDS)
    return [
        a["id"] for a in db.assets_for(campaign_id)
        if a["content"] and (not langs or a["lang"] in langs) and (not chans or a["channel"] in chans)
    ]


async def _classify(request: Request, text: str) -> dict[str, Any] | None:
    settings = request.app.state.settings
    if not text_ready(request.app):
        return None
    try:
        raw = await request.app.state.agnes.chat(classify_messages(text), cache_kind="change", temperature=0, max_tokens=500)
        return parse_json_object(raw)
    except (AgnesError, ValueError, json.JSONDecodeError):
        return None


@router.post("/campaign/{campaign_id}/change/propose")
async def propose(campaign_id: str, body: ProposeIn, request: Request) -> dict:
    db = request.app.state.db
    service = Service(db)
    text = body.text.strip()
    if db.campaign_get(campaign_id) is None:
        raise _http(404, "not_found", "No campaign with that id.")
    if db.facts_approved(campaign_id) is None:
        raise _http(409, "facts_not_approved", "Lock the plan before changing it.")
    window = plan_module.time_window(db, campaign_id)
    ai = await _classify(request, text)
    kind = ai.get("kind") if ai else None
    if kind not in ("fact", "tone", "scope"):
        kind = deterministic_kind(text)
    if kind is None:
        raise _http(422, "not_understood", "I could not tell what to change. Name the price, percent, days, tone, channel or language.")

    proposal: dict[str, Any] = {"kind": kind, "text": text, "patch": None, "instruction": None, "scope": None}
    grounded = True
    if kind == "fact":
        patch, grounded = _ground_patch(ai, text, window) if ai else ({}, True)
        if not patch:
            patch, problem = deterministic_fact_patch(text, window)
            grounded = problem is None
            if problem:
                raise _http(422, "not_understood", problem)
        if not patch:
            raise _http(422, "not_understood", "I could not find a price, percent or day in that.")
        try:
            _facts, changed, affected = service.plan_change(campaign_id, patch)
        except ServiceError as exc:
            raise _http(exc.status, exc.code, exc.message) from exc
        proposal["patch"] = patch
        summary = "Change " + ", ".join(f"{k} to {v}" for k, v in patch.items()) + f". {len(affected)} written assets will be rewritten."
        if not changed:
            summary = "That is already what the plan says. Nothing would change."
    elif kind == "tone":
        proposal["instruction"] = text
        lang = ai.get("target_lang") if ai else None
        chan = ai.get("target_channel") if ai else None
        affected = _tone_targets(db, campaign_id, text, lang, chan)
        summary = f"Rewrite {len(affected)} assets with your instruction. Prices, dates and days stay locked."
    else:
        source = ai if ai and any(ai.get(k) for k in ("add_channels", "remove_channels", "add_languages", "remove_languages")) else deterministic_scope(text)
        scope = {
            "add_channels": _filter(source.get("add_channels"), CHANNELS),
            "remove_channels": _filter(source.get("remove_channels"), CHANNELS),
            "add_languages": _filter(source.get("add_languages"), LANGS),
            "remove_languages": _filter(source.get("remove_languages"), LANGS),
        }
        # A channel or language counts only if the owner named it.
        named_channels = set(_mentioned(text, CHANNEL_WORDS) + (["instagram_post"] if "instagram" in text.lower() and "story" not in text.lower() else []))
        named_langs = set(_mentioned(text, LANG_WORDS))
        for key, named in (("add_channels", named_channels), ("remove_channels", named_channels),
                           ("add_languages", named_langs), ("remove_languages", named_langs)):
            kept = [v for v in scope[key] if v in named]
            grounded = grounded and len(kept) == len(scope[key])
            scope[key] = kept
        if not any(scope.values()):
            raise _http(422, "not_understood", "Which channel or language should I add or remove?")
        facts = OfferFacts.model_validate_json(db.facts_approved(campaign_id)["json"])
        gone_channels = [c for c in scope["remove_channels"] if c in facts.channels]
        gone_langs = [x for x in scope["remove_languages"] if x in facts.languages]
        affected = [
            a["id"] for a in db.assets_for(campaign_id)
            if a["channel"] in gone_channels or a["lang"] in gone_langs
        ]
        proposal["scope"] = scope
        parts = [f"{verb} {', '.join(scope[key])}" for verb, key in
                 (("Add", "add_channels"), ("Remove", "remove_channels"), ("Add", "add_languages"), ("Remove", "remove_languages")) if scope[key]]
        summary = "; ".join(parts) + f". {len(affected)} existing assets are removed."
    pid = uuid.uuid4().hex
    proposal.update(affected_asset_ids=affected, summary=summary, grounded=grounded)
    db.execute("INSERT INTO change_proposal (id, campaign_id, data, status, created_at) VALUES (?, ?, ?, 'proposed', ?)",
               (pid, campaign_id, json.dumps(proposal, ensure_ascii=False), now()))
    return {
        "proposal_id": pid,
        "kind": kind,
        "patch": proposal["patch"],
        "instruction": proposal["instruction"],
        "scope": proposal["scope"],
        "affected_asset_ids": affected,
        "summary": summary,
        "grounded": grounded,
    }


@router.post("/campaign/{campaign_id}/change/{pid}/apply")
async def apply(campaign_id: str, pid: str, request: Request) -> dict:
    db = request.app.state.db
    row = db.query_one("SELECT * FROM change_proposal WHERE id = ? AND campaign_id = ?", (pid, campaign_id))
    if row is None:
        raise _http(404, "not_found", "No proposal with that id for this campaign.")
    if row["status"] != "proposed":
        raise _http(409, "already_applied", "That change was already applied.")
    proposal = json.loads(row["data"])
    if not proposal["grounded"]:
        raise _http(409, "not_grounded", "Part of that change was not in your words. Say it again.")
    service = Service(db)
    has_key = text_ready(request.app)
    try:
        if proposal["kind"] == "fact":
            service.apply_change(campaign_id, proposal["text"], proposal["patch"])
            start_jobs(request.app, service.queue_changed(campaign_id, has_key=has_key))
        elif proposal["kind"] == "tone":
            jobs = []
            for asset_id in proposal["affected_asset_ids"]:
                asset = db.asset_get(asset_id)
                if asset is None or not asset["content"] or db.job_open_for_asset(asset_id):
                    continue
                job = service.queue_job(
                    asset, "copy", has_key=has_key,
                    payload={"attempt": 0, "source": "tone", "feedback": {"previous": service.asset_text(asset), "instruction": proposal["instruction"]}},
                    detail="Rewriting to follow your instruction.",
                )
                if has_key:
                    jobs.append(job)
            db.log(now(), "owner", "tone_change", proposal["text"], campaign_id)
            start_jobs(request.app, jobs)
        else:
            scope = proposal["scope"]
            service.apply_scope(campaign_id, proposal["text"], **scope)
            start_jobs(request.app, service.prepare_generation(campaign_id, has_key=has_key))
    except ServiceError as exc:
        raise _http(exc.status, exc.code, exc.message) from exc
    db.execute("UPDATE change_proposal SET status = 'applied' WHERE id = ?", (pid,))
    return service.board(campaign_id)


# ---------------------------------------------------------------- sample data
# The audit trail of the demo campaign, written by scripts/seed_demo.py so the Change Log screen can be walked through.
# Inserted oldest first, so the newest appears at the top where db.events orders by descending id. It is labelled
# "Sample" wherever the demo campaign's id is shown.
DEMO_EVENTS: tuple[dict[str, Any], ...] = (
    {"hours_ago": 49, "actor": "owner", "action": "campaign_created", "detail": "Transcript stored from a walkthrough."},
    {"hours_ago": 48, "actor": "system", "action": "brief_ready", "detail": "Suggested facts are not locked. Review them before approval."},
    {"hours_ago": 47, "actor": "owner", "action": "facts_approved", "detail": "Offer facts v1 locked."},
    {"hours_ago": 46, "actor": "system", "action": "matrix_built", "detail": "6 asset slots added."},
    {"hours_ago": 45, "actor": "system", "action": "copy_written", "detail": "Wrote 6 assets from the locked facts."},
    {"hours_ago": 30, "actor": "owner", "action": "reply_approved", "detail": "Replied to a customer about Sunday."},
    {"hours_ago": 20, "actor": "owner", "action": "tone_change", "detail": "Make the Hindi one warmer and shorter."},
    {"hours_ago": 8, "actor": "system", "action": "change_applied", "detail": "Changed discount_percent to 25. 6 written assets will be rewritten."},
    {"hours_ago": 2, "actor": "owner", "action": "asset_approved", "detail": "WhatsApp copy approved, ready to paste."},
)


def seed_demo_events(db: Database, campaign_id: str) -> int:
    """Replace the sample change-log events in a demo campaign with the fixed set above. Returns how many were written."""
    clear_demo_events(db, campaign_id)
    stamp = datetime.now(timezone.utc)
    for row in DEMO_EVENTS:
        db.log((stamp - timedelta(hours=row["hours_ago"])).isoformat(), row["actor"], row["action"], row["detail"], campaign_id)
    return len(DEMO_EVENTS)


def clear_demo_events(db: Database, campaign_id: str) -> int:
    """Remove the sample change-log events. Only rows whose campaign is the demo campaign are touched."""
    if not str(campaign_id or "").startswith(DEMO_CAMPAIGN_PREFIX):
        return 0
    rows = db.query("SELECT id FROM event_log WHERE campaign_id = ?", (campaign_id,))
    for row in rows:
        db.execute("DELETE FROM event_log WHERE id = ?", (row["id"],))
    return len(rows)
