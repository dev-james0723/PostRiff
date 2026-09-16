"""Owner-local handoff tasks. No channel transport, credentials or network IO.

All due-task checks and lease fencing use the same SQLite write transaction.
Receipts authorize a local task only; links supplied by users remain unverified.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .studio import (DRAFT_DEFAULTS, ID_PATTERN, MAX_ASSET_BYTES, StudioError, _hash, _integer,
                     _json, _now, _read_owned, _text, _timestamp)

LEASE_SECONDS = 15
CAPABILITIES = {"manualHandoff": True, "automaticPublishing": False, "nativeScheduling": False}
REVIEW_INPUT = {"draftId", "expectedRevision", "channel", "accountLabel", "destinationLabel", "audience",
                "scheduledLocal", "timezone", "fold", "windowMinutes", "deliveryMethod", "derivatives"}
REVIEW_KEYS = {"id", "draftId", "draftRevision", "manifestHash", "manifest", "createdAt"}
JOB_KEYS = {"id", "reviewId", "draftId", "channel", "title", "state", "scheduledUtc", "scheduledLocal", "timezone",
            "deadlineUtc", "createdAt", "updatedAt", "reason", "permalink", "verificationState"}
RECEIPT_KEYS = {"id", "reviewId", "jobId", "manifestHash", "draftRevision", "scope", "authority", "approvedAt", "revokedAt", "revocationReason"}
WORKER_KEYS = {"paused", "heartbeatAt", "owner", "generation", "leaseUntil"}
JOB_STATES = {"queued_local", "human_action_needed", "needs_review", "cancelled", "user_reported"}
PENDING_STATES = {"queued_local", "human_action_needed"}
REASONS = {
    "queued": "Queued locally for a manual handoff task. No external post is scheduled.",
    "due": "Human action needed. Review the manual package; nothing has been published.",
    "expired": "The handoff deadline passed. Prepare and acknowledge a fresh review; no automatic catch-up.",
    "changed": "The bound draft, template or media changed. Prepare and acknowledge a fresh review.",
    "revoked": "The local-task receipt was revoked. A fresh review is required.",
    "restored": "Restored task requires a fresh review and acknowledgment; delivery remains paused.",
    "cancelled": "Local task cancelled. No external action was performed.",
    "cancelled_after_handoff": "Local task cancelled. This cannot recall content already copied, downloaded or manually published.",
    "reported": "User reported a permalink. It was not fetched or independently verified.",
}


def _utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        _timestamp(now, "now")
        now = datetime.fromisoformat(now)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise StudioError("invalid_delivery_time", "Use an explicit timezone-aware time.", 422)
    return now.astimezone(timezone.utc)


def _id(value, field="id"):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise StudioError("invalid_" + field, status=422)
    return value


def _digest(value):
    return _hash(_json(value).encode())


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise StudioError("invalid_manifest_hash", status=422)
    return value


def _owner(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise StudioError("invalid_worker_owner", status=422)
    return value


def _schedule(local, zone_name, fold, window):
    _text(local, "scheduledLocal", 32, True)
    _text(zone_name, "timezone", 100, True)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", local):
        raise StudioError("invalid_scheduled_local", "Use a naive ISO local date and time.", 422)
    if fold is not None and (type(fold) is not int or fold not in (0, 1)):
        raise StudioError("invalid_dst_fold", status=422)
    if type(window) is not int or not 1 <= window <= 1440:
        raise StudioError("invalid_delivery_window", "The local handoff window must be between 1 and 1440 minutes.", 422)
    try:
        naive = datetime.fromisoformat(local)
        zone = ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError):
        raise StudioError("invalid_scheduled_local", "Choose a valid local time and IANA timezone.", 422) from None
    valid = {}
    for choice in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=choice)
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
            valid[choice] = candidate
    if not valid:
        raise StudioError("nonexistent_local_time", "This local time does not exist because of a clock change.", 422)
    if len({item.utcoffset() for item in valid.values()}) > 1 and fold is None:
        raise StudioError("ambiguous_local_time", "Choose the first or second occurrence of this repeated local time.", 422)
    due = valid[0 if fold is None else fold].astimezone(timezone.utc)
    try:
        deadline = due + timedelta(minutes=window)
    except OverflowError:
        raise StudioError("invalid_delivery_window", status=422) from None
    return _utc(due), _utc(deadline)


def _permalink(value):
    _text(value, "permalink", 2048, True)
    if any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in value) or "\\" in value:
        raise StudioError("invalid_permalink", status=422)
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        parsed.port
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=50):
            if key.lower() in {"access_token", "token", "password", "api_key", "code", "secret", "client_secret", "refresh_token"}:
                raise ValueError()
    except ValueError:
        raise StudioError("invalid_permalink", "Supply an HTTPS permalink without embedded credentials or secret query fields. The URL will not be fetched.", 422) from None
    return value


def _worker(db):
    return json.loads(db.execute("SELECT data FROM studio_delivery_worker WHERE id=1").fetchone()[0])


def _public_worker(worker):
    return {key: worker[key] for key in ("paused", "heartbeatAt", "owner", "generation")}


def _save_worker(db, worker):
    db.execute("UPDATE studio_delivery_worker SET data=? WHERE id=1", (_json(worker),))


def _save_job(db, job):
    db.execute("UPDATE studio_delivery_jobs SET data=? WHERE id=?", (_json(job), job["id"]))


def _revoke(db, receipt, when, reason):
    if receipt["revokedAt"] is None:
        receipt.update(revokedAt=when, revocationReason=reason)
        db.execute("UPDATE studio_delivery_receipts SET data=? WHERE id=?", (_json(receipt), receipt["id"]))


class DeliveryService:
    def __init__(self, store):
        self.store = store

    def status(self):
        with self.store.connection() as db:
            reviews = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_delivery_reviews")]
            jobs = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_delivery_jobs")]
            worker = _public_worker(_worker(db))
        return {"reviews": sorted(reviews, key=lambda item: item["createdAt"], reverse=True),
                "jobs": sorted(jobs, key=lambda item: item["createdAt"], reverse=True), "worker": worker, "capabilities": dict(CAPABILITIES)}

    def _review(self, db, review_id):
        _id(review_id, "review_id")
        row = db.execute("SELECT data FROM studio_delivery_reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            raise StudioError("delivery_review_not_found", status=404)
        return json.loads(row[0])

    def _job(self, db, job_id):
        _id(job_id, "job_id")
        row = db.execute("SELECT data FROM studio_delivery_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise StudioError("delivery_job_not_found", status=404)
        return json.loads(row[0])

    def _receipt(self, db, job_id):
        row = db.execute("SELECT data FROM studio_delivery_receipts WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise StudioError("delivery_receipt_missing", status=409)
        return json.loads(row[0])

    def get_receipt(self, job_id):
        _id(job_id, "job_id")
        with self.store.connection() as db:
            return self._receipt(db, job_id)

    def _manifest(self, db, payload, draft, verify_files=True):
        if not isinstance(payload, dict) or set(payload) != REVIEW_INPUT:
            raise StudioError("invalid_delivery_fields", "Only the displayed local delivery fields may be supplied.", 422)
        _id(payload["draftId"], "draftId")
        _integer(payload["expectedRevision"], "expectedRevision")
        if payload["deliveryMethod"] != "assisted_handoff":
            raise StudioError("route_not_qualified", "Only a local assisted handoff is qualified. No automatic publishing or native scheduling route is active.", 422)
        if payload["derivatives"] != "none":
            raise StudioError("separate_derivative_review_required", "Additional native formats need separate drafts and local reviews.", 422)
        channel = _text(payload["channel"], "channel", 100, True)
        if draft["archived"] or draft["id"] != payload["draftId"] or draft["revision"] != payload["expectedRevision"]:
            raise StudioError("delivery_draft_stale", "Reload the current non-archived draft and prepare a fresh review.", 409)
        if channel not in draft["channels"]:
            raise StudioError("delivery_channel_not_selected", status=422)
        for key in ("copies", "languages", "formats"):
            _text(draft[key].get(channel, ""), key, 100000, True)
        for key in ("accountLabel", "destinationLabel", "audience"):
            _text(payload[key], key, 300, True)
        due, deadline = _schedule(payload["scheduledLocal"], payload["timezone"], payload["fold"], payload["windowMinutes"])
        assets = []
        for asset_id in draft["assetIds"]:
            row = db.execute("SELECT data FROM studio_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                raise StudioError("delivery_asset_changed", status=409)
            asset = json.loads(row[0])
            if verify_files:
                data = _read_owned(self.store._asset_path(asset), MAX_ASSET_BYTES)
                if len(data) != asset["size"] or _hash(data) != asset["sha256"]:
                    raise StudioError("delivery_asset_changed", status=409)
            assets.append(asset)
        template = None
        if draft["templateId"]:
            row = db.execute("SELECT data FROM studio_templates WHERE id=? AND version=?", (draft["templateId"], draft["templateVersion"])).fetchone()
            if not row:
                raise StudioError("delivery_template_changed", status=409)
            template = json.loads(row[0])
            if template["hash"] != _digest({key: value for key, value in template.items() if key != "hash"}):
                raise StudioError("delivery_template_changed", status=409)
        manifest = {"version": 1, "scope": "local_handoff_only", "publicationAuthority": False, "remoteScheduling": False,
            "identityState": "unverified", "draftId": draft["id"], "draftRevision": draft["revision"], "title": draft["title"],
            "source": draft["source"], "angle": draft["angle"], "channel": channel, "nativeFormat": draft["formats"][channel],
            "language": draft["languages"][channel], "copy": draft["copies"][channel], "assets": assets, "template": template,
            "visualRef": draft["visualRef"], "accountLabel": payload["accountLabel"], "destinationLabel": payload["destinationLabel"],
            "audience": payload["audience"], "scheduledLocal": payload["scheduledLocal"], "scheduledUtc": due, "deadlineUtc": deadline,
            "timezone": payload["timezone"], "fold": payload["fold"], "windowMinutes": payload["windowMinutes"],
            "deliveryMethod": "assisted_handoff", "derivatives": "none"}
        if len(_json(manifest).encode()) > 2 * 1024 * 1024:
            raise StudioError("delivery_manifest_too_large", status=413)
        return manifest

    @staticmethod
    def _payload(manifest):
        return {key: manifest[{"expectedRevision": "draftRevision"}.get(key, key)] for key in REVIEW_INPUT}

    def _current(self, db, review):
        draft = self.store._draft(db, review["draftId"])
        manifest = self._manifest(db, self._payload(review["manifest"]), draft)
        if manifest != review["manifest"] or _digest(manifest) != review["manifestHash"]:
            raise StudioError("delivery_input_changed", "The reviewed draft, media or template changed. A fresh review is required.", 409)

    def prepare_review(self, payload, now=None):
        when = _utc(_time(now))
        if not isinstance(payload, dict) or set(payload) != REVIEW_INPUT:
            raise StudioError("invalid_delivery_fields", status=422)
        _id(payload["draftId"], "draftId")
        with self.store.connection(write=True) as db:
            manifest = self._manifest(db, payload, self.store._draft(db, payload["draftId"]))
            digest = _digest(manifest)
            # Exact active/unacknowledged reviews are idempotent. A distinct
            # owner preparation after cancellation/restore may renew the same
            # unchanged manifest; it never revives an old receipt or job.
            for existing in db.execute("SELECT id,data FROM studio_delivery_reviews WHERE manifest_hash=? ORDER BY rowid DESC", (digest,)).fetchall():
                job = db.execute("SELECT data FROM studio_delivery_jobs WHERE review_id=?", (existing[0],)).fetchone()
                if job is None or json.loads(job[0])["state"] not in {"cancelled", "needs_review"}:
                    return json.loads(existing[1])
            review = {"id": uuid.uuid4().hex, "draftId": payload["draftId"], "draftRevision": payload["expectedRevision"],
                      "manifestHash": digest, "manifest": manifest, "createdAt": when}
            db.execute("INSERT INTO studio_delivery_reviews VALUES (?,?,?)", (review["id"], digest, _json(review)))
            self.store._activity(db, "delivery_review_prepared", review["id"], "Local handoff review prepared; no approval or publication")
        return review

    def approve(self, review_id, manifest_hash, expected_revision, now=None):
        _sha(manifest_hash)
        _integer(expected_revision, "expectedRevision")
        with self.store.connection(write=True) as db:
            review = self._review(db, review_id)
            if review["manifestHash"] != manifest_hash or review["draftRevision"] != expected_revision:
                raise StudioError("delivery_acknowledgment_mismatch", "Acknowledge only the exact displayed manifest hash and revision.", 409)
            self._current(db, review)
            when = _utc(_time(now))  # sample after the lock wait and media checks
            existing = db.execute("SELECT data FROM studio_delivery_jobs WHERE review_id=?", (review_id,)).fetchone()
            if existing:
                return json.loads(existing[0])
            for row in db.execute("SELECT j.data FROM studio_delivery_jobs j JOIN studio_delivery_reviews r ON j.review_id=r.id WHERE r.manifest_hash=?", (manifest_hash,)):
                if json.loads(row[0])["state"] not in {"cancelled", "needs_review"}:
                    raise StudioError("duplicate_local_handoff", "This exact manifest already has an active or user-reported local task.", 409)
            manifest = review["manifest"]
            if when > manifest["deadlineUtc"]:
                raise StudioError("delivery_window_expired", "Choose and review a new handoff window.", 409)
            job_id, receipt_id = uuid.uuid4().hex, uuid.uuid4().hex
            receipt = {"id": receipt_id, "reviewId": review_id, "jobId": job_id, "manifestHash": manifest_hash,
                       "draftRevision": expected_revision, "scope": "local_handoff_only", "authority": "local_owner_session",
                       "approvedAt": when, "revokedAt": None, "revocationReason": ""}
            job = {"id": job_id, "reviewId": review_id, "draftId": review["draftId"], "channel": manifest["channel"], "title": manifest["title"],
                   "state": "queued_local", "scheduledUtc": manifest["scheduledUtc"], "scheduledLocal": manifest["scheduledLocal"],
                   "timezone": manifest["timezone"], "deadlineUtc": manifest["deadlineUtc"], "createdAt": when, "updatedAt": when,
                   "reason": REASONS["queued"], "permalink": "", "verificationState": "unverified"}
            db.execute("INSERT INTO studio_delivery_receipts VALUES (?,?,?,?)", (receipt_id, review_id, job_id, _json(receipt)))
            db.execute("INSERT INTO studio_delivery_jobs VALUES (?,?,?,?)", (job_id, review_id, receipt_id, _json(job)))
            self.store._activity(db, "delivery_local_task_acknowledged", job_id, "Owner acknowledged an exact local handoff task; not publication approval")
        return job

    def _invalidate(self, db, job, when, reason):
        job.update(state="needs_review", reason=REASONS[reason], updatedAt=when)
        _save_job(db, job)
        _revoke(db, self._receipt(db, job["id"]), when, reason)

    def _valid_job(self, db, job, when, check_deadline=True):
        receipt = self._receipt(db, job["id"])
        if receipt["revokedAt"] is not None:
            return "revoked"
        try:
            review = self._review(db, job["reviewId"])
            if (receipt["manifestHash"] != review["manifestHash"] or receipt["scope"] != "local_handoff_only"
                    or receipt["authority"] != "local_owner_session" or receipt["draftRevision"] != review["draftRevision"]):
                return "revoked"
            self._current(db, review)
        except StudioError:
            return "changed"
        if check_deadline and when > job["deadlineUtc"]:
            return "expired"
        return None

    def cancel(self, job_id, now=None):
        when = _utc(_time(now))
        with self.store.connection(write=True) as db:
            job = self._job(db, job_id)
            if job["state"] == "cancelled":
                return job
            reason = "cancelled_after_handoff" if job["state"] in {"human_action_needed", "user_reported", "needs_review"} else "cancelled"
            job.update(state="cancelled", reason=REASONS[reason], updatedAt=when)
            _save_job(db, job)
            _revoke(db, self._receipt(db, job_id), when, "cancelled")
            self.store._activity(db, "delivery_cancelled", job_id, REASONS[reason])
        return job

    def control(self, paused, now=None):
        if type(paused) is not bool:
            raise StudioError("invalid_delivery_pause", status=422)
        with self.store.connection(write=True) as db:
            worker = _worker(db)
            worker["paused"] = paused
            _save_worker(db, worker)
            self.store._activity(db, "delivery_paused" if paused else "delivery_resumed", "local-worker", "Local manual-task progression paused" if paused else "Local manual-task progression resumed; no external transport")
            return _public_worker(worker)

    def tick(self, owner, now=None):
        _owner(owner)
        with self.store.connection(write=True) as db:
            moment = _time(now)  # a blocked SQLite acquisition must not use stale time
            when = _utc(moment)
            worker = _worker(db)
            if worker["heartbeatAt"] is not None and when < worker["heartbeatAt"]:
                return {"worker": _public_worker(worker), "acquired": False, "promoted": []}
            if worker["owner"] and worker["leaseUntil"] <= when:
                db.execute("UPDATE studio_delivery_lease_owners SET retired=1 WHERE owner=?", (worker["owner"],))
                worker.update(owner=None, leaseUntil=None)
                _save_worker(db, worker)
            old = db.execute("SELECT generation,retired FROM studio_delivery_lease_owners WHERE owner=?", (owner,)).fetchone()
            if old and old[1] or worker["owner"] not in (None, owner):
                return {"worker": _public_worker(worker), "acquired": False, "promoted": []}
            if worker["owner"] is None:
                if old:
                    return {"worker": _public_worker(worker), "acquired": False, "promoted": []}
                worker.update(owner=owner, generation=worker["generation"] + 1)
                db.execute("INSERT INTO studio_delivery_lease_owners VALUES (?,?,0)", (owner, worker["generation"]))
            worker.update(heartbeatAt=when, leaseUntil=_utc(moment + timedelta(seconds=LEASE_SECONDS)))
            _save_worker(db, worker)
            promoted = []
            for row in db.execute("SELECT data FROM studio_delivery_jobs").fetchall():
                job = json.loads(row[0])
                if job["state"] not in PENDING_STATES:
                    continue
                when = _utc(_time(now))
                invalid = self._valid_job(db, job, when)
                when = _utc(_time(now))
                if worker["leaseUntil"] <= when:
                    db.execute("UPDATE studio_delivery_lease_owners SET retired=1 WHERE owner=?", (owner,))
                    worker.update(owner=None, leaseUntil=None)
                    _save_worker(db, worker)
                    return {"worker": _public_worker(worker), "acquired": False, "promoted": promoted}
                if not invalid and when > job["deadlineUtc"]:
                    invalid = "expired"
                if invalid:
                    self._invalidate(db, job, when, invalid)
                elif job["state"] == "queued_local" and not worker["paused"] and when >= job["scheduledUtc"]:
                    job.update(state="human_action_needed", reason=REASONS["due"], updatedAt=when)
                    _save_job(db, job)
                    promoted.append(job["id"])
                    self.store._activity(db, "delivery_human_action_needed", job["id"], "Local task is due; no post or notification was sent")
            return {"worker": _public_worker(worker), "acquired": True, "promoted": promoted}

    def release(self, owner, now=None):
        _owner(owner)
        with self.store.connection(write=True) as db:
            worker = _worker(db)
            if worker["owner"] == owner:
                db.execute("UPDATE studio_delivery_lease_owners SET retired=1 WHERE owner=?", (owner,))
                worker.update(owner=None, leaseUntil=None)
                _save_worker(db, worker)
            return _public_worker(worker)

    def report(self, job_id, permalink, now=None):
        _permalink(permalink)
        error = None
        with self.store.connection(write=True) as db:
            when = _utc(_time(now))
            job = self._job(db, job_id)
            if job["state"] == "user_reported" and job["permalink"] == permalink:
                return job
            if job["state"] != "human_action_needed":
                raise StudioError("handoff_not_available", "Only an active due manual handoff can receive a user report.", 409)
            error = self._valid_job(db, job, when)
            when = _utc(_time(now))
            if not error and when > job["deadlineUtc"]:
                error = "expired"
            if error:
                self._invalidate(db, job, when, error)
            elif _worker(db)["paused"]:
                raise StudioError("delivery_paused", "Resume local handoff tasks before recording this report.", 409)
            else:
                job.update(state="user_reported", permalink=permalink, verificationState="unverified", reason=REASONS["reported"], updatedAt=when)
                _save_job(db, job)
                self.store._activity(db, "delivery_user_reported", job_id, "Owner supplied a permalink; no fetch or independent verification")
        if error:
            raise StudioError("handoff_invalidated", REASONS[error], 409)
        return job

    def package(self, job_id, now=None):
        error = None
        with self.store.connection() as db:
            db.execute("BEGIN")  # Read-only coherent snapshot; GET never revokes a receipt.
            when = _utc(_time(now))
            job = self._job(db, job_id)
            if job["state"] not in {"human_action_needed", "user_reported"}:
                raise StudioError("handoff_not_available", "This job has no current manual handoff package.", 409)
            error = self._valid_job(db, job, when, check_deadline=job["state"] != "user_reported")
            if not error and job["state"] != "user_reported" and _utc(_time(now)) > job["deadlineUtc"]:
                error = "expired"
            if not error and _worker(db)["paused"]:
                raise StudioError("delivery_paused", "Local handoff is paused; no package can be exported.", 409)
            elif not error:
                review = self._review(db, job["reviewId"])
                receipt = self._receipt(db, job_id)
                manifest = review["manifest"]
                lines = ["# Manual handoff package", "", "Local handoff only — not publication approval or a remote schedule.",
                    "Account/destination labels and user-reported links are unverified. Check facts, rights, identity, native format and destination yourself.", "",
                    "## Reviewed copy", "", manifest["copy"], "", "## Exact frozen manifest", "", "```json", _json(manifest), "```", "",
                    "## Local-task receipt", "", "```json", _json(receipt), "```", "", f"Manifest SHA-256: {review['manifestHash']}",
                    f"User-reported permalink (not fetched): {job['permalink'] or 'None'}", "",
                    "Cancellation cannot recall content already copied, downloaded or manually published.", ""]
                result = "\n".join(lines)
        if error:
            raise StudioError("handoff_invalidated", REASONS[error], 409)
        return result


def validate_delivery_records(store, db):
    """Reject malformed or rebound local-task history before restoring a backup."""
    service = DeliveryService(store)
    reviews, jobs, receipts = {}, {}, {}
    for row in db.execute("SELECT id,manifest_hash,data FROM studio_delivery_reviews"):
        review = json.loads(row[2])
        if not isinstance(review, dict) or set(review) != REVIEW_KEYS or review["id"] != row[0] or review["manifestHash"] != row[1]:
            raise StudioError("invalid_backup_delivery_review")
        _id(review["id"])
        _id(review["draftId"])
        _integer(review["draftRevision"], "draftRevision")
        _timestamp(review["createdAt"], "createdAt")
        original = db.execute("SELECT data FROM studio_draft_versions WHERE id=? AND revision=?", (review["draftId"], review["draftRevision"])).fetchone()
        if not original:
            raise StudioError("backup_delivery_draft_missing")
        expected = service._manifest(db, service._payload(review["manifest"]), json.loads(original[0]), verify_files=False)
        if review["manifest"] != expected or review["manifestHash"] != _digest(expected):
            raise StudioError("backup_delivery_manifest_mismatch")
        reviews[review["id"]] = review
    for row in db.execute("SELECT id,review_id,job_id,data FROM studio_delivery_receipts"):
        receipt = json.loads(row[3])
        if (not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS or receipt["id"] != row[0]
                or receipt["reviewId"] != row[1] or receipt["jobId"] != row[2] or receipt["reviewId"] not in reviews):
            raise StudioError("invalid_backup_delivery_receipt")
        _id(receipt["id"])
        _id(receipt["jobId"])
        _timestamp(receipt["approvedAt"], "approvedAt")
        review = reviews[receipt["reviewId"]]
        if (receipt["scope"] != "local_handoff_only" or receipt["authority"] != "local_owner_session"
                or receipt["manifestHash"] != review["manifestHash"] or receipt["draftRevision"] != review["draftRevision"]
                or receipt["approvedAt"] < review["createdAt"] or receipt["approvedAt"] > review["manifest"]["deadlineUtc"]):
            raise StudioError("backup_delivery_receipt_scope")
        if receipt["revokedAt"] is None:
            if receipt["revocationReason"] != "":
                raise StudioError("backup_delivery_revocation_invalid")
        else:
            _timestamp(receipt["revokedAt"], "revokedAt")
            if receipt["revokedAt"] < receipt["approvedAt"] or receipt["revocationReason"] not in {"cancelled", "changed", "expired", "revoked", "restored"}:
                raise StudioError("backup_delivery_revocation_invalid")
        receipts[receipt["id"]] = receipt
    active_manifests = set()
    for row in db.execute("SELECT id,review_id,receipt_id,data FROM studio_delivery_jobs"):
        job = json.loads(row[3])
        if (not isinstance(job, dict) or set(job) != JOB_KEYS or job["id"] != row[0] or job["reviewId"] != row[1]
                or row[1] not in reviews or row[2] not in receipts or job["state"] not in JOB_STATES or job["verificationState"] != "unverified"):
            raise StudioError("invalid_backup_delivery_job")
        _id(job["id"])
        review, receipt = reviews[row[1]], receipts[row[2]]
        manifest = review["manifest"]
        if (receipt["jobId"] != job["id"] or receipt["reviewId"] != review["id"]
                or any(job[key] != manifest[key] for key in ("draftId", "channel", "title", "scheduledUtc", "scheduledLocal", "timezone", "deadlineUtc"))
                or job["createdAt"] != receipt["approvedAt"]):
            raise StudioError("backup_delivery_job_binding")
        _timestamp(job["createdAt"], "createdAt")
        _timestamp(job["updatedAt"], "updatedAt")
        if job["updatedAt"] < job["createdAt"] or job["reason"] not in REASONS.values():
            raise StudioError("backup_delivery_job_timestamp")
        if job["permalink"]:
            _permalink(job["permalink"])
            if job["state"] not in {"user_reported", "cancelled"}:
                raise StudioError("backup_delivery_report_state")
        elif job["permalink"] != "" or job["state"] == "user_reported":
            raise StudioError("backup_delivery_report_missing")
        if job["state"] in PENDING_STATES | {"user_reported"} and receipt["revokedAt"] is not None or job["state"] in {"cancelled", "needs_review"} and receipt["revokedAt"] is None:
            raise StudioError("backup_delivery_receipt_state")
        if job["state"] == "human_action_needed" and not job["scheduledUtc"] <= job["updatedAt"] <= job["deadlineUtc"]:
            raise StudioError("backup_delivery_due_state")
        if job["state"] not in {"cancelled", "needs_review"}:
            if review["manifestHash"] in active_manifests:
                raise StudioError("backup_duplicate_active_handoff")
            active_manifests.add(review["manifestHash"])
        jobs[job["id"]] = job
    if {receipt["jobId"] for receipt in receipts.values()} != set(jobs):
        raise StudioError("backup_delivery_orphan_receipt")
    worker_rows = db.execute("SELECT id,data FROM studio_delivery_worker").fetchall()
    if len(worker_rows) != 1 or worker_rows[0][0] != 1:
        raise StudioError("invalid_backup_delivery_worker")
    worker = json.loads(worker_rows[0][1])
    if (not isinstance(worker, dict) or set(worker) != WORKER_KEYS or type(worker["paused"]) is not bool
            or type(worker["generation"]) is not int or not 0 <= worker["generation"] <= 2**31-1):
        raise StudioError("invalid_backup_delivery_worker")
    owners = {}
    for owner, generation, retired in db.execute("SELECT owner,generation,retired FROM studio_delivery_lease_owners"):
        _owner(owner)
        _integer(generation, "generation")
        if retired not in (0, 1):
            raise StudioError("invalid_backup_delivery_lease")
        owners[owner] = (generation, retired)
    generations = sorted(record[0] for record in owners.values())
    if len(generations) != worker["generation"] or any(generation != index for index, generation in enumerate(generations, 1)):
        raise StudioError("backup_delivery_lease_generation")
    if worker["heartbeatAt"] is not None:
        _timestamp(worker["heartbeatAt"], "heartbeatAt")
    if worker["owner"] is None:
        if worker["leaseUntil"] is not None or any(not record[1] for record in owners.values()):
            raise StudioError("backup_delivery_lease_owner")
    else:
        _owner(worker["owner"])
        _timestamp(worker["leaseUntil"], "leaseUntil")
        if (worker["heartbeatAt"] is None or worker["leaseUntil"] != _utc(_time(worker["heartbeatAt"]) + timedelta(seconds=LEASE_SECONDS))
                or owners.get(worker["owner"]) != (worker["generation"], 0)
                or any(not record[1] for owner, record in owners.items() if owner != worker["owner"])):
            raise StudioError("backup_delivery_lease_owner")


def restore_delivery_records(db):
    """Restore never silently revives a task receipt or a worker lease."""
    when = _now()
    worker = _worker(db)
    worker.update(paused=True, owner=None, heartbeatAt=None, leaseUntil=None)
    _save_worker(db, worker)
    db.execute("UPDATE studio_delivery_lease_owners SET retired=1")
    for row in db.execute("SELECT data FROM studio_delivery_jobs").fetchall():
        job = json.loads(row[0])
        if job["state"] in PENDING_STATES:
            # Future-dated test/import metadata must remain time-consistent.
            changed_at = max(when, job["updatedAt"])
            job.update(state="needs_review", reason=REASONS["restored"], updatedAt=changed_at)
            _save_job(db, job)
            receipt = json.loads(db.execute("SELECT data FROM studio_delivery_receipts WHERE job_id=?", (job["id"],)).fetchone()[0])
            _revoke(db, receipt, changed_at, "restored")
