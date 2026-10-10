"""Deterministic CF3 rules; provider execution is covered separately, never implied here."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from postriff_phase2 import leases
from postriff_phase2.permissions import Membership
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
from postriff_phase2.agent_runtime_v2.task_engine import authz_seam, checkpoints, delegates, errors, flags, model, store

class TaskEngineRules(unittest.TestCase):
    def test_engine_dispatch_uses_registered_specialist_surface(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools, authz, tool_adapter
        from postriff_phase2.agent_runtime_v2.task_engine import executor
        domain_tools.ensure_registered()
        agent = executor.dispatch_agent('image_generate')
        self.assertEqual(agent, 'creative')
        self.assertEqual(authz.tool_surface(tool_adapter.REGISTRY['image_generate'].spec, agent).name, 'specialist')

    def test_library_receipt_tool_has_only_task_surface(self):
        from postriff_phase2.agent_runtime_v2 import capability_registry, domain_tools
        from postriff_phase2.agent_runtime_v2.task_engine import executor
        domain_tools.ensure_registered()
        cap = capability_registry.for_tool('library_metadata_apply')
        self.assertEqual((cap.since, cap.risk, cap.idempotency, cap.data_grants), (2, 'R1', 'receipt_tx', ('library',)))
        self.assertEqual([b.surface for b in capability_registry.bindings(cap.capability_id)], ['task_engine'])
        self.assertEqual(executor.dispatch_agent(cap.name), 'task_engine')

    def test_off_default(self):
        self.assertEqual(flags.mode_for('w',environ={}), 'off')

    def test_empty_allowlist_closed(self):
        self.assertEqual(flags.mode_for('w',environ={'RAFII_AGENT_V2_ENABLED':'1','RAFII_TASK_ENGINE_ENABLED':'1','RAFII_TASK_ENGINE_AUTHORITATIVE':'1'}),'off')

    def test_shadow_explicit(self):
        self.assertEqual(flags.mode_for('w',environ={'RAFII_AGENT_V2_ENABLED':'1','RAFII_TASK_ENGINE_ENABLED':'1','RAFII_TASK_ENGINE_WORKSPACES':'w'}),'shadow')

    def test_config_failure_closed(self):
        self.assertEqual(flags.mode_for('w',SimpleNamespace(task_engine_for=Mock(side_effect=RuntimeError))), 'off')

    def test_cancel_external_stays_open(self):
        s=model.StepFacts('s1','queued',kind='delegate',observes_external=True)
        self.assertEqual(model.derive([s],cancel_requested=True,attempts_left=0)[0],'queued')

    def test_cancel_final_external_partial(self):
        s=model.StepFacts('s1','completed',kind='delegate',observes_external=True)
        self.assertEqual(model.derive([s],cancel_requested=True,attempts_left=0),('cancelled','cancelled_by_person',True))

    def test_partial_not_success(self):
        steps=[model.StepFacts('s1','completed'),model.StepFacts('s2','failed',retry_class='never')]
        state,_,partial=model.derive(steps,cancel_requested=False,attempts_left=24)
        self.assertEqual((state,partial),('failed',True))

    def test_effect_key_replay_and_generation(self):
        tid='12345678-1234-4234-8234-123456789012'
        self.assertEqual(model.effect_key(tid,'s1',1),model.effect_key(tid,'s1',1))
        self.assertNotEqual(model.effect_key(tid,'s1',1),model.effect_key(tid,'s1',2))

    def test_campaign_undo_digest_rejects_intervening_link_cycle(self):
        from postriff_phase2.agent_runtime_v2.task_engine import compensation
        state={'raffi':{'campaignPlanning':{'campaigns':[{'id':'c1','version':1,'items':[],'itemLog':[]}]}}}
        inverse=compensation.INVERSES['campaign_unlink']
        before=compensation.digest_of(state,inverse,'campaign','c1')
        state['raffi']['campaignPlanning']['campaigns'][0]['itemLog']=[{'op':'link','id':'d1','at':1},{'op':'unlink','id':'d1','at':2}]
        self.assertNotEqual(before,compensation.digest_of(state,inverse,'campaign','c1'))

    def test_digest_principal_binding(self):
        self.assertNotEqual(model.request_digest('a',{'x':1}),model.request_digest('b',{'x':1}))
        self.assertEqual(model.input_digest('x',{'b':2,'a':1}),model.input_digest('x',{'a':1,'b':2}))

    def test_manual_unknown_never_retries(self):
        out=leases.reaped(receipt_done=False,receipt_verified=False,retry_class='manual',attempts=1,max_attempts=3,task_attempts_left=24)
        self.assertEqual((out.state,out.reason_code),('failed','outcome_unknown'))

    def test_committed_receipt_replays(self):
        self.assertEqual(leases.reaped(receipt_done=True,receipt_verified=True,retry_class='manual',attempts=1,max_attempts=1,task_attempts_left=0),'completed')

    def test_unverified_receipt_not_completed(self):
        self.assertEqual(leases.reaped(receipt_done=True,receipt_verified=False,retry_class='auto',attempts=1,max_attempts=3,task_attempts_left=24).state,'failed')

    def test_retry_cap_and_backoff(self):
        self.assertEqual(leases.classify('timeout',retry_class='auto',attempts=3,max_attempts=3).state,'failed')
        self.assertEqual(leases.backoff_seconds(1,rand=lambda:0),30)
        self.assertLessEqual(leases.backoff_seconds(20,rand=lambda:1),1125)

    def test_error_contract(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/agent_tasks/contracts/error-codes.json').read_text())
        self.assertEqual(sorted(fixture['errors'].items()),sorted((v['code'],v['http']) for v in errors.public_table()))

    def test_private_receipt_no_content(self):
        out=store.receipt_result({'prompt':'secret','text':'secret','checks':[],'changedRefs':[]})
        self.assertNotIn('prompt',out);self.assertNotIn('text',out)

    def test_provider_revocation_mapping(self):
        self.assertEqual(authz_seam.map_reason('provider_not_connected',allowed_before=True),'provider_disconnected')
        self.assertEqual(authz_seam.map_reason('category_off',allowed_before=True),'permission_revoked')

    def test_ui_action_unverified_never_completes(self):
        for verified in (False,None):
            cur=Mock();cur.fetchone.return_value=('done',{'outcome':'applied','verified':verified})
            out=delegates._ui_action(cur,{'workspaceId':'w'},{'delegateId':'i'})
            self.assertEqual((out.state,out.reason_code),('failed','outcome_unknown'))

    def test_ui_action_verified_completes(self):
        cur=Mock();cur.fetchone.return_value=('done',{'outcome':'applied','verified':True})
        self.assertEqual(delegates._ui_action(cur,{'workspaceId':'w'},{'delegateId':'i'}).state,'completed')

    def test_installed_authz_error_does_not_fallback(self):
        with patch('importlib.import_module',side_effect=ModuleNotFoundError("broken",name='dependency')):
            with self.assertRaises(ModuleNotFoundError):authz_seam._cf2()

    def test_all_delegate_types_have_adapters(self):
        self.assertEqual(set(delegates.ADAPTERS),set(model.DELEGATE_TYPES))

if __name__=='__main__':unittest.main()
