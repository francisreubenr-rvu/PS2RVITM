"""seed_demo: sample data for the Replies and Change Log screens.

The two screens read real rows from this app's database, so the only honest way to fill them for a UI walkthrough is
to seed rows and mark them. This script writes one campaign whose id starts with "demo-" and fills it with sample
replies (drafted, escalated and approved states) and a sample change-log trail. The app labels everything from a
"demo-" campaign "Sample", so it is never read as real customer activity.

    Run from apps/api:   ../../.venv/bin/python scripts/seed_demo.py
    Remove it again:     ../../.venv/bin/python scripts/seed_demo.py --clear

Nothing is sent anywhere and no model is called. By default it works on the same database the app uses
(load_settings). Pass --db to point elsewhere. Every run replaces the previous sample rows, so running it twice
does not pile up duplicates.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import plan as plan_module  # noqa: E402
from app import reply  # noqa: E402
from app.changes import clear_demo_events, seed_demo_events  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.schemas import OfferFacts  # noqa: E402
from app.service import now  # noqa: E402

BUSINESS = {"name": "Brew House (sample)", "type": "cafe", "area": "Indiranagar, Bengaluru"}
TRANSCRIPT = "Sample data for the Replies and Change Log walkthrough. Not a real campaign."
TIME_WINDOW = "8 am to 11 am"


def _next_weekend() -> list[str]:
    today = date.today()
    saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    return [saturday.isoformat(), (saturday + timedelta(days=1)).isoformat()]


def _facts() -> OfferFacts:
    return OfferFacts(
        item="filter coffee", discount_percent=20, price_amount=None, dates=_next_weekend(),
        timings=f"Saturday and Sunday, {TIME_WINDOW}", terms="dine-in only",
        audiences=["regulars", "students"], languages=["en", "kn", "hi"], channels=["whatsapp", "instagram_story", "poster"],
    )


def _plan_data(facts: OfferFacts) -> dict:
    return {
        "business": BUSINESS,
        "goal": {"value": "promote_offer", "label": "Promote an offer", "source_answer_id": None},
        "facts_sources": {key: None for key in ("item", "discount_percent", "timings", "terms")},
        "tone": "warm_local",
        "time_window": TIME_WINDOW,
        "cta": {"kind": "whatsapp", "value": "+91 90000 00000", "source_answer_id": None},
        "email_recipients": [],
        "sources": {},
        "answers": [],
    }


def seed(db: Database) -> str:
    """Create the demo campaign with locked facts and its sample replies and events. Returns the campaign id."""
    cid = reply.DEMO_CAMPAIGN_PREFIX + uuid.uuid4().hex[:12]
    facts = _facts()
    stamp = now()
    db.campaign_insert({"id": cid, "brand_voice": "warm_local", "status": "facts_locked",
                        "transcript": TRANSCRIPT, "suggestion": None, "created_at": stamp})
    db.facts_insert({"campaign_id": cid, "version": 1, "json": facts.model_dump_json(), "approved": 1, "created_at": stamp})
    plan_module.store(db, cid, _plan_data(facts))
    reply.seed_demo_replies(db, cid)
    seed_demo_events(db, cid)
    return cid


def demo_campaigns(db: Database) -> list[str]:
    return [c["id"] for c in db.campaign_list() if str(c["id"]).startswith(reply.DEMO_CAMPAIGN_PREFIX)]


def clear(db: Database) -> int:
    """Delete every demo campaign and all rows that reference it. Real campaigns are never touched."""
    removed = 0
    for cid in demo_campaigns(db):
        tables = [r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            columns = {c["name"] for c in db.query(f"PRAGMA table_info({table})")}
            if "campaign_id" in columns:
                db.execute(f"DELETE FROM {table} WHERE campaign_id = ?", (cid,))
        db.execute("DELETE FROM campaign WHERE id = ?", (cid,))
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or clear the Replies and Change Log sample data.")
    parser.add_argument("--clear", action="store_true", help="remove every demo campaign and its rows, then exit")
    parser.add_argument("--db", type=Path, default=None, help="database path (defaults to the app's own database)")
    args = parser.parse_args()

    settings = load_settings()
    path = args.db or settings.database_path
    db = Database(path)
    db.migrate()
    plan_module.ensure_schema(db)
    reply.ensure_schema(db)

    if args.clear:
        removed = clear(db)
        print(f"Cleared {removed} demo campaign(s) from {path}")
        return 0

    # Replace any previous sample campaign so repeated runs stay clean.
    clear(db)
    cid = seed(db)
    print(f"Seeded demo campaign {cid} in {path}")
    print(f"  Replies     http://127.0.0.1:3050/#/replies/{cid}")
    print(f"  Change Log  http://127.0.0.1:3050/#/log/{cid}")
    print("Clear it with: ../../.venv/bin/python scripts/seed_demo.py --clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
