"""Migration 133 must fail safely under PostgreSQL lock contention; never touch production.

Only permitted when the exact test harness supplies its disposable UNIX-socket DSN.
"""
from __future__ import annotations

import os
import re
import time
import unittest
from pathlib import Path
from uuid import uuid4

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations' / 'postriff'
DSN = os.environ.get('RAFII_X_TEST_DATABASE_DSN', '')


class XMigration133Static(unittest.TestCase):
    def test_bounded_local_postgres_lock_and_statement_timeout(self):
        sql = (MIGRATIONS / '133_x_cost_approval_grants.sql').read_text()
        self.assertRegex(sql, r'(?im)^BEGIN;\s*SET LOCAL lock_timeout\s*=\s*\'5s\';')
        self.assertRegex(sql, r'(?im)^SET LOCAL statement_timeout\s*=\s*\'120s\';')
        self.assertLess(sql.index('SET LOCAL lock_timeout'), sql.index('LOCK TABLE'))
        self.assertLess(sql.index('SET LOCAL statement_timeout'), sql.index('LOCK TABLE'))
        self.assertRegex(sql, r'(?im)^COMMIT;\s*$')


@unittest.skipUnless(DSN, 'Requires explicit local X disposable PostgreSQL DSN')
class XMigration133Postgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        opts = conninfo_to_dict(DSN)
        if not re.fullmatch(r'/tmp/rafii-x-g14-pg-[A-Za-z0-9_-]+/socket', opts.get('host', '')) or opts.get('hostaddr'):
            raise RuntimeError('X migration lock test must use the dedicated local UNIX-socket test cluster')
        cls.psycopg, cls.sql = psycopg, sql
        cls.admin = psycopg.connect(DSN, autocommit=True)
        cls.name = 'x_migration133_lock_' + uuid4().hex[:12]
        cls.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.database = make_conninfo(DSN, dbname=cls.name)
        with psycopg.connect(cls.database, autocommit=True) as db:
            db.execute((MIGRATIONS / '131_x_direct_cost.sql').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(cls.sql.SQL('DROP DATABASE {}').format(cls.sql.Identifier(cls.name)))
        cls.admin.close()

    def test_contended_migration_fails_closed_then_applies_after_unlock(self):
        text = (MIGRATIONS / '133_x_cost_approval_grants.sql').read_text()
        with self.psycopg.connect(self.database) as holder:
            holder.execute('SELECT count(*) FROM postriff.x_cost_windows')  # ACCESS SHARE until holder commits
            started = time.monotonic()
            with self.psycopg.connect(self.database, autocommit=True) as migrator:
                with self.assertRaises(self.psycopg.errors.LockNotAvailable):
                    migrator.execute(text)
            elapsed = time.monotonic() - started
            self.assertGreater(elapsed, 4.0)
            self.assertLess(elapsed, 9.0, 'An unbounded migration wait is unacceptable for live rollout')
            with self.psycopg.connect(self.database) as witness:
                self.assertIsNone(witness.execute("SELECT to_regclass('postriff.x_cost_grants')").fetchone()[0])
            holder.commit()
        with self.psycopg.connect(self.database, autocommit=True) as migrator:
            migrator.execute(text)
            self.assertIsNotNone(migrator.execute("SELECT to_regclass('postriff.x_cost_grants')").fetchone()[0])
            self.assertEqual(migrator.execute('SELECT count(*) FROM postriff.x_cost_app_activation').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
