"""Synthetic Facebook connection regressions; never public-access evidence."""
import copy
import json
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError
from postriff_phase2.wave3_connectors import FacebookPagesProvider
from postriff_phase2.oauth import OAuthService
from postriff_phase2.official_social import capability_states
from test_hosted_wave1_connectors import Wire, ok


class FacebookConnection(unittest.TestCase):
    def session(self, **overrides):
        return json.dumps({'v': 1, 'user': '777', 'ut': 'LONG', 'scope': ['pages_show_list'], 'page': None, **overrides})

    def test_a_single_page_still_requires_explicit_customer_selection(self):
        wire = Wire([ok({'access_token': 'SHORT'}), ok({'access_token': 'LONG', 'expires_in': 5184000}),
                     ok({'id': '777', 'name': 'Person'}),
                     ok({'data': {'app_id': 'app', 'user_id': '777', 'is_valid': True}}),
                     ok({'data': [{'permission': 'pages_show_list', 'status': 'granted'}]}),
                     ok({'data': [{'id': '10001', 'name': 'Only Page', 'tasks': ['ANALYZE'], 'access_token': 'PAGE'}]})])
        grant = FacebookPagesProvider('app', 'secret', transport=wire).exchange('CODE', 'V', 'https://example.invalid/callback')
        self.assertIsNone(json.loads(grant['accessToken'])['page'])

    def test_minimum_identity_keeps_pages_without_publishing_tokens(self):
        page = {'id': '10001', 'name': 'Read-only Page', 'tasks': ['ANALYZE']}
        wire = Wire([ok({'data': [page]}), ok({'data': [page]}), ok({'data': [page]})])
        adapter = FacebookPagesProvider('app', 'secret', transport=wire)
        destinations = adapter.destinations(self.session())
        self.assertEqual(destinations, [{**page, 'kind': 'page', 'selected': False}])
        selected = adapter.with_destination(self.session(), '10001')
        self.assertEqual(adapter.identity(selected), {'providerAccountId': '777', 'handle': 'Read-only Page', 'accountType': 'page'})
        self.assertNotIn('access_token', parse_qs(urlsplit(wire.calls[0]['url']).query)['fields'][0])
        self.assertNotIn('token', json.loads(selected)['page'])

    def test_long_lived_user_expiry_is_preserved_and_app_and_user_are_validated(self):
        now = int(time.time())
        wire = Wire([ok({'access_token': 'SHORT'}), ok({'access_token': 'LONG', 'expires_in': 5184000}),
                     ok({'id': '777', 'name': 'Person'}),
                     ok({'data': {'app_id': 'app', 'user_id': '777', 'is_valid': True,
                                  'expires_at': now + 3600, 'data_access_expires_at': now + 7200}}),
                     ok({'data': [{'permission': 'pages_show_list', 'status': 'granted'},
                                   {'permission': 'pages_manage_posts', 'status': 'declined'}]}), ok({'data': []})])
        adapter = FacebookPagesProvider('app', 'secret', transport=wire)
        grant = adapter.exchange('CODE', 'V', 'https://example.invalid/callback')
        self.assertGreater(grant['expiresIn'], 3500)
        self.assertLessEqual(grant['expiresIn'], 3600)
        self.assertEqual(grant['scopes'], ['pages_show_list'])
        self.assertIsNone(grant['refreshToken'])
        self.assertFalse(adapter.non_expiring)
        self.assertIn('/debug_token?', wire.calls[3]['url'])

    def test_wrong_app_subject_invalid_or_expired_tokens_never_prove_grants(self):
        now = int(time.time())
        valid = {'app_id': 'app', 'user_id': '777', 'is_valid': True, 'expires_at': now + 3600,
                 'data_access_expires_at': now + 7200}
        for changed in ({'app_id': 'other'}, {'user_id': '888'}, {'is_valid': False},
                        {'expires_at': now - 1}, {'data_access_expires_at': now - 1}):
            with self.subTest(changed=changed):
                wire = Wire([ok({'data': {**valid, **changed}})])
                adapter = FacebookPagesProvider('app', 'secret', transport=wire)
                self.assertIsNone(adapter.inspect_scopes(self.session(), '777'))
                self.assertEqual(len(wire.calls), 1)

    def test_basic_page_connection_never_authorizes_a_write_without_a_page_token(self):
        page = {'id': '10001', 'name': 'Page', 'tasks': ['CREATE_CONTENT']}
        adapter = FacebookPagesProvider('app', 'secret', transport=Wire([ok({'data': [page]})]))
        with self.assertRaises(AlphaError):
            adapter.revalidate_page(self.session(page=copy.deepcopy(page)), 'CREATE_CONTENT')

    def test_removed_or_other_page_cannot_be_selected(self):
        adapter = FacebookPagesProvider('app', 'secret', transport=Wire([ok({'data': []})]))
        with self.assertRaises(AlphaError):
            adapter.with_destination(self.session(), '10001')

    def test_publish_grant_without_selected_page_cannot_enable_publishing(self):
        adapter = FacebookPagesProvider('app', 'secret', production_reviewed=True)
        scopes = ['pages_show_list', 'pages_read_engagement', 'pages_manage_posts']
        matrix = OAuthService._capabilities(adapter, 'publish', scopes, [], 1000, self.session(scope=scopes))
        self.assertEqual(matrix['identity']['level'], 'Direct')
        self.assertNotEqual(matrix['publish']['level'], 'Direct')

    def test_minimum_page_connection_does_not_need_per_customer_operator_evidence(self):
        channel = {'evidenceSource': 'live_provider', 'providerAccountId': '777', 'accountType': 'page',
                   'destinationId': '10001', 'identityVerified': True, 'expiresAt': 5000, 'scopes': ['pages_show_list']}
        review = {'state': 'approved', 'audience': 'external', 'appId': 'app',
                  'approvedScopes': ['pages_show_list'], 'evidenceRef': 'synthetic-unit-only'}
        rows = capability_states('facebook', channel, connection_approval=review, now=1000)
        for key in ('connected_person', 'page_selected', 'page_identity', 'page_roles'):
            self.assertTrue(rows[key]['appApproved'])
            self.assertTrue(rows[key]['eligible'])
            self.assertTrue(rows[key]['granted'])
            self.assertEqual(rows[key]['blockers'], ['LIVE E2E NOT PROVEN'])
        self.assertFalse(rows['page_publish']['appApproved'])
        self.assertFalse(rows['page_publish']['granted'])
        channel.pop('destinationId')
        self.assertFalse(capability_states('facebook', channel, connection_approval=review, now=1000)['page_identity']['eligible'])


if __name__ == '__main__':
    unittest.main()
