"""brandgen: the owner's brand look. One brand-look image (generated through Agnes, or the owner's own uploaded logo)
and one short brand-look video through the Agnes video model. Jobs are queued and stored exactly like media.py: a row is
created up front, the worker fills it in, and a job only becomes "ready" when real bytes are written to disk. A failure is
recorded as a failure; nothing is invented.

Prompts follow docs/MEDIA_GENERATION_MASTER.md. The rules applied are quoted in the builders below:
  - "Create one landscape product composition using the authorized reference assets." (text-free image plate)
  - "Keep the type area visually quiet. Final offer lettering and logo are added later."
  - "Does the light belong? ... Choose light for actual materials, subject and owner aesthetic." (anti-generic audit)
  - "Describe materials, placement and lighting rather than 'stunning, cinematic, viral'." (concrete nouns/verbs)
  - "Do not add regional symbols simply because the language is Kannada/Hindi."
  - "Only include motion explicitly authorized for the individual scene." (campaign planner block)
  - "For a fully static default, use an approved image plate ... avoiding the unreliability of asking a video model for
    no movement." (so a brand video needs explicit motion permission, the same switch media.py already uses)
  - "Keep offer text/logos outside generative output for deterministic composition." (visual/audio director block)
  - "No standalone STT/TTS/music endpoint found" (capability matrix): the clip is silent, audio is added later.

The owner's own logo upload is theirs: it is stored as-is and served from /media. It is never passed through a model.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Request, UploadFile
from pydantic import BaseModel, Field

from app import connections
from app.agnes import AgnesError
from app.config import VIDEO_MODEL
from app.db import Database
from app.media import TYPE_WORDS, _extension, _png_size, fail, fetch_bytes
from app.service import now
from app.worker import spawn

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS brandgen (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  file TEXT,
  ratio TEXT NOT NULL,
  status TEXT NOT NULL,
  job_id TEXT,
  detail TEXT,
  prompt TEXT,
  video_id TEXT,
  model TEXT,
  width INTEGER,
  height INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brandgen_owner ON brandgen(owner, created_at);
"""

# The image ratios agnes-image-2.5-flash accepts that matter here: a landscape plate and a square mark.
PLATE_RATIO = "16:9"
MARK_RATIO = "1:1"
IMAGE_STYLES = {"plate": PLATE_RATIO, "mark": MARK_RATIO}
# Landscape is the house default (the user requirement), 9:16 is offered for a story.
VIDEO_ASPECTS = ("16:9", "9:16")
VIDEO_SECONDS = 8
# Token Plan allowance per day, shared with media.py; this module counts both tables so a campaign cannot overshoot it.
VIDEO_DAILY_SECONDS = 500
# Seconds. Poll under the 5 RPM video bucket; give up on a task after 10 minutes (same bounds as media.py).
VIDEO_POLL = 12.0
VIDEO_TIMEOUT = 600.0
VIDEO_QUEUE_RETRIES = 5
VIDEO_QUEUE_WAIT = 30.0

MAX_LOGO_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 150 * 1024 * 1024

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA, (("brandgen", "prompt", "TEXT"), ("brandgen", "video_id", "TEXT"), ("brandgen", "model", "TEXT")))


# ---------------------------------------------------------------- helpers

def _configured(request: Request) -> bool:
    """Agnes is usable when the server has a key or the owner saved one in Settings (the same rule as the client)."""
    if request.app.state.settings.agnes_api_key:
        return True
    from app.extras import key_override

    return any(key_override(request.app.state.db, capability) for capability in ("image", "video"))


def _entry(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    ready = row["status"] == "ready" and bool(row["file"])
    return {
        "id": row["id"],
        "kind": row["kind"],
        "source": row["source"],
        "url": f"/media/{row['file']}" if ready else None,
        "ratio": row["ratio"],
        "status": row["status"],
        "job_id": row["job_id"],
        "detail": row["detail"],
        "width": row["width"],
        "height": row["height"],
    }


def _latest(db: Database, owner: str, kind: str, source: str | None = None) -> dict[str, Any] | None:
    if source is None:
        return db.query_one(
            "SELECT * FROM brandgen WHERE owner = ? AND kind = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (owner, kind),
        )
    return db.query_one(
        "SELECT * FROM brandgen WHERE owner = ? AND kind = ? AND source = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (owner, kind, source),
    )


def _profile(db: Database, owner: str) -> dict[str, Any]:
    row = db.query_one("SELECT profile FROM business WHERE owner = ?", (owner,))
    try:
        return json.loads(row["profile"]) if row and row["profile"] else {}
    except json.JSONDecodeError:
        return {}


def _set(db: Database, brand_id: str, **fields: Any) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.execute(f"UPDATE brandgen SET {assignments} WHERE id = ?", tuple(fields.values()) + (brand_id,))


def _clean(text: str) -> str:
    """Drop digits, quote marks and hashes so nothing in the prompt invites the model to render lettering or numbers."""
    return re.sub(r"[\d\"'`“”‘’#]", "", str(text or "")).strip()


def _subject(profile: dict[str, Any], given: str | None) -> str:
    """The thing to picture: the owner's own words, else the first real menu item. Never invented."""
    if given and given.strip():
        return _clean(given)[:120]
    menu = profile.get("menu") or []
    for item in menu:
        name = (item or {}).get("name")
        if name and str(name).strip():
            return _clean(name)[:120]
    return ""


# ---- palette to plain words (real colours in, no hex or digits into the prompt) ----
_HUES = (
    (15, "red"), (45, "orange"), (70, "yellow"), (95, "yellow green"), (150, "green"),
    (190, "teal"), (225, "blue"), (265, "violet"), (300, "magenta"), (345, "red"), (360, "red"),
)


def _hsl(hex_value: str) -> tuple[float, float, float] | None:
    value = str(hex_value or "").lstrip("#")
    if len(value) == 3:
        value = "".join(c + c for c in value)
    if len(value) != 6:
        return None
    try:
        r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    high, low = max(r, g, b), min(r, g, b)
    light = (high + low) / 2
    if high == low:
        return 0.0, 0.0, light
    delta = high - low
    sat = delta / (2 - high - low) if light > 0.5 else delta / (high + low)
    if high == r:
        hue = ((g - b) / delta) % 6
    elif high == g:
        hue = (b - r) / delta + 2
    else:
        hue = (r - g) / delta + 4
    return hue * 60, sat, light


def colour_words(hex_value: str) -> str:
    """A plain description of a real palette colour, e.g. 'deep warm orange'. None of these words are fabricated."""
    parsed = _hsl(hex_value)
    if parsed is None:
        return ""
    hue, sat, light = parsed
    if sat < 0.12:
        tone = "warm grey" if hue < 90 or hue > 300 else "cool grey"
    else:
        tone = next(name for limit, name in _HUES if hue <= limit)
    shade = "deep" if light < 0.25 else "rich" if light < 0.45 else "mid" if light < 0.72 else "light" if light < 0.88 else "pale"
    return f"{shade} {tone}"


_ROLES = (("bg", "background"), ("ink", "text"), ("accent", "accent"), ("soft", "panel"))


def palette_phrase(palette: dict[str, str] | None, palette_name: str | None) -> str:
    """The resolved palette as visible words. The name is the owner's own choice from the palette list."""
    words = []
    for key, label in _ROLES:
        if not palette or not palette.get(key):
            continue
        described = colour_words(palette[key])
        if described:
            words.append(f"a {described} {label}")
    if not words:
        return ""
    phrase = ", ".join(words[:-1]) + (" and " if len(words) > 1 else "") + words[-1]
    if palette_name and palette_name.strip():
        phrase = f"{_clean(palette_name)[:40]}: {phrase}"
    return phrase


def _lighting(palette: dict[str, str] | None) -> str:
    """Light chosen for the actual palette warmth, not a stock golden-hour recipe (anti-generic audit): a warm accent
    gets soft side daylight, a cool one gets even neutral daylight."""
    parsed = _hsl((palette or {}).get("accent", ""))
    warm = parsed is not None and (parsed[0] < 70 or parsed[0] > 300)
    if warm:
        return "Lighting: soft warm daylight from one side, gentle soft shadows, calm contrast."
    return "Lighting: even neutral daylight, soft and undirected, calm contrast."


# ---- prompt builders (docs/MEDIA_GENERATION_MASTER.md) ----

def build_image_prompt(profile: dict[str, Any], *, style: str, subject: str, palette: dict[str, str] | None, palette_name: str | None) -> str:
    """The text-free brand-look plate. Final lettering and the logo are added later by deterministic composition."""
    kind = _clean(TYPE_WORDS.get(profile.get("type") or "", profile.get("type") or "")) or "small local business"
    parts = [f"Create one brand-look photograph for a {kind}."]
    parts.append(f"Subject: {subject}. Use the real thing itself, not a stock stand-in.")
    if style == "mark":
        parts.append("Composition: one simple centred mark on a calm solid ground, generous margin on every side, flat and clean.")
    else:
        parts.append("Composition: one clear focal subject, generous calm space, with quiet room along one side reserved for a wordmark.")
    parts.append(_lighting(palette))
    parts.append("Material: retain the actual surface finish, colour and proportions; no invented features.")
    phrase = palette_phrase(palette, palette_name)
    if phrase:
        parts.append(f"Brand treatment: {phrase}.")
    parts.append("Keep the type area visually quiet. Final lettering and the logo are added later.")
    parts.append("The image contains no text, no letters, no numbers, no logos, no signage and no watermark.")
    return " ".join(parts)


def build_video_prompt(profile: dict[str, Any], *, aspect: str, subject: str, palette: dict[str, str] | None, palette_name: str | None) -> str:
    """The brand-look shot, only reached after motion opt-in. Follows the master doc's video-shot order: subject and
    setting, reference mapping, action and timing, camera, visual style, sound, consistency, overlay area."""
    kind = _clean(TYPE_WORDS.get(profile.get("type") or "", profile.get("type") or "")) or "small local business"
    frame = "vertical" if aspect == "9:16" else "landscape"
    parts = [f"Photorealistic brand-look video for a {kind}."]
    parts.append(f"Subject and setting: {subject}, in the shop's own everyday setting. No invented product, place or customer.")
    parts.append("Reference mapping: no image references are supplied by this adapter; preserve the subject's real materials and proportions.")
    parts.append("Action and timing: over the whole clip, one approved beat only: gentle natural light and material response. No other action.")
    parts.append(
        f"Camera: locked-off {frame} frame. No camera movement, no zoom, no pan, no parallax, no Ken Burns."
    )
    style_bits = ["natural light", "real materials", "shallow depth of field"]
    phrase = palette_phrase(palette, palette_name)
    if phrase:
        style_bits.insert(0, phrase)
    parts.append("Visual style: " + ", ".join(style_bits) + ".")
    parts.append("Sound and rhythm: silent clip. No speech, music or sound effects are generated; approved audio is added later.")
    parts.append("Consistency: keep the subject's real materials, colour and proportions unchanged; quiet room along one side for the wordmark.")
    parts.append("Keep the type area clear for the deterministic wordmark and captions added later.")
    parts.append("The video contains no text, no letters, no numbers, no logos, no signage and no watermark.")
    return " ".join(parts)


# ---------------------------------------------------------------- jobs

async def run_image_job(app, job_id: str) -> None:
    db = app.state.db
    job = db.job_get(job_id)
    if not job or job["status"] != "queued" or job["kind"] != "brand_image":
        return
    payload = json.loads(job["payload"])
    brand_id = payload["brand_id"]
    db.job_update(job_id, now(), status="running", detail="Generating the brand look.")
    _set(db, brand_id, status="generating", detail="Generating the brand look.")
    try:
        body = await app.state.agnes.image(payload["prompt"], size="1K", ratio=payload["ratio"])
        first = (body.get("data") or [{}])[0]
        if first.get("b64_json"):
            data = base64.b64decode(first["b64_json"])
        elif first.get("url"):
            data = await fetch_bytes(first["url"])
        else:
            raise AgnesError("Agnes image response had neither a url nor b64_json")
        extension = _extension(data)
        if extension is None:
            raise AgnesError("Agnes image was not a PNG, JPEG or WebP file")
        file = f"{brand_id}.{extension}"
        (app.state.settings.assets_dir / file).write_bytes(data)
        width, height = _png_size(data)
        _set(db, brand_id, file=file, status="ready", detail=None, width=width, height=height)
        db.job_update(job_id, now(), status="completed", detail="Brand look ready.", provider_ref=body.get("task_id"))
        db.log(now(), "system", "brand_image_ready", f"{payload['ratio']} brand look stored.", None)
    except (AgnesError, ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        _set(db, brand_id, status="failed", detail=str(exc)[:300])
        db.job_update(job_id, now(), status="failed", detail=str(exc)[:500])
        db.log(now(), "system", "brand_image_failed", str(exc)[:500], None)


def _first(body: dict[str, Any], *keys: str) -> Any:
    layers = [body, body.get("data") if isinstance(body.get("data"), dict) else {}]
    for layer in layers:
        for key in keys:
            if layer.get(key):
                return layer[key]
    return None


async def run_video_job(app, job_id: str) -> None:
    db = app.state.db
    job = db.job_get(job_id)
    if not job or job["status"] != "queued" or job["kind"] != "brand_video":
        return
    payload = json.loads(job["payload"])
    brand_id = payload["brand_id"]
    agnes = app.state.agnes
    db.job_update(job_id, now(), status="running", detail="Asking Agnes for the brand video.")
    _set(db, brand_id, status="generating", detail="Asking Agnes for the brand video.")
    try:
        created = None
        for attempt in range(VIDEO_QUEUE_RETRIES + 1):
            try:
                created = await agnes.video(payload["prompt"], seconds=str(VIDEO_SECONDS), aspect_ratio=payload["aspect"])
                break
            except AgnesError as exc:
                if "video_queue_full" not in str(exc) or attempt == VIDEO_QUEUE_RETRIES:
                    raise
                await asyncio.sleep(VIDEO_QUEUE_WAIT)
        video_id = _first(created or {}, "video_id", "id")
        if not video_id:
            raise AgnesError("Agnes did not return a video_id")
        _set(db, brand_id, video_id=str(video_id), detail="Rendering.")
        db.job_update(job_id, now(), provider_ref=str(video_id), detail="Rendering.")
        waited = 0.0
        url = None
        while url is None:
            status = await agnes.video_status(str(video_id))
            state = str(_first(status, "status", "state") or "").lower()
            if state in ("failed", "error", "cancelled", "canceled"):
                raise AgnesError(f"Agnes video {state}: {str(_first(status, 'error', 'message') or '')[:200]}")
            url = _first(status, "url", "video_url")
            if url is None:
                if waited >= VIDEO_TIMEOUT:
                    raise AgnesError("The video was not ready after 10 minutes")
                await asyncio.sleep(VIDEO_POLL)
                waited += VIDEO_POLL
        data = await fetch_bytes(url, MAX_VIDEO_BYTES)
        if len(data) < 1024 or data[4:8] != b"ftyp":
            raise AgnesError("The downloaded video was empty or not an MP4 file")
        file = f"{brand_id}.mp4"
        (app.state.settings.assets_dir / file).write_bytes(data)
        _set(db, brand_id, file=file, status="ready", detail=None)
        db.job_update(job_id, now(), status="completed", detail="Brand video ready.")
        db.log(now(), "system", "brand_video_ready", f"{payload['aspect']} {VIDEO_SECONDS}s brand video stored.", None)
    except (AgnesError, ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        _set(db, brand_id, status="failed", detail=str(exc)[:300])
        db.job_update(job_id, now(), status="failed", detail=str(exc)[:500])
        db.log(now(), "system", "brand_video_failed", str(exc)[:500], None)


# ---------------------------------------------------------------- routes

@router.get("/brandgen")
def get_brandgen(request: Request) -> dict:
    """The owner's current brand look: the latest image, the latest uploaded logo and the latest generated plate, plus
    the latest video. `configured` is false when no Agnes key is available, and the screen shows that honestly."""
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    configured = _configured(request)
    return {
        "configured": configured,
        "image": _entry(_latest(db, owner, "image")),
        "generated": _entry(_latest(db, owner, "image", "generated")),
        "upload": _entry(_latest(db, owner, "image", "upload")),
        "video": _entry(_latest(db, owner, "video")),
        "note": None
        if configured
        else "Agnes is not configured on this server. Add an Agnes key in Settings, or upload a logo you already have.",
    }


class ImageIn(BaseModel):
    style: Literal["plate", "mark"] = "plate"
    subject: str | None = Field(default=None, max_length=120)
    palette: dict[str, str] | None = None
    palette_name: str | None = Field(default=None, max_length=40)


@router.post("/brandgen/image")
async def create_brand_image(body: ImageIn, request: Request) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    if not _configured(request):
        raise fail("agnes_not_configured", "Agnes is not configured on this server. Add a key in Settings.", 409)
    profile = _profile(db, owner)
    subject = _subject(profile, body.subject)
    if not subject:
        raise fail("no_subject", "Add a menu item, or type what to picture, before generating a brand look.", 409)
    open_row = db.query_one(
        "SELECT * FROM brandgen WHERE owner = ? AND kind = 'image' AND source = 'generated' AND status IN ('queued', 'generating')",
        (owner,),
    )
    if open_row:
        return _entry(open_row)
    ratio = IMAGE_STYLES[body.style]
    prompt = build_image_prompt(profile, style=body.style, subject=subject, palette=body.palette, palette_name=body.palette_name)
    brand_id = uuid.uuid4().hex
    job = _queue(db, brand_id, "brand_image", ratio, prompt, "Queued a brand look for Agnes.")
    db.execute(
        """
        INSERT INTO brandgen (id, owner, kind, source, file, ratio, status, job_id, detail, prompt, model, created_at)
        VALUES (?, ?, 'image', 'generated', NULL, ?, 'queued', ?, 'Queued for Agnes.', ?, ?, ?)
        """,
        (brand_id, owner, ratio, job["id"], prompt, None, now()),
    )
    spawn(request.app, run_image_job(request.app, job["id"]))
    return _entry(db.query_one("SELECT * FROM brandgen WHERE id = ?", (brand_id,)))


@router.post("/brandgen/image/upload")
async def upload_logo(file: UploadFile, request: Request) -> dict:
    """The owner's own logo, stored as-is and served from /media. Never sent through a model."""
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise fail("too_large", "The logo must be under 8MB.", 413)
    extension = _extension(data)
    if extension is None:
        raise fail("not_image", "The logo must be a PNG, JPEG or WebP file.", 415)
    brand_id = uuid.uuid4().hex
    stored = f"{brand_id}.{extension}"
    (request.app.state.settings.assets_dir / stored).write_bytes(data)
    width, height = _png_size(data)
    db.execute(
        """
        INSERT INTO brandgen (id, owner, kind, source, file, ratio, status, job_id, detail, prompt, model, width, height, created_at)
        VALUES (?, ?, 'image', 'upload', ?, ?, 'ready', NULL, NULL, NULL, NULL, ?, ?, ?)
        """,
        (brand_id, owner, stored, "1:1", width, height, now()),
    )
    db.log(now(), "owner", "brand_logo_uploaded", "The owner's own logo stored.", None)
    return _entry(db.query_one("SELECT * FROM brandgen WHERE id = ?", (brand_id,)))


class VideoIn(BaseModel):
    motion_opt_in: bool = False
    aspect: Literal["16:9", "9:16"] = "16:9"
    subject: str | None = Field(default=None, max_length=120)
    palette: dict[str, str] | None = None
    palette_name: str | None = Field(default=None, max_length=40)


@router.post("/brandgen/video")
async def create_brand_video(body: VideoIn, request: Request) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    if not body.motion_opt_in:
        raise fail(
            "motion_not_opted_in",
            "A brand video needs explicit motion permission. Without it the still brand-look image is the deliverable.",
            409,
        )
    if not _configured(request):
        raise fail("agnes_not_configured", "Agnes is not configured on this server. Add a key in Settings.", 409)
    profile = _profile(db, owner)
    subject = _subject(profile, body.subject)
    if not subject:
        raise fail("no_subject", "Add a menu item, or type what to picture, before generating a brand video.", 409)
    open_row = db.query_one(
        "SELECT * FROM brandgen WHERE owner = ? AND kind = 'video' AND status IN ('queued', 'generating')",
        (owner,),
    )
    if open_row:
        return _entry(open_row)
    today = now()[:10]
    used = _video_seconds_used(db, today)
    if used + VIDEO_SECONDS > VIDEO_DAILY_SECONDS:
        raise fail("video_budget_exhausted", f"The {VIDEO_DAILY_SECONDS} second daily video allowance is used up.", 409)
    prompt = build_video_prompt(profile, aspect=body.aspect, subject=subject, palette=body.palette, palette_name=body.palette_name)
    brand_id = uuid.uuid4().hex
    job = _queue(db, brand_id, "brand_video", body.aspect, prompt, "Queued a brand video for Agnes.")
    db.execute(
        """
        INSERT INTO brandgen (id, owner, kind, source, file, ratio, status, job_id, detail, prompt, model, created_at)
        VALUES (?, ?, 'video', 'generated', NULL, ?, 'queued', ?, 'Queued for Agnes.', ?, ?, ?)
        """,
        (brand_id, owner, body.aspect, job["id"], prompt, VIDEO_MODEL, now()),
    )
    spawn(request.app, run_video_job(request.app, job["id"]))
    return _entry(db.query_one("SELECT * FROM brandgen WHERE id = ?", (brand_id,)))


def _video_seconds_used(db: Database, today: str) -> int:
    """Seconds already spent today on campaign videos and brand videos together, against the shared daily allowance."""
    total = 0
    for table in ("media", "brandgen"):
        row = db.query_one(
            f"SELECT COUNT(*) AS n FROM {table} WHERE kind = 'video' AND status != 'failed' AND created_at >= ?",
            (today,),
        )
        total += (row["n"] if row else 0) * VIDEO_SECONDS
    return total


def _queue(db: Database, brand_id: str, kind: str, ratio: str, prompt: str, detail: str) -> dict[str, Any]:
    """One job row, shaped like media.py's queue_job. job.kind names the runner; job.asset_id stays NULL (no campaign asset)."""
    job = {
        "id": uuid.uuid4().hex,
        "campaign_id": "",
        "asset_id": None,
        "kind": kind,
        "status": "queued",
        "detail": detail,
        "provider_ref": None,
        "payload": json.dumps({"brand_id": brand_id, "prompt": prompt, "ratio": ratio, "aspect": ratio}),
        "created_at": now(),
        "updated_at": now(),
    }
    db.job_insert(job)
    db.log(now(), "system", f"{kind}_queued", detail, None)
    return job
