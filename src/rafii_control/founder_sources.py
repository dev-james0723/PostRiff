"""One source-id vocabulary for founder source health (Founder Admin v2, PRD §5.2 D, §8.7).

Boundaries. The founder cron (`founder_cron.probe`) is the only writer of `rafii_control.source_health` rows; the Live
and Demo metric adapters (`live_metrics`, `demo_metrics`) and the silence detector (`founder_incidents`) read exactly the
ids written here, so a source can never be "never probed" merely because two modules spelled it differently. A probe is
a reachability check with a checked_at stamp; a source whose last probe is older than STALE_AFTER_SECONDS is reported
stale (reason 'lagging') by the readers, and every metric drawn from it is labelled stale rather than measured.
"""

# Ids `founder_cron.probe` writes, in display order.
SOURCE_IDS = ('cron', 'database', 'control_database', 'phone_provider', 'notifications')
# Sources whose silence opens a founder incident (founder_incidents.THRESHOLDS['source_silence']).
REQUIRED_SOURCES = ('cron', 'database', 'control_database')
# A probe older than this is no longer evidence that the source is current (matches the cron heartbeat threshold).
STALE_AFTER_SECONDS = 180
# The source each activated metric is drawn from: consumer-database projections, the cron itself, the phone provider
# or the notification outbox.
METRIC_SOURCES = {
    'paid_customers': 'database', 'paid_workspaces': 'database', 'subscriptions_by_plan_status': 'database', 'cash_collected': 'database',
    'payment_failures': 'database', 'refunds_disputes': 'database', 'ai_cost_actual': 'database', 'ai_cost_unknown': 'database',
    'ai_cost_by_feature': 'database', 'cost_vs_cash': 'database', 'founder_ops_cost': 'database', 'budget_remaining': 'database',
    'active_workspaces': 'database', 'publish_outcomes': 'database', 'notification_delivery': 'notifications', 'phone_calls': 'phone_provider',
    'data_requests_backlog': 'database', 'security_events': 'database', 'cron_heartbeat': 'cron', 'source_health': 'cron',
}


def probe_age_seconds(row, now_epoch):
    """Seconds since the row's checked_at, or None when the row never recorded one. `checked_at` is epoch seconds."""
    checked = row.get('checked_at') if isinstance(row, dict) else None
    if checked is None:
        return None
    return max(0.0, float(now_epoch) - float(checked))


def is_stale(row, now_epoch, *, after=STALE_AFTER_SECONDS):
    """Whether a source row should be read as stale: recorded as such, or probed too long ago to be current."""
    if not isinstance(row, dict) or not row:
        return False
    if row.get('state') == 'stale':
        return True
    age = probe_age_seconds(row, now_epoch)
    return age is not None and age > after
