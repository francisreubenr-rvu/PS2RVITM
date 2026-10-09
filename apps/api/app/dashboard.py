"""dashboard: metrics computed only from this app's own tables. Zero stays zero. Contract in PLAN.md."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from app import persona, plan, review
from app.db import Database
from app.media import fail, media_for_assets
from app.outreach import ACTIONS, links_for_campaign, outreach_counts

router = APIRouter()

ACTIVITY_LIMIT = 50
# Review statuses that mean the meaning check did not clear the asset.
NOT_CLEARED = {review.CHECKING, review.FLAGGED, review.FAILED, review.UNAVAILABLE}
FUNNEL = ("planned", "written", "passed checks", "approved", "distributed", "clicked")


def ensure_schema(db: Database) -> None:
    """Nothing to create: the dashboard only reads other tables."""


def _require_campaign(db: Database, campaign_id: str) -> dict[str, Any]:
    campaign = db.campaign_get(campaign_id)
    if campaign is None:
        raise fail("not_found", "No campaign with that id.", 404)
    return campaign


def _marks(values: tuple[str, ...]) -> str:
    return ", ".join("?" for _ in values)


def _distributed_ids(db: Database, campaign_id: str) -> set[str]:
    ids = {
        row["asset_id"]
        for row in db.query(
            f"SELECT DISTINCT asset_id FROM outreach_event WHERE campaign_id = ? AND action IN ({_marks(ACTIONS)})",
            (campaign_id, *ACTIONS),
        )
    }
    ids |= {row["asset_id"] for row in db.query("SELECT DISTINCT asset_id FROM email_send WHERE campaign_id = ?", (campaign_id,))}
    return ids


def _clicked_ids(db: Database, campaign_id: str) -> set[str]:
    return {row["asset_id"] for row in db.query("SELECT DISTINCT asset_id FROM click WHERE campaign_id = ?", (campaign_id,))}


def _count(db: Database, sql: str, campaign_id: str) -> int:
    return db.query_one(sql, (campaign_id,))["n"]


def _passed(asset: dict[str, Any]) -> bool:
    if not asset["content"] or asset["status"] not in ("pending", "approved"):
        return False
    meaning = json.loads(asset["review"]) if asset.get("review") else {}
    return meaning.get("status") not in NOT_CLEARED


def totals_for(db: Database, campaign_id: str) -> dict[str, int]:
    assets = db.assets_for(campaign_id)
    return {
        "assets": len(assets),
        "approved": sum(1 for a in assets if a["status"] == "approved"),
        "blocked": sum(1 for a in assets if a["status"] == "blocked"),
        "distributed": len(_distributed_ids(db, campaign_id)),
        "clicks": _count(db, "SELECT COUNT(*) AS n FROM click WHERE campaign_id = ?", campaign_id),
        "email_sent": _count(db, "SELECT COUNT(*) AS n FROM email_send WHERE campaign_id = ?", campaign_id),
        "email_opens": _count(db, "SELECT COUNT(DISTINCT token) AS n FROM email_open WHERE campaign_id = ?", campaign_id),
    }


def _hour(ts: str) -> str:
    moment = datetime.fromisoformat(ts)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()


def _activity(db: Database, campaign_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in db.query("SELECT ts, action, detail FROM event_log WHERE campaign_id = ? ORDER BY id DESC LIMIT ?", (campaign_id, ACTIVITY_LIMIT)):
        items.append({"ts": row["ts"], "kind": row["action"], "detail": row["detail"] or "", "asset_id": None})
    for row in db.query(
        "SELECT ts, asset_id, action, detail FROM outreach_event WHERE campaign_id = ? ORDER BY id DESC LIMIT ?",
        (campaign_id, ACTIVITY_LIMIT),
    ):
        items.append({"ts": row["ts"], "kind": row["action"], "detail": row["detail"] or row["action"].replace("_", " "), "asset_id": row["asset_id"]})
    for row in db.query("SELECT ts, asset_id, channel, lang, referrer FROM click WHERE campaign_id = ? ORDER BY id DESC LIMIT ?", (campaign_id, ACTIVITY_LIMIT)):
        detail = f"{row['lang']} {row['channel']} link clicked" + (f" from {row['referrer']}" if row["referrer"] else "")
        items.append({"ts": row["ts"], "kind": "click", "detail": detail, "asset_id": row["asset_id"]})
    for row in db.query("SELECT ts, asset_id, recipient_email FROM email_send WHERE campaign_id = ? ORDER BY id DESC LIMIT ?", (campaign_id, ACTIVITY_LIMIT)):
        items.append({"ts": row["ts"], "kind": "email_sent", "detail": f"Email sent to {row['recipient_email']}", "asset_id": row["asset_id"]})
    for row in db.query("SELECT ts, asset_id FROM email_open WHERE campaign_id = ? ORDER BY id DESC LIMIT ?", (campaign_id, ACTIVITY_LIMIT)):
        items.append({"ts": row["ts"], "kind": "email_open", "detail": "Email opened", "asset_id": row["asset_id"]})
    # Prediction events come from their own tables so each row carries its asset.
    for row in db.query(
        """
        SELECT p.ts, p.asset_id, p.mean, a.lang, a.channel FROM (
          SELECT created_at AS ts, asset_id, mean, campaign_id FROM prediction
        ) p JOIN asset a ON a.id = p.asset_id WHERE p.campaign_id = ? ORDER BY p.ts DESC LIMIT ?
        """,
        (campaign_id, ACTIVITY_LIMIT),
    ):
        items.append({"ts": row["ts"], "kind": "prediction_ready", "detail": f"{row['lang']} {row['channel']} scored {row['mean']} of 10 by synthetic personas", "asset_id": row["asset_id"]})
    for row in db.query(
        "SELECT updated_at AS ts, asset_id, loops, detail FROM optimization WHERE campaign_id = ? AND status = 'stopped'", (campaign_id,)
    ):
        items.append({"ts": row["ts"], "kind": "optimize_stopped", "detail": row["detail"] or "", "asset_id": row["asset_id"]})
    for row in db.query(
        "SELECT updated_at AS ts, asset_id, detail FROM job WHERE campaign_id = ? AND kind = 'predict' AND status = 'failed'", (campaign_id,)
    ):
        items.append({"ts": row["ts"], "kind": "predict_failed", "detail": row["detail"] or "", "asset_id": row["asset_id"]})
    items.sort(key=lambda item: item["ts"], reverse=True)
    return items[:ACTIVITY_LIMIT]


def _quality(db: Database, campaign_id: str) -> dict[str, int]:
    def events(action: str) -> int:
        return db.query_one(
            "SELECT COUNT(*) AS n FROM event_log WHERE campaign_id = ? AND action = ?", (campaign_id, action)
        )["n"]

    # A repair is a copy job with attempt >= 1 in its payload. It succeeded when its copy passed the fact check.
    repairs = [
        job
        for job in db.query("SELECT status, payload FROM job WHERE campaign_id = ? AND kind = 'copy' AND payload IS NOT NULL", (campaign_id,))
        if int(json.loads(job["payload"]).get("attempt", 0)) >= 1
    ]
    return {
        "fact_blocks": events("asset_blocked"),
        "meaning_flags": events("meaning_flagged"),
        "repairs": len(repairs),
        "repairs_succeeded": sum(1 for job in repairs if job["status"] == "completed"),
        "repairs_exhausted": events("repair_exhausted"),
    }


def _geography(db: Database, campaign_id: str) -> dict[str, Any]:
    """The place the campaign is for, read from the plan. This app never measures where reach comes from, so this
    is the real place anchor only: the Insights screen splits its sample reach across bands that centre on it."""
    data = plan.get_plan(db, campaign_id) or {}
    area = str((data.get("business") or {}).get("area") or "").strip() or None
    parts = [part.strip() for part in area.split(",")] if area else []
    return {
        "area": area,
        "locality": parts[0] if parts else None,
        "city": parts[-1] if len(parts) > 1 else None,
        "measured": False,
    }


def _predictions(db: Database, campaign_id: str) -> dict[str, Any] | None:
    items = []
    for payload in persona.predictions_for_campaign(db, campaign_id).values():
        history = payload["history"]
        items.append(
            {
                "asset_id": payload["asset_id"],
                "channel": payload["channel"],
                "lang": payload["lang"],
                "mean": payload["mean"],
                "dimensions": payload["dimensions"],
                "before_mean": history[0]["mean"],
                "after_mean": history[-1]["mean"] if len(history) > 1 else None,
                "optimization": payload["optimization"],
            }
        )
    return {"label": persona.LABEL, "items": items} if items else None


@router.get("/campaign/{campaign_id}/dashboard")
def campaign_dashboard(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    _require_campaign(db, campaign_id)
    assets = db.assets_for(campaign_id)
    distributed = _distributed_ids(db, campaign_id)
    clicked = _clicked_ids(db, campaign_id)
    counts = outreach_counts(db, campaign_id)

    stage_counts = (
        len(assets),
        sum(1 for a in assets if a["content"]),
        sum(1 for a in assets if _passed(a)),
        sum(1 for a in assets if a["status"] == "approved"),
        len(distributed),
        len(clicked),
    )

    by_channel: dict[str, dict[str, Any]] = {}
    by_language: dict[str, dict[str, Any]] = {}
    for a in assets:
        c = by_channel.setdefault(a["channel"], {"channel": a["channel"], "assets": 0, "approved": 0, "distributed": 0, "clicks": 0, "opens": 0})
        l = by_language.setdefault(a["lang"], {"lang": a["lang"], "assets": 0, "approved": 0, "clicks": 0})
        own = counts.get(a["id"], {})
        for row in (c, l):
            row["assets"] += 1
            row["approved"] += a["status"] == "approved"
            row["clicks"] += own.get("clicks", 0)
        c["distributed"] += a["id"] in distributed
        c["opens"] += own.get("opens", 0)

    buckets: dict[tuple[str, str], int] = {}
    for row in db.query("SELECT ts, channel FROM click WHERE campaign_id = ?", (campaign_id,)):
        key = (_hour(row["ts"]), row["channel"])
        buckets[key] = buckets.get(key, 0) + 1

    return {
        "totals": totals_for(db, campaign_id),
        "geography": _geography(db, campaign_id),
        "funnel": [{"stage": stage, "count": count} for stage, count in zip(FUNNEL, stage_counts)],
        "by_channel": sorted(by_channel.values(), key=lambda row: row["channel"]),
        "by_language": sorted(by_language.values(), key=lambda row: row["lang"]),
        "clicks_series": [
            {"bucket_start": start, "channel": channel, "count": count} for (start, channel), count in sorted(buckets.items())
        ],
        "activity": _activity(db, campaign_id),
        "quality": _quality(db, campaign_id),
        "predictions": _predictions(db, campaign_id),
    }


@router.get("/campaigns/overview")
def campaigns_overview(request: Request) -> list[dict]:
    db = request.app.state.db
    return [
        {
            "campaign_id": campaign["id"],
            "business": ((plan.get_plan(db, campaign["id"]) or {}).get("business")),
            "status": campaign["status"],
            "totals": totals_for(db, campaign["id"]),
        }
        for campaign in db.campaign_list()
    ]


@router.get("/campaign/{campaign_id}/assets/state")
def assets_state(campaign_id: str, request: Request) -> dict:
    db = request.app.state.db
    _require_campaign(db, campaign_id)
    media = media_for_assets(db, campaign_id)
    links = links_for_campaign(db, campaign_id)
    counts = outreach_counts(db, campaign_id)
    predictions = persona.predictions_for_campaign(db, campaign_id)
    return {
        asset["id"]: {
            "media": media.get(asset["id"], []),
            "link": links.get(asset["id"]),
            "prediction": predictions.get(asset["id"]),
            "outreach": counts.get(asset["id"])
            or {**{action: 0 for action in ACTIONS}, "email_sent": 0, "clicks": 0, "opens": 0},
        }
        for asset in db.assets_for(campaign_id)
    }
