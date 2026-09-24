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


class AutomationTests(unittest.TestCase):
    """`raffi_recurrence_save`: one command creates or edits an automation (brief + recurring task)."""

    def setUp(self):
        self.state = initial_state("workspace-one")
        self.state["phase2"] = {"channels": [
            {"id": "acct-linkedin", "platform": "LinkedIn", "account": "Studio page"},
            {"id": "acct-threads", "platform": "Threads", "account": "@studio"},
            {"id": "acct-gone", "platform": "LinkedIn", "account": "Old page", "revoked": True},
        ]}
        self.state["sources"] = [{"id": "src-note", "active": True, "kind": "note"}, {"id": "src-voice", "active": True, "kind": "voice_sample"}]
        # Tuesday 3 March 2026, 12:00 UTC (20:00 in Hong Kong).
        self.now = dt.datetime(2026, 3, 3, 12, tzinfo=dt.timezone.utc).timestamp()

    def payload(self, **changes):
        base = {
            "name": "Weekly practice tip", "goal": "One practical piano practice tip", "audience": "Adult piano students",
            "schedule": {"weekdays": ["Wednesday", "monday"], "localTime": "9:00", "timeZone": "Asia/Hong_Kong"},
            "destinations": [{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}, {"platform": "Threads", "language": "zh-HK", "channelId": "acct-threads"}],
            "destinationLabel": "Festival", "contentType": {"contentTypeId": "postriff:teach", "formatId": "short_text", "label": "How-to · Text post", "library": {"editorialId": "how-to", "nativeId": "text-post"}},
            "route": "deterministic-preview", "reasoning": "standard", "maxCostUsdMicro": 250_000, "sourceIds": ["src-note"],
        }
        base.update(changes)
        return base

    def save(self, now=None, **changes):
        return campaigns.apply_action(self.state, "raffi_recurrence_save", self.payload(**changes), "editor", now or self.now)

    def task(self):
        return self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]

    def test_several_weekdays_pick_the_earliest_and_upcoming_is_ordered(self):
        schedule = {"weekdays": ["Wednesday", "Monday"], "localTime": "09:00", "timeZone": "Asia/Hong_Kong"}
        runs = campaigns.upcoming(schedule, self.now, 3)
        self.assertEqual([item["local"][:16] for item in runs], ["2026-03-04T09:00", "2026-03-09T09:00", "2026-03-11T09:00"])
        self.assertEqual(campaigns.next_occurrence(schedule, self.now)["local"][:16], "2026-03-04T09:00")
        # The legacy single weekday still resolves the same way.
        self.assertEqual(campaigns.next_occurrence({"weekday": "Monday", "localTime": "09:00", "timeZone": "Asia/Hong_Kong"}, self.now)["local"][:16], "2026-03-09T09:00")
        for bad in ({"weekdays": [], "localTime": "09:00", "timeZone": "UTC"}, {"weekdays": ["Funday"], "localTime": "09:00", "timeZone": "UTC"},
                    {"weekdays": ["Monday"], "localTime": "25:00", "timeZone": "UTC"}, {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": "../etc/passwd"}):
            with self.assertRaises(AlphaError):
                campaigns.next_occurrence(bad, self.now)

    def test_save_creates_a_draft_with_accounts_content_type_and_sources(self):
        result = self.save()
        task = self.task()
        campaign = self.state["raffi"]["campaignPlanning"]["campaigns"][-1]
        self.assertEqual(result["status"], "draft")
        self.assertEqual(len(result["upcoming"]), 3)
        self.assertEqual(task["schedule"], {"weekdays": ["Monday", "Wednesday"], "localTime": "09:00", "timeZone": "Asia/Hong_Kong"})
        self.assertEqual(task["destinations"], [{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}, {"platform": "Threads", "language": "zh-Hant-HK", "channelId": "acct-threads"}])
        self.assertEqual(task["accountLabels"], {"acct-linkedin": "Studio page", "acct-threads": "@studio"})
        self.assertEqual(task["limits"], {"draftsPerOccurrence": 2})
        self.assertEqual(task["contentType"], {"contentTypeId": "postriff:teach", "contentTypeVersion": "1.0.0", "formatId": "short_text"})
        self.assertEqual(task["contentLibrary"], {"editorialId": "how-to", "nativeId": "text-post"})
        self.assertEqual((task["authorityVersion"], task["reasoning"], task["contextSourceIds"]), (2, "standard", ["src-note"]))
        self.assertEqual(task["definitionDigest"], campaigns.definition_digest(task))
        self.assertEqual((campaign["kind"], campaign["goal"], campaign["accountIds"]), ("automation", "One practical piano practice tip", ["acct-linkedin", "acct-threads"]))
        self.assertEqual(task["nextOccurrence"]["local"][:16], "2026-03-04T09:00")

    def test_save_refuses_what_cannot_be_drafted(self):
        refused = {
            "unknown account": {"destinations": [{"platform": "LinkedIn", "language": "en", "channelId": "acct-missing"}]},
            "revoked account": {"destinations": [{"platform": "LinkedIn", "language": "en", "channelId": "acct-gone"}]},
            "platform mismatch": {"destinations": [{"platform": "Threads", "language": "en", "channelId": "acct-linkedin"}]},
            "unsupported platform": {"destinations": [{"platform": "Facebook", "language": "en"}]},
            "unknown language": {"destinations": [{"platform": "LinkedIn", "language": "klingon-xx"}]},
            "no destinations": {"destinations": []},
            "too many": {"destinations": [{"platform": "LinkedIn", "language": tag} for tag in ("en", "fr", "de", "es", "it", "pt", "ja", "ko", "nl", "sv", "da")]},
            "legacy route": {"route": "local-cli"},
            "no route": {"route": ""},
            "reasoning": {"reasoning": "maximum"},
            "cost": {"maxCostUsdMicro": 10_000_001},
            "cost type": {"maxCostUsdMicro": 1.5},
            "voice sample as source": {"sourceIds": ["src-voice"]},
            "content type": {"contentType": {"contentTypeId": "postriff:unknown"}},
            "format": {"contentType": {"contentTypeId": "postriff:teach", "formatId": "hologram"}},
            "name": {"name": "  "},
        }
        for label, change in refused.items():
            with self.subTest(label), self.assertRaises(AlphaError):
                self.save(**change)
        self.assertEqual(self.state.get("raffi", {}).get("campaignPlanning", {}).get("recurringTasks", []), [])

    def test_platform_only_destinations_and_general_writing_are_allowed(self):
        self.save(destinations=[{"platform": "Instagram", "language": "en"}], contentType=None, sourceIds=None)
        task = self.task()
        self.assertEqual(task["destinations"], [{"platform": "Instagram", "language": "en"}])
        self.assertIsNone(task["contentType"])
        self.assertEqual(task["contextSourceIds"], [])

    def test_renaming_keeps_status_but_any_definition_change_returns_to_draft(self):
        self.save()
        task = self.task()
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        digest_before = task["definitionDigest"]
        campaigns.claim_occurrence(self.state, task["id"], task["nextOccurrence"]["scheduledFor"], self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_save", self.payload(taskId=task["id"], name="Wednesday tip", destinationLabel="Personal"), "editor", self.now + 5)
        self.assertEqual((task["status"], task["version"], task["definitionDigest"], task["name"]), ("active", 1, digest_before, "Wednesday tip"))
        for label, change in {"schedule": {"schedule": {"weekdays": ["Friday"], "localTime": "10:30", "timeZone": "Asia/Hong_Kong"}},
                              "cost": {"maxCostUsdMicro": 0}, "writer": {"route": "another-writer"}, "brief": {"goal": "Two practice tips"}}.items():
            with self.subTest(label):
                campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now) if task["status"] == "draft" else None
                version = task["version"]
                campaigns.apply_action(self.state, "raffi_recurrence_save", self.payload(taskId=task["id"], **change), "editor", self.now + 10)
                self.assertEqual(task["status"], "draft")
                self.assertEqual(task["version"], version + 1)
                self.assertNotIn("activatedBy", task)
                self.assertNotEqual(task["definitionDigest"], digest_before)
        occurrences = self.state["raffi"]["campaignPlanning"]["occurrences"]
        self.assertEqual([(item["state"], item.get("reason")) for item in occurrences], [("cancelled", "definition_changed")])
        campaign = self.state["raffi"]["campaignPlanning"]["campaigns"][-1]
        self.assertEqual((campaign["version"], campaign["goal"]), (2, "Two practice tips"))

    def test_event_brief_saves_but_activation_waits_for_facts_and_live_accounts(self):
        self.save(goal="Promote my spring recital")
        task = self.task()
        with self.assertRaisesRegex(AlphaError, "date, venue"):
            campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        self.save(taskId=task["id"], goal="Promote my spring recital", facts={"date": "2026-04-18", "venue": "City Hall", "ignored": 7})
        self.assertEqual(self.state["raffi"]["campaignPlanning"]["campaigns"][-1]["facts"], {"date": "2026-04-18", "venue": "City Hall"})
        self.state["phase2"]["channels"][1]["revoked"] = True
        with self.assertRaisesRegex(AlphaError, "no longer connected"):
            campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        self.state["phase2"]["channels"][1]["revoked"] = False
        # Activated two weeks later: the first run is the next one after activation, not the stale saved time.
        later = self.now + 14 * 86400
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", later)
        self.assertEqual(task["status"], "active")
        self.assertGreater(task["nextOccurrence"]["scheduledFor"], later)

    def test_cancelled_automations_cannot_be_edited_and_claims_follow_the_weekdays(self):
        self.save()
        task = self.task()
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        first = task["nextOccurrence"]["scheduledFor"]
        campaigns.claim_occurrence(self.state, task["id"], first, self.now)
        self.assertEqual(task["nextOccurrence"]["local"][:16], "2026-03-09T09:00")
        campaigns.apply_action(self.state, "raffi_recurrence_cancel", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        with self.assertRaisesRegex(AlphaError, "cancelled"):
            self.save(taskId=task["id"])

    def test_an_existing_campaign_brief_can_be_scheduled_without_duplicating_it(self):
        created = campaigns.apply_action(self.state, "raffi_campaign_create", {"goal": "Studio news", "audience": "Parents"}, "editor", self.now)
        self.save(campaignId=created["campaignId"], goal="Studio news", audience="Parents")
        planning = self.state["raffi"]["campaignPlanning"]
        self.assertEqual(len(planning["campaigns"]), 1)
        self.assertEqual((self.task()["campaignId"], planning["campaigns"][0]["version"]), (created["campaignId"], 1))
        # A changed brief versions the shared campaign; the new task is bound to that version.
        self.save(campaignId=created["campaignId"], goal="Studio news and dates", audience="Parents")
        self.assertEqual((planning["campaigns"][0]["version"], self.task()["campaignVersion"]), (2, 2))
        with self.assertRaises(AlphaError):
            self.save(campaignId="missing-campaign")

    def test_connected_destinations_split_skips_disconnected_accounts(self):
        kept, skipped = campaigns.connected_destinations(self.state, [
            {"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"},
            {"platform": "LinkedIn", "language": "en", "channelId": "acct-gone"},
            {"platform": "Instagram", "language": "en"},
        ])
        self.assertEqual([d.get("channelId") for d in kept], ["acct-linkedin", None])
        self.assertEqual([d["channelId"] for d in skipped], ["acct-gone"])

    def test_writer_uses_the_automations_own_content_type(self):
        from postriff_phase2.ideas import IdeasService
        selection, rules, note = IdeasService._automation_selection(self.state, {"contentTypeId": "postriff:teach", "contentTypeVersion": "1.0.0", "formatId": "carousel"})
        self.assertEqual((selection["contentTypeId"], selection["formatId"], rules, note), ("postriff:teach", "carousel", ("tested_steps", "prerequisites"), None))
        selection, rules, note = IdeasService._automation_selection(self.state, None)
        self.assertEqual((selection["contentTypeId"], rules, note), ("unclassified", (), None))
        selection, rules, note = IdeasService._automation_selection(self.state, {"contentTypeId": "pack.creator:missing", "contentTypeVersion": "1.0.0"})
        self.assertEqual(selection["contentTypeId"], "unclassified")
        self.assertIn("no longer available", note)


if __name__ == "__main__":
    unittest.main()
