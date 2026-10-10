"""Synthetic user-selection seam; never invokes a provider or a local database."""
import copy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_trend_contracts as F
from test_trend_meta_public import policy
from test_trend_meta_runtime import AUTH_ID, Store
from postriff_phase2.growth.trends.contracts import ContractError, digest
from postriff_phase2.growth.trends.providers.base import Batch
from postriff_phase2.growth.trends.providers.meta_runtime import MetaCollector
from postriff_phase2.growth.trends import meta_discovery as D

REQUEST_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
OTHER_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'


class DiscoverySelection(F.OfflineTest):
    def test_exact_user_selection_and_server_owned_account(self):
        proof = SimpleNamespace(reviewed_page_ids=('123', '456'), account_id='789')
        self.assertEqual(D.validate_selection('threads', {'query': 'piano', 'search_type': 'TOP'}, proof),
                         {'query': 'piano', 'search_type': 'TOP'})
        self.assertEqual(D.validate_selection('instagram', {'hashtag': '#音樂'}, proof), {'hashtag': '音樂'})
        self.assertEqual(D.validate_selection('facebook', {'reviewed_page_id': '456'}, proof),
                         {'reviewed_page_id': '456'})

    def test_unreviewed_pages_and_injected_controls_fail_closed(self):
        proof = SimpleNamespace(reviewed_page_ids=('123',), account_id='789')
        values = [('threads', {'query': 'piano', 'search_type': 'RECENT', 'token': 'secret'}),
                  ('threads', {'query': 'x\nq', 'search_type': 'TOP'}),
                  ('threads', {'query': 'piano', 'search_type': 'ALL'}),
                  ('instagram', {'hashtag': 'music', 'ig_user_id': 'foreign'}),
                  ('instagram', {'hashtag': 'https://evil.invalid'}),
                  ('facebook', {'reviewed_page_id': '999'}),
                  ('facebook', {'reviewed_page_id': 'https://evil.invalid'}),
                  ('x', {'query': 'piano'})]
        for provider, selection in values:
            with self.subTest(provider=provider, selection=selection), self.assertRaises(ContractError):
                D.validate_selection(provider, selection, proof)

    def test_request_input_cannot_name_grants_cost_or_vault_fields(self):
        body = {'provider': 'threads', 'selection': {'query': 'piano', 'search_type': 'RECENT'},
                'idempotency_key': 'same-click'}
        self.assertEqual(D.validate_input(body), body)
        for extra in ('authorization_id', 'reservation_microusd', 'token', 'policy_version'):
            with self.subTest(extra=extra), self.assertRaises(ContractError):
                D.validate_input({**body, extra: 'caller-value'})

    def test_runtime_uses_request_selection_and_emits_bound_provenance(self):
        store = Store()
        request = {'request_id': REQUEST_ID, 'coverage_epoch': 'discovery:' + REQUEST_ID,
                   'selection': {'query': 'user piano', 'search_type': 'TOP'},
                   'selection_digest': digest({'query': 'user piano', 'search_type': 'TOP'})}
        collector = MetaCollector(store, AUTH_ID, clock=lambda: F.NOW)
        observed = {'source_identity': 'threads:123', 'provenance': {'third_party': 'unverified'}}
        payload = {'coverage_epoch': request['coverage_epoch'], 'max_items': 2,
                   'discovery_request_id': REQUEST_ID}
        with patch.object(D, 'load_request', return_value=request), patch(
                'postriff_phase2.growth.trends.providers.meta_public.collect_threads_keyword',
                return_value=Batch(observations=(observed,), cursor={'after': 'opaque'})) as collect:
            batch = collector(policy=policy('threads'), cursor=None, now=F.NOW,
                              payload=payload, reservation_microusd=0)
        self.assertEqual((collect.call_args.kwargs['query'], collect.call_args.kwargs['search_type']),
                         ('user piano', 'TOP'))
        self.assertEqual(batch.observations[0]['provenance']['discovery_request_id'], REQUEST_ID)
        self.assertEqual(batch.cursor['discovery_request_id'], REQUEST_ID)
        self.assertEqual(batch.cursor['provider_cursor'], {'after': 'opaque'})

    def test_wrong_request_cursor_or_epoch_never_calls_adapter(self):
        store = Store()
        request = {'request_id': REQUEST_ID, 'coverage_epoch': 'discovery:' + REQUEST_ID,
                   'selection': {'query': 'chosen', 'search_type': 'RECENT'},
                   'selection_digest': digest({'query': 'chosen', 'search_type': 'RECENT'})}
        collector = MetaCollector(store, AUTH_ID, clock=lambda: F.NOW)
        with patch.object(D, 'load_request', return_value=request), patch(
                'postriff_phase2.growth.trends.providers.meta_public.collect_threads_keyword') as collect:
            for epoch, cursor in [(request['coverage_epoch'], {'discovery_request_id': OTHER_ID,
                                  'provider_cursor': {'after': 'foreign'}}),
                                  ('foreign', None), (request['coverage_epoch'], {'after': 'unwrapped'})]:
                with self.subTest(epoch=epoch, cursor=cursor), self.assertRaises(ContractError):
                    collector(policy=policy('threads'), cursor=cursor, now=F.NOW,
                              payload={'coverage_epoch': epoch, 'max_items': 2,
                                       'discovery_request_id': REQUEST_ID}, reservation_microusd=0)
        collect.assert_not_called()

    def test_request_load_rejects_cross_workspace_provider_grant_policy_or_expiry(self):
        class Cursor:
            description = []
            def execute(self, *args): pass
            def fetchone(self): return self.value
        cur = Cursor()
        p = policy('threads')
        base = dict(request_id=REQUEST_ID, workspace_id=F.WORKSPACE, provider_id='threads',
                    authorization_id=AUTH_ID, source_policy_version=p.version,
                    selection={'query': 'chosen', 'search_type': 'RECENT'},
                    selection_digest=digest({'query': 'chosen', 'search_type': 'RECENT'}),
                    coverage_epoch='discovery:' + REQUEST_ID, expires_at=F.AFTER, active=True)
        changes = [{'workspace_id': F.OTHER}, {'authorization_id': OTHER_ID},
                   {'provider_id': 'instagram'}, {'source_policy_version': 'foreign'},
                   {'expires_at': F.BEFORE}, {'selection_digest': '0' * 64}, {'active': False}]
        for change in changes:
            cur.value = {**base, **change}
            with self.subTest(change=change), self.assertRaises(ContractError):
                D.load_request(Store(), REQUEST_ID, p, AUTH_ID, at=F.NOW, cursor=cur)
        cur.value = base
        self.assertEqual(D.load_request(Store(), REQUEST_ID, p, AUTH_ID, at=F.NOW, cursor=cur), base)


if __name__ == '__main__': unittest.main()
