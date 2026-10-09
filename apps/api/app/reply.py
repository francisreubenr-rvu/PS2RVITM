"""reply: a customer-reply agent that may only answer from the locked facts.

A customer message arrives (pasted from WhatsApp, Instagram or email). The agent drafts a short reply in the customer's
language, or hands the message to the owner. It answers only when
  - the message is not on the sensitive list (refunds, allergies, complaints, legal, bulk orders ...: always the owner),
  - the model says which locked facts it used and they are real fact keys, and
  - the draft passes the same deterministic fact validator as every campaign asset.
Anything else becomes an escalation with a holding reply. Nothing is ever sent: the owner approves, edits or dismisses, then
copies the text. An edited reply is re-checked before it can be approved.
"""
from __future__ import annotations

from app.agnes import text_ready

from app import languages

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import plan
from app.agnes import AgnesError
from app.db import Database
from app.media import fail
from app.schemas import OfferFacts
from app.service import now
from app.validator import validate_content
from app.worker import parse_json_object

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS inquiry (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  lang TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL,
  intent TEXT,
  used TEXT,
  draft TEXT,
  reason TEXT,
  final_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inquiry_campaign ON inquiry(campaign_id);
"""
FACT_KEYS = ("item", "discount_percent", "price_amount", "dates", "timings", "terms", "area", "cta")
# Messages the agent never answers. Matching is on plain words so it costs nothing and cannot be talked around.
SENSITIVE = re.compile(
    r"allerg|gluten|nut free|diabet|pregnan|sick|ill\b|poison|vomit|refund|money back|complain|rude|bad service|cheat|fraud|scam|"
    r"lawyer|legal|police|consumer court|cancel|compensat|bulk|catering|wedding|party of|partner|franchise|job|vacancy|salary|"
    r"collab|sponsor|review|rating|\bnot happy\b|unhappy|angry|worst",
    re.IGNORECASE,
)
HOLDING = {  # Kannada and Hindi are drafts until a native speaker has checked them
    "en": "Thanks for asking! The owner will reply to you personally very soon.",
    "kn": "ಕೇಳಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದ! ಮಾಲೀಕರು ಶೀಘ್ರದಲ್ಲೇ ನಿಮಗೆ ಉತ್ತರಿಸುತ್ತಾರೆ.",
    "hi": "पूछने के लिए धन्यवाद! मालिक जल्द ही आपको खुद जवाब देंगे।",
}
# Sample data lives in its own campaign, whose id carries this prefix (see scripts/seed_demo.py). The Replies screen
# labels every row from such a campaign "Sample", so no one reads it as real customer activity.
DEMO_CAMPAIGN_PREFIX = "demo-"


def is_demo(campaign_id: str | None) -> bool:
    return str(campaign_id or "").startswith(DEMO_CAMPAIGN_PREFIX)



class InquiryIn(BaseModel):
    message: str = Field(min_length=2, max_length=1200)
    channel: str = Field(default="whatsapp", pattern="^(whatsapp|instagram|email|other)$")
    lang: str = Field(default="en", pattern=languages.LANG_PATTERN)


class ApproveIn(BaseModel):
    text: str | None = Field(default=None, max_length=1500)


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


def fact_packet(plan_data: dict[str, Any]) -> dict[str, Any]:
    f = plan_data["offer_facts"]
    cta = (plan_data.get("cta") or {}).get("value")
    packet = {"item": f.get("item"), "discount_percent": f.get("discount_percent"), "price_amount": f.get("price_amount"),
              "dates": f.get("dates") or None, "timings": f.get("timings"), "terms": f.get("terms"),
              "area": plan_data["business"].get("area"), "cta": cta}
    return {k: v for k, v in packet.items() if v not in (None, [], "")}


def reply_messages(message: str, lang: str, packet: dict[str, Any], business: str) -> list[dict[str, str]]:
    shape = {"answerable": "<true only if the facts fully answer the question>", "intent": "<price|timing|offer|terms|location|other>",
             "used": "<list of keys from the facts you used>", "reply": "<short reply, or empty>", "reason": "<why not, if not answerable>"}
    names = {"en": "English", "kn": "Kannada", "hi": "Hindi"}
    return [
        {"role": "system", "content": (
            f"You answer customer messages for {business}. You may use ONLY the facts given. If the facts do not fully answer the "
            "question, set answerable to false and leave reply empty. Never invent prices, dates, times, ingredients, delivery, "
            "stock, booking or policies. Never add numbers that are not in the facts. Keep it to one or two short sentences, "
            f"warm and plain, in {names[lang]} unless the customer wrote in another language, then use theirs. "
            "Return one JSON object only, in this shape: " + json.dumps(shape))},
        {"role": "user", "content": json.dumps({"customer_message": message, "facts": packet}, ensure_ascii=False)},
    ]


def check_reply(text: str, facts: OfferFacts) -> list[str]:
    """Deterministic gate for a reply. Returns problems, empty when it may be offered to the owner."""
    result = validate_content(text, facts)
    # A short reply need not restate every day; every wrong claim still fails.
    problems = [i.message for i in result.issues if i.code != "weekday_missing"]
    return problems


def decide(message: str, raw: str | None, facts: OfferFacts, packet: dict[str, Any]) -> dict[str, Any]:
    """Pure decision from a model reply: answer or escalate, with the reason. No I/O."""
    if SENSITIVE.search(message):
        return {"status": "escalated", "intent": "sensitive", "used": [], "draft": None,
                "reason": "This is the kind of message only the owner should answer."}
    if raw is None:
        return {"status": "escalated", "intent": "other", "used": [], "draft": None, "reason": "The agent could not read this message."}
    try:
        parsed = parse_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        return {"status": "escalated", "intent": "other", "used": [], "draft": None, "reason": "The agent's draft was not usable."}
    used = [k for k in (parsed.get("used") or []) if isinstance(k, str)]
    reply = (parsed.get("reply") or "").strip() if isinstance(parsed.get("reply"), str) else ""
    intent = parsed.get("intent") if isinstance(parsed.get("intent"), str) else "other"
    answerable = parsed.get("answerable")
    if isinstance(answerable, str):  # models sometimes write "true" as a string
        answerable = answerable.strip().lower() in ("true", "yes")
    if answerable is not True or not reply:
        return {"status": "escalated", "intent": intent, "used": [], "draft": None,
                "reason": (parsed.get("reason") or "The locked facts do not answer this.")[:200]}
    if not used or any(k not in packet for k in used):
        return {"status": "escalated", "intent": intent, "used": [], "draft": None,
                "reason": "The draft did not point at a locked fact, so it was not offered."}
    problems = check_reply(reply, facts)
    if problems:
        return {"status": "escalated", "intent": intent, "used": [], "draft": None,
                "reason": "The draft contradicted the locked facts: " + problems[0]}
    return {"status": "drafted", "intent": intent, "used": used, "draft": reply, "reason": None}


def _view(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "campaign_id": row["campaign_id"], "channel": row["channel"], "lang": row["lang"],
            "message": row["message"], "status": row["status"], "intent": row["intent"],
            "used": json.loads(row["used"] or "[]"), "draft": row["draft"], "reason": row["reason"],
            "final_text": row["final_text"], "holding": HOLDING.get(row["lang"], HOLDING["en"]) if row["status"] == "escalated" else None,
            "holding_needs_native_review": row["lang"] != "en", "created_at": row["created_at"],
            "demo": is_demo(row.get("campaign_id"))}


def _require_locked(request: Request, campaign_id: str) -> tuple[dict[str, Any], OfferFacts]:
    db = request.app.state.db
    if db.campaign_get(campaign_id) is None:
        raise fail("not_found", "No campaign with that id.", 404)
    data = plan.get_plan(db, campaign_id)
    if not data or data["status"] != "locked":
        raise fail("not_locked", "Lock the plan first. Replies are written from the locked facts only.", 409)
    return data, OfferFacts.model_validate(data["offer_facts"])


@router.post("/campaign/{campaign_id}/replies")
async def draft_reply(campaign_id: str, body: InquiryIn, request: Request) -> dict:
    data, facts = _require_locked(request, campaign_id)
    db: Database = request.app.state.db
    packet = fact_packet(data)
    raw = None
    if not SENSITIVE.search(body.message):  # no model call for messages the agent will not answer
        if not text_ready(request.app):
            raise fail("brain_not_configured", "Groq Qwen is off or has no server key.", 503)
        try:
            raw = await request.app.state.agnes.chat(reply_messages(body.message, body.lang, packet, data["business"]["name"]),
                                                     cache_kind="reply", temperature=0, max_tokens=600)
        except AgnesError:
            raw = None
    verdict = decide(body.message, raw, facts, packet)
    row = {"id": uuid.uuid4().hex, "campaign_id": campaign_id, "channel": body.channel, "lang": body.lang, "message": body.message.strip(),
           "status": verdict["status"], "intent": verdict["intent"], "used": json.dumps(verdict["used"]), "draft": verdict["draft"],
           "reason": verdict["reason"], "final_text": None, "created_at": now(), "updated_at": now()}
    db.execute("INSERT INTO inquiry (id, campaign_id, channel, lang, message, status, intent, used, draft, reason, final_text, created_at, updated_at) "
               "VALUES (:id, :campaign_id, :channel, :lang, :message, :status, :intent, :used, :draft, :reason, :final_text, :created_at, :updated_at)", row)
    return _view(row)


@router.get("/campaign/{campaign_id}/replies")
def list_replies(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    if db.campaign_get(campaign_id) is None:
        raise fail("not_found", "No campaign with that id.", 404)
    rows = db.query("SELECT * FROM inquiry WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 50", (campaign_id,))
    return {"replies": [_view(r) for r in rows]}


@router.post("/replies/{reply_id}/approve")
def approve_reply(reply_id: str, body: ApproveIn, request: Request) -> dict:
    """Marks the text ready to copy. An edited text must pass the fact check again. Nothing is sent."""
    db: Database = request.app.state.db
    row = db.query_one("SELECT * FROM inquiry WHERE id = ?", (reply_id,))
    if row is None:
        raise fail("not_found", "No such reply.", 404)
    data = plan.get_plan(db, row["campaign_id"])
    if not data:
        raise fail("not_found", "No plan for this campaign.", 404)
    text = (body.text or row["draft"] or "").strip()
    if not text:
        raise fail("no_text", "Write the reply yourself, then approve it.", 422)
    problems = check_reply(text, OfferFacts.model_validate(data["offer_facts"]))
    if problems:
        raise fail("facts_mismatch", "That reply does not match the locked facts: " + problems[0], 422)
    db.execute("UPDATE inquiry SET status = 'approved', final_text = ?, updated_at = ? WHERE id = ?", (text, now(), reply_id))
    return _view(db.query_one("SELECT * FROM inquiry WHERE id = ?", (reply_id,)))


@router.post("/replies/{reply_id}/dismiss")
def dismiss_reply(reply_id: str, request: Request) -> dict:
    db: Database = request.app.state.db
    if db.query_one("SELECT id FROM inquiry WHERE id = ?", (reply_id,)) is None:
        raise fail("not_found", "No such reply.", 404)
    db.execute("UPDATE inquiry SET status = 'dismissed', updated_at = ? WHERE id = ?", (now(), reply_id))
    return _view(db.query_one("SELECT * FROM inquiry WHERE id = ?", (reply_id,)))


# ---------------------------------------------------------------- sample data
# Written by scripts/seed_demo.py into a demo campaign so the Replies screen can be walked through. Every row is
# returned with demo = True and shown with a "Sample" label. Nothing here is generated by the model or sent anywhere.
DEMO_REPLIES: tuple[dict[str, Any], ...] = (
    {"channel": "whatsapp", "lang": "en", "hours_ago": 1, "status": "drafted", "intent": "offer",
     "message": "Is the 20% off valid on Sunday, or only on Saturday?",
     "used": ["discount_percent", "timings"], "draft": "Yes, the 20% off on filter coffee runs on Saturday and Sunday, 8 am to 11 am.",
     "reason": None, "final_text": None},
    {"channel": "instagram", "lang": "hi", "hours_ago": 3, "status": "drafted", "intent": "offer",
     "message": "क्या यह ऑफर रविवार को भी है?",
     "used": ["discount_percent", "timings"], "draft": "जी हाँ, 20% छूट शनिवार और रविवार, सुबह 8 से 11 बजे तक है।",
     "reason": None, "final_text": None},
    {"channel": "whatsapp", "lang": "kn", "hours_ago": 6, "status": "escalated", "intent": "sensitive",
     "message": "I want a refund for yesterday's order.", "used": [], "draft": None,
     "reason": "This is the kind of message only the owner should answer.", "final_text": None},
    {"channel": "email", "lang": "en", "hours_ago": 26, "status": "escalated", "intent": "other",
     "message": "Is there parking near the cafe?", "used": [], "draft": None,
     "reason": "The locked facts do not answer this.", "final_text": None},
    {"channel": "whatsapp", "lang": "en", "hours_ago": 30, "status": "approved", "intent": "offer",
     "message": "Do you have the offer on Sunday?", "used": ["discount_percent", "timings"],
     "draft": "Yes, 20% off on filter coffee, Saturday and Sunday, 8 am to 11 am.",
     "reason": None, "final_text": "Yes, 20% off on filter coffee, Saturday and Sunday, 8 am to 11 am."},
    {"channel": "other", "lang": "en", "hours_ago": 50, "status": "dismissed", "intent": "other",
     "message": "Hi", "used": [], "draft": None, "reason": "Dismissed by the owner.", "final_text": None},
)


def seed_demo_replies(db: Database, campaign_id: str) -> int:
    """Replace the sample replies in a demo campaign with the fixed set above. Returns how many were written."""
    clear_demo_replies(db, campaign_id)
    stamp = datetime.now(timezone.utc)
    for index, row in enumerate(DEMO_REPLIES):
        ts = (stamp - timedelta(hours=row["hours_ago"])).isoformat()
        db.execute(
            "INSERT INTO inquiry (id, campaign_id, channel, lang, message, status, intent, used, draft, reason, final_text, created_at, updated_at) "
            "VALUES (:id, :campaign_id, :channel, :lang, :message, :status, :intent, :used, :draft, :reason, :final_text, :created_at, :updated_at)",
            {"id": f"{DEMO_CAMPAIGN_PREFIX}reply-{campaign_id}-{index}", "campaign_id": campaign_id, "created_at": ts, "updated_at": ts,
             **{key: row[key] for key in ("channel", "lang", "message", "status", "intent", "draft", "reason", "final_text")},
             "used": json.dumps(row["used"])},
        )
    return len(DEMO_REPLIES)


def clear_demo_replies(db: Database, campaign_id: str) -> int:
    """Remove the sample replies. Only demo rows (id prefix) are touched, so real replies are never lost."""
    rows = db.query("SELECT id FROM inquiry WHERE campaign_id = ? AND id LIKE ?", (campaign_id, DEMO_CAMPAIGN_PREFIX + "%"))
    for row in rows:
        db.execute("DELETE FROM inquiry WHERE id = ?", (row["id"],))
    return len(rows)
