"""Customer sender names: frozen publication identity and scoped settings.

All transport and custody are synthetic; this never contacts Discord or a DB.
"""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import authorization as auth
from test_discord_multimode import webhook_fixture, social_fixture, session, HookWire, HOOK
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import (
    fixture, review, approve, SyntheticWire, APP, BOT, USER, GUILD, FIRST,
    NOW, WORKSPACE, ACTOR, GENERATION,
)


class FrozenWebhookName(unittest.TestCase):
    def test_customer_name_is_visible_in_review_and_frozen_wire(self):
        engine, state, channel, variant = webhook_fixture()
        channel['discordSenderName'] = 'D Festival 公告'
        manifest = review(engine, state, channel, variant)['manifest']
        self.assertEqual(manifest.get('discordSenderName'), 'D Festival 公告')
        self.assertEqual(auth.wire_content(manifest).get('username'), 'D Festival 公告')

    def test_saved_rename_cannot_silently_rewrite_an_approved_post(self):
        engine, state, channel, variant = webhook_fixture()
        channel['discordSenderName'] = 'Original brand'
        job = approve(engine, state, review(engine, state, channel, variant))
        channel['discordSenderName'] = 'New brand'
        self.assertTrue(auth.job_authorized(state, channel, job))
        self.assertEqual(auth.wire_content(job['manifest']).get('username'), 'Original brand')
        job['manifest']['discordSenderName'] = 'New brand'
        self.assertFalse(auth.job_authorized(state, channel, job))

    def test_legacy_approved_payload_is_byte_compatible(self):
        engine, state, channel, variant = webhook_fixture()
        m = review(engine, state, channel, variant)['manifest']
        self.assertNotIn('username', auth.wire_content(m))

    def test_bad_saved_names_cannot_enter_a_publication(self):
        for name in ('', 'a' * 81, 'bad\nname', 'bad\u202ename', 'Discord official', 'clyde', 42):
            with self.subTest(name=name):
                engine, state, channel, variant = webhook_fixture()
                channel['discordSenderName'] = name
                with self.assertRaises(AlphaError):
                    review(engine, state, channel, variant)

    def test_changing_brand_cannot_bypass_an_uncertain_send(self):
        engine, state, channel, variant = webhook_fixture()
        channel['discordSenderName'] = 'Original brand'
        job = approve(engine, state, review(engine, state, channel, variant))
        job.update(state='uncertain', discordDispatchIntents=[{'id': 'synthetic-intent'}])
        channel['discordSenderName'] = 'New brand'
        with self.assertRaises(AlphaError):
            review(engine, state, channel, variant)

    def test_actual_dispatch_and_receipt_keep_the_approved_name(self):
        engine, state, channel, variant = webhook_fixture()
        channel['discordSenderName'] = 'D Festival 公告'
        job = approve(engine, state, review(engine, state, channel, variant))
        m = job['manifest']
        social, provider, wire, _ = social_fixture()
        original = provider.transport
        def named_wire(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if method == 'POST':
                wire.message['author']['username'] = kwargs['body'].get('username')
            return response
        provider.transport = named_wire
        dispatch = social.prepare_discord_dispatch(m)
        dispatch['intent'] = {'id': 'synthetic-intent', 'manifestDigest': auth.digest(m), 'publicationId': job['id']}
        result = social.submit_discord_authorized(m, dispatch)
        self.assertEqual(result['state'], 'provider_accepted')
        posted = next(c[2]['body'] for c in wire.calls if c[0] == 'POST')
        self.assertEqual(posted.get('username'), 'D Festival 公告')
        observed = social.reconcile_discord(m, {**job, 'providerReference': result['reference']})
        self.assertEqual(observed['state'], 'verified')
        wire.message['author']['username'] = 'Wrong brand'
        self.assertNotEqual(social.reconcile_discord(m, {**job, 'providerReference': result['reference']})['state'], 'verified')

    def test_automation_keeps_its_approved_name_before_queue_commit(self):
        from postriff_phase2 import campaigns, publisher
        for original in (None, 'Approved brand', 'legacy-missing'):
            with self.subTest(original=original):
                engine, state, channel, variant = webhook_fixture()
                legacy = original == 'legacy-missing'
                original = None if legacy else original
                if original is not None: channel['discordSenderName'] = original
                target = auth.destination(state, channel, channel['defaultDestinationId'])
                task = {'id': 'synthetic-task', 'status': 'active', 'schedule': {'timeZone': 'UTC'}}
                item = {'key': 'synthetic-item', 'platform': 'Discord', 'channelId': channel['id'],
                        'variantId': variant['id'], 'state': 'ready_for_review', 'publishAt': NOW + 300}
                run = {'id': 'synthetic-run', 'taskId': task['id'], 'items': [item]}
                root = campaigns._root(state); root['recurringTasks'].append(task); root['occurrences'].append(run)
                body = {'occurrenceId': run['id'], 'itemKey': item['key'], 'decision': 'approve',
                        'confirmed': True, 'variantRevision': 1, 'excludedUnknowns': [], 'acknowledgedWarnings': [],
                        'destinationId': target['id'], 'destinationGeneration': target['resourceGeneration'],
                        'publishAt': NOW + 300, 'discordSenderName': original}
                campaigns._decide(state, root, body, ACTOR, NOW)
                if legacy: item['decision'].pop('discordSenderName')
                channel['discordSenderName'] = 'New future brand'
                queued = publisher.commit(engine, state, ACTOR, {'occurrenceId': run['id'], 'itemKey': item['key']}, NOW + 60)
                job = next(j for j in state['phase2']['jobs'] if j['id'] == queued['jobId'])
                self.assertEqual(auth.wire_content(job['manifest']).get('username'), original)
                self.assertTrue(auth.job_authorized(state, channel, job))
                self.assertEqual(channel['discordSenderName'], 'New future brand')


class SettingsHarness:
    def __init__(self, kind='webhook'):
        self.s, _ = service()
        _, self.state, self.channel, _ = webhook_fixture() if kind == 'webhook' else fixture()
        self.kind = kind
        self.channel.update(discordConnectionKind=kind if kind == 'webhook' else 'installation',
                            discordAuthorizedBy=ACTOR, discordLinkedUserId=USER)
        if kind == 'webhook':
            self.channel.update(providerAccountId=HOOK, discordWebhookChannelId=FIRST)
        else:
            self.channel['discordIdentityConnectionId'] = 'synthetic-identity'
            self.state['phase2']['discordIdentityLinks'] = [{
                'id': 'synthetic-identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR,
                'userId': USER, 'status': 'linked', 'authorizationGeneration': 'synthetic-identity-generation',
            }]
        self.envelope = session() if kind == 'webhook' else {
            'v': 2, 'kind': 'installation', 'workspaceId': WORKSPACE, 'memberId': ACTOR,
            'applicationId': APP, 'guild': GUILD, 'user': USER, 'channel': FIRST,
            'connectionId': self.channel['id'], 'identityConnectionId': 'synthetic-identity',
            'identityGeneration': 'synthetic-identity-generation', 'botUserId': BOT,
        }
        self.envelope['connectionId'] = self.channel['id']
        self.actor = ACTOR
        self.nick = 'Rafii'
        self.user_permissions = (1 << 27) | (1 << 5)
        self.bot_permissions = (1 << 26) | (1 << 5)
        self.patches = []
        self.after_read = None
        self.before_patch = None
        self.cur = Mock()
        self.s.oauth.repository = SimpleNamespace(assert_fresh=Mock())
        self.s.oauth.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda *_: None))
        @contextmanager
        def local(workspace, token):
            yield self.cur, self.state, self.actor
        self.s.local = local
        self.s.read_credential = lambda *_: (
            ('synthetic-ciphertext', 'synthetic-key', None, NOW + 3600, GENERATION,
             self.channel['scopes'], self.channel['providerAccountId']), copy.deepcopy(self.envelope))
        self.s.validate_webhook = Mock()
        self.s.validate_installation = Mock()
        self.s.reverify_installation = Mock()
        self.s.reverify_webhook = Mock()
        self.s.adapter.webhook_v1_enabled = True
        self.wire = HookWire() if kind == 'webhook' else SyntheticWire()
        def transport(method, url, **kwargs):
            path = urlsplit(url).path.removeprefix('/api/v10')
            if path == f'/guilds/{GUILD}/members/@me':
                if self.before_patch is not None:
                    action, self.before_patch = self.before_patch, None
                    action()
                self.patches.append((method, path, copy.deepcopy(kwargs.get('body'))))
                self.nick = kwargs['body']['nick']
                return {'status': 200, 'body': {'user': {'id': BOT, 'username': 'Rafii'}, 'nick': self.nick, 'roles': []}}
            response = self.wire(method, url, **kwargs)
            if path == f'/guilds/{GUILD}':
                response['body']['roles'] = [
                    {'id': GUILD, 'permissions': str((1 << 10) | (1 << 11))},
                    {'id': '11223344', 'permissions': str(self.user_permissions)},
                    {'id': '22334455', 'permissions': str(self.bot_permissions)},
                ]
            if path == f'/guilds/{GUILD}/members/{USER}':
                response['body']['roles'] = ['11223344']
            if path == f'/guilds/{GUILD}/members/{BOT}':
                response['body'].update(nick=self.nick, roles=['22334455'])
                response['body']['user']['username'] = 'Rafii'
            if self.after_read is not None:
                action, self.after_read = self.after_read, None
                action()
            return response
        self.s.adapter.transport = transport
        # External resource verification is already covered by the existing
        # OAuth/Webhook suites; settings must still recheck those boundaries.
        self.s.adapter.webhook_authorizer = Mock(return_value=None)

    def call(self, case, operation, *args):
        method = getattr(self.s, operation, None)
        case.assertTrue(callable(method), 'Discord customer sender-name settings are missing')
        with patch('postriff_phase2.hosted.audit'):
            return method(WORKSPACE, 'synthetic-session', self.channel['id'], *args)


class SenderSettings(unittest.TestCase):
    def test_webhook_name_is_scoped_to_one_connection_without_provider_mutation(self):
        h = SettingsHarness()
        unrelated = copy.deepcopy(h.channel)
        unrelated.update(id='another-customer-connection', discordSenderName='Other brand')
        h.state['phase2']['channels'].append(unrelated)
        current = h.call(self, 'sender_profile')
        updated = h.call(self, 'set_sender_name', {'name': 'D Festival 公告', 'fingerprint': current['fingerprint'], 'confirmed': True})
        self.assertEqual(updated['name'], 'D Festival 公告')
        self.assertEqual(h.channel['discordSenderName'], 'D Festival 公告')
        self.assertEqual(unrelated['discordSenderName'], 'Other brand')
        self.assertEqual(h.patches, [])

    def test_same_server_bot_nickname_requires_explicit_shared_scope_confirmation(self):
        h = SettingsHarness('bot')
        current = h.call(self, 'sender_profile')
        body = {'name': 'D Festival 助手', 'fingerprint': current['fingerprint'], 'confirmed': True}
        with self.assertRaises(AlphaError):
            h.call(self, 'set_sender_name', body)
        self.assertEqual(h.patches, [])
        result = h.call(self, 'set_sender_name', {**body, 'sharedServerConfirmed': True})
        self.assertEqual(result['name'], 'D Festival 助手')
        self.assertEqual(h.patches, [('PATCH', f'/guilds/{GUILD}/members/@me', {'nick': 'D Festival 助手'})])

    def test_wrong_workspace_or_member_cannot_change_sender(self):
        for corruption in ('workspace', 'member', 'generation', 'credential'):
            with self.subTest(corruption=corruption):
                h = SettingsHarness()
                current = h.call(self, 'sender_profile')
                if corruption == 'workspace': h.state['workspace']['id'] = 'other-workspace'
                if corruption == 'member': h.actor = 'other-member'
                if corruption == 'generation': h.channel['discordAuthorizationGeneration'] = 'changed-generation'
                if corruption == 'credential': h.envelope['workspaceId'] = 'other-workspace'
                with self.assertRaises(AlphaError):
                    h.call(self, 'set_sender_name', {'name': 'Wrong brand', 'fingerprint': current['fingerprint'], 'confirmed': True})
                self.assertNotIn('discordSenderName', h.channel)
                self.assertEqual(h.patches, [])

    def test_stale_editor_cannot_overwrite_a_newer_saved_name(self):
        h = SettingsHarness()
        current = h.call(self, 'sender_profile')
        h.call(self, 'set_sender_name', {'name': 'First save', 'fingerprint': current['fingerprint'], 'confirmed': True})
        with self.assertRaises(AlphaError):
            h.call(self, 'set_sender_name', {'name': 'Stale save', 'fingerprint': current['fingerprint'], 'confirmed': True})
        self.assertEqual(h.channel['discordSenderName'], 'First save')

    def test_revocation_during_provider_read_stops_change(self):
        h = SettingsHarness()
        current = h.call(self, 'sender_profile')
        h.after_read = lambda: h.channel.update(revoked=True)
        with self.assertRaises(AlphaError):
            h.call(self, 'set_sender_name', {'name': 'Blocked brand', 'fingerprint': current['fingerprint'], 'confirmed': True})
        self.assertNotIn('discordSenderName', h.channel)
        self.assertEqual(h.patches, [])

    def test_bot_permissions_are_live_and_specific_to_nicknames(self):
        for subject in ('user', 'bot'):
            with self.subTest(subject=subject):
                h = SettingsHarness('bot')
                current = h.call(self, 'sender_profile')
                setattr(h, subject + '_permissions', 1 << 5)  # Manage Server is insufficient.
                with self.assertRaises(AlphaError):
                    h.call(self, 'set_sender_name', {'name': 'Blocked', 'fingerprint': current['fingerprint'],
                        'confirmed': True, 'sharedServerConfirmed': True})
                self.assertEqual(h.patches, [])

    def test_invalid_or_unapproved_input_never_mutates_provider(self):
        for kind, extra in [('bot', {'name': 'a' * 33}), ('webhook', {'name': 'a' * 81}),
                            ('bot', {'name': 'bad\u202ename'}), ('webhook', {'confirmed': False}),
                            ('bot', {'avatarUrl': 'https://example.invalid/avatar.png'})]:
            with self.subTest(kind=kind, extra=extra):
                h = SettingsHarness(kind)
                current = h.call(self, 'sender_profile')
                with self.assertRaises(AlphaError):
                    h.call(self, 'set_sender_name', {'name': 'Valid name', 'fingerprint': current['fingerprint'],
                        'confirmed': True, 'sharedServerConfirmed': True, **extra})
                self.assertEqual(h.patches, [])
                self.assertNotIn('discordSenderName', h.channel)

    def test_fresh_session_is_required_before_any_write(self):
        h = SettingsHarness('bot')
        current = h.call(self, 'sender_profile')
        h.s.oauth.repository.assert_fresh.side_effect = AlphaError('Verify your session again.', 403)
        with self.assertRaises(AlphaError):
            h.call(self, 'set_sender_name', {'name': 'Blocked', 'fingerprint': current['fingerprint'],
                'confirmed': True, 'sharedServerConfirmed': True})
        self.assertEqual(h.patches, [])

    def test_bot_change_is_reserved_before_the_provider_write(self):
        h = SettingsHarness('bot')
        current = h.call(self, 'sender_profile')
        body = {'name': 'First editor', 'fingerprint': current['fingerprint'], 'confirmed': True, 'sharedServerConfirmed': True}
        def competing_editor():
            self.assertIn('discordSenderEdit', h.channel)
            with self.assertRaises(AlphaError):
                h.call(self, 'set_sender_name', {**body, 'name': 'Competing editor'})
        h.before_patch = competing_editor
        h.call(self, 'set_sender_name', body)
        self.assertEqual(len(h.patches), 1)
        self.assertNotIn('discordSenderEdit', h.channel)

    def test_uncertain_bot_change_requires_later_explicit_read_before_new_edit(self):
        h = SettingsHarness('bot')
        current = h.call(self, 'sender_profile')
        body = {'name': 'Uncertain editor', 'fingerprint': current['fingerprint'], 'confirmed': True, 'sharedServerConfirmed': True}
        def uncertain(): raise TimeoutError('Synthetic ambiguous write')
        h.before_patch = uncertain
        with self.assertRaises(AlphaError):
            h.call(self, 'set_sender_name', body)
        self.assertIn('discordSenderEdit', h.channel)
        with self.assertRaises(AlphaError): h.call(self, 'sender_profile')
        h.s.oauth.clock = lambda: NOW + 121
        with self.assertRaises(AlphaError): h.call(self, 'set_sender_name', body)
        recovered = h.call(self, 'sender_profile')
        self.assertEqual(recovered['name'], h.nick)
        self.assertNotIn('discordSenderEdit', h.channel)
        self.assertNotEqual(recovered['fingerprint'], current['fingerprint'])
        self.assertEqual(h.patches, [])

    def test_late_recovery_read_cannot_clear_a_replacement_claim(self):
        h = SettingsHarness('bot')
        h.channel['discordSenderEdit'] = {'id': 'expired-edit', 'name': 'Old', 'expiresAt': NOW - 1}
        replacement = {'id': 'new-edit', 'name': 'New', 'expiresAt': NOW + 120}
        h.s.reverify_installation.side_effect = lambda *_args, **_kwargs: h.channel.update(discordSenderEdit=replacement)
        with self.assertRaises(AlphaError): h.call(self, 'sender_profile')
        self.assertEqual(h.channel['discordSenderEdit'], replacement)

    def test_uncertain_bot_edit_recovers_with_the_real_shared_rate_algorithm(self):
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget
        from test_discord_rate_limits import MemoryLedger, synthetic_policy
        h = SettingsHarness('bot')
        ledger = MemoryLedger(now=NOW)
        h.cur = ledger
        h.s.save_state = Mock()  # Workspace storage; rate SQL uses the real algorithm.
        h.s.oauth.clock = lambda: ledger.now
        h.s.adapter.rate_v1_enabled = True
        h.s.adapter.rate_limiter = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy(NOW))
        transport = h.s.adapter.transport
        def rated(method, url, **kwargs):
            result = transport(method, url, **kwargs)
            result['headers'] = {'X-RateLimit-Bucket': 'synthetic-' + method, 'X-RateLimit-Limit': '100',
                                 'X-RateLimit-Remaining': '90', 'X-RateLimit-Reset-After': '1'}
            return result
        h.s.adapter.transport = rated
        current = h.call(self, 'sender_profile')
        def timeout(): raise TimeoutError('Synthetic ambiguous nickname')
        h.before_patch = timeout
        with self.assertRaises(AlphaError):
            h.call(self, 'set_sender_name', {'name': 'Uncertain', 'fingerprint': current['fingerprint'],
                'confirmed': True, 'sharedServerConfirmed': True})
        admission_id = h.channel['discordSenderEdit']['rateAdmissionId']
        admission_expiry = h.channel['discordSenderEdit']['rateExpiresAt']
        self.assertEqual(ledger.admissions[admission_id]['state'], 'uncertain')
        ledger.now += 121
        recovered = h.call(self, 'sender_profile')
        self.assertEqual(ledger.admissions[admission_id]['state'], 'observed')
        self.assertIsNone(ledger.admissions[admission_id]['status'])
        # A stalled old writer may resume after recovery; terminal cleanup is
        # idempotent and must not degrade the shared provider adapter.
        from postriff_phase2.discord.rate_limits import Permit, _digest
        h.s.adapter.rate_limiter.abandon_unsent_nickname(Permit(admission_id,
            h.s.adapter.rate_limiter.application_key, 'PATCH', _digest(f'/guilds/{GUILD}/members/@me'),
            h.s.adapter._rate_identity('bot'), None, admission_expiry))
        saved = h.call(self, 'set_sender_name', {'name': 'Next intentional edit', 'fingerprint': recovered['fingerprint'],
            'confirmed': True, 'sharedServerConfirmed': True})
        self.assertEqual(saved['name'], 'Next intentional edit')
        self.assertEqual(len(h.patches), 1)


class SenderTransportBoundary(unittest.TestCase):
    def test_guard_is_checked_after_shared_rate_admission(self):
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget
        from test_discord_rate_limits import MemoryLedger, synthetic_policy
        h = SettingsHarness('bot')
        h.s.adapter.rate_v1_enabled = True
        ledger = MemoryLedger()
        h.s.adapter.rate_limiter = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy())
        consent = Mock(side_effect=[True, False])
        with self.assertRaises(AlphaError):
            h.s.adapter._bot('PATCH', f'/guilds/{GUILD}/members/@me', body={'nick': 'Blocked'}, write_authorize=consent)
        self.assertEqual(consent.call_count, 2)
        self.assertEqual(h.patches, [])
        self.assertEqual([row['state'] for row in ledger.admissions.values()], ['blocked'])
        ledger.now += 100
        self.assertEqual(h.s.adapter._bot('GET', f'/guilds/{GUILD}')['status'], 200)

    def test_guard_cannot_be_attached_to_global_bot_identity(self):
        h = SettingsHarness('bot')
        with self.assertRaises(AlphaError):
            h.s.adapter._bot('PATCH', '/users/@me', body={'username': 'Wrong'}, write_authorize=lambda: True)
        self.assertEqual(h.patches, [])

    def test_nickname_write_cannot_skip_its_authorization_guard(self):
        h = SettingsHarness('bot')
        with self.assertRaises(AlphaError):
            h.s.adapter._bot('PATCH', f'/guilds/{GUILD}/members/@me', body={'nick': 'Blocked'})
        self.assertEqual(h.patches, [])

    def test_authenticated_route_and_mutation_guard(self):
        import io
        from postriff_phase2.hosted_app import HostedApplication
        from postriff_phase2.security_gate import capability_for
        connection = Mock()
        connection.sender_profile.return_value = {'name': 'Read name'}
        connection.set_sender_name.return_value = {'name': 'Saved name'}
        app = HostedApplication(service=SimpleNamespace(oauth=SimpleNamespace(discord_connections=connection)))
        path = f'/api/workspaces/{WORKSPACE}/channels/synthetic-channel/discord-sender-name'
        token = 'synthetic-session-' + 'x' * 24
        for method, guarded, expected in [('GET', False, 200), ('POST', False, 403), ('POST', True, 200)]:
            with self.subTest(method=method, guarded=guarded):
                body = json.dumps({'name': 'Saved name', 'confirmed': True}).encode()
                environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'HTTP_HOST': 'rafii.example.invalid',
                    'wsgi.url_scheme': 'https', 'HTTP_AUTHORIZATION': 'Bearer ' + token,
                    'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
                if guarded: environ['HTTP_X_POSTRIFF_REQUEST'] = 'founder-alpha'
                statuses = []
                with patch('postriff_phase2.security_gate.require'):
                    result = b''.join(app._handle(environ, lambda status, _: statuses.append(int(status.split()[0]))))
                self.assertEqual(statuses, [expected], result)
        connection.sender_profile.assert_called_once_with(WORKSPACE, token, 'synthetic-channel')
        connection.set_sender_name.assert_called_once_with(WORKSPACE, token, 'synthetic-channel', {'name': 'Saved name', 'confirmed': True})
        self.assertEqual(capability_for('POST', path.strip('/').split('/')), 'connections')


if __name__ == '__main__':
    unittest.main()
