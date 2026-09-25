"""Customer-visible plan names: an internal note on a pr_plan_terms label never reaches the page or an email."""
import unittest

from postriff_phase2.billing import plan_display_label


class PlanDisplayLabel(unittest.TestCase):
    def test_internal_parenthetical_note_is_dropped(self):
        self.assertEqual(plan_display_label("Studio Assist (bounded-batch experiment)"), "Studio Assist")

    def test_ordinary_names_are_unchanged(self):
        for label in ("Studio", "14-day trial", "Pro (v2) Plus"):
            self.assertEqual(plan_display_label(label), label)

    def test_missing_or_bare_labels_fall_back_to_the_product_name(self):
        self.assertEqual(plan_display_label(None), "Rafii")
        self.assertEqual(plan_display_label("  "), "Rafii")
        self.assertEqual(plan_display_label("(x)"), "(x)")


if __name__ == "__main__":
    unittest.main()
