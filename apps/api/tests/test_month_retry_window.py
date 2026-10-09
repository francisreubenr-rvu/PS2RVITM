"""Month-name rule, truncated-JSON retry with per-channel token limits, and the plan's offer_window."""
import asyncio
import json

import pytest

from app import plan as plan_module
from app.schemas import OfferFacts
from app.service import Service
from app.validator import months_in, validate_content
from app.worker import COPY_MAX_TOKENS, COPY_MAX_TOKENS_DEFAULT, run_copy_job
from test_interview import END, START, make, run_to

OCT = OfferFacts(item="filter coffee", discount_percent=20, timings="Sunday only", audiences=["regulars"],
                 dates=["2026-10-18", "2026-10-20"])
NO_DATES = OfferFacts(item="filter coffee", discount_percent=20, timings="Sunday only", audiences=["regulars"])


def test_the_kannada_august_case_for_an_october_offer_is_blocked():
    copy = "ಆಗಸ್ಟ್ 18 ರಿಂದ 20 ರವರೆಗೆ ಭಾನುವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ 20% ರಿಯಾಯಿತಿ."
    assert "month_mismatch" in validate_content(copy, OCT).codes


@pytest.mark.parametrize("text,month", [
    ("Offer ends 12 October", 10), ("Offer from Oct 12", 10), ("12th Oct only", 10), ("August sale", 8),
    ("ಅಗಸ್ಟ್‌ನಲ್ಲಿ", 8), ("ಅಕ್ಟೋಬರ್ 18", 10), ("ಡಿಸೆಂಬರ್", 12), ("ಮೇ 5", 5),
    ("अगस्त में", 8), ("अक्तूबर", 10), ("दिसम्बर", 12), ("मई में", 5), ("5 May", 5), ("May 5", 5),
])
def test_months_are_read_in_english_kannada_and_hindi(text, month):
    assert months_in(text) == {month}


@pytest.mark.parametrize("text", [
    "We may open early. May the best coffee win.", "Come in, it may rain", "ಮೇಲೆ ಬನ್ನಿ", "Mar and Jan are names",
    "march forward", "Sunday only", "may", "मैं आऊँगा",
])
def test_ordinary_words_are_not_months(text):
    assert months_in(text) == set()


def test_locked_month_is_fine_and_no_dates_means_any_month_is_unexpected():
    ok = "Filter coffee 20% off, Sunday only, 18 October to 20 October."
    assert validate_content(ok, OCT).ok
    assert "month_mismatch" in validate_content("Filter coffee 20% off, Sunday only, 18 November.", OCT).codes
    assert "month_unexpected" in validate_content("Filter coffee 20% off, Sunday only, in December.", NO_DATES).codes
    assert validate_content("Filter coffee 20% off, Sunday only. We may add more.", NO_DATES).ok


def test_a_window_spanning_two_months_allows_both():
    span = OfferFacts(item="coffee", discount_percent=20, timings="Sunday only", audiences=["a"], dates=["2026-10-30", "2026-11-02"])
    assert validate_content("Coffee 20% off Sunday only, 30 October to 2 November.", span).ok


# ---- truncated JSON retry

class RawAgnes:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        self.calls.append({"kind": cache_kind, "messages": messages, "max_tokens": max_tokens})
        return self.replies.pop(0)


def campaign_with(client, app, channel):
    sid, _ = run_to(client, upto="never")
    cid = client.post(f"/interview/{sid}/finish").json()["campaign_id"]
    facts = client.get(f"/campaign/{cid}/plan").json()["offer_facts"]
    client.put(f"/campaigns/{cid}/facts", json={**facts, "languages": ["en"], "channels": [channel]})
    client.post(f"/campaign/{cid}/plan/approve")
    return cid, Service(app.state.db).prepare_generation(cid, has_key=True)


GOOD = json.dumps({"content": "Filter coffee 20% off on Saturday and Sunday."})
TRUNCATED = '{"content": "Filter coffee 20% off on Satur'


def test_a_truncated_reply_is_retried_once_with_the_error_and_then_succeeds(tmp_path):
    agnes = RawAgnes([TRUNCATED, GOOD])
    app, client = make(tmp_path, agnes)
    cid, jobs = campaign_with(client, app, "whatsapp")
    asyncio.run(run_copy_job(app, jobs[0]["id"]))
    assert len(agnes.calls) == 2
    retry = agnes.calls[1]["messages"]
    assert retry[:-1] == agnes.calls[0]["messages"] and "not valid JSON" in retry[-1]["content"]
    assert agnes.calls[1]["max_tokens"] > agnes.calls[0]["max_tokens"]
    asset = app.state.db.assets_for(cid)[0]
    assert asset["status"] == "pending" and asset["content"].startswith("Filter coffee")
    assert app.state.db.jobs_for_campaign(cid)[0]["status"] == "completed"


def test_two_truncated_replies_fail_the_job_cleanly(tmp_path):
    agnes = RawAgnes([TRUNCATED, TRUNCATED])
    app, client = make(tmp_path, agnes)
    cid, jobs = campaign_with(client, app, "whatsapp")
    asyncio.run(run_copy_job(app, jobs[0]["id"]))
    assert len(agnes.calls) == 2
    job = next(j for j in app.state.db.jobs_for_campaign(cid) if j["kind"] == "copy")
    assert job["status"] == "failed"


def test_token_limits_are_per_channel(tmp_path):
    assert COPY_MAX_TOKENS["blog_post"] >= 4000 and COPY_MAX_TOKENS_DEFAULT >= 1500
    agnes = RawAgnes([GOOD])
    app, client = make(tmp_path, agnes)
    _cid, jobs = campaign_with(client, app, "whatsapp")
    asyncio.run(run_copy_job(app, jobs[0]["id"]))
    assert agnes.calls[0]["max_tokens"] == COPY_MAX_TOKENS_DEFAULT


# ---- offer_window

@pytest.mark.parametrize("text,expected", [
    ("9am to 1pm", ("09:00", "13:00")), ("morning nine to one", ("09:00", "13:00")), ("9:30 am - 6 pm", ("09:30", "18:00")),
    ("2 to 6 pm", ("14:00", "18:00")), ("11 am to 2", ("11:00", "14:00")), ("14:00 to 18:00", ("14:00", "18:00")),
    ("evening 6 to 9", ("18:00", "21:00")), ("all day", (None, None)), ("10 to 12 and 4 to 6", (None, None)),
    (None, (None, None)), ("", (None, None)),
])
def test_time_windows_parse_or_give_nulls(text, expected):
    assert plan_module.parse_time_window(text) == expected


def test_plan_carries_the_offer_window_from_the_answers(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="time_window")
    client.post(f"/interview/{sid}/answer", json={"text": "9am to 1pm", "source": "typed"})
    session = client.get(f"/interview/{sid}").json()
    while session["question"] is not None:
        field = session["question"]["field"]
        body = {"terms": {"text": "dine-in only"}, "audiences": {"choices": ["students"]}, "languages": {"choices": ["en"]},
                "channels": {"choices": ["whatsapp"]}, "cta": {"text": "9876543210"}, "tone": {"choices": ["friendly"]}}.get(field, {"choices": ["skip"]})
        session = client.post(f"/interview/{sid}/answer", json={"source": "typed", **body}).json()
    cid = client.post(f"/interview/{sid}/finish").json()["campaign_id"]
    window = client.get(f"/campaign/{cid}/plan").json()["offer_window"]
    assert window == {"days": ["sat", "sun"], "start_date": START, "end_date": END, "time_start": "09:00", "time_end": "13:00"}


def test_offer_window_for_every_day_and_unparseable_time(tmp_path):
    facts = OfferFacts(item="x", audiences=["a"], timings="Every day", dates=[START])
    window = plan_module.offer_window(facts, "whenever we are open")
    assert window == {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "start_date": START, "end_date": None,
                      "time_start": None, "time_end": None}
