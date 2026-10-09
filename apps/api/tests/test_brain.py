"""Agent orchestrate: Groq turns an utterance into bounded app actions. One model, one JSON object, junk is rejected."""
import json

import httpx
import pytest

from app import brain
from b_helpers import make_client

NAVIGATE = json.dumps({"say": "Opening the plan.", "actions": [{"type": "navigate", "params": {"screen": "plan"}}]})


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

    async def post(self, url, **kw):
        Fake.calls.append((url, kw))
        for part, answer in Fake.plan.items():
            if part in url:
                return answer(url, kw) if callable(answer) else answer
        return httpx.Response(404, json={})


def groq_reply(text=NAVIGATE):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    Fake.calls, Fake.plan = [], {}
    monkeypatch.setattr(brain.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    return app, c, monkeypatch


def ask(c, **body):
    return c.post("/agent/orchestrate", json={"utterance": "start the plan", **body})


def test_no_key_is_503(rig):
    _, c, mp = rig
    r = ask(c)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "brain_not_configured"
    assert Fake.calls == []  # the utterance never leaves without a key


def test_the_switch_in_settings_is_respected(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    c.put("/settings/toggles/groq", json={"enabled": False})
    assert ask(c).status_code == 503
    assert Fake.calls == []


def test_happy_path_returns_say_and_actions(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.plan = {"groq.com": groq_reply()}
    out = ask(c, state={"campaign_id": "c1"}).json()
    assert out == {"say": "Opening the plan.", "actions": [{"type": "navigate", "params": {"screen": "plan"}}]}
    sent = Fake.calls[-1][1]["json"]
    assert sent["model"] == "qwen/qwen3.8-27b" and sent["response_format"] == {"type": "json_object"}
    system = sent["messages"][0]["content"]
    assert "POST /campaign/generate" in system and "/plan/approve" in system and "/change/propose" in system and "/assets/{id}/video" in system
    assert sent["messages"][1]["content"] == json.dumps({"utterance": "start the plan", "state": {"campaign_id": "c1"}}, ensure_ascii=False)


def test_a_plain_answer_has_no_actions(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.plan = {"groq.com": groq_reply(json.dumps({"say": "You have no campaign yet.", "actions": []}))}
    assert ask(c).json()["actions"] == []


def test_a_bad_reply_is_502(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.plan = {"groq.com": groq_reply("just plain words, no json")}
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "brain_bad_reply"


def test_an_invented_action_type_is_rejected(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.plan = {"groq.com": groq_reply(json.dumps({"say": "x", "actions": [{"type": "delete_everything", "params": {}}]}))}
    assert ask(c).json()["detail"]["code"] == "brain_bad_reply"


def test_a_provider_failure_is_reported(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.plan = {"groq.com": httpx.Response(500, json={})}
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "brain_provider_error"


def test_missing_utterance_is_422(rig):
    _, c, mp = rig
    assert c.post("/agent/orchestrate", json={}).status_code == 422
    assert c.post("/agent/orchestrate", json={"utterance": ""}).status_code == 422


@pytest.mark.parametrize("raw,ok", [
    (NAVIGATE, True),
    ('```json\n{"say": "Fenced.", "actions": []}\n```', True),
    (json.dumps({"say": "Facts.", "actions": [{"type": "set_offer_facts", "params": {"item": "filter coffee"}}]}), True),
    (json.dumps({"say": "Change.", "actions": [{"type": "apply_change", "params": {"text": "make it 50"}}]}), True),
    (json.dumps({"say": "Video.", "actions": [{"type": "generate_video", "params": {"asset_id": "a1", "motion_opt_in": True}}]}), True),
    ("not json", False),
    (json.dumps({"actions": []}), False),  # no say
    (json.dumps({"say": "x", "actions": "nope"}), False),
    (json.dumps({"say": "x", "actions": [{"type": "nope"}]}), False),
    (json.dumps({"say": "x", "actions": [{"type": "navigate", "params": []}]}), False),
    ("[]", False),  # not an object
])
def test_the_strict_parser(raw, ok):
    if ok:
        out = brain.parse_reply(raw)
        assert isinstance(out["say"], str) and isinstance(out["actions"], list)
    else:
        with pytest.raises(brain.BrainBadReply):
            brain.parse_reply(raw)


def test_not_text_is_rejected():
    with pytest.raises(brain.BrainBadReply):
        brain.parse_reply(None)
