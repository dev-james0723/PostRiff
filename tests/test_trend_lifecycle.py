from copy import deepcopy
from datetime import datetime,timedelta,timezone
from test_trend_metrics import OfflineCase
from postriff_phase2.growth.trends.lifecycle import evaluate_lifecycle
from postriff_phase2.growth.trends.confidence import assess_confidence


def stage_window(hour, *, rate=100, ratio=2, velocity=10, acceleration=5, anomaly=2, state='qualified', **context):
    start=datetime(2026,9,27,tzinfo=timezone.utc)+timedelta(hours=hour);end=start+timedelta(hours=1)
    iso=lambda x:x.isoformat().replace('+00:00','Z')
    return {'window_start':iso(start),'window_end':iso(end),'decision_cutoff':iso(end),'window_hours':1,
            'episode_id':'episode_a','comparison_digest':'same','data_state':state,
            'coverage':{'availability':'available','completeness':'complete_within_scope','breadth':'unknown'},
            'mention_rate':{'value':rate},'observed':{'qualifying_original_count':int(rate),'known_creator_count':30,'unknown_author_fraction':0,'largest_creator_share':.1},
            'momentum':{k:{'value':v} for k,v in [('burst_ratio',ratio),('velocity',velocity),('acceleration',acceleration),('robust_anomaly',anomaly)]},
            'episode_context':context}


class Lifecycle(OfflineCase):
    def test_two_windows_required_and_no_public_stage(self):
        a,b=stage_window(1),stage_window(2)
        self.assertIsNone(evaluate_lifecycle(None,[a])['candidate_stage'])
        result=evaluate_lifecycle(None,[a,b])
        self.assertEqual(result['candidate_stage'],'rising');self.assertIsNone(result['stage']);self.assertEqual(result['publication_state'],'shadow_only')

    def test_overlap_and_hysteresis_prevent_flapping(self):
        a,b=stage_window(1),stage_window(2);initial=evaluate_lifecycle(None,[a,b])
        overlapping=deepcopy(b);overlapping.update(window_start='2026-09-27T02:15:00Z',window_end='2026-09-27T03:15:00Z',decision_cutoff='2026-09-27T03:15:00Z')
        self.assertIsNone(evaluate_lifecycle(None,[b,overlapping])['candidate_stage'])
        for ratio in (1.49,1.21,1.51,1.3):
            nextw=stage_window(3,ratio=ratio)
            state=evaluate_lifecycle(initial,[b,nextw]);self.assertEqual(state['candidate_stage'],'rising')
            if ratio<1.5:self.assertIn('rising_sustain_hysteresis',state['stage_basis'])

    def test_decline_needs_two_windows_no_outage_decline(self):
        prior={'candidate_stage':'rising','episode_high_rate':150,'entered_at':'2026-09-27T01:00:00Z','episode_id':'episode_a'}
        a,b=stage_window(3,rate=60,ratio=1.2,velocity=-20),stage_window(4,rate=50,ratio=1,velocity=-10)
        self.assertEqual(evaluate_lifecycle(prior,[a,b])['candidate_stage'],'declining')
        b['coverage']['completeness']='gap'
        degraded=evaluate_lifecycle(prior,[a,b]);self.assertIsNone(degraded['candidate_stage']);self.assertIsNone(degraded['stage'])

    def test_breaking_precedence_and_concentration_gate(self):
        a,b=[stage_window(i,rate=200,ratio=4,anomaly=5,independent_community_count=2) for i in (1,2)]
        self.assertEqual(evaluate_lifecycle(None,[a,b])['candidate_stage'],'breaking')
        b['observed']['largest_creator_share']=.9
        self.assertIsNone(evaluate_lifecycle(None,[a,b])['candidate_stage'])

    def test_duplicate_density_is_not_topic_saturation(self):
        a,b=[stage_window(i,redundancy_ratio=.7) for i in (1,2)]
        out=evaluate_lifecycle(None,[a,b]);self.assertEqual(out['candidate_stage'],'rising');self.assertTrue(out['repetition_heavy'])

    def test_recurrence_requires_new_episode_identity(self):
        prior={'candidate_stage':'declining','episode_id':'episode_a','entered_at':'2026-09-27T00:00:00Z'}
        a,b=[stage_window(i,new_episode=True) for i in (1,2)]
        self.assertEqual(evaluate_lifecycle(prior,[a,b])['candidate_stage'],'declining')
        a['episode_id']=b['episode_id']='episode_b'
        self.assertEqual(evaluate_lifecycle(prior,[a,b])['candidate_stage'],'rising')

    def test_semantic_confidence_cannot_raise_measurement_support(self):
        w=stage_window(1,rate=2,state='insufficient');w['observed']['known_creator_count']=1
        result=assess_confidence(w,interpretation={'probability':.999})
        self.assertEqual(result['measurement_quality']['level'],'low');self.assertIsNone(result['lifecycle_support']['probability'])

    def test_two_windows_below_sustain_exit_without_fabricating_decline(self):
        a,b=stage_window(1),stage_window(2);prior=evaluate_lifecycle(None,[a,b])
        c,d=stage_window(3,ratio=1.1,velocity=0),stage_window(4,ratio=1.1,velocity=0)
        one=evaluate_lifecycle(prior,[b,c]);self.assertEqual(one['candidate_stage'],'rising')
        out=evaluate_lifecycle(one,[c,d]);self.assertIsNone(out['candidate_stage'])
        self.assertEqual(out['stage_basis'],['two_windows_below_rising_sustain'])
        with self.assertRaisesRegex(ValueError,'future_lifecycle_state'):
            evaluate_lifecycle({**prior,'as_of':'2026-09-28T00:00:00Z'},[a,b])
