"""Whitespace producer: offline contract checks and explicitly allocated real SQL.

All source, fact and review records are synthetic test data. A tested admission
branch is not empirical model/task/cohort qualification. No provider/model calls.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import os
import unittest
from unittest.mock import Mock, patch
import uuid

from postriff_phase2.growth.trends import contracts, text_context, whitespace_admission as W
from postriff_phase2.growth.trends.store import TrendStorageError

NOW = '2026-09-27T20:01:00Z'
END = '2026-09-28T00:00:00Z'


def dedicated_test_dsn(dsn=None):
    """Reject libpq redirects before the wrapper or fixture opens a connection."""
    from psycopg.conninfo import conninfo_to_dict
    dsn = os.environ.get('TREND_WHITESPACE_TEST_DSN', '') if dsn is None else dsn
    p = conninfo_to_dict(dsn)
    if (set(p)-{'host','port','dbname','user'}
            or (p.get('host'),p.get('port'),p.get('dbname')) != ('127.0.0.1','55438','postgres')
            or any(k in os.environ for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'))):
        raise ValueError('exact allocated portable whitespace target required')
    return dsn


def flags(wid):
    return {**{'RAFII_TREND_'+n+'_ENABLED':'true' for n in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','WHITESPACE')},
            'RAFII_TREND_WORKSPACE_ALLOWLIST':wid}


def fixture():
    wid, actor, tid, rid = [str(uuid.uuid4()) for _ in range(4)]
    texts = ['點樣練慢啲？\n原文甲', '點樣練慢啲？\n原文乙', '逐步試慢練，記錄結果。']
    ids = [str(uuid.uuid4()) for _ in texts]
    sources = [{'source_id':sid,'scope_key':'shared:synthetic','platform':'bluesky','language':'yue',
        'event_at':'2026-09-27T19:30:00Z','available_at':'2026-09-27T19:31:00Z','expires_at':END,
        'original':True,'creator_key':'synthetic-'+str(i),
        'rights':{'creative':True,'analysis':True,'display':True,'llm':True}}
        for i,sid in enumerate(ids)]
    inputs = {'common':{'scope_key':'shared:synthetic','decision_cutoff':NOW,'sources':sources,'coverage':{}},
        'facts':{sid:{'text':text,'provider_id':'synthetic','source_identity':sid,'relations':[]} for sid,text in zip(ids,texts)},
        'frame':{'frame_id':'synthetic-comparison','platform':'bluesky','language':'yue',
                 'window_start':'2026-09-27T19:00:00Z','window_end':'2026-09-27T20:00:00Z'},
        'expires_at':END,'episode_id':str(uuid.uuid4())}
    state={'workspace':{'id':wid},'sources':[{'id':'owned-fact-source','active':True,'selected':True,'kind':'text',
        'sourcePolicy':'public_quote','facts':[{'id':'approved-fact','text':'I have an owned practice notebook.','approved':True}]}]}
    selected=[{'task':'semantic_label_generate','qualified':True,'expires_at':END,'available_at':NOW,
        'result':{'task':'trend.semantic_label_generate','status':'ok','executed_model':'synthetic-only','computed_at':NOW,
            'input_digest':'a'*64,'items':[{'language':'yue','concept':'slow practice','claim':'asks about slow practice','stance':'supports',
                'uncertainties':['Synthetic test review, not empirical qualification.'],
                'evidence_spans':[{'observation_id':sid,'start':0,'end':len(text),'text':text} for sid,text in zip(ids,texts)]}]}}]
    bindings=[{'task':'semantic_label_generate','object_id':str(uuid.uuid4()),'revision':1,'result_digest':'a'*64}]
    offered=text_context.question_candidates(inputs);cid=offered['candidates'][0]['candidate_id']
    facts=W.workspace_facts(state)
    review={'payload':{'schema_version':W.REVIEW_SCHEMA,'workspace_id':wid,'trend_id':tid,'candidate_id':cid,
        'candidate_revision':1,'trust_receipt_id':rid,'receipt_revision':1,'frame_id':inputs['frame']['frame_id'],
        'context_digest':facts['context_digest'],'facts_digest':facts['facts_digest'],
        'semantic_bindings_digest':contracts.digest(bindings),'demand_evidence_refs':ids[:2],
        'demand_strength':'supported','gap_type':'practical_example','confirmed_user_fact_refs':['approved-fact'],
        'supply_comparison':{'frame_id':inputs['frame']['frame_id'],'scope':'observed_comparison_sample',
                             'evidence_refs':ids,'expected_units':3,'context_complete':True},
        'supporting_supply_refs':[],'opposing_supply_refs':[ids[2]],'credibility':'supported',
        'risk_assessment':'clear','originality_review':'supported','proposed_contribution':'Use the owned notebook to demonstrate slow practice.',
        'risks':['Sample only.'],'disconfirming_evidence':['One existing example is present.']}}
    return dict(inputs=inputs,candidate_payload=offered,reviews={cid:review},selected=selected,semantic_bindings=bindings,
        state=state,workspace_id=wid,trend_id=tid,receipt_id=rid,receipt_revision=1,candidate_revision=1,now=NOW),actor


def assess(value):
    p=deepcopy(value);inputs=p.pop('inputs');return W.assess(inputs,**p)


class WhitespaceUnitTests(unittest.TestCase):
    def setUp(self):
        self.p,self.actor=fixture()
        for name in ('socket.create_connection','socket.socket.connect','socket.getaddrinfo','urllib.request.urlopen'):
            guard=patch(name,side_effect=AssertionError('network forbidden'));mock=guard.start()
            self.addCleanup(guard.stop);self.addCleanup(mock.assert_not_called)

    def review(self,p=None):return next(iter((p or self.p)['reviews'].values()))['payload']

    def test_actual_evaluator_admits_only_reviewed_sample_and_keeps_global_qualification_unknown(self):
        with patch.object(W.whitespace,'find_whitespace',wraps=W.whitespace.find_whitespace) as pure:
            result=assess(self.p)
        self.assertEqual(pure.call_count,1);self.assertEqual(result['state'],'admitted')
        self.assertEqual(result['semantic_qualification'],'unqualified')
        self.assertEqual(result['opportunities'][0]['supply_search_scope']['retrieval_coverage'],1)
        self.assertNotIn('原文',contracts.canonical(result));self.assertNotIn('I have an owned',contracts.canonical(result))
        self.assertEqual(result['opportunities'][0]['credibility']['approved_fact_refs'],['approved-fact'])

    def test_actual_unreviewed_candidate_is_readable_gap_with_no_opportunity(self):
        self.p.update(reviews={},selected=[],semantic_bindings=[])
        result=assess(self.p)
        self.assertEqual(result['state'],'review_required');self.assertEqual(result['opportunities'],[])
        self.assertEqual(result['gaps'][0]['known_creator_count'],2)
        self.assertIn('still require current review',result['gaps'][0]['summary'])
        self.assertIn('current_candidate_review_required',result['rejected'][0]['reasons'])
        self.assertIn('reviewed_semantic_support_required',result['rejected'][0]['reasons'])

    def test_model_presence_cannot_self_qualify(self):
        self.p['selected'][0]['qualified']=False
        self.assertEqual(assess(self.p)['opportunities'],[])

    def test_all_exact_binding_changes_fail_closed(self):
        for key in ('workspace_id','trend_id','candidate_id','candidate_revision','trust_receipt_id','receipt_revision',
                    'frame_id','context_digest','facts_digest','semantic_bindings_digest'):
            p=deepcopy(self.p);self.review(p)[key]='changed'
            with self.subTest(key=key):self.assertEqual(assess(p)['opportunities'],[])

    def test_numerator_is_measured_and_small_comparison_coverage_is_insufficient(self):
        self.review()['supply_comparison'].update(expected_units=10,observed_units=10,retrieval_coverage=1.0)
        result=assess(self.p);self.assertFalse(result['opportunities'])
        self.assertIn('supply_comparison_insufficient',result['rejected'][0]['reasons'])
        self.review()['supply_comparison']['expected_units']=True
        self.assertFalse(assess(self.p)['opportunities'])

    def test_uncollected_replies_cannot_establish_unanswered_question(self):
        self.review()['gap_type']='unanswered_question'
        result=assess(self.p)
        self.assertFalse(result['opportunities']);self.assertIn('uncollected_or_deleted_replies',result['rejected'][0]['reasons'])

    def test_forbidden_and_unapproved_facts_and_boundaries_are_not_credibility(self):
        for mutation in ('policy','approval','boundary','selection'):
            p=deepcopy(self.p);source=p['state']['sources'][0]
            if mutation=='policy':source['sourcePolicy']='prohibited'
            if mutation=='approval':source['facts'][0]['approved']=False
            if mutation=='selection':source['selected']=False
            if mutation=='boundary':p['state']['profile']={'fields':[{'id':'privacy','value':'private constraint','privacy':'private'}]}
            self.assertEqual(assess(p)['opportunities'],[],mutation)

    def test_exact_native_support_and_current_llm_rights_required(self):
        for mutation in ('span','rights'):
            p=deepcopy(self.p)
            if mutation=='span':p['selected'][0]['result']['items'][0]['evidence_spans'][0]['text']='invented'
            else:p['inputs']['common']['sources'][0]['rights']['llm']=False
            with self.assertRaises(ValueError):assess(p)

    def test_arbitrary_request_candidate_and_foreign_supply_never_admitted(self):
        p=deepcopy(self.p);p['candidate_payload']['candidates'][0]['literal_question_digest']='fake'
        with self.assertRaisesRegex(ValueError,'candidate_changed'):assess(p)
        p=deepcopy(self.p);self.review(p)['opposing_supply_refs']=['foreign']
        self.assertFalse(assess(p)['opportunities'])
        p=deepcopy(self.p);self.review(p)['supply_comparison']['evidence_refs']=['foreign']
        self.assertFalse(assess(p)['opportunities'])

    def test_fewer_than_two_independent_creators_invalidates_stored_candidate(self):
        for s in self.p['inputs']['common']['sources']:s['creator_key']='one-author'
        with self.assertRaisesRegex(ValueError,'candidate_changed'):assess(self.p)

    def test_flags_off_no_allowlist_or_feature_disabled_never_opens_store(self):
        wid=self.p['workspace_id'];tid=self.p['trend_id']
        for values in ({},flags(str(uuid.uuid4())),{**flags(wid),'RAFII_TREND_WHITESPACE_ENABLED':'false'}):
            store=Mock();store.transaction.side_effect=AssertionError('disabled DB')
            worker=W.WhitespaceAdmission(store,values=values)
            self.assertEqual(worker.refresh(wid,self.actor,tid),{'state':'disabled'})
            self.assertIsNone(worker.current_result(wid,self.actor,tid,cursor=Mock()))
            if not values:self.assertEqual(worker.plan_current()['state'],'disabled')
            store.transaction.assert_not_called()

    def test_read_rechecks_context_and_never_writes(self):
        data=assess(self.p);data['input_digest']='stable';wid=self.p['workspace_id'];tid=self.p['trend_id']
        store=Mock();store.get_projection.return_value={'validity':'valid','scope_key':'workspace:'+wid,
            'policy':{'display_excerpt':True},'payload':data}
        worker=W.WhitespaceAdmission(store,values=flags(wid))
        with patch.object(worker,'_workspace_state',return_value=self.p['state']), patch.object(W,'_validate_binding'):
            self.assertEqual(worker.current_result(wid,self.actor,tid,cursor=Mock()),data)
        with patch.object(worker,'_workspace_state',return_value=self.p['state']), patch.object(W,'_validate_binding',side_effect=ValueError('changed')):
            self.assertIsNone(worker.current_result(wid,self.actor,tid,cursor=Mock()))
        store.put_projection.assert_not_called();store.put_manifest.assert_not_called()
        store.get_projection.return_value['policy']['display_excerpt']=False
        self.assertIsNone(worker.current_result(wid,self.actor,tid,cursor=Mock()))

    def test_operator_review_requires_independent_production_method_and_reviewer(self):
        wid=self.p['workspace_id'];store=Mock();cur=Mock()
        r={'validity':'valid','scope_key':'workspace:'+wid,'method_bundle':{'method_id':'synthetic-review','version':'1'},
           'payload':{'schema_version':W.REVIEW_SCHEMA,'fixture':False,'review_ref':'synthetic-review',
                      'reviewed_by':self.actor,'evaluation_digest':'a'*64}}
        store.get_projection.return_value=r;worker=W.WhitespaceAdmission(store)
        cfg={'whitespace_admission':{'state':'production','role':'gap_review','schema_version':W.REVIEW_SCHEMA}}
        for status in (('shadow',None,cfg),('qualified',NOW,cfg),('qualified',None,{})):
            cur.fetchone.return_value=status
            self.assertIsNone(worker._review(cur,wid,self.actor,self.p['trend_id'],'candidate'))
        cur.fetchone.return_value=('qualified',None,cfg)
        self.assertEqual(worker._review(cur,wid,self.actor,self.p['trend_id'],'candidate'),r)
        store._actor.assert_called_once_with(cur,wid,self.actor,write=True)
        r['payload']['fixture']=True
        self.assertIsNone(worker._review(cur,wid,self.actor,self.p['trend_id'],'candidate'))

    def test_planner_bounds_and_review_identity_are_workspace_scoped(self):
        worker=W.WhitespaceAdmission(Mock(),values={})
        for bounds in ({'max_workspaces':3},{'max_workspaces':True},{'trend_limit':0}):
            with self.assertRaises(ValueError):worker.plan_current(**bounds)
        tid=self.p['trend_id'];wid=self.p['workspace_id']
        self.assertNotEqual(W.review_id(wid,tid,'c'),W.review_id(str(uuid.uuid4()),tid,'c'))

    def test_reviewed_contribution_reuses_original_option_and_fact_binding_contract(self):
        p=deepcopy(self.p);state=p['state'];state['memoryEgress']={'cloud':True}
        state['sources'][0]['egressConsent']=['cloud']
        state['phase2']={'channels':[{'id':'c','platform':'Bluesky','language':'yue','revoked':False}]}
        data=assess(self.p);data['input_digest']='synthetic-input'
        trend={'object_id':p['trend_id'],'payload':{'canonical_topic':'practice'}}
        options=W._option_candidates(data,state,trend,p['inputs'],p['selected'],NOW)
        self.assertEqual(len(options),1);op=options[0]
        self.assertFalse(op['qualified']);self.assertTrue(op['executable_ready']);self.assertEqual(op['state'],'suggested')
        self.assertEqual(op['angles'][0]['premise_fact_ids'],['approved-fact'])
        W.generation.validate_context_binding(state,op['generation_context'])
        state['sources'][0]['facts'][0]['approved']=False
        with self.assertRaises(Exception):W.generation.validate_context_binding(state,op['generation_context'])

    def test_no_new_fact_or_literal_copy_can_enter_bridge(self):
        p=deepcopy(self.p);state=p['state'];state['memoryEgress']={'cloud':True}
        state['sources'][0]['egressConsent']=['cloud'];state['phase2']={'channels':[{'id':'c','platform':'bluesky'}]}
        data=assess(self.p);data['input_digest']='synthetic'
        trend={'object_id':p['trend_id'],'payload':{'canonical_topic':'practice'}}
        data['opportunities'][0]['credibility']['approved_fact_refs']=['foreign-fact']
        self.assertEqual(W._option_candidates(data,state,trend,p['inputs'],p['selected'],NOW),[])
        data=assess(self.p);data['input_digest']='synthetic'
        state['memoryEgress']['cloud']=False
        self.assertEqual(W._option_candidates(data,state,trend,p['inputs'],p['selected'],NOW),[])

    def test_new_accepted_source_does_not_invalidate_its_own_fact_binding(self):
        before=W.workspace_facts(self.p['state'])
        state=deepcopy(self.p['state']);state['sources'].append({'id':'accepted','active':True,'selected':True,
            'kind':'idea','sourcePolicy':'public_quote','facts':[],'origin':{'kind':'trend_opportunity'}})
        self.assertEqual(W.workspace_facts(state),before)

    def test_future_semantic_knowledge_cannot_support_gap(self):
        self.p['selected'][0]['result']['computed_at']='2026-09-27T21:00:00Z'
        self.assertEqual(assess(self.p)['opportunities'],[])

    def test_existing_other_opportunity_validator_is_noop(self):
        store=Mock();W.validate_opportunity(store,cursor=Mock(),workspace_id=self.p['workspace_id'],
            actor_id=self.actor,opportunity={'id':'ordinary'},state={})
        store.get_projection.assert_not_called();store.lock_dependencies.assert_not_called()

    def test_dedicated_dsn_rejects_redirects_before_connect(self):
        safe='host=127.0.0.1 port=55438 dbname=postgres'
        with patch('psycopg.connect',side_effect=AssertionError('guard must not connect')) as connect:
            with patch.dict(os.environ,{},clear=True):
                self.assertEqual(dedicated_test_dsn(safe),safe)
                self.assertEqual(dedicated_test_dsn(safe+' user=synthetic'),safe+' user=synthetic')
                for suffix in (' hostaddr=192.0.2.1',' service=remote',' servicefile=/tmp/redirect',
                               ' options=-csearch_path=other',' password=synthetic',' sslmode=require'):
                    with self.subTest(suffix=suffix), self.assertRaises(Exception):dedicated_test_dsn(safe+suffix)
                for dsn in ('','host=localhost port=55438 dbname=postgres','host=127.0.0.1 port=56451 dbname=postgres',
                            'host=127.0.0.1 port=55438 dbname=production'):
                    with self.subTest(dsn=dsn), self.assertRaises(ValueError):dedicated_test_dsn(dsn)
                for variable in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'):
                    for value in ('','redirect'):
                        with patch.dict(os.environ,{variable:value}), self.assertRaises(ValueError):dedicated_test_dsn(safe)
            connect.assert_not_called()


@unittest.skipUnless(os.environ.get('TREND_WHITESPACE_TEST_DSN'),'explicit disposable whitespace DSN required')
class WhitespacePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_trend_enrichment as E
        dsn=dedicated_test_dsn()
        with patch.dict(os.environ,{'TREND_ENRICHMENT_TEST_DSN':dsn}):E.EnrichmentPostgresTests.setUpClass.__func__(cls)

    def setUp(self):
        import test_trend_enrichment as E
        from postriff_phase2.growth.trends.store import TrendStore
        import test_trend_generation as G
        put=TrendStore.put_observation;register=TrendStore.register_policy
        def policy(store,value,**kwargs):
            value=deepcopy(value);value['model_generation']=G.review(self.prefix)
            return register(store,value,**kwargs)
        def question(store,value,**kwargs):
            value=deepcopy(value);value['payload']['is_repost']=False
            value['payload']['text']='香港麵包焗爐應該點調溫度？\n原生實驗記錄 '+value['source_identity']
            value['payload_digest']=contracts.digest(value['payload'])
            return put(store,value,**kwargs)
        # Alter only the synthetic acquisition fixture before real persistence.
        with patch.object(TrendStore,'put_observation',question), patch.object(TrendStore,'register_policy',policy):
            E.EnrichmentPostgresTests.setUp(self)
        self.tid=self.store.get_receipt(self.wid,self.actor,self.rid)['payload']['trend_id']
        self.values.update(flags(self.wid));self.values['RAFII_TREND_MODEL_ENRICHMENT_ENABLED']='false'
        advanced=W.AdvancedPipeline(self.store,values=self.values)
        job=advanced.enqueue(self.wid,self.actor,self.tid,kinds=['whitespace_candidate'])['jobs'][0]
        advanced.run('workspace:'+self.wid,job['job_id'])
        self.admission=W.WhitespaceAdmission(self.store,values=self.values)
        for name in ('socket.create_connection','socket.socket.connect','socket.getaddrinfo','urllib.request.urlopen'):
            guard=patch(name,side_effect=AssertionError('external I/O forbidden'));mock=guard.start()
            self.addCleanup(guard.stop);self.addCleanup(mock.assert_not_called)

    def current(self):
        with self.store.transaction() as cur:return self.admission.current_result(self.wid,self.actor,self.tid,cursor=cur)

    def test_real_producer_persists_readable_gap_dag_and_reuses_revision_without_dispatch(self):
        response=self.admission.plan_current();self.assertEqual(response['stored'],1,response)
        data=self.current();self.assertEqual(data['state'],'review_required');self.assertEqual(data['opportunities'],[])
        self.assertTrue(data['gaps']);self.assertEqual(data['trust_receipt_id'],self.rid)
        replay=self.admission.refresh(self.wid,self.actor,self.tid);self.assertEqual(replay['state'],'reused');self.assertEqual(replay['revision'],1)
        with self.connect() as db:
            refs=db.execute("SELECT DISTINCT n.input_scope_key FROM pr_trend_manifest_inputs n JOIN pr_trend_projections p USING(scope_key,manifest_id) WHERE p.scope_key=%s AND p.kind='whitespace' AND p.object_id=%s",('workspace:'+self.wid,self.tid)).fetchall()
            self.assertEqual(set(r[0] for r in refs),{self.scope,'workspace:'+self.wid})
            self.assertEqual(db.execute('SELECT count(*) FROM pr_model_usage_events WHERE workspace_id=%s',(self.wid,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM pr_trend_projections WHERE scope_key=%s AND kind='opportunity'",('workspace:'+self.wid,)).fetchone()[0],0)
        self.assertEqual(self.calls,[])

    def test_context_change_hides_saved_gap_until_new_revision(self):
        self.admission.refresh(self.wid,self.actor,self.tid)
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{brandHub,audience}','\"Changed audience\"'::jsonb) WHERE id=%s",(self.wid,))
        self.assertIsNone(self.current())
        self.assertEqual(self.admission.refresh(self.wid,self.actor,self.tid)['revision'],2)
        self.assertIsNotNone(self.current())

    def test_revocation_removes_result_and_prevents_new_derivative(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        self.admission.refresh(self.wid,self.actor,self.tid)
        revoke_policy(self.store,self.scope,self.provider,'1')
        self.assertIsNone(self.current())
        with self.assertRaises(ValueError):self.admission.refresh(self.wid,self.actor,self.tid)
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,'whitespace',self.tid)['payload'])

    def test_foreign_actor_and_viewer_cannot_mutate(self):
        self.admission.refresh(self.wid,self.actor,self.tid)
        with self.assertRaises(ValueError):self.admission.refresh(self.wid,str(uuid.uuid4()),self.tid)
        with self.connect() as db:db.execute("UPDATE pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(self.wid,self.actor))
        with self.assertRaises(ValueError):self.admission.refresh(self.wid,self.actor,self.tid)

    def test_caller_transaction_rolls_back_projection(self):
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with self.store.transaction() as cur:
                self.admission.refresh(self.wid,self.actor,self.tid,cursor=cur)
                raise RuntimeError('rollback')
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,'whitespace',self.tid))

    def test_shadow_operator_method_cannot_promote_question_candidate(self):
        self.admission.refresh(self.wid,self.actor,self.tid)
        saved=self.store.get_projection(self.wid,self.actor,'whitespace_candidate',self.tid)
        cid=saved['payload']['candidates'][0]['candidate_id']
        with self.store.transaction() as cur:
            scope='workspace:'+self.wid
            self.store.put_method('synthetic.gap.review','shadow','a'*64,{'whitespace_admission':{'state':'production','role':'gap_review','schema_version':W.REVIEW_SCHEMA}},cursor=cur)
            now=contracts.iso(contracts.instant(W.utcnow()))
            manifest=self.store.put_manifest(scope,[{'scope_key':saved['scope_key'],'node_id':saved['projection_id']}],decision_cutoff=now,available_at=now,retention_until=saved['expires_at'],cursor=cur)
            self.store.put_projection({'scope_key':scope,'kind':'whitespace','object_id':W.review_id(self.wid,self.tid,cid),'revision':1,
                'method_id':'synthetic.gap.review','method_version':'shadow','manifest_id':manifest['manifest_id'],
                'decision_cutoff':now,'available_at':now,'retention_until':saved['expires_at'],'payload':{'schema_version':W.REVIEW_SCHEMA,
                    'fixture':False,'review_ref':'synthetic','reviewed_by':self.actor,'evaluation_digest':'a'*64}},cursor=cur)
        self.assertEqual(self.admission.refresh(self.wid,self.actor,self.tid)['state'],'reused')
        self.assertEqual(self.current()['opportunities'],[])

    def prepare_admitted(self):
        """Real stored generation + three explicitly synthetic production gate fixtures."""
        import test_trend_generation as G
        from postriff_phase2.model_runtime import ServerModelRuntime
        from postriff_phase2.ideas import IdeasService
        from postriff_phase2.coworker.service import CoworkerService
        from postriff_phase2.growth.trends.service import TrendService
        self.state['memoryEgress']={'cloud':True}
        self.state['phase2']['channels']=[{'id':'bake','platform':'Bluesky','language':'yue','revoked':False}]
        self.state['sources']=[{'id':'fact-source','text':'Owned notebook','kind':'idea','active':True,'selected':True,
            'sourcePolicy':'public_quote','egressConsent':['cloud'],'useApprovals':[],
            'facts':[{'id':'fact1','approved':True,'text':'I keep a baking notebook.'}]}]
        with self.connect() as db:db.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(self.state),self.wid))
        self.values['RAFII_TREND_MODEL_ENRICHMENT_ENABLED']='true'
        self.generation_calls=[]
        def transport(method,url,*,headers,body,timeout):
            self.generation_calls.append(body);pack=json.loads(body['messages'][1]['content'])
            output=G.output('semantic_label_generate',pack)
            output['items'][0]['evidence_spans']=[{'observation_id':e['observation_id'],'start':0,
                'end':min(200,len(e['text'])),'text':e['text'][:200]} for e in pack['evidence']]
            return {'status':200,'body':{'model':G.MODEL,'choices':[{'message':{'content':json.dumps(output)},'finish_reason':'stop'}],
                'usage':{'cost':.0001}}}
        runtime=ServerModelRuntime('synthetic',model=G.MODEL,transport=transport)
        self.hosted.ideas=IdeasService(self.hosted.repository,self.hosted.repository.commands,runtime=runtime,runtimes=[runtime],researcher=False)
        self.hosted.commands=self.hosted.repository.commands;self.hosted.connection_factory=self.connect
        gen=W.generation.TrendGeneration(self.hosted,store=self.store,values=self.values,monotonic=lambda:0)
        queued=gen.enqueue(self.wid,self.actor,self.rid,'semantic_label_generate',idempotency_key='synthetic-whitespace-semantics')
        self.assertEqual(gen.tick()['attached'],1)
        self.assertEqual(len(self.generation_calls),1)
        self.svc=TrendService(CoworkerService(self.hosted,values=self.values),cursor_secret=b'synthetic-whitespace-key-32bytes')
        with self.store.transaction() as cur:
            model=self.store.get_projection(self.wid,self.actor,'model_judgment',queued['result_id'],cursor=cur)
            expiry=model['expires_at'];scope='workspace:'+self.wid;now=W.utcnow()
            for kind in ('model_qualification','task_qualification','cohort_qualification'):
                oid=W.semantic_admission.review_id(self.wid,kind,G.MODEL,'semantic_label_generate','bluesky:yue')
                cfg={'semantic_admission':{'state':'production','role':kind,'model_id':G.MODEL,'task':'semantic_label_generate','cohort':'bluesky:yue'}}
                mid='synthetic.whitespace.'+kind+'.'+self.prefix
                self.store.put_method(mid,'1','a'*64,cfg,cursor=cur)
                cur.execute("UPDATE pr_trend_method_versions SET qualification='qualified' WHERE method_id=%s AND version='1'",(mid,))
                manifest=self.store.put_manifest(scope,[{'scope_key':scope,'node_id':model['projection_id']}],decision_cutoff=now,available_at=now,retention_until=expiry,cursor=cur)
                self.store.put_projection({'scope_key':scope,'kind':kind,'object_id':oid,'revision':1,'manifest_id':manifest['manifest_id'],
                    'method_id':mid,'method_version':'1','decision_cutoff':now,'available_at':now,'retention_until':expiry,
                    'payload':{'state':'qualified','fixture':False,'review_ref':'SYNTHETIC TEST BRANCH ONLY; not empirical qualification',
                        'reviewed_by':self.actor,'evaluation_digest':'a'*64,'model_id':G.MODEL,'task':'semantic_label_generate','cohort':'bluesky:yue'}},cursor=cur)
            trend,receipt,manifest,inputs=W.AdvancedPipeline(self.store,values=self.values)._load(cur,self.wid,self.actor,self.tid)
            selected,bindings,refs=W.semantic_admission.load(self.store,cur,workspace_id=self.wid,actor_id=self.actor,
                receipt_id=self.rid,state=self.state,inputs=inputs,values=self.values)
            self.assertTrue(selected[0]['qualified'])
            candidate=self.store.get_projection(self.wid,self.actor,'whitespace_candidate',self.tid,cursor=cur)
            c=candidate['payload']['candidates'][0];facts=W.workspace_facts(self.state)
            p={'schema_version':W.REVIEW_SCHEMA,'fixture':False,'review_ref':'SYNTHETIC GAP REVIEW ONLY',
                'reviewed_by':self.actor,'evaluation_digest':'b'*64,'workspace_id':self.wid,'trend_id':self.tid,
                'candidate_id':c['candidate_id'],'candidate_revision':candidate['revision'],'trust_receipt_id':self.rid,
                'receipt_revision':receipt['revision'],'frame_id':inputs['frame']['frame_id'],
                'context_digest':facts['context_digest'],'facts_digest':facts['facts_digest'],
                'semantic_bindings_digest':contracts.digest(bindings),'gap_type':'practical_example','demand_strength':'supported',
                'demand_evidence_refs':c['evidence_refs'],'supporting_supply_refs':[],'opposing_supply_refs':[],
                'supply_comparison':{'frame_id':inputs['frame']['frame_id'],'scope':'observed_comparison_sample',
                    'evidence_refs':c['evidence_refs'],'expected_units':len(c['evidence_refs']),'context_complete':False},
                'confirmed_user_fact_refs':['fact1'],'credibility':'supported','risk_assessment':'clear','originality_review':'supported',
                'proposed_contribution':'Use the owned baking notebook to outline a temperature comparison, leaving outcomes unclaimed.',
                'risks':['Observed sample only.'],'disconfirming_evidence':[]}
            self.review_oid=W.review_id(self.wid,self.tid,c['candidate_id'])
            mid='synthetic.whitespace.gap.'+self.prefix
            self.store.put_method(mid,'1','b'*64,{'whitespace_admission':{'state':'production','role':'gap_review','schema_version':W.REVIEW_SCHEMA}},cursor=cur)
            cur.execute("UPDATE pr_trend_method_versions SET qualification='qualified' WHERE method_id=%s AND version='1'",(mid,))
            now=W.utcnow();m=self.store.put_manifest(scope,[{'scope_key':scope,'node_id':candidate['projection_id']},*refs],
                decision_cutoff=now,available_at=now,retention_until=expiry,cursor=cur)
            self.review_record={'scope_key':scope,'kind':'whitespace','object_id':self.review_oid,'revision':1,
                'manifest_id':m['manifest_id'],'method_id':mid,'method_version':'1','decision_cutoff':now,
                'available_at':now,'retention_until':expiry,'payload':p}
            self.store.put_projection(self.review_record,cursor=cur)

    def test_admitted_gap_creates_ordinary_opportunity_and_existing_accept_replays(self):
        self.prepare_admitted()
        self.admission.refresh(self.wid,self.actor,self.tid)
        data=self.current();self.assertEqual(data['state'],'admitted');self.assertEqual(len(data['opportunity_refs']),1)
        ref=data['opportunity_refs'][0];oid=ref['opportunity_id']
        raw=self.store.get_opportunity(self.wid,self.actor,oid)['payload']
        self.assertFalse(raw['qualified']);self.assertTrue(raw['executable_ready']);self.assertEqual(raw['semantic_qualification'],'unqualified')
        wire=self.svc.opportunity(self.wid,'fixture',oid)['data'];self.assertEqual(wire['state'],'ready')
        selection={'revision':1,'angle_id':wire['angles'][0]['id'],'channel_id':'bake','goal':'Outline a careful notebook experiment','idempotency_key':'whitespace-accept'}
        first=self.svc.accept(self.wid,'fixture',oid,selection);second=self.svc.accept(self.wid,'fixture',oid,selection)
        self.assertEqual(first['data']['source_id'],second['data']['source_id'])
        state=self.hosted.repository.get(self.wid,'fixture')['state']
        lineage=W.opportunities.lineage(state,[first['data']['source_id']])[0]
        self.assertEqual(lineage['trust_receipt_id'],self.rid);self.assertEqual(lineage['generation_context']['source_ids'],['fact-source'])
        self.assertEqual(lineage['angle']['whitespace_candidate_id'],ref['candidate_id'])
        self.assertIsNotNone(self.current())
        self.assertEqual(self.admission.refresh(self.wid,self.actor,self.tid)['state'],'reused')
        self.assertEqual(len(self.generation_calls),1)

    def test_admitted_fact_change_blocks_existing_accept_and_lineage(self):
        self.prepare_admitted();self.admission.refresh(self.wid,self.actor,self.tid)
        oid=self.current()['opportunity_refs'][0]['opportunity_id'];wire=self.svc.opportunity(self.wid,'fixture',oid)['data']
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{sources,0,facts,0,approved}','false'::jsonb) WHERE id=%s",(self.wid,))
        self.assertIsNone(self.current())
        with self.assertRaises(Exception):self.svc.accept(self.wid,'fixture',oid,{'revision':1,'angle_id':wire['angles'][0]['id'],
            'channel_id':'bake','goal':'x','idempotency_key':'stale-fact'})

    def test_new_review_head_blocks_guard_without_requiring_opportunity_refresh(self):
        self.prepare_admitted();self.admission.refresh(self.wid,self.actor,self.tid)
        oid=self.current()['opportunity_refs'][0]['opportunity_id'];raw=self.store.get_opportunity(self.wid,self.actor,oid)['payload']
        with self.store.transaction() as cur:
            W.validate_opportunity(self.store,cursor=cur,workspace_id=self.wid,actor_id=self.actor,opportunity=raw,state=self.state,mutation=True)
            revised={**self.review_record,'revision':2,'payload':{**self.review_record['payload'],'risk_assessment':'blocked'}}
            self.store.put_projection(revised,expected_revision=1,cursor=cur)
        self.assertIsNone(self.current())
        with self.store.transaction() as cur, self.assertRaises(ValueError):
            W.validate_opportunity(self.store,cursor=cur,workspace_id=self.wid,actor_id=self.actor,opportunity=raw,state=self.state,mutation=True)

    def test_admitted_gap_and_opportunity_rollback_together(self):
        self.prepare_admitted();put=self.store.put_projection
        def fail_opportunity(value,**kwargs):
            if value['kind']=='opportunity':raise RuntimeError('synthetic atomic rollback')
            return put(value,**kwargs)
        with patch.object(self.store,'put_projection',fail_opportunity), self.assertRaisesRegex(RuntimeError,'atomic rollback'):
            self.admission.refresh(self.wid,self.actor,self.tid)
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,'whitespace',self.tid))
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_trend_projections WHERE scope_key=%s AND kind='opportunity'",('workspace:'+self.wid,)).fetchone()[0],0)

    def assert_unavailable(self, callback, *, status=503):
        from postriff_alpha.domain import AlphaError
        with self.assertRaises(AlphaError) as caught:callback()
        self.assertEqual(caught.exception.status,status)

    def accept_admitted(self):
        self.admission.refresh(self.wid,self.actor,self.tid)
        oid=self.current()['opportunity_refs'][0]['opportunity_id']
        wire=self.svc.opportunity(self.wid,'fixture',oid)['data']
        request={'revision':wire['revision'],'angle_id':wire['angles'][0]['id'],'channel_id':'bake',
            'goal':'Describe an owned notebook experiment without claiming outcomes','idempotency_key':'current-read-lineage'}
        response=self.svc.accept(self.wid,'fixture',oid,request)
        state=self.hosted.repository.get(self.wid,'fixture')['state']
        lineage=W.opportunities.lineage(state,[response['data']['source_id']])
        return oid,request,state,lineage

    def advanced_results(self):
        enabled={'RAFII_TREND_GRAPH_GENOME_ENABLED':'true','RAFII_TREND_SATURATION_ENABLED':'true'}
        self.values.update(enabled)
        # CoworkerService snapshots deployment values at construction; enable
        # the actual authenticated read surface as well as the local worker.
        self.svc.values.update(enabled)
        advanced=W.AdvancedPipeline(self.store,values=self.values)
        jobs=advanced.enqueue(self.wid,self.actor,self.tid,kinds=['genome','saturation','graph'])['jobs']
        self.assertEqual(len(jobs),3)
        for job in jobs:
            result=advanced.run('workspace:'+self.wid,job['job_id'])
            self.assertEqual(result['state'],'succeeded',result)
        results={}
        for kind in ('genome','saturation','graph'):
            saved=self.store.get_projection(self.wid,self.actor,kind,self.tid)
            self.assertEqual(saved['validity'],'valid');self.assertTrue(saved['payload']['_semantic_bindings'])
            with self.store.transaction() as cur:
                cur.execute('SELECT manifest_id FROM pr_trend_projections WHERE scope_key=%s AND kind=%s AND object_id=%s AND revision=%s',
                    (saved['scope_key'],kind,saved['object_id'],saved['revision']))
                manifest=self.store.get_manifest(saved['scope_key'],str(cur.fetchone()[0]),cursor=cur)
            for chunk in manifest['chunks']:self.assertEqual(contracts.digest(chunk['payload']),chunk['digest'])
            full=json.loads(''.join(c['payload']['json'] for c in manifest['chunks']))
            digest=contracts.digest({k:v for k,v in full.items() if k!='manifest_digest'})
            self.assertEqual(digest,manifest['document_digest']);self.assertEqual(digest,full['manifest_digest'])
            self.assertEqual(digest,manifest['recipe']['detail_codec']['pure_manifest_digest'])
            results[kind]=(saved,full['details'])
        with self.connect() as db:
            states=db.execute("SELECT state,provider_id,reservation_id FROM pr_trend_jobs WHERE scope_key=%s AND job_id=ANY(%s::uuid[])",
                ('workspace:'+self.wid,[j['job_id'] for j in jobs])).fetchall()
            self.assertEqual(states,[('succeeded',None,None)]*3)
        self.assertEqual(len(self.generation_calls),1)
        return results

    def test_service_whitespace_typed_reads_hide_operator_review_rows(self):
        self.prepare_admitted();self.admission.refresh(self.wid,self.actor,self.tid)
        current=self.current();self.assertEqual(current['state'],'admitted')
        direct=self.svc.get(self.wid,'fixture',self.tid,resource='whitespace')['data']
        stored=self.svc.stored(self.wid,'fixture','whitespace',self.tid)['data']
        listed=self.svc.stored(self.wid,'fixture','whitespace')['data']
        self.assertEqual(direct,stored);self.assertEqual(listed,[direct])
        self.assertEqual(direct['schema_version'],W.SCHEMA)
        self.assertEqual(direct['semantic_qualification'],'unqualified')
        self.assertEqual(direct['opportunity_refs'],current['opportunity_refs'])
        for private in ('binding','_admission_binding','reviewed_by','review_ref','evaluation_digest','fixture'):
            self.assertNotIn(private,direct)
        review=self.store.get_projection(self.wid,self.actor,'whitespace',self.review_oid)
        self.assertEqual(review['payload']['schema_version'],W.REVIEW_SCHEMA)
        self.assert_unavailable(lambda:self.svc.stored(self.wid,'fixture','whitespace',self.review_oid))
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone(),(False,False))
            self.assertIsNone(db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0])

    def test_service_accept_replay_apply_and_queue_recheck_superseding_review(self):
        from postriff_phase2.growth.trends.service import validate_stored_bindings,queue_bindings_current
        self.prepare_admitted();oid,request,state,lineage=self.accept_admitted()
        self.assertTrue(lineage)
        with self.store.transaction() as cur:
            validate_stored_bindings(self.connect,cur,self.wid,self.actor,state,lineage,self.svc.clock())
        self.assertTrue(queue_bindings_current(self.connect,state,lineage,self.svc.clock()))
        with self.store.transaction() as cur:
            revised={**self.review_record,'revision':2,'payload':{**self.review_record['payload'],'risk_assessment':'blocked'}}
            self.store.put_projection(revised,expected_revision=1,cursor=cur)
        self.assertIsNone(self.current())
        self.assert_unavailable(lambda:self.svc.get(self.wid,'fixture',self.tid,resource='whitespace'))
        self.assertEqual(self.svc.stored(self.wid,'fixture','whitespace')['data'],[])
        self.assert_unavailable(lambda:self.svc.accept(self.wid,'fixture',oid,request),status=409)
        self.assert_unavailable(lambda:self.svc.accept(self.wid,'fixture',oid,{**request,'idempotency_key':'different-stale-retry'}),status=409)
        with self.store.transaction() as cur,self.assertRaises(ValueError):
            validate_stored_bindings(self.connect,cur,self.wid,self.actor,state,lineage,self.svc.clock())
        self.assertFalse(queue_bindings_current(self.connect,state,lineage,self.svc.clock()))

    def test_advanced_jobs_service_get_semantic_counts_native_graph_and_current_registry(self):
        self.prepare_admitted();results=self.advanced_results()
        for kind,resource in (('genome','genome'),('saturation','saturation'),('graph','propagation')):
            direct=self.svc.get(self.wid,'fixture',self.tid,resource=resource)['data']
            self.assertEqual(direct,self.svc.stored(self.wid,'fixture',resource,self.tid)['data'])
            self.assertEqual(self.svc.stored(self.wid,'fixture',resource)['data'],[direct])
            self.assertNotIn('_semantic_bindings',direct)
        genome=results['genome'][1];self.assertFalse(genome['qualified'])
        self.assertEqual(genome['dimensions']['topic_narrative']['state'],'supported')
        self.assertTrue(genome['dimensions']['topic_narrative']['evidence_refs'])
        saturation=self.svc.get(self.wid,'fixture',self.tid,resource='saturation')['data']
        for dimension in ('topic','narrative'):
            measured=next(d for d in saturation['dimensions'] if d['dimension']==dimension)
            self.assertGreater(measured['classified'],0);self.assertTrue(measured['sample_details']['patterns'])
        support=results['graph'][1]['semantic_support']
        nodes=support['nodes'];kinds={n['node_type'] for n in nodes}
        self.assertTrue({'phrase','topic','narrative_episode'} <= kinds)
        self.assertFalse(support['causal_claims']);self.assertEqual(support['origin'],'unknown')
        for n in nodes:
            if n['node_type']=='phrase':
                self.assertEqual(n['label'],n['original_spans'][0]['text'])
                self.assertEqual(n['language'],'yue');self.assertIn('香港麵包',n['label'])
            if n['node_type'] in ('topic','narrative_episode'):
                self.assertGreater(contracts.instant(n['available_at']),contracts.instant(support['source_decision_cutoff']))
        method='synthetic.whitespace.cohort_qualification.'+self.prefix
        with self.connect() as db:
            original=db.execute("SELECT config FROM pr_trend_method_versions WHERE method_id=%s AND version='1'",(method,)).fetchone()[0]
        for mutation in ('shadow','not_production'):
            with self.subTest(mutation=mutation):
                changed=deepcopy(original)
                if mutation=='not_production':changed['semantic_admission']['state']='shadow'
                with self.connect() as db:
                    db.execute("UPDATE pr_trend_method_versions SET qualification=%s,config=%s::jsonb WHERE method_id=%s AND version='1'",
                        ('shadow' if mutation=='shadow' else 'qualified',json.dumps(changed),method))
                for resource in ('genome','saturation','propagation'):
                    self.assert_unavailable(lambda:self.svc.get(self.wid,'fixture',self.tid,resource=resource))
                    self.assert_unavailable(lambda:self.svc.stored(self.wid,'fixture',resource,self.tid))
                    self.assertEqual(self.svc.stored(self.wid,'fixture',resource)['data'],[])

    def test_viewer_current_reads_and_lineage_do_not_take_edit_dependency_lock(self):
        from postriff_phase2.growth.trends.store import TrendStore
        from postriff_phase2.growth.trends.service import validate_stored_bindings
        self.prepare_admitted();self.advanced_results();oid,request,state,lineage=self.accept_admitted()
        viewer=str(uuid.uuid4())
        with self.psycopg.connect(self.dsn) as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)',(viewer,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(viewer,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')",(self.wid,viewer))
            self.assertEqual(db.execute('SELECT role,status FROM pr_memberships WHERE workspace_id=%s AND user_id=%s',
                (self.wid,self.actor)).fetchone(),('owner','active'))
        # Authentication changes to a real separate viewer; review authority stays owner.
        self.hosted.repository.verify_session=lambda token:viewer
        with patch.object(TrendStore,'lock_dependencies',side_effect=AssertionError('read attempted edit dependency lock')) as lock:
            for resource in ('whitespace','genome','saturation','propagation'):
                self.assertTrue(self.svc.get(self.wid,'viewer-session',self.tid,resource=resource)['data'])
                self.assertEqual(len(self.svc.stored(self.wid,'viewer-session',resource)['data']),1)
            self.assertTrue(self.svc.opportunity(self.wid,'viewer-session',oid)['data'])
            with self.store.transaction() as cur:
                self.assertIsNotNone(self.admission.current_result(self.wid,viewer,self.tid,cursor=cur))
                validate_stored_bindings(self.connect,cur,self.wid,viewer,state,lineage,self.svc.clock(),read_only=True)
            lock.assert_not_called()

    def test_gap_review_registry_downgrade_and_nonproduction_hide_current_service_result(self):
        self.prepare_admitted();self.admission.refresh(self.wid,self.actor,self.tid)
        for role in ('gap','model_qualification','task_qualification','cohort_qualification'):
            method='synthetic.whitespace.'+role+'.'+self.prefix
            with self.connect() as db:
                original=db.execute("SELECT config FROM pr_trend_method_versions WHERE method_id=%s AND version='1'",(method,)).fetchone()[0]
            mutations=('shadow','not_production','role','schema_version') if role=='gap' else ('shadow','not_production','model_id','cohort','task','role')
            for mutation in mutations:
                with self.subTest(role=role,mutation=mutation):
                    changed=deepcopy(original)
                    gate=changed['whitespace_admission' if role=='gap' else 'semantic_admission']
                    if mutation=='not_production':gate['state']='shadow'
                    elif mutation!='shadow':gate[mutation]='wrong-current-binding'
                    try:
                        with self.connect() as db:
                            db.execute("UPDATE pr_trend_method_versions SET qualification=%s,config=%s::jsonb WHERE method_id=%s AND version='1'",
                                ('shadow' if mutation=='shadow' else 'qualified',json.dumps(changed),method))
                        self.assertIsNone(self.current())
                        self.assert_unavailable(lambda:self.svc.get(self.wid,'fixture',self.tid,resource='whitespace'))
                        self.assertEqual(self.svc.stored(self.wid,'fixture','whitespace')['data'],[])
                    finally:
                        with self.connect() as db:
                            db.execute("UPDATE pr_trend_method_versions SET qualification='qualified',config=%s::jsonb WHERE method_id=%s AND version='1'",
                                (json.dumps(original),method))


if __name__=='__main__':unittest.main()
