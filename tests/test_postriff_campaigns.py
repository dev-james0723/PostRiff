import datetime as dt
import unittest

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import campaigns


class CampaignPlanningTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state("workspace-one")
        self.now = dt.datetime(2026, 3, 1, 12, tzinfo=dt.timezone.utc).timestamp()

    def test_concert_requires_current_date_and_venue_then_versions_without_overwriting_items(self):
        created = campaigns.apply_action(self.state, "raffi_campaign_create", {"goal": "Promote my concert", "audience": "Local listeners", "facts": {}}, "editor", self.now)
        self.assertEqual(created["status"], "needs_input")
        self.assertEqual(created["missingFacts"], ["date", "venue"])
        campaign = self.state["raffi"]["campaignPlanning"]["campaigns"][0]
        campaign["items"] = [{"id": "published", "status": "published"}, {"id": "draft", "status": "draft"}]

        updated = campaigns.apply_action(self.state, "raffi_campaign_update", {"campaignId": campaign["id"], "facts": {"date": "2026-10-01", "venue": "Hall A"}}, "editor", self.now + 1)

        self.assertEqual(updated["missingFacts"], [])
        self.assertEqual(campaign["version"], 2)
        self.assertNotIn("needsReview", campaign["items"][0])
        self.assertTrue(campaign["items"][1]["needsReview"])

    def test_recurrence_needs_explicit_activation_and_is_idempotent_per_occurrence(self):
        created = campaigns.apply_action(self.state, "raffi_campaign_create", {"goal": "Weekly studio notes", "audience": "Students", "facts": {}}, "editor", self.now)
        preview = campaigns.apply_action(self.state, "raffi_recurrence_preview", {"campaignId": created["campaignId"], "schedule": {"weekday": "Sunday", "localTime": "02:30", "timeZone": "America/New_York"}}, "editor", self.now)
        task_id = preview["taskId"]
        with self.assertRaisesRegex(AlphaError, "Confirm"):
            campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task_id}, "owner", self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task_id, "confirmed": True}, "owner", self.now)
        scheduled = preview["preview"]["scheduledFor"]
        first = campaigns.claim_occurrence(self.state, task_id, scheduled, self.now)
        second = campaigns.claim_occurrence(self.state, task_id, scheduled, self.now + 10)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["authority"], "draft_preparation_only")

    def test_dst_gap_moves_to_next_valid_local_minute_and_repeat_uses_earlier_offset(self):
        spring = campaigns.next_occurrence({"weekday": "Sunday", "localTime": "02:30", "timeZone": "America/New_York"}, dt.datetime(2026, 3, 7, 12, tzinfo=dt.timezone.utc).timestamp())
        autumn = campaigns.next_occurrence({"weekday": "Sunday", "localTime": "01:30", "timeZone": "America/New_York"}, dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc).timestamp())
        self.assertIn("T03:00:00-04:00", spring["local"])
        self.assertEqual(autumn["fold"], 0)
        self.assertEqual(autumn["offset"], "-0400")


if __name__ == "__main__":
    unittest.main()
