"""Offline contracts of the admissions retention (B3): what the coordinator's purge sends, how it fails, and when the lane asks.

The deleting itself, the concurrency and the size are proved on PostgreSQL in test_discord_rate_retention_postgres.py. Here a
fake connection records every statement, so these prove the shape that must never change: the purge reads and deletes
admissions only (never a scope row, so never the application row's lock), is bounded, skips rows another caller holds, uses
the transaction clock so that its cutoff can bound the partial index, and never raises into the caller. No network, no database,
no credentials.
"""
import json
import logging
import re
import unittest
from types import SimpleNamespace

from postriff_phase2.discord import lane
from postriff_phase2.discord.rate_limits import PURGE_LOCK, SharedPostgresBudget
from test_discord_rate_limits import APP, synthetic_policy

ROOT = lane.__file__.rsplit('/src/', 1)[0]


class Failure(Exception):
    def __init__(self, sqlstate):
        super().__init__('synthetic database message that must not be repeated')
        self.sqlstate = sqlstate


class Recorder:
    """A connection factory answering the purge's statements; `lock` is what pg_try_advisory_xact_lock answers, `deleted`
    the counts the two DELETEs report, `fail` an exception to raise on the first statement that is not the lock."""
    def __init__(self, lock=True, deleted=(0, 0), fail=None):
        self.lock, self.deleted, self.fail = lock, list(deleted), fail
        self.statements, self.parameters, self.opened = [], [], 0
        self.queue = []

    def __call__(self):
        self.opened += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.statements.append(' '.join(sql.split()))
        self.parameters.append(params)
        if 'set_config' in sql:
            self.queue = [('1000ms', '5000ms', self.lock)]
        else:
            if self.fail is not None:
                raise self.fail
            self.queue = [(self.deleted.pop(0) if self.deleted else 0,)]

    def fetchone(self):
        return self.queue[0]


def limiter(recorder):
    return SharedPostgresBudget(recorder, APP, policy=synthetic_policy())


class PurgeShape(unittest.TestCase):
    def test_it_touches_admissions_only_and_is_bounded_and_skips_held_rows(self):
        recorder = Recorder(deleted=(7, 3))
        outcome = limiter(recorder).purge_settled()
        self.assertEqual((outcome['status'], outcome['reads'], outcome['publications'], outcome['rounds'], outcome['more']),
                         ('ok', 7, 3, 1, False))
        locking, reads, publications = recorder.statements
        self.assertIn('pg_try_advisory_xact_lock', locking)
        self.assertIn("lock_timeout','1000ms'", locking)
        self.assertIn("statement_timeout','5000ms'", locking)
        self.assertEqual(recorder.parameters[0], (PURGE_LOCK,))
        for sql in (reads, publications):
            self.assertIn('DELETE FROM public.pr_discord_request_admissions', sql)
            self.assertIn('FOR UPDATE SKIP LOCKED', sql)
            self.assertIn('LIMIT %s', sql)
            self.assertIn("state IN ('observed','blocked')", sql, 'only settled rows')
            self.assertIn('application_key=%s', sql, 'only this application')
            self.assertNotIn('pr_discord_rate_state', sql, 'no scope row, so no application row and no scope lock')
            self.assertNotIn('pr_discord_route_buckets', sql)
            self.assertNotIn('clock_timestamp', sql, 'a volatile cutoff cannot bound the partial index scan (66 ms for nothing at 50,000 rows)')
            self.assertEqual(sql.count('now()'), 2)
        self.assertIn('NOT is_publish', reads)
        self.assertNotIn('NOT is_publish', publications)
        key = limiter(recorder).application_key
        self.assertEqual(recorder.parameters[1], (key, 3600.0, 600.0, 2000))
        self.assertEqual(recorder.parameters[2], (key, 86400.0, 600.0, 2000))
        self.assertEqual(recorder.opened, 1, 'one short transaction')

    def test_it_runs_more_rounds_only_while_they_come_back_full(self):
        recorder = Recorder(deleted=(2000, 5, 2000, 0, 12, 0))
        outcome = limiter(recorder).purge_settled()
        self.assertEqual((outcome['reads'], outcome['publications'], outcome['rounds'], outcome['more']), (4012, 5, 3, False))
        self.assertEqual(recorder.opened, 3)
        recorder = Recorder(deleted=(2000, 0, 2000, 0, 2000, 0))
        outcome = limiter(recorder).purge_settled()
        self.assertEqual((outcome['reads'], outcome['rounds'], outcome['more']), (6000, 3, True), 'a call is bounded; the next goes on')

    def test_another_purger_holding_the_lock_is_not_an_error(self):
        recorder = Recorder(lock=False)
        outcome = limiter(recorder).purge_settled()
        self.assertEqual((outcome['status'], outcome['reads'], outcome['rounds']), ('busy', 0, 0))
        self.assertEqual(len(recorder.statements), 1, 'nothing was deleted or even selected')

    def test_a_failure_is_an_outcome_never_an_exception_and_never_carries_the_database_message(self):
        for sqlstate, status in (('42501', 'denied'), ('57014', 'timeout'), ('55P03', 'timeout'), ('XX000', 'error'), (None, 'error')):
            with self.subTest(sqlstate=sqlstate):
                outcome = limiter(Recorder(fail=Failure(sqlstate))).purge_settled()
                self.assertEqual((outcome['status'], outcome['reads'], outcome['publications']), (status, 0, 0))
                self.assertEqual(outcome['error'], 'Failure')
                self.assertNotIn('synthetic database message', json.dumps(outcome))

        def unreachable():
            raise OSError('database unreachable')
        outcome = SharedPostgresBudget(unreachable, APP, policy=synthetic_policy()).purge_settled()
        self.assertEqual((outcome['status'], outcome['error']), ('error', 'OSError'))

    def test_the_retention_numbers_are_the_reviewed_ones(self):
        """Written out here so that changing one is a decision made in this file too: 2,000 rows a statement, an hour for a
        read and a day for a publication, ten minutes of grace after a row settles."""
        self.assertEqual((SharedPostgresBudget.PURGE_BATCH, SharedPostgresBudget.PURGE_ROUNDS), (2000, 3))
        self.assertEqual((SharedPostgresBudget.PURGE_READ_SECONDS, SharedPostgresBudget.PURGE_PUBLICATION_SECONDS), (3600.0, 86400.0))
        self.assertEqual(SharedPostgresBudget.PURGE_SETTLE_GRACE_SECONDS, 600.0)
        self.assertLess(SharedPostgresBudget.PURGE_READ_SECONDS, SharedPostgresBudget.PURGE_PUBLICATION_SECONDS)
        horizon = SharedPostgresBudget.UNOBSERVED_MARGIN_SECONDS + 600     # the longest window an unanswered request counts for
        self.assertGreater(SharedPostgresBudget.PURGE_READ_SECONDS, horizon,
                           'longer than the invalid-request window plus the unanswered-request margin')


class Migration(unittest.TestCase):
    def read(self, name):
        with open('%s/migrations/postriff/%s' % (ROOT, name)) as handle:
            return handle.read()

    def test_the_rollback_is_outside_the_numbered_sequence_the_migration_runner_reads(self):
        """scripts/postriff_migrate.py takes every [0-9][0-9][0-9]_*.sql of the folder as a migration and refuses two with one
        number, so a rollback named like the migration made migrations() raise for every plan and every apply (found on the
        first hosted run: tests.test_migration_numbers failed). It lives in its own folder."""
        import sys
        sys.path.insert(0, '%s/scripts' % ROOT)
        import postriff_migrate
        names = [path.name for path in postriff_migrate.migrations()]
        self.assertEqual([name for name in names if name.startswith('142_')], ['142_discord_admission_retention_index.sql'])
        self.assertFalse([name for name in names if 'rollback' in name])
        self.assertTrue(self.read('rollback/142_discord_admission_retention_index.sql').startswith('-- Candidate only. Rollback of'))

    def test_the_index_is_the_one_the_purge_walks_and_the_rollback_drops_it(self):
        up = self.read('142_discord_admission_retention_index.sql')
        down = self.read('rollback/142_discord_admission_retention_index.sql')
        statement = re.sub(r'\s+', ' ', re.search(r'CREATE INDEX IF NOT EXISTS.*?;', up, re.S).group(0))
        self.assertEqual(statement, "CREATE INDEX IF NOT EXISTS pr_discord_admission_purge ON public.pr_discord_request_admissions"
                                    "(is_publish,reserved_at) WHERE state IN ('observed','blocked');")
        for sql in (up, down):
            self.assertRegex(sql, r'(?m)^BEGIN;$')
            self.assertRegex(sql, r'(?m)^COMMIT;$')
            self.assertRegex(sql, r"SET LOCAL lock_timeout='2s'")
            self.assertNotRegex(re.sub(r'(?m)^--.*$', '', sql), r'(?i)\bDELETE\b|\bGRANT\b|\bDROP TABLE\b|\bTRUNCATE\b')
        self.assertIn('NOT APPLIED', up)
        self.assertIn('DROP INDEX IF EXISTS public.pr_discord_admission_purge;', down)
        self.assertIn("state IN ('observed','blocked')", SharedPostgresBudget._PURGE_SQL, 'the purge states the index predicate')


class FakeSocial:
    def __init__(self, limiter_object):
        self.providers = {'discord': SimpleNamespace(rate_limiter=limiter_object)}


class Asked:
    def __init__(self, outcome=None, error=None):
        self.calls, self.outcome, self.error = 0, outcome or {'status': 'ok', 'reads': 0, 'publications': 0, 'rounds': 1, 'more': False}, error

    def purge_settled(self):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.outcome)


class LaneAsks(unittest.TestCase):
    def setUp(self):
        lane._PURGED_AT[0] = None
        self.addCleanup(lambda: lane._PURGED_AT.__setitem__(0, None))
        self.clock = [1000.0]
        self.monotonic = lambda: self.clock[0]

    def ask(self, asked):
        return lane.purge_admissions(SimpleNamespace(social=FakeSocial(asked)), monotonic=self.monotonic)

    def test_at_most_once_a_minute_per_process(self):
        asked = Asked()
        self.assertIsNotNone(self.ask(asked))
        self.clock[0] += 59.9
        self.assertIsNone(self.ask(asked), 'too soon')
        self.clock[0] += .2
        self.assertIsNotNone(self.ask(asked))
        self.assertEqual(asked.calls, 2)

    def test_a_clock_that_ran_backwards_does_not_silence_it_for_ever(self):
        asked = Asked()
        self.ask(asked)
        self.clock[0] -= 500
        self.assertIsNotNone(self.ask(asked))

    def test_a_lane_without_a_coordinator_asks_nobody(self):
        self.assertIsNone(lane.purge_admissions(SimpleNamespace(social=SimpleNamespace(providers={})), monotonic=self.monotonic))
        self.assertIsNone(lane.purge_admissions(SimpleNamespace(social=FakeSocial(object())), monotonic=self.monotonic))

    def test_it_never_raises_and_logs_counts_only(self):
        with self.assertLogs('postriff.request', level='INFO') as logged:
            self.ask(Asked({'status': 'ok', 'reads': 1500, 'publications': 3, 'rounds': 1, 'more': False}))
        (line,) = logged.records
        self.assertEqual(line.levelno, logging.INFO)
        self.assertEqual(json.loads(line.getMessage()), {'event': 'discord.lane.retention', 'status': 'ok', 'reads': 1500,
                                                         'publications': 3, 'rounds': 1, 'more': False})
        self.clock[0] += 61
        with self.assertLogs('postriff.request', level='INFO') as logged:
            self.ask(Asked({'status': 'denied', 'reads': 0, 'publications': 0, 'rounds': 0, 'more': False, 'error': 'InsufficientPrivilege'}))
        (line,) = logged.records
        self.assertEqual(line.levelno, logging.WARNING)
        self.assertEqual(json.loads(line.getMessage())['error'], 'InsufficientPrivilege')
        self.clock[0] += 61
        self.assertIsNone(self.ask(Asked(error=RuntimeError('a limiter that raises anyway'))), 'retention never stops the lane')
        self.clock[0] += 61
        with self.assertNoLogs('postriff.request', level='INFO'):
            self.ask(Asked())    # nothing deleted: silent


if __name__ == '__main__':
    unittest.main()
