"""P0/P1/P2 ONCE, then P3 real-SQL controls in an owned cloud test cluster.

Prepared only. Execute after separate cloud AND disposable-database approval.
The imported harness fences loopback, database identity, synthetic auth/users,
and provider transport. No production database or actual Discord is accepted.
"""
import copy
import json
import os
import runpy
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

if sys.platform != 'linux' or os.environ.get('CI') != 'true' or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') != '1':
    raise SystemExit('Use the separately approved cloud disposable PostgreSQL harness.')

prior = runpy.run_path(str(Path(__file__).with_name('postgres_discord_connections.py')))
base = prior['base']
connection, Fixture = base['connection'], base['Fixture']
PostgresWorker, AlphaError = base['PostgresWorker'], base['AlphaError']
from postriff_phase2.discord import worker as policy
from postriff_phase2.hosted_worker import due_workspaces_sql

with connection() as db:
    db.execute((Path(__file__).resolve().parents[2]/'migrations/postriff/126_discord_worker_projection.sql').read_text())

with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT to_regclass('public.pr_worker_tenants')").fetchone()[0]
    database_now = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
# These synthetic approvals were made six minutes earlier and are now due. P3
# uses real database time; changing an app clock must never make a job due.
Fixture.__init__.__globals__['NOW'] = int(database_now) // 60 * 60 - 360

checks, cohort_metrics = [], {}
started = time.monotonic()


def worker(f, name='p3-owner', factory=connection, offset=0):
    return PostgresWorker(factory, f.social, worker_id=name, discord_workers=True,
                          clock=lambda: time.time() + offset)


def state_of(f):
    with connection() as db:
        return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (f.workspace,)).fetchone()[0]


def job_of(f):
    return state_of(f)['phase2']['jobs'][0]


def change_job(f, **changes):
    with connection() as db:
        state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f.workspace,)).fetchone()[0]
        state['phase2']['jobs'][0].update(changes)
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), f.workspace))


def expire(f):
    change_job(f, leaseUntil=time.time() - 2)


def make_due(f):
    change_job(f, nextAt=time.time() - 2)


def finish_fixture(f):
    # Keep older synthetic workspaces out of later unscoped claim cohorts.
    # Intent/receipt/approval evidence stays intact until cluster cleanup.
    change_job(f, state='held', leaseOwner=None, leaseUntil=0)


def exact_claim(f, w, job):
    return w.claim(workspace_id=f.workspace, job_id=job['id'],
                   approval_digest=job['approvalDigest'], dispatch_principal=f.user)


def seal(f, w, claimed):
    claimed['discordPrepared'] = f.social.prepare_discord_dispatch(claimed['job']['manifest'])
    return w.authorize_dispatch(claimed)


def frozen(f, original):
    current = job_of(f)
    for key in ('manifest', 'discordAuthorization', 'approvalDigest', 'approvedBy', 'approvedAt'):
        assert current[key] == original[key], 'Worker changed frozen human authority: ' + key


def no_posts(f):
    assert not any(call[0] == 'POST' for call in f.wire.calls), 'Unexpected synthetic message POST'


def denied_or_false(action):
    try:
        assert action() is False
    except AlphaError:
        pass


with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
    # Independent rows progress while a peer holds its short claim transaction.
    a, b = Fixture(), Fixture(); ja, jb = a.job(), b.job()
    selected, release = Event(), Event()
    @contextmanager
    def held_connection():
        with connection() as db:
            yield db
            selected.set()
            assert release.wait(8), 'Bounded claim lock probe timed out'
    with ThreadPoolExecutor(max_workers=2) as pool:
        wa, wb = worker(a, 'parallel-a', held_connection), worker(b, 'parallel-b')
        first = pool.submit(wa.claim, discord_only=True)
        try:
            assert selected.wait(8)
            second = pool.submit(wb.claim, discord_only=True).result(timeout=5)
            assert second and second['workspaceId'] in (a.workspace, b.workspace)
        finally:
            release.set()
        first = first.result(timeout=8)
    assert first and first['workspaceId'] != second['workspaceId']
    assert 'LIMIT 1 FOR UPDATE OF w SKIP LOCKED' in due_workspaces_sql(discord_only=True)
    finish_fixture(a); finish_fixture(b)
    checks.append('independent tenant progresses while peer claim transaction holds its row')

    f = Fixture(); original = f.job(); barrier = Barrier(8)
    def collide(index):
        w = worker(f, 'parallel-' + str(index))
        barrier.wait(timeout=10)
        return w, w.claim(discord_only=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(collide, range(8)))
    winners = [(w, c) for w, c in claims if c]
    assert len(winners) == 1
    w, claimed = winners[0]
    assert seal(f, w, claimed)
    assert not w.authorize_dispatch(claimed)
    assert len(job_of(f)['discordDispatchIntents']) == 1
    frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('eight parallel lane claims produce one lease and one intent')

    f, foreign = Fixture(), Fixture(); original, _ = f.job(), foreign.job()
    w = worker(f, offset=-7200); claimed = exact_claim(f, w, original); assert claimed
    before = job_of(f)
    attempted = copy.deepcopy(claimed); attempted['workspaceId'] = foreign.workspace
    denied_or_false(lambda: w.renew_discord_lease(attempted))
    stale = copy.deepcopy(claimed); stale['job']['leaseId'] = 'stale'
    assert not w.renew_discord_lease(stale)
    assert not worker(f, 'wrong-owner').renew_discord_lease(claimed)
    assert job_of(f) == before
    assert w.renew_discord_lease(claimed)
    with connection() as db:
        now = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
    assert now < job_of(f)['leaseUntil'] <= now + 45
    frozen(f, original); finish_fixture(f); finish_fixture(foreign)
    checks.append('foreign tenant, stale lease and wrong owner denied; database time controls renewal')

    # Actual workspace lock wait followed by committed authority withdrawal.
    for kind in ('content', 'destination', 'credential'):
        f = Fixture(); original = f.job(); w = worker(f); claimed = exact_claim(f, w, original); assert claimed
        pids = base['Queue']()
        def renew_after_wait():
            base['LOCAL'].pids = pids
            try:
                return w.renew_discord_lease(claimed)
            finally:
                base['LOCAL'].pids = None
        with ThreadPoolExecutor(max_workers=1) as pool:
            with connection() as blocker:
                state = blocker.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (f.workspace,)).fetchone()[0]
                pending = pool.submit(renew_after_wait)
                base['wait_for_lock'](pids, blocker.info.backend_pid)
                if kind == 'content':
                    state['variants'][-1].update(text='Concurrent P3 edit', revision=2)
                elif kind == 'destination':
                    channel = next(c for c in state['phase2']['channels'] if c['id'] == f.connection_id)
                    base['auth'].revoke_destination(state, channel, original['manifest']['destinationId'], f.user, time.time())
                else:
                    blocker.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=clock_timestamp() WHERE workspace_id=%s AND connection_id=%s', (f.workspace, f.connection_id))
                blocker.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), f.workspace))
            assert pending.result(timeout=10) is False
        assert not job_of(f).get('discordDispatchIntents'); frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('real row-lock renewal races honor content, destination and credential withdrawal')

    # A credential wait must not let transaction-start/host time revive expiry.
    f = Fixture(); original = f.job(); w = worker(f, offset=-7200); claimed = exact_claim(f, w, original); assert claimed
    change_job(f, leaseUntil=time.time() + .3)
    pids = base['Queue']()
    def renew_expiring():
        base['LOCAL'].pids = pids
        try: return w.renew_discord_lease(claimed)
        finally: base['LOCAL'].pids = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection() as blocker:
            blocker.execute('SELECT authorization_generation FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s FOR UPDATE', (f.workspace, f.connection_id))
            pending = pool.submit(renew_expiring)
            base['wait_for_lock'](pids, blocker.info.backend_pid)
            time.sleep(.4)
        assert pending.result(timeout=10) is False
    assert not job_of(f).get('discordDispatchIntents'); frozen(f, original); finish_fixture(f)
    checks.append('lease expiry during credential lock wait cannot renew despite slow host clock')

    f = Fixture(); original = f.job(); w = worker(f); abandoned = exact_claim(f, w, original); assert abandoned
    expire(f)
    assert w.claim(discord_only=True) is None
    current = job_of(f)
    assert current['state'] == 'scheduled' and current[policy.KEY]['recoveries'] == 1
    assert current['nextAt'] > time.time()
    make_due(f); replacement = w.claim(discord_only=True); assert replacement
    assert replacement['job']['leaseId'] != abandoned['job']['leaseId']
    assert not w.renew_discord_lease(abandoned) and not w.authorize_dispatch(abandoned)
    assert seal(f, w, replacement); frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('restart before intent recovers only proven unsent work with bounded backoff')

    f = Fixture(); original = f.job(); w = worker(f); old = exact_claim(f, w, original); assert old
    assert seal(f, w, old); expire(f)
    next_worker = worker(f, 'restart-owner'); recovered = next_worker.claim(discord_only=True); assert recovered
    assert recovered['reconciliation']
    newer_lease = recovered['job']['leaseId']
    late = {'state': 'provider_accepted', 'reference': base['FIRST'] + '/4444444',
            'confirmed': 'Synthetic late receipt', 'discordDeliveryEvidence': 'accepted'}
    assert not w.complete(old, late)
    assert (job_of(f)['leaseId'], job_of(f)['leaseOwner']) == (newer_lease, 'restart-owner')
    assert job_of(f)['discordReceipts'][-1]['late']
    assert next_worker.complete(recovered, f.social.reconcile(recovered['job']['manifest'], recovered['job']))
    assert len(job_of(f)['discordDispatchIntents']) == 1
    frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('restart after intent reconciles; late receipt retained without lease theft or repost')

    f = Fixture(); original = f.job(); w = worker(f)
    with patch.object(f.social, 'prepare_discord_dispatch', side_effect=TimeoutError('synthetic preflight')):
        for index in range(3):
            assert w.step(discord_only=True)
            current = job_of(f)
            assert current['state'] == ('failed' if index == 2 else 'scheduled')
            if index < 2: make_due(f)
    assert job_of(f)[policy.KEY]['deadLetter']['attempts'] == 3
    frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('three unsent transient failures dead-letter with immutable approval and zero POST')

    f = Fixture(); original = f.job(); w = worker(f); f.wire.allowed.clear()
    assert w.step(discord_only=True)
    state = state_of(f); destination = next(d for c in state['phase2']['channels'] for d in c.get('discordDestinations', []) if d['id'] == original['manifest']['destinationId'])
    assert job_of(f)['state'] == 'held' and destination['status'] == 'verification_required'
    assert w.claim(discord_only=True) is None
    frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('lost channel permission holds exact destination pending explicit reauthorization')

    f = Fixture(); original = f.job(); w = worker(f); claimed = exact_claim(f, w, original); assert claimed
    w.request_shutdown(); assert w.claim(discord_only=True) is None
    assert not w.renew_discord_lease(claimed) and w.release_discord_unsent(claimed)
    assert job_of(f)['state'] == 'scheduled' and policy.attempt_count(job_of(f)) == 0
    frozen(f, original); no_posts(f); finish_fixture(f)
    checks.append('shutdown stops admission and releases only owned proven-unsent fence')

    # Twelve continuously eligible synthetic tenants, six real SQL workers,
    # twenty-four rounds. Graceful unsent release keeps original authority and
    # avoids posting or manufacturing a new human approval for each claim.
    cohort = [Fixture() for _ in range(12)]
    originals = {f.workspace: f.job() for f in cohort}
    by_id = {f.workspace: f for f in cohort}
    fleet = [worker(cohort[0], 'fair-' + str(i)) for i in range(6)]
    service_rounds = {f.workspace: [] for f in cohort}
    attempted, completed, collisions, max_gap = 0, 0, 0, 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for round_number in range(24):
            barrier = Barrier(6)
            def fair_claim(w):
                barrier.wait(timeout=10)
                return w, w.claim(discord_only=True)
            results = list(pool.map(fair_claim, fleet)); attempted += 6
            won = [(w, c) for w, c in results if c]
            assert len(won) == 6 and len({c['workspaceId'] for _, c in won}) == 6
            for w, c in won:
                f = by_id[c['workspaceId']]
                assert sum(j.get('leaseOwner') is not None and j.get('leaseUntil', 0) > time.time() for j in state_of(f)['phase2']['jobs']) == 1
                assert w.release_discord_unsent(c)
                make_due(f); frozen(f, originals[f.workspace]); no_posts(f)
                assert not job_of(f).get('discordDispatchIntents')
                service_rounds[f.workspace].append(round_number)
                completed += 1
            collisions += 6-len(won)
    for rounds in service_rounds.values():
        assert rounds
        boundaries = [-1, *rounds, 24]
        max_gap = max(max_gap, max(b-a for a, b in zip(boundaries, boundaries[1:])))
    assert max_gap <= 3, 'A continuously eligible tenant missed the bounded service-gap target'
    report = fleet[0].discord_report()
    assert report['queue']['status'] == 'observed_sample' and report['queue']['sampled']
    cohort_metrics = {'workspaces': 12, 'workers': 6, 'rounds': 24,
        'claimAttempts': attempted, 'completedUnsentReleases': completed,
        'maximumServiceGapRounds': max_gap, 'maximumServiceGapTargetRounds': 3,
        'minimumTenantClaims': min(map(len, service_rounds.values())),
        'maximumTenantClaims': max(map(len, service_rounds.values())),
        'declinedClaims': collisions, 'duplicateIntents': 0, 'unauthorizedHandoffs': 0,
        'maximumInFlightPerTenant': 1, 'queueMetrics': report['queue']}
    for f in cohort: finish_fixture(f)
    checks.append('12-tenant 6-worker 24-round fairness, backpressure and aggregate monitoring')

    # Reproduce the reviewer's starvation trigger with the exact generic cursor
    # writes other-provider claims perform, while both Discord queues stay due.
    mixed = [Fixture(), Fixture()]
    mixed_originals = {f.workspace: f.job() for f in mixed}
    mixed_ids = {f.workspace: f for f in mixed}
    counts = {f.workspace: 0 for f in mixed}
    w = worker(mixed[0], 'mixed-provider-fairness')
    for _ in range(12):
        with connection() as db:
            db.execute('''INSERT INTO public.pr_worker_tenants(workspace_id,last_claimed_at)
                VALUES(%s,clock_timestamp()+interval '1 day')
                ON CONFLICT(workspace_id) DO UPDATE SET last_claimed_at=excluded.last_claimed_at''', (mixed[0].workspace,))
        claimed = w.claim(discord_only=True); assert claimed
        f = mixed_ids[claimed['workspaceId']]
        counts[f.workspace] += 1
        assert w.release_discord_unsent(claimed)
        make_due(f); frozen(f, mixed_originals[f.workspace]); no_posts(f)
    assert sorted(counts.values()) == [6, 6], 'Other-provider cursor updates starved a Discord tenant'
    cohort_metrics['mixedProviderCursorSimulation'] = {'rounds': 12, 'tenantClaims': sorted(counts.values()), 'status': 'PASS'}
    for f in mixed: finish_fixture(f)
    checks.append('continuous other-provider cursor updates cannot starve either Discord queue')

# Real SQL regressions for the authenticated single-job nudge. The requested
# approval is later in the same workspace than another valid eligible job.
with patch('postriff_phase2.billing.require_publishing', return_value=None), patch('postriff_phase2.billing.require_plan_capacity', return_value=None):
    from uuid import uuid4
    from postriff_phase2.contracts import digest
    from postriff_phase2.discord.authorization import approval
    f,requester=Fixture(),Fixture()
    requested=f.job();other=copy.deepcopy(requested)
    other['id']=str(uuid4())
    other['manifest']['discord']['publicationId']=other['id']
    other['approvalDigest']=digest(other['manifest'])
    other['discordAuthorization']=approval(other)
    def set_jobs(jobs):
        with connection() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(f.workspace,)).fetchone()[0]
            state['phase2']['jobs']=copy.deepcopy(jobs)
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),f.workspace))
    with connection() as db:
        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish) VALUES(%s,%s,'approver','active',true)",(f.workspace,requester.user))
    set_jobs([other,requested]);w=worker(f,'p3-exact-job-request')
    scope=dict(workspace_id=f.workspace,job_id=requested['id'],approval_digest=requested['approvalDigest'],dispatch_principal=requester.user)
    claimed=w.claim(**scope)
    assert claimed and claimed['job']['id']==requested['id'] and claimed['dispatchPrincipal']==requester.user
    assert state_of(f)['phase2']['jobs'][0]==other,'Unrequested job was mutated or dispatched'
    claimed['discordPrepared']=f.social.prepare_discord_dispatch(claimed['job']['manifest'])
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s",(f.workspace,requester.user))
    assert w.authorize_dispatch(claimed) is False,'Revoked requester reached final authorization'
    no_posts(f)
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET status='active' WHERE workspace_id=%s AND user_id=%s",(f.workspace,requester.user))
    for reason in ('stale-digest','revoked-requester'):
        set_jobs([other,requested])
        with connection() as db:
            if reason=='stale-digest':
                state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(f.workspace,)).fetchone()[0]
                state['phase2']['jobs'][1]['manifest']['payload']['text']='Changed after route read'
                db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),f.workspace))
            else:db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s",(f.workspace,requester.user))
        before=state_of(f)
        try:w.claim(**scope)
        except AlphaError as error:assert error.status==(409 if reason=='stale-digest' else 403)
        else:raise AssertionError('Scoped claim did not reject '+reason)
        assert state_of(f)==before,'Denied scoped request mutated another stored approval'
    no_posts(f)
    set_jobs([{**job,'state':'held','leaseOwner':None,'leaseUntil':0} for job in (other,requested)])
checks.append('scoped claim selects only requested job;locked digest and requester revocation checked;revocation after claim blocks final authorization;requester carried to final guard;other jobs unchanged;zero POST')

with connection() as db:
    assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.pr_discord_worker_projection'::regclass").fetchone()==(True,True)
    for role in ('anon','authenticated','service_role'):
        rights=db.execute("SELECT has_table_privilege(%s,'public.pr_discord_worker_projection','SELECT'),has_table_privilege(%s,'public.pr_discord_worker_projection','INSERT'),has_table_privilege(%s,'public.pr_discord_worker_projection','UPDATE'),has_table_privilege(%s,'public.pr_discord_worker_projection','DELETE'),has_table_privilege(%s,'public.pr_discord_worker_projection','TRUNCATE')",(role,)*5).fetchone()
        assert rights==((True,False,False,False,False) if role=='service_role' else (False,)*5)
        for signature in ('public.pr_discord_queue_number(jsonb)','public.pr_discord_projection_refresh(uuid,jsonb,bigint)','public.pr_discord_workspace_projection_trigger()'):
            assert not db.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')',(role,signature)).fetchone()[0]
for role in ('anon','authenticated'):
    try:
        with connection() as db:
            db.execute('SET LOCAL ROLE '+role)
            db.execute('SELECT count(*) FROM public.pr_discord_worker_projection')
    except Exception as error:assert getattr(error,'sqlstate',None)=='42501'
    else:raise AssertionError('Browser role read private selector')
checks.append('projection FORCE RLS;browser roles cannot read;service SELECT only;direct refresh/trigger/helper execution denied')

with patch('postriff_phase2.billing.require_publishing',return_value=None),patch('postriff_phase2.billing.require_plan_capacity',return_value=None):
    f=Fixture();original=f.job()
    with connection() as db:
        initial=db.execute('SELECT next_at,last_claimed_at,source_revision FROM public.pr_discord_worker_projection WHERE workspace_id=%s',(f.workspace,)).fetchone()
        revision,state=db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(f.workspace,)).fetchone()
        assert initial and initial[0]<=time.time() and initial[2]==revision
        state['phase2']['jobs'][0]['nextAt']=time.time()+600
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),f.workspace))
        changed=db.execute('SELECT next_at,last_claimed_at,source_revision FROM public.pr_discord_worker_projection WHERE workspace_id=%s',(f.workspace,)).fetchone()
        assert changed[0]>=state['phase2']['jobs'][0]['nextAt'] and changed[2]==revision+1
        db.rollback()
    with connection() as db:
        assert db.execute('SELECT next_at,last_claimed_at,source_revision FROM public.pr_discord_worker_projection WHERE workspace_id=%s',(f.workspace,)).fetchone()==initial
    frozen(f,original);no_posts(f);finish_fixture(f)
checks.append('source-state update and projection are atomic;rolledback schedule edit restores exact hints/revision and original approval')

with patch('postriff_phase2.billing.require_publishing',return_value=None),patch('postriff_phase2.billing.require_plan_capacity',return_value=None):
    f=Fixture();original=f.job();future=time.time()+600;change_job(f,nextAt=future)
    with connection() as db:db.execute('UPDATE public.pr_discord_worker_projection SET next_at=0 WHERE workspace_id=%s',(f.workspace,))
    assert worker(f,'forged-future-hint').claim(discord_only=True) is None,'A hint dispatched future work'
    with connection() as db:assert db.execute('SELECT next_at FROM public.pr_discord_worker_projection WHERE workspace_id=%s',(f.workspace,)).fetchone()[0]>=future
    make_due(f);owner=worker(f,'projection-lease-owner');claimed=owner.claim(discord_only=True);assert claimed
    with connection() as db:
        assert db.execute('SELECT next_at FROM public.pr_discord_worker_projection WHERE workspace_id=%s',(f.workspace,)).fetchone()[0]>=claimed['job']['leaseUntil']
        db.execute('UPDATE public.pr_discord_worker_projection SET next_at=0 WHERE workspace_id=%s',(f.workspace,))
    assert worker(f,'forged-live-lease-hint').claim(discord_only=True) is None,'A hint bypassed active lease'
    assert owner.release_discord_unsent(claimed)
    with connection() as db:
        state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(f.workspace,)).fetchone()[0]
        state['accountBlock']={'synthetic':True}
        db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),f.workspace))
        assert db.execute('SELECT next_at FROM public.pr_discord_worker_projection WHERE workspace_id=%s',(f.workspace,)).fetchone()[0] is None
    frozen(f,original);no_posts(f);finish_fixture(f)
checks.append('forged stale due hint cannot bypass future source time or live lease;source guard repairs hints;account block removes due hint;zero POST')

print('RAFII_DISCORD_WORKER_SQL_JSON ' + json.dumps({
    'status': 'PASS', 'execution': 'owned-disposable-cloud-postgres-synthetic-provider',
    'prerequisites': {'p0': 'PASS', 'p0Groups': len(base['CHECKS']),
                      'p1p2': 'PASS', 'p1p2Groups': len(prior['checks']), 'executionsEach': 1},
    'checks': checks, 'fairness': cohort_metrics, 'durationSeconds': round(time.monotonic()-started, 3),
    'productionSchemaRuntimeCompatibility': 'NOT_RUN', 'realDiscordAcceptance': 'NOT_RUN',
    'stage1000Users': 'NOT_RUN', 'stage10000Users': 'NOT_RUN'}))
