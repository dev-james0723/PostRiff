"""Opt-in credit funding. Verified payments append to the existing usage ledger.

No packs or prices are activated by this module. Network checkout happens outside
transactions; webhook processing is entirely transactional and never calls Stripe.
"""
import json
import re
import time
from postriff_alpha.domain import AlphaError
from .credit_wallet import amount
from .credit_meter import POLICY_VERSION


def _money(value):
    if type(value) is not int or not 0 < value <= 10**9:
        raise ValueError('Invalid payment amount.')
    return value


def _ref(value):
    value = value.get('id') if isinstance(value, dict) else value
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError('Missing payment identity.')
    return value


def refund_credit_amount(granted, paid_cents, refunded_cents):
    amount(granted); _money(paid_cents)
    if type(refunded_cents) is not int or not 0 <= refunded_cents <= paid_cents:
        raise ValueError('Refund exceeds the verified payment.')
    return granted * refunded_cents // paid_cents


DISPUTE_EVENTS = ('charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed', 'charge.dispute.funds_withdrawn', 'charge.dispute.funds_reinstated')


def credit_related(raw):
    """Events this module owns: credit-order checkouts, refunds and disputes. Subscriptions go elsewhere."""
    kind = raw.get('type') if isinstance(raw, dict) else None
    obj = ((raw.get('data') or {}).get('object') or {}) if isinstance(raw, dict) else {}
    if isinstance(kind, str) and kind.startswith('checkout.session.'):
        return isinstance(obj, dict) and bool((obj.get('metadata') or {}).get('credit_order_id'))
    return kind in ('refund.created', 'refund.updated', 'refund.failed') or kind in DISPUTE_EVENTS


def dispute_withdrawn(kind, status):
    """Whether the disputed amount is out of the account now (inquiries and won disputes are not)."""
    if kind == 'charge.dispute.funds_withdrawn': return True
    if kind == 'charge.dispute.funds_reinstated': return False
    return status in ('needs_response', 'under_review', 'lost')


def credit_event(raw):
    obj = (raw.get('data') or {}).get('object') or {}
    kind = raw.get('type')
    if kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        order = (obj.get('metadata') or {}).get('credit_order_id')
        if not order or obj.get('mode') != 'payment' or obj.get('payment_status') != 'paid': return None
        workspace = obj.get('client_reference_id')
        result = {'operation':'fund', 'orderId':_ref(order), 'sessionId':_ref(obj.get('id')),
                  'paymentIntentId':_ref(obj.get('payment_intent')), 'amount':_money(obj.get('amount_total')),
                  'workspaceId':workspace if isinstance(workspace, str) else None}
    elif kind in ('checkout.session.expired', 'checkout.session.async_payment_failed'):
        order = (obj.get('metadata') or {}).get('credit_order_id')
        if not order or obj.get('mode') != 'payment': return None
        result = {'operation':'expire' if kind.endswith('expired') else 'fail', 'orderId':_ref(order), 'sessionId':_ref(obj.get('id')),
                  'paymentIntentId':None, 'amount':_money(obj.get('amount_total'))}
    elif kind in DISPUTE_EVENTS:
        status = obj.get('status')
        if not isinstance(status, str) or not re.fullmatch('[a-z_]{1,40}', status): raise ValueError('Unknown dispute status; reconciliation is required.')
        result = {'operation':'dispute', 'disputeId':_ref(obj.get('id')), 'status':status, 'withdrawn':dispute_withdrawn(kind, status),
                  'paymentIntentId':_ref(obj.get('payment_intent')), 'amount':_money(obj.get('amount'))}
    elif kind in ('refund.created','refund.updated','refund.failed'):
        status = obj.get('status')
        if status not in ('pending','requires_action','succeeded','failed','canceled'):
            raise ValueError('Unknown refund status; reconciliation is required.')
        result = {'operation':'refund', 'refundId':_ref(obj.get('id')), 'status':status,
                  'paymentIntentId':_ref(obj.get('payment_intent')), 'amount':_money(obj.get('amount'))}
    else: return None
    currency = obj.get('currency')
    if not isinstance(currency,str) or not re.fullmatch('[a-z]{3}',currency): raise ValueError('Invalid currency.')
    if type(raw.get('livemode')) is not bool: raise ValueError('Payment mode is unknown.')
    if type(raw.get('created')) is not int: raise ValueError('Event time is required.')
    return {**result, 'currency':currency, 'eventId':_ref(raw.get('id')),
            'createdAt':raw['created'], 'live':raw['livemode']}


class CreditPurchases:
    def __init__(self, book, provider, clock=time.time):
        self.book, self.provider, self.clock = book, provider, clock
        self.live = provider.live

    def packs(self, cur, workspace_id):
        if not self.book.policy(cur, workspace_id): return []
        cur.execute("SELECT id,label,amount_cents,currency,millicredits FROM public.pr_credit_packs WHERE active AND policy_id=%s AND livemode=%s ORDER BY amount_cents,id",(POLICY_VERSION,self.live))
        return [dict(zip(('id','label','amountCents','currency','milliCredits'),row)) for row in cur.fetchall()]

    def prepare_order(self, cur, workspace_id, actor, pack_id, request_id):
        if not self.book.policy(cur,workspace_id): raise AlphaError('This workspace uses its existing plan.',409)
        if not isinstance(request_id,str) or not re.fullmatch('[A-Za-z0-9_-]{16,80}',request_id):
            raise AlphaError('A unique checkout request is required.',400)
        cur.execute('SELECT id::text,pack_id,actor::text,checkout_url,status FROM public.pr_credit_orders WHERE workspace_id=%s AND request_id=%s',(workspace_id,request_id))
        prior=cur.fetchone()
        if prior:
            if prior[1]!=pack_id or prior[2]!=str(actor): raise AlphaError('Checkout request changed.',409)
            if prior[4] in ('expired','failed'): raise AlphaError('This checkout ended without payment. Start a new purchase.',409)
            if prior[4]=='funded': return {'orderId':prior[0],'url':None,'status':'funded','duplicate':True}
            return {'orderId':prior[0],'url':prior[3],'status':prior[4],'duplicate':True}
        cur.execute('SELECT price_id,amount_cents,currency,millicredits FROM public.pr_credit_packs WHERE id=%s AND active AND policy_id=%s AND livemode=%s',(pack_id,POLICY_VERSION,self.live))
        pack=cur.fetchone()
        if not pack: raise AlphaError('This credit pack is not available.',409)
        cur.execute('INSERT INTO public.pr_credit_orders(workspace_id,actor,pack_id,request_id,policy_id,price_id,amount_cents,currency,millicredits,livemode) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id::text',(workspace_id,actor,pack_id,request_id,POLICY_VERSION,*pack,self.live))
        return {'orderId':cur.fetchone()[0],'priceId':pack[0],'url':None,'duplicate':False}

    def attach_checkout(self, cur, workspace_id, order_id, session):
        cur.execute('SELECT session_id FROM public.pr_credit_orders WHERE workspace_id=%s AND id::text=%s FOR UPDATE',(workspace_id,order_id))
        prior=cur.fetchone()
        if not prior or prior[0] not in (None,session['sessionId']): raise AlphaError('Checkout identity changed.',409)
        cur.execute('UPDATE public.pr_credit_orders SET session_id=%s,checkout_url=%s WHERE workspace_id=%s AND id::text=%s',(session['sessionId'],session['url'],workspace_id,order_id))

    def process_webhook(self, cur, signature, body):
        import hashlib
        self.provider.verify_signature(signature,body)
        try: raw=json.loads(body)
        except ValueError as error: raise AlphaError('Invalid credit payment event.',400) from error
        if not credit_related(raw): return None
        fingerprint=hashlib.sha256(body).hexdigest()
        cur.execute("SELECT to_regclass('public.pr_credit_payment_inbox') IS NOT NULL")
        inbox=cur.fetchone()[0]
        try: event=credit_event(raw)
        except (ValueError,TypeError,AttributeError) as error:
            if not inbox: raise AlphaError('Invalid credit payment event.',400) from error
            # A verified event we cannot read is kept for review, not retried until the provider gives up.
            return self._hold(cur,raw,fingerprint,{},f'Unrecognised payment event: {error}')
        if event is None: return None
        cur.execute("SELECT to_regclass('public.pr_credit_orders') IS NOT NULL")
        if not cur.fetchone()[0]:
            if event['operation'] == 'fund': raise AlphaError('Credit schema is not ready; payment remains unapplied.',503)
            return None
        if event['live']!=self.live: raise AlphaError('Payment environment mismatch.',400)
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('credit-event:'+event['eventId'],))
        cur.execute("SELECT outcome,payload_digest FROM public.pr_billing_events WHERE provider='stripe' AND event_id=%s",(event['eventId'],))
        prior=cur.fetchone()
        if not prior and inbox:
            cur.execute('SELECT status,payload_digest FROM public.pr_credit_payment_inbox WHERE event_id=%s',(event['eventId'],))
            prior=cur.fetchone()
        if prior:
            if prior[1]!=fingerprint: raise AlphaError('Payment event changed during replay.',409)
            return {'eventId':event['eventId'],'outcome':'duplicate'}
        payment=event.get('paymentIntentId') or event.get('orderId')
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('credit-payment:'+payment,))
        if inbox: cur.execute('SAVEPOINT credit_event')
        try:
            operation=event['operation']
            if operation=='fund': self._fund(cur,event)
            elif operation in ('expire','fail'): self._close(cur,event)
            elif operation=='dispute': self._dispute(cur,event)
            else: self._refund(cur,event)
            if event.get('paymentIntentId'): self._reconcile(cur,event)
        except AlphaError as error:
            # Business mismatches are kept for review; outages (5xx) still fail so the provider retries.
            if not inbox or error.status>=500: raise
            cur.execute('ROLLBACK TO SAVEPOINT credit_event')
            return self._hold(cur,raw,fingerprint,event,str(error))
        cur.execute("INSERT INTO public.pr_billing_events(provider,event_id,kind,event_at,payload_digest,outcome) VALUES('stripe',%s,%s,to_timestamp(%s),%s,'applied')",(event['eventId'],'credits.'+event['operation'],event['createdAt'],fingerprint))
        return {'eventId':event['eventId'],'outcome':'applied','type':'credits.'+event['operation']}

    def _hold(self, cur, raw, fingerprint, event, reason):
        event_id=raw.get('id') if isinstance(raw.get('id'),str) else None
        if not event_id: raise AlphaError('Invalid credit payment event.',400)
        cur.execute('SELECT payload_digest FROM public.pr_credit_payment_inbox WHERE event_id=%s',(event_id,))
        held=cur.fetchone()
        if held:
            if held[0]!=fingerprint: raise AlphaError('Payment event changed during replay.',409)
            return {'eventId':event_id,'outcome':'duplicate'}
        minimal={k:v for k,v in event.items() if k in ('operation','orderId','sessionId','paymentIntentId','refundId','disputeId','status','withdrawn','amount','currency','workspaceId')}
        cur.execute("INSERT INTO public.pr_credit_payment_inbox(event_id,kind,event_created,livemode,payload_digest,event,status,reason) VALUES(%s,%s,%s,%s,%s,%s::jsonb,'needs_review',%s)",
                    (event_id,str(raw.get('type'))[:80],raw.get('created') if type(raw.get('created')) is int else 0,raw.get('livemode') is True,fingerprint,json.dumps(minimal),reason[:200]))
        return {'eventId':event_id,'outcome':'needs_review','reason':reason[:200]}

    def _fund(self, cur, event):
        cur.execute('SELECT workspace_id::text FROM public.pr_credit_orders WHERE id::text=%s',(event['orderId'],))
        found=cur.fetchone()
        if not found: raise AlphaError('No authorized order matches this payment.',409)
        workspace=found[0]
        if event.get('workspaceId') and event['workspaceId']!=workspace: raise AlphaError('Payment names another workspace than its order.',409)
        self.book.policy(cur,workspace)
        cur.execute('SELECT actor::text,session_id,payment_intent_id,amount_cents,currency,millicredits,livemode,grant_id::text,policy_id FROM public.pr_credit_orders WHERE id::text=%s FOR UPDATE',(event['orderId'],))
        actor,session,payment,cents,currency,milli,live,grant,policy=cur.fetchone()
        if session not in (None,event['sessionId']) or payment not in (None,event['paymentIntentId']) or cents!=event['amount'] or currency!=event['currency'] or live!=event['live'] or policy!=POLICY_VERSION:
            raise AlphaError('Payment does not match the authorized order.',409)
        if grant: return
        funded=self.book.grant(cur,workspace,actor,'credit-order:'+event['orderId'],milli,source='verified-stripe-checkout')
        cur.execute("UPDATE public.pr_credit_orders SET status='funded',session_id=%s,payment_intent_id=%s,grant_id=%s WHERE id::text=%s",(event['sessionId'],event['paymentIntentId'],funded['entryId'],event['orderId']))

    def _close(self, cur, event):
        cur.execute('SELECT status,session_id FROM public.pr_credit_orders WHERE id::text=%s FOR UPDATE',(event['orderId'],))
        found=cur.fetchone()
        if not found: raise AlphaError('No authorized order matches this checkout.',409)
        if found[1] not in (None,event['sessionId']): raise AlphaError('Checkout does not match the authorized order.',409)
        # Money wins: only a still-pending order ends; a funded one keeps its verified payment.
        cur.execute("UPDATE public.pr_credit_orders SET status=%s,closed_at=now() WHERE id::text=%s AND status='pending'",('expired' if event['operation']=='expire' else 'failed',event['orderId']))

    def _dispute(self, cur, event):
        cur.execute('SELECT payment_intent_id,amount_cents,currency,withdrawn,event_created FROM public.pr_credit_disputes WHERE dispute_id=%s FOR UPDATE',(event['disputeId'],))
        prior=cur.fetchone()
        if prior:
            if prior[:3]!=(event['paymentIntentId'],event['amount'],event['currency']): raise AlphaError('Dispute identity changed.',409)
            if prior[4]>event['createdAt']: return
            if prior[4]==event['createdAt'] and prior[3]!=event['withdrawn']: raise AlphaError('Dispute order is ambiguous; reconciliation is required.',409)
        cur.execute('INSERT INTO public.pr_credit_disputes(dispute_id,payment_intent_id,amount_cents,currency,status,withdrawn,event_created) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dispute_id) DO UPDATE SET status=excluded.status,withdrawn=excluded.withdrawn,event_created=excluded.event_created',(event['disputeId'],event['paymentIntentId'],event['amount'],event['currency'],event['status'],event['withdrawn'],event['createdAt']))

    def _refund(self, cur, event):
        cur.execute('SELECT payment_intent_id,amount_cents,currency,status,event_created FROM public.pr_credit_refunds WHERE refund_id=%s FOR UPDATE',(event['refundId'],))
        prior=cur.fetchone()
        if prior:
            if prior[:3]!=(event['paymentIntentId'],event['amount'],event['currency']): raise AlphaError('Refund identity changed.',409)
            if prior[4]>event['createdAt']: return
            if prior[4]==event['createdAt'] and prior[3]!=event['status']: raise AlphaError('Refund order is ambiguous; reconciliation is required.',409)
        cur.execute('INSERT INTO public.pr_credit_refunds(refund_id,payment_intent_id,amount_cents,currency,status,event_created) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(refund_id) DO UPDATE SET status=excluded.status,event_created=excluded.event_created',(event['refundId'],event['paymentIntentId'],event['amount'],event['currency'],event['status'],event['createdAt']))

    def _reconcile(self, cur, event):
        cur.execute('SELECT workspace_id::text FROM public.pr_credit_orders WHERE payment_intent_id=%s',(event['paymentIntentId'],))
        found=cur.fetchone()
        if not found: return self._reconcile_plan_payment(cur,event)  # or a refund ahead of its Checkout webhook
        workspace=found[0]
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(workspace,))
        cur.execute('SELECT id::text,actor::text,grant_id::text,millicredits,amount_cents,currency,reversed_millicredits FROM public.pr_credit_orders WHERE payment_intent_id=%s FOR UPDATE',(event['paymentIntentId'],))
        order,actor,grant,milli,cents,currency,reversed_milli=cur.fetchone()
        if not grant: return
        target=self._take_back(cur,event,workspace,actor,grant,milli,cents,currency,reversed_milli)
        if target is not None:
            cur.execute('UPDATE public.pr_credit_orders SET reversed_millicredits=%s WHERE id::text=%s',(target,order))

    def _reconcile_plan_payment(self, cur, event):
        """A refund or dispute of a monthly plan payment takes back that period's credits the same way."""
        cur.execute("SELECT to_regclass('public.pr_credit_subscription_grants') IS NOT NULL")
        if not cur.fetchone()[0]: return
        cur.execute('SELECT invoice_id,workspace_id::text FROM public.pr_credit_subscription_grants WHERE payment_intent_id=%s AND grant_id IS NOT NULL',(event['paymentIntentId'],))
        found=cur.fetchone()
        if not found: return
        cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(found[1],))
        cur.execute('SELECT grant_id::text,millicredits,amount_cents,currency,reversed_millicredits FROM public.pr_credit_subscription_grants WHERE invoice_id=%s FOR UPDATE',(found[0],))
        grant,milli,cents,currency,reversed_milli=cur.fetchone()
        target=self._take_back(cur,event,found[1],None,grant,milli,cents,currency,reversed_milli)
        if target is not None:
            cur.execute('UPDATE public.pr_credit_subscription_grants SET reversed_millicredits=%s WHERE invoice_id=%s',(target,found[0]))

    def _take_back(self, cur, event, workspace, actor, grant, milli, cents, currency, reversed_milli):
        """Reverses (or restores) credits in proportion to the paid money that is no longer ours."""
        cur.execute("SELECT amount_cents,currency FROM public.pr_credit_refunds WHERE payment_intent_id=%s AND status='succeeded'",(event['paymentIntentId'],))
        refunds=cur.fetchall()
        cur.execute("SELECT to_regclass('public.pr_credit_disputes') IS NOT NULL")
        disputes=[]
        if cur.fetchone()[0]:
            cur.execute('SELECT amount_cents,currency FROM public.pr_credit_disputes WHERE payment_intent_id=%s AND withdrawn',(event['paymentIntentId'],))
            disputes=cur.fetchall()
        if any(row[1]!=currency for row in refunds+disputes): raise AlphaError('Refund or dispute currency mismatch.',409)
        # Money no longer ours (refunded or withdrawn by a dispute) takes back the credits it bought.
        taken=min(cents,sum(row[0] for row in refunds)+sum(row[0] for row in disputes))
        target=refund_credit_amount(milli,cents,taken);delta=target-reversed_milli
        if not delta: return None
        change={'op':'reverse' if delta>0 else 'restore','grantId':grant,'milli':abs(delta)}
        self.book._adjust(cur,workspace,actor,'credit-refund:'+event['eventId'],change)
        self.book.view(cur,workspace)  # Validate projection before committing the adjustment.
        return target
