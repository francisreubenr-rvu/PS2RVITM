from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app import channels, review
from app.db import Database
from app.schemas import OfferFacts
from app.validator import ValidationResult, facts_in_content, fields_present


ALL_AUDIENCES = "all"


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code = code
        self.message = message
        self.status = status


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    return json.loads(value)


class Service:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_campaign(self, transcript: str, brand_voice: str | None) -> dict[str, Any]:
        campaign_id = uuid.uuid4().hex
        self.db.campaign_insert(
            {
                "id": campaign_id,
                "brand_voice": brand_voice,
                "status": "draft",
                "transcript": transcript.strip(),
                "suggestion": None,
                "created_at": now(),
            }
        )
        self.db.log(now(), "owner", "campaign_created", "Transcript stored.", campaign_id)
        campaign = self.db.campaign_get(campaign_id)
        if campaign is None:
            raise ServiceError("not_found", "Campaign was not stored.", 500)
        return self._campaign(campaign)

    def list_campaigns(self) -> list[dict[str, Any]]:
        return [self._campaign(row) for row in self.db.campaign_list()]

    def save_facts(self, campaign_id: str, facts: OfferFacts) -> dict[str, Any]:
        self._require_campaign(campaign_id)
        version = self.db.facts_next_version(campaign_id)
        self.db.facts_insert(
            {
                "campaign_id": campaign_id,
                "version": version,
                "json": facts.model_dump_json(),
                "approved": 0,
                "created_at": now(),
            }
        )
        self._refresh_status(campaign_id)
        self.db.log(now(), "owner", "facts_saved", f"Draft offer facts v{version} saved.", campaign_id)
        return self.board(campaign_id)

    def approve_latest(self, campaign_id: str) -> dict[str, Any]:
        self._require_campaign(campaign_id)
        latest = self.db.facts_latest(campaign_id)
        if latest is None:
            raise ServiceError("facts_missing", "Save offer facts before locking them.", 409)
        if not latest["approved"]:
            self.db.facts_approve(campaign_id, latest["version"])
            self.db.log(
                now(),
                "owner",
                "facts_approved",
                f"Offer facts v{latest['version']} locked.",
                campaign_id,
            )
        self._refresh_status(campaign_id)
        return self.board(campaign_id)

    def prepare_generation(self, campaign_id: str, *, has_key: bool) -> list[dict[str, Any]]:
        self._require_campaign(campaign_id)
        approved = self.db.facts_approved(campaign_id)
        if approved is None:
            raise ServiceError("facts_not_approved", "Lock the offer facts before generating.", 409)
        facts = OfferFacts.model_validate_json(approved["json"])
        self._ensure_matrix(campaign_id, facts, approved["version"])
        jobs: list[dict[str, Any]] = []
        for asset in self.db.assets_for(campaign_id):
            if asset["content"] and asset["status"] != "changed":
                # Written copy is the owner's to edit or approve. Only a fact change rewrites it.
                continue
            existing = self.db.job_open_for_asset(asset["id"])
            if has_key and existing and existing["status"] == "waiting_for_key":
                self.db.job_update(existing["id"], now(), status="queued", detail="Queued for Agnes.")
                existing = self.db.job_get(existing["id"])
                if existing:
                    jobs.append(existing)
                continue
            if existing:
                continue
            job = self.queue_job(asset, "copy", has_key=has_key)
            if has_key:
                jobs.append(job)
        return jobs

    def queue_changed(self, campaign_id: str, *, has_key: bool) -> list[dict[str, Any]]:
        """Queue a rewrite for every asset a fact change marked as changed."""
        jobs: list[dict[str, Any]] = []
        for asset in self.db.assets_for(campaign_id):
            if asset["status"] != "changed" or self.db.job_open_for_asset(asset["id"]):
                continue
            job = self.queue_job(asset, "copy", has_key=has_key)
            if has_key:
                jobs.append(job)
        return jobs

    def queue_job(
        self,
        asset: dict[str, Any],
        kind: str,
        *,
        has_key: bool,
        payload: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        status = "queued" if has_key else "waiting_for_key"
        if not has_key:
            detail = "Groq Qwen is off or has no key. Text generation is waiting." if kind in ("copy", "brief", "review", "review2", "review3") else "AGNES_API_KEY is not set. Asset slot is waiting."
        job = {
            "id": uuid.uuid4().hex,
            "campaign_id": asset["campaign_id"],
            "asset_id": asset["id"],
            "kind": kind,
            "status": status,
            "detail": detail or "Queued for Agnes.",
            "provider_ref": None,
            "payload": json.dumps(payload) if payload else None,
            "created_at": now(),
            "updated_at": now(),
        }
        self.db.job_insert(job)
        self.db.log(now(), "system", f"{kind}_queued", job["detail"], asset["campaign_id"])
        return job

    def queue_brief(self, campaign_id: str, *, has_key: bool) -> dict[str, Any] | None:
        if not has_key:
            self.db.log(
                now(),
                "system",
                "brief_skipped",
                "AGNES_API_KEY is not set. Fill the offer facts by hand.",
                campaign_id,
            )
            return None
        job = {
            "id": uuid.uuid4().hex,
            "campaign_id": campaign_id,
            "asset_id": None,
            "kind": "brief",
            "status": "queued",
            "detail": "Reading the transcript for offer facts.",
            "provider_ref": None,
            "created_at": now(),
            "updated_at": now(),
        }
        self.db.job_insert(job)
        return job

    def plan_change(self, campaign_id: str, patch: dict[str, Any]) -> tuple[OfferFacts, list[str], list[str]]:
        """Dry run of a fact patch: the merged facts, the fields that really change, and the assets that depend on them."""
        self._require_campaign(campaign_id)
        approved = self.db.facts_approved(campaign_id)
        if approved is None:
            raise ServiceError("facts_not_approved", "Lock offer facts before changing them.", 409)
        current = OfferFacts.model_validate_json(approved["json"])
        unknown = set(patch) - set(OfferFacts.model_fields)
        if unknown:
            raise ServiceError("unknown_field", f"Unknown offer fact fields: {', '.join(sorted(unknown))}.")
        merged = current.model_dump()
        merged.update(patch)
        try:
            updated = OfferFacts.model_validate(merged)
        except ValueError as exc:
            raise ServiceError("invalid_patch", str(exc)) from exc
        changed = [key for key in patch if current.model_dump()[key] != updated.model_dump()[key]]
        previous_fields = set(fields_present(current))
        introduced = [key for key in changed if key not in previous_fields]
        affected: list[str] = []
        if changed:
            for asset in self.db.assets_for(campaign_id):
                if not asset["content"]:
                    # Not written yet. It will be written from the newest locked facts.
                    continue
                used = set(_loads(asset["facts_used"], []))
                stale = not channels.validate_asset(asset["channel"], asset["content"], self._extra(asset), updated).ok
                if stale or used.intersection(changed) or introduced:
                    affected.append(asset["id"])
        return updated, changed, affected

    def apply_change(self, campaign_id: str, text: str, patch: dict[str, Any] | None) -> dict[str, Any]:
        self._require_campaign(campaign_id)
        if self.db.facts_approved(campaign_id) is None:
            raise ServiceError("facts_not_approved", "Lock offer facts before changing them.", 409)
        if not patch:
            self.db.log(now(), "owner", "change_unclassified", text.strip(), campaign_id)
            return self.board(campaign_id)
        updated, changed, affected = self.plan_change(campaign_id, patch)
        if not changed:
            self.db.log(now(), "owner", "change_unclassified", text.strip(), campaign_id)
            return self.board(campaign_id)
        version = self.db.facts_next_version(campaign_id)
        self.db.facts_insert(
            {
                "campaign_id": campaign_id,
                "version": version,
                "json": updated.model_dump_json(),
                "approved": 1,
                "created_at": now(),
            }
        )
        touched = 0
        frozen = 0
        for asset in self.db.assets_for(campaign_id):
            if not asset["content"]:
                continue
            if asset["id"] in affected:
                self.db.asset_update(asset["id"], status="changed", facts_version=version, block_reason=None)
                touched += 1
            else:
                frozen += 1
        self._refresh_status(campaign_id)
        detail = f"{text.strip()} Fields: {', '.join(changed)}. {touched} assets changed, {frozen} left as they were."
        self.db.log(now(), "owner", "change_applied", detail, campaign_id)
        return self.board(campaign_id)

    def apply_scope(
        self,
        campaign_id: str,
        text: str,
        *,
        add_channels: list[str],
        remove_channels: list[str],
        add_languages: list[str],
        remove_languages: list[str],
    ) -> dict[str, Any]:
        """Add or remove channels and languages. New slots are queued by prepare_generation; removed slots are deleted."""
        self._require_campaign(campaign_id)
        approved = self.db.facts_approved(campaign_id)
        if approved is None:
            raise ServiceError("facts_not_approved", "Lock offer facts before changing them.", 409)
        current = OfferFacts.model_validate_json(approved["json"])
        merged = current.model_dump()
        merged["channels"] = [c for c in current.channels if c not in remove_channels] + [
            c for c in add_channels if c not in current.channels
        ]
        merged["languages"] = [x for x in current.languages if x not in remove_languages] + [
            x for x in add_languages if x not in current.languages
        ]
        try:
            updated = OfferFacts.model_validate(merged)
        except ValueError as exc:
            raise ServiceError("invalid_scope", str(exc)) from exc
        if updated == current:
            self.db.log(now(), "owner", "change_unclassified", text.strip(), campaign_id)
            return self.board(campaign_id)
        version = self.db.facts_next_version(campaign_id)
        self.db.facts_insert(
            {
                "campaign_id": campaign_id,
                "version": version,
                "json": updated.model_dump_json(),
                "approved": 1,
                "created_at": now(),
            }
        )
        removed = 0
        for asset in self.db.assets_for(campaign_id):
            if asset["channel"] in updated.channels and asset["lang"] in updated.languages:
                continue
            for job in self.db.jobs_for_campaign(campaign_id, limit=500):
                if job["asset_id"] == asset["id"] and job["status"] in ("queued", "waiting_for_key", "running"):
                    self.db.job_update(job["id"], now(), status="superseded", detail="The asset was removed.")
            self.db.execute("DELETE FROM asset WHERE id = ?", (asset["id"],))
            removed += 1
        self._refresh_status(campaign_id)
        self.db.log(now(), "owner", "scope_changed", f"{text.strip()} {removed} asset slots removed.", campaign_id)
        return self.board(campaign_id)

    def write_content(self, asset_id: str, content: str, *, has_key: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        asset = self._require_asset(asset_id)
        facts_row = self.db.facts_approved(asset["campaign_id"])
        if facts_row is None:
            raise ServiceError("facts_not_approved", "Lock the offer facts before writing copy.", 409)
        facts = OfferFacts.model_validate_json(facts_row["json"])
        extra = self._extra(asset)
        result = channels.validate_asset(asset["channel"], content, extra, facts)
        text = channels.visible_text(asset["channel"], content, extra)
        status = "pending" if result.ok else "blocked"
        kept_terms = [field for field in _loads(asset["facts_used"], []) if field == "terms"]
        needs_review = result.ok and asset["lang"] != "en"
        if needs_review:
            review_status = review.CHECKING if has_key else review.UNAVAILABLE
        else:
            review_status = review.NOT_NEEDED if result.ok else None
        self.db.asset_update(
            asset_id,
            content=content,
            status=status,
            facts_version=facts_row["version"],
            facts_used=json.dumps(facts_in_content(text, facts, kept_terms)),
            block_reason=None if result.ok else json.dumps(result.messages()),
            review=self._review_json(review_status, text),
        )
        self.db.log(
            now(),
            "owner",
            "content_edited" if result.ok else "asset_blocked",
            "Copy saved." if result.ok else "; ".join(result.messages()),
            asset["campaign_id"],
        )
        updated = self.db.asset_get(asset_id)
        if updated is None:
            raise ServiceError("not_found", "Asset was not stored.", 500)
        jobs = []
        if needs_review and has_key:
            jobs.append(
                self.queue_job(
                    updated,
                    "review",
                    has_key=True,
                    payload={"owner_edit": True, "content_hash": review.content_hash(text)},
                    detail="Checking the meaning by back-translation.",
                )
            )
        return self._asset(updated), jobs

    def approve_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self._require_asset(asset_id)
        facts_row = self.db.facts_approved(asset["campaign_id"])
        if facts_row is None:
            raise ServiceError("facts_not_approved", "Lock the offer facts before approving an asset.", 409)
        facts = OfferFacts.model_validate_json(facts_row["json"])
        result = channels.validate_asset(asset["channel"], asset["content"] or "", self._extra(asset), facts)
        if not result.ok:
            self.db.asset_update(
                asset_id,
                status="blocked",
                block_reason=json.dumps(result.messages()),
            )
            self.db.log(now(), "validator", "asset_blocked", "; ".join(result.messages()), asset["campaign_id"])
            raise ServiceError("validation_failed", " ".join(result.messages()), 409)
        meaning = _loads(asset.get("review"), None) or {}
        if meaning.get("status") == review.CHECKING:
            raise ServiceError("meaning_check_running", "The meaning check is still running.", 409)
        if meaning.get("status") == review.FLAGGED:
            raise ServiceError("meaning_check_flagged", " ".join(meaning.get("issues", [])), 409)
        self.db.asset_update(
            asset_id,
            status="approved",
            facts_version=facts_row["version"],
            block_reason=None,
        )
        self.db.log(now(), "owner", "asset_approved", f"{asset['lang']} {asset['channel']} approved.", asset["campaign_id"])
        updated = self.db.asset_get(asset_id)
        if updated is None:
            raise ServiceError("not_found", "Asset was not stored.", 500)
        return self._asset(updated)

    def store_copy(
        self,
        asset_id: str,
        content: str,
        result: ValidationResult,
        facts: OfferFacts,
        facts_version: int,
        declared: list[str],
        *,
        review_status: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        asset = self._require_asset(asset_id)
        status = "pending" if result.ok else "blocked"
        extra = extra or {}
        text = channels.visible_text(asset["channel"], content, extra)
        self.db.execute("UPDATE asset SET extra = ? WHERE id = ?", (json.dumps(extra, ensure_ascii=False), asset_id))
        self.db.asset_update(
            asset_id,
            content=content,
            status=status,
            facts_version=facts_version,
            facts_used=json.dumps(facts_in_content(text, facts, declared)),
            review=self._review_json(review_status, text),
            block_reason=None if result.ok else json.dumps(result.messages()),
        )
        self.db.log(
            now(),
            "system",
            "copy_finished" if result.ok else "asset_blocked",
            "Copy ready for review." if result.ok else "; ".join(result.messages()),
            asset["campaign_id"],
        )

    def store_review(self, asset_id: str, outcome: dict[str, Any]) -> bool:
        """Store a meaning check. Returns False when the copy changed after the check started."""
        asset = self._require_asset(asset_id)
        if review.content_hash(self.asset_text(asset)) != outcome.get("content_hash"):
            return False
        fields: dict[str, Any] = {"review": json.dumps(outcome, ensure_ascii=False)}
        if outcome["status"] == review.FLAGGED:
            fields.update(status="blocked", block_reason=json.dumps(outcome["issues"], ensure_ascii=False))
        self.db.asset_update(asset_id, **fields)
        action = {review.OK: "meaning_ok", review.FLAGGED: "meaning_flagged"}.get(outcome["status"], "meaning_unchecked")
        detail = "; ".join(outcome.get("issues") or []) or "Back-translation matches the locked offer."
        self.db.log(now(), "reviewer", action, f"{asset['lang']} {asset['channel']}: {detail}", asset["campaign_id"])
        return True

    @staticmethod
    def _extra(asset: dict[str, Any]) -> dict[str, Any]:
        return _loads(asset.get("extra"), {})

    def asset_text(self, asset: dict[str, Any]) -> str:
        """All customer-visible text of an asset row: extra fields (subject, title, headline, hashtags) and body."""
        return channels.visible_text(asset["channel"], asset["content"] or "", self._extra(asset))

    @staticmethod
    def _review_json(status: str | None, content: str) -> str | None:
        if status is None:
            return None
        return json.dumps({"status": status, "content_hash": review.content_hash(content)})

    def store_suggestion(self, campaign_id: str, suggestion: dict[str, Any]) -> None:
        if self.db.facts_approved(campaign_id):
            self.db.log(now(), "system", "brief_skipped", "Offer facts were already locked.", campaign_id)
            return
        self.db.campaign_set(campaign_id, suggestion=json.dumps(suggestion, ensure_ascii=False))
        self.db.log(now(), "system", "brief_ready", "Suggested facts are not locked. Review them before approval.", campaign_id)

    def board(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._require_campaign(campaign_id)
        approved = self.db.facts_approved(campaign_id)
        latest = self.db.facts_latest(campaign_id)
        draft = latest if latest and not latest["approved"] else None
        return {
            "campaign": self._campaign(campaign),
            "facts": self._facts(approved),
            "draft": self._facts(draft),
            "assets": [self._asset(row) for row in self.db.assets_for(campaign_id)],
            "events": self.db.events(campaign_id),
            "jobs": self.db.jobs_for_campaign(campaign_id),
        }

    def _ensure_matrix(self, campaign_id: str, facts: OfferFacts, version: int) -> None:
        """One slot per channel and language. Audiences are prompt context, so the audience column is a constant."""
        created = 0
        for lang in facts.languages:
            for channel in facts.channels:
                if self.db.asset_find(campaign_id, ALL_AUDIENCES, lang, channel):
                    continue
                self.db.asset_insert(
                    {
                        "id": uuid.uuid4().hex,
                        "campaign_id": campaign_id,
                        "audience": ALL_AUDIENCES,
                        "lang": lang,
                        "channel": channel,
                        "type": "reel" if channel == "reel" else "copy" if channel != "poster" else "poster",
                        "content": None,
                        "facts_used": "[]",
                        "facts_version": version,
                        "status": "pending",
                        "block_reason": None,
                        "score": None,
                        "score_detail": None,
                        "created_at": now(),
                    }
                )
                created += 1
        if created:
            self.db.log(now(), "system", "matrix_built", f"{created} asset slots added.", campaign_id)

    def _refresh_status(self, campaign_id: str) -> None:
        status = "facts_locked" if self.db.facts_approved(campaign_id) else "draft"
        self.db.campaign_set(campaign_id, status=status)

    def _require_campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.db.campaign_get(campaign_id)
        if campaign is None:
            raise ServiceError("not_found", "No campaign with that id.", 404)
        return campaign

    def _require_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self.db.asset_get(asset_id)
        if asset is None:
            raise ServiceError("not_found", "No asset with that id.", 404)
        return asset

    def _campaign(self, row: dict[str, Any]) -> dict[str, Any]:
        suggestion = _loads(row.get("suggestion"), None)
        return {
            "id": row["id"],
            "brand_voice": row["brand_voice"],
            "status": row["status"],
            "transcript": row["transcript"],
            "suggestion": suggestion,
            "created_at": row["created_at"],
        }

    def _facts(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "version": row["version"],
            "approved": bool(row["approved"]),
            "facts": json.loads(row["json"]),
            "created_at": row["created_at"],
        }

    def _asset(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "audience": row["audience"],
            "lang": row["lang"],
            "channel": row["channel"],
            "type": row["type"],
            "content": row["content"],
            "extra": _loads(row.get("extra"), {}),
            "facts_used": _loads(row["facts_used"], []),
            "facts_version": row["facts_version"],
            "status": row["status"],
            "block_reason": _loads(row["block_reason"], []),
            "score": row["score"],
            "review": _loads(row.get("review"), None),
            "created_at": row["created_at"],
        }
