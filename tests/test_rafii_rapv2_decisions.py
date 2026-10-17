"""RAPv2: James's account-protection decisions of 2026-10-16, the parts that need no database.

Decision 5 (incident banner), 6 (step-up notices), 7 (previous address for 14 days), 8 (city) and 11 (support release
inputs). The database-backed checks are rows DEC-03..DEC-08 of tests/phase2/postgres_rapv2_acceptance.py and the
founder action is tests/control/test_founder_actions_pg.py. Synthetic identities only; nothing is sent.
"""
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import account_protection, security_center, security_gate, security_policy as policy  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.notifications import detector, email_render  # noqa: E402
from postriff_phase2.notifications.delivery import DeliveryWorker  # noqa: E402

USER = "10000000-0000-4000-8000-000000000001"
SESSION = "session-decisions-0123456789"
HOLD = {"RAFII_SECURITY_INCIDENT_HOLD": "1"}


class Rows:
    """A connection factory whose cursor answers fetchall/fetchone from a fixed list and records statements."""
    def __init__(self, rows=(), fail=False):
        self.rows, self.fail, self.executed = list(rows), fail, []

    @contextmanager
    def __call__(self):
        outer = self

        class Cursor:
            def execute(self, sql, params=None):
                if outer.fail:
                    raise RuntimeError('relation "public.pr_security_contact_changes" does not exist')
                outer.executed.append((sql, params))

            def fetchall(self):
                return outer.rows

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        class DB:
            def cursor(self):
                return Cursor()

        yield DB()


class Flags(unittest.TestCase):
    def setUp(self):
        self.addCleanup(flags.attach, {})
        # No hold table in a unit test: core_hold (flag off) skips its probe, as in test_rafii_risk_engine.
        from postriff_phase2 import security_holds
        saved = dict(security_holds._INSTALLED)
        self.addCleanup(security_holds._INSTALLED.update, saved)
        security_holds._INSTALLED.update(readable=False, checked=float("inf"))


class PreviousAddress(Flags):
    """Decision 7: for 14 days after an email change, security notices also go to the previous address."""

    def test_expiry_is_safe_before_the_migration_and_on_errors(self):
        missing = base.FakeCursor([((False,), 1)])
        factory = lambda: base.FakeDB(missing)
        self.assertEqual(security_center.expire_contact_changes(factory), {"status": "not_installed"})
        self.assertEqual(security_center.expire_contact_changes(Rows(fail=True))["status"], "unavailable")

    def test_off_with_the_flag_and_fails_safe(self):
        flags.attach({})
        factory = Rows([("old@example.invalid",)])
        self.assertEqual(security_center.previous_addresses(factory, USER, "new@example.invalid"), [])
        self.assertEqual(factory.executed, [])
        flags.attach(HOLD)
        self.assertEqual(security_center.previous_addresses(Rows(fail=True), USER, "new@example.invalid"), [])

    def test_distinct_previous_addresses_within_14_days_never_the_current_one(self):
        flags.attach(HOLD)
        factory = Rows([("Old@Example.invalid",), ("old@example.invalid",), ("NEW@example.invalid",), ("",)])
        self.assertEqual(security_center.previous_addresses(factory, USER, "new@example.invalid"), ["Old@Example.invalid"])
        sql, params = factory.executed[0]
        self.assertIn("make_interval(days => %s)", sql)
        self.assertEqual(params, (USER, 14))

    def test_the_copy_says_why_and_the_headline_is_localized(self):
        worker = DeliveryWorker(None, base_url="https://app.rafii.example")
        row = {"id": "20000000-0000-4000-8000-000000000001", "userId": USER, "workspaceId": None, "createdAt": 1_800_000_000.0, "key": "k" * 20}
        ctx = {"type": "security.account_change", "locale": "zh-Hant-HK", "workspaceName": None,
               "payload": {"title": "We stopped a risky sign-in from opening your account", "titleKey": "titleSignInBlocked", "href": "/app/account/profile"}}
        labels = email_render.catalogue()["locales"]["zh-Hant-HK"]["templates"]["security_alert"]
        plain = worker.render(row, ctx)
        self.assertIn(labels["titleSignInBlocked"], plain["text"])
        self.assertNotIn(labels["previousAddressNote"], plain["text"])
        copy = worker.render(row, ctx, previous_address=True)
        self.assertIn(labels["previousAddressNote"], copy["text"])
        english = worker.render(row, {**ctx, "locale": "en"}, previous_address=True)
        self.assertIn("This was your Rafii email until it changed in the last 14 days.", english["text"])
        # An event without a key keeps its English title.
        legacy = worker.render(row, {**ctx, "payload": {"title": "Two-step sign-in was turned off", "href": "/app/account/profile"}})
        self.assertIn("Two-step sign-in was turned off", legacy["text"])

    def test_every_locale_has_the_new_security_copy(self):
        keys = {"titleIncidentReported", "titleStepUpFailed", "titleSignInBlocked", "titleHoldReleasedBySupport", "detailPreviousAddress", "previousAddressNote"}
        for locale, data in email_render.catalogue()["locales"].items():
            with self.subTest(locale=locale):
                self.assertLessEqual(keys, set(data["templates"]["security_alert"]))
                self.assertTrue(all(len(data["templates"]["security_alert"][k]) <= 80 for k in ("previousAddressNote", "detailPreviousAddress")))


class StepUpNotices(Flags):
    """Decision 6: notices only for a failed or blocked step-up; a successful self-initiated one stays quiet."""

    def test_detector_maps_the_new_kinds_to_localized_account_change_notices(self):
        rows = [(f"a-{kind}", USER, kind, 1_800_000_000.0, "", True, False, None)
                for kind in ("security.step_up_failed", "security.sign_in_blocked", "security.hold_released_by_support", "security.incident_reported", "mfa.disabled")]
        cursor = base.FakeCursor([(rows, len(rows))])
        cursor.fetchall = lambda: rows
        events = detector.security_events(cursor)
        self.assertIn("security.step_up_failed", cursor.executed[0][0])
        self.assertEqual([(e["event_type"], e["payload"].get("titleKey")) for e in events],
                         [("security.account_change", "titleStepUpFailed"), ("security.account_change", "titleSignInBlocked"),
                          ("security.account_change", "titleHoldReleasedBySupport"), ("security.account_change", "titleIncidentReported"),
                          ("security.account_change", None)])
        self.assertNotIn("security.step_up_verified", cursor.executed[0][0])

    def test_a_successful_step_up_records_no_challenge_and_no_notice(self):
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce"})
        cursor = base.FakeCursor([((False, "new", False, 0, True), 1), (None, 1), (None, 1)])
        service = _service(cursor, policy.Proof("totp", 1_800_000_000.0 - 5, "aal2"))
        self.assertEqual(security_gate.require(service, "t" * 40, "exports").outcome, "allow")
        statements = " ".join(sql for sql, _ in cursor.executed)
        self.assertNotIn("session.step_up_challenged", str(cursor.executed))
        self.assertNotIn("security.", statements)

    def test_a_blocked_risky_sign_in_queues_one_notice(self):
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce"})
        cursor = base.FakeCursor([((False, "new", True, 0, True), 1), (None, 1), (None, 0), (None, 0), (("id",), 1), (None, 1)])
        with self.assertRaises(AlphaError):
            security_gate.require(_service(cursor), "t" * 40, "private_data")
        params = [p for _, p in cursor.executed if p]
        self.assertTrue(any(p[2:4] == ("session.sign_in_blocked", f"session.sign_in_blocked:{SESSION}") for p in params if len(p) > 3))
        self.assertTrue(any("security.sign_in_blocked" in (p or ()) for p in params))

    def test_a_notice_failure_never_changes_the_decision(self):
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "enforce"})

        class Partly(base.FakeCursor):
            def execute(self, sql, params=None):
                if "session.step_up_challenged" in str(params):
                    raise RuntimeError("new row violates check constraint")  # migration 129 not applied yet
                super().execute(sql, params)
        with self.assertRaises(AlphaError) as raised:
            security_gate.require(_service(Partly([((False, "new", True, 0, True), 1), (None, 1)])), "t" * 40, "private_data")
        self.assertEqual((raised.exception.status, raised.exception.code), (403, "security_step_up_required"))


def _service(cursor, proof=policy.Proof()):
    from types import SimpleNamespace

    def verify(token):
        return base.PRINCIPAL
    verify.session_id = lambda token, principal: SESSION
    verify.method_time = lambda token, principal: (proof.method, proof.at)
    verify.aal = lambda token, principal: proof.aal
    return SimpleNamespace(repository=SimpleNamespace(verify_session=verify), connection_factory=lambda: base.FakeDB(cursor), clock=lambda: 1_800_000_000.0, identity=None)


class IncidentBanner(Flags):
    """Decision 5: an in-app banner at the next sign-in until dismissed, beside the email."""

    def test_off_with_the_flag_reads_nothing(self):
        flags.attach({})
        cursor = base.FakeCursor()
        self.assertIsNone(security_center.incident_notice(cursor, USER, SESSION))
        self.assertEqual(cursor.executed, [])

    def test_the_reporting_session_is_excluded_and_an_unreadable_table_is_no_banner(self):
        flags.attach(HOLD)
        cursor = base.FakeCursor([(None, 0), (("30000000-0000-4000-8000-000000000001", None, "user_confirmed", True), 1), (None, 0)])
        notice = security_center.incident_notice(cursor, USER, SESSION)
        self.assertEqual((notice["kind"], notice["accountHold"], notice["state"]), ("incident_reported", True, "user_confirmed"))
        self.assertIn("reported_session_id IS DISTINCT FROM %s", cursor.executed[1][0])
        self.assertIn("notice_dismissed_at IS NULL", cursor.executed[1][0])

        class Broken(base.FakeCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                if "pr_security_incidents" in sql:
                    raise RuntimeError('column "notice_dismissed_at" does not exist')
        broken = Broken()
        self.assertIsNone(security_center.incident_notice(broken, USER, SESSION))
        self.assertIn("ROLLBACK TO SAVEPOINT", broken.executed[-1][0])


class SupportRelease(unittest.TestCase):
    """Decision 11: the founder release records how identity was verified out of band."""

    def test_verification_needs_a_listed_method_and_a_case_reference(self):
        self.assertEqual(security_center.validate_support_verification("video_call_id_match", " case-2041 "), ("video_call_id_match", "case-2041"))
        for method, reference in (("email_code", "case-2041"), (None, "case-2041"), ("video_call_id_match", ""), ("video_call_id_match", "person@example.com"),
                                  ("video_call_id_match", "a note with spaces")):
            with self.subTest(method=method, reference=reference), self.assertRaises(AlphaError) as raised:
                security_center.validate_support_verification(method, reference)
            self.assertEqual(raised.exception.status, 400)
        self.assertFalse(any("email" in method for method in security_center.SUPPORT_METHODS))


class CityGranularity(unittest.TestCase):
    """Decision 8: RAFII_SIGN_IN_DETAILS=city (country, region and city)."""

    def test_city_level_records_all_three_from_vercel_headers_only(self):
        level = account_protection.detail_level({"RAFII_SIGN_IN_DETAILS": "city"})
        self.assertEqual(level, "city")
        environ = {"HTTP_X_VERCEL_IP_COUNTRY": "HK", "HTTP_X_VERCEL_IP_COUNTRY_REGION": "KKC", "HTTP_X_VERCEL_IP_CITY": "Sha%20Tin"}
        found = account_protection.coarse_location(environ, level, {"VERCEL": "1"})
        self.assertEqual(found, {"country": "HK", "region": "KKC", "city": "Sha Tin"})
        self.assertEqual(account_protection.location_text(found), "Sha Tin, KKC, HK")
        self.assertIsNone(account_protection.coarse_location(environ, level, {}))


if __name__ == "__main__":
    unittest.main()
