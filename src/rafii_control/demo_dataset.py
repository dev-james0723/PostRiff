"""Deterministic, fictional business records for the existing isolated Demo store.

The catalog is the implemented v2 candidate, not a claim of production pricing.
This module has no provider, mail, model, payment or canonical-write dependency.
"""
from collections import Counter, defaultdict
import copy
import operator


# sample_data() reads no clock, randomness or environment, so it is the same for every founder of a schema version; a
# founder's stored Demo is only an overlay of changes against it (see overlay/restore). Any change to the generated records
# must bump SCHEMA_VERSION: stored overlays are diffs against them, and a row of an older version restarts from the new base.
SCHEMA_VERSION = 'rafii-admin-demo-v1'
SEED = 'rafii-admin-10000-20261001-v1'
AS_OF = '2026-10-01T12:00:00Z'
PAGE_SIZE = 50
COLLECTIONS = ('customers', 'workspaces', 'subscriptions', 'invoices', 'payments',
               'members', 'usage', 'credits', 'tickets', 'activity')
PAID_PLANS = (
    dict(id='starter-v1', name='Starter', priceId=None, amountMinor=2900,
         credits=1000, count=4500, memberLimit=1),
    dict(id='creator-v1', name='Creator', priceId='creator-59-v1', amountMinor=5900,
         credits=3500, count=4000, memberLimit=1),
    dict(id='studio-v2', name='Studio', priceId=None, amountMinor=14900,
         credits=8000, count=1500, memberLimit=3),
)


def seed_manifest():
    return dict(schemaVersion=SCHEMA_VERSION, seed=SEED,
                fictional=True, subscriberCount=10000, currentPaidSubscriptionCount=10000,
                billingCycles=['monthly'], normalScenario='normal', asOf=AS_OF,
                catalogState='implemented_v2_candidate', productionVerified=False,
                pricingActivation='proposed_activation_pending',
                catalogSource=dict(repository='dev-james0723/PostRiff', commit='b862cf1f',
                                   migration='migrations/postriff/048_pricing_credit_catalog_v2.sql',
                                   migrationCommit='0d4334cb7d5b85e2ae73969becfb1babed95b3e7',
                                   migrationSha256='a36357deb034fa32faac10ac9c893d5b09087f01c9689e072e8764adef792ba0'),
                distribution=[dict(planId=p['id'], plan=p['name'], priceId=p['priceId'],
                                   count=p['count'], amountMinor=p['amountMinor'], currency='USD',
                                   billingCycle='monthly', credits=p['credits']) for p in PAID_PLANS],
                note='All customers and operational amounts are fictional Demo assumptions. '
                     'Monthly catalog candidate only; annual billing is not implemented. '
                     'No login accounts, provider customers, charges or messages are created.')


def catalog():
    plans = [dict(id='free-v1', name='Free', priceId=None, amountMinor=0, currency='USD',
                  billingCycle='monthly', credits=0, subscribers=0, paid=False)]
    plans.extend(dict(id=p['id'], name=p['name'], priceId=p['priceId'], amountMinor=p['amountMinor'],
                      currency='USD', billingCycle='monthly', credits=p['credits'],
                      subscribers=p['count'], paid=True, memberLimit=p['memberLimit']) for p in PAID_PLANS)
    return dict(state='implemented_v2_candidate', productionVerified=False,
                activation='proposed_activation_pending', billingCycles=['monthly'],
                source=seed_manifest()['catalogSource'], plans=plans)


def _plan(index):
    # Retain recognizable personas while keeping exact catalog distribution.
    if index == 1: return PAID_PLANS[2]
    if index == 2: return PAID_PLANS[1]
    if index == 3 or index <= 4502: return PAID_PLANS[0]
    return PAID_PLANS[1] if index <= 8501 else PAID_PLANS[2]


def sample_data():
    data = dict(mode='demo', schemaVersion=SCHEMA_VERSION, revision=1, scenario='normal',
                scenarioLabel='Normal operation', asOf=AS_OF, manifest=seed_manifest(), catalog=catalog(),
                paymentState='demo', supportState='demo', usageState='demo',
                limits=dict(pageSize=PAGE_SIZE, truncated=True, totalSubscribers=10000),
                connections=[dict(id='database', label='Isolated Demo workspace', state='demo', required=True,
                                  detail='10,000 fictional subscribers in this founder’s persistent Demo store. '
                                         'No customer accounts or external deliveries are created.')])
    data.update({name: [] for name in COLLECTIONS})
    first_names = ('Maya', 'Leo', 'Aisha', 'Sofia', 'Daniel', 'Mei', 'Noah', 'Imani', 'Lucas', 'Priya',
                   'Amara', 'Hana', 'Elias', 'Nora', 'Mateo', 'Avery', 'Theo', 'Zara', 'Kai', 'Elena')
    last_names = ('Chen', 'Martins', 'Patel', 'Okafor', 'Park', 'Rivera', 'Singh', 'Tanaka', 'Morgan', 'Silva',
                  'Williams', 'Lin', 'Nguyen', 'Garcia', 'Brown', 'Kim', 'Wilson', 'Ali', 'Reed', 'Costa')
    companies = ('Fern', 'Northline', 'Copper', 'Juniper', 'Harbor', 'Willow', 'Atlas', 'Sunday', 'Bluebird', 'Acorn',
                 'Fieldnote', 'Cedar', 'Lantern', 'Orchard', 'Golden', 'Pebble', 'Sparrow', 'Maple', 'Lumen', 'Tide')
    suffixes = ('Studio', 'Stories', 'Creative', 'Media', 'Collective', 'Works', 'Content', 'Lab')
    countries = ('US', 'GB', 'HK', 'CA', 'AU', 'SG', 'DE', 'JP')
    months = ('2026-08', '2026-09', '2026-10')
    for i in range(1, 10001):
        p = _plan(i)
        cid, wid, sid = f'customer-{i}', f'workspace-{i}', f'subscription-{i}'
        name = f'{first_names[(i-1) % 20]} {last_names[((i-1) // 20) % 20]}'
        company = f'{companies[(i-1) % 20]} {suffixes[((i-1) // 20) % 8]} {i:05d}'
        if i <= 3:
            name = ('Maya Chen', 'Leo Martins', 'Aisha Patel')[i-1]
            company = ('Fern Studio', 'Northline Stories', 'Aisha Creates')[i-1]
        started = f'2025-{1+(i % 12):02d}-{1+(i % 26):02d}T09:00:00Z'
        email = f'subscriber.{i:05d}@example.invalid'
        quota = p['credits']
        used = quota * (18 + (i * 37 % 73)) // 100
        member_count = 3 if p['name'] == 'Studio' else 1
        data['customers'].append(dict(id=cid, name=name, company=company, email=email, status='active',
                                      country=countries[i % len(countries)], createdAt=started, plan=p['name'],
                                      planId=p['id'], billingCycle='monthly', subscriptionId=sid, workspaceIds=[wid],
                                      dataState='simulated', fictional=True))
        data['workspaces'].append(dict(id=wid, name=company, ownerId=cid, customerId=cid, memberCount=member_count,
                                       revision=1, plan=p['name'], planId=p['id'], subscriptionId=sid,
                                       billingCycle='monthly', status='active', renameAllowed=True,
                                       creditsQuota=quota, creditsUsed=used, creditsRemaining=quota-used,
                                       createdAt=started, dataState='simulated'))
        data['subscriptions'].append(dict(id=sid, customerId=cid, workspaceId=wid, plan=p['name'], planId=p['id'],
                                          priceId=p['priceId'], status='active', paid=True, amountMinor=p['amountMinor'],
                                          currency='USD', billingCycle='monthly', creditsQuota=quota, startedAt=started,
                                          periodStartsAt='2026-10-01T00:00:00Z', renewsAt='2026-11-01T00:00:00Z',
                                          currentInvoiceId=f'invoice-{i}', termsStatus='implemented_v2_candidate',
                                          productionVerified=False, dataState='simulated'))
        for offset, month in enumerate(reversed(months)):
            suffix = '' if offset == 0 else f'-history-{offset}'
            iid, pid = f'invoice-{i}{suffix}', f'payment-{i}{suffix}'
            at = f'{month}-01T08:{i % 60:02d}:00Z'
            data['invoices'].append(dict(id=iid, number=f'DEMO-{month.replace("-", "")}-{i:05d}',
                                         customerId=cid, workspaceId=wid, subscriptionId=sid, paymentId=pid,
                                         plan=p['name'], planId=p['id'], billingCycle='monthly', amountMinor=p['amountMinor'],
                                         currency='USD', status='paid', period=month, issuedAt=at, dueAt=at, paidAt=at,
                                         lineItems=[dict(label=f'{p["name"]} monthly subscription', quantity=1,
                                                         amountMinor=p['amountMinor'])], dataState='simulated'))
            data['payments'].append(dict(id=pid, customerId=cid, workspaceId=wid, subscriptionId=sid,
                                         invoiceId=iid, plan=p['name'], planId=p['id'], billingCycle='monthly',
                                         amountMinor=p['amountMinor'], currency='USD', status='funded',
                                         method='card', cardLast4=f'{1000 + i % 9000:04d}', at=at, dataState='simulated',
                                         providerState='simulated_not_charged'))
        for j in range(1, member_count+1):
            data['members'].append(dict(id=f'member-{i}-{j}', workspaceId=wid, customerId=cid,
                                        name=name if j == 1 else f'{first_names[(i+j) % 20]} {last_names[(i+j*3) % 20]}',
                                        email=email if j == 1 else f'member.{i:05d}.{j}@example.invalid',
                                        role='owner' if j == 1 else 'editor' if j % 2 else 'member', status='active',
                                        joinedAt=started, dataState='simulated'))
        data['usage'].append(dict(id=f'usage-{i}', customerId=cid, workspaceId=wid, subscriptionId=sid,
                                  plan=p['name'], planId=p['id'], billingCycle='monthly', kind='settle',
                                  dimension='text_model', quantity=used // 5, unit='request', creditsUsed=used,
                                  creditsQuota=quota, creditsRemaining=quota-used, costState='simulated',
                                  actualUsdMicro=None, estimatedUsdMicro=used * 1000, period='2026-10',
                                  at=AS_OF, dataState='simulated'))
        for kind, quantity, balance, at in (('grant', quota, quota, '2026-10-01T00:00:00Z'),
                                             ('settle', -used, quota-used, AS_OF)):
            data['credits'].append(dict(id=f'credit-{i}-{kind}', customerId=cid, workspaceId=wid, subscriptionId=sid,
                                        invoiceId=f'invoice-{i}' if kind == 'grant' else None, usageId=f'usage-{i}' if kind == 'settle' else None,
                                        kind=kind, quantity=quantity, unit='credit', balanceAfter=balance,
                                        provenance='simulated_monthly_plan_grant' if kind == 'grant' else 'simulated_usage_settlement',
                                        at=at, dataState='simulated'))
        title = ('Help connecting a new LinkedIn channel' if i == 1 else
                 'Review the next invoice recipient' if i == 2 else
                 'Quota refreshed after a plan upgrade' if i == 3 else
                 ('Invite a teammate to our workspace', 'Explain this month’s credit usage',
                  'Confirm the invoice billing details', 'Help reconnect a publishing channel')[i % 4])
        opened = i in (1, 2) or i % 17 == 0
        data['tickets'].append(dict(id=f'ticket-{i}', customerId=cid, workspaceId=wid, plan=p['name'], planId=p['id'],
                                    billingCycle='monthly', title=title, status='open' if opened else 'completed',
                                    kind='billing' if i % 4 == 2 or i == 2 else 'support', priority='normal',
                                    description=f'{name} asked to {title[0].lower()+title[1:]}. '
                                                + ('Awaiting an internal Demo follow-up.' if opened else 'Resolved with a documented workspace walkthrough.'),
                                    at=f'2026-09-{1+i % 28:02d}T10:00:00Z', dataState='simulated'))
        data['activity'].append(dict(id=f'activity-{i}', customerId=cid, workspaceId=wid,
                                     label=f'{company}: October subscription paid and monthly credits granted',
                                     kind='subscription_renewal', at=f'2026-10-01T08:{i % 60:02d}:00Z', dataState='simulated'))
    refresh_summary(data)
    data['receipt'] = receipt(data)
    return data


def _provenance(data):
    stale = data.get('scenario') == 'stale_data' or data.get('sourceState') == 'stale'
    as_of = (data.get('lastGoodAsOf') or data['asOf']) if stale else data['asOf']
    result = dict(asOf=as_of, dataState='stale' if stale else 'simulated')
    if stale: result['lastGoodAsOf'] = as_of
    return result


def refresh_summary(data):
    """All displayed business totals derive from the linked records, including scenarios."""
    provenance = _provenance(data)
    subscriptions = data['subscriptions']
    current_paid = [s for s in subscriptions if s.get('paid', True) and s.get('status') in ('active', 'past_due', 'grace')]
    active = [s for s in subscriptions if s.get('status') == 'active']
    count_by_plan = Counter(s['planId'] for s in current_paid)
    mrr_by_plan = Counter()
    for row in active: mrr_by_plan[row['planId']] += row['amountMinor']
    revenue, cash = defaultdict(int), defaultdict(int)
    for row in data.get('invoices', []):
        if row['status'] == 'paid': revenue[row['period']] += row['amountMinor']
    for row in data.get('payments', []):
        if row['status'] == 'funded': cash[row['at'][:7]] += row['amountMinor']
    distribution = [dict(planId=p['id'], plan=p['name'], subscribers=count_by_plan[p['id']],
                         activeSubscriptions=sum(s['planId']==p['id'] for s in active),
                         mrrMinor=mrr_by_plan[p['id']], amountMinor=p['amountMinor'], creditsQuota=p['credits'],
                         currency='USD', billingCycle='monthly') for p in PAID_PLANS]
    data['summary'] = dict(customers=len(data['customers']), workspaces=len(data['workspaces']),
                           totalCustomerRecords=len(data['customers']), currentPaidSubscriptions=len(current_paid),
                           activeSubscriptions=len(active), openRequests=sum(t['status']=='open' for t in data['tickets']),
                           billingReviews=sum(s['status'] in ('past_due','grace') for s in subscriptions),
                           mrrMinor=sum(mrr_by_plan.values()), currency='USD',
                           cashThisMonthMinor=cash[data['asOf'][:7]],
                           creditsQuota=sum(s.get('creditsQuota', 0) for s in active),
                           creditsUsed=sum(r.get('creditsUsed',0) for r in data['usage']),
                           creditsRemaining=sum(w.get('creditsRemaining',0) for w in data['workspaces']),
                           paidInvoices=sum(r['status']=='paid' for r in data.get('invoices',[])),
                           failedPayments=sum(r['status']=='failed' for r in data['payments']), **provenance)
    usage_bands = Counter('Under 50%' if r['creditsUsed'] < r['creditsQuota']*.5 else
                          '50–79%' if r['creditsUsed'] < r['creditsQuota']*.8 else '80% or more' for r in data['usage'])
    data['analytics'] = dict(planDistribution=distribution,
                             revenueTrend=[dict(period=period, revenueMinor=revenue[period], cashMinor=cash[period],
                                                currency='USD', **provenance) for period in sorted(set(revenue)|set(cash))],
                             usageDistribution=[dict(label=label, subscribers=usage_bands[label])
                                                for label in ('Under 50%', '50–79%', '80% or more')],
                             supportDistribution=[dict(status=status, count=count) for status,count in sorted(Counter(r['status'] for r in data['tickets']).items())],
                             revenueDefinition='Active monthly recurring subscriptions; excludes one-time credits and cash timing.',
                             cashDefinition='Simulated funded invoice payments by payment month.', **provenance)


def receipt(data):
    return dict(id=f'demo-{SCHEMA_VERSION}-{data["revision"]}-{data.get("scenario", "normal")}',
                mode='demo', revision=data['revision'], scenario=data.get('scenario','normal'),
                seed=data['manifest']['seed'], **_provenance(data),
                productionVerified=False, externalDelivery=False)


def bounded_snapshot(data):
    """A public response never includes the internal 10,000-row collections."""
    keys = ('mode','schemaVersion','revision','scenario','scenarioLabel','asOf','sourceState','lastGoodAsOf','manifest','catalog',
            'paymentState','supportState','usageState','connections','summary','analytics')
    result = {key: copy.deepcopy(data[key]) for key in keys if key in data}
    result.update({key: copy.deepcopy(data.get(key, [])[:PAGE_SIZE]) for key in COLLECTIONS})
    result['limits'] = dict(pageSize=PAGE_SIZE, truncated=True, totalSubscribers=len(data['customers']),
                            collectionTotals={key:len(data.get(key, [])) for key in COLLECTIONS})
    result['receipt'] = receipt(data)
    result['asOf'] = result['receipt']['asOf']
    result['_dataState'] = 'stale' if result['receipt']['dataState']=='stale' else 'synthetic'
    result['_receiptIds'] = [result['receipt']['id']]
    return result


def linked_records(data, collection, rows):
    """Drilldowns expose only records related to the selected entity, bounded per collection."""
    workspace_ids, customer_ids = set(), set()
    for row in rows:
        workspace_ids.update(row.get('workspaceIds', []))
        if row.get('workspaceId'): workspace_ids.add(row['workspaceId'])
        if collection == 'workspaces': workspace_ids.add(row['id'])
        if row.get('customerId') or row.get('ownerId'): customer_ids.add(row.get('customerId') or row['ownerId'])
        if collection == 'customers': customer_ids.add(row['id'])
    for workspace in data['workspaces']:
        if workspace['id'] in workspace_ids: customer_ids.add(workspace['ownerId'])
    result = {}
    for key in COLLECTIONS:
        selected = [r for r in data.get(key, []) if
                    (key == 'customers' and r['id'] in customer_ids) or
                    (key == 'workspaces' and r['id'] in workspace_ids) or
                    (r.get('customerId') in customer_ids) or (r.get('workspaceId') in workspace_ids)]
        result[key] = copy.deepcopy(selected[:PAGE_SIZE])
    return result


# ---- Per-founder storage -----------------------------------------------------------------------------------------------
# The full dataset is ~66 MB of JSON; storing it per founder made the first Demo open and every action move tens of MB. A
# founder's row holds only an overlay of what their actions changed; the base is generated once per process and shared by
# every founder's view. Shared records are read-only: an in-place write raises instead of leaking into another founder's view.
STORAGE = 'overlay-v1'
_DELTA_KEYS = frozenset(('rows', 'head', 'patch', 'drop', 'stop', 'tail'))
_CONTAINERS = frozenset((dict, list))
_BASES = {}


def _read_only(*_args, **_kwargs):
    raise TypeError('Demo base records are shared and read-only; copy a record before changing it')


class _Record(dict):
    __slots__ = ()
    __setitem__ = __delitem__ = __ior__ = clear = pop = popitem = setdefault = update = _read_only
    def __copy__(self): return dict(self)
    def __deepcopy__(self, memo): return {key: copy.deepcopy(value, memo) for key, value in self.items()}


class _Rows(list):
    __slots__ = ()
    __setitem__ = __delitem__ = __iadd__ = __imul__ = append = extend = insert = pop = remove = clear = sort = reverse = _read_only
    def __copy__(self): return list(self)
    def __deepcopy__(self, memo): return [copy.deepcopy(value, memo) for value in self]


def _freeze(value):
    """A read-only copy; copy/deepcopy of it give plain dicts and lists again."""
    if type(value) in (_Record, _Rows): return value
    if isinstance(value, dict):
        frozen = _Record(value)
        # Only walk records that hold a nested container: most hold none, which keeps the per-process base build cheap.
        if not _CONTAINERS.isdisjoint(map(type, value.values())):
            for key, item in value.items():
                if isinstance(item, (dict, list)): dict.__setitem__(frozen, key, _freeze(item))
        return frozen
    if isinstance(value, list): return _Rows(map(_freeze, value))
    return value


def base():
    """(the read-only base dataset, {collection: {id: position}}), generated once per process for this schema and seed."""
    key = (SCHEMA_VERSION, SEED)
    if key not in _BASES:
        data = sample_data()
        for name in list(data): data[name] = _freeze(data[name])   # releases each plain collection as it goes
        _BASES[key] = _Record(data), {name: {row['id']: index for index, row in enumerate(data[name])} for name in COLLECTIONS}
    return _BASES[key]


def _changes(old, row):
    change = {key: value for key, value in row.items() if key not in old or old[key] != value}
    gone = [key for key in old if key not in row]
    if gone: change['$unset'] = gone
    return change


def _delta(rows, base_rows, positions):
    """`rows` as changes to a base collection: new rows before and after it, and its rows in base order up to `stop`, some
    dropped and some changed field by field. Any other shape (a reordered or interleaved collection) is stored whole."""
    if len(rows) == len(base_rows):
        if all(map(operator.is_, rows, base_rows)): return {}
        # The usual shape after an action: base order, some records replaced by changed copies.
        changed = [index for index, (row, old) in enumerate(zip(rows, base_rows)) if row is not old and row != old]
        if all(isinstance(rows[index], dict) and rows[index].get('id') == base_rows[index]['id']
               and not any(key.startswith('$') for key in rows[index]) for index in changed):
            return dict(patch={rows[index]['id']: _changes(base_rows[index], rows[index]) for index in changed}) if changed else {}
    head, tail, patch, drop, last = [], [], {}, [], -1
    for row in rows:
        ident = row.get('id') if isinstance(row, dict) else None
        index = positions.get(ident) if isinstance(ident, str) else None
        if index is None:
            (tail if last >= 0 else head).append(row)
            continue
        if index <= last or tail: return dict(rows=rows)
        if index > last + 1: drop.extend(base_rows[skipped]['id'] for skipped in range(last + 1, index))
        last, old = index, base_rows[index]
        if row is not old and row != old:
            if any(key.startswith('$') for key in row): return dict(rows=rows)
            patch[ident] = _changes(old, row)
    delta = {key: value for key, value in (('head', head), ('patch', patch), ('drop', drop), ('tail', tail)) if value}
    if last + 1 != len(base_rows): delta['stop'] = last + 1
    return delta


def _rows(base_rows, delta, positions, private):
    """Inverse of _delta. Rows that differ from the base are new objects; the others are the shared base records."""
    own = copy.deepcopy if private else _freeze
    if not isinstance(delta, dict) or not _DELTA_KEYS.issuperset(delta): raise ValueError('invalid Demo overlay')
    if 'rows' in delta:
        if not isinstance(delta['rows'], list): raise ValueError('invalid Demo overlay')
        rows = [own(row) for row in delta['rows']]
    else:
        stop, patch, drop = delta.get('stop', len(base_rows)), delta.get('patch', {}), delta.get('drop', [])
        head, tail = delta.get('head', []), delta.get('tail', [])
        if (type(stop) is not int or not 0 <= stop <= len(base_rows) or not isinstance(patch, dict)
                or not all(isinstance(value, list) for value in (drop, head, tail))
                or not all(isinstance(ident, str) and positions.get(ident, stop) < stop for ident in (*patch, *drop))
                or not all(isinstance(change, dict) and isinstance(change.get('$unset', []), list) for change in patch.values())):
            raise ValueError('invalid Demo overlay')
        rows = base_rows[:stop]
        for ident, change in patch.items():
            row = dict(base_rows[positions[ident]])
            row.update((key, own(value)) for key, value in change.items() if key != '$unset')
            for key in change.get('$unset', []): row.pop(key, None)
            rows[positions[ident]] = row if private else _Record(row)
        if drop:
            dropped = set(drop)
            rows = [row for row in rows if row['id'] not in dropped]
        rows = [own(row) for row in head] + rows + [own(row) for row in tail]
    return rows if private else _Rows(rows)


def overlay(data=None):
    """The stored form of a founder's Demo: what `data` changes against the base (nothing for a new Demo), so its size
    follows the founder's changes, not the dataset. The receipt is derived on every load and not stored."""
    base_data, positions = base()
    result = dict(mode='demo', storage=STORAGE, schemaVersion=SCHEMA_VERSION, seed=SEED,
                  revision=base_data['revision'] if data is None else data['revision'])
    if data is None: return result
    skip = {*COLLECTIONS, 'revision', 'receipt'}
    changed = {key: value for key, value in data.items() if key not in skip and (key not in base_data or base_data[key] != value)}
    unset = [key for key in base_data if key not in data and key != 'receipt']
    rows = {}
    for name in COLLECTIONS:
        delta = _delta(data[name], base_data[name], positions[name]) if name in data else None
        if delta: rows[name] = delta
    result.update((key, value) for key, value in (('set', changed), ('unset', unset), ('rows', rows)) if value)
    return result


def restore(payload, private=False):
    """A founder's full Demo dataset from their stored overlay. ValueError when the payload is not an overlay of this base
    (a legacy row holding the whole dataset, an older schema version or another seed).

    A read view shares the base records and is read-only all the way down, so one can be cached and handed to every reader.
    private=True gives an action its own top-level values and collection lists; records stay the shared read-only ones until
    own() copies them."""
    if not (isinstance(payload, dict) and payload.get('storage') == STORAGE and payload.get('schemaVersion') == SCHEMA_VERSION
            and payload.get('seed') == SEED and type(payload.get('revision')) is int):
        raise ValueError('not an overlay of this Demo base')
    base_data, positions = base()
    changed, unset, rows = payload.get('set', {}), payload.get('unset', []), payload.get('rows', {})
    if not (isinstance(changed, dict) and isinstance(unset, list) and isinstance(rows, dict) and set(rows) <= set(COLLECTIONS)):
        raise ValueError('invalid Demo overlay')
    own = copy.deepcopy if private else _freeze
    data = {key: own(value) for key, value in base_data.items() if key not in COLLECTIONS}
    data.update((key, own(value)) for key, value in changed.items())
    for name in COLLECTIONS:
        data[name] = (_rows(base_data[name], rows[name], positions[name], private) if name in rows else
                      list(base_data[name]) if private else base_data[name])
    for key in unset: data.pop(key, None)
    data['revision'] = payload['revision']
    return data


def own(rows, index):
    """rows[index] as the action's private copy to change (rows must be the action's own list, as restore(private=True) gives)."""
    row = rows[index]
    if type(row) is _Record: row = rows[index] = dict(row)
    return row


def own_records(data):
    """Private copies of every record, for an action that may change any of them (a scenario)."""
    for name in COLLECTIONS: data[name] = list(map(dict, data[name]))


def compact_response(response):
    """An action response as stored for its replays: each collection page becomes a delta against the base, because pages
    nearly always repeat base records (twenty stored responses no longer hold twenty copies of them)."""
    if not isinstance(response, dict): return response
    base_data, positions = base()
    stored = dict(response)
    for name in COLLECTIONS:
        if isinstance(response.get(name), list):
            delta = _delta(response[name], base_data[name], positions[name])
            if 'rows' not in delta: stored[name] = {'$page': delta}
    return stored


def expand_response(stored):
    """The response compact_response stored, as fresh plain objects."""
    if not isinstance(stored, dict): return stored
    base_data, positions = base()
    response = dict(stored)
    for name in COLLECTIONS:
        page = stored.get(name)
        if isinstance(page, dict) and set(page) == {'$page'}:
            response[name] = copy.deepcopy(_rows(base_data[name], page['$page'], positions[name], False))
    return response
