"""RAFII Product Growth v2 billing fixes (F1) that need no database: agent image tools on credit plans (D-026) and the
Growth router's refusal-before-dispatch contract (no invented unknown attempt)."""
import contextlib
import types
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import creative
from postriff_phase2.growth import router as growth_router
from postriff_phase2.growth.service import GrowthService, RefusedBeforeDispatch
from postriff_phase2.growth.usage import MemoryUsageSink

V2 = "credits-v2-2026-09-28"


class Stop(Exception):
    """Raised by the fake ledger once a reservation is attempted, so the test never reaches a provider."""


def image_ctx(policy, reserved):
    studio = types.SimpleNamespace(route=lambda quality, reason: types.SimpleNamespace(available=True, blocker=None, provider="openai", model="gpt-image-2.5-sunburst"),
                                   estimate=lambda quality: 40_000)

    def reserve(*args, **kwargs):
        reserved.append((args, kwargs))
        raise Stop()

    ledger = types.SimpleNamespace(credits=types.SimpleNamespace(policy=lambda cur, wid: policy), reserve=reserve)

    @contextlib.contextmanager
    def workspace():
        yield object(), None, "00000000-0000-4000-8000-000000000001", types.SimpleNamespace(allows=lambda level: True), {}

    return types.SimpleNamespace(image_studio=studio, config=None, remaining=lambda: None, trace_id="trace-1", workspace=workspace,
                                 service=types.SimpleNamespace(assets=object(), ledger=ledger), workspace_id="w-1", run_id=None)


class AgentImageOnCreditPlansTest(unittest.TestCase):
    def test_credit_plan_image_tools_refuse_before_any_reservation(self):
        for operation, args in (("generate", {"prompt": "A quiet practice room"}), ("variant", {"instruction": "Warmer light", "assetId": "a-1"}),
                                ("edit", {"instruction": "Crop it", "assetId": "a-1"})):
            reserved = []
            with self.subTest(operation=operation), self.assertRaises(AlphaError) as caught:
                creative._generate(image_ctx(V2, reserved), args, operation=operation)
            self.assertEqual((caught.exception.status, caught.exception.code), (402, "image_credits_unavailable"))
            self.assertEqual(str(caught.exception), "Images are not part of plan credits yet. Nothing was made or charged.")
            self.assertEqual(reserved, [], "no reservation, so no unconfirmable 'confirm this task credit limit'")

    def test_legacy_plans_keep_their_image_path(self):
        reserved = []
        with self.assertRaises(Stop):
            creative._generate(image_ctx(None, reserved), {"prompt": "A quiet practice room"}, operation="generate")
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0][0][3], "image_generation")


class RefusedBeforeDispatchTest(unittest.TestCase):
    """A guard refusal is not a provider attempt: nothing is recorded, so nothing is held as an unknown cost."""

    def router(self, calls, sink):
        def chat(messages, model, max_tokens, timeout_s):
            calls.append(model)
            return '{"x": 1}', {"gatewayCost": 0.001}

        def refuse():
            raise AlphaError("The input or AI permission changed. Check the current version.", 409, code="growth_input_changed")
        tasks = {"postdoctor.rewrite": ("chat", "writer/one", ("writer/two",), 30.0, 100)}
        return GrowthService._guard_router(growth_router.AIModelRouter(chat=chat, usage=sink, tasks=tasks), refuse, reconcile_unknown=True)

    def test_chat_refusal_records_no_attempt_and_keeps_the_answer(self):
        calls, sink = [], MemoryUsageSink()
        with self.assertRaises(RefusedBeforeDispatch) as caught:
            self.router(calls, sink).complete_json("postdoctor.rewrite", [{"role": "user", "content": "{}"}], validate=lambda value: value)
        self.assertEqual((calls, sink.events), ([], []))
        self.assertEqual(caught.exception.refusal.code, "growth_input_changed")
        self.assertIsInstance(caught.exception, growth_router.RouterError)

    def test_evaluation_refusal_records_no_attempt(self):
        calls, sink = [], MemoryUsageSink()
        jev = types.SimpleNamespace(evaluate=lambda *a, **k: calls.append("jev"))
        router = growth_router.AIModelRouter(jev=jev, usage=sink, tasks={"postdoctor.judge": ("evaluate", "typesafe-ai/jev", (), 3.0, 100)})

        def refuse():
            raise AlphaError("Permission changed.", 403)
        guarded = GrowthService._guard_router(router, refuse)
        question_set = types.SimpleNamespace(payload_questions=lambda names: {"q": {"type": "boolean"}})
        with self.assertRaises(RefusedBeforeDispatch):
            guarded.evaluate("postdoctor.judge", question_set, {"draft": "text"})
        self.assertEqual((calls, sink.events), ([], []))


if __name__ == "__main__":
    unittest.main()
