import copy
import io
import json
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from rafii_control.auth import Boundary, ControlError, Config, READ_BUDGET, VerifiedIdentity, fresh_mfa
from rafii_control.http import ControlApplication

USER = '10000000-0000-4000-8000-000000000001'
NOW = 1790000000.0
CAPS = ['control.read', 'metrics.query', 'customers.read', 'workspaces.read', 'engineering.read', 'audit.read', 'copilot.use']


class MemoryStore:
    """Test-only persistence. Production uses restricted PostgreSQL roles."""
    def __init__(self):
        self.operator_row = dict(user_id=USER, environment='local', role='founder', status='active', auth_epoch=1, capabilities=CAPS)
        self.sessions, self.events = {}, []

    def operator(self, user, environment):
        return copy.deepcopy(self.operator_row) if user == USER and environment == 'local' else None

    def create_session(self, row):
        self.sessions[row['token_hash']] = row

    def session(self, token_hash):
        return copy.deepcopy(self.sessions.get(token_hash))

    def touch(self, token_hash, now):
        self.sessions[token_hash]['last_seen_at'] = now

    def revoke(self, token_hash, now):
        self.sessions[token_hash]['revoked_at'] = now

    def identity_active(self, user, session):
        return True

    def audit(self, **event):
        self.events.append(event)

    def budget(self, purpose, actor, limit):
        pass


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.time = NOW
        self.identity = VerifiedIdentity(USER, 'aal2', 's' * 32, NOW)
        self.boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), self.store,
                                 lambda token: self.identity, clock=lambda: self.time)

    def exchange(self):
        return self.boundary.exchange('verified-token', 'http://localhost:4449')

    def test_opaque_session_never_stores_raw_credential(self):
        token, session = self.exchange()
        self.assertNotIn(token, json.dumps(self.store.sessions))
        self.assertNotIn('verified-token', json.dumps(self.store.sessions))
        self.assertEqual(self.boundary.authorize(token, 'control.read')['operator']['user_id'], USER)
        self.assertTrue(session['csrfToken'])

    def test_customer_or_editable_metadata_cannot_become_operator(self):
        self.identity = VerifiedIdentity('10000000-0000-4000-8000-000000000099', 'aal2', 's' * 32, NOW)
        with self.assertRaisesRegex(ControlError, 'FOUNDER_REQUIRED'):
            self.exchange()

    def test_aal1_and_old_mfa_refreshed_jwt_fail(self):
        self.identity = VerifiedIdentity(USER, 'aal1', 's' * 32, NOW)
        with self.assertRaisesRegex(ControlError, 'STEP_UP_REQUIRED'): self.exchange()
        self.identity = VerifiedIdentity(USER, 'aal2', 's' * 32, NOW - 301)
        with self.assertRaisesRegex(ControlError, 'STEP_UP_REQUIRED'): self.exchange()
        self.assertEqual(fresh_mfa({'iat': NOW, 'amr': [{'method': 'password', 'timestamp': NOW}]}), 0)
        self.assertEqual(fresh_mfa({'amr': [{'method': 'totp', 'timestamp': NOW - 301}]}), NOW - 301)

    def test_revocation_and_epoch_change_take_effect_next_request(self):
        token, _ = self.exchange()
        for changes in [dict(status='revoked'), dict(auth_epoch=2), dict(capabilities=[])]:
            self.store.operator_row.update(changes)
            with self.assertRaises(ControlError): self.boundary.authorize(token, 'control.read')
            self.store.operator_row.update(status='active', auth_epoch=1, capabilities=CAPS)
        self.boundary.logout(token)
        with self.assertRaises(ControlError): self.boundary.authorize(token, 'control.read')

    def test_idle_and_absolute_expiry_are_independent(self):
        token, _ = self.exchange()
        self.time = NOW + 1800
        with self.assertRaises(ControlError): self.boundary.authorize(token, 'control.read')
        self.time = NOW
        token, _ = self.exchange()
        for elapsed in range(1700, 28800, 1700):
            self.time = NOW + elapsed
            self.boundary.authorize(token, 'control.read')
        self.time = NOW + 28800
        with self.assertRaises(ControlError): self.boundary.authorize(token, 'control.read')

    def test_cross_origin_csrf_and_unknown_capability_fail_closed(self):
        token, session = self.exchange()
        for origin, csrf in [('http://sibling.localhost:4449', session['csrfToken']), ('http://localhost:4449', 'wrong')]:
            with self.assertRaises(ControlError): self.boundary.authorize(token, 'metrics.query', origin=origin, csrf=csrf, unsafe=True)
        with self.assertRaises(ControlError): self.boundary.authorize(token, 'refund.execute')

    def test_disabled_flag_and_preview_production_fail_closed(self):
        self.assertFalse(Config.from_environment({}).enabled)
        self.assertFalse(Config.from_environment({'RAFII_CONTROL_ENABLED': '0'}).enabled)
        with self.assertRaises(ValueError): Config.from_environment({'RAFII_CONTROL_ENABLED': 'wat'})
        with self.assertRaises(ValueError): Config.from_environment({'RAFII_CONTROL_ENABLED': '1', 'RAFII_CONTROL_ENVIRONMENT': 'production', 'VERCEL_ENV': 'preview', 'RAFII_CONTROL_ORIGIN': 'https://ops.example'})
        self.boundary.config = Config(False, 'local', 'http://localhost:4449')
        with self.assertRaises(ControlError): self.exchange()

    def test_denials_and_metadata_reads_have_content_free_audit(self):
        token, _ = self.exchange()
        self.boundary.authorize(token, 'customers.read')
        with self.assertRaises(ControlError): self.boundary.authorize(token, 'customer.private.read')
        self.assertEqual(self.store.events[-1]['result'], 'denied')
        self.assertNotIn(token, json.dumps(self.store.events))

    def test_preview_database_identity_and_distinct_logins_are_bound_to_staging(self):
        from rafii_control.hosted import admit_databases
        config=Config(True,'staging','https://control-preview.example')
        values=dict(VERCEL_ENV='preview',RAFII_CONTROL_STAGING_PROJECT_REF='stagefixture',RAFII_CONTROL_PRODUCTION_PROJECT_REF='prodfixture',RAFII_CONTROL_SUPABASE_URL='https://stagefixture.supabase.co')
        session='host=db.stagefixture.supabase.co dbname=postgres user=control_session_login sslmode=verify-full'
        reader='host=db.stagefixture.supabase.co dbname=postgres user=control_reader_login sslmode=verify-full'
        admit_databases(session,reader,values,config)
        for a,b in [(session.replace('stagefixture','prodfixture'),reader), (session,session+' connect_timeout=5'), (session+' hostaddr=127.0.0.1',reader), (session+' service=redirect',reader), (session+' options=-csearch_path=public',reader), (session.replace('db.stagefixture.supabase.co','arbitrary.test'),reader)]:
            with self.subTest(dsn_case='redacted'),self.assertRaises(ValueError):admit_databases(a,b,values,config)
        admit_databases('host=aws-0-test.pooler.supabase.com dbname=postgres user=control_session_login.stagefixture sslmode=verify-full','host=aws-0-test.pooler.supabase.com dbname=postgres user=control_reader_login.stagefixture sslmode=verify-full',values,config)
        for suffix in (' sslmode=require',' port=6543'):
            with self.assertRaises(ValueError): admit_databases(session+suffix,reader,values,config)


class HttpTests(BoundaryTests):
    def request(self, app, path='/api/control/v2/session', method='GET', body=None, cookie='', origin='http://localhost:4449', headers=None):
        raw = json.dumps(body).encode() if body is not None else b''
        env = dict(PATH_INFO=path, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json', HTTP_HOST='localhost:4449', HTTP_ORIGIN=origin, HTTP_COOKIE=cookie, **{'wsgi.input': io.BytesIO(raw)})
        env.update(headers or {})
        result = {}
        data = b''.join(app(env, lambda status, hs: result.update(status=int(status[:3]), headers=dict(hs))))
        return result, json.loads(data)

    def test_bearer_alone_never_authorizes_founder_api(self):
        result, body = self.request(ControlApplication(self.boundary), headers={'HTTP_AUTHORIZATION': 'Bearer user-token'})
        self.assertEqual(result['status'], 401)
        self.assertEqual(body['code'], 'AUTH_REQUIRED')
        self.assertEqual(result['headers']['Cache-Control'], 'private, no-store')

    def test_exchange_cookie_flags_and_logout_csrf(self):
        app = ControlApplication(self.boundary)
        result, body = self.request(app, '/api/control/v2/session/exchange', 'POST', {}, headers={'HTTP_AUTHORIZATION': 'Bearer verified-token', 'HTTP_X_CONTROL_EXCHANGE': '1'})
        self.assertEqual(result['status'], 200)

        cookie = result['headers']['Set-Cookie']
        for part in ['__Host-rafii-control=', 'Secure', 'HttpOnly', 'Path=/', 'SameSite=Strict']: self.assertIn(part, cookie)
        self.assertNotIn('Domain=', cookie)
        result, _ = self.request(app, '/api/control/v2/session/logout', 'POST', {}, cookie=cookie.split(';')[0])
        self.assertEqual(result['status'], 403)
        result, _ = self.request(app, '/api/control/v2/session/logout', 'POST', {}, cookie=cookie.split(';')[0], headers={'HTTP_X_CSRF_TOKEN': body['data']['csrfToken']})
        self.assertEqual(result['status'], 200)

    def test_http_request_id_binds_content_free_audit(self):
        app=ControlApplication(self.boundary)
        result,body=self.request(app,'/api/control/v2/session/exchange','POST',{},headers={'HTTP_AUTHORIZATION':'Bearer verified-token','HTTP_X_CONTROL_EXCHANGE':'1'})
        self.assertEqual(result['status'],200)
        self.assertEqual(self.store.events[-1]['request_id'],body['requestId'])

    def test_error_contract_and_denied_dispatch_audit(self):
        pack = Path(__file__).resolve().parents[2] / 'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2'
        schema = Draft202012Validator(json.loads((pack/'contracts/error.schema.json').read_text()), format_checker=FormatChecker())
        token, session = self.exchange()
        for code, status in [('BUDGET_EXCEEDED',400), ('RATE_LIMITED',429), ('IDEMPOTENCY_CONFLICT',409), ('STALE_PREVIEW',409)]:
            class Queries:
                def dispatch(self, *args): raise ControlError(code,status)
            result, body = self.request(ControlApplication(self.boundary, Queries()), '/api/control/v2/metrics/query', 'POST', {}, cookie='__Host-rafii-control='+token, headers={'HTTP_X_CSRF_TOKEN':session['csrfToken']})
            self.assertEqual(result['status'],status)
            schema.validate(body)
            self.assertEqual(self.store.events[-1]['result'],'denied')
            self.assertEqual(self.store.events[-1]['request_id'],body['requestId'])

    def test_attempted_prohibited_route_is_audited_without_raw_path(self):
        token, _ = self.exchange()
        result, body = self.request(ControlApplication(self.boundary), '/api/control/v2/sql/PRIVATE_CANARY', 'POST', {}, cookie='__Host-rafii-control='+token)
        self.assertEqual(result['status'],404)
        self.assertEqual(self.store.events[-1]['action'],'prohibited')
        self.assertEqual(self.store.events[-1]['result'],'denied')
        self.assertEqual(self.store.events[-1]['request_id'],body['requestId'])
        self.assertNotIn('PRIVATE_CANARY',json.dumps(self.store.events))

    def test_wrong_host_and_effect_routes_never_execute(self):
        app = ControlApplication(self.boundary)
        result, _ = self.request(app, headers={'HTTP_HOST': 'customer.example'})
        self.assertEqual(result['status'], 404)
        token, _ = self.exchange()
        for path in ['/actions/refund', '/sql', '/engineering/checks', '/accounts/delete']:
            result, _ = self.request(app, '/api/control/v2' + path, 'POST', {}, cookie='__Host-rafii-control=' + token)
            self.assertIn(result['status'], [403, 404])

    def test_logout_budget_cannot_be_used_for_other_capabilities_or_reads(self):
        token, session=self.exchange()
        for capability,unsafe in [('customers.read',True),('control.read',False)]:
            with self.assertRaisesRegex(ControlError,'SCOPE_DENIED'):
                self.boundary.authorize(token,capability,unsafe=unsafe,origin='http://localhost:4449',csrf=session['csrfToken'],ending_session=True)

    def test_run_reads_have_read_budget_and_keep_copilot_permission(self):
        token, session=self.exchange()
        budgets=[]
        self.store.budget=lambda purpose,actor,limit:budgets.append((purpose,limit))
        self.boundary.authorize(token,'copilot.use')
        self.boundary.authorize(token,'copilot.use',origin='http://localhost:4449',csrf=session['csrfToken'],unsafe=True)
        self.assertEqual(budgets,[('copilot.read',READ_BUDGET),('copilot.use',5)])
        self.store.operator_row['capabilities']=['control.read']
        with self.assertRaisesRegex(ControlError,'SCOPE_DENIED'):self.boundary.authorize(token,'copilot.use')
