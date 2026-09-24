"""X as a draftable, never-publishable destination, and platform-shaped drafting (Rafii v9 orchestration, platforms slice).

X joins the drafting vocabulary (runtime platforms, limits, intent aliases, fixture writer, channel skills) while
nothing gives it a publishing route: hosted_social maps LinkedIn/Threads/Instagram only and the local fixture store
refuses to simulate an X (or Xiaohongshu) account.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_alpha import generation  # noqa: E402
from postriff_alpha.generation import FixtureAdapter  # noqa: E402
from postriff_phase2 import agent_runtime, cli_runtime, intent, locale_lint, skills  # noqa: E402
from postriff_phase2.contracts import LIMITS  # noqa: E402
from postriff_phase2.hosted import HostedPhase2Commands  # noqa: E402
from postriff_phase2.hosted_social import HostedSocial  # noqa: E402
from postriff_phase2.model_runtime import ServerModelRuntime  # noqa: E402
from postriff_phase2.text_measure import measure, over_by  # noqa: E402

NOW = 1_789_000_000.0
HK = "Asia/Hong_Kong"
DRAFTABLE = agent_runtime.PLATFORMS


def named(text, supported=DRAFTABLE):
    return [d["platform"] for d in intent.parse_request(text, NOW, HK, supported)["destinations"]]


def fixture(platform, language="en", facts=(), idea="Share the seed swap", **extra):
    return FixtureAdapter().generate({"platform": platform, "language": language, "facts": list(facts), "idea": idea, **extra})


LONG_FACTS = [{"text": f"Fact {n} says something moderately long about the community garden and its seed swap plans.", "sourceId": f"s{n}"} for n in range(5)]
SAMPLE = [{"text": en, "sourceId": "sample", "fixture": True} for en, _ in generation.SAMPLE_FACTS]


class Vocabulary(unittest.TestCase):
    def test_x_is_a_drafting_platform_with_a_280_character_post_limit(self):
        self.assertEqual(agent_runtime.PLATFORMS, ("LinkedIn", "Instagram", "Threads", "X", "Xiaohongshu"))
        self.assertEqual(generation.PLATFORMS, agent_runtime.PLATFORMS, "the fixture writer drafts every runtime platform")
        self.assertEqual(LIMITS["X"], {"version": "local-conservative-2026-09-24", "characters": 280, "operation": "post"})
        self.assertEqual(LIMITS["Xiaohongshu"]["title"], 20)
        self.assertEqual(LIMITS["Xiaohongshu"]["characters"], 1000)

    def test_every_drafting_route_accepts_x(self):
        agent_runtime.check_destinations([{"platform": "X", "language": "en"}, {"platform": "X", "language": "zh-Hant-HK"}])
        self.assertIn("X", agent_runtime.FixtureAgentRuntime().supported_platforms())
        self.assertIn("X", ServerModelRuntime.supported_platforms(None))
        self.assertEqual(cli_runtime.PLATFORM_LIMITS["X"], 280)
        self.assertIn("X", cli_runtime.ClaudeCliRuntime.supported_platforms(None))
        payload = ServerModelRuntime._user_payload({"context": {"sources": [], "excluded": []}, "destinations": [{"platform": "X", "language": "en"}]})
        self.assertEqual(payload["destinations"][0]["characterLimit"], 280)
        self.assertEqual(skills.CHANNEL_SKILLS["X"], "postriff-channel-x")

    def test_x_length_is_measured_the_way_x_counts(self):
        self.assertEqual(measure("X", "a" * 280), {"used": 280, "limit": 280, "unit": "x-weighted"})
        self.assertEqual(over_by("X", "a" * 281), 1)
        self.assertEqual(over_by("X", "練" * 141), 2, "CJK weighs two on X")
        self.assertEqual(over_by("X", "練" * 140), 0)


class IntentAliases(unittest.TestCase):
    def test_x_by_name_alias_and_in_a_platform_list(self):
        cases = {
            "Publish it to Xiaohongshu, LinkedIn, and X": ["Xiaohongshu", "LinkedIn", "X"],
            "Publish it to Xiaohongshu, LinkedIn and X tomorrow at 9am": ["Xiaohongshu", "LinkedIn", "X"],
            "Post this on X": ["X"],
            "Draft one for X": ["X"],
            "Share it to X": ["X"],
            "Threads & X please": ["Threads", "X"],
            "LinkedIn or X": ["LinkedIn", "X"],
            "X/Twitter post about practice": ["X"],
            "X (Twitter) post": ["X"],
            "twitter/X": ["X"],
            "Post to Twitter": ["X"],
            "推特": ["X"],
            "x.com post": ["X"],
            "發去小紅書、LinkedIn同X": ["Xiaohongshu", "LinkedIn", "X"],
            "X and LinkedIn at 9am": ["X", "LinkedIn"],
            "X, LinkedIn and Threads": ["X", "LinkedIn", "Threads"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(named(text), expected)

    def test_a_bare_letter_x_elsewhere_stays_a_letter(self):
        cases = {
            "Write about my X-ray results for LinkedIn": ["LinkedIn"],
            "10x growth story for LinkedIn": ["LinkedIn"],
            "10X growth story for LinkedIn": ["LinkedIn"],
            "Series X funding news for LinkedIn": ["LinkedIn"],
            "Series X, LinkedIn": ["LinkedIn"],
            "A Malcolm X quote for Threads": ["Threads"],
            "SpaceX launch recap on Threads": ["Threads"],
            "Xbox review": [],
            "X marks the spot on LinkedIn": ["LinkedIn"],
            "去照X光": [],
            "Post this on x": [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(named(text), expected)

    def test_x_is_supported_and_keeps_its_time_and_language(self):
        parsed = intent.parse_request("Post to LinkedIn at 9am and X at 10am tomorrow", NOW, HK, DRAFTABLE)
        rows = {d["platform"]: d for d in parsed["destinations"]}
        self.assertTrue(rows["X"]["supported"])
        self.assertEqual(rows["X"]["localTime"][11:], "10:00")
        self.assertEqual(parsed["unsupported"], [])
        paired = intent.parse_request("Write it for LinkedIn in English and X in Cantonese", NOW, HK, DRAFTABLE)["languages"]
        self.assertIn({"tags": ["yue-Hant-HK"], "said": ["Cantonese"], "platforms": ["X"]}, [{k: p[k] for k in ("tags", "said", "platforms")} for p in paired])
        # Runtimes that cannot draft X still hear it named, and say so.
        older = intent.parse_request("Publish to LinkedIn and X", NOW, HK, ("LinkedIn", "Instagram", "Threads"))
        self.assertEqual(older["unsupported"], ["X"])

    def test_marking_keeps_length_and_other_alias_readers_never_see_a_bare_x(self):
        text = "to Xiaohongshu, LinkedIn, and X; Series X"
        marked = intent.mark_platform_x(text)
        self.assertEqual(len(marked), len(text))
        self.assertEqual(marked.count(intent.X_MARK), 1)
        self.assertTrue(marked.endswith("Series X"))
        self.assertFalse(any(alias == "x" for _, aliases in intent.PLATFORM_ALIASES for alias in aliases))


class PlatformShapedDrafts(unittest.TestCase):
    def test_x_is_one_post_within_280_whatever_it_is_given(self):
        worst = 0
        for facts in (LONG_FACTS, SAMPLE, [{"text": "A long approved fact. " * 20, "sourceId": "h"}], []):
            for language, idea in (("en", "Share it"), ("en", "word " * 200), ("zh-Hant-HK", "練琴" * 300), ("zh-Hant-HK", "一個想法"), ("en", "")):
                for tone in ("warm", "reflective", "direct"):
                    result = fixture("X", language, facts, idea, tone=tone, styleDirectives={"usesEmoji": True}, sample=facts is SAMPLE)
                    for opening in result["openings"]:  # the alpha "choose another opening" swap must still fit
                        swapped = opening + "\n\n" + result["text"].split("\n\n", 1)[-1]
                        worst = max(worst, measure("X", result["text"])["used"], measure("X", swapped)["used"])
                    self.assertNotRegex(result["text"], r"(?m)^\s*\d+/\d*\s|🧵", "one post, never a thread")
        self.assertLessEqual(worst, 280)

    def test_x_says_what_it_left_out_and_cites_only_what_it_kept(self):
        result = fixture("X", "en", LONG_FACTS)
        self.assertLessEqual(measure("X", result["text"])["used"], 280)
        self.assertLess(len(result["sourceIds"]), len(LONG_FACTS))
        self.assertTrue(all(f"Fact {sid[1:]} " in result["text"] for sid in result["sourceIds"]))
        self.assertTrue(any("left out to keep this to one X post" in w for w in result["warnings"]))
        short = fixture("X", "en", SAMPLE[:1])
        self.assertEqual(short["sourceIds"], ["sample"])
        self.assertFalse(any("left out" in w for w in short["warnings"]))

    def test_x_is_shorter_and_sharper_than_linkedin_which_adds_context(self):
        x, linkedin = fixture("X", "en", SAMPLE), fixture("LinkedIn", "en", SAMPLE)
        self.assertLess(len(x["text"]), len(linkedin["text"]))
        self.assertIn("Why it matters:", linkedin["text"])
        self.assertNotIn("Why it matters:", x["text"])
        self.assertNotIn("•", x["text"])
        self.assertNotIn("verified starting point", fixture("LinkedIn", "en", [])["text"], "no facts, no claim of a verified base")

    def test_xiaohongshu_note_has_a_short_title_a_structured_body_and_topic_tags(self):
        for language in ("zh-Hans-CN", "zh-Hant-TW", "en"):
            for extra in ({}, {"tone": "reflective"}, {"tone": "direct"}, {"shortOpenings": True}):
                with self.subTest(language=language, **extra):
                    result = fixture("Xiaohongshu", language, SAMPLE, "Share the seed swap as a learning opportunity", sample=True, **extra)
                    title, body = result["text"].split("\n\n", 1)
                    self.assertLessEqual(len(title), 20)
                    self.assertTrue(all(len(option) <= 20 for option in result["openings"]))
                    self.assertIn("• ", body)
                    self.assertRegex(result["text"].splitlines()[-1], r"^#\S+( #\S+)+$")
                    self.assertEqual([w for w in locale_lint.reminders(result["text"], language, "Xiaohongshu") if "title" in w], [])

    def test_simplified_xiaohongshu_notes_read_as_simplified(self):
        result = fixture("Xiaohongshu", "zh-Hans-CN", SAMPLE, "Share the seed swap as a learning opportunity", sample=True)
        self.assertIn("社区花园", result["text"])
        self.assertEqual([w for w in locale_lint.reminders(result["text"], "zh-Hans-CN", "Xiaohongshu") if "Traditional" in w], [])
        self.assertIn("社區花園", fixture("Xiaohongshu", "zh-Hant-TW", SAMPLE, sample=True)["text"])
        self.assertTrue(generation.is_simplified("zh-CN") and not generation.is_simplified("zh-Hant-HK") and not generation.is_simplified("yue-Hant-HK"))

    def test_a_long_xiaohongshu_title_is_a_reminder_on_every_route(self):
        warnings = locale_lint.reminders("这是一个非常非常非常非常非常非常长的小红书笔记标题啊\n\n正文", "zh-Hans-CN", "Xiaohongshu")
        self.assertTrue(any("20-character title limit" in w for w in warnings))
        self.assertEqual(locale_lint.reminders("A very long first line that is not a title at all\n\nbody", "en", "LinkedIn"), [])

    def test_the_fixture_runtime_drafts_x_beside_the_others(self):
        destinations = [{"platform": p, "language": "en"} for p in ("Xiaohongshu", "LinkedIn", "X")]
        result = agent_runtime.FixtureAgentRuntime().start_turn({"context": {"sources": [], "excluded": [], "candidateOnly": False}, "idea": "Practice notes", "destinations": destinations}, lambda event: None)
        variants = {v["platform"]: v for v in result["artifact"]["variants"]}
        self.assertEqual(set(variants), {"Xiaohongshu", "LinkedIn", "X"})
        self.assertLessEqual(measure("X", variants["X"]["text"])["used"], 280)


class NeverPublishable(unittest.TestCase):
    def test_hosted_social_has_no_x_publisher(self):
        social = HostedSocial(oauth=None, providers={"linkedin": object(), "threads": object(), "instagram": object()})
        self.assertIsNone(social._provider({"platform": "X"}))
        held = HostedSocial(oauth=None, providers={}).submit({"platform": "X", "workspaceId": "w", "channelId": "c"})
        self.assertEqual(held["state"], "held")

    def test_hosted_commands_cannot_add_channels(self):
        self.assertIn("channel_add", HostedPhase2Commands.SERVER_ACTIONS)

    def test_local_fixture_store_refuses_to_simulate_x_or_xiaohongshu_accounts(self):
        from postriff_phase2.store import Phase2Store
        from test_postriff_phase2 import P2Journey
        with tempfile.TemporaryDirectory() as tmp:
            journey = P2Journey(Phase2Store(Path(tmp) / "p2.db", clock=lambda: 1_800_000_000.0))
            for platform in ("X", "Xiaohongshu"):
                with self.subTest(platform=platform), self.assertRaises(AlphaError):
                    journey.act("p2_channel_add", platform=platform, language="English")
            journey.act("p2_channel_add", platform="LinkedIn", language="English")
            self.assertEqual([c["platform"] for c in journey.state["phase2"]["channels"]], ["LinkedIn"])

    def test_the_x_adapter_promises_no_publishing(self):
        root = skills.default_root()
        if root is None:
            self.skipTest("no repo skill library")
        x = skills.SkillLibrary(root).load("postriff-channel-x")["body"]
        self.assertIn("280", x)
        self.assertIn("no hosted X publisher", x)
        xhs = skills.SkillLibrary(root).load("postriff-channel-xiaohongshu")["body"]
        self.assertIn("at most 20 characters", xhs)
        self.assertIn("`#tag`", xhs)


if __name__ == "__main__":
    unittest.main()
