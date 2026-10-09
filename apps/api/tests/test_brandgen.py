"""Brand look: the Agnes image and video prompts follow the master doc, jobs are queued and stored like media.py, the
owner's own logo upload is stored as-is, and every failure is honest. Agnes and the download are scripted."""
import json
import re

import pytest

from app import brandgen
from app.agnes import AgnesError
from b_helpers import make_client, png_bytes, wait_for

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 3000
PALETTE = {"bg": "#fff7ef", "ink": "#2b1d14", "accent": "#c4561a", "soft": "#fde3cf"}
PROFILE = {"name": "Brew Bandi", "menu": [{"name": "Filter coffee", "price": 60}]}


class BrandAgnes:
    def __init__(self, fail=False, statuses=(), queue_full=0):
        self.fail = fail
        self.statuses = list(statuses)
        self.queue_full = queue_full
        self.images = []
        self.created = []
        self.polled = []

    async def image(self, prompt, *, size="1K", ratio="4:3", references=None):
        self.images.append({"prompt": prompt, "size": size, "ratio": ratio})
        if self.fail:
            raise AgnesError("Agnes 500: boom")
        return {"data": [{"url": "https://platform-outputs.example/b.png", "b64_json": ""}], "task_id": "task_1"}

    async def video(self, prompt, *, seconds="8", aspect_ratio="9:16"):
        if self.queue_full:
            self.queue_full -= 1
            raise AgnesError('Agnes 503: {"code":"video_queue_full"}')
        self.created.append({"prompt": prompt, "seconds": seconds, "aspect_ratio": aspect_ratio})
        return {"id": "task_1", "video_id": "vid_1", "status": "queued"}

    async def video_status(self, video_id):
        self.polled.append(video_id)
        return self.statuses.pop(0) if self.statuses else {"status": "pending", "url": None}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    agnes = BrandAgnes()
    app, client = make_client(tmp_path, agnes)
    monkeypatch.setattr(brandgen, "VIDEO_POLL", 0.01)
    monkeypatch.setattr(brandgen, "VIDEO_QUEUE_WAIT", 0.01)

    async def fake_fetch(url, limit=0):
        return png_bytes(6, 8)

    monkeypatch.setattr(brandgen, "fetch_bytes", fake_fetch)
    with client:
        client.put("/business", json=PROFILE)
        yield app, client, agnes


# ---- prompts follow the master doc ----

def test_image_prompt_is_text_free_and_uses_the_real_palette(rig):
    app, _, _ = rig
    prompt = brandgen.build_image_prompt(PROFILE, style="plate", subject="filter coffee", palette=PALETTE, palette_name="Warm coffee")
    assert not re.search(r"[0-9\"'#]", prompt)
    assert "filter coffee" in prompt and "Warm coffee" in prompt
    assert "small local business" in prompt
    # Master doc: quiet type area, lettering added later, no text in the image.
    assert "type area visually quiet" in prompt and "no letters, no numbers" in prompt
    # Anti-generic audit: light chosen for the palette, not a stock recipe.
    assert "warm daylight" in prompt
    # Real palette described in words, from the actual hex values.
    assert "orange accent" in prompt and "deep orange text" in prompt and "pale orange background" in prompt


def test_colour_words_describe_real_hex_values():
    assert brandgen.colour_words("#c4561a") == "rich orange"
    assert brandgen.colour_words("#2b1d14") == "deep orange"
    assert brandgen.colour_words("#f4fbf2") == "pale green"
    assert brandgen.colour_words("") == "" and brandgen.colour_words("nope") == ""


def test_video_prompt_locks_the_camera_and_stays_silent(rig):
    app, _, _ = rig
    prompt = brandgen.build_video_prompt(PROFILE, aspect="16:9", subject="filter coffee", palette=PALETTE, palette_name="Warm coffee")
    assert not re.search(r'[0-9#"]', prompt)
    for phrase in ("Subject and setting", "Reference mapping", "Action and timing", "Camera", "Visual style", "Sound and rhythm", "Consistency"):
        assert phrase in prompt
    # User requirement: landscape, no camera move of any kind, motion only as explicitly authorized.
    assert "landscape frame" in prompt and "No camera movement, no zoom, no pan, no parallax, no Ken Burns" in prompt
    assert "one approved beat only" in prompt
    assert "silent clip" in prompt and "no letters, no numbers" in prompt


def test_no_configured_key_is_reported_honestly(tmp_path):
    app, client = make_client(tmp_path, key=None)
    with client:
        body = client.get("/brandgen").json()
        assert body["configured"] is False and body["image"] is None and body["video"] is None
        assert "not configured" in body["note"]
        assert client.post("/brandgen/image", json={"subject": "coffee"}).json()["detail"]["code"] == "agnes_not_configured"


# ---- image: generate ----

def test_generated_brand_look_is_stored_and_served(rig):
    app, client, agnes = rig
    created = client.post("/brandgen/image", json={"style": "plate", "subject": "filter coffee", "palette": PALETTE, "palette_name": "Warm coffee"})
    assert created.status_code == 200
    body = created.json()
    assert body["kind"] == "image" and body["source"] == "generated" and body["ratio"] == "16:9"
    wait_for(lambda: client.get(f"/jobs/{body['job_id']}").json()["status"] == "completed")
    got = client.get("/brandgen").json()
    assert got["image"]["status"] == "ready" and got["image"]["url"].startswith("/media/") and got["image"]["width"] == 6
    assert agnes.images[0]["ratio"] == "16:9" and agnes.images[0]["size"] == "1K"
    served = client.get(got["image"]["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.content == png_bytes(6, 8)


def test_mark_style_uses_a_square_ratio(rig):
    app, client, agnes = rig
    body = client.post("/brandgen/image", json={"style": "mark", "subject": "coffee", "palette": PALETTE}).json()
    assert body["ratio"] == "1:1"
    wait_for(lambda: client.get(f"/jobs/{body['job_id']}").json()["status"] == "completed")
    assert agnes.images[0]["ratio"] == "1:1"


def test_request_while_a_generation_is_open_returns_that_entry(rig):
    app, client, agnes = rig
    app.state.db.execute(
        "INSERT INTO brandgen (id, owner, kind, source, ratio, status, created_at) VALUES ('open1', 'local', 'image', 'generated', '16:9', 'generating', 't')"
    )
    assert client.post("/brandgen/image", json={"subject": "coffee"}).json()["id"] == "open1"
    assert agnes.images == []


def test_failed_generation_is_recorded(tmp_path, monkeypatch):
    agnes = BrandAgnes(fail=True)
    app, client = make_client(tmp_path, agnes)
    with client:
        client.put("/business", json=PROFILE)
        body = client.post("/brandgen/image", json={"subject": "coffee"}).json()
        wait_for(lambda: client.get(f"/jobs/{body['job_id']}").json()["status"] == "failed")
        row = app.state.db.query_one("SELECT * FROM brandgen WHERE id = ?", (body["id"],))
        assert row["status"] == "failed" and "boom" in row["detail"] and row["file"] is None


def test_no_subject_is_refused(rig):
    app, client, _ = rig
    app.state.db.execute("DELETE FROM business")
    resp = client.post("/brandgen/image", json={})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "no_subject"


# ---- image: the owner's own upload ----

def test_owner_can_upload_their_own_logo(rig):
    app, client, _ = rig
    resp = client.post("/brandgen/image/upload", files={"file": ("logo.png", png_bytes(4, 5), "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "image" and body["source"] == "upload" and body["status"] == "ready" and body["width"] == 4
    got = client.get("/brandgen").json()
    assert got["image"]["id"] == body["id"] and got["upload"]["id"] == body["id"]
    assert client.get(body["url"]).content == png_bytes(4, 5)


def test_upload_refuses_non_images_and_oversized_files(rig):
    app, client, _ = rig
    assert client.post("/brandgen/image/upload", files={"file": ("a.txt", b"not an image", "image/png")}).status_code == 415
    big = png_bytes() + b"\x00" * (brandgen.MAX_LOGO_BYTES + 10)
    assert client.post("/brandgen/image/upload", files={"file": ("b.png", big, "image/png")}).status_code == 413


# ---- video ----

def test_video_needs_explicit_motion_permission(rig):
    app, client, agnes = rig
    assert client.post("/brandgen/video", json={}).json()["detail"]["code"] == "motion_not_opted_in"
    assert client.post("/brandgen/video", json={"motion_opt_in": False}).status_code == 409
    assert client.post("/brandgen/video", json={"motion_opt_in": True, "aspect": "1:1"}).status_code == 422
    assert agnes.created == [] and app.state.db.query("SELECT * FROM brandgen WHERE kind = 'video'") == []


def test_brand_video_polls_downloads_and_serves(tmp_path, monkeypatch):
    agnes = BrandAgnes(statuses=[{"status": "pending"}, {"status": "processing"}, {"status": "completed", "url": "https://cdn.example/v.mp4"}])
    app, client = make_client(tmp_path, agnes)
    monkeypatch.setattr(brandgen, "VIDEO_POLL", 0.01)

    async def fake_fetch(url, limit=0):
        return MP4

    monkeypatch.setattr(brandgen, "fetch_bytes", fake_fetch)
    with client:
        client.put("/business", json=PROFILE)
        body = client.post("/brandgen/video", json={"motion_opt_in": True, "aspect": "16:9"}).json()
        assert body["kind"] == "video" and body["ratio"] == "16:9" and body["status"] in ("queued", "generating")
        wait_for(lambda: client.get(f"/jobs/{body['job_id']}").json()["status"] == "completed")
        assert agnes.polled == ["vid_1"] * 3
        created = agnes.created[0]
        assert created["seconds"] == "8" and created["aspect_ratio"] == "16:9" and "No camera movement" in created["prompt"]
        assert not re.search(r"[0-9]", created["prompt"])
        got = client.get("/brandgen").json()["video"]
        assert got["status"] == "ready" and got["url"].endswith(".mp4")
        served = client.get(got["url"])
        assert served.status_code == 200 and served.headers["content-type"] == "video/mp4" and served.content == MP4
        row = app.state.db.query_one("SELECT * FROM brandgen WHERE id = ?", (body["id"],))
        assert row["video_id"] == "vid_1" and row["model"] == "agnes-video-2.5-flash"


def test_video_queue_full_is_retried(tmp_path, monkeypatch):
    agnes = BrandAgnes(statuses=[{"status": "completed", "url": "https://cdn.example/v.mp4"}], queue_full=2)
    app, client = make_client(tmp_path, agnes)
    monkeypatch.setattr(brandgen, "VIDEO_POLL", 0.01)
    monkeypatch.setattr(brandgen, "VIDEO_QUEUE_WAIT", 0.01)

    async def fake_fetch(url, limit=0):
        return MP4

    monkeypatch.setattr(brandgen, "fetch_bytes", fake_fetch)
    with client:
        client.put("/business", json=PROFILE)
        body = client.post("/brandgen/video", json={"motion_opt_in": True, "aspect": "9:16"}).json()
        wait_for(lambda: client.get(f"/jobs/{body['job_id']}").json()["status"] == "completed")
        assert agnes.created[0]["aspect_ratio"] == "9:16" and body["ratio"] == "9:16"


def test_video_never_ready_without_a_real_file(tmp_path, monkeypatch):
    agnes = BrandAgnes(statuses=[{"status": "completed", "url": "https://cdn.example/v.mp4"}])
    app, client = make_client(tmp_path, agnes)

    async def empty_fetch(url, limit=0):
        return b""

    monkeypatch.setattr(brandgen, "fetch_bytes", empty_fetch)
    with client:
        client.put("/business", json=PROFILE)
        body = client.post("/brandgen/video", json={"motion_opt_in": True}).json()
        wait_for(lambda: client.get(f"/jobs/{body['job_id']}").json()["status"] == "failed")
        assert app.state.db.query_one("SELECT status, file FROM brandgen WHERE id = ?", (body["id"],)) == {"status": "failed", "file": None}


def test_video_shared_daily_budget(rig):
    app, client, _ = rig
    for i in range(63):
        app.state.db.execute(
            "INSERT INTO media (id, asset_id, campaign_id, kind, ratio, status, created_at) VALUES (?, 'x', 'x', 'video', '16:9', 'ready', ?)",
            (f"m{i}", brandgen.now()),
        )
    resp = client.post("/brandgen/video", json={"motion_opt_in": True})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "video_budget_exhausted"
