"""Offline regression tests for first-deployment social readiness and import safety."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import providers, social_history, voice_analysis
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault, OAuthService
from test_postriff_providers import Recorder
from test_postriff_voice_analysis import add_sample
import test_social_voice_services as fixtures


class ReadinessTests(unittest.TestCase):
    def catalog(self, values):
        registry = providers.registry_from_environment(values)
        service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), registry, 'https://app.example')
        return {p['id']: p for p in service.provider_catalog()}

    def test_partial_credentials_identify_only_the_missing_name(self):
        item = self.catalog({'POSTRIFF_OAUTH_INSTAGRAM_CLIENT_ID': 'synthetic-id'})['instagram']
        self.assertEqual(item.get('configurationState'), 'partial_configuration')
        self.assertEqual(item.get('credentialPresence'), {'clientId': True, 'clientSecret': False})
        self.assertIn('POSTRIFF_OAUTH_INSTAGRAM_CLIENT_SECRET', ' '.join(item['setupIssues']))
        self.assertNotIn('synthetic-id', json.dumps(item))
        self.assertFalse(item['connectReady'])

    def test_all_missing_and_configured_review_states_are_distinct(self):
        self.assertEqual(self.catalog({})['instagram'].get('readinessState'), 'not_configured')
        values = {'POSTRIFF_OAUTH_INSTAGRAM_CLIENT_ID': 'id', 'POSTRIFF_OAUTH_INSTAGRAM_CLIENT_SECRET': 'synthetic'}
        item = self.catalog(values)['instagram']
        self.assertTrue(item['connectReady'])
        self.assertEqual(item.get('readinessState'), 'configured_awaiting_provider_review')
        self.assertFalse(item.get('publicConnectionReady', True))
        item = self.catalog({**values, 'POSTRIFF_OAUTH_INSTAGRAM_REVIEWED': 'true'})['instagram']
        self.assertEqual(item.get('readinessState'), 'identity_connection_available')
        self.assertFalse(item.get('liveVerified', True))

    def test_blank_and_placeholder_credentials_do_not_mount_adapters(self):
        for bad in (' ', '\n', '<replace-me>', 'change-me'):
            with self.subTest(bad=bad):
                values = {'POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID': 'id', 'POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET': bad}
                self.assertNotIn('linkedin', providers.registry_from_environment(values))
                self.assertFalse(self.catalog(values)['linkedin']['connectReady'])

    def test_linkedin_scope_parser_accepts_commas_without_inventing_read_scope(self):
        adapter = providers.LinkedInProvider('id', 's', transport=Recorder([{'status': 200, 'body': {'access_token': 'synthetic', 'scope': 'openid,profile,w_member_social', 'expires_in': 3600}}]))
        self.assertEqual(adapter.exchange('c', 'v', 'https://app.example/cb')['scopes'], ['openid', 'profile', 'w_member_social'])

    def test_readiness_never_equates_identity_or_publish_with_history(self):
        method = getattr(OAuthService, 'connection_readiness', None)
        self.assertTrue(callable(method), 'Expose independent connected/history/publish readiness')
        if not callable(method):
            return
        service = OAuthService(None, None, CredentialVault(None), {}, 'https://app.example')
        channel = {'platform': 'LinkedIn', 'connectionState': 'read_verified', 'scopes': ['openid', 'profile', 'w_member_social'], 'capabilities': {'publish': {'level': 'Direct'}}}
        item = service.connection_readiness(channel, {'configured': True, 'connectReady': True, 'historyAvailableForApp': False, 'productionReviewed': True})
        self.assertEqual(item['connection'], 'CONNECTED')
        self.assertEqual(item['history'], 'HISTORICAL_IMPORT_AWAITING_PROVIDER_APPROVAL')
        self.assertEqual(item['publishing'], 'PUBLISHING_AVAILABLE')
        self.assertFalse(item['fullyAvailable'])
        channel['scopes'].append('r_member_social')
        ready = service.connection_readiness(channel, {'configured': True, 'connectReady': True, 'historyAvailableForApp': True, 'productionReviewed': True})
        self.assertTrue(ready['fullyAvailable'])


class TokenLifecycleTests(unittest.TestCase):
    def service(self, expires, issued_at=1795000000):
        repo = fixtures.Repository()
        vault = CredentialVault(CredentialVault.generate_key())
        encrypted, key = vault.encrypt('synthetic-old')
        repo.credential = ('instagram', encrypted, encrypted, key, expires, True, False, ['instagram_business_basic'], '1789', issued_at)
        adapter = providers.InstagramProvider('id', 's')
        adapter.refresh = Mock(return_value={'accessToken': 'synthetic-new', 'refreshToken': 'synthetic-new', 'expiresIn': 5184000})
        service = OAuthService(repo, None, vault, {'instagram': adapter}, 'https://app.example', clock=lambda: 1800000000)
        return service, adapter

    def test_instagram_renews_a_still_valid_token_before_expiry(self):
        service, adapter = self.service(1800000000 + 86400)
        grant = service.token_for_worker('workspace', 'connection')
        adapter.refresh.assert_called_once_with('synthetic-old')
        self.assertEqual(grant['accessToken'], 'synthetic-new')

    def test_expired_instagram_token_requires_reauthorization_not_refresh(self):
        service, adapter = self.service(1799999999)
        with self.assertRaises(AlphaError):
            service.token_for_worker('workspace', 'connection')
        adapter.refresh.assert_not_called()

    def test_instagram_token_under_24_hours_old_is_not_refreshed_even_near_expiry(self):
        service, adapter = self.service(1800000000 + 3600, issued_at=1800000000 - 60)
        self.assertEqual(service.token_for_worker('workspace', 'connection')['accessToken'], 'synthetic-old')
        adapter.refresh.assert_not_called()

    def test_unknown_instagram_token_age_never_authorizes_refresh(self):
        service, adapter = self.service(1800000000 + 3600, issued_at=None)
        self.assertEqual(service.token_for_worker('workspace', 'connection')['accessToken'], 'synthetic-old')
        adapter.refresh.assert_not_called()

    def test_recent_instagram_token_is_not_refreshed_on_every_read(self):
        service, adapter = self.service(1800000000 + 50 * 86400)
        self.assertEqual(service.token_for_worker('workspace', 'connection')['accessToken'], 'synthetic-old')
        adapter.refresh.assert_not_called()


class HistoryShapeTests(unittest.TestCase):
    def page(self, body, cursor=None):
        adapter = providers.InstagramProvider('id', 's', transport=Recorder([{'status': 200, 'body': body}]))
        return social_history.fetch_page(adapter, 'synthetic', '1789', cursor=cursor)

    def test_normalized_posts_retain_provider_identity_and_media_type(self):
        post = self.page({'data': [{'id': '22', 'caption': 'My own caption.', 'media_type': 'CAROUSEL_ALBUM', 'timestamp': '2026-09-20T12:00:00+0000'}]})['posts'][0]
        self.assertEqual(post.get('provider'), 'instagram')
        self.assertEqual(post.get('providerAccountId'), '1789')
        self.assertEqual(post.get('externalPostId'), '22')
        self.assertEqual(post.get('mediaType'), 'CAROUSEL_ALBUM')

    def test_missing_cursor_does_not_masquerade_as_complete_pagination(self):
        with self.assertRaises(AlphaError):
            self.page({'data': [], 'paging': {'next': 'https://graph.instagram.com/next'}})

    def test_repeated_cursor_is_rejected_instead_of_an_infinite_loop(self):
        with self.assertRaises(AlphaError):
            self.page({'data': [], 'paging': {'next': 'https://graph.instagram.com/next', 'cursors': {'after': 'same'}}}, 'same')

    def test_end_of_one_page_is_distinguished_from_account_coverage(self):
        first = self.page({'data': []})
        self.assertTrue(first.get('coverage', {}).get('endReached'))
        self.assertTrue(first.get('coverage', {}).get('startedFromBeginning'))
        later = self.page({'data': []}, 'later')
        self.assertFalse(later.get('coverage', {}).get('startedFromBeginning', True))
        self.assertTrue(later['partialCoverage'])

    def test_malformed_instagram_page_fails_as_a_provider_error(self):
        for paging in (['invalid'], {'cursors': ['invalid']}, {'next': 'next', 'cursors': {'after': 123}}):
            with self.subTest(paging=paging), self.assertRaises(AlphaError):
                self.page({'data': [], 'paging': paging})


class SelectedImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.HistoryServiceTests(methodName='test_verified_page_import_is_retained_only_and_deduplicates')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo, self.oauth = self.fixture.repo, self.fixture.oauth

    def test_multiple_preview_pages_import_atomically_with_labels_and_metadata(self):
        rows = [{'id': '22', 'caption': 'First caption.', 'media_type': 'IMAGE', 'permalink': 'https://www.instagram.com/p/first/'}, {'id': '23', 'caption': 'Second caption.', 'media_type': 'VIDEO'}]
        self.fixture.adapter.transport = Recorder([{'status': 200, 'body': {'data': [row]}} for row in rows] + [{'status': 200, 'body': {'data': []}}])
        pages = [self.oauth.history.preview('workspace', 'session', 'connection', {'confirmed': True}) for _ in rows]
        payload = {'confirmedAuthorship': True, 'selections': [{'receipt': page['receipt'], 'postIds': [row['id']]} for row, page in zip(rows, pages)], 'labels': {'22': 'representative', '23': 'sponsored'}, 'expectedRevision': 1}
        saved = self.oauth.history.retain('workspace', 'session', 'connection', payload)
        samples = [s for s in saved['state']['sources'] if s.get('kind') == 'voice_sample']
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].get('permalink'), rows[0]['permalink'])
        self.assertEqual(samples[0].get('mediaType'), 'IMAGE')
        self.assertEqual(samples[0].get('importedAt'), 200)
        self.assertEqual(samples[0].get('label'), 'representative')
        self.assertEqual(samples[1].get('label'), 'sponsored')
        self.assertTrue(all(not s['selected'] and not s['useGrants'] for s in samples))
        self.assertFalse(self.repo.state['phase2'].get('jobs'))
        self.assertIsNone(self.repo.state['speaker']['provisional'])
        self.assertTrue(all(call['method'] == 'GET' for call in self.fixture.adapter.transport.calls))

    def test_unrecognized_classification_is_rejected_before_retention(self):
        self.fixture.adapter.transport = Recorder([{'status': 200, 'body': {'data': [{'id': '22', 'caption': 'Original.'}]}}] * 2)
        page = self.oauth.history.preview('workspace', 'session', 'connection', {'confirmed': True})
        with self.assertRaises(AlphaError):
            self.oauth.history.retain('workspace', 'session', 'connection', {'receipt': page['receipt'], 'postIds': ['22'], 'labels': {'22': 'invented-sensitive-label'}, 'confirmedAuthorship': True, 'expectedRevision': 1})
        self.assertFalse(any(s.get('kind') == 'voice_sample' for s in self.repo.state['sources']))


class WritingEvidenceTests(unittest.TestCase):
    def test_unlabelled_languages_are_unknown_not_unspecified_learned_traits(self):
        state = initial_state('w')
        ids = [add_sample(state, 'Bonjour tout le monde.', str(i), language='') for i in range(3)]
        proposal = voice_analysis.build_proposal(state, ids, 'owner', 200)
        language = next(d for d in proposal['dimensions'] if d['id'] == 'language')
        self.assertEqual(language.get('evidenceLevel'), 'insufficient')
        self.assertNotIn('Uses Unspecified.', proposal['observations'])
        self.assertIsNone(proposal['tone'])

    def test_platform_comparison_and_recurring_patterns_keep_source_evidence(self):
        state = initial_state('w')
        ids = [add_sample(state, 'Hello! #studio', str(i), platform='Instagram') for i in range(3)]
        ids += [add_sample(state, 'A longer sentence about the way a draft is arranged.\n\nA second paragraph.', str(i + 3), platform='LinkedIn') for i in range(3)]
        proposal = voice_analysis.build_proposal(state, ids, 'owner', 200)
        dimensions = {d['id']: d for d in proposal['dimensions']}
        self.assertIn('platform_differences', dimensions)
        self.assertIn('recurring_patterns', dimensions)
        for key in ('platform_differences', 'recurring_patterns'):
            self.assertTrue(dimensions[key]['support'])
            self.assertTrue(set(dimensions[key]['support']) <= set(ids))


class StableCallbackTests(unittest.TestCase):
    def call(self, base):
        service = SimpleNamespace(oauth=SimpleNamespace(public_base_url=base))
        app = HostedApplication(service=service)
        captured = {}
        app({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/oauth/instagram/callback', 'HTTP_HOST': 'untrusted.example', 'HTTP_X_FORWARDED_HOST': 'attacker.example', 'HTTP_X_FORWARDED_PROTO': 'http', 'QUERY_STRING': 'state=abc&code=xyz'}, lambda s, h: captured.update(status=s, headers=dict(h)))
        return captured

    def test_forwarded_host_does_not_change_the_configured_callback_destination(self):
        response = self.call('https://app.example')
        self.assertEqual(response['status'], '302 Found')
        self.assertTrue(response['headers']['Location'].startswith('https://app.example/channels/connect?'))
        self.assertEqual(response['headers'].get('Referrer-Policy'), 'no-referrer')

    def test_callback_without_stable_origin_fails_closed(self):
        self.assertEqual(self.call('')['status'], '503 Service Unavailable')


if __name__ == '__main__':
    unittest.main()
