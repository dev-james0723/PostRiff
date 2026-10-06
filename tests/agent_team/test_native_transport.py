"""Fake proxy + local sidecar fixtures only; no Codex process/provider/model."""
import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_team.native_transport import (CodexUnixProxy, DeliveryLedger, ModelPermit,
                                         NativeContext, NativeOwnerSnapshot, NativeOwnerTransport,
                                         SQLiteRecoveryControl, digest)
from agent_team.recovery import (ActiveAttemptEvidence, ContinuityEvidence, NativeOwner,
                                RecoveryBlocked, RecoveryEvidence, RecoveryStore,
                                Registration, WorkspaceSnapshot, WriterProof, build_checkpoint)

SESSION = "12345678-1234-1234-1234-123456789abc"
ROOT_SESSION = "11111111-2222-3333-4444-555555555555"
NEW_SESSION = "87654321-4321-4321-4321-cba987654321"
TURN = "99999999-8888-7777-6666-555555555555"
CALL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SHA = hashlib.sha256(b"original approved authorization").hexdigest()
DIRTY = hashlib.sha256(b"existing untracked and dirty changes").hexdigest()


def registration():
    return Registration("mission-1", "/registered/project", "/registered/worktree", SESSION, "codex",
                        NativeOwner("owning-native-server", "/registered/owner.sock", 42, "positive-pid-start"),
                        "task-1", "root-1", "phase-1", "approved/proposal#scope", SHA, "v1",
                        ("functional", "preserve-user-work"), ("effects/mission-1",))


def evidence(reg, now=100, revision=7):
    workspace = WorkspaceSnapshot(reg.worktree, "original-head", DIRTY, "untracked user notes", "git/positive-proof")
    continuity = ContinuityEvidence(reg.token_pilot_task_id, reg.token_pilot_root_task_id, reg.token_pilot_phase_id,
                                    revision, "ready", reg.authorization_ref, reg.authorization_sha256,
                                    reg.scope_version, "token-pilot/positive-proof", reg.native_session_id)
    writer = WriterProof(reg.mission_id, reg.native_session_id, reg.owner, now, "native/positive-owner-proof",
                         "same-owner-native", True, "idle", True, 0, True)
    return RecoveryEvidence(writer, continuity, workspace, workspace, scope_still_authorized=True,
                            side_effects_reconciled=True, side_effect_reconciliation_ref="effects/reconciled")


def response(reg, thread_id=SESSION, root_id=ROOT_SESSION):
    config = {"cwd": reg.worktree, "model": "fixture-model", "modelProvider": "fixture-provider",
              "approvalPolicy": "untrusted", "approvalsReviewer": "user",
              "sandbox": {"type": "workspaceWrite", "writableRoots": [reg.worktree], "networkAccess": False}}
    return dict(config, thread={"id": thread_id, "sessionId": root_id, "cwd": reg.worktree,
                                "status": {"type": "idle"}, "ephemeral": False})


def snapshot(reg, binding, ev, now=100, root_id=ROOT_SESSION, config=None):
    config = config or {k: v for k, v in response(reg).items() if k != "thread"}
    return NativeOwnerSnapshot(binding.fingerprint, now, ev, 4, 12345, 501,
                               reg.native_session_id, root_id, digest(config), "native/exclusive-writer-epoch", True)


class FakeProxy:
    def __init__(self, reg):
        self.reg = reg
        self.connections = []
        self.sent = []
        self.after_send = None
        self.override = None

    def connect(self, owner, snap):
        self.connections.append((owner, snap.socket_inode))

    def rpc(self, method, params, *, request_id, before_send):
        before_send()
        self.sent.append((method, copy.deepcopy(params), request_id))
        if self.after_send:
            self.after_send()
        if self.override:
            return self.override(method, params)
        if method == "thread/resume":
            return response(self.reg)
        if method == "thread/start":
            return response(self.reg, NEW_SESSION, NEW_SESSION)
        if method == "turn/start":
            return {"turn": {"id": TURN, "status": "inProgress", "items": []}}
        raise AssertionError("Unsupported fake RPC")

    def close(self):
        pass


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "recovery.sqlite")
        self.delivery_path = str(Path(self.temp.name) / "delivery.sqlite")
        self.store = RecoveryStore(self.path)
        self.ledger = DeliveryLedger(self.delivery_path)
        self.reg = registration()
        self.ev = evidence(self.reg)
        self.store.register(self.reg)
        self.binding = self.store.current_execution(self.reg)
        self.cp = build_checkpoint(self.reg, self.ev.continuity, self.ev.checkpoint_workspace,
                                   saved_at=100, goal_ref="original/request", verified_done=("inspection",),
                                   incomplete=("repair",), blockers=(), next_action="finite approved repair",
                                   evidence_refs=("local/receipt",), execution=self.binding)
        self.cp_sha = self.store.save_checkpoint(self.reg, self.cp)
        self.lease = self.store.acquire(self.reg, "holder-a", self.ev, now=100)
        self.now = 101.0
        self.proxy = FakeProxy(self.reg)
        self.control = SQLiteRecoveryControl(self.store)
        self.attempt = None
        self.snap = snapshot(self.reg, self.binding, self.ev)
        self.transport = NativeOwnerTransport(self.control, self.ledger, self.proxy,
                                               lambda context: self.current_snapshot(context),
                                               clock=lambda: self.now, socket_check=lambda owner, snap: None)

    def tearDown(self):
        self.transport.close()
        self.ledger.close()
        self.store.close()
        self.temp.cleanup()

    def current_snapshot(self, context):
        ev = replace(self.snap.evidence, writer=replace(self.snap.evidence.writer, observed_at=self.now))
        active = self.snap.active_evidence
        if active:
            active = replace(active, writer=replace(active.writer, observed_at=self.now), snapshot_observed_at=self.now)
        return replace(self.snap, observed_at=self.now, evidence=ev, active_evidence=active)

    def context(self, mode="repair"):
        if self.attempt is None:
            values = {"alternate_reason": "context_damaged", "alternate_evidence_ref": "native/context-damaged"} if mode == "alternate" else {}
            self.attempt = self.store.start_attempt(self.reg, self.lease, self.ev, incident_id="incident-1",
                                                     mode=mode, failure_signature="failure-1",
                                                     checkpoint_sha256=self.cp_sha, now=101, **values)
        return NativeContext(self.reg, self.binding, self.lease, self.attempt, self.cp_sha, self.snap)

    def permit(self, context, thread, request_sha, reservation, snap):
        return ModelPermit(context.registration.authority_fingerprint, context.execution.fingerprint,
                           context.attempt.id, context.lease.generation, request_sha,
                           thread.configuration_sha256, reservation.cost_microusd, self.now + 2,
                           "fixture/root-approved-model-boundary", "fixture/budget-reservation",
                           "fixture/native-writer-tool-guard", True, True)

    def ledger_receipts(self):
        return [json.loads(row[0]) for row in self.ledger.db.execute("SELECT receipt FROM native_delivery")]

    def test_original_thread_resume_preserves_distinct_session_root_no_model_or_completion(self):
        context = self.context()
        thread, receipt = self.transport.continue_original(context)
        self.assertEqual((thread.thread_id, thread.session_root_id), (SESSION, ROOT_SESSION))
        self.assertEqual(self.proxy.sent[0][:2], ("thread/resume", {"threadId": SESSION, "excludeTurns": True}))
        self.assertEqual(receipt.outcome, "acknowledged")
        self.assertFalse(receipt.retry_allowed)
        self.assertFalse(receipt.mission_complete)
        self.assertEqual(len(self.store.execution_history(self.reg)), 1)
        self.assertNotIn("turn/start", [item[0] for item in self.proxy.sent])

    def test_turn_requires_root_permit_and_durable_receipt_never_contains_payload(self):
        context = self.context()
        thread, _ = self.transport.continue_original(context)
        secret = "PRIVATE_PROMPT_UNIQUE_PAYLOAD never log this"
        receipt = self.transport.start_turn(context, thread, secret, self.permit)
        self.assertEqual(receipt.outcome, "acknowledged")
        self.assertEqual(receipt.turn_id, TURN)
        self.assertFalse(receipt.mission_complete)
        self.assertEqual(self.proxy.sent[-1][1], {"threadId": SESSION, "input": [{"type": "text", "text": secret}]})
        self.assertNotIn(secret, Path(self.delivery_path).read_bytes().decode("utf8", errors="ignore"))
        self.assertNotIn("text", self.ledger_receipts()[-1])
        with self.assertRaisesRegex(RecoveryBlocked, "already_reserved"):
            self.transport.start_turn(context, thread, secret, self.permit)

    def test_missing_native_guard_or_changed_budget_scope_prevents_model_boundary(self):
        for change in ({"native_guard_verified": False}, {"model_calls_authorized": False},
                       {"approval_ref": ""}, {"budget_ref": ""}, {"expires_at": 100},
                       {"request_sha256": SHA}, {"generation": 99}, {"reserved_cost_microusd": 1}):
            with self.subTest(change=change):
                # One-shot isolated ledger per permit case, still the same reserved authority.
                test_ledger = DeliveryLedger(":memory:")
                transport = NativeOwnerTransport(self.control, test_ledger, FakeProxy(self.reg), self.current_snapshot,
                                                  clock=lambda: self.now, socket_check=lambda owner, snap: None)
                context = self.context()
                thread, _ = transport.continue_original(context)
                authorize = lambda *args: replace(self.permit(*args), **change)
                receipt = transport.start_turn(context, thread, "fixture-only model input", authorize)
                self.assertEqual(receipt.outcome, "not_sent")
                self.assertEqual([x[0] for x in transport.proxy.sent], ["thread/resume"])
                transport.close()
                test_ledger.close()

    def test_expired_lease_is_never_dead_writer_proof(self):
        context = self.context()
        self.now = 131
        with self.assertRaisesRegex(RecoveryBlocked, "lease_expired_or_fenced"):
            self.transport.continue_original(context)
        self.assertEqual(self.proxy.connections, [])
        self.assertEqual(self.proxy.sent, [])

    def test_active_unknown_wait_effects_stale_snapshot_and_identity_fail_before_connect(self):
        context = self.context()
        cases = [
            replace(self.snap, observed_at=90),
            replace(self.snap, exclusion_verified=False),
            replace(self.snap, evidence=replace(self.ev, writer=replace(self.ev.writer, native_state="active", writer_quiescent=False))),
            replace(self.snap, evidence=replace(self.ev, writer=replace(self.ev.writer, native_state="notLoaded"))),
            replace(self.snap, evidence=replace(self.ev, writer=replace(self.ev.writer, native_state="stopped"))),
            replace(self.snap, evidence=replace(self.ev, writer=replace(self.ev.writer, identity_verified=False))),
            replace(self.snap, evidence=replace(self.ev, writer=replace(self.ev.writer, owner=replace(self.reg.owner, pid=99)))),
            replace(self.snap, evidence=replace(self.ev, writer=replace(self.ev.writer, owner=replace(self.reg.owner, process_start="reused-pid")))),
            replace(self.snap, evidence=replace(self.ev, waiting_for="human")),
            replace(self.snap, evidence=replace(self.ev, unknown_external_effects=("remote/send-unknown",))),
            replace(self.snap, evidence=replace(self.ev, current_workspace=replace(self.ev.current_workspace, head="stale-head"))),
            replace(self.snap, evidence=replace(self.ev, current_workspace=replace(self.ev.current_workspace, dirty_sha256=SHA))),
        ]
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(RecoveryBlocked):
                self.transport.continue_original(replace(context, initial_snapshot=bad))
        self.assertEqual(self.proxy.connections, [])
        self.assertEqual(self.proxy.sent, [])

    def test_final_presend_guard_reobserves_writer_after_connect(self):
        context = self.context()
        calls = []
        def observer(ctx):
            calls.append(1)
            snap = self.current_snapshot(ctx)
            if len(calls) >= 2:
                snap = replace(snap, evidence=replace(snap.evidence, writer=replace(snap.evidence.writer, native_state="active", writer_quiescent=False)))
            return snap
        self.transport.observer = observer
        thread, receipt = self.transport.continue_original(context)
        self.assertIsNone(thread)
        self.assertEqual(receipt.outcome, "not_sent")
        self.assertEqual(self.proxy.sent, [])

    def test_budget_callback_lease_loss_is_rechecked_before_turn_start(self):
        context = self.context()
        thread, _ = self.transport.continue_original(context)
        def authorize(*args):
            permit = self.permit(*args)
            self.store.db.execute("DELETE FROM recovery_leases")
            return permit
        receipt = self.transport.start_turn(context, thread, "fixture-only", authorize)
        self.assertEqual(receipt.outcome, "not_sent")
        self.assertEqual([x[0] for x in self.proxy.sent], ["thread/resume"])

    def test_model_permit_expiry_during_final_owner_observation_prevents_send(self):
        context = self.context()
        thread, _ = self.transport.continue_original(context)
        count = []
        def observer(ctx):
            count.append(1)
            if len(count) == 3:
                self.now = 104
            return self.current_snapshot(ctx)
        self.transport.observer = observer
        receipt = self.transport.start_turn(context, thread, "fixture-only", self.permit)
        self.assertEqual(receipt.outcome, "not_sent")
        self.assertEqual([x[0] for x in self.proxy.sent], ["thread/resume"])

    def test_native_completed_turn_response_never_marks_mission_complete(self):
        context = self.context()
        thread, _ = self.transport.continue_original(context)
        self.proxy.override = lambda method, params: {"turn": {"id": TURN, "status": "completed", "items": []}}
        receipt = self.transport.start_turn(context, thread, "fixture-only", self.permit)
        self.assertEqual(receipt.outcome, "acknowledged")
        self.assertFalse(receipt.mission_complete)
        self.assertFalse(hasattr(self.store, "complete_mission"))

    def test_timeout_send_error_and_lease_loss_after_send_are_unknown_no_resend(self):
        context = self.context()
        def timeout():
            raise TimeoutError("PRIVATE_PROVIDER_ERROR_BODY must not log")
        self.proxy.after_send = timeout
        thread, receipt = self.transport.continue_original(context)
        self.assertIsNone(thread)
        self.assertEqual(receipt.outcome, "outcome_unknown")
        self.assertNotIn("PRIVATE_PROVIDER_ERROR_BODY", json.dumps(self.ledger_receipts()))
        self.proxy.after_send = None
        with self.assertRaisesRegex(RecoveryBlocked, "unknown_delivery"):
            self.transport.continue_original(context)
        self.assertEqual(len(self.proxy.sent), 1)

    def test_unknown_delivery_survives_transport_restart(self):
        context = self.context()
        self.proxy.after_send = lambda: (_ for _ in ()).throw(BrokenPipeError())
        self.transport.continue_original(context)
        self.ledger.close()
        self.ledger = DeliveryLedger(self.delivery_path)
        restarted = NativeOwnerTransport(self.control, self.ledger, FakeProxy(self.reg), self.current_snapshot,
                                         clock=lambda: self.now, socket_check=lambda owner, snap: None)
        with self.assertRaisesRegex(RecoveryBlocked, "unknown_delivery"):
            restarted.continue_original(context)
        self.assertEqual(restarted.proxy.sent, [])

    def test_acknowledged_response_with_lost_fence_retains_ids_but_not_success(self):
        context = self.context()
        self.proxy.after_send = lambda: self.store.db.execute("DELETE FROM recovery_leases")
        thread, receipt = self.transport.continue_original(context)
        self.assertIsNone(thread)
        self.assertEqual(receipt.outcome, "outcome_unknown")
        self.assertEqual((receipt.thread_id, receipt.session_root_id), (SESSION, ROOT_SESSION))
        self.assertFalse(receipt.mission_complete)

    def test_alternate_uses_durable_checkpoint_and_same_task_append_only_lineage(self):
        context = self.context("alternate")
        original = self.reg.fingerprint
        def bind(ctx, checkpoint, thread):
            self.assertEqual(checkpoint, self.cp)
            target = replace(self.reg, native_session_id=thread.thread_id)
            ev = evidence(target, self.now, revision=8)
            snap = snapshot(target, self.binding, ev, self.now, root_id=thread.session_root_id, config=thread.configuration)
            self.snap = snap
            return target, snap
        new_context, thread, receipt = self.transport.create_alternate(context, bind)
        self.assertEqual(receipt.outcome, "acknowledged")
        self.assertEqual(self.proxy.sent[0][:2], ("thread/start", {"cwd": self.reg.worktree, "ephemeral": False}))
        self.assertEqual(new_context.registration.fingerprint, original)
        self.assertEqual(new_context.registration.native_session_id, SESSION)
        self.assertEqual(new_context.execution.native_session_id, NEW_SESSION)
        self.assertEqual(new_context.execution.predecessor_sha256, self.binding.fingerprint)
        self.assertEqual(new_context.execution.checkpoint_sha256, self.cp_sha)
        self.assertEqual(new_context.execution.attempt_id, context.attempt.id)
        self.assertEqual(self.store.current_execution(self.reg).fingerprint, receipt.binding_sha256)
        self.assertEqual(len(self.store.execution_history(self.reg)), 2)
        self.assertEqual(new_context.registration.token_pilot_task_id, "task-1")
        self.assertFalse(receipt.mission_complete)
        self.snap = new_context.initial_snapshot
        started = self.transport.start_turn(new_context, thread, "fixture checkpoint rendered locally", self.permit)
        self.assertEqual(started.outcome, "acknowledged")
        self.assertEqual(self.proxy.sent[-1][1]["threadId"], NEW_SESSION)

    def test_created_thread_without_trusted_binding_requires_reconciliation_not_new_thread(self):
        context = self.context("alternate")
        def missing_bind(*args):
            raise RecoveryBlocked("token_pilot_native_binding_not_available")
        new_context, thread, receipt = self.transport.create_alternate(context, missing_bind)
        self.assertIsNone(new_context)
        self.assertEqual(thread.thread_id, NEW_SESSION)
        self.assertEqual(receipt.outcome, "outcome_unknown")
        self.assertEqual(len(self.store.execution_history(self.reg)), 1)
        with self.assertRaisesRegex(RecoveryBlocked, "unknown_delivery"):
            self.transport.create_alternate(context, missing_bind)
        self.assertEqual(len(self.proxy.sent), 1)

    def test_alternate_cannot_start_model_on_old_binding(self):
        context = self.context("alternate")
        thread = self.transport._thread(response(self.reg), self.reg.worktree, SESSION)
        with self.assertRaisesRegex(RecoveryBlocked, "alternate_binding_required"):
            self.transport.start_turn(context, thread, "fixture-only", self.permit)
        self.assertEqual(self.proxy.sent, [])

    def active_context(self):
        context = self.context()
        ev = self.current_snapshot(context).evidence
        writer = replace(ev.writer, native_state="active", writer_quiescent=False, active_tool_count=1)
        active = ActiveAttemptEvidence(self.binding.fingerprint, self.cp_sha, writer, ev.continuity,
                                       ev.current_workspace, self.now, True, "native/owned-workspace-proof",
                                       True, True, "effects/reconciled")
        self.snap = replace(self.snap, active_evidence=active, active_turn_id=TURN)
        return context

    def test_owned_tool_checks_current_turn_fence_scope_and_never_logs_arguments_output(self):
        context = self.active_context()
        executor = MagicMock(return_value={"output": "PRIVATE_TOOL_RESULT"})
        result, receipt = self.transport.dispatch_owned_tool(context, call_id=CALL, expected_turn_id=TURN,
                         tool="fixture_tool", arguments={"secret": "PRIVATE_TOOL_ARGUMENT"},
                         authorize_tool=lambda *args: True, executor=executor)
        self.assertEqual(result, {"output": "PRIVATE_TOOL_RESULT"})
        self.assertEqual(receipt.outcome, "acknowledged")
        self.assertFalse(receipt.mission_complete)
        durable = Path(self.delivery_path).read_bytes().decode("utf8", errors="ignore")
        self.assertNotIn("PRIVATE_TOOL_ARGUMENT", durable)
        self.assertNotIn("PRIVATE_TOOL_RESULT", durable)
        with self.assertRaisesRegex(RecoveryBlocked, "already_reserved"):
            self.transport.dispatch_owned_tool(context, call_id=CALL, expected_turn_id=TURN, tool="fixture_tool",
                         arguments={}, authorize_tool=lambda *args: True, executor=executor)
        self.assertEqual(executor.call_count, 1)

    def test_owned_tool_lease_loss_after_authorization_prevents_executor(self):
        context = self.active_context()
        executor = MagicMock()
        def authorize(*args):
            self.store.db.execute("DELETE FROM recovery_leases")
            return True
        _, receipt = self.transport.dispatch_owned_tool(context, call_id=CALL, expected_turn_id=TURN,
                         tool="fixture_tool", arguments={}, authorize_tool=authorize, executor=executor)
        self.assertEqual(receipt.outcome, "not_sent")
        executor.assert_not_called()

    def test_unknown_owned_tool_effect_never_retries(self):
        context = self.active_context()
        executor = MagicMock(side_effect=RuntimeError("private tool output"))
        _, receipt = self.transport.dispatch_owned_tool(context, call_id=CALL, expected_turn_id=TURN,
                         tool="fixture_tool", arguments={}, authorize_tool=lambda *args: True, executor=executor)
        self.assertEqual(receipt.outcome, "outcome_unknown")
        with self.assertRaisesRegex(RecoveryBlocked, "unknown_delivery"):
            self.transport.dispatch_owned_tool(context, call_id=CALL, expected_turn_id=TURN,
                         tool="fixture_tool", arguments={}, authorize_tool=lambda *args: True, executor=executor)
        self.assertEqual(executor.call_count, 1)

    def test_proxy_constructor_has_no_effect_and_explicit_connect_only_uses_proxy_sock(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch("agent_team.native_transport.subprocess.Popen", return_value=process) as launch, \
             patch("agent_team.native_transport.verify_socket"), \
             patch("agent_team.native_transport.os.set_blocking"), \
             patch.object(CodexUnixProxy, "rpc", return_value={}), \
             patch.object(CodexUnixProxy, "_write"):
            proxy = CodexUnixProxy("/installed/codex")
            launch.assert_not_called()
            proxy.connect(self.reg.owner, self.snap)
            self.assertEqual(launch.call_args.args[0], ["/installed/codex", "app-server", "proxy", "--sock", self.reg.owner.socket_path])
            self.assertNotIn("--stdio", launch.call_args.args[0])
            proxy.close()


if __name__ == "__main__":
    unittest.main()
