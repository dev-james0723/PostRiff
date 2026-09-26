"""Raffi orchestration: workflow timing, the v3 automation definition, the shared lifecycle, publishing safety,
capability honesty, the deterministic reading of requests and edits, and the chat plan (orchestration §1–§7).

The end-to-end acceptance scenarios (A–F) run on PostgreSQL in tests/phase2/postgres_orchestration.py.
"""
import datetime as dt
import json
import unittest
import zoneinfo
from pathlib import Path

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import (automation_edit, automation_explain, automation_plan, campaigns, capabilities, lifecycle, publisher,
                             workflow, workflow_parse)
from postriff_phase2.contracts import digest

HK = "Asia/Hong_Kong"
ZONE = zoneinfo.ZoneInfo(HK)
VECTORS = json.loads((Path(__file__).parent / "fixtures" / "automation_lifecycle.json").read_text())


def at(y, m, d, h=0, mi=0, zone=ZONE):
    return dt.datetime(y, m, d, h, mi, tzinfo=zone).timestamp()


def local(epoch, zone=ZONE):
    return dt.datetime.fromtimestamp(epoch, zone).strftime("%a %Y-%m-%d %H:%M")


def base_state():
    state = initial_state("workspace-one")
    state["phase2"] = {"channels": [
        {"id": "li", "platform": "LinkedIn", "account": "Studio page", "evidenceSource": "live_provider", "identityVerified": True, "capabilityVerified": True, "revoked": False},
        {"id": "th", "platform": "Threads", "account": "@studio", "evidenceSource": "synthetic", "identityVerified": True, "capabilityVerified": True, "revoked": False},
    ], "jobs": []}
    state["sources"] = []
    state["variants"] = []
    return state


def save(state, now, **overrides):
    payload = {"name": "Studio reflections", "goal": "A reflection about practice.", "audience": "Students", "facts": {},
               "schedule": {"weekdays": ["Wednesday"], "localTime": "09:00", "timeZone": HK},
               "destinations": [{"platform": "LinkedIn", "language": "en", "channelId": "li"}, {"platform": "X", "language": "en"}],
               "contentType": None, "route": "deterministic-preview", "reasoning": "quick", "maxCostUsdMicro": 0, "sourceIds": [], "include": None,
               "voiceMode": "neutral", "workflow": {"policy": "review", "stages": {"generate": {"at": "anchor"}, "review": {"weekday": "Thursday", "localTime": "09:00"},
                                                                                   "publish": {"weekday": "Saturday", "localTime": "18:00"}}},
               "intent": "Every Wednesday … publish Saturday 6 PM"}
    payload.update(overrides)
    return campaigns.apply_action(state, "raffi_recurrence_save", payload, "owner-1", now)


def task_of(state, task_id):
    return next(t for t in state["raffi"]["campaignPlanning"]["recurringTasks"] if t["id"] == task_id)


class WorkflowTimingTests(unittest.TestCase):
    def test_generation_review_and_publication_are_separate_instants(self):
        schedule = {"weekdays": ["Wednesday"], "localTime": "09:00", "timeZone": HK}
        flow = workflow.normalize_workflow({"policy": "review", "stages": {"review": {"weekday": "Thursday", "localTime": "09:00"}, "publish": {"weekday": "Saturday", "localTime": "18:00"}}}, schedule, ["LinkedIn"])
        times = workflow.stage_times(flow, schedule, at(2026, 9, 30, 9))
        self.assertEqual([local(times[k]) for k in ("generateAt", "reviewAt", "publishAt")], ["Wed 2026-09-30 09:00", "Thu 2026-10-01 09:00", "Sat 2026-10-03 18:00"])

    def test_relative_stages_and_asap(self):
        schedule = {"kind": "once", "date": "2026-09-30", "localTime": "14:00", "timeZone": HK}
        flow = workflow.normalize_workflow({"policy": "auto", "stages": {"generate": {"asap": True}}}, schedule)
        times = workflow.stage_times(flow, schedule, at(2026, 9, 30, 14), claimed_at=at(2026, 9, 29, 10))
        self.assertEqual((local(times["generateAt"]), local(times["publishAt"])), ("Tue 2026-09-29 10:00", "Wed 2026-09-30 14:00"))
        weekly = {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": HK}
        before = workflow.normalize_workflow({"policy": "review", "stages": {"generate": {"dayOffset": -1, "localTime": "17:00"}, "review": {"at": "generate"}}}, weekly)
        self.assertEqual(local(workflow.stage_times(before, weekly, at(2026, 10, 5, 9))["generateAt"]), "Sun 2026-10-04 17:00")
        lead = workflow.normalize_workflow({"policy": "auto", "stages": {"generate": {"minutesOffset": -60}}}, weekly)
        self.assertEqual(local(workflow.stage_times(lead, weekly, at(2026, 10, 5, 9))["generateAt"]), "Mon 2026-10-05 08:00")

    def test_stage_order_and_span_are_checked(self):
        weekly = {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": HK}
        with self.assertRaisesRegex(AlphaError, "wrong side"):
            workflow.normalize_workflow({"policy": "review", "stages": {"generate": {"minutesOffset": 30}}}, weekly)
        with self.assertRaisesRegex(AlphaError, "later weekday"):
            workflow.normalize_workflow({"policy": "review", "stages": {"generate": {"weekday": "Friday", "localTime": "09:00"}}}, weekly)
        with self.assertRaises(AlphaError):
            workflow.normalize_workflow({"policy": "sometimes"}, weekly)
        with self.assertRaisesRegex(AlphaError, "clock schedule"):
            workflow.normalize_workflow({"policy": "review"}, {"kind": "on_new_source", "timeZone": HK})

    def test_next_run_skips_claimed_anchors_and_runs_late_generation_before_its_publication(self):
        schedule = {"weekdays": ["Wednesday"], "localTime": "09:00", "timeZone": HK}
        flow = workflow.normalize_workflow({"policy": "review", "stages": {"publish": {"weekday": "Saturday", "localTime": "18:00"}}}, schedule)
        task = {"schedule": schedule, "workflow": flow, "lastAnchorAt": None}
        first = workflow.next_run(task, at(2026, 9, 28, 10))
        self.assertEqual(local(first["anchorAt"]), "Wed 2026-09-30 09:00")
        # A new automation starts at its next drafting time, never in a week that already began.
        self.assertEqual(local(workflow.next_run(task, at(2026, 10, 1, 12))["anchorAt"]), "Wed 2026-10-07 09:00")
        # After it has run, a week missed while PostRiff was down is drafted late if its post is still ahead.
        task["lastAnchorAt"] = at(2026, 9, 23, 9)
        late = workflow.next_run(task, at(2026, 10, 1, 12))
        self.assertEqual((local(late["anchorAt"]), local(late["scheduledFor"])), ("Wed 2026-09-30 09:00", "Thu 2026-10-01 12:00"))
        task["lastAnchorAt"] = first["anchorAt"]
        self.assertEqual(local(workflow.next_run(task, at(2026, 10, 1, 12))["anchorAt"]), "Wed 2026-10-07 09:00")

    def test_dst_fall_back_uses_the_first_occurrence(self):
        schedule = {"weekdays": ["Sunday"], "localTime": "01:30", "timeZone": "America/New_York"}
        flow = workflow.normalize_workflow({"policy": "auto", "stages": {"generate": {"minutesOffset": -60}}}, schedule)
        run = workflow.next_run({"schedule": schedule, "workflow": flow}, dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc).timestamp())
        self.assertIn("-04:00", dt.datetime.fromtimestamp(run["anchorAt"], zoneinfo.ZoneInfo("America/New_York")).isoformat())

    def test_skills_are_composed_from_the_definition(self):
        base = {"destinations": [{"platform": "LinkedIn"}], "voiceMode": "neutral"}
        plain = [s["skill"] for s in workflow.compose({**base, "workflow": {"policy": "drafts", "content": {"task": "tip"}}})]
        self.assertNotIn("research", plain)
        self.assertNotIn("approval_gate", plain)
        rich = [s["skill"] for s in workflow.compose({"destinations": [{"platform": "LinkedIn"}, {"platform": "X"}], "voiceMode": "personalized",
                                                       "workflow": {"policy": "review", "research": {"domains": ["bbc.co.uk"], "about": "music", "recencyDays": 7, "onNothing": "skip", "quote": {"about": "a scientist"}}}})]
        for skill in ("research", "source_validation", "relevance", "quote_verification", "voice", "platform_adaptation", "approval_gate", "publish"):
            self.assertIn(skill, rich)


class AutomationV3Tests(unittest.TestCase):
    def setUp(self):
        self.state = base_state()
        self.now = at(2026, 9, 28, 10)

    def test_save_is_version_3_with_the_workflow_in_the_authorized_definition(self):
        saved = save(self.state, self.now)
        task = task_of(self.state, saved["taskId"])
        self.assertEqual((task["authorityVersion"], task["status"]), (3, "draft"))
        self.assertEqual(task["definitionDigest"], digest({k: task.get(k) for k in campaigns.DEFINITION_V3}))
        self.assertEqual(local(task["nextOccurrence"]["anchorAt"]), "Wed 2026-09-30 09:00")
        self.assertTrue(task["nextPublish"].startswith("2026-10-03T18:00"))
        # A builder save that does not mention the workflow keeps it; changing it is a new definition.
        payload = {"taskId": task["id"], "name": "Renamed", "goal": "A reflection about practice.", "audience": "Students", "facts": {}, "schedule": task["schedule"],
                   "destinations": task["destinations"], "contentType": None, "route": task["route"], "reasoning": "quick", "maxCostUsdMicro": 0, "sourceIds": [], "include": None, "voiceMode": "neutral"}
        campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "owner-1", self.now)
        self.assertEqual((task["workflow"]["policy"], task["version"], task["name"]), ("review", 1, "Renamed"))

    def test_once_and_multi_slot_schedules(self):
        once = save(self.state, self.now, schedule={"kind": "once", "date": "2026-09-28", "localTime": "14:00", "timeZone": HK},
                    workflow={"policy": "review", "stages": {"generate": {"asap": True}}})
        task = task_of(self.state, once["taskId"])
        self.assertEqual(task["nextOccurrence"]["scheduledFor"], self.now)
        with self.assertRaisesRegex(AlphaError, "already passed"):
            save(self.state, self.now, schedule={"kind": "once", "date": "2026-09-27", "localTime": "14:00", "timeZone": HK}, workflow={"policy": "review", "stages": {"generate": {"asap": True}}})
        slots = campaigns.normalize_schedule({"weekdays": ["Monday", "Thursday"], "localTime": "09:00", "slots": [{"weekday": "Monday", "localTime": "09:00"}, {"weekday": "Thursday", "localTime": "17:00"}], "timeZone": HK})
        self.assertEqual(slots["slots"][1], {"weekday": "Thursday", "localTime": "17:00"})
        upcoming = campaigns.upcoming(slots, self.now, 3)
        self.assertEqual([local(u["scheduledFor"]) for u in upcoming], ["Thu 2026-10-01 17:00", "Mon 2026-10-05 09:00", "Thu 2026-10-08 17:00"])
        same = campaigns.normalize_schedule({"weekdays": ["Wednesday", "Friday"], "localTime": "16:30", "slots": [{"weekday": "Wednesday", "localTime": "16:30"}, {"weekday": "Friday", "localTime": "16:30"}], "timeZone": HK})
        self.assertNotIn("slots", same)

    def test_activation_needs_a_policy_and_auto_publish_needs_an_explicit_grant_for_this_definition(self):
        pending = save(self.state, self.now, workflow={"policy": None})
        with self.assertRaises(AlphaError) as missing:
            campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": pending["taskId"], "confirmed": True}, "owner-1", self.now)
        self.assertEqual(missing.exception.code, "publish_policy_required")
        auto = save(self.state, self.now, workflow={"policy": "auto"})
        with self.assertRaises(AlphaError) as refused:
            campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": auto["taskId"], "confirmed": True}, "owner-1", self.now)
        self.assertEqual(refused.exception.code, "publish_authority_required")
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": auto["taskId"], "confirmed": True, "publishAuthority": {"confirmed": True}}, "owner-1", self.now)
        task = task_of(self.state, auto["taskId"])
        self.assertEqual((task["publishAuthority"]["grantedBy"], task["publishAuthority"]["definitionDigest"]), ("owner-1", task["definitionDigest"]))
        # Any change to the definition voids the grant and the automation waits for a new activation.
        save(self.state, self.now, taskId=task["id"], workflow={"policy": "auto", "stages": {"generate": {"minutesOffset": -30}}})
        self.assertEqual(task["status"], "draft")
        self.assertNotIn("publishAuthority", task)

    def test_pause_until_resume_and_delete_keep_history(self):
        saved = save(self.state, self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", self.now)
        result = campaigns.apply_action(self.state, "raffi_recurrence_pause", {"taskId": saved["taskId"], "until": self.now + 14 * 86400}, "owner-1", self.now)
        self.assertEqual((result["status"], result["pausedUntil"]), ("paused", self.now + 14 * 86400))
        with self.assertRaises(AlphaError):
            campaigns.apply_action(self.state, "raffi_recurrence_pause", {"taskId": saved["taskId"], "until": self.now - 1}, "owner-1", self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_resume", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", self.now)
        task = task_of(self.state, saved["taskId"])
        self.assertEqual(task["status"], "active")
        self.assertNotIn("pausedUntil", task)
        campaigns.apply_action(self.state, "raffi_recurrence_cancel", {"taskId": saved["taskId"], "confirmed": True, "delete": True}, "owner-1", self.now)
        self.assertEqual((task["status"], task["deletedBy"]), ("cancelled", "owner-1"))
        self.assertEqual(automation_edit.live_tasks(self.state), [])

    def _drafted_run(self):
        saved = save(self.state, self.now)
        campaigns.apply_action(self.state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", self.now)
        task = task_of(self.state, saved["taskId"])
        occurrence = campaigns.claim_occurrence(self.state, task["id"], task["nextOccurrence"]["scheduledFor"], task["nextOccurrence"]["scheduledFor"])
        self.state["variants"].append({"id": "v1", "revision": 2, "text": "A reflection.", "unknowns": ["No date given."], "warnings": ["Check the facts."], "sourceIds": []})
        occurrence.update(lifecycle="drafted", state="completed", generatedAt=occurrence["scheduledFor"], items=[
            {"key": "LinkedIn|li|en", "platform": "LinkedIn", "channelId": "li", "language": "en", "variantId": "v1", "variantRevision": 2, "state": "ready_for_review",
             "publishAt": occurrence["stages"]["publishAt"], "jobId": None, "decision": None},
            {"key": "X||en", "platform": "X", "channelId": None, "language": "en", "variantId": "v1", "variantRevision": 2, "state": "ready_for_review", "publishAt": None, "jobId": None}])
        return task, occurrence

    def test_claim_freezes_the_run_plan_and_never_claims_the_same_anchor_twice(self):
        task, occurrence = self._drafted_run()
        self.assertEqual((occurrence["policy"], occurrence["authority"]), ("review", "workflow_review"))
        self.assertEqual(local(occurrence["stages"]["reviewAt"]), "Thu 2026-10-01 09:00")
        self.assertEqual(task["lastAnchorAt"], occurrence["anchorAt"])
        self.assertEqual(local(task["nextOccurrence"]["anchorAt"]), "Wed 2026-10-07 09:00")

    def test_decisions_record_exactly_what_was_reviewed_and_silence_never_approves(self):
        task, occurrence = self._drafted_run()
        item = occurrence["items"][0]
        decide = lambda **extra: campaigns.apply_action(self.state, "raffi_run_decide", {"occurrenceId": occurrence["id"], "itemKey": item["key"], "decision": "approve", "confirmed": True,
                                                                                         "variantRevision": 2, "excludedUnknowns": ["No date given."], "acknowledgedWarnings": ["Check the facts."], **extra}, "approver-1", self.now)
        with self.assertRaisesRegex(AlphaError, "changed"):
            decide(variantRevision=1)
        with self.assertRaisesRegex(AlphaError, "unknown"):
            decide(excludedUnknowns=[])
        with self.assertRaisesRegex(AlphaError, "warning"):
            decide(acknowledgedWarnings=[])
        decide()
        self.assertEqual((item["state"], item["approvedVia"], item["decision"]["by"], item["decision"]["textDigest"]), ("approved", "human", "approver-1", digest("A reflection.")))
        # Too late: the publish time passed.
        other = occurrence["items"][1]
        other["publishAt"] = self.now - 1
        with self.assertRaises(AlphaError) as late:
            campaigns.apply_action(self.state, "raffi_run_decide", {"occurrenceId": occurrence["id"], "itemKey": other["key"], "decision": "approve", "confirmed": True, "variantRevision": 2,
                                                                     "excludedUnknowns": ["No date given."], "acknowledgedWarnings": ["Check the facts."]}, "approver-1", self.now)
        self.assertEqual(late.exception.code, "approval_expired")
        campaigns.apply_action(self.state, "raffi_run_decide", {"occurrenceId": occurrence["id"], "itemKey": other["key"], "decision": "revise", "confirmed": True, "note": "Shorter please"}, "approver-1", self.now)
        self.assertEqual((other["state"], other["reason"]), ("needs_revision", "Shorter please"))

    def test_an_edit_retimes_waiting_posts_and_skips_removed_platforms_without_a_new_run(self):
        task, occurrence = self._drafted_run()
        runs_before = len(self.state["raffi"]["campaignPlanning"]["occurrences"])
        payload = automation_edit._payload(self.state, task)
        payload["workflow"]["stages"]["publish"] = {"weekday": "Friday", "localTime": "18:00"}
        payload["destinations"] = [d for d in payload["destinations"] if d["platform"] != "X"]
        campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "owner-1", self.now)
        self.assertEqual(local(occurrence["items"][0]["publishAt"]), "Fri 2026-10-02 18:00")
        self.assertEqual(occurrence["items"][1]["state"], "skipped")
        self.assertEqual(len(self.state["raffi"]["campaignPlanning"]["occurrences"]), runs_before)
        self.assertEqual(local(task["nextOccurrence"]["anchorAt"]), "Wed 2026-10-07 09:00")

    def test_automation_research_never_triggers_new_material_automations(self):
        self.state["sources"] = [{"id": "s1", "active": True, "kind": "text", "createdAt": self.now, "origin": {"kind": "automation_research"}},
                                 {"id": "s2", "active": True, "kind": "text", "createdAt": self.now, "title": "Mine"}]
        events = campaigns.new_source_events(self.state, {"watchFrom": self.now - 1, "schedule": {"kind": "on_new_source"}})
        self.assertEqual([e["sourceId"] for e in events], ["s2"])


class LifecycleTests(unittest.TestCase):
    def test_python_matches_the_shared_vectors(self):
        self.assertEqual(list(lifecycle.ITEM_STATES), VECTORS["itemStates"])
        self.assertEqual({k: list(v) for k, v in lifecycle.TRANSITIONS.items()}, VECTORS["transitions"])
        for case in VECTORS["moves"]:
            self.assertEqual(lifecycle.can_move(case["from"], case["to"]), case["allowed"], case)
        for case in VECTORS["status"]:
            self.assertEqual(lifecycle.status(case["run"]), case["status"], case)
        for case in VECTORS["attentionCases"]:
            self.assertEqual(lifecycle.attention(case["run"]), case["attention"], case)
        for case in VECTORS["projected"]:
            self.assertEqual(lifecycle.projected(case["run"]), case["projected"], case)
        for case in VECTORS["jobCases"]:
            self.assertEqual(lifecycle.job_item_state(case["job"], case["channelReady"]), case["item"], case)

    def test_review_cannot_jump_to_scheduled(self):
        with self.assertRaises(AlphaError):
            lifecycle.move({"state": "ready_for_review"}, "scheduled")
        with self.assertRaises(AlphaError):
            lifecycle.move({"state": "published"}, "failed")


class PublishingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.state = base_state()
        self.task = {"definitionDigest": "d", "publishAuthority": {"grantedBy": "owner-1", "definitionDigest": "d", "sourceUse": False}}
        self.item = {"platform": "X"}

    def test_auto_publish_refuses_instead_of_forging(self):
        clean = {"text": "Short.", "unknowns": [], "warnings": [], "sourceIds": []}
        self.assertEqual(publisher.auto_blockers(self.state, self.task, {}, self.item, clean), [])
        self.assertTrue(publisher.auto_blockers(self.state, self.task, {}, self.item, {**clean, "unknowns": ["a date"]}))
        self.assertTrue(publisher.auto_blockers(self.state, self.task, {}, self.item, {**clean, "warnings": ["Something new"]}))
        self.assertTrue(publisher.auto_blockers(self.state, self.task, {}, self.item, {**clean, "text": "x" * 281}))
        self.assertTrue(publisher.auto_blockers(self.state, self.task, {"research": {"quote": {"verified": False}}}, self.item, clean))
        research_note = "Some facts came from web research (bbc.co.uk); check them against the pages before scheduling."
        self.assertTrue(publisher.auto_blockers(self.state, self.task, {}, self.item, {**clean, "warnings": [research_note]}))
        self.task["publishAuthority"]["sourceUse"] = True
        self.assertEqual(publisher.auto_blockers(self.state, self.task, {}, self.item, {**clean, "warnings": [research_note]}), [])
        self.state["sources"] = [{"id": "s", "active": True, "sourcePolicy": "internal_reference"}]
        self.assertTrue(publisher.auto_blockers(self.state, self.task, {}, self.item, {**clean, "sourceIds": ["s"]}))
        self.task["definitionDigest"] = "changed"
        self.assertIn("confirmed again", publisher.auto_blockers(self.state, self.task, {}, self.item, clean)[0])

    def test_manifest_time_is_the_publish_minute_or_two_minutes_from_now(self):
        self.assertEqual(publisher._manifest_time(at(2026, 10, 3, 18), HK, at(2026, 10, 3, 17, 30))["localTime"], "2026-10-03T18:00")
        self.assertEqual(publisher._manifest_time(at(2026, 10, 3, 18), HK, at(2026, 10, 3, 17, 59) + 30)["localTime"], "2026-10-03T18:02")


class CapabilityTests(unittest.TestCase):
    class Adapter:
        production_reviewed = True

    def test_publishing_is_promised_only_when_every_link_exists(self):
        state = base_state()
        providers = {"linkedin": self.Adapter()}
        route = lambda destination, **kw: capabilities.publish_route(state, destination, **{"providers": providers, "live": True, **kw})
        self.assertTrue(route({"platform": "LinkedIn", "channelId": "li"})["publish"])
        self.assertEqual(route({"platform": "X"})["code"], "not_configured")  # hosted X connector exists; no adapter mounted here
        self.assertEqual(route({"platform": "Xiaohongshu"})["code"], "no_route")
        self.assertEqual(route({"platform": "LinkedIn", "channelId": "li"}, live=False)["code"], "not_live")
        self.assertEqual(route({"platform": "LinkedIn", "channelId": "li"}, can_publish=False)["code"], "plan")
        self.assertEqual(route({"platform": "Threads", "channelId": "th"})["code"], "not_configured")
        state["phase2"]["channels"][0]["revoked"] = True
        self.assertEqual(route({"platform": "LinkedIn", "channelId": "li"})["code"], "disconnected")
        self.assertEqual(route({"platform": "LinkedIn"})["code"], "not_connected")


NOW = at(2026, 9, 24, 10)


class ReadingTests(unittest.TestCase):
    """The deterministic reading generalizes: none of these requests is special-cased."""

    def read(self, text):
        return workflow_parse.read_automation(text, NOW, HK)

    def test_one_time_and_recurring_schedules(self):
        self.assertEqual(self.read("Post an update about my music studio today at 2 PM")["schedule"], {"kind": "once", "date": "2026-09-24", "localTime": "14:00"})
        self.assertEqual(self.read("Share a thank-you note to my students tomorrow at 8:30am on Threads")["schedule"], {"kind": "once", "date": "2026-09-25", "localTime": "08:30"})
        slots = self.read("Every Monday at 9am and Thursday at 5pm, share a piano practice tip on Threads and publish automatically.")
        self.assertEqual(slots["schedule"]["slots"], [{"weekday": "Monday", "localTime": "09:00"}, {"weekday": "Thursday", "localTime": "17:00"}])
        self.assertEqual(slots["policy"], "auto")
        both = self.read("Every Wednesday and Friday at 4:30 PM, create a motivational quote post using a quote from a famous scientist and publish it to Xiaohongshu, LinkedIn, and X.")
        self.assertEqual([s["weekday"] for s in both["schedule"]["slots"]], ["Wednesday", "Friday"])
        self.assertEqual(both["platforms"], ["Xiaohongshu", "LinkedIn", "X"])
        self.assertEqual(both["research"]["quote"], {"about": "famous scientist"})
        self.assertEqual(self.read("Every Wednesday at 5, make a motivational post for LinkedIn.")["schedule"]["slots"][0]["localTime"], "17:00")
        self.assertEqual(self.read("On the 1st of every month, summarize the latest Reuters news about renewable energy for LinkedIn")["schedule"]["kind"], "monthly")

    def test_stages_sources_conditions_and_platform_notes(self):
        final = self.read("Every Wednesday, find something interesting from a reputable science publication that relates to creativity. Write a short reflection in my voice. "
                          "Have it ready for me Thursday morning. If I approve it, publish a shorter version on X and a fuller version on LinkedIn Friday at 4:30 PM. "
                          "Skip the week if there isn't anything genuinely worth posting.")
        self.assertEqual(final["stages"]["review"], {"weekday": "Thursday", "localTime": "09:00"})
        self.assertEqual(final["stages"]["publish"], {"weekday": "Friday", "localTime": "16:30"})
        self.assertEqual(final["policy"], "review")
        self.assertIn("nature.com", final["research"]["domains"])
        self.assertEqual((final["research"]["about"], final["research"]["onNothing"]), ("creativity", "skip"))
        self.assertEqual(final["platformNotes"], {"X": "a shorter version", "LinkedIn": "a fuller version"})
        self.assertTrue(final["voice"])
        self.assertEqual(final["content"]["task"], "reflection")
        guardian = self.read("Each Tuesday pick a Guardian story about climate policy, summarize it for LinkedIn and let me approve it first; if nothing fits, post a general tip anyway")
        self.assertEqual((guardian["research"]["domains"], guardian["research"]["onNothing"], guardian["policy"]), (["theguardian.com"], "draft_without", "review"))
        link = self.read("Every Friday, read https://example.org/weekly and post my takeaways to LinkedIn at 6 PM")
        self.assertEqual(link["research"]["urls"], ["https://example.org/weekly"])

    def test_policy_is_only_what_the_person_said(self):
        self.assertIsNone(self.read("Every Wednesday at 5, make a motivational post for LinkedIn.")["policy"])
        self.assertEqual(self.read("Every Tuesday draft me a post about warm-ups")["policy"], "drafts")
        self.assertEqual(self.read("Every day at 8am post a vocabulary word, no need to ask me")["policy"], "auto")

    def test_edits_and_questions(self):
        read = lambda text: workflow_parse.read_edit(text, NOW, HK)
        self.assertEqual(read("Actually move it to Friday at 6")["changes"], [{"op": "move", "stage": "auto", "weekdays": ["Friday"], "localTime": "18:00"}])
        self.assertEqual(read("Stop posting this to X")["changes"], [{"op": "remove_platform", "platform": "X"}])
        self.assertEqual(read("Use Reuters instead of BBC")["changes"][0]["domains"], ["reuters.com"])
        self.assertEqual(read("Make these auto-publish from now on")["changes"], [{"op": "policy", "policy": "auto"}])
        self.assertEqual(read("Pause this for two weeks")["changes"], [{"op": "pause", "days": 14}])
        deleted = read("Delete the motivational quote automation")
        self.assertEqual((deleted["changes"], deleted["target"]["name"]), ([{"op": "delete"}], "motivational quote"))
        self.assertEqual(read("Pause the BBC reflection automation")["target"]["name"], "BBC reflection")
        self.assertEqual(workflow_parse.read_explain("Why wasn't yesterday's post published?")["about"], "not_published")
        self.assertEqual(workflow_parse.read_explain("Where did this article come from?")["about"], "source")
        self.assertFalse(workflow_parse.is_edit("Write a post about why I practise scales every day"))
        self.assertFalse(workflow_parse.is_recurring_request("I practise every day, write a post about it"))
        self.assertTrue(workflow_parse.is_recurring_request("Every Monday, find a Nature article about sleep and summarize it"))


class ChatPlanTests(unittest.TestCase):
    def setUp(self):
        self.state = base_state()
        self.now = at(2026, 9, 28, 10)

    def build(self, text, **reading):
        automation = {**workflow_parse.read_automation(text, self.now, HK), **reading}
        return automation_plan.build(self.state, "owner-1", self.now, text, HK, automation, destinations=[{"platform": "LinkedIn", "language": "en"}],
                                     route="deterministic-preview", reasoning="quick", voice=False, voice_route="local-cli", source_ids=[])

    def test_only_the_publishing_decision_and_review_timing_are_asked(self):
        _, question, _ = self.build("Every Wednesday at 5, make a motivational post for LinkedIn.")
        self.assertEqual(question, "policy")
        _, question, _ = self.build("Every Wednesday at 5, make a motivational post for LinkedIn and send it to me for approval first.")
        self.assertEqual(question, "review_time")
        payload, question, _ = self.build("Every Tuesday draft me a post about warm-ups")
        self.assertIsNone(question)
        self.assertEqual(payload["workflow"]["policy"], "drafts")
        payload, question, _ = self.build("Every Wednesday, find a notable BBC News article, have it ready for me Thursday morning, and publish it Saturday at 6 PM.")
        self.assertIsNone(question)
        self.assertEqual(payload["workflow"]["stages"]["generate"], {"at": "anchor"})
        payload, _, _ = self.build("Every Tuesday at 3 PM, post a studio tip about scales on LinkedIn and publish automatically.")
        self.assertEqual(payload["workflow"]["stages"]["generate"], {"minutesOffset": -60})
        self.assertEqual(payload["destinations"][0]["channelId"], "li", "the only connected LinkedIn account is used")

    def test_answers_to_questions(self):
        self.assertEqual(automation_plan.answer_policy("Publish automatically"), "auto")
        self.assertEqual(automation_plan.answer_policy("let me check them first"), "review")
        self.assertEqual(automation_plan.answer_policy("just drafts please"), "drafts")
        self.assertIsNone(automation_plan.answer_policy("what's the weather"))
        schedule = {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": HK}
        self.assertEqual(automation_plan.answer_review_time("The day before at 17:00", schedule), {"dayOffset": -1, "localTime": "17:00"})
        self.assertEqual(automation_plan.answer_review_time("2 hours before", schedule), {"minutesOffset": -120})
        self.assertEqual(automation_plan.answer_review_time("Sunday evening", schedule), {"dayOffset": -1, "localTime": "18:00"})

    def test_confirmation_is_plain_words_and_honest_about_platforms(self):
        payload, question, notes = self.build("Every Wednesday and Friday at 4:30 PM, create a quote post and publish it to LinkedIn and X, send it to me for approval the day before at 5pm.")
        saved = campaigns.apply_action(self.state, "raffi_recurrence_save", payload, "owner-1", self.now)
        automation_plan.activate(self.state, saved["taskId"], "owner-1", self.now, owner=True, paid=False, question=question)
        view = automation_plan.card(self.state, saved["taskId"], [], notes, providers={"linkedin": CapabilityTests.Adapter()}, live=True)
        text = automation_plan.reply(view)
        for forbidden in ("{", "cron", "anthropic", "claude", "haiku", "sonnet", saved["taskId"]):
            self.assertNotIn(forbidden, text.lower())
        self.assertIn("Publishing to X isn't available yet", text)  # hosted X route exists; no X adapter is mounted here
        self.assertIn("Nothing publishes without your approval", text)


class ReviewFindingTests(unittest.TestCase):
    """Regressions for the adversarial review: consent, draft binding, honest routes, retiming."""

    def test_negated_or_unrelated_words_never_grant_automatic_publishing(self):
        self.assertEqual(automation_plan.answer_policy("No, don't publish automatically. Send them to me for approval first"), "review")
        self.assertIsNone(automation_plan.answer_policy("What does this automation do?"))
        self.assertNotEqual(workflow_parse.read_automation("Every Monday at 9am post a tip to LinkedIn, but don't publish automatically", NOW, HK)["policy"], "auto")
        self.assertEqual(workflow_parse.read_edit("I don't want it to publish automatically", NOW, HK)["changes"], [{"op": "policy", "policy": "review"}])
        self.assertEqual(workflow_parse.read_edit("Make these auto-publish from now on", NOW, HK)["changes"], [{"op": "policy", "policy": "auto"}])

    def test_auto_publish_turns_on_only_with_an_explicit_grant(self):
        state, now = base_state(), at(2026, 9, 28, 10)
        saved = save(state, now, workflow={"policy": "auto"})
        needs = automation_plan.activate(state, saved["taskId"], "owner-1", now, owner=True, paid=False, question=None)
        self.assertEqual([n["code"] for n in needs], ["auto_publish"])
        self.assertEqual(task_of(state, saved["taskId"])["status"], "draft")
        automation_plan.activate(state, saved["taskId"], "owner-1", now, owner=True, paid=False, question=None, grant={"confirmed": True, "sourceUse": False})
        self.assertEqual(task_of(state, saved["taskId"])["publishAuthority"]["sourceUse"], False)

    def test_an_owner_edit_keeps_their_grant_without_widening_it(self):
        state, now = base_state(), at(2026, 9, 28, 10)
        saved = save(state, now, workflow={"policy": "auto"})
        campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True, "publishAuthority": {"confirmed": True, "sourceUse": False}}, "owner-1", now)
        result = automation_edit.apply(state, "owner-1", now, {"target": {"name": None}, "changes": [{"op": "move", "stage": "auto", "localTime": "18:00"}]},
                                       conversation_task_id=saved["taskId"], owner=True, paid=False, zone=HK)
        task = task_of(state, saved["taskId"])
        self.assertEqual((task["status"], task["publishAuthority"]["grantedBy"], task["publishAuthority"]["sourceUse"]), ("active", "owner-1", False), result)
        # Another owner's unrelated edit does not inherit the grant: it waits for their confirmation.
        automation_edit.apply(state, "owner-2", now, {"target": {"name": None}, "changes": [{"op": "move", "stage": "auto", "localTime": "19:00"}]},
                              conversation_task_id=saved["taskId"], owner=True, paid=False, zone=HK)
        self.assertEqual(task["status"], "draft")
        self.assertNotIn("publishAuthority", task)

    def test_instagram_is_never_promised_for_text_automations(self):
        state = base_state()
        state["phase2"]["channels"].append({"id": "ig", "platform": "Instagram", "account": "@me", "evidenceSource": "live_provider", "identityVerified": True, "capabilityVerified": True})
        route = capabilities.publish_route(state, {"platform": "Instagram", "channelId": "ig"}, providers={"instagram": CapabilityTests.Adapter()}, live=True)
        self.assertEqual((route["publish"], route["code"]), (False, "needs_image"))

    def test_retiming_never_turns_a_draft_only_item_into_a_publication(self):
        state, now = base_state(), at(2026, 9, 28, 10)
        saved = save(state, now)
        campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", now)
        task = task_of(state, saved["taskId"])
        run = campaigns.claim_occurrence(state, task["id"], task["nextOccurrence"]["scheduledFor"], now)
        run.update(lifecycle="drafted", generatedAt=now, items=[{"key": "X||en", "platform": "X", "channelId": None, "language": "en", "state": "approved", "publishAt": None, "jobId": None}])
        payload = automation_edit._payload(state, task)
        payload["workflow"]["stages"]["publish"] = {"weekday": "Friday", "localTime": "18:00"}
        campaigns.apply_action(state, "raffi_recurrence_save", payload, "owner-1", now)
        self.assertIsNone(run["items"][0]["publishAt"])

    def test_commit_refuses_changed_drafts_and_early_or_late_calls(self):
        class Engine:
            def __init__(self, variants):
                self.variants = variants

            def _variant(self, state, variant_id):
                return self.variants[variant_id]

            def apply_phase2(self, *args):
                raise AssertionError("must not reach the publishing chain")
        state, now = base_state(), at(2026, 9, 28, 10)
        saved = save(state, now, workflow={"policy": "auto"})
        campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True, "publishAuthority": {"confirmed": True}}, "owner-1", now)
        task = task_of(state, saved["taskId"])
        run = campaigns.claim_occurrence(state, task["id"], task["nextOccurrence"]["scheduledFor"], now)
        publish = run["stages"]["publishAt"]
        item = {"key": "LinkedIn|li|en", "platform": "LinkedIn", "channelId": "li", "language": "en", "state": "approved", "publishAt": publish, "jobId": None, "variantId": "v",
                "approvedVia": "owner_preauthorization", "decision": {"decision": "approve", "by": "owner-1", "variantRevision": 1, "textDigest": digest("Approved text")}}
        run.update(lifecycle="drafted", items=[item])
        engine = Engine({"v": {"id": "v", "revision": 2, "text": "Edited later", "unknowns": [], "warnings": [], "sourceIds": []}})
        with self.assertRaises(AlphaError) as early:
            publisher.commit(engine, state, "owner-1", {"occurrenceId": run["id"], "itemKey": item["key"]}, publish - 3 * 3600)
        self.assertEqual(early.exception.code, "not_due")
        with self.assertRaises(AlphaError) as changed:
            publisher.commit(engine, state, "owner-1", {"occurrenceId": run["id"], "itemKey": item["key"]}, publish - 600)
        self.assertEqual(changed.exception.code, "draft_changed")
        with self.assertRaises(AlphaError) as someone_else:
            publisher.commit(engine, state, "approver-9", {"occurrenceId": run["id"], "itemKey": item["key"]}, publish - 600)
        self.assertEqual(someone_else.exception.status, 403)


class CorrectnessFindingTests(unittest.TestCase):
    """Regressions for the correctness review: routing, one-time edits, stage order, reading gaps."""

    def test_drafting_requests_are_never_edits_or_questions_about_an_automation(self):
        names = ["BBC reflection"]
        for text in ("pause before the chorus — write a post about that", "Write a post about how to restart practice after a break",
                     "Why is sight-reading so hard? Write a LinkedIn post about it", "Write a LinkedIn post about my recital and also post it on Instagram"):
            self.assertTrue(workflow_parse.is_drafting_request(text), text)
        self.assertFalse(workflow_parse.refers_to_automation("Why do musicians practise scales?", names, False))
        self.assertTrue(workflow_parse.refers_to_automation("Pause the BBC reflection automation", names, False))
        self.assertTrue(workflow_parse.refers_to_automation("move it to Friday", names, True))
        self.assertIsNone(automation_plan.answer_policy("Write a post reviewing Yuja Wang's recital"))
        self.assertIsNone(automation_plan.answer_review_time("Write a post about my Sunday recital", {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": HK}))

    def test_a_one_time_automation_stays_editable_after_its_run_started(self):
        state, now = base_state(), at(2026, 9, 28, 10)
        saved = save(state, now, schedule={"kind": "once", "date": "2026-09-30", "localTime": "14:00", "timeZone": HK}, workflow={"policy": "review", "stages": {"generate": {"asap": True}}})
        campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", now)
        task = task_of(state, saved["taskId"])
        run = campaigns.claim_occurrence(state, task["id"], task["nextOccurrence"]["scheduledFor"], now)
        run.update(lifecycle="drafted", state="completed", generatedAt=now, items=[{"key": "LinkedIn|li|en", "platform": "LinkedIn", "channelId": "li", "language": "en", "state": "ready_for_review", "publishAt": run["stages"]["publishAt"], "jobId": None}])
        result = automation_edit.apply(state, "owner-1", now, {"target": {"name": None}, "changes": [{"op": "voice", "voice": True}]}, conversation_task_id=task["id"], owner=True, paid=False, zone=HK)
        self.assertEqual(task["status"], "active", result)
        self.assertIsNone(task["nextOccurrence"], "no second run for the same post")
        automation_edit.apply(state, "owner-1", now, {"target": {"name": None}, "changes": [{"op": "move", "stage": "auto", "localTime": "18:00"}]}, conversation_task_id=task["id"], owner=True, paid=False, zone=HK)
        self.assertEqual((task["status"], local(run["items"][0]["publishAt"])), ("active", "Wed 2026-09-30 18:00"))
        self.assertEqual(len([o for o in state["raffi"]["campaignPlanning"]["occurrences"] if o["taskId"] == task["id"]]), 1)

    def test_stage_order_is_checked_on_every_slot(self):
        slots = {"weekdays": ["Monday", "Thursday"], "localTime": "07:00", "slots": [{"weekday": "Monday", "localTime": "07:00"}, {"weekday": "Thursday", "localTime": "09:00"}], "timeZone": HK}
        with self.assertRaisesRegex(AlphaError, "after the drafts"):
            workflow.normalize_workflow({"policy": "auto", "stages": {"generate": {"dayOffset": 0, "localTime": "08:00"}}}, slots)

    def test_monthly_review_named_by_weekday_asks_instead_of_failing(self):
        reading = {"schedule": {"kind": "monthly", "monthDays": [1], "localTime": "09:00"}, "stages": {"review": {"weekday": "Friday", "localTime": "17:00"}}, "policy": "review", "timeRole": "publish"}
        stages, question = automation_plan.stages_for(reading, {"kind": "monthly", "monthDays": [1], "localTime": "09:00", "timeZone": HK}, "review")
        self.assertEqual(question, "review_time")

    def test_reading_gaps_from_the_review(self):
        read = lambda text: workflow_parse.read_automation(text, NOW, HK)
        self.assertEqual(read("Every morning at 7 post a vocabulary word on LinkedIn")["schedule"]["slots"][0]["localTime"], "07:00")
        self.assertTrue(workflow_parse.wants_publishing("Every Friday at 6pm post on LinkedIn about practice"))
        self.assertEqual(read("Every weekend at noon, share a fun fact on Threads automatically")["policy"], "auto")
        twice = read("Twice a week, post a practice tip for Threads, let me approve first")
        self.assertEqual(([s["weekday"] for s in twice["schedule"]["slots"]], twice["policy"]), (["Tuesday", "Friday"], "review"))
        zh = read("每個月1號早上10點，總結AI新聞，發到LinkedIn，要我批准先")
        self.assertEqual((zh["policy"], workflow_parse.wants_publishing("每個月1號早上10點，總結AI新聞，發到LinkedIn")), ("review", True))
        self.assertEqual(read("Every Wednesday at 9am draft a lesson recap and send it to me the day before at 6pm")["policy"], "review")
        self.assertEqual(read("Every Monday publish a short tip on X and a longer version on LinkedIn")["platformNotes"], {"X": "a short version", "LinkedIn": "a longer version"})
        self.assertIn("every week", " ".join(read("Every other Friday at 4pm post a studio update on LinkedIn")["assumptions"]))
        self.assertNotIn("LinkedIn", read("Publish a post about our open house on LinkedIn on October 3 at 10am")["topic"])


class ExplainTests(unittest.TestCase):
    def test_answers_come_from_the_run_history(self):
        state = base_state()
        now = at(2026, 9, 28, 10)
        saved = save(state, now)
        campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", now)
        task = task_of(state, saved["taskId"])
        run = campaigns.claim_occurrence(state, task["id"], task["nextOccurrence"]["scheduledFor"], now)
        run.update(lifecycle="skipped", research={"decision": "nothing_worth", "reason": "Nothing from bbc.co.uk in the last 7 days cleared the bar for “music”."})
        campaigns._history(run, now, "skipped", "Nothing from bbc.co.uk in the last 7 days cleared the bar for “music”.")
        answer = automation_explain.answer(state, "Why wasn't this week's post published?", {"about": "not_published", "target": {"name": None}}, conversation_task_id=task["id"], now=now)
        self.assertTrue(any("cleared the bar" in line for line in answer["lines"]), answer["lines"])
        self.assertTrue(any(line.startswith("Outcome: Skipped") for line in answer["lines"]), answer["lines"])


if __name__ == "__main__":
    unittest.main()
