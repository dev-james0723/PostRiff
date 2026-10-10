"""Offline OAuth custody regression. Synthetic tokens; no Google calls or real acceptance."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import OAuthService
from postriff_phase2.youtube.model import READ, UPLOAD
from postriff_phase2.youtube.provider import YouTubeProvider


NOW = 1_800_000_000
SCOPES = [READ, UPLOAD]
LEGACY = json.dumps({'v': 1, 'at': 'synthetic-old-access', 'scope': SCOPES})


class Wire:
    def __init__(self, audience='standard-client', invalid_legacy=False):
        self.audience, self.invalid_legacy, self.calls = audience, invalid_legacy, []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == 'GET' and url.startswith(YouTubeProvider.TOKENINFO):
            if self.invalid_legacy and 'synthetic-old-access' in url:
                return {'status': 400, 'body': {'error': 'invalid_token'}}
            return {'status': 200, 'body': {'aud': self.audience, 'scope': ' '.join(SCOPES)}}
        if method == 'POST' and url == YouTubeProvider.TOKEN:
            return {'status': 200, 'body': {'access_token': 'synthetic-new-access', 'scope': ' '.join(SCOPES), 'expires_in': 3600}}
        raise AssertionError('Unexpected synthetic provider request')


class CredentialRepository:
    def __init__(self, access, refresh, expires):
        self.access, self.refresh, self.expires = access, refresh, expires
        self.result, self.updates = None, []
        self.generation = '00000000-0000-0000-0000-000000000098'
        self.revocation_locks = []
        self.state = {'phase2': {'channels': [{'id': 'connection', 'scopes': SCOPES, 'identityVerified': True}]}}

    @contextmanager
    def connection_factory(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith('SELECT provider,access_ciphertext'):
            self.result = ('youtube', self.access, self.refresh, 'synthetic-key', self.expires,
                           bool(self.refresh), False, SCOPES, 'UC' + 'a' * 22, NOW - 3600)
        elif sql == 'SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE':
            assert params == ('workspace',)
            self.revocation_locks.append('workspace')
            self.result = ('workspace',)
        elif 'SELECT EXISTS(SELECT 1 FROM pg_attribute' in sql:
            self.result = (True,)
        elif sql.startswith('SELECT authorization_generation::text FROM public.pr_encrypted_credentials'):
            self.result = (self.generation,)
        elif sql.startswith('SELECT c.provider,c.provider_account_id,w.state'):
            self.result = ('youtube', 'UC' + 'a' * 22, self.state)
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            if sql.endswith('FOR UPDATE'):
                assert params == ('workspace',)
                self.revocation_locks.append('workspace')
            self.result = (self.state,)
        elif sql.startswith('SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials'):
            if "provider='youtube'" in sql and sql.endswith('FOR UPDATE'):
                assert self.revocation_locks[-1:] == ['workspace'], 'Revocation must lock workspace before credential.'
                self.revocation_locks.append('credential')
            self.result = (self.access, 'synthetic-key')
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET access_ciphertext='):
            self.updates.append((sql, params))
            self.access, self.refresh = params[:2]
            if 'access_expires_at=' in sql:
                self.expires = params[3]
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET scopes='):
            self.updates.append((sql, params))
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET refresh_supported=false'):
            self.updates.append((sql, params))
        else:
            raise AssertionError('Unexpected synthetic credential SQL')

    def fetchone(self):
        return self.result


class ConnectionFlowRepository:
    """Minimal SQL fixture for single-use custody and the actual completion path."""
    def __init__(self):
        self.locked, self.txn, self.consumed, self.result = False, None, False, None
        self.role = 'owner'
        self.credentials = {}
        self.generation, self.consent_counter = None, 0
        self.state = {'phase2': {'channels': []}}
        self.assert_fresh = Mock()

    @contextmanager
    def transaction(self, *_args):
        self.locked = True
        try:
            yield self, (1, self.state, self.role), 'member'
        finally:
            self.locked = False

    def execute(self, sql, params=()):
        if sql.startswith('INSERT INTO public.pr_oauth_transactions'):
            self.txn, self.consumed, self.result = params, False, ('txn',)
        elif sql.startswith('SELECT id::text,member_id::text,provider,extract'):
            t = self.txn
            self.result = ('txn', t[1], t[2], NOW + 600, self.consumed, t[7], t[8], t[5])
        elif sql.startswith('SELECT id::text,member_id::text,provider,capability'):
            t = self.txn
            self.result = ('txn', t[1], t[2], t[3], t[4], t[5], t[7], t[8], NOW + 600, self.consumed)
        elif sql.startswith('UPDATE public.pr_oauth_transactions'):
            self.consumed = True
        elif sql.startswith('SELECT access_ciphertext,refresh_ciphertext,key_id'):
            self.result = None
        elif sql.startswith('INSERT INTO public.pr_encrypted_credentials'):
            self.credentials[params[1]] = params
            self.consent_counter += 1
            self.generation = f'synthetic-new-consent-{self.consent_counter}'
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET provider_account_id='):
            account, observed_at, workspace, connection = params
            assert self.credentials[connection][0] == workspace
            assert self.credentials[connection][3] == account
            self.identity_observation = (workspace, connection, account, observed_at)
            self.result = (self.generation,)
        elif sql.startswith('SELECT authorization_generation::text FROM public.pr_encrypted_credentials'):
            self.result = (self.generation,) if params[1] in self.credentials else None
        elif sql.startswith('INSERT INTO public.pr_channel_capabilities'):
            pass
        else:
            raise AssertionError('Unexpected flow fixture SQL: ' + sql[:90])

    def fetchone(self):
        return self.result

    def get(self, *_args):
        return {'revision': 1, 'state': self.state}

    def command(self, _workspace, _token, _revision, change, **_kwargs):
        before = copy.deepcopy(self.state)
        try:
            change(self.state, 'member')
            if _kwargs.get('after'):
                _kwargs['after'](self, self.state, 'member')
        except Exception:
            self.state = before
            raise
        return self.get()


def worker_service(provider, access, refresh, expires):
    repository = CredentialRepository(access, refresh, expires)
    vault = SimpleNamespace(decrypt=lambda value, _: value, encrypt=lambda value: (value, 'synthetic-key'))
    service = OAuthService(repository, None, vault, {'youtube': provider}, 'https://rafii.example', clock=lambda: NOW)
    stub_policy_dependency(service)
    service.mark_youtube_revoked = Mock()
    return service, repository


def stub_policy_dependency(service):
    # These issuer/custody fixtures isolate their existing subject. The real
    # policy SQL and dispatch dependency are tested in the isolated policy group.
    service.youtube_policy = SimpleNamespace(require_user=Mock(return_value=None),
        require_pending=Mock(return_value=None), bind=Mock(), assert_connection=Mock(),
        guarded_provider=lambda provider, _grant: provider)


class YouTubeOAuthBindingTests(unittest.TestCase):
    def test_new_grants_encrypt_client_and_lane_metadata_with_both_tokens(self):
        wire = Wire()
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        grant = provider._grant({'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
        for field, key in (('accessToken', 'at'), ('refreshToken', 'rt')):
            envelope = json.loads(grant[field])
            self.assertEqual((envelope['v'], envelope['clientId'], envelope['authorizationLane']), (2, 'standard-client', 'standard'))
            self.assertTrue(envelope[key].startswith('synthetic-'))
        refreshed = provider.refresh(grant['refreshToken'])
        self.assertEqual(wire.calls[-1][2]['form']['refresh_token'], 'synthetic-refresh')
        self.assertEqual(refreshed['refreshToken'], grant['refreshToken'])

    def test_cross_client_and_cross_lane_custody_never_reaches_provider(self):
        wire = Wire()
        original = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        grant = original._grant({'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh'})
        for provider in (YouTubeProvider('production-client', 'synthetic-secret', transport=wire),
                         YouTubeProvider('standard-client', 'synthetic-secret', transport=wire, authorization_lane='agentic')):
            with self.subTest(client=provider.client_id, lane=provider.authorization_lane):
                for operation in (lambda: provider.bind_credentials(grant['accessToken'], grant['refreshToken']),
                                  lambda: provider.refresh(grant['refreshToken']),
                                  lambda: provider.api(grant['accessToken'], 'GET', provider.API + '/channels')):
                    with self.assertRaises(AlphaError) as failure:
                        operation()
                    self.assertEqual(failure.exception.code, 'youtube_oauth_binding_changed')
        self.assertEqual(wire.calls, [])

    def test_valid_legacy_access_survives_but_unknown_refresh_is_not_reused(self):
        wire = Wire()
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        service, repository = worker_service(provider, LEGACY, 'synthetic-refresh', NOW + 60)
        grant = service.token_for_worker('workspace', 'connection')
        self.assertEqual([call[0] for call in wire.calls], ['GET'])
        self.assertEqual(json.loads(repository.access)['clientId'], 'standard-client')
        self.assertEqual(repository.refresh, 'synthetic-refresh')
        self.assertIs(repository.updates[0][1][3], False)
        self.assertTrue(grant['refreshBindingRequired'])
        self.assertEqual(set(grant['scopes']), set(SCOPES))
        service.mark_youtube_revoked.assert_not_called()

    def test_bound_expired_access_refreshes_without_requiring_live_old_access(self):
        wire = Wire(invalid_legacy=True)
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        issued = provider._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh'})
        service, repository = worker_service(provider, issued['accessToken'], issued['refreshToken'], NOW - 1)
        service.token_for_worker('workspace', 'connection')
        self.assertEqual([call[0] for call in wire.calls], ['POST', 'GET'])
        self.assertGreater(repository.expires, NOW)

    def test_unknown_expired_legacy_issuer_is_never_guessed_or_classified_revoked(self):
        wire = Wire(invalid_legacy=True)
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        service, repository = worker_service(provider, LEGACY, 'synthetic-refresh', NOW - 1)
        with self.assertRaises(AlphaError) as failure:
            service.token_for_worker('workspace', 'connection')
        self.assertEqual(failure.exception.code, 'youtube_oauth_binding_required')
        self.assertEqual([call[0] for call in wire.calls], ['GET'])
        self.assertEqual(len(repository.updates), 1)
        self.assertIn('refresh_supported=false', repository.updates[0][0])
        self.assertEqual((repository.access, repository.refresh), (LEGACY, 'synthetic-refresh'))
        service.mark_youtube_revoked.assert_not_called()

    def test_production_client_cutover_does_not_send_legacy_staging_refresh(self):
        wire = Wire(audience='staging-client')
        provider = YouTubeProvider('production-client', 'synthetic-secret', transport=wire)
        service, repository = worker_service(provider, LEGACY, 'synthetic-refresh', NOW + 60)
        with self.assertRaises(AlphaError) as failure:
            service.token_for_worker('workspace', 'connection')
        self.assertEqual(failure.exception.code, 'youtube_oauth_binding_changed')
        self.assertEqual([call[0] for call in wire.calls], ['GET'])
        self.assertEqual(len(repository.updates), 1)
        self.assertIn('refresh_supported=false', repository.updates[0][0])
        self.assertEqual((repository.access, repository.refresh), (LEGACY, 'synthetic-refresh'))
        service.mark_youtube_revoked.assert_not_called()

    @patch('postriff_phase2.hosted.audit')
    def test_worker_binding_intervention_preserves_identity_and_never_purges(self, _audit):
        wire = Wire(invalid_legacy=True)
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        service, repository = worker_service(provider, LEGACY, 'synthetic-refresh', NOW - 1)
        result = service.reverify_for_worker('workspace', 'connection')
        self.assertEqual(result['state'], 'client_binding_missing')
        self.assertFalse(result['ready'])
        self.assertTrue(result['refreshBindingRequired'])
        self.assertTrue(repository.state['phase2']['channels'][0]['identityVerified'])
        self.assertEqual(repository.state['phase2']['channels'][0]['scopes'], SCOPES)
        self.assertEqual((repository.access, repository.refresh), (LEGACY, 'synthetic-refresh'))
        self.assertEqual([call[0] for call in wire.calls], ['GET'])
        service.mark_youtube_revoked.assert_not_called()

    def test_incremental_upgrade_reuses_only_a_proven_refresh_pair(self):
        wire = Wire()
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        issued = provider._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh'})
        self.assertEqual(provider.reusable_refresh(issued['accessToken'], issued['refreshToken']), issued['refreshToken'])
        self.assertIsNone(provider.reusable_refresh(LEGACY, 'synthetic-refresh'))
        other = YouTubeProvider('production-client', 'synthetic-secret', transport=wire)
        self.assertIsNone(other.reusable_refresh(issued['accessToken'], issued['refreshToken']))
        wire.invalid_legacy = True
        self.assertIsNone(provider.reusable_refresh(LEGACY, 'synthetic-refresh'))
        with self.assertRaises(AlphaError) as failure:
            provider.refresh('synthetic-unbound-refresh')
        self.assertEqual(failure.exception.code, 'youtube_oauth_binding_required')

    def test_legacy_access_audience_cannot_prove_a_mixed_refresh_issuer(self):
        wire = Wire()
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=wire)
        access, refresh, scopes = provider.bind_credentials(LEGACY, 'synthetic-refresh-from-unknown-client')
        self.assertTrue(provider.refresh_binding_required(access))
        self.assertEqual(refresh, 'synthetic-refresh-from-unknown-client')
        self.assertEqual(set(scopes), set(SCOPES))
        self.assertIsNone(provider.reusable_refresh(access, refresh))
        with self.assertRaises(AlphaError):
            provider.refresh(refresh)
        self.assertEqual([call[0] for call in wire.calls], ['GET'])

    def test_agentic_configuration_is_separate_and_disabled_by_default(self):
        values = {'POSTRIFF_OAUTH_YOUTUBE_CLIENT_ID': 'standard-client',
                  'POSTRIFF_OAUTH_YOUTUBE_CLIENT_SECRET': 'standard-secret',
                  'POSTRIFF_OAUTH_YOUTUBE_AGENTIC_CLIENT_ID': 'agent-client',
                  'POSTRIFF_OAUTH_YOUTUBE_AGENTIC_CLIENT_SECRET': 'agent-secret'}
        standard, _ = YouTubeProvider.mount(values)
        agentic, diagnostic = YouTubeProvider.mount_agentic(values)
        self.assertEqual((standard.client_id, standard.authorization_lane), ('standard-client', 'standard'))
        self.assertEqual((agentic.client_id, agentic.authorization_lane), ('agent-client', 'agentic'))
        self.assertFalse(agentic.execution_enabled)
        self.assertFalse(diagnostic['executionEnabled'])
        rejected, diagnostic = YouTubeProvider.mount_agentic(values | {'POSTRIFF_OAUTH_YOUTUBE_AGENTIC_CLIENT_ID': 'standard-client'})
        self.assertIsNone(rejected)
        self.assertTrue(diagnostic['separateClientRequired'])
        with self.assertRaises(AlphaError):
            agentic.bind_credentials(LEGACY, 'synthetic-refresh')

    def test_agentic_connection_requires_configured_separate_client_and_explicit_consent(self):
        provider = YouTubeProvider('standard-client', 'synthetic-secret')
        service = OAuthService(None, None, None, {'youtube': provider}, 'https://rafii.example')
        with self.assertRaises(AlphaError) as failure:
            service.start('workspace', 'session', 'youtube', 'publish', {'authorizationLane': 'agentic'})
        self.assertEqual(failure.exception.code, 'youtube_oauth_binding_changed')
        provider.agentic_provider = YouTubeProvider('agent-client', 'synthetic-secret', authorization_lane='agentic')
        with self.assertRaises(AlphaError) as failure:
            service.start('workspace', 'session', 'youtube', 'autopilot', {'authorizationLane': 'agentic'})
        self.assertEqual(failure.exception.code, 'youtube_agentic_consent_required')
        with self.assertRaises(AlphaError) as failure:
            service.start('workspace', 'session', 'youtube', 'autopilot')
        self.assertEqual(failure.exception.code, 'youtube_agentic_consent_required')

    def test_connection_ids_preserve_standard_and_separate_agentic_channel(self):
        import hashlib
        channel = 'UC' + 'a' * 22
        standard = OAuthService._connection_id('youtube', channel)
        self.assertEqual(standard, hashlib.sha256(('youtube:' + channel).encode()).hexdigest()[:32])
        self.assertNotEqual(standard, OAuthService._connection_id('youtube', channel, 'agentic'))

    def test_runtime_lane_comes_only_from_protected_custody(self):
        standard = YouTubeProvider('standard-client', 'synthetic-secret', transport=Wire())
        agentic = YouTubeProvider('agent-client', 'synthetic-secret', transport=Wire(audience='agent-client'), authorization_lane='agentic')
        standard.agentic_provider = agentic
        service = OAuthService(None, None, None, {'youtube': standard}, 'https://rafii.example')
        standard_grant = standard._grant({'access_token': 'synthetic-access'})
        agentic_grant = agentic._grant({'access_token': 'synthetic-access'})
        self.assertIs(service.provider_for_grant({'provider': 'youtube', 'authorizationLane': 'agentic', **standard_grant}), standard)
        self.assertIs(service.provider_for_grant({'provider': 'youtube', 'authorizationLane': 'standard', **agentic_grant}), agentic)
        mismatched = json.loads(agentic_grant['accessToken'])
        mismatched['clientId'] = standard.client_id
        with self.assertRaises(AlphaError) as failure:
            service.provider_for_grant({'provider': 'youtube', 'accessToken': json.dumps(mismatched)})
        self.assertEqual(failure.exception.code, 'youtube_oauth_binding_changed')

    def test_agentic_refresh_uses_only_its_own_client(self):
        standard_wire, agentic_wire = Wire(), Wire(audience='agent-client')
        standard = YouTubeProvider('standard-client', 'synthetic-secret', transport=standard_wire)
        agentic = YouTubeProvider('agent-client', 'synthetic-secret', transport=agentic_wire, authorization_lane='agentic')
        agentic.execution_enabled = True
        standard.agentic_provider = agentic
        issued = agentic._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh'})
        service, _ = worker_service(standard, issued['accessToken'], issued['refreshToken'], NOW - 1)
        grant = service.token_for_worker('workspace', 'connection')
        self.assertEqual(grant['authorizationLane'], 'agentic')
        self.assertEqual(standard_wire.calls, [])
        self.assertEqual(agentic_wire.calls[0][2]['form']['client_id'], 'agent-client')
        self.assertIs(service.provider_for_grant(grant), agentic)

    def test_failed_old_refresh_cannot_purge_a_concurrent_new_consent(self):
        standard = YouTubeProvider('standard-client', 'synthetic-secret', transport=Wire())
        old = standard._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-old-refresh'})
        fresh = standard._grant({'access_token': 'synthetic-new-consent', 'refresh_token': 'synthetic-new-refresh'})
        service, repository = worker_service(standard, old['accessToken'], old['refreshToken'], NOW - 1)
        service.mark_youtube_revoked = OAuthService.mark_youtube_revoked.__get__(service)

        def rotate_then_reject(_refresh):
            repository.access, repository.refresh = fresh['accessToken'], fresh['refreshToken']
            raise AlphaError('Synthetic old refresh rejected.', 409, code='youtube_revoked_oauth')

        standard.refresh = rotate_then_reject
        with patch('postriff_phase2.youtube.journal.purge_authorized_data') as purge:
            with self.assertRaises(AlphaError):
                service.token_for_worker('workspace', 'connection')
            purge.assert_not_called()
        self.assertEqual((repository.access, repository.refresh), (fresh['accessToken'], fresh['refreshToken']))
        self.assertFalse(any('revoked_at=now()' in sql for sql, _ in repository.updates))
        self.assertEqual(repository.revocation_locks, ['workspace', 'credential'])

    def test_api_revocation_fence_rejects_stale_observation_and_unbound_call(self):
        provider = YouTubeProvider('standard-client', 'synthetic-secret', transport=Wire())
        old = provider._grant({'access_token': 'synthetic-old-access'})
        fresh = provider._grant({'access_token': 'synthetic-new-consent'})
        service, repository = worker_service(provider, fresh['accessToken'], None, NOW + 60)
        service.mark_youtube_revoked = OAuthService.mark_youtube_revoked.__get__(service)
        with patch('postriff_phase2.youtube.journal.purge_authorized_data') as purge:
            self.assertFalse(service.mark_youtube_revoked('workspace', 'connection', expected_access_token=old['accessToken'], expected_generation=repository.generation))
            self.assertFalse(service.mark_youtube_revoked('workspace', 'connection'))
            purge.assert_not_called()
        self.assertEqual(repository.revocation_locks, ['workspace', 'credential'])

    @patch('postriff_phase2.hosted._membership', return_value=SimpleNamespace(allows=lambda _right: True))
    @patch('postriff_phase2.hosted.audit')
    @patch('postriff_phase2.hosted.throttle')
    @patch('postriff_phase2.billing.require_plan_capacity')
    @patch('postriff_phase2.product_events.record')
    def test_real_start_and_completion_paths_bind_distinct_channels_and_reserve_unlocked(self, *_mocks):
        from urllib.parse import parse_qs, urlsplit
        from postriff_phase2.youtube.model import MANAGE
        # Custody SQL fixture, not a cryptography acceptance test (covered remotely).
        repository = ConnectionFlowRepository()
        vault = SimpleNamespace(key_id='fixture-key', encrypt=lambda value: ('fixture:' + value, 'fixture-key'),
                                decrypt=lambda value, _key: value.removeprefix('fixture:'))
        standard = YouTubeProvider('standard-client', 'synthetic-secret', transport=Wire(), creator_enabled=True)
        agentic = YouTubeProvider('agent-client', 'synthetic-secret', transport=Wire(audience='agent-client'), creator_enabled=True, authorization_lane='agentic')
        standard.execution_enabled = agentic.execution_enabled = True
        standard.agentic_provider = agentic
        standard.callback_origin = 'https://registered-legacy.example'
        agentic.callback_origin = 'https://agentic-registered-legacy.example'
        identity = {'providerAccountId': 'UC' + 'a' * 22, 'handle': 'Synthetic', 'accountType': 'channel'}
        for provider in (standard, agentic):
            provider.identity = Mock(return_value=identity)
            provider.exchange = Mock(return_value=provider._grant({'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'scope': ' '.join([READ, UPLOAD, MANAGE]), 'expires_in': 3600}))
        commands = SimpleNamespace(upsert_verified_channel=lambda state, actor, channel, **kw: state['phase2']['channels'].append(channel))
        service = OAuthService(repository, commands, vault, {'youtube': standard}, 'https://legacy.example', clock=lambda: NOW,
                               youtube_public_base_url='https://rafii.example')
        stub_policy_dependency(service)
        service._keep_picture = Mock()
        admissions = []
        def reserve(workspace, selected):
            self.assertFalse(repository.locked)
            self.assertTrue(repository.consumed)
            admissions.append(selected)
        service.identity_admission = reserve
        ids = []
        for lane, capability in (('standard', 'publish'), ('agentic', 'autopilot')):
            started = service.start('workspace', 'session', 'youtube', capability, {'authorizationLane': lane, 'agenticConsent': True})
            query = parse_qs(urlsplit(started['authorizeUrl']).query)
            selected = standard if lane == 'standard' else agentic
            self.assertEqual(query['client_id'], [selected.client_id])
            expected_redirect = 'https://rafii.example/api/oauth/youtube/callback'
            self.assertEqual(query['redirect_uri'], [expected_redirect])
            self.assertEqual(repository.txn[4], expected_redirect)
            # An in-flight transaction retains its exact original redirect on exchange.
            service.youtube_public_base_url = 'https://future-cutover.example'
            standard.callback_origin = 'https://moved-legacy.example'
            completed = service.complete('workspace', 'session', 'youtube', query['state'][0], 'synthetic-code')
            self.assertEqual(selected.exchange.call_args.args[2], expected_redirect)
            service.youtube_public_base_url = 'https://rafii.example'
            standard.callback_origin = 'https://registered-legacy.example'
            ids.append(completed['connectionId'])
            encrypted = repository.credentials[completed['connectionId']][4]
            binding = json.loads(vault.decrypt(encrypted, vault.key_id))
            self.assertEqual((binding['authorizationLane'], binding['clientId']), (lane, selected.client_id))
            with self.assertRaises(AlphaError):
                service.complete('workspace', 'session', 'youtube', query['state'][0], 'synthetic-code')
        self.assertNotEqual(*ids)
        self.assertEqual(admissions, [standard, agentic])
        self.assertEqual([channel['authorizationLane'] for channel in repository.state['phase2']['channels']], ['standard', 'agentic'])
        self.assertEqual(repository.assert_fresh.call_count, 3)

    @patch('postriff_phase2.hosted.audit')
    @patch('postriff_phase2.hosted.throttle')
    def test_agentic_completion_rechecks_owner_and_freshness_after_claim_before_exchange(self, *_mocks):
        from urllib.parse import parse_qs, urlsplit
        for change in ('demotion', 'freshness'):
            with self.subTest(change=change):
                repository = ConnectionFlowRepository()
                vault = SimpleNamespace(encrypt=lambda value: ('fixture:' + value, 'fixture-key'),
                                        decrypt=lambda value, _key: value.removeprefix('fixture:'))
                standard = YouTubeProvider('standard-client', 'synthetic-secret', transport=Wire())
                agentic = YouTubeProvider('agent-client', 'synthetic-secret', transport=Wire(audience='agent-client'), authorization_lane='agentic')
                standard.agentic_provider = agentic
                standard.execution_enabled = agentic.execution_enabled = True
                agentic.exchange = Mock(side_effect=AssertionError('Lost owner/session authority must stop before token exchange.'))
                agentic.identity = Mock()
                service = OAuthService(repository, None, vault, {'youtube': standard}, 'https://rafii.example', clock=lambda: NOW)
                stub_policy_dependency(service)
                started = service.start('workspace', 'session', 'youtube', 'autopilot',
                                        {'authorizationLane': 'agentic', 'agenticConsent': True})
                state = parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0]

                def change_after_claim(workspace, provider):
                    self.assertFalse(repository.locked)
                    self.assertTrue(repository.consumed)
                    self.assertEqual(workspace, 'workspace')
                    self.assertIs(provider, agentic)
                    if change == 'demotion':
                        repository.role = 'admin'  # Still manages connections, but cannot own this grant.
                    else:
                        repository.assert_fresh.side_effect = AlphaError('Sign in again.', 403)

                service.identity_admission = Mock(side_effect=change_after_claim)
                with self.assertRaises(AlphaError) as stopped:
                    service.complete('workspace', 'session', 'youtube', state, 'synthetic-code')
                self.assertEqual(stopped.exception.status, 403)
                self.assertTrue(repository.consumed, 'The failed exchange must not make one-time state replayable.')
                self.assertEqual(repository.credentials, {})
                self.assertEqual(repository.state['phase2']['channels'], [])
                service.identity_admission.assert_called_once()
                agentic.exchange.assert_not_called()
                agentic.identity.assert_not_called()
                self.assertEqual(agentic.transport.calls, [])
                self.assertEqual(standard.transport.calls, [])


if __name__ == '__main__':
    unittest.main()
