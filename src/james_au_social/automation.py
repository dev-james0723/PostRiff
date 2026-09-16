"""Durable zero-side-effect recipe control. No scheduler or paid execution.

Receipts require an authenticated caller: checksums bind scope, not identity.
Reminder results are pending intents, never delivery receipts. All paid work
fails closed until a separately authenticated budget broker is implemented.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .execution import instant, payload_hash, wire

TERMINAL = {"rejected", "superseded", "expired", "cancelled", "complete"}
SCOPES = {"trigger": True, "research_and_draft": True, "template_policy": True,
          "target_recommendation": True, "review_reminders": True, "cost_policy": True}


def activation_receipt(recipe, dry_run, *, user_session_ref, now, expires_at):
    if not user_session_ref or instant(expires_at) <= instant(now):
        raise ValueError("invalid_activation")
    if dry_run["recipe_hash"] != payload_hash(recipe):
        raise ValueError("dry_run_recipe_mismatch")
    body = {"record_type": "RecipeActivationReceipt", "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"], "recipe_hash": payload_hash(recipe),
            "dry_run_hash": dry_run["hash"], "activated_by": "user",
            "user_session_ref": user_session_ref, "activated_at": now, "expires_at": expires_at,
            "approved_scopes": {**SCOPES, "post_approval_action": recipe["post_approval_action"]}}
    return {**body, "receipt_hash": payload_hash(body)}


def validate_recipe(value):
    required = {"recipe_id", "recipe_version", "trigger", "codex_execution", "topic_sources",
                "approved_targets", "template_policy", "approval_policy", "post_approval_action",
                "cost_policy", "recipe_expires_at", "review_reminder_policy"}
    if not required <= value.keys() or not value["recipe_id"]:
        raise ValueError("recipe_missing_fields")
    if type(value["recipe_version"]) is not int or value["recipe_version"] < 1:
        raise ValueError("invalid_version")
    trigger = value["trigger"]
    try:
        ZoneInfo(trigger["timezone"])
    except (ZoneInfoNotFoundError, KeyError, TypeError) as exc:
        raise ValueError("invalid_timezone") from exc
    if trigger.get("type") not in {"manual", "schedule", "source_event"}:
        raise ValueError("invalid_trigger")
    if trigger.get("overlap_policy") not in {"skip_new", "queue_one", "block_and_alert"}:
        raise ValueError("invalid_overlap_policy")
    if trigger.get("misfire_policy") not in {"skip", "run_once_when_available", "ask_user"}:
        raise ValueError("invalid_misfire_policy")
    if value["post_approval_action"] not in {"hold", "schedule_approved", "publish_approved_now"}:
        raise ValueError("invalid_post_approval_action")
    if value["approval_policy"] not in {"draft_only", "approve_each_campaign", "preapproved_green_only"}:
        raise ValueError("invalid_approval_policy")
    execution = value["codex_execution"]
    scope = {"thread_heartbeat": "thread_ref", "standalone_project_job": "project_ref"}.get(execution.get("kind"))
    if not scope or not execution.get(scope) or not execution.get("saved_prompt_hash"):
        raise ValueError("execution_scope_required")
    for key in ("per_run_limit_minor", "monthly_limit_minor"):
        amount = value["cost_policy"].get(key)
        if type(amount) is not int or amount < 0:
            raise ValueError("invalid_budget")
    policy = value["review_reminder_policy"]
    if type(policy.get("enabled")) is not bool:
        raise ValueError("invalid_reminder")
    if policy["enabled"] and any(type(policy.get(k)) is not int or policy[k] < 60
                                 for k in ("first_delay_seconds", "repeat_seconds")):
        raise ValueError("invalid_reminder_interval")
    if value["recipe_expires_at"]:
        instant(value["recipe_expires_at"])
    wire(value)


class RecipeStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("symlink_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS recipes(id TEXT, version INTEGER, body TEXT, hash TEXT,
                status TEXT, activation TEXT, reason TEXT, PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS dry_runs(id TEXT, version INTEGER, body TEXT,
                PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, recipe TEXT, version INTEGER,
                state TEXT, review TEXT, review_hash TEXT, approval_receipt_id TEXT,
                reminder_due TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY, event TEXT, target TEXT,
                observed_at TEXT);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def configure(self, recipe):
        validate_recipe(recipe)
        with self.db() as db:
            latest = db.execute("SELECT * FROM recipes WHERE id=? ORDER BY version DESC LIMIT 1",
                                (recipe["recipe_id"],)).fetchone()
            if latest and recipe["recipe_version"] <= latest["version"]:
                if recipe["recipe_version"] == latest["version"] and payload_hash(recipe) == latest["hash"]:
                    return
                raise ValueError("immutable_recipe_version")
            status = "needs_revision" if latest else "draft"
            if latest:
                db.execute("UPDATE recipes SET status='needs_revision',reason='version_superseded' WHERE id=?",
                           (recipe["recipe_id"],))
                db.execute("UPDATE runs SET state='superseded',reminder_due=NULL WHERE recipe=? AND state NOT IN ('complete','rejected','cancelled','expired')",
                           (recipe["recipe_id"],))
            db.execute("INSERT INTO recipes VALUES(?,?,?,?,?,NULL,NULL)",
                       (recipe["recipe_id"], recipe["recipe_version"], wire(recipe), payload_hash(recipe), status))

    def status(self, recipe_id):
        with self.db() as db:
            row = self._latest(db, recipe_id)
            return {"recipe_id": recipe_id, "recipe_version": row["version"],
                    "recipe_hash": row["hash"], "status": row["status"], "reason": row["reason"]}

    @staticmethod
    def _latest(db, recipe_id):
        row = db.execute("SELECT * FROM recipes WHERE id=? ORDER BY version DESC LIMIT 1", (recipe_id,)).fetchone()
        if not row:
            raise ValueError("recipe_not_found")
        return row

    def record_dry_run(self, recipe_id, version, result, *, now):
        instant(now)
        if result.get("external_side_effects") != []:
            raise ValueError("dry_run_side_effects")
        with self.db() as db:
            row = self._latest(db, recipe_id)
            if row["version"] != version or row["status"] == "active":
                raise ValueError("dry_run_version_or_state")
            body = {"recipe_hash": row["hash"], "result": result, "observed_at": now}
            body["hash"] = payload_hash(body)
            db.execute("INSERT OR REPLACE INTO dry_runs VALUES(?,?,?)", (recipe_id, version, wire(body)))

    def dry_run(self, recipe_id, version):
        with self.db() as db:
            row = db.execute("SELECT body FROM dry_runs WHERE id=? AND version=?", (recipe_id, version)).fetchone()
            if not row:
                raise ValueError("dry_run_required")
            return json.loads(row[0])

    @staticmethod
    def _check_activation(db, receipt, now):
        body = {k: v for k, v in receipt.items() if k != "receipt_hash"}
        if receipt.get("receipt_hash") != payload_hash(body) or receipt.get("record_type") != "RecipeActivationReceipt":
            raise ValueError("activation_integrity")
        if receipt.get("activated_by") != "user" or not receipt.get("user_session_ref"):
            raise ValueError("activation_user_required")
        if not instant(receipt["activated_at"]) <= instant(now) < instant(receipt["expires_at"]):
            raise ValueError("activation_expired")
        row = RecipeStore._latest(db, receipt["recipe_id"])
        recipe = json.loads(row["body"])
        if row["version"] != receipt["recipe_version"] or row["hash"] != receipt["recipe_hash"]:
            raise ValueError("activation_recipe_mismatch")
        dry = db.execute("SELECT body FROM dry_runs WHERE id=? AND version=?", (row["id"], row["version"])).fetchone()
        if not dry or json.loads(dry[0])["hash"] != receipt["dry_run_hash"]:
            raise ValueError("activation_dry_run_mismatch")
        if receipt.get("approved_scopes") != {**SCOPES, "post_approval_action": recipe["post_approval_action"]}:
            raise ValueError("activation_scope_mismatch")
        if recipe["recipe_expires_at"] and instant(now) >= instant(recipe["recipe_expires_at"]):
            raise ValueError("recipe_expired")
        return row, recipe

    def activate(self, receipt, *, now):
        with self.db() as db:
            row, _ = self._check_activation(db, receipt, now)
            if row["status"] == "paused":
                raise ValueError("resume_requires_current_user_instruction")
            db.execute("UPDATE recipes SET status='active',activation=?,reason=NULL WHERE id=? AND version=?",
                       (wire(receipt), row["id"], row["version"]))
            db.execute("INSERT INTO audit(event,target,observed_at) VALUES('activate',?,?)", (row["id"], now))

    def pause(self, recipe_id, *, reason):
        with self.db() as db:
            self._latest(db, recipe_id)
            db.execute("UPDATE recipes SET status='paused',reason=? WHERE id=?", (reason, recipe_id))
            db.execute("UPDATE runs SET reminder_due=NULL WHERE recipe=?", (recipe_id,))

    def invalidate(self, recipe_id, *, reason):
        with self.db() as db:
            self._latest(db, recipe_id)
            db.execute("UPDATE recipes SET status='needs_revision',reason=?,activation=NULL WHERE id=?", (reason, recipe_id))
            db.execute("DELETE FROM dry_runs WHERE id=?", (recipe_id,))
            db.execute("UPDATE runs SET state='superseded',reminder_due=NULL WHERE recipe=? AND state NOT IN ('complete','rejected','cancelled','expired')", (recipe_id,))

    def resume(self, receipt, *, current_user_instruction, now):
        if current_user_instruction is not True:
            raise ValueError("current_user_instruction_required")
        with self.db() as db:
            row, _ = self._check_activation(db, receipt, now)
            if row["status"] != "paused" or row["activation"] != wire(receipt):
                raise ValueError("resume_activation_mismatch")
            db.execute("UPDATE recipes SET status='active',reason=NULL WHERE id=? AND version=?", (row["id"], row["version"]))

    def start(self, recipe_id, version, event_id, story_version, *, now, estimated_cost_minor=0):
        if not event_id or not story_version:
            raise ValueError("trigger_identity_required")
        if type(estimated_cost_minor) is not int or estimated_cost_minor != 0:
            raise ValueError("separate_budget_authorization_required")
        run_id = payload_hash({"recipe_id": recipe_id, "version": version, "event_id": event_id,
                               "story_version": story_version})
        with self.db() as db:
            row = self._latest(db, recipe_id)
            if row["version"] != version or row["status"] != "active":
                raise ValueError("recipe_inactive_or_stale")
            _, recipe = self._check_activation(db, json.loads(row["activation"]), now)
            if db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone():
                return run_id
            if db.execute("SELECT id FROM runs WHERE recipe=? AND state NOT IN ('complete','rejected','superseded','expired','cancelled')", (recipe_id,)).fetchone():
                if recipe["trigger"]["overlap_policy"] == "skip_new":
                    return None
                # Durable queue dispatch is not yet implemented; do not silently
                # discard a queue_one or block_and_alert contract as skip_new.
                raise ValueError("overlap_requires_queue_or_alert_dispatcher")
            db.execute("INSERT INTO runs VALUES(?,?,?,'triggered',NULL,NULL,NULL,NULL,?)", (run_id, recipe_id, version, now))
        return run_id

    def run(self, run_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("run_not_found")
            return dict(row)

    def request_review(self, run_id, manifest, *, now):
        with self.db() as db:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["state"] not in {"triggered", "awaiting_review"}:
                raise ValueError("review_state_invalid")
            row = self._latest(db, run["recipe"])
            if row["status"] != "active" or row["version"] != run["version"]:
                raise ValueError("recipe_inactive_or_stale")
            _, recipe = self._check_activation(db, json.loads(row["activation"]), now)
            policy = recipe["review_reminder_policy"]
            due = (instant(now) + timedelta(seconds=policy["first_delay_seconds"])).isoformat() if policy["enabled"] else None
            db.execute("UPDATE runs SET state='awaiting_review',review=?,review_hash=?,reminder_due=? WHERE id=?",
                       (wire(manifest), payload_hash(manifest), due, run_id))

    def resolve_review(self, run_id, outcome, *, expected_review_hash, current_user_instruction, now):
        instant(now)
        if current_user_instruction is not True or outcome not in {"approved", "rejected", "cancelled"}:
            raise ValueError("current_user_instruction_and_resolution_required")
        with self.db() as db:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["state"] != "awaiting_review" or run["review_hash"] != expected_review_hash:
                raise ValueError("review_hash_or_state_mismatch")
            if outcome == "approved":
                row = self._latest(db, run["recipe"])
                if row["status"] != "active":
                    raise ValueError("recipe_inactive")
                self._check_activation(db, json.loads(row["activation"]), now)
            db.execute("UPDATE runs SET state=?,reminder_due=NULL WHERE id=?", (outcome, run_id))
            db.execute("INSERT INTO audit(event,target,observed_at) VALUES(?,?,?)", (outcome, run_id, now))

    def due_reminders(self, *, now):
        notices = []
        with self.db() as db:
            for run in db.execute("SELECT * FROM runs WHERE state='awaiting_review' AND reminder_due IS NOT NULL").fetchall():
                row = self._latest(db, run["recipe"])
                if row["status"] != "active":
                    continue
                try:
                    self._check_activation(db, json.loads(row["activation"]), now)
                except ValueError:
                    db.execute("UPDATE runs SET state='expired',reminder_due=NULL WHERE id=?", (run["id"],))
                    continue
                if instant(run["reminder_due"]) <= instant(now):
                    notices.append({"run_id": run["id"], "review_hash": run["review_hash"],
                                    "message": "Open the owning task to review the pending campaign.",
                                    "delivered": False})
        return notices
