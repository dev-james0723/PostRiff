"""Synthetic private Trial receipt recovery and immutable asset source boundaries."""
import copy
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_storage import SupabaseStorage
from postriff_phase2.oauth import OAuthService
from test_pinterest_private_trial import fixture as trial_fixture, manifest as trial_manifest, pin, PIN, W
from test_pinterest_trial_visibility import fixture, manifest, readback, PIN as VISIBILITY_PIN
from test_hosted_wave1_connectors import ok


class PinterestPrivateTrialRecovery(unittest.TestCase):
    def test_signed_source_matches_only_exact_approved_workspace_immutable_object(self):
        storage=SupabaseStorage('https://synthetic-project.supabase.co','SYNTHETIC_KEY_NOT_REAL_123',send=Mock())
        social=HostedSocial(None,{},assets=SimpleNamespace(storage=storage))
        object_name='a'*32+'-'+'b'*64+'.jpg'
        m={'workspaceId':W,'media':[{'id':'asset','objectName':object_name}]}
        source=storage.project_url+'/storage/v1/object/sign/postriff-private/'+W+'/media/'+object_name+'?token=SYNTHETIC'
        self.assertTrue(social._pinterest_source_matches(m,source))
        for changed in (source.replace('synthetic-project','another-project'),source.replace(W,'00000000-0000-0000-0000-000000000599'),
                        source.replace(object_name,'c'*32+'-'+'b'*64+'.jpg'),source+'&extra=1',source.replace('?token=SYNTHETIC','?token='),source+'#other',None):
            with self.subTest(changed=changed):self.assertFalse(social._pinterest_source_matches(m,changed))
        storage.send.assert_not_called()

    def test_known_create_response_is_journaled_before_returning_to_workspace_proof(self):
        _,p,t=trial_fixture([ok({'id':PIN},201)]);m=trial_manifest();body=pin(m);acks=[]
        p.private_trial_ack_gate=lambda *args:acks.append(args)
        with p.private_trial_dispatch(m,body):
            result=p.api(t,'POST','/v5/pins',body=body)
            self.assertEqual(acks,[(p.trial_policy,m['idempotencyKey'],PIN)])
            self.assertEqual(result['body']['id'],PIN)
        self.assertEqual(len(p.transport.calls),1)

    def test_reconciliation_recovers_known_journal_id_without_a_second_post(self):
        social,p,_=fixture();m=manifest();p.api.return_value=readback(m)
        p.private_trial_recover_reference=Mock(return_value=VISIBILITY_PIN)
        result=social.reconcile(m,{'state':'uncertain'})
        self.assertEqual((result['state'],result['reference'],result['visibility']),('verified',VISIBILITY_PIN,'creator_only_trial'))
        p.private_trial_recover_reference.assert_called_once_with(p.trial_policy,m['idempotencyKey'])
        self.assertEqual(p.api.call_args.args[1:3],('GET','/v5/pins/'+VISIBILITY_PIN))
        p.api.reset_mock();p.private_trial_recover_reference.return_value=None
        self.assertEqual(social.reconcile(m,{'state':'uncertain'})['state'],'uncertain');p.api.assert_not_called()

    def test_pin_gate_recovers_only_matching_intent_among_other_jobs_and_stops_on_disconnect(self):
        _,p,_=trial_fixture();m=trial_manifest();job={'manifest':m,'state':'uncertain'}
        state={'phase2':{'jobs':[{'state':'verified','manifest':{'platform':'Discord'}},job],
                        'channels':[{'id':'connection','providerAccountId':p.trial_policy.provider_account_id,'revoked':False}]}}
        class Repo:
            @contextmanager
            def connection_factory(self):yield self
            @contextmanager
            def cursor(self):yield self
            def execute(self,sql,args):self.args=args
            def fetchone(self):return(copy.deepcopy(state),)
        service=OAuthService.__new__(OAuthService);service.providers={'pinterest':p};service.repository=Repo()
        import time
        service.clock=time.time
        p.private_trial_recover_reference=lambda policy,intent:PIN if intent==m['idempotencyKey'] else None
        self.assertTrue(service._pinterest_private_pin_allowed(PIN));self.assertFalse(service._pinterest_private_pin_allowed('1111111'))
        state['phase2']['channels'][0]['revoked']=True
        self.assertFalse(service._pinterest_private_pin_allowed(PIN))
