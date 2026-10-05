"""Offline access/scope checks; no database, provider or browser dispatch."""
import copy
import io
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import capture_access, request_capture, model_runtime
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.permissions import Membership

WORKSPACE = '0ceb3635-59a6-426f-bfa8-6d0203b8c98e'
ACTOR = '5684cafc-9de2-48b2-a23e-7a914a07e1df'
RUN = '507bb879-a6d0-4372-b31b-181f8b5c2103'
GRANT = 'd47b68ad-ef05-4d39-80fa-d6d305dbc23b'
NONCE = 'n' * 43


class Repository:
    def __init__(self):
        self.state, self.role, self.operator = {}, 'owner', False
        self.calls = []
        self.connection_factory = Mock(side_effect=AssertionError('No real database permitted.'))

    @contextmanager
    def transaction(self, token, workspace_id):
        self.calls.append((token, workspace_id))
        cur = Mock()
        cur.fetchone.return_value = (1,) if self.operator else None
        yield cur, (1, self.state, self.role), ACTOR

    def get(self, workspace_id, token):
        self.calls.append((token, workspace_id))
        return {'state': copy.deepcopy(self.state)}


class CaptureAccess(unittest.TestCase):
    def setUp(self):
        self.repository = Repository()
        self.runtime = model_runtime.ServerModelRuntime('offline-key', model='openai/gpt-4.1-mini')
        self.ideas = SimpleNamespace(repository=self.repository, _member=lambda row: Membership(row[2]),
                                     _state_reader=lambda *args: {}, resolve_writer=lambda *args: (self.runtime, self.runtime.model, None))
        self.service = Mock(allowlisted_workspace=WORKSPACE, public_key=b'p' * 32, key_id='offline-test', deployment_sha='a' * 40)
        self.access = capture_access.CaptureAccess(self.ideas, self.service)
        self.ideas.capture = self.access
        self.exemption = patch('postriff_phase2.developer_usage.ai_usage_exempt', return_value=False)
        self.exemption.start()
        self.addCleanup(self.exemption.stop)
        self.payload = {'auditCapture': {'grantId': GRANT, 'serverNonce': NONCE}, 'idempotencyKey': 'offline-once', 'research': False}

    def validate(self, payload=None, text='A piano lesson'):
        return capture_access.validate_payload(self.ideas, WORKSPACE, 'session', payload or self.payload, self.runtime, text)

    def test_normal_off_does_not_read_environment_keys_or_workspace(self):
        self.assertIsNone(capture_access.from_environment(None, {}))
        capture_access.validate_payload(None, 'unknown', None, {}, None, 'Schedule a model helper')
        self.assertEqual(self.repository.calls, [])
        with capture_access.scope(None, None):
            self.assertFalse(request_capture.active())

    def test_only_exact_ordinary_interactive_workspace_owner_can_access(self):
        self.assertEqual(self.access.actor(WORKSPACE, 'session'), ACTOR)
        for token, workspace in [('prt_secret', WORKSPACE), ('session', 'foreign')]:
            with self.subTest(token=token, workspace=workspace), self.assertRaises(AlphaError):
                self.access.actor(workspace, token)
        self.repository.role = 'admin'
        with self.assertRaises(AlphaError):
            self.access.actor(WORKSPACE, 'session')
        self.repository.role, self.repository.operator = 'owner', True
        with self.assertRaises(AlphaError):
            self.access.actor(WORKSPACE, 'session')
        self.repository.operator = False
        with patch('postriff_phase2.developer_usage.ai_usage_exempt', return_value=True), self.assertRaises(AlphaError):
            self.access.actor(WORKSPACE, 'session')

    def test_retention_grant_binds_only_authenticated_actor_and_explicit_version(self):
        self.access.create(WORKSPACE, 'session', {'model': self.runtime.model, 'confirmed': True,
                           'consentVersion': request_capture.CONSENT_VERSION, 'readerIds': ['foreign'], 'actorId': 'foreign'})
        fields = self.service.create_grant.call_args.kwargs
        self.assertEqual(fields['actor_id'], ACTOR)
        self.assertEqual(fields['reader_ids'], [ACTOR])
        self.assertEqual(fields['ttl_seconds'], 3600)
        self.assertEqual(fields['route'], model_runtime.DEFAULT_ENDPOINT)
        with self.assertRaises(AlphaError):
            self.access.create(WORKSPACE, 'session', {'confirmed': True, 'consentVersion': 'stale'})

    def test_supported_request_and_unsupported_side_calls(self):
        self.validate()
        for changed in ({'research': True}, {'attachments': [{'assetId': 'x'}]}, {'imageGeneration': True},
                        {'references': [{'kind': 'connector_item'}]}):
            with self.subTest(changed=changed), self.assertRaises(AlphaError):
                self.validate({**self.payload, **changed})
        with patch('postriff_phase2.request_model.wants_reading', return_value=True), self.assertRaises(AlphaError):
            self.validate()
        with patch('postriff_phase2.workflow_parse.names_automation', return_value=True), self.assertRaises(AlphaError):
            self.validate()

    def test_custom_endpoint_or_injected_transport_is_not_real_capture(self):
        for change in ('endpoint', 'transport'):
            with self.subTest(change=change):
                original = getattr(self.runtime, change)
                setattr(self.runtime, change, 'https://other.invalid' if change == 'endpoint' else Mock())
                with self.assertRaises(AlphaError):
                    self.validate()
                with self.assertRaises(AlphaError):
                    self.access.create(WORKSPACE, 'session', {'confirmed': True, 'consentVersion': request_capture.CONSENT_VERSION})
                setattr(self.runtime, change, original)

    def test_malformed_identifier_nonce_and_idempotency_fail_before_binding(self):
        for changed in ({'auditCapture': None}, {'auditCapture': {'grantId': 'x', 'serverNonce': NONCE}},
                        {'auditCapture': {'grantId': GRANT, 'serverNonce': 'short'}},
                        {'auditCapture': {'grantId': GRANT, 'serverNonce': '私' * 43}},
                        {'idempotencyKey': ' '}, {'idempotencyKey': 'x' * 101}, {'idempotencyKey': True}):
            with self.subTest(changed=changed), self.assertRaises(AlphaError) as error:
                self.validate({**self.payload, **changed})
            self.assertEqual(error.exception.status, 400)
        self.service.bind_grant.assert_not_called()
        for method in (self.access.read, self.access.list, self.access.revoke):
            with self.assertRaises(AlphaError):
                method(WORKSPACE, 'session', 'not-a-uuid', {'serverNonce': NONCE})

    def test_scope_binds_server_ids_and_is_reset_after_failure(self):
        self.payload['auditCapture']['actorId'] = 'foreign'
        self.payload['auditCapture']['runId'] = 'foreign'
        cur = object()
        bound = capture_access.bind(self.ideas, cur, WORKSPACE, ACTOR, RUN, 'offline-once', self.payload,
                                    self.runtime, {'reservationId': GRANT})
        fields = self.service.bind_grant.call_args.kwargs
        self.assertEqual((fields['workspace_id'], fields['actor_id'], fields['run_id']), (WORKSPACE, ACTOR, RUN))
        self.assertEqual(self.service.bind_grant.call_args.args, (cur,))
        with self.assertRaises(RuntimeError):
            with capture_access.scope(self.ideas, bound):
                self.assertTrue(request_capture.active())
                raise RuntimeError('offline exit')
        self.assertFalse(request_capture.active())

    def test_credits_reads_mounted_key_without_model_body(self):
        with patch.object(model_runtime, 'model_transport', return_value={'status': 200, 'body': {'balance': '8.60', 'total_used': '1.4'}}) as transport:
            self.runtime.transport = transport
            result = self.access.credits(WORKSPACE, 'session', self.runtime.model)
        self.assertEqual(result['balanceUsd'], '8.60')
        self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(transport.call_args.args, ('GET', 'https://ai-gateway.vercel.sh/v1/credits'))
        self.assertEqual(transport.call_args.kwargs['headers'], {'Authorization': 'Bearer offline-key'})
        self.assertNotIn('offline-key', json.dumps(result))

    def test_bad_credit_response_stays_unknown(self):
        for data in ({}, [], {'balance': '-1'}, {'balance': 'NaN'}, {'balance': 'Infinity'}):
            with self.subTest(data=data), patch.object(model_runtime, 'model_transport', return_value={'status': 200, 'body': data}) as transport:
                self.runtime.transport = transport
                with self.assertRaises(AlphaError) as error:
                    self.access.credits(WORKSPACE, 'session')
                self.assertEqual(error.exception.status, 503)

    def test_privacy_revocation_and_actual_learning_reset_delete_captures(self):
        before = {'sources': [{'id': 'voice', 'active': True, 'useGrants': [{'purpose': 'generation', 'route': 'cloud'}]}],
                  'learning': {'revision': 1, 'active': [{'id': 'r'}]}}
        mutations = [dict(before, sources=[]), dict(before, memoryEgress={'cloud': False}),
                     dict(before, learning={'revision': 2, 'active': [], 'resetAt': '2026-10-05T00:00:00Z'}),
                     dict(before, sources=[{'id': 'voice', 'active': True, 'useGrants': []}]),
                     dict(before, sources=[{**before['sources'][0], 'egressConsent': []}]),
                     dict(before, sources=[{**before['sources'][0], 'useApprovals': []}])]
        for after in mutations:
            self.service.revoke_workspace.reset_mock()
            self.access.privacy_changed('cursor', WORKSPACE, before, after, ACTOR)
            self.service.revoke_workspace.assert_called_once_with('cursor', workspace_id=WORKSPACE, actor_id=ACTOR)
        self.service.revoke_workspace.reset_mock()
        self.access.privacy_changed('cursor', WORKSPACE, before, copy.deepcopy(before), ACTOR)
        self.service.revoke_workspace.assert_not_called()

    def test_off_status_route_authenticates_and_private_response_is_no_store(self):
        app = HostedApplication()
        self.ideas.capture = None
        service = SimpleNamespace(ideas=self.ideas, repository=self.repository)
        captured = []
        result = app._ideas({}, lambda *args: captured.append(args), service, 'session', 'GET',
                            ['api', 'workspaces', WORKSPACE, 'ideas', 'capture', 'status'])
        self.assertEqual(json.loads(b''.join(result)), {'enabled': False})
        self.assertIn(('Cache-Control', 'no-store'), captured[0][1])
        self.assertEqual(self.repository.calls[-1], ('session', WORKSPACE))

    def test_private_post_route_shapes_pass_only_workspace_session_path_and_body(self):
        routes = [('grants', ['grants'], 'create', 201), ('receipts', ['receipts', RUN], 'read', 200),
                  ('attempts', ['grants', GRANT, 'attempts'], 'list', 200), ('revoke', ['grants', GRANT, 'revoke'], 'revoke', 200)]
        app = HostedApplication()
        capture = Mock()
        service = SimpleNamespace(ideas=SimpleNamespace(capture=capture))
        body = {'serverNonce': NONCE}
        for name, suffix, method, status in routes:
            with self.subTest(route=name):
                getattr(capture, method).return_value = {'offline': True}
                raw = json.dumps(body).encode()
                environ = {'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw)}
                headers = []
                result = app._ideas(environ, lambda *args: headers.append(args), service, 'session', 'POST',
                                    ['api', 'workspaces', WORKSPACE, 'ideas', 'capture', *suffix])
                expected = (WORKSPACE, 'session', body) if method == 'create' else (WORKSPACE, 'session', suffix[1], body)
                getattr(capture, method).assert_called_once_with(*expected)
                self.assertTrue(headers[0][0].startswith(str(status)))
                self.assertEqual(json.loads(b''.join(result)), {'offline': True})


if __name__ == '__main__':
    unittest.main()
