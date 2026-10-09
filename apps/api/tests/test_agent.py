"""Agent: grounded brief, interview feeding, human gates. No network."""
import json

from fastapi.testclient import TestClient

from app import agent
from app.config import Settings
from app.main import create_app

IDEA = ("Brew Bandi Cafe is a cafe in Indiranagar Bengaluru. I want to promote an offer: 20% off filter coffee "
        "starting 2030-01-05 on weekend for students and families in English and Kannada on WhatsApp and poster. "
        "Reach us at https://instagram.com/brewbandi and keep the tone warm.")
BRIEF = {"fields": {
    "business_name": "Brew Bandi Cafe", "business_type": "cafe", "area": "Indiranagar Bengaluru", "goal": "promote an offer",
    "offer_item": "filter coffee", "offer_type": "20% off", "discount_percent": "20%", "start_date": "2030-01-05",
    "days": "weekend", "audiences": "students and families", "languages": "English and Kannada",
    "channels": "WhatsApp and poster", "cta": "https://instagram.com/brewbandi", "tone": "warm"}}


class FakeAgnes:
    def __init__(self, brief):
        self.brief = brief
        self.kinds = []

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        self.kinds.append(cache_kind)
        if cache_kind == "agent_brief":
            return json.dumps(self.brief)
        return json.dumps({})  # interview AI fallback: nothing extracted, deterministic reading must carry it


def make(tmp_path, brief):
    s = Settings(agnes_api_key="k", agnes_base_url="http://agnes.invalid/v1", agnes_origin="http://agnes.invalid",
                 database_path=tmp_path / "t.db", assets_dir=tmp_path / "a")
    app = create_app(s)
    app.state.agnes = FakeAgnes(brief)
    return app, TestClient(app)


def test_brief_keeps_only_exact_spans_of_the_owners_words():
    out = agent.ground_brief(IDEA, {"fields": {**BRIEF["fields"], "area": "Koramangala", "terms": "dine-in only"}, "budget_inr": 5000})
    assert out["fields"]["business_name"] == "Brew Bandi Cafe"
    assert "area" in out["dropped"] and "terms" in out["dropped"]  # invented, so thrown away
    assert "_budget_inr" not in out["fields"]  # 5000 is not in the idea


def test_budget_is_kept_only_when_the_number_is_in_the_idea():
    out = agent.ground_brief(IDEA + " My budget is 5,000 rupees.", {"fields": {}, "budget_inr": 5000})
    assert out["fields"]["_budget_inr"] == 5000.0


def test_agent_answers_from_the_idea_and_stops_at_the_plan_lock(tmp_path):
    app, c = make(tmp_path, BRIEF)
    r = c.post("/agent/runs", json={"idea": IDEA, "lang": "en"})
    assert r.status_code == 200, r.text
    run = r.json()
    steps = {s["id"]: s for s in run["steps"]}
    assert steps["understand"]["status"] == "done"
    assert steps["interview"]["status"] == "done", steps["interview"]
    assert steps["plan_lock"]["status"] == "needs_you" and run["status"] == "needs_you"
    assert steps["write"]["status"] == "pending"  # nothing is written before the owner locks the plan
    assert run["campaign_id"]
    # every answer is a span of the idea
    plan = c.get(f"/campaign/{run['campaign_id']}/plan").json()
    assert plan["business"]["name"] == "Brew Bandi Cafe" and plan["offer_facts"]["discount_percent"] == 20
    assert plan["status"] == "draft"


def test_agent_asks_the_owner_when_the_idea_lacks_a_required_fact(tmp_path):
    thin = {"fields": {"business_name": "Brew Bandi Cafe", "business_type": "cafe"}}
    app, c = make(tmp_path, thin)
    run = c.post("/agent/runs", json={"idea": IDEA, "lang": "en"}).json()
    steps = {s["id"]: s for s in run["steps"]}
    assert steps["interview"]["status"] == "needs_you"
    assert steps["interview"]["action"]["screen"] == "voice" and run["session_id"]
    assert "Needs you" in steps["interview"]["detail"]
    assert run["campaign_id"] is None


def test_tick_is_idempotent_and_resumes_after_the_owner_locks(tmp_path):
    app, c = make(tmp_path, BRIEF)
    run = c.post("/agent/runs", json={"idea": IDEA, "lang": "en"}).json()
    again = c.post(f"/agent/runs/{run['id']}/tick").json()
    assert again["campaign_id"] == run["campaign_id"]
    assert c.get("/agent/runs").json()["runs"][0]["id"] == run["id"]
    lock = c.post(f"/campaign/{run['campaign_id']}/plan/approve")
    assert lock.status_code == 200
    after = c.post(f"/agent/runs/{run['id']}/tick").json()
    steps = {s["id"]: s for s in after["steps"]}
    assert steps["plan_lock"]["status"] == "done"
    assert steps["budget"]["status"] == "done"
    assert steps["write"]["status"] in ("running", "failed")  # the fake model cannot write copy


def test_gates_only_accept_known_steps(tmp_path):
    app, c = make(tmp_path, BRIEF)
    run = c.post("/agent/runs", json={"idea": IDEA, "lang": "en"}).json()
    assert c.post(f"/agent/runs/{run['id']}/steps/approve/skip").status_code == 422
    assert c.post(f"/agent/runs/{run['id']}/steps/plan_lock/confirm").status_code == 422
    assert c.post("/agent/runs/nope/tick").status_code == 404


def test_agent_needs_a_key(tmp_path):
    s = Settings(agnes_api_key=None, agnes_base_url="http://x.invalid/v1", agnes_origin="http://x.invalid",
                 database_path=tmp_path / "t.db", assets_dir=tmp_path / "a")
    c = TestClient(create_app(s))
    r = c.post("/agent/runs", json={"idea": IDEA, "lang": "en"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "brain_not_configured"
