"""Product event taxonomy (PRD §8.6, CONTRACTS §8.C): one best-effort writer for `public.pr_product_events`.

What is recorded. Journey and adoption milestones as ids and enums only: the workspace, the person who did it (None for
a provider- or system-caused event), the event name from TAXONOMY, a dedupe key `<event>:<entity id>:<version>` and the
event's allowlisted enum properties. Never draft text, titles, prompts, URLs, emails, provider payloads or reasons.

How. `record`/`record_many` write inside the caller's transaction behind their own SAVEPOINT, so a fault rolls back only
the event insert and the customer's command commits exactly as before; they never raise. Production may run this code
before the owner applies the migrations it reads: a missing table, column, grant or check (UndefinedTable,
UndefinedColumn, InsufficientPrivilege, CheckViolation) is logged once per process by exception class and further
attempts are skipped for ten minutes. `capture` is a repository effect (hosted.PostgresWorkspaceRepository.command)
that derives the state-backed events from one command's before/after workspace state; the other call sites name their
event where the owning service records it (bootstrap, OAuth, the publishing worker, automation runs, research, the
humanizer quality check).

Workspaces classified internal/test/demo are recorded like any other: the founder views exclude them, never the writer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid

from .contracts import LIMITS
from .learning_signals import EDIT_ORIGINS

log = logging.getLogger("postriff.product_events")

# Event -> the enum properties it may carry. Anything else is dropped before SQL.
TAXONOMY = {
    "workspace.created": frozenset({"plan"}),
    "channel.connected": frozenset({"provider"}),
    "channel.disconnected": frozenset({"provider", "cause"}),
    "voice.created": frozenset(),
    "brand.created": frozenset(),
    "draft.created": frozenset({"feature", "voice"}),
    "draft.edited": frozenset({"feature"}),
    "draft.discarded": frozenset({"feature"}),
    "review.approved": frozenset({"surface"}),
    "post.scheduled": frozenset({"platform", "via"}),
    "publish.verified": frozenset({"platform"}),
    "publish.failed": frozenset({"platform"}),
    "campaign.created": frozenset(),
    "automation.created": frozenset({"schedule"}),
    "automation.run_completed": frozenset({"outcome"}),
    "suggestion.shown": frozenset({"kind"}),
    "suggestion.accepted": frozenset({"kind"}),
    "research.completed": frozenset({"source", "outcome"}),
    "humanizer.applied": frozenset({"surface", "outcome"}),
}
# draft.created properties.feature: how the draft was started (PRD §8.6 write_like_me | agent | quick_start, plus the
# automation and plain writer entry points). properties.voice says whether personalised voice samples were used.
DRAFT_FEATURES = ("agent", "automation", "quick_start", "write_like_me", "writer")
AGENT_RUN_PREFIXES = frozenset({"agent-draft", "agent-rewrite"})   # agent_runtime_v2.domain_tools writing runs
RUN_OUTCOMES = frozenset({"drafted", "skipped", "failed", "source_unavailable"})   # automation_runs terminal lifecycles
NOT_INSTALLED = frozenset({"UndefinedTable", "UndefinedColumn", "InsufficientPrivilege", "CheckViolation"})
SUSPEND_SECONDS = 600
MAX_EVENTS = 100   # per command; a suggestion refresh is the largest batch in practice

ENUM = re.compile(r"[a-z][a-z0-9_-]{0,39}")
PLATFORM = re.compile(r"[A-Za-z][A-Za-z0-9 ._-]{0,39}")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,119}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
INSERT = "INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key) VALUES "
ROW = "(%s,%s,%s,%s::jsonb,%s)"

_STATE = {"suspended_until": 0.0, "logged": set()}
_clock = time.monotonic


def reset():
    """Tests: forget a suspension and the once-per-process log marks."""
    _STATE["suspended_until"] = 0.0
    _STATE["logged"] = set()


def suspended():
    return _clock() < _STATE["suspended_until"]


def _note(event, error):
    # The class name only: exception text can carry identifiers, SQL or third-party payloads.
    log.warning(json.dumps({"event": event, "exceptionType": type(error).__name__}, sort_keys=True))


def _failed(error):
    name = type(error).__name__
    if name in NOT_INSTALLED:
        # Code deployed ahead of its migration: stop trying for a while and say so once per process.
        _STATE["suspended_until"] = _clock() + SUSPEND_SECONDS
        if name not in _STATE["logged"]:
            _STATE["logged"].add(name)
            log.warning(json.dumps({"event": "product_events.not_installed", "exceptionType": name, "retryAfterSeconds": SUSPEND_SECONDS}, sort_keys=True))
        return
    _note("product_events.write_failed", error)


# Property names whose values are bounded non-negative integers (counts), declared through register(counts=...).
COUNTS = set()
EVENT_NAME = re.compile(r"[a-z][a-z_]{0,39}\.[a-z][a-z_]{0,39}")
PROPERTY_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_COUNT = 1_000_000


def register(events, *, counts=()):
    """Add events to the one taxonomy from another product area (one writer, one table): {event: {property, ...}}.
    Names are `<area>.<verb>` in lowercase; properties are enum strings unless listed in `counts` (non-negative integers
    up to MAX_COUNT). Registering the same event with the same properties again is a no-op; a different set is refused."""
    staged = {}
    for name, properties in dict(events).items():
        props = frozenset(properties)
        if not isinstance(name, str) or not EVENT_NAME.fullmatch(name) or any(not isinstance(p, str) or not PROPERTY_NAME.fullmatch(p) for p in props):
            raise ValueError("invalid product event registration")
        if name in TAXONOMY and TAXONOMY[name] != props:
            raise ValueError("conflicting product event registration: " + name)
        staged[name] = props
    count_names = frozenset(counts)
    if any(not isinstance(p, str) or not PROPERTY_NAME.fullmatch(p) for p in count_names):
        raise ValueError("invalid count property")
    TAXONOMY.update(staged)
    COUNTS.update(count_names)


def _value(key, value):
    if key in COUNTS:
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT else None
    if key == "platform":
        return value if isinstance(value, str) and (value in LIMITS or PLATFORM.fullmatch(value)) else None
    return value if isinstance(value, str) and ENUM.fullmatch(value) else None


def row(workspace_id, user_id, event, entity_id, version, properties=None):
    """The validated insert parameters, or None when the event cannot be recorded without content or invalid ids."""
    if event not in TAXONOMY or not isinstance(workspace_id, str) or not UUID.fullmatch(workspace_id):
        return None
    user = user_id if isinstance(user_id, str) and UUID.fullmatch(user_id) else None
    entity = str(entity_id) if isinstance(entity_id, (str, int)) and not isinstance(entity_id, bool) else ""
    revision = str(version) if isinstance(version, (str, int)) and not isinstance(version, bool) else ""
    if not ENTITY.fullmatch(entity) or not VERSION.fullmatch(revision):
        return None
    allowed = TAXONOMY[event]
    props = {}
    for key, value in (properties if isinstance(properties, dict) else {}).items():
        clean = _value(key, value) if key in allowed else None
        if clean is not None:
            props[key] = clean
    dedupe = f"{event}:{entity}:{revision}"
    if len(dedupe) > 200:
        dedupe = f"{event}:{hashlib.sha256(entity.encode()).hexdigest()[:40]}:{revision}"
    return (workspace_id, user, event, json.dumps(props, sort_keys=True, separators=(",", ":")), dedupe)


def record_many(cur, workspace_id, user_id, events):
    """Write [(event, entity_id, version, properties)] in one statement behind one SAVEPOINT. Returns the number of rows
    PostgreSQL reported written (0 for duplicates, invalid input, a suspension or a failure). Never raises."""
    try:
        unique = {}
        for item in list(events)[:MAX_EVENTS]:
            built = row(workspace_id, user_id, *item)
            if built is not None:
                unique.setdefault((built[2], built[4]), built)   # one row per (event, dedupe key) in a batch
        rows = list(unique.values())
    except Exception as error:  # noqa: BLE001 - a malformed call site must not fail the command either
        _note("product_events.invalid", error)
        return 0
    if not rows or suspended():
        return 0
    mark = "product_event_" + uuid.uuid4().hex[:8]
    try:
        cur.execute(f"SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001 - the caller's transaction is already unusable; its owner decides
        _failed(error)
        return 0
    try:
        cur.execute(INSERT + ",".join([ROW] * len(rows)) + " ON CONFLICT DO NOTHING", [value for item in rows for value in item])
        written = getattr(cur, "rowcount", None)
    except Exception as error:  # noqa: BLE001 - instrumentation must never fail the customer's command
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
            cur.execute(f"RELEASE SAVEPOINT {mark}")
        except Exception:  # noqa: BLE001
            pass
        _failed(error)
        return 0
    try:
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        _failed(error)
        return 0
    return written if isinstance(written, int) and not isinstance(written, bool) and written >= 0 else len(rows)


def record(cur, workspace_id, user_id, event, entity_id, version, properties=None):
    """One event (see record_many). True when PostgreSQL reported a new row."""
    return record_many(cur, workspace_id, user_id, [(event, entity_id, version, properties)]) > 0


# --- worker call sites -------------------------------------------------------------------------------------------------

def publish_outcome(cur, workspace_id, job, state):
    """hosted_worker: a job that reached `verified` or `failed`. The version is the attempt count, so a failure after a
    later attempt is a new event and a replay of the same outcome is not."""
    if state not in ("verified", "failed") or not isinstance(job, dict) or not job.get("id"):
        return False
    manifest = job.get("manifest") if isinstance(job.get("manifest"), dict) else {}
    attempts = len(job.get("attempts") or []) if isinstance(job.get("attempts"), list) else 0
    return record(cur, workspace_id, job.get("approvedBy"), "publish." + state, job["id"], max(1, attempts), {"platform": manifest.get("platform")})


def run_completed(cur, workspace_id, actor, occurrence_id, lifecycle):
    """automation_runs: one run of an automation ended (drafted, skipped, failed or source unavailable)."""
    if lifecycle not in RUN_OUTCOMES:
        return False
    return record(cur, workspace_id, actor, "automation.run_completed", occurrence_id, lifecycle, {"outcome": lifecycle})


def request_entity(workspace_id, key):
    """An opaque, stable entity id for a keyed request (research): never the key or the query itself."""
    return "req-" + hashlib.sha256(f"{workspace_id}:{key}".encode()).hexdigest()[:32]


def humanizer_applied(cur, workspace_id, user_id, state, checked, surface):
    """coworker quality checks: one humanizer.applied per draft the humanizer evaluated, versioned by the draft revision.
    `checked` is [(variant id, outcome status)]; drafts no longer in `state` are skipped."""
    variants = _by_id(_items(_dict(state).get("variants")))
    events = [("humanizer.applied", variant_id, _revision(variants[variant_id].get("revision")), {"surface": surface, "outcome": outcome})
              for variant_id, outcome in checked if isinstance(variant_id, str) and variant_id in variants]
    return record_many(cur, workspace_id, user_id, events) if events else 0


# --- state-backed events (repository effect) -----------------------------------------------------------------------------

def _items(value):
    return [item for item in value if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]] if isinstance(value, list) else []


def _by_id(items):
    return {item["id"]: item for item in items}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _planning(state, key):
    return _items(_dict(_dict(_dict(state).get("raffi")).get("campaignPlanning")).get(key))


def _phase2(state, key):
    return _items(_dict(_dict(state).get("phase2")).get(key))


def _revision(value, default=1):
    return value if type(value) is int and value > 0 else default


def run_id(variant):
    value = _dict(variant.get("provenance")).get("runId") or variant.get("runId")
    return value if isinstance(value, str) and UUID.fullmatch(value) else None


def personalized(variant):
    return bool(variant.get("voiceBindings") or variant.get("voiceSourceIds"))


def draft_feature(state, variant, runs=None):
    """How a draft was started: the agent's writing tools, an automation, Quick start, the writer in the person's own
    voice (Write like me) or the plain writer. `runs` maps run id -> {prefix, quickStart} (from pr_agent_runs)."""
    run = (runs or {}).get(run_id(variant)) or {}
    if run.get("prefix") in AGENT_RUN_PREFIXES:
        return "agent"
    if isinstance(variant.get("automation"), dict) and variant["automation"]:
        return "automation"
    sources = set(variant.get("sourceIds") or []) if isinstance(variant.get("sourceIds"), list) else set()
    if run.get("quickStart") or any(isinstance(s, dict) and s.get("id") in sources and _dict(s.get("origin")).get("kind") == "quick_start"
                                    for s in _dict(state).get("sources") or []):
        return "quick_start"
    return "write_like_me" if personalized(variant) else "writer"


def draft_changes(before, after):
    """[(event, variant, version)]: drafts the command created, edited (a person's edit) or discarded ("don't use")."""
    old = _by_id(_items(_dict(before).get("variants")))
    found = []
    for variant in _items(_dict(after).get("variants")):
        prior = old.get(variant["id"])
        if prior is None:
            found.append(("draft.created", variant, 1))
            continue
        revision = variant.get("revision")
        revisions = variant.get("revisions") if isinstance(variant.get("revisions"), list) else []
        last = revisions[-1] if revisions and isinstance(revisions[-1], dict) else {}
        if type(revision) is int and revision > _revision(prior.get("revision"), 0) and last.get("origin") in EDIT_ORIGINS:
            found.append(("draft.edited", variant, revision))
        if variant.get("rejected") is True and prior.get("rejected") is not True:
            found.append(("draft.discarded", variant, _revision(revision)))
    return found


def state_events(workspace_id, before, after):
    """[(event, entity_id, version, properties)] for the non-draft events one command implies. Pure; ids and enums only."""
    before, after = _dict(before), _dict(after)
    events = []
    speaker, prior_speaker = _dict(after.get("speaker")), _dict(before.get("speaker"))
    active = speaker.get("activeRevision")
    if type(active) is int and active != prior_speaker.get("activeRevision"):
        events.append(("voice.created", speaker.get("id") or f"{workspace_id}.speaker", active, {}))
    hub, prior_hub = _dict(after.get("brandHub")), _dict(before.get("brandHub"))
    if isinstance(hub.get("mode"), str) and hub["mode"].strip() and not (isinstance(prior_hub.get("mode"), str) and prior_hub["mode"].strip()):
        events.append(("brand.created", hub.get("id") or f"{workspace_id}.brand", 1, {}))
    # A person approving a draft: an exact Queue review, or an automation post approved by a person. Standing owner
    # pre-authorisation is not a person's review. One event per draft revision, whichever surface came first.
    old_reviews = _by_id(_phase2(before, "reviews"))
    jobs = _by_id(_phase2(after, "jobs"))
    for review in _phase2(after, "reviews"):
        if review.get("status") != "approved" or _dict(old_reviews.get(review["id"])).get("status") == "approved":
            continue
        job = _dict(jobs.get(review.get("jobId")))
        automation = _dict(job.get("automation"))
        manifest = _dict(review.get("manifest"))
        if automation.get("approvedVia") == "owner_preauthorization" or not manifest.get("variantId"):
            continue
        events.append(("review.approved", manifest["variantId"], _revision(manifest.get("contentRevision")), {"surface": "automation" if automation else "queue"}))
    old_items = {(occurrence["id"], item.get("key")): item.get("state") for occurrence in _planning(before, "occurrences")
                 for item in occurrence.get("items") or [] if isinstance(item, dict)}
    for occurrence in _planning(after, "occurrences"):
        for item in occurrence.get("items") or []:
            if not isinstance(item, dict):
                continue
            decision = _dict(item.get("decision"))
            if item.get("state") != "approved" or item.get("approvedVia") != "human" or decision.get("decision") != "approve" or not item.get("variantId"):
                continue
            if old_items.get((occurrence["id"], item.get("key"))) == "approved":
                continue
            events.append(("review.approved", item["variantId"], _revision(decision.get("variantRevision") or item.get("variantRevision")), {"surface": "automation"}))
    old_jobs = _by_id(_phase2(before, "jobs"))
    for job in _phase2(after, "jobs"):
        if job["id"] in old_jobs:
            continue
        standing = _dict(job.get("automation")).get("approvedVia") == "owner_preauthorization"
        events.append(("post.scheduled", job["id"], 1, {"platform": _dict(job.get("manifest")).get("platform"), "via": "standing" if standing else "person"}))
    old_campaigns = _by_id(_planning(before, "campaigns"))
    for campaign in _planning(after, "campaigns"):
        # An automation's own brief is created with it; automation.created counts that.
        if campaign["id"] not in old_campaigns and campaign.get("kind") != "automation":
            events.append(("campaign.created", campaign["id"], 1, {}))
    old_tasks = _by_id(_planning(before, "recurringTasks"))
    for task in _planning(after, "recurringTasks"):
        kind = _dict(task.get("schedule")).get("kind")
        if task["id"] not in old_tasks and kind != "once":   # a one-time post is not an automation
            events.append(("automation.created", task["id"], 1, {"schedule": kind}))
    old_suggestions = _by_id(_items(_dict(before.get("raffi")).get("suggestions")))
    for suggestion in _items(_dict(after.get("raffi")).get("suggestions")):
        prior = old_suggestions.get(suggestion["id"])
        if prior is None:
            events.append(("suggestion.shown", suggestion["id"], 1, {"kind": suggestion.get("kind")}))
        if suggestion.get("status") == "accepted" and _dict(prior).get("status") != "accepted":
            events.append(("suggestion.accepted", suggestion["id"], 1, {"kind": suggestion.get("kind")}))
    return events


def _run_kinds(cur, workspace_id, run_ids):
    """{run id: {prefix, quickStart}} for the runs behind new or changed drafts: one bounded read behind a SAVEPOINT."""
    ids = sorted({value for value in run_ids if value})[:50]
    if not ids:
        return {}
    mark = "product_event_runs_" + uuid.uuid4().hex[:8]
    try:
        cur.execute(f"SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        _failed(error)
        return {}
    try:
        cur.execute("SELECT id::text,split_part(idempotency_key,':',1),coalesce(usage ? 'quickStart',false) FROM public.pr_agent_runs "
                    "WHERE workspace_id=%s AND id=ANY(%s::uuid[])", (workspace_id, ids))
        rows = cur.fetchall() or []
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
            cur.execute(f"RELEASE SAVEPOINT {mark}")
        except Exception:  # noqa: BLE001
            pass
        _failed(error)
        return {}
    return {str(item[0]): {"prefix": item[1], "quickStart": bool(item[2])} for item in rows if item and len(item) >= 3}


def capture(cur, workspace_id, before, after, principal):
    """Repository effect: the taxonomy events one command implies, written in its transaction. Never raises; a command
    that changed nothing tracked costs no SQL."""
    if suspended():
        return 0
    try:
        if not isinstance(after, dict) or _dict(after.get("workspace")).get("sample"):
            return 0
        before = before if isinstance(before, dict) else {}
        events = state_events(workspace_id, before, after)
        drafts = draft_changes(before, after)
        if drafts:
            runs = _run_kinds(cur, workspace_id, [run_id(variant) for _, variant, _ in drafts])
            for event, variant, version in drafts:
                properties = {"feature": draft_feature(after, variant, runs)}
                if event == "draft.created":
                    properties["voice"] = "personalized" if personalized(variant) else "neutral"
                events.append((event, variant["id"], version, properties))
    except Exception as error:  # noqa: BLE001 - an unexpected state shape must not fail the command
        _note("product_events.capture_failed", error)
        return 0
    return record_many(cur, workspace_id, principal, events) if events else 0
