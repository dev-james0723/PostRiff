"""Customer impact evidence: the paths EVERY customer takes, run on the live tree and on the candidate tree.

One disposable PostgreSQL cluster gets the schema Production has (the RLS harness plus the Discord migrations 124-131),
copied into one database per tree. tests/impact_scenario.py then runs the same scenario with each tree's code (three
first sign-ins, one ordinary LinkedIn post prepared and approved, workspace and Channels reads for everyone, one minute
tick of the worker), with Production's provider configuration (fake credentials; the four Discord flags, the rate
policy and the worker budget set as on 2026-10-23; for the candidate also the dark build's command-line variables:
reviewed flag, cap 10000 and a gate naming one other workspace) and every provider transport refused. tests/impact_state_probe.py
runs the code behind every workspace read and command on the resulting stored state with each tree.

A plain test proves "same as live". A test whose name says it pins a difference documents an accepted difference with
its exact size. A test marked expectedFailure states the behaviour the candidate should have and does not: it is a
finding in docs/CUSTOMER-IMPACT-INVENTORY.md; remove the decorator when the finding is fixed (an unexpected success
fails the run on purpose).

Needs POSTRIFF_PG_BIN (initdb, pg_ctl, psql) and psycopg; both revisions must be in the clone (IMPACT_LIVE_REV,
IMPACT_RC_REV, default live c5fc1fd1 and HEAD). Read-only on the repository: trees come from `git archive`.
"""
import collections
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_REV = os.environ.get('IMPACT_LIVE_REV', 'c5fc1fd10350f3142ec6f34b2c373139e85abb39')
RC_REV = os.environ.get('IMPACT_RC_REV', 'HEAD')
PG_BIN = os.environ.get('POSTRIFF_PG_BIN')
FENCED = '1' in (os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE'), os.environ.get('RAFII_LINKEDIN_SYNTHETIC_FENCE'))
# Applied in Production (S-05) but not part of the generic RLS harness.
DISCORD_MIGRATIONS = ('124_discord_rate_limits', '125_discord_service_grants', '126_discord_worker_projection',
                      '128_discord_lease_protocol_fence', '131_discord_interactions')
WORKSPACES = 3
try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


def _rev(rev):
    done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', rev + '^{commit}'], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def _statements(record, phase):
    """Statement shapes with random savepoint suffixes removed."""
    return collections.Counter(re.sub(r'(SAVEPOINT [a-z_]+?)_[0-9a-f]{8}', r'\1_<id>', s) for s in record['phases'][phase]['statements'])


def _delta(live, rc, phase):
    a, b = _statements(live, phase), _statements(rc, phase)
    return {s: b[s] - a[s] for s in set(a) | set(b) if a[s] != b[s]}


@unittest.skipIf(FENCED, 'the synthetic transport fence refuses databases other than the guarded runner\'s')
@unittest.skipUnless(PG_BIN and psycopg and (Path(PG_BIN or '/nonexistent') / 'initdb').exists(), 'needs POSTRIFF_PG_BIN and psycopg')
@unittest.skipUnless(_rev(LIVE_REV) and _rev(RC_REV), 'both revisions must be present in this clone')
class SharedPathsLiveVersusCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runas = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else []
        cls.tmp = tempfile.mkdtemp(prefix='primpact-', dir='/tmp')
        os.chmod(cls.tmp, 0o755)
        cls.data, cls.sock, cls.port = Path(cls.tmp) / 'data', Path(cls.tmp) / 'sock', _free_port()
        user = ' user=postgres' if cls.runas else ''
        cls.dsn = lambda database: 'host=%s port=%d dbname=%s%s' % (cls.sock, cls.port, database, user)
        try:
            cls.trees = {}
            for name, rev, paths in (('live', LIVE_REV, ['src', 'api']), ('rc', RC_REV, ['src', 'api', 'tests/phase2', 'migrations'])):
                tree = Path(cls.tmp) / name
                tree.mkdir()
                archive = subprocess.run(['git', '-C', str(ROOT), 'archive', _rev(rev), *paths], capture_output=True, check=True)
                subprocess.run(['tar', '-x', '-C', str(tree)], input=archive.stdout, check=True)
                cls.trees[name] = tree
            if cls.runas:
                shutil.chown(cls.tmp, 'postgres', 'postgres')
            cls._run('mkdir', str(cls.sock))
            cls._run(str(Path(PG_BIN) / 'initdb'), '-D', str(cls.data), '-A', 'trust', '--no-locale', '-E', 'UTF8')
            cls._run(str(Path(PG_BIN) / 'pg_ctl'), '-D', str(cls.data), '-l', str(Path(cls.tmp) / 'postgres.log'),
                     '-o', '-k %s -p %d -h ""' % (cls.sock, cls.port), '-w', 'start')
            psql = [str(Path(PG_BIN) / 'psql'), '-X', '-q', '-v', 'ON_ERROR_STOP=1']
            subprocess.run(psql + [cls.dsn('postgres'), '-c', 'CREATE DATABASE impact_template'], check=True, capture_output=True)
            subprocess.run(psql + [cls.dsn('impact_template'), '-f', str(cls.trees['rc'] / 'tests/phase2/rls.sql')], check=True, capture_output=True)
            for migration in DISCORD_MIGRATIONS:
                subprocess.run(psql + [cls.dsn('impact_template'), '-f', str(cls.trees['rc'] / 'migrations/postriff' / (migration + '.sql'))],
                               check=True, capture_output=True)
            policy = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'discord_rate_policy.py'), 'generate'],
                                    capture_output=True, text=True, check=True).stdout.strip()
            cls.records, cls.probes = {}, {}
            for name in ('live', 'rc'):
                subprocess.run(psql + [cls.dsn('postgres'), '-c', 'CREATE DATABASE impact_%s TEMPLATE impact_template' % name], check=True, capture_output=True)
                done = subprocess.run([sys.executable, str(ROOT / 'tests' / 'impact_scenario.py'), '--tree', str(cls.trees[name]),
                                       '--dsn', cls.dsn('impact_' + name)], capture_output=True, text=True, timeout=600,
                                      env={**os.environ, 'IMPACT_RATE_POLICY': policy, 'PYTHONDONTWRITEBYTECODE': '1',
                                           # The candidate runs as the dark build D1 would serve it; live as dpl_47SG.
                                           'IMPACT_BUILD': 'dark' if name == 'rc' else 'live'})
                if done.returncode:
                    raise RuntimeError('scenario failed on %s: %s' % (name, done.stderr[-2000:]))
                cls.records[name] = json.loads(done.stdout)
            stored = Path(cls.tmp) / 'owner-state.json'
            stored.write_text(json.dumps(cls.records['rc']['ownerState']))
            for name in ('live', 'rc'):
                done = subprocess.run([sys.executable, str(ROOT / 'tests' / 'impact_state_probe.py'), str(cls.trees[name]), str(stored)],
                                      capture_output=True, text=True, timeout=300, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                if done.returncode:
                    raise RuntimeError('state probe failed on %s: %s' % (name, done.stderr[-2000:]))
                cls.probes[name] = json.loads(done.stdout)
            if os.environ.get('IMPACT_REPORT'):
                summary = {name: {phase: {'connections': r['phases'][phase]['connections'], 'statements': len(r['phases'][phase]['statements']),
                                          'writes': collections.Counter(r['phases'][phase]['writes'])}
                                  for phase in r['phases']} for name, r in cls.records.items()}
                Path(os.environ['IMPACT_REPORT']).write_text(json.dumps(summary, indent=1, sort_keys=True))
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def _run(cls, *args):
        done = subprocess.run([*cls.runas, *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if done.returncode:
            raise RuntimeError('%s failed (%d): %s' % (args[0], done.returncode, done.stderr.strip()))

    @classmethod
    def tearDownClass(cls):
        try:
            if (cls.data / 'postmaster.pid').exists():
                subprocess.run([*cls.runas, str(Path(PG_BIN) / 'pg_ctl'), '-D', str(cls.data), '-m', 'fast', '-w', 'stop'],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            shutil.rmtree(cls.tmp, ignore_errors=True)

    @property
    def live(self):
        return self.records['live']

    @property
    def rc(self):
        return self.records['rc']

    def same_effects(self, phase):
        for name in ('live', 'rc'):
            self.assertEqual(self.records[name]['phases'][phase]['http'], [], '%s %s: no provider request' % (name, phase))
        self.assertEqual(collections.Counter(self.live['phases'][phase]['writes']), collections.Counter(self.rc['phases'][phase]['writes']))
        self.assertEqual(self.live['phases'][phase]['rowsChanged'], self.rc['phases'][phase]['rowsChanged'])

    # --- sign-in ---------------------------------------------------------------------------------------------------------
    def test_first_sign_in_bootstrap_is_identical_to_live(self):
        self.assertEqual(self.live['errors'], [])
        self.assertEqual(self.rc['errors'], [])
        self.same_effects('bootstrap')
        self.assertEqual(self.live['phases']['bootstrap']['connections'], self.rc['phases']['bootstrap']['connections'])
        self.assertEqual(_delta(self.live, self.rc, 'bootstrap'), {}, 'the same statements, in number and shape')

    # --- an ordinary post -----------------------------------------------------------------------------------------------
    def test_preparing_and_approving_an_ordinary_post_writes_what_live_writes(self):
        self.assertEqual(self.live['prepared'], {'reviewStatus': 'approved', 'jobState': 'scheduled'})
        self.assertEqual(self.rc['prepared'], self.live['prepared'])
        self.same_effects('prepare')

    def test_pins_that_review_preparation_skips_the_publishing_entitlement_check(self):
        """Finding SC-1 (hosted.py, commit ea59babb): p2_review no longer calls require_publishing. One review was prepared,
        so exactly one entitlement read set is missing; approval still checks it."""
        delta = _delta(self.live, self.rc, 'prepare')
        self.assertEqual(sorted(delta.values()), [-1, -1, -1], delta)
        self.assertTrue(any('pr_subscriptions' in s for s in delta) and any('pr_trials' in s for s in delta), delta)

    # --- reads ----------------------------------------------------------------------------------------------------------
    def test_workspace_and_channels_reads_write_nothing_and_call_no_provider(self):
        for name in ('live', 'rc'):
            phase = self.records[name]['phases']['read']
            self.assertEqual((phase['writes'], phase['rowsChanged'], phase['http']), ([], {}, []), name)

    def test_workspace_read_differs_only_by_a_null_worker_binding(self):
        live, rc = self.probes['live']['present'], dict(self.probes['rc']['present'])
        self.assertIsNone(rc.pop('workerBinding'))
        self.assertEqual(json.dumps(live, sort_keys=True), json.dumps(rc, sort_keys=True))
        for a, b in zip(self.live['reads'], self.rc['reads']):
            self.assertEqual((a['stateKeys'], a['phase2Keys']), (b['stateKeys'], b['phase2Keys']))

    def test_state_normalisation_is_a_no_op_for_a_workspace_without_discord_data(self):
        for name in ('live', 'rc'):
            self.assertFalse(self.probes[name]['invalidateChanged'], name)
        for key in ('jobStatesAfterInvalidate', 'current', 'channelState'):
            self.assertEqual(self.probes['live'][key], self.probes['rc'][key], key)

    @unittest.expectedFailure
    def test_channels_read_opens_no_more_database_transactions_than_live(self):
        """FINDING CH-1: oauth.channels() calls discord_connections.public_identities() for every workspace when
        POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED=true, a second repository transaction (in Production also a Supabase
        getUser call and a session-flag query) with a FOR UPDATE lock on the workspace row, to return []."""
        self.assertEqual(self.live['phases']['read']['connections'], self.rc['phases']['read']['connections'])

    def test_pins_the_size_of_the_extra_channels_read_transaction(self):
        delta = _delta(self.live, self.rc, 'read')
        self.assertEqual(list(delta.values()), [WORKSPACES], delta)
        statement = next(iter(delta))
        self.assertTrue(statement.startswith('SELECT w.revision,w.state') and 'pr_memberships' in statement, statement)
        self.assertIn('FOR UPDATE OF w', statement, 'the extra read locks the workspace row')
        self.assertEqual(self.rc['phases']['read']['connections'] - self.live['phases']['read']['connections'], WORKSPACES)

    def test_channels_listing_keeps_discord_closed_for_ordinary_workspaces(self):
        """OBSERVABLE-INTENDED: live offers the original Discord connect flow; the candidate's gate is closed (unset on
        production) and says so. No identity is listed for a workspace that never linked Discord."""
        for live, rc in zip(self.live['reads'], self.rc['reads']):
            self.assertTrue(live['discordEntry']['connectReady'])
            self.assertEqual(rc['discordEntry']['connectReady'], False)
            self.assertEqual(rc['discordEntry']['discordAccess'], {'status': 'closed', 'reason': 'invite_only', 'capped': True})
            self.assertEqual(rc['discordIdentities'], [])
            self.assertEqual(sorted(set(rc['listingKeys']) - set(live['listingKeys'])), ['discordIdentities'])

    # --- the minute worker ------------------------------------------------------------------------------------------------
    def test_minute_worker_treats_an_ordinary_post_exactly_as_live(self):
        self.assertEqual(self.live['tick']['processed'], 1)
        self.assertEqual(self.rc['tick']['processed'], self.live['tick']['processed'])
        self.assertEqual(self.rc['jobsAfterTick'], self.live['jobsAfterTick'])
        self.assertEqual(self.rc['phase2KeysAfterTick'], self.live['phase2KeysAfterTick'], 'no Discord cursor in ordinary state')
        self.same_effects('tick')

    def test_pins_the_minute_workers_extra_reads_with_no_discord_work(self):
        """Finding BG-1: with POSTRIFF_DISCORD_WORKER_V1_ENABLED=true each Discord lane attempt opens one connection for 4
        reads (two catalogue checks, the database clock, the projection hint), the Discord report reads once and the
        rate-limit report reads 3 times on one connection each. One ordinary job due: 2 lane attempts. Nothing writes."""
        delta = _delta(self.live, self.rc, 'tick')
        kinds = {}
        for statement, count in delta.items():
            # Most specific first: both reports also read the database clock.
            key = ('generic-due' if 'LEFT JOIN public.pr_worker_tenants dispatch' in statement else
                   'report' if 'LIMIT 256' in statement else
                   'rate-report' if 'pr_discord_request_admissions' in statement or 'set_config' in statement else
                   'projection' if 'pr_discord_worker_projection' in statement else
                   'catalogue' if 'to_regclass' in statement else 'clock' if 'clock_timestamp' in statement else statement)
            kinds[key] = kinds.get(key, 0) + count
        self.assertEqual(kinds.pop('generic-due', 0), 0, 'the generic lane runs its due query as often as live')
        self.assertEqual(kinds, {'catalogue': 4, 'clock': 2, 'projection': 2, 'report': 1, 'rate-report': 3}, delta)
        generic = [st for st in _statements(self.rc, 'tick') if 'LEFT JOIN public.pr_worker_tenants dispatch' in st]
        self.assertTrue(generic and all(st.count("<>'?'") == 1 for st in generic),
                        'the generic lane now excludes Discord jobs (exclude_discord); nothing else in its query changed')
        self.assertEqual(self.rc['phases']['tick']['connections'] - self.live['phases']['tick']['connections'], 4)
        report = self.rc['tick']['discordWorker']
        self.assertEqual((report['enabled'], report['queue']['depth'], report['queue']['status']), (True, 0, 'observed_sample'))
        self.assertIsNone(self.live['tick']['discordWorker'])

    def test_worker_budget_comes_from_the_environment_on_both_builds(self):
        """Finding WB-1: the live code reads POSTRIFF_WORKER_MAX_JOBS/SECONDS too, so 25 jobs and 40 s apply to any new build."""
        for name in ('live', 'rc'):
            self.assertEqual(self.records[name]['tick']['budget'], {'maxJobs': 25, 'maxSeconds': 40.0}, name)

    def test_no_discord_table_is_written_for_ordinary_customers(self):
        for name in ('live', 'rc'):
            for phase, record in self.records[name]['phases'].items():
                self.assertEqual([t for t in record['writes'] if t.startswith('pr_discord_')], [], (name, phase))
                changed = {t: n for t, n in record['rowsChanged'].items() if t.startswith('pr_discord_')}
                # The projection trigger (migration 126, already in Production) adds one hint row per new workspace on both.
                self.assertEqual(changed, {'pr_discord_worker_projection': WORKSPACES} if phase == 'bootstrap' else {}, (name, phase))

    # --- the Discord surface with the gate closed ---------------------------------------------------------------------
    def test_every_discord_entry_point_refuses_an_ordinary_workspace_without_side_effects(self):
        """With POSTRIFF_DISCORD_CONNECT_WORKSPACES unset on production: connect starts, callbacks, identity, guild,
        destination, engagement, interaction and execute entry points are all refused, with no write, no new row and
        no provider request."""
        outcomes = self.rc['surface']
        self.assertGreaterEqual(len(outcomes), 9)
        for name, outcome in outcomes.items():
            with self.subTest(name):
                self.assertEqual(outcome['outcome'], 'refused', outcome)
                self.assertIn(outcome['status'], (403, 404, 409, 503), outcome)
        phase = self.rc['phases']['surface']
        self.assertEqual((phase['writes'], phase['rowsChanged'], phase['http']), ([], {}, []))
        self.assertEqual(outcomes['oauth.start publish']['code'], 'discord_access_closed')

    def test_pins_that_live_offers_the_original_discord_connect_and_the_candidate_closes_it(self):
        """OBSERVABLE-INTENDED (the dark launch closes Discord to workspaces outside the gate): on live a member can start
        the original bot-install flow, which records an OAuth transaction; the candidate refuses before any write."""
        self.assertEqual(self.live['surface']['oauth.start publish']['outcome'], 'answered')
        self.assertIn('authorizeUrl', self.live['surface']['oauth.start publish']['keys'])
        self.assertIn('pr_oauth_transactions', self.live['phases']['surface']['rowsChanged'])
        self.assertEqual(self.rc['surface']['oauth.start publish'], {'outcome': 'refused', 'status': 403, 'code': 'discord_access_closed'})

    # --- RC2 (W-02 parallel Discord lane) ------------------------------------------------------------------------------
    def test_w02_shard_does_nothing_with_the_lane_flag_off(self):
        """RC2 adds twelve per-minute crons. With POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED unset (Production today) a
        shard answers from the environment alone: no database connection, no statement, no write, no provider call."""
        if not self.rc.get('laneAvailable'):
            self.skipTest('this candidate has no W-02 lane')
        phase = self.rc['phases']['shard-off']
        self.assertEqual((phase['connections'], phase['statements'], phase['writes'], phase['rowsChanged'], phase['http']), (0, [], [], {}, []))
        self.assertEqual((self.rc['shard-off']['enabled'], self.rc['shard-off']['processed'], self.rc['shard-off']['status']['blocker']), (False, 0, 'disabled'))

    def test_pins_w02_shard_cost_with_the_lane_flag_on_and_no_discord_work(self):
        """If the lane flag is turned on: each shard invocation with nothing to send opens 4 connections for 7 reads and
        stops idle (12 shards x 1,440 minutes = about 69,000 connections a day before any Discord post)."""
        if not self.rc.get('laneAvailable'):
            self.skipTest('this candidate has no W-02 lane')
        phase = self.rc['phases']['shard-on']
        self.assertEqual((phase['connections'], len(phase['statements']), phase['writes'], phase['rowsChanged'], phase['http']), (4, 7, [], {}, []))
        self.assertEqual((self.rc['shard-on']['enabled'], self.rc['shard-on']['stoppedBy']), (True, 'idle'))

    # --- other lanes inside the shared approval path ------------------------------------------------------------------
    def test_a_linkedin_post_is_approvable_as_on_live(self):
        self.assertEqual(self.probes['rc']['approvals']['LinkedIn'], self.probes['live']['approvals']['LinkedIn'])
        self.assertEqual(self.probes['live']['approvals']['LinkedIn']['job'], 'scheduled')

    @unittest.expectedFailure
    def test_a_facebook_page_post_is_approvable_as_on_live(self):
        """FINDING FB-1: Phase2Store.current() demands manifest.destinationId == channel.destinationId for Facebook and no
        code writes manifest.destinationId, so the review is born stale, approval is refused, and a post approved on the
        live build is held by the next invalidate() (every command, every worker claim)."""
        self.assertEqual(self.probes['live']['approvals']['Facebook']['job'], 'scheduled')
        self.assertEqual(self.probes['rc']['approvals']['Facebook'], self.probes['live']['approvals']['Facebook'])


if __name__ == '__main__':
    unittest.main()
