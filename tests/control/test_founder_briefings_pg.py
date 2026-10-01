"""Receipted briefings and the reader-projection cost observation on a disposable PostgreSQL (CONTRACTS §8.E).

Skipped without RAFII_CONTROL_TEST_DSN; scripts/rafii_control_pg.py applies 054/055 (and every later founder migration)
twice and sets it. Proves, through the restricted roles: a briefing's values are QueryService receipts owned by the
founder (rafii_control.founder_reports.receipt_ids is non-empty), the cron principal keeps the capability check (a founder
without metrics.query gets no receipt and an audited denial), and observe_live's AI cost excludes workspaces classified
internal and aiUsageExempt rows exactly like the ai_cost_actual metric.
"""
import os
import time
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg

from rafii_control import founder_briefings, founder_cron, founder_schedules
from rafii_control.auth import CAPABILITIES
from rafii_control.founder_cron import PostgresFounderStore
from rafii_control.live_metrics import TIME_ZONE
from rafii_control.store import PostgresStore, connection_factory


def at_local(day, hour):
    zone = ZoneInfo(TIME_ZONE)
    return datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(hour=hour).astimezone(timezone.utc)


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderBriefingsDatabaseTests(unittest.TestCase):
    def connect(self, role=None):
        con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], autocommit=True, prepare_threshold=None)
        if role:
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        owner = self.connect()
        if owner.execute("SELECT to_regclass('rafii_control.business_usage_v2') IS NULL OR to_regclass('rafii_control.founder_reports') IS NULL").fetchone()[0]:
            self.skipTest('migrations 054/055 not applied by this harness')
        self.user, self.other = str(uuid.uuid4()), str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)', (self.user, self.other))
        self.workspace = str(owner.execute("SELECT public.pr_bootstrap(%s,'studio')", (self.user,)).fetchone()[0])
        self.internal = str(owner.execute("SELECT public.pr_bootstrap(%s,'assist')", (self.other,)).fetchone()[0])
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)", (self.user, sorted(CAPABILITIES)))
        self.now = time.time()
        today = datetime.fromtimestamp(self.now, ZoneInfo(TIME_ZONE)).date()
        yesterday, today_at = at_local(today - timedelta(days=1), 12), datetime.fromtimestamp(self.now - 60, timezone.utc)
        for workspace, key, actual, meta, when in ((self.workspace, 'run:a', 2500, '{}', yesterday), (self.workspace, 'agent:c', 100, '{"aiUsageExempt":true}', yesterday),
                                                   (self.internal, 'voice:d', 900, '{"costCenter":"founder_ops"}', yesterday), (self.workspace, 'image:t', 700, '{}', today_at)):
            owner.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,meta,at) "
                          "VALUES(%s,'settle','text_model','gateway','m',50,%s,'actual',%s,%s::jsonb,%s)", (workspace, actual, key, meta, when))
        owner.execute("INSERT INTO rafii_control.workspace_classifications(workspace_id,kind,reason,environment) VALUES(%s,'internal','founder ops test','local') "
                      "ON CONFLICT (workspace_id) DO UPDATE SET kind='internal'", (self.internal,))

    def tearDown(self):
        with psycopg.connect(self.dsn, autocommit=True) as con:
            for workspace in (getattr(self, 'workspace', None), getattr(self, 'internal', None)):
                if workspace:
                    con.execute('DELETE FROM public.pr_usage_ledger WHERE workspace_id=%s', (workspace,))
                    con.execute('DELETE FROM rafii_control.workspace_classifications WHERE workspace_id=%s', (workspace,))
            if getattr(self, 'user', None):
                con.execute('DELETE FROM rafii_control.founder_contact_attempts WHERE operator_id=%s', (self.user,))
                con.execute('DELETE FROM rafii_control.founder_briefing_occurrences WHERE schedule_id IN (SELECT id FROM rafii_control.founder_briefing_schedules WHERE operator_id=%s)',
                            (self.user,))
                con.execute('DELETE FROM rafii_control.founder_briefing_schedules WHERE operator_id=%s', (self.user,))
                con.execute('DELETE FROM rafii_control.founder_reports WHERE operator_id=%s', (self.user,))
                con.execute("UPDATE rafii_control.platform_operators SET status='revoked' WHERE user_id=%s", (self.user,))

    def fstore(self):
        return PostgresFounderStore(PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'),
                                                  connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local'))

    def cost_yesterday(self):
        facts, basis = founder_briefings.briefing_facts(self.fstore(), self.user, 'daily', self.now, fallback=lambda: [])
        return facts, basis, next(f for f in facts if f['label'] == 'AI cost yesterday (actual)')

    def test_briefing_values_are_founder_owned_receipts(self):
        facts, basis, cost = self.cost_yesterday()
        self.assertEqual(basis, {'basis': 'metric_receipts', 'receipts': len(founder_briefings.BRIEF_METRICS['daily'])})
        self.assertIn(cost['dataState'], ('measured', 'stale'))
        owner = self.connect()
        # Deltas, so rows other tests left in the shared database cannot matter: the internal and exempt rows never counted,
        # the customer row counts exactly once.
        owner.execute("DELETE FROM public.pr_usage_ledger WHERE idempotency_key IN ('voice:d','agent:c') AND workspace_id IN (%s,%s)", (self.workspace, self.internal))
        self.assertEqual(self.cost_yesterday()[2]['value'], cost['value'], 'internal and exempt rows are excluded, as in the metric')
        owner.execute("DELETE FROM public.pr_usage_ledger WHERE idempotency_key='run:a' AND workspace_id=%s", (self.workspace,))
        self.assertEqual(cost['value'] - self.cost_yesterday()[2]['value'], 2500)
        receipt_ids = sorted({f['id'] for f in facts if f['id']})
        rows = owner.execute('SELECT operator_id::text,execution_state FROM rafii_control.query_receipts WHERE id = ANY(%s::uuid[])', (receipt_ids,)).fetchall()
        self.assertEqual((len(rows), {tuple(r) for r in rows}), (len(receipt_ids), {(self.user, 'admitted_operational')}))
        audit = owner.execute('SELECT action,result,session FROM rafii_control.admin_audit_log WHERE actor=%s ORDER BY occurred_at DESC LIMIT 1', (self.user,)).fetchone()
        self.assertEqual(tuple(audit), ('metrics.query', 'allowed', None))

    def test_scheduled_briefing_stores_its_receipt_ids(self):
        fstore = self.fstore()
        local = datetime.fromtimestamp(self.now, ZoneInfo(TIME_ZONE))
        slot = (local + timedelta(minutes=2)).strftime('%H:%M')
        schedule = founder_schedules.create_schedule(fstore, {'operator': {'user_id': self.user}}, {'kind': 'daily', 'localTime': slot, 'timeZone': TIME_ZONE},
                                                     now=self.now)['schedule']
        quiet = {'sources_probed': True, 'sources': [], 'publish': {'available': False}, 'cost': {'available': False}, 'payments': {'available': False}}
        result = founder_cron.schedules_stage(fstore, {}, quiet, [self.user], schedule['nextAt'] + 20, lambda operator: None, None, 'pg-test')
        (delivered,) = result['delivered']
        self.assertEqual(delivered['basis'], 'metric_receipts')
        stored = self.connect().execute('SELECT receipt_ids::text[],coverage FROM rafii_control.founder_reports WHERE id=%s', (delivered['reportId'],)).fetchone()
        self.assertTrue(stored[0], 'founder_reports.receipt_ids is never empty when metrics exist')
        self.assertEqual((len(stored[0]), stored[1]['basis']), (delivered['receipts'], 'metric_receipts'))
        self.assertEqual(delivered['attemptState'], 'suppressed', 'no call: the contact policy is off')

    def test_cron_principal_keeps_the_capability_check(self):
        owner = self.connect()
        owner.execute("UPDATE rafii_control.platform_operators SET capabilities=array_remove(capabilities,'metrics.query') WHERE user_id=%s AND environment='local'", (self.user,))
        before = owner.execute('SELECT count(*) FROM rafii_control.query_receipts WHERE operator_id=%s', (self.user,)).fetchone()[0]
        facts, basis = founder_briefings.briefing_facts(self.fstore(), self.user, 'daily', self.now, fallback=lambda: [{'id': None, 'label': 'x', 'dataState': 'unavailable'}])
        self.assertEqual(basis, {'basis': 'cron_observations', 'reason': 'metrics_query_not_granted'})
        self.assertEqual(owner.execute('SELECT count(*) FROM rafii_control.query_receipts WHERE operator_id=%s', (self.user,)).fetchone()[0], before)
        audit = owner.execute('SELECT action,result,error_code FROM rafii_control.admin_audit_log WHERE actor=%s ORDER BY occurred_at DESC LIMIT 1', (self.user,)).fetchone()
        self.assertEqual(tuple(audit), ('metrics.query', 'denied', 'SCOPE_DENIED'))

    def test_observe_live_cost_comes_from_the_reader_projection(self):
        consumer = types.SimpleNamespace(connection_factory=lambda: psycopg.connect(self.dsn), notifications=None)

        def observed():
            return founder_cron.observe_live(self.fstore(), consumer, {}, self.now)['cost']
        everything = observed()
        self.assertEqual((everything['available'], everything['basis'], everything['time_zone']), (True, 'ai_cost_actual_v1_reader_projection', TIME_ZONE))
        owner = self.connect()
        owner.execute("DELETE FROM public.pr_usage_ledger WHERE idempotency_key IN ('voice:d','agent:c') AND workspace_id IN (%s,%s)", (self.workspace, self.internal))
        customers_only = observed()
        self.assertEqual((customers_only['daily_usd_micro'], customers_only['today_usd_micro']), (everything['daily_usd_micro'], everything['today_usd_micro']),
                         'the internal workspace and the exempt row never counted')
        owner.execute("DELETE FROM public.pr_usage_ledger WHERE idempotency_key IN ('run:a','image:t') AND workspace_id=%s", (self.workspace,))
        none = observed()
        self.assertEqual((everything['daily_usd_micro'][-1] - none['daily_usd_micro'][-1], everything['today_usd_micro'] - none['today_usd_micro']), (2500, 700),
                         'yesterday and today on report-time-zone days')


if __name__ == '__main__':
    unittest.main()
