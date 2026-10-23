"""What the nickname route relies on from the shared request coordinator (`SharedPostgresBudget`, not modified by this branch):
`abandon_unsent_nickname` and `reconcile_nickname`, over the repository's in-memory ledger that runs the production algorithm.

The route's own tests use a scriptable stand-in (discord_sender_name_fixture.FakeLimiter) and a real PostgreSQL (the ClaimFlow
class in test_discord_sender_name_postgres.py); these pin the coordinator contract the stand-in imitates, so a change on the
rate limiter's side that breaks the route fails here first. See docs/sender-name/REQUESTS-TO-RATE-LIMITER.md.
"""
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, SharedPostgresBudget
from test_discord_rate_limits import MemoryLedger, synthetic_policy
from test_discord_sender_name import SettingsHarness, GUILD, APP, NOW


class NicknameAdmissions(unittest.TestCase):
    def setUp(self):
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


if __name__ == '__main__':
    unittest.main()
