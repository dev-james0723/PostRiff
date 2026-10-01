"""Customer risk flags (CONTRACTS §8.C; PRD §7.4, §5.3 Customers, §10.2 P1-3): observed, versioned rules evaluated
server-side. Never a black-box health score.

Each flag is one explainable rule (RULES) with its trigger, evidence and since; flags sit side by side and are never
summed into a score. 'At-risk' is the one inferred flag (basis='hypothesis'): Inactive ∧ (Payment risk ∨ Connection
risk), and it names the flags behind it.

Route GET /customers/risk?mode=demo|live&view=<saved view> (customers.read; Live also needs workspaces.read) returns the
workspaces in one saved view, bounded to 200, each with every flag it carries. Live reads the reader-role projections
(053/054/065, and slice 8.D's 066 connection health when it exists) with fixed SQL and bound parameters; a rule whose
projection is missing is 'unavailable' with its reason and flags nobody, never a zero. Demo evaluates the same rules over
the founder's Demo dataset (Connection risk is not simulated there). Workspaces classified internal/test/demo are excluded.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import http, live_metrics
from .auth import ControlError
from .live_metrics import TIME_ZONE, excluded, execute, number, parse_stamp, settled_elsewhere, stamp
from .store import MetricStatement

VERSION = 'v1'
ROW_LIMIT = 200
SQL_LIMIT = 1001
INACTIVE_DAYS = 30
LOOKBACK_DAYS = 400          # inactivity: how far back the last activity is looked up
COST_DAYS = 30
EXPIRY_DAYS = 7
QUOTA_SHARE = 0.8
P_HIGH_VALUE, MIN_CASH_POPULATION = 0.9, 5
P_HIGH_COST, MIN_COST_POPULATION = 0.95, 10
RECONNECT_STATES = ('token_expired', 'reauthorization_required', 'scope_missing')

RULES = (
    dict(id='high_value', label='High value', basis='observed', source='M03/M06',
         trigger='Plan is the highest-priced of two or more plans in use, or cash collected this month is at or above the 90th percentile of workspaces with cash (at least 5).'),
    dict(id='high_ai_cost', label='High AI cost', basis='observed', source='M10/M18',
         trigger='Actual AI cost in the last 30 days is at or above the 95th percentile of workspaces with cost (at least 10), or above the cash it paid in the same 30 days.'),
    dict(id='quota_near_limit', label='Quota near limit', basis='observed', source='M20',
         trigger='The workspace AI budget for its current window is at least 80% used (spent plus reserved over the stop amount). Credit wallets are not evaluated while credits are off.'),
    dict(id='inactive', label='Inactive 30d', basis='observed', source='M21',
         trigger='No completed agent run, product event or publish event in the last 30 days, for a workspace older than 30 days.'),
    dict(id='payment_risk', label='Payment risk', basis='observed', source='M07',
         trigger='Subscription past due or set to cancel at period end, or a failed payment in the last 30 days.'),
    dict(id='connection_risk', label='Connection risk', basis='observed', source='M29',
         trigger='A connection needs reauthorization (token expired, reauthorization required, scope missing) or expires within 7 days; '
                 'until the connection-health projection exists, an unresolved reconnect notification.'),
    dict(id='unknown_cost_holds', label='Unknown cost holds', basis='observed', source='M11',
         trigger='At least one AI usage row whose provider cost is still unknown and not reconciled.'),
    dict(id='at_risk', label='At-risk', basis='hypothesis', source='inferred',
         trigger='Inactive and (Payment risk or Connection risk). A hypothesis to check, not a prediction.'),
)
RULE_IDS = tuple(rule['id'] for rule in RULES)
OBSERVED = RULE_IDS[:-1]
# Saved views (PRD §5.3): High value · High AI cost · Quota ≥80% · Inactive 30d · Payment risk · At-risk, plus the other
# single flags and 'flagged' (every workspace with at least one flag) for the customer table's chips.
VIEWS = {'high_value': 'high_value', 'high_ai_cost': 'high_ai_cost', 'quota_80': 'quota_near_limit', 'inactive_30d': 'inactive', 'payment_risk': 'payment_risk',
         'at_risk': 'at_risk', 'connection_risk': 'connection_risk', 'unknown_cost': 'unknown_cost_holds', 'flagged': None}
# Within one view, the most material workspaces first.
ORDER = {'high_value': ('cashMtdMinor', -1), 'high_ai_cost': ('aiCost30dUsdMicro', -1), 'quota_near_limit': ('usedShare', -1),
         'unknown_cost_holds': ('unknownEstimateUsdMicro', -1)}


class Q:
    """Positional parameters in the order their placeholders appear (every statement here is built left to right)."""
    def __init__(self):
        self.params = []

    def __call__(self, value):
        self.params.append(value)
        return '%s'


def _wid(alias):
    return f'{alias}."workspaceId"'


def _only(q, column, candidates):
    """Restrict a rule to the given workspace ids (phase two); NULL means every workspace."""
    return f'({q(candidates)}::text[] IS NULL OR {column} = ANY({q(candidates)}::text[]))'


def _literal(values):
    """A fixed module literal list for IN (...), never browser input."""
    return '(' + ','.join("'" + value + "'" for value in values) + ')'


def _flag(rule_id, since, **evidence):
    rule = next(item for item in RULES if item['id'] == rule_id)
    return dict(id=rule_id, version=VERSION, label=rule['label'], basis=rule['basis'], trigger=rule['trigger'], since=since,
                evidence={key: value for key, value in evidence.items() if value is not None})


def _iso(value):
    if value is None: return None
    if isinstance(value, datetime): return stamp(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    try: return stamp(parse_stamp(str(value)))
    except ValueError: return None


def _shown(value):
    """A percentile threshold as evidence: interpolation noise rounded away (the comparison itself is unrounded)."""
    value = number(value)
    return None if value is None else round(float(value), 4)


def _merge(found, wid, flag):
    """One flag per rule per workspace: evidence from several statements merges, the earliest since wins."""
    current = found.setdefault(wid, {}).get(flag['id'])
    if current is None:
        found[wid][flag['id']] = flag
        return
    current['evidence'].update(flag['evidence'])
    if flag['since'] and (not current['since'] or flag['since'] < current['since']):
        current['since'] = flag['since']


class Engine:
    def __init__(self):
        self.states = {}   # rule -> {'evaluated': [parts], 'missing': [parts], 'truncated': bool}

    def state(self, rule_id):
        return self.states.setdefault(rule_id, {'evaluated': [], 'missing': [], 'truncated': False})


# ---- Live rules: one statement per source part, each of which may be missing independently -----------------------------

class Live(Engine):
    def __init__(self, service, now):
        super().__init__()
        self.service, self.now = service, now
        local = now.astimezone(ZoneInfo(TIME_ZONE))
        self.month_start = stamp(local.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        self.as_of, self.cost_from, self.inactive_from = stamp(now), stamp(now - timedelta(days=COST_DAYS)), stamp(now - timedelta(days=INACTIVE_DAYS))
        self.lookback, self.expiry = stamp(now - timedelta(days=LOOKBACK_DAYS)), stamp(now + timedelta(days=EXPIRY_DAYS))

    def run(self, rule_id, part, build):
        q = Q()
        rows = execute(self.service, MetricStatement('customer_risk.' + part, build(q)), q.params, SQL_LIMIT)
        state = self.state(rule_id)
        if rows is None:
            state['missing'].append(part)
            return None
        state['evaluated'].append(part)
        state['truncated'] = state['truncated'] or len(rows) >= SQL_LIMIT
        return rows

    def _cash(self, q, since):
        """Funded live top-ups and credit-plan invoice grants in [since, now) (054 views; absent without 021/022)."""
        return ('SELECT p."workspaceId" AS wid, p.currency, p."amountMinor" AS amount, p.at FROM rafii_control.business_payments_v2 p'
                f' WHERE p.status=\'funded\' AND p.livemode AND p."workspaceId" IS NOT NULL AND p.at >= {q(since)}::timestamptz AND p.at < {q(self.as_of)}::timestamptz'
                f' AND {excluded(_wid("p"))}'
                ' UNION ALL SELECT g."workspaceId", g.currency, g."amountMinor", g."recordedAt" FROM rafii_control.business_subscription_grants g'
                f' WHERE g.livemode AND g."workspaceId" IS NOT NULL AND g."recordedAt" >= {q(since)}::timestamptz AND g."recordedAt" < {q(self.as_of)}::timestamptz'
                f' AND {excluded(_wid("g"))}')

    def _cost(self, q):
        return ('SELECT u."workspaceId" AS wid, sum(u."actualUsdMicro") AS cost, min(u.at) AS first_at FROM rafii_control.business_usage_v2 u'
                f' WHERE u.kind=\'settle\' AND u."costState"=\'actual\' AND NOT u."aiUsageExempt" AND u.at >= {q(self.cost_from)}::timestamptz AND u.at < {q(self.as_of)}::timestamptz'
                f' AND {excluded(_wid("u"))} GROUP BY u."workspaceId"')

    def high_value(self, found, candidates):
        for row in self.run('high_value', 'tier', lambda q: (
                'WITH subs AS (SELECT s."workspaceId" AS wid, s.plan, s."amountMinor" AS price, s.currency, s."updatedAt" AS at FROM rafii_control.business_subscriptions_v2 s'
                f' WHERE s.provider<>\'fixture\' AND s.status IN (\'active\',\'past_due\') AND {excluded(_wid("s"))}),'
                ' tiers AS (SELECT max(price) AS top, count(DISTINCT price) AS prices FROM subs WHERE price IS NOT NULL)'
                f' SELECT s.wid, s.at AS since, s.plan, s.price, s.currency FROM subs s, tiers t WHERE t.prices >= 2 AND s.price = t.top AND {_only(q, "s.wid", candidates)}'
                f' ORDER BY s.wid LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('high_value', _iso(row['since']), plan=row.get('plan'), tierPriceMinor=number(row.get('price')), currency=row.get('currency'), highestTier=True))
        for row in self.run('high_value', 'cash', lambda q: (
                f'WITH cash AS (SELECT wid, currency, sum(amount) AS amount, min(at) AS first_at FROM ({self._cash(q, self.month_start)}) x GROUP BY wid, currency),'
                f' stats AS (SELECT currency, percentile_cont({q(P_HIGH_VALUE)}) WITHIN GROUP (ORDER BY amount) AS threshold, count(*) AS n FROM cash GROUP BY currency)'
                ' SELECT c.wid, c.first_at AS since, c.currency, c.amount, s.threshold, s.n FROM cash c JOIN stats s ON s.currency IS NOT DISTINCT FROM c.currency'
                f' WHERE s.n >= {q(MIN_CASH_POPULATION)} AND c.amount >= s.threshold AND {_only(q, "c.wid", candidates)} ORDER BY c.amount DESC, c.wid LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('high_value', _iso(row['since']), cashMtdMinor=number(row.get('amount')), currency=row.get('currency'),
                                            p90CashMtdMinor=_shown(row.get('threshold')), cashPopulation=number(row.get('n'))))

    def high_ai_cost(self, found, candidates):
        for row in self.run('high_ai_cost', 'percentile', lambda q: (
                f'WITH cost AS ({self._cost(q)}), stats AS (SELECT percentile_cont({q(P_HIGH_COST)}) WITHIN GROUP (ORDER BY cost) AS threshold, count(*) AS n FROM cost WHERE cost > 0)'
                f' SELECT c.wid, c.first_at AS since, c.cost, s.threshold, s.n FROM cost c, stats s WHERE s.n >= {q(MIN_COST_POPULATION)} AND c.cost >= s.threshold'
                f' AND {_only(q, "c.wid", candidates)} ORDER BY c.cost DESC, c.wid LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('high_ai_cost', _iso(row['since']), aiCost30dUsdMicro=number(row.get('cost')), p95AiCost30dUsdMicro=_shown(row.get('threshold')),
                                            costPopulation=number(row.get('n'))))
        for row in self.run('high_ai_cost', 'margin', lambda q: (
                f'WITH cost AS ({self._cost(q)}), cash AS (SELECT wid, sum(amount) AS amount FROM ({self._cash(q, self.cost_from)}) x WHERE currency=\'USD\' GROUP BY wid)'
                ' SELECT c.wid, c.first_at AS since, c.cost, cash.amount FROM cost c JOIN cash ON cash.wid=c.wid WHERE c.cost > cash.amount * 10000'
                f' AND {_only(q, "c.wid", candidates)} ORDER BY c.cost DESC, c.wid LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('high_ai_cost', _iso(row['since']), aiCost30dUsdMicro=number(row.get('cost')), cash30dUsdMinor=number(row.get('amount')), negativeMargin=True))

    def quota_near_limit(self, found, candidates):
        for row in self.run('quota_near_limit', 'budget', lambda q: (
                'SELECT substr(b.scope, 11) AS wid, b."windowStart" AS since, b."windowKind" AS window_kind, b."spentUsdMicro"+b."reservedUsdMicro" AS used, b."stopUsdMicro" AS stop'
                ' FROM rafii_control.business_budgets b WHERE b.scope LIKE \'workspace:%%\' AND b."stopUsdMicro" > 0'
                f' AND b."spentUsdMicro"+b."reservedUsdMicro" >= {q(QUOTA_SHARE)} * b."stopUsdMicro"'
                # Only the current window counts: the ledger rolls a budget forward lazily, so last month's spend is not a quota signal.
                f' AND b."windowStart" >= date_trunc(b."windowKind", {q(self.as_of)}::timestamptz AT TIME ZONE \'UTC\') AT TIME ZONE \'UTC\''
                f' AND {excluded("substr(b.scope, 11)")} AND {_only(q, "substr(b.scope, 11)", candidates)}'
                f' ORDER BY (b."spentUsdMicro"+b."reservedUsdMicro")::float8 / b."stopUsdMicro" DESC, b.scope LIMIT {q(SQL_LIMIT)}')) or []:
            used, stop = number(row.get('used')), number(row.get('stop'))
            _merge(found, row['wid'], _flag('quota_near_limit', _iso(row['since']), usedUsdMicro=used, stopUsdMicro=stop, usedShare=used / stop if stop else None,
                                            windowKind=row.get('window_kind'), creditsRule='not_enabled'))

    def inactive(self, found, candidates):
        for row in self.run('inactive', 'activity', lambda q: (
                'WITH ws AS (SELECT s."workspaceId" AS wid, s."createdAt" AS created FROM rafii_control.business_workspace_starts s'
                f' WHERE s."createdAt" < {q(self.inactive_from)}::timestamptz AND {excluded(_wid("s"))} AND {_only(q, _wid("s"), candidates)}),'
                ' activity AS (SELECT r."workspaceId" AS wid, r."createdAt" AS at FROM rafii_control.business_agent_runs r'
                f' WHERE r.status IN (\'completed\',\'applied\') AND r."createdAt" >= {q(self.lookback)}::timestamptz AND r."createdAt" < {q(self.as_of)}::timestamptz'
                ' UNION ALL SELECT n."workspaceId", n."occurredAt" FROM rafii_control.business_notification_events n'
                f' WHERE n."eventType" IN {live_metrics.PUBLISH_EVENTS} AND n."workspaceId" IS NOT NULL AND n."occurredAt" >= {q(self.lookback)}::timestamptz'
                f' AND n."occurredAt" < {q(self.as_of)}::timestamptz'
                ' UNION ALL SELECT p."workspaceId", p."occurredAt" FROM rafii_control.business_product_events p'
                f' WHERE p."workspaceId" IS NOT NULL AND p."occurredAt" >= {q(self.lookback)}::timestamptz AND p."occurredAt" < {q(self.as_of)}::timestamptz),'
                ' seen AS (SELECT a.wid, max(a.at) AS last_at FROM activity a JOIN ws ON ws.wid=a.wid GROUP BY a.wid)'
                f' SELECT ws.wid, ws.created, seen.last_at FROM ws LEFT JOIN seen ON seen.wid=ws.wid WHERE seen.last_at IS NULL OR seen.last_at < {q(self.inactive_from)}::timestamptz'
                f' ORDER BY coalesce(seen.last_at, ws.created), ws.wid LIMIT {q(SQL_LIMIT)}')) or []:
            last = _iso(row.get('last_at'))
            since = last or _iso(row.get('created'))
            _merge(found, row['wid'], _flag('inactive', since, lastActiveAt=last, lastActivityLookbackDays=None if last else LOOKBACK_DAYS,
                                            daysInactive=int((self.now - parse_stamp(since)).total_seconds() // 86400) if since else None))

    def payment_risk(self, found, candidates):
        for row in self.run('payment_risk', 'subscription', lambda q: (
                'SELECT s."workspaceId" AS wid, s."updatedAt" AS since, s.status, s."cancelAtPeriodEnd" AS cancelling FROM rafii_control.business_subscriptions_v2 s'
                ' WHERE s.provider<>\'fixture\' AND (s.status=\'past_due\' OR (s."cancelAtPeriodEnd" AND s.status IN (\'active\',\'past_due\',\'grace\')))'
                f' AND {excluded(_wid("s"))} AND {_only(q, _wid("s"), candidates)} ORDER BY s."updatedAt", s."workspaceId" LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('payment_risk', _iso(row['since']), subscriptionStatus=row.get('status'), cancelAtPeriodEnd=bool(row.get('cancelling'))))
        for row in self.run('payment_risk', 'top_up', lambda q: (
                'SELECT p."workspaceId" AS wid, min(p.at) AS since, count(*) AS failures FROM rafii_control.business_payments_v2 p'
                f' WHERE p.status=\'failed\' AND p."workspaceId" IS NOT NULL AND p.at >= {q(self.cost_from)}::timestamptz AND p.at < {q(self.as_of)}::timestamptz'
                f' AND {excluded(_wid("p"))} AND {_only(q, _wid("p"), candidates)} GROUP BY p."workspaceId" ORDER BY min(p.at), p."workspaceId" LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('payment_risk', _iso(row['since']), failedPayments30d=number(row.get('failures')), paymentKind='top_up'))

    def connection_risk(self, found, candidates):
        health = self.run('connection_risk', 'connection_health', lambda q: (
            'SELECT h."workspaceId" AS wid, min(coalesce(h."expiresAt", h."refreshedAt")) AS since, count(DISTINCT h."connectionId") AS connections,'
            ' array_agg(DISTINCT h."connectionState") AS states, min(h."expiresAt") AS expires FROM rafii_control.business_connection_health h'
            f' WHERE (h."connectionState" IN {_literal(RECONNECT_STATES)} OR (h."expiresAt" IS NOT NULL AND h."expiresAt" < {q(self.expiry)}::timestamptz))'
            f' AND {excluded(_wid("h"))} AND {_only(q, _wid("h"), candidates)} GROUP BY h."workspaceId" ORDER BY 2, 1 LIMIT {q(SQL_LIMIT)}'))
        if health is not None:
            for row in health:
                states = sorted(state for state in (row.get('states') or []) if state in RECONNECT_STATES)
                _merge(found, row['wid'], _flag('connection_risk', _iso(row['since']), connections=number(row.get('connections')), states=states or None,
                                                earliestExpiry=_iso(row.get('expires')), source='connection_health'))
            return
        # Transition source (PRD §7.4) until the 060/066 projection exists: an unresolved channel.reconnect_required event.
        state = self.state('connection_risk')
        state['missing'].remove('connection_health')
        state['fallback'] = 'reconnect_events'
        for row in self.run('connection_risk', 'reconnect_events', lambda q: (
                'SELECT n."workspaceId" AS wid, min(n."occurredAt") AS since, count(*) AS events FROM rafii_control.business_notification_events n'
                ' WHERE n."eventType"=\'channel.reconnect_required\' AND n."resolvedAt" IS NULL AND n."workspaceId" IS NOT NULL'
                f' AND {excluded(_wid("n"))} AND {_only(q, _wid("n"), candidates)} GROUP BY n."workspaceId" ORDER BY 2, 1 LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('connection_risk', _iso(row['since']), openReconnectEvents=number(row.get('events')), source='reconnect_events'))

    def unknown_cost_holds(self, found, candidates):
        for row in self.run('unknown_cost_holds', 'ledger', lambda q: (
                'SELECT u."workspaceId" AS wid, min(u.at) AS since, count(*) AS rows, sum(u."estimatedUsdMicro") AS estimate FROM rafii_control.business_usage_v2 u'
                f' WHERE u."costState"=\'estimated_unknown\' AND NOT u."aiUsageExempt" AND {settled_elsewhere("u")}'
                f' AND {excluded(_wid("u"))} AND {_only(q, _wid("u"), candidates)} GROUP BY u."workspaceId" ORDER BY 2, 1 LIMIT {q(SQL_LIMIT)}')) or []:
            _merge(found, row['wid'], _flag('unknown_cost_holds', _iso(row['since']), unknownRows=number(row.get('rows')), unknownEstimateUsdMicro=number(row.get('estimate'))))

    def workspaces(self, ids):
        q = Q()
        sql = ('SELECT w.id, w.name, w."ownerId", w.plan, w.status, w."createdAt" FROM rafii_control.business_workspaces w'
               f' WHERE w.id = ANY({q(list(ids))}::text[]) ORDER BY w.id LIMIT {q(SQL_LIMIT)}')
        return {row['id']: row for row in execute(self.service, MetricStatement('customer_risk.workspaces', sql), q.params, SQL_LIMIT) or []}


# ---- Demo rules over the founder's Demo dataset -------------------------------------------------------------------------

def _stamp(value):
    try: return parse_stamp(value)
    except (AttributeError, TypeError, ValueError): return None


def _percentile(values, share):
    """percentile_cont over the values (PostgreSQL semantics: linear interpolation between closest ranks)."""
    ordered = sorted(values)
    if not ordered: return None
    position = share * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _keep(wid, candidates):
    return candidates is None or wid in candidates


class Demo(Engine):
    def __init__(self, data, now):
        super().__init__()
        self.data, self.now = data, now
        self.month_start = now.astimezone(ZoneInfo(TIME_ZONE)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self.workspace = {row['id']: row for row in data.get('workspaces', []) if isinstance(row, dict) and row.get('id')}

    def note(self, rule_id, part, missing=False):
        self.state(rule_id)['missing' if missing else 'evaluated'].append(part)

    def _cash(self, since):
        totals = defaultdict(lambda: [0, None])
        for row in self.data.get('payments', []):
            at = _stamp(row.get('at'))
            if row.get('status') == 'funded' and row.get('workspaceId') in self.workspace and at and since <= at < self.now:
                entry = totals[(row['workspaceId'], row.get('currency'))]
                entry[0] += int(row.get('amountMinor') or 0)
                entry[1] = min(entry[1], at) if entry[1] else at
        return totals

    def _cost(self):
        totals = defaultdict(lambda: [0, None])
        since = self.now - timedelta(days=COST_DAYS)
        for row in self.data.get('usage', []):
            at = _stamp(row.get('at'))
            if row.get('kind') != 'settle' or row.get('costState') in ('estimated_unknown', 'released') or row.get('workspaceId') not in self.workspace:
                continue
            if not at or not since <= at < self.now:
                continue
            entry = totals[row['workspaceId']]
            actual = row.get('actualUsdMicro')
            entry[0] += int(actual if actual is not None else (row.get('estimatedUsdMicro') or 0))
            entry[1] = min(entry[1], at) if entry[1] else at
        return totals

    def high_value(self, found, candidates):
        self.note('high_value', 'tier')
        paid = [row for row in self.data.get('subscriptions', []) if row.get('paid', True) and row.get('status') in ('active', 'past_due') and row.get('workspaceId') in self.workspace]
        prices = {row.get('amountMinor') for row in paid if isinstance(row.get('amountMinor'), int)}
        top = max(prices) if len(prices) >= 2 else None
        for row in paid:
            if top is not None and row.get('amountMinor') == top and _keep(row['workspaceId'], candidates):
                _merge(found, row['workspaceId'], _flag('high_value', _iso(row.get('startedAt')), plan=row.get('plan'), tierPriceMinor=top, currency=row.get('currency'), highestTier=True))
        self.note('high_value', 'cash')
        cash = self._cash(self.month_start)
        by_currency = defaultdict(list)
        for (_, currency), (amount, _) in cash.items():
            by_currency[currency].append(amount)
        thresholds = {currency: _percentile(values, P_HIGH_VALUE) for currency, values in by_currency.items()}
        for (wid, currency), (amount, first) in cash.items():
            if len(by_currency[currency]) >= MIN_CASH_POPULATION and amount >= thresholds[currency] and _keep(wid, candidates):
                _merge(found, wid, _flag('high_value', _iso(first), cashMtdMinor=amount, currency=currency, p90CashMtdMinor=_shown(thresholds[currency]), cashPopulation=len(by_currency[currency])))

    def high_ai_cost(self, found, candidates):
        self.note('high_ai_cost', 'percentile')
        cost = self._cost()
        values = [amount for amount, _ in cost.values() if amount > 0]
        threshold = _percentile(values, P_HIGH_COST)
        for wid, (amount, first) in cost.items():
            if len(values) >= MIN_COST_POPULATION and amount >= threshold and _keep(wid, candidates):
                _merge(found, wid, _flag('high_ai_cost', _iso(first), aiCost30dUsdMicro=amount, p95AiCost30dUsdMicro=_shown(threshold), costPopulation=len(values)))
        self.note('high_ai_cost', 'margin')
        cash = {wid: amount for (wid, currency), (amount, _) in self._cash(self.now - timedelta(days=COST_DAYS)).items() if currency == 'USD'}
        for wid, (amount, first) in cost.items():
            if wid in cash and amount > cash[wid] * 10000 and _keep(wid, candidates):
                _merge(found, wid, _flag('high_ai_cost', _iso(first), aiCost30dUsdMicro=amount, cash30dUsdMinor=cash[wid], negativeMargin=True))

    def quota_near_limit(self, found, candidates):
        # The Demo simulates monthly credit quotas rather than provider budgets: used >= 80% of the quota.
        self.note('quota_near_limit', 'credits')
        for wid, row in self.workspace.items():
            quota, used = row.get('creditsQuota'), row.get('creditsUsed')
            if isinstance(quota, int) and quota > 0 and isinstance(used, int) and used >= QUOTA_SHARE * quota and _keep(wid, candidates):
                _merge(found, wid, _flag('quota_near_limit', _iso(self.month_start), creditsUsed=used, creditsQuota=quota, usedShare=used / quota, source='demo_credits'))

    def inactive(self, found, candidates):
        self.note('inactive', 'activity')
        last = {}
        for collection in ('usage', 'activity'):
            for row in self.data.get(collection, []):
                at = _stamp(row.get('at'))
                wid = row.get('workspaceId')
                if wid and at and at < self.now and (wid not in last or at > last[wid]):
                    last[wid] = at
        cutoff = self.now - timedelta(days=INACTIVE_DAYS)
        for wid, row in self.workspace.items():
            created, seen = _stamp(row.get('createdAt')), last.get(wid)
            if created and created < cutoff and (seen is None or seen < cutoff) and _keep(wid, candidates):
                since = seen or created
                _merge(found, wid, _flag('inactive', _iso(since), lastActiveAt=_iso(seen), daysInactive=int((self.now - since).total_seconds() // 86400)))

    def payment_risk(self, found, candidates):
        self.note('payment_risk', 'subscription')
        for row in self.data.get('subscriptions', []):
            wid = row.get('workspaceId')
            if wid in self.workspace and (row.get('status') == 'past_due' or row.get('cancelAtPeriodEnd')) and _keep(wid, candidates):
                _merge(found, wid, _flag('payment_risk', _iso(row.get('startedAt')), subscriptionStatus=row.get('status'), cancelAtPeriodEnd=bool(row.get('cancelAtPeriodEnd'))))
        self.note('payment_risk', 'payments')
        since = self.now - timedelta(days=COST_DAYS)
        failures = defaultdict(list)
        for row in self.data.get('payments', []):
            at = _stamp(row.get('at'))
            if row.get('status') == 'failed' and row.get('workspaceId') in self.workspace and at and since <= at < self.now:
                failures[row['workspaceId']].append(at)
        for wid, stamps in failures.items():
            if _keep(wid, candidates):
                _merge(found, wid, _flag('payment_risk', _iso(min(stamps)), failedPayments30d=len(stamps), paymentKind='subscription_invoice'))

    def connection_risk(self, found, candidates):
        self.note('connection_risk', 'demo_not_simulated', missing=True)

    def unknown_cost_holds(self, found, candidates):
        self.note('unknown_cost_holds', 'usage')
        holds = defaultdict(list)
        for row in self.data.get('usage', []):
            if row.get('costState') == 'estimated_unknown' and row.get('workspaceId') in self.workspace:
                holds[row['workspaceId']].append(row)
        for wid, rows in holds.items():
            if _keep(wid, candidates):
                stamps = [at for at in (_stamp(row.get('at')) for row in rows) if at]
                _merge(found, wid, _flag('unknown_cost_holds', _iso(min(stamps)) if stamps else None, unknownRows=len(rows),
                                         unknownEstimateUsdMicro=sum(int(row.get('estimatedUsdMicro') or 0) for row in rows)))

    def workspaces(self, ids):
        wanted = set(ids)
        return {wid: dict(id=wid, name=row.get('name'), ownerId=row.get('ownerId'), plan=row.get('plan'), status=row.get('status'), createdAt=row.get('createdAt'))
                for wid, row in self.workspace.items() if wid in wanted}


# ---- evaluation ---------------------------------------------------------------------------------------------------------

def _at_risk(found):
    """The inferred flag: Inactive ∧ (Payment risk ∨ Connection risk), naming the flags behind it."""
    for flags in found.values():
        if 'inactive' in flags and ('payment_risk' in flags or 'connection_risk' in flags):
            parts = [flags[name] for name in ('inactive', 'payment_risk', 'connection_risk') if name in flags]
            stamps = [part['since'] for part in parts if part['since']]
            flags['at_risk'] = _flag('at_risk', max(stamps) if stamps else None, because=[part['id'] for part in parts])


def evaluate(engine, view):
    """Phase one: the workspaces in `view`. A single-flag view evaluates only its rule over every workspace; 'at_risk'
    evaluates payment and connection risk, then inactivity for exactly those candidates (so a long inactive list can
    never hide one); 'flagged' evaluates every observed rule. Returns (selected ids, flags by workspace)."""
    rule = VIEWS[view]
    members = {}
    if rule is None:
        for name in OBSERVED:
            getattr(engine, name)(members, None)
    elif rule == 'at_risk':
        engine.payment_risk(members, None)
        engine.connection_risk(members, None)
        engine.inactive(members, sorted(members))
    else:
        getattr(engine, rule)(members, None)
    _at_risk(members)
    selected = [wid for wid, flags in members.items() if flags and (rule is None or rule in flags)]
    return selected, members


def _order(selected, members, rule):
    def key(wid):
        flags = members[wid]
        if rule is None:
            return (-len(flags), wid)
        flag = flags[rule]
        field, sign = ORDER.get(rule, (None, 1))
        value = flag['evidence'].get(field) if field else None
        return (0 if isinstance(value, (int, float)) else 1, -value if isinstance(value, (int, float)) else 0, flag.get('since') or '', wid)
    return sorted(selected, key=key)


def _rule_states(engine, mode):
    out = []
    for rule in RULES:
        entry = {key: rule[key] for key in ('id', 'label', 'basis', 'trigger', 'source')}
        entry['version'] = VERSION
        if rule['id'] == 'at_risk':
            parts = [engine.states.get(name) for name in ('inactive', 'payment_risk', 'connection_risk')]
            entry['state'] = ('not_evaluated' if any(part is None for part in parts) else 'unavailable' if not parts[0]['evaluated'] or not (parts[1]['evaluated'] or parts[2]['evaluated'])
                              else 'partial' if any(part['missing'] or part['truncated'] for part in parts) else 'measured')
        else:
            state = engine.states.get(rule['id'])
            entry['state'] = 'not_evaluated' if state is None else 'unavailable' if not state['evaluated'] else 'partial' if state['missing'] or state['truncated'] else 'measured'
            if state and state['missing']: entry['reason'] = 'demo_not_simulated' if mode == 'demo' else 'source_not_configured'
            if state and state.get('fallback'): entry['fallback'] = state['fallback']
            if state and state['truncated']: entry['truncated'] = True
        out.append(entry)
    return out


def customers_risk(app, principal, request):
    """GET /customers/risk?mode=&view= — the saved view's workspaces (at most 200) with every flag each carries."""
    from .intelligence import QueryService
    QueryService.require(principal, 'customers.read')
    mode = request['mode']
    view = (request['query'].get('view') or ['flagged'])[0]
    if view not in VIEWS: raise ControlError('VALIDATION_FAILED', 400)
    service = app.queries
    if mode == 'demo':
        data = service.demo_data(principal)
        now = parse_stamp(data['asOf']) + timedelta(seconds=1)   # Demo records stamped at asOf belong to the snapshot
        engine, receipts = Demo(data, now), [data['receipt']['id']] if data.get('receipt') else []
    else:
        QueryService.require(principal, 'workspaces.read')
        now = service.clock()
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        engine, receipts = Live(service, now), []
    selected, members = evaluate(engine, view)
    ordered = _order(selected, members, VIEWS[view])
    shown = ordered[:ROW_LIMIT]
    # Phase two: every rule phase one did not evaluate, restricted to the shown workspaces, so each row carries all its chips.
    complete = {wid: {name: flag for name, flag in members[wid].items() if name != 'at_risk'} for wid in shown}
    if shown:
        for name in OBSERVED:
            if name not in engine.states:
                getattr(engine, name)(complete, list(shown))
    _at_risk(complete)
    details = engine.workspaces(shown) if shown else {}
    rows = []
    for wid in shown:
        info = details.get(wid, {})
        flags = [complete[wid][rule_id] for rule_id in RULE_IDS if rule_id in complete[wid]]
        rows.append(dict(workspaceId=wid, name=info.get('name'), ownerId=info.get('ownerId'), plan=info.get('plan'), status=info.get('status'),
                         createdAt=_iso(info.get('createdAt')), flags=flags, flagCount=len(flags)))
    rules = _rule_states(engine, mode)
    target = VIEWS[view]
    view_states = [entry['state'] for entry in rules if (target is None and entry['id'] != 'at_risk') or entry['id'] == target]
    data_state = ('synthetic' if mode == 'demo' else 'unavailable' if view_states and all(state == 'unavailable' for state in view_states)
                  else 'measured' if all(state == 'measured' for state in view_states) else 'partial')
    return dict(mode=mode, view=view, asOf=stamp(now), timeZone=TIME_ZONE, rulesVersion=VERSION, rules=rules, rows=rows, total=len(ordered),
                truncated=len(ordered) > ROW_LIMIT, limit=ROW_LIMIT, basis='observed_rules', _dataState=data_state, _receiptIds=receipts)


http.register_route('GET', r'/customers/risk', 'customers.read', 'founder_risk', 'customers_risk')
