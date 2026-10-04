"""Offline runtime bindings: injected HTTP only; all default switches stay off."""
from contextlib import contextmanager
from dataclasses import asdict
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_trend_contracts as F
from postriff_phase2.growth.trends import config, worker
from postriff_phase2.growth.trends.providers import runtime as R, mastodon, web
from postriff_phase2.growth.trends.contracts import ContractError


class Store:
    def __init__(self, state=None, policies=()):
        self.state = state
        self.policies = list(policies)
        self.queries = []
        self.hosted = SimpleNamespace(billing=SimpleNamespace(pricing_v2_enabled=True),clock=lambda:1_000_000)

    @contextmanager
    def transaction(self):
        cursor = Mock(description=[])
        def execute(sql, args=None):
            self.queries.append((sql, args))
            if '/* trends:funding */' in sql:
                cursor.fetchone.return_value = {'plan':'studio', 'credit_policy':'credits-candidate-2026-09-23-v1'}
            elif sql.startswith('SELECT id FROM public.pr_workspaces'):
                cursor.fetchone.return_value = (args[0],)
            elif sql.startswith('SELECT status,extract'):
                cursor.fetchone.return_value = ('active',None,False,None,'studio-v1')
            elif sql.startswith('SELECT plan_terms_id'):
                cursor.fetchone.return_value = ('studio-v1',)
            else:
                cursor.fetchone.return_value = {'state':self.state} if self.state is not None else None
        cursor.execute.side_effect = execute
        cursor.fetchall.return_value = self.policies
        yield cursor


class Response(io.BytesIO):
    status = 200
    headers = {}


class RuntimeBindings(F.OfflineTest):
    def test_registry_uses_reviewed_instance_and_exact_contract(self):
        p = asdict(F.policy(provider_id='mastodon', operation='public_timeline'))
        p['instance_url'] = 'https://social.example'
        store = Store(policies=[{'manifest':p, 'provider_contract_version':mastodon.VERSION}])
        registry = worker.configured_registry(store)
        cap, policy, adapter = registry.resolve('mastodon','public_timeline',F.SCOPE,p['version'],at=F.NOW)
        self.assertEqual(cap.endpoint, 'https://social.example/api/v1/timelines/public')
        with patch.object(mastodon, 'collect', return_value='synthetic') as collect:
            self.assertEqual(adapter(policy=policy,cursor={},now=F.NOW,
                payload={'coverage_epoch':'e','max_items':2,'instance_url':'https://evil.invalid'},reservation_microusd=10),'synthetic')
        self.assertEqual(collect.call_args.kwargs['instance'],p['instance_url'])
        self.assertIsNone(R.binding(store,p,'unreviewed-contract'))
        self.assertFalse(config.dispatch_allowed('mastodon','public_timeline',{}))

    def test_instance_rejects_credential_port_and_private_host_at_dispatch(self):
        for url in ('http://example.com','https://user@example.com','https://example.com:8443','https://example.com/api','https://example.com?q=x'):
            with self.subTest(url=url), self.assertRaises(ValueError): mastodon.capability(url)
        with self.assertRaises(ContractError):
            mastodon.collect(instance='https://127.0.0.1', policy=F.policy(provider_id='mastodon',operation='public_timeline'),
                enabled=True,entitlement_current=True,received_at=F.NOW,available_at=F.NOW,
                coverage_epoch='e',reservation_microusd=10)

    def test_web_consent_is_live_workspace_state_not_job_input(self):
        policy = F.policy(provider_id='web',operation='corroborate')
        with patch.object(R.research,'allowed',return_value=True):
            for state in (None,{}, {'researchEgress':{'web':False}}, {'researchEgress':{'web':True},'accountDeletion':{'at':1}}):
                with self.subTest(state=state), self.assertRaises(ContractError):R.workspace_state(Store(state),policy)
            state = {'researchEgress':{'web':True}}
            self.assertEqual(R.workspace_state(Store(state),policy),state)
            with self.assertRaises(ContractError): R.workspace_state(Store(state),F.policy(scope_key='shared:fixture'))

    def test_web_binding_rejects_fallback_provider_and_endpoint_override(self):
        p = asdict(F.policy(provider_id='web',operation='corroborate'))
        p.update(broker_provider_id='exa_search',corroboration_endpoint=R.research.DEFAULT_EXA_URL)
        self.assertEqual(R.binding(Store(),p,web.VERSION)[0],web.CAPABILITY)
        for change in ({'broker_provider_id':'other'},{'corroboration_endpoint':'https://other.invalid/mcp'}):
            with self.subTest(change=change),self.assertRaises(ContractError):R.binding(Store(),{**p,**change},web.VERSION)

    def test_exa_two_requests_share_byte_time_cap_and_never_redirect(self):
        backend = R.BoundedExaSearch(R.research.DEFAULT_EXA_URL,clock=lambda:1)
        opener = Mock()
        opener.open.side_effect = [Response(b'{}'),Response(b'{}')]
        with patch.object(R,'safe_url',return_value=backend.url), patch.object(R.urllib.request,'build_opener',return_value=opener) as make:
            backend._post({},b'{}');backend._post({},b'{}')
            with self.assertRaises(ContractError):backend._post({},b'{}')
        self.assertEqual(opener.open.call_count,2)
        self.assertEqual(backend.remaining,web.CAPABILITY.max_response_bytes-4)
        self.assertIsInstance(make.call_args.args[0],R._NoRedirect)
        self.assertLessEqual(opener.open.call_args.kwargs['timeout'],10)

    def test_exa_oversize_and_elapsed_deadline_fail_closed(self):
        backend=R.BoundedExaSearch(R.research.DEFAULT_EXA_URL,clock=lambda:0)
        backend.remaining=2
        with patch.object(R,'safe_url',return_value=backend.url),patch.object(R.urllib.request,'build_opener') as make:
            make.return_value.open.return_value=Response(b'123')
            with self.assertRaisesRegex(ContractError,'web_response_limit'):backend._post({},b'{}')
        backend=R.BoundedExaSearch(R.research.DEFAULT_EXA_URL,clock=Mock(side_effect=[0,21]))
        with self.assertRaisesRegex(ContractError,'web_transport_budget_exhausted'):backend._post({},b'{}')

    def test_actual_broker_binding_normalizes_only_search_leads(self):
        p=asdict(F.policy(provider_id='web',operation='corroborate'))
        p.update(broker_provider_id='exa_search',corroboration_endpoint=R.research.DEFAULT_EXA_URL)
        store=Store({'researchEgress':{'web':True}})
        _,adapter=R.binding(store,p,web.VERSION)
        response={'result':{'content':[{'text':'Title: Cantonese writing\nURL: https://example.com/lead\nHighlights: 喺度 write 😀'}]}}
        fake=Mock(side_effect=[({},None),(response,None)])
        with patch.object(R.research,'allowed',return_value=True),patch.object(R.research,'enabled',return_value=True),patch.object(R.research,'hosted',return_value=True),patch.object(R.BoundedExaSearch,'_rpc',fake),patch.object(web,'safe_url',side_effect=lambda value,**kw:value):
            result=adapter(policy=F.policy(provider_id='web',operation='corroborate'),cursor={},now=F.NOW,
                payload={'query':'Cantonese creative writing','coverage_epoch':'e'},reservation_microusd=10)
        self.assertEqual(len(result.observations),1)
        self.assertEqual(result.observations[0]['kind'],'search_lead')
        self.assertIn('喺度',result.observations[0]['payload']['text'])
        self.assertNotIn('provider_metrics',result.observations[0]['payload'])
        self.assertIsNone(result.cost_microusd)
        self.assertEqual(result.completeness,'partial')
