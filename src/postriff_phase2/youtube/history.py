"""Private, immutable history for inert YouTube plans; never a source of authority.

Every database API accepts the caller's transaction cursor. The caller must first
authorize workspace membership and the exact connection; service-role storage is
not an authorization substitute. Compaction saves the current locked JSON and
archive rows together, without creating a connection or committing. Migration
105 is required. Library assets, variants, ordinary jobs and counters are retained.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import math
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

TABLE = 'public.pr_youtube_agent_history'
MAX_PAGE = 50
MAX_RECORD_BYTES = 262144
KINDS = ('draft', 'policy')
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
SHA256 = re.compile(r'[a-f0-9]{64}\Z')
UNAVAILABLE = 'youtube_agent_history_unavailable'


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _identifier(value):
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_PAGE:
        raise AlphaError('Choose a history page size between one and 50.', 400,
                         code='youtube_agent_history_limit')
    return value


def _scope(workspace, connection, kind=None):
    try:
        workspace = str(UUID(str(workspace)))
    except (ValueError, TypeError, AttributeError) as error:
        raise AlphaError('YouTube history scope unavailable.', 400) from error
    if not isinstance(connection, str) or not 8 <= len(connection) <= 80 or not _identifier(connection):
        raise AlphaError('YouTube history scope unavailable.', 400)
    if kind is not None and kind not in KINDS:
        raise AlphaError('Choose a supported YouTube history kind.', 400)
    return workspace, connection


def _transaction(cur):
    if getattr(getattr(cur, 'connection', None), 'autocommit', None) is not False:
        raise AlphaError('YouTube history requires an existing transaction cursor.', 503,
                         code='youtube_agent_history_transaction_required')


def schema_ready(cur):
    """Presence check only; migration 105 installs RLS, indexes and immutability."""
    cur.execute('SELECT to_regclass(%s)', (TABLE,))
    row = cur.fetchone()
    return bool(row and row[0])


def _require_schema(cur):
    if not schema_ready(cur):
        raise AlphaError('YouTube plan history is unavailable until reviewed migration 105 is applied.',
                         503, code=UNAVAILABLE)


def _connection(cur, workspace, connection):
    # The caller owns the workspace lock before this credential lock. Revocation
    # uses the same order. No legacy credential or other provider fallback.
    cur.execute("""SELECT 1 FROM public.pr_encrypted_credentials
        WHERE workspace_id=%s AND connection_id=%s AND provider='youtube'
          AND revoked_at IS NULL FOR SHARE""", (workspace, connection))
    if not cur.fetchone():
        raise AlphaError('YouTube history connection unavailable.', 403)


@contextmanager
def _atomic(cur):
    # A caught logical conflict must not leave partial archive inserts behind.
    # Savepoints share the caller transaction; they never commit independently.
    cur.execute('SAVEPOINT youtube_agent_history_compaction')
    try:
        yield
    except Exception:
        cur.execute('ROLLBACK TO SAVEPOINT youtube_agent_history_compaction')
        cur.execute('RELEASE SAVEPOINT youtube_agent_history_compaction')
        raise
    else:
        cur.execute('RELEASE SAVEPOINT youtube_agent_history_compaction')


def _canonical(record):
    try:
        encoded = json.dumps(record, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise AlphaError('The YouTube history record is invalid; nothing was compacted.', 409,
                         code='youtube_agent_history_invalid_record') from error
    if len(encoded.encode('utf-8')) > MAX_RECORD_BYTES:
        raise AlphaError('The YouTube history record exceeds the bounded archive size.', 409,
                         code='youtube_agent_history_invalid_record')
    return encoded, hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _lease_blocks(data, now):
    if 'fleetLease' not in data:
        return False
    lease = data['fleetLease']
    # Unknown/malformed ownership is not evidence that compaction is safe.
    authority = lease.get('authorization') if isinstance(lease, dict) else None
    return (not isinstance(lease, dict) or not _identifier(lease.get('id'))
            or not isinstance(authority, dict) or not _identifier(authority.get('policyId'))
            or not isinstance(authority.get('policyDigest'), str) or not SHA256.fullmatch(authority['policyDigest'])
            or authority.get('status') != 'active' or not isinstance(authority.get('grantedBy'), str)
            or not authority['grantedBy'] or not _number(authority.get('grantedAt'))
            or 'authorizationGeneration' not in authority
            or authority['authorizationGeneration'] is not None and not _identifier(authority['authorizationGeneration'])
            or not _number(lease.get('until')) or lease['until'] > now)


def compaction_candidates(state, connection, now, limit=MAX_PAGE):
    """Pure closed groups of expired unqueued drafts and inert policies, <=50.

    Any job/review reference is retained even if terminal. An expired/revoked
    policy and its referenced eligible drafts move as one complete group; a
    retained policy can never lose a referenced draft. Groups larger than the
    bound stay in JSON. Malformed state/leases/references fail closed. Generated
    variants are deliberately never deleted: exclusive reference proof is absent.
    """
    limit = _limit(limit)
    if not _number(now) or not isinstance(state, dict):
        return []
    if state.get('accountDeletion') or state.get('accountBlock'):
        return []
    data, phase = state.get('youtubeAgent'), state.get('phase2', {})
    if not isinstance(data, dict) or not isinstance(phase, dict) or _lease_blocks(data, now):
        return []
    drafts, policies = data.get('drafts', []), data.get('policies', [])
    jobs, reviews = phase.get('jobs', []), phase.get('reviews', [])
    if any(not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows)
           for rows in (drafts, policies, jobs, reviews)):
        return []
    # Duplicate/missing IDs or ambiguous references cannot establish ownership.
    if any(not _identifier(item.get('id')) for item in drafts + policies):
        return []
    if len({d['id'] for d in drafts}) != len(drafts) or len({p['id'] for p in policies}) != len(policies):
        return []
    by_draft, by_policy = {d['id']: d for d in drafts}, {p['id']: p for p in policies}
    references = {}
    for policy in policies:
        entries = policy.get('drafts')
        if (not isinstance(entries, list) or any(not isinstance(entry, dict)
                or not _identifier(entry.get('id')) for entry in entries)):
            return []
        references[policy['id']] = {entry['id'] for entry in entries}
        references[policy['id']].update(d['id'] for d in drafts if d.get('policyId') == policy['id'])
    blocked_drafts, blocked_policies, blocked_variants = set(), set(), set()
    for item in jobs + reviews:
        authority, manifest = item.get('youtubeAgent', {}), item.get('manifest', {})
        if not isinstance(authority, dict) or not isinstance(manifest, dict):
            return []
        for value in (authority.get('draftId'), item.get('draftId')):
            if value:
                if not _identifier(value):
                    return []
                blocked_drafts.add(value)
        for value in (authority.get('policyId'), item.get('policyId')):
            if value:
                if not _identifier(value):
                    return []
                blocked_policies.add(value)
        for value in (manifest.get('variantId'), item.get('variantId')):
            if value:
                if not _identifier(value):
                    return []
                blocked_variants.add(value)
    eligible_drafts = {d['id'] for d in drafts if d.get('connectionId') == connection
        and d.get('status') == 'proposed' and d.get('jobId') is None and not d.get('policyId')
        and isinstance(d.get('timing'), dict) and _number(d['timing'].get('timestamp'))
        and d['timing']['timestamp'] <= now and _identifier(d.get('variantId'))
        and d['id'] not in blocked_drafts and d['variantId'] not in blocked_variants
        and isinstance(d.get('digest'), str) and SHA256.fullmatch(d['digest'])}
    eligible_policies = {p['id'] for p in policies if p.get('connectionId') == connection
        and p.get('status') in ('prepared', 'active', 'paused', 'revoked')
        and (p['status'] == 'revoked' or _number(p.get('endsAt')) and p['endsAt'] <= now)
        and p.get('jobId') is None
        and p['id'] not in blocked_policies
        and isinstance(p.get('digest'), str) and SHA256.fullmatch(p['digest'])}
    # Remove any group with a live, unknown or foreign reference, to a fixed point.
    while True:
        safe_policies = {pid for pid in eligible_policies if references[pid] <= eligible_drafts}
        safe_drafts = {did for did in eligible_drafts if all(pid in safe_policies
            for pid, refs in references.items() if did in refs)}
        if safe_policies == eligible_policies and safe_drafts == eligible_drafts:
            break
        eligible_policies, eligible_drafts = safe_policies, safe_drafts
    nodes = {('draft', did) for did in eligible_drafts} | {('policy', pid) for pid in eligible_policies}
    neighbors = {node: set() for node in nodes}
    for pid in eligible_policies:
        for did in references[pid]:
            neighbors[('policy', pid)].add(('draft', did))
            neighbors[('draft', did)].add(('policy', pid))
    def age(node):
        item = by_draft[node[1]] if node[0] == 'draft' else by_policy[node[1]]
        return (item.get('createdAt') if _number(item.get('createdAt')) else 0, *node)
    selected, seen = [], set()
    for node in sorted(nodes, key=age):
        if node in seen:
            continue
        component, pending = set(), [node]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(neighbors[current] - component)
        seen.update(component)
        if len(selected) + len(component) > limit:
            continue
        selected.extend(sorted(component, key=age))
    return [{'recordKind': kind, 'recordId': identifier,
             'record': copy.deepcopy(by_draft[identifier] if kind == 'draft' else by_policy[identifier])}
            for kind, identifier in selected]


def _archive_record(cur, workspace, connection, candidate):
    record = candidate['record']
    encoded, checksum = _canonical(record)
    key = (workspace, connection, candidate['recordKind'], candidate['recordId'])
    cur.execute("""INSERT INTO public.pr_youtube_agent_history
        (workspace_id,connection_id,record_kind,record_id,record,record_sha256)
        VALUES(%s,%s,%s,%s,%s::jsonb,%s)
        ON CONFLICT(workspace_id,connection_id,record_kind,record_id) DO NOTHING RETURNING record_id""",
        (*key, encoded, checksum))
    if cur.fetchone():
        return
    cur.execute("""SELECT record,record_sha256 FROM public.pr_youtube_agent_history
        WHERE workspace_id=%s AND connection_id=%s AND record_kind=%s AND record_id=%s""", key)
    existing = cur.fetchone()
    if not existing or existing[1] != checksum or _canonical(existing[0])[0] != encoded:
        raise AlphaError('An immutable YouTube history record conflicts; nothing was compacted.',
                         409, code='youtube_agent_history_conflict')


def archive_and_compact(cur, workspace_id, connection_id, now, limit=MAX_PAGE):
    """Archive and persist compaction atomically inside the caller transaction.

    Caller authorization must precede this API. The current workspace row is locked
    and reread; no stale external JSON is accepted. No provider calls, token access,
    auto-activation, original-media deletion or independent commit occurs here.
    """
    workspace, connection = _scope(workspace_id, connection_id)
    _limit(limit)
    _transaction(cur)
    _require_schema(cur)
    with _atomic(cur):
        cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace,))
        row = cur.fetchone()
        if not row:
            raise AlphaError('YouTube history workspace unavailable.', 403)
        revision, state = row
        if isinstance(state, str):
            state = json.loads(state)
        _connection(cur, workspace, connection)
        candidates = compaction_candidates(state, connection, now, limit)
        if candidates:
            for candidate in candidates:
                _archive_record(cur, workspace, connection, candidate)
            state = copy.deepcopy(state)
            data = state['youtubeAgent']
            for kind, field in (('draft', 'drafts'), ('policy', 'policies')):
                identifiers = {c['recordId'] for c in candidates if c['recordKind'] == kind}
                data[field] = [record for record in data[field] if record['id'] not in identifiers]
            cur.execute("""UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1
                WHERE id=%s AND revision=%s RETURNING revision""", (json.dumps(state), workspace, revision))
            saved = cur.fetchone()
            if not saved:
                raise AlphaError('Workspace changed; nothing was compacted.', 409,
                                 code='workspace_revision_conflict')
            revision = saved[0]
        return {'archived': len(candidates), 'revision': revision,
                'draftsArchived': sum(c['recordKind'] == 'draft' for c in candidates),
                'policiesArchived': sum(c['recordKind'] == 'policy' for c in candidates),
                'authorityReactivated': False,
                'residualGrowth': ['Generated variants and Library assets are retained.',
                                   'Ordinary jobs, live references and groups larger than 50 remain in workspace JSON.']}


def _utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _cursor(workspace, connection, kind, row):
    identifier, _record, checksum, archived_at = row
    body = {'v': 1, 'w': workspace, 'c': connection, 'k': kind,
            't': _utc(archived_at), 'i': identifier, 's': checksum}
    return base64.urlsafe_b64encode(json.dumps(body, separators=(',', ':')).encode()).decode().rstrip('=')


def _parse_cursor(value, workspace, connection, kind):
    def invalid():
        return AlphaError('YouTube history cursor unavailable; restart from the first page.',
                          400, code='youtube_agent_history_cursor')
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise invalid()
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        body = json.loads(raw)
        if (not isinstance(body, dict) or set(body) != {'v', 'w', 'c', 'k', 't', 'i', 's'}
                or type(body['v']) is not int or body['v'] != 1
                or (body['w'], body['c'], body['k']) != (workspace, connection, kind)
                or not _identifier(body['i']) or not isinstance(body['s'], str) or not SHA256.fullmatch(body['s'])
                or not isinstance(body['t'], str)):
            raise invalid()
        stamp = datetime.fromisoformat(body['t'])
        if stamp.tzinfo is None or _utc(stamp) != body['t']:
            raise invalid()
        # Reject alternate encodings and duplicate keys, not merely parseable JSON.
        encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(',', ':')).encode()).decode().rstrip('=')
        if encoded != value:
            raise invalid()
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, OverflowError) as error:
        raise invalid() from error
    return body


def public_metadata(kind, record, archived_at):
    """Allowlist only. Stored private records never become executable payloads."""
    result = {'recordKind': kind, 'id': record.get('id'), 'status': 'archived',
              'historicalStatus': record.get('status') if record.get('status') in
              ('proposed', 'prepared', 'active', 'paused', 'revoked') else 'unknown',
              'archivedAt': _utc(archived_at), 'canReactivate': False}
    checksum = record.get('digest')
    if isinstance(checksum, str) and SHA256.fullmatch(checksum):
        result['digest'] = checksum
    channel = record.get('channelId')
    if isinstance(channel, str) and re.fullmatch(r'UC[A-Za-z0-9_-]{22}', channel):
        result['channelId'] = channel
    for source, target in (('createdAt', 'createdAt'), ('endsAt', 'authorityEndedAt')):
        if _number(record.get(source)):
            result[target] = record[source]
    timing = record.get('timing')
    if isinstance(timing, dict) and _number(timing.get('timestamp')):
        result['plannedAt'] = timing['timestamp']
    zone = timing.get('timeZone') if isinstance(timing, dict) else record.get('timeZone')
    if isinstance(zone, str) and len(zone) <= 64:
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            pass
        else:
            result['timeZone'] = zone
    return result


def page(cur, workspace_id, connection_id, kind, *, limit=MAX_PAGE, cursor=None):
    """Newest-first indexed keyset page; no count/offset/unscoped lookup.

    A cursor is an opaque scoped anchor, not authorization. Strict scope and the
    original immutable row/time/checksum must match; removed or tampered anchors
    fail closed. Inserts after the first page appear only on a fresh first page.
    """
    workspace, connection = _scope(workspace_id, connection_id, kind)
    limit = _limit(limit)
    anchor = _parse_cursor(cursor, workspace, connection, kind) if cursor is not None else None
    _transaction(cur)
    _require_schema(cur)
    _connection(cur, workspace, connection)
    scope = (workspace, connection, kind)
    if anchor:
        cur.execute("""SELECT 1 FROM public.pr_youtube_agent_history
            WHERE workspace_id=%s AND connection_id=%s AND record_kind=%s AND record_id=%s
              AND archived_at=%s::timestamptz AND record_sha256=%s""",
            (*scope, anchor['i'], anchor['t'], anchor['s']))
        if not cur.fetchone():
            raise AlphaError('YouTube history cursor unavailable; restart from the first page.',
                             400, code='youtube_agent_history_cursor')
    continuation = ' AND (archived_at,record_id)<(%s::timestamptz,%s)' if anchor else ''
    values = (*scope, anchor['t'], anchor['i'], limit + 1) if anchor else (*scope, limit + 1)
    cur.execute("""SELECT record_id,record,record_sha256,archived_at FROM public.pr_youtube_agent_history
        WHERE workspace_id=%s AND connection_id=%s AND record_kind=%s""" + continuation +
        ' ORDER BY archived_at DESC,record_id DESC LIMIT %s', values)
    rows = cur.fetchall()
    visible = rows[:limit]
    return {'items': [public_metadata(kind, row[1], row[3]) for row in visible],
            'nextCursor': _cursor(workspace, connection, kind, visible[-1]) if len(rows) > limit else None,
            'canReactivate': False}


def purge_connection_history(cur, workspace_id, connection_id):
    """Explicit disconnect cleanup of local archives, never original media.

    Wire into the authorized disconnect/revocation transaction. Credential/workspace
    deletion also cascades. A revoked_at update alone does not trigger FK cascade.
    Missing migration has no archive to clean; it never enables compaction fallback.
    """
    workspace, connection = _scope(workspace_id, connection_id)
    _transaction(cur)
    if not schema_ready(cur):
        return 0
    cur.execute('DELETE FROM public.pr_youtube_agent_history WHERE workspace_id=%s AND connection_id=%s',
                (workspace, connection))
    return cur.rowcount
