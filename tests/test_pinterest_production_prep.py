"""Synthetic security contracts; no live Pinterest consent, traffic or publication."""
import copy
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import contextmanager
from postriff_alpha.domain import AlphaError
from postriff_phase2 import pinterest_agent, publish_options
from postriff_phase2.pinterest_safety import revoke_authority, https_url
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.wave3_connectors import PinterestProvider
from postriff_phase2.oauth import OAuthService
from postriff_phase2.contracts import digest
from postriff_phase2.hosted_worker import defer_pinterest_budget
from test_hosted_wave1_connectors import Wire, ok
import test_hosted_wave3_connectors as wave3
IMAGE, manifest = wave3.IMAGE, wave3.manifest

IDENTITY = ok({'id': '1234567', 'username': 'mock', 'account_type': 'BUSINESS'})
BOARD = {'id': '1234567', 'name': 'Synthetic', 'privacy': 'PUBLIC'}


class PinterestProductionSafety(unittest.TestCase):
    def provider(self, responses=()):
        p = PinterestProvider('1615884', 'MOCK', sandbox=True, transport=Wire(responses))
        return p, p._grant({'access_token': 'MOCK', 'scope': 'user_accounts:read boards:read pins:read pins:write'})['accessToken']

    def test_stable_identity_is_required(self):
        for body in ({'username': 'mutable'}, {'username': 'mutable', 'id': 'bad'}):
            p, token = self.provider([ok(body)])
            with self.assertRaises(AlphaError): p.identity(token)

    def test_account_eligibility_is_safe_and_actionable(self):
        p, token = self.provider([ok({'code': 403, 'message': 'PINNER_DATA_ACCESS_DENIED', 'detail': 'MOCK SECRET'}, 403)])
        with self.assertRaises(AlphaError) as caught: p.destinations(token)
        self.assertEqual(caught.exception.code, 'pinterest_account_ineligible')
        self.assertNotIn('MOCK SECRET', str(caught.exception))

    def test_private_ad_only_and_unknown_boards_are_not_eligible(self):
        p, token = self.provider([ok({'items': [BOARD, {**BOARD, 'id': '2', 'privacy': 'SECRET'},
            {**BOARD, 'id': '3', 'is_ads_only': True}, {'id': '4'}]})])
        self.assertEqual([b['eligible'] for b in p.destinations(token)], [True, False, False, False])

    def test_sections_are_bound_to_accessible_board(self):
        p, token = self.provider([ok({'items': [BOARD]}), ok({'items': [{'id': '7654321', 'name': 'Music'}]})])
        self.assertEqual(p.sections(token, '1234567')[0]['boardId'], '1234567')
        self.assertIn('/v5/boards/1234567/sections?', p.transport.calls[1]['url'])
        other, token = self.provider([ok({'items': []})])
        with self.assertRaises(AlphaError): other.sections(token, '1234567')
        self.assertEqual(len(other.transport.calls), 1)

    def test_invalid_pagination_does_not_return_partial_list(self):
        for body in ({'items': [BOARD], 'bookmark': 22}, {'items': [{'id': 'bad'}]}):
            p, token = self.provider([ok(body)])
            with self.assertRaises(AlphaError): p.destinations(token)

    def test_image_and_pin_metadata_validation(self):
        for media, options, text in [([{**IMAGE[0], 'mime': 'image/svg+xml'}], {'boardId': '1'}, 'x'),
            ([{**IMAGE[0], 'bytes': 10485761}], {'boardId': '1'}, 'x'),
            ([{**IMAGE[0], 'alt': 'a'*501}], {'boardId': '1'}, 'x'),
            (IMAGE, {'boardId': '1', 'boardSectionId': '../2'}, 'x'),
            (IMAGE, {'boardId': '1'}, 'x'*801)]:
            with self.assertRaises(AlphaError): publish_options.normalize('Pinterest', options, media, text)
        self.assertEqual(publish_options.normalize('Pinterest', {'boardId': '1', 'boardSectionId': '2'}, IMAGE, 'x')['boardSectionId'], '2')

    def test_https_link_and_image_sources_reject_unsafe_targets(self):
        for url in ['http://example.com', 'https://user:pass@example.com', 'https://127.0.0.1',
                    'https://[::1]', 'https://localhost', 'https://example.com:bad', 'https://example.com\n']:
            self.assertFalse(https_url(url), url)
        self.assertTrue(https_url('https://example.com/score?q=x'))

    def test_public_connections_stay_off_and_pilot_is_readonly(self):
        base = {'POSTRIFF_OAUTH_PINTEREST_CLIENT_ID':'1615884', 'POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET':'MOCK'}
        self.assertFalse(registry_from_environment(base)['pinterest'].execution_enabled)
        self.assertFalse(registry_from_environment({**base,'POSTRIFF_OAUTH_PINTEREST_REVIEWED':'true'})['pinterest'].execution_enabled)
        public={**base,'POSTRIFF_OAUTH_PINTEREST_REVIEWED':'true','POSTRIFF_OAUTH_PINTEREST_ENABLED':'true','POSTRIFF_OAUTH_PINTEREST_VERIFIED':'true'}
        self.assertFalse(registry_from_environment(public)['pinterest'].execution_enabled)
        self.assertTrue(registry_from_environment({**public,'POSTRIFF_OAUTH_PINTEREST_POLICY_APPROVED':'true'})['pinterest'].execution_enabled)
        trial = registry_from_environment({**base,'POSTRIFF_PINTEREST_SANDBOX':'true','POSTRIFF_PINTEREST_TRIAL_READONLY':'1',
            'POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID':'00000000-0000-0000-0000-000000000501',
            'POSTRIFF_PINTEREST_TRIAL_ACTOR_ID':'00000000-0000-0000-0000-000000000502',
            'POSTRIFF_PINTEREST_TRIAL_USERNAME':'mock',
            'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(int(time.time())+3600)}, transport=Wire([]))['pinterest']
        self.assertTrue(trial.execution_enabled)
        token = trial._grant({'access_token':'MOCK','scope':'user_accounts:read'})['accessToken']
        with self.assertRaises(AlphaError): trial.api(token, 'POST', '/v5/pins', body={})
        self.assertEqual(trial.transport.transport.calls, [])

    def test_refresh_expiry_and_nonfinite_grants_fail_closed(self):
        p, _ = self.provider()
        grant = p._grant({'access_token':'MOCK','refresh_token':'RT','scope':'user_accounts:read','refresh_token_expires_in':60})
        refresh = json.loads(grant['refreshToken']); refresh['expiresAt'] = 1
        with self.assertRaises(AlphaError): p.refresh(json.dumps(refresh))
        for expires in [float('nan'), float('inf')]:
            with self.assertRaises(AlphaError): p._grant({'access_token':'MOCK','scope':'user_accounts:read','expires_in':expires})
        self.assertEqual(p.transport.calls, [])

    def test_account_drift_prevents_a_pin_post(self):
        wire = Wire([])
        social = wave3.PinterestPublishing().social(wire)
        wire.responses[0] = ok({'id':'9999999','username':'other'})
        result = social.submit(manifest('Pinterest','1234567',media=IMAGE, options=wave3.PinterestPublishing.options))
        self.assertEqual(result['state'], 'held')
        self.assertEqual(len(wire.calls), 1)

    def test_post_timeout_remains_uncertain_and_cannot_be_treated_as_unposted(self):
        class Interrupted(Wire):
            def __call__(self, method, url, **kw):
                if method == 'POST':
                    self.calls.append({'method':method,'url':url})
                    raise AlphaError('The provider is temporarily unreachable.',503)
                return super().__call__(method,url,**kw)
        wire=Interrupted([ok({'items':[BOARD]})])
        social=wave3.PinterestPublishing().social(wire)
        result=social.submit(manifest('Pinterest','1234567',media=IMAGE,options=wave3.PinterestPublishing.options))
        self.assertEqual(result['state'],'uncertain')
        self.assertEqual(sum(c['method']=='POST' for c in wire.calls),1)

    def test_pre_post_budget_wait_keeps_job_scheduled_without_any_post(self):
        wire=Wire([ok({'code':429,'message':'limit'},429)])
        social=wave3.PinterestPublishing().social(wire)
        result=social.submit(manifest('Pinterest','1234567',media=IMAGE,options=wave3.PinterestPublishing.options))
        self.assertEqual(result['state'],'scheduled')
        self.assertTrue(result['pinterestBudgetDeferred'])
        self.assertTrue(all(c['method']=='GET' for c in wire.calls))
        job={'manifest':{'platform':'Pinterest','idempotencyKey':'key'},'attempts':[{'idempotencyKey':'key'}]}
        self.assertTrue(defer_pinterest_budget(job,result,False))
        self.assertEqual(job['attempts'],[])
        self.assertEqual(job['pinterestBudgetDeferrals'],1)
        self.assertFalse(defer_pinterest_budget(job,result,True))
        job['providerReference']='987654321'
        self.assertFalse(defer_pinterest_budget(job,result,False))

    def test_readback_checks_all_approved_fields_without_any_retry_post(self):
        body = {'id':'987654321','board_id':'1234567','description':'Rehearsal notes','title':'Score',
                'link':'https://rafii.example/score','media':{'media_type':'image'}}
        for key, changed in [('id','987654322'),('board_id','7654321'),('title','Other'),('description','Other'),
                             ('link','https://wrong.example'),('board_section_id','7654321'),('media',{'media_type':'video'})]:
            wire = Wire([ok({**body,key:changed})]); social = wave3.PinterestPublishing().social(wire)
            result = social.reconcile(manifest('Pinterest','1234567',options=wave3.PinterestPublishing.options),{'providerReference':'987654321'})
            self.assertEqual(result['state'], 'uncertain', key)
            self.assertTrue(all(c['method']=='GET' for c in wire.calls))

    def test_malformed_pin_reference_causes_no_provider_request(self):
        wire = Wire([]); social = wave3.PinterestPublishing().social(wire)
        result = social.reconcile(manifest('Pinterest','1234567',options=wave3.PinterestPublishing.options), {'providerReference':'../oauth/token'})
        self.assertEqual(result['state'],'uncertain'); self.assertEqual(wire.calls,[])

    def test_tenant_cannot_discover_another_workspaces_board_sections(self):
        p, _ = self.provider([])
        service, _ = wave3.ServiceChecks().service({'pinterest':p})
        with self.assertRaises(AlphaError): service.destinations('other-workspace','session','conn',board_id='1234567')
        self.assertEqual(p.transport.calls, [])


class PinterestRevocationAndAgent(unittest.TestCase):
    def dispatch(self, *, canceled=False, lease='lease', token='MOCK', current=True):
        manifest = {'workspaceId':'w','channelId':'c','idempotencyKey':'key','platform':'Pinterest',
                    'providerAccountId':'1234567','actor':'owner','expiresAt':1000}
        job = {'state':'submitting','manifest':manifest,'approvalDigest':digest(manifest),'approvedBy':'owner',
               'leaseId':lease,'leaseOwner':'worker','leaseUntil':200,'cancelRequested':canceled,'events':[]}
        state = {'phase2':{'channels':[{'id':'c','platform':'Pinterest'}],'jobs':[job]}}
        updates=[]
        class Cursor:
            def execute(self, sql, params):
                if sql.startswith('SELECT state'): self.row=(state,)
                elif sql.startswith('SELECT m.role'): self.row=('owner',True)
                elif sql.startswith('SELECT access_ciphertext'): self.row=(token,'key','1234567')
                elif sql.startswith('UPDATE public.pr_workspaces'): updates.append(params)
                else: raise AssertionError(sql)
            def fetchone(self): return self.row
            def __enter__(self): return self
            def __exit__(self,*args): pass
        class DB:
            def cursor(self): return Cursor()
            def __enter__(self): return self
            def __exit__(self,*args): pass
        repo=SimpleNamespace(connection_factory=DB)
        engine=SimpleNamespace(current=lambda *a:current,channel_state=lambda *a:'Ready for posting')
        service=OAuthService(repo,SimpleNamespace(engine=engine),SimpleNamespace(decrypt=lambda x,k:x),{'pinterest':PinterestProvider('1615884','MOCK',sandbox=True,transport=Wire([]))},'https://example.com',clock=lambda:100)
        return service,manifest,job,updates

    def test_dispatch_checks_live_lease_and_cancel_before_external_action(self):
        for values in ({'canceled':True},{'lease':'new-lease'},{'token':'ROTATED'},{'current':False}):
            service,manifest,_job,updates=self.dispatch(**values)
            called=False
            with patch('postriff_phase2.billing.require_publishing'), self.assertRaises(AlphaError):
                with service.pinterest_dispatch(manifest,'MOCK',{'leaseId':'lease','leaseOwner':'worker'}): called=True
            self.assertFalse(called);self.assertEqual(updates,[])

    def test_paused_provider_stops_final_dispatch(self):
        service,manifest,_job,updates=self.dispatch()
        service.providers['pinterest'].execution_enabled=False
        with self.assertRaises(AlphaError) as caught:
            with service.pinterest_dispatch(manifest,'MOCK',{'leaseId':'lease','leaseOwner':'worker'}):pass
        self.assertEqual(caught.exception.status,503)
        self.assertEqual(updates,[])

    def test_known_pin_id_is_saved_before_dispatch_lock_releases(self):
        service,manifest,job,updates=self.dispatch()
        with patch('postriff_phase2.billing.require_publishing'):
            with service.pinterest_dispatch(manifest,'MOCK',{'leaseId':'lease','leaseOwner':'worker'}) as proof:
                proof['pinId']='987654321'
        self.assertEqual(job['providerReference'],'987654321')
        self.assertEqual(len(updates),1)
        self.assertEqual(job['state'],'submitting')  # creation receipt does not imply read-back or public visibility

    def test_disconnect_cancels_future_jobs_and_fences_inflight_work(self):
        jobs = [{'state':s,'manifest':{'channelId':'c','platform':'Pinterest'},'leaseId':'old','events':[]}
                for s in ('scheduled','approved','claimed','held','submitting','provider_accepted','uncertain','verified')]
        other = {'state':'scheduled','manifest':{'channelId':'other','platform':'Pinterest'}}
        state = {'phase2':{'channels':[{'id':'c','platform':'Pinterest'}], 'reviews':[{'manifest':{'channelId':'c','platform':'Pinterest'},'status':'approved'}],
                          'jobs':jobs+[other]},'raffi':{'campaignPlanning':{'recurringTasks':[{'destinations':[{'channelId':'c'}],'status':'active','pausedUntil':10}]}}}
        result = revoke_authority(state,'c',42)
        self.assertEqual(result, {'canceledJobs':4,'uncertainJobs':3})
        self.assertTrue(state['phase2']['channels'][0]['revoked'])
        self.assertEqual(state['phase2']['reviews'][0]['status'],'stale')
        self.assertTrue(all(j['leaseId'] is None for j in jobs[:-1]))
        self.assertEqual(other['state'],'scheduled')
        task = state['raffi']['campaignPlanning']['recurringTasks'][0]
        self.assertEqual(task['status'],'paused'); self.assertNotIn('pausedUntil',task)

    def test_agent_discovery_needs_current_unquoted_request_and_exact_connection(self):
        calls=[]
        ctx = SimpleNamespace(request_text='Show my Pinterest boards',workspace_id='tenant',token='session',
            snapshot=lambda:{'state':{'phase2':{'channels':[{'id':'c','platform':'Pinterest'}]}}},
            service=SimpleNamespace(oauth=SimpleNamespace(destinations=lambda *a,**kw:calls.append((a,kw)) or {'destinations':[BOARD]})))
        with patch.object(pinterest_agent,'enabled',return_value=True):
            self.assertTrue(pinterest_agent.boards(ctx,{'connectionId':'c'})['verified'])
            self.assertEqual(calls[0][0],('tenant','session','c'))
            for text in ['Do not read Pinterest boards','"Show my Pinterest boards"','```\nShow Pinterest boards\n```']:
                ctx.request_text=text
                with self.assertRaises(AlphaError): pinterest_agent.boards(ctx,{'connectionId':'c'})
            ctx.request_text='Show Pinterest boards'
            with self.assertRaises(AlphaError): pinterest_agent.boards(ctx,{'connectionId':'other'})
        self.assertEqual(len(calls),1)

    def test_agent_feature_flag_blocks_even_with_previous_context(self):
        with patch.object(pinterest_agent,'enabled',return_value=False), self.assertRaises(AlphaError):
            pinterest_agent.boards(SimpleNamespace(),{'connectionId':'c'})

    def test_user_feature_flag_cannot_waive_provider_data_permission(self):
        with patch('postriff_phase2.coworker.flags._source',return_value={'POSTRIFF_PINTEREST_AGENT_ENABLED':'1'}):
            self.assertFalse(pinterest_agent.enabled())


if __name__ == '__main__': unittest.main()
