"""Bounded independent state proof for accepted Mastodon account interactions.

The write response acknowledges an operation. Only a separate authenticated GET
can confirm its current state. A missing permission or failed lookup never retries
the mutation or converts server acceptance into a verified outcome.
"""
from postriff_alpha.domain import AlphaError
from .mastodon_protocol import ID, has_scopes


STATUS_FIELDS = {
    'favourite': {'favourited': True}, 'unfavourite': {'favourited': False},
    'reblog': {'reblogged': True}, 'unreblog': {'reblogged': False},
    'bookmark': {'bookmarked': True}, 'unbookmark': {'bookmarked': False},
}
RELATIONSHIP_FIELDS = {
    'follow': {'following': True, 'requested': False},
    'unfollow': {'following': False, 'requested': False},
    'mute': {'muting': True}, 'unmute': {'muting': False},
    'block': {'blocking': True}, 'unblock': {'blocking': False},
}


def readback(provider, session, preview, granted_scopes):
    """Return only the requested boolean state; discard status bodies/private notes."""
    action, target = preview['action'], preview.get('targetId')
    status_action = action in STATUS_FIELDS
    fields = (STATUS_FIELDS if status_action else RELATIONSHIP_FIELDS)[action]
    scope = 'read:statuses' if status_action else 'read:follows'
    evidence = {'state': 'unavailable', 'targetId': target, 'requiredScope': scope}
    result = {'verification': 'unavailable', 'readback': evidence,
              'reason': 'Mastodon accepted the action; its current state could not be independently confirmed. Check Mastodon before preparing another action.'}
    # The current encrypted grant was checked and locked before dispatch. Do not
    # infer GET permission from the corresponding write scope or a public status.
    if not has_scopes(granted_scopes, (scope,)):
        evidence['state'] = 'permission_required'
        result['reason'] = 'Mastodon accepted the action. Independent confirmation requires reconnecting with ' + scope + '.'
        return result
    if not isinstance(target, str) or not ID.fullmatch(target):
        return result
    path = ('/api/v1/statuses/' + target if status_action else
            '/api/v1/accounts/relationships?id%5B%5D=' + target)
    try:
        response = provider.api(session, 'GET', path)
    except (AlphaError, OSError, TimeoutError):
        return result
    if not isinstance(response, dict):
        return result
    if type(response.get('status')) is int:
        evidence['httpStatus'] = response['status']
    if response.get('status') != 200:
        if response.get('status') == 429:
            result['reason'] = 'Mastodon accepted the action, but rate limited its confirmation. No action was resent.'
        return result
    value = response.get('body')
    if not status_action:
        # A query for one account must identify exactly that account once.
        value = value[0] if isinstance(value, list) and len(value) == 1 else None
    if not isinstance(value, dict) or value.get('id') != target:
        return result
    if any(type(value.get(field)) is not bool for field in fields):
        return result
    evidence['observed'] = {field: value[field] for field in fields}
    if action == 'follow' and value['following'] is False and value['requested'] is True:
        evidence['state'] = 'pending'
        result.update(followRequestPending=True,
                      reason='Mastodon accepted a follow request. The target account has not approved it yet.')
    elif evidence['observed'] == fields:
        evidence['state'] = 'confirmed'
        result.update(state='verified',
                      verification='provider_status_lookup' if status_action else 'provider_relationship_lookup',
                      reason='Mastodon confirmed the approved interaction state with a separate account-authorized read.')
    else:
        evidence['state'] = 'unconfirmed'
        result['reason'] = 'Mastodon accepted the action, but a separate read did not confirm the approved state. No action was resent.'
    return result
