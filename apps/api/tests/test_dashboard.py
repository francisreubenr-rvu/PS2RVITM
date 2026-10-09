"""Dashboard numbers come only from this app's own rows. Zero stays zero."""
import json

import pytest

from app import plan
from app.service import now
from b_helpers import PLAN, make_client, seed, write_copy


@pytest.fixture
def rig(tmp_path, monkeypatch):
    app, client = make_client(tmp_path)
    monkeypatch.setattr(plan, "get_plan", lambda db, cid: PLAN)
    campaign_id, assets = seed(client, app)
    return app, client, campaign_id, assets


def test_empty_campaign_is_all_zero(rig):
    app, client, campaign_id, assets = rig
    body = client.get(f"/campaign/{campaign_id}/dashboard").json()
    assert body["totals"] == {"assets": 4, "approved": 0, "blocked": 0, "distributed": 0, "clicks": 0, "email_sent": 0, "email_opens": 0}
    assert [(s["stage"], s["count"]) for s in body["funnel"]] == [
        ("planned", 4), ("written", 0), ("passed checks", 0), ("approved", 0), ("distributed", 0), ("clicked", 0)
    ]
    assert body["clicks_series"] == [] and body["predictions"] is None
    assert body["quality"] == {"fact_blocks": 0, "meaning_flags": 0, "repairs": 0, "repairs_succeeded": 0, "repairs_exhausted": 0}
    assert all(row["clicks"] == 0 and row["distributed"] == 0 for row in body["by_channel"])
    assert client.get("/campaign/nope/dashboard").status_code == 404


def test_counts_follow_real_events(rig):
    app, client, campaign_id, assets = rig
    db = app.state.db
    post, wa, mail, poster = (assets[c] for c in ("instagram_post", "whatsapp", "cold_email", "poster"))
    write_copy(app, post, status="approved")
    write_copy(app, wa, status="pending")
    write_copy(app, mail, "Hi {name}", status="blocked")
    db.asset_update(wa["id"], review=json.dumps({"status": "flagged"}))

    link = client.post(f"/assets/{post['id']}/link").json()
    client.post(f"/assets/{post['id']}/outreach", json={"action": "copied"})
    client.post(f"/assets/{post['id']}/outreach", json={"action": "downloaded"})
    for _ in range(3):
        client.get(f"/r/{link['code']}", follow_redirects=False)
    db.execute("UPDATE click SET ts = '2026-10-09T10:05:00+00:00' WHERE id = 1")
    db.execute("UPDATE click SET ts = '2026-10-09T10:55:00+00:00' WHERE id = 2")
    db.execute("UPDATE click SET ts = '2026-10-09T11:00:00+00:00' WHERE id = 3")
    db.execute(
        "INSERT INTO email_send (ts, token, asset_id, campaign_id, recipient_name, recipient_email) VALUES (?, 'tok', ?, ?, NULL, 'a@example.com')",
        (now(), mail["id"], campaign_id),
    )
    db.execute("INSERT INTO email_open (ts, token, asset_id, campaign_id, ua) VALUES (?, 'tok', ?, ?, NULL)", (now(), mail["id"], campaign_id))
    db.execute("INSERT INTO email_open (ts, token, asset_id, campaign_id, ua) VALUES (?, 'tok', ?, ?, NULL)", (now(), mail["id"], campaign_id))

    body = client.get(f"/campaign/{campaign_id}/dashboard").json()
    assert body["totals"] == {"assets": 4, "approved": 1, "blocked": 1, "distributed": 2, "clicks": 3, "email_sent": 1, "email_opens": 1}
    assert {s["stage"]: s["count"] for s in body["funnel"]} == {
        "planned": 4, "written": 3, "passed checks": 1, "approved": 1, "distributed": 2, "clicked": 1
    }
    channels = {row["channel"]: row for row in body["by_channel"]}
    assert channels["instagram_post"] == {"channel": "instagram_post", "assets": 1, "approved": 1, "distributed": 1, "clicks": 3, "opens": 0}
    assert channels["cold_email"]["opens"] == 1 and channels["cold_email"]["distributed"] == 1
    assert body["by_language"] == [{"lang": "en", "assets": 4, "approved": 1, "clicks": 3}]
    assert body["clicks_series"] == [
        {"bucket_start": "2026-10-09T10:00:00+00:00", "channel": "instagram_post", "count": 2},
        {"bucket_start": "2026-10-09T11:00:00+00:00", "channel": "instagram_post", "count": 1},
    ]
    kinds = {item["kind"] for item in body["activity"]}
    assert {"copied", "downloaded", "click", "email_sent", "email_open"} <= kinds
    stamps = [item["ts"] for item in body["activity"]]
    assert stamps == sorted(stamps, reverse=True)


def test_quality_counts_from_event_log_and_repair_jobs(rig):
    app, client, campaign_id, assets = rig
    db = app.state.db
    for action in ("asset_blocked", "asset_blocked", "meaning_flagged", "repair_exhausted"):
        db.log(now(), "system", action, "x", campaign_id)
    db.log(now(), "system", "asset_blocked", "other campaign", "other")
    aid = assets["whatsapp"]["id"]
    for status, attempt in (("completed", 1), ("blocked", 1), ("completed", 0)):
        db.job_insert(
            {
                "id": f"j{status}{attempt}", "campaign_id": campaign_id, "asset_id": aid, "kind": "copy", "status": status,
                "detail": None, "provider_ref": None, "payload": json.dumps({"attempt": attempt}), "created_at": now(), "updated_at": now(),
            }
        )
    assert client.get(f"/campaign/{campaign_id}/dashboard").json()["quality"] == {
        "fact_blocks": 2, "meaning_flags": 1, "repairs": 2, "repairs_succeeded": 1, "repairs_exhausted": 1
    }


def test_geography_splits_area_from_the_plan(rig):
    app, client, campaign_id, assets = rig
    assert client.get(f"/campaign/{campaign_id}/dashboard").json()["geography"] == {
        "area": "Indiranagar, Bengaluru", "locality": "Indiranagar", "city": "Bengaluru", "measured": False,
    }


def test_geography_handles_missing_and_single_word_area(rig, monkeypatch):
    app, client, campaign_id, assets = rig
    for plan_data, expected in (
        ({"business": {"area": "Jayanagar"}}, {"area": "Jayanagar", "locality": "Jayanagar", "city": None, "measured": False}),
        ({"business": {"area": "  "}}, {"area": None, "locality": None, "city": None, "measured": False}),
        ({"business": {}}, {"area": None, "locality": None, "city": None, "measured": False}),
        (None, {"area": None, "locality": None, "city": None, "measured": False}),
    ):
        monkeypatch.setattr(plan, "get_plan", lambda db, cid, data=plan_data: data)
        assert client.get(f"/campaign/{campaign_id}/dashboard").json()["geography"] == expected


def test_overview_and_assets_state(rig):
    app, client, campaign_id, assets = rig
    overview = client.get("/campaigns/overview").json()
    assert overview == [
        {"campaign_id": campaign_id, "business": PLAN["business"], "status": "facts_locked", "totals": overview[0]["totals"]}
    ]
    assert overview[0]["totals"]["assets"] == 4
    state = client.get(f"/campaign/{campaign_id}/assets/state").json()
    assert set(state) == {a["id"] for a in assets.values()}
    empty = state[assets["poster"]["id"]]
    assert empty["media"] == [] and empty["link"] is None and empty["prediction"] is None
    assert empty["outreach"] == {
        "copied": 0, "shared_whatsapp": 0, "downloaded": 0, "posted_manually": 0, "email_opened_in_app": 0,
        "email_sent": 0, "clicks": 0, "opens": 0,
    }
    assert client.get("/campaign/nope/assets/state").status_code == 404
