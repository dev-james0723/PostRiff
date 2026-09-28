"""Immediate read revocation and content-free tombstones; no asynchronous visibility gap."""
from .store import TrendStorageError, identity_digest, row, rows, utcnow, trust_lock
from .contracts import digest, instant


def revoke_source(store, scope_key, provider_id, source_identity, *, deletion_sequence=0,
                  reason_code='provider_delete', purge_deadline=None, cursor=None):
    if type(deletion_sequence) is not int or deletion_sequence<0 or not reason_code.replace('_','').isalnum():
        raise TrendStorageError('invalid_tombstone')
    key = identity_digest(source_identity)
    with store.transaction(cursor) as cur:
        trust_lock(cur,exclusive=True)
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(scope_key+'|'+provider_id+'|'+key,))
        return _tombstone(cur,scope_key,provider_id,key,deletion_sequence,reason_code,purge_deadline or utcnow())


def _tombstone(cur, scope_key, provider_id, key, sequence, reason, deadline):
    instant(deadline)
    cur.execute("""INSERT INTO public.pr_trend_deletion_tombstones(scope_key,provider_id,source_identity_digest,deletion_sequence,reason_code,purge_deadline)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_key,provider_id,source_identity_digest) DO UPDATE SET
        deletion_sequence=greatest(pr_trend_deletion_tombstones.deletion_sequence,excluded.deletion_sequence),
        purge_deadline=least(pr_trend_deletion_tombstones.purge_deadline,excluded.purge_deadline) RETURNING *""",
        (scope_key,provider_id,key,sequence,reason,deadline))
    result = row(cur)
    cur.execute("""INSERT INTO public.pr_trend_deletion_tasks(scope_key,provider_id,source_identity_digest) VALUES(%s,%s,%s)
        ON CONFLICT(scope_key,provider_id,source_identity_digest) DO UPDATE SET state='queued',updated_at=clock_timestamp()""",(scope_key,provider_id,key))
    return result


def revoke_policy(store, scope_key, provider_id, version, *, cursor=None):
    with store.transaction(cursor) as cur:
        trust_lock(cur,exclusive=True)
        cur.execute('UPDATE public.pr_trend_source_policies SET revoked_at=coalesce(revoked_at,clock_timestamp()) WHERE scope_key=%s AND provider_id=%s AND version=%s',(scope_key,provider_id,version))
        # Reads traverse the policy immediately; cleanup can be bounded by the separate sweeper.
        return cur.rowcount


def revoke_entitlement(store, workspace_id, scope_key, *, cursor=None):
    with store.transaction(cursor) as cur:
        trust_lock(cur,exclusive=True)
        cur.execute('UPDATE public.pr_trend_entitlements SET revoked_at=coalesce(revoked_at,clock_timestamp()) WHERE workspace_id=%s AND scope_key=%s',(workspace_id,scope_key))
        return cur.rowcount


def revoke_author(store, provider_id, author_key, *, purge_deadline=None, cursor=None):
    """Verified provider identity event across all storage domains, including future replay.

    A durable author tombstone suppresses writes even when no observed source item exists yet.
    """
    key = identity_digest(author_key)
    with store.transaction(cursor) as cur:
        trust_lock(cur,exclusive=True)
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('trend-author|'+provider_id+'|'+key,))
        cur.execute('INSERT INTO public.pr_trend_author_tombstones(provider_id,author_digest,revoked_at,purge_deadline) VALUES(%s,%s,clock_timestamp(),%s) ON CONFLICT DO NOTHING',(provider_id,key,purge_deadline or utcnow()))
        cur.execute('SELECT DISTINCT scope_key,source_identity_digest FROM public.pr_trend_observations WHERE provider_id=%s AND author_key=%s',(provider_id,author_key))
        items = rows(cur)
        for item in items:
            _tombstone(cur,item['scope_key'],provider_id,item['source_identity_digest'],0,'provider_author_deleted',purge_deadline or utcnow())
        return len(items)


def export_tombstones(store, *, cursor=None):
    with store.transaction(cursor) as cur:
        cur.execute('SELECT * FROM public.pr_trend_deletion_tombstones ORDER BY scope_key,provider_id,source_identity_digest')
        sources = rows(cur)
        cur.execute('SELECT * FROM public.pr_trend_author_tombstones ORDER BY provider_id,author_digest')
        payload = {'sources':sources,'authors':rows(cur)}
        return {'payload':payload,'digest':digest(payload)}


def begin_restore(store, *, cursor=None):
    """Operator restore protocol: close reads before restoring/importing authoritative tombstones."""
    with store.transaction(cursor) as cur:
        trust_lock(cur,exclusive=True)
        cur.execute('UPDATE public.pr_trend_runtime_guard SET reads_ready=false,restore_generation=restore_generation+1,tombstone_digest=NULL WHERE singleton RETURNING restore_generation')
        return row(cur)['restore_generation']


def restore_tombstones(store, bundle, *, generation, cursor=None):
    if digest(bundle['payload'])!=bundle['digest']:
        raise TrendStorageError('tombstone_digest_mismatch')
    with store.transaction(cursor) as cur:
        cur.execute('SELECT * FROM public.pr_trend_runtime_guard WHERE singleton FOR UPDATE')
        guard = row(cur)
        if guard['reads_ready'] or guard['restore_generation']!=generation:
            raise TrendStorageError('restore_fence_required')
        for t in bundle['payload']['sources']:
            cur.execute('SELECT 1 FROM public.pr_trend_scopes WHERE scope_key=%s',(t['scope_key'],))
            if not cur.fetchone():
                store.ensure_scope(t['scope_key'],cursor=cur)
            _tombstone(cur,t['scope_key'],t['provider_id'],t['source_identity_digest'],t['deletion_sequence'],t['reason_code'],t['purge_deadline'])
        for t in bundle['payload']['authors']:
            cur.execute('INSERT INTO public.pr_trend_author_tombstones(provider_id,author_digest,revoked_at,purge_deadline) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(t['provider_id'],t['author_digest'],t['revoked_at'],t['purge_deadline']))
        cur.execute('UPDATE public.pr_trend_runtime_guard SET reads_ready=true,tombstone_digest=%s WHERE singleton',(bundle['digest'],))
        return {'restored':True,'generation':generation,'digest':bundle['digest']}
