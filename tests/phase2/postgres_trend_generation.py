"""Generation and reused executor regression on the exact disposable suite target."""
from local_pg_target import selected_target
import os
from pathlib import Path
import sys
import unittest
import psycopg
from psycopg.conninfo import conninfo_to_dict
ROOT=Path(__file__).resolve().parents[2]

def main():
    dsn=os.environ.get('POSTRIFF_TEST_DSN','');params=conninfo_to_dict(dsn)
    if (set(params)-{'host','port','dbname','user'} or (params.get('host'),params.get('port'),params.get('dbname'))!=('127.0.0.1',str(selected_target(require_dsn=True).port),'postgres')
            or any(k in os.environ for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'))):
        raise ValueError('exact disposable script runner target required')
    with psycopg.connect(dsn) as db:
        if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]:raise ValueError('003 runtime dependency forbidden')
        if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
            db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
    os.environ['TREND_GENERATION_TEST_DSN']=dsn;os.environ['TREND_ENRICHMENT_TEST_DSN']=dsn;os.environ['TREND_LAB_TEST_DSN']=dsn
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_trend_generation','test_trend_enrichment','test_trend_lab_enrichment'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and not result.skipped else 1
if __name__=='__main__':sys.exit(main())
