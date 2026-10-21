"""Durable X operation transitions. A claimed write is never blindly replayed."""
import hashlib
import json
import math
import re
import secrets
import uuid

from postriff_alpha.domain import AlphaError

SELECT = """workspace_id::text,id::text,connection_id,provider_account_id,authorization_generation,
operation_id,request_key,request,digest,created_by::text,extract(epoch from created_at)::float8,
extract(epoch from preview_expires_at)::float8,state,approved_by::text,extract(epoch from approved_at)::float8,
extract(epoch from approval_expires_at)::float8,extract(epoch from next_at)::float8,attempts,checks,
lease_id::text,extract(epoch from lease_until)::float8,cancel_requested,progress,receipts,reason_code,reason"""
KEYS = ('workspace_id','id','connection_id','provider_account_id','authorization_generation',
        'operation_id','request_key','request','digest','created_by','created_at','preview_expires_at',
        'state','approved_by','approved_at','approval_expires_at','next_at','attempts','checks',
        'lease_id','lease_until','cancel_requested','progress','receipts','reason_code','reason')
JSON_FIELDS = frozenset(('request','progress','receipts'))
TIME_FIELDS = frozenset(('approved_at','approval_expires_at','next_at','lease_until'))
UPDATABLE = frozenset(('state','approved_by','approved_at','approval_expires_at','next_at',
    'attempts','checks','lease_id','lease_until','cancel_requested','progress','receipts','reason_code','reason'))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def schema_ready(cur):
    cur.execute("SELECT to_regclass('public.pr_x_direct_operations')")
    return bool(cur.fetchone()[0])


def require_schema(cur):
    if not schema_ready(cur):
        raise AlphaError('Unavailable — the X Direct operation journal is not installed.', 503,
                         code='x_direct_schema_required')


def row_value(row):
    if not row:
        return None
    value = dict(zip(KEYS, row))
    for key in JSON_FIELDS:
        if isinstance(value.get(key), str):
            value[key] = json.loads(value[key])
    return value


def read(cur, workspace, operation, *, lock=False):
    if not isinstance(operation, str) or not re.fullmatch(r'[0-9a-f-]{36}', operation):
        raise AlphaError('X operation unavailable.', 404)
    cur.execute('SELECT ' + SELECT + ' FROM public.pr_x_direct_operations WHERE workspace_id=%s AND id=%s'
                + (' FOR UPDATE' if lock else ''), (workspace, operation))
    found = row_value(cur.fetchone())
    if found is None:
        raise AlphaError('X operation unavailable.', 404)
    return found


def update(cur, workspace, operation, **values):
    if not values or not set(values) <= UPDATABLE:
        raise ValueError('Untrusted X journal update')
    expressions, parameters = [], []
    for key, value in values.items():
        expressions.append(key + ('=%s::jsonb' if key in JSON_FIELDS else
                                   '=to_timestamp(%s)' if key in TIME_FIELDS else '=%s'))
        parameters.append(json.dumps(value, allow_nan=False) if key in JSON_FIELDS else value)
    cur.execute('UPDATE public.pr_x_direct_operations SET ' + ','.join(expressions)
                + ',updated_at=now() WHERE workspace_id=%s AND id=%s',
                (*parameters, workspace, operation))
    return read(cur, workspace, operation)


def create(cur, *, workspace, connection, account, generation, actor, operation_id,
           request_key, request, now):
    require_schema(cur)
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_key):
        raise AlphaError('Use a stable request key for this operation.', 400, code='x_request_key_required')
    if not isinstance(generation, str) or not generation:
        raise AlphaError('Reconnect X to bind this authorization.', 409, code='x_oauth_binding_required')
    encoded = json.dumps(request, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 64000:
        raise AlphaError('This X operation is too large.', 422)
    digest = fingerprint({'workspace': workspace, 'connection': connection, 'account': account,
                          'generation': generation, 'operation': operation_id, 'request': request})
    cur.execute("""SELECT """ + SELECT + """ FROM public.pr_x_direct_operations
        WHERE workspace_id=%s AND connection_id=%s AND request_key=%s FOR UPDATE""",
        (workspace, connection, request_key))
    prior = row_value(cur.fetchone())
    if prior:
        if not secrets.compare_digest(prior['digest'], digest):
            raise AlphaError('This request key already names a different X operation.', 409,
                             code='x_idempotency_conflict')
        return prior
    operation = str(uuid.uuid4())
    cur.execute("""INSERT INTO public.pr_x_direct_operations(workspace_id,id,connection_id,
        provider_account_id,authorization_generation,operation_id,request_key,request,digest,created_by,
        preview_expires_at,next_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,
        to_timestamp(%s),to_timestamp(%s))""",
        (workspace, operation, connection, account, generation, operation_id, request_key,
         encoded, digest, actor, now + 900, now))
    return read(cur, workspace, operation)


def approve(cur, workspace, operation, actor, digest, confirmed, now):
    item = read(cur, workspace, operation, lock=True)
    assert_immutable(item)
    if confirmed is not True or not isinstance(digest, str) or not secrets.compare_digest(item['digest'], digest):
        raise AlphaError('Approve the exact current X operation.', 409, code='x_exact_approval_required')
    if item['state'] == 'queued' and item['approved_by'] == actor:
        return item
    if item['state'] != 'needs_approval' or item['preview_expires_at'] <= now:
        raise AlphaError('This X preview expired or already left review.', 409, code='x_approval_stale')
    scheduled = item['request'].get('scheduleAt')
    if scheduled is None:
        scheduled = now
    if type(scheduled) not in (int, float) or not math.isfinite(scheduled) or not now - 30 <= scheduled <= now + 30 * 86400:
        raise AlphaError('Choose an X schedule within the next 30 days.', 422, code='x_schedule_invalid')
    return update(cur, workspace, operation, state='queued', approved_by=actor, approved_at=now,
                  approval_expires_at=max(now, scheduled) + 1800, next_at=max(now, scheduled),
                  reason_code=None, reason=None)


def cancel(cur, workspace, operation, now):
    item = read(cur, workspace, operation, lock=True)
    if item['state'] in ('needs_approval', 'queued'):
        return update(cur, workspace, operation, state='canceled', cancel_requested=True,
                      reason_code='x_canceled_before_next_dispatch',
                      reason='Remaining X requests canceled. Existing API receipts remain valid.')
    if item['state'] in ('dispatching', 'accepted'):
        return update(cur, workspace, operation, cancel_requested=True,
                      reason_code='x_cancel_during_dispatch',
                      reason='A request may already have reached X. Reconciliation will retain its actual result.')
    return item


def claim(cur, workspace, operation, *, generation, account, authority, now):
    item = read(cur, workspace, operation, lock=True)
    assert_immutable(item)
    if item['lease_until'] and item['lease_until'] > now:
        return None
    if item['state'] == 'dispatching':
        # A lost process could have sent its write. Only an exact, recorded readback may continue.
        state = 'accepted' if item['progress'].get('phase') == 'reconcile' and item['receipts'] else 'uncertain'
        update(cur, workspace, operation, state=state, lease_id=None, lease_until=None,
               reason_code='x_dispatch_lease_expired',
               reason='The previous request has no completed local result; it was not resubmitted.')
        return None
    if item['state'] not in ('queued', 'accepted') or item['next_at'] > now:
        return None
    if item['cancel_requested'] and item['state'] == 'queued':
        cancel(cur, workspace, operation, now)
        return None
    if (not authority or item['authorization_generation'] != generation
            or item['provider_account_id'] != account or not item['approved_by']
            or not item['approval_expires_at'] or (item['state']=='queued' and item['approval_expires_at'] <= now)):
        update(cur, workspace, operation, state='held', lease_id=None, lease_until=None,
               reason_code='x_authorization_changed',
               reason='Account authorization, membership or approval changed before dispatch.')
        return None
    phase = 'reconcile' if item['state'] == 'accepted' else 'write'
    counter = 'checks' if phase == 'reconcile' else 'attempts'
    if item[counter] >= 3:
        update(cur, workspace, operation, state='uncertain' if phase == 'reconcile' else 'held',
               reason_code='x_attempt_budget_exhausted',
               reason='The bounded request allowance is exhausted; no additional request was sent.')
        return None
    return update(cur, workspace, operation, state='dispatching', lease_id=str(uuid.uuid4()),
                  lease_until=now + 90, progress={**item['progress'], 'phase': phase},
                  **{counter: item[counter] + 1})


def finish(cur, claim_value, *, state, now, receipt=None, reason_code=None, reason=None,
           next_at=None, progress=None, reset_counters=False):
    if state not in ('accepted','verified','uncertain','failed','held','queued','canceled'):
        raise ValueError('Invalid provider transition')
    item = read(cur, claim_value['workspace_id'], claim_value['id'], lock=True)
    assert_immutable(item)
    assert_immutable(claim_value)
    stale=item['state']!='dispatching' or item['lease_id']!=claim_value['lease_id']
    receipts=list(item['receipts'])
    if receipt is not None:
        incoming=_bound_receipt(claim_value,receipt,late=stale)
        if not any(r.get('journalEvidence',{}).get('key')==incoming['journalEvidence']['key'] for r in receipts):
            receipts.append(incoming)
    if stale:
        if receipts!=item['receipts'] and item['digest']==claim_value['digest']:
            update(cur,item['workspace_id'],item['id'],receipts=receipts)
        return None
    if state in ('accepted','verified') and not receipts:
        raise ValueError('Provider success requires a receipt')
    return update(cur, item['workspace_id'], item['id'], state=state, lease_id=None, lease_until=None,
                  receipts=receipts, progress=progress if progress is not None else item['progress'],
                  reason_code=reason_code, reason=reason, next_at=next_at if next_at is not None else now,
                  **({'attempts':0,'checks':0} if reset_counters else {}))


def immutable_digest(item):
    return fingerprint({'workspace':item['workspace_id'],'connection':item['connection_id'],
        'account':item['provider_account_id'],'generation':item['authorization_generation'],
        'operation':item['operation_id'],'request':item['request']})


def assert_immutable(item):
    if not isinstance(item.get('digest'),str) or not secrets.compare_digest(item['digest'],immutable_digest(item)):
        raise AlphaError('The approved X operation changed.',409,code='x_approval_changed')


def pending_fingerprint(item):
    thread=item.get('progress',{}).get('thread')
    if item.get('operation_id')=='posts.thread':
        items=thread.get('items') if isinstance(thread,dict) else None
        return items[-1].get('fingerprint') if isinstance(items,list) and items else None
    return item.get('request',{}).get('normalizedFingerprint')


def receipt_for(item):
    expected=pending_fingerprint(item)
    return next((r for r in reversed(item.get('receipts',[]))
        if isinstance(r,dict) and r.get('source')=='X API'
        and isinstance(r.get('resourceId'),str) and re.fullmatch(r'[1-9][0-9]{0,18}',r['resourceId'])
        and r.get('requestFingerprint')==expected),None)


def assert_dispatch_fence(cur,claimed,now):
    # Must be called in the same held transaction as the bounded provider I/O.
    if getattr(getattr(cur,'connection',None),'autocommit',True):
        raise AlphaError('X dispatch requires a held transaction.',503,code='x_transaction_required')
    live=read(cur,claimed['workspace_id'],claimed['id'],lock=True)
    assert_immutable(live)
    assert_immutable(claimed)
    cur.execute('SELECT extract(epoch from clock_timestamp())::float8')
    checked=max(float(cur.fetchone()[0]),float(now))
    same=all(live.get(k)==claimed.get(k) for k in
        ('digest','connection_id','provider_account_id','authorization_generation',
         'operation_id','request_key','approved_by','approved_at','approval_expires_at','progress'))
    if (not same or live['state']!='dispatching' or live['lease_id']!=claimed['lease_id']
            or not live.get('lease_until') or live['lease_until']<=checked):
        raise AlphaError('X dispatch no longer owns this exact operation.',409,code='x_stale_dispatch')
    if live['progress'].get('phase')=='write':
        if live['cancel_requested']:
            raise AlphaError('Remaining X actions were canceled.',409,code='x_cancel_requested')
        if not live['approval_expires_at'] or live['approval_expires_at']<=checked:
            raise AlphaError('X approval expired before dispatch.',409,code='x_approval_expired')
    elif live['progress'].get('phase')!='reconcile' or receipt_for(live) is None:
        raise AlphaError('No exact X receipt permits this readback.',409,code='x_reconciliation_denied')
    return live


def _bound_receipt(claimed,receipt,late=False):
    if (not isinstance(receipt,dict) or receipt.get('source')!='X API'
            or not isinstance(receipt.get('responseSha256'),str)
            or not re.fullmatch(r'[0-9a-f]{64}',receipt['responseSha256'])
            or receipt.get('requestFingerprint')!=pending_fingerprint(claimed)
            or type(receipt.get('httpStatus')) is not int or receipt['httpStatus'] not in (200,201)):
        raise ValueError('X receipt does not match the exact dispatched operation')
    raw={k:v for k,v in receipt.items() if k!='journalEvidence'}
    binding={'operationDigest':claimed['digest'],'leaseId':claimed['lease_id'],
        'requestFingerprint':pending_fingerprint(claimed)}
    key=fingerprint({'binding':binding,'receipt':raw})
    return {**raw,'journalEvidence':{**binding,'key':key,'late':bool(late)}}
