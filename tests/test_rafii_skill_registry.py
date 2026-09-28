"""Rafii capability registry (adaptive coworker spec §4-§8; architecture lock R1-R4).

The shipped registry must pass `skill_registry.check()` (the CI gate), and each failure class the spec names is
proven to fail: unclassified or duplicate skills, a content change without a version bump, a tool without a typed
tool, a policy without code, a user overlay touching protected policy, incompatible versions, private material in
the default bundle, and customer-specific (James) content in a default skill.
"""
import copy
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from postriff_phase2 import skill_compiler, skill_registry
from postriff_phase2.coworker import flags, overlays
from postriff_phase2.skills import SkillLibrary

REPO = Path(__file__).resolve().parents[1]


class RegistryGateTest(unittest.TestCase):
    """The shipped registry is the CI gate."""

    @classmethod
    def setUpClass(cls):
        flags.attach({})
        cls.registry = skill_registry.load()
        cls.report = skill_registry.check(cls.registry)

    @classmethod
    def tearDownClass(cls):
        flags.attach(None)

    def test_shipped_registry_passes_every_check(self):
        self.assertEqual(self.report.errors, [], "\n".join(self.report.errors))
        self.assertTrue(self.report.ok)

    def test_orphans_are_zero_and_exceptions_are_documented(self):
        self.assertEqual(self.report.orphans, [])
        for item in self.report.exceptions:
            self.assertIn(item["state"], ("deprecated", "dormant"))
            self.assertGreater(len(item["reason"]), 40, item)

    def test_every_installed_skill_is_classified_once(self):
        installed = {p.name for p in (REPO / "skills").iterdir() if p.is_dir()}
        classified = [s.get("id") or s.get("path", "").split("/")[1] for e in self.registry.entries for s in e["hashSources"]
                      if s.get("type") == "skill" or (s.get("type") == "file" and s.get("path", "").startswith("skills/"))]
        self.assertEqual(installed, set(classified))
        self.assertEqual(len(classified), len(set(classified)), "a skill package is classified twice")

    def test_every_default_capability_is_versioned_hashed_and_typed(self):
        for entry in self.registry.defaults():
            self.assertRegex(entry["version"], r"^\d+\.\d+\.\d+$", entry["id"])
            self.assertRegex(entry["sha256"], r"^sha256:[0-9a-f]{64}$", entry["id"])
            self.assertIn(entry["kind"], skill_registry.KINDS)
            self.assertTrue(entry["consumers"], entry["id"])
            self.assertTrue(entry["tests"], entry["id"])

    def test_skill_md_version_matches_the_registry(self):
        for entry in self.registry.entries:
            for source in entry["hashSources"]:
                if source.get("type") != "skill" or entry.get("private"):
                    continue
                text = (REPO / "skills" / source["id"] / "SKILL.md").read_text()
                match = re.search(r"^\s*version:\s*([\w.+-]+)", text.split("\n---", 1)[0], re.M)
                self.assertIsNotNone(match, source["id"])
                self.assertEqual(match.group(1), entry["version"], source["id"])

    def test_policies_are_protected_and_bound_to_code(self):
        policies = [e for e in self.registry.entries if e["kind"] == "policy"]
        self.assertGreaterEqual(len(policies), 8)
        for entry in policies:
            self.assertEqual(entry["personalization"], "protected")
            for ref in entry["policy"]:
                skill_registry.resolve(ref)

    def test_tools_are_registered_typed_tools(self):
        tools = skill_registry.registered_tools()
        for entry in self.registry.entries:
            if entry["kind"] == "tool" and entry["deprecation"] == "active":
                self.assertIn(entry["tool"], tools, entry["id"])

    def test_no_james_content_in_the_default_bundle(self):
        self.assertEqual(self.report.leaks, [])

    def test_totals_are_reported(self):
        totals = self.report.as_dict()["totals"]
        self.assertEqual(totals["registered"], len(self.registry.entries))
        self.assertEqual(sum(totals["byKind"].values()), totals["registered"])
        self.assertGreaterEqual(totals["private"], 5)


class RegistryFailureTest(unittest.TestCase):
    """Each failure the spec names makes `check()` fail."""

    def setUp(self):
        flags.attach({})
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "skills"
        shutil.copytree(REPO / "skills", self.root)
        self.data = json.loads((self.root / skill_registry.REGISTRY_FILE).read_text())

    def tearDown(self):
        flags.attach(None)
        self.tmp.cleanup()

    def _check(self, data=None, **kwargs):
        (self.root / skill_registry.REGISTRY_FILE).write_text(json.dumps(data or self.data))
        return skill_registry.check(skill_registry.load(self.root), **kwargs)

    def _entry(self, cid, data=None):
        return next(e for e in (data or self.data)["capabilities"] if e["id"] == cid)

    def test_duplicate_id_fails(self):
        data = copy.deepcopy(self.data)
        data["capabilities"].append(copy.deepcopy(self._entry("postriff-channel-x", data)))
        report = self._check(data, run_probes=False)
        self.assertTrue(any("duplicate id" in e for e in report.errors))

    def test_unclassified_skill_fails(self):
        (self.root / "rafii-stray").mkdir()
        (self.root / "rafii-stray" / "SKILL.md").write_text("---\nname: rafii-stray\nmetadata:\n  version: 1.0.0\n---\n# stray\n")
        report = self._check(run_probes=False)
        self.assertTrue(any("rafii-stray: installed but not classified" in e for e in report.errors))

    def test_content_change_without_version_bump_fails_and_lock_refuses(self):
        path = self.root / "postriff-channel-x" / "SKILL.md"
        path.write_text(path.read_text() + "\nAn edit nobody versioned.\n")
        report = self._check(run_probes=False)
        self.assertTrue(any(e.startswith("postriff-channel-x: content changed") for e in report.errors))
        result = skill_registry.lock(skill_registry.load(self.root))
        self.assertIn("postriff-channel-x", result["refused"])

    def test_version_bump_lets_lock_record_the_new_hash(self):
        path = self.root / "postriff-channel-x" / "SKILL.md"
        # Bump from whatever the skill is at now, so a real version bump in the library never breaks this test.
        current = self._entry("postriff-channel-x", self.data)["version"]
        major, minor, patch = (int(part) for part in current.split("."))
        bumped = f"{major}.{minor}.{patch + 1}"
        path.write_text(path.read_text().replace(f"version: {current}", f"version: {bumped}", 1) + "\nA versioned edit.\n")
        data = copy.deepcopy(self.data)
        self._entry("postriff-channel-x", data)["version"] = bumped
        (self.root / skill_registry.REGISTRY_FILE).write_text(json.dumps(data))
        result = skill_registry.lock(skill_registry.load(self.root))
        self.assertEqual(result["refused"], [])
        self.assertIn("postriff-channel-x", result["updated"])
        report = skill_registry.check(skill_registry.load(self.root), run_probes=False)
        self.assertFalse(any(e.startswith("postriff-channel-x") for e in report.errors), report.errors)

    def test_tool_without_typed_tool_fails(self):
        data = copy.deepcopy(self.data)
        self._entry("rafii.tool.research-search", data)["tool"] = "research_search_that_does_not_exist"
        report = self._check(data, verify_hashes=False, run_probes=False)
        self.assertTrue(any("is not a registered typed tool" in e for e in report.errors))

    def test_policy_without_implementation_or_unprotected_fails(self):
        data = copy.deepcopy(self.data)
        entry = self._entry("rafii.policy.rights-check", data)
        entry["policy"] = ["postriff_phase2.source_policy:no_such_function"]
        entry["personalization"] = "overlay_only"
        report = self._check(data, verify_hashes=False, run_probes=False)
        self.assertTrue(any("policy implementation" in e for e in report.errors))
        self.assertTrue(any("must be protected" in e for e in report.errors))

    def test_incompatible_version_fails(self):
        data = copy.deepcopy(self.data)
        self._entry("postriff-adapter-contract", data)["version"] = "2.0.0"
        report = self._check(data, verify_hashes=False, run_probes=False)
        self.assertTrue(any("requires postriff-adapter-contract ^1.0.0 but the registry has 2.0.0" in e for e in report.errors))

    def test_orphan_default_skill_fails(self):
        data = copy.deepcopy(self.data)
        self._entry("postriff-discoverability", data)["consumers"] = []
        report = self._check(data, verify_hashes=False, run_probes=False)
        self.assertIn("postriff-discoverability", report.orphans)
        self.assertFalse(report.ok)

    def test_declared_consumer_that_does_not_select_the_skill_fails(self):
        data = copy.deepcopy(self.data)
        # The writer binds LinkedIn's adapter for a LinkedIn destination, never X's.
        self._entry("postriff-channel-x", data)["consumers"][0]["probe"]["destinations"] = [{"platform": "LinkedIn", "language": "en"}]
        report = self._check(data, verify_hashes=False)
        self.assertTrue(any(e.startswith("postriff-channel-x: consumer postriff_phase2.skills:SkillLibrary.bind did not select it") for e in report.errors))

    def test_customer_specific_content_in_a_default_skill_fails(self):
        path = self.root / "postriff-content-craft" / "references" / "editorial-workflow.md"
        path.write_text(path.read_text() + "\nWrite like James, the pianist, would.\n")
        report = self._check(verify_hashes=False, run_probes=False)
        self.assertTrue(any("customer-specific content in postriff-content-craft/references/editorial-workflow.md" in e for e in report.errors))

    def test_private_material_marked_default_fails(self):
        data = copy.deepcopy(self.data)
        self._entry("james-au-content-craft", data)["default"] = True
        report = self._check(data, verify_hashes=False, run_probes=False)
        self.assertTrue(any("private material cannot be in the default bundle" in e for e in report.errors))


class PrivateMaterialTest(unittest.TestCase):
    def test_hosted_binder_refuses_person_specific_skills(self):
        library = SkillLibrary()
        self.assertIsNotNone(library.load("postriff-content-craft"))
        for skill_id in ("james-au-content-craft", "james-au-social-orchestrator", "james-au-security-and-approval"):
            self.assertIsNone(library.load(skill_id), skill_id)

    def test_private_skills_are_excluded_from_the_hosted_build(self):
        self.assertIn("skills/james-au-*/", (REPO / ".vercelignore").read_text())
        artifact = (REPO / "scripts" / "consumer_ready_artifact.cjs").read_text()
        self.assertIn("james-au-[^/]*", artifact)

    def test_leak_scanner_catches_identity_paths_and_voice_anchors(self):
        samples = ["James prefers short posts", "/Users/someone/Documents/app", "http://127.0.0.1:4310", "handle sing-sing-66",
                   "Preserve natural Cantonese-English mixing", "reflective, specific, calm, curious, candid"]
        for sample in samples:
            self.assertTrue(any(p.search(sample) for p, _ in skill_registry._LEAKS), sample)
        for fine in ("Add festival greetings only if the brief does", "music rights for short video", "a builder's checklist for LinkedIn"):
            self.assertFalse(any(p.search(fine) for p, _ in skill_registry._LEAKS), fine)


class OverlayPolicyTest(unittest.TestCase):
    def test_overlay_cannot_touch_protected_policy(self):
        for overlay in ({"ruleKey": "skip_publish_approval"}, {"rule": {"billing": "free"}}, {"capability": "postriff-publish-and-verify"},
                        {"capability": "rafii.policy.tenant-isolation"}, {"ruleKey": "egress_consent_override"}):
            with self.assertRaises(ValueError, msg=overlay):
                skill_registry.validate_overlay(overlay)

    def test_overlay_may_personalise_writing_knowledge(self):
        self.assertTrue(skill_registry.validate_overlay({"capability": "postriff-channel-linkedin", "ruleKey": "no_emoji"}))


class CompilerTest(unittest.TestCase):
    def setUp(self):
        flags.attach({})

    def tearDown(self):
        flags.attach(None)

    def test_compile_is_bounded_and_relevant(self):
        compiled = skill_compiler.compile({"agent": "content", "intent": "draft", "platforms": ["LinkedIn"], "locales": ["en"]}, budget=24_000)
        ids = [s["id"] for s in compiled["selections"]]
        self.assertIn("postriff-content-craft", ids)
        self.assertIn("postriff-channel-linkedin", ids)
        self.assertNotIn("postriff-channel-instagram", ids)
        self.assertNotIn("postriff-social-graphics", ids)
        self.assertLessEqual(len(compiled["text"]), 24_000)
        self.assertTrue(all(re.fullmatch(r"sha256:[0-9a-f]{64}", s["sha256"]) for s in compiled["selections"]))
        self.assertTrue(any(p["id"] == "postriff-security-and-approval" for p in compiled["policies"]))
        self.assertNotIn("## Skill: postriff-security-and-approval", compiled["text"])  # policies are listed, never injected as text

    def test_creative_agent_gets_visual_craft_not_writing_adapters(self):
        compiled = skill_compiler.compile({"agent": "creative", "intent": "creative_brief", "platforms": ["Instagram"]})
        ids = [s["id"] for s in compiled["selections"]]
        self.assertIn("postriff-social-graphics", ids)
        self.assertNotIn("postriff-content-engine", ids)

    def test_writer_is_unchanged_while_the_registry_flag_is_off(self):
        library = SkillLibrary()
        destinations = [{"platform": "LinkedIn", "language": "zh-Hant-HK"}]
        before = library.bind(destinations)
        with skill_compiler.workflow_context("rafii-weekly-operator"):
            during = library.bind(destinations)
        self.assertEqual([b["id"] for b in before["bindings"]], [b["id"] for b in during["bindings"]])
        self.assertFalse(any(b["id"].startswith("rafii-") for b in before["bindings"]))

    def test_writer_adds_humanizer_and_workflow_skill_when_on(self):
        flags.attach({"RAFII_SKILL_REGISTRY_V2_ENABLED": "1"})
        library = SkillLibrary()
        with skill_compiler.workflow_context("rafii-weekly-operator"):
            bound = library.bind([{"platform": "Threads", "language": "zh-Hant-HK"}, {"platform": "LinkedIn", "language": "en"}], max_chars=120_000)
        ids = [b["id"] for b in bound["bindings"]]
        self.assertIn("rafii-humanizer-zh", ids)
        self.assertIn("rafii-humanizer-en", ids)
        self.assertIn("rafii-weekly-operator", ids)
        self.assertNotIn("rafii-source-to-campaign", ids)

    def test_extras_are_the_first_to_go_on_a_tight_budget(self):
        flags.attach({"RAFII_SKILL_REGISTRY_V2_ENABLED": "1"})
        library = SkillLibrary()
        base = library.bind([{"platform": "LinkedIn", "language": "en"}], max_chars=60_000)
        with skill_compiler.workflow_context("rafii-weekly-operator"):
            tight = library.bind([{"platform": "LinkedIn", "language": "en"}], max_chars=len(base["text"]) + 50)
        core = [b["id"] for b in base["bindings"] if not b["id"].startswith("rafii-")]
        self.assertEqual([b["id"] for b in tight["bindings"] if not b["id"].startswith("rafii-")], core)
        self.assertTrue(any(o["skill"].startswith("rafii-") for o in tight["omitted"]))

    def test_provenance_records_skills_overlays_route_and_trace(self):
        state = {"speaker": {"activeRevision": 3}, "brandHub": {"purpose": "Help small bakeries sell", "audience": "local families"},
                 "learning": {"revision": 4, "active": []}}
        compiled = skill_compiler.compile({"agent": "content", "intent": "draft", "platforms": ["X"]}, state=state)
        record = skill_compiler.provenance_for_run(compiled, writer_bindings=[{"id": "postriff-content-craft", "version": "1.2.0", "sha256": "a" * 64}],
                                                   route={"provider": "gateway", "model": "gpt-6-sol"}, trace_id="trace_" + "0" * 32, state=state, strategy_revision=7)
        self.assertTrue(record["registryRelease"].startswith("reg_"))
        self.assertEqual(record["overlays"]["voiceRevision"], 3)
        self.assertTrue(record["overlays"]["brandRevision"].startswith("bh_"))
        self.assertEqual(record["overlays"]["personalizationRevision"], "4.0")
        self.assertEqual(record["overlays"]["strategyRevision"], 7)
        self.assertEqual(record["modelRoute"]["model"], "gpt-6-sol")
        self.assertEqual(record["traceId"], "trace_" + "0" * 32)
        vias = {(s["id"], s["via"]) for s in record["skills"]}
        self.assertIn(("postriff-content-craft", "writer"), vias)
        self.assertIn(("postriff-content-craft", "compiler"), vias)

    def test_overlays_never_cross_workspaces(self):
        def workspace(statement):
            state = {"learning": {"revision": 1, "active": []}}
            overlays.ensure(state)["items"].append({"id": "ov1", "memoryType": "voice", "origin": "explicit", "statement": statement,
                                                    "scope": {}, "status": "active"})
            return state
        a, b = workspace("Always sign off as the Harbour Street Bakery team."), workspace("Use metric units.")
        compiled_b = skill_compiler.compile({"agent": "content", "intent": "draft", "platforms": ["X"]}, state=b)
        self.assertIn("Use metric units.", compiled_b["text"])
        self.assertNotIn("Harbour Street", compiled_b["text"])
        compiled_a = skill_compiler.compile({"agent": "content", "intent": "draft", "platforms": ["X"]}, state=a)
        self.assertNotIn("metric units", compiled_a["text"])

    def test_overlays_are_withheld_without_cloud_consent(self):
        state = {"learning": {"revision": 1, "active": []}}
        overlays.ensure(state)["items"].append({"id": "ov1", "memoryType": "brand", "origin": "explicit", "statement": "Our founder is Mei.",
                                                "scope": {}, "status": "active"})
        compiled = skill_compiler.compile({"agent": "content", "intent": "draft", "cloudAllowed": False}, state=state)
        self.assertNotIn("Mei", compiled["text"])
        self.assertIn("withheld", compiled["text"])


if __name__ == "__main__":
    unittest.main()
