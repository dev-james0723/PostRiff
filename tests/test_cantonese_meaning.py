"""Cantonese negation in the meaning check (brand intelligence HUM-2).

唔 and 冇 are negation; 「唔該」 (please, thanks) and 「唔好意思」 (excuse me, sorry) are courtesy words that contain 唔
and must not count as a negation that a rewrite lost. 「唔應該」 (should not) still does.
"""
import unittest

from postriff_phase2.coworker import humanizer


def codes(source, candidate):
    return [item["code"] for item in humanizer.meaning_diff(source, candidate)]


class CantoneseNegation(unittest.TestCase):
    def test_dropping_a_negation_is_reported(self):
        self.assertIn("negation_lost", codes("今晚嘅 live 唔會 record。", "今晚嘅 live 會 record。"))
        self.assertIn("negation_lost", codes("我哋冇計劃加場。", "我哋計劃加場。"))
        self.assertIn("negation_lost", codes("我哋唔應該咁做。", "我哋應該咁做。"))

    def test_courtesy_words_are_not_negation(self):
        self.assertNotIn("negation_lost", codes("唔該大家準時到。", "請大家準時到。"))
        self.assertNotIn("negation_lost", codes("唔好意思，今日遲咗開門。", "抱歉，今日遲咗開門。"))

    def test_a_kept_negation_is_not_reported(self):
        self.assertEqual(codes("下星期唔使預約。", "下星期都唔使預約。"), [])



class EditTurnCreditApproval(unittest.TestCase):
    """The edit turn asks for the automatic credit limit (Pricing V2) and never for web research: one click per edit."""

    def test_the_server_built_turn_carries_automatic_approval_and_no_research(self):
        from postriff_phase2 import draft_edits
        variant = {"id": "v1", "platform": "LinkedIn", "language": "en", "channelId": "c1"}
        payload = draft_edits.turn_payload(variant, {"mode": "tone", "tone": "warm"}, {"voiceMode": "neutral", "model": "m", "expectedRevision": 3}, "k1")
        self.assertEqual(payload["creditApproval"], "automatic")
        self.assertIs(payload["research"], False)
        self.assertNotIn("creditQuoteId", payload)
        self.assertEqual(payload["destinations"], [{"platform": "LinkedIn", "language": "en", "channelId": "c1"}])


if __name__ == "__main__":
    unittest.main()
