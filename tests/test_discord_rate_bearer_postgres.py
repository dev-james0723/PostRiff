"""Real-PostgreSQL proof of the bearer budget (docs/w02/OPEN-QUESTIONS.md, Q21): the person's own bearer calls on a budget of their
own, beside the bot's, both exact, neither able to take a slot of the other.

A disposable cluster (tests/discord_lane_fixture.py), the repository's schema, the real coordinator and DiscordProvider, Discord as
the in-process mock. The bot's class is read through `provider._bot`, the bearer's through `provider._discord_http(... kind 'user')`,
the way the application makes them, from many threads at once, polling and booking. Every ceiling is computed from the admission
table on the database clock in whole microseconds, per credential kind: the busiest CLOSED second of the bot class's wire times may
hold at most its cap, the bearer class's at most its own. The runbook's hold is the runbook's SQL.

Runs where POSTRIFF_PG_BIN names the PostgreSQL server binaries; synthetic ids only, no network.
"""
import random
import secrets
import threading
import time
import unittest

import discord_lane_fixture as F
from postriff_phase2.discord import rate_limits
from postriff_phase2.discord.rate_limits import RateDelayed, RateCoordinatorUnavailable
from test_discord_rate_booking_postgres import Jittered
from test_discord_rate_ceiling_postgres import Stack, busiest_closed

BOT_CAP, BEARER_CAP = 12, 6        # a rate this box can carry while other agents load it; the shares are what is asserted
SUSTAINED = 1.05                   # a slot frees a window and the guard after its wire time: cap / 1.05 a second at most


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class TwoBudgetsOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def setUp(self):
        self.cluster.reset()

    def stack(self, tenants=6):
        stack = Stack(self.cluster, capacity=BOT_CAP, latency=.03, tenants=tenants, bearer_capacity=BEARER_CAP, bearer_window_seconds=1)
        stack.provider.transport = Jittered(stack.wire, .05)
        stack.user = F.USER
        stack.token = 'synthetic-' + secrets.token_hex(12)
        return stack

    def bearer_read(self, stack, number):
        """One real provider GET made with the person's own bearer: admission, mock Discord, observation."""
        guild = stack.tenants[number % len(stack.tenants)].guild
        return stack.provider._discord_http('GET', '/guilds/' + guild, credential_kind='user', bearer=stack.token, user_id=stack.user,
                                            headers={'Authorization': 'Bearer ' + stack.token, 'User-Agent': 'DiscordBot (synthetic, 1)'})

    def stamps(self, stack, user):
        with self.cluster.connect(autocommit=True) as db:
            return [row[0] for row in db.execute(
                "SELECT (extract(epoch from coalesce(sent_at,reserved_at))*1000000)::bigint FROM public.pr_discord_request_admissions "
                "WHERE application_key=%s AND (credential_kind='user')=%s ORDER BY request_seq", (stack.key, user))]

    def hammer(self, stack, bots, bearers, seconds, *, book):
        """`bots` threads reading as the bot and `bearers` reading as the person, each backing off by the quote as a caller does."""
        stop, lock = time.monotonic() + seconds, threading.Lock()
        counts = {'bot': 0, 'user': 0, 'delayed': {'bot': 0, 'user': 0}, 'other': []}

        def run(index, kind):
            rng = random.Random(index)
            while time.monotonic() < stop:
                try:
                    with rate_limits.booking(1.0 if book else 0.0):
                        if kind == 'bot':
                            stack.read(rng.randrange(1000))
                        else:
                            self.bearer_read(stack, rng.randrange(1000))
                    with lock:
                        counts[kind] += 1
                except RateDelayed as error:
                    with lock:
                        counts['delayed'][kind] += 1
                    time.sleep(min(error.retry_after_seconds, 1.0) + secrets.randbelow(26) / 1000)
                except Exception as error:  # noqa: BLE001 - reported by the test
                    with lock:
                        counts['other'].append(repr(error)[:120])
        threads = ([threading.Thread(target=run, args=(n, 'bot')) for n in range(bots)]
                   + [threading.Thread(target=run, args=(1000 + n, 'user')) for n in range(bearers)])
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return counts

    def steady(self, micros, seconds):
        """Admissions a second in the middle of the run, the first and last second left out."""
        micros = sorted(micros)
        middle = [m for m in micros if micros[0] + 1_000_000 <= m <= micros[-1] - 1_000_000]
        return len(middle) / max(1.0, seconds - 2.0)

    def test_both_classes_saturated_by_threads_at_once_each_keep_their_own_exact_ceiling(self):
        seconds = 8
        for book in (False, True):
            with self.subTest(booking=book):
                self.setUp()
                stack = self.stack()
                counts = self.hammer(stack, 24, 12, seconds, book=book)
                bot, user = self.stamps(stack, False), self.stamps(stack, True)
                self.assertEqual(counts['other'], [])
                self.assertGreater(len(bot), 40, 'the bot class was busy enough to meet its cap')
                self.assertGreater(len(user), 20, 'the bearer class was busy enough to meet its cap')
                self.assertLessEqual(busiest_closed(bot, 1.0), BOT_CAP, 'the bot class, on the database clock')
                self.assertLessEqual(busiest_closed(user, 1.0), BEARER_CAP, 'the bearer class, on the database clock')
                self.assertGreater(counts['delayed']['bot'] + counts['delayed']['user'] + stack.limiter.booking_stats()['bookings'], 10,
                                   'both classes met a full window')
                # Neither class slowed the other: each got most of what its own cap allows while the other was saturated too.
                self.assertGreaterEqual(self.steady(bot, seconds), .6 * BOT_CAP / SUSTAINED, 'bot admissions a second')
                self.assertGreaterEqual(self.steady(user, seconds), .6 * BEARER_CAP / SUSTAINED, 'bearer admissions a second')
                self.assertEqual(stack.wire.route429, 0)

    def test_the_bearer_class_alone_does_not_touch_the_bot_s_window_and_the_reverse(self):
        stack = self.stack()
        counts = self.hammer(stack, 0, 8, 4, book=False)
        self.assertEqual(counts['other'], [])
        self.assertEqual(self.stamps(stack, False), [], 'no bearer call was charged to the bot class')
        self.assertLessEqual(busiest_closed(self.stamps(stack, True), 1.0), BEARER_CAP)
        with self.cluster.connect(autocommit=True) as db:
            row = db.execute("SELECT limit_count,remaining FROM public.pr_discord_rate_state WHERE scope_key=%s",
                             ('00:' + stack.key,)).fetchone()
        self.assertEqual(row, (BOT_CAP, BOT_CAP), 'the application row was seeded as a guard and never debited')
        stack = self.stack()
        counts = self.hammer(stack, 8, 0, 4, book=False)
        self.assertEqual(counts['other'], [])
        self.assertEqual(self.stamps(stack, True), [])
        with self.cluster.connect(autocommit=True) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM public.pr_discord_rate_state WHERE scope_key=%s", ('01:' + stack.key,)).fetchone(),
                              'a bot request does not even seed the bearer row')

    def test_the_runbook_s_hold_stops_the_bearer_class_too_and_a_hold_on_its_row_stops_only_it(self):
        stack = self.stack()
        stack.read(1)
        self.bearer_read(stack, 1)
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy'")   # the runbook's stop
        for ask in (lambda: stack.read(2), lambda: self.bearer_read(stack, 2)):
            with self.assertRaises((RateDelayed, RateCoordinatorUnavailable)):
                ask()
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE kind = 'policy'")
            db.execute("UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE scope_key = %s", ('01:' + stack.key,))
        stack.read(3)
        with self.assertRaises((RateDelayed, RateCoordinatorUnavailable)):
            self.bearer_read(stack, 3)
        with self.cluster.connect(autocommit=True) as db:
            db.execute("UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE scope_key = %s", ('01:' + stack.key,))
        self.bearer_read(stack, 4)

    def test_the_stored_rows_are_per_class_and_say_what_a_booking_of_each_would_find(self):
        stack = self.stack()
        counts = self.hammer(stack, 24, 12, 5, book=True)
        self.assertEqual(counts['other'], [])
        with self.cluster.connect(autocommit=True) as db:
            rows = {key[:3]: (limit, remaining, reset) for key, limit, remaining, reset in db.execute(
                "SELECT scope_key,limit_count,remaining,extract(epoch FROM reset_at) FROM public.pr_discord_rate_state "
                "WHERE scope_key IN (%s,%s)", ('00:' + stack.key, '01:' + stack.key))}
        self.assertEqual(rows['00:'][0], BOT_CAP)
        self.assertEqual(rows['01:'][0], BEARER_CAP)
        for prefix, cap in (('00:', BOT_CAP), ('01:', BEARER_CAP)):
            self.assertTrue(0 <= rows[prefix][1] <= cap, prefix)


if __name__ == '__main__':
    unittest.main()
