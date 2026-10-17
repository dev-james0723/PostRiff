"""Multi-guild authority reuses the actual P0 approval model."""
import copy
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.authorization import register_destination, destination_id, destination
from test_discord_publish_authorization import fixture, review, approve, APP, BOT, USER, GUILD, FIRST, GENERATION, ACTOR, NOW, WORKSPACE


class Destinations(unittest.TestCase):
    def test_two_guild_installations_have_independent_exact_approvals(self):
        engine, state, first, variant = fixture()
        second = copy.deepcopy(first);second.update(id='discord-second-install', providerAccountId='666666', discordDestinations=[], defaultDestinationId=None)
        state['phase2']['channels'].append(second)
        register_destination(state, second, {'applicationId': APP, 'botUserId': BOT, 'linkedUserId': USER,
            'guildId': '666666', 'channelId': FIRST, 'guildName': 'Second synthetic guild', 'channelName': '#synthetic', 'kind': 'text'}, GENERATION, ACTOR, NOW)
        target = destination_id(WORKSPACE, second['id'], '666666', FIRST)
        one = approve(engine, state, review(engine, state, first, variant))
        # A channel snowflake alone cannot select another guild/connection's authority.
        with self.assertRaises(AlphaError):
            destination(state, first, target)
        first['defaultDestinationId'] = None
        self.assertEqual(one['manifest']['discord']['target']['guildId'], GUILD)
        self.assertEqual(len(state['phase2']['jobs']), 1)

    def test_cross_tenant_destination_registry_is_not_approval_evidence(self):
        _, state, channel, _ = fixture()
        channel['discordDestinations'][0]['workspaceId'] = 'foreign-workspace'
        with self.assertRaises(AlphaError):
            destination(state, channel, channel['discordDestinations'][0]['id'])
