"""What a refusal from Discord closes, and for how long (the coordinator's route circuits).

Before: ANY 403 or 404 on a route set that route's circuit to the end of the reviewed policy (up to 31 days) and nothing
cleared it. One 404 on a read of a deleted message blocked every read of every message of that channel; one 403 on a create
blocked the channel; the bot removed from a server and added again was refused for a month with no request reaching Discord,
and the customer saw "waiting for shared request capacity".

Now: a 404 on a read opens no circuit (it answers about one object and Discord does not count it as an invalid request); a
403 (and a 404 on a webhook, which Discord counts as invalid) opens the route's circuit for circuit_seconds, doubling with
each consecutive refusal up to 16 minutes at the reviewed 30 s, and an answer ends the doubling. 401, 429 and 5xx are
unchanged: a 401 holds the credential, a 429 embargoes the scope it names, three 5xx or transport failures open the 30 s circuit.

Storage is the shared MemoryLedger double (fake database clock). The real-PostgreSQL case is in
test_discord_rate_ceiling_postgres.py.
"""
import unittest

from postriff_phase2.discord.rate_limits import Permit, RateDelayed, RequestIdentity, SharedPostgresBudget
from test_discord_rate_limits import A, APP, B, MemoryLedger, synthetic_policy

T0 = 1000
CIRCUIT = synthetic_policy()['circuit_seconds']      # 30
FAILURES = synthetic_policy()['failure_threshold']   # consecutive server errors that open the plain circuit
THIRD = '555555555555555555'
MESSAGE = '/channels/%s/messages/%s'


class Circuits(unittest.TestCase):
    def setUp(self):
        self.db = MemoryLedger(now=T0)
        # the invalid-request budget is not what is tested, and the policy must outlast the longest circuit chain below
        self.policy = {**synthetic_policy(), 'invalid_capacity': 100000, 'expires_at': T0 + 86400}
        self.s = SharedPostgresBudget(self.db.connection, APP, policy=self.policy)
        self.bot = RequestIdentity.make(APP, 'bot', 'circuit-bot')

    def answer(self, status, method='GET', path=None, identity=None, headers=None):
        """One request admitted and answered with `status`; the scope key of its route row is returned with it."""
        path = path or MESSAGE % (A, B)
        permit = self.s.reserve_read(method, path, identity=identity or self.bot) if method == 'GET' else self.s.reserve(
            method, path, identity=identity or self.bot)
        if method != 'GET':
            self.s.consume(permit, method, path)
        self.s.observe(permit, {'status': status, 'headers': headers or {}})
        return permit

    def routes(self):
        return [row for row in self.db.states.values() if row['kind'] == 'route']

    def circuit_left(self):
        """Seconds of circuit the longest-open route row has left (0 when none is open)."""
        return max([(row['circuit'] or 0) - self.db.now for row in self.routes()] + [0])

    def at(self, offset):
        self.db.now = T0 + offset

    def refused(self, path=None, method='GET'):
        with self.assertRaises(RateDelayed) as caught:
            (self.s.reserve_read if method == 'GET' else self.s.reserve)(method, path or MESSAGE % (A, B), identity=self.bot)
        return caught.exception

    def admitted(self, path=None, method='GET'):
        return (self.s.reserve_read if method == 'GET' else self.s.reserve)(method, path or MESSAGE % (A, B), identity=self.bot)

    # --- 404 -----------------------------------------------------------------------------------------------------

    def test_a_404_on_a_read_opens_no_circuit_and_the_channel_is_read_again_one_probe_window_later(self):
        self.answer(404)                                              # one message was deleted
        self.assertEqual(self.circuit_left(), 0)
        self.assertTrue(all(row['circuit'] is None for row in self.db.states.values()))
        self.at(1.1)                                                  # the cold route's own probe window
        self.assertIsInstance(self.admitted(MESSAGE % (A, THIRD)), Permit)       # another message of the same channel

    def test_a_404_on_a_member_lookup_does_not_block_the_server(self):
        member = '/guilds/%s/members/%s' % (A, B)
        self.answer(404, path=member)                                 # the person who authorized has left
        self.assertEqual(self.circuit_left(), 0)
        self.at(1.1)
        server = self.admitted('/guilds/%s' % A)                                # the server's other reads go on
        self.s.observe(server, {'status': 200, 'headers': {}})
        self.assertIsInstance(self.admitted(member), Permit)

    def test_a_404_does_not_count_as_a_failure_of_the_route(self):
        for _ in range(4):
            self.answer(404)
            self.db.now += 1.1
        self.assertEqual({row['streak'] for row in self.routes()}, {0})
        self.assertEqual(self.circuit_left(), 0)

    # --- 403 -----------------------------------------------------------------------------------------------------

    def test_a_403_opens_a_circuit_of_circuit_seconds_and_the_route_is_probed_again_after_it(self):
        self.answer(403)
        self.assertAlmostEqual(self.circuit_left(), CIRCUIT, places=6)           # not the policy's remaining life
        self.assertLess(self.circuit_left(), 3600)
        self.at(CIRCUIT - 1)
        error = self.refused()
        self.assertEqual(error.rate_scope_kind, 'embargo')
        self.assertAlmostEqual(error.retry_after_seconds, 1, delta=.01)
        self.at(CIRCUIT + 1.1)
        self.assertIsInstance(self.admitted(), Permit)               # probed again; the permission may be back

    def test_consecutive_refusals_double_the_circuit_up_to_sixteen_minutes_and_an_answer_ends_the_doubling(self):
        waits = []
        for _ in range(8):
            self.answer(403)
            waits.append(round(self.circuit_left()))
            self.db.now += self.circuit_left() + 1.1                  # wait the circuit out, then the next probe is refused too
        self.assertEqual(waits, [30, 60, 120, 240, 480, 960, 960, 960])
        self.answer(200)                                              # the permission is back: an answer ends the doubling
        self.assertEqual({row['streak'] for row in self.routes()}, {0})
        self.db.now += 1.1
        self.answer(403)
        self.assertEqual(round(self.circuit_left()), 30)

    def test_a_403_on_a_create_closes_that_channel_for_a_bounded_time_and_no_other(self):
        post = '/channels/%s/messages'
        self.answer(403, method='POST', path=post % A)
        error = self.refused(post % A, 'POST')
        self.assertEqual(error.rate_scope_kind, 'embargo')
        self.assertLessEqual(error.retry_after_seconds, CIRCUIT)
        self.assertIsInstance(self.admitted(post % B, 'POST'), Permit)           # another channel is untouched
        self.at(CIRCUIT + 1.1)
        self.assertIsInstance(self.admitted(post % A, 'POST'), Permit)

    def test_a_bot_removed_from_a_server_and_added_again_is_served_again_after_the_circuit(self):
        channels = '/guilds/%s/channels' % A
        self.answer(403, path=channels)                               # destinations(): the bot is not in the server
        self.assertLessEqual(self.refused(channels).retry_after_seconds, CIRCUIT)
        self.at(CIRCUIT + 1.1)                                        # the customer added the bot again meanwhile
        permit = self.admitted(channels)
        self.s.observe(permit, {'status': 200, 'headers': {}})
        self.at(CIRCUIT + 3)
        self.assertIsInstance(self.admitted(channels), Permit)       # normal service, no circuit left

    def test_a_404_on_a_webhook_is_an_invalid_request_and_opens_the_bounded_circuit_too(self):
        hook = RequestIdentity.make(APP, 'webhook', 'a-webhook-token-with-enough-length')
        path = '/webhooks/%s/%s?wait=true' % (A, 'T' * 40)
        permit = self.s.reserve('POST', path, identity=hook)
        self.s.consume(permit, 'POST', path)
        self.s.observe(permit, {'status': 404, 'headers': {}})
        self.assertAlmostEqual(self.circuit_left(), CIRCUIT, places=6)
        invalid = [row for row in self.db.states.values() if row['kind'] == 'invalid']
        self.assertEqual([row['cap'] - row['left'] for row in invalid], [1])

    # --- what did not change ---------------------------------------------------------------------------------------

    def test_a_401_still_holds_the_credential_and_opens_no_route_circuit(self):
        self.answer(401)
        credential = [row for row in self.db.states.values() if row['kind'] == 'credential']
        self.assertEqual([row['hold'] for row in credential], [True])
        self.assertEqual(self.circuit_left(), 0)

    def test_the_configured_number_of_server_errors_still_open_the_plain_circuit_not_a_doubling_one(self):
        for _ in range(FAILURES):
            self.assertEqual(self.circuit_left(), 0)
            self.answer(503)
            self.db.now += 1.1
        self.assertLessEqual(self.circuit_left(), CIRCUIT)
        self.assertGreater(self.circuit_left(), CIRCUIT - 3)

    def test_a_429_still_embargoes_the_scope_it_names_for_its_retry_after(self):
        self.answer(429, headers={'Retry-After': '7', 'X-RateLimit-Scope': 'user'})
        error = self.refused()
        self.assertEqual(error.rate_scope_kind, 'embargo')
        self.assertAlmostEqual(error.retry_after_seconds, 7, delta=.01)


if __name__ == '__main__':
    unittest.main()
