"""How Rafii classifies Discord rate-limit and ban responses (synthetic; no network).

The shared bot serves every customer, so one IP-level restriction stops everyone. These tests pin the properties that
keep a ban short: it counts against the invalid-request budget, a response without a usable hint never grants capacity,
shared-scope limits are not blamed on Rafii, and a held route sends nothing until an operator or the hint releases it.
"""
import unittest

from postriff_phase2.discord.rate_limits import (
    Permit, RateCoordinatorUnavailable, RateDelayed, RequestIdentity, SharedPostgresBudget, classify_response,
    retry_hint)
from test_discord_rate_limits import A, APP, B, MemoryLedger, synthetic_policy

CLOUDFLARE_1015 = {
    'status': 429,
    'headers': {'content-type': 'text/html; charset=UTF-8', 'server': 'cloudflare'},
    'body': {'raw': '<!DOCTYPE html><title>Access denied | discord.com used Cloudflare to restrict access</title> Error 1015'},
}


class ClassifyBanAndScopes(unittest.TestCase):
    def test_cloudflare_html_429_counts_as_an_invalid_request_and_is_not_global(self):
        verdict = classify_response(CLOUDFLARE_1015)
        self.assertEqual(verdict['status'], 429)
        self.assertTrue(verdict['invalid'])
        self.assertFalse(verdict['global'])
        self.assertEqual(verdict['scope'], 'unknown')

    def test_global_scope_is_recognised_by_header_flag_or_body(self):
        by_scope = classify_response({'status': 429, 'headers': {'X-RateLimit-Scope': 'global'}, 'body': {}})
        by_flag = classify_response({'status': 429, 'headers': {'X-RateLimit-Global': 'true'}, 'body': {}})
        by_body = classify_response({'status': 429, 'headers': {}, 'body': {'global': True, 'retry_after': 1}})
        for verdict in (by_scope, by_flag, by_body):
            self.assertTrue(verdict['global'])
            self.assertEqual(verdict['scope'], 'global')
            self.assertTrue(verdict['invalid'])

    def test_conflicting_evidence_takes_the_stricter_global_accounting(self):
        verdict = classify_response({'status': 429, 'headers': {'X-RateLimit-Scope': 'shared', 'X-RateLimit-Global': 'true'}, 'body': {}})
        self.assertEqual((verdict['scope'], verdict['global']), ('global', True))

    def test_shared_scope_limits_are_not_charged_to_rafii(self):
        verdict = classify_response({'status': 429, 'headers': {'X-RateLimit-Scope': 'shared'}, 'body': {}})
        self.assertFalse(verdict['invalid'])
        self.assertFalse(verdict['global'])

    def test_user_scope_limits_count_as_invalid_but_not_global(self):
        verdict = classify_response({'status': 429, 'headers': {'X-RateLimit-Scope': 'user'}, 'body': {}})
        self.assertTrue(verdict['invalid'])
        self.assertFalse(verdict['global'])
        self.assertEqual(verdict['scope'], 'user')

    def test_401_and_403_are_invalid_and_permanent(self):
        for status in (401, 403):
            verdict = classify_response({'status': status, 'headers': {}, 'body': {}})
            self.assertTrue(verdict['invalid'], status)
            self.assertTrue(verdict['permanent'], status)

    def test_a_404_is_invalid_only_for_a_webhook_credential(self):
        self.assertFalse(classify_response({'status': 404, 'headers': {}, 'body': {}}, 'bot')['invalid'])
        self.assertTrue(classify_response({'status': 404, 'headers': {}, 'body': {}}, 'webhook')['invalid'])

    def test_a_missing_status_is_a_failure_not_a_success(self):
        self.assertEqual(classify_response({'headers': {}, 'body': {}})['status'], 503)
        self.assertEqual(classify_response(None)['status'], 503)


class RetryHints(unittest.TestCase):
    def test_a_ban_page_has_no_usable_hint_so_it_never_grants_capacity(self):
        delay, malformed = retry_hint(CLOUDFLARE_1015, 1000.0)
        self.assertTrue(malformed)

    def test_garbage_hints_are_malformed(self):
        for hint in ('soon', '-5', 'nan', 'inf', '1e999'):
            _, malformed = retry_hint({'status': 429, 'headers': {'Retry-After': hint}, 'body': {}}, 1000.0)
            self.assertTrue(malformed, hint)

    def test_a_good_hint_is_honoured_and_the_larger_of_header_and_body_wins(self):
        self.assertEqual(retry_hint({'status': 429, 'headers': {'Retry-After': '2'}, 'body': {'retry_after': 5.5}}, 1000.0), (5.5, False))


class HeldRoutesSendNothing(unittest.TestCase):
    """After a ban-style 429 the route is refused before any HTTP request is built."""

    def setUp(self):
        self.db = MemoryLedger()
        self.limiter = SharedPostgresBudget(self.db.connection, APP, policy=synthetic_policy())
        self.identity = RequestIdentity.make(APP, 'bot', 'synthetic-ban-bot')
        self.path = '/channels/' + A + '/messages/' + B

    def send(self, response):
        permit = self.limiter.reserve('GET', self.path, identity=self.identity)
        self.limiter.consume(permit, 'GET', self.path)
        self.limiter.observe(permit, response)
        return permit

    def reserve(self):
        return self.limiter.reserve('GET', self.path, identity=self.identity)

    def test_a_ban_page_holds_the_route_for_operator_review(self):
        self.send(CLOUDFLARE_1015)
        for _ in range(3):
            with self.assertRaises(RateCoordinatorUnavailable):
                self.reserve()

    def test_the_ban_hold_does_not_lapse_with_time(self):
        self.send(CLOUDFLARE_1015)
        self.db.now += 600  # still inside the reviewed policy window
        with self.assertRaises(RateCoordinatorUnavailable):
            self.reserve()

    def test_a_well_formed_429_delays_and_then_releases_the_route(self):
        self.send({'status': 429, 'headers': {'Retry-After': '2'}, 'body': {'retry_after': 2}})
        with self.assertRaises(RateDelayed) as held:
            self.reserve()
        self.assertGreater(held.exception.retry_after_seconds, 0)
        self.db.now += 2.1
        self.assertIsInstance(self.reserve(), Permit)


if __name__ == '__main__':
    unittest.main()
