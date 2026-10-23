"""One custody condition at a time (independent review, SNR-3).

Every case corrupts exactly one thing BEFORE the first profile read. The settings fingerprint is then computed in the corrupted
state, so a stale fingerprint cannot be what refuses and only the named check can. (An earlier shape of these tests changed the
state after reading the profile, which the fingerprint refuses whether or not the check exists.) Each table row also has its
control: the same world without the corruption answers.

Two worlds: the upstream-style harness with mocked custody validators (conditions that live in SenderNames.custody itself,
plus the write path against the real shared-rate algorithm), and the multi-tenant world with the real validators.
"""
import os
import unittest
from unittest.mock import Mock, patch

from discord_sender_name_settings_fixture import Settings
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.sender_names import SenderNames
from test_discord_sender_name import SettingsHarness, GUILD, APP, NOW, WORKSPACE, ACTOR
from test_discord_sender_name_routes import BODY, Base as RouteBase


class Harnessed(unittest.TestCase):
    """The reviewer's isolated conditions, on the upstream harness."""
    def refused(self, h, op='sender_profile', *args):
        with self.assertRaises(AlphaError) as caught:
            h.call(self, op, *args)
        return caught.exception

    def body(self, h, name='Brand'):
        current = h.call(self, 'sender_profile')
        return {'name': name, 'fingerprint': current['fingerprint'], 'confirmed': True, 'sharedServerConfirmed': True}

    # ---- webhook custody, each condition alone ----
    def test_webhook_envelope_workspace(self):
        h = SettingsHarness(); h.envelope['workspaceId'] = 'other-workspace'; self.refused(h)

    def test_webhook_envelope_connection(self):
        h = SettingsHarness(); h.envelope['connectionId'] = 'other-connection'; self.refused(h)

    def test_webhook_authorization_generation(self):
        h = SettingsHarness(); h.channel['discordAuthorizationGeneration'] = 'stale-generation'; self.refused(h)

    def test_webhook_revalidation_is_called(self):
        h = SettingsHarness(); h.s.validate_webhook.side_effect = AlphaError('authorizer lost permission', 409); self.refused(h)
        self.assertEqual(h.s.validate_webhook.call_count, 1)

    # ---- bot custody, each condition alone ----
    def test_bot_a_member_who_is_not_the_authorizer_sees_why_and_nothing_is_read_or_written(self):
        h = SettingsHarness('bot'); h.actor = 'another-admin-of-this-workspace'
        requests = []
        inner = h.s.adapter.transport
        h.s.adapter.transport = lambda *a, **k: (requests.append(a[:2]), inner(*a, **k))[1]
        profile = h.call(self, 'sender_profile')
        self.assertEqual((profile['editable'], [r['code'] for r in profile['unavailable']]), (False, ['not_authorizing_member']))
        error = self.refused(h, 'set_sender_name', {'name': 'Brand', 'fingerprint': profile['fingerprint'], 'confirmed': True,
                                                     'sharedServerConfirmed': True})
        self.assertEqual((error.status, error.code), (403, 'discord_sender_name_unavailable'))
        self.assertEqual((requests, h.patches), ([], []))

    def test_bot_identity_must_be_linked(self):
        h = SettingsHarness('bot'); h.state['phase2']['discordIdentityLinks'][0]['status'] = 'reconnect_required'; self.refused(h)

    def test_bot_identity_generation(self):
        h = SettingsHarness('bot'); h.state['phase2']['discordIdentityLinks'][0]['authorizationGeneration'] = 'other'; self.refused(h)

    def test_bot_identity_user_matches_installation_user(self):
        h = SettingsHarness('bot'); h.state['phase2']['discordIdentityLinks'][0]['userId'] = '424243'; self.refused(h)

    def test_bot_fresh_authorizer_revalidation_is_called_on_write(self):
        h = SettingsHarness('bot'); body = self.body(h)
        h.s.validate_installation.side_effect = AlphaError('authorizer no longer manages connections', 409)
        self.refused(h, 'set_sender_name', body)
        self.assertEqual(h.patches, [])
        self.assertEqual(h.s.validate_installation.call_count, 1)

    # ---- account and connection state ----
    def test_account_block(self):
        h = SettingsHarness(); h.state['accountBlock'] = True; self.refused(h)

    def test_account_deletion(self):
        h = SettingsHarness(); h.state['accountDeletion'] = True; self.refused(h)

    def test_revoked_connection(self):
        h = SettingsHarness(); h.channel['revoked'] = True; self.refused(h)

    def test_scopes_must_match_the_stored_credential(self):
        h = SettingsHarness()
        base = h.s.read_credential
        h.s.read_credential = lambda *a: ((lambda row, env: (row[:5] + (['identify', 'webhook.incoming', 'guilds'],) + row[6:], env))(*base(*a)))
        self.refused(h)

    def test_credential_application(self):
        h = SettingsHarness(); h.envelope['applicationId'] = '7654321'; self.refused(h)

    def test_credential_snowflakes(self):
        h = SettingsHarness(); h.envelope['guild'] = 'not-a-snowflake'; self.refused(h)

    def test_token_required(self):
        h = SettingsHarness()
        with self.assertRaises(AlphaError) as caught:
            SenderNames(h.s, WORKSPACE, None, h.channel['id'])
        self.assertEqual(caught.exception.status, 401)

    # ---- write path, against the real shared-rate algorithm ----
    def bot_with_real_rate_algorithm(self):
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget
        from test_discord_rate_limits import MemoryLedger, synthetic_policy
        h = SettingsHarness('bot')
        ledger = MemoryLedger(now=NOW)
        h.cur = ledger
        h.s.save_state = Mock()
        h.s.oauth.clock = lambda: ledger.now
        h.s.adapter.rate_v1_enabled = True
        h.s.adapter.rate_limiter = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy(NOW))
        base = h.s.adapter.transport

        def rated(method, url, **kwargs):
            result = base(method, url, **kwargs)
            result['headers'] = {'X-RateLimit-Bucket': 'synthetic-' + method, 'X-RateLimit-Limit': '100',
                                 'X-RateLimit-Remaining': '90', 'X-RateLimit-Reset-After': '1'}
            return result
        h.s.adapter.transport = rated
        return h, ledger

    def test_final_guard_refuses_a_claim_that_expired_after_admission(self):
        h, ledger = self.bot_with_real_rate_algorithm()
        body = self.body(h)
        limiter = h.s.adapter.rate_limiter
        real = limiter.consume

        def consume_then_time_passes(*a, **k):
            real(*a, **k)
            ledger.now += 1000
        limiter.consume = consume_then_time_passes
        self.refused(h, 'set_sender_name', body)
        self.assertEqual(h.patches, [])
        self.assertEqual([r['state'] for r in ledger.admissions.values() if r['method'] == 'PATCH'], ['blocked'])
        self.assertNotIn('discordSenderEdit', h.channel, 'a write known to be unsent leaves no claim behind')

    def test_final_guard_refuses_a_connection_revoked_after_admission(self):
        h, ledger = self.bot_with_real_rate_algorithm()
        body = self.body(h)
        limiter = h.s.adapter.rate_limiter
        real = limiter.consume

        def consume_then_revoked(*a, **k):
            real(*a, **k)
            h.channel['revoked'] = True
        limiter.consume = consume_then_revoked
        self.refused(h, 'set_sender_name', body)
        self.assertEqual(h.patches, [])
        self.assertEqual([r['state'] for r in ledger.admissions.values() if r['method'] == 'PATCH'], ['blocked'])

    def test_patch_answer_with_a_different_nickname_is_not_a_success(self):
        h = SettingsHarness('bot'); body = self.body(h)
        base = h.s.adapter.transport

        def sanitized(method, url, **kw):
            r = base(method, url, **kw)
            if method == 'PATCH':
                r['body']['nick'] = 'Something else'
            return r
        h.s.adapter.transport = sanitized
        error = self.refused(h, 'set_sender_name', body)
        self.assertEqual(error.code, 'discord_sender_write_unconfirmed')
        self.assertNotEqual(h.channel.get('discordSenderName'), 'Brand')
        self.assertIn('discordSenderEdit', h.channel, 'the nickname may have changed: a later read settles it')

    def test_patch_403_is_a_refusal_and_never_a_success(self):
        h = SettingsHarness('bot'); body = self.body(h)
        base = h.s.adapter.transport

        def forbidden(method, url, **kw):
            r = base(method, url, **kw)
            if method == 'PATCH':
                r = {'status': 403, 'body': {'code': 50013}, 'headers': {}}
            return r
        h.s.adapter.transport = forbidden
        error = self.refused(h, 'set_sender_name', body)
        self.assertEqual((error.status, error.code), (409, 'discord_sender_write_refused'))
        self.assertNotIn('discordSenderName', h.channel)
        self.assertNotIn('discordSenderEdit', h.channel)

    def test_readback_by_another_writer_is_not_recorded_as_ours(self):
        h = SettingsHarness('bot'); body = self.body(h)
        base = h.s.adapter.transport
        state = {'patched': False}

        def racing(method, url, **kw):
            r = base(method, url, **kw)
            if method == 'PATCH':
                state['patched'] = True
            elif state['patched'] and url.endswith('/members/9000009'):
                r['body']['nick'] = 'Another tenant won'
            return r
        h.s.adapter.transport = racing
        error = self.refused(h, 'set_sender_name', body)
        self.assertEqual(error.code, 'discord_sender_write_unconfirmed')
        self.assertNotEqual(h.channel.get('discordSenderName'), 'Brand')

    def test_a_post_cannot_clear_an_expired_claim(self):
        h = SettingsHarness('bot')
        h.channel['discordSenderEdit'] = {'id': 'old', 'name': 'Old', 'expiresAt': NOW - 1}
        h.s.oauth.clock = lambda: NOW + 121
        self.refused(h, 'set_sender_name', {'name': 'Brand', 'fingerprint': 'x', 'confirmed': True, 'sharedServerConfirmed': True})
        self.assertEqual(h.channel['discordSenderEdit']['id'], 'old')
        self.assertEqual(h.patches, [])

    # ---- audit ----
    def test_audit_entry_records_scope_and_server_never_the_name(self):
        h = SettingsHarness(); current = h.call(self, 'sender_profile')
        with patch('postriff_phase2.hosted.audit') as audit, patch('postriff_phase2.hosted.throttle'), \
                patch('postriff_phase2.discord.sender_names.provider_ready', return_value=True):
            h.s.set_sender_name(WORKSPACE, 'synthetic-session', h.channel['id'],
                                {'name': 'Secret Brand', 'fingerprint': current['fingerprint'], 'confirmed': True})
        kinds = [c.args[3] for c in audit.call_args_list]
        self.assertIn('discord.sender_name_updated', kinds)
        self.assertNotIn('Secret Brand', repr(audit.call_args_list))
        meta = next(c.args[5] for c in audit.call_args_list if c.args[3] == 'discord.sender_name_updated')
        self.assertEqual(set(meta), {'senderKind', 'scope', 'guildId'})

    # ---- automation approval binds the name the person saw ----
    def test_approving_with_a_name_other_than_the_connections_is_refused(self):
        from test_discord_sender_name import webhook_fixture, auth
        from postriff_phase2 import campaigns
        engine, state, channel, variant = webhook_fixture()
        channel['discordSenderName'] = 'Shown brand'
        target = auth.destination(state, channel, channel['defaultDestinationId'])
        task = {'id': 'synthetic-task', 'status': 'active', 'schedule': {'timeZone': 'UTC'}}
        item = {'key': 'synthetic-item', 'platform': 'Discord', 'channelId': channel['id'], 'variantId': variant['id'],
                'state': 'ready_for_review', 'publishAt': NOW + 300}
        run = {'id': 'synthetic-run', 'taskId': task['id'], 'items': [item]}
        root = campaigns._root(state)
        root['recurringTasks'].append(task)
        root['occurrences'].append(run)
        body = {'occurrenceId': run['id'], 'itemKey': item['key'], 'decision': 'approve', 'confirmed': True, 'variantRevision': 1,
                'excludedUnknowns': [], 'acknowledgedWarnings': [], 'destinationId': target['id'],
                'destinationGeneration': target['resourceGeneration'], 'publishAt': NOW + 300,
                'discordSenderName': 'An older name the person saw'}
        with self.assertRaises(AlphaError):
            campaigns._decide(state, root, body, ACTOR, NOW)


class CustodyConditions(unittest.TestCase):
    """The multi-tenant world with the REAL custody validators: one corruption per case, made before the first read."""
    def setUp(self):
        for patcher in (patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true',
                                                'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}),
                        patch('postriff_phase2.discord.sender_names.provider_ready', return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def world(self):
        """Workspace A (owner = the acting user), a webhook authorized by a different admin, a bot installation authorized by
        the owner; workspace B with its own owner."""
        w = Settings()
        t = type('World', (), {})()
        t.w = w
        t.ua, t.ub, t.u3 = w.user(1), w.user(2), w.user(3)
        t.A, t.B = w.workspace(1), w.workspace(2)
        t.ta, t.tb = w.member(t.A, t.ua, 'owner'), w.member(t.B, t.ub, 'owner')
        t.t3 = w.member(t.A, t.u3, 'admin')
        t.wa = w.webhook(t.A, 1, t.u3, name='Alpha Weekly')
        t.ia = w.installation(t.A, 1, t.ua, guild='6400001')
        t.identity = lambda: w.workspaces[t.A].state['phase2']['discordIdentityLinks'][0]
        return t

    WEBHOOK = {
        'envelope names another member than the card': lambda t: t.w.rewrite_envelope(t.A, t.wa.connection, memberId=t.ub),
        'card names another authorizer': lambda t: t.w.channel(t.A, t.wa.connection).update(discordAuthorizedBy=t.ub),
        'envelope belongs to another workspace': lambda t: t.w.rewrite_envelope(t.A, t.wa.connection, workspaceId=t.B),
        'envelope belongs to another connection': lambda t: t.w.rewrite_envelope(t.A, t.wa.connection, connectionId='discord-webhook-other'),
        'authorization generation is stale': lambda t: t.w.channel(t.A, t.wa.connection).update(discordAuthorizationGeneration='stale'),
        'stored scopes differ from the card': lambda t: t.w.set_row(t.A, t.wa.connection, 5, ['identify', 'webhook.incoming', 'guilds']),
        'credential of another application': lambda t: t.w.rewrite_envelope(t.A, t.wa.connection, applicationId='7654321'),
        'server id is not a snowflake': lambda t: t.w.rewrite_envelope(t.A, t.wa.connection, guild='not-a-snowflake'),
        'webhook id differs from the card': lambda t: t.w.channel(t.A, t.wa.connection).update(providerAccountId='9999999'),
        'linked user differs from the card': lambda t: t.w.channel(t.A, t.wa.connection).update(discordLinkedUserId='424243'),
        'webhook channel differs from the card': lambda t: t.w.channel(t.A, t.wa.connection).update(discordWebhookChannelId='9999999'),
        'card is a bot installation': lambda t: t.w.channel(t.A, t.wa.connection).update(discordConnectionKind='installation'),
        'credential is an installation': lambda t: t.w.rewrite_envelope(t.A, t.wa.connection, kind='installation'),
        'authorizer lost connection management': lambda t: setattr(t.w.workspaces[t.A].members[t.u3], 'role', 'viewer'),
        'stored scopes lack webhook.incoming on both sides': lambda t: (
            t.w.set_row(t.A, t.wa.connection, 5, ['identify']), t.w.channel(t.A, t.wa.connection).update(scopes=['identify'])),
        'no authorization generation stored or on the card': lambda t: (
            t.w.set_row(t.A, t.wa.connection, 4, None), t.w.channel(t.A, t.wa.connection).update(discordAuthorizationGeneration=None)),
    }
    # What only the live validator (validate_webhook) can see: who authorized the webhook and whether they still may.
    LIVE_ONLY = ('envelope names another member than the card', 'card names another authorizer', 'authorizer lost connection management')

    BOT = {
        'identity is no longer linked': lambda t: t.identity().update(status='reconnect_required'),
        'identity generation changed': lambda t: t.identity().update(authorizationGeneration='other'),
        'identity belongs to another Discord user': lambda t: t.identity().update(userId='424243'),
        'card points at another identity': lambda t: t.w.channel(t.A, t.ia.connection).update(discordIdentityConnectionId='someone-elses'),
        'bot user id is not a snowflake': lambda t: t.w.rewrite_envelope(t.A, t.ia.connection, botUserId='not-a-snowflake'),
        'server differs from the card': lambda t: t.w.channel(t.A, t.ia.connection).update(providerAccountId='9999999'),
        'stored scopes differ from the card': lambda t: t.w.set_row(t.A, t.ia.connection, 5, ['bot', 'identify', 'guilds']),
        'credential is a webhook': lambda t: t.w.rewrite_envelope(t.A, t.ia.connection, kind='webhook'),
        'credential of another application': lambda t: t.w.rewrite_envelope(t.A, t.ia.connection, applicationId='7654321'),
        'identity record belongs to another workspace': lambda t: t.identity().update(workspaceId=t.B),
        'identity link is gone': lambda t: t.w.workspaces[t.A].state['phase2']['discordIdentityLinks'].clear(),
        'envelope names another server than the credential row': lambda t: t.w.rewrite_envelope(t.A, t.ia.connection, guild='9999999'),
        'stored scopes lack the installation scope on both sides': lambda t: (
            t.w.set_row(t.A, t.ia.connection, 5, ['identify']), t.w.channel(t.A, t.ia.connection).update(scopes=['identify'])),
        'no authorization generation stored or on the card': lambda t: (
            t.w.set_row(t.A, t.ia.connection, 4, None), t.w.channel(t.A, t.ia.connection).update(discordAuthorizationGeneration=None)),
        # An installation envelope carries no workspace or connection id (discord/oauth.py, the installation callback): its
        # binding to this workspace is the credential row's own key, so there is no such field to corrupt.
    }

    def run_table(self, table, own, *, mock_live=False):
        for label, corrupt in table.items():
            if mock_live and label in self.LIVE_ONLY:
                continue
            with self.subTest(corruption=label, live_validator=not mock_live):
                t = self.world()
                if mock_live:
                    t.w.s.validate_webhook = Mock()      # custody must not lean on the live validator for what it checks itself
                connection = getattr(t, own).connection
                control = t.w.get(t.A, t.ta, connection)                  # the control: the same world answers
                self.assertTrue(control['editable'], label)
                t = self.world()
                if mock_live:
                    t.w.s.validate_webhook = Mock()
                corrupt(t)
                before = t.w.snapshot()
                outcome = t.w.attempt(t.w.get, t.A, t.ta, connection)       # the corruption exists before the first read
                self.assertEqual(outcome[:2], (409, 'discord_connection_required'), label)
                self.assertEqual(t.w.snapshot(), before, 'a refused read changed state, audit or the Discord side')
                # Custody is proven before the fingerprint is looked at: a write is refused for custody, not for staleness.
                write = t.w.attempt(t.w.post, t.A, t.ta, connection,
                                    {'name': 'Intruder Weekly', 'fingerprint': control['fingerprint'], **BODY})
                self.assertEqual(write[:2], (409, 'discord_connection_required'), label)
                self.assertEqual(t.w.snapshot(), before)

    def test_every_webhook_custody_condition_alone_refuses_the_read_and_the_write(self):
        self.run_table(self.WEBHOOK, 'wa')

    def test_every_webhook_condition_that_custody_itself_checks_refuses_even_without_the_live_validator(self):
        self.run_table(self.WEBHOOK, 'wa', mock_live=True)

    def test_every_bot_custody_condition_alone_refuses_the_read_and_the_write(self):
        self.run_table(self.BOT, 'ia')

    def test_state_level_refusals_come_before_custody(self):
        for label, corrupt, status in (
                ('revoked card', lambda t: t.w.channel(t.A, t.wa.connection).update(revoked=True), 404),
                ('account block', lambda t: t.w.workspaces[t.A].state.update(accountBlock=True), 403),
                ('account deletion', lambda t: t.w.workspaces[t.A].state.update(accountDeletion=True), 409)):
            with self.subTest(label):
                t = self.world()
                corrupt(t)
                before = t.w.snapshot()
                outcome = t.w.attempt(t.w.get, t.A, t.ta, t.wa.connection)
                self.assertEqual(outcome[0], status)
                self.assertEqual(t.w.snapshot(), before)

    def test_a_card_of_another_platform_is_not_a_discord_connection(self):
        t = self.world()
        t.w.channel(t.A, t.wa.connection).update(platform='YouTube')
        before = t.w.snapshot()
        self.assertEqual(t.w.attempt(t.w.get, t.A, t.ta, t.wa.connection)[:2], (404, 'not_found'))
        self.assertEqual(t.w.snapshot(), before)

    def test_custody_itself_refuses_an_unknown_actor_and_a_non_authorizer_who_is_required_to_be_the_authorizer(self):
        t = self.world()
        other = t.w.member(t.A, t.w.user(3), 'admin')
        with t.w.s.local(t.A, t.ta) as (cur, state, actor):
            sender = SenderNames(t.w.s, t.A, t.ta, t.ia.connection)
            with self.assertRaises(AlphaError) as raised:
                sender.custody(cur, state, None)
            self.assertEqual((raised.exception.status, raised.exception.code), (403, 'permission_denied'))
            channel, envelope, stamp = sender.custody(cur, state, actor)           # the installer: fine
            self.assertTrue(envelope['_authorizing'])
        with t.w.s.local(t.A, other) as (cur, state, actor):
            sender = SenderNames(t.w.s, t.A, other, t.ia.connection)
            with self.assertRaises(AlphaError) as raised:
                sender.custody(cur, state, actor)
            self.assertEqual((raised.exception.status, raised.exception.code), (403, 'discord_sender_name_unavailable'))
            channel, envelope, stamp = sender.custody(cur, state, actor, require_authorizer=False)
            self.assertFalse(envelope['_authorizing'])

    def test_the_bot_authorizers_fresh_revalidation_gates_the_write_but_not_the_read(self):
        t = self.world()
        profile = t.w.get(t.A, t.ta, t.ia.connection)
        self.assertTrue(profile['editable'])
        t.w.set_row(t.A, t.identity()['id'], 3, NOW - 1)         # the linked identity's access has expired
        self.assertTrue(t.w.get(t.A, t.ta, t.ia.connection)['editable'], 'a read does not revalidate the authorizer')
        write = t.w.attempt(t.w.post, t.A, t.ta, t.ia.connection,
                            {'name': 'Fresh Bot', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(write[:2], (409, 'discord_connection_required'))
        self.assertEqual(t.w.hooks.guild_config['6400001'].patches, [])

    def test_a_non_authorizing_member_of_the_workspace_reads_a_reason_and_triggers_no_discord_request(self):
        t = self.world()
        other = t.w.member(t.A, t.w.user(3), 'admin', can_manage_connections=True)
        calls = len(t.w.hooks.calls)
        profile = t.w.get(t.A, other, t.ia.connection)
        self.assertEqual([r['code'] for r in profile['unavailable']], ['not_authorizing_member'])
        self.assertEqual(len(t.w.hooks.calls), calls)
        write = t.w.attempt(t.w.post, t.A, other, t.ia.connection,
                            {'name': 'Not Mine', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(write[:2], (403, 'discord_sender_name_unavailable'))
        self.assertEqual(t.w.hooks.guild_config['6400001'].patches, [])


if __name__ == '__main__':
    unittest.main()
