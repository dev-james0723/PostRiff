"""G2E-C-05 / G2E-A-11: a ceiling on distinct Discord servers per workspace and per member (beyond the shared cap).

Before: one workspace, one member and one Discord identity could hold as many live servers as the shared cap allowed
(pg_poc_a10_per_workspace: two live servers with the cap at two)."""
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord.oauth import DiscordConnections, MAX_SERVERS_PER_MEMBER, MAX_SERVERS_PER_WORKSPACE
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import ACTOR, GUILD, WORKSPACE

OTHER = '20000000-0000-4000-8000-0000000000bb'


def state_with(mine=0, others=0, revoked=0):
    state = initial_state(WORKSPACE)
    links = [{'id': 'identity-mine', 'authorizedBy': ACTOR, 'workspaceId': WORKSPACE}, {'id': 'identity-other', 'authorizedBy': OTHER, 'workspaceId': WORKSPACE}]
    cards = [{'id': f'm{i}', 'platform': 'Discord', 'providerAccountId': f'8{i:06d}', 'discordConnectionKind': 'installation',
              'discordIdentityConnectionId': 'identity-mine', 'revoked': i < revoked} for i in range(mine)]
    cards += [{'id': f'o{i}', 'platform': 'Discord', 'providerAccountId': f'9{i:06d}', 'discordConnectionKind': 'installation',
               'discordIdentityConnectionId': 'identity-other', 'revoked': False} for i in range(others)]
    cards.append({'id': 'hook', 'platform': 'Discord', 'discordConnectionKind': 'webhook', 'providerAccountId': 'w'})
    state['phase2'] = {'channels': cards, 'discordIdentityLinks': links}
    return state


class ServerCeilings(unittest.TestCase):
    def test_the_member_ceiling(self):
        DiscordConnections.server_ceiling(state_with(mine=MAX_SERVERS_PER_MEMBER - 1), ACTOR, '1111111')
        with self.assertRaises(AlphaError) as raised:
            DiscordConnections.server_ceiling(state_with(mine=MAX_SERVERS_PER_MEMBER), ACTOR, '1111111')
        self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_server_limit'))
        # another person in the same workspace is not held to this member's count
        DiscordConnections.server_ceiling(state_with(mine=MAX_SERVERS_PER_MEMBER), OTHER, '1111111')

    def test_the_workspace_ceiling_counts_every_member_and_disconnected_servers(self):
        DiscordConnections.server_ceiling(state_with(mine=10, others=MAX_SERVERS_PER_WORKSPACE - 11), ACTOR, '1111111')
        with self.assertRaises(AlphaError) as raised:
            DiscordConnections.server_ceiling(state_with(mine=10, others=MAX_SERVERS_PER_WORKSPACE - 10), ACTOR, '1111111')
        self.assertEqual(raised.exception.code, 'discord_server_limit')
        with self.assertRaises(AlphaError):  # a disconnected server still holds its slot in the shared bot
            DiscordConnections.server_ceiling(state_with(mine=MAX_SERVERS_PER_MEMBER, revoked=MAX_SERVERS_PER_MEMBER), ACTOR, '1111111')

    def test_a_server_the_workspace_already_holds_is_never_counted_twice(self):
        full = state_with(mine=MAX_SERVERS_PER_MEMBER)
        DiscordConnections.server_ceiling(full, ACTOR, full['phase2']['channels'][0]['providerAccountId'])  # reconnect
        DiscordConnections.server_ceiling(state_with(), ACTOR, GUILD)
        DiscordConnections.server_ceiling(initial_state(WORKSPACE), ACTOR, GUILD)  # a workspace with no Discord state at all

    def test_start_refuses_before_any_discord_request_or_cap_slot(self):
        s, wire = service()
        state = state_with(mine=MAX_SERVERS_PER_MEMBER)
        cur = Mock()

        @contextmanager
        def local(*_):
            yield cur, state, ACTOR
        s.local = local
        with patch('postriff_phase2.hosted.throttle'), patch('postriff_phase2.hosted.audit'), \
                patch('postriff_phase2.discord.oauth.launch_gate.reserve_capacity') as reserve:
            with self.assertRaises(AlphaError) as raised:
                s.start(WORKSPACE, 'session-token', 'publish', {'discordPurpose': 'installation', 'identityConnectionId': 'identity-mine', 'guildId': GUILD})
        self.assertEqual(raised.exception.code, 'discord_server_limit')
        self.assertEqual(wire.lifecycle_calls, [])
        reserve.assert_not_called()

    def test_the_ceilings_are_far_above_the_shared_launch_cap_per_person(self):
        self.assertGreaterEqual(MAX_SERVERS_PER_MEMBER, 10)
        self.assertGreater(MAX_SERVERS_PER_WORKSPACE, MAX_SERVERS_PER_MEMBER)


if __name__ == '__main__':
    unittest.main()
