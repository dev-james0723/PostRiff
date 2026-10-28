"""Offline contracts for the bearer budget: the person's own user-bearer calls on a budget of their own (the owner's D-2 option 1).

The written budget was "25 requests a second across every credential". With the lane's per-post ledger of 7 requests (6 with the
bot token, 1 with the person's bearer: the grant check `GET /oauth2/@me`) the bearer call took one of every seven slots of the bot's
ceiling although it does not touch the bot's global limit. The owner redefined the budget (reply 16, AUTHORIZATION-RECORD.md):
bot-token requests at most 25 a second, bearer calls budgeted separately. What must hold, and is proved here on the shared
MemoryLedger double with a fake clock:

  * a request authorized with a user bearer (credential kind `user`) is charged to a second exact sliding window with its own cap,
    window and row (`01:`); every other kind (bot, oauth, webhook) stays on the application row (`00:`), whose ceiling is untouched;
  * the two classes never leak into each other: a full bot class leaves the bearer class whole and the reverse, each quotes its own
    window, each is exact over its own wire times (both saturated at once, and over randomized lives);
  * the bearer request still looks at the application row's hold, so the runbook's stop covers it; a hold on the bearer row stops
    only the bearer class;
  * booking and the slot kept for callers that cannot wait apply to the bearer class like the bot's;
  * a policy without the two bearer fields is what it was: the bearer calls stay in the application budget;
  * every call site of the person's bearer reaches the coordinator as kind `user` (the grant check, the profile read, the server
    list), and the client-secret and webhook calls do not.

The real PostgreSQL proof (both classes saturated by threads at once) is test_discord_rate_bearer_postgres.py. No network, no
credentials.
"""
import secrets
import unittest
from unittest.mock import patch

from postriff_phase2.discord.oauth import DiscordConnections
from postriff_phase2.discord.rate_limits import (
    SharedPostgresBudget, RequestIdentity, RateDelayed, RateCoordinatorUnavailable, SafetyPolicy, HOLD_WAIT_SECONDS)
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_rate_booking import Booked
from test_discord_rate_ceiling import T0, EPS, OK, busiest_closed_window, policy
from test_discord_rate_limits import MemoryLedger, APP

USER = '444444444444444444'
SPAN = 1 + EPS      # window 1, no guard in these tests, one tick of the database clock


class Classes(Booked):
    """Bot cap 3, bearer cap 2, both windows 1 s, no guard, no reserve: the arithmetic at its plainest."""
    bearer_capacity = 2

    def setUp(self):
        super().setUp(3, 1, bearer_capacity=self.bearer_capacity, bearer_window_seconds=1)
        self.user = RequestIdentity.make(APP, 'user', 'synthetic-' + secrets.token_hex(8), USER)

    def row(self, prefix):
        return self.db.states[prefix + self.s.application_key]

    def app_row(self):
        return self.row('00:')

    def bearer_row(self):
        return self.row('01:')

    def read_as(self, identity, ahead=0.0, observe=True):
        permit = self.s.reserve_read('GET', self.path(), identity=identity, book_ahead=ahead)
        if observe:
            self.s.observe(permit, OK)
        self.forget_routes()
        return permit

    def bot(self, **kw):
        return self.read_as(self.identity, **kw)

    def bearer(self, **kw):
        return self.read_as(self.user, **kw)

    def wires_of(self, user):
        return sorted(MemoryLedger.wire_time(r) for r in self.db.admissions.values() if (r['kind'] == 'user') == user)


class OwnRow(Classes):
    def test_a_bearer_request_is_charged_to_the_bearer_row_and_only_looks_at_the_application_row(self):
        self.at(0)
        self.bearer()
        self.at(.3)
        self.bearer()
        self.assertEqual((self.bearer_row()['cap'], self.bearer_row()['window']), (2, 1))
        self.assertEqual(self.bearer_row()['left'], 1, 'the horizon of the last admission has room for one more bearer call')
        self.assertEqual((self.app_row()['cap'], self.app_row()['left']), (3, 3), 'the application row was not charged')
        for admission in self.db.admissions.values():
            self.assertIn('00:' + self.s.application_key, admission['keys'], 'it was admitted under the application row\'s hold')
            self.assertIn('01:' + self.s.application_key, admission['keys'])

    def test_a_bot_request_never_touches_the_bearer_row(self):
        self.at(0)
        self.bot()
        self.assertNotIn('01:' + self.s.application_key, self.db.states, 'a bot request does not even seed it')
        for admission in self.db.admissions.values():
            self.assertNotIn('01:' + self.s.application_key, admission['keys'])

    def test_a_full_bot_class_leaves_the_bearer_class_whole(self):
        self.at(0)
        for _ in range(3):
            self.bot()
        self.denied(self.bot)
        self.bearer()
        self.bearer()
        error = self.denied(self.bearer)
        self.assertAlmostEqual(error.retry_after_seconds, SPAN, places=6, msg='the bearer\'s own two wires, at 0')
        self.assertEqual(error.rate_scope_kind, 'application', 'a spent budget is a system-wide cause for the lane, whichever class')

    def test_a_full_bearer_class_leaves_the_bot_class_whole(self):
        self.at(0)
        self.bearer()
        self.bearer()
        self.denied(self.bearer)
        for _ in range(3):
            self.bot()
        error = self.denied(self.bot)
        self.assertAlmostEqual(error.retry_after_seconds, SPAN, places=6)

    def test_each_class_quotes_its_own_window(self):
        for offset in (0, .2, .4):
            self.at(offset)
            self.bot()
        for offset in (.1, .6):
            self.at(offset)
            self.bearer()
        self.at(.7)
        self.assertAlmostEqual(self.denied(self.bot).retry_after_seconds, .3 + EPS, places=6, msg='the bot\'s oldest wire (0) leaves first')
        self.assertAlmostEqual(self.denied(self.bearer).retry_after_seconds, .4 + EPS, places=6, msg='the bearer\'s (.1)')

    def test_both_classes_saturated_at_once_are_exact_each_over_its_own_wires_and_neither_slows_the_other(self):
        for step in range(121):                       # six seconds in twentieths
            self.at(step * .05)
            for ask in (self.bot, self.bearer):
                try:
                    ask()
                except RateDelayed:
                    pass
        bot, bearer = self.wires_of(False), self.wires_of(True)
        self.assertLessEqual(busiest_closed_window(bot, 1.0), 3)
        self.assertLessEqual(busiest_closed_window(bearer, 1.0), 2)
        # a slot frees strictly more than a window after its wire: six rounds in six seconds, at 0, 1.05, 2.1, ... 5.25
        self.assertEqual((len(bot), len(bearer)), (18, 12), 'each class got all it is entitled to: saturating the other took nothing')

    def test_a_policy_without_the_bearer_fields_keeps_the_bearer_calls_in_the_application_budget(self):
        self.make(3, 1)
        self.at(0)
        self.bearer()
        self.bearer()
        self.bot()
        self.denied(self.bearer)
        self.denied(self.bot)
        self.assertNotIn('01:' + self.s.application_key, self.db.states)
        self.assertEqual(self.app_row()['cap'], 3)

    def test_the_client_secret_and_webhook_calls_stay_in_the_application_budget(self):
        other = [RequestIdentity.make(APP, 'oauth', 'synthetic-' + secrets.token_hex(8)),
                 RequestIdentity.make(APP, 'webhook', 'synthetic-' + secrets.token_hex(12))]
        self.at(0)
        self.read_as(other[0])
        self.read_as(other[1])
        self.bot()
        self.denied(self.bot)
        self.bearer()
        self.bearer()
        self.denied(self.bearer)
        for admission in self.db.admissions.values():
            if admission['kind'] != 'user':
                self.assertNotIn('01:' + self.s.application_key, admission['keys'])


class Holds(Classes):
    def test_a_hold_on_the_application_row_stops_the_bearer_class_too(self):
        self.at(0)
        self.bot()
        self.bearer()
        self.app_row()['hold'] = True
        for ask in (self.bot, self.bearer):
            error = self.denied(ask)
            self.assertEqual((error.rate_cause, error.rate_scope_kind), ('hold', 'embargo'))
            self.assertAlmostEqual(error.retry_after_seconds, HOLD_WAIT_SECONDS)

    def test_a_hold_on_the_bearer_row_stops_only_the_bearer_class(self):
        self.at(0)
        self.bearer()
        self.bearer_row()['hold'] = True
        error = self.denied(self.bearer)
        self.assertEqual(error.rate_cause, 'hold')
        self.bot()
        self.bot()

    def test_a_create_permit_of_the_bearer_class_under_a_hold_is_refused_not_waited(self):
        self.at(0)
        self.bearer()
        self.app_row()['hold'] = True
        with self.assertRaises(RateCoordinatorUnavailable):
            self.s.reserve('GET', self.path(), identity=self.user)


class BookingAndReserve(Classes):
    def test_the_bearer_class_is_booked_like_the_bot_class(self):
        self.at(0)
        self.bearer()
        self.bearer()
        self.at(.5)
        self.bearer(ahead=1.0)
        self.assertAlmostEqual(sum(self.sleeps), .5 + EPS, places=6, msg='it slept until the slot, 1 s and a tick after the oldest wire')
        self.assertEqual(self.s.booking_stats()['bookings'], 1)
        self.assertAlmostEqual(self.wires_of(True)[-1], T0 + SPAN, places=6)
        self.assertEqual(self.wires_of(False), [], 'and the bot class was not asked for anything')

    def test_a_full_bearer_horizon_refuses_with_its_own_wait_and_the_bot_class_still_books_at_once(self):
        self.at(0)
        self.bearer()
        self.bearer()
        for _ in range(2):
            self.at(.5)
            self.bearer(ahead=1.0)                      # both booked at 1 + a tick
        self.at(.5)
        error = self.denied(lambda: self.bearer(ahead=1.0))
        self.assertAlmostEqual(error.retry_after_seconds, .5 + 2 * EPS, places=6, msg='the booked wires leave a span after 1 + a tick, less the horizon')
        row = self.bearer_row()
        self.assertEqual(row['left'], 0)
        self.assertGreater(row['reset'], T0 + .5)
        sleeps = len(self.sleeps)
        self.at(.5)
        self.bot(ahead=1.0)
        self.assertEqual(len(self.sleeps), sleeps, 'the bot class found its slot at once')
        self.assertEqual(self.app_row()['left'], 2)

    def test_each_class_published_room_is_its_own(self):
        self.at(0)
        self.bot()
        self.bearer()
        self.at(.2)
        self.bot()
        # bot cap 3: at .2 the wire at 0 has left the horizon's last span, one bot wire is in it; bearer cap 2: its one wire is in it
        self.assertEqual((self.app_row()['left'], self.bearer_row()['left']), (2, 1))


class ReserveKeptPerClass(Classes):
    reserve_slots = 1
    bearer_capacity = 3

    def test_a_caller_that_cannot_wait_keeps_a_slot_in_each_class(self):
        for ask in (self.bot, self.bearer):
            self.setUp()
            self.at(0)
            ask(ahead=1.0)
            ask(ahead=1.0)                              # bookings fill cap - 1 = 2 of the 3 at once
            self.at(.5)
            ask(ahead=1.0)                              # the third is placed after the first leaves, 1 s and a tick after it
            self.assertAlmostEqual(sum(self.sleeps), .5 + EPS, places=6)
            self.at(.5)
            ask()                                       # a web caller still finds the slot the bookings left
            self.denied(ask)                            # and only that one


class PolicyFields(unittest.TestCase):
    def parse(self, **more):
        return SafetyPolicy.parse({**policy(25, 1), **more})

    def test_a_policy_without_the_fields_has_no_separate_bearer_budget(self):
        parsed = self.parse()
        self.assertEqual(parsed.bearer_capacity, 0)

    def test_a_policy_with_both_fields_has_one(self):
        parsed = self.parse(bearer_capacity=10, bearer_window_seconds=1)
        self.assertEqual((parsed.bearer_capacity, parsed.bearer_window_seconds), (10, 1))

    def test_one_field_alone_or_a_bad_value_is_refused_like_every_other_malformed_policy(self):
        for more in ({'bearer_capacity': 10}, {'bearer_window_seconds': 1},
                     {'bearer_capacity': 0, 'bearer_window_seconds': 1}, {'bearer_capacity': 100001, 'bearer_window_seconds': 1},
                     {'bearer_capacity': 10.5, 'bearer_window_seconds': 1}, {'bearer_capacity': True, 'bearer_window_seconds': 1},
                     {'bearer_capacity': 10, 'bearer_window_seconds': .04}, {'bearer_capacity': 10, 'bearer_window_seconds': 86401},
                     {'bearer_capacity': 10, 'bearer_window_seconds': float('nan')}, {'bearer_capacity': 10, 'bearer_window_seconds': 'x'},
                     {'bearer_capacity': 10, 'bearer_window_seconds': 1, 'bearer_extra': 1}):
            with self.subTest(more=more), self.assertRaises(RateCoordinatorUnavailable):
                self.parse(**more)


class CallSites(unittest.TestCase):
    """Every place the application sends a request authorized with the person's own bearer, through the real provider and the real
    helper that makes the call: which row is charged. The lane's per-post grant check is `verified_authorization`; the others are
    the rest of the user-bearer family (the profile read after a token exchange or refresh, the server list, the webhook
    authorizer's reads). The client secret's token calls and the webhook secret's calls are not bearer calls."""
    def setUp(self):
        for name, value in (('SLOT_GUARD_SECONDS', 0.0), ('IMMEDIATE_RESERVE', 0)):
            patcher = patch.object(SharedPostgresBudget, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = MemoryLedger(now=T0)
        self.s = SharedPostgresBudget(self.db.connection, APP, policy=policy(3, 1, bearer_capacity=2, bearer_window_seconds=1))
        self.calls = []
        # Discord names a bucket with a limit far above the budgets, so a route's own window never binds: only the budgets do.
        learned = {'X-RateLimit-Bucket': 'synthetic-bucket', 'X-RateLimit-Limit': '100', 'X-RateLimit-Remaining': '99',
                   'X-RateLimit-Reset-After': '1'}

        def transport(method, url, **kwargs):
            self.calls.append((method, url))
            body = {'application': {'id': APP}, 'user': {'id': USER, 'username': 'synthetic'}, 'scopes': ['identify', 'guilds'], 'id': USER}
            return {'status': 200, 'headers': dict(learned), 'body': [] if 'guilds' in url else body}
        self.p = DiscordProvider(APP, 'synthetic-' + secrets.token_hex(8), 'synthetic-' + secrets.token_hex(8), 'https://rafii.invalid',
                                 transport=transport)
        self.p.rate_v1_enabled, self.p.rate_limiter = True, self.s
        self.p.connections_v2_enabled = self.p.authorization_v2_enabled = True

        class Oauth:   # the one thing DiscordConnections asks of its service for these calls: the provider
            _provider = staticmethod(lambda name: self.p)
        self.connections = DiscordConnections(Oauth())
        self.bearer = 'synthetic-' + secrets.token_hex(12)

    def charged(self):
        """('00:' or '01:' charged, for each admission, in order): the policy row that took the debit."""
        key = self.s.application_key
        return [('01:' if '01:' + key in row['keys'] and row['kind'] == 'user' else '00:')
                for row in sorted(self.db.admissions.values(), key=lambda r: r['seq'])]

    def test_the_grant_check_is_charged_to_the_bearer_budget(self):
        user, scopes = self.connections.verified_authorization(self.bearer, ['identify'], USER)
        self.assertEqual(user['id'], USER)
        self.assertEqual(self.calls, [('GET', self.p.API + '/oauth2/@me')])
        self.assertEqual(self.charged(), ['01:'])
        self.assertEqual((self.db.states['01:' + self.s.application_key]['left'], self.db.states['00:' + self.s.application_key]['left']), (1, 3))

    def test_the_profile_read_that_follows_a_token_exchange_or_refresh_is_too(self):
        self.connections.verified_user(self.bearer, ['identify'], USER)
        self.assertEqual([call[1][len(self.p.API):] for call in self.calls], ['/oauth2/@me', '/users/@me'])
        self.assertEqual(self.charged(), ['01:', '01:'])

    def test_the_server_list_is_too(self):
        self.connections.user_guilds({'bearer': self.bearer, 'userId': USER, 'scopes': ['identify', 'guilds']})
        self.assertEqual(self.charged(), ['01:'])

    def test_the_client_secret_s_token_calls_stay_in_the_application_budget(self):
        self.connections._response('POST', '/oauth2/token', None, user_id=USER, form={'grant_type': 'refresh_token', 'refresh_token': 'x'})
        self.assertEqual(self.charged(), ['00:'])
        self.assertNotIn('01:' + self.s.application_key, self.db.states)

    def test_the_bot_and_a_webhook_secret_stay_in_the_application_budget(self):
        self.p._bot('GET', '/guilds/700000000000000001')
        self.p._discord_http('GET', '/webhooks/700000000000000002/' + 'w' * 24, credential_kind='webhook', bearer='w' * 24,
                             headers={'User-Agent': 'x'})
        self.assertEqual(self.charged(), ['00:', '00:'])

    def test_the_bearer_budget_is_spent_by_the_bearer_alone(self):
        for _ in range(2):
            self.connections.verified_authorization(self.bearer, ['identify'], USER)
        with self.assertRaises(RateDelayed):
            self.connections.verified_authorization(self.bearer, ['identify'], USER)   # refused whole, before any request
        self.assertEqual(len(self.calls), 2)
        for _ in range(3):
            self.p._bot('GET', '/guilds/700000000000000003')
        self.assertEqual(len(self.calls), 5)


if __name__ == '__main__':
    unittest.main()
