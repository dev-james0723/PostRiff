"""Migrations 057 + 063 on a disposable PostgreSQL: billing instrumentation tables, founder projections, the Stripe webhook
writing real rows (and surviving a missing table), and the revenue metrics through the reader role.

Skipped without RAFII_CONTROL_TEST_DSN (scripts/rafii_control_pg.py applies every founder migration twice). Each test seeds
its own workspaces and removes every billing row it wrote, so the aggregate metrics see only its fixtures."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import unittest
import uuid

import psycopg

from postriff_phase2 import billing as billing_module
from postriff_phase2.billing import Billing, Ledger
from postriff_phase2.billing_stripe import StripePaymentProvider
from rafii_control import founder_cron, founder_metrics_revenue as revenue, live_metrics
from rafii_control.auth import CAPABILITIES
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

TZ = 'America/Indiana/Indianapolis'
SECRET = 'whsec_pg_fixture'
SIGNED_AT = 1_790_000_000
AUGUST = dict(start='2026-08-01T04:00:00Z', end='2026-09-01T04:00:00Z', timeZone=TZ)
VIEWS = ('business_subscription_events', 'business_invoices', 'business_subscription_snapshots_v2', 'business_credit_entries')


def epoch(text): return int(datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp())


def stripe_body(kind, obj, event_id, created):
    body = json.dumps({'id': event_id, 'type': kind, 'created': created, 'livemode': False, 'data': {'object': obj}}).encode()
    return f"t={SIGNED_AT},v1={hmac.new(SECRET.encode(), f'{SIGNED_AT}.'.encode() + body, hashlib.sha256).hexdigest()}", body


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderRevenueMigrationTests(unittest.TestCase):
    def connect(self, role=None, autocommit=True):
        con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], autocommit=autocommit, prepare_threshold=None)
        if role: con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        owner = self.connect()
        if owner.execute("SELECT to_regclass('rafii_control.business_subscription_events') IS NULL").fetchone()[0]:
            self.skipTest('migrations 057/063 not applied by this harness')
        billing_module._RECORDING['off_until'].clear()
        self.workspaces = {}
        for name in ('w1', 'w2', 'w3', 'w4', 'w5', 'w6', 'hook'):
            user = str(uuid.uuid4())
            owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
            self.workspaces[name] = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        owner.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,environment) VALUES(%s,'internal','revenue test','local')", (self.workspaces['w3'],))
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': sorted(CAPABILITIES)}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}

    def tearDown(self):
        billing_module._RECORDING['off_until'].clear()
        with psycopg.connect(self.dsn, autocommit=True) as con:
            ids = list(getattr(self, 'workspaces', {}).values())
            con.execute("DELETE FROM public.pr_subscription_events WHERE workspace_id = ANY(%s::uuid[]) OR event_id LIKE 'evt_rev_%%'", (ids,))
            con.execute("DELETE FROM public.pr_invoices WHERE workspace_id = ANY(%s::uuid[]) OR invoice_id LIKE 'in_rev_%%'", (ids,))
            con.execute('DELETE FROM public.pr_subscription_snapshots WHERE workspace_id = ANY(%s::uuid[]) OR day >= %s::date', (ids, '2030-01-01'))
            con.execute('DELETE FROM public.pr_usage_ledger WHERE workspace_id = ANY(%s::uuid[])', (ids,))
            con.execute('DELETE FROM public.pr_billing_events WHERE event_id LIKE %s', ('evt_rev_%',))
            con.execute('DELETE FROM public.pr_subscriptions WHERE workspace_id = ANY(%s::uuid[])', (ids,))
            con.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id = ANY(%s::uuid[])', (ids,))

    def service(self, now):
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        return QueryService(store, clock=lambda: now)

    def query(self, service, metric, group_by=(), interval=AUGUST, filters=()):
        return service.metric_query(dict(metricIds=[metric], interval=dict(interval), groupBy=list(group_by), filters=list(filters), comparison='none', limit=1000),
                                    self.principal, str(uuid.uuid4()))

    def event(self, owner, name, sub, at, status, unit=None, *, interval='month', count=1, discount=0, trial_end=None, terms='studio-v1', kind='customer.subscription.updated'):
        owner.execute('INSERT INTO public.pr_subscription_events(provider,event_id,event_type,workspace_id,provider_subscription_id,event_at,applied,new_status,new_terms,"interval",'
                      'interval_count,unit_amount_minor,quantity,usage_type,currency,discount_minor,trial_end,recorded_at) VALUES(%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                      ('stripe', 'evt_rev_' + uuid.uuid4().hex[:16], kind, self.workspaces[name], sub, at, status, terms, interval if unit is not None else None, count if unit is not None else None,
                       unit, 1 if unit is not None else None, 'licensed' if unit is not None else None, 'usd', discount if unit is not None else None, trial_end, '2026-01-01T00:00:00Z'))

    def subscription(self, owner, name, status, sub=None, terms='studio-v1', provider='stripe'):
        owner.execute('INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,provider_subscription_id,status) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(workspace_id) DO UPDATE '
                      'SET plan_terms_id=excluded.plan_terms_id,provider=excluded.provider,provider_subscription_id=excluded.provider_subscription_id,status=excluded.status',
                      (self.workspaces[name], terms, provider, sub, status))

    def seed_book(self, owner):
        """W1 2900 → 5900 (expansion), W2 annual 34800 less 10% → 2610/month then cancelled (churn), W5 new after a trial,
        W6 4900 past_due (delinquent, unchanged), W3 internal (excluded), W4 a paid subscription without any event (unknown)."""
        self.event(owner, 'w1', 'sub_rev_a', '2026-03-01T00:00:00Z', 'active', 2900, kind='customer.subscription.created')
        self.event(owner, 'w1', 'sub_rev_a', '2026-08-10T00:00:00Z', 'active', 5900)
        self.event(owner, 'w2', 'sub_rev_b', '2026-03-05T00:00:00Z', 'active', 34800, interval='year', discount=3480, kind='customer.subscription.created')
        self.event(owner, 'w2', 'sub_rev_b', '2026-08-20T00:00:00Z', 'cancelled', kind='customer.subscription.deleted')
        self.event(owner, 'w5', 'sub_rev_c', '2026-08-15T00:00:00Z', 'active', 1900, trial_end='2026-08-30T12:00:00Z', kind='customer.subscription.created')
        self.event(owner, 'w6', 'sub_rev_e', '2026-04-01T00:00:00Z', 'active', 4900, kind='customer.subscription.created')
        self.event(owner, 'w6', 'sub_rev_e', '2026-08-25T00:00:00Z', 'past_due', 4900)
        self.event(owner, 'w3', 'sub_rev_d', '2026-03-01T00:00:00Z', 'active', 9900, kind='customer.subscription.created')
        self.subscription(owner, 'w4', 'active')

    def test_tables_views_grants_and_rls(self):
        owner = self.connect()
        for table in ('pr_subscription_events', 'pr_invoices'):
            flags = owner.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='public' AND relname=%s", (table,)).fetchone()
            self.assertEqual(tuple(flags), (True, True), table)
            self.assertEqual(owner.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename=%s AND policyname='service_only'", (table,)).fetchone()[0], 1)
            delete_rule = owner.execute("SELECT confdeltype FROM pg_constraint WHERE conrelid=%s::regclass AND contype='f' AND confrelid='public.pr_workspaces'::regclass", ('public.' + table,)).fetchone()[0]
            self.assertEqual(delete_rule, 'n', 'financial rows survive account deletion with the workspace reference set null')
            for role in ('anon', 'authenticated', 'rafii_control_reader'):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.connect(role).execute(f'SELECT * FROM public.{table} LIMIT 1')
            self.connect('service_role').execute(f'SELECT * FROM public.{table} LIMIT 1')
        columns = {row[0] for row in owner.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_subscription_snapshots'")}
        self.assertTrue({'mrr_minor', 'currency', 'interval', 'interval_count'} <= columns)
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',false)")
        for view in VIEWS:
            with self.subTest(view=view):
                row = owner.execute("SELECT pg_get_userbyid(c.relowner), c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relname=%s AND c.relkind='v'", (view,)).fetchone()
                self.assertEqual(row[0], 'rafii_control_business_projection')
                self.assertIn('security_barrier=true', row[1])
                reader.execute(f'SELECT * FROM rafii_control.{view} LIMIT 1').fetchall()
                for role in ('anon', 'authenticated', 'service_role'):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.connect(role).execute(f'SELECT * FROM rafii_control.{view} LIMIT 1')
        p0 = [row[0] for row in owner.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='rafii_control' AND table_name='business_subscription_snapshots' ORDER BY ordinal_position")]
        self.assertEqual(p0, ['day', 'workspaceId', 'planTermsId', 'plan', 'status', 'provider'], 'the 054 view is unchanged, so 054 stays re-applicable')

    def test_057_before_054_still_gets_the_snapshot_columns_from_063(self):
        """Production applies 057 (public) before the owner-approved 054 creates pr_subscription_snapshots, so 057's column
        ALTERs are no-ops there; 063, applied after 054, must add the four columns. Replayed in one transaction that is rolled
        back, so the shared database is untouched. Only 054's snapshot-table block runs here: re-running all of 054 after 056
        would narrow the capability constraints other tests' operator rows rely on."""
        root = Path(__file__).resolve().parents[2] / 'migrations/postriff'

        def script(name):
            return '\n'.join(line for line in (root / name).read_text().splitlines() if line.strip().lower() not in ('begin;', 'commit;'))
        p054 = (root / '054_rafii_control_founder_views.sql').read_text()
        start = p054.index('create table if not exists public.pr_subscription_snapshots')
        snapshot_block = p054[start:p054.index('do $$ declare n text; begin', start)]
        wanted = {'mrr_minor', 'currency', 'interval', 'interval_count'}
        con = psycopg.connect(self.dsn, prepare_threshold=None)
        try:
            def columns(table, schema='public'):
                return {row[0] for row in con.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s', (schema, table))}
            con.execute('DROP TABLE public.pr_subscription_snapshots CASCADE')
            con.execute(script('057_founder_billing_events.sql'))
            self.assertIsNone(con.execute("SELECT to_regclass('public.pr_subscription_snapshots')").fetchone()[0], '057 never creates the 054 table')
            con.execute(snapshot_block)
            self.assertEqual(columns('pr_subscription_snapshots') & wanted, set(), '054 creates the table without the MRR columns')
            con.execute(script('063_founder_revenue_views.sql'))
            self.assertTrue(wanted <= columns('pr_subscription_snapshots'), '063 adds them when 057 ran first')
            self.assertTrue({'mrrMinor', 'currency', 'interval', 'intervalCount'} <= columns('business_subscription_snapshots_v2', 'rafii_control'))
            con.execute(script('063_founder_revenue_views.sql'))   # and re-applying 063 stays safe
        finally:
            con.rollback()
            con.close()
        owner = self.connect()
        self.assertTrue(wanted <= {row[0] for row in owner.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_subscription_snapshots'")})

    def test_stripe_webhooks_record_events_and_invoices(self):
        provider = StripePaymentProvider('sk_test_pg', SECRET, clock=lambda: SIGNED_AT)
        workspace = self.workspaces['hook']
        t0, t1 = epoch('2026-05-01T00:00:00Z'), epoch('2026-06-01T00:00:00Z')

        def sub(unit, terms, status='active'):
            return {'id': 'sub_rev_hook', 'customer': 'cus_rev', 'status': status, 'metadata': {'workspace_id': workspace, 'plan_terms_id': terms},
                    'items': {'data': [{'price': {'id': 'price_rev', 'unit_amount': unit, 'currency': 'usd', 'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'licensed'}},
                                        'quantity': 1, 'current_period_end': t1 + 86400 * 30}]}}

        def inv(invoice_id, status, paid, terms):
            return {'id': invoice_id, 'customer': 'cus_rev', 'subscription': 'sub_rev_hook', 'status': status, 'amount_due': 3900, 'amount_paid': paid, 'currency': 'usd',
                    'billing_reason': 'subscription_cycle', 'payment_intent': 'pi_' + invoice_id, 'subscription_details': {'metadata': {'workspace_id': workspace, 'plan_terms_id': terms}},
                    'lines': {'data': [{'period': {'start': t1, 'end': t1 + 86400 * 30}}]}}

        events = [('customer.subscription.created', sub(1900, 'studio-v1'), 'evt_rev_w1', t0), ('invoice.paid', dict(inv('in_rev_w1', 'paid', 1900, 'studio-v1'), amount_due=1900), 'evt_rev_w2', t0 + 60),
                  ('customer.subscription.updated', sub(3900, 'assist-v1'), 'evt_rev_w3', t1), ('customer.subscription.updated', sub(1900, 'studio-v1', 'past_due'), 'evt_rev_w4', t0 - 100),
                  ('invoice.payment_failed', inv('in_rev_w2', 'open', 0, 'assist-v1'), 'evt_rev_w5', t1 + 60), ('invoice.paid', inv('in_rev_w2', 'paid', 3900, 'assist-v1'), 'evt_rev_w6', t1 + 120),
                  ('invoice.payment_failed', inv('in_rev_w2', 'open', 0, 'assist-v1'), 'evt_rev_w7', t1 + 90), ('customer.subscription.created', sub(1900, 'studio-v1'), 'evt_rev_w1', t0)]
        outcomes = []
        for kind, obj, event_id, created in events:
            with psycopg.connect(self.dsn, prepare_threshold=None) as db, db.cursor() as cur:
                signature, body = stripe_body(kind, obj, event_id, created)
                outcomes.append(Billing(provider=provider, ledger=Ledger(), clock=lambda: SIGNED_AT).process_webhook(cur, signature, body)['outcome'])
        self.assertEqual(outcomes, ['applied', 'applied', 'applied', 'stale', 'applied', 'applied', 'stale', 'duplicate'])
        owner = self.connect()
        rows = {row[0]: row[1:] for row in owner.execute('SELECT event_id,applied,prior_status,new_status,prior_terms,new_terms,unit_amount_minor,"interval",currency FROM public.pr_subscription_events '
                                                          'WHERE workspace_id=%s', (workspace,))}
        self.assertEqual(set(rows), {'evt_rev_w1', 'evt_rev_w2', 'evt_rev_w3', 'evt_rev_w4', 'evt_rev_w5', 'evt_rev_w6', 'evt_rev_w7'})
        self.assertEqual(rows['evt_rev_w1'], (True, None, 'active', None, 'studio-v1', 1900, 'month', 'usd'))
        self.assertEqual(rows['evt_rev_w3'], (True, 'active', 'active', 'studio-v1', 'assist-v1', 3900, 'month', 'usd'))
        self.assertEqual(rows['evt_rev_w4'][:3], (False, None, 'past_due'))
        self.assertEqual(rows['evt_rev_w5'][2], 'past_due')
        invoices = {row[0]: row[1:] for row in owner.execute('SELECT invoice_id,status,amount_paid,event_id,workspace_id::text FROM public.pr_invoices WHERE invoice_id LIKE %s', ('in_rev_w%',))}
        self.assertEqual(invoices['in_rev_w1'], ('paid', 1900, 'evt_rev_w2', workspace))
        self.assertEqual(invoices['in_rev_w2'], ('paid', 3900, 'evt_rev_w6', workspace), 'a late payment_failed never reopens a paid invoice')
        self.assertEqual(owner.execute('SELECT status,plan_terms_id FROM public.pr_subscriptions WHERE workspace_id=%s', (workspace,)).fetchone(), ('active', 'assist-v1'))
        july = dict(start='2026-06-01T04:00:00Z', end='2026-07-01T04:00:00Z', timeZone=TZ)
        rows = self.query(self.service(datetime(2026, 7, 2, tzinfo=timezone.utc)), 'mrr', ['currency', 'plan'], july)['rows']
        row = next(row for row in rows if row['dimensions']['plan'] == 'Studio Assist')
        self.assertEqual((row['value'], row['currency'], row['dimensions']['plan']), (3900, 'USD', 'Studio Assist'))

    def test_webhook_succeeds_when_the_billing_event_table_is_missing(self):
        owner = self.connect()
        workspace = self.workspaces['hook']
        provider = StripePaymentProvider('sk_test_pg', SECRET, clock=lambda: SIGNED_AT)
        obj = {'id': 'sub_rev_missing', 'status': 'active', 'metadata': {'workspace_id': workspace, 'plan_terms_id': 'studio-v1'},
               'items': {'data': [{'price': {'id': 'p', 'unit_amount': 1900, 'currency': 'usd', 'recurring': {'interval': 'month'}}, 'quantity': 1}]}}
        owner.execute('ALTER TABLE public.pr_subscription_events RENAME TO pr_subscription_events_hidden')
        try:
            with psycopg.connect(self.dsn, prepare_threshold=None) as db, db.cursor() as cur:
                signature, body = stripe_body('customer.subscription.created', obj, 'evt_rev_missing', epoch('2026-05-01T00:00:00Z'))
                result = Billing(provider=provider, ledger=Ledger(), clock=lambda: SIGNED_AT).process_webhook(cur, signature, body)
        finally:
            owner.execute('ALTER TABLE public.pr_subscription_events_hidden RENAME TO pr_subscription_events')
            billing_module._RECORDING['off_until'].clear()
        self.assertEqual(result['outcome'], 'applied')
        self.assertEqual(owner.execute('SELECT status,provider_subscription_id FROM public.pr_subscriptions WHERE workspace_id=%s', (workspace,)).fetchone(), ('active', 'sub_rev_missing'))
        self.assertEqual(owner.execute("SELECT outcome FROM public.pr_billing_events WHERE event_id='evt_rev_missing'").fetchone()[0], 'applied')

    def test_mrr_delinquent_bridge_and_churn_through_the_reader(self):
        owner = self.connect()
        self.seed_book(owner)
        service = self.service(datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
        mrr = self.query(service, 'mrr', ['currency'])['rows']
        usd = next(row for row in mrr if row['currency'] == 'USD')
        self.assertEqual(usd['value'], 5900 + 1900 + 4900, 'W2 cancelled, W3 internal excluded, W5 out of trial')
        self.assertGreaterEqual(sum(row['coverage']['unknown'] for row in mrr), 1, 'W4 is paid with no billing event: unknown, never its list price')
        self.assertEqual(usd['dataState'], 'partial')
        self.assertEqual(usd['collectingSince'], '2026-01-01T00:00:00Z')
        window = dict(start='2026-08-28T04:00:00Z', end='2026-09-01T04:00:00Z', timeZone=TZ)
        series = [(row['dimensions']['window'], row['value']) for row in self.query(service, 'mrr', ['currency', 'window'], window)['rows'] if row['currency'] == 'USD']
        self.assertEqual(series, [('2026-08-28', 10800), ('2026-08-29', 10800), ('2026-08-30', 12700), ('2026-08-31', 12700)])
        self.assertEqual(self.query(service, 'delinquent_mrr', ['currency'])['rows'][0]['value'], 4900)
        bridge = {row['dimensions']['movement']: row for row in self.query(service, 'mrr_movements', ['currency', 'movement'])['rows']}
        self.assertEqual({name: row['value'] for name, row in bridge.items()},
                         dict(opening=2900 + 2610 + 4900, new=1900, expansion=3000, reactivation=0, contraction=0, churn=-2610, closing=12700))
        self.assertTrue(all(row['dataState'] == 'measured' for row in bridge.values()))
        churn = self.query(service, 'logo_churn')['rows'][0]
        self.assertEqual((churn['coverage']['numerator'], churn['coverage']['denominator']), (1, 3))
        self.assertAlmostEqual(churn['value'], 1 / 3)
        recent = self.service(datetime(2026, 1, 20, tzinfo=timezone.utc))
        early = self.query(recent, 'mrr_movements', ['currency', 'movement'], dict(start='2026-01-01T05:00:00Z', end='2026-01-15T05:00:00Z', timeZone=TZ))['rows'][0]
        self.assertEqual(early['reason'], 'insufficient_history')

    def test_daily_snapshot_records_mrr_and_the_forecast_reads_it(self):
        owner = self.connect()
        self.seed_book(owner)
        self.subscription(owner, 'w1', 'active', 'sub_rev_a')
        self.subscription(owner, 'w2', 'cancelled', 'sub_rev_b')
        consumer = type('Consumer', (), {'connection_factory': staticmethod(lambda: psycopg.connect(self.dsn, prepare_threshold=None))})()
        now = datetime(2031, 1, 15, 17, tzinfo=timezone.utc).timestamp()
        result = founder_cron.subscription_snapshot(consumer, now)
        self.assertEqual((result['status'], result['day'], result['mrr']), ('ok', '2031-01-15', True))
        snap = {row[0]: row[1:] for row in owner.execute('SELECT workspace_id::text,mrr_minor,currency,"interval",interval_count FROM public.pr_subscription_snapshots WHERE day=%s', ('2031-01-15',))}
        self.assertEqual(snap[self.workspaces['w1']], (5900, 'usd', 'month', 1))
        self.assertEqual(snap[self.workspaces['w2']], (0, 'usd', 'year', 1))
        self.assertEqual(snap[self.workspaces['w4']], (None, None, None, None), 'no billing event: unknown, not the list price')
        self.assertTrue(founder_cron.subscription_snapshot(consumer, now)['existing'])
        start = datetime(2032, 1, 1).date()
        for offset in range(60):
            owner.execute('INSERT INTO public.pr_subscription_snapshots(day,workspace_id,plan_terms_id,status,provider,mrr_minor,currency,"interval",interval_count) '
                          "VALUES(%s,%s,'studio-v1','active','stripe',%s,'usd','month',1)", (start + timedelta(days=offset), self.workspaces['w1'], 1000 + 10 * offset))
        service = self.service(datetime(2032, 3, 5, 12, tzinfo=timezone.utc))
        rows = self.query(service, 'mrr_forecast', ['currency', 'window'], dict(start='2032-03-10T05:00:00Z', end='2032-03-12T05:00:00Z', timeZone=TZ))['rows']
        self.assertEqual([(row['dimensions']['window'], row['value']) for row in rows], [('2032-03-10', 1690), ('2032-03-11', 1700)])
        self.assertEqual(rows[0]['measures']['basis'], 'scenario')

    def test_cash_collected_v2_dedupes_grants_against_paid_invoices(self):
        owner = self.connect()
        w1 = self.workspaces['w1']
        created = []
        if owner.execute("SELECT to_regclass('rafii_control.business_payments_v2') IS NULL").fetchone()[0]:
            # The harness has no purchase schema (021/022): stand-in projections with the 054 column names, removed after the test.
            owner.execute('CREATE VIEW rafii_control.business_payments_v2 AS SELECT * FROM (VALUES (\'o1\',%s::text,1000::bigint,\'USD\',\'funded\',true,\'pi_o1\',\'2026-08-05T00:00:00Z\'::timestamptz))'
                          ' v(id,"workspaceId","amountMinor",currency,status,livemode,"paymentIntentId",at)'.replace('%s', "'" + w1 + "'"))
            created.append('business_payments_v2')
            if owner.execute("SELECT to_regclass('rafii_control.business_subscription_grants') IS NULL").fetchone()[0]:
                owner.execute('CREATE VIEW rafii_control.business_subscription_grants AS SELECT * FROM (VALUES (\'in_rev_x\',\'{w}\',\'sub_x\',\'studio-v1\',\'subscription_cycle\','
                              'NULL::timestamptz,NULL::timestamptz,2500::bigint,\'USD\',true,\'2026-08-06T00:00:00Z\'::timestamptz), (\'in_rev_y\',\'{w}\',\'sub_x\',\'studio-v1\',\'subscription_cycle\','
                              'NULL::timestamptz,NULL::timestamptz,700::bigint,\'USD\',true,\'2026-08-07T00:00:00Z\'::timestamptz)) v("invoiceId","workspaceId","subscriptionId","planTermsId",'
                              '"billingReason","periodStart","periodEnd","amountMinor",currency,livemode,"recordedAt")'.replace('{w}', w1))
                created.append('business_subscription_grants')
            for view in created: owner.execute(f'GRANT SELECT ON rafii_control.{view} TO rafii_control_reader')
        for invoice_id, status, paid, livemode in (('in_rev_x', 'paid', 2500, True), ('in_rev_z', 'open', 0, True), ('in_rev_t', 'paid', 4000, False)):
            owner.execute("INSERT INTO public.pr_invoices(invoice_id,provider,workspace_id,amount_due,amount_paid,currency,status,livemode,event_id,event_at) "
                          "VALUES(%s,'stripe',%s,%s,%s,'usd',%s,%s,%s,'2026-08-06T00:00:00Z')", (invoice_id, w1, paid or 2500, paid, status, livemode, 'evt_rev_' + invoice_id))
        previous = live_metrics.SPECS['cash_collected']
        try:
            live_metrics.SPECS['cash_collected'] = live_metrics.CASH_COLLECTED_V2
            rows = self.query(self.service(datetime(2026, 10, 1, tzinfo=timezone.utc)), 'cash_collected', ['currency', 'payment_type'])['rows']
        finally:
            live_metrics.SPECS['cash_collected'] = previous
            for view in created: owner.execute(f'DROP VIEW IF EXISTS rafii_control.{view}')
        values = {row['dimensions']['payment_type']: row['value'] for row in rows if row['currency'] == 'USD'}
        if created:
            self.assertEqual(values, {'top_up': 1000, 'subscription_invoice': 2500 + 700}, 'in_rev_x counted once; open and test-mode invoices excluded')
        else:
            self.assertGreaterEqual(values.get('subscription_invoice', 0), 2500)

    def test_credit_metrics_read_the_ledger_through_the_wallet_projection(self):
        owner = self.connect()
        w1 = self.workspaces['w1']
        far = datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()
        grant = owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,unit,cost_state,idempotency_key,meta,at) VALUES(%s,'adjust','action','credit','actual','rev:grant',%s::jsonb,"
                              "'2026-08-02T00:00:00Z') RETURNING id::text", (w1, json.dumps({'credits': {'op': 'grant', 'milli': 10000, 'expiresAt': far, 'source': 'verified-stripe-invoice'}}))).fetchone()[0]

        def reserve(key, milli, at):
            row = owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,estimated_usd_micro,cost_state,idempotency_key,meta,at) VALUES(%s,'reserve','text_model',10,'estimated',%s,%s::jsonb,%s)"
                                ' RETURNING id::text', (w1, key, json.dumps({'credits': {'op': 'reserve', 'maximum': milli, 'allocations': [{'grantId': grant, 'milli': milli}]}}), at)).fetchone()[0]
            owner.execute('UPDATE public.pr_usage_ledger SET reservation_id=id WHERE id::text=%s', (row,))
            return row
        reserve('run:held', 2000, '2026-08-03T00:00:00Z')
        settled = reserve('run:done', 3000, '2026-08-04T00:00:00Z')
        owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,reservation_id,kind,dimension,actual_usd_micro,cost_state,idempotency_key,meta,at) VALUES(%s,%s,'settle','text_model',8,'actual',%s,%s::jsonb,"
                      "'2026-08-05T00:00:00Z')", (w1, settled, 'settle:' + settled + ':completed', json.dumps({'credits': {'op': 'settle', 'used': 1500, 'allocations': [{'grantId': grant, 'milli': 1500}]}})))
        service = self.service(datetime(2026, 10, 1, tzinfo=timezone.utc))
        grants = self.query(service, 'credit_grants', ['grant_source'])['rows']
        self.assertEqual([(row['dimensions']['grant_source'], row['value']) for row in grants], [('subscription', 10000)])
        consumed = self.query(service, 'credit_consumption', ['task_type'])['rows']
        self.assertEqual([(row['dimensions']['task_type'], row['value']) for row in consumed], [('writer', 1500)])
        available = self.query(service, 'credit_available')['rows'][0]
        self.assertEqual((available['value'], available['measures']['heldMilliCredits'], available['dataState']), (10000 - 2000 - 1500, 2000, 'measured'))


if __name__ == '__main__':
    unittest.main()
