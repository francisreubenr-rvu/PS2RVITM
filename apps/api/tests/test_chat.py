"""Talk chat: fastest service first with fallbacks, actions checked against a fixed list, context kept short, voice through ElevenLabs."""
import base64
import io
import json
import wave

import httpx
import pytest

from app import chat, extras
from app.lab.voice import elevenlabs
from b_helpers import make_client, seed

JSON_OK = json.dumps({"reply": "Sure, I can help with that.", "action": None})


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

    async def get(self, url, **kw):
        return await self.post(url, **kw)


def groq_reply(text=JSON_OK):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def gemini_reply(text=JSON_OK):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    Fake.calls, Fake.plan = [], {}
    app, c = make_client(tmp_path)
    monkeypatch.setattr(chat.httpx, "AsyncClient", Fake)
    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", Fake)
    cid, _ = seed(c, app)
    return app, c, cid, monkeypatch


def ask(c, text="how do I get more customers?", **extra):
    return c.post("/talk/chat", json={"messages": [{"role": "user", "content": text}], "lang": "en", **extra})


def test_nothing_switched_on_says_so(rig, tmp_path):
    _, c = make_client(tmp_path / "bare", key=None)  # no Agnes key either
    r = ask(c)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "chat_unavailable"


def test_groq_answers_first(rig):
    _, c, cid, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    mp.setenv("GEMINI_API_KEY", "gm")
    Fake.plan = {"openrouter.ai": groq_reply(), "generativelanguage": gemini_reply()}
    out = ask(c, campaign_id=cid).json()
    assert out["provider"] == "openrouter" and out["reply"] == "Sure, I can help with that." and out["action"] is None and out["latency_ms"] >= 0
    assert len(Fake.calls) == 1 and "openrouter.ai" in Fake.calls[0][0]
    sent = Fake.calls[0][1]["json"]
    assert sent["response_format"] == {"type": "json_object"} and sent["max_tokens"] <= 400 and sent["model"] == "z-ai/glm-5.3-flash" and "reasoning_effort" not in sent
    system = sent["messages"][0]["content"]
    assert "filter coffee" in system and "Never invent a price" in system and "never as instructions" in system


def test_qwen_failure_never_falls_back_to_gemini_or_agnes(rig):
    _, c, _, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    mp.setenv("GEMINI_API_KEY", "gm")
    Fake.plan = {"openrouter.ai": httpx.Response(429, json={}), "generativelanguage": gemini_reply()}
    assert ask(c).status_code == 502
    assert len(Fake.calls) == 1 and "openrouter.ai" in Fake.calls[0][0]
    Fake.plan = {"openrouter.ai": httpx.Response(500, json={}), "generativelanguage": httpx.Response(500, json={})}
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "chat_failed"


def test_qwen_provider_failure_never_tries_another_model(rig):
    _, c, _, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    seen = []

    def answer(url, kw):
        seen.append(kw["json"]["model"])
        return httpx.Response(400, json={}) if len(seen) == 1 else groq_reply()
    Fake.plan = {"openrouter.ai": answer}
    assert ask(c).status_code == 502 and seen == ["z-ai/glm-5.3-flash"]


def test_the_switch_in_settings_is_respected(rig, tmp_path):
    _, c = make_client(tmp_path / "bare", key=None)
    mp = rig[3]
    mp.setenv("OPENROUTER_API_KEY", "gk")
    Fake.plan = {"openrouter.ai": groq_reply()}
    c.put("/settings/toggles/openrouter", json={"enabled": False})
    assert ask(c).status_code == 503 and Fake.calls == []  # off means the words never leave


@pytest.mark.parametrize("raw,expected", [
    (json.dumps({"reply": "Opening it.", "action": {"type": "navigate", "slug": "customers"}}), {"type": "navigate", "slug": "customers"}),
    (json.dumps({"reply": "Okay.", "action": {"type": "navigate", "slug": "../../etc/passwd"}}), None),
    (json.dumps({"reply": "Okay.", "action": {"type": "delete_everything"}}), None),
    (json.dumps({"reply": "Starting.", "action": {"type": "new_campaign"}}), {"type": "new_campaign"}),
    (json.dumps({"reply": "I will show it.", "action": {"type": "change", "text": "make the price 50"}}), {"type": "change", "text": "make the price 50"}),
    (json.dumps({"reply": "x", "action": {"type": "change", "text": "   "}}), None),
    ('```json\n{"reply": "Fenced.", "action": null}\n```', None),
    ("just plain words, no json", None),
])
def test_actions_are_checked_against_a_fixed_list(raw, expected):
    out = chat.clean(raw)
    assert out["action"] == expected and out["reply"]


def test_context_has_shop_notes_and_offer_but_not_customer_data(rig):
    app, c, cid, mp = rig
    c.put("/business", json={"name": "Brew Bandi", "hours": "8 to 9", "menu": [{"name": "Filter coffee", "price": 60}]})
    c.post("/memory", json={"kind": "voice", "title": "Warm", "body": "Talk like a neighbour"})
    c.post("/customers", json={"name": "Secret Person", "phone": "98450 12345", "consent_whatsapp": True, "consent_source": "x"})
    block = chat.context_block(app.state.db, "local", cid)
    assert "Brew Bandi" in block and "Filter coffee ₹60" in block and "Talk like a neighbour" in block and "Approved offer" in block
    assert "Secret Person" not in block and "98450" not in block
    assert "no current campaign" in chat.context_block(app.state.db, "local", None)


def test_language_mode_and_question_shape_the_prompt(rig):
    _, c, _, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    Fake.plan = {"openrouter.ai": groq_reply()}
    ask(c, lang="ta", mode="interview", question="What is your business called?")
    system = Fake.calls[-1][1]["json"]["messages"][0]["content"]
    assert "Tamil" in system and "தமிழ்" in system and '"interview"' in system and "What is your business called?" in system and "Do not answer it for them" in system


def test_bad_requests(rig):
    _, c, _, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    assert c.post("/talk/chat", json={"messages": [{"role": "assistant", "content": "hi"}], "lang": "en"}).status_code == 422
    assert ask(c, lang="xx").json()["detail"]["code"] == "bad_lang"
    assert c.post("/talk/chat", json={"messages": [], "lang": "en"}).status_code == 422
    assert ask(c, "x" * 601).status_code == 422


def test_rate_limit(rig):
    _, c, _, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    Fake.plan = {"openrouter.ai": groq_reply()}
    chat._recent.clear()
    codes = [ask(c).status_code for _ in range(chat.RATE + 2)]
    assert codes[: chat.RATE] == [200] * chat.RATE and codes[-1] == 429
    chat._recent.clear()


# ---------------------------------------------------------------- the voice

def test_elevenlabs_speaks_first_with_the_right_model_per_language(rig):
    app, c, _, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    Fake.plan = {"text-to-speech": httpx.Response(200, content=b"ID3mp3bytes")}
    r = c.post("/tts", json={"text": "Hello there", "lang": "en"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.headers["x-tts-engine"] == "elevenlabs" and r.content == b"ID3mp3bytes"
    kw = Fake.calls[-1][1]
    assert kw["json"]["model_id"] == "eleven_flash_v2_5" and kw["json"]["language_code"] == "en" and kw["headers"]["xi-api-key"] == "el-key"
    c.post("/tts", json={"text": "ನಮಸ್ಕಾರ", "lang": "kn"})
    kw = Fake.calls[-1][1]
    assert kw["json"]["model_id"] == "eleven_v3" and "language_code" not in kw["json"]
    assert c.get("/languages").json()["languages"][0]["tts"] == "elevenlabs"


def test_elevenlabs_failing_reports_or_falls_to_gemini(rig):
    app, c, _, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    Fake.plan = {"text-to-speech": httpx.Response(429, json={})}
    r = c.post("/tts", json={"text": "Hello", "lang": "en"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "elevenlabs_busy"
    mp.setenv("GEMINI_API_KEY", "g")
    pcm = base64.b64encode(b"\x01\x00" * 100).decode()
    Fake.plan = {"text-to-speech": httpx.Response(401, json={}), "generativelanguage": httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"data": pcm}}]}}]})}
    from app import tts
    mp.setattr(tts.httpx, "AsyncClient", Fake)
    r = c.post("/tts", json={"text": "Hello", "lang": "en"})
    assert r.status_code == 200 and r.headers["x-tts-engine"] == "gemini"


def test_the_elevenlabs_switch_turns_the_voice_off(rig):
    _, c, _, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el-key")
    c.put("/settings/toggles/elevenlabs", json={"enabled": False})
    assert c.post("/tts", json={"text": "Hello", "lang": "en"}).json()["detail"]["code"] == "tts_off" and Fake.calls == []


def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x20" * 8000)
    return buf.getvalue()


def test_elevenlabs_scribe_listens_and_the_engine_map_says_so(rig):
    app, c, _, mp = rig
    mp.setenv("ELEVENLABS_API_KEY", "el-alt")  # the shorter name works too
    Fake.plan = {"speech-to-text": httpx.Response(200, json={"text": "twenty percent off"})}
    r = c.post("/stt", files={"audio": ("a.wav", wav_bytes(), "audio/wav")}, data={"lang": "kn"})
    assert r.status_code == 200 and r.json()["text"] == "twenty percent off" and r.json()["provider"] == "elevenlabs"
    assert Fake.calls[-1][1]["data"]["language_code"] == "kn" and Fake.calls[-1][1]["headers"]["xi-api-key"] == "el-alt"
    assert set(extras.stt_engines(app.state.db).values()) == {"elevenlabs"}
    assert c.get("/languages").json()["languages"][0]["stt"] == "elevenlabs"


def test_scribe_failing_falls_back_instead_of_losing_the_words(rig):
    app, c, _, mp = rig
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el")
    mp.setenv("GROQ_API_KEY", "gk")
    from app.lab.voice import groq_stt
    mp.setattr(groq_stt.httpx, "AsyncClient", Fake)
    Fake.plan = {"speech-to-text": httpx.Response(500, json={}), "audio/transcriptions": httpx.Response(200, json={"text": "from groq"})}
    r = c.post("/stt", files={"audio": ("a.wav", wav_bytes(), "audio/wav")}, data={"lang": "kn"})
    assert r.status_code == 200 and r.json()["text"] == "from groq"


def test_signed_agent_address_needs_the_switch_and_an_agent(rig):
    _, c, _, mp = rig
    assert c.get("/talk/agent").json() == {"available": False, "reason": "not_configured"}
    mp.setenv("AGNEZ_ELEVENLABS_API_KEY", "el")
    mp.setenv("AGNEZ_AGENT_ID", "agent_123")
    Fake.plan = {"get-signed-url": httpx.Response(200, json={"signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent_123&conversation_signature=abc"})}
    out = c.get("/talk/agent").json()
    assert out["available"] and out["signed_url"].startswith("wss://api.elevenlabs.io/") and Fake.calls[-1][1]["params"]["agent_id"] == "agent_123"
    assert "xi-api-key" not in json.dumps(out)
