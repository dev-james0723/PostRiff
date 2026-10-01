"""Embedded mount (CONTRACTS §1/§3): Control inside the consumer API keeps its own boundary and never reads consumer credentials."""
import base64
import io
import json
import os
import sys
import time
import types
import unittest
from unittest.mock import MagicMock, Mock, patch
from rafii_control.auth import Boundary, CAPABILITIES, Config, ControlError, VerifiedIdentity
from rafii_control.hosted import PROHIBITED, create_app, embedded_app, founder_tick
from rafii_control.http import ControlApplication
from control.test_boundary import MemoryStore, NOW, USER

PREVIEW = dict(RAFII_CONTROL_MOUNT='embedded', RAFII_CONTROL_ENABLED='1', RAFII_CONTROL_ENVIRONMENT='staging', VERCEL_ENV='preview',
               VERCEL_URL='postriff-git-founder-abc123.vercel.app', VERCEL_BRANCH_URL='postriff-git-founder.vercel.app',
               RAFII_CONTROL_STAGING_PROJECT_REF='stagefixture', RAFII_CONTROL_PRODUCTION_PROJECT_REF='prodfixture',
               RAFII_CONTROL_SUPABASE_URL='https://stagefixture.supabase.co')
LOCAL = dict(RAFII_CONTROL_MOUNT='embedded', RAFII_CONTROL_ENABLED='1', RAFII_CONTROL_ENVIRONMENT='local', RAFII_CONTROL_ORIGINS='http://localhost:3100',
             RAFII_CONTROL_SESSION_DSN='synthetic-session', RAFII_CONTROL_READER_DSN='synthetic-reader',
             RAFII_CONTROL_SUPABASE_URL='https://synthetic.supabase.co', RAFII_CONTROL_SUPABASE_PUBLISHABLE_KEY='synthetic-publishable-key-only')
# Consumer/privileged values that legitimately share the consumer process. Canaries must never appear in any output.
CONSUMER = dict(POSTRIFF_DATABASE_URL='postgres://PRIVATE_CONSUMER_CANARY', SUPABASE_SERVICE_ROLE_KEY='PRIVATE_SERVICE_ROLE_CANARY',
                OPENAI_API_KEY='sk-PRIVATE_OPENAI_CANARY', STRIPE_SECRET_KEY='sk_live_PRIVATE_STRIPE_CANARY')


class Recording(dict):
    """Records every key the configuration reads so a test can prove prohibited names are never touched."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.read.add(key)
        return super().__contains__(key)


def fake_module(name, **members):
    module = types.ModuleType('rafii_control.' + name)
    for key, value in members.items(): setattr(module, key, value)
    return module


class FakeFounderStore:
    """Stands in for founder_cron.PostgresFounderStore(store, environment)."""
    def __init__(self, store, environment):
        self.store, self.environment = store, environment


def upstream_token():
    payload = dict(sub=USER, session_id='synthetic-upstream-session-0001', aal='aal2', amr=[{'method': 'totp', 'timestamp': time.time()}])
    return 'synthetic.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.synthetic-signature'


class EmbeddedConfigTests(unittest.TestCase):
    def test_preview_accepts_its_vercel_urls_and_listed_origins_as_staging(self):
        config = Config.from_environment({**PREVIEW, **CONSUMER})
        self.assertEqual((config.mount, config.enabled, config.environment), ('embedded', True, 'staging'))
        self.assertEqual(config.allowed_origins, ('https://postriff-git-founder-abc123.vercel.app', 'https://postriff-git-founder.vercel.app'))
        self.assertEqual(config.origin, config.allowed_origins[0])
        listed = Config.from_environment({**PREVIEW, 'RAFII_CONTROL_ORIGINS': 'https://founder-preview.example, https://postriff-git-founder.vercel.app'})
        self.assertEqual(listed.allowed_origins, ('https://founder-preview.example', 'https://postriff-git-founder.vercel.app', 'https://postriff-git-founder-abc123.vercel.app'))

    def test_local_production_harness_and_wrong_identity_cannot_run_on_a_preview(self):
        for changes in [dict(RAFII_CONTROL_ENVIRONMENT='local'), dict(RAFII_CONTROL_ENVIRONMENT='local', RAFII_CONTROL_ORIGINS='http://localhost:3100'),
                        dict(RAFII_CONTROL_ENVIRONMENT='production'), dict(RAFII_CONTROL_HARNESS='1'),
                        dict(RAFII_CONTROL_STAGING_PROJECT_REF='prodfixture'), dict(RAFII_CONTROL_SUPABASE_URL='https://prodfixture.supabase.co'), dict(RAFII_CONTROL_ENVIRONMENT='sandbox')]:
            with self.subTest(changes=sorted(changes)), self.assertRaises(ValueError): Config.from_environment({**PREVIEW, **changes})

    def test_production_requires_explicit_https_origins_and_never_infers_vercel_url(self):
        production = dict(RAFII_CONTROL_MOUNT='embedded', RAFII_CONTROL_ENABLED='1', RAFII_CONTROL_ENVIRONMENT='production', VERCEL_ENV='production',
                          VERCEL_URL='postriff-abc.vercel.app', VERCEL_BRANCH_URL='postriff.vercel.app')
        with self.assertRaisesRegex(ValueError, 'Explicit control origins required'): Config.from_environment(production)
        config = Config.from_environment({**production, 'RAFII_CONTROL_ORIGINS': 'https://app.postriff.example'})
        self.assertEqual(config.allowed_origins, ('https://app.postriff.example',))
        for origins in ('http://app.postriff.example', 'https://app.postriff.example/founder', 'https://app.postriff.example,https://other.example/?x=1', 'https://user@app.postriff.example'):
            with self.subTest(origins=origins), self.assertRaises(ValueError): Config.from_environment({**production, 'RAFII_CONTROL_ORIGINS': origins})
        with self.assertRaisesRegex(ValueError, 'Invalid control mount'): Config.from_environment({'RAFII_CONTROL_MOUNT': 'sidecar'})
        with self.assertRaisesRegex(ValueError, 'Explicit control origins required'): Config.from_environment({'RAFII_CONTROL_MOUNT': 'embedded'})

    def test_separate_mount_is_unchanged_when_mount_is_unset(self):
        config = Config.from_environment({})
        self.assertEqual((config.enabled, config.environment, config.origin, config.mount, config.allowed_origins), (False, 'local', 'http://localhost:4449', 'separate', ('http://localhost:4449',)))
        self.assertEqual(Config(True, 'local', 'http://localhost:4449').allowed_origins, ('http://localhost:4449',))
        separate = {**PREVIEW, 'RAFII_CONTROL_MOUNT': 'separate', 'RAFII_CONTROL_ORIGIN': 'https://control-preview.example'}
        self.assertEqual(Config.from_environment(separate).allowed_origins, ('https://control-preview.example',))
        with self.assertRaisesRegex(ValueError, 'Consumer/privileged credentials forbidden'): Config.from_environment({**separate, 'POSTRIFF_DATABASE_URL': 'x'})


class MultiOriginBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.store.operator_row['capabilities'] = sorted(CAPABILITIES)
        self.config = Config(True, 'local', 'http://localhost:3100', 'embedded', ('http://localhost:3100', 'http://localhost:4331'))
        self.boundary = Boundary(self.config, self.store, lambda token: VerifiedIdentity(USER, 'aal2', 's' * 32, NOW), clock=lambda: NOW)

    def test_every_allowed_origin_may_exchange_and_mutate_but_no_other(self):
        for origin in self.config.allowed_origins:
            token, session = self.boundary.exchange('verified-token', origin)
            self.boundary.authorize(token, 'metrics.query', origin=origin, csrf=session['csrfToken'], unsafe=True)
        with self.assertRaisesRegex(ControlError, 'SCOPE_DENIED'): self.boundary.exchange('verified-token', 'http://localhost:4449')
        token, session = self.boundary.exchange('verified-token', 'http://localhost:3100')
        with self.assertRaisesRegex(ControlError, 'SCOPE_DENIED'): self.boundary.authorize(token, 'metrics.query', origin='http://localhost:4449', csrf=session['csrfToken'], unsafe=True)

    def test_founder_purposes_select_budgets_while_audit_keeps_the_capability(self):
        token, session = self.boundary.exchange('verified-token', 'http://localhost:3100')
        budgets = []
        self.store.budget = lambda purpose, actor, limit: budgets.append((purpose, limit))
        unsafe = dict(origin='http://localhost:3100', csrf=session['csrfToken'], unsafe=True)
        self.boundary.authorize(token, 'copilot.use', purpose='founder.agent.turn', **unsafe)
        self.assertEqual(self.store.events[-1]['action'], 'copilot.use')
        self.boundary.authorize(token, 'control.settings', purpose='founder.call.request', **unsafe)
        self.boundary.authorize(token, 'copilot.use', **unsafe)
        self.boundary.authorize(token, 'copilot.use')
        self.boundary.authorize(token, 'incidents.ack', **unsafe)
        self.assertEqual(budgets, [('founder.agent.turn', 20), ('founder.call.request', 5), ('copilot.use', 5), ('copilot.read', 120), ('incidents.ack', 120)])
        self.store.operator_row['capabilities'] = ['control.read']
        for capability in ('incidents.ack', 'followups.write', 'control.settings'):
            with self.assertRaisesRegex(ControlError, 'SCOPE_DENIED'): self.boundary.authorize(token, capability, **unsafe)


class EmbeddedBuildTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        for item in (patch('rafii_control.hosted.build_opener', return_value=MagicMock()), patch('rafii_control.hosted.PostgresStore', return_value=self.store)):
            item.start()
            self.addCleanup(item.stop)

    def test_consumer_credentials_do_not_abort_the_embedded_build_and_are_never_read(self):
        values = Recording({**LOCAL, **CONSUMER, 'RAFII_FOUNDER_CALLS_ENABLED': '0', 'RAFII_FOUNDER_OPS_WORKSPACE_ID': 'ops-workspace'})
        app = create_app(values)
        self.assertTrue(app.boundary.config.enabled)
        self.assertEqual(app.boundary.config.allowed_origins, ('http://localhost:3100',))
        self.assertEqual(app.flags, {'RAFII_FOUNDER_CALLS_ENABLED': '0', 'RAFII_FOUNDER_OPS_WORKSPACE_ID': 'ops-workspace'})
        self.assertEqual(set(PROHIBITED) & values.read, set(), 'embedded Control must never read consumer credentials')
        self.assertEqual(set(PROHIBITED), set(CONSUMER))
        with self.assertRaisesRegex(ValueError, 'Consumer/privileged credentials forbidden'):
            create_app({**LOCAL, **CONSUMER, 'RAFII_CONTROL_MOUNT': 'separate', 'RAFII_CONTROL_ORIGIN': 'http://localhost:4449'})

    def test_unmounted_or_misconfigured_control_fails_closed_without_raising(self):
        def call(app, path='/api/control/v2/session'):
            result = {}
            body = json.loads(b''.join(app({'PATH_INFO': path, 'REQUEST_METHOD': 'GET', 'HTTP_HOST': 'localhost:3100'}, lambda status, headers: result.update(status=int(status[:3]), headers=dict(headers)))))
            return result, body
        result, body = call(embedded_app({**LOCAL, 'RAFII_CONTROL_MOUNT': 'separate'}))
        self.assertEqual((result['status'], body['code']), (404, 'SOURCE_UNAVAILABLE'))
        self.assertEqual(result['headers']['Cache-Control'], 'private, no-store')
        with self.assertLogs('rafii_control.mount', level='ERROR') as logs:
            result, body = call(embedded_app({**LOCAL, **CONSUMER, 'RAFII_CONTROL_ORIGINS': 'https://PRIVATE_ORIGIN_CANARY.example/with-path'}))
        self.assertEqual((result['status'], body['code']), (503, 'SOURCE_UNAVAILABLE'))
        self.assertIn('control_mount_unavailable', logs.output[0])
        self.assertNotIn('CANARY', json.dumps(logs.output) + json.dumps(body))
        with self.assertLogs('rafii_control.mount', level='ERROR'):
            result, body = call(embedded_app({**LOCAL, 'RAFII_CONTROL_READER_DSN': 'synthetic-session'}))
        self.assertEqual((result['status'], body['code']), (503, 'SOURCE_UNAVAILABLE'))


class FounderTickTests(unittest.TestCase):
    def test_disabled_missing_failing_or_unserialisable_founder_cron_never_breaks_the_tick(self):
        service = object()
        self.assertEqual(founder_tick(service, {}), {'status': 'disabled'})
        self.assertEqual(founder_tick(service, {'RAFII_CONTROL_ENABLED': '1'}), {'status': 'disabled'})
        enabled = {'RAFII_CONTROL_ENABLED': '1', 'RAFII_CONTROL_MOUNT': 'embedded'}
        with patch.dict(sys.modules, {'rafii_control.founder_cron': None}):
            self.assertEqual(founder_tick(service, enabled), {'status': 'unavailable'})
        def boom(service, values): raise RuntimeError('PRIVATE_CRON_CANARY')
        with patch.dict(sys.modules, {'rafii_control.founder_cron': fake_module('founder_cron', tick=boom)}):
            self.assertEqual(founder_tick(service, enabled), {'status': 'unavailable'})
        with patch.dict(sys.modules, {'rafii_control.founder_cron': fake_module('founder_cron', tick=lambda s, v: {'status': 'ok', 'object': object()})}):
            self.assertEqual(founder_tick(service, enabled), {'status': 'unavailable'})
        seen = []
        with patch.dict(sys.modules, {'rafii_control.founder_cron': fake_module('founder_cron', tick=lambda s, v: seen.append((s, v)) or {'status': 'ok', 'incidents': 0})}):
            self.assertEqual(founder_tick(service, enabled), {'status': 'ok', 'incidents': 0})
        self.assertEqual(seen, [(service, enabled)])
        self.assertEqual(founder_tick(service, {**enabled, 'RAFII_CONTROL_ENABLED': 'wat'}), {'status': 'unavailable'})


class HostedDelegationTests(unittest.TestCase):
    """The consumer WSGI app hands /api/control/v2/* to Control before its own bearer, guard, health and runtime logic."""
    def setUp(self):
        self.store = MemoryStore()
        self.store.operator_row['capabilities'] = sorted(CAPABILITIES)
        opener = MagicMock()
        response = Mock(status=200)
        response.read.return_value = json.dumps({'id': USER, 'email_confirmed_at': '2026-09-29T00:00:00Z'}).encode()
        opener.open.return_value.__enter__.return_value = response
        runtime = patch('postriff_phase2.hosted_app.runtime_from_environment', side_effect=AssertionError('consumer runtime must not be built for control paths'))
        for item in (patch('rafii_control.hosted.build_opener', return_value=opener), patch('rafii_control.hosted.PostgresStore', return_value=self.store), patch.dict(os.environ, {**LOCAL, **CONSUMER})):
            item.start()
            self.addCleanup(item.stop)
        self.runtime_from_environment = runtime.start()
        self.addCleanup(runtime.stop)
        from postriff_phase2.hosted_app import HostedApplication
        self.app = HostedApplication()

    def request(self, path, method='GET', body=None, headers=None, host='localhost:3100'):
        raw = json.dumps(body).encode() if body is not None else b''
        env = dict(PATH_INFO=path, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json', HTTP_HOST=host, **{'wsgi.input': io.BytesIO(raw), 'wsgi.url_scheme': 'http'})
        env.update(headers or {})
        result = {}
        data = b''.join(self.app(env, lambda status, hs: result.update(status=int(status[:3]), headers=dict(hs))))
        return result, json.loads(data)

    def exchange(self):
        result, body = self.request('/api/control/v2/session/exchange', 'POST', {}, {'HTTP_ORIGIN': 'http://localhost:3100', 'HTTP_X_CONTROL_EXCHANGE': '1', 'HTTP_AUTHORIZATION': 'Bearer ' + upstream_token()})
        self.assertEqual((result['status'], body['data']['assurance']), (200, 'aal2'))
        return result['headers']['Set-Cookie'].split(';')[0], body['data']['csrfToken']

    def test_consumer_bearer_cannot_call_control_and_the_application_guard_is_not_applied(self):
        for bearer in ('Bearer prt_' + 'c' * 40, 'Bearer ' + 't' * 32):
            result, body = self.request('/api/control/v2/session', headers={'HTTP_AUTHORIZATION': bearer})
            self.assertEqual((result['status'], body['code']), (401, 'AUTH_REQUIRED'))
            result, body = self.request('/api/control/v2/metrics/query', 'POST', {}, {'HTTP_AUTHORIZATION': bearer, 'HTTP_X_POSTRIFF_REQUEST': 'founder-alpha', 'HTTP_ORIGIN': 'http://localhost:3100'})
            self.assertEqual((result['status'], body['code']), (401, 'AUTH_REQUIRED'))
        self.runtime_from_environment.assert_not_called()
        cookie, csrf = self.exchange()   # no X-Postriff-Request header, yet the exchange succeeds and sets the control cookie
        self.assertTrue(cookie.startswith('__Host-rafii-control='))
        result, body = self.request('/api/control/v2/session', headers={'HTTP_COOKIE': cookie})
        self.assertEqual((result['status'], body['data']['capabilities']), (200, sorted(CAPABILITIES)))
        self.assertEqual(result['headers']['Cache-Control'], 'private, no-store')
        self.assertTrue(result['headers']['X-Request-ID'])
        result, _ = self.request('/api/control/v2/session/logout', 'POST', {}, {'HTTP_COOKIE': cookie, 'HTTP_ORIGIN': 'http://localhost:3100'})
        self.assertEqual(result['status'], 403)
        result, body = self.request('/api/health')
        self.assertEqual((result['status'], body['status'], body['configured']), (200, 'ok', False))
        result, _ = self.request('/api/auth/verify', 'POST', {'plan': 'assist'}, {'HTTP_AUTHORIZATION': 'Bearer ' + 't' * 32, 'HTTP_ORIGIN': 'http://localhost:3100'})
        self.assertEqual(result['status'], 403)   # the consumer guard still protects consumer mutations
        self.assertIsInstance(self.app.control_app, ControlApplication)   # built once, cached on the hosted application
        self.runtime_from_environment.assert_not_called()
        self.assertNotIn('CANARY', json.dumps(self.store.events))

    def test_forwarded_host_must_match_an_allowed_origin(self):
        cookie, _ = self.exchange()
        result, _ = self.request('/api/control/v2/session', headers={'HTTP_COOKIE': cookie, 'HTTP_X_FORWARDED_HOST': 'localhost:3100, 10.0.0.1'}, host='127.0.0.1:4331')
        self.assertEqual(result['status'], 200)
        for headers, host in [({'HTTP_X_FORWARDED_HOST': 'customer.example'}, 'localhost:3100'), ({}, 'customer.example'), ({}, 'localhost:4449')]:
            result, body = self.request('/api/control/v2/session', headers={'HTTP_COOKIE': cookie, **headers}, host=host)
            self.assertEqual((result['status'], body['code']), (404, 'SCOPE_DENIED'))
        separate = ControlApplication(Boundary(Config(True, 'local', 'http://localhost:4449'), self.store, None))
        env = {'PATH_INFO': '/api/control/v2/session', 'REQUEST_METHOD': 'GET', 'HTTP_HOST': 'customer.example', 'HTTP_X_FORWARDED_HOST': 'localhost:4449'}
        status = []
        separate(env, lambda s, h: status.append(s))
        self.assertEqual(status, ['404 Not Found'])   # the separate mount ignores forwarded hosts, as before


class StubQueries:
    """Only the legacy dispatch surface plus the Demo dataset; founder routes must not reach the legacy dispatcher."""
    def __init__(self, store):
        self.store, self.calls = store, []
        self.clock = lambda: NOW

    def dispatch(self, path, body, principal, request_id):
        self.calls.append(path)
        return {'legacy': path}

    def demo_data(self, principal):
        return {'asOf': '2026-10-01T00:00:00Z', 'receipt': {'id': 'demo-receipt-1'}, 'incidents': [{'id': 'demo_cost_anomaly', 'state': 'open'}, {'id': 'demo_old', 'state': 'resolved'}]}


class FounderRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.store.operator_row['capabilities'] = sorted(CAPABILITIES)
        self.time = NOW
        self.boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), self.store, lambda token: VerifiedIdentity(USER, 'aal2', 's' * 32, NOW), clock=lambda: self.time)
        self.queries = StubQueries(self.store)
        self.app = ControlApplication(self.boundary, self.queries, flags={'RAFII_FOUNDER_CALLS_ENABLED': '0'})
        self.token, session = self.boundary.exchange('verified-token', 'http://localhost:4449')
        self.csrf = session['csrfToken']
        self.seen = []
        self.cron = patch.dict(sys.modules, {'rafii_control.founder_cron': fake_module('founder_cron', PostgresFounderStore=FakeFounderStore)})
        self.cron.start()
        self.addCleanup(self.cron.stop)

    def record(self, name):
        """A fake slice function: records (name, positional args, keyword args) and answers a receipted envelope body."""
        return lambda *args, **kwargs: self.seen.append((name, args, kwargs)) or {'rows': [name], '_dataState': 'partial', '_receiptIds': ['r-' + name]}

    def request(self, path, method='GET', body=None, headers=None, content_type='application/json'):
        raw = json.dumps(body).encode() if body is not None else b''
        path, _, query = path.partition('?')
        env = dict(PATH_INFO='/api/control/v2' + path, QUERY_STRING=query, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), HTTP_HOST='localhost:4449', HTTP_ORIGIN='http://localhost:4449',
                   HTTP_COOKIE='__Host-rafii-control=' + self.token, HTTP_X_CSRF_TOKEN=self.csrf, **{'wsgi.input': io.BytesIO(raw)})
        if content_type: env['CONTENT_TYPE'] = content_type
        env.update(headers or {})
        result = {}
        data = b''.join(self.app(env, lambda status, hs: result.update(status=int(status[:3]), headers=dict(hs))))
        return result, json.loads(data)

    def test_missing_slice_module_fails_only_its_route(self):
        with patch.dict(sys.modules, {'rafii_control.founder_incidents': None}):
            result, body = self.request('/incidents?mode=live')
        self.assertEqual((result['status'], body['code']), (503, 'SOURCE_UNAVAILABLE'))
        self.assertEqual((self.store.events[-1]['action'], self.store.events[-1]['result'], self.store.events[-1]['error_code']), ('control.read', 'denied', 'SOURCE_UNAVAILABLE'))
        result, body = self.request('/session')
        self.assertEqual((result['status'], body['data']['assurance']), (200, 'aal2'))
        with patch.dict(sys.modules, {'rafii_control.founder_incidents': fake_module('founder_incidents')}):   # module present, function missing
            result, body = self.request('/incidents?mode=live')
        self.assertEqual((result['status'], body['code']), (503, 'SOURCE_UNAVAILABLE'))
        with patch.dict(sys.modules, {'rafii_control.founder_cron': None, 'rafii_control.founder_contact': fake_module('founder_contact', get_policy=self.record('policy'))}):
            result, body = self.request('/contact-policy')   # the founder store itself comes from the cron slice
        self.assertEqual((result['status'], body['code'], self.seen), (503, 'SOURCE_UNAVAILABLE', []))
        self.assertEqual(self.queries.calls, [])

    def test_routes_reach_their_slice_with_real_signatures_and_the_envelope(self):
        principal = lambda value: value['operator']['user_id'] == USER
        fstore = lambda value: isinstance(value, FakeFounderStore) and value.store is self.store and value.environment == 'local'
        modules = {'rafii_control.live_metrics': fake_module('live_metrics', overview=self.record('overview'), unknown_reservations=self.record('unknown')),
                   'rafii_control.founder_incidents': fake_module('founder_incidents', list_incidents=self.record('incidents'), acknowledge=self.record('ack')),
                   'rafii_control.founder_follow_ups': fake_module('founder_follow_ups', list_follow_ups=self.record('follow_ups'), create=self.record('follow_up_create'), update=self.record('follow_up_update')),
                   'rafii_control.founder_contact': fake_module('founder_contact', get_policy=self.record('policy'), put_policy=self.record('policy_save'), test_call=self.record('test_call')),
                   'rafii_control.founder_schedules': fake_module('founder_schedules', list_schedules=self.record('schedules'), create=self.record('schedule_create'), delete=self.record('schedule_delete'))}
        with patch.dict(sys.modules, modules):
            result, body = self.request('/overview?mode=demo&period=7d')
            self.assertEqual((result['status'], body['dataState'], body['receiptIds'], body['data'], body['environment']), (200, 'partial', ['r-overview'], {'rows': ['overview']}, 'local'))
            name, args, kwargs = self.seen[-1]
            self.assertEqual((name, principal(args[0]), args[1:], kwargs), ('overview', True, ('demo', '7d', self.queries), {'request_id': body['requestId']}))
            cases = [('/usage/unknown?mode=live&limit=25', 'GET', None, 'unknown', lambda a, k: (principal(a[0]), a[1:], k) == (True, ('live', self.queries), {'limit': 25})),
                     ('/incidents?mode=live&includeResolved=0', 'GET', None, 'incidents', lambda a, k: (fstore(a[0]), principal(a[1]), len(a), k) == (True, True, 2, {'limit': 50, 'include_resolved': False})),
                     ('/incidents/inc-1/ack?mode=live', 'POST', {'version': 2}, 'ack', lambda a, k: (fstore(a[0]), a[1:], k) == (True, ('inc-1', 2, USER), {'now': NOW, 'channel': 'web'})),
                     ('/follow-ups', 'GET', None, 'follow_ups', lambda a, k: (fstore(a[0]), principal(a[1]), len(a), k) == (True, True, 2, {'now': NOW})),
                     ('/follow-ups', 'POST', {'title': 'Call'}, 'follow_up_create', lambda a, k: (fstore(a[0]), principal(a[1]), a[2:], k) == (True, True, ({'title': 'Call'},), {'now': NOW})),
                     ('/follow-ups/f-1', 'POST', {'state': 'completed'}, 'follow_up_update', lambda a, k: (fstore(a[0]), principal(a[1]), a[2:], k) == (True, True, ('f-1', {'state': 'completed'}), {'now': NOW})),
                     ('/contact-policy', 'GET', None, 'policy', lambda a, k: (fstore(a[0]), principal(a[1]), len(a), k) == (True, True, 2, {'now': NOW, 'flags': {'RAFII_FOUNDER_CALLS_ENABLED': '0'}})),
                     ('/contact-policy', 'PUT', {'liveDeliveryEnabled': False}, 'policy_save', lambda a, k: (fstore(a[0]), principal(a[1]), a[2:], k) == (True, True, ({'liveDeliveryEnabled': False},), {'now': NOW})),
                     ('/calls/test', 'POST', {'requestId': 'x'}, 'test_call', lambda a, k: (fstore(a[0]), principal(a[1]), a[2:], k) == (True, True, ({'requestId': 'x'},), {'now': NOW, 'flags': {'RAFII_FOUNDER_CALLS_ENABLED': '0'}, 'calls': None})),
                     ('/briefing-schedules', 'GET', None, 'schedules', lambda a, k: (fstore(a[0]), principal(a[1]), len(a), k) == (True, True, 2, {'now': NOW})),
                     ('/briefing-schedules', 'POST', {'kind': 'daily'}, 'schedule_create', lambda a, k: (fstore(a[0]), principal(a[1]), a[2:], k) == (True, True, ({'kind': 'daily'},), {'now': NOW})),
                     ('/briefing-schedules/s-1', 'DELETE', None, 'schedule_delete', lambda a, k: (fstore(a[0]), principal(a[1]), a[2:], k) == (True, True, ('s-1',), {'now': NOW}))]
            for path, method, payload, name, check in cases:
                with self.subTest(path=path, method=method):
                    self.seen.clear()
                    result, body = self.request(path, method, payload, content_type=None if method == 'DELETE' else 'application/json')
                    self.assertEqual((result['status'], body['data'], body['receiptIds']), (200, {'rows': [name]}, ['r-' + name]), body)
                    self.assertEqual(self.seen[0][0], name)
                    self.assertTrue(check(self.seen[0][1], self.seen[0][2]), self.seen[0])
            self.assertIs(self.seen[0][1][0], self.app.founder_store())   # one founder store per app
            self.seen.clear()
            result, body = self.request('/incidents?mode=demo')   # Demo incidents come from the founder's Demo dataset, never from the live store
            self.assertEqual((result['status'], body['dataState'], body['receiptIds'], body['data']), (200, 'synthetic', ['demo-receipt-1'], {'incidents': [{'id': 'demo_cost_anomaly', 'state': 'open'}, {'id': 'demo_old', 'state': 'resolved'}], 'mode': 'demo'}))
            result, body = self.request('/incidents/demo_cost_anomaly/ack?mode=demo', 'POST', {'version': 1})
            self.assertEqual((result['status'], body['code'], self.seen), (400, 'VALIDATION_FAILED', []))
            for query in ('limit=0', 'limit=1001', 'limit=ten'):
                result, body = self.request('/usage/unknown?' + query)
                self.assertEqual((result['status'], body['code']), (400, 'VALIDATION_FAILED'))
        self.assertEqual(self.queries.calls, [])
        self.assertEqual(self.store.events[-1]['action'], 'metrics.query')

    def test_legacy_overview_mode_validation_step_up_and_idempotency(self):
        result, body = self.request('/overview')
        self.assertEqual((result['status'], body['data'], self.queries.calls), (200, {'legacy': '/overview'}, ['/overview']))
        for query in ('mode=staging', 'mode=demo&period=0d', 'mode=live&period=1000d', 'mode=live&period=30'):
            with self.subTest(query=query):
                result, body = self.request('/overview?' + query)
                self.assertEqual((result['status'], body['code']), (400, 'VALIDATION_FAILED'))
        with patch.dict(sys.modules, {'rafii_control.founder_contact': fake_module('founder_contact', get_policy=lambda *a, **k: {'policy': {}}, put_policy=lambda *a, **k: {'saved': True})}):
            self.time = NOW + 301   # MFA older than five minutes: settings need step-up, reads do not
            result, body = self.request('/contact-policy', 'PUT', {'liveDeliveryEnabled': False})
            self.assertEqual((result['status'], body['code']), (403, 'STEP_UP_REQUIRED'))
            result, body = self.request('/contact-policy')
            self.assertEqual((result['status'], body['data']), (200, {'policy': {}}))
            self.time = NOW
            result, body = self.request('/contact-policy', 'PUT', {'liveDeliveryEnabled': False}, {'HTTP_X_CSRF_TOKEN': 'wrong'})
            self.assertEqual((result['status'], body['code']), (403, 'SCOPE_DENIED'))
        budgets = []
        self.store.budget = lambda purpose, actor, limit: budgets.append((purpose, limit))
        turn = lambda service, principal, body, request_id, *, control: {'runId': 'run-1', 'idempotencyKey': body['idempotencyKey'], 'service': service, 'control': control is self.app}
        with patch.dict(sys.modules, {'rafii_control.founder_agent': fake_module('founder_agent', turn=turn)}):
            result, body = self.request('/agent/turns', 'POST', {'message': 'How many paid customers?'})
            self.assertEqual((result['status'], body['code']), (400, 'VALIDATION_FAILED'))
            result, body = self.request('/agent/turns', 'POST', {'message': 'How many paid customers?'}, {'HTTP_IDEMPOTENCY_KEY': 'founder-turn-0001'})
            self.assertEqual((result['status'], body['code']), (503, 'SOURCE_UNAVAILABLE'))   # separate mount: no consumer runtime
            self.app.runtime = lambda: 'consumer-service'
            result, body = self.request('/agent/turns', 'POST', {'message': 'How many paid customers?'}, {'HTTP_IDEMPOTENCY_KEY': 'founder-turn-0001'})
            self.assertEqual((result['status'], body['data']), (201, {'runId': 'run-1', 'idempotencyKey': 'founder-turn-0001', 'service': 'consumer-service', 'control': True}))
            result, body = self.request('/agent/turns', 'POST', {'idempotencyKey': 'other'}, {'HTTP_IDEMPOTENCY_KEY': 'founder-turn-0001'})
            self.assertEqual((result['status'], body['code']), (400, 'VALIDATION_FAILED'))
        self.assertEqual(budgets[:3], [('founder.agent.turn', 20)] * 3)
        for path, method in [('/agent/turns/x', 'POST'), ('/incidents/inc-1', 'POST'), ('/briefing-schedules/s-1', 'POST'), ('/contact-policy', 'DELETE'), ('/incidents/PRIVATE_CANARY/ack', 'GET'), ('/follow-ups/a/b', 'POST')]:
            with self.subTest(path=path, method=method):
                result, _ = self.request(path, method, {} if method != 'GET' else None)
                self.assertEqual(result['status'], 404)
                self.assertEqual(self.store.events[-1]['action'], 'prohibited')
        self.assertNotIn('PRIVATE_CANARY', json.dumps(self.store.events))
        self.store.operator_row['capabilities'] = ['control.read', 'copilot.use']
        result, body = self.request('/incidents/inc-1/ack', 'POST', {'version': 1})
        self.assertEqual((result['status'], body['code']), (403, 'SCOPE_DENIED'))


if __name__ == '__main__':
    unittest.main()
