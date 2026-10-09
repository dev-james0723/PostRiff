"""Growth Studio before migrations 037/038 reach a database: honest readiness and structured 503s, never a 500.

Production today has 035 (native readings) but not 037/038. This suite loads the full chain, drops the 037/038
tables a Growth tab reads, and proves the catalog still answers (temporarily_unavailable growth_schema_unavailable,
next step 'wait', no reconnect) while every Growth read and paid run refuses with 503 growth_schema_unavailable
before touching a missing relation, reserving budget or calling a model.

    POSTRIFF_PG_BIN=... python scripts/postriff_pg_suite.py postgres_growth_readiness
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService
from growth_phase2_fixtures import Models, Writer, ENV, seed

ONE = '00000000-0000-0000-0000-000000000001'


def connection():
    return psycopg.connect(os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres'))


def verify(token):
    if token == 'one':
        return ONE
    raise AlphaError('Verified session required.', 401)


def schema_refusal(fn):
    try:
        fn()
    except AlphaError as error:
        assert (error.status, error.code) == (503, 'growth_schema_unavailable'), (error.status, error.code, str(error))
        return
    raise AssertionError('expected 503 growth_schema_unavailable')


checks = []
with connection() as db:
    wid = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner'")
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s", (wid,))
clock = [time.time()]
host = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], ideas_runtime=Writer())
host.bootstrap('one', 'studio')
models = Models()
g = host.growth = GrowthService(host, env=ENV, router_factory=models.router, clock=lambda: clock[0])
job = seed(host, wid, 'one')['jobId']
assert g.catalog(wid, 'one')['readiness']['studio']['state'] == 'ready'

# Production shape: 038 and the Growth parts of 037 are absent; 035 (native readings) is present.
with connection() as db:
    for table in ('pr_creator_calibrations', 'pr_audience_clusters', 'pr_comment_judgments', 'pr_postmortems'):
        db.execute(f'DROP TABLE public.{table} CASCADE')
ready = g.catalog(wid, 'one')['readiness']
for section in ('studio', 'results', 'audience', 'patterns'):
    payload = ready[section]
    assert (payload['state'], payload['reasonCodes'], payload['canRead'], payload['canRun'], payload['nextStep']) == (
        'temporarily_unavailable', ['growth_schema_unavailable'], False, False, {'kind': 'wait'}), (section, payload)
assert ready['measurement']['state'] != 'temporarily_unavailable', ready['measurement']
checks.append('catalog answers without 038: studio/results/audience/patterns are temporarily_unavailable growth_schema_unavailable with wait, measurement unaffected')

with connection() as db:
    reserved_before = db.execute('SELECT count(*) FROM public.pr_growth_budgets').fetchone()[0]
    runs_before = db.execute('SELECT count(*) FROM public.pr_post_doctor_runs').fetchone()[0]
c = g.closed_loop
schema_refusal(lambda: c.overview(wid, 'one'))
schema_refusal(lambda: c.audience(wid, 'one'))
schema_refusal(lambda: c.report(wid, 'one', {'jobId': job, 'horizon': '24h', 'confirmed': True, 'requestKey': str(uuid.uuid4())}))
schema_refusal(lambda: c.mine(wid, 'one', {'days': 14, 'confirmed': True, 'requestKey': str(uuid.uuid4())}))
schema_refusal(lambda: g.action(wid, 'one', host.get(wid, 'one')['revision'], 'creator_calibration_propose', {}))
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_growth_budgets').fetchone()[0] == reserved_before
    assert db.execute('SELECT count(*) FROM public.pr_post_doctor_runs').fetchone()[0] == runs_before
assert not models.calls
checks.append('overview, audience, review, analysis and calibration refuse with 503 growth_schema_unavailable before any reservation, run row or model call')

# Without 037 as well: Genome and the run ledger itself.
with connection() as db:
    for table in ('pr_genome_versions', 'pr_share_cards', 'pr_post_history', 'pr_predictions', 'pr_post_doctor_runs', 'pr_growth_budgets'):
        db.execute(f'DROP TABLE IF EXISTS public.{table} CASCADE')
schema_refusal(lambda: g.genome(wid, 'one'))
schema_refusal(lambda: g.feedback(wid, 'one', job))
ready = g.catalog(wid, 'one')['readiness']
assert ready['studio']['reasonCodes'] == ['growth_schema_unavailable'], ready['studio']
assert ready['measurement']['state'] != 'temporarily_unavailable', ready['measurement']
assert not models.calls
checks.append('without 037 the Genome and feedback reads refuse with 503 and the catalog still answers')
print(json.dumps({'status': 'PASS', 'execution': 'disposable PostgreSQL; 037/038 tables dropped to match production', 'checks': checks, 'realModelCalls': 0}))
