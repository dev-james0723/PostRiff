"""Founder product analytics (CONTRACTS §8.C; PRD §7.1 M21/M23/M24, §7.2, §10.2 P1-2, §10.3 correlations).

Six activated metrics, Live and Demo, one row contract (live_metrics.build_row):
- activation_funnel (M23 definition v1): workspaces created in the interval whose 14-day window has matured, and how
  many reached each journey step within 14 days of creation (workspace.created → channel.connected → voice.activated →
  draft.created → draft.approved → post.scheduled → publish.verified). Every step says which source it used: the §8.6
  taxonomy where it covers the cohort, else the M23 transition proxy (audit channel.connected, learning draft.approved /
  post.published, publish notifications) as a lower bound. A step without a proxy counts only workspaces created after
  its taxonomy began collecting and reports the rest as unknown, never as "not reached".
- time_to_value: median seconds from creation to the first value event (first Time Back draft/publish row or first
  verified publication) within the same 14 days, with n, quartiles and the workspaces that reached none.
- feature_adoption: share of the interval's active workspaces (activity definition v1) that used each feature.
- retention_weekly: weekly signup cohort × weeks since signup (0–12). Only matured cells carry a value, n/d per cell;
  unmatured cells are returned without one so they render grey. insufficient_history until 8 weeks of history exist.
- time_back (M24): saved seconds by confidence (measured | personalized | estimated), never merged.
- retention_correlations (P2, hypothesis): per feature, the retained share (active in weeks 4–7) among workspaces that
  adopted it in their first 14 days vs the rest, with n. basis='hypothesis'; small groups are suppressed.

Boundaries: fixed reader-role SQL over the rafii_control projections of 054 and 065 with bound parameters only; customer
metrics exclude workspaces classified internal/test/demo. A projection that does not exist reads 'source_not_configured',
new instrumentation 'not_instrumented' (with collectingSince once it has rows), never zero. The founder cron stage
`product_rollups` keeps learning-event history past its 180-day TTL in public.pr_learning_daily_rollups (059).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import demo_metrics, founder_cron, http, live_metrics
from .auth import ControlError
from .live_metrics import TIME_ZONE, build_row, excluded, execute, number, parse_stamp, stamp
from .store import MetricStatement

WINDOW_DAYS = 14              # M23 activation window, also the time-to-value horizon
RETENTION_WEEKS = 12          # cohort columns: weeks 0..12 since signup
REQUIRED_HISTORY_DAYS = 56    # 8 matured weeks (CONTRACTS §8.0)
RETAINED_DAYS = (28, 56)      # correlations: retained = active in days [28, 56) after creation (weeks 4–7)
MIN_GROUP = 10                # correlations: adopters and non-adopters each need this many workspaces
LIMIT = live_metrics.MAX_POINTS + 1
PUBLISH_EVENTS = live_metrics.PUBLISH_EVENTS
# Person-initiated taxonomy events that count as activity beside the active_workspaces v1 sources.
PERSON_EVENTS = ('channel.connected', 'voice.created', 'brand.created', 'draft.created', 'draft.edited', 'draft.discarded', 'review.approved',
                 'post.scheduled', 'campaign.created', 'automation.created', 'suggestion.accepted', 'research.completed')
LEARNING_PROXIES = ('draft.approved', 'post.published')

# (step, taxonomy event, transition proxy or None). The first step is the cohort anchor (workspace creation).
STEPS = (
    ('workspace_created', None, 'workspace_start'),
    ('channel_connected', 'channel.connected', 'audit:channel.connected'),
    ('voice_activated', 'voice.created', None),
    ('draft_created', 'draft.created', None),
    ('draft_approved', 'review.approved', 'learning:draft.approved'),
    ('post_scheduled', 'post.scheduled', None),
    ('publish_verified', 'publish.verified', 'notification:publish.verified+learning:post.published'),
)
# Feature -> (taxonomy event, (property, value) or None, transition proxies). Proxies are fixed SQL sources below.
FEATURES = (
    ('voice', 'voice.created', None, ()),
    ('brand', 'brand.created', None, ()),
    ('write_like_me', 'draft.created', ('voice', 'personalized'), ()),
    ('quick_start', 'draft.created', ('feature', 'quick_start'), ()),
    ('agent_drafting', 'draft.created', ('feature', 'agent'), ()),
    ('review', 'review.approved', None, ('learning:draft.approved',)),
    ('scheduling', 'post.scheduled', None, ()),
    ('publishing', 'publish.verified', None, ('notification:publish.verified', 'learning:post.published')),
    ('campaigns', 'campaign.created', None, ()),
    ('automations', 'automation.created', None, ()),
    ('suggestions', 'suggestion.accepted', None, ()),
    ('research', 'research.completed', None, ()),
    ('humanizer', 'humanizer.applied', None, ()),
    ('weekly_operator', 'weekly_operator.enabled', None, ()),
)
FEATURE_IDS = tuple(feature for feature, *_ in FEATURES)
TAXONOMY_EVENTS = tuple(dict.fromkeys([event for _, event, _ in STEPS if event] + [event for _, event, _, _ in FEATURES]))


class Q:
    """Positional parameters collected in the order the f-string placeholders are evaluated."""
    def __init__(self):
        self.params = []

    def __call__(self, value):
        self.params.append(value)
        return '%s'


def _quote_list(values):
    """A fixed, module-defined literal list (never browser input) for IN (...)."""
    return '(' + ','.join("'" + value.replace("'", "''") + "'" for value in values) + ')'


def _ws(alias):
    return excluded(f'{alias}."workspaceId"')


def _activity(q, start, end):
    """Activity definition v1: active_workspaces v1 sources (completed/applied agent runs, publish outcomes) plus the
    person-initiated taxonomy events. Rows (wid, at) in [start, end)."""
    return ('SELECT r."workspaceId" AS wid, r."createdAt" AS at FROM rafii_control.business_agent_runs r'
            f' WHERE r.status IN (\'completed\',\'applied\') AND r."createdAt" >= {q(start)}::timestamptz AND r."createdAt" < {q(end)}::timestamptz'
            ' UNION ALL SELECT n."workspaceId", n."occurredAt" FROM rafii_control.business_notification_events n'
            f' WHERE n."eventType" IN {PUBLISH_EVENTS} AND n."workspaceId" IS NOT NULL AND n."occurredAt" >= {q(start)}::timestamptz AND n."occurredAt" < {q(end)}::timestamptz'
            ' UNION ALL SELECT p."workspaceId", p."occurredAt" FROM rafii_control.business_product_events p'
            f' WHERE p.event IN {_quote_list(PERSON_EVENTS)} AND p."workspaceId" IS NOT NULL AND p."occurredAt" >= {q(start)}::timestamptz AND p."occurredAt" < {q(end)}::timestamptz')


def _learning(q, start, end, rollups, label=True):
    """Learning-event proxies (draft.approved, post.published): the live rows plus, where 059/065 exist, the daily
    rollup's first timestamps that outlive the 180-day TTL. min()/exists semantics only, so overlap never double counts."""
    src = "'learning:' || l.kind" if label else 'l.kind'
    sql = (f'SELECT l."workspaceId" AS wid, {src} AS src, l.at FROM rafii_control.business_learning_events l'
           f' WHERE l.kind IN {_quote_list(LEARNING_PROXIES)} AND l.at >= {q(start)}::timestamptz AND l.at < {q(end)}::timestamptz')
    if rollups:
        src = "'learning:' || r.kind" if label else 'r.kind'
        sql += (f' UNION ALL SELECT r."workspaceId", {src}, r."firstAt" FROM rafii_control.business_learning_rollups r'
                f' WHERE r.kind IN {_quote_list(LEARNING_PROXIES)} AND r."firstAt" >= {q(start)}::timestamptz AND r."firstAt" < {q(end)}::timestamptz')
    return sql


def _run(service, name, build, limit=LIMIT):
    """Execute a statement built as build(q, rollups); retried without the learning rollup projection when only that
    projection is missing. None when a required projection is missing (source_not_configured)."""
    for rollups in (True, False):
        q = Q()
        sql = build(q, rollups)
        rows = execute(service, MetricStatement(name, sql), q.params, limit)
        if rows is not None or 'business_learning_rollups' not in sql:
            return rows
    return None


def _shift(value, days):
    return stamp(parse_stamp(value) + timedelta(days=days))


def _iso(value):
    if value is None: return None
    if isinstance(value, datetime): return stamp(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    try: return stamp(parse_stamp(str(value)))
    except ValueError: return None


def _now(service):
    value = service.clock()
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _unavailable(metric, interval, reason, dims=None, **extra):
    return [build_row(metric, interval, dims or {}, value=None, unit=metric['unit'], state='unavailable', reason=reason, **extra)]


def _filtered(rows, query):
    """Catalog-validated filters over the fixed dimensions this module produces."""
    wanted = [(item['dimension'], {str(value) for value in item['values']}) for item in query['filters']]
    return [row for row in rows if all(dim not in row['dimensions'] or str(row['dimensions'][dim]) in values for dim, values in wanted)]


def _state(state, stale, reason=None):
    if stale and state == 'measured': return 'stale', 'source_stale'
    return state, reason


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


# ---- activation_funnel ------------------------------------------------------------------------------------------------

# Per-workspace flags of the funnel statement: t<i> taxonomy reached step i, p<i> its transition proxy reached it.
FLAG_SOURCES = (('t1', ('channel.connected',)), ('p1', ('audit:channel.connected',)), ('t2', ('voice.created',)), ('t3', ('draft.created',)),
                ('t4', ('review.approved',)), ('p4', ('learning:draft.approved',)), ('t5', ('post.scheduled',)), ('t6', ('publish.verified',)),
                ('p6', ('notification:publish.verified', 'learning:post.published')))


def _funnel_sql(q, rollups, interval, as_of, cohort_grouped):
    """Aggregate funnel: one row per (cohort, matured, flag pattern) with its workspace count."""
    sql = _funnel_ctes(q, rollups, interval, as_of, cohort_grouped)
    keys = 'cohort, matured, ' + ', '.join(name for name, _ in FLAG_SOURCES) + ', ' + ', '.join(f'c{index}' for index in range(1, len(STEPS)))
    covered = ', '.join(f'coalesce(w.started >= since.s{index}, false) AS c{index}' for index in range(1, len(STEPS)))
    sinces = ', '.join(f'min(since.s{index}) AS s{index}' for index in range(1, len(STEPS)))
    sql += (f' SELECT {keys}, count(*) AS n, max(last_at) AS watermark, {sinces}'
            f' FROM (SELECT w.*, {covered} FROM per_ws w CROSS JOIN since) x CROSS JOIN since'
            f' GROUP BY {keys} ORDER BY {keys} LIMIT {q(LIMIT)}')
    return sql


def _reach_sql(index):
    """SQL truth of 'reached step index' over per_ws columns (index 0, the anchor, is always reached)."""
    if index == 0: return 'TRUE'
    names = [name for name, _ in FLAG_SOURCES if name[1:] == str(index)]
    return '(' + ' OR '.join(f'w.{name}' for name in names) + ')'


def _known_sql(index):
    """Whether 'not reached' is a known outcome: the step has a proxy, or the taxonomy observed this workspace's window."""
    if index == 0 or STEPS[index][2]: return 'TRUE'
    return f'coalesce(w.started >= since.s{index}, false)'


def _stuck_sql(q, rollups, interval, as_of, index):
    """Matured workspaces that reached the previous step (known) but not step `index` (known), oldest first."""
    sql = _funnel_ctes(q, rollups, interval, as_of, False)
    sql += (f' SELECT w.wid, w.started FROM per_ws w CROSS JOIN since WHERE w.matured AND {_reach_sql(index - 1)}'
            f' AND NOT {_reach_sql(index)} AND {_known_sql(index)} ORDER BY w.started, w.wid LIMIT {q(STUCK_LIMIT + 1)}')
    return sql


def _funnel_ctes(q, rollups, interval, as_of, cohort_grouped):
    """cohort, since, hits and per_ws CTEs, built strictly left to right: every q() runs in the order its placeholder
    appears in the text."""
    start, end, zone = interval['start'], interval['end'], interval['timeZone']
    reach_end = _shift(end, WINDOW_DAYS)
    events = [event for _, event, _ in STEPS if event]
    sql = ('WITH cohort AS (SELECT s."workspaceId" AS wid, s."createdAt" AS started FROM rafii_control.business_workspace_starts s'
           f' WHERE s."createdAt" >= {q(start)}::timestamptz AND s."createdAt" < {q(end)}::timestamptz AND {_ws("s")}),')
    sql += ' since AS (SELECT ' + ', '.join(f'(SELECT min(e."occurredAt") FROM rafii_control.business_product_events e WHERE e.event={q(event)}) AS s{index}'
                                           for index, (_, event, _) in enumerate(STEPS) if event) + '),'
    sql += (' hits AS (SELECT e."workspaceId" AS wid, e.event AS src, e."occurredAt" AS at FROM rafii_control.business_product_events e'
            f' WHERE e.event IN {_quote_list(events)} AND e."occurredAt" >= {q(start)}::timestamptz AND e."occurredAt" < {q(reach_end)}::timestamptz'
            ' UNION ALL SELECT a."workspaceId", \'audit:channel.connected\', a.at FROM rafii_control.business_channel_audit a'
            f' WHERE a.kind=\'channel.connected\' AND a.at >= {q(start)}::timestamptz AND a.at < {q(reach_end)}::timestamptz'
            ' UNION ALL SELECT n."workspaceId", \'notification:publish.verified\', n."occurredAt" FROM rafii_control.business_notification_events n'
            f' WHERE n."eventType"=\'publish.verified\' AND n."workspaceId" IS NOT NULL AND n."occurredAt" >= {q(start)}::timestamptz AND n."occurredAt" < {q(reach_end)}::timestamptz'
            f' UNION ALL {_learning(q, start, reach_end, rollups)}),')
    sql += ' per_ws AS (SELECT c.wid, c.started, '
    sql += f"to_char(date_trunc('week', c.started AT TIME ZONE {q(zone)}),'YYYY-MM-DD')" if cohort_grouped else 'NULL::text'
    sql += f' AS cohort, c.started + interval \'{WINDOW_DAYS} days\' <= {q(as_of)}::timestamptz AS matured, '
    sql += ', '.join(f"coalesce(bool_or(h.src IN ({','.join(q(src) for src in sources)})),false) AS {name}" for name, sources in FLAG_SOURCES)
    sql += (f', max(h.at) AS last_at FROM cohort c LEFT JOIN hits h ON h.wid=c.wid AND h.at >= c.started AND h.at < c.started + interval \'{WINDOW_DAYS} days\''
            ' GROUP BY c.wid, c.started)')
    return sql


def _reached(row, index):
    """Taxonomy and proxy flags for STEPS[index] (index >= 1) of one pattern row."""
    tax = bool(row.get(f't{index}'))
    proxy = bool(row.get(f'p{index}')) if STEPS[index][2] else False
    return tax, proxy


def _funnel_rows(service, metric, query, interval, stale):
    cohort_grouped = 'cohort' in query['groupBy']
    as_of = stamp(_now(service))
    rows = _run(service, 'activation_funnel', lambda q, rollups: _funnel_sql(q, rollups, interval, as_of, cohort_grouped))
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    by_cohort = {}
    for row in rows:
        by_cohort.setdefault(row.get('cohort') if cohort_grouped else None, []).append(row)
    if not by_cohort and cohort_grouped:
        return []
    result = []
    for cohort_key, patterns in sorted(by_cohort.items(), key=lambda item: str(item[0])) or [(None, [])]:
        result.extend(_funnel_cohort(metric, interval, patterns, cohort_key, cohort_grouped, stale))
    return _filtered(result, query)


def _funnel_cohort(metric, interval, patterns, cohort_key, cohort_grouped, stale):
    matured = [row for row in patterns if row.get('matured')]
    population = sum(number(row['n']) for row in matured)
    immature = sum(number(row['n']) for row in patterns if not row.get('matured'))
    watermark = max((_iso(row.get('watermark')) for row in patterns if row.get('watermark')), default=None)
    since = {index: _iso((patterns[0] if patterns else {}).get(f's{index}')) for index in range(1, len(STEPS))}
    dims = lambda step: {'step': step, **({'cohort': cohort_key} if cohort_grouped else {})}  # noqa: E731
    out = []
    state, reason = _state('measured', stale)
    out.append(build_row(metric, interval, dims(STEPS[0][0]), value=population, unit='count', state=state, known=population, numerator=population, denominator=population,
                         watermark=watermark, sample_count=population, reason=reason,
                         measures={'order': 1, 'source': 'workspace_start', 'rate': 1.0 if population else None, 'immature': immature, 'windowDays': WINDOW_DAYS}))
    previous_rate = 1.0 if population else None

    def reached(row, index):
        if index == 0: return True
        tax, proxy = _reached(row, index)
        return tax or proxy

    for index in range(1, len(STEPS)):
        step, event, proxy_label = STEPS[index]
        if not population:
            out.append(build_row(metric, interval, dims(step), value=None, unit='count', state='not_applicable', reason='no_matured_workspaces',
                                 collecting_since=since[index], measures={'order': index + 1, 'source': None, 'proxy': proxy_label, 'immature': immature}))
            continue
        covered = sum(number(row['n']) for row in matured if row.get(f'c{index}'))
        tax_reached = sum(number(row['n']) for row in matured if _reached(row, index)[0])
        proxy_reached = sum(number(row['n']) for row in matured if _reached(row, index)[1])
        if proxy_label:
            numerator, denominator, known, unknown = sum(number(row['n']) for row in matured if reached(row, index)), population, population, 0
            source = 'taxonomy' if covered == population else 'transition_proxy' if covered == 0 else 'taxonomy+transition_proxy'
            state, reason = ('measured', None) if source == 'taxonomy' else ('partial', 'transition_proxy')
            # Same definition as the drill-down route (_stuck_sql): reached the previous step, not this one, and that is known.
            stuck = sum(number(row['n']) for row in matured if reached(row, index - 1) and not reached(row, index))
        else:
            numerator = sum(number(row['n']) for row in matured if row.get(f'c{index}') and _reached(row, index)[0])
            denominator, known, unknown, source = covered, covered, population - covered, 'taxonomy'
            stuck = sum(number(row['n']) for row in matured if row.get(f'c{index}') and reached(row, index - 1) and not _reached(row, index)[0])
            if covered == 0:
                out.append(build_row(metric, interval, dims(step), value=None, unit='count', state='unavailable', known=0, unknown=population,
                                     reason='not_instrumented' if since[index] is None else 'collecting_since_after_cohort_start', collecting_since=since[index],
                                     measures={'order': index + 1, 'source': 'taxonomy', 'proxy': None, 'immature': immature}))
                previous_rate = None
                continue
            state, reason = ('measured', None) if unknown == 0 else ('partial', 'collecting_since_after_cohort_start')
        state, reason = _state(state, stale, reason)
        rate = _rate(numerator, denominator)
        out.append(build_row(metric, interval, dims(step), value=numerator, unit='count', state=state, known=known, unknown=unknown, numerator=numerator, denominator=denominator,
                             watermark=watermark, sample_count=denominator, reason=reason, collecting_since=since[index],
                             measures={'order': index + 1, 'source': source, 'proxy': proxy_label, 'taxonomyReached': tax_reached, 'proxyReached': proxy_reached,
                                       'rate': rate, 'dropFromPrevious': (previous_rate - rate) if previous_rate is not None and rate is not None else None,
                                       'stuckFromPrevious': stuck, 'immature': immature, 'windowDays': WINDOW_DAYS}))
        previous_rate = rate
    return out


# ---- time_to_value ----------------------------------------------------------------------------------------------------

def _ttv_sql(q, rollups, interval, as_of, cohort_grouped):
    """Built strictly left to right (see _funnel_sql)."""
    start, end, zone = interval['start'], interval['end'], interval['timeZone']
    reach_end = _shift(end, WINDOW_DAYS)
    head = (f'WITH cohort AS (SELECT s."workspaceId" AS wid, s."createdAt" AS started FROM rafii_control.business_workspace_starts s'
            f' WHERE s."createdAt" >= {q(start)}::timestamptz AND s."createdAt" < {q(end)}::timestamptz AND {_ws("s")}),')
    firsts = ('SELECT t."workspaceId" AS wid, \'time_back\' AS src, t."occurredAt" AS at FROM rafii_control.business_time_savings t'
              f' WHERE t."taskKind" IN (\'draft\',\'publish\') AND t."occurredAt" >= {q(start)}::timestamptz AND t."occurredAt" < {q(reach_end)}::timestamptz'
              ' UNION ALL SELECT e."workspaceId", \'taxonomy\', e."occurredAt" FROM rafii_control.business_product_events e'
              f' WHERE e.event=\'publish.verified\' AND e."occurredAt" >= {q(start)}::timestamptz AND e."occurredAt" < {q(reach_end)}::timestamptz'
              ' UNION ALL SELECT n."workspaceId", \'transition_proxy\', n."occurredAt" FROM rafii_control.business_notification_events n'
              f' WHERE n."eventType"=\'publish.verified\' AND n."workspaceId" IS NOT NULL AND n."occurredAt" >= {q(start)}::timestamptz AND n."occurredAt" < {q(reach_end)}::timestamptz'
              f' UNION ALL SELECT g.wid, \'transition_proxy\', g.at FROM ({_learning(q, start, reach_end, rollups, label=False)}) g WHERE g.src=\'post.published\'')
    cohort = f"to_char(date_trunc('week', c.started AT TIME ZONE {q(zone)}),'YYYY-MM-DD')" if cohort_grouped else 'NULL::text'
    body = (f' firsts AS ({firsts}),'
            f' first_by_ws AS (SELECT c.wid, c.started, {cohort} AS cohort, c.started + interval \'{WINDOW_DAYS} days\' <= {q(as_of)}::timestamptz AS matured,'
            ' min(f.at) AS first_at, (array_agg(f.src ORDER BY f.at, f.src))[1] AS first_src FROM cohort c'
            f' LEFT JOIN firsts f ON f.wid=c.wid AND f.at >= c.started AND f.at < c.started + interval \'{WINDOW_DAYS} days\' GROUP BY c.wid, c.started)'
            ' SELECT cohort, count(*) FILTER (WHERE matured) AS cohort_n, count(*) FILTER (WHERE NOT matured) AS immature,'
            ' count(first_at) FILTER (WHERE matured) AS n,'
            ' percentile_cont(0.5) WITHIN GROUP (ORDER BY CASE WHEN matured THEN extract(epoch FROM first_at - started)::float8 END) AS median,'
            ' percentile_cont(0.25) WITHIN GROUP (ORDER BY CASE WHEN matured THEN extract(epoch FROM first_at - started)::float8 END) AS p25,'
            ' percentile_cont(0.75) WITHIN GROUP (ORDER BY CASE WHEN matured THEN extract(epoch FROM first_at - started)::float8 END) AS p75,'
            " count(*) FILTER (WHERE matured AND first_src='time_back') AS via_time_back, count(*) FILTER (WHERE matured AND first_src='taxonomy') AS via_taxonomy,"
            " count(*) FILTER (WHERE matured AND first_src='transition_proxy') AS via_proxy, max(first_at) AS watermark"
            f' FROM first_by_ws GROUP BY cohort ORDER BY cohort LIMIT {q(LIMIT)}')
    return head + body


def _ttv_rows(service, metric, query, interval, stale):
    cohort_grouped = 'cohort' in query['groupBy']
    as_of = stamp(_now(service))
    rows = _run(service, 'time_to_value', lambda q, rollups: _ttv_sql(q, rollups, interval, as_of, cohort_grouped))
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    out = []
    for row in rows or ([] if cohort_grouped else [dict(cohort=None, cohort_n=0, immature=0, n=0)]):
        dims = {'cohort': row.get('cohort')} if cohort_grouped else {}
        cohort_n, n, immature = number(row.get('cohort_n')) or 0, number(row.get('n')) or 0, number(row.get('immature')) or 0
        measures = {'n': n, 'cohort': cohort_n, 'noFirstValue': cohort_n - n, 'immature': immature, 'p25': _seconds(row.get('p25')), 'p75': _seconds(row.get('p75')),
                    'windowDays': WINDOW_DAYS, 'firstValueSources': {'time_back': number(row.get('via_time_back')) or 0, 'taxonomy': number(row.get('via_taxonomy')) or 0,
                                                                       'transition_proxy': number(row.get('via_proxy')) or 0}}
        if not cohort_n:
            out.append(build_row(metric, interval, dims, value=None, unit='seconds', state='not_applicable', reason='no_matured_workspaces', measures=measures))
        elif not n:
            out.append(build_row(metric, interval, dims, value=None, unit='seconds', state='not_applicable', known=cohort_n, numerator=0, denominator=cohort_n,
                                 sample_count=0, reason='no_first_value_in_window', measures=measures))
        else:
            state, reason = _state('measured', stale)
            out.append(build_row(metric, interval, dims, value=_seconds(row.get('median')), unit='seconds', state=state, known=cohort_n, numerator=n, denominator=cohort_n,
                                 watermark=_iso(row.get('watermark')), sample_count=n, reason=reason, measures=measures))
    return _filtered(out, query)


def _seconds(value):
    value = number(value)
    return None if value is None else int(round(value))


# ---- feature_adoption -------------------------------------------------------------------------------------------------

def _feature_map(q):
    rows = []
    for feature, event, prop, _ in FEATURES:
        rows.append(f'({q(feature)}, {q(event)}, {q(prop[0]) if prop else "NULL"}, {q(prop[1]) if prop else "NULL"})')
    return 'fmap(feature, event, prop, val) AS (VALUES ' + ', '.join(rows) + ')'


def _feature_hits(q, rollups, start, end):
    """(feature, wid, at, kind) for every feature event in [start, end): taxonomy rows mapped by event and enum property,
    plus the fixed transition proxies of the review and publishing features."""
    return ('SELECT m.feature, e."workspaceId" AS wid, e."occurredAt" AS at, \'taxonomy\' AS kind FROM rafii_control.business_product_events e'
            ' JOIN fmap m ON m.event=e.event AND (m.prop IS NULL OR (m.prop=\'voice\' AND e.voice=m.val) OR (m.prop=\'feature\' AND e.feature=m.val))'
            f' WHERE e."occurredAt" >= {q(start)}::timestamptz AND e."occurredAt" < {q(end)}::timestamptz'
            f' UNION ALL SELECT CASE WHEN g.src=\'draft.approved\' THEN \'review\' ELSE \'publishing\' END, g.wid, g.at, \'proxy\' FROM ({_learning(q, start, end, rollups, label=False)}) g'
            ' UNION ALL SELECT \'publishing\', n."workspaceId", n."occurredAt", \'proxy\' FROM rafii_control.business_notification_events n'
            f' WHERE n."eventType"=\'publish.verified\' AND n."workspaceId" IS NOT NULL AND n."occurredAt" >= {q(start)}::timestamptz AND n."occurredAt" < {q(end)}::timestamptz')


def _since(service):
    """{event: ISO of its earliest taxonomy row or None} for every event this module reads."""
    q = Q()
    sql = ('SELECT ev AS event, (SELECT min(e."occurredAt") FROM rafii_control.business_product_events e WHERE e.event=ev) AS since'
           f' FROM unnest({q(list(TAXONOMY_EVENTS))}::text[]) AS ev')
    rows = execute(service, MetricStatement('product_since', sql), q.params)
    return None if rows is None else {row['event']: _iso(row.get('since')) for row in rows}


def _adoption_sql(q, rollups, interval):
    start, end = interval['start'], interval['end']
    return (f'WITH {_feature_map(q)},'
            f' eligible AS (SELECT DISTINCT a.wid FROM ({_activity(q, start, end)}) a WHERE {excluded("a.wid")}),'
            f' hits AS ({_feature_hits(q, rollups, start, end)})'
            ' SELECT h.feature, count(DISTINCT h.wid) AS adopters, count(DISTINCT h.wid) FILTER (WHERE h.kind=\'taxonomy\') AS taxonomy,'
            ' count(DISTINCT h.wid) FILTER (WHERE h.kind=\'proxy\') AS proxy, max(h.at) AS watermark, (SELECT count(*) FROM eligible) AS eligible'
            ' FROM hits h JOIN eligible e ON e.wid=h.wid GROUP BY h.feature'
            ' UNION ALL SELECT NULL, 0, 0, 0, NULL, (SELECT count(*) FROM eligible)'
            f' ORDER BY 1 NULLS FIRST LIMIT {q(LIMIT)}')


def _adoption_rows(service, metric, query, interval, stale):
    rows = _run(service, 'feature_adoption', lambda q, rollups: _adoption_sql(q, rollups, interval))
    since = _since(service) if rows is not None else None
    if rows is None or since is None:
        return _unavailable(metric, interval, 'source_not_configured')
    eligible = number(next((row['eligible'] for row in rows), 0)) or 0
    hits = {row['feature']: row for row in rows if row.get('feature')}
    start = parse_stamp(interval['start'])
    out = []
    for feature, event, _, proxies in FEATURES:
        row, collecting = hits.get(feature, {}), since.get(event)
        adopters = number(row.get('adopters')) or 0
        measures = {'adopters': adopters, 'taxonomyAdopters': number(row.get('taxonomy')) or 0, 'proxyAdopters': number(row.get('proxy')) or 0,
                    'eligible': eligible, 'eligibleDefinition': 'activity_v1', 'event': event, 'proxies': list(proxies)}
        dims = {'feature': feature}
        if not eligible:
            out.append(build_row(metric, interval, dims, value=None, unit='ratio', state='not_applicable', reason='no_active_workspaces', collecting_since=collecting, measures=measures))
            continue
        if collecting is None and not proxies:
            out.append(build_row(metric, interval, dims, value=None, unit='ratio', state='unavailable', reason='not_instrumented', denominator=eligible, measures=measures))
            continue
        complete = collecting is not None and parse_stamp(collecting) <= start
        measures['source'] = 'taxonomy' if complete else 'transition_proxy' if collecting is None else 'taxonomy+transition_proxy' if proxies else 'taxonomy'
        state, reason = ('measured', None) if complete else ('partial', 'transition_proxy' if proxies else 'collecting_since_after_interval_start')
        state, reason = _state(state, stale, reason)
        out.append(build_row(metric, interval, dims, value=adopters / eligible, unit='ratio', state=state, known=eligible, numerator=adopters, denominator=eligible,
                             watermark=_iso(row.get('watermark')), sample_count=eligible, reason=reason, collecting_since=collecting, measures=measures))
    return _filtered(out, query)


# ---- retention_weekly -------------------------------------------------------------------------------------------------

def _history(service, as_of):
    """Days between the earliest non-excluded workspace creation and as_of; None when the projection is missing."""
    sql = f'SELECT min(s."createdAt") AS first FROM rafii_control.business_workspace_starts s WHERE {_ws("s")}'
    rows = execute(service, MetricStatement('product_history', sql), ())
    if rows is None: return None
    first = _iso(rows[0].get('first')) if rows else None
    return 0 if first is None else max(0, int((as_of - parse_stamp(first)).total_seconds() // 86400))


def _retention_sql(q, interval, as_of):
    start, end, zone = interval['start'], interval['end'], interval['timeZone']
    return (f'WITH cohort AS (SELECT s."workspaceId" AS wid, date_trunc(\'week\', s."createdAt" AT TIME ZONE {q(zone)}) AS cw FROM rafii_control.business_workspace_starts s'
            f' WHERE s."createdAt" >= {q(start)}::timestamptz AND s."createdAt" < {q(end)}::timestamptz AND {_ws("s")}),'
            f' activity AS ({_activity(q, start, as_of)}),'
            f' active AS (SELECT c.cw, a.wid, floor(extract(epoch FROM (date_trunc(\'week\', a.at AT TIME ZONE {q(zone)}) - c.cw)) / 604800)::int AS k, a.at'
            ' FROM cohort c JOIN activity a ON a.wid=c.wid)'
            " SELECT to_char(c.cw,'YYYY-MM-DD') AS cohort, NULL::int AS week, count(*) AS n, NULL::timestamptz AS watermark FROM cohort c GROUP BY c.cw"
            " UNION ALL SELECT to_char(cw,'YYYY-MM-DD'), k, count(DISTINCT wid), max(at) FROM active"
            f' WHERE k BETWEEN 0 AND {RETENTION_WEEKS} GROUP BY cw, k ORDER BY 1, 2 NULLS FIRST LIMIT {q(LIMIT)}')


def _retention_rows(service, metric, query, interval, stale):
    now = _now(service)
    available = _history(service, now)
    if available is None:
        return _unavailable(metric, interval, 'source_not_configured')
    if available < REQUIRED_HISTORY_DAYS:
        return _unavailable(metric, interval, 'insufficient_history', history={'availableDays': available, 'requiredDays': REQUIRED_HISTORY_DAYS})
    as_of = stamp(now)
    q = Q()
    rows = execute(service, MetricStatement('retention_weekly', _retention_sql(q, interval, as_of)), q.params)
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    return _filtered(_cells(metric, interval, rows, now, stale, ZoneInfo(interval['timeZone'])), query)


def _cells(metric, interval, rows, now, stale, zone):
    sizes = {row['cohort']: number(row['n']) for row in rows if row.get('week') is None}
    active = {(row['cohort'], number(row['week'])): row for row in rows if row.get('week') is not None}
    out = []
    for cohort in sorted(sizes):
        size = sizes[cohort]
        week_start = datetime.fromisoformat(cohort).replace(tzinfo=zone)
        for week in range(RETENTION_WEEKS + 1):
            dims = {'cohort': cohort, 'week': week}
            cell_end = (week_start + timedelta(days=7 * (week + 1))).astimezone(timezone.utc)
            if cell_end > now:
                out.append(build_row(metric, interval, dims, value=None, unit='ratio', state='not_applicable', denominator=size, sample_count=size, reason='cell_not_matured',
                                     measures={'cellEnd': stamp(cell_end)}))
                continue
            row = active.get((cohort, week), {})
            count = number(row.get('n')) or 0
            state, reason = _state('measured', stale)
            out.append(build_row(metric, interval, dims, value=count / size if size else None, unit='ratio', state=state if size else 'not_applicable', known=size,
                                 numerator=count, denominator=size, watermark=_iso(row.get('watermark')), sample_count=size, reason=reason if size else 'empty_cohort',
                                 measures={'cellEnd': stamp(cell_end)}))
    return out


# ---- retention_correlations (P2 hypothesis) ---------------------------------------------------------------------------

def _correlation_sql(q, rollups, interval, as_of):
    start, end = interval['start'], interval['end']
    proxied = sorted({feature for feature, _, _, proxies in FEATURES if proxies})
    return (f'WITH {_feature_map(q)},'
            f' since AS (SELECT m.event, (SELECT min(e."occurredAt") FROM rafii_control.business_product_events e WHERE e.event=m.event) AS at FROM (SELECT DISTINCT event FROM fmap) m),'
            f' features AS (SELECT m.feature, m.feature IN {_quote_list(proxied)} AS proxied, min(s.at) AS since FROM fmap m LEFT JOIN since s ON s.event=m.event GROUP BY m.feature),'
            f' cohort AS (SELECT s."workspaceId" AS wid, s."createdAt" AS started FROM rafii_control.business_workspace_starts s'
            f' WHERE s."createdAt" >= {q(start)}::timestamptz AND s."createdAt" < {q(end)}::timestamptz'
            f' AND s."createdAt" + interval \'{RETAINED_DAYS[1]} days\' <= {q(as_of)}::timestamptz AND {_ws("s")}),'
            f' hits AS ({_feature_hits(q, rollups, start, _shift(end, WINDOW_DAYS))}),'
            f' adopted AS (SELECT DISTINCT h.feature, c.wid FROM cohort c JOIN hits h ON h.wid=c.wid AND h.at >= c.started AND h.at < c.started + interval \'{WINDOW_DAYS} days\'),'
            f' activity AS ({_activity(q, start, as_of)}),'
            f' retained AS (SELECT DISTINCT c.wid FROM cohort c JOIN activity a ON a.wid=c.wid AND a.at >= c.started + interval \'{RETAINED_DAYS[0]} days\''
            f' AND a.at < c.started + interval \'{RETAINED_DAYS[1]} days\')'
            ' SELECT f.feature, min(f.since) AS since, count(c.wid) AS population,'
            ' count(c.wid) FILTER (WHERE ad.wid IS NOT NULL) AS adopters, count(c.wid) FILTER (WHERE ad.wid IS NOT NULL AND r.wid IS NOT NULL) AS adopters_retained,'
            ' count(c.wid) FILTER (WHERE ad.wid IS NULL) AS non_adopters, count(c.wid) FILTER (WHERE ad.wid IS NULL AND r.wid IS NOT NULL) AS non_adopters_retained'
            ' FROM features f LEFT JOIN cohort c ON f.proxied OR (f.since IS NOT NULL AND c.started >= f.since)'
            ' LEFT JOIN adopted ad ON ad.feature=f.feature AND ad.wid=c.wid LEFT JOIN retained r ON r.wid=c.wid'
            f' GROUP BY f.feature ORDER BY f.feature LIMIT {q(LIMIT)}')


def _correlation_rows(service, metric, query, interval, stale):
    now = _now(service)
    available = _history(service, now)
    if available is None:
        return _unavailable(metric, interval, 'source_not_configured')
    if available < REQUIRED_HISTORY_DAYS:
        return _unavailable(metric, interval, 'insufficient_history', history={'availableDays': available, 'requiredDays': REQUIRED_HISTORY_DAYS},
                            measures={'basis': 'hypothesis'})
    as_of = stamp(now)
    rows = _run(service, 'retention_correlations', lambda q, rollups: _correlation_sql(q, rollups, interval, as_of))
    if rows is None:
        return _unavailable(metric, interval, 'source_not_configured')
    by_feature = {row['feature']: row for row in rows}
    out = []
    for feature, event, _, proxies in FEATURES:
        row = by_feature.get(feature, {})
        since = _iso(row.get('since'))
        adopters, kept = number(row.get('adopters')) or 0, number(row.get('adopters_retained')) or 0
        others, others_kept = number(row.get('non_adopters')) or 0, number(row.get('non_adopters_retained')) or 0
        share, other_share = _rate(kept, adopters), _rate(others_kept, others)
        measures = {'basis': 'hypothesis', 'adopters': adopters, 'adoptersRetained': kept, 'nonAdopters': others, 'nonAdoptersRetained': others_kept,
                    'nonAdopterShare': other_share, 'difference': share - other_share if share is not None and other_share is not None else None,
                    'adoptionWindowDays': WINDOW_DAYS, 'retainedDays': list(RETAINED_DAYS), 'event': event, 'proxies': list(proxies),
                    'note': 'Correlation among matured cohorts, not a causal effect.'}
        dims = {'feature': feature}
        if not number(row.get('population')):
            covered = 0 if since is None and not proxies else max(0, int((now - parse_stamp(since)).total_seconds() // 86400)) if since else available
            out.append(build_row(metric, interval, dims, value=None, unit='ratio', state='unavailable', reason='not_instrumented' if since is None and not proxies else 'insufficient_history',
                                 collecting_since=since, history={'availableDays': covered, 'requiredDays': REQUIRED_HISTORY_DAYS}, measures=measures))
        elif adopters < MIN_GROUP or others < MIN_GROUP:
            out.append(build_row(metric, interval, dims, value=None, unit='ratio', state='suppressed', reason='sample_too_small', known=adopters + others,
                                 sample_count=adopters + others, collecting_since=since, measures={**measures, 'minimumGroup': MIN_GROUP}))
        else:
            state, reason = _state('measured', stale)
            out.append(build_row(metric, interval, dims, value=share, unit='ratio', state=state, known=adopters + others, numerator=kept, denominator=adopters,
                                 sample_count=adopters + others, reason=reason, collecting_since=since, measures=measures))
    return _filtered(out, query)


# ---- time_back (M24): a fixed SPECS statement through live_metrics ----------------------------------------------------

_OCCURRED = 't."occurredAt"'
TIME_BACK = dict(base=('SELECT t."workspaceId" AS wid, t."occurredAt" AS at, t.confidence, t."taskKind" AS task_kind, t."savedSeconds" AS saved'
                       f' FROM rafii_control.business_time_savings t WHERE {live_metrics.interval_clause(_OCCURRED)} AND {_ws("t")}'),
                 interval_params=1, probe='rafii_control.business_time_savings', implicit=('confidence',), value='coalesce(sum(b.saved),0)',
                 dims={'confidence': 'b.confidence', 'task_type': 'b.task_kind'}, unit='seconds')


# ---- Demo parity ------------------------------------------------------------------------------------------------------

def _demo_funnel(metric, data, query, interval, now, stale):
    """The Demo dataset holds workspace creation dates but no journey events: the anchor step is computed, every later
    step is reported as not simulated (never zero)."""
    start, end = parse_stamp(interval['start']), parse_stamp(interval['end'])
    cohort_grouped = 'cohort' in query['groupBy']
    zone = ZoneInfo(interval['timeZone'])
    groups = {}
    for row in data.get('workspaces', []):
        try: created = parse_stamp(row.get('createdAt'))
        except (AttributeError, TypeError, ValueError): continue
        if start <= created < end and created + timedelta(days=WINDOW_DAYS) <= now:
            local = created.astimezone(zone)
            key = (local - timedelta(days=local.weekday())).strftime('%Y-%m-%d') if cohort_grouped else None
            groups[key] = groups.get(key, 0) + 1
    if cohort_grouped and not groups:
        return []
    out = []
    for key, population in sorted(groups.items(), key=lambda item: str(item[0])) or [(None, 0)]:
        dims = lambda step: {'step': step, **({'cohort': key} if cohort_grouped else {})}  # noqa: E731
        state, reason = _state('measured', stale)
        out.append(build_row(metric, interval, dims(STEPS[0][0]), value=population, unit='count', state=state, known=population, numerator=population,
                             denominator=population, watermark=stamp(now), sample_count=population, reason=reason, fixture=True,
                             measures={'order': 1, 'source': 'workspace_start', 'windowDays': WINDOW_DAYS}))
        for index in range(1, len(STEPS)):
            out.append(build_row(metric, interval, dims(STEPS[index][0]), value=None, unit='count', state='unavailable', reason='demo_not_simulated', fixture=True,
                                 measures={'order': index + 1, 'source': None, 'proxy': STEPS[index][2]}))
    return _filtered(out, query)


def _demo_not_simulated(metric, data, query, interval, now, stale):
    rows = demo_metrics.not_simulated(metric, data, query, interval, now, stale)
    if metric['id'] == 'retention_correlations':
        rows[0]['measures'] = {'basis': 'hypothesis'}
    return rows


# ---- learning rollup cron stage ---------------------------------------------------------------------------------------

ROLLUP_KINDS = ('draft.edited', 'draft.update_accepted', 'draft.rejected', 'draft.approved', 'job.cancelled', 'post.published', 'chat.instruction', 'proposal.decided')
ROLLUP_EVERY_SECONDS = 3600
RECOMPUTE_DAYS = 3
BACKFILL_DAYS = 181


def _consumer(service):
    return getattr(service, 'connection_factory', None) or getattr(getattr(service, 'repository', None), 'connection_factory', None)


def rollup_stage(fstore, service, values, now):
    """Founder cron stage `product_rollups`: at most hourly, recompute the learning-event daily rollup (059) from the last
    rolled day (at least the last three report-time-zone days, at most the 180-day TTL) and purge expired rows. Bounded,
    idempotent, consumer connection only; returns counts, never raises into the tick (founder_cron._stage)."""
    factory = _consumer(service)
    if factory is None:
        return {'status': 'unavailable', 'reason': 'consumer_connection_missing'}
    zone = ZoneInfo(TIME_ZONE)
    today = datetime.fromtimestamp(float(now), zone).date()
    with factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_learning_daily_rollups')")
        if cur.fetchone()[0] is None:
            return {'status': 'unavailable', 'reason': 'table_missing'}
        cur.execute('SELECT extract(epoch FROM max(computed_at)), max(day) FROM public.pr_learning_daily_rollups')
        last, latest = cur.fetchone()
        if last is not None and float(now) - float(last) < ROLLUP_EVERY_SECONDS:
            return {'status': 'ok', 'skipped': 'fresh'}
        first = today - timedelta(days=(RECOMPUTE_DAYS - 1) if latest is not None else BACKFILL_DAYS)
        if latest is not None:
            first = min(first, latest)
        first = max(first, today - timedelta(days=BACKFILL_DAYS))
        since = datetime(first.year, first.month, first.day, tzinfo=zone)
        cur.execute('INSERT INTO public.pr_learning_daily_rollups(day,workspace_id,kind,events,first_at,computed_at)'
                    ' SELECT (l.created_at AT TIME ZONE %s)::date, l.workspace_id, l.kind, count(*), min(l.created_at), now() FROM public.pr_learning_events l'
                    ' WHERE l.created_at >= %s::timestamptz AND l.kind = ANY(%s) GROUP BY 1, 2, 3'
                    ' ON CONFLICT (day, workspace_id, kind) DO UPDATE SET events=excluded.events, first_at=excluded.first_at, computed_at=excluded.computed_at',
                    (TIME_ZONE, since, list(ROLLUP_KINDS)))
        upserted = max(0, cur.rowcount or 0)
        cur.execute('DELETE FROM public.pr_learning_daily_rollups WHERE expires_at < %s::date', (today,))
        purged = max(0, cur.rowcount or 0)
        db.commit()
    return {'status': 'ok', 'from': first.isoformat(), 'upserted': upserted, 'purged': purged}


# ---- funnel drill-down route ------------------------------------------------------------------------------------------

STUCK_LIMIT = 200
STEP_INDEX = {step: index for index, (step, _, _) in enumerate(STEPS)}


def _route_interval(query):
    """start/end (ISO 8601 with offset) and an optional IANA timeZone from the query string: half-open, at most 366 days."""
    try:
        start, end = parse_stamp(query.get('start', [''])[0]), parse_stamp(query.get('end', [''])[0])
        zone = query.get('timeZone', [TIME_ZONE])[0]
        ZoneInfo(zone)
    except (ValueError, KeyError, IndexError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    if not start.tzinfo or not end.tzinfo or not timedelta(0) < end - start <= timedelta(days=366):
        raise ControlError('VALIDATION_FAILED', 400)
    return dict(start=stamp(start), end=stamp(end), timeZone=zone)


def stuck_workspaces(app, principal, request):
    """GET /product/funnel/stuck?mode=&step=&start=&end=[&timeZone=] (customers.read): the funnel drill-down. Matured
    workspaces of the interval's cohort that reached the previous step within 14 days of creation but not `step`, where
    'not reached' is known (a proxy exists, or the taxonomy observed the whole window). Oldest first, at most 200."""
    from .intelligence import QueryService
    QueryService.require(principal, 'customers.read')
    QueryService.require(principal, 'metrics.query')
    query = request['query']
    step = (query.get('step') or [''])[0]
    index = STEP_INDEX.get(step)
    if not index:   # unknown, or the anchor, which has no previous step
        raise ControlError('VALIDATION_FAILED', 400)
    interval = _route_interval(query)
    base = dict(mode=request['mode'], step=step, previousStep=STEPS[index - 1][0], interval=interval, limit=STUCK_LIMIT, windowDays=WINDOW_DAYS,
                source='taxonomy' if not STEPS[index][2] else 'taxonomy+transition_proxy')
    if request['mode'] == 'demo':
        data = app.queries.demo_data(principal)
        return dict(base, rows=[], truncated=False, reason='demo_not_simulated', _dataState='unavailable',
                    _receiptIds=[data['receipt']['id']] if data.get('receipt') else [])
    QueryService.require(principal, 'workspaces.read')
    service = app.queries
    as_of = stamp(_now(service))
    found = _run(service, 'activation_funnel.stuck', lambda q, rollups: _stuck_sql(q, rollups, interval, as_of, index), limit=STUCK_LIMIT + 1)
    if found is None:
        return dict(base, rows=[], truncated=False, reason='source_not_configured', _dataState='unavailable', _receiptIds=[])
    ids = [row['wid'] for row in found[:STUCK_LIMIT]]
    details = {}
    if ids:
        q = Q()
        sql = ('SELECT w.id, w.name, w.plan, w.status FROM rafii_control.business_workspaces w'
               f' WHERE w.id = ANY({q(ids)}::text[]) ORDER BY w.id LIMIT {q(LIMIT)}')
        details = {row['id']: row for row in execute(service, MetricStatement('activation_funnel.stuck_names', sql), q.params, LIMIT) or []}
    rows = [dict(workspaceId=row['wid'], name=details.get(row['wid'], {}).get('name'), plan=details.get(row['wid'], {}).get('plan'),
                 status=details.get(row['wid'], {}).get('status'), createdAt=_iso(row.get('started'))) for row in found[:STUCK_LIMIT]]
    # A proxy is a lower bound, so a workspace listed under a proxy step may have reached it unobserved.
    proxied = bool(STEPS[index][2] or STEPS[index - 1][2])
    return dict(base, rows=rows, truncated=len(found) > STUCK_LIMIT, _dataState='partial' if proxied else 'measured', _receiptIds=[])


# ---- registration -----------------------------------------------------------------------------------------------------

METRICS =('activation_funnel', 'time_to_value', 'feature_adoption', 'retention_weekly', 'time_back', 'retention_correlations')
live_metrics.register(specs={'time_back': TIME_BACK},
                      custom={'activation_funnel': {'rows': _funnel_rows}, 'time_to_value': {'rows': _ttv_rows}, 'feature_adoption': {'rows': _adoption_rows},
                              'retention_weekly': {'rows': _retention_rows, 'previous': None}, 'retention_correlations': {'rows': _correlation_rows, 'previous': None}},
                      sources={metric_id: 'database' for metric_id in METRICS})
demo_metrics.register({'activation_funnel': _demo_funnel, 'time_to_value': demo_metrics.not_simulated, 'feature_adoption': demo_metrics.not_simulated,
                       'retention_weekly': demo_metrics.not_simulated, 'time_back': demo_metrics.not_simulated, 'retention_correlations': _demo_not_simulated})
founder_cron.register_stage('product_rollups', rollup_stage)
http.register_route('GET', r'/product/funnel/stuck', 'customers.read', 'founder_metrics_product', 'stuck_workspaces')
