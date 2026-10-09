"""Change by voice: classify, ground, dry-run, then apply on confirm."""
import json

from app.changes import DEMO_EVENTS, clear_demo_events, seed_demo_events
from app.service import Service, now
from test_interview import ExtractAgnes, make, run_to


def locked_campaign(client, app, channels=("whatsapp", "instagram_story"), langs=("en", "hi"), offer="fixed_price"):
    sid, _ = run_to(client, upto="never", offer=offer)
    cid = client.post(f"/interview/{sid}/finish").json()["campaign_id"]
    facts = client.get(f"/campaign/{cid}/plan").json()["offer_facts"]
    client.put(f"/campaigns/{cid}/facts", json={**facts, "languages": list(langs), "channels": list(channels), "terms": None})
    client.post(f"/campaign/{cid}/plan/approve")
    Service(app.state.db).prepare_generation(cid, has_key=False)
    for a in app.state.db.assets_for(cid):
        body = "Filter coffee ₹80 on Saturday and Sunday." if a["lang"] == "en" else "फ़िल्टर कॉफ़ी ₹80, शनिवार और रविवार।"
        if offer == "percent_off":
            body = body.replace("₹80", "20%")
        client.patch(f"/assets/{a['id']}", json={"content": body})
    for job in app.state.db.jobs_for_campaign(cid):
        app.state.db.job_update(job["id"], "2026-01-01T00:00:00+00:00", status="completed", detail="closed")
    return cid


def propose(client, cid, text):
    return client.post(f"/campaign/{cid}/change/propose", json={"text": text})


def test_trap_change_price_to_one_ninety_nine_is_a_grounded_fact_patch_and_nothing_applies_yet(tmp_path):
    app, client = make(tmp_path)
    cid = locked_campaign(client, app)
    before = len(app.state.db.query("SELECT * FROM offer_facts WHERE campaign_id = ?", (cid,)))
    body = propose(client, cid, "change price to one ninety nine").json()
    assert body["kind"] == "fact" and body["patch"] == {"price_amount": 199.0} and body["grounded"] is True
    assert len(body["affected_asset_ids"]) == len(app.state.db.assets_for(cid))
    assert len(app.state.db.query("SELECT * FROM offer_facts WHERE campaign_id = ?", (cid,))) == before
    board = client.post(f"/campaign/{cid}/change/{body['proposal_id']}/apply").json()
    assert board["facts"]["facts"]["price_amount"] == 199.0
    assert {a["status"] for a in board["assets"]} == {"changed"}
    assert client.post(f"/campaign/{cid}/change/{body['proposal_id']}/apply").status_code == 409


def test_trap_tone_only_edit_does_not_touch_the_ledger(tmp_path):
    app, client = make(tmp_path)
    cid = locked_campaign(client, app)
    body = propose(client, cid, "make the hindi one funnier and add a small chai emoji, don't touch the price").json()
    assert body["kind"] == "tone" and body["patch"] is None and "funnier" in body["instruction"]
    hindi = {a["id"] for a in app.state.db.assets_for(cid) if a["lang"] == "hi"}
    assert set(body["affected_asset_ids"]) == hindi
    before = app.state.db.facts_approved(cid)["version"]
    client.post(f"/campaign/{cid}/change/{body['proposal_id']}/apply")
    assert app.state.db.facts_approved(cid)["version"] == before
    queued = [j for j in app.state.db.jobs_for_campaign(cid) if j["status"] == "waiting_for_key"]
    assert {j["asset_id"] for j in queued} == hindi
    assert json.loads(queued[0]["payload"])["feedback"]["instruction"].startswith("make the hindi one funnier")


def test_percent_and_day_changes_without_a_key(tmp_path):
    app, client = make(tmp_path)
    cid = locked_campaign(client, app, offer="percent_off")
    assert propose(client, cid, "make the discount 10 percent").json()["patch"] == {"discount_percent": 10.0}
    day = propose(client, cid, "make it sunday only").json()
    assert day["kind"] == "fact" and day["patch"] == {"timings": "Sunday"}


def test_unreadable_request_is_refused(tmp_path):
    app, client = make(tmp_path)
    cid = locked_campaign(client, app)
    refused = propose(client, cid, "hmm do the thing")
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "not_understood"
    assert propose(client, cid, "make it 50").status_code == 422


def test_scope_adds_a_channel_and_removes_a_language(tmp_path):
    app, client = make(tmp_path)
    cid = locked_campaign(client, app)
    add = propose(client, cid, "also add a poster").json()
    assert add["kind"] == "scope" and add["scope"]["add_channels"] == ["poster"]
    client.post(f"/campaign/{cid}/change/{add['proposal_id']}/apply")
    assert {a["channel"] for a in app.state.db.assets_for(cid)} == {"whatsapp", "instagram_story", "poster"}
    drop = propose(client, cid, "drop hindi").json()
    assert drop["scope"]["remove_languages"] == ["hi"] and drop["affected_asset_ids"]
    client.post(f"/campaign/{cid}/change/{drop['proposal_id']}/apply")
    assert {a["lang"] for a in app.state.db.assets_for(cid)} == {"en"}
    assert client.get(f"/campaign/{cid}/plan").json()["languages"] == ["en"]


def test_with_a_key_the_model_classifies_and_its_numbers_are_grounded(tmp_path):
    agnes = ExtractAgnes()
    app, client = make(tmp_path, agnes)
    cid = locked_campaign(client, app)
    agnes.replies = [{"kind": "fact", "price_amount": 199}, {"kind": "fact", "price_amount": 99}]
    good = propose(client, cid, "change price to one ninety nine").json()
    assert good["patch"] == {"price_amount": 199.0} and good["grounded"] is True
    assert [k for k, _ in agnes.calls if k == "change"] == ["change"]
    bad = propose(client, cid, "make it cheaper for students")
    # 99 is not in the owner's words, so the model value is dropped and nothing readable remains.
    assert bad.status_code == 422


def test_demo_change_log_is_seeded_newest_first_and_clears(tmp_path):
    app, client = make(tmp_path)
    cid = "demo-log1"
    app.state.db.campaign_insert({"id": cid, "brand_voice": None, "status": "facts_locked",
                                  "transcript": "sample", "suggestion": None, "created_at": now()})
    written = seed_demo_events(app.state.db, cid)
    assert written == len(DEMO_EVENTS)
    assert seed_demo_events(app.state.db, cid) == written  # replaces, never piles up
    events = client.get(f"/campaign/{cid}/board").json()["events"]
    assert len(events) == written
    assert events[0]["campaign_id"] == cid  # the screen reads this to label the row Sample
    assert events[0]["action"] == DEMO_EVENTS[-1]["action"]  # newest first
    assert clear_demo_events(app.state.db, cid) == written
    assert client.get(f"/campaign/{cid}/board").json()["events"] == []


def test_demo_events_never_clear_a_real_campaign(tmp_path):
    app, client = make(tmp_path)
    cid = "a-real-campaign"
    app.state.db.campaign_insert({"id": cid, "brand_voice": None, "status": "draft",
                                  "transcript": "real", "suggestion": None, "created_at": now()})
    app.state.db.log(now(), "owner", "campaign_created", "Transcript stored.", cid)
    assert clear_demo_events(app.state.db, cid) == 0
    assert client.get(f"/campaign/{cid}/board").json()["events"]
