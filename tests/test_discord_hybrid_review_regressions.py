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


if __name__ == '__main__':
    unittest.main()
