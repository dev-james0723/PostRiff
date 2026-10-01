"""Activated v1 founder metrics over the 054 restricted projections, plus the Overview composition.

Boundaries: every metric is one fixed statement from the registry below (server-chosen views,
columns, joins and aggregates). Browser input reaches PostgreSQL only as bound parameters:
half-open interval bounds, an IANA timezone, catalog-listed dimension names resolved here to
fixed expressions, filter values, and the row limit. Customer metrics exclude aiUsageExempt
ledger rows, provider='fixture' subscriptions and workspaces classified internal/test/demo;
founder_ops_cost includes only those. Reader role, read-only transactions, no provider or
model calls, no writes besides the ordinary query receipt. Demo parity lives in demo_metrics.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
from zoneinfo import ZoneInfo
import psycopg
from .auth import ControlError
from .founder_sources import METRIC_SOURCES, SOURCE_IDS, STALE_AFTER_SECONDS
from .store import MetricStatement

# A projection that the canonical schema has not produced (053/054 create payment views only where pr_credit_* exist)
# is a source that is not configured: the metric reports unavailable, never zero and never a 503.
MISSING_SOURCE = (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn, psycopg.errors.InvalidSchemaName, psycopg.errors.InsufficientPrivilege)

TIME_ZONE = 'America/Indiana/Indianapolis'
PERIODS = {'7d': 7, '30d': 30, '90d': 90}
DEFINITION_VERSION = 'v1'
ADAPTER = 'live_metrics/v1'
MAX_POINTS = 1000
HEARTBEAT_STALE_SECONDS = STALE_AFTER_SECONDS
# SOURCE_IDS / METRIC_SOURCES come from founder_sources: the ids founder_cron.probe writes, and the source each metric is drawn from.
__all__ = ['SOURCE_IDS', 'METRIC_SOURCES']
PUBLISH_EVENTS = "('publish.verified','publish.failed','publish.uncertain')"
WINDOW = "to_char(date_trunc('day', b.at AT TIME ZONE %s),'YYYY-MM-DD')"


def excluded(column):
    """Fixed customer exclusion applied inside every customer metric base; the reader sees only its environment."""
    return f"NOT EXISTS (SELECT 1 FROM rafii_control.workspace_classifications c WHERE c.kind IN ('internal','test','demo') AND c.workspace_id::text={column})"


def interval_clause(column): return f'{column} >= %s::timestamptz AND {column} < %s::timestamptz'


def _subscriptions(current_only):
    status = " AND s.status IN ('active','past_due') AND s.\"ownerId\" IS NOT NULL" if current_only else ''
    return ('SELECT s."ownerId" AS owner, s."workspaceId" AS wid, s.plan, s.status, s."updatedAt" AS at FROM rafii_control.business_subscriptions_v2 s'
            f" WHERE s.provider<>'fixture'{status} AND {excluded('s.\"workspaceId\"')}")


def _subscription_history(current_only):
    status = " AND h.status IN ('active','past_due')" if current_only else ''
    return ('SELECT w."ownerId" AS owner, h."workspaceId" AS wid, h.plan, h.status, (h.day::timestamp AT TIME ZONE %s) AS at'
            ' FROM rafii_control.business_subscription_snapshots h LEFT JOIN rafii_control.business_workspaces w ON w.id=h."workspaceId"'
            f" WHERE h.provider<>'fixture'{status} AND h.day >= (%s::timestamptz AT TIME ZONE %s)::date AND h.day < (%s::timestamptz AT TIME ZONE %s)::date AND {excluded('h.\"workspaceId\"')}")


def settled_elsewhere(alias):
    """An estimated_unknown row whose reservation later gained a terminal settle/release row is reconciled, not unknown: the
    ledger keeps the original row (billing.Ledger.unknown_reservations applies the same NOT EXISTS), so it is excluded here."""
    return (f'NOT ({alias}."costState"=\'estimated_unknown\' AND EXISTS (SELECT 1 FROM rafii_control.business_usage_v2 t WHERE t."workspaceId"={alias}."workspaceId"'
            f' AND t."reservationId"={alias}."reservationId" AND t."costState" IN (\'actual\',\'released\')))')


def _usage(cost_states, kinds="('settle')"):
    return ('SELECT u."workspaceId" AS wid, u.at, u.feature, u.provider, u.model, s.plan, u."costState" AS cost_state, u."actualUsdMicro" AS actual, u."estimatedUsdMicro" AS estimated'
            ' FROM rafii_control.business_usage_v2 u LEFT JOIN rafii_control.business_subscriptions_v2 s ON s."workspaceId"=u."workspaceId"'
            f' WHERE u.kind IN {kinds} AND u."costState" IN {cost_states} AND NOT u."aiUsageExempt" AND {settled_elsewhere("u")} AND {interval_clause("u.at")} AND {excluded("u.\"workspaceId\"")}')


# Registry: base rows carry wid/at plus the fixed dimension and measure columns the outer aggregate uses.
# interval_params: how many (start,end) pairs the base consumes; history bases take (tz,start,tz,end,tz).
SPECS = {
    'paid_customers': dict(base=_subscriptions(True), history=_subscription_history(True), interval_params=0, snapshot=True, probe='rafii_control.business_subscriptions_v2',
                           history_probe='rafii_control.business_subscription_snapshots', value='count(DISTINCT b.owner)', dims={'plan': 'b.plan', 'status': 'b.status'}, unit='count'),
    'paid_workspaces': dict(base=_subscriptions(True), history=_subscription_history(True), interval_params=0, snapshot=True, probe='rafii_control.business_subscriptions_v2',
                            history_probe='rafii_control.business_subscription_snapshots', value='count(DISTINCT b.wid)', dims={'plan': 'b.plan', 'status': 'b.status'}, unit='count'),
    'subscriptions_by_plan_status': dict(base=_subscriptions(False), history=_subscription_history(False), interval_params=0, snapshot=True, probe='rafii_control.business_subscriptions_v2',
                                         history_probe='rafii_control.business_subscription_snapshots', value='count(DISTINCT b.wid)', dims={'plan': 'b.plan', 'status': 'b.status'}, unit='count'),
    'cash_collected': dict(base=('SELECT p."workspaceId" AS wid, p.at, p.currency, \'top_up\' AS payment_type, p."amountMinor" AS amount FROM rafii_control.business_payments_v2 p'
                                 f' WHERE p.status=\'funded\' AND p.livemode AND {interval_clause("p.at")} AND {excluded("p.\"workspaceId\"")}'
                                 ' UNION ALL SELECT g."workspaceId", g."recordedAt", g.currency, \'subscription_invoice\', g."amountMinor" FROM rafii_control.business_subscription_grants g'
                                 f' WHERE g.livemode AND {interval_clause("g.\"recordedAt\"")} AND {excluded("g.\"workspaceId\"")}'),
                           interval_params=2, probe='rafii_control.business_payments_v2', value='coalesce(sum(b.amount),0)', dims={'currency': 'b.currency', 'payment_type': 'b.payment_type'},
                           unit='currency_minor', currency='b.currency', state='partial', reason='legacy_plan_invoices_not_recorded'),
    'payment_failures': dict(base=('SELECT n."workspaceId" AS wid, n."createdAt" AS at, \'subscription\' AS payment_type FROM rafii_control.business_billing_notices n'
                                   f' WHERE n.kind=\'payment_failed\' AND {interval_clause("n.\"createdAt\"")} AND {excluded("n.\"workspaceId\"")}'
                                   ' UNION ALL SELECT o."workspaceId", o.at, \'top_up\' FROM rafii_control.business_payments_v2 o'
                                   f' WHERE o.status=\'failed\' AND {interval_clause("o.at")} AND {excluded("o.\"workspaceId\"")}'),
                             interval_params=2, probe='rafii_control.business_billing_notices', value='count(*)', dims={'payment_type': 'b.payment_type'}, unit='count'),
    'refunds_disputes': dict(base=('SELECT r."workspaceId" AS wid, r."eventCreated" AS at, r.currency, \'refund\' AS category, r.status, r."amountMinor" AS amount FROM rafii_control.business_refunds r'
                                   f' WHERE r.status=\'succeeded\' AND {interval_clause("r.\"eventCreated\"")} AND (r."workspaceId" IS NULL OR {excluded("r.\"workspaceId\"")})'
                                   ' UNION ALL SELECT d."workspaceId", d."eventCreated", d.currency, \'dispute\', d.status, d."amountMinor" FROM rafii_control.business_disputes d'
                                   f' WHERE NOT d.withdrawn AND {interval_clause("d.\"eventCreated\"")} AND (d."workspaceId" IS NULL OR {excluded("d.\"workspaceId\"")})'),
                             interval_params=2, probe='rafii_control.business_refunds', value='coalesce(sum(b.amount),0)', known='count(*) FILTER (WHERE b.wid IS NOT NULL)',
                             unknown='count(*) FILTER (WHERE b.wid IS NULL)', dims={'currency': 'b.currency', 'category': 'b.category', 'status': 'b.status'},
                             unit='currency_minor', currency='b.currency', unknown_reason='unattributed_legacy_payments'),
    'ai_cost_actual': dict(base=_usage("('actual','estimated_unknown')"), interval_params=1, probe='rafii_control.business_usage_v2',
                           value="coalesce(sum(b.actual) FILTER (WHERE b.cost_state='actual'),0)", known="count(*) FILTER (WHERE b.cost_state='actual')",
                           unknown="count(*) FILTER (WHERE b.cost_state='estimated_unknown')", measures={'unknownEstimateUsdMicro': "coalesce(sum(b.estimated) FILTER (WHERE b.cost_state='estimated_unknown'),0)"},
                           dims={'feature': 'b.feature', 'provider': 'b.provider', 'model': 'b.model', 'plan': 'b.plan'}, unit='usd_micro', currency="'USD'", unknown_reason='unsettled_cost_rows'),
    'ai_cost_unknown': dict(base=_usage("('estimated_unknown')", "('reserve','settle')"), interval_params=1, probe='rafii_control.business_usage_v2', value='coalesce(sum(b.estimated),0)',
                            dims={'feature': 'b.feature', 'provider': 'b.provider', 'model': 'b.model', 'plan': 'b.plan'}, unit='usd_micro', currency="'USD'"),
    'ai_cost_by_feature': dict(base=_usage("('actual','estimated_unknown')"), interval_params=1, probe='rafii_control.business_usage_v2', implicit=('feature',),
                               value="coalesce(sum(b.actual) FILTER (WHERE b.cost_state='actual'),0)", known="count(*) FILTER (WHERE b.cost_state='actual')",
                               unknown="count(*) FILTER (WHERE b.cost_state='estimated_unknown')", dims={'feature': 'b.feature', 'provider': 'b.provider', 'model': 'b.model', 'plan': 'b.plan'},
                               unit='usd_micro', currency="'USD'", unknown_reason='unsettled_cost_rows'),
    'founder_ops_cost': dict(base=('SELECT u."workspaceId" AS wid, u.at, u.feature, u.provider, u."costState" AS cost_state, coalesce(u."actualUsdMicro",u."estimatedUsdMicro") AS cost FROM rafii_control.business_usage_v2 u'
                                   " WHERE u.kind='settle' AND u.\"costState\"<>'released' AND (u.\"aiUsageExempt\" OR u.\"costCenter\"='founder_ops'"
                                   " OR EXISTS (SELECT 1 FROM rafii_control.workspace_classifications c WHERE c.kind IN ('internal','test','demo') AND c.workspace_id::text=u.\"workspaceId\"))"
                                   f' AND {settled_elsewhere("u")} AND {interval_clause("u.at")}'),
                             interval_params=1, probe='rafii_control.business_usage_v2', value='coalesce(sum(b.cost),0)', known="count(*) FILTER (WHERE b.cost_state='actual')",
                             unknown="count(*) FILTER (WHERE b.cost_state<>'actual')", dims={'feature': 'b.feature', 'provider': 'b.provider'}, unit='usd_micro', currency="'USD'", unknown_reason='estimates_included'),
    'budget_remaining': dict(base=('SELECT b.scope, b.status, b."windowStart" AS at, b."stopUsdMicro"-(b."spentUsdMicro"+b."reservedUsdMicro") AS remaining, b."stopUsdMicro" AS stop,'
                                   ' b."spentUsdMicro"+b."reservedUsdMicro" AS used FROM rafii_control.business_budgets b'),
                             interval_params=0, snapshot=True, probe='rafii_control.business_budgets', implicit=('scope',), value='sum(b.remaining)', numerator='sum(b.used)', denominator='sum(b.stop)',
                             dims={'scope': 'b.scope', 'status': 'b.status'}, unit='usd_micro', currency="'USD'"),
    'active_workspaces': dict(base=('SELECT a.wid, a.at, s.plan FROM (SELECT r."workspaceId" AS wid, r."createdAt" AS at FROM rafii_control.business_agent_runs r'
                                    f' WHERE r.status IN (\'completed\',\'applied\') AND {interval_clause("r.\"createdAt\"")}'
                                    ' UNION ALL SELECT e."workspaceId", e."occurredAt" FROM rafii_control.business_notification_events e'
                                    f' WHERE e."eventType" IN {PUBLISH_EVENTS} AND e."workspaceId" IS NOT NULL AND {interval_clause("e.\"occurredAt\"")}) a'
                                    f' LEFT JOIN rafii_control.business_subscriptions_v2 s ON s."workspaceId"=a.wid WHERE {excluded("a.wid")}'),
                              interval_params=2, probe='rafii_control.business_agent_runs', value='count(DISTINCT b.wid)', dims={'plan': 'b.plan'}, unit='count'),
    'publish_outcomes': dict(base=('SELECT e."workspaceId" AS wid, e."occurredAt" AS at, split_part(e."eventType",\'.\',2) AS status, coalesce(e."payloadPlatform",\'unknown\') AS platform'
                                   f' FROM rafii_control.business_notification_events e WHERE e."eventType" IN {PUBLISH_EVENTS} AND {interval_clause("e.\"occurredAt\"")}'
                                   f' AND (e."workspaceId" IS NULL OR {excluded("e.\"workspaceId\"")})'),
                             interval_params=1, probe='rafii_control.business_notification_events', value='count(*)', known="count(*) FILTER (WHERE b.status IN ('verified','failed'))",
                             unknown="count(*) FILTER (WHERE b.status='uncertain')", numerator="count(*) FILTER (WHERE b.status='verified')", denominator='count(*)',
                             dims={'status': 'b.status', 'platform': 'b.platform'}, unit='count', unknown_reason='uncertain_publish_outcomes'),
    'notification_delivery': dict(base=('SELECT d."workspaceId" AS wid, d."createdAt" AS at, d.channel, d.status, coalesce(d."failureClass",\'none\') AS failure_class'
                                        f' FROM rafii_control.business_notification_deliveries d WHERE {interval_clause("d.\"createdAt\"")} AND (d."workspaceId" IS NULL OR {excluded("d.\"workspaceId\"")})'),
                                  interval_params=1, probe='rafii_control.business_notification_deliveries', value='count(*)', known="count(*) FILTER (WHERE b.status NOT IN ('pending','claimed'))",
                                  unknown="count(*) FILTER (WHERE b.failure_class='uncertain')", dims={'channel': 'b.channel', 'status': 'b.status', 'failure_class': 'b.failure_class'}, unit='count', unknown_reason='uncertain_deliveries'),
    'phone_calls': dict(base=('SELECT c."workspaceId" AS wid, c."requestedAt" AS at, c.kind, c.direction, c.provider, c.state, coalesce(c."failureClass",\'none\') AS failure_class,'
                              ' coalesce(c."telephonyCostUsdMicro",0)+coalesce(c."liveCostUsdMicro",0) AS cost, coalesce(c."durationSeconds",0) AS duration'
                              f' FROM rafii_control.business_phone_calls c WHERE {interval_clause("c.\"requestedAt\"")}'),
                        interval_params=1, probe='rafii_control.business_phone_calls', value='count(*)', known="count(*) FILTER (WHERE b.state<>'ambiguous')", unknown="count(*) FILTER (WHERE b.state='ambiguous')",
                        measures={'costUsdMicro': 'coalesce(sum(b.cost),0)', 'durationSeconds': 'coalesce(sum(b.duration),0)'},
                        dims={'kind': 'b.kind', 'direction': 'b.direction', 'provider': 'b.provider', 'state': 'b.state', 'failure_class': 'b.failure_class'}, unit='count', unknown_reason='ambiguous_calls'),
    'data_requests_backlog': dict(base=('SELECT r."workspaceId" AS wid, r."requestedAt" AS at, r.kind, CASE WHEN r."requestedAt" > now()-interval \'1 day\' THEN \'under_1d\''
                                        ' WHEN r."requestedAt" > now()-interval \'7 days\' THEN \'1d_to_7d\' ELSE \'over_7d\' END AS age_band FROM rafii_control.business_data_requests_v2 r'
                                        f' WHERE r.status=\'requested\' AND (r."workspaceId" IS NULL OR {excluded("r.\"workspaceId\"")})'),
                                  interval_params=0, snapshot=True, probe='rafii_control.business_data_requests_v2', value='count(*)', dims={'kind': 'b.kind', 'age_band': 'b.age_band'}, unit='count'),
    'security_events': dict(base=f'SELECT a."workspaceId" AS wid, a.at, a.kind FROM rafii_control.business_audit_events a WHERE {interval_clause("a.at")}',
                            interval_params=1, probe='rafii_control.business_audit_events', value='count(*)', dims={'kind': 'b.kind'}, unit='count'),
}
COMPOSITE = {'cost_vs_cash'}
PYTHON_ONLY = {'cron_heartbeat', 'source_health'}
# Founder Admin P1/P2 slices extend this registry from their own modules (CONTRACTS §8) instead of editing SPECS here:
# `register(specs=..., custom=..., sources=...)` at import. A custom metric is {'rows': fn, 'previous': fn | None}, where
# fn(service, metric, query, interval, stale) -> rows built with build_row over reader projections; 'previous' defaults
# to the same fn over previous_interval(query), and None means the metric has no comparison (rows say so).
CUSTOM = {}


def register(*, specs=None, custom=None, sources=None):
    """Add activated metrics from a slice module. Ids are unique across SPECS, CUSTOM, COMPOSITE and PYTHON_ONLY."""
    taken = set(SPECS) | set(CUSTOM) | COMPOSITE | PYTHON_ONLY
    for metric_id in list(specs or {}) + list(custom or {}):
        if metric_id in taken: raise ValueError('duplicate live metric ' + metric_id)
        taken.add(metric_id)
    SPECS.update(specs or {})
    for metric_id, entry in (custom or {}).items():
        if not callable(entry.get('rows')) or ('previous' in entry and entry['previous'] is not None and not callable(entry['previous'])):
            raise ValueError('invalid custom live metric ' + metric_id)
        CUSTOM[metric_id] = entry
    for metric_id, source_id in (sources or {}).items():
        if source_id not in SOURCE_IDS: raise ValueError('unknown source for ' + metric_id)
        METRIC_SOURCES[metric_id] = source_id


def load_extensions():
    """Import every installed founder slice once (rafii_control.slices); a failed slice leaves its metrics adapter_unavailable."""
    from . import slices
    slices.load()


def known(metric_id):
    return metric_id in SPECS or metric_id in CUSTOM or metric_id in COMPOSITE or metric_id in PYTHON_ONLY
UNKNOWN_RESERVATIONS = MetricStatement('unknown_reservations', 'SELECT u.id,u."workspaceId",u."runId",u."reservationId",u.kind,u.dimension,u.provider,u.model,u.feature,u."estimatedUsdMicro",u.at FROM rafii_control.business_usage_v2 u'
                                       f' WHERE u."costState"=\'estimated_unknown\' AND NOT u."aiUsageExempt" AND {settled_elsewhere("u")} ORDER BY u.at DESC,u.id LIMIT %s')


def number(value):
    """Reader rows arrive serialized (Decimal -> str); aggregates come back as exact integers or floats."""
    if value is None or isinstance(value, bool): return value
    if isinstance(value, int): return value
    decimal = Decimal(str(value))
    return int(decimal) if decimal == decimal.to_integral_value() else float(decimal)


def parse_stamp(value): return datetime.fromisoformat(value.replace('Z', '+00:00'))
def stamp(value): return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def interval_of(query):
    return dict(start=query['interval']['start'], end=query['interval']['end'], timeZone=query['interval']['timeZone'])


def previous_interval(query):
    """previous_equal_elapsed shifts back by the elapsed length; previous_complete aligns to the previous calendar month when the start is a local month start."""
    start, end = parse_stamp(query['interval']['start']), parse_stamp(query['interval']['end'])
    zone = ZoneInfo(query['interval']['timeZone'])
    local = start.astimezone(zone)
    if query['comparison'] == 'previous_complete' and (local.day, local.hour, local.minute, local.second, local.microsecond) == (1, 0, 0, 0, 0):
        previous_start = (local.replace(day=1) - timedelta(days=1)).replace(day=1)
        previous_end = previous_start + (end - start)
        return dict(start=stamp(previous_start), end=stamp(min(previous_end, local)), timeZone=query['interval']['timeZone'])
    return dict(start=stamp(start - (end - start)), end=stamp(start), timeZone=query['interval']['timeZone'])


def compose(metric_id, query, interval=None):
    """One fixed statement per metric; dimensions and filters resolve to registry expressions only."""
    spec = SPECS[metric_id]
    interval = interval or query['interval']
    group_by = list(spec.get('implicit', ())) + [dim for dim in query['groupBy'] if dim not in spec.get('implicit', ())]
    history = 'window' in group_by and spec.get('history')
    if 'window' in group_by and not history and spec.get('snapshot'): raise ControlError('VALIDATION_FAILED', 400)
    expressions = {**spec['dims'], 'window': WINDOW}
    params = [interval['timeZone'], interval['start'], interval['timeZone'], interval['end'], interval['timeZone']] if history else [interval['start'], interval['end']] * spec['interval_params']
    selected = []
    for dim in group_by:
        if dim not in expressions: raise ControlError('VALIDATION_FAILED', 400)
        selected.append(f'{expressions[dim]} AS "d_{dim}"')
        if dim == 'window': params.append(interval['timeZone'])
    aggregates = [f"{spec['value']} AS value", f"{spec.get('known', 'count(*)')} AS known", f"{spec.get('unknown', '0')} AS unknown",
                  f"{spec.get('numerator', 'NULL')} AS numerator", f"{spec.get('denominator', 'NULL')} AS denominator", 'max(b.at) AS watermark', 'count(*) AS sample_count']
    aggregates += [f'{expression} AS "m_{name}"' for name, expression in spec.get('measures', {}).items()]
    filters = ''
    for item in query['filters']:
        if item['dimension'] not in expressions: raise ControlError('VALIDATION_FAILED', 400)
        filters += f" AND {expressions[item['dimension']]} = ANY(%s)"
        if item['dimension'] == 'window': params.append(interval['timeZone'])
        params.append(list(item['values']))
    grouping = ', '.join(f'"d_{dim}"' for dim in group_by)
    tail = f' GROUP BY {grouping} ORDER BY {grouping}' if group_by else ''
    params.append(MAX_POINTS + 1)
    sql = f"WITH base AS ({spec['history'] if history else spec['base']}) SELECT {', '.join(selected + aggregates)} FROM base b WHERE TRUE{filters}{tail} LIMIT %s"
    return MetricStatement(metric_id, sql), params, group_by, bool(history)


def execute(service, statement, params, limit=MAX_POINTS):
    """Reader-role execution; a missing or unreadable projection yields None so the caller reports source_not_configured."""
    try: return service.store.metric_rows(statement, params, limit)
    except MISSING_SOURCE: return None


def probe(service, view):
    rows = execute(service, MetricStatement('probe', f'SELECT EXISTS(SELECT 1 FROM {view}) AS instrumented'), ())
    return bool(rows and rows[0].get('instrumented'))


def source_states(service):
    return {row['source_id']: row for row in service.store.read('sources')}


def source_stale(row, now):
    """A source recorded as stale, or whose last probe is older than STALE_AFTER_SECONDS, is not evidence that its metrics are current."""
    if not row: return False
    if row.get('state') == 'stale': return True
    checked = row.get('checked_at')
    return bool(checked) and (now - parse_stamp(checked)).total_seconds() > STALE_AFTER_SECONDS


def build_row(metric, interval, dimensions, *, value, unit, currency=None, state, known=0, unknown=0, numerator=None, denominator=None, watermark=None, sample_count=0, reason=None, measures=None, fixture=False,
              collecting_since=None, history=None):
    """One metric row. `collecting_since` (ISO 8601) names when the row's instrumentation started recording; `history`
    ({availableDays, requiredDays}) says how much history a definition still needs (reason 'insufficient_history')."""
    row = dict(metricId=metric['id'], definitionVersion=DEFINITION_VERSION, interval=dict(interval), dimensions=dict(dimensions), value=value, unit=unit,
               dataState=state, coverage=dict(known=known, unknown=unknown, numerator=numerator, denominator=denominator), sourceWatermark=watermark,
               sampleCount=sample_count, reason=reason, fixture=fixture)
    if currency: row['currency'] = currency
    if measures: row['measures'] = measures
    if collecting_since: row['collectingSince'] = collecting_since
    if history: row['history'] = dict(availableDays=int(history['availableDays']), requiredDays=int(history['requiredDays']))
    return row


def _metric_rows(service, metric, query, interval, stale):
    spec = SPECS[metric['id']]
    statement, params, group_by, history = compose(metric['id'], query, interval)
    rows = execute(service, statement, params)
    if rows is None:
        return [build_row(metric, interval, {}, value=None, unit=spec['unit'], state='unavailable', reason='source_not_configured')]
    if not rows or (not group_by and rows[0]['sample_count'] == 0):
        if not probe(service, spec['history_probe'] if history else spec['probe']):
            reason = 'snapshot_history_not_collected' if history else 'not_instrumented'
            return [build_row(metric, interval, {}, value=None, unit=spec['unit'], state='unavailable', reason=reason)]
    result = []
    for row in rows:
        dimensions = {dim: row[f'd_{dim}'] for dim in group_by}
        known, unknown = number(row['known']), number(row['unknown'])
        currency = spec.get('currency')
        currency = row.get('d_currency') if currency == 'b.currency' else currency.strip("'") if currency else None
        state, reason = spec.get('state', 'measured'), spec.get('reason')
        if unknown: state, reason = 'partial', spec.get('unknown_reason')
        if stale and state == 'measured': state, reason = 'stale', 'source_stale'
        if spec.get('currency') == 'b.currency' and not currency: state, reason = 'partial', 'currency_missing'
        measures = {name: number(row[f'm_{name}']) for name in spec.get('measures', {})} or None
        result.append(build_row(metric, interval, dimensions, value=number(row['value']), unit=spec['unit'], currency=currency, state=state, known=known, unknown=unknown,
                                numerator=number(row['numerator']), denominator=number(row['denominator']), watermark=row['watermark'], sample_count=number(row['sample_count']),
                                reason=reason, measures=measures))
    return result


def _snapshot_comparison(service, metric, query, interval):
    """A snapshot metric compares against the daily snapshot taken on the interval's first local day."""
    spec = SPECS[metric['id']]
    if not spec.get('history'): return None
    zone = ZoneInfo(interval['timeZone'])
    day = parse_stamp(interval['start']).astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    history = dict(start=stamp(day), end=stamp(day + timedelta(days=1)), timeZone=interval['timeZone'])
    shifted = {**query, 'groupBy': [dim for dim in query['groupBy'] if dim != 'window'] + ['window'], 'comparison': 'none'}
    return [{**row, 'dimensions': {key: value for key, value in row['dimensions'].items() if key != 'window'}} for row in _metric_rows(service, metric, shifted, history, False)]


def _heartbeat_rows(metric, query, sources, now):
    row = sources.get('cron')
    interval = interval_of(query)
    if not row or not row.get('checked_at'):
        return [build_row(metric, interval, {}, value=None, unit='seconds', state='unavailable', reason='no_heartbeat_recorded')]
    age = max(0, int((now - parse_stamp(row['checked_at'])).total_seconds()))
    state = 'stale' if age > HEARTBEAT_STALE_SECONDS or row.get('state') == 'stale' else 'measured' if row.get('state') == 'measured' else row.get('state', 'unavailable')
    return [build_row(metric, interval, {}, value=age, unit='seconds', state=state, known=1, watermark=row.get('watermark') or row['checked_at'], sample_count=1, reason=row.get('reason_code'))]


def _source_rows(metric, query, sources, now):
    interval, rows = interval_of(query), []
    wanted = [item['values'] for item in query['filters'] if item['dimension'] == 'source']
    for source_id in SOURCE_IDS:
        if wanted and not all(source_id in values for values in wanted): continue
        row = sources.get(source_id) or {}
        labels = {'source': source_id, 'state': row.get('state'), 'reason': row.get('reason_code')}
        dimensions = {dim: labels.get(dim) for dim in query['groupBy']}
        if not row:
            rows.append(build_row(metric, interval, dimensions, value=None, unit='seconds', state='unavailable', reason='no_probe_recorded'))
            continue
        age = max(0, int((now - parse_stamp(row['watermark'])).total_seconds())) if row.get('watermark') else None
        state, reason = row['state'], row.get('reason_code')
        if state == 'measured' and source_stale(row, now): state, reason = 'stale', 'lagging'
        if 'state' in dimensions: dimensions['state'] = state
        if 'reason' in dimensions: dimensions['reason'] = reason
        rows.append(build_row(metric, interval, dimensions, value=age, unit='seconds', state=state, known=1, watermark=row.get('watermark'), sample_count=1, reason=reason))
    return rows


def _cost_vs_cash(service, metric, query, interval, stale):
    cash_query = {**query, 'groupBy': ['currency'] + [dim for dim in query['groupBy'] if dim == 'window'], 'comparison': 'none', 'filters': []}
    cost_query = {**query, 'groupBy': [dim for dim in query['groupBy'] if dim == 'window'], 'comparison': 'none', 'filters': []}
    cash = _metric_rows(service, {**metric, 'id': 'cash_collected'}, cash_query, interval, stale)
    cost = _metric_rows(service, {**metric, 'id': 'ai_cost_actual'}, cost_query, interval, stale)
    cost_by_window = {row['dimensions'].get('window'): row for row in cost}
    rows = []
    for row in cash:
        window = row['dimensions'].get('window')
        cost_row = cost_by_window.get(window)
        dimensions = {dim: row['dimensions'].get(dim) for dim in query['groupBy']}
        if row['dataState'] == 'unavailable' or cost_row is None or cost_row['dataState'] == 'unavailable':
            rows.append(build_row(metric, interval, dimensions, value=None, unit='ratio', currency=row.get('currency'), state='unavailable', reason='side_unavailable'))
            continue
        cash_micro = (row['value'] or 0) * 10000
        if row.get('currency') != 'USD':
            rows.append(build_row(metric, interval, dimensions, value=None, unit='ratio', currency=row.get('currency'), state='not_applicable', numerator=cost_row['value'], denominator=cash_micro, reason='currency_not_comparable'))
        elif not cash_micro:
            rows.append(build_row(metric, interval, dimensions, value=None, unit='ratio', currency='USD', state='not_applicable', numerator=cost_row['value'], denominator=0, reason='zero_cash_denominator'))
        else:
            state = 'partial' if cost_row['coverage']['unknown'] else 'stale' if stale else 'measured'
            rows.append(build_row(metric, interval, dimensions, value=cost_row['value'] / cash_micro, unit='ratio', currency='USD', state=state, known=cost_row['coverage']['known'],
                                  unknown=cost_row['coverage']['unknown'], numerator=cost_row['value'], denominator=cash_micro, watermark=max(filter(None, (row['sourceWatermark'], cost_row['sourceWatermark'])), default=None),
                                  sample_count=row['sampleCount'] + cost_row['sampleCount'], reason='unsettled_cost_rows' if cost_row['coverage']['unknown'] else None))
    if not rows:
        rows.append(build_row(metric, interval, {dim: None for dim in query['groupBy']}, value=None, unit='ratio', state='not_applicable', reason='no_cash_in_interval'))
    return rows


def compute(service, query, metrics):
    """Rows for activated metrics in one query; comparison rows are matched by non-window dimensions."""
    if query['comparison'] == 'cohort_age_aligned': raise ControlError('VALIDATION_FAILED', 400)
    if query['comparison'] != 'none' and 'window' in query['groupBy']: raise ControlError('VALIDATION_FAILED', 400)
    load_extensions()
    now, sources, interval, rows = service.clock(), source_states(service), interval_of(query), []
    for metric in metrics:
        stale = source_stale(sources.get(METRIC_SOURCES.get(metric['id'])), now)
        custom = CUSTOM.get(metric['id'])
        if not known(metric['id']):
            # Activated in the catalog but its slice did not load in this process: say so, never zero, never a 503 for the rest.
            rows.append(build_row(metric, interval, {}, value=None, unit=metric['unit'], state='unavailable', reason='adapter_unavailable'))
            continue
        if metric['id'] == 'cron_heartbeat': current = _heartbeat_rows(metric, query, sources, now)
        elif metric['id'] == 'source_health': current = _source_rows(metric, query, sources, now)
        elif metric['id'] in COMPOSITE: current = _cost_vs_cash(service, metric, query, interval, stale)
        elif custom: current = custom['rows'](service, metric, query, interval, stale)
        else: current = _metric_rows(service, metric, query, interval, stale)
        if query['comparison'] != 'none':
            spec = SPECS.get(metric['id'], {})
            if metric['id'] in PYTHON_ONLY: previous = None
            elif custom:
                compare = custom.get('previous', custom['rows'])
                previous = compare(service, metric, {**query, 'comparison': 'none'}, previous_interval(query), stale) if compare else None
            elif spec.get('snapshot'): previous = _snapshot_comparison(service, metric, query, interval)
            elif metric['id'] in COMPOSITE: previous = _cost_vs_cash(service, metric, query, previous_interval(query), stale)
            else: previous = _metric_rows(service, metric, query, previous_interval(query), stale)
            lookup = {tuple(sorted(row['dimensions'].items())): row for row in previous or []}
            for row in current:
                match = lookup.get(tuple(sorted(row['dimensions'].items())))
                row['comparison'] = dict(interval=match['interval'], value=match['value'], dataState=match['dataState'], coverage=match['coverage']) if match else dict(interval=None, value=None, dataState='unavailable', coverage=None)
        rows.extend(current)
    coverage = dict(complete=all(row['dataState'] == 'measured' for row in rows), returnedRows=len(rows), populationTotal=None, inputLimit=MAX_POINTS,
                    reason='activated_v1' if rows else 'no_rows')
    versions = dict(adapter=ADAPTER, migration='054_rafii_control_founder_views', timeZone=query['interval']['timeZone'], sources={metric['id']: METRIC_SOURCES.get(metric['id']) for metric in metrics})
    return rows, coverage, versions


def unknown_reservations(principal, mode, service, limit=200, demo_data=None):
    """The reconcile queue: ledger rows whose provider cost is still unknown (GET /usage/unknown)."""
    from .intelligence import QueryService, MODES
    QueryService.require(principal, 'metrics.query')
    if mode not in MODES or type(limit) is not int or not 1 <= limit <= 1000: raise ControlError('VALIDATION_FAILED', 400)
    if mode == 'demo':
        data = demo_data if demo_data is not None else service.demo_data(principal)
        rows = [dict(id=row['id'], workspaceId=row.get('workspaceId'), runId=None, kind=row.get('kind'), dimension=row.get('dimension'), provider=None, model=None,
                     feature=row.get('feature', 'writer'), estimatedUsdMicro=row.get('estimatedUsdMicro'), at=row.get('at'))
                for row in data.get('usage', []) if row.get('costState') == 'estimated_unknown']
        rows.sort(key=lambda row: (row['at'] or '', row['id']), reverse=True)
        return dict(mode=mode, rows=rows[:limit], truncated=len(rows) > limit, limit=limit, _dataState='synthetic', _receiptIds=[data['receipt']['id']] if data.get('receipt') else [])
    rows = execute(service, UNKNOWN_RESERVATIONS, (limit + 1,), limit + 1)
    if rows is None: return dict(mode=mode, rows=[], truncated=False, limit=limit, reason='source_not_configured', _dataState='unavailable')
    return dict(mode=mode, rows=rows[:limit], truncated=len(rows) > limit, limit=limit, _dataState='measured')


# ---- Overview (GET /overview?mode=&period=) ------------------------------------------------------------------

TILES = (('paid_customers', 'Paid customers', '/founder/customers', 'count'), ('mrr', 'MRR', '/founder/revenue?tab=mrr-bridge', 'currency_minor'),
         ('cash_collected', 'Cash collected (MTD)', '/founder/revenue?tab=cash', 'currency_minor'), ('ai_cost_actual', 'AI cost (MTD)', '/founder/ai-cost', 'usd_micro'),
         ('publish_outcomes', 'Publishing success (7d)', '/founder/operations?tab=publishing', 'ratio'))
SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}
ACTION_LABELS = {'explain': 'Explain', 'open': 'Open', 'draft_reminder': 'Draft reminder', 'ack': 'Acknowledge'}


def _actions(kinds, href, incident=None):
    """§3 attention actions: `{id, label, kind, href}`; an `ack` names the incident and the exact version it would acknowledge."""
    out = []
    for kind in kinds:
        action = dict(id=kind, label=ACTION_LABELS[kind], kind=kind, href=href if kind == 'open' else None)
        if kind == 'ack':
            if incident is None or incident.get('version') is None: continue   # never acknowledge an unknown version
            action.update(incidentId=incident.get('id'), version=int(incident['version']))
        out.append(action)
    return out


def period_windows(now, period, time_zone):
    zone = ZoneInfo(time_zone)
    local = now.astimezone(zone)
    days = PERIODS[period]
    month_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    def window(start, end): return dict(start=stamp(start), end=stamp(max(end, start + timedelta(minutes=1))), timeZone=time_zone)
    return dict(period=window(local - timedelta(days=days), local), previous=window(local - timedelta(days=2 * days), local - timedelta(days=days)),
                mtd=window(month_start, local), week=window(local - timedelta(days=7), local), day=window(local.replace(hour=0, minute=0, second=0, microsecond=0), local))


def _first_row(result, prefer=None):
    rows = result['rows']
    if prefer: rows = [row for row in rows if row.get('currency') == prefer] or rows
    return rows[0] if rows else None


def _ratio(row):
    coverage = row.get('coverage') or {}
    if row['dataState'] in ('unavailable', 'suppressed') or not coverage.get('denominator'): return None
    return coverage['numerator'] / coverage['denominator']


def _tile(metric_id, label, href, unit, result, sparkline, *, ratio=False, prefer=None):
    row = _first_row(result, prefer)
    if row is None:
        # Grouped SQL over an instrumented source with no rows in the period is a measured zero; anything else stays unavailable.
        measured = result['dataState'] == 'measured' and result['executionState'] in ('admitted_operational', 'demo_dataset')
        return dict(id=metric_id, label=label, value=0 if measured and not ratio else None, unit=unit, currency='USD' if measured and unit != 'count' else None, delta=None, deltaPeriod=None,
                    sparkline=[], dataState='measured' if measured else 'unavailable', coverage=None, receiptId=result['queryReceiptId'], href=href, reason=None if measured else 'no_rows')
    value = _ratio(row) if ratio else row['value']
    comparison = row.get('comparison') or {}
    previous = (_ratio(comparison) if ratio and comparison.get('coverage') else comparison.get('value')) if comparison else None
    delta = (value - previous) if value is not None and previous is not None else None
    points = [dict(window=point['dimensions'].get('window'), value=_ratio(point) if ratio else point['value'], dataState=point['dataState'])
              for point in (sparkline['rows'] if sparkline else []) if point['dimensions'].get('window')]
    return dict(id=metric_id, label=label, value=value, unit='ratio' if ratio else row['unit'], currency=row.get('currency'), delta=delta,
                deltaPeriod=(comparison.get('interval') or {}).get('start') if comparison else None, sparkline=points, dataState=row['dataState'], coverage=row.get('coverage'),
                receiptId=result['queryReceiptId'], href=href, reason=row.get('reason'))


def _series(result, *, ratio=False, scale=1):
    return [dict(window=row['dimensions'].get('window'), value=None if row['value'] is None else (_ratio(row) if ratio else row['value'] * scale), dataState=row['dataState'])
            for row in result['rows'] if row['dimensions'].get('window')]


def _trend_series(series_id, label, result, *, unit, currency=None, ratio=False, scale=1):
    """One §3 trend series: `{id, label, unit, currency, dataState, receiptId, points:[{t, value, dataState}]}` from a window-grouped result."""
    points = [dict(t=point['window'], value=point['value'], dataState=point['dataState']) for point in _series(result, ratio=ratio, scale=scale)]
    return dict(id=series_id, label=label, unit=unit, currency=currency, dataState=result['dataState'], receiptId=result['queryReceiptId'], points=points)


def _trend(trend_id, title, period, series, *, unit, currency=None, definition=None):
    """§3 trend payload (web `OverviewTrend`): a list of series on one axis, every receipt behind them and one overall data state."""
    states = {item['dataState'] for item in series}
    data_state = next(iter(states)) if len(states) == 1 else 'partial'
    receipt_ids = [item['receiptId'] for item in series]
    return dict(id=trend_id, title=title, period=period, unit=unit, currency=currency, series=series, receiptId=receipt_ids[0] if receipt_ids else None,
                receiptIds=receipt_ids, dataState=data_state, definition=definition)


def _attention(results, incidents, now):
    items = []
    failures = results['payment_failures']['rows']
    count = sum(row['value'] or 0 for row in failures if row['value'] is not None)
    if count:
        items.append(dict(id='payment_failures_7d', severity='critical' if count >= 5 else 'warning', title=f'{count} payment failure{"s" if count != 1 else ""} in the last 7 days',
                          scope='billing', count=count, since=results['payment_failures']['normalizedQuery']['interval']['start'], href='/founder/revenue?tab=payments', actions=_actions(('explain', 'open', 'draft_reminder'), '/founder/revenue?tab=payments'), receiptId=results['payment_failures']['queryReceiptId']))
    unknown = results['ai_cost_unknown']['rows']
    pending = sum(row['coverage']['known'] or 0 for row in unknown if row['dataState'] != 'unavailable')
    if pending:
        items.append(dict(id='ai_cost_unknown_30d', severity='warning', title=f'{pending} AI cost row{"s" if pending != 1 else ""} still unsettled', scope='ai_cost', count=pending,
                          since=results['ai_cost_unknown']['normalizedQuery']['interval']['start'], href='/founder/ai-cost?tab=reconcile', actions=_actions(('explain', 'open'), '/founder/ai-cost?tab=reconcile'), receiptId=results['ai_cost_unknown']['queryReceiptId']))
    for row in results['budget_remaining']['rows']:
        stop = (row.get('coverage') or {}).get('denominator')
        if row['dataState'] == 'measured' and stop and row['value'] is not None and row['value'] < stop * 0.2:
            items.append(dict(id='budget_' + str(row['dimensions'].get('scope')), severity='critical' if row['value'] < stop * 0.1 else 'warning', title=f"Budget {row['dimensions'].get('scope')} has {max(row['value'], 0)} USD micro remaining",
                              scope='ai_cost', count=1, since=None, href='/founder/ai-cost?tab=budget', actions=_actions(('explain', 'open'), '/founder/ai-cost?tab=budget'), receiptId=results['budget_remaining']['queryReceiptId']))
    backlog = [row for row in results['data_requests_backlog']['rows'] if row['value']]
    if backlog:
        total = sum(row['value'] for row in backlog)
        items.append(dict(id='data_requests_backlog', severity='critical' if any(row['dimensions'].get('age_band') == 'over_7d' for row in backlog) else 'warning', title=f'{total} data request{"s" if total != 1 else ""} waiting',
                          scope='support', count=total, since=None, href='/founder/support?tab=inbox', actions=_actions(('explain', 'open'), '/founder/support?tab=inbox'), receiptId=results['data_requests_backlog']['queryReceiptId']))
    stale = [row for row in results['source_health']['rows'] if row['dataState'] in ('stale', 'unavailable') and row['dimensions'].get('source') != 'cron' and row['sourceWatermark']]
    if stale:
        items.append(dict(id='sources_stale', severity='warning', title=f'{len(stale)} data source{"s" if len(stale) != 1 else ""} stale', scope='data_health', count=len(stale),
                          since=min(row['sourceWatermark'] for row in stale), href='/founder/advanced?tab=data-health', actions=_actions(('explain', 'open'), '/founder/advanced?tab=data-health'), receiptId=results['source_health']['queryReceiptId']))
    heartbeat = results['cron_heartbeat']['rows'][0]
    if heartbeat['dataState'] in ('stale', 'unavailable'):
        items.append(dict(id='cron_heartbeat', severity='warning', title='Background worker heartbeat ' + ('stale' if heartbeat['dataState'] == 'stale' else 'not recorded'), scope='operations', count=1,
                          since=heartbeat.get('sourceWatermark'), href='/founder/operations?tab=health', actions=_actions(('explain', 'open'), '/founder/operations?tab=health'), receiptId=results['cron_heartbeat']['queryReceiptId']))
    for incident in incidents:
        href = f"/founder/operations?incident={incident.get('id')}"
        items.append(dict(id='incident_' + str(incident.get('id')), severity=incident.get('severity', 'warning'), title=incident.get('title', 'Open incident'), scope='incident',
                          count=incident.get('affectedCount', incident.get('affected_count', 0)), since=incident.get('observedAt', incident.get('opened_at')), href=href,
                          actions=_actions(('explain', 'open', 'ack'), href, incident=incident)))
    items.sort(key=lambda item: (SEVERITY_ORDER.get(item['severity'], 3), item['id']))
    return items[:5]


def _open_incidents(service, principal, mode, data):
    if mode == 'demo': return [row for row in (data or {}).get('incidents', []) if row.get('state') != 'resolved']
    try:
        from . import founder_incidents
    except ImportError: return []
    reader = getattr(founder_incidents, 'open_incidents', None)
    if reader is None: return []
    try: return list(reader(service, principal))
    except ControlError: return []


def _money(row):
    if row is None or row['value'] is None: return 'unavailable'
    if row['unit'] == 'usd_micro': return f"USD {row['value'] / 1_000_000:,.2f}"
    if row['unit'] == 'currency_minor': return f"{row.get('currency') or ''} {row['value'] / 100:,.2f}".strip()
    return f"{row['value']:,}"


def _delta_text(tile):
    """The comparison clause of one brief sentence, in the tile's own unit (money as money, ratios as points)."""
    delta = tile.get('delta')
    if delta is None: return ''
    sign = '+' if delta >= 0 else '-'
    if tile['unit'] == 'ratio': return f" ({sign}{abs(delta) * 100:.1f} pts vs previous)"
    if tile['unit'] in ('usd_micro', 'currency_minor'):
        return f" ({sign}{_money(dict(value=abs(delta), unit=tile['unit'], currency=tile.get('currency')))} vs previous)"
    return f" ({sign}{abs(delta):,} vs previous)"


def _brief(tiles, attention, sources, mode, period):
    sentences = [('Demo dataset' if mode == 'demo' else 'Live') + f' overview for the last {PERIODS[period]} days; every number carries a receipt and a data state.']
    for tile in tiles:
        if tile['dataState'] in ('unavailable', 'suppressed'):
            sentences.append(f"{tile['label']}: not yet collected ({tile.get('reason') or 'definition not activated'}).")
            continue
        value = f"{tile['value'] * 100:.1f}%" if tile['unit'] == 'ratio' else _money(dict(value=tile['value'], unit=tile['unit'], currency=tile['currency']))
        sentences.append(f"{tile['label']}: {value}{_delta_text(tile)}, {tile['dataState']}.")
    sentences.append('Nothing needs a decision right now.' if not attention else f"{len(attention)} item{'s' if len(attention) != 1 else ''} need attention: " + '; '.join(item['title'] for item in attention) + '.')
    degraded = [row['sourceId'] for row in sources if row['state'] in ('stale', 'unavailable')]
    sentences.append('All probed sources are current.' if not degraded else 'Sources not current: ' + ', '.join(degraded) + '. Treat affected metrics as incomplete, not as zero.')
    return ' '.join(sentences)


def overview(principal, mode, period, service, request_id=None):
    """§3 Overview payload: pulse tiles, attention rules, two trends, source health and a deterministic brief.

    Demo reads the founder's own Demo dataset as of its asOf; Live reads the 054 projections.
    Each number comes from a receipted metric query; nothing is computed by the browser.
    """
    from .intelligence import QueryService, MODES
    QueryService.require(principal, 'control.read')
    QueryService.require(principal, 'metrics.query')
    if mode not in MODES or period not in PERIODS: raise ControlError('VALIDATION_FAILED', 400)
    data = service.demo_data(principal) if mode == 'demo' else None
    # Demo records stamped exactly at asOf belong to the snapshot, so its exclusive upper bound sits one second later.
    now = parse_stamp(data['asOf']) + timedelta(seconds=1) if mode == 'demo' else service.clock()
    windows = period_windows(now, period, TIME_ZONE)
    receipts = []

    def run(metric_id, interval, group_by=(), comparison='none'):
        query = dict(metricIds=[metric_id], interval=interval, groupBy=list(group_by), filters=[], comparison=comparison, limit=MAX_POINTS)
        result = service.metric_query(query, principal, str(uuid.uuid4()), mode=mode, demo_data=data)
        receipts.append(result['queryReceiptId'])
        return result

    results = dict(paid_customers=run('paid_customers', windows['period'], comparison='previous_equal_elapsed'), paid_customers_series=run('paid_customers', windows['period'], ['window']),
                   mrr=run('mrr', windows['period'], ['currency']), cash_mtd=run('cash_collected', windows['mtd'], ['currency'], 'previous_complete'),
                   cash_series=run('cash_collected', windows['period'], ['currency', 'window']), cost_mtd=run('ai_cost_actual', windows['mtd'], comparison='previous_complete'),
                   cost_series=run('ai_cost_actual', windows['period'], ['window']), publish_week=run('publish_outcomes', windows['week'], comparison='previous_equal_elapsed'),
                   publish_series=run('publish_outcomes', windows['period'], ['window']), active_series=run('active_workspaces', windows['period'], ['window']),
                   payment_failures=run('payment_failures', windows['week']), ai_cost_unknown=run('ai_cost_unknown', windows['period']), budget_remaining=run('budget_remaining', windows['day']),
                   data_requests_backlog=run('data_requests_backlog', windows['day'], ['kind', 'age_band']), source_health=run('source_health', windows['day'], ['source', 'state', 'reason']),
                   cron_heartbeat=run('cron_heartbeat', windows['day']))
    usd_cash = {**results['cash_series'], 'rows': [row for row in results['cash_series']['rows'] if row.get('currency') in (None, 'USD')]}
    tiles = [_tile(*TILES[0], results['paid_customers'], results['paid_customers_series']),
             _tile(*TILES[1], results['mrr'], None),
             _tile(*TILES[2], results['cash_mtd'], usd_cash, prefer='USD'),
             _tile(*TILES[3], results['cost_mtd'], results['cost_series']),
             _tile(*TILES[4], results['publish_week'], results['publish_series'], ratio=True)]
    sources = [dict(sourceId=row['dimensions'].get('source'), state=row['dataState'] if row['dataState'] != 'unavailable' else 'unavailable', lastGoodAt=row['sourceWatermark'], reasonCode=row.get('reason'))
               for row in results['source_health']['rows']]
    attention = _attention(results, _open_incidents(service, principal, mode, data), now)
    trends = dict(revenueVsCost=_trend('revenue_vs_cost', 'Revenue vs AI cost', period,
                                       [_trend_series('cash_collected', 'Cash collected', usd_cash, unit='usd_micro', currency='USD', scale=10000),
                                        _trend_series('ai_cost_actual', 'AI cost (actual)', results['cost_series'], unit='usd_micro', currency='USD')],
                                       unit='usd_micro', currency='USD', definition='Cash minor units are scaled to USD micro server-side; non-USD cash is excluded from this chart.'),
                  activeVsPublish=_trend('active_vs_publish', 'Active workspaces vs publishing', period,
                                         [_trend_series('active_workspaces', 'Active workspaces', results['active_series'], unit='count'),
                                          _trend_series('publish_outcomes', 'Publish outcomes', results['publish_series'], unit='count')],
                                         unit='count', definition='Workspaces with a run, event or publish per day beside all publish outcomes recorded that day.'))
    return dict(mode=mode, period=period, asOf=stamp(now), timeZone=TIME_ZONE, pulse=tiles, attention=attention, trends=trends, sourceHealth=sources,
                brief=dict(text=_brief(tiles, attention, sources, mode, period), receiptIds=list(receipts)), _receiptIds=list(receipts),
                _dataState='synthetic' if mode == 'demo' else ('partial' if any(tile['dataState'] != 'measured' for tile in tiles) else 'measured'))
