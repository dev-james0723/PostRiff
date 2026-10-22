"""Hardening of the Discord launch gate and server cap after an independent review (synthetic data only).

Each class pins one weakness that was found by reading the code against the intended behaviour: the original connect
flow skipping the cap, a reconnect-required identity being locked out, a misspelt production opening the gate, one
person holding many slots, and a server that already holds a slot being refused at a full house.
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
    """Answers the three statements reserve_capacity can run, and records them."""

    def __init__(self, used, known=()):
        self.used, self.known, self.sql, self.params, self._answer = used, {str(k) for k in known}, [], [], None

    def execute(self, sql, params=None):
        flat = ' '.join(sql.split())
        self.sql.append(flat)
        self.params.append(params)
        if flat.startswith('SELECT pg_advisory_xact_lock'):
            self._answer = None
        elif flat.startswith('SELECT 1 FROM public.pr_encrypted_credentials'):
            self._answer = (1,) if params and str(params[0]) in self.known else None
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


class StartsAreCountedOncePerPerson(unittest.TestCase):
    def test_the_in_flight_part_collapses_to_one_row_per_workspace_and_member(self):
        flat = ' '.join(gate._COUNT.split())
        self.assertIn('SELECT count(*) FROM (SELECT DISTINCT workspace_id, member_id FROM public.pr_oauth_transactions', flat)
        self.assertIn("AND ((consumed_at IS NULL AND expires_at > now()) OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes'))", flat)

    def test_stored_servers_still_count_once_each_including_revoked_grants(self):
        flat = ' '.join(gate._COUNT.split())
        self.assertIn("count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials WHERE provider='discord' AND 'bot' = ANY(scopes)", flat)
        self.assertNotIn('revoked_at', flat)


class RecordingCursor:
    """A cursor for OAuthService.start on the original (non-v2) connect flow."""

    def __init__(self, used):
        self.used, self.sql, self.last = used, [], ''

    def execute(self, sql, params=None):
        self.last = ' '.join(sql.split())
        self.sql.append(self.last)

    def fetchone(self):
        if 'pr_auth_throttle' in self.last:
            return (1,)
        if 'INSERT INTO public.pr_oauth_transactions' in self.last:
            return ('txn-1',)
        return (self.used,)


class OriginalConnectFlow(unittest.TestCase):
    """With the Discord v2 flags off (or mistyped) the bot is still added to a server of the person's choosing."""

    def start(self, *, used, cap, v2=False, gate_value='*', production=True):
        adapter = DiscordProvider('555555', 'secret', 'bot-token', 'https://rafii.example.invalid', transport=Mock(), production_reviewed=True)
        adapter.authorization_v2_enabled = adapter.connections_v2_enabled = v2
        state = state_with()
        cur = RecordingCursor(used)

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

    def test_a_mistyped_flag_does_not_leave_the_original_flow_uncapped(self):
        """'TRUE' is not 'true': the v2 flow stays off, and the cap must still hold."""
        result, _ = self.start(used=90, cap=90, v2=False)
        self.assertEqual(result.code, 'discord_capacity_reached')


if __name__ == '__main__':
    unittest.main()
