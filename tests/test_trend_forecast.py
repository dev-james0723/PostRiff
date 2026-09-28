import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from postriff_phase2.growth.trends import forecast
from postriff_phase2.growth.trends.context import digest


class Forecast(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((Path(__file__).parent/"fixtures/trends/advanced/forecast.json").read_text())
        for target in ("socket.socket","socket.create_connection","urllib.request.urlopen"):
            mock=patch(target,side_effect=AssertionError("no egress")); mock.start(); self.addCleanup(mock.stop)

    def test_last_value_seasonal_naive_and_residual_quantiles(self):
        p={**self.p,"decision_cutoff":"2026-09-26T00:00:00Z"}
        r=forecast.predict_baselines(p)
        a,b=r["predictions"]
        self.assertEqual(a["point"],26)
        self.assertEqual(b["point"],21)
        self.assertIsNotNone(b["quantiles"])
        self.assertEqual(b["quantiles"]["0.1"],21)
        self.assertFalse(r["forecast_wording_enabled"])

    def test_future_count_and_future_availability_cannot_change_prediction(self):
        p={**self.p,"decision_cutoff":"2026-09-26T00:00:00Z"}
        before=forecast.predict_baselines(p)
        p=copy.deepcopy(p)
        for row in p["history"][24:]: row["value"]=100000
        self.assertEqual(forecast.predict_baselines(p),before)
        p["history"][23]["available_at"]="2026-09-27T00:00:00Z"
        self.assertEqual(forecast.predict_baselines(p)["predictions"][0]["point"],24)

    def test_embargo_excludes_recent_windows(self):
        r=forecast.predict_baselines({**self.p,"decision_cutoff":"2026-09-26T00:00:00Z","embargo_hours":2})
        self.assertEqual(r["predictions"][0]["point"],22)
        self.assertEqual(r["training_cutoff"],"2026-09-25T22:00:00+00:00")
        self.assertEqual(r["predictions"][1]["point"],21)

    def test_population_and_retention_limits_fail_closed(self):
        for key,value in (("population","platform_wide"),("supported_horizon_hours",1)):
            p=copy.deepcopy(self.p); p["target"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): forecast.predict_baselines(p)

    def test_rolling_origin_episode_separation_and_exact_mae(self):
        r=forecast.rolling_origin_evaluate(self.p)
        self.assertEqual(r["metrics"]["last_value"]["count"],3)
        self.assertAlmostEqual(r["metrics"]["last_value"]["mae"],11/3)
        self.assertTrue(all(o["training_input_digest"]==r["origins"][0]["training_input_digest"] for o in r["origins"]))
        self.assertEqual(r["holdout_episode_ids"],["holdout"])

    def test_missing_future_and_revoked_outcomes_censored(self):
        p=copy.deepcopy(self.p); p["history"][-1]["complete"]=False
        r=forecast.rolling_origin_evaluate(p)
        self.assertEqual(r["censored_count"],3)
        self.assertEqual(r["metrics"]["last_value"]["count"],2)
        p=copy.deepcopy(self.p); p["sources"][0]["revoked"]=True
        r=forecast.rolling_origin_evaluate(p)
        self.assertEqual(r["metrics"],{})

    def pair(self, **kw):
        return {"prediction_id":"prediction","method":"candidate","episode_id":"episode","issued_at":"2026-09-25T01:00:00Z",
                "training_cutoff":"2026-09-25T01:00:00Z","horizon_end":"2026-09-25T03:00:00Z","frame_id":"sample_count","point":5,
                "quantiles":{"0.1":2,"0.5":5,"0.9":8},"outcome":{"value":10,"complete":True,"frame_id":"sample_count",
                "available_at":"2026-09-25T03:00:00Z","evidence_refs":["forecast_source"]},**kw}

    def test_mae_pinball_coverage_sharpness_arithmetic(self):
        r=forecast.evaluate_forecasts({**self.p,"pairs":[self.pair()]})["metrics"]["candidate"]
        self.assertEqual(r["mae"],5)
        self.assertEqual(r["quantile_loss"]["0.1"],.8)
        self.assertEqual(r["quantile_loss"]["0.9"],1.8)
        self.assertEqual(r["interval_coverage"],0)
        self.assertEqual(r["sharpness"],6)

    def test_future_cutoff_embargo_and_crossing_quantiles_reject(self):
        for change in ({"training_cutoff":"2026-09-26T00:00:00Z"},{"embargo_hours":1},{"quantiles":{"0.1":8,"0.9":2}}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                forecast.evaluate_forecasts({**self.p,"pairs":[self.pair(**change)]})

    def test_missing_future_window_never_zero(self):
        pair=self.pair(); pair["outcome"]["complete"]=False
        r=forecast.evaluate_forecasts({**self.p,"pairs":[pair]})
        self.assertEqual(r["censored_count"],1)
        self.assertEqual(r["metrics"],{})

    def series(self):
        # Synthetic time series exercises the executable path, never live qualification.
        p=copy.deepcopy(self.p); start=datetime(2026,9,23,tzinfo=timezone.utc)
        p.update(fixture=False,history=[],origins=[],seasonal_period=4,trend_window=12)
        p['target'].update(horizon_steps=1,supported_horizon_hours=168)
        p['sources'][0].update(event_at=start.isoformat(),available_at=start.isoformat())
        for i in range(70):
            a=start+timedelta(hours=i); b=a+timedelta(hours=1)
            noise=[-1,0,1,0,0][i%5] if i<60 else (8 if i in (64,69) else 0)
            p['history'].append(dict(frame_id='sample_count',metric_definition='original_count_v1',cohort='fixture_en',
                episode_id='train' if i<60 else f'e{(i-60)//2}',window_start=a.isoformat(),window_end=b.isoformat(),
                available_at=b.isoformat(),complete=True,coverage='stable',value=20+2*i+noise,evidence_refs=['forecast_source']))
            if i>=60: p['origins'].append(a.isoformat())
        p['decision_cutoff']=b.isoformat(); p['holdout_episode_ids']=[f'e{i}' for i in range(5)]
        return p

    def qualification(self, p=None):
        p=self.series() if p is None else p
        report=forecast.rolling_origin_evaluate(p)
        gate={"preregistered_at":"2026-09-22T00:00:00Z","holdout_opened_at":p['origins'][0],
              "dataset_digest":report["dataset_digest"],"target_digest":digest(p["target"]),"primary_loss":"mae",
              "min_episodes":5,"min_pairs":10,"coverage_tolerance":.05,"reviewer":"fixture reviewer",
              "operator_approved":True,"rights_verified":True,"reproducible":True,
              "method_digest":digest(report['method_bundle']),"report_digest":report['report_digest'],
              "evaluation_plan_digest":report['evaluation_plan_digest']}
        gate['preregistration_digest']=forecast.preregistration_digest(gate)
        return {**p,"report":report,"gate":gate}

    def test_fixtures_and_incomplete_gates_never_qualify(self):
        p=self.qualification(); p["report"]["fixture"]=True
        r=forecast.qualify_forecast(p)
        self.assertIn("fixture_not_qualification",r["reasons"])
        self.assertFalse(r["forecast_wording_enabled"])
        p["gate"]={}
        self.assertEqual(forecast.qualify_forecast(p)["state"],"unqualified")

    def test_scope_and_preregistration_and_interval_gates(self):
        p=self.qualification(); p["gate"]["target_digest"]="other"
        self.assertIn("qualification_scope_mismatch",forecast.qualify_forecast(p)["reasons"])
        p=self.qualification(); p["gate"]["preregistered_at"]="2026-09-27T00:00:00Z"
        self.assertIn("preregistration_timing_invalid",forecast.qualify_forecast(p)["reasons"])
        p=self.qualification()
        for row in p["report"]["losses"][forecast.CANDIDATE]: row["interval_covered"]=0
        self.assertIn("evaluation_integrity_mismatch",forecast.qualify_forecast(p)["reasons"])
        p=self.series()
        for row in p['history'][60:]: row['value']+=1000
        self.assertIn("interval_calibration_failed",forecast.qualify_forecast(self.qualification(p))["reasons"])

    def test_candidate_must_improve_better_baseline_with_positive_interval(self):
        p=self.series()
        for row in p['history'][60:]: row['value']=p['history'][59]['value']
        p=self.qualification(p)
        r=forecast.qualify_forecast(p)
        self.assertIn("improvement_interval_not_positive",r["reasons"])
        self.assertEqual(r["better_simple_baseline"],"last_value")

    def test_wrong_target_frame_or_horizon_and_structural_break(self):
        with self.assertRaises(ValueError):
            forecast.evaluate_forecasts({**self.p,"pairs":[self.pair(frame_id="other")]})
        with self.assertRaises(ValueError):
            forecast.evaluate_forecasts({**self.p,"pairs":[self.pair(horizon_end="2026-09-25T04:00:00Z")]})
        r=forecast.predict_baselines({**self.p,"structural_break":True})
        self.assertTrue(all(p["point"] is None for p in r["predictions"]))

    def test_qualification_source_loss_and_method_withdrawal_fail_closed(self):
        p=self.qualification(); p["sources"][0]["revoked"]=True
        self.assertIn("source_support_unavailable",forecast.qualify_forecast(p)["reasons"])
        p=self.qualification(); p["method_withdrawn"]=True
        self.assertIn("method_or_feature_disabled",forecast.qualify_forecast(p)["reasons"])

    def test_executable_third_candidate_predicts_actual_linear_counts(self):
        p=self.series(); p['history']=p['history'][:60]
        p['decision_cutoff']=p['origins'][0]
        for i,row in enumerate(p['history']): row['value']=20+2*i
        r=forecast.predict_candidates(p)
        self.assertEqual([x['method'] for x in r['predictions']],['last_value','seasonal_naive',forecast.CANDIDATE])
        self.assertEqual(r['predictions'][0]['point'],138)
        self.assertEqual(r['predictions'][-1]['point'],140)
        self.assertEqual(r['predictions'][-1]['quantiles'],{'0.1':140,'0.5':140,'0.9':140})
        self.assertFalse(r['forecast_wording_enabled'])
        self.assertEqual(forecast.to_stored_projection(r)['payload']['state'],'unavailable')

    def test_candidate_is_time_causal_and_reordering_invariant(self):
        p=self.series(); p['decision_cutoff']=p['origins'][0]
        before=forecast.predict_candidates(p)
        for r in p['history'][60:]: r['value']=999999
        p['history'].reverse()
        self.assertEqual(forecast.predict_candidates(p),before)
        p=self.series(); report=forecast.rolling_origin_evaluate(p)
        p['history'].reverse(); p['origins'].reverse(); p['holdout_episode_ids'].reverse()
        self.assertEqual(forecast.rolling_origin_evaluate(p),report)
        p=self.series(); p['decision_cutoff']=p['origins'][0]
        p['history'][59]['available_at']='2026-09-30T00:00:00Z'
        after=forecast.predict_candidates(p)
        self.assertNotEqual(after['training_input_digest'],before['training_input_digest'])
        self.assertNotEqual(after['predictions'][-1]['point'],before['predictions'][-1]['point'])

    def test_future_labels_cannot_change_historical_predictions(self):
        p=self.series(); before=forecast.rolling_origin_evaluate(p)
        for r in p['history'][60:]: r['value']=999999
        after=forecast.rolling_origin_evaluate(p)
        self.assertEqual(before['origins'],after['origins'])
        self.assertNotEqual(before['metrics'],after['metrics'])

    def test_wrong_outcome_labels_censor_all_methods(self):
        for field,value in (('frame_id','other'),('metric_definition','other'),('cohort','other'),('feature_version','other'),
                            ('coverage','gap'),('available_at','2026-09-30T00:00:00Z')):
            with self.subTest(field=field):
                p=self.series(); p['history'][60][field]=value
                r=forecast.rolling_origin_evaluate(p)
                self.assertEqual(r['censored_count'],3)
                self.assertTrue(all(m['count']==9 for m in r['metrics'].values()))

    def test_paired_outcome_or_episode_disagreement_rejected(self):
        for field,value in (('episode_id','other'),('outcome',dict(self.pair()['outcome'],value=900))):
            with self.subTest(field=field),self.assertRaises(ValueError):
                forecast.evaluate_forecasts({**self.p,'pairs':[self.pair(),self.pair(method='last_value',**{field:value})]})

    def test_group_separation_is_explicit_and_excludes_shared_groups(self):
        p=self.series()
        for i,r in enumerate(p['history']): r['group_id']='held' if i>=50 else 'train'
        with self.assertRaises(ValueError): forecast.rolling_origin_evaluate(p)
        p['holdout_group_ids']=['held']
        report=forecast.rolling_origin_evaluate(p)
        p['history'][55]['value']=999999
        self.assertEqual(report['origins'],forecast.rolling_origin_evaluate(p)['origins'])

    def test_strict_bounds_duplicates_and_sparse_support(self):
        for field,value in (('trend_window',True),('trend_window',169),('seasonal_period',0)):
            with self.subTest(field=field),self.assertRaises(ValueError): forecast.predict_candidates({**self.series(),field:value})
        p=self.series(); p['origins'].append(p['origins'][0])
        with self.assertRaises(ValueError): forecast.rolling_origin_evaluate(p)
        p=self.series(); p['history']=p['history'][:5]
        self.assertIsNone(forecast.predict_candidates(p)['predictions'][-1]['point'])
        p=self.series(); p['structural_break']=True
        self.assertTrue(all(r['point'] is None for r in forecast.predict_candidates(p)['predictions']))
        p=self.series(); p['history']*=100
        with self.assertRaises(ValueError): forecast.rolling_origin_evaluate(p)

    def test_qualification_executes_candidate_and_records_sample_ci_gates(self):
        q=forecast.qualify_forecast(self.qualification())
        self.assertEqual(q['state'],'qualified')
        self.assertEqual(q['paired_count'],10); self.assertEqual(q['episode_count'],5)
        self.assertEqual(q['better_simple_baseline'],'last_value')
        self.assertGreater(q['improvement_interval']['lower'],0)
        self.assertEqual(q['metrics'][forecast.CANDIDATE]['interval_coverage'],.8)
        self.assertEqual(q['improvement_interval']['confidence_level'],.95)
        self.assertEqual(q['gate_digest'],digest(q['gate']))

    def test_loss_recipe_and_gate_tamper_fail_even_with_resealed_report(self):
        p=self.qualification(); p['report']['losses'][forecast.CANDIDATE][0]['absolute_error']=999
        self.assertIn('evaluation_integrity_mismatch',forecast.qualify_forecast(p)['reasons'])
        p['report']['report_digest']=digest({k:v for k,v in p['report'].items() if k!='report_digest'})
        p['gate']['report_digest']=p['report']['report_digest']
        self.assertIn('evaluation_replay_mismatch',forecast.qualify_forecast(p)['reasons'])
        p=self.qualification(); p['report']['evaluation_recipe']['history'][0]['value']=999
        self.assertIn('evaluation_integrity_mismatch',forecast.qualify_forecast(p)['reasons'])
        p=self.qualification(); p['gate']['min_pairs']=2
        self.assertIn('preregistration_binding_mismatch',forecast.qualify_forecast(p)['reasons'])

    def test_unbound_pair_scores_no_external_data_and_missing_labels_fail_closed(self):
        p=self.qualification(); p['report']=forecast.evaluate_forecasts({**self.p,'pairs':[self.pair()]})
        p['gate']['report_digest']=p['report']['report_digest']
        self.assertIn('executable_evaluation_required',forecast.qualify_forecast(p)['reasons'])
        p=self.series(); p['history']=[]
        self.assertEqual(forecast.qualify_forecast(self.qualification(p))['state'],'unqualified')
        p=self.series()
        for r in p['history']: r.pop('cohort')
        self.assertIn('explicit_cohort_labels_required',forecast.qualify_forecast(self.qualification(p))['reasons'])

    def test_target_cohort_horizon_method_and_scope_are_bound(self):
        for field,value in (('cohort','other'),('horizon_steps',2),('metric_definition','other')):
            p=self.qualification(); p['target'][field]=value
            with self.subTest(field=field):
                self.assertIn('qualification_scope_mismatch',forecast.qualify_forecast(p)['reasons'])
        for field,value in (('trend_window',24),('candidate_method','last_value')):
            p=self.qualification(); p[field]=value
            with self.subTest(field=field):
                self.assertIn('qualification_method_mismatch',forecast.qualify_forecast(p)['reasons'])
        p=self.qualification(); p['scope_key']='other'
        self.assertIn('qualification_scope_mismatch',forecast.qualify_forecast(p)['reasons'])
        p=self.qualification(); p['report']['method_version']='stale'
        self.assertIn('qualification_method_mismatch',forecast.qualify_forecast(p)['reasons'])

    def test_qualified_projection_replays_and_has_exact_binding_metadata(self):
        p=self.qualification(); prediction=forecast.predict_candidates(p)
        wire=forecast.to_stored_projection(prediction,qualification_payload=p)
        self.assertEqual(wire['kind'],'forecast'); self.assertEqual(wire['method_version'],forecast.VERSION)
        self.assertEqual(wire['payload']['state'],'qualified')
        self.assertEqual(wire['payload']['target'],p['target'])
        self.assertEqual(wire['payload']['predictions'][0]['method'],forecast.CANDIDATE)
        self.assertEqual(wire['payload']['qualification']['paired_count'],10)
        self.assertNotIn('prediction_recipe',wire['payload'])
        self.assertNotIn('history',json.dumps(wire))

    def test_projection_cannot_reuse_expired_revoked_mismatched_or_tampered_qualification(self):
        original=self.qualification(); prediction=forecast.predict_candidates(original)
        for mutation in ('revoked','disabled','expired','method','target','point','late_evaluation','retention'):
            p=copy.deepcopy(original); r=copy.deepcopy(prediction)
            if mutation=='revoked': p['sources'][0]['revoked']=True
            if mutation=='disabled': p['enabled']=False
            if mutation=='expired': p['decision_cutoff']=r['horizon_end']
            if mutation=='method': r['method_bundle']['methods'][forecast.CANDIDATE]='2'
            if mutation=='target': r['target']['cohort']='different'
            if mutation=='point': r['predictions'][-1]['point']=9999
            if mutation=='late_evaluation': r['issued_at']=p['origins'][0]
            if mutation=='retention':
                p['sources'][0]['expires_at']=(datetime.fromisoformat(p['decision_cutoff'])+timedelta(minutes=1)).isoformat()
            with self.subTest(mutation=mutation):
                wire=forecast.to_stored_projection(r,qualification_payload=p)['payload']
                self.assertEqual(wire['state'],'unavailable'); self.assertEqual(wire['predictions'],[])
        r=copy.deepcopy(prediction); r['predictions'][-1]['point']=9999
        r['prediction_digest']=digest({k:v for k,v in r.items() if k!='prediction_digest'})
        self.assertEqual(forecast.to_stored_projection(r,qualification_payload=original)['payload']['reason'],'prediction_replay_mismatch')

    def test_failed_numeric_sample_and_approval_gates(self):
        for field,value,reason in (('min_pairs',11,'insufficient_paired_episode_sample'),
                                  ('min_episodes',6,'insufficient_paired_episode_sample'),
                                  ('operator_approved',False,'approval_rights_or_loss_gate'),
                                  ('rights_verified',False,'approval_rights_or_loss_gate'),
                                  ('reproducible',False,'approval_rights_or_loss_gate')):
            p=self.qualification(); p['gate'][field]=value
            p['gate']['preregistration_digest']=forecast.preregistration_digest(p['gate'])
            with self.subTest(field=field): self.assertIn(reason,forecast.qualify_forecast(p)['reasons'])

    def test_large_history_preserves_all_baseline_residuals_but_bounds_candidate(self):
        p=self.series(); template=p['history'][0]; start=datetime.fromisoformat(template['window_start'])
        p['history']=[]
        for i in range(600):
            p['history'].append({**template,'window_start':(start+timedelta(hours=i)).isoformat(),
                'window_end':(start+timedelta(hours=i+1)).isoformat(),
                'available_at':(start+timedelta(hours=i+1)).isoformat(),'value':20+i})
        p['decision_cutoff']=p['history'][-1]['window_end']
        rows=forecast.predict_candidates(p)['predictions']
        self.assertEqual(rows[0]['residual_count'],599)
        self.assertEqual(rows[1]['residual_count'],596)
        self.assertEqual(rows[2]['residual_count'],512)
        p['history']*=10
        p['origins']=[(start+timedelta(hours=i)).isoformat() for i in range(200)]
        with self.assertRaisesRegex(ValueError,'rolling work bound'): forecast.rolling_origin_evaluate(p)

    def test_prediction_needs_explicit_cohort_and_retained_history_through_horizon(self):
        original=self.qualification()
        for mutation in ('cohort','expires_at'):
            p=copy.deepcopy(original)
            for r in p['history']:
                if mutation=='cohort': r.pop('cohort')
                else: r['expires_at']=(datetime.fromisoformat(p['decision_cutoff'])+timedelta(minutes=1)).isoformat()
            prediction=forecast.predict_candidates(p)
            wire=forecast.to_stored_projection(prediction,qualification_payload=original)['payload']
            with self.subTest(mutation=mutation):
                self.assertEqual(wire['state'],'unavailable'); self.assertEqual(wire['predictions'],[])


if __name__=="__main__": unittest.main()
