"""Stripe-shaped credit funding contracts; synthetic payloads, no network or payments."""
import unittest
from unittest.mock import Mock
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


class CreditPurchasePolicyContractTests(unittest.TestCase):
    """Recording cursors only; PG fixtures separately verify persistence and SQL."""
    def purchases(self, current='credits-v2-2026-09-28'):
        from postriff_phase2.credit_purchases import CreditPurchases
        from postriff_phase2.credit_wallet import CreditBook
        book = CreditBook()
        book.policy = Mock(return_value=current)
        book._adjust = Mock(return_value={'entryId': 'grant-fixture'})
        return CreditPurchases(book, Mock(live=False)), book

    def test_catalog_binds_current_server_policy(self):
        for policy in ('credits-candidate-2026-09-23-v1', 'credits-v2-2026-09-28'):
            with self.subTest(policy=policy):
                purchases, book = self.purchases(policy)
                cur = Mock()
                cur.fetchall.return_value = [('same-policy-pack', 'Synthetic', 1500, 'usd', 1000000)]
                self.assertEqual(purchases.packs(cur, 'workspace')[0]['id'], 'same-policy-pack')
                self.assertEqual(cur.execute.call_args.args[1], (policy, False))
                book._adjust.assert_not_called()

    def test_new_order_locks_current_server_policy_and_pack_fields(self):
        for policy in ('credits-candidate-2026-09-23-v1', 'credits-v2-2026-09-28'):
            with self.subTest(policy=policy):
                purchases, book = self.purchases(policy)
                cur = Mock()
                cur.fetchone.side_effect = [None, ('price_fixture', 1500, 'usd', 1000000), ('order-fixture',)]
                purchases.prepare_order(cur, 'workspace', 'actor', 'same-policy-pack', 'unique-request-001')
                lookup, insert = cur.execute.call_args_list[-2:]
                self.assertEqual(lookup.args[1], ('same-policy-pack', policy, False))
                self.assertEqual(insert.args[1], ('workspace', 'actor', 'same-policy-pack', 'unique-request-001',
                                                policy, 'price_fixture', 1500, 'usd', 1000000, False))
                book._adjust.assert_not_called()

    def fund(self, purchases, policy, grant=None, **extra):
        cur = Mock()
        cur.fetchone.side_effect = [('workspace',), ('actor', 'cs_fixture', 'pi_fixture', 1500, 'usd',
                                                     1000000, False, grant, policy)]
        event = {'orderId': 'order-fixture', 'workspaceId': 'workspace', 'sessionId': 'cs_fixture',
                 'paymentIntentId': 'pi_fixture', 'amount': 1500, 'currency': 'usd', 'live': False, **extra}
        purchases._fund(cur, event)
        return cur

    def test_verified_funding_preserves_each_locked_policy_and_has_no_expiry(self):
        from postriff_alpha.domain import AlphaError
        policies = ('credits-candidate-2026-09-23-v1', 'credits-v2-2026-09-28')
        for current in policies:
            for locked in policies:
                with self.subTest(current=current, locked=locked):
                    purchases, book = self.purchases(current)
                    try:
                        cur = self.fund(purchases, locked, policyId='client-policy', expiresAt=1, milliCredits=1)
                    except AlphaError as error:
                        self.fail('Supported locked order funding refused: ' + str(error))
                    self.assertEqual(book._adjust.call_args.args,
                                     (cur, 'workspace', 'actor', 'credit-order:order-fixture',
                                      {'op': 'grant', 'milli': 1000000, 'expiresAt': None,
                                       'policy': locked, 'source': 'verified-stripe-checkout'}))

    def test_current_no_credit_policy_blocks_funded_replay_before_locked_order_read(self):
        from postriff_alpha.domain import AlphaError
        purchases, book = self.purchases(None)
        cur = Mock()
        cur.fetchone.side_effect = [('workspace',), ('actor', 'cs_fixture', 'pi_fixture', 1500, 'usd',
                                                     1000000, False, 'existing-grant', 'credits-candidate-2026-09-23-v1')]
        with self.assertRaises(AlphaError) as caught:
            purchases._fund(cur, {'orderId': 'order-fixture', 'sessionId': 'cs_fixture',
                                 'paymentIntentId': 'pi_fixture', 'amount': 1500, 'currency': 'usd', 'live': False})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(cur.fetchone.call_count, 1)
        book._adjust.assert_not_called()

    def test_unsupported_locked_policy_never_grants(self):
        from postriff_alpha.domain import AlphaError
        purchases, book = self.purchases()
        with self.assertRaises(AlphaError) as caught:
            self.fund(purchases, 'future-policy')
        self.assertEqual(caught.exception.status, 409)
        book._adjust.assert_not_called()

    def test_locked_payment_fields_are_checked_even_on_grant_replay(self):
        from postriff_alpha.domain import AlphaError
        for change in ({'sessionId': 'cs_other'}, {'paymentIntentId': 'pi_other'}, {'amount': 1},
                       {'currency': 'eur'}, {'live': True}, {'workspaceId': 'other-workspace'}):
            with self.subTest(change=change):
                purchases, book = self.purchases()
                with self.assertRaises(AlphaError):
                    self.fund(purchases, 'credits-v2-2026-09-28', 'existing-grant', **change)
                book._adjust.assert_not_called()
