"""Bot-free permission proof uses current, bound OAuth authority; no network."""
import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.webhooks import verify
from test_discord_multimode import HookWire, session, social_fixture
from test_discord_publish_authorization import APP, USER, GUILD, FIRST, WORKSPACE, ACTOR, NOW, GENERATION


def owner_fixture(*, owner=True, permissions='0'):
    _, provider, _, _ = social_fixture()
    hook = HookWire()
    calls = []
    authorization = {'application': {'id': APP}, 'user': {'id': USER}, 'scopes': ['identify', 'guilds']}
    guilds = [{'id': GUILD, 'owner': owner, 'permissions': permissions}]

    def wire(method, url, **kwargs):
        calls.append((method, url, kwargs))
        path = urlsplit(url).path.removeprefix('/api/v10')
        if path == '/oauth2/@me':
            return {'status': 200, 'body': copy.deepcopy(authorization)}
        if path == '/users/@me/guilds':
            return {'status': 200, 'body': copy.deepcopy(guilds)}
        return hook(method, url, **kwargs)

    provider.transport = wire
    provider._bot_identity = Mock(side_effect=AlphaError('No bot is installed.', 409))
    identity = {'userId': USER, 'bearer': 'synthetic-oauth-access', 'scopes': ['identify', 'guilds']}
    provider.webhook_authorizer = Mock(return_value=identity)
    return provider, calls, authorization, guilds


class WebhookOwnerAuthorization(unittest.TestCase):
    def test_owner_uses_current_oauth_without_a_bot(self):
        provider, calls, _, _ = owner_fixture()
        proof = verify(provider, session())
        self.assertEqual(proof['permissionProof'], 'current_owner_oauth')
        self.assertEqual(proof['senderKind'], 'webhook')
        self.assertTrue(proof['userPermissions'] & provider.SEND_MESSAGES)
        provider._bot_identity.assert_not_called()
        self.assertTrue(any('/oauth2/@me' in url for _, url, _ in calls))
        self.assertTrue(any('/users/@me/guilds' in url for _, url, _ in calls))
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))
        self.assertNotIn('synthetic-oauth-access', str(proof))

    def test_administrator_bypasses_overwrites_but_manage_server_does_not(self):
        provider, _, _, _ = owner_fixture(owner=False, permissions='8')
        self.assertEqual(verify(provider, session())['permissionProof'], 'current_admin_oauth')
        provider._bot_identity.assert_not_called()
        for permissions in ('32', '3072', '-1', '8.0', 'bad', True, 8, None):
            with self.subTest(permissions=permissions):
                provider, _, _, _ = owner_fixture(owner=False, permissions=permissions)
                with self.assertRaises(AlphaError):
                    verify(provider, session())

    def test_privilege_loss_is_not_cached_or_replaced_by_webhook_custody(self):
        provider, calls, _, guilds = owner_fixture()
        verify(provider, session())
        guilds[0]['owner'] = False
        with self.assertRaises(AlphaError):
            verify(provider, session())
        self.assertEqual(sum('/users/@me/guilds' in url for _, url, _ in calls), 2)
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))

    def test_wrong_subject_application_or_missing_live_scope_cannot_authorize(self):
        for change in ({'user': {'id': '99887766'}}, {'application': {'id': '99887766'}},
                       {'scopes': ['identify']}, {'scopes': 'identify guilds'}):
            with self.subTest(change=change):
                provider, _, authorization, _ = owner_fixture()
                authorization.update(change)
                with self.assertRaises(AlphaError):
                    verify(provider, session())

    def test_missing_guild_or_ambiguous_provider_response_fails_closed(self):
        for value in ([], [{'id': '99887766', 'owner': True, 'permissions': '8'}],
                      [{'id': GUILD, 'owner': 'true', 'permissions': '0'}],
                      [{'id': GUILD, 'owner': True}, {'id': GUILD, 'owner': False}]):
            with self.subTest(value=value):
                provider, _, _, guilds = owner_fixture()
                guilds[:] = value
                with self.assertRaises(AlphaError):
                    verify(provider, session())

    def test_unbound_or_identify_only_grant_keeps_existing_bot_witness(self):
        from test_discord_multimode import social_fixture
        for identity in (None, {'userId': USER, 'bearer': 'synthetic', 'scopes': ['identify']}):
            with self.subTest(identity=identity):
                _, provider, wire, _ = social_fixture()
                provider.webhook_authorizer = Mock(return_value=identity)
                self.assertEqual(verify(provider, session())['permissionProof'], 'current_app_read')
                self.assertFalse(any('/users/@me/guilds' in url for _, url, _ in wire.calls))

    def test_transient_oauth_reads_use_existing_read_authorization_guard(self):
        provider, _, _, _ = owner_fixture()
        guard = Mock(side_effect=AlphaError('Synthetic canceled read.', 409))
        with self.assertRaises(AlphaError):
            verify(provider, session(), read_authorize=guard)
        guard.assert_called()

    def test_one_webhook_dispatch_and_exact_receipt_without_bot_reads(self):
        from test_discord_multimode import webhook_fixture
        from test_discord_publish_authorization import review, approve
        from postriff_phase2.discord.authorization import digest
        engine, state, channel, variant = webhook_fixture()
        job = approve(engine, state, review(engine, state, channel, variant))
        social, _, _, _ = social_fixture()
        provider, calls, _, _ = owner_fixture()
        social.providers['discord'] = provider
        manifest = job['manifest']
        prepared = social.prepare_discord_dispatch(manifest)
        result = social.submit_discord_authorized(manifest, {**prepared,
            'intent': {'id': 'synthetic-lease', 'manifestDigest': digest(manifest), 'publicationId': job['id']}})
        self.assertEqual(result['state'], 'provider_accepted')
        receipt = social.reconcile_discord(manifest, {**job, 'providerReference': result['reference']})
        self.assertEqual(receipt['state'], 'verified')
        self.assertEqual(sum(method == 'POST' for method, _, _ in calls), 1)
        provider._bot_identity.assert_not_called()


def bound_fixture():
    from test_discord_installation_reverification import reverify_fixture
    s, wire, state, channel, credentials, envelopes, cur = reverify_fixture()
    s.adapter.webhook_v1_enabled = True
    identity_id = channel['discordIdentityConnectionId']
    identity_generation = credentials[identity_id][4]
    channel.update(discordConnectionKind='webhook', providerAccountId='66112233',
                   discordLinkedUserId=USER, discordAuthorizedBy=ACTOR, discordWebhookChannelId=FIRST)
    envelope = {**session(), 'connectionId': channel['id'], 'identityConnectionId': identity_id,
                'identityGeneration': identity_generation}
    ciphertext, key = s.oauth.vault.encrypt(json.dumps(envelope))
    credentials[channel['id']] = [ciphertext, key, None, None, GENERATION, ['identify', 'webhook.incoming'], '66112233']
    envelopes[channel['id']] = copy.deepcopy(envelope)
    last_sql, access = [''], {'active': True}
    original_execute = cur.execute.side_effect

    def execute(sql, params=()):
        last_sql[0] = sql
        original_execute(sql, params)

    def fetchone():
        if last_sql[0].startswith('SELECT m.role,'):
            if not access['active']:
                return None
            return ('owner', True) if 'm.role,m.can_manage_connections' in last_sql[0] else ('owner', True, True, True, True)
        return (state,)

    cur.execute.side_effect, cur.fetchone.side_effect = execute, fetchone
    return s, wire, state, channel, credentials, envelopes, envelope, access


class WebhookIdentityCustody(unittest.TestCase):
    def test_bound_identity_refreshes_outside_locks_and_never_copies_bearer_into_webhook(self):
        s, wire, state, channel, credentials, envelopes, envelope, _ = bound_fixture()
        identity_id = envelope['identityConnectionId']
        credentials[identity_id][2] = s.oauth.vault.encrypt('synthetic-refresh')[0]
        credentials[identity_id][3] = NOW - 10
        original_local, original_fresh, locked = s.local, s._fresh_identity, {'value': False}

        @contextmanager
        def local(*args):
            with original_local(*args) as value:
                locked['value'] = True
                try:
                    yield value
                finally:
                    locked['value'] = False

        def fresh(*args):
            self.assertFalse(locked['value'], 'Provider refresh must not hold the workspace lock')
            return original_fresh(*args)

        s.local, s._fresh_identity = local, fresh
        identity = s.webhook_authorizer(envelope)
        self.assertEqual(identity['userId'], USER)
        self.assertEqual(wire.refresh_count, 1)
        self.assertNotIn(identity['bearer'], json.dumps(envelopes[channel['id']]))
        self.assertNotIn(identity['bearer'], json.dumps(state))

    def test_changed_actor_generation_or_workspace_membership_stops_before_provider_io(self):
        for change in ('actor', 'generation', 'stored_binding', 'member', 'disconnected'):
            with self.subTest(change=change):
                s, wire, state, channel, _, envelopes, envelope, access = bound_fixture()
                record = state['phase2']['discordIdentityLinks'][0]
                if change == 'actor': record['authorizedBy'] = 'other-member'
                if change == 'generation': envelope['identityGeneration'] = 'changed'
                if change == 'stored_binding': envelopes[channel['id']]['identityConnectionId'] = 'other-identity'
                if change == 'member': access['active'] = False
                if change == 'disconnected': record['status'] = 'disconnected'
                with self.assertRaises(AlphaError):
                    s.webhook_authorizer(envelope)
                self.assertEqual(wire.lifecycle_calls, [])

    def test_revocation_during_provider_check_cannot_return_late_success(self):
        s, _, _, channel, _, _, envelope, _ = bound_fixture()
        original_fresh = s._fresh_identity
        def fresh(*args):
            identity = original_fresh(*args)
            channel['revoked'] = True
            return identity
        s._fresh_identity = fresh
        with self.assertRaises(AlphaError):
            s.webhook_authorizer(envelope)

    def test_legacy_and_scope_limited_links_do_not_gain_bot_free_authority(self):
        s, wire, _, _, credentials, _, envelope, _ = bound_fixture()
        credentials[envelope['identityConnectionId']][5] = ['identify']
        self.assertIsNone(s.webhook_authorizer(envelope))
        self.assertIsNone(s.webhook_authorizer(session()))
        self.assertEqual(wire.lifecycle_calls, [])
