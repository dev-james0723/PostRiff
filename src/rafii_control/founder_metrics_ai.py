"""Founder AI & API cost metrics (CONTRACTS §8.B; PRD §7.1 M13–M17, §7.2, §8.0–§8.3, §8.8, §10.2, §10.3).

Activated metrics (catalog rows in pack/catalogs/metrics.d/ai.json), all over the 064 reader projections:
  ai_calls                provider attempts (≠ user actions), with ok/failed/rate-limited/timeout/cancelled/unknown counts.
  ai_tokens               tokens by token_type: input (not served from cache; all input when cached tokens were not
                          reported), cached, output (visible, excluding reasoning) and reasoning — the four partition an
                          attempt's tokens (OpenAI semantics, PRD §8.0). Text attempts only; an unreported count is coverage
                          unknown, never zero.
  ai_latency              p95 latency (value) with p50 and p95 in measures, per group; percentiles are computed in SQL per
                          group and never averaged; groups with fewer than 30 attempts say `small_sample` (n is sampleCount).
                          Voice sessions (audio) are not latency samples.
  ai_fallback_retry_rate  share of attempts that were a fallback route or a retry (attempt_no > 1), each also in measures.
  ai_cost_per_call        mean recorded cost of attempts whose cost is known; attempts with unknown cost are coverage unknown.
  cost_per_useful_outcome P2: canonical AI cost of the population (pr_usage_ledger, failed and cancelled work included) ÷
                          useful outcomes from the outcome proxy named in measures.basis: Time Back accepted outcomes
                          (default) or learning-event approvals/publishes (`outcome_proxy`). A zero denominator is
                          not_applicable.
  ai_cost_forecast        P2 scenario: month-end AI cost (ledger actuals) = month-to-date actuals + an ordinary least-squares
                          line over the 56 complete local days before as-of, extrapolated over the rest of the month, beside
                          the global monthly budget; measures.basis='scenario'. insufficient_history before 56 days.

New instrumentation is honest about its age: until pr_ai_call_events has a row these say not_instrumented; afterwards
rows carry collectingSince (the earliest attempt) and an interval that starts before it is partial. Every customer
metric excludes aiUsageExempt attempts and workspaces classified internal/test/demo (recorded by the writers, excluded here).

Cron stages: usage_rollups (hourly, idempotent recompute of the last 3 report-time-zone days of public.pr_usage_rollups under an
advisory lock) and ai_usage_purge (400-day retention, bounded batches). Both use the consumer connection, are bounded and never
raise into the tick.

Boundaries. Reader role, read-only transactions over fixed statements; browser input reaches SQL only as bound parameters.
Demo parity: the Demo dataset simulates no provider attempts and no outcomes (those metrics say demo_not_simulated); the
forecast runs the same definition over the Demo usage rows.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import demo_metrics, founder_cron, live_metrics
from .auth import ControlError
from .live_metrics import MAX_POINTS, TIME_ZONE, WINDOW, build_row, excluded, execute, interval_clause, number, parse_stamp, stamp
from .store import MetricStatement

CALLS_VIEW = 'rafii_control.business_ai_calls'
USAGE_VIEW = 'rafii_control.business_usage_v2'
TIME_SAVINGS_VIEW = 'rafii_control.business_time_savings'
LEARNING_VIEW = 'rafii_control.business_learning_events'     # slice 8.C (065); absent → that proxy is source_not_configured
SUBSCRIPTIONS_VIEW = 'rafii_control.business_subscriptions_v2'
BUDGETS_VIEW = 'rafii_control.business_budgets'
SMALL_SAMPLE = 30
FORECAST_DAYS = 56
FORECAST_METHOD = 'ols_trailing_56d_daily_actuals_v1'
ROLLUP_VERSION = 'rollup-v1'
ROLLUP_DAYS = 3
ROLLUP_REFRESH_SECONDS = 3300           # hourly: a recompute younger than this is fresh
ROLLUP_LOCK = 5808064                   # pg advisory lock key for the rollup recompute
RETENTION_DAYS = 400
PURGE_BATCH = 5000
ZERO_UUID = '00000000-0000-0000-0000-000000000000'
# idempotency_key prefix → feature, exactly as 054's business_usage_v2 derives it (tests keep the two equal).
LEDGER_FEATURES = (('run', 'writer'), ('image', 'image'), ('agent-image', 'image'), ('understanding', 'understanding'), ('learning', 'learning'),
                   ('voice', 'voice'), ('reply', 'reply'), ('notes', 'notes'), ('media', 'notes'), ('research', 'research'), ('agent', 'agent'),
                   ('agent-follow-ups', 'agent'), ('agent-resume', 'agent'), ('founder', 'agent'), ('site-agent', 'site_agent'),
                   ('phone-live', 'phone'), ('phone-tel', 'phone'), ('radar', 'radar'))
OUTCOME_PROXIES = ('time_back', 'learning_events')
BASIS = {'time_back': 'time_back_accepted_outcomes', 'learning_events': 'learning_approvals_publishes'}

_AC = excluded('ac."workspaceId"')


# ---- statements -----------------------------------------------------------------------------------------------------------
def _calls(columns='', where=''):
    """Customer provider attempts in [start, end): aiUsageExempt users and internal/test/demo workspaces are excluded."""
    return ('SELECT ac."workspaceId" AS wid, ac.at, ac.feature, coalesce(ac.workload,\'none\') AS workload, ac.model, ac.provider, ac.route, ac.status,'
            f' ac."attemptNo" AS attempt_no, {COST_BASIS} AS cost_basis{columns} FROM {CALLS_VIEW} ac WHERE NOT ac."aiUsageExempt"{where} AND {interval_clause("ac.at")} AND {_AC}')


# How an attempt's cost is known (PRD §7.2 coverage: known / estimated / unknown): reported by the provider or gateway,
# computed from a versioned price table at write time, or not known.
COST_BASIS = ("CASE WHEN ac.\"costSource\" IN ('gateway','provider') THEN 'reported' WHEN left(ac.\"costSource\",6)='table:' THEN 'price_table'"
              " ELSE 'unknown' END")


TOKENS_BASE = ('SELECT ac."workspaceId" AS wid, ac.at, ac.feature, ac.model, ac.provider, t.token_type, t.tokens FROM ' + CALLS_VIEW + ' ac CROSS JOIN LATERAL (VALUES'
               ' (\'input\', CASE WHEN ac."inputTokens" IS NULL THEN NULL ELSE greatest(ac."inputTokens"-coalesce(ac."cachedInputTokens",0),0) END),'
               ' (\'cached\', ac."cachedInputTokens"),'
               ' (\'output\', CASE WHEN ac."outputTokens" IS NULL THEN NULL ELSE greatest(ac."outputTokens"-coalesce(ac."reasoningTokens",0),0) END),'
               ' (\'reasoning\', ac."reasoningTokens")) AS t(token_type, tokens)'
               f' WHERE NOT ac."aiUsageExempt" AND ac.images IS NULL AND ac."audioSeconds" IS NULL AND {interval_clause("ac.at")} AND {_AC}')
CALL_DIMS = {'feature': 'b.feature', 'model': 'b.model', 'provider': 'b.provider', 'route': 'b.route', 'status': 'b.status', 'workload': 'b.workload',
             'cost_basis': 'b.cost_basis'}
STATUS_COUNTS = {'ok': "count(*) FILTER (WHERE b.status='ok')", 'failed': "count(*) FILTER (WHERE b.status='failed')",
                 'rateLimited': "count(*) FILTER (WHERE b.status='rate_limited')", 'timeout': "count(*) FILTER (WHERE b.status='timeout')",
                 'cancelled': "count(*) FILTER (WHERE b.status='cancelled')", 'unknownOutcome': "count(*) FILTER (WHERE b.status='unknown')"}
RETRIED = "(b.route='fallback' OR b.attempt_no>1)"
SPECS = {
    'ai_calls': dict(base=_calls(), dims=CALL_DIMS, value='count(*)', unit='count', measures=STATUS_COUNTS),
    'ai_tokens': dict(base=TOKENS_BASE, dims={'token_type': 'b.token_type', 'feature': 'b.feature', 'model': 'b.model', 'provider': 'b.provider'},
                      value='coalesce(sum(b.tokens),0)', known='count(b.tokens)', unknown='count(*)-count(b.tokens)', unit='tokens', unknown_reason='tokens_not_reported'),
    'ai_latency': dict(base=_calls(', ac."latencyMs" AS latency', ' AND ac."latencyMs" IS NOT NULL AND ac."audioSeconds" IS NULL'), dims=CALL_DIMS,
                       value='percentile_cont(0.95) WITHIN GROUP (ORDER BY b.latency)', unit='milliseconds', percentile=True,
                       measures={'p50Ms': 'percentile_cont(0.5) WITHIN GROUP (ORDER BY b.latency)', 'p95Ms': 'percentile_cont(0.95) WITHIN GROUP (ORDER BY b.latency)'}),
    'ai_fallback_retry_rate': dict(base=_calls(), dims={key: CALL_DIMS[key] for key in ('feature', 'model', 'provider', 'workload')},
                                   value=f'(count(*) FILTER (WHERE {RETRIED}))::float8/nullif(count(*),0)', numerator=f'count(*) FILTER (WHERE {RETRIED})',
                                   denominator='count(*)', unit='ratio', ratio=True,
                                   measures={'fallbackAttempts': "count(*) FILTER (WHERE b.route='fallback')", 'retryAttempts': 'count(*) FILTER (WHERE b.attempt_no>1)',
                                             'fallbackRate': "(count(*) FILTER (WHERE b.route='fallback'))::float8/nullif(count(*),0)",
                                             'retryRate': '(count(*) FILTER (WHERE b.attempt_no>1))::float8/nullif(count(*),0)'}),
    'ai_cost_per_call': dict(base=_calls(', ac."costUsdMicro" AS cost'), dims={key: CALL_DIMS[key] for key in ('feature', 'model', 'provider', 'route', 'workload')},
                             value='sum(b.cost)::float8/nullif(count(b.cost),0)', numerator='coalesce(sum(b.cost),0)', denominator='count(b.cost)',
                             known='count(b.cost)', unknown='count(*)-count(b.cost)', unit='usd_micro', currency='USD', ratio=True, unknown_reason='cost_unknown_attempts',
                             measures={'costUsdMicro': 'coalesce(sum(b.cost),0)', 'attempts': 'count(*)'}),
}
# Canonical ledger cost (the ai_cost_actual base) and the two outcome proxies, for cost_per_useful_outcome and the forecast.
COST = dict(base=live_metrics._usage("('actual','estimated_unknown')"), dims={'plan': 'b.plan'}, value="coalesce(sum(b.actual) FILTER (WHERE b.cost_state='actual'),0)",
            known="count(*) FILTER (WHERE b.cost_state='actual')", unknown="count(*) FILTER (WHERE b.cost_state='estimated_unknown')")
_TS, _TS_AT = excluded('t."workspaceId"'), interval_clause('t."occurredAt"')
_LE, _LE_AT = excluded('l."workspaceId"'), interval_clause('l.at')
OUTCOMES = {
    'time_back': dict(base=(f'SELECT t."workspaceId" AS wid, t."occurredAt" AS at, s.plan FROM {TIME_SAVINGS_VIEW} t LEFT JOIN {SUBSCRIPTIONS_VIEW} s ON s."workspaceId"=t."workspaceId"'
                            f' WHERE {_TS_AT} AND {_TS}'), dims={'plan': 'b.plan'}, value='count(*)'),
    'learning_events': dict(base=(f'SELECT l."workspaceId" AS wid, l.at, s.plan FROM {LEARNING_VIEW} l LEFT JOIN {SUBSCRIPTIONS_VIEW} s ON s."workspaceId"=l."workspaceId"'
                                  f" WHERE l.kind IN ('draft.approved','post.published') AND {_LE_AT} AND {_LE}"), dims={'plan': 'b.plan'}, value='count(*)'),
}


def compose(metric_id, spec, query, interval):
    """One fixed statement: the spec's base over one half-open interval, registry dimensions and filters as bound parameters."""
    group_by = list(query['groupBy'])
    expressions = {**spec['dims'], 'window': WINDOW}
    params = [interval['start'], interval['end']]
    selected = []
    for dim in group_by:
        if dim not in expressions:
            raise ControlError('VALIDATION_FAILED', 400)
        selected.append(f'{expressions[dim]} AS "d_{dim}"')
        if dim == 'window':
            params.append(interval['timeZone'])
    aggregates = [f"{spec['value']} AS value", f"{spec.get('known', 'count(*)')} AS known", f"{spec.get('unknown', '0')} AS unknown",
                  f"{spec.get('numerator', 'NULL')} AS numerator", f"{spec.get('denominator', 'NULL')} AS denominator", 'max(b.at) AS watermark', 'count(*) AS sample_count']
    aggregates += [f'{expression} AS "m_{name}"' for name, expression in spec.get('measures', {}).items()]
    filters = ''
    for item in query['filters']:
        if item['dimension'] not in expressions:
            raise ControlError('VALIDATION_FAILED', 400)
        filters += f" AND {expressions[item['dimension']]} = ANY(%s)"
        if item['dimension'] == 'window':
            params.append(interval['timeZone'])
        params.append(list(item['values']))
    grouping = ', '.join(f'"d_{dim}"' for dim in group_by)
    tail = f' GROUP BY {grouping} ORDER BY {grouping}' if group_by else ''
    params.append(MAX_POINTS + 1)
    sql = f"WITH base AS ({spec['base']}) SELECT {', '.join(selected + aggregates)} FROM base b WHERE TRUE{filters}{tail} LIMIT %s"
    return MetricStatement(metric_id, sql), params, group_by


def _unavailable(metric, interval, unit, reason, dimensions=None, **extra):
    return [build_row(metric, interval, dimensions or {}, value=None, unit=unit, state='unavailable', reason=reason, **extra)]


def collecting_since(service):
    """(configured, earliest attempt ISO or None): when pr_ai_call_events started recording."""
    rows = execute(service, MetricStatement('probe', f'SELECT min(ac.at) AS first FROM {CALLS_VIEW} ac'), ())
    if rows is None:
        return False, None
    first = rows[0].get('first') if rows else None
    return True, (stamp(parse_stamp(first)) if isinstance(first, str) else stamp(first) if isinstance(first, datetime) else None)


def _starts_before(since, interval, window):
    """Whether the row's period starts before instrumentation began: its local day for a window row, else the interval."""
    if window:
        zone = ZoneInfo(interval['timeZone'])
        start = datetime.strptime(window, '%Y-%m-%d').replace(tzinfo=zone)
    else:
        start = parse_stamp(interval['start'])
    return start < parse_stamp(since)


# ---- attempt metrics ------------------------------------------------------------------------------------------------------
def _call_rows(service, metric, query, interval, stale):
    spec = SPECS[metric['id']]
    configured, since = collecting_since(service)
    if not configured:
        return _unavailable(metric, interval, spec['unit'], 'source_not_configured')
    if since is None:
        return _unavailable(metric, interval, spec['unit'], 'not_instrumented')
    if parse_stamp(interval['end']) <= parse_stamp(since):
        return _unavailable(metric, interval, spec['unit'], 'not_instrumented', collecting_since=since)
    statement, params, group_by = compose(metric['id'], spec, query, interval)
    rows = execute(service, statement, params)
    if rows is None:
        return _unavailable(metric, interval, spec['unit'], 'source_not_configured')
    result = []
    for row in rows:
        dimensions = {dim: row[f'd_{dim}'] for dim in group_by}
        known, unknown, value, sample = number(row['known']), number(row['unknown']), number(row['value']), number(row['sample_count'])
        state, reason = 'measured', None
        if value is None and spec.get('ratio'):
            state, reason = ('unavailable', spec.get('unknown_reason')) if unknown else ('not_applicable', 'zero_denominator')
        elif value is None and spec.get('percentile'):
            state, reason = 'not_applicable', 'no_attempts'
        elif unknown:
            state, reason = 'partial', spec.get('unknown_reason')
        if state == 'measured' and _starts_before(since, interval, dimensions.get('window')):
            state, reason = 'partial', 'collecting_since'
        if spec.get('percentile') and value is not None and sample < SMALL_SAMPLE and reason is None:
            reason = 'small_sample'
        if stale and state == 'measured':
            state, reason = 'stale', 'source_stale'
        measures = {name: number(row[f'm_{name}']) for name in spec.get('measures', {})} or None
        result.append(build_row(metric, interval, dimensions, value=value, unit=spec['unit'], currency=spec.get('currency'), state=state, known=known, unknown=unknown,
                                numerator=number(row['numerator']), denominator=number(row['denominator']), watermark=row['watermark'], sample_count=sample,
                                reason=reason, measures=measures, collecting_since=since))
    return result


# ---- cost per useful outcome (P2) -------------------------------------------------------------------------------------------
def _grouped(service, metric_id, spec, query, interval):
    """{dimension tuple: row} for one fixed statement, or None when its projection is not configured."""
    statement, params, group_by = compose(metric_id, spec, query, interval)
    rows = execute(service, statement, params)
    if rows is None:
        return None
    return {tuple(row[f'd_{dim}'] for dim in group_by): row for row in rows}


def outcome_rows(metric, interval, group_by, proxies, costs, outcomes, *, stale, fixture=False):
    """Join cost and outcome groups on the SQL dimensions: one row per (group, proxy). Outcomes of 0 → not_applicable."""
    sql_dims = [dim for dim in group_by if dim != 'outcome_proxy']
    result = []
    for proxy in proxies:
        found = outcomes.get(proxy)
        if found is None:
            dimensions = {dim: (proxy if dim == 'outcome_proxy' else None) for dim in group_by}
            result.append(build_row(metric, interval, dimensions, value=None, unit='usd_micro', currency='USD', state='unavailable', reason='source_not_configured',
                                    measures={'basis': BASIS[proxy]}, fixture=fixture))
            continue
        keys = sorted(set(costs) | set(found), key=lambda key: [str(part) for part in key])
        for key in keys:
            cost_row, outcome_row = costs.get(key) or {}, found.get(key) or {}
            cost, known, unknown = number(cost_row.get('value')) or 0, number(cost_row.get('known')) or 0, number(cost_row.get('unknown')) or 0
            count = number(outcome_row.get('value')) or 0
            dimensions = {dim: (proxy if dim == 'outcome_proxy' else key[sql_dims.index(dim)]) for dim in group_by}
            watermark = max(filter(None, (cost_row.get('watermark'), outcome_row.get('watermark'))), default=None)
            measures = {'costUsdMicro': cost, 'outcomes': count, 'basis': BASIS[proxy]}
            if not count:
                result.append(build_row(metric, interval, dimensions, value=None, unit='usd_micro', currency='USD', state='not_applicable', known=known, unknown=unknown,
                                        numerator=cost, denominator=0, watermark=watermark, sample_count=0, reason='zero_denominator', measures=measures, fixture=fixture))
                continue
            state, reason = ('partial', 'unsettled_cost_rows') if unknown else ('stale', 'source_stale') if stale else ('measured', None)
            result.append(build_row(metric, interval, dimensions, value=cost / count, unit='usd_micro', currency='USD', state=state, known=known, unknown=unknown,
                                    numerator=cost, denominator=count, watermark=watermark, sample_count=count, reason=reason, measures=measures, fixture=fixture))
    return result


def _proxies(query):
    wanted = [set(item['values']) for item in query['filters'] if item['dimension'] == 'outcome_proxy']
    proxies = OUTCOME_PROXIES if 'outcome_proxy' in query['groupBy'] else ('time_back',)
    return [proxy for proxy in proxies if all(proxy in values for values in wanted)]


def _cost_per_outcome(service, metric, query, interval, stale):
    sub = {**query, 'groupBy': [dim for dim in query['groupBy'] if dim != 'outcome_proxy'],
           'filters': [item for item in query['filters'] if item['dimension'] != 'outcome_proxy']}
    proxies = _proxies(query)
    costs = _grouped(service, metric['id'], COST, sub, interval)
    if costs is None:
        return _unavailable(metric, interval, 'usd_micro', 'source_not_configured')
    outcomes = {proxy: _grouped(service, metric['id'], OUTCOMES[proxy], sub, interval) for proxy in proxies}
    return outcome_rows(metric, interval, query['groupBy'], proxies, costs, outcomes, stale=stale)


# ---- month-end forecast (P2 scenario) ---------------------------------------------------------------------------------------
def fit_line(values):
    """Ordinary least squares over (0..n-1, values) → (intercept, slope)."""
    n = len(values)
    mean_x, mean_y = (n - 1) / 2, sum(values) / n
    spread = sum((x - mean_x) ** 2 for x in range(n))
    slope = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values)) / spread if spread else 0.0
    return mean_y - slope * mean_x, slope


def month_bounds(as_of_local):
    start = as_of_local.date().replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def forecast(daily, *, first_day, today, month_start, month_end, required=FORECAST_DAYS):
    """The scenario from daily actuals {date: usd_micro}: None plus the history it had when fewer than `required` complete days
    precede `today`; else the month's points [(date, kind, daily, cumulative)], the month-to-date actual and the projection.
    Today counts as a projection (the larger of its actual so far and the line), as do the days after it."""
    available = max(0, (today - first_day).days) if first_day else 0
    if available < required:
        return None, {'availableDays': available, 'requiredDays': required}
    window = [today - timedelta(days=required - offset) for offset in range(required)]
    intercept, slope = fit_line([daily.get(day, 0) for day in window])
    points, total, mtd = [], 0, 0
    day = month_start
    while day < month_end:
        actual = daily.get(day, 0)
        if day < today:
            value, kind = actual, 'actual'
            mtd += actual
        else:
            line = max(0.0, intercept + slope * ((day - window[0]).days))
            if day == today:
                mtd += actual
            value, kind = int(round(max(float(actual), line) if day == today else line)), 'projection'
        total += value
        points.append((day, kind, int(value), int(total)))
        day += timedelta(days=1)
    return {'points': points, 'mtd': int(mtd), 'total': int(total), 'slope': slope, 'intercept': intercept}, {'availableDays': available, 'requiredDays': required}


def forecast_rows(metric, query, interval, scenario, history, budget, *, state, reason, watermark, sample_count, as_of, fixture=False):
    if scenario is None:
        dimensions = {'window': None} if 'window' in query['groupBy'] else {}
        return [build_row(metric, interval, dimensions, value=None, unit='usd_micro', currency='USD', state='unavailable', reason='insufficient_history',
                          history=history, measures={'basis': 'scenario', 'method': FORECAST_METHOD}, fixture=fixture)]
    budget = budget or {}
    common = {'basis': 'scenario', 'method': FORECAST_METHOD, 'budgetStopUsdMicro': budget.get('stop'), 'budgetWarnUsdMicro': budget.get('warn'),
              'budgetStatus': budget.get('status')}
    if 'window' in query['groupBy']:
        wanted = [set(item['values']) for item in query['filters'] if item['dimension'] == 'window']
        return [build_row(metric, interval, {'window': day.isoformat()}, value=cumulative, unit='usd_micro', currency='USD', state=state, reason=reason,
                          known=sample_count, watermark=watermark, sample_count=sample_count, history=history, fixture=fixture,
                          measures={**common, 'kind': kind, 'dailyUsdMicro': daily})
                for day, kind, daily, cumulative in scenario['points'] if all(day.isoformat() in values for values in wanted)]
    points = scenario['points']
    return [build_row(metric, interval, {}, value=scenario['total'], unit='usd_micro', currency='USD', state=state, reason=reason, known=sample_count,
                      watermark=watermark, sample_count=sample_count, history=history, fixture=fixture,
                      measures={**common, 'mtdActualUsdMicro': scenario['mtd'], 'projectedRemainingUsdMicro': scenario['total'] - scenario['mtd'] if points else 0,
                                'slopeUsdMicroPerDay': round(scenario['slope'], 3), 'monthStart': points[0][0].isoformat() if points else None,
                                'monthEnd': (points[-1][0] + timedelta(days=1)).isoformat() if points else None, 'asOf': stamp(as_of)})]


def _forecast_frame(interval, now):
    zone = ZoneInfo(interval['timeZone'])
    as_of = min(parse_stamp(interval['end']), now)
    local = as_of.astimezone(zone)
    month_start, month_end = month_bounds(local)
    today = local.date()
    first = min(month_start, today - timedelta(days=FORECAST_DAYS))
    return zone, as_of, today, month_start, month_end, first


def _forecast_rows(service, metric, query, interval, stale):
    if any(dim != 'window' for dim in query['groupBy']) or any(item['dimension'] != 'window' for item in query['filters']):
        raise ControlError('VALIDATION_FAILED', 400)
    zone, as_of, today, month_start, month_end, first = _forecast_frame(interval, service.clock())
    span = dict(start=stamp(datetime.combine(first, datetime.min.time(), zone)), end=stamp(as_of), timeZone=interval['timeZone'])
    daily_rows = _grouped(service, metric['id'], COST, {'groupBy': ['window'], 'filters': []}, span)
    origin = execute(service, MetricStatement('probe', f"SELECT min(u.at) AS first FROM {USAGE_VIEW} u WHERE u.kind='settle'"), ())
    if daily_rows is None or origin is None:
        return _unavailable(metric, interval, 'usd_micro', 'source_not_configured')
    first_at = origin[0].get('first') if origin else None
    if first_at is None:
        return _unavailable(metric, interval, 'usd_micro', 'not_instrumented')
    first_day = parse_stamp(first_at).astimezone(zone).date()
    daily = {datetime.strptime(key[0], '%Y-%m-%d').date(): number(row['value']) or 0 for key, row in daily_rows.items() if key[0]}
    unknown = sum(number(row['unknown']) or 0 for row in daily_rows.values())
    budget_rows = execute(service, MetricStatement('ai_cost_forecast', f"SELECT b.\"stopUsdMicro\" AS stop, b.\"warnUsdMicro\" AS warn, b.status FROM {BUDGETS_VIEW} b"
                                                                       " WHERE b.scope='global-month' LIMIT %s"), (1,))
    budget = {key: number(value) if key != 'status' else value for key, value in budget_rows[0].items()} if budget_rows else None
    scenario, history = forecast(daily, first_day=first_day, today=today, month_start=month_start, month_end=month_end)
    state, reason = ('partial', 'unsettled_cost_rows') if unknown else ('stale', 'source_stale') if stale else ('measured', None)
    watermark = max((row['watermark'] for row in daily_rows.values() if row.get('watermark')), default=None)
    sample = sum(number(row['sample_count']) or 0 for row in daily_rows.values())
    return forecast_rows(metric, query, interval, scenario, history, budget, state=state, reason=reason, watermark=watermark, sample_count=sample, as_of=as_of)


# ---- Demo parity ------------------------------------------------------------------------------------------------------------
def demo_forecast(metric, data, query, interval, now, stale):
    """The same scenario over the Demo usage rows (settled, actual cost), as of the Demo snapshot."""
    if any(dim != 'window' for dim in query['groupBy']) or any(item['dimension'] != 'window' for item in query['filters']):
        raise ControlError('VALIDATION_FAILED', 400)
    zone, as_of, today, month_start, month_end, _first = _forecast_frame(interval, now)
    daily, first_day, sample, unknown = defaultdict(int), None, 0, 0
    for record in demo_metrics._usage(data):
        at = record.get('at')
        if at is None or at > as_of:
            continue
        day = at.astimezone(zone).date()
        first_day = day if first_day is None or day < first_day else first_day
        daily[day] += record['actual']
        sample += 1
        unknown += record['cost_state'] == 'estimated_unknown'
    if first_day is None:
        return [build_row(metric, interval, {}, value=None, unit='usd_micro', state='unavailable', reason='not_instrumented', fixture=True)]
    scenario, history = forecast(dict(daily), first_day=first_day, today=today, month_start=month_start, month_end=month_end)
    state, reason = ('partial', 'unsettled_cost_rows') if unknown else ('stale', 'source_stale') if stale else ('measured', None)
    return forecast_rows(metric, query, interval, scenario, history, None, state=state, reason=reason, watermark=stamp(as_of), sample_count=sample,
                         as_of=as_of, fixture=True)


# ---- cron stages ------------------------------------------------------------------------------------------------------------
def ledger_feature_sql(alias='u'):
    """054's idempotency-prefix feature derivation (business_usage_v2), over public.pr_usage_ledger directly."""
    cases = ' '.join(f"WHEN '{prefix}' THEN '{feature}'" for prefix, feature in LEDGER_FEATURES)
    return (f"CASE split_part(coalesce((SELECT o.idempotency_key FROM public.pr_usage_ledger o WHERE {alias}.reservation_id IS NOT NULL AND o.workspace_id={alias}.workspace_id"
            f" AND (o.id={alias}.reservation_id OR o.reservation_id={alias}.reservation_id) AND split_part(o.idempotency_key,':',1) NOT IN ('settle','reconcile','release')"
            f" ORDER BY o.at,o.id LIMIT 1), {alias}.idempotency_key),':',1) {cases} ELSE 'other' END")


ROLLUP_SQL = (
    "WITH bounds AS (SELECT (%(first)s::date)::timestamp AT TIME ZONE %(tz)s AS lo, (%(end)s::date)::timestamp AT TIME ZONE %(tz)s AS hi),"
    " calls AS (SELECT (e.started_at AT TIME ZONE %(tz)s)::date AS day, coalesce(e.workspace_id,%(zero)s::uuid) AS wid, coalesce(e.user_id,%(zero)s::uuid) AS uid,"
    " e.feature, e.model, e.provider,"
    " CASE WHEN e.workspace_id IS NULL THEN 'system' WHEN e.ai_usage_exempt THEN 'exempt_developer' ELSE 'customer' END AS actor_class,"
    " count(*) AS calls, count(*) FILTER (WHERE e.status='ok') AS ok, count(*) FILTER (WHERE e.status IN ('failed','rate_limited','timeout')) AS failed,"
    " count(*) FILTER (WHERE e.status='cancelled') AS cancelled, count(*) FILTER (WHERE e.status='unknown') AS unknown,"
    " sum(e.input_tokens) AS input_tokens, sum(e.cached_input_tokens) AS cached_tokens, sum(e.output_tokens) AS output_tokens, sum(e.reasoning_tokens) AS reasoning_tokens,"
    " count(*) FILTER (WHERE e.input_tokens IS NULL OR e.output_tokens IS NULL) AS tokens_unreported,"
    " coalesce(sum(e.images),0) AS images, coalesce(sum(coalesce(e.audio_seconds,s.audio_seconds)),0) AS audio_seconds"
    " FROM public.pr_ai_call_events e CROSS JOIN bounds"
    " LEFT JOIN LATERAL (SELECT x.audio_seconds FROM public.pr_ai_call_settlements x WHERE x.call_event_id=e.id ORDER BY x.at DESC, x.id DESC LIMIT 1) s ON true"
    " WHERE e.started_at >= bounds.lo AND e.started_at < bounds.hi GROUP BY 1,2,3,4,5,6,7),"
    " ledger AS (SELECT (u.at AT TIME ZONE %(tz)s)::date AS day, u.workspace_id AS wid, coalesce(u.member_id,%(zero)s::uuid) AS uid, " + ledger_feature_sql() + " AS feature,"
    " left(coalesce(nullif(u.model,''),'unknown'),160) AS model, left(coalesce(nullif(u.provider,''),'unknown'),60) AS provider,"
    " CASE WHEN jsonb_typeof(u.meta->'aiUsageExempt')='boolean' AND (u.meta->>'aiUsageExempt')::boolean THEN 'exempt_developer' ELSE 'customer' END AS actor_class,"
    " coalesce(sum(u.estimated_usd_micro) FILTER (WHERE u.cost_state IN ('actual','estimated_unknown')),0) AS estimated,"
    " coalesce(sum(u.actual_usd_micro) FILTER (WHERE u.cost_state='actual'),0) AS actual,"
    " coalesce(sum(u.estimated_usd_micro) FILTER (WHERE u.cost_state='estimated_unknown' AND NOT EXISTS (SELECT 1 FROM public.pr_usage_ledger t"
    " WHERE t.workspace_id=u.workspace_id AND t.reservation_id=u.reservation_id AND t.cost_state IN ('actual','released'))),0) AS unknown"
    " FROM public.pr_usage_ledger u CROSS JOIN bounds WHERE u.kind='settle' AND u.at >= bounds.lo AND u.at < bounds.hi GROUP BY 1,2,3,4,5,6,7)"
    " INSERT INTO public.pr_usage_rollups(day,workspace_id,user_id,feature,model,provider,actor_class,calls,ok,failed,cancelled,unknown,input_tokens,cached_tokens,"
    "output_tokens,reasoning_tokens,tokens_unreported,images,audio_seconds,estimated_usd_micro,actual_usd_micro,unknown_usd_micro,rollup_version,computed_at)"
    " SELECT day, nullif(wid,%(zero)s::uuid), nullif(uid,%(zero)s::uuid), feature, model, provider, actor_class, coalesce(c.calls,0), coalesce(c.ok,0), coalesce(c.failed,0),"
    " coalesce(c.cancelled,0), coalesce(c.unknown,0), c.input_tokens, c.cached_tokens, c.output_tokens, c.reasoning_tokens, coalesce(c.tokens_unreported,0),"
    " coalesce(c.images,0), coalesce(c.audio_seconds,0), coalesce(l.estimated,0), coalesce(l.actual,0), coalesce(l.unknown,0), %(version)s, now()"
    " FROM calls c FULL JOIN ledger l USING (day, wid, uid, feature, model, provider, actor_class)")


def _tables_present(cur, *tables):
    cur.execute('SELECT ' + ', '.join('to_regclass(%s) IS NOT NULL' for _ in tables), tuple('public.' + name for name in tables))
    return all(cur.fetchone())


def usage_rollups_stage(fstore, service, values, now):
    """Hourly (a recompute younger than ROLLUP_REFRESH_SECONDS is kept): replace the last ROLLUP_DAYS report-time-zone days of
    public.pr_usage_rollups in one transaction under an advisory lock, so late settlements are absorbed and a concurrent tick
    never doubles a row. Bounded; reports 'unavailable' instead of raising."""
    try:
        today = founder_cron.local_day(now)
        first, end = today - timedelta(days=ROLLUP_DAYS - 1), today + timedelta(days=1)
        with founder_cron._consumer_connection(service)() as db, db.cursor() as cur:
            if not _tables_present(cur, 'pr_usage_rollups', 'pr_ai_call_events', 'pr_ai_call_settlements'):
                return {'status': 'unavailable', 'reason': 'table_missing'}
            cur.execute('SELECT pg_try_advisory_xact_lock(%s)', (ROLLUP_LOCK,))
            if not cur.fetchone()[0]:
                return {'status': 'ok', 'skipped': 'locked'}
            cur.execute('SELECT extract(epoch from max(computed_at)) FROM public.pr_usage_rollups WHERE rollup_version=%s AND day >= %s::date',
                        (ROLLUP_VERSION, first.isoformat()))
            last = cur.fetchone()[0]
            if last is not None and float(now) - float(last) < ROLLUP_REFRESH_SECONDS:
                return {'status': 'ok', 'skipped': 'fresh', 'computedAt': float(last)}
            cur.execute('DELETE FROM public.pr_usage_rollups WHERE day >= %s::date AND day < %s::date', (first.isoformat(), end.isoformat()))
            replaced = max(0, cur.rowcount or 0)
            cur.execute(ROLLUP_SQL, {'first': first.isoformat(), 'end': end.isoformat(), 'tz': TIME_ZONE, 'zero': ZERO_UUID, 'version': ROLLUP_VERSION})
            rows = max(0, cur.rowcount or 0)
            db.commit()
        return {'status': 'ok', 'days': [(first + timedelta(days=offset)).isoformat() for offset in range(ROLLUP_DAYS)], 'rows': rows, 'replaced': replaced,
                'version': ROLLUP_VERSION, 'timeZone': TIME_ZONE}
    except Exception as error:  # noqa: BLE001 - a stage never raises into the tick
        return {'status': 'unavailable', 'error': type(error).__name__}


def purge_stage(fstore, service, values, now):
    """400-day retention: call events (their settlements cascade) in bounded batches, and rollup days past the same horizon."""
    try:
        cutoff = float(now) - RETENTION_DAYS * 86400
        with founder_cron._consumer_connection(service)() as db, db.cursor() as cur:
            if not _tables_present(cur, 'pr_ai_call_events', 'pr_usage_rollups'):
                return {'status': 'unavailable', 'reason': 'table_missing'}
            cur.execute('DELETE FROM public.pr_ai_call_events WHERE id IN (SELECT id FROM public.pr_ai_call_events WHERE started_at < to_timestamp(%s) ORDER BY started_at LIMIT %s)',
                        (cutoff, PURGE_BATCH))
            events = max(0, cur.rowcount or 0)
            cur.execute('DELETE FROM public.pr_usage_rollups WHERE day < (to_timestamp(%s) AT TIME ZONE %s)::date', (cutoff, TIME_ZONE))
            rollups = max(0, cur.rowcount or 0)
            db.commit()
        return {'status': 'ok', 'retentionDays': RETENTION_DAYS, 'deletedCallEvents': events, 'deletedRollupRows': rollups, 'more': events >= PURGE_BATCH}
    except Exception as error:  # noqa: BLE001
        return {'status': 'unavailable', 'error': type(error).__name__}


# ---- registration ---------------------------------------------------------------------------------------------------------
LIVE = {**{metric_id: {'rows': _call_rows} for metric_id in SPECS}, 'cost_per_useful_outcome': {'rows': _cost_per_outcome},
        'ai_cost_forecast': {'rows': _forecast_rows, 'previous': None}}
DEMO = {**{metric_id: demo_metrics.not_simulated for metric_id in SPECS}, 'cost_per_useful_outcome': demo_metrics.not_simulated, 'ai_cost_forecast': demo_forecast}

live_metrics.register(custom=LIVE, sources={metric_id: 'database' for metric_id in LIVE})
demo_metrics.register(DEMO)
founder_cron.register_stage('usage_rollups', usage_rollups_stage)
founder_cron.register_stage('ai_usage_purge', purge_stage)
