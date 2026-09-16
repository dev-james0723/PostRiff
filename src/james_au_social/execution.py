"""Durable local V14 approval/job/reconciliation primitives.

No transport lives here. A caller must supply an independently reviewed driver;
begin() records the uncertain side-effect boundary BEFORE invoking it. A crashed
submitting job retains its account lock until reconciliation or explicit recovery.
Receipt hashes detect drift, not identity forgery: issue_approval is an operator
boundary and must only be called after the human/credential broker authenticates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def wire(value) -> str:
    # This release accepts the integer subset of JCS. Decimal costs use minor
    # units; refusing unsupported numbers is safer than a noncanonical hash.
    def check(v):
        if v is None or isinstance(v, (bool, str)):
            return
        if isinstance(v, int) and abs(v) <= 9007199254740991:
            return
        if isinstance(v, list):
            for child in v:
                check(child)
            return
        if isinstance(v, dict) and all(isinstance(k, str) and k.isascii() for k in v):
            for child in v.values():
                check(child)
            return
        raise ValueError("unsupported_canonical_value")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_hash(value: dict) -> str:
    return "sha256:" + hashlib.sha256(wire(value).encode("utf-8")).hexdigest()


def issue_approval(approval_id, jobs, *, user_session_ref, approved_at, expires_at):
    if not approval_id or not user_session_ref or instant(expires_at) <= instant(approved_at):
        raise ValueError("invalid_approval")
    if not jobs or len({j for j, _ in jobs}) != len(jobs):
        raise ValueError("invalid_approval_jobs")
    receipt = {"record_type": "ApprovalReceipt", "schema_version": "suite.approval/1",
               "approval_id": approval_id, "approved_by": "user",
               "approver_session_ref": user_session_ref, "approved_at": approved_at,
               "expires_at": expires_at,
               "approved_jobs": [{"job_id": j, "content_hash": payload_hash(p)} for j, p in jobs]}
    receipt["receipt_hash"] = payload_hash(receipt)
    return receipt


ROUTE_KEYS = ("channel", "account_ref", "destination_ref", "native_format_id", "route",
              "route_driver", "auth_generation", "adapter_version", "platform_rules_version",
              "format_constraints_version", "authorization_subject", "required_scope_fingerprint",
              "browser_checkpoint_version", "instance_ref")
REQUIRED = set(ROUTE_KEYS) | {"campaign_id", "draft_version", "action", "copy", "media",
    "audience", "mention_policy", "notification_behavior", "scheduled_for", "timezone",
    "cost_minor_units", "template_selection", "depends_on_job_id", "depends_on_content_hash",
    "dependency_condition", "risk_classification", "destination_class", "content_type", "source_claim_bindings"}


def validate_payload(p):
    if not REQUIRED.issubset(p):
        raise ValueError("payload_missing_fields:" + ",".join(sorted(REQUIRED - p.keys())))
    if p["action"] not in {"publish_now", "schedule", "media_upload"}:
        raise ValueError("unsupported_action")
    if p["content_type"] not in {"news", "launch", "youtube", "daily_reflection", "other"}:
        raise ValueError("invalid_content_type")
    bindings = p["source_claim_bindings"]
    if not isinstance(bindings, list) or any(not isinstance(b, dict) or set(b) != {"claim_id", "version", "claim_hash"} for b in bindings):
        raise ValueError("invalid_source_claim_bindings")
    if p["content_type"] in {"news", "launch", "youtube"} and not bindings:
        raise ValueError("source_claims_required")
    if len({(b["claim_id"], b["version"]) for b in bindings}) != len(bindings):
        raise ValueError("duplicate_source_claim_bindings")
    if p["route"] not in {"direct_api", "postiz", "browser"}:
        raise ValueError("route_unavailable")
    if (p["route"] == "browser" and p["route_driver"] not in {"direct_browser", "local_mcp_browser"}
            or p["route"] != "browser" and p["route_driver"] != "native"):
        raise ValueError("route_driver_mismatch")
    for field in ("campaign_id", "account_ref", "destination_ref", "channel", "copy", "native_format_id"):
        if not isinstance(p[field], str) or not p[field].strip():
            raise ValueError("invalid_payload_field:" + field)
    if not p["native_format_id"].startswith(p["channel"] + "."):
        raise ValueError("native_format_channel_mismatch")
    if p["action"] == "schedule":
        from zoneinfo import ZoneInfo
        ZoneInfo(p["timezone"])
        instant(p["scheduled_for"])
    elif p["scheduled_for"] is not None or p["timezone"] is not None:
        raise ValueError("unexpected_schedule")
    if p["dependency_condition"] not in {"none", "parent_verified_published"}:
        raise ValueError("invalid_dependency")
    if p["dependency_condition"] != "none" and not all(p[k] for k in ("depends_on_job_id", "depends_on_content_hash")):
        raise ValueError("missing_parent_binding")
    payload_hash(p)


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, campaign TEXT NOT NULL, identity TEXT UNIQUE NOT NULL,
              duplicate_hash TEXT NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL,
              approval TEXT, status TEXT NOT NULL, verification TEXT NOT NULL,
              created_at TEXT NOT NULL, evidence TEXT);
            CREATE TABLE IF NOT EXISTS attempts(
              id INTEGER PRIMARY KEY, job TEXT NOT NULL, number INTEGER NOT NULL,
              started_at TEXT NOT NULL, outcome TEXT NOT NULL, ended_at TEXT,
              UNIQUE(job,number));
            CREATE TABLE IF NOT EXISTS locks(scope TEXT PRIMARY KEY, job TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS controls(scope TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def account_scope(p):
        return "account:" + payload_hash({k: p[k] for k in ("channel", "account_ref", "instance_ref")})

    def create(self, job_id, payload, *, now):
        validate_payload(payload)
        instant(now)
        identity = payload_hash({k: payload[k] for k in
                                 ("campaign_id", "channel", "account_ref", "destination_ref", "native_format_id", "draft_version", "instance_ref")})
        duplicate = payload_hash({k: v for k, v in payload.items() if k not in
                                  {"campaign_id", "draft_version", "variant_group_id", "recipe_id"}})
        with self.connection() as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL,'awaiting_approval','not_due',?,NULL)",
                       (job_id, payload["campaign_id"], identity, duplicate, wire(payload), payload_hash(payload), now))

    def get(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("job_not_found")
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        return item

    @staticmethod
    def check_approval(job_id, content_hash, receipt, now):
        body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
        if receipt.get("receipt_hash") != payload_hash(body):
            raise ValueError("receipt_hash_mismatch")
        if receipt.get("record_type") != "ApprovalReceipt" or receipt.get("approved_by") != "user" or not receipt.get("approver_session_ref"):
            raise ValueError("approval_required")
        if not instant(receipt["approved_at"]) <= instant(now) < instant(receipt["expires_at"]):
            raise ValueError("approval_expired_or_future")
        matches = [j for j in receipt.get("approved_jobs", []) if j.get("job_id") == job_id]
        if len(matches) != 1 or matches[0].get("content_hash") != content_hash:
            raise ValueError("approval_payload_mismatch")

    def approve(self, job_id, receipt, *, now):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise ValueError("job_not_found")
            self.check_approval(job_id, job["content_hash"], receipt, now)
            self.check_source_claims(db, json.loads(job["payload"]), now)
            changed = db.execute("UPDATE jobs SET approval=?,status='approved' WHERE id=? AND status IN ('awaiting_approval','approved')",
                                 (wire(receipt), job_id)).rowcount
            if not changed:
                raise ValueError("job_not_approvable")

    @staticmethod
    def check_source_claims(db, payload, now):
        validate_payload(payload)
        bindings = payload["source_claim_bindings"]
        if not bindings:
            return
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"claims", "observations", "source_registry"} <= tables:
            raise ValueError("source_ledger_required_in_job_database")
        for binding in bindings:
            row = db.execute("SELECT * FROM claims WHERE id=? AND version=?", (binding["claim_id"], binding["version"])).fetchone()
            if not row or row["state"] != "current":
                raise ValueError("source_claim_stale_or_missing")
            claim = json.loads(row["body"])
            if payload_hash(claim) != binding["claim_hash"] or not claim["usable_for_draft"] or instant(claim["last_reviewed_at"]) > instant(now):
                raise ValueError("source_claim_drift")
            for evidence in claim["evidence"]:
                observation = db.execute("SELECT body FROM observations WHERE id=?", (evidence["observation_id"],)).fetchone()
                if not observation:
                    raise ValueError("source_observation_missing")
                source = json.loads(observation[0])["source"]
                registry = db.execute("SELECT body FROM source_registry WHERE id=? ORDER BY version DESC LIMIT 1", (source["source_id"],)).fetchone()
                if not registry or json.loads(registry[0]) != source or not source["enabled"]:
                    raise ValueError("source_registry_drift")

    def set_kill_switch(self, scope, enabled):
        with self.connection() as db:
            db.execute("INSERT INTO controls VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET enabled=excluded.enabled", (scope, bool(enabled)))

    def begin(self, job_id, route, *, now):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("job_not_found")
            if row["status"] not in {"approved", "queued"}:
                return False
            p = json.loads(row["payload"])
            self.check_source_claims(db, p, now)
            self.check_approval(job_id, row["content_hash"], json.loads(row["approval"]), now)
            if payload_hash(p) != row["content_hash"]:
                raise ValueError("stored_payload_drift")
            scopes = ("global", "platform:" + p["channel"], self.account_scope(p), "recipe:" + p.get("recipe_id", ""))
            if db.execute("SELECT 1 FROM controls WHERE enabled=1 AND scope IN (?,?,?,?)", scopes).fetchone():
                raise ValueError("kill_switch_active")
            if route.get("outcome") != "passed" or route.get("operation") != p["action"] or any(route.get(k) != p[k] for k in ROUTE_KEYS):
                raise ValueError("route_mismatch")
            completed, expiry, current = instant(route["completed_at"]), instant(route["expires_at"]), instant(now)
            if not completed <= current < expiry or expiry - completed > timedelta(days=7 if p["route"] == "browser" else 30):
                raise ValueError("route_expired_or_invalid_ttl")
            if p["dependency_condition"] != "none":
                parent = db.execute("SELECT * FROM jobs WHERE id=?", (p["depends_on_job_id"],)).fetchone()
                if not parent or parent["content_hash"] != p["depends_on_content_hash"] or parent["verification"] != "verified_published":
                    raise ValueError("blocked_by_parent")
            since = (current - timedelta(days=30)).isoformat()
            if db.execute("SELECT 1 FROM jobs WHERE id<>? AND duplicate_hash=? AND created_at>=? AND status IN ('submitting','submitted','published','scheduled','ambiguous')",
                          (job_id, row["duplicate_hash"], since)).fetchone():
                return False
            if db.execute("SELECT 1 FROM locks WHERE scope=?", (self.account_scope(p),)).fetchone():
                return False
            db.execute("INSERT INTO locks VALUES(?,?)", (self.account_scope(p), job_id))
            number = db.execute("SELECT COUNT(*) FROM attempts WHERE job=?", (job_id,)).fetchone()[0] + 1
            db.execute("INSERT INTO attempts(job,number,started_at,outcome) VALUES(?,?,?,'submit_started')", (job_id, number, now))
            db.execute("UPDATE jobs SET status='submitting',verification='pending' WHERE id=?", (job_id,))
            return True

    def finish(self, job_id, outcome, *, now):
        states = {"success": "submitted", "ambiguous_after_submit": "ambiguous",
                  "provider_rejected": "failed", "permanent_error": "failed"}
        if outcome not in states:
            raise ValueError("unsupported_attempt_outcome")
        instant(now)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE jobs SET status=? WHERE id=? AND status='submitting'", (states[outcome], job_id)).rowcount
            if not changed:
                raise ValueError("job_not_submitting")
            db.execute("UPDATE attempts SET outcome=?,ended_at=? WHERE job=? AND outcome='submit_started'", (outcome, now, job_id))
            if outcome in {"provider_rejected", "permanent_error"}:
                db.execute("DELETE FROM locks WHERE job=?", (job_id,))

    def reconcile(self, job_id, evidence, *, now):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] not in {"submitting", "submitted", "ambiguous", "scheduled", "published"}:
                raise ValueError("job_not_reconcilable")
            p = json.loads(row["payload"])
            matched = (evidence.get("source") == "independent_read"
                       and evidence.get("content_hash") == row["content_hash"]
                       and all(evidence.get(k) == p[k] for k in ("account_ref", "destination_ref", "native_format_id"))
                       and bool(evidence.get("provider_id") or evidence.get("permalink"))
                       and instant(row["created_at"]) <= instant(evidence["observed_at"]) <= instant(now))
            state = evidence.get("observed_state")
            if not matched or state not in {"live", "scheduled"}:
                return "unresolved"
            if state == "scheduled" and p["action"] != "schedule":
                return "unresolved"
            if state == "live" and p["scheduled_for"] and instant(now) < instant(p["scheduled_for"]):
                return "unresolved"
            verification = "verified_published" if state == "live" else "verified_scheduled"
            db.execute("UPDATE jobs SET status=?,verification=?,evidence=? WHERE id=?",
                       ("published" if state == "live" else "scheduled", verification, wire(evidence), job_id))
            db.execute("DELETE FROM locks WHERE job=?", (job_id,))
            return verification

    def cancel(self, job_id, *, now):
        instant(now)
        with self.connection() as db:
            return bool(db.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status IN ('awaiting_approval','approved','queued','planned')", (job_id,)).rowcount)

    def attempts(self, job_id):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM attempts WHERE job=? ORDER BY number", (job_id,))]

    def campaign(self, campaign_id):
        with self.connection() as db:
            jobs = [dict(r) for r in db.execute("SELECT id,status,verification FROM jobs WHERE campaign=? ORDER BY id", (campaign_id,))]
        states = {r["status"] for r in jobs}
        if not jobs:
            status = "not_started"
        elif states & {"submitting", "submitted", "ambiguous"}:
            status = "unresolved"
        elif states == {"published"}:
            status = "succeeded"
        elif "published" in states:
            status = "partial_success"
        elif states == {"cancelled"}:
            status = "cancelled"
        elif states <= {"failed", "cancelled"}:
            status = "failed"
        else:
            status = "in_progress"
        return {"campaign_id": campaign_id, "status": status, "jobs": jobs}
