"""Radar under Pricing v2 on disposable PG17 (PRD R-COM-02/03, AC03): Free has no research allowance; a managed-credit
workspace always pays through a credit quote; legacy keeps its included allowance. No external providers."""
import json
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE  # noqa: E402
from postriff_phase2.growth.service import GrowthService, ROUTES  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from radar_fixtures import ENV, Models, Sources, Writer  # noqa: E402

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'


def connection():
    return psycopg.connect(DSN)


class PricedSources(Sources):
    """Same synthetic evidence, but `x` carries a provider price like the live paid sources do."""
    def ceiling(self, source):
        return 40_000 if source == 'x' else 0

    def catalog(self):
        return super().catalog() + [{'id': 'x', 'name': 'X', 'status': 'ready', 'maxRequestUsdMicro': 40_000, 'note': 'Synthetic priced source'}]


class RadarPlanGateV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '048_pricing_credit_catalog_v2.sql', '050_free_lifecycle_bootstrap.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=true WHERE id='creator-v1'")

    def setUp(self):
        self.user = str(uuid.uuid4())
        self.clock = [time.time()]
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))

        def verify(token):
            if token != 'owner':
                raise AlphaError('Verified session required.', 401)
            return self.user
        self.host = HostedWorkspaceService(connection, verify, clock=lambda: self.clock[0], ideas_runtime=Writer(),
                                           credits_enabled=True, pricing_v2_enabled=True)
        self.wid = self.host.bootstrap('owner')['workspaceId']
        self.g = self.host.growth = GrowthService(self.host, env=dict(ENV), router_factory=Models().router, clock=lambda: self.clock[0])
        self.radar = self.g.radar
        self.radar.sources = PricedSources(lambda: self.clock[0])
        saved = self.host.get(self.wid, 'owner')
        self.g.action(self.wid, 'owner', saved['revision'], 'growth_consent', {'confirmed': True, 'routes': [*ROUTES, SUMMARY_ROUTE]})
        saved = self.host.get(self.wid, 'owner')
        self.g.action(self.wid, 'owner', saved['revision'], 'radar_consent', {'confirmed': True, 'sources': ['news', 'bluesky', 'youtube', 'x'], 'ai': True})

    def quote(self, **values):
        return self.radar.quote(self.wid, 'owner', {'mode': 'quick', 'query': 'piano practice', 'sources': ['bluesky', 'news'],
                                                    'useAi': False, 'requestKey': str(uuid.uuid4()), **values})

    def runs(self):
        with connection() as db:
            return db.execute('SELECT count(*) FROM pr_radar_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0]

    def test_ac03_free_refuses_ai_or_priced_sources_before_any_run(self):
        for values in ({'useAi': True}, {'sources': ['bluesky', 'x']}):
            with self.assertRaises(AlphaError) as caught:
                self.quote(**values)
            self.assertEqual((caught.exception.status, caught.exception.code), (402, 'free_research_unavailable'))
        self.assertEqual(self.runs(), 0)
        self.assertEqual(self.radar.sources.calls, [])

    def test_free_zero_cost_scan_stays_available(self):
        quoted = self.quote()
        self.assertEqual(quoted['status'], 'quoted')
        self.assertEqual(self.runs(), 1)

    def test_managed_credits_pay_through_the_credit_quote_not_an_allowance(self):
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') "
                       "ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        self.assertNotEqual(self.g.env.get('POSTRIFF_RADAR_CREDIT_BILLING'), '1')
        # An empty Creator wallet proves the credit authority is applied: the platform allowance would have quoted.
        with self.assertRaises(AlphaError) as caught:
            self.quote(useAi=True, sources=['bluesky', 'x'])
        self.assertEqual(caught.exception.status, 402)
        self.assertIn('credits', str(caught.exception))
        self.assertEqual(self.runs(), 0)
        self.assertEqual(self.radar.sources.calls, [])

    def creator(self, milli=0):
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') "
                       "ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
            if milli:
                self.host.ledger.credits.grant(db.cursor(), self.wid, self.user, 'radar-monitor-' + self.wid, milli, None, source='local-test-only')

    def spend(self):
        with connection() as db:
            return (db.execute('SELECT count(*) FROM pr_radar_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0],
                    db.execute('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s', (self.wid,)).fetchone()[0],
                    db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (self.wid,)).fetchone()[0],
                    self.host.ledger.credits.view(db.cursor(), self.wid)['availableMilliCredits'])

    def test_creator_cannot_enable_daily_monitoring_without_recurring_credit_authorization(self):
        self.creator(milli=600_000)
        self.assertEqual(self.radar.catalog(self.wid, 'owner')['monitoringBlocked'], 'recurring_credit_authorization_unavailable')
        before = self.host.get(self.wid, 'owner')
        with self.assertRaises(AlphaError) as caught:
            self.g.action(self.wid, 'owner', before['revision'], 'radar_watch',
                          {'enabled': True, 'confirmed': True, 'query': 'piano practice', 'timezone': 'UTC', 'maximumUsdMicro': self.radar.maximum('quick')})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'recurring_credit_authorization_unavailable'))
        self.assertFalse(self.host.get(self.wid, 'owner')['state'].get('radarWatch', {}).get('enabled'))
        self.assertEqual(self.spend(), (0, 0, 0, 600_000))

    def test_cron_skips_a_watch_that_would_spend_credits_and_records_why(self):
        # A watch switched on before this workspace moved to Creator: the cron must not quote, start or charge it.
        self.creator(milli=600_000)
        self.clock[0] = int(time.time() // 86400) * 86400 + 12 * 3600   # inside the 08:00–22:00 UTC window
        watch = {'enabled': True, 'query': 'piano practice', 'timezone': 'UTC', 'sources': ['news', 'bluesky', 'youtube', 'x'], 'useAi': True,
                 'maximumUsdMicro': self.radar.maximum('quick'), 'actor': self.user, 'at': self.clock[0]}
        with connection() as db:
            db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{radarWatch}',%s::jsonb) WHERE id=%s", (json.dumps(watch), self.wid))
        result = self.radar.tick()
        mine = [r for r in result['runs'] if r['workspaceId'] == self.wid]
        self.assertEqual(mine, [{'workspaceId': self.wid, 'status': 'skipped', 'reason': 'recurring_credit_authorization_unavailable'}])
        self.assertEqual(self.spend(), (0, 0, 0, 600_000))   # no scan, quote, reservation or credit movement
        self.assertEqual(self.radar.sources.calls, [])
        with connection() as db:
            self.assertTrue(db.execute('SELECT checked_at FROM pr_radar_watch_schedule WHERE workspace_id=%s', (self.wid,)).fetchone())
        # A manual scan still works: it is quoted in credits and waits for the person's confirmation.
        quoted = self.quote()
        self.assertEqual((quoted['status'], quoted['customerCharge']), ('quoted', 'credits'))

    def test_plan_change_after_an_allowance_quote_refuses_start(self):
        quoted = self.quote()   # Free, zero-cost: included
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') "
                       "ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        with self.assertRaises(AlphaError) as caught:
            self.radar.start(self.wid, 'owner', quoted['id'], {'confirmed': True})
        self.assertEqual(caught.exception.code, 'radar_quote_plan_changed')
        self.assertEqual(self.radar.sources.calls, [])


if __name__ == '__main__':
    unittest.main()
