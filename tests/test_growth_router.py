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
    def __init__(self, *outcomes, clock=None, spend=0.0):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.clock, self.spend, self.timeouts = clock, spend, []

    def evaluate(self, state, questions, *, timeout_s):
        self.calls += 1
        self.timeouts.append(timeout_s)
        if self.clock is not None:
            self.clock.t += self.spend
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def router(jev, chat=None, usage=None, clock=None):
    clock = clock or Clock()
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
        def chat(messages, model, max_tokens, timeout_s=None):
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
            def chat(messages, model, max_tokens, timeout_s=None):
                called.append(model)
                return "{}", {}
            with self.subTest(error=error.code), self.assertRaises(R.RouterError) as ctx:
                router(FakeJev(error), chat=chat).evaluate("postdoctor.judge", QS, {})
            self.assertEqual(ctx.exception.code, error.code)
            self.assertEqual(called, [])

    def test_everything_down_raises(self):
        def chat(messages, model, max_tokens, timeout_s=None):
            raise AlphaError("down", 503)
        usage = MemoryUsageSink()
        with self.assertRaises(R.RouterError):
            router(FakeJev(J.JevTimeout("t"), J.JevTimeout("t")), chat=chat, usage=usage).evaluate("postdoctor.judge", QS, {})
        self.assertEqual(usage.events[-1].status, "upstream")
        self.assertEqual(usage.total_usd(), (0, 3))

    def test_malformed_fallback_returns_error(self):
        def chat(messages, model, max_tokens, timeout_s=None):
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


class Deadline(unittest.TestCase):
    """The task budget (postdoctor.judge: 3 s) is one deadline over attempts, retry pause and fallbacks."""

    def test_no_fallback_starts_after_expiry_and_ledger_is_returned(self):
        clock, usage, called = Clock(), MemoryUsageSink(), []
        def chat(messages, model, max_tokens, timeout_s=None):
            called.append(model)
            return "{}", {}
        jev = FakeJev(J.JevTimeout("slow"), clock=clock, spend=3.0)
        with self.assertRaises(R.RouterTimeout) as ctx:
            router(jev, chat=chat, usage=usage, clock=clock).evaluate("postdoctor.judge", QS, {})
        self.assertEqual(called, [])
        self.assertEqual(jev.calls, 1)  # no retry either: nothing left of the budget
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertEqual([e.status for e in ctx.exception.attempts], ["timeout"])
        self.assertEqual(list(ctx.exception.attempts), usage.events)

    def test_each_adapter_gets_only_remaining_time(self):
        clock, seen = Clock(), []
        def chat(messages, model, max_tokens, timeout_s=None):
            seen.append(timeout_s)
            return '{"answers": {"flag": {"type": "boolean", "probability": 0.8}}}', {}
        jev = FakeJev(J.JevUpstream("x"), J.JevUpstream("x"), clock=clock, spend=0.5)
        result = router(jev, chat=chat, clock=clock).evaluate("postdoctor.judge", QS, {})
        self.assertEqual(jev.timeouts, [3.0, 2.0])  # 0.5 spent + 0.5 pause
        self.assertEqual(seen, [1.5])
        self.assertEqual((result.route, result.late, len(result.attempts)), ("fallback", False, 3))

    def test_answer_after_deadline_is_kept_but_marked_late(self):
        clock = Clock()
        def chat(messages, model, max_tokens, timeout_s=None):
            clock.t += 10  # a transport that cannot enforce the timeout
            return '{"answers": {"flag": {"type": "boolean", "probability": 0.8}}}', {}
        result = router(None, chat=chat, clock=clock).evaluate("postdoctor.judge", QS, {})
        self.assertTrue(result.late)

    def test_judgment_service_abstains_on_timeout_and_does_not_cache(self):
        clock = Clock()
        svc = JudgmentService(router(FakeJev(J.JevTimeout("t"), clock=clock, spend=5), clock=clock).evaluator("postdoctor.judge"))
        j = svc.judge(QS, {}, subject=subject_hash("x"), scope="shared", model="typesafe-ai/jev")
        self.assertEqual((j.status, j.answers, j.route, j.calibrated), ("timeout", {}, "none", False))
        self.assertEqual(len(j.attempts), 1)
        self.assertIsNone(j.probability("flag"))
        self.assertEqual(svc.cache.items, {})

    def test_judgment_service_still_raises_on_auth(self):
        svc = JudgmentService(router(FakeJev(J.JevAuthError("no"))).evaluator("postdoctor.judge"))
        with self.assertRaises(R.RouterError):
            svc.judge(QS, {}, subject=subject_hash("x"), scope="shared", model="typesafe-ai/jev")

    def test_runtime_adapter_forwards_timeout_only_when_transport_accepts_it(self):
        from postriff_phase2.model_runtime import ServerModelRuntime
        ok = {"status": 200, "body": {"choices": [{"message": {"content": "{}"}}]}}
        seen = []
        def with_timeout(method, url, headers=None, body=None, timeout=None):
            seen.append(timeout)
            return ok
        def without_timeout(method, url, headers=None, body=None):
            return ok
        chat = R.chat_from_runtime(ServerModelRuntime("k", transport=with_timeout))
        chat([{"role": "user", "content": "x"}], "google/gemini-2.5-flash-lite", 10, 1.25)
        self.assertEqual((seen, chat.enforces_timeout), ([1.25], True))
        chat = R.chat_from_runtime(ServerModelRuntime("k", transport=without_timeout))
        chat([{"role": "user", "content": "x"}], "google/gemini-2.5-flash-lite", 10, 1.25)
        self.assertFalse(chat.enforces_timeout)


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
