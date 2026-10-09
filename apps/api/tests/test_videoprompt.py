"""Video prompt refinement: the Groq Qwen refiner turns the reel brief into a prompt the owner edits, then Agnes is asked with that
prompt. No network: the provider and Agnes are faked.

These tests pin the one model, the honest not-configured answer when Groq is off or unkeyed, the master-doc video rules in the
system prompt, that offer words and numbers never reach the model, the strict shaping of the reply, and that generation uses the
owner's edited prompt behind the same opt-in and budget gates as the existing video route.
"""
import json
import uuid

import httpx
import pytest

from app import brain, media, plan, videoprompt
from b_helpers import PLAN, make_client, seed, wait_for
from test_media import MP4, VideoAgnes

GOOD = {
    "prompt": ("A glass tumbler of filter coffee on a worn wooden counter, side window light from the left, background softly out of focus. "
               "The frame holds still, with no camera movement. Steam drifts above the cup. Opening beat: the tumbler alone. Middle beat: the "
               "same tumbler with an empty stretch of counter on the right. Closing beat: the counter and door behind. Quiet cafe ambience, no "
               "speech, no singing. Same tumbler throughout. Leave the right third calm for the overlay."),
    "beats": ["The tumbler alone on the counter.", "The same tumbler, empty counter beside it.", "The counter and the door behind."],
    "left_out": ["The shop interior, which the brief does not describe."],
}


class Fake:
    calls: list = []
    reply = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        Fake.calls.append((url, kw))
        return Fake.reply(url, kw) if callable(Fake.reply) else Fake.reply


def groq_reply(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    Fake.calls, Fake.reply = [], groq_reply(GOOD)
    monkeypatch.setattr(videoprompt.httpx, "AsyncClient", Fake)
    monkeypatch.setattr(plan, "get_plan", lambda db, cid: PLAN)
    monkeypatch.setattr(media, "VIDEO_POLL", 0.01)

    async def fake_fetch(url, limit=0):
        return MP4

    monkeypatch.setattr(media, "fetch_bytes", fake_fetch)
    agnes = VideoAgnes(statuses=[{"status": "completed", "url": "https://cdn.example/v.mp4"}])
    app, c = make_client(tmp_path, agnes)
    c.__enter__()
    _, assets = seed(c, app)
    row = dict(assets["whatsapp"])
    row.update(id=uuid.uuid4().hex, channel="reel", type="reel")
    app.state.db.asset_insert(row)
    app.state.db.execute("UPDATE asset SET extra = ? WHERE id = ?", (json.dumps({"script": ["Steam rises from a cup", "Sunday filter coffee"]}), row["id"]))
    yield app, c, row["id"], agnes, monkeypatch
    c.__exit__(None, None, None)


def refine(c, reel, **body):
    return c.post("/video/refine", json={"asset_id": reel, **body})


def test_no_key_is_503_and_nothing_leaves(rig):
    _, c, reel, _, _ = rig
    r = refine(c, reel)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "brain_not_configured"
    assert Fake.calls == []


def test_the_settings_switch_is_respected(rig):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    c.put("/settings/toggles/groq", json={"enabled": False})
    assert refine(c, reel).status_code == 503
    assert Fake.calls == []


def test_one_model_and_the_master_doc_rules(rig):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    assert refine(c, reel).status_code == 200
    sent = Fake.calls[-1][1]["json"]
    assert sent["model"] == brain.GROQ_MODEL == "qwen/qwen3.8-27b" and "gpt-oss" not in sent["model"]
    assert sent["response_format"] == {"type": "json_object"}
    system = sent["messages"][0]["content"]
    for rule in ("Motion is opt-in", "no push-in, no parallax", "Recognition", "Offer", "Action", "concrete nouns and verbs",
                 "cinematic, luxury, epic", "never drawn by the video model", "invent nothing", "no speech and no vocals", "no placeholders"):
        assert rule in system, rule


def test_the_model_gets_the_item_and_script_but_no_offer_figures(rig):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    refine(c, reel, aspect="9:16", note="Keep it calm")
    sent = Fake.calls[-1][1]["json"]["messages"][1]["content"]
    brief = json.loads(sent)
    assert brief["offer_item"] == "filter coffee" and brief["business_type"] == "cafe" and brief["aspect"] == "9:16"
    assert brief["script_lines"] == ["Steam rises from a cup", "Sunday filter coffee"] and brief["references"] == []
    assert brief["motion_opt_in"] is False and brief["motion_note"] == "" and brief["owner_note"] == "Keep it calm"
    assert "80" not in sent and "20" not in sent and "Sunday only" not in sent


def test_motion_note_is_sent_only_when_opted_in(rig):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    refine(c, reel, motion_opt_in=False, motion_note="slow zoom in")
    assert json.loads(Fake.calls[-1][1]["json"]["messages"][1]["content"])["motion_note"] == ""
    refine(c, reel, motion_opt_in=True, motion_note="steam rises")
    brief = json.loads(Fake.calls[-1][1]["json"]["messages"][1]["content"])
    assert brief["motion_opt_in"] is True and brief["motion_note"] == "steam rises"


def test_the_contract_is_returned_shaped(rig):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    out = refine(c, reel).json()
    assert out["asset_id"] == reel and out["model"] == "qwen/qwen3.8-27b" and out["aspect"] == "16:9"
    assert out["prompt"] == GOOD["prompt"]
    assert [b["beat"] for b in out["beats"]] == ["Recognition", "Offer", "Action"]
    assert out["left_out"] == GOOD["left_out"] and out["order"][0] == "subject and setting"


@pytest.mark.parametrize("bad", [
    "not json at all",
    {"prompt": "short", "beats": ["a", "b", "c"], "left_out": []},
    {**GOOD, "beats": ["only one"]},
    {**GOOD, "left_out": "none"},
    {**GOOD, "prompt": GOOD["prompt"] + " Now only ₹80."},
    {**GOOD, "prompt": GOOD["prompt"] + " Twenty is fine but 20 percent off is not."},
    {**GOOD, "prompt": GOOD["prompt"] + " Show <product name> here."},
])
def test_a_bad_reply_is_502_and_never_shown(rig, bad):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.reply = groq_reply(bad)
    r = refine(c, reel)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "brain_bad_reply"


def test_a_provider_error_is_502(rig):
    _, c, reel, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    Fake.reply = httpx.Response(500, text="boom")
    assert refine(c, reel).json()["detail"]["code"] == "brain_provider_error"


def test_only_a_reel_can_be_refined(rig):
    app, c, _, _, mp = rig
    mp.setenv("GROQ_API_KEY", "gk")
    other = app.state.db.query_one("SELECT id FROM asset WHERE channel = 'whatsapp'")["id"]
    assert refine(c, other).json()["detail"]["code"] == "no_video_for_channel"
    assert refine(c, "missing").status_code == 404


def test_generate_uses_the_owner_s_prompt_and_the_opt_in(rig):
    _, c, reel, agnes, _ = rig
    edited = "A glass tumbler of filter coffee on a wooden counter, window light from the left, the frame holds still."
    refused = c.post("/video/generate", json={"asset_id": reel, "prompt": edited})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "motion_not_opted_in"
    body = c.post("/video/generate", json={"asset_id": reel, "prompt": edited, "motion_opt_in": True, "aspect": "9:16"}).json()
    assert body["kind"] == "video" and body["ratio"] == "9:16"
    wait_for(lambda: c.get(f"/jobs/{body['job_id']}").json()["status"] == "completed")
    sent = agnes.created[0]
    assert sent["prompt"].startswith(edited) and "free of lettering" in sent["prompt"] and sent["aspect_ratio"] == "9:16"


def test_generate_refuses_offer_figures_and_thin_prompts(rig):
    _, c, reel, agnes, _ = rig
    ok = {"asset_id": reel, "motion_opt_in": True}
    thin = c.post("/video/generate", json={**ok, "prompt": "coffee"})
    assert thin.status_code == 422 and thin.json()["detail"]["code"] == "prompt_too_short"
    priced = c.post("/video/generate", json={**ok, "prompt": "A glass of filter coffee on a counter with a sign that says 20 off."})
    assert priced.status_code == 422 and priced.json()["detail"]["code"] == "prompt_has_offer_text"
    assert agnes.created == []


def test_static_reel_encodes_constant_landscape_frames(rig):
    import shutil, subprocess, io
    from b_helpers import png_bytes
    app,c,reel,agnes,mp=rig
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    rendered=c.post(f"/assets/{reel}/render",files={"file":("frame.png",io.BytesIO(png_bytes(1280,720)),"image/png")}).json()
    row=app.state.db.asset_get(reel)
    response=c.post("/video/static",json={"asset_id":reel,"render_id":rendered["id"],"facts_version":row["facts_version"]})
    assert response.status_code==200,response.text
    entry=response.json()
    wait_for(lambda:c.get("/jobs/"+entry["job_id"]).json()["status"] in ("completed","failed"),seconds=30)
    job=c.get("/jobs/"+entry["job_id"]).json()
    assert job["status"]=="completed",job
    saved=app.state.db.query_one("SELECT * FROM media WHERE id = ?",(entry["id"],))
    assert saved["width"]==1280 and saved["height"]==720 and agnes.created==[]
    result=subprocess.run([shutil.which("ffmpeg"),"-v","error","-i",str(app.state.settings.assets_dir/saved["file"]),"-f","framemd5","-"],capture_output=True,text=True,check=True)
    hashes=[line.rsplit(",",1)[-1].strip() for line in result.stdout.splitlines() if line and not line.startswith("#")]
    assert len(hashes)==192 and len(set(hashes))==1


def test_static_reel_rejects_absent_frame_and_stale_facts(rig):
    app,c,reel,_,mp=rig
    version=app.state.db.asset_get(reel)["facts_version"]
    body={"asset_id":reel,"render_id":"missing","facts_version":version}
    assert c.post("/video/static",json=body).status_code==409
    assert c.post("/video/static",json={**body,"facts_version":version+1}).status_code==409


def test_oversized_prompt_is_never_silently_cut():
    with pytest.raises(ValueError, match="character limit"):
        videoprompt.clean_refined({**GOOD,"prompt":GOOD["prompt"]+" Complete camera clause."*100},None)
    assert videoprompt.clean_refined(GOOD,None)["prompt"] == GOOD["prompt"]


def test_oversized_refinement_gets_one_complete_rewrite(rig):
    _,c,reel,_,mp=rig
    mp.setenv("GROQ_API_KEY","test-key")
    briefs=[]
    async def answer(brief):
        briefs.append(brief)
        return {**GOOD,"prompt":GOOD["prompt"]+" Complete camera clause."*100} if len(briefs)==1 else GOOD
    mp.setattr(videoprompt,"ask_model",answer)
    response=refine(c,reel)
    assert response.status_code==200,response.text
    assert response.json()["prompt"]==GOOD["prompt"]
    assert len(briefs)==2 and "response_limit" in briefs[1]


def test_repeated_oversized_refinement_fails_after_two_calls(rig):
    _,c,reel,_,mp=rig
    mp.setenv("GROQ_API_KEY","test-key")
    calls=[]
    async def answer(brief):
        calls.append(brief)
        return {**GOOD,"prompt":GOOD["prompt"]+" Complete camera clause."*100}
    mp.setattr(videoprompt,"ask_model",answer)
    assert refine(c,reel).status_code==502
    assert len(calls)==2


def test_a_beat_label_the_model_repeats_is_stripped():
    raw = {**GOOD, "beats": ["Recognition: The tumbler alone.", "Offer - The same tumbler.", "Action. The door behind."]}
    out = videoprompt.clean_refined(raw, None)
    assert [b["text"] for b in out["beats"]] == ["The tumbler alone.", "The same tumbler.", "The door behind."]
