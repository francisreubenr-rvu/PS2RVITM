"""site: the one-page website, generated through the OpenRouter GLM planner. One model only (z-ai/glm-5.3-flash, no model fallback). When OpenRouter is switched off in Settings or has no key, the route answers 503 "not configured" and the screen says
so, rather than showing a page that was never generated.

The model writes the site's CONTENT and STRUCTURE: the section order, the headings and sentences, the one primary action's
label, the colour tokens and the type pairing. It never invents a price, a number, a review, a logo or a claim. The owner's
brand, approved offer, menu, hours and number are the only sources for facts, and the renderer inserts them verbatim, escaped.

The design rules the generated page must follow come from the workspace design tables in guides/playbooks/ and guides/RULES.md.
The rules actually encoded, and where they are enforced:

  section order and one idea per row   landing-page.md (5-8); content-structure.md (8); layout-composition.md (3, 13)  -> SECTION_ORDER + prompt
  content before layout, real copy     content-structure.md (10); RULES.md Content and IA (6)                        -> all copy is model-written or real data
  one unmistakable first-read element  hierarchy-attention.md (1, 3); RULES.md Hierarchy (1)                          -> every section leads with one heading
  headline is the biggest, boldest     hero.md (6, 7)                                                                 -> h1 takes the top type tier
  one primary action, no competing     landing-page.md (8); RULES.md Content and IA (9); hero.md (9)                  -> one action, repeated only as the closing row
  CTA label states what happens        RULES.md Interaction and states (2); psychology-ux.md (9)                     -> labelled "Order on WhatsApp" etc.
  big / medium / small per row         layout-composition.md (8); RULES.md Layout and grid (1)                      -> type scale tiers
  12-column grid, fixed container      layout-composition.md (6); RULES.md Layout and grid (2, 3)                      -> .grid + .wrap
  no two adjacent rows share a bg      layout-composition.md (10); RULES.md Layout and grid (6)                       -> alternating .tint
  colour: 3-5 roles, one accent         color-system.md (5, 7, 8); RULES.md Colour (3, 4, 10)                          -> five named roles, accent only on the CTA
  brand colours win when they exist     color-system.md (1); RULES.md Colour (1)                                        -> profile palette overrides the model's
  contrast is checked                  color-system.md (9); RULES.md Colour (9)                                        -> contrast() falls back to a readable pair
  type: two fonts, legible body         typography-system.md (1, 4, 5); RULES.md Typography (1, 3)                      -> approved pairings, body font for body
  H1 once per page, H2 below            typography-system.md (10)                                                       -> one h1, h2 per section
  scale the whole hierarchy on mobile  typography-system.md (11, 12); RULES.md Layout and grid (10)                   -> clamp() on every tier
  hover and focus states               motion-scroll.md (5, 6); RULES.md Interaction and states (6)                     -> :hover and :focus-visible styled
  motion is micro-interaction only     motion-scroll.md (1, 2, 3, 9); RULES.md Motion (1, 3, 4)                        -> transitions on hover only, no scroll effects
  never fabricate proof                psychology-ux.md (5); RULES.md / ROUTER anti-generic checklist (last item)      -> no proof section is ever emitted
"""
from __future__ import annotations

import html
import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import TEXT_PROVIDER, TEXT_URL, text_api_key, text_request
from app import brain, business, extras, languages
from app.db import Database
from app.media import fail
from app.worker import parse_json_object

router = APIRouter()


def ensure_schema(db: Database) -> None:
    """Nothing to create: a generated page is not stored, it is returned for preview and download."""


# The six styles of guides/playbooks/style-selection.md (C05), a closed taxonomy. The model picks one; the default is the
# lowest-risk, broadly legible one. The style steers the copy's tone and the type pairing.
STYLES = ("steve-jobs", "jensen-huang", "drew-barrymore", "zendaya", "virgil-abloh", "christopher-nolan")
DEFAULT_STYLE = "steve-jobs"

# Approved type pairings (typography-system.md 1, 4, 5: one heading font, one plain body font, capped at two). Kept as a
# closed set so no unusable font name reaches the page and the Google Fonts link is always real.
PAIRINGS = {
    "warm-serif": {"heading": "Fraunces", "body": "Inter", "mood": "a warm editorial serif over a clean grotesque; cafes, bakeries, food, craft"},
    "clean-sans": {"heading": "Poppins", "body": "Inter", "mood": "a round geometric sans over a neutral body; salons, gyms, clinics, services"},
    "editorial": {"heading": "Playfair Display", "body": "Source Sans 3", "mood": "a high-contrast display serif over a quiet humanist body; boutiques, fashion, premium"},
    "friendly": {"heading": "DM Serif Display", "body": "DM Sans", "mood": "a soft, friendly serif over a modern sans; approachable local shops"},
}
DEFAULT_PAIRING = "warm-serif"

# The sections of a one-page marketing site, in the order the tables require (hero first, the offer, what is served, the
# story, hours and place, a closing action). One idea per row; the highest-priority content sits first. A section is only
# rendered when the owner's real data backs it, so nothing is fabricated.
SECTION_ORDER = ("hero", "offer", "menu", "about", "hours", "cta")
KINDS = set(SECTION_ORDER)

# The five colour roles (color-system.md 5, 8: one dominant, one or two neutrals, one accent reserved for the CTA).
COLOUR_ROLES = ("background", "surface", "text", "muted", "accent")
DEFAULT_PALETTE = {"background": "#fff7ef", "surface": "#fde3cf", "text": "#2b1d14", "muted": "#6f5c4f", "accent": "#b3491b"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

NOTO = {"kn": "Noto Sans Kannada", "hi": "Noto Sans Devanagari", "mr": "Noto Sans Devanagari", "bn": "Noto Sans Bengali",
        "gu": "Noto Sans Gujarati", "pa": "Noto Sans Gurmukhi", "ta": "Noto Sans Tamil", "te": "Noto Sans Telugu", "ml": "Noto Sans Malayalam"}

SITE_SHAPE = {
    "style": "|".join(STYLES),
    "idea": "<one sentence: what this site is, and who it is for>",
    "palette": {role: "<#rrggbb>" for role in COLOUR_ROLES},
    "fonts": "|".join(PAIRINGS),
    "sections": [
        {"kind": "hero", "eyebrow": "<the business name as the small word above the headline, or empty>",
         "heading": "<the one-line promise: what the business does and why it matters>", "subhead": "<one plain sentence of context>",
         "action": "<button label that states exactly what happens, e.g. Order on WhatsApp>"},
        {"kind": "offer", "heading": "<short heading for the current offer>", "note": "<one sentence framing the offer, no numbers>"},
        {"kind": "menu", "heading": "<short heading for what is served>", "note": "<one sentence, no prices>"},
        {"kind": "about", "heading": "<short heading>", "body": "<two or three plain sentences about the business>"},
        {"kind": "hours", "heading": "<short heading for hours and place>", "note": "<one sentence, no times or address>"},
        {"kind": "cta", "heading": "<a closing line>", "body": "<one sentence>", "action": "<same action as the hero>"},
    ],
}

SYSTEM_PROMPT = (
    "You are GrowIt's website writer for a small shop owner in India. You write the content and structure of one "
    "one-page website from the owner's own brand, approved offer and languages. You invent nothing.\n"
    "THE RULES YOU MUST FOLLOW (the site is rejected if it breaks them):\n"
    "1. Section order, exactly: hero first, then offer, then menu (what is served), then about, then hours and place, "
    "then one closing action. One idea per section, never two. The most important content is in the hero, in the first "
    "screen (landing-page 5-8, content-structure 8, layout 13).\n"
    "2. Every section leads with one unmistakable heading; nothing competes with it. The hero heading is the single "
    "biggest, boldest line on the page (hierarchy 1, hero 6).\n"
    "3. Exactly one primary action for the whole page. Repeat the same action only as the closing row. Never offer a "
    "second, competing action (landing-page 8, content and IA 9).\n"
    "4. The action label states plainly what happens on click, in the site's language (e.g. 'Order on WhatsApp', "
    "'Call us'). Never a vague label like 'Learn more' or 'Submit' (interaction states 2, psychology 9).\n"
    "5. Write the hero heading to do two jobs at once: say what the business does and why it matters (hero 6).\n"
    "6. Colour: return exactly five roles as #rrggbb. background (dominant), surface (a light neutral for alternating "
    "sections), text (dark, readable on background), muted (a softer tone of text), accent (one colour, reserved for the "
    "primary action only). Three to five colours, one accent. Choose the base colour for its meaning and fit to the "
    "audience, not your taste (color-system 2, 3, 5, 8).\n"
    "7. Type: pick one approved pairing id. Two fonts only: one heading, one plain legible body (typography 1, 4, 5).\n"
    "8. Motion: none beyond hover and focus changes on links and the button. No parallax, no scroll animation, no reveal "
    "effects, no moving backgrounds (motion 1, 2, 3, 9).\n"
    "9. Never invent a price, discount, date, number, review, testimonial, award, logo, or any claim the owner did not "
    "state. The offer, menu, hours, address and number are inserted by the app from the owner's saved data; do not "
    "restate their numbers, do not add a section that pretends to be proof (psychology 5).\n"
    "10. Write in the requested language natively. Do not translate an English draft. Keep it plain, warm and concrete, "
    "with everyday words a local customer uses.\n"
    "11. Choose one style from the closed list and let it set the tone: steve-jobs (clean, calm, generous space), "
    "jensen-huang (buttoned-up, functional), drew-barrymore (warm, approachable), zendaya (high-fashion, minimal), "
    "virgil-abloh (one unmissable element), christopher-nolan (bold). When unsure, choose steve-jobs.\n"
    "Return exactly one JSON object and nothing else: no prose, no code fences. It matches this shape exactly: "
    + json.dumps(SITE_SHAPE)
)

DISCLAIMER = "Generated by an AI from your own details. Read it before you publish, and fix anything that is not true of your shop."


class GenerateIn(BaseModel):
    lang: str = Field(default="en", max_length=5)
    instruction: str = Field(default="", max_length=300)


# ---------------------------------------------------------------- the model call

async def _qwen(system: str, user: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """One call to the OpenRouter GLM planner. Raises a clear 503 when OpenRouter is off or unkeyed, 502 when it fails or answers junk."""
    key = text_api_key()
    if not key:
        raise fail("brain_not_configured", "The OpenRouter planner has no key on the server. Add one to switch it on.", 503)
    payload = {"model": brain.TEXT_MODEL,  # one fixed model, no model fallback
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
               "temperature": 0.6, "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(brain.TEXT_URL, headers={"Authorization": f"Bearer {key}"}, json=text_request(payload))
    except httpx.HTTPError as exc:
        raise fail("website_failed", f"The website writer did not answer just now ({type(exc).__name__}). Try again.", 502) from exc
    if response.status_code >= 400:
        raise fail("website_failed", f"The website writer said {response.status_code}. Try again in a moment.", 502)
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise fail("website_failed", "The website writer's answer could not be read. Try again.", 502) from exc
    try:
        return parse_json_object(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise fail("website_failed", "The website writer's answer was not usable. Try again.", 502) from exc


# ---------------------------------------------------------------- shaping (strict, bounded)

def _s(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def _luminance(colour: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """A relative-luminance legibility ratio for two #rrggbb colours (color-system 9: check every pairing)."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def clean_palette(raw: Any) -> dict[str, str]:
    """Five named roles, each a real #rrggbb. Missing or malformed roles fall back to the default role. If text on the
    background is not clearly readable, the whole default set is used instead (color-system 9)."""
    src = raw if isinstance(raw, dict) else {}
    palette = {role: (src.get(role) if isinstance(src.get(role), str) and HEX.match(src.get(role)) else DEFAULT_PALETTE[role]) for role in COLOUR_ROLES}
    if contrast(palette["text"], palette["background"]) < 4.5 or contrast(palette["muted"], palette["background"]) < 3:
        return dict(DEFAULT_PALETTE)
    return palette


def clean_sections(raw: Any) -> list[dict[str, Any]]:
    """Keep only real section kinds, in the required order, hero first. Trims every string. Drops anything invented."""
    kept: dict[str, dict[str, Any]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in KINDS or kind in kept:
            continue
        row: dict[str, Any] = {"kind": kind}
        for field in ("eyebrow", "heading", "subhead", "note", "body", "action"):
            value = _s(item.get(field), 240 if field in ("body", "subhead") else 120)
            if value:
                row[field] = value
        if kind == "hero" and not row.get("heading"):
            continue  # a hero with no headline is unusable
        kept[kind] = row
    ordered = [kept[k] for k in SECTION_ORDER if k in kept]
    if not ordered or ordered[0]["kind"] != "hero":
        raise fail("website_failed", "The writer's page had no hero. Try again.", 502)
    return ordered


def clean_site(raw: Any) -> dict[str, Any]:
    """Shape the model's reply into the site object. Junk (not an object, no idea, no hero) is a bad reply."""
    if not isinstance(raw, dict):
        raise fail("website_failed", "The writer's answer was not usable. Try again.", 502)
    idea = _s(raw.get("idea"), 200)
    if not idea:
        raise fail("website_failed", "The writer's page had no idea. Try again.", 502)
    style = raw.get("style") if raw.get("style") in STYLES else DEFAULT_STYLE
    fonts = raw.get("fonts") if raw.get("fonts") in PAIRINGS else DEFAULT_PAIRING
    return {"idea": idea, "style": style, "fonts": fonts, "palette": clean_palette(raw.get("palette")), "sections": clean_sections(raw.get("sections"))}


# ---------------------------------------------------------------- the page

def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _money(value: float) -> str:
    return f"₹{value:,.0f}" if float(value).is_integer() else f"₹{value:,.2f}"


def _fonts(site: dict[str, Any], lang: str) -> list[str]:
    """The families to load for the page, plus the script face when the language needs one. Real Google Fonts names only."""
    pair = PAIRINGS[site["fonts"]]
    families = [pair["heading"], pair["body"]]
    noto = NOTO.get(lang)
    if noto and noto not in families:
        families.append(noto)
    return families


def _font_link(families: list[str]) -> str:
    query = "&".join(f"family={f.replace(' ', '+')}:wght@400;600;700" for f in families)
    return f"https://fonts.googleapis.com/css2?{query}&display=swap"


def render_page(site: dict[str, Any], profile: dict[str, Any], facts: dict[str, Any] | None, lang: str) -> tuple[str, list[str]]:
    """Render the shaped site to one standalone HTML document. Pure: the same inputs give the same page.
    Prices, menu, hours and contact come from the owner's profile and approved facts, never from the model."""
    palette = site["palette"]
    families = _fonts(site, lang)
    heading_font = f"'{PAIRINGS[site['fonts']]['heading']}', system-ui, sans-serif"
    body_font = f"'{PAIRINGS[site['fonts']]['body']}', system-ui, sans-serif"
    name = _s(profile.get("name"), 80) or "Our shop"
    phone = profile.get("phone") or ""
    about = (profile.get("about") or {}).get(lang) or (profile.get("about") or {}).get("en") or ""
    menu = [it for it in (profile.get("menu") or []) if isinstance(it, dict) and _s(it.get("name"), 60) and isinstance(it.get("price"), (int, float)) and not isinstance(it.get("price"), bool) and it["price"] > 0]
    warnings: list[str] = []
    if not phone:
        warnings.append("No WhatsApp number is saved, so the page has no order button. Add it under Brand & Data.")
    if not facts:
        warnings.append("No approved offer yet, so the offer section is left out. Approve the facts on a campaign first.")
    if not menu:
        warnings.append("The menu is empty, so the menu section is left out.")

    hello = f"Hi {name}, I'd like to order" if lang == "en" else f"Hi {name}"

    def action(section: dict[str, Any]) -> str:
        """The one primary action, as a real button linked to WhatsApp. Only ever labelled from the model, and only shown
        when there is a number to reach (interaction states 3: never style non-working text as a button)."""
        if not phone or not section.get("action"):
            return ""
        return f'<a class="btn" href="{_e(business.order_link(phone, hello))}" rel="noopener">{_e(section["action"])}</a>'

    rows: list[tuple[str, str]] = []  # (kind, inner html) in order; background alternation is applied after

    def heading(section: dict[str, Any]) -> str:
        return _e(section.get("heading") or site["idea"])

    for section in site["sections"]:
        kind = section["kind"]
        if kind == "hero":
            lines = ['<div class="col">']
            if section.get("eyebrow"):
                lines.append(f'<p class="eyebrow">{_e(section["eyebrow"])}</p>')
            lines.append(f"<h1>{heading(section)}</h1>")
            if section.get("subhead"):
                lines.append(f'<p class="lead">{_e(section["subhead"])}</p>')
            button = action(section)
            if button:
                lines.append(f'<p class="cta-row">{button}</p>')
            lines.append("</div>")
            rows.append((kind, "".join(lines)))
        elif kind == "offer":
            if not facts:
                continue
            bits = []
            item = _s(facts.get("item"), 120)
            line = f"{facts['discount_percent']:g}% off {item}".strip() if facts.get("discount_percent") else item
            bits.append(f'<p class="offer-line">{_e(line)}</p>')
            if facts.get("price_amount"):
                bits.append(f'<p class="offer-price">{_money(facts["price_amount"])}</p>')
            when = ", ".join(x for x in [", ".join(facts.get("dates") or []), facts.get("timings") or ""] if x)
            if when:
                bits.append(f'<p class="muted">{_e(when)}</p>')
            if facts.get("terms"):
                bits.append(f'<p class="small">{_e(facts["terms"])}</p>')
            note = f'<p class="muted">{_e(section["note"])}</p>' if section.get("note") else ""
            rows.append((kind, f'<div class="col"><h2>{heading(section)}</h2>{note}{"".join(bits)}</div>'))
        elif kind == "menu":
            if not menu:
                continue
            items = "".join(f'<li><span class="item">{_e(it["name"])}</span><span class="price">{_money(it["price"])}</span></li>' for it in menu)
            note = f'<p class="muted">{_e(section["note"])}</p>' if section.get("note") else ""
            rows.append((kind, f'<div class="col"><h2>{heading(section)}</h2>{note}<ul class="menu">{items}</ul></div>'))
        elif kind == "about":
            body = section.get("body") or about
            if not body:
                continue
            rows.append((kind, f'<div class="col"><h2>{heading(section)}</h2><p class="body">{_e(body)}</p></div>'))
        elif kind == "hours":
            place = [profile.get("hours"), profile.get("address")]
            if not any(place) and not profile.get("maps_url"):
                continue
            parts = [f'<div class="col"><h2>{heading(section)}</h2>']
            if section.get("note"):
                parts.append(f'<p class="muted">{_e(section["note"])}</p>')
            for value in place:
                if value:
                    parts.append(f'<p class="body">{_e(value)}</p>')
            if profile.get("maps_url"):
                parts.append(f'<p><a class="text-link" href="{_e(profile["maps_url"])}" rel="noopener">Open the map</a></p>')
            parts.append("</div>")
            rows.append((kind, "".join(parts)))
        elif kind == "cta":
            parts = ['<div class="col">', f"<h2>{heading(section)}</h2>"]
            if section.get("body"):
                parts.append(f'<p class="body">{_e(section["body"])}</p>')
            button = action(section)
            if button:
                parts.append(f'<p class="cta-row">{button}</p>')
            parts.append("</div>")
            rows.append((kind, "".join(parts)))

    header_cta = ""
    hero = next((s for s in site["sections"] if s["kind"] == "hero"), None)
    if hero and hero.get("action") and phone:
        header_cta = f'<a class="btn btn-sm" href="{_e(business.order_link(phone, hello))}" rel="noopener">{_e(hero["action"])}</a>'

    body_parts = [f'<header class="site"><div class="wrap bar"><span class="wordmark">{_e(name)}</span>{header_cta}</div></header>']
    for index, (_kind, inner) in enumerate(rows):
        tint = " tint" if index % 2 else ""
        body_parts.append(f'<section class="row{tint}"><div class="wrap grid">{inner}</div></section>')
    body_parts.append(f'<footer class="site"><div class="wrap bar small">{_e(name)}</div></footer>')

    css = (
        f":root{{--bg:{palette['background']};--surface:{palette['surface']};--ink:{palette['text']};--muted:{palette['muted']};--accent:{palette['accent']}}}"
        f"*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 {body_font};-webkit-font-smoothing:antialiased}}"
        ".wrap{max-width:1120px;margin:0 auto;padding:0 clamp(18px,4vw,32px)}"
        ".bar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding-top:16px;padding-bottom:16px}"
        f".wordmark{{font-family:{heading_font};font-weight:700;font-size:1.15rem;letter-spacing:-.01em}}"
        "header.site{border-bottom:1px solid rgba(0,0,0,.08)}footer.site{border-top:1px solid rgba(0,0,0,.08);color:var(--muted);padding:22px 0}"
        ".grid{display:grid;grid-template-columns:repeat(12,1fr);gap:clamp(16px,3vw,32px)}.col{grid-column:1/-1;max-width:760px}"
        ".row{padding:clamp(52px,8vw,92px) 0}.row.tint{background:var(--surface)}"
        ".eyebrow{font-size:.8rem;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin:0 0 14px}"
        f"h1{{font-family:{heading_font};font-weight:700;font-size:clamp(2.1rem,5.5vw,3.4rem);line-height:1.08;letter-spacing:-.02em;margin:0 0 18px}}"
        f"h2{{font-family:{heading_font};font-weight:600;font-size:clamp(1.4rem,3vw,2rem);line-height:1.15;margin:0 0 12px}}"
        ".lead{font-size:clamp(1.05rem,2.4vw,1.3rem);color:var(--muted);margin:0 0 26px;max-width:56ch}"
        ".body{font-size:1.05rem;max-width:60ch;margin:0 0 12px}.muted{color:var(--muted);margin:0 0 12px;max-width:60ch}"
        ".small{font-size:.85rem;color:var(--muted);opacity:.9;max-width:60ch}"
        ".offer-line{font-size:clamp(1.2rem,2.6vw,1.5rem);font-weight:600;margin:6px 0}"
        ".offer-price{font-size:clamp(1.6rem,3.6vw,2.2rem);font-weight:700;margin:0 0 10px}"
        ".cta-row{margin:22px 0 0}"
        ".btn{display:inline-flex;align-items:center;gap:.5em;padding:14px 26px;border-radius:999px;background:var(--accent);color:#fff;font-weight:700;text-decoration:none;border:2px solid var(--accent);transition:opacity .15s ease,transform .15s ease}"
        ".btn:hover{opacity:.92;transform:translateY(-1px)}.btn-sm{padding:9px 18px;font-size:.9rem}"
        ".text-link{color:var(--ink);text-decoration:underline;text-underline-offset:3px}"
        "a:focus-visible,.btn:focus-visible{outline:3px solid var(--ink);outline-offset:3px}"
        "ul.menu{list-style:none;margin:14px 0 0;padding:0}"
        "ul.menu li{display:grid;grid-template-columns:1fr auto;gap:16px;align-items:baseline;padding:14px 0;border-bottom:1px solid rgba(0,0,0,.08)}"
        "ul.menu .item{font-weight:500}ul.menu .price{font-variant-numeric:tabular-nums;font-weight:600;color:var(--muted)}"
        "@media print{header.site .btn{display:none}.row.tint{background:transparent}}"
    )
    page = (
        f'<!doctype html><html lang="{_e(lang)}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_e(name)}</title><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{_e(_font_link(families))}"><style>{css}</style></head>'
        f'<body>{"".join(body_parts)}</body></html>'
    )
    return page, warnings


# ---------------------------------------------------------------- routes

@router.post("/site/generate")
async def generate(body: GenerateIn, request: Request) -> dict:
    """The owner's one-page site, written by the OpenRouter GLM planner from their own brand, offer and languages."""
    if body.lang not in languages.CODES:
        raise fail("bad_language", "That language is not one GrowIt knows.", 422)
    if not extras.toggle_state(request.app.state.db, "openrouter")["active"]:
        raise fail("brain_not_configured", "The OpenRouter planner is off or has no key. Switch OpenRouter on in Settings, then try again.", 503)

    db: Database = request.app.state.db
    profile, _row = business._load(db, business.connections._require_owner(request))  # noqa: SLF001
    facts = business.approved_facts(db, profile) if profile else None
    en_about = (profile.get("about") or {}).get("en")

    def has(kind: str) -> bool:
        return {
            "hero": True, "cta": True, "offer": bool(facts), "menu": bool(profile.get("menu")),
            "about": bool((profile.get("about") or {}).get(body.lang) or en_about),
            "hours": bool(any(profile.get(x) for x in ("hours", "address", "maps_url"))),
        }[kind]

    request_body: dict[str, Any] = {
        "language": languages.names().get(body.lang, body.lang),
        "language_code": body.lang,
        "brand": {
            "name": profile.get("name"),
            "about": (profile.get("about") or {}).get(body.lang) or en_about,
            "tagline": (profile.get("tagline") or {}).get(body.lang) or (profile.get("tagline") or {}).get("en"),
            "hours": profile.get("hours"), "address": profile.get("address"),
            "menu": [it.get("name") for it in (profile.get("menu") or []) if isinstance(it, dict)][:20],
            "languages": profile.get("langs") or ["en"],
        },
        "approved_offer": facts,
        "sections_available": [k for k in SECTION_ORDER if has(k)],
    }
    if body.instruction:
        request_body["owner_instruction"] = body.instruction

    parsed = await _qwen(SYSTEM_PROMPT, request_body, 2000)
    site = clean_site(parsed)
    # Established brand colours win over the model's (color-system 1; RULES.md Colour 1).
    if profile.get("palette"):
        brand = profile["palette"]
        site["palette"] = clean_palette({"background": brand.get("bg"), "surface": brand.get("soft"), "text": brand.get("ink"),
                                         "accent": brand.get("accent"), "muted": brand.get("ink")})
    page, warnings = render_page(site, profile, facts, body.lang)
    return {"site": {"lang": body.lang, "idea": site["idea"], "style": site["style"], "fonts": PAIRINGS[site["fonts"]],
                     "palette": site["palette"], "sections": [s["kind"] for s in site["sections"]]},
            "html": page, "model": brain.TEXT_MODEL, "warnings": warnings, "disclaimer": DISCLAIMER}
