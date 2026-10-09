"""Authenticated composer freshness controls; synthetic grants, no Google or real acceptance."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted import HostedWorkspaceService, PostgresWorkspaceRepository
from postriff_phase2.oauth import OAuthService
from postriff_phase2.store import Phase2Store


NOW, TOKEN = 1_800_000_000, 'synthetic-access'


class ComposerDatabase:
    def __init__(self, connections=1):
        self.revision, self.role, self.can_publish, self.depth = 12, 'approver', False, 0
        self.rowcount, self.result, self.counts, self.audits = 1, None, {}, []
        self.revocation_locks = []
        self.purge_context, self.purge_queries = None, []
        self.credentials, self.state = {}, {'variants': [{'id': 'draft'}], 'phase2': {'channels': [], 'reviews': [], 'jobs': []}}
        for index in range(connections):
            connection = f'connection-{index}'
            account = f'UC-synthetic-{index}'
            scopes = ['youtube.upload', 'youtube.readonly']
            channel = {'id': connection, 'platform': 'YouTube', 'configured': True, 'revoked': False,
                       'identityVerified': True, 'capabilityVerified': True, 'expiresAt': NOW - 1,
                       'verifiedAt': NOW - 3601, 'scopes': scopes, 'providerAccountId': account,
                       'capabilityVersion': 1}
            manifest = {'workspaceId': 'workspace', 'platform': 'YouTube', 'channelId': connection, 'actor': 'user',
                        'providerAccountId': account, 'expiresAt': NOW + 3600,
                        'capability': {'scopes': list(scopes), 'version': 1}}
            self.state['phase2']['channels'].append(channel)
            self.state['phase2']['reviews'].append({'id': f'review-{index}', 'manifest': manifest,
                                                   'digest': digest(manifest), 'status': 'needs_review'})
            self.credentials[connection] = {'account': account, 'refresh': True, 'present': True,
                'expires': NOW - 1, 'revoked': False, 'scopes': list(scopes), 'token': TOKEN,
                'generation': 'synthetic-consent-generation', 'identity_ingested_at': None}

    @contextmanager
    def connection_factory(self):
        self.depth += 1
        try:
            yield self
        finally:
            self.depth -= 1

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith('SELECT w.revision,w.state,'):
            self.result = ((self.revision, copy.deepcopy(self.state), self.role, self.can_publish, False, False, False)
                           if params == ('workspace', 'user') else None)
        elif sql == 'SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE':
            assert params == ('workspace',)
            self.revocation_locks.append('workspace')
            self.result = ('workspace',)
        elif sql == "SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube'":
            assert self.revocation_locks[-2:] == ['workspace', 'credential']
            credential = self.credentials.get(params[1]) if params[0] == 'workspace' else None
            # Purge still needs the canonical channel after the token is wiped.
            # This SELECT deliberately includes already-revoked credentials.
            self.result = (credential['account'],) if credential else None
            self.purge_context = (*params, credential['account'] if credential else None)
            self.purge_queries.append(('provenance', params))
        elif sql.startswith('SELECT provider_account_id,refresh_supported,'):
            credential = self.credentials.get(params[1]) if params[0] == 'workspace' else None
            self.result = ((credential['account'], credential['refresh'], credential['present'], credential['expires'])
                           if credential and not credential['revoked'] else None)
        elif sql.startswith('INSERT INTO public.pr_auth_throttle'):
            self.counts[params[0]] = self.counts.get(params[0], 0) + 1
            self.result = (self.counts[params[0]],)
        elif sql.startswith('SELECT c.provider,c.provider_account_id,w.state'):
            credential = self.credentials.get(params[1])
            self.result = (('youtube', credential['account'], copy.deepcopy(self.state))
                           if credential and not credential['revoked'] else None)
        elif sql.startswith('SELECT access_ciphertext,key_id,scopes'):
            credential = self.credentials[params[1]]
            self.result = ((credential['token'], 'test', list(credential['scopes'])) if not credential['revoked'] else None)
        elif sql.startswith('SELECT authorization_generation::text FROM public.pr_encrypted_credentials'):
            credential = self.credentials.get(params[1]) if params[0] == 'workspace' else None
            self.result = (credential['generation'],) if credential and not credential['revoked'] else None
        elif sql.startswith('SELECT access_ciphertext,key_id FROM'):
            if "provider='youtube'" in sql and sql.endswith('FOR UPDATE'):
                assert self.revocation_locks[-1:] == ['workspace'], 'Revocation must lock workspace before credential.'
                self.revocation_locks.append('credential')
            credential = self.credentials.get(params[1]) if params[0] == 'workspace' else None
            self.result = ((credential['token'], 'test') if credential and not credential['revoked'] else None)
        elif sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.result = (copy.deepcopy(self.state),)
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.state, self.revision = json.loads(params[0]), self.revision + 1
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET scopes='):
            self.credentials[params[2]]['scopes'] = list(params[0])
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET youtube_identity_ingested_at='):
            observed_at, workspace, connection, generation, account = params
            credential = self.credentials.get(connection) if workspace == 'workspace' else None
            self.rowcount = int(bool(credential and not credential['revoked']
                                    and credential['generation'] == generation and credential['account'] == account))
            if self.rowcount:
                credential['identity_ingested_at'] = observed_at
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET revoked_at='):
            self.credentials[params[1]].update(revoked=True, token='', refresh=False, scopes=[])
        elif (sql.startswith('SELECT id::text,run_id::text,body FROM public.pr_messages WHERE workspace_id=')
              or sql.startswith('SELECT id::text,artifact FROM public.pr_agent_runs WHERE workspace_id=')):
            workspace, connection, channel = self.purge_context
            key, tag = params[1:3]
            assert key == 'youtubeProviderContext'
            assert json.loads(tag) == [{'provider': 'youtube', 'workspaceId': workspace, 'connectionId': connection}]
            messages = sql.startswith('SELECT id::text,run_id::text,body')
            expected = (workspace, key, tag, connection, channel) if messages else (workspace, key, tag, key, tag, connection, channel)
            assert params == expected, 'Purge must use this exact workspace, connection and canonical channel.'
            self.purge_queries.append(('messages' if messages else 'runs', params))
            self.result = []  # This composer fixture contains no chat messages or agent runs.
        elif sql.startswith('SELECT operation_key,state FROM public.pr_youtube_uploads'):
            assert params == ('workspace', self.purge_context[1])
            self.purge_queries.append(('uploads', params))
            self.result = []  # No resumable upload sessions in this composer fixture.
        elif sql.startswith('SELECT public.pr_youtube_erase_audit_fields'):
            assert params == ('workspace', self.purge_context[1], None)
            self.purge_queries.append(('audit', params))
            self.result = (0,)
        elif sql.startswith('SELECT id::text,manifest FROM public.pr_youtube_actions'):
            assert params == ('workspace', self.purge_context[1])
            self.result = []
        elif sql.startswith('DELETE FROM public.pr_youtube_policy_bindings'):
            assert params == ('workspace', self.purge_context[1])
            self.rowcount = 0
        elif sql.startswith('UPDATE public.pr_encrypted_credentials SET provider_account_id='):
            assert params == ('workspace', self.purge_context[1])
            credential = self.credentials[params[1]]
            assert credential['revoked']
            credential['account'] = ''
            self.rowcount = 1
        elif sql == 'SELECT to_regclass(%s)':
            self.result = (None,)  # This focused composer fixture has no optional creator journals.
        elif sql.startswith('DELETE FROM public.pr_audience_threads'):
            pass
        elif sql.startswith('UPDATE public.pr_channel_capabilities'):
            pass
        elif sql.startswith('INSERT INTO public.pr_audit_events'):
            self.audits.append(params)
        else:
            raise AssertionError(f'Unexpected synthetic SQL: {sql}')

    def fetchone(self):
        return self.result

    def fetchall(self):
        assert isinstance(self.result, list), 'Only the modeled empty chat/run selections return row sets.'
        return copy.deepcopy(self.result)


def composer_for(connections=1):
    db = ComposerDatabase(connections)
    engine = Phase2Store.__new__(Phase2Store)
    engine.clock, engine.hosted_entitlements = lambda: NOW, True

    # Full source/media manifest contracts stay in the existing Phase2 suite.
    def current(state, manifest):
        channel = next(c for c in state['phase2']['channels'] if c['id'] == manifest['channelId'])
        return (channel['providerAccountId'] == manifest['providerAccountId']
                and channel['scopes'] == manifest['capability']['scopes']
                and channel['capabilityVersion'] == manifest['capability']['version'])

    engine.current = current

    def verify_session(token):
        if token != 'session':
            raise AlphaError('Verified session required.', 401)
        return 'user'

    verify_session.auth_time = lambda *_: NOW
    commands = SimpleNamespace(engine=engine)
    repo = PostgresWorkspaceRepository(db.connection_factory, verify_session, commands, clock=lambda: NOW)
    provider = SimpleNamespace(inspect_scopes=lambda *_: None, identity=Mock(return_value={'providerAccountId': 'UC-synthetic-0'}))
    oauth = OAuthService(repo, commands, SimpleNamespace(decrypt=lambda value, _: value),
                         {'youtube': provider}, 'https://rafii.example', clock=lambda: NOW)
    # Isolate age-recovery SQL; policy receipts and RLS use the dedicated real PG group.
    oauth.youtube_policy.require_user = Mock(return_value={'policyId': 'synthetic', 'receiptId': 'synthetic-user'})

    def token_for_worker(workspace, connection):
        assert db.depth == 0, 'The foreground workspace transaction must close before provider I/O.'
        assert workspace == 'workspace'
        credential = db.credentials[connection]
        provider.identity.return_value = {'providerAccountId': credential['account']}
        return {'provider': 'youtube', 'accessToken': credential['token'], 'expiresAt': NOW + 3600,
                'providerAccountId': credential['account'], 'scopes': list(credential['scopes']),
                'authorizationGeneration': credential['generation']}

    oauth.token_for_worker = Mock(side_effect=token_for_worker)
    service = HostedWorkspaceService.__new__(HostedWorkspaceService)
    service.repository, service.oauth, service._present = repo, oauth, lambda value: value
    repo.mutate = Mock(return_value={'revision': 99, 'state': {}})
    return service, oauth, db, provider, token_for_worker


def approval(db, index=0):
    review = db.state['phase2']['reviews'][index]
    return {'confirmed': True, 'reviewId': review['id'], 'digest': review['digest']}


class YouTubeComposerRefreshTests(unittest.TestCase):
    def test_fresh_channel_still_requires_the_actual_composer_actors_policy_acceptance(self):
        service, oauth, db, _, _ = composer_for()
        db.state['phase2']['channels'][0]['verifiedAt'] = NOW
        oauth.youtube_policy.require_user.side_effect = AlphaError('Synthetic missing agreement.', 409,
            code='youtube_policy_acceptance_required')
        with self.assertRaises(AlphaError) as caught:
            service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
        self.assertEqual(caught.exception.code, 'youtube_policy_acceptance_required')
        oauth.token_for_worker.assert_not_called()
        service.repository.mutate.assert_not_called()

    def test_authorized_creator_refreshes_then_explicitly_retries_same_review(self):
        service, oauth, db, _, _ = composer_for()
        before = copy.deepcopy(db.state['phase2']['reviews'])
        requested = approval(db)
        with self.assertRaises(AlphaError) as refreshed:
            service.mutate('workspace', 'session', 12, 'p2_approve', requested)
        self.assertEqual((refreshed.exception.status, refreshed.exception.code), (409, 'youtube_connection_refreshed'))
        self.assertEqual(db.revision, 13)
        self.assertEqual(db.state['phase2']['reviews'], before)
        self.assertEqual(db.state['phase2']['jobs'], [])
        self.assertEqual(db.state['phase2']['channels'][0]['expiresAt'], NOW + 3600)
        self.assertEqual(db.state['phase2']['channels'][0]['youtubeIdentityIngestedAt'], NOW)
        self.assertEqual(db.credentials['connection-0']['identity_ingested_at'], NOW)
        self.assertEqual(db.state['phase2']['channels'][0]['account'], 'UC-synthetic-0')
        service.repository.mutate.assert_not_called()
        self.assertEqual(db.audits[-1][1:3], ('user', oauth.COMPOSER_REVERIFIED))
        service.mutate('workspace', 'session', 13, 'p2_approve', requested)
        service.repository.mutate.assert_called_once_with('workspace', 'session', 13, 'p2_approve', requested)
        oauth.token_for_worker.assert_called_once_with('workspace', 'connection-0')

    def test_same_token_replacement_consent_cannot_refresh_old_identity_result(self):
        service, oauth, db, provider, _ = composer_for()
        before = copy.deepcopy(db.state)

        def replaced_identity(_access):
            db.credentials['connection-0']['generation'] = 'new-consent-same-token'
            return {'providerAccountId': db.credentials['connection-0']['account']}

        provider.identity.side_effect = replaced_identity
        with self.assertRaises(AlphaError) as caught:
            service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
        self.assertEqual(caught.exception.code, 'youtube_connection_changed')
        self.assertEqual(db.state, before)
        self.assertIsNone(db.credentials['connection-0']['identity_ingested_at'])
        service.repository.mutate.assert_not_called()

    def test_review_and_bulk_refresh_at_most_one_exact_selected_connection(self):
        service, oauth, db, _, _ = composer_for(2)
        request = {'confirmed': True, 'reviews': [approval(db, 1), approval(db, 0)]}
        with self.assertRaises(AlphaError) as refreshed:
            service.mutate('workspace', 'session', 12, 'p2_approve_many', request)
        self.assertEqual(refreshed.exception.code, 'youtube_connection_refreshed')
        oauth.token_for_worker.assert_called_once_with('workspace', 'connection-1')
        self.assertEqual(db.state['phase2']['channels'][0]['expiresAt'], NOW - 1)
        self.assertEqual(db.state['phase2']['channels'][1]['expiresAt'], NOW + 3600)
        service.repository.mutate.assert_not_called()
        with self.assertRaises(AlphaError) as refreshed_again:
            service.mutate('workspace', 'session', 13, 'p2_approve_many', request)
        self.assertEqual(refreshed_again.exception.code, 'youtube_connection_refreshed')
        self.assertEqual([call.args[1] for call in oauth.token_for_worker.call_args_list], ['connection-1', 'connection-0'])
        service.repository.mutate.assert_not_called()
        service.mutate('workspace', 'session', 14, 'p2_approve_many', request)
        service.repository.mutate.assert_called_once_with('workspace', 'session', 14, 'p2_approve_many', request)

        service, oauth, db, _, _ = composer_for(2)
        with self.assertRaises(AlphaError) as refreshed:
            service.mutate('workspace', 'session', 12, 'p2_review', {'variantId': 'draft', 'channelId': 'connection-1'})
        self.assertEqual(refreshed.exception.code, 'youtube_connection_refreshed')
        oauth.token_for_worker.assert_called_once_with('workspace', 'connection-1')

    def test_session_permission_revision_digest_and_batch_bounds_precede_provider_reads(self):
        for failure in ('session', 'workspace', 'viewer', 'editor', 'revision', 'digest', 'expired', 'batch_digest', 'batch_size', 'channel', 'draft_channel', 'draft_platform'):
            with self.subTest(failure=failure):
                service, oauth, db, _, _ = composer_for(2)
                workspace, token, revision, action, requested = 'workspace', 'session', 12, 'p2_approve', approval(db)
                if failure == 'session': token = 'invalid-session'
                elif failure == 'workspace': workspace = 'foreign-workspace'
                elif failure in ('viewer', 'editor'): db.role = failure
                elif failure == 'revision': revision = 11
                elif failure == 'digest': requested['digest'] = 'wrong'
                elif failure == 'expired':
                    db.state['phase2']['reviews'][0]['manifest']['expiresAt'] = NOW
                    db.state['phase2']['reviews'][0]['digest'] = digest(db.state['phase2']['reviews'][0]['manifest'])
                    requested = approval(db)
                elif failure == 'batch_digest':
                    action, requested = 'p2_approve_many', {'confirmed': True, 'reviews': [approval(db), approval(db, 1) | {'digest': 'wrong'}]}
                elif failure == 'batch_size':
                    action, requested = 'p2_approve_many', {'confirmed': True, 'reviews': [approval(db)] * 11}
                elif failure == 'channel':
                    action, requested = 'p2_review', {'variantId': 'draft', 'channelId': {'untrusted': 'connection-0'}}
                else:
                    db.state['variants'][0].update({'channelId': 'connection-1'} if failure == 'draft_channel' else {'platform': 'LinkedIn'})
                    action, requested = 'p2_review', {'variantId': 'draft', 'channelId': 'connection-0'}
                with self.assertRaises(AlphaError):
                    service.mutate(workspace, token, revision, action, requested)
                oauth.token_for_worker.assert_not_called()
                service.repository.mutate.assert_not_called()
                self.assertEqual(db.revision, 12)

    def test_permission_revision_and_step_up_are_rechecked_at_commit(self):
        for change in ('permission', 'revision', 'step_up'):
            with self.subTest(change=change):
                service, oauth, db, provider, _ = composer_for()
                before = copy.deepcopy(db.state)

                def identity(_):
                    if change == 'permission': db.role = 'viewer'
                    elif change == 'revision': db.revision += 1
                    return {'providerAccountId': 'UC-synthetic-0'}

                provider.identity.side_effect = identity
                if change == 'step_up':
                    service.repository.assert_fresh = Mock(side_effect=[None, AlphaError('Sign in again.', 403)])
                with patch('postriff_phase2.permissions.STEP_UP_ACTIONS', {'p2_approve'}):
                    with self.assertRaises(AlphaError) as stopped:
                        service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
                self.assertEqual(stopped.exception.status, 409 if change == 'revision' else 403)
                self.assertEqual(db.state, before)
                service.repository.mutate.assert_not_called()

    def test_identity_or_scope_change_invalidates_review_without_capability_upgrade(self):
        for change in ('identity', 'scopes'):
            with self.subTest(change=change):
                service, oauth, db, provider, token_for_worker = composer_for()
                original_manifest = copy.deepcopy(db.state['phase2']['reviews'][0]['manifest'])
                if change == 'identity':
                    provider.identity.side_effect = lambda *_: {'providerAccountId': 'UC-changed-channel'}
                else:
                    oauth.token_for_worker.side_effect = lambda *args: token_for_worker(*args) | {'scopes': ['youtube.readonly']}
                with self.assertRaises(AlphaError) as stopped:
                    service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
                self.assertEqual(stopped.exception.code, 'youtube_connection_changed')
                self.assertFalse(db.state['phase2']['channels'][0]['capabilityVerified'])
                review = db.state['phase2']['reviews'][0]
                self.assertEqual(review['status'], 'privacy_erased' if change == 'identity' else 'stale')
                self.assertEqual(review['digest'], digest(original_manifest))
                if change == 'identity':
                    self.assertTrue(review['privacyErased'] and review['manifest']['privacyErased'])
                    self.assertNotIn('providerAccountId', review['manifest'])
                    self.assertNotIn('account', review['manifest'])
                    for field in ('workspaceId', 'actor', 'channelId', 'capability', 'expiresAt'):
                        self.assertEqual(review['manifest'][field], original_manifest[field])
                else:
                    self.assertEqual(review['manifest'], original_manifest)
                self.assertEqual(db.state['phase2']['jobs'], [])
                self.assertEqual(db.credentials['connection-0']['revoked'], change == 'identity')
                self.assertEqual(db.revocation_locks, ['workspace', 'credential'] if change == 'identity' else [])
                self.assertEqual([kind for kind, _ in db.purge_queries], ['provenance', 'messages', 'runs', 'uploads', 'audit'] if change == 'identity' else [])
                self.assertEqual(db.purge_context, ('workspace', 'connection-0', 'UC-synthetic-0') if change == 'identity' else None)
                service.repository.mutate.assert_not_called()

    def test_stale_revocation_observation_cannot_purge_the_current_composer_grant(self):
        _, oauth, db, _, _ = composer_for()
        before = copy.deepcopy(db.credentials['connection-0'])
        self.assertFalse(oauth.mark_youtube_revoked('workspace', 'connection-0', expected_access_token='older-grant', expected_generation='synthetic-consent-generation'))
        self.assertEqual(db.credentials['connection-0'], before)
        self.assertEqual(db.audits, [])
        self.assertEqual(db.revocation_locks, ['workspace', 'credential'])
        self.assertEqual(db.purge_queries, [])
        self.assertTrue(oauth.mark_youtube_revoked('workspace', 'connection-0', expected_access_token=TOKEN, expected_generation='synthetic-consent-generation'))
        self.assertTrue(db.credentials['connection-0']['revoked'])
        self.assertEqual(db.credentials['connection-0']['token'], '')
        self.assertEqual(db.revocation_locks, ['workspace', 'credential'] * 2)
        self.assertEqual([kind for kind, _ in db.purge_queries], ['provenance', 'messages', 'runs', 'uploads', 'audit'])
        self.assertEqual(db.purge_context, ('workspace', 'connection-0', 'UC-synthetic-0'))

    def test_missing_refresh_revocation_and_transient_rate_limits_fail_closed(self):
        for cause in ('missing_refresh', 'revoked'):
            with self.subTest(cause=cause):
                service, oauth, db, _, _ = composer_for()
                db.credentials['connection-0'].update({'present': False} if cause == 'missing_refresh' else {'revoked': True})
                with self.assertRaises(AlphaError) as stopped:
                    service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
                self.assertEqual(stopped.exception.code, 'youtube_reconnect_required')
                oauth.token_for_worker.assert_not_called()
                service.repository.mutate.assert_not_called()

        service, oauth, db, _, _ = composer_for()
        before = copy.deepcopy(db.state)
        oauth.token_for_worker.side_effect = AlphaError('Synthetic provider unavailable', 503)
        for expected in (503, 503, 429):
            with self.assertRaises(AlphaError) as stopped:
                service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
            self.assertEqual(stopped.exception.status, expected)
        self.assertEqual(oauth.token_for_worker.call_count, 2)
        self.assertEqual(db.state, before)
        self.assertEqual(db.revision, 12)
        service.repository.mutate.assert_not_called()

        service, oauth, db, _, _ = composer_for(11)
        oauth.token_for_worker.side_effect = AlphaError('Synthetic provider unavailable', 503)
        for index in range(11):
            with self.assertRaises(AlphaError) as stopped:
                service.mutate('workspace', 'session', 12, 'p2_review', {'variantId': 'draft', 'channelId': f'connection-{index}'})
            self.assertEqual(stopped.exception.status, 503 if index < 10 else 429)
        self.assertEqual(oauth.token_for_worker.call_count, 10)
        service.repository.mutate.assert_not_called()

    def test_credential_rotation_and_worker_wrapper_preserve_existing_boundaries(self):
        service, oauth, db, provider, _ = composer_for()

        def rotate(_):
            db.credentials['connection-0']['token'] = 'new-person-authorized-token'
            return {'providerAccountId': 'UC-synthetic-0'}

        provider.identity.side_effect = rotate
        with self.assertRaises(AlphaError) as unavailable:
            service.mutate('workspace', 'session', 12, 'p2_approve', approval(db))
        self.assertEqual(unavailable.exception.code, 'youtube_verification_unavailable')
        self.assertEqual(db.state['phase2']['channels'][0]['expiresAt'], NOW - 1)
        service.repository.mutate.assert_not_called()

        _, oauth, db, _, _ = composer_for()
        db.role = 'viewer'  # Worker authority remains server-only; foreground still denies this role.
        self.assertTrue(oauth.reverify_for_worker('workspace', 'connection-0')['ready'])
        self.assertEqual(db.audits[-1][1:3], (None, oauth.WORKER_REVERIFIED))


if __name__ == '__main__':
    unittest.main()
