"""Analysis quality stops (brand intelligence): ranked models per stop from several makers, availability, the
recommended model, "Advanced · choose AI provider", defaults and the model catalogue field."""
import json
import os
import unittest
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import analysis_quality as Q
from postriff_phase2.model_runtime import ServerModelRuntime

CHEAP, MIDDLE, STRONG = "openai/gpt-4.1-mini", "anthropic/claude-sonnet-5", "anthropic/claude-opus-5.5"
OTHER_CHEAP = "google/gemini-2.5-flash"
MAPPING = {Q.ENV: json.dumps({"economy": [CHEAP, OTHER_CHEAP], "balanced": MIDDLE, "best": [STRONG]})}


def runtime(*models, prices=None):
    return ServerModelRuntime("SYNTHETIC_KEY", model=models[0], models=list(models), prices=prices, transport=lambda *a, **k: None)


class Configuration(unittest.TestCase):
    def test_defaults_run_cheapest_to_most_thorough(self):
        self.assertEqual(Q.STOPS, ("economy", "balanced", "best"))
        self.assertEqual(Q.configured({}), Q.DEFAULT_MODELS)
        self.assertEqual(Q.DEFAULT_STOP, "balanced")
        self.assertTrue(all(isinstance(ids, list) and ids for ids in Q.DEFAULT_MODELS.values()))

    def test_an_operator_sets_a_ranked_list_or_one_model_per_stop(self):
        self.assertEqual(Q.configured(MAPPING), {"economy": [CHEAP, OTHER_CHEAP], "balanced": [MIDDLE], "best": [STRONG]})
        mixed = Q.configured({Q.ENV: json.dumps({"best": ["x/strong", "x/strong", " ", 5], "other": "ignored"})})
        self.assertEqual(mixed, {**Q.DEFAULT_MODELS, "best": ["x/strong"]}, "duplicates and junk are dropped; other stops keep defaults")

    def test_an_unreadable_setting_keeps_the_defaults(self):
        for raw in ("not json", "[1, 2]", json.dumps({"economy": 5, "balanced": "  ", "best": []})):
            self.assertEqual(Q.configured({Q.ENV: raw}), Q.DEFAULT_MODELS, raw)

    def test_maker_comes_from_the_model_id(self):
        self.assertEqual((Q.maker(STRONG), Q.maker(OTHER_CHEAP), Q.maker("bare"), Q.maker(None)), ("anthropic", "google", "", ""))


class Availability(unittest.TestCase):
    def test_a_stop_recommends_its_first_offered_model_and_lists_every_choice(self):
        stops = Q.stops(runtime(OTHER_CHEAP, STRONG), MAPPING)
        economy, balanced, best = stops
        self.assertEqual((economy["available"], economy["model"]), (True, OTHER_CHEAP), "the first listed model is not offered, so the next one is recommended")
        self.assertEqual([(c["model"], c["maker"], c["available"]) for c in economy["choices"]], [(CHEAP, "openai", False), (OTHER_CHEAP, "google", True)])
        self.assertEqual((balanced["available"], balanced["model"]), (False, MIDDLE))
        self.assertEqual((best["available"], best["model"]), (True, STRONG))

    def test_a_model_must_be_listed_and_priced_to_be_offered(self):
        unpriced = Q.stops(runtime(CHEAP, "x/unpriced", prices={CHEAP: (0.4, 1.6)}), {Q.ENV: json.dumps({"economy": CHEAP, "best": "x/unpriced"})})
        self.assertEqual([s["available"] for s in unpriced], [True, False, False])
        self.assertEqual([s["available"] for s in Q.stops(None, MAPPING)], [False, False, False])

    def test_the_default_stop_is_balanced_else_the_cheaper_offered_one(self):
        self.assertEqual(Q.default_stop(runtime(CHEAP, MIDDLE, STRONG), MAPPING), "balanced")
        self.assertEqual(Q.default_stop(runtime(CHEAP, STRONG), MAPPING), "economy")
        self.assertEqual(Q.default_stop(runtime(STRONG), MAPPING), "best")
        self.assertIsNone(Q.default_stop(runtime("x/elsewhere", prices={"x/elsewhere": (1, 1)}), MAPPING))


class Choosing(unittest.TestCase):
    def test_without_a_named_model_the_stop_runs_its_recommended_model(self):
        offered = runtime(CHEAP, OTHER_CHEAP, MIDDLE)
        self.assertEqual(Q.model_for(offered, "economy", MAPPING), ("economy", CHEAP))
        self.assertEqual(Q.model_for(offered, None, MAPPING), ("balanced", MIDDLE))

    def test_advanced_honours_a_named_model_of_the_stop_exactly(self):
        offered = runtime(CHEAP, OTHER_CHEAP, MIDDLE)
        self.assertEqual(Q.model_for(offered, "economy", MAPPING, model=OTHER_CHEAP), ("economy", OTHER_CHEAP))

    def test_advanced_refuses_rather_than_replaces(self):
        offered = runtime(CHEAP, MIDDLE)                                    # Google's economy model is not offered here
        with self.assertRaises(AlphaError) as caught:
            Q.model_for(offered, "economy", MAPPING, model=OTHER_CHEAP)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "analysis_model_unavailable"))
        with self.assertRaises(AlphaError) as caught:
            Q.model_for(offered, "economy", MAPPING, model=STRONG)          # a model of another stop
        self.assertEqual((caught.exception.status, caught.exception.code), (400, "analysis_model_invalid"))
        for bad in ("no-maker", 7, "x/" + "y" * 300):
            with self.assertRaises(AlphaError) as caught:
                Q.model_for(offered, "economy", MAPPING, model=bad)
            self.assertEqual(caught.exception.code, "analysis_model_invalid")

    def test_unavailable_or_unknown_stops_are_refused(self):
        offered = runtime(CHEAP, MIDDLE)
        with self.assertRaises(AlphaError) as caught:
            Q.model_for(offered, "best", MAPPING)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "analysis_quality_unavailable"))
        with self.assertRaises(AlphaError) as caught:
            Q.model_for(offered, "premium", MAPPING)
        self.assertEqual((caught.exception.status, caught.exception.code), (400, "analysis_quality_invalid"))

    def test_with_no_stop_offered_the_runtime_default_runs_as_before(self):
        bare = runtime("x/elsewhere", prices={"x/elsewhere": (1, 1)})
        self.assertEqual(Q.model_for(bare, None, MAPPING), (None, "x/elsewhere"))
        with self.assertRaises(AlphaError) as caught:
            Q.model_for(bare, None, MAPPING, model=STRONG)
        self.assertEqual(caught.exception.code, "analysis_model_unavailable")


class Catalogue(unittest.TestCase):
    def test_the_model_catalogue_carries_the_stops_for_the_slider(self):
        from postriff_phase2.ideas import IdeasService
        managed = runtime(CHEAP, OTHER_CHEAP, MIDDLE, STRONG)
        ideas = IdeasService(None, None, runtime=managed, runtimes=[managed], researcher=False)
        with mock.patch.dict(os.environ, MAPPING):
            catalog = ideas.model_catalog()
        self.assertEqual([(s["id"], s["model"], s["available"]) for s in catalog["analysisQuality"]],
                         [("economy", CHEAP, True), ("balanced", MIDDLE, True), ("best", STRONG, True)])
        self.assertEqual([c["maker"] for c in catalog["analysisQuality"][0]["choices"]], ["openai", "google"])
        self.assertEqual(catalog["defaultAnalysisQuality"], "balanced")


if __name__ == "__main__":
    unittest.main()
