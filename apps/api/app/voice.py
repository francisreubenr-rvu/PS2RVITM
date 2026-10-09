"""voice: mints an ElevenLabs conversation token for the Talk agent. The key and the agent id never leave the server.

The browser holds only a short-lived token; the agent id is fixed server-side and rides in the query to ElevenLabs only.
The owner's switch in Settings is the consent: with it off, or with no key or agent id set, the route answers 503. This
sits alongside GET /talk/agent (a signed address for the same agent); the token here is what the browser needs to open it.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request

from app import connections, extras
from app.db import Database
from app.lab.voice import elevenlabs
from app.media import fail

router = APIRouter()

# Confirmed live 2026-10-09: GET returns 200 with {"conversation_id", "token"}. The agent id rides in the query only.
TOKEN_URL = "https://api.elevenlabs.io/v1/convai/conversation/token"


def ensure_schema(db: Database) -> None:
    """Nothing to create: minting a token holds no state."""


def _configured() -> bool:
    return bool(elevenlabs.api_key() and elevenlabs.agent_id())


async def conversation_token() -> str:
    """A short-lived token from ElevenLabs. Raises elevenlabs.ElevenLabsError."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(TOKEN_URL, params={"agent_id": elevenlabs.agent_id()}, headers={"xi-api-key": elevenlabs.api_key()})
    if response.status_code >= 400:
        raise elevenlabs._fail(response, "minting a token")
    try:
        token = response.json()["token"]
    except (KeyError, TypeError, ValueError) as exc:
        raise elevenlabs.ElevenLabsError("elevenlabs_failed", "ElevenLabs gave no conversation token.") from exc
    if not isinstance(token, str) or not token:
        raise elevenlabs.ElevenLabsError("elevenlabs_failed", "ElevenLabs gave no conversation token.")
    return token


@router.get("/voice/token")
async def voice_token(request: Request) -> dict[str, Any]:
    """A short-lived conversation token. The key and the agent id stay on the server."""
    connections._require_owner(request)
    if not extras.toggle_state(request.app.state.db, "elevenlabs")["active"] or not _configured():
        raise fail("voice_not_configured", "The ElevenLabs voice is off or has no key. Switch it on in Settings.", 503)
    try:
        token = await conversation_token()
    except elevenlabs.ElevenLabsError as exc:
        raise fail("voice_provider_error", str(exc), exc.status) from exc
    return {"conversation_token": token}


@router.get("/voice/status")
def voice_status(request: Request) -> dict[str, Any]:
    """Configuration only. Checking a microphone does not mint a provider session."""
    connections._require_owner(request)
    available = bool(extras.toggle_state(request.app.state.db, "elevenlabs")["active"] and _configured())
    return {"available": available, "reason": None if available else "not_configured"}
