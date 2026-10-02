"""Evergreen and Signature Series together (AC20): Evergreen without a series behaves as before (the existing tests in
test_postriff_campaigns.py stay unchanged), two automations never reuse the same post blindly, and an automation can
follow a series through the same evergreen slot — one approved episode at a time, never one whose facts need a
review, never the same episode twice.

    PYTHONPATH=src:tests python -m unittest tests.test_series_evergreen
"""
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.series import commands, model as m
from series_fixtures import DAY, NOW, Flags, case, post, workspace

WEEKLY = {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": "UTC"}


class Base(unittest.TestCase):
    def setUp(self):
        self.flags = Flags(RAFII_SERIES_ENABLED=True).__enter__()
        self.state = workspace()
        self.state["phase2"]["channels"] = [{"id": "acct-threads", "platform": "Threads", "account": "@studio"}]

    def tearDown(self):
        self.flags.__exit__()

    def save(self, name="Evergreen", **include):
        payload = {"name": name, "goal": "Studio notes", "audience": "Students", "schedule": WEEKLY, "include": {"evergreen": {"minAgeDays": 30, **include}},
                   "destinations": [{"platform": "Threads", "language": "en", "channelId": "acct-threads"}], "route": "deterministic-preview"}
        campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "editor", NOW)
        task = self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", NOW)
        return task


class EvergreenWithoutSeriesTest(Base):
    def test_ac20_one_automation_ranks_exactly_as_before(self):
        self.state["phase2"]["jobs"] = [post("recent", "Too new", 5), post("older", "Oldest", 90), post("strong", "Popular", 40, reference="s")]
        task = self.save()
        self.assertEqual(task["include"], {"evergreen": {"minAgeDays": 30}})
        picked = campaigns.evergreen_post(self.state, task, NOW)
        self.assertEqual((picked["jobId"], "priorUse" in picked), ("older", False))
        measured = [{"provider": "threads", "providerPostId": "s", "metrics": {"replies": {"value": 9}}}]
        self.assertEqual(campaigns.evergreen_post(self.state, task, NOW, measured)["jobId"], "strong")

    def test_a_second_automation_prefers_another_post_and_names_any_earlier_reuse(self):
        self.state["phase2"]["jobs"] = [post("a", "First old post", 90), post("b", "Second old post", 60)]
        first, second = self.save("One"), self.save("Two")
        first["evergreenUsed"] = ["a"]
        self.assertEqual(campaigns.evergreen_post(self.state, second, NOW)["jobId"], "b")   # not the one "One" refreshed
        first["evergreenUsed"] = ["a", "b"]
        reused = campaigns.evergreen_post(self.state, second, NOW)
        self.assertEqual(reused["jobId"], "a")                                               # nothing else left: reused, but not blindly
        self.assertEqual(reused["priorUse"], [{"kind": "automation", "id": first["id"]}])
        second["evergreenUsed"] = ["a", "b"]
        self.assertIsNone(campaigns.evergreen_post(self.state, second, NOW))                # never the same post twice in one automation

    def test_a_post_that_starts_a_series_counts_as_reused(self):
        self.state["phase2"]["jobs"] = [post("origin", case("en-series-evergreen")["source"], 90), post("plain", "Another old post", 45)]
        commands.create(self.state, {"origin": {"kind": "post", "id": "origin"}, "audienceQuestion": "Q?", "goal": "G"}, "owner", NOW)
        task = self.save()
        self.assertEqual(campaigns.evergreen_post(self.state, task, NOW)["jobId"], "plain")

    def test_include_validation(self):
        self.assertEqual(campaigns.normalize_include({"evergreen": {"minAgeDays": 30, "seriesId": "abc123"}}), {"evergreen": {"minAgeDays": 30, "seriesId": "abc123"}})
        for bad in ({"evergreen": {"minAgeDays": 30, "seriesId": 5}}, {"evergreen": {"minAgeDays": 30, "seriesId": "../x"}}, {"evergreen": {"seriesId": "abc"}}):
            with self.subTest(bad), self.assertRaises(AlphaError):
                campaigns.normalize_include(bad)


class FollowingASeriesTest(Base):
    def setUp(self):
        super().setUp()
        self.state["phase2"]["jobs"] = [post("origin", case("en-series-evergreen")["source"], 90)]
        self.campaign = commands.create(self.state, {"origin": {"kind": "post", "id": "origin"}, "audienceQuestion": "How should adults practise?", "goal": "Habits"}, "owner", NOW)
        self.series = self.campaign["series"]

    def test_ac20_the_evergreen_slot_carries_the_approved_episode_once(self):
        task = self.save(seriesId=self.campaign["id"])
        self.assertEqual(task["include"]["evergreen"]["seriesId"], self.campaign["id"])
        self.assertIsNone(campaigns.evergreen_post(self.state, task, NOW))                  # nothing approved yet
        first, second = self.series["episodes"][0], self.series["episodes"][1]
        commands.approve(self.state, self.campaign, first["id"], "owner", NOW)
        picked = campaigns.evergreen_post(self.state, task, NOW)
        self.assertEqual((picked["jobId"], picked["episodeId"], picked["episode"]["role"]), ("origin", first["id"], "explanation"))
        self.assertTrue(picked["episode"]["claims"])
        # The worker marks it as being drafted: a second automation following the same series cannot take it.
        m.mark_drafting(self.state, self.campaign["id"], first["id"], task["id"], "occ-1", NOW)
        self.state["raffi"]["campaignPlanning"]["occurrences"].append({"id": "occ-1", "taskId": task["id"], "state": "running"})
        other = self.save("Other", seriesId=self.campaign["id"])
        self.assertIsNone(campaigns.evergreen_post(self.state, other, NOW))
        # A run that ended without drafting frees the episode again; a draft makes it done.
        self.state["raffi"]["campaignPlanning"]["occurrences"][-1]["state"] = "cancelled"
        self.assertEqual(campaigns.evergreen_post(self.state, other, NOW)["episodeId"], first["id"])
        self.state["variants"].append({"id": "d1", "text": "Five minutes on one skill, tonight.", "platform": "Threads", "language": "en", "revision": 1})
        commands.link_draft(self.state, self.campaign, first["id"], {"variantId": "d1", "acknowledgedWarnings": []}, "owner", NOW)
        self.assertIsNone(campaigns.evergreen_post(self.state, other, NOW))
        # The next approved episode is a distinct one.
        commands.approve(self.state, self.campaign, second["id"], "owner", NOW)
        nxt = campaigns.evergreen_post(self.state, task, NOW)
        self.assertEqual((nxt["episodeId"], nxt["episode"]["role"]), (second["id"], "worked_example"))
        self.assertNotEqual(nxt["episode"]["angle"], picked["episode"]["angle"])

    def test_facts_needing_review_paused_series_and_the_flag_hold_the_episode_back(self):
        task = self.save(seriesId=self.campaign["id"])
        first = self.series["episodes"][0]
        commands.approve(self.state, self.campaign, first["id"], "owner", NOW)
        self.assertIsNotNone(campaigns.evergreen_post(self.state, task, NOW))
        self.assertIsNone(campaigns.evergreen_post(self.state, task, NOW + 400 * DAY))      # its facts expired
        commands.set_status(self.state, self.campaign, {"status": "paused"}, "owner", NOW)
        self.assertIsNone(campaigns.evergreen_post(self.state, task, NOW))
        commands.set_status(self.state, self.campaign, {"status": "active"}, "owner", NOW)
        with Flags(RAFII_SERIES_ENABLED=False):
            self.assertIsNone(campaigns.evergreen_post(self.state, task, NOW))              # off stops new series work

    def test_following_needs_an_existing_series_and_the_feature(self):
        with self.assertRaisesRegex(AlphaError, "Choose a series"):
            self.save(seriesId="0123456789abcdef0123456789abcdef")
        commands.set_status(self.state, self.campaign, {"status": "archived"}, "owner", NOW)
        with self.assertRaisesRegex(AlphaError, "Choose a series"):
            self.save(seriesId=self.campaign["id"])
        with Flags(RAFII_SERIES_ENABLED=False), self.assertRaises(AlphaError) as caught:
            self.save(seriesId=self.campaign["id"])
        self.assertEqual(caught.exception.code, "feature_disabled")

    def test_d012_an_existing_follow_stays_saveable_with_the_feature_off(self):
        """With the feature off a new follow is refused, but an automation that already follows a series can still be
        saved (D-012 stops admission only) and the follow can be cleared; re-adding it is then a new follow, refused."""
        task = self.save(seriesId=self.campaign["id"])
        payload = {"taskId": task["id"], "name": "Evergreen", "goal": "Studio notes, edited", "audience": "Students", "schedule": WEEKLY,
                   "include": {"evergreen": {"minAgeDays": 30, "seriesId": self.campaign["id"]}},
                   "destinations": [{"platform": "Threads", "language": "en", "channelId": "acct-threads"}], "route": "deterministic-preview"}
        tasks = lambda: {t["id"]: t for t in self.state["raffi"]["campaignPlanning"]["recurringTasks"]}  # noqa: E731
        with Flags(RAFII_SERIES_ENABLED=False):
            saved = campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "editor", NOW)   # kept: not refused
            self.assertEqual(saved["taskId"], task["id"])
            self.assertEqual(tasks()[task["id"]]["include"]["evergreen"]["seriesId"], self.campaign["id"])
            campaigns.apply_action(self.state, "raffi_recurrence_save", {**payload, "include": {"evergreen": {"minAgeDays": 30}}}, "editor", NOW)
            self.assertNotIn("seriesId", tasks()[task["id"]]["include"]["evergreen"])
            with self.assertRaises(AlphaError) as caught:
                campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "editor", NOW)
        self.assertEqual(caught.exception.code, "feature_disabled")

    def test_a_series_is_not_a_brief_to_schedule(self):
        payload = {"name": "X", "goal": "G", "audience": "A", "schedule": WEEKLY, "campaignId": self.campaign["id"],
                   "destinations": [{"platform": "Threads", "language": "en"}], "route": "deterministic-preview"}
        with self.assertRaisesRegex(AlphaError, "planned in Library"):
            campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "editor", NOW)

    def test_the_writer_lead_names_the_episode_rules(self):
        plain = CampaignWorker._lead(1, {"evergreen": {"platform": "Threads", "publishedAt": "2026-07-01", "text": "old"}})
        self.assertIn("fresh take for today without copying it", plain)
        episode = CampaignWorker._lead(1, {"evergreen": {"text": "old", "episode": {"role": "faq", "angle": "Answer", "claims": ["c"]}}})
        self.assertIn("approved series episode", episode)
        self.assertIn("use only the claims listed with the episode", episode)
        self.assertNotIn("fresh take", episode)


if __name__ == "__main__":
    unittest.main()
