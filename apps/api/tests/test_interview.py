"""Interview engine: scripted questions, deterministic reading, grounded AI fallback, edits, finish."""
import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TODAY = date.today()
START = (TODAY + timedelta(days=3)).isoformat()
END = (TODAY + timedelta(days=10)).isoformat()


class ExtractAgnes:
    """Returns scripted extraction JSON for interview and change calls and records the prompts."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        self.calls.append((cache_kind, messages))
        return json.dumps(self.replies.pop(0))


def make(tmp_path, agnes=None):
    settings = Settings(
        agnes_api_key="test-key" if agnes else None,
        agnes_base_url="http://agnes.invalid/v1",
        agnes_origin="http://agnes.invalid",
        database_path=tmp_path / "campaign.db",
        assets_dir=tmp_path / "assets",
    )
    app = create_app(settings)
    if agnes:
        app.state.agnes = agnes
    return app, TestClient(app)


def say(client, sid, text=None, choices=None, source="typed"):
    body = {"source": source}
    if text is not None:
        body["text"] = text
    if choices is not None:
        body["choices"] = choices
    response = client.post(f"/interview/{sid}/answer", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def run_to(client, upto, lang="en", offer="percent_off"):
    """Answer the script with taps and typed values until the question `upto` is next."""
    sid = client.post("/interview/start", json={"lang": lang}).json()["id"]
    plan = dict([
        ("business_name", dict(text="Brew House")),
        ("business_type", dict(choices=["cafe"])),
        ("area", dict(text="Indiranagar, Bengaluru")),
        ("goal", dict(choices=["promote_offer"])),
        ("offer_item", dict(text="filter coffee")),
        ("offer_type", dict(choices=[offer])),
        ("discount_percent", dict(text="20")),
        ("price_amount", dict(text="80")),
        ("start_date", dict(text=START)),
        ("end_date", dict(text=END)),
        ("days", dict(choices=["sat", "sun"])),
        ("time_window", dict(choices=["skip"])),
        ("terms", dict(text="dine-in only")),
        ("audiences", dict(choices=["students", "regulars"])),
        ("languages", dict(choices=["en", "hi"])),
        ("channels", dict(choices=["cold_email", "whatsapp", "instagram_story"])),
        ("cta", dict(text="9876543210")),
        ("email_recipients", dict(text="Asha <asha@example.com>")),
        ("tone", dict(choices=["warm_local"])),
    ])
    session = client.get(f"/interview/{sid}").json()
    while session["question"] is not None and session["question"]["field"] != upto:
        session = say(client, sid, **plan[session["question"]["field"]])
    return sid, session


def test_full_interview_by_taps_and_typed_values_without_a_key(tmp_path):
    app, client = make(tmp_path)
    sid, session = run_to(client, upto="never")
    assert session["status"] == "complete" and session["question"] is None
    assert session["progress"]["answered"] == session["progress"]["total_required"]
    assert session["fields"]["discount_percent"]["value"] == 20
    assert session["fields"]["days"]["value"] == ["sat", "sun"]
    assert session["fields"]["time_window"]["value"] is None
    finished = client.post(f"/interview/{sid}/finish")
    assert finished.status_code == 200
    campaign_id = finished.json()["campaign_id"]
    plan = client.get(f"/campaign/{campaign_id}/plan").json()
    facts = plan["offer_facts"]
    assert facts["item"] == "filter coffee" and facts["discount_percent"] == 20
    assert facts["timings"] == "Saturday and Sunday" and facts["terms"] == "dine-in only"
    assert facts["dates"] == [START, END]
    assert plan["status"] == "draft"


def test_price_branch_skips_the_percent_question(tmp_path):
    _app, client = make(tmp_path)
    sid, session = run_to(client, upto="price_amount", offer="fixed_price")
    assert session["question"]["field"] == "price_amount"
    assert "discount_percent" not in session["fields"]


def test_trap_two_ninety_nine_is_299_and_mooru_nooru_is_300(tmp_path):
    _app, client = make(tmp_path)
    sid, session = run_to(client, upto="price_amount", offer="fixed_price")
    spoken = "ok so this weekend, saturday sunday, brunch combo, avocado toast plus cold brew, two ninety nine only, morning nine to one"
    session = say(client, sid, spoken, source="voice")
    assert session["fields"]["price_amount"]["value"] == 299
    answer = session["answers"][-1] if session["answers"][-1]["field"] == "price_amount" else next(a for a in session["answers"] if a["field"] == "price_amount")
    kn = client.post(f"/interview/{sid}/answers/{answer['id']}",
                     json={"text": "illi weekend ge combo offer, avocado toast mattu cold brew, mooru nooru ge", "source": "voice"})
    body = kn.json()
    # 300 contradicts the 299 said before, so the app asks instead of silently changing it.
    assert body["fields"]["price_amount"]["value"] == 299
    assert body["clarify"]["field"] == "price_amount" and "299" in body["clarify"]["reason"] and "300" in body["clarify"]["reason"]
    confirmed = client.post(f"/interview/{sid}/answers/{answer['id']}", json={"text": "300", "source": "typed"}).json()
    assert confirmed["fields"]["price_amount"]["value"] == 300 and confirmed["clarify"] is None


def test_trap_self_correction_keeps_the_last_offer_and_drops_the_first(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="offer_type")
    session = say(client, sid, "arre 20 percent off rakh do students ko... nahi nahi, buy one get one, coffee pe", source="voice")
    answer = next(a for a in session["answers"] if a["field"] == "offer_type")
    assert answer["value"] == "buy_one_get_one" and answer["status"] == "accepted"
    assert "Dropped" in answer["reason"]
    assert session["question"]["field"] == "start_date"  # no percent question for a BOGO


def test_trap_next_sunday_is_ambiguous_and_asked_again(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="end_date")
    session = say(client, sid, "offer is till sunday, wait, no, next sunday", source="voice")
    assert session["clarify"]["field"] == "end_date" and "Sunday" in session["clarify"]["reason"]
    assert session["question"]["field"] == "end_date"
    assert "end_date" not in session["fields"]


def test_trap_five_hundred_in_terms_becomes_500(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="terms")
    session = say(client, sid, "free banana bread for kids on sunday, with order above five hundred", source="voice")
    assert session["fields"]["terms"]["value"].endswith("order above 500")


def test_days_in_romanised_hindi_and_kannada(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="days")
    session = say(client, sid, "shanivar aur ಭಾನುವಾರ", source="voice")
    assert session["fields"]["days"]["value"] == ["sat", "sun"]


def test_indic_digits_and_words_are_read_as_numbers(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="discount_percent")
    assert say(client, sid, "ಶೇಕಡಾ ೨೦", source="voice")["fields"]["discount_percent"]["value"] == 20


def test_percent_out_of_range_is_rejected(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="discount_percent")
    session = say(client, sid, "150")
    assert session["clarify"]["field"] == "discount_percent" and session["question"]["field"] == "discount_percent"


def test_relative_dates_resolve_against_the_server_today(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="start_date")
    session = say(client, sid, "tomorrow")
    assert session["fields"]["start_date"]["value"] == (TODAY + timedelta(days=1)).isoformat()


def test_end_before_start_is_rejected(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="end_date")
    session = say(client, sid, TODAY.isoformat())
    assert session["clarify"]["reason"] == "The end date is before the start date."


def test_grounding_rejects_a_number_the_owner_did_not_say(tmp_path):
    agnes = ExtractAgnes({"status": "value", "value": 450, "reason": ""})
    _app, client = make(tmp_path, agnes)
    sid, _ = run_to(client, upto="price_amount", offer="fixed_price")
    session = say(client, sid, "the usual weekday rate for that coffee", source="voice")
    assert agnes.calls and agnes.calls[0][0] == "interview"
    assert "price_amount" not in session["fields"]
    assert "450" in session["clarify"]["reason"]


def test_grounding_accepts_a_value_the_owner_said(tmp_path):
    agnes = ExtractAgnes({"status": "value", "value": 120, "reason": ""})
    _app, client = make(tmp_path, agnes)
    sid, _ = run_to(client, upto="price_amount", offer="fixed_price")
    # "ಒಂದು ನೂರು ಇಪ್ಪತ್ತು" is not parsed by the deterministic reader, but 120 is not said either, so grounding decides.
    session = say(client, sid, "price is 120 flat, only that", source="voice")
    assert session["fields"]["price_amount"]["value"] == 120
    assert not agnes.calls  # deterministic reading answered; no model call


def test_grounding_rejects_a_date_and_a_weekday_not_said(tmp_path):
    day = (TODAY + timedelta(days=5)).isoformat()
    agnes = ExtractAgnes({"status": "value", "value": day, "reason": ""},
                         {"status": "value", "value": ["mon", "tue"], "reason": ""})
    _app, client = make(tmp_path, agnes)
    sid, _ = run_to(client, upto="start_date")
    session = say(client, sid, "when the new batch arrives", source="voice")
    assert "start_date" not in session["fields"] and "not a date you said" in session["clarify"]["reason"]
    session = say(client, sid, START)
    session = say(client, sid, START)
    session = say(client, sid, "the usual days", source="voice")
    assert "days" not in session["fields"]
    assert agnes.calls[1][0] == "interview"


def test_voice_text_fields_use_the_model_but_fall_back_to_the_owners_words(tmp_path):
    agnes = ExtractAgnes({"status": "value", "value": "Brew House"}, {"status": "value", "value": "Invented Name"})
    _app, client = make(tmp_path, agnes)
    sid = client.post("/interview/start", json={"lang": "en"}).json()["id"]
    session = say(client, sid, "my cafe is called Brew House", source="voice")
    assert session["fields"]["business_name"]["value"] == "Brew House"
    session = say(client, sid, choices=["cafe"])
    session = say(client, sid, "near the lake in Mysuru", source="voice")
    assert session["fields"]["area"]["value"] == "near the lake in Mysuru"


def test_edit_reruns_dependent_branches(tmp_path):
    _app, client = make(tmp_path)
    sid, session = run_to(client, upto="tone")
    offer = next(a for a in session["answers"] if a["field"] == "offer_type")
    edited = client.post(f"/interview/{sid}/answers/{offer['id']}", json={"choices": ["fixed_price"], "source": "tap"}).json()
    assert edited["status"] == "asking" and edited["question"]["field"] == "price_amount"
    assert "discount_percent" not in edited["fields"]
    done = say(client, sid, "80")
    assert done["question"]["field"] == "tone"


def test_finish_is_refused_while_required_fields_are_missing(tmp_path):
    _app, client = make(tmp_path)
    sid, _ = run_to(client, upto="days")
    refused = client.post(f"/interview/{sid}/finish")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "interview_incomplete"


def test_questions_are_localised_and_the_script_is_not_model_written(tmp_path):
    _app, client = make(tmp_path)
    first = client.post("/interview/start", json={"lang": "kn"}).json()["question"]
    assert first["field"] == "business_name" and "ವ್ಯಾಪಾರ" in first["prompt"]
    assert client.post("/interview/start", json={"lang": "fr"}).status_code == 422


def test_grow_followers_with_no_offer_skips_the_item_question(tmp_path):
    _app, client = make(tmp_path)
    sid = client.post("/interview/start", json={"lang": "en"}).json()["id"]
    for body in (dict(text="Brew House"), dict(choices=["cafe"]), dict(text="Indiranagar"), dict(choices=["grow_followers"])):
        session = say(client, sid, **body)
    assert session["question"]["field"] == "offer_type"
    session = say(client, sid, choices=["no_offer"])
    assert session["question"]["field"] == "start_date"
