"""Golden definition kernels and privacy validation. These do not activate financial policies.

Inputs must be projections of existing verified domain receipts, never model assertions.
Cash deduplication uses the canonical cash movement identity, not webhook delivery IDs.
"""
from datetime import datetime, timedelta
from fractions import Fraction
import re
from .auth import ControlError
from .intelligence import Catalog


def amount(value):
    if type(value) is not int or value<0: raise ControlError('VALIDATION_FAILED',400)
    return value


def recurring_value(rows):
    totals={}
    for row in rows:
        if not row['recurring'] or row['status']!='active' or row['test'] or row['internal']: continue
        currency=row['currency']
        if not re.fullmatch('[A-Z]{3}',currency): raise ControlError('VALIDATION_FAILED',400)
        count=row['intervalCount']
        if type(count) is not int or count<1 or row['interval'] not in ('month','year'): raise ControlError('VALIDATION_FAILED',400)
        # Caller supplies the discounted recurring amount excluding tax/top-ups. No rounding or currency blending.
        value=Fraction(amount(row['amountMinor']),count*(12 if row['interval']=='year' else 1))
        totals[currency]=totals.get(currency,Fraction(0))+value
    return totals


def cash_movements(rows):
    totals,seen={},{}
    signs={'capture':1,'refund':-1,'dispute_withdrawal':-1,'dispute_reinstatement':1}
    for row in rows:
        if row['verified'] is not True: continue
        if row['kind'] not in signs or not re.fullmatch('[A-Z]{3}',row['currency']): raise ControlError('VALIDATION_FAILED',400)
        signed=amount(row['amountMinor'])*signs[row['kind']]
        key=row['movementId']
        normalized=(row['currency'],signed)
        if key in seen:
            if seen[key]!=normalized: raise ControlError('IDEMPOTENCY_CONFLICT',409)
            continue
        seen[key]=normalized
        totals[row['currency']]=totals.get(row['currency'],0)+signed
    return totals


def quality_ratio(numerator,denominator,state='measured'):
    if state!='measured' or numerator is None or denominator is None:
        return dict(value=None,numerator=numerator,denominator=denominator,dataState=state if state!='measured' else 'unavailable')
    if denominator==0:return dict(value=None,numerator=numerator,denominator=0,dataState='not_applicable')
    if numerator<0 or denominator<0 or numerator>denominator:raise ControlError('VALIDATION_FAILED',400)
    return dict(value=numerator/denominator,numerator=numerator,denominator=denominator,dataState='measured')


def timestamp(value):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if not stamp.tzinfo:raise ValueError('Timezone required')
        return stamp
    except (AttributeError,TypeError,ValueError):raise ControlError('VALIDATION_FAILED',400)


def retention(rows,now,age_days):
    if age_days not in (7,28) or not now.tzinfo:raise ControlError('VALIDATION_FAILED',400)
    mature,returned=0,0
    for row in rows:
        # firstValueAt and qualifiedReturns must already satisfy the versioned useful-outcome definition.
        start=timestamp(row['firstValueAt'])+timedelta(days=age_days)
        end=start+timedelta(days=1)
        if end>now:continue
        mature+=1
        returned+=int(any(start<=timestamp(event)<end for event in row['qualifiedReturns']))
    return quality_ratio(returned,mature)


PAYLOADS={
    'control.source.stale':{'sourceId','reasonCode'},
    'control.signal.detected':{'detectorId','detectorVersion','evidenceIds'},
    'control.investigation.completed':{'investigationId','evidenceIds'},
    'control.recommendation.proposed':{'recommendationId','evidenceIds'},
    'control.action.verified':{'actionId','receiptId'},
    'control.engineering.check_completed':{'receiptId','exactSha'},
    'control.heartbeat.missed':{'workerId','reasonCode'},
}


def validate_event(event,environment,catalog=None):
    catalog=catalog or Catalog()
    catalog.validate('event-envelope',event)
    if event['environment']!=environment or event['classification'] not in ('internal_metadata','customer_metadata'):
        raise ControlError('SCOPE_DENIED')
    if environment=='production' and event['fixture']:raise ControlError('SCOPE_DENIED')
    payload=event['payload']
    if set(payload)!=PAYLOADS[event['eventType']]:raise ControlError('VALIDATION_FAILED',400)
    for key,value in payload.items():
        if key=='evidenceIds':
            if not isinstance(value,list) or len(value)>20:raise ControlError('VALIDATION_FAILED',400)
            from .intelligence import identifier
            for item in value:identifier(item)
        elif key=='detectorVersion':
            if type(value) is not int or value<1:raise ControlError('VALIDATION_FAILED',400)
        elif key=='sourceId':
            if value not in {row['id'] for row in catalog.integrations}:raise ControlError('VALIDATION_FAILED',400)
        elif key=='reasonCode':
            if value not in ('lagging','not_configured','provider_unavailable','reconciliation_required'):raise ControlError('VALIDATION_FAILED',400)
        elif key=='exactSha':
            if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{40}',value):raise ControlError('VALIDATION_FAILED',400)
        elif not isinstance(value,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,160}',value):raise ControlError('VALIDATION_FAILED',400)
    return event
