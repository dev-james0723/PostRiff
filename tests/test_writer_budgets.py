"""The cloud writer accepts every idea the drafting pipeline composes (instruction plus handed-in material), and the
skill text a turn binds fits the writer's byte-cut slot, so no channel adapter is ever cut silently."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from postriff_alpha.generation import MATERIAL_LABEL  # noqa: E402
from postriff_phase2 import ideas, model_runtime, skills  # noqa: E402
from postriff_phase2.model_runtime import ServerModelRuntime  # noqa: E402
from postriff_phase2.skills import SkillLibrary  # noqa: E402
from test_postriff_model_runtime import DESTS, context  # noqa: E402
from test_postriff_skills import write  # noqa: E402


class IdeaWithMaterialTest(unittest.TestCase):
    def composed(self, instruction, material):
        return instruction + f"\n\n{MATERIAL_LABEL}\n<<<\n{material}\n>>>"

    def test_the_largest_composed_idea_fits_the_writer(self):
        # ideas._project bounds the instruction at IDEA_LIMIT and the material at MAX_TEXT, then joins them.
        largest = self.composed("i" * ideas.IDEA_LIMIT, "m" * ideas.MAX_TEXT)
        self.assertLessEqual(len(largest), model_runtime.MAX_IDEA_CHARS)

    def test_a_long_rewrite_reaches_the_writer_whole(self):
        runtime = ServerModelRuntime("secret-key", model="openai/gpt-6-sol")
        idea = self.composed("Rewrite this draft for LinkedIn in a warmer voice.", "A long draft. " * 400)   # ~5,600 chars, over the old 3,000 cap
        payload = runtime._user_payload({"context": context(), "idea": idea, "destinations": DESTS})
        self.assertEqual(payload["idea"], idea)
        messages = runtime._messages({"context": context(), "idea": idea, "tone": "warm", "destinations": DESTS, "reasoning": "quick"}, "quick")
        self.assertIn("A long draft.", json.loads(messages[1]["content"].split("\n\n")[0])["idea"])


class SkillByteBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "postriff-content-craft", {"SKILL.md": "---\nname: postriff-content-craft\nversion: 1.0.0\n---\n# Craft\nWrite plainly.",
                                                   "references/human-voice-pass.md": "Voice pass.", "references/editorial-workflow.md": "e" * 300})
        write(self.root, "postriff-content-engine", {"SKILL.md": "# Engine\nOne idea per post."})
        write(self.root, "postriff-adapter-contract", {"SKILL.md": "# Channel adapter contract\nEvery result stays draft_only."})
        # 400 characters of Chinese are 1,200 UTF-8 bytes.
        write(self.root, "postriff-channel-xiaohongshu", {"SKILL.md": "# xiaohongshu adapter\n" + "小紅書標題不超過二十字" * 40})

    def tearDown(self):
        self.tmp.cleanup()

    def test_cjk_skill_text_is_budgeted_in_bytes(self):
        library = SkillLibrary(self.root)
        whole = library.bind([{"platform": "Xiaohongshu", "language": "zh-Hans"}], max_chars=100_000)
        chars, size = len(whole["text"]), len(whole["text"].encode())
        self.assertGreater(size, chars)
        # A budget between the character count and the byte count used to pass unchanged, then lose the adapter's
        # tail to the writer's byte cut. Now the binder itself keeps the text within the budget, with a warning.
        budget = chars + (size - chars) // 2
        bound = library.bind([{"platform": "Xiaohongshu", "language": "zh-Hans"}], max_chars=budget)
        self.assertLessEqual(len(bound["text"].encode()), budget)
        self.assertTrue(bound["warnings"], "shrinking the skill text is always reported")
        self.assertTrue(any("bytes" in w for w in bound["warnings"]), bound["warnings"])

    def test_paid_route_output_fits_the_writer_slot(self):
        self.assertLessEqual(skills.budget_for("paid"), model_runtime.MAX_SKILLS_BYTES)


if __name__ == "__main__":
    unittest.main()
