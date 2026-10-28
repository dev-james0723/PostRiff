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
import unittest
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
