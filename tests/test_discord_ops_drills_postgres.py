"""H-07 isolated drills as tests (tests/discord_ops_drills.py), plus an offline check of the phone runbook's statements.

The drills start their own disposable PostgreSQL (POSTRIFF_PG_BIN) with a mock Discord and never read a credential or
reach a network except 127.0.0.1. They take about four minutes (one drill keeps a request budget saturated for a
minute) and are skipped where PostgreSQL is not available or under the synthetic transport fence.
"""
import hashlib
import json
import re
import time
import unittest

import discord_lane_fixture as F
import discord_ops_drills as drills


class RunbookStatements(unittest.TestCase):
    def test_the_runbook_carries_the_drilled_statements(self):
        statements = drills.runbook_statements()
        self.assertEqual(set(statements), {'HOLD_ON', 'HOLD_OFF', 'HOLD_READBACK', 'HOLD_INSERT', 'HOLD_KEYCHECK', 'DRAIN_CHECK'})
        body = {name: ' '.join(line for line in text.splitlines() if not line.startswith('--')).strip()
                for name, text in statements.items()}
        # The statement RUNBOOK-INCIDENT step 2 and docs/w02/AS-BUILT.md give, on the coordinator's policy row, made to
        # prove itself: it returns the rows it held (none means there is no hold; the restore drill measured that case).
        self.assertEqual(body['HOLD_ON'], "UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy' "
                                          "RETURNING kind, manual_hold;")
        self.assertEqual(body['HOLD_OFF'], "UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE kind = 'policy' "
                                           "RETURNING kind, manual_hold;")
        for name in ('HOLD_READBACK', 'HOLD_KEYCHECK', 'DRAIN_CHECK'):
            self.assertIsNone(re.search(r'\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP)\b', body[name]), name)
        self.assertNotIn('LIMIT', body['DRAIN_CHECK'], 'the drain check is complete, never a sample (review C1)')

    def test_migration_141_runs_the_sql_twins_own_statement(self):
        root = drills.ROOT
        twin = '\n'.join(l for l in (root / 'docs/ops/discord-ops-snapshot.sql').read_text().splitlines() if not l.startswith('--'))
        migration = (root / 'migrations/postriff/141_discord_ops_snapshot_reader.sql').read_text()
        body = migration.split('$snapshot$\n', 1)[1].split('\n$snapshot$', 1)[0]
        self.assertEqual(' '.join(body.split()), ' '.join(twin.strip().rstrip(';').split()))

    def test_migration_141_pins_the_functions_search_path_and_who_may_execute_it(self):
        """Second review N-10 (mutations N7a, N7b): a SECURITY DEFINER function without its empty search_path, or left
        executable by PUBLIC (and so by Supabase's anon, authenticated and service_role), passed every test."""
        migration = (drills.ROOT / 'migrations/postriff/141_discord_ops_snapshot_reader.sql').read_text()
        self.assertIn("CREATE OR REPLACE FUNCTION public.pr_discord_ops_snapshot() RETURNS jsonb\n"
                      "LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $snapshot$", migration)
        self.assertIn('REVOKE ALL ON FUNCTION public.pr_discord_ops_snapshot() FROM PUBLIC, anon, authenticated, service_role;',
                      migration)
        self.assertEqual(re.findall(r'GRANT EXECUTE ON FUNCTION public\.pr_discord_ops_snapshot\(\) TO ([^;]+);', migration),
                         ['rafii_discord_ops_reader'])

    def test_the_on_call_automatic_hold_runs_the_runbooks_own_statements(self):
        from rafii_control.oncall import autohold
        self.assertEqual(autohold.HOLD_ON, autohold.runbook_block('HOLD_ON'))
        self.assertEqual(autohold.HOLD_READBACK, autohold.runbook_block('HOLD_READBACK'))

    def test_the_fallback_insert_names_the_coordinators_own_policy_row(self):
        statement = drills.runbook_statements()['HOLD_INSERT']
        self.assertIn("'00:' || encode(sha256(convert_to('DISCORD_APPLICATION_ID', 'UTF8')), 'hex')", statement)
        budget = drills.SharedPostgresBudget(lambda: None, F.APP)
        self.assertEqual(budget.application_key, hashlib.sha256(F.APP.encode('utf-8')).hexdigest())
        self.assertIn('manual_hold = true', statement)


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class IsolatedDrills(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lab = drills.Lab()

    @classmethod
    def tearDownClass(cls):
        cls.lab.close()

    def drill(self, function):
        signal = drills.security_signals.DenialSignal()
        with drills.patch.object(drills.security_signals, 'SIGNAL', signal):
            record = function(self.lab)
        failed = [check for check in record['checks'] if not check['pass']]
        self.assertEqual(failed, [], record['id'])
        self.assertEqual(record['result'], 'PASS')

    def test_d0_baseline(self):
        self.drill(drills.d0_baseline)

    def test_d1_backlog(self):
        self.drill(drills.d1_backlog)

    def test_d2_delivery(self):
        self.drill(drills.d2_delivery)

    def test_d3_rate_limit(self):
        self.drill(drills.d3_rate_limit)

    def test_d4_silent_halt(self):
        self.drill(drills.d4_silent_halt)

    def test_d5_cross_tenant(self):
        self.drill(drills.d5_cross_tenant)

    def test_d6_config_drift(self):
        self.drill(drills.d6_config_drift)

    def test_o1_hold(self):
        self.drill(drills.o1_hold)

    def test_o2_rollback_order(self):
        self.drill(drills.o2_rollback_order)

    def test_m9_the_monitoring_function_reads_the_snapshot_and_nothing_else(self):
        """Review M9 design, on the disposable cluster only: migration 141 applied twice; the reader role can call the one
        function, cannot read any table, and gets the same picture as the SQL twin."""
        lab = self.lab
        lab.fresh([F.Tenant(n) for n in range(3)], 1)
        lab.drain(loops=2)
        migration = drills.ROOT / 'migrations/postriff/141_discord_ops_snapshot_reader.sql'
        for _ in range(2):
            done = drills.subprocess.run([str(drills.Path(F.PG_BIN) / 'psql'), lab.cluster.dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f',
                                          str(migration)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr[-800:])
        twin = lab.sql_twin()
        with lab.cluster.connect(autocommit=True) as db:
            db.execute('SET ROLE rafii_discord_ops_reader')
            snapshot = db.execute('SELECT public.pr_discord_ops_snapshot()').fetchone()[0]
            for table in ('pr_discord_request_admissions', 'pr_discord_rate_state', 'pr_discord_worker_projection',
                          'pr_encrypted_credentials', 'pr_oauth_transactions', 'pr_workspaces'):
                with self.subTest(table=table), self.assertRaises(drills.psycopg_errors().InsufficientPrivilege):
                    with db.transaction():
                        db.execute('SELECT 1 FROM public.%s LIMIT 1' % table)
        for path in (('queue', 'dueWorkspaces'), ('deliveries', 'accepted'), ('deliveries', 'creates'), ('unresolved', 'uncertainPublishes'),
                     ('coordinator', 'guards', 'policy', 'hold'), ('servers', 'used')):
            mine, theirs = snapshot, twin
            for key in path:
                mine, theirs = mine[key], theirs[key]
            self.assertEqual(mine, theirs, path)
        self.assertEqual((snapshot['kind'], snapshot['version'], snapshot['source']), ('rafii.discord.ops.health', 1, 'sql'))
        # Second review N-10: the catalog, not the file: definer rights, the empty search_path, and who may execute it
        # (superusers bypass privileges and are left out; the owner keeps EXECUTE).
        definer, settings = lab.sql("SELECT prosecdef, proconfig FROM pg_proc "
                                    "WHERE oid = 'public.pr_discord_ops_snapshot()'::regprocedure")[0]
        self.assertEqual((definer, settings), (True, ['search_path=""']))
        executors = sorted(name for (name,) in lab.sql(
            "SELECT rolname FROM pg_roles WHERE NOT rolsuper "
            "AND has_function_privilege(oid, 'public.pr_discord_ops_snapshot()'::regprocedure, 'EXECUTE')"))
        self.assertEqual(executors, ['rafii_discord_ops_projection', 'rafii_discord_ops_reader'])
        roles = dict(lab.sql("SELECT rolname, rolbypassrls OR rolsuper OR rolcanlogin FROM pg_roles "
                             "WHERE rolname IN ('rafii_discord_ops_projection', 'rafii_discord_ops_reader')"))
        self.assertEqual(roles, {'rafii_discord_ops_projection': False, 'rafii_discord_ops_reader': False})
        alerts = drills.check.evaluate(snapshot, drills.THRESHOLDS, now=lab.cluster.now(), phase='open')
        self.assertNotIn('SILENT_HALT_HEALTH_UNANSWERED', {a['id'] for a in alerts})

    def test_c1_the_drain_check_is_complete_above_five_thousand_workspaces(self):
        """Review C1 (exp_drain): with 5,201 workspaces carrying phase2 state and the one holding a live lease and a sealed
        post last by id, the sampled statement reported (0, 0, 0). The complete one reads the projection."""
        lab = self.lab
        lab.fresh()
        now = lab.cluster.now()
        live = {'phase2': {'jobs': [{'id': 'live-job', 'state': 'submitting', 'manifest': {'platform': 'Discord'},
                                     'leaseOwner': 'discord-lane-3-x', 'leaseUntil': now + 40, 'nextAt': now,
                                     'discordWorker': {'version': 1, 'stage': 'sealed'}}]}}
        with lab.cluster.connect(autocommit=True) as db:
            db.execute('SET session_replication_role = replica')    # idle workspaces only: no Discord work to project
            db.execute("INSERT INTO public.pr_workspaces(id, revision, state) SELECT gen_random_uuid(), 1, %s::jsonb "
                       "FROM generate_series(1, 5200)", (json.dumps({'phase2': {'jobs': []}}),))
            # the live one sorts last by id; its projection row is computed by the trigger's own function (the fence
            # trigger of migration 128 would refuse this synthetic job, which is why triggers are off for the insert)
            db.execute("INSERT INTO public.pr_workspaces(id, revision, state) VALUES ('ffffffff-ffff-4fff-8fff-ffffffffffff', 1, %s::jsonb)",
                       (json.dumps(live),))
            db.execute("SELECT public.pr_discord_projection_refresh(id, state, revision) FROM public.pr_workspaces "
                       "WHERE id = 'ffffffff-ffff-4fff-8fff-ffffffffffff'")
        started = time.monotonic()
        row = lab.named(drills.runbook_statements()['DRAIN_CHECK'])
        took = time.monotonic() - started
        self.assertEqual((row['live_leases'], row['sealed_now'], row['non_terminal_jobs']), (1, 1, 1))
        self.assertLess(took, 10)


if __name__ == '__main__':
    unittest.main()
