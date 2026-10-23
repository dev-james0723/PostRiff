"""G2E-A-02 / A-03 / A-06: a removed, downgraded or departed authorizer's personal Discord credential is neither used,
rotated nor kept (synthetic state, synthetic wire, no network).

The SQL conditions of the real guard (active membership, undeleted profile, manage_connections) are proven on a real
PostgreSQL by tests/phase2/postgres_discord_custody.py; the tests here pin the order of effects and the wiring.
"""
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord.oauth import DiscordConnections
from postriff_phase2.hosted import HostedWorkspaceService
from test_discord_hybrid_review_regressions import GENERATION
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import ACTOR, APP, BOT, GUILD, NOW, USER, WORKSPACE

OTHER = '20000000-0000-4000-8000-0000000000bb'


class World:
    """One installation bound to one identity; `membership` is what the authorizer's membership query returns."""

    def __init__(self, membership, *, expired=True, authorized_by=ACTOR):
        self.s, self.wire = service()
        self.s.oauth.WORKER_REVERIFIED = 'channel.reverified_by_worker'
        self.identity = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': authorized_by, 'userId': USER,
                         'status': 'linked', 'authorizationGeneration': GENERATION}
        self.channel = {'id': 'install', 'platform': 'Discord', 'revoked': False, 'discordConnectionKind': 'installation',
                        'providerAccountId': GUILD, 'discordAuthorizationGeneration': 'G-INSTALL', 'scopes': ['bot', 'identify'],
                        'discordIdentityConnectionId': 'identity', 'enabledPermissionGroups': ['identity', 'publish'],
                        'discordDestinations': [], 'capabilityVerified': True, 'identityVerified': True}
        self.state = initial_state(WORKSPACE)
        self.state['phase2'] = {'channels': [self.channel], 'assets': [], 'reviews': [], 'jobs': [], 'discordIdentityLinks': [self.identity]}
        self.membership = membership
        self.cur = Mock(rowcount=1)
        self.executed = []

        def execute(sql, params=()):
            self.executed.append((sql, params))
            self.cur.last_sql = sql
        self.cur.execute.side_effect = execute
        self.cur.fetchone.side_effect = lambda: self.membership if self.cur.last_sql.startswith('SELECT m.role') else (self.state,)

        @contextmanager
        def local(*_a, **_k):
            yield self.cur, self.state, None
        self.s.local = local
        envelope = {'v': 2, 'kind': 'installation', 'applicationId': APP, 'botUserId': BOT, 'user': USER, 'guild': GUILD,
                    'channel': None, 'identityConnectionId': 'identity', 'identityGeneration': GENERATION,
                    'authorization': {'bearerScopes': ['identify'], 'installationScopes': ['bot']}}
        row = ('c', 'k', None, None, 'G-INSTALL', ['bot', 'identify'], GUILD)
        self.s.read_credential = Mock(return_value=(row, envelope))
        refresh_ct, key = self.s.oauth.vault.encrypt('synthetic-refresh-' + GENERATION)
        self.s.bind_identity = Mock(return_value=(('access-ct', key, refresh_ct, NOW - 10 if expired else NOW + 3600, GENERATION,
                                                   ['identify', 'guilds'], USER), {'user': USER, 'at': 'old-access'}))
        self.s.save_state = Mock()
        self.wire.tokens['old-access'] = ['identify', 'guilds']

    def reverify(self, **kwargs):
        with patch('postriff_phase2.hosted.audit') as audit:
            self.audit = audit
            return self.s.reverify_installation(WORKSPACE, 'install', **kwargs)

    def discord_requests(self):
        return self.wire.lifecycle_calls


class ReverifyChecksTheAuthorizerBeforeAnyDiscordRequest(unittest.TestCase):
    """P1/P2/P11. reverify_installation (worker and composer paths) refreshed and rotated the removed member's token,
    then read Discord with the bot, and only the commit phase refused."""

    def test_a_removed_authorizer_costs_not_one_discord_request_and_the_token_is_not_rotated(self):
        for label, membership in (('removed', None), ('viewer', ('viewer', False)), ('editor without the flag', ('editor', False))):
            world = World(membership)
            with patch.object(DiscordConnections, '_fresh_identity', wraps=world.s._fresh_identity) as fresh:
                result = world.reverify()
            self.assertEqual(result['state'], 'reauthorization_required', label)
            self.assertFalse(result['ready'], label)
            fresh.assert_not_called()
            self.assertEqual(world.discord_requests(), [], label)  # no refresh POST, no @me, no bot read
            self.assertEqual(world.wire.refresh_count, 0, label)

    def test_the_control_an_active_authorizer_does_refresh_and_read(self):
        world = World(('admin', True))
        result = world.reverify()
        self.assertIn(('POST', '/oauth2/token'), world.discord_requests())
        self.assertIn(('GET', '/guilds/' + GUILD + '/channels'), world.discord_requests())
        self.assertNotEqual(result['state'], 'reauthorization_required')

    def test_the_explicit_member_verification_is_covered_too(self):
        world = World(None)
        result = world.reverify(token='synthetic-session')
        self.assertEqual(result['state'], 'reauthorization_required')
        self.assertEqual(world.discord_requests(), [])

    def test_the_card_is_flipped_once_and_later_passes_change_nothing(self):
        world = World(None)
        first = world.reverify()
        self.assertEqual(first['state'], 'reauthorization_required')
        self.assertFalse(world.channel['capabilityVerified'])
        self.assertFalse(world.channel['identityVerified'])
        self.assertTrue(world.channel['discordAuthorizerGone'])
        self.assertFalse(world.channel['revoked'])  # not destroyed: another manager can reconnect the card
        world.s.save_state.assert_called_once()
        world.audit.assert_called_once()
        generation = world.channel['discordVerificationGeneration']
        for _ in range(3):
            again = world.reverify()
            self.assertEqual(again['state'], 'reauthorization_required')
            world.audit.assert_not_called()
        world.s.save_state.assert_called_once()  # still only the first flip
        self.assertEqual(world.channel['discordVerificationGeneration'], generation)
        self.assertEqual(world.discord_requests(), [])

    def test_an_authorizer_reinstated_between_the_check_and_the_flip_is_not_flipped(self):
        world = World(None)
        original = world.s._authorizer_gone

        def reinstated(*args, **kwargs):
            world.membership = ('admin', True)
            return original(*args, **kwargs)
        world.s._authorizer_gone = reinstated
        result = world.reverify()
        self.assertEqual(result['state'], 'verification_unavailable')
        self.assertTrue(world.channel['capabilityVerified'])
        world.s.save_state.assert_not_called()

    def test_the_guard_sql_keeps_its_membership_conditions(self):
        """A textual pin on the statement; the behaviour is proven on PostgreSQL in postgres_discord_custody.py."""
        world = World(('admin', True))
        world.reverify()
        sql = next(sql for sql, _ in world.executed if sql.startswith('SELECT m.role,m.can_manage_connections'))
        for condition in ("m.status='active'", 'p.deleted_at IS NULL', 'm.user_id=%s', 'm.workspace_id=%s'):
            self.assertIn(condition, sql)


def custody_world(*, authorizer=OTHER, extra_authorizer=ACTOR):
    """Two members each with a personal identity (one with an installation), plus one independent webhook."""
    s, wire = service()
    state = initial_state(WORKSPACE)
    gone = {'id': 'identity-gone', 'workspaceId': WORKSPACE, 'authorizedBy': authorizer, 'userId': USER, 'status': 'linked', 'authorizationGeneration': 'G-gone'}
    stuck = {'id': 'identity-stuck', 'workspaceId': WORKSPACE, 'authorizedBy': authorizer, 'userId': USER, 'status': 'reconnect_required', 'authorizationGeneration': 'G-stuck'}
    other = {'id': 'identity-other', 'workspaceId': WORKSPACE, 'authorizedBy': extra_authorizer, 'userId': USER, 'status': 'linked', 'authorizationGeneration': 'G-other'}
    install = {'id': 'install-gone', 'platform': 'Discord', 'revoked': False, 'capabilityVerified': True, 'discordIdentityConnectionId': 'identity-gone',
               'discordDestinations': [{'status': 'authorized'}], 'defaultDestinationId': 'd'}
    kept = {'id': 'install-other', 'platform': 'Discord', 'revoked': False, 'capabilityVerified': True, 'discordIdentityConnectionId': 'identity-other',
            'discordDestinations': [{'status': 'authorized'}]}
    hook = {'id': 'discord-webhook-gone', 'platform': 'Discord', 'revoked': False, 'capabilityVerified': True, 'discordConnectionKind': 'webhook',
            'discordAuthorizedBy': authorizer, 'discordDestinations': [{'status': 'authorized'}]}
    state['phase2'] = {'channels': [install, kept, hook], 'assets': [], 'reviews': [], 'jobs': [], 'discordIdentityLinks': [gone, stuck, other]}
    cur = Mock(rowcount=1)
    return s, cur, state, SimpleNamespace(gone=gone, stuck=stuck, other=other, install=install, kept=kept, hook=hook)


def zeroed(cur):
    """connection ids whose credential row was revoked and emptied."""
    return [c.args[1][2] for c in cur.execute.call_args_list
            if c.args[0].startswith("UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext=''")]


class AMemberWhoIsGoneLeavesNoLiveCredentialBehind(unittest.TestCase):
    """G2E-A-03 (P3). remove_member and leave_workspace never touched discordIdentityLinks or pr_encrypted_credentials: the
    ex-member's personal tokens stayed live, nobody could delete them, and the worker kept rotating them."""

    def test_every_identity_the_member_authorized_is_disconnected_and_zeroed_and_nothing_else_is(self):
        s, cur, state, w = custody_world()
        self.assertTrue(s.disconnect_member(cur, WORKSPACE, state, OTHER))
        for record in (w.gone, w.stuck):
            self.assertEqual(record['status'], 'disconnected')
        self.assertNotIn(record['authorizationGeneration'], ('G-gone', 'G-stuck'))
        self.assertTrue(w.install['revoked'] and not w.install['capabilityVerified'])
        self.assertEqual([d['status'] for d in w.install['discordDestinations']], ['revoked'])
        self.assertTrue(w.hook['revoked'])
        self.assertEqual(sorted(zeroed(cur)), sorted(['identity-gone', 'identity-stuck', 'install-gone', 'discord-webhook-gone']))
        # another member's identity and installation are untouched
        self.assertEqual(w.other['status'], 'linked')
        self.assertFalse(w.kept['revoked'])
        self.assertNotIn('identity-other', zeroed(cur)); self.assertNotIn('install-other', zeroed(cur))
        # idempotent
        before = cur.execute.call_count
        self.assertFalse(s.disconnect_member(cur, WORKSPACE, state, OTHER))
        self.assertEqual(cur.execute.call_count, before)

    def service_double(self, state, role='owner'):
        s, cur, _, world = custody_world()
        s.save_state = Mock()
        discord = s
        service = HostedWorkspaceService.__new__(HostedWorkspaceService)
        row = [1, state, role, True, True, True, True]
        cur.fetchone.return_value = ('admin',)

        @contextmanager
        def transaction(token, workspace, **_):
            yield cur, row, ACTOR
        service.repository = SimpleNamespace(transaction=transaction, assert_fresh=Mock())
        service.oauth = SimpleNamespace(discord_connections=discord)
        service.clock = lambda: NOW
        return service, discord, cur

    def run_membership_change(self, call, *, role='owner'):
        s, cur, state, world = custody_world()
        service, discord, cur = self.service_double(state, role)
        patches = [patch('postriff_phase2.agent_runtime_v2.agent_permissions.on_membership_ended'),
                   patch('postriff_phase2.agent_runtime_v2.authz.mode_for', return_value='off'),
                   patch('postriff_phase2.agent_runtime_v2.authz.runtime_config_for', return_value=None)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        call(service)
        return discord, cur, state, world

    def test_removing_a_member_disconnects_their_identity_in_the_same_transaction(self):
        s, cur, state, world = custody_world()
        service, discord, cur = self.service_double(state)
        with patch('postriff_phase2.agent_runtime_v2.agent_permissions.on_membership_ended'), \
                patch('postriff_phase2.agent_runtime_v2.authz.mode_for', return_value='off'), \
                patch('postriff_phase2.agent_runtime_v2.authz.runtime_config_for', return_value=None):
            service.remove_member(WORKSPACE, 'session', OTHER)
        self.assertIn('identity-gone', zeroed(cur))
        discord.save_state.assert_called_once()
        saved = discord.save_state.call_args.args[2]  # the transaction saves the state it changed
        self.assertEqual([x['status'] for x in saved['phase2']['discordIdentityLinks']], ['disconnected', 'disconnected', 'linked'])

    def test_leaving_disconnects_the_leavers_identity(self):
        s, cur, state, world = custody_world(authorizer=ACTOR, extra_authorizer=OTHER)
        service, discord, cur = self.service_double(state, role='admin')
        with patch('postriff_phase2.agent_runtime_v2.agent_permissions.on_membership_ended'), \
                patch('postriff_phase2.agent_runtime_v2.authz.mode_for', return_value='off'), \
                patch('postriff_phase2.agent_runtime_v2.authz.runtime_config_for', return_value=None):
            service.leave_workspace(WORKSPACE, 'session')
        self.assertIn('identity-gone', zeroed(cur))
        saved = discord.save_state.call_args.args[2]
        self.assertEqual([x['status'] for x in saved['phase2']['discordIdentityLinks']], ['disconnected', 'disconnected', 'linked'])

    def test_dropping_below_manage_connections_disconnects_but_keeping_it_does_not(self):
        for role, flags, dropped in (('viewer', {}, True), ('editor', {}, True), ('approver', {}, True),
                                     ('editor', {'can_manage_connections': True}, False), ('admin', {}, False)):
            s, cur, state, world = custody_world()
            service, discord, cur = self.service_double(state)
            with patch('postriff_phase2.agent_runtime_v2.agent_permissions.on_membership_ended'):
                service.update_member(WORKSPACE, 'session', OTHER, role, flags)
            self.assertEqual('identity-gone' in zeroed(cur), dropped, (role, flags))
            self.assertEqual(discord.save_state.called, dropped, (role, flags))

    def test_a_workspace_without_discord_state_does_nothing_extra(self):
        s, cur, state, world = custody_world()
        state['phase2'] = {'channels': [], 'discordIdentityLinks': []}
        service, discord, cur = self.service_double(state)
        before = None
        with patch('postriff_phase2.agent_runtime_v2.agent_permissions.on_membership_ended'), \
                patch('postriff_phase2.agent_runtime_v2.authz.mode_for', return_value='off'), \
                patch('postriff_phase2.agent_runtime_v2.authz.runtime_config_for', return_value=None):
            service.remove_member(WORKSPACE, 'session', OTHER)
        discord.save_state.assert_not_called()
        self.assertEqual(zeroed(cur), [])


class ManagersMayRemoveAnOrphanedIdentityButNotAnActiveMembersOne(unittest.TestCase):
    """G2E-A-03: records created before this fix (or by any path that bypasses it) must not stay undeletable. The
    authorizedBy == actor filter of identity_record stays the only thing that protects an active member's identity."""

    def disconnect(self, authorizer_is_active):
        s, cur, state, world = custody_world()
        s.save_state = Mock()
        s.oauth.repository = SimpleNamespace(assert_fresh=Mock())
        # the membership query answers for the AUTHORIZER, not for the caller
        cur.fetchone.return_value = ('admin', True) if authorizer_is_active else None

        @contextmanager
        def local(*_):
            yield cur, state, ACTOR
        s.local = local
        with patch('postriff_phase2.hosted.audit') as audit:
            return s, cur, world, audit, (lambda: s.disconnect_identity(WORKSPACE, 'session', 'identity-gone'))

    def test_a_manager_can_remove_the_identity_of_someone_who_is_no_longer_an_active_manager(self):
        s, cur, world, audit, call = self.disconnect(authorizer_is_active=False)
        with patch('postriff_phase2.hosted.audit') as audit:
            self.assertTrue(call()['disconnected'])
        self.assertEqual(world.gone['status'], 'disconnected')
        self.assertIn('identity-gone', zeroed(cur)); self.assertIn('install-gone', zeroed(cur))
        self.assertEqual(audit.call_args.args[3:], ('discord.identity_disconnected', 'identity-gone', {'reason': 'authorizer_gone'}))

    def test_a_manager_still_cannot_touch_an_active_members_identity(self):
        s, cur, world, audit, call = self.disconnect(authorizer_is_active=True)
        with self.assertRaises(AlphaError) as raised:
            call()
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(world.gone['status'], 'linked')
        self.assertEqual(zeroed(cur), [])

    def test_an_identity_that_does_not_exist_in_this_workspace_is_still_a_404(self):
        s, cur, world, audit, call = self.disconnect(authorizer_is_active=False)
        with self.assertRaises(AlphaError) as raised:
            s.disconnect_identity(WORKSPACE, 'session', 'no-such-identity')
        self.assertEqual(raised.exception.status, 404)

    def test_the_owner_disconnecting_their_own_identity_is_unchanged(self):
        s, cur, state, world = custody_world(authorizer=ACTOR)
        s.save_state = Mock(); s.oauth.repository = SimpleNamespace(assert_fresh=Mock())

        @contextmanager
        def local(*_):
            yield cur, state, ACTOR
        s.local = local
        with patch('postriff_phase2.hosted.audit') as audit:
            s.disconnect_identity(WORKSPACE, 'session', 'identity-gone')
        self.assertEqual(world.gone['status'], 'disconnected')
        self.assertEqual(audit.call_args.args[3:5], ('discord.identity_disconnected', 'identity-gone'))


if __name__ == '__main__':
    unittest.main()
