"""English contractions in the meaning check (brand intelligence HUM-2).

"will not" → "won't" and "we will" → "we'll" keep a plan a plan; only a plan that now reads as done is a status change.
"""
import unittest

from postriff_phase2.coworker import humanizer


def codes(source, candidate):
    return [item["code"] for item in humanizer.meaning_diff(source, candidate)]


class Contractions(unittest.TestCase):
    def test_contracted_future_is_still_planned(self):
        self.assertEqual(codes("We will not livestream the concert this year.", "We won't livestream the concert this year."), [])
        self.assertEqual(codes("We will share the date soon.", "We'll share the date soon."), [])
        self.assertEqual(codes("We will share the date soon.", "We’ll share the date soon."), [])

    def test_a_plan_that_now_reads_as_done_is_still_reported(self):
        self.assertIn("status_changed", codes("We will launch the course in autumn.", "We launched the course in autumn."))
        self.assertIn("status_changed", codes("We plan to launch the new course in autumn.", "The new course launches in autumn."))

    def test_a_lost_negation_is_still_reported(self):
        self.assertIn("negation_lost", codes("We will not livestream the concert.", "We'll livestream the concert."))



class AddedApologies(unittest.TestCase):
    """An apology the source did not make is an added feeling (editorial contract: add no feeling)."""

    def test_an_added_apology_is_reported(self):
        self.assertIn("feeling_added", codes("We will not livestream the concert this year.", "We're sorry to say we will not livestream the concert this year."))
        self.assertIn("feeling_added", codes("今晚冇直播。", "好抱歉，今晚冇直播。"))

    def test_an_apology_the_source_already_made_is_kept_without_a_warning(self):
        self.assertEqual(codes("Sorry, the class is full.", "Sorry, this class is full."), [])


if __name__ == "__main__":
    unittest.main()
