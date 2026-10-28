"""Synthetic real review/approval/transport boundaries; never uses live Discord."""
import copy
import json
from secrets import token_urlsafe
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import authorization as auth
from postriff_phase2.discord.oauth import validate_context
from postriff_phase2.discord.rate_limits import route_identity
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import fixture, review, approve, APP, USER, GUILD, FIRST, NOW, WORKSPACE, ACTOR, GENERATION

HOOK = '66112233'
# Generated only in the synthetic process: never commit a token-shaped literal.
SECRET = token_urlsafe(32)


def webhook_fixture():
    engine, state, channel, variant = fixture()
    channel.update(id='discord-webhook-synthetic', scopes=['identify', 'webhook.incoming'], discordConnectionKind='webhook')
    channel['discordDestinations'] = []
    evidence = {'senderKind': 'webhook', 'credentialKind': 'webhook', 'webhookId': HOOK,
                'applicationId': APP, 'linkedUserId': USER, 'guildId': GUILD, 'channelId': FIRST,
                'guildName': GUILD, 'channelName': FIRST, 'kind': 'webhook'}
    auth.register_destination(state, channel, evidence, GENERATION, ACTOR, NOW)
    return engine, state, channel, variant


def session():
    return {'v': 2, 'kind': 'webhook', 'applicationId': APP, 'webhookId': HOOK, 'secret': SECRET,
            'guild': GUILD, 'channel': FIRST, 'user': USER, 'memberId': ACTOR, 'workspaceId': WORKSPACE, 'destinationAuthorized': True}


class HookWire:
    def __init__(self):
        self.calls = []; self.status = 200; self.fail_create = False; self.message = None
    def __call__(self, method, url, **kwargs):
        path = urlsplit(url).path.removeprefix('/api/v10')
        self.calls.append((method, url, kwargs))
        if method == 'POST':
            if self.fail_create: raise TimeoutError('synthetic unknown create')
            self.message = {'id': '99112233', 'channel_id': FIRST, 'webhook_id': HOOK,
                            'author': {'id': HOOK, 'bot': True}, 'content': kwargs['body']['content'],
                            'mentions': [], 'mention_roles': [], 'mention_everyone': False, 'attachments': [], 'embeds': []}
            return {'status': self.status, 'body': self.message if self.status == 200 else {}}
        if '/messages/' in path: return {'status': 200, 'body': self.message}
        if not path.startswith('/webhooks/'):
            from test_discord_publish_authorization import SyntheticWire
            return SyntheticWire()(method, url, **kwargs)
        return {'status': 200, 'body': {'id': HOOK, 'application_id': APP, 'guild_id': GUILD,
                                      'channel_id': FIRST, 'type': 1, 'name': 'Rafii'}}


def social_fixture():
    wire = HookWire()
    provider = DiscordProvider(APP, 'synthetic-oauth-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=wire, production_reviewed=True)
    provider.authorization_v2_enabled = provider.connections_v2_enabled = True
    provider.webhook_v1_enabled = True
    grant = {'provider': 'discord', 'accessToken': json.dumps(session()), 'scopes': ['identify', 'webhook.incoming'], 'authorizationGeneration': GENERATION}
    oauth = SimpleNamespace(discord_grant_for_worker=lambda *_: copy.deepcopy(grant))
    social = HostedSocial(oauth, {'discord': provider})
    return social, provider, wire, grant


class MultiModeTests(unittest.TestCase):
    def test_webhook_v2_state_has_distinct_purpose_and_compatibility(self):
        context = {'v': 2, 'purpose': 'webhook', 'workspaceId': WORKSPACE, 'memberId': ACTOR,
                   'applicationId': APP, 'redirectUri': 'https://rafii.example.invalid/callback', 'pkceVerifier': 'x' * 43}
        self.assertEqual(validate_context(context, WORKSPACE, ACTOR, SimpleNamespace(client_id=APP), context['redirectUri'], ['identify', 'webhook.incoming'], 'publish'), 'webhook')
        for key, value in [('memberId', 'other'), ('workspaceId', 'other'), ('applicationId', '888888')]:
            with self.subTest(key=key), self.assertRaises(AlphaError):
                validate_context({**context, key: value}, WORKSPACE, ACTOR, SimpleNamespace(client_id=APP), context['redirectUri'], ['identify', 'webhook.incoming'], 'publish')

    def test_distinct_sender_bound_in_real_review_and_approval(self):
        engine, state, channel, variant = webhook_fixture()
        entry = review(engine, state, channel, variant)
        self.assertEqual(entry['manifest']['senderKind'], 'webhook')
        self.assertEqual(entry['manifest']['discord']['target']['webhookId'], HOOK)
        self.assertNotIn('botUserId', entry['manifest']['discord']['target'])
        job = approve(engine, state, entry)
        self.assertTrue(auth.job_authorized(state, channel, job))
        job['manifest']['senderKind'] = 'bot'
        self.assertFalse(auth.job_authorized(state, channel, job))

    def test_prepare_and_same_authorized_dispatch_readback(self):
        engine, state, channel, variant = webhook_fixture()
        entry = review(engine, state, channel, variant); job = approve(engine, state, entry)
        social, provider, wire, grant = social_fixture()
        manifest = job['manifest']
        self.assertEqual(social.submit(manifest)['state'], 'held')
        self.assertEqual(wire.calls, [])
        prepared = social.prepare_discord_dispatch(manifest)
        self.assertFalse(any(c[0] == 'POST' for c in wire.calls))
        # Real worker supplies this already committed exact intent, never HTTP input.
        dispatch = {**prepared, 'intent': {'id': 'synthetic-lease', 'manifestDigest': auth.digest(manifest), 'publicationId': job['id']}}
        result = social.submit_discord_authorized(manifest, dispatch)
        self.assertEqual(result['state'], 'provider_accepted')
        post = next(c for c in wire.calls if c[0] == 'POST')
        self.assertTrue(post[1].endswith('?wait=true'))
        self.assertEqual(post[2]['body']['allowed_mentions'], {'parse': []})
        self.assertNotIn('Authorization', post[2].get('headers', {}))
        self.assertFalse(any(c[0] != 'GET' and not urlsplit(c[1]).path.startswith('/api/v10/webhooks/') for c in wire.calls))
        verified = social.reconcile_discord(manifest, {**job, 'providerReference': result['reference']})
        self.assertEqual(verified['state'], 'verified')
        self.assertNotIn(SECRET, json.dumps(result) + json.dumps(verified))

    def test_webhook_payload_rejects_implicit_extra_effects(self):
        engine, state, channel, variant = webhook_fixture()
        manifest = review(engine, state, channel, variant)['manifest']
        for field, value in [('media', [{'mime': 'image/png'}]), ('engagementReply', {'parentMessageId': FIRST}),
                             ('publishOptions', {'thread_id': FIRST}), ('publishOptions', {'username': 'Personal user'})]:
            with self.subTest(field=field), self.assertRaises(AlphaError): auth.wire_content({**manifest, field: value})

    def test_unknown_create_never_blindly_reconciles_by_post(self):
        engine, state, channel, variant = webhook_fixture()
        job = approve(engine, state, review(engine, state, channel, variant)); m = job['manifest']
        social, provider, wire, grant = social_fixture()
        prepared = social.prepare_discord_dispatch(m); wire.fail_create = True
        result = social.submit_discord_authorized(m, {**prepared, 'intent': {'id': 'lease', 'manifestDigest': auth.digest(m), 'publicationId': job['id']}})
        self.assertEqual(result['state'], 'uncertain')
        for _ in range(2): self.assertEqual(social.reconcile_discord(m, job)['state'], 'uncertain')
        self.assertEqual(sum(c[0] == 'POST' for c in wire.calls), 1)
        job.update(state='uncertain', discordDispatchIntents=[{'id': 'lease'}])
        with self.assertRaises(AlphaError): review(engine, state, channel, variant)

    def test_webhook_rate_templates_are_secret_free_and_exact(self):
        template, major = route_identity('POST', f'/webhooks/{HOOK}/{SECRET}?wait=true')
        self.assertEqual(template, 'POST:/webhooks/{id}/{token}')
        self.assertNotIn(SECRET, template + major)
        for path in [f'/webhooks/{HOOK}/{SECRET}?thread_id={FIRST}', f'/webhooks/{HOOK}/{SECRET}?wait=false', f'https://evil.invalid/{HOOK}']:
            with self.subTest(path=path), self.assertRaises(AlphaError): route_identity('POST', path)

    def test_credential_kind_and_workspace_cannot_be_substituted(self):
        engine, state, channel, variant = webhook_fixture(); m = review(engine, state, channel, variant)['manifest']
        social, provider, wire, grant = social_fixture()
        self.assertTrue(auth.grant_matches(m, grant, session()))
        for change in [{'kind': 'installation'}, {'workspaceId': 'other'}, {'webhookId': FIRST}, {'applicationId': USER}, {'user': APP}]:
            self.assertFalse(auth.grant_matches(m, grant, {**session(), **change}))
        channel['revoked'] = True
        self.assertFalse(auth.manifest_current(state, channel, m))

if __name__ == '__main__': unittest.main()

class WorkerAndRateTests(unittest.TestCase):
    def test_default_flags_off_and_webhook_rate_identity(self):
        from postriff_phase2.discord.rate_limits import RequestIdentity
        p = DiscordProvider(APP, 'synthetic', 'synthetic', 'https://rafii.example.invalid')
        self.assertFalse(p.webhook_v1_enabled)
        identity = RequestIdentity.make(APP, 'webhook', SECRET)
        self.assertEqual(identity.kind, 'webhook')
        self.assertNotIn(SECRET, repr(identity))

    def test_real_worker_due_time_cancel_and_unknown(self):
        from unittest.mock import patch
        from test_discord_worker_lifecycle import MemoryDatabase
        from postriff_phase2.hosted_worker import PostgresWorker
        from postriff_phase2 import security_holds
        for scenario in ('due', 'canceled', 'unknown', 'revoked', 'aged'):
            with self.subTest(scenario=scenario):
                engine, state, channel, variant = webhook_fixture()
                if scenario == 'aged': channel.update(qualification='server_verified', evidenceSource='live_provider')
                job = approve(engine, state, review(engine, state, channel, variant, at=NOW + (7200 if scenario == 'aged' else 300)))
                social, provider, wire, grant = social_fixture()
                if scenario == 'canceled': engine.apply_phase2(None, state, 'cancel', {'jobId': job['id']}, {'user_id': ACTOR})
                if scenario == 'revoked': channel['revoked'] = True
                if scenario == 'unknown': wire.fail_create = True
                class CompleteDatabase(MemoryDatabase):
                    def execute(self, sql, params=()):
                        if sql.startswith(('SAVEPOINT learning_', 'RELEASE SAVEPOINT learning_', 'INSERT INTO public.pr_learning_events', 'SAVEPOINT product_event_', 'RELEASE SAVEPOINT product_event_',
                                           'SAVEPOINT telemetry_journal_', 'RELEASE SAVEPOINT telemetry_journal_',
                                           'INSERT INTO public.pr_product_events', 'INSERT INTO public.pr_audit_events')):
                            self.rows, self.rowcount = [], 1
                            self.queries.append((sql, params))
                        else: super().execute(sql, params)
                db = CompleteDatabase(state)
                def custody(workspace, connection, **kwargs):
                    if scenario == 'revoked': raise AlphaError('synthetic revoked', 409)
                    return copy.deepcopy(grant)
                social.oauth.discord_grant_for_worker = custody
                worker = PostgresWorker(db.connection, social, clock=lambda: db.now, worker_id='synthetic-worker', discord_workers=True)
                with patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')}), patch('postriff_phase2.billing.require_publishing'):
                    db.now = NOW + 100
                    worker.tick_discord(max_jobs=1)
                    self.assertFalse(any(c[0] == 'POST' for c in wire.calls))
                    db.now = NOW + (7201 if scenario == 'aged' else 301)
                    worker.tick_discord(max_jobs=1)
                    db.now += 61
                    worker.tick_discord(max_jobs=1)
                saved = db.state['phase2']['jobs'][0]
                if scenario in ('due', 'aged'): self.assertEqual(saved['state'], 'verified')
                elif scenario == 'unknown': self.assertEqual(saved['state'], 'uncertain')
                self.assertEqual(sum(c[0] == 'POST' for c in wire.calls), 0 if scenario in ('canceled', 'revoked') else 1)

class WebhookCustodyTests(unittest.TestCase):
    def test_real_callback_vault_independent_passthrough_proof_and_replay(self):
        from test_discord_oauth_lifecycle import installation_callback
        from unittest.mock import patch
        s, old_wire, state, row, cur = installation_callback()
        s.adapter.webhook_v1_enabled = True
        ctx = {'v': 2, 'purpose': 'webhook', 'workspaceId': WORKSPACE, 'memberId': ACTOR, 'applicationId': APP,
               'redirectUri': s.oauth.callback_uri('discord'), 'pkceVerifier': 'x' * 64, 'expectedChannelId': FIRST}
        encrypted, key = s.oauth.vault.encrypt(json.dumps(ctx))
        row[4:7] = [['identify', 'webhook.incoming'], encrypted, key]
        hookwire = HookWire()
        def wire(method, url, **kwargs):
            path = urlsplit(url).path.removeprefix('/api/v10')
            if path == '/oauth2/token':
                self.assertEqual(kwargs['form']['code_verifier'], 'x' * 64)
                return {'status': 200, 'body': {'token_type': 'Bearer', 'access_token': 'synthetic-bearer', 'expires_in': 3600,
                    'scope': 'webhook.incoming', 'webhook': {'id': HOOK, 'token': SECRET, 'type': 1, 'guild_id': GUILD, 'channel_id': FIRST, 'application_id': APP}}}
            if path == '/oauth2/@me': return {'status': 200, 'body': {'application': {'id': APP}, 'user': {'id': USER}, 'scopes': ['identify']}}
            if path == '/users/@me': return {'status': 200, 'body': {'id': USER}}
            return hookwire(method, url, **kwargs)
        s.adapter.transport = wire
        with patch('postriff_phase2.hosted.audit'):
            result = s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'webhook-code', iss='https://discord.com')
            with self.assertRaises(AlphaError): s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'webhook-code', iss='https://discord.com')
        self.assertTrue(result['connected']); self.assertEqual(result['senderKind'], 'webhook')
        channel = state['phase2']['channels'][0]
        # A webhook created independently of a selected personal identity
        # must not accidentally become dependent on another member's link.
        self.assertNotIn('discordIdentityConnectionId', channel)
        self.assertFalse(channel['capabilityVerified']); self.assertEqual(channel['discordDestinations'], [])
        params = next(c.args[1] for c in cur.execute.call_args_list if c.args[0].startswith('INSERT INTO public.pr_encrypted_credentials'))
        envelope = json.loads(s.oauth.vault.decrypt(params[3], params[5]))
        self.assertEqual(envelope['kind'], 'webhook'); self.assertEqual(envelope['secret'], SECRET)
        self.assertEqual(envelope['authorization'], {'bearerScopes': ['identify'], 'webhookScopes': ['webhook.incoming']})
        self.assertNotIn(SECRET, json.dumps(state)); self.assertNotIn('synthetic-bearer', json.dumps(envelope))
        self.assertFalse(any(c[0] == 'POST' for c in hookwire.calls))

    def test_webhook_selected_identity_disconnect_revokes_dependent_channel(self):
        # A selected identity authorizes the OAuth callback; disconnecting it
        # must fence the corresponding webhook, not merely the installation.
        from test_discord_oauth_lifecycle import installation_callback
        from unittest.mock import patch
        s, _, state, row, cur = installation_callback()
        s.adapter.webhook_v1_enabled = True
        record = state['phase2']['discordIdentityLinks'][0]
        record['userId'] = USER
        ctx = {'v': 2, 'purpose': 'webhook', 'workspaceId': WORKSPACE, 'memberId': ACTOR,
               'applicationId': APP, 'redirectUri': s.oauth.callback_uri('discord'),
               'pkceVerifier': 'x' * 64, 'expectedChannelId': FIRST,
               'identityConnectionId': record['id'], 'identityGeneration': record['authorizationGeneration'],
               'expectedUserId': USER}
        encrypted, key = s.oauth.vault.encrypt(json.dumps(ctx))
        row[4:7] = [['identify', 'webhook.incoming'], encrypted, key]
        wire = HookWire()
        def responder(method, url, **kwargs):
            path = urlsplit(url).path.removeprefix('/api/v10')
            if path == '/oauth2/token':
                return {'status': 200, 'body': {'token_type': 'Bearer', 'access_token': 'synthetic-bearer',
                    'expires_in': 3600, 'scope': 'webhook.incoming',
                    'webhook': {'id': HOOK, 'token': SECRET, 'type': 1, 'guild_id': GUILD,
                                'channel_id': FIRST, 'application_id': APP}}}
            if path == '/oauth2/@me':
                return {'status': 200, 'body': {'application': {'id': APP}, 'user': {'id': USER}, 'scopes': ['identify']}}
            if path == '/users/@me': return {'status': 200, 'body': {'id': USER}}
            return wire(method, url, **kwargs)
        s.adapter.transport = responder
        with patch('postriff_phase2.hosted.audit'):
            s.complete(WORKSPACE, 'synthetic-session', 's' * 32, 'webhook-code', iss='https://discord.com')
        channel = state['phase2']['channels'][0]
        self.assertEqual(channel.get('discordIdentityConnectionId'), record['id'])
        saved = next(c.args[1] for c in cur.execute.call_args_list if c.args[0].startswith('INSERT INTO public.pr_encrypted_credentials'))
        envelope = json.loads(s.oauth.vault.decrypt(saved[3], saved[5]))
        self.assertEqual(envelope['identityConnectionId'], record['id'])
        self.assertEqual(envelope['identityGeneration'], record['authorizationGeneration'])
        self.assertNotIn('synthetic-bearer', json.dumps(envelope))
        s.invalidate_dependents(cur, WORKSPACE, state, record['id'])
        self.assertTrue(channel['revoked'])
        self.assertFalse(channel['capabilityVerified'])
        self.assertFalse(any(c[0] == 'POST' and '/webhooks/' in c[1] for c in wire.calls))

    def test_reverify_entry_exists_for_real_webhook_connections(self):
        from postriff_phase2.discord.oauth import DiscordConnections
        self.assertTrue(callable(getattr(DiscordConnections, 'reverify_webhook', None)), 'webhook lifecycle must have a real verification path')

class LegacyFencingTests(unittest.TestCase):
    def test_legacy_bot_unknown_cannot_get_new_sender_review_to_resubmit(self):
        engine, state, channel, variant = fixture()
        entry = review(engine, state, channel, variant)
        m = entry['manifest']; t = m['discord']['target']
        legacy_digest = auth.digest({'workspaceId': WORKSPACE, 'applicationId': APP, 'botUserId': t['botUserId'],
                                     'guildId': GUILD, 'channelId': FIRST, 'wire': auth.wire_content(m)})
        self.assertEqual(m['discord']['deliveryDigest'], legacy_digest, 'bot deduplication namespace must stay compatible')

class WebhookDurableRateTests(unittest.TestCase):
    def test_webhook_uses_bound_shared_admission_not_implicit_post_budget(self):
        from test_discord_rate_limits import MemoryLedger, synthetic_policy
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget, publish_binding, RequestIdentity
        engine, state, channel, variant = webhook_fixture()
        job = approve(engine, state, review(engine, state, channel, variant)); job['leaseId'] = 'synthetic-lease'
        db = MemoryLedger(now=NOW)
        budget = SharedPostgresBudget(db.connection, APP, policy=synthetic_policy(NOW))
        binding = publish_binding(job, WORKSPACE, 'synthetic-worker')
        identity = RequestIdentity.make(APP, 'webhook', SECRET)
        permit = budget.reserve('POST', f'/webhooks/{HOOK}/{SECRET}?wait=true', identity=identity, binding=binding, valid_until=NOW + 2)
        self.assertTrue(permit.binding_hash)
        for change in [{'webhookKey': '0' * 64}, {'applicationKey': '0' * 64}]:
            with self.subTest(change=change), self.assertRaises(AlphaError):
                budget.reserve('POST', f'/webhooks/{HOOK}/{SECRET}?wait=true', identity=identity, binding={**binding, **change})
        self.assertNotIn(SECRET, json.dumps(db.admissions))
        social, provider, wire, grant = social_fixture()
        provider.rate_v1_enabled = True; provider.rate_limiter = budget
        from postriff_phase2.discord.webhooks import request
        with self.assertRaises(AlphaError): request(provider, 'POST', session(), body={'content': 'unapproved'})
        self.assertEqual(wire.calls, [])

class RateWorkerIntegrationTests(unittest.TestCase):
    def test_existing_worker_seals_and_consumes_webhook_rate_permit_once(self):
        from unittest.mock import patch
        from test_discord_rate_limits import MemoryLedger, synthetic_policy
        from test_discord_worker_lifecycle import MemoryDatabase
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget
        from postriff_phase2.hosted_worker import PostgresWorker
        from postriff_phase2 import security_holds
        engine, state, channel, variant = webhook_fixture()
        job = approve(engine, state, review(engine, state, channel, variant))
        class DB(MemoryDatabase):
            def execute(self, sql, params=()):
                if sql.startswith(('SAVEPOINT learning_', 'RELEASE SAVEPOINT learning_', 'INSERT INTO public.pr_learning_events', 'SAVEPOINT product_event_', 'RELEASE SAVEPOINT product_event_',
                                           'SAVEPOINT telemetry_journal_', 'RELEASE SAVEPOINT telemetry_journal_',
                                           'INSERT INTO public.pr_product_events', 'INSERT INTO public.pr_audit_events')):
                    self.rows, self.rowcount = [], 1; self.queries.append((sql, params))
                else: super().execute(sql, params)
        db = DB(state); shared = MemoryLedger(now=db.now, workspace=db)
        social, provider, wire, grant = social_fixture()
        social.oauth.discord_grant_for_worker = lambda *_, **kwargs: copy.deepcopy(grant)
        provider.rate_v1_enabled = True
        provider.rate_limiter = SharedPostgresBudget(shared.connection, APP, policy=synthetic_policy(db.now))
        original = provider.transport
        def response(method, url, **kwargs):
            result = original(method, url, **kwargs)
            result['headers'] = {'X-RateLimit-Bucket': 'synthetic-hook-bucket', 'X-RateLimit-Limit': '10',
                                 'X-RateLimit-Remaining': '8', 'X-RateLimit-Reset-After': '0.1'}
            return result
        provider.transport = response
        worker = PostgresWorker(shared.connection, social, clock=lambda: db.now, worker_id='synthetic-rate-worker', discord_workers=True)
        with patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')}), patch('postriff_phase2.billing.require_publishing'):
            for _ in range(4):
                worker.tick_discord(max_jobs=1); db.now += 2; shared.now = db.now
        saved = db.state['phase2']['jobs'][0]
        self.assertEqual(saved['state'], 'verified')
        self.assertEqual(len(saved['discordDispatchIntents']), 1)
        self.assertEqual(sum(c[0] == 'POST' for c in wire.calls), 1)
        self.assertTrue(any(a.get('credential_kind') == 'webhook' or a.get('kind') == 'webhook' for a in shared.admissions.values()), repr(shared.admissions))
        self.assertNotIn(SECRET, json.dumps(shared.admissions))

class AuthorizerLifecycleTests(unittest.TestCase):
    def test_removed_authorizer_cannot_keep_webhook_authority(self):
        from test_discord_oauth_lifecycle import service
        from unittest.mock import Mock
        s, wire = service(); s.adapter.webhook_v1_enabled = True
        engine, state, channel, variant = webhook_fixture()
        channel.update(discordAuthorizedBy=ACTOR, discordLinkedUserId=USER, discordWebhookChannelId=FIRST, providerAccountId=HOOK)
        envelope = {**session(), 'connectionId': channel['id']}
        for member in [None, ('viewer', False, False, False, True), ('editor', False, False, False, False)]:
            cur = Mock(); cur.fetchone.side_effect = [(state,), member]
            with self.subTest(member=member), self.assertRaises(AlphaError): s.validate_webhook(cur, WORKSPACE, envelope)
        cur = Mock(); cur.fetchone.side_effect = [(state,), ('owner', True, True, True, True)]
        s.validate_webhook(cur, WORKSPACE, envelope)
        self.assertEqual(wire.lifecycle_calls, [])

class ModePresentationTests(unittest.TestCase):
    def test_webhook_readiness_does_not_require_bot_or_claim_history(self):
        from postriff_phase2.oauth import OAuthService
        channel = {'platform': 'Discord', 'discordConnectionKind': 'webhook', 'connectionState': 'publish_verified',
                   'scopes': ['identify', 'webhook.incoming'], 'capabilities': {'publish': {'level': 'Direct'}}}
        provider = {'configured': True, 'connectReady': True, 'productionReviewed': True,
                    'discordModes': {'webhook': {'enabled': True}}}
        view = OAuthService.connection_readiness(channel, provider)
        self.assertEqual(view['publishing'], 'PUBLISHING_AVAILABLE')
        self.assertEqual(view['history'], 'HISTORICAL_IMPORT_UNAVAILABLE')
        self.assertFalse(view['fullyAvailable'])
        view = OAuthService.connection_readiness(channel, {**provider, 'discordModes': {'webhook': {'enabled': False}}})
        self.assertEqual(view['publishing'], 'PUBLISHING_PERMISSION_UNAVAILABLE')

class HealthModeTests(unittest.TestCase):
    def test_webhook_health_never_requests_bot_upgrade(self):
        from postriff_phase2.connection_health import missing_permissions, _granted
        social, provider, wire, grant = social_fixture()
        view = {'platform': 'Discord', 'discordConnectionKind': 'webhook', 'scopes': ['identify', 'webhook.incoming']}
        public = {'capabilities': {'publish': True}}
        self.assertEqual(missing_permissions(view, public, provider, DiscordProvider), [])
        self.assertTrue(_granted(view, public, provider, DiscordProvider, 'publish'))
        self.assertFalse(_granted(view, public, provider, DiscordProvider, 'comments_read'))

class DiscordCapabilityTruthTests(unittest.TestCase):
    def test_missing_discord_publish_scope_is_unavailable_not_assisted(self):
        from postriff_phase2.oauth import OAuthService
        social, provider, wire, grant = social_fixture()
        matrix = OAuthService._capabilities(provider, 'publish', ['identify'], ['bot'], NOW)
        self.assertEqual(matrix['publish']['level'], 'Unsupported')
        self.assertNotIn('last step', matrix['publish']['evidence'])
        self.assertNotIn('yourself', matrix['publish']['evidence'])

class AdapterIdentityTests(unittest.TestCase):
    def test_webhook_identity_uses_webhook_proof_and_never_bot_transport(self):
        social, provider, wire, grant = social_fixture()
        result = provider.identity(grant['accessToken'])
        self.assertEqual(result['providerAccountId'], HOOK)
        self.assertEqual(result['accountType'], 'webhook')
        self.assertIsNone(provider.inspect_scopes(grant['accessToken']), 'webhook proof must never manufacture bot scopes')
        self.assertTrue(all('/webhooks/' in c[1] for c in wire.calls))
        self.assertTrue(all('Authorization' not in c[2].get('headers', {}) for c in wire.calls))

class RotationUncertaintyTests(unittest.TestCase):
    def test_new_webhook_credential_cannot_bypass_unknown_same_channel_delivery(self):
        engine, state, channel, variant = webhook_fixture()
        job = approve(engine, state, review(engine, state, channel, variant))
        job.update(state='uncertain', discordDispatchIntents=[{'id': 'synthetic-old-intent'}])
        replacement = copy.deepcopy(channel)
        replacement.update(id='discord-webhook-replacement', providerAccountId='66112234', discordDestinations=[])
        state['phase2']['channels'].append(replacement)
        evidence = {**channel['discordDestinations'][0], 'webhookId': '66112234'}
        auth.register_destination(state, replacement, evidence, GENERATION, ACTOR, NOW)
        with self.assertRaises(AlphaError): review(engine, state, replacement, variant)
