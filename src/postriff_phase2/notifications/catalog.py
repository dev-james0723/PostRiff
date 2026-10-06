"""The notification event catalogue (adaptive coworker spec §15). Deterministic, versioned, and the only place
where urgency, default channels, recipients and transactional status are decided. A model may phrase a summary;
it never chooses any of these.

Defaults follow the spec: failures, uncertain publishing, approval blockers, security, reconnects and billing
failures are immediate; successful publication and other routine success go to the in-app centre and the digest,
never one email per post; weekly content ready is push + email + in-app; low-confidence opportunities and
preference proposals are digest or in-app only.
"""
from __future__ import annotations

CATALOG_VERSION = "2026-09-26.2"
CATEGORIES = ("approvals", "publishing", "weekly", "automation", "channels", "engagement", "opportunities", "analytics", "learning",
              "budget", "billing", "security", "research", "assets", "campaigns")
# Who receives an event, by the permission class a member must hold (permissions.CLASSES). "actor" = the person the
# event is about (security); "owner" = owners only.
AUDIENCES = ("approve", "edit", "manage_connections", "reply", "owner", "actor", "read")

# channel defaults: in_app always on unless listed False; email/push: "immediate" | "digest" | "off".
EVENTS = {
    'security.phone_call': {'category':'security','severity':'security','audience':'actor','email':'off','push':'immediate','template':'phone_call_verify','transactional':True},
    'phone.call_failed': {'category':'automation','severity':'warning','audience':'actor','email':'immediate','push':'immediate','template':'phone_call_failed'},
    'james.daily_call_fallback': {'category':'automation','severity':'warning','audience':'actor','email':'off','push':'immediate','template':'phone_call_failed'},
    "weekly_proof.generated": {"category": "analytics", "severity": "info", "audience": "owner", "email": "digest", "push": "immediate", "template": "weekly_performance"},
    "monthly_proof.generated": {"category": "analytics", "severity": "info", "audience": "owner", "email": "digest", "push": "off", "template": "weekly_performance"},
    "campaign.week_ready": {"category": "weekly", "severity": "action", "audience": "edit", "email": "immediate", "push": "immediate", "template": "weekly_ready"},
    "campaign.drafts_ready": {"category": "campaigns", "severity": "action", "audience": "edit", "email": "digest", "push": "off", "template": "drafts_ready"},
    "campaign.approval_required": {"category": "approvals", "severity": "action", "audience": "approve", "email": "immediate", "push": "immediate", "template": "approval_required"},
    "campaign.blocked": {"category": "campaigns", "severity": "warning", "audience": "edit", "email": "immediate", "push": "off", "template": "campaign_blocked"},
    "research.needs_input": {"category": "research", "severity": "action", "audience": "edit", "email": "digest", "push": "off", "template": "needs_input"},
    "asset.review_required": {"category": "assets", "severity": "action", "audience": "edit", "email": "digest", "push": "off", "template": "asset_review"},
    "publish.scheduled": {"category": "publishing", "severity": "info", "audience": "approve", "email": "off", "push": "off", "template": "publish_scheduled"},
    "publish.verified": {"category": "publishing", "severity": "info", "audience": "approve", "email": "digest", "push": "off", "template": "publish_verified"},
    "publish.failed": {"category": "publishing", "severity": "critical", "audience": "approve", "email": "immediate", "push": "immediate", "template": "publish_failed"},
    "publish.uncertain": {"category": "publishing", "severity": "critical", "audience": "approve", "email": "immediate", "push": "immediate", "template": "publish_uncertain"},
    "automation.completed": {"category": "automation", "severity": "info", "audience": "edit", "email": "digest", "push": "off", "template": "automation_completed"},
    "automation.failed": {"category": "automation", "severity": "warning", "audience": "edit", "email": "immediate", "push": "off", "template": "automation_failed"},
    "channel.reconnect_required": {"category": "channels", "severity": "critical", "audience": "manage_connections", "email": "immediate", "push": "immediate", "template": "channel_reconnect"},
    "engagement.needs_attention": {"category": "engagement", "severity": "action", "audience": "reply", "email": "digest", "push": "off", "template": "engagement"},
    "opportunity.detected": {"category": "opportunities", "severity": "info", "audience": "edit", "email": "digest", "push": "off", "template": "opportunity"},
    "analytics.weekly_ready": {"category": "analytics", "severity": "info", "audience": "edit", "email": "immediate", "push": "off", "template": "weekly_performance"},
    "analytics.anomaly_detected": {"category": "analytics", "severity": "warning", "audience": "edit", "email": "digest", "push": "off", "template": "analytics_anomaly"},
    "learning.preference_proposed": {"category": "learning", "severity": "info", "audience": "owner", "email": "digest", "push": "off", "template": "preference_proposed"},
    "budget.threshold_reached": {"category": "budget", "severity": "warning", "audience": "owner", "email": "immediate", "push": "off", "template": "budget_threshold"},
    "billing.payment_failed": {"category": "billing", "severity": "critical", "audience": "owner", "email": "immediate", "push": "immediate", "template": "payment_failed", "transactional": True},
    "billing.trial_ending": {"category": "billing", "severity": "action", "audience": "owner", "email": "immediate", "push": "off", "template": "trial_ending", "transactional": True},
    "billing.subscription_active": {"category": "billing", "severity": "info", "audience": "owner", "email": "immediate", "push": "off", "template": "subscription_active", "transactional": True},
    "security.new_device": {"category": "security", "severity": "security", "audience": "actor", "email": "immediate", "push": "off", "template": "security_alert", "transactional": True},
    "security.account_change": {"category": "security", "severity": "security", "audience": "actor", "email": "immediate", "push": "off", "template": "security_alert", "transactional": True},
}
# Explicit SMS eligibility is never inferred from severity. Security also requires separate consent.
_SMS = {'publish.failed', 'publish.uncertain', 'channel.reconnect_required', 'campaign.approval_required',
        'billing.payment_failed', 'security.account_change'}
for _event, _item in EVENTS.items():
    _item['sms'] = 'escalate' if _event in _SMS else 'off'

# Severity that may interrupt through quiet hours (push is deferred for everything else; email too for info/action).
BREAKS_QUIET_HOURS = ("security",)
# Per person per hour: beyond this an interrupting channel is downgraded to the digest (never dropped).
RATE_LIMITS = {"push": 6, "email": 12}
DIGEST_HOUR = 9  # local time of the daily digest; the weekly digest is Monday at this hour
MAX_ATTEMPTS = {"email": 6, "push": 5, "in_app": 1, "phone": 1, "sms": 3}
PUBLISH_STATE_EVENTS = {"verified": "publish.verified", "failed": "publish.failed", "uncertain": "publish.uncertain", "scheduled": "publish.scheduled"}


# Events an embedded service registers at runtime (Founder mode: rafii_control.founder_incidents). They live beside EVENTS,
# never inside it: the locked notification-planning policy (skills/rafii-registry.json) hashes EVENTS, so the shipped
# customer catalogue stays byte-stable, and public() never lists these events on the customer settings page.
EXTENSION_EVENTS = {
    # Private, person-scoped report readiness. The caller narrows whole-day
    # reports to in-app; existing preferences and quiet hours still apply.
    'james.team_report_ready': {'category': 'automation', 'severity': 'info', 'audience': 'actor',
                              'email': 'off', 'push': 'immediate', 'sms': 'off', 'template': 'digest'},
}


def register_extension_events(events):
    """Idempotent: a name already defined in EVENTS or EXTENSION_EVENTS keeps its first definition."""
    for name, item in events.items():
        if name in EVENTS or name in EXTENSION_EVENTS:
            continue
        if item.get("audience") not in AUDIENCES:
            raise ValueError(f"unknown audience for notification event {name!r}")
        EXTENSION_EVENTS[name] = {**item, "sms": item.get("sms", "off")}


def spec(event_type):
    try:
        return EVENTS[event_type] if event_type in EVENTS else EXTENSION_EVENTS[event_type]
    except KeyError as error:
        raise ValueError(f"unknown notification event {event_type!r}") from error


def transactional(event_type):
    return bool(spec(event_type).get("transactional"))


def public():
    """The catalogue the settings page shows: categories, events and defaults (no recipients or internals)."""
    return {"version": CATALOG_VERSION, "categories": list(CATEGORIES),
            "events": {name: {k: v for k, v in item.items() if k in ("category", "severity", "email", "push", "sms", "transactional")} for name, item in EVENTS.items()}}
