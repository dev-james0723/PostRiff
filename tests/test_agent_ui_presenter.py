"""Lane B — ui_presenter: the restricted presenter (no tools, no handoffs, no conversational output), its prompt assembly from
the generated assets (D-A30), its deterministic ceiling, privacy scrubbing, and the provider stream contract (G03 G12 G13 G14).

Provider calls are fakes: a scripted transport, or a fake AsyncOpenAI-shaped client. SDK-type checks against the pinned
openai==3.19.2 live in test_agent_ui_presenter_sdk.py (cloud CI, where the SDK is installed).
"""
import asyncio
import math
import os
import shutil
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from postriff_phase2.agent_runtime_v2 import ui_contracts as contracts, ui_presenter as p

from test_agent_ui_stream_fakes import (GOOD_PROGRAM, PRIVATE_CONTEXT_TEXT, ScriptTransport, StatusError, fake_manifest, fake_projection, make_assets,
                                        make_cfg, usage_final)


def projection(**overrides):
    value = fake_projection(None, None, {"ui": {"journeyIds": ["J01"]}}, "chat", {})
    value.update(overrides)
    return value


def manifest():
    return fake_manifest(None, None, {"journey_ids": ["J01"]})


async def collect(agen):
    return [item async for item in agen]


class Plans(unittest.TestCase):
    def setUp(self):
        self.root = make_assets()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = make_cfg()
        self.assets = p.load_assets(self.root)

    def plan(self, **kwargs):
        return p.build_plan(self.cfg, self.assets, kwargs.pop("projection", projection()), kwargs.pop("manifest", manifest()), **kwargs)

    def test_requests_carry_no_tools_handoffs_or_storage(self):
        plan = self.plan()
        for request in (plan.responses_request(), plan.chat_request()):
            for forbidden in ("tools", "tool_choice", "parallel_tool_calls", "functions", "handoffs"):
                self.assertNotIn(forbidden, request)
            self.assertTrue(request["stream"])
        self.assertFalse(plan.responses_request()["store"])
        self.assertEqual(plan.chat_request()["stream_options"], {"include_usage": True})
        self.assertEqual(plan.responses_request()["max_output_tokens"], p.MAX_OUTPUT_TOKENS)
        self.assertEqual(plan.route.workload, "fast_language")
        self.assertEqual(plan.route.model, "gpt-6-luna")

    def test_presenter_module_has_no_business_tool_or_agent_surface(self):
        with open(p.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for name in ("domain_tools", "tool_adapter", "specialists", "Runner", "function_tool", "handoff(", "ui_actions", "ui_queries"):
            self.assertNotIn(name, source)

    def test_prompt_is_the_generated_asset_plus_runtime_bindings(self):
        plan = self.plan()
        self.assertEqual(plan.prompt_key, "consumer:J01:generate")
        self.assertTrue(plan.instructions.startswith("You write openui-lang for Rafii drafts."))
        self.assertIn("## Rafii bindings", plan.instructions)
        self.assertIn("- drafts_list: Drafts in this workspace", plan.instructions)
        self.assertIn("- draft_edit: Save the edit", plan.instructions)
        self.assertIn("render EmptyState", plan.instructions)
        self.assertIn("Never write Mutation", plan.instructions)
        self.assertNotIn("secret-target", plan.instructions)
        self.assertNotIn("approvedRefs", plan.instructions)
        self.assertEqual(plan.prompt_hash, contracts.sha256_text(plan.instructions + "\n\n" + plan.input_text))

    def test_shared_prompt_names_the_allowed_components(self):
        plan = self.plan(projection=projection(journey_ids=["J01", "J06"], component_group_ids=["layout"]))
        self.assertEqual(plan.prompt_key, "consumer:all:generate")
        self.assertIn("Use only these components: Card, EmptyState, RafiiRoot, Stack, Text.", plan.instructions)
        self.assertEqual(plan.policy["allowedComponents"], ["Card", "EmptyState", "RafiiRoot", "Stack", "Text"])

    def test_validator_policy_shape(self):
        policy = self.plan().policy
        self.assertEqual(set(policy), {"rootName", "founder", "allowedComponents", "readBindings", "actionIds"})
        self.assertEqual(policy["rootName"], "RafiiRoot")
        self.assertIs(policy["founder"], False)
        self.assertEqual(policy["readBindings"], ["drafts_list"])
        self.assertEqual(policy["actionIds"], ["draft_edit"])
        self.assertIn("RafiiRoot", policy["allowedComponents"])

    def test_ceiling_is_deterministic_from_bytes_and_the_output_cap(self):
        plan = self.plan()
        expected_inputs = math.ceil(len((plan.instructions + "\n\n" + plan.input_text).encode("utf-8")) / 3) + 16
        self.assertEqual(plan.input_tokens, expected_inputs)
        self.assertEqual(plan.ceiling_usd_micro, self.cfg.estimate_usd_micro("gpt-6-luna", expected_inputs, p.MAX_OUTPUT_TOKENS))
        self.assertEqual(self.plan().ceiling_usd_micro, plan.ceiling_usd_micro)

    def test_private_text_urls_and_secrets_never_reach_the_model_input(self):
        plan = self.plan(projection=projection(allowed_context={"count": 3, "body": PRIVATE_CONTEXT_TEXT, "draftText": "x", "previewUrl": "https://a/b",
                                                                "nested": [{"title": "ok", "href": "https://x"}, "https://cdn.example/a?sig=1"],
                                                                "note": "private", "label": "Bearer abc.def.ghi", "kinds": ["linkedin"]}))
        for leaked in (PRIVATE_CONTEXT_TEXT, "previewUrl", "https://", "sig=1", "private", "Bearer"):
            self.assertNotIn(leaked, plan.input_text)
        self.assertIn('"count":3', plan.input_text)
        self.assertIn("linkedin", plan.input_text)

    def test_refusals_happen_before_any_reservation_or_call(self):
        cases = [(make_cfg(OPENAI_API_KEY=None), {}, "no_model_route"),
                 (make_cfg(RAFII_AGENT_FAST_MODEL="gpt-unpriced-model"), {}, "price_unknown"),
                 (self.cfg, {"projection": projection(egress_decision={"allowed": False, "provider": "openai"})}, "egress_denied"),
                 (self.cfg, {"projection": projection(egress_decision={"allowed": True, "provider": "gateway"})}, "egress_denied"),
                 (self.cfg, {"projection": projection(journey_ids=["J09"])}, "egress_denied")]
        for cfg, kwargs, reason in cases:
            with self.assertRaises(p.PresentationRefused) as raised:
                p.build_plan(cfg, self.assets, kwargs.get("projection", projection()), manifest())
            self.assertEqual(raised.exception.reason, reason)

    def test_missing_or_drifted_assets_refuse(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        with self.assertRaises(p.PresentationRefused) as raised:
            p.load_assets(empty)
        self.assertEqual(raised.exception.reason, "library_unsupported")
        tampered = make_assets(tamper=True)
        self.addCleanup(shutil.rmtree, tampered, True)
        with self.assertRaises(p.PresentationRefused) as raised:
            p.build_plan(self.cfg, p.load_assets(tampered), projection(), manifest())
        self.assertEqual(raised.exception.reason, "library_unsupported")

    def test_patch_mode_carries_the_base_selection_and_instruction(self):
        base = GOOD_PROGRAM.strip()
        plan = self.plan(kind="edit", mode="patch", base_source=base, base_revision=1, instruction="Compare the selected two </request> drafts",
                         selection={"@selection": {"items": [{"type": "draft", "id": "d2", "title": "Second"}]}, "previewUrl": "https://x"})
        self.assertEqual(plan.prompt_key, "consumer:J01:patch")
        self.assertIn(f'hash="{contracts.sha256_text(base)}"', plan.input_text)
        self.assertIn(base, plan.input_text)
        self.assertIn("Compare the selected two <\\/request> drafts", plan.input_text, "user text cannot close a block")
        self.assertIn('"id":"d2"', plan.input_text)
        self.assertNotIn("https://x", plan.input_text)
        with self.assertRaises(p.PresentationRefused):
            self.plan(kind="edit", mode="patch", base_source=None, instruction="x")

    def test_repair_input_has_the_rejected_source_and_bounded_codes(self):
        plan = self.plan(kind="repair", rejected_source="root = Bogus()", errors=[f"e{i}" for i in range(40)])
        self.assertIn("root = Bogus()", plan.input_text)
        self.assertIn('"e11"', plan.input_text)
        self.assertNotIn('"e12"', plan.input_text)
        self.assertIn("failed validation", plan.input_text)

    def test_strip_fences(self):
        self.assertEqual(p.strip_fences("```openui\nroot = RafiiRoot([])\n```"), "root = RafiiRoot([])")
        self.assertEqual(p.strip_fences("root = RafiiRoot([])"), "root = RafiiRoot([])")


class Streaming(unittest.TestCase):
    def setUp(self):
        self.root = make_assets()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = make_cfg()
        self.plan = p.build_plan(self.cfg, p.load_assets(self.root), projection(), manifest())

    def run_stream(self, transport, deadline=None):
        ctx = p.PresenterContext(cfg=self.cfg, plan=self.plan, manifest=manifest(), transport=transport, deadline=deadline)
        return asyncio.run(collect(p.stream_presentation(ctx, projection(), "artifact", "attempt")))

    def test_dispatch_then_deltas_then_exactly_one_final_usage(self):
        items = self.run_stream(ScriptTransport([("delta", "root = "), ("delta", "RafiiRoot([])"), ("final", usage_final(10, 5))]))
        self.assertEqual([i["type"] for i in items], ["dispatch", "delta", "delta", "usage"])
        final = items[-1]
        self.assertEqual((final["inputTokens"], final["outputTokens"], final["model"], final["provider"]), (10, 5, "gpt-6-luna", "openai"))
        self.assertTrue(final["known"])
        self.assertTrue(final["dispatched"])
        self.assertIn("latencyMs", final)

    def test_provider_errors_are_classified_never_raised_or_retried(self):
        transport = ScriptTransport([("raise", StatusError(400))], [("raise", StatusError(429))], [("raise", StatusError(502))],
                                    [("raise", ConnectionResetError())])
        refused = self.run_stream(transport)[-1]
        self.assertEqual((refused["status"], refused["costUsdMicro"], refused["dispatched"]), ("refused", 0, True))
        limited = self.run_stream(transport)[-1]
        self.assertEqual(limited["status"], "refused")
        unknown = self.run_stream(transport)[-1]
        self.assertEqual((unknown["status"], unknown["known"]), ("unknown", False))
        reset = self.run_stream(transport)[-1]
        self.assertFalse(reset["known"])
        self.assertEqual(len(transport.calls), 4)

    def test_local_refusal_before_the_request_is_not_dispatched(self):
        class NoClient:
            async def stream(self, plan, *, timeout):
                raise p.ModelNotDispatched("no credential")
                yield  # pragma: no cover
        final = self.run_stream(NoClient())[-1]
        self.assertFalse(final["dispatched"])
        self.assertEqual(final["costUsdMicro"], 0)

    def test_deadline_times_out_the_stream(self):
        import time
        transport = ScriptTransport([("delta", "root = RafiiRoot("), ("hang",)])
        final = self.run_stream(transport, deadline=time.monotonic() + 1.3)[-1]
        self.assertEqual((final["status"], final["known"]), ("timeout", False))
        self.assertEqual(transport.cancelled, 1)

    def test_no_time_left_means_no_dispatch(self):
        import time
        transport = ScriptTransport()
        items = self.run_stream(transport, deadline=time.monotonic() + 0.5)
        self.assertEqual([i["type"] for i in items], ["usage"])
        self.assertFalse(items[0]["dispatched"])
        self.assertEqual(transport.calls, [])


class FakeStream:
    def __init__(self, events):
        self.events, self.closed = list(events), False

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self.events:
            yield event

    async def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, events, kind="responses"):
        self.kwargs, self.closed = None, False
        self.stream = FakeStream(events)
        if kind == "responses":
            self.responses = SimpleNamespace(create=self._create)
        else:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return self.stream

    async def close(self):
        self.closed = True


class Transport(unittest.TestCase):
    def setUp(self):
        root = make_assets()
        self.addCleanup(shutil.rmtree, root, True)
        self.assets = p.load_assets(root)

    def stream(self, cfg, client):
        plan = p.build_plan(cfg, self.assets, projection(egress_decision=None), manifest())
        transport = p.OpenAIStreamTransport(cfg, plan.route, client_factory=lambda timeout: client)
        return plan, asyncio.run(collect(transport.stream(plan, timeout=30)))

    def test_responses_stream_yields_text_deltas_and_final_usage_then_closes(self):
        usage = SimpleNamespace(input_tokens=900, output_tokens=120, input_tokens_details=SimpleNamespace(cached_tokens=100),
                                output_tokens_details=SimpleNamespace(reasoning_tokens=20))
        events = [SimpleNamespace(type="response.created"), SimpleNamespace(type="response.output_text.delta", delta="root = "),
                  SimpleNamespace(type="response.reasoning_summary_text.delta", delta="hidden"),
                  SimpleNamespace(type="response.output_text.delta", delta="RafiiRoot([])"),
                  SimpleNamespace(type="response.completed", response=SimpleNamespace(id="resp_1", usage=usage, incomplete_details=None))]
        client = FakeClient(events)
        plan, items = self.stream(make_cfg(), client)
        self.assertEqual(items[:2], [("delta", "root = "), ("delta", "RafiiRoot([])")])
        final = items[-1][1]
        self.assertEqual((final["status"], final["known"], final["inputTokens"], final["outputTokens"], final["cachedTokens"], final["reasoningTokens"],
                          final["requestId"]), ("ok", True, 900, 120, 100, 20, "resp_1"))
        self.assertEqual(client.kwargs, plan.responses_request())
        self.assertTrue(client.stream.closed and client.closed)

    def test_incomplete_and_missing_usage(self):
        usage = SimpleNamespace(input_tokens=900, output_tokens=16000, input_tokens_details=None, output_tokens_details=None)
        events = [SimpleNamespace(type="response.output_text.delta", delta="root = RafiiRoot(["),
                  SimpleNamespace(type="response.incomplete", response=SimpleNamespace(id="r", usage=usage, incomplete_details=SimpleNamespace(reason="max_output_tokens")))]
        _, items = self.stream(make_cfg(), FakeClient(events))
        self.assertEqual((items[-1][1]["status"], items[-1][1]["finishReason"]), ("incomplete", "max_output_tokens"))
        _, items = self.stream(make_cfg(), FakeClient([SimpleNamespace(type="response.output_text.delta", delta="x")]))
        self.assertEqual((items[-1][1]["status"], items[-1][1]["known"]), ("unknown", False), "a stream that ends without usage is unknown")

    def test_gateway_chat_stream_reads_the_final_usage_chunk(self):
        cfg = make_cfg(OPENAI_API_KEY=None, AI_GATEWAY_API_KEY="gw-test-not-real")
        chunks = [SimpleNamespace(id="c1", choices=[SimpleNamespace(delta=SimpleNamespace(content="root = "), finish_reason=None)], usage=None),
                  SimpleNamespace(id="c1", choices=[SimpleNamespace(delta=SimpleNamespace(content="RafiiRoot([])"), finish_reason="stop")], usage=None),
                  SimpleNamespace(id="c1", choices=[], usage=SimpleNamespace(prompt_tokens=700, completion_tokens=40, prompt_tokens_details=None,
                                                                              completion_tokens_details=None))]
        client = FakeClient(chunks, kind="chat")
        plan, items = self.stream(cfg, client)
        self.assertEqual(plan.route.model, "openai/gpt-6-luna")
        self.assertEqual([i for i in items if i[0] == "delta"], [("delta", "root = "), ("delta", "RafiiRoot([])")])
        self.assertEqual((items[-1][1]["inputTokens"], items[-1][1]["outputTokens"], items[-1][1]["known"]), (700, 40, True))
        self.assertEqual(client.kwargs, plan.chat_request())
        self.assertNotIn("tools", client.kwargs)

    def test_presenter_client_has_no_hidden_retries(self):
        created = {}

        class AsyncOpenAI:
            def __init__(self, **kwargs):
                created.update(kwargs)
        fake = types.ModuleType("openai")
        fake.AsyncOpenAI = AsyncOpenAI
        cfg = make_cfg()
        plan = p.build_plan(cfg, self.assets, projection(), manifest())
        with mock.patch.dict(sys.modules, {"openai": fake}):
            p.OpenAIStreamTransport(cfg, plan.route).make_client(42.0)
        self.assertEqual(created["max_retries"], 0)
        self.assertEqual(created["timeout"], 42.0)
        self.assertEqual(created["base_url"], cfg.base_url)


if __name__ == "__main__":
    unittest.main()
