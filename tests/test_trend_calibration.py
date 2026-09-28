from copy import deepcopy
from datetime import datetime,timedelta,timezone
from test_trend_metrics import OfflineCase
from postriff_phase2.growth.trends import calibration as C, backtest as B


def future():
    start=datetime(2026,9,27,20,tzinfo=timezone.utc);iso=lambda x:x.isoformat().replace('+00:00','Z')
    return [{'window_start':iso(start+timedelta(hours=i)),'window_end':iso(start+timedelta(hours=i+1)),
             'decision_cutoff':iso(start+timedelta(hours=i+1)),'comparison_digest':'epoch_a',
             'data_state':'qualified','coverage':{'availability':'available','completeness':'complete_within_scope'},
             'mention_rate':{'value':80 if i<8 else 40}} for i in range(12)]


def prediction():
    return B.seal_decision({'decision_cutoff':'2026-09-27T20:00:00Z','baseline':{'baseline_rate':50},'comparison_digest':'epoch_a','method_version':'frozen-1'})


class Calibration(OfflineCase):
    def test_wilson_reference_and_empty(self):
        out=C.wilson_interval(50,100)
        self.assertAlmostEqual(out['lower'],.40383153,places=7);self.assertAlmostEqual(out['upper'],.59616847,places=7)
        self.assertIsNone(C.wilson_interval(0,0))
        with self.assertRaises(ValueError):C.wilson_interval(2,1)

    def test_frozen_baseline_success_and_unknown_horizon(self):
        p=prediction();rows=future();at='2026-09-28T08:00:00Z'
        out=C.label_rising_outcome(p,rows,evaluated_at=at)
        self.assertEqual(out['label'],'success');self.assertEqual(out['qualifying_windows'],8);self.assertEqual(out['method_version'],'frozen-1')
        self.assertEqual(C.label_rising_outcome(p,rows[:-1],evaluated_at=at)['label'],'not_evaluable')
        rows[0]['mention_rate']['value']=20
        self.assertEqual(C.label_rising_outcome(p,rows,evaluated_at=at)['label'],'failure')
        rows[1]['comparison_digest']='changed_epoch'
        self.assertEqual(C.label_rising_outcome(p,rows,evaluated_at=at)['label'],'not_evaluable')

    def test_future_unavailable_outage_and_deleted_outcomes_are_unknown(self):
        at='2026-09-28T08:00:00Z'
        for change in [{'available_at':'2026-09-29T00:00:00Z'},{'verification_state':'inputs_deleted'},{'data_state':'insufficient'}]:
            rows=future();rows[0].update(change)
            self.assertEqual(C.label_rising_outcome(prediction(),rows,evaluated_at=at)['label'],'not_evaluable')
        p=prediction();p.pop('decision_digest')
        with self.assertRaises(ValueError):C.label_rising_outcome(p,future(),evaluated_at=at)

    def test_explicit_precision_denominator_and_low_sample_hidden(self):
        rows=[{'decision_digest':str(i),'label':'success' if i<3 else 'failure' if i<4 else 'not_evaluable','group_id':str(i%2)} for i in range(5)]
        out=C.calibrate_outcomes(rows)
        self.assertEqual(out['selected'],5);self.assertEqual(out['evaluable'],4);self.assertEqual(out['unknown'],1);self.assertEqual(out['precision'],.75)
        self.assertIsNone(out['display_accuracy']);self.assertIsNone(out['false_positive_rate']);self.assertIsNone(out['recall'])
        self.assertIsNotNone(out['clustered_bootstrap'])

    def test_cohort_gaps_not_pooled_away_and_block_bootstrap_reproducible(self):
        rows=[{'decision_digest':str(i),'label':'success' if i%3 else 'failure','group_id':str(i//3),
               'cohort':{'language':'en' if i<60 else 'yue'}} for i in range(65)]
        out=C.calibrate_cohorts(rows)
        bylang={r['cohort']['language']:r for r in out}
        self.assertIsNotNone(bylang['en']['display_accuracy']);self.assertIsNone(bylang['yue']['display_accuracy'])
        self.assertEqual(C.calibrate_outcomes(rows,seed=42),C.calibrate_outcomes(rows,seed=42))

    def test_altered_sealed_decision_rejected(self):
        p=prediction();p['baseline']['baseline_rate']=1
        with self.assertRaisesRegex(ValueError,'digest mismatch'):
            C.label_rising_outcome(p,future(),evaluated_at='2026-09-28T08:00:00Z')

    def test_deletion_invalidates_calibration_and_method_versions_do_not_pool(self):
        rows=[{'decision_digest':'a','label':'success','method_version':'v1','verification_state':'inputs_deleted'},
              {'decision_digest':'b','label':'failure','method_version':'v1'}]
        out=C.calibrate_outcomes(rows)
        self.assertEqual(out['invalidated'],1);self.assertEqual(out['unknown'],1);self.assertEqual(out['precision'],0)
        rows[1]['method_version']='v2'
        with self.assertRaises(ValueError):C.calibrate_outcomes(rows)
        self.assertEqual(len(C.calibrate_cohorts(rows)),2)
