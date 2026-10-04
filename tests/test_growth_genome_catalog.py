"""Actual catalog/admission code on synthetic SQL boundaries; no PG or provider."""
import copy
import json
import os
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.preview import ROUTE, SCOPES, PreviewAuthority
import test_growth_base_check_catalog as fixture


class Cursor(fixture.ReadCursor):
    def fetchone(self):
        if 'pr_post_doctor_runs' in self.q:
            kind='genome' if "kind='genome'" in self.q else 'check'
            return (1,) if self.used.get(kind) else None
        return super().fetchone()


class GenomeCatalog(unittest.TestCase):
    def setUp(self):
        self.f=fixture.BaseChecks(methodName='test_default_absent_and_paid_base_opt_in_required')
        self.f.setUp();self.f.cur=Cursor();self.g=self.f.g;self.cur=self.f.cur

    def status(self):
        value=self.g.catalog('workspace','synthetic').get('genomeAnalysis')
        self.assertIsInstance(value,dict,'A separate actual Genome readiness field is required')
        self.assertEqual(set(value),{'billingMode','available','reason','maxPosts','csvImport'})
        self.assertEqual(set(value['csvImport']),{'available','reason'})
        self.assertEqual(value['maxPosts'],20)
        return value

    def test_operator_opt_in_and_default_off_are_independent_of_base_checks(self):
        self.assertEqual(self.status()['reason'],'funding_unavailable')
        self.f.approved(paidBaseChecks=False);self.assertFalse(self.status()['available'])
        self.f.approved();self.g.base_check_status=lambda *a:{'billingMode':'managed_credits','available':False,'reason':'funding_unavailable'}
        self.assertTrue(self.status()['available'])
        self.assertTrue(self.status()['csvImport']['available'])

    def test_forty_attempt_budget_is_independent_of_one_check_budget(self):
        self.f.approved()
        for scope,kind in zip(SCOPES,('day','month')):
            self.cur.budgets={scope:('approved',799999,0,0,kind)}
            self.assertTrue(self.g.base_check_status('workspace','synthetic')['available'])
            self.assertEqual(self.status()['reason'],'funding_unavailable')
            self.cur.budgets={scope:('approved',800000,0,0,kind)}
            self.assertTrue(self.status()['available'])

    def test_selected_analysis_edit_and_csv_owner_permissions_remain_separate(self):
        self.f.approved();self.f.role='editor'
        self.assertTrue(self.status()['available'])
        self.assertEqual(self.status()['csvImport'],{'available':False,'reason':'permission_required'})
        self.f.role='viewer';self.assertEqual(self.status()['reason'],'permission_required')
        self.assertFalse(self.status()['csvImport']['available'])
        self.f.role='owner';self.assertTrue(self.status()['csvImport']['available'])

    def test_genome_flag_and_exact_workspace_route_are_required(self):
        self.f.approved();self.g.env['POSTRIFF_GENOME']='0'
        self.assertTrue(self.g.base_check_status('workspace','synthetic')['available'])
        self.assertEqual(self.status()['reason'],'feature_disabled')
        self.g.env['POSTRIFF_GENOME']='1';self.f.state['growthConsent']['routes']=[fixture.ROUTES[0]]
        self.assertEqual(self.status()['reason'],'consent_required')

    def test_actual_policy_provider_price_and_pause_bindings_fail_closed(self):
        for change in ({'approved':False},{'executionProvider':'other'},{'maxOutputTokens':1501}):
            self.f.approved(**change);self.assertFalse(self.status()['available'])
        self.f.approved();self.f.runtime.allowed_providers={fixture.MODEL:['other']}
        self.assertFalse(self.status()['available'])
        self.f.runtime.allowed_providers={fixture.MODEL:['google']};self.f.runtime.prices[fixture.MODEL]=(100.,100.)
        self.assertFalse(self.status()['available'])
        self.f.runtime.prices[fixture.MODEL]=(.1,.4);self.g.env['POSTRIFF_AI_PAUSED']='1'
        self.assertFalse(self.status()['available']);self.g.env.pop('POSTRIFF_AI_PAUSED')
        with patch.dict(os.environ,{'POSTRIFF_AI_PAUSED':'1'}):self.assertFalse(self.status()['available'])

    def test_current_platform_withdrawal_spend_and_unknown_holds_block_aggregate(self):
        self.f.approved()
        for scope,kind in zip(SCOPES,('day','month')):
            for budget in (('candidate',1000000,0,0,kind),('approved',1000000,200001,0,kind),
                           ('approved',1000000,0,200001,kind),('approved',1000000,-1,0,kind)):
                self.cur.budgets={scope:budget};self.assertFalse(self.status()['available'])
        self.cur.budgets={};self.assertTrue(self.status()['available'])

    def test_actual_shared_platform_rate_and_workspace_rate_block(self):
        self.f.approved()
        for scope,cap in ((SCOPES[0],20),('platform-preview:workspace',2)):
            self.cur.rates={scope:(cap,0)};self.assertEqual(self.status()['reason'],'rate_limited')
            self.cur.rates={scope:(0,1)};self.assertFalse(self.status()['available'])

    def test_free_uses_genome_lifetime_without_consuming_check_contract(self):
        self.f.mode='free';self.f.approved();self.cur.used={'check':1}
        before=copy.deepcopy(self.g.preview_status('workspace','synthetic'))
        self.assertTrue(self.status()['available'])
        self.assertEqual(self.g.preview_status('workspace','synthetic'),before)
        self.cur.used={'genome':1};self.assertEqual(self.status()['reason'],'used')
        self.assertTrue(self.g.base_check_status('workspace','synthetic')['available'])

    def test_legacy_preserves_genome_amount_and_one_run_cap_without_preview_policy(self):
        self.f.mode='legacy';self.assertTrue(self.status()['available'])
        self.cur.rates={'workspace:genome':(0,1)};self.assertEqual(self.status()['reason'],'rate_limited')
        self.cur.rates={};self.g.env['POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP']='0.799999'
        self.assertEqual(self.status()['reason'],'funding_unavailable')
        self.assertTrue(self.g.base_check_status('workspace','synthetic')['available'])

    def test_projection_has_only_selects_and_no_private_funding_fields(self):
        self.f.approved();value=self.status()
        self.assertFalse(any(word in json.dumps(value).lower() for word in ('usd','micro','secret','policy','provider','key')))
        self.assertTrue(all(q.startswith('SELECT ') for q in self.cur.queries))

    def begin(self,count,**request):
        class BeginCursor:
            def execute(c,q,args=()):c.q=q
            def fetchone(c):return (1,) if 'RETURNING calls' in c.q else None
        self.f.cur=BeginCursor();self.reserved=[]
        def reserve(cur,workspace,actor,dimension,amount,key,**kw):
            self.reserved.append((amount,kw));return {'reservationId':'synthetic-existing-ledger-boundary'}
        self.g.hosted.ledger.reserve=reserve
        body={'confirmed':True,'requestKey':'synthetic-distinct-genome-key',**request}
        return self.g._begin('workspace','synthetic','genome',body,lambda *a:{'posts':[{} for _ in range(count)]})

    def test_actual_managed_begin_reaches_existing_preview_authority_for_actual_count(self):
        self.f.approved()
        try:run=self.begin(20)
        except AlphaError as error:self.fail('Qualified managed Genome is still rejected: '+str(error))
        funding=run['funding'];self.assertIsInstance(funding,PreviewAuthority)
        self.assertEqual((funding.kind,funding.max_attempts,funding.maximum_micro),('genome',40,800000))
        self.assertEqual(self.reserved[0][0],800000)
        self.assertIs(self.reserved[0][1]['platform_preview'],funding)
        self.assertFalse(self.reserved[0][1]['charge_batch'])
        try:run=self.begin(1)
        except AlphaError as error:self.fail('Qualified single-post Genome is still rejected: '+str(error))
        self.assertEqual((run['funding'].max_attempts,run['funding'].maximum_micro),(2,40000))

    def test_client_fields_cannot_opt_in_or_expand_actual_attempt_limit(self):
        self.f.approved(paidBaseChecks=False)
        with self.assertRaises(AlphaError):self.begin(1,paidBaseChecks=True,maximumUsdMicro=0)
        self.assertEqual(self.reserved,[])
        self.f.approved()
        with self.assertRaises(AlphaError):self.begin(21,maxPosts=999,quantity=1)
        self.assertEqual(self.reserved,[])

if __name__=='__main__':unittest.main(verbosity=2)
