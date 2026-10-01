"""Transport -> verified identity -> exchange -> safe API/audit regression, no network."""
import base64
import io
import json
import time
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError
from rafii_control.hosted import create_app
from control.test_boundary import MemoryStore, USER


class HostedErrors(unittest.TestCase):
    def exchange(self, *, status=200, raw=None, failure=None, user=USER):
        store = MemoryStore()
        opener = MagicMock()
        if failure is not None:
            opener.open.side_effect = failure
        else:
            response = Mock(status=status)
            response.read.return_value = raw if raw is not None else json.dumps({'id':USER, 'email_confirmed_at':'2026-09-29T00:00:00Z'}).encode()
            opener.open.return_value.__enter__.return_value = response
        values = dict(RAFII_CONTROL_ENABLED='1', RAFII_CONTROL_ENVIRONMENT='local', RAFII_CONTROL_ORIGIN='http://localhost:4449', RAFII_CONTROL_SESSION_DSN='synthetic-session', RAFII_CONTROL_READER_DSN='synthetic-reader', RAFII_CONTROL_SUPABASE_URL='https://synthetic.supabase.co', RAFII_CONTROL_SUPABASE_PUBLISHABLE_KEY='synthetic-publishable-key-only')
        with patch('rafii_control.hosted.build_opener',return_value=opener), patch('rafii_control.hosted.PostgresStore',return_value=store):
            app = create_app(values)
        payload = dict(sub=user, session_id='synthetic-upstream-session-0001', aal='aal2', amr=[{'method':'totp','timestamp':time.time()}])
        token = 'synthetic.'+base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')+'.synthetic-signature'
        env = dict(PATH_INFO='/api/control/v2/session/exchange', REQUEST_METHOD='POST', CONTENT_LENGTH='2', CONTENT_TYPE='application/json', HTTP_HOST='localhost:4449', HTTP_ORIGIN='http://localhost:4449', HTTP_X_CONTROL_EXCHANGE='1', HTTP_AUTHORIZATION='Bearer '+token, **{'wsgi.input':io.BytesIO(b'{}')})
        result = {}
        body = json.loads(b''.join(app(env,lambda s,h:result.update(status=int(s[:3]),headers=dict(h)))))
        return result, body, store, opener

    def error(self, code):
        return HTTPError('https://synthetic.supabase.co/auth/v1/user', code, 'PRIVATE_PROVIDER_CANARY', {}, io.BytesIO(b'PRIVATE_PROVIDER_CANARY'))

    def assert_denied(self, result, code, status):
        response, body, store, opener = result
        self.assertEqual(response['status'],status)
        self.assertEqual(body['code'],code)
        self.assertNotIn('Set-Cookie',response['headers'])
        self.assertEqual(store.sessions,{})
        self.assertEqual(store.events[-1]['error_code'],code)
        self.assertEqual(store.events[-1]['request_id'],body['requestId'])
        self.assertEqual(store.events[-1]['result'],'denied')
        self.assertNotIn('PRIVATE_PROVIDER_CANARY',json.dumps(body)+json.dumps(store.events))
        opener.open.assert_called_once()

    def test_upstream_rate_limit_is_retryable_not_invalid_auth(self):
        self.assert_denied(self.exchange(failure=self.error(429)),'RATE_LIMITED',429)

    def test_upstream_server_errors_are_unavailable(self):
        for status in (500,502,503,504):
            with self.subTest(status=status):self.assert_denied(self.exchange(failure=self.error(status)),'SOURCE_UNAVAILABLE',503)

    def test_invalid_authentication_remains_unauthorized(self):
        for status in (401,403):
            with self.subTest(status=status):self.assert_denied(self.exchange(failure=self.error(status)),'AUTH_REQUIRED',401)

    def test_timeout_and_transport_failure_are_unavailable(self):
        for failure in (TimeoutError('PRIVATE_PROVIDER_CANARY'),URLError('PRIVATE_PROVIDER_CANARY')):
            with self.subTest(kind=type(failure).__name__):self.assert_denied(self.exchange(failure=failure),'SOURCE_UNAVAILABLE',503)

    def test_malformed_and_oversized_success_responses_are_unavailable(self):
        for raw in (b'{',b'[]',b'null',b'{}',b'{"id":42}',b'PRIVATE_PROVIDER_CANARY'*4000,b'{"id":"wrong","email_confirmed_at":"yes"}'):
            with self.subTest(raw_kind=len(raw)):self.assert_denied(self.exchange(raw=raw),'SOURCE_UNAVAILABLE',503)

    def test_redirect_and_unexpected_status_fail_closed(self):
        for status in (302,400,404):
            with self.subTest(status=status):self.assert_denied(self.exchange(failure=self.error(status)),'SOURCE_UNAVAILABLE',503)

    def test_valid_verified_identity_still_requires_founder_and_mfa(self):
        response, body, store, _ = self.exchange()
        self.assertEqual(response['status'],200)
        self.assertEqual(body['data']['assurance'],'aal2')
        self.assertEqual(len(store.sessions),1)

    def test_editable_admin_metadata_never_enrolls_an_operator(self):
        user='10000000-0000-4000-8000-000000000099'
        raw=json.dumps({'id':user,'email_confirmed_at':'2026-09-29T00:00:00Z','user_metadata':{'isAdmin':True}}).encode()
        self.assert_denied(self.exchange(raw=raw,user=user),'FOUNDER_REQUIRED',403)
