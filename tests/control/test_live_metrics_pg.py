"""Migration 054 on a disposable PostgreSQL: projections, grants, RLS and one Live metric round trip.

Skipped without RAFII_CONTROL_TEST_DSN. The harness must apply 054 (twice) after 053; see scripts/rafii_control_pg.py.
"""
import os
import time
import unittest
import uuid
import psycopg
from rafii_control.auth import Boundary, Config, VerifiedIdentity, CAPABILITIES
from rafii_control.intelligence import QueryService
from rafii_control.live_metrics import overview, unknown_reservations
from rafii_control.store import PostgresStore, connection_factory

VIEWS = ('business_subscriptions_v2', 'business_usage_v2', 'business_budgets', 'business_billing_notices', 'business_notification_events', 'business_notification_deliveries',
         'business_phone_calls', 'business_agent_runs', 'business_audit_events', 'business_time_savings', 'business_data_requests_v2', 'business_subscription_snapshots')
# Present only where the canonical purchase schema (021/022) exists; the harness rls.sql does not apply those migrations.
PURCHASE_VIEWS = ('business_payments_v2', 'business_subscription_grants', 'business_refunds', 'business_disputes')
INTERVAL = dict(start='2026-01-01T00:00:00Z', end='2026-12-31T00:00:00Z', timeZone='America/Indiana/Indianapolis')


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderViewsMigrationTests(unittest.TestCase):
    def connect(self, role=None):
        con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], autocommit=True, prepare_threshold=None)
        if role: con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        self.user = str(uuid.uuid4())
        owner = self.connect()
        self.skip_unless_applied(owner)
        self.other = str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)', (self.user, self.other))
        self.workspace = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0])
        self.internal = str(owner.execute("SELECT public.pr_bootstrap(%s,'assist')", (self.other,)).fetchone()[0])
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)", (self.user, list(CAPABILITIES)))
        for workspace, key, state, actual, meta in ((self.workspace, 'run:a', 'actual', 2500, '{}'), (self.workspace, 'image:b', 'estimated_unknown', None, '{}'),
                                                   (self.workspace, 'agent:c', 'actual', 100, '{"aiUsageExempt":true}'), (self.internal, 'voice:d', 'actual', 900, '{"costCenter":"founder_ops"}')):
            owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,meta,at) VALUES(%s,'settle','text_model','gateway','m',50,%s,%s,%s,%s::jsonb,'2026-06-01T00:00:00Z')",
                          (workspace, actual, state, key, meta))
        owner.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,environment) VALUES(%s,'internal','founder ops test','local') ON CONFLICT (workspace_id) DO UPDATE SET kind='internal'", (self.internal,))

    def skip_unless_applied(self, owner):
        if owner.execute("SELECT to_regclass('rafii_control.business_usage_v2') IS NULL").fetchone()[0]:
            self.skipTest('migration 054 not applied by this harness')

    def tearDown(self):
        import hashlib
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.request_budgets WHERE bucket=%s', (hashlib.sha256(b'exchange:global').hexdigest(),))
            # Each test seeds its own workspaces and the Live metrics aggregate every workspace, so the seed rows leave with the test.
            for workspace in (getattr(self, 'workspace', None), getattr(self, 'internal', None)):
                if workspace:
                    con.execute('DELETE FROM public.pr_usage_ledger WHERE workspace_id=%s', (workspace,))
                    con.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,))

    def test_views_are_projection_owned_reader_readable_and_column_bounded(self):
        owner = self.connect()
        purchase_schema = owner.execute("SELECT to_regclass('public.pr_credit_orders') IS NOT NULL").fetchone()[0]
        for view in VIEWS + (PURCHASE_VIEWS if purchase_schema else ()):
            with self.subTest(view=view):
                row = owner.execute("SELECT pg_get_userbyid(c.relowner), c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relname=%s AND c.relkind='v'", (view,)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], 'rafii_control_business_projection')
                self.assertIn('security_barrier=true', row[1])
        reader = self.connect('rafii_control_reader')
        reader.execute("SELECT set_config('rafii_control.environment','local',true)")
        for view in VIEWS + (PURCHASE_VIEWS if purchase_schema else ()): reader.execute(f'SELECT * FROM rafii_control.{view} LIMIT 1').fetchall()
        features = {row[0]: row[1] for row in reader.execute('SELECT id,feature FROM rafii_control.business_usage_v2').fetchall()}
        self.assertEqual(set(features.values()) <= {'writer', 'image', 'agent', 'voice'}, True)
        for query in ('SELECT meta FROM public.pr_usage_ledger', 'SELECT idempotency_key FROM public.pr_usage_ledger', 'SELECT payload FROM public.pr_notification_events',
                      'INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,environment) VALUES(gen_random_uuid(),\'test\',\'local\')',
                      'SELECT * FROM rafii_control.founder_follow_ups'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): reader.execute(query)
        columns = {row[0] for row in owner.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='rafii_control' AND table_name='business_usage_v2'").fetchall()}
        self.assertEqual(columns, {'id', 'workspaceId', 'memberId', 'runId', 'reservationId', 'kind', 'dimension', 'provider', 'model', 'quantity', 'unit', 'estimatedUsdMicro', 'actualUsdMicro', 'costState', 'aiUsageExempt', 'feature', 'creditsUsedMilli', 'costCenter', 'at'})

    def test_new_tables_force_rls_with_environment_policies_and_session_writes(self):
        owner = self.connect()
        for table in ('workspace_classifications', 'founder_follow_ups'):
            flags = owner.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='rafii_control' AND relname=%s", (table,)).fetchone()
            self.assertEqual(tuple(flags), (True, True))
        snapshot = owner.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='public' AND relname='pr_subscription_snapshots'").fetchone()
        self.assertEqual(tuple(snapshot), (True, True))
        session = self.connect('rafii_control_session')
        # Autocommit connections: a transaction-local set_config would end with its own statement, so the GUCs are set for the session.
        session.execute("SELECT set_config('rafii_control.environment','local',false)")
        session.execute("SELECT set_config('rafii_control.operator',%s,false)", (self.user,))
        session.execute("INSERT INTO rafii_control.source_health(source_id,environment,state,watermark,reason_code) VALUES('cron','local','measured',now(),'qualified') ON CONFLICT (source_id,environment) DO UPDATE SET checked_at=now(),watermark=excluded.watermark")
        session.execute("INSERT INTO rafii_control.founder_follow_ups(operator_id,environment,source_type,source_id,title) VALUES(%s,'local','incident','demo-1','Follow up')", (self.user,))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            session.execute("INSERT INTO rafii_control.founder_follow_ups(operator_id,environment,source_type,source_id,title) VALUES(%s,'staging','incident','demo-2','Other environment')", (self.user,))
        other = self.connect('rafii_control_session')
        other.execute("SELECT set_config('rafii_control.environment','local',false)")
        other.execute("SELECT set_config('rafii_control.operator',%s,false)", (str(uuid.uuid4()),))
        self.assertEqual(other.execute('SELECT count(*) FROM rafii_control.founder_follow_ups').fetchone()[0], 0)
        for role in ('anon', 'authenticated', 'service_role'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.connect(role).execute('SELECT * FROM rafii_control.workspace_classifications')
        owner.execute("INSERT INTO rafii_control.query_receipts(id,operator_id,environment,request_id,query_digest,metric_versions,data_state,source_watermarks,row_count,execution_state) VALUES(gen_random_uuid(),%s,'local',gen_random_uuid(),repeat('a',64),'{}','measured','{}',0,'demo_dataset')", (self.user,))
        owner.execute("UPDATE rafii_control.platform_operators SET capabilities=array_append(capabilities,'incidents.ack') WHERE user_id=%s AND environment='local'", (self.user,))

    def live_service(self):
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), store, lambda token: VerifiedIdentity(self.user, 'aal2', 'synthetic-upstream-' + self.user, time.time()))
        token, _ = boundary.exchange('synthetic-identity', 'http://localhost:4449')
        return store, boundary, token, QueryService(store)

    def test_reconciled_unknown_reservations_are_counted_once(self):
        """billing.Ledger keeps the estimated_unknown settle row when reconcile_unknown later writes the actual/released row for
        the same reservation; the metrics, the reconcile queue and founder_ops_cost must count that reservation once."""
        owner = self.connect()
        customer_reservation, ops_reservation = str(uuid.uuid4()), str(uuid.uuid4())
        for workspace, reservation, key, state, estimate, actual, meta in (
                (self.workspace, customer_reservation, 'voice:u', 'estimated_unknown', 300, None, '{}'), (self.workspace, customer_reservation, 'reconcile:voice:u', 'actual', 300, 450, '{}'),
                (self.internal, ops_reservation, 'voice:iu', 'estimated_unknown', 200, None, '{"costCenter":"founder_ops"}'), (self.internal, ops_reservation, 'reconcile:voice:iu', 'actual', 200, 250, '{"costCenter":"founder_ops"}')):
            owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,meta,at) VALUES(%s,%s,'settle','text_model','gateway','m',%s,%s,%s,%s,%s::jsonb,'2026-06-02T00:00:00Z')",
                          (workspace, reservation, estimate, actual, state, key, meta))
        _store, boundary, token, service = self.live_service()
        principal = boundary.authorize(token, 'metrics.query')
        query = dict(metricIds=['ai_cost_actual'], interval=INTERVAL, groupBy=['feature'], filters=[], comparison='none', limit=100)
        by_feature = {row['dimensions']['feature']: row for row in service.metric_query(query, principal, str(uuid.uuid4()))['rows']}
        self.assertEqual((by_feature['voice']['value'], by_feature['voice']['coverage'], by_feature['voice']['dataState']), (450, dict(known=1, unknown=0, numerator=None, denominator=None), 'measured'))
        self.assertEqual((by_feature['image']['coverage']['unknown'], by_feature['image']['dataState']), (1, 'partial'), 'a never-reconciled reservation stays unknown')
        unknown = service.metric_query({**query, 'metricIds': ['ai_cost_unknown'], 'groupBy': []}, principal, str(uuid.uuid4()))['rows'][0]
        self.assertEqual(unknown['value'], 50, 'only image:b is still unknown')
        queue = unknown_reservations(principal, 'live', service, limit=50)
        self.assertEqual([row['feature'] for row in queue['rows']], ['image'])
        ops = {row['dimensions']['feature']: row for row in service.metric_query({**query, 'metricIds': ['founder_ops_cost']}, principal, str(uuid.uuid4()))['rows']}
        self.assertEqual((ops['voice']['value'], ops['voice']['coverage']['known'], ops['voice']['coverage']['unknown']), (900 + 250, 2, 0), 'one founder_ops_cost total per reservation')

    def test_live_metric_round_trip_excludes_classified_and_exempt_rows(self):
        store, boundary, token, service = self.live_service()
        principal = boundary.authorize(token, 'metrics.query')
        query = dict(metricIds=['ai_cost_actual'], interval=INTERVAL, groupBy=['feature'], filters=[], comparison='none', limit=100)
        result = service.metric_query(query, principal, str(uuid.uuid4()))
        by_feature = {row['dimensions']['feature']: row for row in result['rows']}
        self.assertEqual(by_feature['writer']['value'], 2500)
        self.assertEqual(by_feature['writer']['dataState'], 'measured')
        self.assertEqual(by_feature['image']['coverage']['unknown'], 1)
        self.assertEqual(by_feature['image']['dataState'], 'partial')
        self.assertNotIn('agent', by_feature)
        self.assertNotIn('voice', by_feature)
        ops = service.metric_query({**query, 'metricIds': ['founder_ops_cost'], 'groupBy': ['feature']}, principal, str(uuid.uuid4()))
        self.assertEqual({row['dimensions']['feature']: row['value'] for row in ops['rows']}, {'agent': 100, 'voice': 900})
        receipt = store.read('receipt', result['queryReceiptId'])[0]
        self.assertEqual(receipt['execution_state'], 'admitted_operational')
        self.assertEqual(service.authorized_receipt(result['queryReceiptId'], principal)['id'], result['queryReceiptId'])
        page = overview(boundary.authorize(token, 'control.read'), 'live', '30d', service)
        self.assertEqual(len(page['pulse']), 5)
        self.assertTrue(page['_receiptIds'])
        # Without the purchase schema the cash tile is unavailable (source not configured), never a zero or a 503.
        cash = next(tile for tile in page['pulse'] if tile['id'] == 'cash_collected')
        self.assertIn(cash['dataState'], ('unavailable', 'partial', 'measured'))
        if cash['dataState'] == 'unavailable': self.assertIsNone(cash['value'])


if __name__ == '__main__':
    unittest.main()
