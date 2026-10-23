"""G2E-A-07 / G2E-C-07 (P12): the workspace snapshot every member receives must not carry another member's personal Discord
identity (Discord user id, display name, Rafii member id, generation, refresh claim)."""
import copy
import json
import unittest

from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands
from test_discord_publish_authorization import ACTOR, NOW, WORKSPACE

OTHER_MEMBER = '20000000-0000-4000-8000-0000000000bb'
OTHER_DISCORD = '777000111222333444'


class TheSnapshotCarriesNoPersonalDiscordIdentity(unittest.TestCase):
    def state(self):
        state = initial_phase2_state(WORKSPACE, ACTOR, 'Rafii member', 'studio', NOW, execution='hosted-candidate')
        state['phase2']['discordIdentityLinks'] = [
            {'id': 'discord-identity-aaa', 'workspaceId': WORKSPACE, 'applicationId': '1234567', 'userId': OTHER_DISCORD,
             'account': 'Alice the Admin', 'authorizedBy': OTHER_MEMBER, 'authorizedAt': NOW, 'authorizationGeneration': 'gen-1',
             'status': 'linked', 'expiresAt': NOW + 3600, 'discoverGuilds': True, 'refreshClaim': 'claim-uuid', 'refreshStartedAt': NOW}]
        state['phase2']['discordEngagement'] = {'consents': [{'secret': 'not for the snapshot'}]}
        return state

    def test_other_members_identity_records_are_not_in_the_presented_state(self):
        commands = HostedPhase2Commands(clock=lambda: NOW)
        state = self.state()
        before = copy.deepcopy(state)
        shown = commands.present(state, 1)
        phase2 = shown['state']['phase2']
        self.assertNotIn('discordIdentityLinks', phase2)
        text = json.dumps(shown)
        for private in (OTHER_DISCORD, 'Alice the Admin', OTHER_MEMBER, 'claim-uuid', 'gen-1'):
            self.assertNotIn(private, text)
        self.assertEqual(state['phase2']['discordIdentityLinks'], before['phase2']['discordIdentityLinks'])  # the server keeps its records; only the projection drops them

    def test_no_phase2_key_that_names_discord_custody_is_presented(self):
        """A tripwire for the next Discord key: review whether a member may see it before adding it to this allowance."""
        shown = HostedPhase2Commands(clock=lambda: NOW).present(self.state(), 1)
        self.assertEqual([k for k in shown['state']['phase2'] if k.lower().startswith('discord')], [])


if __name__ == '__main__':
    unittest.main()
