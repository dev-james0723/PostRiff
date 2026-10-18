"""Approved Substack handoff targets -> existing in-app notification outbox.

This is a reminder to perform a manual action, never a publisher or an email job.
The scan rereads the workspace under its existing row lock and emits only to
current, unblocked members who can approve. No draft text enters the outbox.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError

from .notifications import catalog
from .substack import build_manual_handoff, validate_publication_url
from .substack_service import MAX_CONNECTIONS, MAX_DRAFTS, _content_hash

EVENT_TYPE = "substack.manual_handoff_due"
DEDUPE_PREFIX = "substack-handoff-due:"
EVENTS = {EVENT_TYPE: {"category": "publishing", "severity": "action", "audience": "actor",
                       "email": "off", "push": "off", "sms": "off", "template": "needs_input"}}
catalog.register_extension_events(EVENTS)

_UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_IDS = {kind: re.compile(r"^" + prefix + r"_[a-f0-9]{32}$")
        for kind, prefix in (("connection", "sc"), ("draft", "sd"), ("job", "sq"))}
_TARGET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$")


def _valid(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _target(value):
    # HostedSubstackService always writes canonical UTC. Keep SQL candidate
    # comparisons and this authoritative check on exactly the same contract.
    if not _valid(_TARGET, value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        canonical = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return parsed.timestamp() if canonical == value else None
    except (ValueError, OverflowError, OSError):
        return None


def _index(items, kind, limit):
    if not isinstance(items, list) or len(items) > limit:
        return None
    result = {}
    for item in items:
        if not isinstance(item, dict) or not _valid(_IDS[kind], item.get("id")) or item["id"] in result:
            return None
        result[item["id"]] = item
    return result


def due_jobs(state, now, workspace_id=None):
    """Return safe, due manual-job metadata; do not mutate state or trust cached approvals."""
    if (not isinstance(state, dict) or "accountBlock" in state or "accountDeletion" in state or
            isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now)):
        return []
    workspace = state.get("workspace")
    if not isinstance(workspace, dict) or workspace.get("sample") is not False:
        return []
    actual_workspace = workspace.get("id")
    if not _valid(_UUID, actual_workspace) or (workspace_id is not None and workspace_id != actual_workspace):
        return []
    section = state.get("substack")
    if not isinstance(section, dict) or type(section.get("version")) is not int or section["version"] != 1:
        return []
    connections = _index(section.get("connections"), "connection", MAX_CONNECTIONS)
    drafts = _index(section.get("drafts"), "draft", MAX_DRAFTS)
    jobs = _index(section.get("queue"), "job", MAX_DRAFTS)
    if connections is None or drafts is None or jobs is None:
        return []
    due = []
    for job in jobs.values():
        if job.get("kind") != "manual_handoff" or job.get("status") != "pending_manual" or job.get("autoPublished") is not False:
            continue
        when = _target(job.get("scheduledFor"))
        if when is None or when > now:
            continue
        draft = drafts.get(job.get("draftId")) if isinstance(job.get("draftId"), str) else None
        connection = connections.get(job.get("connectionId")) if isinstance(job.get("connectionId"), str) else None
        if not draft or not connection or draft.get("status") != "approved":
            continue
        digest = draft.get("contentHash")
        if (not _valid(_HASH, digest) or draft.get("approvedHash") != digest or job.get("contentHash") != digest or
                draft.get("connectionId") != connection["id"] or draft.get("scheduledFor") != job["scheduledFor"] or
                connection.get("mode") != "public_feed" or connection.get("status") != "feed_added"):
            continue
        if job.get("idempotencyKey") != hashlib.sha256((draft["id"] + ":" + digest).encode()).hexdigest():
            continue
        try:
            validate_publication_url(connection.get("publicationUrl"))
            if _content_hash(draft, connection) != digest:
                continue
            # An approved flag cannot turn an incomplete or malformed draft
            # into a usable handoff after an out-of-band state change.
            build_manual_handoff(connection["publicationUrl"], draft)
        except (AlphaError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            continue
        due.append({"id": job["id"], "draftId": draft["id"], "connectionId": connection["id"],
                    "contentHash": digest, "scheduledFor": job["scheduledFor"], "scheduledAt": when})
    return sorted(due, key=lambda job: (job["scheduledAt"], job["id"]))


def _dedupe(job, recipient):
    return DEDUPE_PREFIX + job["id"] + ":" + job["contentHash"] + ":" + recipient


def _event(workspace_id, job, recipient):
    return {"workspace_id": workspace_id, "event_type": EVENT_TYPE, "actor": recipient,
            "dedupe_key": _dedupe(job, recipient), "entity_type": "substack_manual_handoff", "entity_id": job["id"],
            "grouping_key": "substack-handoff:" + job["id"], "occurred_at": job["scheduledAt"],
            "channel_filter": ("in_app",),
            "payload": {"title": "A Substack handoff target was reached",
                        "href": "/app/channels?connect=substack&substackDraft=" + job["draftId"],
                        "reason": "Review the current saved draft, approval and destination in Substack connections. No post or email was sent."}}


_APPROVER = "(m.role IN ('owner','approver') OR (m.role <> 'viewer' AND m.can_publish))"
_UNBLOCKED = """NOT EXISTS (SELECT 1 FROM public.pr_account_blocks b WHERE b.lifted_at IS NULL
                 AND (b.user_id=m.user_id OR b.workspace_id=m.workspace_id OR m.workspace_id=ANY(b.frozen_workspace_ids)))"""
_CANDIDATES = """SELECT w.id::text FROM public.pr_workspaces w
    WHERE NOT (w.state ? 'accountDeletion') AND NOT (w.state ? 'accountBlock')
      AND w.state#>>'{workspace,id}'=w.id::text AND w.state#>'{workspace,sample}'='false'::jsonb
      AND w.state#>>'{substack,version}'='1'
      AND (%s::uuid IS NULL OR w.id>%s::uuid)
      AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.state#>'{substack,queue}')='array'
          THEN w.state#>'{substack,queue}' ELSE '[]'::jsonb END) q
        JOIN public.pr_memberships m ON m.workspace_id=w.id AND m.status='active'
        JOIN public.pr_profiles p ON p.user_id=m.user_id AND p.deleted_at IS NULL
        WHERE """ + _APPROVER + " AND " + _UNBLOCKED + """
          AND q->>'kind'='manual_handoff' AND q->>'status'='pending_manual' AND q->>'autoPublished'='false'
          AND q->>'id' ~ '^sq_[a-f0-9]{32}$' AND q->>'contentHash' ~ '^[a-f0-9]{64}$'
          AND q->>'scheduledFor' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{6})?Z$'
          AND left(q->>'scheduledFor',19)<=%s
          AND NOT EXISTS (SELECT 1 FROM public.pr_notification_events e WHERE e.workspace_id=w.id
            AND e.dedupe_key='""" + DEDUPE_PREFIX + """'||(q->>'id')||':'||(q->>'contentHash')||':'||m.user_id::text))
    ORDER BY w.id LIMIT %s"""
_RECIPIENTS = """SELECT m.user_id::text FROM public.pr_memberships m
    JOIN public.pr_profiles p ON p.user_id=m.user_id AND p.deleted_at IS NULL
    WHERE m.workspace_id=%s AND m.status='active' AND """ + _APPROVER + " AND " + _UNBLOCKED + """
      AND NOT EXISTS (SELECT 1 FROM public.pr_notification_events e WHERE e.workspace_id=m.workspace_id
        AND e.dedupe_key=%s||m.user_id::text)
    ORDER BY m.user_id LIMIT %s FOR SHARE OF m,p SKIP LOCKED"""


def _enabled(hosted, notifications):
    return (getattr(getattr(hosted, "substack", None), "enabled", False) is True and
            notifications is not None and notifications.enabled())


def scan(hosted, notifications=None, *, limit=50, budget_seconds=2.0):
    """Bounded, retryable, in-app-only scan. No workspace or queue state is changed.

    Candidate SQL excludes already-recorded recipient keys before LIMIT. Pages
    continue past malformed or busy workspaces within the same time budget; a
    process-local keyset cursor is only a fairness optimization. Missing
    account-block/notification schema fails closed.
    """
    notifications = notifications if notifications is not None else getattr(hosted, "notifications", None)
    result = {"status": "available", "created": 0, "scanned": 0, "failed": 0}
    if not _enabled(hosted, notifications):
        return {**result, "status": "disabled"}
    if (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or
            isinstance(budget_seconds, bool) or not isinstance(budget_seconds, (int, float)) or
            not math.isfinite(budget_seconds) or budget_seconds <= 0):
        return result
    limit, budget_seconds = min(limit, 100), min(float(budget_seconds), 5.0)
    started = time.monotonic()
    now = getattr(notifications, "clock", time.time)()
    cutoff = datetime.fromtimestamp(now, timezone.utc).isoformat()[:19]
    factory = hosted.repository.connection_factory
    after = getattr(notifications, "_substack_due_scan_after", None)
    after = after if _valid(_UUID, after) else None

    def budget_left():
        return budget_seconds - (time.monotonic() - started)

    def bounded(cur):
        cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(max(1, min(1500, int(budget_left() * 1000)))),))

    try:
        with factory() as db, db.cursor() as cur:
            bounded(cur)
            cur.execute("""SELECT to_regclass('public.pr_workspaces'),to_regclass('public.pr_memberships'),
              to_regclass('public.pr_profiles'),to_regclass('public.pr_account_blocks'),
              to_regclass('public.pr_notification_events'),to_regclass('public.pr_notification_deliveries')""")
            schema = cur.fetchone()
            if not schema or len(schema) != 6 or not all(schema):
                return {**result, "status": "schema_unavailable"}
    except Exception:
        return {**result, "status": "temporarily_unavailable", "failed": 1}

    attempted = 0
    seen, wrapped = set(), False
    while budget_left() > 0 and attempted < limit and _enabled(hosted, notifications):
        try:
            with factory() as db, db.cursor() as cur:
                bounded(cur)
                cur.execute(_CANDIDATES, (after, after, cutoff, limit - attempted))
                rows = cur.fetchall()
        except Exception:
            result["failed"] += 1
            break
        if not rows:
            if after is not None and not wrapped:
                after, wrapped = None, True
                continue
            notifications._substack_due_scan_after = None
            break
        for (workspace_id,) in rows:
            if (budget_left() <= 0 or attempted >= limit or not _enabled(hosted, notifications)):
                break
            if workspace_id in seen:
                return {**result, "status": "partial" if result["failed"] else "available"}
            seen.add(workspace_id)
            # Continue the next keyset page even when this candidate became
            # invalid or locked. No invalid event consumes a durable dedupe key.
            after = notifications._substack_due_scan_after = workspace_id
            local_created = 0
            try:
                with factory() as db, db.cursor() as cur:
                    bounded(cur)
                    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE SKIP LOCKED", (workspace_id,))
                    row = cur.fetchone()
                    if row is None:
                        continue
                    state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    jobs = due_jobs(state, now, workspace_id)
                    result["scanned"] += 1
                    for job in jobs:
                        if budget_left() <= 0 or attempted >= limit or not _enabled(hosted, notifications):
                            break
                        bounded(cur)
                        cur.execute(_RECIPIENTS, (workspace_id, _dedupe(job, ""), limit - attempted))
                        recipients = cur.fetchall()
                        for (recipient,) in recipients:
                            if budget_left() <= 0 or attempted >= limit or not _enabled(hosted, notifications):
                                break
                            if not _valid(_UUID, recipient):
                                continue
                            attempted += 1
                            bounded(cur)
                            cur.execute("SAVEPOINT substack_notification")
                            try:
                                outcome = notifications.emit(cur, **_event(workspace_id, job, recipient))
                                local_created += int(bool(outcome.get("created")))
                                cur.execute("RELEASE SAVEPOINT substack_notification")
                            except Exception:
                                cur.execute("ROLLBACK TO SAVEPOINT substack_notification")
                                cur.execute("RELEASE SAVEPOINT substack_notification")
                                result["failed"] += 1
                    db.commit()
                result["created"] += local_created
            except Exception:
                result["failed"] += 1
    if result["failed"]:
        result["status"] = "partial"
    return result
