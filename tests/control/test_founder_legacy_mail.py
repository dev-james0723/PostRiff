"""Original-source account mail, local PostgreSQL, encrypted payloads and fake transport."""
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch

from postriff_phase2.billing import Ledger
from postriff_phase2.email import Mailer
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.notifications import legacy_outbox, webhooks
from rafii_control import founder_ops


class RecordingTransport:
    requires_cutover = True
    def __init__(self): self.sent = []; self.uncertain = False
    def send(self, message):
        self.sent.append(message)
        if self.uncertain: raise TimeoutError('synthetic response lost')
        return {'id': 'synthetic-resend-' + str(len(self.sent))}


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable PostgreSQL required')
class LegacyMailPostgresTests(unittest.TestCase):
    def setUp(self):
        from control.test_founder_ops_workspace import OpsWorkspacePostgresTests
        OpsWorkspacePostgresTests.setUp(self)
        import psycopg
        self.connect = lambda: psycopg.connect(self.dsn)
        self.now = time.time()
        with self.connect() as db:
            self.added_email = not db.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='auth' AND table_name='users' AND column_name='email')").fetchone()[0]
            if self.added_email: db.execute('ALTER TABLE auth.users ADD COLUMN email text')
            db.execute('UPDATE auth.users SET email=%s WHERE id=%s', ('founder@synthetic.invalid', self.user))
            db.execute('UPDATE public.pr_workspaces SET created_at=to_timestamp(%s) WHERE id=%s', (self.now-1, self.primary))
        app = OpsWorkspacePostgresTests.app(self)
        self.ops = founder_ops.create_ops(app, self.principal, {'mode': 'live'})['workspaceId']
        self.transport = RecordingTransport()
        self.mailer = Mailer(self.transport, 'Rafii <noreply@synthetic.invalid>', 'https://synthetic.invalid')
        self.vault = CredentialVault(CredentialVault.generate_key())
        values = {'POSTRIFF_ENVIRONMENT': 'local', 'RAFII_FOUNDER_EMAIL_COST_CEILING_USD_MICRO': '100',
                  'RAFII_FOUNDER_EMAIL_COST_QUALIFICATION_REF': 'synthetic-provider-ceiling'}
        self.outbox = legacy_outbox.LegacyMailOutbox(self.connect, self.mailer, self.vault, values, Ledger(), clock=lambda: self.now)
        self.mailer.enqueue_legacy = self.outbox.enqueue

    def tearDown(self):
        with self.connect() as db:
            db.execute("DELETE FROM public.pr_delivery_cutovers WHERE operator_id=%s", (self.user,))
            db.execute('DELETE FROM public.pr_transactional_mail WHERE user_id=%s', (self.user,))
            db.execute("DELETE FROM public.pr_notification_provider_events WHERE event_id LIKE 'legacy-%%' OR event_id LIKE 'synthetic-legacy-%%'")
            if self.added_email: db.execute('ALTER TABLE auth.users DROP COLUMN email')
        from control.test_founder_ops_workspace import OpsWorkspacePostgresTests
        OpsWorkspacePostgresTests.tearDown(self)

    def approve(self, *, before=None, recipients=None, cap=3):
        with self.connect() as db:
            db.execute('INSERT INTO public.pr_delivery_cutovers(audience,channel,revision,mode,not_before,approved_at,operator_id,recipient_user_ids,max_messages,template_version,approval_ref) '
                       "VALUES('customer','email',1,'canary_only',to_timestamp(%s),now(),%s,%s,%s,%s,'synthetic-legacy-approval')",
                       (self.now-10 if before is None else before, self.user, [self.user] if recipients is None else recipients, cap, legacy_outbox.VERSION))

    def queue(self):
        return self.mailer.welcome('founder@synthetic.invalid', 'https://synthetic.invalid/app')

    def rows(self):
        with self.connect() as db:
            return db.execute('SELECT id::text,status,provider_ref,payload_cipher,semantic_key,failure_code FROM public.pr_transactional_mail WHERE user_id=%s', (self.user,)).fetchall()

    def test_encrypted_deduped_queue_requires_live_original_source_and_never_sends(self):
        with patch('postriff_phase2.email._notifications_v2', return_value=True):
            self.assertTrue(self.queue()['queued']); self.assertTrue(self.queue()['queued'])
            self.assertTrue(self.mailer.welcome('founder@synthetic.invalid', 'https://synthetic.invalid/changed')['queued'])
            self.assertEqual(self.mailer.new_device('founder@synthetic.invalid', 'device', self.now, 'https://synthetic.invalid/app')['reason'], 'routed_to_notifications_v2')
        rows = self.rows()
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0][1], 'queued')
        self.assertNotIn('founder@synthetic.invalid', rows[0][3])
        self.assertEqual(self.transport.sent, [])
        with self.connect() as db:
            db.execute('UPDATE public.pr_profiles SET deleted_at=now() WHERE user_id=%s', (self.user,))
        self.assertFalse(self.queue()['queued'])
        self.assertEqual(self.outbox.tick()['counts'], {'suppressed': 1})
        self.assertEqual(self.transport.sent, [])

    def test_old_event_before_cutover_precedes_dispatch_and_creates_no_budget_hold(self):
        self.queue(); self.approve(before=self.now+1)
        self.assertEqual(self.outbox.tick()['counts'], {'suppressed': 1})
        self.assertEqual(self.transport.sent, [])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s', (self.ops,)).fetchone()[0], 0)

    def test_owner_recipient_scope_and_current_opt_out_are_rechecked(self):
        for condition in ('different_recipient', 'opt_out'):
            with self.subTest(condition=condition):
                with self.connect() as db:
                    db.execute('DELETE FROM public.pr_delivery_cutovers WHERE operator_id=%s', (self.user,))
                    db.execute('DELETE FROM public.pr_transactional_mail WHERE user_id=%s', (self.user,))
                    if condition == 'opt_out':
                        db.execute("INSERT INTO public.pr_notification_preferences(user_id,scope_key,category,email_unsubscribed) VALUES(%s,'global','all',true)", (self.user,))
                self.approve(recipients=[str(uuid.uuid4())] if condition == 'different_recipient' else None)
                self.queue()
                self.assertEqual(self.outbox.tick()['counts'], {'suppressed': 1})
                self.assertEqual(self.transport.sent, [])
                self.assertEqual(self.rows()[0][-1], 'delivery_outside_canary_scope' if condition == 'different_recipient' else 'email_opt_out')

    def test_shared_founder_cost_cap_blocks_egress_without_invented_actual_cost(self):
        self.approve(); self.queue()
        with self.connect() as db, db.cursor() as cur:
            Ledger().reserve(cur, self.ops, self.user, 'tool', 49_999_999, 'synthetic-preexisting-hold', charge_batch=False)
        self.assertEqual(self.outbox.tick()['counts'], {'suppressed': 1})
        self.assertEqual(self.transport.sent, [])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s', (self.ops,)).fetchone()[0], 1)

    def test_all_three_account_templates_have_original_sources_and_a_shared_canary_limit(self):
        import hashlib
        token = 'synthetic-invitation-token'
        with self.connect() as db:
            db.execute('INSERT INTO public.pr_invitations(workspace_id,email,role,token_hash,created_by,created_at,expires_at) '
                       "VALUES(%s,'founder@synthetic.invalid','viewer',%s,%s,to_timestamp(%s),to_timestamp(%s))",
                       (self.primary, hashlib.sha256(token.encode()).hexdigest(), self.user, self.now-1, self.now+300))
            db.execute('UPDATE public.pr_trials SET expires_at=to_timestamp(%s) WHERE user_id=%s', (self.now-1, self.user))
        self.approve(cap=1)
        self.assertTrue(self.queue()['queued'])
        self.assertEqual(self.outbox.tick()['counts'], {'provider_accepted': 1})
        self.assertTrue(self.mailer.invitation('founder@synthetic.invalid', 'Synthetic operator', 'viewer',
                            'https://synthetic.invalid/invitations/' + token, self.now+300)['queued'])
        self.assertTrue(self.mailer.trial_ended('founder@synthetic.invalid', 'https://synthetic.invalid/pricing', 'Synthetic export note')['queued'])
        self.assertEqual(self.outbox.tick()['counts'], {'suppressed': 2})
        self.assertEqual(len(self.transport.sent), 1)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s', (self.ops,)).fetchone()[0], 1)

    def test_provider_acceptance_signed_delivery_dedupe_and_nonregression(self):
        self.approve(); self.queue()
        self.assertEqual(self.outbox.tick()['counts'], {'provider_accepted': 1}, [row[-1] for row in self.rows()])
        row = self.rows()[0]
        self.assertEqual(self.transport.sent[0]['replyTo'], 'jamesau0723@gmail.com')
        with self.connect() as db:
            ledger = db.execute('SELECT meta,actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s', (self.ops,)).fetchone()
            self.assertEqual(ledger[0]['costCenter'], 'founder_ops'); self.assertIsNone(ledger[1])
        event = {'type': 'email.delivered', 'created_at': '2026-10-02T12:00:00Z',
                 'data': {'email_id': row[2], 'tags': {'legacy_delivery_id': row[0]}}}
        body = json.dumps(event).encode()
        secret = 'whsec_' + __import__('base64').b64encode(b'synthetic-only-secret').decode()
        signed = webhooks.sign_svix(secret, 'synthetic-legacy-event', int(self.now), body)
        with self.connect() as db, db.cursor() as cur:
            verified = webhooks.verify_svix(secret, signed, body, now=self.now)
            self.assertEqual(webhooks.ingest(cur, 'synthetic-legacy-event', verified, body)['outcome'], 'applied')
            self.assertEqual(webhooks.ingest(cur, 'synthetic-legacy-event', verified, body)['outcome'], 'duplicate')
            self.assertEqual(legacy_outbox.ingest(cur, row[0], row[2], 'failed'), 'ignored')
        self.assertEqual(self.rows()[0][1], 'delivered')
        self.outbox.tick(); self.queue(); self.outbox.tick()
        self.assertEqual(len(self.transport.sent), 1)

    def test_uncertain_dispatch_or_lost_claim_never_replays(self):
        self.approve(); self.queue(); self.transport.uncertain = True
        self.assertEqual(self.outbox.tick()['counts'], {'uncertain': 1})
        self.outbox.tick(); self.queue(); self.outbox.tick()
        self.assertEqual(len(self.transport.sent), 1)
        row = self.rows()[0]
        with self.connect() as db:
            db.execute("UPDATE public.pr_transactional_mail SET status='dispatching',lease_until=now()-interval '1 second' WHERE id=%s", (row[0],))
        self.outbox.tick(); self.assertEqual(self.rows()[0][1], 'uncertain')
        self.assertEqual(len(self.transport.sent), 1)

    def test_reader_cannot_read_payload_or_queue_or_apply_provider_callback(self):
        self.queue(); row = self.rows()[0]
        with self.connect() as db, db.cursor() as cur:
            self.assertIsNone(legacy_outbox.ingest(cur, row[0], 'unqualified-ref', 'delivered'))
        import psycopg
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.store.transaction(read=True) as db:
                db.execute('SELECT payload_cipher FROM public.pr_transactional_mail')
        with self.connect() as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (self.primary,))
        self.assertEqual(self.rows(), [])
