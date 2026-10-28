"""Self-checks of the W-02 capacity harness (scripts/discord_lane_capacity_run.py): it is evidence, so it must fail.

Fast checks (no database): the mock's duplicate counters fire when told to accept a create twice, its trailing-second
counters and its 50/s global ceiling fire on a burst, its isolation check fires on a create sent to another tenant's
channel, and the analysis takes lateness from the mock's own create timestamps and never from the application's
records. The live smoke (needs PostgreSQL server binaries named by POSTRIFF_PG_BIN and psycopg; skipped otherwise)
runs the whole harness on a tiny scale against this repository's own code: 30 posts in 10 workspaces, 20-second cron
period, separate OS processes, real WSGI entry, in about two minutes. CAP_HARNESS_FULL=1 adds a live negative control
with the coordinator policy raised to 200/s, which must trip the 25/s counter.

The harness never reaches a network beyond 127.0.0.1 and reads no application credential.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import discord_lane_cap_analysis as analysis  # noqa: E402
import discord_lane_cap_mock as mock  # noqa: E402

PG_BIN = os.environ.get('POSTRIFF_PG_BIN')
try:
    import psycopg  # noqa: F401
    HAVE_PSYCOPG = True
except ImportError:  # pragma: no cover
    HAVE_PSYCOPG = False
LIVE = bool(PG_BIN and (Path(PG_BIN) / 'initdb').exists() and HAVE_PSYCOPG)
FENCED = '1' in (os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE'), os.environ.get('RAFII_LINKEDIN_SYNTHETIC_FENCE'))


def create(world, index, post, nonce, *, channel=None, at=None):
    body = {'content': 'Capacity harness post [cap-post %s]' % post, 'nonce': nonce, 'enforce_nonce': True,
            'allowed_mentions': {'parse': []}}
    return world.handle('POST', '/channels/%s/messages' % (channel or mock.channel_id(index)),
                        {'authorization': 'Bot ' + mock.BOT_TOKEN}, body)


class MockCounters(unittest.TestCase):
    def test_duplicate_counters_fire_when_the_mock_double_accepts(self):
        world = mock.World(workspaces=10, double_accept_every=2)
        for number in range(4):
            status, _, _, _ = create(world, number, 'w%d-p0' % number, 'nonce-%d' % number)
            self.assertEqual(status, 200)
        self.assertEqual(world.counters['doubleAccepted'], 2)
        self.assertEqual(world.counters['duplicateNonceCreates'], 2)
        self.assertEqual(world.counters['duplicatePostCreates'], 2)
        manifest = [{'index': n, 'workspace': 'w%d' % n, 'post': 'w%d-p0' % n, 'nonce': 'nonce-%d' % n,
                     'due': 0.0, 'expiresAt': 3600.0} for n in range(4)]
        posts, foreign = analysis.per_post(manifest, world.log)
        self.assertEqual(sum(len(p['creates']) - 1 for p in posts.values()), 2, 'analysis counts the double accepts')
        self.assertEqual(sum(len(p['creates_by_post']) - 1 for p in posts.values()), 2)
        self.assertEqual(foreign, 0)

    def test_a_nonce_sent_twice_is_a_duplicate_even_with_a_single_accept_each_time(self):
        world = mock.World(workspaces=10)
        create(world, 1, 'w1-p0', 'same')
        clock = world.clock
        world.clock = lambda: clock() + 6  # past the channel's 5-per-5-second window
        create(world, 1, 'w1-p0', 'same')
        self.assertEqual(world.counters['duplicateNonceCreates'], 1)
        self.assertEqual(world.counters['duplicatePostCreates'], 1)

    def test_trailing_second_counters_and_the_global_ceiling_fire_on_a_burst(self):
        now = [1000.0]
        world = mock.World(workspaces=100, clock=lambda: now[0])
        statuses = []
        for number in range(60):
            now[0] += 0.01  # 60 requests inside 0.6 s
            statuses.append(world.handle('GET', '/guilds/%s' % mock.guild_id(number),
                                         {'authorization': 'Bot ' + mock.BOT_TOKEN}, None)[0])
        self.assertEqual(world.counters['abovePolicyAll'], 35, 'requests 26 to 60 are above 25 in a trailing second')
        self.assertEqual(world.counters['aboveGlobalBot'], 10, 'requests 51 to 60 are above 50')
        self.assertEqual(statuses.count(429), 10, 'and the mock refuses them with a global 429')
        record = next(r for r in world.log if r.get('global429'))
        self.assertEqual(record['status'], 429)
        self.assertEqual(world.peak_bot, 60)

    def test_the_isolation_check_fires_on_a_create_in_another_tenants_channel(self):
        world = mock.World(workspaces=10)
        create(world, 3, 'w3-p0', 'n-own')
        self.assertEqual(world.counters['misrouted'], 0)
        create(world, 3, 'w3-p1', 'n-wrong', channel=mock.channel_id(4))
        self.assertEqual(world.counters['misrouted'], 1)
        self.assertTrue(world.log[-1]['misrouted'])

    def test_a_cloudflare_style_ban_page_is_html_without_a_retry_hint(self):
        world = mock.World(workspaces=10, injections=[{'kind': 'html429', 'route': 'GET /guilds/{id}', 'count': 1}])
        status, headers, body, record = world.handle('GET', '/guilds/%s' % mock.guild_id(1),
                                                     {'authorization': 'Bot ' + mock.BOT_TOKEN}, None)
        self.assertEqual(status, 429)
        self.assertIn('text/html', headers['content-type'])
        self.assertNotIn('retry-after', headers)
        self.assertIn('_html', body)
        self.assertEqual(record['injected'], 'html429')
        # The injected answer still names its server, so the analysis can follow that server's posts.
        self.assertEqual(record['guild'], 1)


    def test_an_injected_route_429_names_a_valid_bucket_id(self):
        """The coordinator holds a route whose 429 names an invalid bucket as a manual hold nobody releases (reviewed
        design); the first injected id carried the template's braces and left five F429 posts scheduled."""
        rules = [{'kind': 'route429', 'route': 'GET /guilds/{id}', 'count': 2, 'retryAfter': 3},
                 {'kind': 'route429', 'route': 'POST /channels/{id}/messages', 'count': 2, 'retryAfter': 3}]
        world = mock.World(workspaces=10, injections=rules)
        auth = {'authorization': 'Bot ' + mock.BOT_TOKEN}
        status, read_headers, body, record = world.handle('GET', '/guilds/%s' % mock.guild_id(1), auth, None)
        self.assertEqual((status, record['injected'], body['global']), (429, 'route429', False))
        status, create_headers, _, _ = create(world, 1, 'w1-p0', 'n-1')
        self.assertEqual(status, 429)
        for headers in (read_headers, create_headers):
            self.assertRegex(headers['x-ratelimit-bucket'], r'^[A-Za-z0-9_-]{1,128}$')
            self.assertTrue(mock.BUCKET_ID.fullmatch(headers['x-ratelimit-bucket']))
            self.assertNotIn('{', headers['x-ratelimit-bucket'])
            self.assertEqual(headers['x-ratelimit-scope'], 'user', 'a route limit, not the global one')
            self.assertEqual(headers['retry-after'], '3.000')
        self.assertNotEqual(read_headers['x-ratelimit-bucket'], create_headers['x-ratelimit-bucket'],
                            'two routes, two buckets')
        # The same route always answers with the same bucket (the coordinator learns it once).
        _, again, _, _ = world.handle('GET', '/guilds/%s' % mock.guild_id(2), auth, None)
        self.assertEqual(again['x-ratelimit-bucket'], read_headers['x-ratelimit-bucket'])
        self.assertEqual(read_headers['x-ratelimit-bucket'], 'injected-guilds-id')
        self.assertEqual(create_headers['x-ratelimit-bucket'], 'injected-channels-id-messages')

    def test_the_injected_bucket_id_stays_valid_for_any_route_template(self):
        for route in ('GET /guilds/{id}', 'GET /guilds/{id}/members/{id}', 'POST /channels/{id}/messages',
                      'PATCH /webhooks/{id}/{token}/messages/{id}', 'GET /users/@me/guilds', 'GET /x/' + 'y' * 300):
            bucket = mock.injected_bucket_id(route)
            self.assertTrue(mock.BUCKET_ID.fullmatch(bucket), (route, bucket))


class LatenessComesFromTheMock(unittest.TestCase):
    def test_lateness_uses_the_mock_create_time_not_the_application_record(self):
        manifest = [{'index': 0, 'workspace': 'w0', 'post': 'w0-p0', 'nonce': 'a', 'due': 100.0, 'expiresAt': 3700.0},
                    {'index': 1, 'workspace': 'w1', 'post': 'w1-p0', 'nonce': 'b', 'due': 100.0, 'expiresAt': 3700.0}]
        log = [{'processed': 400.0, 'route': analysis.CREATE, 'created': True, 'nonce': 'a', 'post': 'w0-p0',
                'message': 'm1', 'status': 200},
               {'processed': 406.0, 'route': 'GET /channels/{id}/messages/{id}', 'readback': 'm1', 'status': 200}]
        posts, _ = analysis.per_post(manifest, log)
        self.assertEqual(posts['w0-p0']['createdAt'] - posts['w0-p0']['due'], 300.0)
        self.assertEqual(posts['w0-p0']['verifiedAtMock'], 406.0)
        self.assertIsNone(posts['w1-p0']['createdAt'], 'no create at the mock: not sent, whatever the database says')

    def test_a_run_directory_with_a_lying_database_still_reports_the_mock_lateness(self):
        folder = Path(tempfile.mkdtemp(prefix='cap-analysis-'))
        try:
            (folder / 'mock').mkdir()
            (folder / 'invocations').mkdir()
            manifest = [{'index': i, 'workspace': 'w%d' % i, 'post': 'w%d-p0' % i, 'nonce': 'n%d' % i,
                         'due': 1000.0, 'expiresAt': 4600.0, 'job': 'j%d' % i} for i in range(3)]
            (folder / 'seed-manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in manifest))
            log = [{'processed': 1000.0 + 60 * (i + 1), 'route': analysis.CREATE, 'created': True, 'nonce': 'n%d' % i,
                    'post': 'w%d-p0' % i, 'message': 'm%d' % i, 'status': 200, 'credential': 'bot'} for i in range(2)]
            (folder / 'mock' / 'mock-requests.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in log))
            (folder / 'mock' / 'mock-summary.json').write_text(json.dumps({'counters': {}, 'peakTrailingSecondAll': 1,
                                                                           'peakTrailingSecondBot': 1}))
            # The application claims every post verified, instantly; the analysis must not believe the timing.
            (folder / 'final-states.json').write_text(json.dumps({'byPost': {r['post']: 'verified' for r in manifest},
                                                                  'deadLetters': 0}))
            (folder / 'config.json').write_text(json.dumps({
                'scenario': 'S1', 'label': 'unit', 'sourceTree': '.', 'sourceSha': '0' * 40, 'dueAt': 1000.0,
                'runStartedAt': 900.0, 'cronPeriodSeconds': 60, 'firstCronAt': 960.0, 'policyCeiling': 25,
                'hotPosts': 0}))
            result = analysis.analyse(str(folder))
            lateness = result['lateness']['allPostsUnsentInfinite']
            self.assertEqual(lateness['median'], 120.0)
            self.assertTrue(math.isinf(lateness['max']), 'the post the mock never saw is infinitely late')
            self.assertEqual(result['outcomes']['sentAtMock'], 2)
            self.assertEqual(result['outcomes']['verifiedInDatabase'], 3, 'the claim is reported, not trusted')
            verdicts = {v['id']: v['verdict'] for v in analysis.judge(result, json.loads(
                (ROOT / 'docs/w02/capacity-standard.json').read_text()))}
            self.assertEqual(verdicts['lateness_max'], 'FAIL')
            self.assertEqual(verdicts['held_or_lost'], 'FAIL')
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_nothing_sent_is_never_a_pass(self):
        result = {'scenario': 'S1', 'outcomes': {'sentAtMock': 0}, 'duplicates': {'byNonce': 0}}
        standard = {'measures': [{'id': 'd', 'name': 'd', 'path': 'duplicates.byNonce', 'op': '==', 'limit': 0}]}
        self.assertEqual(analysis.judge(result, standard)[0]['verdict'], 'NOT MEASURED')


class RequestLedger(unittest.TestCase):
    """The ledger must add up, separate the ideal path from overhead, and see a repeated preflight."""

    @staticmethod
    def preflight(world, index):
        bot = {'authorization': 'Bot ' + mock.BOT_TOKEN}
        user = {'authorization': 'Bearer ' + mock.bearer(index)}
        guild = mock.guild_id(index)
        return [world.handle('GET', '/oauth2/@me', user, None)[3],
                world.handle('GET', '/guilds/%s' % guild, bot, None)[3],
                world.handle('GET', '/guilds/%s/members/%s' % (guild, mock.BOT), bot, None)[3],
                world.handle('GET', '/guilds/%s/members/%s' % (guild, mock.user_id(index)), bot, None)[3],
                world.handle('GET', '/guilds/%s/channels' % guild, bot, None)[3]]

    def test_the_ledger_adds_up_and_counts_a_repeated_preflight(self):
        world = mock.World(workspaces=4)
        log = []
        log += self.preflight(world, 0)                      # post 0: one pass
        log += self.preflight(world, 1) + self.preflight(world, 1)  # post 1: a released step, then a second pass
        log += self.preflight(world, 2)                      # post 2: preflight only, never sent
        log.append(world.handle('GET', '/users/@me', {'authorization': 'Bot ' + mock.BOT_TOKEN}, None)[3])
        log.append(world.handle('GET', '/oauth2/applications/@me', {'authorization': 'Bot ' + mock.BOT_TOKEN}, None)[3])
        for index in (0, 1):
            _, _, body, record = create(world, index, 'w%d-p0' % index, 'n%d' % index)
            log.append(record)
            log.append(world.handle('GET', '/channels/%s/messages/%s' % (mock.channel_id(index), body['id']),
                                    {'authorization': 'Bot ' + mock.BOT_TOKEN}, None)[3])
        manifest = [{'index': n, 'workspace': 'w%d' % n, 'post': 'w%d-p0' % n, 'nonce': 'n%d' % n, 'due': 0.0,
                     'expiresAt': 3600.0} for n in range(3)]
        posts, _ = analysis.per_post(manifest, log)
        ledger = analysis.request_ledger(log, posts)
        self.assertEqual((ledger['sentPosts'], ledger['verifiedPosts']), (2, 2))
        self.assertEqual(ledger['total'], len(log))
        self.assertEqual(ledger['essential'], 14, 'two posts on the ideal path of 7')
        self.assertEqual(ledger['essential'] + sum(ledger['overheadBuckets'].values()), ledger['total'])
        self.assertEqual(ledger['overheadBuckets']['botIdentity'], 2)
        self.assertEqual(ledger['overheadBuckets']['extraPreflight'], 10, 'one repeated pass and one unsent post')
        self.assertEqual(ledger['extraPreflightSplit'], {'repeatedPassesForSentPosts': 5, 'forPostsNeverSent': 5,
                                                         'unattributed': 0, 'attributedTotal': 10})
        self.assertEqual(ledger['preflightPassesPerSentPostOnePostWorkspaces'], {'1': 1, '2': 1})
        self.assertEqual(analysis.grant_custody(ledger)['state'], 'real path')

    def test_a_missing_grant_check_is_named_on_the_receipt(self):
        ledger = {'rows': [], 'sentPosts': 3}
        self.assertEqual(analysis.grant_custody(ledger)['state'], 'below one per sent post')

    def test_trailing_and_calendar_peaks(self):
        times = [10.0 + 0.04 * n for n in range(25)] + [11.0 + 0.01 * n for n in range(5)]
        self.assertEqual(analysis.peak_calendar_second(times), 25)
        # (11.03 - 1, 11.03] holds 24 of the first window and 4 of the second: two windows of at most 25 share it.
        self.assertEqual(analysis.peak_trailing(times, 1.0), 28, 'a span of (t-1, t] can hold both windows')
        self.assertEqual(analysis.peak_trailing([0.0, 1.0], 1.0), 1, 'the span is half open, as the mock counts')


class ScenarioSettings(unittest.TestCase):
    def test_a_pinned_scenario_setting_survives_a_profile_wide_override(self):
        import discord_lane_capacity_run as runner
        fdb = runner.settings_for('Fdb', {'max_db_connections': 20, 'db_latency_ms': 2.0})
        self.assertEqual((fdb['max_db_connections'], fdb['db_latency_ms']), (6, 8.0))
        self.assertEqual(fdb['pinnedOverridesIgnored'], {'max_db_connections': 20, 'db_latency_ms': 2.0})
        s1 = runner.settings_for('S1', {'max_db_connections': 20, 'db_latency_ms': 2.0})
        self.assertEqual((s1['max_db_connections'], s1['db_latency_ms'], s1['pinnedOverridesIgnored']), (20, 2.0, None))


class WireTimingAndPermits(unittest.TestCase):
    """Admission-to-wire spread, witness age, permit deaths, the hot channel and the launch gates, on made-up logs."""

    @staticmethod
    def key(path):
        import hashlib
        return hashlib.sha256(path.encode('utf-8')).hexdigest()[:16]

    def record(self, path, arrived, trailing, **extra):
        return {'arrived': arrived, 'processed': arrived + 0.05, 'method': 'GET', 'route': 'GET /guilds/{id}',
                'credential': 'bot', 'status': 200, 'pathKey': self.key(path), 'trailingAll': trailing, **extra}

    @staticmethod
    def admission(path_key, sent, state='observed', publish=False, sealed=None, reserved=None, expires=None):
        reserved = sent if reserved is None else reserved
        return [reserved, sealed, sent, sent + 0.1, (reserved + 10.0) if expires is None else expires, state, 'GET',
                path_key, publish, None, 'bot']

    def test_the_mock_logs_the_wire_path_the_source_and_the_call_time(self):
        world = mock.World(workspaces=2)
        wire = '/guilds/%s?with_counts=true' % mock.guild_id(1)
        headers = {'authorization': 'Bot ' + mock.BOT_TOKEN, 'x-cap-source': 'lane3', 'x-cap-call-at': '1234.5678'}
        record = world.handle('GET', '/guilds/%s' % mock.guild_id(1), headers, None, wire_path=wire)[3]
        self.assertEqual(record['pathKey'], self.key(wire), 'the digest is of the target as sent, query included')
        self.assertEqual((record['src'], record['callAt']), ('lane3', 1234.5678))
        plain = world.handle('GET', '/guilds/%s' % mock.guild_id(1), {'authorization': 'Bot ' + mock.BOT_TOKEN}, None)[3]
        self.assertEqual(plain['pathKey'], self.key('/guilds/%s' % mock.guild_id(1)))
        self.assertNotIn('src', plain)

    def test_wire_jitter_pairs_requests_and_attributes_the_requests_above_25(self):
        window, admissions = [], []
        # 1. 30 sends 50 ms apart (at most 20 in any trailing second at the coordinator) whose arrivals bunch within
        #    10 ms: the last five arrive as the 26th to 30th in their trailing second: wire jitter.
        for number in range(30):
            path = '/guilds/%d' % (100 + number)
            admissions.append(self.admission(self.key(path), 2000.0 + 0.05 * number))
            window.append(self.record(path, 2001.5 + 0.0003 * number, 1 + number, callAt=2000.01 + 0.05 * number))
        # 2. 40 sends at the same instant: the coordinator itself sent more than 25 in that second.
        for number in range(40):
            path = '/guilds/%d' % (200 + number)
            admissions.append(self.admission(self.key(path), 3000.0))
            window.append(self.record(path, 3000.01 + 0.0001 * number, 1 + number))
        # 3. One request the mock counted as the 26th by its own processing order, with nothing near it: mock only.
        admissions.append(self.admission(self.key('/guilds/300'), 4000.0))
        window.append(self.record('/guilds/300', 4000.02, 26))
        # 4. An arrival no admission explains, counted above 25; and an admission that never reached the mock.
        window.append(self.record('/guilds/400', 5000.0, 30))
        admissions.append(self.admission(self.key('/guilds/500'), 6000.0))
        result = analysis.wire_jitter(sorted(window, key=lambda r: r['arrived']), admissions)
        self.assertEqual((result['paired'], result['admissionsSent'], result['admissionsWithoutArrival'],
                          result['arrivalsWithoutAdmission']), (71, 72, 1, 1))
        self.assertEqual(result['aboveCeilingBy'], {'wire': 5, 'coordinator': 15, 'mock': 1, 'unpaired': 1})
        self.assertEqual(result['aboveCeilingAtMock'], 22)
        self.assertEqual(result['sendPeakTrailingSecond'], 40)
        self.assertAlmostEqual(result['admissionToArrival']['min'], 0.01, places=3)
        self.assertAlmostEqual(result['admissionToArrival']['max'], 1.5, places=3)
        self.assertEqual(result['admissionToCall']['n'], 30)
        self.assertAlmostEqual(result['admissionToCall']['p50'], 0.01, places=4)
        self.assertGreater(result['spreadAboveMedianP999'], 1.4, 'p99.9 is the 1.5 s bunching, the median is 10 ms')
        self.assertEqual(result['creates'], None)

    def test_guard_sizing_counts_the_windows_where_the_26th_arrival_is_under_a_second_after_the_first(self):
        import random
        rng = random.Random(5)
        pairs, at = [], 0.0
        for number in range(400):
            at += 1.1 / 25  # 25 sends per 1.1 s: the guard is 0.1 s
            delay = 0.05 + (0.3 if rng.random() < 0.02 else 0.0) + rng.random() * 0.01
            pairs.append((at, {'arrived': at + delay}, False))
        result = analysis.guard_sizing(pairs, 25)
        ordered = sorted(pairs, key=lambda p: p[0])
        expected = sum(1 for i in range(len(ordered) - 25) if ordered[i + 25][1]['arrived'] - ordered[i][1]['arrived'] < 1.0)
        self.assertEqual(result['windows'], 375)
        self.assertEqual(result['violations'], expected)
        self.assertGreater(expected, 0, 'the 2% of 0.3 s delays do push the 26th arrival inside the second')
        self.assertAlmostEqual(result['minSlack'], 0.1, places=6)
        self.assertGreater(result['delayDifference']['max'], 0.25)
        self.assertLess(result['delayDifference']['p50'], 0.02)
        self.assertIsNone(analysis.guard_sizing([(1.0, {'arrived': 1.1}, False)] * 10, 25))

    def test_wire_jitter_is_none_without_an_admissions_export_or_digests(self):
        self.assertIsNone(analysis.wire_jitter([{'arrived': 1.0}], []))
        self.assertIsNone(analysis.wire_jitter([{'arrived': 1.0}], [self.admission('0' * 16, 1.0)]))

    def test_witness_age_runs_from_the_grant_check_to_the_create(self):
        def rec(route, at, **extra):
            return {'arrived': at, 'route': route, 'status': 200, 'credential': 'bot', 'tenant': 7, **extra}
        window = [rec('GET /oauth2/@me', 100.0), rec('GET /guilds/{id}', 100.2), rec('GET /guilds/{id}/members/{id}', 100.4),
                  rec('GET /guilds/{id}/members/{id}', 100.6), rec('GET /guilds/{id}/channels', 100.8),
                  rec(analysis.CREATE, 105.0, created=True),
                  rec('GET /oauth2/@me', 200.0), rec('GET /guilds/{id}', 200.2), rec('GET /guilds/{id}/channels', 200.8),
                  rec(analysis.CREATE, 230.0, created=True)]
        result = analysis.witness_age(window, {})
        self.assertEqual((result['creates'], result['oldestFromGrantCheck'], result['withoutWitness']), (2, 2, 0))
        self.assertAlmostEqual(result['oldest']['p50'], 5.0)
        self.assertAlmostEqual(result['oldest']['max'], 30.0)
        self.assertAlmostEqual(result['newest']['p50'], 4.2)
        self.assertIsNone(analysis.witness_age([rec(analysis.CREATE, 5.0, created=True)], {}))

    def test_permit_stats_separate_the_deaths_before_and_after_the_seal(self):
        rows = [self.admission('a' * 16, 10.0, 'observed', True, sealed=10.2),
                self.admission('b' * 16, 11.0, 'reserved', True)[:2] + [None] + self.admission('b' * 16, 11.0, 'reserved', True)[3:],
                self.admission('c' * 16, 12.0, 'blocked', True, sealed=12.5),
                self.admission('d' * 16, 13.0, 'blocked', True)[:1] + [None, None] + self.admission('d' * 16, 13.0, 'blocked', True)[3:],
                self.admission('e' * 16, 14.0, 'sent', True, sealed=14.1),
                self.admission('f' * 16, 15.0)]  # a read: not a permit
        stats = analysis.permit_stats(rows)
        self.assertEqual((stats['permits'], stats['used'], stats['diedBeforeSeal'], stats['diedAfterSeal'],
                          stats['stoppedBeforeSeal'], stats['leftOpen']), (5, 1, 1, 1, 1, 1))
        self.assertAlmostEqual(stats['sealLatency']['max'], 0.5)
        self.assertIsNone(analysis.permit_stats([self.admission('f' * 16, 15.0)]))

    def test_the_hot_channel_rate_is_per_second_while_the_workspace_had_due_posts(self):
        posts = {'h%d' % n: {'index': 0, 'createdAt': 1000.0 + 1.25 * n if n < 80 else None, 'due': 1000.0} for n in range(100)}
        posts.update({'s%d' % n: {'index': 1 + n, 'createdAt': 1010.0, 'due': 1000.0} for n in range(5)})
        window = [{'processed': 1200.0}]
        hot = analysis.hot_channel(posts, window, 1000.0)
        self.assertEqual((hot['posts'], hot['sent'], hot['notSent'], hot['allSent']), (100, 80, 20, False))
        self.assertAlmostEqual(hot['createsPerSecondWhileDue'], 80 / 200.0)
        self.assertAlmostEqual(hot['steadyCreatesPerSecond'], 79 / (1.25 * 79))
        self.assertEqual(sum(hot['postsPerMinute'].values()), 80)
        self.assertIsNone(analysis.hot_channel({'a': {'index': 0, 'createdAt': 1.0, 'due': 0.0}}, [], 0.0))

    def test_the_launch_gates_report_and_never_raise(self):
        failing = {'database': {
            'openAdmissions': [{'state': 'sent', 'publish': True, 'kind': 'bot', 'unexpired': None, 'count': 3,
                                'oldestAgeSeconds': 900.0, 'olderThan60Seconds': 3},
                               {'state': 'reserved', 'publish': True, 'kind': 'bot', 'unexpired': False, 'count': 5,
                                'oldestAgeSeconds': 900.0, 'olderThan60Seconds': 5}],
            'budgetProbes': [{'admitted': 22, 'capacity': 25, 'waited': 3.0, 'refused': {'scope': 'application'}},
                             {'admitted': 22, 'capacity': 25, 'waited': 93.0, 'refused': {'scope': 'application'}}],
            'jobRetries': {'ratePermitRetries': 4, 'ratePermitRetriesMaxPerJob': 2}},
            'permits': {'permits': 50, 'diedBeforeSeal': 4, 'diedAfterSeal': 1}}
        gates = {g['id']: g for g in analysis.launch_gates(failing)}
        self.assertEqual({k: g['verdict'] for k, g in gates.items()},
                         {'open_admissions': 'FAIL', 'budget_restored': 'FAIL', 'permits_unused': 'FAIL'})
        self.assertIn('3: bot sent create: 3', gates['open_admissions']['measured'], 'expired reserved permits are not counted')
        whole = {'database': {'openAdmissions': [], 'budgetProbes': [{'admitted': 25, 'capacity': 25, 'waited': 93.0}],
                              'jobRetries': {}}, 'permits': {'permits': 9, 'diedBeforeSeal': 0, 'diedAfterSeal': 0}}
        self.assertEqual({g['verdict'] for g in analysis.launch_gates(whole)}, {'PASS'})
        none = {k: g['verdict'] for k, g in {g['id']: g for g in analysis.launch_gates({'database': {}})}.items()}
        self.assertEqual(none, {'open_admissions': 'NOT MEASURED', 'budget_restored': 'NOT MEASURED', 'permits_unused': 'NOT MEASURED'})
        broken = {'database': {'budgetProbes': [{'error': 'boom', 'at': 1.0}]}}
        self.assertEqual({g['id']: g['verdict'] for g in analysis.launch_gates(broken)}['budget_restored'], 'NOT MEASURED')


class AttemptLog(unittest.TestCase):
    """The coordinator attempt log: a wrapper that observes and changes nothing, and the statistics read from it."""

    def fake_coordinator(self):
        import types

        class RateDelayed(Exception):
            def __init__(self, seconds, scope='application', cause='rate_budget'):
                super().__init__('delayed')
                self.retry_after_seconds, self.rate_scope_kind, self.rate_cause = seconds, scope, cause

        class Permit:
            def __init__(self, ident, identity):
                self.id, self.identity = ident, identity

        class Identity:
            kind = 'bot'

        class SharedPostgresBudget:
            refuse = 0
            book = 0.0  # seconds the next call books when its caller allows booking (book_ahead)

            def __init__(self):
                self._booking = {'bookings': 0, 'bookedWaitSeconds': 0.0, 'gateStops': 0, 'horizonRefusals': 0}

            def booking_stats(self):
                return dict(self._booking)

            def _wait_for_slot(self, permit, booked, read_at, read_sent, deadline_in=None):
                self._booking['bookings'] += 1
                self._booking['bookedWaitSeconds'] += booked
                time.sleep(booked)

            def reserve_read(self, method, path, *, identity, book_ahead=0.0):
                if self.refuse:
                    self.refuse -= 1
                    raise RateDelayed(0.4)
                permit = Permit('permit-read', identity)
                if self.book and book_ahead:
                    self._wait_for_slot(permit, self.book, 0.0, True)
                return permit

            def reserve(self, method, path, *, identity, binding=None, valid_until=None, book_ahead=0.0):
                permit = Permit('permit-create', identity)
                if self.book and book_ahead:
                    self._wait_for_slot(permit, self.book, 0.0, False)
                return permit

            def consume(self, permit, method, path, *, binding=None, intent_id=None, authorize=None):
                if permit.id == 'late':
                    raise RateDelayed(0.05, scope='permit', cause='permit_expired')
                return None

        module = types.ModuleType('postriff_phase2.discord.rate_limits')
        module.RateDelayed, module.SharedPostgresBudget = RateDelayed, SharedPostgresBudget
        package, discord = types.ModuleType('postriff_phase2'), types.ModuleType('postriff_phase2.discord')
        discord.rate_limits, package.discord = module, discord
        saved = {name: sys.modules.get(name) for name in ('postriff_phase2', 'postriff_phase2.discord', 'postriff_phase2.discord.rate_limits')}
        sys.modules.update({'postriff_phase2': package, 'postriff_phase2.discord': discord, 'postriff_phase2.discord.rate_limits': module})
        self.addCleanup(lambda: [sys.modules.pop(n, None) if v is None else sys.modules.__setitem__(n, v) for n, v in saved.items()])
        return SharedPostgresBudget, RateDelayed, Permit, Identity

    def test_the_wrapper_logs_every_attempt_and_changes_nothing(self):
        import discord_lane_cap_invoke as invoke
        budget, delayed, permit, identity = self.fake_coordinator()
        path = Path(tempfile.mkdtemp(prefix='cap-attempts-')) / 'a.jsonl'
        self.addCleanup(shutil.rmtree, path.parent, True)
        handle = invoke.instrument_coordinator(str(path), 'lane3')
        self.addCleanup(handle.close)
        coordinator = budget()
        coordinator.refuse = 2
        with self.assertRaises(delayed) as caught:
            coordinator.reserve_read('GET', '/guilds/1392000000000000007/channels', identity=identity())
        self.assertEqual(caught.exception.retry_after_seconds, 0.4, 'the original exception is raised unchanged')
        self.assertIsNone(invoke.CURRENT['permit'])
        with self.assertRaises(delayed):
            coordinator.reserve_read('GET', '/guilds/1392000000000000007/channels', identity=identity())
        got = coordinator.reserve_read('GET', '/guilds/1392000000000000007/channels', identity=identity())
        self.assertEqual(got.id, 'permit-read', 'the original result is returned unchanged')
        self.assertEqual(invoke.CURRENT['permit'], 'permit-read', 'the next request carries the admitted permit')
        create = coordinator.reserve('POST', '/channels/1393000000000000009/messages', identity=identity())
        self.assertIsNone(invoke.CURRENT['permit'], 'a create permit is stamped when it is consumed, not when it is reserved')
        coordinator.consume(create, 'POST', '/channels/1393000000000000009/messages')
        self.assertEqual(invoke.CURRENT['permit'], 'permit-create')
        with self.assertRaises(delayed):
            coordinator.consume(permit('late', identity()), 'POST', '/channels/1393000000000000009/messages')
        self.assertIsNone(invoke.CURRENT['permit'], 'a refused consume stamps nothing')
        handle.flush()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([(r[2], r[7]) for r in rows], [('read', 'R'), ('read', 'R'), ('read', 'A'), ('reserve', 'A'), ('consume', 'A'),
                                                       ('consume', 'R')])
        self.assertEqual(rows[0][4:11], ['/guilds/{id}/channels', 'bot', 7, 'R', 0.4, 'application', 'rate_budget'])
        self.assertEqual((rows[5][8], rows[5][9], rows[5][10], rows[2][11], rows[2][12]), (0.05, 'permit', 'permit_expired', 'permit-read', 'lane3'))
        self.assertEqual(rows[3][6], 9, 'the channel names its workspace')
        self.assertTrue(all(len(r) == 16 for r in rows), 'thirteen columns and the booking columns')
        self.assertTrue(all(r[13:] == [0.0, 0.0, None] for r in rows), 'nothing booked, nothing slept, no room allowed')

    def test_a_booked_call_is_a_slot_reached_and_the_log_says_how_long_it_booked_and_slept(self):
        """Inside booking() reserve and reserve_read sleep in the call until the booked slot and then return the permit: the log
        keeps the seconds booked (the coordinator's own total), the seconds slept in the wait and the room the caller allowed."""
        import discord_lane_cap_invoke as invoke
        budget, delayed, permit, identity = self.fake_coordinator()
        path = Path(tempfile.mkdtemp(prefix='cap-attempts-')) / 'a.jsonl'
        self.addCleanup(shutil.rmtree, path.parent, True)
        handle = invoke.instrument_coordinator(str(path), 'lane3')
        self.addCleanup(handle.close)
        coordinator = budget()
        coordinator.book = 0.06
        got = coordinator.reserve_read('GET', '/guilds/1392000000000000007', identity=identity(), book_ahead=0.8)
        self.assertEqual(got.id, 'permit-read', 'the original result is returned unchanged')
        self.assertEqual(invoke.CURRENT['permit'], 'permit-read', 'the slot has come: the next request carries this permit')
        coordinator.reserve_read('GET', '/guilds/1392000000000000007', identity=identity())  # a caller outside booking(): no room
        coordinator.reserve('POST', '/channels/1393000000000000009/messages', identity=identity(), book_ahead=0.5)
        self.assertIsNone(invoke.CURRENT['permit'], 'a booked create permit is stamped at the consume, as before')
        handle.flush()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([(r[2], r[7]) for r in rows], [('read', 'A'), ('read', 'A'), ('reserve', 'A')])
        booked_read, plain_read, booked_create = rows
        self.assertAlmostEqual(booked_read[13], 0.06, places=3)
        self.assertGreaterEqual(booked_read[14], 0.059)
        self.assertGreaterEqual(booked_read[1], booked_read[14], 'the call took at least the time it slept')
        self.assertEqual(booked_read[15], 0.8)
        self.assertEqual(plain_read[13:], [0.0, 0.0, None])
        self.assertAlmostEqual(booked_create[13], 0.06, places=3)
        self.assertEqual(booked_create[15], 0.5)
        self.assertEqual(coordinator.booking_stats()['bookings'], 2, 'the wrapper reads the coordinator\'s counts, it changes none')

    def test_a_refused_call_with_room_to_book_is_logged_with_the_room(self):
        import discord_lane_cap_invoke as invoke
        budget, delayed, permit, identity = self.fake_coordinator()
        path = Path(tempfile.mkdtemp(prefix='cap-attempts-')) / 'a.jsonl'
        self.addCleanup(shutil.rmtree, path.parent, True)
        handle = invoke.instrument_coordinator(str(path), 'lane3')
        self.addCleanup(handle.close)
        coordinator = budget()
        coordinator.refuse = 1
        with self.assertRaises(delayed):
            coordinator.reserve_read('GET', '/guilds/1392000000000000007', identity=identity(), book_ahead=0.45)
        handle.flush()
        row = json.loads(path.read_text().splitlines()[0])
        self.assertEqual((row[7], row[13], row[14], row[15]), ('R', 0.0, 0.0, 0.45))

    def test_an_error_logs_the_failure_the_coordinator_hid(self):
        """SharedPostgresBudget._transaction turns any failure into RateCoordinatorUnavailable `from None`: the context is
        still on the exception, and its class and SQLSTATE are what tells a lock timeout from a deadlock or a lost connection."""
        import discord_lane_cap_invoke as invoke
        budget, delayed, permit, identity = self.fake_coordinator()

        class LockNotAvailable(Exception):
            sqlstate = '55P03'

        class Unavailable(Exception):
            pass

        def broken(self, method, path, *, identity, book_ahead=0.0):
            try:
                raise LockNotAvailable('canceling statement due to lock timeout')
            except LockNotAvailable:
                raise Unavailable() from None
        budget.reserve_read = broken
        path = Path(tempfile.mkdtemp(prefix='cap-attempts-')) / 'a.jsonl'
        self.addCleanup(shutil.rmtree, path.parent, True)
        handle = invoke.instrument_coordinator(str(path), 'lane3')
        self.addCleanup(handle.close)
        with self.assertRaises(Unavailable):
            budget().reserve_read('GET', '/guilds/1392000000000000007', identity=identity())
        handle.flush()
        row = json.loads(path.read_text().splitlines()[0])
        self.assertEqual((row[7], row[8], row[9], row[10]), ('E', None, None, 'LockNotAvailable:55P03'))
        stats = analysis.attempt_statistics([row], created_posts=1)
        self.assertEqual(stats['errors'], 1)
        self.assertEqual(stats['errorsByCause'], {'read LockNotAvailable:55P03': 1})
        self.assertIn('LockNotAvailable:55P03', '\n'.join(analysis.attempt_lines(stats)))

    def test_a_tree_without_booking_is_logged_as_before(self):
        import discord_lane_cap_invoke as invoke
        budget, delayed, permit, identity = self.fake_coordinator()
        del budget.booking_stats, budget._wait_for_slot
        path = Path(tempfile.mkdtemp(prefix='cap-attempts-')) / 'a.jsonl'
        self.addCleanup(shutil.rmtree, path.parent, True)
        handle = invoke.instrument_coordinator(str(path), 'minute')
        self.addCleanup(handle.close)
        budget().reserve_read('GET', '/oauth2/@me', identity=identity())
        handle.flush()
        row = json.loads(path.read_text().splitlines()[0])
        self.assertEqual((row[7], row[13:]), ('A', [0.0, 0.0, None]))

    def test_statistics_count_attempts_outcomes_quoted_waits_and_read_steps(self):
        def row(t, outcome, wait=None, kind='bot', route='/guilds/{id}', operation='read', ws=1, source='lane1', scope='application'):
            return [t, 0.05, operation, 'GET', route, kind, ws, outcome, wait, scope if outcome == 'R' else None,
                    'rate_budget' if outcome == 'R' else None, 'p%s' % t if outcome == 'A' else None, source]
        attempts = [row(1.0, 'R', 0.3), row(1.4, 'R', 0.2), row(1.7, 'A'),            # a step admitted at the third attempt
                    row(2.0, 'A'),                                                      # a step admitted at the first
                    row(5.0, 'R', 0.9), row(5.9, 'R', 0.8), row(6.5, 'R', 0.7),      # a step that gave up after three
                    row(1.0, 'R', 0.5, kind='user', route='/oauth2/@me', ws=None, scope='learned_route')]
        stats = analysis.attempt_statistics(attempts, created_posts=2)
        self.assertEqual((stats['attempts'], stats['admitted'], stats['refused']), (8, 2, 6))
        self.assertAlmostEqual(stats['refusedPerCreatedPost'], 3.0)
        server = stats['byKind']['bot / server read / read']
        self.assertEqual((server['attempts'], server['admitted'], server['refused']), (7, 2, 5))
        self.assertAlmostEqual(server['quotedWait']['p50'], 0.7)
        self.assertEqual(stats['byKind']['user / grant check / read']['scopes'], {'learned_route/rate_budget': 1})
        self.assertEqual(stats['readSteps']['server read'], {'3 attempt(s), admitted': 1, '1 attempt(s), admitted': 1, '3 attempt(s), gave up': 1})
        self.assertTrue(any('Quoted wait' in line for line in analysis.attempt_lines(stats)))
        self.assertIsNone(analysis.attempt_statistics([]))

    def test_an_admission_is_paired_to_its_arrival_by_the_permit_id_before_path_and_order(self):
        rows = [[10.0, None, 10.0, 10.2, 20.0, 'observed', 'GET', 'aaaaaaaaaaaaaaaa', False, None, 'bot', 'id-1'],
                [10.5, None, 10.5, 10.7, 20.0, 'observed', 'GET', 'aaaaaaaaaaaaaaaa', False, None, 'bot', 'id-2']]
        # The first admission never reached the wire, but the second did: by path and order they would be swapped.
        window = [{'arrived': 10.6, 'pathKey': 'aaaaaaaaaaaaaaaa', 'permit': 'id-2'}]
        pairs, unpaired, every = analysis.pair_admissions(window, rows, with_rows=True)
        self.assertEqual([(p[0], p[3][11]) for p in pairs], [(10.5, 'id-2')])
        self.assertEqual((unpaired, len(every)), (1, 2), 'the other admission is reported without an arrival')
        legacy, unpaired, _ = analysis.pair_admissions([{'arrived': 10.6, 'pathKey': 'aaaaaaaaaaaaaaaa'}], [r[:11] for r in rows])
        self.assertEqual([p[0] for p in legacy], [10.0], 'without the permit id the old pairing by path and order still works')


class SeedingRetries(unittest.TestCase):
    """Seeding is not what a run measures: a GET the coordinator could not take is tried again, and counted with its cause."""

    def install(self):
        import types
        module = types.ModuleType('postriff_phase2.discord.rate_limits')

        class RateDelayed(Exception):
            def __init__(self, seconds=0.01):
                super().__init__('delayed')
                self.retry_after_seconds, self.rate_scope_kind, self.rate_cause = seconds, 'application', 'rate_budget'

        class RateCoordinatorUnavailable(Exception):
            pass
        module.RateDelayed, module.RateCoordinatorUnavailable = RateDelayed, RateCoordinatorUnavailable
        package, discord = types.ModuleType('postriff_phase2'), types.ModuleType('postriff_phase2.discord')
        discord.rate_limits, package.discord = module, discord
        saved = {name: sys.modules.get(name) for name in ('postriff_phase2', 'postriff_phase2.discord', 'postriff_phase2.discord.rate_limits')}
        sys.modules.update({'postriff_phase2': package, 'postriff_phase2.discord': discord, 'postriff_phase2.discord.rate_limits': module})
        self.addCleanup(lambda: [sys.modules.pop(n, None) if v is None else sys.modules.__setitem__(n, v) for n, v in saved.items()])
        return RateDelayed, RateCoordinatorUnavailable

    def patient(self, behaviour):
        import types
        import discord_lane_cap_seed as seed
        calls = []

        def original(method, path, **kwargs):
            calls.append((method, path))
            return behaviour(len(calls), method)
        fake = types.SimpleNamespace(provider=types.SimpleNamespace(_discord_http=original), read_retries={}, mock=mock)
        patcher = unittest.mock.patch.object(seed.time, 'sleep', lambda seconds: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        seed.Seeder._patient_reads(fake)
        return fake, calls

    def test_a_get_is_tried_again_after_a_failure_the_coordinator_hid_and_the_cause_is_counted(self):
        import unittest.mock  # noqa: F401
        delayed, unavailable = self.install()

        class DeadlockDetected(Exception):
            sqlstate = '40P01'

        def behaviour(n, method):
            if n <= 2:
                try:
                    raise DeadlockDetected('deadlock detected')
                except DeadlockDetected:
                    raise unavailable() from None
            return 'answer'
        fake, calls = self.patient(behaviour)
        self.assertEqual(fake.provider._discord_http('GET', '/oauth2/@me'), 'answer')
        self.assertEqual(len(calls), 3)
        self.assertEqual(fake.read_retries, {'GET /oauth2/@me (coordinator unavailable: DeadlockDetected:40P01)': 2})

    def test_six_failures_in_a_row_stop_the_seeding_and_a_write_is_never_tried_again(self):
        import unittest.mock  # noqa: F401
        delayed, unavailable = self.install()

        def behaviour(n, method):
            raise unavailable()
        fake, calls = self.patient(behaviour)
        with self.assertRaises(unavailable):
            fake.provider._discord_http('GET', '/oauth2/@me')
        self.assertEqual(len(calls), 6, 'the first try and five more')
        fake, calls = self.patient(behaviour)
        with self.assertRaises(unavailable):
            fake.provider._discord_http('POST', '/channels/1393000000000000001/messages')
        self.assertEqual(len(calls), 1)


class SchemaSet(unittest.TestCase):
    def test_a_rollback_script_is_not_part_of_the_migration_set_and_not_a_duplicate_number(self):
        import discord_lane_cap_cluster as cluster
        tree = Path(tempfile.mkdtemp(prefix='cap-tree-'))
        self.addCleanup(shutil.rmtree, tree, True)
        folder = tree / 'migrations/postriff'
        folder.mkdir(parents=True)
        for name in ('001_a.sql', '003_local_only.sql', '142_discord_admission_retention_index.sql',
                     '142_discord_admission_retention_index.rollback.sql', '20261014_pinterest_rate_budgets.sql',
                     '20261017_pinterest_metric_reads.sql', '20261017_pinterest_trial_journal.sql',
                     '20261017_pinterest_metric_reads.rollback.sql'):
            (folder / name).write_text('SELECT 1;\n')
        names = [p.name for p in cluster.migration_paths(tree)]
        self.assertEqual(names, ['001_a.sql', '142_discord_admission_retention_index.sql', '20261014_pinterest_rate_budgets.sql',
                                 '20261017_pinterest_metric_reads.sql', '20261017_pinterest_trial_journal.sql'])
        (folder / '142_other.sql').write_text('SELECT 1;\n')
        with self.assertRaises(RuntimeError):
            cluster.migration_paths(tree)


class BookingReceipts(unittest.TestCase):
    """What the receipt takes from booking: attempt rows with booked and slept seconds, the lane counters, the health payload."""

    @staticmethod
    def attempt(t, outcome, booked=None, slept=0.0, room=None, took=0.05, operation='read', route='/guilds/{id}'):
        row = [t, took, operation, 'GET' if operation == 'read' else 'POST', route, 'bot', 1, outcome,
               0.3 if outcome == 'R' else None, 'application' if outcome == 'R' else None, 'rate_budget' if outcome == 'R' else None,
               'p%s' % t if outcome == 'A' else None, 'lane1']
        return row if booked is None else row + [booked, slept, room]

    def test_booked_calls_are_counted_apart_from_calls_that_did_not_book(self):
        a = self.attempt
        attempts = [a(1, 'A', 0.0, 0.0, 0.9), a(2, 'A', 0.3, 0.29, 0.9, took=0.36), a(3, 'A', 0.6, 0.59, 0.9, took=0.66),
                    a(4, 'R', 0.0, 0.0, 0.9), a(5, 'R', 0.0, 0.0, None), a(6, 'A'),            # a 13-column row of an older log
                    a(7, 'A', 0.4, 0.4, 0.7, took=0.5, operation='reserve', route='/channels/{id}/messages')]
        stats = analysis.attempt_statistics(attempts, created_posts=2)
        self.assertEqual((stats['attempts'], stats['admitted'], stats['refused'], stats['booked']), (7, 5, 2, 3))
        self.assertEqual(stats['bookedByOperation'], {'read': 2, 'reserve': 1})
        self.assertAlmostEqual(stats['bookedPlannedSeconds'], 1.3)
        self.assertAlmostEqual(stats['bookedSleptSeconds'], 1.28)
        self.assertEqual(stats['refusedWithRoomToBook'], 1, 'one refusal had room to book, the other was asked for no booking')
        self.assertEqual(stats['withBookingColumns'], 6)
        server = stats['byKind']['bot / server read / read']
        self.assertEqual((server['attempts'], server['admitted'], server['booked']), (6, 4, 2))
        self.assertAlmostEqual(server['callSecondsAdmittedBooked']['p50'], 0.36)
        self.assertAlmostEqual(server['callSecondsAdmittedUnbooked']['p50'], 0.05)
        text = '\n'.join(analysis.attempt_lines(stats))
        self.assertIn('slot reached', text)
        self.assertIn('Booked (planned wait', text)
        old_log = analysis.attempt_statistics([a(1, 'A'), a(2, 'R')])
        self.assertEqual((old_log['withBookingColumns'], old_log['booked']), (0, 0))
        self.assertIn('no booking columns', '\n'.join(analysis.attempt_lines(old_log)))

    @staticmethod
    def reading(t, admissions, ahead, horizon, booked, remaining, status=200):
        return {'at': t, 'status': status, 'wallSeconds': 2.5, 'elapsedMs': 40.0, 'errors': [], 'coordinator': {
            'status': 'observed',
            'guards': {'policy': {'present': True, 'remaining': remaining, 'limit': 25, 'remainingRatio': remaining / 25.0,
                                  'resetSeconds': 0.4, 'hold': False, 'blocked': False, 'circuit': False}},
            'traffic': {'admissions60s': admissions, 'responses429': 0},
            'booking': {'status': 'observed', 'bookAheadSeconds': 1.0, 'aheadNow': ahead, 'horizonSeconds': horizon,
                        'bookedReads60s': booked, 'bookedReadWaitSeconds60s': booked * 0.3,
                        'meanBookedReadWaitSeconds60s': 0.3, 'maxBookedReadWaitSeconds60s': 0.9}}}

    def test_health_readings_are_summarised_over_the_busy_minutes(self):
        r = self.reading
        samples = [r(30, 40, 0, 0.0, 0, 25), r(90, 1300, 18, 0.8, 900, 6), r(150, 1320, 20, 0.95, 950, 0),
                   r(210, 1290, 17, 0.7, 880, 7), r(1000, 50, 0, 0.0, 0, 25)]
        summary = analysis.health_summary(samples)
        self.assertEqual((summary['readings'], summary['usable'], summary['busyReadings'], summary['peakAdmissions60s']), (5, 5, 3, 1320))
        self.assertEqual(summary['bookAheadSeconds'], 1.0)
        self.assertEqual(summary['horizonFullReadings'], 1, 'one busy reading had the horizon within 0.1 s of the book-ahead')
        self.assertEqual(summary['policyRemainingZeroReadings'], 1)
        self.assertEqual(summary['policyRemaining']['p50'], 6)
        self.assertEqual(summary['aheadNow']['max'], 20)
        self.assertEqual(summary['bookedReads60s']['p50'], 900)
        self.assertEqual(summary['policyLimit'], 25)

    def test_a_tree_without_the_health_route_says_so_instead_of_inventing_a_reading(self):
        summary = analysis.health_summary([{'at': 1.0, 'status': 404, 'answer': {'message': 'This hosted route is unavailable.'}},
                                           {'at': 2.0, 'status': None, 'exception': 'TimeoutExpired: 90'}])
        self.assertEqual((summary['readings'], summary['usable'], summary['statuses']), (2, 0, {'404': 1, 'exception': 1}))
        self.assertNotIn('aheadNow', summary)
        self.assertIsNone(analysis.health_summary([]))
        lines = '\n'.join(analysis.booking_lines({'booking': analysis.booking_summary({'bookedWaits': 0, 'bookedSeconds': 0.0}, 10, [], None,
                                                                                    summary)}))
        self.assertIn('none usable', lines)
        self.assertIn('404', lines)

    def test_the_receipt_reads_booking_from_the_counters_the_admissions_the_attempts_and_the_health_payload(self):
        counters = {'bookedWaits': 120, 'bookedSeconds': 36.0, 'rateDelayed': 0, 'permitWaits': 2, 'rateWaits': 3, 'steps': 90,
                    'positionsKept': 1, 'claimed': 80, 'posted': 80, 'verified': 80}
        # [reserved, sealed, sent, outcome, expires, state, method, path, publish, publication, kind, id]
        admissions = [[10.0, None, 10.0, 10.2, 15.0, 'observed', 'GET', 'a' * 16, False, None, 'bot', 'x1'],
                      [10.1, None, 10.4, 10.6, 15.0, 'observed', 'GET', 'a' * 16, False, None, 'bot', 'x2'],     # booked 0.3 s
                      [10.2, None, 10.8, 11.0, 15.0, 'observed', 'GET', 'a' * 16, False, None, 'bot', 'x3'],     # booked 0.6 s
                      [10.3, 10.9, 11.0, 11.2, 15.3, 'observed', 'POST', 'b' * 16, True, 'pub', 'bot', 'x4']]    # a create: not counted as a read
        attempts = analysis.attempt_statistics([self.attempt(1, 'A', 0.3, 0.3, 0.9), self.attempt(2, 'A', 0.6, 0.6, 0.9)], created_posts=80)
        health = analysis.health_summary([self.reading(30, 1300, 18, 0.8, 900, 6), self.reading(90, 1320, 20, 0.95, 950, 3)])
        summary = analysis.booking_summary(counters, 80, admissions, attempts, health)
        self.assertEqual((summary['laneBookedWaits'], summary['laneBookedSeconds']), (120, 36.0))
        self.assertAlmostEqual(summary['laneBookedWaitsPerCreatedPost'], 1.5)
        self.assertAlmostEqual(summary['laneMeanBookedSeconds'], 0.3)
        self.assertEqual((summary['admittedReads'], summary['bookedReads']), (3, 2))
        self.assertAlmostEqual(summary['bookedReadSeconds'], 0.9)
        lines = '\n'.join(analysis.booking_lines({'booking': summary}))
        for expected in ('bookedWaits 120', 'bookedSeconds 36.0', '2 of 3 admitted reads', 'coordinator.booking', 'horizonSeconds',
                         'bookedReads60s', 'meanBookedReadWaitSeconds60s', 'maxBookedReadWaitSeconds60s',
                         'the number of slots bookings may still fill', 'coordinator.guards.policy'):
            self.assertIn(expected, lines)
        self.assertIsNone(analysis.booking_summary({}, 0, [], None, None), 'a tree with no booking shows none')

    def test_the_peak_of_a_booked_read_is_counted_by_wire_time_not_by_reservation(self):
        # 30 reads reserved inside one second but booked across three: by reservation 30 in a second, by wire time 10.
        reserved = [100.0 + i * 0.03 for i in range(30)]
        wire = [100.0 + i * 0.1 for i in range(30)]
        self.assertEqual(analysis.peak_trailing(reserved, 1.0), 30)
        self.assertEqual(analysis.peak_trailing(wire, 1.0), 10)


class CrashInjector(unittest.TestCase):
    """Fcrash's random kills land inside a loop, and a kill with nothing to hit is recorded as missed."""

    class Fake:
        def __init__(self, pid):
            self.pid, self.killed = pid, False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    def harness(self, reference, processes):
        import threading
        import discord_lane_capacity_run as runner
        harness = runner.Harness.__new__(runner.Harness)
        harness.s = {'kills': [0], 'kill_at_create': 0}
        harness.stop = threading.Event()
        harness.reference = reference
        harness.kills = []
        harness.inv_lock = threading.Lock()
        harness.events_lock = threading.Lock()
        harness.events = open(os.devnull, 'w')
        harness.log_handle = open(os.devnull, 'w')
        self.addCleanup(harness.events.close)
        self.addCleanup(harness.log_handle.close)
        harness.dir = Path(tempfile.mkdtemp(prefix='cap-injector-'))
        self.addCleanup(shutil.rmtree, harness.dir, True)
        (harness.dir / 'mock').mkdir()
        harness.invocations = {'%d-lane' % n: {'process': p, 'path': '/api/cron/discord-worker/%d' % n, 'scheduled': reference}
                               for n, p in enumerate(processes)}
        return harness

    def run_injector(self, harness, seconds):
        import threading
        import time
        thread = threading.Thread(target=harness.crash_injector, daemon=True)
        thread.start()
        deadline = time.time() + seconds
        while time.time() < deadline and not harness.kills:
            time.sleep(0.05)
        harness.stop.set()
        thread.join(5)

    def test_a_random_kill_is_delivered_20_seconds_into_its_minute_to_a_running_loop(self):
        import time
        processes = [self.Fake(100 + n) for n in range(3)]
        harness = self.harness(time.time() - 20.5, processes)
        self.run_injector(harness, 5)
        self.assertEqual([k['kind'] for k in harness.kills], ['random'])
        self.assertEqual(sum(p.killed for p in processes), 1)
        early = self.harness(time.time() - 5, [self.Fake(1)])  # 15 s before the kill's moment: nothing yet
        self.run_injector(early, 1)
        self.assertEqual(early.kills, [])

    def test_a_kill_with_no_running_loop_is_recorded_as_missed_after_30_seconds(self):
        import time
        harness = self.harness(time.time() - 51, [])
        self.run_injector(harness, 5)
        self.assertEqual([k['kind'] for k in harness.kills], ['random_missed'])

    def test_the_receipt_row_names_planned_delivered_and_missed(self):
        config = {'settings': {'kills': [3, 5, 8], 'kill_at_create': 2}, 'expect': ['fcrash'], 'ratePolicy': {}}
        kills = [{'kind': 'random'}, {'kind': 'random'}, {'kind': 'random_missed'}, {'kind': 'at_create'}, {'kind': 'at_create_missed'}]
        result = {'_posts': {}, '_window': [], '_states': {}, 'dueAt': 0.0, 'kills': kills, 'endReason': 'every post terminal',
                  'outcomes': {'verifiedInDatabase': 0}, 'duplicates': {}, 'workers': {}}
        row = next(r for r in analysis.expectations(result, config, {}) if r['id'] == 'fcrash_kills')
        self.assertEqual(row['verdict'], 'FAIL')
        self.assertIn('planned 5 (3 random, 2 during a create); delivered 3 (2 random, 1 during a create); '
                      'missed 2 (1 random, 1 during a create)', row['measured'])


class ProfilesAndSettings(unittest.TestCase):
    def test_the_s2_sizes_keep_five_thousand_posts_and_one_hot_workspace(self):
        import discord_lane_capacity_run as runner
        for name, hot in (('S2-100', 100), ('S2-300', 300), ('S2-1000', 1000)):
            settings = runner.settings_for(name, {})
            harness = runner.Harness.__new__(runner.Harness)
            harness.s = settings
            layout = harness.plan()
            sizes = sorted((len(d) for _, d in layout), reverse=True)
            self.assertEqual((sum(sizes), sizes[0], len(layout), settings['judge_as']), (5000, hot, 2000, 'S2'), name)
            self.assertLessEqual(sizes[1], 5, 'every other workspace is small (the fairness measure counts at most five)')
        self.assertEqual(runner.PROFILES['s2sizes'], ['S2-100', 'S2-300', 'S2-1000'])
        self.assertEqual(runner.settings_for('S2', {})['hot_posts'], 3000, 'the 3,000 case stays as the stress case')

    def test_the_devset_is_the_limiter_measurement_and_release_is_unchanged(self):
        import discord_lane_capacity_run as runner
        self.assertEqual(runner.PROFILES['devset'], ['S1', 'S0-100', 'Fdb', 'Fcrash', 'F429'])
        self.assertEqual(len(runner.PROFILES['release']), 16)
        self.assertTrue(all(name in runner.SCENARIOS for items in runner.PROFILES.values() for name in items))

    def test_the_delayed_budget_probe_runs_in_the_measured_scenarios_only(self):
        import discord_lane_capacity_run as runner
        delayed = {n: runner.settings_for(n, {})['budget_probe_delay_seconds'] for n in runner.SCENARIOS}
        self.assertEqual({n for n, v in delayed.items() if not v}, {'smoke', 'Nmisroute', 'Ndup'})
        self.assertEqual(delayed['S1'], 90)

    def test_the_workflows_command_line_leaves_fdbs_pool_and_round_trip_alone(self):
        import re as _re
        import discord_lane_capacity_run as runner
        text = (ROOT / 'docs/w02/ci/discord-lane-capacity.yml.txt').read_text()
        block = text[text.index('Run the scenario'):]
        block = block[:block.index('- name:', 10)]
        line = ' '.join(_re.sub(r'\\\s*\n', ' ', block).split())
        argv = _re.search(r'discord_lane_capacity_run\.py (run .*?)(?: uptime|$)', line).group(1)
        argv = argv.replace('"$SCENARIO"', 'Fdb').replace('"$GITHUB_WORKSPACE/tree"', '/x').replace('"$RUNNER_TEMP/capacity"', '/y')
        argv = argv.replace('"gha-pool${POOL}"', 'gha-pool20').replace('"$POOL"', '20').replace('"$LATENCY"', '2')
        args = runner.build_parser().parse_args(argv.split())
        settings = runner.settings_for(args.scenario, runner.overrides_from(args))
        self.assertEqual((args.max_db_connections, args.db_latency_ms), (20, 2.0), 'the workflow does pass them: ' + argv)
        self.assertEqual((settings['max_db_connections'], settings['db_latency_ms'], settings['db_statement_timeout_ms']),
                         (6, 8.0, 1500))
        s1 = runner.settings_for('S1', runner.overrides_from(runner.build_parser().parse_args(argv.replace('Fdb', 'S1').split())))
        self.assertEqual((s1['max_db_connections'], s1['db_latency_ms']), (20, 2.0))


@unittest.skipIf(FENCED, 'the synthetic transport fence refuses any database but the guarded runner\'s')
@unittest.skipUnless(LIVE, 'needs PostgreSQL server binaries (POSTRIFF_PG_BIN) and psycopg')
class LiveSmoke(unittest.TestCase):
    def run_harness(self, scenario, *extra):
        out = tempfile.mkdtemp(prefix='cap-smoke-')
        self.addCleanup(shutil.rmtree, out, True)
        done = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'discord_lane_capacity_run.py'), 'run',
                               '--scenario', scenario, '--source-tree', str(ROOT), '--out', out, '--label', 'unittest',
                               *extra], capture_output=True, text=True, timeout=600,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        run_dir = next(Path(out).iterdir())
        return json.loads((run_dir / 'result.json').read_text())

    def test_smoke_end_to_end(self):
        result = self.run_harness('smoke')
        expectations = {e['id']: e['verdict'] for e in result['expectations']}
        self.assertEqual(expectations, {'no_duplicates': 'PASS', 'no_late_sends': 'PASS', 'all_verified': 'PASS',
                                        'isolation': 'PASS', 'clean_workers': 'PASS'}, result['expectations'])
        self.assertEqual(result['outcomes']['verifiedAtMock'], result['posts'])
        self.assertGreater(result['requests']['perVerifiedPost'], 2)
        self.assertEqual(result['workers']['blockedEgress'], 0)

    def test_four_seeding_processes_released_together_all_finish(self):
        # The GitHub-hosted failure: four seeding processes asked for the bot's own routes at the same moment, and the
        # provider's one-second admission wait expired in one of them. The slices are now released together on
        # purpose, and a delayed read is retried; every slice must finish and leave no admission open.
        out = tempfile.mkdtemp(prefix='cap-seed-')
        self.addCleanup(shutil.rmtree, out, True)
        done = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'discord_lane_capacity_run.py'), 'seed-check',
                               '--scenario', 'smoke', '--source-tree', str(ROOT), '--out', out, '--label', 'unittest',
                               '--workspaces', '16', '--posts', '32', '--seed-processes', '4', '--lead-seconds', '30'],
                              capture_output=True, text=True, timeout=600,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        summary = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual((summary['posts'], summary['processes'], len(summary['slices'])), (32, 4, 4), summary)
        run_dir = next(Path(out).iterdir())
        config = json.loads((run_dir / 'config.json').read_text())
        self.assertFalse({'sent', 'uncertain'} & set(config['seedAdmissionsByState']), config['seedAdmissionsByState'])

    @unittest.skipUnless(os.environ.get('CAP_HARNESS_FULL') == '1', 'set CAP_HARNESS_FULL=1 for the live ceiling control')
    def test_live_ceiling_control_trips_the_counter(self):
        result = self.run_harness('smoke', '--policy-capacity', '200', '--mock-latency', 'fixed:2', '--posts', '60',
                                  '--shards', '8')
        self.assertGreater(result['ceiling']['aboveTwentyFiveAll'], 0, 'a 200/s policy must exceed 25 in some second')
        self.assertTrue(result['informationOnly'])


if __name__ == '__main__':
    unittest.main()
