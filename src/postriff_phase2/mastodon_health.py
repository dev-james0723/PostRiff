"""One periodically due connection in the existing worker; no destination changes."""
import random
import time
import uuid

from postriff_alpha.domain import AlphaError


def delay(state, failures, jitter=random.uniform):
    if state in ('reauthorization_required', 'scope_missing', 'scope_changed'):
        return 6 * 3600
    if state == 'read_verified':
        return 3000 + jitter(0, 600)
    return min(6 * 3600, 60 * 2 ** min(10, failures)) + jitter(0, 30)


def maintain(oauth, *, seconds=8):
    """Claim and commit before network; stale responses cannot finish another lease.

    A shared transport deadline bounds socket operations. OS DNS resolution is
    still subject to the host resolver's timeout. A transient failure does not
    revoke authority or extend the last successful identity verification.
    """
    if type(seconds) not in (int, float) or not 1 <= seconds <= 8:
        raise ValueError('Health checks require a 1–8 second socket budget.')
    factory = oauth.repository.connection_factory
    lease = str(uuid.uuid4())
    with factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_mastodon_health') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {'state': 'schema_unavailable', 'checked': 0}
        # Enroll at most 100 per tick. Fresh connections are spread across an
        # hour, rather than fanning out all instance checks after deployment.
        cur.execute("INSERT INTO public.pr_mastodon_health(workspace_id,connection_id,next_at) SELECT c.workspace_id,c.connection_id,now()+make_interval(secs=>mod(abs(hashtextextended(c.workspace_id::text||c.connection_id,0)::numeric),3600)::integer) FROM public.pr_encrypted_credentials c WHERE c.provider='mastodon' AND c.revoked_at IS NULL AND NOT EXISTS(SELECT 1 FROM public.pr_mastodon_health h WHERE h.workspace_id=c.workspace_id AND h.connection_id=c.connection_id) ORDER BY c.workspace_id,c.connection_id LIMIT 100 ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM public.pr_mastodon_health WHERE (workspace_id,connection_id) IN (SELECT h.workspace_id,h.connection_id FROM public.pr_mastodon_health h JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) WHERE c.revoked_at IS NOT NULL OR c.provider<>'mastodon' ORDER BY h.workspace_id,h.connection_id LIMIT 100)")
        cur.execute("SELECT h.workspace_id::text,h.connection_id,h.failures,c.access_ciphertext FROM public.pr_mastodon_health h JOIN public.pr_encrypted_credentials c USING(workspace_id,connection_id) JOIN public.pr_workspaces w ON w.id=h.workspace_id WHERE h.next_at<=now() AND (h.lease_until IS NULL OR h.lease_until<=now()) AND c.revoked_at IS NULL AND c.provider='mastodon' AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock' ORDER BY h.next_at,h.workspace_id,h.connection_id LIMIT 1 FOR UPDATE OF h SKIP LOCKED")
        due = cur.fetchone()
        if not due:
            return {'state': 'idle', 'checked': 0}
        workspace, connection, failures, observed_ciphertext = due
        cur.execute("UPDATE public.pr_mastodon_health SET lease_id=%s,lease_until=now()+interval '60 seconds' WHERE workspace_id=%s AND connection_id=%s", (lease, workspace, connection))
    from .net_guard import request_deadline
    started = time.monotonic()
    try:
        with request_deadline(seconds):
            outcome = oauth.reverify_for_worker(workspace, connection)
        state = outcome.get('state', 'verification_unavailable')
    except (AlphaError, OSError, ValueError, TypeError):
        state = 'verification_unavailable'
    failures = 0 if state == 'read_verified' else min(10, failures + 1)
    with factory() as db, db.cursor() as cur:
        cur.execute("SELECT access_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL FOR SHARE", (workspace, connection))
        current = cur.fetchone()
        if not current or current[0] != observed_ciphertext:
            cur.execute("UPDATE public.pr_mastodon_health SET state='pending',failures=0,next_at=now()+interval '60 seconds',lease_id=NULL,lease_until=NULL WHERE workspace_id=%s AND connection_id=%s AND lease_id=%s", (workspace, connection, lease))
            return {'state': 'connection_changed', 'checked': 0}
        cur.execute("UPDATE public.pr_mastodon_health SET checked_at=now(),state=%s,failures=%s,next_at=now()+make_interval(secs=>%s),lease_id=NULL,lease_until=NULL WHERE workspace_id=%s AND connection_id=%s AND lease_id=%s AND lease_until>now()", (state, failures, delay(state, failures), workspace, connection, lease))
        committed = cur.rowcount == 1
    return {'state': state if committed else 'lease_changed', 'checked': int(committed),
            'socketBudgetSeconds': seconds, 'elapsedSeconds': round(time.monotonic() - started, 3)}
