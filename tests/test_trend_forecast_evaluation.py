"""Pure current-store seams; actual arithmetic, no PG or external qualification."""
import copy
import unittest

from postriff_phase2.growth.trends import contracts,forecast,forecast_evaluation as E
from postriff_phase2.growth.trends.pipeline import decode_manifest
from postriff_phase2.growth.trends.store import TrendStorageError
import test_trend_forecast_admission as fixtures


class Cursor(fixtures.MemoryCursor):
    def execute(self,sql,args=()):
        s=self.store
        if 'forecast_evaluation:ancestors' in sql:
            self.calls.append((sql,args));self.result=[]
            c=s.records['forecast_candidate']
            for ref in fixtures.source_bindings(s,c):
                self.result.append({'root':c['projection_id'],'scope_key':ref['scope_key'],'node_id':ref['node_id'],
                                    'observation_id':ref['node_id'],'verification_state':None})
            self.result.append({'root':c['projection_id'],'scope_key':s.scope,'node_id':fixtures.uid('receipt'),
                                'observation_id':None,'verification_state':s.receipt_state})
        elif 'forecast_evaluation:receipt_lock' in sql:
            self.calls.append((sql,args));self.result=[{'scope_key':s.scope,'receipt_id':fixtures.uid('receipt'),'verification_state':s.receipt_state}]
        elif 'forecast_evaluation:observation' in sql:
            self.calls.append((sql,args))
            observation=getattr(s,'observations',{s.observation['source_id']:s.observation}).get(args[1])
            self.result=[copy.deepcopy(observation)] if observation else []
        elif 'forecast_evaluation:entitlement' in sql:
            self.calls.append((sql,args));self.result=[copy.deepcopy(s.entitlement)] if s.entitlement else []
        else:super().execute(sql,args)


class Store(fixtures.MemoryStore):
    def __init__(self,case):
        super().__init__(case);self.cur=Cursor(self);self.evaluations={}

    def get_projection(self,wid,actor,kind,oid,**kwargs):
        if kind=='forecast_evaluation' and oid in self.evaluations:
            self._actor(kwargs['cursor'],wid,actor)
            return copy.deepcopy(self.evaluations[oid])
        return super().get_projection(wid,actor,kind,oid,**kwargs)

    def put_projection(self,value,**kwargs):
        result=super().put_projection(value,**kwargs)
        if value['kind']=='forecast_evaluation':self.evaluations[value['object_id']]=copy.deepcopy(self.forecasts[value['object_id']])
        return result

    def put_manifest(self,scope,inputs,**kwargs):
        result=super().put_manifest(scope,inputs,**kwargs);recipe,chunks=kwargs['recipe'],kwargs['chunks']
        if kwargs.get('manifest_id'):
            self.manifests.pop(result['manifest_id']);result={'manifest_id':kwargs['manifest_id']}
        self.manifests[result['manifest_id']]={'recipe':recipe,'inputs':inputs,'document_digest':kwargs['document_digest'],
            'chunks':[{'ordinal':i,'digest':contracts.digest(c),'payload':c} for i,c in enumerate(chunks)],
            'digest':contracts.digest({'inputs':inputs,'recipe':recipe,'chunks':[contracts.digest(c) for c in chunks]})}
        return result


class Evaluation(unittest.TestCase):
    def setUp(self):
        base=fixtures.Admission();base.setUp();self.addCleanup(base.doCleanups)
        self.wid,self.actor,self.reviewer,self.sid,self.p=base.wid,base.actor,base.reviewer,base.sid,base.p
        self.store=Store(self);self.values=base.values;self.engine=E.ForecastEvaluation(self.store,values=self.values)
        self.candidate_refs=[{'object_id':fixtures.uid('candidate'),'revision':1}]
        self.pre_ref={'object_id':fixtures.uid('preregistration'),'revision':1}
        self.plan={'target':copy.deepcopy(self.p['target']),'method_bundle':self.p['report']['method_bundle'],
            'origins':self.p['origins'],'holdout_episode_ids':self.p['holdout_episode_ids'],
            'excluded_training_episode_ids':[],'holdout_group_ids':[],
            'evaluation_cutoff':fixtures.shifted(self.p['decision_cutoff'],minutes=2),
            'candidate_selection':{'candidate_refs':copy.deepcopy(self.candidate_refs)}}
        self.store.records['forecast_preregistration']['payload']['evaluation_plan']=self.plan
        self.store.records['forecast_candidate']['payload']['trend_id']=fixtures.uid('trend')
        d=E.method_descriptor(allowed_access_methods=['official_public_stream'])
        self.store.methods[(d['method_id'],d['method_version'])]={'method_id':d['method_id'],'version':d['method_version'],
            'artifact_digest':d['artifact_digest'],'config':d['config'],'qualification':'qualified','revoked_at':None}

    def evaluate(self):
        return self.engine.evaluate(self.wid,self.actor,self.pre_ref,self.candidate_refs,cursor=self.store.cur)

    def report(self,result):
        return decode_manifest(self.store.manifests[result['payload']['report_ref']['manifest_id']])['artifact']

    def test_produces_real_rolling_report_from_stored_history_and_never_promotes(self):
        r=self.evaluate();p=r['payload'];report=self.report(r)
        self.assertEqual(p['state'],'evaluated');self.assertEqual(p['qualification'],'unqualified')
        self.assertFalse(p['forecast_wording_enabled']);self.assertEqual(p['paired_count'],10)
        self.assertEqual(set(report['metrics']),{'last_value','seasonal_naive',forecast.CANDIDATE})
        self.assertAlmostEqual(report['metrics'][forecast.CANDIDATE]['mae'],1.7622377622377627)
        self.assertEqual(len(self.store.writes[0][1]),2) # Candidate DAG already owns the verified source edge.
        self.assertNotIn('source_bindings',p);self.assertEqual(p['source_bindings_ref'],p['report_ref'])
        self.assertLess(len(contracts.canonical(p).encode()),65536)
        self.assertEqual(report['fixture'],False) # Derived from synthetic trusted-row seam, not a live claim.
        self.assertFalse(any('INSERT INTO public.pr_trend_method' in sql or 'UPDATE public.pr_trend_method' in sql for sql,_ in self.store.cur.calls))

    def test_chunked_candidate_to_chunked_report_hydrates_the_same_full_binding_contract(self):
        candidate=self.store.records['forecast_candidate'];payload=candidate['payload']
        original=copy.deepcopy(payload['prediction'])
        fixtures.seal_document(self.store,candidate,'prediction',bindings=payload['source_bindings'])
        result=self.evaluate();loaded=copy.deepcopy(result)
        self.engine.admission._hydrate(self.store.cur,loaded,'report')
        self.assertEqual(loaded['payload']['source_bindings'],fixtures.source_bindings(self.store,candidate))
        self.assertEqual(loaded['payload']['report'],self.report(result))
        self.assertNotIn('source_bindings',result['payload'])
        self.assertEqual(decode_manifest(self.store.manifests[payload['prediction_ref']['manifest_id']])['artifact'],original)

    def test_actual_rolling_evaluation_retains_one_thousand_sources_without_root_size_failure(self):
        p=copy.deepcopy(self.p);ids=[fixtures.uid('bulk-source-'+str(i)) for i in range(1000)]
        p['sources']=[{**p['sources'][0],'source_id':sid} for sid in ids]
        self.store.observations={sid:{**copy.deepcopy(self.store.observation),'source_id':sid} for sid in ids}
        for index,window in enumerate(p['history']):window['evidence_refs']=ids[index::len(p['history'])]
        candidate=self.store.records['forecast_candidate'];prediction=forecast.predict_candidates(p)
        candidate['payload']['prediction']=prediction
        bindings=[{'source_id':sid,'scope_key':self.store.scope,'node_id':sid} for sid in ids]
        fixtures.seal_document(self.store,candidate,'prediction',bindings=bindings)
        result=self.evaluate();root=result['payload']
        self.assertEqual(root['state'],'evaluated');self.assertFalse(root['forecast_wording_enabled'])
        self.assertEqual(root['paired_count'],10)
        self.assertLess(len(contracts.canonical(root).encode()),65536)
        document=decode_manifest(self.store.manifests[root['report_ref']['manifest_id']])
        self.assertEqual(document['source_bindings'],sorted(bindings,key=lambda r:r['source_id']))
        self.assertEqual(len(document['source_bindings']),1000)
        self.assertEqual({ref for window in document['artifact']['evaluation_recipe']['history'] for ref in window['evidence_refs']},set(ids))
        hydrated=copy.deepcopy(result);self.engine.admission._hydrate(self.store.cur,hydrated,'report')
        self.assertEqual(hydrated['payload']['source_bindings'],document['source_bindings'])
        self.assertEqual(len(self.store.writes[0][1]),2)

    def test_insufficient_future_history_is_censored_not_zero_or_qualified(self):
        candidate=self.store.records['forecast_candidate']['payload']['prediction']
        recipe=copy.deepcopy(candidate['prediction_recipe']);recipe['history']=recipe['history'][:62]
        recipe['sources']=self.p['sources'];recipe['fixture']=False
        self.store.records['forecast_candidate']['payload']['prediction']=forecast.predict_candidates(recipe)
        r=self.evaluate();report=self.report(r)
        self.assertEqual(r['payload']['state'],'insufficient_history')
        self.assertEqual(r['payload']['paired_count'],2);self.assertEqual(report['censored_count'],24)
        self.assertFalse(r['payload']['forecast_wording_enabled'])

    def test_preregistered_cutoff_not_reached_does_not_create_an_evaluation(self):
        self.plan['evaluation_cutoff']=fixtures.shifted(self.store.now,hours=1)
        self.assertEqual(self.evaluate()['reason'],'evaluation_cutoff_not_reached')
        self.assertFalse(self.store.writes)

    def test_exact_predeclared_candidate_selection_required(self):
        self.plan['candidate_selection']={'candidate_refs':[{'object_id':fixtures.uid('other'),'revision':1}]}
        with self.assertRaisesRegex(TrendStorageError,'candidate_selection'):self.evaluate()

    def test_planned_slots_admit_future_opaque_ids_but_bind_trend_and_target_start(self):
        c=self.store.records['forecast_candidate']['payload']
        self.plan['candidate_selection']={'slots':[self.slot(c)]}
        self.assertEqual(self.evaluate()['payload']['state'],'evaluated')
        self.plan['candidate_selection']['slots'][0]['trend_id']=fixtures.uid('other')
        with self.assertRaisesRegex(TrendStorageError,'candidate_selection'):self.evaluate()

    def slot(self,c):
        return {'trend_id':c['trend_id'],'target_start':c['prediction']['target_start'],
                'target_digest':contracts.digest(c['prediction']['target']),
                **{k:c['prediction']['target'][k] for k in ('cohort','horizon_steps','bin_hours')}}

    def test_missing_planned_slots_are_explicit_and_no_favorable_subset_is_scored(self):
        c=self.store.records['forecast_candidate']['payload'];first=self.slot(c)
        second={**first,'target_start':fixtures.shifted(first['target_start'],hours=1)}
        self.plan['candidate_selection']={'slots':[first,second]}
        result=self.evaluate()
        self.assertEqual(result['state'],'insufficient_history');self.assertEqual(result['missing_slots'],[second])
        self.assertFalse(self.store.writes)
        self.candidate_refs=[];result=self.evaluate()
        self.assertEqual(result['missing_slots'],[first,second]);self.assertFalse(self.store.writes)

    def test_slot_cohort_target_and_horizon_are_explicitly_bound(self):
        c=self.store.records['forecast_candidate']['payload'];slot=self.slot(c)
        self.plan['candidate_selection']={'slots':[slot]};slot['horizon_steps']=2
        with self.assertRaisesRegex(TrendStorageError,'slot_target_binding'):self.evaluate()
        slot['horizon_steps']=True
        with self.assertRaisesRegex(TrendStorageError,'slot_target_binding'):self.evaluate()

    def test_repeated_measurements_keep_earliest_knowledge_but_conflicts_reject(self):
        first=copy.deepcopy(self.store.records['forecast_candidate']);second=copy.deepcopy(first)
        second['projection_id']=fixtures.uid('second-projection')
        p=copy.deepcopy(second['payload']['prediction']['prediction_recipe'])
        p['history'][0]['available_at']=fixtures.shifted(p['history'][0]['available_at'],minutes=1)
        p['sources']=self.p['sources'];second['payload']['prediction']=forecast.predict_candidates(p)
        history,_,_=self.engine._history([first,second],self.plan)
        self.assertEqual(len(history),70)
        self.assertEqual(history[0]['available_at'],first['payload']['prediction']['prediction_recipe']['history'][0]['available_at'])
        p['history'][0]['value']=999;second['payload']['prediction']=forecast.predict_candidates(p)
        with self.assertRaisesRegex(TrendStorageError,'conflicting_history'):self.engine._history([first,second],self.plan)

    def test_origin_cohort_horizon_method_and_split_drift_reject(self):
        for field,value in (('target',{**self.plan['target'],'cohort':'other'}),('origins',[]),
                            ('method_bundle',{**self.plan['method_bundle'],'trend_window':24}),('holdout_episode_ids',['other'])):
            with self.subTest(field=field):
                prior=self.plan[field];self.plan[field]=value
                with self.assertRaisesRegex(TrendStorageError,'preregistration_binding'):self.evaluate()
                self.plan[field]=prior

    def test_no_arbitrary_history_or_fixture_flag_parameters(self):
        with self.assertRaises(TypeError):
            self.engine.evaluate(self.wid,self.actor,self.pre_ref,self.candidate_refs,cursor=self.store.cur,history=[],fixture=False)
        self.assertFalse(self.store.writes)

    def test_current_registry_and_source_provenance_are_required_even_for_stored_candidate(self):
        d=E.method_descriptor();m=self.store.methods[(d['method_id'],d['method_version'])]
        m['qualification']='shadow'
        with self.assertRaisesRegex(TrendStorageError,'production_method_required'):self.evaluate()
        m['qualification']='qualified';self.store.observation['provenance']['access_method']='fixture'
        with self.assertRaisesRegex(TrendStorageError,'observation_unavailable'):self.evaluate()

    def test_idempotent_retry_revalidates_source_and_does_not_duplicate_manifest(self):
        first=self.evaluate();second=self.evaluate()
        self.assertEqual(first,second);self.assertEqual(len(self.store.writes),2)
        self.store.observation['rights']['derive_metrics']['state']='deny'
        with self.assertRaisesRegex(TrendStorageError,'source_rights'):self.evaluate()
        self.assertEqual(len(self.store.writes),2)

    def test_backdated_candidate_availability_and_tampered_history_are_rejected(self):
        c=self.store.records['forecast_candidate'];c['available_at']=fixtures.shifted(self.plan['evaluation_cutoff'],minutes=1)
        with self.assertRaisesRegex(TrendStorageError,'candidate_binding'):self.evaluate()
        c['available_at']=fixtures.shifted(self.p['decision_cutoff'],minutes=1)
        c['payload']['prediction']['prediction_recipe']['history'][0]['value']=999
        with self.assertRaisesRegex(TrendStorageError,'candidate_binding'):self.evaluate()

    def test_flags_actor_receipts_and_transaction_are_current(self):
        self.values['RAFII_TREND_FORECASTS_ENABLED']='0'
        with self.assertRaisesRegex(TrendStorageError,'disabled'):self.evaluate()
        self.values['RAFII_TREND_FORECASTS_ENABLED']='1';self.store.receipt_state='pending'
        with self.assertRaisesRegex(TrendStorageError,'verified_receipts_required'):self.evaluate()
        with self.assertRaisesRegex(TrendStorageError,'authenticated_transaction'):
            self.engine.evaluate(self.wid,self.actor,self.pre_ref,self.candidate_refs,cursor=None)


if __name__=='__main__':unittest.main()
