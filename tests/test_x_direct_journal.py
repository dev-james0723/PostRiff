"""Real disposable PostgreSQL concurrency tests; provider execution stays synthetic."""
import os
import unittest
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from postriff_alpha.domain import AlphaError
from postriff_phase2 import x_direct_journal as journal

DSN = os.environ.get('RAFII_X_TEST_DATABASE_DSN', '')


@unittest.skipUnless(DSN, 'Requires an explicitly supplied disposable local database')
class JournalPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        options = conninfo_to_dict(DSN)
        if not options.get('host', '').startswith('/tmp/rafii-x-g14-pg-'):
            raise RuntimeError('These tests only create databases in the dedicated local Unix-socket cluster')
        cls.psycopg = psycopg
        cls.database = 'x_operations_test_' + uuid.uuid4().hex[:12]
        cls.admin = psycopg.connect(DSN, autocommit=True)
        cls.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database)))
        cls.dsn = make_conninfo(DSN, dbname=cls.database)
        with psycopg.connect(cls.dsn) as db:
            db.execute("""DO $roles$ BEGIN
                IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
                IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
                IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF;
                END $roles$;
                CREATE TABLE public.pr_workspaces(id uuid PRIMARY KEY);
                CREATE TABLE public.pr_encrypted_credentials(
                  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id),
                  connection_id text NOT NULL, PRIMARY KEY(workspace_id,connection_id));""")
        with psycopg.connect(cls.dsn, autocommit=True) as db:
            db.execute(Path('migrations/postriff/132_x_direct_operations.sql').read_text())

    @classmethod
    def tearDownClass(cls):
        from psycopg import sql
        cls.admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database)))
        cls.admin.close()

    def setUp(self):
        self.workspace, self.foreign, self.actor = (str(uuid.uuid4()) for _ in range(3))
        # Fixed application clock must round-trip exactly through PostgreSQL's
        # microsecond timestamps; otherwise a frozen test instant can precede
        # the rounded next_at by a fraction of a microsecond.
        self.now = float(int(time.time()))
        with self.psycopg.connect(self.dsn) as db:
            db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s),(%s)', (self.workspace, self.foreign))
            db.execute('INSERT INTO public.pr_encrypted_credentials VALUES(%s,%s)', (self.workspace, 'connection'))

    def create(self, cur, **changes):
        args = dict(workspace=self.workspace, connection='connection', account='42', generation='consent-1',
                    actor=self.actor, operation_id='posts.create', request_key='stable_request_key_1',
                    request={'body':{'text':'Synthetic isolated journal test'},'normalizedFingerprint':'b'*64}, now=self.now)
        args.update(changes)
        return journal.create(cur, **args)

    def approved(self):
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            item = self.create(cur)
            return journal.approve(cur, self.workspace, item['id'], self.actor, item['digest'], True, self.now)

    def claim(self, operation, **changes):
        args = dict(generation='consent-1', account='42', authority=True, now=self.now)
        args.update(changes)
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (self.workspace,))
            return journal.claim(cur, self.workspace, operation, **args)

    def test_future_timestamp_does_not_dispatch_until_its_database_instant(self):
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            item = self.create(cur, request_key=uuid.uuid4().hex,
                request={'body': {'text': 'Scheduled fixture'}, 'scheduleAt': self.now + 60.0000007})
            item = journal.approve(cur, self.workspace, item['id'], self.actor, item['digest'], True, self.now)
        self.assertIsNone(self.claim(item['id'], now=self.now))
        self.assertIsNotNone(self.claim(item['id'], now=item['next_at']))

    def test_tenant_isolation_and_idempotency_conflict(self):
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            first = self.create(cur)
            self.assertEqual(self.create(cur)['id'], first['id'])
            with self.assertRaises(AlphaError):
                journal.read(cur, self.foreign, first['id'])
            with self.assertRaises(AlphaError):
                self.create(cur, request={'body': {'text': 'Changed approval content'}})

    def test_exact_approval_and_preview_expiry(self):
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            item = self.create(cur)
            for digest, confirmed, now in [('0' * 64, True, self.now),
                    (item['digest'], False, self.now), (item['digest'], True, self.now + 901)]:
                with self.assertRaises(AlphaError):
                    journal.approve(cur, self.workspace, item['id'], self.actor, digest, confirmed, now)

    def test_two_workers_get_one_durable_claim(self):
        item = self.approved()
        with ThreadPoolExecutor(max_workers=2) as workers:
            claims = list(workers.map(self.claim, [item['id'], item['id']]))
        self.assertEqual(sum(value is not None for value in claims), 1)
        self.assertEqual(next(value for value in claims if value)['attempts'], 1)

    def test_expired_write_lease_is_uncertain_and_never_retried(self):
        item = self.approved()
        self.assertIsNotNone(self.claim(item['id']))
        self.assertIsNone(self.claim(item['id'], now=self.now + 91))
        self.assertIsNone(self.claim(item['id'], now=self.now + 200))
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            stored = journal.read(cur, self.workspace, item['id'])
        self.assertEqual(stored['state'], 'uncertain')
        self.assertEqual(stored['attempts'], 1)

    def test_reconnect_and_removed_approver_hold_before_dispatch(self):
        for changes in ({'generation': 'consent-2'}, {'account': '99'}, {'authority': False}):
            with self.subTest(changes=changes):
                with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
                    item = self.create(cur, request_key=uuid.uuid4().hex)
                    journal.approve(cur, self.workspace, item['id'], self.actor, item['digest'], True, self.now)
                self.assertIsNone(self.claim(item['id'], **changes))
                with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
                    self.assertEqual(journal.read(cur, self.workspace, item['id'])['state'], 'held')

    def test_cancellation_prevents_scheduled_dispatch(self):
        item = self.approved()
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            self.assertEqual(journal.cancel(cur, self.workspace, item['id'], self.now)['state'], 'canceled')
        self.assertIsNone(self.claim(item['id']))

    def test_success_requires_receipt_and_stale_lease_cannot_finish(self):
        item = self.approved()
        claim = self.claim(item['id'])
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            with self.assertRaises(ValueError):
                journal.finish(cur, claim, state='verified', now=self.now)
            stale = {**claim, 'lease_id': str(uuid.uuid4())}
            self.assertIsNone(journal.finish(cur, stale, state='failed', now=self.now))
            done = journal.finish(cur, claim, state='uncertain', now=self.now,
                                  reason_code='synthetic_timeout', reason='Synthetic transport timeout')
            self.assertEqual(done['state'], 'uncertain')
            self.assertEqual(done['receipts'], [])

    def test_browser_database_roles_cannot_read_operation_rows(self):
        item = self.approved()
        with self.psycopg.connect(self.dsn) as db, db.cursor() as cur:
            cur.execute('SET LOCAL ROLE authenticated')
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                journal.read(cur, self.workspace, item['id'])

if __name__ == '__main__':
    unittest.main()
