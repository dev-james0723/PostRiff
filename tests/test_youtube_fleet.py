"""Synthetic isolated-lane controls; no cloud provisioning or Google acceptance."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_worker import PostgresWorker, due_workspaces_sql
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.youtube import fleet
from postriff_phase2.youtube.agent import YouTubePublishingAgent, activate_policy, change_policy, policy_authorization
from postriff_phase2.youtube.service import YouTubeCreatorService
from test_youtube_agent import AgentDatabase, CONNECTION, NOW, draft_and_policy, state
from test_youtube_worker_refresh import worker_for

ON = {'POSTRIFF_YOUTUBE_FLEET_ENABLED': '1', 'POSTRIFF_YOUTUBE_CREATOR_ENABLED': '1',
      'POSTRIFF_YOUTUBE_AGENTIC_ENABLED': '1'}


def runtime():
    creator = SimpleNamespace(oauth=SimpleNamespace(providers={'youtube': SimpleNamespace(creator_enabled=True)}),
        fleet_schema_ready=Mock(return_value=True), identity_one=Mock(), agent=SimpleNamespace(dispatch_one=Mock()),
        notifications=SimpleNamespace(renew_one=Mock(return_value=False)))
    return SimpleNamespace(youtube=creator), SimpleNamespace(tick_youtube=Mock(return_value={'processed': 2}))


class FleetConfigTests(unittest.TestCase):
    def test_default_off_and_exact_flags_make_no_runtime_or_worker_calls(self):
        for values in ({}, {'POSTRIFF_YOUTUBE_FLEET_ENABLED': '1'},
                       {**ON, 'POSTRIFF_YOUTUBE_FLEET_ENABLED': 'true'},
                       {**ON, 'POSTRIFF_YOUTUBE_CREATOR_ENABLED': '0'}):
            for lane in fleet.LANES:
                service, worker = runtime()
                self.assertFalse(fleet.run_lane(service, worker, lane, values)['enabled'])
                service.youtube.fleet_schema_ready.assert_not_called()
                worker.tick_youtube.assert_not_called()
                service.youtube.identity_one.assert_not_called()
                service.youtube.agent.dispatch_one.assert_not_called()
        service, worker = runtime()
        self.assertFalse(fleet.run_lane(service, worker, 'planner', {**ON, 'POSTRIFF_YOUTUBE_AGENTIC_ENABLED': '0'})['enabled'])
        service.youtube.agent.dispatch_one.assert_not_called()

    def test_server_budgets_are_bounded_and_do_not_take_client_inputs(self):
        self.assertEqual(fleet.limits('identity', {}), fleet.Limits(10, 20, 60))
        for field, bad in (('MAX_ITEMS', '26'), ('MAX_ITEMS', '0'), ('MAX_SECONDS', 'nan'),
                           ('MAX_SECONDS', '46'), ('MAX_REQUESTS', '201'), ('MAX_REQUESTS', '0')):
            with self.subTest(field=field, bad=bad), self.assertRaises(AlphaError) as caught:
                fleet.limits('identity', {'POSTRIFF_YOUTUBE_FLEET_IDENTITY_' + field: bad})
            self.assertEqual(caught.exception.code, 'youtube_fleet_configuration')
        with self.assertRaises(AlphaError) as caught:
            fleet.run_lane(*runtime(), 'customer-defined', ON)
        self.assertEqual(caught.exception.status, 404)

    def test_missing_schema_or_actual_creator_fails_before_work(self):
        service, worker = runtime()
        service.youtube.fleet_schema_ready.return_value = False
        self.assertEqual(fleet.run_lane(service, worker, 'upload', ON)['blocker'], 'youtube_schema_089_097_104_required')
        worker.tick_youtube.assert_not_called()
        service.youtube.oauth.providers['youtube'].creator_enabled = False
        self.assertEqual(fleet.run_lane(service, worker, 'identity', ON)['blocker'], 'youtube_creator_unavailable')
        service.youtube.identity_one.assert_not_called()


class LaneTests(unittest.TestCase):
    def test_upload_lane_uses_no_shared_tick_identity_planner_or_renewals(self):
        service, worker = runtime()
        result = fleet.run_lane(service, worker, 'upload', ON)
        worker.tick_youtube.assert_called_once_with(10, 20)
        self.assertEqual(result['processed'], 2)
        service.youtube.identity_one.assert_not_called()
        service.youtube.agent.dispatch_one.assert_not_called()
        service.youtube.notifications.renew_one.assert_not_called()

    def test_identity_batch_skips_failed_account_and_cannot_reselect_it(self):
        service, worker = runtime()
        exclusions = []
        selections = [('one', 'connection-a'), ('two', 'connection-b'), None]
        def identity(*, excluded):
            exclusions.append(excluded)
            selection = selections.pop(0)
            if selection:
                fleet.before_request()
            return {'selected': bool(selection), '_selection': selection, 'authorizationChecked': selection == ('two', 'connection-b'),
                    'reconnectionRequired': 'reconnect' if selection == ('one', 'connection-a') else None}
        service.youtube.identity_one.side_effect = identity
        result = fleet.run_lane(service, worker, 'identity', ON)
        self.assertEqual((result['processed'], result['identitiesVerified'], result['interventions']), (2, 1, 1))
        self.assertIn(('one', 'connection-a'), exclusions[1])
        self.assertNotIn('connection-a', str(result))
        worker.tick_youtube.assert_not_called()
        service.youtube.agent.dispatch_one.assert_not_called()

    def test_planner_continues_after_intervention_without_reselecting_workspace(self):
        service, worker = runtime()
        service.youtube.agent.dispatch_one.side_effect = [
            {'_workspace': 'held', 'dispatched': False, 'interventionRequired': True},
            {'_workspace': 'allowed', 'dispatched': True}, {'dispatched': False}]
        result = fleet.run_lane(service, worker, 'planner', ON)
        self.assertEqual((result['processed'], result['plansQueued'], result['interventions']), (2, 1, 1))
        self.assertIn('held', service.youtube.agent.dispatch_one.call_args_list[1].kwargs['exclude_workspaces'])
        self.assertTrue(all(call.kwargs['fleet'] is True for call in service.youtube.agent.dispatch_one.call_args_list))
        worker.tick_youtube.assert_not_called()
        service.youtube.identity_one.assert_not_called()

    def test_request_and_time_budget_stop_new_admissions_and_reset_context(self):
        with fleet.request_budget(fleet.Limits(10, 20, 1)) as budget:
            fleet.before_request()
            with self.assertRaises(AlphaError) as caught:
                fleet.before_request()
            self.assertEqual(caught.exception.capacity_reason, 'fleet_budget')
            self.assertEqual(budget.requests, 1)
        fleet.before_request()  # An unrelated API request inherits no lane budget.
        with fleet.request_budget(fleet.Limits(10, 1, 10)) as budget:
            budget.started -= 2
            with self.assertRaises(AlphaError):
                fleet.before_request()
            self.assertEqual(budget.requests, 0)

    def test_request_budget_bounds_identity_batch_and_does_not_renew_after_exhaustion(self):
        service, worker = runtime()
        def identity(*, excluded):
            fleet.before_request()
            return {'selected': True, '_selection': ('one', str(len(excluded))), 'authorizationChecked': True}
        service.youtube.identity_one.side_effect = identity
        result = fleet.run_lane(service, worker, 'identity', {**ON, 'POSTRIFF_YOUTUBE_FLEET_IDENTITY_MAX_REQUESTS': '1'})
        self.assertEqual((result['processed'], result['apiAdmissionAttempts'], result['budgetExhausted']), (1, 1, True))
        service.youtube.notifications.renew_one.assert_not_called()


class WorkerIsolationTests(unittest.TestCase):
    def test_default_shared_tick_unchanged_and_fleet_owner_keeps_cleanup_only(self):
        worker = PostgresWorker.__new__(PostgresWorker)
        maintenance = Mock(return_value={'enabled': True})
        worker.social = SimpleNamespace(youtube=SimpleNamespace(maintenance=maintenance))
        worker.step = Mock(return_value=False)
        with patch.dict('os.environ', {}, clear=True):
            worker.tick()
        maintenance.assert_called_once_with()
        worker.step.assert_called_once_with()
        maintenance.reset_mock(); worker.step.reset_mock()
        with patch.dict('os.environ', ON, clear=True):
            worker.tick()
        maintenance.assert_called_once_with(dispatch=False)
        worker.step.assert_called_once_with(youtube_only=False, exclude_youtube=True)
        maintenance.reset_mock(); worker.step.reset_mock()
        worker.tick_youtube(2, 2)
        maintenance.assert_not_called()
        worker.step.assert_called_once_with(youtube_only=True, exclude_youtube=False)

    @patch('postriff_phase2.billing.require_publishing')
    def test_real_job_filter_never_claims_or_invalidates_another_platform(self, _billing):
        worker, db, _, _, _ = worker_for(2)
        other = db.state['phase2']['jobs'][0]
        other['manifest']['platform'] = 'LinkedIn'
        other['manifest']['expiresAt'] = NOW - 1  # Would become held if invalidated by the upload lane.
        unchanged = copy.deepcopy(other)
        selected = worker.claim(youtube_only=True)
        self.assertEqual(selected['job']['id'], 'job-1')
        self.assertEqual(db.state['phase2']['jobs'][0], unchanged)
        self.assertIn("j#>>'{manifest,platform}'='YouTube'", due_workspaces_sql(youtube_only=True, operations_ready=False))
        self.assertIn("coalesce(j#>>'{manifest,platform}','')<>'YouTube'", due_workspaces_sql(exclude_youtube=True))
        with self.assertRaises(AlphaError):
            worker.claim(youtube_only=True, exclude_youtube=True)

    def test_cleanup_only_runs_retention_without_any_authorization_or_dispatch(self):
        creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
        creator.retention = Mock(return_value={'dataCleanup': True})
        creator.oauth = SimpleNamespace(providers={'youtube': SimpleNamespace(creator_enabled=True)})
        creator.identity_one = Mock(); creator.agent = SimpleNamespace(dispatch_one=Mock())
        result = creator.maintenance(dispatch=False)
        self.assertTrue(result['dataCleanup'])
        creator.retention.assert_called_once_with()
        creator.identity_one.assert_not_called()
        creator.agent.dispatch_one.assert_not_called()

    def test_planner_expired_or_replaced_fence_cannot_approve_or_queue(self):
        value = state(); draft_and_policy(value)
        value['youtubeAgent']['fleetLease'] = {'id': 'newer-worker', 'until': NOW + 120}
        db = AgentDatabase(value)
        creator = SimpleNamespace(service=SimpleNamespace(connection_factory=db.factory), repository=SimpleNamespace(), clock=lambda: NOW,
            oauth=SimpleNamespace(reverify_for_worker=Mock(return_value={'ready': True, 'state': 'read_verified'})))
        agent = YouTubePublishingAgent(creator)
        agent._agentic_gate = Mock()
        policy, draft = value['youtubeAgent']['policies'][0], value['youtubeAgent']['drafts'][0]
        candidate = ('workspace-one', CONNECTION, policy['id'], draft['id'], 'crashed-worker', policy_authorization(policy))
        with patch('postriff_phase2.youtube.agent.queue_draft') as queue:
            result = agent._dispatch_candidate(candidate)
        self.assertTrue(result['leaseLost'])
        queue.assert_not_called()
        self.assertEqual(db.state['phase2']['jobs'], [])

    @patch('postriff_phase2.billing.require_publishing')
    def test_transient_planner_verification_defers_without_revoking_finite_authority(self, _billing):
        value = state(); draft_and_policy(value)
        value['youtubeAgent']['fleetLease'] = {'id': 'worker', 'until': NOW + 120,
            'authorization': policy_authorization(value['youtubeAgent']['policies'][0])}
        db = AgentDatabase(value)
        service = SimpleNamespace(connection_factory=db.factory, commands=HostedPhase2Commands(clock=lambda: NOW))
        creator = SimpleNamespace(service=service, repository=SimpleNamespace(), clock=lambda: NOW,
            oauth=SimpleNamespace(reverify_for_worker=Mock(side_effect=[{'state': 'verification_unavailable', 'ready': False},
                {'state': 'read_verified', 'ready': True}])))
        agent = YouTubePublishingAgent(creator); agent._agentic_gate = Mock()
        policy, draft = value['youtubeAgent']['policies'][0], value['youtubeAgent']['drafts'][0]
        candidate = ('workspace-one', CONNECTION, policy['id'], draft['id'], 'worker', policy_authorization(policy))
        first = agent._dispatch_candidate(candidate)
        self.assertTrue(first['deferred'])
        self.assertEqual(db.state['youtubeAgent']['policies'][0]['status'], 'active')
        self.assertEqual(db.state['phase2']['jobs'], [])
        second = agent._dispatch_candidate(candidate)
        self.assertTrue(second['dispatched'])
        self.assertEqual(len(db.state['phase2']['jobs']), 1)
        self.assertEqual(db.state['youtubeAgent']['policies'][0]['status'], 'active')

    def test_old_success_or_error_cannot_use_or_pause_reactivated_authority(self):
        self._assert_reactivated_authority_is_preserved(leased=False)
        self._assert_reactivated_authority_is_preserved(leased=True)

    def _assert_reactivated_authority_is_preserved(self, *, leased):
        for fails in (False, True):
            for new_owner in ('owner', 'owner-b'):
                with self.subTest(leased=leased, fails=fails, new_owner=new_owner):
                    value = state(); draft, policy = draft_and_policy(value)
                    old_generation = policy['authorizationGeneration']
                    db = AgentDatabase(value)
                    creator = SimpleNamespace(service=SimpleNamespace(connection_factory=db.factory), repository=SimpleNamespace(),
                        clock=lambda: NOW, oauth=SimpleNamespace(reverify_for_worker=Mock(return_value={'ready': True, 'state': 'read_verified'})))
                    agent = YouTubePublishingAgent(creator)
                    candidate = agent._select_candidate(fleet=leased)
                    captured = copy.deepcopy(candidate[5])
                    self.assertEqual(captured['authorizationGeneration'], old_generation)
                    self.assertEqual(captured['policyDigest'], policy['digest'])
                    def reauthorize_then_finish(*_args):
                        # Same owner and frozen clock must still create a fresh
                        # authority generation; old client failure is then stale.
                        current = db.state['youtubeAgent']['policies'][0]
                        change_policy(db.state, CONNECTION, current['id'], 'pause', new_owner, NOW)
                        activate_policy(db.state, CONNECTION, current['id'], {'confirmed': True,
                            'digest': current['digest'], 'confirmationChannelId': current['channelId']}, new_owner, NOW)
                        if fails:
                            raise AlphaError('Old OAuth gate failed.', 409, code='youtube_agentic_oauth_required')
                    agent._agentic_gate = Mock(side_effect=reauthorize_then_finish)
                    with patch('postriff_phase2.youtube.agent.queue_draft') as queue:
                        result = agent._dispatch_candidate(candidate)
                    self.assertTrue(result['authorityChanged'])
                    current = db.state['youtubeAgent']['policies'][0]
                    self.assertEqual(current['status'], 'active')
                    self.assertEqual(current['grantedBy'], new_owner)
                    self.assertEqual(current['grantedAt'], NOW)
                    self.assertNotEqual(current['authorizationGeneration'], old_generation)
                    if leased:
                        self.assertEqual(db.state['youtubeAgent']['fleetLease']['authorization'], captured)
                    else:
                        self.assertNotIn('fleetLease', db.state['youtubeAgent'])
                    self.assertNotIn('intervention', current)
                    self.assertEqual(db.state['phase2']['jobs'], [])
                    queue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
