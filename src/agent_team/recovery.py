"""Fail-closed recovery control candidate; never launches or completes an agent task.

Kynlo owns mission identity and Token Pilot owns task/scope/continuity. This store
retains only mission recovery bindings, checkpoints, leases, and attempt receipts.
Native proof must be produced by an authenticated adapter on the *owning* host;
generic listing metadata, notLoaded, missing sessions, and expired leases are not
proof. No native adapter or cloud owner transport is implemented by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import PurePath
from typing import Iterator, Protocol
from uuid import UUID


class RecoveryBlocked(ValueError):
    """A recovery transition lacks the evidence or authority it requires."""


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value: str, name: str, limit: int = 2048) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise RecoveryBlocked(f"invalid_{name}")


def _hash(value: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RecoveryBlocked(f"invalid_{name}")


def _path(value: str) -> None:
    # The host adapter must resolve symlinks before registration. Do not guess a
    # canonical project from a basename or discover unrelated worktrees here.
    if not isinstance(value, str) or not PurePath(value).is_absolute() or os.path.normpath(value) != value:
        raise RecoveryBlocked("canonical_absolute_path_required")


@dataclass(frozen=True)
class NativeOwner:
    server_id: str
    socket_path: str
    pid: int
    process_start: str


@dataclass(frozen=True)
class Registration:
    mission_id: str
    canonical_project: str
    worktree: str
    native_session_id: str
    engine: str
    owner: NativeOwner
    token_pilot_task_id: str
    token_pilot_root_task_id: str
    token_pilot_phase_id: str | None
    authorization_ref: str
    authorization_sha256: str
    scope_version: str
    acceptance_criteria: tuple[str, ...]
    side_effect_ledger_refs: tuple[str, ...]
    descendant_refs: tuple[str, ...] = ()
    background_refs: tuple[str, ...] = ()
    ci_refs: tuple[str, ...] = ()
    max_repairs: int = 2
    max_alternates: int = 1
    cost_budget_microusd: int = 0
    max_attempt_cost_microusd: int = 0
    paid_authorization_ref: str | None = None

    def validate(self) -> None:
        for name in ("mission_id", "native_session_id", "token_pilot_task_id", "token_pilot_root_task_id",
                     "authorization_ref", "scope_version"):
            _text(getattr(self, name), name)
        _path(self.canonical_project)
        _path(self.worktree)
        _path(self.owner.socket_path)
        _text(self.owner.server_id, "server_id")
        _text(self.owner.process_start, "process_start")
        if type(self.owner.pid) is not int or self.owner.pid < 1:
            raise RecoveryBlocked("positive_native_pid_required")
        if self.engine not in {"codex", "claude-code"}:
            raise RecoveryBlocked("unsupported_engine")
        try:
            UUID(self.native_session_id)
        except (ValueError, AttributeError) as exc:
            raise RecoveryBlocked("explicit_native_session_uuid_required") from exc
        _hash(self.authorization_sha256, "authorization_sha256")
        if not self.acceptance_criteria:
            raise RecoveryBlocked("acceptance_criteria_required")
        if not self.side_effect_ledger_refs:
            raise RecoveryBlocked("side_effect_ledger_required")
        for name in ("acceptance_criteria", "side_effect_ledger_refs", "descendant_refs", "background_refs", "ci_refs"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise RecoveryBlocked(f"duplicate_{name}")
            for value in values:
                _text(value, name)
        for value, ceiling in ((self.max_repairs, 2), (self.max_alternates, 1)):
            if type(value) is not int or not 0 <= value <= ceiling:
                raise RecoveryBlocked("retry_bounds_exceed_authorization")
        for value in (self.cost_budget_microusd, self.max_attempt_cost_microusd):
            if type(value) is not int or value < 0:
                raise RecoveryBlocked("invalid_cost_bound")
        if self.max_attempt_cost_microusd > self.cost_budget_microusd:
            raise RecoveryBlocked("attempt_cost_exceeds_budget")
        if self.cost_budget_microusd and not self.paid_authorization_ref:
            raise RecoveryBlocked("paid_authorization_required")

    @property
    def fingerprint(self) -> str:
        self.validate()
        return _digest(asdict(self))

    @property
    def authority_fingerprint(self) -> str:
        """Original mission/task/scope/cost/effect contract, excluding execution identity."""
        self.validate()
        body = asdict(self)
        for name in ("native_session_id", "engine", "owner", "descendant_refs", "background_refs", "ci_refs"):
            body.pop(name)
        return _digest(body)


@dataclass(frozen=True)
class ExecutionBinding:
    """Append-only native execution lineage; the original registration stays immutable."""
    mission_id: str
    registration_sha256: str
    ordinal: int
    predecessor_sha256: str | None
    native_session_id: str
    engine: str
    owner: NativeOwner
    descendant_refs: tuple[str, ...]
    background_refs: tuple[str, ...]
    ci_refs: tuple[str, ...]
    checkpoint_sha256: str | None
    attempt_id: int | None
    continuity_revision: int
    evidence_ref: str
    created_at: float

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))

    def runtime_registration(self, registration: Registration) -> Registration:
        if (self.mission_id, self.registration_sha256) != (registration.mission_id, registration.fingerprint):
            raise RecoveryBlocked("execution_registration_mismatch")
        if type(self.ordinal) is not int or self.ordinal < 0 or type(self.continuity_revision) is not int or self.continuity_revision < 0:
            raise RecoveryBlocked("invalid_execution_lineage")
        if not math.isfinite(self.created_at) or not self.evidence_ref:
            raise RecoveryBlocked("execution_evidence_required")
        if self.ordinal > 0:
            _hash(self.predecessor_sha256, "execution_predecessor")
            _hash(self.checkpoint_sha256, "execution_checkpoint")
            if type(self.attempt_id) is not int or self.attempt_id < 1:
                raise RecoveryBlocked("execution_attempt_required")
        result = replace(registration, native_session_id=self.native_session_id, engine=self.engine, owner=self.owner,
                         descendant_refs=self.descendant_refs, background_refs=self.background_refs, ci_refs=self.ci_refs)
        result.validate()
        return result


@dataclass(frozen=True)
class WorkspaceSnapshot:
    worktree: str
    head: str
    dirty_sha256: str
    dirty_summary: str
    evidence_ref: str


@dataclass(frozen=True)
class JobProof:
    reference: str
    state: str
    evidence_ref: str
    identity_verified: bool


@dataclass(frozen=True)
class WriterProof:
    mission_id: str
    native_session_id: str
    owner: NativeOwner
    observed_at: float
    evidence_ref: str
    source: str
    identity_verified: bool
    native_state: str
    writer_quiescent: bool
    active_tool_count: int
    inventory_complete: bool
    descendants: tuple[JobProof, ...] = ()
    background: tuple[JobProof, ...] = ()
    ci: tuple[JobProof, ...] = ()


@dataclass(frozen=True)
class ContinuityEvidence:
    task_id: str
    root_task_id: str
    phase_id: str | None
    revision: int
    state: str
    authorization_ref: str
    authorization_sha256: str
    scope_version: str
    evidence_ref: str
    session_id: str | None = None


@dataclass(frozen=True)
class RecoveryEvidence:
    writer: WriterProof
    continuity: ContinuityEvidence
    checkpoint_workspace: WorkspaceSnapshot
    current_workspace: WorkspaceSnapshot
    waiting_for: str | None = None
    unknown_external_effects: tuple[str, ...] = ()
    scope_still_authorized: bool = False
    side_effects_reconciled: bool = False
    side_effect_reconciliation_ref: str | None = None


@dataclass(frozen=True)
class Gate:
    ready: bool
    reason: str


def validate_recovery(registration: Registration, evidence: RecoveryEvidence, *, now: float,
                      max_proof_age: float = 30.0, execution: ExecutionBinding | None = None) -> Gate:
    """Pure validation. Adapter evidence is explicit and no process is stopped."""
    try:
        registration.validate()
        if execution is not None:
            registration = execution.runtime_registration(registration)
    except RecoveryBlocked as exc:
        return Gate(False, str(exc))
    if evidence.waiting_for is not None:
        return Gate(False, "waiting_excluded")
    if evidence.unknown_external_effects:
        return Gate(False, "unknown_external_effect")
    if not evidence.side_effects_reconciled or not evidence.side_effect_reconciliation_ref:
        return Gate(False, "side_effect_reconciliation_required")
    c = evidence.continuity
    if (c.task_id, c.root_task_id, c.phase_id) != (registration.token_pilot_task_id,
                                               registration.token_pilot_root_task_id,
                                               registration.token_pilot_phase_id):
        return Gate(False, "continuity_identity_mismatch")
    if c.state != "ready":
        return Gate(False, f"token_pilot_{c.state}")
    if type(c.revision) is not int or c.revision < 0 or not c.evidence_ref:
        return Gate(False, "continuity_evidence_required")
    if execution is not None and (c.session_id != registration.native_session_id or c.revision < execution.continuity_revision):
        return Gate(False, "continuity_execution_binding_mismatch")
    if not evidence.scope_still_authorized or (c.authorization_ref, c.authorization_sha256, c.scope_version) != (
            registration.authorization_ref, registration.authorization_sha256, registration.scope_version):
        return Gate(False, "authorization_changed")
    for snapshot in (evidence.checkpoint_workspace, evidence.current_workspace):
        if snapshot.worktree != registration.worktree or not snapshot.evidence_ref or not snapshot.head:
            return Gate(False, "workspace_identity_mismatch")
        try:
            _hash(snapshot.dirty_sha256, "dirty_sha256")
        except RecoveryBlocked:
            return Gate(False, "dirty_preservation_evidence_required")
    if evidence.checkpoint_workspace.head != evidence.current_workspace.head:
        return Gate(False, "head_changed_needs_review")
    if evidence.checkpoint_workspace.dirty_sha256 != evidence.current_workspace.dirty_sha256:
        return Gate(False, "dirty_changed_needs_review")
    p = evidence.writer
    if (p.mission_id, p.native_session_id, p.owner) != (registration.mission_id,
                                                     registration.native_session_id, registration.owner):
        return Gate(False, "owning_native_identity_mismatch")
    if p.source != "same-owner-native" or p.identity_verified is not True or not p.evidence_ref:
        return Gate(False, "positive_same_owner_proof_required")
    if not 0 <= now - p.observed_at <= max_proof_age:
        return Gate(False, "writer_proof_stale")
    if p.native_state not in {"idle", "finished"} or p.writer_quiescent is not True:
        return Gate(False, "live_or_unknown_writer")
    if type(p.active_tool_count) is not int or p.active_tool_count != 0:
        return Gate(False, "active_or_unknown_tool")
    if p.inventory_complete is not True:
        return Gate(False, "writer_inventory_incomplete")
    for name in ("descendants", "background", "ci"):
        jobs = getattr(p, name)
        expected = getattr(registration, f"{name if name != 'descendants' else 'descendant'}_refs")
        refs = [job.reference for job in jobs]
        if len(refs) != len(set(refs)) or set(refs) != set(expected):
            return Gate(False, f"{name}_inventory_mismatch")
        if any(job.identity_verified is not True or not job.evidence_ref or job.state not in {"idle", "finished"}
               for job in jobs):
            return Gate(False, f"{name}_active_or_unknown")
    return Gate(True, "ready")


@dataclass(frozen=True)
class ActiveAttemptEvidence:
    """Fresh ownership heartbeat of an already dispatched attempt, never a retry gate.

    Owned changes may advance HEAD/dirty state. The observing adapter must prove
    that attribution; an arbitrary current snapshot cannot replace the checkpoint.
    Known waiting states retain exclusion without scheduling another attempt.
    """
    execution_binding_sha256: str
    checkpoint_sha256: str
    writer: WriterProof
    continuity: ContinuityEvidence
    workspace: WorkspaceSnapshot
    snapshot_observed_at: float
    workspace_changes_owned: bool
    workspace_review_ref: str
    scope_still_authorized: bool
    side_effects_reconciled: bool
    side_effect_reconciliation_ref: str | None
    unknown_external_effects: tuple[str, ...] = ()


def validate_active_attempt(registration: Registration, execution: ExecutionBinding,
                            evidence: ActiveAttemptEvidence, *, now: float,
                            max_proof_age: float = 30.0) -> Gate:
    try:
        runtime = execution.runtime_registration(registration)
        _hash(evidence.checkpoint_sha256, "checkpoint_sha256")
        _hash(evidence.workspace.dirty_sha256, "dirty_sha256")
    except RecoveryBlocked as exc:
        return Gate(False, str(exc))
    if evidence.execution_binding_sha256 != execution.fingerprint:
        return Gate(False, "active_execution_binding_mismatch")
    if not 0 <= now - evidence.snapshot_observed_at <= max_proof_age:
        return Gate(False, "active_snapshot_stale")
    if evidence.unknown_external_effects or not evidence.side_effects_reconciled or not evidence.side_effect_reconciliation_ref:
        return Gate(False, "unknown_or_unreconciled_external_effect")
    c = evidence.continuity
    if (c.task_id, c.root_task_id, c.phase_id, c.session_id) != (
            registration.token_pilot_task_id, registration.token_pilot_root_task_id,
            registration.token_pilot_phase_id, execution.native_session_id):
        return Gate(False, "active_continuity_identity_mismatch")
    if c.state != "ready" or not c.evidence_ref or type(c.revision) is not int or c.revision < execution.continuity_revision:
        return Gate(False, "active_continuity_not_verified")
    if not evidence.scope_still_authorized or (c.authorization_ref, c.authorization_sha256, c.scope_version) != (
            registration.authorization_ref, registration.authorization_sha256, registration.scope_version):
        return Gate(False, "authorization_changed")
    w = evidence.workspace
    if w.worktree != registration.worktree or not w.head or not w.evidence_ref or evidence.workspace_changes_owned is not True or not evidence.workspace_review_ref:
        return Gate(False, "active_workspace_not_verified")
    p = evidence.writer
    if (p.mission_id, p.native_session_id, p.owner) != (runtime.mission_id, runtime.native_session_id, runtime.owner):
        return Gate(False, "owning_native_identity_mismatch")
    if p.source != "same-owner-native" or p.identity_verified is not True or not p.evidence_ref:
        return Gate(False, "positive_same_owner_proof_required")
    if not 0 <= now - p.observed_at <= max_proof_age:
        return Gate(False, "writer_proof_stale")
    known = {"running", "active", "idle", "finished", "waiting_tool", "waiting_ci", "waiting_human", "waiting_approval"}
    if p.native_state not in known or type(p.active_tool_count) is not int or p.active_tool_count < 0 or p.inventory_complete is not True:
        return Gate(False, "active_writer_inventory_unknown")
    for name in ("descendants", "background", "ci"):
        jobs = getattr(p, name)
        expected = getattr(runtime, f"{name if name != 'descendants' else 'descendant'}_refs")
        refs = [job.reference for job in jobs]
        if len(refs) != len(set(refs)) or set(refs) != set(expected):
            return Gate(False, f"{name}_inventory_mismatch")
        if any(job.identity_verified is not True or not job.evidence_ref or job.state not in known for job in jobs):
            return Gate(False, f"{name}_active_identity_unknown")
    return Gate(True, "owned_active_attempt_heartbeat_only")


@dataclass(frozen=True)
class Checkpoint:
    mission_id: str
    registration_sha256: str
    native_session_id: str
    engine: str
    token_pilot_task_id: str
    token_pilot_root_task_id: str
    token_pilot_phase_id: str | None
    token_pilot_revision: int
    authorization_ref: str
    authorization_sha256: str
    scope_version: str
    workspace: WorkspaceSnapshot
    saved_at: float
    goal_ref: str
    verified_done: tuple[str, ...]
    incomplete: tuple[str, ...]
    blockers: tuple[str, ...]
    next_action: str
    acceptance_criteria: tuple[str, ...]
    side_effect_ledger_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    max_repairs: int
    max_alternates: int
    cost_budget_microusd: int
    execution_state: str = "checkpoint_candidate"
    execution_binding_sha256: str | None = None


def build_checkpoint(registration: Registration, continuity: ContinuityEvidence, workspace: WorkspaceSnapshot,
                     *, saved_at: float, goal_ref: str, verified_done: tuple[str, ...],
                     incomplete: tuple[str, ...], blockers: tuple[str, ...], next_action: str,
                     evidence_refs: tuple[str, ...], execution: ExecutionBinding | None = None) -> Checkpoint:
    registration.validate()
    _text(goal_ref, "goal_ref")
    _text(next_action, "next_action")
    if workspace.worktree != registration.worktree:
        raise RecoveryBlocked("workspace_identity_mismatch")
    _hash(workspace.dirty_sha256, "dirty_sha256")
    if (continuity.task_id, continuity.root_task_id, continuity.phase_id) != (
            registration.token_pilot_task_id, registration.token_pilot_root_task_id, registration.token_pilot_phase_id):
        raise RecoveryBlocked("continuity_identity_mismatch")
    if (continuity.authorization_ref, continuity.authorization_sha256, continuity.scope_version) != (
            registration.authorization_ref, registration.authorization_sha256, registration.scope_version):
        raise RecoveryBlocked("authorization_changed")
    if type(continuity.revision) is not int or continuity.revision < 0:
        raise RecoveryBlocked("invalid_continuity_revision")
    runtime = execution.runtime_registration(registration) if execution else registration
    return Checkpoint(registration.mission_id, registration.fingerprint, runtime.native_session_id,
                      runtime.engine, registration.token_pilot_task_id, registration.token_pilot_root_task_id,
                      registration.token_pilot_phase_id, continuity.revision, registration.authorization_ref,
                      registration.authorization_sha256, registration.scope_version, workspace, saved_at, goal_ref,
                      verified_done, incomplete, blockers, next_action, registration.acceptance_criteria,
                      registration.side_effect_ledger_refs, evidence_refs, registration.max_repairs,
                      registration.max_alternates, registration.cost_budget_microusd,
                      execution_binding_sha256=execution.fingerprint if execution else None)


@dataclass(frozen=True)
class Lease:
    mission_id: str
    worktree: str
    holder: str
    generation: int
    expires_at: float


@dataclass(frozen=True)
class Attempt:
    id: int
    mission_id: str
    incident_id: str
    mode: str
    generation: int


class RecoveryOwnerTransport(Protocol):
    """Port for one authenticated cloud owner; no implementation or connection.

    A remote implementation must preserve atomic worktree exclusion, increasing
    generations, server time, and scoped authentication. Local SQLite alone does
    not coordinate multiple Macs or prove exclusion of native writers.
    """

    def acquire(self, registration: Registration, holder: str, evidence: RecoveryEvidence,
                *, now: float, ttl_seconds: float = 30.0) -> Lease: ...

    def assert_fence(self, lease: Lease, *, now: float) -> None: ...

    def renew(self, lease: Lease, registration: Registration, evidence: RecoveryEvidence,
              *, now: float, ttl_seconds: float = 30.0) -> Lease: ...

    def renew_active_attempt(self, lease: Lease, registration: Registration, attempt: Attempt,
                             evidence: ActiveAttemptEvidence, *, now: float,
                             ttl_seconds: float = 30.0) -> Lease: ...

    def release(self, lease: Lease, *, now: float) -> None: ...


class RecoveryStore:
    """Single local control candidate; cloud ownership transport remains separate.

    Every mutation affecting an attempt requires a live matching fence. A fence
    covers participating callers only, so native proof is still mandatory.
    """

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=3)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS recovery_bindings(
              mission_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_generations(worktree TEXT PRIMARY KEY, generation INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_leases(
              worktree TEXT PRIMARY KEY, mission_id TEXT NOT NULL, holder TEXT NOT NULL,
              generation INTEGER NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_checkpoints(
              mission_id TEXT NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL,
              PRIMARY KEY(mission_id,digest));
            CREATE TABLE IF NOT EXISTS recovery_attempts(
              id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT NOT NULL, incident_id TEXT NOT NULL,
              mode TEXT NOT NULL, holder TEXT NOT NULL, generation INTEGER NOT NULL,
              failure_signature TEXT NOT NULL, outcome TEXT NOT NULL, reserved_cost INTEGER NOT NULL,
              measured_cost INTEGER, receipt_ref TEXT, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_execution_bindings(
              mission_id TEXT NOT NULL, ordinal INTEGER NOT NULL, digest TEXT NOT NULL,
              predecessor TEXT, body TEXT NOT NULL,
              PRIMARY KEY(mission_id,ordinal), UNIQUE(mission_id,digest));
            CREATE TABLE IF NOT EXISTS recovery_attempt_contexts(
              attempt_id INTEGER PRIMARY KEY REFERENCES recovery_attempts(id),
              checkpoint_digest TEXT NOT NULL, alternate_reason TEXT, alternate_evidence_ref TEXT);
            CREATE TABLE IF NOT EXISTS recovery_attempt_execution_links(
              attempt_id INTEGER NOT NULL REFERENCES recovery_attempts(id),
              execution_digest TEXT NOT NULL, evidence_ref TEXT NOT NULL,
              PRIMARY KEY(attempt_id,execution_digest));
            CREATE TABLE IF NOT EXISTS recovery_attempt_heartbeats(
              id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL REFERENCES recovery_attempts(id),
              generation INTEGER NOT NULL, observed_at REAL NOT NULL, proof_digest TEXT NOT NULL, evidence_ref TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def register(self, registration: Registration) -> str:
        fingerprint = registration.fingerprint
        with self._transaction():
            row = self.db.execute("SELECT fingerprint FROM recovery_bindings WHERE mission_id=?",
                                  (registration.mission_id,)).fetchone()
            if row and row["fingerprint"] != fingerprint:
                raise RecoveryBlocked("registered_contract_changed_needs_review")
            self.db.execute("INSERT OR IGNORE INTO recovery_bindings VALUES(?,?,?)",
                            (registration.mission_id, fingerprint, _json(asdict(registration))))
            origin = ExecutionBinding(registration.mission_id, fingerprint, 0, None,
                                      registration.native_session_id, registration.engine, registration.owner,
                                      registration.descendant_refs, registration.background_refs, registration.ci_refs,
                                      None, None, 0, registration.authorization_ref, 0.0)
            self.db.execute("INSERT OR IGNORE INTO recovery_execution_bindings VALUES(?,?,?,?,?)",
                            (registration.mission_id, 0, origin.fingerprint, None, _json(asdict(origin))))
        return fingerprint

    def _registered(self, registration: Registration) -> None:
        row = self.db.execute("SELECT fingerprint FROM recovery_bindings WHERE mission_id=?",
                              (registration.mission_id,)).fetchone()
        if not row or row["fingerprint"] != registration.fingerprint:
            raise RecoveryBlocked("exact_registered_mission_required")

    @staticmethod
    def _execution(body: str) -> ExecutionBinding:
        data = json.loads(body)
        data["owner"] = NativeOwner(**data["owner"])
        for name in ("descendant_refs", "background_refs", "ci_refs"):
            data[name] = tuple(data[name])
        return ExecutionBinding(**data)

    def current_execution(self, registration: Registration) -> ExecutionBinding:
        self._registered(registration)
        row = self.db.execute("SELECT digest,body FROM recovery_execution_bindings WHERE mission_id=? ORDER BY ordinal DESC LIMIT 1",
                              (registration.mission_id,)).fetchone()
        if not row:
            raise RecoveryBlocked("execution_binding_required")
        result = self._execution(row["body"])
        result.runtime_registration(registration)
        if result.fingerprint != row["digest"]:
            raise RecoveryBlocked("execution_binding_digest_mismatch")
        return result

    def execution_history(self, registration: Registration) -> tuple[ExecutionBinding, ...]:
        self._registered(registration)
        rows = self.db.execute("SELECT body FROM recovery_execution_bindings WHERE mission_id=? ORDER BY ordinal",
                               (registration.mission_id,)).fetchall()
        return tuple(self._execution(row["body"]) for row in rows)

    def _recovery_gate(self, registration: Registration, evidence: RecoveryEvidence, *, now: float) -> ExecutionBinding:
        execution = self.current_execution(registration)
        gate = validate_recovery(registration, evidence, now=now, execution=execution)
        if not gate.ready:
            raise RecoveryBlocked(gate.reason)
        return execution

    def _owned_attempt(self, lease: Lease, attempt: Attempt, *, now: float) -> sqlite3.Row:
        self.assert_fence(lease, now=now)
        row = self.db.execute("SELECT * FROM recovery_attempts WHERE id=?", (attempt.id,)).fetchone()
        if (attempt.mission_id, attempt.generation) != (lease.mission_id, lease.generation) or not row or (
                row["mission_id"], row["incident_id"], row["mode"], row["holder"], row["generation"]) != (
                lease.mission_id, attempt.incident_id, attempt.mode, lease.holder, lease.generation) or row["outcome"] != "started":
            raise RecoveryBlocked("attempt_not_owned_or_already_recorded")
        return row

    def save_checkpoint(self, registration: Registration, checkpoint: Checkpoint) -> str:
        self._registered(registration)
        if checkpoint.mission_id != registration.mission_id or checkpoint.registration_sha256 != registration.fingerprint:
            raise RecoveryBlocked("checkpoint_registration_mismatch")
        execution = self.current_execution(registration)
        if (checkpoint.native_session_id, checkpoint.engine) != (execution.native_session_id, execution.engine) or (
                checkpoint.execution_binding_sha256 != execution.fingerprint and not (
                execution.ordinal == 0 and checkpoint.execution_binding_sha256 is None)):
            raise RecoveryBlocked("checkpoint_execution_binding_mismatch")
        digest = _digest(asdict(checkpoint))
        self.db.execute("INSERT OR IGNORE INTO recovery_checkpoints VALUES(?,?,?)",
                        (registration.mission_id, digest, _json(asdict(checkpoint))))
        return digest

    def acquire(self, registration: Registration, holder: str, evidence: RecoveryEvidence,
                *, now: float, ttl_seconds: float = 30.0) -> Lease:
        _text(holder, "holder", 128)
        if not 0 < ttl_seconds <= 60:
            raise RecoveryBlocked("invalid_lease_ttl")
        with self._transaction():
            self._registered(registration)
            self._recovery_gate(registration, evidence, now=now)
            row = self.db.execute("SELECT * FROM recovery_leases WHERE worktree=?", (registration.worktree,)).fetchone()
            if row and row["expires_at"] > now:
                raise RecoveryBlocked("lease_conflict")
            row = self.db.execute("SELECT generation FROM recovery_generations WHERE worktree=?",
                                  (registration.worktree,)).fetchone()
            generation = (row["generation"] if row else 0) + 1
            self.db.execute("INSERT INTO recovery_generations VALUES(?,?) ON CONFLICT(worktree) DO UPDATE SET generation=excluded.generation",
                            (registration.worktree, generation))
            self.db.execute("INSERT INTO recovery_leases VALUES(?,?,?,?,?) ON CONFLICT(worktree) DO UPDATE SET mission_id=excluded.mission_id,holder=excluded.holder,generation=excluded.generation,expires_at=excluded.expires_at",
                            (registration.worktree, registration.mission_id, holder, generation, now + ttl_seconds))
        return Lease(registration.mission_id, registration.worktree, holder, generation, now + ttl_seconds)

    def assert_fence(self, lease: Lease, *, now: float) -> None:
        row = self.db.execute("SELECT * FROM recovery_leases WHERE worktree=?", (lease.worktree,)).fetchone()
        if not row or (row["mission_id"], row["holder"], row["generation"]) != (lease.mission_id, lease.holder, lease.generation) or row["expires_at"] <= now:
            raise RecoveryBlocked("lease_expired_or_fenced")

    def renew(self, lease: Lease, registration: Registration, evidence: RecoveryEvidence,
              *, now: float, ttl_seconds: float = 30.0) -> Lease:
        if not 0 < ttl_seconds <= 60:
            raise RecoveryBlocked("invalid_lease_ttl")
        with self._transaction():
            self._registered(registration)
            self._recovery_gate(registration, evidence, now=now)
            self.assert_fence(lease, now=now)
            if (lease.mission_id, lease.worktree) != (registration.mission_id, registration.worktree):
                raise RecoveryBlocked("lease_registration_mismatch")
            self.db.execute("UPDATE recovery_leases SET expires_at=? WHERE worktree=?",
                            (now + ttl_seconds, lease.worktree))
        return Lease(lease.mission_id, lease.worktree, lease.holder, lease.generation, now + ttl_seconds)

    def renew_active_attempt(self, lease: Lease, registration: Registration, attempt: Attempt,
                             evidence: ActiveAttemptEvidence, *, now: float,
                             ttl_seconds: float = 30.0) -> Lease:
        """Keep an already owned attempt fenced while it runs or waits.

        This never bypasses the idle-only retry gate, acquires an expired fence,
        records success, expands scope, or resumes a process.
        """
        if not 0 < ttl_seconds <= 60:
            raise RecoveryBlocked("invalid_lease_ttl")
        with self._transaction():
            self._registered(registration)
            self._owned_attempt(lease, attempt, now=now)
            if (lease.mission_id, lease.worktree) != (registration.mission_id, registration.worktree):
                raise RecoveryBlocked("lease_registration_mismatch")
            execution = self.current_execution(registration)
            gate = validate_active_attempt(registration, execution, evidence, now=now)
            if not gate.ready:
                raise RecoveryBlocked(gate.reason)
            context = self.db.execute("SELECT checkpoint_digest FROM recovery_attempt_contexts WHERE attempt_id=?",
                                      (attempt.id,)).fetchone()
            link = self.db.execute("SELECT 1 FROM recovery_attempt_execution_links WHERE attempt_id=? AND execution_digest=?",
                                   (attempt.id, execution.fingerprint)).fetchone()
            if not context or context["checkpoint_digest"] != evidence.checkpoint_sha256 or not link:
                raise RecoveryBlocked("active_attempt_context_mismatch")
            checkpoint = self.db.execute("SELECT body FROM recovery_checkpoints WHERE mission_id=? AND digest=?",
                                         (registration.mission_id, context["checkpoint_digest"])).fetchone()
            if not checkpoint or evidence.continuity.revision < json.loads(checkpoint["body"])["token_pilot_revision"]:
                raise RecoveryBlocked("active_continuity_revision_rollback")
            self.db.execute("UPDATE recovery_leases SET expires_at=? WHERE worktree=?", (now + ttl_seconds, lease.worktree))
            self.db.execute("INSERT INTO recovery_attempt_heartbeats(attempt_id,generation,observed_at,proof_digest,evidence_ref) VALUES(?,?,?,?,?)",
                            (attempt.id, lease.generation, now, _digest(asdict(evidence)), evidence.writer.evidence_ref))
        return Lease(lease.mission_id, lease.worktree, lease.holder, lease.generation, now + ttl_seconds)

    def append_execution(self, registration: Registration, lease: Lease, attempt: Attempt,
                         source_evidence: RecoveryEvidence, target: Registration,
                         target_evidence: RecoveryEvidence, *, evidence_ref: str, now: float) -> ExecutionBinding:
        """Transfer a reserved alternate to a proven target without replacing its task.

        The adapter must already have created/loaded the target without a model
        turn. Both endpoints must be positively quiescent. Token Pilot performs
        its own revision-safe bind; this only records that verified outcome.
        """
        _text(evidence_ref, "execution_evidence_ref")
        if target.authority_fingerprint != registration.authority_fingerprint:
            raise RecoveryBlocked("execution_authority_changed")
        with self._transaction():
            self._registered(registration)
            row = self._owned_attempt(lease, attempt, now=now)
            if (lease.mission_id, lease.worktree) != (registration.mission_id, registration.worktree):
                raise RecoveryBlocked("lease_registration_mismatch")
            if row["mode"] != "alternate":
                raise RecoveryBlocked("execution_handoff_requires_reserved_alternate")
            source = self._recovery_gate(registration, source_evidence, now=now)
            context = self.db.execute("SELECT * FROM recovery_attempt_contexts WHERE attempt_id=?", (attempt.id,)).fetchone()
            linked = self.db.execute("SELECT 1 FROM recovery_attempt_execution_links WHERE attempt_id=? AND execution_digest=?",
                                     (attempt.id, source.fingerprint)).fetchone()
            if not context or not linked or not context["alternate_evidence_ref"]:
                raise RecoveryBlocked("execution_handoff_context_required")
            if source.attempt_id == attempt.id:
                raise RecoveryBlocked("alternate_execution_already_bound")
            if target.engine != source.engine and context["alternate_reason"] != "engine_change_authorized":
                raise RecoveryBlocked("engine_change_not_authorized")
            if (target.native_session_id, target.engine, target.owner) == (source.native_session_id, source.engine, source.owner):
                raise RecoveryBlocked("execution_identity_unchanged")
            gate = validate_recovery(target, target_evidence, now=now)
            if not gate.ready:
                raise RecoveryBlocked(gate.reason)
            if source_evidence.continuity.session_id != source.native_session_id or target_evidence.continuity.session_id != target.native_session_id:
                raise RecoveryBlocked("execution_continuity_session_required")
            if target_evidence.continuity.revision <= source_evidence.continuity.revision:
                raise RecoveryBlocked("execution_continuity_revision_required")
            if tuple(getattr(source_evidence.current_workspace, name) for name in ("worktree", "head", "dirty_sha256")) != tuple(
                    getattr(target_evidence.current_workspace, name) for name in ("worktree", "head", "dirty_sha256")):
                raise RecoveryBlocked("execution_workspace_changed")
            checkpoint = self.db.execute("SELECT body FROM recovery_checkpoints WHERE mission_id=? AND digest=?",
                                         (registration.mission_id, context["checkpoint_digest"])).fetchone()
            if not checkpoint or json.loads(checkpoint["body"])["workspace"] != asdict(source_evidence.checkpoint_workspace):
                raise RecoveryBlocked("execution_checkpoint_mismatch")
            result = ExecutionBinding(registration.mission_id, registration.fingerprint, source.ordinal + 1,
                                      source.fingerprint, target.native_session_id, target.engine, target.owner,
                                      target.descendant_refs, target.background_refs, target.ci_refs,
                                      context["checkpoint_digest"], attempt.id, target_evidence.continuity.revision,
                                      evidence_ref, now)
            result.runtime_registration(registration)
            self.db.execute("INSERT INTO recovery_execution_bindings VALUES(?,?,?,?,?)",
                            (registration.mission_id, result.ordinal, result.fingerprint, source.fingerprint, _json(asdict(result))))
            self.db.execute("INSERT INTO recovery_attempt_execution_links VALUES(?,?,?)", (attempt.id, result.fingerprint, evidence_ref))
        return result

    def release(self, lease: Lease, *, now: float) -> None:
        with self._transaction():
            self.assert_fence(lease, now=now)
            self.db.execute("DELETE FROM recovery_leases WHERE worktree=?", (lease.worktree,))

    def start_attempt(self, registration: Registration, lease: Lease, evidence: RecoveryEvidence,
                      *, incident_id: str, mode: str, failure_signature: str,
                      checkpoint_sha256: str, reserved_cost_microusd: int = 0,
                      alternate_reason: str | None = None, alternate_evidence_ref: str | None = None,
                      now: float) -> Attempt:
        _text(incident_id, "incident_id", 128)
        _text(failure_signature, "failure_signature", 256)
        _hash(checkpoint_sha256, "checkpoint_sha256")
        if mode not in {"repair", "alternate"}:
            raise RecoveryBlocked("invalid_recovery_mode")
        if mode == "alternate" and (alternate_reason not in {"context_damaged", "session_expired", "engine_change_authorized"}
                                    or not alternate_evidence_ref):
            raise RecoveryBlocked("alternate_requires_specific_reason_and_evidence")
        if type(reserved_cost_microusd) is not int or reserved_cost_microusd < 0 or reserved_cost_microusd > registration.max_attempt_cost_microusd:
            raise RecoveryBlocked("attempt_cost_not_authorized")
        with self._transaction():
            self._registered(registration)
            execution = self._recovery_gate(registration, evidence, now=now)
            self.assert_fence(lease, now=now)
            if (lease.mission_id, lease.worktree) != (registration.mission_id, registration.worktree):
                raise RecoveryBlocked("lease_registration_mismatch")
            checkpoint = self.db.execute("SELECT body FROM recovery_checkpoints WHERE mission_id=? AND digest=?",
                                         (registration.mission_id, checkpoint_sha256)).fetchone()
            if not checkpoint:
                raise RecoveryBlocked("durable_checkpoint_required")
            checkpoint_body = json.loads(checkpoint["body"])
            if (checkpoint_body["native_session_id"], checkpoint_body["engine"]) != (execution.native_session_id, execution.engine) or (
                    checkpoint_body.get("execution_binding_sha256") != execution.fingerprint and not (
                    execution.ordinal == 0 and checkpoint_body.get("execution_binding_sha256") is None)):
                raise RecoveryBlocked("checkpoint_execution_binding_mismatch")
            if checkpoint_body["workspace"] != asdict(evidence.checkpoint_workspace):
                raise RecoveryBlocked("checkpoint_workspace_mismatch")
            if checkpoint_body["token_pilot_revision"] != evidence.continuity.revision:
                raise RecoveryBlocked("continuity_revision_changed")
            # A new mission binding must not evade an unresolved previous writer
            # on this worktree. This reads only this recovery sidecar's bindings.
            outstanding = self.db.execute(
                "SELECT a.outcome,a.measured_cost,b.body FROM recovery_attempts a "
                "JOIN recovery_bindings b ON a.mission_id=b.mission_id "
                "WHERE a.outcome IN ('started','outcome_unknown') OR a.measured_cost IS NULL"
            ).fetchall()
            if any(json.loads(row["body"])["worktree"] == registration.worktree for row in outstanding):
                raise RecoveryBlocked("prior_attempt_requires_reconciliation")
            attempts = self.db.execute("SELECT * FROM recovery_attempts WHERE mission_id=?", (registration.mission_id,)).fetchall()
            if any(a["outcome"] in {"started", "outcome_unknown"} or a["measured_cost"] is None and a["outcome"] != "started" for a in attempts):
                raise RecoveryBlocked("prior_attempt_requires_reconciliation")
            incident = [a for a in attempts if a["incident_id"] == incident_id]
            if any(a["outcome"] == "failed" and a["failure_signature"] == failure_signature for a in attempts):
                raise RecoveryBlocked("repeated_failure_signature")
            ceiling = registration.max_repairs if mode == "repair" else registration.max_alternates
            if sum(a["mode"] == mode for a in incident) >= ceiling:
                raise RecoveryBlocked("retry_cap_reached")
            spent = sum(a["measured_cost"] or 0 for a in attempts)
            if spent + reserved_cost_microusd > registration.cost_budget_microusd:
                raise RecoveryBlocked("mission_cost_budget_exhausted")
            cursor = self.db.execute("INSERT INTO recovery_attempts(mission_id,incident_id,mode,holder,generation,failure_signature,outcome,reserved_cost,created_at) VALUES(?,?,?,?,?,?,'started',?,?)",
                                     (registration.mission_id, incident_id, mode, lease.holder, lease.generation,
                                      failure_signature, reserved_cost_microusd, now))
            self.db.execute("INSERT INTO recovery_attempt_contexts VALUES(?,?,?,?)",
                            (cursor.lastrowid, checkpoint_sha256, alternate_reason, alternate_evidence_ref))
            self.db.execute("INSERT INTO recovery_attempt_execution_links VALUES(?,?,?)",
                            (cursor.lastrowid, execution.fingerprint, evidence.writer.evidence_ref))
            return Attempt(cursor.lastrowid, registration.mission_id, incident_id, mode, lease.generation)

    def record_attempt(self, lease: Lease, attempt: Attempt, *, outcome: str, failure_signature: str,
                       measured_cost_microusd: int | None, receipt_ref: str, now: float) -> None:
        if outcome not in {"succeeded", "failed", "outcome_unknown"}:
            raise RecoveryBlocked("invalid_attempt_outcome")
        _text(receipt_ref, "receipt_ref")
        _text(failure_signature, "failure_signature", 256)
        if measured_cost_microusd is not None and (type(measured_cost_microusd) is not int or measured_cost_microusd < 0):
            raise RecoveryBlocked("invalid_measured_cost")
        with self._transaction():
            self._owned_attempt(lease, attempt, now=now)
            # An overrun is retained honestly and blocks additional budget; it is
            # never hidden by rejecting the cost receipt after an effect.
            self.db.execute("UPDATE recovery_attempts SET outcome=?,failure_signature=?,measured_cost=?,receipt_ref=? WHERE id=?",
                            (outcome, failure_signature, measured_cost_microusd, receipt_ref, attempt.id))


@dataclass(frozen=True)
class AcceptanceEvidence:
    mission_id: str
    authorization_sha256: str
    scope_version: str
    criterion_id: str
    accepted: bool
    validator: str
    evidence_ref: str


def verify_acceptance(registration: Registration, evidence: tuple[AcceptanceEvidence, ...]) -> Gate:
    """Return a verification gate only; Kynlo completion is a separate action."""
    try:
        registration.validate()
    except RecoveryBlocked as exc:
        return Gate(False, str(exc))
    ids = [item.criterion_id for item in evidence]
    if len(ids) != len(set(ids)) or set(ids) != set(registration.acceptance_criteria):
        return Gate(False, "acceptance_coverage_incomplete")
    for item in evidence:
        if (item.mission_id, item.authorization_sha256, item.scope_version) != (
                registration.mission_id, registration.authorization_sha256, registration.scope_version):
            return Gate(False, "acceptance_scope_mismatch")
        if item.accepted is not True or item.validator != "acceptance-gem" or not item.evidence_ref:
            return Gate(False, "acceptance_not_verified")
    return Gate(True, "acceptance_verified_kynlo_completion_pending")


@dataclass(frozen=True)
class NativeCommandPreview:
    argv: tuple[str, ...]
    cwd: str
    execution_state: str = "preview_only"
    execute_allowed: bool = False
    limitation: str = "Requires owning-native transport, fresh proof, checkpoint, live fence, and authorized attempt."


def native_command_preview(registration: Registration, *, mode: str = "resume") -> NativeCommandPreview:
    """Verified installed CLI shapes; a preview never launches or claims delivery.

    CLI resume/fork alone cannot prove it addresses the original owning daemon.
    Do not execute these previews until an owning-endpoint adapter is validated.
    """
    registration.validate()
    try:
        UUID(registration.native_session_id)
    except (ValueError, AttributeError) as exc:
        raise RecoveryBlocked("explicit_native_session_uuid_required") from exc
    if mode not in {"resume", "fork"}:
        raise RecoveryBlocked("unsupported_native_command")
    if registration.engine == "codex":
        argv = ("codex", mode, registration.native_session_id, "--cd", registration.worktree)
    else:
        argv = ("claude", "--resume", registration.native_session_id)
        if mode == "fork":
            argv += ("--fork-session",)
    return NativeCommandPreview(argv, registration.worktree)
