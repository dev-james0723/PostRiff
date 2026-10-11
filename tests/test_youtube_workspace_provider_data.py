"""Synthetic runtime-output deletion/fencing contracts; no provider I/O."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.youtube import workspace_provider_data as private
from postriff_phase2.youtube.journal import UploadJournal, purge_expired_data
from postriff_phase2.youtube.uploads import UploadEngine

NOW = 1800000000
WORKSPACE, CONNECTION, GENERATION = 'workspace-one', 'connection-one', 'generation-one'
CHANNEL, VIDEO = 'UC' + 'a' * 22, 'abcdefghijk'


def job(platform='YouTube'):
    manifest = {'workspaceId': WORKSPACE, 'channelId': CONNECTION, 'providerAccountId': CHANNEL,
                'platform': platform, 'actor': 'owner', 'idempotencyKey': 'operation-one',
                'payload': {'text': 'My original Library description ' + VIDEO},
                'media': [{'id': 'user-video', 'hash': 'user-original-hash'}],
                'publishOptions': {'title': 'My title', 'playlistIds': ['user-chosen-list']}}
    return {'id': 'job-one', 'manifest': manifest, 'approvalDigest': digest(manifest), 'approvedBy': 'owner',
            'approvedAt': NOW, 'state': 'processing', 'leaseOwner': 'worker', 'leaseId': 'lease-one',
            'leaseUntil': NOW + 45, 'events': [{'state': 'approved', 'message': 'Exact approval recorded'}],
            'attempts': [{'number': 1, 'startedAt': NOW}], 'checks': 1}


def result():
    return {'state': 'verified', 'confirmed': 'Synthetic exact API readback', 'reference': VIDEO,
            'url': 'https://www.youtube.com/watch?v=' + VIDEO, 'verification': 'provider_lookup',
            'progress': {'version': 2, 'stage': 'published', 'videoId': VIDEO, 'bytesSent': 6, 'totalBytes': 6,
                         'steps': {'caption': {'source': 'YouTube Data API', 'resourceId': 'caption-provider-id',
                                              'result': {'id': 'caption-provider-id', 'snippet': {'channelId': CHANNEL}}}}}}


class Database:
    """Small SQL boundary double; real transaction ordering is covered in PostgreSQL."""
    def __init__(self, saved=None):
        saved = saved or job()
        self.state = {'phase2': {'channels': [], 'reviews': [], 'jobs': [copy.deepcopy(saved)]},
                      'userNotes': 'Keep ' + VIDEO, 'variants': [{'text': 'My draft ' + VIDEO}]}
        self.generation, self.member, self.journal = GENERATION, ('owner', True), None
        self.rowcount, self.sql, self.rows = 1, [], None

    @contextmanager
    def connection(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        if sql.startswith('SELECT revision,state'):
            self.rows = (1, copy.deepcopy(self.state))
        elif sql.startswith('SELECT authorization_generation'):
            self.rows = (self.generation,) if self.generation else None
        elif sql.startswith('SELECT m.role,m.can_publish'):
            self.rows = self.member
        elif sql.startswith('SELECT state FROM public.pr_youtube_uploads'):
            self.rows = (copy.deepcopy(self.journal),) if self.journal is not None else None
        elif sql.startswith('SELECT id FROM public.pr_workspaces'):
            self.rows = (WORKSPACE,)
        elif sql.startswith('SELECT pg_') or sql.startswith('SELECT EXISTS'):
            self.rows = (True,)
        elif sql.startswith('SELECT to_regclass'):
            self.rows = ('pr_worker_tenants',)
        elif sql.startswith('SELECT w.id::text,w.revision,w.state'):
            self.rows = [(WORKSPACE, 1, copy.deepcopy(self.state))]
        elif sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.state = json.loads(params[0])
        elif sql.startswith('INSERT INTO public.pr_youtube_uploads'):
            self.journal = json.loads(params[-1])
        elif not sql.startswith('INSERT INTO public.pr_worker_tenants'):
            raise AssertionError('Unexpected SQL: ' + sql)

    def fetchone(self):
        return self.rows

    def fetchall(self):
        return self.rows


def worker(db):
    value = PostgresWorker(db.connection, social=SimpleNamespace(youtube=object()), clock=lambda: NOW, worker_id='worker', on_verified=Mock())
    value.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda _: None))
    return value


def claimed(saved=None):
    return {'workspaceId': WORKSPACE, 'job': copy.deepcopy(saved or job()), 'reconciliation': True,
            'youtubeAuthorizationGeneration': GENERATION}


class WorkspaceProviderDataTests(unittest.TestCase):
    def test_runtime_outputs_are_removed_without_rewriting_approval_or_user_content(self):
        saved = job()
        saved.update(providerReference=VIDEO, url=result()['url'], progress=result()['progress'],
                     verification={'method': 'provider_lookup'}, insights={'raw': CHANNEL}, comments={'id': VIDEO})
        before = copy.deepcopy(saved)
        private.scrub_job(saved, 'youtube_expired_data_removed', NOW)
        for key in ('manifest', 'approvalDigest', 'approvedBy', 'approvedAt', 'attempts'):
            self.assertEqual(saved[key], before[key])
        self.assertEqual(digest(saved['manifest']), before['approvalDigest'])
        self.assertNotIn('caption-provider-id', json.dumps(saved))
        self.assertNotIn('providerReference', saved)
        self.assertNotIn('url', saved)
        self.assertEqual(saved['progress'], {'version': 2, 'stage': 'held', 'errorCategory': 'youtube_expired_data_removed'})
        self.assertEqual((saved['state'], saved['leaseOwner'], saved['leaseUntil']), ('held', None, 0))
        self.assertIn('not canceled', saved['nextAction'])
        self.assertIn(VIDEO, saved['manifest']['payload']['text'])
        private.scrub_job(saved, 'youtube_expired_data_removed', NOW + 1)
        self.assertEqual(len(saved['events']), 2)

    def test_only_deterministic_youtube_output_slots_are_legacy_candidates(self):
        old = job()
        old['approvedAt'] = NOW - 31 * 86400
        self.assertFalse(private._expired_job(old, NOW))
        old['providerReference'] = VIDEO
        self.assertTrue(private._expired_job(old, NOW))
        old['manifest']['platform'] = 'LinkedIn'
        self.assertFalse(private._expired_job(old, NOW))
        self.assertFalse(private.youtube_job(job(), 'another-connection'))
        for malformed in (None, 'not-a-source', [], {'expiresAt': 'recent'}):
            saved = job()
            saved.update(providerReference=VIDEO)
            saved[private.KEY] = malformed
            self.assertTrue(private._expired_job(saved, NOW))

    def test_cached_receipts_cannot_restart_the_retention_clock(self):
        saved = job()
        first = private.source(WORKSPACE, saved, GENERATION, NOW)
        saved[private.KEY] = first
        later = private.source(WORKSPACE, saved, GENERATION, NOW + 86400)
        self.assertEqual(first, later)
        saved.pop(private.KEY)
        saved.update(providerReference=VIDEO, approvedAt=NOW - 20 * 86400)
        legacy = private.source(WORKSPACE, saved, GENERATION, NOW)
        self.assertEqual(legacy['expiresAt'], NOW + 10 * 86400)

    def test_claim_captures_database_generation_for_native_read_only_work(self):
        saved = job()
        saved.update(leaseUntil=0, progress={'version': 2, 'stage': 'native_scheduled'})
        db = Database(saved)
        selection = worker(db).claim(youtube_only=True)
        self.assertEqual(selection['youtubeAuthorizationGeneration'], GENERATION)
        self.assertNotIn('youtubeForward', selection)
        self.assertEqual(selection['job']['manifest'], saved['manifest'])

    @patch('postriff_phase2.product_events.publish_outcome')
    @patch('postriff_phase2.hosted_worker.record_published')
    def test_current_completion_stamps_exact_source_and_runs_hooks(self, learning, outcome):
        db, selected = Database(), claimed()
        current = worker(db)
        self.assertTrue(current.complete(selected, result()))
        saved = db.state['phase2']['jobs'][0]
        self.assertEqual(saved['providerReference'], VIDEO)
        self.assertEqual(saved[private.KEY], private.source(WORKSPACE, job(), GENERATION, NOW))
        self.assertEqual(saved['approvalDigest'], selected['job']['approvalDigest'])
        current.on_verified.assert_called_once()
        learning.assert_called_once()
        outcome.assert_called_once()

    @patch('postriff_phase2.product_events.publish_outcome')
    @patch('postriff_phase2.hosted_worker.record_published')
    def test_revoked_replaced_actor_and_expired_sources_never_run_stale_hooks(self, learning, outcome):
        for change in ('revoked', 'replacement', 'actor', 'authority', 'expiry', 'missing-generation'):
            with self.subTest(change=change):
                db, selection = Database(), claimed()
                saved = db.state['phase2']['jobs'][0]
                if change == 'revoked': db.generation = None
                if change == 'replacement': db.generation = 'new-consent'
                if change == 'actor': saved['approvedBy'] = 'somebody-else'
                if change == 'authority': db.member = ('viewer', False)
                if change == 'expiry': saved[private.KEY] = private.source(WORKSPACE, saved, GENERATION, NOW - 31 * 86400)
                if change == 'missing-generation': selection.pop('youtubeAuthorizationGeneration')
                current = worker(db)
                self.assertFalse(current.complete(selection, result()))
                saved = db.state['phase2']['jobs'][0]
                self.assertTrue(saved[private.REMOVED])
                self.assertNotIn('caption-provider-id', json.dumps(saved))
                self.assertEqual(saved['manifest'], selection['job']['manifest'])
                current.on_verified.assert_not_called()
        learning.assert_not_called()
        outcome.assert_not_called()

    @patch('postriff_phase2.product_events.publish_outcome')
    @patch('postriff_phase2.hosted_worker.record_published')
    def test_non_youtube_completion_does_not_acquire_credentials_or_redact(self, _learning, _outcome):
        saved = job('LinkedIn')
        db, selection = Database(saved), claimed(saved)
        selection.pop('youtubeAuthorizationGeneration')
        receipt = {'state': 'verified', 'confirmed': 'Synthetic LinkedIn receipt', 'reference': 'linked-in-post', 'verification': 'provider_lookup'}
        self.assertTrue(worker(db).complete(selection, receipt))
        self.assertEqual(db.state['phase2']['jobs'][0]['providerReference'], 'linked-in-post')
        self.assertFalse(any('pr_encrypted_credentials' in sql for sql, _ in db.sql))
        self.assertNotIn(private.KEY, db.state['phase2']['jobs'][0])

    @patch('postriff_phase2.youtube.journal.time.time', return_value=NOW)
    def test_journal_stamps_once_and_tombstone_blocks_stale_save_and_new_consent(self, _clock):
        db, key = Database(), (WORKSPACE, CONNECTION, 'operation-one')
        journal = UploadJournal(db.connection, None)
        original = {'manifestDigest': 'immutable-digest', 'stage': 'uploading', 'sessionCiphertext': 'synthetic-session',
                    'options': {'title': 'User title'}, 'steps': {'raw': CHANNEL}}
        with journal.lock(key):
            journal.save(key, original)
            self.assertEqual(db.journal[private.INGESTED], NOW)
            journal.save(key, {**original, private.INGESTED: NOW + 86400})
            self.assertEqual(db.journal[private.INGESTED], NOW)
            db.journal = private.tombstone(db.journal, 'youtube_expired_data_removed', NOW)
            with self.assertRaises(AlphaError) as error:
                journal.save(key, original)
            self.assertEqual(error.exception.code, 'youtube_data_removed')
            with self.assertRaises(AlphaError): journal.assert_current(key)
        self.assertEqual(set(db.journal), {'version', 'stage', private.REMOVED, 'dataRemovalReason', 'removedAt', 'manifestDigest'})
        for generation in (GENERATION, 'replacement-consent'):
            db.generation = generation
            api = Mock(side_effect=AssertionError('A tombstone must never call Google.'))
            engine = UploadEngine(journal, api, Mock())
            with self.assertRaises(AlphaError) as error:
                engine.step(job()['manifest'])
            self.assertEqual(error.exception.code, 'youtube_data_removed')
            api.assert_not_called()

    def test_workspace_scan_remains_cron_only(self):
        # The additional privacy-erasure cron scan also sees no candidates.
        cur = SimpleNamespace(execute=Mock(), fetchall=Mock(return_value=[]))
        with patch('postriff_phase2.youtube.workspace_provider_data.purge_expired') as sweep, patch('postriff_phase2.youtube.agent_context.purge_expired'):
            purge_expired_data(cur)
            sweep.assert_not_called()
            cur.fetchall.assert_not_called()
            purge_expired_data(cur, agent_context=True)
            sweep.assert_called_once_with(cur)
            cur.fetchall.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
