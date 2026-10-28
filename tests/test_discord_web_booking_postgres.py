"""Real-PostgreSQL proof of what booking the web calls that read Discord several times in a row does, and what it costs
(docs/w02/AS-BUILT.md, "Web calls that read several times"; the independent review's IMMEDIATE_RESERVE measurement).

The lane is twelve booking loops (reads and creates, as the lane makes them) that keep the application window saturated; the web
callers make a channel list, which is the real DiscordProvider.destinations (four reads in a row) against the in-process mock
Discord. The same load runs with the web calls immediate (what they were) and inside rate_limits.web_reads() (what they are):

  * the exact ceiling holds in every phase, counted on the database clock over every admission of both;
  * booked, the web calls complete (light demand: about one call a second; heavy: three threads asking back to back), where
    immediate they are refused after the first read or two while the lane saturates;
  * the lane is not starved: its creates and reads go on at a rate that the web's share of the window explains;
  * how long a web call takes under the burst is reported (one JSON line on stderr per phase, `web-booking-report`).

A disposable cluster (tests/discord_lane_fixture.py), the repository's schema, the real coordinator. Runs where POSTRIFF_PG_BIN names
the PostgreSQL server binaries; synthetic ids only, no network. The share asserted for one workspace's flood needs the per-workspace
read throttle of G2a (discord/oauth.py, READ_LIMIT_WORKSPACE) and is skipped where it is not merged yet.
"""
import json
import random
import secrets
import sys
import threading
import time
import unittest
from unittest.mock import patch

import discord_lane_fixture as F
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import oauth as discord_oauth
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, RateDelayed, booking, web_reads
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_rate_ceiling_postgres import Stack, busiest_closed

CAP = 25
LOOPS = 12


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else None


class Counted:
    """The transport, counting what each kind of caller sent to Discord (a thread's name begins with its kind)."""

    def __init__(self, wire):
        self.wire, self.lock, self.sent = wire, threading.Lock(), {}

    def __call__(self, *args, **kwargs):
        kind = threading.current_thread().name.split('-')[0]
        with self.lock:
            self.sent[kind] = self.sent.get(kind, 0) + 1
        return self.wire(*args, **kwargs)


class Load:
    """The lane's loops and the web's callers on one Stack for `seconds`."""

    def __init__(self, stack, tenants=40):
        self.stack = stack
        self.counted = Counted(stack.wire)
        stack.provider.transport = self.counted
        answered = stack.wire._answer

        def answer(method, path, body, now):
            result = answered(method, path, body, now)
            if path == '/oauth2/applications/@me' and result['status'] == 200:
                result = {**result, 'body': {'id': stack.app}}      # the mock's application is the fixture's; this stack has its own
            return result
        stack.wire._answer = answer
        self.guard = threading.Lock()
        self.lane = {'reads': 0, 'creates': 0, 'expired': 0, 'delayed': 0, 'errors': 0}
        self.web = {'ok': 0, 'refused': 0, 'errors': 0, 'throttled': 0, 'seconds': [], 'reads': 0}

    def token(self, number):
        guild = self.stack.tenants[number % len(self.stack.tenants)].guild
        return json.dumps({'v': 2, 'kind': 'installation', 'applicationId': self.stack.provider.client_id, 'botUserId': F.BOT,
                           'user': F.USER, 'guild': guild, 'channel': None})

    def lane_loop(self, index, stop):
        stack, rng = self.stack, random.Random(index)
        while time.monotonic() < stop:
            tenant = stack.tenants[rng.randrange(len(stack.tenants))]
            try:
                if rng.random() < .14:
                    path = '/channels/%s/messages' % tenant.channel
                    permit = stack.limiter.reserve('POST', path, identity=stack.identity, book_ahead=1.0)
                    time.sleep(rng.uniform(.15, .5))
                    try:
                        stack.limiter.consume(permit, 'POST', path)
                    except RateDelayed:
                        with self.guard:
                            self.lane['expired'] += 1
                        continue
                    answer = self.counted('POST', DiscordProvider.API + path, body={'content': 'synthetic', 'nonce': secrets.token_hex(6)})
                    stack.limiter.observe(permit, answer)
                    with self.guard:
                        self.lane['creates'] += 1
                else:
                    with booking(1.0):
                        stack.provider._bot('GET', '/guilds/' + tenant.guild)
                    with self.guard:
                        self.lane['reads'] += 1
            except RateDelayed as error:
                with self.guard:
                    self.lane['delayed'] += 1
                time.sleep(min(error.retry_after_seconds, 1.0) + secrets.randbelow(26) / 1000)
            except RateCoordinatorUnavailable:
                with self.guard:
                    self.lane['errors'] += 1

    def web_loop(self, index, stop, *, booked, gap, call=None):
        stack, rng = self.stack, random.Random(1000 + index)
        while time.monotonic() < stop:
            began = time.monotonic()
            try:
                if call is not None:
                    call(index, booked)
                elif booked:
                    with web_reads():
                        stack.provider.destinations(self.token(rng.randrange(1000)))
                else:
                    stack.provider.destinations(self.token(rng.randrange(1000)))
                with self.guard:
                    self.web['ok'] += 1
                    self.web['seconds'].append(time.monotonic() - began)
            except Throttled:
                with self.guard:
                    self.web['throttled'] += 1
            except RateDelayed:
                with self.guard:
                    self.web['refused'] += 1
            except (RateCoordinatorUnavailable, AlphaError) as error:
                with self.guard:
                    self.web['errors'] += 1
                    self.web.setdefault('why', []).append(repr(error)[:100])
            time.sleep(rng.uniform(gap / 2, gap * 1.5))

    def run(self, seconds, *, web=0, booked=False, gap=.05, call=None, loops=LOOPS):
        stop = time.monotonic() + seconds
        threads = ([threading.Thread(target=self.lane_loop, args=(n, stop), name='lane-%d' % n) for n in range(loops)]
                   + [threading.Thread(target=self.web_loop, args=(n, stop), kwargs={'booked': booked, 'gap': gap, 'call': call},
                                       name='web-%d' % n) for n in range(web)])
        began = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.monotonic() - began
        stamps = self.stack.stamps()
        calls = self.web['ok'] + self.web['refused']
        seconds_ok = self.web['seconds']
        sent = self.counted.sent
        return {'seconds': round(elapsed, 1), 'busiestClosedSecond': busiest_closed(stamps, 1.0), 'admissionsPerSecond': round(len(stamps) / elapsed, 1),
                'laneCreatesPerSecond': round(self.lane['creates'] / elapsed, 2), 'laneReadsPerSecond': round(self.lane['reads'] / elapsed, 1),
                'laneExpiredUnused': self.lane['expired'], 'laneErrors': self.lane['errors'],
                'webCalls': calls, 'webThrottled': self.web['throttled'], 'webCompleted': self.web['ok'], 'webCompletedShare': round(self.web['ok'] / calls, 2) if calls else None,
                'webReadsToDiscord': sent.get('web', 0), 'webErrors': self.web['errors'],
                'webSecondsP50': round(percentile(seconds_ok, .5), 2) if seconds_ok else None,
                'webSecondsP90': round(percentile(seconds_ok, .9), 2) if seconds_ok else None,
                'webSecondsMax': round(max(seconds_ok), 2) if seconds_ok else None}


class Throttled(Exception):
    """The per-workspace or per-member read throttle (G2a) refused the call before any request to Discord."""


def report(label, result):
    print('web-booking-report ' + json.dumps({'phase': label, **result}), file=sys.stderr, flush=True)


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
class WebCallsWhileTheLaneSaturates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def phase(self, label, seconds=8, **kwargs):
        self.cluster.reset()
        stack = Stack(self.cluster, capacity=CAP, latency=.05, tenants=40)
        result = Load(stack).run(seconds, **kwargs)
        report(label, result)
        self.assertLessEqual(result['busiestClosedSecond'], CAP, label + ': the ceiling holds over every admission of both')
        self.assertEqual((result['laneErrors'], result['webErrors']), (0, 0), label)
        return result

    def test_a_channel_list_completes_booked_where_it_is_refused_immediate_and_the_lane_goes_on(self):
        alone = self.phase('lane alone')
        self.assertGreater(alone['admissionsPerSecond'], 12, 'the lane saturated the window')
        for demand, web, gap, seconds in (('light', 1, 1.0, 9), ('heavy', 3, .05, 14)):
            immediate = self.phase(demand + ' demand, immediate', seconds, web=web, gap=gap)
            booked = self.phase(demand + ' demand, booked', seconds, web=web, gap=gap, booked=True)
            self.assertGreaterEqual(booked['webCompletedShare'], .6, demand + ': a booked call completes')
            self.assertLess(booked['webSecondsP50'], 8, demand + ': the wait is a few seconds, not a timeout')
            if demand == 'heavy':
                self.assertGreater(booked['webCompletedShare'], immediate['webCompletedShare'] + .3,
                                   'three threads asking back to back: immediate they are refused, booked they wait their turn')
            # The lane is not starved: it gives the web the share of the window the web used, not more.
            self.assertGreaterEqual(booked['laneCreatesPerSecond'], .5 * alone['laneCreatesPerSecond'], demand + ': the lane\'s creates')
            self.assertGreaterEqual(booked['laneReadsPerSecond'], .5 * alone['laneReadsPerSecond'], demand + ': the lane\'s reads')


THROTTLE = hasattr(discord_oauth, 'READ_LIMIT_WORKSPACE')


@unittest.skipIf(F.FENCED, F.SKIP_FENCED)
@unittest.skipUnless(F.AVAILABLE, F.SKIP_UNAVAILABLE)
@unittest.skipUnless(THROTTLE, 'needs the per-workspace read throttle of G2a (discord/oauth.py, READ_LIMIT_WORKSPACE); skipped until it is merged')
class OneWorkspacesFlood(unittest.TestCase):
    """A workspace that asks for channel lists as fast as it can is held to its throttle BEFORE any request to Discord, so the
    share of the window it can take is bounded by the throttle, and the lane goes on. The production limits are 30 a minute for a
    member and 120 for a workspace (about four reads a call); the test uses 10 and 20 so that a few seconds reach them, and reports
    the reads a call made, which is what scales them to the production numbers."""
    WORKSPACE = '00000000-0000-4000-8000-0000000000f1'
    MEMBER_LIMIT, WORKSPACE_LIMIT = 10, 20

    @classmethod
    def setUpClass(cls):
        cls.cluster = F.Cluster()

    @classmethod
    def tearDownClass(cls):
        cls.cluster.close()

    def run_flood(self, threads, seconds):
        counts, lock = {}, threading.Lock()

        def throttle(cur, scope, limit, window):        # hosted.throttle's semantics: a fixed-window counter, 429 above the limit
            with lock:
                counts[scope] = counts.get(scope, 0) + 1
                if counts[scope] > limit:
                    counts[scope] -= 1
                    raise AlphaError('Too many attempts. Wait a minute and try again.', 429)
        self.cluster.reset()
        stack = Stack(self.cluster, capacity=CAP, latency=.05, tenants=40)
        load = Load(stack)

        def flood_call(index, booked):
            try:
                discord_oauth.DiscordConnections.admit_read(None, None, self.WORKSPACE, 'member-%d' % (index % 4))
            except AlphaError as error:
                if error.status == 429:
                    raise Throttled() from error
                raise
            with web_reads():
                stack.provider.destinations(load.token(index))
        with patch('postriff_phase2.hosted.throttle', throttle), \
                patch.object(discord_oauth, 'READ_LIMIT_MEMBER', (self.MEMBER_LIMIT, 60)), \
                patch.object(discord_oauth, 'READ_LIMIT_WORKSPACE', (self.WORKSPACE_LIMIT, 60)):
            result = load.run(seconds, web=threads, booked=True, gap=.02, call=flood_call)
        return result, counts

    def test_a_flood_from_one_workspace_takes_no_more_than_its_throttle_and_the_lane_goes_on(self):
        self.cluster.reset()
        alone = Load(Stack(self.cluster, capacity=CAP, latency=.05, tenants=40)).run(16)
        report('lane alone, 16 s', alone)
        result, counts = self.run_flood(12, 16)
        report('flood of 12 threads from one workspace, throttle %d calls' % self.WORKSPACE_LIMIT, result)
        admitted = result['webCalls']                    # completed or refused by the coordinator: they passed the throttle
        self.assertLessEqual(counts['discord-read:' + self.WORKSPACE], self.WORKSPACE_LIMIT, 'the workspace counter')
        self.assertLessEqual(admitted, self.WORKSPACE_LIMIT, 'calls that passed the throttle')
        self.assertGreater(result['webThrottled'], 0, 'the flood reached the throttle (otherwise this proves nothing)')
        self.assertLessEqual(result['webReadsToDiscord'], self.WORKSPACE_LIMIT * 6, 'at most six reads a call (the identity read is cached)')
        self.assertLessEqual(result['busiestClosedSecond'], CAP, 'the ceiling holds over every admission of both')
        self.assertEqual((result['laneErrors'], result['webErrors']), (0, 0))
        self.assertGreaterEqual(result['laneCreatesPerSecond'], .4 * alone['laneCreatesPerSecond'], 'the lane\'s creates go on')
        self.assertGreaterEqual(result['laneReadsPerSecond'], .4 * alone['laneReadsPerSecond'], 'and so do its reads')


if __name__ == '__main__':
    unittest.main()
