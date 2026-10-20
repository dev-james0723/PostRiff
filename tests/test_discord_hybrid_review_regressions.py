"""Independent-review regressions; all provider and storage values are synthetic."""
import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from postriff_alpha.domain import AlphaError
from test_discord_multimode import social_fixture, webhook_fixture, session, review, approve, GENERATION, WORKSPACE, ACTOR, GUILD, FIRST, USER
from test_discord_interactions import InteractionFixture
from test_discord_oauth_lifecycle import service


class RecoveryRouteTests(InteractionFixture, unittest.TestCase):
    def test_no_or_ambiguous_identity_uses_real_authenticated_channels_route(self):
        for links in ([], [{'workspaceId': 'a'}, {'workspaceId': 'b'}]):
            self.links = links
            self.seen.clear()
            value = self.send(self.packet())
            self.assertIn('https://rafii.example.invalid/app/channels?connect=discord', value['data']['content'])
            self.assertNotIn('workspaceId=', value['data']['content'])


class WebhookPermissionTests(unittest.TestCase):
    def test_surviving_webhook_does_not_send_after_discord_authorizer_removed(self):
        engine, state, channel, variant = webhook_fixture()
        manifest = approve(engine, state, review(engine, state, channel, variant))['manifest']
        social, provider, wire, _ = social_fixture()
        old = provider.transport
        def removed(method, url, **kwargs):
            if '/guilds/' in url or '/channels/' in url:
                return {'status': 404, 'body': {}}
            return old(method, url, **kwargs)
        provider.transport = removed
        with self.assertRaises(AlphaError):
            social.prepare_discord_dispatch(manifest)
        self.assertFalse(any(call[0] == 'POST' for call in wire.calls))

    def test_permission_witness_requires_current_exact_channel_permissions(self):
        _, provider, wire, _ = social_fixture()
        old = provider.transport
        def denied(method, url, **kwargs):
            if url.endswith('/guilds/' + GUILD):
                return {'status': 200, 'body': {'id': GUILD, 'owner_id': '909090', 'roles': [{'id': GUILD, 'permissions': '1024'}]}}
            if '/members/' in url:
                return {'status': 200, 'body': {'user': {'id': url.rsplit('/', 1)[1]}, 'roles': [], 'pending': False}}
            if url.endswith('/channels/' + FIRST):
                return {'status': 200, 'body': {'id': FIRST, 'guild_id': GUILD, 'type': 0, 'permission_overwrites': []}}
            return old(method, url, **kwargs)
        provider.transport = denied
        with self.assertRaises(AlphaError):
            provider.destinations(json.dumps(session()))
        self.assertFalse(any(call[0] == 'POST' for call in wire.calls))


class WebhookVerificationRaceTests(unittest.TestCase):
    def test_newer_denial_fences_old_success_even_when_initial_capability_false(self):
        s, _ = service()
        s.adapter.webhook_v1_enabled = True
        channel = {'id': 'hook', 'capabilityVerified': False,
                   'discordDestinations': [{'status': 'authorized', 'authorizationGeneration': GENERATION}]}
        state = {'workspace': {'id': WORKSPACE}, 'phase2': {'channels': [channel]}}
        cursor = Mock()
        @contextmanager
        def local(*args, **kwargs):
            yield cursor, state, ACTOR
        s.local = local
        row = ('ciphertext', 'key', None, None, GENERATION, ['identify', 'webhook.incoming'])
        s.read_credential = Mock(return_value=(row, {**session(), 'connectionId': 'hook'}))
        s.validate_webhook = Mock()
        s.save_state = Mock()
        running_inner = False
        def interleaved(*args, **kwargs):
            nonlocal running_inner
            if running_inner:
                raise AlphaError('Newer permission observation denied', 409)
            running_inner = True
            with self.assertRaises(AlphaError):
                s.reverify_webhook(WORKSPACE, 'hook', token='synthetic-session')
            running_inner = False
            return {'id': FIRST}
        with patch('postriff_phase2.discord.webhooks.verify', side_effect=interleaved), patch('postriff_phase2.hosted.audit'):
            with self.assertRaises(AlphaError):
                s.reverify_webhook(WORKSPACE, 'hook', token='synthetic-session')
        self.assertFalse(channel['capabilityVerified'])
        self.assertTrue(channel.get('discordVerificationGeneration'))


class InstallationAuthorizerMembershipTests(unittest.TestCase):
    def test_removed_workspace_authorizer_cannot_keep_bot_installation_authority(self):
        s, _ = service()
        from test_discord_oauth_lifecycle import NOW
        generation = GENERATION
        state = {'workspace': {'id': WORKSPACE}, 'phase2': {'discordIdentityLinks': [
            {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR,
             'userId': USER, 'status': 'linked', 'authorizationGeneration': generation}]}}
        cursor = Mock()
        def execute(sql, params=()):
            cursor.last_sql = sql
        def fetchone():
            if cursor.last_sql.startswith('SELECT state FROM public.pr_workspaces'):
                return (state,)
            if cursor.last_sql.startswith('SELECT m.role'):
                return None  # User is no longer a Rafii workspace member.
            raise AssertionError('Unexpected SQL query')
        cursor.execute.side_effect = execute
        cursor.fetchone.side_effect = fetchone
        s.bind_identity = Mock(return_value=(('cipher', 'key', None, NOW + 3600,
                                                 generation, ['identify', 'guilds'], USER), {'user': USER}))
        with self.assertRaises(AlphaError):
            s.validate_installation(cursor, WORKSPACE, {
                'kind': 'installation', 'identityConnectionId': 'identity',
                'identityGeneration': generation, 'user': USER})
        self.assertTrue(any(c.args[0].startswith('SELECT m.role') for c in cursor.execute.call_args_list))

    def test_downgraded_authorizer_cannot_supply_bot_installation_authority(self):
        s, _ = service()
        from test_discord_oauth_lifecycle import NOW
        state = {'workspace': {'id': WORKSPACE}, 'phase2': {'discordIdentityLinks': [
            {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR,
             'userId': USER, 'status': 'linked', 'authorizationGeneration': GENERATION}]}}
        cursor = Mock()
        def execute(sql, params=()):
            cursor.last_sql = sql
        cursor.execute.side_effect = execute
        s.bind_identity = Mock(return_value=(('cipher', 'key', None, NOW + 3600,
                GENERATION, ['identify'], USER), {'user': USER}))
        for downgraded in [('editor', False), ('viewer', False)]:
            with self.subTest(role=downgraded[0]):
                def fetchone():
                    return (state,) if cursor.last_sql.startswith('SELECT state') else downgraded
                cursor.fetchone.side_effect = fetchone
                with self.assertRaises(AlphaError):
                    s.validate_installation(cursor, WORKSPACE, {
                        'kind': 'installation', 'identityConnectionId': 'identity',
                        'identityGeneration': GENERATION, 'user': USER})
        s.bind_identity.assert_not_called()

    def test_active_authorizer_may_refresh_expired_identity_before_final_installation_guard(self):
        # A legitimate linked identity can be expired at the instant a worker
        # starts; membership must be checked early without blocking the
        # existing rotating-token refresh.
        from test_discord_oauth_lifecycle import NOW
        s, _ = service()
        state = {'workspace': {'id': WORKSPACE}, 'phase2': {'discordIdentityLinks': [
            {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR,
             'userId': USER, 'status': 'linked', 'authorizationGeneration': GENERATION}]}}
        cur = Mock()
        @contextmanager
        def local(*args, **kwargs):
            yield cur, state, None
        s.local = local
        cur.execute.side_effect = lambda sql, params=(): setattr(cur, 'last_sql', sql)
        cur.fetchone.side_effect = lambda: ('owner', True) if cur.last_sql.startswith('SELECT m.role') else (state,)
        s.read_credential = Mock(return_value=(('cipher',), {'kind': 'installation',
            'identityConnectionId': 'identity'}))
        s.bind_identity = Mock(return_value=(('cipher', 'key', 'refresh', NOW - 1, GENERATION,
            ['identify'], USER), {'user': USER}))
        s._fresh_identity = Mock(return_value={'authorizationGeneration': GENERATION, 'userId': USER})
        s.installation_identity(WORKSPACE, 'install')
        s._fresh_identity.assert_called_once_with(WORKSPACE, None, 'identity')

    def test_worker_cannot_refresh_removed_installation_identity_before_authority_check(self):
        s, _ = service()
        cursor = Mock()
        state = {'workspace': {'id': WORKSPACE}, 'phase2': {'discordIdentityLinks': [
            {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR,
             'status': 'linked', 'authorizationGeneration': GENERATION}]}}
        @contextmanager
        def local(*args, **kwargs):
            yield cursor, state, None
        s.local = local
        s.read_credential = Mock(return_value=(('cipher',), {'kind': 'installation',
            'identityConnectionId': 'identity'}))
        s.require_active_installation_authorizer = Mock(side_effect=AlphaError('Removed workspace member', 409))
        s._fresh_identity = Mock()
        with self.assertRaises(AlphaError):
            s.installation_identity(WORKSPACE, 'server')
        s.require_active_installation_authorizer.assert_called_once()
        s._fresh_identity.assert_not_called()


if __name__ == '__main__':
    unittest.main()
