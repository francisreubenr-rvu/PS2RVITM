"""Copy -> fact check -> meaning check -> one repair, driven by a scripted Agnes stand-in (no network)."""

import asyncio
import json
import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.worker import run_copy_job

SUNDAY_KN = "ಭಾನುವಾರ ಮಾತ್ರ ಫಿಲ್ಟರ್ ಕಾಫಿ 20% ರಿಯಾಯಿತಿ, ಕೇವಲ ₹80."
GOOD_BACK = "Filter coffee 20% off on Sunday only, just ₹80."


class ScriptedAgnes:
    """Answers copy and review calls from queues, and records every request."""

    def __init__(self, copies=(), reviews=()):
        self.copies = list(copies)
        self.reviews = list(reviews)
        self.calls = []
        self.second = []
        self.last_review = None

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        if cache_kind == "brief":
            return json.dumps({"item": "filter coffee", "audiences": ["regulars"]})
        self.calls.append((cache_kind, messages))
        if cache_kind == "copy":
            return json.dumps({"content": self.copies.pop(0), "facts_used": ["item", "timings"]})
        if cache_kind in ("review2", "review3"):
            # The second blind pass confirms the first by default; tests that need a different second pass set it.
            back, problems = self.second.pop(0) if self.second else self.last_review
        else:
            back, problems = self.last_review = self.reviews.pop(0)
        return json.dumps({"back_translation": back, "language_problems": problems})

    def kinds(self):
        return [kind for kind, _ in self.calls]


def setup(tmp_path, agnes, lang="kn"):
    settings = Settings(
        agnes_api_key="test-key",
        agnes_base_url="http://agnes.invalid/v1",
        agnes_origin="http://agnes.invalid",
        database_path=tmp_path / "campaign.db",
        assets_dir=tmp_path / "assets",
    )
    app = create_app(settings)
    app.state.agnes = agnes
    client = TestClient(app)
    campaign_id = client.post("/campaigns", json={"transcript": "Sunday coffee"}).json()["campaign"]["id"]
    facts = {
        "item": "filter coffee",
        "discount_percent": 20,
        "price_amount": 80,
        "timings": "Sunday only",
        "audiences": ["regulars"],
        "languages": [lang],
        "channels": ["whatsapp"],
    }
    client.put(f"/campaigns/{campaign_id}/facts", json=facts)
    client.post("/facts/approve", json={"campaign_id": campaign_id})
    return app, client, campaign_id


def generate(app, campaign_id):
    """Queue copy jobs directly and run them, plus every follow-up job, to completion."""
    from app.service import Service

    jobs = Service(app.state.db).prepare_generation(campaign_id, has_key=True)

    async def run():
        for job in jobs:
            await run_copy_job(app, job["id"])
        loop = asyncio.get_running_loop()
        while pending := [task for task in app.state.tasks if task.get_loop() is loop and not task.done()]:
            await asyncio.gather(*pending)

    asyncio.run(run())
    return app.state.db.assets_for(campaign_id)[0]


def test_kannada_copy_passes_the_meaning_check(tmp_path):
    agnes = ScriptedAgnes(copies=[SUNDAY_KN], reviews=[(GOOD_BACK, [])])
    app, client, campaign_id = setup(tmp_path, agnes)
    asset = generate(app, campaign_id)
    assert agnes.kinds() == ["copy", "review", "review2", "review3"]
    assert asset["status"] == "pending"
    assert json.loads(asset["review"])["status"] == "ok"
    assert client.post(f"/assets/{asset['id']}/approve").status_code == 200


def test_reviewer_is_blind_to_the_offer_facts(tmp_path):
    agnes = ScriptedAgnes(copies=[SUNDAY_KN], reviews=[(GOOD_BACK, [])])
    app, _client, campaign_id = setup(tmp_path, agnes)
    generate(app, campaign_id)
    review_prompt = json.dumps(agnes.calls[1][1] + agnes.calls[2][1] + agnes.calls[3][1], ensure_ascii=False)
    assert "offer_facts" not in review_prompt
    assert "Sunday only" not in review_prompt


def test_copy_prompt_gives_the_locked_day_in_kannada(tmp_path):
    agnes = ScriptedAgnes(copies=[SUNDAY_KN], reviews=[(GOOD_BACK, [])])
    app, _client, campaign_id = setup(tmp_path, agnes)
    generate(app, campaign_id)
    request = json.loads(agnes.calls[0][1][1]["content"])
    assert request["weekday_words_to_use"] == ["ಭಾನುವಾರ"]


def test_flagged_meaning_is_repaired_once_with_the_reasons(tmp_path):
    agnes = ScriptedAgnes(
        copies=["ಫಿಲ್ಟರ್ ಕಾಫಿ ಭಾನುವಾರ 20% ರಿಯಾಯಿತಿ ₹80 [ಏಳವಾರ]", SUNDAY_KN],
        reviews=[("Filter coffee 20% off on Sunday and [elavara], every day, ₹80.",
                  [{"quote": "ಏಳವಾರ", "type": "not_a_word", "note": "invented weekday", "fix": "ಭಾನುವಾರ"}]),
                 (GOOD_BACK, [])],
    )
    app, client, campaign_id = setup(tmp_path, agnes)
    asset = generate(app, campaign_id)
    assert agnes.kinds() == ["copy", "review", "review2", "review3", "copy", "review", "review2", "review3"]
    repair = json.loads(agnes.calls[4][1][1]["content"])
    assert any("not a word" in issue and "ಏಳವಾರ" in issue for issue in repair["problems_to_fix"])
    assert any("widens" in issue for issue in repair["problems_to_fix"])
    assert asset["content"] == SUNDAY_KN
    assert asset["status"] == "pending"
    assert json.loads(asset["review"])["status"] == "ok"


def test_repair_stops_after_one_attempt_and_leaves_the_asset_blocked(tmp_path):
    bad_back = ("Filter coffee 20% off on Saturday, ₹80.", [])
    agnes = ScriptedAgnes(copies=[SUNDAY_KN, SUNDAY_KN + " "], reviews=[bad_back, bad_back])
    app, client, campaign_id = setup(tmp_path, agnes)
    asset = generate(app, campaign_id)
    assert agnes.kinds() == ["copy", "review", "review2", "review3", "copy", "review", "review2", "review3"]
    assert asset["status"] == "blocked"
    assert any("Saturday" in reason for reason in json.loads(asset["block_reason"]))
    refused = client.post(f"/assets/{asset['id']}/approve")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "meaning_check_flagged"
    events = [e["action"] for e in client.get(f"/campaign/{campaign_id}/board").json()["events"]]
    assert "repair_exhausted" in events


def test_english_fact_failure_is_repaired_without_a_meaning_check(tmp_path):
    agnes = ScriptedAgnes(copies=["Filter coffee 20% off this Saturday, ₹80.", "Filter coffee 20% off this Sunday, ₹80."])
    app, _client, campaign_id = setup(tmp_path, agnes, lang="en")
    asset = generate(app, campaign_id)
    assert agnes.kinds() == ["copy", "copy"]
    assert asset["status"] == "pending"
    assert json.loads(asset["review"])["status"] == "not_needed"


def test_owner_edit_is_checked_but_never_rewritten(tmp_path):
    agnes = ScriptedAgnes(copies=[SUNDAY_KN], reviews=[(GOOD_BACK, []), ("Filter coffee on Saturday, ₹80.", [])])
    app, client, campaign_id = setup(tmp_path, agnes)
    asset = generate(app, campaign_id)
    with client:
        edited = client.patch(f"/assets/{asset['id']}", json={"content": "ಭಾನುವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ ₹80"})
        assert edited.json()["review"]["status"] == "checking"
        refused = client.post(f"/assets/{asset['id']}/approve")
        assert refused.json()["detail"]["code"] in {"meaning_check_running", "meaning_check_flagged"}
        for _ in range(100):
            if json.loads(app.state.db.asset_get(asset["id"])["review"])["status"] != "checking":
                break
            asyncio.run(asyncio.sleep(0.02))
    final = app.state.db.asset_get(asset["id"])
    assert json.loads(final["review"])["status"] == "flagged"
    assert final["content"] == "ಭಾನುವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ ₹80"
    assert agnes.kinds().count("copy") == 1


def test_generate_does_not_overwrite_written_copy(tmp_path):
    agnes = ScriptedAgnes(copies=[SUNDAY_KN], reviews=[(GOOD_BACK, [])])
    app, client, campaign_id = setup(tmp_path, agnes)
    generate(app, campaign_id)
    from app.service import Service

    assert Service(app.state.db).prepare_generation(campaign_id, has_key=True) == []


def test_migrate_adds_new_columns_to_an_old_database(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE asset (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, audience TEXT NOT NULL, "
                 "lang TEXT NOT NULL, channel TEXT NOT NULL, type TEXT NOT NULL, content TEXT, "
                 "facts_used TEXT NOT NULL DEFAULT '[]', facts_version INTEGER, status TEXT NOT NULL, "
                 "block_reason TEXT, score REAL, score_detail TEXT, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE job (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, asset_id TEXT, kind TEXT NOT NULL, "
                 "status TEXT NOT NULL, detail TEXT, provider_ref TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.commit()
    conn.close()
    Database(path).migrate()
    conn = sqlite3.connect(path)
    assert "review" in {row[1] for row in conn.execute("PRAGMA table_info(asset)")}
    assert "payload" in {row[1] for row in conn.execute("PRAGMA table_info(job)")}


def test_reviewer_complaints_must_quote_the_copy_and_name_a_real_defect():
    from app.review import grounded_problems

    content = "ರವಿವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ, ರವಿವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ"
    kept, dropped = grounded_problems(
        [
            {"quote": "ಭಾನುಗಾಲ", "type": "not_a_word"},
            {"quote": "ರವಿವಾರ ಫಿಲ್ಟರ್", "type": "grammar"},
            {"quote": "ರವಿವಾರ  ಫಿಲ್ಟರ್ ಕಾಫಿ", "type": "repeated", "note": "said twice", "fix": "ರವಿವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ ಒಮ್ಮೆ"},
            "free text complaint",
        ],
        content,
    )
    assert dropped == 3
    assert kept == ["repeated: \u201cರವಿವಾರ ಫಿಲ್ಟರ್ ಕಾಫಿ\u201d (said twice)"]
