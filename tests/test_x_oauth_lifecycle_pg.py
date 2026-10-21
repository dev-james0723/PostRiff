"""Real local HTTP/SQL OAuth lifecycle; explicit opt-in, synthetic X only, no egress."""
from __future__ import annotations

import http.client
import json
import os
import pwd
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@unittest.skipUnless(os.environ.get('RAFII_X_LOCAL_OAUTH_E2E') == '1', 'Explicit disposable local OAuth fixture required')
class XOAuthLifecyclePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='rafii-x-oauth-lifecycle-')
        cls.directory = Path(cls.temp.name)
        cls.port, pg_port = free_port(), free_port()
        cls.pg_port = pg_port
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.control_path = cls.directory / 'fixture-control.json'
        cls.log = (cls.directory / 'fixture.log').open('w')
        env = {key: value for key, value in os.environ.items() if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'POSTRIFF_PG_BIN')}
        env.update(POSTRIFF_DEV_WEB_ORIGIN=cls.base, RAFII_X_FIXTURE_CONTROL_FILE=str(cls.control_path),
                   PYTHONPATH=str(ROOT / 'src') + os.pathsep + str(ROOT / 'tests'),
                   POSTRIFF_RESEARCH='0', POSTRIFF_LOCAL_CLI='0', OPENAI_AGENTS_DISABLE_TRACING='1',
                   NEXT_TELEMETRY_DISABLED='1', OPENUI_TELEMETRY_DISABLED='1', LC_ALL='C')
        cls.child = subprocess.Popen([sys.executable, 'scripts/x_direct_browser_fixture.py', '--port', str(cls.port), '--pg-port', str(pg_port)],
                                    cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.cleanup_fixture)
        for _ in range(120):
            if cls.child.poll() is not None:
                raise RuntimeError('The disposable synthetic OAuth fixture exited during startup.')
            try:
                status, _, _ = cls.request_raw('GET', '/api/auth/config')
                if status == 200:
                    cls.control = json.loads(cls.control_path.read_text())
                    assert cls.control['classification'] == 'synthetic-local-only'
                    return
            except OSError:
                pass
            time.sleep(.25)
        raise TimeoutError('Disposable OAuth fixture did not become ready.')

    @classmethod
    def cleanup_fixture(cls):
        if cls.child.poll() is None:
            cls.child.terminate()  # Only the synthetic child created above; its handler stops its own DB.
            cls.child.wait(timeout=35)
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def request_raw(cls, method, path, body=None, headers=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('Only paths on the exact loopback fixture are allowed.')
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read(262144)
        finally:
            connection.close()

    def setUp(self):
        self.principal = str(uuid4())
        self.headers = {'Authorization': 'Bearer dev:' + self.principal, 'Origin': self.base,
                        'X-PostRiff-Request': 'founder-alpha', 'Content-Type': 'application/json'}
        self.ws = self.api('POST', '/api/auth/verify', {'plan': 'studio'}, expected=201)['workspaceId']
        self.channel_base = f'/api/workspaces/{self.ws}/channels'

    def api(self, method, path, data=None, expected=200):
        status, _, raw = self.request_raw(method, path, json.dumps(data).encode() if data is not None else None, self.headers)
        self.assertEqual(status, expected, f'{method} {path}: HTTP {status}; expected {expected}')
        return json.loads(raw)

    def authorize(self):
        started = self.api('POST', self.channel_base + '/x/oauth/start', {'capability': 'publish'}, expected=201)
        target = urlsplit(started['authorizeUrl'])
        self.assertEqual(f'{target.scheme}://{target.netloc}', self.base)
        state = parse_qs(target.query)['state'][0]
        headers = {**self.headers, 'Content-Type': 'application/x-www-form-urlencoded'}
        status, response_headers, _ = self.request_raw('POST', '/dev/x/consent', urlencode({'state': state, 'decision': 'allow'}), headers)
        self.assertEqual(status, 302)
        location = urlsplit(response_headers['Location'])
        self.assertEqual(f'{location.scheme}://{location.netloc}', self.base)
        return {key: values[0] for key, values in parse_qs(location.query).items()}

    def connect(self):
        return self.api('POST', self.channel_base + '/x/oauth/complete', self.authorize())['connectionId']

    def stats(self):
        status, _, raw = self.request_raw('GET', '/api/x-fixture/stats', headers={'X-Fixture-Secret': self.control['secret'], 'Origin': self.base})
        self.assertEqual(status, 200)
        return json.loads(raw)

    def local_database(self, name='postgres'):
        import psycopg
        self.assertIsNone(self.child.poll(), 'Test-owned disposable server must still be running.')
        return psycopg.connect(host='127.0.0.1', port=self.pg_port, dbname=name,
                               user=pwd.getpwuid(os.getuid()).pw_name, connect_timeout=3)

    def test_database_roles_cannot_expose_direct_or_cost_tables_to_clients(self):
        import psycopg
        tables = ['public.pr_x_direct_operations', 'public.pr_x_resource_evidence',
                  'postriff.x_cost_windows', 'postriff.x_cost_workspaces', 'postriff.x_cost_reservations',
                  'postriff.x_cost_grants', 'postriff.x_cost_grant_workspaces',
                  'postriff.x_cost_price_evidence', 'postriff.x_cost_app_activation']
        for table in tables:
            with self.subTest(table=table), self.local_database() as db:
                self.assertTrue(db.execute('SELECT relrowsecurity FROM pg_class WHERE oid=%s::regclass', (table,)).fetchone()[0])
                for role in ('anon', 'authenticated'):
                    self.assertFalse(db.execute('SELECT has_table_privilege(%s,%s,%s)', (role, table, 'SELECT')).fetchone()[0])
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with db.transaction():
                            db.execute(psycopg.sql.SQL('SET LOCAL ROLE {}').format(psycopg.sql.Identifier(role)))
                            db.execute(psycopg.sql.SQL('SELECT count(*) FROM {}').format(psycopg.sql.Identifier(*table.split('.'))))
                self.assertTrue(db.execute('SELECT has_table_privilege(%s,%s,%s)', ('service_role', table, 'SELECT')).fetchone()[0])
                with db.transaction():
                    db.execute('SET LOCAL ROLE service_role')
                    self.assertIsInstance(db.execute(psycopg.sql.SQL('SELECT count(*) FROM {}').format(psycopg.sql.Identifier(*table.split('.')))).fetchone()[0], int)

    def migration_case(self, constraint, *, no_op=False, reject=False):
        import psycopg
        name = 'x_migration135_' + uuid4().hex[:12]
        with self.local_database() as admin:
            admin.autocommit = True
            admin.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))
            try:
                with self.local_database(name) as db:
                    db.autocommit = True
                    db.execute('CREATE TABLE public.pr_oauth_transactions(provider text NOT NULL, CONSTRAINT pr_oauth_transactions_provider_check CHECK (' + constraint + '))')
                    before = db.execute("SELECT oid,pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conname='pr_oauth_transactions_provider_check'").fetchone()
                    migration = (ROOT / 'migrations/postriff/135_x_oauth_provider_identifier.sql').read_text()
                    if reject:
                        with self.assertRaises(psycopg.Error):
                            db.execute(migration)
                        db.execute('ROLLBACK')
                        self.assertEqual(db.execute("SELECT oid,pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conname='pr_oauth_transactions_provider_check'").fetchone(), before)
                    else:
                        db.execute(migration)
                        after = db.execute("SELECT oid,pg_get_expr(conbin,conrelid) FROM pg_constraint WHERE conname='pr_oauth_transactions_provider_check'").fetchone()
                        if no_op:
                            self.assertEqual(after, before, 'An already-effective constraint must not be dropped/recreated.')
                        db.execute("INSERT INTO public.pr_oauth_transactions VALUES ('x'),('linkedin')")
                        with self.assertRaises(psycopg.errors.CheckViolation):
                            db.execute("INSERT INTO public.pr_oauth_transactions VALUES ('y')")
            finally:
                admin.execute(psycopg.sql.SQL('DROP DATABASE {}').format(psycopg.sql.Identifier(name)))

    def test_migration135_preserves_an_already_effective_constraint(self):
        self.migration_case("provider = 'x' OR length(provider) BETWEEN 2 AND 40", no_op=True)

    def test_migration135_rejects_unknown_existing_policy(self):
        self.migration_case("provider = 'linkedin'", reject=True)

    def test_migration135_upgrades_only_the_known_legacy_policy(self):
        self.migration_case('length(provider) BETWEEN 2 AND 40')

    def test_disconnect_pending_consent_fences_callback_and_cancels_approved_schedule(self):
        cid = self.connect()
        endpoint = f'/api/workspaces/{self.ws}/x/{cid}'
        future = self.api('POST', endpoint + '/preview', {'operation': 'posts.create', 'body': {'text': 'Canceled fixture only'},
                           'requestKey': str(uuid4()), 'scheduleAt': time.time() + 3600}, expected=201)
        self.api('POST', endpoint + '/operations/' + future['id'] + '/approve', {'confirmed': True, 'digest': future['digest']}, expected=202)
        pending = self.authorize()  # A callback exists but has not been exchanged.
        before = self.stats()
        removed = self.api('DELETE', self.channel_base + '/' + cid, {})
        self.assertTrue(removed['disconnected'])
        self.assertTrue(removed['remoteRevoked'])
        status, _, _ = self.request_raw('POST', self.channel_base + '/x/oauth/complete', json.dumps(pending).encode(), self.headers)
        self.assertIn(status, (403, 404, 409))
        after = self.stats()
        self.assertEqual(after['posts'], before['posts'])
        self.assertEqual(after['realProviderCalls'], 0)
        self.assertEqual(sum(e['event'] == 'pkce_exchange' for e in after['authEvents']),
                         sum(e['event'] == 'pkce_exchange' for e in before['authEvents']))
        status, _, _ = self.request_raw('POST', endpoint + '/preview', json.dumps({'operation': 'posts.create', 'body': {'text': 'Blocked'}}).encode(), self.headers)
        self.assertIn(status, (403, 404, 409))
        # New interactive consent may reconnect; old approval stays canceled.
        fresh = self.connect()
        self.assertEqual(fresh, cid)
        overview = self.api('GET', f'/api/workspaces/{self.ws}/x/{fresh}')
        operation = next(item for item in overview['operations'] if item['id'] == future['id'])
        self.assertEqual(operation['state'], 'canceled')
        self.assertTrue(operation['cancelRequested'])
        self.assertEqual(self.stats()['posts'], before['posts'])


if __name__ == '__main__':
    unittest.main()
