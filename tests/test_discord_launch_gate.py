"""Launch gate and server cap for Discord connections (fail closed; synthetic data only).

The gate decides which workspaces may START a Discord connection; the cap keeps the shared bot below the number of
servers an unverified Discord app may join. Neither touches Discord, publishing or workspaces that are already connected.
"""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord import launch_gate as gate
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import ACTOR, APP, GUILD, NOW, USER, WORKSPACE

OTHER = '10000000-0000-4000-8000-000000000002'
THIRD = '10000000-0000-4000-8000-000000000003'
HOSTED = {'VERCEL_ENV': 'production'}


def env(value=None, **extra):
    values = dict(extra)
    if value is not None:
        values[gate.ENV_WORKSPACES] = value
    return values


def state_with(channels=(), links=()):
    state = initial_state(WORKSPACE)
    state['phase2'] = {'channels': list(channels), 'assets': [], 'reviews': [], 'jobs': [], 'discordIdentityLinks': list(links)}
    return state


class GateConfiguration(unittest.TestCase):
    def test_unset_is_open_outside_hosted_production(self):
        self.assertTrue(gate.configuration({}).allows(WORKSPACE))
        self.assertTrue(gate.configuration({'VERCEL_ENV': 'preview'}).allows(WORKSPACE))

    def test_unset_is_closed_on_hosted_production(self):
        self.assertFalse(gate.configuration(HOSTED).allows(WORKSPACE))
        self.assertFalse(gate.configuration({'POSTRIFF_ENVIRONMENT': 'production'}).allows(WORKSPACE))

    def test_empty_value_closes_everyone(self):
        self.assertFalse(gate.configuration(env('')).allows(WORKSPACE))
        self.assertFalse(gate.configuration(env('   ')).allows(WORKSPACE))

    def test_everyone_must_be_written_out(self):
        self.assertTrue(gate.configuration(env('*', **HOSTED)).allows(WORKSPACE))
        self.assertTrue(gate.configuration(env(' * ', **HOSTED)).allows(OTHER))

    def test_a_list_allows_only_listed_workspaces_in_any_case(self):
        configured = gate.configuration(env(f'{WORKSPACE.upper()}, {OTHER}', **HOSTED))
        self.assertTrue(configured.allows(WORKSPACE))
        self.assertTrue(configured.allows(OTHER.upper()))
        self.assertFalse(configured.allows(THIRD))
        self.assertFalse(configured.misconfigured)

    def test_whitespace_and_newlines_separate_ids(self):
        configured = gate.configuration(env(f'{WORKSPACE}\n{OTHER}'))
        self.assertTrue(configured.allows(OTHER))

    def test_star_mixed_with_ids_is_misconfigured_and_closed(self):
        configured = gate.configuration(env(f'*,{WORKSPACE}', **HOSTED))
        self.assertTrue(configured.misconfigured)
        self.assertFalse(configured.allows(WORKSPACE))

    def test_an_invalid_id_closes_everything_rather_than_guessing(self):
        configured = gate.configuration(env(f'{WORKSPACE},not-a-workspace'))
        self.assertTrue(configured.misconfigured)
        self.assertFalse(configured.allows(WORKSPACE))

    def test_non_strings_never_allow(self):
        self.assertFalse(gate.configuration(env('')).allows(None))
        self.assertFalse(gate.configuration(env(WORKSPACE)).allows(12345))


class Footprint(unittest.TestCase):
    def test_an_unrevoked_server_card_counts(self):
        self.assertTrue(gate.has_footprint(state_with(channels=[{'id': 'c', 'platform': 'Discord', 'revoked': False}])))

    def test_a_revoked_card_does_not(self):
        self.assertFalse(gate.has_footprint(state_with(channels=[{'id': 'c', 'platform': 'Discord', 'revoked': True}])))

    def test_other_platforms_do_not(self):
        self.assertFalse(gate.has_footprint(state_with(channels=[{'id': 'c', 'platform': 'Mastodon'}])))

    def test_a_linked_identity_counts_a_disconnected_one_does_not(self):
        self.assertTrue(gate.has_footprint(state_with(links=[{'id': 'i', 'status': 'linked'}])))
        self.assertFalse(gate.has_footprint(state_with(links=[{'id': 'i', 'status': 'disconnected'}])))

    def test_malformed_state_is_tolerated(self):
        for bad in (None, {}, {'phase2': None}, {'phase2': {'channels': 'x', 'discordIdentityLinks': [None, 3]}}):
            self.assertFalse(gate.has_footprint(bad))


class Access(unittest.TestCase):
    def test_allowlisted_workspace_is_open(self):
        result = gate.access(WORKSPACE, state_with(), env(WORKSPACE, **HOSTED))
        self.assertEqual((result['status'], result['reason']), ('open', 'allowlisted'))

    def test_everyone_open_reports_open_to_all(self):
        self.assertEqual(gate.access(OTHER, state_with(), env('*', **HOSTED))['reason'], 'open_to_all')

    def test_existing_connection_is_never_locked_out(self):
        live = state_with(channels=[{'id': 'c', 'platform': 'Discord', 'revoked': False}])
        result = gate.access(OTHER, live, env(WORKSPACE, **HOSTED))
        self.assertEqual((result['status'], result['reason']), ('open', 'existing_connection'))

    def test_a_typo_in_the_gate_does_not_lock_out_live_workspaces(self):
        live = state_with(channels=[{'id': 'c', 'platform': 'Discord', 'revoked': False}])
        self.assertEqual(gate.access(OTHER, live, env('oops', **HOSTED))['status'], 'open')

    def test_everyone_else_is_closed_with_a_reason(self):
        self.assertEqual(gate.access(OTHER, state_with(), env(WORKSPACE, **HOSTED)), {'status': 'closed', 'reason': 'invite_only'})
        self.assertEqual(gate.access(OTHER, state_with(), env('oops', **HOSTED)), {'status': 'closed', 'reason': 'misconfigured'})
        self.assertEqual(gate.access(OTHER, state_with(), HOSTED), {'status': 'closed', 'reason': 'invite_only'})


class RequireConnectAccess(unittest.TestCase):
    def connections(self, state):
        cur = Mock()
        used = []

        @contextmanager
        def local(*args):
            used.append(args)
            yield cur, state, ACTOR
        return SimpleNamespace(local=local), used

    def test_an_allowlisted_workspace_never_touches_the_database(self):
        connections, used = self.connections(state_with())
        gate.require_connect_access(connections, WORKSPACE, 'session', env(WORKSPACE, **HOSTED))
        self.assertEqual(used, [])

    def test_a_closed_workspace_is_refused_before_anything_else(self):
        connections, _ = self.connections(state_with())
        with self.assertRaises(AlphaError) as raised:
            gate.require_connect_access(connections, OTHER, 'session', env(WORKSPACE, **HOSTED))
        self.assertEqual((raised.exception.status, raised.exception.code), (403, 'discord_access_closed'))

    def test_a_workspace_with_a_live_discord_card_may_reconnect(self):
        live = state_with(channels=[{'id': 'c', 'platform': 'Discord', 'revoked': False}])
        connections, used = self.connections(live)
        gate.require_connect_access(connections, OTHER, 'session', env(WORKSPACE, **HOSTED))
        self.assertEqual(len(used), 1)

    def test_the_message_promises_nothing_it_cannot_keep(self):
        connections, _ = self.connections(state_with())
        with self.assertRaises(AlphaError) as raised:
            gate.require_connect_access(connections, OTHER, 'session', HOSTED)
        text = str(raised.exception)
        self.assertIn('not open', text)
        self.assertNotIn('waitlist', text.lower())


class Cap(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(gate.guild_cap({}), (None, False))
        self.assertEqual(gate.guild_cap(HOSTED), (gate.DEFAULT_PRODUCTION_CAP, False))
        self.assertEqual(gate.DEFAULT_PRODUCTION_CAP, 90)

    def test_explicit_values(self):
        self.assertEqual(gate.guild_cap({gate.ENV_CAP: '150', **HOSTED}), (150, False))
        self.assertEqual(gate.guild_cap({gate.ENV_CAP: ' 7 '}), (7, False))
        self.assertEqual(gate.guild_cap({gate.ENV_CAP: '0'}), (0, False))

    def test_garbage_closes_the_cap_rather_than_removing_it(self):
        for bad in ('', 'many', '-1', '1.5', '9' * 12, 'NaN'):
            self.assertEqual(gate.guild_cap({gate.ENV_CAP: bad}), (0, True), bad)


class ScriptedCursor:
    def __init__(self, used):
        self.used, self.sql = used, []

    def execute(self, sql, params=None):
        self.sql.append(' '.join(sql.split()))

    def fetchone(self):
        return (self.used,)


class ReserveCapacity(unittest.TestCase):
    def test_no_cap_means_no_sql(self):
        cur = ScriptedCursor(0)
        self.assertIsNone(gate.reserve_capacity(cur, {}))
        self.assertEqual(cur.sql, [])

    def test_takes_the_lock_before_counting(self):
        cur = ScriptedCursor(10)
        result = gate.reserve_capacity(cur, {gate.ENV_CAP: '90'})
        self.assertEqual(result, {'used': 10, 'cap': 90})
        self.assertIn('pg_advisory_xact_lock', cur.sql[0])
        self.assertEqual(len(cur.sql), 2)

    def test_counts_distinct_servers_including_revoked_grants_and_unexpired_starts(self):
        cur = ScriptedCursor(0)
        gate.reserve_capacity(cur, {gate.ENV_CAP: '90'})
        count = cur.sql[1]
        self.assertIn("provider='discord'", count)
        self.assertIn('count(DISTINCT provider_account_id)', count)
        self.assertIn("'bot' = ANY(scopes)", count)
        self.assertNotIn('revoked_at', count)  # a disconnect leaves the shared bot in the server
        self.assertIn('consumed_at IS NULL AND expires_at > now()', count)
        self.assertIn("outcome = 'exchange_started'", count)

    def test_refuses_at_the_cap_and_below_it_admits(self):
        gate.reserve_capacity(ScriptedCursor(89), {gate.ENV_CAP: '90'})
        for used in (90, 91, 500):
            with self.assertRaises(AlphaError) as raised:
                gate.reserve_capacity(ScriptedCursor(used), {gate.ENV_CAP: '90'})
            self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_capacity_reached'))

    def test_a_zero_cap_refuses_every_new_server(self):
        with self.assertRaises(AlphaError):
            gate.reserve_capacity(ScriptedCursor(0), {gate.ENV_CAP: '0'})


class CatalogAnnotation(unittest.TestCase):
    def entries(self):
        return [{'id': 'discord', 'platform': 'Discord', 'connectReady': True}, {'id': 'x', 'platform': 'X', 'connectReady': True}]

    def test_closed_blocks_connect_for_discord_only(self):
        result = gate.annotate_catalog(self.entries(), OTHER, state_with(), env(WORKSPACE, **HOSTED))
        self.assertFalse(result[0]['connectReady'])
        self.assertEqual(result[0]['discordAccess']['status'], 'closed')
        self.assertTrue(result[1]['connectReady'])
        self.assertNotIn('discordAccess', result[1])

    def test_open_leaves_readiness_alone_and_reports_the_cap(self):
        result = gate.annotate_catalog(self.entries(), WORKSPACE, state_with(), env('*', **HOSTED))
        self.assertTrue(result[0]['connectReady'])
        self.assertEqual(result[0]['discordAccess'], {'status': 'open', 'reason': 'open_to_all', 'capped': True})

    def test_outside_hosted_production_nothing_changes(self):
        result = gate.annotate_catalog(self.entries(), WORKSPACE, state_with(), {})
        self.assertTrue(result[0]['connectReady'])
        self.assertFalse(result[0]['discordAccess']['capped'])


class Wiring(unittest.TestCase):
    """The gate is enforced where HTTP enters, and the cap where the OAuth transaction is written."""

    def oauth(self):
        adapter = DiscordProvider(APP, 'secret', 'bot-token', 'https://rafii.example.invalid', transport=Mock(), production_reviewed=True)
        adapter.connections_v2_enabled = adapter.authorization_v2_enabled = True
        return OAuthService(SimpleNamespace(), Mock(), CredentialVault(CredentialVault.generate_key()), {'discord': adapter},
                            'https://rafii.example.invalid', clock=lambda: NOW)

    def test_discord_start_checks_the_gate_before_the_connection_flow(self):
        oauth, order = self.oauth(), []
        with patch.object(gate, 'require_connect_access', side_effect=lambda *a, **k: order.append('gate')), \
                patch.object(oauth.discord_connections, 'start', side_effect=lambda *a, **k: order.append('flow') or {'ok': True}):
            self.assertEqual(oauth.start(WORKSPACE, 'session', 'discord', 'identity', {'discordPurpose': 'identity'}), {'ok': True})
        self.assertEqual(order, ['gate', 'flow'])

    def test_a_closed_gate_stops_the_flow(self):
        oauth = self.oauth()
        refusal = AlphaError('closed', 403, code='discord_access_closed')
        with patch.object(gate, 'require_connect_access', side_effect=refusal), \
                patch.object(oauth.discord_connections, 'start') as flow:
            with self.assertRaises(AlphaError) as raised:
                oauth.start(WORKSPACE, 'session', 'discord', 'identity', {'discordPurpose': 'identity'})
        self.assertEqual(raised.exception.code, 'discord_access_closed')
        flow.assert_not_called()

    def test_other_providers_never_reach_the_gate(self):
        oauth = self.oauth()
        with patch.object(gate, 'require_connect_access') as guard:
            with self.assertRaises(AlphaError):
                oauth.start(WORKSPACE, 'session', 'no-such-provider', 'identity', {})
        guard.assert_not_called()


class StartCapacity(unittest.TestCase):
    """DiscordConnections.start reserves a server slot only for a brand-new installation."""

    def started(self, inputs, *, reserve=None):
        s, _ = service()
        link = {'id': 'identity-1', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'status': 'linked',
                'authorizationGeneration': 'g1', 'userId': USER}
        card = {'id': 'conn-1', 'platform': 'Discord', 'providerAccountId': GUILD, 'discordAuthorizationGeneration': 'gen'}
        state = state_with(channels=[card], links=[link])
        order, cur = [], Mock()
        cur.fetchone.return_value = ('transaction-id',)
        cur.execute.side_effect = lambda sql, *a: order.append('insert') if sql.startswith('INSERT INTO public.pr_oauth_transactions') else None

        @contextmanager
        def local(*_):
            yield cur, state, ACTOR
        s.local = local
        s._fresh_identity = Mock(return_value={'connectionId': 'identity-1', 'authorizationGeneration': 'g1'})
        s.user_guilds = Mock(return_value=[{'id': GUILD}])
        s.bind_identity = Mock()
        reserved = reserve or (lambda cursor, values=None, guild_id=None, person=None, new_server=True: order.append('reserve'))
        with patch('postriff_phase2.hosted.audit'), patch('postriff_phase2.hosted.throttle'), \
                patch.object(gate, 'reserve_capacity', side_effect=reserved) as spy:
            try:
                result = s.start(WORKSPACE, 'session', 'publish' if inputs.get('discordPurpose') != 'identity' else 'identity', inputs)
            except AlphaError as error:
                result = error
        return result, order, spy

    def test_new_installation_reserves_before_it_writes_the_transaction(self):
        result, order, spy = self.started({'discordPurpose': 'installation', 'guildId': GUILD, 'identityConnectionId': 'identity-1'})
        self.assertEqual(order, ['reserve', 'insert'])
        self.assertEqual(result['transactionId'], 'transaction-id')
        # a server that already holds a slot is let through, and one person may only have a few starts in flight
        self.assertEqual(spy.call_args.kwargs, {'guild_id': GUILD, 'person': (WORKSPACE, ACTOR), 'new_server': True})

    def test_a_full_house_writes_no_transaction_and_sends_nobody_to_discord(self):
        full = AlphaError('Discord is at capacity.', 409, code='discord_capacity_reached')
        result, order, spy = self.started({'discordPurpose': 'installation', 'guildId': GUILD, 'identityConnectionId': 'identity-1'},
                                          reserve=Mock(side_effect=full))
        self.assertIsInstance(result, AlphaError)
        self.assertEqual(result.code, 'discord_capacity_reached')
        self.assertNotIn('insert', order)

    def test_reconnecting_an_existing_server_takes_no_new_slot_but_counts_as_a_start(self):
        result, order, spy = self.started({'discordPurpose': 'installation', 'guildId': GUILD, 'identityConnectionId': 'identity-1',
                                           'connectionId': 'conn-1'})
        self.assertEqual(spy.call_args.kwargs, {'guild_id': GUILD, 'person': (WORKSPACE, ACTOR), 'new_server': False})
        self.assertEqual(order, ['reserve', 'insert'])

    def test_identity_linking_does_not_use_a_slot(self):
        result, order, spy = self.started({'discordPurpose': 'identity'})
        spy.assert_not_called()


class KillSwitch(unittest.TestCase):
    """POSTRIFF_OAUTH_DISCORD_DISABLED composes with the gate: it wins, and it never resends anything."""

    def paused(self, wire=None):
        provider = DiscordProvider(APP, 'secret', 'bot-token', 'https://rafii.example.invalid', transport=wire or Mock(), production_reviewed=True)
        provider.connections_v2_enabled = provider.authorization_v2_enabled = True
        provider.execution_enabled = False
        return provider

    def test_a_paused_provider_refuses_to_start_even_when_the_gate_is_wide_open(self):
        s, _ = service()
        s.oauth._provider = lambda _: self.paused()
        self.assertTrue(gate.configuration({gate.ENV_WORKSPACES: '*'}).allows(WORKSPACE))
        with self.assertRaises(AlphaError) as raised:
            s.start(WORKSPACE, 'session', 'identity', {'discordPurpose': 'identity'})
        self.assertEqual(raised.exception.status, 503)

    def test_a_paused_provider_holds_a_fenced_post_and_makes_no_request(self):
        from postriff_phase2.hosted_social import HostedSocial
        wire = Mock()
        social = HostedSocial(Mock(), {'discord': self.paused(wire)})
        result = social.submit_discord_authorized({'platform': 'Discord'}, {'grant': {'accessToken': 'synthetic'}})
        self.assertEqual((result['state'], result['discordDeliveryEvidence']), ('held', 'not_sent'))
        wire.assert_not_called()

    def test_the_publish_route_reports_paused(self):
        from postriff_phase2.capabilities import publish_route
        route = publish_route({'phase2': {'channels': []}}, {'platform': 'Discord'}, providers={'discord': self.paused()}, live=True)
        self.assertEqual((route['publish'], route['code']), (False, 'paused'))

    def test_the_catalog_marks_a_paused_discord_without_reopening_the_gate(self):
        entries = [{'id': 'discord', 'platform': 'Discord', 'connectReady': False, 'executionPaused': True}]
        gate.annotate_catalog(entries, WORKSPACE, state_with(), env('*', **HOSTED))
        self.assertTrue(entries[0]['executionPaused'])
        self.assertFalse(entries[0]['connectReady'])


class WidenWithoutRedeploy(unittest.TestCase):
    """The gate and the cap are read at request time, so an env change alone moves tester-only -> capped public -> wider."""

    def test_the_same_process_follows_the_environment(self):
        values = dict(HOSTED, **{gate.ENV_WORKSPACES: WORKSPACE})
        self.assertTrue(gate.configuration(values).allows(WORKSPACE))
        self.assertFalse(gate.configuration(values).allows(OTHER))
        values[gate.ENV_WORKSPACES] = '*'
        self.assertTrue(gate.configuration(values).allows(OTHER))
        values[gate.ENV_WORKSPACES] = ''
        self.assertFalse(gate.configuration(values).allows(WORKSPACE))

    def test_the_cap_can_be_raised_after_verification_and_lowered_again(self):
        values = dict(HOSTED)
        self.assertEqual(gate.guild_cap(values)[0], 90)
        values[gate.ENV_CAP] = '100000'
        self.assertEqual(gate.guild_cap(values)[0], 100000)
        values[gate.ENV_CAP] = '0'
        with self.assertRaises(AlphaError):
            gate.reserve_capacity(ScriptedCursor(0), values)

    def test_reading_the_process_environment_is_live(self):
        import os
        with patch.dict(os.environ, {gate.ENV_WORKSPACES: WORKSPACE}, clear=False):
            self.assertTrue(gate.configuration().allows(WORKSPACE))
            self.assertFalse(gate.configuration().allows(OTHER))
        with patch.dict(os.environ, {gate.ENV_WORKSPACES: '*'}, clear=False):
            self.assertTrue(gate.configuration().allows(OTHER))


if __name__ == '__main__':
    unittest.main()
