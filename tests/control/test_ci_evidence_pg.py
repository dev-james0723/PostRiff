"""Migration 071 and the CI ingest on a disposable PostgreSQL: what rafii_control_ingest may now write (CI manifests and
check rows, in its session environment only, verdict columns only), the constraints every writer meets, a further
reapplication over live rows, and the full path from a collector write through a NOINHERIT member login to a production
reader's 'checks_passed' (and back to 'suspected').

Skipped without RAFII_CONTROL_TEST_DSN. scripts/rafii_control_pg.py applies every founder migration from 054 on twice.
"""
import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from control.test_ci_evidence import M, OBSERVED, STATUSES_KEY, evaluate, load_routes, FakeGitHub
from rafii_control import ci_evidence
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'migrations/postriff/071_founder_engineering_evidence.sql'
SHA = 'f' * 40   # role-boundary rows; M is the collector scenario's tip
COLUMNS = ('id', 'environment', 'kind', 'provider', 'external_id', 'exact_sha', 'state', 'conclusion', 'failure_class', 'attested', 'required', 'observed_at')


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class CiEvidencePostgresTests(unittest.TestCase):
    def connect(self, role=None):
        con = psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None)
        self.addCleanup(con.close)
        if role:
            con.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
        return con

    def login(self, prefix, role, *, inherit):
        """A test-only login that is a member of `role` (NOINHERIT = SET only, the deployment shape)."""
        name = f'{prefix}_{uuid.uuid4().hex[:8]}'
        self.connect().execute(sql.SQL('CREATE ROLE {} LOGIN {} IN ROLE {}').format(sql.Identifier(name), sql.SQL('INHERIT' if inherit else 'NOINHERIT'), sql.Identifier(role)))

        def drop():
            with psycopg.connect(self.dsn, autocommit=True) as con:
                con.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(name)))
        self.addCleanup(drop)
        return name

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        if not self.connect().execute("SELECT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='rafii_control' AND tablename='github_check_snapshots' "
                                      "AND policyname='rc_github_ci_insert')").fetchone()[0]:
            self.skipTest('migration 071 not applied by this harness')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.engineering_evidence WHERE exact_sha=ANY(%s)', ([M, SHA],))
            con.execute('DELETE FROM rafii_control.github_check_snapshots WHERE exact_sha=ANY(%s)', ([M, SHA],))

    def read(self, path, login, environment):
        """One founder read through the restricted reader login, exactly as Control serves it."""
        factory = connection_factory(make_conninfo(self.dsn, user=login), 'rafii_control_reader', environment)
        principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['engineering.read']}, 'session': {'environment': environment}}
        return QueryService(PostgresStore(factory, factory, environment)).dispatch(path, {}, principal, str(uuid.uuid4()))

    # ---- 071 shape -----------------------------------------------------------------------------------------------------
    def test_071_relaxes_only_the_local_manifest_rule_and_keeps_the_role_split(self):
        owner = self.connect()
        checks = dict(owner.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='rafii_control.github_check_snapshots'::regclass "
                                    "AND contype='c'").fetchall())
        self.assertTrue({'rc_github_environment', 'rc_github_provenance', 'rc_github_ci_attested'} <= set(checks))
        self.assertFalse([name for name, definition in checks.items() if definition == "CHECK ((environment = 'local'::text))"], "052's local-only rule is gone")
        self.assertEqual(sum('provenance' in definition and 'ARRAY' in definition for definition in checks.values()), 1, 'one provenance list, not two')
        self.assertIn('rc_evidence_check_green', {row[0] for row in owner.execute("SELECT conname FROM pg_constraint WHERE conrelid='rafii_control.engineering_evidence'::regclass").fetchall()})
        self.assertEqual(tuple(owner.execute("SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname='rafii_control_ingest'").fetchone()), (False, False, False))
        for table in ('engineering_evidence', 'github_check_snapshots'):
            self.assertTrue(owner.execute('SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', ('rafii_control.' + table,)).fetchone()[0])

        def can(role, table, privilege):
            return owner.execute('SELECT has_table_privilege(%s,%s,%s)', (role, 'rafii_control.' + table, privilege)).fetchone()[0]
        self.assertTrue(can('rafii_control_ingest', 'engineering_evidence', 'INSERT'))
        for privilege in ('UPDATE', 'DELETE', 'TRUNCATE'):
            self.assertFalse(can('rafii_control_ingest', 'engineering_evidence', privilege), privilege)
            self.assertFalse(can('rafii_control_ingest', 'github_check_snapshots', privilege), privilege)
        updatable = {column for column in COLUMNS if owner.execute("SELECT has_column_privilege('rafii_control_ingest','rafii_control.engineering_evidence',%s,'UPDATE')", (column,)).fetchone()[0]}
        self.assertEqual(updatable, {'state', 'conclusion', 'failure_class', 'attested', 'observed_at'})
        for role in ('rafii_control_reader', 'rafii_control_session', 'anon', 'authenticated', 'service_role'):
            for table in ('engineering_evidence', 'github_check_snapshots'):
                self.assertFalse(can(role, table, 'INSERT') or can(role, table, 'UPDATE'), (role, table))
        members = [row[0] for row in owner.execute("SELECT m.rolname FROM pg_auth_members a JOIN pg_roles m ON m.oid=a.member WHERE a.roleid='rafii_control_ingest'::regrole").fetchall()]
        self.assertEqual([name for name in members if not name.startswith('ci_')], [], 'the migration grants no login or membership')

    def test_ingest_writes_only_ci_evidence_in_its_session_environment(self):
        owner, ingest = self.connect(), self.connect('rafii_control_ingest')
        ingest.execute("SELECT set_config('rafii_control.environment','production',false)")

        def evidence(con=ingest, **change):
            row = dict(id=str(uuid.uuid4()), environment='production', kind='check', provider='github', external_id=f'pg-071/{uuid.uuid4().hex}',
                       exact_sha=SHA, state='suspected', conclusion='success', failure_class=None, attested=True, required=True, observed_at='2026-10-01T10:00:00Z')
            row.update(change)
            con.execute(f"INSERT INTO rafii_control.engineering_evidence({','.join(COLUMNS)}) VALUES({','.join(['%s'] * len(COLUMNS))})", tuple(row[key] for key in COLUMNS))
            return row
        green = evidence(state='checks_passed')
        evidence(provider='vercel')
        for change in (dict(environment='staging'), dict(kind='error'), dict(kind='deployment'), dict(provider='sentry'), dict(provider='local')):
            with self.subTest(change=change), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                evidence(**change)
        for change in (dict(state='checks_passed', conclusion='failure'), dict(state='checks_passed', conclusion='skipped'),
                       dict(state='checks_passed', attested=False), dict(state='checks_passed', conclusion=None)):
            with self.subTest(change=change), self.assertRaises(psycopg.errors.CheckViolation):
                evidence(**change)
        self.assertEqual(ingest.execute("UPDATE rafii_control.engineering_evidence SET state='suspected', conclusion='failure', failure_class='unknown', "
                                        "attested=true, observed_at=now() WHERE id=%s", (green['id'],)).rowcount, 1)
        for statement, params in (('UPDATE rafii_control.engineering_evidence SET exact_sha=%s WHERE id=%s', ('b' * 40, green['id'])),
                                  ('UPDATE rafii_control.engineering_evidence SET required=false WHERE id=%s', (green['id'],)),
                                  ("UPDATE rafii_control.engineering_evidence SET provider='vercel' WHERE id=%s", (green['id'],)),
                                  ('DELETE FROM rafii_control.engineering_evidence WHERE id=%s', (green['id'],))):
            with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                ingest.execute(statement, params)
        staging = evidence(con=owner, environment='staging')
        self.assertEqual(ingest.execute("UPDATE rafii_control.engineering_evidence SET conclusion='failure' WHERE id=%s", (staging['id'],)).rowcount, 0)
        self.assertIsNone(ingest.execute('SELECT id FROM rafii_control.engineering_evidence WHERE id=%s', (staging['id'],)).fetchone())

        payload = {'schemaVersion': 2, 'adapterVersion': ci_evidence.ADAPTER_VERSION, 'provenance': 'ci_attested', 'exactSha': SHA}

        def manifest(con=ingest, environment='production', provenance='ci_attested', body=payload):
            con.execute('INSERT INTO rafii_control.github_check_snapshots(id,environment,source_request_id,exact_sha,provenance,observed_at,payload_digest,payload) '
                        'VALUES(%s,%s,%s,%s,%s,now(),%s,%s)', (str(uuid.uuid4()), environment, str(uuid.uuid4()), SHA, provenance, '0' * 64, Jsonb(body)))
        manifest()
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            manifest(environment='staging')
        with self.assertRaises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)):
            manifest(provenance='admitted_operational')
        for change in (dict(provenance='synthetic'), dict(provenance='provider_observed_test'), dict(body={**payload, 'exactSha': 'b' * 40}),
                       dict(body={**payload, 'schemaVersion': 1}), dict(body={**payload, 'adapterVersion': 'github-workflow/1'}),
                       dict(body={key: value for key, value in payload.items() if key != 'schemaVersion'}), dict(body={}), dict(environment='qa')):
            with self.subTest(change=change), self.assertRaises(psycopg.errors.CheckViolation):
                manifest(con=owner, **change)
        manifest(con=owner, environment='local', provenance='synthetic', body={'manual': True})   # local manual captures are unchanged
        for statement in ("UPDATE rafii_control.github_check_snapshots SET provenance='ci_attested' WHERE exact_sha=%s",
                          'DELETE FROM rafii_control.github_check_snapshots WHERE exact_sha=%s'):
            with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                ingest.execute(statement, (SHA,))
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','production',false)")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            evidence(con=reader)

    # ---- the collector end to end ------------------------------------------------------------------------------------
    def test_a_collector_write_reads_checks_passed_in_production_only_and_survives_reapplication(self):
        ingest_login = self.login('ci_ingest', 'rafii_control_ingest', inherit=False)
        reader_login = self.login('ci_reader', 'rafii_control_reader', inherit=True)
        dsn = make_conninfo(self.dsn, user=ingest_login)
        evaluation = evaluate()
        first = ci_evidence.write(dsn, 'production', evaluation)
        self.assertEqual(first['rows'], 5)
        self.assertIsNotNone(first['snapshot'])
        self.assertEqual(ci_evidence.write(dsn, 'production', dict(evaluation, observedAt='2026-10-01T10:20:00+00:00')), {'rows': 5, 'snapshot': None},
                         'an unchanged evaluation refreshes the rows and adds no manifest')
        owner = self.connect()
        self.assertEqual(owner.execute('SELECT count(*) FROM rafii_control.github_check_snapshots WHERE exact_sha=%s', (M,)).fetchone()[0], 1)
        rows = owner.execute("SELECT count(*), count(*) FILTER (WHERE state='checks_passed' AND attested), min(observed_at)=max(observed_at), "
                             "max(observed_at)='2026-10-01T10:20:00+00:00'::timestamptz FROM rafii_control.engineering_evidence WHERE exact_sha=%s", (M,)).fetchone()
        self.assertEqual(tuple(rows), (5, 5, True, True))

        result = self.read('/engineering', reader_login, 'production')
        mine = [row for row in result['evidence'] if row['exact_sha'] == M]
        self.assertEqual((len(mine), {row['state'] for row in mine}), (5, {'checks_passed'}))
        self.assertEqual((result['verdict']['sha'], result['verdict']['state'], result['verdict']['requiredCount']), (M, 'checks_passed', 5))
        checks = [entry for entry in self.read('/engineering/checks', reader_login, 'production')['snapshots'] if entry['exactSha'] == M]
        self.assertEqual([(entry['provenance'], entry['trusted'], entry['qualification']['requiredCount']) for entry in checks], [('ci_attested', True, 5)])
        self.assertEqual([row for row in self.read('/engineering', reader_login, 'staging')['evidence'] if row['exact_sha'] == M], [])

        # A third application of 071 over live rows keeps them and its rules.
        owner.execute(MIGRATION.read_text())
        self.assertEqual(owner.execute('SELECT count(*) FROM rafii_control.engineering_evidence WHERE exact_sha=%s', (M,)).fetchone()[0], 5)
        self.assertEqual(self.read('/engineering', reader_login, 'production')['verdict']['state'], 'checks_passed')

        # Vercel goes pending again (a redeploy): one row changes, a new manifest is recorded, production reads suspected.
        routes = load_routes()
        routes[STATUSES_KEY] = [dict(id=3009, state='pending', context='Vercel', creator={'login': 'vercel[bot]'})]
        self.assertIsNotNone(ci_evidence.write(dsn, 'production', evaluate(routes, observed='2026-10-01T10:30:00+00:00'))['snapshot'])
        result = self.read('/engineering', reader_login, 'production')
        vercel = next(row for row in result['evidence'] if row['external_id'] == f'ci/{M}/vercel/production')
        self.assertEqual((vercel['state'], vercel['attested'], vercel['conclusion']), ('suspected', False, None))
        self.assertEqual(result['verdict']['state'], 'suspected')
        others = [row for row in result['evidence'] if row['exact_sha'] == M and row['id'] != vercel['id']]
        self.assertTrue(len(others) == 4 and all(row['state'] == 'suspected' and row['observed_stage'] == 'checks_passed' for row in others))

        # The GitHub Actions entry point records the success again through the same login and prints no DSN.
        out = []
        environ = {'RAFII_ENGINEERING_INGEST_DSN': dsn, 'RAFII_ENGINEERING_ENVIRONMENT': 'production'}
        clock = lambda: datetime(2026, 10, 1, 10, 40, tzinfo=timezone.utc)   # noqa: E731 - after the pending manifest above
        self.assertEqual(ci_evidence.main(environ, client=FakeGitHub(load_routes()), clock=clock, out=out.append), 0, out)
        self.assertNotIn(ingest_login, '\n'.join(out))
        self.assertEqual(self.read('/engineering', reader_login, 'production')['verdict']['state'], 'checks_passed')

        # Refused: a privileged login, and a login that inherits the role instead of SET-only membership.
        with self.assertRaisesRegex(ci_evidence.IngestRefused, 'privileged'):
            ci_evidence.write(self.dsn, 'production', evaluation)
        inherits = self.login('ci_inherit', 'rafii_control_ingest', inherit=True)
        with self.assertRaisesRegex(ci_evidence.IngestRefused, 'NOINHERIT'):
            ci_evidence.write(make_conninfo(self.dsn, user=inherits), 'production', copy.deepcopy(evaluation))
        self.assertEqual(OBSERVED, evaluation['observedAt'])


if __name__ == '__main__':
    unittest.main()
