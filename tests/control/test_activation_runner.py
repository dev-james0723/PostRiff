"""Pinned activation runner regressions. Database cases use only the disposable Control harness."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import psycopg

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'docs/releases/founder-admin-2026-10-01/activate_founder.py'
SPEC = importlib.util.spec_from_file_location('founder_activation_under_test', SCRIPT)
activation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activation)


class ActivationSourceTests(unittest.TestCase):
    def test_all_migration_bytes_match_the_reviewed_pins(self):
        self.assertEqual(len(activation.checked(activation.PARITY + activation.FOUNDER)), 23)

    def test_hosted_target_rejects_the_other_project_before_connecting(self):
        args = type('Args', (), {'rehearsal': False})()
        with self.assertRaises(activation.Refused):
            activation.target(args, {'VERCEL_PROJECT_ID': activation.VERCEL_PROJECT, 'VERCEL_ENV': 'production',
                                    'POSTRIFF_DATABASE_URL': 'host=db.oxacvkhpfgytkepxcaqh.supabase.co dbname=postgres'})


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable Control PostgreSQL DSN required')
class FounderEnrollmentPostgresTests(unittest.TestCase):
    def setUp(self):
        self.con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'])
        self.addCleanup(self.con.close)
        self.addCleanup(self.con.rollback)
        self.founder, self.other = uuid.uuid4(), uuid.uuid4()
        self.con.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)', (self.founder, self.other))
        self.environment = 'staging'
        self.record_refusal(self.founder)

    def record_refusal(self, actor, *, minutes_ago=0):
        self.con.execute("INSERT INTO rafii_control.admin_audit_log(request_id,actor,environment,action,result,error_code,occurred_at) "
                         "VALUES(%s,%s,%s,'session.exchange','denied','FOUNDER_REQUIRED',now()-(%s * interval '1 minute'))",
                         (uuid.uuid4(), actor, self.environment, minutes_ago))

    def run_enrollment(self, expected=None):
        env = {} if expected is None else {'FOUNDER_EXPECTED_USER_ID': str(expected)}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()):
            activation.enroll(self.con, self.environment)

    def operator_count(self):
        return self.con.execute('SELECT count(*) FROM rafii_control.platform_operators WHERE user_id=ANY(%s)',
                                ([self.founder, self.other],)).fetchone()[0]

    def test_a_recent_refusal_is_not_itself_founder_authorization(self):
        with self.assertRaises(activation.Refused):
            self.run_enrollment()
        self.assertEqual(self.operator_count(), 0)

    def test_malformed_explicit_identity_cannot_enroll_anyone(self):
        for value in ('not-a-uuid', '00000000-0000-0000-0000-000000000000', ' '):
            with self.subTest(value=value), self.assertRaises(activation.Refused):
                self.run_enrollment(value)
        self.assertEqual(self.operator_count(), 0)

    def test_refused_identity_must_equal_the_separately_verified_founder(self):
        with self.assertRaises(activation.Refused):
            self.run_enrollment(self.other)
        self.assertEqual(self.operator_count(), 0)

    def test_matching_identity_is_idempotent_and_does_not_create_a_session(self):
        self.run_enrollment(self.founder)
        self.run_enrollment(self.founder)
        row = self.con.execute('SELECT role,status,capabilities FROM rafii_control.platform_operators WHERE user_id=%s AND environment=%s',
                               (self.founder, self.environment)).fetchone()
        self.assertEqual(row[:2], ('founder', 'active'))
        self.assertEqual(set(row[2]), set(activation.CAPABILITIES))
        self.assertEqual(self.operator_count(), 1)
        self.assertEqual(self.con.execute('SELECT count(*) FROM rafii_control.founder_sessions WHERE user_id=%s', (self.founder,)).fetchone()[0], 0)

    def test_ambiguous_refusals_never_pick_the_first_identity(self):
        self.record_refusal(self.other)
        with self.assertRaises(activation.Refused):
            self.run_enrollment(self.founder)
        self.assertEqual(self.operator_count(), 0)

    def test_existing_other_founder_is_never_replaced(self):
        self.con.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status) VALUES(%s,%s,'founder','active')",
                         (self.other, self.environment))
        with self.assertRaises(activation.Refused):
            self.run_enrollment(self.founder)
        self.assertEqual(self.operator_count(), 1)

    def test_revoked_founder_is_not_silently_reactivated(self):
        self.con.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status) VALUES(%s,%s,'founder','revoked')",
                         (self.founder, self.environment))
        with self.assertRaises(activation.Refused):
            self.run_enrollment(self.founder)
        self.assertEqual(self.con.execute('SELECT status FROM rafii_control.platform_operators WHERE user_id=%s AND environment=%s',
                                         (self.founder, self.environment)).fetchone()[0], 'revoked')
