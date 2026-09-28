import copy
import unittest
import uuid
from unittest.mock import Mock, patch
from postriff_phase2.growth.trends import advanced_pipeline as advanced, contracts, semantic_admission as S
import test_trend_text_context as context_fixture


class SemanticAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = context_fixture.TextContextTests()
        context_fixture.TextContextTests.setUpClass()

    def setUp(self):
        self.inputs = self.fixture.inputs()
        s = self.inputs['common']['sources'][0]
        sid = s['source_id']; text = self.inputs['facts'][sid]['text']
        self.result = {'task':'trend.semantic_label_generate','executed_model':'synthetic-model','status':'ok','input_digest':'a'*64,
            'items':[{'id':'synthetic-item','concept':'Practice','claim':'Slow practice helps precision','stance':'supports',
                'language':s['language'],'uncertainties':['Synthetic test interpretation, not empirical qualification.'],
                'evidence_spans':[{'observation_id':sid,'start':0,'end':len(text),'text':text}]}]}
        self.entry = {'task':'semantic_label_generate','result':self.result,'qualified':False,'available_at':context_fixture.NOW,'expires_at':self.inputs['expires_at']}
        self.wid = str(uuid.uuid4()); self.actor = str(uuid.uuid4()); self.rid = str(uuid.uuid4())
        self.projection = {'scope_key':'workspace:'+self.wid,'kind':'model_judgment','object_id':str(uuid.uuid4()),
            'revision':1,'projection_id':str(uuid.uuid4()),'validity':'valid','available_at':context_fixture.NOW,'expires_at':self.inputs['expires_at'],'payload':{'result':self.result}}

    def test_actual_generation_unqualified_stays_candidate_not_public_genome(self):
        adapted = S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        self.assertEqual(adapted['dimensions'], {})
        self.assertEqual(adapted['annotations'], [])
        self.assertEqual(adapted['candidates'][0]['qualification'],'unqualified')
        value = advanced.build_projection('genome',self.inputs,now=context_fixture.NOW,semantic=adapted)
        self.assertTrue(all(c['mode']=='exact_native_wording' for c in value['details']['period_membership']['day']['clusters']))

    def test_reviewed_actual_items_feed_genome_and_native_periods(self):
        self.entry['qualified'] = True
        adapted = S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        self.assertEqual(adapted['dimensions']['topic_narrative']['value'],self.result['items'][0]['claim'])
        value = advanced.build_projection('genome',self.inputs,now=context_fixture.NOW,
            semantic_dimensions=adapted['dimensions'],semantic=adapted)
        self.assertTrue(any(c['mode']=='reviewed_claim' for c in value['details']['period_membership']['day']['clusters']))
        span = adapted['annotations'][0]['original_spans'][0]
        original = self.inputs['facts'][span['source_id']]['text']
        self.assertEqual(span['text'], original[span['start']:span['end']])
        self.assertEqual(span['text'], original.splitlines()[0])

    def test_actual_adapted_items_feed_separate_saturation_and_graph_builders(self):
        # The model labels an actual source in the current comparison window.
        source=self.inputs['common']['sources'][-1];sid=source['source_id'];text=self.inputs['facts'][sid]['text']
        self.result['items'][0]['evidence_spans']=[{'observation_id':sid,'start':0,'end':len(text),'text':text}]
        self.entry['qualified']=True
        adapted=S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        result=advanced.build_projection('saturation',self.inputs,now=context_fixture.NOW,
            semantic=adapted,semantic_selected=[self.entry])
        for name in ('topic','narrative'):
            row=result['details']['dimensions'][name]
            self.assertGreater(row['classified_count'],0)
            self.assertIsNone(row['redundancy_ratio'])
            wire=next(d for d in result['payload']['dimensions'] if d['dimension']==name)
            self.assertEqual(wire['sample_details']['patterns'],row['patterns'][:20])
            self.assertEqual(wire['sample_details']['classification_coverage'],row['classification_coverage'])
        graph=advanced.build_projection('graph',self.inputs,now=context_fixture.NOW,semantic=adapted)
        self.assertTrue({'topic','narrative_episode','phrase'} <= {n['node_type'] for n in graph['details']['nodes']})
        self.assertEqual(graph['details']['source_decision_cutoff'],self.inputs['common']['decision_cutoff'])
        self.assertTrue(graph['details']['semantic_support']['nodes'])
        before=advanced._fingerprint('m','saturation','artifact',None,None,[])
        after=advanced._fingerprint('m','saturation','artifact',None,None,[{'different':'annotation'}])
        self.assertNotEqual(before,after)

    def test_tampered_span_or_current_llm_denial_refuses_candidate_reuse(self):
        for cause in ('tamper','rights'):
            with self.subTest(cause=cause):
                inputs=copy.deepcopy(self.inputs); entry=copy.deepcopy(self.entry)
                if cause=='tamper': entry['result']['items'][0]['evidence_spans'][0]['text']='different'
                else: inputs['common']['sources'][0]['rights']['llm']=False
                with self.assertRaises(ValueError): S.adapt(inputs,[entry],context_fixture.NOW)

    def test_conflicting_same_source_abstains_independent_of_item_order(self):
        self.entry['qualified'] = True
        opposite=copy.deepcopy(self.result['items'][0]); opposite.update(id='opposing',stance='opposes')
        self.result['items'].append(opposite)
        first=S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        self.result['items'].reverse()
        second=S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        self.assertEqual(first,second)
        self.assertEqual(first['annotations'],[])
        self.assertNotIn('topic_narrative',first['dimensions'])
        self.assertEqual(len(first['candidates']),2)
        self.assertTrue(first['conflicts'])

    def test_real_storage_time_not_receipt_cutoff_no_computed_time_invented(self):
        self.entry['qualified']=True
        adapted=S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        self.assertEqual(adapted['annotations'][0]['available_at'],context_fixture.NOW)
        self.assertNotIn('computed_at',self.result)
        for key in ('available_at','expires_at'):
            entry=copy.deepcopy(self.entry)
            entry[key]='2030-01-01T00:00:00Z' if key=='available_at' else '2000-01-01T00:00:00Z'
            self.assertEqual(S.adapt(self.inputs,[entry],context_fixture.NOW)['annotations'],[])
        entry=copy.deepcopy(self.entry);entry.pop('available_at')
        self.assertEqual(S.adapt(self.inputs,[entry],context_fixture.NOW)['annotations'],[])

    def test_multiple_independent_claims_do_not_become_one_global_interpretation(self):
        self.entry['qualified']=True
        other=copy.deepcopy(self.result['items'][0]);source=self.inputs['common']['sources'][1]
        text=self.inputs['facts'][source['source_id']]['text']
        other.update(id='second',concept='Another',claim='Another distinct episode',
            evidence_spans=[{'observation_id':source['source_id'],'start':0,'end':len(text),'text':text}])
        self.result['items'].append(other)
        adapted=S.adapt(self.inputs,[self.entry],context_fixture.NOW)
        self.assertEqual(len(adapted['annotations']),2)
        self.assertNotIn('topic_narrative',adapted['dimensions'])

    def test_qualification_uses_actual040_registry_and_exact_current_three_reviews(self):
        store=Mock(); cur=Mock(); found={'projection':self.projection,'result':self.result}
        cohort=self.inputs['frame']['platform']+':'+self.inputs['frame']['language']
        def review(_w,_a,kind,oid,**_kw):
            if kind == 'model_judgment': return self.projection
            p={'state':'qualified','fixture':False,'reviewed_by':self.actor,'review_ref':'synthetic-review',
                'evaluation_digest':'b'*64,'model_id':'synthetic-model','task':'semantic_label_generate','cohort':cohort}
            gate={**p,'state':'production','role':kind}
            cur.fetchone.return_value=('qualified',None,{'semantic_admission':gate})
            return {**self.projection,'object_id':oid,'kind':kind,'payload':p,'validity':'valid',
                    'method_bundle':{'method_id':'test-reviewed','version':'1'}}
        store.get_projection.side_effect=review
        def read(_s,**kw): return found if kw['task']=='semantic_label_generate' else None
        with patch.object(S,'current_annotations',side_effect=read):
            result,bindings,refs=S.load(store,cur,workspace_id=self.wid,actor_id=self.actor,receipt_id=self.rid,
                state={},inputs=self.inputs,values={})
            self.assertTrue(result[0]['qualified']); self.assertEqual(len(refs),4)
            self.assertEqual(len(bindings[0]['qualification_refs']),3)
            store.get_projection.side_effect=lambda _w,_a,kind,*a,**kw: self.projection if kind=='model_judgment' else None
            with self.assertRaises(ValueError):
                S.load(store,cur,workspace_id=self.wid,actor_id=self.actor,receipt_id=self.rid,
                    state={},inputs=self.inputs,values={},expected=bindings)


class CurrentReviewTests(unittest.TestCase):
    def setUp(self):
        self.wid=str(uuid.uuid4());self.actor=str(uuid.uuid4());self.store=Mock();self.cur=Mock()
        self.payload={'result':{'executed_model':'synthetic','items':[]},'context_revision':'current-context'}
        self.model={'object_id':str(uuid.uuid4()),'revision':1,'validity':'valid','scope_key':'workspace:'+self.wid,
                    'policy':{'llm_process':True},'payload':self.payload}
        self.reviews={}
        self.bound={'task':'semantic_label_generate','cohort':'bluesky:yue','object_id':self.model['object_id'],'revision':1,
                    'projection_digest':contracts.digest(self.payload),'qualification_refs':[]}
        for kind in ('model_qualification','task_qualification','cohort_qualification'):
            payload={'state':'qualified','fixture':False,'reviewed_by':self.actor,'review_ref':'synthetic',
                     'evaluation_digest':'a'*64,'model_id':'synthetic','task':'semantic_label_generate','cohort':'bluesky:yue'}
            record={'object_id':str(uuid.uuid4()),'revision':1,'validity':'valid','scope_key':'workspace:'+self.wid,
                    'payload':payload,'method_bundle':{'method_id':kind,'version':'1'}}
            self.reviews[kind]=record
            self.bound['qualification_refs'].append({'kind':kind,'object_id':record['object_id'],'revision':1,'digest':contracts.digest(payload)})
        def get(w,a,kind,oid,**kwargs):
            if kind=='model_judgment':return self.model
            self.kind=kind;return self.reviews[kind]
        self.store.get_projection.side_effect=get
        self.state='qualified';self.release='production'
        self.cur.fetchone.side_effect=lambda:(self.state,None,{'semantic_admission':{'state':self.release,'role':self.kind,
            'model_id':'synthetic','task':'semantic_label_generate','cohort':'bluesky:yue'}})

    def validate(self):
        with patch('postriff_phase2.growth.trends.generation.workspace_context',return_value={'revision':'current-context'}):
            S.validate_current(self.store,self.cur,self.wid,self.actor,{},[self.bound])

    def test_current_read_requires_three_production_reviews_and_never_mutates(self):
        self.validate();self.store.lock_dependencies.assert_not_called();self.store.put_projection.assert_not_called()
        for status,release in (('shadow','production'),('qualified','shadow')):
            self.state,self.release=status,release
            with self.assertRaisesRegex(ValueError,'review_changed'):self.validate()
        self.state,self.release='qualified','production'
        self.reviews['cohort_qualification']['revision']=2
        with self.assertRaisesRegex(ValueError,'review_changed'):self.validate()

    def test_source_model_context_and_review_reviewer_revocation_fail_closed(self):
        self.model['policy']['llm_process']=False
        with self.assertRaisesRegex(ValueError,'binding_changed'):self.validate()
        self.model['policy']['llm_process']=True
        with patch('postriff_phase2.growth.trends.generation.workspace_context',return_value={'revision':'new'}):
            with self.assertRaisesRegex(ValueError,'context_changed'):
                S.validate_current(self.store,self.cur,self.wid,self.actor,{},[self.bound])
        self.store._actor.side_effect=contracts.ContractError('workspace_access_denied')
        with self.assertRaises(ValueError):self.validate()


if __name__=='__main__': unittest.main()
