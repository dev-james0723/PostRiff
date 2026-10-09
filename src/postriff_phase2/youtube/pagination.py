"""Bounded projections of local YouTube plans; never returns internal authority leases."""
import base64
import copy
import json
import math
import re

from postriff_alpha.domain import AlphaError
from ..contracts import digest

DRAFT_PUBLIC = ('id', 'digest', 'connectionId', 'channelId', 'assetId', 'variantId', 'status',
                'uploadWorkflow', 'uploadAt', 'timing', 'publishOptions', 'recommendations', 'jobId',
                'approvalMode', 'createdAt')
POLICY_PUBLIC = ('id', 'digest', 'channelId', 'status', 'drafts', 'assetIds', 'timeZone', 'startsAt',
                 'endsAt', 'maxDaily', 'intervention', 'createdAt')


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def projection(record, kind, now):
    fields = DRAFT_PUBLIC if kind == 'draft' else POLICY_PUBLIC
    value = {key: copy.deepcopy(record[key]) for key in fields if key in record}
    if kind == 'draft':
        origin = record.get('metadataOrigin')
        if origin in ('user_or_filename_suggestion', 'chat_model_proposal_requires_video_review'):
            value['metadataOrigin'] = origin
        timing = record.get('timing')
        at = timing.get('timestamp') if isinstance(timing, dict) else None
        value['readOnly'] = record.get('status') != 'proposed' or not finite(at) or at <= now
    else:
        end = record.get('endsAt')
        if record.get('status') in ('prepared', 'active', 'paused') and finite(end) and end <= now:
            value['status'] = 'expired'
    return value


def live_page(records, workspace, connection, kind, now, *, limit=25, cursor=None):
    if kind not in ('draft', 'policy'):
        raise AlphaError('YouTube history kind unavailable.', 404)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise AlphaError('Choose a page size between 1 and 50.', 400, code='youtube_agent_page_limit')
    items = [item for item in records if isinstance(item, dict) and item.get('connectionId') == connection
             and isinstance(item.get('id'), str)]
    def key(item):
        at = item.get('createdAt')
        return (at if finite(at) else 0, item['id'])
    items.sort(key=key, reverse=True)
    scope = digest({'workspace': workspace, 'connection': connection, 'kind': kind})
    offset = 0
    if cursor is not None:
        invalid = AlphaError('This publishing page changed. Reload its first page.', 400, code='youtube_agent_page_cursor')
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048 or not re.fullmatch(r'[A-Za-z0-9_-]+', cursor):
            raise invalid
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        except (ValueError, UnicodeError):
            raise invalid from None
        if (not isinstance(value, dict) or set(value) != {'v', 'scope', 'id', 'at', 'digest'}
                or type(value['v']) is not int or value['v'] != 1 or value['scope'] != scope):
            raise invalid
        anchors = [index for index, item in enumerate(items) if item['id'] == value['id']
                   and key(item)[0] == value['at'] and digest(item) == value['digest']]
        if len(anchors) != 1:
            raise invalid
        offset = anchors[0] + 1
    chosen = items[offset:offset + limit]
    more = len(items) > offset + limit
    next_cursor = None
    if chosen and more:
        last = chosen[-1]
        value = {'v': 1, 'scope': scope, 'id': last['id'], 'at': key(last)[0], 'digest': digest(last)}
        next_cursor = base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
    return {'items': [projection(item, kind, now) for item in chosen], 'nextCursor': next_cursor, 'hasMore': more}
