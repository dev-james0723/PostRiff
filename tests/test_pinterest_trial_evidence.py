import json
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.pinterest_trial_evidence import SandboxReadOnlyEvidenceTransport, PinterestReadOnlyEvidenceTransport
from test_hosted_wave1_connectors import Wire, ok


class TrialEvidence(unittest.TestCase):
    def test_redacts_all_credentials_private_identity_and_bookmarks(self):
        receipts = []
        wire = Wire([ok({'access_token': 'PRIVATE-AT', 'refresh_token': 'PRIVATE-RT', 'scope': 'user_accounts:read boards:read ads:read'}),
                     ok({'username': 'PRIVATE-HANDLE', 'id': 'PRIVATE-ID'}),
                     ok({'items': [{'id': 'PRIVATE-BOARD', 'name': 'PRIVATE-NAME'}], 'bookmark': 'PRIVATE-BOOKMARK'})])
        probe = SandboxReadOnlyEvidenceTransport(receipts.append, mock_transport=wire)
        host = 'https://api-sandbox.pinterest.com'
        probe('POST', host + '/v5/oauth/token', headers={'Authorization': 'PRIVATE-BASIC'},
              form={'grant_type': 'authorization_code', 'code': 'PRIVATE-CODE', 'redirect_uri': 'https://isolated.example/callback'})
        probe('GET', host + '/v5/user_account', headers={'Authorization': 'PRIVATE-BEARER'})
        probe('GET', host + '/v5/boards?bookmark=PRIVATE-QUERY', headers={'Authorization': 'PRIVATE-BEARER'})
        text = json.dumps(receipts)
        self.assertNotIn('PRIVATE-', text)
        self.assertEqual(len(receipts), 6)
        self.assertEqual(receipts[1]['summary']['recognizedScopes'], ['boards:read', 'user_accounts:read'])
        self.assertTrue(receipts[1]['summary']['unexpectedScopesPresent'])
        self.assertTrue(all(r['mode'] == 'mock' for r in receipts))

    def test_no_pin_board_or_production_operation_can_reach_wire(self):
        receipts, wire = [], Wire([])
        probe = SandboxReadOnlyEvidenceTransport(receipts.append, mock_transport=wire)
        for method, url, args in [
            ('POST', 'https://api-sandbox.pinterest.com/v5/pins', {'body': {}}),
            ('POST', 'https://api-sandbox.pinterest.com/v5/boards', {'body': {}}),
            ('GET', 'https://api.pinterest.com/v5/user_account', {}),
            ('DELETE', 'https://api-sandbox.pinterest.com/v5/pins/123', {}),
            ('POST', 'https://api-sandbox.pinterest.com/v5/oauth/token', {'form': {'grant_type': 'client_credentials'}}),
            ('GET', 'https://api-sandbox.pinterest.com/v5/boards?access_token=private', {})]:
            with self.subTest(method=method, url=url), self.assertRaises(AlphaError):
                probe(method, url, **args)
        self.assertEqual((wire.calls, receipts), ([], []))

    def test_journal_failure_prevents_network_and_network_failure_is_recorded(self):
        wire = Wire([])
        def no_journal(_):
            raise OSError('journal unavailable')
        probe = SandboxReadOnlyEvidenceTransport(no_journal, mock_transport=wire)
        with self.assertRaises(OSError):
            probe('GET', 'https://api-sandbox.pinterest.com/v5/user_account')
        self.assertEqual(wire.calls, [])
        receipts = []
        def unreachable(*a, **k):
            raise TimeoutError('PRIVATE-DETAIL')
        probe = SandboxReadOnlyEvidenceTransport(receipts.append, mock_transport=unreachable)
        with self.assertRaises(TimeoutError):
            probe('GET', 'https://api-sandbox.pinterest.com/v5/user_account')
        self.assertEqual(receipts[-1]['phase'], 'network_failure')
        self.assertNotIn('PRIVATE-DETAIL', json.dumps(receipts))


class ExplicitOfficialApiTrialEvidence(unittest.TestCase):
    def test_production_selection_allows_only_identity_boards_and_oauth_and_records_environment(self):
        receipts = []
        wire = Wire([ok({'id': 'PRIVATE-ID', 'username': 'PRIVATE-HANDLE'}), ok({'items': []}),
                     ok({'access_token': 'PRIVATE-AT', 'scope': 'user_accounts:read boards:read'})])
        probe = PinterestReadOnlyEvidenceTransport(receipts.append, environment='production', mock_transport=wire)
        probe('GET', 'https://api.pinterest.com/v5/user_account', headers={'Authorization': 'PRIVATE-TOKEN'})
        probe('GET', 'https://api.pinterest.com/v5/boards?page_size=100')
        probe('POST', 'https://api.pinterest.com/v5/oauth/token', form={'grant_type': 'authorization_code', 'code': 'PRIVATE-CODE'})
        self.assertEqual(len(wire.calls), 3)
        self.assertTrue(all(r['apiEnvironment'] == 'production' and r['mode'] == 'mock' for r in receipts))
        self.assertNotIn('PRIVATE-', json.dumps(receipts))
        for method, url, args in [
            ('GET', 'https://api-sandbox.pinterest.com/v5/user_account', {}),
            ('POST', 'https://api.pinterest.com/v5/pins', {'body': {}}),
            ('POST', 'https://api.pinterest.com/v5/boards', {'body': {}}),
            ('GET', 'https://api.pinterest.com/v5/pins/123', {}),
            ('GET', 'https://api.pinterest.com/v5/boards/123/sections', {}),
            ('DELETE', 'https://api.pinterest.com/v5/pins/123', {}),
            ('GET', 'https://api.pinterest.com/v5/boards?access_token=PRIVATE', {}),
            ('POST', 'https://api.pinterest.com/v5/oauth/token', {'form': {'grant_type': 'client_credentials'}}),
            ('GET', 'https://api.pinterest.com.evil.invalid/v5/user_account', {})]:
            with self.subTest(method=method,url=url), self.assertRaises(AlphaError): probe(method,url,**args)
        self.assertEqual(len(wire.calls), 3)

    def test_no_arbitrary_or_implicit_environment_is_accepted(self):
        for environment in ('https://api.pinterest.com', '', '*', None, []):
            with self.subTest(environment=environment), self.assertRaises(AlphaError):
                PinterestReadOnlyEvidenceTransport(lambda _:None, environment=environment, mock_transport=Wire([]))
