"""Lane B — the presenter against the pinned SDKs (openai==3.19.2, openai-agents==0.22.3). Runs in cloud CI, where
requirements.txt is installed; it checks real SDK names and signatures, not mocks:

- the presenter's request keys are parameters of the pinned AsyncResponses.create / AsyncCompletions.create;
- the stream event type literals the presenter reads are the pinned SDK's literals;
- real SDK event objects flow through the presenter transport into deltas and a final usage record;
- no hidden retries: both the Manager's agent client (manager.provider_model) and the presenter client use max_retries=0.
No network request is made (clients are constructed and closed, never called).
"""
import asyncio
import inspect
import shutil
import typing
import unittest

import openai
from openai.resources.chat.completions import AsyncCompletions
from openai.resources.responses import AsyncResponses
from openai.types.responses import ResponseCompletedEvent, ResponseIncompleteEvent, ResponseTextDeltaEvent
from openai.types.responses.response import Response
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails, ResponseUsage

from postriff_phase2.agent_runtime_v2 import manager, ui_presenter as p

from test_agent_ui_stream_fakes import fake_manifest, fake_projection, make_assets, make_cfg


def _literal(model_cls) -> str:
    return typing.get_args(model_cls.model_fields["type"].annotation)[0]


async def _collect(agen):
    return [item async for item in agen]


async def _events(items):
    for item in items:
        yield item


class PinnedSdk(unittest.TestCase):
    def setUp(self):
        root = make_assets()
        self.addCleanup(shutil.rmtree, root, True)
        self.cfg = make_cfg()
        self.plan = p.build_plan(self.cfg, p.load_assets(root), fake_projection(None, None, {"ui": {"journeyIds": ["J01"]}}, "chat", {}),
                                 fake_manifest(None, None, {"journey_ids": ["J01"]}))

    def test_request_keys_are_pinned_sdk_parameters(self):
        responses = set(inspect.signature(AsyncResponses.create).parameters)
        self.assertLessEqual(set(self.plan.responses_request()), responses)
        chat = set(inspect.signature(AsyncCompletions.create).parameters)
        self.assertLessEqual(set(self.plan.chat_request()), chat)

    def test_event_literals_match_the_pinned_sdk(self):
        self.assertEqual(_literal(ResponseTextDeltaEvent), "response.output_text.delta")
        self.assertEqual(_literal(ResponseCompletedEvent), "response.completed")
        self.assertEqual(_literal(ResponseIncompleteEvent), "response.incomplete")

    def test_real_sdk_events_become_deltas_and_final_usage(self):
        usage = ResponseUsage.model_construct(input_tokens=1500, output_tokens=420, total_tokens=1920,
                                              input_tokens_details=InputTokensDetails.model_construct(cached_tokens=256),
                                              output_tokens_details=OutputTokensDetails.model_construct(reasoning_tokens=64))
        events = [ResponseTextDeltaEvent.model_construct(type="response.output_text.delta", delta="root = ", sequence_number=1),
                  ResponseTextDeltaEvent.model_construct(type="response.output_text.delta", delta="RafiiRoot([])", sequence_number=2),
                  ResponseCompletedEvent.model_construct(type="response.completed", sequence_number=3,
                                                         response=Response.model_construct(id="resp_pinned", usage=usage, incomplete_details=None))]
        items = asyncio.run(_collect(p.OpenAIStreamTransport._responses(_events(events))))
        self.assertEqual(items[:2], [("delta", "root = "), ("delta", "RafiiRoot([])")])
        final = items[-1][1]
        self.assertEqual((final["inputTokens"], final["outputTokens"], final["cachedTokens"], final["reasoningTokens"], final["requestId"], final["known"]),
                         (1500, 420, 256, 64, "resp_pinned", True))

    def test_presenter_client_is_constructed_without_retries(self):
        client = p.OpenAIStreamTransport(self.cfg, self.plan.route).make_client(30.0)
        try:
            self.assertIsInstance(client, openai.AsyncOpenAI)
            self.assertEqual(client.max_retries, 0)
        finally:
            asyncio.run(client.close())

    def test_agent_runtime_client_is_constructed_without_retries(self):
        sink = []
        token = manager._CLIENTS.set(sink)
        try:
            manager.provider_model(self.cfg, "standard_reasoning")
        finally:
            manager._CLIENTS.reset(token)
        self.assertEqual(len(sink), 1)
        self.assertEqual(sink[0].max_retries, 0)
        asyncio.run(manager.close_clients(sink))


if __name__ == "__main__":
    unittest.main()
