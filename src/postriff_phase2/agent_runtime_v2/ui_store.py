"""Lane F — artifact storage, CAS revisions, leases, private replay events and UI state (02-CONTRACTS §3, §5; migration 102).

Frozen entry points (signatures fixed by A, A-DECISIONS D-A18..D-A22 and Amendment 2 D-A32..D-A39; "ext" = optional extension):
- create_or_resume_artifact(cur, auth, parent_run_id, slot, idempotency_key, *, surface, manifest, projection, kind='generate',
  retry_of=None, lease_owner, base=None) -> dict ArtifactLease {artifact, attempt, created, producer, replay_cursor} (D-A33 shapes).
  Same key -> same attempt; one live producer per (artifact, target revision) via the partial unique index; records
  body.agent.uiArtifacts on the message. `base` = {revision, sourceHash, instruction, selection?} for kind='edit' (D-A32);
  kind='repair' + retry_of=<failed initial attempt> is the single automatic repair. ext: library {libraryHash, libraryVersion,
  languageVersion, promptHash}.
- append_event(conn_or_cur, artifact_id, attempt_id, revision, kind, payload) -> dict UiEventV1 (allocates monotonic seq;
  ui.heartbeat is never persisted, D-A36)
- checkpoint(conn_or_cur, attempt_id, source, *, lease_owner) -> None   (outside the workspace lock; lease-owner checked; renews the
  lease; queued -> streaming; raises 409 ui_lease_lost (owner mismatch / lease gone) or ui_attempt_closed (canceled, reaped, ended))
- commit_ui_revision(cur, auth, patch, validation) -> dict UiArtifactV1 (atomic CAS on baseRevision/baseSourceHash; immutable revision)
- finish_attempt(cur, attempt_id, state, reason=None, usage=None) -> dict attempt (legal transitions; idempotent on the same state).
  D-A39: lane B's ui_metering is the only writer of the accounting columns (reservation_id, provider_attempts, usage,
  cost_usd_micro, cost_state); this module never writes them.
- persist_ui_state(cur, auth, artifact_id, expected_state_revision, patch) -> dict (declared persistable fields only; CAS)
- snapshot_http(runtime, workspace_id, token, artifact_id) -> dict {artifact, manifest(public), revisions, attempt, compatibility,
  display, access, lastSeq}
- by_message_http(runtime, workspace_id, token, message_id) -> dict {messageId, artifacts: [snapshot...]}
- persist_state_http(runtime, workspace_id, token, artifact_id, request) -> dict
- events_after(cur, auth, artifact_id, after, limit) -> list[dict UiEventV1]
- selection_context(cur, auth, ui_context) -> dict | None  ({references:[{type, kind, id, title}], note} in the order shown)
- reap_expired(cur, workspace_id, now) -> int  (interrupted leases; unknown usage stays held via ui_metering.settle_attempt)
  + reap_all(connection_factory) for the cron worker; attempt_state(), replay_view() for producers/replayers (ext)

Rules this module keeps (spec §7, 02-CONTRACTS §5, A-DECISIONS D-A18..D-A22):
- Every read and write is scoped by the authenticated workspace AND the artifact scope. A founder artifact (or any artifact of an
  `agent:founder:` run) is the same 404 as a missing one on consumer routes, and a consumer artifact is 404 on founder routes.
- A ready revision is immutable (pr_ui_revisions). An edit commits only when its base revision and base source hash still match;
  the previous ready revision stays the recoverable view. Validation is server-produced for exactly this source/library/manifest
  and is re-checked here (hash, size, query/action names inside the manifest), never trusted from a client.
- Nothing here calls a model, a provider or a domain command. Snapshot, by-message, replay and state reads never start a
  generation; an unsupported library version is answered with the stored native fallback, not a regeneration.
- Persisted UI state holds declared non-secret presentation fields only (OpenUI `$vars`/form names the server validator listed
  for the current revision, plus Rafii's ordered `@selection`), at most 16 KiB, with its own stateRevision so typing never
  invalidates accepted source.
- Raw source (deltas, checkpoints, revisions) lives in the service-only migration-102 tables, never in SAFE_EVENTS, logs or URLs.
- Lock order is always artifact row → attempt row (commit, finish, reap, create), so concurrent commits/cancels never deadlock.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from postriff_alpha.domain import AlphaError

from . import ui_contracts as contracts

LIVE_STATES = ("queued", "streaming", "validating")
FAILED_STATES = ("failed", "canceled", "interrupted")
LEASE_SECONDS = contracts.BOUNDS["generationTimeoutSeconds"] + 30   # producer lease; renewed by every checkpoint
# The private replay log stays bounded without capping seq: deltas of a finished attempt are compacted away, and only the
# latest STATE_EVENTS_KEPT ui.state_changed events are kept (selection history for follow-up turns).
STATE_EVENTS_KEPT = 200
# pr_ui_events.payload is checked at 40 000 bytes of jsonb text, which adds a space after each ':' and ','; keep a margin.
EVENT_PAYLOAD_BYTES = 36000
MAX_REVISIONS_LISTED = 10
MANIFEST_BYTES = 64 * 1024              # a server capability manifest (D builds it) is bounded before it is stored
RUN_KEY_PREFIX = "agent:"
FOUNDER_RUN_PREFIX = "agent:founder:"
SELECTION_KEY = "@selection"            # Rafii-reserved state key (OpenUI store keys never start with '@')
SELECTION_MAX_ITEMS = 50
SELECTION_VISIBLE_MAX = 50              # the list as shown when selecting ("the second draft" resolves against it)
STATE_STRING_MAX = 2000
STATE_ARRAY_MAX = 200
STATE_DEPTH_MAX = 6
_STATE_VAR = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]{0,63}$")
_FORM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ATTEMPT_KEY = re.compile(r"^[A-Za-z0-9:_-]{16,120}$")
_REF_ID = re.compile(r"^[A-Za-z0-9:_.-]{1,80}$")
_REF_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SECRETISH = re.compile(r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential|signature|private[_-]?key)", re.I)
_SIGNED_URL = re.compile(r"(x-amz-signature|x-goog-signature|[?&](token|sig|signature)=|bearer\s+[a-z0-9._-]{12,})", re.I)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ASSETS = Path(__file__).resolve().parent / "generated" / "openui-assets.json"
LIBRARY_REF_TYPES = ("library_asset", "library_item", "document", "file")
# Selection types → the chip kind the Manager's APP_STATE reads (service._assemble uses `kind`; a draft chip is a 'post').
_CHIP_KIND = {"draft": "post", "variant": "post", "post": "post"}

_ARTIFACT_COLUMNS = ("a.id::text, a.workspace_id::text, a.scope, a.scope_key, a.conversation_id::text, a.parent_run_id::text, a.message_id::text, "
                     "a.slot, a.actor::text, a.surface, a.journey_ids, a.revision, a.source_hash, a.generation_state, a.validation_state, "
                     "a.current_attempt_id::text, a.reason, a.contract_version, a.language_version, a.library_version, a.library_hash, a.prompt_hash, "
                     "a.manifest, a.manifest_id, a.binding_version, a.fallback_text, a.safe_state, a.state_revision, a.next_seq, a.as_of, "
                     "a.created_at, a.updated_at, r.idempotency_key")
_ARTIFACT_KEYS = ("artifactId", "workspaceId", "scope", "scopeKey", "conversationId", "runId", "messageId", "slot", "actor", "surface", "journeyIds",
                  "revision", "sourceHash", "generationState", "validationState", "generationAttemptId", "reason", "contractVersion", "languageVersion",
                  "libraryVersion", "libraryHash", "promptHash", "manifest", "manifestId", "bindingVersion", "fallbackText", "safeState", "stateRevision",
                  "nextSeq", "asOf", "createdAt", "updatedAt", "runKey")
_ATTEMPT_COLUMNS = ("id::text, artifact_id::text, workspace_id::text, kind, target_revision, base_revision, base_source_hash, state, reason, idempotency_key, "
                    "retry_of::text, instruction, lease_owner, lease_expires_at, reservation_id, provider_attempts, usage, cost_usd_micro, cost_state, "
                    "checkpoint_source, checkpoint_hash, checkpoint_bytes, admitted_at, first_delta_at, ready_at, finished_at, created_at, updated_at")
_ATTEMPT_KEYS = ("attemptId", "artifactId", "workspaceId", "kind", "targetRevision", "baseRevision", "baseSourceHash", "state", "reason", "idempotencyKey",
                 "retryOf", "instruction", "leaseOwner", "leaseExpiresAt", "reservationId", "providerAttempts", "usage", "costUsdMicro", "costState",
                 "checkpointSource", "checkpointHash", "checkpointBytes", "admittedAt", "firstDeltaAt", "readyAt", "finishedAt", "createdAt", "updatedAt")


class StateConflict(AlphaError):
    """409 on a stale stateRevision. `current` carries the stored state so the client merges its dirty fields and retries."""

    def __init__(self, current: dict):
        super().__init__("This view changed in another tab. Your edits are kept; Rafii will merge them.", 409, code="ui_state_conflict")
        self.current = current


class RevisionConflict(AlphaError):
    """409 on a stale baseRevision/baseSourceHash. Nothing is overwritten; the caller may rebase the presentation only."""

    def __init__(self, current_revision: int, current_hash: str | None):
        super().__init__("This view changed since the edit started. Nothing was overwritten.", 409, code="ui_revision_conflict")
        self.current = {"revision": current_revision, "sourceHash": current_hash}


UiStateConflict = StateConflict
UiRevisionConflict = RevisionConflict


# --- small helpers ------------------------------------------------------------------------------------------------------
def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return str(value)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _not_found(what: str = "That view is unavailable.", code: str = "ui_artifact") -> AlphaError:
    return AlphaError(what, 404, code=code)


def effective_scope(auth) -> tuple[str, str]:
    """(scope, scope_key) of the caller. Founder scope comes only from server code (the founder route family builds its own
    auth from the verified control principal); a client never supplies it."""
    scope = getattr(auth, "scope", "workspace") or "workspace"
    key = getattr(auth, "scope_key", "") or ""
    if scope not in contracts.SCOPES:
        raise _not_found(code="ui_scope")
    return scope, (key if scope == "founder" else "")


def founder_scope_key(run_key: str | None) -> str | None:
    """`founder:<mode>:<env>` of an `agent:founder:<mode>:<env>:<key>` run; None for any other run."""
    if not isinstance(run_key, str) or not run_key.startswith(FOUNDER_RUN_PREFIX):
        return None
    parts = run_key[len(FOUNDER_RUN_PREFIX):].split(":", 2)
    return f"founder:{parts[0]}:{parts[1]}" if len(parts) == 3 and parts[0] and parts[1] else None


def scope_allows(record: dict, auth) -> bool:
    """A stored artifact is visible only in its own scope, and never in workspace scope when its run is a founder run."""
    scope, key = effective_scope(auth)
    if record.get("scope") != scope or (record.get("scopeKey") or "") != key:
        return False
    run_founder = founder_scope_key(record.get("runKey"))
    if scope == "workspace":
        return run_founder is None
    return run_founder == key


def _cursor_scope(conn_or_cur):
    """(cursor, commit) for a psycopg connection (own short transaction) or a cursor (caller's transaction)."""
    if hasattr(conn_or_cur, "cursor") and not hasattr(conn_or_cur, "fetchone"):
        return conn_or_cur.cursor(), conn_or_cur.commit
    return conn_or_cur, None


def _artifact_row(row) -> dict:
    record = dict(zip(_ARTIFACT_KEYS, row))
    record["journeyIds"] = list(record.get("journeyIds") or [])
    record["manifest"] = record.get("manifest") or {}
    record["safeState"] = record.get("safeState") or {}
    for key in ("asOf", "createdAt", "updatedAt"):
        record[key] = _iso(record.get(key))
    return record


def _attempt_row(row) -> dict:
    record = dict(zip(_ATTEMPT_KEYS, row))
    record["usage"] = record.get("usage") or {}
    for key in ("leaseExpiresAt", "admittedAt", "firstDeltaAt", "readyAt", "finishedAt", "createdAt", "updatedAt"):
        record[key] = _iso(record.get(key))
    return record


def _load(cur, auth, artifact_id: str, *, lock: bool = False) -> dict:
    if not contracts.valid_uuid(artifact_id or ""):
        raise _not_found()
    cur.execute(f"SELECT {_ARTIFACT_COLUMNS} FROM public.pr_ui_artifacts a JOIN public.pr_agent_runs r ON r.id=a.parent_run_id "
                f"WHERE a.id::text=%s AND a.workspace_id=%s" + (" FOR UPDATE OF a" if lock else ""), (artifact_id.lower(), auth.workspace_id))
    row = cur.fetchone()
    if not row:
        raise _not_found()
    record = _artifact_row(row)
    if not scope_allows(record, auth):
        raise _not_found()
    return record


def _attempt(cur, attempt_id: str | None, *, lock: bool = False) -> dict | None:
    if not contracts.valid_uuid(attempt_id or ""):
        return None
    cur.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM public.pr_ui_attempts WHERE id::text=%s" + (" FOR UPDATE" if lock else ""), (attempt_id.lower(),))
    row = cur.fetchone()
    return _attempt_row(row) if row else None


def _attempt_by_key(cur, workspace_id: str, key: str, *, lock: bool = False) -> dict | None:
    cur.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM public.pr_ui_attempts WHERE workspace_id=%s AND idempotency_key=%s" + (" FOR UPDATE" if lock else ""),
                (workspace_id, key))
    row = cur.fetchone()
    return _attempt_row(row) if row else None


def _current_source(cur, artifact_id: str, revision: int) -> str | None:
    if revision < 1:
        return None
    cur.execute("SELECT source FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND revision=%s", (artifact_id, revision))
    row = cur.fetchone()
    return row[0] if row else None


def public_attempt(attempt: dict | None) -> dict | None:
    """What the browser may know about an attempt: identity, kind, state, stable reason and cost certainty. Never source,
    lease owner, reservation, instruction or raw usage."""
    if not attempt:
        return None
    return {"attemptId": attempt["attemptId"], "kind": attempt["kind"], "state": attempt["state"], "reason": attempt.get("reason"),
            "targetRevision": attempt["targetRevision"], "baseRevision": attempt.get("baseRevision"), "retryOf": attempt.get("retryOf"),
            "providerAttempts": attempt.get("providerAttempts") or 0, "costState": attempt.get("costState") or "none",
            "live": attempt["state"] in LIVE_STATES}


def _reason(value, default: str) -> str:
    return value if value in contracts.REASON_CODES else default


# --- library compatibility (old versions → native fallback, never a regeneration) -------------------------------------------
def supported_library_hashes(path: Path | None = None, values=None) -> dict:
    """{scope: set(libraryHash)} the deployed renderer can draw: the current generated assets plus explicitly verified
    compatible older hashes (RAFII_GENUI_COMPATIBLE_LIBRARIES, comma list). No assets → nothing is supported (native only)."""
    values = os.environ if values is None else values
    out = {"workspace": set(), "founder": set()}
    try:
        assets = json.loads((path or _ASSETS).read_text("utf-8"))
        for name, scope in (("consumer", "workspace"), ("founder", "founder")):
            library = (assets.get("libraries") or {}).get(name) or {}
            if contracts.valid_hash(library.get("libraryHash") or ""):
                out[scope].add(library["libraryHash"])
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    for raw in str(values.get("RAFII_GENUI_COMPATIBLE_LIBRARIES") or "").split(","):
        raw = raw.strip().lower()
        if contracts.valid_hash(raw):
            out["workspace"].add(raw)
            out["founder"].add(raw)
    return out


def compatibility(record: dict, supported: dict | None = None) -> dict:
    if record["revision"] < 1 or not record.get("libraryHash"):
        return {"supported": True, "reason": None}
    supported = supported_library_hashes() if supported is None else supported
    ok = record["libraryHash"] in supported.get(record["scope"], set())
    return {"supported": ok, "reason": None if ok else "library_unsupported"}


# --- revoked / deleted sources (re-checked on every reopen; snapshots are never a bypass) ----------------------------------
def _ref_pairs(manifest: dict) -> list[tuple[str, str]]:
    out = []
    for item in (manifest or {}).get("approvedRefs") or []:
        if isinstance(item, dict):
            kind, ident = item.get("type") or item.get("kind"), item.get("id")
        elif isinstance(item, str) and ":" in item:
            kind, ident = item.split(":", 1)
        else:
            continue
        if isinstance(kind, str) and isinstance(ident, str) and _REF_TYPE.match(kind) and _REF_ID.match(ident):
            out.append((kind, ident))
    return out[:200]


def state_ids(state: dict) -> dict:
    """Ids of the workspace-state records a generated view may reference (drafts, posts/reviews, campaigns, automations,
    sources). Inactive or retracted sources count as revoked."""
    state = state if isinstance(state, dict) else {}
    phase2 = state.get("phase2") if isinstance(state.get("phase2"), dict) else {}
    raffi = state.get("raffi") if isinstance(state.get("raffi"), dict) else {}
    planning = raffi.get("campaignPlanning") if isinstance(raffi.get("campaignPlanning"), dict) else {}

    def ids(items, keep=lambda _x: True):
        return {str(i.get("id")) for i in items or [] if isinstance(i, dict) and i.get("id") and keep(i)}
    drafts = ids(state.get("variants"))
    return {"draft": drafts, "variant": drafts, "post": drafts, "job": ids(phase2.get("jobs")), "review": ids(phase2.get("reviews")),
            "campaign": ids(planning.get("campaigns")), "automation": ids(planning.get("recurringTasks")),
            "source": ids(state.get("sources"), lambda s: s.get("active") is not False and not s.get("retracted") and not s.get("retractedAt"))}


def revoked_refs(cur, auth, manifest: dict) -> list[str]:
    """`type:id` of approved refs that no longer exist (deleted, being deleted, retracted) in the caller's workspace now.
    Types this store cannot check stay unchecked here; their data still flows only through re-authorized queries (lane D)."""
    pairs = _ref_pairs(manifest)
    if not pairs:
        return []
    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (auth.workspace_id,))
    row = cur.fetchone()
    state = row[0] if row else {}
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            state = {}
    known = state_ids(state)
    library = sorted({i.lower() for k, i in pairs if k in LIBRARY_REF_TYPES and contracts.valid_uuid(i)})
    library_ok = set()
    if library:
        cur.execute("SELECT id::text FROM public.pr_library_assets WHERE workspace_id=%s AND id::text = ANY(%s) AND processing_status <> 'deleting'",
                    (auth.workspace_id, library))
        library_ok = {r[0] for r in cur.fetchall()}
    tables = {"conversation": "pr_conversations", "message": "pr_messages", "run": "pr_agent_runs"}
    revoked = []
    for kind, ident in pairs:
        if kind in known:
            gone = ident not in known[kind]
        elif kind in LIBRARY_REF_TYPES:
            gone = ident.lower() not in library_ok
        elif kind in tables:
            gone = True
            if contracts.valid_uuid(ident):
                cur.execute(f"SELECT 1 FROM public.{tables[kind]} WHERE id::text=%s AND workspace_id=%s", (ident.lower(), auth.workspace_id))
                gone = cur.fetchone() is None
        else:
            gone = False
        if gone:
            revoked.append(f"{kind}:{ident}")
    return revoked[:100]


# --- create / resume ------------------------------------------------------------------------------------------------------
def _parent_run(cur, auth, parent_run_id: str) -> dict:
    if not contracts.valid_uuid(parent_run_id or ""):
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
    cur.execute("SELECT id::text, conversation_id::text, status, idempotency_key, actor::text, artifact->'result'->'ui', artifact->'result'->>'composedBy', "
                "artifact->'result'->>'answerText' FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s",
                (parent_run_id.lower(), auth.workspace_id))
    row = cur.fetchone()
    if not row or not str(row[3] or "").startswith(RUN_KEY_PREFIX):
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
    run = {"runId": row[0], "conversationId": row[1], "status": row[2], "runKey": row[3], "actor": row[4], "ui": row[5] if isinstance(row[5], dict) else None,
           "composedBy": row[6], "answerText": row[7] or ""}
    scope, key = effective_scope(auth)
    run_founder = founder_scope_key(run["runKey"])
    if scope == "workspace" and run_founder is not None:
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")      # founder data never through consumer routes
    if scope == "founder" and (run_founder != key or run["actor"] != str(auth.principal)):
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
    return run


def _message_for_run(cur, workspace_id: str, run_id: str) -> tuple[str, dict] | None:
    cur.execute("SELECT id::text, body FROM public.pr_messages WHERE workspace_id=%s AND run_id::text=%s AND role='assistant' ORDER BY seq DESC LIMIT 1 FOR UPDATE",
                (workspace_id, run_id))
    row = cur.fetchone()
    if not row:
        return None
    return row[0], (row[1] if isinstance(row[1], dict) else {})


def _record_on_message(cur, workspace_id: str, message_id: str, body: dict, artifact_id: str, slot: str) -> None:
    """body.agent.uiArtifacts=[{artifactId, slot}] on the assistant message (D-A19), so a reload finds the view."""
    agent = body.get("agent") if isinstance(body.get("agent"), dict) else {}
    refs = [r for r in agent.get("uiArtifacts") or [] if isinstance(r, dict)]
    if any(r.get("artifactId") == artifact_id for r in refs):
        return
    agent = {**agent, "uiArtifacts": (refs + [{"artifactId": artifact_id, "slot": slot}])[-4:]}
    cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s AND workspace_id=%s", (_json({**body, "agent": agent}), message_id, workspace_id))


def manifest_names(manifest: dict) -> tuple[set, set]:
    queries = {q.get("name") for q in (manifest or {}).get("queries") or [] if isinstance(q, dict) and isinstance(q.get("name"), str)}
    actions = {a.get("actionId") for a in (manifest or {}).get("actions") or [] if isinstance(a, dict) and isinstance(a.get("actionId"), str)}
    return queries, actions


def _projection_value(projection, key, default=None):
    if isinstance(projection, dict):
        return projection.get(key, default)
    return getattr(projection, key, default)


def _replay_cursor(cur, artifact_id: str, attempt_id: str | None, next_seq: int) -> int:
    if attempt_id:
        cur.execute("SELECT min(seq) FROM public.pr_ui_events WHERE artifact_id::text=%s AND attempt_id::text=%s", (artifact_id, attempt_id))
        row = cur.fetchone()
        if row and row[0]:
            return int(row[0]) - 1
    return max(0, int(next_seq) - 1)


def lease_artifact(cur, record: dict) -> dict:
    """D-A33 `lease['artifact']`: the camelCase UiArtifactV1 fields (runId = parent run; canonicalSource of the current accepted
    revision, which an edit uses as its base) plus server-only identity B needs (scope, surface, journeys, the server manifest)."""
    full = {**record, "canonicalSource": _current_source(cur, record["artifactId"], record["revision"])}
    out = contracts.public_artifact(full)
    out.update({"workspaceId": record["workspaceId"], "scope": record["scope"], "scopeKey": record["scopeKey"], "surface": record["surface"],
                "journeyIds": list(record["journeyIds"]), "actor": record["actor"], "slot": record["slot"], "reason": record.get("reason"),
                "manifest": record["manifest"]})
    return out


def lease_attempt(attempt: dict | None) -> dict | None:
    """D-A33 `lease['attempt']`. Server-side only (lease owner, key, reservation and checkpoint never reach a browser)."""
    if not attempt:
        return None
    return {"attemptId": attempt["attemptId"], "kind": attempt["kind"], "targetRevision": attempt["targetRevision"], "baseRevision": attempt.get("baseRevision"),
            "baseSourceHash": attempt.get("baseSourceHash"), "state": attempt["state"], "reason": attempt.get("reason"), "leaseOwner": attempt.get("leaseOwner"),
            "leaseExpiresAt": attempt.get("leaseExpiresAt"), "idempotencyKey": attempt["idempotencyKey"], "reservationId": attempt.get("reservationId"),
            "retryOf": attempt.get("retryOf"), "instruction": attempt.get("instruction"), "providerAttempts": attempt.get("providerAttempts") or 0,
            "checkpointSource": attempt.get("checkpointSource") or "", "checkpointHash": attempt.get("checkpointHash"),
            "checkpointBytes": attempt.get("checkpointBytes") or 0, "artifactId": attempt["artifactId"]}


def _lease(cur, record, attempt, *, created, replay_cursor):
    return {"artifact": lease_artifact(cur, record), "attempt": lease_attempt(attempt), "created": bool(created), "producer": bool(created),
            "replay_cursor": int(replay_cursor)}


def _same_request(existing: dict, kind: str, retry_of, base: dict | None) -> bool:
    if existing["kind"] != kind:
        return False
    if retry_of is not None and existing.get("retryOf") != str(retry_of).lower():
        return False
    if base is not None and (existing.get("baseRevision"), existing.get("baseSourceHash"), existing.get("instruction")) != \
            (base["revision"], base["sourceHash"], base["instruction"]):
        return False
    return True


def _edit_base(base) -> dict:
    """D-A32 `base` of an explicit edit: the accepted revision and source hash the person saw, and what they asked to change."""
    if not isinstance(base, dict):
        raise AlphaError("An edit needs the revision it changes.", 400, code="ui_base")
    revision, source_hash, instruction = base.get("revision"), base.get("sourceHash"), base.get("instruction")
    if type(revision) is not int or revision < 1 or not contracts.valid_hash(source_hash or ""):
        raise AlphaError("An edit needs the revision it changes.", 400, code="ui_base")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 2000:
        raise AlphaError("Say what to change in up to 2,000 characters.", 400, code="ui_instruction")
    return {"revision": revision, "sourceHash": source_hash, "instruction": instruction.strip()[:2000]}


def create_or_resume_artifact(cur, auth, parent_run_id, slot, idempotency_key, *, surface, manifest, projection, kind="generate", retry_of=None,
                              lease_owner, base=None, library=None):
    """Claim or resume the producer of one presentation attempt (inside the caller's first short ui_transaction).

    Returns the D-A33 lease {artifact (camelCase UiArtifactV1 + server identity/manifest), attempt, created, producer, replay_cursor}:
    - created/producer True: a new attempt row was inserted; this caller (lease_owner) produces it and dispatches the provider.
    - created False: the same key, or a concurrent request for the same artifact, found an existing attempt: the caller attaches as
      a replayer from replay_cursor and must not dispatch a provider. A ready artifact is returned as is (no new spend).
    kind='generate' never makes a second producer or spend for a view that already exists; 'retry' (explicit "Try again", retry_of =
    the stopped latest attempt) and 'edit' (base = {revision, sourceHash, instruction}) are new metered attempts on revision+1;
    'repair' (retry_of = the failed initial attempt, which B finished as failed/parse_rejected first) keeps its target revision.
    """
    if kind not in contracts.ATTEMPT_KINDS:
        raise AlphaError("Unknown presentation attempt kind.", 400, code="ui_attempt_kind")
    slot = slot or "main"
    if slot not in contracts.SLOTS:
        raise AlphaError("Unknown presentation slot.", 400, code="ui_slot")
    if surface not in contracts.UI_SURFACES:
        raise AlphaError("Unknown surface.", 400, code="ui_surface")
    scope, scope_key = effective_scope(auth)
    if (surface == "founder") != (scope == "founder"):
        raise AlphaError("Unknown surface.", 400, code="ui_surface")
    if not isinstance(idempotency_key, str) or not _ATTEMPT_KEY.match(idempotency_key):
        raise AlphaError("A valid idempotencyKey is required.", 400, code="ui_idempotency_key")
    if not isinstance(lease_owner, str) or not 1 <= len(lease_owner) <= 80:
        raise AlphaError("A producer lease owner is required.", 400, code="ui_lease_owner")
    if retry_of is not None and not contracts.valid_uuid(retry_of):
        raise AlphaError("retryOfAttemptId is invalid.", 400, code="ui_retry")
    if kind in ("retry", "repair") and retry_of is None:
        raise AlphaError("A retry names the attempt it follows.", 400, code="ui_retry")
    edit = _edit_base(base) if kind == "edit" else None
    if not auth.allows("edit"):
        raise AlphaError("Interactive views need the 'edit' permission in this workspace.", 403, code="ui_forbidden")
    # Same key → same attempt, whatever happened since (never a second producer, never an unannounced new attempt).
    existing = _attempt_by_key(cur, auth.workspace_id, idempotency_key)
    if existing:
        record = _load(cur, auth, existing["artifactId"], lock=True)
        if record["runId"] != str(parent_run_id).lower() or record["slot"] != slot or not _same_request(existing, kind, retry_of, edit):
            raise AlphaError("This idempotencyKey belongs to another view.", 409, code="ui_idempotency_conflict")
        if _reap_artifact(cur, record):
            record = _load(cur, auth, record["artifactId"], lock=True)
        attempt = _attempt(cur, existing["attemptId"])
        return _lease(cur, record, attempt, created=False, replay_cursor=_replay_cursor(cur, record["artifactId"], attempt["attemptId"], record["nextSeq"]))
    run = _parent_run(cur, auth, parent_run_id)
    cur.execute("SELECT id::text FROM public.pr_ui_artifacts WHERE workspace_id=%s AND parent_run_id::text=%s AND slot=%s", (auth.workspace_id, run["runId"], slot))
    known = cur.fetchone()
    if known is None:
        if kind != "generate":
            raise _not_found()
        if run["status"] != "completed":
            raise AlphaError("This answer is not finished, so it can't get an interactive view yet.", 409, code="not_eligible")
        if not (run["ui"] or {}).get("eligible"):
            raise AlphaError("This answer doesn't need an interactive view.", 409, code="not_eligible")
        if not isinstance(manifest, dict) or not manifest:
            raise AlphaError("This view has no capability manifest.", 409, code="not_eligible")
        if _bytes(_json(manifest)) > MANIFEST_BYTES:
            raise AlphaError("This view's capability manifest is too large.", 413, code="ui_manifest_too_large")
        found = _message_for_run(cur, auth.workspace_id, run["runId"])
        message_id, body = found if found else (None, {})
        allowed_journeys = contracts.FOUNDER_JOURNEYS if scope == "founder" else contracts.CONSUMER_JOURNEYS
        journeys = [j for j in (_projection_value(projection, "journey_ids") or manifest.get("journeyIds") or []) if j in allowed_journeys][:9]
        fallback = str(_projection_value(projection, "fallback_text") or run["answerText"] or "")[:12000]
        library = library if isinstance(library, dict) else (manifest.get("library") if isinstance(manifest.get("library"), dict) else {})
        cur.execute("INSERT INTO public.pr_ui_artifacts(workspace_id,scope,scope_key,conversation_id,parent_run_id,message_id,slot,actor,surface,journey_ids,"
                    "manifest,manifest_id,binding_version,fallback_text,language_version,library_version,library_hash,prompt_hash) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (workspace_id,parent_run_id,slot) DO NOTHING RETURNING id::text",
                    (auth.workspace_id, scope, scope_key, run["conversationId"], run["runId"], message_id, slot, str(auth.principal), surface, journeys,
                     _json(manifest), str(manifest.get("manifestId") or _projection_value(projection, "manifest_id") or "")[:120],
                     max(1, int(manifest.get("bindingVersion") or 1)), fallback, str(library.get("languageVersion") or "")[:40],
                     str(library.get("libraryVersion") or "")[:40], str(library.get("libraryHash") or "")[:64], str(library.get("promptHash") or "")[:64]))
        inserted = cur.fetchone()
        if inserted is None:
            cur.execute("SELECT id::text FROM public.pr_ui_artifacts WHERE workspace_id=%s AND parent_run_id::text=%s AND slot=%s", (auth.workspace_id, run["runId"], slot))
            artifact_id = cur.fetchone()[0]
        else:
            artifact_id = inserted[0]
            if message_id:
                _record_on_message(cur, auth.workspace_id, message_id, body, artifact_id, slot)
    else:
        artifact_id = known[0]
    # A view's manifest is fixed when it is created: a later edit, retry or repair never widens its data or controls.
    record = _load(cur, auth, artifact_id, lock=True)
    if _reap_artifact(cur, record):
        record = _load(cur, auth, artifact_id, lock=True)
    current = _attempt(cur, record.get("generationAttemptId"))
    if current and current["state"] in LIVE_STATES:
        if kind in ("generate", "retry"):
            # Another tab or request already produces this artifact: attach, never a second producer.
            return _lease(cur, record, current, created=False, replay_cursor=_replay_cursor(cur, artifact_id, current["attemptId"], record["nextSeq"]))
        raise AlphaError("This view is still being prepared. Try again when it's ready.", 409, code="ui_attempt_live")
    target = record["revision"] + 1
    instruction = None
    if kind == "generate":
        if current is not None or record["revision"] >= 1:
            # Duplicate create of an existing view: show what exists (ready, or stopped with an explicit "Try again" offered).
            return _lease(cur, record, current, created=False,
                          replay_cursor=_replay_cursor(cur, artifact_id, current["attemptId"] if current else None, record["nextSeq"]))
        base_rev, base_hash = None, None
    elif kind == "retry":
        prior = _attempt(cur, retry_of)
        if prior is None or prior["artifactId"] != artifact_id or prior["state"] not in FAILED_STATES:
            raise AlphaError("Only a stopped view can be tried again.", 409, code="ui_retry")
        if current is not None and current["attemptId"] != prior["attemptId"]:
            raise AlphaError("Only the latest attempt of this view can be tried again.", 409, code="ui_retry")
        base_rev = prior.get("baseRevision") if record["revision"] >= 1 and prior.get("baseRevision") else None
        if base_rev is not None and base_rev != record["revision"]:
            raise RevisionConflict(record["revision"], record["sourceHash"])
        if base_rev is None and record["revision"] >= 1:
            raise AlphaError("This view is already ready; ask for a change instead.", 409, code="ui_retry")
        base_hash = record["sourceHash"] if base_rev else None
        instruction = prior.get("instruction")
    elif kind == "repair":
        prior = _attempt(cur, retry_of)
        if prior is None or prior["artifactId"] != artifact_id or prior["state"] != "failed" or prior["kind"] == "repair":
            raise AlphaError("A repair follows exactly one failed attempt.", 409, code="ui_retry")
        cur.execute("SELECT 1 FROM public.pr_ui_attempts WHERE retry_of::text=%s AND kind='repair'", (prior["attemptId"],))
        if cur.fetchone():
            raise AlphaError("This view was already repaired once.", 409, code="repair_exhausted")
        base_rev, base_hash, instruction = prior.get("baseRevision"), prior.get("baseSourceHash"), prior.get("instruction")
        target = prior["targetRevision"]
        if record["revision"] != target - 1:
            raise RevisionConflict(record["revision"], record["sourceHash"])
    else:  # edit
        if record["revision"] < 1 or record["validationState"] != "accepted":
            raise AlphaError("This view is not ready to edit yet.", 409, code="ui_not_ready")
        if edit["revision"] != record["revision"] or edit["sourceHash"] != (record["sourceHash"] or ""):
            raise RevisionConflict(record["revision"], record["sourceHash"])      # before any spend
        base_rev, base_hash, instruction = record["revision"], record["sourceHash"], edit["instruction"]
    cur.execute("INSERT INTO public.pr_ui_attempts(artifact_id,workspace_id,kind,target_revision,base_revision,base_source_hash,idempotency_key,retry_of,instruction,"
                "lease_owner,lease_expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+make_interval(secs => %s)) ON CONFLICT DO NOTHING RETURNING id::text",
                (artifact_id, auth.workspace_id, kind, target, base_rev, base_hash, idempotency_key, str(retry_of).lower() if retry_of else None,
                 instruction, lease_owner, LEASE_SECONDS))
    created = cur.fetchone()
    if created is None:
        # Lost a race on the same key or on the one-live-producer index for this target revision: attach to the winner.
        cur.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM public.pr_ui_attempts WHERE artifact_id::text=%s AND state IN ('queued','streaming','validating') "
                    "ORDER BY created_at DESC LIMIT 1", (artifact_id,))
        row = cur.fetchone()
        attempt = _attempt_row(row) if row else _attempt_by_key(cur, auth.workspace_id, idempotency_key)
        if attempt is None:
            raise AlphaError("This view is still being prepared. Try again when it's ready.", 409, code="ui_attempt_live")
        return _lease(cur, record, attempt, created=False, replay_cursor=_replay_cursor(cur, artifact_id, attempt["attemptId"], record["nextSeq"]))
    attempt_id = created[0]
    state_sql = ", generation_state='queued', validation_state='pending', reason=NULL" if record["revision"] < 1 else ""
    cur.execute(f"UPDATE public.pr_ui_artifacts SET current_attempt_id=%s, updated_at=now(){state_sql} WHERE id::text=%s", (attempt_id, artifact_id))
    record = _load(cur, auth, artifact_id, lock=True)
    return _lease(cur, record, _attempt(cur, attempt_id), created=True, replay_cursor=max(0, record["nextSeq"] - 1))


def attempt_state(conn_or_cur, attempt_id) -> str | None:
    """ext: the current state of one attempt; a producer polls it between chunks to notice a cancel (None when unknown)."""
    if not contracts.valid_uuid(attempt_id or ""):
        return None
    cur, commit = _cursor_scope(conn_or_cur)
    cur.execute("SELECT state FROM public.pr_ui_attempts WHERE id::text=%s", (attempt_id.lower(),))
    row = cur.fetchone()
    if commit:
        commit()
    return row[0] if row else None


# --- events and checkpoints -----------------------------------------------------------------------------------------------
def append_event(conn_or_cur, artifact_id, attempt_id, revision, kind, payload):
    """Persist one private replay event with the next monotonic seq of the artifact (row-locked counter) and return the stored
    UiEventV1 (D-A35). `ui.heartbeat` is liveness only and never persisted (D-A36): a producer reuses its last sent seq for it."""
    if kind not in contracts.EVENT_KINDS:
        raise ValueError(f"unknown UI event kind {kind}")
    if kind == "ui.heartbeat":
        raise ValueError("ui.heartbeat frames are not persisted")
    if not contracts.valid_uuid(artifact_id or ""):
        raise _not_found()
    if attempt_id is not None and not contracts.valid_uuid(attempt_id):
        raise _not_found("That presentation attempt is unavailable.", "ui_attempt")
    if type(revision) is not int or revision < 0:
        raise ValueError("UI event revision must be a non-negative integer")
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("UI event payload must be an object")
    text = _json(payload)
    if _bytes(text) > EVENT_PAYLOAD_BYTES:
        raise AlphaError("This presentation event is too large.", 413, code="ui_event_too_large")
    cur, commit = _cursor_scope(conn_or_cur)
    cur.execute("UPDATE public.pr_ui_artifacts SET next_seq=next_seq+1, updated_at=now() WHERE id::text=%s RETURNING next_seq-1, workspace_id::text",
                (artifact_id.lower(),))
    row = cur.fetchone()
    if not row:
        if commit:
            commit()
        raise _not_found()
    seq, workspace_id = int(row[0]), row[1]
    if attempt_id is not None:
        cur.execute("SELECT 1 FROM public.pr_ui_attempts WHERE id::text=%s AND artifact_id::text=%s", (attempt_id.lower(), artifact_id.lower()))
        if not cur.fetchone():
            if commit:
                commit()
            raise _not_found("That presentation attempt is unavailable.", "ui_attempt")
    at = contracts.now_iso()
    cur.execute("INSERT INTO public.pr_ui_events(artifact_id,workspace_id,seq,attempt_id,revision,kind,payload,at) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (artifact_id.lower(), workspace_id, seq, attempt_id.lower() if attempt_id else None, revision, kind, text, at))
    if commit:
        commit()
    return contracts.make_event(artifact_id.lower(), attempt_id.lower() if attempt_id else None, revision, seq, kind, json.loads(text), at=at)


def checkpoint(conn_or_cur, attempt_id, source, *, lease_owner):
    """Durable source cursor of a live attempt (coarse: >= 4 KiB or >= 1 s, the caller decides). Touches only the attempt row,
    renews the lease and moves queued → streaming. Raises 409 ui_attempt_closed (canceled/reaped/finished) or ui_lease_lost
    (another owner), so a producer stops instead of writing over someone else's attempt."""
    if not isinstance(source, str):
        raise ValueError("checkpoint source must be text")
    size = _bytes(source)
    if size > contracts.BOUNDS["sourceBytes"]:
        raise AlphaError("This view's source is too large.", 413, code="source_too_large")
    cur, commit = _cursor_scope(conn_or_cur)
    cur.execute("UPDATE public.pr_ui_attempts SET checkpoint_source=%s, checkpoint_hash=%s, checkpoint_bytes=%s, "
                "state=CASE WHEN state='queued' THEN 'streaming' ELSE state END, first_delta_at=coalesce(first_delta_at, now()), "
                "lease_expires_at=greatest(lease_expires_at, now()+make_interval(secs => %s)), updated_at=now() "
                "WHERE id::text=%s AND lease_owner=%s AND state IN ('queued','streaming','validating') AND lease_expires_at > now() RETURNING 1",
                (source, contracts.sha256_text(source), size, LEASE_SECONDS, attempt_id, lease_owner))
    ok = cur.fetchone()
    if not ok:
        cur.execute("SELECT state FROM public.pr_ui_attempts WHERE id::text=%s", (attempt_id,))
        found = cur.fetchone()
        if commit:
            commit()
        if not found:
            raise _not_found("That presentation attempt is unavailable.", "ui_attempt")
        if found[0] not in LIVE_STATES:
            raise AlphaError("This presentation was stopped.", 409, code="ui_attempt_closed")
        raise AlphaError("This presentation is no longer being produced here.", 409, code="ui_lease_lost")
    if commit:
        commit()


def events_after(cur, auth, artifact_id, after, limit):
    """Authorized bounded replay: events with seq > after, oldest first (at most BOUNDS.replayPageEvents). Compacted deltas of
    finished attempts leave seq gaps; a client accepts them (the server is authoritative) and reads the snapshot on a terminal."""
    record = _load(cur, auth, artifact_id)
    after = int(after) if type(after) is int and after >= 0 else 0
    limit = max(1, min(int(limit or contracts.BOUNDS["replayPageEvents"]), contracts.BOUNDS["replayPageEvents"]))
    cur.execute("SELECT seq, attempt_id::text, revision, kind, payload, at FROM public.pr_ui_events WHERE artifact_id::text=%s AND workspace_id=%s AND seq > %s "
                "ORDER BY seq LIMIT %s", (record["artifactId"], auth.workspace_id, after, limit))
    return [contracts.make_event(record["artifactId"], attempt, revision, seq, kind, payload or {}, at=_iso(at))
            for seq, attempt, revision, kind, payload, at in cur.fetchall()]


def _compact(cur, artifact_id: str, attempt_id: str) -> None:
    """A finished attempt's raw deltas and checkpoint are no longer needed (an accepted source is a revision; a failed candidate
    is never shown again). Started/checkpoint/terminal events stay, so replay still tells what happened."""
    cur.execute("DELETE FROM public.pr_ui_events WHERE artifact_id::text=%s AND attempt_id::text=%s AND kind='ui.delta'", (artifact_id, attempt_id))
    cur.execute("UPDATE public.pr_ui_attempts SET checkpoint_source='' WHERE id::text=%s AND state NOT IN ('queued','streaming','validating')", (attempt_id,))


# --- commit (CAS) and attempt lifecycle -------------------------------------------------------------------------------------
def _revision_kind(attempt: dict) -> str:
    if attempt["kind"] == "repair":
        return "repair"
    return "edit" if attempt["kind"] == "edit" or attempt.get("baseRevision") else "generate"


def commit_ui_revision(cur, auth, patch, validation):
    """Atomically commit a validated revision. `patch` = UiPatchV1 {artifactId, baseRevision, baseSourceHash, patchSource,
    idempotencyKey} (+ optional attemptId, promptHash, languageVersion); `validation` = the server validator's result for exactly
    this source. Stale base → RevisionConflict 409 (nothing overwritten). Returns the public UiArtifactV1 (ready + accepted)."""
    if not isinstance(patch, dict) or not isinstance(validation, dict):
        raise AlphaError("Invalid revision commit.", 400, code="ui_commit")
    record = _load(cur, auth, str(patch.get("artifactId") or ""), lock=True)
    if patch.get("attemptId"):
        attempt = _attempt(cur, patch["attemptId"], lock=True)
    else:
        attempt = _attempt_by_key(cur, auth.workspace_id, str(patch.get("idempotencyKey") or ""), lock=True)
    if attempt is None or attempt["artifactId"] != record["artifactId"]:
        raise _not_found("That presentation attempt is unavailable.", "ui_attempt")
    if attempt["state"] not in LIVE_STATES:
        raise AlphaError("This presentation was stopped.", 409, code="ui_attempt_closed")
    base_revision = patch.get("baseRevision")
    base_hash = patch.get("baseSourceHash") or None
    if type(base_revision) is not int or base_revision != record["revision"] or attempt["targetRevision"] != record["revision"] + 1:
        raise RevisionConflict(record["revision"], record["sourceHash"])
    if record["revision"] >= 1 and base_hash != record["sourceHash"]:
        raise RevisionConflict(record["revision"], record["sourceHash"])
    canonical = validation.get("canonicalSource")
    if not validation.get("accepted") or not isinstance(canonical, str) or not canonical:
        raise AlphaError("This view did not pass validation.", 422, code="parse_rejected")
    if _bytes(canonical) > contracts.BOUNDS["sourceBytes"]:
        raise AlphaError("This view's source is too large.", 413, code="source_too_large")
    source_hash = contracts.sha256_text(canonical)
    if validation.get("sourceHash") != source_hash:
        raise AlphaError("This view's validation does not match its source.", 422, code="validation_unavailable")
    patch_source = patch.get("patchSource")
    if isinstance(patch_source, str):
        scope, _key = effective_scope(auth)
        limit = (contracts.BOUNDS["sourceBytes"] if record["revision"] < 1
                 else contracts.BOUNDS["founderPatchBytes"] if scope == "founder" else contracts.BOUNDS["patchBytes"])
        if _bytes(patch_source) > limit:
            raise AlphaError("This change is too large.", 413, code="source_too_large")
    library_hash = validation.get("libraryHash")
    if not contracts.valid_hash(library_hash or ""):
        raise AlphaError("This view's component library is unknown.", 422, code="library_unsupported")
    allowed_queries, allowed_actions = manifest_names(record["manifest"])
    if not set(validation.get("queryNames") or []) <= allowed_queries or not set(validation.get("actionIds") or []) <= allowed_actions:
        # A revision never reaches data or controls outside the server manifest (no query/action expansion by an edit).
        raise AlphaError("This view asks for data or controls it isn't allowed.", 422, code="parse_rejected")
    revision = record["revision"] + 1
    stored_validation = {k: v for k, v in validation.items() if k != "canonicalSource"}
    library_version = str(validation.get("libraryVersion") or record["libraryVersion"] or "")[:40]
    prompt_hash = str(patch.get("promptHash") or record["promptHash"] or "")[:64]
    cur.execute("INSERT INTO public.pr_ui_revisions(artifact_id,workspace_id,revision,kind,attempt_id,base_revision,source,source_hash,validation,library_version,"
                "library_hash,prompt_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (record["artifactId"], auth.workspace_id, revision, _revision_kind(attempt), attempt["attemptId"], record["revision"] or None, canonical, source_hash,
                 _json(stored_validation), library_version, library_hash, prompt_hash))
    cur.execute("UPDATE public.pr_ui_artifacts SET revision=%s, source_hash=%s, generation_state='ready', validation_state='accepted', reason=NULL, "
                "current_attempt_id=%s, library_version=%s, library_hash=%s, prompt_hash=%s, language_version=%s, as_of=coalesce(as_of, now()), updated_at=now() "
                "WHERE id::text=%s AND revision=%s",
                (revision, source_hash, attempt["attemptId"], library_version, library_hash, prompt_hash,
                 str(patch.get("languageVersion") or record["languageVersion"] or "")[:40], record["artifactId"], record["revision"]))
    if cur.rowcount != 1:
        raise RevisionConflict(record["revision"], record["sourceHash"])
    cur.execute("UPDATE public.pr_ui_attempts SET state='ready', reason=NULL, ready_at=now(), finished_at=now(), updated_at=now() WHERE id::text=%s",
                (attempt["attemptId"],))
    _compact(cur, record["artifactId"], attempt["attemptId"])
    fresh = _load(cur, auth, record["artifactId"])
    fresh["canonicalSource"] = canonical
    return contracts.public_artifact(fresh)


def finish_attempt(cur, attempt_id, state, reason=None, usage=None):
    """Move an attempt along the state machine (streaming/validating, or terminal failed/canceled/interrupted). The same state
    again is a no-op (idempotent). `ready` comes only from commit_ui_revision. Before the first ready revision the artifact
    mirrors its current attempt; afterwards it stays on its last ready revision (an edit that fails leaves the previous revision
    as the view). D-A39: `usage` is accepted for the frozen signature but accounting columns are written only by lane B's
    ui_metering (reservation_id, provider_attempts, usage, cost_usd_micro, cost_state)."""
    _ = usage
    if state not in contracts.GENERATION_STATES or state == "queued":
        raise ValueError(f"unknown target generation state {state}")
    peek = _attempt(cur, attempt_id)
    if peek is None:
        raise _not_found("That presentation attempt is unavailable.", "ui_attempt")
    cur.execute("SELECT 1 FROM public.pr_ui_artifacts WHERE id::text=%s FOR UPDATE", (peek["artifactId"],))   # lock order: artifact → attempt
    attempt = _attempt(cur, attempt_id, lock=True)
    if state == "ready" and attempt["state"] != "ready":
        raise AlphaError("A presentation becomes ready only through a validated commit.", 409, code="ui_state_transition")
    if state == attempt["state"]:
        return attempt
    if attempt["state"] == "queued" and state == "validating":
        contracts.require_transition("queued", "streaming")      # a tiny source can finish before its first checkpoint
    else:
        contracts.require_transition(attempt["state"], state)
    defaults = {"failed": "internal_error", "canceled": "canceled_by_user", "interrupted": "client_gone"}
    terminal = state in contracts.TERMINAL_GENERATION_STATES
    code = _reason(reason, defaults[state]) if state in defaults else None
    cur.execute("UPDATE public.pr_ui_attempts SET state=%s, reason=coalesce(%s, reason), finished_at=CASE WHEN %s THEN coalesce(finished_at, now()) ELSE finished_at END, "
                "updated_at=now() WHERE id::text=%s", (state, code, terminal, attempt["attemptId"]))
    rejected = state == "failed" and code in ("parse_rejected", "repair_exhausted", "source_too_large", "library_unsupported")
    cur.execute("UPDATE public.pr_ui_artifacts SET generation_state=%s, reason=%s, validation_state=CASE WHEN %s THEN 'rejected' ELSE validation_state END, "
                "updated_at=now() WHERE id::text=%s AND revision=0 AND current_attempt_id::text=%s",
                (state, code, rejected, attempt["artifactId"], attempt["attemptId"]))
    if terminal:
        _compact(cur, attempt["artifactId"], attempt["attemptId"])
    return _attempt(cur, attempt["attemptId"])


# --- leases and reaping ---------------------------------------------------------------------------------------------------
def _reservation_for(cur, workspace_id: str, attempt: dict, parent_run_id: str) -> str | None:
    """The ledger hold of an attempt: the column B wrote at claim, else B's fixed key `agent:{parentRunId}:ui:{attemptId}` (D-A23)."""
    if attempt.get("reservationId"):
        return attempt["reservationId"]
    cur.execute("SELECT id::text FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key=%s AND kind='reserve'",
                (workspace_id, f"agent:{parent_run_id}:ui:{attempt['attemptId']}"))
    row = cur.fetchone()
    return row[0] if row else None


def _settle_unknown(cur, ledger, workspace_id: str, attempt: dict, parent_run_id: str):
    """An interrupted attempt's usage is unknown: its hold stays held until reconciled (never booked as zero). Lane B's
    ui_metering.settle_attempt owns the ledger call and the accounting columns (D-A39); until B's module is wired the hold is
    settled 'unknown' through the existing Ledger directly (no accounting columns written here either way)."""
    reservation = _reservation_for(cur, workspace_id, attempt, parent_run_id)
    usage = {"costState": "unknown", "costUsdMicro": None, "reservationId": reservation, "reason": "lease_expired",
             "inputTokens": None, "outputTokens": None, "model": None}
    try:
        from . import ui_metering
        return ui_metering.settle_attempt(None, cur, None, {**lease_attempt(attempt), "reservationId": reservation,
                                                            "workspaceId": workspace_id, "parentRunId": parent_run_id}, usage)
    except AlphaError as error:
        if error.code != "ui_not_ready":          # B's stub until ui_metering lands; any real refusal propagates
            raise
    if not reservation:
        return None
    if ledger is None:
        from ..billing import Ledger
        ledger = Ledger()
    return ledger.settle(cur, workspace_id, reservation, "unknown")   # keeps the hold; a terminal settlement already made wins


def _interrupt(cur, attempt: dict, artifact_id: str, workspace_id: str, parent_run_id: str, revision: int, ledger=None) -> None:
    cur.execute("UPDATE public.pr_ui_attempts SET state='interrupted', reason='lease_expired', finished_at=now(), updated_at=now() "
                "WHERE id::text=%s AND state IN ('queued','streaming','validating')", (attempt["attemptId"],))
    cur.execute("UPDATE public.pr_ui_artifacts SET generation_state='interrupted', reason='lease_expired', updated_at=now() "
                "WHERE id::text=%s AND revision=0 AND current_attempt_id::text=%s", (artifact_id, attempt["attemptId"]))
    append_event(cur, artifact_id, attempt["attemptId"], revision, "ui.interrupted", {"reason": "lease_expired", "fallback": "native"})
    _settle_unknown(cur, ledger, workspace_id, attempt, parent_run_id)
    _compact(cur, artifact_id, attempt["attemptId"])


def _reap_artifact(cur, record: dict, ledger=None) -> int:
    """Interrupt expired attempts of one artifact whose row the caller already holds (artifact → attempt lock order)."""
    cur.execute(f"SELECT {_ATTEMPT_COLUMNS} FROM public.pr_ui_attempts WHERE artifact_id::text=%s AND state IN ('queued','streaming','validating') "
                "AND lease_expires_at < now() FOR UPDATE SKIP LOCKED", (record["artifactId"],))
    rows = [_attempt_row(r) for r in cur.fetchall()]
    for attempt in rows:
        _interrupt(cur, attempt, record["artifactId"], record["workspaceId"], record["runId"], record["revision"], ledger)
    return len(rows)


def reap_expired(cur, workspace_id, now, *, ledger=None, limit=50):
    """Interrupt live attempts whose producer lease expired before `now` (epoch seconds, datetime, or None = database now): the
    producer died, or a request ended without settling. A ui.interrupted event tells replaying clients to show the native
    fallback, and the usage is settled unknown (the hold stays until reconciled; never zero). No provider call, no retry.
    workspace_id=None sweeps every workspace (cron)."""
    at = now.timestamp() if isinstance(now, datetime) else (float(now) if now is not None else None)
    expiry = "t.lease_expires_at < now()" if at is None else "t.lease_expires_at < to_timestamp(%s)"
    params: list = [] if at is None else [at]
    where = f"t.state IN ('queued','streaming','validating') AND {expiry}"
    if workspace_id:
        where += " AND t.workspace_id=%s"
        params.append(workspace_id)
    cur.execute(f"SELECT t.id::text, t.artifact_id::text FROM public.pr_ui_attempts t WHERE {where} ORDER BY t.lease_expires_at LIMIT %s", (*params, int(limit)))
    count = 0
    for attempt_id, artifact_id in cur.fetchall():
        cur.execute("SELECT workspace_id::text, parent_run_id::text, revision FROM public.pr_ui_artifacts WHERE id::text=%s FOR UPDATE SKIP LOCKED", (artifact_id,))
        owner = cur.fetchone()
        if not owner:
            continue                                  # a producer is committing right now; the next sweep sees the outcome
        attempt = _attempt(cur, attempt_id, lock=True)
        if not attempt or attempt["state"] not in LIVE_STATES:
            continue
        cur.execute("SELECT lease_expires_at < " + ("now()" if at is None else "to_timestamp(%s)") + " FROM public.pr_ui_attempts WHERE id::text=%s",
                    ((attempt_id,) if at is None else (at, attempt_id)))
        if not cur.fetchone()[0]:
            continue                                  # renewed by a checkpoint since the candidate scan
        _interrupt(cur, attempt, artifact_id, owner[0], owner[1], owner[2], ledger)
        count += 1
    return count


def reap_all(connection_factory, *, ledger=None, limit=50) -> dict:
    """Cron entry (next to ideas.recover_stalled): one short bounded transaction, zero provider requests."""
    with connection_factory() as db, db.cursor() as cur:
        count = reap_expired(cur, None, None, ledger=ledger, limit=limit)
    return {"interrupted": count, "providerRequests": 0}


# --- UI state (CAS, declared fields only) --------------------------------------------------------------------------------
def declared_fields(cur, record: dict) -> tuple[set, set]:
    """($var names, form names) the current accepted revision declares: the server validator's `stateNames`/`formNames`
    stored with the revision, plus manifest `stateFields`. Anything else is refused."""
    cur.execute("SELECT validation FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND revision=%s", (record["artifactId"], record["revision"]))
    row = cur.fetchone()
    validation = row[0] if row and isinstance(row[0], dict) else {}
    names = {n if n.startswith("$") else "$" + n for n in list(validation.get("stateNames") or []) + list((record.get("manifest") or {}).get("stateFields") or [])
             if isinstance(n, str) and n}
    forms = {n for n in validation.get("formNames") or [] if isinstance(n, str) and n}
    return names, forms


def _clean_value(value, depth=0):
    if depth > STATE_DEPTH_MAX:
        raise AlphaError("This view's saved state is nested too deeply.", 400, code="ui_state_value")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return json.loads(contracts.canonical_json(value))
    if isinstance(value, str):
        if len(value) > STATE_STRING_MAX or _SIGNED_URL.search(value):
            raise AlphaError("This view's saved state has a value Rafii won't keep.", 400, code="ui_state_value")
        return value
    if isinstance(value, list):
        if len(value) > STATE_ARRAY_MAX:
            raise AlphaError("This view's saved state has too many items.", 400, code="ui_state_value")
        return [_clean_value(v, depth + 1) for v in value]
    if isinstance(value, dict):
        if len(value) > STATE_ARRAY_MAX:
            raise AlphaError("This view's saved state has too many fields.", 400, code="ui_state_value")
        out = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64 or _SECRETISH.search(key):
                raise AlphaError("This view's saved state has a field Rafii won't keep.", 400, code="ui_state_field")
            out[key] = _clean_value(item, depth + 1)
        return out
    raise AlphaError("This view's saved state has a value Rafii won't keep.", 400, code="ui_state_value")


def _clean_ref(item, *, titled: bool) -> dict:
    if not isinstance(item, dict) or set(item) - {"type", "id", "title"}:
        raise AlphaError("Invalid selection.", 400, code="ui_selection")
    kind, ident, title = item.get("type"), item.get("id"), item.get("title")
    if not isinstance(kind, str) or not _REF_TYPE.match(kind) or not isinstance(ident, str) or not _REF_ID.match(ident):
        raise AlphaError("Invalid selection.", 400, code="ui_selection")
    out = {"type": kind, "id": ident}
    if titled:
        out["title"] = _CONTROL_CHARS.sub("", title)[:120] if isinstance(title, str) else ""
    return out


def clean_selection(value) -> dict | None:
    """Rafii's ordered selection {items:[{type,id,title}], visible?:[{type,id}], listId?, revision?}: what was selected and the
    list as it was shown when selecting (D-A20), so "the second draft" means what it meant then, not after a later re-sort."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"items", "visible", "listId", "revision"}:
        raise AlphaError("Invalid selection.", 400, code="ui_selection")
    items = value.get("items")
    if not isinstance(items, list) or len(items) > SELECTION_MAX_ITEMS:
        raise AlphaError("Invalid selection.", 400, code="ui_selection")
    out, seen = [], set()
    for item in items:
        ref = _clean_ref(item, titled=True)
        if (ref["type"], ref["id"]) in seen:
            continue
        seen.add((ref["type"], ref["id"]))
        out.append(ref)
    visible = value.get("visible")
    shown = None
    if visible is not None:
        if not isinstance(visible, list) or len(visible) > SELECTION_VISIBLE_MAX:
            raise AlphaError("Invalid selection.", 400, code="ui_selection")
        shown = [_clean_ref({k: v for k, v in item.items() if k != "title"} if isinstance(item, dict) else item, titled=False) for item in visible]
    list_id = value.get("listId")
    if list_id is not None and (not isinstance(list_id, str) or not _FORM_NAME.match(list_id.lstrip("$"))):
        raise AlphaError("Invalid selection.", 400, code="ui_selection")
    revision = value.get("revision")
    return {"items": out, **({"visible": shown} if shown else {}), **({"listId": list_id} if list_id else {}),
            **({"revision": revision} if type(revision) is int and revision >= 0 else {})}


def validate_state_fields(patch: dict, declared_vars: set, declared_forms: set) -> dict:
    """Keep only declared, non-secret presentation fields. `null` removes a field. Raises 400 on anything else."""
    out = {}
    for key, value in (patch or {}).items():
        if key == SELECTION_KEY:
            out[key] = clean_selection(value)
            continue
        if not isinstance(key, str) or _SECRETISH.search(key):
            raise AlphaError("This view's saved state has a field Rafii won't keep.", 400, code="ui_state_field")
        if _STATE_VAR.match(key):
            allowed = key in declared_vars
        elif _FORM_NAME.match(key):
            allowed = key in declared_forms
        else:
            allowed = False
        if not allowed:
            raise AlphaError("This view doesn't declare that field.", 400, code="ui_state_field")
        out[key] = _clean_value(value)
    return out


def persist_ui_state(cur, auth, artifact_id, expected_state_revision, patch):
    """Compare-and-swap the artifact's presentation state. A stale expected revision raises StateConflict (409) carrying the
    stored state, so another tab's accepted edits are never overwritten. Not a business mutation; requires `edit`."""
    if not auth.allows("edit"):
        raise AlphaError("Saving this view needs the 'edit' permission in this workspace.", 403, code="ui_forbidden")
    if type(expected_state_revision) is not int or expected_state_revision < 0:
        raise AlphaError("expectedStateRevision must be a whole number.", 400, code="ui_revision")
    if not isinstance(patch, dict):
        raise AlphaError("patch must be an object.", 400, code="ui_state_patch")
    record = _load(cur, auth, artifact_id, lock=True)
    if record["revision"] < 1 or record["validationState"] != "accepted":
        raise AlphaError("This view is not ready yet.", 409, code="ui_not_ready")
    if expected_state_revision != record["stateRevision"]:
        raise StateConflict({"artifactId": record["artifactId"], "stateRevision": record["stateRevision"], "safeState": record["safeState"]})
    names, forms = declared_fields(cur, record)
    cleaned = validate_state_fields(patch, names, forms)
    merged = {k: v for k, v in {**record["safeState"], **cleaned}.items() if v is not None}
    text = contracts.canonical_json(merged)
    if _bytes(text) > contracts.BOUNDS["stateBytes"]:
        raise AlphaError("This view's saved state is too large.", 413, code="ui_state_too_large")
    revision = record["stateRevision"] + 1
    cur.execute("UPDATE public.pr_ui_artifacts SET safe_state=%s::jsonb, state_revision=%s, updated_at=now() WHERE id::text=%s AND state_revision=%s",
                (text, revision, record["artifactId"], record["stateRevision"]))
    if cur.rowcount != 1:
        current = _load(cur, auth, artifact_id)
        raise StateConflict({"artifactId": current["artifactId"], "stateRevision": current["stateRevision"], "safeState": current["safeState"]})
    payload = {"stateRevision": revision, "fields": sorted(cleaned)[:64]}
    if SELECTION_KEY in cleaned:
        payload["selection"] = cleaned[SELECTION_KEY]
    append_event(cur, record["artifactId"], None, record["revision"], "ui.state_changed", payload)
    # The replay log stays bounded: only the latest STATE_EVENTS_KEPT state events (selection history) are kept.
    cur.execute("DELETE FROM public.pr_ui_events WHERE artifact_id::text=%s AND kind='ui.state_changed' AND seq < (SELECT min(seq) FROM (SELECT seq FROM "
                "public.pr_ui_events WHERE artifact_id::text=%s AND kind='ui.state_changed' ORDER BY seq DESC LIMIT %s) kept)",
                (record["artifactId"], record["artifactId"], STATE_EVENTS_KEPT))
    return {"artifactId": record["artifactId"], "stateRevision": revision, "safeState": merged}


# --- selection memory for follow-up turns (D-A20) -------------------------------------------------------------------------
def _selection_at(cur, record: dict, state_revision: int) -> dict | None:
    if state_revision >= record["stateRevision"]:
        return record["safeState"].get(SELECTION_KEY)
    cur.execute("SELECT payload FROM public.pr_ui_events WHERE artifact_id::text=%s AND kind='ui.state_changed' AND payload ? 'selection' "
                "AND (payload->>'stateRevision')::int <= %s ORDER BY seq DESC LIMIT 1", (record["artifactId"], state_revision))
    row = cur.fetchone()
    return (row[0] or {}).get("selection") if row else None


def selection_note(references: list[dict], revision: int, dropped: int = 0, visible: list[dict] | None = None) -> str:
    """Plain words for the Manager: what was selected, in the order shown, and the list as shown then. Ids and types only
    (titles are display text and never reach a prompt)."""
    parts = [f"{i}. {r['type']} {r['id']}" for i, r in enumerate(references, start=1)]
    note = ("In the interactive view (revision %d) the person selected, in the order shown when selecting: %s." % (revision, "; ".join(parts))) if parts else ""
    if visible:
        note += " The list as shown then: " + "; ".join(f"{i}. {r['type']} {r['id']}" for i, r in enumerate(visible[:SELECTION_VISIBLE_MAX], start=1)) + "."
    if dropped:
        note = (note + " " if note else "") + f"{dropped} selected item(s) are no longer available."
    return note[:2400]


def selection_context(cur, auth, ui_context):
    """{references:[{type, kind, id, title}], note, artifactId, artifactRevision, stateRevision} as stored when the person
    selected (never a later reordered live table); None when there is nothing to resolve. Never raises for a stale or foreign
    view (a follow-up turn must not fail because of a view)."""
    if not isinstance(ui_context, dict) or not contracts.valid_uuid(ui_context.get("artifactId") or ""):
        return None
    try:
        record = _load(cur, auth, ui_context["artifactId"])
    except AlphaError:
        return None
    if record["revision"] < 1:
        return None
    wanted = ui_context.get("stateRevision")
    selection = _selection_at(cur, record, wanted if type(wanted) is int and wanted >= 0 else record["stateRevision"])
    items = [i for i in (selection or {}).get("items") or [] if isinstance(i, dict) and i.get("id")]
    if not items:
        return None
    revoked = set(revoked_refs(cur, auth, {"approvedRefs": [{"type": i["type"], "id": i["id"]} for i in items]}))
    kept = [i for i in items if f"{i['type']}:{i['id']}" not in revoked]
    references = [{"type": i["type"], "kind": _CHIP_KIND.get(i["type"], i["type"]), "id": i["id"], "title": i.get("title") or ""} for i in kept][:12]
    visible = [v for v in (selection or {}).get("visible") or [] if isinstance(v, dict) and v.get("id")]
    return {"references": references, "note": selection_note(references, record["revision"], len(items) - len(kept), visible), "artifactId": record["artifactId"],
            "artifactRevision": record["revision"], "stateRevision": record["stateRevision"]}


# --- reads (snapshot / by message) ---------------------------------------------------------------------------------------
def display_for(record: dict, attempt: dict | None, compat: dict, revoked: list) -> dict:
    """How the browser shows an artifact, decided here so every surface agrees: the generated view (`generated`), a view still
    being prepared (`pending`), or the stored native fallback (`fallback`, with a stable reason). Never a new model call."""
    accepted = record["revision"] >= 1 and record["validationState"] == "accepted"
    live = attempt is not None and attempt["state"] in LIVE_STATES
    if accepted and not compat["supported"]:
        return {"mode": "fallback", "reason": "library_unsupported", "updating": False}
    if accepted:
        return {"mode": "generated", "reason": None, "updating": live, "revokedRefs": len(revoked)}
    if live:
        return {"mode": "pending", "reason": None, "updating": True}
    return {"mode": "fallback", "reason": record.get("reason") or (attempt or {}).get("reason") or "internal_error", "updating": False}


def _expired(manifest: dict) -> bool:
    raw = (manifest or {}).get("expiresAt")
    if raw in (None, ""):
        return False
    try:
        if isinstance(raw, (int, float)):
            return float(raw) <= datetime.now(timezone.utc).timestamp()
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True


def access_for(record: dict, auth, flags: dict, compat: dict, revoked: list) -> dict:
    """What this caller may do with the view right now (re-derived on every read; nothing here is stored or trusted later):
    every route still re-checks server-side. A historical view (expired capability) reads as-of data until the person goes live."""
    founder = record["scope"] == "founder"
    enabled = bool(flags.get("enabled"))
    editor = bool(auth.allows("edit"))
    expired = _expired(record["manifest"])
    is_actor = record["actor"] == str(auth.principal)
    return {"role": getattr(auth, "role", "") or "", "isActor": is_actor, "enabled": enabled, "live": enabled and compat["supported"],
            "canQuery": enabled and compat["supported"], "canAct": enabled and bool(flags.get("actions")) and editor and not founder and not expired,
            "canEdit": enabled and bool(flags.get("edits")) and editor and record["revision"] >= 1, "canRetry": enabled and editor,
            "canPersistState": enabled and editor, "manifestExpired": expired, "historical": expired, "revokedRefs": revoked}


def snapshot(cur, auth, artifact_id, *, flags=None, supported=None) -> dict:
    """The authorized persisted view: public artifact + public manifest + revision metadata + current attempt, re-checked now.
    Never generates. An unsupported library version yields the stored native fallback (canonicalSource withheld, no model call);
    a disabled feature is reported so the client renders native only. Revoked sources are re-checked before anything is served:
    the parent run, the conversation and the answer message must still exist in this scope."""
    record = _load(cur, auth, artifact_id)
    if not record.get("messageId"):
        raise AlphaError("The answer this view belonged to was removed.", 404, code="ui_artifact_revoked")
    cur.execute("SELECT 1 FROM public.pr_messages WHERE id::text=%s AND workspace_id=%s AND conversation_id::text=%s",
                (record["messageId"], auth.workspace_id, record["conversationId"]))
    if not cur.fetchone():
        raise AlphaError("The answer this view belonged to was removed.", 404, code="ui_artifact_revoked")
    flags = flags if isinstance(flags, dict) else {}
    attempt = _attempt(cur, record.get("generationAttemptId"))
    if record["revision"] < 1 and attempt is not None:
        record["generationState"] = attempt["state"]       # before the first ready revision the view is its current attempt
    record["canonicalSource"] = _current_source(cur, record["artifactId"], record["revision"])
    compat = compatibility(record, supported)
    revoked = revoked_refs(cur, auth, record["manifest"])
    cur.execute("SELECT revision, kind, source_hash, attempt_id::text, library_version, created_at FROM public.pr_ui_revisions WHERE artifact_id::text=%s "
                "ORDER BY revision DESC LIMIT %s", (record["artifactId"], MAX_REVISIONS_LISTED))
    revisions = [{"revision": r, "kind": k, "sourceHash": h, "attemptId": a, "libraryVersion": v or "", "createdAt": _iso(c)} for r, k, h, a, v, c in cur.fetchall()]
    artifact = contracts.public_artifact(record)
    display = display_for(record, attempt, compat, revoked)
    if display["mode"] != "generated":
        artifact["canonicalSource"] = None          # an old library or unfinished source is never rendered: native fallback
    manifest = contracts.public_manifest(record["manifest"])
    access = access_for(record, auth, flags, compat, revoked)
    if not access["canAct"]:
        manifest["actions"] = []                    # no write control is offered where writes are off, expired or not allowed
    return {"artifact": artifact, "manifest": manifest, "revisions": revisions, "attempt": public_attempt(attempt), "compatibility": compat,
            "display": display, "access": access, "lastSeq": max(0, record["nextSeq"] - 1), "journeyIds": record["journeyIds"],
            "surface": record["surface"], "scope": record["scope"]}


def by_message(cur, auth, message_id, *, flags=None, supported=None) -> dict:
    if not contracts.valid_uuid(message_id or ""):
        raise _not_found("That message is unavailable.", "ui_message")
    scope, key = effective_scope(auth)
    cur.execute("SELECT r.idempotency_key FROM public.pr_messages m LEFT JOIN public.pr_agent_runs r ON r.id=m.run_id WHERE m.id::text=%s AND m.workspace_id=%s",
                (message_id.lower(), auth.workspace_id))
    row = cur.fetchone()
    if not row:
        raise _not_found("That message is unavailable.", "ui_message")
    run_founder = founder_scope_key(row[0])
    if (scope == "workspace" and run_founder is not None) or (scope == "founder" and run_founder != key):
        raise _not_found("That message is unavailable.", "ui_message")     # founder answers never through consumer routes
    cur.execute("SELECT id::text FROM public.pr_ui_artifacts WHERE message_id::text=%s AND workspace_id=%s AND scope=%s AND scope_key=%s ORDER BY created_at LIMIT 4",
                (message_id.lower(), auth.workspace_id, scope, key))
    supported = supported_library_hashes() if supported is None else supported
    artifacts = []
    for (artifact_id,) in cur.fetchall():
        try:
            artifacts.append(snapshot(cur, auth, artifact_id, flags=flags, supported=supported))
        except AlphaError:
            continue                                  # a founder/foreign row is simply absent here
    return {"messageId": message_id.lower(), "artifacts": artifacts}


def replay_view(cur, auth, artifact_id, after, limit=None) -> dict:
    """ext: events after `after` plus the current attempt and whether anything more can arrive: what a reconnecting client (or the
    founder's polling transport) needs to resume without any provider call."""
    record = _load(cur, auth, artifact_id)
    events = events_after(cur, auth, artifact_id, after, limit or contracts.BOUNDS["replayPageEvents"])
    attempt = _attempt(cur, record.get("generationAttemptId"))
    live = attempt is not None and attempt["state"] in LIVE_STATES
    cursor = events[-1]["seq"] if events else (int(after) if type(after) is int and after >= 0 else 0)
    return {"artifactId": record["artifactId"], "events": events, "cursor": cursor, "lastSeq": max(0, record["nextSeq"] - 1),
            "done": not live and cursor >= record["nextSeq"] - 1, "attempt": public_attempt(attempt)}


def _transaction(runtime, token, workspace_id, need="read"):
    from .ui_http import ui_transaction
    return ui_transaction(runtime, token, workspace_id, need)


def _flags(runtime, workspace_id) -> dict:
    founder = isinstance(getattr(runtime, "founder", None), dict)
    try:
        return runtime.cfg.genui_for(workspace_id, founder=founder)
    except TypeError:
        return runtime.cfg.genui_for(workspace_id)
    except AttributeError:
        return {"enabled": False}


def snapshot_http(runtime, workspace_id, token, artifact_id):
    """GET presentations/{id}: authorized persisted snapshot; never generates (zero provider attempts)."""
    supported = supported_library_hashes()
    with _transaction(runtime, token, workspace_id, "read") as (cur, auth):
        return snapshot(cur, auth, artifact_id, flags=_flags(runtime, workspace_id), supported=supported)


def by_message_http(runtime, workspace_id, token, message_id):
    """GET messages/{id}: the views of one assistant message for reload (snapshots only; zero provider attempts)."""
    supported = supported_library_hashes()
    with _transaction(runtime, token, workspace_id, "read") as (cur, auth):
        return by_message(cur, auth, message_id, flags=_flags(runtime, workspace_id), supported=supported)


def persist_state_http(runtime, workspace_id, token, artifact_id, request):
    """POST presentations/{id}/state. While the kill switch is on, state is read-only (no new writes)."""
    if not _flags(runtime, workspace_id).get("enabled"):
        raise AlphaError("Interactive views are not available here.", 404, code="ui_disabled")
    with _transaction(runtime, token, workspace_id, "edit") as (cur, auth):
        return persist_ui_state(cur, auth, artifact_id, request["expectedStateRevision"], request["patch"])
