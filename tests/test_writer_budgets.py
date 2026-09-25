"""The cloud writer accepts every idea the drafting pipeline composes (instruction plus handed-in material), and the
skill text a turn binds fits the writer's byte-cut slot, so no channel adapter is ever cut silently."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from postriff_alpha.generation import MATERIAL_LABEL  # noqa: E402
from postriff_phase2 import ideas, model_runtime, skills  # noqa: E402
from postriff_phase2.model_runtime import ServerModelRuntime  # noqa: E402
from postriff_phase2.skills import SkillLibrary  # noqa: E402
from test_postriff_model_runtime import DESTS, context  # noqa: E402
from test_postriff_skills import write  # noqa: E402


class IdeaWithMaterialTest(unittest.TestCase):
    def composed(self, instruction, material):
        return instruction + f"\n\n{MATERIAL_LABEL}\n<<<\n{material}\n>>>"

    def test_the_largest_composed_idea_fits_the_writer(self):
        # ideas._project bounds the instruction at IDEA_LIMIT and the material at MAX_TEXT, then joins them.
        largest = self.composed("i" * ideas.IDEA_LIMIT, "m" * ideas.MAX_TEXT)
        self.assertLessEqual(len(largest), model_runtime.MAX_IDEA_CHARS)

    def test_a_long_rewrite_reaches_the_writer_whole(self):
        runtime = ServerModelRuntime("secret-key", model="openai/gpt-6-sol")
        idea = self.composed("Rewrite this draft for LinkedIn in a warmer voice.", "A long draft. " * 400)   # ~5,600 chars, over the old 3,000 cap
        payload = runtime._user_payload({"context": context(), "idea": idea, "destinations": DESTS})
        self.assertEqual(payload["idea"], idea)
        messages = runtime._messages({"context": context(), "idea": idea, "tone": "warm", "destinations": DESTS, "reasoning": "quick"}, "quick")
        self.assertIn("A long draft.", json.loads(messages[1]["content"].split("\n\n")[0])["idea"])


class SkillByteBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "postriff-content-craft", {"SKILL.md": "---\nname: postriff-content-craft\nversion: 1.0.0\n---\n# Craft\nWrite plainly.",
                                                   "references/human-voice-pass.md": "Voice pass.", "references/editorial-workflow.md": "e" * 300})
        write(self.root, "postriff-content-engine", {"SKILL.md": "# Engine\nOne idea per post."})
        write(self.root, "postriff-adapter-contract", {"SKILL.md": "# Channel adapter contract\nEvery result stays draft_only."})
        # 400 characters of Chinese are 1,200 UTF-8 bytes.
        write(self.root, "postriff-channel-xiaohongshu", {"SKILL.md": "# xiaohongshu adapter\n" + "小紅書標題不超過二十字" * 40})

    def tearDown(self):
        self.tmp.cleanup()

    def test_cjk_skill_text_is_budgeted_in_bytes(self):
        library = SkillLibrary(self.root)
        whole = library.bind([{"platform": "Xiaohongshu", "language": "zh-Hans"}], max_chars=100_000)
        chars, size = len(whole["text"]), len(whole["text"].encode())
        self.assertGreater(size, chars)
        # A budget between the character count and the byte count used to pass unchanged, then lose the adapter's
        # tail to the writer's byte cut. Now the binder itself keeps the text within the budget, with a warning.
        budget = chars + (size - chars) // 2
        bound = library.bind([{"platform": "Xiaohongshu", "language": "zh-Hans"}], max_chars=budget)
        self.assertLessEqual(len(bound["text"].encode()), budget)
        self.assertTrue(bound["warnings"], "shrinking the skill text is always reported")
        self.assertTrue(any("bytes" in w for w in bound["warnings"]), bound["warnings"])

    def test_paid_route_output_fits_the_writer_slot(self):
        self.assertLessEqual(skills.budget_for("paid"), model_runtime.MAX_SKILLS_BYTES)



class ThinkingModelTest(unittest.TestCase):
    """A thinking model's reasoning tokens share max_tokens; a 2,400 cap ended long drafts mid-JSON in production.
    Which models think, the reasoning level and the optional parameters come from the gateway catalogue."""

    ASTRA = {"openai/gpt-6-astra": (2.0, 10.0)}   # a model that must reason; priced here for the test

    def call(self, model, **kwargs):
        calls = []

        def transport(method, url, headers=None, body=None, timeout=None):
            calls.append({"body": body, "timeout": timeout})
            return {"status": 200, "body": {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}}
        runtime = ServerModelRuntime("key", model=model, models=[model], transport=transport, prices=self.ASTRA)
        runtime._call([{"role": "user", "content": "x"}], model, **kwargs)
        return calls[0]

    def test_catalogue_driven_reasoning_per_family(self):
        sent = {m: self.call(m)["body"] for m in ("openai/gpt-6-sol", "openai/gpt-6-astra", "anthropic/claude-sonnet-5", "anthropic/claude-opus-5.5",
                                                   "deepseek/deepseek-v4-pro", "anthropic/claude-haiku-4.5", "alibaba/qwen3.6-plus", "openai/gpt-4.1-mini")}
        # The drafting baseline is the lowest real level on the model's scale, never "none", with headroom.
        for model in ("openai/gpt-6-sol", "openai/gpt-6-astra", "anthropic/claude-sonnet-5", "anthropic/claude-opus-5.5", "alibaba/qwen3.6-plus"):
            self.assertEqual(sent[model]["reasoning"], {"effort": "low"}, model)
            self.assertEqual(sent[model]["max_tokens"], model_runtime.THINKING_OUTPUT_TOKENS, model)
        # Only heavy levels (none/high/max) and a toggle: nothing sent, thinking stays off, no headroom.
        self.assertNotIn("reasoning", sent["deepseek/deepseek-v4-pro"])
        self.assertEqual(sent["deepseek/deepseek-v4-pro"]["max_tokens"], model_runtime.MAX_OUTPUT_TOKENS)
        self.assertNotIn("reasoning_effort", sent["openai/gpt-6-sol"])
        self.assertNotIn("response_format", sent["anthropic/claude-opus-5.5"], "only parameters the catalogue lists")
        self.assertNotIn("response_format", sent["alibaba/qwen3.6-plus"])
        # A toggle with no effort scale (thinking off unless asked): nothing sent, no headroom.
        self.assertNotIn("reasoning", sent["anthropic/claude-haiku-4.5"])
        self.assertEqual(sent["anthropic/claude-haiku-4.5"]["max_tokens"], model_runtime.MAX_OUTPUT_TOKENS)
        self.assertNotIn("reasoning", sent["openai/gpt-4.1-mini"])
        self.assertEqual(sent["openai/gpt-4.1-mini"]["max_tokens"], model_runtime.MAX_OUTPUT_TOKENS)
        self.assertEqual(sent["openai/gpt-4.1-mini"]["response_format"], {"type": "json_object"})

    def test_thinking_models_get_a_longer_timeout(self):
        self.assertEqual(self.call("openai/gpt-6-sol")["timeout"], model_runtime.THINKING_TIMEOUT_SECONDS)
        self.assertIsNone(self.call("openai/gpt-4.1-mini")["timeout"], "others keep the transport default")

    def big_deep_request(self):
        # Near every limit at once: a full skills slot, 16 kB of memory and a user payload just under MAX_CONTEXT_BYTES.
        facts = [{"id": f"f{i}", "sourceId": "s1", "text": "Fact " + "x" * 440, "locator": ""} for i in range(95)]
        sources = [{"id": "s1", "policy": "public_quote", "candidateOnly": False, "hash": "h", "facts": facts}]
        return {"context": context(sources=sources), "idea": self.composed_idea(), "tone": "warm", "destinations": DESTS, "reasoning": "deep",
                "memory": [{"name": "VOICE.md", "body": "v" * 16_000}], "skills": {"text": "s" * 59_000}}

    @staticmethod
    def composed_idea():
        return "Rewrite this for LinkedIn." + f"\n\n{MATERIAL_LABEL}\n<<<\n" + "m" * 6_000 + "\n>>>"

    def test_headroom_is_trimmed_to_fit_the_per_request_budget(self):
        import os
        from unittest import mock
        # Priced with expensive output ($2/$20): the full headroom no longer fits the $1 launch policy, a trimmed one does.
        runtime = ServerModelRuntime("key", model="openai/gpt-6-astra", models=["openai/gpt-6-astra"], prices={"openai/gpt-6-astra": (2.0, 20.0)})
        request = self.big_deep_request()
        self.assertLess(len(json.dumps(runtime._user_payload(request), ensure_ascii=False).encode()), model_runtime.MAX_CONTEXT_BYTES)
        with mock.patch.dict(os.environ, {"POSTRIFF_BUDGET_POLICY": ""}):
            self.assertGreater(runtime.price_quote(request), 1.0, "with the full headroom this turn would be refused under $1")
        with mock.patch.dict(os.environ, {"POSTRIFF_BUDGET_POLICY": "launch-2026-09-24"}):
            cap = runtime.output_tokens(request)
            quote = runtime.price_quote(request)
        self.assertLessEqual(quote, 1.0, "a deep turn near the context limit stays inside the $1 policy")
        self.assertGreaterEqual(cap, model_runtime.MAX_OUTPUT_TOKENS)
        self.assertLess(cap, model_runtime.THINKING_OUTPUT_TOKENS)
        with mock.patch.dict(os.environ, {"POSTRIFF_BUDGET_POLICY": ""}):
            self.assertEqual(runtime.output_tokens(request), model_runtime.THINKING_OUTPUT_TOKENS, "no policy: full headroom")
        small = {"context": context(), "idea": "Announce the recital", "destinations": DESTS, "reasoning": "quick"}
        with mock.patch.dict(os.environ, {"POSTRIFF_BUDGET_POLICY": "launch-2026-09-24"}):
            self.assertEqual(runtime.output_tokens(small), model_runtime.THINKING_OUTPUT_TOKENS, "a normal turn keeps the full headroom")

    def test_the_reservation_ceiling_follows_the_larger_cap(self):
        request = {"context": context(), "idea": "Announce the recital", "destinations": DESTS, "reasoning": "quick"}
        thinking = ServerModelRuntime("key", model="openai/gpt-6-astra", models=["openai/gpt-6-astra"], prices=self.ASTRA)
        plain = ServerModelRuntime("key", model="openai/gpt-4.1-mini", models=["openai/gpt-4.1-mini"], prices={"openai/gpt-4.1-mini": (2.0, 10.0)})   # same prices, no reasoning
        self.assertGreater(thinking.price_quote(request), plain.price_quote(request))
        self.assertGreater(thinking.typical_quote(request), plain.typical_quote(request))
        self.assertLess(thinking.price_quote(request), 1.0, "stays under the $1 per-request policy")


class StructuredCallTest(unittest.TestCase):
    def body(self, model):
        from postriff_phase2.learning_model import GatewayCall
        calls = []

        def transport(method, url, headers=None, body=None):
            calls.append(body)
            return {"status": 200, "body": {"choices": [{"message": {"content": "{}"}}], "usage": {}}}
        GatewayCall("key", model=model, transport=transport)("system", "user", {"type": "object"})
        return calls[0]

    def test_side_calls_keep_thinking_off_where_they_can(self):
        sonnet, opus, haiku = (self.body(m) for m in ("anthropic/claude-sonnet-5", "anthropic/claude-opus-5.5", "anthropic/claude-haiku-4.5"))
        self.assertEqual((sonnet["reasoning"], sonnet["max_tokens"]), ({"effort": "none"}, 1200))
        self.assertNotIn("temperature", sonnet, "the catalogue does not list temperature for Sonnet 5")
        self.assertEqual((opus["reasoning"], opus["max_tokens"]), ({"effort": "low"}, 4000))
        self.assertNotIn("response_format", opus)
        self.assertNotIn("reasoning", haiku)
        self.assertEqual((haiku["max_tokens"], haiku["temperature"]), (1200, 0.2))


class CatalogueTest(unittest.TestCase):
    def test_parse_and_refresh_keep_what_works(self):
        from postriff_phase2 import gateway_catalog
        data = {"data": [{"id": "vendor/new", "type": "language", "reasoning_options": [{"type": "effort", "values": ["low", "high"]}], "supported_parameters": ["reasoning", "max_tokens"], "max_tokens": 1000},
                         {"id": "vendor/image", "type": "image"}]}
        self.assertEqual(gateway_catalog.parse(data), {"vendor/new": {"reasoning": [{"type": "effort", "values": ["low", "high"]}], "params": ["max_tokens", "reasoning"], "maxTokens": 1000}})
        before = gateway_catalog._models()
        gateway_catalog._refresh(transport=lambda url: {"data": []})
        self.assertIs(gateway_catalog._models(), before, "an empty answer never replaces the catalogue")

    def test_only_a_deployed_app_fetches(self):
        import os
        from unittest import mock
        from postriff_phase2 import gateway_catalog
        with mock.patch.dict(os.environ, {"VERCEL": ""}):
            self.assertFalse(gateway_catalog._refresh_allowed())
        with mock.patch.dict(os.environ, {"VERCEL": "1", "POSTRIFF_GATEWAY_CATALOG_REFRESH": "0"}):
            self.assertFalse(gateway_catalog._refresh_allowed())

if __name__ == "__main__":
    unittest.main()
