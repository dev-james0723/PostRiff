"""Pure scenario observations over the founder's existing isolated Demo records.

The authenticated caller owns founder/AAL2, CSRF, RLS, revision, audit and the
transaction. This module never dispatches, provisions or creates a second seed.
Saved field patches contain only this service's minimal reversible changes;
incident timelines remain append-only when the visible scenario is restored.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib

from .auth import ControlError

SCENARIOS = {
    'normal': 'Normal operation',
    'payment_failure': 'Simulated payment failure',
    'outage': 'Simulated bug / outage',
    'stale_data': 'Simulated stale source data',
    'notification_failure': 'Simulated notification failure',
    'recovery': 'Simulated recovery',
}
_STATE = '_founderPreviewScenarios'
_META = dict(simulation=True, externalDelivery=False)


def _error(code, status=409):
    raise ControlError('PREVIEW_SCENARIO_' + code, status)


def _stamp(value):
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError()
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _error('INVALID', 400)


def _validate(data, scenario_id, now):
    if not isinstance(data, dict) or data.get('mode') != 'demo':
        _error('DEMO_REQUIRED', 403)
    if not isinstance(scenario_id, str) or scenario_id not in SCENARIOS:
        _error('INVALID', 400)
    stamp = _stamp(now)
    # Full internal source records, never the bounded public chart snapshot.
    if (not isinstance(data.get('manifest'), dict) or data['manifest'].get('fictional') is not True
            or not isinstance(data.get('asOf'), str)):
        _error('SOURCE_REQUIRED')
    _stamp(data['asOf'])
    for name in ('customers', 'workspaces', 'subscriptions', 'invoices', 'payments', 'members', 'tickets', 'usage'):
        rows = data.get(name)
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or not isinstance(r.get('id'), str) for r in rows):
            _error('SOURCE_REQUIRED')
    if (type(data['manifest'].get('subscriberCount')) is not int
            or len(data['customers']) != data['manifest']['subscriberCount']):
        _error('FULL_SOURCE_REQUIRED')
    state = data.get(_STATE, {})
    if (not isinstance(state, dict) or not isinstance(state.get('patches', []), list)
            or not isinstance(state.get('episode', 0), int)):
        _error('STATE_INVALID')
    for name in ('incidents', 'notificationEvents'):
        rows = data.get(name, [])
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            _error('STATE_INVALID')
    if state.get('lastAppliedAt') and stamp < _stamp(state['lastAppliedAt']):
        _error('STALE_EVENT')
    return state


def _row(data, collection, row_id):
    return next((row for row in data.get(collection, []) if row.get('id') == row_id), None)


def _target(data, patch):
    if patch.get('collection'):
        return _row(data, patch['collection'], patch['rowId'])
    if patch.get('object'):
        return data.get(patch['object'])
    return data


def _patch(data, state, key, value, *, collection=None, row_id=None, object_key=None):
    patch = dict(key=key, collection=collection, rowId=row_id, object=object_key)
    target = _target(data, patch)
    if not isinstance(target, dict):
        _error('SOURCE_REQUIRED')
    patch.update(existed=key in target, value=copy.deepcopy(target.get(key)), appliedValue=copy.deepcopy(value))
    state['patches'].append(patch)
    target[key] = copy.deepcopy(value)


def _restore(data, state):
    for patch in reversed(state['patches']):
        target = _target(data, patch)
        # A later independent edit wins; never replace a customer/workspace row.
        if isinstance(target, dict) and target.get(patch['key']) == patch['appliedValue']:
            if patch['existed']:
                target[patch['key']] = copy.deepcopy(patch['value'])
            else:
                target.pop(patch['key'], None)
    state['patches'] = []


def _payment_sources(data):
    customer = next((row for row in data['customers'] if row.get('name') == 'Leo Martins'), data['customers'][0])
    subscription = _row(data, 'subscriptions', customer.get('subscriptionId'))
    if subscription is None or subscription.get('customerId') != customer['id']:
        _error('SOURCE_LINK_INVALID')
    workspace = _row(data, 'workspaces', subscription.get('workspaceId'))
    invoice = _row(data, 'invoices', subscription.get('currentInvoiceId'))
    payment = _row(data, 'payments', invoice.get('paymentId')) if invoice else None
    if (workspace is None or invoice is None or payment is None
            or workspace.get('customerId') != customer['id']
            or any(row.get('subscriptionId') != subscription['id'] for row in (invoice, payment))
            or any(row.get('customerId') != customer['id'] or row.get('workspaceId') != workspace['id']
                   for row in (invoice, payment))
            or payment.get('invoiceId') != invoice['id']):
        _error('SOURCE_LINK_INVALID')
    return customer, workspace, subscription, invoice, payment


def _impact(data):
    sources, seen = [], set()
    for member in data['members']:
        wid = member.get('workspaceId')
        if wid in seen:
            continue
        workspace = _row(data, 'workspaces', wid)
        customer = _row(data, 'customers', member.get('customerId'))
        if workspace and customer and workspace.get('customerId') == customer['id']:
            sources.append(dict(memberId=member['id'], customerId=customer['id'], workspaceId=wid,
                                name=customer.get('name', 'Fictional subscriber'), workspaceName=workspace.get('name')))
            seen.add(wid)
        if len(sources) == 3:
            return sources
    _error('SOURCE_LINK_INVALID')


def _timeline(incident, event_type, now):
    event_id = incident['episodeId'] + '-' + event_type.replace('_', '-')
    if any(row.get('id') == event_id for row in incident['timeline']):
        return False
    incident['timeline'].append(dict(id=event_id, type=event_type, at=now, **_META))
    return True


def _notification(data, incident, kind, now, state='queued'):
    event_id = incident['episodeId'] + '-email-' + kind
    existing = next((row for row in data['notificationEvents'] if row.get('id') == event_id), None)
    if existing is None:
        existing = dict(id=event_id, incidentId=incident['id'], episodeId=incident['episodeId'],
                        kind=kind, channel='email', state=state, createdAt=now, acknowledged=False,
                        acknowledgement='unacknowledged', providerRef=None, **_META)
        data['notificationEvents'].append(existing)
    elif state == 'failed' and existing['state'] == 'queued':
        existing.update(state='failed', failedAt=now, failure='simulated_delivery_failure')
    return existing


def _incident(data, state, now, *, payment_sources=None, reuse_active=False):
    family = 'demo_payment_exception' if payment_sources else 'demo_publishing_outage'
    active_id = state.get('activeIncidentId')
    incident = next((row for row in data['incidents'] if row.get('id') == active_id), None)
    if (incident and incident.get('state') != 'resolved'
            and (reuse_active or incident.get('detectorFamily') == family)):
        return incident
    state['episode'] += 1
    seed = data['manifest'].get('seed', data['schemaVersion'])
    digest = hashlib.sha256(str(seed).encode()).hexdigest()[:12]
    episode_id = f'demo-{"payment" if payment_sources else "outage"}-{digest}-{state["episode"]}'
    if payment_sources:
        customer, workspace, subscription, invoice, payment = payment_sources
        sources = [dict(customerId=customer['id'], workspaceId=workspace['id'], subscriptionId=subscription['id'],
                        invoiceId=invoice['id'], paymentId=payment['id'], name=customer.get('name', 'Fictional subscriber'),
                        workspaceName=workspace.get('name'), plan=subscription.get('plan'),
                        amountMinor=invoice['amountMinor'], currency=invoice['currency'])]
        source_ids = {collection: [row['id']] for collection, row in
                      zip(('customers', 'workspaces', 'subscriptions', 'invoices', 'payments'), payment_sources)}
        known = [f"The Demo control simulated failed payment {payment['id']} for fictional subscriber {customer.get('name', customer['id'])}.",
                 f"Linked invoice {invoice['id']} is past due for {invoice['amountMinor']} minor units ({invoice['currency']}); subscription {subscription['id']} is past due.",
                 'No provider charge, live billing failure or outbound customer message was observed or performed.']
        title = 'Simulated payment exception — ' + customer.get('name', 'Fictional subscriber')
        classification = 'simulated_payment_exception'
    else:
        sources = _impact(data)
        source_ids = dict(members=[row['memberId'] for row in sources],
                          customers=[row['customerId'] for row in sources],
                          workspaces=[row['workspaceId'] for row in sources])
        known = ['The Demo control explicitly simulated a publishing outage for these linked fictional records.',
                 'No live service, customer or provider fault was observed.']
        title, classification = 'Simulated publishing outage', 'simulated_bug_outage'
    incident = dict(id='incident-' + episode_id, episodeId=episode_id, title=title,
                    severity='warning', state='open', classification=classification,
                    detectorFamily=family, sourceTrust='server_owned_demo_scenario',
                    affectedCount=len(sources), affectedWorkspaceIds=[row['workspaceId'] for row in sources],
                    affectedSourceIds=source_ids,
                    affectedRecords=sources, observedAt=now, lastGoodAsOf=data['asOf'],
                    known=known,
                    unknown=['Root cause is unverified; simulated classification is not live causality.'],
                    acknowledged=False, acknowledgement='unacknowledged', notificationState='queued',
                    timeline=[], **_META)
    _timeline(incident, 'opened', now)
    data['incidents'].append(incident)
    state['activeIncidentId'] = incident['id']
    _notification(data, incident, 'incident', now)
    return incident


def _result(data, state, *, replayed=False):
    result = dict(scenario=data['scenario'], scenarioLabel=data['scenarioLabel'], replayed=replayed, **_META)
    if state.get('activeIncidentId'):
        incident = _row(data, 'incidents', state['activeIncidentId'])
        if incident:
            result.update(incidentId=incident['id'], episodeId=incident['episodeId'],
                          incidentState=incident['state'], affectedCount=incident['affectedCount'])
    if state.get('paymentSourceIds'):
        result['paymentSourceIds'] = copy.deepcopy(state['paymentSourceIds'])
    return result


def apply_scenario(data: dict, scenario_id: str, *, now: str) -> dict:
    """Apply a bounded simulated scenario after caller authorization/revision checks.

    Replays do not create timeline events, episodes or notification metadata.
    Recovery explicitly resolves the same incident; acknowledgement is separate.
    Normal restores scenario-owned fields and retains the incident audit history.
    The canonical dataset owner derives all financial aggregates/receipts.
    """
    prior = _validate(data, scenario_id, now)
    if prior.get('appliedScenario') == scenario_id:
        return _result(data, prior, replayed=True)
    # Validate source links before any state mutation so rejection is atomic.
    active = _row(data, 'incidents', prior.get('activeIncidentId'))
    payment_context = (scenario_id == 'payment_failure' or
                       (scenario_id == 'notification_failure' and active
                        and active.get('state') != 'resolved' and active.get('detectorFamily') == 'demo_payment_exception'))
    payment_sources = _payment_sources(data) if payment_context else None
    if scenario_id == 'outage' or (scenario_id == 'notification_failure' and not payment_context):
        _impact(data)
    from .demo_dataset import refresh_summary, receipt

    state = copy.deepcopy(prior) if prior else dict(patches=[], episode=0)
    _restore(data, state)
    data.setdefault('incidents', [])
    data.setdefault('notificationEvents', [])
    state.pop('paymentSourceIds', None)
    if payment_context:
        customer, workspace, subscription, invoice, payment = payment_sources
        fields = (('customers', customer, 'billing_review'), ('workspaces', workspace, 'grace'),
                  ('subscriptions', subscription, 'past_due'), ('invoices', invoice, 'past_due'),
                  ('payments', payment, 'failed'))
        for collection, row, status in fields:
            _patch(data, state, 'status', status, collection=collection, row_id=row['id'])
        _patch(data, state, 'paidAt', None, collection='invoices', row_id=invoice['id'])
        _patch(data, state, 'paymentState', 'simulated_payment_failure')
        state['paymentSourceIds'] = {collection: row['id'] for collection, row, _ in fields}
        incident = _incident(data, state, now, payment_sources=payment_sources)
    elif scenario_id in ('outage', 'notification_failure'):
        incident = _incident(data, state, now, reuse_active=scenario_id == 'notification_failure')
        if incident['detectorFamily'] == 'demo_publishing_outage':
            _patch(data, state, 'supportState', 'simulated_outage')
    elif scenario_id == 'recovery':
        incident = _row(data, 'incidents', state.get('activeIncidentId'))
        if incident and incident.get('state') != 'resolved':
            incident.update(state='resolved', resolvedAt=now)
            _timeline(incident, 'resolved', now)
            _notification(data, incident, 'recovery', now)
    if scenario_id == 'notification_failure':
        _notification(data, incident, 'incident', now, 'failed')
        incident['notificationState'] = 'failed'
        _timeline(incident, 'notification_failed', now)
    data.update(scenario=scenario_id, scenarioLabel=SCENARIOS[scenario_id])
    refresh_summary(data)
    if scenario_id == 'stale_data':
        _patch(data, state, 'dataState', 'stale')
        _patch(data, state, 'lastGoodAsOf', data['asOf'])
        _patch(data, state, 'staleSince', now)
        _patch(data, state, 'sourceState', 'stale')
        _patch(data, state, 'dataState', 'stale', object_key='summary')
        _patch(data, state, 'dataState', 'stale', object_key='analytics')
        for connection in data.get('connections', []):
            if isinstance(connection, dict) and connection.get('id') == 'database':
                _patch(data, state, 'state', 'stale', collection='connections', row_id=connection['id'])
                _patch(data, state, 'lastGoodAsOf', data['asOf'], collection='connections', row_id=connection['id'])
    state.update(appliedScenario=scenario_id, lastAppliedAt=now)
    data[_STATE] = state
    data['receipt'] = receipt(data)
    return _result(data, state)
