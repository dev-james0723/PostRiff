#!/usr/bin/env python3
"""Restore hazard drill: what a PostgreSQL point-in-time restore does to Rafii's Discord posting, and the procedure
that prevents duplicate posts. Local, throw-away, synthetic; rebuilds everything from scratch on every run.

Nothing here touches Production, Supabase, Vercel or the real Discord API: the clusters are local PostgreSQL 16
clusters under --work-dir (127.0.0.1 only), Discord is the in-process mock of tests/discord_restore_fixture.py, and the
application is the repository's own code (DiscordProvider, the shared request coordinator, PostgresWorker, the W-02
lane loops), pointed at whichever database the scenario names.

Phases (--phases, comma separated; default core,midrun,holdrow,liveswap):
  core      one archived first timeline with N tenants plus edge-case tenants, a base backup BEFORE any send, the
            lane sending everything to the mock, then point-in-time restores into new data directories at a point
            just after seeding and before the first send:
              A  the hazard: the same code against the restored database and the same mock, no precaution
              A2 the same with the mock enforcing nonces inside Discord's dedupe window (a replay within minutes)
              B  the procedure: hold first, show nothing is sent, reconcile (dry-run, apply, apply again), lift, run
  midrun    a restore point in the middle of the first timeline's sending run (A and B again)
  holdrow   a restored database with no policy row: the runbook's UPDATE matches nothing; the tool's verified hold
  liveswap  a restore under running cron-like lane loops (database swapped in place on the same port), operator
            hold N seconds after it is back, versus restoring on another port and holding before the swap
  timing    local restore wall time for a database padded to --size-mb with --wal-segments forced WAL switches
  reconscale reconciliation time per 1,000 posts
Results: --results (JSON). Run it under `nice`; it uses a few hundred MB under --work-dir and removes it at the end.
"""
import argparse
import copy
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('POSTRIFF_PG_BIN', '/usr/lib/postgresql/16/bin')  # the drill's default; tests require it set
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'src'), str(ROOT / 'scripts')]
import discord_lane_fixture as F  # noqa: E402
import discord_restore_fixture as R  # noqa: E402
import discord_restore_reconcile as T  # noqa: E402

P = F.P
FINAL = ('verified', 'failed', 'canceled', 'held', 'uncertain')
SCRATCH = Path('/tmp/claude-0/-home-user-PostRiff/3cb76cca-883c-52d5-850d-5dab5e917b4a/scratchpad/restore-drill')


def log(message, **values):
    stamp = time.strftime('%H:%M:%S')
    print('[%s] %s%s' % (stamp, message, (' ' + json.dumps(values, sort_keys=True)) if values else ''), flush=True)


# --- synthetic tenants and posts ---------------------------------------------------------------------------------

def build_posts(tenant, specs, *, now):
    """One workspace whose posts are (text, scheduled time) pairs, approved by the real review and approve commands."""
    with patch.object(P, 'WORKSPACE', tenant.id), patch.object(P, 'NOW', now), \
            patch.object(P, 'GUILD', tenant.guild), patch.object(P, 'FIRST', tenant.channel), \
            patch.object(P, 'SECOND', str(int(tenant.channel) + 500000)):
        engine, state, channel, variant = P.fixture()
        channel.update(discordConnectionKind='installation', qualification='server_verified', evidenceSource='live_provider')
        state['variants'].remove(variant)
        for number, (text, at) in enumerate(specs):
            draft = copy.deepcopy(variant)
            draft.update(id='synthetic-draft-%d' % number, text=text)
            state['variants'].append(draft)
            P.approve(engine, state, F._review(engine, state, channel, draft, tenant, at))
    return state


def seed(cluster, plan):
    """plan: [(tenant, [(text, at), ...])]. Inserts the workspaces and the approver's membership."""
    with cluster.connect() as db:
        db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (F.ACTOR,))
        db.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (F.ACTOR,))
        for tenant, specs in plan:
            state = build_posts(tenant, specs, now=min(at for _, at in specs) - 300)
            db.execute('INSERT INTO public.pr_workspaces(id,revision,state) VALUES(%s,1,%s::jsonb)', (tenant.id, json.dumps(state)))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply) "
                       "VALUES(%s,%s,'owner','active',true,true)", (tenant.id, F.ACTOR))


class App:
    """The application (provider, coordinator, worker) pointed at one database and one Discord."""

    def __init__(self, cluster, tenants, wire, capacity=200):
        self.cluster, self.wire = cluster, wire
        self.hosted = F.social(cluster, tenants, wire, capacity=capacity)
        self.worker = F.base_worker(cluster, self.hosted)

    def lanes(self, loops=4, seconds=30):
        return F.run_lanes(self.worker, loops, seconds=seconds)

    def drain(self, loops=4, rounds=8, seconds=30):
        """Lane rounds until a round changes nothing: no claim, or claims that neither create, verify, hold nor
        mark anything uncertain (a read-back waiting on the coordinator is re-claimed without progress)."""
        summary = Counter()
        stopped = Counter()
        for _ in range(rounds):
            results, failures = self.lanes(loops, seconds)
            if failures:
                raise RuntimeError('lane loop failed: %r' % (failures[:1],))
            progress = sum(r['counters'][k] for r in results for k in ('posted', 'verified', 'held', 'uncertain', 'deadLetters'))
            for r in results:
                summary.update({k: v for k, v in r['counters'].items() if v})
                stopped[r['stoppedBy']] += 1
            if not progress:
                break
        return {'counters': dict(summary), 'stoppedBy': dict(stopped)}

    def tick(self, flag=True):
        values = {F.discord_lane.ENV_ENABLED: 'true' if flag else 'false', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true'}
        with patch.dict(os.environ, values), F.no_billing():
            return self.worker.tick(10, 20)

    def warm(self):
        """One admitted read, so the coordinator's rows (the policy row among them) exist, as in a running system."""
        provider = self.hosted.providers['discord']
        permit = provider.rate_limiter.reserve_read('GET', '/guilds/6900000', identity=provider._rate_identity('bot'))
        provider.rate_limiter.observe(permit, {'status': 200, 'headers': {}})


def fork(wire, tenants):
    """A copy of Discord as customers see it (messages, deletions, nonce memory), with fresh request counters."""
    copy_ = R.RestoreMockDiscord(tenants, nonce_window=wire.nonce_window)
    with wire.lock:
        copy_.messages = copy.deepcopy(wire.messages)
        copy_.history = copy.deepcopy(wire.history)
        copy_.deleted = set(wire.deleted)
        copy_.nonces = dict(wire.nonces)
        copy_.log = copy.deepcopy(wire.log)
        copy_.creates = defaultdict(list, copy.deepcopy(dict(wire.creates)))
        copy_.counter = wire.counter
    copy_.inherited = len(copy_.log)
    return copy_


def wait_until(cluster, moment, limit=600):
    while True:
        now = cluster.now()
        if now >= moment:
            return now
        if moment - now > limit:
            raise RuntimeError('refusing to wait %.0f s' % (moment - now))
        time.sleep(min(1.0, moment - now + .05))


def job_index(cluster):
    return F.jobs(cluster)


# --- analysis -----------------------------------------------------------------------------------------------------

def creates(wire, since=0):
    """Distinct messages created per nonce in wire.log[since:] (a nonce-deduplicated answer creates nothing)."""
    counts = Counter()
    for entry in wire.log[since:]:
        if not entry['deduplicated']:
            counts[entry['nonce']] += 1
    return counts


def outcome(cluster, wire, truth, groups, *, since):
    """Per scenario: duplicates (a second create of a post customers already saw), first sends, states, by group."""
    jobs = job_index(cluster)
    after = creates(wire, since)
    by_group, total = {}, Counter()
    per_tenant = Counter()
    for key, job in jobs.items():
        nonce = F.nonce(job)
        group = groups.get(key[0], 'other')
        before = truth.get(nonce, 0)
        new = after.get(nonce, 0)
        row = by_group.setdefault(group, Counter())
        row['posts'] += 1
        row['state:' + job['state']] += 1
        row['sentBefore'] += before > 0
        row['duplicates'] += new if before else max(0, new - 1)
        row['firstSends'] += 1 if (new and not before) else 0
        row['sentOnceTotal'] += (before + new) == 1
        row['neverSent'] += (before + new) == 0
        if new and before:
            per_tenant[key[0]] += new
    for row in by_group.values():
        total.update(row)
    traces = {}
    for key, job in sorted(jobs.items(), key=lambda item: (groups.get(item[0][0], 'other'), item[1]['nextAt'])):
        group = groups.get(key[0], 'other')
        if group == 'main':
            continue
        nonce = F.nonce(job)
        traces.setdefault(group, []).append({
            'state': job['state'], 'createsBefore': truth.get(nonce, 0), 'createsNow': after.get(nonce, 0),
            'intents': len(job.get('discordDispatchIntents') or []), 'reference': bool(job.get('providerReference')),
            'verification': (job.get('verification') or {}).get('method'),
            'reconciliation': (job.get(T.MARKER) or {}).get('reason') or (job.get(T.MARKER) or {}).get('decision'),
            'events': [e['state'] + ': ' + e['message'][:90] for e in job.get('events', [])
                       if e.get('execution') in ('hosted-worker', T.EXECUTION)][-4:]})
    return {'groups': {g: dict(sorted(r.items())) for g, r in sorted(by_group.items())},
            'traces': traces,
            'total': dict(sorted(total.items())),
            'tenantsWithDuplicates': len(per_tenant),
            'duplicatesPerTenant': sorted(Counter(per_tenant.values()).items())}


def protections(cluster):
    """What the product recorded: states, the event messages that show a protection firing, coordinator admissions."""
    jobs = job_index(cluster)
    events = Counter()
    for job in jobs.values():
        for event in job.get('events', []):
            if event.get('execution') in ('hosted-worker', T.EXECUTION) and event['state'] in ('held', 'uncertain', 'failed', 'canceled'):
                events[event['state'] + ': ' + event['message'][:110]] += 1
    rows = cluster.sql("SELECT state, is_publish, count(*) FROM public.pr_discord_request_admissions GROUP BY 1,2 ORDER BY 1,2")
    intents = Counter(len(job.get('discordDispatchIntents') or []) for job in jobs.values())
    return {'states': dict(Counter(job['state'] for job in jobs.values())),
            'protectionEvents': dict(events.most_common()),
            'intentsPerJob': dict(sorted(intents.items())),
            'verifiedBy': dict(Counter((job.get('verification') or {}).get('method') for job in jobs.values()
                                       if job['state'] == 'verified')),
            'admissions': [{'state': s, 'publish': p, 'count': c} for s, p, c in rows]}


def restored_facts(cluster, now=None):
    """SQL facts of a restored database before any worker runs: posts look unsent, approvals still valid."""
    rows = cluster.sql("""
        SELECT j->>'state', count(*), count(*) FILTER (WHERE (j#>>'{manifest,expiresAt}')::float8 > extract(epoch from clock_timestamp())),
               count(*) FILTER (WHERE jsonb_array_length(coalesce(j->'discordDispatchIntents','[]'::jsonb))>0),
               count(*) FILTER (WHERE j ? 'providerReference' AND j->>'providerReference' IS NOT NULL)
        FROM public.pr_workspaces w, jsonb_array_elements(w.state#>'{phase2,jobs}') j
        WHERE j#>>'{manifest,platform}'='Discord' GROUP BY 1 ORDER BY 1""")
    hold = cluster.sql("SELECT count(*), count(*) FILTER (WHERE manual_hold) FROM public.pr_discord_rate_state WHERE kind='policy'")[0]
    admissions = cluster.sql("SELECT count(*) FILTER (WHERE is_publish), count(*) FROM public.pr_discord_request_admissions")[0]
    return {'jobsByState': [{'state': s, 'jobs': n, 'approvalStillValid': v, 'withIntent': i, 'withReference': r}
                            for s, n, v, i, r in rows],
            'policyRows': hold[0], 'policyRowsHeld': hold[1], 'publishAdmissions': admissions[0], 'admissions': admissions[1]}


# --- the first timeline ---------------------------------------------------------------------------------------------

class Timeline:
    """Cluster c0 (archived), base backup before any send, tenants seeded, lane sends everything, hold, stop."""

    def __init__(self, work, *, tenants=20, posts=2, edges=True, later_seconds=100, expiring_seconds=45, loops=4):
        self.work = Path(work)
        self.archive = self.work / 'archive'
        self.main = [F.Tenant(n) for n in range(tenants)]
        self.posts, self.edges, self.loops = posts, edges, loops
        self.later_seconds, self.expiring_seconds = later_seconds, expiring_seconds
        self.edge = {name: F.Tenant(900 + i) for i, name in enumerate(
            ('deleted', 'uncertain_accepted', 'uncertain_lost', 'twins', 'expiring_sent', 'expiring_unsent', 'edited',
             'later_0', 'later_1', 'later_2', 'later_3', 'canceled', 'orphan'))} if edges else {}
        self.tenants = self.main + list(self.edge.values())
        self.groups = {t.id: 'main' for t in self.main}
        self.groups.update({t.id: name.split('_')[0] if name.startswith('later') else name for name, t in self.edge.items()})

    def plan(self, now):
        plan = [(t, [('Synthetic lane post %d for %s' % (n, t.guild), now - 60) for n in range(self.posts)]) for t in self.main]
        if self.edges:
            e = self.edge
            soon = now - 60
            self.later_at = now + self.later_seconds
            self.expiring_at = now + self.expiring_seconds - 3600  # its approval ends expiring_seconds from now
            plan += [(e['deleted'], [('Synthetic post a moderator deletes, %s' % e['deleted'].guild, soon)]),
                     (e['uncertain_accepted'], [('Synthetic post whose create answer is lost, %s' % e['uncertain_accepted'].guild, soon)]),
                     (e['uncertain_lost'], [('Synthetic post whose create never arrives, %s' % e['uncertain_lost'].guild, soon)]),
                     (e['twins'], [('Synthetic twin text, %s' % e['twins'].guild, soon),
                                   ('Synthetic twin text, %s' % e['twins'].guild, self.later_at)]),
                     (e['expiring_sent'], [('Synthetic expiring post %d, %s' % (n, e['expiring_sent'].guild), self.expiring_at)
                                           for n in range(2)]),
                     (e['expiring_unsent'], [('Synthetic expiring unsent post, %s' % e['expiring_unsent'].guild, self.expiring_at)]),
                     (e['edited'], [('Synthetic post someone edits, %s' % e['edited'].guild, soon)])]
            plan += [(e['later_%d' % n], [('Synthetic later post, %s' % e['later_%d' % n].guild, self.later_at)]) for n in range(4)]
            plan += [(e['canceled'], [('Synthetic post the customer cancels, %s' % e['canceled'].guild, self.later_at)])]
        return plan

    def approve_after_restore_point(self, now):
        """A workspace (and its approved post) created after the restore point: the restored database never knew it."""
        if self.edges:
            orphan = self.edge['orphan']
            seed(self.c0, [(orphan, [('Synthetic post approved after the restore point, %s' % orphan.guild, now - 60)])])

    def cancel_in_first_timeline(self):
        """The customer cancels a queued post after the restore point, with the product's own cancel command."""
        if not self.edges:
            return
        tenant = self.edge['canceled']
        from postriff_phase2.hosted import HostedPhase2Commands
        engine = HostedPhase2Commands(clock=time.time).engine
        with self.c0.connect() as db:
            revision, state = db.execute('SELECT revision, state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',
                                         (tenant.id,)).fetchone()
            job = state['phase2']['jobs'][0]
            engine.apply_phase2(None, state, 'cancel', {'jobId': job['id']}, {'user_id': F.ACTOR})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s AND revision=%s',
                       (json.dumps(state), tenant.id, revision))

    def hooks(self, wire):
        """The first timeline's Discord trouble: a lost create answer, a create lost on the way, a refused server."""
        if not self.edges:
            return
        e = self.edge
        once = {'accepted': False, 'lost': False}

        def fail(method, path):
            if method == 'POST' and path == '/channels/%s/messages' % e['uncertain_lost'].channel and not once['lost']:
                once['lost'] = True
                raise ConnectionResetError('synthetic: the create never reached Discord')
            if method == 'GET' and path.startswith('/guilds/%s' % e['expiring_unsent'].guild):
                return {'status': 403, 'headers': {}, 'body': {'message': 'Missing Access', 'code': 50001}}
            return None

        def after(method, path, answer):
            if method == 'POST' and path == '/channels/%s/messages' % e['uncertain_accepted'].channel and not once['accepted']:
                once['accepted'] = True
                raise ConnectionResetError('synthetic: Discord created the message, the answer was lost')
        wire.fail, wire.after = fail, after

    def run(self):
        work = self.work
        t0 = time.monotonic()
        self.c0 = R.ArchivedCluster(work / 'c0', archive=self.archive).start()
        self.c0.apply_schema()
        wire = R.RestoreMockDiscord(self.tenants)
        App(self.c0, self.tenants, wire).warm()
        self.base, backup_seconds = self.c0.base_backup(work / 'base')
        self.t_base = self.c0.now()
        log('base backup taken', seconds=round(backup_seconds, 2))
        time.sleep(1.0)
        seed_now = self.c0.now()
        seed(self.c0, self.plan(seed_now))
        time.sleep(1.5)
        self.t_restore = self.c0.now()  # after every seed commit, before the first send
        time.sleep(1.5)
        self.approve_after_restore_point(self.c0.now())
        self.hooks(wire)
        app = App(self.c0, self.tenants, wire)
        log('first timeline: lane sending', tenants=len(self.tenants))
        sending = time.monotonic()
        drained = app.drain(self.loops)
        wire.fail = wire.after = None
        self.cancel_in_first_timeline()
        self.send_seconds = time.monotonic() - sending
        self.first_send = min(entry['at'] for entry in wire.log)
        jobs = job_index(self.c0)
        later = [k for k, j in jobs.items() if self.groups.get(k[0]) in ('later', 'canceled')] + \
                [k for k, j in jobs.items() if self.groups.get(k[0]) == 'twins' and j['nextAt'] > self.t_restore + 30]
        sent_late = [k for k in later if creates(wire).get(F.nonce(jobs[k]))]
        if sent_late:
            raise RuntimeError('posts scheduled after the interval were sent in the first timeline; raise later_seconds')
        # What Discord shows afterwards that Rafii did not do: a moderator deletes one post, someone edits one, people chat.
        if self.edges:
            by_nonce = {F.nonce(j): j for j in jobs.values()}
            def message_of(tenant):
                return next(entry['id'] for entry in wire.log if entry['channel'] == tenant.channel and not entry['deduplicated'])
            wire.delete(message_of(self.edge['deleted']))
            wire.edit(message_of(self.edge['edited']), 'Synthetic post someone edits, changed afterwards')
            first_main = self.main[0]
            wire.post_as_user(first_main.channel, 'Synthetic lane post 0 for %s' % first_main.guild)  # same text, not the bot
            for tenant in self.main[:5]:
                wire.post_as_user(tenant.channel, 'Synthetic chatter in %s' % tenant.guild)
            assert by_nonce
        # M-03 step 1: the operator hold in the ORIGINAL database before the restore; nothing is sent after it.
        with self.c0.connect() as db:
            self.hold_original = T.set_hold(db)
        self.t_end = self.c0.now()
        segment, failed = self.c0.flush_archive()
        self.c0.stop('fast')
        self.truth = creates(wire)
        self.wire = wire
        self.states = Counter(j['state'] for j in jobs.values())
        report = {'tenants': len(self.tenants), 'posts': len(jobs), 'baseBackupSeconds': round(backup_seconds, 2),
                  'restorePoint': R.iso(self.t_restore), 'firstSend': R.iso(self.first_send),
                  'intervalEnd': R.iso(self.t_end), 'sendSeconds': round(self.send_seconds, 2),
                  'createsInDiscord': len(wire.visible_creates()), 'statesInOriginal': dict(self.states),
                  'laneCounters': drained['counters'], 'archive': {'lastSegment': segment, 'failed': failed,
                  'segments': len(list(self.archive.iterdir()))}, 'holdInOriginal': self.hold_original,
                  'seconds': round(time.monotonic() - t0, 2)}
        log('first timeline done', **{k: report[k] for k in ('posts', 'createsInDiscord', 'sendSeconds')})
        return report


# --- scenarios ------------------------------------------------------------------------------------------------------

def scenario_hazard(timeline, name, target, *, nonce_window=None):
    """The same code, the restored database, Discord as customers see it; no precaution."""
    cluster, restore = R.restore(timeline.base, timeline.archive, target, timeline.work / name)
    try:
        facts = restored_facts(cluster)
        wire = fork(timeline.wire, timeline.tenants)
        wire.nonce_window = nonce_window
        if timeline.edges:
            wait_until(cluster, timeline.expiring_at + 3600 + 1)  # the expiring approvals end before the resume
        app = App(cluster, timeline.tenants, wire)
        run = [app.drain(timeline.loops)]
        if timeline.edges and timeline.later_at > cluster.now():
            wait_until(cluster, timeline.later_at + 1)  # so the posts never sent before are covered too
            run.append(app.drain(timeline.loops))
        result = {'restore': restore, 'restoredFacts': facts, 'lane': run,
                  'outcome': outcome(cluster, wire, timeline.truth, timeline.groups, since=wire.inherited),
                  'product': protections(cluster),
                  'nonceDeduplicated': sum(e['deduplicated'] for e in wire.log[wire.inherited:])}
    finally:
        cluster.destroy()
    log(name, duplicates=result['outcome']['total'].get('duplicates'), firstSends=result['outcome']['total'].get('firstSends'))
    return result


def scenario_procedure(timeline, name, target, *, interval_end=None):
    """Hold before any worker runs; nothing is sent; reconcile; lift; zero duplicates."""
    cluster, restore = R.restore(timeline.base, timeline.archive, target, timeline.work / name)
    try:
        facts = restored_facts(cluster)
        with cluster.connect() as db:
            held = T.set_hold(db)
        wire = fork(timeline.wire, timeline.tenants)
        app = App(cluster, timeline.tenants, wire)
        if timeline.edges:
            wait_until(cluster, timeline.expiring_at + 3600 + 1)
        calls = len(wire.calls)
        under_hold = app.drain(timeline.loops, rounds=1, seconds=10)
        tick = app.tick(flag=True)
        held_check = {'lane': under_hold, 'minuteTickClaimed': tick['processed'],
                      'discordRequests': len(wire.calls) - calls, 'creates': len(wire.log) - wire.inherited}
        reader = T.DiscordReader(wire, 'synthetic-bot-token', pace=0)
        kwargs = {'restore_point': target, 'interval_end': interval_end or timeline.t_end}
        dry, _ = T.reconcile(cluster.factory(), reader, dry_run=True, **kwargs)
        applied, decisions = T.reconcile(cluster.factory(), reader, dry_run=False, **kwargs)
        again, _ = T.reconcile(cluster.factory(), reader, dry_run=False, **kwargs)
        detail = timeline.work / (name + '-decisions.json')
        detail.write_text(json.dumps(decisions, indent=1))
        with cluster.connect() as db:
            lifted = T.lift_hold(db)
        first = app.drain(timeline.loops)
        if timeline.edges and timeline.later_at > cluster.now():
            wait_until(cluster, timeline.later_at + 1)
        second = app.drain(timeline.loops)
        result = {'restore': restore, 'restoredFacts': facts, 'hold': held, 'underHold': held_check,
                  'reconcileDryRun': dry, 'reconcileApply': applied, 'reconcileAgain': again, 'lifted': lifted,
                  'laneAfterLift': [first, second],
                  'outcome': outcome(cluster, wire, timeline.truth, timeline.groups, since=wire.inherited),
                  'product': protections(cluster), 'decisionsByGroup': decisions_by_group(decisions, timeline.groups)}
    finally:
        cluster.destroy()
    log(name, duplicates=result['outcome']['total'].get('duplicates'), decisions=result['reconcileApply']['decisions'])
    return result


def decisions_by_group(decisions, groups):
    table = defaultdict(Counter)
    for item in decisions:
        table[groups.get(item['workspaceId'], 'other')][item['decision'] + ':' + str(item['reason'] or '-')] += 1
    return {g: dict(sorted(c.items())) for g, c in sorted(table.items())}


def guarded(result, name, function, *args, **kwargs):
    """Run one scenario; keep its result or its error, so one failure does not lose the others."""
    try:
        result[name] = function(*args, **kwargs)
    except Exception as error:
        result[name] = {'error': '%s: %s' % (type(error).__name__, error), 'trace': traceback.format_exc()[-3000:]}
        log('scenario failed: ' + name, error=str(error)[:300])


def phase_core(work, args, result):
    timeline = Timeline(work / 'core', tenants=args.tenants, posts=args.posts, edges=True, loops=args.loops)
    result['firstTimeline'] = timeline.run()
    guarded(result, 'A', scenario_hazard, timeline, 'core-A', timeline.t_restore)
    guarded(result, 'A2', scenario_hazard, timeline, 'core-A2', timeline.t_restore, nonce_window=900)
    guarded(result, 'B', scenario_procedure, timeline, 'core-B', timeline.t_restore)
    return timeline


def phase_midrun(timeline, args):
    """A restore point in the middle of the sending run: about half the posts were sent before it."""
    main = sorted(e['at'] for e in timeline.wire.log if not e['deduplicated'])
    middle = len(main) // 2
    target = (main[middle - 1] + main[middle]) / 2
    result = {'restorePoint': R.iso(target), 'createsBeforePoint': middle, 'createsInFirstTimeline': len(main)}
    guarded(result, 'A', scenario_hazard, timeline, 'mid-A', target)
    guarded(result, 'B', scenario_procedure, timeline, 'mid-B', target)
    return result


def phase_holdrow(timeline, args):
    """The runbook's hold is an UPDATE: in a database restored to before the coordinator's first request it matches
    no row, and the first request then creates the policy row unheld."""
    cluster, restore = R.restore(timeline.base, timeline.archive, timeline.t_restore, timeline.work / 'holdrow')
    try:
        cluster.sql("DELETE FROM public.pr_discord_rate_state")  # as if restored to before the first request
        updated = cluster.sql("UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy'")
        wire = fork(timeline.wire, timeline.tenants)
        app = App(cluster, timeline.tenants, wire)
        results, _ = app.lanes(timeline.loops, seconds=6)
        sent = len(wire.log) - wire.inherited
        status_after_lane = restored_facts(cluster)
        with cluster.connect() as db:
            verified = T.set_hold(db)
        # A fresh restore, the verified hold with --create-missing before anything runs.
        result = {'runbookUpdateRows': updated, 'laneStoppedBy': [r['stoppedBy'] for r in results],
                  'createsWithTheUnverifiedHold': sent, 'policyRowsAfterLane': status_after_lane['policyRows'],
                  'toolHoldAfterwards': verified}
    finally:
        cluster.destroy()
    cluster, _ = R.restore(timeline.base, timeline.archive, timeline.t_restore, timeline.work / 'holdrow2')
    try:
        cluster.sql("DELETE FROM public.pr_discord_rate_state")
        with cluster.connect() as db:
            missing = T.set_hold(db)
            created = T.set_hold(db, application_id=F.APP, create_missing=True)
        wire = fork(timeline.wire, timeline.tenants)
        app = App(cluster, timeline.tenants, wire)
        results, _ = app.lanes(timeline.loops, seconds=6)
        flag_off = app.tick(flag=False)
        result.update(toolHoldWithoutRow=missing, toolHoldCreateMissing=created,
                      laneStoppedByAfterCreate=[r['stoppedBy'] for r in results],
                      createsAfterCreate=len(wire.log) - wire.inherited,
                      flagOffMinuteTickUnderHold={'processed': flag_off['processed'],
                                                  'rateDelays': flag_off.get('discordWorker', {}).get('counters', {}).get('rateDelays'),
                                                  'creates': len(wire.log) - wire.inherited})
    finally:
        cluster.destroy()
    log('holdrow', **{k: result[k] for k in ('runbookUpdateRows', 'createsWithTheUnverifiedHold', 'createsAfterCreate')})
    return result


# --- a restore under running loops ------------------------------------------------------------------------------------

class Tagged:
    """The transport one invocation sees: Discord itself, plus a note of which invocation made each create."""

    def __init__(self, wire, number, notes):
        self.wire, self.number, self.notes = wire, number, notes

    def __call__(self, method, url, **kwargs):
        answer = self.wire(method, url, **kwargs)
        if method == 'POST' and isinstance(answer, dict) and answer.get('status') == 200:
            self.notes.append({'invocation': self.number, 'at': time.time(), 'id': (answer.get('body') or {}).get('id')})
        return answer


class Cron:
    """A cron that starts one lane invocation every `period` seconds (shards round robin), each on a fresh provider
    (a cold function instance), until stopped. `build` is the deployment new invocations run: 'normal', or 'paused'
    (the same code with a rate policy that does not parse, so its coordinator refuses every Discord request).
    Records every invocation's build, start, end, error and counters, and which invocation made each create."""

    def __init__(self, cluster, tenants, wire, *, period=1.0, seconds=8, shards=4):
        self.cluster, self.tenants, self.wire = cluster, tenants, wire
        self.period, self.seconds, self.shards = period, seconds, shards
        self.build = 'normal'
        self.stop = threading.Event()
        self.invocations, self.threads, self.notes = {}, [], []
        self.lock = threading.Lock()

    def one(self, number):
        record = {'shard': number % self.shards, 'started': time.time(), 'build': self.build}
        with self.lock:
            self.invocations[number] = record
        try:
            app = App(self.cluster, self.tenants, Tagged(self.wire, number, self.notes))
            if record['build'] == 'paused':
                provider = app.hosted.providers['discord']
                # What OAuthService does at startup when POSTRIFF_DISCORD_RATE_POLICY does not parse.
                provider.rate_limiter, provider.rate_coordinator_degraded = None, True
            values = {**F.LANE_ENV, 'POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS': str(self.seconds)}
            with F.no_billing():
                result = F.discord_lane.run(app.worker, number % self.shards, values)
                if record['build'] == 'paused':
                    tick = app.tick(flag=True)  # the paused build's minute cron as well
                    record['tickProcessed'] = tick['processed']
            record.update(stoppedBy=result['stoppedBy'], posted=result['counters']['posted'],
                          claimed=result['counters']['claimed'])
        except BaseException as error:  # a function invocation that errors: the next cron minute starts another
            record.update(error=type(error).__name__)
        record['ended'] = time.time()

    def loop(self):
        number = 0
        while not self.stop.is_set():
            thread = threading.Thread(target=self.one, args=(number,), daemon=True)
            thread.start()
            self.threads.append(thread)
            number += 1
            self.stop.wait(self.period)

    def running(self, build):
        with self.lock:
            return [r for r in self.invocations.values() if r['build'] == build and 'ended' not in r]

    def __enter__(self):
        self.runner = threading.Thread(target=self.loop, daemon=True)
        self.runner.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.runner.join()
        for thread in self.threads:
            thread.join(timeout=self.seconds + 120)


def phase_liveswap(work, args):
    """A restore under the lane's running cron. Three orders:
    in_place      the database is replaced at the same address while the cron keeps firing; the operator sets the
                  hold `--hold-delay` seconds after it is back (what M-03 section 6 step 2 describes)
    hold_first    the restore goes to another address, the hold is set there, then it takes the old address
    paused_build  before the restore the cron runs a build whose rate policy does not parse (a stop that does not
                  live in the database); in-place restore; hold; the normal build again; reconcile; lift"""
    results = {}
    for variant in ('in_place', 'hold_first', 'paused_build'):
        base_dir = work / ('swap-' + variant)
        shutil.rmtree(base_dir, ignore_errors=True)
        tenants = [F.Tenant(500 + n) for n in range(args.swap_tenants)]
        trickle = [F.Tenant(600 + n) for n in range(12)]
        everyone = tenants + trickle
        port = R.free_port()
        c0 = R.ArchivedCluster(base_dir / 'c0', port=port, archive=base_dir / 'archive').start()
        restored = None
        try:
            c0.apply_schema()
            wire = R.RestoreMockDiscord(everyone)
            App(c0, everyone, wire).warm()
            base, _ = c0.base_backup(base_dir / 'base')
            now = c0.now()
            # Posts due now, and a trickle due every few seconds so loops are alive (idle-waiting) across the swap.
            seed(c0, [(t, [('Synthetic swap post for %s' % t.guild, now - 60)]) for t in tenants] +
                 [(t, [('Synthetic trickle post for %s' % t.guild, now + 5 + 3 * n)]) for n, t in enumerate(trickle)])
            time.sleep(1.5)
            target = c0.now()
            time.sleep(1.5)
            extra = {}
            with Cron(c0, everyone, wire, period=1.0, seconds=8) as cron:
                deadline = time.monotonic() + 90
                ids = {t.id for t in tenants}
                while time.monotonic() < deadline:
                    states = Counter(j['state'] for k, j in F.jobs(c0).items() if k[0] in ids)
                    if states.get('verified', 0) == len(tenants):
                        break
                    time.sleep(.5)
                if variant == 'paused_build':
                    cron.build = 'paused'  # promote the paused twin, then wait for the normal build's invocations to end
                    waited = time.monotonic()
                    while cron.running('normal') and time.monotonic() - waited < 60:
                        time.sleep(.2)
                    extra['waitedForNormalInvocationsSeconds'] = round(time.monotonic() - waited, 1)
                first_creates = len(wire.visible_creates())
                truth = creates(wire)
                c0.flush_archive()
                swap_started = time.time()
                if variant in ('in_place', 'paused_build'):
                    c0.stop('immediate')  # the in-place restore takes the database away under the running loops
                    restored, report = R.restore(base, base_dir / 'archive', target, base_dir / 'restored', port=port)
                    back = time.time()
                    time.sleep(args.hold_delay)  # the same window for both: the operator needs a few seconds
                    with restored.connect() as db:
                        hold = T.set_hold(db)
                    held_at = time.time()
                    if variant == 'paused_build':
                        cron.build = 'normal'  # promote the normal build again: the database hold now stops it
                else:
                    restored, report = R.restore(base, base_dir / 'archive', target, base_dir / 'restored')  # elsewhere
                    with restored.connect() as db:
                        hold = T.set_hold(db)  # before the application can reach it
                    held_at = time.time()
                    c0.stop('immediate')
                    restored.stop('fast')
                    restored.configure({'port': str(port)})
                    restored.port, restored.dsn = port, c0.dsn
                    restored.start()
                    back = time.time()
                time.sleep(8)
                if variant == 'paused_build':
                    reader = T.DiscordReader(wire, 'synthetic-bot-token', pace=0)
                    applied, _ = T.reconcile(restored.factory(), reader, restore_point=target, interval_end=swap_started,
                                             dry_run=False)
                    extra['reconcile'] = {k: applied[k] for k in ('decisions', 'reasons', 'write')}
                    with restored.connect() as db:
                        extra['lifted'] = T.lift_hold(db)
                    lifted_at = time.time()
                    time.sleep(12)
                    extra['afterLift'] = {'creates': sum(1 for e in wire.log if not e['deduplicated'] and e['at'] > lifted_at),
                                          'duplicates': sum(1 for e in wire.log if not e['deduplicated'] and e['at'] > lifted_at
                                                            and truth.get(e['nonce'])),
                                          'states': dict(Counter(j['state'] for j in F.jobs(restored).values()))}
            after = Counter()
            for entry in wire.log:
                if not entry['deduplicated'] and entry['at'] > swap_started:
                    after['beforeHold' if entry['at'] <= held_at else 'afterHold'] += 1
            duplicates = [e for e in wire.log if not e['deduplicated'] and e['at'] > swap_started and truth.get(e['nonce'])]
            by_message = {note['id']: note['invocation'] for note in cron.notes}
            started = {n: r['started'] for n, r in cron.invocations.items()}
            senders = Counter('startedBeforeSwap' if started[by_message[e['id']]] < swap_started else
                              'startedDuringDowntime' if started[by_message[e['id']]] < back else 'startedAfterBack'
                              for e in duplicates if e['id'] in by_message)
            records = list(cron.invocations.values())
            results[variant] = {
                'posts': len(tenants), 'trickle': len(trickle), 'firstTimelineCreates': first_creates,
                'restore': report, 'downSeconds': round(back - swap_started, 2),
                'holdSecondsAfterBack': round(held_at - back, 2), 'hold': hold, 'createsAfterSwap': dict(after),
                'duplicates': len(duplicates), 'duplicatesBySender': dict(senders),
                'invocations': {'startedBeforeSwap': summarize([r for r in records if r['started'] < swap_started], swap_started),
                                'startedDuringDowntime': summarize([r for r in records if swap_started <= r['started'] < back], swap_started),
                                'startedAfterBack': summarize([r for r in records if r['started'] >= back], swap_started)},
                **extra}
            log('liveswap ' + variant, duplicates=len(duplicates), after=dict(after), senders=dict(senders))
        finally:
            if restored is not None:
                restored.destroy()
            c0.destroy()
    return results


def summarize(records, swap):
    alive = [r for r in records if r.get('ended', float('inf')) > swap]
    return {'count': len(records), 'aliveAtSwap': len(alive),
            'builds': dict(Counter(r['build'] for r in records)),
            'errors': dict(Counter(r.get('error') for r in records if r.get('error'))),
            'stoppedBy': dict(Counter(r.get('stoppedBy') for r in records if r.get('stoppedBy'))),
            'posted': sum(r.get('posted', 0) for r in records),
            'pausedTickProcessed': sum(r.get('tickProcessed', 0) for r in records)}


# --- local timing ------------------------------------------------------------------------------------------------------

def phase_timing(work, args):
    """Local restore wall time: a database padded to --size-mb, a base backup, then --wal-segments forced WAL
    switches with --wal-updates workspace updates each (one production day at archive_timeout 120 s is 720), a
    compressed archive, and a restore to the last commit. LOCAL figure on this machine, not Supabase's."""
    root = work / 'timing'
    shutil.rmtree(root, ignore_errors=True)
    archive = root / 'archive'
    gz = "'test ! -f \"%s/%%f.gz\" && gzip -1 -c \"%%p\" > \"%s/%%f.gz.tmp\" && mv \"%s/%%f.gz.tmp\" \"%s/%%f.gz\"'" % ((archive,) * 4)
    cluster = R.ArchivedCluster(root / 'c0', archive=archive, wal_segsize=args.wal_segsize, archive_timeout=120,
                                fsync=True, extra={'archive_command': gz, 'wal_recycle': 'off', 'wal_init_zero': 'off',
                                                   'max_wal_size': "'1GB'", 'checkpoint_timeout': "'5min'"})
    cluster.start()
    report = {'label': 'LOCAL measurement on this shared 4-core machine; not a Supabase figure'}
    try:
        cluster.apply_schema()
        started = time.monotonic()
        cluster.sql("CREATE TABLE public.drill_padding(id bigserial PRIMARY KEY, payload text NOT NULL)")
        chunk = 0
        while cluster.sql('SELECT pg_database_size(current_database())')[0][0] < args.size_mb * 1024 * 1024:
            cluster.sql("INSERT INTO public.drill_padding(payload) SELECT string_agg(md5(random()::text||g||%s), '') "
                        "FROM generate_series(1,60) g, generate_series(1,2000) r GROUP BY r", (chunk,))
            chunk += 1
        workspaces = 400
        cluster.sql("""INSERT INTO public.pr_workspaces(id,revision,state)
            SELECT gen_random_uuid(),1,jsonb_build_object('drill',true,'blob',(SELECT string_agg(md5(random()::text||g),'')
                FROM generate_series(1,200) g)) FROM generate_series(1,%s)""", (workspaces,))
        size = cluster.sql('SELECT pg_database_size(current_database())')[0][0]
        report['padSeconds'] = round(time.monotonic() - started, 1)
        report['databaseMB'] = round(size / 1048576, 1)
        base, report['baseBackupSeconds'] = cluster.base_backup(root / 'base')
        report['baseBackupSeconds'] = round(report['baseBackupSeconds'], 2)
        start_lsn = cluster.sql('SELECT pg_current_wal_lsn()')[0][0]
        started = time.monotonic()
        for segment in range(args.wal_segments):
            cluster.sql("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{blob}',to_jsonb(md5(random()::text)||(state->>'blob'))), "
                        "revision=revision+1 WHERE id IN (SELECT id FROM public.pr_workspaces WHERE state ? 'drill' "
                        "ORDER BY random() LIMIT %s)", (args.wal_updates,))
            cluster.sql('SELECT pg_switch_wal()')
        target = cluster.now()
        cluster.sql("UPDATE public.pr_workspaces SET revision=revision+1 WHERE id=(SELECT id FROM public.pr_workspaces LIMIT 1)")
        end_lsn = cluster.sql('SELECT pg_current_wal_lsn()')[0][0]
        report['walBytes'] = cluster.sql('SELECT pg_wal_lsn_diff(%s,%s)::bigint', (end_lsn, start_lsn))[0][0]
        cluster.flush_archive(timeout=600)
        report['walGenerationSeconds'] = round(time.monotonic() - started, 1)
        report['walSegments'] = args.wal_segments
        report['walSegmentMB'] = args.wal_segsize
        report['archiveMB'] = round(sum(f.stat().st_size for f in archive.iterdir()) / 1048576, 1)
        cluster.stop('fast')
        restore_cmd = "'gzip -dc \"%s/%%f.gz\" > \"%%p\"'" % archive
        restored_root = root / 'restored'
        started = time.monotonic()
        restored = R.ArchivedCluster(restored_root, initialize=False)
        shutil.copytree(base, restored.data, symlinks=True)
        os.chmod(restored.data, 0o700)
        copied = time.monotonic() - started
        restored.configure({'port': str(restored.port), 'archive_mode': 'off', 'restore_command': restore_cmd,
                            'recovery_target_time': "'%s'" % R.iso(target), 'recovery_target_action': "'promote'",
                            'recovery_target_timeline': "'current'"})
        (restored.data / 'recovery.signal').touch()
        restored.start(timeout=3600)
        while restored.sql('SELECT pg_is_in_recovery()')[0][0]:
            time.sleep(.2)
        report['restore'] = {'copySeconds': round(copied, 2), 'wallSeconds': round(time.monotonic() - started, 2)}
        report['restoredDatabaseMB'] = round(restored.sql('SELECT pg_database_size(current_database())')[0][0] / 1048576, 1)
        restored.destroy()
    finally:
        cluster.destroy()
        shutil.rmtree(root, ignore_errors=True)
    log('timing', **report['restore'])
    return report


def phase_reconscale(work, args):
    """Reconciliation time for --scale-posts posts (every one already in Discord), per 1,000 posts."""
    root = work / 'reconscale'
    shutil.rmtree(root, ignore_errors=True)
    cluster = R.ArchivedCluster(root / 'c0').start()
    try:
        cluster.apply_schema()
        per = 5
        tenants = [F.Tenant(2000 + n) for n in range(args.scale_posts // per)]
        wire = R.RestoreMockDiscord(tenants)
        App(cluster, tenants, wire).warm()
        now = cluster.now()
        started = time.monotonic()
        seed(cluster, [(t, [('Synthetic scale post %d for %s' % (n, t.guild), now - 60) for n in range(per)]) for t in tenants])
        seeded = time.monotonic() - started
        restore_point = cluster.now()
        time.sleep(1.0)
        for (workspace, _), job in F.jobs(cluster).items():  # as if the old timeline had sent every post
            target = job['manifest']['discord']['target']
            with wire.lock:
                wire._new_message(target['channelId'], job['manifest']['payload']['text'], {'id': F.BOT, 'bot': True})
        interval_end = cluster.now()
        with cluster.connect() as db:
            T.set_hold(db)
        reader = T.DiscordReader(wire, 'synthetic-bot-token', pace=0)
        dry, _ = T.reconcile(cluster.factory(), reader, restore_point=restore_point, interval_end=interval_end, dry_run=True)
        reader = T.DiscordReader(wire, 'synthetic-bot-token', pace=0)
        applied, _ = T.reconcile(cluster.factory(), reader, restore_point=restore_point, interval_end=interval_end, dry_run=False)
        posts = len(tenants) * per
        result = {'posts': posts, 'channels': len(tenants), 'seedSeconds': round(seeded, 1),
                  'dryRun': {k: dry[k] for k in ('seconds', 'discordRequests', 'decisions')},
                  'apply': {k: applied[k] for k in ('seconds', 'discordRequests', 'decisions', 'write')},
                  'applySecondsPer1000': round(applied['seconds'] * 1000 / posts, 2),
                  'dryRunSecondsPer1000': round(dry['seconds'] * 1000 / posts, 2),
                  'requestsPer1000': round(applied['discordRequests'] * 1000 / posts),
                  'note': 'mock Discord answers in microseconds; with the tool pacing 0.25 s per request a real run '
                          'needs about requestsPer1000 x 0.25 s per 1,000 posts, plus any 429 waits'}
    finally:
        cluster.destroy()
        shutil.rmtree(root, ignore_errors=True)
    log('reconscale', **{k: result[k] for k in ('posts', 'applySecondsPer1000', 'requestsPer1000')})
    return result


# --- summary ---------------------------------------------------------------------------------------------------------

def summary(results):
    """The counts the drill record quotes, as plain lines (`--summary results.json`)."""
    lines = []
    def scenario(label, data):
        if not isinstance(data, dict) or 'outcome' not in data:
            lines.append('%s: %s' % (label, (data or {}).get('error', 'missing') if isinstance(data, dict) else data))
            return
        total = data['outcome']['total']
        lines.append('%s: posts %d, sent before the restore point or in the rewound interval %d, duplicates %d, '
                     'first sends %d, sent exactly once overall %d, never sent %d, final states %s' % (
                         label, total.get('posts', 0), total.get('sentBefore', 0), total.get('duplicates', 0),
                         total.get('firstSends', 0), total.get('sentOnceTotal', 0), total.get('neverSent', 0),
                         {k[6:]: v for k, v in total.items() if k.startswith('state:')}))
        lines.append('   tenants with duplicates %d, duplicates per tenant %s' % (
            data['outcome']['tenantsWithDuplicates'], data['outcome']['duplicatesPerTenant']))
        for group, row in data['outcome']['groups'].items():
            lines.append('   %-20s %s' % (group, {k: v for k, v in row.items() if v}))
        if 'reconcileApply' in data:
            for key in ('reconcileDryRun', 'reconcileApply', 'reconcileAgain'):
                item = data[key]
                lines.append('   %s: decisions %s reasons %s write %s requests %s seconds %s' % (
                    key, item['decisions'], item['reasons'], item.get('write'), item['discordRequests'], item['seconds']))
            lines.append('   under hold: %s' % data['underHold'])
            lines.append('   decisions by group: %s' % data['decisionsByGroup'])
        lines.append('   product: %s' % {k: data['product'][k] for k in ('states', 'protectionEvents', 'verifiedBy')})
        if 'nonceDeduplicated' in data:
            lines.append('   nonce-deduplicated answers: %d' % data['nonceDeduplicated'])
        lines.append('   restore: %s; facts before any worker: %s' % (data['restore'], data['restoredFacts']))
    core = results.get('core', {})
    if 'firstTimeline' in core:
        lines.append('first timeline: %s' % {k: core['firstTimeline'][k] for k in (
            'tenants', 'posts', 'createsInDiscord', 'statesInOriginal', 'restorePoint', 'firstSend', 'intervalEnd',
            'sendSeconds', 'archive', 'holdInOriginal')})
    for name in ('A', 'A2', 'B'):
        scenario('core ' + name, core.get(name))
    mid = results.get('midrun', {})
    if mid:
        lines.append('midrun: restore point %s, creates before it %s of %s' % (
            mid.get('restorePoint'), mid.get('createsBeforePoint'), mid.get('createsInFirstTimeline')))
        for name in ('A', 'B'):
            scenario('midrun ' + name, mid.get(name))
    for name in ('holdrow', 'liveswap', 'timing', 'reconscale'):
        if name in results:
            lines.append('%s: %s' % (name, json.dumps(results[name], default=str)[:4000]))
    lines.append('seconds per phase: %s' % results.get('seconds'))
    return '\n'.join(lines)


# --- main --------------------------------------------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--work-dir', default=str(SCRATCH / 'run'))
    parser.add_argument('--results', default=None)
    parser.add_argument('--phases', default='core,midrun,holdrow,liveswap')
    parser.add_argument('--tenants', type=int, default=20)
    parser.add_argument('--posts', type=int, default=2)
    parser.add_argument('--loops', type=int, default=4)
    parser.add_argument('--hold-delay', type=int, default=3)
    parser.add_argument('--swap-tenants', type=int, default=12)
    parser.add_argument('--size-mb', type=int, default=237)
    parser.add_argument('--wal-segments', type=int, default=720)
    parser.add_argument('--wal-updates', type=int, default=20)
    parser.add_argument('--wal-segsize', type=int, default=16)
    parser.add_argument('--scale-posts', type=int, default=1000)
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--summary', help='print the summary of an earlier results file and exit')
    args = parser.parse_args(argv)
    if args.summary:
        print(summary(json.loads(Path(args.summary).read_text())))
        return 0
    if not R.available():
        print('needs PostgreSQL server binaries (POSTRIFF_PG_BIN) and psycopg', file=sys.stderr)
        return 2
    work = Path(args.work_dir)
    shutil.rmtree(work, ignore_errors=True)  # every run starts from nothing
    work.mkdir(parents=True)
    os.chmod(work, 0o755)
    results_path = Path(args.results) if args.results else work.parent / ('results-%s.json' % time.strftime('%Y%m%dT%H%M%S'))
    sha = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    results = {'meta': {'sha': sha, 'started': R.iso(time.time()), 'load': os.getloadavg(),
                        'postgres': subprocess.run([str(R.PG_BIN / 'postgres'), '--version'], capture_output=True,
                                                   text=True).stdout.strip(), 'args': vars(args)}}
    phases = [p.strip() for p in args.phases.split(',') if p.strip()]
    timeline = None
    try:
        for phase in phases:
            started = time.monotonic()
            log('phase ' + phase)
            try:
                if phase == 'core':
                    results['core'] = {}
                    timeline = phase_core(work, args, results['core'])
                elif phase in ('midrun', 'holdrow'):
                    if timeline is None:
                        raise RuntimeError(phase + ' needs the core phase first')
                    results[phase] = (phase_midrun if phase == 'midrun' else phase_holdrow)(timeline, args)
                elif phase == 'liveswap':
                    results[phase] = phase_liveswap(work, args)
                elif phase == 'timing':
                    results[phase] = phase_timing(work, args)
                elif phase == 'reconscale':
                    results[phase] = phase_reconscale(work, args)
                else:
                    raise RuntimeError('unknown phase ' + phase)
            except Exception as error:
                results[phase] = {'error': '%s: %s' % (type(error).__name__, error), 'trace': traceback.format_exc()[-3000:]}
                log('phase failed: ' + phase, error=str(error)[:300])
            results.setdefault('seconds', {})[phase] = round(time.monotonic() - started, 1)
            results_path.write_text(json.dumps(results, indent=1, default=str))
    finally:
        if timeline is not None and getattr(timeline, 'c0', None):
            timeline.c0.destroy()
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        results['meta']['finished'] = R.iso(time.time())
        results_path.write_text(json.dumps(results, indent=1, default=str))
        log('results written', path=str(results_path))
    return 0 if not any(isinstance(v, dict) and 'error' in v for v in results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
