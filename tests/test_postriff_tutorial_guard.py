"""A how-to that names no steps gets a reminder (never a block); keyed on the type's own tested_steps rule."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import content_types as ct  # noqa: E402
from postriff_phase2 import skills  # noqa: E402


def selecting(content_type_id):
    state = {"brief": {"sourceIds": [], "revision": 1}, "variants": []}
    ct.ensure_content_state(state)
    ct.apply_content_action(state, "content_install_pack", {"packId": ct.CREATOR_PACK_ID, "version": ct.CREATOR_PACK_VERSION}, "u", 1.0)
    item = ct.definition(state, content_type_id)
    ct.apply_content_action(state, "content_select", {"contentTypeId": content_type_id, "contentTypeVersion": item["version"]}, "u", 1.0)
    return state


class Guard(unittest.TestCase):
    def test_types_that_require_tested_steps_ask_when_nothing_is_supplied(self):
        for type_id in ("pack.creator:tutorial_how_to", "postriff:teach"):
            rules = ct.selected_rule_ids(selecting(type_id))
            self.assertEqual(ct.missing_tutorial_input(rules, "A carousel for first-timers on how to wedge clay.", {"sources": []}), ct.TUTORIAL_NEEDS, type_id)

    def test_other_types_and_no_selection_never_ask(self):
        self.assertEqual(ct.missing_tutorial_input(ct.selected_rule_ids(selecting("pack.creator:personal_reflection")), "Wedging.", {"sources": []}), "")
        self.assertEqual(ct.selected_rule_ids({"contentSystem": {"selection": {"contentTypeId": "unclassified"}}}), ())
        self.assertEqual(ct.selected_rule_ids({}), ())

    def test_approved_facts_or_steps_in_the_message_are_enough(self):
        rules = ("tested_steps",)
        self.assertEqual(ct.missing_tutorial_input(rules, "Wedging.", {"sources": [{"facts": [{"id": "f1"}]}]}), "")
        for idea in ("How I wedge:\n1. Cut the clay\n2. Slam the halves together",
                     "Steps:\n- cut\n- slam",
                     "First cut the block, then slam it, then press forward.",
                     "揉土：首先把泥切半，然後用力摔合，最後向前壓揉。"):
            self.assertEqual(ct.missing_tutorial_input(rules, idea, {"sources": []}), "", idea)
        # One sequence word is not a method.
        self.assertNotEqual(ct.missing_tutorial_input(rules, "I teach wedging and then centering.", {"sources": []}), "")


class NamespacedTypesBindClaimRules(unittest.TestCase):
    def test_catalog_ids_match_by_local_name(self):
        for type_id in ("pack.creator:article_news_commentary", "pack.creator:deep_point_of_view", "pack.creator:product_feature_launch", "postriff:promote"):
            self.assertTrue(skills.cites_sources("draft", type_id), type_id)
        for type_id in ("pack.creator:personal_reflection", "postriff:teach", None, 7):
            self.assertFalse(skills.cites_sources("draft", type_id), type_id)
        self.assertTrue(skills.cites_sources("research", None))


if __name__ == "__main__":
    unittest.main()
