"""No-call tests. Every provider, connector transport, database and telephony admission is synthetic."""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.james_daily_call import (
    DailyCallConfig, DailyCallService, TEAM_REPORT_ORIGIN, TEAM_REPORT_ZONE,
    _team_report_context, _team_report_slot,
)
from postriff_phase2.personal_agent import JamesPersonalRouter
from postriff_phase2.productivity_connectors import ProductivityConnectorService

ACCOUNT = "personal@example.com"
BINDINGS = {p: {"account": ACCOUNT, "connectionId": "pc_" + c * 32}
            for p, c in (("gmail", "1"), ("google_calendar", "2"))}
BASE = {
    "JAMES_DAILY_CALL_ENABLED": "1", "JAMES_DAILY_CALL_OUTBOUND_ENABLED": "1",
    "JAMES_DAILY_CALL_SCHEDULED_ENABLED": "0", "JAMES_AGENT_TEAM_CALL_ENABLED": "1",
    "JAMES_DAILY_CALL_TIMEZONE": TEAM_REPORT_ZONE,
    "JAMES_DAILY_CALL_DAILY_USD_MICRO": "1000000", "JAMES_DAILY_CALL_MONTHLY_USD_MICRO": "5000000",
    "JAMES_DAILY_CALL_USER_ID": "11111111-1111-4111-8111-111111111111",
    "JAMES_DAILY_CALL_WORKSPACE_ID": "22222222-2222-4222-8222-222222222222",
    "JAMES_DAILY_CALL_GMAIL_ACCOUNT": ACCOUNT, "JAMES_DAILY_CALL_GMAIL_CONNECTION_ID": BINDINGS["gmail"]["connectionId"],
    "JAMES_DAILY_CALL_CALENDAR_ACCOUNT": ACCOUNT, "JAMES_DAILY_CALL_CALENDAR_CONNECTION_ID": BINDINGS["google_calendar"]["connectionId"],
    "JAMES_PHONE_E164": "+15555550123",
}
NOW = datetime(2026, 10, 5, 17, 2, tzinfo=ZoneInfo(TEAM_REPORT_ZONE)).timestamp()


def briefing(now=NOW, **changes):
    return {"kind": "half_day", "verified": True, "timeZone": TEAM_REPORT_ZONE, "cutoffLocalTime": "17:00",
            "generatedAt": now, "summary": "One registered mission needs a decision; acceptance is pending.",
            "happened": "Its worker stopped after saving progress.", "attempted": "Read-only diagnosis completed.",
            "impact": "The mission is waiting.", "requestedDecision": "Review the secure action card.",
            "evidenceRefs": ["event:test-worker-stopped"], "coverageGaps": ["One connector is unavailable."], **changes}


def database():
    cur, db = MagicMock(), MagicMock()
    db.__enter__.return_value = db
    db.cursor.return_value.__enter__.return_value = cur
    return db, cur


class PersonalIdentityTests(unittest.TestCase):
    def test_config_requires_both_explicit_account_bindings(self):
        self.assertEqual(DailyCallConfig(BASE).briefing_bindings, BINDINGS)
        with self.assertRaises(AlphaError) as raised:
            _ = DailyCallConfig({}).briefing_bindings
        self.assertEqual(raised.exception.code, "briefing_identity_unbound")

    def service(self, provider_id="gmail", account=ACCOUNT, missing=False):
        cur = Mock()
        cur.fetchone.return_value = None if missing else (BINDINGS[provider_id]["connectionId"],)
        provider = Mock()
        provider.authenticated_account.return_value = account
        service = ProductivityConnectorService(SimpleNamespace(), Mock(), providers={provider_id: provider}, flags={provider_id: True})
        service._connection = Mock(return_value={"connectionId": BINDINGS[provider_id]["connectionId"]})
        service._access_token = Mock(return_value="synthetic-token")
        return service, provider, cur

    def test_exact_bound_connection_selected_and_provider_identity_checked(self):
        for provider_id in BINDINGS:
            service, provider, cur = self.service(provider_id)
            service._personal_access(cur, "workspace", "user", provider_id, account_bindings=BINDINGS)
            sql, values = cur.execute.call_args.args
            self.assertIn("connection_id=%s AND lower(provider_account_id)=%s", sql)
            self.assertNotIn("ORDER BY updated_at", sql)
            self.assertEqual(values[-2:], (BINDINGS[provider_id]["connectionId"], ACCOUNT))
            provider.authenticated_account.assert_called_once_with("synthetic-token")
            provider.search.assert_not_called()

    def test_missing_binding_fails_before_any_provider_or_database_read(self):
        service, provider, cur = self.service()
        with self.assertRaises(AlphaError) as raised:
            service._personal_access(cur, "workspace", "user", "gmail")
        self.assertEqual(raised.exception.code, "briefing_identity_unbound")
        cur.execute.assert_not_called()
        provider.authenticated_account.assert_not_called()

    def test_work_identity_and_missing_account_never_fall_back(self):
        for account, missing, code in (("work@example.com", False, "briefing_identity_mismatch"),
                                      (ACCOUNT, True, "connector_not_connected")):
            service, provider, cur = self.service(account=account, missing=missing)
            with self.assertRaises(AlphaError) as raised:
                service._personal_access(cur, "workspace", "user", "gmail", account_bindings=BINDINGS)
            self.assertEqual(raised.exception.code, code)
            provider.search.assert_not_called()

    def test_personal_router_forwards_bindings_to_every_google_helper(self):
        connectors = Mock()
        connectors.personal_calendar_search.return_value = []
        connectors.personal_calendar_range.return_value = []
        connectors.personal_gmail_search.return_value = []
        daily = SimpleNamespace(cfg=DailyCallConfig(BASE), clock=lambda: NOW,
                                hosted=SimpleNamespace(productivity_connectors=connectors))
        router = JamesPersonalRouter(daily)
        router._calendar("Check my calendar tomorrow")
        router._calendar("Find my calendar appointment with Lori")
        router._gmail("Check unread email")
        for helper in (connectors.personal_calendar_range, connectors.personal_calendar_search, connectors.personal_gmail_search):
            self.assertEqual(helper.call_args.kwargs, {"account_bindings": BINDINGS})

    def test_opening_brief_forwards_same_bindings(self):
        connectors = Mock()
        connectors.daily_brief_context.return_value = {"gmail": {"status": "ok"}, "calendar": {"status": "ok"}}
        service = DailyCallService(SimpleNamespace(clock=lambda: NOW, productivity_connectors=connectors), BASE)
        service._context()
        self.assertEqual(connectors.daily_brief_context.call_args.kwargs, {"account_bindings": BINDINGS})


class AgentTeamReportTests(unittest.TestCase):
    def service(self, now=NOW, **config):
        db, cur = database()
        hosted = SimpleNamespace(clock=lambda: now, connection_factory=lambda: db)
        service = DailyCallService(hosted, {**BASE, **config})
        service._require_base = Mock()
        service._dial = Mock(side_effect=lambda run, _attempt: {**run, "state": "dialing"})
        service._create = Mock(side_effect=lambda _slot, _origin, context: ({"id": "synthetic-run", "context": context}, True))
        return service, cur

    def call(self, service, value=None, report_id="report-1", version=1):
        return service.call_report(report_id, "mission-1", "2026-10-05", version, briefing() if value is None else value)

    def test_half_day_report_uses_distinct_mission_slot_without_reading_personal_sources(self):
        service, _ = self.service()
        service._context = Mock(side_effect=AssertionError("Report calls must not read personal context"))
        result = self.call(service)
        slot, origin, context = service._create.call_args.args
        self.assertTrue(slot.startswith("team-report:"))
        self.assertEqual(origin, TEAM_REPORT_ORIGIN)
        self.assertEqual(context["agentTeamReport"]["missionId"], "mission-1")
        self.assertEqual(context["agentTeamReport"]["coverageGaps"], ["One connector is unavailable."])
        self.assertEqual(result["callsCreated"], 1)
        self.assertNotIn("context", result)
        service._context.assert_not_called()

    def test_whole_day_is_audio_pending_without_provider_admission(self):
        service, _ = self.service(now=datetime(2026, 10, 6, 1, tzinfo=ZoneInfo(TEAM_REPORT_ZONE)).timestamp())
        result = self.call(service, briefing(kind="whole_day", cutoffLocalTime="01:00"))
        self.assertEqual(result["state"], "audio_pending")
        self.assertEqual(result["callsCreated"], 0)
        service._require_base.assert_not_called()
        service._create.assert_not_called()
        service._dial.assert_not_called()

    def test_explicit_report_flag_is_required_without_creating_a_run(self):
        service, _ = self.service(JAMES_AGENT_TEAM_CALL_ENABLED="0")
        with self.assertRaises(AlphaError) as raised:
            self.call(service)
        self.assertEqual(raised.exception.code, "agent_team_call_disabled")
        service._create.assert_not_called()
        service._dial.assert_not_called()

    def test_quiet_night_and_stale_report_never_dial(self):
        quiet = datetime(2026, 10, 5, 22, tzinfo=ZoneInfo(TEAM_REPORT_ZONE)).timestamp()
        for now, changes, code in ((quiet, {"generatedAt": quiet}, "agent_team_call_window"),
                                  (NOW, {"generatedAt": NOW - 901}, "agent_team_report_stale"),
                                  (NOW, {"generatedAt": NOW + 61}, "agent_team_report_stale")):
            service, _ = self.service(now=now)
            with self.assertRaises(AlphaError) as raised:
                self.call(service, briefing(**changes))
            self.assertEqual(raised.exception.code, code)
            service._create.assert_not_called()
            service._dial.assert_not_called()
        service, _ = self.service(JAMES_DAILY_CALL_QUIET_START_MINUTE="1020", JAMES_DAILY_CALL_QUIET_END_MINUTE="1080")
        with self.assertRaises(AlphaError) as raised:
            self.call(service)
        self.assertEqual(raised.exception.code, "quiet_hours")
        service._dial.assert_not_called()

    def test_timezone_mismatch_fails_before_run(self):
        service, _ = self.service(JAMES_DAILY_CALL_TIMEZONE="America/Chicago")
        with self.assertRaises(AlphaError) as raised:
            self.call(service)
        self.assertEqual(raised.exception.code, "agent_team_timezone")
        service._create.assert_not_called()

    def test_report_contract_flag_does_not_claim_project_completion(self):
        context = _team_report_context("report-1", "mission-1", "2026-10-05", 1, briefing())
        self.assertTrue(context["agentTeamReport"]["reportContractVerified"])
        self.assertNotIn("completed", context["agentTeamReport"])
        self.assertIn("acceptance is pending", context["agentTeamReport"]["summary"])

    def test_invalid_or_executable_envelopes_fail_closed(self):
        for changes in ({"verified": False}, {"evidenceRefs": []}, {"generatedAt": float("nan")},
                        {"command": "delete files"}, {"summary": "x" * 1601}, {"coverageGaps": ["中" * 300] * 20}):
            service, _ = self.service()
            with self.assertRaises(AlphaError) as raised:
                self.call(service, briefing(**changes))
            self.assertEqual(raised.exception.code, "agent_team_report_invalid")
            service._dial.assert_not_called()

    def test_versions_and_supplements_cannot_generate_another_automatic_call(self):
        old = _team_report_context("report-1", "mission-1", "2026-10-05", 1, briefing())
        newer = _team_report_context("report-2", "mission-1", "2026-10-05", 2, briefing())
        self.assertEqual(_team_report_slot(old), _team_report_slot(newer))
        service, _ = self.service()
        service._create.return_value = ({"id": "existing-run", "state": "completed", "context": old}, False)
        service._create.side_effect = None
        result = self.call(service, report_id="report-2", version=2)
        self.assertTrue(result["replayed"])
        self.assertEqual(result["reportId"], "report-1")
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["callsCreated"], 0)
        service._dial.assert_not_called()

    def test_real_run_creation_checks_cost_before_insert_with_report_duration(self):
        service, cur = self.service()
        service._create = DailyCallService._create.__get__(service)
        service._existing = Mock(return_value=None)
        service._estimate = Mock(return_value=125)
        service._budget_check = Mock()
        context = _team_report_context("report-1", "mission-1", "2026-10-05", 1, briefing())
        service._create(_team_report_slot(context), TEAM_REPORT_ORIGIN, context)
        service._estimate.assert_called_once_with(90)
        service._budget_check.assert_called_once_with(cur, NOW, extra=125)
        self.assertIn("pg_advisory_xact_lock", cur.execute.call_args_list[0].args[0])

    def test_daily_monthly_cost_caps_block_report_estimate(self):
        service, cur = self.service()
        for spend, code in (([999_950, 0], "daily_cost_cap"), ([0, 4_999_950], "monthly_cost_cap")):
            with patch.object(service, "_spend", side_effect=spend):
                with self.assertRaises(AlphaError) as raised:
                    service._budget_check(cur, NOW, extra=100)
            self.assertEqual(raised.exception.code, code)

    def test_dial_reuses_scoped_phone_admission_and_ninety_second_limit(self):
        service, cur = self.service()
        service._dial = DailyCallService._dial.__get__(service)
        service._estimate = Mock(return_value=125)
        service._budget_check = Mock()
        context = _team_report_context("report-1", "mission-1", "2026-10-05", 1, briefing())
        scoped = Mock()
        scoped.request.return_value = {"id": "synthetic-call", "conversationId": "synthetic-conversation"}
        with patch("postriff_phase2.james_daily_call.principal_phone", return_value=(scoped, "synthetic-capability")):
            service._dial({"id": "synthetic-run", "origin": TEAM_REPORT_ORIGIN, "context": context}, 1)
        args, kwargs = scoped.request.call_args
        self.assertEqual(args[2]["idempotencyKey"], "jtr:synthetic-run:a1")
        self.assertEqual(args[2]["callDurationLimitSeconds"], 90)
        self.assertEqual(kwargs["_destination_ref"], "james_env")
        self.assertEqual(kwargs["kind"], "explicit")
        service._budget_check.assert_called_once_with(cur, NOW, extra=125)

    def test_opening_is_immutable_report_only_and_decision_remains_candidate(self):
        service, _ = self.service()
        context = _team_report_context("report-1", "mission-1", "2026-10-05", 1, briefing())
        service._row_for_call = Mock(return_value={"context": context})
        service._context = Mock(side_effect=AssertionError("No personal source refresh"))
        prompt = service.initial_request("synthetic-call")
        self.assertIn("AGENT_TEAM_REPORT_JSON=", prompt)
        self.assertIn("One connector is unavailable", prompt)
        self.assertIn("separate authenticated mission decision path", prompt)
        self.assertNotIn("DAILY_CONTEXT_JSON=", prompt)
        service._context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
