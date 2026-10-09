"""Keep the developer's real .env out of the tests: login gate, Google client and CORS settings must not leak in."""
import pytest

LOCAL_ONLY = ("REQUIRE_LOGIN", "ALLOWED_EMAILS", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FRONTEND_URL", "SESSION_SECRET",
              "CORS_ORIGINS", "GOOGLE_REDIRECT_URI", "COOKIE_SECURE", "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_REDIRECT_URI", "YOUTUBE_REDIRECT_URI", "SMTP_HOST", "PUBLIC_BASE_URL", "TEXT_RPM", "IMAGE_RPM", "VIDEO_RPM", "TOKEN_PLAN_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "AGNEZ_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY", "AGNEZ_AGENT_ID", "ELEVENLABS_AGENT_ID", "AGNES_API_KEY")


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in LOCAL_ONLY:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SCHEDULER", "off")  # the background loop must never send anything during a test
