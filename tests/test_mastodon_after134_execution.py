"""Test the explicit disposable-runner opt-in without opening a database."""
import os
from unittest import TestCase
from unittest.mock import patch
import mastodon_after134_fixture as fixture

DSN = 'host=127.0.0.1 port=55438 dbname=postgres user=postriff_test'
BASE = {'POSTRIFF_MASTODON_AFTER134_FIXTURE': '1'}
LOCAL = {**BASE, 'POSTRIFF_MASTODON_AFTER134_LOCAL_FIXTURE': '1'}

class DatabaseReached(Exception):
    pass

class DisposableExecutionTests(TestCase):
    def probe(self):
        raise DatabaseReached('Validated inputs reached the connection boundary')

    def test_explicit_local_macos_runner_reaches_database_preflight(self):
        with patch.dict(os.environ, LOCAL, clear=True), patch.object(fixture.sys, 'platform', 'darwin'):
            with self.assertRaises(DatabaseReached):
                fixture.prepare(self.probe, DSN)

    def test_linux_ci_keeps_its_existing_route(self):
        with patch.dict(os.environ, {**BASE, 'CI': 'true'}, clear=True), patch.object(fixture.sys, 'platform', 'linux'):
            with self.assertRaises(DatabaseReached):
                fixture.prepare(self.probe, DSN)

    def test_neither_os_nor_ci_alone_is_a_disposable_opt_in(self):
        for platform, env in [('darwin', BASE), ('darwin', {'CI': 'true', **BASE}),
                              ('linux', BASE), ('linux', LOCAL), ('win32', LOCAL),
                              ('darwin', {'POSTRIFF_MASTODON_AFTER134_LOCAL_FIXTURE': '1'})]:
            with self.subTest(platform=platform, env=env), patch.dict(os.environ, env, clear=True), patch.object(fixture.sys, 'platform', platform):
                with self.assertRaises(RuntimeError):
                    fixture.prepare(self.probe, DSN)

    def test_local_opt_in_never_widens_database_routing(self):
        for dsn in [DSN.replace('127.0.0.1', 'production.example'), DSN.replace('55438', '5432'),
                    DSN + ' password=secret', DSN + ' hostaddr=10.0.0.1', DSN.replace('dbname=postgres', 'dbname=customer')]:
            with self.subTest(dsn=dsn), patch.dict(os.environ, LOCAL, clear=True), patch.object(fixture.sys, 'platform', 'darwin'):
                with self.assertRaises(RuntimeError):
                    fixture.prepare(self.probe, dsn)

    def test_local_opt_in_keeps_credential_environment_refusal(self):
        for key in ['PGHOSTADDR', 'PGSERVICE', 'PGPASSWORD', 'PGSSLCERT', 'PGSSLKEY']:
            with self.subTest(key=key), patch.dict(os.environ, {**LOCAL, key: 'unexpected'}, clear=True), patch.object(fixture.sys, 'platform', 'darwin'):
                with self.assertRaises(RuntimeError):
                    fixture.prepare(self.probe, DSN)

    def test_unknown_route_and_browser_without_opt_in_still_refuse(self):
        with patch.dict(os.environ, LOCAL, clear=True), patch.object(fixture.sys, 'platform', 'darwin'):
            for route in ['production', 'management-browser']:
                with self.subTest(route=route), self.assertRaises(RuntimeError):
                    fixture.prepare(self.probe, DSN, fixture_route=route)
