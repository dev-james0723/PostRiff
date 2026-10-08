"""Server-only, workspace-scoped journals. Commit intent before any remote write."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json

from postriff_alpha.domain import AlphaError


class UploadJournal:
    def __init__(self, connection_factory, vault):
        self.connection_factory, self.vault = connection_factory, vault
        # A shared service can execute several uploads concurrently. Keep each
        # lock's exact consent generation in its execution context, never in a
        # mutable instance-wide field or in the customer-visible journal state.
        self._authorization = ContextVar('youtube_upload_authorization', default=None)

    @staticmethod
    def _authorization_error(changed=False):
        error = AlphaError('This YouTube authorization was disconnected or replaced. Reconnect and review before continuing.',
                           409, code='youtube_revoked_oauth')
        # This is a local fence, not a provider revocation observation. In
        # particular, an old worker must never purge a newer consent grant.
        error.youtube_authorization_fence = True
        error.youtube_authorization_changed = changed
        return error

    @staticmethod
    def _schema(cur):
        cur.execute("""SELECT EXISTS(SELECT 1 FROM pg_attribute
            WHERE attrelid=to_regclass('public.pr_encrypted_credentials')
              AND attname='authorization_generation' AND NOT attisdropped)""")
        if not cur.fetchone()[0]:
            raise AlphaError('YouTube publishing is temporarily unavailable. Try again later or contact Rafii support. No request was sent to YouTube.',
                             503, code='youtube_authorization_schema')

    @staticmethod
    def _generation(cur, key, *, locked=False):
        cur.execute("""SELECT authorization_generation::text FROM public.pr_encrypted_credentials
            WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL"""
            + (' FOR NO KEY UPDATE' if locked else ''), key[:2])
        row = cur.fetchone()
        return row[0] if row else None

    def _assert_current(self, cur, key, *, locked=False):
        expected = self._authorization.get()
        if expected is None or expected[0] != tuple(key):
            raise self._authorization_error(changed=True)
        self.assert_authorized(key[0], key[1], expected[1], cursor=cur, locked=locked)

    def assert_authorized(self, workspace, connection, generation, *, cursor=None, locked=False):
        """Shared exact-grant fence for API calls and transactional cache saves.

        A locked check must share the write's cursor so its credential lock
        survives until that same transaction commits. Never retain it for I/O.
        """
        def check(cur):
            if not isinstance(generation, str) or not generation:
                raise self._authorization_error(changed=True)
            if locked:
                # Hosted disconnect locks workspace -> credential. Child-table
                # foreign keys also acquire a workspace key-share lock, so take
                # that lock first rather than letting the later INSERT reverse
                # the order and deadlock with disconnect's workspace row lock.
                cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR KEY SHARE', (workspace,))
                if not cur.fetchone():
                    raise self._authorization_error()
            current = self._generation(cur, (workspace, connection), locked=locked)
            if current is None or current != generation:
                raise self._authorization_error(changed=current is not None)
        if cursor is not None:
            check(cursor)
        else:
            with self.connection_factory() as db, db.cursor() as cur:
                check(cur)

    def assert_current(self, key):
        """Read a fresh committed fence immediately before a provider request."""
        with self.connection_factory() as db, db.cursor() as cur:
            self._assert_current(cur, key)

    @contextmanager
    def lock(self, key):
        number = int.from_bytes(hashlib.sha256(':'.join(key).encode()).digest()[:8], 'big', signed=True)
        # Session lock: individual saves must commit before bytes leave the process.
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s)', (number,))
                if not cur.fetchone()[0]:
                    raise AlphaError('This upload is already being reconciled.', 409, code='youtube_operation_busy')
                token = None
                try:
                    self._schema(cur)
                    generation = self._generation(cur, key)
                    if generation is None:
                        raise self._authorization_error()
                    token = self._authorization.set((tuple(key), generation))
                    yield
                finally:
                    if token is not None:
                        self._authorization.reset(token)
                    cur.execute('SELECT pg_advisory_unlock(%s)', (number,))

    def load(self, key):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s AND operation_key=%s', key)
            row = cur.fetchone()
        return row[0] if row else None

    def save(self, key, state, *, cursor=None):
        def write(cur):
            # Serialize this save with disconnect/consent replacement. The
            # credential lock and upsert commit together; no network operation
            # runs while this short row lock is held.
            self._assert_current(cur, key, locked=True)
            cur.execute('INSERT INTO public.pr_youtube_uploads(workspace_id,connection_id,operation_key,state) VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT(workspace_id,connection_id,operation_key) DO UPDATE SET state=excluded.state,updated_at=now()', (*key, json.dumps(state)))
        if cursor is not None:
            # Recovery already owns the credential/workspace transaction. A
            # second connection would wait on its own uncommitted row lock.
            write(cursor)
        else:
            with self.connection_factory() as db, db.cursor() as cur:
                write(cur)

    def seal(self, value):
        return self.vault.encrypt(value)

    def unseal(self, ciphertext, key_id):
        return self.vault.decrypt(ciphertext, key_id)


def purge_authorized_data(cur, workspace_id, connection_id):
    """Revocation deletes authorized content immediately; keep only content-free audit events."""
    for table in ('pr_youtube_cache', 'pr_youtube_reporting_coverage', 'pr_youtube_chat_cursor',
                  'pr_youtube_uploads', 'pr_youtube_actions', 'pr_youtube_settings', 'pr_youtube_push'):
        cur.execute('SELECT to_regclass(%s)', ('public.' + table,))
        if cur.fetchone()[0]:
            cur.execute('DELETE FROM public.' + table + ' WHERE workspace_id=%s AND connection_id=%s', (workspace_id, connection_id))
    cur.execute("DELETE FROM public.pr_audience_threads WHERE workspace_id=%s AND connection_id=%s AND provider='youtube'", (workspace_id, connection_id))


def purge_expired_data(cur):
    # Cascades also remove reply drafts and their saved approval context.
    cur.execute("DELETE FROM public.pr_audience_threads WHERE provider='youtube' AND ingested_at<=now()-interval '30 days'")
    cur.execute('DELETE FROM public.pr_youtube_cache WHERE expires_at<=now()')
    cur.execute("DELETE FROM public.pr_youtube_reporting_coverage WHERE ingested_at<now()-interval '30 days'")
    cur.execute("DELETE FROM public.pr_youtube_chat_cursor WHERE updated_at<now()-interval '30 days'")
    # API response bodies and stream keys are sensitive authorized data, not indefinite audit content.
    cur.execute("UPDATE public.pr_youtube_actions SET receipt=NULL,secret_ciphertext=NULL,secret_key_id=NULL WHERE updated_at<now()-interval '30 days' AND (receipt IS NOT NULL OR secret_ciphertext IS NOT NULL)")
    cur.execute("DELETE FROM public.pr_youtube_usage WHERE attempted_at<now()-interval '90 days'")
