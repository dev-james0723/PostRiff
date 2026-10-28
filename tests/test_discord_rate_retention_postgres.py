"""Real-PostgreSQL proof of the retention of the shared request coordinator's admissions (B3).

Every request writes a row to pr_discord_request_admissions and nothing used to delete it: 3.7 to 6.5 KB per admission, 8 to
14 GB a day at the reviewed 25 a second. SharedPostgresBudget.purge_settled() deletes the rows the coordinator can no longer
count: a settled (observed, blocked) admission that is not a publication after an hour, a settled publication after a day.
It never touches an unresolved row (sent, uncertain, reserved, sealed), the scope rows (windows, embargoes, circuits) or the
application row, and it works in bounded batches that skip rows another caller holds.

A disposable cluster from tests/discord_lane_fixture.py plus migration 142 (the partial index the purge walks; written, not
applied anywhere). Runs where POSTRIFF_PG_BIN names the PostgreSQL server binaries; reads no credential and touches no other
database. Set POSTRIFF_RETENTION_ROWS=1000000 for the million-row timing (about 2 GB of disk for a few minutes); the default
is 200,000. Synthetic ids only.
"""
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import discord_lane_fixture as F
from postriff_phase2.discord import lane as discord_lane, ops
from postriff_phase2.discord.rate_limits import RateDelayed, RequestIdentity, SharedPostgresBudget

ADMISSIONS = 'public.pr_discord_request_admissions'
MIGRATION = F.ROOT / 'migrations/postriff/142_discord_admission_retention_index.sql'
ROLLBACK = F.ROOT / 'migrations/postriff/142_discord_admission_retention_index.rollback.sql'
HOUR, DAY = 3600, 86400
ROWS = int(os.environ.get('POSTRIFF_RETENTION_ROWS', '200000'))

# One admission row, every column the table checks. Reads are sent when admitted; a publication is a bound POST with an intent.
INSERT = f'''INSERT INTO {ADMISSIONS}(id,application_key,auth_key,credential_key,credential_kind,method,path_key,route_key,major_key,
    bucket_key,scope_keys,is_publish,binding_hash,workspace_id,publication_id,manifest_digest,authorization_digest,approval_digest,
    worker_key,lease_key,channel_key,intent_id,state,reserved_at,expires_at,sealed_at,sent_at,outcome_at,status_code,rate_scope)
SELECT {{columns}} FROM generate_series(1,%(n)s) g'''
HEX = "encode(sha256(convert_to(%(tag)s||':'||{part}||g::text,'UTF8')),'hex')"


def digest(part):
    return HEX.format(part=part)


def bulk_sql(publish, state):
    """The SELECT list for `n` rows. ages run from %(oldest)s seconds ago (g=1) to %(newest)s seconds ago (g=n); settled rows
    were settled %(settled)s seconds after they were reserved (NULL: never)."""
    reserved = ("clock_timestamp()-make_interval(secs=>%(oldest)s::double precision"
                "-(%(oldest)s::double precision-%(newest)s::double precision)*g/%(n)s::double precision)")
    sealed = f"({reserved})+interval '1 second'" if publish and state != 'reserved' else 'NULL'
    sent = f"({reserved})+interval '2 seconds'" if state in ('sent', 'observed', 'uncertain') else 'NULL'
    outcome = f"({reserved})+make_interval(secs=>%(settled)s)" if state in ('observed', 'blocked') else 'NULL'
    columns = [
        'gen_random_uuid()', '%(app)s', digest("'auth'"), digest("'credential'"), "'bot'", "'POST'" if publish else "'GET'",
        digest("'path'"), digest("'route'"), digest("'major'||(g%%1000)::text"), 'NULL',
        "ARRAY['00:'||%(app)s,'10:'||" + digest("'auth'") + ",'11:'||" + digest("'credential'") + ",'20:'||" + digest("'egress'")
        + ",'40:'||" + digest("'major'||(g%%1000)::text") + ",'50:'||" + digest("'route'||(g%%1000)::text") + "]",
        'true' if publish else 'false',
        digest("'binding'") if publish else 'NULL',
        "'00000000-0000-4000-8000-000000000001'::uuid" if publish else 'NULL',
        "'pub-'||%(tag)s||g::text" if publish else 'NULL',
        digest("'manifest'") if publish else 'NULL', digest("'authorization'") if publish else 'NULL',
        digest("'approval'") if publish else 'NULL', digest("'worker'") if publish else 'NULL',
        digest("'lease'") if publish else 'NULL', digest("'channel'") if publish else 'NULL',
        "'intent-'||%(tag)s||g::text" if publish and state != 'reserved' else 'NULL',
        f"'{state}'", reserved, f"({reserved})+interval '10 seconds'", sealed, sent, outcome,
        '200' if state == 'observed' else 'NULL', 'NULL']
    return ',\n    '.join(columns)


def application_key(application):
    return hashlib.sha256(application.encode()).hexdigest()


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class Retention(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()
        cls.psql(MIGRATION)

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    @classmethod
    def psql(cls, script):
        done = subprocess.run([str(Path(F.PG_BIN) / 'psql'), cls.cluster.dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f', str(script)],
                              cwd=script.parent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if done.returncode:
            raise RuntimeError(f'{script.name} failed: {done.stderr.strip()[-2000:]}')

    def setUp(self):
        self.cluster.reset()
        self.app = '8%017d' % (int(time.time() * 1000) % 10**11 * 1000 + uuid.uuid4().int % 1000)
        self.key = application_key(self.app)
        self.limiter = SharedPostgresBudget(self.cluster.factory(), self.app, policy=F.policy(self.cluster.now(), capacity=25))

    def add(self, count, *, state='observed', publish=False, oldest=2 * HOUR, newest=None, settled=1.0, app=None, tag=None):
        newest = oldest if newest is None else newest
        with self.cluster.connect(autocommit=True) as db:
            db.execute(INSERT.format(columns=bulk_sql(publish, state)),
                       {'n': count, 'app': app or self.key, 'oldest': oldest, 'newest': newest, 'settled': settled,
                        'tag': tag or uuid.uuid4().hex})

    def one(self, **options):
        """One row; its id is returned."""
        self.add(1, **options)
        with self.cluster.connect(autocommit=True) as db:
            return db.execute(f'SELECT id FROM {ADMISSIONS} ORDER BY request_seq DESC LIMIT 1').fetchone()[0]

    def ids(self):
        with self.cluster.connect(autocommit=True) as db:
            return {row[0] for row in db.execute(f'SELECT id FROM {ADMISSIONS}').fetchall()}

    def count(self, where='true'):
        with self.cluster.connect(autocommit=True) as db:
            return db.execute(f'SELECT count(*) FROM {ADMISSIONS} WHERE {where}').fetchone()[0]

    # --- what is deleted and what never is --------------------------------------------------------------------------

    def test_it_deletes_exactly_what_the_coordinator_no_longer_counts(self):
        gone = {
            'a read answered two hours ago': self.one(),
            'a read blocked unsent two hours ago': self.one(state='blocked'),
            'a settled publication past a day': self.one(publish=True, oldest=25 * HOUR),
            'a blocked publication past a day': self.one(publish=True, state='blocked', oldest=25 * HOUR),
        }
        kept = {
            'a read answered half an hour ago': self.one(oldest=HOUR // 2),
            'a read sent and never answered, two hours ago': self.one(state='sent'),
            'a read sent and never answered, three days ago': self.one(state='sent', oldest=3 * DAY),
            'a write whose outcome is unknown': self.one(state='uncertain', oldest=3 * DAY),
            'a reserved permit, two hours old': self.one(state='reserved'),
            'a settled publication inside a day': self.one(publish=True, oldest=3 * HOUR),
            'a publication whose create is uncertain, 100 hours ago': self.one(publish=True, state='uncertain', oldest=100 * HOUR),
            'a sealed publication, 100 hours ago': self.one(publish=True, state='sealed', oldest=100 * HOUR),
            'another application\'s settled read': self.one(app=application_key('8123456789012345678')),
            'a read reserved long ago and settled a minute ago': self.one(oldest=5 * HOUR, settled=5 * HOUR - 60),
        }
        outcome = self.limiter.purge_settled()
        self.assertEqual((outcome['status'], outcome['reads'], outcome['publications']), ('ok', 2, 2))
        remaining = self.ids()
        for what, row in gone.items():
            self.assertNotIn(row, remaining, what)
        for what, row in kept.items():
            self.assertIn(row, remaining, what)
        again = self.limiter.purge_settled()
        self.assertEqual((again['status'], again['reads'], again['publications'], again['more']), ('ok', 0, 0, False),
                         'idempotent: a second call finds nothing')
        self.assertEqual(self.ids(), remaining)

    def test_it_deletes_in_bounded_batches_oldest_first(self):
        self.add(5000, oldest=10 * HOUR, newest=2 * HOUR)
        with patch.object(SharedPostgresBudget, 'PURGE_BATCH', 2000), patch.object(SharedPostgresBudget, 'PURGE_ROUNDS', 1):
            counts = []
            for _ in range(4):
                outcome = self.limiter.purge_settled()
                counts.append((outcome['reads'], outcome['more']))
        self.assertEqual(counts, [(2000, True), (2000, True), (1000, False), (0, False)])
        self.assertEqual(self.count(), 0)
        self.add(3000, oldest=10 * HOUR, newest=2 * HOUR)
        with patch.object(SharedPostgresBudget, 'PURGE_BATCH', 1000), patch.object(SharedPostgresBudget, 'PURGE_ROUNDS', 1):
            self.limiter.purge_settled()
        with self.cluster.connect(autocommit=True) as db:
            (youngest_gone,) = db.execute(f'SELECT count(*) FROM {ADMISSIONS} WHERE reserved_at<clock_timestamp()-make_interval(secs=>%s)',
                                          (10 * HOUR - (10 * HOUR - 2 * HOUR) // 3 + 60,)).fetchone()
        self.assertEqual(youngest_gone, 0, 'the oldest third went, so nothing older than the cut is left')
        self.assertEqual(self.count(), 2000)

    def test_a_call_runs_a_few_rounds_and_says_when_more_is_left(self):
        self.add(2500, oldest=10 * HOUR, newest=2 * HOUR)
        with patch.object(SharedPostgresBudget, 'PURGE_BATCH', 1000), patch.object(SharedPostgresBudget, 'PURGE_ROUNDS', 2):
            outcome = self.limiter.purge_settled()
        self.assertEqual((outcome['reads'], outcome['rounds'], outcome['more']), (2000, 2, True))
        with patch.object(SharedPostgresBudget, 'PURGE_BATCH', 1000), patch.object(SharedPostgresBudget, 'PURGE_ROUNDS', 2):
            outcome = self.limiter.purge_settled()
        self.assertEqual((outcome['reads'], outcome['rounds'], outcome['more']), (500, 1, False))

    # --- concurrency ------------------------------------------------------------------------------------------------

    def test_concurrent_callers_delete_each_row_once_and_none_of_them_fails(self):
        self.add(6000, oldest=10 * HOUR, newest=2 * HOUR)
        self.add(500, state='sent', oldest=10 * HOUR)
        results, errors, start = [], [], threading.Barrier(8, timeout=30)

        def work():
            try:
                start.wait()
                for _ in range(6):
                    results.append(self.limiter.purge_settled())
            except BaseException as error:
                errors.append(error)
        threads = [threading.Thread(target=work) for _ in range(8)]
        with patch.object(SharedPostgresBudget, 'PURGE_BATCH', 500), patch.object(SharedPostgresBudget, 'PURGE_ROUNDS', 1):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(120)
            while self.limiter.purge_settled()['more']:
                pass
        self.assertEqual(errors, [])
        self.assertEqual({result['status'] for result in results} - {'ok', 'busy'}, set(), 'no timeout, deadlock or error')
        self.assertEqual((self.count("state='observed'"), self.count("state='sent'")), (0, 500), 'all went, and nothing else was touched')

    def test_it_never_waits_for_the_application_row_and_a_purge_in_flight_never_blocks_a_reservation(self):
        self.add(3000, oldest=10 * HOUR, newest=2 * HOUR)
        identity = RequestIdentity.make(self.app, 'bot', 'synthetic-bot-token')
        self.limiter.observe(self.limiter.reserve_read('GET', '/guilds/710000000000000001', identity=identity),
                             {'status': 200, 'headers': {}, 'body': {}})            # the application row exists
        with self.cluster.connect() as holder:
            holder.execute("SELECT 1 FROM public.pr_discord_rate_state WHERE kind='policy' FOR UPDATE")   # a reservation's lock
            began = time.monotonic()
            outcome = self.limiter.purge_settled()
            took = time.monotonic() - began
            holder.rollback()
        self.assertEqual(outcome['status'], 'ok')
        self.assertGreater(outcome['reads'], 0)
        self.assertLess(took, 2.0, 'the purge did not queue behind the application row (lock_timeout is 1 s)')
        # And the other way: an open purge transaction holds row locks on old settled rows only.
        self.add(3000, oldest=10 * HOUR, newest=2 * HOUR)
        with self.cluster.connect() as purger:
            purger.execute(f'''DELETE FROM {ADMISSIONS} WHERE request_seq IN (SELECT request_seq FROM {ADMISSIONS}
                WHERE state='observed' AND reserved_at<clock_timestamp()-interval '1 hour' ORDER BY reserved_at LIMIT 2000
                FOR UPDATE SKIP LOCKED)''')
            began = time.monotonic()
            for number in range(5):
                permit = self.limiter.reserve_read('GET', '/guilds/71000000000000010%d' % number, identity=identity)
                self.limiter.observe(permit, {'status': 200, 'headers': {}, 'body': {}})
            self.assertLess(time.monotonic() - began, 2.0, 'reservations ran while a purge transaction was open')
            purger.rollback()

    def test_live_reservations_keep_the_ceiling_while_the_purge_runs_flat_out(self):
        self.add(30000, oldest=12 * HOUR, newest=2 * HOUR)
        capacity = 25
        tenants = [F.Tenant(n) for n in range(10)]
        wire = F.MockDiscord(tenants, ceiling=capacity)
        provider = F.DiscordProvider(self.app, 'synthetic-secret', 'synthetic-bot-token', 'https://rafii.example.invalid',
                                     transport=wire, production_reviewed=True)
        provider.authorization_v2_enabled = provider.connections_v2_enabled = provider.rate_v1_enabled = True
        provider.rate_limiter = self.limiter
        stop, errors, admitted, purged = threading.Event(), [], [], []

        def reserve(number):
            try:
                while not stop.is_set():
                    try:
                        provider._bot('GET', '/guilds/' + tenants[number % len(tenants)].guild)
                        admitted.append(1)
                    except RateDelayed:
                        time.sleep(.02)
            except BaseException as error:
                errors.append(error)

        def purge():
            try:
                while not stop.is_set():
                    purged.append(self.limiter.purge_settled())
                    time.sleep(.01)
            except BaseException as error:
                errors.append(error)
        threads = [threading.Thread(target=reserve, args=(n,)) for n in range(6)] + [threading.Thread(target=purge)]
        for thread in threads:
            thread.start()
        time.sleep(6)
        stop.set()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(wire.over_ceiling, 0, 'the mock never saw more than %d in a trailing second' % capacity)
        self.assertGreater(len(admitted), 50, 'the coordinator kept admitting while the purge ran')
        self.assertEqual({result['status'] for result in purged} - {'ok', 'busy'}, set())
        self.assertGreater(sum(result['reads'] for result in purged), 20000, 'and the purge made its progress')

    # --- nothing the coordinator counts is lost -------------------------------------------------------------------

    def test_nothing_the_coordinator_counts_is_lost(self):
        identity = RequestIdentity.make(self.app, 'bot', 'synthetic-bot-token')
        # History first: request_seq runs in time order, as it does in production, and the window reads the newest rows.
        self.add(4000, oldest=20 * HOUR, newest=2 * HOUR)
        self.add(500, publish=True, oldest=100 * HOUR, newest=25 * HOUR)
        old_unanswered = self.one(state='sent', oldest=3 * HOUR)
        old_uncertain_write = self.one(state='uncertain', oldest=3 * HOUR)
        publication = self.one(publish=True, state='uncertain', oldest=100 * HOUR)
        sealed = self.one(publish=True, state='sealed', oldest=100 * HOUR)
        for number in range(4):                                              # live admissions inside the window
            self.limiter.observe(self.limiter.reserve_read('GET', '/guilds/72000000000000000%d' % number, identity=identity),
                                 {'status': 200, 'headers': {}, 'body': {}})
        self.limiter.observe(self.limiter.reserve_read('GET', '/guilds/720000000000000010/channels', identity=identity),
                             {'status': 403, 'headers': {}})                    # a circuit on that route
        unanswered_young = self.limiter.reserve_read('GET', '/guilds/720000000000000020', identity=identity)   # sent, never answered

        with self.cluster.connect(autocommit=True) as db:   # one fixed instant, just after the last live admission
            at = float(db.execute(f"SELECT extract(epoch from max(reserved_at)) FROM {ADMISSIONS} "
                                  "WHERE reserved_at>clock_timestamp()-interval '1 hour'").fetchone()[0]) + .05

        def readings():
            with self.cluster.connect(autocommit=True) as db, db.cursor() as cur:
                now, window = self.limiter._window_state(cur, 25, 1.0, at)
                cur.execute('SELECT scope_key,kind,limit_count,remaining,blocked_until,circuit_until,error_streak,manual_hold,'
                            'observation_seq,policy_revision FROM public.pr_discord_rate_state ORDER BY scope_key')
                scopes = cur.fetchall()
                cur.execute(f"SELECT id,state,intent_id FROM {ADMISSIONS} WHERE state NOT IN ('observed','blocked') ORDER BY request_seq")
                unresolved = cur.fetchall()
            return window['held'], window['occupied'], scopes, unresolved
        before = readings()
        outcome = self.limiter.purge_settled()
        while outcome['more']:
            outcome = self.limiter.purge_settled()
        after = readings()
        self.assertGreater(self.count("state='observed'"), 0, 'recent settled rows stay')
        self.assertEqual(len(before[1]), 6, 'the five answered and the one unanswered request occupy the window at that instant')
        self.assertEqual(after[0], before[0], 'the slots the window holds for permits and unanswered requests')
        self.assertEqual(after[1], before[1], 'the slots the window occupies, wire time for wire time')
        self.assertEqual(after[2], before[2], 'windows, embargoes, circuits and holds are untouched, byte for byte')
        self.assertEqual(after[3], before[3], 'every unresolved admission, with its intent, is still there')
        self.assertTrue({old_unanswered, old_uncertain_write, publication, sealed} <= self.ids())
        with self.cluster.connect(autocommit=True) as db:
            duplicate = db.execute(f"SELECT workspace_id,publication_id,intent_id FROM {ADMISSIONS} WHERE id=%s", (publication,)).fetchone()
            with self.assertRaises(Exception) as caught:
                db.execute(f'''INSERT INTO {ADMISSIONS}(id,application_key,auth_key,credential_key,credential_kind,method,path_key,
                    route_key,major_key,scope_keys,is_publish,binding_hash,workspace_id,publication_id,manifest_digest,
                    authorization_digest,approval_digest,worker_key,lease_key,channel_key,intent_id,state,expires_at)
                    SELECT gen_random_uuid(),application_key,auth_key,credential_key,credential_kind,method,path_key,route_key,
                    major_key,scope_keys,true,%s,workspace_id,publication_id,manifest_digest,authorization_digest,approval_digest,
                    worker_key,lease_key,channel_key,intent_id,'sealed',clock_timestamp()+interval '10 seconds'
                    FROM {ADMISSIONS} WHERE id=%s''', (hashlib.sha256(b'another binding').hexdigest(), publication))
        self.assertIn('unique', str(caught.exception).lower(), 'the intent of an unresolved publication still blocks a second admission')
        self.assertIsNotNone(duplicate)
        self.assertIsNotNone(unanswered_young)

    # --- a role that cannot delete ---------------------------------------------------------------------------------

    def test_a_role_without_delete_gets_a_quiet_denial_and_the_lane_goes_on(self):
        self.add(10, oldest=5 * HOUR)
        with self.cluster.connect(autocommit=True) as db:
            db.execute('ALTER ROLE service_role LOGIN')

        def as_service_role():
            return F.psycopg.connect(F.psycopg.conninfo.make_conninfo(self.cluster.dsn, user='service_role'), prepare_threshold=None)
        limiter = SharedPostgresBudget(as_service_role, self.app, policy=F.policy(self.cluster.now(), capacity=25))
        outcome = limiter.purge_settled()
        self.assertEqual((outcome['status'], outcome['reads'], outcome['publications']), ('denied', 0, 0))
        self.assertEqual(self.count(), 10, 'nothing was deleted and nothing raised')
        self.assertNotIn('permission', json.dumps(outcome).lower(), 'no database message in the outcome')

    # --- the index and the migration --------------------------------------------------------------------------------

    def test_the_purge_walks_the_partial_index_and_the_rollback_leaves_it_working(self):
        self.add(20000, oldest=10 * HOUR, newest=1 * HOUR)
        self.add(2000, state='sent', oldest=5 * HOUR)
        with self.cluster.connect(autocommit=True) as db:
            db.execute(f'ANALYZE {ADMISSIONS}')

        def plan():
            with self.cluster.connect(autocommit=True) as db:
                db.execute('SET enable_seqscan=off')       # a table this small is cheaper to scan; the million-row test asks the planner
                return '\n'.join(row[0] for row in db.execute(
                    f'''EXPLAIN SELECT request_seq FROM {ADMISSIONS} WHERE application_key=%s AND state IN ('observed','blocked')
                        AND NOT is_publish AND reserved_at<now()-interval '1 hour'
                        AND coalesce(outcome_at,reserved_at)<now()-interval '10 minutes'
                        ORDER BY reserved_at LIMIT 2000 FOR UPDATE SKIP LOCKED''', (self.key,)).fetchall())
        self.assertIn('pr_discord_admission_purge', plan())
        self.psql(ROLLBACK)
        try:
            with self.cluster.connect(autocommit=True) as db:
                self.assertIsNone(db.execute("SELECT to_regclass('public.pr_discord_admission_purge')").fetchone()[0])
            self.assertNotIn('pr_discord_admission_purge', plan())
            outcome = self.limiter.purge_settled()                     # slower, still correct
            self.assertEqual((outcome['status'], outcome['reads']), ('ok', 6000), 'three rounds of the default batch of 2,000, '
                                                                          'a third of the rows are older than the cut')
        finally:
            self.psql(MIGRATION)
        self.psql(MIGRATION)                                           # and it can be applied again
        with self.cluster.connect(autocommit=True) as db:
            self.assertIsNotNone(db.execute("SELECT to_regclass('public.pr_discord_admission_purge')").fetchone()[0])

    # --- size ------------------------------------------------------------------------------------------------------

    def test_a_table_of_a_million_rows_is_purged_in_bounded_time(self):
        """POSTRIFF_RETENTION_ROWS rows (a million for the evidence run), 84% reads and 14% publications as in production,
        half of each past its retention, 2% unresolved. The planner must choose the partial index at this size, a call
        (three rounds of 2,000) must finish well inside the 5 s statement timeout, a call with nothing to do must take a
        few milliseconds, and what survives must be exactly what the rules keep."""
        total = ROWS
        old_reads, new_reads, old_publications, new_publications = (int(total * share) for share in (.60, .24, .07, .07))
        stuck = int(total * .01)
        began = time.monotonic()
        self.add(old_reads, oldest=6 * HOUR, newest=90 * 60)                 # all past the hour, and none crosses it during the run
        self.add(new_reads, oldest=40 * 60, newest=60)                       # all inside it
        self.add(old_publications, publish=True, oldest=96 * HOUR, newest=30 * HOUR)
        self.add(new_publications, publish=True, oldest=20 * HOUR, newest=60)
        self.add(stuck, state='sent', oldest=5 * HOUR, newest=3 * HOUR)
        self.add(stuck, publish=True, state='uncertain', oldest=100 * HOUR, newest=60 * HOUR)
        loaded = time.monotonic() - began
        with self.cluster.connect(autocommit=True) as db:
            db.execute(f'VACUUM (ANALYZE) {ADMISSIONS}')
            size = db.execute(f"SELECT pg_total_relation_size('{ADMISSIONS}')").fetchone()[0]
            plan = '\n'.join(row[0] for row in db.execute(
                f"""EXPLAIN SELECT request_seq FROM {ADMISSIONS} WHERE application_key=%s AND NOT is_publish
                    AND state IN ('observed','blocked') AND reserved_at<now()-make_interval(secs=>3600)
                    AND coalesce(outcome_at,reserved_at)<now()-make_interval(secs=>600)
                    ORDER BY reserved_at LIMIT 2000 FOR UPDATE SKIP LOCKED""", (self.key,)).fetchall())
        self.assertIn('Index Scan using pr_discord_admission_purge', plan, 'the planner walks the partial index:\n' + plan)
        timings = []
        for _ in range(2):
            began = time.monotonic()
            outcome = self.limiter.purge_settled()
            timings.append((time.monotonic() - began, outcome['reads'], outcome['publications'], outcome['rounds']))
        first = timings[0]
        self.assertLess(first[0], 5.0, 'a call finished inside the statement timeout: %r' % (timings,))
        self.assertEqual((first[1], first[3]), (6000, 3), 'three rounds of 2,000 reads')
        began = time.monotonic()
        drained = 0
        while True:
            outcome = self.limiter.purge_settled()
            drained += outcome['reads'] + outcome['publications']
            if not outcome['more']:
                break
        drain = time.monotonic() - began
        began = time.monotonic()
        nothing = self.limiter.purge_settled()
        idle = time.monotonic() - began
        self.assertEqual((nothing['reads'], nothing['publications'], nothing['more']), (0, 0, False))
        self.assertLess(idle, .1, 'a call with nothing to delete is a connection and two index probes')
        self.assertEqual(self.count("NOT is_publish AND state='observed'"), new_reads)
        self.assertEqual(self.count("is_publish AND state='observed'"), new_publications)
        self.assertEqual(self.count("state IN ('sent','uncertain')"), 2 * stuck)
        round_ms = 1000 * first[0] / first[3]
        print('\nretention timing: %d rows (%.0f MB with indexes, loaded in %.0f s). A call: %d rounds of 2,000 reads in %.2f s '
              '(%.0f ms a round). The other %d eligible rows went in %.1f s. Nothing to do: %.1f ms.' % (
                  total, size / 1e6, loaded, first[3], first[0], round_ms, drained, drain, 1000 * idle))

    # --- where it runs ---------------------------------------------------------------------------------------------

    def test_a_lane_with_work_purges_once_and_an_idle_shard_does_not(self):
        tenants = [F.Tenant(0)]
        F.seed(self.cluster, tenants, 1)
        wire = F.MockDiscord(tenants)
        hosted = F.social(self.cluster, tenants, wire, capacity=200)
        worker = F.base_worker(self.cluster, hosted)
        key = application_key(F.APP)
        self.add(5000, oldest=10 * HOUR, newest=2 * HOUR, app=key)
        discord_lane._PURGED_AT[0] = None
        with self.assertLogs('postriff.request', level='INFO') as logged:
            results, failures = F.run_lanes(worker, 1, seconds=20)
        self.assertEqual(failures, [])
        self.assertEqual(self.count("state='observed' AND reserved_at<clock_timestamp()-interval '1 hour'"), 0)
        events = [json.loads(line.getMessage()) for line in logged.records if '"discord.lane.retention"' in line.getMessage()]
        self.assertEqual(len(events), 1, 'one line, counts only')
        self.assertEqual(events[0]['reads'], 5000)
        self.assertEqual(set(events[0]) & {'workspace', 'job', 'channel', 'application'}, set())
        # An idle shard: nothing is due, so it opens one connection for one statement and purges nothing.
        self.add(1000, oldest=10 * HOUR, newest=2 * HOUR, app=key)
        discord_lane._PURGED_AT[0] = None
        results, failures = F.run_lanes(worker, 1, seconds=20)
        self.assertEqual(results[0]['stoppedBy'], 'idle')
        self.assertEqual(self.count("reserved_at<clock_timestamp()-interval '1 hour'"), 1000,
                         'an idle invocation leaves retention to a busy one')

    # --- the health payload ---------------------------------------------------------------------------------------

    def test_the_health_payload_reports_the_backlog_and_the_row_counts(self):
        self.add(400, oldest=5 * HOUR)
        self.add(100, publish=True, oldest=60 * HOUR)
        self.add(50, publish=True, oldest=HOUR)
        with self.cluster.connect(autocommit=True) as db:
            db.execute(f'VACUUM (ANALYZE) {ADMISSIONS}')

        def read():
            with self.cluster.connect(autocommit=True) as db, db.cursor() as cur:
                return ops.read_retention(cur, self.cluster.now(), {})
        before = read()
        self.assertEqual(before['status'], 'observed')
        self.assertEqual(before['retentionSeconds'], {'reads': 3600, 'publications': 86400})
        self.assertAlmostEqual(before['oldestSettledReadAgeSeconds'], 5 * HOUR, delta=30)
        self.assertAlmostEqual(before['oldestSettledPublicationAgeSeconds'], 60 * HOUR, delta=30)
        self.assertEqual(before['liveRowsEstimate'], 550)
        self.limiter.purge_settled()
        with self.cluster.connect(autocommit=True) as db:
            db.execute(f'VACUUM (ANALYZE) {ADMISSIONS}')
        deadline, after = time.monotonic() + 10, None
        while time.monotonic() < deadline:
            after = read()
            if after['liveRowsEstimate'] == 50 and after['rowsDeletedTotal'] - before['rowsDeletedTotal'] >= 500:
                break
            time.sleep(.2)
        self.assertIsNone(after['oldestSettledReadAgeSeconds'], 'no settled read is left, so there is no backlog')
        self.assertAlmostEqual(after['oldestSettledPublicationAgeSeconds'], HOUR, delta=30)
        self.assertEqual(after['liveRowsEstimate'], 50)
        self.assertEqual(after['rowsDeletedTotal'] - before['rowsDeletedTotal'], 500,
                         'the counter is the table\'s own (cumulative for the cluster, so compared as a difference)')


if __name__ == '__main__':
    unittest.main()
