import json
"""Planner, calibration, provider-key and STT routes."""
import io
import wave

from fastapi.testclient import TestClient

from app.config import Settings
from app.lab.voice import groq_stt
from app.main import create_app


def client(tmp_path):
    s = Settings(agnes_api_key=None, agnes_base_url="https://x.test/v1", agnes_origin="https://x.test",
                 database_path=tmp_path / "t.db", assets_dir=tmp_path / "assets")
    return TestClient(create_app(s))


WANTED = [{"lang": l, "channel": c, "audience_id": "a1"} for l in ("en", "kn", "hi") for c in ("instagram", "whatsapp")]


def test_planner_route_fits_within_limits(tmp_path):
    r = client(tmp_path).post("/planner/solve", json={"wanted": WANTED, "limits": {"time_s": 180, "money_inr": 50, "review_s": 480}})
    assert r.status_code == 200 and r.json()["feasible"]
    assert r.json()["cost"]["review_s"] <= 480


def test_calibration_route_reports_source(tmp_path):
    r = client(tmp_path).get("/calibration")
    assert r.status_code == 200 and r.json()["rpm"]["text"] == 10


def test_provider_keys_are_write_only_and_encrypted(tmp_path):
    c = client(tmp_path)
    r = c.put("/settings/providers/image", json={"provider": "agnes", "api_key": "sk-secret-123456"})
    assert r.status_code == 200 and r.json()["last4"] == "3456" and "api_key" not in r.json()
    assert "sk-secret" not in c.get("/settings/providers").text
    raw = c.app.state.db.query_one("SELECT key_enc FROM provider_keys WHERE capability='image'")["key_enc"]
    assert b"sk-secret" not in raw
    # a blank key on the next save keeps the stored one
    c.put("/settings/providers/image", json={"provider": "agnes", "model": "agnes-image-2.5-flash"})
    assert c.get("/settings/providers").json()["providers"][1]["last4"] == "3456"
    assert c.app.state.agnes._require_key() == "sk-secret-123456"
    c.delete("/settings/providers/image")
    assert c.get("/settings/providers").json()["providers"][1]["key_set"] is False


def test_provider_custom_url_blocks_private_hosts(tmp_path):
    r = client(tmp_path).put("/settings/providers/image", json={"provider": "custom", "base_url": "https://127.0.0.1/v1"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "blocked_url"


def test_stt_rejects_kannada_and_bad_audio(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = client(tmp_path)
    r = c.post("/stt", files={"audio": ("a.wav", _wav(), "audio/wav")}, data={"lang": "kn"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "stt_unsupported"
    r = c.post("/stt", files={"audio": ("a.wav", b"not audio", "audio/wav")}, data={"lang": "en"})
    assert r.status_code == 422


def _tone(seconds=0.2, amp=8000, rate=16000):
    import math
    b = io.BytesIO()
    w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(b"".join(int(amp * math.sin(i / 8)).to_bytes(2, "little", signed=True) for i in range(int(rate * seconds)))); w.close()
    return b.getvalue()


def _wav(amp=8000, seconds=0.2):
    """Audible audio (a tone), so tests exercise the engines. A silent file is caught before any engine is called."""
    import math
    b = io.BytesIO()
    w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"".join(int(amp * math.sin(i / 8)).to_bytes(2, "little", signed=True) for i in range(int(16000 * seconds)))); w.close()
    return b.getvalue()


def test_toggles_report_key_state_and_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = client(tmp_path)
    t = {x["name"]: x for x in c.get("/settings/toggles").json()["toggles"]}
    assert t["groq"]["configured"] and t["groq"]["enabled"] and t["groq"]["active"]
    assert t["gemini"]["configured"] is False and t["gemini"]["active"] is False
    off = c.put("/settings/toggles/groq", json={"enabled": False}).json()
    assert off["enabled"] is False and off["active"] is False
    assert {x["name"]: x["enabled"] for x in c.get("/settings/toggles").json()["toggles"]}["groq"] is False
    assert c.put("/settings/toggles/nope", json={"enabled": True}).status_code == 404
    assert "gsk_test" not in c.get("/settings/toggles").text  # keys are never returned


def test_groq_is_used_for_kannada_only_when_switched_on(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    seen = {}

    async def fake(data, lang, key, **kw):
        seen["lang"], seen["key"] = lang, key
        return {"text": "ok", "segments": [], "lang": lang, "provider": "groq", "model": "m", "latency_ms": 1}

    monkeypatch.setattr("app.lab.voice.groq_stt.transcribe", fake)
    c = client(tmp_path)
    files = {"audio": ("a.wav", _wav(), "audio/wav")}
    r = c.post("/stt", files=files, data={"lang": "kn"})
    assert r.status_code == 200 and r.json()["provider"] == "groq" and seen["lang"] == "kn"
    c.put("/settings/toggles/groq", json={"enabled": False})
    off = c.post("/stt", files=files, data={"lang": "kn"})
    assert off.status_code == 422 and "Switch Groq on in Settings" in off.json()["detail"]["message"]


def test_groq_failure_is_a_clean_502(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")

    async def boom(*a, **k):
        raise groq_stt.GroqError("Groq is rate limiting this key. Try again in a minute.")

    monkeypatch.setattr("app.lab.voice.groq_stt.transcribe", boom)
    r = client(tmp_path).post("/stt", files={"audio": ("a.wav", _wav(), "audio/wav")}, data={"lang": "kn"})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "groq_failed"


def test_groq_client_never_passes_on_the_response_body():
    import asyncio
    import httpx

    def handler(request):
        if request.headers["authorization"] != "Bearer good":
            return httpx.Response(401, json={"error": "invalid key gsk_secretecho"})
        return httpx.Response(200, json={"text": " ನಮಸ್ಕಾರ "})

    async def run(key):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await groq_stt.transcribe(b"x", "kn", key, client=client)

    assert asyncio.run(run("good"))["text"] == "ನಮಸ್ಕಾರ"
    try:
        asyncio.run(run("bad"))
        raise AssertionError("expected an error")
    except groq_stt.GroqError as exc:
        assert "401" in str(exc) and "gsk_secretecho" not in str(exc)


def test_silent_audio_never_reaches_an_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    async def spy(*a, **k):
        calls.append(1)
        return {"text": "Thank you.", "segments": [], "lang": "kn", "provider": "groq", "model": "m", "latency_ms": 1}

    monkeypatch.setattr("app.lab.voice.groq_stt.transcribe", spy)
    c = client(tmp_path)
    r = c.post("/stt", files={"audio": ("a.wav", _wav(amp=40), "audio/wav")}, data={"lang": "kn"}).json()
    assert r["silent"] is True and r["text"] == "" and calls == []  # Whisper would have invented "Thank you."
    loud = c.post("/stt", files={"audio": ("a.wav", _wav(), "audio/wav")}, data={"lang": "kn"}).json()
    assert loud["text"] == "Thank you." and calls == [1]


def test_oversized_recordings_are_refused(tmp_path):
    c = client(tmp_path)
    big = b"\0" * (10 * 1024 * 1024 + 10)
    r = c.post("/stt", files={"audio": ("a.wav", big, "audio/wav")}, data={"lang": "kn"})
    assert r.status_code == 413 and r.json()["detail"]["code"] == "audio_too_large"


def test_engine_map_tells_the_browser_what_will_transcribe_each_language(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    c = client(tmp_path)
    on = c.get("/stt/languages").json()
    assert on["engines"]["kn"] == "groq" and on["groq"]["active"] is True
    c.put("/settings/toggles/groq", json={"enabled": False})
    off = c.get("/stt/languages").json()
    assert off["engines"]["kn"] is None and off["groq"]["active"] is False
    assert "gsk_test" not in json.dumps(off)


def test_is_silent_reads_real_levels():
    from app.extras import is_silent
    assert is_silent(_wav(amp=10)) and not is_silent(_wav(amp=8000))
    assert is_silent(b"not audio") is False  # unreadable is reported by the engine, not hidden as silence


def test_silent_audio_never_reaches_an_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    async def spy(*a, **k):
        calls.append(1)
        return {"text": "Thank you.", "segments": [], "lang": "kn", "provider": "groq", "model": "m", "latency_ms": 1}

    monkeypatch.setattr("app.lab.voice.groq_stt.transcribe", spy)
    c = client(tmp_path)
    r = c.post("/stt", files={"audio": ("a.wav", _wav(amp=40), "audio/wav")}, data={"lang": "kn"}).json()
    assert r["silent"] is True and r["text"] == "" and calls == []  # Whisper would have invented "Thank you."
    loud = c.post("/stt", files={"audio": ("a.wav", _wav(), "audio/wav")}, data={"lang": "kn"}).json()
    assert loud["text"] == "Thank you." and calls == [1]


def test_oversized_recordings_are_refused(tmp_path):
    c = client(tmp_path)
    big = b"\0" * (10 * 1024 * 1024 + 10)
    r = c.post("/stt", files={"audio": ("a.wav", big, "audio/wav")}, data={"lang": "kn"})
    assert r.status_code == 413 and r.json()["detail"]["code"] == "audio_too_large"


def test_engine_map_tells_the_browser_what_will_transcribe_each_language(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    c = client(tmp_path)
    on = c.get("/stt/languages").json()
    assert on["engines"]["kn"] == "groq" and on["groq"]["active"] is True
    c.put("/settings/toggles/groq", json={"enabled": False})
    off = c.get("/stt/languages").json()
    assert off["engines"]["kn"] is None and off["groq"]["active"] is False
    assert "gsk_test" not in json.dumps(off)


def test_is_silent_reads_real_levels():
    from app.extras import is_silent
    assert is_silent(_wav(amp=10)) and not is_silent(_wav(amp=8000))
    assert is_silent(b"not audio") is False  # unreadable is reported by the engine, not hidden as silence


def test_planner_uses_the_configured_rpm(monkeypatch):
    from app.extras import latest_calibration
    monkeypatch.delenv("TEXT_RPM", raising=False); monkeypatch.delenv("IMAGE_RPM", raising=False); monkeypatch.delenv("VIDEO_RPM", raising=False)
    assert latest_calibration().rpm == {"text": 10, "image": 10, "video": 1}  # free tier defaults
    monkeypatch.setenv("TEXT_RPM", "1000"); monkeypatch.setenv("VIDEO_RPM", "5"); monkeypatch.setenv("IMAGE_RPM", "oops")
    c = latest_calibration()
    assert c.rpm == {"text": 1000.0, "image": 10, "video": 5.0} and "TEXT_RPM" in c.source  # a bad value is ignored, not fatal


def test_text_provider_is_fixed_and_reports_real_groq_state(tmp_path, monkeypatch):
    c = client(tmp_path)
    assert c.put("/settings/providers/text",json={"provider":"agnes","api_key":"unused"}).status_code == 409
    row=c.get("/settings/providers").json()["providers"][0]
    assert row["provider"] == "groq" and row["model"] == "qwen/qwen3.8-27b" and row["active"] is False
    monkeypatch.setenv("GROQ_API_KEY","test-key")
    assert c.get("/settings/providers").json()["providers"][0]["active"] is True
    c.put("/settings/toggles/groq",json={"enabled":False})
    assert c.get("/settings/providers").json()["providers"][0]["active"] is False
