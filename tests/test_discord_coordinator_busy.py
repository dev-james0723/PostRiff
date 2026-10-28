"""A database that is slow does not become a coordinator that is gone (the independent review's NEW-1 and G2E-B-09), offline.

(a) A reservation whose lock or statement times out (lock_timeout 2 s, statement_timeout 5 s: SQLSTATE 55P03 and 57014) was rolled
back: nothing was admitted and nothing sent. It used to surface as RateCoordinatorUnavailable, which a worker turns into a 300-second
release of the post (the review reproduced 253 of them in 12 seconds at 24 loops and 20 ms of statement latency). Now it is a
RateDelayed of 1.5 seconds, cause `coordinator_busy`, scope `application` (the lane waits for it as for a spent window and keeps the
post's place); any other database failure is as unavailable as before.

(b) A coordinator that failed to record an outcome after a request was sent used to disable Discord in that process for good
(`rate_coordinator_degraded`), and one lock timeout in an observation was enough. Now an observation whose own lock or statement
timed out (a rollback: nothing recorded) is asked once more, and a failure that remains stops this process asking the coordinator for
45 seconds, not for ever. A flag set at setup (the reviewed policy does not parse) is still for good.

The real-PostgreSQL proof is test_discord_coordinator_busy_postgres.py. No network, no credentials.
"""
import json
import logging
import secrets
import time
import unittest
from unittest.mock import patch

from postriff_phase2.discord import rate_limits
from postriff_phase2.discord.rate_limits import (
    BUSY_WAIT_SECONDS, RateCoordinatorBusy, RateCoordinatorUnavailable, RateDelayed, ReadAdmissionDelayed, RequestIdentity,
    SharedPostgresBudget, _digest)
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_rate_limits import MemoryLedger, synthetic_policy, APP, A


class DatabaseError(Exception):
    def __init__(self, sqlstate=None):
        super().__init__('synthetic database failure')
        self.sqlstate = sqlstate


class Base(unittest.TestCase):
    def setUp(self):
        self.db = MemoryLedger(now=1000)
        self.s = SharedPostgresBudget(self.db.connection, APP, policy=synthetic_policy())
        self.identity = RequestIdentity.make(APP, 'bot', 'synthetic-busy-bot')
        self.failures = []

    def breaks(self, prefix, error, times=1):
        """The next `times` statements that begin with `prefix` raise `error`; the double rolls the transaction back, as a database does."""
        original, left = self.db.execute, [times]

        def execute(query, params=()):
            if left[0] and ' '.join(query.split()).startswith(prefix):
                left[0] -= 1
                self.failures.append(prefix)
                raise error
            return original(query, params)
        self.db.execute = execute


class ReservationsThatTimeOutWaitSoonInsteadOfFailing(Base):
    LOCK = 'WITH scope_lock AS MATERIALIZED'
    WINDOW = 'WITH tick AS MATERIALIZED'

    def test_a_lock_timeout_in_a_read_admission_is_a_short_wait_and_admits_nothing(self):
        self.breaks(self.LOCK, DatabaseError('55P03'))
        with self.assertRaises(RateDelayed) as caught:
            self.s.reserve_read('GET', '/guilds/700000000000000001', identity=self.identity)
        error = caught.exception
        self.assertNotIsInstance(error, RateCoordinatorUnavailable)
        self.assertEqual((error.rate_cause, error.rate_scope_kind, error.retry_after_seconds), ('coordinator_busy', 'application', BUSY_WAIT_SECONDS))
        self.assertEqual(self.db.admissions, {}, 'nothing was admitted')
        self.s.reserve_read('GET', '/guilds/700000000000000001', identity=self.identity)   # and the next one is

    def test_a_statement_timeout_and_a_create_permit_are_the_same(self):
        self.breaks(self.WINDOW, DatabaseError('57014'))
        bound = {'workspaceId': '00000000-0000-0000-0000-000000000001', 'publicationId': 'p', 'manifestDigest': 'a' * 64,
                 'authorizationDigest': 'b' * 64, 'approvalDigest': 'c' * 64, 'workerKey': 'd' * 64, 'leaseKey': _digest('p'),
                 'channelKey': _digest(A), 'applicationKey': _digest(APP)}
        with self.assertRaises(RateDelayed) as caught:
            self.s.reserve('POST', '/channels/%s/messages' % A, identity=self.identity, binding=bound)
        self.assertEqual(caught.exception.rate_cause, 'coordinator_busy')
        self.assertEqual(self.db.admissions, {})

    def test_a_reservation_refused_as_busy_is_counted_apart_from_every_other_delay(self):
        """`coordinatorBusy` is what the alert RATE_COORDINATOR_BUSY reads: one for each reservation the database could not take in
        time, in the process (booking_stats) and in the tally of the context it was made in (the lane's counters)."""
        tally = {'bookings': 0, 'bookedWaitSeconds': 0.0, 'horizonRefusals': 0, 'coordinatorBusy': 0}
        self.assertEqual(self.s.booking_stats()['coordinatorBusy'], 0)
        for sqlstate in ('55P03', '57014'):
            self.breaks(self.LOCK if sqlstate == '55P03' else self.WINDOW, DatabaseError(sqlstate))
            with rate_limits.booking(1.0, tally), self.assertRaises(RateDelayed):
                self.s.reserve_read('GET', '/guilds/700000000000000001', identity=self.identity)
            self.db.execute = self.db.__class__.execute.__get__(self.db)      # the failing hook is spent
        self.assertEqual((self.s.booking_stats()['coordinatorBusy'], tally['coordinatorBusy']), (2, 2))
        with self.assertRaises(RateCoordinatorUnavailable):                      # a database that is gone is not a slow one
            self.breaks(self.LOCK, DatabaseError('08006'))
            self.s.reserve_read('GET', '/guilds/700000000000000001', identity=self.identity)
        self.db.execute = self.db.__class__.execute.__get__(self.db)
        outside = dict(tally)
        self.breaks(self.LOCK, DatabaseError('55P03'))
        with self.assertRaises(RateDelayed):                                      # outside booking() the process counts it, no tally does
            self.s.reserve_read('GET', '/guilds/700000000000000001', identity=self.identity)
        self.assertEqual((self.s.booking_stats()['coordinatorBusy'], tally), (3, outside))

    def test_any_other_database_failure_is_as_unavailable_as_it_was(self):
        for error in (DatabaseError(None), DatabaseError('08006'), DatabaseError('40001'), OSError('the connection was lost')):
            with self.subTest(error=repr(error)):
                self.setUp()
                self.breaks(self.LOCK, error)
                with self.assertRaises(RateCoordinatorUnavailable) as caught:
                    self.s.reserve_read('GET', '/guilds/700000000000000001', identity=self.identity)
                self.assertNotIsInstance(caught.exception, (RateDelayed, RateCoordinatorBusy))

    def test_a_timeout_in_seal_consume_or_observe_stays_a_failure_of_the_coordinator(self):
        permit = self.s.reserve_read('GET', '/guilds/700000000000000002', identity=self.identity)
        self.breaks('SELECT route_key,major_key', DatabaseError('55P03'))
        with self.assertRaises(RateCoordinatorBusy):      # a RateCoordinatorUnavailable, which the observation's caller may ask again
            self.s.observe(permit, {'status': 200, 'headers': {}})
        self.assertNotIsInstance(RateCoordinatorBusy(), RateDelayed)

    def test_the_provider_releases_a_read_after_a_short_wait_and_sends_nothing(self):
        sent = []
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.invalid',
                                   transport=lambda *a, **k: sent.append(a) or {'status': 200, 'headers': {}, 'body': {}})
        provider.rate_v1_enabled, provider.rate_limiter = True, self.s
        self.breaks(self.LOCK, DatabaseError('55P03'), times=3)
        with self.assertRaises(ReadAdmissionDelayed) as caught:
            provider._bot('GET', '/guilds/700000000000000003')
        self.assertEqual((caught.exception.rate_cause, caught.exception.retry_after_seconds), ('coordinator_busy', BUSY_WAIT_SECONDS))
        self.assertEqual(sent, [])
        self.assertFalse(provider.rate_coordinator_degraded, 'a slow database is not a missing coordinator')


class ARecordingThatTimedOutIsAskedOnceMoreAndAFailureThatRemainsDoesNotDisableDiscordForGood(Base):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.clock = [5000.0]
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.invalid',
                                   transport=lambda *a, **k: self.sent.append(a) or {'status': 200, 'headers': {}, 'body': {}})
        provider.rate_v1_enabled, provider.rate_limiter = True, self.s
        self.provider = provider
        fake = type('Clock', (), {'monotonic': staticmethod(lambda: self.clock[0]), 'time': staticmethod(time.time),
                                  'sleep': staticmethod(time.sleep)})
        patcher = patch('postriff_phase2.social_connectors.time', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        quiet = logging.NullHandler()                        # the lines these tests provoke are not for the test output
        logging.getLogger('postriff.request').addHandler(quiet)
        self.addCleanup(logging.getLogger('postriff.request').removeHandler, quiet)
        self.n = 0

    def read(self):
        self.n += 1
        return self.provider._bot('GET', '/guilds/%d' % (700000000000000100 + self.n))

    OBSERVE = 'SELECT route_key,major_key'

    def test_one_lock_timeout_in_the_observation_is_asked_again_and_recorded_once(self):
        self.breaks(self.OBSERVE, DatabaseError('55P03'))
        self.assertEqual(self.read()['status'], 200)
        self.assertFalse(self.provider.rate_coordinator_degraded)
        (row,) = self.db.admissions.values()
        self.assertEqual(row['state'], 'observed')
        self.assertEqual(self.failures, [self.OBSERVE])

    def test_the_retry_does_not_count_a_failure_twice(self):
        self.provider.transport = lambda *a, **k: self.sent.append(a) or {'status': 503, 'headers': {}, 'body': {}}
        self.breaks(self.OBSERVE, DatabaseError('55P03'))
        self.read()
        route = next(row for key, row in self.db.states.items() if key.startswith('50:'))
        self.assertEqual(route['streak'], 1, 'one 503 answered, one failure counted, though the observation ran twice')

    def test_two_timeouts_stop_this_process_asking_for_45_seconds_and_then_it_asks_again(self):
        self.breaks(self.OBSERVE, DatabaseError('55P03'), times=2)
        with self.assertRaises(RateCoordinatorUnavailable):
            self.read()
        self.assertTrue(self.provider.rate_coordinator_degraded)
        sent = len(self.sent)
        with self.assertRaises(RateCoordinatorUnavailable):
            self.read()
        self.assertEqual(len(self.sent), sent, 'while it is stopped nothing is sent')
        self.clock[0] += 44
        self.assertTrue(self.provider.rate_coordinator_degraded)
        self.clock[0] += 2
        self.assertFalse(self.provider.rate_coordinator_degraded)
        self.assertEqual(self.read()['status'], 200)

    def test_a_failure_that_is_not_a_timeout_is_not_asked_again(self):
        self.breaks(self.OBSERVE, OSError('the connection was lost'), times=2)
        with self.assertRaises(RateCoordinatorUnavailable):
            self.read()
        self.assertEqual(self.failures, [self.OBSERVE], 'asked once')
        self.assertTrue(self.provider.rate_coordinator_degraded)
        self.clock[0] += 46
        self.assertFalse(self.provider.rate_coordinator_degraded)

    def test_a_write_that_may_have_reached_discord_keeps_its_receipt_whatever_the_coordinator_does(self):
        """A POST's answer is returned though its observation failed: the receipt is kept (unchanged), the process rests 45 seconds."""
        self.breaks(self.OBSERVE, DatabaseError('55P03'), times=2)
        answer = {'status': 200, 'headers': {}, 'body': {'id': '1'}}
        self.provider.transport = lambda *a, **k: self.sent.append(a) or answer
        result = self.provider._discord_http('POST', '/oauth2/token', credential_kind='oauth', headers={'Authorization': 'Basic x'},
                                             form={'grant_type': 'refresh_token', 'refresh_token': 'x'})
        self.assertEqual(result['status'], 200, 'the answer of a request that was sent is returned, not hidden behind the ledger')
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.provider.rate_coordinator_degraded)

    def degrade_lines(self, work):
        """The WARNING lines the provider leaves while `work` runs, as parsed events."""
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            work()
        return [json.loads(record.getMessage()) for record in logged.records if 'discord.coordinator.degraded' in record.getMessage()]

    def test_entering_the_rest_leaves_one_line_with_the_kind_of_process_and_the_class_of_the_failure_and_nothing_else(self):
        """The coordinator hides what the database said behind its own classes (RateCoordinatorBusy for a lock or statement timeout,
        RateCoordinatorUnavailable for the rest), so the line can say the class and cannot say more."""
        canary = 'synthetic-' + secrets.token_hex(12)

        class Leaky(Exception):
            pass
        self.breaks(self.OBSERVE, Leaky('the database said ' + canary), times=1)
        token = rate_limits.bind_process_kind('cron')
        try:
            with self.assertLogs('postriff.request', 'WARNING') as logged:
                self._read_raises()
        finally:
            rate_limits.release_process_kind(token)
        (message,) = [record.getMessage() for record in logged.records]
        self.assertNotIn(canary, message)
        self.assertEqual(json.loads(message), {'event': 'discord.coordinator.degraded', 'processKind': 'cron',
                                               'reason': 'RateCoordinatorUnavailable', 'restSeconds': 45.0})
        self.assertTrue(self.provider.rate_coordinator_degraded)

    def test_two_timeouts_in_a_row_say_busy(self):
        self.breaks(self.OBSERVE, DatabaseError('55P03'), times=2)
        lines = self.degrade_lines(self._read_raises)
        self.assertEqual([line['reason'] for line in lines], ['RateCoordinatorBusy'])

    def test_the_line_is_left_when_the_rest_begins_and_not_while_it_goes_on_and_again_after_it(self):
        self.breaks(self.OBSERVE, OSError('the connection was lost'), times=1)
        self.assertEqual([line['reason'] for line in self.degrade_lines(self._read_raises)], ['RateCoordinatorUnavailable'])
        with self.assertNoLogs('postriff.request', 'WARNING'):                  # a failure during the rest: no second line
            self.provider._coordinator_failed()
        self.clock[0] += 46
        self.assertFalse(self.provider.rate_coordinator_degraded)
        self.db.execute = self.db.__class__.execute.__get__(self.db)
        self.breaks(self.OBSERVE, OSError('again'), times=1)
        self.assertEqual([line['reason'] for line in self.degrade_lines(self._read_raises)], ['RateCoordinatorUnavailable'],
                         'a new rest, a new line')

    def _read_raises(self):
        with self.assertRaises(RateCoordinatorUnavailable):
            self.read()

    def test_a_process_nobody_labelled_says_other_and_a_call_outside_a_handler_says_unknown(self):
        (event,) = self.degrade_lines(self.provider._coordinator_failed)
        self.assertEqual((event['processKind'], event['reason']), ('other', 'unknown'))

    def test_a_flag_set_at_setup_is_for_good_until_it_is_cleared(self):
        self.provider.rate_coordinator_degraded = True
        self.clock[0] += 10_000
        self.assertTrue(self.provider.rate_coordinator_degraded)
        self.provider.rate_coordinator_degraded = False
        self.assertFalse(self.provider.rate_coordinator_degraded)
        self.provider._coordinator_failed()
        self.assertTrue(self.provider.rate_coordinator_degraded)
        self.provider.rate_coordinator_degraded = False
        self.assertFalse(self.provider.rate_coordinator_degraded, 'clearing it clears the timed rest too')


class TheKindOfProcessIsLabelledPerRequest(unittest.TestCase):
    """The line a degrade leaves says whether it was the lane, the minute cron or the web: the hosted app binds the kind from the path."""

    def setUp(self):
        quiet = logging.NullHandler()                        # the request lines of the stub handler are not for the test output
        logging.getLogger('postriff.request').addHandler(quiet)
        self.addCleanup(logging.getLogger('postriff.request').removeHandler, quiet)

    def test_the_path_names_the_kind(self):
        for path, kind in (('/api/cron/discord-worker/0', 'lane'), ('/api/cron/discord-worker/11', 'lane'), ('/api/cron/worker', 'cron'),
                           ('/api/cron/agent-tasks', 'cron'), ('/api/cron/youtube/uploads', 'cron'),
                           ('/api/workspaces/w/channels/c/destinations', 'web'), ('/api/me', 'web'), ('', 'web'), (None, 'other')):
            with self.subTest(path=path):
                self.assertEqual(rate_limits.process_kind_of(path), kind)

    def test_an_unknown_kind_is_other(self):
        token = rate_limits.bind_process_kind('something else')
        self.assertEqual(rate_limits.current_process_kind(), 'other')
        rate_limits.release_process_kind(token)

    def test_the_hosted_app_binds_it_while_a_request_is_handled_and_releases_it_after(self):
        from types import SimpleNamespace
        from postriff_phase2.hosted_app import HostedApplication
        app = HostedApplication(service=SimpleNamespace())
        seen = []
        app._handle = lambda environ, respond: (seen.append(rate_limits.current_process_kind()), [b'{}'])[1]
        paths = ['/api/cron/discord-worker/3', '/api/cron/worker', '/api/workspaces/w/channels/c/destinations']
        for path in paths:
            b''.join(app({'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'wsgi.url_scheme': 'https', 'HTTP_HOST': 'rafii.example.invalid'},
                         lambda status, headers, exc_info=None: None))
        self.assertEqual(seen, ['lane', 'cron', 'web'])
        self.assertEqual(rate_limits.current_process_kind(), 'other', 'nothing is left bound')

    def test_it_is_released_when_the_request_fails_too(self):
        from types import SimpleNamespace
        from postriff_phase2.hosted_app import HostedApplication
        app = HostedApplication(service=SimpleNamespace())

        def explode(environ, respond):
            raise RuntimeError('synthetic')
        app._handle = explode
        with self.assertRaises(RuntimeError):
            app({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/cron/discord-worker/1', 'wsgi.url_scheme': 'https', 'HTTP_HOST': 'x.invalid'},
                lambda status, headers, exc_info=None: None)
        self.assertEqual(rate_limits.current_process_kind(), 'other')


if __name__ == '__main__':
    unittest.main()
