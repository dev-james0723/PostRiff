"""G2E-A-06 / G2E-C-08: guards of the identity, consent and custody code that no earlier test would notice losing.

Each class names the guard it pins and the mutation that used to survive: delete the guard and the test fails. (The SQL
conditions of the authorizer guard are pinned on a real PostgreSQL in tests/phase2/postgres_discord_custody.py.)
"""
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord.oauth import identity_record
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_hybrid_review_regressions import GENERATION
from test_discord_oauth_lifecycle import SECOND_GUILD, installation_callback, service
from test_discord_publish_authorization import ACTOR, APP, GUILD, NOW, USER, WORKSPACE

OTHER = '20000000-0000-4000-8000-0000000000bb'


def with_roles(role, *flags):
    """DiscordConnections whose repository answers with a membership of `role` (+ publish, reply, moderate, manage)."""
    s, wire = service()
    cur, state = Mock(), initial_state(WORKSPACE)
    state['phase2'] = {'channels': [], 'discordIdentityLinks': []}

    @contextmanager
    def transaction(token, workspace):
        yield cur, [1, state, role, *flags], ACTOR
    s.oauth.repository = SimpleNamespace(transaction=transaction, assert_fresh=Mock(), connection_factory=Mock())
    return s, wire, cur


class ManageConnectionsGuardsEveryDiscordEntryPoint(unittest.TestCase):
    """DiscordConnections.local requires manage_connections. Without it a viewer or an approver could START an identity link
    (the only guard on that route; the guilds and disconnect routes have a second one)."""
    ALLOWED = [('owner', False, False, False, False), ('admin', False, False, False, False),
               ('editor', False, False, False, True)]
    REFUSED = [('viewer', True, True, True, True), ('approver', True, False, False, False), ('editor', True, True, True, False),
               ('editor', False, False, False, False)]

    def test_roles_that_may_manage_connections(self):
        for row in self.ALLOWED:
            s, _, _ = with_roles(*row)
            with s.local(WORKSPACE, 'session') as (_, _, actor):
                self.assertEqual(actor, ACTOR, row)
        for row in self.REFUSED:
            s, _, _ = with_roles(*row)
            with self.assertRaises(AlphaError) as raised:
                with s.local(WORKSPACE, 'session'):
                    pass
            self.assertEqual(raised.exception.status, 403, row)

    def test_a_viewer_or_approver_cannot_start_an_identity_link_or_an_installation(self):
        for row in self.REFUSED:
            s, wire, cur = with_roles(*row)
            for capability, inputs in (('identity', {'discordPurpose': 'identity'}),
                                       ('publish', {'discordPurpose': 'installation', 'identityConnectionId': 'identity', 'guildId': GUILD})):
                with self.assertRaises(AlphaError) as raised:
                    s.start(WORKSPACE, 'session', capability, inputs)
                self.assertEqual(raised.exception.status, 403, (row, capability))
            self.assertEqual(wire.lifecycle_calls, [])
            self.assertFalse(cur.execute.called, row)  # no transaction row, no throttle, no cap slot

    def test_the_other_public_entry_points_refuse_them_too(self):
        s, wire, cur = with_roles('viewer', True, True, True, True)
        for call in (lambda: s.guilds(WORKSPACE, 'session', 'identity'), lambda: s.disconnect_identity(WORKSPACE, 'session', 'identity'),
                     lambda: s.complete(WORKSPACE, 'session', 's' * 32, 'code'), lambda: s.reverify_installation(WORKSPACE, 'c', token='session')):
            with self.assertRaises(AlphaError) as raised:
                call()
            self.assertEqual(raised.exception.status, 403)
        self.assertEqual(wire.lifecycle_calls, [])


class AnIdentityBelongsToItsAuthorizer(unittest.TestCase):
    """identity_record's authorizedBy == actor filter: an admin could otherwise list guilds with, and disconnect, the owner's
    personal identity (DO18 survived every earlier test)."""

    def state(self):
        state = initial_state(WORKSPACE)
        state['phase2'] = {'discordIdentityLinks': [
            {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'status': 'linked'},
            {'id': 'foreign', 'workspaceId': '10000000-0000-4000-8000-0000000000ff', 'authorizedBy': ACTOR, 'status': 'linked'}]}
        return state

    def test_the_filter(self):
        state = self.state()
        self.assertEqual(identity_record(state, 'identity', ACTOR)['id'], 'identity')
        self.assertEqual(identity_record(state, 'identity')['id'], 'identity')  # the internal worker names no actor
        with self.assertRaises(AlphaError) as raised:
            identity_record(state, 'identity', OTHER)
        self.assertEqual(raised.exception.status, 404)
        with self.assertRaises(AlphaError):
            identity_record(state, 'foreign', ACTOR)  # another workspace's record is never visible here

    def test_another_member_cannot_list_guilds_with_or_start_an_installation_through_it(self):
        s, wire, cur = with_roles('admin', True, True, True, True)
        s.local = lambda workspace, token: _local(cur, self.state(), OTHER)
        with self.assertRaises(AlphaError) as raised:
            s.guilds(WORKSPACE, 'session', 'identity')
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(wire.lifecycle_calls, [])


def _local(cur, state, actor):
    @contextmanager
    def local():
        yield cur, state, actor
    return local()


class AReconnectCannotSmuggleAnotherServerPastTheCap(unittest.TestCase):
    """P5. start() lets a reconnect (connectionId) skip the cap slot. Only the check that the card's server IS the requested
    server stops 'any card id + any guild id' from being a free slot (DO17: proven on real PostgreSQL to bypass the cap)."""

    def world(self):
        s, wire = service()
        state = initial_state(WORKSPACE)
        identity = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'userId': USER, 'status': 'linked',
                    'authorizationGeneration': GENERATION, 'discoverGuilds': True}
        card = {'id': 'card', 'platform': 'Discord', 'providerAccountId': GUILD, 'discordConnectionKind': 'installation',
                'discordIdentityConnectionId': 'identity', 'discordAuthorizationGeneration': 'G-INSTALL'}
        state['phase2'] = {'channels': [card], 'discordIdentityLinks': [identity]}
        cur = Mock()
        cur.fetchone.return_value = ('transaction-id',)
        s.local = lambda workspace, token: _local(cur, state, ACTOR)
        s.bind_identity = Mock(return_value=(('c', 'k', 'r', NOW + 3600, GENERATION, ['identify', 'guilds'], USER), {'user': USER, 'at': 'a'}))
        s._fresh_identity = Mock(return_value={'connectionId': 'identity', 'authorizationGeneration': GENERATION, 'userId': USER,
                                               'bearer': 'b', 'scopes': ['identify', 'guilds']})
        s.user_guilds = Mock(return_value=[{'id': GUILD, 'name': 'one'}, {'id': SECOND_GUILD, 'name': 'two'}])
        return s

    def start(self, s, guild):
        with patch('postriff_phase2.hosted.throttle'), patch('postriff_phase2.hosted.audit'), \
                patch('postriff_phase2.discord.oauth.launch_gate.reserve_capacity') as reserve:
            try:
                s.start(WORKSPACE, 'session', 'publish', {'discordPurpose': 'installation', 'identityConnectionId': 'identity',
                                                           'guildId': guild, 'connectionId': 'card'})
                outcome = 'started'
            except AlphaError as error:
                outcome = error
        return outcome, reserve

    def test_a_reconnect_naming_a_different_server_than_the_card_is_refused_and_takes_no_slot_path(self):
        outcome, reserve = self.start(self.world(), SECOND_GUILD)
        self.assertIsInstance(outcome, AlphaError)
        self.assertEqual(outcome.status, 404)
        reserve.assert_not_called()

    def test_the_control_a_genuine_reconnect_is_a_reconnect_not_a_new_server(self):
        outcome, reserve = self.start(self.world(), GUILD)
        self.assertEqual(outcome, 'started')
        self.assertIs(reserve.call_args.kwargs['new_server'], False)


class AStartIsThrottledPerWorkspace(unittest.TestCase):
    """The oauth-start throttle (20 per 10 minutes per workspace) for every purpose (DO13 survived)."""

    def test_identity_and_installation_starts_each_count_against_the_workspace(self):
        for capability, inputs in (('identity', {'discordPurpose': 'identity'}),
                                   ('publish', {'discordPurpose': 'installation', 'identityConnectionId': 'identity', 'guildId': GUILD})):
            s, wire, cur = with_roles('owner', True, True, True, True)
            seen = []

            def refuse(cur_, scope, limit, window):
                seen.append((scope, limit, window))
                raise AlphaError('Too many attempts. Wait a minute and try again.', 429)
            with patch('postriff_phase2.hosted.throttle', refuse):
                with self.assertRaises(AlphaError) as raised:
                    s.start(WORKSPACE, 'session', capability, inputs)
            self.assertEqual(raised.exception.status, 429)
            self.assertEqual(seen[0], (f'oauth-start:{WORKSPACE}', 20, 600), capability)
            self.assertEqual(wire.lifecycle_calls, [], capability)


class TheCallbackIssuerIsChecked(unittest.TestCase):
    """RFC 9207 `iss`: a callback that names another issuer is refused before the code is exchanged (DO4 survived)."""

    def complete(self, iss, *, v2=False):
        s, wire, state, row, cur = installation_callback()
        if v2:
            s.adapter.webhook_v1_enabled = True
            context = {'v': 2, 'purpose': 'webhook', 'workspaceId': WORKSPACE, 'memberId': ACTOR, 'applicationId': APP,
                       'redirectUri': s.oauth.callback_uri('discord'), 'pkceVerifier': 'x' * 64, 'expectedChannelId': '7777777'}
            encrypted, key = s.oauth.vault.encrypt(json.dumps(context))
            row[4:7] = [['identify', 'webhook.incoming'], encrypted, key]
        with patch('postriff_phase2.hosted.audit'):
            try:
                s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'install-' + GUILD, **({} if iss is ... else {'iss': iss}))
            except AlphaError as error:
                return error, wire
        return None, wire

    def exchanged(self, wire):
        return ('POST', '/oauth2/token') in wire.lifecycle_calls

    def test_a_foreign_issuer_never_reaches_the_token_endpoint(self):
        for v2 in (False, True):
            error, wire = self.complete('https://discord.evil.example', v2=v2)
            self.assertIn('issuer', str(error), v2)
            self.assertFalse(self.exchanged(wire), v2)

    def test_the_v2_flow_requires_the_issuer_to_be_present(self):
        error, wire = self.complete(None, v2=True)
        self.assertIn('issuer', str(error))
        self.assertFalse(self.exchanged(wire))

    def test_the_genuine_issuer_and_the_legacy_absent_issuer_are_accepted(self):
        for iss in ('https://discord.com', ...):
            error, wire = self.complete(iss, v2=False)
            self.assertIsNone(error, iss)
            self.assertTrue(self.exchanged(wire), iss)


class TheBotIsInvitedWithExactlyTheFourPermissions(unittest.TestCase):
    """DiscordProvider.PERMISSIONS = View Channel + Send Messages + Attach Files + Read Message History = 101376 (SC5b: no test
    pinned the integer that decides what the shared bot may do in every customer's server)."""

    def test_the_integer(self):
        self.assertEqual(DiscordProvider.PERMISSIONS, 101376)
        self.assertEqual(DiscordProvider.PERMISSIONS, (1 << 10) | (1 << 11) | (1 << 15) | (1 << 16))
        for dangerous in (1 << 3, 1 << 5, 1 << 17, 1 << 18, 1 << 6, 1 << 13, 1 << 28, 1 << 29):  # Administrator, Manage Server/Channels/Roles/Webhooks, Mention Everyone...
            self.assertFalse(DiscordProvider.PERMISSIONS & dangerous)

    def test_the_authorization_link_carries_it_and_nothing_wider(self):
        s, wire, cur = with_roles('owner', True, True, True, True)
        s.local = lambda workspace, token: _local(cur, _state_with_identity(), ACTOR)
        s.bind_identity = Mock(return_value=(('c', 'k', 'r', NOW + 3600, GENERATION, ['identify', 'guilds'], USER), {'user': USER, 'at': 'a'}))
        s._fresh_identity = Mock(return_value={'connectionId': 'identity', 'authorizationGeneration': GENERATION, 'userId': USER, 'bearer': 'b', 'scopes': ['identify', 'guilds']})
        s.user_guilds = Mock(return_value=[{'id': GUILD, 'name': 'one'}])
        cur.fetchone.return_value = ('transaction-id',)
        with patch('postriff_phase2.hosted.throttle'), patch('postriff_phase2.hosted.audit'):
            started = s.start(WORKSPACE, 'session', 'publish', {'discordPurpose': 'installation', 'identityConnectionId': 'identity', 'guildId': GUILD})
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(started['authorizeUrl']).query)
        self.assertEqual(query['permissions'], ['101376'])
        self.assertEqual(query['scope'], ['identify bot'])
        self.assertEqual((query['guild_id'], query['disable_guild_select']), ([GUILD], ['true']))


def _state_with_identity():
    state = initial_state(WORKSPACE)
    state['phase2'] = {'channels': [], 'discordIdentityLinks': [
        {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'userId': USER, 'status': 'linked',
         'authorizationGeneration': GENERATION, 'discoverGuilds': True}]}
    return state


class TheRefreshClaimFencesTheInstallation(unittest.TestCase):
    """While a rotating refresh is in flight (refreshClaim) nothing may validate or re-verify through that identity."""

    def test_validate_installation_refuses_while_a_refresh_is_claimed(self):
        s, _ = service()
        for claim, ok in ((None, True), ('claim', False)):
            record = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'userId': USER, 'status': 'linked',
                      'authorizationGeneration': GENERATION, **({'refreshClaim': claim} if claim else {})}
            state = initial_state(WORKSPACE)
            state['phase2'] = {'channels': [], 'discordIdentityLinks': [record]}
            cur = Mock()
            cur.fetchone.return_value = (state,)
            s.require_active_installation_authorizer = Mock()
            s.bind_identity = Mock(return_value=(('c', 'k', 'r', NOW + 3600, GENERATION, ['identify'], USER), {'user': USER}))
            envelope = {'kind': 'installation', 'identityConnectionId': 'identity', 'identityGeneration': GENERATION, 'user': USER}
            if ok:
                s.validate_installation(cur, WORKSPACE, envelope)
            else:
                with self.assertRaises(AlphaError):
                    s.validate_installation(cur, WORKSPACE, envelope)

    def test_reverification_refuses_while_a_refresh_is_claimed_and_asks_discord_nothing(self):
        from test_discord_authorizer_custody import World
        world = World(('admin', True))
        world.identity['refreshClaim'] = 'in-flight'
        with self.assertRaises(AlphaError):
            world.reverify()
        self.assertEqual(world.discord_requests(), [])


class TheWorkerGrantUsesBothAuthorizerChecks(unittest.TestCase):
    """E-2: discord_grant_for_worker verifies the authorizing member BEFORE any Discord request (installation_identity) and
    again under the credential lock (validate_installation). Removing either wiring survived every offline test."""

    def oauth(self):
        from postriff_phase2.oauth import CredentialVault, OAuthService
        adapter = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=Mock(), production_reviewed=True)
        adapter.authorization_v2_enabled = adapter.connections_v2_enabled = True
        service_ = OAuthService(SimpleNamespace(connection_factory=Mock()), SimpleNamespace(), CredentialVault(CredentialVault.generate_key()), {'discord': adapter}, 'https://rafii.example.invalid')
        return service_, adapter

    def test_without_a_cursor_the_identity_is_verified_first_and_a_refusal_stops_everything(self):
        service_, adapter = self.oauth()
        service_.discord_connections.installation_identity = Mock(side_effect=AlphaError('The Discord server authorizer no longer manages this workspace connection.', 409))
        with self.assertRaises(AlphaError):
            service_.discord_grant_for_worker(WORKSPACE, 'connection')
        service_.discord_connections.installation_identity.assert_called_once_with(WORKSPACE, 'connection')
        service_.repository.connection_factory.assert_not_called()  # it never got as far as reading the credential
        adapter.transport.assert_not_called()

    def test_with_a_cursor_the_installation_is_validated_before_a_grant_is_returned(self):
        service_, adapter = self.oauth()
        envelope = {'v': 2, 'kind': 'installation', 'identityConnectionId': 'identity'}
        encrypted, key = service_.vault.encrypt(json.dumps(envelope))
        cur = Mock()
        cur.fetchone.return_value = (encrypted, key, ['bot', 'identify'], 'generation')
        service_.discord_connections.validate_installation = Mock(side_effect=AlphaError('Removed workspace member', 409))
        with self.assertRaises(AlphaError):
            service_.discord_grant_for_worker(WORKSPACE, 'connection', cur=cur)
        service_.discord_connections.validate_installation.assert_called_once()
        service_.discord_connections.validate_installation = Mock()
        self.assertEqual(service_.discord_grant_for_worker(WORKSPACE, 'connection', cur=cur)['authorizationGeneration'], 'generation')


if __name__ == '__main__':
    unittest.main()
