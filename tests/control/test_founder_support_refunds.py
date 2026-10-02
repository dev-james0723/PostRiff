"""Disposable tenant boundaries, support durability and zero-network refund recovery."""
import os
import time
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2 import support
from rafii_control import founder_refunds, founder_support, founder_ops, founder_policy
from rafii_control.auth import ControlError


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class SupportRefundPostgresTests(unittest.TestCase):
    def setUp(self):
        from control.test_founder_ops_workspace import OpsWorkspacePostgresTests
        OpsWorkspacePostgresTests.setUp(self)
        import psycopg
        self.connect = lambda: psycopg.connect(self.dsn)
        with self.connect() as db:
            self._created_email_column = not db.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='auth' AND table_name='users' AND column_name='email')").fetchone()[0]
            if self._created_email_column:
                db.execute('ALTER TABLE auth.users ADD COLUMN email text')
            db.execute('UPDATE auth.users SET email=%s WHERE id=%s', ('synthetic@example.test', self.user))
        from postriff_phase2.hosted import PostgresWorkspaceRepository, _membership
        self.service = SimpleNamespace(repository=PostgresWorkspaceRepository(self.connect, lambda token: token),
                                       ideas=SimpleNamespace(_member=_membership), connection_factory=self.connect)
        self.app = SimpleNamespace(queries=SimpleNamespace(store=self.store), runtime=lambda: self.service, consumer=lambda: self.service, flags={})

    def tearDown(self):
        # Tests run as the disposable schema owner and remove only these synthetic
        # requests. The application role has no financial DELETE privilege.
        with self.connect() as db:
            db.execute('DELETE FROM public.pr_founder_refund_dispatches WHERE workspace_id=%s', (self.primary,))
            if getattr(self, '_created_refund_source', False):
                db.execute('DROP TABLE public.pr_credit_refunds')
            if self._created_email_column:
                db.execute('ALTER TABLE auth.users DROP COLUMN email')
        from control.test_founder_ops_workspace import OpsWorkspacePostgresTests
        OpsWorkspacePostgresTests.tearDown(self)

    def request(self, operation, ticket, body):
        return founder_support.operate(self.app, self.principal, {'match': (ticket, operation), 'body': body})

    def test_original_tenant_messages_masked_projection_reply_reveal_and_cas(self):
        request = str(uuid.uuid4())
        body = {'requestId': request, 'category': 'technical', 'message': 'Synthetic private support message synthetic@example.test'}
        created = support.customer(self.service, self.primary, self.user, 'POST', body=body)
        ticket = created['ticket']
        self.assertTrue(support.customer(self.service, self.primary, self.user, 'POST', body=body)['duplicate'])
        listing = founder_support.list_tickets(self.app, self.principal, {})
        self.assertEqual(listing['identityVisibility'], 'masked')
        self.assertNotIn('Synthetic private', str(listing))
        self.assertNotIn('synthetic@example.test', str(listing))
        with self.assertRaises(ControlError):
            self.request('reveal', ticket['id'], {'confirmation': 'YES', 'reasonCode': 'support_investigation'})
        revealed = self.request('reveal', ticket['id'], {'confirmation': 'REVEAL', 'reasonCode': 'support_investigation'})
        self.assertEqual(revealed['messages'][0]['body'], body['message'])
        reply = {'requestId': str(uuid.uuid4()), 'message': 'Synthetic in-app reply', 'revision': ticket['revision']}
        first = self.request('reply', ticket['id'], reply)
        self.assertFalse(first['duplicate'])
        self.assertTrue(self.request('reply', ticket['id'], reply)['duplicate'])
        with self.assertRaises(ControlError):
            self.request('status', ticket['id'], {'revision': ticket['revision'], 'status': 'resolved'})
        self.request('status', ticket['id'], {'revision': first['ticket']['revision'], 'status': 'resolved'})
        read = support.customer(self.service, self.primary, self.user, 'GET', ticket['id'])
        self.assertEqual(len(read['messages']), 2)
        self.assertEqual(read['ticket']['status'], 'resolved')
        with self.connect() as db:
            meta = db.execute("SELECT meta FROM public.pr_audit_events WHERE kind='support.identity.revealed' AND subject=%s", (ticket['id'],)).fetchone()[0]
            self.assertEqual(meta, {'reasonCode': 'support_investigation'})
            db.execute('SET LOCAL ROLE rafii_control_reader')
            with self.assertRaises(Exception):
                db.execute('SELECT body FROM public.pr_support_messages')

    def test_tenant_and_user_isolation_and_internal_exclusion(self):
        with self.assertRaises(AlphaError):
            support.customer(self.service, self.primary, str(uuid.uuid4()), 'GET')
        ops = founder_ops.create_ops(self.app, self.principal, {'mode': 'live'})['workspaceId']
        body = {'requestId': str(uuid.uuid4()), 'category': 'other', 'message': 'Synthetic internal ticket'}
        ticket = support.customer(self.service, ops, self.user, 'POST', body=body)['ticket']
        self.assertNotIn(ticket['id'], str(founder_support.list_tickets(self.app, self.principal, {})))
        with self.assertRaises(ControlError):
            self.request('reveal', ticket['id'], {'confirmation': 'REVEAL', 'reasonCode': 'support_investigation'})
        with self.assertRaises(AlphaError):
            support.customer(self.service, self.primary, self.user, 'GET', ticket['id'])

    def test_durable_defaults_seed_future_slots_once_and_preserve_channel_consent(self):
        from rafii_control.founder_cron import PostgresFounderStore
        app = self.app
        app.founder_store = lambda: PostgresFounderStore(self.store, 'local')
        ops = founder_ops.create_ops(app, self.principal, {'mode': 'live'})['workspaceId']
        settings = founder_policy.policy.defaults()
        self.assertEqual(founder_policy.sync_defaults(app, ops, self.user, settings, time.time()), 'applied')
        self.assertEqual(founder_policy.sync_defaults(app, ops, self.user, settings, time.time()), 'applied')
        with self.connect() as db:
            rows = db.execute('SELECT kind,local_time,weekdays,time_zone,next_at>now() FROM rafii_control.founder_briefing_schedules WHERE operator_id=%s ORDER BY kind', (self.user,)).fetchall()
            self.assertEqual([(r[0],r[1],r[3],r[4]) for r in rows], [('daily','08:30','America/Indiana/Indianapolis',True), ('weekly','09:00','America/Indiana/Indianapolis',True)])
            self.assertEqual(rows[1][2], [0])
            live, channels, budget = db.execute('SELECT live_delivery_enabled,channels,budget_usd_micro_daily FROM rafii_control.founder_contact_policy WHERE operator_id=%s', (self.user,)).fetchone()
            self.assertEqual((live, channels, budget), (False, [], 50_000_000))

    def test_refund_lost_response_recovers_by_read_and_never_repeats_post(self):
        state = {'posts': 0, 'gets': 0}
        action = str(uuid.uuid4())
        params = {'workspaceId': self.primary, 'paymentIntentId': 'pi_synthetic', 'amountMinor': 500, 'currency': 'usd', 'reasonCode': 'other'}
        payment_snapshot = {'source':'credit_order','sourceId':'synthetic','paidMinor':1000,'refundedMinor':0,'refunds':0,'disputed':False,'currency':'usd','status':'funded','livemode':False}
        receipt = {'id':'re_synthetic','payment_intent':'pi_synthetic','amount':500,'currency':'usd','status':'pending'}
        def submit(**kwargs):
            state['posts'] += 1
            raise TimeoutError('synthetic accepted-but-lost response')
        def reconcile(**kwargs):
            state['gets'] += 1
            return receipt
        @contextmanager
        def transaction():
            with self.connect() as db, db.cursor() as cur:
                yield cur
        adapter = SimpleNamespace(service=SimpleNamespace(billing=SimpleNamespace(provider=SimpleNamespace(id='stripe',live=False,create_refund=submit,find_refund=reconcile))), transaction=transaction)
        row = {'params': params,'id':action,'operator_id':self.user}
        # The tiny missing source table stands in for the verified existing
        # payment snapshot. This test proves the real dispatch transaction only.
        with self.connect() as db:
            self._created_refund_source = db.execute("SELECT to_regclass('public.pr_credit_refunds') IS NULL").fetchone()[0]
            db.execute('CREATE TABLE IF NOT EXISTS public.pr_credit_refunds(refund_id text,status text)')
        with patch.object(founder_refunds.operator_actions, 'payment_snapshot', return_value=payment_snapshot):
            with self.assertRaises(ControlError):
                founder_refunds.execute(adapter, row, lambda value: self.assertEqual(value['dispatchHoldsMinor'],0))
            recovered = founder_refunds.execute(adapter, row, lambda value: self.fail('claimed action must not re-check or re-dispatch'))
            self.assertEqual(recovered['providerStatus'], 'pending')
            self.assertFalse(recovered['refundSucceeded'])
            self.assertTrue(founder_refunds.execute(adapter, row, lambda value: None)['duplicate'])
            with self.connect() as db, db.cursor() as cur:
                self.assertEqual(founder_refunds.snapshot(cur, params)['dispatchHoldsMinor'], 500)
        self.assertEqual(state, {'posts': 1, 'gets': 1})
