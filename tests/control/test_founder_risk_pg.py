"""Customer risk flags on a disposable PostgreSQL: every Live rule statement runs against the 054/065 (and, when present,
066) projections with bound parameters, flags the seeded workspaces it should, excludes classified ones, and the at-risk
hypothesis combines inactivity with payment risk. Skipped without RAFII_CONTROL_TEST_DSN."""
import os
import time
import unittest
import uuid

import psycopg

from rafii_control import founder_risk as risk
from rafii_control.auth import Boundary, CAPABILITIES, Config, VerifiedIdentity
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderRiskPostgresTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        self.owner = psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None)
        self.addCleanup(self.owner.close)
        if self.owner.execute("SELECT to_regclass('rafii_control.business_workspace_starts') IS NULL").fetchone()[0]:
            self.skipTest('migration 065 not applied by this harness')
        self.operator = str(uuid.uuid4())
        self.owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.operator,))
        self.owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.operator,))   # identity_active needs the operator's profile
        self.owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)",
                           (self.operator, list(CAPABILITIES)))
        self.workspaces = []
        self.addCleanup(self.cleanup)

    def workspace(self, created_at='2024-01-02T15:00:00Z'):
        user = str(uuid.uuid4())
        self.owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
        workspace = str(self.owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        self.owner.execute('UPDATE public.pr_workspaces SET created_at=%s WHERE id=%s', (created_at, workspace))
        self.workspaces.append(workspace)
        return workspace, user

    def subscription(self, workspace, status, cancelling=False):
        self.owner.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,status,cancel_at_period_end,updated_at) VALUES(%s,'studio-v1','stripe',%s,%s,'2026-09-20T00:00:00Z')"
                           " ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='studio-v1',provider='stripe',status=excluded.status,cancel_at_period_end=excluded.cancel_at_period_end,"
                           "updated_at=excluded.updated_at", (workspace, status, cancelling))

    def cleanup(self):
        import hashlib
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.request_budgets WHERE bucket=%s', (hashlib.sha256(b'exchange:global').hexdigest(),))
            health = con.execute("SELECT to_regclass('public.pr_connection_health') IS NOT NULL").fetchone()[0]
            for workspace in self.workspaces:
                for table in ('pr_product_events', 'pr_notification_events', 'pr_usage_ledger', 'pr_subscriptions') + (('pr_connection_health',) if health else ()):
                    con.execute(f'DELETE FROM public.{table} WHERE workspace_id=%s', (workspace,))
                con.execute('DELETE FROM public.pr_budgets WHERE scope=%s', ('workspace:' + workspace,))
                con.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,))

    def call(self, view):
        if getattr(self, '_session', None) is None:
            self._session = self.session()
        app, principal = self._session
        return risk.customers_risk(app, principal, dict(mode='live', query={'view': [view]}, method='GET', path='/customers/risk'))

    def session(self):
        store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), store, lambda token: VerifiedIdentity(self.operator, 'aal2', 'synthetic-upstream-' + self.operator, time.time()))
        token, _ = boundary.exchange('synthetic-identity', 'http://localhost:4449')
        app = type('App', (), {'queries': QueryService(store)})()
        return app, boundary.authorize(token, 'customers.read')

    def test_live_rules_flag_the_seeded_workspaces_and_exclude_classified_ones(self):
        lapsed, _ = self.workspace()
        busy, busy_user = self.workspace()
        disconnected, _ = self.workspace()
        internal, _ = self.workspace()
        self.subscription(lapsed, 'past_due')
        self.subscription(internal, 'past_due')
        self.owner.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,environment) VALUES(%s,'test','risk pg test','local')", (internal,))
        self.owner.execute("INSERT INTO public.pr_budgets(scope,window_kind,window_start,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,status)"
                           " VALUES(%s,'month',date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC',500000,1000000,850000,50000,'approved')", ('workspace:' + busy,))
        self.owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,meta,at)"
                           " VALUES(%s,'settle','text_model','gateway','m',4321,NULL,'estimated_unknown','run:risk-pg','{}'::jsonb,now()-interval '2 days')", (busy,))
        self.owner.execute("INSERT INTO public.pr_product_events(workspace_id,user_id,event,dedupe_key,occurred_at) VALUES(%s,%s,'draft.created','risk-pg:active',now()-interval '1 day')", (busy, busy_user))
        self.owner.execute("INSERT INTO public.pr_notification_events(workspace_id,scope_key,event_type,category,severity,dedupe_key,occurred_at) VALUES(%s,%s,'channel.reconnect_required','channels','action',%s,now()-interval '3 days')",
                           (disconnected, 'workspace:' + disconnected, 'risk-pg:' + uuid.uuid4().hex))
        if self.owner.execute("SELECT to_regclass('public.pr_connection_health') IS NOT NULL").fetchone()[0]:
            self.owner.execute("INSERT INTO public.pr_connection_health(workspace_id,connection_id,capability,provider,level,state,connection_state,expires_at)"
                               " VALUES(%s,'conn-1','publish','linkedin','Direct','expired','token_expired',now()-interval '1 day')", (disconnected,))

        payment = self.call('payment_risk')
        rows = {row['workspaceId']: row for row in payment['rows']}
        self.assertIn(lapsed, rows)
        self.assertNotIn(internal, rows, 'classified test workspaces are excluded')
        self.assertEqual(rows[lapsed]['flags'][[flag['id'] for flag in rows[lapsed]['flags']].index('payment_risk')]['evidence']['subscriptionStatus'], 'past_due')
        states = {rule['id']: rule for rule in payment['rules']}
        self.assertEqual(states['payment_risk']['state'], 'partial' if states['payment_risk'].get('reason') else 'measured')

        at_risk = self.call('at_risk')
        self.assertIn(lapsed, [row['workspaceId'] for row in at_risk['rows']])
        flag = next(flag for flag in next(row for row in at_risk['rows'] if row['workspaceId'] == lapsed)['flags'] if flag['id'] == 'at_risk')
        self.assertEqual((flag['basis'], flag['evidence']['because']), ('hypothesis', ['inactive', 'payment_risk']))

        quota = {row['workspaceId']: row for row in self.call('quota_80')['rows']}
        evidence = next(flag for flag in quota[busy]['flags'] if flag['id'] == 'quota_near_limit')['evidence']
        self.assertEqual((evidence['usedUsdMicro'], evidence['stopUsdMicro'], evidence['usedShare']), (900000, 1000000, 0.9))
        self.assertIn('unknown_cost_holds', [flag['id'] for flag in quota[busy]['flags']], 'phase two adds the other chips')
        self.assertNotIn('inactive', [flag['id'] for flag in quota[busy]['flags']], 'a product event yesterday is activity')

        connection = {row['workspaceId']: row for row in self.call('connection_risk')['rows']}
        self.assertIn(disconnected, connection)
        self.assertIn(next(flag for flag in connection[disconnected]['flags'] if flag['id'] == 'connection_risk')['evidence']['source'], ('connection_health', 'reconnect_events'))

        flagged = self.call('flagged')
        self.assertTrue({lapsed, busy, disconnected} <= {row['workspaceId'] for row in flagged['rows']})
        self.assertNotIn(internal, {row['workspaceId'] for row in flagged['rows']})
        self.assertIn(flagged['_dataState'], ('measured', 'partial'))
        self.assertLessEqual(len(flagged['rows']), risk.ROW_LIMIT)


if __name__ == '__main__':
    unittest.main()
