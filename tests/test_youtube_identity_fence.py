"""Synthetic OAuth identity/picture fences; real PostgreSQL races have a separate group."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
from postriff_phase2.oauth import OAuthService
from postriff_phase2.youtube.model import READ, UPLOAD
from postriff_phase2.youtube.provider import YouTubeProvider


NOW, ACCESS = 1_800_000_000, 'synthetic-same-access-token'
CHANNEL, DRIFT = 'UC' + 'i' * 22, 'UC' + 'j' * 22
SCOPES = [READ, UPLOAD]


class IdentityDatabase:
    """Strict, rollback-capable SQL model, not a substitute for the PG group."""
    def __init__(self, provider='youtube'):
        self.provider, self.depth, self.revision = provider, 0, 1
        self.connection = OAuthService._connection_id(provider, CHANNEL)
        self.generation, self.consent_count, self.revoked = 'consent-1', 1, False
        self.account, self.access, self.scopes, self.identity_at = CHANNEL, ACCESS, list(SCOPES), None
        self.pictures, self.capabilities, self.sql = {}, [], []
        self.state = {'phase2': {'channels': [self.channel('Original provider title')], 'jobs': [], 'reviews': []}}
        self.rowcount, self.result = 1, None

    def channel(self, title):
        return {'id': self.connection, 'platform': 'YouTube' if self.provider == 'youtube' else 'LinkedIn',
                'account': title, 'providerAccountId': CHANNEL, 'accountType': 'channel',
                'configured': True, 'identityVerified': True, 'capabilityVerified': True, 'revoked': False,
                'scopes': list(SCOPES), 'verifiedAt': NOW - 60, 'expiresAt': NOW + 3600, 'capabilityVersion': 2}

    def replace(self):
        self.consent_count += 1
        self.generation, self.revoked = f'consent-{self.consent_count}', False
        self.state['phase2']['channels'] = [self.channel('Replacement consent title')]
        self.identity_at = NOW - 1
        self.revision += 1

    def disconnect(self):
        self.revoked = True
        self.pictures.clear()
        self.state['phase2']['channels'] = [{'id': self.connection, 'platform': 'YouTube',
            'account': 'YouTube data removed', 'revoked': True, 'youtubeProviderDataRemoved': True}]
        self.revision += 1

    def durable(self):
        return copy.deepcopy((self.state, self.revision, self.generation, self.revoked,
                              self.account, self.access, self.scopes, self.identity_at, self.pictures, self.capabilities))

    @contextmanager
    def connection_factory(self):
        before = self.durable()
        self.depth += 1
        try:
            yield self
        except Exception:
            (self.state, self.revision, self.generation, self.revoked, self.account, self.access,
             self.scopes, self.identity_at, self.pictures, self.capabilities) = before
            raise
        finally:
            self.depth -= 1

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        self.rowcount, self.result = 1, None
        if sql.startswith('SELECT w.revision,w.state,'):
            self.result = (self.revision, copy.deepcopy(self.state), 'owner', True, False, False, False)
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.result = (copy.deepcopy(self.state),)
        elif sql.startswith('SELECT id FROM public.pr_workspaces'):
            self.result = ('workspace',)
        elif sql.startswith('SELECT provider,provider_account_id,scopes,access_ciphertext,key_id'):
            self.result = (self.provider, self.account, list(self.scopes), self.access, 'test') if not self.revoked else None
        elif sql.startswith('SELECT c.provider,c.provider_account_id,w.state'):
            self.result = (self.provider, self.account, copy.deepcopy(self.state)) if not self.revoked else None
        elif sql.startswith('SELECT access_ciphertext,key_id,scopes'):
            self.result = (self.access, 'test', list(self.scopes)) if not self.revoked else None
        elif sql.startswith('SELECT access_ciphertext,key_id FROM'):
            self.result = (self.access, 'test') if not self.revoked else None
        elif sql.startswith('SELECT authorization_generation::text FROM'):
            self.result = (self.generation,) if not self.revoked else None
        elif sql.startswith('SELECT id::text,member_id::text,provider,capability'):
            self.result = ('txn', 'user', 'youtube', 'publish', 'https://rafii.example/api/oauth/youtube/callback',
                           list(SCOPES), 'synthetic-pkce', 'test', NOW + 600, False)
        elif sql.startswith('UPDATE public.pr_oauth_transactions'):
            pass
        elif sql.startswith('INSERT INTO public.pr_encrypted_credentials'):
            self.consent_count += 1
            self.generation, self.revoked = f'consent-{self.consent_count}', False
            self.account, self.access, self.scopes = params[3], params[4], list(params[7])
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET provider_account_id='):
            self.account, self.identity_at = params[:2]
            self.result = (self.generation,)
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET youtube_identity_ingested_at='):
            observed, _, _, generation, account = params
            self.rowcount = int(not self.revoked and generation == self.generation and account == self.account)
            if self.rowcount:
                self.identity_at = observed
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET scopes='):
            self.scopes = list(params[0])
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET revoked_at='):
            self.revoked, self.access, self.scopes = True, '', []
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.state, self.revision = json.loads(params[0]), self.revision + 1
        elif sql.startswith('UPDATE public.pr_channel_capabilities'):
            self.capabilities.append(params)
        elif sql.startswith('INSERT INTO public.pr_channel_pictures'):
            self.pictures[params[1]] = tuple(params[2:])
        elif sql.startswith('DELETE FROM public.pr_channel_pictures'):
            self.pictures.pop(params[1], None)
        elif sql.startswith(('SAVEPOINT ', 'RELEASE SAVEPOINT ', 'ROLLBACK TO SAVEPOINT ',
                             'INSERT INTO public.pr_audit_events', 'INSERT INTO public.pr_channel_capabilities')):
            pass
        else:
            raise AssertionError('Unexpected identity-fence fixture SQL: ' + sql)

    def fetchone(self):
        return self.result


def identity_service(provider_id='youtube'):
    db = IdentityDatabase(provider_id)
    commands = HostedPhase2Commands.__new__(HostedPhase2Commands)
    commands.engine = SimpleNamespace(invalidate=Mock(), channel_state=lambda _: 'Ready for posting')
    verify = lambda _token: 'user'
    repo = PostgresWorkspaceRepository(db.connection_factory, verify, commands, clock=lambda: NOW)
    provider = YouTubeProvider('synthetic-identity.apps.googleusercontent.com', 'synthetic-secret',
        transport=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('No external I/O.')), creator_enabled=True)
    provider.identity = Mock(return_value={'providerAccountId': CHANNEL, 'handle': 'Fresh provider title'})
    provider.exchange = Mock(return_value={'accessToken': ACCESS, 'refreshToken': 'synthetic-refresh',
                                         'scopes': list(SCOPES), 'expiresIn': 3600})
    vault = SimpleNamespace(encrypt=lambda value: (value, 'test'), decrypt=lambda value, _key: value)
    oauth = OAuthService(repo, commands, vault, {provider_id: provider}, 'https://rafii.example', clock=lambda: NOW)
    oauth.youtube_policy = SimpleNamespace(require_user=Mock(), require_pending=Mock(), bind=Mock())

    def token(*_args):
        assert db.depth == 0, 'Provider observation must follow the short workspace transaction.'
        return {'provider': provider_id, 'accessToken': db.access, 'scopes': list(db.scopes),
                'expiresAt': NOW + 3600, 'authorizationGeneration': db.generation}

    oauth.token_for_worker = Mock(side_effect=token)
    oauth.provider_for_grant = Mock(return_value=provider)
    # OAuth client-envelope parsing is covered separately; this fixture models
    # the observed token/grant and exercises the actual generation/save fences.
    oauth._provider_for_access = Mock(return_value=provider)
    return oauth, db, provider


class YouTubeIdentityFenceTests(unittest.TestCase):
    def test_same_token_replacement_rejects_manual_match_drift_and_error_without_changes(self):
        for outcome in ('match', 'drift', 'error'):
            with self.subTest(outcome=outcome):
                oauth, db, provider = identity_service()
                expected = []

                def late_identity(_access):
                    db.replace()
                    expected.append(db.durable())
                    if outcome == 'error':
                        raise AlphaError('Synthetic identity error.', 503, code='synthetic_identity_error')
                    return {'providerAccountId': DRIFT if outcome == 'drift' else CHANNEL, 'handle': 'Stale title'}

                provider.identity.side_effect = late_identity
                with self.assertRaises(AlphaError) as caught:
                    oauth.verify('workspace', 'session', db.connection)
                self.assertEqual(caught.exception.code, 'youtube_connection_changed')
                self.assertEqual(db.durable(), expected[0])
                self.assertEqual(db.access, ACCESS)

    def test_same_token_replacement_preserves_worker_match_drift_and_error(self):
        for outcome in ('match', 'drift', 'error'):
            with self.subTest(outcome=outcome):
                oauth, db, provider = identity_service()
                expected = []

                def late_identity(_access):
                    db.replace()
                    expected.append(db.durable())
                    if outcome == 'error':
                        raise AlphaError('Synthetic identity error.', 503)
                    return {'providerAccountId': DRIFT if outcome == 'drift' else CHANNEL}

                provider.identity.side_effect = late_identity
                if outcome == 'error':
                    self.assertFalse(oauth.reverify_for_worker('workspace', db.connection)['ready'])
                else:
                    with self.assertRaises(AlphaError) as caught:
                        oauth.reverify_for_worker('workspace', db.connection)
                    self.assertEqual(caught.exception.code, 'youtube_connection_changed')
                self.assertEqual(db.durable(), expected[0])

    def test_current_manual_and_worker_identity_refresh_remain_available(self):
        for manual in (True, False):
            with self.subTest(manual=manual):
                oauth, db, _ = identity_service()
                result = oauth.verify('workspace', 'session', db.connection) if manual else oauth.reverify_for_worker('workspace', db.connection)
                self.assertEqual(result['state'], 'read_verified')
                self.assertEqual(db.identity_at, NOW)
                self.assertEqual(db.state['phase2']['channels'][0]['account'], 'Fresh provider title')
                self.assertEqual(db.generation, 'consent-1')

    def test_genuine_current_identity_restores_removed_profile_without_restoring_authority(self):
        for manual in (True, False):
            with self.subTest(manual=manual):
                oauth, db, _ = identity_service()
                profile = db.state['phase2']['channels'][0]
                profile.pop('providerAccountId')
                profile.update(account='YouTube data removed', configured=False, revoked=True,
                               identityVerified=False, capabilityVerified=False, youtubeProviderDataRemoved=True)
                db.state['phase2']['jobs'] = [{'id': 'erased-job', 'state': 'held', 'privacyErased': True}]
                db.state['phase2']['reviews'] = [{'id': 'erased-review', 'status': 'privacy_erased', 'privacyErased': True}]
                jobs, reviews = copy.deepcopy(db.state['phase2']['jobs']), copy.deepcopy(db.state['phase2']['reviews'])
                result = oauth.verify('workspace', 'session', db.connection) if manual else oauth.reverify_for_worker('workspace', db.connection)
                self.assertEqual(result['state'], 'read_verified')
                restored = db.state['phase2']['channels'][0]
                self.assertEqual(restored['providerAccountId'], CHANNEL)
                self.assertTrue(restored['configured'] and restored['identityVerified'])
                self.assertFalse(restored['revoked'] or restored['capabilityVerified'])
                self.assertNotIn('youtubeProviderDataRemoved', restored)
                self.assertEqual(restored['youtubeIdentityIngestedAt'], NOW)
                self.assertEqual(db.identity_at, NOW)
                self.assertEqual((db.state['phase2']['jobs'], db.state['phase2']['reviews']), (jobs, reviews))

    def test_completion_after_disconnect_or_new_consent_rolls_back_profile_save(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                oauth, db, _ = identity_service()
                original_get, expected = oauth.repository.get, []

                def changed_after_custody(*args):
                    db.disconnect()
                    if replacement:
                        db.replace()
                    expected.append(db.durable())
                    return original_get(*args)

                with patch.object(oauth.repository, 'get', side_effect=changed_after_custody), \
                     patch('postriff_phase2.billing.require_plan_capacity'), \
                     patch('postriff_phase2.product_events.record'):
                    with self.assertRaises(AlphaError) as caught:
                        oauth._complete('workspace', 'session', 'youtube', 'x' * 32, 'synthetic-code')
                self.assertEqual(caught.exception.code, 'youtube_connection_changed')
                self.assertEqual(db.durable(), expected[0])

    def test_current_completion_saves_profile_and_captures_picture_generation(self):
        oauth, db, _ = identity_service()
        with patch('postriff_phase2.billing.require_plan_capacity'), \
             patch('postriff_phase2.product_events.record'), patch.object(oauth, '_keep_picture') as picture:
            result = oauth._complete('workspace', 'session', 'youtube', 'x' * 32, 'synthetic-code')
        self.assertTrue(result['connected'])
        self.assertEqual(db.state['phase2']['channels'][0]['account'], 'Fresh provider title')
        self.assertEqual(picture.call_args.kwargs, {'youtube_generation': db.generation})

    def test_late_picture_cannot_restore_disconnected_or_replaced_image(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                oauth, db, _ = identity_service()
                previous = db.generation

                def fetched(*_args):
                    db.disconnect()
                    if replacement:
                        db.replace()
                        db.pictures[db.connection] = (b'new-consent-picture', 'new-digest')
                    return 'ok', (b'stale-picture', 'stale-digest')

                with patch('postriff_phase2.oauth.account_pictures.picture_from_identity', side_effect=fetched):
                    oauth._keep_picture('workspace', 'session', db.connection, {}, youtube_generation=previous)
                expected = {db.connection: (b'new-consent-picture', 'new-digest')} if replacement else {}
                self.assertEqual(db.pictures, expected)
                self.assertFalse(any(sql.startswith('INSERT INTO public.pr_channel_pictures') for sql, _ in db.sql))

    def test_current_picture_write_orders_workspace_before_credential(self):
        oauth, db, _ = identity_service()
        with patch('postriff_phase2.oauth.account_pictures.picture_from_identity', return_value=('ok', (b'picture', 'digest'))):
            oauth._keep_picture('workspace', 'session', db.connection, {}, youtube_generation=db.generation)
        self.assertEqual(db.pictures[db.connection], (b'picture', 'digest'))
        workspace = next(i for i, (sql, _) in enumerate(db.sql) if 'FOR UPDATE OF w' in sql)
        credential = next(i for i, (sql, _) in enumerate(db.sql) if 'FOR NO KEY UPDATE' in sql)
        insert = next(i for i, (sql, _) in enumerate(db.sql) if sql.startswith('INSERT INTO public.pr_channel_pictures'))
        self.assertLess(workspace, credential)
        self.assertLess(credential, insert)

    def test_stale_or_missing_generation_cannot_revoke_same_token_new_consent(self):
        oauth, db, _ = identity_service()
        old = db.generation
        db.replace()
        before = db.durable()
        with patch('postriff_phase2.youtube.journal.purge_authorized_data') as purge:
            for generation in (None, old):
                self.assertFalse(oauth.mark_youtube_revoked('workspace', db.connection,
                    expected_access_token=ACCESS, expected_generation=generation))
            purge.assert_not_called()
        self.assertEqual(db.durable(), before)

    def test_revocation_error_preserves_observed_generation(self):
        oauth, db, _ = identity_service()
        error = AlphaError('Synthetic rejected token.', 401, code='youtube_revoked_oauth')
        with self.assertRaises(AlphaError):
            with oauth._credential_errors('youtube', 'observed-ciphertext', db.generation):
                raise error
        self.assertEqual(error.credential_revocation_ciphertext, 'observed-ciphertext')
        self.assertEqual(error.credential_revocation_generation, db.generation)

    def test_non_youtube_verification_and_picture_do_not_require_generation(self):
        oauth, db, _ = identity_service('linkedin')
        self.assertEqual(oauth.verify('workspace', 'session', db.connection)['state'], 'read_verified')
        with patch('postriff_phase2.oauth.account_pictures.picture_from_identity', return_value=('ok', (b'ordinary', 'ordinary-digest'))):
            oauth._keep_picture('workspace', 'session', db.connection, {})
        self.assertEqual(db.pictures[db.connection], (b'ordinary', 'ordinary-digest'))
        self.assertFalse(any('authorization_generation' in sql for sql, _ in db.sql))


if __name__ == '__main__':
    unittest.main()
