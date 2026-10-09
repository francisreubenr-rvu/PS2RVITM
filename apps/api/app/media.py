"""media: Agnes images for assets, local storage, client-rendered overlay upload. Contract in PLAN.md.

Agnes image request shape, confirmed by live calls on 2026-10-09 (agnes-image-2.5-flash):

    POST {base}/images/generations
    {"model": "agnes-image-2.5-flash", "prompt": "...", "size": "1K", "ratio": "3:4",
     "extra_body": {"response_format": "url"}}

    -> {"data": [{"url": "https://platform-outputs.agnes-ai.space/.../output_<hash>.png",
                  "b64_json": "", "revised_prompt": ""}], "created": <unix>, "task_id": "task_..."}

`size` and `ratio` sit at the top level. `ratio` must be one of 1:1, 3:4, 4:3, 16:9, 9:16, 2:3, 3:2, 21:9;
4:5 is rejected with HTTP 400, so Instagram posts are requested at 3:4 and the client crops to 4:5.
A 1K 3:4 request returned an 864x1152 PNG. The result URL is public (no auth header) and is downloaded
into ASSETS_DIR, then served from GET /media/{file} on the API origin so the client canvas is not tainted.
Reference images (`extra_body.image`) are not used here.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from typing import Any, Literal

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import plan
from app.agnes import AgnesError
from app.config import VIDEO_MODEL
from app.db import Database
from app.service import Service, now
from app.worker import spawn

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  file TEXT,
  ratio TEXT NOT NULL,
  status TEXT NOT NULL,
  job_id TEXT,
  detail TEXT,
  width INTEGER,
  height INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_asset ON media(asset_id);
CREATE INDEX IF NOT EXISTS idx_media_campaign ON media(campaign_id);
"""

# Channel -> Agnes ratio. Channels not listed here carry no image (cold_email, whatsapp, reel).
# "story" is the legacy channel name still present in config.CHANNELS.
CHANNEL_RATIO = {
    "instagram_post": "3:4",
    "instagram_story": "9:16",
    "story": "9:16",
    "blog_post": "16:9",
    "reel": "16:9",
    "poster": "3:4",
    "google_business_post": "4:3",
}
COMPOSITION = {
    "instagram_post": "Square-friendly composition with the subject centred and breathing room on every side.",
    "instagram_story": "Vertical composition, subject in the middle third, calm empty space at the top and bottom.",
    "story": "Vertical composition, subject in the middle third, calm empty space at the top and bottom.",
    "blog_post": "Wide composition, subject off-centre, soft uncluttered background.",
    "reel": "Landscape still photograph, subject on the left with a clear background.",
    "poster": "Single focal subject, generous calm empty space at the top and bottom for a headline.",
    "google_business_post": "Clear subject, tidy background, nothing busy at the edges.",
}
TONE_MOOD = {
    "friendly": "bright, friendly and approachable",
    "warm_local": "warm, homely and rooted in the neighbourhood",
    "playful": "lively, colourful and playful",
    "straightforward": "clean, simple and uncluttered",
}
# Plan.business.type values are slugs; "other" has no useful words in it.
TYPE_WORDS = {"other": "small local business"}

MAX_RENDER_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MEDIA_FILE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|mp4)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "mp4": "video/mp4"}

VIDEO_SECONDS = 8
VIDEO_DAILY_SECONDS = 500  # Token Plan allowance per day
MAX_VIDEO_BYTES = 150 * 1024 * 1024
# Seconds. Poll under the 5 RPM video bucket; give up on a task after 10 minutes.
VIDEO_POLL = 12.0
VIDEO_TIMEOUT = 600.0
# Agnes answers 503 video_queue_full when its shared queue is busy. Retry creating a few times.
VIDEO_QUEUE_RETRIES = 5
VIDEO_QUEUE_WAIT = 30.0


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA, (("media", "model", "TEXT"), ("media", "video_id", "TEXT")))


def fail(code: str, message: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def asset_or_404(db: Database, asset_id: str) -> dict[str, Any]:
    asset = db.asset_get(asset_id)
    if asset is None:
        raise fail("not_found", "No asset with that id.", 404)
    return asset


def entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "url": f"/media/{row['file']}" if row["file"] and row["status"] == "ready" else None,
        "ratio": row["ratio"],
        "status": row["status"],
        "job_id": row["job_id"],
        "detail": row["detail"],
        "width": row["width"],
        "height": row["height"],
    }


def media_for_assets(db: Database, campaign_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in db.query("SELECT * FROM media WHERE campaign_id = ? ORDER BY created_at, rowid", (campaign_id,)):
        out.setdefault(row["asset_id"], []).append(entry(row))
    return out


def _clean(text: str) -> str:
    """Drop digits and quote marks so nothing in the prompt invites the model to render lettering."""
    return re.sub(r"[\d\"'`“”‘’]", "", text).strip()


def _item(db: Database, campaign_id: str, campaign_plan: dict | None) -> str | None:
    approved = db.facts_approved(campaign_id)
    if approved:
        return json.loads(approved["json"]).get("item")
    if campaign_plan:
        return (campaign_plan.get("offer_facts") or {}).get("item")
    return None


def build_prompt(asset: dict[str, Any], item: str, campaign_plan: dict | None) -> str:
    """Text-free image prompt from the item, business type, area and tone. No price, date or wording to render."""
    business = (campaign_plan or {}).get("business") or {}
    kind = _clean(TYPE_WORDS.get(business.get("type") or "", business.get("type") or "")) or "small local business"
    parts = [f"Photorealistic editorial photograph for a {kind}"]
    area = _clean(business.get("area") or "")
    if area:
        parts[0] += f" in {area}, with the everyday look and feel of that neighbourhood"
    parts[0] += "."
    parts.append(f"Subject: {_clean(item)}.")
    mood = TONE_MOOD.get((campaign_plan or {}).get("tone") or "")
    if mood:
        parts.append(f"Mood: {mood}.")
    parts.append(COMPOSITION[asset["channel"]])
    parts.append("Natural light, real materials, shallow depth of field.")
    parts.append("The image contains no text, no letters, no numbers, no logos, no signage, no menus and no watermark.")
    return " ".join(parts)


async def fetch_bytes(url: str, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    if not url.startswith("https://"):
        raise AgnesError("Agnes returned a non-https media URL")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise AgnesError(f"Media download failed with HTTP {response.status_code}")
    if len(response.content) > limit:
        raise AgnesError(f"Media download was larger than {limit // (1024 * 1024)}MB")
    return response.content


def _extension(data: bytes) -> str | None:
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _png_size(data: bytes) -> tuple[int | None, int | None]:
    if data.startswith(PNG_MAGIC) and data[12:16] == b"IHDR" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None, None


def _set_media(db: Database, media_id: str, **fields: Any) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.execute(f"UPDATE media SET {assignments} WHERE id = ?", tuple(fields.values()) + (media_id,))


async def run_image_job(app: FastAPI, job_id: str) -> None:
    db = app.state.db
    job = db.job_get(job_id)
    if not job or job["status"] != "queued" or job["kind"] != "image":
        return
    payload = json.loads(job["payload"])
    media_id = payload["media_id"]
    db.job_update(job_id, now(), status="running", detail="Generating the image.")
    _set_media(db, media_id, status="generating", detail="Generating the image.")
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
        file = f"{media_id}.{extension}"
        (app.state.settings.assets_dir / file).write_bytes(data)
        width, height = _png_size(data)
        _set_media(db, media_id, file=file, status="ready", detail=None, width=width, height=height)
        db.job_update(job_id, now(), status="completed", detail="Image ready.", provider_ref=body.get("task_id"))
        db.log(now(), "system", "image_ready", f"{payload['ratio']} image stored.", job["campaign_id"])
    except (AgnesError, ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        _set_media(db, media_id, status="failed", detail=str(exc)[:300])
        db.job_update(job_id, now(), status="failed", detail=str(exc)[:500])
        db.log(now(), "system", "image_failed", str(exc)[:500], job["campaign_id"])


class ImageIn(BaseModel):
    prompt: str = Field(min_length=40, max_length=1900)


@router.post("/assets/{asset_id}/image")
async def create_image(asset_id: str, request: Request, body: ImageIn | None = None) -> dict:
    db = request.app.state.db
    asset = asset_or_404(db, asset_id)
    ratio = CHANNEL_RATIO.get(asset["channel"])
    if ratio is None:
        raise fail("no_image_for_channel", f"{asset['channel']} assets carry no image.", 400)
    if not request.app.state.settings.agnes_api_key:
        raise fail("agnes_not_configured", "AGNES_API_KEY is not set.", 409)
    open_row = db.query_one(
        "SELECT * FROM media WHERE asset_id = ? AND kind = 'base' AND status IN ('queued', 'generating')",
        (asset_id,),
    )
    if open_row:
        return entry(open_row)
    campaign_plan = plan.get_plan(db, asset["campaign_id"])
    item = _item(db, asset["campaign_id"], campaign_plan)
    if not item:
        raise fail("no_item", "The campaign has no offer item to picture yet.", 409)
    prompt = build_prompt(asset, item, campaign_plan)
    if body is not None:
        from app.videoprompt import leaks, OVERLAY_LINE
        approved = db.facts_approved(asset["campaign_id"])
        why = leaks(body.prompt, json.loads(approved["json"]) if approved else None)
        if why:
            raise fail("prompt_has_offer_text", "Offer text is added by the renderer.", 422)
        prompt = body.prompt + " " + OVERLAY_LINE
    media_id = uuid.uuid4().hex
    job = Service(db).queue_job(
        asset,
        "image",
        has_key=True,
        payload={"media_id": media_id, "prompt": prompt, "ratio": ratio},
        detail="Queued an image for Agnes.",
    )
    db.execute(
        """
        INSERT INTO media (id, asset_id, campaign_id, kind, file, ratio, status, job_id, detail, created_at)
        VALUES (?, ?, ?, 'base', NULL, ?, 'queued', ?, 'Queued for Agnes.', ?)
        """,
        (media_id, asset_id, asset["campaign_id"], ratio, job["id"], now()),
    )
    spawn(request.app, run_image_job(request.app, job["id"]))
    return entry(db.query_one("SELECT * FROM media WHERE id = ?", (media_id,)))


@router.get("/media/{file}")
def serve_media(file: str, request: Request) -> FileResponse:
    if not MEDIA_FILE.match(file):
        raise fail("not_found", "No such media file.", 404)
    assets_dir = request.app.state.settings.assets_dir.resolve()
    path = (assets_dir / file).resolve()
    if path.parent != assets_dir or not path.is_file():
        raise fail("not_found", "No such media file.", 404)
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[file.rsplit(".", 1)[1]],
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/assets/{asset_id}/render")
async def store_render(asset_id: str, file: UploadFile, request: Request) -> dict:
    db = request.app.state.db
    asset = asset_or_404(db, asset_id)
    data = await file.read(MAX_RENDER_BYTES + 1)
    if len(data) > MAX_RENDER_BYTES:
        raise fail("too_large", "The rendered PNG must be under 8MB.", 413)
    width, height = _png_size(data)
    if width is None:
        raise fail("not_png", "The render must be a PNG file.", 415)
    ratio = CHANNEL_RATIO.get(asset["channel"], "1:1")
    media_id = uuid.uuid4().hex
    stored = f"{media_id}.png"
    (request.app.state.settings.assets_dir / stored).write_bytes(data)
    for old in db.query("SELECT * FROM media WHERE asset_id = ? AND kind = 'final'", (asset_id,)):
        if old["file"]:
            (request.app.state.settings.assets_dir / old["file"]).unlink(missing_ok=True)
        db.execute("DELETE FROM media WHERE id = ?", (old["id"],))
    db.execute(
        """
        INSERT INTO media (id, asset_id, campaign_id, kind, file, ratio, status, job_id, detail, width, height, created_at)
        VALUES (?, ?, ?, 'final', ?, ?, 'ready', NULL, NULL, ?, ?, ?)
        """,
        (media_id, asset_id, asset["campaign_id"], stored, ratio, width, height, now()),
    )
    db.log(now(), "owner", "render_stored", f"{asset['lang']} {asset['channel']} final image stored.", asset["campaign_id"])
    return entry(db.query_one("SELECT * FROM media WHERE id = ?", (media_id,)))


# ---- Reel video (P1). Motion is opt-in per request; the default is a locked-off landscape shot. ----


class VideoIn(BaseModel):
    motion_opt_in: bool = False
    aspect: Literal["16:9", "9:16"] = "16:9"


def _script_lines(asset: dict[str, Any]) -> list[str]:
    raw = asset.get("extra")
    try:
        extra = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        extra = {}
    script = extra.get("script") if isinstance(extra, dict) else None
    if isinstance(script, str):
        script = script.splitlines()
    return [line for line in (_clean(str(x)) for x in script or []) if line]


def build_video_prompt(asset: dict[str, Any], item: str, campaign_plan: dict | None) -> str:
    """Static, text-free prompt. The reel script is scene context only and is never to be rendered as lettering."""
    business = (campaign_plan or {}).get("business") or {}
    kind = _clean(TYPE_WORDS.get(business.get("type") or "", business.get("type") or "")) or "small local business"
    opening = f"Photorealistic video of {_clean(item)} for a {kind}"
    area = _clean(business.get("area") or "")
    if area:
        opening += f" in {area}, with the everyday look and feel of that neighbourhood"
    parts = [opening + "."]
    mood = TONE_MOOD.get((campaign_plan or {}).get("tone") or "")
    if mood:
        parts.append(f"Mood: {mood}.")
    lines = _script_lines(asset)
    if lines:
        parts.append("Scene context only, not to be shown as text: " + " ".join(lines))
    parts.append("Natural light, real materials, shallow depth of field.")
    parts.append(
        "Locked-off static camera: no camera movement, no zoom, no pan, no parallax. "
        "Minimal subject motion, at most gentle steam or a soft flicker of light."
    )
    parts.append("The video contains no text, no letters, no numbers, no logos, no signage and no watermark.")
    return " ".join(parts)


def _first(body: dict[str, Any], *keys: str) -> Any:
    layers = [body, body.get("data") if isinstance(body.get("data"), dict) else {}]
    for layer in layers:
        for key in keys:
            if layer.get(key):
                return layer[key]
    return None


async def run_video_job(app: FastAPI, job_id: str) -> None:
    db = app.state.db
    job = db.job_get(job_id)
    if not job or job["status"] != "queued" or job["kind"] != "video":
        return
    payload = json.loads(job["payload"])
    media_id = payload["media_id"]
    agnes = app.state.agnes
    db.job_update(job_id, now(), status="running", detail="Asking Agnes for the video.")
    _set_media(db, media_id, status="generating", detail="Asking Agnes for the video.")
    try:
        for attempt in range(VIDEO_QUEUE_RETRIES + 1):
            try:
                created = await agnes.video(payload["prompt"], seconds=str(VIDEO_SECONDS), aspect_ratio=payload["aspect"])
                break
            except AgnesError as exc:
                if "video_queue_full" not in str(exc) or attempt == VIDEO_QUEUE_RETRIES:
                    raise
                await asyncio.sleep(VIDEO_QUEUE_WAIT)
        video_id = _first(created, "video_id", "id")
        if not video_id:
            raise AgnesError("Agnes did not return a video_id")
        _set_media(db, media_id, video_id=str(video_id), detail="Rendering.")
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
        file = f"{media_id}.mp4"
        (app.state.settings.assets_dir / file).write_bytes(data)
        _set_media(db, media_id, file=file, status="ready", detail=None)
        db.job_update(job_id, now(), status="completed", detail="Video ready.")
        db.log(now(), "system", "video_ready", f"{payload['aspect']} {VIDEO_SECONDS}s video stored.", job["campaign_id"])
    except (AgnesError, ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        _set_media(db, media_id, status="failed", detail=str(exc)[:300])
        db.job_update(job_id, now(), status="failed", detail=str(exc)[:500])
        db.log(now(), "system", "video_failed", str(exc)[:500], job["campaign_id"])


@router.post("/assets/{asset_id}/video")
async def create_video(asset_id: str, body: VideoIn, request: Request) -> dict:
    db = request.app.state.db
    asset = asset_or_404(db, asset_id)
    if asset["channel"] != "reel":
        raise fail("no_video_for_channel", "Only reel assets carry a video.", 400)
    if not body.motion_opt_in:
        raise fail("motion_not_opted_in", "Video motion is opt-in. Send motion_opt_in true to generate it.", 409)
    if not request.app.state.settings.agnes_api_key:
        raise fail("agnes_not_configured", "AGNES_API_KEY is not set.", 409)
    open_row = db.query_one(
        "SELECT * FROM media WHERE asset_id = ? AND kind = 'video' AND status IN ('queued', 'generating')", (asset_id,)
    )
    if open_row:
        return entry(open_row)
    today = now()[:10]
    used = db.query_one(
        "SELECT COUNT(*) AS n FROM media WHERE kind = 'video' AND status != 'failed' AND created_at >= ?", (today,)
    )["n"] * VIDEO_SECONDS
    if used + VIDEO_SECONDS > VIDEO_DAILY_SECONDS:
        raise fail("video_budget_exhausted", f"The {VIDEO_DAILY_SECONDS} second daily video allowance is used up.", 409)
    campaign_plan = plan.get_plan(db, asset["campaign_id"])
    item = _item(db, asset["campaign_id"], campaign_plan)
    if not item:
        raise fail("no_item", "The campaign has no offer item to picture yet.", 409)
    media_id = uuid.uuid4().hex
    job = Service(db).queue_job(
        asset,
        "video",
        has_key=True,
        payload={"media_id": media_id, "prompt": build_video_prompt(asset, item, campaign_plan), "aspect": body.aspect, "model": VIDEO_MODEL},
        detail="Queued a video for Agnes.",
    )
    db.execute(
        """
        INSERT INTO media (id, asset_id, campaign_id, kind, file, ratio, status, job_id, detail, model, created_at)
        VALUES (?, ?, ?, 'video', NULL, ?, 'queued', ?, 'Queued for Agnes.', ?, ?)
        """,
        (media_id, asset_id, asset["campaign_id"], body.aspect, job["id"], VIDEO_MODEL, now()),
    )
    spawn(request.app, run_video_job(request.app, job["id"]))
    return entry(db.query_one("SELECT * FROM media WHERE id = ?", (media_id,)))
