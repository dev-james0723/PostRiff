"""Finite offline contract tests: subprocesses and sockets are test doubles only."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests/phase2'))


def load_runner(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suite = load_runner('postriff_pg_suite')
disposable = load_runner('postriff_disposable_postgres')


class RunnerContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='task13-offline-')
        self.addCleanup(self.tmp.cleanup)
        self.pg = Path(self.tmp.name)
        (self.pg / 'initdb').touch()
        self.calls = []
        self.run = patch('subprocess.run', side_effect=self.record).start()
        self.addCleanup(patch.stopall)
        patch('tempfile.tempdir', self.tmp.name).start()
        # Never open a real socket, including in RED.
        self.sock = patch('socket.socket').start()
        self.binding = self.sock.return_value.__enter__.return_value
        self.env = patch.dict(os.environ, {'POSTRIFF_TEST_PG_PORT': '55439'}, clear=True)
        self.env.start()
        patch.object(suite, 'PG', self.pg).start()
        patch.object(disposable, 'PG', self.pg).start()
        patch.object(sys, 'argv', ['postriff_pg_suite.py', 'postgres_plan_guards']).start()
        self.output = io.StringIO()

    def record(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='synthetic stdout\n', stderr='')

    def invoke(self, runner=suite):
        with contextlib.redirect_stdout(self.output):
            return runner.main() if runner is suite else runner.main(['tests/phase2/postgres_plan_guards.py'])

    def test_selected_port_reaches_server_psql_and_both_sequence_children(self):
        self.assertEqual(self.invoke(), 0)
        start = next(a for a, _ in self.calls if a[-1] == 'start')
        self.assertIn('127.0.0.1', start[start.index('-o') + 1])
        self.assertIn('55439', start[start.index('-o') + 1])
        psql = next(a for a, _ in self.calls if Path(a[0]).name == 'psql')
        self.assertIn('port=55439', psql[1])
        children = [(a, kw) for a, kw in self.calls if a[0] == sys.executable]
        self.assertEqual([Path(a[1]).stem for a, _ in children], ['postgres_repository', 'postgres_plan_guards'])
        for _, kw in children:
            self.assertEqual(kw['env']['POSTRIFF_TEST_PG_PORT'], '55439')
            self.assertEqual(kw['env']['POSTRIFF_TEST_DSN'], 'host=127.0.0.1 port=55439 dbname=postgres')

    def test_disposable_forwards_the_same_target_and_dsn(self):
        self.assertEqual(self.invoke(disposable), 0)
        child = next(kw for a, kw in self.calls if a[0] == sys.executable)
        self.assertIn('POSTRIFF_TEST_DSN', child['env'])
        self.assertEqual(child['env']['POSTRIFF_TEST_DSN'], 'host=127.0.0.1 port=55439 dbname=postgres')
        self.assertEqual(child['env']['POSTRIFF_TEST_PG_PORT'], '55439')

    def test_invalid_port_fails_before_socket_or_process_for_both_runners(self):
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__):
                os.environ['POSTRIFF_TEST_PG_PORT'] = '65536'
                with self.assertRaises(ValueError):
                    self.invoke(runner)
                self.sock.assert_not_called()
                self.run.assert_not_called()

    def test_conflicting_dsn_fails_before_socket_or_process(self):
        os.environ['POSTRIFF_TEST_DSN'] = 'host=127.0.0.1 port=55438 dbname=postgres'
        with self.assertRaises(ValueError):
            self.invoke()
        self.sock.assert_not_called()
        self.run.assert_not_called()

    def test_recently_stopped_cluster_time_wait_does_not_refuse_the_next_group(self):
        # Same bind policy as the owned PostgreSQL listener. A live listener is
        # still refused by the separate existing occupied-target regression.
        from local_pg_target import selected_target
        options = set()
        self.binding.setsockopt.side_effect = lambda level, option, value: options.add((level, option, value))
        def time_wait_binding(address):
            if (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) not in options:
                raise OSError('synthetic TIME_WAIT after verified owned stop')
        self.binding.bind.side_effect = time_wait_binding
        try:
            selected_target().assert_available()
        except RuntimeError as error:
            self.fail(str(error))
        self.binding.bind.assert_called_once_with(('127.0.0.1', 55439))
        self.run.assert_not_called()

    def test_new_genome_and_beta_parent_groups_require_the_actual_schema_before_children(self):
        for name in ('postgres_growth_genome_catalog.py', 'postgres_pricing_beta_events.py'):
            with self.subTest(script=name):
                path = ROOT / 'tests/phase2' / name
                with self.assertRaises(RuntimeError):
                    disposable.group_migrations((path,), {})
                setup = disposable.group_migrations((path,), {'POSTRIFF_TEST_OWNED_PG': 'task9-growth'})
                self.assertEqual(tuple(p.name for p in setup), disposable.GROWTH_SCHEMA)
        self.sock.assert_not_called()
        self.run.assert_not_called()

    def test_occupied_target_refused_before_init_and_never_stopped(self):
        self.binding.bind.side_effect = OSError('occupied synthetic target')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.run.assert_not_called()

    def test_unknown_selection_refuses_instead_of_silently_dropping_it(self):
        sys.argv.append('postgres_misspelled')
        with self.assertRaises(ValueError):
            self.invoke()
        self.sock.assert_not_called()
        self.run.assert_not_called()

    def test_catalogue_covers_every_actual_fixture_once_and_keeps_sequences(self):
        groups = suite.selected_groups()
        self.assertEqual(sorted(p.name for group in groups for p in group),
                         sorted(p.name for p in (ROOT / 'tests/phase2').glob('postgres_*.py')))
        self.assertIn(('postgres_repository', 'postgres_plan_guards'), [tuple(p.stem for p in g) for g in groups])
        self.assertIn(('postgres_instagram_lifecycle', 'postgres_safety'), [tuple(p.stem for p in g) for g in groups])

    def test_each_selected_group_gets_a_distinct_data_directory(self):
        sys.argv[:] = ['suite', 'postgres_plan_guards', 'postgres_instagram_lifecycle']
        self.assertEqual(self.invoke(), 0)
        starts = [a[a.index('-D') + 1] for a, _ in self.calls if a[-1] == 'start']
        stops = [a[a.index('-D') + 1] for a, _ in self.calls if a[-1] == 'stop']
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0], starts[1])
        self.assertEqual(starts, stops)
        self.assertEqual([Path(a[1]).stem for a, _ in self.calls if a[0] == sys.executable],
                         ['postgres_instagram_lifecycle', 'postgres_safety', 'postgres_repository', 'postgres_plan_guards'])

    def test_failed_init_or_start_never_stops_a_cluster(self):
        for stage in ('initdb', 'start'):
            with self.subTest(stage=stage):
                self.calls.clear()
                def failed(argv, **kw):
                    result = self.record(argv, **kw)
                    if Path(argv[0]).name == stage or argv[-1] == stage:
                        raise subprocess.CalledProcessError(1, argv)
                    return result
                self.run.side_effect = failed
                with self.assertRaises(subprocess.CalledProcessError):
                    self.invoke()
                self.assertFalse(any(a[-1] == 'stop' for a, _ in self.calls))
                self.assertFalse(any(Path(a[0]).name == 'psql' for a, _ in self.calls))

    def test_failed_baseline_stops_only_the_successfully_started_data_directory(self):
        def failed(argv, **kw):
            result = self.record(argv, **kw)
            if Path(argv[0]).name == 'psql':
                raise subprocess.CalledProcessError(1, argv)
            return result
        self.run.side_effect = failed
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke()
        start = next(a for a, _ in self.calls if a[-1] == 'start')
        stops = [a for a, _ in self.calls if a[-1] == 'stop']
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][stops[0].index('-D') + 1], start[start.index('-D') + 1])

    def test_listener_acquired_during_init_is_refused_before_start(self):
        self.binding.bind.side_effect = [None, OSError('occupied during init')]
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual([Path(a[0]).name for a, _ in self.calls], ['initdb'])

    def test_blank_migration013_group_skips_baseline_without_spawning_second_cluster(self):
        sys.argv[:] = ['suite', 'postgres_migration_013']
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(sum(Path(a[0]).name == 'initdb' for a, _ in self.calls), 1)
        self.assertFalse(any(Path(a[0]).name == 'psql' for a, _ in self.calls))
        source = (ROOT / 'tests/phase2/postgres_migration_013.py').read_text()
        self.assertNotIn('pg_ctl', source)
        self.assertIn('db.execute(SCHEMA)', source)

    def test_child_failure_is_reported_without_dropping_sequence_or_other_groups(self):
        sys.argv[:] = ['suite', 'postgres_plan_guards', 'postgres_instagram_lifecycle']
        def failed(argv, **kw):
            result = self.record(argv, **kw)
            if Path(argv[-1]).name == 'postgres_repository.py':
                result.returncode = 7
            return result
        self.run.side_effect = failed
        self.assertEqual(self.invoke(), 1)
        import json
        receipt = json.loads(self.output.getvalue().splitlines()[-1])
        self.assertEqual(len(receipt['results']), 4)
        self.assertEqual(next(r['exitCode'] for r in receipt['results'] if r['script'].endswith('postgres_repository.py')), 7)
        self.assertEqual(receipt['target'], '127.0.0.1:55439/postgres')

    def test_all_processes_get_target_env_and_user_controlled_policy_is_preserved(self):
        os.environ['POSTRIFF_TEST_OWNED_PG'] = 'parent-controlled-marker'
        os.environ['POSTRIFF_GROWTH_CREDIT_POLICY'] = 'synthetic-parent-grant-policy'
        self.assertEqual(self.invoke(), 0)
        for _, kw in self.calls:
            self.assertEqual(kw['env']['POSTRIFF_TEST_DSN'], 'host=127.0.0.1 port=55439 dbname=postgres')
            self.assertEqual(kw['env']['POSTRIFF_TEST_OWNED_PG'], 'parent-controlled-marker')
            self.assertEqual(kw['env']['POSTRIFF_GROWTH_CREDIT_POLICY'], 'synthetic-parent-grant-policy')
            self.assertEqual(kw['env']['LC_ALL'], 'C')
            self.assertFalse(any(k.startswith('PG') for k in kw['env']))
            self.assertNotIn('capture_output', kw)  # Full inherited raw logs.

    def test_disposable_rejects_outside_nonexistent_duplicate_and_blank_mixed_paths(self):
        for names in ([], ['../postgres_x.py'], ['tests/test_postriff_billing.py'],
                      ['tests/phase2/postgres_missing.py'],
                      ['tests/phase2/postgres_plan_guards.py'] * 2,
                      ['tests/phase2/postgres_migration_013.py', 'tests/phase2/postgres_plan_guards.py']):
            with self.subTest(names=names), self.assertRaises(ValueError):
                disposable.main(names)
        self.run.assert_not_called()
        self.sock.assert_not_called()

    def test_missing_binary_is_unavailable_with_no_socket_or_process(self):
        (self.pg / 'initdb').unlink()
        self.assertEqual(self.invoke(), 3)
        self.sock.assert_not_called()
        self.run.assert_not_called()

    def test_growth_missing_parent_marker_fails_before_socket_or_process(self):
        with self.assertRaises(RuntimeError):
            disposable.group_migrations((ROOT / 'tests/phase2/postgres_growth_credit_rewrite.py',), os.environ)
        self.sock.assert_not_called()
        self.run.assert_not_called()

    def test_growth_fresh_group_applies_minimal_real_schema_before_unchanged_fixture(self):
        os.environ['POSTRIFF_TEST_OWNED_PG'] = 'task9-growth'
        # Parent-owned Growth fixture is absent at this recovery base. Exercise
        # its schema contract directly, without creating that foreign source.
        from local_pg_target import selected_target
        target = selected_target()
        env = disposable.child_environment(target, os.environ)
        migrations = disposable.group_migrations((ROOT / 'tests/phase2/postgres_growth_credit_rewrite.py',), env)
        with disposable.owned_cluster(target, self.pg, env, migrations=migrations):
            subprocess.run([sys.executable, str(ROOT / 'tests/phase2/postgres_plan_guards.py')], env=env)
        sql = [Path(a[a.index('-f') + 1]).name for a, _ in self.calls if Path(a[0]).name == 'psql']
        self.assertEqual(sql, ['rls.sql', '020_credit_quotes.sql', '021_credit_purchases.sql',
                              '022_credit_payment_lifecycle.sql', '048_pricing_credit_catalog_v2.sql',
                              '050_free_lifecycle_bootstrap.sql', '051_pricing_public_four_plans.sql', '052_fixed_plan_checkout_approval.sql'])
        last_sql = max(i for i, (a, _) in enumerate(self.calls) if Path(a[0]).name == 'psql')
        first_child = next(i for i, (a, _) in enumerate(self.calls) if a[0] == sys.executable)
        self.assertLess(last_sql, first_child)

    def test_parent_new_growth_catalogue_uses_same_schema_contract_without_new_file_edits(self):
        # Its path comes from the parent's integration, not worker file creation.
        path = ROOT / 'tests/phase2/postgres_growth_base_check_catalog.py'
        with self.assertRaises(RuntimeError):
            disposable.group_migrations((path,), {})
        setup = disposable.group_migrations((path,), {'POSTRIFF_TEST_OWNED_PG': 'task9-growth'})
        self.assertEqual(tuple(p.name for p in setup), disposable.GROWTH_SCHEMA)
        self.assertEqual(disposable.group_migrations((ROOT / 'tests/phase2/postgres_billing.py',), {}), ())

    def test_receipt_binds_raw_argv_actual_selected_sources_and_migrations(self):
        self.assertEqual(self.invoke(), 0)
        import hashlib
        import json
        receipt = json.loads(self.output.getvalue().splitlines()[-1])
        self.assertEqual(receipt['argv'], [sys.executable, *sys.argv])
        self.assertEqual(receipt['source_before'], receipt['source_after'])
        self.assertTrue(receipt['source_unchanged'])
        for name in ('scripts/postriff_pg_suite.py', 'scripts/postriff_disposable_postgres.py',
                     'tests/phase2/local_pg_target.py', 'tests/phase2/rls.sql',
                     'tests/phase2/postgres_repository.py', 'tests/phase2/postgres_plan_guards.py',
                     'migrations/postriff/048_pricing_credit_catalog_v2.sql'):
            self.assertEqual(receipt['source_before'][name], hashlib.sha256((ROOT / name).read_bytes()).hexdigest())

    def test_source_drift_is_a_failure_even_when_children_pass(self):
        with patch.object(suite, 'source_bindings', side_effect=[{'fixture': 'before'}, {'fixture': 'after'}]):
            self.assertEqual(self.invoke(), 1)
        self.assertIn('"source_unchanged": false', self.output.getvalue())

    def test_server_argv_and_setup_dsn_only_use_selected_loopback_target(self):
        import shlex
        self.assertEqual(self.invoke(), 0)
        start = next(a for a, _ in self.calls if a[-1] == 'start')
        options = shlex.split(start[start.index('-o') + 1])
        self.assertEqual(options[:4], ['-h', '127.0.0.1', '-p', '55439'])
        self.assertEqual(options[4], '-k')
        self.assertTrue(Path(options[5]).is_absolute())
        for argv, _ in self.calls:
            self.assertFalse(any('55438' in str(a) for a in argv))

    def test_conflicting_dedicated_fixture_dsn_fails_before_any_socket_or_psql(self):
        os.environ['TREND_PIPELINE_TEST_DSN'] = 'host=127.0.0.1 port=55438 dbname=postgres'
        with self.assertRaises(ValueError):
            self.invoke()
        self.sock.assert_not_called()
        self.run.assert_not_called()

    def test_default55438_remains_a_mocked_target_only(self):
        os.environ.pop('POSTRIFF_TEST_PG_PORT')
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.binding.bind.call_args_list[0].args[0], ('127.0.0.1', 55438))
        psql = next(a for a, _ in self.calls if Path(a[0]).name == 'psql')
        self.assertEqual(psql[1], 'host=127.0.0.1 port=55438 dbname=postgres')

    def receipt(self):
        import json
        lines = [s for s in self.output.getvalue().splitlines() if s.startswith('{')]
        self.assertTrue(lines, 'failure must retain a structured partial receipt')
        return json.loads(lines[-1])

    def test_review_all_setup_psql_argv_disable_startup_files(self):
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__):
                self.assertEqual(self.invoke(runner), 0)
        from local_pg_target import selected_target
        target = selected_target()
        env = disposable.child_environment(target, os.environ)
        env['POSTRIFF_TEST_OWNED_PG'] = 'task9-growth'
        migrations = disposable.group_migrations((ROOT / 'tests/phase2/postgres_growth_credit_rewrite.py',), env)
        with disposable.owned_cluster(target, self.pg, env, migrations=migrations):
            pass
        setup = [a for a, _ in self.calls if Path(a[0]).name == 'psql']
        self.assertEqual(len(setup), 10)
        applied = {Path(a[a.index('-f') + 1]).name for a in setup if '-f' in a}
        self.assertTrue({'051_pricing_public_four_plans.sql', '052_fixed_plan_checkout_approval.sql'} <= applied)
        self.assertTrue(all('-X' in a or '--no-psqlrc' in a for a in setup))

    def test_review_psqlrc_presence_refused_before_socket_and_process(self):
        for runner in (suite, disposable):
            for value in ('', 'synthetic-startup-input'):
                with self.subTest(runner=runner.__name__, empty=value == ''), patch.dict(os.environ, {'PSQLRC': value}):
                    with self.assertRaises(ValueError) as caught:
                        self.invoke(runner)
                    self.assertNotIn('synthetic-startup-input', str(caught.exception))
        self.assertEqual(self.sock.call_count, 0)
        self.assertEqual(len(self.calls), 0)

    def test_review_documented_connection_defaults_refused_by_presence(self):
        # Independent PG17.11 libpq-envars list, not the helper's own denylist.
        keys = '''PGHOST PGSSLNEGOTIATION PGHOSTADDR PGPORT PGDATABASE PGUSER
            PGPASSWORD PGPASSFILE PGREQUIREAUTH PGCHANNELBINDING PGSERVICE
            PGSERVICEFILE PGOPTIONS PGAPPNAME PGSSLMODE PGREQUIRESSL
            PGSSLCOMPRESSION PGSSLCERT PGSSLKEY PGSSLCERTMODE PGSSLROOTCERT
            PGSSLCRL PGSSLCRLDIR PGSSLSNI PGREQUIREPEER PGSSLMINPROTOCOLVERSION
            PGSSLMAXPROTOCOLVERSION PGGSSENCMODE PGKRBSRVNAME PGGSSLIB
            PGGSSDELEGATION PGCONNECT_TIMEOUT PGCLIENTENCODING
            PGTARGETSESSIONATTRS PGLOADBALANCEHOSTS PGSYSCONFDIR'''.split()
        for runner in (suite, disposable):
            for key in keys:
                for value in ('', 'synthetic-auth-input'):
                    with self.subTest(runner=runner.__name__, key=key, empty=value == ''), patch.dict(os.environ, {key: value}):
                        with self.assertRaises(ValueError) as caught:
                            self.invoke(runner)
                        self.assertNotIn('synthetic-auth-input', str(caught.exception))
        self.assertEqual(self.sock.call_count, 0)
        self.assertEqual(len(self.calls), 0)

    def test_review_drift_status_and_exit_use_same_failure_for_both_runners(self):
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__), patch.object(runner, 'source_bindings', side_effect=[{'fixture': 'before'}, {'fixture': 'after'}]):
                self.assertEqual(self.invoke(runner), 1)
                receipt = self.receipt()
                self.assertIn('status', receipt)
                self.assertEqual(receipt['status'], 'fail')
                self.assertFalse(receipt['source_unchanged'])

    def test_review_partial_receipt_on_setup_and_stop_errors(self):
        for runner in (suite, disposable):
            for stage in ('initdb', 'start', 'psql', 'stop'):
                with self.subTest(runner=runner.__name__, stage=stage):
                    self.calls.clear(); self.output.seek(0); self.output.truncate()
                    error = subprocess.CalledProcessError(8, ['synthetic-' + stage])
                    def failed(argv, **kw):
                        result = self.record(argv, **kw)
                        if Path(argv[0]).name == stage or argv[-1] == stage: raise error
                        return result
                    self.run.side_effect = failed
                    with self.assertRaises(subprocess.CalledProcessError) as caught: self.invoke(runner)
                    self.assertIs(caught.exception, error)
                    receipt = self.receipt()
                    self.assertEqual(receipt['status'], 'fail'); self.assertTrue(receipt['partial'])
                    self.assertEqual(receipt['error']['returncode'], 8)
                    self.assertEqual(receipt['source_before'], receipt['source_after'])
                    self.assertEqual(receipt['target'], '127.0.0.1:55439/postgres')
                    self.assertEqual(len(receipt['results']), (2 if runner is suite else 1) if stage == 'stop' else 0)
                    for cluster in receipt['clusters']:
                        if cluster.get('retained_directory'):
                            import shutil
                            shutil.rmtree(cluster['retained_directory'])  # This test's empty mocked directory only.

    def test_review_later_group_failure_retains_completed_results(self):
        sys.argv[:] = ['suite', 'postgres_instagram_lifecycle', 'postgres_plan_guards']
        def failed(argv, **kw):
            result = self.record(argv, **kw)
            if Path(argv[0]).name == 'psql' and sum(Path(a[0]).name == 'psql' for a, _ in self.calls) == 2:
                raise subprocess.CalledProcessError(9, ['synthetic-second-baseline'])
            return result
        self.run.side_effect = failed
        with self.assertRaises(subprocess.CalledProcessError): self.invoke()
        receipt = self.receipt()
        self.assertEqual([Path(r['script']).stem for r in receipt['results']], ['postgres_instagram_lifecycle', 'postgres_safety'])
        self.assertEqual(len(receipt['clusters']), 2)
        self.assertTrue(all(c['stopped'] for c in receipt['clusters']))

    def test_review_cleanup_failure_preserves_primary_error_and_source_identity(self):
        primary = subprocess.CalledProcessError(8, ['synthetic-setup'])
        cleanup = subprocess.CalledProcessError(9, ['synthetic-stop'])
        def failed(argv, **kw):
            result = self.record(argv, **kw)
            if Path(argv[0]).name == 'psql': raise primary
            if argv[-1] == 'stop': raise cleanup
            return result
        self.run.side_effect = failed
        with self.assertRaises(subprocess.CalledProcessError) as caught: self.invoke()
        self.assertIs(caught.exception, primary)
        receipt = self.receipt()
        self.assertEqual(receipt['error']['returncode'], 8)
        cluster = receipt['clusters'][0]
        self.assertEqual(cluster['cleanup_error']['returncode'], 9)
        self.assertTrue(cluster['started']); self.assertFalse(cluster['stopped'])
        self.assertTrue(receipt['source_unchanged'])
        import shutil
        shutil.rmtree(cluster['retained_directory'])

    def test_review_diagnostic_stat_failure_preserves_original_setup_exception(self):
        original_exists = Path.exists
        def unreadable(path):
            if path.name == 'postgres.log':
                raise OSError('synthetic diagnostic stat failure')
            return original_exists(path)
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__):
                primary = subprocess.CalledProcessError(8, ['synthetic-setup'])
                def failed(argv, **kw):
                    result = self.record(argv, **kw)
                    if Path(argv[0]).name == 'psql': raise primary
                    return result
                self.run.side_effect = failed
                actual = None
                with patch.object(Path, 'exists', unreadable):
                    try: self.invoke(runner)
                    except BaseException as caught: actual = caught
                self.assertIs(actual, primary)
                receipt = self.receipt()
                self.assertEqual(receipt['error']['returncode'], 8)
                self.assertEqual(receipt['clusters'][0]['diagnostic_error']['type'], 'OSError')
                self.assertTrue(receipt['clusters'][0]['stopped'])

    def test_review_directory_cleanup_failure_keeps_primary_and_owned_stop(self):
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__):
                primary = subprocess.CalledProcessError(8, ['synthetic-setup'])
                def failed(argv, **kw):
                    result = self.record(argv, **kw)
                    if Path(argv[0]).name == 'psql': raise primary
                    return result
                self.run.side_effect = failed
                with patch.object(disposable.shutil, 'rmtree', side_effect=PermissionError('synthetic removal failure')):
                    with self.assertRaises(subprocess.CalledProcessError) as caught: self.invoke(runner)
                self.assertIs(caught.exception, primary)
                cluster = self.receipt()['clusters'][0]
                self.assertTrue(cluster['stopped'])
                self.assertEqual(cluster['directory_cleanup_error']['type'], 'PermissionError')
                self.assertTrue(Path(cluster['retained_directory']).is_relative_to(self.pg))

    def test_review_source_after_hash_failure_is_partial_fail_for_both_runners(self):
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__), patch.object(runner, 'source_bindings', side_effect=[{'source': 'before'}, OSError('synthetic hash failure')]):
                self.assertEqual(self.invoke(runner), 1)
                receipt = self.receipt()
                self.assertEqual(receipt['status'], 'fail'); self.assertTrue(receipt['partial'])
                self.assertIsNone(receipt['source_after']); self.assertFalse(receipt['source_unchanged'])
                self.assertEqual(receipt['source_after_error']['type'], 'OSError')
                self.assertTrue(receipt['results'])

    def test_review_receipt_write_failure_never_replaces_primary_error(self):
        class BrokenReceipt(io.StringIO):
            def write(self, value):
                if value.startswith('{"status":'):
                    raise OSError('synthetic receipt write failure')
                return super().write(value)
        for runner in (suite, disposable):
            with self.subTest(runner=runner.__name__):
                self.output = BrokenReceipt()
                primary = subprocess.CalledProcessError(8, ['synthetic-setup'])
                def failed(argv, **kw):
                    result = self.record(argv, **kw)
                    if Path(argv[0]).name == 'psql': raise primary
                    return result
                self.run.side_effect = failed
                with self.assertRaises(subprocess.CalledProcessError) as caught: self.invoke(runner)
                self.assertIs(caught.exception, primary)
                self.assertIn('Partial receipt could not be emitted: OSError', primary.__notes__)
                self.assertTrue(any(a[-1] == 'stop' for a, _ in self.calls))

    def test_review_uncertain_start_or_failed_stop_retains_only_owned_directory(self):
        for runner in (suite, disposable):
            for stage in ('start', 'stop'):
                with self.subTest(runner=runner.__name__, stage=stage):
                    self.calls.clear()
                    primary = subprocess.CalledProcessError(8, ['synthetic-' + stage])
                    def failed(argv, **kw):
                        result = self.record(argv, **kw)
                        if argv[-1] == stage: raise primary
                        return result
                    self.run.side_effect = failed
                    with patch.object(disposable.shutil, 'rmtree') as remove:
                        with self.assertRaises(subprocess.CalledProcessError) as caught: self.invoke(runner)
                        remove.assert_not_called()
                    self.assertIs(caught.exception, primary)
                    cluster = self.receipt()['clusters'][0]
                    self.assertTrue(Path(cluster['retained_directory']).is_relative_to(self.pg))
                    self.assertEqual(cluster['stop_attempted'], stage == 'stop')
                    self.assertEqual(sum(a[-1] == 'stop' for a, _ in self.calls), int(stage == 'stop'))

    def test_review_direct_owned_cluster_refuses_connection_overrides_before_io(self):
        from local_pg_target import selected_target
        target = selected_target()
        for key in ('PSQLRC', 'PGSSLKEY', 'PGGSSDELEGATION'):
            for value in ('', 'synthetic-private-input'):
                with self.subTest(key=key, empty=value == ''), self.assertRaises(ValueError):
                    with disposable.owned_cluster(target, self.pg, {**os.environ, key: value}):
                        self.fail('invalid direct cluster admission')
        self.sock.assert_not_called(); self.run.assert_not_called()

    def test_recovery_legacy_constant_dsn_cannot_reach_foreign_target_for_either_runner(self):
        import ast
        from local_pg_target import selected_target
        # These surviving committed preimages are outside the focused patch.
        # A parent must adapt them; the harness must not start a cluster and
        # then allow either legacy script to connect to occupied foreign55438.
        for runner in (suite, disposable):
            for name in ('postgres_credit_purchases', 'postgres_final_purchase_lifecycle'):
                with self.subTest(runner=runner.__name__, script=name):
                    self.calls.clear(); self.run.reset_mock(); self.sock.reset_mock()
                    path = ROOT / ('tests/phase2/' + name + '.py')
                    constants = [n.value.value for n in ast.parse(path.read_text()).body
                                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DSN' for t in n.targets)
                                 and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
                    unsafe = False
                    for raw in constants:
                        try: selected_target().validate_dsn(raw)
                        except ValueError: unsafe = True
                    def invoke_selected():
                        with contextlib.redirect_stdout(self.output):
                            if runner is suite:
                                sys.argv[:] = ['suite', name]
                                return runner.main()
                            return runner.main(['tests/phase2/' + name + '.py'])
                    if unsafe:
                        with self.assertRaises(ValueError): invoke_selected()
                        self.run.assert_not_called(); self.sock.assert_not_called()
                    else:
                        # Parent may integrate a portable source later. Keep
                        # testing the actual selected script, with mocked I/O.
                        self.assertEqual(invoke_selected(), 0)
                        self.assertTrue(any(Path(a[0]).name == 'psql' and 'port=55439' in a[1] for a, _ in self.calls))
        # Keep a stable negative contract even after parent ports both files.
        legacy = self.pg / 'legacy_target.py'
        legacy.write_text("DSN = 'host=127.0.0.1 port=55438 dbname=postgres'\n")
        with self.assertRaises(ValueError):
            disposable.validate_script_targets([legacy], selected_target())


class HarnessFixturePortability(unittest.TestCase):
    def test_setup_owns_system_tmp_without_source_parent_evidence(self):
        # A managed checkout need not have writable siblings or prior evidence.
        with tempfile.TemporaryDirectory(prefix='task13-source-view-') as source_view:
            absent_root = Path(source_view) / 'absent-parent' / 'checkout'
            case = RunnerContracts('test_default55438_remains_a_mocked_target_only')
            with patch.object(sys.modules[__name__], 'ROOT', absent_root):
                try:
                    try:
                        case.setUp()
                    except OSError as error:
                        self.fail('offline setup depends on source-parent evidence: ' + str(error))
                    self.assertTrue(Path(case.tmp.name).is_dir())
                    self.assertFalse(Path(case.tmp.name).is_relative_to(Path(source_view)))
                    self.assertFalse(absent_root.parent.exists())
                    case.sock.assert_not_called()
                    case.run.assert_not_called()
                finally:
                    case.doCleanups()
            self.assertFalse(Path(case.tmp.name).exists())


class TargetValidation(unittest.TestCase):
    def setUp(self):
        from local_pg_target import selected_target, LocalPGTarget
        self.select = selected_target
        self.target_type = LocalPGTarget
        self.env = {'POSTRIFF_TEST_PG_PORT': '55439'}

    def test_default_bounds_and_explicit_selected_port(self):
        self.assertEqual(self.select({}).port, 55438)
        for port in ('1024', '55439', '65535'):
            self.assertEqual(self.select({'POSTRIFF_TEST_PG_PORT': port}).port, int(port))

    def test_invalid_ports_refused_without_network_or_process(self):
        for value in ('', '0', '1', '1023', '65536', '99999', '100000', '-55439', '+55439',
                      '55439.0', ' 55439', '55439 ', '055439', '５５４３９', '54\n439', '55439;touch', True, 55439, None):
            with self.subTest(value=value), patch('socket.socket') as sock, patch('subprocess.run') as run:
                with self.assertRaises(ValueError):
                    self.select({'POSTRIFF_TEST_PG_PORT': value})
                sock.assert_not_called()
                run.assert_not_called()

    def test_dsn_is_an_assertion_and_cannot_select_a_port(self):
        self.assertEqual(self.select({**self.env, 'POSTRIFF_TEST_DSN': 'dbname=postgres port=55439 host=127.0.0.1'}).port, 55439)
        for env in ({'POSTRIFF_TEST_DSN': 'host=127.0.0.1 port=55439 dbname=postgres'},
                    {**self.env, 'POSTRIFF_TEST_DSN': 'host=127.0.0.1 port=55438 dbname=postgres'},
                    {**self.env, 'POSTRIFF_TEST_DSN': ''}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                self.select(env)
        with self.assertRaises(ValueError):
            self.select(self.env, require_dsn=True)

    def test_libpq_redirects_even_empty_fail_and_errors_do_not_echo_inputs(self):
        from local_pg_target import LIBPQ_OVERRIDES
        for key in LIBPQ_OVERRIDES:
            for value in ('', 'sensitive-fixture-value'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError) as caught:
                    self.select({**self.env, key: value})
                self.assertNotIn('sensitive-fixture-value', str(caught.exception))

    def test_dedicated_fixture_dsns_cannot_override_selected_target(self):
        for key in ('TREND_TEST_DSN', 'TREND_PIPELINE_TEST_DSN', 'TREND_ADVANCED_TEST_DSN',
                    'TREND_PLANNER_TEST_DSN', 'TREND_SERVICE_TEST_DSN', 'TREND_ENRICHMENT_TEST_DSN',
                    'TREND_NOTIFICATIONS_TEST_DSN', 'TREND_EXPOSURE_TEST_DSN',
                    'TREND_GENERATION_TEST_DSN', 'TREND_LAB_TEST_DSN',
                    'TREND_INTERPRETATION_TEST_DSN', 'TREND_WHITESPACE_TEST_DSN'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.select({**self.env, key: 'host=127.0.0.1 port=55438 dbname=postgres'})
            self.assertEqual(self.select({**self.env, key: 'host=127.0.0.1 port=55439 dbname=postgres'}).port, 55439)

    def test_legacy_port_is_only_a_compatibility_assertion(self):
        self.assertEqual(self.select({**self.env, 'POSTRIFF_PG_PORT': '55439'}).port, 55439)
        for env in ({'POSTRIFF_PG_PORT': '55439'}, {**self.env, 'POSTRIFF_PG_PORT': '55438'}):
            with self.assertRaises(ValueError):
                self.select(env)

    def test_no_uri_user_credentials_redirect_or_duplicate_dsn_fields(self):
        good = 'host=127.0.0.1 port=55439 dbname=postgres'
        invalid = ['postgresql://someone:secret@127.0.0.1:55439/postgres',
                   good + ' user=postgres', good + ' password=sensitive-fixture-value',
                   good + ' hostaddr=127.0.0.1', good + ' service=test', good + ' options=-csearch_path=public',
                   good + ' connect_timeout=5', good + ' sslmode=disable', good + ' port=55439',
                   good.replace('127.0.0.1', 'localhost'), good.replace('127.0.0.1', '::1'),
                   good.replace('127.0.0.1', 'example.invalid'), good.replace('postgres', 'production'),
                   good.replace('host=', "host='") + "'", 'host=127.0.0.1 dbname=postgres', None]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError) as caught:
                self.select({**self.env, 'POSTRIFF_TEST_DSN': raw})
            self.assertNotIn('sensitive-fixture-value', str(caught.exception))

    def test_exact_known_database_names_only_without_prefix_wildcards(self):
        from local_pg_target import DATABASES
        target = self.select(self.env)
        for name in DATABASES:
            self.assertEqual(target.validate_dsn(target.dsn(name), dbnames=(name,)), target.dsn(name))
        for name in ('production', 'migration_any', 'trend_restore_random', 'trend_foo', '', 'postgres user=owner'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                target.dsn(name)
        for name in DATABASES - {'postgres'}:
            with self.assertRaises(ValueError):
                self.select({**self.env, 'POSTRIFF_TEST_DSN': target.dsn(name)})

    def test_bind_only_preflight_checks_selected_address_and_always_closes(self):
        with patch('socket.socket') as sock:
            target = self.select(self.env)
            target.assert_available()
            sock.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
            probe = sock.return_value.__enter__.return_value
            probe.bind.assert_called_once_with(('127.0.0.1', 55439))
            probe.connect.assert_not_called()
            sock.return_value.__exit__.assert_called_once()

    def test_direct_constructor_cannot_bypass_integer_bounds(self):
        for value in (True, 0, 1023, 65536, '55439'):
            with self.assertRaises(ValueError):
                self.target_type(value)

    def test_child_env_never_silently_replaces_conflicting_authority(self):
        target = self.select(self.env)
        with self.assertRaises(ValueError):
            target.child_env({**self.env, 'POSTRIFF_TEST_DSN': 'host=127.0.0.1 port=55438 dbname=postgres'})
        with self.assertRaises(ValueError):
            target.child_env({'POSTRIFF_TEST_PG_PORT': '55438'})

    def test_environment_is_not_mutated_and_application_dsn_is_never_used(self):
        env = {**self.env, 'POSTRIFF_DATABASE_URL': 'do-not-use-application-credentials',
               'DATABASE_URL': 'do-not-use-application-credentials'}
        before = dict(env)
        target = self.select(env)
        child = target.child_env(env)
        self.assertEqual(env, before)
        self.assertEqual(child['POSTRIFF_TEST_DSN'], 'host=127.0.0.1 port=55439 dbname=postgres')


if __name__ == '__main__':
    unittest.main(verbosity=2)
