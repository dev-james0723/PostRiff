"""Hardening of the Discord launch gate and server cap after an independent review (synthetic data only).

Each class pins one weakness that was found by reading the code against the intended behaviour: the original connect
flow skipping the cap, a reconnect-required identity being locked out, a misspelt production opening the gate, one
person holding many slots (and, the other way round, one person opening the bot to many servers for the price of one),
and a server that already holds a slot being refused at a full house.
"""
import os
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord import launch_gate as gate
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import ACTOR, GUILD, WORKSPACE

OTHER = '10000000-0000-4000-8000-000000000002'


def state_with(channels=(), links=()):
    state = initial_state(WORKSPACE)
    state['phase2'] = {'channels': list(channels), 'assets': [], 'reviews': [], 'jobs': [], 'discordIdentityLinks': list(links)}
    return state


class IdentityThatMustReconnect(unittest.TestCase):
    """A refresh failure leaves the identity 'reconnect_required' and revokes its servers; that person is not a stranger."""

    def test_it_counts_as_a_footprint_so_the_person_can_reconnect(self):
        self.assertTrue(gate.has_footprint(state_with(links=[{'id': 'i', 'status': 'reconnect_required'}])))

    def test_a_disconnected_identity_still_does_not(self):
        self.assertFalse(gate.has_footprint(state_with(links=[{'id': 'i', 'status': 'disconnected'}])))

    def test_a_closed_gate_lets_them_in_with_the_existing_connection_reason(self):
        verdict = gate.access(OTHER, state_with(links=[{'id': 'i', 'status': 'reconnect_required'}]),
                              {'VERCEL_ENV': 'production'})
        self.assertEqual(verdict, {'status': 'open', 'reason': 'existing_connection'})

    def test_a_stranger_is_still_closed_out(self):
        verdict = gate.access(OTHER, state_with(), {'VERCEL_ENV': 'production'})
        self.assertEqual((verdict['status'], verdict['reason']), ('closed', 'invite_only'))


class ProductionIsRecognisedWhateverItsSpelling(unittest.TestCase):
    """A misspelt production must close the gate and apply the cap, never open them."""

    def test_case_and_surrounding_space_do_not_matter(self):
        for variable in ('VERCEL_ENV', 'POSTRIFF_ENVIRONMENT'):
            for value in ('production', 'Production', 'PRODUCTION', ' production ', 'production\n'):
                values = {variable: value}
                self.assertTrue(gate.hosted_production(values), (variable, value))
                self.assertEqual(gate.configuration(values).mode, 'closed', (variable, value))
                self.assertEqual(gate.guild_cap(values), (90, False), (variable, value))

    def test_other_environments_stay_open_and_uncapped(self):
        for value in ('preview', 'development', 'staging', '', None, 'prod'):
            values = {'VERCEL_ENV': value} if value is not None else {}
            self.assertFalse(gate.hosted_production(values), value)
            self.assertEqual(gate.configuration(values).mode, 'open', value)
            self.assertEqual(gate.guild_cap(values), (None, False), value)

    def test_non_strings_do_not_raise(self):
        self.assertFalse(gate.hosted_production({'VERCEL_ENV': 1, 'POSTRIFF_ENVIRONMENT': ['production']}))


class Cursor:
    """Answers the four statements reserve_capacity can run, and records them."""

    def __init__(self, used, known=(), pending=0):
        self.used, self.known, self.pending = used, {str(k) for k in known}, pending
        self.sql, self.params, self._answer = [], [], None

    def execute(self, sql, params=None):
        flat = ' '.join(sql.split())
        self.sql.append(flat)
        self.params.append(params)
        if flat.startswith('SELECT pg_advisory_xact_lock'):
            self._answer = None
        elif flat.startswith('SELECT 1 FROM public.pr_encrypted_credentials'):
            self._answer = (1,) if params and str(params[0]) in self.known else None
        elif flat.startswith('SELECT count(*) FROM public.pr_oauth_transactions'):
            self._answer = (self.pending,)
        else:
            self._answer = (self.used,)

    def fetchone(self):
        return self._answer


CAP = {gate.ENV_CAP: '90'}


class ServerThatAlreadyHoldsASlot(unittest.TestCase):
    """Reinstalling a server the bot already has (after a disconnect, or from another workspace) needs no second slot."""

    def test_it_is_admitted_at_a_full_house_without_counting(self):
        cur = Cursor(used=90, known=[GUILD])
        result = gate.reserve_capacity(cur, CAP, guild_id=GUILD)
        self.assertEqual(result, {'known': True, 'cap': 90})
        self.assertEqual(len(cur.sql), 2)
        self.assertIn('pg_advisory_xact_lock', cur.sql[0])
        self.assertIn('provider_account_id = %s', cur.sql[1])

    def test_a_new_server_at_a_full_house_is_still_refused(self):
        cur = Cursor(used=90, known=['777'])
        with self.assertRaises(AlphaError) as raised:
            gate.reserve_capacity(cur, CAP, guild_id=GUILD)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_capacity_reached'))

    def test_a_new_server_with_room_is_counted_normally(self):
        cur = Cursor(used=10, known=[])
        self.assertEqual(gate.reserve_capacity(cur, CAP, guild_id=GUILD), {'used': 10, 'cap': 90})
        self.assertEqual(len(cur.sql), 3)

    def test_without_a_server_id_the_lock_and_the_count_are_the_only_statements(self):
        cur = Cursor(used=5)
        gate.reserve_capacity(cur, CAP)
        self.assertEqual(len(cur.sql), 2)

    def test_the_server_id_travels_as_a_parameter_never_inside_the_sql(self):
        cur = Cursor(used=1)
        gate.reserve_capacity(cur, CAP, guild_id=GUILD)
        self.assertFalse(any(GUILD in statement for statement in cur.sql))
        self.assertIn((GUILD,), cur.params)

    def test_the_lock_is_always_taken_before_the_lookup(self):
        cur = Cursor(used=1, known=[GUILD])
        gate.reserve_capacity(cur, CAP, guild_id=GUILD)
        self.assertIn('pg_advisory_xact_lock', cur.sql[0])

    def test_no_cap_means_no_statements_even_with_a_server_id(self):
        cur = Cursor(used=500, known=[])
        self.assertIsNone(gate.reserve_capacity(cur, {}, guild_id=GUILD))
        self.assertEqual(cur.sql, [])


class EveryLiveStartHoldsItsOwnSlot(unittest.TestCase):
    """Collapsing starts per person would let one account open the bot to many servers for the price of one."""

    def test_in_flight_starts_are_counted_row_by_row(self):
        flat = ' '.join(gate._COUNT.split())
        self.assertIn("(SELECT count(*) FROM public.pr_oauth_transactions WHERE provider='discord' AND 'bot' = ANY(scopes)", flat)
        self.assertNotIn('DISTINCT workspace_id', flat)
        self.assertNotIn('member_id', flat)
        self.assertIn("AND ((consumed_at IS NULL AND expires_at > now()) OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes'))", flat)

    def test_stored_servers_still_count_once_each_including_revoked_grants(self):
        flat = ' '.join(gate._COUNT.split())
        self.assertIn("count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials WHERE provider='discord' AND 'bot' = ANY(scopes)", flat)
        self.assertNotIn('revoked_at', flat)


PERSON = (WORKSPACE, OTHER)


class OnePersonCannotHoardTheCap(unittest.TestCase):
    """Exact counting makes hoarding possible again, so a person may only have a few starts in flight."""

    def test_the_limit_is_three(self):
        self.assertEqual(gate.MAX_PENDING_PER_PERSON, 3)

    def test_a_person_at_the_limit_is_refused_before_anything_is_counted(self):
        cur = Cursor(used=0, pending=3)
        with self.assertRaises(AlphaError) as raised:
            gate.reserve_capacity(cur, CAP, guild_id=GUILD, person=PERSON)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_capacity_reached'))
        self.assertIn('waiting to be finished', str(raised.exception))
        self.assertEqual(len(cur.sql), 2)  # the lock and the person's own count, nothing else

    def test_below_the_limit_the_normal_count_follows(self):
        cur = Cursor(used=10, pending=2)
        self.assertEqual(gate.reserve_capacity(cur, CAP, guild_id=GUILD, person=PERSON), {'used': 10, 'cap': 90})
        self.assertEqual(len(cur.sql), 4)  # lock, person, known server, count

    def test_the_limit_applies_to_a_server_the_bot_already_holds(self):
        """Otherwise re-starting a known server over and over would hoard the count for everybody else."""
        cur = Cursor(used=90, known=[GUILD], pending=3)
        with self.assertRaises(AlphaError):
            gate.reserve_capacity(cur, CAP, guild_id=GUILD, person=PERSON)
        self.assertFalse(any('provider_account_id = %s' in statement for statement in cur.sql))

    def test_a_reconnect_takes_no_slot_but_obeys_the_limit(self):
        cur = Cursor(used=90, pending=2)
        self.assertEqual(gate.reserve_capacity(cur, CAP, guild_id=GUILD, person=PERSON, new_server=False), {'reconnect': True, 'cap': 90})
        self.assertEqual(len(cur.sql), 2)  # lock and the person's count; no server lookup, no cap count
        with self.assertRaises(AlphaError):
            gate.reserve_capacity(Cursor(used=0, pending=3), CAP, guild_id=GUILD, person=PERSON, new_server=False)

    def test_the_person_travels_as_parameters_and_the_count_matches_the_gate_count(self):
        cur = Cursor(used=1)
        gate.reserve_capacity(cur, CAP, person=PERSON)
        self.assertIn(PERSON, cur.params)
        self.assertFalse(any(WORKSPACE in statement or OTHER in statement for statement in cur.sql))
        pending = ' '.join(gate._PENDING.split())
        self.assertIn("workspace_id = %s AND member_id = %s", pending)
        self.assertIn(' '.join(gate._IN_FLIGHT.split()), pending)  # the very same notion of "in flight"

    def test_without_a_person_there_is_no_per_person_statement(self):
        cur = Cursor(used=5)
        gate.reserve_capacity(cur, CAP)
        self.assertEqual(len(cur.sql), 2)

    def test_no_cap_means_no_statements_even_with_a_person(self):
        cur = Cursor(used=0, pending=99)
        self.assertIsNone(gate.reserve_capacity(cur, {}, person=PERSON))
        self.assertEqual(cur.sql, [])

    def test_the_lock_comes_first(self):
        cur = Cursor(used=1, pending=0)
        gate.reserve_capacity(cur, CAP, person=PERSON)
        self.assertIn('pg_advisory_xact_lock', cur.sql[0])


class RecordingCursor:
    """A cursor for OAuthService.start on the original (non-v2) connect flow."""

    def __init__(self, used, pending=0):
        self.used, self.pending, self.sql, self.params, self.last = used, pending, [], [], ''

    def execute(self, sql, params=None):
        self.last = ' '.join(sql.split())
        self.sql.append(self.last)
        self.params.append(params)

    def fetchone(self):
        if 'pr_auth_throttle' in self.last:
            return (1,)
        if 'INSERT INTO public.pr_oauth_transactions' in self.last:
            return ('txn-1',)
        if self.last.startswith('SELECT count(*) FROM public.pr_oauth_transactions'):
            return (self.pending,)
        return (self.used,)


class OriginalConnectFlow(unittest.TestCase):
    """With the Discord v2 flags off (or mistyped) the bot is still added to a server of the person's choosing."""

    def start(self, *, used, cap, v2=False, gate_value='*', production=True, pending=0):
        adapter = DiscordProvider('555555', 'secret', 'bot-token', 'https://rafii.example.invalid', transport=Mock(), production_reviewed=True)
        adapter.authorization_v2_enabled = adapter.connections_v2_enabled = v2
        state = state_with()
        cur = RecordingCursor(used, pending)

        class Repository:
            connection_factory = None

            @contextmanager
            def transaction(self, token, workspace, **kwargs):
                yield cur, (1, json.dumps(state), 'owner', True, True, True, True), ACTOR

        oauth = OAuthService(Repository(), Mock(), CredentialVault(CredentialVault.generate_key()), {'discord': adapter},
                             'https://rafii.example.invalid', clock=lambda: 1_800_000_000)
        env = {gate.ENV_WORKSPACES: gate_value}
        if production:
            env['VERCEL_ENV'] = 'production'
        if cap is not None:
            env[gate.ENV_CAP] = str(cap)
        with patch.dict(os.environ, env, clear=False), patch('postriff_phase2.hosted.audit'):
            if cap is None:
                os.environ.pop(gate.ENV_CAP, None)
            try:
                return oauth.start(WORKSPACE, 'session', 'discord', 'publish', {}), cur
            except AlphaError as error:
                return error, cur

    def test_a_full_house_refuses_it_before_anything_is_written(self):
        result, cur = self.start(used=3, cap=3)
        self.assertIsInstance(result, AlphaError)
        self.assertEqual((result.status, result.code), (409, 'discord_capacity_reached'))
        self.assertFalse(any('INSERT INTO public.pr_oauth_transactions' in s for s in cur.sql))
        self.assertTrue(any('pg_advisory_xact_lock' in s for s in cur.sql))

    def test_with_room_it_reserves_under_the_lock_before_it_writes_the_transaction(self):
        result, cur = self.start(used=2, cap=3)
        self.assertEqual(result['transactionId'], 'txn-1')
        order = [i for i, s in enumerate(cur.sql) if 'pg_advisory_xact_lock' in s or 'count(DISTINCT provider_account_id)' in s
                 or 'INSERT INTO public.pr_oauth_transactions' in s]
        kinds = [('lock' if 'pg_advisory' in cur.sql[i] else 'count' if 'count(' in cur.sql[i] else 'insert') for i in order]
        self.assertEqual(kinds, ['lock', 'count', 'insert'])

    def test_a_zero_cap_blocks_the_original_flow_like_the_new_one(self):
        result, _ = self.start(used=0, cap=0)
        self.assertEqual(result.code, 'discord_capacity_reached')

    def test_the_default_cap_on_production_applies_to_it(self):
        result, _ = self.start(used=90, cap=None)
        self.assertEqual(result.code, 'discord_capacity_reached')

    def test_outside_production_without_a_cap_nothing_changes(self):
        result, cur = self.start(used=999, cap=None, production=False)
        self.assertEqual(result['transactionId'], 'txn-1')
        self.assertFalse(any('pg_advisory_xact_lock' in s for s in cur.sql))

    def test_a_closed_gate_still_stops_it_before_any_sql_is_run_for_the_cap(self):
        result, cur = self.start(used=0, cap=90, gate_value='')
        self.assertEqual((result.status, result.code), (403, 'discord_access_closed'))
        self.assertFalse(any('pg_advisory_xact_lock' in s for s in cur.sql))

    def test_it_counts_the_person_and_refuses_a_fourth_start_in_flight(self):
        result, cur = self.start(used=0, cap=90, pending=3)
        self.assertEqual((result.status, result.code), (409, 'discord_capacity_reached'))
        self.assertFalse(any('INSERT INTO public.pr_oauth_transactions' in s for s in cur.sql))
        self.assertIn((WORKSPACE, ACTOR), cur.params)  # the workspace and the signed-in member, as parameters

    def test_two_starts_in_flight_still_leave_room_for_a_third(self):
        result, _ = self.start(used=0, cap=90, pending=2)
        self.assertEqual(result['transactionId'], 'txn-1')

    def test_a_mistyped_flag_does_not_leave_the_original_flow_uncapped(self):
        """'TRUE' is not 'true': the v2 flow stays off, and the cap must still hold."""
        result, _ = self.start(used=90, cap=90, v2=False)
        self.assertEqual(result.code, 'discord_capacity_reached')


if __name__ == '__main__':
    unittest.main()
