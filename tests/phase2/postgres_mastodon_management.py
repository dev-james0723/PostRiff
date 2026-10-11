"""Real disposable PostgreSQL isolation and action journal. All Mastodon responses synthetic."""
import json
import hashlib
from types import SimpleNamespace
import os
from pathlib import Path
import sys
import time
import threading
import unittest
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import MastodonProvider
from postriff_phase2.mastodon_management import MastodonManagement
from test_hosted_wave1_connectors import PUBLIC, ok

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')


def connection(): return psycopg.connect(DSN, client_encoding='utf8')


class JournalTests(unittest.TestCase):
    def tearDown(self):
        # Health maintenance scans all workspaces. Keep each disposable test's
        # due credentials out of the next test's worker lease assertions.
        with connection() as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id IN (%s,%s)', (self.workspace, self.foreign))

    @classmethod
    def setUpClass(cls):
        cls.sql = (ROOT / 'migrations/postriff/113_mastodon_management.sql').read_text()
        with connection() as db:
            db.execute(cls.sql)
            db.execute(cls.sql)
            metrics = (ROOT / 'migrations/postriff/114_mastodon_native_metrics.sql').read_text()
            db.execute(metrics); db.execute(metrics)
            health = (ROOT / 'migrations/postriff/115_mastodon_connection_health.sql').read_text()
            db.execute(health); db.execute(health)

    def setUp(self):
        self.actor = str(uuid.uuid4())
        self.other = str(uuid.uuid4())
        self.now = time.time()
        self.posts = []
        self.calls = []
        self.sample_app_secret = uuid.uuid4().hex
        def transport(method, url, **kw):
            self.calls.append((method, url, kw))
            if '/api/v2/instance' in url: return ok({'version': '4.2.9'})
            if '/verify_credentials' in url:
                if '/apps/' in url: return ok({'scopes': ['read:accounts', 'write:favourites']})
                return ok({'id': '100', 'username': 'fixture'})
            if method == 'POST' and '/api/v1/apps' in url:
                return ok({'client_id': 'fixture-client', 'client_secret': self.sample_app_secret})
            if method == 'POST':
                self.posts.append(url)
                return ok({'id': '123'})
            return ok({}, 404)
        self.provider = MastodonProvider('https://rafii.io', transport=transport, production_reviewed=True, resolver=PUBLIC)
        self.vault = CredentialVault(CredentialVault.generate_key())
        with connection() as db:
            db.execute('INSERT INTO auth.users VALUES(%s),(%s)', (self.actor, self.other))
        self.service = HostedWorkspaceService(connection, lambda token: str(uuid.UUID(token)),
            clock=lambda: self.now, vault=self.vault, providers={'mastodon': self.provider}, public_base_url='https://rafii.io')
        self.workspace = self.service.bootstrap(self.actor, 'studio')['workspaceId']
        self.foreign = self.service.bootstrap(self.other, 'studio')['workspaceId']
        self.manager = MastodonManagement(self.service)
        self.account = '100@mastodon.social'
        self.connection_id = uuid.uuid4().hex
        encrypted, key = self.vault.encrypt(json.dumps({'v': 1, 'at': 'fixture-token', 'instance': 'mastodon.social',
            'clientId': 'fixture-client', 'clientSecret': self.sample_app_secret, 'scope': ['read:accounts', 'write:favourites']}))
        with connection() as db:
            db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'mastodon',%s,%s,%s,%s)",
                       (self.workspace, self.connection_id, self.account, encrypted, key, ['read:accounts', 'write:favourites']))

    def preview(self):
        return self.manager.preview(self.workspace, self.actor, self.connection_id, {'action': 'favourite', 'targetId': '123'})

    def test_exhausted_account_read_budget_blocks_all_remote_oauth_calls(self):
        from postriff_phase2.hosted import bucket
        with connection() as db:
            db.execute("INSERT INTO public.pr_auth_throttle(bucket,window_start,count) VALUES(%s,now(),60)",
                (bucket('mastodon-read-account:' + self.workspace + self.connection_id),))
        self.calls.clear()
        with self.assertRaises(AlphaError) as caught:
            self.manager._grant(self.workspace, self.actor, self.connection_id)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(self.calls, [])
        with connection() as db:
            row = db.execute('SELECT count FROM public.pr_auth_throttle WHERE bucket=%s',
                (bucket('mastodon-read-account:' + self.workspace + self.connection_id),)).fetchone()
            self.assertEqual(row[0], 60)  # The rejected transaction rolled back.

    def test_verified_receipt_survives_actual_sql_failure_in_optional_hook(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        calls = []
        def failed_hook(cur, *_args):
            calls.append('called')
            cur.execute('SELECT 1/0')  # Real PostgreSQL transaction-abort behavior.
        worker = PostgresWorker(connection, clock=lambda: self.now, worker_id='verified-hook-test', on_verified=failed_hook)
        job = {'id': uuid.uuid4().hex, 'state': 'processing', 'events': [], 'leaseOwner': worker.worker_id,
               'leaseId': 'exact-completion-lease', 'leaseUntil': self.now + 60,
               'manifest': {'platform': 'Mastodon', 'variantId': 'synthetic-variant', 'providerAccountId': self.account,
                            'channelId': self.connection_id, 'payload': {'text': 'SYNTHETIC verified hook regression'},
                            'voiceRevision': None, 'styleRevision': 1}}
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['jobs'].append(job)
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
        claimed = {'workspaceId': self.workspace, 'job': job, 'reconciliation': True}
        result = {'state': 'verified', 'reference': '123', 'confirmed': 'Synthetic exact native readback', 'verification': 'provider_lookup'}
        self.assertTrue(worker.complete(claimed, result))
        with connection() as db:
            current = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][-1]
            self.assertEqual(current['state'], 'verified'); self.assertEqual(current['providerReference'], '123')
            self.assertEqual(current['insights']['availability'], 'unavailable'); self.assertIsNone(current['leaseOwner'])
        self.assertFalse(worker.complete(claimed, result)); self.assertEqual(calls, ['called'])

    def health_channel(self):
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['channels'].append({'id': self.connection_id, 'platform': 'Mastodon', 'account': '@fixture@mastodon.social',
                'providerAccountId': self.account, 'configured': True, 'revoked': False, 'identityVerified': True,
                'capabilityVerified': True, 'scopes': ['read:accounts', 'write:favourites'], 'verifiedAt': self.now,
                'capabilityVersion': self.provider.capability_version, 'evidenceSource': 'oauth', 'expiresAt': 0})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
            db.execute("INSERT INTO public.pr_mastodon_health(workspace_id,connection_id,next_at) VALUES(%s,%s,now()-interval '1 minute') ON CONFLICT(workspace_id,connection_id) DO UPDATE SET next_at=excluded.next_at", (self.workspace, self.connection_id))

    def test_health_records_actual_proof_and_cannot_be_read_by_browser_role(self):
        from postriff_phase2.mastodon_health import maintain
        self.health_channel()
        result = maintain(self.service.oauth)
        self.assertEqual(result['state'], 'read_verified'); self.assertEqual(result['checked'], 1)
        self.assertEqual(self.manager.read(self.workspace, self.actor, self.connection_id, 'health')['data']['state'], 'read_verified')
        with self.assertRaises(AlphaError): self.manager.read(self.foreign, self.other, self.connection_id, 'health')
        with connection() as db:
            row = db.execute('SELECT state,failures,lease_id,next_at>now(),checked_at IS NOT NULL FROM public.pr_mastodon_health WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()
            self.assertEqual(row, ('read_verified', 0, None, True, True))
        with connection() as db, self.assertRaises(psycopg.errors.InsufficientPrivilege):
            db.execute('SET LOCAL ROLE authenticated'); db.execute('SELECT * FROM public.pr_mastodon_health')

    def test_migrated_origin_downgrades_authority_without_following_destination(self):
        from postriff_phase2.mastodon_health import maintain
        self.health_channel()
        self.scoped_transport(['read:accounts', 'write:favourites'],
            lambda _method, url, **_kw: ok({'id': '100', 'moved': {'id': '999', 'url': 'http://127.0.0.1/private'}}) if '/accounts/verify_credentials' in url else None)
        result = maintain(self.service.oauth)
        self.assertEqual(result['state'], 'reauthorization_required')
        with connection() as db:
            channel = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['channels'][-1]
            self.assertTrue(channel['revoked']); self.assertFalse(channel['identityVerified']); self.assertEqual(channel['providerAccountId'], self.account)
            self.assertEqual(channel['scopes'], []); self.assertEqual(channel['mastodonHealth']['reason'], 'account_moved')

    def test_health_lease_blocks_duplicate_checks_and_reconnect_wins_over_old_outcome(self):
        from postriff_phase2.mastodon_health import maintain
        self.health_channel(); started, release = threading.Event(), threading.Event()
        def reverify(*_args):
            started.set(); self.assertTrue(release.wait(5))
            with connection() as db:
                db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s WHERE workspace_id=%s AND connection_id=%s', ('new-encrypted-consent', self.workspace, self.connection_id))
            return {'state': 'scope_changed', 'ready': False}
        with patch.object(self.service.oauth, 'reverify_for_worker', side_effect=reverify), ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(maintain, self.service.oauth); self.assertTrue(started.wait(5))
            second = maintain(self.service.oauth); self.assertEqual(second['checked'], 0)
            release.set(); self.assertEqual(first.result()['state'], 'connection_changed')
        with connection() as db:
            self.assertEqual(db.execute('SELECT state,failures,lease_id FROM public.pr_mastodon_health WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone(), ('pending', 0, None))

    def test_401_removes_only_observed_credential_and_old_revoke_cannot_erase_reconnect(self):
        self.health_channel()
        with connection() as db:
            old = db.execute('SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()[0]
            db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s WHERE workspace_id=%s AND connection_id=%s', ('new-consent', self.workspace, self.connection_id))
        self.assertFalse(self.service.oauth.mark_mastodon_revoked(self.workspace, self.connection_id, expected_ciphertext=old))
        with connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s WHERE workspace_id=%s AND connection_id=%s', (old, self.workspace, self.connection_id))
        self.provider.transport = lambda *_args, **_kwargs: ok({}, 401)
        with self.assertRaises(AlphaError) as caught: self.service.oauth.token_for_worker(self.workspace, self.connection_id)
        self.assertEqual(caught.exception.code, 'mastodon_authorization_revoked')
        with connection() as db:
            row = db.execute('SELECT revoked_at IS NOT NULL,access_ciphertext,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()
            self.assertEqual(row, (True, '', []))

    def scoped_transport(self, scopes, custom):
        with connection() as db:
            encrypted = db.execute('SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()
            envelope = json.loads(self.vault.decrypt(*encrypted)); envelope['scope'] = scopes
            envelope['capabilities'] = {'streamingUrl': 'https://mastodon.social'}
            cipher, key = self.vault.encrypt(json.dumps(envelope))
            db.execute('UPDATE public.pr_encrypted_credentials SET scopes=%s,access_ciphertext=%s,key_id=%s WHERE workspace_id=%s AND connection_id=%s', (scopes, cipher, key, self.workspace, self.connection_id))
        original = self.provider.transport
        def transport(method, url, **kw):
            if '/api/v1/apps/verify_credentials' in url: return ok({'scopes': scopes})
            handled = custom(method, url, **kw)
            return handled if handled is not None else original(method, url, **kw)
        self.provider.transport = transport

    def test_exact_native_reschedule_and_cancellation_sync_existing_queue_atomically(self):
        native = {'at': datetime.fromtimestamp(self.now + 600, timezone.utc).isoformat(), 'gone': False}
        writes = []
        def transport(method, url, **kw):
            if '/api/v1/scheduled_statuses/41' not in url: return None
            if method == 'PUT': native['at'] = kw['body']['scheduled_at']; writes.append(method)
            if method == 'DELETE': native['gone'] = True; writes.append(method); return ok({})
            return ok({}, 404) if native['gone'] else ok({'id': '41', 'scheduled_at': native['at']})
        self.scoped_transport(['read:accounts', 'read:statuses', 'write:statuses'], transport)
        manifest = {'platform': 'Mastodon', 'providerAccountId': self.account, 'channelId': self.connection_id,
                    'payload': {'text': 'Preserve the approved post'}, 'publishOptions': {'scheduled_at': native['at']}}
        job = {'id': 'existing-native-job', 'manifest': manifest, 'state': 'processing', 'approvalDigest': 'original-approval',
               'progress': {'stage': 'native_scheduled', 'reference': '41', 'scheduledAt': native['at']},
               'leaseOwner': 'old-worker', 'leaseId': 'old-fence', 'leaseUntil': self.now + 45}
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['jobs'] = [job]
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
        new_at = datetime.fromtimestamp(self.now + 1200, timezone.utc).isoformat()
        preview = self.manager.preview(self.workspace, self.actor, self.connection_id, {'action': 'native_reschedule', 'targetId': '41', 'scheduled_at': new_at})
        result = self.execute(preview); self.assertEqual(result['state'], 'verified'); self.assertEqual(result['syncedJobIds'], ['existing-native-job'])
        with connection() as db:
            persisted = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][0]
            self.assertEqual(persisted['manifest'], manifest); self.assertEqual(persisted['approvalDigest'], 'original-approval')
            self.assertEqual(persisted['progress']['scheduledAt'], new_at); self.assertIsNone(persisted['leaseOwner'])
        self.assertTrue(self.execute(preview)['replayed']); self.assertEqual(writes, ['PUT'])
        cancel = self.manager.preview(self.workspace, self.actor, self.connection_id, {'action': 'native_cancel', 'targetId': '41'})
        self.assertEqual(self.execute(cancel)['state'], 'verified')
        with connection() as db:
            persisted = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][0]
            self.assertEqual(persisted['state'], 'canceled'); self.assertTrue(persisted['cancelRequested'])

    def test_stream_rechecks_tenant_and_revocation_before_private_result(self):
        self.scoped_transport(['read:accounts', 'read:statuses', 'read:notifications'], lambda *_a, **_kw: None)
        def window(_origin, _token):
            with connection() as db:
                db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id))
            return {'status': 200, 'events': [{'id': '22', 'excerpt': 'PRIVATE_NOT_RETURNED_AFTER_REVOKE'}]}
        self.provider.streaming_transport = window
        with self.assertRaises(AlphaError): self.manager.read(self.foreign, self.other, self.connection_id, 'live_events')
        with self.assertRaises(AlphaError): self.manager.read(self.workspace, self.actor, self.connection_id, 'live_events')

    def test_private_notification_response_is_fenced_after_revocation(self):
        def transport(method, url, **_kwargs):
            if '/api/v1/notifications' not in url:
                return None
            with connection() as db:
                db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id))
            return ok([{'id': '22', 'type': 'mention', 'status': {'id': '23', 'visibility': 'direct',
                'content': 'PRIVATE_LATE_RESPONSE_MUST_NOT_ESCAPE'}}])
        self.scoped_transport(['read:accounts', 'read:notifications'], transport)
        with self.assertRaises(AlphaError) as caught:
            self.manager.read(self.workspace, self.actor, self.connection_id, 'notifications')
        self.assertEqual(caught.exception.code, 'mastodon_read_changed')

    def audio(self, cur):
        asset_id = uuid.uuid4().hex
        cur.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,bucket,object_name,etag,processing_status) VALUES(%s,%s,%s,'test.mp3','audio','audio/mpeg','mp3',200,%s,'postriff-private',%s,'synthetic-etag','unsupported')",
                    (asset_id, self.workspace, self.actor, 'c' * 64, asset_id + '.mp3'))
        return asset_id

    def test_audio_custody_is_workspace_bound_and_frozen_at_queue_entry(self):
        from postriff_phase2.mastodon_media import audio_snapshot, library_bindings_current, validate_new_bindings
        with connection() as db, db.cursor() as cur:
            asset_id = self.audio(cur)
            snapshot = audio_snapshot(cur, self.workspace, asset_id)
            manifest = {'platform': 'Mastodon', 'media': [{**snapshot, 'rightsConfirmed': True}]}
            self.assertTrue(library_bindings_current(cur, self.workspace, manifest))
            with self.assertRaises(AlphaError): audio_snapshot(cur, self.foreign, asset_id)
            before = {'phase2': {'reviews': [], 'jobs': []}}
            after = {'phase2': {'reviews': [{'id': 'review', 'manifest': manifest}], 'jobs': []}}
            validate_new_bindings(cur, self.workspace, before, after)
            cur.execute("UPDATE public.pr_library_assets SET sha256=%s WHERE id=%s", ('d' * 64, asset_id))
            self.assertFalse(library_bindings_current(cur, self.workspace, manifest))
            with self.assertRaises(AlphaError): validate_new_bindings(cur, self.workspace, before, after)

    def test_audio_removed_or_processing_again_stops_approval_and_worker_binding(self):
        from postriff_phase2.mastodon_media import audio_snapshot, library_bindings_current, validate_new_bindings
        with connection() as db, db.cursor() as cur:
            asset_id = self.audio(cur)
            manifest = {'platform': 'Mastodon', 'media': [{**audio_snapshot(cur, self.workspace, asset_id), 'rightsConfirmed': True}]}
            before = {'phase2': {'reviews': [{'id': 'review', 'manifest': manifest}], 'jobs': []}}
            after = {'phase2': {'reviews': before['phase2']['reviews'], 'jobs': [{'id': 'job', 'manifest': manifest}]}}
            cur.execute("UPDATE public.pr_library_assets SET processing_status='processing' WHERE id=%s", (asset_id,))
            with self.assertRaises(AlphaError): validate_new_bindings(cur, self.workspace, before, after)
            cur.execute("DELETE FROM public.pr_library_assets WHERE id=%s", (asset_id,))
            self.assertFalse(library_bindings_current(cur, self.workspace, manifest))

    def test_queue_checkpoint_is_committed_fenced_and_rechecks_write_authority(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        worker = PostgresWorker(connection, social=SimpleNamespace(oauth=self.service.oauth), clock=lambda: self.now)
        scopes = ['read:accounts', 'write:statuses', 'write:media']
        self.scoped_transport(scopes, lambda *_args, **_kw: None)
        with connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET scopes=%s WHERE workspace_id=%s AND connection_id=%s', (scopes, self.workspace, self.connection_id))
        grant = self.service.oauth.token_for_worker(self.workspace, self.connection_id)
        job = {'id': uuid.uuid4().hex, 'manifest': {'platform': 'Mastodon', 'media': [], 'channelId': self.connection_id, 'providerAccountId': self.account}, 'state': 'submitting',
               'leaseOwner': worker.worker_id, 'leaseId': uuid.uuid4().hex, 'leaseUntil': self.now + 45}
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['jobs'] = [job]
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
        claimed = {'workspaceId': self.workspace, 'job': job}
        progress = {'version': 3, 'stage': 'publish_attempted', 'attachments': [], 'retryCount': 0}
        with patch.object(worker, '_approved', return_value=False), self.assertRaises(AlphaError):
            worker.mastodon_checkpoint(claimed, progress, before_external=True)
        with patch.object(worker, '_approved', return_value=True):
            worker.mastodon_checkpoint(claimed, progress, before_external=True, authorization=grant)
        with connection() as db:
            stored = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][0]
            self.assertEqual(stored['progress']['stage'], 'publish_attempted')
        # A second worker cannot claim another worker's response or intention.
        other = PostgresWorker(connection, clock=lambda: self.now)
        with self.assertRaises(AlphaError): other.mastodon_checkpoint(claimed, progress)
        # Provider receipt can still be saved after authority changes: it records an
        # effect already attempted and does not authorize another external write.
        accepted = {**progress, 'stage': 'provider_accepted', 'reference': '123'}
        with patch.object(worker, '_approved', return_value=False): worker.mastodon_checkpoint(claimed, accepted)
        with connection() as db:
            stored = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][0]
            self.assertEqual(stored['providerReference'], '123')
        self.now += 50
        with self.assertRaises(AlphaError): worker.mastodon_checkpoint(claimed, accepted)

    def test_worker_refuses_revoke_rotation_and_scope_change_before_every_write_intent(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        self.health_channel()
        scopes = ['read:accounts', 'write:statuses', 'write:media']
        self.scoped_transport(scopes, lambda *_args, **_kw: None)
        worker = PostgresWorker(connection, social=SimpleNamespace(oauth=self.service.oauth), clock=lambda: self.now)
        manifest = {'platform': 'Mastodon', 'channelId': self.connection_id, 'providerAccountId': self.account,
            'payload': {'text': 'Root', 'threadParts': ['Child']}, 'media': [], 'publishOptions': {}}
        prior = {'version': 3, 'stage': 'thread_wait', 'attachments': [], 'retryCount': 0, 'reference': '123', 'threadReferences': ['123']}
        job = {'id': uuid.uuid4().hex, 'manifest': manifest, 'progress': prior, 'state': 'processing',
            'providerReference': '123', 'leaseOwner': worker.worker_id, 'leaseId': uuid.uuid4().hex, 'leaseUntil': self.now + 45}
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['jobs'] = [job]
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
            original = db.execute('SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()
        claimed = {'workspaceId': self.workspace, 'job': job}
        dispatched = []
        for stage in ('media_upload_attempted', 'publish_attempted', 'thread_publish_attempted'):
            for change in ('revoke', 'rotate', 'scopes'):
                with self.subTest(stage=stage, change=change):
                    with connection() as db:
                        db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s,scopes=%s,revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s', (*original, scopes, self.workspace, self.connection_id))
                    grant = self.service.oauth.token_for_worker(self.workspace, self.connection_id)
                    with connection() as db:
                        if change == 'revoke':
                            db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id))
                        elif change == 'rotate':
                            rotated, key = self.vault.encrypt(self.vault.decrypt(*original))
                            db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s WHERE workspace_id=%s AND connection_id=%s', (rotated, key, self.workspace, self.connection_id))
                        else:
                            db.execute('UPDATE public.pr_encrypted_credentials SET scopes=%s WHERE workspace_id=%s AND connection_id=%s', (['read:accounts'], self.workspace, self.connection_id))
                    with patch.object(worker, '_approved', return_value=True), self.assertRaises(AlphaError):
                        worker.mastodon_checkpoint(claimed, {**prior, 'stage': stage}, before_external=True, authorization=grant)
                        dispatched.append(stage)
                    with connection() as db:
                        saved = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][0]
                        self.assertEqual(saved['progress'], prior)
                        self.assertEqual(saved['providerReference'], '123')
                        self.assertFalse(saved.get('authorization'))
        self.assertEqual(dispatched, [])

    def test_disconnect_atomically_revokes_state_and_cannot_revoke_a_later_consent(self):
        self.health_channel()
        def reconnect_after_commit(*_args):
            with connection() as db:
                state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
                channel = next(c for c in state['phase2']['channels'] if c['id'] == self.connection_id)
                self.assertTrue(channel['revoked'])
                self.assertTrue(db.execute('SELECT revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()[0])
                # A new consent commits before the old disconnect finishes its cleanup.
                channel['revoked'] = False
                db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id))
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), self.workspace))
        with patch.object(self.service.repository, 'assert_fresh'), patch('postriff_phase2.growth.history_import.purge_after_disconnect', side_effect=reconnect_after_commit):
            self.service.oauth.disconnect(self.workspace, self.actor, self.connection_id)
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            self.assertFalse(next(c for c in state['phase2']['channels'] if c['id'] == self.connection_id)['revoked'])
            self.assertFalse(db.execute('SELECT revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()[0])

    def test_dispatch_gate_refuses_disconnect_in_flight_and_isolates_destinations(self):
        oauth = self.service.oauth
        with patch.object(self.service.repository, 'assert_fresh'):
            with oauth.mastodon_dispatch_fence(self.workspace, self.connection_id):
                with self.assertRaises(AlphaError) as busy:
                    oauth.disconnect(self.workspace, self.actor, self.connection_id)
                self.assertEqual(busy.exception.code, 'mastodon_dispatch_busy')
                with connection() as db:
                    self.assertFalse(db.execute('SELECT revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',
                                               (self.workspace, self.connection_id)).fetchone()[0])
                # The same channel label in another workspace and a second
                # destination in this workspace do not share the fence.
                with oauth.mastodon_dispatch_fence(self.foreign, self.connection_id):
                    with oauth.mastodon_dispatch_fence(self.workspace, self.connection_id + '-b'):
                        pass
            oauth.disconnect(self.workspace, self.actor, self.connection_id)
        with self.assertRaises(AlphaError):
            oauth.token_for_worker(self.workspace, self.connection_id)
        # Both a normal exit and an exception release the dedicated transaction.
        with self.assertRaises(RuntimeError):
            with oauth.mastodon_dispatch_fence(self.workspace, self.connection_id):
                raise RuntimeError('simulated interrupted dispatch')
        with oauth.mastodon_dispatch_fence(self.workspace, self.connection_id):
            pass

    def test_thread_checkpoint_keeps_accepted_ids_after_cancellation_and_blocks_next_write(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        worker = PostgresWorker(connection, clock=lambda: self.now)
        manifest = {'platform': 'Mastodon', 'providerAccountId': self.account, 'media': [],
                    'payload': {'text': 'Root', 'threadParts': ['Child']}, 'publishOptions': {}}
        job = {'id': uuid.uuid4().hex, 'manifest': manifest, 'state': 'processing',
               'leaseOwner': worker.worker_id, 'leaseId': uuid.uuid4().hex, 'leaseUntil': self.now + 45}
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['jobs'] = [job]
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
        claimed = {'workspaceId': self.workspace, 'job': job}
        progress = {'version': 3, 'stage': 'thread_wait', 'attachments': [], 'retryCount': 0,
                    'reference': '123', 'threadReferences': ['123']}
        worker.mastodon_checkpoint(claimed, progress)
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            state['phase2']['jobs'][0]['cancelRequested'] = True
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), self.workspace))
        with self.assertRaises(AlphaError):
            worker.mastodon_checkpoint(claimed, {**progress, 'stage': 'thread_publish_attempted'}, before_external=True)
        # Saving an already observed effect does not grant the canceled approval another write.
        accepted = {**progress, 'stage': 'provider_accepted', 'threadReferences': ['123', '124']}
        worker.mastodon_checkpoint(claimed, accepted)
        with connection() as db:
            persisted = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]['phase2']['jobs'][0]
            self.assertTrue(persisted['cancelRequested']); self.assertEqual(persisted['progress']['threadReferences'], ['123', '124'])
        other = PostgresWorker(connection, clock=lambda: self.now)
        with self.assertRaises(AlphaError): other.mastodon_checkpoint(claimed, accepted)

    def test_crashed_actions_and_retention_cleanup_never_send_again(self):
        from postriff_phase2.mastodon_management import maintain
        preview = self.preview()
        with connection() as db:
            db.execute("UPDATE public.pr_mastodon_actions SET status='running',updated_at=now()-interval '10 minutes' WHERE id=%s", (preview['actionId'],))
        before = len(self.posts)
        result = maintain(connection)
        self.assertEqual(result['interruptedActions'], 1)
        self.assertEqual(self.execute(preview)['state'], 'uncertain')
        self.assertEqual(len(self.posts), before)
        with connection() as db:
            db.execute("UPDATE public.pr_mastodon_actions SET created_at=now()-interval '8 days' WHERE id=%s", (preview['actionId'],))
            db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,metric,definition_version,value,unit,availability,observed_at) VALUES(%s,%s,'mastodon','123','likes','2026-09',3,'count','available',now()-interval '91 days')", (self.workspace, self.connection_id))
        result = maintain(connection)
        self.assertGreaterEqual(result['expiredActions'], 1)
        self.assertEqual(result['expiredMetrics'], 1)
        with self.assertRaises(AlphaError): self.execute(preview)
        self.assertEqual(len(self.posts), before)

    def execute(self, preview, **changes):
        return self.manager.execute(self.workspace, self.actor, self.connection_id, preview['actionId'],
                                    {'confirmed': True, 'digest': preview['digest'], **changes})

    def profile_image(self):
        raw = b'synthetic-decoded-image'
        asset = {'id': uuid.uuid4().hex, 'mime': 'image/png', 'processing': 'decoded', 'bytes': len(raw), 'hash': hashlib.sha256(raw).hexdigest()}
        asset['objectName'] = asset['id'] + '.png'
        with connection() as db:
            stored = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,)).fetchone()[0]
            stored['phase2']['assets'].append(asset)
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(stored), self.workspace))
            stored_grant = db.execute('SELECT access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id)).fetchone()
            envelope = json.loads(self.vault.decrypt(*stored_grant)); envelope['scope'] = ['read:accounts', 'write:accounts']
            cipher, key = self.vault.encrypt(json.dumps(envelope))
            db.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s,access_ciphertext=%s,key_id=%s WHERE workspace_id=%s AND connection_id=%s", (envelope['scope'], cipher, key, self.workspace, self.connection_id))
        self.service.assets = SimpleNamespace(storage=SimpleNamespace(get=lambda w, category, name: raw if w == self.workspace and category == 'media' and name == asset['objectName'] else b''))
        original = self.provider.transport
        self.profile_writes = []
        def transport(method, url, **kw):
            if '/api/v1/apps/verify_credentials' in url: return ok({'scopes': ['read:accounts', 'write:accounts']})
            if method == 'PATCH':
                self.profile_writes.append((url, kw))
                return ok({'id': '100'})
            return original(method, url, **kw)
        self.provider.transport = transport
        return asset

    def test_profile_image_exact_approval_uses_private_bytes_once(self):
        asset = self.profile_image()
        prepared = self.manager.preview(self.workspace, self.actor, self.connection_id,
            {'action': 'profile_update', 'profile': {'source': {'privacy': 'private'}}, 'profileMedia': {'avatar': {'assetId': asset['id'], 'rightsConfirmed': True}}})
        self.assertEqual(prepared['preview']['media']['avatar']['hash'], asset['hash'])
        self.assertNotIn('note', prepared['preview']['body'])
        approval = {'confirmed': True, 'digest': prepared['digest']}
        self.assertEqual(self.manager.execute(self.workspace, self.actor, self.connection_id, prepared['actionId'], approval)['state'], 'accepted')
        self.assertTrue(self.manager.execute(self.workspace, self.actor, self.connection_id, prepared['actionId'], approval)['replayed'])
        self.assertEqual(len(self.profile_writes), 1)
        self.assertIn(b'name="avatar"', self.profile_writes[0][1]['data'])
        self.assertIn(b'synthetic-decoded-image', self.profile_writes[0][1]['data'])
        self.assertIn(b'name="source[privacy]"', self.profile_writes[0][1]['data'])

    def test_changed_profile_image_approval_cannot_dispatch(self):
        asset = self.profile_image()
        prepared = self.manager.preview(self.workspace, self.actor, self.connection_id,
            {'action': 'profile_update', 'profileMedia': {'header': {'assetId': asset['id'], 'rightsConfirmed': True}}})
        self.service.assets.storage.get = lambda *_: b'replaced-image'
        result = self.manager.execute(self.workspace, self.actor, self.connection_id, prepared['actionId'], {'confirmed': True, 'digest': prepared['digest']})
        self.assertEqual(result['state'], 'uncertain'); self.assertEqual(self.profile_writes, [])

    def test_legitimate_history_and_central_analytics_preserve_instance_and_tenant(self):
        from postriff_phase2.mastodon_analytics import history
        from postriff_phase2.insights import record_observations
        with connection() as db, db.cursor() as cur:
            for workspace, connection_id, endpoint, value in (
                    (self.workspace, self.connection_id, 'https://mastodon.social/api/v1/statuses/123', 3),
                    (self.workspace, self.connection_id, 'https://mastodon.social/api/v1/statuses/123', 5),
                    (self.foreign, self.connection_id, 'https://mastodon.social/api/v1/statuses/123', 900),
                    (self.workspace, self.connection_id, 'https://mastodon.online/api/v1/statuses/123', 800)):
                record_observations(cur, workspace, connection_id, 'mastodon', '123', None,
                                    {'likes': value, 'reposts': 1, 'replies': 0}, endpoint, self.now - (60 if value == 3 else 0), read_offset='24h')
            report = history(cur, self.workspace, self.connection_id, 'mastodon.social', ['123'])
            self.assertEqual([r['value'] for r in report['readings'] if r['metric'] == 'likes'], [3, 5])
            self.assertEqual(next(r['change'] for r in report['trends'] if r['metric'] == 'likes'), 2)
            self.assertEqual(history(cur, self.workspace, self.connection_id, 'mastodon.social', [])['readings'], [])
        central = self.service.analytics(self.workspace, self.actor)
        # The shared summary shows legitimate stored Mastodon counts with unavailable reach/rates.
        post = next(p for p in central['posts'] if p['provider'] == 'mastodon')
        self.assertEqual(post['metrics']['likes']['value'], 5); self.assertEqual(post['metrics']['likes']['nativeName'], 'favourites_count')
        self.assertNotIn('reach', post['metrics']); self.assertEqual(post['rates']['likesPerView']['value'], None)

    def test_cross_tenant_denial_sends_no_provider_request(self):
        before = len(self.calls)
        for workspace, actor in ((self.workspace, self.other), (self.foreign, self.other)):
            with self.assertRaises(AlphaError):
                self.manager.read(workspace, actor, self.connection_id, 'profile')
        self.assertEqual(len(self.calls), before)

    def test_approval_digest_and_expiry(self):
        preview = self.preview()
        self.assertEqual(self.posts, [])
        with self.assertRaises(AlphaError): self.execute(preview, digest='0' * 64)
        with self.assertRaises(AlphaError): self.execute(preview, confirmed=False)
        self.now += 601
        with self.assertRaises(AlphaError): self.execute(preview)
        self.assertEqual(self.posts, [])

    def test_repeated_confirmation_never_sends_twice(self):
        preview = self.preview()
        self.assertEqual(self.execute(preview)['state'], 'accepted')
        self.assertTrue(self.execute(preview)['replayed'])
        self.assertEqual(len(self.posts), 1)

    def test_simultaneous_confirmation_has_one_effect(self):
        preview = self.preview()
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: self.execute(preview), range(8)))
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(sum(not r.get('replayed', False) for r in results), 1)

    def test_revoked_connection_stops_before_dispatch(self):
        preview = self.preview()
        with connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (self.workspace, self.connection_id))
        with self.assertRaises(AlphaError): self.execute(preview)
        self.assertEqual(self.posts, [])

    def test_application_cache_is_encrypted_and_shared_by_binding(self):
        cache = self.provider.application_cache
        first = cache('mastodon.social', 'https://rafii.io/api/oauth/mastodon/callback', ['read:accounts'])
        second = cache('mastodon.social', 'https://rafii.io/api/oauth/mastodon/callback', ['read:accounts'])
        self.assertEqual(first, second)
        self.assertEqual(len([c for c in self.calls if c[0] == 'POST' and c[1].endswith('/api/v1/apps')]), 1)
        with connection() as db:
            row = db.execute('SELECT credentials_ciphertext FROM public.pr_mastodon_applications').fetchone()
            self.assertNotIn('fixture-secret', row[0])

    def test_browser_roles_cannot_read_credentials_or_action_bodies(self):
        self.preview()
        for role in ('anon', 'authenticated'):
            for table in ('pr_mastodon_applications', 'pr_mastodon_actions'):
                with connection() as db:
                    db.execute('SET LOCAL ROLE ' + role)
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege): db.execute('SELECT * FROM public.' + table)


if __name__ == '__main__': unittest.main()
