"""Persona selection, scoring jobs and the optimizer loop. Agnes is scripted."""
import json

import pytest

from app import persona, plan
from b_helpers import GOOD_COPY, PLAN, make_client, seed, wait_for, write_copy

BETTER = "Sunday only: filter coffee 20% off, just ₹80."
WRONG_PRICE = "Filter coffee 20% off on Sunday only, just ₹60."


class PersonaAgnes:
    """predict calls pop a score level (applied to every dimension); copy calls pop a rewrite."""

    def __init__(self, levels=(), rewrites=()):
        self.levels = list(levels)
        self.rewrites = list(rewrites)
        self.calls = []

    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        self.calls.append((cache_kind, messages))
        if cache_kind == "predict":
            ids = [p["id"] for p in json.loads(messages[1]["content"])["personas"]]
            level = self.levels.pop(0)
            cell = {"score": level, "reason": f"level {level} reason"}
            return json.dumps({"scores": [{"persona_id": pid, **{d: cell for d in persona.DIMENSIONS}} for pid in ids]})
        if cache_kind == "copy":
            return json.dumps({"content": self.rewrites.pop(0), "facts_used": ["item"]})
        raise AssertionError(cache_kind)

    def kinds(self):
        return [kind for kind, _ in self.calls]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(persona, "WAIT_POLL", 0.01)
    monkeypatch.setattr(plan, "get_plan", lambda db, cid: PLAN)
    if not hasattr(plan, "copy_context"):
        # Agent A's copy prompt context; absent until their plan module lands.
        monkeypatch.setattr(plan, "copy_context", lambda db, cid: None, raising=False)

    def build(agnes):
        app, client = make_client(tmp_path, agnes)
        return app, client

    return build


def start(build, agnes):
    app, client = build(agnes)
    client.__enter__()
    campaign_id, assets = seed(client, app)
    asset = assets["whatsapp"]
    write_copy(app, asset)
    return app, client, campaign_id, asset


def test_personas_are_the_synthetic_dataset():
    people = persona.load_personas()
    assert len(people) == 60 and {"id", "segment", "language_pref", "pet_peeves"} <= set(people[0])


def test_pick_language_first_then_segment():
    people = persona.load_personas()
    for lang in ("en", "kn", "hi"):
        picked = persona.pick_personas("c1", {"id": "a1", "lang": lang}, ["students", "office_workers"])
        assert len(picked) == 5
        assert all(persona.covers(p["language_pref"], lang) and p["match"] in ("segment", "language") for p in picked)
        flags = [p["match"] == "segment" for p in picked]
        assert flags == sorted(flags, reverse=True)
        assert picked == persona.pick_personas("c1", {"id": "a1", "lang": lang}, ["students", "office_workers"])
    hindi = persona.pick_personas("c1", {"id": "a1", "lang": "hi"}, ["students"])
    assert {p["language_pref"] for p in hindi} <= {"hi", "hi-en"}
    assert hindi[0]["segment"] == "college_student" and hindi[0]["match"] == "segment"
    assert all(p["match"] == "language" for p in hindi if p["segment"] != "college_student")
    assert persona.covers("hi-en", "en") and persona.covers("kn-en", "kn") and not persona.covers("en", "hi")
    assert len(people) == 60


def test_pick_marks_language_fallback_when_too_few_cover(monkeypatch):
    few = [p for p in persona.load_personas() if not persona.covers(p["language_pref"], "hi") or p["id"] in ("C002", "C003")]
    monkeypatch.setattr(persona, "load_personas", lambda: tuple(few))
    picked = persona.pick_personas("c1", {"id": "a1", "lang": "hi"}, ["families"])
    hindi_ready = [p for p in picked if p["match"] != "language_fallback"]
    assert len(hindi_ready) == len([p for p in few if persona.covers(p["language_pref"], "hi")])
    fallback = [p for p in picked if p["match"] == "language_fallback"]
    assert fallback and all(persona.covers(p["language_pref"], "en") and not persona.covers(p["language_pref"], "hi") for p in fallback)


def test_pick_with_no_matching_audience_is_seeded_per_language():
    a = persona.pick_personas("c9", {"id": "a1", "lang": "hi"}, ["pet owners"])
    b = persona.pick_personas("c9", {"id": "zzz", "lang": "hi"}, [])
    assert a == b and all(p["match"] == "language" and persona.covers(p["language_pref"], "hi") for p in a)
    assert a != persona.pick_personas("c9", {"id": "a1", "lang": "kn"}, [])
    assert a != persona.pick_personas("c10", {"id": "a1", "lang": "hi"}, [])


def test_predict_scores_and_labels(rig):
    agnes = PersonaAgnes(levels=[8])
    app, client, campaign_id, asset = start(rig, agnes)
    resp = client.post(f"/campaign/{campaign_id}/predict")
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "Pre-launch prediction from synthetic personas"
    assert body["queued"] == [asset["id"]]
    assert {s["reason"] for s in body["skipped"]} == {"not_written"}
    wait_for(lambda: client.get(f"/campaign/{campaign_id}/predictions").json()["items"])
    item = client.get(f"/campaign/{campaign_id}/predictions").json()
    assert item["label"] == persona.LABEL
    pred = item["items"][0]
    assert pred["mean"] == 8 and set(pred["dimensions"]) == set(persona.DIMENSIONS) and len(pred["personas"]) == 5
    assert all(p["synthetic"] and p["scores"]["trust"]["reason"] == "level 8 reason" for p in pred["personas"])
    assert all(p["match"] in ("segment", "language") and p["language_pref"] for p in pred["personas"])
    sent = json.loads(agnes.calls[0][1][1]["content"])
    assert all(p["language_pref"] for p in sent["personas"]) and "language_pref" in agnes.calls[0][1][0]["content"]
    activity = [a for a in client.get(f"/campaign/{campaign_id}/dashboard").json()["activity"] if a["kind"] == "prediction_ready"]
    assert activity and activity[0]["asset_id"] == asset["id"]
    state = client.get(f"/campaign/{campaign_id}/assets/state").json()[asset["id"]]["prediction"]
    assert state["label"] == persona.LABEL and state["history"][0]["content"] == GOOD_COPY
    dash = client.get(f"/campaign/{campaign_id}/dashboard").json()["predictions"]
    assert dash["label"] == persona.LABEL and dash["items"][0]["before_mean"] == 8 and dash["items"][0]["after_mean"] is None
    # Scored content is not scored twice.
    again = client.post(f"/campaign/{campaign_id}/predict").json()
    assert again["queued"] == [] and {"asset_id": asset["id"], "reason": "already_scored"} in again["skipped"]
    client.__exit__(None, None, None)


def test_bad_model_output_fails_the_job_without_a_prediction(rig):
    class Broken(PersonaAgnes):
        text_ready = True

        async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
            return json.dumps({"scores": [{"persona_id": "nobody"}]})

    app, client, campaign_id, asset = start(rig, Broken())
    client.post(f"/campaign/{campaign_id}/predict")
    wait_for(lambda: app.state.db.query_one("SELECT * FROM job WHERE kind = 'predict' AND status = 'failed'"))
    assert app.state.db.query("SELECT * FROM prediction") == []
    client.__exit__(None, None, None)


def test_optimize_rewrites_low_scores_and_rescores_once_target_met(rig):
    agnes = PersonaAgnes(levels=[5, 8], rewrites=[BETTER])
    app, client, campaign_id, asset = start(rig, agnes)
    client.post(f"/campaign/{campaign_id}/predict")
    wait_for(lambda: persona.latest_prediction(app.state.db, asset["id"]))
    opt = client.post(f"/campaign/{campaign_id}/optimize").json()
    assert opt["started"] == [asset["id"]] and opt["label"] == persona.LABEL
    wait_for(lambda: (app.state.db.query_one("SELECT * FROM optimization")["status"] == "done"))
    pred = client.get(f"/campaign/{campaign_id}/assets/state").json()[asset["id"]]["prediction"]
    assert [(h["seq"], h["mean"], h["content"]) for h in pred["history"]] == [(0, 5, GOOD_COPY), (1, 8, BETTER)]
    assert pred["optimization"]["loops"] == 1 and "reached" in pred["optimization"]["detail"]
    assert app.state.db.asset_get(asset["id"])["content"] == BETTER
    feedback = [m for kind, m in agnes.calls if kind == "copy"][0]
    assert "level 5 reason" in json.dumps(json.loads(feedback[1]["content"])["problems_to_fix"])
    again = client.post(f"/campaign/{campaign_id}/optimize").json()
    assert again["started"] == [] and again["skipped"][0]["reason"] == "target_reached"
    client.__exit__(None, None, None)


def test_optimize_stops_after_two_loops(rig):
    agnes = PersonaAgnes(levels=[4, 5, 6], rewrites=[BETTER, "Filter coffee, 20% off, Sunday only, just ₹80."])
    app, client, campaign_id, asset = start(rig, agnes)
    client.post(f"/campaign/{campaign_id}/predict")
    wait_for(lambda: persona.latest_prediction(app.state.db, asset["id"]))
    client.post(f"/campaign/{campaign_id}/optimize")
    wait_for(lambda: (app.state.db.query_one("SELECT * FROM optimization")["status"] == "done"))
    row = app.state.db.query_one("SELECT * FROM optimization")
    assert row["loops"] == 2 and "Stopped after 2 loops at mean 6" in row["detail"]
    assert [p["mean"] for p in client.get(f"/campaign/{campaign_id}/predictions").json()["items"][0]["history"]] == [4, 5, 6]
    assert agnes.kinds().count("copy") == 2
    third = client.post(f"/campaign/{campaign_id}/optimize").json()
    assert third["started"] == [] and third["skipped"][0]["reason"] == "loops_exhausted"
    client.__exit__(None, None, None)


def test_rewrite_that_fails_the_checks_is_not_scored_and_the_old_copy_returns(rig):
    agnes = PersonaAgnes(levels=[4], rewrites=[WRONG_PRICE, WRONG_PRICE])
    app, client, campaign_id, asset = start(rig, agnes)
    client.post(f"/campaign/{campaign_id}/predict")
    wait_for(lambda: persona.latest_prediction(app.state.db, asset["id"]))
    client.post(f"/campaign/{campaign_id}/optimize")
    wait_for(lambda: (app.state.db.query_one("SELECT * FROM optimization")["status"] == "stopped"))
    assert "restored" in app.state.db.query_one("SELECT * FROM optimization")["detail"]
    restored = app.state.db.asset_get(asset["id"])
    assert restored["content"] == GOOD_COPY and restored["status"] == "pending"
    assert agnes.kinds().count("predict") == 1
    client.__exit__(None, None, None)


def test_optimize_needs_predictions_and_leaves_approved_assets(rig):
    agnes = PersonaAgnes(levels=[3])
    app, client, campaign_id, asset = start(rig, agnes)
    assert client.post(f"/campaign/{campaign_id}/optimize").json()["detail"]["code"] == "no_predictions"
    client.post(f"/campaign/{campaign_id}/predict")
    wait_for(lambda: persona.latest_prediction(app.state.db, asset["id"]))
    app.state.db.asset_update(asset["id"], status="approved")
    out = client.post(f"/campaign/{campaign_id}/optimize").json()
    assert out["started"] == [] and out["skipped"] == [{"asset_id": asset["id"], "reason": "approved_asset_not_rewritten"}]
    assert client.post("/campaign/nope/predict").status_code == 404
    client.__exit__(None, None, None)
