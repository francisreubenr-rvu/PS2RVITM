"""Instagram connection: OAuth redirect, state check, token swaps, encrypted storage, refresh, disconnect. No network."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import auth, connections
from app.config import Settings
from app.main import create_app

PROFILE = {"user_id": "1784", "username": "brewbandi", "name": "Brew Bandi Cafe", "account_type": "BUSINESS",
           "profile_picture_url": "https://cdn.example/p.jpg", "followers_count": 1240, "follows_count": 180, "media_count": 57}
MEDIA = {"data": [{"id": "m1", "caption": "Weekend filter coffee, 20% off", "media_type": "IMAGE", "media_url": "https://cdn.example/1.jpg",
                   "permalink": "https://instagram.com/p/1", "timestamp": "2026-10-04T08:00:00+0000", "like_count": 88, "comments_count": 9}]}


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def make(tmp_path, monkeypatch, *, configured=True, require=False):
    for name in ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_REDIRECT_URI", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    if configured:
        monkeypatch.setenv("INSTAGRAM_APP_ID", "ig-app-1")
        monkeypatch.setenv("INSTAGRAM_APP_SECRET", "ig-secret-xyz")
    if require:
        monkeypatch.setenv("REQUIRE_LOGIN", "1")
    s = Settings(agnes_api_key=None, agnes_base_url="http://x.invalid/v1", agnes_origin="http://x.invalid",
                 database_path=tmp_path / "t.db", assets_dir=tmp_path / "a")
    return TestClient(create_app(s), follow_redirects=False, base_url="http://127.0.0.1:8000")


def fake_instagram(monkeypatch, *, token_status=200, profile_status=200, media_status=200, calls=None, profile=PROFILE, insights=False):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, **k):
            calls.append(("POST", url, dict(data or {}))) if calls is not None else None
            if token_status != 200:
                return Resp(token_status, {"error_message": "Invalid authorization code"})
            return Resp(200, {"data": [{"access_token": "SHORT", "user_id": 1784, "permissions": "instagram_business_basic"}]})

        async def get(self, url, params=None, **k):
            calls.append(("GET", url, dict(params or {}))) if calls is not None else None
            if url.endswith("/access_token"):
                return Resp(200, {"access_token": "LONG", "token_type": "bearer", "expires_in": 5184000})
            if url.endswith("/refresh_access_token"):
                return Resp(200, {"access_token": "LONG2", "expires_in": 5184000})
            if url.endswith("/me/insights"):
                if not insights:
                    return Resp(400, {"error": {"message": "(#10) Application does not have permission", "code": 10}})
                return Resp(200, {"data": [{"name": "reach", "total_value": {"value": 1200}}, {"name": "profile_views", "total_value": {"value": 85}}]})
            if url.endswith("/insights"):
                return Resp(200, {"data": [{"name": "reach", "values": [{"value": 300}]}, {"name": "saved", "values": [{"value": 9}]}]})
            if url.endswith("/me/media"):
                return Resp(media_status, MEDIA if media_status == 200 else {"error": {"message": "Error validating access token", "code": 190}})
            if url.endswith("/me"):
                return Resp(profile_status, profile if profile_status == 200 else {"error": {"message": "Error validating access token", "code": 190}})
            return Resp(404, {})

    monkeypatch.setattr(connections.httpx, "AsyncClient", Client)


def begin(c):
    r = c.get("/auth/instagram/login")
    return r, parse_qs(urlparse(r.headers["location"]).query)


def finish(c, state, **extra):
    return c.get("/auth/instagram/callback", params={"code": "abc#_", "state": state, **extra})


def test_login_needs_the_meta_app_keys(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch, configured=False)
    r = c.get("/auth/instagram/login")
    assert r.status_code == 501 and r.json()["detail"]["code"] == "instagram_not_configured"
    assert c.get("/connections").json()["connections"][0] == {"provider": "instagram", "label": "Instagram", "configured": False, "connected": False,
                                                                     "missing": ["INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET"]}


def test_login_redirects_to_instagram_with_the_smallest_scope_and_a_signed_state(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    r, q = begin(c)
    assert r.status_code == 302 and r.headers["location"].startswith("https://www.instagram.com/oauth/authorize?")
    assert q["client_id"] == ["ig-app-1"] and q["scope"] == ["instagram_business_basic,instagram_business_manage_insights"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8000/auth/instagram/callback"]
    flow = auth.verify(c.app, c.cookies.get(connections.FLOW_COOKIE))
    assert flow["state"] == q["state"][0]
    assert "httponly" in r.headers["set-cookie"].lower()


def test_full_connect_stores_an_encrypted_long_lived_token_and_the_profile(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    calls = []
    fake_instagram(monkeypatch, calls=calls)
    _, q = begin(c)
    r = finish(c, q["state"][0])
    assert r.status_code == 302 and r.headers["location"].endswith("/#/connections/connected")
    posted = next(x for x in calls if x[0] == "POST")
    assert posted[2]["code"] == "abc" and posted[2]["grant_type"] == "authorization_code" and posted[2]["client_secret"] == "ig-secret-xyz"  # "#_" removed
    swap = next(x for x in calls if x[0] == "GET" and x[1].endswith("/access_token"))
    assert swap[2]["grant_type"] == "ig_exchange_token" and swap[2]["access_token"] == "SHORT"
    me_call = next(x for x in calls if x[1].endswith("/me"))
    assert me_call[2]["access_token"] == "LONG"  # reads use the long-lived token, not the short one
    row = c.app.state.db.query_one("SELECT token_enc FROM connection")
    assert b"LONG" not in row["token_enc"] and b"SHORT" not in row["token_enc"]
    view = c.get("/connections").json()["connections"][0]
    assert view["connected"] and view["profile"]["username"] == "brewbandi" and view["profile"]["followers_count"] == 1240
    assert view["media"][0]["likes"] == 88 and view["media"][0]["comments"] == 9
    assert view["can_read_insights"] is False and view["expired"] is False
    assert "LONG" not in json.dumps(c.get("/connections").json()) and "ig-secret" not in json.dumps(c.get("/connections").json())


@pytest.mark.parametrize("extra,code", [({"error": "access_denied", "error_reason": "user_denied"}, "denied"), ({"error": "server_error"}, "failed")])
def test_callback_reports_a_refusal(tmp_path, monkeypatch, extra, code):
    c = make(tmp_path, monkeypatch)
    begin(c)
    r = c.get("/auth/instagram/callback", params=extra)
    assert r.headers["location"].endswith(f"/#/connections/{code}")


def test_callback_rejects_a_wrong_or_missing_state(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    fake_instagram(monkeypatch)
    begin(c)
    assert finish(c, "forged").headers["location"].endswith("/#/connections/failed")
    fresh = make(tmp_path, monkeypatch)
    assert finish(fresh, "anything").headers["location"].endswith("/#/connections/failed")  # no flow cookie at all
    assert c.get("/connections").json()["connections"][0]["connected"] is False


def test_a_rejected_code_or_a_personal_account_is_explained(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    fake_instagram(monkeypatch, token_status=400)
    _, q = begin(c)
    assert finish(c, q["state"][0]).headers["location"].endswith("/#/connections/failed")
    c2 = make(tmp_path, monkeypatch)
    fake_instagram(monkeypatch, profile_status=400)
    _, q2 = begin(c2)
    assert finish(c2, q2["state"][0]).headers["location"].endswith("/#/connections/expired")  # error 190 means the login itself is bad


def test_refresh_rereads_the_account_and_renews_an_old_token(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    fake_instagram(monkeypatch)
    _, q = begin(c)
    finish(c, q["state"][0])
    calls = []
    fake_instagram(monkeypatch, calls=calls, profile={**PROFILE, "followers_count": 1300})
    again = c.post("/connections/instagram/refresh").json()
    assert again["profile"]["followers_count"] == 1300
    assert not any(x[1].endswith("/refresh_access_token") for x in calls)  # the token is minutes old: Instagram would refuse to renew it
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    c.app.state.db.execute("UPDATE connection SET token_issued_at = ?", (old,))
    calls.clear()
    c.post("/connections/instagram/refresh")
    assert any(x[1].endswith("/refresh_access_token") for x in calls)
    assert any(x[1].endswith("/me") and x[2]["access_token"] == "LONG2" for x in calls)


def test_refresh_without_a_connection_and_disconnect(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    assert c.post("/connections/instagram/refresh").status_code == 404
    fake_instagram(monkeypatch)
    _, q = begin(c)
    finish(c, q["state"][0])
    assert c.delete("/connections/instagram").json() == {"disconnected": True}
    assert c.get("/connections").json()["connections"][0]["connected"] is False
    assert c.app.state.db.query("SELECT * FROM connection") == []


def test_an_expired_token_is_flagged(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch)
    fake_instagram(monkeypatch)
    _, q = begin(c)
    finish(c, q["state"][0])
    c.app.state.db.execute("UPDATE connection SET expires_at = ?", ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
    assert c.get("/connections").json()["connections"][0]["expired"] is True


def test_with_login_required_each_owner_sees_only_their_own_connection(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch, require=True)
    assert c.get("/connections").status_code == 401
    assert c.get("/auth/instagram/login").headers["location"].endswith("/#/login")  # not signed in to the app: no Instagram redirect
    fake_instagram(monkeypatch)
    for email in ("a@example.com", "b@example.com"):
        c.cookies.clear()
        c.cookies.set(auth.SESSION_COOKIE, auth.sign(c.app, {"email": email, "name": email, "sub": email}, 600))
        if email == "a@example.com":
            _, q = begin(c)
            finish(c, q["state"][0])
    assert c.get("/connections").json()["connections"][0]["connected"] is False  # b has nothing
    c.cookies.clear()
    c.cookies.set(auth.SESSION_COOKIE, auth.sign(c.app, {"email": "a@example.com", "name": "a", "sub": "a"}, 600))
    assert c.get("/connections").json()["connections"][0]["connected"] is True


def test_insights_are_read_when_granted_and_quiet_when_not(tmp_path, monkeypatch):
    import asyncio
    for granted in (True, False):
        fake_instagram(monkeypatch, insights=granted)
        profile = {"followers_count": 1}
        media = [{"id": "m1"}]
        asyncio.run(connections._insights(connections.httpx.AsyncClient(), "tok", profile, media))
        if granted:
            assert profile["insights"] == {"window_days": 28, "reach": 1200, "profile_views": 85}
            assert media[0]["reach"] == 300 and media[0]["saved"] == 9
        else:
            assert "insights" not in profile and "reach" not in media[0]
