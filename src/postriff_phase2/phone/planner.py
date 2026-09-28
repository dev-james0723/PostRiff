"""Pure deterministic policy. No model may grant phone egress."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ..notifications.planner import in_quiet_hours
from .contracts import CALL_EVENTS


def day_start(now, time_zone):
    local = datetime.fromtimestamp(now, ZoneInfo(time_zone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def eligibility(kind, prefs, *, now, verified, membership, configured, live_configured, flags, event_type=None,
                daily_calls=0, recent_equivalent=False, active=False, reserved_cost=0, estimate=0, daily_budget=0, direction='outbound'):
    inbound = direction == 'inbound'
    checks = [(flags.get('RAFII_PHONE_ENABLED'), 'phone_disabled'),
              (flags.get('RAFII_PHONE_INBOUND_ENABLED' if inbound else 'RAFII_PHONE_OUTBOUND_ENABLED'), 'inbound_disabled' if inbound else 'outbound_disabled'),
              (verified, 'phone_unverified'), (inbound or prefs['enabled'], 'calling_off'), (membership, 'membership'),
              (configured, 'provider_unavailable'), (live_configured, 'live_unavailable'),
              (not active, 'call_active'), (kind == 'explicit' or not recent_equivalent, 'recent_equivalent'),
              (estimate > 0 and reserved_cost + estimate <= daily_budget, 'phone_budget')]
    if kind != 'explicit':
        checks += [(not in_quiet_hours(now, {'quiet_start': prefs['quietStart'], 'quiet_end': prefs['quietEnd'], 'time_zone': prefs['timeZone']}), 'quiet_hours'),
                   (daily_calls < prefs['maxCallsPerDay'], 'daily_limit')]
    if kind == 'scheduled':
        checks += [(flags.get('RAFII_PHONE_SCHEDULED_ENABLED') and prefs['scheduledCalls'], 'scheduled_off')]
    elif kind == 'proactive':
        checks += [(flags.get('RAFII_PHONE_PROACTIVE_ENABLED') and prefs['proactiveCalls'], 'proactive_off'),
                   (event_type in CALL_EVENTS and event_type in prefs['eventAllowlist'], 'event_not_allowed')]
    elif kind != 'explicit':
        return 'kind_invalid'
    return next((reason for allowed, reason in checks if not allowed), None)
