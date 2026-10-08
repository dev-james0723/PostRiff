"""Synthetic authorization-generation contracts; never Google acceptance."""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube.journal import UploadJournal

KEY = ('workspace', 'connection', 'operation')


class Cursor:
    def __init__(self, repository):
        self.repository, self.result = repository, None
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        if 'pg_try_advisory_lock' in statement:
            self.result = (True,)
        elif 'pg_attribute' in statement:
            self.result = (self.repository.schema,)
        elif 'SELECT id FROM public.pr_workspaces' in statement:
            self.result = ('workspace',) if self.repository.workspace_present else None
        elif 'SELECT authorization_generation::text' in statement:
            self.result = None if self.repository.revoked else (self.repository.generation,)
        elif 'INSERT INTO public.pr_youtube_uploads' in statement:
            self.repository.writes.append(parameters)
        elif 'pg_advisory_unlock' in statement:
            self.result = (True,)
        else:
            raise AssertionError(statement)

    def fetchone(self):
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Repository:
    def __init__(self):
        self.schema, self.revoked, self.generation = True, False, 'generation-one'
        self.workspace_present = True
        self.opened, self.cursors, self.writes = 0, [], []

    @contextmanager
    def connection(self):
        self.opened += 1
        cursor = Cursor(self)
        self.cursors.append(cursor)
        yield SimpleNamespace(cursor=lambda: cursor)


class JournalFenceTests(unittest.TestCase):
    def setUp(self):
        self.repository = Repository()
        self.journal = UploadJournal(self.repository.connection, None)

    def test_missing_generation_schema_holds_before_operation(self):
        self.repository.schema = False
        with self.assertRaises(AlphaError) as stopped:
            with self.journal.lock(KEY):
                self.fail('The operation must not start without migration 098.')
        self.assertEqual(stopped.exception.code, 'youtube_authorization_schema')
        self.assertFalse(self.repository.writes)

    def test_save_locks_workspace_before_credential_and_child_insert(self):
        with self.journal.lock(KEY):
            self.journal.assert_current(KEY)
            self.journal.save(KEY, {'stage': 'uploading'})
        writer = self.repository.cursors[-1]
        self.assertEqual(len(self.repository.writes), 1)
        self.assertEqual(len(writer.statements), 3)
        self.assertIn('public.pr_workspaces', writer.statements[0][0])
        self.assertIn('FOR KEY SHARE', writer.statements[0][0])
        self.assertEqual(writer.statements[0][1], KEY[:1])
        self.assertIn('public.pr_encrypted_credentials', writer.statements[1][0])
        self.assertIn('FOR NO KEY UPDATE', writer.statements[1][0])
        self.assertEqual(writer.statements[1][1], KEY[:2])
        self.assertIn('INSERT INTO public.pr_youtube_uploads', writer.statements[2][0])

    def test_disconnect_or_new_consent_cannot_recreate_purged_state(self):
        for changed in (False, True):
            with self.subTest(new_consent=changed):
                repository = Repository()
                journal = UploadJournal(repository.connection, None)
                with journal.lock(KEY):
                    repository.revoked = not changed
                    repository.generation = 'generation-two'
                    for operation in (lambda: journal.assert_current(KEY), lambda: journal.save(KEY, {'stage': 'uploading'})):
                        with self.assertRaises(AlphaError) as stopped:
                            operation()
                        self.assertTrue(stopped.exception.youtube_authorization_fence)
                        self.assertEqual(stopped.exception.youtube_authorization_changed, changed)
                self.assertFalse(repository.writes)

    def test_recovery_reuses_its_existing_transaction_cursor(self):
        with self.journal.lock(KEY):
            current = Cursor(self.repository)
            opened = self.repository.opened
            self.journal.save(KEY, {'stage': 'uploading'}, cursor=current)
            self.assertEqual(self.repository.opened, opened)
            self.assertIn('FOR KEY SHARE', current.statements[0][0])
            self.assertIn('FOR NO KEY UPDATE', current.statements[1][0])
            self.assertEqual(len(self.repository.writes), 1)

    def test_deleted_workspace_stops_save_before_credential_lock_or_insert(self):
        with self.journal.lock(KEY):
            self.repository.workspace_present = False
            with self.assertRaises(AlphaError) as stopped:
                self.journal.save(KEY, {'stage': 'stale-response'})
        self.assertTrue(stopped.exception.youtube_authorization_fence)
        writer = self.repository.cursors[-1]
        self.assertEqual(len(writer.statements), 1)
        self.assertIn('public.pr_workspaces', writer.statements[0][0])
        self.assertFalse(self.repository.writes)

    def test_request_fence_does_not_hold_transaction_row_locks(self):
        self.journal.assert_authorized(*KEY[:2], self.repository.generation)
        reader = self.repository.cursors[-1]
        self.assertEqual(len(reader.statements), 1)
        self.assertIn('public.pr_encrypted_credentials', reader.statements[0][0])
        self.assertNotIn('FOR ', reader.statements[0][0])

    def test_generic_service_fence_requires_the_exact_nonempty_generation(self):
        for generation in (None, '', 'older-generation'):
            with self.subTest(generation=generation), self.assertRaises(AlphaError):
                self.journal.assert_authorized(*KEY[:2], generation)
        self.journal.assert_authorized(*KEY[:2], self.repository.generation)
        self.repository.revoked = True
        with self.assertRaises(AlphaError):
            self.journal.assert_authorized(*KEY[:2], self.repository.generation)

    def test_no_lock_wrong_operation_or_ended_context_cannot_save(self):
        for stage in ('before', 'during', 'after'):
            with self.subTest(stage=stage):
                if stage == 'during':
                    with self.journal.lock(KEY):
                        with self.assertRaises(AlphaError):
                            self.journal.save((*KEY[:2], 'another-operation'), {})
                else:
                    with self.assertRaises(AlphaError):
                        self.journal.save(KEY, {})
        self.assertFalse(self.repository.writes)


if __name__ == '__main__':
    unittest.main()
