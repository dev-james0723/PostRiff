"""manager.MeteredModel.stream_response meters streamed calls exactly like get_response (runtime-core D4, A-DECISIONS D-A23):
one span from the final `response.completed` usage; a raised, abandoned or usage-less stream is one failed/unknown call in
`ledger.calls` (never zero spend). Requires openai-agents (cloud CI)."""
import asyncio
import unittest
from types import SimpleNamespace

from agents.models.interface import Model

from postriff_phase2.agent_runtime_v2 import manager
from postriff_phase2.agent_runtime_v2.context import EffectLedger


class _Inner(Model):
    def __init__(self, events, error=None):
        self.events, self.error = events, error

    async def get_response(self, *args, **kwargs):  # pragma: no cover - not used here
        raise AssertionError("streaming only")

    async def stream_response(self, *args, **kwargs):
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


def _wrap(inner):
    ctx = SimpleNamespace(ledger=EffectLedger(), thinking=lambda *a, **k: None)
    return ctx, manager.metered(inner, ctx, agent="rafii_presenter", workload="fast_language", route={"model": "gpt-6-luna", "provider": "openai"})


async def _drain(model, stop_after=None):
    seen = []
    stream = model.stream_response(None, "hi", None, [], None, [], None, previous_response_id=None, conversation_id=None, prompt=None)
    async for event in stream:
        seen.append(event)
        if stop_after is not None and len(seen) >= stop_after:
            await stream.aclose()
            break
    return seen


def _completed(inp, out):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out, input_tokens_details=SimpleNamespace(cached_tokens=0),
                            output_tokens_details=SimpleNamespace(reasoning_tokens=0))
    return SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage, response_id="resp_s"))


class MeteredStream(unittest.TestCase):
    def test_final_usage_becomes_one_span(self):
        ctx, model = _wrap(_Inner([SimpleNamespace(type="response.output_text.delta", delta="a"), _completed(1200, 80)]))
        asyncio.run(_drain(model))
        self.assertEqual(ctx.ledger.model_requests, 1)
        self.assertEqual(len(ctx.ledger.spans), 1)
        self.assertEqual((ctx.ledger.spans[0]["inputTokens"], ctx.ledger.spans[0]["outputTokens"]), (1200, 80))
        self.assertEqual(ctx.ledger.calls, [])

    def test_failed_stream_is_one_unknown_call(self):
        ctx, model = _wrap(_Inner([SimpleNamespace(type="response.output_text.delta", delta="a")], error=ConnectionResetError()))
        with self.assertRaises(ConnectionResetError):
            asyncio.run(_drain(model))
        self.assertEqual(ctx.ledger.spans, [])
        self.assertEqual([c["status"] for c in ctx.ledger.calls], ["unknown"])
        self.assertNotIn("cost_usd_micro", ctx.ledger.calls[0])

    def test_stream_without_final_usage_is_unknown(self):
        ctx, model = _wrap(_Inner([SimpleNamespace(type="response.output_text.delta", delta="a")]))
        asyncio.run(_drain(model))
        self.assertEqual([c["status"] for c in ctx.ledger.calls], ["unknown"])

    def test_abandoned_stream_is_unknown(self):
        ctx, model = _wrap(_Inner([SimpleNamespace(type="response.output_text.delta", delta="a"), SimpleNamespace(type="response.output_text.delta", delta="b"),
                                   _completed(10, 10)]))
        asyncio.run(_drain(model, stop_after=1))
        self.assertEqual(ctx.ledger.spans, [])
        self.assertEqual(len(ctx.ledger.calls), 1)


if __name__ == "__main__":
    unittest.main()
