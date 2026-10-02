"""Synthetic physical transports only; never a real provider or PostgreSQL."""
import copy
import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError
from postriff_phase2.credit_wallet import request_digest
from postriff_phase2.model_runtime import ServerModelRuntime, DEFAULT_ENDPOINT
from postriff_phase2.growth.jev import EVALUATE_ENDPOINT
from postriff_phase2.growth.usage import MemoryUsageSink
from postriff_phase2.growth import questions

WRITER = 'anthropic/claude-sonnet-5'
FALLBACK = 'google/gemini-2.5-flash-lite'
JEV = 'typesafe-ai/jev'
NOW = 1_800_000_000


def declaration():
    routes = []
    for kind, model, provider in (('chat', WRITER, 'anthropic'), ('chat', FALLBACK, 'google'), ('evaluate', JEV, 'typesafe-ai')):
        routes.append({'kind': kind, 'model': model, 'provider': 'vercel-ai-gateway',
                       'endpoint': EVALUATE_ENDPOINT if kind == 'evaluate' else DEFAULT_ENDPOINT,
                       'executionProviders': [provider], 'ceilingUsdMicro': 100_000,
                       'maxInputBytes': 100_000, 'maxOutputTokens': None if kind == 'evaluate' else 4500,
                       'priceBasis': None if kind == 'evaluate' else {'version': 'configured', 'inputUsdPerMTok': .1, 'outputUsdPerMTok': .4}})
    return {'approved': True, 'id': 'synthetic-growth-v1', 'qualification': 'operator-approved-ceiling',
            'evidenceRef': 'synthetic-only-no-live-price-verification', 'expiresAt': NOW + 3600, 'routes': routes}


def runtime(transport):
    return ServerModelRuntime('synthetic', model=WRITER, models=[WRITER, FALLBACK],
                              prices={WRITER: (.1, .4), FALLBACK: (.1, .4)}, transport=transport)


def load(name):
    try:
        return importlib.import_module('postriff_phase2.growth.' + name)
    except ModuleNotFoundError:
        return None


class RewritePolicyTests(unittest.TestCase):
    def setUp(self):
        self.module = load('credit_policy')
        self.assertIsNotNone(self.module, 'A real managed rewrite qualification policy is required')

    def plan(self, policy=None, version=2, routes=None, writer=None):
        rt = writer or runtime(lambda *a, **kw: self.fail('policy must not dispatch'))
        env = {'POSTRIFF_JEV': '1', 'AI_GATEWAY_API_KEY': 'synthetic',
               'POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY': json.dumps(policy or declaration())}
        state = {'growthConsent': {'routes': routes or ['cloud:vercel-ai-gateway:' + m for m in (WRITER, FALLBACK, JEV)]}}
        return self.module.RewritePolicy.from_env(env, NOW).plan(rt, WRITER, version, state, env)

    def test_default_off_and_complete_pipeline_maximum(self):
        self.assertIsNone(self.module.RewritePolicy.from_env({}, NOW))
        p = self.plan()
        self.assertEqual(p.maximum_micro, 1_300_000)  # writer + 4*(2 Jev + 1 fallback)
        self.assertEqual(p.max_attempts, 13)
        self.assertEqual(self.plan(version=1).maximum_micro, 700_000)
        self.assertEqual(p.tasks['postdoctor.judge'][1], JEV)

    def test_expiry_approval_evidence_and_unknown_fields_fail_closed(self):
        for delta in ({'approved': False}, {'expiresAt': NOW}, {'expiresAt': NOW+32*86400},
                      {'evidenceRef': ''}, {'qualification': 'guess'}, {'clientOverride': True}):
            with self.subTest(delta=delta), self.assertRaises(AlphaError):
                self.plan({**declaration(), **delta})

    def test_every_actual_provider_fallback_and_price_must_be_bound(self):
        for mutate in ('missing-fallback', 'provider', 'price', 'cap', 'endpoint', 'output'):
            p = declaration()
            if mutate == 'missing-fallback': p['routes'].pop(1)
            if mutate == 'provider': p['routes'][0]['executionProviders'] = ['other']
            if mutate == 'price': p['routes'][0]['priceBasis']['inputUsdPerMTok'] = 7
            if mutate == 'cap': p['routes'][0]['ceilingUsdMicro'] = 1
            if mutate == 'endpoint': p['routes'][2]['endpoint'] = 'https://other.test/v1/evaluate'
            if mutate == 'output': p['routes'][0]['maxOutputTokens'] = 3999
            with self.subTest(mutate=mutate), self.assertRaises(AlphaError): self.plan(p)

    def test_cannot_silently_replace_or_disable_jev(self):
        env = {'POSTRIFF_JEV': '0', 'AI_GATEWAY_API_KEY': 'synthetic'}
        with self.assertRaises(AlphaError):
            self.module.RewritePolicy.from_env({'POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY': json.dumps(declaration())}, NOW).plan(runtime(None), WRITER, 2, {}, env)

    def test_price_policy_and_pipeline_increases_change_quote_binding(self):
        a = self.plan()
        p = declaration(); p['routes'][2]['ceilingUsdMicro'] += 1
        self.assertNotEqual(a.fingerprint, self.plan(p).fingerprint)
        self.assertNotEqual(a.fingerprint, self.plan(version=1).fingerprint)

    def test_actual_writer_and_fallback_reasoning_headroom_cannot_be_shrunk(self):
        p=self.plan()
        self.assertEqual(p.tasks['postdoctor.rewrite'][4],4500)
        self.assertEqual(p.tasks['postdoctor.grounding'][4],4500)
        with patch('postriff_phase2.growth.credit_policy.output_cap',return_value=5000):
            with self.assertRaises(AlphaError):self.plan()


class FundingTests(unittest.TestCase):
    def setUp(self):
        self.module = load('credit_funding')
        self.policy = load('credit_policy')
        self.assertIsNotNone(self.module, 'A physical-attempt managed rewrite funding bridge is required')
        self.assertIsNotNone(self.policy)
        self.sent = []; self.guarded = []; self.cost = .004; self.status = 200; self.provider = 'anthropic'
        self.response_hook = None
        def transport(method, url, headers=None, body=None, **kw):
            self.assertTrue(self.guarded, 'committed funding guard must precede physical I/O')
            self.sent.append(copy.deepcopy(body))
            if self.response_hook: self.response_hook()
            return {'status': self.status, 'body': {'choices': [{'message': {'content': '{"value":1}'}}],
                    'usage': {'cost': .99}, 'providerMetadata': {'gateway': {'cost': self.cost,
                    'generationId': 'opaque-'+str(len(self.sent)), 'routing': {'finalProvider': self.provider}}}}}
        self.rt = runtime(transport)
        self.env = {'POSTRIFF_JEV': '1', 'AI_GATEWAY_API_KEY': 'synthetic',
                    'POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY': json.dumps(declaration())}
        self.state = {'growthConsent': {'routes': ['cloud:vercel-ai-gateway:'+m for m in (WRITER, FALLBACK, JEV)]}}
        self.plan = self.policy.RewritePolicy.from_env(self.env, NOW).plan(self.rt, WRITER, 2, self.state, self.env)
        self.sink = MemoryUsageSink()
        def guard(task, model, route, next_micro): self.guarded.append((task, model, route, next_micro))
        self.funding = self.module.RewriteFunding(self.plan, self.sink, guard, now=lambda: NOW)
        self.router = self.funding.router(self.rt, self.env)

    def write(self):
        return self.router.complete_json('postdoctor.rewrite', [{'role':'user','content':'synthetic'}], validate=lambda v:v, workspace_id='opaque', subject='opaque')

    def test_physical_charge_exactly_once_without_overlap(self):
        self.write()
        self.assertEqual(len(self.sink.events), 1)
        self.assertEqual(self.funding.costs(), (4000, False))
        self.assertEqual(self.sink.events[0].generation_id, 'opaque-1')
        self.assertEqual(self.sent[0]['providerOptions']['gateway']['only'], ['anthropic'])

    def test_unknown_or_unsafe_invoice_stops_all_subsequent_paid_io(self):
        for cost in (None, True, float('nan'), float('inf'), 1e308, 1e13, 'invalid'):
            with self.subTest(cost=cost):
                self.sink.events.clear(); self.sent.clear(); self.cost = cost
                self.funding.blocked = False  # Each subcase is a distinct fresh synthetic run.
                try: self.write()
                except Exception: pass
                with self.assertRaises(Exception): self.write()
                self.assertEqual(len(self.sent), 1)
                self.assertEqual(self.funding.costs(), (0, True))

    def test_known_failed_envelope_cost_survives(self):
        self.status = 500
        with self.assertRaises(Exception): self.write()
        self.assertEqual(self.funding.costs(), (4000, False))
        self.assertEqual(len(self.sink.events), 1)

    def test_provider_mismatch_books_actual_but_stops_pipeline(self):
        self.provider = 'other'
        with self.assertRaises(Exception): self.write()
        with self.assertRaises(Exception): self.write()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.funding.costs(), (4000, False))

    def test_guard_rejection_does_not_invent_a_paid_attempt(self):
        def deny(*args): raise AlphaError('synthetic revoked',409)
        self.funding.guard = deny
        with self.assertRaises(Exception): self.write()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.sink.events, [])

    def test_bound_output_and_input_and_count_before_io(self):
        self.router.tasks['postdoctor.rewrite'] = ('chat', WRITER, (), 45, 4501)
        with self.assertRaises(Exception): self.write()
        self.assertEqual(self.sent, [])

    def test_over_ceiling_charge_is_retained_and_no_next_attempt(self):
        self.cost = .2
        try: self.write()
        except Exception: pass
        with self.assertRaises(Exception): self.write()
        self.assertEqual(self.funding.costs(), (200000, False))
        self.assertEqual(len(self.sent), 1)

    def evaluate_transport(self, statuses, costs):
        def transport(method, url, headers=None, body=None, **kw):
            self.sent.append(body)
            self.assertEqual(body['providerOptions']['gateway']['only'], ['typesafe-ai'] if url==EVALUATE_ENDPOINT else ['google'])
            i=len(self.sent)-1
            answers={name:{'type':'boolean','probability':.95} for name in questions.get('grounding').names}
            return {'status':statuses[i], 'body':{'answers':answers,'choices':[{'message':{'content':json.dumps({'answers':answers})}}],
                    'providerMetadata':{'gateway':{'cost':costs[i], 'routing':{'finalProvider':'typesafe-ai' if url==EVALUATE_ENDPOINT else 'google'}}}}}
        self.rt.transport=transport
        self.router=self.funding.router(self.rt,self.env)
        self.router.sleep=lambda _:None

    def test_known_failed_jev_attempts_and_actual_fallback_sum_once(self):
        self.evaluate_transport([500,500,200],[.001,.002,.003])
        answer=self.router.evaluate('postdoctor.grounding',questions.get('grounding'),{},workspace_id='opaque')
        self.assertEqual(answer.route,'fallback')
        self.assertEqual(len(self.sent),3)
        self.assertEqual(len(self.sink.events),3)
        self.assertEqual(self.funding.costs(),(6000,False))

    def test_unknown_jev_rate_limit_cannot_start_a_paid_retry(self):
        self.evaluate_transport([429,200],[None,.003])
        with self.assertRaises(Exception): self.router.evaluate('postdoctor.grounding',questions.get('grounding'),{},workspace_id='opaque')
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.funding.costs(),(0,True))

    def test_jev_per_task_physical_ceiling_cannot_be_reused(self):
        self.evaluate_transport([200,200,200],[.001,.002,.003])
        for _ in range(2): self.router.evaluate('postdoctor.grounding',questions.get('grounding'),{},workspace_id='opaque')
        with self.assertRaises(Exception): self.router.evaluate('postdoctor.grounding',questions.get('grounding'),{},workspace_id='opaque')
        self.assertEqual(len(self.sent),2)

    def test_expiry_and_actual_payload_size_reject_before_transport(self):
        self.funding.now=lambda:NOW+3600
        with self.assertRaises(Exception):self.write()
        self.funding.now=lambda:NOW
        with self.assertRaises(Exception):
            self.router.complete_json('postdoctor.rewrite',[{'role':'user','content':'x'*100_000}],validate=lambda v:v)
        self.assertEqual(self.sent,[])


class AccountingCursor:
    """Small SQL-boundary fixture, not a PostgreSQL integration claim."""
    def __init__(self):
        self.body={};self.status='running';self.usage_count=0;self.used=None;self.last='';self.expiries=[]
    def execute(self,q,args=()):
        self.last=q
        if q.startswith('INSERT INTO public.pr_model_usage_events'):self.usage_count+=1
        elif 'SET body=body||' in q:self.body.update(json.loads(args[0]))
        elif 'SET status=%s,body=' in q:self.status=args[0];self.body=json.loads(args[1])
        elif "SET status='cancelled',body=" in q:self.status='cancelled';self.body=json.loads(args[0])
        elif "SET status='cancelled'" in q:self.status='cancelled'
    def fetchone(self):
        if 'SELECT body,status,expires_at' in self.last:return (copy.deepcopy(self.body),self.status,self.expiries.pop(0) if self.expiries else False)
        if "SELECT meta->'credits'" in self.last:return ({'used':self.used},) if self.used is not None else None
        if 'SELECT body FROM' in self.last:return (copy.deepcopy(self.body),)
        return ('workspace',)
    def __enter__(self):return self
    def __exit__(self,*args):return False


class ServiceAccountingTests(unittest.TestCase):
    def setUp(self):
        from postriff_phase2.growth.service import GrowthService
        from postriff_phase2.growth.usage import UsageEvent
        self.cur=AccountingCursor(); self.revoked=False;self.revision=1;self.settlements=[]
        @contextmanager
        def connection():yield SimpleNamespace(cursor=lambda:self.cur)
        @contextmanager
        def transaction(*args):
            if self.revoked:raise AlphaError('synthetic revoked',403)
            yield self.cur,(self.revision,{},'owner',False,False,False,False),'actor'
        def settle(cur,wid,rid,outcome,actual,**kwargs):
            if self.cur.used is not None:return {'state':'released' if self.cur.used==0 else 'actual','duplicate':True}
            self.settlements.append((outcome,actual))
            self.cur.used=7 if outcome=='completed' else 0 if outcome=='failed' else None
            return {'state':'estimated_unknown' if outcome=='unknown' else 'actual' if outcome=='completed' else 'released'}
        self.g=object.__new__(GrowthService)
        self.g.repository=SimpleNamespace(transaction=transaction)
        self.g.hosted=SimpleNamespace(connection_factory=connection,ledger=SimpleNamespace(settle=settle))
        self.g._context=lambda state:'current'
        self.run={'id':'run','reservationId':'reservation','creditPlan':True,'creditBinding':'opaque',
                  'revision':1,'context':'current','prepared':{}}
        self.sink=MemoryUsageSink()
        self.sink.record(UsageEvent('postdoctor.rewrite',WRITER,'primary','ok',1,cost_usd=.004,cost_source='gateway'))

    def finish(self,error=None):return self.g._finish('workspace','token',self.run,self.sink,{'rewrite':'result'},error)

    def test_success_uses_durable_customer_debit_and_replay_does_not_record_twice(self):
        result=self.finish()
        self.assertEqual(result['userMilliCreditsCharged'],7)
        self.assertEqual(result['userCreditsCharged'],.007)
        self.assertEqual(self.finish(),result)
        self.assertEqual(self.cur.usage_count,1)
        self.assertEqual(self.settlements,[('completed',4000)])

    def test_failed_customer_zero_keeps_known_platform_cost(self):
        with self.assertRaises(AlphaError):self.finish(AlphaError('synthetic failed',502))
        self.assertEqual(self.settlements,[('failed',4000)])
        self.assertEqual(self.cur.body['userMilliCreditsCharged'],0)

    def test_revoked_permission_accounts_known_usage_before_content_fence(self):
        self.revoked=True
        with self.assertRaises(AlphaError):self.finish()
        self.assertEqual(self.cur.usage_count,1)
        self.assertEqual(self.settlements,[('failed',4000)])
        self.assertTrue(self.cur.body['_usageRecorded'])

    def test_revision_change_cannot_charge_a_failed_content_result(self):
        self.revision=2
        with self.assertRaises(AlphaError):self.finish()
        self.assertEqual(self.settlements,[('failed',4000)])

    def test_unknown_is_a_hold_and_never_customer_zero(self):
        from postriff_phase2.growth.usage import UsageEvent
        self.sink.events=[UsageEvent('postdoctor.rewrite',WRITER,'primary','upstream',1)]
        with self.assertRaises(AlphaError):self.finish(AlphaError('lost',502))
        self.assertTrue(all(s==('unknown',None) for s in self.settlements))
        self.assertIsNone(self.cur.body['userMilliCreditsCharged'])

    def test_expired_recorded_invoice_settles_known_failure_without_recording_twice(self):
        self.cur.body={'_usageRecorded':True,'_creditFunding':{'opaque':'bound'},'_reservationId':'reservation',
                       '_actualUsage':{'usdMicro':12000,'unknown':False},'_usageSource':{'kind':'physical-gateway-attempts','count':3},
                       'rewrite':'private retained text'}
        self.cur.expiries=[True]
        with self.assertRaises(AlphaError):self.finish()
        self.assertEqual(self.settlements,[('failed',12000)])
        self.assertEqual(self.cur.usage_count,0)
        self.assertEqual(self.cur.body['_usageSource']['count'],3)
        self.assertEqual(self.cur.body['_creditSettlement']['usedMilliCredits'],0)
        self.assertNotIn('rewrite',self.cur.body)

    def test_expired_recorded_unknown_invoice_preserves_hold_and_provenance(self):
        self.cur.body={'_usageRecorded':True,'_creditFunding':{'opaque':'bound'},
                       '_actualUsage':{'usdMicro':None,'unknown':True},'_usageSource':{'count':1}}
        self.cur.expiries=[True]
        with self.assertRaises(AlphaError):self.finish()
        self.assertEqual(self.settlements,[('unknown',None)])
        self.assertEqual(self.cur.usage_count,0)
        self.assertEqual(self.cur.body['_usageSource']['count'],1)
        self.assertIsNone(self.cur.body['_creditSettlement']['usedMilliCredits'])

    def test_expiry_between_accounting_and_content_preserves_opaque_accounting(self):
        self.cur.body={'_creditFunding':{'opaque':'bound'},'_reservationId':'reservation'}
        self.cur.expiries=[False,True]
        with self.assertRaises(AlphaError):self.finish()
        self.assertEqual(self.settlements,[('failed',4000)])
        self.assertEqual(self.cur.usage_count,1)
        self.assertEqual(self.cur.body.get('_actualUsage'),{'usdMicro':4000,'unknown':False})
        self.assertEqual(self.cur.body.get('_usageSource',{}).get('count'),1)
        self.assertEqual(self.cur.body.get('_creditSettlement',{}).get('usedMilliCredits'),0)
        self.assertNotIn('rewrite',self.cur.body)

    def test_real_rewrite_pipeline_uses_writer_grounding_recheck_both_comparisons(self):
        from postriff_phase2.growth.credit_policy import RewritePolicy
        from growth_postdoctor_v2_fixtures import ComparisonModels
        models=ComparisonModels();sent=[];guards=[]
        def transport(method,url,headers=None,body=None,**kw):
            sent.append(copy.deepcopy(body))
            self.assertEqual(len(guards),len(sent))
            if 'messages' in body:
                content,_=models.chat(body['messages'],body['model'],body['max_tokens'],1)
                data={'choices':[{'message':{'content':content}}]}
            else:data={'answers':models.evaluate(body['state'],body['questions'],timeout_s=1).answers}
            data['providerMetadata']={'gateway':{'cost':.004,'routing':{'finalProvider':body['model'].split('/')[0]}}}
            return {'status':200,'body':data}
        rt=runtime(transport)
        self.g.env={'POSTRIFF_GROWTH':'1','POSTRIFF_POST_DOCTOR':'1','POSTRIFF_POST_DOCTOR_V2':'1','POSTRIFF_JEV':'1',
                    'AI_GATEWAY_API_KEY':'synthetic','POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY':json.dumps(declaration())}
        self.g.clock=lambda:NOW;self.g.profile=None
        self.g.hosted.ideas=SimpleNamespace(_select_runtime=lambda model:rt)
        self.g._guard_rewrite=lambda *args:guards.append(args[-4:])
        state={'growthConsent':{'routes':['cloud:vercel-ai-gateway:'+m for m in (WRITER,FALLBACK,JEV)]}}
        self.run.update(creditPlan=RewritePolicy.from_env(self.g.env,NOW).plan(rt,WRITER,2,state,self.g.env),state=state)
        draft={'text':'One idea. Another idea!','platform':'Threads','language':'en','id':None,'revision':None}
        messages=[{'role':'user','content':json.dumps({'original':draft['text']})}]
        self.run['prepared']={'writer':WRITER,'draft':draft,'check':{'questionSet':'postdoctor.v2'},'messages':messages,'facts':{},'posts':[]}
        self.g._begin=lambda *args:self.run
        result=self.g.rewrite('workspace','token',{'checkId':'check'})
        self.assertEqual(len(sent),5)
        self.assertEqual(sent[0]['model'],WRITER)
        self.assertTrue(all(b['model']==JEV for b in sent[1:]))
        self.assertTrue(result['comparison']['orderChecked'])
        self.assertEqual(result['grounding'],'passed')
        self.assertEqual(self.settlements,[('completed',20000)])
        self.assertEqual(self.cur.usage_count,5)


class DispatchTests(unittest.TestCase):
    def test_expired_durable_rewrite_stops_before_parent_guard_and_io(self):
        from postriff_phase2.growth.service import GrowthService
        updates=[];calls=[]
        record={'opaque':'bound'}
        plan=SimpleNamespace(fingerprint='plan',record=lambda:record,max_attempts=13,writer=WRITER)
        cur=SimpleNamespace(execute=lambda q,args:updates.append(q),fetchone=lambda:({'_creditFunding':record,'_attempts':0},'running',True))
        @contextmanager
        def transaction(*args):yield cur,(1,{},'owner',False,False,False,False),'actor'
        g=object.__new__(GrowthService)
        g.repository=SimpleNamespace(transaction=transaction)
        g.hosted=SimpleNamespace(connection_factory=lambda:None,ledger=SimpleNamespace(ensure_entitlement=lambda *a:None,growth_mode=lambda *a:'managed_credits'))
        g._prepare_rewrite=lambda *a:{};g._rewrite_plan=lambda *a:plan;g._rewrite_binding=lambda *a:'bound'
        run={'id':'run','revision':1,'reservationId':'hold','creditRequest':{},'creditPlan':plan,'creditBinding':'bound'}
        funding=SimpleNamespace(sink=MemoryUsageSink(),costs=lambda:(0,False))
        with patch('postriff_phase2.growth.service.credit_guard',return_value=lambda *a,**kw:calls.append(kw)):
            with self.assertRaises(AlphaError):g._guard_rewrite('workspace','token',run,funding,'postdoctor.rewrite',WRITER,'primary',20000)
        self.assertEqual(calls,[])
        self.assertFalse(any('jsonb_set' in q for q in updates))

    def test_free_general_growth_still_rejects_before_preparation(self):
        from postriff_phase2.growth.service import GrowthService,ROUTES
        cur=SimpleNamespace(execute=lambda *args:None,fetchone=lambda:None)
        @contextmanager
        def transaction(*args):yield cur,(1,{'growthConsent':{'routes':list(ROUTES)}},'owner',False,False,False,False),'actor'
        g=object.__new__(GrowthService)
        g.env={'POSTRIFF_GROWTH':'1','POSTRIFF_POST_DOCTOR':'1'}
        g.repository=SimpleNamespace(transaction=transaction)
        g.hosted=SimpleNamespace(ledger=SimpleNamespace(ensure_entitlement=lambda *a:None,growth_mode=lambda *a:'free'))
        with self.assertRaises(AlphaError) as caught:
            g._begin('workspace','token','rewrite',{'confirmed':True,'requestKey':'stable-free-request','text':'original'},lambda *a:self.fail('Free preparation reached'))
        self.assertEqual(caught.exception.code,'free_managed_writing_unavailable')

    def test_real_prepare_keeps_workspace_and_original_writer_context(self):
        from postriff_phase2.growth.service import GrowthService
        calls=[]
        cur=SimpleNamespace(execute=lambda q,args:calls.append((q,args)),fetchone=lambda:({'draft':{'text':'An idea.','platform':'Threads','language':'en'},'change':['clarity']},'current'))
        g=object.__new__(GrowthService)
        g._context=lambda state:'current'
        g._history=lambda cur,w,state:[]
        g.hosted=SimpleNamespace(ideas=SimpleNamespace(resolve_writer=lambda state,m:(SimpleNamespace(provider_class='cloud'),WRITER,None)))
        with patch('postriff_phase2.growth.service.memory.projection',return_value={'files':[]}):
            prepared=g._prepare_rewrite(cur,'workspace',{'growthConsent':{'routes':['cloud:vercel-ai-gateway:'+WRITER]}},'actor',{'checkId':'check','facts':{}})
        self.assertEqual(calls[0][1],('workspace','check'))
        self.assertEqual(prepared['writer'],WRITER)
        self.assertIn('An idea.',prepared['messages'][1]['content'])

    def test_estimate_and_issue_call_actual_growth_service(self):
        from postriff_phase2.credit_requests import CreditRequests
        calls=[]
        credits=CreditRequests(SimpleNamespace())
        with self.assertRaises(AlphaError):credits.estimate('w','session',{'operation':'post-doctor-rewrite'})
        credits.growth=SimpleNamespace(rewrite_credit_request=lambda *a,**kw:calls.append((a,kw)) or {'actual':True})
        body={'operation':'post-doctor-rewrite','request':{}}
        self.assertEqual(credits.estimate('w','session',body),{'actual':True})
        self.assertEqual(credits.issue('w','session',body),{'actual':True})
        self.assertEqual(calls[0][1],{'issue':False})
        self.assertEqual(calls[1][1],{'issue':True})

    def test_parent_guard_absence_is_fail_closed(self):
        from postriff_phase2.growth.credit_funding import credit_guard
        with patch.dict('sys.modules',{'postriff_phase2.credit_task_guard':None}):
            with self.assertRaises(AlphaError):credit_guard()


class OperationTests(unittest.TestCase):
    def test_real_rewrite_operation_binds_input_and_discards_only_transport_approval(self):
        body = {'checkId':'opaque','model':WRITER,'facts':{},'confirmed':True,'requestKey':'unique-request-key'}
        try: value = request_digest('post-doctor-rewrite', body)
        except ValueError: value = None
        self.assertIsNotNone(value, 'The concrete Growth operation must be wired into credit request binding')
        self.assertEqual(value, request_digest('post-doctor-rewrite', {**body,'creditQuoteId':'transport','expectedRevision':5}))
        self.assertNotEqual(value, request_digest('post-doctor-rewrite', {**body,'facts':{'own':'changed'}}))
        with self.assertRaises(ValueError): request_digest('post-doctor-rewrite',{**body,'ceilingUsdMicro':1})


if __name__ == '__main__': unittest.main(verbosity=2)
