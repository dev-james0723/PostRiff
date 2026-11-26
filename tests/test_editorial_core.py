"""The editorial core pack and the skill set an edit binds (brand intelligence spec 5.5; HUM-1, HUM-4).

One contract file says what a tone or polish edit may change and what it must keep. It is shared byte for byte with a
separately packaged editing skill, so its hash is pinned here: a change to it is a change to both. The pack's own text
repeats the contract's sentences, and an edit binds a small set (the pack, the editing pack for the draft's language,
the adapter contract and the destination's adapter) that fits the paid writer's 60,000-byte slot in Chinese too.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

from postriff_phase2 import skill_registry, skills
from postriff_phase2.coworker import flags
from postriff_phase2.skills import SkillLibrary

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "skills" / "rafii-editorial-core"
# sha256 of skills/rafii-editorial-core/contract.json as shared with the public editing skill.
CONTRACT_SHA256 = "077f767fbdeff106b628c78dcfc6552b745359d378228a01bee02c1cab515d73"
HK = [{"platform": "LinkedIn", "language": "zh-Hant-HK"}]
EN = [{"platform": "LinkedIn", "language": "en"}]


def contract():
    return json.loads((PACK / "contract.json").read_text(encoding="utf-8"))


def pack_text():
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(PACK.rglob("*.md")))


def ids(bound):
    return [binding["id"] for binding in bound["bindings"]]


class ContractTest(unittest.TestCase):
    def test_the_contract_is_the_pinned_file(self):
        self.assertEqual(hashlib.sha256((PACK / "contract.json").read_bytes()).hexdigest(), CONTRACT_SHA256)

    def test_every_mode_tone_and_depth_has_an_id_a_label_and_a_guide(self):
        data = contract()
        for group in ("modes", "tones", "depths"):
            for item in data[group]:
                with self.subTest(group=group, id=item.get("id")):
                    self.assertRegex(item["id"], r"^[a-z]+$")
                    self.assertTrue(item["label"].strip() and item["guide"].strip())
        self.assertEqual([item["id"] for item in data["modes"]], ["polish", "tone"])
        self.assertEqual([item["id"] for item in data["tones"]], ["warm", "professional", "direct", "playful", "custom"])
        self.assertEqual([item["id"] for item in data["depths"]], ["light", "standard", "deep"])
        self.assertEqual(len(data["protected"]), 13)

    def test_the_code_reads_tones_depths_and_protected_rules_from_the_contract(self):
        from postriff_phase2 import draft_edits
        data = contract()
        self.assertEqual(draft_edits.contract(), data)
        self.assertEqual(draft_edits.TONES, tuple(item["id"] for item in data["tones"]))
        self.assertEqual(draft_edits.DEPTHS, tuple(item["id"] for item in data["depths"]))
        self.assertEqual(draft_edits.MODES, tuple(item["id"] for item in data["modes"]))
        self.assertEqual(draft_edits.guide("tones", "warm"), data["tones"][0]["guide"])
        self.assertEqual(draft_edits.label("tones", "playful"), "Playful")


class PackTextTest(unittest.TestCase):
    def test_the_pack_repeats_the_contract_word_for_word(self):
        data, text = contract(), pack_text()
        sentences = ([item["rule"] for item in data["protected"]] + [item["guide"] for group in ("modes", "tones", "depths") for item in data[group]]
                     + list(data["separations"]) + [data["noChange"], data["scope"]["selection"], data["voice"]["personalized"], data["voice"]["neutral"]])
        for sentence in sentences:
            with self.subTest(sentence[:50]):
                self.assertIn(sentence, text)

    def test_the_pack_is_general_and_makes_no_claim_about_who_wrote_a_text(self):
        for path in sorted(PACK.rglob("*")):
            if not path.is_file():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for pattern, label in skill_registry.LEAK_PATTERNS:
                    self.assertIsNone(re.search(pattern, line, re.I), f"{path.name}:{number} {label}")
        text = pack_text()
        self.assertNotRegex(text, re.compile(r"detector|undetectable|ai[- ]generated|pass(?:es|ing)? as human", re.I))

    def test_skill_md_is_versioned_bounded_and_links_only_what_an_edit_receives(self):
        body = (PACK / "SKILL.md").read_text(encoding="utf-8")
        front = body.split("\n---", 1)[0]
        self.assertRegex(front, r"(?m)^name: rafii-editorial-core$")
        self.assertRegex(front, r"(?m)^\s*version:\s*1\.0\.0$")
        self.assertLessEqual(len(body.encode()), 9_000)
        linked = set(re.findall(r"\]\((references/[^)]+)\)", body))
        self.assertEqual(linked, set(skills.EDITORIAL_REFERENCES))
        for relative in skills.EDITORIAL_REFERENCES:
            self.assertTrue((PACK / relative).is_file(), relative)
        # The run's strict output schema has no field for a change log, so the pack names only fields that exist.
        self.assertNotRegex(pack_text(), re.compile(r"`(copy|fields|channelId|canonicalBrief|formatId)`|variants\[\]\."))


class EditBindingTest(unittest.TestCase):
    def setUp(self):
        self.library = SkillLibrary(REPO / "skills")

    def test_a_hong_kong_chinese_edit_binds_the_small_set_inside_the_paid_budget(self):
        bound = self.library.bind(HK, None, "draft_edit", None, max_chars=60_000)
        self.assertEqual(ids(bound), ["rafii-editorial-core", "rafii-humanizer-zh", "postriff-adapter-contract", "postriff-channel-linkedin"])
        self.assertEqual(bound["omitted"], [])
        self.assertEqual(bound["warnings"], [])
        self.assertLess(len(bound["text"].encode()), 60_000)
        self.assertEqual([f["path"] for f in bound["bindings"][0]["files"]], ["SKILL.md", *skills.EDITORIAL_REFERENCES])
        # No ideation or craft reference reaches an edit: it changes wording, it does not plan a post.
        self.assertNotIn("postriff-content-craft", ids(bound))
        self.assertNotIn("postriff-content-engine", ids(bound))
        self.assertNotIn("postriff-content-craft/references", bound["text"])
        self.assertNotIn("human-voice-pass.md", bound["text"])

    def test_a_mixed_english_and_chinese_draft_binds_both_editing_packs(self):
        bound = self.library.bind(HK, None, "draft_edit", None, max_chars=60_000, languages=("zh", "en"))
        self.assertEqual(ids(bound)[:3], ["rafii-editorial-core", "rafii-humanizer-zh", "rafii-humanizer-en"])
        self.assertEqual(bound["omitted"], [])
        self.assertLess(len(bound["text"].encode()), 60_000)
        english = self.library.bind(EN, None, "draft_edit", None, max_chars=60_000, languages=("en", "zh"))
        self.assertEqual(ids(english)[:3], ["rafii-editorial-core", "rafii-humanizer-en", "rafii-humanizer-zh"])

    def test_one_language_binds_one_pack_and_an_uncovered_language_binds_none(self):
        self.assertEqual(ids(self.library.bind(EN, None, "draft_edit", None, max_chars=60_000)),
                         ["rafii-editorial-core", "rafii-humanizer-en", "postriff-adapter-contract", "postriff-channel-linkedin"])
        cantonese = self.library.bind([{"platform": "Threads", "language": "yue-Hant-HK"}], None, "draft_edit", None, max_chars=60_000)
        self.assertEqual(ids(cantonese), ["rafii-editorial-core", "rafii-humanizer-zh", "postriff-adapter-contract", "postriff-channel-threads"])
        french = self.library.bind([{"platform": "LinkedIn", "language": "fr"}], None, "draft_edit", None, max_chars=60_000)
        self.assertEqual(ids(french), ["rafii-editorial-core", "postriff-adapter-contract", "postriff-channel-linkedin"])

    def test_the_edit_set_does_not_depend_on_the_registry_flag(self):
        flags.attach({"RAFII_SKILL_REGISTRY_V2_ENABLED": ""})
        try:
            off = self.library.bind(HK, None, "draft_edit", None, max_chars=60_000)
            flags.attach({"RAFII_SKILL_REGISTRY_V2_ENABLED": "1"})
            on = self.library.bind(HK, None, "draft_edit", None, max_chars=60_000)
        finally:
            flags.attach(None)
        self.assertEqual(off, on)

    def test_a_tight_budget_drops_the_optional_parts_whole_and_never_the_core(self):
        full = self.library.bind(HK, None, "draft_edit", None, max_chars=60_000)
        core = next(len(self.library._section(self.library.load("rafii-editorial-core")).encode()) for _ in [0])
        tight = self.library.bind(HK, None, "draft_edit", None, max_chars=len(full["text"].encode()) - 1)
        self.assertEqual([(o["skill"], o["path"]) for o in tight["omitted"]], [("rafii-editorial-core", "references/tone-guide.md")])
        self.assertEqual(ids(tight), ids(full))
        smallest = self.library.bind(HK, None, "draft_edit", None, max_chars=core + 14_000)
        self.assertEqual(ids(smallest), ["rafii-editorial-core", "postriff-adapter-contract", "postriff-channel-linkedin"])
        self.assertEqual([(o["skill"], o["path"]) for o in smallest["omitted"]],
                         [("rafii-editorial-core", "references/tone-guide.md"), ("rafii-editorial-core", "references/fidelity-check.md"), ("rafii-humanizer-zh", "SKILL.md")])
        self.assertLessEqual(len(smallest["text"].encode()), core + 14_000)

    def test_every_other_turn_binds_what_it_bound_before(self):
        for intent in (None, "draft", "research", "engagement_reply"):
            bound = self.library.bind(HK, None, intent, None, max_chars=120_000)
            self.assertNotIn("rafii-editorial-core", ids(bound), intent)
            self.assertEqual(ids(bound)[:2], ["postriff-content-engine", "postriff-content-craft"], intent)
        # `languages` only means something to an edit.
        self.assertEqual(self.library.bind(EN, max_chars=120_000), self.library.bind(EN, max_chars=120_000, languages=("zh",)))


class RegistryTest(unittest.TestCase):
    def test_the_pack_is_registered_hashed_and_proven_by_its_consumer(self):
        flags.attach({})
        try:
            registry = skill_registry.load()
            entry = registry.get("rafii-editorial-core")
            self.assertIsNotNone(entry, "skills/rafii-editorial-core is not classified in the registry")
            self.assertEqual((entry["kind"], entry["version"], entry["deprecation"], entry["private"]), ("knowledge", "1.0.0", "active", False))
            self.assertEqual(entry["intents"], ["draft_edit"])
            self.assertEqual(entry["sha256"], skill_registry.entry_hash(entry, registry.root, {}))
            self.assertEqual(entry.get("lockedVersion"), entry["version"])
            self.assertIn("rafii-editorial-core", skill_registry.run_probe(entry["consumers"][0], registry))
            report = skill_registry.check(registry)
        finally:
            flags.attach(None)
        mine = [error for error in report.errors if "editorial-core" in error]
        self.assertEqual(mine, [])
        self.assertNotIn("rafii-editorial-core", report.orphans)

    def test_no_other_agent_or_side_call_is_handed_the_edit_pack(self):
        from postriff_phase2 import skill_compiler
        for task in ({"agent": "content", "intent": "draft"}, {"agent": "writer", "intent": "*"}, {"agent": "content", "intent": "engagement_reply", "locales": ["zh-Hant-HK"]}):
            self.assertNotIn("rafii-editorial-core", [s["id"] for s in skill_compiler.compile(dict(task))["selections"]], task)


if __name__ == "__main__":
    unittest.main()
