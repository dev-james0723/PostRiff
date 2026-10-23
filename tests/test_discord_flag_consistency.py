"""G2E-A-08 (P4): AUTHORIZATION_V2 on with CONNECTIONS_V2 mistyped left the original connect flow reachable, and its
envelopes pass the worker grant with no authorizer check. That combination must fail closed (503) on every entry."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_publish_authorization import APP, GUILD, USER, WORKSPACE


def oauth(authorization, connections):
    adapter = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid', transport=Mock(), production_reviewed=True)
    adapter.authorization_v2_enabled, adapter.connections_v2_enabled = authorization, connections
    repository = SimpleNamespace(connection_factory=Mock(), transaction=Mock(side_effect=AssertionError('no database before the refusal')))
    return OAuthService(repository, SimpleNamespace(), CredentialVault(CredentialVault.generate_key()), {'discord': adapter}, 'https://rafii.example.invalid'), adapter


class MixedFlagsFailClosed(unittest.TestCase):
    def test_start_complete_and_the_worker_grant_refuse_with_503_before_any_work(self):
        service, adapter = oauth(True, False)
        legacy = json.dumps({'v': 2, 'guild': GUILD, 'user': USER})  # the original flow's envelope: no kind, no identity link
        cur = Mock()
        cur.fetchone.return_value = (*service.vault.encrypt(legacy), ['bot', 'identify'], 'generation')
        calls = [lambda: service.start(WORKSPACE, 'session', 'discord', 'publish'),
                 lambda: service.complete(WORKSPACE, 'session', 'discord', 's' * 32, 'code'),
                 lambda: service.discord_grant_for_worker(WORKSPACE, 'connection', cur=cur),
                 lambda: service.discord_grant_for_worker(WORKSPACE, 'connection')]
        for call in calls:
            with self.assertRaises(AlphaError) as raised:
                call()
            self.assertEqual(raised.exception.status, 503)
        cur.execute.assert_not_called()
        adapter.transport.assert_not_called()

    def test_the_consistent_combinations_are_not_refused_by_this_guard(self):
        for authorization, connections in ((False, False), (True, True), (False, True)):
            service, _ = oauth(authorization, connections)
            service._discord_flags_consistent()  # raises only for (True, False)

    def test_other_providers_never_enter_the_guard(self):
        service, _ = oauth(True, False)
        service._discord_flags_consistent = Mock()
        with self.assertRaises(Exception):
            service.start(WORKSPACE, 'session', 'unknown-provider', 'publish')
        service._discord_flags_consistent.assert_not_called()


if __name__ == '__main__':
    unittest.main()
