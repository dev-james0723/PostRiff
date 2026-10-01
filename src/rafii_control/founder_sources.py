"""One source-id vocabulary for founder source health (Founder Admin v2, PRD §5.2 D, §8.7, §10.3 WP11; CONTRACTS §8.D).

Boundaries. The founder cron (`founder_cron.probe`) is the only writer of `rafii_control.source_health` rows; the Live
and Demo metric adapters (`live_metrics`, `demo_metrics`) and the silence detector (`founder_incidents`) read exactly the
ids written here, so a source can never be "never probed" merely because two modules spelled it differently. A probe is
a reachability check with a checked_at stamp; a source whose last probe is older than STALE_AFTER_SECONDS is reported
stale (reason 'lagging') by the readers, and every metric drawn from it is labelled stale rather than measured.

Event-recency sources (Stripe webhooks, the email provider, model settles) are probed over the consumer connection by the
time of their latest good event, which becomes the source watermark: the readers show it as "last event N seconds ago". A
table that is not installed is 'not_configured', never an error; a provider the runtime did not mount is 'not_applicable'.
The probes read counts and timestamps only, never payloads.

The independent watchdog (`watchdog_main`, run by .github/workflows/founder-watchdog.yml) reads these rows back through the
read-only `rafii_control_watchdog` role (migration 066) and fails when the cron heartbeat is older than ten minutes or its
probe is not measured. It prints exception classes only, never a DSN or a server message.
"""
import os
import time

# Ids `founder_cron.probe` writes, in display order.
SOURCE_IDS = ('cron', 'database', 'control_database', 'control_reader', 'phone_provider', 'notifications', 'stripe_webhooks', 'email_provider', 'model_gateway')
# Sources whose silence opens a founder incident (founder_incidents.THRESHOLDS['source_silence']). The 8.D probes report
# health and recency; none of them pages on its own.
REQUIRED_SOURCES = ('cron', 'database', 'control_database')
# A probe older than this is no longer evidence that the source is current (matches the cron heartbeat threshold).
STALE_AFTER_SECONDS = 180
# The source each activated metric is drawn from: consumer-database projections, the cron itself, the phone provider
# or the notification outbox. Slices add theirs through live_metrics.register(sources=...).
METRIC_SOURCES = {
    'paid_customers': 'database', 'paid_workspaces': 'database', 'subscriptions_by_plan_status': 'database', 'cash_collected': 'database',
    'payment_failures': 'database', 'refunds_disputes': 'database', 'ai_cost_actual': 'database', 'ai_cost_unknown': 'database',
    'ai_cost_by_feature': 'database', 'cost_vs_cash': 'database', 'founder_ops_cost': 'database', 'budget_remaining': 'database',
    'active_workspaces': 'database', 'publish_outcomes': 'database', 'notification_delivery': 'notifications', 'phone_calls': 'phone_provider',
    'data_requests_backlog': 'database', 'security_events': 'database', 'cron_heartbeat': 'cron', 'source_health': 'cron',
}

# (source id, table that must exist, fixed statement returning the epoch of the latest good event or NULL).
EVENT_SOURCES = (
    ('stripe_webhooks', 'public.pr_billing_events',
     "SELECT extract(epoch FROM max(processed_at)) FROM public.pr_billing_events WHERE provider='stripe' AND outcome<>'rejected'"),
    ('email_provider', 'public.pr_notification_provider_events',
     "SELECT extract(epoch FROM max(received_at)) FROM public.pr_notification_provider_events WHERE provider='resend' AND outcome<>'rejected'"),
    ('model_gateway', 'public.pr_usage_ledger',
     "SELECT extract(epoch FROM max(at)) FROM public.pr_usage_ledger WHERE kind='settle' AND cost_state='actual'"),
)
EVENT_SOURCE_IDS = tuple(source_id for source_id, _, _ in EVENT_SOURCES)
_MISSING = object()


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


# --- probes (called by founder_cron.probe) --------------------------------------------------------------------------------
def reader_probe(fstore):
    """control_reader: the restricted reader login answers SELECT 1 as rafii_control_reader, the role every founder metric
    reads through (PostgresStore.transaction(read=True) refuses any other, superuser or bypassrls role). (state, reason)."""
    transaction = getattr(getattr(fstore, 'store', None), 'transaction', None)
    if not callable(transaction):
        return 'unavailable', 'not_configured'
    try:
        with transaction(read=True) as con:
            row = con.execute('SELECT 1 AS ok').fetchone()
        ok = (row['ok'] if isinstance(row, dict) else row[0]) == 1
        return ('measured', 'qualified') if ok else ('unavailable', 'provider_unavailable')
    except Exception:
        return 'unavailable', 'provider_unavailable'


def configured(source_id, service):
    """Whether the consumer runtime mounted the provider behind an event source: True, False, or None when it cannot tell.
    Reads the mounted objects only, never a credential or environment value."""
    if source_id == 'stripe_webhooks':
        provider = getattr(getattr(service, 'billing', None), 'provider', None)
        return None if provider is None else getattr(provider, 'id', None) == 'stripe'
    if source_id == 'email_provider':
        transport = getattr(getattr(service, 'mailer', None), 'transport', None)
        return None if transport is None else type(transport).__name__ == 'ResendTransport'
    if source_id == 'model_gateway':
        ideas = getattr(service, 'ideas', None)
        runtimes = list(getattr(ideas, 'runtimes', None) or []) + [getattr(ideas, 'runtime', None)]
        # Other runtimes (agent v2, phone audio) also settle, so the absence of the gateway runtime proves nothing.
        return True if any(type(runtime).__name__ == 'ServerModelRuntime' for runtime in runtimes if runtime is not None) else None
    return None


def _savepoint(db, work):
    """Run one probe statement group inside a savepoint when the connection supports it, so a failing probe cannot abort
    the others sharing the consumer transaction."""
    transaction = getattr(db, 'transaction', None)
    if not callable(transaction):
        return work()
    with transaction():
        return work()


def _latest_event(db, table, sql):
    def work():
        with db.cursor() as cur:
            cur.execute('SELECT to_regclass(%s) IS NOT NULL', (table,))
            row = cur.fetchone()
            if not row or not row[0]:
                return _MISSING
            cur.execute(sql)
            row = cur.fetchone()
            return None if not row or row[0] is None else float(row[0])
    return _savepoint(db, work)


def event_state(mounted, latest):
    """(state, reason, watermark) for one event-recency source."""
    if latest is _MISSING:
        return 'not_applicable', 'not_configured', None
    if mounted is False:
        return 'not_applicable', 'not_configured', latest
    if latest is None:
        return 'partial', 'lagging', None   # mounted (or unknown) but no good event recorded yet: no recency evidence
    return 'measured', 'qualified', latest


def event_recency(db, service):
    """{source id: (state, reason, watermark epoch)} for the event-recency sources over one open consumer connection.
    Never raises: a failing statement marks that source unavailable."""
    out = {}
    for source_id, table, sql in EVENT_SOURCES:
        try:
            out[source_id] = event_state(configured(source_id, service), _latest_event(db, table, sql))
        except Exception:
            out[source_id] = ('unavailable', 'provider_unavailable', None)
    return out


# --- independent watchdog (P2, WP11) ---------------------------------------------------------------------------------------
WATCHDOG_MAX_AGE_SECONDS = 600
WATCHDOG_ENVIRONMENTS = ('local', 'staging', 'production')


class WatchdogRefused(Exception):
    """The login behind RAFII_WATCHDOG_DSN is not the dedicated read-only watchdog login."""


def watchdog_verdict(rows, now_epoch, *, max_age=WATCHDOG_MAX_AGE_SECONDS):
    """(ok, problems, lines) over one environment's source_health rows. Fails only on the cron heartbeat: missing, older than
    max_age seconds, or its probe not 'measured'. Other sources are listed for context."""
    by_id = {row['source_id']: row for row in rows or [] if isinstance(row, dict) and row.get('source_id')}
    order = {source_id: index for index, source_id in enumerate(SOURCE_IDS)}
    lines = []
    for source_id in sorted(by_id, key=lambda value: (order.get(value, len(order)), value)):
        row, age = by_id[source_id], probe_age_seconds(by_id[source_id], now_epoch)
        lines.append(f"{source_id}: {row.get('state')} ({row.get('reason_code')}), checked {'never' if age is None else str(int(age)) + ' s ago'}")
    problems = []
    cron = by_id.get('cron')
    if cron is None:
        problems.append('No cron heartbeat row is recorded for this environment.')
    else:
        age = probe_age_seconds(cron, now_epoch)
        if age is None:
            problems.append('The cron heartbeat row has no checked_at stamp.')
        elif age > max_age:
            problems.append(f'The cron heartbeat is {int(age)} s old (limit {max_age} s).')
        if cron.get('state') != 'measured':
            problems.append(f"The cron probe is {cron.get('state')} ({cron.get('reason_code')}), not measured.")
    return not problems, problems, lines


def read_source_health(dsn, environment, *, connect=None):
    """One read-only transaction as rafii_control_watchdog: refuse a privileged login or a role that can write, then read the
    environment's source_health rows (ids, states, reason codes, epoch timestamps)."""
    if connect is None:
        import psycopg

        def connect():
            return psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None, application_name='rafii-founder-watchdog')
    with connect() as con:
        with con.transaction():
            con.execute('SET TRANSACTION READ ONLY')
            con.execute("SET LOCAL statement_timeout = '5s'")
            login = con.execute('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=session_user').fetchone()
            if login is None or login[0]:
                raise WatchdogRefused('Use the dedicated read-only watchdog login, not a privileged role.')
            con.execute('SET LOCAL ROLE rafii_control_watchdog')
            if con.execute("SELECT has_table_privilege('rafii_control.source_health','INSERT,UPDATE,DELETE,TRUNCATE')").fetchone()[0]:
                raise WatchdogRefused('The watchdog role can write source_health; it must be SELECT-only.')
            con.execute("SELECT set_config('rafii_control.environment',%s,true)", (environment,))
            rows = con.execute('SELECT source_id,state,reason_code,extract(epoch FROM checked_at),extract(epoch FROM watermark) FROM rafii_control.source_health '
                               'WHERE environment=%s ORDER BY source_id LIMIT 100', (environment,)).fetchall()
    return [{'source_id': row[0], 'state': row[1], 'reason_code': row[2], 'checked_at': None if row[3] is None else float(row[3]),
             'watermark': None if row[4] is None else float(row[4])} for row in rows]


def _summary(environ, environment, ok, problems, lines):
    path = environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(f"## Founder watchdog ({environment}): {'heartbeat current' if ok else 'heartbeat FAILED'}\n\n")
            for line in problems + lines:
                handle.write(f'- {line}\n')
    except OSError:
        pass


def watchdog_main(environ=None, *, connect=None, clock=time.time, out=print):
    """Exit code for the scheduled GitHub Actions watchdog: 0 when not configured (notice) or the heartbeat is current, 1 when
    it is stale, unmeasured or unreadable. Prints GitHub annotations; never the DSN or a server message."""
    environ = os.environ if environ is None else environ
    dsn = (environ.get('RAFII_WATCHDOG_DSN') or '').strip()
    environment = (environ.get('RAFII_WATCHDOG_ENVIRONMENT') or 'production').strip()
    if not dsn:
        out('::notice title=Founder watchdog not configured::RAFII_WATCHDOG_DSN is not set, so the founder cron heartbeat was not checked. '
            'Add the read-only watchdog login DSN as a repository secret to enable this check.')
        return 0
    if environment not in WATCHDOG_ENVIRONMENTS:
        out('::error title=Founder watchdog misconfigured::RAFII_WATCHDOG_ENVIRONMENT must be local, staging or production.')
        return 1
    try:
        rows = read_source_health(dsn, environment, connect=connect)
    except WatchdogRefused as refused:
        out(f'::error title=Founder watchdog refused the login::{refused}')
        return 1
    except Exception as error:
        out(f'::error title=Founder watchdog cannot read source health::{type(error).__name__}')
        return 1
    ok, problems, lines = watchdog_verdict(rows, clock())
    for line in lines:
        out(line)
    _summary(environ, environment, ok, problems, lines)
    if not ok:
        for problem in problems:
            out(f'::error title=Founder cron heartbeat ({environment})::{problem}')
        return 1
    out(f'::notice title=Founder cron heartbeat ({environment})::The founder cron heartbeat is current.')
    return 0
