"""Offline evaluation of actual nested admission code, without fixture imports.

Compile each existing pure DSN guard, or only the admission prefix of class
setup. Never execute class decorators, product imports, SQL or connect calls.
psycopg.conninfo is the real local parser; psycopg is never monkeypatched.
"""
import ast
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from local_pg_target import selected_target

GUARDS = {
    'pipeline': ('TREND_PIPELINE_TEST_DSN', None),
    'planner': ('TREND_PLANNER_TEST_DSN', None),
    'advanced_pipeline': ('TREND_ADVANCED_TEST_DSN', None),
    'forecast_postgres': ('POSTRIFF_TEST_DSN', None),
    'media_jobs': ('POSTRIFF_TEST_DSN', None),
    'whitespace_admission': ('TREND_WHITESPACE_TEST_DSN', None),
    'enrichment': ('TREND_ENRICHMENT_TEST_DSN', 'EnrichmentPostgresTests'),
    'integration': ('TREND_SERVICE_TEST_DSN', 'DurableServiceTests'),
    'notifications': ('TREND_NOTIFICATIONS_TEST_DSN', 'NotificationPostgres'),
}
# Independent PG17 documented connection defaults; do not derive expectations
# from the implementation's denylist.
OVERRIDES = '''PGHOST PGSSLNEGOTIATION PGHOSTADDR PGPORT PGDATABASE PGUSER
    PGPASSWORD PGPASSFILE PGREQUIREAUTH PGCHANNELBINDING PGSERVICE PGSERVICEFILE
    PGOPTIONS PGAPPNAME PGSSLMODE PGREQUIRESSL PGSSLCOMPRESSION PGSSLCERT PGSSLKEY
    PGSSLCERTMODE PGSSLROOTCERT PGSSLCRL PGSSLCRLDIR PGSSLSNI PGREQUIREPEER
    PGSSLMINPROTOCOLVERSION PGSSLMAXPROTOCOLVERSION PGGSSENCMODE PGKRBSRVNAME
    PGGSSLIB PGGSSDELEGATION PGCONNECT_TIMEOUT PGCLIENTENCODING
    PGTARGETSESSIONATTRS PGLOADBALANCEHOSTS PGSYSCONFDIR PSQLRC'''.split()


def admission(name):
    """Bind an actual source function, truncating setup before any schema work."""
    path = ROOT / ('tests/test_trend_' + name + '.py')
    tree = ast.parse(path.read_text(), filename=str(path))
    cls = GUARDS[name][1]
    if cls is None:
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'dedicated_test_dsn')
    else:
        owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
        function = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'setUpClass')
    function = copy.deepcopy(function)
    function.decorator_list = []
    if cls is not None:
        prefix = []
        for statement in function.body:
            # The original admission ends before root/role/schema setup.
            if (isinstance(statement, ast.Assign) and any(isinstance(n, ast.Name)
                    and n.id in ('root', 'role') for target in statement.targets for n in ast.walk(target))):
                break
            if isinstance(statement, ast.ImportFrom) and statement.module not in ('psycopg.conninfo', 'local_pg_target'):
                continue  # Product imports are not admission code.
            prefix.append(statement)
        else:
            raise AssertionError('actual setup admission boundary missing: ' + name)
        function.body = prefix + [ast.Return(value=ast.Attribute(value=ast.Name(id='cls', ctx=ast.Load()), attr='dsn', ctx=ast.Load()))]
    # Refuse evolving source rather than execute I/O or a new unreviewed helper.
    allowed = {'selected_target', 'str', 'any', 'set', 'ValueError', 'conninfo_to_dict', 'make_conninfo',
               'env.get', 'os.environ.get', 'unittest.SkipTest'}
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            if func not in allowed and not (isinstance(node.func, ast.Attribute) and node.func.attr in ('get', 'startswith')):
                raise AssertionError('non-admission call in ' + name + ': ' + func)
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {'os': os, 'unittest': unittest, 'selected_target': selected_target}
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[function.name]


class NestedAdmissionContracts(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.socket = patch('socket.socket', side_effect=AssertionError('real socket forbidden')).start()
        self.process = patch('subprocess.run', side_effect=AssertionError('real subprocess forbidden')).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.socket.assert_not_called)
        self.addCleanup(self.process.assert_not_called)
        self.functions = {name: admission(name) for name in GUARDS}

    def invoke(self, name, env, raw=None):
        with patch.dict(os.environ, env, clear=True):
            function = self.functions[name]
            if GUARDS[name][1]:
                return function(SimpleNamespace())
            if name == 'whitespace_admission':
                return function(raw)
            return function(env)

    def portable_env(self, name, port, *, selected=True):
        dsn = f'host=127.0.0.1 port={port} dbname=postgres'
        env = {'POSTRIFF_TEST_DSN': dsn}
        if selected:
            env['POSTRIFF_TEST_PG_PORT'] = str(port)
        if name in ('enrichment', 'integration', 'notifications', 'whitespace_admission'):
            env[GUARDS[name][0]] = dsn
        return env

    def test_actual_nine_guards_accept_selected55439_and_port_bounds_without_io(self):
        for name in GUARDS:
            for port in (55439, 1024, 65535):
                with self.subTest(guard=name, port=port):
                    try:
                        raw = self.invoke(name, self.portable_env(name, port))
                    except ValueError as error:
                        self.fail('actual selected admission refused: ' + str(error))
                    self.assertEqual(conninfo_to_dict(raw)['port'], str(port))

    def test_default55438_positives_remain_offline(self):
        for name in GUARDS:
            with self.subTest(guard=name):
                self.assertEqual(conninfo_to_dict(self.invoke(name, self.portable_env(name, 55438, selected=False)))['port'], '55438')

    def test_invalid_selectors_and_conflicting_runner_dsn_fail_before_io(self):
        for name in GUARDS:
            for value in ('', '0', '1023', '65536', '055439', '+55439', ' 55439', '5.5', '５５４３９'):
                env = self.portable_env(name, 55438)
                env['POSTRIFF_TEST_PG_PORT'] = value
                with self.subTest(guard=name, invalid=value), self.assertRaises(ValueError):
                    self.invoke(name, env)
            env = self.portable_env(name, 55438)
            env['POSTRIFF_TEST_PG_PORT'] = '55439'
            with self.subTest(guard=name, conflict=True), self.assertRaises(ValueError):
                self.invoke(name, env)

    def test_all_documented_environment_overrides_even_empty_refused_without_values(self):
        for name in GUARDS:
            for key in OVERRIDES:
                for value in ('', 'synthetic-private-auth-input'):
                    env = {**self.portable_env(name, 55438), key: value}
                    with self.subTest(guard=name, key=key, empty=value == ''):
                        with self.assertRaises(ValueError) as caught:
                            self.invoke(name, env)
                        self.assertNotIn('synthetic-private-auth-input', str(caught.exception))

    def test_historical_dedicated_alias_host_port_prefix_and_user_are_preserved(self):
        legacy = {
            'pipeline': ('/private/tmp', '56447', 'trend_pipeline_test'),
            'planner': ('127.0.0.1', '56447', 'trend_planner_retry_test'),
            'advanced_pipeline': ('127.0.0.1', '56451', 'trend_advanced_test'),
            'enrichment': ('127.0.0.1', '56451', 'trend_enrichment_test'),
            'integration': ('/private/tmp', '56447', 'trend_pipeline_service_test'),
            'notifications': ('127.0.0.1', '56451', 'trend_notifications_test'),
        }
        for name, (host, port, dbname) in legacy.items():
            raw = f'host={host} port={port} dbname={dbname} user=synthetic_role'
            env = {GUARDS[name][0]: raw}
            with self.subTest(guard=name, positive=True):
                self.assertEqual(conninfo_to_dict(self.invoke(name, env))['user'], 'synthetic_role')
            for bad in (raw.replace(dbname, 'postgres'), raw.replace(host, 'remote.invalid'), raw + ' hostaddr=198.51.100.1'):
                with self.subTest(guard=name, negative=True), self.assertRaises(ValueError):
                    self.invoke(name, {GUARDS[name][0]: bad})
        # Dedicated aliases on these three guards are deliberately not runner
        # aliases; preserving these negative fixtures is part of portability.
        for name in ('pipeline', 'planner', 'advanced_pipeline'):
            for port in (55438, 55439):
                env = self.portable_env(name, port)
                env[GUARDS[name][0]] = env['POSTRIFF_TEST_DSN']
                with self.subTest(guard=name, alias_port=port), self.assertRaises(ValueError):
                    self.invoke(name, env)
        raw = 'host=127.0.0.1 port=56451 dbname=trend_exposure_test'
        self.assertEqual(conninfo_to_dict(self.invoke('integration', {'TREND_SERVICE_TEST_DSN': raw}))['dbname'], 'trend_exposure_test')

    def test_explicit_whitespace_user_and_portable_class_aliases_keep_original_fields(self):
        raw = 'host=127.0.0.1 port=55439 dbname=postgres user=synthetic_role'
        for name in ('whitespace_admission', 'enrichment', 'integration', 'notifications'):
            env = {'POSTRIFF_TEST_PG_PORT': '55439', GUARDS[name][0]: raw}
            with self.subTest(guard=name):
                try:
                    admitted = self.invoke(name, env, raw if name == 'whitespace_admission' else None)
                except ValueError as error:
                    self.fail('original user field rejected: ' + str(error))
                self.assertEqual(conninfo_to_dict(admitted)['user'], 'synthetic_role')

    def test_remote_uri_extra_fields_wrong_database_and_nonselected_port_rejected(self):
        safe = 'host=127.0.0.1 port=55439 dbname=postgres'
        for name in GUARDS:
            for bad in (safe.replace('127.0.0.1', 'localhost'), safe.replace('127.0.0.1', 'remote.invalid'),
                        safe.replace('postgres', 'production'), safe.replace('55439', '5432'),
                        safe + ' hostaddr=198.51.100.1', safe + ' password=synthetic-secret',
                        safe + ' service=production', safe + ' sslmode=require',
                        'postgresql://synthetic:secret@remote.invalid/postgres'):
                env = self.portable_env(name, 55439)
                env['POSTRIFF_TEST_DSN'] = bad
                if name in ('enrichment', 'integration', 'notifications', 'whitespace_admission'):
                    env[GUARDS[name][0]] = bad
                with self.subTest(guard=name, bad=bad), self.assertRaises(ValueError):
                    self.invoke(name, env)

    def test_adapter_and_raw_source_bindings_include_all_nine_actual_consumers(self):
        spec = importlib.util.spec_from_file_location('nested_target_adapter', ROOT / 'tests/local_pg_target.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        self.assertEqual(adapter.selected_target({'POSTRIFF_TEST_PG_PORT': '55439'}).port, 55439)
        sys.path.insert(0, str(ROOT / 'scripts'))
        import postriff_disposable_postgres as runner
        bindings = runner.source_bindings([])
        for name in GUARDS:
            path = ROOT / ('tests/test_trend_' + name + '.py')
            self.assertEqual(bindings[str(path.relative_to(ROOT))], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(bindings['tests/local_pg_target.py'], hashlib.sha256((ROOT / 'tests/local_pg_target.py').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
