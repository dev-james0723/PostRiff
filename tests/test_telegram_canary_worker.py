"""Offline owner scheduling isolation; synthetic inputs never qualify Telegram."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.telegram.canary_worker import LEGACY_FENCE_AT, accepts_event, dispatch_at, fence_job, ingress_scope, preserve_fence, selected, worker_scope
from postriff_phase2.telegram.canary_cron import NoRedirect, preserve_live_cron
from postriff_phase2.social_release import PRODUCTION_PROJECT, PRODUCTION_REF, PRODUCTION_URL
from test_postriff_phase2_hosted import invoke

NOW = 1800000000
WORKSPACE = '11111111-1111-4111-8111-111111111111'
ACTOR = '22222222-2222-4222-8222-222222222222'


def grant():
    return {'workspaceId': WORKSPACE, 'actorId': ACTOR, 'botId': 999, 'expiresAt': NOW + 600,
            'destinations': [{'chatId': -100123, 'mode': 'bot', 'capabilities': ['publish', 'schedule', 'text']}]}


def approved_job():
    return {'id': 'qa-job', 'state': 'approved', 'approvedBy': ACTOR, 'approvalDigest': 'reviewed',
            'nextAt': NOW, 'manifest': {'platform': 'Telegram', 'workspaceId': WORKSPACE,
                'actor': ACTOR, 'channelId': 'qa', 'expiresAt': NOW + 300}}


class CanaryCronContinuityTests(unittest.TestCase):
    def values(self):
        return {'VERCEL_ENV': 'production', 'VERCEL_PROJECT_ID': PRODUCTION_PROJECT,
                'VERCEL_URL': 'postriff-phase2-private-new-jamesau0723-6572s-projects.vercel.app',
                'POSTRIFF_SUPABASE_URL': PRODUCTION_URL, 'NEXT_PUBLIC_SUPABASE_URL': PRODUCTION_URL,
                'POSTRIFF_DATABASE_URL': 'postgresql://postgres.' + PRODUCTION_REF + ':synthetic@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require',
                'POSTRIFF_TELEGRAM_CANARY_ENABLED': 'true',
                'POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN': 'https://postriff-phase2-private-accepted-jamesau0723-6572s-projects.vercel.app'}

    def platform_headers(self):
        return {'Authorization': 'Bearer ' + 'c' * 24, 'User-Agent': 'vercel-cron/1.0',
                'X-Vercel-Cron-Schedule': '* * * * *'}

    def test_manual_acceptance_does_not_invoke_live_worker(self):
        send = Mock(side_effect=AssertionError('No shared worker'))
        self.assertIsNone(preserve_live_cron({}, self.values(), 'c' * 24, send=send))
        send.assert_not_called()

    def test_platform_call_delegates_once_to_exact_accepted_host(self):
        send = Mock(return_value=200)
        result = preserve_live_cron({'HTTP_USER_AGENT': 'vercel-cron/1.0',
                                     'HTTP_X_VERCEL_CRON_SCHEDULE': '* * * * *'},
                                    self.values(), 'c' * 24, send=send)
        self.assertEqual(result, {'state': 'delegated', 'upstreamHttpStatus': 200, 'retried': False})
        url, headers = send.call_args.args
        self.assertEqual(url, self.values()['POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN'] + '/api/cron/worker')
        self.assertEqual(headers['Authorization'], 'Bearer ' + 'c' * 24)
        self.assertEqual(headers['X-Postriff-Telegram-Cron-Relay'], '1')
        send.assert_called_once()

    def test_unknown_missing_alias_redirect_and_self_targets_never_receive_secret(self):
        for origin in ('', 'https://rafii.io', 'http://postriff-phase2-private-accepted-jamesau0723-6572s-projects.vercel.app',
                       self.values()['POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN'] + '/redirect',
                       self.values()['POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN'] + '?url=another',
                       'https://' + self.values()['VERCEL_URL'],
                       'https://user:password@postriff-phase2-private-accepted-jamesau0723-6572s-projects.vercel.app'):
            with self.subTest(origin=origin):
                send = Mock()
                with self.assertRaises(AlphaError):
                    preserve_live_cron({'HTTP_USER_AGENT': 'vercel-cron/1.0'},
                                       {**self.values(), 'POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN': origin},
                                       'c' * 24, send=send)
                send.assert_not_called()

    def test_relay_loop_and_wrong_environment_stop_before_network(self):
        for env, values in (({'HTTP_X_POSTRIFF_TELEGRAM_CRON_RELAY': '1'}, self.values()),
                            ({}, {**self.values(), 'VERCEL_ENV': 'preview'}),
                            ({}, {**self.values(), 'VERCEL_PROJECT_ID': 'another'})):
            send = Mock()
            with self.assertRaises(AlphaError):
                preserve_live_cron({'HTTP_USER_AGENT': 'vercel-cron/1.0', **env}, values, 'c' * 24, send=send)
            send.assert_not_called()

    def test_failed_or_ambiguous_old_worker_calls_are_scrubbed_and_never_retried(self):
        for response in (302, 401, 500, RuntimeError('Bearer ' + 'c' * 24)):
            send = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
            with self.subTest(response=type(response).__name__), self.assertRaises(AlphaError) as caught:
                preserve_live_cron({'HTTP_USER_AGENT': 'vercel-cron/1.0'}, self.values(), 'c' * 24, send=send)
            self.assertNotIn('c' * 24, str(caught.exception))
            send.assert_called_once()

    def test_redirect_handler_never_moves_cron_authorization_to_another_host(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://another.example'))

    def test_unauthorized_platform_request_never_relays_or_opens_runtime(self):
        app = HostedApplication(cron_secret='c' * 24)
        app._runtime = Mock()
        with patch.dict('os.environ', self.values()), patch('postriff_phase2.telegram.canary_cron._send') as send:
            status, _, _ = invoke(app, 'GET', '/api/cron/worker',
                                  headers={**self.platform_headers(), 'Authorization': 'Bearer wrong'})
        self.assertEqual(status, 401)
        send.assert_not_called()
        app._runtime.assert_not_called()

    def test_missing_live_target_stops_platform_request_before_runtime(self):
        app = HostedApplication(cron_secret='c' * 24)
        app._runtime = Mock()
        with patch.dict('os.environ', {**self.values(), 'POSTRIFF_TELEGRAM_CANARY_LIVE_WORKER_ORIGIN': ''}), \
                patch('postriff_phase2.telegram.canary_cron._send') as send:
            status, _, _ = invoke(app, 'GET', '/api/cron/worker', headers=self.platform_headers())
        self.assertEqual(status, 503)
        send.assert_not_called()
        app._runtime.assert_not_called()

    def test_grant_expiry_preserves_accepted_cron_without_shared_candidate_worker(self):
        service = SimpleNamespace(oauth=SimpleNamespace(telegram=SimpleNamespace(candidate_scope={})))
        worker = Mock()
        worker.tick_telegram_canary.side_effect = AlphaError('Expired', 503, code='telegram_canary_unavailable')
        app = HostedApplication(service, worker, cron_secret='c' * 24)
        with patch.dict('os.environ', self.values()), patch('postriff_phase2.telegram.canary_cron._send', return_value=200) as send:
            status, _, result = invoke(app, 'GET', '/api/cron/worker', headers=self.platform_headers())
        self.assertEqual((status, result['processed'], result['acceptanceState']), (200, 0, 'unavailable'))
        self.assertEqual(result['preservedLiveCron']['upstreamHttpStatus'], 200)
        send.assert_called_once()
        worker.tick.assert_not_called()


class CanaryWorkerTests(unittest.TestCase):
    def test_fence_preserves_approval_and_never_releases_to_legacy_reconciliation(self):
        job = approved_job()
        original = copy.deepcopy(job)
        fence_job(job, grant())
        self.assertEqual(job['manifest'], original['manifest'])
        self.assertEqual(job['approvalDigest'], original['approvalDigest'])
        self.assertEqual(dispatch_at(job, telegram_canary=True), NOW)
        self.assertEqual(dispatch_at(job), LEGACY_FENCE_AT)
        self.assertTrue(selected(job, grant(), ['qa'], require_fence=True))
        self.assertFalse(selected(original, grant(), ['qa'], require_fence=True))
        self.assertFalse(selected(job, {**grant(), 'expiresAt': NOW + 601}, ['qa'], require_fence=True))
        # An old worker skips nextAt before both forward and reconciliation paths.
        for state in ('approved', 'submitting', 'uncertain', 'processing'):
            job['state'] = state
            self.assertGreater(job['nextAt'], NOW + 10 * 86400)

    def test_retry_reschedule_and_cancellation_preserve_the_server_fence(self):
        job = approved_job()
        fence_job(job, grant())
        original = copy.deepcopy(job)
        job.pop('telegramCanary')
        job.update(state='scheduled', nextAt=NOW + 120)
        preserve_fence(job, original)
        self.assertEqual(job['nextAt'], LEGACY_FENCE_AT)
        self.assertEqual(dispatch_at(job, telegram_canary=True), NOW + 120)
        job['state'] = 'canceled'
        preserve_fence(job)
        self.assertEqual(job['nextAt'], LEGACY_FENCE_AT)
        plain = approved_job()
        preserve_fence(plain)
        self.assertEqual(plain, approved_job())

    def test_queue_fence_uses_active_owner_and_exact_unrevoked_destination(self):
        from postriff_phase2.telegram.service import TelegramService
        service = TelegramService.__new__(TelegramService)
        provider = SimpleNamespace(candidate_mode=True, candidate_scope=grant())
        service.oauth = SimpleNamespace(providers={'telegram': provider})
        service.clock = lambda: NOW
        cur = Mock()
        cur.fetchone.return_value = (1,)
        cur.fetchall.return_value = [('qa',)]
        job = approved_job()
        state = {'phase2': {'jobs': [job]}}
        service.fence_jobs(cur, WORKSPACE, {'phase2': {'jobs': []}}, state, ACTOR)
        self.assertEqual(job['nextAt'], LEGACY_FENCE_AT)
        self.assertIn('revoked_at IS NULL', cur.execute.call_args.args[0])
        self.assertEqual(cur.execute.call_args.args[1], (WORKSPACE, 999, [-100123]))
        for change in ({'channelId': 'outside'}, {'actor': 'outside'}, {'workspaceId': 'outside'}):
            bad = approved_job()
            bad['manifest'].update(change)
            with self.subTest(change=change), self.assertRaises(AlphaError):
                service.fence_jobs(cur, WORKSPACE, {}, {'phase2': {'jobs': [bad]}}, ACTOR)
        provider.candidate_scope = {**grant(), 'expiresAt': NOW}
        cur.reset_mock()
        with self.assertRaises(AlphaError):
            service.fence_jobs(cur, WORKSPACE, {}, {'phase2': {'jobs': [approved_job()]}}, ACTOR)
        cur.execute.assert_not_called()
        provider.candidate_mode = False
        untouched = approved_job()
        service.fence_jobs(cur, WORKSPACE, {}, {'phase2': {'jobs': [untouched]}}, ACTOR)
        self.assertEqual(untouched, approved_job())
        cur.execute.assert_not_called()

    def test_fence_runs_before_the_first_workspace_write(self):
        from contextlib import contextmanager
        from postriff_phase2.hosted import PostgresWorkspaceRepository
        repository = PostgresWorkspaceRepository(Mock(), Mock(), clock=lambda: NOW)
        cur = Mock()
        row = (1, {'phase2': {'jobs': []}}, 'owner', True, True, True, True)
        @contextmanager
        def transaction(*_args, **_kwargs):
            yield cur, row, ACTOR
        repository.transaction = transaction
        repository.before_save.append(lambda _cur, _wid, _before, after, _actor: fence_job(after['phase2']['jobs'][0], grant()))
        repository.command(WORKSPACE, None, 1, lambda state, _actor: {'phase2': {'jobs': [approved_job()]}})
        import json
        saved = json.loads(cur.execute.call_args_list[0].args[1][0])
        self.assertEqual(saved['phase2']['jobs'][0]['nextAt'], LEGACY_FENCE_AT)

    def test_completion_retry_does_not_expose_a_canary_job_to_the_old_worker(self):
        worker = PostgresWorker(Mock(), clock=lambda: NOW, worker_id='qa-worker')
        job = approved_job()
        fence_job(job, grant())
        job.update(state='submitting', leaseOwner='qa-worker', leaseId='lease', leaseUntil=NOW + 45, attempts=[])
        claimed = {'workspaceId': WORKSPACE, 'job': copy.deepcopy(job), 'reconciliation': False}
        cur = Mock()
        cur.fetchone.return_value = (1, {'phase2': {'jobs': [job]}})
        cur.rowcount = 1
        database = Mock()
        database.__enter__ = Mock(return_value=database)
        database.__exit__ = Mock(return_value=False)
        database.cursor.return_value.__enter__ = Mock(return_value=cur)
        database.cursor.return_value.__exit__ = Mock(return_value=False)
        worker.connection_factory.return_value = database
        result = {'state': 'scheduled', 'confirmed': 'Synthetic rate limit before acceptance', 'retryAfter': 120}
        with patch('postriff_phase2.hosted_worker.normalize_result', return_value=result):
            self.assertTrue(worker.complete(claimed, result))
        import json
        saved = json.loads(cur.execute.call_args.args[1][0])['phase2']['jobs'][0]
        self.assertEqual(saved['nextAt'], LEGACY_FENCE_AT)
        self.assertEqual(dispatch_at(saved, telegram_canary=True), NOW + 120)

    def test_workspace_projection_shows_actual_schedule_and_hides_internal_fence(self):
        from postriff_phase2.hosted import HostedPhase2Commands
        commands = HostedPhase2Commands(clock=lambda: NOW)
        job = approved_job()
        fence_job(job, grant())
        state = {'phase2': {'jobs': [job]}}
        commands.engine = SimpleNamespace(_present=lambda original, revision: {'state': copy.deepcopy(original), 'revision': revision})
        with patch('postriff_phase2.hosted.brand_brain.projection', return_value={}):
            shown = commands.present(state, 1)
        self.assertEqual(shown['state']['phase2']['jobs'][0]['nextAt'], NOW)
        self.assertNotIn('telegramCanary', shown['state']['phase2']['jobs'][0])
        self.assertEqual(state['phase2']['jobs'][0]['nextAt'], LEGACY_FENCE_AT)

    def test_public_invalidation_keeps_youtube_and_other_jobs_but_preserves_canary(self):
        protected = approved_job()
        fence_job(protected, grant())
        ordinary = []
        for platform in ('YouTube', 'Telegram', 'X'):
            job = approved_job()
            job['id'], job['manifest']['platform'] = platform, platform
            ordinary.append(job)
        state = {'phase2': {'jobs': [copy.deepcopy(protected), *ordinary], 'reviews': []}}
        cur = Mock()
        cur.fetchone.side_effect = [(True,), (None,)]
        cur.fetchall.return_value = [(WORKSPACE, 1, state)]
        cur.rowcount = 1
        database = MagicMock()
        database.__enter__.return_value = database
        database.cursor.return_value.__enter__.return_value = cur
        seen = []
        def invalidate(selected_state):
            for item in selected_state['phase2']['jobs']:
                seen.append(item['id'])
                item['state'] = 'held'
        worker = PostgresWorker(lambda: database, clock=lambda: NOW)
        worker.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=invalidate))
        self.assertIsNone(worker.claim())
        self.assertEqual(seen, ['YouTube', 'Telegram', 'X'])
        self.assertEqual(state['phase2']['jobs'][0], protected)

    def test_invalid_expired_or_outside_chat_ingress_has_zero_database_and_vault_calls(self):
        from postriff_phase2.telegram.updates import ingest
        database = Mock(side_effect=AssertionError('No database access'))
        vault = SimpleNamespace(encrypt=Mock(side_effect=AssertionError('No private context retained')))
        service = SimpleNamespace(repository=SimpleNamespace(connection_factory=database), vault=vault, clock=lambda: NOW)
        provider = SimpleNamespace(candidate_mode=True, candidate_scope=grant(), me=Mock(return_value={'id':999}))
        outside = {'update_id':1,'business_message':{'chat':{'id':825540},'business_connection_id':'outside','text':'excluded private context'}}
        self.assertTrue(ingest(service,provider,outside,b'synthetic').get('canaryIgnored'))
        for scope in (None, {}, {**grant(),'expiresAt':NOW}, {**grant(),'expiresAt':float('nan')},
                      {**grant(),'destinations':[{'chatId':7,'mode':'business','capabilities':['reply']}]}):
            provider.candidate_scope = scope
            with self.subTest(scope=scope):
                event = {'update_id':2,'channel_post':{'chat':{'id':-100123},'text':'synthetic'}}
                self.assertTrue(ingest(service,provider,event,b'synthetic').get('canaryIgnored'))
        provider.me.assert_not_called()
        database.assert_not_called()
        vault.encrypt.assert_not_called()

    def test_business_ingress_requires_exact_private_chat_and_connection(self):
        scope = grant()
        scope['destinations'].append({'chatId':777,'mode':'business','businessConnectionId':'qa-only','capabilities':['reply']})
        self.assertTrue(accepts_event(scope,'business_message',{'chat':{'id':777},'business_connection_id':'qa-only'}))
        for event in ({'chat':{'id':778},'business_connection_id':'qa-only'},
                      {'chat':{'id':777},'business_connection_id':'another'}, {'chat':{'id':True},'business_connection_id':'qa-only'}):
            self.assertFalse(accepts_event(scope,'business_message',event))
        provider = SimpleNamespace(candidate_mode=True,candidate_scope=scope)
        self.assertIsNotNone(ingress_scope(provider,NOW)[1])
        self.assertIsNone(ingress_scope(provider,NOW+600)[1])

    def test_ignored_update_cannot_reach_legacy_connect_code_claiming(self):
        from postriff_phase2.oauth import OAuthService
        oauth = OAuthService.__new__(OAuthService)
        oauth.telegram = object()
        oauth.repository = SimpleNamespace(connection_factory=Mock(side_effect=AssertionError('No legacy claim')))
        adapter = SimpleNamespace(webhook_secret='x'*32,observe=Mock(side_effect=AssertionError('No legacy observation')))
        with patch('postriff_phase2.telegram.updates.ingest',return_value={'ok':True,'canaryIgnored':True}):
            self.assertEqual(oauth.telegram_webhook('x'*32,b'{"update_id":1}',adapter),{'ok':True})
        adapter.observe.assert_not_called()
        oauth.repository.connection_factory.assert_not_called()

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
