"""Time Back (docs/raffi-time-back/ENGINEERING.md): an inspectable estimate of the human work time Raffi returned to a
person, counted from completed outcomes only.

One immutable ledger row per atomic task: a generated draft accepted for use, each genuinely separate further version
of it (another platform, language or account), a provider-verified publication, an automation activated from a draft. Generating, suggesting, failing or resuming saves
nothing. Every row keeps its baseline, the measured active time when there is one, where the baseline came from and the
calculator version, so any total can explain itself. Missing is not zero: without a valid baseline, or a beneficiary who
is an active member of the workspace, no row is written.

Writes run inside the transaction of the outcome that earned them, behind a savepoint, so Time Back can never fail a
publication or a command. Tables come from migration 023; they hold ids and numbers, never content.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

CALCULATOR_VERSION = "time-back-v1"
DEFAULTS_VERSION = "raffi-default-v1"
PERSONALIZED_VERSION = "personalized-median-v1"
OVERRIDE_VERSION = "user-override-v1"
TASK_KINDS = ("draft", "adapt", "publish", "campaign_plan", "recurring_setup")
# Versioned, conservative product defaults in seconds (§3.2): about how long the task takes a person without Raffi.
DEFAULT_BASELINES = {"draft": 480, "adapt": 240, "publish": 180, "campaign_plan": 900, "recurring_setup": 600}
# The one outcome that completes each counted task kind. campaign_plan has none yet: a campaign only ever becomes
# active as its recurring automation, which recurring_setup already counts (§2.2, no double counting).
OUTCOME_KINDS = {"draft": "accepted_draft", "adapt": "accepted_adaptation", "publish": "verified_publication", "recurring_setup": "activated_automation"}
CONFIDENCE = ("estimated", "personalized", "measured")
PERSONALIZE_AFTER, SAMPLE_WINDOW = 3, 7
MIN_BASELINE, MAX_BASELINE = 60, 14400
PROMPT_INTERVAL, PROMPT_RECENCY = 30 * 86400, 7 * 86400
SESSION_CAP, SESSION_RETENTION = 4 * 3600, 30 * 86400
# A cumulative heartbeat may add no more than the wall-clock time since the previous one (plus network slack), and a
# new session opens with at most one heartbeat period: a client cannot claim time it could not have measured.
HEARTBEAT_SLACK, FIRST_HEARTBEAT = 15, 90
RANGES = ("7d", "30d", "year", "all")
RANGE_SECONDS = {"7d": 7 * 86400, "30d": 30 * 86400}
# Only drafts a Raffi writer produced count; an author's own edits never make a draft Raffi's.
GENERATED_ORIGINS = ("ideas-candidate", "fixture")
WORKFLOW_PREFIXES = ("conversation", "variant", "automation")
UUID = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.IGNORECASE)
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
OUTCOME_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$")
WORKFLOW_KEY = re.compile(r"^([a-z][a-z_]{1,23}):([A-Za-z0-9_-]{1,64})$")
SESSION_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
# Row metadata is allowlisted and pattern-checked; anything else (a caption, a prompt, an email) is dropped.
METADATA = {
    "platform": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$"),
    "language": re.compile(r"^\w[\w .-]{0,34}$"),
    "channelId": ID,
    "groupRef": re.compile(r"^[a-z]{2,12}:[A-Za-z0-9_-]{1,64}$"),
    "source": re.compile(r"^(?:worker|repair|command)$"),
}
logger = logging.getLogger("postriff.time_back")


# --- pure rules -------------------------------------------------------------------------------------------------------

def dedupe_key(workspace_id, beneficiary_user_id, task_kind, outcome_kind, outcome_ref, calculator_version=CALCULATOR_VERSION):
    """Server-only (§8.1), stable per workspace, person, task, outcome and calculator. Never taken from a client."""
    parts = (str(workspace_id), str(beneficiary_user_id), task_kind, outcome_kind, outcome_ref, calculator_version)
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def clean_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    return {key: value for key, value in metadata.items() if key in METADATA and isinstance(value, str) and METADATA[key].match(value)}


def median_low(samples):
    """With an even count, the smaller middle answer: the conservative median."""
    ordered = sorted(samples)
    return ordered[(len(ordered) - 1) // 2]


def resolve_baseline(task_kind, override=None, samples=()):
    """Precedence (§3.1): an explicit override, then the median of the latest answers once there are enough, then the
    versioned default. `samples` are the person's prompt answers, newest first."""
    if override is not None:
        return int(override), "user_override", OVERRIDE_VERSION
    recent = [int(value) for value in samples][:SAMPLE_WINDOW]
    if len(recent) >= PERSONALIZE_AFTER:
        return median_low(recent), "personalized", PERSONALIZED_VERSION
    return DEFAULT_BASELINES[task_kind], "raffi_default", DEFAULTS_VERSION


def saving(baseline_seconds, active_seconds, baseline_source):
    """(saved seconds, confidence): baseline minus measured active time, never below zero. Without a measurement the
    row is a baseline-only estimate labelled by where its baseline came from."""
    if active_seconds is None:
        return baseline_seconds, "estimated" if baseline_source == "raffi_default" else "personalized"
    return max(0, baseline_seconds - active_seconds), "measured"


def display_minutes(seconds):
    """Whole minutes for display (§3): the nearest minute, never seconds."""
    return (int(seconds) + 30) // 60


def allocate_minutes(parts):
    """Split the displayed total over the parts so a shown breakdown adds up exactly to the shown total (largest
    remainder; ties keep the given order). A part never gains a minute it has no seconds towards."""
    minutes = [part // 60 for part in parts]
    short = display_minutes(sum(parts)) - sum(minutes)
    for index in sorted(range(len(parts)), key=lambda i: (-(parts[i] % 60), i))[:short]:
        minutes[index] += 1
    return minutes


def range_start(range_key, now, time_zone=""):
    """Epoch start of a reporting window, None for all time. "This year" starts on 1 January in the person's saved
    time zone (Account → Profile), else UTC."""
    if range_key not in RANGES:
        raise AlphaError("Choose 7d, 30d, year or all.")
    if range_key == "all":
        return None
    if range_key == "year":
        try:
            zone = ZoneInfo(time_zone) if time_zone else timezone.utc
        except (ZoneInfoNotFoundError, ValueError, OSError):
            zone = timezone.utc
        return datetime(datetime.fromtimestamp(now, zone).year, 1, 1, tzinfo=zone).timestamp()
    return now - RANGE_SECONDS[range_key]


def group_ref(variants, variant):
    """The post a platform version belongs to: the root it was derived from, else the writing run that produced it with
    its siblings, else itself. Siblings and adaptations of one post share it."""
    root, seen = variant, set()
    while len(seen) < 20:
        parent = (root.get("provenance") or {}).get("derivedFrom")
        if not isinstance(parent, str) or parent in seen or not isinstance(variants.get(parent), dict):
            break
        seen.add(parent)
        root = variants[parent]
    run = (root.get("provenance") or {}).get("runId") or root.get("runId")
    return "run:" + run if isinstance(run, str) and ID.match(run) else "variant:" + str(root.get("id"))


def _jobs(state):
    jobs = ((state or {}).get("phase2") or {}).get("jobs")
    return [job for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []


def _planning(state):
    planning = ((state or {}).get("raffi") or {}).get("campaignPlanning")
    return planning if isinstance(planning, dict) else {}


def completed_outcomes(before, after):
    """What one command completed, from its before and after state alone (no SQL): generated drafts accepted for use (a
    new publish job, or a person approving an automation post) and automations activated from a draft. Generating,
    reviewing, suggesting, resuming or editing completes nothing."""
    found = []
    old_jobs = {job.get("id") for job in _jobs(before)}
    for job in _jobs(after):
        manifest = job.get("manifest") if isinstance(job.get("manifest"), dict) else {}
        # The worker holds a job whose approver is not the manifest actor; so does Time Back.
        if job.get("id") in old_jobs or not isinstance(manifest.get("variantId"), str) or job.get("approvedBy") != manifest.get("actor"):
            continue
        found.append({"taskKind": "draft", "variantId": manifest["variantId"], "principal": job.get("approvedBy"), "at": job.get("approvedAt"), "channelId": manifest.get("channelId")})
    old_items = {(occurrence.get("id"), item.get("key")): item.get("state") for occurrence in _planning(before).get("occurrences") or [] if isinstance(occurrence, dict)
                 for item in occurrence.get("items") or [] if isinstance(item, dict)}
    for occurrence in _planning(after).get("occurrences") or []:
        if not isinstance(occurrence, dict):
            continue
        for item in occurrence.get("items") or []:
            decision = item.get("decision") if isinstance(item, dict) and isinstance(item.get("decision"), dict) else {}
            # Owner pre-authorization is not a person's review of this post; its commit (a new job above) is.
            if item.get("state") != "approved" or item.get("approvedVia") != "human" or decision.get("decision") != "approve":
                continue
            if old_items.get((occurrence.get("id"), item.get("key"))) == "approved":
                continue
            found.append({"taskKind": "draft", "variantId": item.get("variantId"), "principal": decision.get("by"), "at": decision.get("at"), "channelId": item.get("channelId")})
    old_tasks = {task.get("id"): task.get("status") for task in _planning(before).get("recurringTasks") or [] if isinstance(task, dict)}
    for task in _planning(after).get("recurringTasks") or []:
        # Setup is counted once, from a draft (or a task created active); a resume or a re-activation after an edit is not setup.
        if not isinstance(task, dict) or task.get("status") != "active" or old_tasks.get(task.get("id"), "draft") != "draft":
            continue
        if (task.get("schedule") or {}).get("kind") == "once":
            continue  # A one-time post, not a recurring workflow.
        found.append({"taskKind": "recurring_setup", "taskId": task.get("id"), "principal": task.get("activatedBy"), "at": task.get("activatedAt")})
    return found


# --- guarded writes ---------------------------------------------------------------------------------------------------

def _note(failures, event, error):
    if failures is not None:
        failures.append(type(error).__name__)
    # The class name only: exception text can carry identifiers or third-party payloads.
    logger.warning(json.dumps({"event": event, "exceptionType": type(error).__name__}))


def guarded(cur, operation, event="time_back.write_failed", failures=None):
    """Run a Time Back write inside a savepoint, so a fault rolls back only Time Back's own statements and never the
    transaction of the outcome that earned it. Returns (result, None) or (None, error); never raises."""
    mark = "time_back_" + uuid.uuid4().hex[:8]
    try:
        cur.execute(f"SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001 - the transaction is already unusable; its owner decides
        _note(failures, event, error)
        return None, error
    try:
        result = operation()
    except Exception as error:  # noqa: BLE001 - Time Back must never fail the outcome that earned it
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
            cur.execute(f"RELEASE SAVEPOINT {mark}")
        except Exception:  # noqa: BLE001
            pass
        _note(failures, event, error)
        return None, error
    try:
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        _note(failures, event, error)
        return None, error
    return result, None


def active_member(cur, workspace_id, user_id):
    if not isinstance(user_id, str) or not UUID.match(user_id):
        return False
    cur.execute("SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, user_id))
    return cur.fetchone() is not None


def baseline(cur, workspace_id, user_id, task_kind):
    cur.execute("SELECT override_seconds FROM public.pr_time_savings_preferences WHERE workspace_id=%s AND user_id=%s AND task_kind=%s", (workspace_id, user_id, task_kind))
    row = cur.fetchone()
    cur.execute("SELECT baseline_seconds FROM public.pr_time_savings_calibrations WHERE workspace_id=%s AND user_id=%s AND task_kind=%s AND source='prompt' ORDER BY created_at DESC,id DESC LIMIT %s", (workspace_id, user_id, task_kind, SAMPLE_WINDOW))
    return resolve_baseline(task_kind, row[0] if row else None, [value for (value,) in cur.fetchall()])


def consume_active(cur, workspace_id, user_id, workflow_keys, now):
    """Measured seconds of these workflows not yet credited to an earlier outcome, credited now. None when nothing was
    measured for them: missing is not zero."""
    if not workflow_keys:
        return None
    cur.execute("SELECT id,active_seconds-consumed_seconds FROM public.pr_active_work_sessions WHERE workspace_id=%s AND user_id=%s AND workflow_key=ANY(%s) FOR UPDATE", (workspace_id, user_id, list(workflow_keys)))
    rows = cur.fetchall()
    if not rows:
        return None
    cur.execute("UPDATE public.pr_active_work_sessions SET consumed_seconds=active_seconds,consumed_at=to_timestamp(%s),updated_at=now() WHERE id=ANY(%s)", (now, [row[0] for row in rows]))
    return min(SESSION_CAP, sum(max(0, value) for _, value in rows))


def record_outcome(cur, workspace_id, beneficiary_user_id, task_kind, outcome_kind, outcome_ref, workflow_keys, occurred_at, metadata=None, now=None):
    """Write the one immutable row a completed outcome earns. "recorded" is False for a duplicate, or when no
    beneficiary can be established (then nothing is written at all). Invalid input raises; callers guard."""
    if task_kind not in OUTCOME_KINDS or outcome_kind != OUTCOME_KINDS[task_kind]:
        raise AlphaError("Unsupported Time Back outcome.")
    if not isinstance(outcome_ref, str) or not OUTCOME_REF.match(outcome_ref):
        raise AlphaError("Invalid Time Back outcome reference.")
    keys = [workflow_keys] if isinstance(workflow_keys, str) else list(workflow_keys or ())
    if any(not isinstance(key, str) or not WORKFLOW_KEY.match(key) for key in keys):
        raise AlphaError("Invalid Time Back workflow key.")
    if type(occurred_at) not in (int, float) or occurred_at <= 0:
        raise AlphaError("Invalid Time Back outcome time.")
    if not active_member(cur, workspace_id, beneficiary_user_id):
        return {"recorded": False, "reason": "no_beneficiary"}
    cur.execute("SELECT 1 FROM public.pr_time_savings_ledger WHERE workspace_id=%s AND task_kind=%s AND outcome_kind=%s AND outcome_ref=%s", (workspace_id, task_kind, outcome_kind, outcome_ref))
    if cur.fetchone():
        return {"recorded": False, "reason": "duplicate"}
    seconds, source, version = baseline(cur, workspace_id, beneficiary_user_id, task_kind)
    active = consume_active(cur, workspace_id, beneficiary_user_id, keys, now if now is not None else occurred_at)
    saved, confidence = saving(seconds, active, source)
    cur.execute(
        "INSERT INTO public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,active_seconds,saved_seconds,"
        "baseline_source,baseline_version,confidence,calculator_version,occurred_at,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s::jsonb) "
        "ON CONFLICT DO NOTHING RETURNING id::text",
        (workspace_id, beneficiary_user_id, task_kind, outcome_kind, outcome_ref, dedupe_key(workspace_id, beneficiary_user_id, task_kind, outcome_kind, outcome_ref),
         seconds, active, saved, source, version, confidence, CALCULATOR_VERSION, occurred_at, json.dumps(clean_metadata(metadata))))
    written = cur.fetchone() is not None
    return {"recorded": written, "reason": None if written else "duplicate", "taskKind": task_kind, "savedSeconds": saved if written else 0, "confidence": confidence}


def conversation_for(cur, workspace_id, variant):
    run = (variant.get("provenance") or {}).get("runId")
    if not isinstance(run, str) or not UUID.match(run):
        return None
    cur.execute("SELECT conversation_id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s", (workspace_id, run.lower()))
    row = cur.fetchone()
    return row[0] if row else None


def _same_text(first, second):
    """Identical wording, ignoring only whitespace. Compared in memory; no text or digest is ever stored."""
    return isinstance(first, str) and isinstance(second, str) and " ".join(first.split()) == " ".join(second.split())


def record_acceptance(cur, workspace_id, state, outcome, now):
    """A generated draft accepted for use (§4.A-B). The first version of a post counts as `draft`; each genuinely
    separate further version (another platform, language or account) counts as `adapt`. A version for a slot already
    counted, a version whose text is identical to one already counted, and a draft that is not Rafii's writing add
    nothing: an identical outcome is never counted twice."""
    variants = {v.get("id"): v for v in state.get("variants") or [] if isinstance(v, dict)}
    variant = variants.get(outcome.get("variantId"))
    if variant is None or not isinstance(variant.get("id"), str) or not ID.match(variant["id"]):
        return {"recorded": False, "reason": "no_variant"}
    revisions = variant.get("revisions") or []
    if not revisions or not isinstance(revisions[0], dict) or revisions[0].get("origin") not in GENERATED_ORIGINS:
        return {"recorded": False, "reason": "not_generated"}
    ref = "variant:" + variant["id"]
    cur.execute("SELECT 1 FROM public.pr_time_savings_ledger WHERE workspace_id=%s AND task_kind IN ('draft','adapt') AND outcome_ref=%s", (workspace_id, ref))
    if cur.fetchone():
        return {"recorded": False, "reason": "duplicate"}
    group = group_ref(variants, variant)
    # The slot is compared exactly as it is stored, so a value the allowlist drops compares the same on both sides.
    metadata = clean_metadata({"platform": variant.get("platform"), "language": variant.get("language"),
                               "channelId": variant.get("channelId") or outcome.get("channelId"), "groupRef": group, "source": "command"})
    slot = (metadata.get("platform"), metadata.get("language"), metadata.get("channelId"))
    cur.execute("SELECT outcome_ref,metadata->>'platform',metadata->>'language',metadata->>'channelId' FROM public.pr_time_savings_ledger "
                "WHERE workspace_id=%s AND task_kind IN ('draft','adapt') AND metadata->>'groupRef'=%s", (workspace_id, group))
    counted = cur.fetchall()
    for other_ref, platform, language, channel in counted:
        if (platform, language, channel) == slot:
            return {"recorded": False, "reason": "version_counted"}
        other = variants.get(other_ref.split(":", 1)[1]) if other_ref.startswith("variant:") else None
        if other is not None and _same_text(other.get("text"), variant.get("text")):
            return {"recorded": False, "reason": "identical_version"}
    kind = "adapt" if counted else "draft"
    keys = [ref]
    if kind == "draft":
        # The composer conversation that wrote it: its measured time belongs to the post's first draft.
        conversation = conversation_for(cur, workspace_id, variant)
        if conversation:
            keys.append("conversation:" + conversation)
    return record_outcome(cur, workspace_id, outcome.get("principal"), kind, OUTCOME_KINDS[kind], ref, keys, outcome["at"], metadata, now)


def record_verified_publish(cur, workspace_id, job, source="worker", failures=None):
    """The worker's verified hook (§4.C, §8.2): one publish row for the person who approved the publication, or who
    granted the standing authority it ran under; both are job.approvedBy, which the worker requires to equal the
    manifest actor. Runs behind a savepoint and never raises. A fault leaves job["timeSavings"] = "pending" in the
    state the worker saves, so the cron repair retries it; the ledger's uniqueness makes every retry safe."""
    try:
        if not isinstance(job, dict) or job.get("state") != "verified":
            return {"recorded": False, "reason": "not_verified"}
        manifest = job.get("manifest") if isinstance(job.get("manifest"), dict) else {}
        verified_at = (job.get("verification") or {}).get("at")
        if (not isinstance(job.get("id"), str) or not ID.match(job["id"]) or job.get("approvedBy") != manifest.get("actor")
                or type(verified_at) not in (int, float) or verified_at <= 0):
            job.pop("timeSavings", None)
            return {"recorded": False, "reason": "no_beneficiary"}
        approver, reference = job["approvedBy"], "job:" + job["id"]
        metadata = {"platform": manifest.get("platform"), "channelId": manifest.get("channelId"), "source": source}
    except Exception as error:  # noqa: BLE001
        _note(failures, "time_back.publish_failed", error)
        return {"recorded": False, "reason": "invalid_job"}
    result, error = guarded(cur, lambda: record_outcome(cur, workspace_id, approver, "publish", OUTCOME_KINDS["publish"], reference, None, verified_at, metadata),
                            "time_back.publish_failed", failures)
    if error is not None:
        job["timeSavings"] = "pending"
        return {"recorded": False, "reason": "pending_repair"}
    job.pop("timeSavings", None)
    return result


def with_time_back(on_verified, time_savings):
    """Fan out the worker's verified hook (§8.2): the existing hook runs first and unchanged, then Time Back, even when
    the first one fails, whose error still reaches the worker as before. Time Back itself never raises."""
    def hook(cur, workspace_id, job):
        try:
            if on_verified is not None:
                on_verified(cur, workspace_id, job)
        finally:
            time_savings.record_verified_publish(cur, workspace_id, job)
    return hook


def repair_pending(cur, limit=10, failures=None):
    """Retry verified publications whose row could not be written. Only workspaces carrying a pending marker are
    touched; the row lock is skipped when busy, so the publishing worker is never blocked."""
    cur.execute("SELECT id::text,revision,state FROM public.pr_workspaces WHERE state->'phase2'->'jobs' @> %s::jsonb AND NOT state ? 'accountDeletion' ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
                (json.dumps([{"timeSavings": "pending"}]), limit))
    repaired = pending = 0
    for workspace_id, revision, raw in cur.fetchall():
        state = json.loads(raw) if isinstance(raw, str) else raw
        for job in _jobs(state):
            if job.get("timeSavings") != "pending":
                continue
            result = record_verified_publish(cur, workspace_id, job, source="repair", failures=failures)
            pending += job.get("timeSavings") == "pending"
            repaired += bool(result.get("recorded"))
        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), workspace_id, revision))
    return {"repaired": repaired, "pending": pending}


# --- activity, calibration, summary -----------------------------------------------------------------------------------

def _bounded_int(value, low, high, message):
    if type(value) is not int or not low <= value <= high:
        raise AlphaError(message)
    return value


def upsert_active_session(cur, workspace_id, user_id, payload, now):
    """A cumulative, idempotent heartbeat (§6.3): only a higher sequence is applied, the stored value never decreases,
    and it can grow no faster than wall-clock time since the previous beat, up to the four-hour cap."""
    if not isinstance(payload, dict):
        raise AlphaError("Expected an activity heartbeat.")
    key, workflow, kind = payload.get("clientSessionKey"), payload.get("workflowKey"), payload.get("taskKind")
    if not isinstance(key, str) or not SESSION_KEY.match(key):
        raise AlphaError("Invalid activity session.")
    match = WORKFLOW_KEY.match(workflow) if isinstance(workflow, str) else None
    if not match or match.group(1) not in WORKFLOW_PREFIXES:
        raise AlphaError("Invalid workflow key.")
    if kind not in OUTCOME_KINDS:
        raise AlphaError("Unsupported Time Back task kind.")
    seconds = _bounded_int(payload.get("activeSeconds"), 0, 86400, "Invalid active seconds.")
    sequence = _bounded_int(payload.get("sequence"), 1, 1_000_000, "Invalid heartbeat sequence.")
    closing = payload.get("closed") is True
    cur.execute("SELECT active_seconds,sequence,extract(epoch from last_active_at),workflow_key,task_kind FROM public.pr_active_work_sessions WHERE workspace_id=%s AND user_id=%s AND client_session_key=%s FOR UPDATE",
                (workspace_id, user_id, key))
    row = cur.fetchone()
    if row is None:
        value = min(seconds, FIRST_HEARTBEAT, SESSION_CAP)
        cur.execute("INSERT INTO public.pr_active_work_sessions(workspace_id,user_id,workflow_key,client_session_key,task_kind,active_seconds,sequence,started_at,last_active_at,closed_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),CASE WHEN %s THEN to_timestamp(%s) END) ON CONFLICT (workspace_id,user_id,client_session_key) DO NOTHING RETURNING 1",
                    (workspace_id, user_id, workflow, key, kind, value, sequence, now - value, now, closing, now))
        if cur.fetchone() is None:
            return {"accepted": False, "activeSeconds": 0, "sequence": 0}
        return {"accepted": True, "activeSeconds": value, "sequence": sequence}
    active, last_sequence, last_at, stored_workflow, stored_kind = row
    if stored_workflow != workflow or stored_kind != kind:
        raise AlphaError("This activity session belongs to another workflow.", 409)
    if sequence <= last_sequence:
        return {"accepted": False, "activeSeconds": active, "sequence": last_sequence}  # A retry or a late beat.
    value = min(max(active, seconds), active + max(0, int(now - float(last_at))) + HEARTBEAT_SLACK, SESSION_CAP)
    cur.execute("UPDATE public.pr_active_work_sessions SET active_seconds=%s,sequence=%s,last_active_at=to_timestamp(%s),updated_at=now(),closed_at=CASE WHEN %s THEN to_timestamp(%s) ELSE closed_at END "
                "WHERE workspace_id=%s AND user_id=%s AND client_session_key=%s", (value, sequence, now, closing, now, workspace_id, user_id, key))
    return {"accepted": True, "activeSeconds": value, "sequence": sequence}


def _preference(cur, workspace_id, user_id, kind, column, value):
    cur.execute(f"INSERT INTO public.pr_time_savings_preferences(workspace_id,user_id,task_kind,{column},updated_at) VALUES(%s,%s,%s,%s,now()) "
                f"ON CONFLICT (workspace_id,user_id,task_kind) DO UPDATE SET {column}=excluded.{column},updated_at=now()", (workspace_id, user_id, kind, value))


def record_calibration(cur, workspace_id, user_id, payload, now):
    """A prompt answer (a sample), a dismissed prompt (no sample), or an explicit settings override and its removal.
    Answering or dismissing both start the 30-day quiet period for that task kind."""
    if not isinstance(payload, dict):
        raise AlphaError("Expected a calibration.")
    kind, source = payload.get("taskKind"), payload.get("source")
    if kind not in OUTCOME_KINDS:
        raise AlphaError("Unsupported Time Back task kind.")
    if source not in ("prompt", "settings_override"):
        raise AlphaError("Choose a prompt answer or a settings override.")
    if source == "prompt" and payload.get("dismissed") is True:
        cur.execute("INSERT INTO public.pr_time_savings_preferences(workspace_id,user_id,task_kind,prompted_at,updated_at) VALUES(%s,%s,%s,to_timestamp(%s),now()) "
                    "ON CONFLICT (workspace_id,user_id,task_kind) DO UPDATE SET prompted_at=excluded.prompted_at,updated_at=now()", (workspace_id, user_id, kind, now))
        return {"taskKind": kind, "source": source, "dismissed": True}
    if source == "settings_override" and payload.get("clear") is True:
        _preference(cur, workspace_id, user_id, kind, "override_seconds", None)
        return {"taskKind": kind, "source": source, "cleared": True}
    seconds = _bounded_int(payload.get("manualSeconds"), MIN_BASELINE, MAX_BASELINE, "Choose a time between 1 minute and 4 hours.")
    cur.execute("INSERT INTO public.pr_time_savings_calibrations(workspace_id,user_id,task_kind,baseline_seconds,source,created_at) VALUES(%s,%s,%s,%s,%s,to_timestamp(%s))",
                (workspace_id, user_id, kind, seconds, source, now))
    if source == "prompt":
        cur.execute("INSERT INTO public.pr_time_savings_preferences(workspace_id,user_id,task_kind,prompted_at,updated_at) VALUES(%s,%s,%s,to_timestamp(%s),now()) "
                    "ON CONFLICT (workspace_id,user_id,task_kind) DO UPDATE SET prompted_at=excluded.prompted_at,updated_at=now()", (workspace_id, user_id, kind, now))
    else:
        _preference(cur, workspace_id, user_id, kind, "override_seconds", seconds)
    return {"taskKind": kind, "source": source, "manualSeconds": seconds}


def calibration_state(cur, workspace_id, user_id, now):
    """Current baselines and which kinds may be asked about: a kind this person completed in the last week, with no
    override, fewer than three answers and no prompt answered or dismissed in 30 days. Never before any value."""
    cur.execute("SELECT task_kind,override_seconds,extract(epoch from prompted_at) FROM public.pr_time_savings_preferences WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_id))
    preferences = {kind: (override, float(prompted) if prompted is not None else None) for kind, override, prompted in cur.fetchall()}
    cur.execute("SELECT task_kind,(array_agg(baseline_seconds ORDER BY created_at DESC,id DESC))[1:%s] FROM public.pr_time_savings_calibrations WHERE workspace_id=%s AND user_id=%s AND source='prompt' GROUP BY task_kind",
                (SAMPLE_WINDOW, workspace_id, user_id))
    samples = {kind: list(values) for kind, values in cur.fetchall()}
    cur.execute("SELECT DISTINCT task_kind FROM public.pr_time_savings_ledger WHERE workspace_id=%s AND beneficiary_user_id=%s AND occurred_at >= to_timestamp(%s)", (workspace_id, user_id, now - PROMPT_RECENCY))
    recent = {kind for (kind,) in cur.fetchall()}
    baselines, due = [], []
    for kind in OUTCOME_KINDS:
        override, prompted = preferences.get(kind, (None, None))
        seconds, source, _ = resolve_baseline(kind, override, samples.get(kind, ()))
        # What applies without an override (personalized or default), so a setting can say what clearing it returns to.
        automatic = resolve_baseline(kind, None, samples.get(kind, ()))[0]
        baselines.append({"taskKind": kind, "seconds": seconds, "source": source, "samples": len(samples.get(kind, ())), "defaultSeconds": DEFAULT_BASELINES[kind], "automaticSeconds": automatic})
        if kind in recent and override is None and len(samples.get(kind, ())) < PERSONALIZE_AFTER and (prompted is None or now - prompted >= PROMPT_INTERVAL):
            due.append(kind)
    return {"due": due, "baselines": baselines, "personalizeAfter": PERSONALIZE_AFTER}


def summarize(cur, workspace_id, user_id, now, range_key="30d", time_zone=""):
    """The person's own Time Back for a window (§9). Breakdown minutes add up exactly to the displayed total."""
    since = range_start(range_key, now, time_zone)
    window = " AND occurred_at >= to_timestamp(%s)" if since is not None else ""
    cur.execute("SELECT task_kind,confidence,count(*),coalesce(sum(saved_seconds),0) FROM public.pr_time_savings_ledger WHERE workspace_id=%s AND beneficiary_user_id=%s" + window + " GROUP BY task_kind,confidence",
                (workspace_id, user_id) + ((since,) if since is not None else ()))
    kinds, counts, weights = {}, dict.fromkeys(CONFIDENCE, 0), dict.fromkeys(CONFIDENCE, 0)
    for kind, level, count, saved in cur.fetchall():
        entry = kinds.setdefault(kind, [0, 0])
        entry[0] += int(saved)
        entry[1] += int(count)
        counts[level] += int(count)
        weights[level] += int(saved)
    ordered = [kind for kind in TASK_KINDS if kind in kinds]
    breakdown = [{"taskKind": kind, "savedSeconds": kinds[kind][0], "minutes": minutes, "count": kinds[kind][1]}
                 for kind, minutes in zip(ordered, allocate_minutes([kinds[kind][0] for kind in ordered]))]
    completed = sum(item["count"] for item in breakdown)
    total = sum(item["savedSeconds"] for item in breakdown)
    calibration = calibration_state(cur, workspace_id, user_id, now)
    return {
        "range": range_key, "since": since, "until": now,
        "state": "ready" if completed else "empty",
        "totalSavedSeconds": total, "totalMinutes": sum(item["minutes"] for item in breakdown), "completedTasks": completed,
        # The label covering the most saved time (then the most rows); a tie goes to the more conservative one.
        "basis": max(CONFIDENCE, key=lambda level: (weights[level], counts[level], -CONFIDENCE.index(level))) if completed else None,
        "breakdown": breakdown, "confidence": counts,
        "calculatorVersion": CALCULATOR_VERSION,
        "hasCalibrationPrompt": bool(calibration["due"]), "calibration": calibration,
    }


def sweep(cur, now):
    """Activity aggregates older than the retention window can no longer be credited; drop them."""
    cur.execute("DELETE FROM public.pr_active_work_sessions WHERE last_active_at < to_timestamp(%s)", (now - SESSION_RETENTION,))
    return cur.rowcount


class TimeSavingsService:
    """The HTTP surface (§9) and the hooks the worker, the repository and the cron call."""

    def __init__(self, repository, clock=time.time):
        self.repository = repository
        self.clock = clock
        # Exception class names of guarded writes that failed, for tests and the cron result; never messages.
        self.failures = []

    @contextmanager
    def _member(self, token, workspace_id, write=False):
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError("Time back is personal. Use an interactive session.", 403, code="token_scope_denied")
        if not isinstance(workspace_id, str) or not UUID.match(workspace_id):
            raise AlphaError("Workspace unavailable.", 403)
        principal = self.repository.verify_session(token)
        with self.repository.connection_factory() as db:
            with db.cursor() as cur:
                # A plain membership read, never a row lock on the workspace the publishing worker claims.
                cur.execute("SELECT w.state ? 'accountDeletion',coalesce(p.time_zone,'') FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id "
                            "JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, principal))
                row = cur.fetchone()
                if not row:
                    raise AlphaError("Workspace unavailable.", 403)
                if row[0] and write:
                    raise AlphaError("Account deletion is pending. Only deletion can continue.", 409, code="account_deletion_pending")
                yield cur, principal, row[1]

    def summary(self, workspace_id, token, range_key="30d"):
        with self._member(token, workspace_id) as (cur, principal, zone):
            return summarize(cur, workspace_id, principal, self.clock(), range_key, zone)

    def activity(self, workspace_id, token, payload):
        from .hosted import throttle
        with self._member(token, workspace_id, write=True) as (cur, principal, _):
            throttle(cur, f"time-back-activity:{workspace_id}:{principal}", 30, 60)
            return upsert_active_session(cur, workspace_id, principal, payload, self.clock())

    def calibrate(self, workspace_id, token, payload):
        from .hosted import throttle
        with self._member(token, workspace_id, write=True) as (cur, principal, _):
            throttle(cur, f"time-back-calibration:{workspace_id}:{principal}", 20, 60)
            result = record_calibration(cur, workspace_id, principal, payload, self.clock())
            return {**result, "calibration": calibration_state(cur, workspace_id, principal, self.clock())}

    def record_verified_publish(self, cur, workspace_id, job):
        return record_verified_publish(cur, workspace_id, job, failures=self.failures)

    def capture(self, cur, workspace_id, before, after, principal):
        """Repository effect: the drafts, adaptations and automation activations a command completed, recorded in its
        transaction, each behind its own savepoint. A command that completed nothing costs no SQL."""
        try:
            outcomes = completed_outcomes(before, after)
        except Exception as error:  # noqa: BLE001 - an unexpected state shape must not fail the command
            _note(self.failures, "time_back.capture_failed", error)
            return
        now = self.clock()
        for outcome in outcomes:
            if type(outcome.get("at")) not in (int, float) or outcome["at"] <= 0:
                outcome["at"] = now
            if outcome["taskKind"] == "recurring_setup":
                task_id = outcome.get("taskId")
                if not isinstance(task_id, str) or not ID.match(task_id):
                    continue
                operation = lambda ref="automation:" + task_id, outcome=outcome: record_outcome(
                    cur, workspace_id, outcome.get("principal"), "recurring_setup", OUTCOME_KINDS["recurring_setup"], ref, [ref], outcome["at"], {"source": "command"}, now)
            else:
                operation = lambda outcome=outcome: record_acceptance(cur, workspace_id, after, outcome, now)
            guarded(cur, operation, "time_back.capture_failed", self.failures)

    def maintain(self, limit=10):
        """Cron: repair pending publish rows, drop stale activity. Never raises."""
        try:
            with self.repository.connection_factory() as db:
                with db.cursor() as cur:
                    repaired, error = guarded(cur, lambda: repair_pending(cur, limit, self.failures), "time_back.repair_failed", self.failures)
                    dropped, _ = guarded(cur, lambda: sweep(cur, self.clock()), "time_back.sweep_failed", self.failures)
            return {"status": "ok" if error is None else "unavailable", **(repaired or {"repaired": 0, "pending": 0}), "sessionsDropped": dropped or 0}
        except Exception as error:  # noqa: BLE001 - the cron keeps running every other job
            _note(self.failures, "time_back.maintain_failed", error)
            return {"status": "unavailable", "repaired": 0, "pending": 0, "sessionsDropped": 0}
