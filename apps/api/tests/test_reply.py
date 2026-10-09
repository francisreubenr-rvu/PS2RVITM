"""Reply agent: answers only from locked facts, escalates the rest. No network."""
import json

from app import plan, reply
from app.schemas import OfferFacts
from app.service import now
from tests.b_helpers import make_client, seed

FACTS = OfferFacts(item="filter coffee", discount_percent=20, timings="Saturday and Sunday, 8 am to 11 am",
                   dates=["2030-01-05", "2030-01-06"], terms="dine-in only", audiences=["students"], languages=["en"], channels=["whatsapp"])
PACKET = {"item": "filter coffee", "discount_percent": 20, "timings": "Saturday and Sunday, 8 am to 11 am", "terms": "dine-in only",
          "area": "Indiranagar"}
PLAN = {"campaign_id": "x", "status": "locked", "business": {"name": "Brew House", "type": "cafe", "area": "Indiranagar"},
        "offer_facts": FACTS.model_dump(), "audiences": ["students"], "languages": ["en"], "channels": ["whatsapp"], "cta": {"value": "@brew"},
        "answers": []}


def answer(**kw):
    return json.dumps({"answerable": True, "intent": "offer", "used": ["discount_percent", "item"],
                       "reply": "Yes, it is 20% off on filter coffee.", **kw})


def test_sensitive_messages_are_never_answered_even_if_the_model_would():
    for msg in ["I am allergic to nuts, is it safe?", "I want a refund", "my friend got sick after the coffee", "can I book for a wedding party"]:
        out = reply.decide(msg, answer(), FACTS, PACKET)
        assert out["status"] == "escalated" and out["intent"] == "sensitive" and out["draft"] is None


def test_a_good_grounded_reply_is_drafted():
    out = reply.decide("how much off is the coffee?", answer(), FACTS, PACKET)
    assert out["status"] == "drafted" and out["used"] == ["discount_percent", "item"]


def test_reply_that_contradicts_the_lock_is_escalated():
    out = reply.decide("how much off?", answer(reply="Yes, it is 30% off on filter coffee."), FACTS, PACKET)
    assert out["status"] == "escalated" and "30" in out["reason"]
    out = reply.decide("do you deliver?", answer(reply="Yes we deliver for 50 rupees.", used=["item"]), FACTS, PACKET)
    assert out["status"] == "escalated"


def test_reply_must_point_at_real_locked_facts():
    assert reply.decide("hi", answer(used=[]), FACTS, PACKET)["status"] == "escalated"
    assert reply.decide("hi", answer(used=["delivery_policy"]), FACTS, PACKET)["status"] == "escalated"


def test_not_answerable_or_garbage_is_escalated():
    assert reply.decide("do you have parking?", json.dumps({"answerable": False, "reason": "No fact about parking."}), FACTS, PACKET)["reason"].startswith("No fact")
    assert reply.decide("hi", "not json at all", FACTS, PACKET)["status"] == "escalated"
    assert reply.decide("hi", None, FACTS, PACKET)["status"] == "escalated"


class FakeAgnes:
    def __init__(self, text):
        self.text, self.calls = text, 0

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        self.calls += 1
        return self.text


def setup(tmp_path, monkeypatch, text, locked=True):
    app, client = make_client(tmp_path, FakeAgnes(text))
    cid, _ = seed(client, app)
    monkeypatch.setattr(reply.plan, "get_plan", lambda db, campaign_id: {**PLAN, "status": "locked" if locked else "draft"})
    return app, client, cid


def test_route_drafts_escalates_and_never_calls_the_model_for_sensitive_messages(tmp_path, monkeypatch):
    app, c, cid = setup(tmp_path, monkeypatch, answer())
    ok = c.post(f"/campaign/{cid}/replies", json={"message": "how much off is the coffee?"}).json()
    assert ok["status"] == "drafted" and ok["draft"].startswith("Yes")
    calls = app.state.agnes.calls
    bad = c.post(f"/campaign/{cid}/replies", json={"message": "I want a refund now"}).json()
    assert bad["status"] == "escalated" and bad["holding"] and app.state.agnes.calls == calls  # no model call at all
    kn = c.post(f"/campaign/{cid}/replies", json={"message": "I want a refund now", "lang": "kn"}).json()
    assert kn["holding_needs_native_review"] is True
    assert len(c.get(f"/campaign/{cid}/replies").json()["replies"]) == 3


def test_replies_need_a_locked_plan(tmp_path, monkeypatch):
    app, c, cid = setup(tmp_path, monkeypatch, answer(), locked=False)
    r = c.post(f"/campaign/{cid}/replies", json={"message": "hello there"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_locked"


def test_edited_reply_is_rechecked_before_approval(tmp_path, monkeypatch):
    app, c, cid = setup(tmp_path, monkeypatch, answer())
    d = c.post(f"/campaign/{cid}/replies", json={"message": "how much off?"}).json()
    bad = c.post(f"/replies/{d['id']}/approve", json={"text": "It is 50% off today!"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "facts_mismatch"
    good = c.post(f"/replies/{d['id']}/approve", json={"text": "Yes, 20% off on filter coffee, dine-in only."}).json()
    assert good["status"] == "approved" and good["final_text"].startswith("Yes, 20%")
    assert c.post(f"/replies/{d['id']}/dismiss").json()["status"] == "dismissed"
    assert c.post("/replies/nope/approve", json={}).status_code == 404


def test_string_true_from_the_model_is_accepted():
    out = reply.decide("how much off?", answer(answerable="true"), FACTS, PACKET)
    assert out["status"] == "drafted"
    assert reply.decide("how much off?", answer(answerable="no"), FACTS, PACKET)["status"] == "escalated"


def _demo_campaign(app, cid="demo-abc123"):
    app.state.db.campaign_insert({"id": cid, "brand_voice": None, "status": "facts_locked",
                                  "transcript": "sample", "suggestion": None, "created_at": now()})
    return cid


def test_demo_replies_render_in_several_states_and_are_marked_sample(tmp_path):
    app, c = make_client(tmp_path, FakeAgnes(answer()))
    cid = _demo_campaign(app)
    written = reply.seed_demo_replies(app.state.db, cid)
    assert written == len(reply.DEMO_REPLIES)
    rows = c.get(f"/campaign/{cid}/replies").json()["replies"]
    assert len(rows) == written
    assert all(r["demo"] is True for r in rows)
    # Every state the screen can draw is present: a draft to edit, an escalation to answer, an approved text to copy.
    assert {"drafted", "escalated", "approved"} <= {r["status"] for r in rows}
    assert any(r["holding"] for r in rows)  # the escalation carries a holding reply


def test_demo_seed_can_be_cleared_again(tmp_path):
    app, c = make_client(tmp_path, FakeAgnes(answer()))
    cid = _demo_campaign(app)
    count = reply.seed_demo_replies(app.state.db, cid)
    assert reply.seed_demo_replies(app.state.db, cid) == count  # running twice replaces, never piles up
    assert reply.clear_demo_replies(app.state.db, cid) == count
    assert c.get(f"/campaign/{cid}/replies").json()["replies"] == []


def test_replies_from_a_real_campaign_are_not_marked_sample(tmp_path):
    app, c = make_client(tmp_path, FakeAgnes(answer()))
    cid = _demo_campaign(app, cid="a-real-campaign")
    reply.seed_demo_replies(app.state.db, cid)
    rows = c.get(f"/campaign/{cid}/replies").json()["replies"]
    assert rows and all(r["demo"] is False for r in rows)


def test_demo_replies_are_scoped_to_each_campaign(tmp_path):
    app, c = make_client(tmp_path, FakeAgnes(answer()))
    first = _demo_campaign(app, "demo-first")
    second = _demo_campaign(app, "demo-second")
    count = reply.seed_demo_replies(app.state.db, first)
    assert reply.seed_demo_replies(app.state.db, second) == count
    before = c.get(f"/campaign/{second}/replies").json()["replies"]
    assert len(before) == count
    assert reply.seed_demo_replies(app.state.db, first) == count
    assert reply.clear_demo_replies(app.state.db, first) == count
    assert c.get(f"/campaign/{second}/replies").json()["replies"] == before
