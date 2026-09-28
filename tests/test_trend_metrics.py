"""Synthetic-only offline arithmetic and trust boundary fixtures."""
from copy import deepcopy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
from postriff_phase2.growth.trends import metrics as M, baselines as B, momentum as V

FIXTURE = Path(__file__).parent/'fixtures/trends/metrics/60_90_150.json'


def fixture(): return json.loads(FIXTURE.read_text())


def windows(data=None):
    f=data or fixture()
    kwargs={'decision_cutoff':f['decision_cutoff'],'source_policies':f['source_policies']}
    return [M.aggregate_window(f['observations'],**kwargs,**s) for s in f['window_specs']]


def baseline(data=None):
    f=data or fixture()
    history=[M.aggregate_window(f['observations'],decision_cutoff=f['decision_cutoff'],source_policies=f['source_policies'],**s) for s in f['baseline_window_specs']]
    return B.build_baseline(history,current_window=windows(f)[-1],decision_cutoff=f['decision_cutoff'])


class OfflineCase(unittest.TestCase):
    def setUp(self):
        for name in ('socket.create_connection','socket.socket.connect','urllib.request.urlopen'):
            guard=patch(name,side_effect=AssertionError('network prohibited in trend tests'))
            guard.start(); self.addCleanup(guard.stop)


class Metrics(OfflineCase):
    def test_exact_60_90_150_and_robust_baseline(self):
        w=windows(); b=baseline(); out=V.compute_momentum(w,b)
        self.assertEqual([x['mention_rate']['value'] for x in w],[60,90,150])
        self.assertEqual(b['baseline_rate'],50); self.assertEqual(b['sample_windows'],4)
        for key,value in [('velocity',60),('acceleration',30),('growth_pct',200),('burst_ratio',3),('robust_anomaly',100)]: self.assertEqual(out[key]['value'],value)
        self.assertEqual(out['acceleration']['unit'],'posts/hour^3')

    def test_unknown_coverage_is_not_zero_or_extrapolated(self):
        f=fixture(); f['window_specs'][-1]['coverage']['completeness']='unknown'
        w=windows(f)[-1]
        self.assertIsNone(w['mention_rate']['value']); self.assertEqual(w['observed']['qualifying_original_count'],150)
        self.assertEqual(w['mention_rate']['reason'],'coverage_unknown')

    def test_no_cross_epoch_acceleration_or_zero_base_percentage(self):
        w=windows();b=baseline();b['baseline_rate']=0
        self.assertEqual(V.compute_momentum(w,b)['growth_pct']['reason'],'insufficient_base')
        w[-1]['comparison_digest']='changed-query'
        self.assertEqual(V.compute_momentum(w,baseline())['velocity']['reason'],'incomparable_windows')
        self.assertIsNone(V.compute_momentum(w,baseline())['growth_pct']['value'])

    def test_irregular_intervals_do_not_fake_acceleration(self):
        w=windows(); w[1]['window_end']='2026-09-27T18:59:59Z'
        self.assertIsNone(V.compute_momentum(w,baseline())['acceleration']['value'])

    def test_retry_dedup_reposts_and_identical_originals(self):
        f=fixture(); f['observations'] += deepcopy(f['observations'][-10:])
        self.assertEqual(windows(f)[-1]['observed']['qualifying_original_count'],150)
        current=[r for r in f['observations'] if '2026-09-27T19:' in r['event_at']]
        current[0]['payload']['is_repost']=True; current[0]['payload_digest']=M.canonical_digest(current[0]['payload'])
        current[1]['payload']['text']=current[2]['payload']['text']; current[1]['payload_digest']=M.canonical_digest(current[1]['payload'])
        self.assertEqual(windows(f)[-1]['observed']['qualifying_original_count'],149)

    def test_boundary_unknown_event_and_late_backfill(self):
        f=fixture();rows=[r for r in f['observations'] if '2026-09-27T19:' in r['event_at']]
        rows[0]['event_at']='2026-09-27T20:00:00Z'
        rows[1]['event_at']=None;rows[1]['time_basis']='retrieval'
        rows[2]['event_at']='2026-09-01T19:10:00Z'
        w=windows(f)[-1]
        self.assertEqual(w['observed']['qualifying_original_count'],147)
        self.assertEqual(w['discovery_rate']['value'],1)

    def test_delete_wins_over_late_old_create(self):
        f=fixture();old=next(r for r in f['observations'] if '2026-09-27T19:' in r['event_at'])
        deleted=deepcopy(old);deleted.update(revision_sequence=3,revision_identity='delete-r3',operation='delete',payload={'platform':'bluesky'},available_at='2026-09-27T19:50:00Z')
        deleted['payload_digest']=M.canonical_digest(deleted['payload'])
        old['available_at']='2026-09-27T19:59:00Z'
        f['observations'].append(deleted)
        self.assertEqual(windows(f)[-1]['observed']['qualifying_original_count'],149)

    def test_future_revision_is_invisible(self):
        f=fixture();expected=windows(f)
        future=deepcopy(f['observations'][0]);future.update(revision_sequence=99,revision_identity='future',available_at='2026-09-28T00:00:00Z')
        f['observations'].append(future)
        self.assertEqual(windows(f),expected)

    def test_authors_policy_scope_and_expiry_fail_closed(self):
        f=fixture();row=next(r for r in f['observations'] if '2026-09-27T19:' in r['event_at'])
        row['payload'].update(author_status='unknown',author_key=None); row['payload_digest']=M.canonical_digest(row['payload'])
        w=windows(f)[-1]; self.assertEqual(w['observed']['known_author_post_count'],149)
        f['source_policies'][0]['rights']['derive_metrics']['state']='deny'
        self.assertIsNone(windows(f)[-1]['mention_rate']['value'])
        self.assertFalse(M.right_allowed({'derive_metrics':'allow'},'derive_metrics',f['decision_cutoff'],'shared:fixture'))

    def test_counter_corrections_and_missing_are_distinct(self):
        old={'provider_id':'fixture','platform':'bluesky','source_identity':'x','metric_definition_id':'likes','counter_epoch':'v1','value':10,'received_at':'2026-09-27T18:00:00Z'}
        new={**old,'value':6,'received_at':'2026-09-27T19:00:00Z'}
        out=M.engagement_velocity(old,new); self.assertEqual(out['value'],-4);self.assertIn('counter_decreased',out['flags']);self.assertEqual(out['time_basis'],'retrieval_time')
        self.assertEqual(M.engagement_velocity(old,{**new,'value':None,'missing_reason':'permission_denied'})['reason'],'permission_denied')
        self.assertIsNone(M.engagement_velocity(old,{**new,'platform':'threads'})['value'])
        self.assertIsNone(M.engagement_velocity(old,{**new,'provider_observed_at':new['received_at']})['value'])

    def test_provider_measurement_and_retrieval_times_remain_distinct(self):
        old={'provider_id':'fixture','platform':'bluesky','source_identity':'x','metric_definition_id':'likes','counter_epoch':'v1',
             'value':10,'received_at':'2026-09-27T18:00:00Z','provider_observed_at':'2026-09-27T17:00:00Z'}
        new={**old,'value':16,'received_at':'2026-09-27T20:00:00Z','provider_observed_at':'2026-09-27T18:30:00Z'}
        result=M.engagement_velocity(old,new)
        self.assertEqual((result['value'],result['elapsed_hours'],result['time_basis']),(4.0,1.5,'provider_measurement'))
        self.assertNotEqual(new['provider_observed_at'],new['received_at'])

    def test_creator_entropy_effective_creators_and_largest_share_are_distinct(self):
        observed=windows()[-1]['observed']
        self.assertAlmostEqual(observed['effective_creators'],math.exp(observed['creator_entropy']))
        self.assertAlmostEqual(observed['largest_creator_share'],4/150)
        self.assertNotEqual(observed['effective_creators'],observed['known_author_post_count'])

    def test_occupancy_and_redundancy_denominators(self):
        assignments=[{'observation_id':str(i),'dimension':'hook','pattern_id':'chosen' if i<20 else str(i),'copy_group_id':'copy' if i<20 else str(i)} for i in range(80)]
        result=M.pattern_occupancy([str(i) for i in range(100)],assignments,dimension='hook')
        self.assertEqual(result['classification_coverage'],.8);self.assertEqual(result['pattern_shares']['chosen'],.25)
        self.assertEqual(result['redundancy_ratio'],19/80);self.assertEqual(result['unclassified_count'],20);self.assertIsNone(result['saturation'])

    def test_no_future_baseline_or_duplicate_window_support(self):
        f=fixture();w=windows(f)
        out=B.build_baseline([w[0]]*4,current_window=w[-1],decision_cutoff=f['decision_cutoff'],match_hour_of_week=False)
        self.assertEqual(out['sample_windows'],1);self.assertIsNone(out['baseline_rate'])
        out=B.build_baseline([w[-1]],current_window=w[-1],decision_cutoff=f['decision_cutoff'])
        self.assertEqual(out['sample_windows'],0)

    def test_zero_count_requires_an_admitted_source_frame(self):
        f=fixture()
        out=M.aggregate_window([],decision_cutoff=f['decision_cutoff'],source_policies=[],**f['window_specs'][-1])
        self.assertIsNone(out['mention_rate']['value']);self.assertEqual(out['mention_rate']['reason'],'source_policy_unavailable')
        out=M.aggregate_window([],decision_cutoff=f['decision_cutoff'],source_policies=f['source_policies'],**f['window_specs'][-1])
        self.assertEqual(out['mention_rate']['value'],0)

    def test_future_baseline_is_not_decision_time_knowledge(self):
        b=baseline();b['decision_cutoff']='2026-09-28T00:00:00Z'
        out=V.compute_momentum(windows(),b)
        self.assertEqual(out['growth_pct']['reason'],'future_baseline')
