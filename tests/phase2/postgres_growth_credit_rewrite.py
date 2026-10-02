"""Parent-coordinated owned PG only, real Growth/Ledger and synthetic HTTP transports.

No cluster startup, schema mutation, provider call, or lease acquisition here.
Parent supplies the existing Task5/6 schema harness and the exclusive port.
"""
import copy
import json
import os
import time
import unittest
import uuid

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.model_runtime import ServerModelRuntime
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2.growth.credit_policy import ENV_KEY
from growth_postdoctor_v2_fixtures import ComparisonModels
from growth_phase1_fixtures import ENV
from consumer_fixtures import approve_budgets
from test_growth_credit_rewrite import declaration, WRITER, FALLBACK


def connection():
    if os.environ.get('POSTRIFF_TEST_OWNED_PG') != 'task9-growth':
        raise RuntimeError('Parent exclusive disposable-PG lease is required; no default port.')
    port=int(os.environ['POSTRIFF_TEST_PG_PORT'])
    if not 1024<=port<=65535: raise RuntimeError('Explicit loopback test port required')
    db=psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres',client_encoding='utf8')
    assert db.info.host=='127.0.0.1' and db.info.port==port
    return db


class RewriteCreditPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            for name in ('pr_workspaces','pr_post_doctor_runs','pr_model_usage_events','pr_credit_quotes','pr_usage_ledger'):
                assert db.execute('SELECT to_regclass(%s)',('public.'+name,)).fetchone()[0], 'Parent Task5/6 schema required'

    def setUp(self):
        self.now=[float(int(time.time()))];self.actor=str(uuid.uuid4());self.sent=[];self.costs=[];self.failures=[]
        self.hook=None;self.malformed=False;self.provider_override=None;self.models=ComparisonModels()
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)',(self.actor,))
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=false WHERE id='creator-v1'")
        def verify(token):
            if token!='synthetic-growth':raise AlphaError('Verified synthetic session required',401)
            return self.actor
        verify.session_id=lambda token,principal:'synthetic-growth-session'
        verify.auth_time=lambda token,principal:self.now[0]
        def transport(method,url,headers=None,body=None,**kw):
            # A different connection can see the concrete credit hold before *every* rewrite IO.
            with connection() as db:
                reservations=db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'",(self.wid,)).fetchall()
            self.sent.append({'body':copy.deepcopy(body),'committedCredits':[r[0] for r in reservations if r[0]]})
            index=len(self.sent)-1
            if self.hook:self.hook(index,body)
            if 'messages' in body:
                value=json.loads(body['messages'][-1]['content'])
                if 'original' in value:
                    content,_=self.models.chat(body['messages'],body['model'],body['max_tokens'],1)
                else:
                    content=json.dumps({'answers':self.models.evaluate(value['state'],value['questions'],timeout_s=1).answers})
                data={'choices':[] if self.malformed else [{'message':{'content':content}}]}
            else:
                data={'answers':self.models.evaluate(body['state'],body['questions'],timeout_s=1).answers}
            provider=self.provider_override or body['model'].split('/')[0]
            cost=self.costs[index] if index<len(self.costs) else .004
            data.update(model=body['model'],usage={'cost':.99},providerMetadata={'gateway':{'cost':cost,'generationId':'opaque-'+str(index),'routing':{'finalProvider':provider}}})
            return {'status':self.failures[index] if index<len(self.failures) else 200,'body':data}
        self.runtime=ServerModelRuntime('synthetic-only',model=WRITER,models=[WRITER,FALLBACK],
            prices={WRITER:(.1,.4),FALLBACK:(.1,.4)},transport=transport)
        self.host=HostedWorkspaceService(connection,verify,clock=lambda:self.now[0],ideas_runtime=self.runtime,
                                         credits_enabled=True,pricing_v2_enabled=True)
        self.wid=self.host.bootstrap('synthetic-growth')['workspaceId']
        policy=declaration();policy['expiresAt']=int(self.now[0])+3600
        for route in policy['routes']:route['ceilingUsdMicro']=20000
        self.g=self.host.growth=GrowthService(self.host,env={**ENV,'POSTRIFF_POST_DOCTOR_V2':'1','POSTRIFF_JEV':'1',
            'AI_GATEWAY_API_KEY':'synthetic-only',ENV_KEY:json.dumps(policy),'POSTRIFF_GROWTH_PLATFORM_PREVIEW':json.dumps({
            'approved':True,'id':'synthetic-baseline-only','attemptMaxUsdMicro':20000,'dailyUsdMicro':2000000,
            'monthlyUsdMicro':4000000,'dailyRuns':100,'workspaceDailyRuns':2,'maxInputBytes':64000,'maxOutputTokens':1500})})
        saved=self.host.get(self.wid,'synthetic-growth')
        self.g.action(self.wid,'synthetic-growth',saved['revision'],'growth_consent',{'confirmed':True,'routes':[*ROUTES,'cloud:vercel-ai-gateway:'+WRITER]})
        baseline=self.g.check(self.wid,'synthetic-growth',{'text':'One idea. Another idea!','platform':'Threads','language':'en','confirmed':True,'requestKey':str(uuid.uuid4())})
        self.check_id=baseline['runId'];self.sent.clear()
        with connection() as db:
            ent=db.execute("SELECT entitlements FROM pr_plan_terms WHERE id='creator-v1'").fetchone()[0]
            self.host.billing._reconcile_entitlement(db.cursor(),self.wid,'creator-v1',ent,self.now[0]+600)
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,current_period_end,provider_subscription_id,price_variant_id) VALUES(%s,'creator-v1','stripe','active',to_timestamp(%s),%s,'creator-49-v1') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end,price_variant_id='creator-49-v1'",(self.wid,self.now[0]+600,'sub_synthetic_growth_'+self.wid))
            self.host.ledger._credit_book.grant(db.cursor(),self.wid,self.actor,'synthetic-growth-fund-'+self.wid,100000,None)
        approve_budgets(connection,self.wid)

    def request(self):return {'checkId':self.check_id,'model':WRITER,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())}

    def estimate(self,payload):return self.host.ideas.credit_requests.estimate(self.wid,'synthetic-growth',{'operation':'post-doctor-rewrite','request':payload})

    def quote(self,payload):
        estimate=self.estimate(payload)
        q=self.host.ideas.credit_requests.issue(self.wid,'synthetic-growth',{'operation':'post-doctor-rewrite','request':payload,'expectedRevision':estimate['stateRevision'],'maxMilliCredits':estimate['ceilingMilliCredits']})
        return {**payload,'expectedRevision':estimate['stateRevision'],'creditQuoteId':q['quoteId']}

    def rewrite(self,payload):return self.g.rewrite(self.wid,'synthetic-growth',payload)

    def wallet(self):
        with connection() as db:return self.host.ledger._credit_book.view(db.cursor(),self.wid)

    def accounting(self):
        with connection() as db:
            return db.execute("SELECT kind,actual_usd_micro,cost_state,meta->'credits' FROM pr_usage_ledger WHERE workspace_id=%s AND meta->>'growthRunId' IS NOT NULL OR workspace_id=%s AND reservation_id IN (SELECT id FROM pr_usage_ledger WHERE workspace_id=%s AND meta->>'growthRunId' IS NOT NULL) ORDER BY at,id",(self.wid,self.wid,self.wid)).fetchall()

    def test_full_pipeline_committed_credit_hold_actual_sum_and_quote_free_replay(self):
        body=self.request();estimate=self.estimate(body)
        self.assertEqual(estimate['ceilingMilliCredits'],78000)
        self.assertEqual(estimate['estimateKind'],'maximum')
        result=self.rewrite(self.quote(body))
        self.assertEqual(len(self.sent),5)
        self.assertTrue(all(call['committedCredits'][0]['maximum']==78000 for call in self.sent))
        self.assertEqual(result['userMilliCreditsCharged'],6000)
        self.assertEqual((self.wallet()['heldMilliCredits'],self.wallet()['usedMilliCredits']),(0,6000))
        self.assertEqual(self.rewrite(body),result)  # No consumed quote is needed for exact completed replay.
        self.assertTrue(self.estimate(body)['cached'])
        self.assertEqual(len(self.sent),5)
        self.assertEqual([r[1] for r in self.accounting() if r[1] is not None],[20000])

    def test_known_failed_envelope_is_customer_zero_and_platform_actual(self):
        self.malformed=True
        with self.assertRaises(AlphaError):self.rewrite(self.quote(self.request()))
        self.assertEqual(len(self.sent),1)
        self.assertEqual((self.wallet()['heldMilliCredits'],self.wallet()['usedMilliCredits']),(0,0))
        self.assertEqual([r[1] for r in self.accounting() if r[1] is not None],[4000])

    def test_unknown_holds_and_does_not_retry_or_requote_same_run(self):
        self.costs=[None]
        body=self.request()
        with self.assertRaises(AlphaError):self.rewrite(self.quote(body))
        with self.assertRaises(AlphaError):self.estimate(body)
        self.assertEqual(len(self.sent),1)
        self.assertEqual((self.wallet()['heldMilliCredits'],self.wallet()['usedMilliCredits']),(78000,0))
        self.assertTrue(any(r[2]=='estimated_unknown' for r in self.accounting()))

    def test_final_above_max_is_absorbed_without_an_extra_customer_debit(self):
        self.costs=[.004,.004,.004,.004,.3]
        result=self.rewrite(self.quote(self.request()))
        self.assertEqual(result['userMilliCreditsCharged'],78000)
        self.assertEqual(self.wallet()['usedMilliCredits'],78000)
        settle=next(r for r in self.accounting() if r[0]=='settle')
        self.assertEqual((settle[1],settle[3]['absorbed']),(316000,16800))

    def test_revocation_between_comparisons_stops_next_io_but_keeps_invoice(self):
        def revoke(index,body):
            if index==3:
                saved=self.host.get(self.wid,'synthetic-growth')
                self.g.action(self.wid,'synthetic-growth',saved['revision'],'growth_consent',{'confirmed':True,'routes':[]})
        self.hook=revoke
        with self.assertRaises(AlphaError):self.rewrite(self.quote(self.request()))
        self.assertEqual(len(self.sent),4)
        self.assertEqual(self.wallet()['usedMilliCredits'],0)
        self.assertEqual([r[1] for r in self.accounting() if r[1] is not None],[16000])

    def test_known_jev_failures_retry_then_fallback_all_physically_accounted(self):
        self.failures=[200,500,500,200,200,200,200]
        self.rewrite(self.quote(self.request()))
        self.assertEqual(len(self.sent),7)
        self.assertEqual(self.wallet()['usedMilliCredits'],8400)
        self.assertEqual(self.sent[3]['body']['model'],FALLBACK)

    def test_changed_ceiling_and_policy_require_new_max_before_io(self):
        payload=self.quote(self.request())
        policy=json.loads(self.g.env[ENV_KEY]);policy['routes'][2]['ceilingUsdMicro']+=1
        self.g.env[ENV_KEY]=json.dumps(policy)
        with self.assertRaises(AlphaError):self.rewrite(payload)
        self.assertEqual(self.sent,[])

    def test_client_prices_foreign_quote_and_default_off_cannot_fund_io(self):
        payload=self.quote(self.request())
        with self.assertRaises(AlphaError):self.rewrite({**payload,'facts':{'own':'changed'}})
        with self.assertRaises(AlphaError):self.rewrite({**payload,'ceilingUsdMicro':1})
        self.g.env.pop(ENV_KEY)
        with self.assertRaises(AlphaError):self.estimate(self.request())
        self.assertEqual(self.sent,[])

    def test_expiry_during_writer_stops_grounding_and_preserves_invoice(self):
        body=self.request()
        def expire(index,payload):
            if index==0:
                with connection() as db:db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s AND request_key=%s",(self.wid,body['requestKey']))
        self.hook=expire
        with self.assertRaises(AlphaError):self.rewrite(self.quote(body))
        self.assertEqual(len(self.sent),1)
        self.assertEqual((self.wallet()['heldMilliCredits'],self.wallet()['usedMilliCredits']),(0,0))
        self.assertEqual([r[1] for r in self.accounting() if r[1] is not None],[4000])
        self.g.sweep()
        with connection() as db:row=db.execute('SELECT status,body FROM pr_post_doctor_runs WHERE workspace_id=%s AND request_key=%s',(self.wid,body['requestKey'])).fetchone()
        self.assertEqual(row[0],'cancelled')
        self.assertEqual(row[1]['_actualUsage']['usdMicro'],4000)
        self.assertEqual(row[1]['_usageSource']['count'],1)
        self.assertNotIn('rewrite',row[1])

    def test_expired_unknown_hold_survives_sweep_and_cannot_be_requoted(self):
        self.costs=[None];body=self.request()
        with self.assertRaises(AlphaError):self.rewrite(self.quote(body))
        with connection() as db:db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s AND request_key=%s",(self.wid,body['requestKey']))
        self.g.sweep();self.g.sweep()
        with connection() as db:row=db.execute('SELECT status,body FROM pr_post_doctor_runs WHERE workspace_id=%s AND request_key=%s',(self.wid,body['requestKey'])).fetchone()
        self.assertEqual(row[0],'cancelled')
        self.assertTrue(row[1]['_actualUsage']['unknown'])
        self.assertEqual(row[1]['_usageSource']['count'],1)
        self.assertIn('_creditFunding',row[1])
        with self.assertRaises(AlphaError):self.estimate(body)
        self.assertEqual((self.wallet()['heldMilliCredits'],self.wallet()['usedMilliCredits']),(78000,0))
        self.assertEqual(len(self.sent),1)

    def test_expired_completed_rewrite_removes_private_content_keeps_accounting(self):
        body=self.request();result=self.rewrite(self.quote(body))
        with connection() as db:db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s AND id=%s",(self.wid,result['runId']))
        self.g.sweep();self.g.sweep()
        with connection() as db:row=db.execute('SELECT status,body,accepted_changes FROM pr_post_doctor_runs WHERE workspace_id=%s AND id=%s',(self.wid,result['runId'])).fetchone()
        self.assertEqual(row[0],'cancelled');self.assertEqual(row[2],[])
        self.assertEqual(row[1]['_actualUsage']['usdMicro'],20000)
        self.assertEqual(row[1]['_creditSettlement']['usedMilliCredits'],6000)
        self.assertTrue(all(k.startswith('_') for k in row[1]))
        self.assertEqual((self.wallet()['heldMilliCredits'],self.wallet()['usedMilliCredits']),(0,6000))
        self.assertEqual(len(self.sent),5)


if __name__=='__main__':unittest.main(verbosity=2)
