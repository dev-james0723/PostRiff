"""Meaningful statistics, abstention, provenance and action-boundary checks; no network."""
import copy
import unittest
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
        job={'id':'11','state':'verified','providerReference':'abc','verification':{'at':1,'method':'provider_lookup'},'manifest':{'execution':'hosted-live','channelId':'own','payload':{'text':'Original text'}}}
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


if __name__=='__main__':unittest.main()
