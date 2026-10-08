"""Server-only, workspace-scoped journals. Commit intent before any remote write."""
from contextlib import contextmanager
import hashlib
import json

from postriff_alpha.domain import AlphaError


class UploadJournal:
    def __init__(self, connection_factory, vault):
        self.connection_factory, self.vault = connection_factory, vault

    @contextmanager
    def lock(self, key):
        number = int.from_bytes(hashlib.sha256(':'.join(key).encode()).digest()[:8], 'big', signed=True)
        # Session lock: individual saves must commit before bytes leave the process.
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s)', (number,))
                if not cur.fetchone()[0]:
                    raise AlphaError('This upload is already being reconciled.', 409, code='youtube_operation_busy')
                try:
                    yield
                finally:
                    cur.execute('SELECT pg_advisory_unlock(%s)', (number,))

    def load(self, key):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s AND operation_key=%s', key)
            row = cur.fetchone()
        return row[0] if row else None

    def save(self, key, state):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('INSERT INTO public.pr_youtube_uploads(workspace_id,connection_id,operation_key,state) VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT(workspace_id,connection_id,operation_key) DO UPDATE SET state=excluded.state,updated_at=now()', (*key, json.dumps(state)))

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
