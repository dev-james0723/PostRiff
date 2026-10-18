"""Public thread excerpts and Rafii paging over one bounded instance response.

Mastodon's context endpoint has no documented paging query. Cursors below page
our filtered snapshot only; a changed snapshot requires restarting the read.
"""
import hashlib
import json
import re

from postriff_alpha.domain import AlphaError
from .mastodon_protocol import ID
from .mastodon_threads import plain_content

CURSOR = re.compile(r'[a-f0-9]{64}:[0-9]{1,3}\Z')
SIDE_LIMIT, PAGE_SIZE, PAGE_BYTES = 100, 20, 9000


def checked_cursor(value):
    if value is None:
        return None, 0
    if not isinstance(value, str) or not CURSOR.fullmatch(value):
        raise AlphaError('Choose a valid Rafii thread context cursor.', 400)
    digest, offset = value.split(':')
    if not 0 <= int(offset) < SIDE_LIMIT * 2:
        raise AlphaError('Thread context cursor exceeds the bounded snapshot.', 400)
    return digest, int(offset)


def public_excerpt(value, relation):
    if (not isinstance(value, dict) or value.get('visibility') not in ('public', 'unlisted')
            or value.get('sensitive') is not False or value.get('spoiler_text') or value.get('reblog')):
        return None
    account = value.get('account')
    identifier = str(value.get('id', ''))
    author = str(account.get('id', '')) if isinstance(account, dict) else ''
    if not ID.fullmatch(identifier) or not ID.fullmatch(author) or not isinstance(value.get('content'), str):
        return None
    return {'postId': identifier, 'authorId': author, 'relation': relation,
            'visibility': value['visibility'], 'excerpt': plain_content(value['content'][:64000])[:1000],
            'replyToId': value.get('in_reply_to_id') if isinstance(value.get('in_reply_to_id'), str)
                         and ID.fullmatch(value['in_reply_to_id']) else None}


def page(target, context, cursor=None, *, binding=None):
    expected, offset = checked_cursor(cursor)
    root = public_excerpt(target, 'target')
    if root is None:
        raise AlphaError('Public thread context is unavailable for this status.', 403)
    if (not isinstance(context, dict) or any(not isinstance(context.get(k), list)
            or len(context[k]) > 4096 for k in ('ancestors', 'descendants'))):
        raise AlphaError('Mastodon returned invalid thread context.', 502)
    rows, seen = [], {root['postId']}
    for key, relation in (('ancestors', 'ancestor'), ('descendants', 'descendant')):
        for raw in context[key][:SIDE_LIMIT]:
            projected = public_excerpt(raw, relation)
            if projected is not None and projected['postId'] not in seen:
                seen.add(projected['postId'])
                rows.append(projected)
    fingerprint = hashlib.sha256(json.dumps([binding, root, rows], sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=False).encode()).hexdigest()
    if expected is not None and expected != fingerprint:
        raise AlphaError('This thread snapshot changed. Read the first page again.', 409,
                         code='mastodon_context_snapshot_changed')
    if offset > len(rows):
        raise AlphaError('Thread context cursor exceeds the current snapshot.', 400)
    posts, used = [], 0
    for item in rows[offset:offset + PAGE_SIZE]:
        size = len(json.dumps(item, ensure_ascii=False).encode()) + 2
        if used + size > PAGE_BYTES:
            break
        posts.append(item)
        used += size
    next_offset = offset + len(posts)
    return {'target': root, 'posts': posts, 'snapshot': fingerprint,
            'nextCursor': f'{fingerprint}:{next_offset}' if next_offset < len(rows) else None,
            'truncated': any(len(context[k]) > SIDE_LIMIT for k in ('ancestors', 'descendants')),
            'pagination': 'Rafii filtered snapshot pages; Mastodon context has no native paging cursor.',
            'coverage': 'At most 100 ancestors and 100 descendants scanned from this instance response; '
                        '20 excerpts and 9000 serialized excerpt bytes per page, plus the target. '
                        'Private, unknown visibility, CW and sensitive content omitted. Not complete federation coverage.'}
