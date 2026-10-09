"""brain: one in-app reasoning model (Groq) that turns an owner's utterance plus app state into bounded app actions.

The model is told the app's real screens and the routes each action maps to, and it may return only action types the
app can act on. Anything else, or any reply that is not one JSON object, is a bad reply and is never acted on. The model
proposes; every route it names still stops at the owner's own gate (the plan lock, the change confirmation, the asset).
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import extras
from app.config import TEXT_MODEL
from app.db import Database
from app.media import fail
from app.worker import parse_json_object

router = APIRouter()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# One model, fixed. GROQ_CHAT_MODEL wins if set; the default is the app's own reasoning model.
GROQ_MODEL = TEXT_MODEL
# The only action types the app can act on. Anything else is a bad reply, never invented.
ACTION_TYPES = (
    "navigate",
    "set_offer_facts",
    "start_plan",
    "generate_campaign",
    "apply_change",
    "generate_video",
)
# The screens the app really has (Frontend/src/navigation.js), plus change (the Talk screen in change mode).
SCREENS = (
    "home", "voice", "change", "plan", "planner", "campaign", "dashboard", "log", "agent",
    "insights", "memory", "connections", "replies", "customers", "brand", "settings",
    "studio", "launch", "identity", "website", "video", "bakeoff",
)

SYSTEM_PROMPT = (
    "You are GrowIt, the reasoning voice inside a campaign app for small shop owners in India. "
    "Read the owner's utterance and the current app state, then decide the next step. "
    "Reply with exactly one JSON object and nothing else: no prose, no explanation, no code fences. "
    "The object has two keys: say (one short spoken sentence for the owner) and actions (an array, possibly empty). "
    "Each action is an object with keys type and params. type must be one of: " + ", ".join(ACTION_TYPES) + ". "
    "params by type, and the app route each one drives: "
    "navigate -> {\"screen\": one of " + ", ".join(SCREENS) + "} (opens that screen); "
    "set_offer_facts -> {the offer facts the owner stated: item, discount_percent, price_amount, currency, dates, timings, terms, audiences, languages, channels} (fills the offer facts of the current campaign); "
    "start_plan -> {} (POST /campaign/{id}/plan/approve, locks the plan); "
    "generate_campaign -> {} (POST /campaign/generate, writes Campaign 0); "
    "apply_change -> {\"text\": the owner's change instruction} (POST /campaign/{id}/change/propose, proposes the change for a yes); "
    "generate_video -> {\"asset_id\": the reel asset id, \"motion_opt_in\": true} (POST /assets/{id}/video). "
    "Pick only the steps the current state still needs; never repeat a step the state shows is already done. "
    "Never invent offer facts, ids, screens or action types. "
    "If the owner only asked a question, answer in say and return an empty actions array."
)


class OrchestrateIn(BaseModel):
    utterance: str = Field(min_length=1, max_length=4000)
    state: dict | None = None


class BrainError(Exception):
    pass


class BrainNotConfigured(BrainError):
    pass


class BrainBadReply(BrainError):
    pass


def ensure_schema(db: Database) -> None:
    """Nothing to create: orchestration holds no state."""


def parse_reply(content: Any) -> dict[str, Any]:
    """Strict: the model must return one object with a say string and a bounded action list. Junk raises."""
    if not isinstance(content, str):
        raise BrainBadReply("Groq reply was not text")
    try:
        data = parse_json_object(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise BrainBadReply("Groq reply was not JSON") from exc
    say = data.get("say")
    if not isinstance(say, str):
        raise BrainBadReply("Groq reply had no say string")
    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raise BrainBadReply("Groq reply actions was not a list")
    actions: list[dict[str, Any]] = []
    for action in raw_actions:
        if not isinstance(action, dict):
            raise BrainBadReply("Groq action was not an object")
        kind = action.get("type")
        if kind not in ACTION_TYPES:
            raise BrainBadReply(f"Groq action type {kind!r} is not in the vocabulary")
        params = action.get("params", {})
        if not isinstance(params, dict):
            raise BrainBadReply("Groq action params was not an object")
        actions.append({"type": kind, "params": params})
    return {"say": say, "actions": actions}


def _require_key() -> str:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        raise BrainNotConfigured("GROQ_API_KEY is not set")
    return key


async def orchestrate(utterance: str, state: dict | None) -> dict[str, Any]:
    """Ask Groq for the next step. Raises BrainNotConfigured, BrainBadReply or BrainError."""
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"utterance": utterance, "state": state or {}}, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {_require_key()}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(GROQ_URL, headers=headers, json=payload)
    if response.status_code >= 400:
        raise BrainError(f"Groq {response.status_code}: {response.text[:300]}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BrainBadReply("Groq response had no message content") from exc
    return parse_reply(content)


@router.post("/agent/orchestrate")
async def orchestrate_route(body: OrchestrateIn, request: Request) -> dict[str, Any]:
    if not extras.toggle_state(request.app.state.db, "groq")["active"]:
        raise fail("brain_not_configured", "The Groq model is off or has no key. Switch it on in Settings.", 503)
    try:
        return await orchestrate(body.utterance, body.state)
    except BrainNotConfigured as exc:
        raise fail("brain_not_configured", str(exc), 503) from exc
    except BrainBadReply as exc:
        raise fail("brain_bad_reply", str(exc), 502) from exc
    except BrainError as exc:
        raise fail("brain_provider_error", str(exc), 502) from exc
