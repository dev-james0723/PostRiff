"""Verified cloud decision to the existing fenced native recovery transport.

This is an execution adapter, not a task registry or a shell-resume fallback.
The default guard is unavailable. Kynlo/ORC must supply the owning host's real
snapshot and enforce model/tool exclusion before any native RPC is allowed.
An acknowledged turn remains active; it is never reported as task completion.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Protocol
from uuid import UUID
from urllib.parse import urlencode

from .audio_bridge import request_json
from .native_transport import (ModelPermit, NativeContext, NativeOwnerSnapshot,
                               NativeOwnerTransport, NativeThread, Reservation,
                               digest, verify_socket)
from .recovery import (Checkpoint, ExecutionBinding, NativeOwner, RecoveryBlocked,
                       RecoveryStore, Registration, validate_recovery)

STAGING_NATIVE_WORK = "https://rafii-consumer-staging.vercel.app/api/internal/james-agent-team/native-work"
HASH = re.compile(r"[0-9a-f]{64}")
FIELDS = {"decisionKey", "effectKey", "missionId", "scopeVersion", "callRunId",
          "questionVersion", "choice", "authenticatedUserId", "workspaceId",
          "questionSha256", "authorizationSha256", "registrationSha256",
          "executionBindingSha256", "completionRequirementRefs", "attendedCallId",
          "humanEvidenceId", "mediaEvidenceId", "playbackAckSha256", "recordedAt"}


def _uuid(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise RecoveryBlocked("native_decision_uuid_required") from None


@dataclass(frozen=True)
class VerifiedDecision:
    """Normalized data read through the separate cloud verifier role.

    Never build this from an observer event, transcript, local approval text or
    the old Daily Call completion path. The owning cloud endpoint joins the
    immutable James-authenticated decision and private human/media receipts.
    """
    document: dict
    source_ref: str

    def validate(self, registration: Registration, execution: ExecutionBinding):
        d = self.document
        if not isinstance(d, dict) or set(d) != FIELDS:
            raise RecoveryBlocked("native_decision_contract_invalid")
        if d["choice"] not in {"continue", "wait", "needs_human"}:
            raise RecoveryBlocked("native_decision_choice_invalid")
        if d["decisionKey"] != d["effectKey"] or not isinstance(d["effectKey"], str) or not re.fullmatch(r"team-decision:[0-9a-f]{64}", d["effectKey"]):
            raise RecoveryBlocked("native_decision_effect_invalid")
        for name in ("questionVersion", "questionSha256", "authorizationSha256", "registrationSha256",
                     "executionBindingSha256", "humanEvidenceId", "mediaEvidenceId", "playbackAckSha256"):
            if not isinstance(d[name], str) or not HASH.fullmatch(d[name]):
                raise RecoveryBlocked("native_decision_hash_required")
        for name in ("callRunId", "authenticatedUserId", "workspaceId", "attendedCallId"):
            _uuid(d[name])
        if type(d["recordedAt"]) not in (int, float) or not math.isfinite(d["recordedAt"]) or d["recordedAt"] < 0:
            raise RecoveryBlocked("native_decision_time_invalid")
        expected_refs = [ref if HASH.fullmatch(ref) else hashlib.sha256(ref.encode()).hexdigest()
                         for ref in registration.acceptance_criteria]
        if (d["missionId"], d["scopeVersion"], d["authorizationSha256"], d["registrationSha256"],
                d["executionBindingSha256"], d["completionRequirementRefs"]) != (
                registration.mission_id, registration.scope_version, registration.authorization_sha256,
                registration.fingerprint, execution.fingerprint, expected_refs):
            raise RecoveryBlocked("native_decision_registration_changed")
        expected_effect = "team-decision:" + digest([d["callRunId"], d["missionId"], d["scopeVersion"], d["questionVersion"]])
        if d["effectKey"] != expected_effect or self.source_ref != STAGING_NATIVE_WORK:
            raise RecoveryBlocked("native_decision_source_unverified")
        execution.runtime_registration(registration)


def _verifier_token(canonical_root):
    root = Path(canonical_root).resolve(strict=True)
    path = root / ".runtime/cloud-verifier.token"
    if path.is_symlink() or not path.is_file() or path.resolve() != path or path.stat().st_mode & 0o077:
        raise RecoveryBlocked("private_native_verifier_token_required")
    token = path.read_text().strip()
    if not 32 <= len(token) <= 512 or any(c.isspace() for c in token):
        raise RecoveryBlocked("native_verifier_token_invalid")
    return token


def read_native_work(canonical_root, *, mission_id=None, request=request_json):
    """Read one bounded decision; the observer credential can never authorize it."""
    if mission_id is not None and (not isinstance(mission_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", mission_id)):
        raise RecoveryBlocked("native_work_mission_invalid")
    url = STAGING_NATIVE_WORK + ("?" + urlencode({"missionId": mission_id}) if mission_id is not None else "")
    token = _verifier_token(canonical_root)
    try:
        value = request(url, token)
    except Exception:
        # HTTP errors may contain private headers/provider bodies. Never retain them.
        raise RecoveryBlocked("native_cloud_decision_read_unavailable") from None
    if isinstance(value, dict) and value.get("state") == "idle":
        return None
    if not isinstance(value, dict) or value.get("state") != "ready" or not isinstance(value.get("decision"), dict):
        raise RecoveryBlocked("native_cloud_decision_unverified")
    if mission_id is not None and value["decision"].get("missionId") != mission_id:
        raise RecoveryBlocked("native_work_mission_mismatch")
    return VerifiedDecision(json.loads(json.dumps(value["decision"])), STAGING_NATIVE_WORK)


@dataclass(frozen=True)
class NativeGuardAttestation:
    source: str
    evidence_ref: str
    native_guard_ref: str
    observed_at: float
    registration_sha256: str
    execution_sha256: str
    authorization_sha256: str
    owner: NativeOwner
    writer_exclusion_enforced: bool
    model_and_tools_enforced: bool

    def validate(self, registration, execution, *, now):
        if (self.source != "kynlo_orc_owner" or not self.evidence_ref or not self.native_guard_ref
                or self.writer_exclusion_enforced is not True or self.model_and_tools_enforced is not True):
            raise RecoveryBlocked("native_guard_enforcement_unavailable")
        if (self.registration_sha256, self.execution_sha256, self.authorization_sha256, self.owner) != (
                registration.fingerprint, execution.fingerprint, registration.authorization_sha256, execution.owner):
            raise RecoveryBlocked("native_guard_binding_mismatch")
        if type(self.observed_at) not in (int, float) or not math.isfinite(self.observed_at) or not 0 <= now - self.observed_at <= 5:
            raise RecoveryBlocked("native_guard_attestation_stale")

    def projection(self, registration, execution, *, now):
        self.validate(registration, execution, now=now)
        return {"schemaVersion": 1, "source": self.source, "evidenceRef": self.evidence_ref,
                "nativeGuardRef": self.native_guard_ref, "nativeGuardVerified": True,
                "observedAt": self.observed_at, "registrationSha256": self.registration_sha256,
                "executionSha256": self.execution_sha256, "authorizationSha256": self.authorization_sha256,
                "owner": asdict(self.owner)}


class OwnerGuardPort(Protocol):
    """Only an authenticated owning-host adapter may implement this port.

    A metadata list, cooperative flock, queued mission, or arbitrary boolean is
    insufficient. The producer must exclude all native writers and fence native
    built-in tools as well as model dispatch, retaining the exact current scope.
    """
    def observe(self, registration: Registration, execution: ExecutionBinding,
                checkpoint: Checkpoint) -> tuple[NativeOwnerSnapshot, NativeGuardAttestation]: ...
    def authorize_model(self, context: NativeContext, thread: NativeThread, request_sha256: str,
                        reservation: Reservation, snapshot: NativeOwnerSnapshot) -> ModelPermit: ...


class UnavailableOwnerGuard:
    def observe(self, *args):
        raise RecoveryBlocked("kynlo_native_owner_guard_unavailable")

    def authorize_model(self, *args):
        raise RecoveryBlocked("kynlo_native_owner_guard_unavailable")


def _checkpoint(store, registration, checkpoint_sha256):
    row = store.db.execute("SELECT body,digest FROM recovery_checkpoints WHERE mission_id=? AND digest=?",
                           (registration.mission_id, checkpoint_sha256)).fetchone()
    if not row:
        raise RecoveryBlocked("durable_checkpoint_required")
    data = json.loads(row["body"])
    if hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest() != row["digest"]:
        raise RecoveryBlocked("transport_checkpoint_digest_mismatch")
    from .recovery import WorkspaceSnapshot
    data["workspace"] = WorkspaceSnapshot(**data["workspace"])
    for name in ("verified_done", "incomplete", "blockers", "acceptance_criteria", "side_effect_ledger_refs", "evidence_refs"):
        data[name] = tuple(data[name])
    return Checkpoint(**data)


def refresh_guarded_checkpoint(store, registration, checkpoint_sha256, guard, *,
                               clock=time.time, socket_check=verify_socket):
    """Save a new checkpoint after real native hooks advance continuity.

    The original checkpoint stays immutable. Scope, action, worktree/HEAD/dirty
    state and acceptance requirements cannot change here. An unseeded, active,
    stale or uncertain owner cannot refresh anything. This is required after
    genuine native Stop hooks; copying the old continuity revision would make
    start_attempt correctly reject the later human-approved continuation.
    """
    execution = store.current_execution(registration)
    checkpoint = _checkpoint(store, registration, checkpoint_sha256)
    snapshot, attestation = guard.observe(registration, execution, checkpoint)
    attestation.validate(registration, execution, now=clock())
    gate = validate_recovery(registration, snapshot.evidence, now=clock(), max_proof_age=5, execution=execution)
    if not gate.ready: raise RecoveryBlocked(gate.reason)
    if (snapshot.execution_sha256 != execution.fingerprint or snapshot.thread_id != execution.native_session_id
            or snapshot.exclusion_ref != attestation.native_guard_ref or snapshot.exclusion_verified is not True
            or asdict(snapshot.evidence.checkpoint_workspace) != asdict(checkpoint.workspace)
            or (snapshot.evidence.current_workspace.worktree, snapshot.evidence.current_workspace.head,
                snapshot.evidence.current_workspace.dirty_sha256) != (
                checkpoint.workspace.worktree, checkpoint.workspace.head, checkpoint.workspace.dirty_sha256)):
        raise RecoveryBlocked('native_checkpoint_refresh_binding_mismatch')
    socket_check(execution.owner, snapshot)
    revision = snapshot.evidence.continuity.revision
    if revision < checkpoint.token_pilot_revision:
        raise RecoveryBlocked('native_checkpoint_continuity_rollback')
    if revision == checkpoint.token_pilot_revision: return checkpoint_sha256
    fresh = replace(checkpoint, token_pilot_revision=revision, saved_at=clock(),
                    evidence_refs=checkpoint.evidence_refs+(attestation.evidence_ref,))
    return store.save_checkpoint(registration, fresh)


def publish_mission_binding(canonical_root, store, registration, checkpoint_sha256, guard, *,
                            actor_id, workspace_id, request=request_json, clock=time.time,
                            socket_check=verify_socket):
    """Publish a genuine owner attestation only, never an observer-derived guess."""
    _uuid(actor_id)
    _uuid(workspace_id)
    execution = store.current_execution(registration)
    checkpoint = _checkpoint(store, registration, checkpoint_sha256)
    snapshot, attestation = guard.observe(registration, execution, checkpoint)
    attestation.validate(registration, execution, now=clock())
    gate = validate_recovery(registration, snapshot.evidence, now=clock(), max_proof_age=5, execution=execution)
    if not gate.ready:
        raise RecoveryBlocked(gate.reason)
    if (snapshot.execution_sha256 != execution.fingerprint or snapshot.thread_id != execution.native_session_id
            or snapshot.exclusion_ref != attestation.native_guard_ref or snapshot.exclusion_verified is not True
            or asdict(snapshot.evidence.checkpoint_workspace) != asdict(checkpoint.workspace)):
        raise RecoveryBlocked("native_guard_snapshot_mismatch")
    socket_check(execution.owner, snapshot)
    payload = {"schemaVersion": 1, "actorId": actor_id, "workspaceId": workspace_id,
               "registration": asdict(registration), "registrationSha256": registration.fingerprint,
               "execution": asdict(execution), "executionSha256": execution.fingerprint,
               "nativeAttestation": attestation.projection(registration, execution, now=clock())}
    token = _verifier_token(canonical_root)
    try:
        reply = request(STAGING_NATIVE_WORK.removesuffix("native-work") + "mission-registry", token, payload)
    except Exception:
        raise RecoveryBlocked("native_binding_upload_unavailable") from None
    if not isinstance(reply, dict) or (reply.get("state"), reply.get("missionId"), reply.get("registrationSha256"),
            reply.get("executionSha256"), reply.get("attestationSha256")) != (
            "registered", registration.mission_id, registration.fingerprint, execution.fingerprint,
            digest(payload["nativeAttestation"])):
        raise RecoveryBlocked("native_binding_acknowledgment_unverified")
    return reply


def publish_native_receipt(canonical_root, receipt, *, request=request_json, clock=time.time):
    """A receipt is uploaded separately; an upload never creates a native turn."""
    if (not isinstance(receipt, dict) or receipt.get("source") != "kynlo_orc_native_transport"
            or receipt.get("nativeGuardVerified") is not True
            or receipt.get("executionState") not in {"unknown", "resumed", "turn_started"}
            or receipt.get("receiptSha256") != digest({k: v for k, v in receipt.items() if k != "receiptSha256"})):
        raise RecoveryBlocked("native_receipt_not_publishable")
    observed = receipt.get("observedAt")
    if type(observed) not in (int, float) or not math.isfinite(observed) or not 0 <= clock() - observed <= 30:
        raise RecoveryBlocked("native_receipt_stale")
    token = _verifier_token(canonical_root)
    try:
        reply = request(STAGING_NATIVE_WORK.removesuffix("native-work") + "native-receipts", token, receipt)
    except Exception:
        raise RecoveryBlocked("native_receipt_upload_unavailable") from None
    if not isinstance(reply, dict) or (reply.get("state"), reply.get("decisionKey"), reply.get("receiptSha256"),
                                     reply.get("executionState")) != (
            "recorded", receipt["decisionKey"], receipt["receiptSha256"], receipt["executionState"]):
        raise RecoveryBlocked("native_receipt_acknowledgment_unverified")
    return reply


def continue_verified_decision(store: RecoveryStore, registration: Registration, decision: VerifiedDecision,
                               checkpoint_sha256: str, guard: OwnerGuardPort,
                               transport_factory: Callable[[Callable], NativeOwnerTransport], *,
                               holder: str, reserved_cost_microusd: int = 0, clock=time.time,
                               socket_check=verify_socket):
    """One bounded same-session repair. Never retries, shells out or completes it.

    The caller retains a live recovery lease for the acknowledged active turn.
    Unknown sends stay unreconciled, preventing another decision from resending.
    All prompts come from the durable local checkpoint, never cloud event text.
    """
    execution = store.current_execution(registration)
    decision.validate(registration, execution)
    if decision.document["choice"] != "continue":
        return {"executionState": decision.document["choice"], "reason": "human_choice_" + decision.document["choice"],
                "decisionKey": decision.document["effectKey"]}
    checkpoint = _checkpoint(store, registration, checkpoint_sha256)

    def observe(context=None):
        snapshot, attestation = guard.observe(registration, execution, checkpoint)
        attestation.validate(registration, execution, now=clock())
        gate = validate_recovery(registration, snapshot.evidence, now=clock(), max_proof_age=5, execution=execution)
        if not gate.ready:
            raise RecoveryBlocked(gate.reason)
        if (snapshot.execution_sha256 != execution.fingerprint or snapshot.thread_id != execution.native_session_id
                or snapshot.exclusion_ref != attestation.native_guard_ref or snapshot.exclusion_verified is not True):
            raise RecoveryBlocked("native_guard_snapshot_mismatch")
        socket_check(execution.owner, snapshot)
        return snapshot, attestation

    # An unavailable guard produces no lease, attempt or native RPC.
    initial, attestation = observe()
    store.db.execute("CREATE TABLE IF NOT EXISTS native_decision_delivery (effect_key TEXT PRIMARY KEY, decision_sha256 TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT)")
    effect_key = decision.document["effectKey"]
    if store.db.execute("SELECT 1 FROM native_decision_delivery WHERE effect_key=?", (effect_key,)).fetchone():
        raise RecoveryBlocked("native_decision_already_reserved_no_resend")
    lease = store.acquire(registration, holder, initial.evidence, now=clock())
    try:
        store.db.execute("INSERT INTO native_decision_delivery VALUES(?,?,?,'reserved',NULL)",
                         (effect_key, digest(decision.document), checkpoint_sha256))
    except Exception:
        store.release(lease, now=clock())
        raise RecoveryBlocked("native_decision_already_reserved_no_resend") from None
    transport = None
    attempt = None
    receipt = {"decisionKey": effect_key, "registrationSha256": registration.fingerprint,
               "executionBindingSha256": execution.fingerprint, "checkpointSha256": checkpoint_sha256,
               "nativeGuardRef": attestation.native_guard_ref,
               "source": "kynlo_orc_native_transport", "nativeGuardVerified": True,
               "attemptId": None, "generation": None, "resumeRequestId": None,
               "turnRequestId": None, "turnId": None}
    try:
        initial, attestation = observe()
        attempt = store.start_attempt(registration, lease, initial.evidence, incident_id=effect_key,
                                      mode="repair", failure_signature="verified_phone_continuation",
                                      checkpoint_sha256=checkpoint_sha256, reserved_cost_microusd=reserved_cost_microusd,
                                      now=clock())
        context = NativeContext(registration, execution, lease, attempt, checkpoint_sha256, initial)
        receipt.update(attemptId=attempt.id, generation=lease.generation)
        transport = transport_factory(lambda context: observe(context)[0])
        thread, resumed = transport.continue_original(context)
        receipt["resumeRequestId"] = resumed.request_id
        if thread is None or resumed.outcome != "acknowledged":
            receipt.update(executionState="unknown", reason=resumed.reason)
        else:
            def authorize(context, thread, request_sha, reservation, snapshot):
                _, fresh = observe(context)
                permit = guard.authorize_model(context, thread, request_sha, reservation, snapshot)
                if permit.native_guard_ref != fresh.native_guard_ref or permit.native_guard_verified is not True:
                    raise RecoveryBlocked("native_guard_permit_mismatch")
                return permit
            turn = transport.start_turn(context, thread, checkpoint.next_action, authorize)
            receipt.update(turnRequestId=turn.request_id, turnId=turn.turn_id,
                           executionState="turn_started" if turn.outcome == "acknowledged" else "resumed" if turn.outcome == "not_sent" else "unknown",
                           reason=turn.reason)
    except RecoveryBlocked as error:
        receipt.update(executionState="blocked" if attempt is None else "unknown", reason=str(error))
    except Exception:
        receipt.update(executionState="unknown", reason="native_dispatch_outcome_unverified")
    finally:
        if transport:
            transport.close()
        if attempt is None:
            store.release(lease, now=clock())
    receipt["observedAt"] = clock()
    receipt["receiptSha256"] = digest(receipt)
    store.db.execute("UPDATE native_decision_delivery SET state=?,receipt=? WHERE effect_key=?",
                     (receipt["executionState"], json.dumps(receipt, sort_keys=True), effect_key))
    return receipt
