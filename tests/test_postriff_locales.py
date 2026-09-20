"""Languages per channel (docs/postriff-worldwide-languages-plan.md): locale tags, message pairing,
several languages on one channel, locale guides, reminders, remembered picks and learned scopes."""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha import learning  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import intent, locale_lint, locales, memory  # noqa: E402
from postriff_phase2.agent_runtime import FixtureAgentRuntime  # noqa: E402
from postriff_phase2.model_runtime import ServerModelRuntime  # noqa: E402
from postriff_phase2.skills import SkillLibrary  # noqa: E402
from postriff_phase2.text_measure import measure  # noqa: E402

HK = "Asia/Hong_Kong"
SUPPORTED = ("LinkedIn", "Instagram", "Threads", "Xiaohongshu")
NOW = datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo(HK)).timestamp()
FOUR = [{"platform": "LinkedIn", "language": "en-GB"}, {"platform": "Xiaohongshu", "language": "zh-Hans-CN"},
        {"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Threads", "language": "en-US"}]


def resolve(text, requested=FOUR, settings=None):
    return intent.resolve_destinations(intent.parse_request(text, NOW, HK, SUPPORTED), requested, None, (), settings=settings)


class Catalogue(unittest.TestCase):
    def test_python_and_web_read_the_same_bytes(self):
        self.assertEqual((ROOT / "src/postriff_phase2/locale_catalogue.json").read_bytes(), (ROOT / "web/src/lib/locales/catalogue.generated.json").read_bytes(),
                         "run node scripts/build_locale_catalogue.mjs")

    def test_every_researched_locale_has_its_guide_and_a_stable_tag(self):
        guides = ROOT / "skills/postriff-content-engine"
        for entry in locales.catalogue()["entries"]:
            with self.subTest(tag=entry["tag"]):
                self.assertEqual(locales.canonical(entry["tag"], family_ok=True), entry["tag"])
                if entry["guide"]:
                    self.assertTrue((guides / entry["guide"]).is_file())
        for family in locales.catalogue()["familyGuides"]:
            self.assertTrue((guides / f"references/locales/_family-{family}.md").is_file())
        self.assertTrue((guides / "references/locales/_generic.md").is_file())

    def test_chinese_names_lead_with_script_and_never_say_mainland(self):
        names = {tag: locales.display(tag) for tag in ("zh-Hant-HK", "yue-Hant-HK", "zh-Hant-TW", "zh-Hans-CN", "zh-Hans-SG")}
        self.assertEqual(names, {"zh-Hant-HK": "繁體中文（香港）", "yue-Hant-HK": "廣東話（香港）", "zh-Hant-TW": "繁體中文（台灣）", "zh-Hans-CN": "简体中文（中国）", "zh-Hans-SG": "简体中文（新加坡）"})
        self.assertEqual(locales.entry("en-GB-scotland")["flag"], "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f")
        self.assertEqual((locales.entry("zh-Hant-HK")["flag"], locales.entry("en")["flag"], locales.entry("es-419")["flag"], locales.entry("ar-001")["flag"]), ("🇭🇰", "🌐", "🌎", "🌍"))


class Canonical(unittest.TestCase):
    def test_legacy_values_aliases_casing_and_names(self):
        cases = {"English": "en", "繁體中文": "zh-Hant", "zh-HK": "zh-Hant-HK", "zh_tw": "zh-Hant-TW", "zh-hant-hk": "zh-Hant-HK", "yue": "yue-Hant-HK",
                 "EN-gb": "en-GB", "en-gb-scotland": "en-GB-scotland", "tl": "fil-PH", "ja": "ja-JP", "日本語": "ja-JP", "简体中文（中国）": "zh-Hans-CN",
                 "es-cl": "es-CL", "fr-LU": "fr-LU", "zh-SG": "zh-Hans-SG", "arz": "ar-EG"}
        for value, tag in cases.items():
            with self.subTest(value=value):
                self.assertEqual(locales.canonical(value), tag)

    def test_what_is_not_a_language(self):
        for value in (None, "", "klingon", "x-private", "en-u-ca-gregory", "zz-ZZ", "zh", "a" * 80):
            with self.subTest(value=value):
                self.assertIsNone(locales.canonical(value))
        self.assertEqual(locales.canonical("zh", family_ok=True), "zh")
        self.assertTrue(locales.same("繁體中文", "zh-hant"))

    def test_scope_chain_reaches_parents_and_families(self):
        self.assertEqual(locales.scope_chain("yue-Hant-HK"), ["yue-Hant-HK", "yue-Hant", "yue", "zh-Hant-HK", "zh-Hant", "zh"])
        self.assertIn("es-419", locales.scope_chain("es-MX"))
        self.assertEqual(locales.scope_chain("English"), ["en"])


class NamedInTheMessage(unittest.TestCase):
    def test_only_language_names_after_an_instruction_count(self):
        def said(text):
            return [(h["tag"], h["said"]) for h in locales.named_languages(text)]
        self.assertEqual(said("Write a post about Sunday's recital in Japanese."), [("ja-JP", "Japanese")])
        self.assertEqual(said("Instagram in Hong Kong Chinese and British English."), [("zh-Hant-HK", "Hong Kong Chinese"), ("en-GB", "British English")])
        self.assertEqual(said("幫我用繁體中文同英文寫 Instagram"), [("zh-Hant", "繁體中文"), ("en", "英文")])
        self.assertEqual(said("寫成廣東話"), [("yue-Hant-HK", "廣東話")])
        self.assertEqual(said("A post about the Japanese food we had after the recital in Hong Kong."), [])
        self.assertEqual(said("Our show in Taiwan was sold out"), [])

    def test_the_four_channel_example_keeps_every_channels_language(self):
        self.assertEqual(resolve("Tell me a topic for a post about Sunday's recital."), FOUR)

    def test_a_language_for_one_channel_changes_only_that_channel(self):
        rows = resolve("Sunday's recital post. Threads in British English, and 小紅書用台灣中文寫。")
        self.assertEqual(rows, [{"platform": "LinkedIn", "language": "en-GB"}, {"platform": "Xiaohongshu", "language": "zh-Hant-TW"},
                                {"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Threads", "language": "en-GB"}])

    def test_a_language_with_no_channel_applies_to_every_channel(self):
        rows = resolve("Write a post about Sunday's recital in Japanese.")
        self.assertEqual({row["language"] for row in rows}, {"ja-JP"})
        self.assertEqual([row["platform"] for row in rows], ["LinkedIn", "Xiaohongshu", "Instagram", "Threads"])

    def test_joined_languages_give_one_channel_several_destinations(self):
        rows = resolve("Instagram in Hong Kong Chinese and British English.")
        self.assertEqual([row for row in rows if row["platform"] == "Instagram"], [{"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Instagram", "language": "en-GB"}])
        self.assertEqual(len(rows), 5)

    def test_a_family_name_keeps_a_regional_pick(self):
        rows = resolve("write it in Chinese", requested=[{"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Threads", "language": "en-US"}])
        self.assertEqual(rows, [{"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Threads", "language": "zh-Hant"}])

    def test_a_channel_named_only_with_a_language_joins_the_selection(self):
        rows = resolve("Xiaohongshu in Simplified Chinese please", requested=[{"platform": "LinkedIn", "language": "en-GB"}])
        self.assertEqual(rows, [{"platform": "LinkedIn", "language": "en-GB"}, {"platform": "Xiaohongshu", "language": "zh-Hans-CN"}])

    def test_a_channel_named_with_a_time_still_replaces_the_selection(self):
        rows = resolve("Instagram at 4pm today", requested=FOUR)
        self.assertEqual(rows, [{"platform": "Instagram", "language": "zh-Hant-HK"}])

    def test_one_channel_can_carry_several_languages_from_the_composer(self):
        requested = FOUR + [{"platform": "Instagram", "language": "en-GB"}, {"platform": "Instagram", "language": "en-gb"}]
        rows = resolve("A topic please", requested=requested)
        self.assertEqual([row["language"] for row in rows if row["platform"] == "Instagram"], ["zh-Hant-HK", "en-GB"])


class RememberedLanguages(unittest.TestCase):
    def test_a_channel_starts_with_what_it_used_last_then_its_usual_language_then_the_default(self):
        state = {"languageSettings": {"channels": {"Threads": ["en-US", "yue-Hant-HK"]}, "default": "en-GB"}}
        self.assertEqual(locales.languages_for("Threads", state), ["en-US", "yue-Hant-HK"])
        self.assertEqual(locales.languages_for("Xiaohongshu", state), ["zh-Hans-CN"])
        self.assertEqual(locales.languages_for("LinkedIn", state), ["en-GB"])
        self.assertEqual(locales.languages_for("LinkedIn", {}), ["en"])
        rows = resolve("Threads tomorrow 3pm", requested=[], settings=lambda: state)
        self.assertEqual(rows, [{"platform": "Threads", "language": "en-US"}, {"platform": "Threads", "language": "yue-Hant-HK"}])

    def test_the_settings_action_merges_validates_and_lands_in_identity(self):
        state = {}
        self.assertTrue(locales.apply_language_action(state, "language_settings", {"channels": {"Instagram": ["zh-HK", "en-GB"], "Threads": ["en-US"]}}, "owner", 100))
        self.assertTrue(locales.apply_language_action(state, "language_settings", {"channels": {"Threads": []}, "default": "en-GB", "selfReference": "neutral"}, "owner", 101))
        self.assertEqual(locales.settings(state), {"default": "en-GB", "channels": {"Instagram": ["zh-Hant-HK", "en-GB"]}, "selfReference": "neutral"})
        self.assertFalse(locales.apply_language_action(state, "memory_egress", {}, "owner", 102))
        for bad in ({"channels": {"Instagram": ["klingon"]}}, {"channels": {"Instagram": ["en", "fr", "de", "es", "ja"]}}, {"selfReference": "yes"}, {"default": "zz"}):
            with self.subTest(payload=bad), self.assertRaises(AlphaError):
                locales.apply_language_action(state, "language_settings", bad, "owner", 103)
        identity = next(f["body"] for f in memory.render_files(state) if f["name"] == "IDENTITY.md")
        self.assertIn("Referring to yourself in languages that mark gender: use neutral wording wherever the grammar allows", identity)


class Drafting(unittest.TestCase):
    def test_the_fixture_route_writes_each_pair_and_refuses_unknown_or_repeated_ones(self):
        events = []
        destinations = [{"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Instagram", "language": "en-GB"}, {"platform": "Xiaohongshu", "language": "zh-Hans-CN"}]
        result = FixtureAgentRuntime().start_turn({"context": {"sources": [], "excluded": [], "candidateOnly": False}, "idea": "x", "destinations": destinations}, events.append)
        self.assertEqual([(v["platform"], v["language"]) for v in result["artifact"]["variants"]], [(d["platform"], d["language"]) for d in destinations])
        for bad in ([{"platform": "Instagram", "language": "klingon"}], [{"platform": "Instagram", "language": "en"}, {"platform": "Instagram", "language": "English"}], [{"platform": "Weibo", "language": "zh-Hans-CN"}]):
            with self.subTest(destinations=bad), self.assertRaises(AlphaError):
                FixtureAgentRuntime().start_turn({"context": {"sources": [], "excluded": [], "candidateOnly": False}, "destinations": bad}, events.append)

    def test_the_cloud_route_names_each_locale_and_reads_echoed_languages(self):
        request = {"context": {"sources": [], "excluded": []}, "destinations": [{"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Instagram", "language": "en-GB"}]}
        payload = ServerModelRuntime._user_payload(request)
        self.assertEqual([(d["languageId"], d["language"]) for d in payload["destinations"]],
                         [("zh-Hant-HK", "Standard written Chinese as used in Hong Kong (Traditional characters, Hong Kong vocabulary)"), ("en-GB", "British English")])
        content = json.dumps({"variants": [{"platform": "Instagram", "language": "en-gb", "text": "Programme notes are in the comments."},
                                           {"platform": "Instagram", "language": "zh-Hant-HK", "text": "星期日見。"}]}, ensure_ascii=False)
        variants = ServerModelRuntime._parse(content, request["destinations"], request["context"])
        self.assertEqual([(v["language"], v["text"]) for v in variants], [("zh-Hant-HK", "星期日見。"), ("en-GB", "Programme notes are in the comments.")])

    def test_each_destination_language_binds_its_guide(self):
        library = SkillLibrary()

        def files(destinations):
            bound = library.bind(destinations)
            return [f["path"] for b in bound["bindings"] if b["id"] == "postriff-content-engine" for f in b["files"]]
        self.assertIn("references/locales/en-GB.md", files([{"platform": "LinkedIn", "language": "en-GB"}]))
        self.assertNotIn("references/localization.md", files([{"platform": "LinkedIn", "language": "en-GB"}]))
        both = files([{"platform": "Instagram", "language": "zh-Hant-HK"}, {"platform": "Instagram", "language": "en-GB"}])
        self.assertTrue({"references/localization.md", "references/locales/zh-Hant-HK.md", "references/locales/en-GB.md"} <= set(both))
        self.assertEqual([p for p in files([{"platform": "LinkedIn", "language": "es-CL"}]) if "locales/" in p],
                         ["references/locales/es-419.md", "references/locales/_family-es.md", "references/locales/_generic.md"])
        self.assertEqual([p for p in files([{"platform": "LinkedIn", "language": "繁體中文"}]) if "locales/" in p],
                         ["references/locales/_family-zh.md", "references/locales/_generic.md"])


class Reminders(unittest.TestCase):
    def test_wrong_script_other_regions_words_and_local_rules(self):
        self.assertIn("Simplified", locale_lint.reminders("这是我们的新作品。", "zh-Hant-HK")[0])
        self.assertIn("Traditional", locale_lint.reminders("這是我們的新作品。", "zh-Hans-CN")[0])
        self.assertIn("軟件 → 軟體", locale_lint.reminders("新軟件上線了", "zh-Hant-TW")[0])
        self.assertIn("color → colour", locale_lint.reminders("A new color for the season", "en-GB")[0])
        self.assertTrue(any("Xiaohongshu" in w for w in locale_lint.reminders("加我微信聊", "zh-Hans-CN", "Xiaohongshu")))
        self.assertTrue(any("税込" in w for w in locale_lint.reminders("チケットは3,000円です", "ja-JP")))
        self.assertEqual(locale_lint.reminders("星期日晚喺大會堂見。", "yue-Hant-HK"), [])
        self.assertEqual(locale_lint.reminders("The colour of autumn", "en-GB"), [])
        self.assertTrue(all(len(pair) == 2 for pair in locale_lint._PAIRS))

    def test_x_counts_cjk_twice_and_everything_else_in_code_points(self):
        self.assertEqual(measure("X", "hi 你好")["used"], 7)
        self.assertEqual(measure("Threads", "hi 你好 🎹"), {"used": 7, "limit": 500, "unit": "codepoint"})
        self.assertEqual(measure("Xiaohongshu", "")["limit"], 1000)


class LearnedScopes(unittest.TestCase):
    def test_old_scopes_keep_applying_and_parents_cover_their_regions(self):
        state = {"learning": learning.initial(), "preferences": [], "speaker": {}}
        state["learning"]["migratedAt"] = "2026-09-01T00:00:00+00:00"
        state["learning"]["active"] = [{"id": "a", "type": "writing_preference", "ruleKey": "hashtags.use", "polarity": "avoid", "status": "active", "statement": "No hashtags.",
                                        "scope": {"platform": "Instagram", "language": "繁體中文", "contentTypeId": None}, "scopeKey": "writing_preference|hashtags.use|avoid|Instagram|繁體中文|*"}]
        learning.ensure(state, NOW)
        item = state["learning"]["active"][0]
        self.assertEqual((item["scope"]["language"], item["scopeKey"]), ("zh-Hant", "writing_preference|hashtags.use|avoid|Instagram|zh-Hant|*"))
        for language, expected in (("zh-Hant-HK", True), ("yue-Hant-HK", True), ("zh-Hant-TW", True), ("繁體中文", True), ("zh-Hans-CN", False), ("en-GB", False)):
            with self.subTest(language=language):
                self.assertEqual(learning.applies(item, "Instagram", language), expected)
        chinese_wide = {"scope": {"platform": None, "language": "zh"}}
        self.assertTrue(learning.applies(chinese_wide, "Threads", "yue-Hant-HK"))
        self.assertTrue(learning.applies({"scope": {"language": "en"}}, "LinkedIn", "en-GB-scotland"))
        self.assertEqual(learning.canonical_scope_key("writing_preference|closing.cta|do|*|English|*"), "writing_preference|closing.cta|do|*|en|*")


if __name__ == "__main__":
    unittest.main()
