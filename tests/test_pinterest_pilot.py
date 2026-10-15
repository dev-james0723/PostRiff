"""Read-only Trial containment contracts. Synthetic accounts and transport only."""
import json
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from postriff_alpha.domain import AlphaError
from postriff_phase2.pinterest_pilot import PinterestTrialPolicy
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.wave3_connectors import PinterestProvider
from test_hosted_wave1_connectors import Wire, ok
import test_hosted_wave3_connectors as wave3


class PinterestPilot(unittest.TestCase):
    def configured(self):
        return {'POSTRIFF_OAUTH_PINTEREST_CLIENT_ID':'1615884','POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET':'MOCK',
            'POSTRIFF_PINTEREST_SANDBOX':'true','POSTRIFF_PINTEREST_TRIAL_READONLY':'1',
            'POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID':'00000000-0000-0000-0000-000000000501',
            'POSTRIFF_PINTEREST_TRIAL_ACTOR_ID':'00000000-0000-0000-0000-000000000502',
            'POSTRIFF_PINTEREST_TRIAL_USERNAME':'mock',
            'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(int(time.time())+3600)}

    def service(self, responses=()):
        provider = PinterestProvider('1615884','MOCK',sandbox=True,transport=Wire(responses))
        provider.trial_readonly = True
        provider.trial_policy = PinterestTrialPolicy('workspace','owner','mock',int(time.time())+3600)
        service, repo = wave3.ServiceChecks().service({'pinterest':provider})
        return service, repo, provider

    def test_no_incomplete_or_wildcard_pilot_can_mount(self):
        base = self.configured()
        keys = [key for key in base if key.startswith('POSTRIFF_PINTEREST_TRIAL_') and key != 'POSTRIFF_PINTEREST_TRIAL_READONLY']
        for key in keys:
            for value in ['', '*', 'one,two']:
                registry = registry_from_environment({**base,key:value}, transport=Wire([]))
                self.assertNotIn('pinterest',registry,(key,value))
        for expiry in [int(time.time())-1,int(time.time())+90000]:
            self.assertNotIn('pinterest',registry_from_environment({**base,'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(expiry)},transport=Wire([])))

    def test_pilot_never_opens_public_gates(self):
        registry = registry_from_environment(self.configured(),transport=Wire([]))
        self.assertTrue(registry['pinterest'].execution_enabled)
        self.assertTrue(registry['pinterest'].quota_required)
        self.assertFalse(registry.diagnostics['pinterest']['productionEnabled'])
        disabled=registry_from_environment({**self.configured(),'POSTRIFF_OAUTH_PINTEREST_DISABLED':'true'},transport=Wire([]))
        self.assertFalse(disabled['pinterest'].execution_enabled)

    def test_board_consent_is_minimal_and_publish_schedule_are_denied_before_network(self):
        service,repo,p=self.service()
        started=service.start('workspace','session','pinterest','boards_read')
        self.assertEqual(set(started['scopes']),{'user_accounts:read','boards:read'})
        self.assertEqual(parse_qs(urlparse(started['authorizeUrl']).query)['scope'],['user_accounts:read,boards:read'])
        for capability in ['publish','schedule']:
            with self.assertRaises(AlphaError) as caught:service.start('workspace','session','pinterest',capability)
            self.assertEqual(caught.exception.code,'pinterest_trial_readonly')
        self.assertEqual(p.transport.calls,[])
        view=next(v for v in service.provider_catalog() if v['id']=='pinterest')
        self.assertTrue(view['capabilities']['boards_read'])
        self.assertFalse(view['capabilities']['publish'])

    def test_callback_after_allowlist_change_does_not_exchange(self):
        service,repo,p=self.service()
        started=service.start('workspace','session','pinterest','boards_read')
        state=parse_qs(urlparse(started['authorizeUrl']).query)['state'][0]
        p.trial_policy=PinterestTrialPolicy('different','owner','mock',int(time.time())+3600)
        with self.assertRaises(AlphaError):service.complete('workspace','session','pinterest',state,'MOCK-CODE')
        self.assertEqual(p.transport.calls,[])

    def test_same_workspace_other_actor_cannot_start_or_read_custody(self):
        service,repo,p=self.service()
        original=repo.transaction
        @contextmanager
        def other_actor(token,workspace):
            with original(token,workspace) as (cur,row,_):yield cur,row,'different-actor'
        repo.transaction=other_actor
        with self.assertRaises(AlphaError):service.start('workspace','session','pinterest','boards_read')
        wave3.ServiceChecks().credential(service,repo,'pinterest','1234567',
            json.loads(p._grant({'access_token':'MOCK','scope':'user_accounts:read boards:read'})['accessToken']),
            ['user_accounts:read','boards:read'])
        with patch.object(service,'token_for_worker') as custody:
            with self.assertRaises(AlphaError):service.destinations('workspace','session','conn')
            custody.assert_not_called()
        self.assertEqual(p.transport.calls,[])

    def test_unknown_account_cannot_return_boards(self):
        service,repo,p=self.service([ok({'id':'1234567','username':'different'})])
        token=p._grant({'access_token':'MOCK','scope':'user_accounts:read boards:read'})['accessToken']
        with self.assertRaises(AlphaError) as caught:p.destinations(token)
        self.assertEqual(caught.exception.code,'pinterest_trial_account_mismatch')
        self.assertEqual(len(p.transport.calls),1)
        self.assertTrue(p.transport.calls[0]['url'].endswith('/user_account'))

    def test_broader_tokens_and_identity_only_board_access_fail_before_network(self):
        service,repo,p=self.service()
        with self.assertRaises(AlphaError):p._grant({'access_token':'MOCK','scope':'user_accounts:read pins:write'})
        token=p._grant({'access_token':'MOCK','scope':'user_accounts:read'})['accessToken']
        with self.assertRaises(AlphaError):p.api(token,'GET','/v5/boards')
        with self.assertRaises(AlphaError):p.sections(token,'1234567')
        with self.assertRaises(AlphaError):
            with service.pinterest_dispatch({},token,{}):pass
        self.assertEqual(p.transport.calls,[])

    def test_every_token_operation_is_budgeted_and_budget_failure_sends_nothing(self):
        service,repo,p=self.service()
        p.quota_required=True
        def exhausted(*args):raise AlphaError('Budget exhausted',429)
        p.rate_gate=exhausted
        with self.assertRaises(AlphaError):p.exchange('MOCK-CODE','unused','https://synthetic.invalid/callback')
        grant=p._grant({'access_token':'MOCK','refresh_token':'MOCK-RT','scope':'user_accounts:read'})
        with self.assertRaises(AlphaError):p.refresh(grant['refreshToken'])
        self.assertEqual(p.transport.calls,[])

    def test_expired_pilot_blocks_before_transport_and_profile_images_are_omitted(self):
        service,repo,p=self.service([ok({'id':'1234567','username':'mock','profile_image':'https://example.com/private.png'})])
        token=p._grant({'access_token':'MOCK','scope':'user_accounts:read'})['accessToken']
        self.assertIsNone(p.identity(token)['pictureUrl'])
        p.trial_policy=PinterestTrialPolicy('workspace','owner','mock',int(time.time())-1)
        with self.assertRaises(AlphaError):p.identity(token)
        self.assertEqual(len(p.transport.calls),1)
