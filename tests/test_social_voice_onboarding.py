"""Offline regression coverage for channel onboarding and consented historical posts."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import providers, voice_analysis, voice_sources
from postriff_phase2.oauth import CredentialVault, OAuthService
from test_postriff_providers import Recorder
from test_postriff_voice_analysis import add_sample


class OnboardingRegressionTests(unittest.TestCase):
    def test_missing_configuration_is_visible_without_mounting_fake_adapters(self):
        service = OAuthService(None, None, CredentialVault(None), {}, 'https://app.example')
        self.assertTrue(callable(getattr(service, 'provider_catalog', None)), 'Expose safe setup diagnostics, not an empty provider list')
        catalog = {p['id']: p for p in service.provider_catalog()}
        self.assertFalse(catalog['instagram']['connectReady'])
        self.assertIn('POSTRIFF_OAUTH_INSTAGRAM_CLIENT_ID', ' '.join(catalog['instagram']['setupIssues']))
        self.assertEqual(catalog['linkedin']['callbackUri'], 'https://app.example/api/oauth/linkedin/callback')
        self.assertEqual(providers.registry_from_environment({}), {})

    def test_identity_connect_is_ready_without_publish_review(self):
        adapter = providers.InstagramProvider('id', 'SYNTHETIC_SECRET')
        service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), {'instagram': adapter}, 'https://app.example')
        self.assertTrue(callable(getattr(service, 'provider_catalog', None)))
        item = next(p for p in service.provider_catalog() if p['id'] == 'instagram')
        self.assertTrue(item['connectReady'])
        self.assertFalse(item['productionReviewed'])
        self.assertTrue(item['capabilities']['identity'])
        self.assertTrue(item['capabilities']['posts_read'])
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(item))

    def test_linkedin_restricted_history_scope_is_opt_in(self):
        values = {'POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID': 'id', 'POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET': 's'}
        self.assertEqual(providers.registry_from_environment(values)['linkedin'].capability_scopes('posts_read'), [])
        values['POSTRIFF_OAUTH_LINKEDIN_HISTORY_APPROVED'] = 'true'
        adapter = providers.registry_from_environment(values)['linkedin']
        self.assertIn('r_member_social', adapter.capability_scopes('posts_read'))
        self.assertNotIn('r_member_social', adapter.capability_scopes('identity'))

    def test_linkedin_introspection_accepts_space_delimited_actual_scopes(self):
        adapter = providers.LinkedInProvider('id', 's', transport=Recorder([{'status': 200, 'body': {'active': True, 'client_id': 'id', 'scope': 'openid profile r_member_social'}}]))
        self.assertEqual(adapter.inspect_scopes('synthetic', 'urn:li:person:one'), ['openid', 'profile', 'r_member_social'])

    def test_local_rules_do_not_claim_to_learn_a_warm_tone(self):
        state = initial_state('workspace')
        sid = add_sample(state, 'Report. Values remain unchanged.', 'one')
        proposal = voice_analysis.build_proposal(state, [sid], 'owner', 200)
        self.assertIsNone(proposal.get('tone'))
        self.assertEqual(proposal['analysisMethod'], 'local-rules')
        self.assertEqual(proposal['writingExample'], '', 'Analysis-only consent must not forward raw samples through VOICE.md')
        with self.assertRaises(AlphaError):
            voice_analysis.build_proposal(state, [sid], 'owner', 200, route='cloud:unapproved')


class OwnedPostsContractTests(unittest.TestCase):
    def history(self):
        self.assertIsNotNone(importlib.util.find_spec('postriff_phase2.social_history'), 'Implement bounded official owned-post reads')
        from postriff_phase2 import social_history
        return social_history

    def test_instagram_pagination_uses_cursor_not_arbitrary_next_url(self):
        history = self.history()
        transport = Recorder([{'status': 200, 'body': {'data': [{'id': '22', 'caption': 'My own words', 'timestamp': '2026-09-20T12:00:00+0000', 'media_type': 'IMAGE', 'permalink': 'https://www.instagram.com/p/one/'}], 'paging': {'cursors': {'after': 'CURSOR'}, 'next': 'https://evil.example/?access_token=secret'}}}])
        adapter = providers.InstagramProvider('id', 's', transport=transport)
        page = history.fetch_page(adapter, 'synthetic', '1789', cursor=None, limit=25)
        self.assertEqual(page['nextCursor'], 'CURSOR')
        self.assertEqual(page['posts'][0]['text'], 'My own words')
        self.assertEqual(urlparse(transport.calls[0]['url']).hostname, 'graph.instagram.com')
        self.assertNotIn('synthetic', transport.calls[0]['url'])
        self.assertNotIn('evil', json.dumps(page))
        self.assertTrue(page['partialCoverage'])

    def test_linkedin_excludes_foreign_authors_reshares_and_drafts(self):
        history = self.history()
        valid = {'id': 'urn:li:share:1', 'author': 'urn:li:person:one', 'commentary': 'Original words', 'lifecycleState': 'PUBLISHED'}
        transport = Recorder([{'status': 200, 'body': {'elements': [valid, {**valid, 'author': 'urn:li:person:other'}, {**valid, 'reshareContext': {'parent': 'other'}}, {**valid, 'lifecycleState': 'DRAFT'}], 'paging': {'start': 0, 'count': 25, 'links': []}}}])
        adapter = providers.LinkedInProvider('id', 's', transport=transport)
        adapter.history_approved = True
        page = history.fetch_page(adapter, 'synthetic', 'urn:li:person:one')
        self.assertEqual(len(page['posts']), 1)
        self.assertEqual(page['skippedCount'], 3)
        query = parse_qs(urlparse(transport.calls[0]['url']).query)
        self.assertEqual(query['author'], ['urn:li:person:one'])
        self.assertEqual(query['q'], ['author'])

    def test_provider_failure_is_not_an_empty_history(self):
        history = self.history()
        for status in (401, 403, 429, 500):
            adapter = providers.InstagramProvider('id', 's', transport=Recorder([{'status': status, 'body': {'error': 'PRIVATE_TOKEN'}}]))
            with self.subTest(status=status), self.assertRaises(AlphaError) as error:
                history.fetch_page(adapter, 'synthetic', '1789')
            self.assertNotIn('PRIVATE_TOKEN', str(error.exception))

    def test_selection_receipt_binds_actor_workspace_connection_and_expiry(self):
        history = self.history()
        vault = CredentialVault(CredentialVault.generate_key())
        binding = {'workspace': 'w', 'actor': 'a', 'connection': 'c', 'account': '1789', 'credential': 'fingerprint'}
        receipt = history.seal_page(vault, binding, {'posts': [{'id': '22', 'text': 'My words'}]}, 100)
        page = history.open_page(vault, receipt, binding, 101)
        self.assertEqual(page['posts'][0]['id'], '22')
        for key in binding:
            with self.subTest(key=key), self.assertRaises(AlphaError):
                history.open_page(vault, receipt, {**binding, key: 'foreign'}, 101)
        with self.assertRaises(AlphaError):
            history.open_page(vault, receipt, binding, 2000)
        with self.assertRaises(AlphaError):
            history.open_page(vault, receipt + 'tampered', binding, 101)

    def test_manual_import_does_not_accept_claimed_official_provenance(self):
        state = initial_state('w')
        voice_sources.apply_action(state, 'voice_samples_import', {'text': 'User words', 'voiceOrigin': 'official_api'}, 'a', 100)
        self.assertEqual(state['sources'][-1].get('voiceOrigin'), 'user_provided')


if __name__ == '__main__':
    unittest.main()
