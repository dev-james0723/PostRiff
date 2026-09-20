"""Deterministic intent/schedule parser for the agent chat (design §4.1 ①, §4.4)."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import intent  # noqa: E402

HK = "Asia/Hong_Kong"
SUPPORTED = ("LinkedIn", "Instagram", "Threads")


def at(iso, zone=HK):
    return datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo(zone)).timestamp()


class ParseRequestTest(unittest.TestCase):
    def rows(self, parsed):
        return {d["platform"]: d["localTime"] for d in parsed["destinations"]}

    def test_cantonese_three_destinations_with_times(self):
        text = "想出一個 post 講 AI 點樣幫我練琴。今日晏晝 4 點 post 去 Instagram、今日下晝 5 點 post 去 LinkedIn、聽日晏晝 3 點半 post 去 Facebook。"
        parsed = intent.parse_request(text, at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual(parsed["intent"], "schedule")
        self.assertEqual(parsed["language"], "zh-Hant")  # a suggestion from the script, never a decision
        self.assertEqual(self.rows(parsed), {"Instagram": "2026-09-16T16:00", "LinkedIn": "2026-09-16T17:00", "Facebook": "2026-09-17T15:30"})
        self.assertEqual(parsed["unsupported"], ["Facebook"])
        self.assertFalse(any(d["assumed"] for d in parsed["destinations"]))

    def test_english_channel_then_time(self):
        text = "A post about how AI is changing my piano practice. Instagram at 4pm today, LinkedIn at 5pm, Facebook tomorrow 3:30pm."
        parsed = intent.parse_request(text, at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual(parsed["language"], "en")
        self.assertEqual(self.rows(parsed), {"Instagram": "2026-09-16T16:00", "LinkedIn": "2026-09-16T17:00", "Facebook": "2026-09-17T15:30"})

    def test_bare_hours_are_assumed_and_flagged(self):
        parsed = intent.parse_request("LinkedIn 5 點, Threads 9 點", at("2026-09-16T08:00"), HK, SUPPORTED)
        self.assertEqual(self.rows(parsed), {"LinkedIn": "2026-09-16T17:00", "Threads": "2026-09-16T09:00"})
        self.assertTrue(all(d["assumed"] for d in parsed["destinations"]))
        self.assertEqual(len([w for w in parsed["warnings"] if w.startswith("Read")]), 2)

    def test_time_already_passed_rolls_to_tomorrow_without_explicit_day(self):
        parsed = intent.parse_request("Instagram 4pm", at("2026-09-16T18:00"), HK, SUPPORTED)
        self.assertEqual(self.rows(parsed), {"Instagram": "2026-09-17T16:00"})
        self.assertTrue(any("moved to tomorrow" in w for w in parsed["warnings"]))

    def test_explicit_today_in_the_past_is_kept_and_warned(self):
        parsed = intent.parse_request("今日 4pm Instagram", at("2026-09-16T18:00"), HK, SUPPORTED)
        self.assertEqual(self.rows(parsed), {"Instagram": "2026-09-16T16:00"})
        self.assertTrue(any("already passed" in w for w in parsed["warnings"]))

    def test_time_without_channel_stays_unattached(self):
        parsed = intent.parse_request("Post this at 16:00 today.", at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual(parsed["destinations"], [])
        self.assertEqual(parsed["unattachedTimes"], [{"localTime": "2026-09-16T16:00", "assumed": False}])
        self.assertEqual(parsed["intent"], "schedule")

    def test_weekday_and_day_carry_over(self):
        parsed = intent.parse_request("Friday 9am LinkedIn, then Threads at 11am", at("2026-09-16T10:00"), HK, SUPPORTED)  # a Wednesday
        self.assertEqual(self.rows(parsed), {"LinkedIn": "2026-09-18T09:00", "Threads": "2026-09-18T11:00"})

    def test_draft_and_research_intents(self):
        draft = intent.parse_request("Write a post about my piano practice for LinkedIn.", at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual((draft["intent"], self.rows(draft)), ("draft", {"LinkedIn": None}))
        research = intent.parse_request("幫我調研一下 AI 練琴 app 嘅討論", at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual(research["intent"], "research")
        now = intent.parse_request("Post this to Threads now", at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual(now["intent"], "publish_now")

    def test_standing_instructions_are_memory_but_one_offs_and_topics_are_not(self):
        memory = {
            "以後 LinkedIn 唔好用 emoji": ["LinkedIn"],
            "From now on, keep my Instagram captions short.": ["Instagram"],
            "Remember: no hashtags on Threads.": ["Threads"],
            "No hashtags.": [],
            "Don't end my posts with a call to action": [],
            "記住每篇最多兩段": [],
        }
        for text, platforms in memory.items():
            with self.subTest(text=text):
                parsed = intent.parse_request(text, at("2026-09-16T10:00"), HK, SUPPORTED)
                self.assertEqual((parsed["intent"], list(self.rows(parsed))), ("memory", platforms))
        for text in ("今次呢篇短啲", "Write a post about why I never skip warm-ups", "Never mind, write about the seed swap", "Always " + "x" * 260, "Remember when we ran the first workshop? Draft that story for LinkedIn."):
            with self.subTest(text=text):
                self.assertNotEqual(intent.parse_request(text, at("2026-09-16T10:00"), HK, SUPPORTED)["intent"], "memory")
        self.assertEqual(intent.parse_request("記住聽日 4 點 post 去 LinkedIn", at("2026-09-16T10:00"), HK, SUPPORTED)["intent"], "schedule", "a time keeps the schedule intent")

    def test_plain_numbers_and_weekdays_without_times_are_not_schedules(self):
        parsed = intent.parse_request("The community garden hosts a free seed-swap on Saturday for 5 people.", at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertEqual(parsed["intent"], "draft")
        self.assertFalse(parsed["hasTimes"])

    def test_invalid_zone_falls_back_to_utc(self):
        self.assertEqual(intent.safe_zone("Mars/Olympus"), "UTC")
        self.assertEqual(intent.safe_zone(None), "UTC")
        self.assertEqual(intent.safe_zone(HK), HK)


class ResolveAndPlanTest(unittest.TestCase):
    default = [{"platform": "LinkedIn", "language": "English"}, {"platform": "Instagram", "language": "繁體中文"}]

    def test_named_channels_win_over_composer_selection(self):
        parsed = intent.parse_request("Instagram at 4pm today", at("2026-09-16T10:00"), HK, SUPPORTED)
        rows = intent.resolve_destinations(parsed, [{"platform": "LinkedIn", "language": "English"}], "English", self.default)
        self.assertEqual(rows, [{"platform": "Instagram", "language": "en"}])

    def test_unsupported_only_falls_back_to_selection(self):
        parsed = intent.parse_request("Facebook tomorrow 3pm", at("2026-09-16T10:00"), HK, SUPPORTED)
        rows = intent.resolve_destinations(parsed, [{"platform": "Threads", "language": "English"}], "English", self.default)
        self.assertEqual(rows, [{"platform": "Threads", "language": "en"}])
        # The time belonged to Facebook, so it does not silently move to Threads: no plan, one warning surface.
        self.assertIsNone(intent.build_plan(parsed, rows))
        self.assertEqual(parsed["unsupported"], ["Facebook"])

    def test_unattached_time_applies_to_every_destination(self):
        parsed = intent.parse_request("Post this at 16:00 today.", at("2026-09-16T10:00"), HK, SUPPORTED)
        plan = intent.build_plan(parsed, self.default)
        self.assertEqual([d["localTime"] for d in plan["destinations"]], ["2026-09-16T16:00", "2026-09-16T16:00"])

    def test_no_times_means_no_plan(self):
        parsed = intent.parse_request("Write about practice.", at("2026-09-16T10:00"), HK, SUPPORTED)
        self.assertIsNone(intent.build_plan(parsed, self.default))


if __name__ == "__main__":
    unittest.main()
