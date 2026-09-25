"""No draft comes from templates unless the person chose them: a request that names no model uses the mounted managed
cloud writer; the fixture is reached only by its own id ("Templates (no AI model)")."""
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.ideas import IdeasService
from postriff_phase2.model_runtime import ServerModelRuntime


class Subscription:
    """A person's own CLI plan: cloud, but not a Rafii-managed paid writer."""
    cost_class, provider_class, provider = "subscription", "cloud", "claude-code"

    def owns(self, model_id):
        return model_id == "claude-code:sonnet"

    def list_supported_models(self):
        return [{"id": "claude-code:sonnet", "label": "Claude Code", "qualified": True, "costClass": "subscription", "route": "claude-code"}]

    def list_supported_reasoning(self):
        return [{"id": "quick", "available": True}]

    def describe(self):
        return None


def service(*extra):
    fixture = FixtureAgentRuntime()
    return IdeasService(None, None, runtime=fixture, runtimes=[fixture, *extra], researcher=False), fixture


class DefaultWriterTest(unittest.TestCase):
    def test_without_a_managed_writer_the_default_stays_local(self):
        ideas, fixture = service()
        self.assertIs(ideas._select_runtime(None), fixture)
        self.assertIs(ideas._select_runtime(""), fixture)
        ideas, fixture = service(Subscription())
        self.assertIs(ideas._select_runtime(None), fixture, "a person's own CLI plan is never chosen for them")

    def test_no_model_means_the_managed_writer_once_it_is_mounted(self):
        managed = ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])
        ideas, fixture = service(managed)
        self.assertIs(ideas._select_runtime(None), managed)
        self.assertIs(ideas._select_runtime(""), managed)
        self.assertIs(ideas._select_runtime("openai/gpt-6-sol"), managed)
        # An explicit choice of templates still reaches the fixture; an unknown writer is refused, never substituted.
        self.assertIs(ideas._select_runtime("deterministic-preview"), fixture)
        with self.assertRaises(AlphaError):
            ideas._select_runtime("unknown/model")

    def test_catalog_names_templates_and_drops_the_placeholder_next_to_a_real_writer(self):
        ideas, _ = service()
        ids = {m["id"]: m for m in ideas.model_catalog()["models"]}
        self.assertEqual(ids["deterministic-preview"]["label"], "Templates (no AI model)")
        self.assertIn("server-openai", ids, "with no managed writer the placeholder still says one is coming")
        managed = ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])
        ideas, _ = service(managed)
        catalog = ideas.model_catalog()
        self.assertEqual({m["id"] for m in catalog["models"]}, {"deterministic-preview", "openai/gpt-6-sol"})
        self.assertEqual(catalog["reasoning"], managed.list_supported_reasoning())


class SourceCampaignWriterTest(unittest.TestCase):
    def test_source_to_campaign_sends_no_model_so_it_gets_the_default_writer(self):
        # The agent tool and the route pass no model; the service must not pick one of its own (templates) either.
        from test_rafii_flag_fixes import SourceCampaignRepeatTest
        harness = SourceCampaignRepeatTest("record_id")
        record = {"id": harness.record_id(), "status": "drafting", "drafts": [], "sourceId": "s1", "campaignId": "c1", "conversationId": "conv-1"}
        _result, ideas_mock = harness.run_with(record)
        self.assertIsNone(ideas_mock.turn.call_args.args[3]["model"])
        managed = ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])
        ideas, _ = service(managed)
        self.assertIs(ideas._select_runtime(ideas_mock.turn.call_args.args[3]["model"]), managed)


if __name__ == "__main__":
    unittest.main()
