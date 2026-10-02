"""Task10: actual disposable PG17, recording checkout + HMAC events only.

Seeded packs remain inactive. Active packs below are isolated synthetic fixtures,
not commercial approval or Stripe qualification. Run via the owned PG harness.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import unittest
import uuid

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.credit_meter import POLICY_VERSION, V2_POLICY_VERSION
from postriff_phase2.hosted import HostedWorkspaceService

ROOT = Path(__file__).resolve().parents[2]
TEST_PG_PORT = int(os.environ.get('POSTRIFF_TEST_PG_PORT', '55438'))
if not 1024 <= TEST_PG_PORT <= 65535:
    raise ValueError('Disposable PostgreSQL port must be between 1024 and 65535.')
DSN = f'host=127.0.0.1 port={TEST_PG_PORT} dbname=postgres'
NOW = int(time.time())
SECRET = 'task10-synthetic-hmac-only'
BASE = {'writingBatches': 10, 'mediaCredits': 1, 'members': 2,
        'connectedAccounts': 3, 'storageMb': 200}


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class CreditPurchasePolicyV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == TEST_PG_PORT
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql',
                         '022_credit_payment_lifecycle.sql', '048_pricing_credit_catalog_v2.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())
            for version, (key, policy, status) in enumerate((
                ('candidate', POLICY_VERSION, 'active'), ('v2', V2_POLICY_VERSION, 'active'),
                ('inactive', V2_POLICY_VERSION, 'proposed'), ('unsupported', 'future-policy', 'active'),
                ('allowance', None, 'active')), 970):
                ent = {**BASE, **({'creditPolicy': policy} if policy else {})}
                db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) "
                           "VALUES(%s,'studio',%s,'Synthetic Task10',0,%s,%s::jsonb)",
                           ('task10-' + key, version, status, json.dumps(ent)))
            for key, policy, live in (('candidate', POLICY_VERSION, False), ('v2', V2_POLICY_VERSION, False),
                                      ('v2-live', V2_POLICY_VERSION, True), ('unsupported', 'future-policy', False)):
                db.execute('INSERT INTO pr_credit_packs VALUES(%s,%s,%s,%s,1500,\'usd\',1000000,%s,true)',
                           ('task10-' + key, 'Synthetic ' + key, policy, 'price_task10_' + key, live))

    def setUp(self):
        self.actor = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
        def verify(token):
            if token != 'fixture':
                raise AlphaError('Denied', 403)
            return self.actor
        verify.session_id = lambda token, principal: 'task10-' + self.actor
        verify.auth_time = lambda token, principal: NOW
        self.verify = verify
        self.calls = []
        def transport(method, url, headers=None, form=None):
            self.calls.append(form)
            sid = 'cs_' + form['metadata[credit_order_id]']
            return {'status': 200, 'body': {'id': sid, 'url': 'https://checkout.stripe.com/c/pay/' + sid}}
        self.provider = StripePaymentProvider('sk_test_fixture', SECRET, transport=transport, clock=lambda: NOW)
        self.service = self.make_service(credits_enabled=True, credit_purchases_enabled=True)
        self.wid = self.service.bootstrap('fixture', 'studio')['workspaceId']
        with connection() as db:
            self.service.ledger.ensure_entitlement(db.cursor(), self.wid, None)
        self.set_policy('v2')

    def make_service(self, **flags):
        return HostedWorkspaceService(connection, self.verify, clock=lambda: NOW, billing_provider=self.provider,
                                      public_base_url='https://example.invalid',
                                      email_lookup=lambda actor: 'synthetic@example.invalid', **flags)

    def set_policy(self, key):
        with connection() as db:
            db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s',
                       ('task10-' + key, self.wid))

    def checkout(self, pack='task10-v2', request='task10-request-00001', *, success=True):
        # Preserve the throttle in source; clear only this disposable fixture's bucket.
        with connection() as db:
            bucket = hashlib.sha256(('credit-checkout:' + self.wid).encode()).hexdigest()
            db.execute('DELETE FROM pr_auth_throttle WHERE bucket=%s', (bucket,))
        try:
            return self.service.billing_credit_checkout(self.wid, 'fixture', pack, request)
        except AlphaError as error:
            if success:
                self.fail('Expected same-policy synthetic checkout refused: ' + str(error))
            raise

    def event(self, obj, event_id=None, kind='checkout.session.completed', live=False):
        raw = json.dumps({'id': event_id or 'evt_' + uuid.uuid4().hex, 'type': kind, 'created': NOW,
                          'livemode': live, 'data': {'object': obj}}).encode()
        signature = hmac.new(SECRET.encode(), f'{NOW}.'.encode() + raw, hashlib.sha256).hexdigest()
        return f't={NOW},v1={signature}', raw

    def payment(self, order, **extra):
        return {'id': order['sessionId'], 'mode': 'payment', 'payment_status': 'paid',
                'payment_intent': 'pi_' + order['orderId'], 'amount_total': 1500, 'currency': 'usd',
                'client_reference_id': self.wid, 'metadata': {'credit_order_id': order['orderId']}, **extra}

    def grant_rows(self):
        with connection() as db:
            return db.execute("SELECT id::text,meta->'credits' FROM pr_usage_ledger "
                              "WHERE workspace_id=%s AND meta->'credits'->>'op'='grant' ORDER BY id",
                              (self.wid,)).fetchall()

    def test_seeded_v2_packs_exact_inactive_blank_price(self):
        with connection() as db:
            packs = db.execute("SELECT id,policy_id,amount_cents,currency,millicredits,livemode,active,price_id "
                               "FROM pr_credit_packs WHERE id LIKE 'credits-%-v2' ORDER BY id").fetchall()
            self.assertEqual(packs, [
                ('credits-1000-v2', V2_POLICY_VERSION, 1500, 'usd', 1000000, False, False, None),
                ('credits-2000-v2', V2_POLICY_VERSION, 2900, 'usd', 2000000, False, False, None)])
            self.assertEqual(db.execute("SELECT status,new_checkout_enabled FROM pr_plan_terms WHERE id='creator-v1'").fetchone(),
                             ('proposed', False))

    def test_defaults_and_both_enable_flags_are_required(self):
        for flags in ({}, {'credits_enabled': True}, {'credit_purchases_enabled': True},
                      {'credits_enabled': False, 'credit_purchases_enabled': True}):
            with self.subTest(flags=flags):
                service = self.make_service(**flags)
                self.assertEqual(service.billing_credit_packs(self.wid, 'fixture'), {'available': False, 'packs': []})
                with self.assertRaises(AlphaError) as caught:
                    service.billing_credit_checkout(self.wid, 'fixture', 'task10-v2', 'task10-disabled-0001')
                self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.calls, [])

    def test_flag_alone_cannot_sell_inactive_packs_or_bleed_candidate_catalog(self):
        with connection() as db, db.transaction(force_rollback=True):
            db.execute("UPDATE pr_credit_packs SET active=false WHERE id='task10-v2'")
            # Use the same transaction for the catalog read; candidate remains active.
            self.assertEqual(self.service.credit_purchases.packs(db.cursor(), self.wid), [])
        for pack in ('credits-1000-v2', 'credits-2000-v2', 'task10-candidate', 'task10-v2-live', 'task10-unsupported'):
            with self.subTest(pack=pack), self.assertRaises(AlphaError) as caught:
                self.checkout(pack, success=False)
            self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.calls, [])

    def test_active_catalog_is_exact_current_policy_and_provider_mode(self):
        for key, expected in (('candidate', 'task10-candidate'), ('v2', 'task10-v2')):
            self.set_policy(key)
            packs = self.service.billing_credit_packs(self.wid, 'fixture')
            self.assertTrue(packs['available'])
            self.assertEqual([p['id'] for p in packs['packs']], [expected])
            self.assertEqual(set(packs['packs'][0]), {'id', 'label', 'amountCents', 'currency', 'milliCredits'})

    def test_v2_order_locks_server_pack_fields_and_rejects_foreign_pack(self):
        order = self.checkout()
        with connection() as db:
            stored = db.execute('SELECT policy_id,price_id,amount_cents,currency,millicredits,livemode '
                                'FROM pr_credit_orders WHERE id=%s', (order['orderId'],)).fetchone()
        self.assertEqual(stored, (V2_POLICY_VERSION, 'price_task10_v2', 1500, 'usd', 1000000, False))
        self.assertEqual(self.calls[0]['line_items[0][price]'], 'price_task10_v2')
        self.assertEqual(self.checkout()['orderId'], order['orderId'])
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(AlphaError) as caught:
            self.checkout('task10-candidate', 'task10-other-request', success=False)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.grant_rows(), [])

    def test_verified_v2_funding_uses_locked_order_not_payload_or_edited_pack(self):
        order = self.checkout()
        with connection() as db, db.transaction(force_rollback=True):
            db.execute("UPDATE pr_credit_packs SET policy_id=%s,amount_cents=1,millicredits=1,price_id='price_changed' "
                       "WHERE id='task10-v2'", (POLICY_VERSION,))
            # process_webhook is transactional, so this proves the changed pack isn't consulted.
            obj = self.payment(order, metadata={'credit_order_id': order['orderId'], 'policy_id': POLICY_VERSION,
                                               'price_id': 'price_client', 'millicredits': 1, 'expiresAt': NOW + 1})
            result = self.service.credit_purchases.process_webhook(db.cursor(), *self.event(obj))
            self.assertEqual(result['outcome'], 'applied')
            row = db.execute("SELECT u.meta->'credits' FROM pr_credit_orders o JOIN pr_usage_ledger u ON u.id=o.grant_id "
                             "WHERE o.id=%s", (order['orderId'],)).fetchone()[0]
            self.assertEqual(row, {'op': 'grant', 'milli': 1000000, 'expiresAt': None,
                                   'policy': V2_POLICY_VERSION, 'source': 'verified-stripe-checkout'})

    def test_late_orders_keep_both_locked_policies_across_transition_and_replay(self):
        for source, target, pack, policy in (
            ('candidate', 'v2', 'task10-candidate', POLICY_VERSION),
            ('v2', 'candidate', 'task10-v2', V2_POLICY_VERSION)):
            with self.subTest(source=source):
                self.set_policy(source)
                before = self.grant_rows()
                order = self.checkout(pack, 'task10-transition-' + source)
                self.set_policy(target)
                signature, body = self.event(self.payment(order))
                self.assertEqual(self.service.billing_webhook(signature, body)['outcome'], 'applied')
                self.assertEqual(self.service.billing_webhook(signature, body)['outcome'], 'duplicate')
                self.assertEqual(self.service.billing_webhook(*self.event(self.payment(order),
                                  kind='checkout.session.async_payment_succeeded'))['outcome'], 'applied')
                after = self.grant_rows()
                self.assertEqual(len(after), len(before) + 1)
                self.assertTrue(all(row in after for row in before))
                with connection() as db:
                    locked = db.execute("SELECT o.policy_id,u.meta->'credits' FROM pr_credit_orders o "
                                        "JOIN pr_usage_ledger u ON u.id=o.grant_id WHERE o.id=%s", (order['orderId'],)).fetchone()
                self.assertEqual(locked[0], policy)
                self.assertEqual(locked[1]['policy'], policy)
                self.assertEqual(locked[1]['source'], 'verified-stripe-checkout')
                self.assertIsNone(locked[1]['expiresAt'])

    def test_current_active_guard_blocks_new_and_duplicate_funding(self):
        self.set_policy('candidate')  # Existing base can fund this order for the guard assertion.
        paid = self.checkout('task10-candidate')
        self.assertEqual(self.service.billing_webhook(*self.event(self.payment(paid)))['outcome'], 'applied')
        pending = self.checkout('task10-candidate', 'task10-guard-pending')
        before = self.grant_rows()
        for current in ('allowance', 'inactive', 'unsupported'):
            self.set_policy(current)
            for order in (paid, pending):
                with self.subTest(current=current, funded=order == paid):
                    result = self.service.billing_webhook(*self.event(self.payment(order)))
                    self.assertEqual(result['outcome'], 'needs_review')
                    self.assertTrue(result['reason'])
            self.assertEqual(self.grant_rows(), before)

    def test_new_orders_refuse_allowance_inactive_and_unsupported_current_policy(self):
        for key in ('allowance', 'inactive', 'unsupported'):
            self.set_policy(key)
            with self.subTest(key=key), self.assertRaises(AlphaError) as caught:
                self.checkout(success=False)
            self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.calls, [])

    def test_unsupported_locked_order_is_held_without_grant(self):
        self.set_policy('candidate')
        order = self.checkout('task10-candidate')
        with connection() as db:
            db.execute("UPDATE pr_credit_orders SET policy_id='future-policy' WHERE id=%s", (order['orderId'],))
        self.assertEqual(self.service.billing_webhook(*self.event(self.payment(order)))['outcome'], 'needs_review')
        self.assertEqual(self.grant_rows(), [])

    def test_signature_replay_and_order_bindings_remain_enforced(self):
        self.set_policy('candidate')
        order = self.checkout('task10-candidate')
        payment = self.payment(order)
        signature, body = self.event(payment)
        with self.assertRaises(AlphaError) as caught:
            self.service.billing_webhook(signature, body + b' ')
        self.assertEqual(caught.exception.status, 401)
        for change in ({'amount_total': 1}, {'currency': 'eur'}, {'id': 'cs_other'},
                       {'client_reference_id': str(uuid.uuid4())}):
            with self.subTest(change=change):
                sig, raw = self.event({**payment, **change})
                self.assertEqual(self.service.billing_webhook(sig, raw)['outcome'], 'needs_review')
                self.assertEqual(self.service.billing_webhook(sig, raw)['outcome'], 'duplicate')
        self.assertEqual(self.grant_rows(), [])
        self.assertEqual(self.service.billing_webhook(signature, body)['outcome'], 'applied')
        changed = json.loads(body); changed['data']['object']['amount_total'] = 1
        with self.assertRaises(AlphaError) as caught:
            self.service.billing_webhook(*self.event(changed['data']['object'], changed['id']))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.service.billing_webhook(*self.event({**payment, 'payment_intent': 'pi_other'}))['outcome'], 'needs_review')
        with self.assertRaises(AlphaError) as caught:
            self.service.billing_webhook(*self.event(payment, live=True))
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(len(self.grant_rows()), 1)

    def test_non_owner_cannot_list_or_open_purchases(self):
        with connection() as db:
            db.execute("UPDATE pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",
                       (self.wid, self.actor))
        self.assertEqual(self.service.billing_credit_packs(self.wid, 'fixture'), {'available': False, 'packs': []})
        with self.assertRaises(AlphaError) as caught:
            self.checkout(success=False)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
