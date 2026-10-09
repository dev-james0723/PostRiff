"""Founder Admin P1/P2 slice 8.D: reliability, operations and support (CONTRACTS §8.D; PRD §5.3, §7.1 M22/M25-M31, §7.2,
§7.3, §8.7, §10.2 P1-4/P1-7, §13.4).

Registers at import (rafii_control.slices):
- Live metrics over the 066 projections, read through the restricted reader role with fixed parameterised SQL, half-open
  intervals and the report time zone: api_error_rate, api_latency, queue_health, connection_health, publish_by_provider,
  slo_burn, support_aging.
- Demo parity: support_aging from the Demo inbox records (the same stand-in data_requests_backlog uses); the others are
  demo_not_simulated, never a zero.
- Cron stages: operational_snapshot (each tick), connection_health (hourly), reliability_purge (daily, 03:00 local).
- Route: GET /incidents/{id}?mode= (control.read), one incident with its timeline for the Operations swimlane.

Honest states. A projection that is not installed is 'source_not_configured'; an installed but empty one 'not_instrumented';
an interval that starts before the first retained row is 'partial' with collectingSince (reason collecting_since, or
retention_limited once the 30-day purge is the cause). Percentiles come from summed histogram buckets and are never averaged;
fewer than 30 requests is 'partial' (small_sample). The SLO burn rate is measured against a PROPOSED 99.5% target that nobody
has approved, and every row says so. Request metrics have no workspace, so internal or test traffic cannot be excluded at
the route level; the catalog limitations say so.

Stages write public tables over the consumer connection. Production may run this code before 060 is applied, so each stage
checks its table first: a missing table or privilege is 'not installed yet', logged once per process (class only) and the
stage pauses for ten minutes. Stages never raise into the tick.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import json
import logging
import re
from zoneinfo import ZoneInfo

from . import demo_metrics, founder_cron, http, live_metrics
from .auth import ControlError
from .live_metrics import (MAX_POINTS, PUBLISH_EVENTS, TIME_ZONE, WINDOW, build_row, excluded, execute, interval_clause, number,
                           parse_stamp, stamp)
from .store import MetricStatement

# Histogram upper bounds (ms) of the first 19 buckets; the 20th is open-ended. Must equal postriff_phase2.request_metrics.BOUNDS_MS.
BOUNDS_MS = (10, 25, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 20000, 30000)
PERCENTILES = (('p50', 0.5), ('p95', 0.95))
SMALL_SAMPLE = 30
RETENTION_DAYS = 30
REQUEST_LAG_SECONDS = 20 * 60        # the cron alone requests every minute, so twenty silent minutes mean the writer stopped
SNAPSHOT_LAG_SECONDS = 10 * 60
PROJECTION_LAG_SECONDS = 3 * 3600
HOUR = "to_char(date_trunc('hour', b.at AT TIME ZONE %s),'YYYY-MM-DD\"T\"HH24:00')"
TIME_DIMS = ('window', 'hour')
REQUEST_VIEW = 'rafii_control.business_request_metrics'
SNAPSHOT_VIEW = 'rafii_control.business_operational_snapshots'
CONNECTION_VIEW = 'rafii_control.business_connection_health'
REQUESTS_VIEW = 'rafii_control.business_data_requests_v2'
EVENTS_VIEW = 'rafii_control.business_notification_events'

# SRE workbook multi-window burn rates (PRD §13.4) against a proposed target: burn = error ratio / (1 - target). A pair alerts
# only when both of its windows exceed the threshold with enough events; fewer than MIN_BURN_EVENTS is 'low_traffic'.
SLO_TARGET = 0.995
SLO_LABEL = 'proposed SLO, not approved'
BURN_WINDOWS = (('5m', 5), ('30m', 30), ('1h', 60), ('6h', 360))
BURN_PAIRS = {'1h/5m': ('1h', '5m', 14.4), '6h/30m': ('6h', '30m', 6.0)}
MIN_BURN_EVENTS = 20

# operational_signals.snapshot counters grouped into the queues the Operations jobs tab shows; SMS signals arrive as 'sms.*'.
COUNTER_QUEUES = {
    'publicationUncertain': 'publishing', 'queueDelayed': 'publishing', 'publicationFailed': 'publishing', 'publicationHeld': 'publishing',
    'modelStuck': 'model_runs', 'researchStuck': 'model_runs', 'costUnsettled': 'cost', 'budgetStops': 'cost', 'budgetWarnings': 'cost',
    'billingRejected24h': 'billing', 'notificationsUnsent': 'notifications', 'notificationBacklog': 'notifications', 'notificationDead24h': 'notifications',
    'deletionPending': 'privacy', 'historyPurgesPending': 'privacy', 'metricReadsOverdue': 'growth', 'metricBackfillStale': 'growth',
    'metricReadsDead24h': 'growth', 'historyImportsFailed24h': 'growth',
}
AGE_BANDS = (('under_1d', 1), ('1d_to_3d', 3), ('3d_to_7d', 7), ('7d_to_14d', 14), ('14d_to_30d', 30))
LOGGER = logging.getLogger('rafii_control.founder_ops')
# Quoted projection columns used inside the fixed statements below.
H_WORKSPACE, E_WORKSPACE, E_OCCURRED = 'h."workspaceId"', 'e."workspaceId"', 'e."occurredAt"'
Q_WORKSPACE, Q_REQUESTED = 'q."workspaceId"', 'q."requestedAt"'


# ---- shared helpers --------------------------------------------------------------------------------------------------------
def _now(service):
    return service.clock()


def _unavailable(metric, interval, reason, *, dims=None, unit=None, fixture=False, collecting_since=None):
    return [build_row(metric, interval, dims or {}, value=None, unit=unit or metric['unit'], state='unavailable', reason=reason, fixture=fixture,
                      collecting_since=collecting_since)]


def _coverage(service, metric_id, view, column):
    """Earliest/latest retained row of a projection, or None when the projection is not installed (source_not_configured)."""
    rows = execute(service, MetricStatement(metric_id + ':coverage', f'SELECT min({column}) AS earliest, max({column}) AS latest FROM {view}'), ())
    if rows is None:
        return None
    row = rows[0] if rows else {}
    return dict(earliest=row.get('earliest'), latest=row.get('latest'))


def _gap(interval, coverage, now):
    """(reason, nothing_collected) when the interval starts before the first retained row, else (None, False)."""
    earliest = parse_stamp(coverage['earliest'])
    if parse_stamp(interval['start']) >= earliest:
        return None, False
    reason = 'retention_limited' if earliest <= now - timedelta(days=RETENTION_DAYS - 1) else 'collecting_since'
    return reason, parse_stamp(interval['end']) <= earliest


def _lagging(coverage, interval, now, seconds):
    """The interval reaches into the last `seconds`, yet the newest retained row is older than that: the writer stopped."""
    latest = coverage.get('latest')
    if not latest:
        return False
    end = min(parse_stamp(interval['end']), now)
    return (now - end).total_seconds() < seconds and (now - parse_stamp(latest)).total_seconds() > seconds


def _finish(state, reason, *, gap=None, lagging=None, stale=False):
    if gap and state == 'measured':
        state, reason = 'partial', gap
    if lagging and state in ('measured', 'partial'):
        state, reason = 'stale', lagging
    if stale and state == 'measured':
        state, reason = 'stale', 'source_stale'
    return state, reason


def _filter_values(query, dimension):
    sets = [set(item['values']) for item in query['filters'] if item['dimension'] == dimension]
    return set.intersection(*sets) if sets else None


def _no_hour_comparison(query):
    if query['comparison'] != 'none' and 'hour' in query['groupBy']:
        raise ControlError('VALIDATION_FAILED', 400)


def _compose(metric_id, query, base, base_params, dims, aggregates, *, implicit=(), python_dims=(), time=True, limit=MAX_POINTS):
    """WITH base AS (<fixed base>) SELECT <dims>, <aggregates> FROM base b WHERE TRUE <filters> GROUP BY <dims> LIMIT %s.
    Dimension and filter names resolve to the fixed expressions here; filter values and the time zone are bound parameters.
    Dimensions in python_dims are expanded by the caller and never reach SQL."""
    expressions = {**dims, **({'window': WINDOW, 'hour': HOUR} if time else {})}
    group_by = list(implicit) + [dim for dim in query['groupBy'] if dim not in implicit and dim not in python_dims]
    tz, params, selected = query['interval']['timeZone'], list(base_params), []
    for dim in group_by:
        if dim not in expressions:
            raise ControlError('VALIDATION_FAILED', 400)
        selected.append(f'{expressions[dim]} AS "d_{dim}"')
        if dim in TIME_DIMS:
            params.append(tz)
    filters = ''
    for item in query['filters']:
        if item['dimension'] in python_dims:
            continue
        if item['dimension'] not in expressions:
            raise ControlError('VALIDATION_FAILED', 400)
        filters += f" AND {expressions[item['dimension']]} = ANY(%s)"
        if item['dimension'] in TIME_DIMS:
            params.append(tz)
        params.append(list(item['values']))
    grouping = ', '.join(f'"d_{dim}"' for dim in group_by)
    tail = f' GROUP BY {grouping} ORDER BY {grouping}' if group_by else ''
    params.append(limit + 1)
    columns = ', '.join(selected + [f'{expression} AS {alias}' for alias, expression in aggregates])
    return MetricStatement(metric_id, f'WITH base AS ({base}) SELECT {columns} FROM base b WHERE TRUE{filters}{tail} LIMIT %s'), params, group_by


def _dimensions(row, group_by):
    return {dim: row.get(f'd_{dim}') for dim in group_by}


# ---- api_error_rate / api_latency (M25) --------------------------------------------------------------------------------------
REQUEST_BASE = ('SELECT r.minute AS at, r."routePattern" AS route, r."statusClass" AS status_class, r."requestCount" AS requests, r."durationBuckets" AS buckets'
                f' FROM {REQUEST_VIEW} r WHERE {interval_clause("r.minute")}')
REQUEST_DIMS = {'route': 'b.route'}


def _request_coverage(service, metric, interval, now):
    """(coverage, early rows): early rows answer the query when the projection is missing, empty or did not cover it."""
    coverage = _coverage(service, metric['id'], REQUEST_VIEW, 'minute')
    if coverage is None:
        return None, _unavailable(metric, interval, 'source_not_configured')
    if not coverage['earliest']:
        return None, _unavailable(metric, interval, 'not_instrumented')
    gap, nothing = _gap(interval, coverage, now)
    if nothing:
        return None, _unavailable(metric, interval, gap, collecting_since=coverage['earliest'])
    return dict(coverage, gap=gap), None


def api_error_rate_rows(service, metric, query, interval, stale):
    """5xx / all requests per route pattern and period; the zero-request case is not_applicable, never 0%."""
    _no_hour_comparison(query)
    now = _now(service)
    coverage, early = _request_coverage(service, metric, interval, now)
    if early:
        return early
    statement, params, group_by = _compose(metric['id'], query, REQUEST_BASE, [interval['start'], interval['end']], REQUEST_DIMS,
                                           [('requests', 'sum(b.requests)'), ('errors', "coalesce(sum(b.requests) FILTER (WHERE b.status_class='5xx'),0)"),
                                            ('client_errors', "coalesce(sum(b.requests) FILTER (WHERE b.status_class='4xx'),0)"),
                                            ('watermark', 'max(b.at)'), ('sample_count', 'count(*)')])
    rows = execute(service, statement, params)
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    lagging = 'request_metrics_lagging' if _lagging(coverage, interval, now, REQUEST_LAG_SECONDS) else None
    since = coverage['earliest'] if coverage['gap'] else None
    out = []
    for row in rows:
        requests, errors, client = number(row['requests']) or 0, number(row['errors']) or 0, number(row['client_errors']) or 0
        if not requests:
            if group_by:
                continue
            state, reason = _finish('not_applicable', 'no_requests', lagging=lagging)
            out.append(build_row(metric, interval, {}, value=None, unit='ratio', state=state, numerator=0, denominator=0, reason=reason, collecting_since=since))
            continue
        state, reason = _finish('measured', None, gap=coverage['gap'], lagging=lagging, stale=stale)
        out.append(build_row(metric, interval, _dimensions(row, group_by), value=errors / requests, unit='ratio', state=state, known=requests, unknown=0,
                             numerator=errors, denominator=requests, watermark=row['watermark'], sample_count=requests, reason=reason,
                             measures={'requests': requests, 'serverErrors': errors, 'clientErrors': client}, collecting_since=since))
    return out


def percentile(buckets, q):
    """(milliseconds, open_ended) for quantile q of a bucket histogram: linear interpolation inside the bucket that holds the
    rank (Prometheus histogram_quantile); the open-ended last bucket reports its lower bound. Never an average."""
    counts = [max(0, int(number(value) or 0)) for value in buckets or []]
    total = sum(counts)
    if total <= 0:
        return None, False
    rank, cumulative = q * total, 0
    for index, count in enumerate(counts):
        if count and cumulative + count >= rank:
            lower = float(BOUNDS_MS[index - 1]) if index else 0.0
            if index >= len(BOUNDS_MS):
                return float(BOUNDS_MS[-1]), True
            return round(lower + (BOUNDS_MS[index] - lower) * (rank - cumulative) / count, 1), False
        cumulative += count
    return float(BOUNDS_MS[-1]), True


def _latency_statement(metric_id, query, interval, limit):
    """Sum the 20 histogram buckets element-wise per group in SQL; Python turns each summed histogram into p50/p95."""
    expressions = {'route': 'b.route', 'window': WINDOW, 'hour': HOUR}
    group_by = [dim for dim in query['groupBy'] if dim != 'percentile']
    tz, params, selected = query['interval']['timeZone'], [interval['start'], interval['end']], []
    for dim in group_by:
        if dim not in expressions:
            raise ControlError('VALIDATION_FAILED', 400)
        selected.append(f'{expressions[dim]} AS "d_{dim}"')
        if dim in TIME_DIMS:
            params.append(tz)
    filters = ''
    for item in query['filters']:
        if item['dimension'] == 'percentile':
            continue
        if item['dimension'] not in expressions:
            raise ControlError('VALIDATION_FAILED', 400)
        filters += f" AND {expressions[item['dimension']]} = ANY(%s)"
        if item['dimension'] in TIME_DIMS:
            params.append(tz)
        params.append(list(item['values']))
    names = [f'"d_{dim}"' for dim in group_by]
    inner = ', '.join(names + ['i'])
    outer = ', '.join(names)
    params.append(limit + 1)
    sql = (f'WITH base AS ({REQUEST_BASE}), '
           f'cells AS (SELECT {", ".join(selected + ["b.at", "u.v", "u.i"])} FROM base b CROSS JOIN LATERAL unnest(b.buckets) WITH ORDINALITY AS u(v, i) WHERE TRUE{filters}), '
           f'totals AS (SELECT {inner}, sum(v) AS total, max(at) AS watermark FROM cells GROUP BY {inner}) '
           f'SELECT {", ".join(names + ["array_agg(total ORDER BY i) AS buckets", "max(watermark) AS watermark"])} FROM totals'
           + (f' GROUP BY {outer} ORDER BY {outer}' if names else '') + ' LIMIT %s')
    return MetricStatement(metric_id, sql), params, group_by


def api_latency_rows(service, metric, query, interval, stale):
    """p50 and p95 request duration (ms) per route pattern and period from summed histogram buckets; 'percentile' is implicit."""
    _no_hour_comparison(query)
    now = _now(service)
    wanted = _filter_values(query, 'percentile')
    percentiles = [(name, q) for name, q in PERCENTILES if wanted is None or name in wanted]
    coverage, early = _request_coverage(service, metric, interval, now)
    if early:
        return early
    statement, params, group_by = _latency_statement(metric['id'], query, interval, MAX_POINTS // len(PERCENTILES))
    rows = execute(service, statement, params, limit=MAX_POINTS // len(PERCENTILES))
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    lagging = 'request_metrics_lagging' if _lagging(coverage, interval, now, REQUEST_LAG_SECONDS) else None
    since = coverage['earliest'] if coverage['gap'] else None
    out = []
    for row in rows:
        buckets = row.get('buckets') or []
        requests = sum(max(0, int(number(value) or 0)) for value in buckets)
        dims = _dimensions(row, group_by)
        for name, q in percentiles:
            if not requests:
                if group_by:
                    continue
                state, reason = _finish('not_applicable', 'no_requests', lagging=lagging)
                out.append(build_row(metric, interval, {**dims, 'percentile': name}, value=None, unit='milliseconds', state=state, reason=reason, collecting_since=since))
                continue
            value, open_ended = percentile(buckets, q)
            state, reason = _finish('partial' if requests < SMALL_SAMPLE else 'measured', 'small_sample' if requests < SMALL_SAMPLE else None,
                                    gap=coverage['gap'], lagging=lagging, stale=stale)
            out.append(build_row(metric, interval, {**dims, 'percentile': name}, value=value, unit='milliseconds', state=state, known=requests, unknown=0,
                                 watermark=row.get('watermark'), sample_count=requests, reason=reason, measures={'requests': requests, 'openEnded': open_ended},
                                 collecting_since=since))
    return out


# ---- queue_health (M25-M27 jobs) -------------------------------------------------------------------------------------------
def _queue_case(column):
    whens = ' '.join(f"WHEN '{counter}' THEN '{queue}'" for counter, queue in COUNTER_QUEUES.items())
    return f"CASE {column} {whens} ELSE CASE WHEN starts_with({column}, 'sms.') THEN 'sms' ELSE 'other' END END"


QUEUE_BASE = (f'SELECT s.minute AS at, k.key AS counter, {_queue_case("k.key")} AS queue, (k.value #>> \'{{}}\')::numeric AS value'
              f' FROM {SNAPSHOT_VIEW} s CROSS JOIN LATERAL jsonb_each(s.counts) AS k(key, value)'
              f" WHERE jsonb_typeof(k.value)='number' AND {interval_clause('s.minute')}")


def queue_health_rows(service, metric, query, interval, stale):
    """Per operational counter (implicit) the peak over the group, with the latest reading as a measure. Counts of overdue,
    stuck and failed work per minute snapshot; there is no per-job wait distribution (jobs live in workspace state)."""
    _no_hour_comparison(query)
    now = _now(service)
    coverage = _coverage(service, metric['id'], SNAPSHOT_VIEW, 'minute')
    if coverage is None:
        return _unavailable(metric, interval, 'source_not_configured')
    if not coverage['earliest']:
        return _unavailable(metric, interval, 'not_instrumented')
    gap, nothing = _gap(interval, coverage, now)
    if nothing:
        return _unavailable(metric, interval, gap, collecting_since=coverage['earliest'])
    statement, params, group_by = _compose(metric['id'], query, QUEUE_BASE, [interval['start'], interval['end']], {'counter': 'b.counter', 'queue': 'b.queue'},
                                           [('peak', 'max(b.value)'), ('latest', '(array_agg(b.value ORDER BY b.at DESC))[1]'), ('latest_at', 'max(b.at)'),
                                            ('watermark', 'max(b.at)'), ('sample_count', 'count(*)')], implicit=('counter',))
    rows = execute(service, statement, params)
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    lagging = 'snapshots_lagging' if _lagging(coverage, interval, now, SNAPSHOT_LAG_SECONDS) else None
    since = coverage['earliest'] if gap else None
    out = []
    for row in rows:
        state, reason = _finish('measured', None, gap=gap, lagging=lagging, stale=stale)
        out.append(build_row(metric, interval, _dimensions(row, group_by), value=number(row['peak']), unit='count', state=state, known=number(row['sample_count']),
                             watermark=row['watermark'], sample_count=number(row['sample_count']), reason=reason, collecting_since=since,
                             measures={'latest': number(row['latest']), 'latestAt': row['latest_at'], 'snapshots': number(row['sample_count'])}))
    return out


# ---- connection_health (M29) -----------------------------------------------------------------------------------------------
CONNECTION_BASE = ('SELECT h."workspaceId" AS wid, h.provider, h.capability, h.state, h.level, h."refreshedAt" AS at'
                   f' FROM {CONNECTION_VIEW} h WHERE {excluded(H_WORKSPACE)}')
CONNECTION_DIMS = {'provider': 'b.provider', 'capability': 'b.capability', 'state': 'b.state', 'level': 'b.level'}


def connection_health_rows(service, metric, query, interval, stale):
    """Connections x capability by provider, capability, health state and capability level, as of the last hourly refresh.
    Customer workspaces only (internal/test/demo excluded). A snapshot: the interval does not filter it."""
    now = _now(service)
    coverage = _coverage(service, metric['id'], CONNECTION_VIEW, '"refreshedAt"')
    if coverage is None:
        return _unavailable(metric, interval, 'source_not_configured')
    if not coverage['earliest']:
        return _unavailable(metric, interval, 'not_instrumented')
    statement, params, group_by = _compose(metric['id'], query, CONNECTION_BASE, [], CONNECTION_DIMS,
                                           [('value', 'count(*)'), ('workspaces', 'count(DISTINCT b.wid)'), ('watermark', 'max(b.at)'), ('sample_count', 'count(*)')],
                                           time=False)
    rows = execute(service, statement, params)
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    lagging = 'projection_lagging' if (now - parse_stamp(coverage['latest'])).total_seconds() > PROJECTION_LAG_SECONDS else None
    out = []
    for row in rows:
        count = number(row['value']) or 0
        if not count and group_by:
            continue
        state, reason = _finish('measured', None, lagging=lagging, stale=stale)
        out.append(build_row(metric, interval, _dimensions(row, group_by), value=count, unit='count', state=state, known=count,
                             watermark=row['watermark'] or coverage['latest'], sample_count=count, reason=reason, measures={'workspaces': number(row['workspaces']) or 0}))
    return out


# ---- publish_by_provider (M22) ---------------------------------------------------------------------------------------------
PUBLISH_BY_PROVIDER = dict(
    base=('SELECT e."workspaceId" AS wid, e."occurredAt" AS at, split_part(e."eventType",\'.\',2) AS status, lower(coalesce(e."payloadPlatform",\'unknown\')) AS provider'
          f' FROM {EVENTS_VIEW} e WHERE e."eventType" IN {PUBLISH_EVENTS} AND {interval_clause(E_OCCURRED)}'
          f' AND (e."workspaceId" IS NULL OR {excluded(E_WORKSPACE)})'),
    interval_params=1, probe=EVENTS_VIEW, implicit=('provider',),
    value="(count(*) FILTER (WHERE b.status='verified'))::float8/count(*)",
    known="count(*) FILTER (WHERE b.status IN ('verified','failed'))", unknown="count(*) FILTER (WHERE b.status='uncertain')",
    numerator="count(*) FILTER (WHERE b.status='verified')", denominator='count(*)',
    measures={'verified': "count(*) FILTER (WHERE b.status='verified')", 'failed': "count(*) FILTER (WHERE b.status='failed')",
              'uncertain': "count(*) FILTER (WHERE b.status='uncertain')"},
    dims={'provider': 'b.provider'}, unit='ratio', unknown_reason='uncertain_publish_outcomes')


# ---- slo_burn (§7.3 / §13.4) -----------------------------------------------------------------------------------------------
API_BURN = ('SELECT ' + ', '.join(f'coalesce(sum(r."requestCount") FILTER (WHERE r.minute >= %s::timestamptz),0) AS total_{name}, '
                                  f'coalesce(sum(r."requestCount") FILTER (WHERE r.minute >= %s::timestamptz AND r."statusClass"=\'5xx\'),0) AS bad_{name}'
                                  for name, _ in BURN_WINDOWS)
            + f', max(r.minute) AS watermark FROM {REQUEST_VIEW} r WHERE r.minute >= %s::timestamptz AND r.minute < %s::timestamptz'
            + ' AND split_part(r."routePattern", \'/\', 3) NOT IN (\'cron\',\'control\')')
PUBLISH_BURN = ('SELECT ' + ', '.join(f'count(*) FILTER (WHERE e."occurredAt" >= %s::timestamptz) AS total_{name}, '
                                      f'count(*) FILTER (WHERE e."occurredAt" >= %s::timestamptz AND e."eventType"<>\'publish.verified\') AS bad_{name}'
                                      for name, _ in BURN_WINDOWS)
                + f', max(e."occurredAt") AS watermark FROM {EVENTS_VIEW} e WHERE e."eventType" IN {PUBLISH_EVENTS}'
                + ' AND e."occurredAt" >= %s::timestamptz AND e."occurredAt" < %s::timestamptz'
                + f' AND (e."workspaceId" IS NULL OR {excluded(E_WORKSPACE)})')


def _burn_params(anchor):
    starts = {name: stamp(anchor - timedelta(minutes=minutes)) for name, minutes in BURN_WINDOWS}
    params = [value for name, _ in BURN_WINDOWS for value in (starts[name], starts[name])]
    return params + [starts[BURN_WINDOWS[-1][0]], stamp(anchor)]


def _burn_rows(metric, interval, slo, result, windows, stale, lagging=None):
    totals = {name: (number(result.get(f'total_{name}')) or 0, number(result.get(f'bad_{name}')) or 0) for name, _ in BURN_WINDOWS}
    burns = {name: (bad / total) / (1 - SLO_TARGET) if total else None for name, (total, bad) in totals.items()}
    alerting = {pair: all(burns[name] is not None and totals[name][0] >= MIN_BURN_EVENTS and burns[name] > threshold for name in (long, short))
                for pair, (long, short, threshold) in BURN_PAIRS.items()}
    rows = []
    for name, minutes in BURN_WINDOWS:
        if windows is not None and name not in windows:
            continue
        total, bad = totals[name]
        pair = next(key for key, (long, short, _) in BURN_PAIRS.items() if name in (long, short))
        if not total:
            state, reason = 'not_applicable', 'no_events'
        elif total < MIN_BURN_EVENTS:
            state, reason = 'partial', 'low_traffic'
        else:
            state, reason = 'measured', 'proposed_slo_not_approved'
        if lagging and state in ('measured', 'partial'):
            state, reason = 'stale', lagging
        elif stale and state == 'measured':
            state, reason = 'stale', 'source_stale'
        rows.append(build_row(metric, interval, {'slo': slo, 'burn_window': name}, value=None if burns[name] is None else round(burns[name], 4), unit='multiple',
                              state=state, known=total, unknown=0, numerator=bad, denominator=total, watermark=result.get('watermark'), sample_count=total, reason=reason,
                              measures={'bad': bad, 'total': total, 'errorRatio': (bad / total) if total else None, 'windowMinutes': minutes, 'pair': pair,
                                        'threshold': BURN_PAIRS[pair][2], 'alerting': alerting[pair], 'sloTarget': SLO_TARGET, 'errorBudget': round(1 - SLO_TARGET, 6),
                                        'basis': 'proposed_slo', 'sloStatus': 'proposed_not_approved', 'label': SLO_LABEL}))
    return rows


def slo_burn_rows(service, metric, query, interval, stale):
    """Burn rates for API availability (5xx over all API requests, cron and founder Control excluded) and publish success
    (failed + uncertain over all publish outcomes) over trailing 5m/30m/1h/6h windows ending at min(interval end, now)."""
    now = _now(service)
    anchor = min(parse_stamp(interval['end']), now)
    slos, windows = _filter_values(query, 'slo'), _filter_values(query, 'burn_window')
    out = []
    if slos is None or 'api_availability' in slos:
        coverage = _coverage(service, metric['id'], REQUEST_VIEW, 'minute')
        dims = {'slo': 'api_availability'}
        if coverage is None:
            out += _unavailable(metric, interval, 'source_not_configured', dims=dims)
        elif not coverage['earliest']:
            out += _unavailable(metric, interval, 'not_instrumented', dims=dims)
        else:
            rows = execute(service, MetricStatement(metric['id'] + ':api', API_BURN), _burn_params(anchor))
            lagging = 'request_metrics_lagging' if _lagging(coverage, {'end': stamp(anchor)}, now, REQUEST_LAG_SECONDS) else None
            out += (_unavailable(metric, interval, 'source_not_configured', dims=dims) if rows is None
                    else _burn_rows(metric, interval, 'api_availability', rows[0] if rows else {}, windows, stale, lagging))
    if slos is None or 'publish_success' in slos:
        dims = {'slo': 'publish_success'}
        if not live_metrics.probe(service, EVENTS_VIEW):
            out += _unavailable(metric, interval, 'not_instrumented', dims=dims)
        else:
            rows = execute(service, MetricStatement(metric['id'] + ':publish', PUBLISH_BURN), _burn_params(anchor))
            out += _unavailable(metric, interval, 'source_not_configured', dims=dims) if rows is None else _burn_rows(metric, interval, 'publish_success', rows[0] if rows else {}, windows, stale)
    return out


# ---- support_aging (M31, M32) ----------------------------------------------------------------------------------------------
def _age_case(column, now):
    whens = ' '.join(f"WHEN {column} > {now} - interval '{days} days' THEN '{band}'" for band, days in AGE_BANDS)
    return f"CASE {whens} ELSE 'over_30d' END"


SUPPORT_BASE = (f'SELECT q."workspaceId" AS wid, q."requestedAt" AS at, q.kind, {_age_case(Q_REQUESTED, "p.now")} AS age_band,'
                ' extract(epoch FROM (p.now - q."requestedAt")) AS age_seconds'
                f' FROM {REQUESTS_VIEW} q CROSS JOIN (SELECT %s::timestamptz AS now) p'
                f' WHERE q.status=\'requested\' AND q."requestedAt" < p.now AND (q."workspaceId" IS NULL OR {excluded(Q_WORKSPACE)})')


TICKETS = 'not_collected'   # no support-ticket source has been chosen (PRD §10.1a D7)


def _ticket_row(metric, interval, group_by, fixture=False):
    dims = {dim: None for dim in group_by}
    dims['source'] = 'support_tickets'
    row = build_row(metric, interval, dims, value=None, unit='count', state='unavailable', reason=TICKETS, fixture=fixture)
    row['measures'] = {'decision': 'D7'}   # never a zero: the ticket source does not exist yet
    return row


def _support_shape(query):
    """(rows from data requests?, ticket row?, group dims without 'source', whether 'source' is grouped). 'source' is optional:
    grouping or filtering by it adds the support-ticket row (unavailable, not_collected) beside the data-request rows."""
    sources, grouped = _filter_values(query, 'source'), 'source' in query['groupBy']
    requests = sources is None or 'data_requests' in sources
    tickets = (grouped or sources is not None) and (sources is None or 'support_tickets' in sources)
    return requests, tickets, [dim for dim in query['groupBy'] if dim != 'source'], grouped


def support_aging_rows(service, metric, query, interval, stale):
    """Open data requests by age band and kind as of now, with the oldest age as a measure. Every row says the support-ticket
    source is not collected (measures.ticketSource, D7); grouping by 'source' adds that source as its own unavailable row. A
    snapshot: the interval does not filter it."""
    requests, tickets, group_by, grouped = _support_shape(query)
    source = {'source': 'data_requests'} if grouped else {}
    out = []
    if requests:
        statement, params, sql_group = _compose(metric['id'], query, SUPPORT_BASE, [stamp(_now(service))], {'kind': 'b.kind', 'age_band': 'b.age_band'},
                                                [('value', 'count(*)'), ('oldest', 'max(b.age_seconds)'), ('watermark', 'max(b.at)'), ('sample_count', 'count(*)')],
                                                python_dims=('source',), time=False)
        rows = execute(service, statement, params)
        if rows is None:
            out += _unavailable(metric, interval, 'source_not_configured', dims=source)
        else:
            rows = [row for row in rows if number(row['sample_count'])]
            if not rows and not live_metrics.probe(service, REQUESTS_VIEW):
                out += _unavailable(metric, interval, 'not_instrumented', dims=source)
            elif not rows and not sql_group:
                state, reason = _finish('measured', None, stale=stale)
                out.append(build_row(metric, interval, dict(source), value=0, unit='count', state=state, reason=reason, measures={'oldestSeconds': None, 'ticketSource': TICKETS}))
            for row in rows:
                count, oldest = number(row['sample_count']), number(row['oldest'])
                state, reason = _finish('measured', None, stale=stale)
                out.append(build_row(metric, interval, {**_dimensions(row, sql_group), **source}, value=count, unit='count', state=state, known=count,
                                     watermark=row['watermark'], sample_count=count, reason=reason,
                                     measures={'oldestSeconds': None if oldest is None else int(oldest), 'ticketSource': TICKETS}))
    if tickets:
        out.append(_ticket_row(metric, interval, group_by))
    return out


def _band(age_seconds):
    if age_seconds is None:
        return 'over_30d'
    for band, days in AGE_BANDS:
        if age_seconds < days * 86400:
            return band
    return 'over_30d'


def demo_support_aging(metric, data, query, interval, now, stale):
    """Demo parity: the Demo inbox records (open tickets, as data_requests_backlog uses them) aged against the Demo asOf."""
    requests, tickets, group_by, grouped = _support_shape(query)
    source = {'source': 'data_requests'} if grouped else {}
    filters = {item['dimension']: set(item['values']) for item in query['filters'] if item['dimension'] in ('kind', 'age_band')}
    out = []
    if requests:
        groups = defaultdict(list)
        for row in data.get('tickets', []):
            if row.get('status') != 'open':
                continue
            try:
                at = parse_stamp(row.get('at'))
            except (AttributeError, TypeError, ValueError):
                at = None
            age = max(0.0, (now - at).total_seconds()) if at else None
            record = dict(at=at, kind=row.get('kind'), age_band=_band(age), age=age)
            if any(record.get(dim) not in allowed for dim, allowed in filters.items()):
                continue
            groups[tuple(record.get(dim) for dim in group_by)].append(record)
        if len(groups) > MAX_POINTS:
            raise ControlError('BUDGET_EXCEEDED', 400)
        if not groups and not group_by:
            groups[()] = []
        state, reason = ('stale', 'source_stale') if stale else ('measured', None)
        for key in sorted(groups, key=lambda item: [str(value) for value in item]):
            members = groups[key]
            stamps = [member['at'] for member in members if member['at']]
            ages = [member['age'] for member in members if member['age'] is not None]
            out.append(build_row(metric, interval, {**dict(zip(group_by, key)), **source}, value=len(members), unit='count', state=state, known=len(members),
                                 watermark=stamp(max(stamps)) if stamps else None, sample_count=len(members), reason=reason, fixture=True,
                                 measures={'oldestSeconds': int(max(ages)) if ages else None, 'ticketSource': TICKETS}))
    if tickets:
        out.append(_ticket_row(metric, interval, group_by, fixture=True))
    return out


# ---- cron stages -----------------------------------------------------------------------------------------------------------
NOT_INSTALLED = frozenset(('UndefinedTable', 'UndefinedColumn', 'InsufficientPrivilege'))
NOT_INSTALLED_PAUSE = 600
PAUSED, LOGGED = {}, set()
COUNTER_KEY = re.compile(r'^[A-Za-z][A-Za-z0-9_.]{0,59}$')
MAX_COUNTERS = 64
SNAPSHOT_UPSERT = ('INSERT INTO public.pr_operational_snapshots(minute,observed_at,status,notification_delivery,counts) VALUES(to_timestamp(%s),to_timestamp(%s),%s,%s,%s::jsonb) '
                   'ON CONFLICT (minute) DO UPDATE SET observed_at=excluded.observed_at,status=excluded.status,'
                   'notification_delivery=excluded.notification_delivery,counts=excluded.counts,recorded_at=now()')
CAPABILITIES = ('identity', 'publish', 'schedule', 'analytics', 'comments_read', 'reply', 'moderate', 'media_types', 'webhooks')
LEVELS = ('Direct', 'Assisted', 'Bridge', 'Unsupported')
CONNECTION_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,80}$')
HEALTH = {'reauthorization_required': 'blocked', 'scope_missing': 'blocked', 'identity_known': 'blocked', 'client_binding_missing': 'blocked',
          'token_expired': 'expired'}
EXPIRING_SECONDS = 7 * 86400
MAX_CONNECTIONS = 5000
REFRESH_SECONDS = 55 * 60
REFRESH_MINUTES = range(5, 10)       # an empty projection is retried once an hour (a few ticks of grace), not every minute
PURGE_LOCAL_HOUR, PURGE_LOCAL_MINUTES = 3, range(0, 10)
PURGES = (('public.pr_request_metrics', 'minute', RETENTION_DAYS), ('public.pr_operational_snapshots', 'minute', RETENTION_DAYS),
          ('public.pr_connection_health', 'refreshed_at', 7))
CHANNELS_SQL = ("SELECT w.id::text, c->>'id', c->>'platform', c->'configured', c->'revoked', c->'identityVerified', coalesce(c->>'providerAccountId','')<>'', "
                "CASE WHEN jsonb_typeof(c->'expiresAt')='number' THEN (c->>'expiresAt')::double precision END, "
                "CASE WHEN jsonb_typeof(c->'scopes')='array' THEN jsonb_array_length(c->'scopes') ELSE 0 END, c->'capabilityVerified', "
                "CASE WHEN jsonb_typeof(c->'verifiedAt')='number' THEN (c->>'verifiedAt')::double precision END "
                "FROM public.pr_workspaces w CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.state->'phase2'->'channels')='array' "
                "THEN w.state->'phase2'->'channels' ELSE '[]'::jsonb END) AS c "
                "WHERE jsonb_typeof(c)='object' AND c->'configured' IS NOT NULL AND c->'configured' NOT IN ('false'::jsonb,'null'::jsonb) "
                "ORDER BY 1, 2 LIMIT %s")
CONNECTION_UPSERT = ('INSERT INTO public.pr_connection_health(workspace_id,connection_id,capability,provider,level,state,connection_state,expires_at,last_sync_at,refreshed_at) '
                     'SELECT u.w::uuid,u.c,u.cap,u.p,u.l,u.s,u.cs,to_timestamp(u.e),to_timestamp(u.v),to_timestamp(%s) '
                     'FROM unnest(%s::text[],%s::text[],%s::text[],%s::text[],%s::text[],%s::text[],%s::text[],%s::float8[],%s::float8[]) AS u(w,c,cap,p,l,s,cs,e,v) '
                     'ON CONFLICT (workspace_id,connection_id,capability) DO UPDATE SET provider=excluded.provider,level=excluded.level,state=excluded.state,'
                     'connection_state=excluded.connection_state,expires_at=excluded.expires_at,last_sync_at=excluded.last_sync_at,refreshed_at=excluded.refreshed_at')


def _factory(service):
    factory = getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)
    return factory if callable(factory) else None


def _paused(stage, now):
    return PAUSED.get(stage, 0) > now


def _not_installed(stage, now, cause):
    """A table or privilege that 060 has not provided yet: pause the stage for ten minutes; log once per process, class only."""
    PAUSED[stage] = now + NOT_INSTALLED_PAUSE
    if stage not in LOGGED:
        LOGGED.add(stage)
        LOGGER.warning(json.dumps({'event': 'founder_ops.not_installed', 'stage': stage, 'cause': cause, 'pauseSeconds': NOT_INSTALLED_PAUSE}, sort_keys=True))
    return {'status': 'unavailable', 'reason': 'not_installed', 'cause': cause}


def _failure(stage, now, error):
    if any(cls.__name__ in NOT_INSTALLED for cls in type(error).__mro__):
        return _not_installed(stage, now, type(error).__name__)
    return {'status': 'unavailable', 'error': type(error).__name__}


def _table_exists(cur, name):
    cur.execute('SELECT to_regclass(%s)', (name,))
    row = cur.fetchone()
    return bool(row and row[0])


def _provided_snapshot(service, now):
    """The snapshot the consumer cron computed this minute, when the worker hands it over (service.last_operational_snapshot)."""
    snapshot = getattr(service, 'last_operational_snapshot', None)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('counts'), dict):
        return None
    try:
        return snapshot if abs(float(now) - float(snapshot.get('observedAt'))) <= 120 else None
    except (TypeError, ValueError):
        return None


def snapshot_counts(snapshot):
    """Integer counters only (operational_signals counts plus 'sms.*' signals), bounded; anything else is dropped."""
    out = {}
    for prefix, values in (('', snapshot.get('counts')), ('sms.', snapshot.get('sms'))):
        for key, value in (values or {}).items() if isinstance(values, dict) else ():
            name = prefix + str(key)
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not COUNTER_KEY.fullmatch(name):
                continue
            if value < 0 or int(value) != value or len(out) >= MAX_COUNTERS:
                continue
            out[name] = int(value)
    return out


def operational_snapshot_stage(fstore, service, values, now):
    """Each tick: persist the minute's operational_signals.snapshot counts into public.pr_operational_snapshots."""
    if _paused('operational_snapshot', now):
        return {'status': 'skipped', 'reason': 'not_installed'}
    factory = _factory(service)
    if factory is None:
        return {'status': 'unavailable', 'reason': 'consumer_database_not_configured'}
    try:
        with factory() as db:
            with db.cursor() as cur:
                if not _table_exists(cur, 'public.pr_operational_snapshots'):
                    return _not_installed('operational_snapshot', now, 'table_missing')
        snapshot, source = _provided_snapshot(service, now), 'cron_result'
        if snapshot is None:
            from postriff_phase2.operational_signals import snapshot as compute
            snapshot, source = compute(factory, now), 'computed'
        observed = float(snapshot.get('observedAt') or now)
        minute = int(observed // 60) * 60
        counts = snapshot_counts(snapshot)
        status = snapshot.get('status') if snapshot.get('status') in ('ok', 'attention') else 'attention'
        delivery = snapshot.get('notificationDelivery') if snapshot.get('notificationDelivery') in ('rafii_v2', 'not_configured') else 'not_configured'
        with factory() as db:
            with db.cursor() as cur:
                cur.execute(SNAPSHOT_UPSERT, (minute, observed, status, delivery, json.dumps(counts, sort_keys=True)))
            db.commit()
        return {'status': 'ok', 'minute': minute, 'counters': len(counts), 'source': source}
    except Exception as error:
        return _failure('operational_snapshot', now, error)


def provider_key(platform):
    return re.sub(r'[^a-z0-9]+', '_', str(platform or '').lower()).strip('_')[:40] or 'unknown'


def project_connections(channels, levels, now, connection_state, youtube_status=None):
    """Projection rows {(workspace, connection, capability): row} from the channel fields CHANNELS_SQL reads, classified by the
    customer Channels card's own connection_state. Disconnected channels are not connections and are skipped.
    `youtube_status` ({(workspace, connection): vault facts} from channels.youtube_credential_status) overlays the same
    secret-free vault facts the Channels card uses, so an expired access token with a working refresh grant is not reported
    as an expired connection, and a retained but disabled refresh grant is client_binding_missing."""
    from postriff_phase2.channels import with_youtube_credential_status
    rows = {}
    for workspace_id, connection_id, platform, configured, revoked, identity, has_account, expires, scopes, capability_verified, verified_at in channels:
        if not connection_id or not CONNECTION_ID.fullmatch(str(connection_id)):
            continue
        expires_at = float(expires) if expires is not None else None
        channel = {'platform': platform, 'configured': configured, 'revoked': revoked, 'identityVerified': identity, 'providerAccountId': 'present' if has_account else None,
                   'expiresAt': expires_at if expires_at is not None else 0, 'scopes': bool(scopes), 'capabilityVerified': capability_verified}
        if youtube_status is not None:
            channel = with_youtube_credential_status(channel, youtube_status.get((workspace_id, connection_id)))
        raw = connection_state(channel, now)
        if raw == 'disconnected':
            continue
        # A refreshable grant's access-token deadline is not a grant deadline: never 'expiring' for it.
        refreshable = channel.get('refreshSupported') is True
        state = HEALTH.get(raw) or ('expiring' if expires_at is not None and not refreshable and expires_at - now < EXPIRING_SECONDS else 'ok')
        for capability, level in sorted((levels.get((workspace_id, connection_id)) or {'identity': 'unknown'}).items()):
            if capability in CAPABILITIES:
                rows[(workspace_id, connection_id, capability)] = (workspace_id, connection_id, capability, provider_key(platform), level if level in LEVELS else 'unknown',
                                                                    state, raw, expires_at, None if verified_at is None else float(verified_at))
    return rows


def _refresh_due(latest, now):
    if latest is not None:
        return now - float(latest) >= REFRESH_SECONDS
    return int(now // 60) % 60 in REFRESH_MINUTES


def connection_health_stage(fstore, service, values, now):
    """Hourly: recompute public.pr_connection_health from workspace channel state and capability levels in one transaction
    (advisory-locked, bounded to MAX_CONNECTIONS), then drop rows of connections that disappeared."""
    if _paused('connection_health', now):
        return {'status': 'skipped', 'reason': 'not_installed'}
    factory = _factory(service)
    if factory is None:
        return {'status': 'unavailable', 'reason': 'consumer_database_not_configured'}
    try:
        from postriff_phase2.channels import connection_state
    except Exception as error:
        return {'status': 'unavailable', 'error': type(error).__name__}
    try:
        with factory() as db:
            with db.cursor() as cur:
                if not _table_exists(cur, 'public.pr_connection_health'):
                    return _not_installed('connection_health', now, 'table_missing')
                cur.execute('SELECT extract(epoch FROM max(refreshed_at)) FROM public.pr_connection_health')
                latest = (cur.fetchone() or (None,))[0]
                if not _refresh_due(latest, now):
                    return {'status': 'skipped', 'reason': 'not_due'}
                cur.execute("SELECT pg_try_advisory_xact_lock(hashtext('rafii.founder.connection_health'))")
                if not (cur.fetchone() or (False,))[0]:
                    return {'status': 'skipped', 'reason': 'refresh_in_progress'}
                cur.execute('SET LOCAL statement_timeout = 20000')
                cur.execute(CHANNELS_SQL, (MAX_CONNECTIONS + 1,))
                channels = cur.fetchall()
                truncated = len(channels) > MAX_CONNECTIONS
                channels = channels[:MAX_CONNECTIONS]
                levels = {}
                if channels and _table_exists(cur, 'public.pr_channel_capabilities'):
                    cur.execute('SELECT workspace_id::text,connection_id,capability,level FROM public.pr_channel_capabilities WHERE workspace_id=ANY(%s::uuid[]) LIMIT %s',
                                (sorted({row[0] for row in channels}), MAX_CONNECTIONS * len(CAPABILITIES) + 1))
                    for workspace_id, connection_id, capability, level in cur.fetchall():
                        levels.setdefault((workspace_id, connection_id), {})[capability] = level
                youtube = None
                youtube_workspaces = sorted({row[0] for row in channels if row[2] == 'YouTube'})
                if youtube_workspaces and _table_exists(cur, 'public.pr_encrypted_credentials'):
                    # Booleans, an expiry and the revoked flag reach Python; ciphertext presence is tested in SQL only. A savepoint keeps
                    # this optional overlay from ever aborting the refresh: on any error the projection falls back to channel state.
                    from postriff_phase2.channels import youtube_credential_status
                    cur.execute('SAVEPOINT youtube_overlay')
                    try:
                        youtube = youtube_credential_status(cur, youtube_workspaces)
                        cur.execute('RELEASE SAVEPOINT youtube_overlay')
                    except Exception:   # noqa: BLE001
                        cur.execute('ROLLBACK TO SAVEPOINT youtube_overlay')
                        youtube = None
                rows = list(project_connections(channels, levels, now, connection_state, youtube).values())
                if rows:
                    columns = list(zip(*rows))
                    cur.execute(CONNECTION_UPSERT, (now, *[list(column) for column in columns]))
                cur.execute('DELETE FROM public.pr_connection_health WHERE refreshed_at < to_timestamp(%s)', (now,))
                removed = max(0, cur.rowcount or 0)
            db.commit()
        return {'status': 'ok', 'connections': len(channels), 'rows': len(rows), 'removed': removed, 'truncated': truncated}
    except Exception as error:
        return _failure('connection_health', now, error)


def _purge_due(now):
    local = datetime.fromtimestamp(float(now), ZoneInfo(TIME_ZONE))
    return local.hour == PURGE_LOCAL_HOUR and local.minute in PURGE_LOCAL_MINUTES


def reliability_purge_stage(fstore, service, values, now):
    """Daily (03:00-03:09 report time zone, idempotent): request metrics and operational snapshots older than 30 days, connection
    health rows not refreshed for 7 days."""
    if not _purge_due(now):
        return {'status': 'skipped', 'reason': 'not_due'}
    if _paused('reliability_purge', now):
        return {'status': 'skipped', 'reason': 'not_installed'}
    factory = _factory(service)
    if factory is None:
        return {'status': 'unavailable', 'reason': 'consumer_database_not_configured'}
    deleted = {}
    try:
        with factory() as db:
            with db.cursor() as cur:
                cur.execute('SET LOCAL statement_timeout = 30000')
                for table, column, days in PURGES:
                    if not _table_exists(cur, table):
                        deleted[table.split('.', 1)[1]] = 'table_missing'
                        continue
                    cur.execute(f'DELETE FROM {table} WHERE {column} < to_timestamp(%s)', (float(now) - days * 86400,))
                    deleted[table.split('.', 1)[1]] = max(0, cur.rowcount or 0)
            db.commit()
    except Exception as error:
        return _failure('reliability_purge', now, error)
    if all(value == 'table_missing' for value in deleted.values()):
        return _not_installed('reliability_purge', now, 'table_missing')
    return {'status': 'ok', 'deleted': deleted}


# ---- incident detail (Operations timeline) ---------------------------------------------------------------------------------
INCIDENT_ROUTE = r'/incidents/([A-Za-z0-9_-]{1,80})'


def incident_detail(app, principal, request):
    """GET /incidents/{id}?mode= (control.read): one incident with its event timeline for the Operations swimlane. Live reads
    founder_incidents through the restricted session store; Demo reads the founder's own Demo dataset, never Live. Read-only."""
    incident_id = request['match'][0]
    if request['mode'] == 'demo':
        data = app.queries.demo_data(principal)
        incident = next((row for row in data.get('incidents', []) if row.get('id') == incident_id), None)
        if incident is None:
            raise ControlError('VALIDATION_FAILED', 404)
        return dict(mode='demo', incident=incident, _dataState='synthetic', _receiptIds=[data['receipt']['id']] if data.get('receipt') else [])
    from . import founder_incidents
    return founder_incidents.read_incident(app.founder_store(), principal, incident_id)


# ---- registration ----------------------------------------------------------------------------------------------------------
LIVE_IDS = ('api_error_rate', 'api_latency', 'queue_health', 'connection_health', 'publish_by_provider', 'slo_burn', 'support_aging')
live_metrics.register(
    specs={'publish_by_provider': PUBLISH_BY_PROVIDER},
    custom={'api_error_rate': {'rows': api_error_rate_rows}, 'api_latency': {'rows': api_latency_rows}, 'queue_health': {'rows': queue_health_rows},
            'connection_health': {'rows': connection_health_rows, 'previous': None}, 'slo_burn': {'rows': slo_burn_rows, 'previous': None},
            'support_aging': {'rows': support_aging_rows, 'previous': None}},
    sources={'api_error_rate': 'database', 'api_latency': 'database', 'slo_burn': 'database', 'publish_by_provider': 'database',
             'support_aging': 'database', 'queue_health': 'cron', 'connection_health': 'cron'})
demo_metrics.register({'api_error_rate': demo_metrics.not_simulated, 'api_latency': demo_metrics.not_simulated, 'queue_health': demo_metrics.not_simulated,
                       'connection_health': demo_metrics.not_simulated, 'publish_by_provider': demo_metrics.not_simulated, 'slo_burn': demo_metrics.not_simulated,
                       'support_aging': demo_support_aging})
founder_cron.register_stage('operational_snapshot', operational_snapshot_stage)
founder_cron.register_stage('connection_health', connection_health_stage)
founder_cron.register_stage('reliability_purge', reliability_purge_stage)
http.register_route('GET', INCIDENT_ROUTE, 'control.read', 'founder_metrics_ops', 'incident_detail')
