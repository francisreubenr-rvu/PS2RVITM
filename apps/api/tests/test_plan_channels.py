"""Plan (sources, schedule rules), Campaign 0 channel structure, prompt context, config."""
import asyncio
import json
from datetime import date, timedelta

import pytest

from app import channels, plan as plan_module
from app.config import CHANNELS, Settings, load_settings
from app.queue import MAX_BURST, TokenBucket
from app.schemas import OfferFacts
from app.service import Service
from app.worker import run_copy_job
from test_interview import END, START, make, run_to

START_D = date.fromisoformat(START)


def finished(client, **kw):
    sid, _ = run_to(client, upto="never", **kw)
    return sid, client.post(f"/interview/{sid}/finish").json()["campaign_id"]


def test_plan_matches_the_contract_and_every_field_has_a_source(tmp_path):
    _app, client = make(tmp_path)
    sid, cid = finished(client)
    plan = client.get(f"/campaign/{cid}/plan").json()
    assert set(plan) >= {"campaign_id", "status", "business", "goal", "offer_facts", "facts_sources", "audiences",
                         "languages", "channels", "tone", "cta", "email_recipients", "schedule", "answers"}
    assert plan["business"] == {"name": "Brew House", "type": "cafe", "area": "Indiranagar, Bengaluru"}
    assert plan["cta"]["kind"] == "phone" and plan["cta"]["destination_url"] == "tel:+919876543210"
    assert plan["email_recipients"] == [{"name": "Asha", "email": "asha@example.com"}]
    answer_ids = {a["id"] for a in plan["answers"]}
    assert plan["goal"]["source_answer_id"] in answer_ids and plan["cta"]["source_answer_id"] in answer_ids
    assert set(plan["facts_sources"].values()) <= answer_ids
    assert set(plan["sources"].values()) <= answer_ids
    assert set(plan["facts_sources"]) >= {"item", "discount_percent", "dates", "timings", "terms", "audiences"}


def test_plan_approve_locks_the_facts(tmp_path):
    _app, client = make(tmp_path)
    _sid, cid = finished(client)
    locked = client.post(f"/campaign/{cid}/plan/approve").json()
    assert locked["status"] == "locked"
    assert client.get(f"/campaign/{cid}/plan").json()["status"] == "locked"
    assert client.get("/campaign/nope/plan").status_code == 404


def test_bogo_and_free_item_are_locked_from_the_offer_type_answer(tmp_path):
    _app, client = make(tmp_path)
    _sid, cid = finished(client, offer="buy_one_get_one")
    facts = client.get(f"/campaign/{cid}/plan").json()["offer_facts"]
    assert facts["discount_percent"] is None and facts["terms"].startswith("Buy one get one free.")


def facts(**kw):
    base = dict(item="coffee", dates=[START, END], timings="Saturday and Sunday", audiences=["regulars"],
                languages=["en"], channels=list(CHANNELS))
    base.update(kw)
    return OfferFacts(**base)


def test_schedule_rules_each_row_names_its_rule():
    rows = plan_module.build_schedule(facts())
    by = lambda purpose: [r for r in rows if r["purpose"] == purpose]
    teaser = by("teaser")
    assert {r["channel"] for r in teaser} == {"instagram_story", "whatsapp"}
    assert {r["date"] for r in teaser} == {(START_D - timedelta(days=1)).isoformat()}
    launch = by("launch")
    assert {r["channel"] for r in launch} == set(CHANNELS) and {r["date"] for r in launch} == {START}
    assert {r["channel"] for r in by("last_day")} == {"instagram_story", "whatsapp"}
    assert all(r["date"] == END for r in by("last_day"))
    for r in by("reminder"):
        assert START < r["date"] < END and r["weekday"] in ("Saturday", "Sunday") and r["channel"] in ("instagram_story", "whatsapp")
    assert all(r["rule"].startswith(r["purpose"]) for r in rows)
    # cold_email and blog_post appear once, on launch.
    assert [r["purpose"] for r in rows if r["channel"] in ("cold_email", "blog_post")] == ["launch", "launch"]


def test_schedule_single_day_window_and_unchosen_channels():
    rows = plan_module.build_schedule(facts(dates=[START], channels=["whatsapp", "poster"]))
    assert {(r["purpose"], r["channel"]) for r in rows} == {("teaser", "whatsapp"), ("launch", "whatsapp"), ("launch", "poster")}


def test_every_day_offer_reminds_on_each_day_of_the_window():
    rows = plan_module.build_schedule(facts(dates=[START, (START_D + timedelta(days=3)).isoformat()], timings="Every day", channels=["whatsapp"]))
    assert [r["purpose"] for r in rows if r["purpose"] == "reminder"] == ["reminder", "reminder"]


def test_all_new_channels_are_accepted_by_offer_facts():
    assert OfferFacts(item="x", audiences=["a"], channels=list(CHANNELS)).channels == list(CHANNELS)


# ---- channel structure

def test_parse_output_builds_the_extra_for_each_channel():
    assert channels.parse_output("cold_email", {"subject": "Hi", "content": "Hi {name}"}) == ("Hi {name}", {"subject": "Hi"})
    content, extra = channels.parse_output("instagram_post", {"content": "x", "hashtags": ["coffee", "#ok", " "]})
    assert extra == {"hashtags": ["#coffee", "#ok"]}
    assert channels.parse_output("reel", {"script": ["a", "b", "c"]}) == ("a\nb\nc", {"script": ["a", "b", "c"]})
    assert channels.parse_output("google_business_post", {"content": "x", "button": "CALL"})[1] == {"button": "call"}


@pytest.mark.parametrize("channel,content,extra,code", [
    ("cold_email", "Hello there", {"subject": "Sunday coffee"}, "name_placeholder"),
    ("cold_email", "Hi {name}", {"subject": ""}, "subject_missing"),
    ("instagram_post", "Sunday coffee", {"hashtags": []}, "hashtags_missing"),
    ("instagram_story", "Sunday coffee", {"headline": "one two three four five six seven eight nine"}, "headline_long"),
    ("blog_post", "Sunday coffee " * 3, {"title": "T"}, "blog_length"),
    ("poster", "Sunday coffee", {"headline": "H", "subline": ""}, "subline_missing"),
    ("google_business_post", "x" * 1501, {"button": "call"}, "google_long"),
    ("google_business_post", "Sunday coffee", {"button": "buy"}, "button_invalid"),
    ("reel", "a\nb", {"script": ["a", "b"]}, "script_lines"),
])
def test_structure_rules_block_a_bad_shape(channel, content, extra, code):
    assert code in [i.code for i in channels.structure_issues(channel, content, extra, strict=True)]


def test_validator_covers_subject_title_headline_and_hashtags():
    f = OfferFacts(item="coffee", discount_percent=20, timings="Sunday only", audiences=["a"])
    bad = {
        "cold_email": ("Hi {name}, coffee 20% off Sunday only.", {"subject": "30% off coffee"}),
        "instagram_post": ("Coffee 20% off Sunday only.", {"hashtags": ["#SaturdayTreat", "#40percent"]}),
        "instagram_story": ("Coffee 20% off Sunday only.", {"headline": "Coffee 50% off"}),
        "poster": ("Coffee 20% off Sunday only.", {"headline": "Free coffee every day", "subline": "x"}),
    }
    for channel, (content, extra) in bad.items():
        result = channels.validate_asset(channel, content, extra, f, strict=True)
        assert not result.ok, channel
        assert any(code in result.codes for code in ("percent_mismatch", "weekday_widen", "free_mismatch")), (channel, result.codes)


def test_visible_text_includes_extra_fields():
    assert channels.visible_text("cold_email", "Body", {"subject": "Subj"}) == "Subj\nBody"
    assert channels.visible_text("instagram_post", "Cap", {"hashtags": ["#a", "#b"]}) == "#a #b\nCap"


# ---- generation matrix and prompt

class JsonAgnes:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        self.calls.append((cache_kind, messages))
        return json.dumps(self.replies.pop(0))


def run_jobs(app, cid):
    jobs = Service(app.state.db).prepare_generation(cid, has_key=True)

    async def go():
        for job in jobs:
            await run_copy_job(app, job["id"])
        loop = asyncio.get_running_loop()
        while pending := [t for t in app.state.tasks if t.get_loop() is loop and not t.done()]:
            await asyncio.gather(*pending)

    asyncio.run(go())


def test_matrix_is_channels_by_languages_and_the_prompt_carries_only_plan_context(tmp_path):
    email = {"subject": "Weekend coffee", "content": "Hi {name}, filter coffee is 20% off on Saturday and Sunday.", "facts_used": ["item"]}
    agnes = JsonAgnes([email, {"content": "Filter coffee 20% off Saturday and Sunday."}] * 2)
    app, client = make(tmp_path, agnes)
    sid, _ = run_to(client, upto="never")
    # Only English, two channels, so the scripted replies line up by channel order.
    cid = client.post(f"/interview/{sid}/finish").json()["campaign_id"]
    client.put(f"/campaigns/{cid}/facts", json={**client.get(f"/campaign/{cid}/plan").json()["offer_facts"],
                                               "languages": ["en"], "channels": ["cold_email", "whatsapp"]})
    client.post(f"/campaign/{cid}/plan/approve")
    jobs = Service(app.state.db).prepare_generation(cid, has_key=True)
    assets = app.state.db.assets_for(cid)
    assert len(assets) == 2 and {a["audience"] for a in assets} == {"all"}
    asyncio.run(asyncio.sleep(0))
    for asset in assets:
        agnes.replies = [email if asset["channel"] == "cold_email" else {"content": "Filter coffee 20% off Saturday and Sunday."}]
        job = next(j for j in jobs if j["asset_id"] == asset["id"])
        asyncio.run(run_copy_job(app, job["id"]))
    stored = {a["channel"]: a for a in app.state.db.assets_for(cid)}
    assert json.loads(stored["cold_email"]["extra"]) == {"subject": "Weekend coffee"}
    assert stored["cold_email"]["status"] == "pending"
    board = client.get(f"/campaign/{cid}/board").json()["assets"]
    assert {a["channel"]: a["extra"] for a in board}["cold_email"] == {"subject": "Weekend coffee"}
    request = json.loads(agnes.calls[0][1][1]["content"])
    assert request["business_name"] == "Brew House" and request["area"] == "Indiranagar, Bengaluru"
    assert request["tone"] == "warm_local" and request["audiences"] == ["students", "regulars"]
    assert request["cta"] == {"kind": "phone", "value": "9876543210"}
    assert set(request) <= {"language", "language_code", "channel", "audiences", "offer_facts", "business_name", "area",
                            "tone", "cta", "weekday_words_to_use", "rejected_attempt", "problems_to_fix", "owner_instruction"}
    assert "business_type" not in json.dumps(request)


def test_a_structure_failure_is_blocked_and_repaired_once(tmp_path):
    bad = {"subject": "Coffee", "content": "Hello, filter coffee is 20% off on Saturday and Sunday."}
    good = {"subject": "Coffee", "content": "Hi {name}, filter coffee is 20% off on Saturday and Sunday."}
    agnes = JsonAgnes([bad, good])
    app, client = make(tmp_path, agnes)
    sid, _ = run_to(client, upto="never")
    cid = client.post(f"/interview/{sid}/finish").json()["campaign_id"]
    client.put(f"/campaigns/{cid}/facts", json={**client.get(f"/campaign/{cid}/plan").json()["offer_facts"],
                                               "languages": ["en"], "channels": ["cold_email"]})
    client.post(f"/campaign/{cid}/plan/approve")
    run_jobs(app, cid)
    asset = app.state.db.assets_for(cid)[0]
    assert asset["status"] == "pending" and "{name}" in asset["content"]
    repair = json.loads(agnes.calls[1][1][1]["content"])
    assert any("{name}" in p for p in repair["problems_to_fix"])


# ---- config and queue

def test_rpm_and_models_are_env_configurable(monkeypatch):
    monkeypatch.setenv("TEXT_RPM", "1000")
    monkeypatch.setenv("IMAGE_RPM", "100")
    monkeypatch.setenv("VIDEO_RPM", "5")
    monkeypatch.setenv("TOKEN_PLAN_KEY", "paid")
    monkeypatch.setenv("AGNES_API_KEY", "free")
    s = load_settings()
    assert (s.text_rpm, s.image_rpm, s.video_rpm) == (1000, 100, 5)
    assert s.agnes_api_key == "paid" and s.agnes_key_pool == "token_plan"
    monkeypatch.setenv("TOKEN_PLAN_KEY", "")
    s = load_settings()
    assert s.agnes_api_key == "free" and s.agnes_key_pool == "free"


def test_bucket_burst_is_capped():
    assert TokenBucket(1000).capacity == MAX_BURST
    assert TokenBucket(10).capacity == 10 and TokenBucket(1).capacity == 1
