"""YouTube: Google OAuth with upload scope, channel read, token renewal, Shorts upload rules. No network."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import auth, connections, plan, youtube
from app.config import Settings
from app.main import create_app
from b_helpers import PLAN, seed, write_copy

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
CHANNEL = {"items": [{"id": "UC123", "snippet": {"title": "Brew Bandi Cafe", "customUrl": "@brewbandi", "thumbnails": {"default": {"url": "https://yt.example/a.jpg"}}},
                      "statistics": {"subscriberCount": "420", "videoCount": "12", "viewCount": "9000"}}]}


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body if body is not None else {}, headers or {}

    def json(self):
        return self._body


def make(tmp_path, monkeypatch, *, google=True):
    for n in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "YOUTUBE_REDIRECT_URI", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(n, raising=False)
    if google:
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    s = Settings(agnes_api_key=None, agnes_base_url="http://x.invalid/v1", agnes_origin="http://x.invalid", database_path=tmp_path / "t.db", assets_dir=tmp_path / "assets")
    return TestClient(create_app(s), follow_redirects=False, base_url="http://127.0.0.1:8000")


def fake_google(monkeypatch, calls, *, scope=f"{UPLOAD_SCOPE} {READ_SCOPE}", token_status=200, channel=CHANNEL, upload_status=200, init_error=None, applied="private"):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, json=None, params=None, headers=None, **k):
            calls.append(("POST", url, dict(data or {}), json, dict(params or {}), dict(headers or {})))
            if url == youtube.TOKEN_URL:
                if token_status != 200:
                    return Resp(token_status, {"error": "invalid_grant"})
                if (data or {}).get("grant_type") == "refresh_token":
                    return Resp(200, {"access_token": "ACCESS2", "expires_in": 3600})
                return Resp(200, {"access_token": "ACCESS", "refresh_token": "REFRESH", "expires_in": 3600, "scope": scope})
            if url == youtube.REVOKE_URL:
                return Resp(200, {})
            if url == youtube.UPLOAD:
                if init_error:
                    return Resp(403, {"error": {"errors": [{"reason": init_error}]}})
                return Resp(200, {}, {"location": "https://upload.example/session1"})
            return Resp(404, {})

        async def get(self, url, params=None, headers=None, **k):
            calls.append(("GET", url, dict(params or {}), None, {}, dict(headers or {})))
            if url.endswith("/channels"):
                return Resp(200, channel) if channel is not None else Resp(401, {"error": {"message": "bad"}})
            return Resp(404, {})

        async def put(self, url, content=None, headers=None, **k):
            calls.append(("PUT", url, {}, len(content or b""), {}, dict(headers or {})))
            return Resp(upload_status, {"id": "VID9", "status": {"privacyStatus": applied}})

    monkeypatch.setattr(youtube.httpx, "AsyncClient", Client)


def begin(c):
    r = c.get("/auth/youtube/login")
    return r, parse_qs(urlparse(r.headers["location"]).query)


def finish(c, state, **extra):
    return c.get("/auth/youtube/callback", params={"code": "abc", "state": state, **extra})


def connect(c, monkeypatch, calls=None, **kw):
    calls = [] if calls is None else calls
    fake_google(monkeypatch, calls, **kw)
    _, q = begin(c)
    return finish(c, q["state"][0]), calls


def test_login_asks_for_upload_scope_offline_with_pkce(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    r, q = begin(c)
    assert r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert set(q["scope"][0].split()) == {UPLOAD_SCOPE, READ_SCOPE}
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8000/auth/youtube/callback"]
    assert auth.verify(c.app, c.cookies.get(youtube.FLOW_COOKIE))["state"] == q["state"][0]


def test_login_needs_google_configured(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch, google=False)
    assert c.get("/auth/youtube/login").status_code == 501
    row = {r["provider"]: r for r in c.get("/connections").json()["connections"]}["youtube"]
    assert row["configured"] is False and row["missing"] == ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]


def test_connect_stores_encrypted_tokens_and_reads_the_channel(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    r, calls = connect(c, monkeypatch)
    assert r.headers["location"].endswith("/#/connections/youtube-connected")
    row = c.app.state.db.query_one("SELECT token_enc FROM connection WHERE provider = 'youtube'")
    assert b"REFRESH" not in row["token_enc"] and b"ACCESS" not in row["token_enc"]
    yt = next(x for x in c.get("/connections").json()["connections"] if x["provider"] == "youtube")
    assert yt["connected"] and yt["profile"]["title"] == "Brew Bandi Cafe" and yt["profile"]["subscribers"] == 420 and yt["has_refresh_token"]
    assert "REFRESH" not in json.dumps(c.get("/connections").json())
    assert next(x for x in calls if x[0] == "POST" and x[1] == youtube.TOKEN_URL)[2]["code_verifier"]


def test_unticking_the_upload_permission_is_caught(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    r, _ = connect(c, monkeypatch, scope=READ_SCOPE)
    assert r.headers["location"].endswith("/#/connections/youtube-scope")
    assert c.app.state.db.query("SELECT * FROM connection") == []


def test_refusal_bad_state_and_a_google_account_with_no_channel(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    begin(c)
    assert c.get("/auth/youtube/callback", params={"error": "access_denied"}).headers["location"].endswith("youtube-denied")
    assert finish(c, "forged").headers["location"].endswith("youtube-failed")
    c2 = make(tmp_path, monkeypatch)
    r, _ = connect(c2, monkeypatch, channel={"items": []})
    assert r.headers["location"].endswith("youtube-no_channel")


def test_the_login_includes_the_connect_cards_for_every_service(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    cards = {x["provider"]: x for x in c.get("/connections").json()["connections"]}
    assert list(cards) == ["instagram", "youtube", "whatsapp", "facebook"]
    assert cards["facebook"]["coming_soon"] is True and cards["facebook"]["connected"] is False
    assert cards["whatsapp"]["mode"] == "click_to_chat" and "Business API is not connected" in cards["whatsapp"]["note"]


def test_an_expired_access_token_is_renewed_with_the_refresh_token(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    connect(c, monkeypatch)
    old = youtube._pack("STALE", "REFRESH", -3600)
    c.app.state.db.execute("UPDATE connection SET token_enc = ? WHERE provider = 'youtube'", (old,))
    calls = []
    fake_google(monkeypatch, calls)
    assert c.post("/connections/youtube/refresh").json()["profile"]["id"] == "UC123"
    assert any(x[1] == youtube.TOKEN_URL and x[2].get("grant_type") == "refresh_token" for x in calls)
    assert next(x for x in calls if x[1].endswith("/channels"))[5]["Authorization"] == "Bearer ACCESS2"
    fresh = youtube._unpack(c.app.state.db.query_one("SELECT token_enc FROM connection")["token_enc"])
    assert fresh["access"] == "ACCESS2" and fresh["refresh"] == "REFRESH"


def test_disconnect_revokes_and_forgets(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    connect(c, monkeypatch)
    calls = []
    fake_google(monkeypatch, calls)
    assert c.delete("/connections/youtube").json() == {"disconnected": True}
    assert any(x[1] == youtube.REVOKE_URL and x[2]["token"] == "REFRESH" for x in calls)
    assert c.app.state.db.query("SELECT * FROM connection") == []


# ---- shorts upload
@pytest.fixture
def rig(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    monkeypatch.setattr(plan, "get_plan", lambda db, cid: PLAN)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://growit.example")
    cid, assets = seed(c, c.app)
    reel = assets["whatsapp"]  # reuse a seeded asset as the reel
    c.app.state.db.execute("UPDATE asset SET channel = 'reel' WHERE id = ?", (reel["id"],))
    write_copy(c.app, reel, "Hook line\nSecond line\nOffer line", status="approved")
    return c, reel["id"], tmp_path, monkeypatch


def add_video(c, asset_id, tmp_path, *, ratio="9:16", w=720, h=1280, status="ready", data=b"\x00\x00\x00 ftypmp42" + b"v" * 5000):
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "clip.mp4").write_bytes(data)
    c.app.state.db.execute("INSERT INTO media (id, asset_id, campaign_id, kind, file, ratio, status, width, height, created_at) VALUES ('m1', ?, 'x', 'video', 'clip.mp4', ?, ?, ?, ?, '2026-10-09')",
                           (asset_id, ratio, status, w, h))


def test_a_short_is_uploaded_private_with_a_tracked_link_and_the_shorts_tag(rig):
    c, aid, tmp_path, monkeypatch = rig
    add_video(c, aid, tmp_path)
    connect(c, monkeypatch)
    calls = []
    fake_google(monkeypatch, calls)
    out = c.post(f"/assets/{aid}/youtube", json={}).json()
    assert out["video_id"] == "VID9" and out["url"] == "https://youtu.be/VID9" and out["privacy_applied"] == "private" and out["locked_private"] is False
    init = next(x for x in calls if x[1] == youtube.UPLOAD)
    meta = init[3]
    assert meta["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    assert meta["snippet"]["title"].endswith("#Shorts") and len(meta["snippet"]["title"]) <= 100
    assert "https://growit.example/r/" in meta["snippet"]["description"] and "#Shorts" in meta["snippet"]["description"]
    assert init[5]["Authorization"] == "Bearer ACCESS" and init[5]["X-Upload-Content-Length"] == "5012"
    put = next(x for x in calls if x[0] == "PUT")
    assert put[1] == "https://upload.example/session1" and put[3] == 5012
    event = c.app.state.db.query_one("SELECT action, detail FROM outreach_event ORDER BY id DESC")
    assert event["action"] == "posted_manually" and event["detail"] == "youtube:VID9"


def test_asking_for_public_is_reported_honestly_when_youtube_locks_it_private(rig):
    c, aid, tmp_path, monkeypatch = rig
    add_video(c, aid, tmp_path)
    connect(c, monkeypatch)
    fake_google(monkeypatch, [], applied="private")
    out = c.post(f"/assets/{aid}/youtube", json={"privacy": "public"}).json()
    assert out["privacy_requested"] == "public" and out["privacy_applied"] == "private" and out["locked_private"] is True
    assert "has not audited" in out["note"]
    fake_google(monkeypatch, [], applied="public")
    ok = c.post(f"/assets/{aid}/youtube", json={"privacy": "public"}).json()
    assert ok["locked_private"] is False and ok["privacy_applied"] == "public"
    assert c.post(f"/assets/{aid}/youtube", json={"privacy": "everyone"}).status_code == 422


@pytest.mark.parametrize("setup,code,status", [
    ("not_approved", "not_approved", 409), ("not_reel", "not_a_reel", 422), ("no_connection", "not_connected", 409),
    ("no_video", "no_video", 409), ("landscape", "not_a_short", 422), ("video_not_ready", "no_video", 409),
])
def test_uploads_are_refused_unless_every_rule_holds(rig, setup, code, status):
    c, aid, tmp_path, monkeypatch = rig
    if setup != "no_connection":
        connect(c, monkeypatch)
    if setup == "not_approved":
        c.app.state.db.asset_update(aid, status="pending")
    if setup == "not_reel":
        c.app.state.db.execute("UPDATE asset SET channel = 'whatsapp' WHERE id = ?", (aid,))
    if setup == "landscape":
        add_video(c, aid, tmp_path, ratio="16:9", w=1280, h=720)
    elif setup == "video_not_ready":
        add_video(c, aid, tmp_path, status="queued")
    elif setup not in ("no_video", "not_approved", "not_reel", "no_connection"):
        add_video(c, aid, tmp_path)
    if setup in ("not_approved", "not_reel", "no_connection"):
        add_video(c, aid, tmp_path)
    fake_google(monkeypatch, [])
    r = c.post(f"/assets/{aid}/youtube", json={})
    assert r.status_code == status and r.json()["detail"]["code"] == code


def test_quota_and_daily_limit_errors_are_explained(rig):
    c, aid, tmp_path, monkeypatch = rig
    add_video(c, aid, tmp_path)
    connect(c, monkeypatch)
    fake_google(monkeypatch, [], init_error="quotaExceeded")
    r = c.post(f"/assets/{aid}/youtube", json={})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "quota" and "tomorrow" in r.json()["detail"]["message"]
    fake_google(monkeypatch, [], init_error="uploadLimitExceeded")
    assert c.post(f"/assets/{aid}/youtube", json={}).json()["detail"]["code"] == "upload_limit"


def test_titles_are_short_tagged_and_never_empty():
    asset = {"channel": "reel", "content": "A very long first line " * 10, "extra": None}
    t = youtube.short_title(asset, None)
    assert len(t) <= 100 and t.endswith("#Shorts")
    assert youtube.short_title({"channel": "reel", "content": "", "extra": None}, None) == "New offer #Shorts"
    assert youtube.short_title(asset, "Weekend coffee #shorts") == "Weekend coffee #shorts"
