"""Synthetic owner/decision tests. No native process, network or model call."""
import json
import sqlite3
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from agent_team.decision_worker import DecisionWorker
from agent_team.native_decision import UnavailableOwnerGuard, VerifiedDecision
from agent_team.native_transport import NativeContext, NativeOwnerTransport, SQLiteRecoveryControl, digest
from agent_team.recovery import Attempt, Lease, RecoveryBlocked
from agent_team.restricted_owner import RestrictedOwner, parse_native_result
import test_native_decision as native_fixture

SESSION, TURN = native_fixture.SESSION, native_fixture.TURN


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = native_fixture.NativeDecisionTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        f = self.f
        self.reader = Mock(return_value=f.decision); self.publisher = Mock()
        self.settler = Mock(return_value={'state':'native_turn_finished','turnId':TURN,'missionComplete':False})
        self.factory = lambda observer:NativeOwnerTransport(SQLiteRecoveryControl(f.store),f.ledger,f.proxy,observer,
            clock=lambda:101,socket_check=lambda *args:None)

    def worker(self, **changes):
        f = self.f
        options = dict(holder='synthetic-worker',reader=self.reader,publisher=self.publisher,
                       settler=self.settler,clock=lambda:101,dispatch_enabled=True)
        options.update(changes)
        return DecisionWorker(f.root,f.store,f.reg,f.cp_sha,f.guard,self.factory,**options)

    def test_idle_and_read_only_poll_cannot_create_an_attempt(self):
        self.reader.return_value = None
        self.assertEqual(self.worker().once()['state'],'listening')
        self.reader.assert_called_once_with(self.f.root,mission_id='mission-1')
        self.reader.return_value = self.f.decision
        self.assertEqual(self.worker(dispatch_enabled=False).once()['state'],'decision_ready_read_only')
        self.f.guard.observe.assert_not_called(); self.assertEqual(self.f.proxy.sent,[])

    def test_unavailable_guard_creates_no_lease_attempt_or_publication(self):
        worker = self.worker(); worker.guard = UnavailableOwnerGuard()
        self.assertEqual(worker.once()['reason'],'kynlo_native_owner_guard_unavailable')
        self.assertEqual(self.f.store.db.execute('SELECT count(*) FROM recovery_attempts').fetchone()[0],0)
        self.assertEqual(self.f.store.db.execute('SELECT count(*) FROM recovery_leases').fetchone()[0],0)
        self.publisher.assert_not_called(); self.settler.assert_not_called(); self.assertEqual(self.f.proxy.sent,[])

    def test_verified_continue_resumes_checkpoint_once_then_reconciles_only_receipt(self):
        # Bypass only the synthetic socket filesystem check, not recovery guards.
        import agent_team.decision_worker as module
        real = module.continue_verified_decision
        with patch.object(module,'continue_verified_decision',side_effect=lambda *a,**kw:real(*a,**kw,socket_check=lambda *x:None)):
            worker = self.worker(); result = worker.once()
            self.assertEqual(result['state'],'receipt_published'); self.assertFalse(result['missionComplete'])
            self.settler.assert_called_once(); self.assertEqual(len(self.f.proxy.sent),2)
            self.assertEqual(self.f.proxy.sent[1][1]['input'][0]['text'],self.f.cp.next_action)
            self.assertEqual(worker.once()['state'],'receipt_reconciled_no_resend')
            self.assertEqual(len(self.f.proxy.sent),2); self.settler.assert_called_once()

    def test_other_mission_bad_human_evidence_and_wait_never_dispatch(self):
        for change in ({'missionId':'other'},{'humanEvidenceId':'unverified'}):
            self.reader.return_value = VerifiedDecision(dict(self.f.decision.document,**change),self.f.decision.source_ref)
            self.assertEqual(self.worker().once()['state'],'blocked')
        self.reader.return_value = VerifiedDecision(dict(self.f.decision.document,choice='wait'),self.f.decision.source_ref)
        self.assertEqual(self.worker().once()['state'],'human_choice_recorded')
        self.f.guard.observe.assert_not_called(); self.assertEqual(self.f.proxy.sent,[])

    def test_reserved_unknown_delivery_and_stale_receipt_cannot_resend(self):
        self.f.run_bridge()
        self.assertEqual(self.worker(clock=lambda:132).once()['state'],'already_reserved_no_resend')
        self.publisher.assert_not_called(); self.assertEqual(len(self.f.proxy.sent),2)

    def test_private_exception_body_never_enters_status(self):
        self.reader.side_effect = ValueError('Bearer private-token /Users/private')
        result = self.worker().once()
        self.assertEqual(result['reason'],'private_native_worker_failure')
        self.assertNotIn('Bearer',json.dumps(result)); self.assertEqual(self.f.proxy.sent,[])

    def test_binding_pulse_refreshes_real_hook_revision_before_poll_without_model_call(self):
        import agent_team.decision_worker as module
        real=module.refresh_guarded_checkpoint; f=self.f
        f.guard.observe.return_value=(replace(f.snapshot,evidence=replace(f.evidence,
            continuity=replace(f.evidence.continuity,revision=8))),f.attestation)
        binding=Mock();self.reader.return_value=None
        with patch.object(module,'refresh_guarded_checkpoint',side_effect=lambda *a,**kw:real(*a,**kw,socket_check=lambda *x:None)):
            worker=self.worker(actor_id=SESSION,workspace_id=SESSION,binding_publisher=binding)
            status=worker.once()
        self.assertEqual(status['state'],'listening');self.assertEqual(status['bindingState'],'registered')
        self.assertNotEqual(worker.checkpoint_sha256,f.cp_sha);binding.assert_called_once()
        self.assertEqual(f.proxy.sent,[]);self.publisher.assert_not_called()

    def test_read_only_mode_never_refreshes_or_uploads_binding_even_with_principal(self):
        binding=Mock();self.reader.return_value=None
        result=self.worker(dispatch_enabled=False,actor_id=SESSION,workspace_id=SESSION,binding_publisher=binding).once()
        self.assertEqual(result['state'],'listening');binding.assert_not_called()
        self.f.guard.observe.assert_not_called()

    def test_completed_turn_refreshes_cloud_guard_before_receipt_upload(self):
        import agent_team.decision_worker as module
        real_continue=module.continue_verified_decision; real_refresh=module.refresh_guarded_checkpoint
        events=[]
        binding=Mock(side_effect=lambda *a,**kw:events.append('binding'))
        self.publisher.side_effect=lambda *a,**kw:events.append('receipt')
        with patch.object(module,'continue_verified_decision',side_effect=lambda *a,**kw:real_continue(*a,**kw,socket_check=lambda *x:None)), \
             patch.object(module,'refresh_guarded_checkpoint',side_effect=lambda *a,**kw:real_refresh(*a,**kw,socket_check=lambda *x:None)):
            status=self.worker(actor_id=SESSION,workspace_id=SESSION,binding_publisher=binding).once()
        self.assertEqual(status['state'],'receipt_published')
        self.assertEqual(events,['binding','binding','receipt']);self.assertEqual(len(self.f.proxy.sent),2)

    def test_phone_arm_requires_dispatch_principal_and_real_owner_before_any_call(self):
        phone=Mock()
        with self.assertRaisesRegex(RecoveryBlocked,'explicit_staging_phone_arm'):
            self.worker(dispatch_enabled=False,phone_acceptance=phone)
        with self.assertRaisesRegex(RecoveryBlocked,'explicit_staging_phone_arm'):
            self.worker(phone_acceptance=phone)
        worker=self.worker(actor_id=SESSION,workspace_id=SESSION,phone_acceptance=phone)
        worker.guard=UnavailableOwnerGuard()
        self.assertEqual(worker.once()['state'],'blocked');phone.once.assert_not_called()


class OwnerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.f = native_fixture.NativeDecisionTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        f = self.f; self.receipt = f.run_bridge()
        row = f.store.db.execute('SELECT * FROM recovery_leases').fetchone()
        lease = Lease(row['mission_id'],row['worktree'],row['holder'],row['generation'],row['expires_at'])
        row = f.store.db.execute('SELECT * FROM recovery_attempts').fetchone()
        attempt = Attempt(row['id'],row['mission_id'],row['incident_id'],row['mode'],row['generation'])
        self.owner = RestrictedOwner.__new__(RestrictedOwner)
        o = self.owner; o.store = f.store; o.owner = f.reg.owner; o.root = f.root; o.guard_ref = f.attestation.native_guard_ref
        o.context = NativeContext(f.reg,f.execution,lease,attempt,f.cp_sha,f.snapshot)
        o.binding = Mock(return_value=(f.reg,f.execution)); o.clock = lambda:110
        o.validate_host = Mock(); o.continuity = Mock(return_value=f.evidence.continuity)
        o.job = Mock(pid=55); o.job.poll.return_value = None; o.inflight_request = self.receipt['turnRequestId']
        o.db = sqlite3.connect(':memory:'); self.addCleanup(o.db.close)
        o.db.execute('CREATE TABLE operations(id TEXT,method TEXT,state TEXT)')
        o.db.execute('INSERT INTO operations VALUES(?,?,?)',(o.inflight_request,'turn/start','unknown'))

    def test_owned_child_heartbeat_keeps_same_generation_without_retry_or_lease_takeover(self):
        o = self.owner
        with patch('agent_team.restricted_owner.process_identity',return_value=(o.owner.pid,'synthetic-child')), \
             patch('agent_team.restricted_owner.workspace_snapshot',return_value=self.f.cp.workspace):
            o.heartbeat_native()
        self.f.store.assert_fence(o.context.lease,now=131)
        self.assertEqual(o.context.lease.generation,1)
        self.assertEqual(self.f.store.db.execute('SELECT count(*) FROM recovery_attempt_heartbeats').fetchone()[0],1)
        self.assertEqual(self.f.store.db.execute('SELECT count(*) FROM recovery_attempts').fetchone()[0],1)

    def test_unrelated_unknown_effect_changed_child_and_expired_fence_block_renewal(self):
        o = self.owner
        with patch('agent_team.restricted_owner.workspace_snapshot',return_value=self.f.cp.workspace), \
             patch('agent_team.restricted_owner.process_identity',return_value=(999,'other')):
            with self.assertRaisesRegex(RecoveryBlocked,'child_changed'):o.heartbeat_native()
        o.db.execute("INSERT INTO operations VALUES('other','seed','unknown')")
        with patch('agent_team.restricted_owner.workspace_snapshot',return_value=self.f.cp.workspace), \
             patch('agent_team.restricted_owner.process_identity',return_value=(o.owner.pid,'owned')):
            with self.assertRaisesRegex(RecoveryBlocked,'unreconciled'):o.heartbeat_native()
            o.db.execute("DELETE FROM operations WHERE id='other'"); o.clock=lambda:132
            with self.assertRaisesRegex(RecoveryBlocked,'fenced'):o.heartbeat_native()

    def native_output(self, turn=TURN):
        rows=[{'type':'system','subtype':'init','session_id':SESSION,'model':'synthetic-model','tools':[],'mcp_servers':[]},
              {'type':'result','subtype':'success','session_id':SESSION,'is_error':False,'num_turns':1,'uuid':turn,
               'usage':{'input_tokens':2,'output_tokens':2},'total_cost_usd':.001}]
        path=self.f.root/'native-output.jsonl'; path.write_text('\n'.join(json.dumps(x) for x in rows)); path.chmod(0o600)
        path=self.f.root/'native-result.json'; path.write_text(json.dumps(parse_native_result(rows,session=SESSION))); path.chmod(0o600)
        self.owner.observe=Mock(); self.owner.db.execute("UPDATE operations SET state='acknowledged'")

    def test_only_completed_matching_native_result_settles_attempt_not_mission(self):
        self.native_output()
        terminal=self.owner.settle_turn(self.receipt)
        self.assertEqual(terminal['state'],'native_turn_finished'); self.assertFalse(terminal['missionComplete'])
        self.assertEqual(self.f.store.db.execute('SELECT outcome FROM recovery_attempts').fetchone()[0],'succeeded')
        self.assertEqual(self.f.store.db.execute('SELECT count(*) FROM recovery_leases').fetchone()[0],0)

    def test_wrong_turn_cannot_settle_or_release_the_attempt(self):
        self.native_output(turn=SESSION)
        with self.assertRaisesRegex(RecoveryBlocked,'result_mismatch'):self.owner.settle_turn(self.receipt)
        self.assertEqual(self.f.store.db.execute('SELECT outcome FROM recovery_attempts').fetchone()[0],'started')
        self.assertEqual(self.f.store.db.execute('SELECT count(*) FROM recovery_leases').fetchone()[0],1)


if __name__ == '__main__': unittest.main()
