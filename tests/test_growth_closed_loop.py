"""Meaningful statistics, abstention, provenance and action-boundary checks; no network."""
import copy
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth import audience_miner as miner, creator_calibration as cal, performance, postmortem, questions
from postriff_phase2.growth.decision_loop import DecisionLoop
from postriff_phase2.growth.judgments import JudgmentService, subject_hash
from growth_phase1_fixtures import Models


def observations(n=60):
    posts=[];predictions={}
    for i in range(n):
        # Chronological populations both span the same range; no train/holdout leakage.
        score=(i%20)/20
        post={'id':str(i),'platform':'Threads','connectionId':'own','format':'text','language':'en','timeBucket':'unknown',
              'readings':{'24h':{'shares':{'value':score*100,'availability':'available','definitionVersion':'v1','provenance':'official'}}}}
        posts.append(post)
        predictions[str(i)]={'verifiedAt':i,'scores':{'shareability':score,'specificity':score,'novelty':score},
                             'evaluation':{'model':'typesafe-ai/jev','rubricDigest':'rubric'},
                             'levels':[{'id':'shareability','label':'Share value','level':3,'levelName':'Very strong'}]}
    return posts,predictions


class ClosedLoopTests(unittest.TestCase):
    def test_reading_status_requires_a_mounted_worker_and_its_workspace_admission(self):
        from types import SimpleNamespace
        from postriff_phase2.growth.closed_loop import collection_enabled
        growth=SimpleNamespace(hosted=SimpleNamespace(),env={'POSTRIFF_METRIC_READS':'1'})
        self.assertFalse(collection_enabled(growth,'owned'))
        growth.hosted.metric_reads=SimpleNamespace(workspace_allowed=lambda wid:wid=='owned')
        self.assertTrue(collection_enabled(growth,'owned'))
        self.assertFalse(collection_enabled(growth,'foreign'))
        growth.env={}
        self.assertFalse(collection_enabled(growth,'owned'))

    def test_same_account_cohort_and_version(self):
        posts,predictions=observations()
        result=cal.propose(posts,predictions)
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(len(result['candidates'][0]['dimensions']),3)
        self.assertAlmostEqual(sum(d['weight'] for d in result['candidates'][0]['dimensions']),1,places=5)
        self.assertTrue(all(d['holdoutCount']==18 for d in result['candidates'][0]['dimensions']))
        changed=copy.deepcopy(posts)
        for p in changed[:20]:p['connectionId']='someone-else'
        self.assertEqual(cal.propose(changed,predictions)['candidates'],[])
        changed=copy.deepcopy(posts)
        for p in changed[:20]:p['readings']['24h']['shares']['definitionVersion']='different'
        self.assertEqual(cal.propose(changed,predictions)['candidates'],[])

    def test_small_constant_missing_and_wrong_model(self):
        posts,predictions=observations(49)
        self.assertEqual(cal.propose(posts,predictions)['status'],'insufficient_evidence')
        posts,predictions=observations()
        for pred in predictions.values():pred['scores']={k:.5 for k in pred['scores']}
        self.assertEqual(cal.propose(posts,predictions)['candidates'],[])
        posts,predictions=observations()
        result=cal.propose(posts,predictions)
        self.assertEqual(cal.apply(result,posts[0],'new-model','rubric',{'shareability':.9}),[])
        self.assertTrue(cal.apply(result,posts[0],'typesafe-ai/jev','rubric',{'shareability':.9}))

    def test_holdout_failure_cannot_approve(self):
        posts,predictions=observations()
        for p in posts[42:]:p['readings']['24h']['shares']['value']=100-p['readings']['24h']['shares']['value']
        self.assertEqual(cal.propose(posts,predictions)['candidates'],[])

    def test_publication_boundaries_and_counterexamples(self):
        posts,predictions=observations(12)
        job={'id':'11','state':'verified','providerReference':'abc','verification':{'at':1},'manifest':{'channelId':'own','payload':{'text':'Original text'}}}
        report=postmortem.build(job,predictions['11'],posts,predictions,'24h')
        self.assertTrue(report['comparisons'])
        self.assertEqual(report['comparisons'][0]['status'],'aligned')
        self.assertEqual(report['lessons'][0]['grade'],'conflicting')
        self.assertTrue(report['lessons'][0]['counterEvidenceIds'])
        b=postmortem.binding(job)
        state={'phase2':{'jobs':[job],'channels':[]}}
        self.assertTrue(postmortem.bindings_current(state,[b]))
        state['phase2']['channels']=[{'id':'own','revoked':True}]
        self.assertFalse(postmortem.bindings_current(state,[b]))
        state['phase2']['channels']=[];job['manifest']['payload']['text']='Changed'
        self.assertFalse(postmortem.bindings_current(state,[b]))

    def test_lessons_do_not_mix_opposite_expectations_or_models(self):
        posts,predictions=observations(12)
        job={'id':'11','manifest':{'payload':{'text':'Sample'}}}
        for key,pred in predictions.items():
            if key!='11':pred['levels'][0]['level']=0
        report=postmortem.build(job,predictions['11'],posts,predictions,'24h')
        self.assertEqual(report['lessons'][0]['grade'],'limited')
        self.assertEqual(report['lessons'][0]['evidenceIds'],['11'])
        for key,pred in predictions.items():
            if key!='11':pred['levels'][0]['level']=3;pred['evaluation']['model']='another-model'
        self.assertEqual(postmortem.build(job,predictions['11'],posts,predictions,'24h')['lessons'][0]['grade'],'limited')

    def test_release_gate_rejects_fixtures_and_wrong_assignment(self):
        import importlib.util
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('phase2_gate',Path(__file__).resolve().parents[1]/'scripts/postriff_growth_phase2_gate.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        posts,predictions=observations()
        accounts=[{'accountId':str(i),'arm':cal.assignment('registered',str(i)), 'percentiles':[80 if cal.assignment('registered',str(i))=='shown' else 60]} for i in range(20)]
        data={'execution':'synthetic','experimentId':'registered','elapsedDays':28,'accounts':accounts,'posts':posts,'predictions':predictions,'suggestions':[{'id':'one','written':True}]}
        self.assertFalse(any(module.evaluate(data)['checks'].values()))
        data['execution']='observed'
        self.assertTrue(all(module.evaluate(data)['checks'].values()))
        data['accounts'][0]['arm']='shown' if data['accounts'][0]['arm']=='withheld' else 'withheld'
        with self.assertRaises(ValueError):module.evaluate(data)

    def test_unavailable_and_zero_are_not_success(self):
        posts,predictions=observations(5)
        for p in posts:p['readings']['24h']['shares']['value']=0
        r=performance.compare(posts[-1],posts,'24h')
        self.assertIsNone(r['metrics']['shares']['multiple'])
        self.assertEqual(postmortem.comparison(predictions['4'],r)[0]['status'],'mixed')
        self.assertEqual(postmortem.comparison(None,r),[])

    def test_decision_ids_are_bounded(self):
        loop=DecisionLoop(2)
        self.assertEqual(loop.choose(['owned-a','owned-b'],'send-secret'),'owned-a')
        loop.finish('owned-a','completed')
        self.assertEqual(loop.choose(['owned-a','owned-b'],'owned-a'),'owned-b')
        loop.finish('owned-b','abstained')
        self.assertIsNone(loop.choose(['owned-c']))

    def test_privacy_and_synthesis_validation(self):
        self.assertNotIn('alice@example.com',miner.redact('email alice@example.com @alice https://example.com +1 212 555 1234'))
        self.assertNotIn('@alice',miner.redact('@alice'))
        groups=[{'evidenceIds':['one']}]
        self.assertEqual(miner.validate_synthesis({'suggestions':[{'group':'0','title':'Practice with care','question':'How do you start?'}]},groups)['0']['kind'],'suggested_topic')
        for item in ({'group':'2','title':'x','question':'y'}, {'group':'0','title':'Gain 100 followers','question':'why?'}):
            with self.assertRaises(ValueError):miner.validate_synthesis({'suggestions':[item]},groups)
        self.assertEqual(miner.clusters([{'connectionId':'a','judgment':{'sensitive':True}}]),[])

    def test_uncertain_privacy_is_withheld(self):
        models=Models();qs=questions.get('audience')
        j=JudgmentService(models.router(None).evaluator('audience.classify')).judge(qs,{'comment':'Hello'},scope='personal:one',subject=subject_hash('test','one'),model='typesafe-ai/jev')
        self.assertTrue(miner.classify(j)['sensitive'])

    def test_experiment_gate_is_honest(self):
        accounts=[{'accountId':str(i),'arm':'shown' if i<2 else 'withheld','percentiles':[80 if i<2 else 60]} for i in range(4)]
        self.assertFalse(cal.experiment_report(accounts,27)['targetMet'])
        self.assertFalse(cal.experiment_report(accounts,28,synthetic=True)['targetMet'])
        self.assertEqual(cal.experiment_report(accounts,28)['percentileDifference'],20)
        self.assertEqual(cal.assignment('v3','a'),cal.assignment('v3','a'))
        with self.assertRaises(ValueError):cal.experiment_report([*accounts,accounts[0]],28)



class History(unittest.TestCase):
    def test_backfill_never_enters_a_reading_window_or_comparison(self):
        from unittest.mock import patch
        from postriff_phase2 import insights
        row=('instagram','media-1',None,'views','2026-09',0,'count','available',1_759_617_440.0,1_759_617_440.0,'ig','backfill')
        post={'id':'media-1','provider':'instagram','providerPostId':'media-1','connectionId':'ig','platform':'Instagram','format':'text','language':'en','timeBucket':'unknown'}
        with patch.object(insights,'latest_observations',return_value=[row]):
            attached=performance.attach_readings(None,'w',[post])
        self.assertNotIn('readings',attached[0])
        for horizon in performance.HORIZONS:
            self.assertEqual(performance.compare(attached[0],attached,horizon)['status'],'unavailable')

    def test_history_entry_is_a_lifetime_reading_at_its_age_with_zero_and_missing_kept_apart(self):
        from postriff_phase2.growth.closed_loop import history_entry
        published=1_759_616_041.0;observed=published+1399
        entry=history_entry({'connectionId':'ig','provider':'instagram','providerPostId':'media-1','publishedAt':published,
                             'mediaType':'IMAGE','permalink':'https://www.instagram.com/p/x/'},
                            ('done',None),{'reach':(0.0,'available',observed),'views':(0.0,'available',observed),'likes':(None,'unavailable',observed)})
        self.assertEqual((entry['state'],entry['platform'],entry['ageSeconds'],entry['observedAt']),('backfill','Instagram',1399,observed))
        values={m['metric']:(m['value'],m['availability']) for m in entry['metrics']}
        self.assertEqual(values['reach'],(0.0,'available'))
        self.assertEqual(values['likes'],(None,'unavailable'))
        self.assertEqual(values['saved'],(None,'unavailable'))      # never read: missing, not zero
        self.assertEqual([m['metric'] for m in entry['metrics']],['reach','views','likes','comments','saved','shares'])
        self.assertEqual(history_entry({'connectionId':'ig','provider':'instagram','providerPostId':'m2','publishedAt':published},('pending',None),{})['state'],'scheduled')
        self.assertEqual(history_entry({'connectionId':'ig','provider':'instagram','providerPostId':'m3','publishedAt':published},('unavailable','http_400'),{})['state'],'unavailable')
        self.assertEqual(history_entry({'connectionId':'ig','provider':'instagram','providerPostId':'m4','publishedAt':None},None,{})['state'],'unscheduled')

    def test_a_review_made_under_older_consent_is_stale(self):
        from postriff_phase2.contracts import digest
        from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE,report_consent_current
        consent={'routes':[SUMMARY_ROUTE],'audience':False,'at':1}
        state={'growthConsent':consent}
        self.assertTrue(report_consent_current({'consentDigest':digest(consent)},state))
        self.assertTrue(report_consent_current({},state))
        self.assertFalse(report_consent_current({'consentDigest':digest({**consent,'at':2})},state))
        self.assertFalse(report_consent_current({},{'growthConsent':{'routes':[]}}))


class RunCursor:
    """Answers one paid run's statements: the request-key lookup, budget reservations and the run row."""

    def __init__(self, world):
        self.world, self.rows, self.rowcount = world, [], 1

    def execute(self, sql, params=()):
        text=' '.join(sql.split());w=self.world;w['sql'].append(text)
        if 'unnest(%s::text[]) AS name' in text:self.rows=[(n,) for n in params[0]]
        elif text.startswith('SELECT id::text,status,fingerprint,body,context_fingerprint FROM public.pr_post_doctor_runs'):
            self.rows=[w['existing']] if w.get('existing') else []
        elif text.startswith('UPDATE public.pr_growth_budgets'):self.rows=[] if w.get('limit_reached') else [(1,)]
        else:self.rows=[]

    def fetchone(self):return self.rows[0] if self.rows else None
    def fetchall(self):return list(self.rows)
    def __enter__(self):return self
    def __exit__(self,*a):return False


class RetrySemantics(unittest.TestCase):

    def growth(self,env=None,**world):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from postriff_phase2.growth.service import GrowthService,ROUTES
        from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE
        from growth_phase2_fixtures import ENV
        w={'sql':[],**world}
        state={'growthConsent':{'routes':[*ROUTES,SUMMARY_ROUTE],'audience':True}}
        class Repository:
            effects=[]
            @contextmanager
            def transaction(self,token,wid,**_):
                yield RunCursor(w),(1,state,'owner',False,False,False,False),'actor'
        class Connection:
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def cursor(self):return RunCursor(w)
        hosted=SimpleNamespace(repository=Repository(),clock=lambda:1_760_000_000.0,connection_factory=Connection)
        return GrowthService(hosted,env=dict(ENV if env is None else env)),w,state

    BODY={'jobId':'job','horizon':'24h','confirmed':True,'requestKey':'retry-key-0123456789'}

    def begin(self,growth):
        return growth._begin('w','session','postmortem',dict(self.BODY),lambda cur,state,principal:{'basis':{}})

    def test_a_key_whose_run_failed_without_usage_can_be_rotated_and_retried(self):
        from postriff_phase2.contracts import digest
        cases=(('failed','growth_request_failed'),('cancelled','growth_request_failed'),
               ('unknown','growth_request_unknown'),('running','growth_request_pending'))
        for status,code in cases:
            with self.subTest(status=status):
                growth,w,_=self.growth(existing=('run',status,digest(self.BODY),{},'ctx'))
                with self.assertRaises(AlphaError) as caught:self.begin(growth)
                self.assertEqual((caught.exception.status,caught.exception.code),(409,code))
                self.assertFalse([t for t in w['sql'] if 'pr_growth_budgets' in t or t.startswith('INSERT INTO public.pr_post_doctor_runs')])

    def test_budget_refusals_happen_before_any_run_row_so_the_key_stays_usable(self):
        from growth_phase2_fixtures import ENV
        unset={k:v for k,v in ENV.items() if 'USD_CAP' not in k}
        growth,w,_=self.growth(env=unset)
        with self.assertRaises(AlphaError) as caught:self.begin(growth)
        self.assertEqual((caught.exception.status,caught.exception.code),(503,'growth_budget_unconfigured'))
        self.assertFalse([t for t in w['sql'] if t.startswith('INSERT INTO public.pr_post_doctor_runs')])
        growth,w,_=self.growth(limit_reached=True)
        with self.assertRaises(AlphaError) as caught:self.begin(growth)
        self.assertEqual((caught.exception.status,caught.exception.code),(429,'growth_daily_limit'))
        self.assertFalse([t for t in w['sql'] if t.startswith('INSERT INTO public.pr_post_doctor_runs')])
        growth,w,_=self.growth()
        run=self.begin(growth)
        self.assertEqual(len([t for t in w['sql'] if t.startswith('INSERT INTO public.pr_post_doctor_runs')]),1)
        self.assertTrue(run['id'])

    def test_finish_tells_a_clean_failure_from_an_uncertain_one(self):
        from types import SimpleNamespace
        from postriff_phase2.growth.usage import UsageEvent
        for events,status,code in (([],'failed','growth_request_failed'),
                                   ([UsageEvent(task='postmortem.explain',model='m',route='primary',status='timeout',latency_ms=1,workspace_id='w')],'unknown','growth_request_unknown')):
            with self.subTest(status=status):
                growth,w,state=self.growth()
                run={'id':'run','context':growth._context(state),'prepared':{},'requirement':'edit'}
                with self.assertRaises(AlphaError) as caught:
                    growth._finish('w','session',run,SimpleNamespace(events=events),None,RuntimeError('provider timeout'))
                self.assertEqual((caught.exception.status,caught.exception.code),(503,code))
                update=next(t for t in w['sql'] if t.startswith('UPDATE public.pr_post_doctor_runs SET status=%s'))
                self.assertIn("status='running'",update)

if __name__=='__main__':unittest.main()
