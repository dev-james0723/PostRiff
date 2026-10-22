"""Mastodon replies for the Inbox: public replies to an owned status, and one approved reply back.

Reads use the status context (the replies the account can see); only public or unlisted replies without a
content warning or sensitive flag are kept, so private mentions never reach the Inbox. A reply is one status with
in_reply_to_id, sent with an Idempotency-Key bound to the approved draft and read back before it is verified.
"""
import html
import re
from urllib.parse import quote

ID = re.compile(r'^[0-9]{1,40}$')
DESCENDANT_LIMIT = 80


def plain(content):
    text = re.sub(r'<br\s*/?>|</p>\s*<p>', '\n', str(content or ''))
    return html.unescape(re.sub(r'<[^>]+>', '', text)).strip()


def replies(adapter, access_token, post_id, provider_account_id):
    """(ok, [{id, author, text, createdAt}]) for other people's public replies under post_id; never raises for provider answers."""
    if not ID.fullmatch(str(post_id)):
        return False, []
    session = adapter.session(access_token)
    response = adapter.api(session, 'GET', f'/api/v1/statuses/{quote(str(post_id))}/context')
    body = response.get('body') if isinstance(response.get('body'), dict) else {}
    if response.get('status') != 200 or not isinstance(body.get('descendants'), list):
        return False, []
    items = []
    for status in body['descendants'][:DESCENDANT_LIMIT]:
        if not isinstance(status, dict) or not ID.fullmatch(str(status.get('id', ''))):
            continue
        if status.get('visibility') not in ('public', 'unlisted') or status.get('sensitive') or status.get('spoiler_text'):
            continue
        account = status.get('account') if isinstance(status.get('account'), dict) else {}
        acct = account.get('acct') if isinstance(account.get('acct'), str) else ''
        if not acct or str(account.get('id', '')) + '@' + session['instance'] == provider_account_id:
            continue
        items.append({'id': str(status['id']), 'author': acct if '@' in acct else f"{acct}@{session['instance']}",
                      'text': plain(status.get('content')), 'createdAt': status.get('created_at')})
    return True, items


MENTION_LIMIT = 40


def mentions(adapter, access_token, provider_account_id):
    """(ok, [{id, postId, author, text, createdAt}]) for public replies to any of the account's own posts, read from its
    mention notifications. Private mentions and replies to other people's posts are never kept."""
    session = adapter.session(access_token)
    own_id = str(provider_account_id).split('@', 1)[0]
    response = adapter.api(session, 'GET', f'/api/v1/notifications?types[]=mention&limit={MENTION_LIMIT}')
    rows = response.get('body')
    if response.get('status') != 200 or not isinstance(rows, list):
        return False, []
    items = []
    for row in rows[:MENTION_LIMIT]:
        status = row.get('status') if isinstance(row, dict) and isinstance(row.get('status'), dict) else {}
        post_id = str(status.get('in_reply_to_id') or '')
        if (row.get('type') != 'mention' or not ID.fullmatch(str(status.get('id', ''))) or not ID.fullmatch(post_id)
                or str(status.get('in_reply_to_account_id') or '') != own_id
                or status.get('visibility') not in ('public', 'unlisted') or status.get('sensitive') or status.get('spoiler_text')):
            continue
        account = status.get('account') if isinstance(status.get('account'), dict) else {}
        acct = account.get('acct') if isinstance(account.get('acct'), str) else ''
        if not acct or str(account.get('id', '')) == own_id:
            continue
        items.append({'id': str(status['id']), 'postId': post_id, 'author': acct if '@' in acct else f"{acct}@{session['instance']}",
                      'text': plain(status.get('content')), 'createdAt': status.get('created_at')})
    return True, items


def addressed(text, author):
    """The exact text to approve: Mastodon notifies the person replied to only when they are mentioned."""
    mention = '@' + author
    return text if mention.casefold() in text.casefold() else f'{mention} {text}'


def send(adapter, access_token, reply_to_id, text, idempotency_key, provider_account_id):
    """One reply; the outcome is verified only when a read-back matches the account, parent and text."""
    session = adapter.session(access_token)
    sent = adapter.api(session, 'POST', '/api/v1/statuses', headers={'Idempotency-Key': idempotency_key[:64]},
                       body={'status': text, 'in_reply_to_id': str(reply_to_id), 'visibility': 'public'})
    body = sent.get('body') if isinstance(sent.get('body'), dict) else {}
    reply_id = str(body.get('id', ''))
    if sent.get('status') in (401, 403):
        return {'state': 'failed', 'confirmed': 'Mastodon rejected the reply permission; reconnect and approve again.'}
    if sent.get('status') != 200 or not ID.fullmatch(reply_id):
        return {'state': 'uncertain', 'confirmed': 'Mastodon reply response was inconclusive; do not resend.'}
    check = adapter.api(session, 'GET', '/api/v1/statuses/' + quote(reply_id))
    status = check.get('body') if isinstance(check.get('body'), dict) else {}
    account = str((status.get('account') or {}).get('id', '')) + '@' + session['instance']
    # Mastodon renders a same-server mention as @name; matches_text binds it to the status's reported mention identities.
    from .mastodon_status_text import matches_text
    from .mastodon_threads import plain_content
    if (check.get('status') == 200 and account == provider_account_id and str(status.get('in_reply_to_id')) == str(reply_to_id)
            and matches_text(status, text, session['instance'], plain_content)):
        return {'state': 'verified', 'reference': reply_id, 'confirmed': 'Mastodon read-back matched the approved reply.'}
    return {'state': 'submitted', 'reference': reply_id, 'confirmed': 'Mastodon accepted the reply; read-back did not match yet.'}
