"""Rafii Account Protection v2, P1 item 4: "This wasn't me" (POST/GET /api/auth/security/incidents).

Authenticated, interactive only, explicit confirmation, fresh signed sign-in (never `iat`), 3 reports per hour; one
transaction records the incident, places the hold, revokes the scoped sessions and writes the ledger; third-party
connections are never disconnected; GET never changes anything; 404 while RAFII_SECURITY_INCIDENT_HOLD is off.
Statement-level tests over a recording cursor; the schema against a real database is in
tests/phase2/postgres_security_incidents.py.
"""
import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication  # noqa: E402
from postriff_phase2.security_incidents import SecurityIncidents  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0
CURRENT = "session-current-0123456789"
OTHER = "session-other-00000000001"
INCIDENT = "44444444-4444-4444-8444-444444444444"
EVENT = "33333333-3333-4333-8333-333333333333"
CREATED = datetime(2027, 1, 15, 8, 0, tzinfo=timezone.utc)
BODY = {"type": "not_me", "confirmed": True, "revokeOtherSessions": True}


class Identity:
    def __init__(self, result=True):
        self.calls, self.result = [], result

    def logout_others(self, token):
        self.calls.append(token)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Case(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)
        flags.attach({"RAFII_SECURITY_INCIDENT_HOLD": "1"})
        self.cursors = []

    def service(self, *scripts, signed_in_at=NOW - 60, identity=None):
        scripts = list(scripts)

        def factory():
            cursor = base.FakeCursor(scripts.pop(0) if scripts else [])
            self.cursors.append(cursor)
            return base.FakeDB(cursor)

        def verify(token):
            return base.PRINCIPAL
        verify.session_id = lambda token, principal: CURRENT
        verify.method_time = lambda token, principal: ("otp", signed_in_at)
        return SimpleNamespace(verify_session=verify, connection_factory=factory, clock=lambda: NOW, identity=identity or Identity())

    def report_script(self, revoked=(OTHER,), source=None):
        script = []
        if source is not None:
            script.append(source)
        script += [((INCIDENT, CREATED), 1), ((3,), 1), ([(s,) for s in revoked], len(revoked))]
        if revoked:
            script.append((None, 1))
        return script + [(None, 1), (None, 1), (None, 1), (None, 1)]

    def statements(self, cursor, needle):
        return [(sql, params) for sql, params in cursor.executed if needle in sql]


class Report(Case):
    def test_one_transaction_records_holds_revokes_and_ledgers(self):
        identity = Identity()
        service = self.service([((1,), 1)], self.report_script(), identity=identity)
        result = SecurityIncidents(service).report("t" * 40, dict(BODY))
        throttle, work = self.cursors
        self.assertIn("pr_auth_throttle", throttle.executed[0][0])
        insert = self.statements(work, "INSERT INTO public.pr_security_incidents")[0]
        self.assertIn("'user_confirmed','not_me'", insert[0])
        self.assertEqual(self.statements(work, "pr_security_set_hold")[0][1], (base.PRINCIPAL, "incident.not_me"))
        revoke_sql, revoke = self.statements(work, "pr_session_revocations")[0]
        self.assertEqual(revoke, (base.PRINCIPAL, CURRENT, True, ""))
        self.assertIn("s.session_id<>%s", revoke_sql)  # never the current session
        mirrored = self.statements(work, "UPDATE public.pr_session_security")[0][1]
        self.assertEqual(mirrored, (base.PRINCIPAL, [OTHER]))
        ledger = [params[3] for sql, params in self.statements(work, "pr_security_login_events")]
        self.assertEqual(ledger, ["incident.reported", "account.hold_placed"])
        self.assertEqual(self.statements(work, "pr_audit_events")[0][1][2], "security.incident_reported")
        self.assertEqual(identity.calls, ["t" * 40])
        self.assertEqual(result, {
            "incidentId": INCIDENT, "state": "user_confirmed", "accountHold": True, "holdEpoch": 3,
            "createdAt": "2027-01-15T08:00:00Z", "resolvedAt": None,
            "sessions": {"rafiiApiRevoked": 1, "providerRefreshState": "confirmed"},
            "agents": {"newSensitiveActions": "held", "alreadyExecutedActions": "not_reversible"},
            "connectedAccounts": "not_disconnected", "nextAction": "verify_recovery"})

    def test_third_party_connections_are_never_touched(self):
        service = self.service([((1,), 1)], self.report_script())
        SecurityIncidents(service).report("t" * 40, dict(BODY))
        everything = " ".join(sql for cursor in self.cursors for sql, _ in cursor.executed)
        for table in ("pr_oauth", "pr_channel", "credential", "pr_productivity"):
            self.assertNotIn(table, everything)
        source = (ROOT / "src" / "postriff_phase2" / "security_incidents.py").read_text()
        self.assertNotIn("disconnect(", source)

    def test_provider_failure_is_reported_not_hidden(self):
        service = self.service([((1,), 1)], self.report_script(), identity=Identity(RuntimeError("down")))
        self.assertEqual(SecurityIncidents(service).report("t" * 40, dict(BODY))["sessions"]["providerRefreshState"], "partial")
        service = self.service([((1,), 1)], self.report_script(revoked=()), identity=Identity())
        self.assertEqual(SecurityIncidents(service).report("t" * 40, {**BODY, "revokeOtherSessions": False})["sessions"], {"rafiiApiRevoked": 0, "providerRefreshState": "unsupported"})

    def test_a_reported_event_scopes_the_revocation_to_its_session(self):
        service = self.service([((1,), 1)], self.report_script(source=((OTHER,), 1)))
        SecurityIncidents(service).report("t" * 40, {**BODY, "revokeOtherSessions": False, "sourceEventId": EVENT})
        work = self.cursors[1]
        self.assertEqual(work.executed[0][1], (base.PRINCIPAL, EVENT))
        self.assertEqual(self.statements(work, "pr_session_revocations")[0][1], (base.PRINCIPAL, CURRENT, False, OTHER))

    def test_another_persons_or_unknown_event_is_not_found(self):
        service = self.service([((1,), 1)], [(None, 1)])
        with self.assertRaises(AlphaError) as raised:
            SecurityIncidents(service).report("t" * 40, {**BODY, "sourceEventId": EVENT})
        self.assertEqual((raised.exception.status, raised.exception.code), (404, "security_resource_not_found"))
        self.assertEqual(self.statements(self.cursors[1], "pr_security_set_hold"), [])

    def test_the_current_session_cannot_be_the_target(self):
        service = self.service([((1,), 1)], [((CURRENT,), 1)])
        with self.assertRaises(AlphaError) as raised:
            SecurityIncidents(service).report("t" * 40, {**BODY, "sourceEventId": EVENT})
        self.assertEqual(raised.exception.code, "current_device_revocation_requires_logout")


class AbuseControls(Case):
    def refused(self, body=None, token="t" * 40, **kwargs):
        self.cursors = []
        service = self.service([((1,), 1)], **kwargs)
        with self.assertRaises(AlphaError) as raised:
            SecurityIncidents(service).report(token, dict(BODY) if body is None else body)
        writes = [sql for cursor in self.cursors[1:] for sql, _ in cursor.executed]
        self.assertEqual(writes, [])
        return raised.exception

    def test_explicit_confirmation_only(self):
        for body in ({**BODY, "confirmed": False}, {**BODY, "confirmed": "true"}, {**BODY, "type": "lost_phone"},
                     {"type": "not_me", "confirmed": True}, {**BODY, "extra": 1}, {**BODY, "revokeOtherSessions": "yes"},
                     {**BODY, "sourceEventId": "../x"}):
            self.assertEqual(self.refused(body).status, 400, body)

    def test_fresh_signed_sign_in_required(self):
        for when in (NOW - 601, 0, NOW + 120):
            self.assertEqual(self.refused(signed_in_at=when).code, "step_up_required", when)

    def test_api_tokens_cannot_report(self):
        service = self.service()
        with self.assertRaises(AlphaError) as raised:
            SecurityIncidents(service).report("prt_" + "a" * 43, dict(BODY))
        self.assertEqual((raised.exception.status, self.cursors), (403, []))

    def test_rate_limited_before_anything_else(self):
        service = self.service([((4,), 1)])
        with self.assertRaises(AlphaError) as raised:
            SecurityIncidents(service).report("t" * 40, dict(BODY))
        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(len(self.cursors), 1)

    def test_idempotency_key_replays_or_conflicts(self):
        from postriff_phase2.security_incidents import digest, validate
        print_ = digest(base.PRINCIPAL, validate(dict(BODY)))
        replay = ((INCIDENT, "user_confirmed", 3, CREATED, None, True, print_, 2), 1)
        service = self.service([((1,), 1)], [replay])
        result = SecurityIncidents(service).report("t" * 40, dict(BODY), "key-0123456789abcdef")
        self.assertEqual((result["replayed"], result["sessions"]["rafiiApiRevoked"]), (True, 2))
        self.assertEqual(self.statements(self.cursors[1], "pr_security_set_hold"), [])
        service = self.service([((1,), 1)], [((INCIDENT, "user_confirmed", 3, CREATED, None, True, "0" * 64, 2), 1)])
        with self.assertRaises(AlphaError) as raised:
            SecurityIncidents(service).report("t" * 40, dict(BODY), "key-0123456789abcdef")
        self.assertEqual((raised.exception.status, raised.exception.code), (409, "idempotency_key_conflict"))

    def test_a_concurrent_report_with_the_same_key_replays_the_winner(self):
        from postriff_phase2.security_incidents import digest, validate
        print_ = digest(base.PRINCIPAL, validate(dict(BODY)))

        class UniqueViolation(Exception):
            pass

        class Racing(base.FakeCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                if sql.startswith("INSERT INTO public.pr_security_incidents"):
                    raise UniqueViolation()
        winner = ((INCIDENT, "user_confirmed", 3, CREATED, None, True, print_, 1), 1)
        racing = Racing([(None, 1), (None, 1), (None, 1), (None, 1), winner])
        service = self.service([((1,), 1)])
        service.connection_factory = (lambda first=iter([base.FakeDB(base.FakeCursor([((1,), 1)])), base.FakeDB(racing)]): next(first))
        result = SecurityIncidents(service).report("t" * 40, dict(BODY), "key-0123456789abcdef")
        self.assertEqual((result["incidentId"], result["replayed"]), (INCIDENT, True))
        self.assertIn("ROLLBACK TO SAVEPOINT rapv2_incident", [sql for sql, _ in racing.executed])
        self.assertNotIn("pr_security_set_hold", " ".join(sql for sql, _ in racing.executed))

    def test_off_is_not_found_and_runs_nothing(self):
        flags.attach({})
        service = self.service()
        for call in (lambda s: s.report("t" * 40, dict(BODY)), lambda s: s.list("t" * 40)):
            with self.assertRaises(AlphaError) as raised:
                call(SecurityIncidents(service))
            self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.cursors, [])


class List(Case):
    def test_get_reads_only_its_own_rows(self):
        service = self.service([([(INCIDENT, "user_confirmed", 3, CREATED, None, True)], 1)])
        self.assertEqual(SecurityIncidents(service).list("t" * 40)["incidents"][0]["accountHold"], True)
        [(sql, params)] = self.cursors[0].executed
        self.assertTrue(sql.startswith("SELECT"))
        self.assertIn("WHERE i.user_id=%s", sql)
        self.assertEqual(params, (base.PRINCIPAL,))


class Wsgi(Case):
    def test_routes_and_status_codes(self):
        class Fake(base.FakeAccountService):
            pass
        app = HostedApplication(Fake(), None, {"provider": "supabase"}, "c" * 24)
        # The fake service has no incident wiring: with the flag off both routes are simply unavailable.
        flags.attach({})
        self.assertEqual(base.invoke(app, "GET", "/api/auth/security/incidents", headers=base.AUTH)[0], 404)
        self.assertEqual(base.invoke(app, "POST", "/api/auth/security/incidents", BODY, base.AUTH)[0], 404)

    def test_the_web_app_confirms_explicitly_and_hides_when_off(self):
        card = (ROOT / "web" / "src" / "features" / "account" / "security-card.tsx").read_text()
        client = (ROOT / "web" / "src" / "lib" / "api" / "client.ts").read_text()
        self.assertIn("if (!incidents.isSuccess) return null;", card)
        self.assertIn("<NotMe />", card)
        self.assertIn("Your connected social accounts stay connected", card)
        self.assertIn("{ type: 'not_me', confirmed: true, revokeOtherSessions, sourceEventId }", client)


class Migration(unittest.TestCase):
    SQL = re.sub(r"--[^\n]*", "", (ROOT / "migrations" / "postriff" / "122_rapv2_security_incidents.sql").read_text()).lower()

    def test_composite_source_fk_and_server_only(self):
        sql = self.SQL
        self.assertIn("foreign key (user_id, source_event_id) references public.pr_security_login_events (user_id, id) on delete restrict", sql)
        self.assertIn("alter table public.pr_security_incidents force row level security", sql)
        self.assertIn("revoke all on public.pr_security_incidents from public, anon, authenticated", sql)
        self.assertNotIn("to authenticated", sql.replace("from public, anon, authenticated", ""))
        self.assertNotIn("on delete cascade", sql)
        self.assertIn("unique (user_id, idempotency_key)", sql)
        self.assertIn("delete from public.pr_security_incidents where user_id = p_user", sql)

    def test_the_harness_applies_it(self):
        self.assertIn("122_rapv2_security_incidents.sql", (ROOT / "tests" / "phase2" / "rls.sql").read_text())


if __name__ == "__main__":
    unittest.main()
