"""Skill binding for writing routes (agent chat design §7): selection, hashing, composition, absence."""
import os
import re
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
            "references/algorithm-practice.md": "# Algorithm-aware creation\nHonest title, same payoff.",
        })
        write(self.root, "postriff-research-and-source-log", {
            "SKILL.md": "---\nname: postriff-research-and-source-log\n---\n# Research and source log\nJudge each atomic statement independently.",
            "references/provenance-ledger.md": "# Provenance ledger\nRecord through the host.",
        })
        write(self.root, "postriff-content-engine", {
            "SKILL.md": "---\nname: postriff-content-engine\n---\n# Content engine\nThe method, never the person.",
            "references/content-pillars-and-workflows.md": "# Pillars\nBuilding, thinking, becoming.",
            "references/localization.md": "# Localization\nLocalize the idea, not the words.",
            "references/research-and-sensitivity.md": "# Research\nRead the primary document.",
            "references/platform-and-templates.md": "# Templates\nAt most three combinations.",
            "references/operations.md": "# Operations\nAudit the queue first.",
        })
        write(self.root, "postriff-adapter-contract", {"SKILL.md": "---\nname: postriff-adapter-contract\n---\n# Channel adapter contract\n## 8. Approval and safety rules\nEvery result stays draft_only."})
        write(self.root, "postriff-channel-linkedin", {"SKILL.md": "---\nname: postriff-channel-linkedin\n---\n# linkedin adapter\nProfessional relevance."})
        write(self.root, "postriff-channel-threads", {"SKILL.md": "# threads adapter\nConversational."})

    def tearDown(self):
        self.tmp.cleanup()

    def test_bind_core_plus_one_adapter_per_platform_and_records_hashes(self):
        bound = SkillLibrary(self.root).bind([{"platform": "LinkedIn", "language": "English"}, {"platform": "Threads", "language": "English"}, {"platform": "LinkedIn", "language": "繁體中文"}])
        ids = [b["id"] for b in bound["bindings"]]
        self.assertEqual(ids, ["postriff-content-engine", "postriff-content-craft", "postriff-adapter-contract", "postriff-channel-linkedin", "postriff-channel-threads"])
        core = bound["bindings"][1]
        self.assertEqual(core["version"], "1.1.1")
        self.assertEqual([f["path"] for f in core["files"]], ["SKILL.md", "references/editorial-workflow.md", "references/human-voice-pass.md", "references/platform-playbooks.md", "references/algorithm-practice.md"])
        self.assertNotIn("postriff-research-and-source-log", ids, "an uncited turn carries no claim rules")
        self.assertTrue(all(len(f["sha256"]) == 64 for f in core["files"]) and len(core["sha256"]) == 64)
        self.assertEqual(bound["bindings"][4]["version"], "unversioned")
        self.assertEqual(bound["warnings"], [])
        self.assertIn("## Skill: postriff-content-craft (v1.1.1)", bound["text"])
        self.assertIn("### postriff-content-craft/references/platform-playbooks.md", bound["text"])
        self.assertIn("Professional relevance.", bound["text"])
        self.assertNotIn("name: postriff-content-craft", bound["text"])  # frontmatter stripped
        self.assertEqual(skills.summary(bound["bindings"]), ["content-engine", "content-craft", "adapter-contract", "channel-linkedin", "channel-threads"])
        self.assertEqual(bound["text"].count("## Skill: postriff-adapter-contract"), 1)

    def test_engine_carries_only_the_references_the_turn_uses(self):
        library = SkillLibrary(self.root)

        def paths(**kwargs):
            bound = library.bind([{"platform": "LinkedIn", "language": "English"}], **kwargs)
            return [f["path"] for f in bound["bindings"][0]["files"]]

        # A bare English turn carries the engine's SKILL.md alone; operations.md is never bound.
        self.assertEqual(paths(), ["SKILL.md"])
        self.assertEqual(paths(format_id="short_text"), ["SKILL.md", "references/content-pillars-and-workflows.md"])
        self.assertIn("references/research-and-sensitivity.md", paths(intent="research"))
        self.assertIn("references/research-and-sensitivity.md", paths(content_type="article_news_commentary"))
        self.assertNotIn("references/research-and-sensitivity.md", paths(content_type="personal_reflection"))
        self.assertIn("references/platform-and-templates.md", paths(format_id="carousel"))
        self.assertNotIn("references/operations.md", paths(format_id="carousel", intent="research", content_type="deep_point_of_view"))

    def test_localization_binds_only_when_a_turn_is_not_plain_english(self):
        library = SkillLibrary(self.root)

        def has_localization(destinations):
            bound = library.bind(destinations)
            return "references/localization.md" in [f["path"] for f in bound["bindings"][0]["files"]]

        self.assertFalse(has_localization([{"platform": "LinkedIn", "language": "English"}]))
        self.assertTrue(has_localization([{"platform": "LinkedIn", "language": "繁體中文"}]))
        self.assertTrue(has_localization([{"platform": "LinkedIn", "language": "English"}, {"platform": "Threads", "language": "日本語"}]))

    def test_engine_skill_fits_the_per_file_cap(self):
        """The split exists so the voice contract is never delivered truncated."""
        repo = skills.default_root()
        if repo is None:
            self.skipTest("no repo skill library")
        loaded = SkillLibrary(repo).load(skills.ENGINE_SKILL)
        self.assertIsNotNone(loaded, "the shipped library must contain the voice contract")
        self.assertLessEqual(len(loaded["body"]), skills.MAX_FILE_CHARS)
        for relative in (skills.ENGINE_WORKFLOWS, skills.ENGINE_LOCALIZATION, skills.ENGINE_RESEARCH, skills.ENGINE_TEMPLATES):
            reference = SkillLibrary(repo).load(skills.ENGINE_SKILL, (relative,))["references"]
            self.assertEqual(len(reference), 1, f"{relative} is missing from the shipped package")
            self.assertLessEqual(len(reference[0]["text"]), skills.MAX_FILE_CHARS)

    def test_over_budget_turns_leave_out_whole_optional_files_and_record_only_what_was_sent(self):
        library = SkillLibrary(self.root)
        # Make the lowest-priority optional reference big enough to push the turn over budget.
        write(self.root, "postriff-content-engine", {"references/content-pillars-and-workflows.md": "w" * (skills.MAX_FILE_CHARS - 10)})
        write(self.root, "postriff-content-craft", {"references/platform-playbooks.md": "p" * (skills.MAX_FILE_CHARS - 10)})
        write(self.root, "postriff-channel-linkedin", {"SKILL.md": "# linkedin adapter\n" + "l" * (skills.MAX_FILE_CHARS - 100)})
        before = library.bind([{"platform": "LinkedIn", "language": "English"}], "short_text")
        self.assertLessEqual(len(before["text"]), skills.MAX_TEXT_CHARS)
        # The workflows file went first and whole; nothing mandatory was cut mid-text.
        self.assertTrue(any("Left out postriff-content-engine/references/content-pillars-and-workflows.md" in w for w in before["warnings"]))
        self.assertFalse(any("later sections were left out" in w for w in before["warnings"]))
        self.assertTrue(before["text"].rstrip().endswith("l" * 50), "the adapter, composed last, arrived whole")
        engine = before["bindings"][0]
        self.assertEqual([f["path"] for f in engine["files"]], ["SKILL.md"], "a left-out file is not recorded")
        self.assertEqual(engine["sha256"], library.load("postriff-content-engine")["sha256"], "the hash describes what was sent")
        # Playbooks stay, because leaving out the first file was enough.
        self.assertIn("references/platform-playbooks.md", [f["path"] for f in before["bindings"][1]["files"]])

    def test_claim_rules_bind_only_when_a_turn_cites_sources(self):
        library = SkillLibrary(self.root)

        def research(**kwargs):
            bound = library.bind([{"platform": "LinkedIn", "language": "English"}], **kwargs)
            return next((b for b in bound["bindings"] if b["id"] == skills.RESEARCH_SKILL), None)

        self.assertIsNone(research())
        self.assertIsNone(research(content_type="personal_reflection"))
        for kwargs in ({"intent": "research"}, {"content_type": "article_news_commentary"}, {"content_type": "product_feature_launch"}):
            binding = research(**kwargs)
            self.assertIsNotNone(binding, kwargs)
            self.assertEqual([f["path"] for f in binding["files"]], ["SKILL.md", "references/provenance-ledger.md"])

    def test_shipped_skills_only_link_references_the_binder_can_send(self):
        """cli_runtime tells the model every file a skill refers to is inline, so a link to a file
        the binder never sends is an instruction the model cannot follow."""
        repo = skills.default_root()
        if repo is None:
            self.skipTest("no repo skill library")
        bindable = {
            skills.ENGINE_SKILL: {skills.ENGINE_WORKFLOWS, skills.ENGINE_LOCALIZATION, skills.ENGINE_RESEARCH, skills.ENGINE_TEMPLATES},
            skills.CORE_SKILL: set(skills.CORE_REFERENCES) | {skills.VISUAL_REFERENCE, skills.DISCOVERY_REFERENCE},
            skills.RESEARCH_SKILL: set(skills.RESEARCH_REFERENCES),
            skills.ADAPTER_CONTRACT: set(),
            **{skill_id: set() for skill_id in skills.CHANNEL_SKILLS.values()},
        }
        for skill_id, allowed in bindable.items():
            body = (repo / skill_id / "SKILL.md").read_text(encoding="utf-8")
            linked = set(re.findall(r"\]\((references/[^)]+)\)", body))
            self.assertEqual(linked - allowed, set(), f"{skill_id} links a file no run receives")
            for relative in allowed:
                self.assertTrue((repo / skill_id / relative).is_file(), f"{skill_id}/{relative} is bound but missing")

    def test_shipped_skills_describe_the_enforced_output_schema(self):
        """Bound skills must not name fields the run's strict JSON schema rejects."""
        from postriff_phase2.cli_runtime import OUTPUT_SCHEMA
        repo = skills.default_root()
        if repo is None:
            self.skipTest("no repo skill library")
        run_bound = [skills.ENGINE_SKILL, skills.CORE_SKILL, skills.RESEARCH_SKILL, skills.ADAPTER_CONTRACT, *skills.CHANNEL_SKILLS.values()]
        stale = re.compile(r"`(copy|fields|channelId|canonicalBrief|formatId)`|variants\[\]\.")
        for skill_id in run_bound:
            for path in sorted((repo / skill_id).rglob("*.md")):
                match = stale.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match, f"{path.relative_to(repo)} names {match and match.group(0)}")
        contract = (repo / skills.ADAPTER_CONTRACT / "SKILL.md").read_text(encoding="utf-8")
        for field in OUTPUT_SCHEMA["properties"]["variants"]["items"]["required"]:
            self.assertIn(f"`{field}`", contract, f"the adapter contract never names the schema field {field}")

    def test_engine_names_exactly_the_memory_files_a_writing_run_receives(self):
        """The engine tells the model which memory files it has; that must match what memory.py sends."""
        import inspect
        from postriff_phase2 import memory
        repo = skills.default_root()
        if repo is None:
            self.skipTest("no repo skill library")
        sent = set(inspect.signature(memory.prompt_fragments).parameters["names"].default)
        body = SkillLibrary(repo).load(skills.ENGINE_SKILL)["body"]
        rows = dict(re.findall(r"^\| `([A-Z]+\.md)` \|[^|]*\| (supplied|not supplied) \|$", body, re.M))
        self.assertEqual(set(rows), set(memory.FILE_ORDER), "the engine's memory table must list every memory file")
        self.assertEqual({name for name, state in rows.items() if state == "supplied"}, sent)

    def test_a_platform_with_no_adapter_is_reported(self):
        bound = SkillLibrary(self.root).bind([{"platform": "Farcaster", "language": "English"}])
        self.assertEqual([b["id"] for b in bound["bindings"]], ["postriff-content-engine", "postriff-content-craft"])
        self.assertTrue(any("No channel adapter is mapped for Farcaster" in w for w in bound["warnings"]))

    def test_every_shipped_channel_adapter_is_reachable(self):
        """An adapter nobody can bind is dead weight; a bound id with no package is a silent gap."""
        repo = skills.default_root()
        if repo is None:
            self.skipTest("no repo skill library")
        shipped = {p.name for p in repo.glob("postriff-channel-*")}
        mapped = set(skills.CHANNEL_SKILLS.values())
        self.assertEqual(mapped - shipped, set(), "mapped to a package that is not installed")
        self.assertEqual(shipped - mapped, set(), "installed but no platform name binds it")
        self.assertTrue((repo / skills.ADAPTER_CONTRACT / "SKILL.md").is_file())

    def test_shipped_adapters_do_not_repeat_the_contract(self):
        """Each adapter carries its own sections; shared ones appear only as a genuine override."""
        repo = skills.default_root()
        if repo is None:
            self.skipTest("no repo skill library")
        contract = SkillLibrary(repo).load(skills.ADAPTER_CONTRACT)["body"]
        for path in sorted(repo.glob("postriff-channel-*/SKILL.md")):
            body = SkillLibrary(repo).load(path.parent.name)["body"]
            self.assertIn(f"`{skills.ADAPTER_CONTRACT}`", body, path.parent.name)
            for heading in ("## 5. Asset rules", "## 9. Draft payload mapping", "## PostRiff runtime binding"):
                self.assertIn(heading, contract)
                self.assertNotIn(heading, body, f"{path.parent.name} repeats a section no adapter overrides")

    def test_visual_formats_add_the_handoff_reference(self):
        library = SkillLibrary(self.root)
        plain = library.bind([{"platform": "LinkedIn", "language": "English"}], "short_text")
        visual = library.bind([{"platform": "LinkedIn", "language": "English"}], "carousel")
        self.assertNotIn("visual-handoff", plain["text"])
        self.assertIn("One idea per slide.", visual["text"])

    def test_missing_adapter_is_reported_not_fatal(self):
        bound = SkillLibrary(self.root).bind([{"platform": "Xiaohongshu", "language": "繁體中文"}])
        self.assertEqual([b["id"] for b in bound["bindings"]], ["postriff-content-engine", "postriff-content-craft"])
        self.assertTrue(any("postriff-channel-xiaohongshu" in w for w in bound["warnings"]))
        self.assertFalse(any("adapter-contract" in w for w in bound["warnings"]))

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
