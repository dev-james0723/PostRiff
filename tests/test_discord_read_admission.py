"""G2E-A-05 / G2E-C-01: reads that reach Discord are throttled per member and per workspace BEFORE any provider request,
one is in flight per connection, and a connection's channel list / re-check answer is reused for a short while.

All Discord answers are synthetic and the throttle table is a faithful in-memory fixed window; no network, no database.
"""
import json
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import discord as _discord  # noqa: F401  (package import)
from postriff_phase2.discord import oauth as discord_oauth
from postriff_phase2.discord.oauth import DiscordConnections, READ_CACHE_SECONDS, READ_LIMIT_MEMBER, READ_LIMIT_WORKSPACE
from postriff_phase2.oauth import CredentialVault, OAuthService
from test_discord_oauth_lifecycle import LifecycleWire
from test_discord_publish_authorization import ACTOR, APP, BOT, FIRST, GUILD, NOW, USER, WORKSPACE
from postriff_phase2.social_connectors import DiscordProvider

OTHER_MEMBER = '20000000-0000-4000-8000-0000000000cc'
CONNECTION = 'install'
GENERATION = '30000000-0000-4000-8000-0000000000aa'


class Throttles:
    """The production semantics of hosted.throttle: a counter per hashed scope that raises 429 ABOVE the limit."""

    def __init__(self, log):
        self.counts, self.seen, self.log = {}, [], log

    def __call__(self, cur, scope, limit, window):
        self.log.append(('throttle', scope))
        self.seen.append((scope, limit, window))
        self.counts[scope] = self.counts.get(scope, 0) + 1
        if self.counts[scope] > limit:
            self.counts[scope] -= 1  # the failed attempt rolls back with its transaction
            raise AlphaError('Too many attempts. Wait a minute and try again.', 429)


class Rig:
    """A real OAuthService + DiscordConnections over a synthetic wire; only storage and the grant are doubles."""

    def __init__(self):
        self.log = []
        self.wire = LifecycleWire()
        base = self.wire.__call__
        self.wire.__class__ = type('Logged', (LifecycleWire,), {'__call__': lambda w, *a, **k: (self.log.append(('discord', a[0], a[1])), base(*a, **k))[1]})
        self.adapter = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=self.wire, production_reviewed=True)
        self.adapter.connections_v2_enabled = self.adapter.authorization_v2_enabled = True
        self.principal = ACTOR
        self.role = ('owner', True, True, True, True)
        self.state = initial_state(WORKSPACE)
        self.channel = {'id': CONNECTION, 'platform': 'Discord', 'revoked': False, 'discordDestinations': []}
        self.identity = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'userId': USER, 'status': 'linked',
                         'authorizationGeneration': GENERATION, 'discoverGuilds': True}
        self.state['phase2'] = {'channels': [self.channel], 'assets': [], 'reviews': [], 'jobs': [], 'discordIdentityLinks': [self.identity]}
        cur = self.cur = Mock(rowcount=1)

        def execute(sql, params=()):
            cur.last = sql
        cur.execute.side_effect = execute
        cur.fetchone.side_effect = lambda: (('discord',) if cur.last.startswith('SELECT provider FROM') else (GENERATION,))

        @contextmanager
        def transaction(token, workspace, **_):
            yield cur, [1, self.state, *self.role], self.principal
        repository = SimpleNamespace(transaction=transaction, assert_fresh=Mock(), connection_factory=Mock(),
                                     get=lambda workspace, token: {'revision': 1, 'state': self.state})
        self.service = OAuthService(repository, SimpleNamespace(), CredentialVault(CredentialVault.generate_key()), {'discord': self.adapter}, 'https://rafii.example.invalid', clock=lambda: NOW)
        self.grant = {'provider': 'discord', 'scopes': ['bot', 'identify'], 'authorizationGeneration': GENERATION,
                      'accessToken': json.dumps({'v': 2, 'kind': 'installation', 'applicationId': APP, 'botUserId': BOT, 'user': USER,
                                                 'guild': GUILD, 'channel': None, 'identityConnectionId': 'identity'})}
        self.grants = 0

        def grant(workspace, connection, *, cur=None):
            self.grants += 1
            self.log.append(('grant', connection))
            return self.grant
        self.service.discord_grant_for_worker = grant
        self.service.provider_for_grant = lambda grant: self.adapter
        self.throttles = Throttles(self.log)
        patcher = patch('postriff_phase2.hosted.throttle', self.throttles); patcher.start()
        self.cleanup = [patcher.stop]
        self.connections = self.service.discord_connections

    def requests(self):
        return [entry for entry in self.log if entry[0] == 'discord']

    def first_provider_request(self):
        return next(i for i, entry in enumerate(self.log) if entry[0] in ('discord', 'grant'))

    def last_throttle_before_provider(self):
        return max(i for i, entry in enumerate(self.log[:self.first_provider_request()]) if entry[0] == 'throttle')


class ReadsAreThrottledBeforeAnyProviderRequest(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(lambda: [stop() for stop in self.rig.cleanup])

    def scopes(self):
        return {scope for scope, _, _ in self.rig.throttles.seen}

    def test_the_channel_list_is_throttled_per_member_and_per_workspace_first(self):
        self.rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        self.assertEqual(self.rig.throttles.seen[:2], [(f'discord-read:{WORKSPACE}:{ACTOR}', *READ_LIMIT_MEMBER), (f'discord-read:{WORKSPACE}', *READ_LIMIT_WORKSPACE)])
        self.assertLess(self.rig.last_throttle_before_provider(), self.rig.first_provider_request())
        self.assertTrue(self.rig.requests())

    def test_choosing_a_destination_re_reads_discord_so_it_is_throttled_first_too(self):
        self.rig.service.repository.transaction  # the same transaction helper serves destinations and choose_destination
        self.rig.service._member_grant(WORKSPACE, 'session', CONNECTION, 'manage_connections')
        self.assertIn(f'discord-read:{WORKSPACE}:{ACTOR}', self.scopes())
        self.assertLess(self.rig.last_throttle_before_provider(), self.rig.first_provider_request())

    def test_the_server_list_is_throttled_before_the_identity_is_verified(self):
        self.rig.connections.local = lambda workspace, token: _local(self.rig)
        self.rig.connections._fresh_identity = Mock(side_effect=lambda *a: self.rig.log.append(('discord', 'GET', '/oauth2/@me')) or
                                                    {'connectionId': 'identity', 'bearer': 'b', 'userId': USER, 'scopes': ['identify', 'guilds'], 'authorizationGeneration': GENERATION})
        self.rig.connections.user_guilds = Mock(return_value=[{'id': GUILD, 'name': 'x'}])
        self.rig.connections.guilds(WORKSPACE, 'session', 'identity')
        self.assertIn(f'discord-read:{WORKSPACE}:{ACTOR}', self.scopes())
        self.assertLess(self.rig.last_throttle_before_provider(), self.rig.first_provider_request())

    def test_another_members_identity_spends_none_of_this_members_allowance(self):
        self.rig.identity['authorizedBy'] = OTHER_MEMBER
        self.rig.connections.local = lambda workspace, token: _local(self.rig)
        with self.assertRaises(AlphaError) as raised:
            self.rig.connections.guilds(WORKSPACE, 'session', 'identity')
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.rig.throttles.seen, [])
        self.assertEqual(self.rig.requests(), [])

    def test_a_throttled_caller_costs_discord_nothing_at_all(self):
        """P10 (poc/test_poc_a4_io_before_throttle): three rejected installation starts used to make six Discord GETs."""
        rig = self.rig
        rig.connections.local = lambda workspace, token: _local(rig)
        rig.connections.bind_identity = Mock(return_value=(('c', 'k', 'r', NOW + 3600, GENERATION, ['identify', 'guilds'], USER), {'user': USER, 'at': 'at'}))
        rig.wire.tokens['at'] = ['identify', 'guilds']

        def throttled(cur, scope, limit, window):
            rig.log.append(('throttle', scope))
            raise AlphaError('Too many attempts. Wait a minute and try again.', 429)
        with patch('postriff_phase2.hosted.throttle', throttled), patch('postriff_phase2.hosted.audit'):
            for _ in range(3):
                with self.assertRaises(AlphaError) as raised:
                    rig.connections.start(WORKSPACE, 'session-token', 'publish', {'discordPurpose': 'installation', 'identityConnectionId': 'identity', 'guildId': GUILD})
                self.assertEqual(raised.exception.status, 429)
        self.assertEqual(rig.requests(), [])
        self.assertEqual(rig.wire.lifecycle_calls, [])

    def test_a_workspace_that_hammers_the_list_is_cut_off_and_the_cache_keeps_discord_traffic_flat(self):
        """The deterministic form of the scope-C starvation proofs: one tenant, one connection, 200 requests in a minute."""
        rig = self.rig
        for _ in range(READ_LIMIT_MEMBER[0]):
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        one_fetch = len(rig.requests())
        self.assertGreater(one_fetch, 0)
        for _ in range(170):
            with self.assertRaises(AlphaError) as raised:
                rig.service.destinations(WORKSPACE, 'session', CONNECTION)
            self.assertEqual(raised.exception.status, 429)
        self.assertEqual(len(rig.requests()), one_fetch)  # 30 admitted calls, ONE set of Discord reads; the rest never got there
        self.assertEqual(rig.grants, 1)

    def test_a_second_member_has_their_own_allowance_until_the_workspace_one_is_spent(self):
        rig = self.rig
        for _ in range(READ_LIMIT_MEMBER[0]):
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        with self.assertRaises(AlphaError):
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        rig.principal = OTHER_MEMBER
        for _ in range(READ_LIMIT_MEMBER[0]):
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        with self.assertRaises(AlphaError):
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        for index in range(3):  # two more members reach the workspace ceiling (120) before their own (30)
            rig.principal = f'20000000-0000-4000-8000-0000000d{index:04d}'
            try:
                for _ in range(READ_LIMIT_MEMBER[0]):
                    rig.service.destinations(WORKSPACE, 'session', CONNECTION)
            except AlphaError as error:
                self.assertEqual(error.status, 429)
                self.assertGreaterEqual(rig.throttles.counts[f'discord-read:{WORKSPACE}'], READ_LIMIT_WORKSPACE[0])
                break
        else:
            self.fail('the workspace ceiling was never reached')

    def test_the_ui_never_trips_the_limits(self):
        """Opening the picker, a re-check and a refresh a few times a minute is far below either limit."""
        for _ in range(8):
            self.rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        self.assertLess(8, READ_LIMIT_MEMBER[0] // 3)

    def test_a_viewer_is_refused_before_the_throttle_is_touched(self):
        self.rig.role = ('viewer', False, False, False, False)
        with self.assertRaises(AlphaError) as raised:
            self.rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(self.rig.throttles.seen, [])
        self.assertEqual(self.rig.requests(), [])


def _local(rig):
    @contextmanager
    def local():
        yield rig.cur, rig.state, rig.principal
    return local()


class OneDiscordReadPerConnectionAndAShortCache(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(lambda: [stop() for stop in self.rig.cleanup])

    def test_concurrent_requests_for_one_connection_make_one_set_of_discord_reads(self):
        rig = self.rig
        gate, entered, results = threading.Event(), threading.Event(), []
        original = rig.adapter.destinations

        def slow(token, **kwargs):
            entered.set()
            gate.wait(5)
            return original(token, **kwargs)
        rig.adapter.destinations = slow
        threads = [threading.Thread(target=lambda: results.append(rig.service.destinations(WORKSPACE, 'session', CONNECTION))) for _ in range(5)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(5))
        gate.set()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len(results), 5)
        self.assertEqual(rig.grants, 1)  # one in flight; the other four were served from the leader's answer
        self.assertEqual(len([r for r in rig.requests() if r[2].endswith('/channels')]), 1)

    def test_the_answer_is_reused_for_the_cache_window_and_then_read_again(self):
        rig = self.rig
        clock = [1000.0]
        with patch.object(discord_oauth.time, 'monotonic', side_effect=lambda: clock[0]):
            first = rig.service.destinations(WORKSPACE, 'session', CONNECTION)
            clock[0] += READ_CACHE_SECONDS - 1
            again = rig.service.destinations(WORKSPACE, 'session', CONNECTION)
            self.assertEqual(rig.grants, 1)
            self.assertEqual(first, again)
            clock[0] += 2
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
            self.assertEqual(rig.grants, 2)

    def test_an_empty_list_is_only_remembered_briefly_so_a_fix_in_discord_shows_up(self):
        rig = self.rig
        rig.wire.allowed = set()  # no usable channel yet
        clock = [1000.0]
        with patch.object(discord_oauth.time, 'monotonic', side_effect=lambda: clock[0]):
            self.assertEqual(rig.service.destinations(WORKSPACE, 'session', CONNECTION)['destinations'], [])
            rig.wire.allowed = {FIRST}
            clock[0] += discord_oauth.READ_RETRY_SECONDS + 1  # well inside the normal window
            self.assertEqual([d['id'] for d in rig.service.destinations(WORKSPACE, 'session', CONNECTION)['destinations']], [FIRST])

    def test_the_cache_is_per_connection_and_per_consent_generation(self):
        rig = self.rig
        rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        rig.service.destinations(WORKSPACE, 'session', 'another-connection')
        self.assertEqual(rig.grants, 2)
        rig.cur.fetchone.side_effect = lambda: (('discord',) if rig.cur.last.startswith('SELECT provider FROM') else ('30000000-0000-4000-8000-0000000000bb',))
        rig.service.destinations(WORKSPACE, 'session', CONNECTION)  # a reconnect changed the generation: not served from the old answer
        self.assertEqual(rig.grants, 3)

    def test_an_error_is_never_cached(self):
        rig = self.rig
        calls = []

        def flaky(workspace, connection, *, cur=None):
            calls.append(1)
            if len(calls) == 1:
                raise AlphaError('Discord was disconnected.', 409)
            return rig.grant
        rig.service.discord_grant_for_worker = flaky
        with self.assertRaises(AlphaError):
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        self.assertEqual(len(calls), 2)

    def test_a_cached_answer_never_crosses_the_role_check(self):
        rig = self.rig
        rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        rig.role = ('viewer', False, False, False, False)
        with self.assertRaises(AlphaError) as raised:
            rig.service.destinations(WORKSPACE, 'session', CONNECTION)
        self.assertEqual(raised.exception.status, 403)

    def test_the_re_check_is_throttled_first_cached_when_healthy_and_serialised(self):
        rig = self.rig
        rig.cur.fetchone.side_effect = lambda: (('discord', 'provider-account', ['bot', 'identify'], 'ct', 'key') if rig.cur.last.startswith('SELECT provider,provider_account_id')
                                                else (GENERATION,))
        verified = Mock(return_value={'connectionId': CONNECTION, 'state': 'read_verified', 'ready': True, 'scopes': []})
        rig.connections.reverify_installation = verified
        with patch.object(OAuthService, '_assert_pinterest_context'):
            rig.service.verify(WORKSPACE, 'session', CONNECTION)
            rig.service.verify(WORKSPACE, 'session', CONNECTION)
            self.assertEqual(verified.call_count, 1)  # the second click is served from the first answer
            self.assertEqual(rig.throttles.counts[f'discord-read:{WORKSPACE}:{ACTOR}'], 2)  # ...but still counted
            verified.return_value = {'connectionId': CONNECTION, 'state': 'permission_missing', 'ready': False, 'scopes': []}
            clock = [5000.0]
            with patch.object(discord_oauth.time, 'monotonic', side_effect=lambda: clock[0]):
                rig.service.verify(WORKSPACE, 'session', 'second')
                clock[0] += discord_oauth.READ_RETRY_SECONDS + 1
                rig.service.verify(WORKSPACE, 'session', 'second')
            self.assertEqual(verified.call_count, 3)  # a problem is re-checked after seconds, not after the full window


if __name__ == '__main__':
    unittest.main()
