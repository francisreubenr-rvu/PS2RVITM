"""youtube: connect the owner's YouTube channel and upload an approved reel as a Short.

Sign-in is Google OAuth (the same Google client as sign-in to this app) with the scopes youtube.upload and youtube.readonly,
asked for offline so the server can renew its own access. Tokens are stored encrypted, never returned.

Uploading
  - only an approved reel asset with a finished video that is vertical or square
  - the title, description and tracked link come from the approved asset and are built here
  - the video is always sent as PRIVATE unless the owner picks otherwise on that upload

Two limits of YouTube's own rules, which this code cannot change:
  - Videos uploaded through the API by a Google project that has not passed YouTube's API compliance audit are locked to private,
    whatever visibility is requested. The answer reports the visibility YouTube actually applied.
  - Each upload costs 1,600 of the project's 10,000 daily quota units, so about six uploads a day until quota is raised.
While the Google consent screen is in Testing, only listed test users can connect and their tokens expire after 7 days.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app import auth, connections, outreach, whatsapp
from app.db import Database
from app.lab.security import decrypt_key, encrypt_key
from app.media import asset_or_404, fail
from app.service import now

router = APIRouter()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = ("https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly")
FLOW_COOKIE = "ll_yt_oauth"
MAX_BYTES = 256 * 1024 * 1024
PRIVACY = ("private", "unlisted", "public")


def ensure_schema(db: Database) -> None:
    """The connection table is created by the connections module."""


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return auth.configured()


def _redirect_uri(request: Request) -> str:
    return _env("YOUTUBE_REDIRECT_URI") or str(request.url.replace(path="/auth/youtube/callback", query=""))


def _b64(data: bytes) -> str:
    return auth._b64(data)


class YouTubeError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


def _check(r: httpx.Response, what: str) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        reasons = {e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)}
        if r.status_code == 401 or body.get("error") == "invalid_grant":
            raise YouTubeError("expired", f"YouTube no longer accepts the saved login while {what}. Connect again.", 409)
        if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
            raise YouTubeError("quota", "The daily YouTube upload limit for this app is used up. Try again tomorrow.", 429)
        if reasons & {"uploadLimitExceeded"}:
            raise YouTubeError("upload_limit", "This channel has reached YouTube's daily upload limit.", 429)
        if r.status_code == 403:
            raise YouTubeError("forbidden", f"YouTube refused permission while {what}. Check the YouTube Data API is enabled and the scopes were granted.", 403)
        raise YouTubeError("failed", f"YouTube said {r.status_code} while {what}.")
    return body


# ---------------------------------------------------------------- tokens and storage

def _pack(access: str, refresh: str | None, expires_in: int) -> bytes:
    return encrypt_key(json.dumps({"access": access, "refresh": refresh, "exp": (datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)).isoformat()}))


def _unpack(blob: bytes) -> dict[str, Any] | None:
    raw = decrypt_key(blob)
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


async def _refresh(client: httpx.AsyncClient, refresh: str) -> tuple[str, int]:
    r = await client.post(TOKEN_URL, data={"client_id": _env("GOOGLE_CLIENT_ID"), "client_secret": _env("GOOGLE_CLIENT_SECRET"),
                                          "refresh_token": refresh, "grant_type": "refresh_token"})
    body = _check(r, "renewing the login")
    return str(body["access_token"]), int(body.get("expires_in") or 3600)


async def _access(client: httpx.AsyncClient, db: Database, owner: str, row: dict[str, Any]) -> str:
    """A working access token, renewed with the refresh token when it has run out. The renewed one is saved."""
    tokens = _unpack(row["token_enc"])
    if not tokens:
        raise YouTubeError("token_unreadable", "The saved login can no longer be read. Connect again.", 409)
    if datetime.fromisoformat(tokens["exp"]) > datetime.now(timezone.utc):
        return tokens["access"]
    if not tokens.get("refresh"):
        raise YouTubeError("expired", "The YouTube login ran out. Connect again.", 409)
    access, expires_in = await _refresh(client, tokens["refresh"])
    db.execute("UPDATE connection SET token_enc = ? WHERE provider = 'youtube' AND owner = ?", (_pack(access, tokens["refresh"], expires_in), owner))
    return access


async def read_channel(client: httpx.AsyncClient, access: str) -> dict[str, Any]:
    body = _check(await client.get(f"{API}/channels", params={"part": "snippet,statistics", "mine": "true"}, headers={"Authorization": f"Bearer {access}"}),
                  "reading the channel")
    items = body.get("items") or []
    if not items:
        raise YouTubeError("no_channel", "That Google account has no YouTube channel yet. Create one in YouTube first.", 409)
    c = items[0]
    sn, st = c.get("snippet") or {}, c.get("statistics") or {}
    thumbs = sn.get("thumbnails") or {}
    return {"id": c.get("id"), "title": sn.get("title"), "handle": sn.get("customUrl"),
            "picture": (thumbs.get("default") or thumbs.get("medium") or {}).get("url"),
            "subscribers": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount") or 0),
            "videos": int(st.get("videoCount") or 0), "views": int(st.get("viewCount") or 0)}


def view(db: Database, owner: str) -> dict[str, Any]:
    base = {"provider": "youtube", "label": "YouTube", "configured": configured(), "connected": False,
            "missing": [n for n in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if not _env(n)]}
    row = db.query_one("SELECT * FROM connection WHERE provider = 'youtube' AND owner = ?", (owner,))
    if not row:
        return base
    tokens = _unpack(row["token_enc"]) or {}
    return {**base, "connected": True, "profile": json.loads(row["profile"] or "{}"), "connected_at": row["connected_at"], "fetched_at": row["fetched_at"],
            "can_upload": True, "has_refresh_token": bool(tokens.get("refresh")),
            "limits": ["Uploads from an app Google has not audited are locked to private.", "About six uploads a day on the default quota."]}


def _store(db: Database, owner: str, tokens: bytes, channel: dict[str, Any]) -> None:
    existing = db.query_one("SELECT connected_at FROM connection WHERE provider = 'youtube' AND owner = ?", (owner,))
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO connection (provider, owner, account_id, username, token_enc, token_issued_at, expires_at, profile, media, fetched_at, connected_at) "
        "VALUES ('youtube', ?, ?, ?, ?, ?, NULL, ?, '[]', ?, ?) ON CONFLICT(provider, owner) DO UPDATE SET account_id=excluded.account_id, "
        "username=excluded.username, token_enc=excluded.token_enc, token_issued_at=excluded.token_issued_at, profile=excluded.profile, fetched_at=excluded.fetched_at",
        (owner, channel.get("id") or "", channel.get("handle") or channel.get("title"), tokens, stamp, json.dumps(channel, ensure_ascii=False), stamp,
         existing["connected_at"] if existing else stamp))


# ---------------------------------------------------------------- routes

def _back(request: Request, code: str) -> Response:
    resp = RedirectResponse(f"{auth._frontend(request)}/#/connections/youtube-{code}", status_code=302)
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp


@router.get("/auth/youtube/login")
def login(request: Request) -> Response:
    if not configured():
        return JSONResponse(status_code=501, content={"detail": {"code": "google_not_configured",
                            "message": "Google is not set up on this server. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."}})
    if connections._owner(request) is None:
        return RedirectResponse(f"{auth._frontend(request)}/#/login", status_code=302)
    verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(24)
    params = {"client_id": _env("GOOGLE_CLIENT_ID"), "redirect_uri": _redirect_uri(request), "response_type": "code", "scope": " ".join(SCOPES),
              "state": state, "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
              "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false"}
    resp = RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=302)
    resp.set_cookie(FLOW_COOKIE, auth.sign(request.app, {"state": state, "verifier": verifier}, auth.FLOW_TTL), max_age=auth.FLOW_TTL, httponly=True,
                    samesite="lax", secure=auth._secure(request), path="/")
    return resp


@router.get("/auth/youtube/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    if not configured():
        return _back(request, "failed")
    if error:
        return _back(request, "denied" if error == "access_denied" else "failed")
    owner = connections._owner(request)
    flow = auth.verify(request.app, request.cookies.get(FLOW_COOKIE))
    if owner is None or not flow or not code or not state or not secrets.compare_digest(state, flow.get("state", "")):
        return _back(request, "failed")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(TOKEN_URL, data={"code": code, "client_id": _env("GOOGLE_CLIENT_ID"), "client_secret": _env("GOOGLE_CLIENT_SECRET"),
                                                  "redirect_uri": _redirect_uri(request), "grant_type": "authorization_code", "code_verifier": flow["verifier"]})
            body = _check(r, "signing in")
            if SCOPES[0] not in (body.get("scope") or "").split():
                return _back(request, "scope")  # the owner unticked the upload permission
            channel = await read_channel(client, body["access_token"])
    except YouTubeError as exc:
        return _back(request, exc.code)
    except httpx.HTTPError:
        return _back(request, "failed")
    _store(request.app.state.db, owner, _pack(body["access_token"], body.get("refresh_token"), int(body.get("expires_in") or 3600)), channel)
    return _back(request, "connected")


@router.post("/connections/youtube/refresh")
async def refresh(request: Request) -> dict:
    owner = connections._require_owner(request)
    db: Database = request.app.state.db
    row = db.query_one("SELECT * FROM connection WHERE provider = 'youtube' AND owner = ?", (owner,))
    if not row:
        raise fail("not_connected", "YouTube is not connected.", 404)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            channel = await read_channel(client, await _access(client, db, owner, row))
    except YouTubeError as exc:
        raise fail(exc.code, str(exc), exc.status) from exc
    except httpx.HTTPError as exc:
        raise fail("failed", "Could not reach YouTube.", 502) from exc
    db.execute("UPDATE connection SET profile = ?, fetched_at = ? WHERE provider = 'youtube' AND owner = ?",
               (json.dumps(channel, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), owner))
    return view(db, owner)


@router.delete("/connections/youtube")
async def disconnect(request: Request) -> dict:
    owner = connections._require_owner(request)
    db: Database = request.app.state.db
    row = db.query_one("SELECT * FROM connection WHERE provider = 'youtube' AND owner = ?", (owner,))
    if row:
        tokens = _unpack(row["token_enc"]) or {}
        try:  # best effort: tell Google to drop the grant. The local copy is removed either way.
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(REVOKE_URL, data={"token": tokens.get("refresh") or tokens.get("access") or ""})
        except httpx.HTTPError:
            pass
        db.execute("DELETE FROM connection WHERE provider = 'youtube' AND owner = ?", (owner,))
    return {"disconnected": True}


# ---------------------------------------------------------------- shorts upload

class ShortIn(BaseModel):
    privacy: str = Field(default="private", pattern="^(private|unlisted|public)$")
    title: str | None = Field(default=None, max_length=100)


def short_video(db: Database, asset_id: str) -> dict[str, Any]:
    """The finished video for a reel, if it can be a Short (vertical or square)."""
    rows = db.query("SELECT * FROM media WHERE asset_id = ? AND kind = 'video' AND status = 'ready' AND file IS NOT NULL ORDER BY created_at DESC", (asset_id,))
    if not rows:
        raise fail("no_video", "This reel has no finished video yet. Make the video first.", 409)
    m = rows[0]
    w, h = m.get("width"), m.get("height")
    ratio = (m.get("ratio") or "").replace("/", ":")
    vertical = (w and h and h >= w) or ratio in ("9:16", "1:1", "3:4", "2:3")
    if not vertical:
        raise fail("not_a_short", "YouTube Shorts must be vertical or square. Make this video in 9:16.", 422)
    return m


def short_title(asset: dict[str, Any], wanted: str | None) -> str:
    extra = outreach._extra(asset)
    base = (wanted or extra.get("title") or extra.get("headline") or (asset.get("content") or "").strip().splitlines()[0:1] or [""])
    base = base if isinstance(base, str) else base[0]
    base = re.sub(r"\s+", " ", base).strip(" #") or "New offer"
    tag = " #Shorts"
    return (base[: 100 - len(tag)].rstrip() + tag) if "#shorts" not in base.lower() else base[:100]


@router.post("/assets/{asset_id}/youtube")
async def upload_short(asset_id: str, body: ShortIn, request: Request) -> dict:
    owner = connections._require_owner(request)
    db: Database = request.app.state.db
    asset = asset_or_404(db, asset_id)
    outreach.require_approved(asset)
    if asset["channel"] != "reel":
        raise fail("not_a_reel", "Only a reel can be posted as a YouTube Short.", 422)
    row = db.query_one("SELECT * FROM connection WHERE provider = 'youtube' AND owner = ?", (owner,))
    if not row:
        raise fail("not_connected", "Connect YouTube first.", 409)
    media = short_video(db, asset_id)
    path = (request.app.state.settings.assets_dir / media["file"]).resolve()
    if path.parent != request.app.state.settings.assets_dir.resolve() or not path.is_file():
        raise fail("video_missing", "The video file is missing on this server.", 409)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise fail("too_large", "That video is too large to upload from here.", 422)
    link = outreach.ensure_link(db, asset)["url"] if outreach.destination(db, asset["campaign_id"]) else None
    description = whatsapp.distributable_text(asset, link)
    if "#shorts" not in description.lower():
        description += "\n\n#Shorts"
    metadata = {"snippet": {"title": short_title(asset, body.title), "description": description[:4900], "categoryId": "22"},
                "status": {"privacyStatus": body.privacy, "selfDeclaredMadeForKids": False}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20)) as client:
            access = await _access(client, db, owner, row)
            init = await client.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=metadata,
                                     headers={"Authorization": f"Bearer {access}", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
            _check(init, "starting the upload") if init.status_code >= 400 else None
            location = init.headers.get("location")
            if not location:
                raise YouTubeError("failed", "YouTube did not give an upload address.")
            sent = await client.put(location, content=path.read_bytes(), headers={"Content-Type": "video/mp4", "Authorization": f"Bearer {access}"})
            result = _check(sent, "uploading the video")
    except YouTubeError as exc:
        raise fail(exc.code, str(exc), exc.status) from exc
    except httpx.HTTPError as exc:
        raise fail("failed", "Could not reach YouTube.", 502) from exc
    vid = result.get("id")
    applied = ((result.get("status") or {}).get("privacyStatus")) or body.privacy
    db.execute("INSERT INTO outreach_event (ts, asset_id, campaign_id, action, detail) VALUES (?, ?, ?, 'posted_manually', ?)",
               (now(), asset_id, asset["campaign_id"], f"youtube:{vid}"))
    return {"video_id": vid, "url": f"https://youtu.be/{vid}" if vid else None, "studio_url": f"https://studio.youtube.com/video/{vid}/edit" if vid else None,
            "privacy_requested": body.privacy, "privacy_applied": applied,
            "locked_private": applied == "private" and body.privacy != "private",
            "note": "Check it in YouTube Studio. Uploads from an app Google has not audited stay private, whatever was asked for."
            if applied == "private" else "Uploaded."}
