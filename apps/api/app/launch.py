"""launch: the "no business yet" path. The OpenRouter GLM planner devises a few pathways from the answers, the owner picks one, and
then ideas, names and taglines come back from GLM 5.3 Flash, ending in a hand-off to the agent.

Everything a model returns here is a suggestion. Costs are model estimates, not advice, and the response says so. Kannada and
Hindi taglines are drafts for a native speaker. The hand-off sentence is composed by code from what the owner picked, so the
agent reads it like any other idea and still stops at the plan lock.

All reasoning steps talk to OpenRouter, and it uses one model: GLM 5.3 Flash (fixed). When OpenRouter is
switched off in Settings or has no key, the route answers 503 "not configured" and the screen says so, rather than inventing a plan.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import TEXT_PROVIDER, TEXT_URL, text_api_key, text_request
from app import brain, extras
from app.agnes import AgnesError
from app.media import fail
from app.worker import parse_json_object

router = APIRouter()


def ensure_schema(db) -> None:
    """Nothing to create."""

TYPES = ("cafe", "restaurant", "bakery", "salon", "boutique", "gym", "clinic", "coaching", "other")
DAY_WORDS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}
DISCLAIMER = "Suggestions from an AI, not advice. Costs are rough estimates: check prices, licences and rules where you live."


class IdeasIn(BaseModel):
    city: str = Field(min_length=2, max_length=80)
    skills: list[str] = Field(default_factory=list, max_length=12)
    budget: str = Field(default="10to50k", max_length=20)  # older callers; newer ones send the per-week amount instead
    amount_per_week: int | None = Field(default=None, ge=0, le=10_000_000)
    hours_per_week: int = Field(default=20, ge=1, le=100)
    avoid: str = Field(default="", max_length=200)
    pathway: str = Field(default="", max_length=120)  # the pathway the owner picked, to keep the ideas inside it


class PathwaysIn(BaseModel):
    city: str = Field(min_length=2, max_length=80)
    skills: list[str] = Field(default_factory=list, max_length=12)
    amount_per_week: int = Field(default=0, ge=0, le=10_000_000)
    hours_per_week: int = Field(default=20, ge=1, le=100)
    avoid: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=80)
    tagline: str = Field(default="", max_length=120)


class NamesIn(BaseModel):
    idea: str = Field(min_length=3, max_length=160)
    city: str = Field(min_length=2, max_length=80)


class HandoffIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    business_type: str = Field(default="other")
    city: str = Field(min_length=2, max_length=80)
    item: str = Field(min_length=2, max_length=100)
    discount_percent: float = Field(gt=0, lt=100)
    days: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["en", "kn"])
    channels: list[str] = Field(default_factory=lambda: ["whatsapp", "poster"])


def _s(value: Any, limit: int = 240) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def clean_ideas(raw: Any) -> list[dict[str, Any]]:
    """Shape and trim the model's ideas. Drops any that lack a title, a reason or a starter menu."""
    out = []
    for n, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        items = []
        for it in item.get("items") or []:
            if isinstance(it, dict) and _s(it.get("name"), 60) and isinstance(it.get("price"), (int, float)) and not isinstance(it.get("price"), bool) and it["price"] > 0:
                items.append({"name": _s(it["name"], 60), "price": int(it["price"])})
        if not (_s(item.get("title"), 90) and _s(item.get("why")) and items):
            continue
        btype = item.get("business_type") if item.get("business_type") in TYPES else "other"
        out.append({"id": f"idea{n}", "title": _s(item["title"], 90), "why": _s(item["why"]), "startup": _s(item.get("startup")),
                    "first_month": _s(item.get("first_month")), "risks": [_s(r, 120) for r in (item.get("risks") or []) if _s(r, 120)][:3],
                    "channels": [_s(c, 30) for c in (item.get("channels") or []) if _s(c, 30)][:4], "business_type": btype, "items": items[:5]})
    return out[:3]


SCRIPTS = {"kn": (0x0C80, 0x0CFF), "hi": (0x0900, 0x097F)}


def script_ok(text: str, lang: str) -> bool:
    """A Kannada or Hindi line may only hold its own script plus plain ASCII. Models sometimes slip in stray scripts."""
    lo, hi = SCRIPTS[lang]
    own = 0
    for ch in text:
        if ch.isalpha() and ord(ch) < 128:
            continue
        if ch.isalpha() or (0x0900 <= ord(ch) <= 0x0DFF):
            if not lo <= ord(ch) <= hi:
                return False
            own += 1
    return own > 0


def clean_names(raw: Any) -> dict[str, Any]:
    names = [_s(n, 40) for n in (raw.get("names") if isinstance(raw, dict) else []) or [] if _s(n, 40)][:6]
    taglines = []
    for n, t in enumerate((raw.get("taglines") if isinstance(raw, dict) else []) or []):
        if isinstance(t, dict) and _s(t.get("en"), 80):
            line = {"id": f"tag{n}", "en": _s(t["en"], 80), "hi": _s(t.get("hi"), 80), "kn": _s(t.get("kn"), 80)}
            for lang in ("hi", "kn"):
                if line[lang] and not script_ok(line[lang], lang):
                    line[lang] = ""  # a line with stray scripts is withheld, not shown as if it were fine
            taglines.append(line)
    return {"names": names, "taglines": taglines[:4]}


def clean_pathways(raw: Any) -> list[dict[str, Any]]:
    """Shape the planner's pathways. Each needs a title, a summary and a reason of its own; the rest is trimmed or dropped.
    Bounded to four, so the screen shows three or four and never a wall of them."""
    out = []
    for n, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        title, summary, why = _s(item.get("title"), 80), _s(item.get("summary"), 240), _s(item.get("why"), 240)
        if not (title and summary and why):
            continue
        out.append({"id": f"path{n}", "title": title, "summary": summary, "why": why,
                    "first_move": _s(item.get("first_move"), 200), "money": _s(item.get("money"), 160),
                    "time": _s(item.get("time"), 80), "risk": _s(item.get("risk"), 140)})
    return out[:4]


async def _ask(request: Request, messages: list[dict[str, str]], kind: str) -> Any:
    if not extras.toggle_state(request.app.state.db, "openrouter")["active"]:
        raise fail("brain_not_configured", "The OpenRouter planner is off or has no key. Switch OpenRouter on in Settings, then try again.", 503)
    return await _qwen(messages[0]["content"], json.loads(messages[1]["content"]), 2200)


async def _qwen(system: str, user: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """One call to the OpenRouter GLM planner. Raises a clear 503 when OpenRouter is off or unkeyed, 502 when it fails or answers junk."""
    key = text_api_key()
    if not key:
        raise fail("brain_not_configured", "The OpenRouter planner has no key on the server. Add one to switch it on.", 503)
    payload = {"model": brain.TEXT_MODEL,  # one fixed model, no model fallback
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
               "temperature": 0.5, "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(brain.TEXT_URL, headers={"Authorization": f"Bearer {key}"}, json=text_request(payload))
    except httpx.HTTPError as exc:
        raise fail("pathways_failed", f"The planner did not answer just now ({type(exc).__name__}). Try again.", 502) from exc
    if response.status_code >= 400:
        raise fail("pathways_failed", f"The planner said {response.status_code}. Try again in a moment.", 502)
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise fail("pathways_failed", "The planner's answer could not be read. Try again.", 502) from exc
    try:
        return parse_json_object(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise fail("pathways_failed", "The planner's answer was not usable. Try again.", 502) from exc


@router.post("/launch/ideas")
async def ideas(body: IdeasIn, request: Request) -> dict:
    shape = {"ideas": [{"title": "<short>", "business_type": "|".join(TYPES), "why": "<one sentence for this person>",
                        "startup": "<rough cost range in rupees and what it covers>", "first_month": "<a modest first-month aim>",
                        "risks": ["<licence, location, season ...>"], "channels": ["<where it sells>"],
                        "items": [{"name": "<product>", "price": "<example price in rupees, integer>"}]}]}
    messages = [
        {"role": "system", "content": (
            "You suggest three small, realistic business ideas for an Indian first-time owner. Fit their skills, the money they can put "
            "in each week, their hours and their avoidances. When the request names a chosen pathway, keep every idea inside that "
            "pathway and consistent with it. Be modest about costs and say what licence or permission may be needed. Each idea needs 3 "
            "starter items with example prices. Return one JSON object only, in this shape: " + json.dumps(shape))},
        {"role": "user", "content": json.dumps(body.model_dump(), ensure_ascii=False)},
    ]
    parsed = await _ask(request, messages, "launch_ideas")
    found = clean_ideas(parsed.get("ideas"))
    if not found:
        raise fail("ideas_failed", "No usable ideas came back. Try again.", 502)
    return {"ideas": found, "disclaimer": DISCLAIMER}


PATHWAY_SHAPE = {"pathways": [{
    "title": "<short name for this direction>",
    "summary": "<what this business is, in one or two plain sentences>",
    "why": "<why it fits this person's skills, weekly money, hours and avoidances>",
    "first_move": "<the very first step they could take this week>",
    "money": "<what their weekly money would cover to start>",
    "time": "<rough hours a week it needs>",
    "risk": "<the one main thing that could go wrong>",
}]}


@router.post("/launch/pathways")
async def pathways(body: PathwaysIn, request: Request) -> dict:
    """The planner step: the moment the form is submitted, OpenRouter GLM turns the answers into three or four pathways to choose from."""
    if not extras.toggle_state(request.app.state.db, "openrouter")["active"]:
        raise fail("brain_not_configured", "The OpenRouter planner is off or has no key. Switch OpenRouter on in Settings, then try again.", 503)
    shape = json.dumps(PATHWAY_SHAPE)
    system = (
        "You are the GrowIt planner for a first-time owner in India who has no business yet. Read their skills, the money they can put "
        "in each week, their hours and what they want to avoid, then devise exactly four distinct business pathways, each a clear "
        "direction they could take. Keep every number modest and in rupees and say what licence or permission a step needs. Do not "
        "invent facts about them beyond what they wrote. Return one JSON object only, in this shape: " + shape)
    found = clean_pathways((await _qwen(system, body.model_dump(), 1800)).get("pathways"))
    if len(found) < 3:  # one more try: the model sometimes leaves a summary or reason out
        found = clean_pathways((await _qwen(system, body.model_dump(), 1800)).get("pathways"))
    if len(found) < 3:
        raise fail("pathways_failed", "No usable pathways came back. Try again.", 502)
    return {"pathways": found, "model": brain.TEXT_MODEL, "disclaimer": DISCLAIMER}


@router.post("/launch/names")
async def names(body: NamesIn, request: Request) -> dict:
    shape = {"names": ["<short memorable name>"], "taglines": [{"en": "<English>", "hi": "<Hindi in Devanagari>", "kn": "<Kannada>"}]}
    messages = [
        {"role": "system", "content": (
            "You suggest business names and taglines for a small Indian business. Give 5 short, easy-to-say names that do not copy a "
            "famous brand, and 3 taglines in English, Hindi and Kannada. Keep taglines plain and warm, no unprovable claims. "
            "Return one JSON object only, in this shape: " + json.dumps(shape))},
        {"role": "user", "content": json.dumps(body.model_dump(), ensure_ascii=False)},
    ]
    out = clean_names(await _ask(request, messages, "launch_names"))
    if not out["names"] or not out["taglines"]:
        raise fail("ideas_failed", "No usable names came back. Try again.", 502)
    return {**out, "needs_native_review": ["hi", "kn"], "disclaimer": "Check that a name is free to use before you print anything."}


@router.post("/launch/handoff")
def handoff(body: HandoffIn) -> dict:
    """Compose the idea sentence for the agent from the owner's own choices. No model involved."""
    langs = {"en": "English", "kn": "Kannada", "hi": "Hindi"}
    chans = {"whatsapp": "WhatsApp", "poster": "poster", "instagram_post": "Instagram post", "instagram_story": "Instagram story"}
    btype = body.business_type if body.business_type in TYPES else "other"
    days = [DAY_WORDS[d] for d in body.days if d in DAY_WORDS]
    pct = int(body.discount_percent) if float(body.discount_percent).is_integer() else body.discount_percent
    text = (f"I run {body.name}, a {btype} in {body.city}. I want to promote an offer: {pct}% off {body.item}"
            + (f" on {' and '.join(days)}" if days else "")
            + f", in {' and '.join(langs.get(l, l) for l in body.languages)}, on {' and '.join(chans.get(c, c) for c in body.channels)}.")
    return {"idea": text, "note": "The agent will ask you who it is for, when it starts and how customers reach you."}
