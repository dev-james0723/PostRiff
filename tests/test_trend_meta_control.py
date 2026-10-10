"""Synthetic operator imports only; no Meta calls or production evidence."""
import copy
from datetime import timedelta
import importlib
import unittest

import test_trend_contracts as F
from test_trend_meta_public import policy, TOKEN
from postriff_phase2.growth.trends.contracts import ContractError, iso, instant
from postriff_phase2.oauth import CredentialVault

try:
    C = importlib.import_module('postriff_phase2.growth.trends.providers.meta_control')
except ModuleNotFoundError:
    C = None

APP = '1401844428820097'
ACCOUNT = '123456'
AUTH = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
HASH = __import__('hashlib').sha256(TOKEN.encode()).hexdigest()


def evidence():
    common = dict(provider_id='threads', operation='keyword_search', app_id=APP,
                  workspace_id=F.WORKSPACE, account_id=ACCOUNT, token_fingerprint=HASH)
    policy_binding = dict(source_policy_id='synthetic-policy', source_policy_version='fixture-v1',
        scope_key=F.SCOPE, rights_digest=F.C.digest(F.permissions()), max_retention_seconds=3600)
    return {
        'operator:diagnostic': dict(common, kind='meta_token_diagnostic',
            captured_at=F.NOW, artifact_sha256='a' * 64, reviewed_by='operator:test',
            api_version='v1.0', login_kind='threads_login', account_kind='user',
            token_subject_id=ACCOUNT, identity={'id': ACCOUNT},
            response={'data': {'app_id': APP, 'is_valid': True, 'type': 'USER',
                'user_id': ACCOUNT, 'scopes': ['threads_basic', 'threads_keyword_search'],
                'expires_at': int(instant(F.AFTER).timestamp())}}),
        'operator:review': dict(policy_binding, kind='meta_app_review', app_id=APP,
            provider_id='threads', operation='keyword_search', api_version='v1.0',
            status='approved', reviewed_at=F.BEFORE, expires_at=F.AFTER,
            reviewed_by='operator:reviewer', artifact_sha256='b' * 64,
            approved_scopes=['threads_basic', 'threads_keyword_search'],
            approved_features=[], reviewed_page_ids=[], page_public=False, page_restricted=False,
            quota_rule_ref='operator:quota', quota_limit=10, quota_window_seconds=86400,
            quota_rules={'threads_keyword_search': {'limit': 10, 'window_seconds': 86400}}),
        'operator:consent': dict(common, **policy_binding, kind='meta_public_consent', status='granted',
            granted_at=F.BEFORE, expires_at=F.AFTER, reviewed_by='operator:test',
            artifact_sha256='c' * 64),
    }


class MetaControl(F.OfflineTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(C, 'service-only Meta public control API is missing')
        self.records = evidence()

    def proof(self, **kw):
        return C.import_operator_review(policy=policy('threads'), token=TOKEN,
            expected_app_id=APP, diagnostic=self.records['operator:diagnostic'],
            app_review=self.records['operator:review'], consent=self.records['operator:consent'],
            app_review_ref='operator:review', at=F.NOW, authorization_id=AUTH,
            selection={'query': 'piano', 'search_type': 'RECENT'}, **kw)

    def test_independent_evidence_builds_short_lived_bound_proof(self):
        proof = self.proof()
        self.assertEqual(proof.app_id, APP)
        self.assertEqual(proof.account_id, ACCOUNT)
        self.assertEqual(proof.expires_at, '2026-09-27T12:15:00Z')
        self.assertEqual(proof.review_id, AUTH)
        self.assertEqual(proof.verified_scopes, ('threads_basic', 'threads_keyword_search'))
        self.assertNotIn(TOKEN, repr(proof))

    def test_app_review_is_independent_of_published_mode_and_oauth_grant(self):
        for mutation in ({'status': 'not_submitted'}, {'status': 'published'},
                         {'approved_scopes': ['threads_basic']}, {'app_id': '999999'},
                         {'artifact_sha256': ''}, {'reviewed_by': ''}):
            self.records = evidence()
            self.records['operator:review'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.proof()

    def test_raw_diagnostic_binding_validity_expiry_and_scope_fail_closed(self):
        mutations = ({'app_id': '999999'}, {'is_valid': False}, {'is_valid': 'true'},
                     {'user_id': '999999'}, {'type': 'APP'}, {'scopes': ['threads_basic']},
                     {'scopes': 'threads_basic,threads_keyword_search'},
                     {'expires_at': 0}, {'expires_at': int(instant(F.BEFORE).timestamp())},
                     {'data_access_expires_at': int(instant(F.BEFORE).timestamp())})
        for mutation in mutations:
            self.records = evidence()
            self.records['operator:diagnostic']['response']['data'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.proof()

    def test_foreign_workspace_subject_fingerprint_login_or_stale_import_rejected(self):
        for mutation in ({'workspace_id': F.OTHER}, {'account_id': '999999'},
                         {'token_fingerprint': '0' * 64}, {'login_kind': 'instagram_login'},
                         {'account_kind': 'app'}, {'api_version': 'v25.0'},
                         {'captured_at': F.BEFORE}, {'captured_at': F.AFTER}):
            self.records = evidence()
            self.records['operator:diagnostic'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.proof()

    def test_missing_or_foreign_consent_never_becomes_current(self):
        for mutation in ({'status': 'revoked'}, {'workspace_id': F.OTHER},
                         {'account_id': '999999'}, {'app_id': '99999'},
                         {'token_fingerprint': '0' * 64}, {'expires_at': F.NOW}):
            self.records = evidence()
            self.records['operator:consent'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                self.proof()

    def test_provider_expiry_caps_fifteen_minute_proof(self):
        self.records['operator:diagnostic']['response']['data']['expires_at'] = int(
            (instant(F.NOW) + timedelta(minutes=2)).timestamp())
        self.assertEqual(self.proof().expires_at, '2026-09-27T12:02:00Z')


class Cursor:
    """Minimal storage-boundary recorder; PostgreSQL constraints run in cloud."""
    description = []
    def __init__(self, store):
        self.store, self.result = store, None
    def execute(self, sql, args=()):
        self.store.calls.append((sql, args))
        self.result = None
        if 'FROM public.pr_workspaces' in sql:
            self.result = {'id': F.WORKSPACE}
        elif 'INSERT INTO public.pr_encrypted_credentials' in sql:
            keys = ('workspace_id','connection_id','provider','provider_account_id',
                    'access_ciphertext','key_id','scopes','access_expires_at')
            row = dict(zip(keys, args))
            self.store.credentials[row['connection_id']] = row
        elif 'INSERT INTO public.pr_trend_meta_authorizations' in sql:
            keys = ('authorization_id','workspace_id','provider_id','operation',
                    'source_policy_version','connection_id','ciphertext_digest','review',
                    'selection','quota_rules','consent_at','expires_at')
            row = dict(zip(keys, (getattr(x, 'obj', x) for x in args)))
            row['revoked_at'] = None
            self.store.grants[row['authorization_id']] = row
        elif 'SELECT' in sql and 'FROM public.pr_trend_meta_authorizations' in sql:
            auth_id, workspace_id = args
            row = self.store.grants.get(auth_id)
            self.result = copy.deepcopy(row) if row and row['workspace_id'] == workspace_id else None
        elif 'UPDATE public.pr_trend_meta_authorizations' in sql:
            revoked, auth_id, workspace_id = args
            row = self.store.grants.get(auth_id)
            if row and row['workspace_id'] == workspace_id:
                row['revoked_at'] = row['revoked_at'] or revoked
        elif 'UPDATE public.pr_encrypted_credentials' in sql:
            revoked, workspace_id, connection_id, provider = args
            row = self.store.credentials.get(connection_id)
            if row and row['workspace_id'] == workspace_id and row['provider'] == provider:
                row.update(access_ciphertext='', revoked_at=revoked)
    def fetchone(self):
        return self.result


class Store:
    def __init__(self):
        self.meta_vault = CredentialVault(CredentialVault.generate_key())
        self.calls, self.credentials, self.grants = [], {}, {}
    @__import__('contextlib').contextmanager
    def transaction(self, cursor=None):
        original = copy.deepcopy((self.credentials, self.grants))
        try:
            yield cursor or Cursor(self)
        except Exception:
            self.credentials, self.grants = original
            raise


class MetaEnrollment(F.OfflineTest):
    def setUp(self):
        super().setUp()
        self.assertTrue(C is not None and hasattr(C, 'MetaPublicControlService'),
                        'trusted Meta enrollment service missing')
        self.records, self.store = evidence(), Store()
        self.service = C.MetaPublicControlService(self.store, app_ids={'threads': APP},
            evidence_reader=lambda ref: copy.deepcopy(self.records[ref]), clock=lambda: F.NOW)

    def register(self, **kw):
        values = dict(policy=policy('threads'), token=TOKEN, diagnostic_ref='operator:diagnostic',
            app_review_ref='operator:review', consent_ref='operator:consent',
            selection={'query': 'piano', 'search_type': 'RECENT'},
            quota_rules={'threads_keyword_search': {'limit': 10, 'window_seconds': 86400}})
        values.update(kw)
        return self.service.register_connection(**values)

    def test_register_encrypts_dedicated_credential_and_stores_only_derived_proof(self):
        receipt = self.register()
        grant = self.store.grants[receipt['authorization_id']]
        credential = self.store.credentials[grant['connection_id']]
        self.assertEqual(credential['provider'], 'meta_public_threads')
        self.assertEqual(self.store.meta_vault.decrypt(credential['access_ciphertext'], credential['key_id']), TOKEN)
        self.assertEqual(grant['review']['token_fingerprint'], HASH)
        self.assertNotIn(TOKEN, repr(self.store.calls) + repr(receipt))
        self.assertNotIn('response', grant['review'])
        self.assertNotIn('identity', grant['review'])
        self.assertEqual(receipt['activation_state'], 'awaiting_live_public_read')
        self.assertEqual(receipt['verification_method'], 'operator_evidence_import')
        self.assertFalse(any('pr_trend_sources' in sql for sql, _ in self.store.calls))

    def test_denied_review_or_unsafe_quota_cannot_write_vault_or_database(self):
        for mutation in ({'status': 'not_submitted'}, {'approved_scopes': []}):
            self.records['operator:review'].update(mutation)
            with self.assertRaises(ContractError): self.register()
            self.assertEqual(self.store.calls, [])
            self.assertEqual(self.store.credentials, {})
            self.records = evidence()
        with self.assertRaises(ContractError):
            self.register(quota_rules={'threads_keyword_search': {'limit': 999, 'window_seconds': 1}})
        self.assertEqual(self.store.calls, [])

    def test_renewal_needs_new_policy_version_and_creates_new_immutable_grant(self):
        first = self.register()
        with self.assertRaises(ContractError):
            self.register(previous_authorization_id=first['authorization_id'])
        from dataclasses import replace
        renewed_at = '2026-09-27T12:00:01Z'
        self.records['operator:diagnostic']['captured_at'] = renewed_at
        self.service.clock = lambda: renewed_at
        for ref in ('operator:review','operator:consent'):
            self.records[ref]['source_policy_version'] = 'fixture-v2'
        second = self.register(policy=replace(policy('threads'), version='fixture-v2'),
                               previous_authorization_id=first['authorization_id'])
        self.assertNotEqual(first['authorization_id'], second['authorization_id'])
        old = self.store.grants[first['authorization_id']]
        self.assertEqual(old['source_policy_version'], 'fixture-v1')
        self.assertEqual(old['revoked_at'], '2026-09-27T12:00:01Z')
        self.assertEqual(self.store.credentials[old['connection_id']]['access_ciphertext'], '')

    def test_revoke_holds_shared_trust_fence_and_erases_only_matching_public_credential(self):
        receipt = self.register()
        connection = self.store.grants[receipt['authorization_id']]['connection_id']
        self.store.calls.clear()
        revoked = self.service.revoke_connection(workspace_id=F.WORKSPACE,
            authorization_id=receipt['authorization_id'])
        self.assertEqual(revoked['state'], 'revoked')
        self.assertEqual(self.store.credentials[connection]['access_ciphertext'], '')
        first_sql = self.store.calls[0][0]
        self.assertIn('pg_advisory_xact_lock(', first_sql)
        self.assertNotIn('pg_advisory_xact_lock_shared', first_sql)
        self.assertNotIn(TOKEN, repr(revoked))

    def test_renewal_locks_and_checks_workspace_before_trust_or_grant(self):
        from dataclasses import replace
        from unittest.mock import patch
        first = self.register()
        renewed_at = '2026-09-27T12:00:01Z'
        self.records['operator:diagnostic']['captured_at'] = renewed_at
        self.service.clock = lambda: renewed_at
        for ref in ('operator:review', 'operator:consent'):
            self.records[ref]['source_policy_version'] = 'fixture-v2'
        args = dict(policy=replace(policy('threads'), version='fixture-v2'),
                    previous_authorization_id=first['authorization_id'])
        self.store.calls.clear()
        self.register(**args)
        statements = [sql for sql, _ in self.store.calls]
        self.assertIn('FROM public.pr_workspaces', statements[0])
        self.assertIn("NOT state ? 'accountDeletion'", statements[0])
        self.assertIn('FOR SHARE', statements[0])
        self.assertIn('pg_advisory_xact_lock(', statements[1])
        self.assertIn('FROM public.pr_trend_meta_authorizations', statements[2])

        # A blocked workspace stops before acquiring any renewal fence/row or
        # touching credentials, even when the old grant also became unavailable.
        self.store.calls.clear()
        execute = Cursor.execute
        def unavailable_workspace(cur, sql, values=()):
            execute(cur, sql, values)
            if 'FROM public.pr_workspaces' in sql:
                cur.result = None
        with patch.object(Cursor, 'execute', unavailable_workspace):
            with patch.object(self.store.meta_vault, 'encrypt') as encrypt:
                with self.assertRaisesRegex(ContractError, 'meta_workspace_unavailable'):
                    self.register(**args)
                encrypt.assert_not_called()
        self.assertEqual(len(self.store.calls), 1)

    def test_revoke_foreign_workspace_cannot_mutate_grant(self):
        receipt = self.register()
        with self.assertRaises(ContractError):
            self.service.revoke_connection(workspace_id=F.OTHER,
                authorization_id=receipt['authorization_id'])
        self.assertIsNone(self.store.grants[receipt['authorization_id']]['revoked_at'])

    def test_caller_quota_must_match_independent_operator_evidence_exactly(self):
        with self.assertRaises(ContractError):
            self.register(quota_rules={'threads_keyword_search': {'limit': 9, 'window_seconds': 86400}})
        self.records['operator:review']['quota_rules']['threads_keyword_search']['limit'] = 9
        with self.assertRaises(ContractError):
            self.register()
        self.assertEqual(self.store.credentials, {})

    def test_failed_grant_write_cannot_leave_encrypted_token(self):
        from unittest.mock import patch
        real_execute = Cursor.execute
        def failed_grant(cur, sql, args=()):
            if 'INSERT INTO public.pr_trend_meta_authorizations' in sql:
                raise RuntimeError('synthetic database failure')
            return real_execute(cur, sql, args)
        with patch.object(Cursor, 'execute', failed_grant), self.assertRaises(RuntimeError):
            self.register()
        self.assertEqual(self.store.credentials, {})
        self.assertEqual(self.store.grants, {})

    def test_instagram_feature_and_linked_professional_identity_are_independent(self):
        from postriff_phase2.growth.trends.providers import meta_public as meta
        records = evidence()
        for record in (records['operator:diagnostic'], records['operator:consent']):
            record.update(provider_id='instagram', operation='hashtag_discovery', account_id='178400009999')
        diagnostic = records['operator:diagnostic']
        diagnostic.update(api_version=meta.GRAPH_VERSION, login_kind='facebook_login', account_kind='business',
            identity={'id':'178400009999','account_type':'BUSINESS','linked_page_id':'54321',
                      'token_subject_id':ACCOUNT})
        diagnostic['response']['data']['scopes'] = ['instagram_basic']
        review = records['operator:review']
        review.update(provider_id='instagram', operation='hashtag_discovery', api_version=meta.GRAPH_VERSION,
            approved_scopes=['instagram_basic'], approved_features=['instagram_public_content_access'],
            quota_limit=30, quota_window_seconds=604800,
            quota_rules={'instagram_distinct_hashtag_7d': {'limit':30,'window_seconds':604800},
                         'instagram_graph_request': {'limit':10,'window_seconds':86400}})
        service = C.MetaPublicControlService(self.store, app_ids={'instagram':APP},
            evidence_reader=lambda ref: copy.deepcopy(records[ref]), clock=lambda:F.NOW)
        args = dict(policy=policy('instagram'), token=TOKEN, diagnostic_ref='operator:diagnostic',
            app_review_ref='operator:review', consent_ref='operator:consent',
            selection={'ig_user_id':'178400009999','hashtag':'music'}, quota_rules=review['quota_rules'])
        result = service.register_connection(**args)
        self.assertEqual(self.store.grants[result['authorization_id']]['review']['verified_scopes'], ('instagram_basic',))
        for change in ({'approved_features':[]}, {'approved_scopes': ['instagram_business_basic']}):
            old = copy.deepcopy(review)
            review.update(change)
            with self.assertRaises(ContractError): service.register_connection(**args)
            review.clear(); review.update(old)
        diagnostic['identity']['token_subject_id'] = '99999'
        with self.assertRaises(ContractError): service.register_connection(**args)

    def test_facebook_ppca_feature_requires_eligible_exact_page(self):
        from postriff_phase2.growth.trends.providers import meta_public as meta
        records = evidence()
        for record in (records['operator:diagnostic'], records['operator:consent']):
            record.update(provider_id='facebook', operation='page_public_posts')
        diagnostic = records['operator:diagnostic']
        diagnostic.update(api_version=meta.GRAPH_VERSION, login_kind='facebook_login', account_kind='system_user')
        diagnostic['response']['data'].update(type='SYSTEM_USER', scopes=[])
        review = records['operator:review']
        review.update(provider_id='facebook', operation='page_public_posts', api_version=meta.GRAPH_VERSION,
            approved_scopes=[], approved_features=['pages_public_content_access'],
            reviewed_page_ids=['54321'], page_public=True, page_restricted=False,
            quota_rules={'facebook_public_page_read': {'limit':10,'window_seconds':86400}})
        service = C.MetaPublicControlService(self.store, app_ids={'facebook':APP},
            evidence_reader=lambda ref: copy.deepcopy(records[ref]), clock=lambda:F.NOW)
        args = dict(policy=policy('facebook'), token=TOKEN, diagnostic_ref='operator:diagnostic',
            app_review_ref='operator:review', consent_ref='operator:consent',
            selection={'reviewed_page_id':'54321'}, quota_rules=review['quota_rules'])
        result = service.register_connection(**args)
        self.assertEqual(self.store.grants[result['authorization_id']]['review']['verified_scopes'], ())
        for change in ({'approved_features':[]}, {'page_public':False}, {'page_restricted':True},
                       {'reviewed_page_ids':['12345']}):
            old = copy.deepcopy(review)
            review.update(change)
            with self.assertRaises(ContractError): service.register_connection(**args)
            review.clear(); review.update(old)

    def test_third_party_attestation_is_imported_only_from_trusted_review(self):
        self.records['operator:review'].update(
            third_party_source_ids=['threads:998877'],
            third_party_evidence_ref='operator:third-party-artifact')
        receipt = self.register()
        selection = self.store.grants[receipt['authorization_id']]['selection']
        self.assertEqual(selection.get('third_party_source_ids'), ['threads:998877'])
        self.assertEqual(selection.get('third_party_evidence_ref'), 'operator:third-party-artifact')
        self.assertEqual(receipt['activation_state'], 'awaiting_live_public_read')
        with self.assertRaises(ContractError):
            self.register(selection={'query':'piano','search_type':'RECENT',
                'third_party_source_ids':['threads:998877'],
                'third_party_evidence_ref':'client:claim'})

    def test_malformed_or_cross_provider_third_party_attestation_is_denied(self):
        for sources in (['instagram:998877'], ['threads:abc'], ['threads:1?token=x'],
                        ['threads:1','threads:1'], ['threads:'+str(i) for i in range(21)],
                        'threads:998877', ['threads:123_456']):
            self.records['operator:review'].update(third_party_source_ids=sources,
                third_party_evidence_ref='operator:third-party-artifact')
            with self.subTest(sources=sources), self.assertRaises(ContractError):
                self.register()
        self.assertEqual(self.store.credentials,{})
        self.records['operator:review'].update(third_party_source_ids=['threads:998877'],
            third_party_evidence_ref='')
        with self.assertRaises(ContractError): self.register()

    def test_default_attestation_is_empty_and_never_activates_a_source(self):
        receipt = self.register()
        selection = self.store.grants[receipt['authorization_id']]['selection']
        self.assertEqual(selection.get('third_party_source_ids',[]),[])
        self.assertNotIn('third_party_evidence_ref',selection)
        self.assertEqual(receipt['activation_state'],'awaiting_live_public_read')

    def test_unchanged_operator_artifacts_cannot_widen_processing_rights(self):
        from dataclasses import replace
        from postriff_phase2.growth.trends.contracts import digest
        permissions = ('llm_process','store_raw','store_metrics','share_across_workspaces','cross_source_combine')
        approved = policy('threads', rights=F.permissions(**{key:'deny' for key in permissions}))
        for ref in ('operator:review','operator:consent'):
            self.records[ref].update(source_policy_id=approved.id, source_policy_version=approved.version,
                scope_key=approved.scope_key, rights_digest=digest(approved.rights),
                max_retention_seconds=approved.retention_seconds)
        for permission in permissions:
            widened = copy.deepcopy(approved.rights)
            widened[permission]['state'] = 'allow'
            with self.subTest(permission=permission), self.assertRaises(ContractError):
                self.register(policy=replace(approved,rights=widened))
        self.assertEqual(self.store.credentials,{})
        self.assertEqual(self.store.calls,[])

    def test_both_artifacts_must_bind_policy_identity_rights_and_retention(self):
        from dataclasses import replace
        from postriff_phase2.growth.trends.contracts import digest
        original = policy('threads')
        for ref in ('operator:review','operator:consent'):
            self.records[ref].update(source_policy_id=original.id, source_policy_version=original.version,
                scope_key=original.scope_key, rights_digest=digest(original.rights),
                max_retention_seconds=original.retention_seconds)
        for changes in ({'retention_seconds':3601}, {'version':'unreviewed-v2'}, {'id':'unreviewed-policy'}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.register(policy=replace(original,**changes))
        for ref in ('operator:review','operator:consent'):
            original_record=copy.deepcopy(self.records[ref])
            for changes in ({'rights_digest':'0'*64}, {'scope_key': 'workspace:'+F.OTHER},
                            {'max_retention_seconds':3599}, {'max_retention_seconds':True},
                            {'source_policy_version':'foreign'}, {'source_policy_id':'foreign'}):
                self.records[ref].update(changes)
                with self.subTest(ref=ref,changes=changes), self.assertRaises(ContractError):
                    self.register()
                self.records[ref]=copy.deepcopy(original_record)
        self.assertEqual(self.store.credentials,{})

    def test_enrollment_persists_independent_exact_reviewed_policy_capsule(self):
        approved = policy('threads', rights=F.permissions(llm_process='deny'))
        for ref in ('operator:review','operator:consent'):
            self.records[ref]['rights_digest'] = F.C.digest(approved.rights)
            self.records[ref]['max_retention_seconds'] = 7200
        expected_rights = copy.deepcopy(approved.rights)
        receipt = self.register(policy=approved)
        saved = self.store.grants[receipt['authorization_id']]['selection'].get('reviewed_policy')
        self.assertEqual(saved, dict(policy_id='synthetic-policy',version='fixture-v1',
            scope_key=F.SCOPE,provider_id='threads',operation='keyword_search',
            rights=expected_rights,max_retention_seconds=3600))
        approved.rights['llm_process']['state'] = 'allow'
        self.assertEqual(saved['rights']['llm_process']['state'],'deny')

    def test_caller_cannot_supply_reviewed_policy_capsule(self):
        with self.assertRaises(ContractError):
            self.register(selection={'query':'piano','search_type':'RECENT',
                'reviewed_policy':{'rights':F.permissions(),'max_retention_seconds':999999}})
        self.assertEqual(self.store.credentials,{})
        self.assertEqual(self.store.calls,[])


if __name__ == '__main__':
    unittest.main()
