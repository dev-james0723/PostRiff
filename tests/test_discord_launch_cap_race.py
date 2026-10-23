"""Real-PostgreSQL proof that concurrent Discord installation starts cannot exceed the server cap (synthetic rows only).

`launch_gate.reserve_capacity` takes a transaction-scoped advisory lock, counts, and the caller inserts its transaction row
before committing. The scripted-cursor tests prove that order; this test proves the effect: with many starts racing for
the last slots, exactly the free slots are handed out. A control run without the lock shows the race is real, so a pass
means the lock is doing the work. Every live start holds its own slot (one account starting ten different servers must not
pass the cap), and one person may only have a few in flight.

Runs where PostgreSQL server binaries are named by POSTRIFF_PG_BIN (the qualification and local-gates workflows set it). It
starts its own disposable cluster in a temporary directory and never reads application credentials or touches any other
database. It does not run under the synthetic transport fence (RAFII_DISCORD_SYNTHETIC_FENCE), which by design refuses every
database except the guarded runner's own: the same tests run in the unfenced full-suite step of both workflows.
"""
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import launch_gate as gate

try:
    import psycopg
except ImportError:  # pragma: no cover - the dependency set always has it in CI
    psycopg = None

PG_BIN = os.environ.get('POSTRIFF_PG_BIN')
FENCED = '1' in (os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE'), os.environ.get('RAFII_LINKEDIN_SYNTHETIC_FENCE'))
CAP = 5
RACERS = 12
# Only the columns the count reads; the production tables carry more.
SCHEMA = """
CREATE TABLE public.pr_encrypted_credentials (
  provider text NOT NULL, provider_account_id text NOT NULL, scopes text[] NOT NULL, revoked_at timestamptz);
CREATE TABLE public.pr_oauth_transactions (
  id bigserial PRIMARY KEY, workspace_id uuid NOT NULL, member_id uuid NOT NULL, provider text NOT NULL,
  scopes text[] NOT NULL, expires_at timestamptz NOT NULL, consumed_at timestamptz, outcome text);
"""


def ident(name):
    """A stable synthetic UUID for a name: the production columns are uuid, so the statements run against that type."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name + '.example.invalid'))


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@unittest.skipIf(FENCED, 'the synthetic transport fence refuses any database but the guarded runner\'s; these tests run in the unfenced suite')
@unittest.skipUnless(PG_BIN and psycopg and (Path(PG_BIN) / 'initdb').exists(),
                     'needs PostgreSQL server binaries (POSTRIFF_PG_BIN) and psycopg')
class ConcurrentCapReservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # PostgreSQL refuses to run as root (some development containers do); use the postgres account there.
        cls.runas = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else []
        cls.tmp = tempfile.mkdtemp(prefix='prcap-', dir='/tmp')  # short path: unix socket names are length limited
        os.chmod(cls.tmp, 0o755)
        if cls.runas:
            shutil.chown(cls.tmp, 'postgres', 'postgres')
        cls.data, cls.sock = Path(cls.tmp) / 'data', Path(cls.tmp) / 'sock'
        cls.port = _free_port()
        cls.dsn = f'host={cls.sock} port={cls.port} dbname=postgres' + (' user=postgres' if cls.runas else '')
        try:
            cls._run('mkdir', str(cls.sock))
            cls._run(str(Path(PG_BIN) / 'initdb'), '-D', str(cls.data), '-A', 'trust', '--no-locale', '-E', 'UTF8')
            cls._run(str(Path(PG_BIN) / 'pg_ctl'), '-D', str(cls.data), '-l', str(Path(cls.tmp) / 'postgres.log'),
                     '-o', f'-k {cls.sock} -p {cls.port} -h ""', '-w', 'start')
            with psycopg.connect(cls.dsn, autocommit=True) as db:
                db.execute(SCHEMA)
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def _run(cls, *args):
        done = subprocess.run([*cls.runas, *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if done.returncode:
            raise RuntimeError(f'{args[0]} failed ({done.returncode}): {done.stderr.strip()}')

    @classmethod
    def tearDownClass(cls):
        try:
            if (cls.data / 'postmaster.pid').exists():
                subprocess.run([*cls.runas, str(Path(PG_BIN) / 'pg_ctl'), '-D', str(cls.data), '-m', 'fast', '-w', 'stop'],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        with psycopg.connect(self.dsn, autocommit=True) as db:
            db.execute('TRUNCATE public.pr_encrypted_credentials, public.pr_oauth_transactions RESTART IDENTITY')
            # Two servers already hold the bot (one grant was revoked: the bot stays in the server, so it still counts).
            db.execute("INSERT INTO public.pr_encrypted_credentials VALUES "
                       "('discord','server-a',ARRAY['bot','guilds'],NULL), ('discord','server-b',ARRAY['bot'],now()), "
                       "('discord','user-x',ARRAY['identify'],NULL)")  # an identity link is not a server
            # None of these occupy a slot: expired, finished without an exchange, or somebody else's provider.
            db.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,scopes,expires_at,consumed_at,outcome) VALUES "
                       "(%s,%s,'discord',ARRAY['bot'],now()-interval '1 minute',NULL,NULL),"
                       "(%s,%s,'discord',ARRAY['bot'],now()+interval '5 minutes',now(),'denied'),"
                       "(%s,%s,'mastodon',ARRAY['bot'],now()+interval '5 minutes',NULL,NULL)",
                       tuple(ident(n) for n in ('w-old', 'm-old', 'w-denied', 'm-denied', 'w-other', 'm-other')))

    def used(self):
        with psycopg.connect(self.dsn, autocommit=True) as db:
            return int(db.execute(gate._COUNT).fetchone()[0])

    def race(self, pause):
        """RACERS concurrent installation starts: reserve, hold the transaction open for `pause` seconds, insert, commit."""
        gate_open = threading.Barrier(RACERS, timeout=60)
        outcomes, failures = [], []

        def start(racer):
            try:
                with psycopg.connect(self.dsn) as db:
                    cur = db.cursor()
                    gate_open.wait()
                    try:
                        gate.reserve_capacity(cur, {gate.ENV_CAP: str(CAP)}, person=(ident(f'w-{racer}'), ident(f'm-{racer}')))
                    except AlphaError as refused:
                        db.rollback()
                        outcomes.append(('refused', refused.status, refused.code))
                        return
                    cur.execute('SELECT pg_sleep(%s)', (pause,))
                    # Every racer is a different person, so each one that is admitted holds its own slot.
                    cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,scopes,expires_at) "
                                "VALUES (%s,%s,'discord',ARRAY['bot','identify'],now()+interval '10 minutes')",
                                (ident(f'w-{racer}'), ident(f'm-{racer}')))
                    db.commit()
                    outcomes.append(('admitted', None, None))
            except BaseException as exc:  # a thread must never die silently
                failures.append(repr(exc))

        threads = [threading.Thread(target=start, args=(n,)) for n in range(RACERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        self.assertEqual(failures, [])
        self.assertEqual(len(outcomes), RACERS)
        return outcomes

    def test_the_starting_position_counts_servers_not_noise(self):
        self.assertEqual(self.used(), 2)

    def test_racing_starts_are_handed_exactly_the_free_slots(self):
        outcomes = self.race(pause=0.15)
        admitted = [o for o in outcomes if o[0] == 'admitted']
        refused = [o for o in outcomes if o[0] == 'refused']
        self.assertEqual(len(admitted), CAP - 2)
        self.assertEqual(len(refused), RACERS - (CAP - 2))
        self.assertTrue(all(o[1:] == (409, 'discord_capacity_reached') for o in refused))
        self.assertEqual(self.used(), CAP)  # never above the cap, not even momentarily after commit

    def test_without_the_lock_the_same_race_overshoots(self):
        """Control: proves the race exists on this database, so the passing run above is the lock's doing."""
        with patch.object(gate, '_LOCK', 'SELECT 1'):
            outcomes = self.race(pause=0.3)
        admitted = [o for o in outcomes if o[0] == 'admitted']
        self.assertGreater(len(admitted), CAP - 2)
        self.assertGreater(self.used(), CAP)

    def test_a_second_wave_after_the_cap_is_reached_is_refused(self):
        self.race(pause=0.05)
        outcomes = self.race(pause=0.05)
        self.assertEqual({o[0] for o in outcomes}, {'refused'})
        self.assertEqual(self.used(), CAP)


    def hold(self, rows):
        """In-flight installation starts, as (workspace, member) names."""
        with psycopg.connect(self.dsn, autocommit=True) as db:
            for workspace, member in rows:
                db.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,scopes,expires_at) "
                           "VALUES (%s,%s,'discord',ARRAY['bot','identify'],now()+interval '10 minutes')", (ident(workspace), ident(member)))

    def reserve(self, guild_id=None, person=None, cap=CAP, new_server=True, take=False):
        """What DiscordConnections.start does in one transaction: reserve, then (take=True) write its transaction row."""
        with psycopg.connect(self.dsn) as db:
            cur = db.cursor()
            try:
                result = gate.reserve_capacity(cur, {gate.ENV_CAP: str(cap)}, guild_id=guild_id,
                                               person=tuple(ident(n) for n in person) if person else None, new_server=new_server)
            except AlphaError as refused:
                return refused
            if take:
                cur.execute("INSERT INTO public.pr_oauth_transactions(workspace_id,member_id,provider,scopes,expires_at) "
                            "VALUES (%s,%s,'discord',ARRAY['bot','identify'],now()+interval '10 minutes')", tuple(ident(n) for n in person))
            return result

    def test_every_start_holds_its_own_slot_whoever_makes_it(self):
        """Each live start is a server the bot may join; counting one per person let one account open the bot to many."""
        self.hold([('w-one', 'm-one')] * 4)
        self.assertEqual(self.used(), 2 + 4)

    def test_different_people_each_hold_their_own_slot(self):
        self.hold([(f'w-{n}', f'm-{n}') for n in range(2)])
        self.assertEqual(self.used(), 2 + 2)

    def test_one_account_starting_many_different_servers_cannot_pass_the_cap(self):
        """The regression: with 2 stored and 3 free slots, one account used to be admitted for ten different servers."""
        person = ('w-agency', 'm-agency')
        outcomes = [self.reserve(guild_id=f'server-{n}', person=person, take=True) for n in range(10)]
        admitted = [o for o in outcomes if not isinstance(o, AlphaError)]
        self.assertEqual(len(admitted), CAP - 2)
        self.assertTrue(all(isinstance(o, AlphaError) and o.code == 'discord_capacity_reached' for o in outcomes[CAP - 2:]))
        self.assertEqual(self.used(), CAP)  # the bot can be in at most the cap's worth of servers after they all consent
        stranger = self.reserve(guild_id='server-stranger', person=('w-other-agency', 'm-other-agency'), take=True)
        self.assertIsInstance(stranger, AlphaError)

    def test_one_person_may_have_at_most_three_starts_in_flight_however_much_room_there_is(self):
        person = ('w-spam', 'm-spam')
        outcomes = [self.reserve(guild_id=f'server-{n}', person=person, cap=50, take=True) for n in range(6)]
        self.assertEqual([isinstance(o, AlphaError) for o in outcomes], [False] * 3 + [True] * 3)
        self.assertIn('waiting to be finished', str(outcomes[3]))
        self.assertEqual((outcomes[3].status, outcomes[3].code), (409, 'discord_capacity_reached'))
        self.assertEqual(self.used(), 2 + 3)
        # Somebody else is not affected by it.
        self.assertNotIsInstance(self.reserve(guild_id='server-fair', person=('w-fair', 'm-fair'), cap=50, take=True), AlphaError)

    def test_a_finished_start_frees_the_persons_next_one(self):
        person = ('w-agency', 'm-agency')
        for n in range(3):
            self.assertNotIsInstance(self.reserve(guild_id=f'server-{n}', person=person, cap=50, take=True), AlphaError)
        self.assertIsInstance(self.reserve(guild_id='server-3', person=person, cap=50, take=True), AlphaError)
        with psycopg.connect(self.dsn, autocommit=True) as db:  # the callback finished one of them
            db.execute("UPDATE public.pr_oauth_transactions SET consumed_at=now(), outcome='exchanged' WHERE id=(SELECT max(id) FROM public.pr_oauth_transactions)")
        self.assertNotIsInstance(self.reserve(guild_id='server-3', person=person, cap=50, take=True), AlphaError)

    def test_a_reconnect_takes_no_slot_at_a_full_house_but_obeys_the_person_limit(self):
        self.hold([(f'w-{n}', f'm-{n}') for n in range(CAP - 2)])  # full house
        self.assertEqual(self.used(), CAP)
        again = ('w-0', 'm-0')  # one pending start already (the held row)
        self.assertEqual(self.reserve(person=again, new_server=False), {'reconnect': True, 'cap': CAP})
        self.hold([again] * 2)  # now three pending
        self.assertIsInstance(self.reserve(person=again, new_server=False), AlphaError)

    def test_a_server_that_already_has_a_row_is_admitted_at_a_full_house_and_a_new_one_is_not(self):
        self.hold([(f'w-{n}', f'm-{n}') for n in range(CAP - 2)])  # three more people: 2 stored + 3 in flight = the cap
        self.assertEqual(self.used(), CAP)
        self.assertIsInstance(self.reserve(guild_id='server-brand-new'), AlphaError)
        self.assertEqual(self.reserve(guild_id='server-a'), {'known': True, 'cap': CAP})  # stored, active
        self.assertEqual(self.reserve(guild_id='server-b'), {'known': True, 'cap': CAP})  # stored, revoked: the bot stays
        self.assertIsInstance(self.reserve(guild_id='user-x'), AlphaError)  # an identity row is not a server


if __name__ == '__main__':
    unittest.main()
