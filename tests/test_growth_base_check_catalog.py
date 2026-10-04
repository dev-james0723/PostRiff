"""Real catalog/eligibility code on synthetic SQL boundaries, with no DB/provider."""
import copy
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2.growth.preview import MODEL, ROUTE, SCOPES
from postriff_phase2.model_runtime import ServerModelRuntime

NOW=1790000000
POLICY={'approved':True,'id':'synthetic-secret-policy','attemptMaxUsdMicro':20000,
        'dailyUsdMicro':1000000,'monthlyUsdMicro':2000000,'dailyRuns':20,'workspaceDailyRuns':2,
        'maxInputBytes':64000,'maxOutputTokens':1500,'paidBaseChecks':True}

class ReadCursor:
    def __init__(self):
        self.used={};self.budgets={};self.rates={};self.legacy={};self.q='';self.args=();self.queries=[]
    def execute(self,q,args=()):
        if not q.startswith('SELECT '):raise AssertionError('Projection may not fund/activate: '+q)
        self.q,self.args=q,args;self.queries.append(q)
    def fetchall(self):return list(self.used.items())
    def fetchone(self):
        if 'pr_budgets' in self.q:return self.budgets.get(self.args[0])
        if 'pr_growth_budgets' in self.q:return self.rates.get(self.args[0])
        if 'pr_post_doctor_runs' in self.q:return (1,) if self.used.get('check') else None
        return None

class BaseChecks(unittest.TestCase):
    def setUp(self):
        self.cur=ReadCursor();self.mode='managed_credits';self.role='owner';self.reconciled=0
        self.state={'growthConsent':{'routes':[ROUTE]},'workspace':{'id':'workspace'}}
        @contextmanager
        def transaction(*args):
            yield self.cur,(1,copy.deepcopy(self.state),self.role,False,False,False,False),'actor'
        def ensure(*args):self.reconciled+=1
        self.runtime=ServerModelRuntime('synthetic-only',model=MODEL,models=[MODEL],
            prices={MODEL:(.1,.4)},allowed_providers={MODEL:['google']},
            transport=lambda *a,**kw:self.fail('Catalog must not call a provider'))
        self.g=object.__new__(GrowthService)
        self.g.clock=lambda:NOW
        self.g.env={'POSTRIFF_GROWTH':'1','POSTRIFF_POST_DOCTOR':'1','POSTRIFF_GENOME':'1',
                    'POSTRIFF_GROWTH_DAILY_USD_CAP':'50','POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP':'5'}
        self.g.repository=SimpleNamespace(transaction=transaction,get=lambda *a:{'state':copy.deepcopy(self.state)})
        self.g.hosted=SimpleNamespace(ledger=SimpleNamespace(ensure_entitlement=ensure,growth_mode=lambda *a:self.mode),
            ideas=SimpleNamespace(_select_runtime=lambda model:self.runtime,resolve_writer=lambda *a:(self.runtime,MODEL,None)))
        self.g.rewrite_credit_status=lambda *a:{'billingMode':self.mode,'available':False,'estimateAvailable':False,'reason':'funding_unavailable'}

    def approved(self,**changes):
        self.g.env['POSTRIFF_GROWTH_PLATFORM_PREVIEW']=json.dumps({**POLICY,**changes})

    def base(self):
        value=self.g.catalog('workspace','synthetic').get('baseChecks')
        self.assertIsInstance(value,dict,'Catalog must expose actual server-managed base-check readiness')
        self.assertEqual(set(value),{'billingMode','available','reason'})
        return value

    def test_default_absent_and_paid_base_opt_in_required(self):
        self.assertEqual(self.base(),{'billingMode':'managed_credits','available':False,'reason':'funding_unavailable'})
        self.approved(paidBaseChecks=False)
        self.assertFalse(self.base()['available'])
        self.approved()
        self.assertEqual(self.base(),{'billingMode':'managed_credits','available':True,'reason':None})
        self.assertGreaterEqual(self.reconciled,3)

    def test_qualified_managed_check_ignores_free_lifetime_and_rewrite_readiness(self):
        self.cur.used={'check':9,'genome':2};self.approved()
        self.assertTrue(self.base()['available'])
        self.assertFalse(self.g.catalog('workspace','synthetic')['rewriteCredits']['available'])
        self.assertEqual(self.g.preview_status('workspace','synthetic')['postDoctor'],
                         {'remaining':0,'eligible':False,'reason':'plan_unavailable'})

    def test_current_permission_feature_and_exact_route_consent(self):
        self.approved()
        self.role='viewer';self.assertEqual(self.base()['reason'],'permission_required')
        self.role='owner';self.g.env['POSTRIFF_POST_DOCTOR']='0';self.assertEqual(self.base()['reason'],'feature_disabled')
        self.g.env['POSTRIFF_POST_DOCTOR']='1';self.state['growthConsent']['routes']=[ROUTES[0]]
        self.assertEqual(self.base()['reason'],'consent_required')
        self.state['growthConsent']['routes']=[ROUTE];self.assertTrue(self.base()['available'])

    def test_policy_provider_prices_and_global_or_service_pause_fail_closed(self):
        for change in ({'approved':False},{'dailyRuns':0},{'executionProvider':'other'},
                       {'maxOutputTokens':1501},{'expiresAt':NOW-1}):
            with self.subTest(change=change):
                self.approved(**change);self.assertEqual(self.base()['reason'],'funding_unavailable')
        self.approved();self.runtime.allowed_providers={MODEL:['other']}
        self.assertFalse(self.base()['available'])
        self.runtime.allowed_providers={MODEL:['google']};self.runtime.prices[MODEL]=(100.,100.)
        self.assertFalse(self.base()['available'])
        self.runtime.prices[MODEL]=(.1,.4)
        self.g.env['POSTRIFF_AI_PAUSED']='1';self.assertFalse(self.base()['available'])
        self.g.env.pop('POSTRIFF_AI_PAUSED')
        with patch.dict(os.environ,{'POSTRIFF_AI_PAUSED':'1'}):self.assertFalse(self.base()['available'])

    def test_platform_withdrawal_tightening_and_held_unknown_budget(self):
        self.approved()
        # Actual SQL projection returns effective current-window spent, retaining all holds.
        for scope in SCOPES:
            for budget in (('candidate',1000000,0,0,'day' if scope==SCOPES[0] else 'month'),
                           ('approved',19999,0,0,'day' if scope==SCOPES[0] else 'month'),
                           ('approved',1000000,990000,0,'day' if scope==SCOPES[0] else 'month'),
                           ('approved',1000000,0,990000,'day' if scope==SCOPES[0] else 'month')):
                with self.subTest(scope=scope,budget=budget):
                    self.cur.budgets={scope:budget};self.assertFalse(self.base()['available'])
        self.cur.budgets={};self.assertTrue(self.base()['available']) # approved policy covers first-use creation

    def test_rate_caps_and_nonzero_rate_reserved_amount_block_current_check(self):
        self.approved()
        for scope,cap in ((SCOPES[0],20),('platform-preview:workspace',2)):
            self.cur.rates={scope:(cap,0)};self.assertEqual(self.base()['reason'],'rate_limited')
            self.cur.rates={scope:(0,1)};self.assertFalse(self.base()['available'])
        self.cur.rates={};self.assertTrue(self.base()['available'])

    def test_free_lifetime_contract_and_twenty_post_limit_unchanged(self):
        self.mode='free';self.approved()
        before=self.g.preview_status('workspace','synthetic')
        self.assertEqual(before,{'postDoctor':{'remaining':1,'eligible':True,'reason':None},
                                 'genome':{'remaining':1,'eligible':True,'reason':None,'maxPosts':20}})
        self.assertEqual(self.base(),{'billingMode':'free','available':True,'reason':None})
        self.assertEqual(self.g.preview_status('workspace','synthetic'),before)
        self.cur.used={'check':1}
        self.assertEqual(self.base(),{'billingMode':'free','available':False,'reason':'used'})
        self.assertEqual(self.g.preview_status('workspace','synthetic')['genome']['maxPosts'],20)

    def test_legacy_check_uses_existing_daily_caps_without_preview_opt_in(self):
        self.mode='legacy'
        self.assertEqual(self.base(),{'billingMode':'legacy','available':True,'reason':None})
        self.g.env.pop('POSTRIFF_GROWTH_DAILY_USD_CAP')
        self.assertEqual(self.base()['reason'],'funding_unavailable')
        self.g.env['POSTRIFF_GROWTH_DAILY_USD_CAP']='50'
        for scope,cap in (('global',10000),('workspace',1000),('workspace:check',10)):
            self.cur.rates={scope:(0,cap)}
            self.assertEqual(self.base()['reason'],'rate_limited')
        self.cur.rates={'workspace:check':(1,0)}
        self.assertTrue(self.base()['available']) # exact existing zero-cost call guard permits one micro
        self.cur.rates={'workspace:check':(2,0)}
        self.assertFalse(self.base()['available'])
        self.assertEqual(self.g.preview_status('workspace','synthetic')['postDoctor']['reason'],'plan_unavailable')

    def test_response_is_sanitized_and_projection_cannot_write_funding(self):
        self.approved()
        value=self.base()
        self.assertFalse(any(term in json.dumps(value).lower() for term in ('usd','micro','secret','policy','provider','key')))
        self.assertTrue(all(q.startswith('SELECT ') for q in self.cur.queries))

if __name__=='__main__':unittest.main(verbosity=2)
