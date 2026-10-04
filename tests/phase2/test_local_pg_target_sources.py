"""Offline source bindings: inspect/evaluate only pure target expressions, never fixtures."""
import ast
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/phase2'))
from local_pg_target import selected_target, DATABASES


def load_suite():
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('offline_catalogue', ROOT / 'scripts/postriff_pg_suite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixtureSourceContracts(unittest.TestCase):
    def checked_port_helpers(self, tree, env=None):
        """Admit only the complete, closed bounded-port function before exec."""
        expected = ast.parse('''
def test_port(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1024 <= int(value) <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be an integer in 1024..65535.')
    return int(value)
''').body[0]
        selected = ast.parse('''
def selected_port(env=None):
    env = os.environ if env is None else env
    value = env.get('POSTRIFF_TEST_PG_PORT', '55438')
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError('POSTRIFF_TEST_PG_PORT must be an explicit decimal port')
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be between 1024 and 65535')
    return port
''').body[0]
        helpers = {}
        for template in (expected, selected):
            functions = [node for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == template.name]
            self.assertLessEqual(len(functions), 1, 'duplicate target helper')
            if not functions:
                continue
            function = functions[0]
            # Exact AST covers arguments, decorators, annotations, all body
            # statements, calls and bounds. No fixture/module imports run.
            self.assertEqual(ast.dump(function), ast.dump(template), 'unchecked target helper body')
            module = ast.Module(body=[copy.deepcopy(function)], type_ignores=[])
            namespace = {'__builtins__': {}, 'isinstance': isinstance,
                         'str': str, 'int': int, 'ValueError': ValueError,
                         'os': SimpleNamespace(environ={} if env is None else env)}
            exec(compile(ast.fix_missing_locations(module), '<checked-port-helper>', 'exec'), namespace)
            function = namespace[template.name]
            def invoke(raw):
                return function({'POSTRIFF_TEST_PG_PORT': raw}) if template.name == 'selected_port' else function(raw)
            for raw, port in (('1024', 1024), ('55438', 55438), ('55439', 55439), ('65535', 65535)):
                self.assertEqual(invoke(raw), port)
            for raw in (None, True, 55439, '', '0', '1023', '65536', '+55439',
                        '-55439', ' 55439', '55439 ', '5.5', '５５４３９'):
                with self.assertRaises(ValueError):
                    invoke(raw)
            helpers[template.name] = function
        return helpers

    def portable_default_nodes(self, tree, helpers):
        """Recognize defaults by their checked target binding, never filename."""
        defaults = set()
        getter = "os.environ.get('POSTRIFF_TEST_PG_PORT', '55438')"
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in ('PORT', 'TEST_PG_PORT')):
                continue
            for name in ('int', *(('test_port',) if 'test_port' in helpers else ())):
                expected = ast.parse(name + '(' + getter + ')', mode='eval').body
                if ast.dump(node.value) == ast.dump(expected):
                    defaults.add(id(node.value.args[0].args[1]))
        if 'selected_port' in helpers:
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'selected_port')
            # The complete function was checked above; only this exact getter's
            # default is admitted, never other literals in a helper body.
            defaults.add(id(function.body[1].value.args[1]))
        return defaults

    def assert_selected_connection_guard(self, tree):
        # This is a source assertion on the actual new PG17 connection, not an
        # invocation of it. Credentials, other hosts and altered guards fail.
        expected = ast.parse('''
def connection():
    db = psycopg.connect(DSN, client_encoding='utf8')
    assert db.info.host == '127.0.0.1' and db.info.port == PORT
    assert 170000 <= db.info.server_version < 180000, 'Task11 requires the parent PG17 fixture'
    return db
''').body[0]
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'connection']
        self.assertEqual(len(functions), 1, 'missing or duplicate selected connection guard')
        self.assertEqual(ast.dump(functions[0]), ast.dump(expected), 'actual connected-target/PG17 guard changed')

    def assert_trends_connection_guards(self, tree):
        expected = ast.parse('''
def validated_dsn(env=None):
    env = os.environ if env is None else env
    port = selected_port(env)
    dsn = env.get('POSTRIFF_TEST_DSN', f'host=127.0.0.1 port={port} dbname=postgres')
    params = conninfo_to_dict(dsn)
    if (set(params) - {'host', 'port', 'dbname', 'user'}
            or (params.get('host'), params.get('port'), params.get('dbname'))
            != ('127.0.0.1', str(port), 'postgres')
            or any(k in env for k in PG_ENV_OVERRIDES)):
        raise ValueError('exact loopback disposable DSN must match the selected port')
    return dsn
def connection(*, row_factory=tuple_row, service=False):
    db = psycopg.connect(validated_dsn(), client_encoding='utf8',
        row_factory=row_factory, connect_timeout=3, passfile='/dev/null',
        options='-c statement_timeout=10000 -c lock_timeout=750')
    if (db.info.host, db.info.port, db.info.dbname) != ('127.0.0.1', selected_port(), 'postgres'):
        db.close()
        raise ValueError('connected database differs from the selected disposable target')
    if service:
        db.execute('SET ROLE service_role')
    return db
''')
        for template in expected.body:
            functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == template.name]
            self.assertEqual(len(functions), 1, 'missing or duplicate Trends admission guard')
            self.assertEqual(ast.dump(functions[0]), ast.dump(template), 'actual Trends DSN/connected-target guard changed')

    def assert_pure_target_expression(self, expression, helpers=()):
        # An evolving catalogue must fail this validator, never execute new I/O.
        allowed = {'selected_target', 'int', 'os.environ.get', 'TARGET.validate_dsn', 'TARGET.dsn',
                   'selected_target().dsn', 'selected_target(require_dsn=True).dsn'}
        allowed.update(helpers)
        for node in ast.walk(expression):
            if isinstance(node, ast.Call):
                self.assertIn(ast.unparse(node.func), allowed)
            self.assertNotIsInstance(node, (ast.Lambda, ast.NamedExpr, ast.ListComp, ast.GeneratorExp))

    def test_every_actual_fixture_parses_without_importing_or_running_it(self):
        for path in sorted((ROOT / 'tests/phase2').glob('postgres_*.py')):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), filename=str(path))

    def test_no_fixed_target_dsn_label_or_foreign_cluster_survives_in_catalogue(self):
        for path in sorted((ROOT / 'tests/phase2').glob('postgres_*.py')):
            tree = ast.parse(path.read_text())
            helpers = self.checked_port_helpers(tree)
            defaults = self.portable_default_nodes(tree, helpers)
            if 'test_port' in helpers:
                self.assert_selected_connection_guard(tree)
            if 'selected_port' in helpers:
                self.assert_trends_connection_guards(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotIn('host=127.0.0.1 port=55438', node.value, (path.name, node.lineno))
                    self.assertNotIn('127.0.0.1:55438/postgres', node.value, (path.name, node.lineno))
                    self.assertNotIn('pg_ctl', node.value, (path.name, node.lineno))
                    if node.value == '55438':
                        self.assertIn(id(node), defaults, (path.name, node.lineno, 'unchecked default port context'))
                if isinstance(node, ast.Assert):
                    # Port safety remains an exact equality, now selected by helper.
                    self.assertNotIn('Constant(value=55438)', ast.dump(node), path.name)

    def test_pure_fixture_dsn_assignments_and_inline_connections_bind_selected55439(self):
        env = {'POSTRIFF_TEST_PG_PORT': '55439',
               'POSTRIFF_TEST_DSN': 'host=127.0.0.1 port=55439 dbname=postgres'}
        target = selected_target(env)
        for path in sorted((ROOT / 'tests/phase2').glob('postgres_*.py')):
            tree = ast.parse(path.read_text())
            helpers = self.checked_port_helpers(tree, env)
            if 'test_port' in helpers:
                self.assert_selected_connection_guard(tree)
            if 'selected_port' in helpers:
                self.assert_trends_connection_guards(tree)
            namespace = {'selected_target': lambda **kwargs: selected_target(env, **kwargs),
                         'os': SimpleNamespace(environ=env), 'int': int, 'TARGET': target, **helpers}
            # Only target expressions are evaluated. No imports, SQL, providers,
            # psycopg, fixture setup, test methods or assertions are executed.
            for node in tree.body:
                if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                name = node.targets[0].id
                if name not in ('DSN', 'BASE_DSN', 'PORT', 'TEST_PG_PORT', 'TARGET'):
                    continue
                self.assert_pure_target_expression(node.value, helpers)
                value = eval(compile(ast.Expression(node.value), str(path), 'eval'), {'__builtins__': {}}, namespace)
                namespace[name] = value
                if name in ('DSN', 'BASE_DSN'):
                    with self.subTest(path=path.name, binding=name):
                        try:
                            admitted = target.validate_dsn(value)
                        except ValueError as error:
                            self.fail('actual fixture target binding is incompatible: ' + str(error))
                        self.assertEqual(admitted, target.dsn())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'connect' and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == 'psycopg' and node.args):
                    expression = node.args[0]
                    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute) and expression.func.attr == 'dsn':
                        self.assert_pure_target_expression(expression, helpers)
                        value = eval(compile(ast.Expression(expression), str(path), 'eval'), {'__builtins__': {}}, namespace)
                        self.assertEqual(target.validate_dsn(value, dbnames=DATABASES), value)

    def test_selected_port_and_database_guard_structure_is_retained(self):
        beta = ROOT / 'tests/phase2/postgres_pricing_beta_events.py'
        if beta.is_file():
            tree = ast.parse(beta.read_text())
            self.assertEqual(set(self.checked_port_helpers(tree)), {'test_port'})
            self.assert_selected_connection_guard(tree)
        trends = ROOT / 'tests/phase2/postgres_task9_trends_funding_v2.py'
        if trends.is_file():
            tree = ast.parse(trends.read_text())
            self.assertEqual(set(self.checked_port_helpers(tree)), {'selected_port'})
            self.assert_trends_connection_guards(tree)
        path = ROOT / 'tests/phase2/postgres_growth_credit_rewrite.py'
        if path.is_file():
            tree = ast.parse(path.read_text())
            connection = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'connection')
            source = ast.unparse(connection)
            self.assertIn("os.environ.get('POSTRIFF_TEST_OWNED_PG') != 'task9-growth'", source)
            self.assertIn("'POSTRIFF_TEST_PG_PORT' not in os.environ", source)
            self.assertIn("db.info.host == '127.0.0.1' and db.info.port == port", source)
            setup = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'setUpClass')
            self.assertIn('Parent Task5/6 schema required', ast.unparse(setup))
            self.assertNotIn('db.execute(', source.split('psycopg.connect')[0])
        else:
            # Missing parent source must never become an admitted executable.
            suite = load_suite()
            with self.assertRaises(ValueError): suite.selected_groups((path.stem,))
            self.assertIn(path.stem, suite.group_migrations.__globals__['GROWTH_PARENT_GROUPS'])
        for name in ('postgres_trend_frontier.py', 'postgres_trend_generation.py',
                     'postgres_trend_services.py', 'postgres_trend_interpretation.py'):
            source = (ROOT / 'tests/phase2' / name).read_text()
            self.assertIn('selected_target(require_dsn=True)', source)
            for key in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR', 'PGOPTIONS'):
                self.assertIn(key, source)

    def test_migration_restore_and_pricing_database_connections_use_exact_allowlist(self):
        expected = {
            'postgres_consumer_migrations.py': ('migration_candidate', 'migration_restore', 'migration_fresh'),
            'postgres_pricing_catalog_v2.py': ('pricing_catalog_v2_', 'pricing_catalog_v2_old_packs'),
            'postgres_trend_trust.py': ('trend_restore',),
        }
        for name, names in expected.items():
            source = (ROOT / 'tests/phase2' / name).read_text()
            for value in names:
                self.assertIn(value, source)
            self.assertNotIn('make_conninfo(BASE_DSN, dbname=', source)
            self.assertNotIn("restore_db='trend_restore_'+", source)
        source = (ROOT / 'tests/phase2/postgres_trend_trust.py').read_text()
        self.assertIn("dbnames=('postgres', 'trend_restore')", source)
        self.assertIn('NOSUPERUSER NOBYPASSRLS INHERIT', source)
        self.assertIn('assert condition,label', source)

    def test_actual_catalogue_and_source_bindings_include_every_selected_script(self):
        suite = load_suite()
        groups = suite.selected_groups()
        actual = sorted((ROOT / 'tests/phase2').glob('postgres_*.py'))
        self.assertEqual(sorted(p for g in groups for p in g), actual)
        bindings = suite.source_bindings([p for g in groups for p in g])
        for path in actual:
            self.assertEqual(bindings[str(path.relative_to(ROOT))], hashlib.sha256(path.read_bytes()).hexdigest())
        for name in ('scripts/postriff_pg_suite.py', 'scripts/postriff_disposable_postgres.py',
                     'tests/phase2/local_pg_target.py'):
            self.assertIn(name, bindings)

    def test_fixture_role_and_grant_probes_are_still_real_sql(self):
        source = (ROOT / 'tests/phase2/postgres_pricing_catalog_v2.py').read_text()
        for value in ('NOBYPASSRLS', 'SET LOCAL ROLE authenticated', 'SET LOCAL ROLE service_role'):
            self.assertIn(value, source)
        # Independent qualification/current-rights probes retain their original
        # fixtures; this adapter never supplies or changes a grant policy.
        source = (ROOT / 'tests/phase2/postgres_trend_trust.py').read_text()
        self.assertIn('rolsuper,rolbypassrls', source)
        self.assertIn('revocation.revoke_entitlement', source)
        self.assertIn("r==(False,False)", source)
        self.assertIn('restore_tombstones', source)


class SourceAdmissionRegression(unittest.TestCase):
    # Static source samples only. No PG module imports or connection calls.
    PORT_SOURCE = '''
def test_port(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1024 <= int(value) <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be an integer in 1024..65535.')
    return int(value)
'''
    CONNECTION_SOURCE = '''
def connection():
    db = psycopg.connect(DSN, client_encoding='utf8')
    assert db.info.host == '127.0.0.1' and db.info.port == PORT
    assert 170000 <= db.info.server_version < 180000, 'Task11 requires the parent PG17 fixture'
    return db
'''
    SELECTED_PORT_SOURCE = '''
def selected_port(env=None):
    env = os.environ if env is None else env
    value = env.get('POSTRIFF_TEST_PG_PORT', '55438')
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError('POSTRIFF_TEST_PG_PORT must be an explicit decimal port')
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be between 1024 and 65535')
    return port
'''
    TRENDS_GUARD_SOURCE = '''
def validated_dsn(env=None):
    env = os.environ if env is None else env
    port = selected_port(env)
    dsn = env.get('POSTRIFF_TEST_DSN', f'host=127.0.0.1 port={port} dbname=postgres')
    params = conninfo_to_dict(dsn)
    if (set(params) - {'host', 'port', 'dbname', 'user'}
            or (params.get('host'), params.get('port'), params.get('dbname'))
            != ('127.0.0.1', str(port), 'postgres')
            or any(k in env for k in PG_ENV_OVERRIDES)):
        raise ValueError('exact loopback disposable DSN must match the selected port')
    return dsn
def connection(*, row_factory=tuple_row, service=False):
    db = psycopg.connect(validated_dsn(), client_encoding='utf8',
        row_factory=row_factory, connect_timeout=3, passfile='/dev/null',
        options='-c statement_timeout=10000 -c lock_timeout=750')
    if (db.info.host, db.info.port, db.info.dbname) != ('127.0.0.1', selected_port(), 'postgres'):
        db.close()
        raise ValueError('connected database differs from the selected disposable target')
    if service:
        db.execute('SET ROLE service_role')
    return db
'''

    def setUp(self):
        self.contract = FixtureSourceContracts('test_every_actual_fixture_parses_without_importing_or_running_it')

    def test_checked_helper_evaluates_actual_selected_default_and_bounded_ports(self):
        helpers = self.contract.checked_port_helpers(ast.parse(self.PORT_SOURCE))
        expression = ast.parse("test_port(os.environ.get('POSTRIFF_TEST_PG_PORT', '55438'))", mode='eval').body
        self.contract.assert_pure_target_expression(expression, helpers)
        for env, expected in (({}, 55438), ({'POSTRIFF_TEST_PG_PORT': '55439'}, 55439),
                              ({'POSTRIFF_TEST_PG_PORT': '1024'}, 1024),
                              ({'POSTRIFF_TEST_PG_PORT': '65535'}, 65535)):
            namespace = {'os': SimpleNamespace(environ=env), **helpers}
            self.assertEqual(eval(compile(ast.Expression(expression), '<pure-port-regression>', 'eval'),
                                  {'__builtins__': {}}, namespace), expected)
        # Preserve the existing fixture's spelling semantics; the runner's
        # canonical selector refusal is covered separately by TargetValidation.
        self.assertEqual(helpers['test_port']('055439'), 55439)

    def test_unchecked_helper_mutations_fail_before_any_execution(self):
        changes = (
            ('1024 <=', '0 <='), ('<= 65535', '<= 99999'),
            ('not value.isascii() or ', ''), ('not value.isdigit() or ', ''),
            ('not isinstance(value, str) or ', ''), (' or ', ' and '),
            ('return int(value)', 'return value'),
            ('return int(value)', "import os\n    os.system('prohibited')\n    return int(value)"),
            ('def test_port(value):', "@prohibited()\ndef test_port(value):"),
            ('def test_port(value):', 'def test_port(value=prohibited()):'),
            ('def test_port(value):', 'def test_port(value: prohibited()):'),
            ('def test_port(value):', 'def test_port(value) -> prohibited():'),
            ('def test_port(value):', 'async def test_port(value):'),
        )
        for before, after in changes:
            with self.subTest(mutation=after), self.assertRaises(AssertionError):
                self.contract.checked_port_helpers(ast.parse(self.PORT_SOURCE.replace(before, after)))
        with self.assertRaises(AssertionError):
            self.contract.checked_port_helpers(ast.parse(self.PORT_SOURCE + self.PORT_SOURCE))

    def test_default_literal_is_admitted_only_in_exact_target_binding(self):
        helpers = self.contract.checked_port_helpers(ast.parse(self.PORT_SOURCE))
        getter = "os.environ.get('POSTRIFF_TEST_PG_PORT', '55438')"
        for assignment in ('PORT = int(' + getter + ')', 'TEST_PG_PORT = int(' + getter + ')',
                           'PORT = test_port(' + getter + ')'):
            tree = ast.parse(assignment)
            defaults = self.contract.portable_default_nodes(tree, helpers)
            literal = next(node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == '55438')
            self.assertEqual(defaults, {id(literal)})
        for assignment in (
            "PORT = int(os.environ.get('PGPORT', '55438'))",
            "OTHER = int(os.environ.get('POSTRIFF_TEST_PG_PORT', '55438'))",
            'PORT = unchecked(' + getter + ')', 'PORT = int(' + getter + ', base=10)',
            "DSN = 'host=127.0.0.1 port=55438 dbname=postgres'",
            "def arbitrary():\n    return '55438'",
        ):
            with self.subTest(source=assignment):
                self.assertEqual(self.contract.portable_default_nodes(ast.parse(assignment), helpers), set())
        tree = ast.parse('PORT = test_port(' + getter + ')')
        self.assertEqual(self.contract.portable_default_nodes(tree, {}), set())

    def test_actual_connected_host_port_and_pg17_assertions_cannot_be_removed(self):
        self.contract.assert_selected_connection_guard(ast.parse(self.CONNECTION_SOURCE))
        changes = (
            ("assert db.info.host == '127.0.0.1' and db.info.port == PORT", 'pass'),
            ("db.info.host == '127.0.0.1'", "db.info.host == 'remote.invalid'"),
            ('db.info.port == PORT', 'db.info.port == 55438'),
            ("assert 170000 <= db.info.server_version < 180000, 'Task11 requires the parent PG17 fixture'", 'pass'),
            ('170000 <=', '140000 <='), ('< 180000', '< 190000'),
            ("client_encoding='utf8'", "client_encoding='utf8', user='unchecked'"),
            ('return db', "db.execute('prohibited SQL')\n    return db"),
        )
        for before, after in changes:
            with self.subTest(mutation=after), self.assertRaises(AssertionError):
                self.contract.assert_selected_connection_guard(ast.parse(self.CONNECTION_SOURCE.replace(before, after)))
        for source in ('', self.CONNECTION_SOURCE + self.CONNECTION_SOURCE):
            with self.assertRaises(AssertionError):
                self.contract.assert_selected_connection_guard(ast.parse(source))

    def test_expression_calls_require_the_checked_helper_and_reject_unrelated_io(self):
        expression = ast.parse("test_port(os.environ.get('POSTRIFF_TEST_PG_PORT', '55438'))", mode='eval').body
        with self.assertRaises(AssertionError):
            self.contract.assert_pure_target_expression(expression)
        helpers = self.contract.checked_port_helpers(ast.parse(self.PORT_SOURCE))
        for source in ("unchecked('55439')", "os.system('prohibited')", "psycopg.connect('prohibited')",
                       "test_port(os.system('prohibited'))", '(lambda: 55439)()',
                       "[int(v) for v in ('55439',)]"):
            with self.subTest(source=source), self.assertRaises(AssertionError):
                self.contract.assert_pure_target_expression(ast.parse(source, mode='eval').body, helpers)

    def test_trends_helper_default_is_checked_with_actual_bounds_and_no_body_exception(self):
        tree = ast.parse(self.SELECTED_PORT_SOURCE)
        helpers = self.contract.checked_port_helpers(tree, {'POSTRIFF_TEST_PG_PORT': '55439'})
        self.assertEqual(helpers['selected_port'](), 55439)
        self.assertEqual(helpers['selected_port']({}), 55438)
        for raw, expected in (('1024', 1024), ('65535', 65535)):
            self.assertEqual(helpers['selected_port']({'POSTRIFF_TEST_PG_PORT': raw}), expected)
        literal = next(node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == '55438')
        self.assertEqual(self.contract.portable_default_nodes(tree, helpers), {id(literal)})
        self.assertEqual(self.contract.portable_default_nodes(tree, {}), set())
        for before, after in (
            ('1024 <=', '0 <='), ('<= 65535', '<= 99999'),
            ('not value.isascii() or ', ''), ('not value.isdecimal()', 'False'),
            ('return port', "os.system('prohibited')\n    return port"),
            ('env=None', 'env=prohibited()'),
        ):
            with self.subTest(mutation=after), self.assertRaises(AssertionError):
                self.contract.checked_port_helpers(ast.parse(self.SELECTED_PORT_SOURCE.replace(before, after)))

    def test_trends_dsn_and_connected_target_guards_cannot_be_relaxed(self):
        self.contract.assert_trends_connection_guards(ast.parse(self.TRENDS_GUARD_SOURCE))
        for before, after in (
            ('127.0.0.1', 'remote.invalid'), ('str(port)', "'55438'"),
            ('dbname=postgres', 'dbname=foreign'),
            (' or any(k in env for k in PG_ENV_OVERRIDES)', ''),
            ("('127.0.0.1', selected_port(), 'postgres')", "('127.0.0.1', 55438, 'postgres')"),
            ('db.close()', 'pass'),
            ("raise ValueError('connected database differs from the selected disposable target')", 'pass'),
            ("db.execute('SET ROLE service_role')", 'pass'),
        ):
            with self.subTest(mutation=after), self.assertRaises(AssertionError):
                self.contract.assert_trends_connection_guards(ast.parse(self.TRENDS_GUARD_SOURCE.replace(before, after)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
