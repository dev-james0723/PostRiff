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
