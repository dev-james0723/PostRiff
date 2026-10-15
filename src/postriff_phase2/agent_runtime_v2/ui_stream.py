"""Lane B — real presentation streaming over the existing WSGI app (02-CONTRACTS §3-4; A-DECISIONS D-A5..D-A9, D-A32..D-A39).

Frozen entry points (called by ui_http; signatures fixed by A):
- create_presentation(runtime, environ, start_response, workspace_id, token, request) -> WSGI iterable (text/event-stream).
- replay(runtime, environ, start_response, workspace_id, token, artifact_id, after) -> WSGI iterable: authorized bounded replay
  + live tail of the existing attempt (heartbeats, <= BOUNDS.replayTailSeconds); never starts a provider call.
- cancel_http(runtime, workspace_id, token, artifact_id) -> dict: cancel presentation only; the business result is untouched.
- create_edit(runtime, environ, start_response, workspace_id, token, artifact_id, request) -> WSGI iterable: explicit semantic edit,
  a new bounded metered attempt on (baseRevision, baseSourceHash); stale base -> 409 before any reservation or provider call.
- probe(runtime, environ, start_response, workspace_id, token) -> WSGI iterable: authenticated, zero-model G04 probe.

How one presentation runs (D-A7, D-A8):
1. Admission, one short ``ui_transaction`` (verified session + active membership + workspace row lock; 'edit'; the caller must be
   the actor of the parent run): the parent must be a completed, metered Manager run whose ``result.ui.eligible`` is true and fresh
   (a passive reopen of an old answer never generates); lane D projects and builds the manifest; lane F claims or resumes the
   attempt (same idempotency key → the same attempt, replayed, never re-dispatched; another live producer → attach); the plan and
   its deterministic ceiling are built; ui_metering reserves inside the parent turn's combined plan; ``ui.started`` is persisted.
   A refusal after the claim (no route, unpriced, budget, egress, library) persists a failed attempt and streams one ``ui.failed``:
   the native answer stays, no provider call is made, and a reload never retries.
2. Stream (no transaction held): a worker thread runs ``asyncio.run(ui_presenter.stream_presentation(...))`` with
   ``AsyncOpenAI(max_retries=0)`` and feeds a bounded queue; the WSGI generator coalesces deltas into persisted ``ui.delta``
   frames (append + byte offset), checkpoints coarsely (>= 4 KiB or >= 1 s; lease-owner checked) on its own connection, polls for a
   cancel, and sends ``ui.heartbeat`` after 10 s of silence.
3. Finalize: the SDK stream is drained to its final usage; the server validator (C, through A's seam) validates the candidate
   (policy from the manifest); exactly one automatic UI-only repair runs if it was rejected and time and budget allow (its own
   reservation); then one short ``ui_transaction`` settles the attempt and CAS-commits the revision; only then ``ui.ready``.
4. Every exception inside the generator ends in a terminal ``ui.failed`` with a REASON_CODES value (nothing re-raised).
   ``close()``/GeneratorExit (client gone) cancels the worker, marks the attempt ``interrupted`` and settles once (unknown keeps
   the hold). A content-free ``request.stream_closed`` line is logged.

Raw source deltas are private conversation content: they go only to the client of this artifact and to the service-only
``pr_ui_events`` table (lane F), never to logs, SAFE_EVENTS or telemetry.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
import queue
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext

from postriff_alpha.domain import AlphaError

from . import ui_contracts as contracts
from . import ui_http, ui_metering, ui_presenter

log = logging.getLogger("postriff.agent_ui")

# Tunables (contract bounds; tests shorten the timing ones).
HEARTBEAT_SECONDS = float(contracts.BOUNDS["heartbeatSeconds"])
REPLAY_TAIL_SECONDS = float(contracts.BOUNDS["replayTailSeconds"])
REPLAY_POLL_SECONDS = 0.5
CANCEL_POLL_SECONDS = 1.0
FLUSH_BYTES = 1024                      # coalesce SDK deltas into frames of about this size ...
FLUSH_SECONDS = 0.15                    # ... or this age, whichever comes first
FRAME_MAX_BYTES = 8 * 1024              # one persisted ui.delta payload stays far below pr_ui_events' 40 000-byte check
CHECKPOINT_BYTES = contracts.BOUNDS["checkpointBytes"]
CHECKPOINT_SECONDS = contracts.BOUNDS["checkpointMs"] / 1000.0
GENERATION_SECONDS = float(contracts.BOUNDS["generationTimeoutSeconds"])
DEPLOYMENT_SECONDS = 300.0              # vercel.json maxDuration of postriff_api
DEPLOYMENT_MARGIN_SECONDS = 40.0        # validation, commit and the response tail after the provider stream
MIN_REPAIR_SECONDS = 12.0               # a repair needs at least this much of the presentation budget left
WORKER_GRACE_SECONDS = 3.0              # the stream loop's own guard beyond the presenter deadline
WORKER_JOIN_SECONDS = 5.0
FRESH_SECONDS = 900                     # an initial presentation is admitted only this long after its turn completed
QUEUE_ITEMS = 1024
READY_INLINE_BYTES = 16 * 1024          # ui.ready carries the canonical source when it is this small; else read the snapshot
PROBE_GAP_SECONDS = 1.5
PROBE_SPLIT_SECONDS = 0.25
PROBE_LIMIT_PER_MINUTE = 6
PROBE_TEXT = "粵語 ✓ 🎹 Rafii"          # multi-byte UTF-8 (3- and 4-byte characters) for the fragmentation check
LIVE_STATES = ("queued", "streaming", "validating")
# Validator codes no presenter output can fix → the terminal reason (no automatic repair, no second reservation).
NOT_REPAIRABLE = {"validation_unavailable": "validation_unavailable", "source_too_large": "source_too_large", "library_unsupported": "library_unsupported",
                  "contract_mismatch": "library_unsupported", "missing_base": "revision_conflict", "validator_error": "validation_unavailable",
                  "bad_request": "validation_unavailable", "unauthorized": "validation_unavailable"}
_sleep = time.sleep


# --- small helpers ------------------------------------------------------------------------------------------------------
def _lease_owner() -> str:
    return "b:" + uuid.uuid4().hex


def _repair_key(original_key: str) -> str:
    """D-A32: the single automatic repair's idempotency key is derived from the original attempt's key."""
    return "r1_" + contracts.sha256_text(str(original_key))[:40]


def _request_id(environ) -> str | None:
    value = (environ or {}).get("postriff.request_id")
    return value if isinstance(value, str) and len(value) <= 64 else None


@contextmanager
def _savepoint(cur):
    """A psycopg savepoint when the cursor has a connection (a nested transaction rolls back only this block)."""
    connection = getattr(cur, "connection", None)
    block = connection.transaction() if connection is not None and hasattr(connection, "transaction") else nullcontext()
    with block:
        yield


def _call(fn, *args, **kwargs):
    """Call a lane function with only the keyword arguments its signature accepts (F's optional extensions, D-A32 `base`)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def _sse_start(start_response):
    start_response("200 OK", list(contracts.SSE_HEADERS))


def _log_closed(route: str, outcome: str, started: float, frames: int, sent: int, provider_attempts: int, request_id: str | None) -> None:
    """Content-free: route class, outcome code, counts and duration only (never ids of people, prompts or source)."""
    try:
        log.info(json.dumps({"event": "request.stream_closed", "route": route, "outcome": outcome, "durationMs": round((time.monotonic() - started) * 1000),
                             "frames": frames, "bytes": sent, "providerAttempts": provider_attempts, "requestId": request_id}))
    except Exception:  # noqa: BLE001 — logging never breaks a stream
        pass


# The fixed code vocabulary a rejection can carry (D-A48): web/src/lib/agent-runtime/ui-parser/validate.ts's literal prefixes,
# lang-core 0.3.2's ValidationErrorCode / OpenUIErrorCode (evidence/r0/openui-package.md) and the seam codes. Anything else is
# counted as "other", so an unexpected string can never reach the log.
REJECTION_CODES = frozenset((
    "action_denied", "action_id_not_literal", "bound_literal", "bounds_depth", "bounds_forms", "bounds_state", "bounds_statements",
    "component_denied", "duplicate_statement", "excess_args", "form_name_invalid", "href_not_allowed", "incomplete", "mutation_forbidden",
    "query_args_count", "query_args_shape", "query_binding_denied", "query_defaults_forbidden", "query_inline", "refresh_invalid",
    "root_invalid", "source_not_query", "state_name_invalid", "unexplained_deletion", "unknown_component", "unresolved_ref",
    "unreachable_statement", "query_as_child", "query_arg_placeholder",                       # D-A52 (stricter generate/arguments rules)
    "fence_in_source", "library_unsupported", "missing_base", "nesting_too_deep", "parse_exception", "revision_conflict",
    "source_too_large", "parse_rejected",
    "missing-required", "null-required", "unknown-component", "inline-reserved", "excess-args", "type-mismatch",
    "runtime-error", "render-error", "parse-exception", "parse-failed",
    *NOT_REPAIRABLE))


def _log_rejected(kind, errors) -> None:
    """Content-free: the validator's code prefixes (the part before ':') with counts, never the statement ids, names or source
    behind them, so first-pass rejections can be measured and fixed without logging what a view contained."""
    try:
        counts: dict = {}
        for error in errors[:contracts.BOUNDS.get("statements", 512)]:
            code = str(error).split(":", 1)[0]
            code = code if code in REJECTION_CODES else "other"
            counts[code] = counts.get(code, 0) + 1
        log.info(json.dumps({"event": "genui.validation_rejected", "kind": kind if kind in ("generate", "repair", "retry", "edit") else "other",
                             "codes": dict(sorted(counts.items())), "errorCount": len(errors)}))
    except Exception:  # noqa: BLE001 — logging never breaks a stream
        pass


class _Closing:
    """The WSGI iterable: delegates to a frame generator; `close()` (client gone or normal end) closes it exactly once. A stream
    closed before its first frame still runs the generator's cleanup through `on_unstarted`."""

    def __init__(self, generator, on_unstarted=None):
        self._generator, self._on_unstarted, self._started, self._closed = generator, on_unstarted, False, False

    def __iter__(self):
        return self

    def __next__(self):
        self._started = True
        return next(self._generator)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if not self._started and self._on_unstarted is not None:
            try:
                self._on_unstarted()
            except Exception:  # noqa: BLE001
                pass
        self._generator.close()


# --- data access (own SQL; exercised on PostgreSQL in tests/phase2/postgres_agent_ui_stream.py) ---------------------------
def _parent_run(cur, workspace_id, run_id) -> dict | None:
    cur.execute("/* rafii-ui:parent_run */ SELECT id::text, conversation_id::text, status, idempotency_key, actor::text, artifact->'result', "
                "extract(epoch from (now()-updated_at)) FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (str(run_id).lower(), workspace_id))
    row = cur.fetchone()
    if not row:
        return None
    result = row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if isinstance(row[5], str) else {})
    return {"runId": row[0], "conversationId": row[1], "status": row[2], "runKey": row[3] or "", "actor": row[4], "result": result or {},
            "ageSeconds": float(row[6] or 0)}


def _assert_parent_context(cur, auth, workspace_id, run_id) -> dict:
    """Read the current server parent in the authenticated tenant and scope.

    A cached UI handoff, projection or accepted revision is never authority for
    reusing a YouTube-derived answer after its native context was removed.
    """
    from . import ui_projection
    scope = getattr(auth, "scope", "workspace") or "workspace"
    scope_key = getattr(auth, "scope_key", "") or ""
    if str(getattr(auth, "workspace_id", "")) != str(workspace_id):
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
    parent = _parent_run(cur, workspace_id, run_id)
    if parent is None or not _run_in_scope(parent["runKey"], scope, scope_key):
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
    ui_projection.assert_presentable_parent(parent["result"])
    return parent


def _assert_artifact_parent_context(cur, auth, workspace_id, artifact_id) -> dict:
    head = _store_head(cur, auth, workspace_id, artifact_id)
    parent = _assert_parent_context(cur, auth, workspace_id, head["runId"])
    if str(parent["actor"]) != str(head["actor"]):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    return head


def _attempt_key_exists(cur, workspace_id, key) -> bool:
    cur.execute("/* rafii-ui:attempt_by_key */ SELECT id::text FROM public.pr_ui_attempts WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
    return cur.fetchone() is not None


def _run_in_scope(run_key: str, scope: str, scope_key: str) -> bool:
    """Consumer scope: an `agent:` run that is not a founder run. Founder scope: exactly this founder namespace's runs
    (`agent:founder:<mode>:<env>:…`, scope_key `founder:<mode>:<env>`)."""
    run_key = str(run_key or "")
    if scope == "founder":
        return bool(scope_key) and scope_key.startswith("founder:") and run_key.startswith(f"agent:{scope_key}:")
    return scope == "workspace" and run_key.startswith("agent:") and not run_key.startswith("agent:founder:")


def _artifact_head(cur, workspace_id, artifact_id, *, scope: str = "workspace", scope_key: str = "") -> dict:
    """The artifact in exactly the caller's scope (404 for a missing or foreign one, and for one of the other scope)."""
    cur.execute("/* rafii-ui:artifact_head */ SELECT a.parent_run_id::text, a.slot, a.actor::text, a.scope, a.scope_key, a.surface, a.journey_ids, a.revision, "
                "a.source_hash, a.manifest, a.current_attempt_id::text, r.idempotency_key FROM public.pr_ui_artifacts a JOIN public.pr_agent_runs r ON r.id=a.parent_run_id "
                "WHERE a.id::text=%s AND a.workspace_id=%s", (str(artifact_id).lower(), workspace_id))
    row = cur.fetchone()
    expected_key = scope_key if scope == "founder" else ""
    if not row or row[3] != scope or (row[4] or "") != expected_key or not _run_in_scope(row[11], scope, scope_key):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    manifest = row[9] if isinstance(row[9], dict) else (json.loads(row[9]) if isinstance(row[9], str) else {})
    return {"artifactId": str(artifact_id).lower(), "runId": row[0], "slot": row[1], "actor": row[2], "surface": row[5], "journeyIds": list(row[6] or []),
            "revision": int(row[7] or 0), "sourceHash": row[8], "manifest": manifest or {}, "currentAttemptId": row[10]}


def _revision_source(cur, workspace_id, artifact_id, revision) -> str | None:
    cur.execute("/* rafii-ui:revision_source */ SELECT source FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND workspace_id=%s AND revision=%s",
                (artifact_id, workspace_id, revision))
    row = cur.fetchone()
    return row[0] if row else None


def _current_attempt(cur, workspace_id, artifact_id) -> dict | None:
    cur.execute("/* rafii-ui:current_attempt */ SELECT t.id::text, t.state, t.target_revision, t.reservation_id, t.lease_expires_at < now() "
                "FROM public.pr_ui_artifacts a JOIN public.pr_ui_attempts t ON t.id=a.current_attempt_id WHERE a.id::text=%s AND a.workspace_id=%s",
                (artifact_id, workspace_id))
    row = cur.fetchone()
    if not row:
        return None
    return {"attemptId": row[0], "state": row[1], "targetRevision": row[2], "reservationId": row[3], "leaseExpired": bool(row[4])}


def _attempt_state(cur, workspace_id, attempt_id) -> str | None:
    cur.execute("/* rafii-ui:attempt_state */ SELECT state FROM public.pr_ui_attempts WHERE id::text=%s AND workspace_id=%s", (attempt_id, workspace_id))
    row = cur.fetchone()
    return row[0] if row else None


def _lock_workspace(cur, workspace_id) -> None:
    cur.execute("/* rafii-ui:workspace_lock */ SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))


def _throttle(cur, scope: str, limit: int, window: int) -> None:
    from ..hosted import throttle
    throttle(cur, scope, limit, window)


@contextmanager
def _connection(runtime):
    """One connection of the service's own factory (no Supabase call, no workspace lock) for stream-time writes."""
    db = runtime.service.repository.connection_factory()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def _service_tx(runtime, workspace_id):
    """Bookkeeping of an already admitted attempt (settle, terminal state, terminal event) when the request may be ending:
    a fresh connection, the workspace row locked (the Ledger's precondition), committed on success, rolled back on error.
    It never grants anything new, so it does not re-verify the session (a client that just left has no request to verify)."""
    with _connection(runtime) as db:
        cur = db.cursor()
        try:
            _lock_workspace(cur, workspace_id)
            yield cur
            db.commit()
        except BaseException:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise


def _sweep(runtime, cur, workspace_id) -> None:
    """Heal dead producers before a new admission (lane F: expired leases → interrupted + unknown; lane B: holds of terminal
    attempts nobody settled). Never fails the request."""
    ledger = getattr(getattr(runtime, "service", None), "ledger", None)
    for step in (lambda: _call(_ui_store().reap_expired, cur, workspace_id, None, ledger=ledger), lambda: ui_metering.settle_orphans(runtime, cur, workspace_id)):
        try:
            with _savepoint(cur):
                step()
        except Exception:  # noqa: BLE001
            pass


def _ui_store():
    from . import ui_store
    return ui_store


def _assets(runtime):
    return ui_presenter.load_assets(getattr(runtime, "ui_assets_dir", None))


# --- the presenter worker (async provider stream in its own thread) ------------------------------------------------------
class _Worker:
    """Runs one presenter attempt with asyncio.run in a daemon thread and hands its items to the WSGI generator through a
    bounded queue (backpressure pauses the provider read, never drops a delta). `stop()` cancels the task in its own loop."""

    def __init__(self, factory, size: int = QUEUE_ITEMS):
        self.queue: queue.Queue = queue.Queue(maxsize=size)
        self._factory, self._loop, self._task = factory, None, None
        self._stopping = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="rafii-ui-presenter", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            asyncio.run(self._main())
        except BaseException as error:  # noqa: BLE001 — reported to the consumer, never raised in a daemon thread
            self._offer(("error", error))
        finally:
            self._offer(("done", None))

    async def _main(self):
        self._loop, self._task = asyncio.get_running_loop(), asyncio.current_task()
        if self._stopping.is_set():
            return
        agen = self._factory()
        try:
            async for item in agen:
                await self._put(("item", item))
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001
            await self._put(("error", error))
        finally:
            closer = getattr(agen, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except BaseException:  # noqa: BLE001
                    pass

    async def _put(self, item):
        while True:
            try:
                self.queue.put_nowait(item)
                return
            except queue.Full:
                if self._stopping.is_set():
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.02)

    def _offer(self, item):
        try:
            self.queue.put(item, timeout=1.0)
        except queue.Full:
            pass

    def get(self, timeout: float):
        try:
            return self.queue.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    def stop(self, join: float = WORKER_JOIN_SECONDS):
        self._stopping.set()
        loop, task = self._loop, self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        if self.thread is not None:
            self.thread.join(join)

    def drain(self) -> list:
        items = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                return items


# --- the producer --------------------------------------------------------------------------------------------------------
class _Outcome:
    def __init__(self, kind, *, candidate="", usage=None, reason=None):
        self.kind, self.candidate, self.usage, self.reason = kind, candidate, usage, reason


class _Producer:
    """Owns one admitted attempt chain (the attempt, then at most one automatic repair) for the lifetime of one request."""

    def __init__(self, runtime, tx, auth, workspace_id, *, lease, plan, projection, manifest, base_source, instruction, selection, deadline,
                 first_events, terminal, owner, route, request_id, started):
        # `tx(need)` opens the caller's short authorized transaction (consumer: ui_http.ui_transaction; founder: the control
        # boundary's own), so the same producer serves both route families.
        self.runtime, self.tx, self.auth, self.workspace_id = runtime, tx, auth, workspace_id
        self.artifact, self.attempt, self.plan = lease["artifact"], lease["attempt"], plan
        self.projection, self.manifest = projection or {}, manifest or {}
        self.base_source, self.instruction, self.selection = base_source, instruction, selection
        self.deadline, self.owner, self.route, self.request_id, self.started = deadline, owner, route, request_id, started
        self.first_events, self.done = list(first_events), terminal
        self.last_seq = max([e["seq"] for e in first_events] or [int(lease.get("replay_cursor") or 0)])
        self.frames_sent, self.bytes_sent, self.provider_attempts, self.outcome = 0, 0, 0, "unknown"
        self.worker, self.dispatched, self.usage = None, False, None
        self.settled: set = set()
        self.last_sent = time.monotonic()
        self.timing = {"admittedAt": contracts.now_iso()}
        self._db = None

    # --- frames ---------------------------------------------------------------------------------------------------------
    def _frame(self, event) -> bytes:
        data = contracts.sse_frame(event, retry_ms=2000 if self.frames_sent == 0 else None)
        self.frames_sent += 1
        self.bytes_sent += len(data)
        self.last_sent = time.monotonic()
        if event.get("kind") != "ui.heartbeat":
            self.last_seq = max(self.last_seq, int(event.get("seq") or 0))
        return data

    def _heartbeat(self) -> bytes:
        # D-A36: not persisted; reuses the last sent seq so Last-Event-ID stays correct.
        return self._frame(contracts.make_event(self.artifact["artifactId"], self.attempt["attemptId"], self._revision(), self.last_seq, "ui.heartbeat", {}))

    def _revision(self) -> int:
        return int(self.attempt.get("targetRevision") or (int(self.artifact.get("revision") or 0) + 1))

    def _cursor(self):
        if self._db is None:
            self._db = self.runtime.service.repository.connection_factory()
        return self._db.cursor()

    def _commit(self):
        if self._db is not None:
            self._db.commit()

    def _close_db(self):
        if self._db is not None:
            try:
                self._db.close()
            except Exception:  # noqa: BLE001
                pass
            self._db = None

    def _append(self, kind, payload) -> dict:
        cur = self._cursor()
        try:
            if kind == "ui.delta":
                _lock_workspace(cur, self.workspace_id)
                _assert_parent_context(cur, self.auth, self.workspace_id, self.artifact["runId"])
            event = _ui_store().append_event(cur, self.artifact["artifactId"], self.attempt["attemptId"], self._revision(), kind, payload)
            self._commit()
            return event
        except BaseException:
            try:
                self._db.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise

    # --- the generator ----------------------------------------------------------------------------------------------------
    def frames(self):
        try:
            with self.tx("read") as (cur, auth):
                _assert_parent_context(cur, auth, self.workspace_id, self.artifact["runId"])
            for event in self.first_events:
                yield self._frame(event)
            if self.done:
                self.outcome = "refused"
                return
            while True:
                outcome = yield from self._run_attempt()
                if outcome.kind == "closed":
                    yield from self._closed(outcome)
                    return
                if outcome.kind == "terminal":
                    yield from self._terminal("ui.failed", "failed", outcome.reason, outcome.usage)
                    return
                status = (outcome.usage or {}).get("status")
                if status not in ("ok", "incomplete"):
                    given = (outcome.usage or {}).get("reason")
                    reason = given if given in contracts.REASON_CODES else ("provider_timeout" if status == "timeout" else "provider_error")
                    yield from self._terminal("ui.failed", "failed", reason, outcome.usage)
                    return
                candidate = ui_presenter.strip_fences(outcome.candidate)
                validation = self._validate(candidate)
                if validation.get("accepted"):
                    yield from self._ready(candidate, validation, outcome.usage)
                    return
                errors = [str(e) for e in validation.get("errors") or []] or ["parse_rejected"]
                _log_rejected(self.attempt.get("kind"), errors)
                fatal = next((NOT_REPAIRABLE[e.split(":", 1)[0]] for e in errors if e.split(":", 1)[0] in NOT_REPAIRABLE), None)
                if fatal is not None:
                    # The model can't fix this (seam down, deploy/asset skew, size, missing base): no second paid call.
                    yield from self._terminal("ui.failed", "failed", fatal, outcome.usage)
                    return
                if self.attempt.get("kind") == "repair":
                    yield from self._terminal("ui.failed", "failed", "repair_exhausted", outcome.usage)
                    return
                if self.deadline - time.monotonic() < MIN_REPAIR_SECONDS:
                    yield from self._terminal("ui.failed", "failed", "parse_rejected", outcome.usage)
                    return
                started = yield from self._repair(candidate, errors, outcome.usage)
                if not started:
                    return
        except GeneratorExit:
            self._abandon("client_gone")
            raise
        except Exception as error:  # noqa: BLE001 — every failure ends in a terminal frame with a stable reason
            log.error(json.dumps({"event": "agent_ui.stream_failed", "errorClass": type(error).__name__, "requestId": self.request_id}))
            self._stop_worker()          # book what the provider task knows before settling, never after
            frame = self._safe_terminal("ui.failed", "failed", "internal_error")
            if frame is not None:
                yield frame
        finally:
            self._stop_worker()
            self._close_db()
            _log_closed("agent.ui.presentations", self.outcome, self.started, self.frames_sent, self.bytes_sent, self.provider_attempts, self.request_id)

    def unstarted(self):
        """close() before the first frame: the client left during admission; the attempt is interrupted, never produced."""
        if not self.done:
            self._abandon("client_gone")
            self.done = True

    # --- one attempt ------------------------------------------------------------------------------------------------------
    def _presenter_items(self):
        # A prebuilt plan does not bypass the current parent check. Release the
        # short authorized transaction before starting any provider transport.
        with self.tx("read") as (cur, auth):
            _assert_parent_context(cur, auth, self.workspace_id, self.artifact["runId"])
        context = ui_presenter.PresenterContext(cfg=self.runtime.cfg, plan=self.plan, manifest=self.manifest, transport=getattr(self.runtime, "ui_transport", None),
                                                deadline=self.deadline)
        return ui_presenter.stream_presentation(context, self.projection, self.artifact["artifactId"], self.attempt["attemptId"], mode=self.plan.mode,
                                                base_source=self.base_source, instruction=self.instruction)

    def _run_attempt(self):
        self.dispatched, self.usage = False, None
        founder = getattr(self.auth, "scope", "workspace") == "founder"
        limit = (contracts.BOUNDS["founderPatchBytes"] if founder else contracts.BOUNDS["patchBytes"]) if self.plan.mode == "patch" else contracts.BOUNDS["sourceBytes"]
        worker = self.worker = _Worker(self._presenter_items)
        worker.start()
        parts, pending, pending_since = [], [], None
        total, flushed, checkpointed, checkpoint_at = 0, 0, 0, time.monotonic()
        last_poll = time.monotonic()
        finished = False
        while True:
            now = time.monotonic()
            waits = [self.last_sent + HEARTBEAT_SECONDS - now, last_poll + CANCEL_POLL_SECONDS - now, self.deadline + WORKER_GRACE_SECONDS - now]
            if pending:
                waits.append(pending_since + FLUSH_SECONDS - now)
            item = worker.get(max(0.005, min(waits))) if not finished else None
            now = time.monotonic()
            if item is not None:
                tag, value = item
                if tag == "item" and isinstance(value, dict):
                    kind = value.get("type")
                    if kind == "dispatch":
                        self.dispatched = True
                        self.provider_attempts += 1
                        self.timing.setdefault("dispatchedAt", contracts.now_iso())
                    elif kind == "delta" and isinstance(value.get("text"), str) and value["text"]:
                        text = value["text"]
                        size = len(text.encode("utf-8"))
                        if total + size > limit:
                            self._stop_worker()
                            return _Outcome("terminal", usage=self._interrupted_usage(), reason="source_too_large")
                        parts.append(text)
                        pending.append(text)
                        total += size
                        pending_since = pending_since or now
                    elif kind == "usage":
                        self.usage = dict(value)
                        self.dispatched = self.dispatched or bool(value.get("dispatched"))
                elif tag == "error":
                    self._stop_worker()
                    return _Outcome("terminal", usage=self._interrupted_usage(), reason="internal_error")
                elif tag == "done":
                    finished = True
            # Flush coalesced deltas (persist, then send).
            if pending and (finished or sum(len(p.encode("utf-8")) for p in pending) >= FLUSH_BYTES or now - pending_since >= FLUSH_SECONDS):
                text = "".join(pending)
                pending, pending_since = [], None
                for chunk in _chunks(text, FRAME_MAX_BYTES):
                    event = self._append("ui.delta", {"append": chunk, "offset": flushed, "attempt": self.attempt["attemptId"]})
                    flushed += len(chunk.encode("utf-8"))
                    if checkpointed == 0 and flushed > 0:
                        closed = self._checkpoint("".join(parts)[:], flushed)
                        if closed:
                            self._stop_worker()
                            return closed
                        checkpointed, checkpoint_at = flushed, time.monotonic()
                        self.timing.setdefault("firstDeltaAt", contracts.now_iso())
                    yield self._frame(event)
            # Coarse durable checkpoint (>= 4 KiB or >= 1 s of new source).
            if flushed > checkpointed and (flushed - checkpointed >= CHECKPOINT_BYTES or now - checkpoint_at >= CHECKPOINT_SECONDS):
                closed = self._checkpoint("".join(parts), flushed)
                if closed:
                    self._stop_worker()
                    return closed
                checkpointed, checkpoint_at = flushed, time.monotonic()
                yield self._frame(self._append("ui.checkpoint", {"cursor": flushed, "hash": contracts.sha256_text(_prefix_bytes("".join(parts), flushed))}))
            if finished and not pending:
                break
            # Cancel / reap poll (the attempt row is the only signal another request can give this producer).
            if now - last_poll >= CANCEL_POLL_SECONDS:
                last_poll = now
                state = self._state()
                if state not in LIVE_STATES:
                    self._stop_worker()
                    return _Outcome("closed", usage=self._interrupted_usage(), reason="canceled_by_user" if state == "canceled" else "lease_expired")
            if time.monotonic() > self.deadline + WORKER_GRACE_SECONDS:
                self._stop_worker()
                return _Outcome("terminal", usage=self._interrupted_usage("timeout"), reason="provider_timeout")
            if time.monotonic() - self.last_sent >= HEARTBEAT_SECONDS:
                yield self._heartbeat()
        self.worker = None
        usage = self.usage or self._interrupted_usage()
        return _Outcome("finished", candidate="".join(parts), usage=usage)

    def _state(self) -> str | None:
        cur = self._cursor()
        try:
            state = _attempt_state(cur, self.workspace_id, self.attempt["attemptId"])
            self._commit()
            return state
        except BaseException:
            try:
                self._db.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise

    def _checkpoint(self, source, flushed) -> _Outcome | None:
        cur = self._cursor()
        try:
            _lock_workspace(cur, self.workspace_id)
            _assert_parent_context(cur, self.auth, self.workspace_id, self.artifact["runId"])
            _ui_store().checkpoint(cur, self.attempt["attemptId"], _prefix_bytes(source, flushed), lease_owner=self.owner)
            self._commit()
            return None
        except AlphaError as error:
            try:
                self._db.rollback()
            except Exception:  # noqa: BLE001
                pass
            if error.code == "ui_attempt_closed":
                return _Outcome("closed", usage=self._interrupted_usage(), reason="canceled_by_user")
            if error.code == "ui_lease_lost":
                return _Outcome("closed", usage=self._interrupted_usage(), reason="lease_expired")
            if error.status == 413:
                return _Outcome("terminal", usage=self._interrupted_usage(), reason="source_too_large")
            raise

    def _stop_worker(self):
        worker, self.worker = self.worker, None
        if worker is None:
            return
        worker.stop()
        for tag, value in worker.drain():
            if tag == "item" and isinstance(value, dict):
                if value.get("type") == "dispatch":
                    self.dispatched = True
                elif value.get("type") == "usage":
                    self.usage = dict(value)

    def _interrupted_usage(self, status: str = "cancelled") -> dict:
        """What is known about an attempt that was cut: its final usage if the provider finished, else unknown after dispatch
        (the hold stays), else never sent (released at 0)."""
        if self.usage and self.usage.get("known"):
            return dict(self.usage)
        route = getattr(self.plan, "route", None)
        base = {"model": getattr(route, "model", None), "provider": getattr(route, "provider", None)}
        if self.dispatched:
            return {**base, "dispatched": True, "known": False, "status": status, "costState": "unknown"}
        return {**base, "dispatched": False, "known": True, "status": "failed", "inputTokens": 0, "outputTokens": 0, "costUsdMicro": 0}

    # --- validation, repair, commit -------------------------------------------------------------------------------------
    def _validate(self, candidate: str) -> dict:
        from . import ui_validator
        self._mark_validating()
        started = time.monotonic()
        scope = {"workspaceId": self.workspace_id, "artifactId": self.artifact["artifactId"], "attemptId": self.attempt["attemptId"]}
        try:
            result = ui_validator.validate_and_merge_ui(self.base_source if self.plan.mode == "patch" else None, candidate, self.plan.library_hash, self.plan.mode,
                                                        policy=dict(self.plan.policy), scope=scope)
        except Exception:  # noqa: BLE001 — the seam answers "not accepted" on any failure
            result = {"accepted": False, "errors": ["validation_unavailable"]}
        self.timing["validationMs"] = round((time.monotonic() - started) * 1000)
        return result if isinstance(result, dict) else {"accepted": False, "errors": ["validation_unavailable"]}

    def _mark_validating(self):
        cur = self._cursor()
        try:
            _ui_store().finish_attempt(cur, self.attempt["attemptId"], "validating")
            self._commit()
        except Exception:  # noqa: BLE001 — a cosmetic state; the commit below is the authority
            try:
                self._db.rollback()
            except Exception:  # noqa: BLE001
                pass

    def _ready(self, candidate, validation, usage):
        attempt_id = self.attempt["attemptId"]
        failure, settled_here = None, False
        try:
            with self.tx("edit") as (cur, auth):
                _assert_parent_context(cur, auth, self.workspace_id, self.artifact["runId"])
                if _attempt_state(cur, self.workspace_id, attempt_id) not in LIVE_STATES:
                    failure = "closed"
                else:
                    settled = ui_metering.settle_attempt(self.runtime, cur, auth, self.attempt, usage)
                    settled_here = True
                    patch = {"artifactId": self.artifact["artifactId"], "attemptId": attempt_id, "baseRevision": int(self.artifact.get("revision") or 0),
                             "baseSourceHash": self.artifact.get("sourceHash") or None, "patchSource": candidate, "idempotencyKey": self.attempt.get("idempotencyKey"),
                             "promptHash": self.plan.prompt_hash, "languageVersion": self.plan.language_version}
                    try:
                        with _savepoint(cur):
                            artifact = _ui_store().commit_ui_revision(cur, auth, patch, validation)
                    except AlphaError as error:
                        reason = {"ui_revision_conflict": "revision_conflict", "ui_attempt_closed": "canceled_by_user", "source_too_large": "source_too_large",
                                  "library_unsupported": "library_unsupported"}.get(error.code, "parse_rejected" if error.status == 422 else "revision_conflict")
                        failure = reason
                        if reason != "canceled_by_user":
                            _ui_store().finish_attempt(cur, attempt_id, "failed", reason)
                            event = _ui_store().append_event(cur, self.artifact["artifactId"], attempt_id, int(self.artifact.get("revision") or 0), "ui.failed",
                                                             {"reason": reason, "fallback": "native", "attempt": attempt_id})
                    else:
                        canonical = validation.get("canonicalSource") or ""
                        self.timing["readyAt"] = contracts.now_iso()
                        payload = {"revision": artifact.get("revision"), "sourceHash": artifact.get("sourceHash"), "validationState": "accepted", "attempt": attempt_id,
                                   "promptHash": self.plan.prompt_hash, "libraryHash": self.plan.library_hash, "costState": settled.get("costState"),
                                   "providerAttempts": self.provider_attempts, "timing": dict(self.timing),
                                   "canonicalSource": canonical if len(canonical.encode("utf-8")) <= READY_INLINE_BYTES else None}
                        event = _ui_store().append_event(cur, self.artifact["artifactId"], attempt_id, int(artifact.get("revision") or 0), "ui.ready", payload)
        except AlphaError:
            failure, settled_here = "error", False
        if settled_here:
            self.settled.add(attempt_id)
        if failure is None:
            self.outcome, self.done = "ready", True
            yield self._frame(event)
            return
        if failure == "closed" or failure == "canceled_by_user":
            yield from self._closed(_Outcome("closed", usage=usage, reason="canceled_by_user"))
            return
        if failure == "error":
            # The finalize transaction itself failed (session or membership gone, database): book what is known, never ready.
            yield from self._terminal("ui.failed", "failed", "internal_error", usage)
            return
        self.outcome, self.done = failure, True
        yield self._frame(event)

    def _repair(self, candidate, errors, usage):
        """Exactly one automatic, presentation-only repair: settle the rejected attempt, claim the repair attempt (F, derived key),
        build its plan with the validator's codes, reserve it separately inside the same chain, then stream it."""
        original = self.attempt
        refused, event = None, None
        try:
            with self.tx("edit") as (cur, auth):
                _assert_parent_context(cur, auth, self.workspace_id, self.artifact["runId"])
                ui_metering.settle_attempt(self.runtime, cur, auth, original, usage)
                _ui_store().finish_attempt(cur, original["attemptId"], "failed", "parse_rejected")
                lease = _call(_ui_store().create_or_resume_artifact, cur, auth, self.artifact["runId"], self.artifact.get("slot") or "main",
                              _repair_key(original.get("idempotencyKey") or original["attemptId"]), surface=self.artifact.get("surface") or "chat",
                              manifest=self.manifest, projection=self.projection, kind="repair", retry_of=original["attemptId"], lease_owner=self.owner,
                              base=_base_of(original, self.instruction), base_revision=original.get("baseRevision"),
                              base_source_hash=original.get("baseSourceHash"), instruction=self.instruction)
                if not lease.get("created"):
                    raise AlphaError("This view was already repaired once.", 409, code="repair_exhausted")
                repair = lease["attempt"]
                plan = ui_presenter.build_plan(self.runtime.cfg, _assets(self.runtime), self.projection, self.manifest, kind="repair", mode=self.plan.mode,
                                               chain=self.plan.chain, base_source=self.base_source, base_revision=original.get("baseRevision"),
                                               instruction=self.instruction, selection=self.selection, rejected_source=candidate, errors=errors)
                try:
                    with _savepoint(cur):
                        ui_metering.reserve_attempt(self.runtime, cur, auth, self.artifact, repair, plan)
                except AlphaError as error:
                    refused = ui_metering.reason_for(error)
                    _ui_store().finish_attempt(cur, repair["attemptId"], "failed", refused)
                    event = _ui_store().append_event(cur, self.artifact["artifactId"], repair["attemptId"], int(self.artifact.get("revision") or 0), "ui.failed",
                                                     {"reason": refused, "fallback": "native", "attempt": repair["attemptId"]})
                else:
                    event = _ui_store().append_event(cur, self.artifact["artifactId"], repair["attemptId"], int(repair.get("targetRevision") or 0), "ui.started",
                                                     _started_payload(self.artifact, repair, plan, self.manifest, retry_of=original["attemptId"]))
        except (AlphaError, ui_presenter.PresentationRefused) as error:
            # The original attempt is settled only if that transaction committed; book it here otherwise.
            reason = getattr(error, "reason", None) or ("repair_exhausted" if getattr(error, "code", "") == "repair_exhausted" else "parse_rejected")
            yield from self._terminal("ui.failed", "failed", reason if reason in contracts.REASON_CODES else "parse_rejected", usage)
            return False
        self.settled.add(original["attemptId"])
        self.attempt, self.plan = repair, plan
        if refused:
            self.outcome, self.done = refused, True
            self.settled.add(repair["attemptId"])
            yield self._frame(event)
            return False
        yield self._frame(event)
        return True

    # --- terminal paths -------------------------------------------------------------------------------------------------
    def _book(self, cur, attempt, usage, state, reason) -> None:
        if attempt["attemptId"] not in self.settled:
            ui_metering.settle_attempt(self.runtime, cur, self.auth, attempt, usage or self._interrupted_usage())
        try:
            with _savepoint(cur):
                _ui_store().finish_attempt(cur, attempt["attemptId"], state, reason)
        except (AlphaError, ValueError):
            pass   # already terminal (canceled by the person, reaped): keep that state

    def _terminal(self, kind, state, reason, usage):
        event = None
        with _service_tx(self.runtime, self.workspace_id) as cur:
            self._book(cur, self.attempt, usage, state, reason)
            event = _ui_store().append_event(cur, self.artifact["artifactId"], self.attempt["attemptId"], int(self.artifact.get("revision") or 0), kind,
                                             {"reason": reason, "fallback": "native", "attempt": self.attempt["attemptId"]})
        self.settled.add(self.attempt["attemptId"])
        self.outcome, self.done = reason, True
        yield self._frame(event)

    def _closed(self, outcome):
        """Canceled by the person (another request) or reaped: settle what this producer knows, then forward the terminal event
        that request persisted (never a second terminal event)."""
        with _service_tx(self.runtime, self.workspace_id) as cur:
            self._book(cur, self.attempt, outcome.usage, "canceled" if outcome.reason == "canceled_by_user" else "interrupted", outcome.reason)
            events = _ui_store().events_after(cur, self.auth, self.artifact["artifactId"], self.last_seq, contracts.BOUNDS["replayPageEvents"])
        self.settled.add(self.attempt["attemptId"])
        self.outcome, self.done = outcome.reason, True
        forwarded = False
        for event in events:
            if event.get("kind") != "ui.delta":
                forwarded = forwarded or event.get("kind") in contracts.TERMINAL_EVENT_KINDS
                yield self._frame(event)
        if not forwarded:
            kind = "ui.canceled" if outcome.reason == "canceled_by_user" else "ui.interrupted"
            yield self._frame(contracts.make_event(self.artifact["artifactId"], self.attempt["attemptId"], int(self.artifact.get("revision") or 0), self.last_seq,
                                                   kind, {"reason": outcome.reason, "fallback": "native", "persisted": False}))

    def _safe_terminal(self, kind, state, reason):
        try:
            with _service_tx(self.runtime, self.workspace_id) as cur:
                self._book(cur, self.attempt, None, state, reason)
                event = _ui_store().append_event(cur, self.artifact["artifactId"], self.attempt["attemptId"], int(self.artifact.get("revision") or 0), kind,
                                                 {"reason": reason, "fallback": "native", "attempt": self.attempt["attemptId"]})
            self.settled.add(self.attempt["attemptId"])
            self.outcome, self.done = reason, True
            return self._frame(event)
        except Exception:  # noqa: BLE001 — the lease reaper settles it as unknown later; the client keeps the native answer
            self.outcome, self.done = reason, True
            fallback = contracts.make_event(self.artifact["artifactId"], self.attempt["attemptId"], int(self.artifact.get("revision") or 0), self.last_seq,
                                            kind, {"reason": reason, "fallback": "native", "persisted": False})
            return self._frame(fallback)

    def _abandon(self, reason):
        """The client left mid-stream: cancel the provider task, mark interrupted, settle once. No frame can be sent."""
        if self.done:
            return
        self.done = True
        self._stop_worker()
        self.outcome = reason
        try:
            with _service_tx(self.runtime, self.workspace_id) as cur:
                self._book(cur, self.attempt, self._interrupted_usage(), "interrupted", reason)
                _ui_store().append_event(cur, self.artifact["artifactId"], self.attempt["attemptId"], int(self.artifact.get("revision") or 0), "ui.interrupted",
                                         {"reason": reason, "fallback": "native", "attempt": self.attempt["attemptId"]})
            self.settled.add(self.attempt["attemptId"])
        except Exception as error:  # noqa: BLE001 — the lease expires and F's reaper settles it unknown
            log.error(json.dumps({"event": "agent_ui.abandon_failed", "errorClass": type(error).__name__, "requestId": self.request_id}))


def _chunks(text: str, limit: int):
    """Split text into pieces of at most `limit` UTF-8 bytes on character boundaries."""
    out, current, size = [], [], 0
    for char in text:
        n = len(char.encode("utf-8"))
        if current and size + n > limit:
            out.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += n
    if current:
        out.append("".join(current))
    return out


def _prefix_bytes(text: str, nbytes: int) -> str:
    data = text.encode("utf-8")[:nbytes]
    return data.decode("utf-8", errors="ignore")


def _base_of(attempt, instruction):
    if attempt.get("baseRevision") is None:
        return None
    return {"revision": attempt.get("baseRevision"), "sourceHash": attempt.get("baseSourceHash"), "instruction": instruction, "selection": None}


def _started_payload(artifact, attempt, plan, manifest, *, retry_of=None, surface=None) -> dict:
    """ui.started: identity, kind, library/language/manifest versions and the PUBLIC manifest only (no private data, no targets)."""
    return {"attempt": attempt["attemptId"], "kind": attempt.get("kind"), "retryOf": retry_of, "targetRevision": attempt.get("targetRevision"),
            "baseRevision": attempt.get("baseRevision"), "libraryVersion": plan.library_version, "libraryHash": plan.library_hash, "library": plan.library,
            "languageVersion": plan.language_version, "promptHash": plan.prompt_hash, "manifestId": (manifest or {}).get("manifestId"),
            "bindingVersion": (manifest or {}).get("bindingVersion"), "manifest": contracts.public_manifest(manifest or {}),
            "surface": surface or artifact.get("surface"), "timeOrigin": "presentation_admission"}


# --- admission ------------------------------------------------------------------------------------------------------------
def _admit(runtime, cur, auth, lease, *, plan, refusal, manifest, retry_of=None):
    """After a new claim: reserve (or persist the refusal). Returns (first events, terminal?)."""
    store = _ui_store()
    artifact, attempt = lease["artifact"], lease["attempt"]
    if refusal is None:
        try:
            with _savepoint(cur):
                ui_metering.reserve_attempt(runtime, cur, auth, artifact, attempt, plan)
        except AlphaError as error:
            refusal = ui_metering.reason_for(error)
    if refusal is not None:
        store.finish_attempt(cur, attempt["attemptId"], "failed", refusal)
        event = store.append_event(cur, artifact["artifactId"], attempt["attemptId"], int(artifact.get("revision") or 0), "ui.failed",
                                   {"reason": refusal, "fallback": "native", "attempt": attempt["attemptId"]})
        return [event], True
    event = store.append_event(cur, artifact["artifactId"], attempt["attemptId"], int(attempt.get("targetRevision") or 1), "ui.started",
                               _started_payload(artifact, attempt, plan, manifest, retry_of=retry_of))
    return [event], False


def _deadline(started: float) -> float:
    """60 s for the presenter including its repair, capped by what the function invocation has left."""
    return started + min(GENERATION_SECONDS, DEPLOYMENT_SECONDS - DEPLOYMENT_MARGIN_SECONDS)


def _flags(runtime, workspace_id, scope) -> dict:
    """The deployment's GenUI switches for this workspace (founder ones in founder scope); the routes re-check them independently."""
    try:
        return runtime.cfg.genui_for(workspace_id, founder=scope == "founder")
    except Exception:  # noqa: BLE001 — unknown switches: no write controls
        return {"enabled": True, "actions": False, "edits": False}


def _without_disabled_actions(manifest, flags):
    """With the actions kill switch off the presenter never composes a write control: no action ids in its prompt or in the
    validator policy (an ActionButton is then rejected). The stored manifest of an existing artifact is not rewritten."""
    if not isinstance(manifest, dict) or (flags or {}).get("actions"):
        return manifest
    return {**manifest, "actions": []}


def _plan_or_refusal(build):
    try:
        return build(), None
    except ui_presenter.PresentationRefused as refused:
        return None, refused.reason


def _library_info(plan):
    if plan is None:
        return None
    return {"libraryHash": plan.library_hash, "libraryVersion": plan.library_version, "languageVersion": plan.language_version, "promptHash": plan.prompt_hash}


def _consumer_tx(runtime, token, workspace_id):
    return lambda need: ui_http.ui_transaction(runtime, token, workspace_id, need)


def _start_presentation(runtime, tx, workspace_id, request, *, started, request_id):
    """Admission of one presentation (shared by the consumer stream and blocking route families). Returns
    ("replay", auth, artifact_id, cursor) for an attempt this request must not produce, or ("produce", producer)."""
    owner = _lease_owner()
    store = _ui_store()
    from . import ui_capabilities, ui_projection
    with tx("edit") as (cur, auth):
        scope = getattr(auth, "scope", "workspace") or "workspace"
        parent = _assert_parent_context(cur, auth, workspace_id, request["parentRunId"])
        if (request.get("surface") == "founder") != (scope == "founder"):
            raise AlphaError("Unknown surface.", 400, code="ui_surface")
        if parent["actor"] != str(auth.principal):
            # Presentations are metered to the person whose turn it was (the conversation may be shared; replay stays open).
            raise AlphaError("Only the person who asked can start this view.", 403, code="ui_forbidden")
        if request.get("conversationId") and request["conversationId"].lower() != str(parent["conversationId"]).lower():
            raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
        _sweep(runtime, cur, workspace_id)
        key, retry_of = request["idempotencyKey"], request.get("retryOfAttemptId")
        kind = "retry" if retry_of else "generate"
        if _attempt_key_exists(cur, workspace_id, key):
            lease = _call(store.create_or_resume_artifact, cur, auth, parent["runId"], request["slot"], key, surface=request["surface"], manifest=None,
                          projection=None, kind=kind, retry_of=retry_of, lease_owner=owner)
            return "replay", auth, lease["artifact"]["artifactId"], int(lease.get("replay_cursor") or 0)
        result = parent["result"] or {}
        usage = result.get("usage") or {}
        if (parent["status"] != "completed" or result.get("composedBy") != "manager" or usage.get("billing") != "metered"
                or not (result.get("ui") or {}).get("eligible")):
            # Plain text, greetings, fallbacks and deterministic answers never reach the presenter.
            raise AlphaError("This answer doesn't need an interactive view.", 409, code="ui_not_eligible")
        if retry_of is None and parent["ageSeconds"] > FRESH_SECONDS:
            # Reopening an old answer shows its stored state; it never starts (or charges for) a new generation.
            raise AlphaError("This answer is too old to start an interactive view; ask again for a fresh one.", 409, code="ui_not_eligible")
        verified = {**result, "runId": parent["runId"], "conversationId": parent["conversationId"]}
        flags = _flags(runtime, workspace_id, scope)
        projection = _call(ui_projection.project_ui_context, cur, auth, verified, request["surface"], {}, flags=flags)
        # Lane D's projection carries the manifest it built from the same journeys for this member (deterministic per issue).
        manifest = projection.get("manifest") if isinstance(projection.get("manifest"), dict) else _call(ui_capabilities.build_manifest, cur, auth, projection,
                                                                                                          scope=scope, flags=flags)
        manifest = _without_disabled_actions(manifest, flags)
        plan, refusal = _plan_or_refusal(lambda: ui_presenter.build_plan(runtime.cfg, _assets(runtime), projection, manifest, kind=kind, mode="generate"))
        lease = _call(store.create_or_resume_artifact, cur, auth, parent["runId"], request["slot"], key, surface=request["surface"], manifest=manifest,
                      projection=projection, kind=kind, retry_of=retry_of, lease_owner=owner, library=_library_info(plan))
        if not lease.get("created"):
            return "replay", auth, lease["artifact"]["artifactId"], int(lease.get("replay_cursor") or 0)
        events, terminal = _admit(runtime, cur, auth, lease, plan=plan, refusal=refusal, manifest=manifest, retry_of=retry_of)
    producer = _Producer(runtime, tx, auth, workspace_id, lease=lease, plan=plan, projection=projection, manifest=manifest, base_source=None, instruction=None,
                         selection=None, deadline=_deadline(started), first_events=events, terminal=terminal, owner=owner, route="presentations",
                         request_id=request_id, started=started)
    return "produce", producer


def create_presentation(runtime, environ, start_response, workspace_id, token, request):
    """POST …/agent/ui/presentations → text/event-stream of one presentation attempt (or a replay of the existing one)."""
    started = time.monotonic()
    admitted = _start_presentation(runtime, _consumer_tx(runtime, token, workspace_id), workspace_id, request, started=started,
                                   request_id=_request_id(environ))
    if admitted[0] == "replay":
        _, auth, artifact_id, cursor = admitted
        return _replay_stream(runtime, environ, start_response, workspace_id, auth, artifact_id, cursor, route="agent.ui.presentations")
    producer = admitted[1]
    _sse_start(start_response)
    return _Closing(producer.frames(), producer.unstarted)


def _drain_producer(producer) -> dict:
    frames = producer.frames()
    try:
        for _ in frames:
            pass
    finally:
        frames.close()
    return {"artifactId": producer.artifact["artifactId"], "attemptId": producer.attempt["attemptId"], "producing": True, "outcome": producer.outcome,
            "lastSeq": producer.last_seq}


def run_presentation(runtime, workspace_id, request, *, transaction, request_id=None) -> dict:
    """Blocking form for a route family that cannot stream (D-A22 founder: durable checkpoints + `GET …/events?after=` polling).
    `transaction(need)` yields (cur, UiAuth) from that boundary's own authentication (founder scope set server-side). Produces
    the attempt to its terminal state inside this request; a duplicate key or another live producer only reports the artifact."""
    started = time.monotonic()
    admitted = _start_presentation(runtime, transaction, workspace_id, request, started=started, request_id=request_id)
    if admitted[0] == "replay":
        return {"artifactId": admitted[2], "producing": False, "replayCursor": admitted[3]}
    return _drain_producer(admitted[1])


def _start_edit(runtime, tx, workspace_id, artifact_id, request, *, started, request_id):
    """Admission of one explicit edit. Returns ("replay", auth, artifact_id, cursor) or ("produce", producer)."""
    owner = _lease_owner()
    store = _ui_store()
    from . import ui_capabilities
    if request.get("artifactId") and str(request["artifactId"]).lower() != str(artifact_id).lower():
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    with tx("edit") as (cur, auth):
        head = _assert_artifact_parent_context(cur, auth, workspace_id, artifact_id)
        if head["actor"] != str(auth.principal):
            raise AlphaError("Only the person who asked can change this view.", 403, code="ui_forbidden")
        _sweep(runtime, cur, workspace_id)
        key = request["idempotencyKey"]
        base = {"revision": request["baseRevision"], "sourceHash": request["baseSourceHash"], "instruction": request["instruction"], "selection": request.get("selection")}
        if _attempt_key_exists(cur, workspace_id, key):
            lease = _call(store.create_or_resume_artifact, cur, auth, head["runId"], head["slot"], key, surface=head["surface"], manifest=None, projection=None,
                          kind="edit", lease_owner=owner, base=base, base_revision=request["baseRevision"], base_source_hash=request["baseSourceHash"],
                          instruction=request["instruction"])
            return "replay", auth, lease["artifact"]["artifactId"], int(lease.get("replay_cursor") or 0)
        busy = _current_attempt(cur, workspace_id, head["artifactId"])
        if busy and busy["state"] in LIVE_STATES:
            raise AlphaError("This view is already changing. Wait for it to finish, then ask again.", 409, code="ui_busy")
        # Compare-and-swap BEFORE anything is reserved or sent: a stale tab never spends and never overwrites.
        if head["revision"] < 1 or request["baseRevision"] != head["revision"] or request["baseSourceHash"] != head["sourceHash"]:
            error = AlphaError("This view changed since the edit started. Nothing was overwritten or charged.", 409, code="ui_revision_conflict")
            error.current = {"revision": head["revision"], "sourceHash": head["sourceHash"]}
            raise error
        base_source = _revision_source(cur, workspace_id, head["artifactId"], head["revision"])
        if not base_source or contracts.sha256_text(base_source) != head["sourceHash"]:
            raise AlphaError("This view changed since the edit started. Nothing was overwritten or charged.", 409, code="ui_revision_conflict")
        manifest = _without_disabled_actions(ui_capabilities.current(cur, auth, head["manifest"]), _flags(runtime, workspace_id, getattr(auth, "scope", "workspace")))
        projection = {"journey_ids": head["journeyIds"], "component_group_ids": list((manifest or {}).get("componentGroups") or []), "allowed_context": {}}
        plan, refusal = _plan_or_refusal(lambda: ui_presenter.build_plan(runtime.cfg, _assets(runtime), projection, manifest, kind="edit", mode="patch",
                                                                         base_source=base_source, base_revision=head["revision"],
                                                                         instruction=request["instruction"], selection=request.get("selection")))
        lease = _call(store.create_or_resume_artifact, cur, auth, head["runId"], head["slot"], key, surface=head["surface"], manifest=manifest,
                      projection=projection, kind="edit", lease_owner=owner, base=base, base_revision=request["baseRevision"],
                      base_source_hash=request["baseSourceHash"], instruction=request["instruction"], library=_library_info(plan))
        if not lease.get("created"):
            return "replay", auth, lease["artifact"]["artifactId"], int(lease.get("replay_cursor") or 0)
        if plan is not None:
            plan = dataclasses.replace(plan, chain=ui_metering.chain_for("edit", lease["attempt"]["attemptId"]))
        events, terminal = _admit(runtime, cur, auth, lease, plan=plan, refusal=refusal, manifest=manifest)
    producer = _Producer(runtime, tx, auth, workspace_id, lease=lease, plan=plan, projection=projection, manifest=manifest, base_source=base_source,
                         instruction=request["instruction"], selection=request.get("selection"), deadline=_deadline(started), first_events=events,
                         terminal=terminal, owner=owner, route="edits", request_id=request_id, started=started)
    return "produce", producer


def _store_head(cur, auth, workspace_id, artifact_id) -> dict:
    """The artifact the caller may edit or cancel, in the caller's own scope (consumer or founder; never the other)."""
    head = _artifact_head(cur, workspace_id, artifact_id, scope=getattr(auth, "scope", "workspace") or "workspace", scope_key=getattr(auth, "scope_key", "") or "")
    return head


def create_edit(runtime, environ, start_response, workspace_id, token, artifact_id, request):
    """POST …/presentations/{a}/edits → an explicit, separately metered patch on (baseRevision, baseSourceHash)."""
    started = time.monotonic()
    admitted = _start_edit(runtime, _consumer_tx(runtime, token, workspace_id), workspace_id, artifact_id, request, started=started,
                           request_id=_request_id(environ))
    if admitted[0] == "replay":
        _, auth, replay_artifact, cursor = admitted
        return _replay_stream(runtime, environ, start_response, workspace_id, auth, replay_artifact, cursor, route="agent.ui.edits")
    producer = admitted[1]
    _sse_start(start_response)
    return _Closing(producer.frames(), producer.unstarted)


def run_edit(runtime, workspace_id, artifact_id, request, *, transaction, request_id=None) -> dict:
    """Blocking form of create_edit for a route family that cannot stream (founder, patch cap BOUNDS.founderPatchBytes)."""
    started = time.monotonic()
    admitted = _start_edit(runtime, transaction, workspace_id, artifact_id, request, started=started, request_id=request_id)
    if admitted[0] == "replay":
        return {"artifactId": admitted[2], "producing": False, "replayCursor": admitted[3]}
    return _drain_producer(admitted[1])


# --- replay -----------------------------------------------------------------------------------------------------------------
def _live(cur, workspace_id, artifact_id) -> bool:
    attempt = _current_attempt(cur, workspace_id, artifact_id)
    return bool(attempt and attempt["state"] in LIVE_STATES)


def _replay_frames(runtime, auth, workspace_id, artifact_id, events, live, request_id, started, route):
    store = _ui_store()
    frames = sent = 0
    last_seq = 0
    last_sent = time.monotonic()
    outcome = "replayed"

    def frame(event, first=False):
        nonlocal frames, sent, last_sent
        data = contracts.sse_frame(event, retry_ms=2000 if first else None)
        frames += 1
        sent += len(data)
        last_sent = time.monotonic()
        return data

    try:
        with _connection(runtime) as db:
            _assert_artifact_parent_context(db.cursor(), auth, workspace_id, artifact_id)
            db.commit()
        terminal = False
        for event in events:
            yield frame(event, first=frames == 0)
            last_seq = max(last_seq, int(event["seq"]))
            terminal = terminal or event["kind"] in contracts.TERMINAL_EVENT_KINDS
        if terminal or not live:
            outcome = "complete"
            return
        page_full = len(events) >= contracts.BOUNDS["replayPageEvents"]
        until = time.monotonic() + REPLAY_TAIL_SECONDS
        with _connection(runtime) as db:
            while time.monotonic() < until:
                if not page_full:
                    _sleep(REPLAY_POLL_SECONDS)
                cur = db.cursor()
                _assert_artifact_parent_context(cur, auth, workspace_id, artifact_id)
                fresh = store.events_after(cur, auth, artifact_id, last_seq, contracts.BOUNDS["replayPageEvents"])
                still_live = _live(cur, workspace_id, artifact_id)
                db.commit()
                page_full = len(fresh) >= contracts.BOUNDS["replayPageEvents"]
                for event in fresh:
                    yield frame(event, first=frames == 0)
                    last_seq = max(last_seq, int(event["seq"]))
                    if event["kind"] in contracts.TERMINAL_EVENT_KINDS:
                        outcome = "complete"
                        return
                if not fresh and not still_live:
                    outcome = "complete"
                    return
                if time.monotonic() - last_sent >= HEARTBEAT_SECONDS:
                    yield frame(contracts.make_event(artifact_id, None, 0, last_seq, "ui.heartbeat", {}), first=frames == 0)
        outcome = "tail_elapsed"   # the client reconnects with after=<last seq>
    except GeneratorExit:
        outcome = "client_gone"
        raise
    except Exception as error:  # noqa: BLE001 — a replay failure never touches the attempt; the client reconnects
        outcome = "internal_error"
        log.error(json.dumps({"event": "agent_ui.replay_failed", "errorClass": type(error).__name__, "requestId": request_id}))
    finally:
        _log_closed(route, outcome, started, frames, sent, 0, request_id)


def _replay_stream(runtime, environ, start_response, workspace_id, auth, artifact_id, after, *, route):
    """Replay of an attempt this request did not produce (duplicate key, another live producer): never dispatches."""
    started = time.monotonic()
    with _connection(runtime) as db:
        cur = db.cursor()
        _assert_artifact_parent_context(cur, auth, workspace_id, artifact_id)
        events = _ui_store().events_after(cur, auth, artifact_id, after, contracts.BOUNDS["replayPageEvents"])
        live = _live(cur, workspace_id, artifact_id)
        db.commit()
    _sse_start(start_response)
    return _Closing(_replay_frames(runtime, auth, workspace_id, artifact_id, events, live, _request_id(environ), started, route))


def replay(runtime, environ, start_response, workspace_id, token, artifact_id, after):
    """GET …/presentations/{a}/events?after= — authorized bounded replay + live tail; zero provider calls."""
    started = time.monotonic()
    with ui_http.ui_transaction(runtime, token, workspace_id, "read") as (cur, auth):
        _assert_artifact_parent_context(cur, auth, workspace_id, artifact_id)
        events = _ui_store().events_after(cur, auth, artifact_id, int(after or 0), contracts.BOUNDS["replayPageEvents"])
        live = _live(cur, workspace_id, artifact_id)
        if live:
            attempt = _current_attempt(cur, workspace_id, artifact_id)
            if attempt and attempt["leaseExpired"]:
                # The producer died: let F interrupt it (unknown usage stays held) so this client gets a terminal event.
                try:
                    with _savepoint(cur):
                        _ui_store().reap_expired(cur, workspace_id, None)
                    events = _ui_store().events_after(cur, auth, artifact_id, int(after or 0), contracts.BOUNDS["replayPageEvents"])
                    live = _live(cur, workspace_id, artifact_id)
                except Exception:  # noqa: BLE001
                    pass
    _sse_start(start_response)
    return _Closing(_replay_frames(runtime, auth, workspace_id, artifact_id, events, live, _request_id(environ), started, "agent.ui.events"))


# --- cancel -----------------------------------------------------------------------------------------------------------------
def cancel_presentation(runtime, workspace_id, artifact_id, *, transaction) -> dict:
    """Stop the presentation only. The live producer sees the canceled attempt at its next poll, settles what it knows (unknown
    keeps the hold) and forwards this ui.canceled event. The business answer, its proposals and receipts are not touched."""
    store = _ui_store()
    with transaction("edit") as (cur, auth):
        head = _store_head(cur, auth, workspace_id, artifact_id)
        if head["actor"] != str(auth.principal):
            raise AlphaError("Only the person who asked can stop this view.", 403, code="ui_forbidden")
        attempt = _current_attempt(cur, workspace_id, head["artifactId"])
        if attempt and attempt["state"] in LIVE_STATES and attempt["leaseExpired"]:
            try:
                with _savepoint(cur):
                    _call(store.reap_expired, cur, workspace_id, None, ledger=getattr(getattr(runtime, "service", None), "ledger", None))
            except Exception:  # noqa: BLE001
                pass
            attempt = _current_attempt(cur, workspace_id, head["artifactId"])
        if not attempt or attempt["state"] not in LIVE_STATES:
            return {"artifactId": head["artifactId"], "attemptId": attempt["attemptId"] if attempt else None, "state": attempt["state"] if attempt else None,
                    "canceled": False, "businessResult": "unchanged"}
        store.finish_attempt(cur, attempt["attemptId"], "canceled", "canceled_by_user")
        event = store.append_event(cur, head["artifactId"], attempt["attemptId"], head["revision"], "ui.canceled",
                                   {"reason": "canceled_by_user", "fallback": "native", "attempt": attempt["attemptId"]})
        return {"artifactId": head["artifactId"], "attemptId": attempt["attemptId"], "state": "canceled", "canceled": True, "seq": event.get("seq"),
                "businessResult": "unchanged"}


def cancel_http(runtime, workspace_id, token, artifact_id):
    """POST …/presentations/{a}/cancel (consumer route)."""
    return cancel_presentation(runtime, workspace_id, artifact_id, transaction=_consumer_tx(runtime, token, workspace_id))


# --- G04 probe --------------------------------------------------------------------------------------------------------------
def _probe_frames(request_id, started):
    artifact_id = str(uuid.uuid4())
    frames = sent = 0
    outcome = "complete"
    text = PROBE_TEXT
    split_char = text[0]                                   # '粵' (3 bytes) is split after its first byte

    def event(seq, kind, payload):
        return contracts.make_event(artifact_id, None, 0, seq, kind, {"probe": True, "n": seq, "serverMonotonicNs": time.monotonic_ns(),
                                                                      "serverWallMs": int(time.time() * 1000), **payload})
    try:
        first = contracts.sse_frame(event(1, "ui.started", {"gapSeconds": PROBE_GAP_SECONDS, "frames": 3}), retry_ms=2000)
        frames, sent = frames + 1, sent + len(first)
        yield first
        _sleep(PROBE_GAP_SECONDS)
        second = contracts.sse_frame(event(2, "ui.delta", {"append": text, "offset": 0}))
        cut = second.index(split_char.encode("utf-8")) + 1
        frames, sent = frames + 1, sent + len(second)
        yield second[:cut]                                 # this write ends inside a multi-byte character
        _sleep(PROBE_SPLIT_SECONDS)
        yield second[cut:]
        _sleep(PROBE_GAP_SECONDS)
        tail = " · stream ok"
        third = contracts.sse_frame(event(3, "ui.delta", {"append": tail, "offset": len(text.encode("utf-8"))}))
        frames, sent = frames + 1, sent + len(third)
        yield third
        _sleep(PROBE_GAP_SECONDS)
        done = contracts.sse_frame(event(4, "ui.ready", {"sourceHash": contracts.sha256_text(text + tail), "bytes": len((text + tail).encode("utf-8"))}))
        frames, sent = frames + 1, sent + len(done)
        yield done
    except GeneratorExit:
        outcome = "client_gone"
        raise
    finally:
        _log_closed("agent.ui.probe", outcome, started, frames, sent, 0, request_id)


def probe(runtime, environ, start_response, workspace_id, token):
    """GET …/agent/ui/diagnostics/stream (D-A9): authenticated read member, zero model cost, throttled per person."""
    started = time.monotonic()
    with ui_http.ui_transaction(runtime, token, workspace_id, "read") as (cur, auth):
        _throttle(cur, f"ui-probe:{auth.principal}", PROBE_LIMIT_PER_MINUTE, 60)
    _sse_start(start_response)
    return _Closing(_probe_frames(_request_id(environ), started))


__all__ = ["create_presentation", "replay", "cancel_http", "create_edit", "probe", "run_presentation", "run_edit", "cancel_presentation"]
