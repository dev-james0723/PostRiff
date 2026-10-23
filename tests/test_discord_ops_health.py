"""H-07 Discord operations health route and payload, offline: authority, answer shapes, privacy, failure behaviour.

No database, network or credential: the route is driven as WSGI, the database is an in-memory stand-in that answers
the payload's own statements. The real-PostgreSQL proof of the same payload is in test_discord_ops_drills_postgres.py.
"""
import hashlib
import importlib.util
import io
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_phase2.discord import lane, launch_gate, ops
from postriff_phase2.discord.rate_limits import SharedPostgresBudget, route_identity
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.social_connectors import DiscordProvider

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('discord_rate_policy', ROOT / 'scripts/discord_rate_policy.py')
POLICY_TOOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(POLICY_TOOL)
APP = '123456789012345678'
NOW = 1_800_000_000.0
SECRET = 'h' * 24
WORKSPACE = '3f6c8d2e-1b7a-4c5d-9e8f-0a1b2c3d4e5f'
LANE_ON = {'POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED': 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}


def call(app, path, authorization='', method='GET'):
    result = {}
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_AUTHORIZATION': authorization,
               'wsgi.input': io.BytesIO(), 'CONTENT_LENGTH': '0'}

    def response(status, headers):
        result['status'] = status
        result['headers'] = {key: value for key, value in headers if key != 'X-Request-ID'}
    result['body'] = b''.join(app(environ, response))
    return result


def provider(*, policy_at=NOW, rate_limits=True, reviewed=True):
    adapter = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot-token', 'https://rafii.example.invalid',
                              production_reviewed=reviewed)
    adapter.connections_v2_enabled = adapter.authorization_v2_enabled = True
    adapter.rate_v1_enabled = rate_limits
    adapter.rate_limiter = (SharedPostgresBudget(lambda: None, APP, policy=json.dumps(POLICY_TOOL.build(policy_at, days=10)))
                            if policy_at is not None else None)
    return adapter


class FakeDatabase:
    """Answers the payload's statements with synthetic aggregates, and records them."""

    def __init__(self, adapter, *, fail=(), raise_on_connect=False):
        self.adapter, self.fail, self.raise_on_connect = adapter, set(fail), raise_on_connect
        self.statements = []

    def __call__(self):
        if self.raise_on_connect:
            raise OSError('database unreachable')
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.statements.append(sql)
        self.result = None
        for name, marker in (('queue', 'pr_discord_worker_projection'), ('ledger', 'pr_discord_request_admissions'),
                             ('coordinator', 'pr_discord_rate_state'), ('servers', 'pr_encrypted_credentials'),
                             ('platform', 'FROM public.pr_operational_snapshots'), ('requests', 'FROM public.pr_request_metrics')):
            if marker in sql and name in self.fail:
                raise RuntimeError('synthetic failure')
        if sql.startswith('SELECT set_config'):
            self.result = [('2000ms', '500ms', NOW)]
        elif 'pr_discord_worker_projection' in sql:
            self.result = [(2, 1, 3, 420.5, NOW - 30)]
        elif 'pr_discord_request_admissions' in sql:
            self.result = [(120, NOW - 700, NOW - 2, 40, 33, 2, 1, 1, 2, 1, 0, 0, 0, 3, 0, 9, 60, 1, 80, 0, 0,
                            NOW - 3, NOW - 1)]
        elif 'WHERE scope_key = ANY' in sql:
            keys = sorted(ops.guard_keys(self.adapter))
            kinds = [ops.GUARDS[key[:3]] for key in keys]
            self.result = [(key, kind, False, 2000 if kind == 'invalid' else 25 if kind == 'policy' else None,
                            1500 if kind == 'invalid' else 20 if kind == 'policy' else None, NOW + 300, None, None,
                            NOW - 10, NOW + 86400 * 9) for key, kind in zip(keys, kinds)]
        elif 'pr_discord_rate_state' in sql:
            self.result = [('route', 0, 1, 3, 2, 0)]
        elif 'pr_encrypted_credentials' in sql:
            self.result = [(7, 2)]
        elif 'to_regclass' in sql:
            self.result = [(True,)]
        elif 'pr_operational_snapshots' in sql:
            self.result = [(NOW - 40, 'attention', {'publicationUncertain': 1, 'queueDelayed': 4, 'publicationFailed': 0,
                                                    'publicationHeld': 2, 'modelStuck': 0})]
        elif 'pr_request_metrics' in sql:
            self.result = [('GET /api/workspaces/:id/discord/identities/:id/guilds', 3),
                           ('GET /api/workspaces/:id/channels/:id/destinations', 5), ('GET /api/workspaces/:id', 7),
                           ('GET /api/me', 1)]

    def fetchone(self):
        return self.result[0]

    def fetchall(self):
        return list(self.result)


def worker_for(adapter, database):
    return SimpleNamespace(social=HostedSocial(None, {'discord': adapter}), connection_factory=database)


def leaves(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, path + (key,))
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item, path)
    else:
        yield path, value


class Authority(unittest.TestCase):
    def app(self):
        app = HostedApplication(cron_secret=SECRET)
        app._runtime = Mock(side_effect=AssertionError('runtime initialized'))
        return app

    def test_missing_wrong_or_user_tokens_never_start_the_runtime(self):
        for authorization in ('', 'Bearer dev:someone', 'Bearer prt_not-cron-authority', 'Bearer ' + SECRET[:-1],
                              SECRET, 'bearer ' + SECRET, 'Bearer ' + SECRET + ' ', 'Bearer é' + SECRET):
            with self.subTest(authorization=authorization):
                app = self.app()
                self.assertTrue(call(app, ops.ROUTE, authorization)['status'].startswith('401'))
                app._runtime.assert_not_called()

    def test_a_short_or_absent_cron_secret_refuses_even_a_matching_bearer(self):
        for secret in ('', 's' * 15):
            with self.subTest(length=len(secret)), patch.dict('os.environ', {'CRON_SECRET': secret}):
                app = HostedApplication()
                app._runtime = Mock(side_effect=AssertionError('runtime initialized'))
                self.assertTrue(call(app, ops.ROUTE, 'Bearer ' + secret)['status'].startswith('401'))
                app._runtime.assert_not_called()

    def test_other_methods_and_paths_under_the_prefix_are_not_routes(self):
        for path, method in ((ops.ROUTE, 'POST'), (ops.ROUTE, 'PUT'), (ops.ROUTE, 'DELETE'), (ops.ROUTE, 'HEAD'),
                             (ops.ROUTE + '/', 'GET'), (ops.PREFIX, 'GET'), (ops.PREFIX + 'healthz', 'GET'),
                             (ops.ROUTE + '/x', 'GET')):
            with self.subTest(path=path, method=method):
                app = self.app()
                self.assertTrue(call(app, path, 'Bearer ' + SECRET, method)['status'].startswith('404'))
                app._runtime.assert_not_called()

    def test_the_401_and_404_answers_are_the_shard_routes_own(self):
        for authorization, ours, shard in (('Bearer wrong', ops.ROUTE, lane.ROUTE + '0'),
                                           ('Bearer ' + SECRET, ops.ROUTE + '/x', lane.ROUTE + 'x'),
                                           ('', ops.PREFIX + 'other', lane.ROUTE + '99')):
            with self.subTest(ours=ours):
                mine, theirs = call(self.app(), ours, authorization), call(self.app(), shard, authorization)
                self.assertEqual((mine['status'], mine['headers'], mine['body']),
                                 (theirs['status'], theirs['headers'], theirs['body']))

    def test_the_route_reads_the_runtimes_worker_once_authorized(self):
        app = HostedApplication(service=object(), worker='the-worker', cron_secret=SECRET)
        with patch.object(ops, 'snapshot', return_value={'version': 1}) as snapshot:
            answered = call(app, ops.ROUTE, 'Bearer ' + SECRET)
        self.assertTrue(answered['status'].startswith('200'))
        self.assertEqual(json.loads(answered['body']), {'version': 1})
        self.assertEqual(snapshot.call_args.args, ('the-worker',))
        self.assertEqual(answered['headers']['Cache-Control'], 'no-store')

    def test_an_unconfigured_runtime_answers_503_after_authorization(self):
        app = HostedApplication(cron_secret=SECRET)
        with patch('postriff_phase2.hosted_app.runtime_from_environment', side_effect=ValueError('no database')):
            answered = call(app, ops.ROUTE, 'Bearer ' + SECRET)
        self.assertTrue(answered['status'].startswith('503'))
        self.assertNotIn(b'no database', answered['body'])


class Payload(unittest.TestCase):
    def snapshot(self, adapter=None, database=None, values=None):
        adapter = adapter or provider()
        database = database or FakeDatabase(adapter)
        environment = {'VERCEL_ENV': 'production', 'POSTRIFF_DISCORD_CONNECT_WORKSPACES': '*',
                       'POSTRIFF_DISCORD_GUILD_CAP': '10000', 'VERCEL_GIT_COMMIT_SHA': 'a' * 40,
                       'VERCEL_DEPLOYMENT_ID': 'dpl_SyntheticDeployment01', **LANE_ON,
                       **(values if values is not None else {})}
        return ops.snapshot(worker_for(adapter, database), environment, clock=lambda: NOW), database

    def test_the_payload_carries_counts_ages_booleans_and_codes_only(self):
        payload, _ = self.snapshot()
        allowed_text = {'rafii.discord.ops.health', 'health_route', 'observed', 'open', 'closed', 'list', 'instance',
                        'production', 'attention', 'ok', 'no_coordinator', 'w02-health', 'not_installed'}
        for path, value in leaves(payload):
            with self.subTest(path='.'.join(map(str, path))):
                if isinstance(value, str):
                    self.assertTrue(value in allowed_text or path[-1] in ('sourceRevision', 'deploymentId', 'revision'),
                                    value)
                else:
                    self.assertIsInstance(value, (int, float, bool, type(None)))
        text = json.dumps(payload)
        self.assertNotIn(WORKSPACE, text)
        self.assertNotIn(APP, text)
        self.assertIsNone(re.search(r'[0-9a-f]{64}', text), 'no scope key or digest')
        self.assertIsNone(re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-', text), 'no uuid')
        self.assertNotIn('synthetic-bot-token', text)

    def test_the_effective_configuration_is_read_back(self):
        payload, _ = self.snapshot()
        config = payload['config']
        self.assertEqual(config['gate'], {'mode': 'open', 'workspaces': 0, 'misconfigured': False})
        self.assertEqual(config['cap'], {'value': 10000, 'unlimited': False, 'misconfigured': False})
        self.assertEqual(config['servers'], {'status': 'observed', 'counted': 7, 'inFlight': 2, 'used': 9,
                                             'ratio': 0.0009})
        self.assertTrue(config['reviewed'] and config['rateLimitsV1'] and config['laneFlag'] and config['workerV1'])
        self.assertTrue(config['policy']['valid'])
        self.assertAlmostEqual(config['policy']['daysLeft'], 10.0, delta=0.01)
        self.assertEqual(payload['build'], {'sourceRevision': 'a' * 40, 'deploymentId': 'dpl_SyntheticDeployment01',
                                            'environment': 'production'})
        listed, _ = self.snapshot(values={'POSTRIFF_DISCORD_CONNECT_WORKSPACES': WORKSPACE + ',' + WORKSPACE.replace('3f', '4f'),
                                          'POSTRIFF_DISCORD_GUILD_CAP': None})
        self.assertEqual(listed['config']['gate'], {'mode': 'list', 'workspaces': 2, 'misconfigured': False})
        self.assertNotIn(WORKSPACE, json.dumps(listed))
        with patch.dict('os.environ', {}, clear=True):
            omitted = ops.config_section(provider(), NOW, {'VERCEL_ENV': 'production'})
        self.assertEqual((omitted['gate']['mode'], omitted['cap']['value']), ('closed', launch_gate.DEFAULT_PRODUCTION_CAP))

    def test_the_lane_section_is_the_w02_health_status(self):
        payload, _ = self.snapshot()
        expected = lane.status(worker_for(provider(), None).social, NOW, LANE_ON)
        self.assertEqual({key: payload['lane'][key] for key in expected}, expected)
        self.assertEqual(payload['lane']['staticBlocker'], None)
        off, _ = self.snapshot(adapter=provider(rate_limits=False))
        self.assertEqual((off['lane']['blocker'], off['lane']['staticBlocker']), ('coordinator_unavailable',
                                                                                  'coordinator_unavailable'))

    def test_queue_progress_deliveries_and_coordinator_sections(self):
        payload, database = self.snapshot()
        self.assertEqual(payload['queue'], {'status': 'observed', 'dueWorkspaces': 2, 'dueWithin5Min': 1,
                                            'pendingWorkspaces': 3, 'oldestDueLagSeconds': 420.5})
        self.assertEqual(payload['progress']['lastClaimAgeSeconds'], 30.0)
        self.assertEqual(payload['progress']['lastAdmissionAgeSeconds'], 2.0)
        self.assertEqual(payload['progress']['lastReadbackAgeSeconds'], 1.0)
        deliveries = payload['deliveries']
        self.assertEqual((deliveries['creates'], deliveries['accepted'], deliveries['rejectedCustomer'],
                          deliveries['rejectedSystem'], deliveries['uncertain']), (40, 33, 2, 1, 2))
        self.assertTrue(deliveries['windowCovered'])
        guards = payload['coordinator']['guards']
        self.assertEqual(sorted(guards), ['credential', 'global', 'invalid', 'policy'])
        self.assertEqual(guards['invalid']['remainingRatio'], 0.75)
        self.assertEqual(payload['coordinator']['kinds'], {'route': {'holds': 0, 'blocks': 1, 'circuits': 3,
                                                                     'persistentCircuits': 2, 'openOver5Min': 0}})
        self.assertEqual(payload['coordinator']['traffic']['admissions60s'], 80)
        self.assertEqual(payload['security']['responses4xx'], {'status': 'observed', 'windowSeconds': 900,
                                                               'workspace': 7, 'connections': 5, 'discord': 3, 'other': 1})
        self.assertEqual(payload['platform']['queueDelayed'], 4)
        self.assertNotIn('modelStuck', payload['platform'])
        self.assertEqual(payload['errors'], [])
        self.assertEqual(database.statements[0], 'SET TRANSACTION READ ONLY')
        self.assertFalse([s for s in database.statements if re.search(r'\b(INSERT|UPDATE|DELETE|TRUNCATE)\b', s)])
        self.assertFalse([s for s in database.statements if 'pr_workspaces' in s], 'no customer state is read')

    def test_a_failing_section_answers_unavailable_alone(self):
        adapter = provider()
        payload, _ = self.snapshot(adapter, FakeDatabase(adapter, fail={'ledger'}))
        self.assertEqual(payload['deliveries'], {'status': 'unavailable', 'error': 'RuntimeError'})
        self.assertEqual(payload['coordinator']['traffic'], {'status': 'unavailable'})
        self.assertEqual(payload['queue']['status'], 'observed')
        self.assertEqual(payload['progress']['status'], 'partial')
        self.assertEqual(payload['errors'], [{'section': 'ledger', 'error': 'RuntimeError'}])

    def test_an_unreachable_database_still_answers_the_process_view(self):
        adapter = provider()
        payload, _ = self.snapshot(adapter, FakeDatabase(adapter, raise_on_connect=True))
        self.assertIsNone(payload['observedAt'])
        for name in ('queue', 'deliveries', 'platform'):
            self.assertEqual(payload[name]['status'], 'unavailable')
        self.assertEqual(payload['progress']['status'], 'unavailable')
        self.assertEqual(payload['errors'], [{'section': 'database', 'error': 'OSError'}])
        self.assertEqual(payload['config']['gate']['mode'], 'open')
        self.assertTrue(payload['lane']['enabled'])

    def test_without_a_coordinator_the_guard_rows_are_not_read(self):
        adapter = provider(policy_at=None)
        payload, database = self.snapshot(adapter)
        self.assertEqual(payload['coordinator']['status'], 'no_coordinator')
        self.assertFalse([s for s in database.statements if 'scope_key = ANY' in s])
        self.assertFalse(payload['config']['policy']['present'])


class Constants(unittest.TestCase):
    def test_the_readback_route_key_is_the_coordinators_own(self):
        template, _major = route_identity('GET', '/channels/1234567/messages/7654321')
        self.assertEqual(ops.READBACK_ROUTE_KEY, hashlib.sha256(template.encode()).hexdigest())

    def test_servers_used_is_the_connect_gates_own_count(self):
        self.assertIn(launch_gate._IN_FLIGHT, ops._SERVERS)
        self.assertIn("provider='discord' AND 'bot' = ANY(scopes)", ops._SERVERS)

    def test_guard_keys_are_the_four_application_wide_rows_the_lane_reads(self):
        keys = ops.guard_keys(provider())
        self.assertEqual(sorted(keys.values()), ['credential', 'global', 'invalid', 'policy'])
        self.assertEqual(sorted(key[:3] for key in keys), sorted(lane._GUARDS))

    def test_route_families_of_masked_request_patterns(self):
        for pattern, family in (('GET /api/workspaces/:id/discord/identities/:id/guilds', 'discord'),
                                ('POST /api/workspaces/:id/channels/discord/oauth/start', 'discord'),
                                ('GET /api/workspaces/:id/channels/:id/destinations', 'connections'),
                                ('GET /api/workspaces/:id', 'workspace'), ('GET /api/me', 'other'),
                                (None, 'other')):
            self.assertEqual(ops.family(pattern), family)


if __name__ == '__main__':
    unittest.main()
