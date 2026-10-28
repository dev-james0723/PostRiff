"""What the nickname route relies on from the shared request coordinator (`SharedPostgresBudget`, not modified by this branch):
`abandon_unsent_nickname` and `reconcile_nickname`, over the repository's in-memory ledger that runs the production algorithm.

The route's own tests use a scriptable stand-in (discord_sender_name_fixture.FakeLimiter) and a real PostgreSQL (the ClaimFlow
class in test_discord_sender_name_postgres.py); these pin the coordinator contract the stand-in imitates, so a change on the
rate limiter's side that breaks the route fails here first. See docs/sender-name/REQUESTS-TO-RATE-LIMITER.md.
"""
import os
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, SharedPostgresBudget, route_identity
from test_discord_rate_limits import MemoryLedger, synthetic_policy
from test_discord_sender_name import SettingsHarness, GUILD, APP, NOW

NICKNAME_FLAG = 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED'


class NicknameAdmissions(unittest.TestCase):
    def setUp(self):
        # The coordinator may admit the nickname route only while the capability is on (R1, REQUESTS-TO-RATE-LIMITER.md).
        # These tests are about the admissions, so they turn it on themselves and pass with or without R1.
        patcher = patch.dict(os.environ, {NICKNAME_FLAG: 'true'})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.h = SettingsHarness('bot')
        self.ledger = MemoryLedger(now=NOW)
        self.h.s.oauth.clock = lambda: self.ledger.now
        adapter = self.h.s.adapter
        adapter.rate_v1_enabled = True
        self.limiter = SharedPostgresBudget(self.ledger.connection, APP, policy=synthetic_policy(NOW))
        adapter.rate_limiter = self.limiter
        transport = adapter.transport

        def rated(method, url, **kwargs):
            result = transport(method, url, **kwargs)
            result['headers'] = {'X-RateLimit-Bucket': 'synthetic-' + method, 'X-RateLimit-Limit': '100',
                                 'X-RateLimit-Remaining': '90', 'X-RateLimit-Reset-After': '1'}
            return result
        adapter.transport = rated
        self.path = f'/guilds/{GUILD}/members/@me'

    def write(self, *, lose=False, deny_second_guard=False):
        """One nickname PATCH through the real adapter and coordinator; returns the Permit it was admitted under."""
        permits, passes = [], [0]

        def guard():
            passes[0] += 1
            if deny_second_guard and passes[0] == 2:
                raise AlphaError('Synthetic final guard refusal.', 409)
            return True

        def timeout():
            raise TimeoutError('Synthetic lost response')
        if lose:
            self.h.before_patch = timeout
        with patch('postriff_phase2.hosted.audit'):
            try:
                self.h.s.adapter._bot('PATCH', self.path, body={'nick': 'Coordinator Bot'}, write_authorize=guard, write_admitted=permits.append)
            except (AlphaError, TimeoutError):
                pass
        return permits[0]

    def state(self, permit):
        return self.ledger.admissions[permit.id]['state']

    def test_a_lost_response_is_uncertain_and_only_an_aged_exact_reading_retires_it(self):
        permit = self.write(lose=True)
        self.assertEqual(self.state(permit), 'uncertain')
        with self.assertRaises(RateCoordinatorUnavailable):
            self.limiter.reconcile_nickname(self.ledger, permit, GUILD)             # too young: the deadline has not passed
        self.assertEqual(self.state(permit), 'uncertain')
        self.ledger.now += 121
        with self.assertRaises(RateCoordinatorUnavailable):
            self.limiter.reconcile_nickname(self.ledger, permit, '9999999')         # another server's path
        self.assertEqual(self.state(permit), 'uncertain')
        self.limiter.reconcile_nickname(self.ledger, permit, GUILD)
        row = self.ledger.admissions[permit.id]
        self.assertEqual((row['state'], row['status']), ('observed', None), 'no HTTP status is invented for the original write')
        self.limiter.reconcile_nickname(self.ledger, permit, GUILD)                 # settled twice: silent
        self.limiter.abandon_unsent_nickname(permit)                                # a late denied writer: silent
        self.assertEqual(self.state(permit), 'observed')

    def test_only_a_guard_denial_after_admission_blocks_an_admission_and_nothing_else_does(self):
        denied = self.write(deny_second_guard=True)
        self.assertEqual(self.state(denied), 'blocked')
        self.limiter.abandon_unsent_nickname(denied)                                # idempotent
        self.assertEqual(self.state(denied), 'blocked')
        self.ledger.now += 5                                                        # the unknown-route probe window is one second
        lost = self.write(lose=True)
        with self.assertRaises(RateCoordinatorUnavailable):
            self.limiter.abandon_unsent_nickname(lost)                              # it may have been sent: never retired as unsent
        self.assertEqual(self.state(lost), 'uncertain')

    def test_the_route_depends_on_exactly_these_refusals_to_keep_a_claim_pending(self):
        """`SenderNames._resolve_admission` treats RateCoordinatorUnavailable as "not settled yet": a young or foreign reading
        never clears a claim."""
        permit = self.write(lose=True)
        for seconds in (0, 60, 119):
            self.ledger.now = NOW + seconds
            with self.subTest(seconds=seconds), self.assertRaises(RateCoordinatorUnavailable):
                self.limiter.reconcile_nickname(self.ledger, permit, GUILD)


class RouteAdmission(unittest.TestCase):
    """R1: the coordinator admits PATCH:/guilds/{id}/members/@me only while the nickname capability is on, read at call time.

    rate_limits.py does not have R1 yet (it is not part of this branch). Until it does this test is SKIPPED with that
    reason, so it neither fails the suite nor claims something that is not true; the moment R1 merges it starts asserting."""
    PATH = f'/guilds/{GUILD}/members/@me'

    def admitted(self, value):
        """The route template the coordinator admits with the flag set to `value` (None: unset), or None when it refuses."""
        env = {k: v for k, v in os.environ.items() if k != NICKNAME_FLAG}
        if value is not None:
            env[NICKNAME_FLAG] = value
        with patch.dict(os.environ, env, clear=True):
            try:
                return route_identity('PATCH', self.PATH)[0]
            except RateCoordinatorUnavailable:
                return None

    def test_the_nickname_route_is_admitted_only_while_the_capability_is_on(self):
        if self.admitted(None) is not None:
            self.skipTest('R1 is not in rate_limits.py yet (docs/sender-name/REQUESTS-TO-RATE-LIMITER.md): the coordinator still '
                          'admits PATCH:/guilds/{id}/members/@me whatever POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED says')
        for value in (None, 'false', '1', 'True', 'TRUE', ' true', 'true ', ''):
            with self.subTest(flag=value):
                self.assertIsNone(self.admitted(value))
        self.assertEqual(self.admitted('true'), 'PATCH:/guilds/{id}/members/@me')
        # the whole reservation refuses too, and leaves no admission behind
        ledger = MemoryLedger(now=NOW)
        limiter = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy(NOW))
        identity = SettingsHarness('bot').s.adapter._rate_identity('bot')
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != NICKNAME_FLAG}, clear=True):
            with self.assertRaises(RateCoordinatorUnavailable):
                limiter.reserve('PATCH', self.PATH, identity=identity)
        self.assertEqual(ledger.admissions, {})

    def test_reading_the_flag_is_not_part_of_settling_what_already_exists(self):
        """R1 must not strand an admission made while the capability was on: reconciling and abandoning work with it off."""
        with patch.dict(os.environ, {NICKNAME_FLAG: 'true'}):
            h = SettingsHarness('bot')
            ledger = MemoryLedger(now=NOW)
            limiter = SharedPostgresBudget(ledger.connection, APP, policy=synthetic_policy(NOW))
            h.s.adapter.rate_v1_enabled, h.s.adapter.rate_limiter = True, limiter
            transport = h.s.adapter.transport

            def rated(method, url, **kwargs):
                result = transport(method, url, **kwargs)
                result['headers'] = {'X-RateLimit-Bucket': 'synthetic-' + method, 'X-RateLimit-Limit': '100',
                                     'X-RateLimit-Remaining': '90', 'X-RateLimit-Reset-After': '1'}
                return result
            h.s.adapter.transport = rated
            permits = []

            def lose():
                raise TimeoutError('Synthetic lost response')
            h.before_patch = lose
            with patch('postriff_phase2.hosted.audit'):
                try:
                    h.s.adapter._bot('PATCH', self.PATH, body={'nick': 'Flag Bot'}, write_authorize=lambda: True, write_admitted=permits.append)
                except (AlphaError, TimeoutError):
                    pass
        self.assertEqual(len(permits), 1)
        ledger.now += 121
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != NICKNAME_FLAG}, clear=True):
            limiter.reconcile_nickname(ledger, permits[0], GUILD)           # capability off: the existing admission still settles
            limiter.abandon_unsent_nickname(permits[0])
        self.assertEqual(ledger.admissions[permits[0].id]['state'], 'observed')


if __name__ == '__main__':
    unittest.main()
