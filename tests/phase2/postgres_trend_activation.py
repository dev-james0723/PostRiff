"""Disposable PostgreSQL Stage 2 activation; no external provider I/O."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]

import psycopg
from psycopg.conninfo import conninfo_to_dict
from postriff_phase2.growth.trends.activation import candidate
from postriff_phase2.growth.trends import beta
from postriff_phase2.growth.trends.contracts import ContractError, iso
from postriff_phase2.growth.trends.jobs import TrendJobs
from postriff_phase2.growth.trends.planner import FrontierPlanner
from postriff_phase2.growth.trends.revocation import revoke_policy
from postriff_phase2.growth.trends.store import TrendStore
from postriff_phase2.growth.trends.worker import configured_registry
from trend_provider_activation import apply, audit_release_schema, snapshot


def main():
    dsn = os.environ.get('POSTRIFF_TEST_DSN', '')
    params = conninfo_to_dict(dsn)
    if (set(params) - {'host', 'port', 'dbname', 'user'} or params.get('host') != '127.0.0.1'
            or params.get('port') != '55438' or params.get('dbname') != 'postgres'):
        raise ValueError('disposable_postgres_required')
    with psycopg.connect(dsn) as db:
        if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
            raise RuntimeError('rls_baseline_required')
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT / 'migrations/postriff/040_social_trend_intelligence.sql').read_text())

    class ActivationPostgres(unittest.TestCase):
        def test_immutable_activation_budget_job_and_revoke(self):
            wid = str(uuid.uuid4())
            scope = 'workspace:' + wid
            now = datetime.now(timezone.utc)
            start = now - timedelta(minutes=1)
            end = start + timedelta(hours=4)
            desired = candidate(wid, iso(start), iso(end), now=iso(now))
            with psycopg.connect(dsn) as db:
                db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (wid,))
            store = TrendStore(lambda: psycopg.connect(dsn))
            with psycopg.connect(dsn) as db:
                db.execute('CREATE SCHEMA IF NOT EXISTS postriff_private')
                db.execute('CREATE TABLE IF NOT EXISTS postriff_private.schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL)')
                for name in ('035_growth_metric_reads.sql', '040_social_trend_intelligence.sql'):
                    db.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s) ON CONFLICT(name) DO UPDATE SET sha256=excluded.sha256',
                               (name, hashlib.sha256((ROOT / 'migrations/postriff' / name).read_bytes()).hexdigest()))
            audit_release_schema(store)
            self.assertEqual(apply(store, wid, desired)['policy'], 'match')
            self.assertEqual(apply(store, wid, desired)['contract'], 'match')
            current = snapshot(store, wid)
            self.assertEqual(len(current['budgets']), 3)
            flags = {**{'RAFII_TREND_' + name + '_ENABLED': '1' for name in ('INTELLIGENCE', 'RADAR', 'PROVIDER_OPERATIONS')},
                     'RAFII_TREND_WORKSPACE_ALLOWLIST': wid,
                     'RAFII_TREND_ALLOWED_OPERATIONS': 'bluesky:live_sample'}
            registry = configured_registry(store)
            planner = FrontierPlanner(store, registry, values=flags)
            job = planner.plan_one(scope, 'bluesky', desired['policy']['version'])
            self.assertEqual(job['kind'], 'trend.ingest')
            self.assertEqual(job['payload']['reservation_microusd'], 0)
            self.assertEqual(len(job['payload']['budget_keys']), 3)
            self.assertEqual(planner.plan_one(scope, 'bluesky', desired['policy']['version'])['job_id'], job['job_id'])
            self.assertEqual(beta.acquisition_evidence(store, wid), 'unverified')
            with psycopg.connect(dsn) as db:
                db.execute("INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s)",
                           (scope, 'bluesky', 'stage2-test'))
                db.execute("UPDATE public.pr_trend_jobs SET state='succeeded' WHERE scope_key=%s AND job_id=%s",
                           (scope, job['job_id']))
                db.execute("""INSERT INTO public.pr_trend_ingestion_batches
                    (scope_key,provider_id,partition_key,batch_key,job_id,fence,previous_generation,next_generation,item_count,digest,terminal_page)
                    VALUES(%s,%s,%s,%s,%s,0,0,1,0,%s,true)""",
                           (scope, 'bluesky', 'stage2-test', 'stage2-test', job['job_id'], 'synthetic-test'))
                db.execute("""INSERT INTO public.pr_trend_source_health
                    (scope_key,provider_id,status,observed_at,notes_code)
                    VALUES(%s,%s,'partial',clock_timestamp(),'synthetic-test')""", (scope, 'bluesky'))
            self.assertEqual(beta.acquisition_evidence(store, wid), 'active')
            with psycopg.connect(dsn) as db:
                db.execute("UPDATE public.pr_trend_source_health SET status='gap',observed_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s",
                           (scope, 'bluesky'))
            self.assertEqual(beta.acquisition_evidence(store, wid), 'degraded')
            keys = [b['budget_key'] for b in desired['budgets']]
            reservation = TrendJobs(store).reserve(scope, 'stage2-test', str(uuid.uuid4()), 0, keys)
            self.assertEqual(reservation['amount_micro_usd'], 0)
            self.assertEqual(TrendJobs(store).settle(scope, reservation['reservation_id'], actual_micro_usd=0)['state'], 'settled')
            denied = {**flags, 'RAFII_TREND_WORKSPACE_ALLOWLIST': str(uuid.uuid4())}
            with self.assertRaises(ContractError):
                FrontierPlanner(store, registry, values=denied).plan_one(scope, 'bluesky', desired['policy']['version'])
            self.assertEqual(revoke_policy(store, scope, 'bluesky', desired['policy']['version']), 1)
            with self.assertRaises(ContractError):
                planner.plan_one(scope, 'bluesky', desired['policy']['version'])
            with self.assertRaises(ContractError):
                apply(store, wid, desired)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ActivationPostgres))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
