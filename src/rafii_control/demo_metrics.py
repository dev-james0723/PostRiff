"""Demo parity for the activated v1 founder metrics, computed from the founder's Demo dataset.

Same metric ids, definitions, half-open intervals, timezone handling and row shape as
live_metrics, evaluated over ``demo_dataset`` records (customers, workspaces, subscriptions,
payments, usage, tickets, activity, incidents, notificationEvents, connections, founder
contact attempts). Pure functions: no store, provider, model, mail or canonical access.
Demo is a data mode, never a Live fallback; every row is marked fixture=True and the
receipt names the Demo dataset. Record kinds the Demo does not simulate are reported
as unavailable with reason demo_not_simulated, never as zero.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .auth import ControlError
from .live_metrics import (SOURCE_IDS, HEARTBEAT_STALE_SECONDS, build_row, interval_of, previous_interval, parse_stamp, stamp)

ADAPTER = 'demo_metrics/v1'
MAX_POINTS = 1000
NOT_SIMULATED = ('refunds_disputes', 'founder_ops_cost', 'budget_remaining', 'publish_outcomes', 'security_events')
PAID_STATES = ('active', 'past_due')
FEATURES = {'text_model': 'writer', 'image_generation': 'image', 'tool': 'agent', 'storage': 'other', 'action': 'other'}
SOURCE_REASONS = {'demo': 'qualified', 'connected': 'qualified', 'stale': 'lagging'}


def _stamp(value):
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try: return parse_stamp(value)
    except (AttributeError, TypeError, ValueError): return None


def _bounds(interval):
    return parse_stamp(interval['start']), parse_stamp(interval['end']), ZoneInfo(interval['timeZone'])


def _within(record, start, end):
    at = record.get('at')
    return at is not None and start <= at < end


def _cost(row):
    actual, estimated = row.get('actualUsdMicro'), row.get('estimatedUsdMicro')
    return int(actual if actual is not None else (estimated or 0))


# ---- Normalized record builders: each yields dicts with at (aware datetime) + dimension/measure fields ----

def _subscriptions(data, current_only):
    workspaces = {row['id']: row for row in data.get('workspaces', [])}
    for row in data.get('subscriptions', []):
        if not row.get('paid', True) or (current_only and row.get('status') not in PAID_STATES): continue
        yield dict(at=_stamp(row.get('startedAt')), owner=row.get('customerId') or workspaces.get(row.get('workspaceId'), {}).get('ownerId'), wid=row.get('workspaceId'),
                   plan=row.get('plan'), status=row.get('status'))


def _payments(data, status):
    for row in data.get('payments', []):
        if row.get('status') != status: continue
        yield dict(at=_stamp(row.get('at')), wid=row.get('workspaceId'), currency=row.get('currency'), payment_type='subscription_invoice', amount=int(row.get('amountMinor') or 0))


def _usage(data, unknown_only=False):
    workspaces = {row['id']: row for row in data.get('workspaces', [])}
    for row in data.get('usage', []):
        unknown = row.get('costState') == 'estimated_unknown'
        if unknown_only and not unknown: continue
        if row.get('kind') not in ('settle', 'reserve') or row.get('costState') == 'released': continue
        if not unknown_only and row.get('kind') != 'settle': continue
        yield dict(at=_stamp(row.get('at')), wid=row.get('workspaceId'), feature=row.get('feature') or FEATURES.get(row.get('dimension'), 'other'), provider=row.get('provider') or 'simulated',
                   model=row.get('model') or 'simulated', plan=row.get('plan') or workspaces.get(row.get('workspaceId'), {}).get('plan'), cost_state='estimated_unknown' if unknown else 'actual',
                   actual=0 if unknown else _cost(row), estimated=int(row.get('estimatedUsdMicro') or 0))


def _activity(data):
    workspaces = {row['id']: row for row in data.get('workspaces', [])}
    for collection in ('usage', 'activity'):
        for row in data.get(collection, []):
            if row.get('workspaceId'):
                yield dict(at=_stamp(row.get('at')), wid=row['workspaceId'], plan=workspaces.get(row['workspaceId'], {}).get('plan'))


def _notifications(data):
    for row in data.get('notificationEvents', []):
        failed = row.get('state') == 'failed'
        yield dict(at=_stamp(row.get('createdAt')), wid=None, channel=row.get('channel', 'email'), status=row.get('state'), failure_class='transient' if failed else 'none', uncertain=False)


def _calls(data):
    for row in (data.get('founderIntelligence') or {}).get('contactAttempts', []):
        if row.get('channel') != 'call': continue
        yield dict(at=_stamp(row.get('createdAt')), wid=None, kind='proactive', direction='outbound', provider='simulated', state=row.get('state'), failure_class='none',
                   ambiguous=row.get('state') == 'ambiguous', cost=0, duration=0)


def _tickets(data, now):
    for row in data.get('tickets', []):
        if row.get('status') != 'open': continue
        at = _stamp(row.get('at'))
        age = (now - at) if at else timedelta(days=8)
        yield dict(at=at, wid=row.get('workspaceId'), kind=row.get('kind'), age_band='under_1d' if age < timedelta(days=1) else '1d_to_7d' if age < timedelta(days=7) else 'over_7d')


# ---- Generic grouping ----

def _group(records, query, interval, *, dims, implicit=()):
    start, end, zone = _bounds(interval)
    group_by = list(implicit) + [dim for dim in query['groupBy'] if dim not in implicit]
    filters = [(item['dimension'], set(item['values'])) for item in query['filters']]
    groups = defaultdict(list)
    for record in records:
        values = {dim: record.get(dim) for dim in dims}
        values['window'] = record['at'].astimezone(zone).strftime('%Y-%m-%d') if record.get('at') else None
        if any(values.get(dim) not in allowed for dim, allowed in filters): continue
        groups[tuple((dim, values.get(dim)) for dim in group_by)].append(record)
    if len(groups) > MAX_POINTS: raise ControlError('BUDGET_EXCEEDED', 400)
    return group_by, [(dict(key), rows) for key, rows in sorted(groups.items(), key=lambda item: [str(value) for _, value in item[0]])]


def _watermark(rows):
    stamps = [row['at'] for row in rows if row.get('at')]
    return stamp(max(stamps)) if stamps else None


def _event_rows(metric, data, query, interval, records, *, dims, value, unit, currency=None, known=None, unknown=None, numerator=None, denominator=None, measures=None, implicit=(), stale=False):
    start, end, _ = _bounds(interval)
    selected = [record for record in records if _within(record, start, end)]
    group_by, groups = _group(selected, query, interval, dims=dims, implicit=implicit)
    if not groups and group_by: return []
    if not groups: groups = [({}, [])]
    rows = []
    for dimensions, members in groups:
        unknown_count = unknown(members) if unknown else 0
        state, reason = ('partial', 'unsettled_cost_rows') if unknown_count else ('stale', 'source_stale') if stale else ('measured', None)
        rows.append(build_row(metric, interval, dimensions, value=value(members), unit=unit, currency=(dimensions.get('currency') if currency == 'dimension' else currency),
                              state=state, known=known(members) if known else len(members), unknown=unknown_count, numerator=numerator(members) if numerator else None,
                              denominator=denominator(members) if denominator else None, watermark=_watermark(members), sample_count=len(members), reason=reason,
                              measures={name: fn(members) for name, fn in (measures or {}).items()} or None, fixture=True))
    return rows


def _snapshot_rows(metric, data, query, interval, records, *, dims, value, unit, as_of, stale):
    """Snapshot metrics count the state at asOf; a window series counts records started before each local day's end."""
    group_by = query['groupBy']
    if 'window' not in group_by:
        all_records = list(records)
        _, groups = _group(all_records, {**query, 'groupBy': group_by}, interval, dims=dims)
        if not groups and group_by: return []
        if not groups: groups = [({}, [])]
        return [build_row(metric, interval, dimensions, value=value(members), unit=unit, state='stale' if stale else 'measured', known=len(members), watermark=stamp(as_of),
                          sample_count=len(members), reason='source_stale' if stale else None, fixture=True) for dimensions, members in groups]
    start, end, zone = _bounds(interval)
    all_records = list(records)
    rows, day = [], start.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end.astimezone(zone):
        day_end = min(day + timedelta(days=1), as_of + timedelta(seconds=1))
        present = [record for record in all_records if record.get('at') and record['at'] < day_end]
        pinned = [{**record, 'at': day} for record in present]
        other_dims = [dim for dim in group_by if dim != 'window']
        _, groups = _group(pinned, {**query, 'groupBy': other_dims}, interval, dims=dims)
        for dimensions, members in groups or ([({}, [])] if not other_dims else []):
            rows.append(build_row(metric, interval, {**{dim: dimensions.get(dim) for dim in other_dims}, 'window': day.strftime('%Y-%m-%d')}, value=value(members), unit=unit,
                                  state='stale' if stale else 'measured', known=len(members), watermark=stamp(min(day_end, as_of)), sample_count=len(members), fixture=True))
        day += timedelta(days=1)
        if len(rows) > MAX_POINTS: raise ControlError('BUDGET_EXCEEDED', 400)
    return rows


def _distinct(field): return lambda members: len({row.get(field) for row in members if row.get(field) is not None})
def _sum(field): return lambda members: sum(row.get(field) or 0 for row in members)
def _count(predicate=None): return lambda members: sum(1 for row in members if predicate is None or predicate(row))


def _sources(data):
    connection = next((row for row in data.get('connections', []) if isinstance(row, dict) and row.get('id') == 'database'), {})
    stale = data.get('sourceState') == 'stale' or connection.get('state') == 'stale'
    watermark = (data.get('lastGoodAsOf') if stale else None) or data.get('asOf')
    return stale, watermark, connection


def _source_rows(metric, data, query, interval, now):
    stale, watermark, connection = _sources(data)
    rows = []
    wanted = [set(item['values']) for item in query['filters'] if item['dimension'] == 'source']
    state, reason = ('stale', SOURCE_REASONS['stale']) if stale else ('measured', SOURCE_REASONS['demo'])
    for source_id in SOURCE_IDS:
        if wanted and not all(source_id in values for values in wanted): continue
        dimensions = {dim: {'source': source_id, 'state': state, 'reason': reason}.get(dim) for dim in query['groupBy']}
        age = max(0, int((now - parse_stamp(watermark)).total_seconds()))
        rows.append(build_row(metric, interval, dimensions, value=age, unit='seconds', state=state, known=1, watermark=watermark, sample_count=1, reason=reason, fixture=True))
    return rows


def _heartbeat_rows(metric, data, interval, now):
    stale, watermark, _ = _sources(data)
    age = max(0, int((now - parse_stamp(watermark)).total_seconds()))
    state = 'stale' if stale or age > HEARTBEAT_STALE_SECONDS else 'measured'
    return [build_row(metric, interval, {}, value=age, unit='seconds', state=state, known=1, watermark=watermark, sample_count=1, reason='lagging' if state == 'stale' else 'qualified', fixture=True)]


def _cost_vs_cash(metric, data, query, interval, stale):
    cash_query = {**query, 'groupBy': ['currency'] + [dim for dim in query['groupBy'] if dim == 'window'], 'filters': []}
    cost_query = {**query, 'groupBy': [dim for dim in query['groupBy'] if dim == 'window'], 'filters': []}
    cash = _event_rows({**metric, 'id': 'cash_collected'}, data, cash_query, interval, list(_payments(data, 'funded')), dims=('currency', 'payment_type'), value=_sum('amount'), unit='currency_minor', currency='dimension', stale=stale)
    cost = _event_rows({**metric, 'id': 'ai_cost_actual'}, data, cost_query, interval, list(_usage(data)), dims=('feature', 'provider', 'model', 'plan'), value=_sum('actual'),
                       unit='usd_micro', currency='USD', known=_count(lambda row: row['cost_state'] == 'actual'), unknown=_count(lambda row: row['cost_state'] == 'estimated_unknown'), stale=stale)
    cost_by_window = {row['dimensions'].get('window'): row for row in cost}
    rows = []
    for row in cash:
        cost_row = cost_by_window.get(row['dimensions'].get('window'))
        dimensions = {dim: row['dimensions'].get(dim) for dim in query['groupBy']}
        cash_micro = (row['value'] or 0) * 10000
        if cost_row is None:
            rows.append(build_row(metric, interval, dimensions, value=None, unit='ratio', currency=row.get('currency'), state='unavailable', reason='side_unavailable', fixture=True))
        elif row.get('currency') != 'USD':
            rows.append(build_row(metric, interval, dimensions, value=None, unit='ratio', currency=row.get('currency'), state='not_applicable', numerator=cost_row['value'], denominator=cash_micro, reason='currency_not_comparable', fixture=True))
        elif not cash_micro:
            rows.append(build_row(metric, interval, dimensions, value=None, unit='ratio', currency='USD', state='not_applicable', numerator=cost_row['value'], denominator=0, reason='zero_cash_denominator', fixture=True))
        else:
            state = 'partial' if cost_row['coverage']['unknown'] else 'stale' if stale else 'measured'
            rows.append(build_row(metric, interval, dimensions, value=cost_row['value'] / cash_micro, unit='ratio', currency='USD', state=state, known=cost_row['coverage']['known'], unknown=cost_row['coverage']['unknown'],
                                  numerator=cost_row['value'], denominator=cash_micro, watermark=max(filter(None, (row['sourceWatermark'], cost_row['sourceWatermark'])), default=None),
                                  sample_count=row['sampleCount'] + cost_row['sampleCount'], reason='unsettled_cost_rows' if cost_row['coverage']['unknown'] else None, fixture=True))
    if not rows: rows.append(build_row(metric, interval, {dim: None for dim in query['groupBy']}, value=None, unit='ratio', state='not_applicable', reason='no_cash_in_interval', fixture=True))
    return rows


def _rows(metric, data, query, interval, now, stale):
    metric_id = metric['id']
    if metric_id in NOT_SIMULATED:
        return [build_row(metric, interval, {}, value=None, unit=metric['unit'], state='unavailable', reason='demo_not_simulated', fixture=True)]
    if metric_id == 'cron_heartbeat': return _heartbeat_rows(metric, data, interval, now)
    if metric_id == 'source_health': return _source_rows(metric, data, query, interval, now)
    if metric_id == 'cost_vs_cash': return _cost_vs_cash(metric, data, query, interval, stale)
    if metric_id in ('paid_customers', 'paid_workspaces', 'subscriptions_by_plan_status'):
        records = _subscriptions(data, metric_id != 'subscriptions_by_plan_status')
        value = _distinct('owner') if metric_id == 'paid_customers' else _distinct('wid')
        return _snapshot_rows(metric, data, query, interval, records, dims=('plan', 'status'), value=value, unit='count', as_of=now, stale=stale)
    if metric_id == 'data_requests_backlog':
        return _snapshot_rows(metric, data, query, interval, _tickets(data, now), dims=('kind', 'age_band'), value=_count(), unit='count', as_of=now, stale=stale)
    if metric_id == 'cash_collected':
        return _event_rows(metric, data, query, interval, list(_payments(data, 'funded')), dims=('currency', 'payment_type'), value=_sum('amount'), unit='currency_minor', currency='dimension', stale=stale)
    if metric_id == 'payment_failures':
        records = [dict(record, payment_type='subscription') for record in _payments(data, 'failed')]
        return _event_rows(metric, data, query, interval, records, dims=('payment_type',), value=_count(), unit='count', stale=stale)
    if metric_id in ('ai_cost_actual', 'ai_cost_by_feature'):
        return _event_rows(metric, data, query, interval, list(_usage(data)), dims=('feature', 'provider', 'model', 'plan'), value=_sum('actual'), unit='usd_micro', currency='USD',
                           known=_count(lambda row: row['cost_state'] == 'actual'), unknown=_count(lambda row: row['cost_state'] == 'estimated_unknown'),
                           measures={'unknownEstimateUsdMicro': lambda members: sum(row['estimated'] for row in members if row['cost_state'] == 'estimated_unknown')},
                           implicit=('feature',) if metric_id == 'ai_cost_by_feature' else (), stale=stale)
    if metric_id == 'ai_cost_unknown':
        return _event_rows(metric, data, query, interval, list(_usage(data, unknown_only=True)), dims=('feature', 'provider', 'model', 'plan'), value=_sum('estimated'), unit='usd_micro', currency='USD', stale=stale)
    if metric_id == 'active_workspaces':
        return _event_rows(metric, data, query, interval, list(_activity(data)), dims=('plan',), value=_distinct('wid'), unit='count', stale=stale)
    if metric_id == 'notification_delivery':
        return _event_rows(metric, data, query, interval, list(_notifications(data)), dims=('channel', 'status', 'failure_class'), value=_count(), unit='count',
                           known=_count(lambda row: row['status'] not in ('pending', 'claimed')), unknown=_count(lambda row: row['uncertain']), stale=stale)
    if metric_id == 'phone_calls':
        return _event_rows(metric, data, query, interval, list(_calls(data)), dims=('kind', 'direction', 'provider', 'state', 'failure_class'), value=_count(), unit='count',
                           known=_count(lambda row: not row['ambiguous']), unknown=_count(lambda row: row['ambiguous']), measures={'costUsdMicro': _sum('cost'), 'durationSeconds': _sum('duration')}, stale=stale)
    raise ControlError('VALIDATION_FAILED', 400)


def compute(data, query, metrics):
    """Rows, receipt coverage and source versions for activated metrics over one Demo dataset."""
    if not isinstance(data, dict) or data.get('mode') != 'demo' or not isinstance(data.get('asOf'), str): raise ControlError('SCOPE_DENIED')
    if query['comparison'] == 'cohort_age_aligned': raise ControlError('VALIDATION_FAILED', 400)
    if query['comparison'] != 'none' and 'window' in query['groupBy']: raise ControlError('VALIDATION_FAILED', 400)
    now = parse_stamp(data['asOf'])
    stale, _, _ = _sources(data)
    interval, rows = interval_of(query), []
    for metric in metrics:
        current = _rows(metric, data, query, interval, now, stale)
        if query['comparison'] != 'none' and metric['id'] not in NOT_SIMULATED + ('cron_heartbeat', 'source_health'):
            if metric['id'] in ('paid_customers', 'paid_workspaces', 'subscriptions_by_plan_status', 'data_requests_backlog'):
                zone = ZoneInfo(interval['timeZone'])
                day = parse_stamp(interval['start']).astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
                history = dict(start=stamp(day), end=stamp(day + timedelta(days=1)), timeZone=interval['timeZone'])
                previous = [{**row, 'dimensions': {key: value for key, value in row['dimensions'].items() if key != 'window'}}
                            for row in _rows(metric, data, {**query, 'groupBy': query['groupBy'] + ['window'], 'comparison': 'none'}, history, now, stale)] if metric['id'] != 'data_requests_backlog' else []
            else:
                previous = _rows(metric, data, {**query, 'comparison': 'none'}, previous_interval(query), now, stale)
            lookup = {tuple(sorted(row['dimensions'].items())): row for row in previous}
            for row in current:
                match = lookup.get(tuple(sorted(row['dimensions'].items())))
                row['comparison'] = dict(interval=match['interval'], value=match['value'], dataState=match['dataState'], coverage=match['coverage']) if match else dict(interval=None, value=None, dataState='unavailable', coverage=None)
        rows.extend(current)
    coverage = dict(complete=all(row['dataState'] == 'measured' for row in rows), returnedRows=len(rows), populationTotal=None, inputLimit=MAX_POINTS, reason='demo_dataset' if rows else 'no_rows',
                    scenario=data.get('scenario', 'normal'), revision=data.get('revision'))
    versions = dict(adapter=ADAPTER, dataset=data.get('schemaVersion'), seed=(data.get('manifest') or {}).get('seed'), scenario=data.get('scenario', 'normal'), timeZone=query['interval']['timeZone'],
                    receipt=(data.get('receipt') or {}).get('id'))
    return rows, coverage, versions
