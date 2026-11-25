"""R4: real accounting methods, synthetic cursors/transports; no SQL server or provider."""
import copy
import json
import unittest
from contextlib import contextmanager
from decimal import localcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger
from postriff_phase2.credit_meter import V2_POLICY_VERSION, actual_millicredits, millicredits
from postriff_phase2.credit_task_guard import guard_credit_call
from postriff_phase2.growth.credit_funding import RewriteFunding
from postriff_phase2.growth.credit_policy import RewritePolicy
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.growth.usage import MemoryUsageSink, UsageEvent, MAX_USD_MICRO
import test_growth_credit_rewrite as fixtures


def events(*costs):
    return [UsageEvent('postdoctor.rewrite',fixtures.WRITER,'primary','ok',1,
                       cost_usd=c,cost_source='gateway',generation_id='opaque-'+str(i))
            for i,c in enumerate(costs)]


class Cursor:
    """Records strings/values passed to SQL boundaries; never parses or executes SQL."""
    def __init__(self,estimate):
        self.estimate=estimate;self.last='';self.body={};self.status='running'
        maximum=millicredits(estimate)
        self.credit={'op':'reserve','policy':V2_POLICY_VERSION,'maximum':maximum,
                     'allocations':[{'grantId':'opaque-lot','milli':maximum}]}
        self.meta={'credits':self.credit,'budgetScopes':['global']}
        self.usage=[];self.rows=[];self.spent=0;self.reserved=estimate;self.audits=[]
    def execute(self,query,args=()):
        self.last=query;self.args=args
        if query.startswith('INSERT INTO public.pr_model_usage_events'):
            self.usage.append(dict(zip(('workspace_id','task','stage','model','route','provider','generation_id','input_tokens',
                'output_tokens','cost_usd_micro','cost_source','latency_ms','status','subject'),args)))
        elif 'SET body=body||' in query:self.body.update(json.loads(args[0]))
        elif 'SET status=%s,body=' in query:self.status=args[0];self.body=json.loads(args[1])
        elif "SET status='cancelled'" in query:self.status='cancelled'
        elif query.startswith('INSERT INTO public.pr_usage_ledger'):
            if "'estimated_unknown'" in query:
                self.rows.append({'kind':'settle','cost_state':'estimated_unknown','actual':None,'key':args[10],'credits':None})
            else:self.rows.append({'kind':args[5],'cost_state':args[11],'actual':args[10],'key':args[13],
                                   'credits':json.loads(args[14]).get('credits'),'meta':json.loads(args[14])})
        elif query.startswith('UPDATE public.pr_budgets'):
            self.reserved=max(0,self.reserved-args[0]);self.spent+=args[1]
        elif query.startswith('INSERT INTO public.pr_audit_events'):self.audits.append(args)
    def fetchone(self):
        q=self.last
        if 'SELECT body,status,expires_at' in q:return (copy.deepcopy(self.body),self.status,False)
        if q.startswith('SELECT body FROM'):return (copy.deepcopy(self.body),)
        if q.startswith("SELECT meta->'credits'"):
            if "kind='reserve'" in q:return (copy.deepcopy(self.credit),)
            row=next((r for r in self.rows if r['cost_state'] in ('actual','released')),None)
            return (copy.deepcopy(row['credits']),) if row else None
        if q.startswith('SELECT meta FROM'):return (copy.deepcopy(self.meta),)
        if q.startswith('SELECT cost_state FROM'):
            row=next((r for r in self.rows if r['cost_state'] in ('actual','released')),None)
            return (row['cost_state'],) if row else None
        if q.startswith('SELECT dimension,estimated'):
            return ('tool',self.estimate,False,'vercel-ai-gateway',fixtures.WRITER,None,None,'actor')
        if q.startswith('SELECT estimated_usd_micro,model,provider,meta'):
            return (self.estimate,fixtures.WRITER,'vercel-ai-gateway',copy.deepcopy(self.meta),None)
        if "p.entitlements->>'creditPolicy'" in q:return (V2_POLICY_VERSION,'active')
        if q.startswith('SELECT status,stop_usd_micro,spent_usd_micro,reserved_usd_micro'):
            return ('approved',10**12,self.spent,self.reserved)
        if q.startswith('SELECT spent_usd_micro'):return (self.spent,)
        if 'idempotency_key=%s' in q:return (1,) if any(r['key']==self.args[1] for r in self.rows) else None
        if q.startswith('SELECT 1 FROM'):return None
        return ('workspace',)
    def __enter__(self):return self
    def __exit__(self,*args):return False


class TaskRounding(unittest.TestCase):
    def setUp(self):
        self.sink=MemoryUsageSink();self.open_transactions=0;self.guards=[];self.sent=[]
        self.runtime=fixtures.runtime(lambda *a,**kw:self.fail('Unbound provider runtime'))
        self.env={'POSTRIFF_JEV':'1','AI_GATEWAY_API_KEY':'synthetic-only',
                  'POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY':json.dumps(fixtures.declaration())}
        state={'growthConsent':{'routes':['cloud:vercel-ai-gateway:'+m for m in (fixtures.WRITER,fixtures.FALLBACK,fixtures.JEV)]}}
        self.plan=RewritePolicy.from_env(self.env,fixtures.NOW).plan(self.runtime,fixtures.WRITER,2,state,self.env)
        self.cur=Cursor(self.plan.maximum_micro)
        self.ledger=Ledger(credits_enabled=True)
        self.ledger.ensure_entitlement=Mock()
        @contextmanager
        def connection():
            self.open_transactions+=1
            try:yield SimpleNamespace(cursor=lambda:self.cur)
            finally:self.open_transactions-=1
        self.connection=connection
        def guard(task,model,route,next_micro):
            spent,unknown=self.funding.costs()
            self.guards.append((spent,unknown))
            guard_credit_call(self.ledger,self.connection,'workspace','hold',next_usd_micro=next_micro,
                spent_usd_micro=spent,unknown=unknown,model=fixtures.WRITER,provider='vercel-ai-gateway')
        self.funding=RewriteFunding(self.plan,self.sink,guard,now=lambda:fixtures.NOW)
        @contextmanager
        def transaction(*args):yield self.cur,(1,{},'owner',False,False,False,False),'actor'
        self.service=object.__new__(GrowthService)
        self.service.repository=SimpleNamespace(transaction=transaction)
        self.service.hosted=SimpleNamespace(connection_factory=connection,ledger=self.ledger)
        self.service._context=lambda state:'current'
        self.run={'id':'opaque-run','reservationId':'hold','creditPlan':self.plan,'creditBinding':'opaque-binding',
                  'revision':1,'context':'current','prepared':{}}
        self.event_patch=patch('postriff_phase2.billing.pricing_events.settled')
        self.event_patch.start();self.addCleanup(self.event_patch.stop)

    def hop(self,task,model,cost):
        bound=self.plan.routes[('chat',model)]
        def underlying(method,url,headers=None,body=None,**kw):
            self.assertEqual(self.open_transactions,0,'No transaction survives paid transport')
            self.assertTrue(self.guards)
            self.sent.append((task,model))
            return {'status':200,'body':{'model':model,'usage':{'cost':.99},
                'providerMetadata':{'gateway':{'cost':cost,'generationId':'private-hop-'+str(len(self.sent)),
                    'routing':{'finalProvider':bound['executionProviders'][0]}}}}}
        send=self.funding.transport(underlying,'chat')
        body={'model':model,'max_tokens':20,'messages':[{'role':'user','content':'private-input'}],
              'providerOptions':{'gateway':{'only':bound['executionProviders']}}}
        return self.funding.invoke(task,model,'primary',send,('POST',bound['endpoint']),{'body':body},
                                   {'workspace_id':'workspace','subject':'opaque-subject'})

    def finish(self,error=None):
        return self.service._finish('workspace','synthetic',self.run,self.sink,{'candidate':'safe-result'},error)

    def test_two_fractional_hops_round_once_at_task_boundary(self):
        self.sink.events=events(.0001664,.0001664)
        self.assertEqual([e.cost_usd_micro() for e in self.sink.events],[167,167])
        self.assertEqual(self.funding.costs(),(333,False))
        self.assertEqual(actual_millicredits(self.funding.costs()[0]),100)

    def test_one_task_split_into_hops_has_same_debit_as_single_invoice(self):
        self.sink.events=events(.0003328);one=self.funding.costs()
        self.sink.events=events(.0001664,.0001664)
        self.assertEqual(self.funding.costs(),one)

    def test_decimal_context_does_not_change_exact_task_total(self):
        self.sink.events=events(.0001664,.0001664)
        with localcontext() as context:
            context.prec=2
            self.assertEqual(self.funding.costs(),(333,False))

    def test_guard_and_durable_settlement_use_same_task_total_private_hops_stay_detail(self):
        self.hop('postdoctor.rewrite',fixtures.WRITER,.0001664)
        self.hop('postdoctor.grounding',fixtures.FALLBACK,.0001664)
        self.hop('postdoctor.judge',fixtures.FALLBACK,0)
        self.assertEqual(self.guards[-1],(333,False))
        result=self.finish()
        self.assertEqual(self.cur.body['_actualUsage'],{'usdMicro':333,'unknown':False,
                            'basis':'verified-task-usd-v1','usdExact':'0.0003328'})
        self.assertEqual(self.cur.rows[-1]['actual'],333)
        self.assertEqual(self.cur.spent,333)
        self.assertEqual(result['userMilliCreditsCharged'],100)
        self.assertEqual(result['userCreditsCharged'],.1)
        self.assertEqual([r['cost_usd_micro'] for r in self.cur.usage],[167,167,0])
        self.assertEqual(self.cur.body['_usageSource']['count'],3)
        self.assertFalse(any(k.startswith('_') for k in result))
        self.assertNotIn('private-hop',json.dumps(result))
        self.assertEqual(self.finish(),result)
        self.assertEqual(len(self.cur.rows),1);self.assertEqual(len(self.cur.usage),3)

    def test_known_failure_retains_aggregate_platform_loss_customer_zero(self):
        self.sink.events=events(.0001664,.0001664)
        with self.assertRaises(AlphaError):self.finish(AlphaError('known failure',502))
        self.assertEqual(self.cur.rows[-1]['actual'],333)
        self.assertEqual(self.cur.rows[-1]['cost_state'],'released')
        self.assertEqual(self.cur.rows[-1]['credits']['used'],0)
        self.assertEqual(self.cur.body['userMilliCreditsCharged'],0)
        self.assertEqual(self.cur.spent,333)

    def test_actual_customer_debit_rounds_once_for_two_physical_attempts(self):
        self.hop('postdoctor.rewrite',fixtures.WRITER,.0001664)
        self.hop('postdoctor.grounding',fixtures.FALLBACK,.0001664)
        result=self.finish()
        self.assertEqual(result['userCreditsCharged'],.1)
        self.assertEqual(self.cur.rows[-1]['credits']['used'],100)
        self.assertEqual(self.cur.body['_actualUsage']['usdMicro'],333)

    def test_unknown_holds_and_blocks_further_physical_io(self):
        self.hop('postdoctor.rewrite',fixtures.WRITER,None)
        with self.assertRaises(Exception):self.hop('postdoctor.grounding',fixtures.FALLBACK,0)
        self.assertEqual(len(self.sent),1);self.assertEqual(len(self.guards),1)
        with self.assertRaises(AlphaError):self.finish(AlphaError('unknown',502))
        self.assertEqual(self.cur.rows[-1]['cost_state'],'estimated_unknown')
        self.assertIsNone(self.cur.rows[-1]['actual'])
        self.assertIsNone(self.cur.body['userMilliCreditsCharged'])
        self.assertEqual(self.cur.reserved,self.plan.maximum_micro);self.assertEqual(self.cur.spent,0)

    def test_known_zero_and_empty_pre_io_failure_are_not_unknown(self):
        self.hop('postdoctor.rewrite',fixtures.WRITER,0)
        result=self.finish()
        self.assertEqual(self.funding.costs(),(0,False))
        self.assertEqual(result['userMilliCreditsCharged'],0)
        self.assertEqual(self.cur.rows[-1]['actual'],0);self.assertEqual(self.cur.reserved,0)

    def test_empty_pre_io_failure_releases_without_inventing_attempt(self):
        with self.assertRaises(AlphaError):self.finish(AlphaError('before IO',503))
        self.assertEqual(self.cur.rows[-1]['actual'],0)
        self.assertEqual(self.cur.rows[-1]['credits']['used'],0)
        self.assertEqual(self.cur.usage,[])

    def test_known_over_max_absorbed_without_extra_customer_debit_or_retry(self):
        self.hop('postdoctor.rewrite',fixtures.WRITER,1.4)
        with self.assertRaises(Exception):self.hop('postdoctor.grounding',fixtures.FALLBACK,0)
        result=self.finish()
        credit=self.cur.rows[-1]['credits']
        self.assertEqual(self.cur.rows[-1]['actual'],1400000)
        self.assertEqual(result['userMilliCreditsCharged'],self.cur.credit['maximum'])
        self.assertEqual(credit['absorbed'],30000)
        self.assertEqual(self.cur.spent,1400000);self.assertEqual(len(self.sent),1)

    def test_ordinary_one_usd_retains_300_credits(self):
        self.sink.events=events(.25,.75)
        self.assertEqual(self.funding.costs(),(1000000,False))
        self.assertEqual(actual_millicredits(self.funding.costs()[0]),300000)

    def test_unsafe_hops_and_aggregate_overflow_remain_unknown(self):
        for unsafe in (None,True,-1,float('nan'),float('inf'),1e13,10**400,'0.0001664'):
            with self.subTest(unsafe=repr(unsafe)):
                self.sink.events=events(.0001664,unsafe,.0001664)
                self.assertEqual(self.funding.costs(),(333,True))
        self.sink.events=events(9e12,9e12)
        total,unknown=self.funding.costs()
        self.assertGreater(total,MAX_USD_MICRO);self.assertTrue(unknown)
        with self.assertRaises(AlphaError):self.finish(AlphaError('overflow',502))
        self.assertEqual(self.cur.rows[-1]['cost_state'],'estimated_unknown')

    def test_tiny_known_cost_is_not_lost_beside_large_storage_safe_cost(self):
        self.sink.events=events(9e12,1e-300)
        self.assertEqual(self.funding.costs(),(9000000000000000001,False))

    def test_platform_preview_settlement_uses_same_task_aggregate(self):
        self.run.pop('creditPlan');self.run['funding']=True
        self.cur.meta={'platformPreview':{'synthetic':True},'budgetScopes':['global']}
        self.sink.events=events(.0001664,.0001664)
        result=self.finish()
        self.assertEqual(self.cur.rows[-1]['actual'],333)
        self.assertEqual(self.cur.spent,333)
        self.assertEqual(result['userCreditsCharged'],0)


    def test_raw_below_threshold_reaches_durable_wallet_without_double_rounding(self):
        self.sink.events=events(.0001666666,.0001666666)
        result=self.finish()
        self.assertEqual(self.cur.rows[-1]['actual'],334)
        self.assertEqual(self.cur.spent,334)
        self.assertEqual(self.cur.rows[-1]['credits']['used'],100)
        self.assertEqual(result['userMilliCreditsCharged'],100)
        self.assertEqual(self.cur.body['_actualUsage']['usdExact'],'0.0003333332')
        self.assertEqual(self.cur.rows[-1]['meta']['actualUsdExact'],'0.0003333332')
        self.assertNotIn('usdExact',json.dumps(result))

    def test_same_audit_micro_above_threshold_reaches_durable_wallet(self):
        self.sink.events=events(.0001666667,.0001666667)
        result=self.finish()
        self.assertEqual(self.cur.rows[-1]['actual'],334)
        self.assertEqual(result['userMilliCreditsCharged'],200)
        self.assertEqual(self.cur.rows[-1]['credits']['used'],200)
        self.assertEqual(self.cur.rows[-1]['meta'].get('actualUsdExact'),'0.0003333334')

    def test_second_credit_threshold_uses_raw_task_usd(self):
        self.sink.events=events(.0003333333,.0003333333)
        result=self.finish()
        self.assertEqual(self.cur.rows[-1]['actual'],667)
        self.assertEqual(result['userMilliCreditsCharged'],200)

    def test_split_and_unsplit_invoice_have_identical_durable_wallet_debit(self):
        debits=[]
        for costs in ((.0003333332,),(.0001666666,.0001666666)):
            self.cur=Cursor(self.plan.maximum_micro)
            self.sink.events=events(*costs)
            result=self.finish()
            debits.append((result['userMilliCreditsCharged'],self.cur.rows[-1]['actual']))
        self.assertEqual(debits,[(100,334),(100,334)])

    def interrupt_after_durable_accounting(self):
        original=self.service.repository.transaction
        @contextmanager
        def crash(*args):
            raise SystemExit('synthetic process stopped after accounting commit')
            yield
        self.service.repository.transaction=crash
        with self.assertRaises(SystemExit):self.finish()
        self.service.repository.transaction=original
        self.sink.events=[]

    def test_saved_exact_basis_replays_after_losing_sink_once(self):
        self.sink.events=events(.0001666666,.0001666666)
        self.interrupt_after_durable_accounting()
        self.assertTrue(self.cur.body['_usageRecorded'])
        result=self.finish()
        self.assertEqual(result['userMilliCreditsCharged'],100)
        self.assertEqual(self.cur.rows[-1]['actual'],334)
        self.assertEqual(self.cur.rows[-1]['meta']['actualUsdExact'],'0.0003333332')
        self.assertEqual(self.finish(),result)
        self.assertEqual(len(self.cur.rows),1)
        self.assertEqual(len(self.cur.usage),2)

    def test_exact_basis_replay_cancellation_keeps_known_loss_customer_zero(self):
        self.sink.events=events(.0001666666,.0001666666)
        self.interrupt_after_durable_accounting()
        self.cur.status='cancelled'
        with self.assertRaises(AlphaError):self.finish()
        self.assertEqual(self.cur.rows[-1]['actual'],334)
        self.assertEqual(self.cur.spent,334)
        self.assertEqual(self.cur.rows[-1]['credits']['used'],0)
        self.assertEqual(self.cur.rows[-1]['meta'].get('actualUsdExact'),'0.0003333332')

    def test_raw_basis_still_caps_max_and_absorbs_only_excess(self):
        self.cur.credit['maximum']=100
        self.cur.credit['allocations']=[{'grantId':'opaque-lot','milli':100}]
        self.sink.events=events(.0001666667,.0001666667)
        result=self.finish()
        self.assertEqual(result['userMilliCreditsCharged'],100)
        self.assertEqual(self.cur.rows[-1]['credits']['absorbed'],100)
        self.assertEqual(self.cur.rows[-1]['actual'],334)

    def test_failed_raw_threshold_keeps_verified_platform_cost_and_zero_debit(self):
        self.sink.events=events(.0001666666,.0001666666)
        with self.assertRaises(AlphaError):self.finish(AlphaError('known failed result',502))
        self.assertEqual(self.cur.rows[-1]['credits']['used'],0)
        self.assertEqual(self.cur.rows[-1]['actual'],334)
        self.assertEqual(self.cur.rows[-1]['meta'].get('actualUsdExact'),'0.0003333332')

    def test_unknown_raw_threshold_keeps_hold_and_no_exact_debit_basis(self):
        self.sink.events=events(.0001666666,None,.0001666666)
        with self.assertRaises(AlphaError):self.finish(AlphaError('unknown physical attempt',502))
        self.assertEqual(self.cur.rows[-1]['cost_state'],'estimated_unknown')
        self.assertEqual(self.cur.reserved,self.plan.maximum_micro)
        self.assertEqual(self.cur.spent,0)
        self.assertIsNone(self.cur.body['_actualUsage'].get('usdExact'))
        self.assertIsNone(self.cur.body['userMilliCreditsCharged'])


    def test_exact_credit_conversion_is_independent_of_decimal_context(self):
        with localcontext() as context:
            context.prec=2
            self.assertEqual(actual_millicredits(334,actual_usd_exact='0.0003333332'),100)
            self.assertEqual(actual_millicredits(334,actual_usd_exact='0.0003333334'),200)

    def test_invalid_exact_basis_cannot_debit_or_release_known_hold(self):
        for basis in ('0.0003333335','NaN','Infinity','-0.0003333332',0.0003333332,True):
            with self.subTest(basis=basis):
                self.cur=Cursor(self.plan.maximum_micro)
                actual=333 if basis=='0.0003333335' else 334
                result=self.ledger.settle(self.cur,'workspace','hold','completed',actual,
                                         actual_usd_exact=basis)
                self.assertEqual(result['state'],'estimated_unknown')
                self.assertEqual(self.cur.reserved,self.plan.maximum_micro)
                self.assertEqual(self.cur.spent,0)
                self.assertIsNone(self.cur.rows[-1]['credits'])

    def test_new_exact_basis_missing_on_replay_keeps_hold(self):
        self.sink.events=events(.0001666666,.0001666666)
        self.interrupt_after_durable_accounting()
        self.cur.body['_actualUsage'].pop('usdExact')
        result=self.finish()
        self.assertIsNone(result['userMilliCreditsCharged'])
        self.assertEqual(self.cur.rows[-1]['cost_state'],'estimated_unknown')
        self.assertEqual(self.cur.reserved,self.plan.maximum_micro)
        self.assertEqual(self.cur.spent,0)

    def test_historical_micro_only_replay_preserves_existing_interface(self):
        self.cur.body={'_usageRecorded':True,'_actualUsage':{'usdMicro':334,'unknown':False}}
        self.sink.events=[]
        result=self.finish()
        self.assertEqual(result['userMilliCreditsCharged'],200)
        self.assertEqual(self.cur.rows[-1]['actual'],334)
        self.assertNotIn('actualUsdExact',self.cur.rows[-1]['meta'])

    def test_exact_zero_is_durable_known_zero(self):
        self.sink.events=events(0,0)
        result=self.finish()
        self.assertEqual(result['userMilliCreditsCharged'],0)
        self.assertEqual(self.cur.rows[-1]['meta']['actualUsdExact'],'0')
        self.assertEqual(self.cur.rows[-1]['actual'],0)
        self.assertEqual(self.cur.reserved,0)

    def test_storage_safe_exact_large_cost_retains_platform_absorption(self):
        self.sink.events=events(2e9)
        result=self.finish()
        self.assertEqual(self.cur.rows[-1]['actual'],2000000000000000)
        self.assertEqual(result['userMilliCreditsCharged'],self.cur.credit['maximum'])
        self.assertEqual(self.cur.rows[-1]['credits']['absorbed'],600000000000000-self.cur.credit['maximum'])

if __name__=='__main__':unittest.main()
