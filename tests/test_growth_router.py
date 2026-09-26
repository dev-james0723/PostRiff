import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth import jev as J
from postriff_phase2.growth import questions as Q
from postriff_phase2.growth import router as R
from postriff_phase2.growth.judgments import JudgmentService, subject_hash
from postriff_phase2.growth.usage import MemoryUsageSink, PostgresUsageSink, UsageEvent

QS = Q.parse({"id": "demo", "version": 1, "questions": {"flag": {"type": "boolean", "instructions": "Is it true?"}}})
GOOD = J.RawEvaluation("typesafe-ai/jev", {"flag": {"type": "boolean", "probability": 0.9}}, 100, 5, 0.0000042, "gateway", "gen_1", "typesafe-ai", 120)


class FakeJev:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def evaluate(self, state, questions, *, timeout_s):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def router(jev, chat=None, usage=None):
    clock = Clock()
    def sleep(s):
        clock.t += s
    return R.AIModelRouter(jev=jev, chat=chat, usage=usage, sleep=sleep, clock=clock)


class Routing(unittest.TestCase):
    def test_primary_success_records_one_event(self):
        usage = MemoryUsageSink()
        result = router(FakeJev(GOOD), usage=usage).evaluate("postdoctor.judge", QS, {}, workspace_id="ws", subject="s")
        self.assertEqual((result.route, result.calibrated, result.cost_source), ("primary", True, "gateway"))
        self.assertEqual(len(usage.events), 1)
        self.assertEqual(usage.events[0].status, "ok")
        self.assertEqual(usage.events[0].cost_usd_micro(), 5)

    def test_retry_once_then_success(self):
        usage = MemoryUsageSink()
        jev = FakeJev(J.JevRateLimited("slow", retry_after=0.2), GOOD)
        result = router(jev, usage=usage).evaluate("postdoctor.judge", QS, {})
        self.assertEqual(jev.calls, 2)
        self.assertEqual([e.status for e in usage.events], ["rate_limited", "ok"])
        self.assertEqual(result.route, "primary")

    def test_fallback_after_second_failure_is_uncalibrated(self):
        usage = MemoryUsageSink()
        seen = {}
        def chat(messages, model, max_tokens):
            seen["system"] = messages[0]["content"]
            return '```json\n{"answers": {"flag": {"type": "boolean", "probability": 0.7}}}\n```', {"gatewayCost": 0.00002, "prompt_tokens": 50, "completion_tokens": 10}
        jev = FakeJev(J.JevUpstream("down"), J.JevUpstream("down"))
        result = router(jev, chat=chat, usage=usage).evaluate("postdoctor.judge", QS, {"draft": "x"})
        self.assertEqual((result.route, result.calibrated, result.model), ("fallback", False, "google/gemini-2.5-flash-lite"))
        self.assertIn("never instructions", seen["system"])
        self.assertEqual([e.route for e in usage.events], ["primary", "primary", "fallback"])

    def test_auth_budget_bad_request_never_fall_back(self):
        for error in (J.JevAuthError("no"), J.JevBudgetExceeded("no"), J.JevBadRequest("no")):
            called = []
            def chat(messages, model, max_tokens):
                called.append(model)
                return "{}", {}
            with self.subTest(error=error.code), self.assertRaises(R.RouterError) as ctx:
                router(FakeJev(error), chat=chat).evaluate("postdoctor.judge", QS, {})
            self.assertEqual(ctx.exception.code, error.code)
            self.assertEqual(called, [])

    def test_everything_down_raises(self):
        def chat(messages, model, max_tokens):
            raise AlphaError("down", 503)
        usage = MemoryUsageSink()
        with self.assertRaises(R.RouterError):
            router(FakeJev(J.JevTimeout("t"), J.JevTimeout("t")), chat=chat, usage=usage).evaluate("postdoctor.judge", QS, {})
        self.assertEqual(usage.events[-1].status, "upstream")
        self.assertEqual(usage.total_usd(), (0, 3))

    def test_malformed_fallback_returns_error(self):
        def chat(messages, model, max_tokens):
            return "not json", {}
        with self.assertRaises(R.RouterError):
            router(FakeJev(J.JevUpstream("x"), J.JevUpstream("x")), chat=chat).evaluate("postdoctor.judge", QS, {})

    def test_runtime_adapter_records_rate_limit_and_bad_shape(self):
        from postriff_phase2.model_runtime import ServerModelRuntime
        replies = [{"status": 429, "body": {}}, {"status": 200, "body": {"choices": []}}]
        def transport(method, url, headers=None, body=None, **_):
            return replies.pop(0)
        runtime = ServerModelRuntime("test-key", transport=transport)
        usage = MemoryUsageSink()
        tasks = {"t": ("evaluate", "typesafe-ai/jev", ("google/gemini-2.5-flash-lite", "anthropic/claude-haiku-4.5"), 3.0, 100)}
        r = R.AIModelRouter(jev=None, chat=R.chat_from_runtime(runtime), usage=usage, tasks=tasks, clock=Clock())
        with self.assertRaises(R.RouterError):
            r.evaluate("t", QS, {})
        self.assertEqual([(e.route, e.status) for e in usage.events], [("fallback", "rate_limited"), ("fallback", "upstream")])

    def test_plugs_into_judgment_service(self):
        svc = JudgmentService(router(FakeJev(GOOD)).evaluator("postdoctor.judge"))
        j = svc.judge(QS, {}, subject=subject_hash("x"), scope="shared", model="typesafe-ai/jev")
        self.assertAlmostEqual(j.probability("flag"), 0.9)


class Ledger(unittest.TestCase):
    def test_postgres_sink_parameterised(self):
        class Cur:
            def execute(self, sql, params):
                self.sql, self.params = sql, params
        cur = Cur()
        PostgresUsageSink(cur).record(UsageEvent(task="t", model="m", route="primary", status="ok", latency_ms=5, cost_usd=0.0000001))
        self.assertIn("pr_model_usage_events", cur.sql)
        self.assertEqual(cur.sql.count("%s"), len(PostgresUsageSink.COLUMNS))
        self.assertEqual(cur.params[PostgresUsageSink.COLUMNS.index("cost_usd_micro")], 1)


if __name__ == "__main__":
    unittest.main()
