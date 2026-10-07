"""Confirmed financial actions with a committed dispatch and read-only recovery."""
import json
import re
from postriff_phase2 import operator_actions
from postriff_phase2.hosted import audit


def snapshot(cur, params, *, except_action=None):
    value = operator_actions.payment_snapshot(cur, params['workspaceId'], params['paymentIntentId'])
    if not isinstance(value, dict):
        return value
    cur.execute("SELECT coalesce(sum(d.amount_minor),0) FROM public.pr_founder_refund_dispatches d WHERE d.workspace_id=%s AND d.payment_intent_id=%s "
                "AND (%s::uuid IS NULL OR d.action_id<>%s::uuid) AND d.state IN ('prepared','uncertain','pending','requires_action','succeeded') "
                "AND NOT EXISTS(SELECT 1 FROM public.pr_credit_refunds r WHERE r.refund_id=d.refund_id)",
                (params['workspaceId'], params['paymentIntentId'], except_action, except_action))
    return {**value, 'dispatchHoldsMinor': int(cur.fetchone()[0])}


def core(value):
    return {k: value[k] for k in ('source', 'sourceId', 'paidMinor', 'refundedMinor', 'refunds', 'disputed', 'currency', 'dispatchHoldsMinor')}


def provider(service):
    from .founder_actions import ActionError
    payment = getattr(getattr(service, 'billing', None), 'provider', None)
    if getattr(payment, 'id', None) != 'stripe' or not callable(getattr(payment, 'create_refund', None)) or not callable(getattr(payment, 'find_refund', None)):
        raise ActionError('POLICY_DISABLED', 409, 'stripe_refund_provider_not_configured')
    return payment


def execute(adapter, request, check):
    from .founder_actions import ActionError
    params, action, actor = request['params'], request['id'], request['operator_id']
    payment = provider(adapter.service)
    with adapter.transaction() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('founder-refund:' + params['paymentIntentId'],))
        cur.execute('SELECT state,result FROM public.pr_founder_refund_dispatches WHERE action_id=%s FOR UPDATE', (action,))
        previous = cur.fetchone()
        if previous and previous[1]:
            return {**previous[1], 'duplicate': True}
        if not previous:
            value = snapshot(cur, params)
            if not isinstance(value, dict) or value['status'] != 'funded' or value['disputed'] or value['livemode'] != payment.live:
                raise ActionError('STALE_PREVIEW', 409, 'payment_state_changed')
            check(core(value))
            if params['amountMinor'] > value['paidMinor'] - value['refundedMinor'] - value['dispatchHoldsMinor']:
                raise ActionError('STALE_PREVIEW', 409, 'amount_exceeds_refundable')
            cur.execute("INSERT INTO public.pr_founder_refund_dispatches(action_id,workspace_id,payment_intent_id,amount_minor,currency,operator_id,state) VALUES(%s,%s,%s,%s,%s,%s,'prepared')",
                        (action, params['workspaceId'], params['paymentIntentId'], params['amountMinor'], params['currency'], actor))
            audit(cur, params['workspaceId'], actor, 'refund.dispatch.prepared', action, {'amountMinor': params['amountMinor'], 'currency': params['currency']})
        # The context commits before provider egress. Any second execution only
        # reads Stripe, even if the first process died before submitting.
    try:
        result = payment.find_refund(payment_intent_id=params['paymentIntentId'], action_id=action) if previous else payment.create_refund(
            payment_intent_id=params['paymentIntentId'], amount_minor=params['amountMinor'], action_id=action, reason=params['reasonCode'])
    except Exception:
        with adapter.transaction() as cur:
            cur.execute("UPDATE public.pr_founder_refund_dispatches SET state='uncertain' WHERE action_id=%s AND result IS NULL", (action,))
            audit(cur, params['workspaceId'], actor, 'refund.dispatch.uncertain', action, {})
        raise ActionError('SOURCE_UNAVAILABLE', 503, 'refund_outcome_unknown_reconcile_same_request') from None
    status = result.get('status') if isinstance(result, dict) else None
    refund_id = result.get('id') if isinstance(result, dict) else None
    if (not isinstance(refund_id, str) or not re.fullmatch(r're_[A-Za-z0-9]{1,100}', refund_id) or
            status not in ('pending', 'requires_action', 'succeeded', 'failed', 'canceled') or
            result.get('amount') != params['amountMinor'] or result.get('currency') != params['currency'] or
            result.get('payment_intent') != params['paymentIntentId']):
        raise ActionError('SOURCE_UNAVAILABLE', 503, 'refund_receipt_not_verified')
    verified = {'refundId': refund_id, 'providerStatus': status, 'amountMinor': params['amountMinor'], 'currency': params['currency'],
                'providerRefundCreated': True, 'refundSucceeded': status == 'succeeded', 'customerNotified': False, 'duplicate': bool(previous)}
    with adapter.transaction() as cur:
        cur.execute('UPDATE public.pr_founder_refund_dispatches SET state=%s,refund_id=%s,result=%s::jsonb WHERE action_id=%s AND result IS NULL',
                    (status, refund_id, json.dumps(verified), action))
        audit(cur, params['workspaceId'], actor, 'refund.provider.receipt', action, verified)
    return verified
