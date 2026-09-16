import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from postriff_phase2.content_types import CATALOG_VERSION, CREATOR_TYPES, FORMAT_IDS, content_preflight, digest, ensure_content_state, export_template, projection, public_catalog, recommendations, resolve_catalog
from postriff_phase2.store import Phase2Store
from test_postriff_phase2 import P2Journey


class ContentTypeAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1_800_000_000.0
        self.store = Phase2Store(Path(self.temp.name) / "content.db", clock=lambda: self.now)
        self.journey = P2Journey(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_creator_pack_and_formats_are_exact_versioned_and_namespaced(self):
        self.assertEqual(len(CREATOR_TYPES), 11)
        self.assertEqual(len({item["id"] for item in CREATOR_TYPES}), 11)
        self.assertTrue(all(item["id"].startswith("pack.creator:") for item in CREATOR_TYPES))
        self.assertEqual(FORMAT_IDS, {"short_text", "image_caption", "quote_card", "carousel", "article", "short_video", "long_video", "story", "community_post", "poll"})
        self.journey.act("p2_content_install_pack", packId="pack.creator", version="1.0.0")
        creator = [item for item in self.journey.state["contentTypes"]["catalog"] if item["id"].startswith("pack.creator:")]
        self.assertEqual(len(creator), 11)
        self.assertEqual(self.journey.state["contentTypes"]["catalogVersion"], CATALOG_VERSION)
        self.assertEqual(len(public_catalog()), 16)
        self.assertTrue(all("instructions" not in item for item in public_catalog()))

    def test_unrelated_workspace_gets_small_role_catalog_without_creator_pack(self):
        self.journey.act("p2_content_context", role="restaurant", goals=["weekly menu"], audience="Local diners", sources=["menu"], channels=["Instagram"])
        suggestions = self.journey.state["contentTypes"]["suggestions"]
        self.assertGreaterEqual(len(suggestions), 3)
        self.assertLessEqual(len(suggestions), 4)
        self.assertTrue(all(item["contentTypeId"].startswith("pack.restaurant:") for item in suggestions))
        self.assertFalse(any(item["id"].startswith("pack.creator:") for item in self.journey.state["contentTypes"]["catalog"]))
        self.assertEqual(recommendations(copy.deepcopy(self.journey.state)), recommendations(copy.deepcopy(self.journey.state)))

    def test_legacy_migration_and_type_change_preserve_sources_and_custom_variants(self):
        self.journey.setup().act("generate", platform="LinkedIn", language="English")
        variant = self.journey.state["variants"][0]
        self.assertEqual(variant["contentTypeId"], "unclassified")
        self.journey.act("variant_edit", variantId=variant["id"], variantRevision=variant["revision"], text=variant["text"] + "\n\nA custom ending.")
        variant = self.journey.state["variants"][0]
        source_ids = copy.deepcopy(self.journey.state["brief"]["sourceIds"])
        self.journey.act("p2_content_select", contentTypeId="postriff:teach", contentTypeVersion="1.0.0", formatId="carousel")
        self.journey.act("p2_content_format", formatId="short_video")
        self.journey.act("p2_content_select", contentTypeId="postriff:story", contentTypeVersion="1.0.0")
        self.assertEqual(self.journey.state["brief"]["sourceIds"], source_ids)
        self.assertEqual(self.journey.state["variants"][0]["id"], variant["id"])
        self.assertEqual(self.journey.state["contentTypes"]["selection"]["formatId"], "short_video")
        self.assertEqual(self.journey.state["contentTypes"]["selection"]["transformation"]["preservedVariantIds"], [variant["id"]])

    def test_guided_interview_is_one_question_at_a_time_and_requires_exact_review(self):
        self.journey.act("p2_content_interview_start", path="guided")
        for index, answer in enumerate(("A weekly studio build log", "Independent creators should understand the tradeoff", "A changelog and screenshot")):
            question = self.journey.state["contentTypes"]["interview"]
            self.assertEqual(question["index"], index)
            with self.assertRaises(Exception):
                self.journey.act("p2_content_interview_answer", questionKey="wrong", answer=answer)
            self.journey.refresh().act("p2_content_interview_answer", questionKey=question["questionKey"], answer=answer, finish=index == 2)
        proposal = self.journey.state["contentTypes"]["proposal"]
        self.assertEqual(proposal["status"], "needs_review")
        self.assertEqual(len(proposal["fixtureExamples"]), 2)
        with self.assertRaises(Exception):
            self.journey.act("p2_content_proposal_save", confirmed=True, proposalDigest="forged")
        self.journey.refresh().act("p2_content_proposal_test", idea="A fictional workshop release")
        proposal = self.journey.state["contentTypes"]["proposal"]
        self.journey.act("p2_content_proposal_save", confirmed=True, proposalDigest=proposal["proposalDigest"])
        saved_id = self.journey.state["contentTypes"]["proposal"]["savedTypeId"]
        self.assertTrue(saved_id.startswith("workspace_"))
        self.assertIn(saved_id, {item["id"] for item in self.journey.state["contentTypes"]["catalog"]})

    def test_all_creation_paths_produce_reviewable_proposals(self):
        cases = (
            ("example", {"example": "A concrete moment, what changed, and what comes next."}),
            ("adapt", {"baseTypeId": "postriff:teach"}),
            ("manual", {"definition": {"name": "Field observation", "purpose": "Capture a useful observation."}}),
        )
        for path, payload in cases:
            with self.subTest(path=path):
                self.journey.act("p2_content_interview_start", path=path, **payload)
                self.assertEqual(self.journey.state["contentTypes"]["proposal"]["status"], "needs_review")

    def test_private_templates_are_default_private_and_workspace_isolated(self):
        self.journey.act("p2_template_create", name="My teaching note", description="Private defaults", contentTypeId="postriff:teach", contentTypeVersion="1.0.0", overrides={"formatId": "carousel"})
        template = self.journey.state["contentTypes"]["templates"][0]
        self.assertEqual(template["visibility"], "private")
        other = P2Journey(self.store)
        self.assertEqual(other.state["contentTypes"]["templates"], [])
        with self.assertRaises(Exception):
            other.act("p2_template_archive", templateId=template["id"], archived=True)
        self.journey.act("p2_template_duplicate", templateId=template["id"], name="My copy")
        self.assertEqual(len(self.journey.state["contentTypes"]["templates"]), 2)
        self.journey.act("p2_template_edit", templateId=template["id"], expectedTemplateRevision=1, name="My edited teaching note", visibility="workspace", overrides={"formatId": "article"})
        edited = self.journey.state["contentTypes"]["templates"][0]
        self.assertEqual((edited["revision"], len(edited["versions"]), edited["overrides"]["formatId"]), (2, 2, "article"))
        exported = export_template(copy.deepcopy(self.journey.state), template["id"], edited["ownerUserId"])
        self.assertEqual(exported["template"]["contentTypeVersion"], "1.0.0")
        self.assertNotIn("instructions", exported["contentType"])
        self.journey.act("p2_template_archive", templateId=template["id"], expectedTemplateRevision=2, archived=True)
        self.journey.act("p2_template_archive", templateId=template["id"], expectedTemplateRevision=3, archived=False)
        self.assertFalse(self.journey.state["contentTypes"]["templates"][0]["archived"])

    def test_quote_and_article_rules_remain_visible_and_block_missing_sources(self):
        state = copy.deepcopy(self.journey.state)
        ensure_content_state(state)["installedPacks"] = [{"id": "pack.creator", "version": "1.0.0"}]
        ensure_content_state(state)["selection"].update({"contentTypeId": "pack.creator:quick_thought_quote", "contentTypeVersion": "1.0.0", "formatId": "quote_card"})
        self.assertEqual(content_preflight(state)[0]["ruleId"], "quote_attribution")
        ensure_content_state(state)["selection"].update({"contentTypeId": "pack.creator:article_news_commentary", "contentTypeVersion": "1.0.0", "formatId": "article"})
        self.assertIn("source_required", {item["ruleId"] for item in content_preflight(state)})


if __name__ == "__main__":
    unittest.main()
