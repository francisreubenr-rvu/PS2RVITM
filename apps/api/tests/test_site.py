"""Website generation: the Groq Qwen writer turns the owner's real brand, approved offer and languages into one page's content
and structure, and code renders the standalone HTML. No network; the provider is faked.

These tests pin the one model (qwen, GROQ_CHAT_MODEL as the override), the honest not-configured answer when Groq is off or
unkeyed, the strict shaping of the reply (unknown section kinds dropped, the design tables' order enforced), the design rules
the prompt encodes, and that every number on the page comes from the owner's saved data, never from the model.
"""
import json

import httpx
import pytest

from app import brain, site
from b_helpers import make_client, seed

PROFILE = {"name": "Brew Bandi", "phone": "98450 12345", "address": "12 Church St, Bengaluru", "maps_url": "https://maps.example/x",
           "hours": "8am to 9pm", "about": {"en": "A small cafe."}, "tagline": {"en": "Coffee, your way"},
           "menu": [{"name": "Filter coffee", "price": 60}, {"name": "Masala dosa", "price": 90.5}], "langs": ["en", "kn"]}

GOOD = {
    "style": "steve-jobs",
    "idea": "A neighbourhood cafe site for regulars in Bengaluru.",
    "palette": {"background": "#fff8f0", "surface": "#f7e6d5", "text": "#241a12", "muted": "#6d5c4d", "accent": "#b3491b"},
    "fonts": "warm-serif",
    "sections": [
        {"kind": "hero", "eyebrow": "Brew Bandi", "heading": "Filter coffee, poured the way you like it",
         "subhead": "A small cafe on Church Street.", "action": "Order on WhatsApp"},
        {"kind": "offer", "heading": "This week", "note": "Our current offer, straight from the counter."},
        {"kind": "menu", "heading": "What we serve", "note": "Fresh through the day."},
        {"kind": "about", "heading": "Our little cafe", "body": "We roast in small batches."},
        {"kind": "hours", "heading": "When to find us", "note": "Drop in, or order ahead."},
        {"kind": "cta", "heading": "See you soon", "body": "Send us a message and we will keep it ready.", "action": "Order on WhatsApp"},
    ],
}


class Fake:
    """A stand-in for httpx.AsyncClient: records what was sent and answers with a canned Response."""

    calls: list = []
    reply = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aclose(self):
        return None

    async def post(self, url, **kw):
        Fake.calls.append((url, kw))
        return Fake.reply(url, kw) if callable(Fake.reply) else Fake.reply


def groq_reply(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    Fake.calls, Fake.reply = [], groq_reply(GOOD)
    monkeypatch.setattr(site.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    seed(c, app)  # an approved offer: filter coffee, 20% off, Sunday only
    c.put("/business", json=PROFILE)
    return app, c, monkeypatch


def ask(c, **body):
    return c.post("/site/generate", json={"lang": "en", **body})


def test_no_key_is_503_and_the_brief_never_leaves(rig):
    _, c, _ = rig
    r = ask(c)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "brain_not_configured"
    assert Fake.calls == []


def test_the_settings_switch_is_respected(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    c.put("/settings/toggles/openrouter", json={"enabled": False})
    assert ask(c).status_code == 503
    assert Fake.calls == []


def test_the_writer_gets_one_model_and_the_design_rules(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    ask(c)
    sent = Fake.calls[-1][1]["json"]
    assert sent["model"] == brain.TEXT_MODEL == "z-ai/glm-5.3-flash" and "gpt-oss" not in sent["model"]
    assert sent["response_format"] == {"type": "json_object"}
    system = sent["messages"][0]["content"]
    for rule in ("Section order, exactly", "one primary action", "unmistakable heading", "accent", "pairing",
                 "No parallax, no scroll animation", "Never invent a price", "colour for its meaning"):
        assert rule in system, rule
    assert "12-column" not in system  # layout is enforced by the renderer, not asked of the model


def test_the_writer_is_told_only_the_owner_s_real_details(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    ask(c)
    user = json.loads(Fake.calls[-1][1]["json"]["messages"][1]["content"])
    assert user["language"] == "English" and user["language_code"] == "en"
    assert user["brand"]["name"] == "Brew Bandi" and "Filter coffee" in user["brand"]["menu"]
    assert user["approved_offer"]["item"] == "filter coffee" and user["approved_offer"]["discount_percent"] == 20
    assert user["sections_available"] == ["hero", "offer", "menu", "about", "hours", "cta"]


def test_a_missing_section_is_not_offered_to_the_writer(tmp_path, monkeypatch):
    Fake.calls, Fake.reply = [], groq_reply(GOOD)
    monkeypatch.setattr(site.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    c.put("/business", json={"name": "Bare Shop"})  # no offer, no menu, no hours
    monkeypatch.setenv("OPENROUTER_API_KEY", "gk")
    assert ask(c).status_code == 200
    user = json.loads(Fake.calls[-1][1]["json"]["messages"][1]["content"])
    assert user["sections_available"] == ["hero", "cta"] and user["approved_offer"] is None


def test_the_page_uses_real_data_and_one_action(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    out = ask(c).json()
    page = out["html"]
    assert out["model"] == "z-ai/glm-5.3-flash" and out["site"]["style"] == "steve-jobs"
    assert out["site"]["sections"] == ["hero", "offer", "menu", "about", "hours", "cta"]
    assert out["site"]["fonts"]["heading"] == "Fraunces"
    # every fact on the page is the owner's: the approved offer, the menu prices, the address, one wa.me link per action
    for fact in ("20% off filter coffee", "₹80", "Sunday only", "Filter coffee", "₹60", "Masala dosa", "₹90.50",
                 "12 Church St, Bengaluru", "8am to 9pm"):
        assert fact in page, fact
    assert page.count("wa.me/919845012345") == 3  # header + hero + closing row, all the same one action
    assert page.count("<h1") == 1 and page.count("<h2") == 5
    assert 'lang="en"' in page and "Fraunces" in page and "#b3491b" in page
    assert out["warnings"] == [] and "not true of your shop" in out["disclaimer"]


def test_no_proof_is_ever_rendered(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    # the model tries to add proof sections and a proof claim; both are refused
    reply = dict(GOOD, sections=GOOD["sections"] + [
        {"kind": "testimonials", "heading": "Loved by 500 customers", "body": "Rated 5 stars."},
        {"kind": "proof", "heading": "Award winning", "body": "Best cafe 2025."},
    ])
    Fake.reply = groq_reply(reply)
    page = ask(c).json()["html"]
    assert "500 customers" not in page and "5 stars" not in page and "Award" not in page
    assert ask(c).json()["site"]["sections"] == ["hero", "offer", "menu", "about", "hours", "cta"]


def test_the_design_tables_shape_is_enforced(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    # sections returned out of order, an invented kind, and a duplicate: all are re-ordered, dropped and de-duplicated
    reply = dict(GOOD, style="not-a-style", fonts="comic-sans", sections=[
        {"kind": "menu", "heading": "Menu"},
        {"kind": "signup_form", "heading": "Join"},
        {"kind": "hero", "heading": "A real headline", "action": "Order on WhatsApp"},
        {"kind": "hero", "heading": "A second hero"},
        {"kind": "cta", "heading": "Bye", "action": "Order on WhatsApp"},
    ])
    Fake.reply = groq_reply(reply)
    out = ask(c).json()
    assert out["site"]["sections"] == ["hero", "menu", "cta"]  # required order, no invented kind, no duplicate hero
    assert out["site"]["style"] == "steve-jobs" and out["site"]["fonts"]["heading"] == "Fraunces"
    assert "A second hero" not in out["html"] and "Join" not in out["html"]


def test_a_page_without_a_hero_is_a_bad_reply(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    Fake.reply = groq_reply(dict(GOOD, sections=[{"kind": "about", "heading": "About"}]))
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "website_failed"


def test_a_bad_reply_is_502(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    Fake.reply = groq_reply("just words, no json")
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "website_failed"


def test_a_provider_failure_is_reported(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    Fake.reply = httpx.Response(429, json={})
    r = ask(c)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "website_failed"


def test_an_unknown_language_is_422(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    assert ask(c, lang="xx").status_code == 422
    assert Fake.calls == []


def test_no_phone_means_no_button_and_a_warning(tmp_path, monkeypatch):
    Fake.calls, Fake.reply = [], groq_reply(GOOD)
    monkeypatch.setattr(site.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    seed(c, app)
    c.put("/business", json={"name": "Brew Bandi", "about": {"en": "A small cafe."}})
    monkeypatch.setenv("OPENROUTER_API_KEY", "gk")
    out = ask(c).json()
    assert "wa.me" not in out["html"] and 'class="btn' not in out["html"]
    assert any("WhatsApp number" in w for w in out["warnings"])


def test_brand_colours_win_over_the_model(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    c.put("/business", json={"palette": {"bg": "#101820", "ink": "#f5f5f5", "accent": "#ffb703", "soft": "#1b2733"}})
    out = ask(c).json()
    assert out["site"]["palette"]["background"] == "#101820" and out["site"]["palette"]["accent"] == "#ffb703"
    assert "#101820" in out["html"] and "--accent:#ffb703" in out["html"]


def test_everything_the_owner_typed_is_escaped(tmp_path, monkeypatch):
    Fake.calls, Fake.reply = [], groq_reply(dict(GOOD, sections=[
        {"kind": "hero", "heading": "<script>alert(1)</script>", "action": '"><b>x</b>'},
        {"kind": "menu", "heading": "Menu & more"},
    ]))
    monkeypatch.setattr(site.httpx, "AsyncClient", Fake)
    app, c = make_client(tmp_path)
    c.put("/business", json={"name": "<img src=x onerror=alert(1)>", "menu": [{"name": "\"><i>y", "price": 5}]})
    monkeypatch.setenv("OPENROUTER_API_KEY", "gk")
    page = ask(c).json()["html"]
    assert "<script>" not in page and "<img" not in page and "<b>x" not in page and "<i>y" not in page
    assert "&lt;script&gt;" in page and "Menu &amp; more" in page


def test_kannada_gets_its_script_face(rig):
    _, c, mp = rig
    mp.setenv("OPENROUTER_API_KEY", "gk")
    page = ask(c, lang="kn").json()["html"]
    assert 'lang="kn"' in page and "Noto+Sans+Kannada" in page


def test_low_contrast_colours_fall_back_to_a_readable_pair():
    bad = site.clean_palette({"background": "#f2f2f2", "surface": "#eeeeee", "text": "#efefef", "muted": "#f0f0f0", "accent": "#dddddd"})
    assert bad == site.DEFAULT_PALETTE
    assert site.contrast(bad["text"], bad["background"]) >= 4.5
    assert site.clean_palette({"background": "not-a-colour", "accent": "red"}) == site.DEFAULT_PALETTE


def test_contrast_is_a_real_ratio():
    assert site.contrast("#000000", "#ffffff") == 21
    assert site.contrast("#777777", "#ffffff") < 4.5


@pytest.mark.parametrize("raw,ok", [
    (GOOD, True),
    ({"idea": "x", "sections": [{"kind": "hero", "heading": "H"}]}, True),
    ('{"idea": "x"}', False),  # not an object
    ({"sections": [{"kind": "hero", "heading": "H"}]}, False),  # no idea
    ({"idea": "x"}, False),  # no hero
    ({"idea": "x", "sections": "nope"}, False),
])
def test_the_strict_shaper(raw, ok):
    value = json.loads(raw) if isinstance(raw, str) else raw
    if ok:
        out = site.clean_site(value)
        assert set(out) == {"idea", "style", "fonts", "palette", "sections"} and out["sections"][0]["kind"] == "hero"
    else:
        with pytest.raises(Exception):
            site.clean_site(value)


def test_sections_are_trimmed_and_bounded():
    out = site.clean_sections([{"kind": "hero", "heading": "  A   headline  ", "invented": "x", "body": "y" * 400},
                               {"kind": "nope", "heading": "z"}, "junk", {"kind": "cta", "action": "Order"}])
    assert [s["kind"] for s in out] == ["hero", "cta"]
    assert out[0]["heading"] == "A headline" and "invented" not in out[0] and len(out[0]["body"]) == 240
    with pytest.raises(Exception):  # no hero at all is a bad reply, never a page without its first screen
        site.clean_sections([{"kind": "cta", "heading": "Bye"}])
