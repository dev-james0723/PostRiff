"""Native poll reads and exact vote custody; no automatic vote or resubmission."""
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError
from .mastodon_protocol import has_scopes


MAX_OPTIONS = 64


def choices(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_OPTIONS
            or any(type(index) is not int or not 0 <= index < MAX_OPTIONS for index in value)
            or len(set(value)) != len(value)):
        raise AlphaError('Choose distinct Mastodon poll option indexes, starting at zero.', 400)
    return sorted(value)


def view(value, target):
    """Bound a single poll; missing/hidden totals remain unavailable, never zero."""
    if (not isinstance(value, dict) or value.get('id') != target
            or type(value.get('expired')) is not bool or type(value.get('multiple')) is not bool):
        raise AlphaError('Mastodon did not identify the exact poll and its current settings.', 502)
    options = value.get('options')
    if (not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS
            or any(not isinstance(option, dict) or not isinstance(option.get('title'), str)
                   or not 1 <= len(option['title'].strip()) <= 5000 for option in options)):
        raise AlphaError('The poll answers are unavailable or exceed the supported read bound.', 502)
    expiry = value.get('expires_at')
    if 'expires_at' not in value:
        raise AlphaError('Mastodon did not confirm the poll expiry.', 502)
    if expiry is not None:
        try:
            instant = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
            if instant.tzinfo is None:
                raise ValueError()
            expiry = instant.astimezone(timezone.utc).isoformat()
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise AlphaError('Mastodon returned an invalid poll expiry.', 502) from None
    def count(number):
        return number if type(number) is int and 0 <= number <= 2**53 - 1 else None
    own = value.get('own_votes')
    if (not isinstance(own, list) or len(own) > len(options)
            or any(type(index) is not int or not 0 <= index < len(options) for index in own)
            or len(set(own)) != len(own)):
        own = None
    return {'id': target, 'expiresAt': expiry, 'expired': value['expired'], 'multiple': value['multiple'],
            'voted': value.get('voted') if type(value.get('voted')) is bool else None,
            'ownVotes': sorted(own) if own is not None else None,
            'votesCount': count(value.get('votes_count')), 'votersCount': count(value.get('voters_count')),
            'options': [{'index': index, 'title': option['title'], 'votes': count(option.get('votes_count'))}
                        for index, option in enumerate(options)]}


def snapshot(poll):
    # Counts and other people's votes change normally and do not change the exact
    # option meaning, order or voting rules the person approved.
    return {key: poll[key] for key in ('id', 'expiresAt', 'multiple')} | {
        'options': [{'index': option['index'], 'title': option['title']} for option in poll['options']]}


def vote_binding(value, target, selected, now):
    poll = view(value, target)
    selected = choices(selected)
    if (poll['expired'] or poll['expiresAt'] is not None
            and datetime.fromisoformat(poll['expiresAt']).timestamp() <= now):
        raise AlphaError('This Mastodon poll has ended. No vote was sent.', 409)
    if poll['voted'] is not False:
        raise AlphaError('Mastodon could not confirm this account has not already voted. No vote was sent.', 409)
    if any(index >= len(poll['options']) for index in selected) or not poll['multiple'] and len(selected) != 1:
        raise AlphaError('Choose the supported number of answers from this exact poll.', 400)
    return snapshot(poll)


def vote_readback(provider, session, preview, response, granted_scopes):
    target = preview['targetId']
    body = response.get('body')
    if not isinstance(body, dict) or body.get('id') != target:
        return {'state': 'uncertain', 'reason': 'The vote response did not identify the approved poll. Check Mastodon; do not resend.'}
    evidence = {'state': 'unavailable', 'targetId': target, 'requiredScope': 'read:statuses'}
    result = {'verification': 'unavailable', 'readback': evidence,
              'reason': 'Mastodon accepted the vote; the selected answers could not be independently confirmed. Do not resend.'}
    if not has_scopes(granted_scopes, ('read:statuses',)):
        evidence['state'] = 'permission_required'
        return result
    try:
        checked = provider.api(session, 'GET', '/api/v1/polls/' + target)
        if not isinstance(checked, dict):
            return result
        if type(checked.get('status')) is int:
            evidence['httpStatus'] = checked['status']
        if checked.get('status') != 200:
            return result
        poll = view(checked.get('body'), target)
    except (AlphaError, OSError, TimeoutError):
        return result
    if (snapshot(poll) == preview.get('pollSnapshot') and poll['voted'] is True
            and poll['ownVotes'] == preview['body']['choices']):
        evidence.update(state='confirmed', ownVotes=poll['ownVotes'])
        result.update(state='verified', verification='provider_poll_lookup',
                      reason='Mastodon independently confirmed this account voted for the exact approved poll answers.')
    else:
        evidence['state'] = 'unconfirmed'
    return result
