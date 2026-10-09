"""Synthetic capacity and resumable-delay contracts; no Google or real acceptance."""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube.capacity import CapacityPolicy, CapacityController, DEFAULT_LIMITS, DEFAULT_ANALYTICS_LIMITS, budget_decision, analytics_budget_decision
from postriff_phase2.youtube.model import YouTubeError
from postriff_phase2.youtube.uploads import CHUNK_ALIGNMENT, CHUNK_SIZE, configured_chunk_size
import test_youtube_creator as creator_fixtures


class CapacityPolicyTests(unittest.TestCase):
    def provider(self, proof=None, client='client-one'):
        return SimpleNamespace(client_id=client, project_evidence=proof or {})

    def proof(self):
        return {'projectId': 'synthetic-project', 'clientId': 'client-one', 'quota': {
            'status': 'verified', 'source': 'google_platform', 'reference': 'synthetic-only',
            'observedAt': datetime.now(timezone.utc).isoformat(),
            'limits': {'videoUploads': 5000, 'search': 1000, 'general': 200000}}}

    def test_environment_cannot_manufacture_approved_capacity(self):
        policy = CapacityPolicy.from_environment(self.provider(), {'POSTRIFF_YOUTUBE_UPLOAD_DAILY_LIMIT': '5000'})
        self.assertEqual(policy.limits, DEFAULT_LIMITS)
        self.assertFalse(policy.approved_evidence)
        self.assertNotIn('client-one', policy.project_key)

    def test_only_fresh_bound_google_evidence_can_raise_ceiling(self):
        proof = self.proof()
        self.assertEqual(CapacityPolicy.from_environment(self.provider(proof)).limits['videoUploads'], 5000)
        for change in ({'source': 'operator_assertion'}, {'status': 'submitted'}, {'observedAt': '2000-01-01'}, {'reference': ''}, {'projectId': 'another-project'}):
            bad = copy.deepcopy(proof); bad['quota'].update(change)
            self.assertEqual(CapacityPolicy.from_environment(self.provider(bad)).limits, DEFAULT_LIMITS)
        self.assertEqual(CapacityPolicy.from_environment(self.provider(proof, 'different-client')).limits, DEFAULT_LIMITS)

    def test_clients_in_same_bound_project_share_budget_without_fake_verification(self):
        one = self.provider({'projectId': 'one-project', 'clientId': 'client-one'})
        two = self.provider({'projectId': 'one-project', 'clientId': 'client-two'}, 'client-two')
        self.assertEqual(CapacityPolicy.from_environment(one).project_key, CapacityPolicy.from_environment(two).project_key)
        self.assertFalse(CapacityPolicy.from_environment(one).approved_evidence)

    def test_operator_can_lower_limits_but_never_raise_above_approval(self):
        policy = CapacityPolicy.from_environment(self.provider(self.proof()), {
            'POSTRIFF_YOUTUBE_UPLOAD_DAILY_LIMIT': '50', 'POSTRIFF_YOUTUBE_GENERAL_DAILY_LIMIT': '999999999'})
        self.assertEqual(policy.limits['videoUploads'], 50)
        self.assertEqual(policy.limits['general'], 200000)
        self.assertTrue(all(policy.workspace_limits[k] <= v for k, v in policy.limits.items()))

    def test_project_workspace_and_rate_limits_are_distinct(self):
        policy = CapacityPolicy('synthetic')
        now = datetime(2026, 3, 8, 9, 59, tzinfo=timezone.utc).timestamp()
        self.assertEqual(budget_decision(policy, 'videoUploads', 1, 100, 0, 0, now)[0], 'project_daily')
        self.assertEqual(budget_decision(policy, 'videoUploads', 1, 5, 5, 0, now)[0], 'workspace_daily')
        self.assertEqual(budget_decision(policy, 'videoUploads', None, 100, 5, 120, now)[0], 'workspace_rate')
        reset = budget_decision(policy, 'videoUploads', 1, 100, 0, 0, now)[1]
        self.assertEqual(datetime.fromtimestamp(reset, timezone.utc).isoformat(), '2026-03-09T07:00:00+00:00')
        self.assertIsNone(budget_decision(policy, 'videoUploads', None, 100, 5, 0, now))
        with self.assertRaises(AlphaError): budget_decision(policy, 'unrecognized', 1, 0, 0, 0, now)

    def test_queue_limits_count_pending_across_channels_only_in_this_workspace(self):
        controller = CapacityController(None, CapacityPolicy('synthetic', pending_per_workspace=2))
        job = {'state': 'approved', 'manifest': {'platform': 'YouTube'}}
        state = {'phase2': {'jobs': [copy.deepcopy(job), copy.deepcopy(job)]}}
        with self.assertRaises(AlphaError): controller.assert_queue_capacity(state)
        controller.assert_queue_capacity(state, additional=0)
        with self.assertRaises(AlphaError): controller.assert_queue_capacity(state, additional=2)
        state['phase2']['jobs'][0]['state'] = 'canceled'
        controller.assert_queue_capacity(state)
        state['phase2']['jobs'][0] = {'state': 'approved', 'manifest': {'platform': 'LinkedIn'}}
        controller.assert_queue_capacity(state)

    def test_chunks_are_aligned_and_memory_bounded(self):
        self.assertEqual(configured_chunk_size(), 8 * 1024 * 1024)
        self.assertEqual(configured_chunk_size(str(CHUNK_ALIGNMENT)), CHUNK_ALIGNMENT)
        for invalid in (1, CHUNK_SIZE + CHUNK_ALIGNMENT, 'bad', True, CHUNK_ALIGNMENT + 1):
            with self.assertRaises(AlphaError): configured_chunk_size(invalid)

    def test_identity_reservation_has_fixed_method_and_no_invented_connection(self):
        controller = CapacityController(None, CapacityPolicy('synthetic'))
        controller._reserve = Mock()
        controller.record_identity('trusted-claimed-workspace')
        controller._reserve.assert_called_once_with('trusted-claimed-workspace', None, 'channels.list', 'general', 1)
        for missing in (None, ''):
            with self.assertRaises(AlphaError):
                controller.record('workspace', missing, 'videos.list', 'general', 1)


class AnalyticsCapacityTests(unittest.TestCase):
    provider = CapacityPolicyTests.provider
    proof = CapacityPolicyTests.proof

    def test_analytics_defaults_are_separate_request_limits_and_cannot_be_raised_by_environment(self):
        policy = CapacityPolicy.from_environment(self.provider(), {
            'POSTRIFF_YOUTUBE_ANALYTICS_DAILY_LIMIT': '9999999',
            'POSTRIFF_YOUTUBE_ANALYTICS_PROJECT_REQUESTS_PER_MINUTE': '9999999'})
        self.assertEqual(policy.limits, DEFAULT_LIMITS)
        self.assertEqual(policy.analytics_daily_limit, DEFAULT_ANALYTICS_LIMITS['requestsPerDay'])
        self.assertEqual(policy.analytics_project_per_minute, DEFAULT_ANALYTICS_LIMITS['requestsPerMinute'])
        self.assertFalse(policy.approved_evidence)

    def test_analytics_limits_lower_or_raise_only_with_fresh_exact_google_project_evidence(self):
        proof = self.proof()
        proof['quota']['analyticsLimits'] = {'requestsPerDay': 200000, 'requestsPerMinute': 1440}
        policy = CapacityPolicy.from_environment(self.provider(proof), {
            'POSTRIFF_YOUTUBE_ANALYTICS_DAILY_LIMIT': '50000',
            'POSTRIFF_YOUTUBE_ANALYTICS_PROJECT_REQUESTS_PER_MINUTE': '300',
            'POSTRIFF_YOUTUBE_ANALYTICS_WORKSPACE_DAILY_LIMIT': '9999999'})
        self.assertEqual((policy.analytics_daily_limit, policy.analytics_project_per_minute,
                          policy.analytics_workspace_daily_limit), (50000, 300, 50000))
        raised = CapacityPolicy.from_environment(self.provider(proof))
        self.assertEqual((raised.analytics_daily_limit, raised.analytics_project_per_minute), (200000, 1440))
        for change in ({'source': 'operator_assertion'}, {'status': 'submitted'}, {'observedAt': '2000-01-01'}, {'reference': ''}, {'projectId': 'wrong-project'}):
            bad = copy.deepcopy(proof); bad['quota'].update(change)
            closed = CapacityPolicy.from_environment(self.provider(bad))
            self.assertEqual((closed.analytics_daily_limit, closed.analytics_project_per_minute), (100000, 720))
        closed = CapacityPolicy.from_environment(self.provider(proof, 'wrong-client'))
        self.assertEqual((closed.analytics_daily_limit, closed.analytics_project_per_minute), (100000, 720))

    def test_analytics_invalid_limits_fail_to_conservative_defaults(self):
        proof = self.proof(); proof['quota']['analyticsLimits'] = {'requestsPerDay': True, 'requestsPerMinute': -1}
        policy = CapacityPolicy.from_environment(self.provider(proof), {
            'POSTRIFF_YOUTUBE_ANALYTICS_DAILY_LIMIT': 'broken',
            'POSTRIFF_YOUTUBE_ANALYTICS_PROJECT_REQUESTS_PER_MINUTE': '0',
            'POSTRIFF_YOUTUBE_ANALYTICS_WORKSPACE_DAILY_LIMIT': '-1'})
        self.assertEqual((policy.analytics_daily_limit, policy.analytics_project_per_minute,
                          policy.analytics_workspace_daily_limit), (100000, 720, 2000))

    def test_analytics_daily_project_minute_and_workspace_rate_backoffs_are_distinct(self):
        policy = CapacityPolicy('synthetic', analytics_daily_limit=10, analytics_project_per_minute=3,
                                analytics_workspace_daily_limit=4, requests_per_minute=2)
        now = datetime(2026, 3, 8, 9, 59, tzinfo=timezone.utc).timestamp()
        for args, reason in (((10, 0, 0, 0), 'analytics_project_daily'),
                             ((0, 4, 0, 0), 'analytics_workspace_daily'),
                             ((0, 0, 3, 0), 'analytics_project_rate'),
                             ((0, 0, 0, 2), 'workspace_rate')):
            decision = analytics_budget_decision(policy, *args, now)
            self.assertEqual(decision[0], reason)
            self.assertGreater(decision[1], now)
            if reason.endswith('daily'):
                self.assertEqual(datetime.fromtimestamp(decision[1], timezone.utc).isoformat(), '2026-03-09T07:00:00+00:00')
            else:
                self.assertEqual(decision[1], now // 60 * 60 + 60)
        self.assertIsNone(analytics_budget_decision(policy, 9, 3, 2, 1, now))

    def test_null_analytics_cost_routes_to_request_counter_without_inventing_data_units(self):
        controller = CapacityController(None, CapacityPolicy('synthetic'))
        controller._reserve_analytics = Mock()
        controller.record('workspace', 'connection', 'analytics.reports.query', 'analytics', None)
        controller._reserve_analytics.assert_called_once_with('workspace', 'connection', 'analytics.reports.query')
        for method, cost in (('analytics.reports.query', 1), ('videos.list', None)):
            with self.assertRaises(AlphaError):
                controller.record('workspace', 'connection', method, 'analytics', cost)


class UploadCapacityDelayTests(unittest.TestCase):
    def setup(self):
        case = creator_fixtures.UploadTests(); case.setup_engine()
        return case

    def test_denied_initiation_sends_no_request_then_resumes_same_journal_once(self):
        case = self.setup()
        def deny(*_):
            raise YouTubeError('capacity_delay', 'Synthetic capacity delay.', status=429, retry_at=case.clock[0] + 60)
        case.engine.account_usage = deny
        delayed = case.engine.step(case.m)
        self.assertEqual(delayed['progress']['stage'], 'quota_delayed')
        self.assertEqual(case.wire.calls, [])
        self.assertNotIn('session_open_attempted', [s['stage'] for s in case.journal.saves])
        case.engine.step(case.m)
        self.assertEqual(case.wire.calls, [])
        case.engine.account_usage = lambda *_: None
        case.advance(); case.advance()
        self.assertEqual(sum(c[0] == 'POST' for c in case.wire.calls), 1)

    def test_delayed_resume_preserves_encrypted_session_and_acknowledged_offset(self):
        case = self.setup(); case.advance()
        before = case.wire.offset
        case.clock[0] += 2
        case.engine.account_usage = lambda *_: (_ for _ in ()).throw(
            YouTubeError('capacity_delay', 'Synthetic capacity delay.', status=429, retry_at=case.clock[0] + 60))
        delayed = case.engine.step(case.m)
        self.assertEqual(delayed['progress']['stage'], 'quota_delayed')
        self.assertEqual(case.wire.offset, before)
        case.engine.account_usage = lambda *_: None
        final = case.advance()
        self.assertEqual(final['reference'], 'abcdefghijk')
        self.assertEqual(sum(c[0] == 'POST' for c in case.wire.calls), 1)


if __name__ == '__main__':
    unittest.main()
