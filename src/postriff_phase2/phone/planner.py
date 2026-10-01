"""Pure deterministic policy. No model may grant phone egress."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ..notifications.planner import in_quiet_hours
from .contracts import CALL_EVENTS, FOUNDER_CALL_EVENTS, FOUNDER_REASON_PREFIX
from .rules import active_rule


def day_start(now, time_zone):
    local = datetime.fromtimestamp(now, ZoneInfo(time_zone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def founder_event(flags, event_type):
    """The founder call event a proactive request may use, or None (Founder Admin, CONTRACTS §5).

    `runtime.principal_phone(..., founder_reason_key=...)` attaches `flags['founder']` = {workspaceId, opsWorkspaceId,
    reasonKey} to exactly one founder-scoped PhoneService. PhoneService.request passes the explicit event
    ('founder.incident'); delivery.deliver passes the reason key's first segment ('founder'). Either is accepted only when
    the reason key carries the founder prefix and names a founder purpose, and the request targets the configured ops
    workspace. A customer request never carries this scope, and no preference allowlist can admit a founder event.
    """
    scope = flags.get('founder') if isinstance(flags, dict) else None
    if not isinstance(scope, dict):
        return None
    key, workspace, ops = scope.get('reasonKey'), scope.get('workspaceId'), scope.get('opsWorkspaceId')
    if not (isinstance(key, str) and key.startswith(FOUNDER_REASON_PREFIX) and workspace and ops and workspace == ops):
        return None
    parts = key.split(':')
    event = 'founder.' + parts[1] if len(parts) >= 3 and parts[2] else ''
    if event not in FOUNDER_CALL_EVENTS or event_type not in (event, FOUNDER_REASON_PREFIX.rstrip(':')):
        return None
    return event


def eligibility(kind, prefs, *, now, verified, membership, configured, live_configured, flags, event_type=None,
                daily_calls=0, recent_equivalent=False, active=False, reserved_cost=0, estimate=0, daily_budget=0, direction='outbound', custom_rule_ref=None):
    inbound = direction == 'inbound'
    checks = [(flags.get('RAFII_PHONE_ENABLED'), 'phone_disabled'),
              (flags.get('RAFII_PHONE_INBOUND_ENABLED' if inbound else 'RAFII_PHONE_OUTBOUND_ENABLED'), 'inbound_disabled' if inbound else 'outbound_disabled'),
              (verified, 'phone_unverified'), (inbound or prefs['enabled'], 'calling_off'), (membership, 'membership'),
              (configured, 'provider_unavailable'), (live_configured, 'live_unavailable'),
              (not active, 'call_active'), (kind == 'explicit' or not recent_equivalent, 'recent_equivalent'),
              (estimate > 0 and (kind == 'explicit' or reserved_cost + estimate <= daily_budget), 'phone_budget')]
    if kind != 'explicit':
        checks += [(not in_quiet_hours(now, {'quiet_start': prefs['quietStart'], 'quiet_end': prefs['quietEnd'], 'time_zone': prefs['timeZone']}), 'quiet_hours'),
                   (daily_calls < prefs['maxCallsPerDay'], 'daily_limit')]
    if kind == 'scheduled':
        checks += [(flags.get('RAFII_PHONE_SCHEDULED_ENABLED') and prefs['scheduledCalls'], 'scheduled_off')]
    elif kind == 'proactive':
        custom = active_rule(prefs, *custom_rule_ref) if custom_rule_ref else None
        founder = founder_event(flags, event_type)
        checks += [(flags.get('RAFII_PHONE_PROACTIVE_ENABLED') and prefs['proactiveCalls'], 'proactive_off'),
                   (founder is not None or (event_type in CALL_EVENTS and (bool(custom and custom['eventType'] == event_type) if custom_rule_ref else event_type in prefs['eventAllowlist'])), 'event_not_allowed')]
    elif kind != 'explicit':
        return 'kind_invalid'
    return next((reason for allowed, reason in checks if not allowed), None)
