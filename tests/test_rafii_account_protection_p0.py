"""Rafii Account Protection v2, phase P0 (preflight 2026-10-14, Approval A-P0).

Every first sighting of a session becomes a `session.observed` account event in the session row's transaction, before
the alert preference is read; the sign-in paths that used to record a session silently (bootstrap, invitation
acceptance) alert like /api/me; Notification V2 derives one notice per session from that event, still governed by the
person's alert preference (owner decision D-1); browser labels and security times are honest. All of it sits behind
RAFII_ACCOUNT_PROTECTION_V2_MODE=observe, and `off` (the default) keeps today's behaviour.

Statement-level tests over a recording cursor; the SQL dedupe between `session.observed` and `session.alerted` and the
V2 cutover against a real database are covered by the acceptance matrix, not here.
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_phase2 import account_protection, hosted  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.email import Mailer, NullTransport  # noqa: E402
from postriff_phase2.notifications import detector  # noqa: E402

SESSION = "session-current-0123456789"
WS = "00000000-0000-0000-0000-0000000000aa"
OBSERVED = ("session.observed", SESSION)


def audits(cursor, kind):
    return [params for sql, params in cursor.executed if "INSERT INTO public.pr_audit_events" in sql and params[2] == kind]


class Mode(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)

    def observe(self):
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe"})

    def off(self):
        flags.attach({})


class ModeFlag(Mode):
    def test_off_unless_exactly_observe(self):
        self.assertEqual(account_protection.mode({}), "off")
        self.assertEqual(account_protection.mode({"RAFII_ACCOUNT_PROTECTION_V2_MODE": " Observe "}), "observe")
        # P1 enforcement observes too; any other value is off.
        self.assertEqual(account_protection.mode({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce"}), "enforce")
        self.assertTrue(account_protection.observing({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce"}))
        self.assertFalse(account_protection.enforcing({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe"}))
        self.assertEqual(account_protection.mode({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "1"}), "off")


class SessionObserved(Mode):
    def alerting(self, cursor):
        svc = base.service(cursor, base.verifier(), email_lookup=lambda principal: "me@example.invalid")
        svc.public_base_url = "https://app.example"
        svc.mailer = base.FakeMailer()
        return svc

    def test_first_sighting_is_recorded_with_the_session_even_when_alerts_are_off(self):
        self.observe()
        cursor = base.FakeCursor([((True,), 1), ((False,), 1), (None, 1), (("James", None, "", "", False), 1), *base.STYLE_READ, ((False, ""), 1)])
        svc = self.alerting(cursor)
        svc.me("t", client_label="Safari on iPhone")
        self.assertIn("RETURNING (xmax = 0)", cursor.executed[0][0])
        # The account event follows the session row on the same cursor (one transaction), with the alert decision
        # taken from the preference at that moment.
        self.assertIn("alert_new_device", cursor.executed[1][0])
        self.assertEqual(cursor.executed[2][1][1:4], (base.PRINCIPAL, *OBSERVED))
        self.assertEqual(json.loads(cursor.executed[2][1][4]), {"client": "Safari on iPhone", "alert": False})
        self.assertEqual(svc.mailer.calls, [])
        self.assertEqual(audits(cursor, "session.alerted"), [])

    def test_a_session_seen_before_records_nothing_new(self):
        self.observe()
        cursor = base.FakeCursor([((False,), 1), (("James", None, "", "", True), 1)])
        svc = self.alerting(cursor)
        svc.me("t", client_label="Safari on iPhone")
        self.assertEqual((audits(cursor, "session.observed"), svc.mailer.calls), ([], []))

    def test_two_tabs_racing_record_one_event(self):
        # Two requests carrying one new session: PostgreSQL's ON CONFLICT lets exactly one insert win (xmax = 0).
        self.observe()
        first = base.FakeCursor([((True,), 1), ((True,), 1), (None, 1)])
        second = base.FakeCursor([((False,), 1)])
        svc = self.alerting(first)
        self.assertTrue(svc._touch_session(first, base.PRINCIPAL, SESSION, "Chrome on Mac"))
        self.assertFalse(svc._touch_session(second, base.PRINCIPAL, SESSION, "Chrome on Mac"))
        self.assertEqual(len(audits(first, "session.observed")) + len(audits(second, "session.observed")), 1)

    def test_off_mode_keeps_todays_statements(self):
        self.off()
        cursor = base.FakeCursor([((True,), 1), (("James", None, "", "", False), 1), *base.STYLE_READ, ((False, ""), 1)])
        svc = self.alerting(cursor)
        svc.me("t", client_label="Safari on iPhone")
        self.assertEqual((audits(cursor, "session.observed"), len(cursor.executed)), ([], 6))

    def bootstrap(self, touch):
        responses = [((1,), 1), ((WS,), 1), ((1, {"phase2": {}}, "studio", 1.0, 2.0, 10, 0, 1, "owner", True, True, True, True), 1), touch]
        if touch[0] == (True,) and account_protection.observing():
            responses += [((True,), 1), (None, 1), ((True, ""), 1), (None, 1)]
        cursor = base.FakeCursor(responses)
        svc = self.alerting(cursor)
        svc.commands = SimpleNamespace(present=lambda state, revision: {"revision": revision})
        svc.bootstrap("t", "studio", client_label="Safari on iPhone")
        return cursor, svc

    def test_bootstrap_first_sign_in_records_the_alert_decision_like_api_me(self):
        self.observe()
        cursor, svc = self.bootstrap(((True,), 1))
        self.assertEqual(len(audits(cursor, "session.observed")), 1)
        # The email itself leaves the request (RAP-143): the cron's deliver_sign_in_alerts sends it from this row.
        self.assertEqual(json.loads(audits(cursor, "session.observed")[0][4])["alert"], True)
        self.assertEqual(svc.mailer.calls, [])
        # A later /api/me finds the session already seen, so the person is told exactly once.
        cursor, svc = self.bootstrap(((False,), 1))
        self.assertEqual((audits(cursor, "session.observed"), svc.mailer.calls), ([], []))

    def test_bootstrap_stays_silent_in_off_mode(self):
        self.off()
        cursor, svc = self.bootstrap(((True,), 1))
        self.assertEqual((audits(cursor, "session.observed"), svc.mailer.calls), ([], []))

    def accept(self, touch_fresh):
        invitation = ("inv-1", base.WORKSPACE, "editor", {"can_publish": True})
        responses = [((1,), 1), (invitation, 1), (None, 1), (None, 0), (None, 1), (None, 1), (("manual-seats", 10, 1, 2, 2, 200, None, "manual", 1), 1), ((1,), 1), (None, 1), (None, 1), (None, 1),
                     ((touch_fresh,), 1)]
        if touch_fresh and account_protection.observing():
            responses += [((True,), 1), (None, 1), ((True, ""), 1), (None, 1)]
        cursor = base.FakeCursor(responses)
        svc = self.alerting(cursor)
        return cursor, svc, svc.accept_my_invitation("t", "inv-1", client_label="Safari on iPhone")

    def test_invitation_acceptance_on_a_new_session_alerts_after_commit(self):
        self.observe()
        cursor, svc, result = self.accept(True)
        self.assertNotIn("_alertSession", result)  # the marker never reaches the API response
        self.assertEqual(result["workspaceId"], base.WORKSPACE)
        observed = audits(cursor, "session.observed")
        self.assertEqual(json.loads(observed[0][4]), {"client": "Safari on iPhone", "alert": True})  # R1: the browser is kept
        self.assertEqual(svc.mailer.calls, [])  # RAP-143: the cron sends it from the recorded decision

    def test_invitation_acceptance_off_mode_is_unchanged(self):
        self.off()
        cursor, svc, result = self.accept(True)
        self.assertNotIn("_alertSession", result)
        self.assertEqual((audits(cursor, "session.observed"), svc.mailer.calls), ([], []))


class SignInAlertDelivery(Mode):
    """RAP-133/143: the cron step that sends observe mode's new-sign-in emails, capped per person."""
    def test_sends_from_the_recorded_event_and_suppresses_past_the_cap(self):
        self.observe()
        cursor = base.FakeCursor([([(base.PRINCIPAL, "sess-a"), (base.PRINCIPAL, "sess-b")], 2),
                                  ((True,), 1), ((1_791_996_977.0, "Safari on iPhone", ""), 1), ((0,), 1), (None, 1),
                                  ((True,), 1), ((1_791_996_978.0, "Chrome on Mac", ""), 1), ((hosted.SIGN_IN_ALERT_CAP,), 1), (None, 1)])
        svc = base.service(cursor, base.verifier(), email_lookup=lambda principal: "me@example.invalid")
        svc.public_base_url, svc.mailer = "https://app.example", base.FakeMailer()
        self.assertEqual(svc.deliver_sign_in_alerts(), {"status": "ok", "pending": 2, "sent": 1, "suppressed": 1})
        self.assertEqual(svc.mailer.calls, [("me@example.invalid", "Safari on iPhone", "https://app.example/app/account/profile")])
        self.assertEqual([(params[3], json.loads(params[4])) for params in audits(cursor, "session.alerted")],
                         [("sess-a", {"sent": True}), ("sess-b", {"sent": False, "reason": "rate_limited"})])

    def test_a_person_locked_by_another_run_is_left_for_it(self):
        self.observe()
        cursor = base.FakeCursor([([(base.PRINCIPAL, "sess-a")], 1), ((False,), 1)])
        svc = base.service(cursor, base.verifier(), email_lookup=lambda principal: "me@example.invalid")
        svc.public_base_url, svc.mailer = "https://app.example", base.FakeMailer()
        self.assertEqual(svc.deliver_sign_in_alerts()["sent"], 0)
        self.assertEqual((svc.mailer.calls, audits(cursor, "session.alerted")), ([], []))

    def test_off_mode_has_nothing_to_deliver(self):
        self.off()
        svc = base.service(base.FakeCursor([]), base.verifier())
        svc.public_base_url = "https://app.example"
        self.assertEqual(svc.deliver_sign_in_alerts(), {"status": "disabled"})


class SessionHistoryErasure(unittest.TestCase):
    """RAP-088 (owner decision A+B): deletion erases the session inventory, after the device-registry purge."""
    SOURCE = (Path(__file__).resolve().parents[1] / "src" / "postriff_phase2" / "account_deletion.py").read_text()

    def test_erasure_runs_only_when_installed_and_after_the_security_purge(self):
        # pr_session_security references pr_sessions ON DELETE RESTRICT (migration 120), so its rows must go first.
        self.assertIn("to_regprocedure('public.pr_erase_session_history(uuid)')", self.SOURCE)
        self.assertLess(self.SOURCE.index("SELECT public.pr_security_purge(%s)"), self.SOURCE.index("SELECT public.pr_erase_session_history(%s)"))
        self.assertLess(self.SOURCE.index("SELECT public.pr_erase_session_history(%s)"), self.SOURCE.index("DELETE FROM public.pr_profiles WHERE user_id=%s"))


class AlertsCannotBeCancelledBySignIn(Mode):
    def test_a_new_session_turning_alerts_off_is_still_reported(self):
        # The reviewed attack (A2): a fresh session's very first call is PATCH /api/me {alertNewDevice: false}.
        self.observe()
        cursor = base.FakeCursor([((True,), 1), ((True,), 1), (None, 1), (("James", "", "", False), 1), *base.STYLE_READ, ((False, ""), 1), (None, 1)])
        svc = base.service(cursor, base.verifier(), email_lookup=lambda principal: "me@example.invalid")
        svc.public_base_url, svc.mailer = "https://app.example", base.FakeMailer()
        result = svc.update_profile("t", {"alertNewDevice": False}, client_label="Chrome on Windows")
        self.assertFalse(result["preferences"]["alertNewDevice"])  # the change itself still applies
        statements = [sql for sql, _ in cursor.executed]
        observed = next(i for i, (sql, params) in enumerate(cursor.executed) if "pr_audit_events" in sql and params[2] == "session.observed")
        upsert = next(i for i, sql in enumerate(statements) if "INSERT INTO public.pr_profiles" in sql)
        self.assertLess(observed, upsert)  # observed (with the setting as it was) before the setting changes
        self.assertEqual(json.loads(cursor.executed[observed][1][4]), {"client": "Chrome on Windows", "alert": True})
        # The cron sends from that recorded decision (meta.alert), not from the preference the session just changed.
        self.assertEqual(svc.mailer.calls, [])

    def test_off_mode_profile_changes_touch_nothing_new(self):
        self.off()
        cursor = base.FakeCursor([(("James", "", "", False), 1), *base.STYLE_READ])
        svc = base.service(cursor, base.verifier())
        svc.update_profile("t", {"alertNewDevice": False})
        self.assertFalse(any("pr_sessions" in sql or "pr_audit_events" in sql for sql, _ in cursor.executed))


class AccountHistory(unittest.TestCase):
    def test_an_observed_session_is_listed_once(self):
        audit_rows = [("e1", "session.observed", "session-phone-0123456789", 250.0, {"client": "Safari on iPhone"}, None, "")]
        session_rows = [("session-phone-0123456789", "Safari on iPhone", 250.0), ("session-old-000123456789", "Chrome", 50.0)]
        cursor = base.FakeCursor([(audit_rows, 1), (session_rows, 2)])
        feed = base.service(cursor, base.verifier()).security_events("t", limit=10)["events"]
        self.assertEqual([(event["kind"], event["subject"]) for event in feed],
                         [("session.observed", "session-phone-0123456789"), ("session.started", "session-old-000123456789")])
        self.assertIn("session.observed", cursor.executed[0][1][1])

    def test_a_single_revocation_says_which_session(self):
        cursor = base.FakeCursor([((1,), 1), (None, 1), (None, 1)])
        svc = base.service(cursor, base.verifier())
        svc.repository.assert_fresh = lambda token, principal: None
        svc.revoke_session("t", "session-other-0123456789")
        self.assertEqual(audits(cursor, "session.revoked")[0][3], "session-other-0123456789")

    def test_repeating_a_revocation_writes_no_second_audit_row(self):
        # RAP-051: the revocation row already exists (ON CONFLICT DO NOTHING inserts nothing), so nothing is audited.
        cursor = base.FakeCursor([((1,), 1), (None, 0)])
        svc = base.service(cursor, base.verifier())
        svc.repository.assert_fresh = lambda token, principal: None
        self.assertTrue(svc.revoke_session("t", "session-other-0123456789")["revoked"])
        self.assertEqual(audits(cursor, "session.revoked"), [])


class Detector(unittest.TestCase):
    def rows(self, *rows):
        cur = base.FakeCursor([(list(rows), len(rows))])
        return cur, detector.security_events(cur)

    def test_observed_sign_ins_carry_the_time_and_browser_and_follow_the_preference(self):
        cur, events = self.rows(("a1", base.PRINCIPAL, "session.observed", 1_791_996_977.0, "Safari on iPhone", False))
        sql = cur.executed[0][0]
        # D-1: preference-governed, as recorded at the first sighting (A2); the current setting only for older rows.
        self.assertIn("a.kind = 'session.observed' AND CASE WHEN a.meta->>'alert' IS NOT NULL THEN a.meta->>'alert' = 'true'", sql)
        self.assertIn("ELSE coalesce(p.alert_new_device, false) END", sql)
        self.assertIn("o.kind='session.observed' AND o.subject=a.subject", sql)  # one notice when both rows exist
        event = events[0]
        self.assertEqual((event["event_type"], event["dedupe_key"], event["occurred_at"]), ("security.new_device", "security.new_device:a1", 1_791_996_977.0))
        self.assertEqual(event["payload"], {"title": "New sign-in to your account", "href": "/app/account/profile", "device": "Safari on iPhone"})
        self.assertFalse(event["legacy_sent"])

    def test_legacy_rows_keep_their_shape(self):
        _, events = self.rows(("a2", base.PRINCIPAL, "session.alerted"), ("a3", base.PRINCIPAL, "mfa.enabled"))
        self.assertEqual([(e["event_type"], e["payload"]["title"], e["legacy_sent"]) for e in events],
                         [("security.new_device", "A new device signed in", True), ("security.account_change", "Two-step sign-in was turned on", True)])
        self.assertNotIn("occurred_at", events[0])


class CommittingDB(base.FakeDB):
    def commit(self):
        pass


class FirstRunBaseline(Mode):
    def run_cron(self):
        from postriff_phase2.notifications.service import NotificationService  # needs the push dependencies
        events = [{"event_type": "security.new_device", "dedupe_key": "security.new_device:a1", "user_id": base.PRINCIPAL, "payload": {}, "legacy_sent": False},
                  {"event_type": "security.new_device", "dedupe_key": "security.new_device:a2", "user_id": base.PRINCIPAL, "payload": {}, "legacy_sent": True}]
        cursor = base.FakeCursor([((True,), 1), ([], 0)])
        svc = NotificationService.__new__(NotificationService)
        svc.enabled = lambda: True
        svc.hosted = SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda: CommittingDB(cursor)))
        svc.emit = mock.Mock(return_value={"created": True})
        svc.worker = lambda: mock.Mock()
        with mock.patch.object(detector, "security_events", return_value=events):
            result = svc.cron()
        self.assertTrue(all("legacy_sent" not in call.kwargs for call in svc.emit.call_args_list))
        return {call.kwargs["dedupe_key"]: call.kwargs.get("baseline", False) for call in svc.emit.call_args_list}, result

    def test_off_mode_keeps_the_original_first_run_baseline(self):
        # A3: with account protection off, enabling notifications V2 never replays a day of old alerts.
        self.off()
        calls, result = self.run_cron()
        self.assertEqual(calls, {"security.new_device:a1": True, "security.new_device:a2": True})
        self.assertEqual(result["security"], {"created": 0})

    def test_observe_mode_baselines_only_alerts_the_legacy_mailer_delivered(self):
        self.observe()
        calls, result = self.run_cron()
        self.assertEqual(calls, {"security.new_device:a1": False, "security.new_device:a2": True})
        self.assertEqual(result["security"], {"created": 1})  # only the alert nobody was sent counts as a new notice


class Labels(unittest.TestCase):
    AGENTS = {
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1": "Safari on iPhone",
        "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1": "Chrome on iPad",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36": "Chrome on Mac",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0": "Edge on Windows",
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0": "Firefox on Linux",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/122.0 Mobile Safari/537.36": "Samsung Internet on Android",
        "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36": "Chrome on ChromeOS",
        "Mozilla/5.0 (Windows NT 10.0)": "Browser on Windows",
        "Mozilla/5.0 (compatible; <script>alert(1)</script>)": "Unrecognized browser",
        "curl/8.7.1": "Unrecognized browser",
        "": "Unrecognized browser",
    }

    def test_labels_name_a_browser_family_and_os_and_never_echo_the_header(self):
        for agent, label in self.AGENTS.items():
            with self.subTest(agent=agent[:40]):
                self.assertEqual(account_protection.browser_label(agent), label)
                self.assertLessEqual(len(account_protection.browser_label(agent)), 40)
        self.assertEqual(account_protection.browser_label(None), "Unrecognized browser")


class SecurityTimes(unittest.TestCase):
    AT = 1_791_996_977.0  # 2026-10-14T16:56:17Z, the time of the eBay reference notice

    def test_the_zone_abbreviation_follows_daylight_saving(self):
        self.assertEqual(account_protection.security_time(self.AT, "America/Los_Angeles"), "14 October 2026, 09:56 PDT (America/Los_Angeles) · 16:56 UTC")
        january = 1_799_946_000.0  # 2027-01-14T17:00:00Z
        self.assertEqual(account_protection.security_time(january, "America/Los_Angeles"), "14 January 2027, 09:00 PST (America/Los_Angeles) · 17:00 UTC")

    def test_a_different_local_date_repeats_the_utc_date(self):
        self.assertEqual(account_protection.security_time(self.AT, "Asia/Hong_Kong"), "15 October 2026, 00:56 HKT (Asia/Hong_Kong) · 14 October 2026, 16:56 UTC")

    def test_without_a_valid_zone_utc_alone(self):
        for zone in ("", "Not/AZone", "../etc/passwd", None, "x" * 80):
            with self.subTest(zone=zone):
                self.assertEqual(account_protection.security_time(self.AT, zone), "14 October 2026, 16:56 UTC")
        self.assertEqual(account_protection.security_time("soon", "UTC"), "an unknown time")

    def test_the_email_carries_the_same_time_in_text_and_html(self):
        transport = NullTransport()
        Mailer(transport, "Rafii <no-reply@rafii.invalid>", "https://app.example").new_device("me@example.invalid", "Safari on iPhone", self.AT, "https://app.example/app/account/profile", time_zone="America/Los_Angeles")
        mail = transport.sent[0]
        for body in (mail["text"], mail["html"]):
            self.assertIn("09:56 PDT", body)
            self.assertIn("16:56 UTC", body)
        self.assertNotIn("PST", mail["text"])


    def test_numeric_dates_for_copy_in_any_language(self):
        self.assertEqual(account_protection.security_time(self.AT, "America/Los_Angeles", numeric=True), "2026-10-14 09:56 PDT (America/Los_Angeles) · 16:56 UTC")
        self.assertEqual(account_protection.security_time(self.AT, "Asia/Hong_Kong", numeric=True), "2026-10-15 00:56 HKT (Asia/Hong_Kong) · 2026-10-14 16:56 UTC")
        self.assertEqual(account_protection.security_time(self.AT, "", numeric=True), "2026-10-14 16:56 UTC")


class V2SignInDetails(unittest.TestCase):
    """R2: the Notification V2 security email shows the browser and the time, not only a title."""
    AT = SecurityTimes.AT

    def details(self, **ctx):
        from postriff_phase2.notifications.delivery import DeliveryWorker  # needs the push dependencies
        return DeliveryWorker._sign_in_details({"type": "security.new_device", "payload": {"device": "Safari on iPhone"}, "occurredAt": self.AT,
                                                "timeZone": "America/Los_Angeles", "locale": "en", **ctx})

    def test_browser_and_local_time_in_the_persons_language(self):
        self.assertEqual(self.details(), [("Browser", "Safari on iPhone"), ("Time", "2026-10-14 09:56 PDT (America/Los_Angeles) · 16:56 UTC")])
        self.assertEqual([label for label, _ in self.details(locale="zh-Hant-HK")], ["瀏覽器", "時間"])
        self.assertEqual(self.details(payload={}, timeZone=""), [("Time", "2026-10-14 16:56 UTC")])

    def test_only_new_sign_ins_and_only_recorded_facts(self):
        self.assertIsNone(self.details(type="security.account_change"))
        self.assertIsNone(self.details(payload={}, occurredAt=None))

    def test_the_rendered_email_carries_them_in_text_and_html(self):
        from postriff_phase2.notifications import email_render
        message = email_render.render("security_alert", locale="en", values={"title": "New sign-in to your account"}, base_url="https://app.example",
                                      href="/app/account/profile", transactional=True, details=self.details())
        for body in (message["text"], message["html"]):
            self.assertIn("Safari on iPhone", body)
            self.assertIn("09:56 PDT", body)


if __name__ == "__main__":
    unittest.main()
