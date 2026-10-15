"""Real disposable PostgreSQL; synthetic members/assets, no storage/provider calls."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.library_metadata import LibraryMetadataChanges, MAX_ASSETS, PREVIEW_SECONDS, UNDO_SECONDS

ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class LibraryMetadataPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = (ROOT / 'migrations/postriff/112_library_metadata_changes.sql').read_text()
        with connection() as db:
            db.execute(cls.migration)
            db.execute(cls.migration)  # additive/reapply-safe, no reset of versions or receipts

    def setUp(self):
        self.now = time.time()
        self.actor = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users VALUES(%s)', (self.actor,))
        self.service = HostedWorkspaceService(connection, lambda token: str(uuid.UUID(token)), clock=lambda: self.now)
        self.w = self.service.bootstrap(self.actor, 'studio')['workspaceId']
        self.library = self.service.library
        self.changes = LibraryMetadataChanges(self.library)
        self.asset = self.new_asset()

    def new_asset(self, w=None, title='Original title', tags=None):
        ident = uuid.uuid4().hex
        with connection() as db:
            db.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,title_source,tags,kind,mime,extension,bytes,bucket,object_name,processing_status,provenance) VALUES(%s,%s,%s,'original.txt',%s,'generated',%s,'document','text/plain','txt',1,'test-library',%s,'ready',%s::jsonb)",
                       (ident, w or self.w, self.actor, title, tags or ['inherited'], ident + '.txt', json.dumps({'private': 'FILE_CONTENT_MUST_NOT_EGRESS'})))
            db.execute("INSERT INTO public.pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,0,'FILE_CONTENT_MUST_NOT_EGRESS')", (ident, w or self.w))
        return ident

    def preview(self, patch, asset=None):
        return self.changes.preview(self.w, self.actor, {'changes': [{'assetId': asset or self.asset, 'changes': patch}]})

    def apply(self, receipt):
        return self.changes.apply(self.w, self.actor, {'receiptId': receipt['receiptId']})

    def undo(self, receipt):
        return self.changes.undo(self.w, self.actor, {'receiptId': receipt['receiptId']})

    def state(self, asset=None):
        with connection() as db:
            return db.execute('SELECT display_title,title_source,tags FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s', (self.w, asset or self.asset)).fetchone()

    def assert_error(self, status, function, *args):
        with self.assertRaises(AlphaError) as caught:
            function(*args)
        self.assertEqual(caught.exception.status, status, str(caught.exception))
        return caught.exception

    def test_exact_preview_apply_verified_undo_and_no_content(self):
        collection = self.library.collections(self.w, self.actor, {'name': 'Lessons'})['collections'][0]['id']
        receipt = self.preview({'title': 'Reviewed title', 'tags': ['reviewed'], 'collections': [collection]})
        self.assertEqual(self.state(), ('Original title', 'generated', ['inherited']))
        entry = receipt['entries'][0]
        self.assertEqual(entry['current'], {'title': 'Original title', 'tags': ['inherited'], 'collections': []})
        self.assertEqual(entry['proposed'], {'title': 'Reviewed title', 'tags': ['reviewed'], 'collections': [{'id': collection, 'name': 'Lessons'}]})
        self.assertEqual(receipt['affectedResources'], [{'kind': 'library_asset', 'id': self.asset}, {'kind': 'library_collection', 'id': collection}])
        applied = self.apply(receipt)
        self.assertTrue(applied['canUndo'])
        self.assertEqual(self.state(), ('Reviewed title', 'user', ['reviewed']))
        with connection() as db:
            revision = db.execute('SELECT revision FROM public.pr_library_metadata_versions WHERE workspace_id=%s AND asset_key=%s', (self.w, self.asset)).fetchone()
            persisted = db.execute('SELECT payload::text FROM public.pr_library_metadata_changes WHERE id=%s', (receipt['receiptId'],)).fetchone()[0]
        self.assertNotIn('FILE_CONTENT_MUST_NOT_EGRESS', persisted + json.dumps(applied))
        self.assertEqual(self.apply(receipt)['status'], 'applied')
        with connection() as db:
            self.assertEqual(db.execute('SELECT revision FROM public.pr_library_metadata_versions WHERE workspace_id=%s AND asset_key=%s', (self.w, self.asset)).fetchone(), revision)
        self.assertEqual(self.undo(receipt)['status'], 'undone')
        self.assertEqual(self.state(), ('Original title', 'generated', ['inherited']))
        self.assertEqual(self.undo(receipt)['status'], 'undone')
        self.assertEqual(self.apply(receipt)['status'], 'undone')
        with connection() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=%s', (self.w, self.asset)).fetchone())
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind IN ('library.metadata_applied','library.metadata_undone')", (self.w,)).fetchone()[0], 2)

    def test_collection_only_preserves_inherited_title_tags_and_undo(self):
        collection = self.library.collections(self.w, self.actor, {'name': 'Archive'})['collections'][0]['id']
        receipt = self.preview({'collections': [collection]})
        self.apply(receipt)
        self.assertEqual(self.state(), ('Original title', 'generated', ['inherited']))
        self.undo(receipt)
        self.assertEqual(self.state(), ('Original title', 'generated', ['inherited']))

    def test_conflict_rolls_back_entire_batch(self):
        second = self.new_asset(title='Second title')
        receipt = self.changes.preview(self.w, self.actor, {'changes': [{'assetId': i, 'changes': {'tags': ['batch']}} for i in (self.asset, second)]})
        self.library.metadata(self.w, self.actor, second, {'title': 'Other edit'})
        self.assert_error(409, self.apply, receipt)
        self.assertEqual(self.state(), ('Original title', 'generated', ['inherited']))
        self.assertEqual(self.state(second)[0], 'Other edit')

    def test_native_aba_and_collection_aba_reject_stale_preview(self):
        receipt = self.preview({'title': 'Previewed'})
        with connection() as db:
            db.execute("UPDATE public.pr_library_assets SET display_title='Other' WHERE id=%s", (self.asset,))
            db.execute("UPDATE public.pr_library_assets SET display_title='Original title' WHERE id=%s", (self.asset,))
        self.assert_error(409, self.apply, receipt)
        group = self.library.collections(self.w, self.actor, {'name': 'Transient'})['collections'][0]['id']
        receipt = self.preview({'title': 'Previewed'})
        with connection() as db:
            db.execute('INSERT INTO public.pr_library_collection_items VALUES(%s,%s,%s)', (self.w, group, self.asset))
            db.execute('DELETE FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=%s', (self.w, self.asset))
        self.assert_error(409, self.apply, receipt)

    def test_undo_after_drift_cannot_overwrite_later_edit(self):
        receipt = self.preview({'title': 'Applied title'})
        self.apply(receipt)
        self.library.metadata(self.w, self.actor, self.asset, {'title': 'Later edit'})
        self.assert_error(409, self.undo, receipt)
        self.assertFalse(self.apply(receipt)['canUndo'])
        self.assertEqual(self.state()[0], 'Later edit')

    def test_revoke_blocks_apply_undo_and_replay(self):
        prepared = self.preview({'title': 'First preview'})
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (self.w, self.actor))
        self.assert_error(403, self.apply, prepared)
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s", (self.w, self.actor))
        self.apply(prepared)
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (self.w, self.actor))
        self.assert_error(403, self.undo, prepared)
        self.assert_error(403, self.apply, prepared)
        self.assertEqual(self.state()[0], 'First preview')

    def test_foreign_workspace_and_different_actor_receipts_refused(self):
        stranger = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users VALUES(%s)', (stranger,))
        foreign = self.service.bootstrap(stranger, 'studio')['workspaceId']
        receipt = self.preview({'title': 'Protected'})
        self.assert_error(404, self.changes.preview, foreign, stranger, {'changes': [{'assetId': self.asset, 'changes': {'title': 'Bad'}}]})
        self.assert_error(404, self.changes.apply, foreign, stranger, {'receiptId': receipt['receiptId']})
        with connection() as db:
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.w, stranger))
        self.assert_error(404, self.changes.apply, self.w, stranger, {'receiptId': receipt['receiptId']})

    def test_selection_bounds_duplicates_and_untrusted_extra_payload(self):
        item = {'assetId': self.asset, 'changes': {'title': 'Bounded'}}
        for body in ({'changes': []}, {'changes': [item] * (MAX_ASSETS + 1)}, {'changes': [item, item]}, {'changes': [item], 'before': {}}, {'changes': [{'assetId': self.asset, 'changes': {'text': 'never'}}]}):
            self.assert_error(400, self.changes.preview, self.w, self.actor, body)
        self.assert_error(400, self.changes.apply, self.w, self.actor, {'receiptId': uuid.uuid4().hex, 'changes': {}})

    def test_large_metadata_preview_is_bounded_without_persisting_partial_change(self):
        ids = [self.asset] + [self.new_asset() for _ in range(MAX_ASSETS - 1)]
        body = {'changes': [{'assetId': i, 'changes': {'tags': [str(n) + '界' * 38 for n in range(30)]}} for i in ids]}
        self.assert_error(413, self.changes.preview, self.w, self.actor, body)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_library_metadata_changes WHERE workspace_id=%s', (self.w,)).fetchone()[0], 0)

    def test_collection_deleted_before_apply_or_required_for_undo(self):
        group = self.library.collections(self.w, self.actor, {'name': 'Missing'})['collections'][0]['id']
        receipt = self.preview({'collections': [group]})
        self.library.collections(self.w, self.actor, collection_id=group, delete=True)
        self.assert_error(409, self.apply, receipt)
        group = self.library.collections(self.w, self.actor, {'name': 'Original group'})['collections'][0]['id']
        self.library.metadata(self.w, self.actor, self.asset, {'collections': [group], 'tags': ['inherited']})
        receipt = self.preview({'collections': []})
        self.apply(receipt)
        self.library.collections(self.w, self.actor, collection_id=group, delete=True)
        self.assert_error(409, self.undo, receipt)

    def test_expiration_and_missing_asset_fail_closed(self):
        self.now = int(self.now) + .1234567  # exceeds PostgreSQL microsecond precision
        receipt = self.preview({'title': 'Expired'})
        with connection() as db:
            persisted = db.execute('SELECT extract(epoch from expires_at) FROM public.pr_library_metadata_changes WHERE id=%s', (receipt['receiptId'],)).fetchone()[0]
        self.assertEqual(receipt['expiresAt'], persisted)
        self.assertLessEqual(receipt['expiresAt'], self.now + PREVIEW_SECONDS)
        self.now = receipt['expiresAt']
        self.assert_error(409, self.apply, receipt)
        receipt = self.preview({'title': 'Undo expiry'})
        self.now += .1234567
        applied = self.apply(receipt)
        with connection() as db:
            persisted = db.execute('SELECT extract(epoch from undo_expires_at) FROM public.pr_library_metadata_changes WHERE id=%s', (receipt['receiptId'],)).fetchone()[0]
        self.assertEqual(applied['undoExpiresAt'], persisted)
        self.assertLessEqual(applied['undoExpiresAt'], self.now + UNDO_SECONDS)
        self.now = applied['undoExpiresAt']
        self.assert_error(409, self.undo, receipt)
        receipt = self.preview({'title': 'Deleted'})
        with connection() as db:
            db.execute('DELETE FROM public.pr_library_assets WHERE id=%s', (self.asset,))
        self.assert_error(404, self.apply, receipt)

    def test_legacy_media_and_original_label_provenance(self):
        legacy = uuid.uuid4().hex
        with connection() as db:
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.w,)).fetchone()[0]
            state.setdefault('phase2', {}).setdefault('assets', []).append({'id': legacy, 'mime': 'image/jpeg', 'displayTitle': 'Legacy image', 'aiTags': ['camera']})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), self.w))
        receipt = self.preview({'title': 'Label override', 'tags': ['new']}, legacy)
        self.assertEqual(receipt['entries'][0]['current']['tags'], ['camera'])
        self.apply(receipt)
        self.undo(receipt)
        with connection() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=%s', (self.w, legacy)).fetchone())

    def prepared(self, receipt, actor=None):
        with self.service.repository.transaction(actor or self.actor, self.w) as (cur, _, principal):
            return self.changes.prepared_in(cur, self.w, principal, receipt['receiptId'])

    def test_task_engine_prepared_preview_rechecks_exact_metadata_and_collections(self):
        group = self.library.collections(self.w, self.actor, {'name': 'Before'})['collections'][0]['id']
        receipt = self.preview({'title': 'Approval title', 'collections': [group]})
        self.assertEqual(self.prepared(receipt), receipt)
        self.assertEqual(self.state()[0], 'Original title')
        with connection() as db:
            db.execute('UPDATE public.pr_library_collections SET name=%s WHERE id=%s', ('Renamed', group))
        self.assert_error(409, self.prepared, receipt)
        receipt = self.preview({'title': 'Approval title'})
        self.library.metadata(self.w, self.actor, self.asset, {'tags': ['later']})
        self.assert_error(409, self.prepared, receipt)
        receipt = self.preview({'title': 'Approval title'})
        self.apply(receipt)
        self.assert_error(409, self.prepared, receipt)

    def test_task_engine_prepared_preview_requires_creator_role_and_unexpired_receipt(self):
        receipt = self.preview({'title': 'Approval title'})
        stranger = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users VALUES(%s)', (stranger,))
        self.service.bootstrap(stranger, 'studio')
        with connection() as db:
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.w, stranger))
        self.assert_error(404, self.prepared, receipt, stranger)
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (self.w, self.actor))
        self.assert_error(403, self.prepared, receipt)
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s", (self.w, self.actor))
        self.now = receipt['expiresAt']
        self.assert_error(409, self.prepared, receipt)

    def test_task_engine_cursor_inverse_digest_and_idempotency(self):
        receipt = self.preview({'tags': ['engine']})
        self.apply(receipt)
        with self.service.repository.transaction(self.actor, self.w) as (cur, _, principal):
            witness = self.changes.current_digest(cur, self.w, receipt['receiptId'])
            result = self.changes.undo_in(cur, self.w, principal, receipt['receiptId'], witness, 'task-step-1')
            self.assertEqual(result['status'], 'undone')
        with self.service.repository.transaction(self.actor, self.w) as (cur, _, principal):
            self.assertEqual(self.changes.undo_in(cur, self.w, principal, receipt['receiptId'], witness, 'task-step-1')['status'], 'undone')
        with self.service.repository.transaction(self.actor, self.w) as (cur, _, principal):
            self.assert_error(409, self.changes.undo_in, cur, self.w, principal, receipt['receiptId'], witness, 'different-step')

    def test_history_is_bounded_creator_only_and_reopen_checks_current_version(self):
        receipts = []
        for n in range(11):
            receipt = self.preview({'title': f'History title {n}'})
            self.apply(receipt)
            receipts.append(receipt)
        history = self.changes.history(self.w, self.actor)['changes']
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0]['receiptId'], receipts[-1]['receiptId'])
        self.assertNotIn(receipts[0]['receiptId'], [item['receiptId'] for item in history])
        self.assertTrue(self.changes.read(self.w, self.actor, receipts[-1]['receiptId'])['canUndo'])
        self.assertFalse(self.changes.read(self.w, self.actor, receipts[0]['receiptId'])['canUndo'])
        stranger = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users VALUES(%s)', (stranger,))
        self.service.bootstrap(stranger, 'studio')
        with connection() as db:
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (self.w, stranger))
        self.assertEqual(self.changes.history(self.w, stranger)['changes'], [])
        self.assert_error(404, self.changes.read, self.w, stranger, receipts[-1]['receiptId'])
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (self.w, self.actor))
        self.assert_error(403, self.changes.read, self.w, self.actor, receipts[-1]['receiptId'])
        self.assert_error(403, self.changes.history, self.w, self.actor)

    def test_rls_and_missing_schema_preserve_native_api(self):
        for role in ('anon', 'authenticated'):
            with connection() as db:
                for table in ('pr_library_metadata_versions', 'pr_library_metadata_changes'):
                    with db.transaction():
                        db.execute(f'SET LOCAL ROLE {role}')
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            with db.transaction():
                                db.execute(f'SELECT * FROM public.{table}')
        with connection() as db:
            for table in ('pr_library_metadata_versions', 'pr_library_metadata_changes'):
                self.assertEqual(db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', ('public.' + table,)).fetchone(), (True, True))
            db.execute('ALTER TABLE public.pr_library_metadata_changes RENAME TO pr_library_metadata_changes_temporarily_absent')
        try:
            self.assertEqual(self.assert_error(503, self.preview, {'title': 'Needs schema'}).code, 'library_metadata_unavailable')
            self.library.metadata(self.w, self.actor, self.asset, {'title': 'Native still works'})
            self.assertEqual(self.state()[0], 'Native still works')
        finally:
            with connection() as db:
                db.execute('ALTER TABLE public.pr_library_metadata_changes_temporarily_absent RENAME TO pr_library_metadata_changes')


if __name__ == '__main__':
    unittest.main(verbosity=2)
