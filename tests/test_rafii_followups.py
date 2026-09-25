"""Follow-up suggestions after each Rafii answer (E2): two or three chips from the light model, built from the person's
message, the answer and the open work; never a decision; paid from the same turn (its reservation's room, or a small
reservation of its own on a deterministic answer); skipped quietly when the budget refuses or anything fails."""
import json
import unittest
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import config, contracts, followups
from postriff_phase2.agent_runtime_v2 import context as rt_context
from postriff_phase2.agent_runtime_v2.creative import CreativeError
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.permissions import Membership

CFG = config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "test-key", "RAFII_AGENT_V2_ENABLED": "1"})
GATEWAY = config.RuntimeConfig.from_environment({"AI_GATEWAY_API_KEY": "gw-key", "RAFII_AGENT_V2_ENABLED": "1"})


class Light:
    """A fake light-model endpoint (OpenAI Responses or the gateway's chat completions)."""

    def __init__(self, chips=("Draft the Tuesday teaser", "What should the Friday clip show?"), status=200, raise_=None, text=None):
        self.chips, self.status, self.raise_, self.text, self.calls = list(chips), status, raise_, text, []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls.append({"url": url, "body": body, "timeout": timeout})
        if self.raise_:
            raise self.raise_
        text = self.text if self.text is not None else json.dumps({"followUps": self.chips})
        if url.endswith("/responses"):
            return {"status": self.status, "body": {"output_text": text, "usage": {"input_tokens": 400, "output_tokens": 30}}}
        return {"status": self.status, "body": {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 400, "completion_tokens": 30}}}


def suggest(transport, cfg=CFG, **kw):
    return followups.suggest(cfg, transport, message=kw.pop("message", "What should I post this week?"),
                             answer=kw.pop("answer", "A teaser on Tuesday and a behind-the-scenes clip on Friday."), **kw)


class SuggestTest(unittest.TestCase):
    def test_the_light_model_writes_two_or_three_chips_with_thinking_off_and_a_small_cap(self):
        light = Light()
        out = suggest(light, work=["Proposal awaiting the person's decision: schedule Tuesday"], language="en")
        self.assertEqual(out["followUps"], ["Draft the Tuesday teaser", "What should the Friday clip show?"])
        sent = light.calls[0]
        self.assertEqual(sent["url"], "https://api.openai.com/v1/responses")
        self.assertEqual((sent["body"]["model"], sent["body"]["reasoning"], sent["body"]["max_output_tokens"], sent["body"]["store"]),
                         ("gpt-6-luna", {"effort": "none"}, followups.OUTPUT_TOKENS, False))
        data = json.loads(sent["body"]["input"][0]["content"][0]["text"])
        self.assertEqual((data["message"], data["openWork"]), ("What should I post this week?", ["Proposal awaiting the person's decision: schedule Tuesday"]))
        self.assertEqual((out["span"]["agent"], out["span"]["model"], out["span"]["inputTokens"], out["span"]["outputTokens"]), ("follow_ups", "gpt-6-luna", 400, 30))

    def test_the_gateway_route_sends_the_same_request_shape(self):
        light = Light()
        out = suggest(light, cfg=GATEWAY)
        body = light.calls[0]["body"]
        self.assertEqual((light.calls[0]["url"], body["model"], body["reasoning_effort"], body["max_tokens"]),
                         ("https://ai-gateway.vercel.sh/v1/chat/completions", "openai/gpt-6-luna", "none", followups.OUTPUT_TOKENS))
        self.assertEqual(len(out["followUps"]), 2)

    def test_a_chip_is_never_a_decision_a_repeat_a_link_or_long(self):
        chips = ["Yes, apply it", "Cancel that", "the second one", "2", "What should I post this week?", "See https://example.com",
                 "x" * 81, "Draft the Tuesday teaser", "draft the tuesday teaser", "Plan next week's posts", "Rewrite it shorter"]
        self.assertEqual(followups.clean(chips, exclude="What should I post this week?"), ["Draft the Tuesday teaser", "Plan next week's posts", "Rewrite it shorter"])

    def test_no_call_without_room_route_price_or_time(self):
        light = Light()
        self.assertEqual(suggest(light, room_usd_micro=1)["skipped"], "budget")
        self.assertEqual(suggest(light, seconds_left=5)["skipped"], "time")
        self.assertEqual(suggest(light, cfg=config.RuntimeConfig.from_environment({}))["skipped"], "route_unavailable")
        unpriced = config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "k", "RAFII_AGENT_FAST_MODEL": "unpriced-model"})
        self.assertEqual(suggest(light, cfg=unpriced)["skipped"], "route_unavailable")
        self.assertEqual(light.calls, [])

    def test_failures_leave_no_chips_and_book_only_possible_spend(self):
        refused = suggest(Light(status=400))
        self.assertEqual((refused["followUps"], refused["span"]), ([], None))
        unknown = suggest(Light(raise_=CreativeError("timeout", uncertain=True)))
        self.assertEqual(unknown["followUps"], [])
        self.assertTrue(unknown["span"]["estimated"] and unknown["span"]["outputTokens"] == followups.OUTPUT_TOKENS, "a call whose outcome is unknown is booked at its ceiling")
        failed = suggest(Light(raise_=CreativeError("refused", uncertain=False)))
        self.assertEqual((failed["followUps"], failed["span"]), ([], None))
        unreadable = suggest(Light(text="not json"))
        self.assertEqual((unreadable["followUps"], unreadable["span"]["outputTokens"]), ([], 30))
        one = suggest(Light(chips=["Yes, apply it", "Draft the Tuesday teaser"]))
        self.assertEqual(one["followUps"], [], "fewer than two usable suggestions show none")


class FakeLedger:
    def __init__(self, refuse=False):
        self.refuse, self.reserved = refuse, []

    def reserve(self, cur, workspace_id, principal, dimension, estimate, key, **kw):
        if self.refuse:
            raise AlphaError("The daily AI budget is used up.", 402)
        self.reserved.append((dimension, estimate, key, kw.get("model")))
        return {"reservationId": "r-follow"}


class FakeService:
    def __init__(self, refuse=False):
        self.ledger = FakeLedger(refuse)

        @contextmanager
        def transaction(token, workspace_id):
            yield None, ("row",), "owner-1"
        self.repository = type("Repo", (), {"transaction": staticmethod(transaction)})()


def runtime(service=None, model_factory=None):
    rt = AgentRuntimeService(service or FakeService(), CFG, model_factory=model_factory, clock=lambda: 0)
    rt._is_cancelled = lambda *a: False
    return rt


def ctx_for(rt):
    ctx = rt_context.RafiiRunContext(service=rt.service, workspace_id="ws", token="t", principal="owner-1", membership=Membership.from_row("owner"),
                                     conversation_id="conv", trace_id=contracts.new_trace_id(), request_text="What should I post this week?")
    ctx.ledger.spans.append({"span": "generation", "agent": "rafii_manager", "model": "gpt-6-sol", "inputTokens": 10_000, "outputTokens": 1_000})
    return ctx


class ServiceTest(unittest.TestCase):
    def test_after_a_manager_answer_chips_fit_inside_the_turns_reservation(self):
        rt = runtime()
        rt.followup_transport = light = Light()
        ctx = ctx_for(rt)
        spent = rt._spend(ctx.ledger, "gpt-6-sol")
        out = rt._manager_follow_ups(ctx, "run-1", {"reservationId": "r", "estimateUsdMicro": spent + 5_000}, "A teaser on Tuesday.", "en", "gpt-6-sol")
        self.assertEqual(len(out["followUps"]), 2)
        ctx.ledger.spans.append(out["span"])
        self.assertGreater(rt._spend(ctx.ledger, "gpt-6-sol"), spent, "the chips' cost is part of the same turn's spend")
        # No room left in the reservation: no call at all.
        full = rt._manager_follow_ups(ctx_for(rt), "run-2", {"reservationId": "r", "estimateUsdMicro": spent}, "A teaser on Tuesday.", "en", "gpt-6-sol")
        self.assertEqual((full["followUps"], full["skipped"]), ([], "budget"))
        # A live turn without a reservation is never billed for chips it can't account for.
        self.assertEqual(rt._manager_follow_ups(ctx_for(rt), "run-3", None, "A teaser.", "en", "gpt-6-sol")["skipped"], "unmetered")
        self.assertEqual(len(light.calls), 1)

    def test_a_stopped_run_or_a_scripted_run_gets_no_chips(self):
        rt = runtime()
        rt.followup_transport = light = Light()
        rt._is_cancelled = lambda *a: True
        self.assertEqual(rt._manager_follow_ups(ctx_for(rt), "run", {"reservationId": "r", "estimateUsdMicro": 10**9}, "A.", "en", "gpt-6-sol")["skipped"], "cancelled")
        scripted = runtime(model_factory=lambda *a: None)
        self.assertEqual(scripted._manager_follow_ups(ctx_for(scripted), "run", None, "A.", "en", "gpt-6-sol")["skipped"], "scripted")
        self.assertEqual(scripted._simple_follow_ups("ws", "t", "run", "trace", "yes", {"answerText": "Done."})[0]["skipped"], "scripted")
        self.assertEqual(light.calls, [])

    def test_after_a_deterministic_answer_the_chips_reserve_their_own_small_ceiling_on_the_run(self):
        service = FakeService()
        rt = runtime(service)
        rt.followup_transport = Light()
        chips, settle = rt._simple_follow_ups("ws", "t", "run-9", "trace", "yes", {"answerText": "Done and checked: Instagram post on Thursday 11:00."})
        self.assertEqual(len(chips["followUps"]), 2)
        dimension, estimate, key, model = service.ledger.reserved[0]
        self.assertEqual((dimension, key, model), ("text_model", "agent-follow-ups:run-9", "gpt-6-luna"))
        self.assertLess(estimate, 5_000, "a small per-turn cap")
        self.assertEqual(settle["cost"], CFG.estimate_usd_micro("gpt-6-luna", 400, 30))

    def test_a_refused_budget_means_no_chips_and_no_call(self):
        rt = runtime(FakeService(refuse=True))
        rt.followup_transport = light = Light()
        chips, settle = rt._simple_follow_ups("ws", "t", "run", "trace", "yes", {"answerText": "Done."})
        self.assertEqual((chips["followUps"], chips["skipped"], settle, light.calls), ([], "budget", None, []))


if __name__ == "__main__":
    unittest.main()
