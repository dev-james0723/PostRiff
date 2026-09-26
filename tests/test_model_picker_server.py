"""Model picker, server side: per-model reasoning levels from the gateway catalogue, their caps, attempts, time and
per-request ceilings; what a run records about the reasoning it asked for and spent; the catalogue the picker reads;
and the workspace default writer ("Auto") that every request naming no writer resolves to."""
import json
import os
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns, gateway_catalog, model_runtime, writer_defaults
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.cli_runtime import ClaudeCliRuntime
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.ideas import IdeasService, RunSink, requested_level, translate_reasoning
from postriff_phase2.model_runtime import ProviderFailure, ServerModelRuntime, check_level_ceiling, level_quote
from test_postriff_model_runtime import DESTS, GOOD, context

PRICES = {"openai/gpt-6-sol": (2, 10), "openai/gpt-6-luna": (0.1, 0.5), "openai/gpt-6-astra": (10, 50), "anthropic/claude-sonnet-5": (2, 10),
          "google/gemini-3.8-flash": (0.75, 3.75), "google/gemini-3.1-pro-preview": (2, 12), "bytedance/seed-2.1-turbo": (1, 4),
          "minimax/minimax-m3": (1, 4), "meta/muse-spark-1.2": (1, 4)}
MODELS = list(PRICES)
NO_POLICY = {"POSTRIFF_BUDGET_POLICY": ""}
LAUNCH = {"POSTRIFF_BUDGET_POLICY": "launch-2026-09-24"}
PAID = {"POSTRIFF_BUDGET_POLICY": "paid-2026-09-24"}


def production(transport=None, **kwargs):
    kwargs.setdefault("prices", PRICES)
    return ServerModelRuntime("key", model="openai/gpt-6-sol", models=MODELS, transport=transport, **kwargs)


class Transport:
    """Records every call; answers with the queued responses (a dict per call)."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls.append({"body": body, "timeout": timeout})
        return self.responses.pop(0)


def answer(variants=GOOD, usage=None, finish="stop", provider=None):
    body = {"choices": [{"message": {"content": json.dumps({"variants": variants}) if isinstance(variants, list) else variants}, "finish_reason": finish}],
            "usage": usage if usage is not None else {"prompt_tokens": 1000, "completion_tokens": 400}}
    if provider:
        body["providerMetadata"] = {"gateway": {"routing": {"finalProvider": provider}}}
    return {"status": 200, "body": body}


def request(**extra):
    return {"context": context(), "idea": "Announce the seed swap", "tone": "warm", "destinations": DESTS, **extra}


class CatalogueTest(unittest.TestCase):
    def test_levels_output_limit_and_version_come_from_the_catalogue(self):
        self.assertEqual(gateway_catalog.levels("openai/gpt-6-sol"), ["none", "low", "medium", "high", "xhigh", "max"])
        self.assertEqual(gateway_catalog.levels("minimax/minimax-m3"), [], "budget-only: no effort scale")
        self.assertEqual(gateway_catalog.levels("vendor/unlisted"), [])
        self.assertEqual(gateway_catalog.max_tokens("google/gemini-3.8-flash"), 65535)
        self.assertIsNone(gateway_catalog.max_tokens("vendor/unlisted"))
        version = gateway_catalog.version()
        self.assertEqual(version["snapshot"], "2026-09-25")

    def test_the_version_names_a_refresh_only_when_it_replaced_the_models(self):
        saved = dict(gateway_catalog._state)
        self.addCleanup(gateway_catalog._state.update, saved)
        gateway_catalog._models()
        gateway_catalog._state["refreshedAt"] = None
        gateway_catalog._refresh(transport=lambda url: {"data": []})
        self.assertIsNone(gateway_catalog.version()["refreshedAt"], "a failed or empty refresh keeps the snapshot")
        gateway_catalog._refresh(transport=lambda url: {"data": [{"id": "vendor/new", "type": "language"}]})
        self.assertIsInstance(gateway_catalog.version()["refreshedAt"], float)

    def test_thinking_follows_an_explicit_level(self):
        self.assertTrue(gateway_catalog.thinking("openai/gpt-6-sol"))
        self.assertFalse(gateway_catalog.thinking("openai/gpt-6-sol", "none"))
        self.assertTrue(gateway_catalog.thinking("openai/gpt-6-sol", "high"))
        self.assertFalse(gateway_catalog.thinking("anthropic/claude-haiku-4.5", "auto"))

    def test_models_carry_family_tier_featured_and_default(self):
        runtime = production(prices={**PRICES, "google/gemini-3.1-pro-preview": None})
        rows = {m["id"]: m for m in runtime.list_supported_models()}
        sol, luna, astra, seed = rows["openai/gpt-6-sol"], rows["openai/gpt-6-luna"], rows["openai/gpt-6-astra"], rows["bytedance/seed-2.1-turbo"]
        self.assertEqual((sol["displayName"], sol["maker"], sol["family"], sol["default"]), ("gpt-6-sol", "openai", "GPT", True))
        self.assertEqual((sol["featured"], sol["featuredRank"], luna["featured"], luna["featuredRank"]), (True, 0, False, None))
        self.assertEqual((seed["family"], rows["minimax/minimax-m3"]["family"], rows["meta/muse-spark-1.2"]["family"]), ("Seed", "MiniMax", "Muse"))
        self.assertEqual([(m["costTier"], m["costTierLabel"]) for m in (luna, sol, astra)], [(1, "Lower cost"), (2, "Medium cost"), (3, "Higher cost")])
        unpriced = rows["google/gemini-3.1-pro-preview"]
        self.assertEqual((unpriced["priced"], unpriced["qualified"], unpriced["costTier"], unpriced["costTierLabel"]), (False, True, None, None))
        self.assertEqual(runtime.featured_models(), list(model_runtime.FEATURED_MODELS))

    def test_featured_models_can_be_set_by_environment(self):
        from postriff_phase2.hosted_app import ideas_runtime_from_environment
        runtime = ideas_runtime_from_environment({"AI_GATEWAY_API_KEY": "k", "POSTRIFF_MODEL_ID": "openai/gpt-6-sol", "POSTRIFF_MODEL_IDS": "openai/gpt-6-sol,openai/gpt-6-luna",
                                                  "POSTRIFF_FEATURED_MODEL_IDS": "openai/gpt-6-luna, vendor/not-offered ,openai/gpt-6-sol"})
        self.assertEqual(runtime.featured_models(), ["openai/gpt-6-luna", "openai/gpt-6-sol"], "ids the deployment does not offer are ignored")

    def test_per_model_levels_in_order_with_what_they_send_and_cost(self):
        runtime = production()
        with mock.patch.dict(os.environ, PAID):
            sol = runtime.list_supported_reasoning(model="openai/gpt-6-sol")
            minimax = runtime.list_supported_reasoning(model="minimax/minimax-m3")
            muse = runtime.list_supported_reasoning(model="meta/muse-spark-1.2")
        self.assertEqual([i["id"] for i in sol], ["auto", "none", "low", "medium", "high", "xhigh", "max", "thorough"])
        self.assertEqual([i["label"] for i in sol], ["Auto", "Off", "Low", "Medium", "High", "Extra high", "Max", "Thorough (draft, then revise)"])
        self.assertEqual([i["kind"] for i in sol], ["auto"] + ["effort"] * 6 + ["pass"])
        self.assertEqual([i["sends"] for i in sol], ["low", "none", "low", "medium", "high", "xhigh", "max", "low"])
        by_id = {i["id"]: i for i in sol}
        for level in ("xhigh", "max"):
            self.assertEqual((by_id[level]["available"], by_id[level]["detail"], by_id[level]["ceilingMilliCredits"]), (False, "Not offered yet: too slow for one draft", None))
        self.assertTrue(all(by_id[level]["available"] for level in ("auto", "none", "low", "medium", "high", "thorough")))
        self.assertLess(by_id["auto"]["typicalMilliCredits"], by_id["auto"]["ceilingMilliCredits"])
        self.assertGreater(by_id["thorough"]["ceilingMilliCredits"], by_id["auto"]["ceilingMilliCredits"])
        self.assertTrue(all("Usd" not in key for item in sol for key in item), "the public catalogue shows credits, never provider USD")
        self.assertEqual([(i["id"], i["sends"]) for i in minimax], [("auto", None), ("thorough", None)], "budget-only: Auto and Thorough")
        self.assertEqual([i["id"] for i in muse], ["auto", "minimal", "low", "medium", "high", "xhigh", "thorough"])
        self.assertEqual(runtime.list_supported_reasoning()[0]["id"], "quick", "without a model: the legacy list, unchanged")

    def test_a_level_over_the_request_limit_is_marked_and_auto_never_is(self):
        runtime = production()
        with mock.patch.dict(os.environ, LAUNCH):
            astra = {i["id"]: i for i in runtime.list_supported_reasoning(model="openai/gpt-6-astra")}
        self.assertEqual((astra["low"]["available"], astra["low"]["detail"]), (False, "Over the per-request limit"))
        self.assertTrue(astra["auto"]["available"], "Auto trims its headroom instead")

    def test_a_broken_policy_never_breaks_the_catalogue(self):
        runtime = production(prices={**PRICES, "google/gemini-3.8-flash": None})
        with mock.patch.dict(os.environ, {"POSTRIFF_BUDGET_POLICY": "no-such-policy"}):
            sol = {i["id"]: i for i in runtime.list_supported_reasoning(model="openai/gpt-6-sol")}
            unpriced = runtime.list_supported_reasoning(model="google/gemini-3.8-flash")
        self.assertTrue(sol["auto"]["available"])
        self.assertEqual((sol["high"]["available"], sol["high"]["detail"]), (False, "Paid AI requests are off on this deployment"))
        self.assertFalse(sol["thorough"]["available"])
        with mock.patch.dict(os.environ, NO_POLICY):
            unpriced = runtime.list_supported_reasoning(model="google/gemini-3.8-flash")
        self.assertEqual({i["ceilingMilliCredits"] for i in unpriced}, {None}, "no price, no credit figures, no exception")

    def test_the_ideas_catalogue_asks_per_model_and_names_default_and_featured(self):
        fixture, managed = FixtureAgentRuntime(), production()
        ideas = IdeasService(None, None, runtime=fixture, runtimes=[fixture, managed], researcher=False)
        with mock.patch.dict(os.environ, NO_POLICY):
            catalog = ideas.model_catalog()
        models = {m["id"]: m for m in catalog["models"]}
        self.assertEqual(catalog["defaultModel"], "openai/gpt-6-sol")
        self.assertEqual(catalog["featured"], list(model_runtime.FEATURED_MODELS))
        self.assertEqual(models["deterministic-preview"]["reasoning"], fixture.list_supported_reasoning())
        self.assertEqual([i["id"] for i in models["minimax/minimax-m3"]["reasoning"]], ["auto", "thorough"])
        self.assertEqual(catalog["reasoning"], managed.list_supported_reasoning(), "top level stays the legacy list")
        alone = IdeasService(None, None, runtime=fixture, runtimes=[fixture], researcher=False).model_catalog()
        self.assertEqual((alone["defaultModel"], alone["featured"]), (None, []))

    def test_the_fixture_fallback_has_the_same_keys(self):
        from postriff_phase2.hosted_app import HostedApplication
        from test_postriff_phase2_hosted import invoke
        app = HostedApplication(type("Service", (), {"ideas": object()})(), None, {"provider": "supabase"}, "c" * 24)
        status, _, body = invoke(app, "GET", "/api/ideas/models")
        self.assertEqual((status, body["defaultModel"], body["featured"]), (200, None, []))


class LevelCallTest(unittest.TestCase):
    def call(self, model, **kwargs):
        transport = Transport(answer())
        ServerModelRuntime("key", model=model, models=[model], prices=PRICES, transport=transport)._call([{"role": "user", "content": "x"}], model, **kwargs)
        return transport.calls[0]

    def test_an_explicit_level_is_sent_with_its_own_cap_and_time(self):
        medium = self.call("openai/gpt-6-sol", effort="medium")
        self.assertEqual((medium["body"]["reasoning"], medium["body"]["max_tokens"], medium["timeout"]), ({"effort": "medium"}, 8_000, 160))
        high = self.call("google/gemini-3.8-flash", effort="high")
        self.assertEqual((high["body"]["reasoning"], high["body"]["max_tokens"], high["timeout"]), ({"effort": "high"}, 12_000, 240))
        off = self.call("openai/gpt-6-sol", effort="none")
        self.assertEqual((off["body"]["reasoning"], off["body"]["max_tokens"], off["timeout"]), ({"effort": "none"}, 2_400, None), "thinking off: no headroom, the default 45 s")
        auto = self.call("openai/gpt-6-sol")
        self.assertEqual((auto["body"]["reasoning"], auto["body"]["max_tokens"], auto["timeout"]), ({"effort": "low"}, 4_500, 90), "Auto is today's baseline")

    def test_a_level_the_model_does_not_list_is_never_sent(self):
        for model, level in (("openai/gpt-6-astra", "none"), ("google/gemini-3.8-flash", "medium"), ("minimax/minimax-m3", "low"), ("openai/gpt-6-sol", "xhigh")):
            transport = Transport()
            runtime = ServerModelRuntime("key", model=model, models=[model], prices=PRICES, transport=transport)
            with self.subTest(model=model), self.assertRaises(ProviderFailure) as refused:
                runtime._call([{"role": "user", "content": "x"}], model, {"dispatched": False}, effort=level)
            self.assertEqual((refused.exception.dispatched, refused.exception.cost_usd, transport.calls), (False, 0.0, []))

    def test_caps_stay_inside_the_catalogue_output_limit(self):
        runtime = production()
        with mock.patch.object(gateway_catalog, "max_tokens", return_value=6_000):
            self.assertEqual(model_runtime.level_cap(runtime, "openai/gpt-6-sol", "high", 1_000), 6_000)
            self.assertEqual(model_runtime.level_cap(runtime, "openai/gpt-6-sol", "low", 1_000), 4_500)


class LevelQuoteTest(unittest.TestCase):
    def test_explicit_levels_are_priced_untrimmed_with_their_attempts(self):
        runtime = production()
        with mock.patch.dict(os.environ, LAUNCH):
            high = level_quote(runtime, "openai/gpt-6-astra", "high", 48_000, 1)
            auto = level_quote(runtime, "openai/gpt-6-astra", "auto", 48_000, 1)
        self.assertEqual((high["cap"], high["calls"]), (12_000, 1))
        self.assertEqual(auto["calls"], model_runtime.ATTEMPTS)
        self.assertLess(auto["cap"], model_runtime.THINKING_OUTPUT_TOKENS, "Auto trims to the $1 launch limit")
        self.assertAlmostEqual(high["ceilingUsd"], (48_256 * 10 + 12_000 * 50) / 1e6, places=6)

    def test_the_request_level_drives_the_reservation(self):
        runtime = production()
        with mock.patch.dict(os.environ, NO_POLICY):
            auto = runtime.price_quote(request(reasoning="standard"), "openai/gpt-6-sol")
            legacy_quick = runtime.price_quote(request(reasoning="quick"), "openai/gpt-6-sol")
            medium = runtime.price_quote(request(reasoning="standard", level="medium"), "openai/gpt-6-sol")
            thorough = runtime.price_quote(request(reasoning="deep", level="thorough"), "openai/gpt-6-sol")
            deep = runtime.price_quote(request(reasoning="deep"), "openai/gpt-6-sol")
        self.assertEqual(thorough, deep, "Thorough is the deep revise pass")
        self.assertNotEqual(medium, auto)
        self.assertGreater(auto, 0)
        self.assertGreater(legacy_quick, 0)
        self.assertIn("not measured", runtime.ESTIMATE_BASIS)

    def test_an_explicit_level_over_the_limit_is_refused_and_auto_is_not(self):
        runtime = production()
        big = request(reasoning="standard", skills={"text": "s" * 40_000})
        with mock.patch.dict(os.environ, LAUNCH):
            check_level_ceiling(runtime, "openai/gpt-6-astra", big)   # Auto: trimmed, never refused here
            with self.assertRaises(AlphaError) as high:
                check_level_ceiling(runtime, "openai/gpt-6-astra", {**big, "level": "high"})
            with self.assertRaises(AlphaError) as low:
                check_level_ceiling(runtime, "openai/gpt-6-astra", {**big, "level": "low"})
            check_level_ceiling(runtime, "openai/gpt-6-sol", {**request(reasoning="standard"), "level": "high"})
        self.assertEqual((high.exception.status, high.exception.code), (402, "reasoning_level_over_limit"))
        self.assertIn("credits", str(high.exception))
        self.assertIn("Choose a lower level.", str(high.exception))
        self.assertIn("Choose Auto or fewer sources.", str(low.exception), "the lowest level the model lists")
        with mock.patch.dict(os.environ, NO_POLICY):
            check_level_ceiling(runtime, "openai/gpt-6-astra", {**big, "level": "high"})   # no policy: no per-request limit

    def test_research_allowance_counts_toward_the_ceiling(self):
        runtime = production()
        near = request(reasoning="deep", level="thorough", skills={"text": "s" * 36_000})
        with mock.patch.dict(os.environ, LAUNCH):
            check_level_ceiling(runtime, "openai/gpt-6-sol", near)
            with self.assertRaises(AlphaError):
                check_level_ceiling(runtime, "openai/gpt-6-sol", near, extra_bytes=200_000)


class RunRecordTest(unittest.TestCase):
    def run_turn(self, transport, **extra):
        events = []
        runtime = ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"], transport=transport)
        return runtime.start_turn(request(**extra), events.append), events

    def test_the_run_records_the_level_it_asked_for_sent_and_spent(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 900, "completion_tokens_details": {"reasoning_tokens": 700}}
        result, events = self.run_turn(Transport(answer(usage=usage)), reasoning="standard", level="medium")
        block = result["usage"]["reasoning"]
        self.assertEqual({k: block[k] for k in ("requested", "sent", "passes", "reviseFailed", "tokens")}, {"requested": "medium", "sent": "medium", "passes": 1, "reviseFailed": False, "tokens": 700})
        self.assertEqual(block["catalog"]["snapshot"], "2026-09-25")
        started = events[0]
        self.assertEqual((started["type"], started["reasoning"], started["reasoningDetail"]["requested"], started["reasoningDetail"]["sent"]), ("run.started", "standard", "medium", "medium"))
        self.assertNotIn("tokens", started["reasoningDetail"])
        completed = [e for e in events if e["type"] == "run.completed"][0]
        self.assertEqual(completed["usage"]["reasoning"]["tokens"], 700)

    def test_auto_records_the_baseline_and_unknown_reasoning_tokens(self):
        result, events = self.run_turn(Transport(answer()))
        block = result["usage"]["reasoning"]
        self.assertEqual((block["requested"], block["sent"], block["tokens"]), ("auto", "low", None), "a call that omits reasoning tokens makes the sum unknown")

    def test_medium_and_high_make_one_attempt(self):
        transport = Transport(answer("not json"), answer())
        with self.assertRaises(ProviderFailure) as failed:
            self.run_turn(transport, reasoning="standard", level="high")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(failed.exception.usage["reasoning"]["requested"], "high")

    def test_a_level_no_longer_offered_is_refused_before_any_call(self):
        transport = Transport()
        with self.assertRaises(ProviderFailure) as refused:
            self.run_turn(transport, reasoning="standard", level="xhigh")
        self.assertEqual((refused.exception.status, refused.exception.dispatched, transport.calls), (400, False, []))


class ReviseAccountingTest(unittest.TestCase):
    def run_turn(self, *responses):
        transport = Transport(*responses)
        events = []
        runtime = ServerModelRuntime("key", model="anthropic/claude-sonnet-5", models=["anthropic/claude-sonnet-5"], transport=transport)
        return runtime.start_turn(request(reasoning="deep", level="thorough"), events.append), events, transport

    def test_a_costed_revise_that_does_not_parse_keeps_the_known_cost(self):
        result, events, _ = self.run_turn(answer(usage={"prompt_tokens": 1000, "completion_tokens": 400, "cost": 0.01}),
                                          answer("not json", usage={"prompt_tokens": 1200, "completion_tokens": 500, "cost": 0.02}))
        usage = result["usage"]
        self.assertEqual((usage["costUsd"], usage["provenance"], usage["modelRequests"]), (0.03, "provider_reported", 2))
        self.assertEqual((usage["reasoning"]["passes"], usage["reasoning"]["reviseFailed"]), (1, True))
        self.assertTrue(any(e["type"] == "warning.created" and "revise pass did not complete" in e["message"] for e in events))

    def test_a_used_revise_counts_two_passes_and_its_gateway_cost(self):
        revised = answer(usage={"prompt_tokens": 1200, "completion_tokens": 500})
        revised["body"]["providerMetadata"] = {"gateway": {"cost": 0.02, "routing": {"finalProvider": "anthropic"}}}
        result, _, _ = self.run_turn(answer(usage={"prompt_tokens": 1000, "completion_tokens": 400}), revised)
        usage = result["usage"]
        self.assertEqual((usage["reasoning"]["passes"], usage["reasoning"]["reviseFailed"]), (2, False))
        self.assertEqual(usage["provenance"], "provider_reported", "the revise pass's gateway cost is a reported cost, as on the first pass")

    def test_a_revise_cut_at_its_limit_keeps_the_first_draft_and_its_cost(self):
        result, _, _ = self.run_turn(answer(usage={"prompt_tokens": 1000, "completion_tokens": 400, "cost": 0.01}),
                                     answer(usage={"prompt_tokens": 1000, "completion_tokens": 4500, "cost": 0.05}, finish="length"))
        self.assertEqual((result["usage"]["costUsd"], result["usage"]["reasoning"]["reviseFailed"]), (0.06, True))

    def test_a_revise_from_an_unapproved_provider_is_refused_with_its_known_cost(self):
        with self.assertRaises(ProviderFailure) as refused:
            self.run_turn(answer(usage={"prompt_tokens": 1000, "completion_tokens": 400, "cost": 0.01}),
                          answer(usage={"prompt_tokens": 1000, "completion_tokens": 400, "cost": 0.02}, provider="somewhere-else"))
        self.assertEqual((refused.exception.dispatched, refused.exception.cost_usd), (True, 0.03))


class DeadlineTest(unittest.TestCase):
    def runtime(self, transport, model="openai/gpt-6-sol"):
        return ServerModelRuntime("key", model=model, models=[model], transport=transport)

    def test_a_call_gets_only_the_time_left_and_the_tokens_it_can_write(self):
        transport = Transport(answer())
        self.runtime(transport).start_turn(request(reasoning="standard", deadline=time.monotonic() + 35), lambda e: None)
        call = transport.calls[0]
        self.assertTrue(20 <= call["timeout"] <= 30, call["timeout"])
        self.assertLessEqual(call["body"]["max_tokens"], 50 * 30)

    def test_too_little_time_is_refused_before_anything_is_sent(self):
        transport = Transport(answer())
        with self.assertRaises(ProviderFailure) as refused:
            self.runtime(transport).start_turn(request(reasoning="standard", deadline=time.monotonic() + 10), lambda e: None)
        self.assertEqual((refused.exception.dispatched, refused.exception.cost_usd, refused.exception.code, transport.calls), (False, 0.0, "reasoning_time_exhausted", []))
        self.assertIn("enough time left", str(refused.exception))
        # High needs its whole answer's time (12,000 tokens at 50 a second): 100 s left is not enough.
        with self.assertRaises(ProviderFailure):
            self.runtime(Transport(answer())).start_turn(request(reasoning="standard", level="high", deadline=time.monotonic() + 100), lambda e: None)

    def test_plenty_of_time_leaves_the_call_as_it_was(self):
        transport = Transport(answer())
        self.runtime(transport).start_turn(request(reasoning="standard", deadline=time.monotonic() + 280), lambda e: None)
        self.assertEqual((transport.calls[0]["timeout"], transport.calls[0]["body"]["max_tokens"]), (90, 4_500))

    def test_the_deadline_never_changes_the_price(self):
        runtime = production()
        with mock.patch.dict(os.environ, NO_POLICY):
            self.assertEqual(runtime.price_quote(request(reasoning="standard")), runtime.price_quote(request(reasoning="standard", deadline=123.0)))


class TranslationTest(unittest.TestCase):
    def test_requested_level_defaults_to_auto(self):
        self.assertEqual([requested_level(p) for p in ({}, {"reasoning": ""}, {"reasoning": None}, {"reasoning": "high"})], ["auto", "auto", "auto", "high"])

    def test_the_managed_writer_gets_its_pass_and_its_level(self):
        runtime = production()
        cases = {"auto": ("standard", "auto"), "quick": ("quick", "auto"), "standard": ("standard", "auto"), "deep": ("deep", "thorough"),
                 "thorough": ("deep", "thorough"), "none": ("standard", "none"), "medium": ("standard", "medium")}
        for level, expected in cases.items():
            self.assertEqual(translate_reasoning(runtime, "openai/gpt-6-sol", level), expected, level)
        for model, level in (("openai/gpt-6-sol", "xhigh"), ("openai/gpt-6-astra", "none"), ("minimax/minimax-m3", "low"), ("openai/gpt-6-sol", "ultra")):
            with self.subTest(model=model, level=level), self.assertRaises(AlphaError) as refused:
                translate_reasoning(runtime, model, level)
            self.assertEqual((refused.exception.status, str(refused.exception)), (400, "Choose a reasoning level this writer supports."))

    def test_the_fixture_and_cli_keep_their_own_vocabulary(self):
        fixture = FixtureAgentRuntime()
        self.assertEqual([translate_reasoning(fixture, fixture.model, level)[0] for level in ("auto", "thorough", "quick", "standard", "deep")], ["quick", "deep", "quick", "standard", "deep"])
        with self.assertRaises(AlphaError):
            translate_reasoning(fixture, fixture.model, "medium")
        cli = ClaudeCliRuntime.__new__(ClaudeCliRuntime)
        self.assertEqual([translate_reasoning(cli, "claude-code:sonnet", level)[0] for level in ("auto", "thorough", "quick", "high")], ["low", "high", "low", "high"])
        with self.assertRaises(AlphaError):
            translate_reasoning(cli, "claude-code:sonnet", "none")

    def test_automations_store_a_pass_never_a_new_level(self):
        self.assertEqual([campaigns.automation_reasoning(v) for v in (None, "auto", "none", "high", "max", "thorough", "quick", "standard", "deep")],
                         ["standard", "standard", "standard", "standard", "standard", "deep", "quick", "standard", "deep"])


def workspace(model=None):
    state = {"sources": [], "speaker": {"revisions": []}, "variants": []}
    if model is not False:
        state["writerDefaults"] = {"model": model, "decidedBy": "owner", "decidedAt": 1.0}
    return state


class WriterDefaultsTest(unittest.TestCase):
    def test_an_owner_sets_a_priced_managed_model_and_can_clear_it(self):
        runtime = production(prices={**PRICES, "google/gemini-3.1-pro-preview": None})
        state = {}
        self.assertTrue(writer_defaults.apply_action(state, "writer_defaults", {"model": "openai/gpt-6-luna", "confirmed": True}, "owner-1", 5.0, lambda: runtime))
        self.assertEqual(state["writerDefaults"], {"model": "openai/gpt-6-luna", "decidedBy": "owner-1", "decidedAt": 5.0})
        for payload in ({"model": "openai/gpt-6-luna"}, {"model": "openai/gpt-6-luna", "confirmed": "yes"}, {"confirmed": True}):
            with self.subTest(payload=payload), self.assertRaises(AlphaError) as refused:
                writer_defaults.apply_action(state, "writer_defaults", payload, "owner-1", 6.0, lambda: runtime)
            self.assertEqual(refused.exception.status, 400)
        for model in ("vendor/unknown", "google/gemini-3.1-pro-preview", "deterministic-preview", 5):
            with self.subTest(model=model), self.assertRaises(AlphaError) as refused:
                writer_defaults.apply_action(state, "writer_defaults", {"model": model, "confirmed": True}, "owner-1", 6.0, lambda: runtime)
            self.assertEqual((refused.exception.status, str(refused.exception)), (400, "Choose a writer this workspace offers."))
        with self.assertRaises(AlphaError) as none_here:
            writer_defaults.apply_action(state, "writer_defaults", {"model": "openai/gpt-6-luna", "confirmed": True}, "owner-1", 6.0, lambda: None)
        self.assertEqual((none_here.exception.status, str(none_here.exception)), (409, "No managed writer is available here."))
        self.assertTrue(writer_defaults.apply_action(state, "writer_defaults", {"model": None, "confirmed": True}, "owner-1", 7.0, None), "clearing needs no writer")
        self.assertIsNone(state["writerDefaults"]["model"])
        self.assertFalse(writer_defaults.apply_action(state, "language_settings", {}, "owner-1", 8.0, None))

    def test_resolve_uses_the_default_while_it_is_offered_and_says_when_it_is_not(self):
        runtime = production(prices={**PRICES, "google/gemini-3.1-pro-preview": None})
        self.assertEqual(writer_defaults.resolve(workspace("openai/gpt-6-luna"), runtime), ("openai/gpt-6-luna", "workspace", None))
        self.assertEqual(writer_defaults.resolve(workspace(False), runtime), ("openai/gpt-6-sol", "deployment", None))
        self.assertEqual(writer_defaults.resolve({"writerDefaults": "broken"}, runtime), ("openai/gpt-6-sol", "deployment", None))
        for gone in ("vendor/dropped", "google/gemini-3.1-pro-preview"):
            model, source, note = writer_defaults.resolve(workspace(gone), runtime)
            self.assertEqual((model, source), ("openai/gpt-6-sol", "deployment"))
            self.assertEqual(note, f"The workspace default writer {gone} is no longer offered, so Rafii used openai/gpt-6-sol.")

    def test_only_an_owner_decides_and_the_decision_is_audited(self):
        from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
        from postriff_phase2.permissions import classify
        self.assertEqual(classify("writer_defaults"), "owner")
        runtime = production()
        commands = HostedPhase2Commands(clock=lambda: 9.0)
        self.assertIsNone(commands.writers)
        commands.writers = lambda: runtime
        state = commands({"sources": []}, "owner-1", "writer_defaults", {"model": "bytedance/seed-2.1-turbo", "confirmed": True})
        self.assertEqual(state["writerDefaults"], {"model": "bytedance/seed-2.1-turbo", "decidedBy": "owner-1", "decidedAt": 9.0})
        repository = PostgresWorkspaceRepository.__new__(PostgresWorkspaceRepository)
        repository.commands, repository.clock, seen = commands, lambda: 9.0, {}
        repository.command = lambda *args, **kwargs: seen.update(kwargs)
        repository.mutate("w", "t", 3, "writer_defaults", {"model": "bytedance/seed-2.1-turbo", "confirmed": True})
        self.assertEqual(seen["requirement"], "owner")
        self.assertEqual(seen["audit_event"](state), ("writer.default_decided", "writer", {"model": "bytedance/seed-2.1-turbo"}))

    def test_the_hosted_service_validates_against_the_writer_mounted_now(self):
        from test_postriff_account_security import service, verifier
        hosted = service(None, verifier())
        self.assertIsNone(hosted.commands.writers(), "no managed writer mounted")
        runtime = production()
        hosted.ideas.runtimes.append(runtime)
        self.assertIs(hosted.commands.writers(), runtime)

    def test_resolve_writer_follows_auto_and_keeps_an_explicit_choice(self):
        fixture, managed = FixtureAgentRuntime(), production()
        ideas = IdeasService(None, None, runtime=fixture, runtimes=[fixture, managed], researcher=False)
        for requested in (None, "", "auto"):
            self.assertEqual(ideas.resolve_writer(workspace("openai/gpt-6-luna"), requested), (managed, "openai/gpt-6-luna", None))
        self.assertEqual(ideas.resolve_writer(lambda: workspace(False), None), (managed, "openai/gpt-6-sol", None), "state is read only when needed")
        runtime, model, note = ideas.resolve_writer(workspace("vendor/dropped"), "auto")
        self.assertEqual((runtime, model), (managed, "openai/gpt-6-sol"))
        self.assertIn("no longer offered", note)
        self.assertEqual(ideas.resolve_writer(workspace("openai/gpt-6-luna"), "anthropic/claude-sonnet-5"), (managed, "anthropic/claude-sonnet-5", None))
        self.assertEqual(ideas.resolve_writer(workspace("openai/gpt-6-luna"), "deterministic-preview"), (fixture, "deterministic-preview", None))
        self.assertIs(ideas._select_runtime("auto"), managed)
        local = IdeasService(None, None, runtime=fixture, runtimes=[fixture], researcher=False)
        self.assertEqual(local.resolve_writer(lambda: self.fail("no state read without a managed writer"), None), (fixture, "deterministic-preview", None))


class Stop(Exception):
    """Ends a turn at the point a test inspects."""


class Cursor:
    def __init__(self):
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        if "FROM public.pr_conversations" in self.sql:
            return ("c1", "Idea", "u1", 1.0, 1.0, False)
        if "INSERT INTO public.pr_agent_runs" in self.sql:
            return ("run-1",)
        return None


class Repository:
    """Just enough of the workspace repository for a turn to reach its reservation."""

    def __init__(self, state, state_in_transaction=None):
        self.state, self.state_in_transaction, self.commands = state, state_in_transaction, []

    @contextmanager
    def transaction(self, token, workspace_id):
        yield Cursor(), (1, self.state_in_transaction if self.state_in_transaction is not None else self.state, "owner", True, True, True, True), "u1"

    def get(self, workspace_id, token):
        return {"state": self.state, "revision": 1}

    def command(self, *args, **kwargs):
        self.commands.append(args)
        raise Stop("a source would be stored")


class TurnTest(unittest.TestCase):
    PAYLOAD = {"text": "", "intentText": "Announce the spring recital on Saturday.", "sourceIds": [], "destinations": [{"platform": "LinkedIn", "language": "en"}]}

    def setUp(self):
        self.transport = Transport()   # any provider call fails the test: nothing is answered
        self.managed = production(transport=self.transport)
        self.fixture = FixtureAgentRuntime()

    def ideas(self, repository):
        # The real command handler: a quick-start estimate stores its source in a copy of the state, never the workspace.
        return IdeasService(repository, HostedPhase2Commands(time.time), runtime=self.fixture, runtimes=[self.fixture, self.managed], researcher=False)

    def reserved_request(self, ideas, payload, **kwargs):
        """The request and model a turn prices for its reservation (the turn stops there)."""
        seen = {}
        original = self.managed.price_quote

        def capture(request, model=None):
            seen.update(request=request, model=model, price=original(request, model))
            raise Stop()
        with mock.patch.object(self.managed, "price_quote", side_effect=capture), self.assertRaises(Stop):
            ideas.turn("w", "t", "c1", payload, **kwargs)
        return seen

    def test_an_omitted_level_prices_the_same_request_the_estimate_prices(self):
        state = workspace("openai/gpt-6-luna")
        ideas = self.ideas(Repository(state))
        with mock.patch.dict(os.environ, NO_POLICY):
            turn = self.reserved_request(ideas, dict(self.PAYLOAD), _started=1_000.0)
            _, model, estimate = ideas.estimate_request(state, dict(self.PAYLOAD), "turn", "u1")
            estimated = self.managed.price_quote(estimate, model)
        self.assertEqual((turn["model"], model), ("openai/gpt-6-luna", "openai/gpt-6-luna"), "Auto is the workspace default in both")
        self.assertEqual((turn["request"]["reasoning"], turn["request"]["level"], estimate["reasoning"], estimate["level"]), ("standard", "auto", "standard", "auto"))
        self.assertEqual(turn["price"], estimated)
        self.assertEqual(turn["request"]["deadline"], 1_000.0 + model_runtime.REQUEST_SECONDS)
        self.assertNotIn("deadline", estimate)
        self.assertEqual(self.transport.calls, [])

    def test_a_credit_limit_approved_for_a_writer_keeps_that_writer(self):
        ideas = self.ideas(Repository(workspace("openai/gpt-6-luna")))
        authority = {"quoteId": "q1", "requestDigest": "d", "model": "bytedance/seed-2.1-turbo"}
        with mock.patch.dict(os.environ, NO_POLICY):
            seen = self.reserved_request(ideas, dict(self.PAYLOAD), _credit_authority=authority)
        self.assertEqual(seen["model"], "bytedance/seed-2.1-turbo")

    def test_a_default_changed_while_preparing_is_refused_before_any_spend(self):
        ideas = self.ideas(Repository(workspace("openai/gpt-6-luna"), state_in_transaction=workspace("anthropic/claude-sonnet-5")))
        with mock.patch.dict(os.environ, NO_POLICY), self.assertRaises(AlphaError) as refused:
            ideas.turn("w", "t", "c1", dict(self.PAYLOAD))
        self.assertEqual((refused.exception.status, refused.exception.code), (409, "writer_default_changed"))

    def test_an_explicit_level_over_the_limit_is_refused_before_research(self):
        ideas = self.ideas(Repository(workspace("openai/gpt-6-astra")))
        big = {**self.PAYLOAD, "intentText": "x" * 2_000, "reasoning": "high"}
        with mock.patch.dict(os.environ, LAUNCH), mock.patch.object(ideas, "_research", side_effect=AssertionError("research ran")), \
                mock.patch.object(model_runtime.ServerModelRuntime, "_prompt_bytes", return_value=90_000), self.assertRaises(AlphaError) as refused:
            ideas.turn("w", "t", "c1", big)
        self.assertEqual((refused.exception.status, refused.exception.code), (402, "reasoning_level_over_limit"))

    def test_an_unsupported_level_is_refused_at_the_cheap_check(self):
        ideas = self.ideas(Repository(workspace("minimax/minimax-m3")))
        with mock.patch.object(ideas, "_research", side_effect=AssertionError("research ran")), self.assertRaises(AlphaError) as refused:
            ideas.turn("w", "t", "c1", {**self.PAYLOAD, "reasoning": "medium"})
        self.assertEqual((refused.exception.status, str(refused.exception)), (400, "Choose a reasoning level this writer supports."))

    def test_quick_start_refuses_an_explicit_level_over_the_limit_before_storing_the_source(self):
        # A full workspace state: the estimate stores the source in a copy, which the source command needs.
        repository = Repository({**initial_phase2_state("w", "u1", "Owner", "studio", 1.0), **workspace("openai/gpt-6-astra"), "sources": []})
        ideas = self.ideas(repository)
        payload = {"text": "A note about practising slowly.", "confirmUse": True, "ownContent": True, "reasoning": "high", "research": False}
        with mock.patch.dict(os.environ, LAUNCH), mock.patch.object(ideas, "_understand", side_effect=lambda w, t, text, z, r, parsed: (parsed, None)), \
                mock.patch.object(model_runtime.ServerModelRuntime, "_prompt_bytes", return_value=90_000), self.assertRaises(AlphaError) as refused:
            ideas.quick_start("w", "t", 1, payload)
        self.assertEqual((refused.exception.status, refused.exception.code), (402, "reasoning_level_over_limit"))
        self.assertEqual(repository.commands, [], "no source was stored")

    def test_quick_start_forwards_the_callers_level_and_its_clock(self):
        repository = Repository(workspace(False))
        ideas = self.ideas(repository)
        seen = {}

        def turn(workspace_id, token, conversation_id, payload, **kwargs):
            seen.update(payload=payload, kwargs=kwargs)
            raise Stop()
        repository.command = lambda workspace_id, token, revision, command: {"revision": 2, "state": command({"sources": [], "speaker": {"revisions": []}, "variants": [], "brandHub": {}}, "u1")}
        with mock.patch.object(ideas, "_understand", side_effect=lambda w, t, text, z, r, parsed: (parsed, None)), \
                mock.patch.object(ideas, "commands", create=True, new=lambda state, actor, action, payload: state["sources"].append({"id": "s1", "active": True, "facts": [], "kind": "idea"})), \
                mock.patch.object(ideas, "create_conversation", return_value={"conversationId": "c1"}), mock.patch.object(ideas, "turn", side_effect=turn), self.assertRaises(Stop):
            ideas.quick_start("w", "t", 1, {"text": "A note about practising slowly.", "confirmUse": True, "ownContent": True})
        self.assertNotIn("reasoning", seen["payload"], "an absent level stays absent: the turn's Auto decides")
        self.assertIsInstance(seen["kwargs"]["_started"], float)


class CreditIssueTest(unittest.TestCase):
    def test_the_quote_records_the_writer_the_estimate_resolved(self):
        from postriff_phase2.credit_requests import CreditRequests
        managed = production()
        issued = {}

        class Book:
            def issue(self, cur, workspace_id, actor, revision, binding, model, provider, maximum):
                issued.update(model=model)
                return {"quoteId": "q1"}

        @contextmanager
        def transaction(token, workspace_id):
            yield None, (4, {}), "u1"
        ideas = mock.Mock()
        ideas.ledger.credits = Book()
        ideas._wants_image.return_value = False
        ideas._select_runtime.return_value = managed
        ideas.repository.transaction = transaction
        ideas.estimate_request.return_value = (managed, "openai/gpt-6-luna", request(reasoning="standard", level="auto"))
        with mock.patch("postriff_phase2.credit_requests.require"):
            CreditRequests(ideas).issue("w", "session", {"request": {"research": False, "text": "x"}, "expectedRevision": 4, "maxMilliCredits": 900_000})
        self.assertEqual(issued["model"], "openai/gpt-6-luna")


class RunSinkUsageTest(unittest.TestCase):
    def sink(self, running):
        executed = []

        class Cur:
            def execute(self, sql, params=None):
                executed.append((sql, params))

            def fetchone(self):
                return ("running",) if running else ("cancelled",)

        class DB:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def cursor(self):
                return self

            __enter__ = __enter__

        cursor = Cur()

        @contextmanager
        def db():
            yield type("Conn", (), {"cursor": lambda self: _Ctx(cursor)})()
        service = mock.Mock()
        service.repository.connection_factory = lambda: _Ctx(type("Conn", (), {"cursor": lambda self: _Ctx(cursor)})())
        return RunSink(service, "w", "c", "r1", {"reservationId": "res", "paid": True, "parsed": {"intent": "draft"}, "destinations": [], "model": "m"}), executed

    def test_a_failed_run_keeps_what_the_runtime_recorded_on_every_branch(self):
        usage = {"reasoning": {"requested": "high", "tokens": 12}}
        for running in (True, False):
            sink, executed = self.sink(running)
            sink.fail("The writer did not finish.", known_cost_usd=0.01, usage=usage)
            merged = [params for sql, params in executed if sql.startswith("UPDATE public.pr_agent_runs SET usage=usage ||")]
            self.assertEqual([json.loads(params[0]) for params in merged], [usage], running)


class _Ctx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *_):
        return False


class SideCallTest(unittest.TestCase):
    def test_a_reply_on_a_budget_only_model_gets_headroom_and_no_sampling(self):
        from postriff_phase2.learning_model import GatewayCall
        bodies = []

        def transport(method, url, headers=None, body=None):
            bodies.append(body)
            return {"status": 200, "body": {"choices": [{"message": {"content": "{}"}}], "usage": {}}}
        GatewayCall("key", model="minimax/minimax-m3", transport=transport, drafting=True)("system", "user", {"type": "object"})
        self.assertEqual(bodies[0]["max_tokens"], 4_000, "its reasoning shares max_tokens")
        self.assertNotIn("temperature", bodies[0])
        self.assertNotIn("reasoning", bodies[0], "no effort scale: nothing is sent")
        GatewayCall("key", model="anthropic/claude-haiku-4.5", transport=transport, drafting=True)("system", "user", {"type": "object"})
        self.assertEqual((bodies[1]["max_tokens"], bodies[1]["temperature"]), (1_200, 0.2), "a model that does not think is unchanged")

    def test_a_weekly_writer_run_has_room_for_two_thinking_attempts(self):
        from postriff_phase2.coworker import service
        self.assertEqual(service.WRITER_RUN_SECONDS, 195)


if __name__ == "__main__":
    unittest.main()
