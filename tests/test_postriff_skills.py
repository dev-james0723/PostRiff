"""Skill binding for writing routes (agent chat design §7): selection, hashing, composition, absence."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import skills  # noqa: E402
from postriff_phase2.skills import SkillLibrary  # noqa: E402


def write(root, skill_id, files):
    for relative, text in files.items():
        path = root / skill_id / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class SkillLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "postriff-content-craft", {
            "SKILL.md": "---\nname: postriff-content-craft\nmetadata:\n  version: 1.1.1\n---\n# Content craft\nConcrete opening, earned payoff.",
            "references/editorial-workflow.md": "# Editorial workflow\nResolve the source first.",
            "references/human-voice-pass.md": "# Human voice pass\nRead it aloud.",
            "references/platform-playbooks.md": "# Playbooks\n## LinkedIn\nNo corporate filler.",
            "references/visual-handoff.md": "# Visual handoff\nOne idea per slide.",
        })
        write(self.root, "postriff-channel-linkedin", {"SKILL.md": "---\nname: postriff-channel-linkedin\n---\n# linkedin adapter\nProfessional relevance."})
        write(self.root, "postriff-channel-threads", {"SKILL.md": "# threads adapter\nConversational."})

    def tearDown(self):
        self.tmp.cleanup()

    def test_bind_core_plus_one_adapter_per_platform_and_records_hashes(self):
        bound = SkillLibrary(self.root).bind([{"platform": "LinkedIn", "language": "English"}, {"platform": "Threads", "language": "English"}, {"platform": "LinkedIn", "language": "繁體中文"}])
        ids = [b["id"] for b in bound["bindings"]]
        self.assertEqual(ids, ["postriff-content-craft", "postriff-channel-linkedin", "postriff-channel-threads"])
        core = bound["bindings"][0]
        self.assertEqual(core["version"], "1.1.1")
        self.assertEqual([f["path"] for f in core["files"]], ["SKILL.md", "references/editorial-workflow.md", "references/human-voice-pass.md", "references/platform-playbooks.md"])
        self.assertTrue(all(len(f["sha256"]) == 64 for f in core["files"]) and len(core["sha256"]) == 64)
        self.assertEqual(bound["bindings"][2]["version"], "unversioned")
        self.assertEqual(bound["warnings"], [])
        self.assertIn("## Skill: postriff-content-craft (v1.1.1)", bound["text"])
        self.assertIn("### postriff-content-craft/references/platform-playbooks.md", bound["text"])
        self.assertIn("Professional relevance.", bound["text"])
        self.assertNotIn("name: postriff-content-craft", bound["text"])  # frontmatter stripped
        self.assertEqual(skills.summary(bound["bindings"]), ["content-craft", "channel-linkedin", "channel-threads"])

    def test_visual_formats_add_the_handoff_reference(self):
        library = SkillLibrary(self.root)
        plain = library.bind([{"platform": "LinkedIn", "language": "English"}], "short_text")
        visual = library.bind([{"platform": "LinkedIn", "language": "English"}], "carousel")
        self.assertNotIn("visual-handoff", plain["text"])
        self.assertIn("One idea per slide.", visual["text"])

    def test_missing_adapter_is_reported_not_fatal(self):
        bound = SkillLibrary(self.root).bind([{"platform": "Xiaohongshu", "language": "繁體中文"}])
        self.assertEqual([b["id"] for b in bound["bindings"]], ["postriff-content-craft"])
        self.assertTrue(any("postriff-channel-xiaohongshu" in w for w in bound["warnings"]))

    def test_no_library_binds_nothing_and_says_so(self):
        empty = SkillLibrary(Path(self.tmp.name) / "nowhere")
        self.assertFalse(empty.available())
        bound = empty.bind([{"platform": "LinkedIn", "language": "English"}])
        self.assertEqual((bound["bindings"], bound["text"]), ([], ""))
        self.assertIn("No skill library", bound["warnings"][0])

    def test_paths_stay_inside_the_library_and_ids_are_validated(self):
        library = SkillLibrary(self.root)
        self.assertIsNone(library.load("../etc"))
        self.assertIsNone(library.load("postriff-content-craft", ("../../SKILL.md",)) and None)
        loaded = library.load("postriff-content-craft", ("../postriff-channel-linkedin/SKILL.md",))
        self.assertEqual([f["path"] for f in loaded["files"]], ["SKILL.md"])

    def test_env_override_and_repo_default(self):
        os.environ[skills.SKILLS_DIR_ENV] = str(self.root)
        try:
            self.assertEqual(skills.default_root(), self.root)
        finally:
            del os.environ[skills.SKILLS_DIR_ENV]
        repo = skills.default_root()
        self.assertTrue(repo is None or (repo / "postriff-content-craft" / "SKILL.md").is_file())

    def test_oversized_text_is_cut_with_a_warning(self):
        write(self.root, "postriff-content-craft", {"references/editorial-workflow.md": "x" * (skills.MAX_TEXT_CHARS + 10)})
        bound = SkillLibrary(self.root).bind([{"platform": "LinkedIn", "language": "English"}])
        self.assertLessEqual(len(bound["text"]), skills.MAX_TEXT_CHARS)
        self.assertTrue(any("cut at" in w for w in bound["warnings"]))


if __name__ == "__main__":
    unittest.main()
