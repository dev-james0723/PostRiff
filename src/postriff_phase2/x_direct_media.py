"""Approval-bound X media workflow, one official request per durable worker step.

No endpoint is priced by guesswork. Transfers need explicit server-side price
ceilings and the ordinary X cost controller. Storage identity, account consent,
expiry, and exact attachment keys remain bound through post readback.

Official contracts: docs.x.com/x-api/media/{upload-media,initialize-media-upload,
append-media-upload,finalize-media-upload,get-media-upload-status,create-media-metadata}
OpenAPI 2.172, checked 2026-10-20. No live provider acceptance is implied.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace

from postriff_alpha.domain import AlphaError
from .x_direct_contract import NormalizedOperation
from .x_direct_cost import MEDIA_PRICE_KEYS, XCostAdmissionError
from .x_direct_executor import plain, provider_failure, receipt, valid_id
from .social_connectors import multipart

CHUNK_BYTES = 4 * 1024 * 1024
MAX_POLLS = 8
IMAGE_LIMITS = {'image/jpeg': 5_000_000, 'image/png': 5_000_000, 'image/gif': 15_000_000}
VIDEO_LIMIT = 100_000_000  # Rafii's verified private-storage cap, not X's platform cap.
VERSION = 'rafii-x-media-v1-20261020'


def _fail(message, code='x_media_invalid'):
    raise AlphaError(message, 409, code=code)


def _digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _asset(value):
    if not isinstance(value, Mapping) or value.get('deleted') or value.get('deleting'):
        _fail('This media asset was deleted or is unavailable.', 'x_media_asset_unavailable')
    aid, name, mime, size, identity = (value.get(key) for key in ('id', 'objectName', 'mime', 'bytes', 'hash'))
    if (not isinstance(aid, str) or not re.fullmatch(r'[a-f0-9]{32}', aid)
            or not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity)
            or type(size) is not int or size <= 0 or not isinstance(name, str)):
        _fail('Choose a verified immutable Rafii media asset.', 'x_media_asset_unavailable')
    result = {key: value[key] for key in ('id', 'objectName', 'mime', 'bytes', 'hash')}
    result['deleted'] = False
    if mime in IMAGE_LIMITS:
        if (size > IMAGE_LIMITS[mime] or value.get('processing') != 'decoded'
                or not re.fullmatch(r'[a-f0-9]{32}-[a-f0-9]{64}\.jpg', name)):
            _fail('This image exceeds the supported rendition limit or is not decoded.', 'x_media_asset_unavailable')
        result['processing'] = 'decoded'
    elif mime in ('video/mp4', 'video/quicktime'):
        etag, duration = value.get('etag'), value.get('duration')
        if (size > VIDEO_LIMIT or value.get('processing') != 'ready'
                or not re.fullmatch(r'[a-f0-9]{32}\.(mp4|mov)', name)
                or not isinstance(etag, str) or not 1 <= len(etag) <= 200
                or type(duration) not in (int, float) or not math.isfinite(duration)
                or not 0 < duration <= 1200 or value.get('durationSource') != 'container'
                or (value.get('verified') or {}).get('container') is not True):
            _fail('Rafii requires a container-verified video of at most 100 MB and 20 minutes.', 'x_media_asset_unavailable')
        expected = hashlib.sha256(f'video:{name}:{size}:{etag}'.encode()).hexdigest()
        if identity != expected:
            _fail('The verified video identity changed.', 'x_media_asset_changed')
        result.update(etag=etag, duration=duration, durationSource='container', processing='ready', verified={'container': True})
    else:
        _fail('Unavailable — this Rafii media rendition type has no verified X upload path.', 'x_media_asset_unavailable')
    return result


def _envelope(asset, alt, prices):
    stages = ({'media_upload': 1} if asset['mime'] in IMAGE_LIMITS else
              {'media_initialize': 1, 'media_append': math.ceil(asset['bytes'] / CHUNK_BYTES), 'media_finalize': 1})
    stages['media_status'] = MAX_POLLS
    if alt:
        stages['media_metadata'] = 1
    if any(type(prices.get(key)) is not int or prices[key] <= 0 for key in stages):
        raise XCostAdmissionError('Unavailable — X media transfers require explicit, current per-endpoint price evidence.')
    # Every stage permits at most three definite refusals. Unknown writes stop.
    return {'maximumApiRequests': 3 * sum(stages.values()),
            'estimatedMaxCostMicros': 3 * sum(prices[key] * count for key, count in stages.items()),
            'priceKeys': frozenset(stages)}


def _fingerprint(workspace, connection, actor, asset, alt):
    return _digest({'version': VERSION, 'workspace': workspace, 'connection': connection,
                    'actor': actor, 'asset': asset, 'altText': alt})


def plan_media(workspace, connection, actor, asset, alt, prices):
    asset = _asset(asset)
    if not isinstance(alt, str) or len(alt) > 1000 or '\x00' in alt:
        _fail('Alternative text must be a string of at most 1,000 characters.')
    if not valid_id(actor) or not isinstance(connection, str) or not re.fullmatch(r'[a-f0-9]{32}', connection):
        _fail('The X upload is not bound to an authorized account.', 'x_media_account_invalid')
    envelope = _envelope(asset, alt, prices)
    return NormalizedOperation('media.upload', 'POST', '/2/media/upload',
        {'asset': asset, 'altText': alt}, {}, _fingerprint(workspace, connection, actor, asset, alt),
        envelope['estimatedMaxCostMicros'], envelope['maximumApiRequests'])


def media_budget(request, prices):
    if request.operation_id != 'media.upload' or set(request.body) != {'asset', 'altText'}:
        raise XCostAdmissionError('Invalid X media workflow cost envelope.')
    budget = _envelope(_asset(request.body['asset']), request.body['altText'], prices)
    if request.estimated_cost_micros != budget['estimatedMaxCostMicros'] or request.max_billable_resources != budget['maximumApiRequests']:
        raise XCostAdmissionError('X media prices changed. Review this exact upload again.')
    return budget


def asset_from_workspace(cur, workspace, asset_id):
    if not isinstance(asset_id, str) or not re.fullmatch(r'[a-f0-9]{32}', asset_id):
        _fail('Choose an existing workspace media asset.', 'x_media_asset_unavailable')
    cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace,))
    row = cur.fetchone()
    state = json.loads(row[0]) if row and isinstance(row[0], str) else row[0] if row else {}
    matches = [a for a in (state.get('phase2') or {}).get('assets', []) if isinstance(a, dict) and a.get('id') == asset_id]
    if len(matches) != 1:
        _fail('This media asset is unavailable in this workspace.', 'x_media_asset_unavailable')
    return _asset(matches[0])


def plan_input(cur, workspace, connection, credential, body, prices):
    payload = body.get('body')
    if (not isinstance(payload, dict) or set(payload) - {'asset_id', 'alt_text'}
            or body.get('path') or body.get('query') or body.get('scheduleAt') is not None):
        _fail('Upload an exact workspace asset first; schedule the post separately.')
    return plan_media(workspace, connection, credential['account'],
                      asset_from_workspace(cur, workspace, payload.get('asset_id')),
                      payload.get('alt_text', ''), prices)


def _read_image(storage, workspace, asset):
    if asset['bytes'] > 8 * 1024 * 1024 and hasattr(storage, 'get_bounded'):
        data = storage.get_bounded(workspace, 'media', asset['objectName'], max_bytes=asset['bytes'])
    else:
        data = storage.get(workspace, 'media', asset['objectName'])
    if (not isinstance(data, bytes) or len(data) != asset['bytes']
            or hashlib.sha256(data).hexdigest() != asset['hash']):
        _fail('The approved image bytes changed.', 'x_media_asset_changed')
    return data


def _read_chunk(storage, workspace, asset, segment):
    stream = storage.iter_verified_video(workspace, asset['objectName'], expected_bytes=asset['bytes'],
        expected_mime=asset['mime'], expected_etag=asset['etag'], chunk_size=CHUNK_BYTES)
    try:
        for index, chunk in enumerate(stream):
            if index == segment:
                wanted = min(CHUNK_BYTES, asset['bytes'] - segment * CHUNK_BYTES)
                if not isinstance(chunk, bytes) or len(chunk) != wanted or wanted <= 0:
                    _fail('The approved video chunk changed.', 'x_media_asset_changed')
                return chunk
    finally:
        close = getattr(stream, 'close', None)
        if close: close()
    _fail('The approved video chunk is unavailable.', 'x_media_asset_changed')


def _expires(data, now, existing=None):
    ttl = data.get('expires_after_secs')
    if type(ttl) is not int or not 0 < ttl <= 86400:
        raise ValueError('Missing bounded media expiration')
    return min(existing, now + ttl) if existing is not None else now + ttl


def _media_identity(data, previous=None):
    rid, key = data.get('id'), data.get('media_key')
    if (not valid_id(rid) or not isinstance(key, str)
            or not re.fullmatch(r'[1-9][0-9]{0,3}_' + re.escape(rid), key)):
        raise ValueError('Missing or contradictory media identifiers')
    if previous and (rid != previous['id'] or key != previous['mediaKey']):
        raise ValueError('Media identity changed')
    return rid, key


def _ready_stage(data, state, *, from_status=False):
    processing = data.get('processing_info')
    if processing is None and not from_status:
        return True, None
    if not isinstance(processing, dict) or processing.get('state') not in ('pending', 'in_progress', 'succeeded', 'failed'):
        raise ValueError('Unknown media processing state')
    stage = processing['state']
    if stage == 'failed': return False, 'failed'
    if stage == 'succeeded': return True, None
    delay = processing.get('check_after_secs')
    if type(delay) is not int or not 0 <= delay <= 86400:
        raise ValueError('Missing processing retry delay')
    return False, max(1, delay)


def advance_media(request, provider, grant, progress, storage, *, now, before_send=None):
    """Execute at most ONE cost-admitted request. The journal owns the lease/approval."""
    asset, alt = _asset(request.body.get('asset')), request.body.get('altText')
    if (request.operation_id != 'media.upload' or request.method != 'POST' or request.path != '/2/media/upload'
            or request.query or getattr(provider, 'id', None) != 'x' or not isinstance(alt, str)
            or _fingerprint(grant.get('workspaceId'), grant.get('connectionId'), grant.get('providerAccountId'), asset, alt) != request.fingerprint
            or 'media.write' not in grant.get('scopes', [])
            or 'media.write' not in (provider.inspect_scopes(grant.get('accessToken')) or [])
            or provider.authorization_generation(grant.get('accessToken')) != grant.get('authorizationGeneration')):
        _fail('The upload does not match this X account and consent.', 'x_media_account_invalid')
    state = dict(progress.get('media') or {'stage': 'upload' if asset['mime'] in IMAGE_LIMITS else 'initialize',
        'offset': 0, 'polls': 0, 'planFingerprint': request.fingerprint,
        'authorizationGeneration': grant['authorizationGeneration']})
    stage = state.get('stage')
    if (state.get('planFingerprint') != request.fingerprint
            or state.get('authorizationGeneration') != grant['authorizationGeneration']
            or stage not in ('upload', 'initialize', 'append', 'finalize', 'status', 'metadata')
            or type(state.get('offset')) is not int or not 0 <= state['offset'] <= asset['bytes']
            or type(state.get('polls')) is not int or not 0 <= state['polls'] <= MAX_POLLS):
        _fail('The saved upload state is not bound to this approval.', 'x_media_state_invalid')
    if stage not in ('upload', 'initialize'):
        if (not valid_id(state.get('id')) or not isinstance(state.get('mediaKey'), str)
                or type(state.get('expiresAt')) not in (int, float) or not math.isfinite(state['expiresAt'])
                or state['expiresAt'] <= now):
            _fail('The X upload expired or has no valid provider identity.', 'x_media_expired')
    verb, path, options = 'POST', '/2/media/upload', {}
    chunk_hash = None
    if stage == 'upload':
        raw = _read_image(storage, grant['workspaceId'], asset)
        category = 'tweet_gif' if asset['mime'] == 'image/gif' else 'tweet_image'
        data, mime = multipart([('media_category', category)], [('media', 'rafii-media', asset['mime'], raw)])
        options = {'data': data, 'headers': {'Content-Type': mime}}
        chunk_hash = hashlib.sha256(raw).hexdigest()
    elif stage == 'initialize':
        path += '/initialize'
        options = {'json_body': {'media_type': asset['mime'], 'total_bytes': asset['bytes'], 'media_category': 'tweet_video'}}
    elif stage == 'append':
        if state['offset'] >= asset['bytes'] or state['offset'] % CHUNK_BYTES:
            _fail('The upload chunk offset is invalid.', 'x_media_state_invalid')
        index = state['offset'] // CHUNK_BYTES
        raw = _read_chunk(storage, grant['workspaceId'], asset, index)
        data, mime = multipart([('segment_index', index)], [('media', 'rafii-chunk', 'application/octet-stream', raw)])
        path += '/' + state['id'] + '/append'
        options = {'data': data, 'headers': {'Content-Type': mime}}
        chunk_hash = hashlib.sha256(raw).hexdigest()
    elif stage == 'finalize':
        if state['offset'] != asset['bytes']:
            _fail('Not all approved video bytes were uploaded.', 'x_media_state_invalid')
        path += '/' + state['id'] + '/finalize'
    elif stage == 'status':
        if state['polls'] >= MAX_POLLS:
            return {'state': 'held', 'progress': {**progress, 'media': state}, 'reasonCode': 'x_media_processing_limit',
                    'reason': 'The bounded X processing check allowance is exhausted.'}
        verb = 'GET'
        options = {'query': {'command': 'STATUS', 'media_id': state['id']}}
    else:
        path = '/2/media/metadata'
        options = {'json_body': {'id': state['id'], 'metadata': {'alt_text': {'text': alt}}}}
    if before_send is not None:
        before_send()  # Storage reads may outlive the lease; recheck before external I/O.
    try:
        response = provider.api(grant['accessToken'], verb, path, max_resources=1, **options)
    except XCostAdmissionError:
        raise
    except AlphaError as error:
        if error.code != 'x_provider_transport_unknown': raise
        return {'state': 'uncertain', 'reasonCode': 'x_media_outcome_unknown',
                'reason': 'X may have received the upload step. It will not be replayed.'}
    except (OSError, TimeoutError, ValueError, TypeError):
        return {'state': 'uncertain', 'reasonCode': 'x_media_outcome_unknown',
                'reason': 'X may have received the upload step. It will not be replayed.'}
    if not isinstance(response, dict) or type(response.get('status')) is not int or response['status'] not in (200, 201):
        return {**provider_failure(response if isinstance(response, dict) else {}, now=now),
                'progress': {**progress, 'media': state}}
    body = response.get('body'); data = body.get('data') if isinstance(body, dict) else None
    candidate_id = data.get('id') if isinstance(data, dict) else state.get('id')
    candidate_id = candidate_id if valid_id(candidate_id) else state.get('id')
    evidence = receipt(replace(request, method=verb, path=path), response, data, resource_id=candidate_id)
    evidence.update(mediaStep=stage, accountBinding='authenticated_upload', assetIdentity=asset['hash'],
                    authorizationGeneration=grant['authorizationGeneration'], accountId=grant['providerAccountId'])
    if chunk_hash: evidence['chunkSha256'] = chunk_hash
    if stage == 'append': evidence['segmentIndex'] = state['offset'] // CHUNK_BYTES
    next_at, completed = now, False
    try:
        if not isinstance(data, dict) or body.get('errors'):
            raise ValueError('Partial or missing upload response')
        if stage in ('upload', 'initialize'):
            rid, key = _media_identity(data)
            state.update(id=rid, mediaKey=key, expiresAt=_expires(data, now))
        elif stage in ('finalize', 'status'):
            _media_identity(data, state)
            state['expiresAt'] = _expires(data, now, state['expiresAt'])
            if 'size' in data and data['size'] != asset['bytes']:
                raise ValueError('Wrong uploaded byte count')
        if stage == 'initialize': state['stage'] = 'append'
        elif stage == 'append':
            if type(data.get('expires_at')) not in (int, float) or not math.isfinite(data['expires_at']) or data['expires_at'] <= now:
                raise ValueError('Missing append acceptance expiration')
            state['expiresAt'] = min(state['expiresAt'], data['expires_at'])
            state['offset'] += min(CHUNK_BYTES, asset['bytes'] - state['offset'])
            state['stage'] = 'finalize' if state['offset'] == asset['bytes'] else 'append'
        elif stage == 'metadata':
            if data.get('id') != state['id'] or (data.get('associated_metadata') or {}).get('alt_text') != {'text': alt}:
                raise ValueError('Alternative text was not confirmed')
            state.update(altVerified=True, stage='ready'); completed = True
        else:
            if stage == 'status': state['polls'] += 1
            ready, wait = _ready_stage(data, state, from_status=stage == 'status')
            if wait == 'failed':
                return {'state': 'failed', 'receipt': evidence, 'progress': {**progress, 'media': state},
                        'reasonCode': 'x_media_processing_failed', 'reason': 'X rejected media processing.'}
            if ready:
                state['stage'] = 'metadata' if alt else 'ready'
                completed = not alt
            else:
                state['stage'] = 'status'; next_at = now + wait
                if state['polls'] >= MAX_POLLS:
                    return {'state': 'held', 'receipt': evidence, 'progress': {**progress, 'media': state},
                            'reasonCode': 'x_media_processing_limit', 'reason': 'X media is not ready within the approved processing allowance.'}
    except (ValueError, TypeError, KeyError):
        return {'state': 'uncertain', 'receipt': evidence, 'progress': {**progress, 'media': state},
                'reasonCode': 'x_media_response_unverified',
                'reason': 'The X response did not verify the exact media step. No write will be repeated.'}
    evidence.update(mediaKey=state.get('mediaKey'), expiresAt=state.get('expiresAt'), mediaReady=completed)
    return {'state': 'verified' if completed else 'queued', 'receipt': evidence,
            'progress': {**progress, 'media': state}, 'resetCounters': True, 'nextAt': next_at,
            'reason': 'The uploaded X media is ready for a separately approved post.' if completed else 'The exact media step is saved; the durable queue owns the next step.'}


def verified_attachments(cur, workspace, connection, credential, ids, now):
    """Only completed uploads made by this account and consent generation can attach."""
    from . import x_direct_journal as journal
    if not isinstance(ids, (list, tuple)) or not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        _fail('Choose one to four distinct verified media items.', 'x_media_ownership_required')
    found = {}
    for rid in ids:
        if not valid_id(rid): _fail('Invalid uploaded media ID.', 'x_media_ownership_required')
        cur.execute('SELECT ' + journal.SELECT + ''' FROM public.pr_x_direct_operations
            WHERE workspace_id=%s AND connection_id=%s AND provider_account_id=%s
              AND authorization_generation=%s AND operation_id='media.upload' AND state='verified'
              AND progress#>>'{media,id}'=%s ORDER BY created_at DESC LIMIT 2''',
            (workspace, connection, credential['account'], credential['generation'], rid))
        rows = [journal.row_value(value) for value in cur.fetchall()]
        if len(rows) != 1: _fail('This media ID has no unique upload receipt for this account.', 'x_media_ownership_required')
        item = rows[0]; journal.assert_immutable(item)
        state = item['progress'].get('media') or {}
        source = asset_from_workspace(cur, workspace, item['request']['body'].get('asset_id'))
        alt = item['request']['body'].get('alt_text', '')
        fingerprint = _fingerprint(workspace, connection, credential['account'], source, alt)
        proof = next((r for r in reversed(item['receipts']) if r.get('mediaReady') is True and r.get('resourceId') == rid), None)
        if (state.get('stage') != 'ready' or state.get('planFingerprint') != fingerprint
                or item['request'].get('normalizedFingerprint') != fingerprint
                or state.get('authorizationGeneration') != credential['generation']
                or type(state.get('expiresAt')) not in (int, float) or state['expiresAt'] <= now + 30
                or not proof or proof.get('mediaKey') != state.get('mediaKey')
                or proof.get('requestFingerprint') != fingerprint or (alt and not state.get('altVerified'))):
            _fail('The uploaded media expired, changed or was reauthorized.', 'x_media_ownership_required')
        found[rid] = {'mediaKey': state['mediaKey'], 'expiresAt': state['expiresAt'], 'mime': source['mime'], 'altText': alt}
    if len(found) > 1 and any(row['mime'] not in ('image/jpeg', 'image/png') for row in found.values()):
        _fail('A video or animated GIF must be attached alone.', 'x_media_combination_invalid')
    return found
