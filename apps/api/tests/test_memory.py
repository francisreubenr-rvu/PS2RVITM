"""Memory: owner-written items, suggestions that wait for acceptance, dismissals that stick, and a copy prompt that never sees prices."""
import json

import pytest

from app import memory, prompts
from b_helpers import make_client, seed
from app.schemas import OfferFacts


@pytest.fixture
def rig(tmp_path):
    app, client = make_client(tmp_path)
    seed(client, app)  # approved facts: filter coffee, 20% off, Sunday only
    client.put("/business", json={"name": "Brew Bandi", "phone": "98450 12345", "hours": "8am to 9pm", "menu": [{"name": "Filter coffee", "price": 60}]})
    return app, client


def test_owner_can_add_edit_pin_and_delete(rig):
    _, c = rig
    made = c.post("/memory", json={"kind": "menu", "title": "Dosa menu", "body": "Plain dosa 70", "pinned": True}).json()
    assert made["source"] == "you" and made["status"] == "active" and made["pinned"]
    edited = c.put(f"/memory/{made['id']}", json={"kind": "menu", "title": "Dosa menu", "body": "Plain dosa 75"}).json()
    assert edited["body"] == "Plain dosa 75" and not edited["pinned"]
    assert [i["title"] for i in c.get("/memory").json()["items"]] == ["Dosa menu"]
    assert c.get("/memory", params={"q": "75"}).json()["items"] and not c.get("/memory", params={"q": "zzz"}).json()["items"]
    c.delete(f"/memory/{made['id']}")
    assert c.get("/memory").json()["items"] == []
    assert c.post("/memory", json={"kind": "bogus", "title": "x"}).json()["detail"]["code"] == "bad_kind"


def test_refresh_proposes_suggestions_with_evidence_and_uses_none_until_accepted(rig):
    _, c = rig
    out = c.post("/memory/refresh").json()
    assert out["added"] >= 3
    got = c.get("/memory").json()
    assert got["items"] == [] and got["suggested"]
    titles = {s["title"] for s in got["suggested"]}
    assert {"Menu and prices", "Opening hours"} <= titles and any(t.startswith("Offer: filter coffee") for t in titles)
    menu = [s for s in got["suggested"] if s["title"] == "Menu and prices"][0]
    assert menu["source"] == "growit" and "Filter coffee: ₹60" in menu["body"] and menu["evidence"]
    assert c.post("/memory/refresh").json()["added"] == 0  # same facts, nothing new


def test_accept_keeps_it_and_the_next_refresh_does_not_overwrite_it(rig):
    _, c = rig
    c.post("/memory/refresh")
    sug = [s for s in c.get("/memory").json()["suggested"] if s["title"] == "Opening hours"][0]
    assert c.post(f"/memory/{sug['id']}/accept").json()["status"] == "active"
    c.put("/business", json={"hours": "9am to 5pm"})
    out = c.post("/memory/refresh").json()
    kept = [i for i in c.get("/memory").json()["items"] if i["title"] == "Opening hours"][0]
    assert kept["body"] == "8am to 9pm" and out["updated"] == 0


def test_a_waiting_suggestion_follows_new_data(rig):
    _, c = rig
    c.post("/memory/refresh")
    c.put("/business", json={"hours": "10am to 6pm"})
    assert c.post("/memory/refresh").json()["updated"] == 1
    assert [s for s in c.get("/memory").json()["suggested"] if s["title"] == "Opening hours"][0]["body"] == "10am to 6pm"


def test_dismissed_or_deleted_suggestions_do_not_return(rig):
    _, c = rig
    c.post("/memory/refresh")
    for s in c.get("/memory").json()["suggested"]:
        c.post(f"/memory/{s['id']}/dismiss")
    assert c.get("/memory").json()["suggested"] == [] and c.post("/memory/refresh").json()["added"] == 0
    assert c.post("/memory/nope/accept").status_code == 404


def test_editing_a_suggestion_makes_it_the_owners(rig):
    _, c = rig
    c.post("/memory/refresh")
    s = c.get("/memory").json()["suggested"][0]
    r = c.put(f"/memory/{s['id']}", json={"kind": s["kind"], "title": s["title"], "body": "My own words"}).json()
    assert r["source"] == "you" and r["status"] == "active"


def test_only_voice_and_rules_reach_the_copy_prompt_and_never_a_price(rig):
    app, c = rig
    c.post("/memory", json={"kind": "voice", "title": "Warm and short", "body": "Talk like a neighbour."})
    c.post("/memory", json={"kind": "rules", "title": "No discounts talk", "body": "Never say cheap."})
    c.post("/memory", json={"kind": "menu", "title": "Menu", "body": "Coffee 999 rupees"})
    c.post("/memory", json={"kind": "voice", "title": "Private", "body": "Do not use me", "use_ai": False})
    notes = memory.prompt_notes(app.state.db)
    assert len(notes) == 2 and all("999" not in n for n in notes) and any(n.startswith("Avoid:") for n in notes) and not any("Private" in n for n in notes)
    facts = OfferFacts(item="filter coffee", audiences=["regulars"])
    msgs = prompts.copy_messages(facts, {"lang": "en", "channel": "whatsapp"}, None, {"owner_notes": notes})
    user = json.loads(msgs[1]["content"])
    assert user["owner_notes"] == notes and "never a source for a price" in msgs[0]["content"]


def test_export_and_forget(rig):
    _, c = rig
    c.post("/memory", json={"kind": "other", "title": "A", "body": "b"})
    assert [i["title"] for i in c.get("/memory/export").json()["items"]] == ["A"]
    assert c.delete("/memory").json()["detail"]["code"] == "confirm_required"
    c.delete("/memory", params={"confirm": "true"})
    assert c.get("/memory").json() == {**c.get("/memory").json(), "items": [], "suggested": []}


def test_memory_belongs_to_its_owner(rig):
    app, c = rig
    made = c.post("/memory", json={"kind": "other", "title": "Mine"}).json()
    app.state.db.execute("UPDATE memory_item SET owner = 'other@x.com'")
    assert c.get("/memory").json()["items"] == [] and c.put(f"/memory/{made['id']}", json={"kind": "other", "title": "x"}).status_code == 404


def test_results_you_entered_become_a_suggestion_with_evidence(rig):
    app, c = rig
    campaign = app.state.db.campaign_list()[0]["id"]
    assets = app.state.db.assets_for(campaign)
    wa = [a for a in assets if a["channel"] == "whatsapp"][0]
    r = c.post(f"/campaign/{campaign}/results", json={"results": [{"asset_id": wa["id"], "reach": 200, "redemptions": 30}]})
    assert r.status_code == 200, r.text
    c.post("/memory/refresh")
    got = [s for s in c.get("/memory").json()["suggested"] if s["kind"] == "results"]
    assert got and got[0]["title"].startswith("What worked: filter coffee") and "Best channel: whatsapp" in got[0]["body"]
    assert "200" in got[0]["evidence"] and got[0]["status"] == "suggested"


def fact(**kw):
    return {"subject": "", "relation": "founded", "object": "Brew Bandi", "kind": "org", "detail": "in 2019", "quote": "I started it in a garage", **kw}


def test_a_briefing_is_kept_only_when_the_owner_saves_it_and_one_note_per_kind(rig):
    _, c = rig
    r = c.post("/memory/briefing", json={"facts": [fact(), fact(relation="worked at", object="Infosys", detail="", quote=""), fact(kind="skill", relation="is good at", object="roasting", detail="", quote="")]})
    assert r.json() == {"saved": 3, "notes": 2}
    items = {i["title"]: i for i in c.get("/memory").json()["items"]}
    org = items["From my briefing: Organisations"]
    assert org["source"] == "you" and org["status"] == "active" and org["kind"] == "about" and "briefing" in org["evidence"]
    assert "founded Brew Bandi (in 2019)" in org["body"] and "\u201cI started it in a garage\u201d" in org["body"] and "worked at Infosys" in org["body"]
    assert "is good at roasting" in items["From my briefing: Skills"]["body"]


def test_a_second_briefing_adds_lines_and_never_removes_or_duplicates(rig):
    _, c = rig
    c.post("/memory/briefing", json={"facts": [fact()]})
    note = c.get("/memory").json()["items"][0]
    c.put(f"/memory/{note['id']}", json={"kind": "about", "title": note["title"], "body": note["body"] + "\nmy own line"})  # the owner edits it
    c.post("/memory/briefing", json={"facts": [fact(), fact(relation="led", object="a team of ten", kind="org", detail="", quote="")]})
    body = c.get("/memory").json()["items"][0]["body"].split("\n")
    assert body.count([b for b in body if b.startswith("founded")][0]) == 1 and "my own line" in body and any("led a team of ten" in b for b in body)


def test_a_removed_briefing_note_comes_back_clean_when_a_new_briefing_is_saved(rig):
    _, c = rig
    c.post("/memory/briefing", json={"facts": [fact()]})
    c.delete(f"/memory/{c.get('/memory').json()['items'][0]['id']}")
    assert c.get("/memory").json()["items"] == []
    c.post("/memory/briefing", json={"facts": [fact(object="Other Cafe")]})
    body = c.get("/memory").json()["items"][0]["body"]
    assert body.startswith("founded Other Cafe") and "\n\n" not in body


def test_briefing_input_is_checked(rig):
    _, c = rig
    assert c.post("/memory/briefing", json={"facts": []}).status_code == 422
    assert c.post("/memory/briefing", json={"facts": [fact(kind="secret")]}).json()["detail"]["code"] == "bad_kind"
    assert c.post("/memory/briefing", json={"facts": [fact(object="x" * 201)]}).status_code == 422


def test_import_splits_bullets_lines_and_json_without_saving(rig):
    _, c = rig
    text = "# What I know about you\n- Prefers warm, plain English\n- **Opens**: 8am to 9pm\n2. Prefers warm, plain English\n\n---\nNever mention competitors"
    got = c.post("/memory/import/preview", json={"text": text}).json()
    assert got["method"] == "split"
    assert [(e["title"], e["body"]) for e in got["entries"]] == [("Prefers warm, plain English", ""), ("Opens", "8am to 9pm"), ("Never mention competitors", "")]
    js = c.post("/memory/import/preview", json={"text": '{"memories": [{"title": "Tone", "content": "Friendly"}, "Closed on Mondays"]}'}).json()
    assert [(e["title"], e["body"]) for e in js["entries"]] == [("Tone", "Friendly"), ("Closed on Mondays", "")]
    assert c.get("/memory").json()["items"] == []  # a preview keeps nothing
    assert c.post("/memory/import/preview", json={"text": "# only a heading"}).json()["detail"]["code"] == "nothing_found"


def test_import_save_keeps_only_what_the_owner_sends_and_skips_repeats(rig):
    _, c = rig
    entries = [{"kind": "voice", "title": "Tone", "body": "Warm"}, {"kind": "other", "title": "Parking", "body": "Behind the shop"}]
    assert c.post("/memory/import", json={"entries": entries}).json() == {"saved": 2, "skipped": 0}
    assert c.post("/memory/import", json={"entries": entries}).json() == {"saved": 0, "skipped": 2}
    items = c.get("/memory").json()["items"]
    assert {i["title"] for i in items} == {"Tone", "Parking"} and all(i["source"] == "you" and i["status"] == "active" for i in items)
    assert c.post("/memory/import", json={"entries": [{"kind": "bogus", "title": "x"}]}).json()["detail"]["code"] == "bad_kind"
    assert c.post("/memory/import", json={"entries": []}).status_code == 422


def test_tidy_uses_the_one_groq_model_and_respects_the_switch(rig, monkeypatch):
    import httpx
    from app import brain
    _, c = rig
    seen = {}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            seen["model"] = kw["json"]["model"]
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"entries": [{"title": "Opens early", "body": "From 8am."}]})}}]})

    monkeypatch.setattr(brain.httpx, "AsyncClient", Fake)
    assert c.post("/memory/import/preview", json={"text": "x", "tidy": True}).json()["detail"]["code"] == "brain_not_configured"  # no key
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    got = c.post("/memory/import/preview", json={"text": "I open at 8am, as I said.", "tidy": True}).json()
    assert got["method"] == "model" and got["entries"][0]["title"] == "Opens early" and seen["model"] == brain.TEXT_MODEL == "z-ai/glm-5.3-flash"
    c.put("/settings/toggles/openrouter", json={"enabled": False})
    assert c.post("/memory/import/preview", json={"text": "x", "tidy": True}).status_code == 503
