"""Small, deterministic vocabulary for owner-reviewed proactive phone rules.

Free text is never executable policy. Unsupported conditions fail closed instead
of being approximated by a broader event trigger.
"""
from __future__ import annotations

import hashlib
import re
import uuid

from postriff_alpha.domain import AlphaError

MAX_RULES = 5
MAX_WHEN = 240
MAX_DISCUSS = 500
WINDOW_HOURS = 24


def compile_when(value):
    if not isinstance(value, str) or not 8 <= len(value.strip()) <= MAX_WHEN:
        raise AlphaError('Describe when Rafii should call in 8–240 characters.', 400, code='phone_rule_invalid')
    text = value.strip().lower().rstrip('.!? ').replace('’', "'")
    text = re.sub(r'^(?:please )?(?:have rafii )?call me (?:when|if) ', '', text)
    text = re.sub(r'^(?:when|if) ', '', text)
    count = re.fullmatch(
        r'(?:(?:a|any|my) )?(?:(scheduled )?post|publication|publishing) (?:fails|failed)'
        r'(?: (twice|2 times|three times|3 times) (?:in|within) (?:one day|a day|24 hours))?', text)
    if count:
        threshold = 2 if count[2] in ('twice', '2 times') else 3 if count[2] else 1
        return {'eventType': 'publish.failed', 'countAtLeast': threshold, 'windowHours': WINDOW_HOURS,
                'sameEntity': bool(count[1] and threshold > 1)}
    phrases = {
        'publish.uncertain': (r'(?:a |any |my )?(?:post|publication|publishing) (?:is |has an? )?(?:uncertain|unknown)(?: outcome)?',
                              r'(?:the )?publication outcome is uncertain'),
        'campaign.approval_required': (r'(?:an? |my )?approval is due within 24 hours',
                                       r'(?:an? |my )?approval is blocking a deadline'),
        'campaign.blocked': (r'(?:a |any |my )?campaign is blocked',),
        'channel.reconnect_required': (r'(?:a |any |my )?(?:channel|account|connection) (?:needs? reconnecting|needs? reconnection|is disconnected)',),
    }
    for event_type, patterns in phrases.items():
        if any(re.fullmatch(pattern, text) for pattern in patterns):
            return {'eventType': event_type, 'countAtLeast': 1, 'windowHours': WINDOW_HOURS, 'sameEntity': False}
    raise AlphaError('This situation is not supported yet. Use one of the examples shown below.', 400, code='phone_rule_unsupported')


def normalize(raw, previous=None):
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        raise AlphaError('Save up to five custom call situations.', 400, code='phone_rules_invalid')
    before = {r['id']: r for r in (previous or []) if isinstance(r, dict) and isinstance(r.get('id'), str)}
    seen, out = set(), []
    for item in raw:
        if not isinstance(item, dict) or set(item) - {'id', 'when', 'discuss', 'enabled', 'eventType', 'countAtLeast', 'windowHours', 'sameEntity', 'version'}:
            raise AlphaError('Send a valid custom call situation.', 400, code='phone_rule_invalid')
        try:
            rule_id = str(uuid.UUID(item.get('id', '')))
        except (ValueError, TypeError, AttributeError):
            raise AlphaError('Send a valid custom call situation ID.', 400, code='phone_rule_invalid') from None
        if rule_id in seen:
            raise AlphaError('Each custom call situation needs a unique ID.', 400, code='phone_rule_invalid')
        seen.add(rule_id)
        when, discuss = item.get('when'), item.get('discuss')
        compiled = compile_when(when)
        if not isinstance(discuss, str) or not 3 <= len(discuss.strip()) <= MAX_DISCUSS:
            raise AlphaError('Describe what Rafii should discuss in 3–500 characters.', 400, code='phone_rule_invalid')
        if type(item.get('enabled')) is not bool:
            raise AlphaError('Review and enable each call situation explicitly.', 400, code='phone_rule_invalid')
        when, discuss = when.strip(), discuss.strip()
        version = hashlib.sha256((when + '\0' + discuss).encode()).hexdigest()[:16]
        prior = before.get(rule_id)
        # First save or any edit produces an inactive review card. A second,
        # unchanged save may activate it after the user has seen the preview.
        enabled = item['enabled'] and bool(prior and prior.get('version') == version)
        out.append({'id': rule_id, 'when': when, 'discuss': discuss, 'enabled': enabled,
                    'version': version, **compiled})
    return out


def active_rule(prefs, rule_id, version):
    return next((rule for rule in prefs.get('customRules', [])
                 if rule.get('id') == rule_id and rule.get('version') == version and rule.get('enabled')), None)


def reason_ref(reason_key):
    match = re.match(r'^[a-z.]+:rule:([0-9a-f-]{36}):([0-9a-f]{16}):', reason_key or '')
    return (match[1], match[2]) if match else None


def reason_key(event_type, rule, group):
    return f"{event_type}:rule:{rule['id']}:{rule['version']}:{group[:80]}"[:200]


def matching(cur, prefs, principal, workspace_id, event_type, entity_id, now):
    for rule in prefs.get('customRules', []):
        if not rule.get('enabled') or rule.get('eventType') != event_type:
            continue
        # Keep the cooldown across edits and re-approval of the same rule ID.
        ref = f"{event_type}:rule:{rule['id']}:"
        cur.execute('SELECT 1 FROM public.pr_phone_calls WHERE user_id=%s AND workspace_id=%s '
                    'AND left(reason_key,length(%s))=%s AND requested_at>to_timestamp(%s) LIMIT 1',
                    (principal, workspace_id, ref, ref, now - 24 * 3600))
        if cur.fetchone():
            continue
        if rule['countAtLeast'] > 1:
            if rule['sameEntity'] and not entity_id:
                continue
            cur.execute('SELECT count(*) FROM public.pr_notification_events WHERE workspace_id=%s AND event_type=%s '
                        'AND occurred_at>=to_timestamp(%s) AND occurred_at<=to_timestamp(%s) '
                        'AND (%s::boolean=false OR entity_id=%s)',
                        (workspace_id, event_type, now - rule['windowHours'] * 3600, now,
                         rule['sameEntity'], str(entity_id) if entity_id is not None else None))
            if int(cur.fetchone()[0]) < rule['countAtLeast']:
                continue
        return rule
    return None
