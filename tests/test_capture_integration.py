"""Offline changed-boundary integration tests. Stubs do not prove runtime dispatch."""
import io
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import account_deletion
from postriff_phase2.ideas import IdeasService, request_fingerprint
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.permissions import Membership

WID = '0ceb3635-59a6-426f-bfa8-6d0203b8c98e'
AID = '5684cafc-9de2-48b2-a23e-7a914a07e1df'


class CaptureBoundaries(unittest.TestCase):
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
