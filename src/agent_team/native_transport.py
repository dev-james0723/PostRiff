"""One-shot Codex owner transport; no owner creation, model call on import, or retry.

Wire shapes were checked against installed Codex 0.160.0 generate-json-schema
and https://learn.chatgpt.com/docs/app-server. Only `app-server proxy --sock`
is launched by explicit connect(): that child is a pipe to an existing owner.

Root supplies trusted PID/start/socket observations, native writer exclusion,
Token Pilot continuity binding and the approved model/tool budget boundary.
JSON-RPC has no turn/start fencing CAS and cannot interpose every native tool;
without a real native guard attestation start_turn fails closed. Receipts/outbox
contain hashes and IDs only, never prompt, tool arguments, outputs or RPC errors.
The outbox is an attempt delivery ledger, not a mission/task registry.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import sqlite3
import stat
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import PurePath
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from .recovery import (ActiveAttemptEvidence, Attempt, Checkpoint, ExecutionBinding,
                       Lease, NativeOwner, RecoveryBlocked, RecoveryEvidence,
                       RecoveryStore, Registration, WorkspaceSnapshot,
                       _digest as recovery_digest, validate_active_attempt, validate_recovery)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _hash(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RecoveryBlocked("transport_hash_required")


def _uuid(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise RecoveryBlocked("transport_native_uuid_required") from None


@dataclass(frozen=True)
class NativeOwnerSnapshot:
    """Attested by root's actual owner observer, never synthesized from RPC status."""
    execution_sha256: str
    observed_at: float
    evidence: RecoveryEvidence
    socket_device: int
    socket_inode: int
    socket_uid: int
    thread_id: str
    session_root_id: str
    configuration_sha256: str
    exclusion_ref: str
    exclusion_verified: bool
    active_evidence: ActiveAttemptEvidence | None = None
    active_turn_id: str | None = None


@dataclass(frozen=True)
class NativeContext:
    registration: Registration
    execution: ExecutionBinding
    lease: Lease
    attempt: Attempt
    checkpoint_sha256: str
    initial_snapshot: NativeOwnerSnapshot


@dataclass(frozen=True)
class Reservation:
    checkpoint: Checkpoint = field(repr=False)
    cost_microusd: int
    evidence_ref: str


@dataclass(frozen=True)
class NativeThread:
    thread_id: str
    session_root_id: str
    configuration_sha256: str
    model: str
    model_provider: str
    configuration: dict[str, Any] = field(repr=False, compare=False)


@dataclass(frozen=True)
class NativeReceipt:
    request_id: str
    mission_id: str
    attempt_id: int
    generation: int
    execution_sha256: str
    method: str
    request_sha256: str
    outcome: str
    reason: str
    observed_at: float
    thread_id: str | None = None
    session_root_id: str | None = None
    turn_id: str | None = None
    binding_sha256: str | None = None
    retry_allowed: bool = False
    mission_complete: bool = False


@dataclass(frozen=True)
class ModelPermit:
    authority_sha256: str
    execution_sha256: str
    attempt_id: int
    generation: int
    request_sha256: str
    configuration_sha256: str
    reserved_cost_microusd: int
    expires_at: float
    approval_ref: str
    budget_ref: str
    native_guard_ref: str
    native_guard_verified: bool
    model_calls_authorized: bool


class ControlPort(Protocol):
    def assert_reserved(self, context: NativeContext, *, now: float) -> Reservation: ...
    def append_binding(self, context: NativeContext, source: NativeOwnerSnapshot,
                       target: Registration, target_snapshot: NativeOwnerSnapshot,
                       *, receipt_ref: str, now: float) -> ExecutionBinding: ...


class ProxyPort(Protocol):
    def connect(self, owner: NativeOwner, snapshot: NativeOwnerSnapshot) -> None: ...
    def rpc(self, method: str, params: dict[str, Any], *, request_id: str,
            before_send: Callable[[], None]) -> dict[str, Any]: ...
    def close(self) -> None: ...


class SQLiteRecoveryControl:
    """Adapter over the existing recovery authority; creates no task registry."""
    def __init__(self, store: RecoveryStore):
        self.store = store

    def assert_reserved(self, context: NativeContext, *, now: float) -> Reservation:
        r, b, lease, attempt = context.registration, context.execution, context.lease, context.attempt
        r.validate()
        b.runtime_registration(r)
        if (lease.mission_id, lease.worktree, attempt.mission_id, attempt.generation) != (
                r.mission_id, r.worktree, r.mission_id, lease.generation):
            raise RecoveryBlocked("transport_context_mismatch")
        self.store.assert_fence(lease, now=now)
        if self.store.current_execution(r).fingerprint != b.fingerprint:
            raise RecoveryBlocked("transport_execution_superseded")
        row = self.store.db.execute("SELECT * FROM recovery_attempts WHERE id=?", (attempt.id,)).fetchone()
        if not row or (row["mission_id"], row["incident_id"], row["mode"], row["holder"], row["generation"], row["outcome"]) != (
                r.mission_id, attempt.incident_id, attempt.mode, lease.holder, lease.generation, "started"):
            raise RecoveryBlocked("transport_exact_reserved_attempt_required")
        linked = self.store.db.execute("SELECT 1 FROM recovery_attempt_execution_links WHERE attempt_id=? AND execution_digest=?",
                                      (attempt.id, b.fingerprint)).fetchone()
        cp = self.store.db.execute("SELECT c.body,c.digest FROM recovery_checkpoints c JOIN recovery_attempt_contexts a "
                                  "ON c.digest=a.checkpoint_digest WHERE a.attempt_id=? AND c.mission_id=?",
                                  (attempt.id, r.mission_id)).fetchone()
        if not linked or not cp or cp["digest"] != context.checkpoint_sha256:
            raise RecoveryBlocked("transport_durable_checkpoint_required")
        data = json.loads(cp["body"])
        if recovery_digest(data) != cp["digest"]:
            raise RecoveryBlocked("transport_checkpoint_digest_mismatch")
        data["workspace"] = WorkspaceSnapshot(**data["workspace"])
        for name in ("verified_done", "incomplete", "blockers", "acceptance_criteria", "side_effect_ledger_refs", "evidence_refs"):
            data[name] = tuple(data[name])
        checkpoint = Checkpoint(**data)
        if (checkpoint.mission_id, checkpoint.registration_sha256, checkpoint.authorization_ref,
                checkpoint.authorization_sha256, checkpoint.scope_version, checkpoint.token_pilot_task_id,
                checkpoint.token_pilot_root_task_id, checkpoint.token_pilot_phase_id,
                checkpoint.acceptance_criteria, checkpoint.side_effect_ledger_refs,
                checkpoint.cost_budget_microusd, checkpoint.max_repairs, checkpoint.max_alternates) != (
                r.mission_id, r.fingerprint, r.authorization_ref, r.authorization_sha256, r.scope_version,
                r.token_pilot_task_id, r.token_pilot_root_task_id, r.token_pilot_phase_id,
                r.acceptance_criteria, r.side_effect_ledger_refs, r.cost_budget_microusd, r.max_repairs, r.max_alternates):
            raise RecoveryBlocked("transport_checkpoint_authority_mismatch")
        source_checkpoint = (checkpoint.native_session_id, checkpoint.engine) == (b.native_session_id, b.engine)
        if source_checkpoint and checkpoint.execution_binding_sha256 != b.fingerprint and not (
                b.ordinal == 0 and checkpoint.execution_binding_sha256 is None):
            raise RecoveryBlocked("transport_checkpoint_execution_mismatch")
        if not source_checkpoint and (b.attempt_id, b.checkpoint_sha256) != (attempt.id, context.checkpoint_sha256):
            raise RecoveryBlocked("transport_checkpoint_lineage_mismatch")
        cost = row["reserved_cost"]
        if type(cost) is not int or not 0 <= cost <= r.max_attempt_cost_microusd:
            raise RecoveryBlocked("transport_reserved_cost_invalid")
        return Reservation(checkpoint, cost, "recovery/attempt/" + str(attempt.id))

    def append_binding(self, context: NativeContext, source: NativeOwnerSnapshot,
                       target: Registration, target_snapshot: NativeOwnerSnapshot,
                       *, receipt_ref: str, now: float) -> ExecutionBinding:
        return self.store.append_execution(context.registration, context.lease, context.attempt,
                                           source.evidence, target, target_snapshot.evidence,
                                           evidence_ref=receipt_ref, now=now)


class DeliveryLedger:
    """Durable one-shot send intent. Crash/timeout/lease-loss cannot cause resends."""
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=3)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS native_delivery(
          request_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, worktree TEXT NOT NULL,
          attempt_id INTEGER NOT NULL, operation TEXT NOT NULL, method TEXT NOT NULL,
          generation INTEGER NOT NULL, execution_sha256 TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL,
          request_sha256 TEXT NOT NULL, outcome TEXT NOT NULL, receipt TEXT,
          UNIQUE(mission_id,attempt_id,operation))""")

    def close(self) -> None:
        self.db.close()

    def reserve(self, context: NativeContext, operation: str, method: str, request_sha256: str) -> str:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM native_delivery WHERE worktree=? AND outcome IN ('sending','outcome_unknown')",
                               (context.registration.worktree,)).fetchone():
                raise RecoveryBlocked("native_unknown_delivery_requires_reconciliation")
            request_id = str(uuid4())
            try:
                self.db.execute("INSERT INTO native_delivery VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)",
                                (request_id, context.registration.mission_id, context.registration.worktree,
                                 context.attempt.id, operation, method, context.lease.generation,
                                 context.execution.fingerprint, context.checkpoint_sha256, request_sha256, "sending"))
            except sqlite3.IntegrityError:
                raise RecoveryBlocked("native_operation_already_reserved_no_resend") from None
            self.db.execute("COMMIT")
            return request_id
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, receipt: NativeReceipt) -> None:
        self.db.execute("UPDATE native_delivery SET outcome=?,receipt=? WHERE request_id=? AND outcome='sending'",
                        (receipt.outcome, json.dumps(asdict(receipt), sort_keys=True, allow_nan=False), receipt.request_id))


class RpcUncertain(Exception):
    """Fixed local diagnostic only; never wrap or expose native response bodies."""


def verify_socket(owner: NativeOwner, snapshot: NativeOwnerSnapshot) -> None:
    info = os.lstat(owner.socket_path)
    if not stat.S_ISSOCK(info.st_mode) or (info.st_dev, info.st_ino, info.st_uid) != (
            snapshot.socket_device, snapshot.socket_inode, snapshot.socket_uid) or info.st_uid != os.getuid():
        raise RecoveryBlocked("native_socket_identity_changed")
    if info.st_mode & 0o022:
        raise RecoveryBlocked("native_socket_writable_by_other_owner")


class CodexUnixProxy:
    """Explicit existing-owner connection. Never starts/restarts an app-server."""
    def __init__(self, codex_binary: str, *, timeout: float = 10.0):
        if not PurePath(codex_binary).is_absolute() or os.path.normpath(codex_binary) != codex_binary:
            raise RecoveryBlocked("exact_installed_codex_binary_required")
        if not 0 < timeout <= 30:
            raise RecoveryBlocked("native_rpc_timeout_invalid")
        self.binary, self.timeout = codex_binary, timeout
        self.process: subprocess.Popen | None = None
        self.buffer = b""
        self.lock = threading.Lock()

    def connect(self, owner: NativeOwner, snapshot: NativeOwnerSnapshot) -> None:
        if self.process is not None:
            raise RecoveryBlocked("native_proxy_already_connected")
        verify_socket(owner, snapshot)
        self.process = subprocess.Popen([self.binary, "app-server", "proxy", "--sock", owner.socket_path],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        try:
            for stream in (self.process.stdin, self.process.stdout):
                os.set_blocking(stream.fileno(), False)
            self.rpc("initialize", {"clientInfo": {"name": "james_agent_team_owner", "version": "1"}},
                     request_id="initialize-" + str(uuid4()), before_send=lambda: verify_socket(owner, snapshot))
            self._write({"method": "initialized"}, lambda: verify_socket(owner, snapshot))
        except BaseException:
            self.close()
            raise RpcUncertain("native_proxy_handshake_unavailable") from None

    def _write(self, payload: dict[str, Any], before_send: Callable[[], None]) -> None:
        raw = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()
        if len(raw) > 256 * 1024 or self.process is None or self.process.poll() is not None:
            raise RpcUncertain("native_proxy_unavailable")
        deadline = time.monotonic() + self.timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin, selectors.EVENT_WRITE)
            offset = 0
            while offset < len(raw):
                if not selector.select(max(0, deadline - time.monotonic())) or time.monotonic() > deadline:
                    raise RpcUncertain("native_write_timeout")
                before_send()  # Revalidated immediately before every write, including partial writes.
                try:
                    wrote = os.write(self.process.stdin.fileno(), raw[offset:])
                except BlockingIOError:
                    continue
                except OSError:
                    raise RpcUncertain("native_send_uncertain") from None
                if wrote < 1:
                    raise RpcUncertain("native_send_uncertain")
                offset += wrote

    def rpc(self, method: str, params: dict[str, Any], *, request_id: str,
            before_send: Callable[[], None]) -> dict[str, Any]:
        with self.lock:
            self._write({"id": request_id, "method": method, "params": params}, before_send)
            deadline = time.monotonic() + self.timeout
            count = 0
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                while True:
                    if b"\n" not in self.buffer:
                        if not selector.select(max(0, deadline - time.monotonic())) or time.monotonic() > deadline:
                            raise RpcUncertain("native_response_timeout")
                        part = os.read(self.process.stdout.fileno(), 65536)
                        if not part:
                            raise RpcUncertain("native_response_eof")
                        self.buffer += part
                        if len(self.buffer) > 2 * 1024 * 1024:
                            raise RpcUncertain("native_response_limit")
                        continue
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    count += 1
                    if count > 10000:
                        raise RpcUncertain("native_notification_limit")
                    try:
                        reply = json.loads(line)
                    except (UnicodeDecodeError, ValueError):
                        raise RpcUncertain("native_response_invalid") from None
                    if not isinstance(reply, dict):
                        raise RpcUncertain("native_response_invalid")
                    if "method" in reply:
                        if "id" in reply:
                            # Approval/tool requests need root's owned handler. No auto-approval.
                            raise RpcUncertain("native_server_request_requires_owned_handler")
                        continue  # Never retain notification text, tool args, or deltas.
                    if reply.get("id") != request_id:
                        raise RpcUncertain("native_response_id_mismatch")
                    if "error" in reply or not isinstance(reply.get("result"), dict):
                        raise RpcUncertain("native_rpc_result_unproven")
                    return reply["result"]

    def close(self) -> None:
        process, self.process = self.process, None
        self.buffer = b""
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.terminate()  # Only our proxy child; never the native owner's PID.
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass


class NativeOwnerTransport:
    def __init__(self, control: ControlPort, ledger: DeliveryLedger, proxy: ProxyPort,
                 observer: Callable[[NativeContext], NativeOwnerSnapshot], *, clock: Callable[[], float] = time.time,
                 socket_check: Callable[[NativeOwner, NativeOwnerSnapshot], None] = verify_socket,
                 max_snapshot_age: float = 5.0):
        if not 0 < max_snapshot_age <= 30:
            raise RecoveryBlocked("native_snapshot_age_invalid")
        self.control, self.ledger, self.proxy, self.observer = control, ledger, proxy, observer
        self.clock, self.socket_check, self.max_age = clock, socket_check, max_snapshot_age
        self.connected_owner: NativeOwner | None = None

    def _validate_snapshot(self, context: NativeContext, snapshot: NativeOwnerSnapshot, *, active: bool = False) -> Reservation:
        now = self.clock()
        reservation = self.control.assert_reserved(context, now=now)
        r, b = context.registration, context.execution
        if b.engine != "codex":
            raise RecoveryBlocked("native_transport_codex_only")
        if snapshot.execution_sha256 != b.fingerprint or snapshot.thread_id != b.native_session_id:
            raise RecoveryBlocked("native_snapshot_execution_mismatch")
        _uuid(snapshot.thread_id)
        _uuid(snapshot.session_root_id)
        _hash(snapshot.configuration_sha256)
        if not math.isfinite(snapshot.observed_at) or not 0 <= now - snapshot.observed_at <= self.max_age:
            raise RecoveryBlocked("native_snapshot_expired")
        if snapshot.exclusion_verified is not True or not snapshot.exclusion_ref:
            raise RecoveryBlocked("native_writer_exclusion_unproven")
        if any(type(value) is not int or value < 0 for value in (snapshot.socket_device, snapshot.socket_inode, snapshot.socket_uid)):
            raise RecoveryBlocked("native_socket_attestation_required")
        if active:
            if snapshot.active_evidence is None or not snapshot.active_turn_id:
                raise RecoveryBlocked("native_active_turn_proof_required")
            _uuid(snapshot.active_turn_id)
            if snapshot.active_evidence.checkpoint_sha256 != context.checkpoint_sha256:
                raise RecoveryBlocked("native_active_checkpoint_mismatch")
            gate = validate_active_attempt(r, b, snapshot.active_evidence, now=now, max_proof_age=self.max_age)
            writer = snapshot.active_evidence.writer
        else:
            gate = validate_recovery(r, snapshot.evidence, now=now, max_proof_age=self.max_age, execution=b)
            writer = snapshot.evidence.writer
            if asdict(reservation.checkpoint.workspace) != asdict(snapshot.evidence.checkpoint_workspace):
                raise RecoveryBlocked("native_checkpoint_workspace_changed")
            if b.attempt_id != context.attempt.id and snapshot.evidence.continuity.revision != reservation.checkpoint.token_pilot_revision:
                raise RecoveryBlocked("native_checkpoint_continuity_changed")
        if not gate.ready:
            raise RecoveryBlocked(gate.reason)
        if writer.owner != b.owner:
            raise RecoveryBlocked("native_positive_owner_mismatch")
        self.socket_check(b.owner, snapshot)
        return reservation

    def _fresh(self, context: NativeContext, *, active: bool = False) -> NativeOwnerSnapshot:
        snapshot = self.observer(context)
        self._validate_snapshot(context, snapshot, active=active)
        initial = context.initial_snapshot
        if (snapshot.socket_device, snapshot.socket_inode, snapshot.socket_uid, snapshot.session_root_id,
                snapshot.configuration_sha256, snapshot.exclusion_ref) != (
                initial.socket_device, initial.socket_inode, initial.socket_uid,
                initial.session_root_id, initial.configuration_sha256, initial.exclusion_ref):
            raise RecoveryBlocked("native_owner_identity_or_configuration_changed")
        return snapshot

    def _connect(self, context: NativeContext) -> None:
        self._validate_snapshot(context, context.initial_snapshot)
        fresh = self._fresh(context)
        if self.connected_owner is None:
            self.proxy.connect(context.execution.owner, fresh)
            self.connected_owner = context.execution.owner
        elif self.connected_owner != context.execution.owner:
            raise RecoveryBlocked("native_proxy_owner_changed")

    def _mutate(self, context: NativeContext, operation: str, method: str, params: dict[str, Any],
                parse: Callable[[dict[str, Any]], dict[str, str]],
                authorize: Callable[[NativeOwnerSnapshot, str], Callable[[], None]] | None = None) -> NativeReceipt:
        self._connect(context)
        payload_hash = digest(params)
        request_id = self.ledger.reserve(context, operation, method, payload_hash)
        write_entered = False

        def guard() -> None:
            nonlocal write_entered
            snapshot = self._fresh(context)
            if authorize:
                recheck_permit = authorize(snapshot, payload_hash)
                self._fresh(context)  # An authority callback may have taken time or lost its lease.
                recheck_permit()
            # Conservatively marks a call handed to the proxy, even if OS write fails.
            write_entered = True

        values: dict[str, str] = {}
        try:
            result = self.proxy.rpc(method, params, request_id=request_id, before_send=guard)
            if not write_entered:
                raise RpcUncertain("native_proxy_guard_contract_broken")
            values = parse(result)
            self.control.assert_reserved(context, now=self.clock())
            outcome, reason = "acknowledged", "native_request_acknowledged"
        except RecoveryBlocked:
            outcome = "outcome_unknown" if write_entered else "not_sent"
            reason = "native_send_or_receipt_unproven" if write_entered else "native_presend_guard_rejected"
        except BaseException:
            outcome, reason = "outcome_unknown", "native_send_or_receipt_unproven"
        receipt = NativeReceipt(request_id, context.registration.mission_id, context.attempt.id,
                                context.lease.generation, context.execution.fingerprint, method,
                                payload_hash, outcome, reason, self.clock(), **values)
        self.ledger.finish(receipt)
        return receipt

    @staticmethod
    def _thread(result: dict[str, Any], worktree: str, expected_thread: str | None = None) -> NativeThread:
        thread = result.get("thread")
        if not isinstance(thread, dict) or result.get("cwd") != worktree or thread.get("cwd") != worktree:
            raise RpcUncertain("native_thread_worktree_mismatch")
        thread_id, session_id = thread.get("id"), thread.get("sessionId")
        _uuid(thread_id)
        _uuid(session_id)
        if expected_thread is not None and thread_id != expected_thread:
            raise RpcUncertain("native_thread_identity_mismatch")
        if thread.get("status") != {"type": "idle"} or thread.get("ephemeral") is not False:
            raise RpcUncertain("native_thread_not_verified_idle")
        config = {name: result.get(name) for name in ("cwd", "model", "modelProvider", "approvalPolicy", "approvalsReviewer", "sandbox")}
        if any(config[name] is None for name in config) or any(not isinstance(config[name], str) or not config[name] or len(config[name]) > 256 for name in ("model", "modelProvider")):
            raise RpcUncertain("native_configuration_missing")
        return NativeThread(thread_id, session_id, digest(config), config["model"], config["modelProvider"], config)

    def continue_original(self, context: NativeContext) -> tuple[NativeThread | None, NativeReceipt]:
        if context.attempt.mode != "repair":
            raise RecoveryBlocked("native_original_requires_repair_attempt")
        parsed: list[NativeThread] = []

        def parse(result: dict[str, Any]) -> dict[str, str]:
            thread = self._thread(result, context.registration.worktree, context.execution.native_session_id)
            if (thread.session_root_id, thread.configuration_sha256) != (
                    context.initial_snapshot.session_root_id, context.initial_snapshot.configuration_sha256):
                raise RpcUncertain("native_original_configuration_changed")
            parsed.append(thread)
            return {"thread_id": thread.thread_id, "session_root_id": thread.session_root_id}

        receipt = self._mutate(context, "resume", "thread/resume", {
            "threadId": context.execution.native_session_id, "excludeTurns": True}, parse)
        return (parsed[0] if parsed and receipt.outcome == "acknowledged" else None), receipt

    def create_alternate(self, context: NativeContext,
                         bind_continuity: Callable[[NativeContext, Checkpoint, NativeThread], tuple[Registration, NativeOwnerSnapshot]]) -> tuple[NativeContext | None, NativeThread | None, NativeReceipt]:
        if context.attempt.mode != "alternate":
            raise RecoveryBlocked("native_new_thread_requires_reserved_alternate")
        reservation = self._validate_snapshot(context, context.initial_snapshot)
        source = self._fresh(context)
        parsed: list[NativeThread] = []

        def parse(result: dict[str, Any]) -> dict[str, str]:
            thread = self._thread(result, context.registration.worktree)
            if thread.thread_id == context.execution.native_session_id:
                raise RpcUncertain("native_alternate_identity_unchanged")
            parsed.append(thread)
            return {"thread_id": thread.thread_id, "session_root_id": thread.session_root_id}

        receipt = self._mutate(context, "new-thread", "thread/start",
                               {"cwd": context.registration.worktree, "ephemeral": False}, parse)
        if receipt.outcome != "acknowledged":
            return None, None, receipt
        thread = parsed[0]
        try:
            # Fresh source proof immediately before root advances the same task's continuity.
            source = self._fresh(context)
            target, snapshot = bind_continuity(context, reservation.checkpoint, thread)
            if (target.authority_fingerprint, target.native_session_id, target.engine, target.owner) != (
                    context.registration.authority_fingerprint, thread.thread_id, "codex", context.execution.owner):
                raise RecoveryBlocked("native_alternate_authority_or_owner_changed")
            if (snapshot.thread_id, snapshot.session_root_id, snapshot.configuration_sha256) != (
                    thread.thread_id, thread.session_root_id, thread.configuration_sha256):
                raise RecoveryBlocked("native_alternate_snapshot_mismatch")
            if snapshot.exclusion_verified is not True or not snapshot.exclusion_ref or not 0 <= self.clock() - snapshot.observed_at <= self.max_age:
                raise RecoveryBlocked("native_alternate_owner_unproven")
            if not 0 <= self.clock() - source.observed_at <= self.max_age:
                raise RecoveryBlocked("native_source_proof_expired_during_binding")
            self.socket_check(target.owner, snapshot)
            binding = self.control.append_binding(context, source, target, snapshot,
                                                  receipt_ref="native/request/" + receipt.request_id, now=self.clock())
            snapshot = replace(snapshot, execution_sha256=binding.fingerprint)
            new_context = replace(context, execution=binding, initial_snapshot=snapshot)
            self._validate_snapshot(new_context, snapshot)
            receipt = replace(receipt, binding_sha256=binding.fingerprint, reason="native_alternate_bound_same_task")
            # Update receipt metadata only; never resend the acknowledged thread/start.
            self.ledger.db.execute("UPDATE native_delivery SET receipt=? WHERE request_id=?",
                                   (json.dumps(asdict(receipt), sort_keys=True), receipt.request_id))
            return new_context, thread, receipt
        except BaseException:
            receipt = replace(receipt, outcome="outcome_unknown", reason="native_created_thread_requires_binding_reconciliation")
            self.ledger.db.execute("UPDATE native_delivery SET outcome=?,receipt=? WHERE request_id=?",
                                   (receipt.outcome, json.dumps(asdict(receipt), sort_keys=True), receipt.request_id))
            return None, thread, receipt

    def start_turn(self, context: NativeContext, thread: NativeThread, text: str,
                   authorize_model: Callable[[NativeContext, NativeThread, str, Reservation, NativeOwnerSnapshot], ModelPermit]) -> NativeReceipt:
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 32768:
            raise RecoveryBlocked("native_local_prompt_bounds_invalid")
        if (thread.thread_id, thread.session_root_id, thread.configuration_sha256) != (
                context.execution.native_session_id, context.initial_snapshot.session_root_id,
                context.initial_snapshot.configuration_sha256):
            raise RecoveryBlocked("native_turn_execution_mismatch")
        if thread.configuration_sha256 != digest(thread.configuration) or (
                thread.model, thread.model_provider) != (thread.configuration.get("model"), thread.configuration.get("modelProvider")):
            raise RecoveryBlocked("native_turn_configuration_payload_changed")
        if context.attempt.mode == "alternate" and (context.execution.attempt_id, context.execution.checkpoint_sha256) != (
                context.attempt.id, context.checkpoint_sha256):
            raise RecoveryBlocked("native_alternate_binding_required_before_model")

        def authorize(snapshot: NativeOwnerSnapshot, request_sha: str) -> Callable[[], None]:
            reservation = self.control.assert_reserved(context, now=self.clock())
            permit = authorize_model(context, thread, request_sha, reservation, snapshot)
            if not isinstance(permit, ModelPermit) or (permit.authority_sha256, permit.execution_sha256,
                    permit.attempt_id, permit.generation, permit.request_sha256, permit.configuration_sha256,
                    permit.reserved_cost_microusd) != (context.registration.authority_fingerprint,
                    context.execution.fingerprint, context.attempt.id, context.lease.generation,
                    request_sha, thread.configuration_sha256, reservation.cost_microusd):
                raise RecoveryBlocked("native_root_budget_scope_permit_mismatch")
            if not all((permit.approval_ref, permit.budget_ref, permit.native_guard_ref)) or permit.native_guard_verified is not True or permit.model_calls_authorized is not True or not math.isfinite(permit.expires_at) or self.clock() >= permit.expires_at:
                raise RecoveryBlocked("native_model_or_tool_guard_not_authorized")
            def recheck_permit() -> None:
                if self.clock() >= permit.expires_at:
                    raise RecoveryBlocked("native_model_permit_expired_before_send")
            return recheck_permit

        def parse(result: dict[str, Any]) -> dict[str, str]:
            turn = result.get("turn")
            if not isinstance(turn, dict) or turn.get("status") not in {"inProgress", "completed", "interrupted", "failed"}:
                raise RpcUncertain("native_turn_response_unproven")
            _uuid(turn.get("id"))
            return {"thread_id": thread.thread_id, "session_root_id": thread.session_root_id, "turn_id": turn["id"]}

        return self._mutate(context, "model-turn", "turn/start", {"threadId": thread.thread_id,
                           "input": [{"type": "text", "text": text}]}, parse, authorize)

    def dispatch_owned_tool(self, context: NativeContext, *, call_id: str, expected_turn_id: str,
                            tool: str, arguments: Any,
                            authorize_tool: Callable[[NativeContext, str, str, str, NativeOwnerSnapshot], bool],
                            executor: Callable[[str, Any], Any]) -> tuple[Any, NativeReceipt]:
        """Root-owned tools only. Does not claim to intercept native built-in tools."""
        _uuid(call_id)
        _uuid(expected_turn_id)
        if not isinstance(tool, str) or not tool or len(tool) > 128:
            raise RecoveryBlocked("native_tool_identity_required")
        argument_sha = digest(arguments)
        request_sha = digest({"tool": tool, "arguments_sha256": argument_sha, "turn_id": expected_turn_id})
        snapshot = self._fresh(context, active=True)
        if snapshot.active_turn_id != expected_turn_id:
            raise RecoveryBlocked("native_tool_turn_mismatch")
        request_id = self.ledger.reserve(context, "tool-" + call_id, "owned-tool", request_sha)
        entered = False
        result = None
        try:
            snapshot = self._fresh(context, active=True)
            if snapshot.active_turn_id != expected_turn_id or authorize_tool(context, tool, argument_sha, request_sha, snapshot) is not True:
                raise RecoveryBlocked("native_tool_scope_not_authorized")
            snapshot = self._fresh(context, active=True)
            if snapshot.active_turn_id != expected_turn_id:
                raise RecoveryBlocked("native_tool_turn_changed_before_dispatch")
            entered = True
            result = executor(tool, arguments)  # Local payload only; never stored or journaled.
            self.control.assert_reserved(context, now=self.clock())
            outcome, reason = "acknowledged", "owned_tool_returned_not_mission_completion"
        except BaseException:
            result = None
            outcome, reason = ("outcome_unknown", "owned_tool_effect_requires_reconciliation") if entered else ("not_sent", "owned_tool_presend_guard_rejected")
        receipt = NativeReceipt(request_id, context.registration.mission_id, context.attempt.id,
                                context.lease.generation, context.execution.fingerprint, "owned-tool",
                                request_sha, outcome, reason, self.clock(), thread_id=context.execution.native_session_id,
                                session_root_id=snapshot.session_root_id, turn_id=expected_turn_id)
        self.ledger.finish(receipt)
        return result, receipt

    def close(self) -> None:
        self.proxy.close()
        self.connected_owner = None
