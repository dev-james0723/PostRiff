from __future__ import annotations

import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

STATES = ('requested', 'dialing', 'ringing', 'answered', 'live', 'ending', 'completed', 'busy', 'declined', 'no_answer', 'voicemail', 'failed', 'ambiguous', 'cancelled')
TERMINAL = frozenset(('completed', 'busy', 'declined', 'no_answer', 'voicemail', 'failed', 'cancelled'))
CALL_EVENTS = frozenset(('publish.failed', 'publish.uncertain', 'campaign.approval_required', 'campaign.blocked', 'channel.reconnect_required'))
FLAGS = ('RAFII_PHONE_ENABLED', 'RAFII_PHONE_OUTBOUND_ENABLED', 'RAFII_PHONE_SCHEDULED_ENABLED', 'RAFII_PHONE_PROACTIVE_ENABLED', 'RAFII_PHONE_VERIFICATION_ENABLED')
DEFAULTS = {'enabled': False, 'proactiveCalls': False, 'scheduledCalls': False, 'quietStart': 1320, 'quietEnd': 480,
            'timeZone': 'UTC', 'maxCallsPerDay': 2, 'maxMilliCreditsPerCall': 0, 'eventAllowlist': [], 'fallbackToPush': True, 'fallbackToEmail': True}
GREETING = 'Hi, this is Rafii, your AI assistant.'


def phone_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
        raise AlphaError('Enter a phone number with its country code, such as +14155550123.', 400, code='phone_invalid')
    return value


def preferences(patch, current=None):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise AlphaError('Send valid phone preferences.', 400)
    out = {**DEFAULTS, **(current or {}), **patch}
    for key in ('enabled', 'proactiveCalls', 'scheduledCalls', 'fallbackToPush', 'fallbackToEmail'):
        if not isinstance(out[key], bool):
            raise AlphaError('Phone switches must be on or off.', 400)
    for key, low, high in (('quietStart', 0, 1439), ('quietEnd', 0, 1439), ('maxCallsPerDay', 1, 2), ('maxMilliCreditsPerCall', 0, 100_000_000)):
        if type(out[key]) is not int or not low <= out[key] <= high:
            raise AlphaError('Choose valid quiet hours and a daily limit of one or two calls.', 400)
    try:
        ZoneInfo(out['timeZone'])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise AlphaError('Choose a valid time zone.', 400) from None
    if not isinstance(out['eventAllowlist'], list) or any(v not in CALL_EVENTS for v in out['eventAllowlist']):
        raise AlphaError('Choose supported call events.', 400)
    out['eventAllowlist'] = sorted(set(out['eventAllowlist']))
    return out


@dataclass(frozen=True)
class ProviderEvent:
    event_id: str
    call_ref: str
    state: str
    duration_seconds: int | None = None


@dataclass(frozen=True)
class CallReceipt:
    state: str
    call_ref: str | None = None
    duration_seconds: int | None = None


def transition(current, incoming):
    if incoming not in STATES or current in TERMINAL:
        return current
    if incoming in TERMINAL:
        return incoming
    rank = {'requested': 0, 'dialing': 1, 'ambiguous': 1, 'ringing': 2, 'answered': 3, 'live': 4, 'ending': 5}
    return incoming if rank.get(incoming, -1) >= rank.get(current, -1) else current
