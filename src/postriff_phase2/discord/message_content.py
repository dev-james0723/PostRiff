"""Optional broader-content gate. Server policy AND fresh Discord evidence required.

This never enables an intent, edits the app or consumes a user-supplied proof.
The current deployment has no such evidence, so limited mode stays the default.
"""
import json
import math
import re

from postriff_alpha.domain import AlphaError
from .authorization import digest, snowflake

SCHEMA = 'rafii.discord.message-content-evidence.v1'
MODES = ('mentions_only', 'approved_content')
FLAGS = (1 << 18) | (1 << 19)


def deny():
    raise AlphaError('Broader Discord content needs a current app-specific approval record, live Message Content Intent access and your separate channel consent.',
                     409, code='discord_message_content_approval_required')


def policy(provider, now):
    raw = getattr(provider, 'message_content_evidence_raw', None)
    try:
        data = json.loads(raw) if isinstance(raw, str) and len(raw) <= 4096 else raw
        if (not isinstance(data, dict) or set(data) != {'schema', 'applicationId', 'botUserId', 'permission',
                'reviewStatus', 'reviewReference', 'approvedBy', 'issuedAt', 'expiresAt'}
                or data['schema'] != SCHEMA or data['applicationId'] != provider.client_id
                or not snowflake(data['applicationId']) or not snowflake(data['botUserId'])
                or data['permission'] != 'MESSAGE_CONTENT' or data['reviewStatus'] not in ('approved', 'not_required')
                or any(not isinstance(data[k], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{3,160}', data[k])
                       for k in ('reviewReference', 'approvedBy'))
                or any(type(data[k]) not in (int, float) or not math.isfinite(data[k]) for k in ('issuedAt', 'expiresAt'))
                or not 0 <= data['issuedAt'] <= now < data['expiresAt'] <= data['issuedAt'] + 30 * 86400):
            return None
        return data
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


def assert_binding(provider, target, consent, now):
    if consent.get('contentAccess', 'mentions_only') == 'mentions_only':
        return None
    evidence = policy(provider, now)
    if (consent.get('contentAccess') != 'approved_content' or not evidence
            or evidence['botUserId'] != target['botUserId'] or evidence['applicationId'] != target['applicationId']
            or consent.get('contentEvidenceDigest') != digest(evidence)):
        deny()
    return evidence


def verify(provider, target, consent, authorize, now):
    evidence = assert_binding(provider, target, consent, now)
    if evidence is None:
        return False
    if not callable(authorize) or authorize() is not True:
        deny()
    body = provider._json(provider._bot('GET', '/oauth2/applications/@me', read_authorize=authorize), dict)
    # Discord documents legacy numeric flags and full-width string flags_new.
    # When both are present they must agree; an ON field cannot override a
    # contradictory OFF field in either direction.
    observed = []
    for key in ('flags', 'flags_new'):
        if key not in body:
            continue
        value = body[key]
        if key == 'flags_new' and isinstance(value, str) and re.fullmatch(r'[0-9]{1,20}', value):
            value = int(value)
        if type(value) is not int or not 0 <= value < 1 << 64:
            deny()
        observed.append(value)
    if (body.get('id') != target['applicationId'] or not observed or len(set(observed)) != 1
            or not observed[0] & FLAGS or authorize() is not True):
        deny()
    return True
