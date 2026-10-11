"""Focused offline control regression; no Google requests or real acceptance claims."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import OAuthService
from postriff_phase2.youtube.api import YouTubeApi
from postriff_phase2.youtube.model import READ, UPLOAD, MANAGE
from postriff_phase2.youtube.provider import YouTubeProvider
from postriff_phase2.youtube.service import YouTubeCreatorService


CHANNEL, VIDEO, NOW = 'UC' + 'a' * 22, 'abcdefghijk', 1_800_000_000
SCOPES = [READ, UPLOAD, MANAGE]
TOKEN = json.dumps({'v': 1, 'at': 'synthetic-access'})
GENERATION = '00000000-0000-0000-0000-000000000098'


class Repository:
    """Record scope and channel mutations at the OAuth service boundary."""
    def __init__(self):
        self.scopes = list(SCOPES)
        self.state = {'phase2': {'channels': [{'id': 'connection', 'scopes': list(SCOPES),
            'identityVerified': True, 'capabilityVerified': True, 'verifiedAt': NOW - 10,
            'expiresAt': NOW + 3600}]}}
        self.executed, self.result = [], None
        self.rowcount, self.identity_ingested_at = 1, None

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if sql.startswith('SELECT provider,access_ciphertext'):
            self.result = ('youtube', TOKEN, None, 'test', NOW + 3600, False, False, list(self.scopes), CHANNEL, NOW - 10)
        elif sql.startswith('SELECT provider,provider_account_id,scopes'):
            self.result = ('youtube', CHANNEL, list(self.scopes), TOKEN, 'test')
        elif 'SELECT EXISTS(SELECT 1 FROM pg_attribute' in sql:
            self.result = (True,)
        elif sql.startswith('SELECT authorization_generation::text FROM public.pr_encrypted_credentials'):
            self.result = (GENERATION,)
        elif sql.startswith('SELECT c.provider,c.provider_account_id,w.state'):
            self.result = ('youtube', CHANNEL, self.state)
        elif sql.startswith('SELECT access_ciphertext,key_id,scopes'):
            self.result = (TOKEN, 'test', list(self.scopes))
        elif sql.startswith('SELECT access_ciphertext,key_id FROM'):
            self.result = (TOKEN, 'test')
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.result = (self.state,)
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET scopes='):
            self.scopes = list(params[0])
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET youtube_identity_ingested_at='):
            observed_at, workspace, connection, generation, account = params
            assert (workspace, connection, generation, account) == ('workspace', 'connection', GENERATION, CHANNEL)
            self.identity_ingested_at = observed_at
            self.rowcount = 1
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.state = json.loads(params[0])

    def fetchone(self):
        return self.result

    @contextmanager
    def cursor(self):
        yield self

    @contextmanager
    def connection_factory(self):
        yield self

    @contextmanager
    def transaction(self, token, workspace):
        assert (token, workspace) == ('session', 'workspace')
        yield self, (1, self.state, 'owner', False, False, False, False), 'owner'


def service_for(observation):
    repo = Repository()

    def wire(method, url, **_):
        assert method == 'GET', 'The control regression must not perform provider writes.'
        if url.startswith(YouTubeProvider.TOKENINFO):
            if isinstance(observation, AlphaError):
                raise observation
            return copy.deepcopy(observation)
        if url.startswith(YouTubeProvider.API + '/channels?'):
            return {'status': 200, 'body': {'items': [{'id': CHANNEL, 'snippet': {'title': 'Synthetic channel'}}]}}
        raise AssertionError('Unexpected synthetic request')

    provider = YouTubeProvider('test-client', 'test-secret', transport=wire, creator_enabled=True)
    engine = SimpleNamespace(invalidate=Mock(), channel_state=lambda c: 'Ready for posting' if c['capabilityVerified'] else 'Needs reconnect')
    vault = SimpleNamespace(decrypt=lambda value, _: value)
    service = OAuthService(repo, SimpleNamespace(engine=engine), vault, {'youtube': provider}, 'https://rafii.example', clock=lambda: NOW)
    # Isolate scope observation/custody; the policy dependency has its own real
    # receipt/RLS/OAuth regressions in the dedicated policy acceptance PG group.
    service.youtube_policy.require_user = Mock(return_value=None)
    service.youtube_policy.assert_connection = Mock()
    service.mark_youtube_revoked = Mock()
    return service, repo, provider


class YouTubeConnectionSafetyTests(unittest.TestCase):
    def test_scope_observations_and_scheduling_authority(self):
        unavailable = [
            {'status': 503, 'body': {}},
            {'status': 429, 'body': {}},
            {'status': 200, 'body': {'aud': 'another-client', 'scope': ' '.join(SCOPES)}},
            {'status': 200, 'body': {'aud': 'test-client'}},
            AlphaError('Synthetic tokeninfo network outage', 503),
        ]
        for observation in unavailable:
            with self.subTest(observation=observation):
                service, repo, _ = service_for(observation)
                original = copy.deepcopy(repo.state)
                with self.assertRaises(AlphaError) as failure:
                    service.token_for_worker('workspace', 'connection')
                self.assertEqual((failure.exception.status, failure.exception.code), (503, 'youtube_verification_unavailable'))
                self.assertEqual(service.verify('workspace', 'session', 'connection')['state'], 'verification_unavailable')
                self.assertEqual(service.reverify_for_worker('workspace', 'connection')['state'], 'verification_unavailable')
                self.assertEqual(repo.scopes, SCOPES)
                self.assertEqual(repo.state, original)
                self.assertFalse(any(sql.startswith('UPDATE ') for sql, _ in repo.executed))
                service.mark_youtube_revoked.assert_not_called()

        service, repo, _ = service_for({'status': 200, 'body': {'aud': 'test-client', 'scope': ''}})
        self.assertEqual(service.token_for_worker('workspace', 'connection')['scopes'], [])
        self.assertEqual(repo.scopes, [])
        self.assertEqual(service.reverify_for_worker('workspace', 'connection')['state'], 'scope_missing')
        self.assertFalse(repo.state['phase2']['channels'][0]['capabilityVerified'])

        service, _, _ = service_for({'status': 401, 'body': {'error': 'invalid_token'}})
        with self.assertRaises(AlphaError) as revoked:
            service.token_for_worker('workspace', 'connection')
        self.assertEqual(revoked.exception.code, 'youtube_revoked_oauth')
        service.mark_youtube_revoked.assert_called_once_with('workspace', 'connection',
                                                           expected_ciphertext=TOKEN, expected_generation=GENERATION)

        service, repo, provider = service_for({'status': 200, 'body': {'aud': 'test-client', 'scope': ' '.join(SCOPES)}})
        self.assertEqual(set(service.token_for_worker('workspace', 'connection')['scopes']), set(SCOPES))
        self.assertTrue(repo.state['phase2']['channels'][0]['capabilityVerified'])

        api = YouTubeApi(provider, {'accessToken': TOKEN, 'scopes': SCOPES}, CHANNEL, clock=lambda: NOW)
        current = {'id': VIDEO, 'snippet': {'title': 'Original', 'description': '', 'categoryId': '22'},
            'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': False}}
        api.owned = Mock(return_value=current)
        for publish_at in ('2099-01-01T00:00:00Z', None):
            with self.subTest(generic_edit_publish_at=publish_at), self.assertRaises(AlphaError) as bypass:
                api.plan('video.edit', {'id': VIDEO, 'patch': {'status': {'privacyStatus': 'private', 'publishAt': publish_at}}}, never_published=True)
            self.assertEqual(bypass.exception.code, 'youtube_invalid_scheduling_state')
        api.owned.assert_not_called()
        self.assertEqual(api.plan('video.schedule', {'id': VIDEO, 'publishAt': '2099-01-01T00:00:00Z'}, never_published=True)['body']['status']['publishAt'], '2099-01-01T00:00:00Z')
        self.assertEqual(api.plan('video.edit', {'id': VIDEO, 'patch': {'snippet': {'title': 'Reviewed title'}}})['body']['snippet']['title'], 'Reviewed title')

        api.owned.return_value = copy.deepcopy(current)
        api.owned.return_value['status']['publishAt'] = '2099-01-01T00:00:00Z'
        cancellation = api.plan('video.cancel_schedule', {'id': VIDEO}, never_published=True)
        api.call = Mock(side_effect=AssertionError('Read-back must not repeat the write'))
        self.assertFalse(YouTubeCreatorService.verify_action(api, cancellation, {'id': VIDEO})['verified'])
        api.owned.return_value['status'].pop('publishAt')
        self.assertTrue(YouTubeCreatorService.verify_action(api, cancellation, {'id': VIDEO})['verified'])
        api.owned.return_value['status']['publishAt'] = None
        self.assertTrue(YouTubeCreatorService.verify_action(api, cancellation, {'id': VIDEO})['verified'])
        api.owned.return_value['id'] = 'different01'
        self.assertFalse(YouTubeCreatorService.verify_action(api, cancellation, {'id': 'different01'})['verified'])
        api.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
