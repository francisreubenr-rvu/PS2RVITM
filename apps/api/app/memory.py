"""memory: "How we remember you". What GrowIt knows about the shop, in plain words the owner can read, edit and delete.

Two kinds of author:
  you      the owner types it (the menu, the pricing, the timings, how they like to sound)
  growit   GrowIt proposes it after looking at the shop's own data: saved details, approved offers, the customer list

What GrowIt proposes is only ever SUGGESTED. A suggestion is shown with its evidence and is not used anywhere until the owner
accepts it; dismissing it keeps it from coming back. Nothing here is a second source of truth for offers: prices, dates and discounts
for a campaign still come from the locked Offer Facts. The only memory that reaches the copy prompt is the owner's own voice and
"never say" notes, so a remembered price can never leak into a post.

Everything belongs to the signed-in owner, can be exported, and can be wiped in one call.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import business, connections
from app.db import Database
from app.media import fail

router = APIRouter()

KINDS = {
    "menu": "Menu and prices", "pricing": "Plans and pricing", "hours": "Hours and schedule", "offers": "Offers and specials",
    "audience": "Customers and audience", "voice": "How we sound", "results": "What has worked", "rules": "Never say or do", "about": "About the business", "other": "Other",
}
PROMPT_KINDS = ("voice", "rules")  # the only kinds that may reach a copy prompt
MAX_ITEMS = 200
MAX_NOTE_CHARS = 900
SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_item (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  use_ai INTEGER NOT NULL DEFAULT 1,
  pinned INTEGER NOT NULL DEFAULT 0,
  evidence TEXT,
  dedupe_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_key ON memory_item(owner, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_owner ON memory_item(owner, status, kind);
"""


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _view(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "kind": r["kind"], "kind_label": KINDS.get(r["kind"], r["kind"]), "title": r["title"], "body": r["body"],
            "source": r["source"], "status": r["status"], "use_ai": bool(r["use_ai"]), "pinned": bool(r["pinned"]), "evidence": r["evidence"],
            "updated_at": r["updated_at"]}


# ---------------------------------------------------------------- proposals (the "AI" side)

def propose(db: Database, owner: str, *, kind: str, title: str, body: str, key: str, evidence: str) -> str:
    """Add or refresh one suggestion. Returns 'added', 'updated' or 'kept'.
    A suggestion that is still waiting is refreshed with the newest facts. One the owner accepted, edited or dismissed is left alone."""
    row = db.query_one("SELECT id, status, body FROM memory_item WHERE owner = ? AND dedupe_key = ?", (owner, key))
    now = _now()
    if row is None:
        if db.query_one("SELECT COUNT(*) AS n FROM memory_item WHERE owner = ?", (owner,))["n"] >= MAX_ITEMS:
            return "kept"
        db.execute("INSERT INTO memory_item (id, owner, kind, title, body, source, status, evidence, dedupe_key, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, ?, 'growit', 'suggested', ?, ?, ?, ?)", (uuid.uuid4().hex[:12], owner, kind, title[:120], body[:2000], evidence[:300], key, now, now))
        return "added"
    if row["status"] == "suggested" and row["body"] != body[:2000]:
        db.execute("UPDATE memory_item SET body = ?, evidence = ?, updated_at = ? WHERE id = ?", (body[:2000], evidence[:300], now, row["id"]))
        return "updated"
    return "kept"


def gather(db: Database, owner: str) -> list[dict[str, str]]:
    """What GrowIt can tell about the shop from data it already holds. Plain code, no model, every item cites where it came from."""
    out: list[dict[str, str]] = []
    profile, _ = business._load(db, owner)
    if profile.get("menu"):
        lines = "\n".join(f"{m['name']}: ₹{m['price']:g}" for m in profile["menu"])
        out.append({"kind": "menu", "title": "Menu and prices", "body": lines, "key": "profile:menu", "evidence": "From the menu in Brand & Data."})
    if profile.get("hours"):
        out.append({"kind": "hours", "title": "Opening hours", "body": profile["hours"], "key": "profile:hours", "evidence": "From Brand & Data."})
    place = ", ".join(x for x in [profile.get("address"), f"WhatsApp +{profile['phone']}" if profile.get("phone") else ""] if x)
    if place:
        out.append({"kind": "about", "title": "Where and how to reach us", "body": place, "key": "profile:place", "evidence": "From Brand & Data."})
    about = (profile.get("about") or {}).get("en")
    if about:
        out.append({"kind": "about", "title": "About the business", "body": about, "key": "profile:about", "evidence": "From Brand & Data."})
    tag = (profile.get("tagline") or {}).get("en")
    if tag:
        out.append({"kind": "voice", "title": "Our tagline", "body": tag, "key": "profile:tagline", "evidence": "From Names & Brand look."})
    for c in db.campaign_list()[:6]:
        row = db.facts_approved(c["id"])
        if not row:
            continue
        f = json.loads(row["json"])
        bits = [f.get("item"), f"{f['discount_percent']:g}% off" if f.get("discount_percent") else None, f"₹{f['price_amount']:g}" if f.get("price_amount") else None,
                ", ".join(f.get("dates") or []) or None, f.get("timings"), f.get("terms")]
        out.append({"kind": "offers", "title": f"Offer: {f.get('item')}", "body": " · ".join(b for b in bits if b), "key": f"offer:{c['id']}",
                    "evidence": "From the approved facts of one of your campaigns."})
    from app import learn  # imported here: learn pulls in the forecast, which memory does not otherwise need
    for cid in [r["campaign_id"] for r in db.query("SELECT DISTINCT campaign_id FROM result ORDER BY updated_at DESC LIMIT 3")]:
        got = learn.learning(db, cid)
        if not got["summary"]["assets_with_results"]:
            continue
        best = got["summary"]["best_channel"]
        body = "\n".join(([f"Best channel: {best.replace('_', ' ')}."] if best else []) + got["lessons"][:4])
        row = db.facts_approved(cid) or db.facts_latest(cid)
        item = json.loads(row["json"]).get("item") if row else None
        out.append({"kind": "results", "title": f"What worked: {item}" if item else "What worked in a past campaign",
                    "body": body, "key": f"results:{cid}",
                    "evidence": f"From the {got['summary']['assets_with_results']} result(s) you entered: {got['summary']['total_reached']:,} reached, {got['summary']['total_redemptions']:,} redeemed."})
    rows = db.query("SELECT language FROM customer WHERE owner = ?", (owner,))
    langs = Counter(r["language"] for r in rows if r["language"])
    if sum(langs.values()) >= 5:
        total = sum(langs.values())
        mix = ", ".join(f"{n * 100 // total}% {lang}" for lang, n in langs.most_common())
        out.append({"kind": "audience", "title": "Languages your customers use", "body": mix, "key": "customers:language",
                    "evidence": f"From the {total} people in your Customers list who have a language set."})
    return out


def prompt_notes(db: Database, owner: str | None = None) -> list[str]:
    """Short style notes for the copy prompt: the owner's accepted voice and never-say memory only, trimmed. Never prices or offers."""
    rows = db.query("SELECT kind, title, body FROM memory_item WHERE status = 'active' AND use_ai = 1 AND kind IN ('voice', 'rules') "
                    + ("AND owner = ? " if owner else "") + "ORDER BY pinned DESC, updated_at DESC LIMIT 12", (owner,) if owner else ())
    notes, used = [], 0
    for r in rows:
        line = f"{'Avoid' if r['kind'] == 'rules' else 'Style'}: {r['title']}. {r['body']}".strip()[:300]
        if used + len(line) > MAX_NOTE_CHARS:
            break
        notes.append(line)
        used += len(line)
    return notes


# ---------------------------------------------------------------- the voice briefing

BRIEFING_KINDS = {"org": "Organisations", "role": "Roles", "project": "Projects", "skill": "Skills", "judgment": "What I believe", "ambition": "Ambitions", "trait": "Traits"}


class BriefFact(BaseModel):
    """One fact from the voice briefing, as the live agent recorded it: subject, relation, object, and what sort of thing the object is."""
    subject: str = Field(default="", max_length=160)
    relation: str = Field(min_length=1, max_length=60)
    object: str = Field(min_length=1, max_length=200)
    kind: str = Field(max_length=20)
    detail: str = Field(default="", max_length=300)
    quote: str = Field(default="", max_length=400)


class BriefingIn(BaseModel):
    facts: list[BriefFact] = Field(min_length=1, max_length=120)


def fact_line(f: BriefFact) -> str:
    head = f"{f.subject.strip()} " if f.subject.strip() else ""
    line = f"{head}{f.relation.strip()} {f.object.strip()}"
    if f.detail.strip():
        line += f" ({f.detail.strip()})"
    if f.quote.strip():
        line += f" - \u201c{f.quote.strip()}\u201d"
    return line


# ---------------------------------------------------------------- routes

class ItemIn(BaseModel):
    kind: str = Field(default="other", max_length=20)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=2000)
    use_ai: bool = True
    pinned: bool = False


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise fail("bad_kind", f"Kind must be one of: {', '.join(KINDS)}.", 422)
    return kind


def _mine(db: Database, owner: str, item_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM memory_item WHERE id = ? AND owner = ?", (item_id, owner))
    if row is None:
        raise fail("not_found", "No memory with that id.", 404)
    return row


@router.get("/memory")
def listing(request: Request, q: str | None = None) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    rows = db.query("SELECT * FROM memory_item WHERE owner = ? AND status IN ('active', 'suggested') ORDER BY pinned DESC, updated_at DESC", (owner,))
    items = [_view(r) for r in rows]
    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in (i["title"] + " " + i["body"]).lower()]
    return {"kinds": KINDS, "items": [i for i in items if i["status"] == "active"], "suggested": [i for i in items if i["status"] == "suggested"],
            "note": "Suggestions are not used until you accept them. Prices and dates in a campaign always come from its approved facts, not from memory."}


@router.post("/memory")
def create(body: ItemIn, request: Request) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    _check_kind(body.kind)
    if db.query_one("SELECT COUNT(*) AS n FROM memory_item WHERE owner = ?", (owner,))["n"] >= MAX_ITEMS:
        raise fail("too_many", f"At most {MAX_ITEMS} memories. Remove some first.", 409)
    now, item_id = _now(), uuid.uuid4().hex[:12]
    db.execute("INSERT INTO memory_item (id, owner, kind, title, body, source, status, use_ai, pinned, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'you', 'active', ?, ?, ?, ?)",
               (item_id, owner, body.kind, body.title.strip(), body.body.strip(), int(body.use_ai), int(body.pinned), now, now))
    return _view(db.query_one("SELECT * FROM memory_item WHERE id = ?", (item_id,)))


@router.put("/memory/{item_id}")
def update(item_id: str, body: ItemIn, request: Request) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    row = _mine(db, owner, item_id)
    _check_kind(body.kind)
    # An edit makes it the owner's: it is active and no longer refreshed from data.
    db.execute("UPDATE memory_item SET kind = ?, title = ?, body = ?, use_ai = ?, pinned = ?, source = 'you', status = 'active', updated_at = ? WHERE id = ?",
               (body.kind, body.title.strip(), body.body.strip(), int(body.use_ai), int(body.pinned), _now(), row["id"]))
    return _view(db.query_one("SELECT * FROM memory_item WHERE id = ?", (item_id,)))


@router.post("/memory/{item_id}/accept")
def accept(item_id: str, request: Request) -> dict:
    db: Database = request.app.state.db
    row = _mine(db, connections._require_owner(request), item_id)
    if row["status"] != "suggested":
        raise fail("not_suggested", "Only a suggestion can be accepted.", 409)
    db.execute("UPDATE memory_item SET status = 'active', updated_at = ? WHERE id = ?", (_now(), item_id))
    return _view(db.query_one("SELECT * FROM memory_item WHERE id = ?", (item_id,)))


@router.post("/memory/{item_id}/dismiss")
def dismiss(item_id: str, request: Request) -> dict:
    """Keeps a record that it was dismissed (with its key), so the same suggestion does not come back."""
    db: Database = request.app.state.db
    row = _mine(db, connections._require_owner(request), item_id)
    if row["status"] != "suggested":
        raise fail("not_suggested", "Only a suggestion can be dismissed.", 409)
    db.execute("UPDATE memory_item SET status = 'dismissed', body = '', updated_at = ? WHERE id = ?", (_now(), item_id))
    return {"ok": True}


@router.delete("/memory/{item_id}")
def remove(item_id: str, request: Request) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    row = _mine(db, owner, item_id)
    if row["dedupe_key"]:  # a remembered-from-data item becomes "dismissed" so it is not suggested again
        db.execute("UPDATE memory_item SET status = 'dismissed', body = '', updated_at = ? WHERE id = ?", (_now(), item_id))
    else:
        db.execute("DELETE FROM memory_item WHERE id = ?", (item_id,))
    return {"ok": True}


@router.post("/memory/briefing")
def save_briefing(body: BriefingIn, request: Request) -> dict:
    """Keep what the owner said in a voice briefing. They press Save after seeing the live map, so this is their own yes: the notes are active.
    One note per kind of fact. A later briefing adds lines the note does not have yet and never removes or rewrites what is there."""
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    grouped: dict[str, list[str]] = {}
    for f in body.facts:
        if f.kind not in BRIEFING_KINDS:
            raise fail("bad_kind", f"A fact's kind must be one of: {', '.join(BRIEFING_KINDS)}.", 422)
        grouped.setdefault(f.kind, []).append(fact_line(f))
    now = _now()
    saved = 0
    for kind, lines in grouped.items():
        key = f"briefing:{kind}"
        row = db.query_one("SELECT id, body FROM memory_item WHERE owner = ? AND dedupe_key = ?", (owner, key))
        title = f"From my briefing: {BRIEFING_KINDS[kind]}"
        if row is None:
            if db.query_one("SELECT COUNT(*) AS n FROM memory_item WHERE owner = ?", (owner,))["n"] >= MAX_ITEMS:
                raise fail("too_many", f"At most {MAX_ITEMS} memories. Remove some first.", 409)
            db.execute("INSERT INTO memory_item (id, owner, kind, title, body, source, status, evidence, dedupe_key, created_at, updated_at) "
                       "VALUES (?, ?, 'about', ?, ?, 'you', 'active', ?, ?, ?, ?)",
                       (uuid.uuid4().hex[:12], owner, title, "\n".join(dict.fromkeys(lines))[:2000], f"Said by you in a voice briefing on {now[:10]}.", key, now, now))
        else:
            have = [ln for ln in row["body"].split("\n") if ln]  # a note the owner removed has an empty body
            merged = have + [ln for ln in dict.fromkeys(lines) if ln not in have]
            db.execute("UPDATE memory_item SET body = ?, status = 'active', updated_at = ? WHERE id = ?", ("\n".join(merged)[:2000], now, row["id"]))
        saved += len(lines)
    return {"saved": saved, "notes": len(grouped)}


# ---------------------------------------------------------------- import from another AI

MAX_IMPORT_CHARS = 20000
MAX_IMPORT_ENTRIES = 120
LIST_KEYS = ("memories", "memory", "items", "entries", "facts", "notes", "data")
TEXT_KEYS = ("content", "text", "memory", "body", "value", "fact", "note", "description")
TITLE_KEYS = ("title", "name", "key", "label", "topic", "subject")
BULLET = re.compile(r"^\s*(?:[-*•●▪]|\d{1,3}[.)])\s+")


class ImportDraft(BaseModel):
    """One proposed memory, shown to the owner for review. Nothing here is saved."""
    kind: str = Field(default="other", max_length=20)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=2000)


class ImportPreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_IMPORT_CHARS)
    tidy: bool = False  # the owner asks the reasoning model to rewrite messy text into short entries


class ImportSaveIn(BaseModel):
    entries: list[ImportDraft] = Field(min_length=1, max_length=MAX_IMPORT_ENTRIES)


def _draft(title: str, body: str) -> dict[str, str] | None:
    title, body = " ".join(str(title or "").split()), str(body or "").strip()
    if not title and not body:
        return None
    if not title:
        title = body
    if len(title) > 60:  # a long first line becomes its own body; the title is its opening words
        body = body or title
        cut = title[:60].rsplit(" ", 1)[0] or title[:60]
        title = cut.rstrip(",;:-") + "..."
    return {"kind": "other", "title": title[:120], "body": body[:2000] if body != title else ""}


def _from_json(data: Any) -> list[dict[str, str]]:
    if isinstance(data, dict):
        for k in LIST_KEYS:
            if isinstance(data.get(k), list):
                return _from_json(data[k])
        out = [_draft(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in data.items() if v not in (None, "", [], {})]
        return [d for d in out if d]
    out = []
    for row in data if isinstance(data, list) else []:
        if isinstance(row, str):
            d = _draft("", row)
        elif isinstance(row, dict):
            body = next((str(row[k]) for k in TEXT_KEYS if row.get(k)), "")
            title = next((str(row[k]) for k in TITLE_KEYS if row.get(k)), "")
            d = _draft(title, body) if (title or body) else None
        else:
            d = None
        if d:
            out.append(d)
    return out


def _from_text(text: str) -> list[dict[str, str]]:
    """Bullets first; failing that, one entry per line. Headings are dropped, 'Label: detail' lines keep the label as the title."""
    out = []
    for raw in text.replace("\r", "").split("\n"):
        line = BULLET.sub("", raw).strip()
        if not line or re.fullmatch(r"[-_=*#\s]{3,}", line) or re.match(r"^#{1,6}\s", line) or (line.endswith(":") and len(line) < 80):
            continue
        line = line.replace("**", "")
        head, sep, rest = line.partition(":")
        d = _draft(head, rest.strip()) if sep and rest.strip() and 0 < len(head) <= 60 else _draft("", line)
        if d:
            out.append(d)
    return out


def split_import(text: str) -> list[dict[str, str]]:
    """Deterministic split of pasted or uploaded text (plain text, markdown or JSON) into atomic entries. Never adds anything that was not there."""
    body = text.strip()
    found: list[dict[str, str]] = []
    if body[:1] in ("[", "{"):
        try:
            found = _from_json(json.loads(body))
        except ValueError:
            found = []
    if not found:
        found = _from_text(body)
    seen, out = set(), []
    for d in found:
        key = (d["title"].lower(), d["body"].lower())
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out[:MAX_IMPORT_ENTRIES]


TIDY_PROMPT = (
    "You tidy a memory export from another AI assistant into short, separate, factual entries about one small business owner and their shop. "
    "Rules: use only facts that are written in the text. Never invent, infer or add anything. Do not add prices, dates or discounts that are not in the text, "
    "and copy any that are there exactly. Split anything that holds several facts into one entry per fact. Drop greetings, instructions to the assistant and duplicates. "
    'Reply with JSON only: {"entries":[{"title":"2 to 6 words","body":"one short sentence"}]}.'
)


async def tidy_with_model(text: str) -> list[dict[str, str]]:
    """Ask the app's one reasoning model (OpenRouter, brain.TEXT_MODEL) to tidy raw text. Raises brain.BrainNotConfigured, BrainBadReply or BrainError."""
    import httpx
    from app import brain
    from app.config import text_request
    payload = {"model": brain.TEXT_MODEL, "temperature": 0.1, "max_tokens": 3000, "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": TIDY_PROMPT}, {"role": "user", "content": text[:12000]}]}
    headers = {"Authorization": f"Bearer {brain._require_key()}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(brain.TEXT_URL, headers=headers, json=text_request(payload))
    if r.status_code >= 400:
        raise brain.BrainError(f"OpenRouter {r.status_code}")
    try:
        rows = brain.parse_json_object(r.json()["choices"][0]["message"]["content"])["entries"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise brain.BrainBadReply("OpenRouter did not return a list of entries") from exc
    out = [_draft(str(x.get("title") or ""), str(x.get("body") or "")) for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []
    return [d for d in out if d][:MAX_IMPORT_ENTRIES]


@router.post("/memory/import/preview")
async def import_preview(body: ImportPreviewIn, request: Request) -> dict:
    """Turn pasted text into proposed entries. Saves nothing: the owner reviews, edits and presses Save on /memory/import."""
    from app import brain, extras
    connections._require_owner(request)
    method = "split"
    if body.tidy:
        if not extras.toggle_state(request.app.state.db, "openrouter")["active"]:
            raise fail("brain_not_configured", "The OpenRouter model is off or has no key. Switch it on in Settings, or import without tidying.", 503)
        try:
            entries = await tidy_with_model(body.text)
            method = "model"
        except brain.BrainNotConfigured as exc:
            raise fail("brain_not_configured", str(exc), 503) from exc
        except brain.BrainBadReply as exc:
            raise fail("brain_bad_reply", str(exc), 502) from exc
        except brain.BrainError as exc:
            raise fail("brain_provider_error", str(exc), 502) from exc
    else:
        entries = split_import(body.text)
    if not entries:
        raise fail("nothing_found", "No separate items were found in that text.", 422)
    return {"entries": entries, "method": method}


@router.post("/memory/import")
def import_save(body: ImportSaveIn, request: Request) -> dict:
    """Keep the entries the owner reviewed. They press Save after seeing the list, so these are their own yes: active, never applied to prices or offers."""
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    have = db.query_one("SELECT COUNT(*) AS n FROM memory_item WHERE owner = ?", (owner,))["n"]
    now = _now()
    saved = skipped = 0
    for e in body.entries:
        _check_kind(e.kind)
        title, text = e.title.strip(), e.body.strip()
        if not title or db.query_one("SELECT id FROM memory_item WHERE owner = ? AND status = 'active' AND lower(title) = ? AND lower(body) = ?", (owner, title.lower(), text.lower())):
            skipped += 1
            continue
        if have + saved >= MAX_ITEMS:
            raise fail("too_many", f"At most {MAX_ITEMS} memories. Remove some first. {saved} were saved before the limit.", 409)
        db.execute("INSERT INTO memory_item (id, owner, kind, title, body, source, status, evidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'you', 'active', ?, ?, ?)",
                   (uuid.uuid4().hex[:12], owner, e.kind, title, text, f"Imported from another source and reviewed by you on {now[:10]}.", now, now))
        saved += 1
    return {"saved": saved, "skipped": skipped}


@router.post("/memory/refresh")
def refresh(request: Request) -> dict:
    """Look at the shop's data again and propose anything new. Never changes what the owner already accepted or wrote."""
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    counts = Counter(propose(db, owner, kind=g["kind"], title=g["title"], body=g["body"], key=g["key"], evidence=g["evidence"]) for g in gather(db, owner))
    return {"added": counts["added"], "updated": counts["updated"]}


@router.get("/memory/export")
def export(request: Request) -> dict:
    db: Database = request.app.state.db
    owner = connections._require_owner(request)
    rows = db.query("SELECT * FROM memory_item WHERE owner = ? AND status != 'dismissed' ORDER BY kind, title", (owner,))
    return {"exported_at": _now(), "items": [_view(r) for r in rows]}


@router.delete("/memory")
def forget_all(request: Request, confirm: bool = False) -> dict:
    if not confirm:
        raise fail("confirm_required", "Add ?confirm=true to forget everything.", 400)
    db: Database = request.app.state.db
    db.execute("DELETE FROM memory_item WHERE owner = ?", (connections._require_owner(request),))
    return {"ok": True}
