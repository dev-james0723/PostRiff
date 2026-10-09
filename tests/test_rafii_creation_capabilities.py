"""Content Skills Integration P0 (spec ACCEPTANCE A01–A17): one creation-capability projection over the capability
registry and the channel skills' native-format tables, shared by validation, the writing routes and the composer.

Deterministic, zero-network. Model quality is not established here: these tests prove routing, schemas, provenance and
compatibility only (spec §14: automated routing tests do not establish editorial quality).
"""
import json
import os
import re
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_alpha import generation  # noqa: E402
from postriff_phase2 import agent_runtime, creation_capabilities as cc, ideas, intent, skills, skill_registry  # noqa: E402
from postriff_phase2.capabilities import publish_route  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.model_runtime import ServerModelRuntime, SYSTEM_PROMPT  # noqa: E402

WAVE1 = {"RAFII_CREATION_PROJECTION_ENABLED": "1"}
ALL = {"RAFII_CREATION_ALL_PLATFORMS_ENABLED": "1"}
OFF = {"RAFII_CREATION_PROJECTION_ENABLED": "", "RAFII_CREATION_ALL_PLATFORMS_ENABLED": ""}
CONTEXT = {"sources": [{"id": "src1", "policy": "approved", "candidateOnly": False,
                        "facts": [{"id": "f1", "sourceId": "src1", "text": "The community garden hosts a free seed-swap on Saturday.", "fixture": True}]}],
           "excluded": [], "candidateOnly": False}


def env(values):
    """Flags read from os.environ (no attached snapshot), isolated like the hosted app reads them."""
    return mock.patch.dict(os.environ, values)


class FlagIsolation(unittest.TestCase):
    def setUp(self):
        self._attached = flags._values
        flags.attach(None)
        cc._CACHE.clear()

    def tearDown(self):
        flags.attach(self._attached)
        cc._CACHE.clear()


class InventoryTest(FlagIsolation):
    """A01: every mapped platform and native format, recomputed from current authority."""

    def test_every_mapped_platform_is_a_row_with_registry_and_formats(self):
        proj = cc.projection(ALL)
        self.assertEqual(len(proj.rows), 33)
        self.assertEqual({r["platform"] for r in proj.rows}, set(skills.CHANNEL_SKILLS))
        self.assertEqual(sum(len(r["formats"]) for r in proj.rows), 56)
        registry = skill_registry.default_registry()
        channel_entries = [e for e in registry.entries if e["id"].startswith("postriff-channel-")]
        self.assertEqual(len(channel_entries), 33)
        for row in proj.rows:
            self.assertTrue(row["formats"], row["platform"])
            self.assertEqual(row["qualification"]["modelRoute"], "unverified")
            self.assertEqual(row["qualification"]["production"], "unverified")
            self.assertEqual(set(row["operations"]), set(cc.OPERATIONS))
            for op in row["operations"].values():
                self.assertIn(op["state"], cc.STATES)
                self.assertTrue(op["reason"])

    def test_registry_totals_are_entries_not_executable_skills(self):
        registry = skill_registry.default_registry()
        kinds = {}
        for entry in registry.entries:
            kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
        skill_backed = {s["id"] for e in registry.defaults() for s in e.get("hashSources") or [] if s.get("type") == "skill"}
        # Recomputed, not asserted from the earlier conversation: entries != installed skill packages.
        self.assertGreater(len(registry.entries), len(skill_backed))
        self.assertTrue(skill_backed >= set(skills.CHANNEL_SKILLS.values()))

    def test_format_tables_match_the_studio_profiles(self):
        sys.path.insert(0, str(ROOT / "src"))
        from james_au_social.channel_adapters import PROFILES
        theirs = {k: (v[0], list(v[1])) for _, (_, formats) in PROFILES.items() for k, v in formats.items()}
        mine = {f["id"]: (f["mediaKind"], f["nativeFields"]) for r in cc.projection().rows for f in r["formats"]}
        self.assertEqual(mine, theirs)


class RolloutTest(FlagIsolation):
    """A02, A11, A12: Facebook is reproduced as rejected, then fixed behind a reversible flag; the five stay."""

    def test_facebook_rejected_with_flags_off_and_accepted_on_wave_one(self):
        with env(OFF):
            with self.assertRaises(AlphaError) as caught:
                agent_runtime.check_destinations([{"platform": "Facebook", "language": "en"}])
            self.assertEqual(caught.exception.code, "platform_not_enabled")
            self.assertEqual(agent_runtime.draftable_platforms(), cc.ORIGINAL_PLATFORMS)
        cc._CACHE.clear()
        with env(WAVE1):
            agent_runtime.check_destinations([{"platform": "Facebook", "language": "en"}])
            self.assertIn("Facebook", agent_runtime.FixtureAgentRuntime().supported_platforms())
            self.assertNotIn("TikTok", agent_runtime.draftable_platforms())
        cc._CACHE.clear()
        with env(ALL):
            self.assertEqual(set(agent_runtime.draftable_platforms()), set(skills.CHANNEL_SKILLS))

    def test_original_five_never_depend_on_flags(self):
        for values in (OFF, WAVE1, ALL):
            cc._CACHE.clear()
            with env(values):
                agent_runtime.check_destinations([{"platform": p, "language": "en"} for p in cc.ORIGINAL_PLATFORMS])
        self.assertEqual(agent_runtime.PLATFORMS, cc.ORIGINAL_PLATFORMS)
        self.assertEqual(agent_runtime.DEFAULT_REQUEST_DESTINATIONS, ({"platform": "LinkedIn", "language": "en"}, {"platform": "Instagram", "language": "zh-Hant"}))

    def test_failed_projection_falls_back_to_the_five(self):
        with env(ALL), mock.patch.object(cc, "projection", side_effect=RuntimeError("registry unreadable")):
            self.assertEqual(cc.draftable_platforms(), cc.ORIGINAL_PLATFORMS)

    def test_missing_registry_blocks_extra_rows(self):
        class Broken:
            def release(self):
                raise ValueError("bad registry")
        proj = cc.projection(ALL, registry=Broken())
        self.assertEqual(proj.draftable(), ())
        self.assertTrue(all(r["operations"]["draft"]["reason"] == "registry_unavailable" for r in proj.rows))
        # validate_destinations still accepts the original five from its own fallback.
        cc.validate_destinations([{"platform": "LinkedIn", "language": "en"}], proj=proj)

    def test_registry_v2_flag_on_and_off_matches_bindings(self):
        library = skills.SkillLibrary()
        with env({"RAFII_SKILL_REGISTRY_V2_ENABLED": ""}):
            ids = [b["id"] for b in library.bind([{"platform": "Facebook", "language": "zh-Hant-HK"}])["bindings"]]
            self.assertFalse(any("humanizer" in i for i in ids))
        with env({"RAFII_SKILL_REGISTRY_V2_ENABLED": "1"}):
            # On the paid route's 60 kB budget the Humanizer pack is the first to go, and it is recorded as omitted,
            # never reported as executed; the subscription budget carries it.
            paid = library.bind([{"platform": "Facebook", "language": "zh-Hant-HK"}], max_chars=skills.MAX_TEXT_CHARS)
            self.assertNotIn("rafii-humanizer-zh", [b["id"] for b in paid["bindings"]])
            self.assertIn("rafii-humanizer-zh", [o["skill"] for o in paid["omitted"]])
            roomy = library.bind([{"platform": "Facebook", "language": "zh-Hant-HK"}], max_chars=skills.SUBSCRIPTION_TEXT_CHARS)
            self.assertIn("rafii-humanizer-zh", [b["id"] for b in roomy["bindings"]])


class ValidationTest(FlagIsolation):
    """A04, A06, A12: forged, retired, private or duplicated requests fail with stable codes."""

    def codes(self, destinations, **kwargs):
        try:
            cc.validate_destinations(destinations, **kwargs)
        except AlphaError as error:
            return error.code
        return "ok"

    def test_stable_error_codes(self):
        with env(WAVE1):
            self.assertEqual(self.codes([{"platform": "MySpace", "language": "en"}]), "unknown_platform")
            self.assertEqual(self.codes([{"platform": "TikTok", "language": "en"}]), "platform_not_enabled")
            self.assertEqual(self.codes([{"platform": "Facebook", "language": "en", "format": "facebook.carousel"}]), "unknown_format")
            self.assertEqual(self.codes([{"platform": "Facebook", "language": "en", "format": "instagram.reel"}]), "format_platform_mismatch")
            self.assertEqual(self.codes([{"platform": "Facebook", "language": "xx-Nope"}]), "unknown_language")
            self.assertEqual(self.codes([{"platform": "Facebook", "language": "en"}], revision="cap_stale"), "schema_revision_mismatch")
            self.assertEqual(self.codes([{"platform": "Facebook", "language": "en"}], revision=cc.projection().revision), "ok")

    def test_private_and_unknown_skills_are_never_rows(self):
        ids = {r["skill"]["id"] for r in cc.projection(ALL).rows}
        self.assertFalse(any(i.startswith("james-au-") for i in ids))
        self.assertIsNone(skills.SkillLibrary().load("james-au-content-craft"))

    def test_two_accounts_formats_and_locales_stay_distinct(self):
        with env(WAVE1):
            distinct = [{"platform": "Facebook", "language": "en", "channelId": "page-a"}, {"platform": "Facebook", "language": "en", "channelId": "page-b"},
                        {"platform": "Facebook", "language": "en", "channelId": "page-a", "format": "facebook.reel"},
                        {"platform": "Facebook", "language": "zh-Hant-HK", "channelId": "page-a"}]
            self.assertEqual(self.codes(distinct), "ok")
            self.assertEqual(self.codes(distinct + [{"platform": "Facebook", "language": "en", "channelId": "page-a", "format": "facebook.page_post"}]), "duplicate_destination")
        requested = [{"platform": "Instagram", "language": "en", "format": "instagram.carousel"}, {"platform": "Instagram", "language": "en", "format": "instagram.reel"}]
        out = intent.resolve_destinations(intent.parse_request("A post", 1_789_000_000.0, "Asia/Hong_Kong", cc.ORIGINAL_PLATFORMS), requested, None, ())
        self.assertEqual([d.get("format") for d in out], ["instagram.carousel", "instagram.reel"])
        self.assertFalse(ideas.same_slot({"platform": "Instagram", "language": "en", "format": "instagram.reel"}, {"platform": "Instagram", "language": "en"}))
        self.assertTrue(ideas.same_slot({"platform": "Instagram", "language": "en"}, {"platform": "Instagram", "language": "en", "format": "instagram.post"}))

    def test_cross_workspace_account_binding_is_rejected(self):
        state = {"phase2": {"channels": [{"id": "page-a", "platform": "Facebook", "account": "Garden Page"}]}}
        with self.assertRaises(AlphaError):
            intent.bind_accounts([{"platform": "Facebook", "language": "en", "channelId": "someone-elses-page"}], state)
        with self.assertRaises(AlphaError):
            intent.bind_accounts([{"platform": "Instagram", "language": "en", "channelId": "page-a"}], state)

    def test_agent_tool_cannot_enable_a_platform_by_naming_it(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools
        self.assertEqual(set(domain_tools.MAPPED_PLATFORMS), set(skills.CHANNEL_SKILLS))
        with env(OFF):
            self.assertFalse(domain_tools._draftable("Facebook"))
            self.assertTrue(domain_tools._draftable("Instagram"))


class WriterRouteTest(FlagIsolation):
    """A05, A07, A13, A15: drafts without OAuth, native fields, Facebook Page reference, readiness separation."""

    def run_fixture(self, destinations):
        events = []
        result = agent_runtime.FixtureAgentRuntime().start_turn({"context": CONTEXT, "idea": "seed swap", "destinations": destinations}, events.append)
        return result["artifact"]["variants"], events

    def test_unconnected_facebook_and_instagram_drafts_and_export(self):
        with env(WAVE1):
            variants, events = self.run_fixture([{"platform": "Facebook", "language": "en"}, {"platform": "Instagram", "language": "en", "format": "instagram.carousel"}])
            cc.attach_native(variants)
            self.assertEqual([v["platform"] for v in variants], ["Facebook", "Instagram"])
            facebook, instagram = variants
            self.assertNotIn("channelId", facebook)
            self.assertEqual(facebook["native"]["formatId"], "facebook.page_post")
            self.assertEqual(facebook["native"]["unresolved"], ["page_ref"])  # A07: explicit, never substituted
            self.assertEqual(instagram["native"]["formatId"], "instagram.carousel")
            self.assertEqual(instagram["native"]["media"]["state"], "needs_input")
            self.assertEqual(instagram["native"]["readiness"]["publish"], "not_checked")
            package = cc.export_package(variants)
            self.assertFalse(package["published"])
            self.assertEqual(len(package["files"]), 2)
            self.assertIn("Source note", package["files"][0]["text"]) if "Source note" in facebook["text"] else None
        # Publishing an unbound Facebook draft is refused by the existing live chain (no account substitution).
        route = publish_route({"phase2": {"channels": [{"id": "p", "platform": "Facebook", "account": "Other Page"}]}}, {"platform": "Facebook"},
                              providers={"facebook": type("A", (), {"production_reviewed": True, "execution_enabled": True})()}, live=True)
        self.assertFalse(route["publish"])
        self.assertEqual(route["code"], "choose_account")

    def test_every_format_has_a_positive_and_negative_native_case(self):
        proj = cc.projection(ALL)
        for row in proj.rows:
            for fmt in row["formats"]:
                variant = {"platform": row["platform"], "language": "en", "format": fmt["id"], "text": "First paragraph.\n\nSecond paragraph.", "privateNotes": ["internal: shoot at dusk"]}
                native = cc.native_draft(variant, proj)
                self.assertEqual(native["formatId"], fmt["id"])
                self.assertEqual(native["unresolved"], [f for f in fmt["bindingFields"]])
                self.assertNotIn("dusk", cc.text_projection(native))
                self.assertEqual(native["media"]["required"], fmt["mediaKind"])
                ok, errors = cc.validate_native_fields(row["platform"], fmt["id"], {"caption": "x"}, proj)
                self.assertEqual(errors, [])
                _, errors = cc.validate_native_fields(row["platform"], fmt["id"], {"page_secret": "x", "caption": 3}, proj)
                self.assertIn("field_not_allowed:page_secret", errors)
                self.assertIn("type_invalid:caption", errors)
                if "slides" in fmt["draftFields"]:
                    _, errors = cc.validate_native_fields(row["platform"], fmt["id"], {"slides": [{"index": 2, "text": "b"}, {"index": 1, "text": "a"}]}, proj)
                    self.assertEqual(errors, ["order_invalid:slides"])
                self.assertFalse(native["constraints"]["verified"])

    def test_instagram_and_facebook_formats_are_distinct_from_media_and_publishing(self):
        proj = cc.projection(WAVE1)
        self.assertEqual([f["id"] for f in proj.by_platform["Instagram"]["formats"]], ["instagram.post", "instagram.carousel", "instagram.story", "instagram.reel"])
        self.assertEqual(sorted(f["id"] for f in proj.by_platform["Facebook"]["formats"]), ["facebook.page_post", "facebook.reel", "facebook.story"])
        reel = next(f for f in proj.by_platform["Instagram"]["formats"] if f["id"] == "instagram.reel")
        self.assertEqual(reel["media"]["reason"], "video_input_required")
        self.assertIn("spokenScript", reel["draftFields"])
        self.assertEqual(proj.by_platform["Facebook"]["operations"]["publish"]["reason"], "live_check_required")
        self.assertEqual(proj.by_platform["Xiaohongshu"]["operations"]["publish"]["reason"], "no_publisher")

    def test_text_projection_is_faithful_including_xiaohongshu_title_first(self):
        with env(ALL):
            for platform in sorted(skills.CHANNEL_SKILLS):
                for language in ("en", "zh-Hans-CN", "zh-Hant-TW", "zh-Hant-HK", "yue-Hant-HK"):
                    variants, _ = self.run_fixture([{"platform": platform, "language": language}])
                    cc.attach_native(variants)
                    self.assertEqual(cc.text_projection(variants[0]["native"]), variants[0]["text"], (platform, language))
        native = cc.native_draft({"platform": "Xiaohongshu", "language": "zh-Hans-CN", "text": "标题在这里\n\n正文第一段"})
        self.assertEqual(native["fields"]["title"], "标题在这里")
        self.assertEqual(cc.text_projection(native), "标题在这里\n\n正文第一段")

    def test_user_edit_wins_over_a_stored_native_draft(self):
        variant = {"platform": "Instagram", "language": "en", "format": "instagram.carousel", "text": "a\n\nb"}
        cc.attach_native([variant])
        variant["text"] = "edited\n\nsecond\n\nthird"
        current = cc.current_native(variant)
        self.assertEqual(current["fields"]["caption"], variant["text"])
        self.assertEqual([s["text"] for s in current["fields"]["slides"]], ["edited", "second", "third"])


class LocaleTest(FlagIsolation):
    """A16 (deterministic writer only): script and register choices are explicit, facts are preserved."""

    def test_four_chinese_choices_are_distinct_tags_with_their_guides(self):
        from postriff_phase2 import locales
        tags = [locales.canonical(t) for t in ("zh-Hans-CN", "zh-Hant-TW", "zh-Hant-HK", "yue-Hant-HK")]
        self.assertEqual(len(set(tags)), 4)
        library = skills.SkillLibrary()
        for tag in tags:
            bound = library.bind([{"platform": "Facebook", "language": tag}])
            engine = next(b for b in bound["bindings"] if b["id"] == "postriff-content-engine")
            self.assertTrue(any(f["path"].startswith("references/locales/") for f in engine["files"]), tag)

    def test_simplified_and_traditional_scripts_follow_the_tag(self):
        from postriff_phase2 import locale_lint
        with env(ALL):
            for platform in ("Weibo", "Zhihu", "Douyin", "Bilibili", "WeChat Channels", "Facebook"):
                hans = generation.FixtureAdapter().generate({"platform": platform, "language": "zh-Hans-CN", "facts": CONTEXT["sources"][0]["facts"], "idea": "x"})["text"]
                hant = generation.FixtureAdapter().generate({"platform": platform, "language": "zh-Hant-TW", "facts": CONTEXT["sources"][0]["facts"], "idea": "x"})["text"]
                self.assertEqual(locale_lint.reminders(hans, "zh-Hans-CN", platform), [], platform)
                self.assertEqual(locale_lint.reminders(hant, "zh-Hant-TW", platform), [], platform)
                self.assertIn("种子", hans)
                self.assertIn("種子", hant)


class SkillRouteTest(FlagIsolation):
    """A08, A09, A10: required instructions reach the writer whole, or the draft says it is generic."""

    def test_every_draftable_route_binds_core_contract_and_adapter_with_hashes(self):
        library = skills.SkillLibrary()
        with env(ALL):
            for platform in agent_runtime.draftable_platforms():
                bound = library.bind([{"platform": platform, "language": "en"}])
                route = cc.skill_route(platform, bound["bindings"], bound["omitted"])
                self.assertTrue(route["qualified"], (platform, route))
                for item in route["required"]:
                    self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                    self.assertTrue(item["version"])
                adapter = next(b for b in bound["bindings"] if b["id"] == skills.CHANNEL_SKILLS[platform])
                self.assertIn(f"## Skill: {adapter['id']}", bound["text"])

    def test_missing_library_or_adapter_is_a_generic_draft(self):
        self.assertTrue(cc.skill_route("Facebook", [], [])["generic"])
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("postriff-content-craft", "postriff-content-engine", "postriff-adapter-contract"):
                shutil.copytree(ROOT / "skills" / name, Path(tmp) / name)
            bound = skills.SkillLibrary(tmp).bind([{"platform": "Facebook", "language": "en"}])
            route = cc.skill_route("Facebook", bound["bindings"], bound["omitted"])
            # Without an installed adapter the shared adapter contract is not bound either.
            self.assertEqual(route["missing"], ["postriff-adapter-contract", "postriff-channel-facebook"])
            variants = [{"platform": "Facebook", "language": "en", "text": "x"}]
            cc.attach_native(variants, bindings=bound["bindings"], omissions=bound["omitted"])
            self.assertTrue(variants[0]["native"]["skillRoute"]["generic"])
            self.assertIn("Unvalidated generic draft", " ".join(variants[0]["warnings"]))

    def test_multi_platform_cjk_budget_drops_whole_files_and_records_cuts(self):
        library = skills.SkillLibrary()
        destinations = [{"platform": p, "language": t} for p in ("Xiaohongshu", "Weibo", "Zhihu", "Douyin", "Bilibili", "WeChat Channels", "Facebook", "Instagram")
                        for t in ("zh-Hans-CN", "zh-Hant-HK")]
        bound = library.bind(destinations, max_chars=60_000)
        self.assertLessEqual(len(bound["text"].encode()), 60_000)
        self.assertFalse(any(o.get("cut") for o in bound["omitted"]))
        for platform in {d["platform"] for d in destinations}:
            self.assertTrue(cc.skill_route(platform, bound["bindings"], bound["omitted"])["qualified"], platform)
        tight = library.bind(destinations, max_chars=9_000)
        self.assertTrue(any(o.get("cut") for o in tight["omitted"]))
        self.assertTrue(cc.skill_route("Facebook", tight["bindings"], tight["omitted"])["generic"])


class ModelRouteTest(FlagIsolation):
    """A12/A13 on the paid writer's contract: unchanged prompt for existing turns; native fields parsed into slots."""

    def test_existing_turns_keep_the_exact_prompt(self):
        request = {"context": CONTEXT, "destinations": [{"platform": "LinkedIn", "language": "en"}]}
        self.assertEqual(ServerModelRuntime._system_prompt(request), SYSTEM_PROMPT)
        payload = ServerModelRuntime._user_payload(request)
        self.assertEqual(payload["destinations"][0], {"platform": "LinkedIn", "language": "English (no region chosen)", "languageId": "en", "characterLimit": 3000})

    def test_native_turn_adds_rule_slots_and_no_invented_limit(self):
        with env(ALL):
            request = {"context": CONTEXT, "destinations": [{"platform": "Dcard", "language": "zh-Hant-TW"}, {"platform": "Instagram", "language": "en", "format": "instagram.carousel"}]}
            self.assertIn("13. A destination with \"format\"", ServerModelRuntime._system_prompt(request))
            dcard, ig = ServerModelRuntime._user_payload(request)["destinations"]
            self.assertIsNone(dcard["characterLimit"])
            self.assertEqual(dcard["format"], "dcard.post")
            self.assertIn("title", dcard["draftFields"])
            self.assertIn("slides", ig["draftFields"])
            content = json.dumps({"variants": [
                {"platform": "Dcard", "language": "zh-Hant-TW", "format": "dcard.post", "text": "內文", "nativeFields": {"title": "標題", "board_ref": "forged"}, "sourceIds": ["src1"]},
                {"platform": "Instagram", "language": "en", "format": "instagram.carousel", "text": "Body", "nativeFields": {"slides": ["one", "two"]}, "sourceIds": []}]})
            dcard_v, ig_v = ServerModelRuntime._parse(content, request["destinations"], CONTEXT)
            self.assertEqual(dcard_v["nativeFields"], {"title": "標題"})
            self.assertTrue(any("board_ref" in w for w in dcard_v["warnings"]))
            self.assertEqual(ig_v["nativeFields"]["slides"], [{"index": 1, "text": "one"}, {"index": 2, "text": "two"}])
            self.assertEqual(ig_v["format"], "instagram.carousel")


class PackReviewTest(unittest.TestCase):
    """A17 (automated part): no shipped channel adapter or shared playbook demands hashtag quotas, promises reach, or
    tells the writer to invent experience. Editorial quality itself still needs the human/paired review."""

    BANNED = (r"\b(always|must)\s+(use|include|add)\s+\d+\s+hashtags", r"guarantee[sd]?\s+(reach|views|virality|growth)",
              r"\binvent\s+(a|an)\s+(personal|anecdote|story)")

    def test_no_blanket_algorithm_claims_or_quotas(self):
        files = list((ROOT / "skills").glob("postriff-channel-*/SKILL.md")) + [ROOT / "skills/postriff-content-craft/references/platform-playbooks.md"]
        for path in files:
            text = path.read_text()
            for pattern in self.BANNED:
                self.assertIsNone(re.search(pattern, text, re.I), (path.name, pattern))

    def test_web_fallback_matches_the_server_original_set(self):
        composer = (ROOT / "web/src/features/agent/composer.tsx").read_text()
        listed = re.search(r"export const DRAFT_PLATFORMS = \[([^\]]*)\]", composer).group(1)
        self.assertEqual(sorted(re.findall(r"'([^']+)'", listed)), sorted(cc.ORIGINAL_PLATFORMS))
        self.assertEqual(set(generation.PLATFORMS) | set(generation.NATIVE_PLATFORMS), set(skills.CHANNEL_SKILLS))


if __name__ == "__main__":
    unittest.main()
