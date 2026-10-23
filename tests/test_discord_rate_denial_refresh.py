"""A refusal by the shared request coordinator must never destroy a Discord connection (synthetic state only).

The coordinator refuses BEFORE a request is built or sent (an operator hold, an expired policy, an open circuit, a busy
minute). Refreshing a person's rotating token is the one place where any other failure is treated as ambiguous and
revokes the identity and every server installed through it. A refusal that sent nothing is not ambiguous: the old
refresh token is untouched, so the claim must be freed and the same error raised, and a later attempt must work. The same
holds when Discord itself answers 429 to the refresh request: a rate-limited request is not processed, so the token is
unspent. Every other answer stays ambiguous.

G2E-A-01: only Discord's OWN refusal (a JSON error in Discord's shape, or `invalid_grant`) is a verdict on a person's
consent. An HTML/WAF page, an unknown body, a 5xx or a lost connection is not: it must not revoke an installation, zero a
credential or force customers to reconnect. Where a rotating refresh token may or may not have been spent (a 5xx, a lost
connection, a crash) the identity still fails closed, but the servers installed through it are suspended, not destroyed.
"""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.discord.oauth import DiscordConnections, REFRESH_CLAIM_TTL, SETTLE_ATTEMPTS, stable_id
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, RateDelayed, ReadAdmissionDelayed, SharedPostgresBudget
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_oauth_lifecycle import service
from test_discord_publish_authorization import ACTOR, APP, GUILD, NOW, USER, WORKSPACE
from test_discord_rate_limits import MemoryLedger, synthetic_policy


class Harness:
    """One identity with an expired access token, one installed server and one authorized channel."""

    def __init__(self, response, expired=True):
        self.s, self.wire = service()
        self.state = initial_state(WORKSPACE)
        self.record = {'id': 'identity', 'workspaceId': WORKSPACE, 'authorizedBy': ACTOR, 'status': 'linked',
                       'authorizationGeneration': 'generation'}
        self.card = {'id': 'conn-1', 'platform': 'Discord', 'providerAccountId': GUILD,
                     'discordIdentityConnectionId': 'identity', 'revoked': False,
                     'discordDestinations': [{'status': 'authorized'}]}
        self.state['phase2'] = {'discordIdentityLinks': [self.record], 'channels': [self.card]}
        state = self.state
        self.cur = Mock(rowcount=1)

        @contextmanager
        def local(*_):
            yield self.cur, state, ACTOR
        self.s.local = local
        access, _key = self.s.oauth.vault.encrypt(json.dumps({'user': USER, 'at': 'old'}))
        refresh, _ = self.s.oauth.vault.encrypt('synthetic-refresh')
        self.s.bind_identity = Mock(return_value=((access, _key, refresh, NOW - 10 if expired else NOW + 3600, 'generation', ['identify', 'guilds'], USER),
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

    def test_a_refusal_that_is_not_discords_own_leaves_the_token_unspent_and_the_connection_alone(self):
        """A 4xx that is not Discord's JSON refusal (an empty or unknown body) did not exercise the grant."""
        for status in (400, 401, 403):
            harness = self.harness(status)
            error = harness.refresh()
            self.assertEqual((error.status, error.code), (503, 'service_unavailable'), status)
            self.assertEqual(harness.record['status'], 'linked', status)
            self.assertFalse(harness.card['revoked'], status)
            self.assertNotIn('refreshClaim', harness.record)  # freed, so the next attempt really tries again
            self.assertNotIn('discordSuspended', harness.card)

    def test_a_server_error_is_ambiguous_so_the_identity_closes_but_the_servers_are_only_suspended(self):
        for status in (500, 502, 503, 504):
            harness = self.harness(status)
            error = harness.refresh()
            self.assertEqual(error.code, 'discord_connection_required', status)
            self.assertEqual(harness.record['status'], 'reconnect_required', status)
            self.assertTrue(harness.record['dependentsSuspended'], status)
            self.assertFalse(harness.card['revoked'], status)
            self.assertTrue(harness.card['discordSuspended'], status)
            self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['authorized'], status)

    def test_discords_own_refusal_still_revokes_everything(self):
        """Genuine answers: `invalid_grant` on the token endpoint, or a JSON 401/403 in Discord's error shape."""
        for status, body in ((400, {'error': 'invalid_grant', 'error_description': 'Invalid "refresh_token" in request.'}),
                             (401, {'message': '401: Unauthorized', 'code': 0}),
                             (403, {'message': 'Missing Access', 'code': 50001})):
            harness = self.harness(status)
            harness.wire.route_overrides[('POST', '/oauth2/token')] = {'status': status, 'body': body, 'headers': {'content-type': 'application/json'}}
            error = harness.refresh()
            self.assertEqual(error.code, 'discord_connection_required', status)
            self.assertEqual(harness.record['status'], 'reconnect_required', status)
            self.assertTrue(harness.card['revoked'], status)
            self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['revoked'], status)

    def test_the_provider_status_is_tagged_on_the_error_and_nothing_else_changes(self):
        harness = self.harness(429)
        with self.assertRaises(AlphaError) as raised:
            harness.s._response('POST', '/oauth2/token', user_id=USER, form={})
        self.assertEqual((raised.exception.status, raised.exception.discord_status, raised.exception.discord_permanent), (503, 429, False))
        harness.wire.route_overrides[('POST', '/oauth2/token')] = {'status': 401, 'body': {'message': '401: Unauthorized', 'code': 0}}
        with self.assertRaises(AlphaError) as raised:
            harness.s._response('POST', '/oauth2/token', user_id=USER, form={})
        self.assertEqual((raised.exception.status, raised.exception.discord_status, raised.exception.discord_permanent), (409, 401, True))
        harness.wire.route_overrides[('POST', '/oauth2/token')] = {'status': 401, 'body': {}}
        with self.assertRaises(AlphaError) as raised:
            harness.s._response('POST', '/oauth2/token', user_id=USER, form={})
        self.assertEqual((raised.exception.status, raised.exception.discord_status, raised.exception.discord_permanent), (503, 401, False))


class OtherFailuresStillFailClosed(unittest.TestCase):
    """The ambiguous cases keep their protection: anything else means the rotating token may have been spent.

    The identity stays closed (the person must link it again) but the servers installed through it are suspended, not
    destroyed, and they come back when the same Discord user links again (see ResumeAfterSuspension)."""

    def assert_suspended(self, failure):
        harness = Harness(failure)
        error = harness.refresh()
        self.assertEqual(error.code, 'discord_connection_required')
        self.assertEqual(harness.record['status'], 'reconnect_required')
        self.assertTrue(harness.record['dependentsSuspended'])
        self.assertNotIn('refreshClaim', harness.record)
        self.assertFalse(harness.card['revoked'])
        self.assertTrue(harness.card['discordSuspended'])
        self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['authorized'])
        # nothing was zeroed: the installation's credential row is not touched by a suspension
        self.assertFalse(any('pr_encrypted_credentials' in str(call) for call in harness.cur.execute.call_args_list))
        return harness

    def test_a_provider_error_suspends(self):
        self.assert_suspended(AlphaError('Discord access is unavailable. Reconnect if permissions were removed.', 503))

    def test_a_transport_failure_suspends(self):
        self.assert_suspended(TimeoutError('the response was lost'))

    def test_a_refusal_after_the_exchange_succeeded_suspends(self):
        """The old refresh token is spent once Discord answered; losing the new one cannot be retried."""
        harness = Harness([{'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 604800, 'scope': 'identify guilds'}])
        harness.s.token_body = Mock(side_effect=lambda body: body)
        harness.s.verified_user = Mock(side_effect=RateDelayed(5))
        error = harness.refresh()
        self.assertEqual(error.code, 'discord_connection_required')
        self.assertEqual(harness.record['status'], 'reconnect_required')
        self.assertFalse(harness.card['revoked'])
        self.assertTrue(harness.card['discordSuspended'])

    def test_discord_saying_the_new_token_is_not_authorized_revokes(self):
        denial = AlphaError('Discord access is unavailable.', 409); denial.discord_permanent = True
        harness = Harness([{'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 604800, 'scope': 'identify guilds'}])
        harness.s.token_body = Mock(side_effect=lambda body: body)
        harness.s.verified_user = Mock(side_effect=denial)
        error = harness.refresh()
        self.assertEqual(error.code, 'discord_connection_required')
        self.assertTrue(harness.card['revoked'])


EDGE_PAGE = {'status': 403, 'headers': {'content-type': 'text/html; charset=UTF-8', 'cf-ray': '8f3a1c2b4d5e6f70-HKG'},
             'body': {'raw': '<!DOCTYPE html><html><title>Attention Required! | Cloudflare</title>error code: 1020</html>'}}
DISCORD_401 = {'status': 401, 'headers': {'content-type': 'application/json', 'cf-ray': '8f3a1c2b4d5e6f71-HKG'},
               'body': {'message': '401: Unauthorized', 'code': 0}}


class NonAuthoritativeAnswersRevokeNothing(unittest.TestCase):
    """G2E-A-01 (P7). The old code turned ANY 401/403/404 (or any non-429 failure of the refresh) into
    discord_connection_required + discord_permanent: one Cloudflare page, one 5xx or one dropped connection revoked every
    installation bound to the identity, zeroed their credentials and forced every customer to reconnect."""

    def harness(self, route, answer, *, expired):
        harness = Harness(None, expired=expired)
        harness.s._response = DiscordConnections._response.__get__(harness.s)  # the real classification, over a synthetic wire
        harness.wire.route_overrides[route] = answer
        return harness

    def assert_untouched(self, harness, label):
        self.assertEqual(harness.record['status'], 'linked', label)
        self.assertNotIn('dependentsSuspended', harness.record, label)
        self.assertFalse(harness.card['revoked'], label)
        self.assertNotIn('discordSuspended', harness.card, label)
        self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['authorized'], label)
        self.assertFalse(any('pr_encrypted_credentials' in str(call) for call in harness.cur.execute.call_args_list), label)

    def test_an_edge_page_a_server_error_or_an_unknown_body_on_the_still_valid_token_changes_nothing(self):
        answers = [('cloudflare 403 html', EDGE_PAGE), ('502', {**EDGE_PAGE, 'status': 502}), ('503', {**EDGE_PAGE, 'status': 503}),
                   ('500 json', {'status': 500, 'body': {'message': 'Internal Server Error', 'code': 0}}),
                   ('401 empty', {'status': 401, 'body': {}}), ('403 empty', {'status': 403, 'body': {}}),
                   ('404 empty', {'status': 404, 'body': {}}),
                   ('403 json without a discord code', {'status': 403, 'body': {'message': 'blocked'}}),
                   ('cloudflare json', {'status': 403, 'body': {'title': 'Error 1020', 'status': 403, 'cloudflare_error': True}}),
                   ('401 html even with a code-shaped body', {**DISCORD_401, 'headers': {'content-type': 'text/html', 'cf-ray': 'x'}})]
        for label, answer in answers:
            harness = self.harness(('GET', '/oauth2/@me'), answer, expired=False)
            error = harness.refresh()
            self.assertEqual(error.status, 503, label)
            self.assertNotEqual(error.code, 'discord_connection_required', label)
            self.assertFalse(error.discord_permanent, label)
            self.assert_untouched(harness, label)
            harness.s.save_state.assert_not_called()

    def test_a_lost_connection_on_the_still_valid_token_changes_nothing(self):
        harness = Harness(None, expired=False)
        harness.s._response = DiscordConnections._response.__get__(harness.s)
        harness.s.adapter.transport = Mock(side_effect=AlphaError('The provider is temporarily unreachable.', 503))
        error = harness.refresh()
        self.assertEqual(error.status, 503)
        self.assert_untouched(harness, 'transport')
        harness.s.save_state.assert_not_called()

    def test_discords_own_json_refusal_on_the_still_valid_token_still_revokes(self):
        for status, body in ((401, {'message': '401: Unauthorized', 'code': 0}), (403, {'message': 'Missing Access', 'code': 50001}),
                             (404, {'message': 'Unknown User', 'code': 10013})):
            harness = self.harness(('GET', '/oauth2/@me'), {'status': status, 'headers': {'content-type': 'application/json'}, 'body': body}, expired=False)
            error = harness.refresh()
            self.assertTrue(error.discord_permanent, status)
            self.assertEqual(harness.record['status'], 'reconnect_required', status)
            self.assertTrue(harness.card['revoked'], status)
            self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['revoked'], status)

    def test_an_edge_page_on_the_refresh_request_never_reached_discord_so_the_token_is_unspent(self):
        harness = self.harness(('POST', '/oauth2/token'), EDGE_PAGE, expired=True)
        error = harness.refresh()
        self.assertEqual((error.status, error.code), (503, 'service_unavailable'))
        self.assert_untouched(harness, 'refresh')
        self.assertNotIn('refreshClaim', harness.record)
        # and the very next attempt really tries again (it is not refused as "pending")
        harness.wire.route_overrides.clear()
        renewed = harness.s._fresh_identity(WORKSPACE, 'session', 'identity')
        self.assertTrue(renewed['bearer'].startswith('synthetic-access-'))
        self.assertEqual(len([c for c in harness.wire.lifecycle_calls if c == ('POST', '/oauth2/token')]), 2)
        self.assertEqual(harness.record['status'], 'linked')

    def test_a_server_error_or_a_lost_connection_on_the_refresh_request_is_ambiguous_so_closed_but_not_destroyed(self):
        for label, answer in (('502 html', {**EDGE_PAGE, 'status': 502}), ('500', {'status': 500, 'body': {'message': 'oops', 'code': 0}})):
            harness = self.harness(('POST', '/oauth2/token'), answer, expired=True)
            error = harness.refresh()
            self.assertEqual(error.code, 'discord_connection_required', label)
            self.assertEqual(harness.record['status'], 'reconnect_required', label)
            self.assertFalse(harness.card['revoked'], label)
            self.assertTrue(harness.card['discordSuspended'], label)
        harness = Harness(None, expired=True)
        harness.s._response = DiscordConnections._response.__get__(harness.s)
        harness.s.adapter.transport = Mock(side_effect=AlphaError('The provider is temporarily unreachable.', 503))
        harness.refresh()
        self.assertEqual(harness.record['status'], 'reconnect_required')
        self.assertFalse(harness.card['revoked'])

    def test_the_server_cannot_be_used_while_its_identity_is_suspended(self):
        harness = self.harness(('POST', '/oauth2/token'), {**EDGE_PAGE, 'status': 502}, expired=True)
        harness.refresh()
        harness.s.bind_identity = DiscordConnections.bind_identity.__get__(harness.s)
        harness.s.read_credential = Mock()
        with self.assertRaises(AlphaError) as raised:
            harness.s._fresh_identity(WORKSPACE, 'session', 'identity')
        self.assertEqual(raised.exception.code, 'discord_connection_required')
        harness.s.read_credential.assert_not_called()


class RateCoordinatedReadsClassifyTheSameWay(unittest.TestCase):
    """The reads inside DiscordProvider._discord_http (rate coordinator on, as in production)."""

    def provider(self, answer):
        ledger = MemoryLedger()
        provider = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.example.invalid',
                                   transport=lambda *a, **k: json.loads(json.dumps(answer)))
        provider.rate_v1_enabled = True
        provider.rate_limiter = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy())
        return provider

    def test_discords_json_denial_is_permanent_and_nothing_else_is(self):
        for status in (401, 403, 404):
            with self.assertRaises(AlphaError) as raised:
                self.provider({'status': status, 'headers': {}, 'body': {'message': 'denied', 'code': 50001}})._bot('GET', '/guilds/9000000')
            self.assertEqual((raised.exception.code, raised.exception.discord_permanent), ('discord_connection_required', True), status)
            with self.assertRaises(AlphaError) as raised:
                self.provider({**EDGE_PAGE, 'status': status})._bot('GET', '/guilds/9000000')
            self.assertEqual((raised.exception.status, raised.exception.discord_permanent), (503, False), status)
            self.assertNotEqual(raised.exception.code, 'discord_connection_required')
            with self.assertRaises(AlphaError) as raised:
                self.provider({'status': status, 'headers': {}, 'body': {}})._bot('GET', '/guilds/9000000')
            self.assertFalse(raised.exception.discord_permanent, status)

    def test_the_shape_test_itself(self):
        denial = DiscordProvider.is_discord_denial
        self.assertTrue(denial({'status': 401, 'body': {'message': '401: Unauthorized', 'code': 0}}))
        self.assertTrue(denial({'status': 403, 'headers': {'content-type': 'application/json'}, 'body': {'message': 'Missing Access', 'code': 50001}}))
        self.assertTrue(denial({'status': 400, 'body': {'error': 'invalid_grant'}}))
        for answer in ({'status': 403, 'body': {'raw': '<html>'}}, {'status': 403, 'body': {}}, {'status': 403, 'body': []},
                       {'status': 403, 'body': {'message': 'x', 'code': True}}, {'status': 403, 'body': {'message': 'x', 'code': '5'}},
                       {'status': 403, 'headers': {'content-type': 'text/html'}, 'body': {'message': 'x', 'code': 1}},
                       {'status': 500, 'body': {'message': 'x', 'code': 0}}, {'status': 429, 'body': {'message': 'x', 'code': 0}},
                       {'status': 401, 'body': {'error': 'invalid_client'}}, {'status': 403, 'body': {'error': 'invalid_grant'}},
                       {'status': None, 'body': {'message': 'x', 'code': 0}}, {'status': 403}):
            self.assertFalse(denial(answer), answer)


def suspended_world(*, user=USER, status='reconnect_required', suspended=True):
    s, wire = service()
    connection = stable_id('identity', WORKSPACE, APP, USER, ACTOR)
    record = {'id': connection, 'workspaceId': WORKSPACE, 'applicationId': APP, 'userId': USER, 'authorizedBy': ACTOR,
              'authorizationGeneration': 'old-generation', 'status': status, **({'dependentsSuspended': True} if suspended else {})}
    card = {'id': 'conn-1', 'platform': 'Discord', 'providerAccountId': GUILD, 'discordIdentityConnectionId': connection,
            'revoked': not suspended, 'capabilityVerified': False, 'discordAuthorizationGeneration': 'install-generation',
            'discordDestinations': [{'status': 'authorized' if suspended else 'revoked'}],
            **({'discordSuspended': True} if suspended else {})}
    state = initial_state(WORKSPACE)
    state['phase2'] = {'discordIdentityLinks': [record], 'channels': [card]}
    cur = Mock(rowcount=1)
    cur.fetchone.return_value = ('fresh-generation',)

    @contextmanager
    def local(*_):
        yield cur, state, ACTOR
    s.local = local
    s.save_state = Mock()
    s.invalidate_dependents = Mock(wraps=s.invalidate_dependents)
    return s, cur, state, record, card, connection


class ResumeAfterSuspension(unittest.TestCase):
    """A suspended identity's servers come back when the SAME Discord user links the SAME identity again."""

    def relink(self, world, discord_user=USER):
        s, cur, state, record, card, connection = world
        context = {'memberId': ACTOR, 'identityGenerations': {connection: record['authorizationGeneration']}}
        body = {'access_token': 'synthetic-new', 'refresh_token': 'synthetic-new-refresh', 'expires_in': 3600}
        return s.save_identity(WORKSPACE, 'session', context, body, {'id': discord_user, 'username': 'Synthetic'}, ['identify', 'guilds'])

    def test_the_same_user_linking_again_restores_the_servers_without_reinstalling_them(self):
        world = suspended_world()
        s, cur, state, record, card, connection = world
        self.relink(world)
        self.assertEqual(record['status'], 'linked')
        self.assertEqual(record['authorizationGeneration'], 'old-generation')  # the installations name this generation
        self.assertNotIn('dependentsSuspended', record)
        s.invalidate_dependents.assert_not_called()
        self.assertFalse(card['revoked'])
        self.assertNotIn('discordSuspended', card)
        self.assertEqual([d['status'] for d in card['discordDestinations']], ['authorized'])
        # approvals are not restored by a relink: the card still needs an explicit verification
        self.assertFalse(card['capabilityVerified'])
        restore = [c for c in cur.execute.call_args_list if c.args[0].startswith('UPDATE public.pr_encrypted_credentials SET authorization_generation')]
        self.assertEqual([c.args[1] for c in restore], [('old-generation', WORKSPACE, connection)])

    def test_a_relink_after_discord_itself_refused_the_grant_still_fences_every_dependent(self):
        world = suspended_world(suspended=False)
        s, cur, state, record, card, connection = world
        self.relink(world)
        s.invalidate_dependents.assert_called_once()
        self.assertTrue(card['revoked'])
        self.assertNotEqual(record['authorizationGeneration'], 'old-generation')
        self.assertFalse(any(c.args[0].startswith('UPDATE public.pr_encrypted_credentials SET authorization_generation') and c.args[1][0] == 'old-generation'
                             for c in cur.execute.call_args_list))


class ARefreshClaimHasNoImmortalOwner(unittest.TestCase):
    """G2E-A-04 (P8). A crashed or killed refresh left a claim that nothing ever released: the identity and every server
    bound to it were refused as "pending" until a relink, which destroys them."""

    def claimed(self, age):
        harness = Harness(None, expired=False)
        harness.record.update(refreshClaim='dead-worker', refreshStartedAt=NOW - age)
        return harness

    def test_a_live_claim_is_still_respected(self):
        harness = self.claimed(age=REFRESH_CLAIM_TTL - 1)
        error = harness.refresh()
        self.assertIn('pending', str(error))
        self.assertEqual(harness.record['status'], 'linked')
        self.assertEqual(harness.record['refreshClaim'], 'dead-worker')
        self.assertEqual(harness.wire.lifecycle_calls, [])

    def test_a_claim_older_than_the_function_limit_becomes_a_visible_reconnect_without_destroying_anything(self):
        for age in (REFRESH_CLAIM_TTL + 1, 30 * 86400):
            harness = self.claimed(age=age)
            error = harness.refresh()
            self.assertEqual(error.code, 'discord_connection_required')
            self.assertEqual(harness.record['status'], 'reconnect_required')
            self.assertTrue(harness.record['dependentsSuspended'])
            self.assertNotIn('refreshClaim', harness.record)
            self.assertFalse(harness.card['revoked'])
            self.assertTrue(harness.card['discordSuspended'])
            self.assertEqual([d['status'] for d in harness.card['discordDestinations']], ['authorized'])
            self.assertEqual(harness.wire.lifecycle_calls, [])  # not a single Discord request
            harness.s.save_state.assert_called_once()

    def test_a_claim_without_a_start_time_is_treated_as_dead_not_as_immortal(self):
        for started in (None, 'yesterday', True):
            harness = Harness(None, expired=False)
            harness.record.update(refreshClaim='dead-worker', refreshStartedAt=started)
            self.assertEqual(harness.refresh().code, 'discord_connection_required')
            self.assertEqual(harness.record['status'], 'reconnect_required')


class ASpentTokenIsNotLostToATransientDatabaseError(unittest.TestCase):
    """G2E-A-04 (P9). A database error while settling a successful rotating refresh left status 'linked', the claim in
    place and the new token pair lost: a silent dead end."""

    def harness(self, failing_calls):
        harness = Harness([{'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 604800, 'scope': 'identify guilds'}])
        harness.s.token_body = Mock(side_effect=lambda body: body)
        harness.s.verified_user = Mock(return_value=({'id': USER}, ['identify', 'guilds']))
        calls = {'n': 0}
        original = harness.s.local

        @contextmanager
        def local(*args):
            calls['n'] += 1
            if calls['n'] in failing_calls:
                raise RuntimeError('canceling statement due to lock timeout')
            with original(*args) as value:
                yield value
        harness.s.local = local
        patcher = patch('postriff_phase2.discord.oauth.time.sleep'); patcher.start(); self.addCleanup(patcher.stop)
        return harness

    def test_one_transient_failure_is_retried_and_the_new_token_is_saved(self):
        harness = self.harness({2})  # call 1 = the claim, call 2 = the first settle
        result = harness.s._fresh_identity(WORKSPACE, 'session', 'identity')
        self.assertEqual(result['bearer'], 'new')
        self.assertEqual(harness.record['status'], 'linked')
        self.assertNotIn('refreshClaim', harness.record)
        self.assertTrue(any(c.args[0].startswith('UPDATE public.pr_encrypted_credentials SET access_ciphertext') for c in harness.cur.execute.call_args_list))

    def test_a_persistent_failure_is_made_visible_and_suspends_instead_of_leaving_a_silent_claim(self):
        harness = self.harness(set(range(2, 2 + SETTLE_ATTEMPTS)))  # every settle attempt fails, the marker then succeeds
        error = harness.refresh()
        self.assertEqual(error.code, 'discord_connection_required')
        self.assertEqual(harness.record['status'], 'reconnect_required')
        self.assertNotIn('refreshClaim', harness.record)
        self.assertFalse(harness.card['revoked'])
        self.assertTrue(harness.card['discordSuspended'])

    def test_a_conflict_is_not_retried(self):
        harness = self.harness(set())
        entered = {'n': 0}
        original = harness.s.local

        @contextmanager
        def local(*args):
            entered['n'] += 1
            if entered['n'] == 2:
                harness.record['refreshClaim'] = 'someone-else'  # the claim changed hands while the exchange was in flight
            with original(*args) as value:
                yield value
        harness.s.local = local
        with self.assertRaises(AlphaError) as raised:
            harness.s._fresh_identity(WORKSPACE, 'session', 'identity')
        self.assertIn('changed while refreshing', str(raised.exception))
        self.assertEqual(entered['n'], 2)  # the claim and ONE settle attempt: a conflict is not a database fault


if __name__ == '__main__':
    unittest.main()
