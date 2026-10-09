import pathlib
import unittest

from postriff_phase2.library_autometa import MAX_TAG_CHARS, MAX_TAGS, suggest
from postriff_phase2.library_extract import extract_text

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "library" / "real-world-slides.pdf"


class AutoMetadataTests(unittest.TestCase):
    """Free tags and one sentence from a document's own text: recurring key phrases, never a model."""

    def test_slide_deck_gets_its_recurring_phrases_and_a_sentence_from_the_file(self):
        _, text = extract_text(FIXTURE.read_bytes(), "pdf")
        result = suggest(text, "teaching-slides.pdf")
        tags = result["tags"]
        self.assertTrue(tags)
        self.assertTrue(any("seventh" in tag or "leading" in tag or "tonic" in tag for tag in tags), tags)
        # Slide counters and timestamps are furniture, never tags.
        self.assertFalse(any(tag.startswith("slide") or ":" in tag for tag in tags), tags)
        self.assertIn(result["summary"], " ".join(text.split()))  # verbatim from the file
        self.assertNotIn("SLIDE", result["summary"])

    def test_traditional_chinese_tags_are_whole_terms(self):
        text = ("香港大會堂獨奏會節目單\n本場音樂會演奏布拉姆斯作品118號間奏曲。\n"
                "布拉姆斯晚期鋼琴作品充滿內省。間奏曲的和聲與踏板運用需要細緻控制。\n練琴筆記：左手踏板同埋 rubato 要再練。")
        tags = suggest(text, "2026年10月 香港大會堂 獨奏會 節目單.md")["tags"]
        for expected in ("布拉姆斯", "間奏曲", "香港大會堂"):
            self.assertIn(expected, tags)
        self.assertNotIn("堂獨奏會節目", tags)  # a fragment across words that occurs once is not a tag

    def test_a_file_without_text_is_tagged_from_its_name(self):
        result = suggest("", "Beethoven+Op+70%2C+no+2%3AI.pdf")
        self.assertEqual(result, {"tags": ["beethoven"], "summary": None})

    def test_table_rows_are_not_a_summary_and_limits_hold(self):
        text = "Pianist | Pieces | Theme\n" + "\n".join(f"Pianist {n} | {n} | Rhythm and play" for n in range(40))
        result = suggest(text, "recordings.xlsx")
        self.assertTrue(result["summary"] is None or "|" not in result["summary"])
        self.assertLessEqual(len(result["tags"]), MAX_TAGS)
        self.assertTrue(all(0 < len(tag) <= MAX_TAG_CHARS for tag in result["tags"]))

    def test_empty_input(self):
        self.assertEqual(suggest("", ""), {"tags": [], "summary": None})


if __name__ == "__main__":
    unittest.main()
