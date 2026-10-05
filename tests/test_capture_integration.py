"""Offline changed-boundary integration tests. Stubs do not prove runtime dispatch."""
import io
import json
import unittest
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import account_deletion
from postriff_phase2.ideas import IdeasService, request_fingerprint
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.permissions import Membership

WID = '00000000-0000-4000-8000-000000000101'
AID = '00000000-0000-4000-8000-000000000102'


class CaptureBoundaries(unittest.TestCase):
    def cron(self, repository):
        """Exercise the real cron route, with unrelated subsystems offline."""
        service = SimpleNamespace(repository=repository, ideas=None, run_reminders=Mock(return_value={'sent': 0}))
        worker = Mock()
        worker.tick.return_value = {'processed': 1, 'externalExecution': False}
        app = HostedApplication(service=service, worker=worker, cron_secret='offline-cron-secret-123456')
        environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/cron/worker', 'QUERY_STRING': '',
                   'wsgi.input': io.BytesIO(b''), 'HTTP_AUTHORIZATION': 'Bearer offline-cron-secret-123456'}
        output = {}
        with ExitStack() as stack:
            for target, result in (
                ('postriff_phase2.growth.history_import.sweep_pending_purges', {'status': 'offline'}),
                ('postriff_phase2.growth.trends.worker.cron', {'status': 'offline'}),
                ('postriff_phase2.coworker.runtime.cron', {'status': 'offline'}),
                ('postriff_phase2.phone.runtime.cron', {'status': 'offline'}),
                ('postriff_phase2.operational_signals.snapshot', {'status': 'ok'}),
                ('rafii_control.hosted.founder_tick', {'status': 'offline'}),
            ):
                stack.enter_context(patch(target, return_value=result))
            raw = b''.join(app(environ, lambda status, headers: output.update(status=int(status[:3]))))
        return output['status'], json.loads(raw), worker

    def test_capture_purge_failure_does_not_stop_unrelated_cron_work(self):
        repository = SimpleNamespace(connection_factory=Mock(side_effect=AssertionError('No real database permitted.')))
        with patch('postriff_phase2.capture_access.purge_expired', side_effect=RuntimeError('private-database-detail')) as purge, \
                self.assertLogs('postriff.capture', level='ERROR') as logs:
            status, result, worker = self.cron(repository)
        self.assertEqual((status, result['captureCleanup'], result['processed']), (200, 'failed', 1))
        worker.tick.assert_called_once_with()
        purge.assert_called_once_with(repository)
        self.assertIn('RuntimeError', logs.output[0])
        self.assertNotIn('private-database-detail', logs.output[0])

    def test_disabled_capture_feature_still_uses_restricted_installed_purge(self):
        cursor = Mock()
        cursor.fetchone.return_value = ('audit_private.capture_operation(text,jsonb)',)

        @contextmanager
        def cursor_context():
            yield cursor

        @contextmanager
        def connect():
            yield SimpleNamespace(cursor=cursor_context)

        repository = SimpleNamespace(connection_factory=connect)
        # The cron service has no active capture object or private key; cleanup uses only
        # the installed constrained SQL capability, even after the feature is disabled.
        with patch('postriff_phase2.request_capture.PostgresCaptureRepository') as restricted:
            restricted.return_value.call.return_value = {'purged_grants': 1}
            status, result, worker = self.cron(repository)
        self.assertEqual((status, result['captureCleanup']), (200, 'ok'))
        worker.tick.assert_called_once_with()
        cursor.execute.assert_called_once_with("SELECT to_regprocedure('audit_private.capture_operation(text,jsonb)')")
        restricted.assert_called_once_with(connect)
        restricted.return_value.call.assert_called_once_with('purge', {}, cursor=cursor)

    def test_understanding_rechecks_helper_need_at_actual_boundary(self):
        service = IdeasService.__new__(IdeasService)
        service.repository = Mock()
        service.repository.get.return_value = {'state': {}}
        service._read_request = Mock(return_value={'action': 'draft'})
        parsed = {'intent': 'draft'}
        with patch('postriff_phase2.request_model.wants_reading', return_value=True):
            with self.assertRaises(AlphaError) as failed:
                service._understand(WID, 'session', 'schedule later', 'UTC', object(), parsed, audit_required=True)
            self.assertEqual(failed.exception.code, 'audit_capture_blocked')
            service._read_request.assert_not_called()
            self.assertEqual(service._understand(WID, 'session', 'schedule later', 'UTC', object(), parsed)[1], {'action': 'draft'})
        service._read_request.reset_mock()
        # Even if automation names change after early validation, the actual helper decision fails closed.
        with patch('postriff_phase2.request_model.wants_reading', return_value=False), \
                patch('postriff_phase2.automation_edit.summaries', return_value=[{'name': 'newly-created'}]), \
                patch('postriff_phase2.workflow_parse.names_automation', return_value=True):
            with self.assertRaises(AlphaError):
                service._understand(WID, 'session', 'newly-created', 'UTC', object(), parsed, audit_required=True)
        service._read_request.assert_not_called()

    def test_ordinary_credit_denial_happens_before_audit_binding_or_helper(self):
        service = IdeasService.__new__(IdeasService)
        service._quick_start_replay = Mock(return_value=None)
        service.credit_requests = Mock()
        service.credit_requests.authorize.side_effect = AlphaError('Ordinary credits unavailable.', 402)
        service.resolve_writer = Mock()
        service._understand = Mock()
        service.capture = Mock()
        with self.assertRaises(AlphaError) as failed:
            service.quick_start(WID, 'session', 1, {'text': 'Piano lesson', 'confirmUse': True,
                'idempotencyKey': 'one', 'research': False, 'auditCapture': {'grantId': 'unbound', 'serverNonce': 'unbound'}})
        self.assertEqual(failed.exception.status, 402)
        service.resolve_writer.assert_not_called()
        service._understand.assert_not_called()
        service.capture.service.bind_grant.assert_not_called()

    def test_existing_run_replay_never_rebinds_a_grant_or_authorizes_new_credits(self):
        service = IdeasService.__new__(IdeasService)
        cur = Mock()

        @contextmanager
        def transaction(*args):
            yield cur, (1, {}, 'owner'), AID

        service.repository = SimpleNamespace(transaction=transaction)
        service._member = lambda row: Membership(row[2])
        service._conversation = Mock()
        service._keyed_run = Mock(return_value='existing-run')
        service._events_for = Mock(return_value={'runId': 'existing-run'})
        service.credit_requests = Mock()
        service.capture = Mock()
        payload = {'idempotencyKey': 'same', 'auditCapture': {'grantId': 'already-bound', 'serverNonce': 'same-nonce'}}
        self.assertEqual(service.turn(WID, 'session', 'conversation', payload), {'runId': 'existing-run'})
        service.credit_requests.authorize.assert_not_called()
        service.capture.service.bind_grant.assert_not_called()
        changed = {**payload, 'auditCapture': {'grantId': 'different', 'serverNonce': 'different'}}
        self.assertNotEqual(request_fingerprint('turn', payload, 'conversation'), request_fingerprint('turn', changed, 'conversation'))

    def test_private_capture_http_routes_require_session_and_same_origin(self):
        capture = Mock()
        capture.status.return_value = {'enabled': True}
        app = HostedApplication(service=SimpleNamespace(ideas=SimpleNamespace(capture=capture)))

        def request(method, suffix, authorization=None, origin='https://rafii.example'):
            raw = b'{}'
            environ = {'REQUEST_METHOD': method, 'PATH_INFO': f'/api/workspaces/{WID}/ideas/capture/{suffix}',
                'QUERY_STRING': '', 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)),
                'wsgi.input': io.BytesIO(raw), 'wsgi.url_scheme': 'https', 'HTTP_HOST': 'rafii.example', 'HTTP_ORIGIN': origin}
            if authorization:
                environ['HTTP_AUTHORIZATION'] = authorization
            result = {}
            data = b''.join(app(environ, lambda status, headers: result.update(status=int(status[:3]), headers=dict(headers))))
            return result, json.loads(data)

        result, _ = request('GET', 'status')
        self.assertEqual(result['status'], 401)
        capture.status.assert_not_called()
        result, _ = request('POST', 'grants', 'Bearer interactive-session-token-123456789', origin='https://foreign.example')
        self.assertEqual(result['status'], 403)
        capture.create.assert_not_called()
        result, data = request('GET', 'status', 'Bearer interactive-session-token-123456789')
        self.assertEqual((result['status'], data), (200, {'enabled': True}))
        self.assertEqual(result['headers']['Cache-Control'], 'no-store')
        capture.status.assert_called_once_with(WID, 'interactive-session-token-123456789')

    def test_deletion_revokes_capture_before_any_external_cleanup(self):
        order = []
        state = {'accountDeletion': {'receiptId': 'pending'}, 'phase2': {'assets': [], 'jobs': []}}

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query, *args): self.query = query
            def fetchone(self): return (state, 'owner') if self.query.startswith('SELECT w.state,m.role') else None

        cursor = Cursor()

        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return cursor

        capture_service = Mock(allowlisted_workspace=WID)
        capture_service.revoke_workspace.side_effect = lambda *args, **kwargs: order.append('capture-revoked')
        service = SimpleNamespace(connection_factory=Connection, ideas=SimpleNamespace(capture=SimpleNamespace(service=capture_service)),
                                  phone=None, video_uploads=None)

        def stop_before_external(*args):
            order.append('external-cleanup-boundary')
            raise RuntimeError('offline stop')

        with patch.object(account_deletion, 'revoke_remote_grants', side_effect=stop_before_external), self.assertRaises(RuntimeError):
            account_deletion._delete(service, WID, AID)
        self.assertEqual(order, ['capture-revoked', 'external-cleanup-boundary'])
        capture_service.revoke_workspace.assert_called_once_with(cursor, workspace_id=WID, actor_id=AID)


if __name__ == '__main__':
    unittest.main()
