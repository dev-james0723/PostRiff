"""Real disposable PostgreSQL; synthetic identities/messages, zero provider calls."""
import json
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from rafii_control import founder_activation, founder_ops, founder_sources
from rafii_control.auth import ControlError
from postriff_phase2 import ai_call_events, product_events, telemetry_journal
from postriff_phase2.notifications import cutover


class ReadinessTests(unittest.TestCase):
    def test_flags_alone_never_mean_activation_and_all_24_are_present(self):
        values = {flag: '1' for _, _, flags, _, _ in founder_activation.FEATURES for flag in flags}
        rows = founder_activation.feature_manifest(values)
        self.assertEqual([r['id'] for r in rows], ['F%02d' % n for n in range(1, 25)])
        self.assertTrue(all(r['activationProof']=='not_verified' for r in rows))
        self.assertIn('ops_workspace_not_ready', next(r for r in rows if r['id']=='F05')['blockers'])
        self.assertIn('durable_cutover_and_delivery_proof_required', next(r for r in rows if r['id']=='F10')['blockers'])
        self.assertEqual(founder_activation.telemetry(SimpleNamespace()), {'dataState': 'unavailable', 'reason': 'source_unavailable', 'writers': []})


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class IntegrityPostgresTests(unittest.TestCase):
    def setUp(self):
        from control.test_founder_ops_workspace import OpsWorkspacePostgresTests
        OpsWorkspacePostgresTests.setUp(self)
        import psycopg
        self.connect = lambda: psycopg.connect(self.dsn)
        product_events.reset()
        ai_call_events._STATE.update(disabled_until=0, logged=False)

    def tearDown(self):
        from control.test_founder_ops_workspace import OpsWorkspacePostgresTests
        OpsWorkspacePostgresTests.tearDown(self)
        product_events.reset()
        ai_call_events._STATE.update(disabled_until=0, logged=False)
        with self.connect() as db:
            db.execute('DELETE FROM public.pr_delivery_cutovers')
            db.execute("DELETE FROM public.pr_notification_provider_events WHERE provider IN ('resend_dispatch','webpush_dispatch')")

    def test_gap_survives_failed_writer_suspension_and_recovery_preserves_times(self):
        import psycopg
        # Fault the writer's own INSERT, not the domain transaction or journal.
        with self.connect() as db, db.cursor() as cur:
            class FaultCursor:
                rowcount = 0
                def execute(self, sql, args=()):
                    if sql.startswith('INSERT INTO public.pr_product_events'):
                        raise psycopg.errors.UndefinedTable('synthetic missing table')
                    return cur.execute(sql, args)
            self.assertEqual(product_events.record_many(FaultCursor(), self.primary, self.user, [('voice.created', 'synthetic-voice', 1, {'prompt': 'never retain this'})]), 0)
            self.assertEqual(product_events.record_many(cur, self.primary, self.user, [('brand.created', 'synthetic-brand', 1, {})]), 0)
            db.commit()
        app = SimpleNamespace(queries=SimpleNamespace(store=self.store))
        health = founder_activation.telemetry(app)
        product = next(r for r in health['writers'] if r['writer']=='product_events')
        self.assertEqual((product['attempted'], product['missing'], product['failed_batches'], product['suspended_batches']), (2, 2, 1, 1))
        with self.connect() as db:
            self.assertEqual(founder_sources.writer_health(db)['product_writer'][:2], ('partial', 'reconciliation_required'))
        with self.connect() as db, db.cursor() as cur:
            cur.execute("SELECT min(at),meta::text FROM public.pr_audit_events WHERE workspace_id=%s AND kind='telemetry.product_events' GROUP BY meta ORDER BY min(at)", (self.primary,))
            journal = cur.fetchall()
            self.assertNotIn('never retain this', str(journal))
            self.assertEqual(telemetry_journal.recover(cur)['inserted'], 2)
            db.commit()
        with self.connect() as db, db.cursor() as cur:
            self.assertEqual(telemetry_journal.recover(cur)['inserted'], 0)
            cur.execute("SELECT occurred_at,recorded_at FROM public.pr_product_events WHERE workspace_id=%s AND event='voice.created'", (self.primary,))
            occurred, observed = cur.fetchone()
            self.assertEqual(occurred, journal[0][0])
            self.assertGreaterEqual(observed, occurred)
        health = founder_activation.telemetry(app)
        self.assertEqual(next(r for r in health['writers'] if r['writer']=='product_events')['missing'], None)
        with self.connect() as db:
            self.assertEqual(founder_sources.writer_health(db)['product_writer'][:2], ('measured', 'qualified'))

    def test_recovery_does_not_restore_revoked_actor_and_reader_never_reads_journal_rows(self):
        with self.connect() as db, db.cursor() as cur:
            row = product_events.row(self.primary, self.user, 'draft.created', 'synthetic-draft', 1, {})
            telemetry_journal.record(cur, 'product_events', [row], state='failed')
            cur.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (self.primary, self.user))
            result = telemetry_journal.recover(cur)
            self.assertEqual((result['inserted'], result['discarded']), (0, 1))
        with self.assertRaises(Exception):
            with self.store.transaction(read=True) as con:
                con.execute('SELECT meta FROM public.pr_audit_events')
        with self.store.transaction(read=True) as con:
            columns = con.execute('SELECT * FROM rafii_control.business_telemetry_health LIMIT 1').fetchone()
            self.assertNotIn('meta', columns)
            self.assertNotIn('rows', columns)

    def policy(self, now, *, cap=1, audience='founder', allowed=None, channel='email'):
        with self.connect() as db:
            db.execute("INSERT INTO public.pr_delivery_cutovers(audience,channel,revision,mode,not_before,approved_at,operator_id,recipient_user_ids,max_messages,template_version,approval_ref) "
                       "VALUES(%s,%s,1,'canary_only',to_timestamp(%s),now(),%s,%s,%s,'synthetic-v1','synthetic-approval')",
                       (audience, channel, now-10, self.user, [allowed or self.user], cap))

    def delivery(self, key='synthetic-email-1', user=None):
        return ([{'id': str(uuid.uuid4()), 'userId': user or self.user}], [{'type': 'founder.test_notice', 'occurredAt': time.time()}],
                {'idempotencyKey': key, 'templateVersion': 'synthetic-v1', 'to': 'owner@synthetic.invalid', 'text': 'synthetic canary'})

    def test_cutover_blocks_absence_old_events_other_recipient_and_customer_scope(self):
        now = time.time()
        rows, contexts, message = self.delivery()
        self.assertEqual(cutover.admit(self.connect, rows, contexts, message, now=now)['detail'], 'delivery_cutover_not_approved')
        self.policy(now)
        self.assertEqual(cutover.admit(self.connect, rows, [{**contexts[0], 'occurredAt': now-20}], message, now=now)['detail'], 'delivery_before_cutover')
        self.assertEqual(cutover.admit(self.connect, [{**rows[0], 'userId': str(uuid.uuid4())}], contexts, message, now=now)['detail'], 'delivery_outside_canary_scope')
        self.assertEqual(cutover.admit(self.connect, rows, [{**contexts[0], 'type': 'billing.payment_failed'}], message, now=now)['detail'], 'delivery_cutover_not_approved')

    def test_dispatch_marker_survives_crash_and_quota_race_never_exceeds_cap(self):
        now = time.time()
        self.policy(now)
        inputs = [self.delivery('synthetic-email-' + str(i)) for i in range(2)]
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(lambda item: cutover.admit(self.connect, *item, now=now), inputs))
        self.assertEqual(outcomes.count(None), 1)
        index = outcomes.index(None)
        admitted = inputs[index]
        self.assertIsNone(cutover.admit(self.connect, *admitted, now=now+1))
        self.assertEqual(cutover.admit(self.connect, *admitted, now=now+cutover.WINDOW)['state'], 'uncertain')
        self.assertEqual(cutover.admit(self.connect, admitted[0], admitted[1], {**admitted[2], 'text': 'changed'}, now=now+2)['state'], 'uncertain')
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_notification_provider_events WHERE provider='resend_dispatch'").fetchone()[0], 1)

    def test_readiness_cannot_hide_database_failure_as_no_ops(self):
        app = SimpleNamespace(queries=SimpleNamespace(store=None), flags={}, runtime=None)
        result = founder_activation.readiness(app, self.principal, {})
        self.assertEqual(result['ops']['reason'], 'SOURCE_UNAVAILABLE')
        self.assertFalse(result['releaseVerified'])

    def test_push_counts_device_dispatches_and_never_replays_uncertainty(self):
        now = time.time()
        self.policy(now, channel='push', cap=3)
        for i in range(3):
            inputs = self.delivery('synthetic-device-' + str(i))
            self.assertIsNone(cutover.admit(self.connect, *inputs, now=now, channel='push'))
            self.assertEqual(cutover.admit(self.connect, *inputs, now=now+1, channel='push')['state'], 'uncertain')
        self.assertEqual(cutover.admit(self.connect, *self.delivery('synthetic-device-4'), now=now, channel='push')['detail'], 'delivery_cutover_cap_reached')

    def test_budget_failure_rolls_back_cutover_admission(self):
        self.policy(time.time())
        def refused(cur):
            raise RuntimeError('synthetic budget denied')
        self.assertEqual(cutover.admit(self.connect, *self.delivery(), now=time.time(), reserve=refused)['state'], 'config')
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_notification_provider_events WHERE provider='resend_dispatch'").fetchone()[0], 0)

    def test_worker_push_byte_payload_counts_devices_and_does_not_resend(self):
        from rafii_control import founder_notifications
        from postriff_phase2.notifications.delivery import DeliveryWorker
        from postriff_phase2.notifications.push import RecordingPushTransport
        founder_notifications.register_events()
        now = time.time()
        self.policy(now, channel='push', cap=3)
        transport = RecordingPushTransport()
        transport.requires_cutover = True
        worker = DeliveryWorker(self.connect, push_transport=transport, vault=object(), clock=lambda: now)
        worker._subscriptions = lambda user: [{'id':str(uuid.uuid4()),'endpoint':'https://fcm.googleapis.com/fcm/send/synthetic'} for _ in range(2)]
        subscriptions = worker._subscriptions(self.user)
        worker._subscriptions = lambda user: subscriptions
        worker.render = lambda row, ctx: {'templateVersion':'synthetic-v1','subject':'Synthetic canary'}
        row = {'id':str(uuid.uuid4()),'userId':self.user,'key':'synthetic-push-message-1','eventId':'synthetic-event-1'}
        ctx = {'type':'founder.briefing_ready','occurredAt':now,'payload':{'href':'/app/founder'}}
        self.assertEqual(worker.send_push(row,ctx)['state'], 'sent')
        self.assertEqual(len(transport.sent), 2)
        self.assertEqual(worker.send_push(row,ctx)['state'], 'uncertain')
        self.assertEqual(len(transport.sent), 2)
        self.assertEqual(worker.send_push({**row,'key':'synthetic-push-message-2'},ctx)['state'], 'sent')
        self.assertEqual(len(transport.sent), 3)

    def test_financial_history_is_immutable_and_retains_original_rows(self):
        from postriff_phase2.billing import Ledger
        with self.connect() as db, db.cursor() as cur:
            value = Ledger().reserve(cur, self.primary, self.user, 'tool', 0, 'synthetic-history-' + str(uuid.uuid4()), charge_batch=False)
            record = cur.execute("SELECT record FROM public.pr_financial_history WHERE source_table='pr_usage_ledger' AND record->>'id'=%s AND operation='INSERT'", (value['reservationId'],)).fetchone()[0]
            self.assertEqual(record['workspace_id'], self.primary)
            cur.execute('DELETE FROM public.pr_usage_ledger WHERE id=%s', (value['reservationId'],))
            versions = cur.execute("SELECT operation FROM public.pr_financial_history WHERE record->>'id'=%s", (value['reservationId'],)).fetchall()
            self.assertEqual({r[0] for r in versions}, {'INSERT', 'UPDATE', 'DELETE'})
            self.assertEqual(len(versions), 3)
        for sql in ('DELETE FROM public.pr_financial_history', "UPDATE public.pr_financial_history SET operation='DELETE'"):
            with self.assertRaises(Exception):
                with self.connect() as db:
                    db.execute(sql)
        with self.assertRaises(Exception):
            with self.store.transaction(read=True) as con:
                con.execute('SELECT record FROM public.pr_financial_history')
