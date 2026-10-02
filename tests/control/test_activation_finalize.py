"""Release-only finalizer tests; all database effects roll back in the disposable harness."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'docs/releases/founder-admin-2026-10-01/finalize_founder.py'


def load():
    if not SCRIPT.is_file():
        raise AssertionError('The pinned migration-071 finalizer is missing')
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('finalize_founder_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FinalizerSourceTests(unittest.TestCase):
    def test_071_is_pinned_separately_without_changing_the_original_twenty(self):
        m = load()
        self.assertEqual(len(m.a.FOUNDER), 20)
        self.assertEqual(m.a.checked(m.EVIDENCE)[0][0], '071_founder_engineering_evidence.sql')

    def test_default_mode_is_read_only(self):
        self.assertEqual(load().arguments([]).mode, 'probe')


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable PostgreSQL required')
class FinalizerPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.m = load()
        self.con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], prepare_threshold=None)
        self.addCleanup(self.con.close)
        self.addCleanup(self.con.rollback)
        self.con.execute('CREATE SCHEMA IF NOT EXISTS postriff_private')
        self.con.execute('CREATE TABLE IF NOT EXISTS postriff_private.schema_migrations(name text primary key,sha256 text not null)')
        for name, sha in self.m.a.FOUNDER + self.m.a.PARITY:
            self.con.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s) ON CONFLICT(name) DO UPDATE SET sha256=excluded.sha256', (name, sha))

    def test_evidence_apply_is_idempotent_and_records_the_exact_pin(self):
        self.assertTrue(self.m.apply_evidence(self.con, 'local'))
        self.assertFalse(self.m.apply_evidence(self.con, 'local'))
        self.assertEqual(self.con.execute('SELECT sha256 FROM postriff_private.schema_migrations WHERE name=%s', (self.m.EVIDENCE[0][0],)).fetchone()[0], self.m.EVIDENCE[0][1])
        self.assertTrue(self.m.verify_evidence(self.con.cursor()))

    def test_checksum_drift_is_rejected_not_adopted(self):
        name = self.m.EVIDENCE[0][0]
        self.con.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)', (name, '0' * 64))
        with self.assertRaises(self.m.a.Refused):
            self.m.apply_evidence(self.con, 'local')
        self.assertEqual(self.con.execute('SELECT sha256 FROM postriff_private.schema_migrations WHERE name=%s', (name,)).fetchone()[0], '0' * 64)

    def test_evidence_migration_does_not_grant_browser_or_session_writes(self):
        self.m.apply_evidence(self.con, 'local')
        for role in ('anon', 'authenticated', 'rafii_control_session', 'rafii_control_reader'):
            for table in ('engineering_evidence', 'github_check_snapshots'):
                self.assertFalse(self.con.execute('SELECT has_table_privilege(%s,%s,\'INSERT,UPDATE,DELETE,TRUNCATE\')', (role, 'rafii_control.' + table)).fetchone()[0])

    def test_ingest_login_has_only_its_exact_set_only_role(self):
        import base64
        salt = base64.b64encode(bytes(range(16))).decode()
        key = base64.b64encode(bytes(range(32))).decode()
        verifier = f'SCRAM-SHA-256$4096:{salt}${key}:{key}'
        self.m.provision_ingest(self.con, verifier)
        row = self.con.execute('SELECT rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication FROM pg_roles WHERE rolname=%s', (self.m.INGEST_LOGIN,)).fetchone()
        self.assertEqual(tuple(row), (True, False, False, False, False, False, False))
        members = self.con.execute('SELECT r.rolname,m.inherit_option,m.set_option FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE m.member=%s::regrole', (self.m.INGEST_LOGIN,)).fetchall()
        self.assertEqual(members, [('rafii_control_ingest', False, True)])
        self.assertFalse(self.con.execute('SELECT has_schema_privilege(%s,\'rafii_control\',\'USAGE\')', (self.m.INGEST_LOGIN,)).fetchone()[0])

    def test_invalid_verifier_does_not_create_a_login(self):
        with self.assertRaises(self.m.a.Refused):
            self.m.provision_ingest(self.con, 'not-a-verifier')
        self.assertFalse(self.con.execute('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)', (self.m.INGEST_LOGIN,)).fetchone()[0])
