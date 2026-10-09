"""Autopilot, scout and launch. No network."""
import json
from datetime import date

from fastapi.testclient import TestClient

from app import autopilot, launch, scout
from app.config import Settings
from app.main import create_app


class FakeAgnes:
    def __init__(self, reply):
        self.reply = reply

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        return json.dumps(self.reply)


def client(tmp_path, reply=None):
    s = Settings(agnes_api_key="k", agnes_base_url="http://x.invalid/v1", agnes_origin="http://x.invalid",
                 database_path=tmp_path / "t.db", assets_dir=tmp_path / "a")
    app = create_app(s)
    if reply is not None:
        app.state.agnes = FakeAgnes(reply)
    return app, TestClient(app)


# ---- autopilot
def test_autopilot_prefers_channels_that_redeemed_more_and_stays_in_budget(tmp_path):
    app, c = client(tmp_path)
    out = c.post("/autopilot", json={"money_inr": 50, "time_s": 300, "review_s": 150}).json()
    assert out["feasible"] and out["cost"]["review_s"] <= 150
    assert "whatsapp" in out["channels"]  # history: broadcasts redeem about 16%, the best channel
    assert out["channels"][0] == "whatsapp" and out["sentence"].startswith("Write it in")
    assert out["dropped"], "a tight review budget must drop something and say why"


def test_autopilot_says_when_nothing_fits(tmp_path):
    app, c = client(tmp_path)
    out = c.post("/autopilot", json={"review_s": 10, "time_s": 10}).json()
    assert out["feasible"] is False and out["sentence"] is None


def test_autopilot_priorities_come_from_history():
    p = autopilot.priorities(["whatsapp", "instagram_story", "cold_email"])
    assert p["whatsapp"] > p["instagram_story"] and p["cold_email"] == 3.0  # no history: neutral, not bad


# ---- scout
def test_scout_flags_overlap_teaser_and_extension_and_skips_far_events():
    today = date(2026, 10, 10)
    events = [{"name": "Children's Day", "start": "2026-11-14", "end": "2026-11-14", "kind": "fixed", "audiences": ["families"]},
              {"name": "Kannada Rajyotsava", "start": "2026-11-01", "end": "2026-11-01", "kind": "fixed", "audiences": ["families"]},
              {"name": "Gandhi Jayanti", "start": "2026-10-02", "end": "2026-10-02", "kind": "fixed", "audiences": []},
              {"name": "Christmas", "start": "2026-12-25", "end": "2026-12-25", "kind": "fixed", "audiences": []}]
    notes = scout.advise((date(2026, 11, 10), date(2026, 11, 16)), ["families"], events, today)
    by = {n["name"]: n["tone"] for n in notes}
    assert by == {"Children's Day": "overlap", "Kannada Rajyotsava": "teaser"}  # Christmas and an old date are ignored
    assert [n for n in notes if n["name"] == "Children's Day"][0]["suits_audience"] is True
    upcoming = scout.advise(None, [], events, today)
    assert [n["name"] for n in upcoming] == ["Kannada Rajyotsava"]  # 22 days away; a past date and one 35 days out are skipped


def test_scout_has_no_moving_festivals_built_in():
    names = {n for _, _, n, _ in scout.FIXED}
    assert not names & {"Diwali", "Ugadi", "Eid", "Pongal", "Holi", "Dasara"}


def test_owner_events_are_stored_and_validated(tmp_path):
    app, c = client(tmp_path)
    assert c.post("/scout/events", json={"name": "College fest", "start": "2026-11-12", "end": "2026-11-10"}).status_code == 422
    assert c.post("/scout/events", json={"name": "College fest", "start": "2026-13-45"}).status_code in (422,)
    ok = c.post("/scout/events", json={"name": "College fest", "start": "2026-11-12", "end": "2026-11-14"}).json()
    assert ok["name"] == "College fest"
    assert [e["name"] for e in scout._owner_events(app.state.db)] == ["College fest"]
    assert c.delete(f"/scout/events/{ok['id']}").json() == {"deleted": True}
    assert c.get("/campaign/nope/scout").status_code == 404


# ---- launch

def qwen_reply(monkeypatch, reply):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    async def answer(*args):
        return reply
    monkeypatch.setattr(launch, "_qwen", answer)

IDEAS = {"ideas": [
    {"title": "Tiffin service", "business_type": "restaurant", "why": "Low cost.", "startup": "Rs 10,000", "first_month": "15 subscribers",
     "risks": ["FSSAI licence"], "channels": ["WhatsApp"], "items": [{"name": "Thali", "price": 110}]},
    {"title": "Broken", "why": "", "items": []},
    {"title": "Gift boxes", "business_type": "not-a-type", "why": "Photos sell.", "items": [{"name": "Box", "price": -5}, {"name": "Card set", "price": 199}]}]}


def test_ideas_are_trimmed_and_bad_ones_dropped(tmp_path, monkeypatch):
    qwen_reply(monkeypatch, IDEAS)
    app, c = client(tmp_path, IDEAS)
    out = c.post("/launch/ideas", json={"city": "Bengaluru", "skills": ["cook"]}).json()
    assert [i["title"] for i in out["ideas"]] == ["Tiffin service", "Gift boxes"]
    assert out["ideas"][1]["business_type"] == "other" and out["ideas"][1]["items"] == [{"name": "Card set", "price": 199}]
    assert "not advice" in out["disclaimer"]


def test_ideas_fail_cleanly_when_nothing_usable(tmp_path, monkeypatch):
    qwen_reply(monkeypatch, {})
    app, c = client(tmp_path, {"ideas": [{"title": "x"}]})
    assert c.post("/launch/ideas", json={"city": "Bengaluru"}).status_code == 502


def test_names_flag_hindi_and_kannada_as_drafts(tmp_path, monkeypatch):
    qwen_reply(monkeypatch, {"names":["Kaapi Corner", "Brew Bandi"], "taglines":[{"en":"Warm cups.", "hi":"गरम चाय।", "kn":"ಬಿಸಿ ಕಾಫಿ."}]})
    app, c = client(tmp_path, {"names": ["Kaapi Corner", "Brew Bandi"], "taglines": [{"en": "Warm cups.", "hi": "गरम चाय।", "kn": "ಬಿಸಿ ಕಾಫಿ."}]})
    out = c.post("/launch/names", json={"idea": "Filter coffee kiosk", "city": "Bengaluru"}).json()
    assert out["names"] == ["Kaapi Corner", "Brew Bandi"] and out["needs_native_review"] == ["hi", "kn"]


def test_handoff_sentence_is_composed_by_code_and_reads_in_the_agent(tmp_path):
    app, c = client(tmp_path)
    out = c.post("/launch/handoff", json={"name": "Kaapi Corner", "business_type": "cafe", "city": "Bengaluru", "item": "Filter coffee",
                                           "discount_percent": 15, "days": ["sat", "sun"]}).json()["idea"]
    assert out == ("I run Kaapi Corner, a cafe in Bengaluru. I want to promote an offer: 15% off Filter coffee on Saturday and Sunday, "
                   "in English and Kannada, on WhatsApp and poster.")
    from app import agent  # every phrase the agent would quote is in the sentence
    brief = {"fields": {"business_name": "Kaapi Corner", "business_type": "cafe", "area": "Bengaluru", "discount_percent": "15%",
                        "offer_item": "Filter coffee", "days": "Saturday and Sunday", "languages": "English and Kannada", "channels": "WhatsApp and poster"}}
    assert agent.ground_brief(out, brief)["dropped"] == []


def test_taglines_with_stray_scripts_are_withheld():
    assert launch.script_ok("ನಿಮ್ಮ ಮನೆಗೆ ತಾಜಾ ಬೇಕಿಂಗ್", "kn") and launch.script_ok("आपके घर के लिए ताज़ा", "hi")
    assert not launch.script_ok("ನಿಮ್ಮ ಮನೆಯთვის ತಾಜಾ", "kn")  # a Georgian word slipped in
    assert not launch.script_ok("आपके घर ಮನೆ", "hi") and not launch.script_ok("only english", "kn")
    out = launch.clean_names({"names": ["A Name"], "taglines": [{"en": "Warm.", "hi": "गरम।", "kn": "ಮನೆಯთვის"}]})
    assert out["taglines"][0]["hi"] == "गरम।" and out["taglines"][0]["kn"] == ""
