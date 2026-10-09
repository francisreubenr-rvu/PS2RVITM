"""extras: budget planner, calibration numbers, bring-your-own provider keys, offline Vosk speech-to-text.

Routes here come from the lab core in app/lab (knapsack planner, Vosk adapter, key encryption). Provider keys are
write-only: the API never returns a stored key, only its last four characters.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import wave
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.config import ROOT, TEXT_MODEL
from app import languages
from app.lab.voice import elevenlabs
from app.db import Database
from app.lab.domain.planner import Calibration, solve
from app.lab.security import BlockedUrl, check_custom_base_url, decrypt_key, encrypt_key, last4
from app.lab.voice import groq_stt, vosk_stt

router = APIRouter()

CAPABILITIES = ("text", "image", "video", "stt", "tts")
SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_keys (
    capability TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    base_url TEXT,
    model TEXT,
    key_enc BLOB,
    last4 TEXT,
    updated_at TEXT NOT NULL
)
"""
CALIBRATION_DIR = ROOT / "data" / "calibration"

# Extra services the owner can switch on or off. The key lives in the server's .env; the switch is the owner's consent.
TOGGLES = {
    "groq": {"label": "Groq", "env": "GROQ_API_KEY", "used_for": "Qwen is the only in-app text model: planning, campaign writing, review and Talk. Text is sent to Groq."},
    "gemini": {"label": "Gemini", "env": "GEMINI_API_KEY", "used_for": "The backup for chat replies, and a voice for reading aloud when ElevenLabs is off. Text is sent to Google."},
    "elevenlabs": {"label": "ElevenLabs", "env": "AGNEZ_ELEVENLABS_API_KEY", "alt": ["ELEVENLABS_API_KEY"],
                   "used_for": "GrowIt's voice: reads its replies aloud and turns your speech into text, in every language. Text and audio are sent to ElevenLabs."},
}
TOGGLE_SCHEMA = "CREATE TABLE IF NOT EXISTS service_toggle (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL, updated_at TEXT NOT NULL)"


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)
    db.ensure(TOGGLE_SCHEMA)


def toggle_state(db: Database, name: str) -> dict:
    """configured: a key is set on the server. enabled: the owner's switch (on until they turn it off). active: both."""
    meta = TOGGLES[name]
    row = db.query_one("SELECT enabled FROM service_toggle WHERE name = ?", (name,))
    configured = any((os.environ.get(n) or "").strip() for n in (meta["env"], *meta.get("alt", [])))
    enabled = True if row is None else bool(row["enabled"])
    return {"name": name, "label": meta["label"], "used_for": meta["used_for"], "configured": configured, "enabled": enabled,
            "active": configured and enabled}


def key_override(db: Database, capability: str) -> str | None:
    """A key the owner saved in Settings for an Agnes capability, or None to use the server's .env key."""
    try:
        row = db.query_one("SELECT provider, key_enc FROM provider_keys WHERE capability = ?", (capability,))
    except Exception:  # noqa: BLE001 table missing in a bare test database
        return None
    if row and row["provider"] == "agnes" and row["key_enc"]:
        return decrypt_key(row["key_enc"])
    return None


def _fail(code: str, message: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


# ---------------------------------------------------------------- planner and calibration

class PlannerIn(BaseModel):
    wanted: list[dict[str, Any]] = Field(default_factory=list)
    reel_seconds: int = 0
    reels: int = 0
    limits: dict[str, float] = Field(default_factory=dict)


def _rpm_from_env(calib: Calibration) -> Calibration:
    """The queue throttles to TEXT_RPM, IMAGE_RPM and VIDEO_RPM, so the planner must plan with the same numbers."""
    for kind, name in (("text", "TEXT_RPM"), ("image", "IMAGE_RPM"), ("video", "VIDEO_RPM")):
        try:
            value = float((os.environ.get(name) or "").strip())
        except ValueError:
            continue
        if value > 0:
            calib.rpm = {**calib.rpm, kind: value}
            calib.source = f"{calib.source}, rpm from {name}" if name not in calib.source else calib.source
    return calib


def latest_calibration() -> Calibration:
    """Measured latency from the newest data/calibration/agnes-*.json, else documented defaults. RPM follows the configured limits."""
    files = sorted(CALIBRATION_DIR.glob("agnes-*.json")) if CALIBRATION_DIR.is_dir() else []
    if not files:
        return _rpm_from_env(Calibration())
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        calib = Calibration(source=files[-1].name)
        text = (data.get("latency_s", {}).get("copy_batch") or {}).get("p50")
        image = (data.get("image") or {}).get("seconds")
        calib.latency = {**calib.latency, **({"text": float(text)} if text else {}), **({"image": float(image)} if image else {})}
        return _rpm_from_env(calib)
    except (OSError, ValueError, TypeError):
        return _rpm_from_env(Calibration())


@router.post("/planner/solve")
def planner_solve(body: PlannerIn) -> dict:
    # Images are generated by Agnes here (no uploaded photo), so image channels pay an image-queue charge.
    return solve(body.model_dump(), latest_calibration(), poster_uses_photo=False)


@router.get("/calibration")
def calibration() -> dict:
    calib = latest_calibration()
    return {"source": calib.source, "rpm": calib.rpm, "latency_s": calib.latency}


# ---------------------------------------------------------------- bring-your-own provider keys

class ProviderIn(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    api_key: str | None = Field(default=None, max_length=400)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {"capability": row["capability"], "provider": row["provider"], "base_url": row["base_url"],
            "model": row["model"], "key_set": bool(row["key_enc"]), "last4": row["last4"],
            "updated_at": row["updated_at"]}


@router.get("/settings/providers")
def list_providers(request: Request) -> dict:
    db: Database = request.app.state.db
    saved = {r["capability"]: _public(r) for r in db.query("SELECT * FROM provider_keys")}
    default_key = bool(request.app.state.settings.agnes_api_key)
    out = []
    for cap in CAPABILITIES:
        if cap == "text":
            state = toggle_state(db, "groq")
            out.append({"capability":"text","provider":"groq","model":TEXT_MODEL,"key_set":False,
                        "last4":None,"base_url":None,"updated_at":None,"default":True,
                        "configured":state["configured"],"active":state["active"]})
            continue
        out.append(saved.get(cap) or {"capability": cap, "provider": "agnes" if cap in ("text", "image", "video") else "browser",
                                      "base_url": None, "model": None, "key_set": False, "last4": None,
                                      "updated_at": None, "default": True})
    return {"providers": out, "default_agnes_key_configured": default_key,
            "stt_offline": {"engine": "vosk", "languages": sorted(vosk_stt.available_languages())}}


@router.put("/settings/providers/{capability}")
def save_provider(capability: str, body: ProviderIn, request: Request) -> dict:
    if capability not in CAPABILITIES:
        raise _fail("bad_capability", f"capability must be one of {', '.join(CAPABILITIES)}", 422)
    if capability == "text":
        raise _fail("fixed_text_provider", "Text reasoning uses only server-configured Groq Qwen.", 409)
    if body.base_url:
        try:
            check_custom_base_url(body.base_url)
        except BlockedUrl as exc:
            raise _fail("blocked_url", str(exc), 422) from exc
    db: Database = request.app.state.db
    old = db.query_one("SELECT key_enc, last4 FROM provider_keys WHERE capability = ?", (capability,))
    key_enc, tail = (old["key_enc"], old["last4"]) if old else (None, None)
    if body.api_key:  # a blank key keeps the stored one: keys are write-only, the form cannot send it back
        key_enc, tail = encrypt_key(body.api_key.strip()), last4(body.api_key.strip())
    db.execute(
        "INSERT INTO provider_keys (capability, provider, base_url, model, key_enc, last4, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(capability) DO UPDATE SET provider=excluded.provider, "
        "base_url=excluded.base_url, model=excluded.model, key_enc=excluded.key_enc, last4=excluded.last4, "
        "updated_at=excluded.updated_at",
        (capability, body.provider, body.base_url, body.model, key_enc, tail, datetime.now(timezone.utc).isoformat()),
    )
    return _public(db.query_one("SELECT * FROM provider_keys WHERE capability = ?", (capability,)))


@router.delete("/settings/providers/{capability}")
def reset_provider(capability: str, request: Request) -> dict:
    request.app.state.db.execute("DELETE FROM provider_keys WHERE capability = ?", (capability,))
    return {"capability": capability, "reset": True}


# ---------------------------------------------------------------- service switches

class ToggleIn(BaseModel):
    enabled: bool


@router.get("/settings/toggles")
def list_toggles(request: Request) -> dict:
    return {"toggles": [toggle_state(request.app.state.db, n) for n in TOGGLES]}


@router.put("/settings/toggles/{name}")
def set_toggle(name: str, body: ToggleIn, request: Request) -> dict:
    if name not in TOGGLES:
        raise _fail("unknown_service", f"Unknown service. Choose from {', '.join(TOGGLES)}.", 404)
    db: Database = request.app.state.db
    db.execute("INSERT INTO service_toggle (name, enabled, updated_at) VALUES (?, ?, ?) "
               "ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
               (name, int(body.enabled), datetime.now(timezone.utc).isoformat()))
    return toggle_state(db, name)


# ---------------------------------------------------------------- offline speech-to-text

def stt_engines(db: Database) -> dict[str, str | None]:
    """Which engine would transcribe each language right now: offline Vosk, Groq (if switched on), or none."""
    installed = vosk_stt.available_languages()
    groq_on = toggle_state(db, "groq")["active"]
    if toggle_state(db, "elevenlabs")["active"]:
        return {lang: "elevenlabs" for lang in languages.CODES}
    # Vosk has no Kannada model, so Kannada is Groq or nothing. Every other language: Vosk if a model is installed, else Groq if on.
    return {lang: ("vosk" if lang in installed and lang != "kn" else ("groq" if groq_on else None)) for lang in languages.CODES}


@router.get("/stt/languages")
def stt_languages(request: Request) -> dict:
    db: Database = request.app.state.db
    return {"engine": "vosk", "installed": vosk_stt.available_languages(), "engines": stt_engines(db),
            "groq": {k: toggle_state(db, "groq")[k] for k in ("configured", "enabled", "active")},
            "unsupported": ["kn", "hinglish"] + [c for c in languages.CODES if c != "kn" and c not in vosk_stt.available_languages()],
            "note": "Vosk has no Kannada or Hinglish model. Switch Groq on in Settings, use the browser mic, or type the answer."}


MAX_AUDIO_BYTES = 10 * 1024 * 1024
SILENCE_PEAK = 300  # of 32768. Whisper invents words ("Thank you.") for silence, so quiet audio never reaches it.


def is_silent(wav_bytes: bytes) -> bool:
    """True when a 16-bit WAV never gets louder than a faint hiss. Unreadable audio is not called silent: the engine reports it."""
    import array
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            if w.getsampwidth() != 2:
                return False
            samples = array.array("h")
            samples.frombytes(w.readframes(w.getnframes()))
    except (wave.Error, EOFError):
        return False
    return not samples or max(abs(min(samples)), abs(max(samples))) < SILENCE_PEAK


@router.post("/stt")
async def stt(request: Request, audio: UploadFile = File(...), lang: str = Form("en")) -> dict:
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise _fail("audio_too_large", "That recording is too long. Keep it under about a minute.", 413)
    if is_silent(data):
        return {"text": "", "segments": [], "lang": lang, "provider": "none", "model": None, "latency_ms": 0, "silent": True}
    eleven = toggle_state(request.app.state.db, "elevenlabs")
    if eleven["active"]:
        try:
            return await elevenlabs.transcribe(data, lang)
        except elevenlabs.ElevenLabsError:
            pass  # fall through to the offline model or Groq: the owner still gets their words
    groq = toggle_state(request.app.state.db, "groq")
    # Vosk next (offline, nothing leaves the machine). Groq only for what Vosk cannot do, and only when switched on.
    if groq["active"] and (lang in ("kn", "hinglish") or lang not in vosk_stt.available_languages()):
        try:
            return await groq_stt.transcribe(data, "hi" if lang == "hinglish" else lang, os.environ["GROQ_API_KEY"].strip())
        except groq_stt.GroqError as exc:
            raise _fail("groq_failed", str(exc), 502) from exc
    try:
        # Vosk is CPU-bound; keep the event loop free.
        result = await asyncio.to_thread(vosk_stt.transcribe, data, lang)
    except vosk_stt.Unsupported as exc:
        hint = ""
        if lang in ("kn", "hinglish") or lang not in vosk_stt.available_languages():
            hint = (" Switch Groq on in Settings to transcribe it." if groq["configured"] and not groq["enabled"]
                    else " Add a Groq key to the server to transcribe it." if not groq["configured"] else "")
        raise _fail("stt_unsupported", str(exc) + hint, 422) from exc
    except (ValueError, EOFError, wave.Error) as exc:
        raise _fail("bad_audio", f"Send a 16-bit PCM WAV file ({exc}).", 422) from exc
    # The transcript is only text for the owner to correct. It never writes the locked offer facts.
    return result
