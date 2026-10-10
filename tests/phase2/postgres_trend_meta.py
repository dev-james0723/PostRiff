"""Cloud disposable PostgreSQL acceptance. Synthetic Meta records; no provider I/O."""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
import threading
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from psycopg.types.json import Jsonb
from test_trend_pipeline import dedicated_test_dsn
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.growth.trends import retention
from postriff_phase2.growth.trends.contracts import ContractError, PERMISSIONS, iso
from postriff_phase2.growth.trends.policy import SourcePolicy
from postriff_phase2.growth.trends.jobs import TrendJobs
from postriff_phase2.growth.trends.retry import fail_attempt
from postriff_phase2.growth.trends.providers import meta_public as meta
from postriff_phase2.growth.trends.providers.base import observation
from postriff_phase2.growth.trends.providers.meta_runtime import MetaCollector, load_authorization
from postriff_phase2.growth.trends.store import TrendStore, trust_lock
from postriff_phase2.growth.trends.providers.meta_control import MetaPublicControlService

TOKEN = 'synthetic-meta-token'
OPERATIONS = {'threads': 'keyword_search', 'instagram': 'hashtag_discovery', 'facebook': 'page_public_posts'}
SCOPES = {'threads': ['threads_basic', 'threads_keyword_search'],
          'instagram': ['instagram_basic'], 'facebook': []}
FEATURES = {'threads': [], 'instagram': ['instagram_public_content_access'],
            'facebook': ['pages_public_content_access']}


class MetaPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = dedicated_test_dsn()
        cls.role = 'meta_fixture_' + uuid4().hex[:12]
        with psycopg.connect(cls.dsn) as db:
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())
            migration = ROOT / 'migrations/postriff/110_meta_public_trends.sql'
            if migration.exists(): db.execute(migration.read_text())
            assert db.execute("SELECT to_regclass('public.pr_trend_meta_authorizations')").fetchone()[0], \
                'Meta public authorization schema missing'
            db.execute('CREATE ROLE ' + cls.role + ' NOSUPERUSER NOBYPASSRLS INHERIT')
            db.execute('GRANT service_role TO ' + cls.role)
            # Legacy tenancy expects Supabase BYPASSRLS; only this old table needs
            # a fixture policy. Migration110 supplies all new-table RLS policies.
            db.execute('CREATE POLICY meta_fixture_workspace ON public.pr_workspaces '
                       'FOR ALL TO service_role USING(true) WITH CHECK(true)')

    def connect(self):
        db = psycopg.connect(self.dsn)
        db.execute('SET ROLE ' + self.role)
        return db

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.start, self.end = iso(self.now - timedelta(minutes=1)), iso(self.now + timedelta(days=1))
        self.workspace = self.new_workspace()
        self.vault = CredentialVault(CredentialVault.generate_key())
        self.store = TrendStore(self.connect, offline_replay=True)
        self.store.meta_vault = self.vault
        self.app_id = str(uuid4().int)[:15]

    def new_workspace(self):
        wid = str(uuid4())
        with psycopg.connect(self.dsn) as db:
            db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (wid,))
        return wid

    def grant(self, provider='threads', *, workspace=None, account=None, limit=10,
              hashtag='music', review_changes=None, credential_changes=None, changes=None, denied_rights=()):
        wid = workspace or self.workspace
        aid, connection = str(uuid4()), 'meta-fixture-' + uuid4().hex
        scope, account = 'workspace:' + wid, account or str(uuid4().int)[:15]
        ciphertext, key_id = self.vault.encrypt(TOKEN)
        rights = {p: {'state': 'deny' if p in denied_rights else 'allow', 'policy_ref': 'synthetic-reviewed',
                      'audience_scope': scope, 'expires_at': self.end} for p in PERMISSIONS}
        policy = SourcePolicy(id='synthetic-policy', version='fixture-' + uuid4().hex,
            provider_id=provider, operation=OPERATIONS[provider], scope_key=scope, rights=rights,
            reviewed_by='synthetic-reviewer', review_ref='synthetic-review', effective_at=self.start,
            expires_at=self.end, retention_seconds=3600, readiness='ready',
            verified_scopes=tuple(SCOPES[provider]), price_ref=None, approved_attempt_cap_microusd=0)
        selection = {'threads': {'query': 'piano', 'search_type': 'RECENT'},
                     'instagram': {'ig_user_id': account, 'hashtag': hashtag},
                     'facebook': {'reviewed_page_id': account}}[provider]
        selection['reviewed_policy'] = dict(policy_id=policy.id, version=policy.version,
            scope_key=scope, provider_id=provider, operation=policy.operation,
            rights=copy.deepcopy(policy.rights), max_retention_seconds=policy.retention_seconds)
        review = dict(review_id=aid, app_id=self.app_id, provider_id=provider,
            operation=OPERATIONS[provider], api_version='v1.0' if provider == 'threads' else meta.GRAPH_VERSION,
            scope_key=scope, login_kind='threads_login' if provider == 'threads' else 'facebook_login',
            account_id=account, account_kind={'threads': 'user', 'instagram': 'business', 'facebook': 'app'}[provider],
            token_fingerprint=hashlib.sha256(TOKEN.encode()).hexdigest(),
            verified_scopes=SCOPES[provider], approved_scopes=SCOPES[provider],
            approved_features=FEATURES[provider],
            verified_at=iso(self.now - timedelta(seconds=5)), expires_at=iso(self.now + timedelta(minutes=10)),
            quota_limit=limit, quota_window_seconds=604800 if provider == 'instagram' else 86400,
            reviewed_page_ids=[account] if provider == 'facebook' else [],
            page_public=provider == 'facebook', page_restricted=False, consent_current=True,
            review_ref='synthetic:meta-app-review', quota_rule_ref='synthetic:meta-quota')
        review.update(review_changes or {})
        quota_rules = {'threads_keyword_search': {'limit': limit, 'window_seconds': 86400},
                       'instagram_graph_request': {'limit': limit, 'window_seconds': 86400},
                       'instagram_distinct_hashtag_7d': {'limit': min(limit, 30), 'window_seconds': 604800},
                       'facebook_public_page_read': {'limit': limit, 'window_seconds': 86400}}
        credential = dict(provider='meta_public_' + provider, provider_account_id=account,
                          access_ciphertext=ciphertext, key_id=key_id, scopes=SCOPES[provider],
                          access_expires_at=self.end, revoked_at=None)
        credential.update(credential_changes or {})
        value = dict(authorization_id=aid, workspace_id=wid, connection_id=connection,
            provider_id=provider, operation=OPERATIONS[provider], source_policy_version=policy.version,
            review=Jsonb(review), selection=Jsonb(selection), quota_rules=Jsonb(quota_rules),
            ciphertext_digest=hashlib.sha256(ciphertext.encode()).hexdigest(),
            consent_at=self.start, expires_at=self.end, revoked_at=None)
        value.update(changes or {})
        with self.connect() as db:
            db.execute('INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,' +
                       ','.join(credential) + ') VALUES(' + ','.join(['%s'] * (2 + len(credential))) + ')',
                       [wid, connection, *credential.values()])
            db.execute('INSERT INTO public.pr_trend_meta_authorizations(' + ','.join(value) +
                       ') VALUES(' + ','.join(['%s'] * len(value)) + ')', list(value.values()))
            db.execute('''INSERT INTO public.pr_trend_provider_contracts
                (provider_id,version,operations,valid_from,expires_at,manifest)
                VALUES(%s,%s,%s,%s,%s,'{}') ON CONFLICT DO NOTHING''',
                (provider, meta.PROTOCOL, list(PERMISSIONS), self.start, self.end))
        self.store.ensure_scope(scope)
        self.store.register_policy({**asdict(policy), 'meta_authorization_id': aid}, provider_contract_version=meta.PROTOCOL)
        return dict(id=aid, connection=connection, policy=policy, review=review,
                    account=account, workspace=wid, ciphertext=ciphertext, selection=selection)

    def active(self, grant):
        with self.connect() as db:
            return db.execute('SELECT postriff_private.trend_meta_authorization_valid(%s)', (grant['id'],)).fetchone()[0]

    def collect(self, grant):
        return MetaCollector(self.store, grant['id'])

    def assert_current_sql(self, grant):
        if not self.active(grant):
            # Only for a known-valid synthetic fixture, expose swallowed SQL
            # faults without weakening the production fail-closed helper.
            # The diagnostic definition is rolled back with this transaction.
            with psycopg.connect(self.dsn) as db:
                definition = db.execute("SELECT pg_get_functiondef('postriff_private.trend_meta_authorization_valid(uuid)'::regprocedure)").fetchone()[0]
                diagnostic = definition.replace('postriff_private.trend_meta_authorization_valid(',
                    'postriff_private.meta_fixture_authorization_diagnostic(', 1).replace(
                    'exception when others then return false;', 'exception when others then raise;')
                db.execute(diagnostic)
                valid = db.execute('SELECT postriff_private.meta_fixture_authorization_diagnostic(%s)', (grant['id'],)).fetchone()[0]
                db.rollback()
            self.assertTrue(valid, 'valid synthetic Meta proof failed a current SQL admission predicate')

    def test_current_server_grants_accept_three_distinct_reviewed_operations(self):
        for provider in ('threads', 'instagram', 'facebook'):
            with self.subTest(provider=provider):
                grant = self.grant(provider)
                self.assert_current_sql(grant)
                _, proof, token = load_authorization(self.store, grant['id'], grant['policy'], at=iso(self.now))
                self.assertEqual((proof.provider_id, token), (provider, TOKEN))

    def tree(self, grant, *, provenance=None):
        p, at = grant['policy'], iso(self.now - timedelta(seconds=2))
        source = observation(policy=p, source_identity=p.provider_id + ':' + str(uuid4()),
            revision_identity='revision1', sequence=1, kind='raw_post', operation='create',
            payload={'platform': p.provider_id, 'native_id': str(uuid4().int), 'author_status': 'unknown',
                     'text': 'Synthetic permitted source', 'language': 'en'},
            event_at=self.start, received_at=at, available_at=at, coverage_epoch='synthetic',
            contract_version=meta.PROTOCOL, access_method='official_graph_json')
        source['provenance'].update(provenance if provenance is not None else {'review_id': grant['id']})
        self.store.put_observation(source)
        manifest = self.store.put_manifest(p.scope_key, [{'scope_key': p.scope_key, 'node_id': source['observation_id']}],
            decision_cutoff=at, available_at=at, retention_until=source['retention_until'])
        child = str(uuid4())
        with self.connect() as db:
            db.execute('''INSERT INTO public.pr_trend_nodes(scope_key,node_id,node_kind,available_at,retention_until)
                VALUES(%s,%s,'manifest',%s,%s)''', (p.scope_key, child, at, source['retention_until']))
            db.execute('''INSERT INTO public.pr_trend_dependencies(scope_key,node_id,input_scope_key,input_node_id)
                VALUES(%s,%s,%s,%s)''', (p.scope_key, child, p.scope_key, manifest['manifest_id']))
        return source['observation_id'], manifest['manifest_id'], child

    def valid_nodes(self, grant, ids):
        with self.connect() as db:
            return [db.execute('SELECT postriff_private.trend_node_valid(%s,%s)',
                    (grant['policy'].scope_key, node)).fetchone()[0] for node in ids]

    def test_nonbypass_server_can_use_grant_but_clients_cannot_enumerate(self):
        grant = self.grant()
        self.assertTrue(self.active(grant))
        for role in ('anon', 'authenticated'):
            for table in ('pr_trend_meta_authorizations', 'pr_trend_meta_quota_events'):
                with self.subTest(role=role, table=table), psycopg.connect(self.dsn) as db:
                    db.execute('SET LOCAL ROLE ' + role)
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        db.execute('SELECT * FROM public.' + table)
        # Even accidental table grants cannot defeat the forced-RLS policies.
        with psycopg.connect(self.dsn) as db:
            for table in ('pr_trend_meta_authorizations', 'pr_trend_meta_quota_events'):
                self.assertEqual(db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class '
                    'WHERE oid=%s::regclass', ('public.' + table,)).fetchone(), (True, True))
                db.execute('GRANT SELECT ON public.' + table + ' TO authenticated')
            db.execute('SET LOCAL ROLE authenticated')
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_meta_authorizations').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_meta_quota_events').fetchone()[0], 0)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute('SELECT postriff_private.trend_meta_authorization_valid(%s)', (grant['id'],))

    def test_review_selection_quota_immutable_and_revocation_final(self):
        grant = self.grant()
        for column, value in (('review', Jsonb({})), ('selection', Jsonb({})), ('quota_rules', Jsonb({})),
                              ('source_policy_version', 'replacement'), ('ciphertext_digest', 'a' * 64)):
            with self.subTest(column=column), self.connect() as db, self.assertRaises(psycopg.Error):
                db.execute('UPDATE public.pr_trend_meta_authorizations SET ' + column + '=%s '
                           'WHERE authorization_id=%s', (value, grant['id']))
        with self.connect() as db:
            db.execute('UPDATE public.pr_trend_meta_authorizations SET revoked_at=clock_timestamp() '
                       'WHERE authorization_id=%s', (grant['id'],))
        self.assertFalse(self.active(grant))
        with self.connect() as db, self.assertRaises(psycopg.Error):
            db.execute('UPDATE public.pr_trend_meta_authorizations SET revoked_at=NULL WHERE authorization_id=%s', (grant['id'],))

    def test_unverified_owned_stale_foreign_and_malformed_proofs_fail_closed(self):
        for changes in ({'account_id': '999999'}, {'scope_key': 'workspace:' + str(uuid4())},
                        {'review_id': str(uuid4())}, {'operation': 'owned_read'}, {'consent_current': False},
                        {'approved_scopes': ['threads_basic']}, {'approved_features': 'malformed'},
                        {'verified_at': iso(self.now - timedelta(minutes=16))},
                        {'verified_at': iso(self.now + timedelta(minutes=1))},
                        {'expires_at': iso(self.now - timedelta(seconds=1))}, {'verified_at': 'malformed'}):
            with self.subTest(changes=changes): self.assertFalse(self.active(self.grant(review_changes=changes)))
        for changes in ({'provider': 'threads'}, {'scopes': ['threads_basic']},
                        {'scopes': SCOPES['threads'] + ['unexpected_added_scope']},
                        {'access_expires_at': iso(self.now - timedelta(seconds=1))}, {'revoked_at': self.start}):
            with self.subTest(credential=changes): self.assertFalse(self.active(self.grant(credential_changes=changes)))

    def test_foreign_policy_cannot_load_another_workspace_grant(self):
        grant = self.grant()
        foreign = replace(grant['policy'], scope_key='workspace:' + self.new_workspace())
        with self.assertRaises(ContractError): load_authorization(self.store, grant['id'], foreign, at=iso(self.now))

    def test_owned_and_licensed_meta_operations_keep_existing_policy_path(self):
        for provider in ('threads', 'instagram', 'facebook'):
            grant = self.grant(provider)
            for operation in ('owned_read', 'licensed_discovery'):
                policy = replace(grant['policy'], version='fixture-' + uuid4().hex, operation=operation)
                self.store.register_policy(asdict(policy), provider_contract_version=meta.PROTOCOL)
                ids = self.tree({**grant, 'policy': policy}, provenance={})
                self.assertEqual(self.valid_nodes({**grant, 'policy': policy}, ids), [True, True, True])

    def test_proof_expiry_hides_already_stored_descendants(self):
        expiry = datetime.now(timezone.utc) + timedelta(seconds=3)
        grant = self.grant(review_changes={'expires_at': iso(expiry)})
        ids = self.tree(grant)
        self.assertEqual(self.valid_nodes(grant, ids), [True, True, True])
        time.sleep(max(0, (expiry - datetime.now(timezone.utc)).total_seconds()) + 0.05)
        self.assertEqual(self.valid_nodes(grant, ids), [False, False, False])

    def test_same_version_policy_cannot_widen_imported_rights_or_retention(self):
        for mutation in ('rights', 'retention', 'policy_id'):
            with self.subTest(mutation=mutation):
                grant = self.grant(denied_rights=('llm_process',))
                ids = self.tree(grant)
                self.assertEqual(self.valid_nodes(grant, ids), [True, True, True])
                manifest = asdict(grant['policy'])
                if mutation == 'rights': manifest['rights']['llm_process']['state'] = 'allow'
                elif mutation == 'retention': manifest['retention_seconds'] += 1
                else: manifest['id'] = 'unreviewed-replacement'
                # A later registry write with the same version cannot substitute
                # a policy for the independent rights captured during import.
                with self.connect() as db:
                    db.execute('''UPDATE public.pr_trend_source_policies
                        SET rights=%s,max_retention_seconds=%s,manifest=manifest||%s
                        WHERE scope_key=%s AND provider_id=%s AND version=%s''',
                        (Jsonb(manifest['rights']), manifest['retention_seconds'], Jsonb(manifest),
                         grant['policy'].scope_key, grant['policy'].provider_id, grant['policy'].version))
                self.assertEqual(self.valid_nodes(grant, ids), [False, False, False])
                with self.assertRaises(ContractError):
                    load_authorization(self.store, grant['id'], SourcePolicy(**manifest), at=iso(self.now))

    def test_authorization_revocation_hides_existing_descendants_and_purges(self):
        grant = self.grant()
        ids = self.tree(grant)
        self.assertEqual(self.valid_nodes(grant, ids), [True, True, True])
        with self.connect() as db:
            db.execute('UPDATE public.pr_trend_meta_authorizations SET revoked_at=clock_timestamp() '
                       'WHERE authorization_id=%s', (grant['id'],))
        self.assertEqual(self.valid_nodes(grant, ids), [False, False, False])
        with self.assertRaises(ContractError):
            self.collect(grant).reserve(grant['policy'], 'threads_keyword_search', grant['policy'].scope_key, 1)
        retention.sweep(self.store)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT payload,provenance,purged_at IS NOT NULL FROM '
                'public.pr_trend_observations WHERE observation_id=%s', (ids[0],)).fetchone(), ({}, {}, True))
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_nodes WHERE node_id=ANY(%s::uuid[]) '
                "AND validity='purged'", (list(ids),)).fetchone()[0], 3)

    def test_credential_replace_revoke_expire_and_workspace_delete_hide_descendants(self):
        for mutation in ('replace', 'revoke', 'expire', 'workspace_deleting'):
            with self.subTest(mutation=mutation):
                grant = self.grant()
                ids = self.tree(grant)
                self.assertEqual(self.valid_nodes(grant, ids), [True, True, True])
                with self.connect() as db:
                    if mutation == 'workspace_deleting':
                        db.execute("UPDATE public.pr_workspaces SET state=state||'{\"accountDeletion\":{}}'::jsonb WHERE id=%s", (self.workspace,))
                    else:
                        setter = {'replace': "access_ciphertext='different-ciphertext'", 'revoke': 'revoked_at=clock_timestamp()',
                                  'expire': "access_expires_at=clock_timestamp()-interval '1 second'"}[mutation]
                        db.execute('UPDATE public.pr_encrypted_credentials SET ' + setter +
                                   ' WHERE workspace_id=%s AND connection_id=%s', (grant['workspace'], grant['connection']))
                self.assertEqual(self.valid_nodes(grant, ids), [False, False, False])

    def test_observation_cannot_substitute_missing_other_or_foreign_review(self):
        grant, other, foreign = self.grant(), self.grant(), self.grant(workspace=self.new_workspace())
        for provenance in ({}, {'review_id': other['id']}, {'review_id': foreign['id']}, {'review_id': 'malformed'}):
            with self.subTest(provenance=provenance), self.assertRaises(ContractError): self.tree(grant, provenance=provenance)

    def test_one_remaining_quota_slot_atomic_between_workspaces(self):
        account = str(uuid4().int)[:15]
        grants = [self.grant(account=account, limit=1), self.grant(workspace=self.new_workspace(), account=account, limit=1)]
        barrier = threading.Barrier(2)
        def reserve(grant):
            barrier.wait(timeout=10)
            try: return self.collect(grant).reserve(grant['policy'], 'threads_keyword_search', grant['policy'].scope_key, 1)
            except ContractError as error:
                self.assertEqual(str(error), 'meta_provider_quota_exhausted')
                return False
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(sorted(pool.map(reserve, grants)), [False, True])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_meta_quota_events '
                'WHERE authorization_id=ANY(%s::uuid[])', ([g['id'] for g in grants],)).fetchone()[0], 1)

    def test_quota_survives_authorization_and_workspace_removal(self):
        grant = self.grant(limit=1)
        self.collect(grant).reserve(grant['policy'], 'threads_keyword_search', grant['policy'].scope_key, 1)
        with self.connect() as db:
            bucket, subject = db.execute('SELECT bucket_digest,subject_digest FROM public.pr_trend_meta_quota_events '
                                        'WHERE authorization_id=%s', (grant['id'],)).fetchone()
            self.assertRegex(bucket, '^[a-f0-9]{64}$'); self.assertRegex(subject, '^[a-f0-9]{64}$')
            db.execute('DELETE FROM public.pr_trend_meta_authorizations WHERE authorization_id=%s', (grant['id'],))
        with psycopg.connect(self.dsn) as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (grant['workspace'],))
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT authorization_id FROM public.pr_trend_meta_quota_events '
                                        'WHERE bucket_digest=%s', (bucket,)).fetchone(), (None,))
        reconnect = self.grant(workspace=self.new_workspace(), account=grant['account'], limit=1)
        with self.assertRaisesRegex(ContractError, 'meta_provider_quota_exhausted'):
            self.collect(reconnect).reserve(reconnect['policy'], 'threads_keyword_search', reconnect['policy'].scope_key, 1)

    def test_instagram_distinct_hashtag_account_global_and_repeat_free(self):
        account = str(uuid4().int)[:15]
        first = self.grant('instagram', account=account, limit=1, hashtag='Music')
        repeated = self.grant('instagram', account=account, workspace=self.new_workspace(), limit=1, hashtag='music')
        other = self.grant('instagram', account=account, workspace=self.new_workspace(), limit=1, hashtag='piano')
        for grant in (first, repeated):
            self.assertTrue(self.collect(grant).reserve(grant['policy'], 'instagram_distinct_hashtag_7d', account + ':music', 1))
        with self.assertRaisesRegex(ContractError, 'meta_provider_quota_exhausted'):
            self.collect(other).reserve(other['policy'], 'instagram_distinct_hashtag_7d', account + ':piano', 1)

    def test_collector_commits_quota_before_io_and_retains_uncertain_failure(self):
        grant = self.grant(limit=1)
        observed = []
        test = self
        class FailedTransport:
            def get(self, _url, **_kwargs):
                # A second real connection sees only committed reservations.
                with test.connect() as db:
                    observed.append(db.execute('SELECT count(*) FROM public.pr_trend_meta_quota_events '
                        'WHERE authorization_id=%s', (grant['id'],)).fetchone()[0])
                raise TimeoutError('synthetic uncertain provider outcome')
        collector = MetaCollector(self.store, grant['id'], transport=FailedTransport())
        args = dict(policy=grant['policy'], cursor=None, now=iso(self.now),
                    payload={'coverage_epoch': 'synthetic', 'max_items': 1}, reservation_microusd=0)
        with self.assertRaisesRegex(ContractError, 'meta_transport_unavailable'):
            collector(**args)
        self.assertEqual(observed, [1])
        with self.assertRaisesRegex(ContractError, 'meta_provider_quota_exhausted'):
            collector(**args)
        self.assertEqual(observed, [1], 'exhausted quota dispatched a second request')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_meta_quota_events '
                'WHERE authorization_id=%s', (grant['id'],)).fetchone()[0], 1)

    def test_instagram_collector_commits_distinct_and_each_graph_request_before_io(self):
        grant = self.grant('instagram', limit=3)
        observed = []
        test = self
        class InstagramTransport:
            def get(self, _url, **_kwargs):
                with test.connect() as db:
                    observed.append(db.execute('SELECT count(*) FROM public.pr_trend_meta_quota_events '
                        'WHERE authorization_id=%s', (grant['id'],)).fetchone()[0])
                return ({'data': [{'id': '17841230000'}]} if len(observed) == 1 else {'data': []}, {}, 20)
        collector = MetaCollector(self.store, grant['id'], transport=InstagramTransport())
        collector(policy=grant['policy'], cursor=None, now=iso(self.now),
            payload={'coverage_epoch': 'synthetic', 'max_items': 1}, reservation_microusd=0)
        self.assertEqual(observed, [2, 3])

    def test_admission_holds_credential_and_grant_locks_until_commit(self):
        grant = self.grant()
        with self.store.transaction() as cur:
            load_authorization(self.store, grant['id'], grant['policy'], at=iso(self.now), cursor=cur)
            for table, where, args in (
                ('pr_trend_meta_authorizations', 'authorization_id=%s', (grant['id'],)),
                ('pr_encrypted_credentials', 'workspace_id=%s AND connection_id=%s', (grant['workspace'], grant['connection'])),
            ):
                with self.subTest(table=table), self.connect() as competing:
                    competing.execute("SET LOCAL lock_timeout='100ms'")
                    with self.assertRaises(psycopg.errors.LockNotAvailable):
                        competing.execute('UPDATE public.' + table + ' SET revoked_at=clock_timestamp() WHERE ' + where, args)
        self.assertTrue(self.active(grant))

    def test_provider_auth_failure_hides_lineage_but_rate_limit_preserves_rights(self):
        jobs = TrendJobs(self.store)
        for status in (401, 403, 429):
            with self.subTest(status=status):
                grant = self.grant(workspace=self.new_workspace())
                scope, nodes = grant['policy'].scope_key, self.tree(grant)
                self.assertTrue(self.active(grant))
                self.assertEqual(self.valid_nodes(grant, nodes), [True] * 3)
                queued = jobs.enqueue(scope, 'trend.ingest', {'operation': 'keyword_search'},
                    idempotency_key='meta-' + uuid4().hex, provider_id='threads',
                    source_policy_version=grant['policy'].version)
                claim = jobs.start(jobs.claim('meta-fixture-worker', job_id=queued['job_id'], scope_key=scope))
                fail_attempt(self.store, claim, status=status, dispatched=True,
                    proven_unbilled=status == 429, headers={'Retry-After': '60'} if status == 429 else None)
                with self.connect() as db:
                    health = db.execute('SELECT status,next_allowed_at>clock_timestamp() FROM '
                        'public.pr_trend_source_health WHERE scope_key=%s AND provider_id=%s',
                        (scope, 'threads')).fetchone()
                permitted = status == 429
                self.assertEqual(self.active(grant), permitted)
                self.assertEqual(self.valid_nodes(grant, nodes), [permitted] * 3)
                if permitted:
                    self.assertEqual(health, ('unavailable', True))
                    _, _, token = load_authorization(self.store, grant['id'], grant['policy'], at=iso(self.now))
                    self.assertEqual(token, TOKEN)
                else:
                    self.assertEqual(health[0], 'revoked')
                    with self.assertRaisesRegex(ContractError, 'meta_public_authorization_unavailable'):
                        load_authorization(self.store, grant['id'], grant['policy'], at=iso(self.now))

    def test_runtime_admission_does_not_lock_workspace_row(self):
        grant = self.grant()
        def bounded_connect():
            db = self.connect()
            db.execute("SET LOCAL lock_timeout='100ms'")
            return db
        store = TrendStore(bounded_connect, offline_replay=True)
        store.meta_vault = self.vault
        with self.connect() as workspace_writer:
            workspace_writer.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE',
                                     (grant['workspace'],))
            # The hosted deletion path holds workspace before the trust fence.
            # Admission holds trust and only grant/credential rows; taking a
            # workspace share lock here would invert that order and time out.
            _, _, token = load_authorization(store, grant['id'], grant['policy'], at=iso(self.now))
            self.assertEqual(token, TOKEN)

    def test_control_revocation_waits_on_trust_fence_then_erases_credential(self):
        grant = self.grant()
        def competing_connect():
            db = self.connect()
            db.execute("SET LOCAL lock_timeout='100ms'")
            return db
        control = MetaPublicControlService(TrendStore(competing_connect), app_ids={'threads': self.app_id},
                                          evidence_reader=lambda _ref: {})
        with self.store.transaction() as cur:
            # Hold only the shared advisory fence, no grant/credential row lock.
            # A writer that omits the exclusive trust fence would wrongly win.
            trust_lock(cur)
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                control.revoke_connection(workspace_id=grant['workspace'], authorization_id=grant['id'])
            self.assertTrue(self.active(grant))
        control.revoke_connection(workspace_id=grant['workspace'], authorization_id=grant['id'])
        self.assertFalse(self.active(grant))
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT access_ciphertext,revoked_at IS NOT NULL FROM '
                'public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',
                (grant['workspace'], grant['connection'])).fetchone(), ('', True))

    def test_local_quota_deferral_preserves_payload_refunds_attempt_and_releases_fence(self):
        grant, jobs = self.grant(), TrendJobs(self.store)
        scope = grant['policy'].scope_key
        keys = ['meta-' + uuid4().hex for _ in range(3)]
        for key, dimension in zip(keys, ('system', 'provider', 'workspace')):
            jobs.configure_budget(key, dimension, 100, self.start, self.end)
        payload = {'operation': 'keyword_search', 'max_items': 1, 'coverage_epoch': 'synthetic',
                   'budget_keys': keys, 'reservation_microusd': 0}
        queued = jobs.enqueue(scope, 'trend.ingest', payload, idempotency_key='meta-' + uuid4().hex,
            provider_id='threads', source_policy_version=grant['policy'].version, max_attempts=1)
        with self.connect() as db:
            usage_before = db.execute('SELECT count(*) FROM public.pr_model_usage_events').fetchone()[0]
        claim = jobs.claim('meta-fixture-worker', job_id=queued['job_id'], scope_key=scope,
                           budget_keys=keys, amount_micro_usd=0)
        self.assertEqual(claim['attempts'], 1)
        started = jobs.start(claim)
        deferred = jobs.defer_local(started, code='meta_provider_quota_exhausted')
        self.assertEqual((deferred['state'], deferred['attempts'], deferred['payload'],
                          deferred['lease_owner'], deferred['lease_until'], deferred['reservation_id']),
                         ('retry_wait', 0, payload, None, None, None))
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT state,usage_event_id FROM public.pr_trend_budget_reservations '
                'WHERE reservation_id=%s', (claim['reservation_id'],)).fetchone(), ('released', None))
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_model_usage_events').fetchone()[0], usage_before)
            self.assertTrue(db.execute('SELECT due_at>clock_timestamp() FROM public.pr_trend_jobs WHERE job_id=%s',
                                      (claim['job_id'],)).fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_source_health WHERE scope_key=%s',
                                       (scope,)).fetchone()[0], 0)
        with self.assertRaisesRegex(ContractError, 'stale_job_fence'):
            jobs.defer_local(started, code='meta_provider_quota_exhausted')
        with self.connect() as db:
            db.execute("UPDATE public.pr_trend_jobs SET due_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
                       (claim['job_id'],))
        retry = jobs.claim('meta-fixture-retry', job_id=queued['job_id'], scope_key=scope,
                           budget_keys=keys, amount_micro_usd=0)
        self.assertEqual(retry['attempts'], 1)
        self.assertGreater(retry['lease_generation'], claim['lease_generation'])
        self.assertNotEqual(retry['reservation_id'], claim['reservation_id'])
        with self.assertRaisesRegex(ContractError, 'stale_job_fence'):
            jobs.defer_local(started, code='meta_provider_quota_exhausted')
        jobs.cancel(scope, retry['job_id'])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MetaPostgres))
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
