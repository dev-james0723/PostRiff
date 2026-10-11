"""Offline owner scheduling isolation; synthetic inputs never qualify Telegram."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.telegram.canary_worker import selected, worker_scope
from test_postriff_phase2_hosted import invoke

NOW = 1800000000
WORKSPACE = '11111111-1111-4111-8111-111111111111'
ACTOR = '22222222-2222-4222-8222-222222222222'


def grant():
    return {'workspaceId': WORKSPACE, 'actorId': ACTOR, 'botId': 999, 'expiresAt': NOW + 600,
            'destinations': [{'chatId': -100123, 'mode': 'bot', 'capabilities': ['publish', 'schedule', 'text']}]}


class CanaryWorkerTests(unittest.TestCase):
    def test_invalid_or_expired_grant_cannot_open_a_worker_database(self):
        database = Mock(side_effect=AssertionError('No database access'))
        worker = PostgresWorker(database, clock=lambda: NOW)
        for scope in (None, {}, {**grant(), 'expiresAt': NOW}, {**grant(), 'expiresAt': NOW + 86401},
                      {**grant(), 'expiresAt': float('nan')}, {**grant(), 'botId': True},
                      {**grant(), 'workspaceId': 'other'}, {**grant(), 'actorId': 'other'},
                      {**grant(), 'destinations': []},
                      {**grant(), 'destinations': [{'chatId': -100123, 'mode': 'business', 'capabilities': ['publish', 'schedule']}]},
                      {**grant(), 'destinations': [{'chatId': -100123, 'mode': 'bot', 'capabilities': ['publish']}]},
                      {**grant(), 'destinations': [{'chatId': True, 'mode': 'bot', 'capabilities': ['publish', 'schedule']}]}):
            with self.subTest(scope=scope), self.assertRaises(AlphaError):
                worker.tick_telegram_canary(scope)
        database.assert_not_called()

    def test_canary_budget_has_no_youtube_maintenance_and_rechecks_expiry(self):
        clock = [NOW]
        youtube = SimpleNamespace(maintenance=Mock(side_effect=AssertionError('No shared maintenance')))
        worker = PostgresWorker(Mock(), social=SimpleNamespace(youtube=youtube), clock=lambda: clock[0])
        worker.step = Mock(return_value=False)
        scope = grant()
        before = copy.deepcopy(scope)
        result = worker.tick_telegram_canary(scope)
        self.assertEqual(result['budget'], {'maxJobs': 1, 'maxSeconds': 5})
        self.assertEqual(result['processed'], 0)
        self.assertEqual(scope, before)
        self.assertEqual(worker.step.call_args.kwargs['telegram_canary']['workspaceId'], WORKSPACE)
        youtube.maintenance.assert_not_called()
        clock[0] = scope['expiresAt']
        with self.assertRaises(AlphaError):
            worker.tick_telegram_canary(scope)
        self.assertEqual(worker.step.call_count, 1)

    def test_grant_expiry_after_claim_blocks_provider_egress(self):
        worker = PostgresWorker(Mock(), social=Mock(), clock=lambda: NOW + 600)
        worker.claim = Mock(return_value={'reconciliation': True, 'job': {'manifest': {}}, 'workspaceId': WORKSPACE})
        with self.assertRaises(AlphaError):
            worker.step(telegram_canary=grant())
        worker.social.submit.assert_not_called()
        worker.social.reconcile.assert_not_called()

    def test_scope_preserves_other_members_platforms_and_destinations(self):
        item = {'manifest': {'platform': 'Telegram', 'workspaceId': WORKSPACE, 'actor': ACTOR, 'channelId': 'qa'},
                'approvedBy': ACTOR}
        self.assertTrue(selected(item, grant(), ['qa']))
        for change in ({'platform': 'X'}, {'workspaceId': 'another'}, {'actor': 'another'}, {'channelId': 'other'}):
            self.assertFalse(selected({**item, 'manifest': {**item['manifest'], **change}}, grant(), ['qa']))
        self.assertFalse(selected({**item, 'approvedBy': 'another'}, grant(), ['qa']))
        self.assertFalse(selected({'manifest': item['manifest']}, grant(), ['qa']))

    def test_other_background_routes_stop_before_runtime_initialization(self):
        app = HostedApplication(cron_secret='c' * 24)
        app._runtime = Mock(side_effect=AssertionError('No runtime initialization'))
        with patch.dict('os.environ', {'POSTRIFF_TELEGRAM_CANARY_ENABLED': 'true'}):
            for path in ('/api/cron/agent-tasks', '/api/cron/youtube/uploads', '/api/cron/future'):
                status, _, result = invoke(app, 'GET', path, headers={'Authorization': 'Bearer ' + 'c' * 24})
                self.assertEqual(status, 503)
                self.assertEqual(result['code'], 'telegram_canary_jobs_isolated')
        app._runtime.assert_not_called()

    def test_unauthorized_worker_does_not_initialize_runtime(self):
        app = HostedApplication(cron_secret='c' * 24)
        app._runtime = Mock(side_effect=AssertionError('No runtime initialization'))
        with patch.dict('os.environ', {'POSTRIFF_TELEGRAM_CANARY_ENABLED': 'true'}):
            status, _, _ = invoke(app, 'GET', '/api/cron/worker', headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(status, 401)
        app._runtime.assert_not_called()

    def test_authorized_cron_uses_only_telegram_lane(self):
        scope = grant()
        service = SimpleNamespace(oauth=SimpleNamespace(telegram=SimpleNamespace(candidate_scope=scope)),
                                  run_reminders=Mock(side_effect=AssertionError('No shared reminders')))
        worker = PostgresWorker(Mock(), clock=lambda: NOW)
        worker.tick = Mock(side_effect=AssertionError('No shared worker'))
        worker.step = Mock(return_value=False)
        app = HostedApplication(service, worker, cron_secret='c' * 24)
        with patch.dict('os.environ', {'POSTRIFF_TELEGRAM_CANARY_ENABLED': 'true'}):
            status, _, result = invoke(app, 'GET', '/api/cron/worker', headers={'Authorization': 'Bearer ' + 'c' * 24})
        self.assertEqual((status, result['processed'], result['acceptanceScope']), (200, 0, 'telegram_owner_only'))
        worker.tick.assert_not_called()
        service.run_reminders.assert_not_called()
