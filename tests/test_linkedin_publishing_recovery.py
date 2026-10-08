"""Synthetic LinkedIn publishing regressions; never evidence of a live publication."""
import copy
import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.capabilities import publish_route
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.oauth import OAuthService
from postriff_phase2.official_operations import OfficialAPI
from postriff_phase2.official_social import capability_states
from postriff_phase2.provider_candidates import little_text
from postriff_phase2.providers import LinkedInProvider, registry_from_environment
from postriff_phase2.social_formats import options
from test_official_social import response, runtime, job, Transport


CAPTION = 'Rafii preview test (approved) — @friends [draft] <3 #Rafii *text* \\ | {x}'


def approved_member_app():
    provider = LinkedInProvider('synthetic-client', 'synthetic-secret')
    provider.public_origin = 'https://preview.example.invalid'
    provider.deployment_environment = 'preview'
    provider.official_approvals = {'share_on_linkedin': {
        'state': 'approved', 'appId': 'synthetic-client', 'audience': 'external',
        'approvedScopes': ['w_member_social'], 'evidenceRef': 'synthetic-unit-only',
        'callbackUri': provider.public_origin + '/api/oauth/linkedin/callback', 'environment': 'preview',
    }}
    return provider


class MemberPublishingAccess(unittest.TestCase):
    def test_linkedin_expanded_workflow_flag_cannot_enable_another_provider(self):
        values = {'POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID':'synthetic-client','POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET':'synthetic-secret',
                  'POSTRIFF_OAUTH_THREADS_CLIENT_ID':'synthetic-threads','POSTRIFF_OAUTH_THREADS_CLIENT_SECRET':'synthetic-secret',
                  'POSTRIFF_OAUTH_LINKEDIN_OFFICIAL_SOCIAL_ENABLED':'true'}
        providers = registry_from_environment(values)
        self.assertTrue(providers['linkedin'].official_social_enabled)
        self.assertFalse(providers['threads'].official_social_enabled)
        self.assertFalse(providers['linkedin'].member_publishing_approved(), 'Workflow flag never supplies app approval')
        values.update(POSTRIFF_OFFICIAL_SOCIAL_ENABLED='true', POSTRIFF_OAUTH_LINKEDIN_OFFICIAL_SOCIAL_ENABLED='false')
        providers = registry_from_environment(values)
        self.assertFalse(providers['linkedin'].official_social_enabled)
        self.assertTrue(providers['threads'].official_social_enabled)

    def test_product_evidence_is_bound_to_this_app_external_audience_and_scope(self):
        provider = approved_member_app()
        check = lambda: getattr(provider, 'member_publishing_approved', lambda: False)()
        self.assertTrue(check())
        original = copy.deepcopy(provider.official_approvals)
        for change in ({'appId': 'another-app'}, {'state': 'requested'}, {'audience': 'testers'},
                       {'approvedScopes': ['openid', 'profile']}, {'evidenceRef': ''},
                       {'approvedScopes': 'w_member_social'}, {'environment': 'production'},
                       {'callbackUri': 'https://production.example.invalid/api/oauth/linkedin/callback'}):
            with self.subTest(change=change):
                provider.official_approvals = copy.deepcopy(original)
                provider.official_approvals['share_on_linkedin'].update(change)
                self.assertFalse(check())
        provider.official_approvals = {'openid_connect': original['share_on_linkedin']}
        self.assertFalse(check(), 'Identity approval never supplies publication access')
        provider.official_approvals = original
        provider.deployment_environment = None
        self.assertFalse(check(), 'Unknown runtime environment cannot enable a preview product record')
        provider.deployment_environment = 'production'
        self.assertFalse(check(), 'Preview evidence cannot enable production')

    def test_configuration_diagnostics_name_the_mismatch_without_credential_values(self):
        provider = approved_member_app()
        original = copy.deepcopy(provider.official_approvals)
        for change, code in (({'appId':'different-client'}, 'oauth_client_mismatch'),
                             ({'callbackUri':'https://elsewhere.invalid/callback'}, 'callback_mismatch'),
                             ({'environment':'production'}, 'environment_mismatch')):
            with self.subTest(code=code):
                provider.official_approvals = copy.deepcopy(original)
                provider.official_approvals['share_on_linkedin'].update(change)
                status = provider.member_publishing_status()
                self.assertFalse(status['approved'])
                self.assertEqual(status['code'], code)
                self.assertIn('operator', status['message'])
                self.assertNotIn(provider.client_id, status['message'])
                self.assertNotIn(provider.client_secret, status['message'])
                self.assertNotIn("hasn't approved", status['message'])
        provider.official_approvals = {}
        status = provider.member_publishing_status()
        self.assertFalse(status['approved'])
        self.assertEqual(status['code'], 'share_evidence_missing')
        self.assertTrue(status['runtimeEnvironmentVerified'])
        self.assertEqual(status['runtimeEnvironment'], 'preview', 'Runtime presence is observable before any operator evidence activation')
        for unknown_environment in (None, '', 'development', 'unexpected-value'):
            provider.deployment_environment = unknown_environment
            status = provider.member_publishing_status()
            self.assertFalse(status['runtimeEnvironmentVerified'])
            self.assertIsNone(status['runtimeEnvironment'], 'Only known environment labels may be exposed')
            self.assertFalse(status['approved'])
        matrix = OAuthService._capabilities(provider, 'publish', ['openid','profile','w_member_social'], [], 1000)
        self.assertIn('not yet been verified/configured', matrix['publish']['evidence'])
        self.assertNotIn("hasn't approved", matrix['publish']['evidence'])

    def test_member_product_and_actual_grant_enable_only_member_publish_and_schedule(self):
        provider = approved_member_app()
        self.assertFalse(provider.production_reviewed)
        provider.approved_scopes = {'r_member_postAnalytics', 'w_member_social_feed'}
        granted = ['openid', 'profile', 'w_member_social', 'r_member_postAnalytics', 'w_member_social_feed']
        matrix = OAuthService._capabilities(provider, 'publish', granted, [], 1000)
        self.assertEqual(matrix['publish']['level'], 'Direct')
        self.assertEqual(matrix['schedule']['level'], 'Direct')
        self.assertNotEqual(matrix['analytics']['level'], 'Direct')
        self.assertNotEqual(matrix['reply']['level'], 'Direct')
        without_write = OAuthService._capabilities(provider, 'publish', ['openid', 'profile'], ['w_member_social'], 1000)
        self.assertNotEqual(without_write['publish']['level'], 'Direct')

    def test_hosted_member_access_does_not_unlock_organization_or_paused_execution(self):
        provider = approved_member_app()
        host = HostedSocial(SimpleNamespace(), {'linkedin': provider})
        self.assertIs(host._provider({'platform': 'LinkedIn'}), provider)
        self.assertIsNone(host._provider({'platform': 'LinkedIn', 'publishOptions': {'destinationType': 'organization', 'authorUrn': 'urn:li:organization:7'}}))
        provider.execution_enabled = False
        self.assertIsNone(host._provider({'platform': 'LinkedIn'}))

    def test_automation_checks_member_grant_without_requiring_restricted_product(self):
        provider = approved_member_app()
        channel = {'id': 'connection', 'platform': 'LinkedIn', 'account': 'Synthetic member',
                   'accountType': 'member', 'identityVerified': True, 'capabilityVerified': True,
                   'evidenceSource': 'live_provider', 'scopes': ['openid', 'profile', 'w_member_social']}
        state = {'phase2': {'channels': [channel]}}
        destination = {'platform': 'LinkedIn', 'channelId': channel['id']}
        route = lambda: publish_route(state, destination, providers={'linkedin': provider}, live=True, can_publish=True)
        self.assertTrue(route()['publish'])
        channel['scopes'] = ['openid', 'profile']
        self.assertFalse(route()['publish'], 'A stale capability flag cannot replace the actual write grant')
        channel['scopes'].append('w_member_social')
        provider.execution_enabled = False
        self.assertFalse(route()['publish'])

    def test_readiness_separates_member_permission_from_restricted_history(self):
        channel = {'platform': 'LinkedIn', 'accountType': 'member', 'connectionState': 'publish_verified',
                   'scopes': ['openid', 'profile', 'w_member_social'], 'capabilities': {'publish': {'level': 'Direct'}}}
        provider = {'configured': True, 'connectReady': True, 'productionReviewed': False,
                    'memberPublishingApproved': True, 'historyAvailableForApp': False}
        ready = OAuthService.connection_readiness(channel, provider)
        self.assertEqual(ready['publishing'], 'PUBLISHING_AVAILABLE')
        self.assertEqual(ready['history'], 'HISTORICAL_IMPORT_AWAITING_PROVIDER_APPROVAL')
        self.assertFalse(ready['fullyAvailable'])

    def test_share_qualification_needs_no_customer_e2e_record_to_accept_own_member_eligibility(self):
        provider = approved_member_app()
        channel = {'evidenceSource': 'live_provider', 'providerAccountId': 'urn:li:person:synthetic',
                   'identityVerified': True, 'accountType': 'member', 'expiresAt': 4600,
                   'scopes': ['openid', 'profile', 'w_member_social']}
        rows = capability_states('linkedin', channel, approvals=provider.official_approvals,
                                 member_publishing_approved=provider.member_publishing_approved(), now=1000)
        self.assertTrue(rows['member_publish']['appApproved'])
        self.assertTrue(rows['member_publish']['granted'])
        self.assertTrue(rows['member_publish']['eligible'])
        self.assertFalse(rows['member_publish']['liveE2E'])
        self.assertEqual(rows['member_publish']['state'], 'BLOCKED', 'Permission is not live qualification')
        self.assertFalse(rows['organization_publish']['appApproved'])
        self.assertFalse(rows['analytics']['appApproved'])
        provider.deployment_environment = 'production'
        rows = capability_states('linkedin', channel, approvals=provider.official_approvals,
                                 member_publishing_approved=provider.member_publishing_approved(), now=1000)
        self.assertFalse(rows['member_publish']['appApproved'])


class ExactPostContent(unittest.TestCase):
    def test_link_card_requires_explicit_title_without_scraping_the_destination(self):
        for title in (None, '', '   '):
            with self.subTest(title=title), self.assertRaises(AlphaError):
                options('LinkedIn', {'link':'https://example.invalid/article', **({'title':title} if title is not None else {})}, [], 'Approved caption')
        selected = options('LinkedIn', {'link':'https://example.invalid/article','title':'Approved title','description':'Approved description'}, [], 'Approved caption')
        self.assertEqual(selected['title'], 'Approved title')
        owner, manifest, transport, _ = runtime(approved_member_app(), [response(status=201, **{'x-restli-id':'urn:li:share:123'})], options=selected)
        owner.advance(manifest, job('create_attempted'), 'create')
        self.assertEqual(transport.calls[0][2]['body']['content']['article'], {'source':selected['link'],'title':selected['title'],'description':selected['description']})
        self.assertEqual(len(transport.calls), 1, 'Metadata is explicit; do not scrape or request a second create')

    def test_accepted_member_post_without_private_read_grant_keeps_a_safe_owner_check_link(self):
        provider = approved_member_app()
        grant = {'accessToken':'synthetic-token','scopes':['openid','profile','w_member_social']}
        transport = Transport([])
        oauth = SimpleNamespace(token_for_worker=lambda *_: grant)
        host = HostedSocial(oauth, {'linkedin':provider}, transport=transport)
        manifest = {'workspaceId':'W','channelId':'C','platform':'LinkedIn',
                    'providerAccountId':'urn:li:person:synthetic','payload':{'text':CAPTION}}
        receipt = host.reconcile(manifest, {'providerReference':'urn:li:share:123'})
        self.assertEqual(receipt['state'], 'provider_accepted', 'A known accepted post must not become a failed or blocked create')
        self.assertNotIn('verification', receipt, 'Manual owner inspection is not API verification')
        self.assertEqual(receipt['url'], 'https://www.linkedin.com/feed/update/urn:li:share:123/')
        self.assertIn('read permission', receipt['confirmed'])
        self.assertNotIn('BLOCKED', receipt['confirmed'], 'Private readback is independent of accepted publication')
        self.assertFalse(transport.calls, 'Do not issue a predictably forbidden private read')

    def test_official_create_preserves_plain_caption_and_remains_accepted_until_read_back(self):
        owner, manifest, transport, grant = runtime(LinkedInProvider('app', 'secret'), [response(status=201, **{'x-restli-id': 'urn:li:share:123'})])
        manifest['payload']['text'] = CAPTION
        grant['scopes'] = ['openid', 'profile', 'w_member_social']
        result = owner.advance(manifest, job('create_attempted'), 'create')
        self.assertEqual(transport.calls[0][2]['body']['commentary'], little_text(CAPTION))
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(result['url'], 'https://www.linkedin.com/feed/update/urn:li:share:123/')
        self.assertNotIn('verification', result)

    def test_member_edit_uses_same_plain_text_contract_without_unlocking_feed_actions(self):
        provider = approved_member_app()
        provider.official_social_enabled = True
        provider.transport = Transport([response({'sub': 'abc'}), response(status=204)])
        api = OfficialAPI(provider, {'accessToken': 'synthetic-token', 'scopes': ['openid', 'profile', 'w_member_social']})
        self.assertEqual(api.write('edit', 'urn:li:share:123', {'text': CAPTION})['executionState'], 'submitted')
        self.assertEqual(provider.transport.calls[-1][2]['body']['patch']['$set']['commentary'], little_text(CAPTION))
        provider.transport.calls.clear()
        with self.assertRaises(AlphaError):
            api.write('reply', 'urn:li:share:123', {'text': 'Reply', 'rootPostUrn': 'urn:li:share:123'})
        self.assertFalse(provider.transport.calls, 'Share product does not grant the feed product')

    def test_single_image_post_keeps_the_approved_alt_text(self):
        owner, manifest, transport, _ = runtime(LinkedInProvider('app', 'secret'), [response(status=201, **{'x-restli-id': 'urn:li:share:123'})], ['image/jpeg'])
        assets = [{'id': 'urn:li:image:123', 'kind': 'images', 'assetId': '0', 'alt': 'Approved accessible description'}]
        owner.advance(manifest, job('publish_attempted', {'providerAssets': assets}), 'publish')
        self.assertEqual(transport.calls[0][2]['body']['content']['media']['altText'], assets[0]['alt'])


if __name__ == '__main__':
    unittest.main()
