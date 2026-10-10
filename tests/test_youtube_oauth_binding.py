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
from postriff_phase2.youtube.provider import LegacyYouTubeReadProvider, YouTubeProvider


NOW = 1_800_000_000
SCOPES = [READ, UPLOAD]
LEGACY = json.dumps({'v': 1, 'at': 'synthetic-old-access', 'scope': SCOPES})


class Wire:
    def __init__(self, audience='standard-client', invalid_legacy=False, scopes=None):
        self.audience, self.invalid_legacy, self.calls = audience, invalid_legacy, []
        self.scopes = list(SCOPES if scopes is None else scopes)

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == 'GET' and url.startswith(YouTubeProvider.TOKENINFO):
            if self.invalid_legacy and 'synthetic-old-access' in url:
                return {'status': 400, 'body': {'error': 'invalid_token'}}
            return {'status': 200, 'body': {'aud': self.audience, 'scope': ' '.join(self.scopes)}}
        if method == 'POST' and url == YouTubeProvider.TOKEN:
            return {'status': 200, 'body': {'access_token': 'synthetic-new-access', 'scope': ' '.join(self.scopes), 'expires_in': 3600}}
        raise AssertionError('Unexpected synthetic provider request')


class CredentialRepository:
    def __init__(self, access, refresh, expires, scopes=None):
        self.access, self.refresh, self.expires = access, refresh, expires
        self.scopes = list(SCOPES if scopes is None else scopes)
        self.result, self.updates = None, []
        self.generation = '00000000-0000-0000-0000-000000000098'
        self.revocation_locks = []
        self.state = {'phase2': {'channels': [{'id': 'connection', 'scopes': self.scopes, 'identityVerified': True}]}}

    @contextmanager
    def connection_factory(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith('SELECT provider,access_ciphertext'):
            self.result = ('youtube', self.access, self.refresh, 'synthetic-key', self.expires,
                           bool(self.refresh), False, self.scopes, 'UC' + 'a' * 22, NOW - 3600)
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
        self.actor = 'member'
        self.credentials = {}
        self.generation, self.consent_counter = None, 0
        self.state = {'phase2': {'channels': []}}
        self.assert_fresh = Mock()

    @contextmanager
    def transaction(self, *_args):
        self.locked = True
        try:
            yield self, (1, self.state, self.role), self.actor
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
        elif sql.startswith('SELECT provider,provider_account_id,scopes,access_ciphertext,key_id'):
            previous = self.credentials.get(params[1])
            self.result = (previous[2], previous[3], previous[7], previous[4], previous[6]) if previous else None
        elif sql.startswith('SELECT access_ciphertext,refresh_ciphertext,key_id'):
            previous = self.credentials.get(params[1])
            self.result = (previous[4], previous[5], previous[6]) if previous else None
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


def worker_service(provider, access, refresh, expires, scopes=None):
    repository = CredentialRepository(access, refresh, expires, scopes=scopes)
    vault = SimpleNamespace(decrypt=lambda value, _: value, encrypt=lambda value: (value, 'synthetic-key'))
    service = OAuthService(repository, None, vault, {'youtube': provider}, 'https://rafii.example', clock=lambda: NOW)
    stub_policy_dependency(service)
    service.mark_youtube_revoked = Mock()
    return service, repository


def stub_policy_dependency(service):
    # These issuer/custody fixtures isolate their existing subject. The real
    # policy SQL and dispatch dependency are tested in the isolated policy group.
    service.youtube_policy = SimpleNamespace(required=Mock(return_value=False), require_user=Mock(return_value=None),
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

    def test_optional_legacy_mount_uses_only_server_pair_and_redacted_diagnostics(self):
        values = {'POSTRIFF_OAUTH_YOUTUBE_CLIENT_ID': 'production-client',
                  'POSTRIFF_OAUTH_YOUTUBE_CLIENT_SECRET': 'synthetic-production-secret',
                  'POSTRIFF_OAUTH_YOUTUBE_LEGACY_CLIENT_ID': 'standard-client',
                  'POSTRIFF_OAUTH_YOUTUBE_LEGACY_CLIENT_SECRET': 'synthetic-legacy-secret',
                  'POSTRIFF_OAUTH_YOUTUBE_AGENTIC_CLIENT_ID': 'agent-client'}
        standard, diagnostic = YouTubeProvider.mount(values, Wire(scopes=[READ]))
        self.assertIsInstance(standard.legacy_provider, LegacyYouTubeReadProvider)
        self.assertEqual(standard.legacy_provider.client_id, 'standard-client')
        self.assertFalse(standard.legacy_provider.creator_enabled)
        self.assertEqual(standard.legacy_provider.project_evidence, {})
        self.assertEqual(standard.legacy_provider.authorization_lane, 'standard')
        self.assertEqual(standard.legacy_provider.capability_scopes('publish'), [])
        self.assertNotIn('synthetic-legacy-secret', json.dumps(diagnostic))
        for duplicate in ('production-client', 'agent-client'):
            rejected, failure = YouTubeProvider.mount_legacy(values | {'POSTRIFF_OAUTH_YOUTUBE_LEGACY_CLIENT_ID': duplicate})
            self.assertIsNone(rejected)
            self.assertTrue(failure['separateClientRequired'])
        partial = values.copy()
        partial.pop('POSTRIFF_OAUTH_YOUTUBE_LEGACY_CLIENT_SECRET')
        mounted, failure = YouTubeProvider.mount(partial)
        self.assertIsNone(mounted.legacy_provider)
        self.assertEqual(failure['legacyRefreshConfiguration']['configurationState'], 'partial_configuration')

    def test_expired_bound_legacy_read_grant_refreshes_only_with_its_original_client(self):
        old_wire, active_wire = Wire(scopes=[READ]), Wire(audience='production-client', scopes=[READ])
        standard = YouTubeProvider('production-client', 'synthetic-active-secret', transport=active_wire)
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-legacy-secret', transport=old_wire)
        standard.legacy_provider = legacy
        issued = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
        service, repository = worker_service(standard, issued['accessToken'], issued['refreshToken'], NOW - 1, scopes=[READ])
        generation = repository.generation
        grant = service.token_for_worker('workspace', 'connection', youtube_policy_required=True)
        self.assertEqual([call[0] for call in old_wire.calls], ['POST', 'GET'])
        self.assertEqual(old_wire.calls[0][2]['form']['client_id'], 'standard-client')
        self.assertEqual(old_wire.calls[0][2]['form']['client_secret'], 'synthetic-legacy-secret')
        self.assertEqual(active_wire.calls, [])
        self.assertEqual(json.loads(repository.access)['clientId'], 'standard-client')
        self.assertEqual(repository.refresh, issued['refreshToken'])
        self.assertEqual((grant['authorizationGeneration'], repository.generation), (generation, generation))
        self.assertEqual(grant['scopes'], [READ])
        self.assertIs(service.provider_for_grant(grant), legacy)
        self.assertFalse(any('authorization_generation=' in sql for sql, _ in repository.updates))
        self.assertEqual(service.youtube_policy.assert_connection.call_count, 2)
        for call in service.youtube_policy.assert_connection.call_args_list:
            self.assertEqual(call.args, ('workspace', 'connection', legacy))
            self.assertEqual(call.kwargs['generation'], generation)
            self.assertTrue(call.kwargs['force'])

    def test_legacy_read_compatibility_never_extends_stored_or_live_scopes(self):
        for stored, live in ((SCOPES, [READ]), ([READ], SCOPES), ([], [READ])):
            with self.subTest(stored=stored, live=live):
                old_wire = Wire(scopes=live)
                legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=old_wire)
                standard = YouTubeProvider('production-client', 'synthetic-secret', transport=Wire())
                standard.legacy_provider = legacy
                issued = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
                service, _ = worker_service(standard, issued['accessToken'], issued['refreshToken'], NOW + 600, scopes=stored)
                with self.assertRaises(AlphaError):
                    service.token_for_worker('workspace', 'connection')
                self.assertFalse(any(call[0] == 'POST' for call in old_wire.calls))
                self.assertEqual(len(old_wire.calls), int(stored == [READ]))
                service.mark_youtube_revoked.assert_not_called()

    def test_legacy_binding_cannot_bypass_policy_or_operator_pause(self):
        old_wire = Wire(scopes=[READ])
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=old_wire)
        standard = YouTubeProvider('production-client', 'synthetic-secret', transport=Wire())
        standard.legacy_provider = legacy
        issued = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
        service, _ = worker_service(standard, issued['accessToken'], issued['refreshToken'], NOW - 1, scopes=[READ])
        service.youtube_policy.assert_connection.side_effect = AlphaError('Synthetic policy receipt missing.', 409, code='youtube_policy_acceptance_required')
        with self.assertRaises(AlphaError) as stopped:
            service.token_for_worker('workspace', 'connection', youtube_policy_required=True)
        self.assertEqual(stopped.exception.code, 'youtube_policy_acceptance_required')
        self.assertEqual(old_wire.calls, [])
        standard.execution_enabled = False
        with self.assertRaises(AlphaError) as stopped:
            service.token_for_worker('workspace', 'connection')
        self.assertEqual(stopped.exception.status, 503)
        self.assertEqual(old_wire.calls, [])

    def test_legacy_retention_preserves_active_creator_policy_requirement(self):
        from postriff_phase2.youtube.policy_acceptance import YouTubePolicyAcceptance
        wire = Wire(scopes=[READ])
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=wire)
        standard = YouTubeProvider('production-client', 'synthetic-secret', transport=Wire(), creator_enabled=True)
        standard.legacy_provider = legacy
        issued = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
        service, repository = worker_service(standard, issued['accessToken'], issued['refreshToken'], NOW - 1, scopes=[READ])
        policy = YouTubePolicyAcceptance(service)
        self.assertFalse(policy.required(legacy, scopes=[READ]))
        self.assertTrue(policy.required(standard, scopes=[READ]))
        service.youtube_policy.required.side_effect = policy.required
        service.youtube_policy.assert_connection.side_effect = AlphaError('Synthetic policy receipt missing.', 409, code='youtube_policy_acceptance_required')
        with self.assertRaises(AlphaError) as stopped:
            service.token_for_worker('workspace', 'connection')
        self.assertEqual(stopped.exception.code, 'youtube_policy_acceptance_required')
        service.youtube_policy.required.assert_called_once_with(standard, scopes=[READ])
        self.assertTrue(service.youtube_policy.assert_connection.call_args.kwargs['force'])
        self.assertEqual(service.youtube_policy.assert_connection.call_args.kwargs['generation'], repository.generation)
        self.assertEqual(wire.calls, [])

    @patch('postriff_phase2.hosted._membership', return_value=SimpleNamespace(allows=lambda _right: True))
    def test_legacy_verify_requires_the_current_actor_interactive_policy_receipt(self, _membership):
        from postriff_phase2.youtube.policy_acceptance import YouTubePolicyAcceptance
        for token, expected in (('session', 'youtube_policy_acceptance_required'),
                                ('prt_synthetic', 'youtube_policy_interactive_required')):
            with self.subTest(token=token):
                repository = ConnectionFlowRepository()
                repository.actor, repository.generation = 'second-member', 'original-owner-generation'
                vault = SimpleNamespace(decrypt=lambda value, _key: value.removeprefix('fixture:'))
                old_wire, active_wire = Wire(scopes=[READ]), Wire(audience='production-client', scopes=[READ])
                standard = YouTubeProvider('production-client', 'synthetic-secret', transport=active_wire, creator_enabled=True)
                legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=old_wire)
                standard.legacy_provider = legacy
                issued = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
                repository.credentials['connection'] = ('workspace', 'connection', 'youtube', 'UC' + 'a' * 22,
                    'fixture:' + issued['accessToken'], 'fixture:' + issued['refreshToken'], 'fixture-key', [READ], NOW - 1, True)
                service = OAuthService(repository, None, vault, {'youtube': standard}, 'https://rafii.example', clock=lambda: NOW)
                policy = YouTubePolicyAcceptance(service)
                published = {'id': 'current-policy'}
                policy._current = Mock(return_value=published)
                policy._receipt = Mock(side_effect=lambda _cur, _workspace, actor, _policy:
                                       {'id': 'owner-receipt'} if actor == 'original-owner' else None)
                service.youtube_policy = policy
                service.token_for_worker = Mock(side_effect=AssertionError('Actor policy admission must precede token/provider I/O.'))
                with self.assertRaises(AlphaError) as stopped:
                    service.verify('workspace', token, 'connection')
                self.assertEqual(stopped.exception.code, expected)
                if token == 'session':
                    policy._receipt.assert_called_once_with(repository, 'workspace', 'second-member', published)
                else:
                    policy._current.assert_not_called()
                    policy._receipt.assert_not_called()
                service.token_for_worker.assert_not_called()
                self.assertEqual(old_wire.calls, [])
                self.assertEqual(active_wire.calls, [])
                self.assertEqual(repository.generation, 'original-owner-generation')

    def test_foreign_raw_v1_and_agentic_custody_never_uses_legacy_adapter(self):
        old_wire, active_wire = Wire(scopes=[READ]), Wire(audience='standard-client', scopes=[READ])
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=old_wire)
        standard = YouTubeProvider('production-client', 'synthetic-secret', transport=active_wire)
        standard.legacy_provider = legacy
        standard.agentic_provider = YouTubeProvider('agent-client', 'synthetic-secret', transport=Wire(audience='agent-client'), authorization_lane='agentic')
        bound = json.loads(legacy._grant({'access_token': 'synthetic-old-access', 'scope': READ})['accessToken'])
        cases = (json.dumps(bound | {'clientId': 'foreign-client'}),
                 json.dumps(bound | {'authorizationLane': 'agentic'}),
                 LEGACY, 'synthetic-raw-access')
        for access in cases:
            with self.subTest(access=access):
                service, _ = worker_service(standard, access, 'synthetic-unbound-refresh', NOW - 1, scopes=[READ])
                with self.assertRaises(AlphaError):
                    service.token_for_worker('workspace', 'connection')
        self.assertEqual(old_wire.calls, [])
        self.assertFalse(any(call[0] == 'POST' for call in active_wire.calls))

    def test_legacy_access_does_not_make_unbound_or_other_client_refresh_reusable(self):
        wire = Wire(scopes=[READ])
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=wire)
        standard = YouTubeProvider('production-client', 'synthetic-secret', transport=Wire())
        standard.legacy_provider = legacy
        issued = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
        other = standard._grant({'access_token': 'synthetic-other', 'refresh_token': 'synthetic-other-refresh', 'scope': READ})
        for refresh in ('synthetic-unbound-refresh', other['refreshToken']):
            service, _ = worker_service(standard, issued['accessToken'], refresh, NOW - 1, scopes=[READ])
            with self.assertRaises(AlphaError):
                service.token_for_worker('workspace', 'connection')
        self.assertEqual(wire.calls, [])
        self.assertIsNone(standard.reusable_refresh(issued['accessToken'], issued['refreshToken']))

    def test_legacy_adapter_cannot_authorize_exchange_or_write(self):
        wire = Wire(scopes=[READ])
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-secret', transport=wire)
        issued = legacy._grant({'access_token': 'synthetic-old-access', 'scope': READ})
        for operation in (lambda: legacy.authorize_url('https://rafii.example/callback', 'state', 'challenge', [READ]),
                          lambda: legacy.exchange('code', 'verifier', 'https://rafii.example/callback'),
                          lambda: legacy.api(issued['accessToken'], 'POST', legacy.API + '/videos'),
                          lambda: legacy.bearer(LEGACY),
                          lambda: legacy.bind_credentials(LEGACY, 'synthetic-raw-refresh')):
            with self.assertRaises(AlphaError):
                operation()
        self.assertEqual(wire.calls, [])

    def test_active_standard_refresh_stays_on_active_pair_when_legacy_is_mounted(self):
        active_wire, old_wire = Wire(audience='production-client', scopes=[READ]), Wire(scopes=[READ])
        standard = YouTubeProvider('production-client', 'synthetic-active-secret', transport=active_wire)
        standard.legacy_provider = LegacyYouTubeReadProvider('standard-client', 'synthetic-legacy-secret', transport=old_wire)
        issued = standard._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-refresh', 'scope': READ})
        service, _ = worker_service(standard, issued['accessToken'], issued['refreshToken'], NOW - 1, scopes=[READ])
        service.token_for_worker('workspace', 'connection')
        self.assertEqual(active_wire.calls[0][2]['form']['client_id'], 'production-client')
        self.assertEqual(active_wire.calls[0][2]['form']['client_secret'], 'synthetic-active-secret')
        self.assertEqual(old_wire.calls, [])

    @patch('postriff_phase2.hosted._membership', return_value=SimpleNamespace(allows=lambda _right: True))
    @patch('postriff_phase2.hosted.audit')
    @patch('postriff_phase2.hosted.throttle')
    @patch('postriff_phase2.billing.require_plan_capacity')
    @patch('postriff_phase2.product_events.record')
    def test_new_standard_consent_replaces_legacy_generation_without_reusing_old_refresh(self, *_mocks):
        from urllib.parse import parse_qs, urlsplit
        repository = ConnectionFlowRepository()
        vault = SimpleNamespace(key_id='fixture-key', encrypt=lambda value: ('fixture:' + value, 'fixture-key'),
                                decrypt=lambda value, _key: value.removeprefix('fixture:'))
        active_wire, old_wire = Wire(audience='production-client', scopes=[READ]), Wire(scopes=[READ])
        standard = YouTubeProvider('production-client', 'synthetic-active-secret', transport=active_wire)
        legacy = LegacyYouTubeReadProvider('standard-client', 'synthetic-legacy-secret', transport=old_wire)
        standard.legacy_provider = legacy
        account = 'UC' + 'a' * 22
        connection = OAuthService._connection_id('youtube', account)
        old = legacy._grant({'access_token': 'synthetic-old-access', 'refresh_token': 'synthetic-old-refresh', 'scope': READ})
        repository.credentials[connection] = ('workspace', connection, 'youtube', account,
                                              'fixture:' + old['accessToken'], 'fixture:' + old['refreshToken'],
                                              'fixture-key', [READ], NOW - 1, True)
        repository.generation = 'synthetic-old-consent'
        standard.identity = Mock(return_value={'providerAccountId': account, 'handle': 'Synthetic', 'accountType': 'channel'})
        commands = SimpleNamespace(upsert_verified_channel=lambda state, actor, channel, **kw: state['phase2']['channels'].append(channel))
        service = OAuthService(repository, commands, vault, {'youtube': standard}, 'https://rafii.example', clock=lambda: NOW)
        stub_policy_dependency(service)
        service._keep_picture = Mock()
        started = service.start('workspace', 'session', 'youtube', 'identity', {'connectionId': connection})
        query = parse_qs(urlsplit(started['authorizeUrl']).query)
        self.assertEqual(query['client_id'], ['production-client'])
        completed = service.complete('workspace', 'session', 'youtube', query['state'][0], 'synthetic-code')
        self.assertEqual(completed['connectionId'], connection)
        self.assertEqual(active_wire.calls[0][2]['form']['client_id'], 'production-client')
        self.assertEqual(repository.generation, 'synthetic-new-consent-1')
        saved = repository.credentials[connection]
        self.assertEqual(json.loads(vault.decrypt(saved[4], 'fixture-key'))['clientId'], 'production-client')
        self.assertIsNone(saved[5])  # Google omitted fresh refresh; the old issuer cannot fill that gap.
        self.assertFalse(saved[9])
        self.assertEqual(old_wire.calls, [])

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
