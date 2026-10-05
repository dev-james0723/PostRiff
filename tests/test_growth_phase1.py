import copy
import io
import json
import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.growth import genome, performance, rewrite, router
from postriff_phase2.growth.service import bindings_current, current_genome, public_result
from postriff_phase2.growth.usage import MemoryUsageSink
from postriff_phase2.hosted_app import HostedApplication


def post(i,value,**changes):
    return {'id':str(i),'sourceId':str(i),'sourceRevision':1,'grantsDigest':'a','platform':'Threads','connectionId':'one','language':'en',
            'format':'text','timeBucket':'unknown','labels':{'hook':'question'},'scores':{'hook':.9},
            'readings':{'24h':{'likes':{'value':value,'availability':'available','definitionVersion':'native-v1','provenance':'official'}}},**changes}


class Performance(unittest.TestCase):
    def test_like_for_like_missing_and_zero(self):
        target=post(4,8);peers=[post(i,i) for i in range(4)]+[target,post('other',100,connectionId='two')]
        result=performance.compare(target,peers,'24h')['metrics']['likes']
        self.assertEqual(result['baselineCount'],4)
        self.assertEqual(result['median'],1.5)
        self.assertEqual(result['percentile'],100)
        self.assertEqual(performance.compare(target,peers,'1h')['status'],'unavailable')
        self.assertIsNone(performance.compare(post('t',None),peers,'24h')['metrics']['likes']['value'])
        zeros=[post(i,0) for i in range(4)]
        self.assertIsNone(performance.compare(target,zeros,'24h')['metrics']['likes']['multiple'])
        self.assertIsNone(performance.compare(target,zeros[:2],'24h')['metrics']['likes']['median'])

    def test_incompatible_definitions_do_not_pool(self):
        peers=[post(i,i) for i in range(4)]
        for p in peers:p['readings']['24h']['likes']['definitionVersion']='user-export:24h'
        result=performance.compare(post('t',10),peers,'24h')['metrics']['likes']
        self.assertEqual(result['baselineCount'],0)

    def test_prediction_hook_failure_preserves_previous(self):
        calls=[]
        class Cur:
            def execute(self,sql,args=None):
                calls.append(sql)
                if sql.startswith('INSERT'):raise RuntimeError('No schema')
        job={'id':'j','manifest':{'postDoctor':{'levels':[]}},'verification':{'at':1},'providerReference':'p'}
        performance.then_capture(lambda *_:calls.append('previous'),True)(Cur(),'w',job)
        self.assertEqual(calls[0],'previous')
        self.assertIn('ROLLBACK TO SAVEPOINT growth_prediction',calls)


class Genome(unittest.TestCase):
    def test_writing_only_grades_and_no_inferred_metrics(self):
        posts=[post(i,i,readings={}) for i in range(3)]
        result=genome.proposal(posts)
        self.assertEqual(result['measuredPosts'],0)
        self.assertEqual(result['statements'][0]['kind'],'writing')
        self.assertEqual(result['statements'][0]['grade'],'supported')
        self.assertIsNone(genome.fit_winners({'hook':.8},posts,posts[0]))

    def test_conflicting_evidence_and_winners_need_ten(self):
        posts=[post(i,i) for i in range(10)]
        result=genome.proposal(posts)
        self.assertEqual(result['statements'][0]['grade'],'conflicting')
        self.assertTrue(result['statements'][0]['counterEvidenceIds'])
        self.assertIsNotNone(genome.fit_winners({'hook':.9},posts,posts[0]))
        self.assertIsNone(genome.fit_winners({'hook':.9},posts[:9],posts[0]))
        posts[-1]['readings']['24h']={'shares':{'value':20,'availability':'available','definitionVersion':'native-v1','provenance':'official'}}
        self.assertIsNone(genome.fit_winners({'hook':.9},posts,posts[0]))

    def test_csv_numbers_horizons_and_limits(self):
        row=genome.parse_upload('text,platform,likes\nA thought,Threads,4\n')[0]
        self.assertIsNone(row['horizon'])
        for value in ('NaN','inf','-1'):
            with self.assertRaises(AlphaError):genome.parse_upload(f'text,platform,likes\nA thought,Threads,{value}\n')
        with self.assertRaises(AlphaError):genome.parse_upload('text,platform,horizon\nA thought,Threads,now\n')
        with self.assertRaises(AlphaError):genome.parse_upload('text,platform\n'+'post,Threads\n'*21)

    def test_genome_evidence_keeps_uploaded_and_official_readings_separate(self):
        posts=[]
        for prefix,version,provenance in (('native','native-v1','official'),('export','user-export:24h','user_supplied')):
            for i,value in enumerate((1,2,3,20,21)):
                sample=post(prefix+str(i),value,labels={'hook':'question'} if i>=3 else {})
                sample['readings']['24h']['likes'].update(definitionVersion=version,provenance=provenance)
                posts.append(sample)
        statements=genome.proposal(posts)['statements']
        self.assertEqual(len(statements),2)
        self.assertEqual({s['definitionVersion'] for s in statements},{'native-v1',None})
        self.assertTrue(all(s['grade']=='limited' and len(s['evidenceIds'])==2 for s in statements))
        self.assertEqual({tuple(s['provenance']) for s in statements},{('official',),()})
        self.assertEqual({s['kind'] for s in statements}, {'performance', 'writing'}, 'uploaded counts cannot teach outcome strategy')

    def test_grant_and_revision_revocation_fence_active_genome(self):
        source={'id':'s','active':True,'selected':True,'revision':1,'useGrants':{'a':'b'}, 'authoredByConfirmed':'synthetic-owner', 'label':'representative'}
        state={'sources':[source],'growthConsent':{'routes':['test']}}
        binding={'id':'s','revision':1,'grantsDigest':digest(source['useGrants'])}
        state['brandHub']={'genome':{'status':'approved','evidenceBindings':[binding],'consentDigest':digest(state['growthConsent'])}}
        self.assertIsNotNone(current_genome(state))
        source['useGrants']={}
        self.assertFalse(bindings_current(state,[binding]))
        self.assertIsNone(current_genome(state))


class Rewrite(unittest.TestCase):
    def test_selection_and_fact_validation(self):
        original='One idea. Another idea!\n最後一句。'
        data={'changes':[{'index':1,'text':' A clearer idea!','dimension':'clarity','usesFacts':[]}],'missingFacts':[],'notes':''}
        valid=rewrite.validate(data,original,{})
        self.assertEqual(rewrite.apply(original,valid['changes'],[]),original)
        self.assertEqual(rewrite.apply(original,valid['changes'],['1']),'One idea. A clearer idea!\n最後一句。')
        with self.assertRaises(AlphaError):rewrite.apply(original,valid['changes'],['9'])
        data['changes'][0]['text']=' Earned 700 views!'
        with self.assertRaises(AlphaError):rewrite.validate(data,original,{})
        data['changes'][0]['usesFacts']=['real']
        self.assertIn('700',rewrite.validate(data,original,{'real':'My post earned 700 views.'})['rewrite'])

    def test_unknown_cost_stays_unknown_and_malformed_does_not_retry(self):
        sink=MemoryUsageSink();calls=[]
        def chat(*args):calls.append(args);return 'invalid JSON',{}
        r=router.AIModelRouter(chat=chat,usage=sink)
        with self.assertRaises(router.RouterError):r.complete_json('postdoctor.rewrite',[],validate=lambda d:d)
        self.assertEqual(len(calls),1)
        self.assertIsNone(sink.events[0].cost_usd)

    def test_public_result_has_no_private_payload(self):
        result=public_result({'dimensions':[],'draft':'secret','_scores':{'a':.1},'runId':'private','helping':['Hook']})
        self.assertEqual(result,{'dimensions':[],'helping':['Hook']})


class HTTP(unittest.TestCase):
    def test_public_post_requires_origin_guard(self):
        app=HostedApplication(service=SimpleNamespace(growth=SimpleNamespace(public_check=lambda *_:{})))
        raw=json.dumps({'confirmed':True,'text':'test','platform':'Threads'}).encode()
        environ={'REQUEST_METHOD':'POST','PATH_INFO':'/api/post-doctor','wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw)),
                 'HTTP_HOST':'local.test','wsgi.url_scheme':'https'}
        status=[]
        b''.join(app(environ,lambda s,h:status.append(s)))
        self.assertTrue(status[0].startswith('403'))


if __name__=='__main__':unittest.main()
