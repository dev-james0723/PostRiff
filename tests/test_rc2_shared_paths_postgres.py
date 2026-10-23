"""RC2 shared-path fixes on real PostgreSQL: the live tree and this tree run the same scenario (FB-1 and CH-1).

One disposable PostgreSQL cluster gets the schema Production has (the RLS harness plus the Discord migrations 124-131),
copied into one database per run. tests/rc2_shared_path_scenario.py then runs with each tree's code:

  live   the live tree (c5fc1fd1, from `git archive`) runs every phase on its own database;
  rc     this tree runs every phase on its own database;
  cross  the live tree signs in and approves the Facebook post (the post approved before promotion), then this tree
         runs the next hosted command and the minute worker on the same database.

FB-1: the Facebook Page post is approved, kept by the next hosted command (invalidate()) and claimed and sent by the
worker exactly as on live, also when the live build approved it. CH-1: a Channels read of a workspace without Discord
data verifies the session, opens connections and repository transactions exactly as often as live; a workspace with a
linked Discord identity still lists it.

Needs POSTRIFF_PG_BIN (initdb, pg_ctl, psql) and psycopg; skipped under the synthetic transport fence (it refuses any
database but the guarded runner's) and when the live revision is not in the clone. Adapted from the impact agent's
tests/test_customer_impact_shared_paths.py.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_REV = os.environ.get('RC2_LIVE_REV', 'c5fc1fd10350f3142ec6f34b2c373139e85abb39')
PG_BIN = os.environ.get('POSTRIFF_PG_BIN')
FENCED = '1' in (os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE'), os.environ.get('RAFII_LINKEDIN_SYNTHETIC_FENCE'))
DISCORD_MIGRATIONS = ('124_discord_rate_limits', '125_discord_service_grants', '126_discord_worker_projection',
                      '128_discord_lease_protocol_fence', '131_discord_interactions')
try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


def _rev(rev):
    done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', '--quiet', rev + '^{commit}'], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@unittest.skipIf(FENCED, 'the synthetic transport fence refuses databases other than the guarded runner\'s')
@unittest.skipUnless(PG_BIN and psycopg and (Path(PG_BIN or '/nonexistent') / 'initdb').exists(), 'needs POSTRIFF_PG_BIN and psycopg')
@unittest.skipUnless(_rev(LIVE_REV), 'the live revision is not in this clone (shallow checkout)')
class SharedPathsOnPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runas = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else []
        cls.tmp = tempfile.mkdtemp(prefix='rc2pg-', dir='/tmp')
        os.chmod(cls.tmp, 0o755)
        cls.data, cls.sock, cls.port = Path(cls.tmp) / 'data', Path(cls.tmp) / 'sock', _free_port()
        user = ' user=postgres' if cls.runas else ''
        cls.dsn = lambda database: 'host=%s port=%d dbname=%s%s' % (cls.sock, cls.port, database, user)
        try:
            live = Path(cls.tmp) / 'live'
            live.mkdir()
            archive = subprocess.run(['git', '-C', str(ROOT), 'archive', _rev(LIVE_REV), 'src'], capture_output=True, check=True)
            subprocess.run(['tar', '-x', '-C', str(live)], input=archive.stdout, check=True)
            cls.trees = {'live': live, 'rc': ROOT}
            if cls.runas:
                shutil.chown(cls.tmp, 'postgres', 'postgres')
            cls._run('mkdir', str(cls.sock))
            cls._run(str(Path(PG_BIN) / 'initdb'), '-D', str(cls.data), '-A', 'trust', '--no-locale', '-E', 'UTF8')
            cls._run(str(Path(PG_BIN) / 'pg_ctl'), '-D', str(cls.data), '-l', str(Path(cls.tmp) / 'postgres.log'),
                     '-o', '-k %s -p %d -h ""' % (cls.sock, cls.port), '-w', 'start')
            psql = [str(Path(PG_BIN) / 'psql'), '-X', '-q', '-v', 'ON_ERROR_STOP=1']
            subprocess.run(psql + [cls.dsn('postgres'), '-c', 'CREATE DATABASE rc2_template'], check=True, capture_output=True)
            subprocess.run(psql + [cls.dsn('rc2_template'), '-f', str(ROOT / 'tests/phase2/rls.sql')], check=True, capture_output=True)
            for migration in DISCORD_MIGRATIONS:
                subprocess.run(psql + [cls.dsn('rc2_template'), '-f', str(ROOT / 'migrations/postriff' / (migration + '.sql'))],
                               check=True, capture_output=True)
            for name in ('live', 'rc', 'cross'):
                subprocess.run(psql + [cls.dsn('postgres'), '-c', 'CREATE DATABASE rc2_%s TEMPLATE rc2_template' % name],
                               check=True, capture_output=True)
            every = 'bootstrap,facebook,command,tick,channels'
            cls.records = {name: cls._scenario(name, 'rc2_' + name, every, 'handoff-' + name) for name in ('live', 'rc')}
            cls.records['crossApproved'] = cls._scenario('live', 'rc2_cross', 'bootstrap,facebook', 'handoff-cross')
            cls.records['cross'] = cls._scenario('rc', 'rc2_cross', 'command,tick', 'handoff-cross')
            if os.environ.get('RC2_REPORT'):
                Path(os.environ['RC2_REPORT']).write_text(json.dumps(cls.records, indent=1, sort_keys=True))
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def _scenario(cls, tree, database, phases, handoff):
        done = subprocess.run([sys.executable, str(ROOT / 'tests' / 'rc2_shared_path_scenario.py'), '--tree', str(cls.trees[tree]),
                               '--dsn', cls.dsn(database), '--phases', phases, '--handoff', str(Path(cls.tmp) / handoff)],
                              capture_output=True, text=True, timeout=600, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if done.returncode:
            raise RuntimeError('scenario failed on %s: %s' % (tree, done.stderr[-3000:]))
        return json.loads(done.stdout)

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

    def test_scenarios_ran_without_errors(self):
        for name in ('live', 'rc', 'crossApproved', 'cross'):
            self.assertEqual(self.records[name]['errors'], [], name)
        self.assertIn('facebook', self.rc['mounted'])
        self.assertIn('discord', self.rc['mounted'])

    # --- FB-1 -------------------------------------------------------------------------------------------------------------
    def test_a_facebook_page_post_is_approved_as_on_live(self):
        self.assertEqual((self.live['review'], self.live.get('approvalRefused')), ('needs_review', None))
        self.assertEqual((self.rc['review'], self.rc.get('approvalRefused')), (self.live['review'], None))
        self.assertEqual(self.rc['afterApproval'], self.live['afterApproval'])
        self.assertEqual([j['state'] for j in self.live['afterApproval']], ['scheduled'])

    def test_the_next_hosted_command_keeps_the_approved_post_as_on_live(self):
        self.assertEqual([j['state'] for j in self.live['afterCommand']], ['scheduled'])
        self.assertEqual(self.rc['afterCommand'], self.live['afterCommand'])

    def test_the_worker_claims_and_sends_the_facebook_post_as_on_live(self):
        self.assertEqual(self.live['tick']['processed'], 1)
        self.assertEqual([j['state'] for j in self.live['afterTick']], ['provider_accepted'])
        self.assertEqual((self.rc['tick'], self.rc['afterTick']), (self.live['tick'], self.live['afterTick']))
        self.assertEqual(self.rc['phases']['tick']['http'], self.live['phases']['tick']['http'])
        self.assertIn({'method': 'POST', 'url': 'graph.facebook.com/v*/100200300400/feed'}, self.live['phases']['tick']['http'])

    def test_a_facebook_post_approved_on_live_is_kept_and_sent_by_this_build(self):
        self.assertEqual(self.records['crossApproved']['afterApproval'], self.live['afterApproval'])
        cross = self.records['cross']
        self.assertEqual(cross['afterCommand'], self.live['afterCommand'])
        self.assertEqual((cross['tick'], cross['afterTick']), (self.live['tick'], self.live['afterTick']))

    # --- CH-1 -------------------------------------------------------------------------------------------------------------
    def test_a_channels_read_without_discord_data_costs_what_live_costs(self):
        """One verification (Supabase Auth getUser plus a session-flag connection in Production), one connection and one
        workspace-row transaction per repository call: the same number as live."""
        live, rc = self.live['channels'][0], self.rc['channels'][0]
        for key in ('verifications', 'connections', 'transactions', 'statements'):
            with self.subTest(count=key):
                self.assertEqual(rc[key], live[key])
        self.assertEqual(rc['discordIdentities'], [])
        self.assertEqual(sorted(set(rc['keys']) - set(live['keys'])), ['discordIdentities'])

    def test_a_workspace_with_a_linked_discord_identity_still_lists_it(self):
        """Unchanged by the fix: the member's own link is listed with its identity-only capabilities, read by the same
        identity transaction as before (live has no such list)."""
        b = self.rc['channels'][1]
        self.assertEqual(len(b['discordIdentities']), 1, b)
        listed = dict(b['discordIdentities'][0])
        self.assertIsInstance(listed.pop('expiresAt'), float)
        self.assertEqual(listed, {'id': 'discord-identity-1', 'account': 'synthetic#0001', 'userId': '4242424242', 'status': 'linked',
                                  'discoverGuilds': False, 'canPublish': False, 'canSchedule': False,
                                  'capabilityReason': 'discord_identity_only', 'connectionKind': 'identity',
                                  'postAsPersonalUser': False, 'senderKind': 'none'})
        live = self.live['channels'][1]
        self.assertEqual((b['verifications'], b['connections'], b['transactions']),
                         (live['verifications'] + 1, live['connections'] + 1, live['transactions'] + 1),
                         'only a workspace with identity links pays for the identity read')


if __name__ == '__main__':
    unittest.main()
