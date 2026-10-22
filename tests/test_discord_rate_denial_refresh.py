"""A refusal by the shared request coordinator must never destroy a Discord connection (synthetic state only).

The coordinator refuses BEFORE a request is built or sent (an operator hold, an expired policy, an open circuit, a busy
minute). Refreshing a person's rotating token is the one place where any other failure is treated as ambiguous and
revokes the identity and every server installed through it. A refusal that sent nothing is not ambiguous: the old
refresh token is untouched, so the claim must be freed and the same error raised, and a later attempt must work. The same
holds when Discord itself answers 429 to the refresh request: a rate-limited request is not processed, so the token is
unspent. Every other answer stays ambiguous.
"""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord.oauth import DiscordConnections
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, RateDelayed, ReadAdmissionDelayed
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import ACTOR, GUILD, NOW, USER, WORKSPACE


class Harness:
    """One identity with an expired access token, one installed server and one authorized channel."""

    def __init__(self, response):
        self.s, self.wire = service()
        self.state = initial_state(WORKSPACE)
        self.record = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'status': 'linked',
                       'authorizationGeneration': 'generation'}
        self.card = {'id': 'conn-1', 'platform': 'Discord', 'providerAccountId': GUILD,
                     'discordIdentityConnectionId': 'identity', 'revoked': False,
                     'discordDestinations': [{'status': 'authorized'}]}
        self.state['phase2'] = {'discordIdentityLinks': [self.record], 'channels': [self.card]}
        state = self.state

        @contextmanager
        def local(*_):
            yield Mock(), state, ACTOR
        self.s.local = local
        access, _key = self.s.oauth.vault.encrypt(json.dumps({'user': USER, 'at': 'old'}))
        refresh, _ = self.s.oauth.vault.encrypt('synthetic-refresh')
        self.s.bind_identity = Mock(return_value=((access, _key, refresh, NOW - 10, 'generation', ['identify', 'guilds'], USER),
                                                  {'user': USER, 'at': 'old'}))
        self.s._response = Mock(side_effect=response)
        self.s.save_state = Mock()

    def refresh(self):
        try:
            self.s._fresh_identity(WORKSPACE, 'session', 'identity')
        except AlphaError as error:
            return error
        raise AssertionError('the refresh was expected to fail')


class RateDenialDoesNotRevoke(unittest.TestCase):
    def check(self, denial):
        harness = Harness(denial)
        error = harness.refresh()
        # The same refusal reaches the caller, so it can show "busy" or "paused" and try again.
        self.assertIs(error, denial)
        self.assertEqual(error.status, denial.status)
        # Nothing was revoked.
        self.assertEqual(harness.record['status'], 'linked')
        self.assertFalse(harness.card['revoked'])
        self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['authorized'])
        # The claim is free again, otherwise the next attempt would fail as "refresh pending" and need a reconnect.
        self.assertNotIn('refreshClaim', harness.record)
        self.assertNotIn('refreshStartedAt', harness.record)
        self.assertEqual(harness.s.save_state.call_count, 2)  # the claim, then its release
        return harness

    def test_a_delayed_request_leaves_the_connection_alone(self):
        harness = self.check(RateDelayed(30))
        self.assertEqual(harness.s._response.call_count, 1)

    def test_an_unavailable_coordinator_leaves_the_connection_alone(self):
        self.check(RateCoordinatorUnavailable())

    def test_a_read_admission_refusal_leaves_the_connection_alone(self):
        self.check(ReadAdmissionDelayed(RateDelayed(5)))

    def test_the_next_attempt_is_not_blocked_by_a_stale_claim(self):
        harness = self.check(RateDelayed(30))
        again = harness.refresh()
        self.assertIsInstance(again, RateDelayed)
        self.assertEqual(again.code, 'discord_rate_delayed')
        self.assertEqual(harness.record['status'], 'linked')
        self.assertEqual(harness.s._response.call_count, 2)  # it really tried the exchange again, it was not refused as pending

    def test_the_hold_used_as_the_break_glass_step_cannot_cost_anyone_a_connection(self):
        """An operator hold makes every request raise this; any number of attempts may be made while it lasts."""
        harness = Harness(RateCoordinatorUnavailable())
        for _ in range(5):
            error = harness.refresh()
            self.assertEqual(error.code, 'discord_rate_coordinator_unavailable')
        self.assertEqual(harness.record['status'], 'linked')
        self.assertFalse(harness.card['revoked'])


class ProviderRateLimitDoesNotRevoke(unittest.TestCase):
    """Discord's own 429 on the refresh POST, through the real request code (only the wire is synthetic)."""

    def harness(self, status):
        harness = Harness(None)
        harness.s._response = DiscordConnections._response.__get__(harness.s)  # the real one, not the mock
        harness.wire.route_overrides[('POST', '/oauth2/token')] = {'status': status, 'body': {}}
        return harness

    def token_posts(self, harness):
        return [call for call in harness.wire.lifecycle_calls if call == ('POST', '/oauth2/token')]

    def test_a_429_frees_the_claim_and_revokes_nothing(self):
        harness = self.harness(429)
        error = harness.refresh()
        self.assertIsInstance(error, RateDelayed)
        self.assertEqual((error.status, error.code, error.rate_cause), (429, 'discord_rate_delayed', 'provider_429'))
        self.assertGreater(error.retry_after_seconds, 0)
        self.assertEqual(harness.record['status'], 'linked')
        self.assertFalse(harness.card['revoked'])
        self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['authorized'])
        self.assertNotIn('refreshClaim', harness.record)
        self.assertNotIn('refreshStartedAt', harness.record)
        self.assertEqual(len(self.token_posts(harness)), 1)

    def test_the_next_attempt_really_tries_again(self):
        harness = self.harness(429)
        harness.refresh()
        again = harness.refresh()
        self.assertIsInstance(again, RateDelayed)  # not "refresh pending, reconnect"
        self.assertEqual(len(self.token_posts(harness)), 2)
        self.assertEqual(harness.record['status'], 'linked')

    def test_every_other_status_is_still_ambiguous_and_fails_closed(self):
        for status in (400, 401, 403, 500, 502, 503, 504):
            harness = self.harness(status)
            error = harness.refresh()
            self.assertEqual(error.code, 'discord_connection_required', status)
            self.assertEqual(harness.record['status'], 'reconnect_required', status)
            self.assertTrue(harness.card['revoked'], status)

    def test_the_provider_status_is_tagged_on_the_error_and_nothing_else_changes(self):
        harness = self.harness(429)
        with self.assertRaises(AlphaError) as raised:
            harness.s._response('POST', '/oauth2/token', user_id=USER, form={})
        self.assertEqual((raised.exception.status, raised.exception.discord_status, raised.exception.discord_permanent), (503, 429, False))
        harness.wire.route_overrides[('POST', '/oauth2/token')] = {'status': 401, 'body': {}}
        with self.assertRaises(AlphaError) as raised:
            harness.s._response('POST', '/oauth2/token', user_id=USER, form={})
        self.assertEqual((raised.exception.status, raised.exception.discord_status, raised.exception.discord_permanent), (409, 401, True))


class OtherFailuresStillFailClosed(unittest.TestCase):
    """The ambiguous cases keep their protection: anything else means the rotating token may have been spent."""

    def assert_revoked(self, failure):
        harness = Harness(failure)
        error = harness.refresh()
        self.assertEqual(error.code, 'discord_connection_required')
        self.assertEqual(harness.record['status'], 'reconnect_required')
        self.assertTrue(harness.card['revoked'])

    def test_a_provider_error_revokes(self):
        self.assert_revoked(AlphaError('Discord access is unavailable. Reconnect if permissions were removed.', 503))

    def test_a_transport_failure_revokes(self):
        self.assert_revoked(TimeoutError('the response was lost'))

    def test_a_refusal_after_the_exchange_succeeded_revokes(self):
        """The old refresh token is spent once Discord answered; losing the new one cannot be retried."""
        harness = Harness([{'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 604800, 'scope': 'identify guilds'}])
        harness.s.token_body = Mock(side_effect=lambda body: body)
        harness.s.verified_user = Mock(side_effect=RateDelayed(5))
        error = harness.refresh()
        self.assertEqual(error.code, 'discord_connection_required')
        self.assertEqual(harness.record['status'], 'reconnect_required')
        self.assertTrue(harness.card['revoked'])


if __name__ == '__main__':
    unittest.main()
