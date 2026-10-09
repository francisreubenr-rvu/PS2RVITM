"""videoprompt: the owner's reel brief becomes a refined video prompt, read and edited by the owner, before Agnes is asked
for a video. The refiner is the app's one reasoning model (OpenRouter z-ai/glm-5.3-flash, no model fallback); when
OpenRouter is off in Settings or has no key the route answers 503 brain_not_configured and no prompt is invented.

The rules come from docs/MEDIA_GENERATION_MASTER.md in the PS2RVITM2026-Francis repo and are applied as written. Where each
one is enforced:

  motion is opt-in; no camera move, Ken Burns, parallax     Operating decision; Visual/audio director       -> prompt rule 2, motion text only when opted in
  one visual unit, simple shot, simple timed beats          Research techniques (one unit); Video shot      -> prompt rule 3 (three beats)
  three beats: recognition, offer, action                   Eight-second story and shot grammar             -> beats[3], names fixed
  concrete nouns and verbs, no mood adjectives              Research techniques; Failure remediation       -> prompt rule 4
  every clause changes an observable property               Prompt audit                                    -> prompt rule 4
  Video shot order (subject, action, camera, style, sound,  Prompt templates: Video shot                    -> PROMPT_ORDER, prompt rule 5
    consistency, clear overlay area)
  offer text and logos stay outside generative output       Visual/audio director; Prompt audit             -> prompt rule 6; offer words never reach the model
  nothing invented about product, place, customer, offer    Operating decision; Campaign planner            -> prompt rule 7; only the saved item is supplied
  separate sound direction, no assumed speech or stems      Visual/audio director; Audio pipeline           -> prompt rule 8 (silent or ambience only)
  unresolved fields absent, no placeholders in a prompt     Prompt audit; Application contract              -> clean_refined drops any <...> or {...} field
  positive wording, no negative-prompt syntax               Research techniques (do not transfer)           -> prompt rule 4 and 6
"""
from __future__ import annotations

import asyncio
import shutil
import json
import os
import re
import uuid
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import TEXT_PROVIDER, TEXT_URL, text_api_key, text_request
from app import brain, extras, media, plan
from app.db import Database
from app.media import fail
from app.service import Service, now
from app.worker import parse_json_object, spawn

router = APIRouter()

PROMPT_ORDER = ("subject and setting", "action and timing", "camera", "visual style", "sound", "consistency", "clear overlay area")
BEATS = ("Recognition", "Offer", "Action")
MAX_PROMPT = 1500
MIN_PROMPT = 40
OVERLAY_LINE = "Leave a calm, uncluttered area of the frame for the overlay added later. Surfaces are free of lettering, numbers, logos and signage."

SYSTEM_PROMPT = (
    "You refine one reel brief into one prompt for the Agnes video model. The clip is eight seconds, landscape or portrait as given. "
    "You write the prompt in English, as plain prose, for a small shop in India. You invent nothing.\n"
    "THE RULES YOU MUST FOLLOW (the prompt is rejected if it breaks them):\n"
    "1. Use only what the brief gives you: the offer item, the business type, the area, the tone, the reel script lines. "
    "Never invent a product look, a place, a customer, a testimonial, a price, a date, an offer, a quantity or a result. "
    "The offer words and numbers are stamped by code over the finished video, so they never appear in your prompt.\n"
    "2. Motion is opt-in. If motion_opt_in is false, describe a locked-off, still frame with no camera movement, no zoom, no pan, "
    "no push-in, no parallax and no subject animation, only the natural stillness of the scene. If motion_opt_in is true, allow "
    "only the motion the owner wrote in motion_note, in their words, and nothing else. Never add a camera move or a slow zoom yourself.\n"
    "3. One visual unit, a simple shot, in three timed beats written with words and no digits: Recognition (the real hero product "
    "or one real detail of the brand), Offer (the same product held in a calm composition with room for the offer text), Action "
    "(the authorized closing view that invites a visit). Keep the beats short and in one setting.\n"
    "4. Use concrete nouns and verbs: the material, the surface, the light direction, the framing, the depth of the background. "
    "Do not use mood or hype words such as cinematic, luxury, epic, stunning, premium, viral or beautiful. Every clause must change "
    "something you can see. Remove redundant adjectives. Write what is in the frame, positively; do not write lists of what to avoid.\n"
    "5. Order the prompt as: subject and setting, action and timing, camera, visual style, sound, consistency, clear overlay area. "
    "Light and palette must fit the product and the owner's tone, not a stock recipe.\n"
    "6. Letters, numbers, prices, logos and signage are never drawn by the video model. The frame keeps a calm area where code "
    "stamps the offer text later. Do not ask for any text.\n"
    "7. Do not mention a reference image or audio unless the brief lists one; it lists none.\n"
    "8. Sound: ask for no speech and no vocals. At most a quiet ambience that truly belongs to the setting; no crowd reactions, "
    "no invented customers, no music with singing.\n"
    "9. Leave no placeholders, no angle brackets, no template fields. If something is not in the brief, leave it out.\n"
    "Return exactly one JSON object and nothing else: no prose, no code fences. Keys: "
    "prompt (the full prompt, one paragraph, at most 1200 characters), "
    "beats (exactly three strings, one short sentence each, for Recognition, Offer and Action), "
    "left_out (an array of short strings naming anything you needed but the brief did not give, empty if none)."
)


class RefineIn(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    aspect: Literal["16:9", "9:16"] = "16:9"
    motion_opt_in: bool = False
    motion_note: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=300)


class GenerateIn(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=4000)
    aspect: Literal["16:9", "9:16"] = "16:9"
    motion_opt_in: bool = False


def ensure_schema(db: Database) -> None:
    """Nothing to create: a refined prompt is returned for the owner to read, not stored."""


def _s(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def _fact_numbers(facts: dict[str, Any] | None) -> list[str]:
    """The approved numbers that must never appear in a visual prompt (they are stamped by code)."""
    out: list[str] = []
    for key in ("discount_percent", "price_amount"):
        value = (facts or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(f"{value:g}")
    return out


def leaks(text: str, facts: dict[str, Any] | None) -> str | None:
    """Why a prompt may not go to the video model, or None. Offer figures and currency belong to the stamped overlay."""
    if re.search(r"[₹%$]|\brs\.?\b|\binr\b", text, re.IGNORECASE):
        return "a price or percentage"
    for number in _fact_numbers(facts):
        if re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.])", text):
            return "an offer figure"
    if re.search(r"<[^>]*>|\{[^}]*\}", text):
        return "an unfilled field"
    return None


def clean_refined(raw: Any, facts: dict[str, Any] | None) -> dict[str, Any]:
    """Strict and bounded. Anything that is not the contract is a bad reply and never reaches the owner."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    value = raw.get("prompt")
    prompt = re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""
    if len(prompt) > MAX_PROMPT:
        raise ValueError("prompt exceeds the character limit")
    if len(prompt) < MIN_PROMPT:
        raise ValueError("no prompt")
    beats = raw.get("beats")
    if not isinstance(beats, list) or len(beats) != 3 or not all(isinstance(b, str) and _s(b, 240) for b in beats):
        raise ValueError("beats must be three strings")
    left_out = raw.get("left_out", [])
    if not isinstance(left_out, list) or not all(isinstance(x, str) for x in left_out):
        raise ValueError("left_out must be a list of strings")
    beats = [re.sub(rf"^{name}\s*[:.\-]\s*", "", _s(b, 240), flags=re.IGNORECASE) for name, b in zip(BEATS, beats)]
    left = [x for x in (_s(x, 160) for x in left_out[:6]) if x]
    for text in [prompt, *beats]:
        why = leaks(text, facts)
        if why:
            raise ValueError(f"the prompt carries {why}")
    return {"prompt": prompt, "beats": [{"beat": name, "text": text} for name, text in zip(BEATS, beats)], "left_out": left}


def brief_for(db: Database, asset: dict[str, Any], body: RefineIn) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The owner's brief, gathered from saved data only. Offer words and numbers are not included: code stamps them."""
    campaign_plan = plan.get_plan(db, asset["campaign_id"])
    item = media._item(db, asset["campaign_id"], campaign_plan)  # noqa: SLF001
    if not item:
        raise fail("no_item", "The campaign has no offer item to picture yet.", 409)
    business = (campaign_plan or {}).get("business") or {}
    approved = db.facts_approved(asset["campaign_id"])
    facts = json.loads(approved["json"]) if approved else None
    brief = {
        "offer_item": media._clean(str(item)),  # noqa: SLF001
        "business_type": media._clean(media.TYPE_WORDS.get(business.get("type") or "", business.get("type") or "")) or "small local business",  # noqa: SLF001
        "area": media._clean(business.get("area") or ""),  # noqa: SLF001
        "tone": media.TONE_MOOD.get((campaign_plan or {}).get("tone") or "") or "",
        "script_lines": media._script_lines(asset),  # noqa: SLF001
        "aspect": body.aspect,
        "duration_seconds": media.VIDEO_SECONDS,
        "motion_opt_in": body.motion_opt_in,
        "motion_note": _s(body.motion_note, 300) if body.motion_opt_in else "",
        "owner_note": _s(body.note, 300),
        "references": [],
    }
    return brief, facts


async def ask_model(brief: dict[str, Any]) -> Any:
    """One call to the OpenRouter reasoning model. Raises fail() with the app's codes."""
    key = text_api_key()
    if not key:
        raise fail("brain_not_configured", "The OpenRouter model has no key on the server. Add one to switch it on.", 503)
    payload = {"model": brain.TEXT_MODEL,  # one model only; no model fallback
               "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
               "temperature": 0.4, "max_tokens": 1200, "response_format": {"type": "json_object"}}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(brain.TEXT_URL, headers={"Authorization": f"Bearer {key}"}, json=text_request(payload))
    except httpx.HTTPError as exc:
        raise fail("brain_provider_error", f"The prompt refiner did not answer just now ({type(exc).__name__}). Try again.", 502) from exc
    if response.status_code >= 400:
        raise fail("brain_provider_error", f"The prompt refiner said {response.status_code}. Try again in a moment.", 502)
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise fail("brain_bad_reply", "The prompt refiner's answer could not be read. Try again.", 502) from exc
    try:
        return parse_json_object(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise fail("brain_bad_reply", "The prompt refiner's answer was not usable. Try again.", 502) from exc


@router.post("/video/refine")
async def refine(body: RefineIn, request: Request) -> dict[str, Any]:
    """Refine the reel brief into a prompt the owner reads and edits. Nothing is generated and no video quota is spent."""
    db: Database = request.app.state.db
    if not extras.toggle_state(db, "openrouter")["active"]:
        raise fail("brain_not_configured", "The OpenRouter model is off or has no key. Switch it on in Settings.", 503)
    asset = media.asset_or_404(db, body.asset_id)
    if asset["channel"] != "reel":
        raise fail("no_video_for_channel", "Only reel assets carry a video.", 400)
    brief, facts = brief_for(db, asset, body)
    raw = await ask_model(brief)
    try:
        refined = clean_refined(raw, facts)
    except ValueError as exc:
        if str(exc) != "prompt exceeds the character limit":
            raise fail("brain_bad_reply", f"The refined prompt was rejected: {exc}. Try again.", 502) from exc
        # One bounded rewrite preserves complete clauses instead of cutting the model's text.
        shorter = {**brief, "response_limit": "Rewrite the complete prompt under one thousand characters. Keep subject, static camera, sound, consistency and clear overlay area. Remove redundant descriptions, never cut a word or sentence."}
        try:
            refined = clean_refined(await ask_model(shorter), facts)
        except ValueError as retry_exc:
            raise fail("brain_bad_reply", f"The refined prompt was rejected: {retry_exc}. Try again.", 502) from retry_exc
    return {"asset_id": asset["id"], "model": brain.TEXT_MODEL, "aspect": body.aspect, "motion_opt_in": body.motion_opt_in,
            "order": list(PROMPT_ORDER), **refined}


@router.post("/video/generate")
async def generate(body: GenerateIn, request: Request) -> dict:
    """Queue the Agnes video with the owner's own (refined, edited) prompt. Same gates as POST /assets/{id}/video."""
    db: Database = request.app.state.db
    asset = media.asset_or_404(db, body.asset_id)
    if asset["channel"] != "reel":
        raise fail("no_video_for_channel", "Only reel assets carry a video.", 400)
    if not body.motion_opt_in:
        raise fail("motion_not_opted_in", "Video motion is opt-in. Send motion_opt_in true to generate it.", 409)
    if not request.app.state.settings.agnes_api_key:
        raise fail("agnes_not_configured", "AGNES_API_KEY is not set.", 409)
    prompt = _s(body.prompt, MAX_PROMPT + 400)
    if len(prompt) < MIN_PROMPT:
        raise fail("prompt_too_short", "The prompt is too short to describe a shot. Refine it or write more.", 422)
    approved = db.facts_approved(asset["campaign_id"])
    why = leaks(prompt, json.loads(approved["json"]) if approved else None)
    if why:
        raise fail("prompt_has_offer_text", f"The prompt carries {why}. Offer text is stamped by code, so take it out.", 422)
    open_row = db.query_one("SELECT * FROM media WHERE asset_id = ? AND kind = 'video' AND status IN ('queued', 'generating')", (asset["id"],))
    if open_row:
        return media.entry(open_row)
    used = db.query_one("SELECT COUNT(*) AS n FROM media WHERE kind = 'video' AND status != 'failed' AND created_at >= ?", (now()[:10],))["n"] * media.VIDEO_SECONDS
    if used + media.VIDEO_SECONDS > media.VIDEO_DAILY_SECONDS:
        raise fail("video_budget_exhausted", f"The {media.VIDEO_DAILY_SECONDS} second daily video allowance is used up.", 409)
    if "free of lettering" not in prompt:
        prompt = f"{prompt} {OVERLAY_LINE}"
    media_id = uuid.uuid4().hex
    job = Service(db).queue_job(
        asset, "video", has_key=True,
        payload={"media_id": media_id, "prompt": prompt, "aspect": body.aspect, "model": media.VIDEO_MODEL},
        detail="Queued a video for Agnes.",
    )
    db.execute(
        """
        INSERT INTO media (id, asset_id, campaign_id, kind, file, ratio, status, job_id, detail, model, created_at)
        VALUES (?, ?, ?, 'video', NULL, ?, 'queued', ?, 'Queued for Agnes.', ?, ?)
        """,
        (media_id, asset["id"], asset["campaign_id"], body.aspect, job["id"], media.VIDEO_MODEL, now()),
    )
    spawn(request.app, media.run_video_job(request.app, job["id"]))
    return media.entry(db.query_one("SELECT * FROM media WHERE id = ?", (media_id,)))


class StaticIn(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64)
    render_id: str = Field(min_length=1, max_length=64)
    facts_version: int = Field(ge=1)


async def run_static_job(app, job_id: str) -> None:
    db = app.state.db
    job = db.job_get(job_id)
    if not job or job["status"] != "queued":
        return
    payload = json.loads(job["payload"])
    mid = payload["media_id"]
    db.job_update(job_id, now(), status="running", detail="Holding the approved rendered frame for eight seconds.")
    media._set_media(db, mid, status="generating")
    destination = app.state.settings.assets_dir / f"{mid}.mp4"
    try:
        process = await asyncio.create_subprocess_exec(
            payload["ffmpeg"], "-v", "error", "-nostdin", "-y", "-loop", "1", "-i",
            str(app.state.settings.assets_dir / payload["source"]), "-t", "8", "-r", "24", "-an",
            "-c:v", "libx264", "-crf", "18", "-g", "1", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, error = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise ValueError("Static reel encoding timed out.")
        if process.returncode:
            raise ValueError("Static reel encoding failed: " + error.decode(errors="replace")[-250:])
        current = db.facts_approved(job["campaign_id"])
        if not current or current["version"] != payload["facts_version"]:
            raise ValueError("Offer facts changed while rendering. Generate the reel again.")
        media._set_media(db, mid, file=destination.name, status="ready", width=1280, height=720,
                         detail="Static Agnes image, locally assembled; no animation or audio.")
        db.job_update(job_id, now(), status="completed", detail="Static landscape reel ready.")
    except (ValueError, OSError) as exc:
        media._set_media(db, mid, status="failed", detail=str(exc)[:300])
        db.job_update(job_id, now(), status="failed", detail=str(exc)[:500])


@router.post("/video/static")
async def static_video(body: StaticIn, request: Request) -> dict:
    """Hold the existing canvas-rendered approved frame. No generated motion."""
    db = request.app.state.db
    asset = media.asset_or_404(db, body.asset_id)
    if asset["channel"] != "reel":
        raise fail("no_video_for_channel", "Only reel assets carry a video.", 400)
    approved = db.facts_approved(asset["campaign_id"])
    if not approved or approved["version"] != body.facts_version or asset.get("facts_version") != approved["version"]:
        raise fail("facts_not_approved", "Lock current offer facts before making a reel.", 409)
    frame = db.query_one("SELECT * FROM media WHERE id = ? AND asset_id = ? AND kind = 'final' AND status = 'ready'", (body.render_id, body.asset_id))
    if not frame or not frame["file"] or frame["width"] != 1280 or frame["height"] != 720:
        raise fail("no_rendered_frame", "Render a landscape frame for this reel first.", 409)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise fail("renderer_not_configured", "FFmpeg is required to assemble a static reel.", 503)
    open_row = db.query_one("SELECT * FROM media WHERE asset_id = ? AND kind = 'video' AND status IN ('queued', 'generating')", (body.asset_id,))
    if open_row:
        return media.entry(open_row)
    mid = uuid.uuid4().hex
    job = Service(db).queue_job(asset, "static_video", has_key=True,
        payload={"media_id":mid,"source":frame["file"],"ffmpeg":ffmpeg,"facts_version":approved["version"]}, detail="Assembling the static landscape reel.")
    db.execute("INSERT INTO media (id, asset_id, campaign_id, kind, ratio, status, job_id, detail, created_at) VALUES (?, ?, ?, 'video', '16:9', 'queued', ?, 'Static Agnes image with local assembly.', ?)",
               (mid, body.asset_id, asset["campaign_id"], job["id"], now()))
    spawn(request.app, run_static_job(request.app, job["id"]))
    return media.entry(db.query_one("SELECT * FROM media WHERE id = ?", (mid,)))
