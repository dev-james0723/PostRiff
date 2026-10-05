"""Offline scope/meaning regressions for approved Genome prompt projection."""
import copy
import unittest

from postriff_alpha.domain import initial_state
from postriff_phase2 import memory
from postriff_phase2.contracts import digest
from postriff_phase2.model_runtime import ServerModelRuntime


def workspace(statements):
    state = initial_state("genome-scope-regression-only")
    state["memoryEgress"] = {"cloud": True}
    state["growthConsent"] = {"routes": ["test"]}
    source = {"id": "sample", "active": True, "selected": True, "revision": 1, "useGrants": [{"purpose": "analysis"}]}
    state["sources"] = [source]
    state["brandHub"]["genome"] = {
        "status": "approved", "statements": statements,
        "evidenceBindings": [{"id": source["id"], "revision": 1, "grantsDigest": digest(source["useGrants"])}],
        "consentDigest": digest(state["growthConsent"]),
    }
    return state


def statement(text="GENOME_MARKER", kind="performance", **changes):
    return {"id": text, "text": text, "kind": kind, "grade": "supported", **changes}


def projected(state, platform="LinkedIn", language="en", content="promotion", campaign="campaign-a", channel="account-a"):
    return memory.projection(state, "cloud", [{"platform": platform, "language": language, "channelId": channel}],
                             content, campaign_id=campaign)


def prompt(shared):
    return ServerModelRuntime._system_prompt({"memory": shared["files"]})


class GenomeMemoryScope(unittest.TestCase):
    def test_matching_performance_is_strategy_never_voice_or_identity(self):
        state = workspace([statement(cohort={"platform": "LinkedIn", "language": "en", "connectionId": "account-a"},
                                     scope={"contentTypeId": "promotion", "campaignId": "campaign-a"})])
        before = copy.deepcopy(state)
        shared = projected(state)
        files = {f["name"]: f["body"] for f in shared["files"]}
        self.assertIn("GENOME_MARKER", files["STRATEGY.md"])
        self.assertIn("LinkedIn", files["STRATEGY.md"])
        self.assertIn("campaign-a", files["STRATEGY.md"])
        self.assertIn("not voice traits, identity facts", files["STRATEGY.md"])
        self.assertNotIn("GENOME_MARKER", files["VOICE.md"])
        self.assertNotIn("GENOME_MARKER", files["IDENTITY.md"])
        self.assertIn("GENOME_MARKER", prompt(shared))
        self.assertEqual(state, before)

    def test_any_mismatched_scope_dimension_excludes_statement_from_final_prompt(self):
        state = workspace([statement(cohort={"platform": "LinkedIn", "language": "en", "connectionId": "account-a"},
                                     scope={"contentTypeId": "promotion", "campaignId": "campaign-a"})])
        for changes in ({"platform": "Instagram"}, {"language": "zh-Hant"}, {"content": "reflection"},
                        {"campaign": "campaign-b"}, {"campaign": None}, {"channel": "account-b"}):
            with self.subTest(changes=changes):
                shared = projected(state, **changes)
                self.assertNotIn("GENOME_MARKER", prompt(shared))
                self.assertNotIn("STRATEGY.md", [f["name"] for f in shared["files"]])

    def test_global_writing_and_strategy_remain_separate_across_destinations(self):
        state = workspace([statement("GLOBAL_WRITING", "writing"), statement("GLOBAL_STRATEGY")])
        for platform in ("LinkedIn", "Instagram"):
            files = {f["name"]: f["body"] for f in projected(state, platform=platform)["files"]}
            self.assertIn("GLOBAL_WRITING", files["VOICE.md"])
            self.assertNotIn("GLOBAL_STRATEGY", files["VOICE.md"])
            self.assertIn("GLOBAL_STRATEGY", files["STRATEGY.md"])
            self.assertNotIn("GLOBAL_WRITING", files["IDENTITY.md"])

    def test_later_scope_cannot_override_original_evidence_cohort(self):
        state = workspace([statement(cohort={"platform": "LinkedIn"}, scope={"platform": "Instagram"})])
        for platform in ("LinkedIn", "Instagram"):
            self.assertNotIn("GENOME_MARKER", prompt(projected(state, platform=platform)))

    def test_unknown_destination_withholds_scoped_statement_and_mixed_turn_keeps_label(self):
        state = workspace([statement(cohort={"platform": "LinkedIn"})])
        self.assertNotIn("GENOME_MARKER", prompt(memory.projection(state, "cloud")))
        shared = memory.projection(state, "cloud", [{"platform": "Instagram", "language": "en"}, {"platform": "LinkedIn", "language": "en"}])
        self.assertIn("[LinkedIn · all languages] GENOME_MARKER", prompt(shared))

    def test_consent_revocation_stale_evidence_and_unsupported_claims_stay_excluded(self):
        for change in ("cloud_off", "growth_consent", "source_revision", "unsupported"):
            state = workspace([statement()])
            if change == "cloud_off":
                state["memoryEgress"]["cloud"] = False
            elif change == "growth_consent":
                state["growthConsent"] = {}
            elif change == "source_revision":
                state["sources"][0]["revision"] = 2
            else:
                state["brandHub"]["genome"]["statements"][0]["grade"] = "limited"
            with self.subTest(change=change):
                self.assertNotIn("GENOME_MARKER", prompt(projected(state)))

    def test_no_genome_keeps_existing_core_fragments_without_strategy(self):
        state = workspace([])
        with_empty_genome = projected(state)
        del state["brandHub"]["genome"]
        without_genome = projected(state)
        self.assertEqual(with_empty_genome, without_genome)
        self.assertEqual([f["name"] for f in without_genome["files"]], list(memory.PROMPT_FILES))

    def test_memory_page_marks_optional_strategy_as_shared_not_private_display_only(self):
        state = workspace([statement(cohort={"platform": "LinkedIn"})])
        files = {f["name"]: f["body"] for f in memory.render_files(state)}
        self.assertIn("GENOME_MARKER", files["STRATEGY.md"])
        self.assertIn("STRATEGY.md", memory.egress_summary(state)["sharedFiles"])
        del state["brandHub"]["genome"]
        self.assertEqual(memory.egress_summary(state)["sharedFiles"], list(memory.PROMPT_FILES))


if __name__ == "__main__":
    unittest.main()
