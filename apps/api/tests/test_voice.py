"""Voice token: a short-lived ElevenLabs token behind the owner's switch. The key and the agent id never leave the server."""
import json

import httpx
import pytest

from app import voice
from b_helpers import make_client

TOKEN = "convai-token-abc"


class Fake:
    """A stand-in for httpx.AsyncClient that answers by URL and records what it was sent."""
    calls: list = []
    plan: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aclose(self):
        return None

    async def get(self, url, **kw):
        Fake.calls.append((url, kw))
        for part, answer in Fake.plan.items():
            if part in url:
                return answer(url, kw) if callable(answer) else answer
        return httpx.Response(404, json={})


def token_reply():
    return httpx.Response(200, json={"conversation_id": "c1", "token": TOKEN})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    Fake.calls, Fake.plan = [], {}
    monkeypatch.setattr(voice.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    return app, c, monkeypatch


def test_no_key_and_no_agent_is_503(rig):
    _, c, mp = rig
    r = c.get("/voice/token")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "voice_not_configured"
    assert Fake.calls == []  # nothing leaves the server


def test_the_switch_in_settings_is_respected(rig):
    _, c, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    mp.setenv("AGNEZ_AGENT_ID", "agent_123")
    c.put("/settings/toggles/elevenlabs", json={"enabled": False})
    r = c.get("/voice/token")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "voice_not_configured"
    assert Fake.calls == []


def test_a_key_without_an_agent_id_is_503(rig):
    _, c, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")  # the agent id is missing
    assert c.get("/voice/token").status_code == 503
    assert Fake.calls == []


def test_happy_path_mints_a_token_and_hides_the_secrets(rig):
    _, c, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    mp.setenv("AGNEZ_AGENT_ID", "agent_123")
    Fake.plan = {"conversation/token": token_reply()}
    r = c.get("/voice/token")
    assert r.status_code == 200 and r.json() == {"conversation_token": TOKEN}
    url, kw = Fake.calls[-1]
    assert url == voice.TOKEN_URL
    assert kw["params"]["agent_id"] == "agent_123" and kw["headers"]["xi-api-key"] == "el-key"
    body = json.dumps(r.json())
    assert "el-key" not in body and "agent_123" not in body


def test_the_shorter_key_name_works_too(rig):
    _, c, mp = rig
    mp.setenv("ELEVENLABS_API_KEY", "alt-key")
    mp.setenv("ELEVENLABS_AGENT_ID", "agent_alt")
    Fake.plan = {"conversation/token": token_reply()}
    assert c.get("/voice/token").json() == {"conversation_token": TOKEN}
    assert Fake.calls[-1][1]["headers"]["xi-api-key"] == "alt-key"


def test_a_provider_failure_is_502(rig):
    _, c, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    mp.setenv("AGNEZ_AGENT_ID", "agent_123")
    Fake.plan = {"conversation/token": httpx.Response(401, json={})}
    r = c.get("/voice/token")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "voice_provider_error"


def test_a_tokenless_reply_is_502(rig):
    _, c, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    mp.setenv("AGNEZ_AGENT_ID", "agent_123")
    Fake.plan = {"conversation/token": httpx.Response(200, json={"conversation_id": "c1"})}
    r = c.get("/voice/token")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "voice_provider_error"
