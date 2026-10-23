"""W-02 parallel Discord lane, offline: flag, budget, route, the existing tick, and the loop itself.

No database, network or credential. The real-PostgreSQL proofs (exactly once with many loops, the rate cap, fairness,
expiry, the operator hold, a global 429, connections) are in test_discord_parallel_lane_postgres.py.
"""
import copy
import hashlib
import importlib.util
import io
import itertools
import json
import logging
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import hosted_worker, security_holds
from postriff_phase2.discord import lane
from postriff_phase2.discord.rate_limits import RateDelayed, SharedPostgresBudget
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import (APP, NOW, WORKSPACE, SyntheticGrants, SyntheticWire, approve, fixture,
                                                review)
from test_discord_worker_lifecycle import MemoryDatabase

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('discord_rate_policy', ROOT / 'scripts/discord_rate_policy.py')
POLICY_TOOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(POLICY_TOOL)
ON = {lane.ENV_ENABLED: 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}
BASE_SOURCE = ROOT / 'tests/phase2/fixtures/hosted_worker_2a5a523d.py.txt'
BASE_SHA256 = '8fdfd6e3dc461a88a9d4784a587491e22ada54b27585480a41609fb8c64f76de'  # pragma: allowlist secret -- content hash of the pinned source


class FlagAndBudget(unittest.TestCase):
    def test_only_the_exact_string_true_with_the_worker_protocol_on_enables_the_lane(self):
        self.assertTrue(lane.enabled(ON))
        for value in ('TRUE', 'True', '1', 'yes', ' true', 'true ', '', None):
            with self.subTest(value=value):
                self.assertFalse(lane.enabled({**ON, lane.ENV_ENABLED: value} if value is not None else
                                              {'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}))
        self.assertFalse(lane.enabled({lane.ENV_ENABLED: 'true'}), 'needs the Discord worker lease protocol too')
        self.assertFalse(lane.enabled({}))

    def test_the_default_budget_ends_well_inside_one_cron_minute(self):
        self.assertEqual(lane.limits({}), (50.0, 600))

    def test_no_budget_can_outlast_the_function_limit_with_one_step_in_flight(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        duration = config['services']['postriff_api']['functions']['api/index.py']['maxDuration']
        self.assertEqual(lane.FUNCTION_SECONDS, duration)
        self.assertEqual(lane.MAX_SECONDS + lane.STEP_RESERVE_SECONDS + lane.COLD_START_SECONDS + lane.MARGIN_SECONDS,
                         duration)
        self.assertEqual(lane.MAX_SECONDS, 90)
        self.assertGreaterEqual(lane.MARGIN_SECONDS, 30, 'room for database time nothing else bounds')
        # Seven Discord requests at the 20-second transport timeout, and room for their transactions.
        self.assertGreaterEqual(lane.STEP_RESERVE_SECONDS, 7 * 20 + 20)
        self.assertEqual(lane.limits({lane.ENV_SECONDS: str(lane.MAX_SECONDS)})[0], lane.MAX_SECONDS)
        for seconds in (lane.MAX_SECONDS + 1, 290, '1e9'):
            with self.subTest(seconds=seconds):
                self.assertEqual(lane.limits({lane.ENV_SECONDS: str(seconds)})[0], lane.MAX_SECONDS)
        for seconds, steps in ((4, 10), ('nan', 10), ('inf', 10), ('-inf', 10), ('x', 10), ('', 10),
                               (50, 0), (50, lane.MAX_STEPS + 1), (50, 'x')):
            with self.subTest(seconds=seconds, steps=steps), self.assertRaises(AlphaError) as refused:
                lane.limits({lane.ENV_SECONDS: str(seconds), lane.ENV_STEPS: str(steps)})
            self.assertEqual(refused.exception.code, 'discord_lane_configuration')

    def test_a_budget_above_ninety_seconds_is_clamped_to_ninety(self):
        self.assertEqual(lane.limits({lane.ENV_SECONDS: '120'}), (90.0, 600))
        self.assertEqual(lane.limits({lane.ENV_SECONDS: '90'}), (90.0, 600))
        self.assertEqual(lane.limits({lane.ENV_SECONDS: '89.5'}), (89.5, 600))

    def test_shards_are_small_decimal_numbers_only(self):
        self.assertEqual([lane.shard(text) for text in ('0', '7', '11', '31')], [0, 7, 11, 31])
        for text in ('32', '99', '-1', '01', '1.0', ' 1', '1/2', '', 'one', None, '١'):
            with self.subTest(text=text):
                self.assertIsNone(lane.shard(text))

    def test_vercel_starts_one_loop_per_shard_every_minute_and_git_deploys_stay_off(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        self.assertEqual(config['git'], {'deploymentEnabled': False})
        self.assertEqual(config['crons'][0], {'path': '/api/cron/worker', 'schedule': '* * * * *'})
        self.assertEqual(config['crons'][1:], [{'path': lane.ROUTE + str(n), 'schedule': '* * * * *'}
                                               for n in range(lane.SHARDS)])
        self.assertLessEqual(lane.SHARDS, lane.MAX_SHARDS)


class HostedPreflight(unittest.TestCase):
    """scripts/check_postriff_hosted_preflight.py refuses a lane flag the lane cannot act on."""
    def setUp(self):
        spec = importlib.util.spec_from_file_location('w02_hosted_preflight', ROOT / 'scripts/check_postriff_hosted_preflight.py')
        self.preflight = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.preflight)

    def lane_check(self, values):
        return {item['name']: item for item in self.preflight.validate_environment(values)}['discord-parallel-lane']

    def test_the_lane_flag_without_rate_limits_fails_the_preflight(self):
        on = {lane.ENV_ENABLED: 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}
        for rate in (None, 'false', 'TRUE', '1'):
            with self.subTest(rate=rate):
                check = self.lane_check({**on, **({'POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED': rate} if rate else {})})
                self.assertEqual(check['status'], 'fail')
                self.assertIn('POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED', check['detail'])
        ready = {**on, 'POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED': 'true'}
        self.assertEqual(self.lane_check(ready)['status'], 'pass')
        self.assertEqual(self.lane_check({**ready, 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'false'})['status'], 'fail')
        for off in ({}, {lane.ENV_ENABLED: 'TRUE'}, {lane.ENV_ENABLED: 'false', 'POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED': 'false'}):
            with self.subTest(off=off):
                self.assertEqual(self.lane_check(off)['status'], 'pass')

    def test_the_failed_lane_check_fails_the_command(self):
        values = {lane.ENV_ENABLED: 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}
        with patch.dict('os.environ', values, clear=True), patch('sys.stdout', io.StringIO()) as printed:
            self.assertEqual(self.preflight.main([]), 1)
        report = json.loads(printed.getvalue())
        self.assertEqual(report['status'], 'fail')
        self.assertIn({'name': 'discord-parallel-lane', 'status': 'fail'},
                      [{key: item[key] for key in ('name', 'status')} for item in report['checks']])


def invoke(app, suffix, authorization='', method='GET'):
    result = {}
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': lane.ROUTE + suffix, 'QUERY_STRING': '',
               'HTTP_AUTHORIZATION': authorization, 'wsgi.input': io.BytesIO(), 'CONTENT_LENGTH': '0'}

    def response(status, headers):
        result['status'] = int(status.split()[0])
    result['body'] = json.loads(b''.join(app(environ, response)))
    return result


class CronRoute(unittest.TestCase):
    SECRET = 'c' * 24

    def app(self):
        app = HostedApplication(cron_secret=self.SECRET)
        app._runtime = Mock(side_effect=AssertionError('runtime initialized'))
        return app

    def test_missing_or_user_tokens_never_start_the_runtime(self):
        for authorization in ('', 'Bearer dev:someone', 'Bearer prt_not-cron-authority', 'Bearer ' + 'c' * 23):
            with self.subTest(authorization=authorization), patch.dict('os.environ', ON):
                app = self.app()
                self.assertEqual(invoke(app, '0', authorization)['status'], 401)
                app._runtime.assert_not_called()

    def test_with_the_flag_off_an_authorized_shard_answers_without_the_runtime(self):
        with patch.dict('os.environ', {lane.ENV_ENABLED: 'TRUE', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}):
            app = self.app()
            result = invoke(app, '3', 'Bearer ' + self.SECRET)
        self.assertEqual(result, {'status': 200, 'body': {'version': 1, 'lane': 'discord', 'enabled': False,
                                                         'shard': 3, 'processed': 0, 'status': {
                                                             'version': 1, 'enabled': False, 'ready': False,
                                                             'blocker': 'disabled', 'maxSeconds': 50.0, 'maxSteps': 600,
                                                             'shards': 12, 'policyDaysLeft': None,
                                                             'quarantined': lane.quarantined()}}})
        app._runtime.assert_not_called()

    def test_unknown_shards_and_methods_are_not_routes(self):
        for suffix, method in (('32', 'GET'), ('x', 'GET'), ('1/2', 'GET'), ('', 'GET'), ('1', 'POST')):
            with self.subTest(suffix=suffix, method=method), patch.dict('os.environ', ON):
                app = self.app()
                self.assertEqual(invoke(app, suffix, 'Bearer ' + self.SECRET, method)['status'], 404)
                app._runtime.assert_not_called()

    def test_with_the_flag_on_the_shard_runs_one_loop_on_the_shared_worker(self):
        worker = object()
        app = HostedApplication(service=object(), worker=worker, cron_secret=self.SECRET)
        with patch.dict('os.environ', ON), patch.object(lane, 'run', return_value={'lane': 'discord'}) as run:
            result = invoke(app, '11', 'Bearer ' + self.SECRET)
        self.assertEqual(result, {'status': 200, 'body': {'lane': 'discord'}})
        self.assertEqual(run.call_args.args, (worker, 11))
        self.assertIsInstance(run.call_args.kwargs['started'], float)

    def test_the_request_log_files_shards_under_cron(self):
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logger = logging.getLogger('postriff.request')
        logger.addHandler(handler)
        try:
            invoke(self.app(), '0')
        finally:
            logger.removeHandler(handler)
        logged = [json.loads(line) for line in records if '"request.completed"' in line]
        self.assertEqual([entry['route'] for entry in logged], ['cron'])


def coordinator(provider, connection_factory=lambda: None, *, rate_limits=True, policy='current', degraded=False,
                at=NOW):
    """Leave `provider` as runtime_from_environment and OAuthService would: rate limits on or off, a reviewed policy
    current at `at` (or expired, not yet valid, or absent), this process's coordinator healthy or degraded."""
    provider.rate_v1_enabled = rate_limits
    provider.rate_limiter = None if policy is None else SharedPostgresBudget(connection_factory, APP, policy=json.dumps(
        POLICY_TOOL.build({'current': at, 'expired': at - 3 * 86400, 'future': at + 86400}[policy], days=1)))
    provider.rate_coordinator_degraded = degraded
    return provider


def discord_social(connection_factory=None, **setup):
    provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                               transport=SyntheticWire(), production_reviewed=True)
    provider.authorization_v2_enabled = True
    factory = connection_factory or Mock(side_effect=AssertionError('the readiness test opened a connection'))
    return HostedSocial(SyntheticGrants(), {'discord': coordinator(provider, factory, **setup)})


# Every configuration in which no shard loop can run, in any process, with the reason it stops with.
NOT_READY = (
    ('rate limits off', {'rate_limits': False, 'policy': None}, 'coordinator_unavailable'),
    ('rate limits off with a policy', {'rate_limits': False}, 'coordinator_unavailable'),
    ('no shared coordinator', {'policy': None}, 'coordinator_unavailable'),
    ('policy expired', {'policy': 'expired'}, 'coordinator_unavailable'),
    ('policy not valid yet', {'policy': 'future'}, 'coordinator_unavailable'),
)
# A coordinator that lost an observation in this process only: this process's loops stop, other processes' do not.
DEGRADED = ('coordinator degraded in this process', {'degraded': True}, 'coordinator_degraded')


def recording_worker(step, *, discord=True, social=None):
    instance = object.__new__(PostgresWorker)
    instance._stopping = False
    instance._ensure_lifecycle = lambda: None
    instance.social = SimpleNamespace() if social is None else social
    instance.clock = lambda: NOW
    instance.discord_workers = discord
    instance.discord_report = lambda: {}
    instance.step = step
    return instance


class ExistingTick(unittest.TestCase):
    def test_with_the_lane_on_and_able_to_run_the_minute_tick_never_claims_discord(self):
        seen = []
        with patch.dict('os.environ', ON):
            result = recording_worker(lambda **kw: seen.append(kw) or True, social=discord_social()).tick()
        self.assertEqual(result['processed'], 10)
        self.assertTrue(result['discordParallelLane'])
        self.assertEqual(seen, [{'exclude_youtube': False, 'exclude_discord': True}] * 10)

    def test_with_the_lane_on_and_the_youtube_fleet_on_both_stay_excluded(self):
        seen = []
        with patch.dict('os.environ', {**ON, 'POSTRIFF_YOUTUBE_FLEET_ENABLED': '1', 'POSTRIFF_YOUTUBE_CREATOR_ENABLED': '1'}):
            recording_worker(lambda **kw: seen.append(kw) or False, social=discord_social()).tick()
        self.assertEqual(seen, [{'exclude_youtube': True, 'exclude_discord': True}])

    def test_with_the_lane_off_the_tick_still_alternates_its_two_lanes(self):
        seen = []
        with patch.dict('os.environ', {lane.ENV_ENABLED: 'false', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}):
            result = recording_worker(lambda **kw: seen.append(kw) or True).tick()
        self.assertNotIn('discordParallelLane', result)
        self.assertEqual(seen.count({'discord_only': True}), 5)

    def test_with_the_lane_on_but_unable_to_run_here_the_tick_keeps_discord(self):
        cases = [(name, ON, setup) for name, setup, _ in NOT_READY]
        cases.append(('lane budget misconfigured', {**ON, lane.ENV_SECONDS: '4'}, {}))
        for name, environment, setup in cases:
            seen = []
            with self.subTest(name), patch.dict('os.environ', environment):
                result = recording_worker(lambda **kw: seen.append(kw) or True, social=discord_social(**setup)).tick()
                self.assertNotIn('discordParallelLane', result)
                self.assertEqual(result['processed'], 10)
                self.assertEqual(seen.count({'discord_only': True}), 5, 'the minute worker still runs Discord steps')

    def test_with_only_this_process_degraded_the_tick_still_leaves_discord_to_the_lane(self):
        # This process cannot send either; lane loops in healthy processes can.
        seen = []
        with patch.dict('os.environ', ON):
            result = recording_worker(lambda **kw: seen.append(kw) or True, social=discord_social(**DEGRADED[1])).tick()
        self.assertTrue(result['discordParallelLane'])
        self.assertEqual(seen, [{'exclude_youtube': False, 'exclude_discord': True}] * 10)


class LaneReadiness(unittest.TestCase):
    """One readiness test decides both who sends Discord in the minute tick and whether a shard loop runs."""
    def test_the_readiness_test_names_why_the_lane_cannot_run(self):
        self.assertIsNone(lane.blocker(discord_social(), NOW, {}))
        self.assertIsNone(lane.blocker(discord_social(), NOW, {}, process_state=False))
        for name, setup, reason in NOT_READY:
            with self.subTest(name):
                self.assertEqual(lane.blocker(discord_social(**setup), NOW, {}), reason)
                self.assertEqual(lane.blocker(discord_social(**setup), NOW, {}, process_state=False), reason,
                                 'a static cause stops the lane in every process')
        name, setup, reason = DEGRADED
        self.assertEqual(lane.blocker(discord_social(**setup), NOW, {}), reason)
        self.assertIsNone(lane.blocker(discord_social(**setup), NOW, {}, process_state=False),
                          'a degraded process stops only its own loops')
        both = discord_social(degraded=True, policy='expired')
        self.assertEqual(lane.blocker(both, NOW, {}), 'coordinator_degraded')
        self.assertEqual(lane.blocker(both, NOW, {}, process_state=False), 'coordinator_unavailable')
        self.assertEqual(lane.blocker(discord_social(), NOW, {lane.ENV_SECONDS: 'x'}), 'configuration')
        self.assertEqual(lane.blocker(discord_social(), NOW, {lane.ENV_SECONDS: 'x'}, process_state=False),
                         'configuration')
        self.assertEqual(lane.blocker(SimpleNamespace(), NOW, {}), 'coordinator_unavailable')
        self.assertEqual(lane.blocker(hosted_worker.DisabledHostedSocial(), NOW, {}), 'coordinator_unavailable')
        policy = discord_social().providers['discord'].rate_limiter.policy
        self.assertIsNone(lane.blocker(discord_social(), policy.issued_at, {}))
        for edge in (policy.expires_at, policy.issued_at - .001, float('nan'), None):
            with self.subTest(edge=edge):
                self.assertEqual(lane.blocker(discord_social(), edge, {}), 'coordinator_unavailable')

    @staticmethod
    def projection_only(statements):
        """A database that answers only the lane's schema check: any claim or coordinator read fails the test."""
        @contextmanager
        def factory():
            class Cursor:
                def execute(self, sql, params=()):
                    statements.append(sql)
                    assert sql == "SELECT to_regclass('public.pr_discord_worker_projection')", sql

                def fetchone(self):
                    return ('pr_discord_worker_projection',)

            class Connection:
                def cursor(self):
                    return contextmanager(lambda: (yield Cursor()))()
            yield Connection()
        return factory

    def run_shard(self, social, values=ON):
        statements = []
        base = PostgresWorker(self.projection_only(statements), social=social, clock=lambda: NOW,
                              worker_id='minute', discord_workers=True)
        with patch.object(lane.LaneWorker, 'step', side_effect=AssertionError('a shard claimed work')), \
                self.assertLogs('postriff.request', 'WARNING') as logged:
            result = lane.run(base, 1, values, started=0.0, sleep=Mock(side_effect=AssertionError('slept')),
                              monotonic=lambda: 0.0)
        return result, statements, json.loads(logged.records[-1].getMessage())

    def test_a_shard_that_cannot_run_claims_nothing_and_says_why(self):
        for name, setup, reason in NOT_READY + (DEGRADED,):
            with self.subTest(name):
                result, statements, entry = self.run_shard(discord_social(**setup))
                self.assertEqual((result['stoppedBy'], result['processed'], result['counters']['steps']), (reason, 0, 0))
                self.assertEqual(len(statements), 0, 'no connection at all: no claim, coordinator read or due probe')
                self.assertEqual((entry['event'], entry['stoppedBy']), ('discord.lane.completed', reason))
                self.assertEqual((result['status']['ready'], result['status']['blocker']), (False, reason))

    def test_a_shard_with_a_misconfigured_budget_answers_503_and_claims_nothing(self):
        with self.assertRaises(AlphaError) as refused:
            lane.run(object(), 1, {**ON, lane.ENV_SECONDS: '4'})
        self.assertEqual((refused.exception.status, refused.exception.code), (503, 'discord_lane_configuration'))

    def test_the_minute_tick_and_the_shard_loop_ask_the_same_readiness_test(self):
        asked = []

        def verdict(social, now, values=None, *, process_state=True):
            asked.append((now, process_state))
            return 'coordinator_unavailable'
        seen = []
        with patch.object(lane, 'blocker', verdict), patch.dict('os.environ', ON):
            result = recording_worker(lambda **kw: seen.append(kw) or True, social=discord_social()).tick()
            self.assertNotIn('discordParallelLane', result)
            self.assertEqual(seen.count({'discord_only': True}), 5)
            shard, statements, _ = self.run_shard(discord_social())
        self.assertEqual(shard['stoppedBy'], 'coordinator_unavailable')
        # The same function: the tick decides on its static part; the tick's health status, the shard's pre-claim
        # check and the shard's health status ask the full rule.
        self.assertEqual(asked, [(NOW, False), (NOW, True), (NOW, True), (NOW, True)])
        seen.clear()
        with patch.object(lane, 'blocker', lambda social, now, values=None, **scope: None), patch.dict('os.environ', ON):
            result = recording_worker(lambda **kw: seen.append(kw) or True, social=SimpleNamespace()).tick()
        self.assertTrue(result['discordParallelLane'], 'the tick follows the readiness test alone')
        self.assertEqual(seen, [{'exclude_youtube': False, 'exclude_discord': True}] * 10)


class HealthStatus(unittest.TestCase):
    """lane.status(): a stable, pure health indication in the minute cron's report and every shard answer."""
    SHAPE = {'version': int, 'enabled': bool, 'ready': bool, 'blocker': (str, type(None)),
             'maxSeconds': (float, type(None)), 'maxSteps': (int, type(None)), 'shards': int,
             'policyDaysLeft': (float, type(None)), 'quarantined': int}

    def test_the_shape_is_stable_and_documented(self):
        value = lane.status(discord_social(), NOW, ON)
        self.assertEqual(value, {'version': 1, 'enabled': True, 'ready': True, 'blocker': None, 'maxSeconds': 50.0,
                                 'maxSteps': 600, 'shards': 12, 'policyDaysLeft': 1.0, 'quarantined': lane.quarantined()})
        for name, setup, _ in NOT_READY + (DEGRADED,):
            for values in (ON, {}, {**ON, lane.ENV_SECONDS: 'x'}):
                with self.subTest(name, values=values):
                    other = lane.status(discord_social(**setup), NOW, values)
                    self.assertEqual(set(other), set(self.SHAPE))
                    for key, kinds in self.SHAPE.items():
                        self.assertIsInstance(other[key], kinds, key)
        documented = (ROOT / 'docs/w02/AS-BUILT.md').read_text()
        for key in self.SHAPE:
            self.assertIn('`%s`' % key, documented)

    def test_it_names_each_cause(self):
        cases = [(name, setup, ON, reason) for name, setup, reason in NOT_READY + (DEGRADED,)]
        cases += [('flag off', {}, {}, 'disabled'), ('lease protocol off', {}, {lane.ENV_ENABLED: 'true'}, 'disabled'),
                  ('lane budget misconfigured', {}, {**ON, lane.ENV_SECONDS: '4'}, 'configuration')]
        for name, setup, values, reason in cases:
            with self.subTest(name):
                value = lane.status(discord_social(**setup), NOW, values)
                self.assertEqual((value['ready'], value['blocker']), (False, reason))
                self.assertEqual(value['enabled'], reason != 'disabled')
        self.assertEqual(lane.status(discord_social(), NOW, {**ON, lane.ENV_SECONDS: '4'})['maxSeconds'], None)
        self.assertEqual(lane.status(discord_social(), NOW, {**ON, lane.ENV_SECONDS: '120'})['maxSeconds'], 90.0)
        self.assertEqual(lane.status(discord_social(policy='expired'), NOW, ON)['policyDaysLeft'], -2.0)
        self.assertEqual(lane.status(discord_social(policy='future'), NOW, ON)['policyDaysLeft'], 2.0)
        self.assertIsNone(lane.status(discord_social(policy=None), NOW, ON)['policyDaysLeft'])
        self.assertIsNone(lane.status(None, NOW, ON)['policyDaysLeft'])
        self.assertIsNone(lane.status(discord_social(), float('nan'), ON)['policyDaysLeft'])

    def test_it_is_pure_and_holds_no_secret(self):
        # discord_social()'s coordinator fails the test if it opens a connection; the fence refuses any network.
        value = json.dumps([lane.status(discord_social(**setup), NOW, ON) for _, setup, _ in NOT_READY + (DEGRADED,)])
        for secret in ('synthetic-secret', 'synthetic-bot', APP):
            self.assertNotIn(secret, value)

    def test_the_minute_report_carries_it_whenever_the_flag_is_on(self):
        for name, setup, owned, reason in (('ready', {}, True, None), ('policy expired', {'policy': 'expired'}, False,
                                           'coordinator_unavailable'), (DEGRADED[0], DEGRADED[1], True, DEGRADED[2])):
            with self.subTest(name), patch.dict('os.environ', ON):
                social = discord_social(**setup)
                result = recording_worker(lambda **kw: False, social=social).tick()
                self.assertEqual(result.get('discordParallelLane', False), owned)
                self.assertEqual(result['discordLaneStatus'], lane.status(social, NOW))
                self.assertEqual(result['discordLaneStatus']['blocker'], reason)
        with patch.dict('os.environ', {lane.ENV_ENABLED: 'false', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}):
            result = recording_worker(lambda **kw: False, social=discord_social()).tick()
        self.assertNotIn('discordLaneStatus', result, 'the flag-off tick result stays the frozen one')

    def test_every_shard_answer_carries_it(self):
        self.assertEqual(lane.disabled(5, {})['status']['blocker'], 'disabled')
        result = FakeLane(steps=[False]).run()
        self.assertEqual(set(result['status']), set(self.SHAPE))
        self.assertTrue(result['status']['enabled'])


class LagWarning(unittest.TestCase):
    """With the flag on, the minute tick warns when due Discord work waits too long: from its own report (a sample
    of 256 workspaces) and, when the lane owns Discord, from the projection (every workspace, one statement)."""
    KEYS = {'event', 'oldestEligibleLagSeconds', 'projectedLagSeconds', 'thresholdSeconds', 'report', 'projection',
            'laneOwnsDiscord', 'laneBlocker', 'depth', 'held', 'uncertain', 'deadLetters'}

    def setUp(self):
        for item in (patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')}),
                     patch('postriff_phase2.billing.require_publishing', return_value=None),
                     patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))):
            item.start()
            self.addCleanup(item.stop)

    def projection(self, lag):
        """A database that answers only the projection's due probe: the oldest due work `lag` seconds ago (None:
        nothing due; 'unreadable': the read fails). Any other statement fails the test."""
        statements = self.statements = []

        @contextmanager
        def factory():
            class Cursor:
                def execute(self, sql, params=()):
                    statements.append(sql)
                    assert sql == lane._SOONEST, sql
                    if lag == 'unreadable':
                        raise RuntimeError('synthetic projection read failure')

                def fetchone(self):
                    return (NOW, None if lag is None else NOW - lag)

            class Connection:
                def cursor(self):
                    return contextmanager(lambda: (yield Cursor()))()
            yield Connection()
        return factory

    def tick(self, lag, *, setup=None, environment=ON, projected=0.0):
        report = {'version': 1, 'queue': {'status': 'observed_sample', 'sampled': True, 'workspaceLimit': 256,
                                          'jobLimit': 4096, 'depth': 7, 'oldestEligibleLagSeconds': lag, 'held': 1,
                                          'uncertain': 2, 'deadLetters': 0}}
        if lag is None:
            report['queue'] = {'status': 'unavailable', 'sampled': True}
        worker = recording_worker(lambda **kw: False, social=discord_social(**(setup or {})))
        worker.discord_report = lambda: copy.deepcopy(report)
        worker.connection_factory = self.projection(projected)
        with patch.dict('os.environ', environment):
            result = worker.tick()
        self.assertEqual(result['discordWorker'], report, 'the report is returned unchanged')
        return result

    def test_the_threshold_is_five_minutes(self):
        self.assertEqual(lane.LAG_WARNING_SECONDS, 300)

    def test_due_work_later_than_five_minutes_logs_one_warning_with_counts_only(self):
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            self.tick(301.0)
        (record,) = logged.records
        entry = json.loads(record.getMessage())
        self.assertEqual(set(entry), self.KEYS)
        self.assertEqual(entry, {'event': 'discord.lane.lagging', 'oldestEligibleLagSeconds': 301.0,
                                 'projectedLagSeconds': 0.0, 'thresholdSeconds': 300, 'report': 'sample',
                                 'projection': 'read', 'laneOwnsDiscord': True, 'laneBlocker': None,
                                 'depth': 7, 'held': 1, 'uncertain': 2, 'deadLetters': 0})
        self.assertEqual(self.statements, [lane._SOONEST], 'one statement: the projection due probe')

    def test_at_or_below_five_minutes_nothing_is_logged(self):
        for lag in (300.0, 299.9, 0.0):
            with self.subTest(lag=lag), self.assertNoLogs('postriff.request', 'WARNING'):
                self.tick(lag, projected=lag)

    def test_lagging_work_outside_the_reports_sample_is_seen_in_the_projection(self):
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            self.tick(0.0, projected=901.0)
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual((entry['oldestEligibleLagSeconds'], entry['projectedLagSeconds'], entry['projection']),
                         (0.0, 901.0, 'read'))

    def test_a_report_that_failed_is_a_warning_of_its_own(self):
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            self.tick(None)
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual((entry['report'], entry['oldestEligibleLagSeconds'], entry['projectedLagSeconds']),
                         ('unavailable', None, 0.0))

    def test_a_projection_that_cannot_be_read_while_the_lane_owns_discord_is_a_warning(self):
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            result = self.tick(0.0, projected='unreadable')
        self.assertTrue(result['discordParallelLane'], 'the tick itself goes on')
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual((entry['projection'], entry['projectedLagSeconds']), ('unreadable', None))

    def test_with_the_flag_off_the_frozen_tick_never_warns(self):
        with self.assertNoLogs('postriff.request', 'WARNING'):
            self.tick(10_000.0, environment={lane.ENV_ENABLED: 'false', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'},
                      projected=10_000.0)
        self.assertEqual(self.statements, [], 'the frozen tick reads no projection')

    def test_a_tick_that_kept_discord_says_why_the_lane_could_not_run(self):
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            result = self.tick(900.0, setup={'policy': 'expired'})
        self.assertNotIn('discordParallelLane', result)
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual((entry['laneOwnsDiscord'], entry['laneBlocker']), (False, 'coordinator_unavailable'))

    def test_a_coordinator_degraded_only_in_this_process_leaves_the_lane_owning_discord(self):
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            result = self.tick(900.0, setup=DEGRADED[1])
        self.assertTrue(result['discordParallelLane'])
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual((entry['laneOwnsDiscord'], entry['laneBlocker']), (True, None))

    def test_the_warning_comes_from_the_report_the_tick_already_makes(self):
        statements, warnings = {}, {}
        for late in (10, 700):
            db = MemoryDatabase(FlagOffIsTheFrozenBase.queue())
            db.projection_ready = True  # the production schema (migration 126): the tick also reads its due probe
            db.now = NOW + 300 + late
            worker = PostgresWorker(db.connection, discord_social(db.connection), clock=lambda: db.now,
                                    worker_id='minute-worker', discord_workers=True)
            with patch.dict('os.environ', ON, clear=True), self.assertLogs('postriff.request', 'DEBUG') as logged:
                logging.getLogger('postriff.request').debug('marker')
                result = worker.tick()
            self.assertTrue(result['discordParallelLane'])
            statements[late] = [sql for sql, _ in db.queries]
            warnings[late] = [record.getMessage() for record in logged.records if 'discord.lane.lagging' in record.getMessage()]
        self.assertEqual(statements[700], statements[10], 'warning or not, the tick runs the same statements')
        self.assertEqual(statements[10].count(lane._SOONEST), 1, 'plus one statement: the projection due probe')
        self.assertEqual(warnings[10], [])
        (message,) = warnings[700]
        self.assertEqual(json.loads(message)['oldestEligibleLagSeconds'], 700.0)
        self.assertEqual(json.loads(message)['projectedLagSeconds'], 700.0)
        private = {WORKSPACE, 'minute-worker'}
        for job in db.state['phase2']['jobs']:
            target = job['manifest']['discord']['target']
            private |= {job['id'], job['manifest']['channelId'], target['channelId'], target['guildId']}
        for value in private:
            self.assertNotIn(value, message)


class Deterministic:
    """Same ids and clocks for two runs, so their traces can be compared exactly."""
    def __enter__(self):
        counter = itertools.count(1)
        clock = itertools.count(0)
        self.patches = [patch.object(uuid, 'uuid4', lambda: uuid.UUID(int=next(counter))),
                        patch.object(time, 'monotonic', lambda: next(clock) * 0.001)]
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *exc):
        for item in reversed(self.patches):
            item.stop()


class FlagOffIsTheFrozenBase(unittest.TestCase):
    """The frozen release candidate's worker (2a5a523d) and this one, run side by side on the same inputs."""
    @classmethod
    def setUpClass(cls):
        source = BASE_SOURCE.read_bytes()
        assert hashlib.sha256(source).hexdigest() == BASE_SHA256, 'the pinned base worker changed'
        namespace = {'__name__': 'postriff_phase2.hosted_worker_2a5a523d', '__package__': 'postriff_phase2',
                     '__builtins__': __builtins__}
        exec(compile(source, str(BASE_SOURCE), 'exec'), namespace)
        cls.Base = namespace['PostgresWorker']

    def setUp(self):
        for item in (patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')}),
                     patch('postriff_phase2.billing.require_publishing', return_value=None),
                     patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))):
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def queue(jobs=2):
        engine, state, channel, variant = fixture()
        approve(engine, state, review(engine, state, channel, variant))
        for number in range(1, jobs):
            draft = dict(variant, id='synthetic-draft-%d' % number, text='Synthetic second post %d' % number)
            state['variants'].append(draft)
            approve(engine, state, review(engine, state, channel, draft))
        return state

    def trace(self, cls, environment, state, setup=None):
        db, wire = MemoryDatabase(copy.deepcopy(state)), SyntheticWire()
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                                   transport=wire, production_reviewed=True)
        provider.authorization_v2_enabled = True
        if setup is not None:
            coordinator(provider, db.connection, **setup)
        social = HostedSocial(SyntheticGrants(), {'discord': provider})
        with patch.dict('os.environ', environment, clear=True), Deterministic():
            worker = cls(db.connection, social, clock=lambda: NOW + 301, worker_id='trace-worker')
            results = [worker.tick() for _ in range(3)]
        return {'sql': db.queries, 'http': wire.calls, 'state': db.state, 'results': results,
                'stats': worker.discord_stats}

    def assert_same(self, environment, setup=None):
        state = self.queue()
        base = self.trace(self.Base, environment, state, setup)
        current = self.trace(PostgresWorker, environment, state, setup)
        self.assertGreater(len(base['sql']), 10)
        # With the flag on, each tick result also carries the health indication: the one added key, checked on its
        # own; every SQL statement, request, state, stat and other result field is still compared byte for byte.
        statuses = [result.pop('discordLaneStatus', None) for result in current['results']]
        if lane.enabled(environment):
            self.assertTrue(all(isinstance(value, dict) and value['enabled'] for value in statuses), statuses)
        else:
            self.assertEqual(statuses, [None] * 3, 'the flag-off tick result is byte for byte the base')
        for key in ('sql', 'http', 'state', 'results', 'stats'):
            with self.subTest(key=key):
                self.assertEqual(json.dumps(current[key], sort_keys=True, default=repr),
                                 json.dumps(base[key], sort_keys=True, default=repr))
        base['statuses'] = statuses
        return base

    def test_flag_unset_matches_the_base_exactly(self):
        base = self.assert_same({'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'})
        self.assertTrue(any(call[0] == 'POST' for call in base['http']), 'the run reached a Discord create')

    def test_flag_not_exactly_true_matches_the_base_exactly(self):
        for value in ('TRUE', '1', 'yes', ' true'):
            with self.subTest(value=value):
                self.assert_same({'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true', lane.ENV_ENABLED: value})

    def test_flag_on_without_the_worker_protocol_matches_the_base_exactly(self):
        self.assert_same({lane.ENV_ENABLED: 'true'})

    def test_flag_on_with_rate_limits_off_matches_the_base_exactly(self):
        # The lane cannot run without the coordinator, so the minute tick keeps sending Discord as the base does.
        base = self.assert_same({'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true', lane.ENV_ENABLED: 'true'})
        self.assertTrue(any(call[0] == 'POST' for call in base['http']), 'the run reached a Discord create')

    def test_flag_on_but_the_lane_unable_to_run_matches_the_base_exactly(self):
        environment = {'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true', lane.ENV_ENABLED: 'true'}
        for name, setup, reason in NOT_READY:
            with self.subTest(name):
                base = self.assert_same(environment, setup)
                self.assertGreater(base['stats']['claims'], 0, 'the frozen tick claimed Discord work')
                self.assertEqual({(s['ready'], s['blocker']) for s in base['statuses']}, {(False, reason)},
                                 'the report says why the lane is not running')
        with self.subTest('lane budget misconfigured'):
            base = self.assert_same({**environment, lane.ENV_SECONDS: 'x'}, {})
            self.assertEqual({(s['ready'], s['blocker']) for s in base['statuses']}, {(False, 'configuration')})

    def test_control_flag_on_and_the_lane_able_to_run_changes_the_trace(self):
        environment = {'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true', lane.ENV_ENABLED: 'true'}
        # A coordinator degraded only in this process still leaves Discord to the lane loops of healthy processes.
        for name, setup in (('lane able to run', {}), DEGRADED[:2]):
            with self.subTest(name):
                state = self.queue()
                base = self.trace(self.Base, environment, state, setup)
                current = self.trace(PostgresWorker, environment, state, setup)
                self.assertGreater(base['stats']['claims'], 0, 'the frozen tick claims Discord')
                self.assertEqual(current['stats']['claims'], 0, 'the minute tick leaves Discord to the lane')
                self.assertEqual(current['http'], [])
                jobs = current['state']['phase2']['jobs']
                self.assertEqual({job['state'] for job in jobs}, {'scheduled'})
                self.assertFalse([job for job in jobs if job.get('attempts')])
                self.assertTrue(all(result['discordParallelLane'] for result in current['results']))


class FakeLane:
    """Drives run() without a database: steps, the coordinator outlook and the due hint are scripted."""
    def __init__(self, steps=None, outlooks=None, due=None, step_seconds=1.0, projection=True):
        self.now = 0.0
        self.steps, self.outlooks, self.due = list(steps or []), list(outlooks or []), list(due or [])
        self.step_seconds, self.projection = step_seconds, projection
        self.started, self.slept, self.outlook_calls = [], [], 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def step(self, worker, **kw):
        assert kw == {'discord_only': True}
        self.started.append(self.now)
        self.now += self.step_seconds
        outcome = self.steps.pop(0) if self.steps else True
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == 'claim':
            worker.discord_stats['claims'] += 1
            return True
        return outcome

    def outlook(self, worker):
        self.outlook_calls += 1
        return self.outlooks.pop(0) if self.outlooks else (None, 0.0)

    @contextmanager
    def patched(self):
        with patch.object(lane, 'outlook', self.outlook), \
                patch.object(lane, 'soonest_due', lambda worker: self.due.pop(0) if self.due else None), \
                patch.object(lane, '_projection_ready', lambda worker: self.projection), \
                patch.object(lane.LaneWorker, 'step', lambda worker, **kw: self.step(worker, **kw)):
            yield

    def run(self, values=None, **kw):
        base = PostgresWorker(lambda: None, social=SimpleNamespace(providers={}), worker_id='fake', discord_workers=True)
        with self.patched():
            return lane.run(base, 2, {**ON, **(values or {})}, started=0.0, sleep=self.sleep, monotonic=self.monotonic,
                            rng=SimpleNamespace(random=lambda: 0.0), **kw)


class TheLoop(unittest.TestCase):
    def test_no_step_starts_after_the_budget_and_the_last_ends_within_one_step(self):
        fake = FakeLane(step_seconds=7.0)
        result = fake.run({lane.ENV_SECONDS: '50'})
        self.assertEqual(result['stoppedBy'], 'time_budget')
        self.assertTrue(all(at < 50 for at in fake.started))
        self.assertLessEqual(result['elapsedSeconds'], 50 + 7)
        self.assertEqual(len(fake.started), 8)

    def test_a_configured_120_seconds_runs_for_90(self):
        fake = FakeLane(step_seconds=7.0)
        result = fake.run({lane.ENV_SECONDS: '120'})
        self.assertEqual((result['stoppedBy'], result['budget']['maxSeconds']), ('time_budget', 90.0))
        self.assertTrue(all(at < 90 for at in fake.started))
        self.assertGreaterEqual(fake.started[-1], 90 - 7)
        self.assertLessEqual(result['elapsedSeconds'], 90 + 7)

    def test_the_step_budget_bounds_a_fast_loop(self):
        fake = FakeLane(step_seconds=.001)
        self.assertEqual(fake.run({lane.ENV_STEPS: '25'})['stoppedBy'], 'step_budget')
        self.assertEqual(len(fake.started), 25)

    def test_an_operator_hold_before_the_first_claim_stops_with_no_step(self):
        fake = FakeLane(outlooks=[('operator_hold', 0.0)])
        result = fake.run()
        self.assertEqual((result['stoppedBy'], fake.started), ('operator_hold', []))

    def test_an_operator_hold_set_mid_run_stops_at_the_next_iteration(self):
        fake = FakeLane(outlooks=[(None, 0.0)] * 3 + [('operator_hold', 0.0)])
        result = fake.run()
        self.assertEqual(result['stoppedBy'], 'operator_hold')
        self.assertEqual(len(fake.started), 3, 'no step after the hold was seen')
        self.assertEqual(fake.outlook_calls, 4)

    def test_a_degraded_or_unavailable_coordinator_stops_the_loop(self):
        for blocker in ('coordinator_degraded', 'coordinator_unavailable'):
            with self.subTest(blocker=blocker):
                fake = FakeLane(outlooks=[(blocker, 0.0)])
                self.assertEqual(fake.run()['stoppedBy'], blocker)
                self.assertEqual(fake.started, [])

    def test_an_embargo_is_slept_out_before_the_next_claim(self):
        fake = FakeLane(outlooks=[(None, 0.0), (None, 4.0), (None, 0.0)], steps=[True, True, False])
        result = fake.run()
        self.assertEqual(fake.started[1] - fake.started[0], 1.0 + 4.0 + .01)
        self.assertEqual(result['counters']['rateWaits'], 1)
        self.assertEqual(result['waitedSeconds']['rate'], 4.01)

    def test_an_embargo_longer_than_the_budget_ends_the_loop_instead_of_waiting(self):
        fake = FakeLane(outlooks=[(None, 60.0)])
        result = fake.run({lane.ENV_SECONDS: '30'})
        self.assertEqual((result['stoppedBy'], fake.started, fake.slept), ('rate_wait', [], []))

    def test_no_due_work_ends_the_loop_after_one_miss(self):
        fake = FakeLane(steps=[False], due=[None])
        result = fake.run()
        self.assertEqual((result['stoppedBy'], len(fake.started)), ('idle', 1))

    def test_work_due_within_seconds_is_waited_for(self):
        fake = FakeLane(steps=[False, 'claim', False], due=[4.0, None])
        result = fake.run()
        self.assertEqual(fake.slept, [4.0])
        self.assertEqual(result['counters']['idleWaits'], 1)
        self.assertEqual(result['counters']['claimed'], 1)

    def test_work_due_later_than_the_horizon_is_left_to_the_next_minute(self):
        fake = FakeLane(steps=[False], due=[lane.IDLE_HORIZON_SECONDS + 1])
        self.assertEqual(fake.run()['stoppedBy'], 'idle')
        self.assertEqual(fake.slept, [])

    def test_overdue_work_another_loop_holds_is_retried_a_few_times_then_left(self):
        fake = FakeLane(steps=[False] * 20, due=[-1.0] * 20, step_seconds=.01)
        result = fake.run()
        self.assertEqual(result['stoppedBy'], 'idle')
        self.assertEqual(len(fake.started), lane.MAX_IDLE_MISSES + 1)
        self.assertEqual(fake.slept, [min(1.0, .05 * 2 ** n) for n in range(1, lane.MAX_IDLE_MISSES + 1)])

    def test_missing_projection_schema_claims_nothing(self):
        fake = FakeLane(projection=False)
        self.assertEqual((fake.run()['stoppedBy'], fake.started), ('schema', []))

    def test_a_step_failure_is_logged_with_its_class_and_raised(self):
        fake = FakeLane(steps=['claim', RuntimeError('database down')])
        with self.assertLogs('postriff.request', 'WARNING') as logged, self.assertRaises(RuntimeError):
            fake.run()
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual((entry['event'], entry['stoppedBy'], entry['error']), ('discord.lane.completed', 'error', 'RuntimeError'))
        self.assertEqual(entry['counters']['claimed'], 1)
        self.assertNotIn('database down', logged.records[-1].getMessage())

    def test_each_invocation_logs_its_counters_and_no_identifiers(self):
        fake = FakeLane(steps=['claim', 'claim', False])
        with self.assertLogs('postriff.request', 'INFO') as logged:
            result = fake.run(request_id='req-1')
        entry = json.loads(logged.records[-1].getMessage())
        self.assertEqual(entry['event'], 'discord.lane.completed')
        self.assertEqual(entry['requestId'], 'req-1')
        self.assertEqual(set(entry['counters']), set(lane.COUNTERS))
        self.assertEqual(entry['counters']['claimed'], 2)
        self.assertEqual({key: entry[key] for key in result}, result)
        self.assertNotIn('discord-lane-', logged.records[-1].getMessage(), 'the lease owner id is not logged')

    def test_flag_off_runs_nothing(self):
        fake = FakeLane()
        with fake.patched():
            result = lane.run(object(), 4, {lane.ENV_ENABLED: 'true'})
        self.assertEqual(result, lane.disabled(4, {lane.ENV_ENABLED: 'true'}))
        self.assertEqual(result['status']['blocker'], 'disabled')
        self.assertEqual(fake.started, [])

    def test_every_invocation_has_its_own_lease_owner(self):
        base = PostgresWorker(lambda: None, social=SimpleNamespace(providers={}), worker_id='shared', discord_workers=True)
        one, two = lane.LaneWorker(base, 0), lane.LaneWorker(base, 0)
        self.assertNotEqual(one.worker_id, two.worker_id)
        self.assertTrue(one.worker_id.startswith('discord-lane-0-'))
        self.assertTrue(one.discord_workers)
        self.assertIs(one.connection_factory, base.connection_factory)
        self.assertEqual(one.worker_binding, base.worker_binding)


class Outlook(unittest.TestCase):
    """The pre-claim read uses the coordinator's own key derivation and only reads."""
    def setUp(self):
        build = POLICY_TOOL.build
        self.provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                                        transport=SyntheticWire(), production_reviewed=True)
        self.provider.rate_v1_enabled = True
        self.now = 1_800_000_000.0
        self.statements = []
        self.rows = []
        self.provider.rate_limiter = SharedPostgresBudget(self.factory, APP,
                                                          policy=json.dumps(build(self.now - 100, days=1)))
        self.worker = SimpleNamespace(social=SimpleNamespace(providers={'discord': self.provider}),
                                      connection_factory=self.factory, clock=lambda: self.now)

    @contextmanager
    def factory(self):
        test = self

        class Cursor:
            def execute(self, sql, params=()):
                test.statements.append((sql, params))

            def fetchall(self):
                return test.rows or [(test.now, None, None, None, None, None, None, None)]

        class Connection:
            def cursor(self):
                return contextmanager(lambda: (yield Cursor()))()
        yield Connection()

    def keys(self):
        limiter = self.provider.rate_limiter
        identity = self.provider._rate_identity('bot')
        expected = limiter._keys(identity, 'r' * 64, 'm' * 64, 'b' * 64)
        return sorted(key for key in expected if expected[key][0] in ('policy', 'global', 'credential', 'invalid'))

    def row(self, key, kind, hold=False, remaining=10, reset=None, blocked=None, circuit=None):
        return (self.now, key, kind, hold, remaining, reset, blocked, circuit)

    def test_it_reads_the_four_application_wide_rows_without_locking(self):
        self.assertEqual(lane.outlook(self.worker), (None, 0.0))
        (sql, params), = self.statements
        self.assertNotIn('FOR UPDATE', sql.upper())
        self.assertNotIn('FOR SHARE', sql.upper())
        self.assertTrue(sql.lstrip().upper().startswith('WITH OBSERVED'))
        self.assertEqual(params, (self.keys(),))

    def test_a_hold_on_the_policy_row_is_the_operator_hold_and_any_other_hold_also_stops(self):
        for index, kind in enumerate(('policy', 'global', 'credential', 'invalid')):
            with self.subTest(kind=kind):
                self.rows = [self.row(self.keys()[index], kind, hold=True)]
                self.assertEqual(lane.outlook(self.worker),
                                 ('operator_hold' if kind == 'policy' else 'coordinator_hold', 0.0))

    def test_embargoes_circuits_and_a_spent_window_become_a_wait(self):
        policy, global_ = self.keys()[0], self.keys()[1]
        self.rows = [self.row(policy, 'policy', remaining=0, reset=self.now + .4),
                     self.row(global_, 'global', remaining=None, blocked=self.now + 3)]
        self.assertEqual(lane.outlook(self.worker), (None, 3.0))
        self.rows = [self.row(policy, 'policy', remaining=0, reset=self.now + .4)]
        self.assertAlmostEqual(lane.outlook(self.worker)[1], .4, places=5)
        self.rows = [self.row(policy, 'policy', remaining=0, reset=self.now - 1)]
        self.assertEqual(lane.outlook(self.worker), (None, 0.0), 'a past window refills on the next reservation')

    def test_a_spent_invalid_request_budget_is_a_wait_like_a_spent_window(self):
        # The coordinator refuses on any capped row with nothing left (rate_limits._reserve), not only the policy row.
        invalid = self.keys()[3]
        self.rows = [self.row(invalid, 'invalid', remaining=0, reset=self.now + 42)]
        self.assertEqual(lane.outlook(self.worker), (None, 42.0))
        for remaining, reset in ((1, self.now + 42), (0, self.now - 1), (0, None)):
            with self.subTest(remaining=remaining, reset=reset):
                self.rows = [self.row(invalid, 'invalid', remaining=remaining, reset=reset)]
                self.assertEqual(lane.outlook(self.worker), (None, 0.0))
        for index, kind in ((1, 'global'), (2, 'credential')):
            with self.subTest(kind=kind):  # uncapped rows: their remaining is NULL, only embargoes count
                self.rows = [self.row(self.keys()[index], kind, remaining=None, reset=self.now + 42)]
                self.assertEqual(lane.outlook(self.worker), (None, 0.0))

    def test_an_expired_policy_or_missing_coordinator_stops_the_loop(self):
        self.now = self.provider.rate_limiter.policy.expires_at + 1
        self.assertEqual(lane.outlook(self.worker)[0], 'coordinator_unavailable')
        self.provider.rate_v1_enabled = False
        self.assertEqual(lane.outlook(self.worker)[0], 'coordinator_unavailable')
        self.provider.rate_v1_enabled = True
        self.provider.rate_coordinator_degraded = True
        self.assertEqual(lane.outlook(self.worker)[0], 'coordinator_degraded')
        self.worker.social = SimpleNamespace(providers={})
        self.assertEqual(lane.outlook(self.worker)[0], 'coordinator_unavailable')


class CreatePermitWait(unittest.TestCase):
    def social(self, *errors):
        calls = []

        def reserve(manifest, **kw):
            calls.append(kw)
            if errors[len(calls) - 1:len(calls)]:
                raise errors[len(calls) - 1]
            return 'permit'
        clock = SimpleNamespace(now=0.0)
        paced = lane.PacedSocial(SimpleNamespace(reserve_discord_send=reserve, other='kept'),
                                 sleep=lambda s: setattr(clock, 'now', clock.now + s), monotonic=lambda: clock.now)
        return paced, calls, clock

    def test_a_spent_application_window_is_waited_for_once_within_a_second(self):
        paced, calls, clock = self.social(RateDelayed(.4, scope='application'))
        self.assertEqual(paced.reserve_discord_send({}, job={'id': 'j'}), 'permit')
        self.assertEqual((len(calls), paced.permit_waits), (2, 1))
        self.assertLess(clock.now, 1.0)
        self.assertEqual(calls[0], calls[1], 'the same binding and deadline are asked for again')
        self.assertEqual(paced.other, 'kept')

    def test_a_permit_that_lapsed_at_its_window_end_is_asked_for_again(self):
        paced, calls, _ = self.social(RateDelayed(.05, cause='permit_expired', scope='permit'))
        self.assertEqual(paced.reserve_discord_send({}), 'permit')
        self.assertEqual(len(calls), 2)

    def test_an_embargo_a_channel_window_or_a_passed_deadline_is_refused_as_before(self):
        for scope, cause in (('embargo', 'rate_budget'), ('learned_route', 'rate_budget'), ('unknown_route', 'rate_budget'),
                             ('discovery', 'rate_budget'), ('unknown', 'rate_budget'), ('permit', 'window_expiring')):
            with self.subTest(scope=scope, cause=cause):
                paced, calls, _ = self.social(RateDelayed(.2, cause=cause, scope=scope))
                with self.assertRaises(RateDelayed):
                    paced.reserve_discord_send({})
                self.assertEqual(len(calls), 1)

    def test_the_wait_never_runs_past_one_second(self):
        paced, calls, clock = self.social(*[RateDelayed(.45, scope='application')] * 5)
        with self.assertRaises(RateDelayed):
            paced.reserve_discord_send({})
        self.assertLessEqual(clock.now, 1.0)
        self.assertEqual(len(calls), 3)


class Quarantine(unittest.TestCase):
    """G2E-C-10: a document the claim cannot read stops only its own workspace. The real-PostgreSQL proof, with other
    workspaces to go on to, is in test_discord_parallel_lane_postgres.py (section m); here the claim's own rules."""
    def setUp(self):
        for item in (patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')}),
                     patch('postriff_phase2.billing.require_publishing', return_value=None),
                     patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))):
            item.start()
            self.addCleanup(item.stop)
        self.db = MemoryDatabase(FlagOffIsTheFrozenBase.queue())
        base = PostgresWorker(self.db.connection, discord_social(self.db.connection), clock=lambda: NOW + 301,
                              worker_id='minute-worker', discord_workers=True)
        self.worker = lane.LaneWorker(base, 0)

    def failing_claim(self, errors):
        """Replace the inherited claim by one that reads WORKSPACE and raises each error in turn, then succeeds."""
        calls = []

        def claim(worker, **options):
            calls.append(options)
            worker._examining = WORKSPACE
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return {'workspaceId': WORKSPACE, 'job': {'id': 'claimed'}, 'reconciliation': True}
        return patch.object(PostgresWorker, '_claim', claim), calls

    def test_a_failure_reading_a_document_sets_that_workspace_aside_and_the_claim_goes_on(self):
        for error in (AttributeError('x'), TypeError('x'), KeyError('x'), IndexError('x'), ValueError('x')):
            with self.subTest(error=type(error).__name__):
                replaced, calls = self.failing_claim([error])
                with replaced, patch.object(lane.LaneWorker, '_quarantine') as quarantine:
                    self.assertEqual(self.worker.claim(discord_only=True)['job']['id'], 'claimed')
                self.assertEqual(len(calls), 2, 'the claim ran again')
                quarantine.assert_called_once_with(WORKSPACE, error)

    def test_a_failure_that_is_not_the_shape_of_a_document_is_raised_as_before(self):
        for error in (RuntimeError('database down'), AlphaError('Worker claim lost its workspace revision.', 409),
                      OSError('connection lost')):
            with self.subTest(error=type(error).__name__):
                replaced, calls = self.failing_claim([error])
                with replaced, patch.object(lane.LaneWorker, '_quarantine') as quarantine, self.assertRaises(type(error)):
                    self.worker.claim(discord_only=True)
                self.assertEqual((len(calls), quarantine.called), (1, False))

    def test_the_third_failure_in_one_claim_is_the_claim_code_not_a_document_and_is_raised(self):
        replaced, calls = self.failing_claim([TypeError('1'), TypeError('2'), TypeError('3'), TypeError('4')])
        with replaced, patch.object(lane.LaneWorker, '_quarantine') as quarantine, self.assertRaises(TypeError) as raised:
            self.worker.claim(discord_only=True)
        self.assertEqual(str(raised.exception), '3')
        self.assertEqual((len(calls), quarantine.call_count), (lane.MAX_QUARANTINES_PER_CLAIM + 1,
                                                              lane.MAX_QUARANTINES_PER_CLAIM))

    def test_a_failure_before_any_workspace_is_read_is_raised(self):
        def claim(worker, **options):
            raise TypeError('before the first candidate')
        with patch.object(PostgresWorker, '_claim', claim), patch.object(lane.LaneWorker, '_quarantine') as quarantine, \
                self.assertRaises(TypeError):
            self.worker.claim(discord_only=True)
        self.assertFalse(quarantine.called)

    def test_only_the_loops_unscoped_discord_claim_is_guarded(self):
        scope = dict(workspace_id=WORKSPACE, job_id='j', approval_digest='a' * 64, dispatch_principal='p')
        for name, options in (('scoped', {**scope, 'discord_only': True}), ('not Discord', {}),
                              ('youtube', {'youtube_only': True})):
            with self.subTest(name):
                replaced, calls = self.failing_claim([TypeError('x')])
                with replaced, patch.object(lane.LaneWorker, '_quarantine') as quarantine, self.assertRaises(TypeError):
                    self.worker.claim(**options)
                self.assertEqual((len(calls), quarantine.called), (1, False))

    def test_a_workspace_that_cannot_be_set_aside_keeps_the_original_failure(self):
        error = AttributeError('the document')
        replaced, _ = self.failing_claim([error])
        with replaced, patch.object(lane.LaneWorker, '_quarantine', side_effect=RuntimeError('database down')), \
                self.assertRaises(AttributeError) as raised:
            self.worker.claim(discord_only=True)
        self.assertIs(raised.exception, error)

    def test_setting_aside_dates_the_cursor_ahead_counts_and_logs_one_line_without_identifiers(self):
        before = lane.quarantined()
        with self.assertLogs('postriff.request', 'WARNING') as logged:
            self.worker._quarantine(WORKSPACE, AttributeError("'NoneType' object has no attribute 'append'"))
        (record,) = logged.records
        entry = json.loads(record.getMessage())
        self.assertEqual(entry, {'event': 'discord.lane.quarantined', 'error': 'AttributeError',
                                 'quarantineSeconds': lane.QUARANTINE_SECONDS})
        for private in (WORKSPACE, 'minute-worker', self.worker.worker_id, 'NoneType', 'append'):
            self.assertNotIn(private, record.getMessage())
        cursor = self.db.state['phase2'][hosted_worker.discord_worker.CURSOR]
        until = self.db.now + lane.QUARANTINE_SECONDS
        self.assertEqual(cursor, {'version': 1, 'lastClaimedAt': until, 'quarantinedUntil': until})
        self.assertEqual((self.worker.discord_stats['quarantined'], lane.quarantined() - before), (1, 1))
        self.assertEqual(lane.status(self.worker.social, NOW + 301, ON)['quarantined'], lane.quarantined())
        for job in self.db.state['phase2']['jobs']:
            self.assertEqual(job['state'], 'scheduled', 'only the cursor changed')
            self.assertNotIn('lastDispatchedAt', job)

    def test_a_workspace_set_aside_is_not_offered_again_until_its_window_ends_and_then_is_claimed_by_itself(self):
        self.worker._quarantine(WORKSPACE, TypeError())
        self.assertIsNone(self.worker.claim(discord_only=True), 'skipped: nothing else is due')
        self.assertEqual(self.worker.discord_stats['claimMisses'], 1)
        self.assertEqual({job['state'] for job in self.db.state['phase2']['jobs']}, {'scheduled'})
        self.db.state['phase2'][hosted_worker.discord_worker.CURSOR]['quarantinedUntil'] = NOW + 300  # ended
        claimed = self.worker.claim(discord_only=True)
        self.assertEqual(claimed['workspaceId'], WORKSPACE)
        self.assertNotIn('quarantinedUntil', self.db.state['phase2'][hosted_worker.discord_worker.CURSOR],
                         'the first normal claim clears the mark')


class PositionKept(unittest.TestCase):
    """F2: a release the shared budget caused puts the claim's stamps back. The cross-workspace order, with real
    rotation, is in test_discord_parallel_lane_postgres.py (section n); here the rule on one document."""
    CURSOR = hosted_worker.discord_worker.CURSOR

    def setUp(self):
        for item in (patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')}),
                     patch('postriff_phase2.billing.require_publishing', return_value=None),
                     patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))):
            item.start()
            self.addCleanup(item.stop)
        self.db = MemoryDatabase(FlagOffIsTheFrozenBase.queue())
        self.base = PostgresWorker(self.db.connection, discord_social(self.db.connection), clock=lambda: NOW + 301,
                                   worker_id='minute-worker', discord_workers=True)
        self.worker = lane.LaneWorker(self.base, 0)

    def jobs(self):
        return self.db.state['phase2']['jobs']

    def released(self, worker=None, *, scope='application', cause='rate_budget', reason='rate_delayed', seconds=2.0):
        """Claim the first due post and release it unsent, the way step() does for a refused permit."""
        worker = worker or self.worker
        claimed = worker.claim(discord_only=True)
        self.assertEqual(claimed['workspaceId'], WORKSPACE)
        self.assertTrue(worker.release_discord_unsent(claimed, reason=reason, retry_after_seconds=seconds,
                                                      rate_cause=cause, rate_scope=scope))
        return claimed

    def test_a_spent_application_window_or_an_unused_permit_puts_the_stamps_back_and_the_retry_is_due_at_once(self):
        for name, scope, cause in (('application window', 'application', 'rate_budget'),
                                   ('permit ended before the seal', 'unknown', 'permit_expired'),
                                   ('permit ended before use', 'permit', 'permit_expired')):
            with self.subTest(name):
                self.setUp()
                claimed = self.released(scope=scope, cause=cause)
                self.assertEqual(claimed['positionBefore'], {'cursor': None, 'lastDispatchedAt': None})
                job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
                self.assertEqual((job['state'], job['leaseOwner']), ('scheduled', None))
                self.assertNotIn('lastDispatchedAt', job, 'as the claim found it')
                self.assertNotIn(self.CURSOR, self.db.state['phase2'], 'the workspace turn is back too')
                self.assertEqual((job['nextAt'], job['discordWorker']['rateDelayedUntil']), (self.db.now, self.db.now))
                self.assertEqual(job['discordPositionRestores'], 1)
                self.assertEqual(self.worker.lane_counts['positionsKept'], 1)
                again = self.worker.claim(discord_only=True)
                self.assertEqual(again['job']['id'], claimed['job']['id'], 'the same post is the very next claim')

    def test_the_values_the_claim_found_are_the_values_that_come_back(self):
        self.db.state['phase2'][self.CURSOR] = {'version': 1, 'lastClaimedAt': 123.5}
        self.jobs()[0]['lastDispatchedAt'] = 77.0
        self.released()
        self.assertEqual(self.jobs()[0]['lastDispatchedAt'], 77.0)
        self.assertEqual(self.db.state['phase2'][self.CURSOR], {'version': 1, 'lastClaimedAt': 123.5})

    def test_a_release_one_tenants_resource_caused_keeps_the_claims_stamps(self):
        for scope, cause in (('learned_route', 'rate_budget'), ('unknown_route', 'rate_budget'), ('discovery', 'rate_budget'),
                             ('embargo', 'rate_budget'), ('embargo', 'permit_blocked'), ('unknown', 'provider_429'),
                             ('permit', 'window_expiring'), (None, None)):
            with self.subTest(scope=scope, cause=cause):
                self.setUp()
                claimed = self.released(scope=scope, cause=cause, seconds=2.0)
                job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
                self.assertEqual(job['lastDispatchedAt'], self.db.now, 'the penalty')
                self.assertEqual(self.db.state['phase2'][self.CURSOR], {'version': 1, 'lastClaimedAt': self.db.now})
                self.assertEqual(job['nextAt'], self.db.now + 2.0)
                self.assertNotIn('discordPositionRestores', job)
                self.assertEqual(self.worker.lane_counts['positionsKept'], 0)

    def test_a_release_that_is_not_a_rate_wait_keeps_the_claims_stamps(self):
        for reason in ('preflight_transient', 'shutdown'):
            with self.subTest(reason):
                self.setUp()
                claimed = self.released(reason=reason, scope='application', cause='permit_expired')
                job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
                self.assertEqual(job['lastDispatchedAt'], self.db.now)
                self.assertNotIn('discordPositionRestores', job)

    def test_the_position_is_kept_for_three_releases_of_a_post_and_then_it_is_not(self):
        for number in range(1, lane.MAX_POSITION_RESTORES + 1):
            claimed = self.released()
            job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
            self.assertEqual((job['discordPositionRestores'], 'lastDispatchedAt' in job), (number, False))
        self.assertEqual(lane.MAX_POSITION_RESTORES, 3)
        claimed = self.released()
        job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
        self.assertEqual((job['discordPositionRestores'], job['lastDispatchedAt']), (3, self.db.now), 'the fourth costs the turn')
        self.assertEqual(self.db.state['phase2'][self.CURSOR], {'version': 1, 'lastClaimedAt': self.db.now})
        self.assertEqual(self.worker.lane_counts['positionsKept'], 3)

    def test_a_release_that_ends_in_a_hold_or_a_cancellation_changes_no_stamp(self):
        # The rate wait outlasts the approval: the post is held, and a held post has no place in a queue.
        claimed = self.worker.claim(discord_only=True)
        self.assertTrue(self.worker.release_discord_unsent(claimed, reason='rate_delayed', retry_after_seconds=10 ** 7,
                                                           rate_cause='rate_budget', rate_scope='application'))
        job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
        self.assertEqual(job['state'], 'held')
        self.assertEqual(job['lastDispatchedAt'], self.db.now)
        self.assertNotIn('discordPositionRestores', job)

    def test_only_the_lane_worker_keeps_the_position_the_minute_workers_release_is_the_frozen_one(self):
        claimed = self.base.claim(discord_only=True)
        self.assertNotIn('positionBefore', claimed)
        self.assertTrue(self.base.release_discord_unsent(claimed, reason='rate_delayed', retry_after_seconds=2.0,
                                                         rate_cause='rate_budget', rate_scope='application'))
        job = next(job for job in self.jobs() if job['id'] == claimed['job']['id'])
        self.assertEqual(job['lastDispatchedAt'], self.db.now)
        self.assertNotIn('discordPositionRestores', job)


if __name__ == '__main__':
    unittest.main()
