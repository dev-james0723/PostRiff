"""Founder reliability: Rafii agent observability summary (P0.7). Read-only and content-free.

Route (registered at import, rafii_control.slices): GET /reliability/agent?window=1h|24h|7d (default 24h) with capability
control.read. The Control boundary already enforces the founder session (AAL2), Origin, CSRF rules and the request budget
before this handler runs; nothing here weakens or repeats them. Demo mode is not simulated (no fixture numbers).

Every number comes from the restricted reader role, with fixed parameterised SQL over column-allowlisted projections and a
half-open window [start, end):
- agent: rafii_control.business_agent_metrics (migration 110) — turns by path and status with p50/p95 end-to-end latency,
  fallbacks, tool calls and error rates, authorization decisions (legacy role checks today; CF-2 shadow/enforce once lane B1
  emits them), approval waits, provider authorization failures, retries, recoveries, completion accuracy (verified vs
  unverified), GenUI handoff and per-turn cost.
- providerCalls: rafii_control.business_ai_calls (064, the existing usage ledger of provider attempts) — cost by feature and
  workload (known amounts only; unknown stays unknown), failures, 401/403 refusals and attempts after the first.
- runs: rafii_control.business_agent_runs (054) — durable run outcomes by kind (agent / task / voice).
- genui: rafii_control.business_genui_artifacts / business_genui_attempts (110 over 102) — validation outcomes, repairs and
  retries. The existing genui.validation_rejected log line is not duplicated.
Each section reports its own dataState: measured | partial (group limit exceeded; totals withheld) | not_instrumented (installed, nothing in the window) | source_not_configured
(the projection is not installed yet) | unavailable. Agent metrics carry no workspace id, so internal or test traffic cannot be
excluded there (like request metrics); providerCalls, runs and genui exclude internal/test/demo workspaces.
"""
from datetime import datetime, timedelta, timezone

from . import http
from .live_metrics import MISSING_SOURCE, excluded, interval_clause, number
from .store import MetricStatement

# Must equal postriff_phase2.agent_metrics.BOUNDS_MS (the writer) and migration 110's comment.
BOUNDS_MS = (50, 100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000, 15000, 20000, 30000, 45000, 60000, 120000, 300000, 900000, 3600000)
WINDOWS = {'1h': 1, '24h': 24, '7d': 168}
METRICS_VIEW = 'rafii_control.business_agent_metrics'
LIMIT = 1000
TOP = 10

AGENT_SQL = ('WITH w AS (SELECT m.metric, m.label, m."eventCount", m."valueSum", m."valueBuckets" FROM ' + METRICS_VIEW + ' m WHERE '
             + interval_clause('m.minute') + '), '
             't AS (SELECT metric, label, sum("eventCount")::bigint AS events, sum("valueSum")::double precision AS total FROM w GROUP BY metric, label), '
             'b AS (SELECT x.metric, x.label, array_agg(x.s ORDER BY x.i) AS buckets FROM (SELECT w.metric, w.label, u.i, sum(u.v)::bigint AS s '
             'FROM w CROSS JOIN LATERAL unnest(w."valueBuckets") WITH ORDINALITY AS u(v, i) GROUP BY w.metric, w.label, u.i) x GROUP BY x.metric, x.label) '
             'SELECT t.metric, t.label, t.events, t.total, b.buckets FROM t LEFT JOIN b ON b.metric = t.metric AND b.label = t.label '
             'ORDER BY t.events DESC, t.metric, t.label LIMIT ' + str(LIMIT + 1))
COVERAGE_SQL = 'SELECT min(m.minute) AS earliest, max(m.minute) AS latest FROM ' + METRICS_VIEW + ' m'
CALLS_SQL = ('SELECT pc.feature, pc.workload, count(*) AS calls, count(*) FILTER (WHERE pc.status = \'ok\') AS ok, '
             'count(*) FILTER (WHERE pc.status <> \'ok\') AS failed, count(*) FILTER (WHERE pc."httpStatus" IN (401, 403)) AS refused, '
             'count(*) FILTER (WHERE pc."attemptNo" > 1) AS retries, coalesce(sum(pc."costUsdMicro") FILTER (WHERE pc."costUsdMicro" IS NOT NULL), 0)::bigint AS known_usd_micro, '
             'count(*) FILTER (WHERE pc."costUsdMicro" IS NULL) AS unknown_cost '
             'FROM rafii_control.business_ai_calls pc WHERE ' + interval_clause('pc.at') + ' AND ' + excluded('pc."workspaceId"')
             + ' GROUP BY pc.feature, pc.workload ORDER BY calls DESC LIMIT 201')
RUNS_SQL = ('SELECT r."idempotencyPrefix" AS kind, r.status, count(*) AS runs, '
            'percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM r."updatedAt" - r."createdAt")) AS p50_seconds, '
            'percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM r."updatedAt" - r."createdAt")) AS p95_seconds '
            'FROM rafii_control.business_agent_runs r WHERE ' + interval_clause('r."createdAt"') + " AND r.\"idempotencyPrefix\" IN ('agent', 'task', 'voice') AND "
            + excluded('r."workspaceId"') + ' GROUP BY r."idempotencyPrefix", r.status ORDER BY runs DESC LIMIT 101')
GENUI_ARTIFACTS_SQL = ('SELECT a.surface, a."validationState" AS validation, a."generationState" AS generation, a."reasonCode" AS reason, count(*) AS artifacts '
                       'FROM rafii_control.business_genui_artifacts a WHERE ' + interval_clause('a."createdAt"') + ' AND ' + excluded('a."workspaceId"')
                       + ' GROUP BY 1, 2, 3, 4 ORDER BY artifacts DESC LIMIT 201')
GENUI_ATTEMPTS_SQL = ('SELECT t.kind, t.state, t."reasonCode" AS reason, count(*) AS attempts, count(*) FILTER (WHERE t."providerAttempts" > 1) AS provider_retries '
                      'FROM rafii_control.business_genui_attempts t WHERE ' + interval_clause('t."createdAt"') + ' AND ' + excluded('t."workspaceId"')
                      + ' GROUP BY 1, 2, 3 ORDER BY attempts DESC LIMIT 201')

# One sentinel group detects truncation without loading an unbounded result. Never
# derive totals or rates from the most frequent groups alone: rare failures matter.
GROUP_LIMITS = {AGENT_SQL: LIMIT, CALLS_SQL: 200, RUNS_SQL: 100, GENUI_ARTIFACTS_SQL: 200, GENUI_ATTEMPTS_SQL: 200}


class _SourceTruncated(Exception):
    def __init__(self, limit):
        self.limit = limit


def percentile(buckets, q):
    """(milliseconds, open_ended) for quantile q of a bucket histogram (linear interpolation inside the bucket holding the rank;
    the open-ended last bucket reports its lower bound). Never an average."""
    counts = [max(0, int(number(value) or 0)) for value in buckets or []]
    total = sum(counts)
    if total <= 0:
        return None, False
    rank, cumulative = q * total, 0
    for index, count in enumerate(counts):
        if count and cumulative + count >= rank:
            if index >= len(BOUNDS_MS):
                return float(BOUNDS_MS[-1]), True
            lower = float(BOUNDS_MS[index - 1]) if index else 0.0
            return round(lower + (BOUNDS_MS[index] - lower) * (rank - cumulative) / count, 1), False
        cumulative += count
    return float(BOUNDS_MS[-1]), True


def _sum_buckets(rows):
    total = [0] * (len(BOUNDS_MS) + 1)
    for row in rows:
        for index, value in enumerate((row.get('buckets') or [])[:len(total)]):
            total[index] += max(0, int(number(value) or 0))
    return total


def _latency(rows):
    buckets = _sum_buckets(rows)
    p50, open50 = percentile(buckets, 0.5)
    p95, open95 = percentile(buckets, 0.95)
    return {'p50Ms': p50, 'p95Ms': p95, 'openEnded': open50 or open95, 'samples': sum(buckets)}


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


def _split(label, parts):
    pieces = str(label or '').split(':')
    return (pieces + ['other'] * parts)[:parts]


def _events(row):
    return int(number(row.get('events')) or 0)


def _read(queries, sql, params):
    """Rows, or None when the projection is not installed (source_not_configured)."""
    try:
        limit = GROUP_LIMITS.get(sql, LIMIT)
        rows = queries.store.metric_rows(MetricStatement('agent_observability', sql), params, limit + 1)
        if len(rows) > limit:
            raise _SourceTruncated(limit)
        return rows
    except MISSING_SOURCE:
        return None


def _state(rows):
    return 'source_not_configured' if rows is None else ('measured' if rows else 'not_instrumented')


def _section(reader):
    try:
        return reader()
    except _SourceTruncated as error:
        return {'dataState': 'partial', 'reason': 'source_truncated', 'groupLimit': error.limit,
                'totalsAvailable': False}
    except Exception as error:  # noqa: BLE001 — one unavailable source never hides the others; the class name only
        return {'dataState': 'unavailable', 'reason': 'source_error', 'errorClass': type(error).__name__}


def agent_section(rows, coverage=None):
    if rows is None:
        return {'dataState': 'source_not_configured', 'source': METRICS_VIEW}
    by = {}
    for row in rows:
        by.setdefault(row.get('metric'), []).append(row)
    turns = {}
    for row in by.get('agent.turn', []):
        path, status = _split(row.get('label'), 2)
        entry = turns.setdefault(path, {'rows': [], 'statuses': {}})
        entry['rows'].append(row)
        entry['statuses'][status] = entry['statuses'].get(status, 0) + _events(row)
    turn_rows = by.get('agent.turn', [])
    completed = sum(_events(r) for r in turn_rows if _split(r.get('label'), 2)[1] == 'completed')
    failed = sum(_events(r) for r in turn_rows if _split(r.get('label'), 2)[1] in ('failed', 'error'))
    tools = {}
    for row in by.get('agent.tool', []):
        tool, status = _split(row.get('label'), 2)
        entry = tools.setdefault(tool, {'calls': 0, 'verified': 0, 'unverified': 0, 'failed': 0, 'blocked': 0, 'rows': []})
        entry['calls'] += _events(row)
        if status in entry:
            entry[status] += _events(row)
        entry['rows'].append(row)
    tool_calls = sum(t['calls'] for t in tools.values())
    tool_errors = sum(t['failed'] + t['unverified'] for t in tools.values())
    outcome = {label: sum(_events(r) for r in by.get('agent.outcome', []) if r.get('label') == label)
               for label in ('verified', 'unverified', 'failed', 'cancelled', 'pending_approval', 'no_change')}
    changes = {label: sum(_events(r) for r in by.get('agent.change', []) if r.get('label') == label) for label in ('verified', 'unverified')}
    authz = [dict(zip(('mode', 'outcome', 'reason'), _split(r.get('label'), 3)), count=_events(r)) for r in by.get('agent.authz', [])]
    denials = [a for a in authz if a['outcome'] == 'deny']
    approvals = {}
    for row in by.get('agent.approval', []):
        surface, result = _split(row.get('label'), 2)
        approvals.setdefault(surface, {'outcomes': {}, 'rows': []})
        approvals[surface]['outcomes'][result] = approvals[surface]['outcomes'].get(result, 0) + _events(row)
        approvals[surface]['rows'].append(row)
    recoveries = {}
    for row in by.get('agent.recovery', []):
        kind, result = _split(row.get('label'), 2)
        recoveries.setdefault(kind, {})[result] = recoveries.setdefault(kind, {}).get(result, 0) + _events(row)
    cost_rows = by.get('agent.turn.cost', [])

    def top(metric, keys):
        return [dict(zip(keys, _split(r.get('label'), len(keys))), count=_events(r)) for r in sorted(by.get(metric, []), key=_events, reverse=True)[:TOP]]

    return {
        'dataState': 'measured' if rows else 'not_instrumented', 'source': METRICS_VIEW,
        'collectingSince': (coverage or {}).get('earliest'), 'latestMinute': (coverage or {}).get('latest'),
        'turns': {'total': sum(_events(r) for r in turn_rows), 'completed': completed, 'failedOrError': failed,
                  'successRate': _rate(completed, completed + failed), 'latency': _latency(turn_rows),
                  'byPath': [{'path': path, 'statuses': entry['statuses'], 'latency': _latency(entry['rows'])} for path, entry in sorted(turns.items())],
                  'fallbacks': top('agent.turn.fallback', ('reason',)), 'closedOutsideTurn': top('agent.run.closed', ('path', 'status'))},
        'tools': {'calls': tool_calls, 'errors': tool_errors, 'errorRate': _rate(tool_errors, tool_calls),
                  'blocked': sum(t['blocked'] for t in tools.values()), 'latency': _latency(by.get('agent.tool', [])),
                  'mostFailing': [{'tool': name, **{k: v for k, v in entry.items() if k != 'rows'}, 'errorRate': _rate(entry['failed'] + entry['unverified'], entry['calls'])}
                                  for name, entry in sorted(tools.items(), key=lambda item: item[1]['failed'] + item[1]['unverified'], reverse=True)[:TOP]
                                  if entry['failed'] + entry['unverified']],
                  'errorCodes': top('agent.tool.error', ('tool', 'code'))},
        'permissions': {'decisions': sum(a['count'] for a in authz), 'denials': sum(a['count'] for a in denials),
                        'shadowWouldDeny': sum(a['count'] for a in denials if a['mode'] == 'shadow'),
                        'byReason': sorted(denials, key=lambda a: a['count'], reverse=True)[:TOP]},
        'approvals': {'decided': sum(sum(v['outcomes'].values()) for v in approvals.values()),
                      'bySurface': [{'surface': surface, 'outcomes': value['outcomes'], 'wait': _latency(value['rows'])} for surface, value in sorted(approvals.items())]},
        'providerAuthorization': {'failures': sum(_events(r) for r in by.get('agent.provider_auth', [])), 'byProvider': top('agent.provider_auth', ('provider', 'reason'))},
        'retries': {'total': sum(_events(r) for r in by.get('agent.retry', [])), 'byKind': top('agent.retry', ('kind',))},
        'recoveries': [{'kind': kind, 'results': results,
                        'successRate': _rate(results.get('recovered', 0) + results.get('delivered', 0) + results.get('closed', 0), sum(results.values()))}
                       for kind, results in sorted(recoveries.items())],
        'completionAccuracy': {'outcomes': outcome, 'verifiedShare': _rate(outcome['verified'], outcome['verified'] + outcome['unverified']),
                               'changes': changes, 'changesVerifiedShare': _rate(changes['verified'], changes['verified'] + changes['unverified'])},
        'cost': {'byPath': [{'path': r.get('label'), 'turns': _events(r), 'usdMicro': int(number(r.get('total')) or 0)}
                            for r in cost_rows if ':' not in str(r.get('label'))],
                 'unknownCostTurns': sum(_events(r) for r in cost_rows if str(r.get('label')).endswith(':unknown'))},
        'genuiHandoff': top('agent.genui', ('state',)),
        'tasks': top('agent.task', ('event', 'state')),
    }


def calls_section(rows):
    if rows is None:
        return {'dataState': 'source_not_configured', 'source': 'rafii_control.business_ai_calls'}
    items = [{'feature': r.get('feature'), 'workload': r.get('workload'), **{k: int(number(r.get(k)) or 0) for k in ('calls', 'ok', 'failed', 'refused', 'retries', 'unknown_cost')},
              'knownUsdMicro': int(number(r.get('known_usd_micro')) or 0)} for r in rows]
    calls = sum(i['calls'] for i in items)
    return {'dataState': _state(rows), 'source': 'rafii_control.business_ai_calls', 'calls': calls, 'failureRate': _rate(sum(i['failed'] for i in items), calls),
            'authorizationRefusals': sum(i['refused'] for i in items), 'retries': sum(i['retries'] for i in items),
            'knownUsdMicro': sum(i['knownUsdMicro'] for i in items), 'unknownCostCalls': sum(i['unknown_cost'] for i in items),
            'byFeature': [{**{k: v for k, v in i.items() if k != 'unknown_cost'}, 'unknownCostCalls': i['unknown_cost']} for i in items[:50]]}


def runs_section(rows):
    if rows is None:
        return {'dataState': 'source_not_configured', 'source': 'rafii_control.business_agent_runs'}
    kinds = {}
    for r in rows:
        entry = kinds.setdefault(r.get('kind'), {'kind': r.get('kind'), 'statuses': {}, 'p50Seconds': None, 'p95Seconds': None})
        entry['statuses'][r.get('status')] = int(number(r.get('runs')) or 0)
        if r.get('status') == 'completed':
            entry['p50Seconds'] = _seconds(r.get('p50_seconds'))
            entry['p95Seconds'] = _seconds(r.get('p95_seconds'))
    for entry in kinds.values():
        done, failed = entry['statuses'].get('completed', 0), entry['statuses'].get('failed', 0)
        entry['successRate'] = _rate(done, done + failed)
    return {'dataState': _state(rows), 'source': 'rafii_control.business_agent_runs', 'byKind': sorted(kinds.values(), key=lambda e: str(e['kind']))}


def _seconds(value):
    value = number(value)
    return round(float(value), 1) if isinstance(value, (int, float)) else None


def genui_section(artifacts, attempts):
    if artifacts is None and attempts is None:
        return {'dataState': 'source_not_configured', 'source': 'rafii_control.business_genui_artifacts'}
    out = {'dataState': 'measured' if (artifacts or attempts) else 'not_instrumented'}
    if artifacts is not None:
        validation = {}
        for r in artifacts:
            validation[r.get('validation')] = validation.get(r.get('validation'), 0) + int(number(r.get('artifacts')) or 0)
        accepted, rejected = validation.get('accepted', 0), validation.get('rejected', 0)
        out['artifacts'] = {'validation': validation, 'acceptedShare': _rate(accepted, accepted + rejected),
                            'rejectionReasons': sorted(({'reason': r.get('reason'), 'count': int(number(r.get('artifacts')) or 0)} for r in artifacts
                                                        if r.get('validation') == 'rejected' and r.get('reason')), key=lambda x: x['count'], reverse=True)[:TOP]}
    if attempts is not None:
        kinds = {}
        for r in attempts:
            entry = kinds.setdefault(r.get('kind'), {'kind': r.get('kind'), 'states': {}, 'providerRetries': 0})
            entry['states'][r.get('state')] = entry['states'].get(r.get('state'), 0) + int(number(r.get('attempts')) or 0)
            entry['providerRetries'] += int(number(r.get('provider_retries')) or 0)
        for entry in kinds.values():
            entry['readyShare'] = _rate(entry['states'].get('ready', 0), sum(entry['states'].values()))
        out['attempts'] = sorted(kinds.values(), key=lambda e: str(e['kind']))
    return out


def window_of(query):
    value = (query.get('window') or ['24h'])[0]
    if value not in WINDOWS:
        from .auth import ControlError
        raise ControlError('VALIDATION_FAILED', 400)
    return value


def summary(app, principal, request):
    """GET /reliability/agent (control.read). Read-only; content-free; one section per source."""
    window = window_of(request.get('query') or {})
    end = datetime.fromtimestamp(float(request['now']), tz=timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    start = end - timedelta(hours=WINDOWS[window])
    interval = {'start': start.isoformat().replace('+00:00', 'Z'), 'end': end.isoformat().replace('+00:00', 'Z'), 'window': window}
    if request.get('mode') == 'demo':
        return {'mode': 'demo', 'interval': interval, 'sections': {}, 'reason': 'demo_not_simulated', '_dataState': 'not_applicable'}
    queries = app.queries
    params = (start, end)

    def agent():
        rows = _read(queries, AGENT_SQL, params)
        coverage = (_read(queries, COVERAGE_SQL, ()) or [{}])[0] if rows is not None else None
        return agent_section(rows, coverage)

    sections = {
        'agent': _section(agent),
        'providerCalls': _section(lambda: calls_section(_read(queries, CALLS_SQL, params))),
        'runs': _section(lambda: runs_section(_read(queries, RUNS_SQL, params))),
        'genui': _section(lambda: genui_section(_read(queries, GENUI_ARTIFACTS_SQL, params), _read(queries, GENUI_ATTEMPTS_SQL, params))),
    }
    states = [s.get('dataState') for s in sections.values()]
    overall = 'measured' if all(s == 'measured' for s in states) else ('unavailable' if not any(s in ('measured', 'not_instrumented', 'partial') for s in states) else 'partial')
    return {'mode': 'live', 'interval': interval, 'sections': sections, 'contentFree': True,
            'limitations': ['Agent metrics carry no workspace id, so internal and test traffic is included there.',
                            'Agent metrics are per-minute aggregates flushed from each server process; a crashed or frozen process can lose its last minutes.',
                            'Permission decisions cover today\'s role, voice, tenant and scope checks; CF-2 shadow and enforce decisions appear once that lane emits them.'],
            '_dataState': overall}


http.register_route('GET', r'/reliability/agent', 'control.read', 'founder_agent_observability', 'summary')
