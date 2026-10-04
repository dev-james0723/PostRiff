import threading
import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from postriff_phase2.personal_agent import JamesPersonalRouter, calendar_window, gmail_query
from postriff_phase2.phone.session import PhoneSessionController


TZ = "America/Chicago"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo(TZ)).timestamp()


class FakeConnectors:
    def __init__(self):
        self.calendar_calls = []
        self.calendar_search_calls = []
        self.gmail_calls = []

    def personal_calendar_range(self, workspace, user, zone, start, end, limit):
        self.calendar_calls.append((workspace, user, zone, start, end, limit))
        return [
            {"title": "Lori lesson", "start": "2026-10-05T15:30:00-05:00", "end": "2026-10-05T16:30:00-05:00", "location": "Studio"},
            {"title": "Studio class", "start": "2026-10-06T19:30:00-05:00", "end": "2026-10-06T20:30:00-05:00", "location": ""},
        ]

    def personal_calendar_search(self, workspace, user, query, limit):
        self.calendar_search_calls.append((workspace, user, query, limit))
        return [{"title": "Lori lesson", "excerpt": "2026-10-22T15:30:00-05:00 · Studio"}]

    def personal_gmail_search(self, workspace, user, query, limit):
        self.gmail_calls.append((workspace, user, query, limit))
        return [{"subject": "Recording time confirmed", "from": "Violinist <music@example.com>", "snippet": "Weekend works.", "date": "today"}]


class FakePulse:
    def fetch(self):
        return {"status": "ok", "items": [
            {"project": "Kynlo", "title": "Kynlo optimization", "branch": "fix/orc", "state": "running",
             "verification": "tests passing", "nextAction": "finish acceptance", "client": "codex", "updatedAt": "today"},
            {"project": "Dori", "title": "Dori voice", "branch": "feat/dori", "state": "blocked",
             "verification": "browser pending", "nextAction": "run iPhone acceptance", "client": "codex", "updatedAt": "today"},
        ]}


class Daily:
    def __init__(self):
        self.cfg = SimpleNamespace(workspace_id="w1", user_id="u1", time_zone=TZ)
        self.values = {}
        self.hosted = SimpleNamespace(productivity_connectors=FakeConnectors(), connection_factory=None)
        self.project_pulse = FakePulse()

    def clock(self):
        return NOW

    def personal_context_refresh(self):
        return "Refreshed personal context."


class PersonalAgentTests(unittest.TestCase):
    def setUp(self):
        self.daily = Daily()
        self.router = JamesPersonalRouter(self.daily)

    def test_next_week_resolves_calendar_range_and_fetches_live_calendar(self):
        start, end, label = calendar_window("What do I have next week?", NOW, TZ)
        self.assertEqual(label, "next week")
        self.assertEqual(datetime.fromtimestamp(start, ZoneInfo(TZ)).date().isoformat(), "2026-10-05")
        self.assertEqual(datetime.fromtimestamp(end, ZoneInfo(TZ)).date().isoformat(), "2026-10-12")

        result = self.router.route("What do I have next week?")
        self.assertEqual((result["status"], result["kind"], result["sourceCount"]), ("ok", "calendar", 2))
        self.assertIn("Lori lesson", result["speakable"])
        self.assertIn("Studio class", result["speakable"])
        self.assertEqual(len(self.daily.hosted.productivity_connectors.calendar_calls), 1)

    def test_cantonese_next_week_routes_calendar(self):
        result = self.router.route("下個禮拜我有啲咩活動？")
        self.assertEqual(result["kind"], "calendar")
        self.assertIn("Google Calendar", result["speakable"])

    def test_named_calendar_event_search_is_not_limited_to_next_seven_days(self):
        result = self.router.route("When is my next Lori lesson?")
        self.assertEqual(result["kind"], "calendar")
        self.assertIn("Lori lesson", result["speakable"])
        self.assertEqual(len(self.daily.hosted.productivity_connectors.calendar_calls), 0)
        self.assertEqual(len(self.daily.hosted.productivity_connectors.calendar_search_calls), 1)

    def test_short_calendar_followup_inherits_previous_tool_domain(self):
        result = self.router.route("What about Tuesday?", hint="calendar")
        self.assertEqual(result["kind"], "calendar")
        self.assertIn("Google Calendar", result["speakable"])

    def test_weather_place_followup_inherits_weather_domain(self):
        weather = Mock()
        weather.now.return_value = {
            "place": "Bloomington",
            "current": {"temperatureC": 20.0, "feelsLikeC": 19.0, "conditions": "clear"},
            "today": {"highC": 23.0, "lowC": 12.0, "rainChancePercent": 10},
        }
        with patch("postriff_phase2.personal_agent.live_tools.default_weather", return_value=weather):
            result = self.router.route("Bloomington", hint="weather")
        self.assertEqual(result["kind"], "weather")
        self.assertIn("Bloomington", result["speakable"])

    def test_gmail_reply_question_builds_safe_query_and_searches(self):
        query = gmail_query("有冇人覆我錄音時間？")
        self.assertIn("in:inbox", query)
        self.assertIn("newer_than:30d", query)
        self.assertIn("錄音時間", query)
        result = self.router.route("有冇人覆我錄音時間？")
        self.assertEqual(result["kind"], "gmail")
        self.assertIn("Recording time confirmed", result["speakable"])
        self.assertNotIn("IGNORE", result["speakable"])

    def test_project_question_filters_project_pulse(self):
        result = self.router.route("Kynlo project 去到邊？")
        self.assertEqual(result["kind"], "project")
        self.assertIn("Kynlo", result["speakable"])
        self.assertNotIn("Dori voice", result["speakable"])

    def test_weather_named_place_uses_read_only_weather(self):
        weather = Mock()
        weather.now.return_value = {
            "place": "Bloomington",
            "current": {"temperatureC": 20.0, "feelsLikeC": 19.0, "conditions": "partly cloudy"},
            "today": {"highC": 23.0, "lowC": 12.0, "rainChancePercent": 20},
        }
        with patch("postriff_phase2.personal_agent.live_tools.default_weather", return_value=weather):
            result = self.router.route("What's the weather in Bloomington?")
        self.assertEqual(result["kind"], "weather")
        self.assertIn("Bloomington", result["speakable"])
        self.assertIn("68°F", result["speakable"])
        weather.now.assert_called_once()

    def test_weather_without_place_asks_one_question(self):
        result = self.router.route("What's the weather?")
        self.assertEqual((result["status"], result["kind"]), ("needs_input", "weather"))
        self.assertIn("Which city", result["speakable"])

    def test_unknown_personal_question_refreshes_without_rafii_manager(self):
        result = self.router.route("What should I focus on?")
        self.assertEqual(result["kind"], "snapshot")
        self.assertEqual(result["speakable"], "Refreshed personal context.")

    def test_phone_delegation_passes_exact_question_to_personal_router_not_rafii_manager(self):
        class Cursor:
            def __init__(self):
                self.one = None
            def execute(self, sql, params=()):
                if sql.startswith('SELECT state,summary FROM public.pr_phone_delegations'):
                    self.one = None
                elif sql.startswith('INSERT INTO public.pr_phone_delegations'):
                    self.one = ('delegation-1',)
                else:
                    self.one = None
            def fetchone(self):
                return self.one

        cursor = Cursor()
        db = Mock()
        @contextmanager
        def transaction(*_args):
            yield cursor, None, 'u1'
        @contextmanager
        def cursor_context():
            yield cursor
        db.cursor = cursor_context
        @contextmanager
        def connection_factory():
            yield db

        daily = SimpleNamespace(query_personal=Mock(return_value={
            'status': 'ok', 'kind': 'calendar',
            'speakable': 'Next week you have two events.', 'sourceCount': 2
        }))
        controller = PhoneSessionController.__new__(PhoneSessionController)
        controller.call_id = 'call-1'
        controller.closed = False
        controller.user_text = 'What do I have next week?'
        controller.lock = threading.Lock()
        controller.call = {
            'workspace_id': 'w1', 'destination_ref': 'james_env',
            'voice_run_id': 'voice-1', 'conversation_id': 'conversation-1'
        }
        controller.capability = 'cap'
        controller.runtime = SimpleNamespace(
            service=SimpleNamespace(repository=SimpleNamespace(transaction=transaction)),
            turn=Mock(side_effect=AssertionError('Rafii Manager must not run for James personal calls')),
        )
        controller.service = SimpleNamespace(
            hosted=SimpleNamespace(james_daily_call=daily, connection_factory=connection_factory),
            abort_delegation=Mock(),
        )
        with patch('postriff_phase2.phone.session.store.prefs', return_value={'timeZone': TZ}):
            result = controller.delegate({'delegation': {'id': 'delegation-1', 'target': 'client'}})
        daily.query_personal.assert_called_once_with('What do I have next week?', hint=None)
        controller.runtime.turn.assert_not_called()
        self.assertEqual(result['type'], 'session.commentary.append')
        self.assertEqual(result['delegation_id'], 'delegation-1')
        self.assertEqual(result['content'], 'Next week you have two events.')

    def test_result_is_bounded_for_live_commentary(self):
        self.daily.hosted.productivity_connectors.personal_calendar_range = Mock(return_value=[
            {"title": "X" * 500, "start": "2026-10-05T15:30:00-05:00", "end": "", "location": "Y" * 500}
            for _ in range(20)
        ])
        result = self.router.route("What do I have next week?")
        self.assertLessEqual(len(result["speakable"]), 1200)


if __name__ == "__main__":
    unittest.main()
