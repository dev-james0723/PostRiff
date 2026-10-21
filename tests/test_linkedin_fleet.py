"""Cron authentication, bounded concurrency and fail-closed dispatch controls."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_worker import PostgresWorker, due_workspaces_sql
from postriff_phase2.linkedin_fleet import configuration, tick
from test_postriff_phase2_hosted import invoke


ENABLED = {'POSTRIFF_LINKEDIN_FLEET_ENABLED': 'true'}


class LinkedInFleet(unittest.TestCase):
    def base(self, approved=True, execution=True):
        provider = SimpleNamespace(execution_enabled=execution,
                                   member_publishing_approved=lambda: approved)
        return PostgresWorker(Mock(), social=SimpleNamespace(providers={'linkedin': provider}),
                              worker_binding={'environment': 'preview', 'origin': 'https://preview.example.invalid'},
                              on_verified=Mock())

    def test_disabled_default_never_constructs_a_worker_or_reads_custody(self):
        worker = self.base()
        with patch('postriff_phase2.linkedin_fleet.PostgresWorker') as factory:
            self.assertEqual(tick(worker, {}), {'enabled': False, 'processed': 0, 'externalExecution': False})
        factory.assert_not_called()
        worker.connection_factory.assert_not_called()

    def test_invalid_limits_pause_before_any_worker_or_provider_call(self):
        for field in ('WORKERS', 'MAX_JOBS', 'MAX_SECONDS'):
            for value in (0, -1, 1000, True, '1.5', 'NaN'):
                with self.subTest(field=field, value=value), self.assertRaises(AlphaError) as error:
                    configuration({**ENABLED, 'POSTRIFF_LINKEDIN_FLEET_' + field: value})
                self.assertEqual(error.exception.code, 'linkedin_fleet_configuration')
        self.assertEqual(configuration(ENABLED), dict(enabled=True, workers=8, maxJobs=25, maxSeconds=45))

    def test_unapproved_or_disabled_app_never_dispatches(self):
        for approved, execution in ((False, True), (True, False)):
            worker = self.base(approved, execution)
            with patch('postriff_phase2.linkedin_fleet.PostgresWorker') as factory:
                result = tick(worker, ENABLED)
            self.assertEqual(result['state'], 'provider_access_unavailable')
            self.assertEqual(result['processed'], 0)
            factory.assert_not_called()
            worker.connection_factory.assert_not_called()

    def test_pool_preserves_exact_deployment_binding_and_authority_context(self):
        worker = self.base()
        child = Mock()
        child.tick_linkedin.return_value = {'processed': 1}
        with patch('postriff_phase2.linkedin_fleet.PostgresWorker', return_value=child) as factory:
            result = tick(worker, ENABLED)
        self.assertEqual(result['processed'], 8)
        self.assertEqual(factory.call_count, 8)
        for call in factory.call_args_list:
            self.assertIs(call.args[0], worker.connection_factory)
            self.assertIs(call.kwargs['social'], worker.social)
            self.assertEqual(call.kwargs['worker_binding'], worker.worker_binding)
            self.assertIs(call.kwargs['clock'], worker.clock)
            self.assertIs(call.kwargs['on_verified'], worker.on_verified)
        self.assertEqual(child.tick_linkedin.call_count, 8)
        child.tick_linkedin.assert_called_with(25, 45)

    def test_unknown_effect_is_not_retried_or_exposed_by_the_pool(self):
        worker = self.base()
        child = Mock()
        child.tick_linkedin.side_effect = TimeoutError('private provider payload')
        with patch('postriff_phase2.linkedin_fleet.PostgresWorker', return_value=child):
            result = tick(worker, {**ENABLED, 'POSTRIFF_LINKEDIN_FLEET_WORKERS': 1})
        self.assertEqual(child.tick_linkedin.call_count, 1)
        self.assertEqual(result['errors'], ['TimeoutError'])
        self.assertNotIn('private provider payload', str(result))

    def test_linkedin_lane_is_bounded_and_has_no_cross_platform_maintenance(self):
        worker = self.base()
        worker.step = Mock(return_value=True)
        worker.youtube_maintenance = Mock()
        result = worker.tick_linkedin(2, 1)
        self.assertEqual(result['processed'], 2)
        self.assertEqual(worker.step.call_count, 2)
        worker.step.assert_called_with(linkedin_only=True)
        worker.youtube_maintenance.assert_not_called()
        worker.connection_factory.assert_not_called()

    def test_short_peer_claim_contention_does_not_abandon_a_ready_lane(self):
        worker = self.base()
        def step(**kwargs):
            self.assertEqual(kwargs, {'linkedin_only': True})
            count = worker.step.call_count
            worker.claim_contended = count == 1
            return count == 2
        worker.step = Mock(side_effect=step)
        with patch('postriff_phase2.hosted_worker.time.sleep') as pause:
            self.assertEqual(worker.tick_linkedin(2, 1)['processed'], 1)
        self.assertEqual(worker.step.call_count, 3)
        pause.assert_called_once_with(.02)

    def test_platform_selector_cannot_expand_to_youtube(self):
        self.assertIn("j#>>'{manifest,platform}'='LinkedIn'", due_workspaces_sql(linkedin_only=True))
        with self.assertRaises(AlphaError):
            due_workspaces_sql(linkedin_only=True, youtube_only=True)

    def test_cron_authentication_precedes_runtime_and_dispatch(self):
        app = HostedApplication(cron_secret='synthetic-cron-secret-0000000000')
        app._runtime = Mock(side_effect=AssertionError('Unauthenticated cron must not initialize runtime'))
        for authorization in ('', 'Bearer wrong-secret', 'Bearer ordinary-user-session'):
            status, _, _ = invoke(app, 'GET', '/api/cron/linkedin/worker', {}, {'Authorization': authorization})
            self.assertEqual(status, 401)
        app._runtime.assert_not_called()

    def test_valid_cron_can_only_invoke_the_configured_server_pool(self):
        app = HostedApplication(service=SimpleNamespace(), worker=Mock(), cron_secret='synthetic-cron-secret-0000000000')
        with patch('postriff_phase2.linkedin_fleet.tick', return_value={'enabled': False, 'processed': 0}) as run:
            status, _, result = invoke(app, 'GET', '/api/cron/linkedin/worker', {},
                                       {'Authorization': 'Bearer synthetic-cron-secret-0000000000'})
        self.assertEqual(status, 200)
        self.assertEqual(result['processed'], 0)
        run.assert_called_once_with(app.worker)


if __name__ == '__main__':
    unittest.main()
