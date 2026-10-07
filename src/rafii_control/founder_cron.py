"""Founder cron tick (Founder Admin v2, CONTRACTS §1 and §5): probes → source_health; daily subscription snapshot;
detectors → incidents → critical contact; schedules → briefing → contact; reconcile attempts.

Boundaries. `tick(service, values)` runs inside the consumer `/api/cron/worker` branch, guarded there by
RAFII_CONTROL_ENABLED and wrapped so it never breaks the worker tick; every stage here is bounded and reports
'unavailable' instead of raising. Founder rows are written only through the restricted rafii_control_session store
(`PostgresFounderStore`), observations are fixed count/state queries over the consumer connection, and the only way to a
call is `founder_contact.PhoneCalls` → `PhoneService.request` in the ops workspace. Nothing here enables delivery: founder
notifications reach the shared outbox as in-app rows only until the operator's contact policy enables live delivery for
email/push (`_notifier`), and days are the report time zone (`live_metrics.TIME_ZONE`), never UTC.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from . import founder_briefings, founder_contact, founder_incidents, founder_schedules
from .auth import ControlError
from .founder_briefings import ReportSQL
from .founder_contact import ContactSQL, truthy
from .founder_follow_ups import FollowUpSQL
from .founder_incidents import IncidentSQL
from .founder_schedules import ScheduleSQL
from .founder_sources import SOURCE_IDS
from .live_metrics import TIME_ZONE

ENVIRONMENTS = ('local', 'staging', 'production')
SOURCE_STATES = ('measured', 'partial', 'stale', 'unavailable', 'not_applicable', 'suppressed')
REASON_CODES = ('qualified', 'not_configured', 'scope_missing', 'lagging', 'reconciliation_required', 'provider_unavailable')
PUBLISH_WINDOW_MINUTES = 60
# Notification channels a founder event may use before any policy is read: the in-app centre only (PRD §8.7, CONTRACTS §0).
BASELINE_CHANNELS = frozenset({'in_app'})
POLICY_CHANNELS = ('email', 'push')


class PostgresFounderStore(ContactSQL, IncidentSQL, ScheduleSQL, ReportSQL, FollowUpSQL):
    """All founder tables over one rafii_control.store.PostgresStore (session role, environment GUC policies)."""

    def __init__(self, store, environment=None):
        if environment is not None and environment != store.environment:
            raise ControlError('SCOPE_DENIED', 403)
        self.store, self.environment = store, store.environment

    def ping(self):
        with self.store.transaction() as con:
            return con.execute('SELECT 1 AS ok').fetchone()['ok'] == 1

    def upsert_source_health(self, source_id, state, reason_code, checked_at, watermark=None):
        if state not in SOURCE_STATES or reason_code not in REASON_CODES:
            raise ValueError('invalid source health')
        with self.store.transaction() as con:
            con.execute('INSERT INTO rafii_control.source_health(source_id,environment,state,watermark,checked_at,reason_code) '
                        'VALUES(%s,%s,%s,to_timestamp(%s),to_timestamp(%s),%s) ON CONFLICT(source_id,environment) DO UPDATE SET state=excluded.state,'
                        'watermark=coalesce(excluded.watermark,source_health.watermark),checked_at=excluded.checked_at,reason_code=excluded.reason_code',
                        (source_id, self.environment, state, watermark, checked_at, reason_code))

    def source_health(self):
        with self.store.transaction() as con:
            rows = con.execute('SELECT source_id,state,extract(epoch from watermark) AS watermark,extract(epoch from checked_at) AS checked_at,reason_code '
                               'FROM rafii_control.source_health WHERE environment=%s ORDER BY source_id LIMIT 100', (self.environment,)).fetchall()
        return [{**r, 'watermark': None if r['watermark'] is None else float(r['watermark']), 'checked_at': float(r['checked_at'])} for r in rows]

    def audit(self, action, result, actor, request_id, *, error_code=None):
        """One content-free admin_audit_log row (CONTRACTS §3 actions such as founder.call.request): ids, environment and outcome only."""
        self.store.audit(request_id=request_id, actor=actor, session=None, environment=self.environment, action=action, result=result, error_code=error_code)


def control_store(values):
    """The founder store from the restricted Control DSNs, or None when Control is not configured in this process."""
    from .store import PostgresStore, connection_factory
    session_dsn, reader_dsn = values.get('RAFII_CONTROL_SESSION_DSN'), values.get('RAFII_CONTROL_READER_DSN')
    environment = values.get('RAFII_CONTROL_ENVIRONMENT', 'local')
    if not session_dsn or not reader_dsn or session_dsn == reader_dsn or environment not in ENVIRONMENTS:
        return None
    store = PostgresStore(connection_factory(session_dsn, 'rafii_control_session', environment),
                          connection_factory(reader_dsn, 'rafii_control_reader', environment), environment)
    return PostgresFounderStore(store)


def _consumer_connection(service):
    factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
    if factory is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    return factory


def default_calls_factory(service, values, fstore=None):
    """PhoneCalls per operator, or None when the phone product or the operator's ops workspace (the deployment variable, else
    the founder's stored setting) is absent; attempts then suppress."""
    phone = getattr(service, 'phone', None)
    if not phone:
        return lambda operator_id: None
    from .founder_ops import resolve

    def calls(operator_id):
        ops, _source = resolve(values, getattr(fstore, 'store', None), operator_id)
        return founder_contact.PhoneCalls(phone, ops, operator_id,
            policy_loader=(lambda: founder_contact.load_policy(fstore, operator_id)) if fstore else None) if ops else None
    return calls


# Founder P1/P2 slices add cron stages from their own modules (CONTRACTS §8): register_stage(name, fn) at import, where
# fn(fstore, service, values, now) returns a JSON-serialisable summary. Stages run after the P0 stages, each bounded by
# _stage so one failing slice reports 'unavailable' without breaking the tick or the consumer worker.
STAGES = []


def register_stage(name, work):
    if not isinstance(name, str) or not name.isidentifier() or not callable(work) or any(existing == name for existing, _ in STAGES):
        raise ValueError('invalid or duplicate founder cron stage')
    STAGES.append((name, work))


def tick(service, values, *, fstore=None, calls_factory=None, clock=time.time, observe=None, lease_owner=None):
    """One founder tick. Returns a JSON-serialisable summary; stage failures are reported, never raised."""
    if not truthy(values.get('RAFII_CONTROL_ENABLED')):
        return {'status': 'disabled'}
    fstore = fstore if fstore is not None else control_store(values)
    if fstore is None:
        return {'status': 'disabled', 'reason': 'control_store_not_configured'}
    now = float(clock())
    calls_factory = calls_factory or default_calls_factory(service, values, fstore)
    result = {'status': 'ok', 'at': now, 'environment': fstore.environment}
    operators = _stage(result, 'operators', lambda: fstore.founder_operators()) or []
    _stage(result, 'probes', lambda: probe(fstore, service, values, now))
    _stage(result, 'snapshot', lambda: subscription_snapshot(service, now))
    observations = _stage(result, 'observations', lambda: (observe or observe_live)(fstore, service, values, now)) or {}
    notify = _notifier(service, operators, now, fstore, values)
    _stage(result, 'incidents', lambda: incidents_stage(fstore, values, observations, operators, now, calls_factory, notify))
    _stage(result, 'schedules', lambda: schedules_stage(fstore, values, observations, operators, now, calls_factory, notify,
                                                        lease_owner or 'founder-cron:' + uuid.uuid4().hex[:12]))
    _stage(result, 'reconcile', lambda: reconcile_stage(fstore, operators, now, calls_factory))
    from . import slices
    failed = slices.load()
    if failed:
        result['slices'] = {'status': 'unavailable', 'failed': sorted(failed)}
    for name, work in list(STAGES):
        _stage(result, name, lambda work=work: work(fstore, service, values, now))
    return result


def _stage(result, name, work):
    try:
        result[name] = work()
        return result[name]
    except Exception as error:
        result[name] = {'status': 'unavailable', 'error': type(error).__name__}
        result['status'] = 'partial'
        return None


# --- probes and snapshot --------------------------------------------------------------------------------------------------
def probe(fstore, service, values, now):
    """Self, consumer database, control database and its reader role, phone provider, notifications, and the event-recency
    sources (Stripe webhooks, email provider, model settles) → source_health rows: exactly the ids in
    founder_sources.SOURCE_IDS, which the metric adapters read back (CONTRACTS §8.D). Reachability sources stamp `now` as
    their watermark when measured; event sources stamp their latest good event. Every probe is bounded and never raises."""
    from . import founder_sources
    rows = {'cron': ('measured', 'qualified', now)}
    recency, writer_health = {}, {}
    try:
        with _consumer_connection(service)() as db:
            db.execute('SELECT 1')
            rows['database'] = ('measured', 'qualified', now)
            recency = founder_sources.event_recency(db, service)
            writer_health = founder_sources.writer_health(db)
    except Exception:
        if 'database' not in rows:
            rows['database'] = ('unavailable', 'provider_unavailable', None)
    try:
        rows['control_database'] = ('measured', 'qualified', now) if fstore.ping() else ('unavailable', 'provider_unavailable', None)
    except Exception:
        rows['control_database'] = ('unavailable', 'provider_unavailable', None)
    state, reason = founder_sources.reader_probe(fstore)
    rows['control_reader'] = (state, reason, now if state == 'measured' else None)
    try:
        provider = getattr(getattr(service, 'phone', None), 'provider', None)
        rows['phone_provider'] = ('measured', 'qualified', now) if provider and provider.configured else ('not_applicable', 'not_configured', None)
    except Exception:
        rows['phone_provider'] = ('unavailable', 'provider_unavailable', None)
    try:
        notifications = getattr(service, 'notifications', None)
        rows['notifications'] = ('measured', 'qualified', now) if notifications and notifications.enabled() else ('not_applicable', 'not_configured', None)
    except Exception:
        rows['notifications'] = ('unavailable', 'provider_unavailable', None)
    for source_id in founder_sources.EVENT_SOURCE_IDS:
        rows[source_id] = recency.get(source_id, ('unavailable', 'provider_unavailable', None))
    for source_id in ('product_writer', 'ai_writer'):
        rows[source_id] = writer_health.get(source_id, ('unavailable', 'provider_unavailable', None))
    if set(rows) != set(SOURCE_IDS):   # the readers (live_metrics, demo_metrics) iterate SOURCE_IDS; a drift here would show as 'never probed'
        raise ValueError('probe ids and founder_sources.SOURCE_IDS must agree')
    written = {}
    for source_id, (state, reason, watermark) in rows.items():
        try:
            fstore.upsert_source_health(source_id, state, reason, now, watermark=watermark)
            written[source_id] = state
        except Exception:
            written[source_id] = 'write_failed'
    return written


def local_day(now):
    """The report-time-zone calendar day (live_metrics.TIME_ZONE) an epoch instant falls in, as an ISO date."""
    return datetime.fromtimestamp(float(now), ZoneInfo(TIME_ZONE)).date()


SNAPSHOT_MRR_COLUMNS = ('mrr_minor', 'currency', 'interval', 'interval_count')


def _snapshot_mrr_sql(cur):
    """The MRR-recording snapshot insert (founder_metrics_revenue.snapshot_insert_sql), or None while 057 is not applied
    (no pr_subscription_events, or the snapshot table lacks its MRR columns) or the revenue slice cannot be imported."""
    cur.execute("SELECT to_regclass('public.pr_subscription_events') IS NOT NULL,"
                "(SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_subscription_snapshots' AND column_name = ANY(%s))",
                (list(SNAPSHOT_MRR_COLUMNS),))
    row = cur.fetchone()
    if not row or not row[0] or int(row[1] or 0) != len(SNAPSHOT_MRR_COLUMNS):
        return None
    try:
        from .founder_metrics_revenue import snapshot_insert_sql
    except Exception:  # noqa: BLE001 - the plan/status snapshot never depends on the revenue slice
        return None
    return snapshot_insert_sql()


def subscription_snapshot(service, now):
    """Once per report-time-zone day: copy every subscription's plan/status/provider into public.pr_subscription_snapshots
    (054). The snapshot is the state at the first tick of the local day, so the history series (`live_metrics
    ._subscription_history`, which reads `day` as a local date) is never mis-dated by an evening tick. Once 057 is applied
    the same row also records the workspace's normalized MRR, currency and billing interval from its latest billing events
    (null when no priced event exists: unknown, never the list price); if that richer insert fails, the plan/status
    snapshot is still written."""
    day = local_day(now).isoformat()
    with _consumer_connection(service)() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_subscription_snapshots')")
        if cur.fetchone()[0] is None:
            return {'status': 'unavailable', 'reason': 'table_missing', 'day': day}
        cur.execute('SELECT 1 FROM public.pr_subscription_snapshots WHERE day=%s::date LIMIT 1', (day,))
        if cur.fetchone():
            return {'status': 'ok', 'day': day, 'inserted': 0, 'existing': True}
        inserted, mrr = None, False
        mrr_sql = _snapshot_mrr_sql(cur)
        if mrr_sql:
            cur.execute('SAVEPOINT founder_snapshot_mrr')
            try:
                cur.execute(mrr_sql, (float(now), day))
                inserted, mrr = cur.rowcount, True
                cur.execute('RELEASE SAVEPOINT founder_snapshot_mrr')
            except Exception:  # noqa: BLE001 - fall back to the plan/status snapshot below
                cur.execute('ROLLBACK TO SAVEPOINT founder_snapshot_mrr')
                cur.execute('RELEASE SAVEPOINT founder_snapshot_mrr')
        if not mrr:
            cur.execute('INSERT INTO public.pr_subscription_snapshots(day,workspace_id,plan_terms_id,status,provider) '
                        'SELECT %s::date,workspace_id,plan_terms_id,status,provider FROM public.pr_subscriptions ON CONFLICT(day,workspace_id) DO NOTHING', (day,))
            inserted = cur.rowcount
        db.commit()
    return {'status': 'ok', 'day': day, 'inserted': max(0, inserted or 0), 'existing': False, 'mrr': mrr}


# --- observations (counts, states and timestamps only) --------------------------------------------------------------------
def observe_live(fstore, service, values, now):
    """What the detectors see this tick. Publishing outcomes and new past-due subscriptions are fixed counts on the
    consumer connection. AI cost (CONTRACTS §8.E) goes through the reader projections instead: the activated
    `ai_cost_actual` v1 statement (`live_metrics.compose`) over `rafii_control.business_usage_v2`, grouped by
    report-time-zone day, so aiUsageExempt rows and workspaces classified internal/test/demo are excluded exactly as in the
    receipted metric, and the budget stop comes from `business_budgets`. A missing or unreadable projection leaves cost
    unobserved, so the cost detector neither opens nor resolves an episode on absent data."""
    from datetime import timedelta

    from . import live_metrics
    from .store import MetricStatement
    observations = {'sources': [], 'sources_probed': True, 'publish': {'available': False}, 'cost': {'available': False}, 'payments': {'available': False}}
    try:
        observations['sources'] = fstore.source_health()
    except Exception:
        observations['sources_probed'] = False
    notifications = getattr(service, 'notifications', None)
    try:
        with _consumer_connection(service)() as db, db.cursor() as cur:
            if notifications and notifications.enabled():
                cur.execute("SELECT count(*) FILTER (WHERE event_type='publish.failed'),count(*) FILTER (WHERE event_type='publish.uncertain'),"
                            "count(*) FILTER (WHERE event_type='publish.verified') FROM public.pr_notification_events "
                            "WHERE event_type IN ('publish.failed','publish.uncertain','publish.verified') AND occurred_at>to_timestamp(%s)",
                            (now - PUBLISH_WINDOW_MINUTES * 60,))
                failed, uncertain, verified = cur.fetchone()
                observations['publish'] = {'available': True, 'window_minutes': PUBLISH_WINDOW_MINUTES, 'failed': int(failed), 'uncertain': int(uncertain), 'verified': int(verified)}
            else:
                observations['publish'] = {'available': False, 'reason': 'notifications_disabled'}
            cur.execute("SELECT count(*) FROM public.pr_subscriptions WHERE status='past_due' AND provider<>'fixture' AND coalesce(last_event_at,updated_at)>to_timestamp(%s)",
                        (now - 24 * 3600,))
            observations['payments'] = {'available': True, 'past_due_new': int(cur.fetchone()[0])}
    except Exception as error:
        observations['error'] = type(error).__name__
    store = getattr(fstore, 'store', None)
    if store is None or not callable(getattr(store, 'metric_rows', None)):
        observations['cost'] = {'available': False, 'reason': 'projection_unavailable'}
        return observations
    local = datetime.fromtimestamp(float(now), ZoneInfo(TIME_ZONE)).replace(microsecond=0)
    today = local.date()
    first = datetime.combine(today - timedelta(days=7), datetime.min.time(), tzinfo=ZoneInfo(TIME_ZONE))
    query = {'metricIds': ['ai_cost_actual'], 'interval': {'start': live_metrics.stamp(first), 'end': live_metrics.stamp(local + timedelta(seconds=1)), 'timeZone': TIME_ZONE},
             'groupBy': ['window'], 'filters': [], 'comparison': 'none', 'limit': live_metrics.MAX_POINTS}
    try:
        statement, params, _group_by, _history = live_metrics.compose('ai_cost_actual', query)
        rows = store.metric_rows(statement, params)
    except live_metrics.MISSING_SOURCE:
        observations['cost'] = {'available': False, 'reason': 'projection_unavailable'}
        return observations
    except Exception as error:
        observations['cost'] = {'available': False, 'reason': 'projection_error', 'error': type(error).__name__}
        return observations
    by_day = {str(row['d_window']): int(live_metrics.number(row['value']) or 0) for row in rows if row.get('d_window')}
    history = [by_day.get((today - timedelta(days=days)).isoformat(), 0) for days in range(7, 0, -1)]
    stop, budget = False, 'observed'
    try:
        found = store.metric_rows(MetricStatement('founder_budget_stop', 'SELECT EXISTS(SELECT 1 FROM rafii_control.business_budgets b WHERE b.status=\'approved\' '
                                                  'AND b."stopUsdMicro" IS NOT NULL AND b."spentUsdMicro"+b."reservedUsdMicro">=b."stopUsdMicro" '
                                                  'AND b.scope IN (\'global\',\'global-month\')) AS stop'), ())
        stop = bool(found and found[0].get('stop'))
    except Exception:
        budget = 'unavailable'
    observations['cost'] = {'available': True, 'today_usd_micro': by_day.get(today.isoformat(), 0), 'daily_usd_micro': history, 'budget_stop_reached': stop,
                            'budget': budget, 'basis': 'ai_cost_actual_v1_reader_projection', 'time_zone': TIME_ZONE}
    return observations


UNRECEIPTED = 'unreceipted_cron_observation'


def briefing_receipts(observations, now):
    """Receipt-shaped facts for the deterministic briefing. They are fixed cron counts without a query receipt, so every
    line is 'partial' with the detail `unreceipted_cron_observation` (CONTRACTS §0/§4: a receipted number comes from
    QueryService.metric_query) until the briefing composer runs through the receipt path."""
    publish, cost, payments = observations.get('publish') or {}, observations.get('cost') or {}, observations.get('payments') or {}
    sources = observations.get('sources') or []
    unavailable = {'dataState': 'unavailable'}
    observed = {'dataState': 'partial', 'detail': UNRECEIPTED}
    out = []
    for metric, label in (('publish_verified', 'Verified publications (last hour)'), ('publish_failed', 'Failed publications (last hour)'),
                          ('publish_uncertain', 'Uncertain publications (last hour)')):
        key = metric.split('_', 1)[1]
        out.append({'id': None, 'metricId': metric, 'label': label, 'unit': 'count', 'value': publish.get(key), **observed}
                   if publish.get('available') else {'id': None, 'metricId': metric, 'label': label, 'unit': 'count', **unavailable, 'detail': publish.get('reason')})
    out.append({'id': None, 'metricId': 'ai_cost_actual', 'label': 'AI cost today (actual)', 'unit': 'usd_micro', 'currency': 'USD',
                'value': cost.get('today_usd_micro'), **observed} if cost.get('available')
               else {'id': None, 'metricId': 'ai_cost_actual', 'label': 'AI cost today (actual)', 'unit': 'usd_micro', **unavailable})
    out.append({'id': None, 'metricId': 'payment_failures', 'label': 'New past-due subscriptions (24 h)', 'unit': 'count',
                'value': payments.get('past_due_new'), **observed} if payments.get('available')
               else {'id': None, 'metricId': 'payment_failures', 'label': 'New past-due subscriptions (24 h)', 'unit': 'count', **unavailable})
    measured = [s['source_id'] for s in sources if s.get('state') == 'measured']
    degraded = [f"{s['source_id']} {s.get('state')}" for s in sources if s.get('state') not in ('measured', 'not_applicable')]
    out.append({'id': None, 'metricId': 'source_health', 'label': 'Sources measured', 'unit': 'count', 'value': len(measured),
                'dataState': 'partial' if sources else 'unavailable', 'detail': ', '.join(degraded) if degraded else None})
    return out


# --- stages -------------------------------------------------------------------------------------------------------------------
def notification_channels(fstore, operator_id):
    """The outbox channels a founder event may plan for one operator: the in-app centre always; email/push only when the
    operator's founder contact policy has live delivery enabled AND lists the channel (founder_contact.DEFAULT_POLICY
    disables both, so nothing is mailed or pushed by default). No store, or an unreadable policy, is in-app only."""
    allowed = set(BASELINE_CHANNELS)
    if fstore is None:
        return sorted(allowed)
    try:
        policy = founder_contact.load_policy(fstore, operator_id)
    except Exception:
        return sorted(allowed)
    if policy.get('live_delivery_enabled'):
        allowed |= {channel for channel in POLICY_CHANNELS if channel in (policy.get('channels') or [])}
    return sorted(allowed)


def _notifier(service, operators, now, fstore=None, values=None):
    """notify(event_type, subject) for the founder notices of this tick (CONTRACTS §8.E; founder_notifications.notifier):
    every notice is recorded in the founder's in-app centre (rafii_control.founder_notices, when installed) and emitted
    per operator through the shared outbox (workspace_id=None, user_id=operator; payload title/href only) when the
    consumer notification feature is on. Email/push are planned only when the founder contact policy enables live
    delivery and lists the channel AND RAFII_FOUNDER_EMAIL_ENABLED / RAFII_FOUNDER_PUSH_ENABLED are set (`values`, else
    the process environment the cron runs with); founder quiet hours hold everything below critical/security. None when
    there is neither a founder centre nor an enabled outbox, or when the notices slice cannot load (the tick goes on)."""
    try:
        from . import founder_notifications
        return founder_notifications.notifier(service, operators, now, fstore, values)
    except Exception as error:  # noqa: BLE001 - notices are best-effort; detectors, briefings and contact still run
        import json
        import logging
        logging.getLogger('rafii_control.founder_cron').warning(json.dumps({'event': 'founder_notifier_unavailable', 'error': type(error).__name__}))
        return None


def incidents_stage(fstore, values, observations, operators, now, calls_factory, notify):
    findings = founder_incidents.detect(observations, now)
    summary = founder_incidents.evaluate(fstore, findings, now, notify=notify, observed=founder_incidents.observed_detectors(observations))
    contacts = []
    for incident in founder_incidents.escalations_due(fstore):
        for operator in operators:
            attempt, decision, created = founder_contact.contact(fstore, calls_factory(operator), operator, 'incident', incident['id'], now, flags=values)
            if created:
                kind = 'contact_suppressed' if attempt['state'] == 'suppressed' else 'contact_dispatched' if attempt.get('phone_call_id') else 'contact_planned'
                fstore.insert_incident_event(incident['id'], kind, now, {'attemptId': attempt['id'], 'decision': decision['decision'], 'detail': decision['detail'],
                                                                        'state': attempt['state']})
            contacts.append({'incidentId': incident['id'], 'operator': operator, 'attemptId': attempt['id'], 'state': attempt['state'],
                             'decision': decision['decision'], 'created': created})
    return {**summary, 'findings': len(findings), 'contacts': contacts}


def schedules_stage(fstore, values, observations, operators, now, calls_factory, notify, lease_owner):
    """Claim due briefing occurrences, compose each report once and contact the founder. The report's values come from
    receipted `QueryService.metric_query` reads run as the schedule's operator (`founder_briefings.briefing_facts`, cron
    principal = that operator's own active founder row, capability checks intact); only when no receipt can be produced
    do the cron's unreceipted observations stand in, and the report's coverage names that basis and why."""
    due = founder_schedules.claim_due(fstore, now, lease_owner=lease_owner)
    delivered, missed = [], []
    for item in due['claimed'] + due['missed']:
        schedule, operator = item['schedule'], item['schedule']['operator_id']
        report = fstore.report(item['report_id']) if item.get('report_id') else None
        if report is None:
            facts, basis = founder_briefings.briefing_facts(fstore, operator, schedule['kind'], now, fallback=lambda: briefing_receipts(observations, now))
            brief = founder_briefings.compose_brief(schedule['kind'], facts, now=now, time_zone=schedule['time_zone'],
                                                    environment=fstore.environment, incidents=fstore.open_incidents(), basis=basis)
            report = founder_briefings.save_report(fstore, operator, brief)
            fstore.update_occurrence(item['id'], report_id=report['id'], updated_at=now)
        if notify is not None:
            try:
                notify('founder.briefing_ready', report)
            except Exception:
                pass
        sourced = {'basis': (report.get('coverage') or {}).get('basis'), 'receipts': len(report.get('receipt_ids') or [])}
        if item['state'] == 'missed':
            # Late slot: the briefing reaches the inbox; no catch-up call is placed.
            founder_schedules.finish_occurrence(fstore, item['id'], state='missed', now=now, report_id=report['id'])
            missed.append({'occurrenceId': item['id'], 'reportId': report['id'], **sourced})
            continue
        attempt, decision, _created = founder_contact.contact(fstore, calls_factory(operator), operator, 'briefing', report['id'], now, flags=values,
                                                              scheduled_at=item['scheduled_at'])
        founder_schedules.finish_occurrence(fstore, item['id'], state='delivered', now=now, report_id=report['id'], attempt_id=attempt['id'])
        delivered.append({'occurrenceId': item['id'], 'reportId': report['id'], 'attemptId': attempt['id'], 'attemptState': attempt['state'],
                          'decision': decision['decision'], **sourced})
    return {'delivered': delivered, 'missed': missed, 'coalesced': [o['id'] for o in due['coalesced']]}


def reconcile_stage(fstore, operators, now, calls_factory):
    settled = {}
    for operator in operators:
        settled[operator] = len(founder_contact.reconcile_attempts(fstore, calls_factory(operator), now, operator_id=operator))
    return {'settled': settled}
