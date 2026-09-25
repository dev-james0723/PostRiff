"""Stripe-shaped credit funding contracts; synthetic payloads, no network or payments."""
import unittest
try:
    from postriff_phase2.credit_purchases import credit_event, refund_credit_amount
except ImportError:
    credit_event = refund_credit_amount = None

class CreditPurchaseContractTests(unittest.TestCase):
    def event(self, kind, obj, live=False):
        self.assertTrue(callable(credit_event), 'Credit funding parser must exist')
        return credit_event({'id':'evt_fixture','type':kind,'created':1800000000,'livemode':live,'data':{'object':obj}})

    def test_unpaid_checkout_does_not_grant_credits(self):
        obj={'id':'cs_fixture','mode':'payment','payment_status':'unpaid','metadata':{'credit_order_id':'order-fixture'}}
        self.assertIsNone(self.event('checkout.session.completed',obj))

    def test_async_paid_checkout_preserves_payment_and_order_identity(self):
        obj={'id':'cs_fixture','mode':'payment','payment_status':'paid','payment_intent':'pi_fixture','amount_total':1000,'currency':'usd','metadata':{'credit_order_id':'order-fixture'}}
        out=self.event('checkout.session.async_payment_succeeded',obj)
        self.assertEqual((out['operation'],out['orderId'],out['paymentIntentId']),('fund','order-fixture','pi_fixture'))
        self.assertIs(out['live'],False)

    def test_unrelated_checkout_is_ignored(self):
        self.assertIsNone(self.event('checkout.session.completed',{'mode':'subscription','payment_status':'paid'}))

    def test_refund_status_remains_explicit(self):
        for status in ['pending','succeeded','failed']:
            out=self.event('refund.updated',{'id':'re_fixture','payment_intent':'pi_fixture','amount':250,'currency':'usd','status':status})
            self.assertEqual(out['status'],status)

    def test_partial_refunds_round_the_cumulative_amount_only(self):
        self.assertTrue(callable(refund_credit_amount))
        self.assertEqual(refund_credit_amount(1000,3,1),333)
        self.assertEqual(refund_credit_amount(1000,3,2),666)
        self.assertEqual(refund_credit_amount(1000,3,3),1000)
        for refunded in [-1,4,True]:
            with self.assertRaises(ValueError): refund_credit_amount(1000,3,refunded)

    def test_malformed_money_and_missing_payment_identity_are_refused(self):
        obj={'id':'cs_fixture','mode':'payment','payment_status':'paid','amount_total':1000,'currency':'usd','metadata':{'credit_order_id':'order-fixture'}}
        with self.assertRaises(ValueError): self.event('checkout.session.completed',obj)
        with self.assertRaises(ValueError): self.event('checkout.session.completed',{**obj,'payment_intent':'pi_fixture','amount_total':True})

    def test_failed_refund_can_restore_a_prior_reversal_without_new_money(self):
        from postriff_phase2.credit_wallet import project_credit_wallet
        rows=[{'id':'g','credits':{'op':'grant','milli':1000}},
              {'id':'r','credits':{'op':'reverse','grantId':'g','milli':600}},
              {'id':'restored','credits':{'op':'restore','grantId':'g','milli':600}}]
        self.assertEqual(project_credit_wallet(rows,0)['availableMilliCredits'],1000)

    def test_checkout_is_one_time_and_binds_the_server_order(self):
        from postriff_phase2.billing_stripe import StripePaymentProvider
        calls=[]
        def transport(method,url,headers=None,form=None):
            calls.append(form);return {'status':200,'body':{'id':'cs_fixture','url':'https://checkout.stripe.com/c/pay/fixture'}}
        provider=StripePaymentProvider('sk_test_fixture','fixture',transport=transport)
        self.assertTrue(callable(getattr(provider,'create_credit_checkout_session',None)))
        result=provider.create_credit_checkout_session(order_id='order-fixture',workspace_id='workspace-fixture',price_id='price_fixture',customer_email='synthetic@example.invalid',success_url='https://example.invalid/billing',cancel_url='https://example.invalid/billing')
        self.assertEqual(result['sessionId'],'cs_fixture')
        self.assertEqual(calls[0]['mode'],'payment')
        self.assertEqual(calls[0]['metadata[credit_order_id]'],'order-fixture')
        self.assertEqual(calls[0]['payment_intent_data[metadata][credit_order_id]'],'order-fixture')
