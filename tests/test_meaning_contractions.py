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



class NamesAtTheStartOfASentence(unittest.TestCase):
    """One capitalised word opening a sentence is not read as a name, so a name that moves into or out of that position
    is still the same name. Found in a live edit: "Fees for January" → "January fees" was reported as a changed name."""

    def test_a_name_moved_to_the_start_of_a_sentence_is_not_missing(self):
        source = "Lessons resume on 2 January. Fees for January are due by 31 December."
        self.assertNotIn("name_changed", codes(source, "Lessons will resume on 2 January. January fees are due by 31 December."))

    def test_a_name_moved_out_of_the_opening_position_is_not_added(self):
        source = "January fees are due by 31 December."
        self.assertNotIn("name_added", codes(source, "Please pay the fees for January by 31 December."))

    def test_a_name_that_is_really_gone_is_still_reported(self):
        self.assertIn("name_changed", codes("Ask Maria about the recital.", "Ask the office about the recital."))
        self.assertIn("name_changed", codes("Tickets are with Maria Chen at the door.", "Tickets are with our teacher at the door."))


class AddedApologies(unittest.TestCase):
    """An apology the source did not make is an added feeling (editorial contract: add no feeling)."""

    def test_an_added_apology_is_reported(self):
        self.assertIn("feeling_added", codes("We will not livestream the concert this year.", "We're sorry to say we will not livestream the concert this year."))
        self.assertIn("feeling_added", codes("今晚冇直播。", "好抱歉，今晚冇直播。"))

    def test_an_apology_the_source_already_made_is_kept_without_a_warning(self):
        self.assertEqual(codes("Sorry, the class is full.", "Sorry, this class is full."), [])


if __name__ == "__main__":
    unittest.main()
