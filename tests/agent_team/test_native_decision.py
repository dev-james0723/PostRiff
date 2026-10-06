"""Synthetic owner/phone fixtures only; no native process, RPC or provider call."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from agent_team.native_decision import (NativeGuardAttestation, STAGING_NATIVE_WORK,
                                       UnavailableOwnerGuard, VerifiedDecision,
                                       continue_verified_decision, publish_mission_binding,
                                       publish_native_receipt, read_native_work)
from agent_team.native_transport import (DeliveryLedger, ModelPermit, NativeOwnerSnapshot,
                                        NativeOwnerTransport, SQLiteRecoveryControl, digest)
from agent_team.recovery import (ContinuityEvidence, NativeOwner, RecoveryBlocked,
                                RecoveryEvidence, RecoveryStore, Registration,
                                WorkspaceSnapshot, WriterProof, build_checkpoint)

SESSION = "12345678-1234-1234-1234-123456789abc"
TURN = "99999999-8888-7777-6666-555555555555"


class SyntheticProxy:
    def __init__(self, response):
        self.response, self.sent = response, []

    def connect(self, *args):
        pass

    def rpc(self, method, params, *, request_id, before_send):
        before_send()
        self.sent.append((method, params))
        return self.response if method == "thread/resume" else {"turn": {"id": TURN, "status": "inProgress"}}

    def close(self):
        pass


class NativeDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = RecoveryStore(str(self.root / "recovery.sqlite"))
        self.ledger = DeliveryLedger(str(self.root / "delivery.sqlite"))
        self.reg = Registration("mission-1", "/registered/project", "/registered/worktree", SESSION, "codex",
                                NativeOwner("owner-server", "/registered/owner.sock", 42, "pid-start"),
                                "task-1", "root-1", None, "original/authorization", digest("authority"), "v1",
                                ("preserve-original-work",), ("effects/mission-1",))
        self.store.register(self.reg)
        self.execution = self.store.current_execution(self.reg)
        ws = WorkspaceSnapshot(self.reg.worktree, "exact-head", digest("dirty"), "known notes", "git/receipt")
        continuity = ContinuityEvidence("task-1", "root-1", None, 7, "ready", self.reg.authorization_ref,
                                        self.reg.authorization_sha256, "v1", "continuity/receipt", SESSION)
        writer = WriterProof("mission-1", SESSION, self.reg.owner, 100, "owner/receipt", "same-owner-native",
                             True, "idle", True, 0, True)
        self.evidence = RecoveryEvidence(writer, continuity, ws, ws, scope_still_authorized=True,
                                         side_effects_reconciled=True, side_effect_reconciliation_ref="effects/reconciled")
        self.cp = build_checkpoint(self.reg, continuity, ws, saved_at=100, goal_ref="original/request",
                                    verified_done=("inspected",), incomplete=("finish",), blockers=(),
                                    next_action="繼續原本已授權的有界任務。", evidence_refs=("local/receipt",), execution=self.execution)
        self.cp_sha = self.store.save_checkpoint(self.reg, self.cp)
        config = {"cwd": self.reg.worktree, "model": "fixture-model", "modelProvider": "fixture-provider",
                  "approvalPolicy": "untrusted", "approvalsReviewer": "user", "sandbox": {"type": "readOnly"}}
        response = dict(config, thread={"id": SESSION, "sessionId": SESSION, "cwd": self.reg.worktree,
                                        "status": {"type": "idle"}, "ephemeral": False})
        self.proxy = SyntheticProxy(response)
        self.snapshot = NativeOwnerSnapshot(self.execution.fingerprint, 100, self.evidence, 4, 5, 501,
                                             SESSION, SESSION, digest(config), "fixture/guard-epoch", True)
        self.attestation = NativeGuardAttestation("kynlo_orc_owner", "fixture/owner", "fixture/guard-epoch", 100,
                                                  self.reg.fingerprint, self.execution.fingerprint,
                                                  self.reg.authorization_sha256, self.reg.owner, True, True)
        self.guard = Mock()
        self.guard.observe.return_value = (self.snapshot, self.attestation)
        self.guard.authorize_model.side_effect = lambda c, t, sha, reservation, snap: ModelPermit(
            self.reg.authority_fingerprint, self.execution.fingerprint, c.attempt.id, c.lease.generation, sha,
            t.configuration_sha256, reservation.cost_microusd, 104, "fixture/approval", "fixture/budget",
            "fixture/guard-epoch", True, True)
        d = {"decisionKey": "", "effectKey": "", "missionId": "mission-1", "scopeVersion": "v1",
             "callRunId": SESSION, "questionVersion": digest("question-version"), "choice": "continue",
             "authenticatedUserId": SESSION, "workspaceId": SESSION, "questionSha256": digest("question"),
             "authorizationSha256": self.reg.authorization_sha256, "registrationSha256": self.reg.fingerprint,
             "executionBindingSha256": self.execution.fingerprint,
             "completionRequirementRefs": [hashlib.sha256(b"preserve-original-work").hexdigest()],
             "attendedCallId": SESSION, "humanEvidenceId": digest("human-fixture"), "mediaEvidenceId": digest("media-fixture"),
             "playbackAckSha256": digest("real-receipt-fixture"), "recordedAt": 99}
        d["decisionKey"] = d["effectKey"] = "team-decision:" + digest([SESSION, "mission-1", "v1", d["questionVersion"]])
        self.decision = VerifiedDecision(d, STAGING_NATIVE_WORK)

    def tearDown(self):
        self.ledger.close()
        self.store.close()
        self.temp.cleanup()

    def run_bridge(self, guard=None, decision=None):
        def factory(observer):
            return NativeOwnerTransport(SQLiteRecoveryControl(self.store), self.ledger, self.proxy, observer,
                                         clock=lambda: 101, socket_check=lambda *args: None)
        return continue_verified_decision(self.store, self.reg, decision or self.decision, self.cp_sha,
                                           guard or self.guard, factory, holder="fixture-holder", clock=lambda: 101,
                                           socket_check=lambda *args: None)

    def test_unavailable_guard_creates_no_native_attempt_or_lease(self):
        with self.assertRaisesRegex(RecoveryBlocked, "kynlo_native_owner_guard_unavailable"):
            self.run_bridge(UnavailableOwnerGuard())
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM recovery_attempts").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM recovery_leases").fetchone()[0], 0)
        self.assertEqual(self.proxy.sent, [])

    def test_bound_fixture_continuation_uses_original_checkpoint_and_is_not_completion(self):
        receipt = self.run_bridge()
        self.assertEqual(receipt["executionState"], "turn_started")
        self.assertEqual(receipt["turnId"], TURN)
        self.assertEqual(self.proxy.sent[1][1]["input"][0]["text"], self.cp.next_action)
        self.assertEqual(receipt["checkpointSha256"], self.cp_sha)
        self.assertEqual(receipt["receiptSha256"], digest({k: v for k, v in receipt.items() if k != "receiptSha256"}))
        self.assertEqual(self.store.db.execute("SELECT outcome FROM recovery_attempts").fetchone()[0], "started")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM recovery_leases").fetchone()[0], 1)

    def test_same_human_choice_never_resends(self):
        self.run_bridge()
        with self.assertRaisesRegex(RecoveryBlocked, "native_decision_already_reserved_no_resend"):
            self.run_bridge()
        self.assertEqual(len(self.proxy.sent), 2)

    def test_missing_media_receipt_and_registration_drift_fail_before_native_rpc(self):
        for field, value in (("mediaEvidenceId", "not-a-receipt"), ("registrationSha256", digest("other"))):
            bad = VerifiedDecision(dict(self.decision.document, **{field: value}), STAGING_NATIVE_WORK)
            with self.assertRaises(RecoveryBlocked):
                self.run_bridge(decision=bad)
        self.assertEqual(self.proxy.sent, [])
        self.guard.observe.assert_not_called()

    def test_live_owner_unknown_effect_and_dirty_drift_remain_blocked(self):
        for ev in (replace(self.evidence, writer=replace(self.evidence.writer, native_state="running")),
                   replace(self.evidence, unknown_external_effects=("unknown/effect",)),
                   replace(self.evidence, current_workspace=replace(self.evidence.current_workspace, dirty_sha256=digest("changed")))):
            self.guard.observe.return_value = (replace(self.snapshot, evidence=ev), self.attestation)
            with self.assertRaises(RecoveryBlocked):
                self.run_bridge()
        self.assertEqual(self.proxy.sent, [])

    def test_stale_or_cooperative_only_guard_cannot_project_or_start(self):
        for proof in (replace(self.attestation, observed_at=90), replace(self.attestation, model_and_tools_enforced=False)):
            self.guard.observe.return_value = (self.snapshot, proof)
            with self.assertRaises(RecoveryBlocked):
                self.run_bridge()
            with self.assertRaises(RecoveryBlocked):
                proof.projection(self.reg, self.execution, now=101)
        self.assertEqual(self.proxy.sent, [])

    def test_wait_choice_does_not_need_or_invoke_a_native_guard(self):
        choice = VerifiedDecision(dict(self.decision.document, choice="wait"), STAGING_NATIVE_WORK)
        self.assertEqual(self.run_bridge(decision=choice)["executionState"], "wait")
        self.guard.observe.assert_not_called()
        self.assertEqual(self.proxy.sent, [])

    def test_verifier_read_is_pinned_to_staging_and_errors_hide_private_values(self):
        directory = self.root / ".runtime"
        directory.mkdir()
        token = directory / "cloud-verifier.token"
        token.write_text("fixture-verifier-only-credential-0000")
        token.chmod(0o600)
        request = Mock(return_value={"state": "ready", "decision": self.decision.document})
        verified = read_native_work(self.root, request=request)
        verified.validate(self.reg, self.execution)
        self.assertEqual(request.call_args.args[0], STAGING_NATIVE_WORK)
        request.side_effect = ValueError("private-token-body-must-not-escape")
        with self.assertRaisesRegex(RecoveryBlocked, "^native_cloud_decision_read_unavailable$"):
            read_native_work(self.root, request=request)

    def test_native_writer_epoch_change_cannot_reach_rpc(self):
        observed = []
        def observe(*args):
            observed.append(1)
            if len(observed) <= 2:
                return self.snapshot, self.attestation
            return (replace(self.snapshot, exclusion_ref="fixture/changed-epoch"),
                    replace(self.attestation, native_guard_ref="fixture/changed-epoch"))
        self.guard.observe.side_effect = observe
        receipt = self.run_bridge()
        self.assertEqual(receipt["executionState"], "unknown")
        self.assertEqual(self.proxy.sent, [])
        self.assertEqual(receipt["reason"], "native_owner_identity_or_configuration_changed")

    def test_projection_default_guard_is_blocked_before_network_upload(self):
        request = Mock()
        with self.assertRaisesRegex(RecoveryBlocked, "kynlo_native_owner_guard_unavailable"):
            publish_mission_binding(self.root, self.store, self.reg, self.cp_sha, UnavailableOwnerGuard(),
                                    actor_id=SESSION, workspace_id=SESSION, request=request, clock=lambda: 101)
        request.assert_not_called()

    def test_bound_fixture_projection_and_receipt_use_exact_cloud_ack_shape(self):
        directory = self.root / ".runtime"
        directory.mkdir()
        token = directory / "cloud-verifier.token"
        token.write_text("fixture-verifier-only-credential-0000")
        token.chmod(0o600)
        requested = []
        def request(url, token, payload):
            requested.append(url)
            if url.endswith("/mission-registry"):
                return {"state": "registered", "missionId": payload["registration"]["mission_id"],
                        "registrationSha256": payload["registrationSha256"], "executionSha256": payload["executionSha256"],
                        "attestationSha256": digest(payload["nativeAttestation"]), "replayed": False,
                        "nativeExecutionState": "not_dispatched"}
            return {"state": "recorded", "decisionKey": payload["decisionKey"], "receiptSha256": payload["receiptSha256"],
                    "executionState": payload["executionState"], "replayed": False}
        projection = publish_mission_binding(self.root, self.store, self.reg, self.cp_sha, self.guard,
                                             actor_id=SESSION, workspace_id=SESSION, request=request, clock=lambda: 101,
                                             socket_check=lambda *args: None)
        self.assertEqual(projection["nativeExecutionState"], "not_dispatched")
        receipt = self.run_bridge()
        self.assertEqual(publish_native_receipt(self.root, receipt, request=request, clock=lambda: 101)["executionState"], "turn_started")
        self.assertTrue(all(url.startswith("https://rafii-consumer-staging.vercel.app/api/internal/james-agent-team/") for url in requested))
