"""A chat request for recurring drafts becomes an automation with the builder's checks (automation_chat)."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError, initial_state  # noqa: E402
from postriff_phase2 import automation_chat, campaigns, request_model  # noqa: E402

HK = "Asia/Hong_Kong"
EXAMPLE = "Set up an Automation of drafting me a news article post using my voice and template uploaded here about the topic of AI for Science on every Tuesday"


class ScheduleTest(unittest.TestCase):
    def schedule(self, text):
        return automation_chat.schedule_of(text, HK)

    def test_weekly_days_and_times(self):
        for text, weekdays, local in (
            ("every Tuesday", ["Tuesday"], "09:00"),
            ("on Tuesdays and Fridays at 7:30pm", ["Tuesday", "Friday"], "19:30"),
            ("every weekday at 8am", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "08:00"),
            ("every day", list(campaigns.WEEKDAY_NAMES), "09:00"),
            ("every evening", list(campaigns.WEEKDAY_NAMES), "18:00"),
            ("every weekend", ["Saturday", "Sunday"], "09:00"),
            ("逢星期二同星期五晚上8點", ["Tuesday", "Friday"], "20:00"),
        ):
            with self.subTest(text=text):
                schedule, _ = self.schedule(text)
                self.assertEqual(schedule, {"weekdays": weekdays, "localTime": local, "timeZone": HK})

    def test_monthly_days(self):
        for text, days in (("every month on the 15th", [15]), ("on the 1st and 15th of every month", [1, 15]), ("on the last day of every month", ["last"]), ("每個月1號", [1]), ("monthly", [1])):
            with self.subTest(text=text):
                schedule, _ = self.schedule(text)
                self.assertEqual((schedule["kind"], schedule["monthDays"]), ("monthly", days))

    def test_what_had_to_be_assumed_is_said(self):
        _, notes = self.schedule("every week")
        self.assertTrue(any("09:00" in note for note in notes) and any("Monday" in note for note in notes))
        schedule, notes = self.schedule("every other week on Monday at 10:00")
        self.assertEqual(schedule["weekdays"], ["Monday"])
        self.assertTrue(any("every week" in note for note in notes))


class ReadingTest(unittest.TestCase):
    def test_topic_stops_before_schedule_and_settings(self):
        self.assertEqual(automation_chat.topic_of(EXAMPLE), "AI for Science")
        self.assertEqual(automation_chat.topic_of("Write me a LinkedIn post every Tuesday about AI in music, using my voice"), "AI in music")
        self.assertEqual(automation_chat.topic_of("Every Monday draft a tip about warm-ups for LinkedIn"), "warm-ups")
        self.assertEqual(automation_chat.topic_of("逢星期二幫我寫一篇關於AI for Science嘅新聞文章"), "AI for Science")
        self.assertIsNone(automation_chat.topic_of("Every Monday, draft a practice tip"))

    def test_describe(self):
        self.assertEqual(automation_chat.describe({"weekdays": ["Tuesday"], "localTime": "09:00", "timeZone": HK}), "Every Tuesday at 09:00 (Asia/Hong_Kong)")
        self.assertEqual(automation_chat.describe({"kind": "monthly", "monthDays": [1, 22, "last"], "localTime": "08:30", "timeZone": HK}), "On the 1st, the 22nd and the last day of every month at 08:30 (Asia/Hong_Kong)")


class CreateTest(unittest.TestCase):
    def setUp(self):
        self.state = initial_state("workspace-one")
        self.state["phase2"] = {"channels": [{"id": "acct-linkedin", "platform": "LinkedIn", "account": "Studio page"}]}
        self.state["sources"] = [
            {"id": "src-template", "active": True, "kind": "text", "title": "News post template"},
            {"id": "src-voice", "active": True, "kind": "voice_sample", "selected": True},
        ]
        # Thursday 24 September 2026, 21:00 in Hong Kong.
        self.now = dt.datetime(2026, 9, 24, 13, tzinfo=dt.timezone.utc).timestamp()

    def create(self, text=EXAMPLE, **changes):
        options = {"destinations": [{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}], "route": "deterministic-preview",
                   "voice_route": "local-cli", "reasoning": "quick", "paid": False, "voice": False, "source_ids": ["src-template"], "owner": True}
        options.update(changes)
        return automation_chat.create(self.state, "owner-1", self.now, text, HK, **options)

    def task(self):
        return self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]

    def test_owner_request_with_a_free_writer_is_turned_on(self):
        view = self.create()
        task = self.task()
        self.assertEqual((view["status"], task["status"], task["activatedBy"]), ("active", "active", "owner-1"))
        self.assertEqual(task["schedule"], {"weekdays": ["Tuesday"], "localTime": "09:00", "timeZone": HK})
        self.assertEqual(task["destinations"], [{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}])
        self.assertEqual(task["contextSourceIds"], ["src-template"])
        self.assertEqual(task["voiceMode"], "personalized")
        self.assertEqual(task["contentType"]["contentTypeId"], "pack.creator:article_news_commentary")
        self.assertEqual(task["name"], "AI for Science · News article post")
        self.assertEqual(view["goal"], "A news article post about AI for Science.")
        self.assertEqual(view["audience"], automation_chat.DEFAULT_AUDIENCE)
        self.assertEqual(view["firstRun"], "Tuesday 29 September at 09:00")
        self.assertEqual(view["sources"], [{"id": "src-template", "title": "News post template"}])
        self.assertEqual(view["needs"], [])
        # The starter pack was installed because only it offers the news type.
        self.assertTrue(any(item["id"] == "pack.creator" for item in self.state["contentSystem"]["installedPacks"]))
        text = automation_chat.reply(view)
        self.assertTrue(text.startswith("Done. Every Tuesday at 09:00 (Asia/Hong_Kong), I'll prepare a news article post about AI for Science for LinkedIn (Studio page), in your voice"))
        self.assertIn("nothing is published without you", text)

    def test_decisions_left_to_the_owner_keep_it_waiting(self):
        view = self.create(paid=True)
        self.assertEqual((view["status"], [n["code"] for n in view["needs"]]), ("draft", ["spend"]))
        view = self.create(owner=False)
        self.assertEqual((view["status"], [n["code"] for n in view["needs"]]), ("draft", ["owner"]))
        view = self.create("Every Friday draft a post about my spring concert")
        self.assertEqual((view["status"], [n["code"] for n in view["needs"]]), ("draft", ["facts"]))
        self.assertIn("date and venue", view["needs"][0]["text"])
        self.assertIn("waiting for you", automation_chat.reply(view))

    def test_brand_audience_home_selection_and_neutral_voice(self):
        self.state["brandHub"]["audience"] = "Adult beginners"
        view = self.create("Every Monday draft a post about warm-ups")
        task = self.task()
        self.assertEqual((view["audience"], task["voiceMode"], task["contentType"]), ("Adult beginners", "neutral", None))
        self.assertFalse(any(item["id"] == "pack.creator" for item in self.state["contentSystem"]["installedPacks"]))
        view = self.create("Every Monday draft a practice tip about warm-ups as a carousel")
        self.assertEqual((self.task()["contentType"]["contentTypeId"], self.task()["contentType"]["formatId"]), ("postriff:teach", "carousel"))

    def test_a_missing_writing_sample_is_said_not_refused(self):
        self.state["sources"] = [item for item in self.state["sources"] if item["kind"] != "voice_sample"]
        view = self.create()
        self.assertEqual((view["status"], view["voiceMode"]), ("active", "personalized"))
        self.assertTrue(any("Brand page" in note for note in view["notes"]))

    def test_the_builder_checks_still_apply(self):
        with self.assertRaises(AlphaError):
            self.create(destinations=[{"platform": "LinkedIn", "language": "en", "channelId": "acct-gone"}])
        with self.assertRaises(AlphaError):
            self.create(route="local-cli")
        self.assertIn("could not set up", automation_chat.reply(None, "One selected account is no longer connected."))


class ModelReadingTest(unittest.TestCase):
    """Rafii's model reading is a proposal: only what fits this workspace is kept, and it merges over the rules."""

    def setUp(self):
        self.state = initial_state("workspace-one")
        self.state["phase2"] = {"channels": [{"id": "acct-linkedin", "platform": "LinkedIn", "account": "Studio page"}]}
        self.now = dt.datetime(2026, 9, 24, 13, tzinfo=dt.timezone.utc).timestamp()

    def test_reading_keeps_only_valid_fields(self):
        answer = {"action": "automation", "automation": {
            "weekdays": ["Friday", "Tuesday", "Someday"], "monthDays": [3], "localTime": "25:00", "topic": " AI news ", "goal": "A short AI news post.",
            "name": "AI news", "contentTypeId": "pack.creator:article_news_commentary", "formatId": "poll", "voice": True, "assumptions": ["Twice a week: Tuesday and Friday.", 7]}}
        reading = request_model.reading(answer, self.state)
        self.assertEqual(reading, {"action": "automation", "automation": {
            "weekdays": ["Tuesday", "Friday"], "topic": "AI news", "goal": "A short AI news post.", "name": "AI news",
            "contentTypeId": "pack.creator:article_news_commentary", "voice": True, "assumptions": ["Twice a week: Tuesday and Friday."]}})
        self.assertEqual(request_model.reading({"action": "draft", "automation": {"weekdays": ["Monday"]}}, self.state), {"action": "draft"})
        for bad in (None, {}, {"action": "publish"}, "automation"):
            self.assertIsNone(request_model.reading(bad, self.state))
        unknown = request_model.reading({"action": "automation", "automation": {"contentTypeId": "workspace_x:unknown", "monthDays": [0, 31, "last", 31]}}, self.state)
        self.assertEqual(unknown["automation"], {"monthDays": [31, "last"], "assumptions": []})

    def test_prompt_carries_only_the_message_date_and_catalog(self):
        self.state["sources"] = [{"id": "src-private", "active": True, "kind": "text", "title": "Private notes", "text": "secret"}]
        prompt = request_model.user_prompt("Every Tuesday draft AI news", HK, self.now, self.state)
        self.assertNotIn("secret", prompt)
        self.assertNotIn("Studio page", prompt)
        self.assertIn('"now": "Thursday 2026-09-24 21:00"', prompt)
        self.assertIn("pack.creator:article_news_commentary", prompt)
        self.assertGreater(request_model.price_quote_micro(self.state, prompt), 0)
        self.assertTrue(request_model.CUE.search("Keep my LinkedIn going with AI news twice a week"))
        self.assertFalse(request_model.CUE.search("Write a post about my recital"))

    def test_writer_route_decides_where_the_message_may_go(self):
        from postriff_phase2.agent_runtime import FixtureAgentRuntime
        from postriff_phase2.learning_model import GatewayCall
        from postriff_phase2.model_runtime import ServerModelRuntime
        self.assertIsNone(request_model.call_for(FixtureAgentRuntime()))
        call = request_model.call_for(ServerModelRuntime("gateway-key"))
        self.assertIsInstance(call, GatewayCall)
        self.assertEqual((call.model, call.local), (request_model.UNDERSTANDING_MODEL, False))
        marker = object()
        self.assertIs(request_model.call_for(FixtureAgentRuntime(), marker), marker)

    def test_understood_request_merges_over_the_rules(self):
        understood = request_model.reading({"action": "automation", "automation": {
            "weekdays": ["Tuesday", "Friday"], "topic": "AI news", "goal": "A short AI news post with my view.", "name": "AI news, twice a week",
            "contentTypeId": "pack.creator:article_news_commentary", "voice": True, "assumptions": ["Twice a week: Tuesday and Friday."]}}, self.state)["automation"]
        view = automation_chat.create(self.state, "owner-1", self.now, "Keep my LinkedIn going with AI news twice a week", HK,
                                      destinations=[{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}], route="deterministic-preview",
                                      voice_route="local-cli", reasoning="quick", paid=False, voice=False, source_ids=[], owner=True, understood=understood)
        task = self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]
        self.assertEqual(task["schedule"], {"weekdays": ["Tuesday", "Friday"], "localTime": "09:00", "timeZone": HK})
        self.assertEqual((task["name"], view["goal"], task["voiceMode"], task["status"]), ("AI news, twice a week", "A short AI news post with my view.", "personalized", "active"))
        self.assertEqual(task["contentType"]["contentTypeId"], "pack.creator:article_news_commentary")
        self.assertIn("Twice a week: Tuesday and Friday.", view["notes"])
        self.assertTrue(any("09:00" in note for note in view["notes"]))
        # A schedule the builder refuses falls back to the rules' reading.
        bad = {"monthDays": ["last"], "localTime": "07:00"}
        schedule = automation_chat._understood_schedule(bad, {"localTime": "09:00"}, HK)
        self.assertEqual(schedule["monthDays"], ["last"])
        self.assertIsNone(automation_chat._understood_schedule({}, {"localTime": "09:00"}, HK))

    def test_countdown_reading_becomes_a_countdown_automation(self):
        # Live gateway runs (2026-09-24) read "two weeks before, one week before and on the day" as monthly days
        # 4, 11 and 18, which would repeat every month after the event; a countdown has its own shape.
        answer = {"action": "automation", "automation": {"countdown": {"eventDate": "2026-10-18", "daysBefore": [0, 14, 7, 7]}, "monthDays": [4, 11, 18], "topic": "my recital"}}
        understood = request_model.reading(answer, self.state)["automation"]
        self.assertEqual(understood["countdown"], {"eventDate": "2026-10-18", "daysBefore": [14, 7, 0]})
        self.assertNotIn("monthDays", understood)
        for bad in ({"eventDate": "18 October", "daysBefore": [7]}, {"eventDate": "2026-10-18", "daysBefore": [120]}, {"eventDate": "2026-10-18", "daysBefore": []}):
            with self.subTest(bad=bad):
                reading = request_model.reading({"action": "automation", "automation": {"countdown": bad, "weekdays": ["Monday"]}}, self.state)["automation"]
                self.assertNotIn("countdown", reading)
                self.assertEqual(reading["weekdays"], ["Monday"])
        self.assertIn("countdown", request_model.schema(self.state)["properties"]["automation"]["properties"])
        self.assertTrue(request_model.CUE.search("Count down to my recital on 18 October"))
        self.assertTrue(request_model.CUE.search("幫我倒數音樂會"))
        view = automation_chat.create(self.state, "owner-1", self.now, "Count down to my recital on 18 October on LinkedIn", HK,
                                      destinations=[{"platform": "LinkedIn", "language": "en", "channelId": "acct-linkedin"}], route="deterministic-preview",
                                      voice_route="local-cli", reasoning="quick", paid=False, voice=False, source_ids=[], owner=True, understood=understood)
        task = self.state["raffi"]["campaignPlanning"]["recurringTasks"][-1]
        self.assertEqual(task["schedule"], {"kind": "countdown", "eventDate": "2026-10-18", "daysBefore": [14, 7, 0], "localTime": "09:00", "timeZone": HK})
        campaign = next(item for item in self.state["raffi"]["campaignPlanning"]["campaigns"] if item["id"] == task["campaignId"])
        self.assertEqual(campaign["facts"]["date"], "2026-10-18")
        # A recital still needs its venue, so the countdown waits for the owner instead of turning on.
        self.assertNotEqual(task["status"], "active")
        self.assertIn("facts", [need["code"] for need in view["needs"]])
        self.assertEqual(view["scheduleText"], "Countdown to 2026-10-18: 14 days before, 7 days before and on the day at 09:00 (Asia/Hong_Kong)")
        # A countdown whose dates have all passed is not used.
        past = {"countdown": {"eventDate": "2026-09-01", "daysBefore": [7, 0]}}
        self.assertIsNone(automation_chat._understood_schedule(past, {"localTime": "09:00"}, HK, self.now))
        self.assertIsNotNone(automation_chat._understood_schedule(past, {"localTime": "09:00"}, HK))


class VoiceModeTest(unittest.TestCase):
    def test_voice_is_part_of_what_is_drafted(self):
        state = initial_state("workspace-one")
        now = dt.datetime(2026, 9, 24, 13, tzinfo=dt.timezone.utc).timestamp()
        payload = {"name": "Tip", "goal": "One tip", "audience": "Students", "schedule": {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": HK},
                   "destinations": [{"platform": "LinkedIn", "language": "en"}], "route": "deterministic-preview", "maxCostUsdMicro": 0}
        saved = campaigns.apply_action(state, "raffi_recurrence_save", payload, "owner-1", now)
        campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, "owner-1", now)
        task = state["raffi"]["campaignPlanning"]["recurringTasks"][-1]
        self.assertEqual((task["voiceMode"], task["status"]), ("neutral", "active"))
        campaigns.apply_action(state, "raffi_recurrence_save", {**payload, "taskId": task["id"], "voiceMode": "personalized"}, "owner-1", now)
        self.assertEqual((task["voiceMode"], task["status"]), ("personalized", "draft"))
        with self.assertRaises(AlphaError):
            campaigns.apply_action(state, "raffi_recurrence_save", {**payload, "voiceMode": "loud"}, "owner-1", now)


if __name__ == "__main__":
    unittest.main()
