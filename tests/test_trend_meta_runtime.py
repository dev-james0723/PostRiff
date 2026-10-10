"""Synthetic runtime admission; database concurrency is tested in postgres_trend_meta."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta
from unittest.mock import Mock
import hashlib
import unittest

import test_trend_contracts as F
from test_trend_meta_public import policy, TOKEN
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.growth.trends.contracts import ContractError, iso, instant
from postriff_phase2.growth.trends.providers import runtime, meta_public as M

AUTH_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def record(vault, **changes):
    ciphertext, kid = vault.encrypt(TOKEN)
    result = dict(authorization_id=AUTH_ID, workspace_id=F.WORKSPACE,
        provider_id='threads', operation='keyword_search', source_policy_version='fixture-v1',
        connection_id='meta-public-synthetic', credential_provider='meta_public_threads',
        credential_account_id='123456', credential_scopes=['threads_basic', 'threads_keyword_search'],
        access_ciphertext=ciphertext, key_id=kid, credential_revoked_at=None,
        access_expires_at=F.AFTER, ciphertext_digest=hashlib.sha256(ciphertext.encode()).hexdigest(),
        revoked_at=None, consent_at=F.BEFORE, expires_at=F.AFTER,
        review=dict(review_id=AUTH_ID, app_id='1234567', provider_id='threads', operation='keyword_search',
            api_version='v1.0', scope_key=F.SCOPE, login_kind='threads_login', account_id='123456',
            account_kind='user', token_fingerprint=hashlib.sha256(TOKEN.encode()).hexdigest(),
            verified_scopes=['threads_basic','threads_keyword_search'],
            approved_scopes=['threads_basic','threads_keyword_search'], approved_features=[],
            verified_at=F.NOW, expires_at=iso(instant(F.NOW)+timedelta(minutes=10)),
            quota_limit=10, quota_window_seconds=86400, reviewed_page_ids=[],
            page_public=False, page_restricted=False, consent_current=True,
            review_ref='synthetic:meta-approved-operation', quota_rule_ref='synthetic:quota-rule'),
        quota_rules={'threads_keyword_search':{'limit':10,'window_seconds':86400}},
        selection={'query':'piano','search_type':'RECENT','reviewed_policy': dict(policy_id=policy('threads').id,version=policy('threads').version,scope_key=F.SCOPE,provider_id='threads',operation='keyword_search',rights=policy('threads').rights,max_retention_seconds=policy('threads').retention_seconds)}, active=True)
    result.update(changes)
    return result


class Cursor:
    description = []
    def __init__(self, record): self.record=record
    def execute(self, *args): pass
    def fetchone(self): return self.record


class Store:
    def __init__(self):
        self.meta_vault=CredentialVault(CredentialVault.generate_key())
        self.record=record(self.meta_vault)
    @contextmanager
    def transaction(self, cursor=None): yield cursor or Cursor(self.record)


class MetaRuntime(F.OfflineTest):
    def test_reviewed_server_manifest_gets_inert_runtime_binding(self):
        store=Store()
        manifest={**asdict(policy('threads')), 'meta_authorization_id':AUTH_ID}
        with unittest.mock.patch('postriff_phase2.growth.trends.store.utcnow',return_value=F.NOW):
            selected=runtime.binding(store,manifest,M.PROTOCOL)
        self.assertIsNotNone(selected, 'reviewed Meta source has no runtime binding')
        self.assertEqual(selected[0].operation,'keyword_search')
        self.assertTrue(callable(selected[1]))

    def test_foreign_workspace_or_owned_credential_cannot_bind(self):
        store=Store(); manifest={**asdict(policy('threads')), 'meta_authorization_id':AUTH_ID}
        for changes in ({'workspace_id':F.OTHER},{'credential_provider':'threads'},
                        {'credential_scopes':['threads_basic']},{'revoked_at':F.NOW},
                        {'active':False},{'access_expires_at':F.BEFORE}):
            with self.subTest(changes=changes):
                store.record=record(store.meta_vault,**changes)
                with unittest.mock.patch('postriff_phase2.growth.trends.store.utcnow',return_value=F.NOW):
                    self.assertIsNone(runtime.binding(store,manifest,M.PROTOCOL))

    def test_job_cannot_override_server_query_or_credential(self):
        from postriff_phase2.growth.trends.providers.meta_runtime import MetaCollector
        store=Store()
        collector=MetaCollector(store,AUTH_ID,clock=lambda:F.NOW)
        for malicious in ({'query':'stolen'}, {'connection_id':'foreign'}, {'token':TOKEN},
                          {'page_id':'123'}, {'endpoint':'https://evil.invalid'}):
            with self.subTest(key=next(iter(malicious))), self.assertRaises(ContractError):
                collector(policy=policy('threads'),cursor=None,now=F.NOW,
                    payload={'coverage_epoch':'synthetic','max_items':2,**malicious},reservation_microusd=0)

    def test_revocation_after_binding_blocks_before_vault_decryption(self):
        from postriff_phase2.growth.trends.providers.meta_runtime import MetaCollector
        store=Store();collector=MetaCollector(store,AUTH_ID,clock=lambda:F.NOW)
        store.record['revoked_at']=F.NOW
        with unittest.mock.patch.object(store.meta_vault,'decrypt',side_effect=AssertionError('must not decrypt')):
            with self.assertRaises(ContractError):
                collector(policy=policy('threads'),cursor=None,now=F.NOW,
                    payload={'coverage_epoch':'synthetic','max_items':2},reservation_microusd=0)

if __name__=='__main__': unittest.main()

class MetaRuntimeEvidence(F.OfflineTest):
    def test_only_real_transport_and_independently_reviewed_source_can_qualify(self):
        from postriff_phase2.growth.trends.providers.meta_runtime import MetaCollector
        from postriff_phase2.growth.trends.providers.base import Batch
        store=Store();store.record['selection'].update(third_party_source_ids=['threads:123'],third_party_evidence_ref='operator:sample-reviewed')
        collector=MetaCollector(store,AUTH_ID,clock=lambda:F.NOW)
        for kind,identity,expected in [('synthetic','threads:123','unverified'),
                                      ('provider_response','threads:456','unverified'),
                                      ('provider_response','threads:123',True)]:
            observation=dict(source_identity=identity,provenance={'evidence_kind':kind,'third_party':'unverified'})
            with self.subTest(kind=kind,identity=identity),unittest.mock.patch.object(M,'collect_threads_keyword',return_value=Batch(observations=(observation,))):
                batch=collector(policy=policy('threads'),cursor=None,now=F.NOW,
                    payload={'coverage_epoch':'synthetic','max_items':2},reservation_microusd=0)
                self.assertEqual(batch.observations[0]['provenance']['third_party'],expected)
