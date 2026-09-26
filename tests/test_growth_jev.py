import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth import jev as J

KEY = "vck-test-placeholder-0123456789"
Q = {"flag": {"type": "boolean", "instructions": "Is it true?"}}
OK = {"model": "typesafe-ai/jev", "answers": {"flag": {"type": "boolean", "probability": 0.9}},
      "usage": {"inputTokens": 275, "outputTokens": 20},
      "providerMetadata": {"gateway": {"routing": {"finalProvider": "typesafe-ai"}, "cost": "0.00001155", "generationId": "gen_1"}}}


class Fake:
    def __init__(self, status=200, body=OK, raises=None):
        self.status, self.body_, self.raises, self.calls = status, body, raises, []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout})
        if self.raises:
            raise self.raises
        return {"status": self.status, "body": self.body_}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 0.25
        return self.t


class Evaluate(unittest.TestCase):
    def test_success_parses_cost_and_request_shape(self):
        fake = Fake()
        svc = J.JevService(KEY, transport=fake, clock=Clock())
        result = svc.evaluate({"draft": "hi"}, Q, timeout_s=3)
        call = fake.calls[0]
        self.assertEqual(call["url"], J.EVALUATE_ENDPOINT)
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual(call["body"]["providerOptions"], {"gateway": {"zeroDataRetention": True}})
        self.assertEqual(call["body"]["model"], "typesafe-ai/jev")
        self.assertEqual(call["timeout"], 3)
        self.assertAlmostEqual(result.cost_usd, 0.00001155)
        self.assertEqual((result.cost_source, result.generation_id, result.final_provider), ("gateway", "gen_1", "typesafe-ai"))
        self.assertEqual((result.input_tokens, result.output_tokens, result.latency_ms), (275, 20, 250))

    def test_status_mapping_and_no_key_leak(self):
        cases = [(401, J.JevAuthError), (403, J.JevAuthError), (402, J.JevBudgetExceeded), (429, J.JevRateLimited),
                 (400, J.JevBadRequest), (422, J.JevBadRequest), (500, J.JevUpstream), (503, J.JevUpstream),
                 (200, J.JevMalformed)]
        for status, error in cases:
            body = {"error": KEY} if status != 200 else {"answers": "nope"}
            svc = J.JevService(KEY, transport=Fake(status, body))
            with self.subTest(status=status), self.assertRaises(error) as ctx:
                svc.evaluate({}, Q, timeout_s=1)
            self.assertNotIn(KEY, str(ctx.exception))
        self.assertNotIn(KEY, repr(J.JevService(KEY)))

    def test_network_error_is_upstream(self):
        svc = J.JevService(KEY, transport=Fake(raises=AlphaError("boom", 503)))
        with self.assertRaises(J.JevUpstream):
            svc.evaluate({}, Q, timeout_s=1)
        svc = J.JevService(KEY, transport=Fake(raises=TimeoutError()))
        with self.assertRaises(J.JevTimeout):
            svc.evaluate({}, Q, timeout_s=1)

    def test_rate_limit_retry_after(self):
        svc = J.JevService(KEY, transport=Fake(429, {"retry_after": 2}))
        with self.assertRaises(J.JevRateLimited) as ctx:
            svc.evaluate({}, Q, timeout_s=1)
        self.assertEqual(ctx.exception.retry_after, 2.0)

    def test_unknown_cost_is_unknown_not_zero(self):
        body = {"answers": {}, "usage": {}}
        result = J.JevService(KEY, transport=Fake(200, body)).evaluate({}, Q, timeout_s=1)
        self.assertIsNone(result.cost_usd)
        self.assertEqual(result.cost_source, "unknown")

    def test_size_guard_refuses_before_sending(self):
        fake = Fake()
        svc = J.JevService(KEY, transport=fake)
        with self.assertRaises(J.JevBadRequest):
            svc.evaluate({"text": "琴" * 33_000}, Q, timeout_s=1)
        with self.assertRaises(J.JevBadRequest):
            svc.evaluate({}, {}, timeout_s=1)
        self.assertEqual(fake.calls, [])

    def test_constructor_guards(self):
        with self.assertRaises(ValueError):
            J.JevService("")
        with self.assertRaises(ValueError):
            J.JevService(KEY, endpoint="http://insecure.example")


if __name__ == "__main__":
    unittest.main()
