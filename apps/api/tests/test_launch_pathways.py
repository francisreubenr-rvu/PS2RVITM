"""Build my business pathways: Groq Qwen turns the answers into three or four pathways. No network; the provider is faked.

The pathways route is the only Groq caller in launch.py, and it uses one model (qwen, GROQ_CHAT_MODEL as the override). These
tests pin that, the strict shaping of the reply, and the honest not-configured answer when Groq is off or unkeyed.
"""
import json

import httpx
import pytest

from app import brain, launch
from b_helpers import make_client


class Fake:
    """A stand-in for httpx.AsyncClient: records what was sent and answers with a canned Response."""

    calls: list = []
    reply = None

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
        return Fake.reply(url, kw) if callable(Fake.reply) else Fake.reply


def groq_reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


FOUR = [{"title": "Home tiffin", "summary": "Cook and deliver lunch boxes.", "why": "Fits cooking and a small weekly budget.",
         "first_move": "Cook for five neighbours.", "money": "Rs 2,000 a week covers ingredients", "time": "15 hours a week",
         "risk": "Needs an FSSAI licence"},
        {"title": "Repair bench", "summary": "Fix phones and laptops.", "why": "Fits repair skills and a bench at home.",
         "first_move": "Take five walk-in jobs.", "money": "Rs 3,000 a week for tools", "time": "20 hours a week", "risk": "Parts upfront"},
        {"title": "Tuition sessions", "summary": "Teach maths to school students.", "why": "Fits teaching and no stock needed.",
         "first_move": "Run one free class.", "money": "Nothing beyond a whiteboard", "time": "10 hours a week", "risk": "Seasonal demand"},
        {"title": "Tailoring orders", "summary": "Alter and stitch clothes.", "why": "Fits tailoring with a sewing machine at home.",
         "first_move": "Alter ten items.", "money": "Rs 1,500 a week for thread and parts", "time": "18 hours a week", "risk": "Late deliveries"}]

BODY = {"city": "Bengaluru", "skills": ["Cooking / baking"], "amount_per_week": 2500, "hours_per_week": 20,
        "avoid": "no late nights", "name": "Mane Ruchi", "tagline": "The taste of home."}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    Fake.calls, Fake.reply = [], groq_reply(json.dumps({"pathways": FOUR}))
    monkeypatch.setattr(launch.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    return app, c, monkeypatch


def ask(c, **body):
    return c.post("/launch/pathways", json={**BODY, **body})


def test_no_key_is_503_and_never_calls_the_planner(rig):
    _, c, _ = rig
    r = ask(c)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "brain_not_configured"
    assert Fake.calls == []  # the answers never leave without a key


def test_the_settings_switch_is_respected(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    c.put("/settings/toggles/groq", json={"enabled": False})
    r = ask(c)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "brain_not_configured"
    assert Fake.calls == []


def test_happy_path_returns_three_or_four_bounded_pathways(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    out = ask(c).json()
    assert len(out["pathways"]) == 4
    assert [p["id"] for p in out["pathways"]] == ["path0", "path1", "path2", "path3"]
    for p in out["pathways"]:
        assert set(p) == {"id", "title", "summary", "why", "first_move", "money", "time", "risk"}
    assert out["model"] == "qwen/qwen3.8-27b" and "not advice" in out["disclaimer"]


def test_the_planner_is_told_only_the_answers_and_the_one_model(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    ask(c)
    sent = Fake.calls[-1][1]["json"]
    assert sent["model"] == brain.GROQ_MODEL == "qwen/qwen3.8-27b" and "gpt-oss" not in sent["model"]
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["messages"][1]["content"] == json.dumps(BODY, ensure_ascii=False)
    system = sent["messages"][0]["content"]
    assert "pathways" in system and "exactly four" in system


def test_a_shortlist_is_dropped_and_too_few_is_502(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    # one of three is unusable (no summary), so only two survive and the route refuses to show a two-item shortlist
    Fake.reply = groq_reply(json.dumps({"pathways": [FOUR[0], FOUR[1], {"title": "No summary", "why": "x"}]}))
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "pathways_failed"


def test_a_bad_reply_is_502(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.reply = groq_reply("just words, no json")
    assert ask(c).json()["detail"]["code"] == "pathways_failed"


def test_a_provider_failure_is_reported(rig):
    _, c, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.reply = httpx.Response(500, json={})
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "pathways_failed"


def test_missing_city_is_422(rig):
    _, c, _ = rig
    assert c.post("/launch/pathways", json={"skills": []}).status_code == 422


def test_clean_pathways_trims_drops_and_bounds():
    raw = [{"title": "  A  ", "summary": " s ", "why": " w ", "extra": "invented", "title_unused": "x"},
           {"title": "B", "why": "w"},  # no summary
           {"summary": "s", "why": "w"},  # no title
           {"title": "C", "summary": "s", "why": "w"},
           {"title": "D", "summary": "s", "why": "w"},
           {"title": "E", "summary": "s", "why": "w"}]  # a fifth is cut
    out = launch.clean_pathways(raw)
    assert [p["title"] for p in out] == ["A", "C", "D", "E"]
    assert set(out[0]) == {"id", "title", "summary", "why", "first_move", "money", "time", "risk"}
    assert launch.clean_pathways("not a list") == []


class FakeAgnes:
    last = None

    def __init__(self, reply):
        self.reply = reply

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        FakeAgnes.last = messages
        return json.dumps(self.reply)


IDEAS = {"ideas": [{"title": "Tiffin service", "business_type": "restaurant", "why": "Low cost.", "startup": "Rs 10,000",
                    "first_month": "15 subscribers", "risks": ["FSSAI licence"], "channels": ["WhatsApp"],
                    "items": [{"name": "Thali", "price": 110}]}]}


def test_ideas_still_work_and_carry_the_chosen_pathway(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    async def answer(system, user, tokens):
        FakeAgnes.last = [{"content": system}, {"content": json.dumps(user)}]
        return IDEAS
    monkeypatch.setattr(launch, "_qwen", answer)
    app, c = make_client(tmp_path, agnes=FakeAgnes(IDEAS))
    out = c.post("/launch/ideas", json={"city": "Bengaluru", "skills": ["Cooking / baking"], "amount_per_week": 2500,
                                        "pathway": "Home tiffin"}).json()
    assert out["ideas"][0]["title"] == "Tiffin service"
    user = FakeAgnes.last[1]["content"]
    assert "Home tiffin" in user and "2500" in user


def test_ideas_still_work_with_the_older_body(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    async def answer(*args):
        return IDEAS
    monkeypatch.setattr(launch, "_qwen", answer)
    app, c = make_client(tmp_path, agnes=FakeAgnes(IDEAS))
    assert c.post("/launch/ideas", json={"city": "Bengaluru", "skills": ["cook"]}).json()["ideas"][0]["title"] == "Tiffin service"


def test_ideas_and_names_use_qwen_and_respect_switch(rig):
    app, c, mp = rig
    mp.setenv("GROQ_API_KEY", "test-key")
    Fake.reply = groq_reply(json.dumps(IDEAS))
    assert c.post("/launch/ideas", json={"city":"Bengaluru"}).status_code == 200
    Fake.reply = groq_reply(json.dumps({"names":["Brew House"],"taglines":[{"en":"Coffee nearby"}]}))
    assert c.post("/launch/names", json={"city":"Bengaluru","idea":"Coffee kiosk"}).status_code == 200
    assert len(Fake.calls) == 2
    assert all(call[1]["json"]["model"] == brain.GROQ_MODEL for call in Fake.calls)
    c.put("/settings/toggles/groq", json={"enabled":False})
    assert c.post("/launch/ideas", json={"city":"Bengaluru"}).status_code == 503
    assert c.post("/launch/names", json={"city":"Bengaluru","idea":"Coffee kiosk"}).status_code == 503
    assert len(Fake.calls) == 2
