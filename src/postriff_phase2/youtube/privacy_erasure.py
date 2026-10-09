"""Erase attributable API identity snapshots, preserving unusable approval evidence.

Caller order is workspace lock -> provenance-dependent cleanup -> this helper ->
source-row deletion. The cron entry point takes the same workspace lock itself.
Original digests are commitments, not anonymous data or executable approvals.
Submitted action inputs retain their original, unverified submission provenance;
we never reconstruct user input from a merged provider plan or scan free text.
"""
import copy
import json
import math
import time

RETENTION_SECONDS = 30 * 86400
BATCH_SIZE = 100
MARKER = 'privacyErased'
NOTICE = 'YouTube API identity data was erased. Prepare and approve a new operation; this approval cannot execute again.'


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _items(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _expired(record, now, *, manifest=False):
    clocks = [record.get('createdAt'), record.get('approvedAt')]
    if manifest:
        clocks.append(((record.get('manifest') or {}).get('capability') or {}).get('verifiedAt'))
    clocks = [_number(value) for value in clocks]
    clocks = [value for value in clocks if value is not None]
    return not clocks or any(value <= now - RETENTION_SECONDS or value > now for value in clocks)


def _manifest_match(record, workspace, connection):
    manifest = record.get('manifest')
    return (isinstance(manifest, dict) and manifest.get('platform') == 'YouTube'
            and manifest.get('workspaceId') == workspace and manifest.get('channelId') == connection)


def _stamp(record, reason, now):
    record.update(privacyErased=True, privacyErasedAt=now, privacyErasureReason=reason)


def scrub_workspace(state, workspace, connection, now, *, expired_only=False, unavailable=False):
    """Fixed identity slots only; original digests and all submitted content survive."""
    counts = {'reviews': 0, 'jobs': 0, 'drafts': 0, 'policies': 0}
    data = state.get('phase2') or {}
    reason = 'youtube_identity_expired' if expired_only else 'youtube_consent_revoked'
    for family in ('reviews', 'jobs'):
        for record in _items(data.get(family)):
            if (not _manifest_match(record, workspace, connection) or record.get(MARKER) is True
                    or expired_only and not unavailable and not _expired(record, now, manifest=True)):
                continue
            manifest = record['manifest']
            manifest.pop('account', None)
            manifest.pop('providerAccountId', None)
            _stamp(manifest, reason, now)
            _stamp(record, reason, now)
            if family == 'reviews':
                record['status'] = 'privacy_erased'
            else:
                record.update(state='held', leaseOwner=None, leaseUntil=0, nextAt=0,
                              cancelRequested=True, nextAction=NOTICE)
                record.pop('leaseId', None)
            counts[family] += 1
    agent = state.get('youtubeAgent') or {}
    for family in ('drafts', 'policies'):
        for record in _items(agent.get(family)):
            if (record.get('connectionId') != connection or record.get(MARKER) is True
                    or expired_only and not unavailable and not _expired(record, now)):
                continue
            # Empty is deliberately not a canonical channel. Do not regenerate
            # a digest: the old digest records a now-erased approval snapshot.
            record['channelId'] = ''
            _stamp(record, reason, now)
            record['status'] = 'revoked' if family == 'policies' else 'privacy_erased'
            record.pop('authorizationGeneration', None)
            counts[family] += 1
    return counts


def _connections(state, workspace):
    result = set()
    data = state.get('phase2') or {}
    for family in ('reviews', 'jobs'):
        for record in _items(data.get(family)):
            manifest = record.get('manifest') or {}
            if (manifest.get('platform') == 'YouTube' and manifest.get('workspaceId') == workspace
                    and isinstance(manifest.get('channelId'), str) and manifest['channelId']):
                result.add(manifest['channelId'])
    for family in ('drafts', 'policies'):
        for record in _items((state.get('youtubeAgent') or {}).get(family)):
            if isinstance(record.get('connectionId'), str) and record['connectionId']:
                result.add(record['connectionId'])
    return result


def _erase_actions(cur, workspace, connection, now, *, expired_only=False):
    predicate, params = '', (workspace, connection)
    if expired_only:
        predicate = ' AND created_at<=to_timestamp(%s)'
        params += (now - RETENTION_SECONDS,)
    limit = ' LIMIT 100' if expired_only else ''
    cur.execute('SELECT id::text,manifest FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s'
                + ' AND privacy_erased_at IS NULL' + predicate + ' ORDER BY id' + limit + ' FOR UPDATE', params)
    rows = cur.fetchall()
    for identifier, manifest in rows:
        tombstone = {'schema': 'postriff.youtube.action.privacy-erased.v1', 'action': manifest.get('action'),
                     MARKER: True, 'privacyErasedAt': now}
        cur.execute("""UPDATE public.pr_youtube_actions SET
            user_inputs=coalesce(user_inputs,manifest->'inputs'),manifest=%s::jsonb,
            status='privacy_erased',receipt=NULL,secret_ciphertext=NULL,secret_key_id=NULL,
            privacy_erased_at=to_timestamp(%s),updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND id::text=%s""",
            (json.dumps(tombstone), now, workspace, connection, identifier))
    return len(rows)


def _erase_audit(cur, workspace, connection, now, *, expired_only=False):
    # This narrowly privileged function resolves application subjects from the
    # database itself, while their exact connection provenance still exists.
    cur.execute('SELECT public.pr_youtube_erase_audit_fields(%s,%s,%s)',
                (workspace, connection, now - RETENTION_SECONDS if expired_only else None))
    return cur.fetchone()[0]


def _clear_revoked(cur, workspace, connection):
    cur.execute("""DELETE FROM public.pr_youtube_policy_bindings b WHERE b.workspace_id=%s AND b.connection_id=%s
        AND EXISTS(SELECT 1 FROM public.pr_encrypted_credentials c WHERE c.workspace_id=b.workspace_id
        AND c.connection_id=b.connection_id AND c.provider='youtube' AND c.revoked_at IS NOT NULL)""", (workspace, connection))
    bindings = cur.rowcount
    cur.execute("""UPDATE public.pr_encrypted_credentials SET provider_account_id='',scopes='{}'
        WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NOT NULL
        AND (provider_account_id<>'' OR cardinality(scopes)>0)""", (workspace, connection))
    return bindings, cur.rowcount


def _save(cur, workspace, state):
    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), workspace))


def purge_connection(cur, workspace, connection, now=None):
    """After provenance cleanup; caller already owns this workspace FOR UPDATE."""
    now = time.time() if now is None else now
    cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
    row = cur.fetchone()
    if not row:
        return {'reviews': 0, 'jobs': 0, 'drafts': 0, 'policies': 0, 'actions': 0, 'audit': 0, 'bindings': 0, 'credentials': 0}
    state = copy.deepcopy(json.loads(row[0]) if isinstance(row[0], str) else row[0])
    audit = _erase_audit(cur, workspace, connection, now)
    actions = _erase_actions(cur, workspace, connection, now)
    counts = scrub_workspace(state, workspace, connection, now)
    if any(counts.values()):
        _save(cur, workspace, state)
    bindings, credentials = _clear_revoked(cur, workspace, connection)
    return dict(counts, actions=actions, audit=audit, bindings=bindings, credentials=credentials)


def _array(path):
    return "CASE WHEN jsonb_typeof(w.state#>'{" + path + "}')='array' THEN w.state#>'{" + path + "}' ELSE '[]'::jsonb END"


def _old(alias, now, *, manifest=False):
    paths = ['createdAt', 'approvedAt'] + (['manifest,capability,verifiedAt'] if manifest else [])
    clocks = [alias + "#>'{" + path + "}'" for path in paths]
    terms = ["jsonb_path_exists(" + alias + ", '$." + path.replace(',', '.')
             + " ? (@ <= $cutoff || @ > $clock)', jsonb_build_object('cutoff', "
             + str(now - RETENTION_SECONDS) + ", 'clock', " + str(now) + '))' for path in paths]
    terms.append('(' + ' AND '.join("jsonb_typeof(" + clock + ") IS DISTINCT FROM 'number'" for clock in clocks) + ')')
    return '(' + ' OR '.join(terms) + ')'


def purge_expired(cur, now=None, *, purge_authorized=None):
    """Cron-only, <=100 workspaces; active revocation erases all consent copies.

    Otherwise action-only expiry processes <=100 rows per connection/pass.
    """
    now = time.time() if now is None else now
    if _number(now) is None:
        raise ValueError('A finite server retention clock is required.')
    candidates = []
    for family in ('reviews', 'jobs'):
        candidates.append('EXISTS(SELECT 1 FROM jsonb_array_elements(' + _array('phase2,' + family) + ") r WHERE r#>>'{manifest,platform}'='YouTube'"
                          " AND r#>>'{manifest,workspaceId}'=w.id::text AND coalesce(r#>>'{manifest,channelId}','')<>''"
                          " AND r->>'privacyErased' IS DISTINCT FROM 'true' AND " + _old('r', now, manifest=True) + ')')
    for family in ('drafts', 'policies'):
        candidates.append('EXISTS(SELECT 1 FROM jsonb_array_elements(' + _array('youtubeAgent,' + family)
                          + ") r WHERE coalesce(r->>'connectionId','')<>'' AND r->>'privacyErased' IS DISTINCT FROM 'true' AND " + _old('r', now) + ')')
    candidates += ["EXISTS(SELECT 1 FROM public.pr_youtube_actions a WHERE a.workspace_id=w.id AND a.privacy_erased_at IS NULL AND a.created_at<=to_timestamp(%s))",
                   "EXISTS(SELECT 1 FROM public.pr_encrypted_credentials c WHERE c.workspace_id=w.id AND c.provider='youtube' AND c.revoked_at IS NOT NULL AND (c.provider_account_id<>'' OR cardinality(c.scopes)>0))",
                   "EXISTS(SELECT 1 FROM public.pr_encrypted_credentials c WHERE c.workspace_id=w.id AND c.provider='youtube' AND c.revoked_at IS NULL AND coalesce(c.youtube_identity_ingested_at,c.created_at)<=to_timestamp(%s))",
                   "EXISTS(SELECT 1 FROM jsonb_array_elements(" + _array('phase2,channels') + ") c WHERE c->>'platform'='YouTube' AND c->>'youtubeProviderDataRemoved'='true' AND ("
                   "EXISTS(SELECT 1 FROM jsonb_array_elements(" + _array('phase2,jobs') + ") r WHERE r#>>'{manifest,channelId}'=c->>'id' AND r#>>'{manifest,platform}'='YouTube' AND NOT r ? 'privacyErased') OR "
                   "EXISTS(SELECT 1 FROM jsonb_array_elements(" + _array('phase2,reviews') + ") r WHERE r#>>'{manifest,channelId}'=c->>'id' AND r#>>'{manifest,platform}'='YouTube' AND NOT r ? 'privacyErased') OR "
                   "EXISTS(SELECT 1 FROM jsonb_array_elements(" + _array('youtubeAgent,drafts') + ") r WHERE r->>'connectionId'=c->>'id' AND NOT r ? 'privacyErased') OR "
                   "EXISTS(SELECT 1 FROM jsonb_array_elements(" + _array('youtubeAgent,policies') + ") r WHERE r->>'connectionId'=c->>'id' AND NOT r ? 'privacyErased')))" ]
    cur.execute('SELECT w.id::text FROM public.pr_workspaces w WHERE ' + ' OR '.join(candidates) + ' ORDER BY w.id LIMIT 100', (now - RETENTION_SECONDS, now - RETENTION_SECONDS))
    workspaces = [row[0] for row in cur.fetchall()]
    result = {'workspaces': 0, 'reviews': 0, 'jobs': 0, 'drafts': 0, 'policies': 0, 'actions': 0, 'audit': 0, 'bindings': 0, 'credentials': 0, 'activeRevoked': 0}
    for workspace in workspaces:
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE SKIP LOCKED', (workspace,))
        row = cur.fetchone()
        if not row:
            continue
        state = copy.deepcopy(json.loads(row[0]) if isinstance(row[0], str) else row[0])
        cur.execute("SELECT connection_id,revoked_at IS NOT NULL,extract(epoch from coalesce(youtube_identity_ingested_at,created_at))::float8,authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND provider='youtube' ORDER BY connection_id FOR UPDATE", (workspace,))
        credential_rows = cur.fetchall()
        credentials = {row[0]: row[1] for row in credential_rows}
        for connection, revoked, ingested, generation in credential_rows:
            if not revoked and ingested <= now - RETENTION_SECONDS:
                if purge_authorized is None:
                    raise RuntimeError('Active YouTube identity expiry requires the provenance cleanup callback.')
                # Re-evaluate the exact generation and source timestamp after
                # both locks; a newer OAuth identity read never inherits expiry.
                cur.execute("""UPDATE public.pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='',refresh_ciphertext=NULL,scopes='{}',updated_at=now()
                    WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL
                    AND authorization_generation::text=%s AND coalesce(youtube_identity_ingested_at,created_at)<=to_timestamp(%s)""",
                    (workspace, connection, generation, now - RETENTION_SECONDS))
                if cur.rowcount:
                    purge_authorized(cur, workspace, connection)
                    credentials[connection] = True
                    result['activeRevoked'] += 1
        # A callback may persist runtime and approval erasure. Never save the
        # earlier workspace snapshot over that cleanup.
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
        state = copy.deepcopy(cur.fetchone()[0])
        if isinstance(state, str):
            state = json.loads(state)
        cur.execute('SELECT DISTINCT connection_id FROM public.pr_youtube_actions WHERE workspace_id=%s AND privacy_erased_at IS NULL AND created_at<=to_timestamp(%s)', (workspace, now - RETENTION_SECONDS))
        connections = _connections(state, workspace) | set(credentials) | {row[0] for row in cur.fetchall()}
        unavailable = {c.get('id') for c in _items((state.get('phase2') or {}).get('channels')) if c.get('platform') == 'YouTube' and c.get('youtubeProviderDataRemoved')}
        changed = False
        for connection in sorted(connections):
            revoked = credentials.get(connection, False)
            counts = scrub_workspace(state, workspace, connection, now, expired_only=True,
                                     unavailable=revoked or connection in unavailable)
            changed = changed or any(counts.values())
            for key, value in counts.items():
                result[key] += value
            result['audit'] += _erase_audit(cur, workspace, connection, now, expired_only=not revoked)
            result['actions'] += _erase_actions(cur, workspace, connection, now, expired_only=not revoked)
            bindings, cleared = _clear_revoked(cur, workspace, connection)
            result['bindings'] += bindings
            result['credentials'] += cleared
        if changed:
            _save(cur, workspace, state)
        result['workspaces'] += 1
    return result
