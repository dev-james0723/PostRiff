"""The web calls that read Discord several times in a row are booked like the lane, offline (docs/w02/AS-BUILT.md, "Web calls that
read several times"; the independent review's IMMEDIATE_RESERVE measurement).

While the lane saturates the application window, the one slot kept for immediate callers cannot carry a channel list (four to six
reads in a row): the call is refused after the first read or two, almost every time. Four web calls make such a series, and only
those: the channel list (GET destinations), choosing a channel (POST destination), the re-check (POST verify) and the last step of a
connection (POST oauth/complete). They now run inside rate_limits.web_reads(), which books each read a slot up to one second ahead
like the lane does. Everything else, a single read above all, stays immediate. The real-PostgreSQL proof, with the lane saturating
the window, is test_discord_web_booking_postgres.py. No network, no credentials.
"""
import io
import json
import threading
import unittest
from types import SimpleNamespace

from postriff_phase2.discord import rate_limits
from postriff_phase2.discord.rate_limits import (
    BOOK_AHEAD_SECONDS, RateCoordinatorUnavailable, booking, current_book_ahead, web_booked, web_reads)
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.social_connectors import DiscordProvider


class TheContext(unittest.TestCase):
    def test_a_web_call_is_booked_inside_the_block_and_immediate_outside_it(self):
        self.assertEqual(current_book_ahead(), 0.0)
        with web_reads():
            self.assertEqual(current_book_ahead(), BOOK_AHEAD_SECONDS)
        self.assertEqual(current_book_ahead(), 0.0)

    def test_it_is_restored_when_the_call_fails(self):
        with self.assertRaises(ZeroDivisionError):
            with web_reads():
                1 / 0
        self.assertEqual(current_book_ahead(), 0.0)

    def test_it_never_books_further_than_the_maximum_and_a_zero_is_no_booking(self):
        with web_reads(30):
            self.assertEqual(current_book_ahead(), BOOK_AHEAD_SECONDS)
        with web_reads(0):
            self.assertEqual(current_book_ahead(), 0.0)

    def test_a_caller_that_is_already_booking_keeps_its_own_horizon_and_its_tally(self):
        tally = {'bookings': 0, 'bookedWaitSeconds': 0.0}
        with booking(.4, tally):
            with web_reads():
                self.assertEqual(current_book_ahead(), .4, 'the lane\'s horizon is not replaced')
                self.assertIs(rate_limits._BOOK_AHEAD.get()[1], tally, 'and neither is its tally')
            self.assertEqual(current_book_ahead(), .4)
        self.assertEqual(current_book_ahead(), 0.0)

    def test_another_thread_does_not_see_it(self):
        seen = []
        with web_reads():
            thread = threading.Thread(target=lambda: seen.append(current_book_ahead()))
            thread.start()
            thread.join()
        self.assertEqual(seen, [0.0])

    def test_web_booked_runs_the_call_inside_the_block_and_returns_what_it_returns(self):
        def call(*args, **kwargs):
            return args, kwargs, current_book_ahead()
        self.assertEqual(web_booked(call, 1, 2, three=3), ((1, 2), {'three': 3}, BOOK_AHEAD_SECONDS))
        self.assertEqual(current_book_ahead(), 0.0)


class TheProviderAsksForTheBooking(unittest.TestCase):
    """Inside web_reads() a direct read reaches the coordinator with a book_ahead; nothing else does."""

    def setUp(self):
        self.calls = []
        calls = self.calls

        class Limiter:
            policy = SimpleNamespace(read_attempts=1)

            def reserve_read(self, method, path, *, identity, book_ahead=0.0):
                calls.append(('reserve_read', path, book_ahead))
                raise RateCoordinatorUnavailable()

            def reserve(self, method, path, *, identity, **kwargs):
                calls.append(('reserve', path, kwargs.get('book_ahead', 0.0)))
                raise RateCoordinatorUnavailable()

        self.provider = DiscordProvider('800000000000000001', 'synthetic-secret', 'synthetic-bot', 'https://rafii.invalid',
                                        transport=lambda *a, **k: self.fail('nothing is sent'))
        self.provider.rate_v1_enabled, self.provider.rate_limiter = True, Limiter()

    def read(self):
        with self.assertRaises(RateCoordinatorUnavailable):
            self.provider._bot('GET', '/guilds/700000000000000001')
        return self.calls[-1]

    def test_outside_the_block_a_read_is_immediate(self):
        self.assertEqual(self.read(), ('reserve_read', '/guilds/700000000000000001', 0.0))

    def test_inside_the_block_a_read_may_be_booked_for_what_its_wait_allows(self):
        with web_reads():
            kind, path, ahead = self.read()
        self.assertEqual((kind, path), ('reserve_read', '/guilds/700000000000000001'))
        self.assertTrue(.9 < ahead <= BOOK_AHEAD_SECONDS, ahead)       # a read waits at most a second for its slot

    def test_a_request_that_is_not_a_read_is_never_booked(self):
        with web_reads():
            with self.assertRaises(RateCoordinatorUnavailable):
                self.provider._discord_http('POST', '/oauth2/token', credential_kind='oauth', headers={'Authorization': 'Basic x'},
                                            form={'grant_type': 'refresh_token', 'refresh_token': 'x'})
        self.assertEqual(self.calls[-1], ('reserve', '/oauth2/token', 0.0))


class Routes(unittest.TestCase):
    """Which web routes book: drive the real handler with a service that records what its calls were told."""
    WORKSPACE, CONNECTION = '00000000-0000-4000-8000-000000000001', 'discord-installation'

    def setUp(self):
        self.seen = []

        def record(name, fail=False):
            def call(*args, **kwargs):
                self.seen.append((name, current_book_ahead()))
                if fail:
                    from postriff_alpha.domain import AlphaError
                    raise AlphaError('synthetic failure', 409)
                return {'ok': name}
            return call
        self.record = record
        oauth = SimpleNamespace(**{name: record(name) for name in (
            'destinations', 'choose_destination', 'verify', 'complete', 'creator_info', 'start', 'remove_discord_destination')})
        self.app = HostedApplication(service=SimpleNamespace(oauth=oauth))

    def request(self, method, suffix, body=None):
        raw = json.dumps(body or {}).encode()
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': '/api/workspaces/%s/channels/%s/%s' % (self.WORKSPACE, self.CONNECTION, suffix),
                   'wsgi.url_scheme': 'https', 'HTTP_HOST': 'rafii.example.invalid', 'HTTP_AUTHORIZATION': 'Bearer ' + 'x' * 40,
                   'HTTP_X_POSTRIFF_REQUEST': 'founder-alpha', 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)),
                   'wsgi.input': io.BytesIO(raw), 'QUERY_STRING': ''}
        statuses = []
        b''.join(self.app._handle(environ, lambda status, headers: statuses.append(status)))
        return statuses[0]

    def test_the_four_calls_that_read_several_times_are_booked(self):
        for method, suffix, body, name in (('GET', 'destinations', None, 'destinations'),
                                           ('POST', 'destination', {'destinationId': '1'}, 'choose_destination'),
                                           ('POST', 'verify', {}, 'verify'),
                                           ('POST', 'oauth/complete', {'state': 's', 'code': 'c'}, 'complete')):
            with self.subTest(route=suffix):
                self.seen.clear()
                self.assertTrue(self.request(method, suffix, body).startswith('200'))
                self.assertEqual(self.seen, [(name, BOOK_AHEAD_SECONDS)])

    def test_the_other_routes_stay_immediate(self):
        for method, suffix, body, name in (('GET', 'creator-info', None, 'creator_info'),
                                           ('POST', 'oauth/start', {}, 'start'),
                                           ('DELETE', 'destinations/1234567', None, 'remove_discord_destination')):
            with self.subTest(route=suffix):
                self.seen.clear()
                self.request(method, suffix, body)
                self.assertEqual(self.seen, [(name, 0.0)])

    def test_a_call_that_fails_leaves_nothing_booked_behind(self):
        self.app.service.oauth.destinations = self.record('destinations', fail=True)
        self.assertTrue(self.request('GET', 'destinations').startswith('409'))
        self.assertEqual(current_book_ahead(), 0.0)


if __name__ == '__main__':
    unittest.main()
