"""connections: link the owner's own accounts. Today that is Instagram, through "Instagram API with Instagram Login".

Flow (all server side, the app secret and the token never reach the browser)
  GET  /auth/instagram/login      checks the owner is signed in to this app, then redirects to Instagram with a signed state.
  GET  /auth/instagram/callback   checks state, swaps the code for a short-lived token, swaps that for a 60-day token, reads the
                                  profile and recent posts, stores the token encrypted, and returns to the Connections screen.
  GET  /connections               what is connected, with profile and recent posts. Never returns a token.
  POST /connections/instagram/refresh   reads the account again (and renews the token when it is more than a day old).
  DELETE /connections/instagram   forgets the token on this server.

What this can and cannot do: it works for Instagram Business or Creator accounts, and until the Meta app passes review only for
accounts added as testers of the app. Personal accounts are not supported by Instagram's API any more. It reads profile details, recent posts
with likes and comments, and (insights scope) 28-day reach, profile views and engaged accounts, plus reach, saves and shares for
the newest posts. If the insights are not granted or not returned, the Insights screen keeps its sample data.

Settings (environment): INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET, INSTAGRAM_REDIRECT_URI (only if it differs from this server's own
callback URL, for example behind an https tunnel).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app import auth
from app.db import Database
from app.lab.security import decrypt_key, encrypt_key
from app.media import fail

router = APIRouter()

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
SCOPE = "instagram_business_basic,instagram_business_manage_insights"
PROFILE_FIELDS = "user_id,username,name,account_type,profile_picture_url,followers_count,follows_count,media_count"
MEDIA_FIELDS = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
MEDIA_LIMIT = 30
INSIGHT_POSTS = 10  # per-post insights are one request each, so only the newest few
FLOW_COOKIE = "ll_ig_oauth"
RENEW_AFTER = timedelta(hours=24)  # Instagram only renews a long-lived token that is at least a day old
SCHEMA = """
CREATE TABLE IF NOT EXISTS connection (
  provider TEXT NOT NULL,
  owner TEXT NOT NULL,
  account_id TEXT NOT NULL,
  username TEXT,
  token_enc BLOB NOT NULL,
  token_issued_at TEXT NOT NULL,
  expires_at TEXT,
  profile TEXT,
  media TEXT,
  fetched_at TEXT,
  connected_at TEXT NOT NULL,
  PRIMARY KEY (provider, owner)
)
"""


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return bool(_env("INSTAGRAM_APP_ID") and _env("INSTAGRAM_APP_SECRET"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owner(request: Request) -> str | None:
    """Whose connection this is: the signed-in Google email, or 'local' when the app is open for local work."""
    user = auth.current_user(request)
    if user:
        return user["email"]
    return None if auth.require_login() else "local"


def _redirect_uri(request: Request) -> str:
    return _env("INSTAGRAM_REDIRECT_URI") or str(request.url.replace(path="/auth/instagram/callback", query=""))


def _back(request: Request, code: str) -> Response:
    resp = RedirectResponse(f"{auth._frontend(request)}/#/connections/{code}", status_code=302)
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------- Instagram calls

class InstagramError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _check(r: httpx.Response, what: str) -> dict[str, Any]:
    """Turn an Instagram error into a short code. The body can echo request details, so it is never passed on."""
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        message = str(err.get("message") or body.get("error_message") or "")
        if r.status_code in (401, 403) or err.get("code") == 190 or "token" in message.lower():
            raise InstagramError("expired", f"Instagram no longer accepts the saved login while {what}.")
        if "business" in message.lower() or "professional" in message.lower() or "account type" in message.lower():
            raise InstagramError("not_business", "That Instagram account is a personal account. Switch it to Business or Creator first.")
        raise InstagramError("failed", f"Instagram said {r.status_code} while {what}.")
    return body


async def exchange_code(client: httpx.AsyncClient, code: str, redirect_uri: str) -> tuple[str, str]:
    r = await client.post(TOKEN_URL, data={"client_id": _env("INSTAGRAM_APP_ID"), "client_secret": _env("INSTAGRAM_APP_SECRET"),
                                          "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code": code})
    body = _check(r, "signing in")
    row = (body.get("data") or [body])[0] if isinstance(body.get("data"), list) else body
    token, user_id = row.get("access_token"), row.get("user_id")
    if not token or not user_id:
        raise InstagramError("failed", "Instagram did not return a login.")
    return str(token), str(user_id)


async def long_lived(client: httpx.AsyncClient, short: str) -> tuple[str, int]:
    r = await client.get(f"{GRAPH}/access_token", params={"grant_type": "ig_exchange_token", "client_secret": _env("INSTAGRAM_APP_SECRET"),
                                                          "access_token": short})
    body = _check(r, "extending the login")
    if not body.get("access_token"):
        raise InstagramError("failed", "Instagram did not extend the login.")
    return str(body["access_token"]), int(body.get("expires_in") or 60 * 24 * 3600)


async def renew(client: httpx.AsyncClient, token: str) -> tuple[str, int]:
    r = await client.get(f"{GRAPH}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token})
    body = _check(r, "renewing the login")
    return str(body.get("access_token") or token), int(body.get("expires_in") or 60 * 24 * 3600)


async def read_account(client: httpx.AsyncClient, token: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    me = _check(await client.get(f"{GRAPH}/me", params={"fields": PROFILE_FIELDS, "access_token": token}), "reading the profile")
    profile = {k: me.get(k) for k in ("user_id", "username", "name", "account_type", "profile_picture_url", "followers_count",
                                      "follows_count", "media_count")}
    media: list[dict[str, Any]] = []
    try:
        r = _check(await client.get(f"{GRAPH}/me/media", params={"fields": MEDIA_FIELDS, "limit": MEDIA_LIMIT, "access_token": token}), "reading posts")
        for m in r.get("data") or []:
            media.append({"id": m.get("id"), "caption": (m.get("caption") or "")[:300], "media_type": m.get("media_type"),
                          "thumbnail": m.get("thumbnail_url") or m.get("media_url"), "permalink": m.get("permalink"),
                          "timestamp": m.get("timestamp"), "likes": m.get("like_count"), "comments": m.get("comments_count")})
    except InstagramError as exc:
        if exc.code == "expired":
            raise  # the login itself is bad: say so. Any other post-reading failure still leaves the profile usable.
    await _insights(client, token, profile, media)
    return profile, media


async def _insights(client: httpx.AsyncClient, token: str, profile: dict[str, Any], media: list[dict[str, Any]]) -> None:
    """Reach and friends, when the owner granted the insights scope. Every failure here is quiet: the profile and posts still show."""
    try:
        until = int(_now().timestamp())
        r = _check(await client.get(f"{GRAPH}/me/insights", params={"metric": "reach,profile_views,accounts_engaged,total_interactions", "period": "day",
                                    "metric_type": "total_value", "since": until - 28 * 86400, "until": until, "access_token": token}), "reading insights")
        totals = {m.get("name"): (m.get("total_value") or {}).get("value") for m in r.get("data") or []}
        if totals:
            profile["insights"] = {"window_days": 28, **{k: v for k, v in totals.items() if isinstance(v, (int, float))}}
    except (InstagramError, httpx.HTTPError):
        return
    for m in media[:INSIGHT_POSTS]:
        try:
            r = _check(await client.get(f"{GRAPH}/{m['id']}/insights", params={"metric": "reach,saved,shares", "access_token": token}), "reading post insights")
            got = {d.get("name"): (d.get("values") or [{}])[0].get("value") for d in r.get("data") or []}
            m.update({k: v for k, v in got.items() if isinstance(v, (int, float))})
        except (InstagramError, httpx.HTTPError):
            continue


# ---------------------------------------------------------------- storage

def _save(db: Database, owner: str, token: str, expires_in: int, profile: dict[str, Any], media: list[dict[str, Any]], issued: datetime | None = None) -> None:
    now = _now()
    existing = db.query_one("SELECT connected_at, media FROM connection WHERE provider = 'instagram' AND owner = ?", (owner,))
    if existing and existing["media"]:
        from app import notifications  # imported here: notifications uses this module
        try:
            notifications.notify_engagement(db, owner, json.loads(existing["media"]), media, _iso(now))
        except (ValueError, TypeError):
            pass  # an unreadable old snapshot must never block saving the new one
    db.execute(
        "INSERT INTO connection (provider, owner, account_id, username, token_enc, token_issued_at, expires_at, profile, media, fetched_at, connected_at) "
        "VALUES ('instagram', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(provider, owner) DO UPDATE SET account_id=excluded.account_id, "
        "username=excluded.username, token_enc=excluded.token_enc, token_issued_at=excluded.token_issued_at, expires_at=excluded.expires_at, "
        "profile=excluded.profile, media=excluded.media, fetched_at=excluded.fetched_at",
        (owner, str(profile.get("user_id") or ""), profile.get("username"), encrypt_key(token), _iso(issued or now), _iso(now + timedelta(seconds=expires_in)),
         json.dumps(profile, ensure_ascii=False), json.dumps(media, ensure_ascii=False), _iso(now), existing["connected_at"] if existing else _iso(now)))


def _view(row: dict[str, Any] | None) -> dict[str, Any]:
    base = {"provider": "instagram", "label": "Instagram", "configured": configured(), "connected": False,
            "missing": [n for n in ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET") if not _env(n)]}
    if not row:
        return base
    expires = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
    return {**base, "connected": True, "profile": json.loads(row["profile"] or "{}"), "media": json.loads(row["media"] or "[]"),
            "connected_at": row["connected_at"], "fetched_at": row["fetched_at"], "expires_at": row["expires_at"],
            "expired": bool(expires and expires <= _now()), "scope": SCOPE,
            "can_read_insights": bool(json.loads(row["profile"] or "{}").get("insights"))}


def _require_owner(request: Request) -> str:
    owner = _owner(request)
    if owner is None:
        raise fail("login_required", "Sign in to continue.", 401)
    return owner


# ---------------------------------------------------------------- routes

@router.get("/connections")
def connections(request: Request) -> dict:
    from app import whatsapp, youtube  # imported here: both modules import this one

    owner = _require_owner(request)
    db: Database = request.app.state.db
    row = db.query_one("SELECT * FROM connection WHERE provider = 'instagram' AND owner = ?", (owner,))
    return {"connections": [
        _view(row),
        youtube.view(db, owner),
        {"provider": "whatsapp", "label": "WhatsApp", "mode": "click_to_chat", "connected": True, "configured": True, "link_reachable": whatsapp.link_reachable(),
         "note": "Opens your own WhatsApp with the message ready. You press send. The WhatsApp Business API is not connected."},
        {"provider": "facebook", "label": "Facebook", "connected": False, "configured": False, "coming_soon": True},
    ], "setup": {"redirect_uri": _redirect_uri(request), "youtube_redirect_uri": youtube._redirect_uri(request), "scope": SCOPE,
                 "needs": "A Meta app with the Instagram product, and an Instagram Business or Creator account added as a tester."}}


@router.get("/auth/instagram/login")
def login(request: Request) -> Response:
    if not configured():
        return JSONResponse(status_code=501, content={"detail": {"code": "instagram_not_configured",
                            "message": "Instagram is not set up on this server. Add INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET."}})
    if _owner(request) is None:
        return RedirectResponse(f"{auth._frontend(request)}/#/login", status_code=302)
    state = secrets.token_urlsafe(24)
    params = {"client_id": _env("INSTAGRAM_APP_ID"), "redirect_uri": _redirect_uri(request), "response_type": "code", "scope": SCOPE, "state": state}
    resp = RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=302)
    resp.set_cookie(FLOW_COOKIE, auth.sign(request.app, {"state": state}, auth.FLOW_TTL), max_age=auth.FLOW_TTL, httponly=True,
                    samesite="lax", secure=auth._secure(request), path="/")
    return resp


@router.get("/auth/instagram/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                   error_reason: str | None = None) -> Response:
    if not configured():
        return _back(request, "failed")
    if error or error_reason:
        return _back(request, "denied" if (error_reason == "user_denied" or error == "access_denied") else "failed")
    owner = _owner(request)
    flow = auth.verify(request.app, request.cookies.get(FLOW_COOKIE))
    if owner is None or not flow or not code or not state or not secrets.compare_digest(state, flow.get("state", "")):
        return _back(request, "failed")
    code = code.removesuffix("#_")  # Instagram appends "#_" to the code
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            short, _ = await exchange_code(client, code, _redirect_uri(request))
            token, expires_in = await long_lived(client, short)
            profile, media = await read_account(client, token)
    except InstagramError as exc:
        return _back(request, exc.code)
    except httpx.HTTPError:
        return _back(request, "failed")
    _save(request.app.state.db, owner, token, expires_in, profile, media)
    return _back(request, "connected")


@router.post("/connections/instagram/refresh")
async def refresh(request: Request) -> dict:
    owner = _require_owner(request)
    db: Database = request.app.state.db
    row = db.query_one("SELECT * FROM connection WHERE provider = 'instagram' AND owner = ?", (owner,))
    if not row:
        raise fail("not_connected", "Instagram is not connected.", 404)
    token = decrypt_key(row["token_enc"])
    if not token:
        raise fail("token_unreadable", "The saved login can no longer be read. Connect again.", 409)
    issued = datetime.fromisoformat(row["token_issued_at"])
    expires_in = int((datetime.fromisoformat(row["expires_at"]) - _now()).total_seconds()) if row["expires_at"] else 0
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            if _now() - issued >= RENEW_AFTER and expires_in > 0:
                token, expires_in = await renew(client, token)
                issued = _now()
            profile, media = await read_account(client, token)
    except InstagramError as exc:
        raise fail(exc.code, str(exc), 409 if exc.code == "expired" else 502) from exc
    except httpx.HTTPError as exc:
        raise fail("failed", "Could not reach Instagram.", 502) from exc
    _save(db, owner, token, expires_in, profile, media, issued)
    return _view(db.query_one("SELECT * FROM connection WHERE provider = 'instagram' AND owner = ?", (owner,)))


@router.delete("/connections/instagram")
def disconnect(request: Request) -> dict:
    owner = _require_owner(request)
    request.app.state.db.execute("DELETE FROM connection WHERE provider = 'instagram' AND owner = ?", (owner,))
    # Instagram has no revoke call for this token. It stops working at expiry, or when the owner removes the app in Instagram's settings.
    return {"disconnected": True}
