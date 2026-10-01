"""Founder reliability request metrics (CONTRACTS §8.D): the request-completion hook and its best-effort writer.

No PostgreSQL, no network: fake connections stand in for the consumer database. Proves that only route patterns with masked
identifiers are kept, that aggregation is bounded, that the flush is an upsert off the request path, and that a missing
table (production running before 060 is applied) changes nothing about any response and is logged once.
"""
import io
import json
import os
import re
import threading
import unittest
from pathlib import Path
from unittest import mock

import psycopg

from postriff_phase2 import request_metrics
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.request_metrics import (BOUNDS_MS, BUCKETS, FAILURE_PAUSE, FLUSH_SECONDS, MAX_KEYS, MAX_ROUTE_LENGTH, NOT_INSTALLED_PAUSE, OVERFLOW_KEYS,
                                             ROUTE_WORDS, Recorder, route_key, status_class)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / 'migrations/postriff/060_founder_reliability.sql').read_text()
# The 060 CHECK on route_pattern, verbatim; every key the writer can produce must satisfy it.
ROUTE_CHECK = re.search(r"route_pattern ~ '([^']+)'", MIGRATION).group(1)
UUID = '5f0c1a52-8f3e-4b8e-9a53-0f5c2e1f9a10'
T0 = 1_790_000_040.0   # an exact minute start


class FakeCursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.db.statements.append((sql, params))

    def executemany(self, sql, rows):
        self.db.batches.append((sql, list(rows)))
        if self.db.fail is not None:
            raise self.db.fail


class FakeDB:
    def __init__(self, fail=None):
        self.fail, self.statements, self.batches, self.commits = fail, [], [], 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class Factory:
    """A consumer connection factory that counts every connection attempt."""
    def __init__(self, fail=None):
        self.fail, self.connections = fail, []

    def __call__(self):
        db = FakeDB(self.fail)
        self.connections.append(db)
        return db


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def synchronous(work):
    work()


class RouteKeyTests(unittest.TestCase):
    def test_identifiers_tokens_and_unknown_segments_are_masked(self):
        cases = {
            ('GET', f'/api/workspaces/{UUID}/ideas/runs/0123456789abcdef0123/events'): 'GET /api/workspaces/:id/ideas/runs/:id/events',
            ('POST', f'/api/workspaces/{UUID}/channels/linkedin/oauth/start'): 'POST /api/workspaces/:id/channels/linkedin/oauth/start',
            ('POST', '/api/control/v2/incidents/42/ack'): 'POST /api/control/v2/incidents/:id/ack',
            ('GET', '/api/content-dna/shortshare'): 'GET /api/content-dna/:id',
            ('GET', '/api/invitations/AbCdEfGh/accept'): 'GET /api/invitations/:id/accept',
            ('GET', '/api/me/someone@example.com'): 'GET /api/me/:id',
            ('GET', '/api/workspaces/abc/billing/credit-checkout'): 'GET /api/workspaces/:id/billing/credit-checkout',
            ('GET', '/api/workspaces/%2E%2E/members'): 'GET /api/workspaces/:id/members',
            ('GET', '/api/../health'): 'GET /api/:id/health',
            ('get', '/api/health/'): 'GET /api/health',
            ('PROPFIND', '/api/health'): 'OTHER /api/health',
            (None, None): 'OTHER /:other',
            ('GET', '/'): 'GET /:other',
            ('GET', '/_next/static/chunk-1234.js'): 'GET /:other',
            ('GET', '/API/health'): 'GET /:other',
        }
        for (method, path), expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(route_key(method, path), expected)
                self.assertRegex(route_key(method, path), ROUTE_CHECK)

    def test_depth_and_length_are_bounded_at_a_segment_boundary(self):
        deep = route_key('GET', '/api/' + '/'.join(['workspaces'] * 30))
        self.assertTrue(deep.endswith('/:more'))
        self.assertEqual(deep.count('/'), 10)
        long = route_key('DELETE', '/api/' + '/'.join(['notification-preferences'] * 7))
        self.assertLessEqual(len(long), MAX_ROUTE_LENGTH)
        self.assertRegex(long, ROUTE_CHECK)
        self.assertNotIn('notification-preferences/:more/', long)

    def test_every_route_word_fits_the_060_check(self):
        for word in sorted(ROUTE_WORDS):
            with self.subTest(word=word):
                self.assertRegex(f'GET /api/{word}', ROUTE_CHECK)
        self.assertNotIn('', ROUTE_WORDS)

    def test_status_classes(self):
        self.assertEqual([status_class(code) for code in (101, 200, 302, 404, 503, 0, 700, 'x', None)],
                         ['1xx', '2xx', '3xx', '4xx', '5xx', '5xx', '5xx', '5xx', '5xx'])

    def test_histogram_bounds_match_the_reader_and_the_migration(self):
        from rafii_control.founder_metrics_ops import BOUNDS_MS as READER_BOUNDS
        self.assertEqual(BOUNDS_MS, READER_BOUNDS)
        self.assertEqual(BUCKETS, 20)
        self.assertIn(', '.join(str(bound) for bound in BOUNDS_MS) + ' ms', ' '.join(MIGRATION.replace('--', ' ').split()))
        self.assertIn('cardinality(duration_buckets) = 20', MIGRATION)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.spawned = []
        self.recorder = Recorder(clock=self.clock, spawn=self.spawned.append)

    def test_aggregates_minute_route_status_and_histogram(self):
        self.recorder.record('GET', f'/api/workspaces/{UUID}', 200, 0.004, now=T0 + 1)
        self.recorder.record('GET', f'/api/workspaces/{UUID.replace("5", "6")}', 200, 0.120, now=T0 + 30)
        self.recorder.record('GET', f'/api/workspaces/{UUID}', 503, 31.0, now=T0 + 40)
        self.recorder.record('GET', f'/api/workspaces/{UUID}', 200, 0.010, now=T0 + 61)
        minute = int(T0 // 60) * 60
        ok = self.recorder.buffer[(minute, 'GET /api/workspaces/:id', '2xx')]
        self.assertEqual((ok[0], round(ok[1], 3)), (2, 124.0))
        self.assertEqual((ok[2][0], ok[2][BOUNDS_MS.index(150)]), (1, 1))
        failed = self.recorder.buffer[(minute, 'GET /api/workspaces/:id', '5xx')]
        self.assertEqual(failed[2][-1], 1, 'over 30 s lands in the open-ended bucket')
        next_minute = self.recorder.buffer[(minute + 60, 'GET /api/workspaces/:id', '2xx')]
        self.assertEqual(next_minute[2][0], 1, 'exactly 10 ms is <= the first bound')
        self.assertTrue(all(UUID not in key[1] for key in self.recorder.buffer))

    def test_buffer_is_bounded_by_overflow_buckets_then_drops(self):
        with mock.patch.object(request_metrics, 'MAX_KEYS', 3), mock.patch.object(request_metrics, 'OVERFLOW_KEYS', 1):
            for minute in range(6):
                self.recorder.record('GET', '/api/health', 200, 0.01, now=T0 + minute * 60)
        self.assertEqual(len(self.recorder.buffer), 4)
        self.assertEqual(sum(1 for key in self.recorder.buffer if key[1] == 'GET /:overflow'), 1)
        self.assertEqual(self.recorder.dropped, 2)
        self.assertGreater(MAX_KEYS + OVERFLOW_KEYS, 0)

    def test_flush_is_spawned_off_the_request_path_and_upserts_sorted_rows(self):
        factory = Factory()
        self.recorder.record('POST', f'/api/workspaces/{UUID}/actions', 200, 0.2)
        self.recorder.record('GET', '/api/health', 200, 0.01)
        self.assertTrue(self.recorder.maybe_flush(factory))
        self.assertEqual((factory.connections, len(self.spawned)), ([], 1), 'nothing touches the database on the request thread')
        self.assertEqual(self.recorder.buffer, {})
        self.spawned.pop()()
        db = factory.connections[0]
        sql, rows = db.batches[0]
        self.assertIn('ON CONFLICT (minute,route_pattern,status_class) DO UPDATE', sql)
        self.assertIn('unnest(m.duration_buckets,excluded.duration_buckets) WITH ORDINALITY', sql)
        self.assertEqual(db.statements[0][0], 'SET LOCAL statement_timeout = 2000')
        self.assertEqual([row[1] for row in rows], sorted(row[1] for row in rows))
        self.assertEqual({row[1] for row in rows}, {'GET /api/health', 'POST /api/workspaces/:id/actions'})
        self.assertTrue(all(len(row[5]) == BUCKETS and row[3] == 1 for row in rows))
        self.assertNotIn(UUID, json.dumps(rows))
        self.assertEqual(db.commits, 1)
        self.assertFalse(self.recorder.flushing)

    def test_one_flusher_at_a_time_and_at_most_every_flush_interval(self):
        factory = Factory()
        self.recorder.record('GET', '/api/health', 200, 0.01)
        self.assertTrue(self.recorder.maybe_flush(factory))
        self.recorder.record('GET', '/api/health', 200, 0.01)
        self.assertFalse(self.recorder.maybe_flush(factory), 'the first flush is still running')
        self.spawned.pop()()
        self.assertFalse(self.recorder.maybe_flush(factory), 'not again before FLUSH_SECONDS')
        self.clock.now += FLUSH_SECONDS
        self.assertTrue(self.recorder.maybe_flush(factory))
        self.assertFalse(Recorder(clock=self.clock, spawn=self.spawned.append).maybe_flush(factory), 'nothing buffered, nothing to flush')

    def test_generic_failure_logs_class_only_and_pauses_five_minutes(self):
        factory = Factory(fail=psycopg.OperationalError('connection to postgres://user:secret@db.example failed'))
        recorder = Recorder(clock=self.clock, spawn=synchronous)
        recorder.record('GET', '/api/health', 200, 0.01)
        with self.assertLogs('postriff.request_metrics', level='WARNING') as logs:
            recorder.maybe_flush(factory)
        record = json.loads(logs.records[0].getMessage())
        self.assertEqual(record, {'error': 'OperationalError', 'event': 'request_metrics.flush_failed', 'pauseSeconds': FAILURE_PAUSE})
        self.assertNotIn('secret', ' '.join(logs.output))
        self.assertEqual(recorder.paused_until, T0 + FAILURE_PAUSE)
        recorder.record('GET', '/api/health', 200, 0.01)
        self.assertEqual(recorder.buffer, {}, 'paused: nothing is buffered')

    def test_a_spawn_failure_is_a_failed_flush_not_a_failed_request(self):
        def broken(work):
            raise RuntimeError('cannot start thread')
        recorder = Recorder(clock=self.clock, spawn=broken)
        recorder.record('GET', '/api/health', 200, 0.01)
        with self.assertLogs('postriff.request_metrics', level='WARNING'):
            self.assertTrue(recorder.maybe_flush(Factory()))
        self.assertFalse(recorder.flushing)

    def test_default_flusher_runs_on_a_daemon_thread(self):
        done = threading.Event()

        class Committing(FakeDB):
            def commit(self):
                super().commit()
                done.set()
        recorder = Recorder()
        recorder.record('GET', '/api/health', 200, 0.01)
        threads = []
        real = threading.Thread

        def capture(*args, **kwargs):
            thread = real(*args, **kwargs)
            threads.append(thread)
            return thread
        with mock.patch.object(request_metrics.threading, 'Thread', side_effect=capture):
            recorder.maybe_flush(lambda: Committing())
        self.assertTrue(done.wait(5))
        self.assertTrue(threads[0].daemon)
        threads[0].join(5)


class FakeService:
    """The consumer runtime as far as the hook can see it: a connection factory."""
    def __init__(self, factory):
        self.connection_factory = factory


class HookTests(unittest.TestCase):
    """The hook inside HostedApplication.__call__ (the request-completion region only)."""
    def setUp(self):
        self.clock = Clock()
        self.recorder = Recorder(clock=self.clock, spawn=synchronous)
        patcher = mock.patch.object(request_metrics, 'RECORDER', self.recorder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, app, path, method='GET'):
        result = {}

        def start(status, headers, exc_info=None):
            result.update(status=status, headers=dict(headers))
        body = b''.join(app({'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': 'token=PRIVATE', 'wsgi.input': io.BytesIO()}, start))
        headers = {key: value for key, value in result['headers'].items() if key != 'X-Request-ID'}
        return result['status'], headers, json.loads(body)

    def responses(self, app):
        return [self.request(app, '/api/health'), self.request(app, f'/api/workspaces/{UUID}/members'), self.request(app, '/api/health')]

    def test_missing_table_changes_nothing_about_the_response_and_logs_once(self):
        with mock.patch.dict(os.environ, {'POSTRIFF_REQUEST_METRICS': '0'}):
            baseline = self.responses(HostedApplication(FakeService(Factory()), None, {}, 'c' * 24))
        missing = Factory(fail=psycopg.errors.UndefinedTable('relation "public.pr_request_metrics" does not exist'))
        app = HostedApplication(FakeService(missing), None, {}, 'c' * 24)
        with mock.patch.dict(os.environ, {'POSTRIFF_DATABASE_URL': 'postgresql://synthetic.invalid/db', 'POSTRIFF_REQUEST_METRICS': '1'}), \
             self.assertLogs('postriff.request_metrics', level='WARNING') as logs, self.assertLogs('postriff.request', level='INFO') as requests:
            observed = self.responses(app)
            self.clock.now += NOT_INSTALLED_PAUSE + 1   # ten minutes later the writer tries again, and still logs nothing new
            observed.append(self.request(app, '/api/health'))
        self.assertEqual(observed[:3], baseline)
        self.assertEqual(observed[3], baseline[0])
        self.assertEqual([status for status, _, _ in baseline], ['200 OK', '401 Unauthorized', '200 OK'])
        self.assertEqual(len(missing.connections), 2, 'one attempt, then a ten-minute pause, then one more')
        self.assertEqual([json.loads(record.getMessage()) for record in logs.records],
                         [{'error': 'UndefinedTable', 'event': 'request_metrics.not_installed', 'pauseSeconds': NOT_INSTALLED_PAUSE}])
        completed = [json.loads(record.getMessage()) for record in requests.records if record.name == 'postriff.request']
        self.assertEqual([record['event'] for record in completed], ['request.completed'] * 4)
        self.assertNotIn('PRIVATE', ' '.join(logs.output + requests.output))

    def test_hook_records_route_patterns_and_never_raises(self):
        factory = Factory()
        app = HostedApplication(FakeService(factory), None, {}, 'c' * 24)
        with mock.patch.dict(os.environ, {'POSTRIFF_DATABASE_URL': 'postgresql://synthetic.invalid/db'}):
            status, _, _ = self.request(app, f'/api/workspaces/{UUID}/members')
        self.assertEqual(status, '401 Unauthorized')
        rows = factory.connections[0].batches[0][1]
        self.assertEqual([(row[1], row[2], row[3]) for row in rows], [('GET /api/workspaces/:id/members', '4xx', 1)])
        with mock.patch.dict(os.environ, {'POSTRIFF_DATABASE_URL': 'x'}), mock.patch.object(self.recorder, 'record', side_effect=RuntimeError('boom')):
            self.assertEqual(self.request(app, '/api/health')[0], '200 OK')
        with mock.patch.object(request_metrics, 'observe', side_effect=RuntimeError('boom')):
            self.assertEqual(self.request(app, '/api/health')[0], '200 OK')

    def test_off_without_a_deployed_database_or_with_the_switch(self):
        factory = Factory()
        app = HostedApplication(FakeService(factory), None, {}, 'c' * 24)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('POSTRIFF_DATABASE_URL', None)
            self.request(app, '/api/health')
        with mock.patch.dict(os.environ, {'POSTRIFF_DATABASE_URL': 'x', 'POSTRIFF_REQUEST_METRICS': '0'}):
            self.request(app, '/api/health')
        self.assertEqual((self.recorder.buffer, factory.connections), ({}, []))
        # Before the runtime is built (no service yet) requests are buffered but nothing connects.
        unbuilt = HostedApplication()
        unbuilt._runtime = lambda: (_ for _ in ()).throw(AssertionError('the hook must not build the runtime'))
        with mock.patch.dict(os.environ, {'POSTRIFF_DATABASE_URL': 'x'}):
            self.assertEqual(self.request(unbuilt, '/api/health')[0], '200 OK')
        self.assertEqual(len(self.recorder.buffer), 1)
        self.assertIsNone(request_metrics.connection_factory(None))


if __name__ == '__main__':
    unittest.main()
