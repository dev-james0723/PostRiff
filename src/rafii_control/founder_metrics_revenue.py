"""Founder revenue and billing metrics (CONTRACTS §8.A; PRD §7.1 M04/M05/M09, §7.2, §8.5, §10.2 P1-1, §10.3).

Activated metrics (catalog rows in pack/catalogs/metrics.d/revenue.json):
  mrr, delinquent_mrr   normalized monthly recurring revenue at the interval end (or each local day end with `window`),
                        from the latest billing event per subscription (057 pr_subscription_events via the 063 view):
                        annual/12, quarterly/3, weekly 52/12, daily 365/12; forever and repeating discounts subtracted,
                        one-time discounts and refunds ignored; trials, free and metered prices contribute nothing;
                        active ∪ past_due count (delinquent_mrr is the past_due part). A paid subscription without a priced
                        event is coverage.unknown, never its list price.
  mrr_movements         the MRR bridge over [start, end): per customer (workspace, else subscription) and currency, opening
                        and closing MRR are compared; new / reactivation / expansion / contraction / churn are the signed
                        net changes, plus `opening` and `closing` rows over the same customers, so the rows reconcile
                        exactly. Needs a full month of events and history back to `start` (insufficient_history before).
  logo_churn            opening paying customers whose MRR is zero at the end ÷ opening paying customers.
  credit_grants, credit_consumption, credit_available
                        the credit ledger (pr_usage_ledger meta.credits through business_credit_entries); available credits
                        come from the existing wallet projection (credit_wallet.project_credit_wallet), never re-derived.
                        No credit rows exist while credits are off, so these say not_instrumented.
  mrr_forecast          P2 scenario: an ordinary least-squares line over the most recent ≤90 daily snapshot totals
                        (≥56 required), extrapolated; measures.basis='scenario'.

Boundaries. Reader role, read-only transactions over fixed statements; browser input reaches SQL only as bound
parameters (instants, labels, filter values, limits). Customer metrics exclude provider='fixture' and workspaces
classified internal/test/demo; deleted workspaces stay (their rows lose the workspace id, never the money). Amounts stay
in native minor units per currency and are never summed across currencies. Demo parity computes the same ids from the
founder's Demo dataset (the candidate v2 catalog, labelled as not active); the Demo has no subscription-change history,
so the bridge and logo churn are not simulated there.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import math
import re
from zoneinfo import ZoneInfo

from . import demo_metrics, http, live_metrics
from .auth import ControlError
from .live_metrics import build_row, excluded, execute, interval_clause, number, parse_stamp, stamp
from .store import MetricStatement

EVENTS_VIEW = 'rafii_control.business_subscription_events'
INVOICES_VIEW = 'rafii_control.business_invoices'
SNAPSHOTS_VIEW = 'rafii_control.business_subscription_snapshots_v2'
CREDITS_VIEW = 'rafii_control.business_credit_entries'
SUBSCRIPTIONS_VIEW = 'rafii_control.business_subscriptions_v2'
MRR_STATUSES = ('active', 'past_due')
BRIDGE_REQUIRED_DAYS = 30
FORECAST_REQUIRED_DAYS = 56
FORECAST_FIT_DAYS = 90
MOVEMENTS = ('new', 'expansion', 'reactivation', 'contraction', 'churn')
BRIDGE_ROWS = ('opening',) + MOVEMENTS + ('closing',)
ROUTE_LIMIT = 200
EVENTS_PER_UNIT = 10
CREDIT_ROW_LIMIT = 50_000
MAX_ROWS = live_metrics.MAX_POINTS
DEMO_CATALOG = 'Candidate v2 catalog (not active)'
FORECAST_METHOD = 'ols_daily_snapshot_totals_v1'
# Normalization to one month: (multiplier, divisor) per Stripe interval unit, divided again by interval_count.
FACTORS = {'month': (1, 1), 'year': (1, 12), 'week': (52, 12), 'day': (365, 12)}
DEMO_CYCLES = {'monthly': ('month', 1), 'quarterly': ('month', 3), 'annual': ('year', 1), 'yearly': ('year', 1)}
EXCLUDE_EVENT_WORKSPACE = excluded('e."workspaceId"')
EXCLUDE_CREDIT_WORKSPACE = excluded('k."workspaceId"')   # k, never c: excluded() aliases the classifications as c
EXCLUDE_SUBSCRIPTION_WORKSPACE = excluded('s."workspaceId"')
EXCLUDE_SNAPSHOT_WORKSPACE = excluded('h."workspaceId"')
EXCLUDE_INVOICE_WORKSPACE = excluded('i."workspaceId"')
GRANT_SOURCES = "CASE WHEN k.\"grantSource\"='verified-stripe-invoice' THEN 'subscription' WHEN k.\"grantSource\"='verified-stripe-checkout' THEN 'purchase'" \
                " WHEN k.\"grantSource\"='test' THEN 'test' WHEN k.\"grantSource\" LIKE '%%operator%%' OR k.\"grantSource\" LIKE '%%goodwill%%' THEN 'goodwill' ELSE 'other' END"


# ---- MRR arithmetic: one SQL renderer and its exact Python twin --------------------------------------------------------

def monthly_sql(net, interval, count):
    """Normalized monthly amount in SQL, rounded half away from zero. The numerator is an exact integer product, so every
    terminating quotient (annual/12, quarterly/3, 18/12 = 1.5) rounds exactly as `monthly` does."""
    return (f"round(({net})::numeric * (CASE {interval} WHEN 'week' THEN 52 WHEN 'day' THEN 365 ELSE 1 END)"
            f" / ((CASE {interval} WHEN 'month' THEN 1 ELSE 12 END) * {count}))::bigint")


def net_sql(unit, quantity, discount, discount_end, at):
    """Recurring amount per interval after a forever discount, or a repeating one until it ends."""
    return f"greatest({unit} * coalesce({quantity}, 1) - CASE WHEN {discount_end} IS NULL OR {discount_end} > {at} THEN {discount} ELSE 0 END, 0)"


def monthly(net, interval, count):
    multiplier, divisor = FACTORS[interval]
    return math.floor(Fraction(int(net) * multiplier, divisor * int(count)) + Fraction(1, 2))


def snapshot_insert_sql():
    """founder_cron.subscription_snapshot: today's row per workspace with its MRR from the latest events of the workspace's
    current subscription (consumer connection, public tables). Params: (now epoch, local day). Unknown stays null."""
    match = ('e.workspace_id=s.workspace_id AND e.provider=s.provider AND (s.provider_subscription_id IS NULL OR e.provider_subscription_id=s.provider_subscription_id)'
             ' AND e.event_at < n.at')
    order = 'ORDER BY e.event_at DESC, e.recorded_at DESC, e.id DESC LIMIT 1'
    mrr = monthly_sql(net_sql('p.unit_amount_minor', 'p.quantity', 'p.discount_minor', 'p.discount_end', 'n.at'), 'p."interval"', 'p.interval_count')
    return ('WITH n AS (SELECT to_timestamp(%s) AS at) INSERT INTO public.pr_subscription_snapshots(day,workspace_id,plan_terms_id,status,provider,mrr_minor,currency,"interval",interval_count) '
            'SELECT %s::date,s.workspace_id,s.plan_terms_id,s.status,s.provider,'
            "CASE WHEN l.new_status IS NULL THEN NULL WHEN l.new_status NOT IN ('active','past_due') THEN 0 WHEN p.unit_amount_minor IS NULL THEN NULL"
            " WHEN p.trial_end IS NOT NULL AND p.trial_end > n.at THEN 0 WHEN p.usage_type='metered' THEN 0"
            f' WHEN p."interval" IS NULL OR p.interval_count IS NULL OR p.currency IS NULL OR p.discount_minor IS NULL THEN NULL ELSE {mrr} END,'
            'coalesce(p.currency,l.currency),p."interval",p.interval_count FROM public.pr_subscriptions s CROSS JOIN n'
            f' LEFT JOIN LATERAL (SELECT e.new_status,e.currency FROM public.pr_subscription_events e WHERE {match} {order}) l ON true'
            ' LEFT JOIN LATERAL (SELECT e.unit_amount_minor,e.quantity,e."interval",e.interval_count,e.usage_type,e.currency,e.discount_minor,e.discount_end,e.trial_end'
            f' FROM public.pr_subscription_events e WHERE {match} AND e.unit_amount_minor IS NOT NULL {order}) p ON true'
            ' ON CONFLICT(day,workspace_id) DO NOTHING')


# ---- shared helpers ----------------------------------------------------------------------------------------------------

def _now(service):
    return service.clock()


def _instants(interval, window):
    """[(instant, label)]: the interval end, or each local day's end inside the interval (the day as label)."""
    start, end = parse_stamp(interval['start']), parse_stamp(interval['end'])
    if not window:
        return [(end, '')]   # one unlabeled instant (a text label keeps the bound array typed)
    zone = ZoneInfo(interval['timeZone'])
    day, out = start.astimezone(zone).date(), []
    while True:
        day_start = datetime(day.year, day.month, day.day, tzinfo=zone)
        if day_start >= end: break
        day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone)
        out.append((min(day_end, end), day.isoformat()))
        day += timedelta(days=1)
        if len(out) > 367: raise ControlError('BUDGET_EXCEEDED', 400)
    return out


def _dims(query, expressions, implicit=()):
    group_by = list(implicit) + [dim for dim in query['groupBy'] if dim not in implicit]
    for dim in group_by + [item['dimension'] for item in query['filters']]:
        if dim not in expressions: raise ControlError('VALIDATION_FAILED', 400)
    return group_by


def _filters(query, expressions):
    sql, params = '', []
    for item in query['filters']:
        sql += f" AND {expressions[item['dimension']]} = ANY(%s)"
        params.append(list(item['values']))
    return sql, params


def _first(service, view, column, where='TRUE'):
    """(instrumented?, earliest ISO stamp): None when the projection is missing (source not configured)."""
    rows = execute(service, MetricStatement('probe', f'SELECT min({column}) AS first FROM {view} WHERE {where}'), ())
    if rows is None: return None
    first = rows[0].get('first') if rows else None
    return (first is not None, stamp(parse_stamp(first)) if isinstance(first, str) else None)


def _unavailable(metric, interval, reason, **extra):
    return [build_row(metric, interval, {}, value=None, unit=metric['unit'], state='unavailable', reason=reason, **extra)]


def _state(base_state, base_reason, unknown, stale, unknown_reason):
    if unknown: return 'partial', unknown_reason
    if stale and base_state == 'measured': return 'stale', 'source_stale'
    return base_state, base_reason


def _days(seconds): return int(seconds // 86400)


# ---- subscription state at instants (reader projections) ---------------------------------------------------------------

def _state_ctes():
    """CTEs t (instants), ev (customer billing events), latest/priced (per subscription at each instant), state (kind+mrr).
    Params: (instants timestamptz[], labels text[])."""
    mrr = monthly_sql(net_sql('c.unit_amount', 'c.quantity', 'c.discount', 'c.discount_end', 'c.t'), 'c.ival', 'c.icount')
    return ('t(at, label) AS (SELECT * FROM unnest(%s::timestamptz[], %s::text[])),'
            ' ev AS (SELECT e.id, coalesce(e."providerSubscriptionId", \'workspace:\' || coalesce(e."workspaceId", e.id)) AS sk, e."workspaceId" AS wid, e."eventAt" AS at,'
            ' e."recordedAt" AS rec, e."newStatus" AS status, coalesce(e."newPlan", e."newTermsId") AS plan, e."unitAmountMinor" AS unit_amount, e.quantity,'
            ' e."interval" AS ival, e."intervalCount" AS icount, e."usageType" AS usage_type, e.currency, e."discountMinor" AS discount, e."discountEnd" AS discount_end,'
            f' e."trialEnd" AS trial_end FROM {EVENTS_VIEW} e WHERE e.provider<>\'fixture\' AND (e."workspaceId" IS NULL OR {EXCLUDE_EVENT_WORKSPACE})),'
            ' latest AS (SELECT DISTINCT ON (t.at, ev.sk) t.at AS t, t.label, ev.sk, ev.wid, ev.status, ev.plan, ev.currency, ev.at AS event_at'
            ' FROM t JOIN ev ON ev.at < t.at ORDER BY t.at, ev.sk, ev.at DESC, ev.rec DESC, ev.id DESC),'
            ' priced AS (SELECT DISTINCT ON (t.at, ev.sk) t.at AS t, ev.sk, ev.plan, ev.unit_amount, ev.quantity, ev.ival, ev.icount, ev.usage_type, ev.currency,'
            ' ev.discount, ev.discount_end, ev.trial_end FROM t JOIN ev ON ev.at < t.at AND ev.unit_amount IS NOT NULL'
            ' ORDER BY t.at, ev.sk, ev.at DESC, ev.rec DESC, ev.id DESC),'
            ' classified AS (SELECT l.t, l.label, l.sk, l.wid, coalesce(l.wid, l.sk) AS unit, l.status, coalesce(p.plan, l.plan) AS plan, coalesce(p.currency, l.currency) AS currency,'
            " l.event_at, CASE WHEN l.status IS NULL OR l.status NOT IN ('active','past_due') THEN 'inactive' WHEN p.sk IS NULL THEN 'unknown'"
            " WHEN p.trial_end IS NOT NULL AND p.trial_end > l.t THEN 'trial' WHEN p.usage_type = 'metered' THEN 'metered'"
            " WHEN p.ival IS NULL OR p.icount IS NULL OR p.currency IS NULL OR p.discount IS NULL THEN 'unknown' ELSE 'priced' END AS kind,"
            ' p.unit_amount, p.quantity, p.discount, p.discount_end, p.ival, p.icount FROM latest l LEFT JOIN priced p ON p.t = l.t AND p.sk = l.sk),'
            f" state AS (SELECT c.t, c.label, c.sk, c.wid, c.unit, c.status, c.plan, c.currency, c.event_at, c.kind, CASE WHEN c.kind='priced' THEN {mrr} END AS mrr FROM classified c)")


MRR_DIMS = {'currency': 'b.currency', 'plan': 'b.plan', 'status': 'b.status', 'window': 'b.label'}


def mrr_statement(metric_id, query, instants):
    """mrr / delinquent_mrr: one aggregate per requested group at each instant. Current paid subscriptions with no billing
    event at all are added as unknown (their MRR is not known; the list price is never used). delinquent_mrr keeps every
    group of the MRR population and sums only its past_due part, so "no delinquency" is a measured zero per currency."""
    group_by = _dims(query, MRR_DIMS)
    scope = " AND b.status='past_due'" if metric_id == 'delinquent_mrr' else ''
    filters, filter_params = _filters(query, MRR_DIMS)
    selected = ', '.join(f'{MRR_DIMS[dim]} AS "d_{dim}"' for dim in group_by)
    grouping = ', '.join(f'"d_{dim}"' for dim in group_by)
    sql = (f'WITH {_state_ctes()},'
           " missing AS (SELECT t.at AS t, t.label, NULL::text AS sk, s.\"workspaceId\" AS wid, s.\"workspaceId\" AS unit, s.status, s.plan, upper(s.currency) AS currency,"
           " NULL::timestamptz AS event_at, 'unknown'::text AS kind, NULL::bigint AS mrr"
           f" FROM t CROSS JOIN {SUBSCRIPTIONS_VIEW} s WHERE s.provider<>'fixture' AND s.status IN ('active','past_due') AND {EXCLUDE_SUBSCRIPTION_WORKSPACE}"
           ' AND NOT EXISTS (SELECT 1 FROM ev WHERE ev.wid = s."workspaceId")),'
           " base AS (SELECT * FROM state WHERE kind <> 'inactive' UNION ALL SELECT * FROM missing)"
           f" SELECT {selected + ', ' if selected else ''}coalesce(sum(b.mrr) FILTER (WHERE b.kind='priced'{scope}),0) AS value,"
           f" count(*) FILTER (WHERE b.kind <> 'unknown'{scope}) AS known, count(*) FILTER (WHERE b.kind='unknown'{scope}) AS unknown,"
           f" count(*) FILTER (WHERE b.kind='priced' AND b.mrr > 0{scope}) AS paying, max(b.event_at) AS watermark, count(*) FILTER (WHERE TRUE{scope}) AS sample_count"
           f' FROM base b WHERE TRUE{filters}' + (f' GROUP BY {grouping} ORDER BY {grouping}' if group_by else '') + ' LIMIT %s')
    params = [[at for at, _ in instants], [label for _, label in instants]] + filter_params + [MAX_ROWS + 1]
    return MetricStatement(metric_id, sql), params, group_by


def _mrr_rows(service, metric, query, interval, stale):
    probe = _first(service, EVENTS_VIEW, '"recordedAt"', "provider<>'fixture'")
    if probe is None: return _unavailable(metric, interval, 'source_not_configured')
    instrumented, since = probe
    if not instrumented: return _unavailable(metric, interval, 'not_instrumented')
    statement, params, group_by = mrr_statement(metric['id'], query, _instants(interval, 'window' in query['groupBy']))
    rows = execute(service, statement, params, MAX_ROWS)
    if rows is None: return _unavailable(metric, interval, 'source_not_configured')
    out = []
    for row in rows:
        if not group_by and not number(row['sample_count']): row = {**row, 'value': 0}
        unknown = number(row['unknown']) or 0
        currency = row.get('d_currency')
        state, reason = _state('measured', None, unknown, stale, 'subscriptions_without_priced_event')
        if 'currency' in group_by and not currency and state != 'partial': state, reason = 'partial', 'currency_missing'
        out.append(build_row(metric, interval, {dim: row[f'd_{dim}'] for dim in group_by}, value=number(row['value']), unit='currency_minor', currency=currency,
                             state=state, known=number(row['known']), unknown=unknown, watermark=row.get('watermark'), sample_count=number(row['sample_count']),
                             reason=reason, measures={'payingSubscriptions': number(row['paying'])}, collecting_since=since))
    return out


# ---- bridge (mrr_movements, logo_churn, the movements route) -------------------------------------------------------------

def _bridge_ctes():
    """Per customer unit and currency: opening/closing MRR and the movement. Params after the state CTE params:
    (start, timeZone) for the snapshot pre-check, (start) for the reactivation check."""
    return (f'{_state_ctes()},'
            " per AS (SELECT s.unit, s.currency, s.label, coalesce(sum(s.mrr) FILTER (WHERE s.kind='priced'),0) AS mrr, bool_or(s.kind='unknown') AS unknown,"
            ' max(s.plan) AS plan, max(s.status) AS status, max(s.wid) AS wid, array_agg(DISTINCT s.sk) AS subs FROM state s GROUP BY s.unit, s.currency, s.label),'
            ' pre AS (SELECT h."workspaceId" AS unit FROM rafii_control.business_subscription_snapshots h WHERE h.day = (%s::timestamptz AT TIME ZONE %s)::date'
            " AND h.provider<>'fixture' AND h.status IN ('active','past_due')),"
            ' units AS (SELECT coalesce(o.unit, c.unit) AS unit, coalesce(c.currency, o.currency) AS currency, coalesce(o.mrr,0) AS opening, coalesce(c.mrr,0) AS closing,'
            ' coalesce(o.unknown,false) OR coalesce(c.unknown,false) OR (o.unit IS NULL AND EXISTS (SELECT 1 FROM pre WHERE pre.unit = c.unit)) AS unknown,'
            ' coalesce(o.plan, c.plan) AS opening_plan, coalesce(c.plan, o.plan) AS plan, o.status AS opening_status, c.status AS closing_status,'
            ' coalesce(c.wid, o.wid) AS wid, coalesce(c.subs, o.subs) AS subs'
            " FROM (SELECT * FROM per WHERE label='opening') o FULL JOIN (SELECT * FROM per WHERE label='closing') c ON c.unit = o.unit AND coalesce(c.currency, '') = coalesce(o.currency, '')),"
            " moves AS (SELECT u.*, CASE WHEN u.unknown THEN 'unknown' WHEN u.opening = 0 AND u.closing > 0 THEN CASE WHEN EXISTS (SELECT 1 FROM ev h"
            " WHERE coalesce(h.wid, h.sk) = u.unit AND h.at < %s::timestamptz AND h.status IN ('active','past_due') AND h.unit_amount > 0"
            " AND (h.trial_end IS NULL OR h.trial_end <= h.at)) THEN 'reactivation' ELSE 'new' END"
            " WHEN u.opening > 0 AND u.closing = 0 THEN 'churn' WHEN u.closing > u.opening THEN 'expansion' WHEN u.closing < u.opening THEN 'contraction'"
            " ELSE 'unchanged' END AS movement FROM units u)")


def _bridge_params(interval):
    start, end = parse_stamp(interval['start']), parse_stamp(interval['end'])
    return [[start, end], ['opening', 'closing'], start, interval['timeZone'], start]


def bridge_statement(metric_id):
    sql = (f'WITH {_bridge_ctes()} SELECT m.movement, m.currency, m.plan, m.opening_plan, sum(m.opening) AS opening, sum(m.closing) AS closing,'
           ' count(*) AS units, count(DISTINCT m.unit) FILTER (WHERE NOT m.unknown AND m.opening > 0) AS opening_units,'
           ' count(DISTINCT m.unit) FILTER (WHERE NOT m.unknown AND m.closing > 0) AS closing_units FROM moves m'
           ' GROUP BY m.movement, m.currency, m.plan, m.opening_plan ORDER BY m.movement, m.currency, m.plan, m.opening_plan LIMIT %s')
    return MetricStatement(metric_id, sql)


def _history(service, interval, required_floor):
    """(ok, since, history) for a definition that needs events covering [start, now) and at least `required_floor` days."""
    probe = _first(service, EVENTS_VIEW, '"recordedAt"', "provider<>'fixture'")
    if probe is None: return None
    instrumented, since = probe
    if not instrumented: return False, None, None
    now = _now(service)
    available = _days((now - parse_stamp(since)).total_seconds())
    required = max(required_floor, math.ceil((now - parse_stamp(interval['start'])).total_seconds() / 86400))
    return available >= required, since, dict(availableDays=available, requiredDays=required)


def _bridge_rows(service, metric, query, interval, stale):
    history = _history(service, interval, BRIDGE_REQUIRED_DAYS)
    if history is None: return _unavailable(metric, interval, 'source_not_configured')
    ok, since, needed = history
    if since is None: return _unavailable(metric, interval, 'not_instrumented')
    if not ok: return _unavailable(metric, interval, 'insufficient_history', collecting_since=since, history=needed)
    rows = execute(service, bridge_statement(metric['id']), _bridge_params(interval) + [MAX_ROWS + 1], MAX_ROWS)
    if rows is None: return _unavailable(metric, interval, 'source_not_configured')
    if metric['id'] == 'logo_churn': return _logo_churn(metric, query, interval, stale, rows, since)
    return _movements(metric, query, interval, stale, rows, since)


def _movements(metric, query, interval, stale, rows, since):
    group_by = _dims(query, {'currency': 1, 'plan': 1, 'movement': 1})
    wanted = {item['dimension']: set(item['values']) for item in query['filters']}
    cells, unknown = defaultdict(lambda: defaultdict(lambda: [0, 0])), defaultdict(int)
    for row in rows:
        movement, currency, plan = row['movement'], row['currency'], row['plan']
        opening, closing, units = number(row['opening']) or 0, number(row['closing']) or 0, number(row['units']) or 0
        if movement == 'unknown':
            unknown[(currency, plan)] += units
            continue
        bucket = cells[(currency, plan)]
        bucket['opening'][0] += opening
        bucket['opening'][1] += number(row['opening_units']) or 0
        bucket['closing'][0] += closing
        bucket['closing'][1] += number(row['closing_units']) or 0
        if movement in MOVEMENTS:
            bucket[movement][0] += closing - opening
            bucket[movement][1] += units
    for key in unknown: cells.setdefault(key, defaultdict(lambda: [0, 0]))
    groups = defaultdict(lambda: dict(value=0, count=0, unknown=0, keys=set()))
    for (currency, plan), bucket in cells.items():
        for movement in BRIDGE_ROWS:
            labels = dict(currency=currency, plan=plan, movement=movement)
            if any(labels.get(dim) not in values for dim, values in wanted.items()): continue
            if 'movement' not in group_by and movement in ('opening', 'closing'): continue   # ungrouped: the net movement
            key = tuple((dim, labels[dim]) for dim in group_by)
            groups[key]['value'] += bucket[movement][0]
            groups[key]['count'] += bucket[movement][1]
            if (currency, plan) not in groups[key]['keys']:
                groups[key]['keys'].add((currency, plan))
                groups[key]['unknown'] += unknown.get((currency, plan), 0)
    order = {name: index for index, name in enumerate(BRIDGE_ROWS)}
    out = []
    for key in sorted(groups, key=lambda item: [order.get(value, 0) if dim == 'movement' else str(value) for dim, value in item]):
        cell = groups[key]
        dims = dict(key)
        state, reason = _state('measured', None, cell['unknown'], stale, 'subscriptions_without_priced_event')
        if 'currency' in dims and not dims['currency'] and state != 'partial': state, reason = 'partial', 'currency_missing'
        out.append(build_row(metric, interval, dims, value=cell['value'], unit='currency_minor', currency=dims.get('currency'), state=state, known=cell['count'],
                             unknown=cell['unknown'], sample_count=cell['count'], reason=reason, measures={'method': 'net_per_customer_v1'}, collecting_since=since))
    if len(out) > MAX_ROWS: raise ControlError('BUDGET_EXCEEDED', 400)
    return out


def _logo_churn(metric, query, interval, stale, rows, since):
    group_by = _dims(query, {'plan': 1})
    wanted = {item['dimension']: set(item['values']) for item in query['filters']}
    groups = defaultdict(lambda: dict(opening=0, churned=0, unknown=0))
    for row in rows:
        plan = row['opening_plan']
        if 'plan' in wanted and plan not in wanted['plan']: continue
        key = tuple((dim, plan) for dim in group_by)
        units = number(row['units']) or 0
        if row['movement'] == 'unknown': groups[key]['unknown'] += units
        else: groups[key]['opening'] += number(row['opening_units']) or 0
        if row['movement'] == 'churn': groups[key]['churned'] += units
    if not groups and not group_by: groups[()]
    out = []
    for key in sorted(groups, key=lambda item: [str(value) for _, value in item]):
        cell = groups[key]
        if not cell['opening']:
            out.append(build_row(metric, interval, dict(key), value=None, unit='ratio', state='not_applicable', numerator=cell['churned'], denominator=0,
                                 unknown=cell['unknown'], reason='no_opening_paid_customers', collecting_since=since))
            continue
        state, reason = _state('measured', None, cell['unknown'], stale, 'subscriptions_without_priced_event')
        out.append(build_row(metric, interval, dict(key), value=cell['churned'] / cell['opening'], unit='ratio', state=state, known=cell['opening'], unknown=cell['unknown'],
                             numerator=cell['churned'], denominator=cell['opening'], sample_count=cell['opening'], reason=reason, collecting_since=since))
    return out


# ---- credits (ledger meta.credits) -------------------------------------------------------------------------------------

CREDIT_DIMS = {'credit_grants': {'grant_source': 'b.grant_source', 'plan': 'b.plan', 'window': live_metrics.WINDOW},
               'credit_consumption': {'task_type': 'b.task_type', 'plan': 'b.plan', 'window': live_metrics.WINDOW}}


def credit_statement(metric_id, query, interval):
    expressions = CREDIT_DIMS[metric_id]
    group_by = _dims(query, expressions)
    if metric_id == 'credit_grants':
        base = (f'SELECT k."workspaceId" AS wid, k.at, {GRANT_SOURCES} AS grant_source, s.plan, k.milli AS amount FROM {CREDITS_VIEW} k'
                f' LEFT JOIN {SUBSCRIPTIONS_VIEW} s ON s."workspaceId"=k."workspaceId" WHERE k.op=\'grant\' AND k.milli IS NOT NULL AND NOT k."aiUsageExempt"'
                f' AND {interval_clause("k.at")} AND {EXCLUDE_CREDIT_WORKSPACE}')
    else:
        base = (f'SELECT k."workspaceId" AS wid, k.at, coalesce(u.feature, \'other\') AS task_type, s.plan, k."usedMilli" AS amount FROM {CREDITS_VIEW} k'
                ' LEFT JOIN rafii_control.business_usage_v2 u ON u.id=k.id'
                f' LEFT JOIN {SUBSCRIPTIONS_VIEW} s ON s."workspaceId"=k."workspaceId" WHERE k.op=\'settle\' AND k."usedMilli" IS NOT NULL AND NOT k."aiUsageExempt"'
                f' AND {interval_clause("k.at")} AND {EXCLUDE_CREDIT_WORKSPACE}')
    params = [interval['start'], interval['end']]
    selected = []
    for dim in group_by:
        selected.append(f'{expressions[dim]} AS "d_{dim}"')
        if dim == 'window': params.append(interval['timeZone'])
    filters = ''
    for item in query['filters']:
        filters += f" AND {expressions[item['dimension']]} = ANY(%s)"
        if item['dimension'] == 'window': params.append(interval['timeZone'])
        params.append(list(item['values']))
    grouping = ', '.join(f'"d_{dim}"' for dim in group_by)
    sql = (f"WITH base AS ({base}) SELECT {', '.join(selected + ['coalesce(sum(b.amount),0) AS value', 'count(*) AS known', 'max(b.at) AS watermark', 'count(*) AS sample_count'])}"
           f' FROM base b WHERE TRUE{filters}' + (f' GROUP BY {grouping} ORDER BY {grouping}' if group_by else '') + ' LIMIT %s')
    return MetricStatement(metric_id, sql), params + [MAX_ROWS + 1], group_by


def _credit_rows(service, metric, query, interval, stale):
    probe = _first(service, CREDITS_VIEW, 'at')
    if probe is None: return _unavailable(metric, interval, 'source_not_configured')
    instrumented, since = probe
    if not instrumented: return _unavailable(metric, interval, 'not_instrumented')
    statement, params, group_by = credit_statement(metric['id'], query, interval)
    rows = execute(service, statement, params, MAX_ROWS)
    if rows is None: return _unavailable(metric, interval, 'source_not_configured')
    out = []
    for row in rows:
        state, reason = _state('measured', None, 0, stale, None)
        out.append(build_row(metric, interval, {dim: row[f'd_{dim}'] for dim in group_by}, value=number(row['value']), unit='millicredits', state=state,
                             known=number(row['known']), watermark=row.get('watermark'), sample_count=number(row['sample_count']), reason=reason, collecting_since=since))
    return out


AVAILABLE_SQL = (f'SELECT k.id, k."workspaceId" AS wid, k."reservationId", k.op, k.milli, k."grantId", k."expiresAtEpoch", k.allocations, s.plan, k.at FROM {CREDITS_VIEW} k'
                 f' LEFT JOIN {SUBSCRIPTIONS_VIEW} s ON s."workspaceId"=k."workspaceId" WHERE k.at < %s::timestamptz AND NOT k."aiUsageExempt"'
                 f' AND {EXCLUDE_CREDIT_WORKSPACE} ORDER BY k."workspaceId", k.at, k.id LIMIT %s')


def _available_rows(service, metric, query, interval, stale):
    from postriff_phase2.credit_wallet import project_credit_wallet
    probe = _first(service, CREDITS_VIEW, 'at')
    if probe is None: return _unavailable(metric, interval, 'source_not_configured')
    instrumented, since = probe
    if not instrumented: return _unavailable(metric, interval, 'not_instrumented')
    group_by = _dims(query, {'plan': 1})
    end = parse_stamp(interval['end'])
    try:
        rows = execute(service, MetricStatement(metric['id'], AVAILABLE_SQL), (end, CREDIT_ROW_LIMIT + 1), CREDIT_ROW_LIMIT)
    except ControlError:
        return _unavailable(metric, interval, 'credit_history_over_read_limit', collecting_since=since)
    if rows is None: return _unavailable(metric, interval, 'source_not_configured')
    by_workspace = defaultdict(list)
    for row in rows: by_workspace[row['wid']].append(row)
    wanted = {item['dimension']: set(item['values']) for item in query['filters']}
    groups = defaultdict(lambda: dict(available=0, held=0, debt=0, known=0, unknown=0, at=None))
    for workspace, entries in by_workspace.items():
        plan = entries[-1].get('plan')
        if 'plan' in wanted and plan not in wanted['plan']: continue
        key = tuple((dim, plan) for dim in group_by)
        cell = groups[key]
        ledger = [dict(id=row['id'], reservationId=row.get('reservationId'),
                       credits=dict(op=row['op'], milli=number(row.get('milli')), grantId=row.get('grantId'), expiresAt=number(row.get('expiresAtEpoch')),
                                    allocations=[dict(grantId=item.get('grantId'), milli=number(item.get('milli'))) for item in (row.get('allocations') or [])]))
                  for row in entries]
        try:
            wallet = project_credit_wallet(ledger, end.timestamp())
        except (ValueError, TypeError, KeyError):
            cell['unknown'] += 1
            continue
        cell['available'] += wallet['availableMilliCredits']
        cell['held'] += wallet['heldMilliCredits']
        cell['debt'] += wallet['debtMilliCredits']
        cell['known'] += 1
        cell['at'] = max(filter(None, (cell['at'], entries[-1].get('at'))), default=None)
    if not groups and not group_by: groups[()]
    out = []
    for key in sorted(groups, key=lambda item: [str(value) for _, value in item]):
        cell = groups[key]
        state, reason = _state('measured', None, cell['unknown'], stale, 'wallet_projection_failed')
        out.append(build_row(metric, interval, dict(key), value=cell['available'], unit='millicredits', state=state, known=cell['known'], unknown=cell['unknown'],
                             watermark=cell['at'], sample_count=cell['known'] + cell['unknown'], reason=reason,
                             measures={'heldMilliCredits': cell['held'], 'debtMilliCredits': cell['debt']}, collecting_since=since))
    return out


# ---- forecast (P2 scenario over daily snapshots) -----------------------------------------------------------------------

FORECAST_SQL = (f"SELECT h.day::text AS day, h.currency, sum(h.\"mrrMinor\") AS mrr, count(*) FILTER (WHERE h.\"mrrMinor\" IS NULL AND h.status IN ('active','past_due')) AS unknown"
                f" FROM {SNAPSHOTS_VIEW} h WHERE h.provider<>'fixture' AND h.day < (%s::timestamptz AT TIME ZONE %s)::date AND h.day >= (%s::timestamptz AT TIME ZONE %s)::date - 366"
                f" AND {EXCLUDE_SNAPSHOT_WORKSPACE} GROUP BY h.day, h.currency ORDER BY h.day, h.currency LIMIT %s")


def fit_line(points):
    """Ordinary least squares over [(x, y)]: (slope, intercept)."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    slope = 0.0 if not spread else sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
    return slope, mean_y - slope * mean_x


def forecast_rows(metric, query, interval, series, *, stale, since, fixture=False, extra_measures=None):
    """Rows for one or more currencies: series = {currency: [(date, total, unknown_count)]} (ascending, one per day)."""
    group_by = _dims(query, {'currency': 1, 'window': 1})
    wanted = {item['dimension']: set(item['values']) for item in query['filters']}
    targets = _instants(interval, 'window' in group_by)
    zone = ZoneInfo(interval['timeZone'])
    out = []
    for currency in sorted(series, key=str):
        if 'currency' in wanted and currency not in wanted['currency']: continue
        points = [point for point in series[currency] if point[1] is not None]
        dims = {'currency': currency} if 'currency' in group_by else {}
        if len(points) < FORECAST_REQUIRED_DAYS:
            out.append(build_row(metric, interval, dims, value=None, unit='currency_minor', currency=currency, state='unavailable', reason='insufficient_history',
                                 collecting_since=since, history=dict(availableDays=len(points), requiredDays=FORECAST_REQUIRED_DAYS), fixture=fixture))
            continue
        fit = points[-FORECAST_FIT_DAYS:]
        origin = fit[0][0]
        slope, intercept = fit_line([((day - origin).days, total) for day, total, _ in fit])
        unknown = sum(1 for _, _, missing in fit if missing)
        measures = dict(basis='scenario', method=FORECAST_METHOD, fitDays=len(fit), slopePerDayMinor=round(slope, 4), lastActualMinor=fit[-1][1],
                        lastActualDay=fit[-1][0].isoformat(), **(extra_measures or {}))
        for at, label in targets:
            day = date_of(label) if label else (at - timedelta(microseconds=1)).astimezone(zone).date()
            projected = max(0, round(intercept + slope * (day - origin).days))
            labels = {**dims, **({'window': label} if 'window' in group_by else {})}
            if 'window' in wanted and label not in wanted['window']: continue
            state, reason = _state('measured', None, unknown, stale, 'snapshot_days_with_unknown_mrr')
            out.append(build_row(metric, interval, labels, value=projected, unit='currency_minor', currency=currency, state=state, known=len(fit) - unknown,
                                 unknown=unknown, sample_count=len(fit), reason=reason, measures=dict(measures), collecting_since=since, fixture=fixture))
    if len(out) > MAX_ROWS: raise ControlError('BUDGET_EXCEEDED', 400)
    return out


def date_of(label):
    return datetime.strptime(label, '%Y-%m-%d').date()


def _forecast_rows(service, metric, query, interval, stale):
    zone = interval['timeZone']
    end = parse_stamp(interval['end'])
    now = _now(service)
    cut = min(end, now)   # the fit uses only snapshot days before the interval end and before now
    rows = execute(service, MetricStatement(metric['id'], FORECAST_SQL), (cut, zone, cut, zone, 366 * 8), 366 * 8)
    if rows is None: return _unavailable(metric, interval, 'source_not_configured')
    series = defaultdict(dict)
    for row in rows:
        currency = row.get('currency')
        if row.get('mrr') is None and currency is None: continue   # snapshots without any priced event carry no MRR yet
        day = date_of(row['day'])
        series[currency][day] = (day, number(row['mrr']), number(row['unknown']) or 0)
    if not series: return _unavailable(metric, interval, 'not_instrumented')
    since = min(min(days) for days in series.values()).isoformat()
    return forecast_rows(metric, query, interval, {currency: [days[day] for day in sorted(days)] for currency, days in series.items()}, stale=stale, since=since)


# ---- Demo parity (the candidate v2 catalog in the founder's Demo dataset) ------------------------------------------------

def _demo_stamp(value):
    try: return parse_stamp(value) if isinstance(value, str) else None
    except ValueError: return None


def _demo_subscriptions(data):
    for row in data.get('subscriptions', []):
        if not row.get('paid', True): continue
        cycle = DEMO_CYCLES.get(row.get('billingCycle'))
        amount = row.get('amountMinor')
        yield dict(at=_demo_stamp(row.get('startedAt')), wid=row.get('workspaceId'), plan=row.get('plan'), status=row.get('status'), currency=row.get('currency'),
                   mrr=monthly(amount, *cycle) if cycle and type(amount) is int and amount >= 0 else None)


def _demo_measures(**extra): return dict(catalogLabel=DEMO_CATALOG, **extra)


def _demo_group(records, group_by, wanted, dims):
    groups = defaultdict(list)
    for record in records:
        labels = {dim: record.get(dim) for dim in dims}
        if any(labels.get(dim) not in values for dim, values in wanted.items()): continue
        groups[tuple((dim, labels[dim]) for dim in group_by)].append(record)
    return groups


def _demo_sweep(records, instants):
    """Yield (instant, label, present) in ascending instant order, adding records whose start precedes each instant. Demo
    statuses carry no history, so a record counts from its start at its current status (as the P0 snapshot metrics do)."""
    ordered = sorted((row for row in records if row['at']), key=lambda row: row['at'])
    index, present = 0, []
    for at, label in sorted(instants, key=lambda item: item[0]):
        while index < len(ordered) and ordered[index]['at'] < at:
            present.append(ordered[index])
            index += 1
        yield at, label, present


def demo_mrr(metric, data, query, interval, now, stale):
    group_by = _dims(query, MRR_DIMS)
    wanted = {item['dimension']: set(item['values']) for item in query['filters'] if item['dimension'] != 'window'}
    windows = {value for item in query['filters'] if item['dimension'] == 'window' for value in item['values']}
    keyed = [dim for dim in group_by if dim != 'window']
    delinquent = metric['id'] == 'delinquent_mrr'
    records = [row for row in _demo_subscriptions(data) if row['status'] in MRR_STATUSES and not any(row.get(dim) not in values for dim, values in wanted.items())]
    totals, seen, out = defaultdict(lambda: [0, 0, 0, 0]), 0, []   # value, members, unknown, paying per non-window key
    for at, label, present in _demo_sweep(records, _instants(interval, 'window' in group_by)):
        for row in present[seen:]:
            cell = totals[tuple((dim, row.get(dim)) for dim in keyed)]   # every MRR group exists, so no delinquency is a measured zero
            if delinquent and row['status'] != 'past_due': continue
            cell[0] += row['mrr'] or 0
            cell[1] += 1
            cell[2] += row['mrr'] is None
            cell[3] += (row['mrr'] or 0) > 0
        seen = len(present)
        if windows and label not in windows: continue
        keys = sorted(totals, key=lambda item: [str(value) for _, value in item]) or ([()] if not keyed else [])
        for key in keys:
            value, members, unknown, paying = totals[key] if key in totals else (0, 0, 0, 0)
            dims = {**dict(key), **({'window': label} if 'window' in group_by else {})}
            state, reason = _state('measured', None, unknown, stale, 'subscriptions_without_priced_event')
            out.append(build_row(metric, interval, {dim: dims[dim] for dim in group_by}, value=value, unit='currency_minor', currency=dims.get('currency'), state=state,
                                 known=members - unknown, unknown=unknown, watermark=stamp(min(at, now)), sample_count=members, reason=reason,
                                 measures=_demo_measures(payingSubscriptions=paying), fixture=True))
        if len(out) > MAX_ROWS: raise ControlError('BUDGET_EXCEEDED', 400)
    return out


def _demo_credit_records(data, kind):
    workspaces = {row['id']: row for row in data.get('workspaces', [])}
    usage = {row['id']: row for row in data.get('usage', [])}
    for row in data.get('credits', []):
        if row.get('kind') != kind or type(row.get('quantity')) is not int: continue
        workspace = workspaces.get(row.get('workspaceId'), {})
        task = demo_metrics.FEATURES.get((usage.get(row.get('usageId')) or {}).get('dimension'), 'other')
        yield dict(at=_demo_stamp(row.get('at')), wid=row.get('workspaceId'), plan=workspace.get('plan'), grant_source='subscription', task_type=task,
                   amount=abs(row['quantity']) * 1000)


def demo_credits(metric, data, query, interval, now, stale):
    dims = ('grant_source', 'plan', 'window') if metric['id'] == 'credit_grants' else ('task_type', 'plan', 'window')
    group_by = _dims(query, {dim: 1 for dim in dims})
    wanted = {item['dimension']: set(item['values']) for item in query['filters']}
    start, end = parse_stamp(interval['start']), parse_stamp(interval['end'])
    zone = ZoneInfo(interval['timeZone'])
    records = [dict(row, window=row['at'].astimezone(zone).strftime('%Y-%m-%d')) for row in _demo_credit_records(data, 'grant' if metric['id'] == 'credit_grants' else 'settle')
               if row['at'] and start <= row['at'] < end]
    groups = _demo_group(records, group_by, wanted, dims)
    if not groups and not group_by: groups[()] = []
    out = []
    for key in sorted(groups, key=lambda item: [str(value) for _, value in item]):
        members = groups[key]
        state, reason = _state('measured', None, 0, stale, None)
        stamps = [row['at'] for row in members]
        out.append(build_row(metric, interval, dict(key), value=sum(row['amount'] for row in members), unit='millicredits', state=state, known=len(members),
                             watermark=stamp(max(stamps)) if stamps else None, sample_count=len(members), reason=reason, measures=_demo_measures(), fixture=True))
    return out


def demo_available(metric, data, query, interval, now, stale):
    group_by = _dims(query, {'plan': 1})
    wanted = {item['dimension']: set(item['values']) for item in query['filters']}
    records = [dict(plan=row.get('plan'), amount=row['creditsRemaining'] * 1000) for row in data.get('workspaces', []) if type(row.get('creditsRemaining')) is int]
    groups = _demo_group(records, group_by, wanted, ('plan',))
    if not groups and not group_by: groups[()] = []
    state, reason = _state('measured', None, 0, stale, None)
    return [build_row(metric, interval, dict(key), value=sum(row['amount'] for row in groups[key]), unit='millicredits', state=state, known=len(groups[key]),
                      watermark=stamp(now), sample_count=len(groups[key]), reason=reason, measures=_demo_measures(heldMilliCredits=0, debtMilliCredits=0), fixture=True)
            for key in sorted(groups, key=lambda item: [str(value) for _, value in item])]


def demo_forecast(metric, data, query, interval, now, stale):
    """Daily Demo MRR totals for the FORECAST_FIT_DAYS local days before asOf (subscriptions started by each day's end, at
    their current status), then the same least-squares scenario as Live."""
    zone = ZoneInfo(interval['timeZone'])
    today = now.astimezone(zone).date()
    days = [today - timedelta(days=offset) for offset in range(FORECAST_FIT_DAYS, 0, -1)]
    instants = [(datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone), day.isoformat()) for day in days]
    records = [row for row in _demo_subscriptions(data) if row['status'] in MRR_STATUSES]
    totals, seen, series = defaultdict(lambda: [0, 0]), 0, defaultdict(list)
    for _, label, present in _demo_sweep(records, instants):
        for row in present[seen:]:
            totals[row['currency']][0] += row['mrr'] or 0
            totals[row['currency']][1] += row['mrr'] is None
        seen = len(present)
        for currency, (total, unknown) in totals.items(): series[currency].append((date_of(label), total, unknown))
    if not series: return demo_metrics.not_simulated(metric, data, query, interval, now, stale)
    since = min(points[0][0] for points in series.values()).isoformat()
    return forecast_rows(metric, query, interval, series, stale=stale, since=since, fixture=True, extra_measures=dict(catalogLabel=DEMO_CATALOG))


# ---- routes ----------------------------------------------------------------------------------------------------------------

def _route_interval(app, query, now):
    """`start`/`end` (ISO 8601, both or neither, ≤366 days) or `period=Nd` ending now, in the report time zone."""
    zone = live_metrics.TIME_ZONE
    if 'start' in query or 'end' in query:
        try:
            start, end = parse_stamp(query['start'][0]), parse_stamp(query['end'][0])
        except (KeyError, IndexError, ValueError, AttributeError):
            raise ControlError('VALIDATION_FAILED', 400) from None
        if not start.tzinfo or not end.tzinfo or not timedelta(0) < end - start <= timedelta(days=366): raise ControlError('VALIDATION_FAILED', 400)
        return dict(start=stamp(start), end=stamp(end), timeZone=zone)
    days = int(app.query_period(query)[:-1])
    if days > 366: raise ControlError('VALIDATION_FAILED', 400)
    return dict(start=stamp(now - timedelta(days=days)), end=stamp(now), timeZone=zone)


def _route_now(app, principal, request):
    """(now, demo data): Demo periods end at the Demo dataset's own asOf (as the Overview does), never at wall-clock time."""
    if request['mode'] == 'demo':
        data = app.queries.demo_data(principal)
        return parse_stamp(data['asOf']) + timedelta(seconds=1), data
    return datetime.fromtimestamp(float(request['now']), timezone.utc), None


def _customer_href(customer, mode):
    """Customer 360 on the Customers page (`?record=<customer id>`, the workspace owner); None when there is no owner."""
    if not isinstance(customer, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', customer): return None
    return f'/founder/customers?record={customer}' + ('&mode=demo' if mode == 'demo' else '')


OWNER_SQL = 'SELECT w."ownerId" FROM rafii_control.business_workspaces w WHERE w.id = {}'


MOVEMENT_ROWS_SQL = (f'WITH {_bridge_ctes()} SELECT m.unit, m.wid, ({OWNER_SQL.format("m.wid")}) AS owner, m.subs, m.currency, m.plan, m.opening_status, m.closing_status,'
                     ' m.opening, m.closing, m.movement FROM moves m WHERE m.movement = ANY(%s) ORDER BY abs(m.closing - m.opening) DESC, m.unit LIMIT %s')
MOVEMENT_EVENTS_SQL = ('SELECT e.id, e."eventId", e."eventType", e."providerSubscriptionId", e."workspaceId", e."eventAt", e.applied, e."priorStatus", e."newStatus",'
                       ' coalesce(e."newPlan", e."newTermsId") AS plan, e."unitAmountMinor", e.quantity, e."interval", e."intervalCount", e.currency, e."discountMinor"'
                       f' FROM {EVENTS_VIEW} e WHERE e.provider<>\'fixture\' AND coalesce(e."providerSubscriptionId", \'workspace:\' || coalesce(e."workspaceId", e.id)) = ANY(%s)'
                       ' AND e."eventAt" >= %s::timestamptz AND e."eventAt" < %s::timestamptz ORDER BY e."eventAt", e.id LIMIT %s')


def movements(app, principal, request):
    """GET /revenue/movements?mode=&period=|start=&end=&movement= → the customers behind one bridge segment (≤200), each with
    its subscription ids, plan, status change, opening/closing/delta MRR and the billing events inside the interval."""
    from .intelligence import QueryService
    QueryService.require(principal, 'metrics.query')
    query, mode = request['query'], request['mode']
    now, data = _route_now(app, principal, request)
    interval = _route_interval(app, query, now)
    movement = query.get('movement', [None])[0]
    if movement is not None and movement not in MOVEMENTS: raise ControlError('VALIDATION_FAILED', 400)
    selected = [movement] if movement else list(MOVEMENTS)
    base = dict(mode=mode, interval=interval, movement=movement, limit=ROUTE_LIMIT, definition='Net change per customer and currency between the opening and closing MRR.')
    if mode == 'demo':
        return dict(base, rows=[], truncated=False, reason='demo_not_simulated', catalogLabel=DEMO_CATALOG, _dataState='unavailable',
                    _receiptIds=[data['receipt']['id']] if data.get('receipt') else [])
    service = app.queries
    history = _history(service, interval, BRIDGE_REQUIRED_DAYS)
    if history is None: return dict(base, rows=[], truncated=False, reason='source_not_configured', _dataState='unavailable')
    ok, since, needed = history
    if since is None: return dict(base, rows=[], truncated=False, reason='not_instrumented', _dataState='unavailable')
    if not ok: return dict(base, rows=[], truncated=False, reason='insufficient_history', collectingSince=since, history=needed, _dataState='unavailable')
    rows = execute(service, MetricStatement('revenue_movements', MOVEMENT_ROWS_SQL), _bridge_params(interval) + [selected, ROUTE_LIMIT + 1], ROUTE_LIMIT + 1)
    if rows is None: return dict(base, rows=[], truncated=False, reason='source_not_configured', _dataState='unavailable')
    truncated, rows = len(rows) > ROUTE_LIMIT, rows[:ROUTE_LIMIT]
    keys = sorted({key for row in rows for key in (row.get('subs') or []) if key})
    events = execute(service, MetricStatement('revenue_movement_events', MOVEMENT_EVENTS_SQL),
                     (keys, interval['start'], interval['end'], ROUTE_LIMIT * EVENTS_PER_UNIT + 1), ROUTE_LIMIT * EVENTS_PER_UNIT + 1) if keys else []
    by_key = defaultdict(list)
    for event in events or []:
        key = event.get('providerSubscriptionId') or 'workspace:' + str(event.get('workspaceId') or event.get('id'))
        by_key[key].append(dict(id=event['id'], eventId=event.get('eventId'), type=event.get('eventType'), at=event.get('eventAt'), applied=event.get('applied'),
                                priorStatus=event.get('priorStatus'), newStatus=event.get('newStatus'), plan=event.get('plan'), unitAmountMinor=number(event.get('unitAmountMinor')),
                                quantity=event.get('quantity'), interval=event.get('interval'), intervalCount=event.get('intervalCount'), currency=event.get('currency'),
                                discountMinor=number(event.get('discountMinor'))))
    out = []
    for row in rows:
        subs = [key for key in (row.get('subs') or []) if key]
        opening, closing = number(row['opening']) or 0, number(row['closing']) or 0
        listed = sorted((event for key in subs for event in by_key.get(key, [])), key=lambda event: (event['at'] or '', event['id']))
        out.append(dict(customer=row['unit'], workspaceId=row.get('wid'), customerId=row.get('owner'), subscriptionIds=[key for key in subs if not key.startswith('workspace:')], plan=row.get('plan'),
                        currency=row.get('currency'), movement=row['movement'], statusChange=dict(opening=row.get('opening_status'), closing=row.get('closing_status')),
                        openingMrrMinor=opening, closingMrrMinor=closing, deltaMinor=closing - opening, events=listed[:EVENTS_PER_UNIT],
                        eventsTruncated=len(listed) > EVENTS_PER_UNIT, href=_customer_href(row.get('owner'), mode)))
    return dict(base, rows=out, truncated=truncated, collectingSince=since, _dataState='measured')


INVOICE_STATUSES = ('draft', 'open', 'paid', 'uncollectible', 'void')
INVOICE_OWNER = OWNER_SQL.format('i."workspaceId"')
INVOICES_SQL = (f'SELECT i."invoiceId", i."workspaceId", ({INVOICE_OWNER}) AS owner, i."subscriptionId", i."billingReason", i."periodStart", i."periodEnd", i."amountDueMinor", i."amountPaidMinor",'
                f' i.currency, i.status, i.livemode, i."eventAt" FROM {INVOICES_VIEW} i WHERE i.provider<>\'fixture\' AND {interval_clause("i.\"eventAt\"")}'
                f' AND (i."workspaceId" IS NULL OR {EXCLUDE_INVOICE_WORKSPACE}) AND i.status = ANY(%s) ORDER BY i."eventAt" DESC, i."invoiceId" LIMIT %s')


def invoices(app, principal, request):
    """GET /revenue/invoices?mode=&period=|start=&end=&status= → invoice records (≤200, newest first) for the invoices and
    dunning tables: ids, workspace link, billing reason, service period, amounts in native minor units, status."""
    from .intelligence import QueryService
    QueryService.require(principal, 'metrics.query')
    query, mode = request['query'], request['mode']
    now, data = _route_now(app, principal, request)
    interval = _route_interval(app, query, now)
    status = query.get('status', [None])[0]
    if status is not None and status not in INVOICE_STATUSES: raise ControlError('VALIDATION_FAILED', 400)
    statuses = [status] if status else list(INVOICE_STATUSES)
    base = dict(mode=mode, interval=interval, status=status, limit=ROUTE_LIMIT)
    if mode == 'demo':
        start, end = parse_stamp(interval['start']), parse_stamp(interval['end'])
        picked = []
        for row in data.get('invoices', []):
            at = _demo_stamp(row.get('paidAt') or row.get('issuedAt'))
            demo_status = 'open' if row.get('status') == 'past_due' else row.get('status')
            if at is None or not start <= at < end or demo_status not in statuses: continue
            picked.append(dict(invoiceId=row['id'], workspaceId=row.get('workspaceId'), customerId=row.get('customerId'), subscriptionId=row.get('subscriptionId'), billingReason=None,
                               periodStart=None, periodEnd=None, amountDueMinor=row.get('amountMinor'), amountPaidMinor=row.get('amountMinor') if demo_status == 'paid' else 0,
                               currency=row.get('currency'), status=demo_status, livemode=False, eventAt=stamp(at), href=_customer_href(row.get('customerId'), mode)))
        picked.sort(key=lambda row: (row['eventAt'], row['invoiceId']), reverse=True)
        return dict(base, rows=picked[:ROUTE_LIMIT], truncated=len(picked) > ROUTE_LIMIT, catalogLabel=DEMO_CATALOG, _dataState='synthetic',
                    _receiptIds=[data['receipt']['id']] if data.get('receipt') else [])
    probe = _first(app.queries, INVOICES_VIEW, '"recordedAt"', "provider<>'fixture'")
    if probe is None: return dict(base, rows=[], truncated=False, reason='source_not_configured', _dataState='unavailable')
    if not probe[0]: return dict(base, rows=[], truncated=False, reason='not_instrumented', _dataState='unavailable')
    rows = execute(app.queries, MetricStatement('revenue_invoices', INVOICES_SQL), (interval['start'], interval['end'], statuses, ROUTE_LIMIT + 1), ROUTE_LIMIT + 1)
    if rows is None: return dict(base, rows=[], truncated=False, reason='source_not_configured', _dataState='unavailable')
    out = [dict(invoiceId=row['invoiceId'], workspaceId=row.get('workspaceId'), customerId=row.get('owner'), subscriptionId=row.get('subscriptionId'), billingReason=row.get('billingReason'),
                periodStart=row.get('periodStart'), periodEnd=row.get('periodEnd'), amountDueMinor=number(row.get('amountDueMinor')), amountPaidMinor=number(row.get('amountPaidMinor')),
                currency=row.get('currency'), status=row.get('status'), livemode=row.get('livemode'), eventAt=row.get('eventAt'), href=_customer_href(row.get('owner'), mode))
           for row in rows[:ROUTE_LIMIT]]
    return dict(base, rows=out, truncated=len(rows) > ROUTE_LIMIT, collectingSince=probe[1], _dataState='measured')


# ---- cash_collected v2 (catalog-gated) -----------------------------------------------------------------------------------

# The catalog row that activates cash_collected v2. It belongs in metrics.d/revenue.json once intelligence.Catalog lets a
# metrics.d row supersede an activated metrics.json row with a higher version (today a second activated row is refused).
CASH_COLLECTED_V2_ROW = {
    'id': 'cash_collected', 'version': 2, 'title': 'Cash collected', 'grain': 'funds movement', 'unit': 'currency_minor',
    'definition': 'Sum of funded live-mode credit orders, live-mode paid invoices of every plan (pr_invoices.amount_paid at the paid event) and live-mode '
                  'credit-plan invoice grants whose invoice is not in pr_invoices (deduplicated by invoice id), in the half-open interval, by native currency.',
    'source_contract': 'pr_credit_orders + pr_invoices + pr_credit_subscription_grants', 'allowed_dimensions': ['currency', 'payment_type', 'window'],
    'query_template_ref': 'metrics/cash_collected/v2', 'default_exclusions': ['synthetic', 'test', 'internal_founder_activity', 'ai_usage_exempt', 'fixture_subscriptions'],
    'data_state_required': True, 'currency_policy': 'native_currency_separate', 'zero_denominator': 'not_applicable', 'refresh_target': 'event_driven_or_15m',
    'limitations': 'Partial: invoices issued before the 057 billing-event instrumentation were never stored and provider fees are not recorded; gross of refunds (see refunds_disputes).',
    'status': 'activated_v1',
    'activation': {'definitionVersion': 'v2', 'liveAdapter': 'rafii_control.live_metrics', 'demoAdapter': 'rafii_control.demo_metrics',
                   'migration': '057_founder_billing_events+063_founder_revenue_views', 'snapshot': False, 'prd': '7.1 M06'},
}


def activate_cash_collected(catalog=None):
    """Serve cash_collected v2 only when the governing catalog row is version 2 or later; otherwise keep v1 (the bump and the
    definition change always travel together). Returns the governing version."""
    try:
        from .intelligence import Catalog
        version = int((catalog if catalog is not None else Catalog()).metrics['cash_collected'].get('version') or 1)
    except Exception:  # noqa: BLE001 - an unreadable catalog keeps the definition already in force
        version = 1
    live_metrics.SPECS['cash_collected'] = live_metrics.CASH_COLLECTED_V2 if version >= 2 else live_metrics.CASH_COLLECTED_V1
    return version


# ---- registration ----------------------------------------------------------------------------------------------------------

LIVE = {'mrr': _mrr_rows, 'delinquent_mrr': _mrr_rows, 'mrr_movements': _bridge_rows, 'logo_churn': _bridge_rows, 'credit_grants': _credit_rows,
        'credit_consumption': _credit_rows, 'credit_available': _available_rows, 'mrr_forecast': _forecast_rows}
DEMO = {'mrr': demo_mrr, 'delinquent_mrr': demo_mrr, 'mrr_movements': demo_metrics.not_simulated, 'logo_churn': demo_metrics.not_simulated,
        'credit_grants': demo_credits, 'credit_consumption': demo_credits, 'credit_available': demo_available, 'mrr_forecast': demo_forecast}

live_metrics.register(custom={metric_id: ({'rows': fn, 'previous': None} if metric_id == 'mrr_forecast' else {'rows': fn}) for metric_id, fn in LIVE.items()},
                      sources={metric_id: 'database' for metric_id in LIVE})
demo_metrics.register(DEMO)
http.register_route('GET', r'/revenue/movements', 'metrics.query', 'founder_metrics_revenue', 'movements')
http.register_route('GET', r'/revenue/invoices', 'metrics.query', 'founder_metrics_revenue', 'invoices')
activate_cash_collected()
