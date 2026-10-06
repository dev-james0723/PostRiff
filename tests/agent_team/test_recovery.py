"""Synthetic recovery controls only: no native sessions or model calls."""

import hashlib
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from agent_team.recovery import (
    ActiveAttemptEvidence,
    AcceptanceEvidence,
    ContinuityEvidence,
    JobProof,
    NativeOwner,
    RecoveryBlocked,
    RecoveryEvidence,
    RecoveryStore,
    Registration,
    WorkspaceSnapshot,
    WriterProof,
    build_checkpoint,
    native_command_preview,
    validate_recovery,
    verify_acceptance,
)


SHA = hashlib.sha256(b"original approved authority").hexdigest()
DIRTY = hashlib.sha256(b"user uncommitted changes including untracked paths").hexdigest()
SESSION = "12345678-1234-1234-1234-123456789abc"


def registration(**changes):
    return replace(Registration(
        mission_id="mission-1", canonical_project="/registered/project", worktree="/registered/worktree",
        native_session_id=SESSION, engine="codex", owner=NativeOwner("owning-desktop-server", "/registered/owner.sock", 42, "pid-start-identity"),
        token_pilot_task_id="task-1", token_pilot_root_task_id="root-1", token_pilot_phase_id="phase-1",
        authorization_ref="approved/proposal#scope", authorization_sha256=SHA, scope_version="v1",
        acceptance_criteria=("functional", "preserve-user-work"), side_effect_ledger_refs=("effects/mission-1",),
        descendant_refs=("child:42:123",), background_refs=("background:1",), ci_refs=("ci:run-1",),
    ), **changes)


def evidence(reg=None, now=100.0, **changes):
    reg = reg or registration()
    workspace = WorkspaceSnapshot(reg.worktree, "head-1", DIRTY, "modified user file and untracked notes", "git/observation-1")
    continuity = ContinuityEvidence(reg.token_pilot_task_id, reg.token_pilot_root_task_id, reg.token_pilot_phase_id,
                                    7, "ready", reg.authorization_ref, reg.authorization_sha256,
                                    reg.scope_version, "token-pilot/resolve-7", reg.native_session_id)
    writer = WriterProof(reg.mission_id, reg.native_session_id, reg.owner, now, "native/positive-owner-proof",
                         "same-owner-native", True, "idle", True, 0, True,
                         tuple(JobProof(ref, "finished", "native/child-finished", True) for ref in reg.descendant_refs),
                         tuple(JobProof(ref, "idle", "native/background-idle", True) for ref in reg.background_refs),
                         tuple(JobProof(ref, "finished", "ci/finished", True) for ref in reg.ci_refs))
    return replace(RecoveryEvidence(writer, continuity, workspace, workspace, scope_still_authorized=True,
                                   side_effects_reconciled=True, side_effect_reconciliation_ref="effects/reconciled-1"), **changes)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "recovery.sqlite")
        self.store = RecoveryStore(self.path)
        self.reg = registration()
        self.ev = evidence(self.reg)
        self.store.register(self.reg)
        self.checkpoint = build_checkpoint(
            self.reg, self.ev.continuity, self.ev.checkpoint_workspace, saved_at=100,
            goal_ref="original/request", verified_done=("inspection",), incomplete=("implementation",),
            blockers=("fixture-blocker",), next_action="finite authorized repair", evidence_refs=("read/receipt",))
        self.checkpoint_digest = self.store.save_checkpoint(self.reg, self.checkpoint)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def lease(self, holder="holder-a", now=100):
        return self.store.acquire(self.reg, holder, evidence(self.reg, now), now=now)

    def start(self, lease, mode="repair", signature="failure-A", now=101, incident="incident-1", **changes):
        if mode == "alternate":
            changes.setdefault("alternate_reason", "context_damaged")
            changes.setdefault("alternate_evidence_ref", "native/context-damage-proof")
        return self.store.start_attempt(self.reg, lease, evidence(self.reg, now), incident_id=incident,
                                        mode=mode, failure_signature=signature,
                                        checkpoint_sha256=self.checkpoint_digest, now=now, **changes)

    def finish(self, lease, attempt, signature, now=102, **changes):
        values = {"outcome": "failed", "failure_signature": signature, "measured_cost_microusd": 0,
                  "receipt_ref": "attempt/failure-receipt", "now": now}
        values.update(changes)
        self.store.record_attempt(lease, attempt, **values)

    def active(self, now=110, state="running", **changes):
        execution = self.store.current_execution(self.reg)
        runtime = execution.runtime_registration(self.reg)
        ev = evidence(runtime, now)
        writer = replace(ev.writer, native_state=state, writer_quiescent=False, active_tool_count=1)
        continuity = replace(ev.continuity, revision=max(7, execution.continuity_revision))
        return replace(ActiveAttemptEvidence(execution.fingerprint, self.checkpoint_digest, writer, continuity,
                                            ev.current_workspace, now, True, "native/workspace-attribution",
                                            True, True, "effects/reconciled-active"), **changes)

    def target(self, now=103, **changes):
        reg = replace(self.reg, native_session_id="87654321-4321-4321-4321-cba987654321",
                      owner=NativeOwner("owned-target-server", "/registered/target.sock", 55, "target-pid-start"),
                      descendant_refs=(), background_refs=(), ci_refs=())
        reg = replace(reg, **changes)
        ev = evidence(reg, now)
        return reg, replace(ev, continuity=replace(ev.continuity, revision=8))

    def test_active_attempt_heartbeat_renews_then_allows_receipt_after_original_ttl(self):
        lease = self.lease()
        attempt = self.start(lease)
        active = self.active(129)
        with self.assertRaisesRegex(RecoveryBlocked, "live_or_unknown_writer"):
            self.store.renew(lease, self.reg, replace(self.ev, writer=active.writer), now=129)
        renewed = self.store.renew_active_attempt(lease, self.reg, attempt, active, now=129)
        self.assertEqual(renewed.generation, lease.generation)
        self.assertEqual(renewed.expires_at, 159)
        self.finish(renewed, attempt, "finished-after-first-ttl", now=140, outcome="succeeded")
        self.assertFalse(hasattr(self.store, "complete_mission"))

    def test_active_heartbeat_requires_exact_started_attempt_and_unexpired_fence(self):
        lease = self.lease()
        attempt = self.start(lease)
        with self.assertRaisesRegex(RecoveryBlocked, "lease_expired_or_fenced"):
            self.store.renew_active_attempt(lease, self.reg, attempt, self.active(131), now=131)
        with self.assertRaisesRegex(RecoveryBlocked, "attempt_not_owned_or_already_recorded"):
            self.store.renew_active_attempt(lease, self.reg, replace(attempt, id=999), self.active(), now=110)
        self.finish(lease, attempt, "finished")
        with self.assertRaisesRegex(RecoveryBlocked, "attempt_not_owned_or_already_recorded"):
            self.store.renew_active_attempt(lease, self.reg, attempt, self.active(), now=110)

    def test_active_heartbeat_rejects_stale_unknown_effect_or_mismatched_identity(self):
        lease = self.lease()
        attempt = self.start(lease)
        good = self.active()
        cases = (
            replace(good, snapshot_observed_at=70),
            replace(good, snapshot_observed_at=111),
            replace(good, writer=replace(good.writer, observed_at=70)),
            replace(good, writer=replace(good.writer, native_state="notLoaded")),
            replace(good, writer=replace(good.writer, native_state="stopped")),
            replace(good, writer=replace(good.writer, inventory_complete=False)),
            replace(good, writer=replace(good.writer, owner=replace(good.writer.owner, process_start="reused-pid"))),
            replace(good, unknown_external_effects=("unknown-submission",)),
            replace(good, side_effects_reconciled=False),
            replace(good, workspace_changes_owned=False),
            replace(good, checkpoint_sha256="0" * 64),
            replace(good, continuity=replace(good.continuity, session_id="other-session")),
            replace(good, continuity=replace(good.continuity, state="owner_state_unknown")),
            replace(good, continuity=replace(good.continuity, revision=6)),
            replace(good, continuity=replace(good.continuity, scope_version="unapproved-v2")),
        )
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(RecoveryBlocked):
                self.store.renew_active_attempt(lease, self.reg, attempt, bad, now=110)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM recovery_attempt_heartbeats").fetchone()[0], 0)

    def test_owned_progress_and_known_waits_keep_fence_without_authorizing_retry(self):
        lease = self.lease()
        attempt = self.start(lease)
        for index, state in enumerate(("waiting_tool", "waiting_ci", "waiting_human", "waiting_approval")):
            now = 110 + index
            active = self.active(now, state)
            active = replace(active, workspace=replace(active.workspace, head="owned-new-head", dirty_sha256=hashlib.sha256(b"owned-progress").hexdigest()))
            lease = self.store.renew_active_attempt(lease, self.reg, attempt, active, now=now)
            with self.assertRaisesRegex(RecoveryBlocked, "waiting_excluded"):
                self.store.start_attempt(self.reg, lease, replace(evidence(self.reg, now), waiting_for=state),
                                         incident_id="new-incident", mode="repair", failure_signature="new-signature",
                                         checkpoint_sha256=self.checkpoint_digest, now=now)

    def test_append_execution_keeps_registration_task_scope_cost_and_history(self):
        lease = self.lease()
        attempt = self.start(lease, mode="alternate")
        target, ev = self.target()
        original = self.reg.fingerprint
        origin = self.store.current_execution(self.reg)
        binding = self.store.append_execution(self.reg, lease, attempt, evidence(self.reg, 103), target, ev,
                                             evidence_ref="handoff/verified-token-pilot-bind", now=103)
        self.assertEqual(binding.predecessor_sha256, origin.fingerprint)
        self.assertEqual(binding.registration_sha256, original)
        self.assertEqual(binding.checkpoint_sha256, self.checkpoint_digest)
        self.assertEqual(self.store.register(self.reg), original)
        self.assertEqual(len(self.store.execution_history(self.reg)), 2)
        runtime = binding.runtime_registration(self.reg)
        self.assertEqual(runtime.authority_fingerprint, self.reg.authority_fingerprint)
        self.assertEqual(runtime.native_session_id, target.native_session_id)
        self.assertEqual(runtime.token_pilot_task_id, self.reg.token_pilot_task_id)
        self.assertEqual(runtime.max_alternates, 1)
        with self.assertRaisesRegex(RecoveryBlocked, "registered_contract_changed_needs_review"):
            self.store.register(target)
        old = self.active()
        old = replace(old, writer=evidence(self.reg, 110).writer)
        with self.assertRaisesRegex(RecoveryBlocked, "owning_native_identity_mismatch"):
            self.store.renew_active_attempt(lease, self.reg, attempt, old, now=110)
        renewed = self.store.renew_active_attempt(lease, self.reg, attempt, self.active(129), now=129)
        self.finish(renewed, attempt, "handoff-finished", now=140, outcome="succeeded")
        checkpoint = build_checkpoint(self.reg, ev.continuity, ev.current_workspace, saved_at=141,
                                      goal_ref="original/request", verified_done=("handoff",), incomplete=("validate",),
                                      blockers=(), next_action="independent acceptance", evidence_refs=("native/receipt",), execution=binding)
        self.assertEqual(checkpoint.registration_sha256, original)
        self.assertEqual(checkpoint.native_session_id, target.native_session_id)
        digest = self.store.save_checkpoint(self.reg, checkpoint)
        latest = evidence(target, 141)
        latest = replace(latest, continuity=replace(latest.continuity, revision=8))
        with self.assertRaisesRegex(RecoveryBlocked, "retry_cap_reached"):
            self.store.start_attempt(self.reg, renewed, latest, incident_id="incident-1",
                                     mode="alternate", failure_signature="new-after-handoff", checkpoint_sha256=digest,
                                     alternate_reason="context_damaged", alternate_evidence_ref="new-damage-proof", now=141)

    def test_execution_handoff_cannot_change_authority_or_bypass_reserved_alternate(self):
        lease = self.lease()
        repair = self.start(lease)
        target, ev = self.target()
        with self.assertRaisesRegex(RecoveryBlocked, "reserved_alternate"):
            self.store.append_execution(self.reg, lease, repair, evidence(self.reg, 103), target, ev,
                                        evidence_ref="handoff", now=103)
        self.finish(lease, repair, "different-failure")
        alternate = self.start(lease, mode="alternate", signature="other-failure", now=103)
        for changed in (replace(target, scope_version="v2"), replace(target, token_pilot_task_id="new-task"),
                        replace(target, max_repairs=1), replace(target, side_effect_ledger_refs=("new-effects",))):
            with self.subTest(changed=changed), self.assertRaisesRegex(RecoveryBlocked, "execution_authority_changed"):
                self.store.append_execution(self.reg, lease, alternate, evidence(self.reg, 104), changed, ev,
                                            evidence_ref="handoff", now=104)

    def test_execution_handoff_rejects_unproven_source_target_and_repeated_hop(self):
        lease = self.lease()
        attempt = self.start(lease, mode="alternate")
        target, ev = self.target()
        source = evidence(self.reg, 103)
        for bad in (replace(ev, writer=replace(ev.writer, native_state="notLoaded")),
                    replace(ev, writer=replace(ev.writer, identity_verified=False)),
                    replace(ev, unknown_external_effects=("unknown-effect",)),
                    replace(ev, continuity=replace(ev.continuity, revision=7)),
                    replace(ev, continuity=replace(ev.continuity, session_id=None))):
            with self.subTest(bad=bad), self.assertRaises(RecoveryBlocked):
                self.store.append_execution(self.reg, lease, attempt, source, target, bad, evidence_ref="handoff", now=103)
        with self.assertRaisesRegex(RecoveryBlocked, "live_or_unknown_writer"):
            self.store.append_execution(self.reg, lease, attempt, replace(source, writer=replace(source.writer, native_state="running")),
                                        target, ev, evidence_ref="handoff", now=103)
        self.store.append_execution(self.reg, lease, attempt, source, target, ev, evidence_ref="handoff", now=103)
        new_target = replace(target, native_session_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        current = evidence(target, 104)
        current = replace(current, continuity=replace(current.continuity, revision=8))
        final = evidence(new_target, 104)
        final = replace(final, continuity=replace(final.continuity, revision=9))
        with self.assertRaisesRegex(RecoveryBlocked, "alternate_execution_already_bound"):
            self.store.append_execution(self.reg, lease, attempt, current, new_target, final, evidence_ref="second-hop", now=104)

    def test_only_one_of_two_competing_holders_can_acquire(self):
        barrier = threading.Barrier(2)

        def compete(holder):
            store = RecoveryStore(self.path)
            try:
                barrier.wait()
                try:
                    return store.acquire(self.reg, holder, self.ev, now=100)
                except RecoveryBlocked as exc:
                    return str(exc)
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, ("holder-a", "holder-b")))
        self.assertEqual(sum(not isinstance(item, str) for item in results), 1)
        self.assertIn("lease_conflict", results)

    def test_shared_worktree_blocks_a_different_mission(self):
        self.lease()
        other = registration(mission_id="mission-2")
        self.store.register(other)
        with self.assertRaisesRegex(RecoveryBlocked, "lease_conflict"):
            self.store.acquire(other, "holder-b", evidence(other), now=100)

    def test_expired_lease_is_never_writer_death_proof(self):
        first = self.lease()
        ev = evidence(self.reg, 131)
        for native_state in ("notLoaded", "stopped", "missing", "unknown", "running"):
            with self.subTest(native_state=native_state):
                bad = replace(ev, writer=replace(ev.writer, native_state=native_state))
                with self.assertRaisesRegex(RecoveryBlocked, "live_or_unknown_writer"):
                    self.store.acquire(self.reg, "holder-b", bad, now=131)
        second = self.store.acquire(self.reg, "holder-b", ev, now=131)
        self.assertGreater(second.generation, first.generation)
        with self.assertRaisesRegex(RecoveryBlocked, "lease_expired_or_fenced"):
            self.store.assert_fence(first, now=131)

    def test_stale_holder_cannot_record_an_attempt_after_replacement(self):
        first = self.lease()
        attempt = self.start(first)
        self.store.acquire(self.reg, "holder-b", evidence(self.reg, 131), now=131)
        with self.assertRaisesRegex(RecoveryBlocked, "lease_expired_or_fenced"):
            self.finish(first, attempt, "failure-A", now=132)

    def test_positive_exact_native_identity_is_required(self):
        cases = (
            replace(self.ev.writer, source="kynlo-listing"),
            replace(self.ev.writer, identity_verified=False),
            replace(self.ev.writer, owner=replace(self.reg.owner, pid=43)),
            replace(self.ev.writer, owner=replace(self.reg.owner, process_start="PID-reused")),
            replace(self.ev.writer, owner=replace(self.reg.owner, server_id="fresh-unrelated-server")),
            replace(self.ev.writer, native_session_id="different-session"),
            replace(self.ev.writer, evidence_ref=""),
            replace(self.ev.writer, observed_at=1),
            replace(self.ev.writer, observed_at=101),
        )
        for writer in cases:
            with self.subTest(writer=writer):
                self.assertFalse(validate_recovery(self.reg, replace(self.ev, writer=writer), now=100).ready)

    def test_active_native_writer_or_tool_is_blocked(self):
        for writer in (replace(self.ev.writer, native_state="running"), replace(self.ev.writer, writer_quiescent=False),
                       replace(self.ev.writer, active_tool_count=1), replace(self.ev.writer, active_tool_count=-1)):
            with self.subTest(writer=writer):
                self.assertFalse(validate_recovery(self.reg, replace(self.ev, writer=writer), now=100).ready)

    def test_each_registered_job_needs_positive_idle_or_finished_proof(self):
        for name in ("descendants", "background", "ci"):
            jobs = getattr(self.ev.writer, name)
            for replacement in ((), (replace(jobs[0], state="running"),), (replace(jobs[0], state="unknown"),),
                                (replace(jobs[0], identity_verified=False),), (jobs[0], jobs[0])):
                with self.subTest(name=name, replacement=replacement):
                    writer = replace(self.ev.writer, **{name: replacement})
                    self.assertFalse(validate_recovery(self.reg, replace(self.ev, writer=writer), now=100).ready)
        writer = replace(self.ev.writer, inventory_complete=False)
        self.assertEqual(validate_recovery(self.reg, replace(self.ev, writer=writer), now=100).reason,
                         "writer_inventory_incomplete")

    def test_waiting_ci_tool_or_human_is_not_recovery(self):
        for waiting in ("ci", "tool", "human", "approval", "download"):
            with self.subTest(waiting=waiting):
                self.assertEqual(validate_recovery(self.reg, replace(self.ev, waiting_for=waiting), now=100).reason,
                                 "waiting_excluded")

    def test_token_pilot_authority_is_preserved(self):
        for state in ("busy", "owner_state_unknown", "needs_reconciliation", "needs_review", "completed"):
            with self.subTest(state=state):
                ev = replace(self.ev, continuity=replace(self.ev.continuity, state=state))
                self.assertEqual(validate_recovery(self.reg, ev, now=100).reason, f"token_pilot_{state}")
        ev = replace(self.ev, continuity=replace(self.ev.continuity, root_task_id="other-root"))
        self.assertEqual(validate_recovery(self.reg, ev, now=100).reason, "continuity_identity_mismatch")
        ev = replace(self.ev, continuity=replace(self.ev.continuity, scope_version="v2"))
        self.assertEqual(validate_recovery(self.reg, ev, now=100).reason, "authorization_changed")

    def test_stale_head_and_changed_dirty_work_need_review(self):
        current = replace(self.ev.current_workspace, head="new-HEAD")
        self.assertEqual(validate_recovery(self.reg, replace(self.ev, current_workspace=current), now=100).reason,
                         "head_changed_needs_review")
        current = replace(self.ev.current_workspace, dirty_sha256=hashlib.sha256(b"new user work").hexdigest())
        self.assertEqual(validate_recovery(self.reg, replace(self.ev, current_workspace=current), now=100).reason,
                         "dirty_changed_needs_review")
        self.assertEqual(self.checkpoint.workspace.dirty_sha256, DIRTY)
        self.assertIn("untracked", self.checkpoint.workspace.dirty_summary)

    def test_missing_or_changed_checkpoint_cannot_dispatch(self):
        lease = self.lease()
        with self.assertRaisesRegex(RecoveryBlocked, "durable_checkpoint_required"):
            self.store.start_attempt(self.reg, lease, self.ev, incident_id="incident-1", mode="repair",
                                     failure_signature="A", checkpoint_sha256="0" * 64, now=100)
        ev = replace(self.ev, checkpoint_workspace=replace(self.ev.checkpoint_workspace, head="other-HEAD"),
                     current_workspace=replace(self.ev.current_workspace, head="other-HEAD"))
        with self.assertRaisesRegex(RecoveryBlocked, "checkpoint_workspace_mismatch"):
            self.store.start_attempt(self.reg, lease, ev, incident_id="incident-1", mode="repair",
                                     failure_signature="A", checkpoint_sha256=self.checkpoint_digest, now=100)

    def test_at_most_two_repairs_and_one_alternate(self):
        lease = self.lease()
        first = self.start(lease, signature="A")
        self.finish(lease, first, "B")
        second = self.start(lease, signature="C", now=103)
        self.finish(lease, second, "D", now=104)
        with self.assertRaisesRegex(RecoveryBlocked, "retry_cap_reached"):
            self.start(lease, signature="E", now=105)
        alternate = self.start(lease, mode="alternate", signature="E", now=105)
        self.finish(lease, alternate, "F", now=106)
        with self.assertRaisesRegex(RecoveryBlocked, "retry_cap_reached"):
            self.start(lease, mode="alternate", signature="G", now=107)

    def test_repeat_signature_stops_without_fork_escape(self):
        lease = self.lease()
        first = self.start(lease, signature="same-failure")
        self.finish(lease, first, "same-failure")
        for mode in ("repair", "alternate"):
            with self.subTest(mode=mode), self.assertRaisesRegex(RecoveryBlocked, "repeated_failure_signature"):
                self.start(lease, mode=mode, signature="same-failure", now=103)
        with self.assertRaisesRegex(RecoveryBlocked, "repeated_failure_signature"):
            self.start(lease, signature="same-failure", now=103, incident="renamed-incident")

    def test_alternate_requires_specific_damage_or_expiry_evidence(self):
        lease = self.lease()
        with self.assertRaisesRegex(RecoveryBlocked, "alternate_requires_specific_reason_and_evidence"):
            self.start(lease, mode="alternate", alternate_reason="different-prompt", alternate_evidence_ref="prompt/changed")

    def test_checkpoint_revision_cannot_silently_move(self):
        lease = self.lease()
        ev = replace(self.ev, continuity=replace(self.ev.continuity, revision=8))
        with self.assertRaisesRegex(RecoveryBlocked, "continuity_revision_changed"):
            self.store.start_attempt(self.reg, lease, ev, incident_id="incident-1", mode="repair",
                                     failure_signature="A", checkpoint_sha256=self.checkpoint_digest, now=100)

    def test_unreconciled_external_effect_is_not_retried(self):
        ev = replace(self.ev, unknown_external_effects=("possible-duplicate-publication",))
        self.assertEqual(validate_recovery(self.reg, ev, now=100).reason, "unknown_external_effect")
        lease = self.lease()
        first = self.start(lease)
        self.finish(lease, first, "unknown-effect", outcome="outcome_unknown")
        with self.assertRaisesRegex(RecoveryBlocked, "prior_attempt_requires_reconciliation"):
            self.start(lease, signature="new-prompt", now=103, incident="new-incident")

    def test_expired_incomplete_attempt_cannot_be_retried(self):
        lease = self.lease()
        self.start(lease)
        new = self.store.acquire(self.reg, "holder-b", evidence(self.reg, 131), now=131)
        with self.assertRaisesRegex(RecoveryBlocked, "prior_attempt_requires_reconciliation"):
            self.start(new, signature="new-failure", now=132)

    def test_new_mission_on_same_worktree_cannot_evade_unknown_attempt(self):
        lease = self.lease()
        attempt = self.start(lease)
        self.finish(lease, attempt, "unknown-effect", outcome="outcome_unknown")
        other = registration(mission_id="new-mission-same-worktree")
        self.store.register(other)
        ev = evidence(other, 131)
        checkpoint = replace(self.checkpoint, mission_id=other.mission_id, registration_sha256=other.fingerprint)
        digest = self.store.save_checkpoint(other, checkpoint)
        new = self.store.acquire(other, "holder-b", ev, now=131)
        with self.assertRaisesRegex(RecoveryBlocked, "prior_attempt_requires_reconciliation"):
            self.store.start_attempt(other, new, ev, incident_id="new-incident", mode="repair",
                                     failure_signature="new-prompt", checkpoint_sha256=digest, now=131)

    def test_unknown_cost_blocks_retry_and_paid_authority_is_required(self):
        with self.assertRaisesRegex(RecoveryBlocked, "paid_authorization_required"):
            registration(cost_budget_microusd=100, max_attempt_cost_microusd=50).validate()
        lease = self.lease()
        first = self.start(lease)
        self.finish(lease, first, "B", measured_cost_microusd=None)
        with self.assertRaisesRegex(RecoveryBlocked, "prior_attempt_requires_reconciliation"):
            self.start(lease, signature="C", now=103)

    def test_cost_overrun_is_recorded_and_budget_blocks_further_attempts(self):
        reg = registration(mission_id="paid-mission", worktree="/registered/paid-worktree", cost_budget_microusd=100,
                           max_attempt_cost_microusd=60, paid_authorization_ref="approved/exact-provider-cost")
        ev = evidence(reg)
        self.store.register(reg)
        checkpoint = build_checkpoint(reg, ev.continuity, ev.checkpoint_workspace, saved_at=100,
                                      goal_ref="original/request", verified_done=(), incomplete=("repair",), blockers=(),
                                      next_action="repair", evidence_refs=("receipt",))
        digest = self.store.save_checkpoint(reg, checkpoint)
        lease = self.store.acquire(reg, "holder-a", ev, now=100)
        first = self.store.start_attempt(reg, lease, ev, incident_id="incident-1", mode="repair",
                                        failure_signature="A", checkpoint_sha256=digest, reserved_cost_microusd=60, now=100)
        self.store.record_attempt(lease, first, outcome="failed", failure_signature="B", measured_cost_microusd=120,
                                  receipt_ref="actual-cost-receipt", now=101)
        with self.assertRaisesRegex(RecoveryBlocked, "mission_cost_budget_exhausted"):
            self.store.start_attempt(reg, lease, evidence(reg, 102), incident_id="incident-1", mode="repair",
                                     failure_signature="C", checkpoint_sha256=digest, reserved_cost_microusd=0, now=102)

    def test_registration_cannot_silently_replace_original_authority(self):
        changed = registration(scope_version="v2")
        with self.assertRaisesRegex(RecoveryBlocked, "registered_contract_changed_needs_review"):
            self.store.register(changed)

    def test_no_task_completion_from_stopped_turn_or_attempt_success(self):
        self.assertFalse(verify_acceptance(self.reg, ()).ready)
        fake = tuple(AcceptanceEvidence(self.reg.mission_id, SHA, "v1", criterion, True,
                                        "turn-stopped", "native/turn-completed") for criterion in self.reg.acceptance_criteria)
        self.assertEqual(verify_acceptance(self.reg, fake).reason, "acceptance_not_verified")
        proof = tuple(replace(item, validator="acceptance-gem", evidence_ref="gem/independent-validation") for item in fake)
        self.assertEqual(verify_acceptance(self.reg, proof).reason, "acceptance_verified_kynlo_completion_pending")
        self.assertFalse(hasattr(self.store, "complete_mission"))

    def test_native_commands_are_exact_session_preview_only(self):
        for mode in ("resume", "fork"):
            preview = native_command_preview(self.reg, mode=mode)
            self.assertEqual(preview.argv, ("codex", mode, SESSION, "--cd", self.reg.worktree))
            self.assertFalse(preview.execute_allowed)
            self.assertEqual(preview.execution_state, "preview_only")
        claude = native_command_preview(registration(engine="claude-code"), mode="fork")
        self.assertEqual(claude.argv, ("claude", "--resume", SESSION, "--fork-session"))
        self.assertEqual(claude.cwd, self.reg.worktree)
        with self.assertRaisesRegex(RecoveryBlocked, "explicit_native_session_uuid_required"):
            native_command_preview(registration(native_session_id="latest"))


if __name__ == "__main__":
    unittest.main()
