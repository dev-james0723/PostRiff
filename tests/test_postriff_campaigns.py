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


class ScheduleKindTests(unittest.TestCase):
    """Phase 2: monthly and countdown schedules, recap context, seen marks and email opt-in."""

    def setUp(self):
        self.state = initial_state("workspace-one")
        self.state["phase2"] = {"channels": [{"id": "acct-linkedin", "platform": "LinkedIn", "account": "Studio page"}], "jobs": []}
        # Tuesday 3 March 2026, 12:00 UTC (20:00 in Hong Kong).
        self.now = dt.datetime(2026, 3, 3, 12, tzinfo=dt.timezone.utc).timestamp()

    def save(self, schedule, **changes):
        payload = {"name": "Automation", "goal": "Studio notes", "audience": "Students", "schedule": schedule,
                   "destinations": [{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}], "route": "deterministic-preview"}
        payload.update(changes)
        return campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "editor", self.now)

    def task(self):
        return self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]

    def test_monthly_days_clamp_to_short_months_and_last_day(self):
        schedule = {"kind": "monthly", "monthDays": [31, 15], "localTime": "18:00", "timeZone": "Asia/Hong_Kong"}
        runs = [item["local"][:16] for item in campaigns.upcoming(schedule, self.now, 4)]
        self.assertEqual(runs, ["2026-03-15T18:00", "2026-03-31T18:00", "2026-04-15T18:00", "2026-04-30T18:00"])
        last = campaigns.upcoming({"kind": "monthly", "monthDays": ["last"], "localTime": "09:00", "timeZone": "UTC"}, dt.datetime(2026, 1, 31, 10, tzinfo=dt.timezone.utc).timestamp(), 2)
        self.assertEqual([item["local"][:10] for item in last], ["2026-02-28", "2026-03-31"])
        for bad in ([], [0], [32], ["first"], [1, 2, 3, 4, 5], "15"):
            with self.subTest(bad), self.assertRaises(AlphaError):
                campaigns.next_occurrence({"kind": "monthly", "monthDays": bad, "localTime": "09:00", "timeZone": "UTC"}, self.now)

    def test_countdown_runs_before_the_event_then_finishes(self):
        schedule = {"kind": "countdown", "eventDate": "2026-03-10", "daysBefore": [0, 7, 3, 1, 7], "localTime": "10:00", "timeZone": "Asia/Hong_Kong"}
        runs = campaigns.upcoming(schedule, self.now, 10)
        # The run 7 days before (3 March, 10:00) already passed at 20:00 local; the rest remain, in date order.
        self.assertEqual([item["local"][:16] for item in runs], ["2026-03-07T10:00", "2026-03-09T10:00", "2026-03-10T10:00"])
        self.assertIsNone(campaigns.next_occurrence(schedule, runs[-1]["scheduledFor"] + 1))
        self.assertEqual(campaigns.countdown_context(schedule, runs[0]["scheduledFor"]), {"eventDate": "2026-03-10", "daysToGo": 3})
        self.assertIsNone(campaigns.countdown_context({"weekdays": ["Monday"], "localTime": "09:00", "timeZone": "UTC"}, self.now))
        for bad in ({"eventDate": "10 March"}, {"daysBefore": []}, {"daysBefore": [91]}, {"daysBefore": [1, 2, 3, 4, 5, 6, 7, 8, 9]}):
            with self.subTest(bad), self.assertRaises(AlphaError):
                campaigns.next_occurrence({**schedule, **bad}, self.now)

    def test_countdown_save_fills_the_date_fact_and_refuses_a_past_event(self):
        self.save({"kind": "countdown", "eventDate": "2026-03-20", "daysBefore": [14, 7, 1], "localTime": "10:00", "timeZone": "Asia/Hong_Kong"}, goal="Countdown to my spring recital", facts={"venue": "City Hall"})
        task, campaign = self.task(), self.state["raffi"]["campaignPlanning"]["campaigns"][-1]
        self.assertEqual(task["schedule"], {"kind": "countdown", "eventDate": "2026-03-20", "daysBefore": [14, 7, 1], "localTime": "10:00", "timeZone": "Asia/Hong_Kong"})
        self.assertEqual((campaign["facts"], campaign["missingFacts"]), ({"venue": "City Hall", "date": "2026-03-20"}, []))
        self.assertEqual(task["nextOccurrence"]["local"][:16], "2026-03-06T10:00")
        with self.assertRaisesRegex(AlphaError, "countdown date has passed"):
            self.save({"kind": "countdown", "eventDate": "2026-03-01", "daysBefore": [0], "localTime": "10:00", "timeZone": "Asia/Hong_Kong"})
        # Activating after the last date is refused rather than silently doing nothing.
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        self.assertEqual(task["status"], "active")
        campaigns.apply_action(self.state, "raffi_recurrence_pause", {"taskId": task["id"]}, "owner", self.now)
        with self.assertRaisesRegex(AlphaError, "countdown date has passed"):
            campaigns.apply_action(self.state, "raffi_recurrence_resume", {"taskId": task["id"], "confirmed": True}, "owner", dt.datetime(2026, 3, 21, tzinfo=dt.timezone.utc).timestamp())

    def test_recap_include_is_part_of_the_definition_and_reads_only_published_posts(self):
        self.save({"kind": "monthly", "monthDays": ["last"], "localTime": "17:00", "timeZone": "UTC"}, include={"recentPostsDays": 30})
        task = self.task()
        self.assertEqual(task["include"], {"recentPostsDays": 30})
        digest = task["definitionDigest"]
        campaigns.apply_action(self.state, "raffi_recurrence_save", {"taskId": task["id"], "name": "Automation", "goal": "Studio notes", "audience": "Students",
                               "schedule": task["schedule"], "destinations": task["destinations"], "route": "deterministic-preview", "include": None}, "editor", self.now)
        self.assertNotEqual(task["definitionDigest"], digest)
        for bad in ({"recentPostsDays": 3}, {"recentPostsDays": 120}, {"posts": 30}, "30"):
            with self.subTest(bad), self.assertRaises(AlphaError):
                self.save(task["schedule"], include=bad)
        day = 86400
        self.state["phase2"]["jobs"] = [
            {"state": "verified", "verification": {"at": self.now - 2 * day}, "manifest": {"platform": "LinkedIn", "payload": {"text": "Recital recap " + "x" * 700}}},
            {"state": "verified", "verification": {"at": self.now - 40 * day}, "manifest": {"platform": "LinkedIn", "payload": {"text": "Too old"}}},
            {"state": "failed", "verification": None, "manifest": {"platform": "LinkedIn", "payload": {"text": "Never published"}}},
            {"state": "verified", "verification": {"at": self.now - 1 * day}, "manifest": {"platform": "Threads", "payload": {"text": "Newest"}}},
        ]
        posts = campaigns.recent_posts(self.state, self.now, 30)
        self.assertEqual([post["text"][:13] for post in posts], ["Newest", "Recital recap"])
        self.assertEqual(len(posts[1]["text"]), 600)
        self.assertEqual(posts[0], {"platform": "Threads", "publishedAt": "2026-03-02", "text": "Newest"})

    def test_seen_marks_completed_runs_and_watch_is_a_personal_opt_in(self):
        self.save({"weekdays": ["Monday"], "localTime": "09:00", "timeZone": "UTC"})
        task = self.task()
        planning = self.state["raffi"]["campaignPlanning"]
        planning["occurrences"] += [{"id": "run-1", "taskId": task["id"], "state": "completed"}, {"id": "run-2", "taskId": task["id"], "state": "completed"}, {"id": "run-3", "taskId": task["id"], "state": "held"}]
        result = campaigns.apply_action(self.state, "raffi_recurrence_seen", {"taskId": task["id"], "occurrenceIds": ["run-1"]}, "editor", self.now)
        self.assertEqual(result["marked"], 1)
        self.assertEqual(campaigns.apply_action(self.state, "raffi_recurrence_seen", {"taskId": task["id"]}, "editor", self.now + 1)["marked"], 1)
        self.assertEqual([(o["id"], o.get("seenAt")) for o in planning["occurrences"]], [("run-1", self.now), ("run-2", self.now + 1), ("run-3", None)])
        digest, version = task["definitionDigest"], task["version"]
        campaigns.apply_action(self.state, "raffi_recurrence_watch", {"taskId": task["id"], "email": True}, "viewer", self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_watch", {"taskId": task["id"], "email": True}, "viewer", self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_watch", {"taskId": task["id"], "email": True}, "owner", self.now)
        self.assertEqual(task["emailWatchers"], ["viewer", "owner"])
        campaigns.apply_action(self.state, "raffi_recurrence_watch", {"taskId": task["id"], "email": False}, "viewer", self.now)
        self.assertEqual(task["emailWatchers"], ["owner"])
        self.assertEqual((task["definitionDigest"], task["version"], task["status"]), (digest, version, "draft"))
        with self.assertRaises(AlphaError):
            campaigns.apply_action(self.state, "raffi_recurrence_watch", {"taskId": task["id"], "email": "yes"}, "viewer", self.now)

    def test_drafts_ready_email_names_the_automation_and_links_to_the_drafts(self):
        from postriff_phase2.email import Mailer
        sent = []
        class Transport:
            def send(self, message):
                sent.append(message)
                return {"id": "message-1"}
        mailer = Mailer(Transport(), "PostRiff <no-reply@postriff.invalid>", "https://postriff.example")
        self.assertTrue(mailer.drafts_ready("owner@example.com", "Weekly tip", 3, "https://postriff.example/app/agent/c1")["sent"])
        self.assertEqual(sent[0]["subject"], "3 drafts ready for review: Weekly tip")
        self.assertIn("https://postriff.example/app/agent/c1", sent[0]["text"])
        self.assertIn("Nothing was scheduled or published", sent[0]["text"])


class TriggerTests(unittest.TestCase):
    """Phase 3: runs started by new material in Ideas, by strong recent posts, and evergreen resharing."""

    def setUp(self):
        self.state = initial_state("workspace-one")
        self.state["phase2"] = {"channels": [{"id": "acct-threads", "platform": "Threads", "account": "@studio"}], "jobs": []}
        self.now = dt.datetime(2026, 3, 3, 12, tzinfo=dt.timezone.utc).timestamp()

    def save(self, schedule, **changes):
        payload = {"name": "Trigger", "goal": "Studio notes", "audience": "Students", "schedule": schedule,
                   "destinations": [{"platform": "Threads", "language": "en", "channelId": "acct-threads"}], "route": "deterministic-preview"}
        payload.update(changes)
        campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "editor", self.now)
        task = self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True}, "owner", self.now)
        return task

    def source(self, source_id, created, kind="link", active=True):
        self.state["sources"].append({"id": source_id, "kind": kind, "title": f"Source {source_id}", "active": active, "createdAt": created})

    def test_new_material_runs_once_per_item_added_after_activation_within_the_daily_limit(self):
        self.source("old", self.now - 60)  # added before the automation started watching
        task = self.save({"kind": "on_new_source", "sourceKinds": ["link", "idea"], "maxPerDay": 2, "timeZone": "Asia/Hong_Kong"})
        self.assertEqual((task["schedule"]["maxPerDay"], task["watchFrom"], task["nextOccurrence"]), (2, self.now, None))
        self.assertEqual(campaigns.upcoming(task["schedule"], self.now), [])
        self.source("link-1", dt.datetime.fromtimestamp(self.now + 10, dt.timezone.utc).isoformat(), "link")
        self.source("doc-1", self.now + 11, "document")  # not a chosen kind
        self.source("idea-1", self.now + 12, "idea")
        self.source("idea-2", self.now + 13, "idea")
        self.source("idea-off", self.now + 14, "idea", active=False)
        events = campaigns.new_source_events(self.state, task)
        self.assertEqual([e["sourceId"] for e in events], ["link-1", "idea-1", "idea-2"])
        self.assertTrue(campaigns.enqueue_events(self.state, task, events, self.now + 20))
        self.assertEqual([e["sourceId"] for e in task["pendingEvents"]], ["link-1", "idea-1"])
        self.assertEqual(task["skippedEvents"], 1)
        self.assertFalse(campaigns.enqueue_events(self.state, task, events, self.now + 21))  # already seen
        first = campaigns.claim_occurrence(self.state, task["id"], task["nextOccurrence"]["scheduledFor"], self.now + 30)
        self.assertEqual((first["event"]["sourceId"], first["event"]["kind"]), ("link-1", "new_source"))
        again = campaigns.claim_occurrence(self.state, task["id"], first["scheduledFor"], self.now + 31)
        self.assertEqual(again["event"]["sourceId"], "idea-1")
        self.assertIsNone(task["nextOccurrence"])
        # Pausing drops anything waiting; resuming watches from then on only.
        self.source("idea-3", self.now + 40, "idea")
        campaigns.enqueue_events(self.state, task, campaigns.new_source_events(self.state, task), self.now + 90000)
        campaigns.apply_action(self.state, "raffi_recurrence_pause", {"taskId": task["id"]}, "owner", self.now + 90001)
        self.assertEqual((task.get("pendingEvents"), task["nextOccurrence"]), (None, None))
        campaigns.apply_action(self.state, "raffi_recurrence_resume", {"taskId": task["id"], "confirmed": True}, "owner", self.now + 90002)
        self.assertEqual(campaigns.new_source_events(self.state, task), [])

    def test_strong_posts_compare_like_for_like_and_need_three_measured_posts(self):
        task = self.save({"kind": "on_strong_post", "withinDays": 7, "timeZone": "UTC"})
        day = 86400
        def post(ref, replies, language="en", provider="threads"):
            self.state["phase2"]["jobs"].append({"id": f"job-{ref}", "providerReference": ref, "state": "verified", "verification": {"at": self.now - day},
                                                 "manifest": {"platform": "Threads", "payload": {"text": f"Post {ref}"}}})
            return {"provider": provider, "providerPostId": ref, "cohort": {"provider": provider, "language": language, "contentTypeId": None, "definitionVersion": "2026-09"},
                    "metrics": {"replies": {"value": replies}}}
        posts = [post("a", 2), post("b", 3), post("c", 4), post("d", 30), post("e", 40, language="fr"), post("f", 1, language="fr")]
        events = campaigns.strong_post_events(self.state, task, posts, self.now)
        self.assertEqual([e["jobId"] for e in events], ["job-d"])  # the French pair is too small to compare
        self.assertEqual((events[0]["value"], events[0]["typical"], events[0]["sampleSize"], events[0]["metric"]), (30.0, 3.5, 4, "replies"))
        # Too old for the window, or unmeasured: never a trigger.
        self.state["phase2"]["jobs"][3]["verification"]["at"] = self.now - 8 * day
        self.assertEqual(campaigns.strong_post_events(self.state, task, posts, self.now), [])
        posts[3]["metrics"]["replies"]["value"] = None
        self.assertEqual(campaigns.strong_post_events(self.state, task, posts, self.now), [])

    def test_evergreen_picks_an_old_post_once_and_needs_a_time_schedule(self):
        weekly = {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": "UTC"}
        task = self.save(weekly, include={"evergreen": {"minAgeDays": 30}})
        self.assertEqual(task["include"], {"evergreen": {"minAgeDays": 30}})
        day = 86400
        self.state["phase2"]["jobs"] = [
            {"id": "recent", "providerReference": "r", "state": "verified", "verification": {"at": self.now - 5 * day}, "manifest": {"platform": "Threads", "payload": {"text": "Too new"}}},
            {"id": "older", "providerReference": "o", "state": "verified", "verification": {"at": self.now - 90 * day}, "manifest": {"platform": "Threads", "payload": {"text": "Oldest"}}},
            {"id": "strong", "providerReference": "s", "state": "verified", "verification": {"at": self.now - 40 * day}, "manifest": {"platform": "Threads", "payload": {"text": "Popular"}}},
        ]
        self.assertEqual(campaigns.evergreen_post(self.state, task, self.now)["jobId"], "older")  # nothing measured: oldest first
        measured = [{"provider": "threads", "providerPostId": "s", "metrics": {"replies": {"value": 9}}}]
        self.assertEqual(campaigns.evergreen_post(self.state, task, self.now, measured)["jobId"], "strong")
        task["evergreenUsed"] = ["strong", "older"]
        self.assertIsNone(campaigns.evergreen_post(self.state, task, self.now, measured))
        with self.assertRaisesRegex(AlphaError, "weekly, monthly or countdown"):
            self.save({"kind": "on_new_source", "timeZone": "UTC"}, include={"evergreen": {"minAgeDays": 30}})
        for bad in ({"evergreen": {"minAgeDays": 7}}, {"evergreen": {"days": 30}}, {"evergreen": 30}):
            with self.subTest(bad), self.assertRaises(AlphaError):
                self.save(weekly, include=bad)

    def test_trigger_schedules_validate(self):
        for bad in ({"kind": "on_new_source", "sourceKinds": ["voice_sample"], "timeZone": "UTC"}, {"kind": "on_new_source", "maxPerDay": 0, "timeZone": "UTC"},
                    {"kind": "on_strong_post", "withinDays": 60, "timeZone": "UTC"}, {"kind": "on_rain", "timeZone": "UTC"}):
            with self.subTest(bad), self.assertRaises(AlphaError):
                campaigns.normalize_schedule(bad)
        self.assertEqual(campaigns.normalize_schedule({"kind": "on_new_source", "timeZone": "UTC"}), {"kind": "on_new_source", "sourceKinds": ["idea", "text", "link", "document"], "maxPerDay": 3, "timeZone": "UTC"})


if __name__ == "__main__":
    unittest.main()
