"""Review panel: independent reviewers, a code referee, quotes must be real. No network."""
import asyncio
import json

from app import panel
from app.schemas import OfferFacts
from tests.b_helpers import make_client, seed

FACTS = OfferFacts(item="filter coffee", discount_percent=20, timings="Sunday only", audiences=["regulars"], languages=["en"], channels=["whatsapp"])
TEXT = "The best coffee in town! Filter coffee 20% off on Sunday only. Only today, hurry!"


def test_tone_concern_needs_a_real_quote():
    ok = panel.parse_tone(json.dumps({"verdict": "concern", "reason": "pushy", "quote": "hurry"}), TEXT)
    assert ok["verdict"] == "concern" and ok["quote"] == "hurry"
    bad = panel.parse_tone(json.dumps({"verdict": "concern", "reason": "pushy", "quote": "buy right now"}), TEXT)
    assert bad["verdict"] == "unchecked"  # an uncheckable concern is ignored, never shown as a finding
    assert panel.parse_tone("nonsense", TEXT)["verdict"] == "unchecked"
    assert panel.parse_tone(json.dumps({"verdict": "ok"}), TEXT)["verdict"] == "ok"


def test_claims_keep_only_quotes_that_are_in_the_copy():
    raw = json.dumps({"concerns": [{"quote": "best coffee in town", "type": "superlative", "reason": "unprovable"},
                                   {"quote": "100% organic", "type": "health", "reason": "not in copy"}]})
    out = panel.parse_claims(raw, TEXT)
    assert out["verdict"] == "concern" and out["quote"] == "best coffee in town" and "superlative" in out["reason"]
    assert panel.parse_claims(json.dumps({"concerns": [{"quote": "100% organic", "type": "health", "reason": "x"}]}), TEXT)["verdict"] == "ok"
    assert panel.parse_claims(json.dumps({"concerns": []}), TEXT)["verdict"] == "ok"


def test_facts_reviewer_is_deterministic():
    assert panel.facts_review("Filter coffee 20% off on Sunday only.", FACTS)["verdict"] == "ok"
    bad = panel.facts_review("Filter coffee 30% off on Sunday only.", FACTS)
    assert bad["verdict"] == "block" and "30" in bad["reason"]


def test_referee_merges_and_names_disagreements():
    v = lambda r, s: panel.verdict(r, s)
    assert panel.referee([v("facts", "ok"), v("meaning", "ok"), v("tone", "ok"), v("claims", "ok")]) == {"status": "clear", "needs_human": False, "disagreements": []}
    mixed = panel.referee([v("facts", "ok"), v("meaning", "ok"), v("tone", "ok"), v("claims", "concern")])
    assert mixed["status"] == "review" and mixed["needs_human"] and any("claims raised a concern that" in d for d in mixed["disagreements"])
    assert panel.referee([v("facts", "block"), v("meaning", "ok"), v("tone", "ok"), v("claims", "ok")])["status"] == "blocked"
    inc = panel.referee([v("facts", "ok"), v("meaning", "unchecked"), v("tone", "ok"), v("claims", "ok")])
    assert inc["status"] == "incomplete" and inc["needs_human"]  # unchecked is never approval


class PanelAgnes:
    text_ready = True

    async def chat(self, messages, *, cache_kind, temperature=0.2, max_tokens=1200):
        if cache_kind == "panel_tone":
            return json.dumps({"verdict": "ok", "reason": "Warm enough."})
        return json.dumps({"concerns": [{"quote": "best coffee in town", "type": "superlative", "reason": "unprovable"}]})


def test_panel_route_runs_all_reviewers_and_flags_stale_edits(tmp_path, monkeypatch):
    app, c = make_client(tmp_path, PanelAgnes())
    cid, assets = seed(c, app)
    db = app.state.db
    db.execute("UPDATE asset SET content = ? WHERE campaign_id = ?", ("The best coffee in town! Filter coffee 20% off on Sunday only.", cid))
    monkeypatch.setattr(panel.plan, "get_plan", lambda d, i: {"offer_facts": FACTS.model_dump(), "tone": "warm_local"})
    assert c.get(f"/campaign/{cid}/panel").json()["summary"]["reviewed"] == 0
    asyncio.run(panel.run_panel(app, cid))  # the route spawns this; run it directly so the test is deterministic
    out = c.get(f"/campaign/{cid}/panel").json()
    assert out["summary"]["reviewed"] == out["summary"]["assets"] > 0
    wa = next(i for i in out["items"] if i["channel"] == "whatsapp")
    assert {v["reviewer"] for v in wa["verdicts"]} == set(panel.REVIEWERS)
    assert wa["status"] == "review" and wa["needs_human"]
    claims = next(v for v in wa["verdicts"] if v["reviewer"] == "claims")
    assert claims["quote"] == "best coffee in town"
    db.execute("UPDATE asset SET content = ? WHERE id = ?", ("Filter coffee 20% off on Sunday only.", wa["asset_id"]))
    again = next(i for i in c.get(f"/campaign/{cid}/panel").json()["items"] if i["asset_id"] == wa["asset_id"])
    assert again["stale"] is True and again["reviewed"] is False  # an edited asset must be reviewed again


def test_panel_needs_a_campaign_and_a_key(tmp_path):
    app, c = make_client(tmp_path, PanelAgnes(), key=None)
    assert c.post("/campaign/nope/panel").status_code == 404
