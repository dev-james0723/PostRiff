"""Account security surface behind the profile page: second-factor enforcement, sessions,
cross-workspace channels and the workspace summary.

Route wiring runs against a fake service; service methods run against a recording cursor so the
SQL each one issues is asserted without PostgreSQL. The verifier test proves the API refuses an
AAL1 session once a user has turned on two-factor authentication.
"""
import base64
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService, workspace_summary
from postriff_phase2.hosted_app import HostedApplication, supabase_verifier
from postriff_phase2.hosted_identity import SupabaseIdentityAdmin, verified_aal

PRINCIPAL = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
WORKSPACE = "00000000-0000-0000-0000-000000000010"
AUTH = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"}


def jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "header." + encoded + ".signature"


def invoke(app, method, path, body=None, headers=None):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "https", "HTTP_HOST": "postriff.example", "HTTP_ORIGIN": "https://postriff.example"}
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}
    response = b"".join(app(environ, lambda status, values: captured.update(status=status, headers=dict(values))))
    return int(captured["status"].split()[0]), json.loads(response)


class FakeAccountService:
    def __init__(self):
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name, *args))

    def me(self, token, client_label=""):
        self._record("me", client_label)
        return {"userId": PRINCIPAL, "displayName": "", "mfa": {"available": True, "enforced": False, "enforcedAt": None, "aal": "aal1"}}

    def update_profile(self, token, changes):
        self._record("update_profile", changes)
        return {"displayName": changes.get("displayName", ""), "preferences": {"timeZone": changes.get("timeZone", ""), "locale": "", "alertNewDevice": False}}

    def my_channels(self, token):
        self._record("my_channels")
        return {"channels": [{"workspaceId": WORKSPACE, "platform": "Threads", "canManage": False}]}

    def enable_mfa(self, token):
        self._record("enable_mfa")
        return {"enforced": True, "enforcedAt": 1.0}

    def disable_mfa(self, token):
        self._record("disable_mfa")
        return {"enforced": False, "enforcedAt": None}

    def revoke_other_sessions(self, token):
        self._record("revoke_other_sessions")
        return {"revoked": 2, "refreshRevoked": True, "current": "s" * 20}

    def leave_workspace(self, workspace_id, token):
        self._record("leave_workspace", workspace_id)
        return {"workspaceId": workspace_id, "status": "left"}

    def transfer_ownership(self, workspace_id, token, new_owner_id):
        self._record("transfer_ownership", workspace_id, new_owner_id)
        return {"ownerId": new_owner_id, "previousOwnerId": PRINCIPAL}

    def security_events(self, token):
        self._record("security_events")
        return {"events": [{"id": "e1", "kind": "mfa.enabled", "at": 1.0}]}

    def my_invitations(self, token):
        self._record("my_invitations")
        return {"available": True, "invitations": [{"invitationId": "inv-1", "workspaceName": "Studio", "role": "editor"}]}

    def accept_my_invitation(self, token, invitation_id):
        self._record("accept_my_invitation", invitation_id)
        return {"workspaceId": WORKSPACE, "role": "editor"}

    def decline_my_invitation(self, token, invitation_id):
        self._record("decline_my_invitation", invitation_id)
        return {"invitationId": invitation_id, "state": "declined"}

    def get(self, workspace_id, token):
        return {"workspace": workspace_id}


class FakeCursor:
    """Records every statement; answers fetchone/rowcount from a queue, one entry per execute."""
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.executed = []
        self.rowcount = 0
        self._row = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._row, self.rowcount = self.responses.pop(0) if self.responses else (None, 0)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._row or []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeDB:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeIdentity:
    def __init__(self, factors):
        self.factors = factors
        self.logged_out_others = []

    def verified_factors(self, principal):
        return list(self.factors)

    def logout_others(self, access_token):
        self.logged_out_others.append(access_token)
        return True


def verifier(aal="aal1", auth_time=1_800_000_000.0):
    def verify(token):
        return PRINCIPAL
    verify.session_id = lambda token, principal: "session-current-0123456789"
    verify.auth_time = lambda token, principal: auth_time
    verify.aal = lambda token, principal: aal
    return verify


def service(cursor, verify, identity=None, email_lookup=None):
    return HostedWorkspaceService(lambda: FakeDB(cursor), verify, clock=lambda: 1_800_000_000.0, identity=identity, email_lookup=email_lookup)


class AccountRoutes(unittest.TestCase):
    def test_account_routes_are_wired_and_mutations_need_the_guard(self):
        fake = FakeAccountService()
        app = HostedApplication(fake, None, {"provider": "supabase"}, "c" * 24)
        self.assertEqual(invoke(app, "GET", "/api/me", headers={**AUTH, "User-Agent": "Safari/605.1 (iPhone)"})[0], 200)
        self.assertEqual(fake.calls[0], ("me", "Safari"))  # the device label reaches the service for new-device alerts
        self.assertEqual(invoke(app, "GET", "/api/me/channels", headers=AUTH)[1]["channels"][0]["platform"], "Threads")
        self.assertEqual(invoke(app, "PATCH", "/api/me", {"displayName": "James", "timeZone": "Asia/Hong_Kong"}, AUTH)[1]["preferences"]["timeZone"], "Asia/Hong_Kong")
        self.assertEqual(invoke(app, "POST", "/api/auth/mfa", {}, AUTH)[1]["enforced"], True)
        self.assertEqual(invoke(app, "DELETE", "/api/auth/mfa", {}, AUTH)[1]["enforced"], False)
        self.assertEqual(invoke(app, "POST", "/api/auth/sessions/revoke-others", {}, AUTH)[1]["revoked"], 2)
        self.assertEqual(invoke(app, "POST", f"/api/workspaces/{WORKSPACE}/leave", {}, AUTH)[1]["status"], "left")
        self.assertEqual(invoke(app, "POST", f"/api/workspaces/{WORKSPACE}/transfer-ownership", {"newOwnerId": OTHER}, AUTH)[1]["ownerId"], OTHER)
        self.assertEqual(invoke(app, "GET", "/api/me/security-events", headers=AUTH)[1]["events"][0]["kind"], "mfa.enabled")
        self.assertEqual(invoke(app, "GET", "/api/me/invitations", headers=AUTH)[1]["invitations"][0]["workspaceName"], "Studio")
        self.assertEqual(invoke(app, "POST", "/api/me/invitations/inv-1/accept", {}, AUTH)[1]["role"], "editor")
        self.assertEqual(invoke(app, "POST", "/api/me/invitations/inv-1/decline", {}, AUTH)[1]["state"], "declined")
        self.assertEqual(invoke(app, "POST", "/api/me/invitations/inv-1/forward", {}, AUTH)[0], 404)
        self.assertEqual([call[0] for call in fake.calls], ["me", "my_channels", "update_profile", "enable_mfa", "disable_mfa", "revoke_other_sessions", "leave_workspace", "transfer_ownership", "security_events", "my_invitations", "accept_my_invitation", "decline_my_invitation"])
        self.assertEqual(fake.calls[2], ("update_profile", {"displayName": "James", "timeZone": "Asia/Hong_Kong"}))
        self.assertEqual(fake.calls[7], ("transfer_ownership", WORKSPACE, OTHER))
        self.assertEqual(fake.calls[-2:], [("accept_my_invitation", "inv-1"), ("decline_my_invitation", "inv-1")])
        # Every mutation is refused without the application guard, exactly like the existing routes.
        bare = {"Authorization": AUTH["Authorization"]}
        for method, path in (("POST", "/api/auth/mfa"), ("DELETE", "/api/auth/mfa"), ("POST", "/api/auth/sessions/revoke-others"), ("PATCH", "/api/me"), ("POST", f"/api/workspaces/{WORKSPACE}/leave"), ("POST", f"/api/workspaces/{WORKSPACE}/transfer-ownership"), ("POST", "/api/me/invitations/inv-1/accept")):
            with self.subTest(path=path):
                self.assertEqual(invoke(app, method, path, {}, bare)[0], 403)
        self.assertEqual(invoke(app, "GET", "/api/me")[0], 401)


class AssuranceLevel(unittest.TestCase):
    def test_verified_aal_is_aal2_only_when_stamped(self):
        self.assertEqual(verified_aal(jwt({"sub": PRINCIPAL, "aal": "aal2"}), PRINCIPAL), "aal2")
        self.assertEqual(verified_aal(jwt({"sub": PRINCIPAL, "aal": "aal1"}), PRINCIPAL), "aal1")
        self.assertEqual(verified_aal(jwt({"sub": PRINCIPAL}), PRINCIPAL), "aal1")
        self.assertEqual(verified_aal(jwt({"sub": PRINCIPAL, "aal": "aal3"}), PRINCIPAL), "aal1")
        with self.assertRaises(AlphaError):
            verified_aal(jwt({"sub": OTHER, "aal": "aal2"}), PRINCIPAL)

    def test_verifier_refuses_aal1_sessions_once_two_factor_is_enforced(self):
        flags = {"deleted": False, "revoked": False, "enforced": True}
        cursor = FakeCursor()

        def factory():
            cursor.responses = [((flags["deleted"], flags["revoked"], flags["enforced"]), 1)]
            return FakeDB(cursor)

        def get_user(url, token):
            return {"status": 200, "body": {"id": PRINCIPAL, "email_confirmed_at": "2026-01-01T00:00:00Z"}}

        verify = supabase_verifier("https://project.supabase.co", "p" * 24, factory, get_user=get_user)
        aal1 = jwt({"sub": PRINCIPAL, "session_id": "session-1234567890", "aal": "aal1"})
        aal2 = jwt({"sub": PRINCIPAL, "session_id": "session-1234567890", "aal": "aal2"})
        with self.assertRaises(AlphaError) as refused:
            verify(aal1)
        self.assertEqual(refused.exception.status, 403)
        self.assertEqual(verify(aal2), PRINCIPAL)
        self.assertEqual(verify.aal(aal2, PRINCIPAL), "aal2")
        flags["enforced"] = False
        self.assertEqual(verify(aal1), PRINCIPAL)
        flags["revoked"] = True
        with self.assertRaises(AlphaError) as revoked:
            verify(aal2)
        self.assertEqual(revoked.exception.status, 401)
        self.assertIn("pr_mfa_enforcement", cursor.executed[-1][0])


class SecondFactorService(unittest.TestCase):
    def test_enable_needs_aal2_and_a_verified_factor_then_records_and_audits(self):
        with self.assertRaises(AlphaError) as aal1:
            service(FakeCursor(), verifier("aal1"), FakeIdentity([{"id": "f1"}])).enable_mfa("t")
        self.assertEqual(aal1.exception.status, 403)
        with self.assertRaises(AlphaError) as none:
            service(FakeCursor(), verifier("aal2"), FakeIdentity([])).enable_mfa("t")
        self.assertEqual(none.exception.status, 409)
        cursor = FakeCursor([(None, 1), (None, 0), ((1_800_000_000.0,), 1)])
        result = service(cursor, verifier("aal2"), FakeIdentity([{"id": "f1"}])).enable_mfa("t")
        self.assertEqual(result, {"enforced": True, "enforcedAt": 1_800_000_000.0})
        statements = [sql for sql, _ in cursor.executed]
        self.assertIn("INSERT INTO public.pr_mfa_enforcement", statements[0])
        self.assertIn("pr_audit_events", statements[1])
        self.assertEqual(cursor.executed[1][1][2], "mfa.enabled")

    def test_enable_works_without_an_identity_admin(self):
        cursor = FakeCursor([(None, 0), ((5.0,), 1)])
        self.assertEqual(service(cursor, verifier("aal2")).enable_mfa("t")["enforcedAt"], 5.0)
        # Already enforced: nothing inserted, nothing audited.
        self.assertEqual(len(cursor.executed), 2)

    def test_disable_needs_a_fresh_aal2_session(self):
        with self.assertRaises(AlphaError) as aal1:
            service(FakeCursor(), verifier("aal1")).disable_mfa("t")
        self.assertEqual(aal1.exception.status, 403)
        with self.assertRaises(AlphaError) as stale:
            service(FakeCursor(), verifier("aal2", auth_time=1_800_000_000.0 - 3600)).disable_mfa("t")
        self.assertIn("Sign in again", str(stale.exception))
        cursor = FakeCursor([(None, 1), (None, 1)])
        self.assertEqual(service(cursor, verifier("aal2")).disable_mfa("t"), {"enforced": False, "enforcedAt": None})
        self.assertIn("DELETE FROM public.pr_mfa_enforcement", cursor.executed[0][0])
        self.assertEqual(cursor.executed[1][1][2], "mfa.disabled")

    def test_dev_identities_report_two_factor_unavailable(self):
        verify = verifier()
        del verify.aal
        cursor = FakeCursor([(None, 1), (("Dev", None, "", "", False), 1)])
        me = service(cursor, verify).me("t")
        self.assertEqual(me["mfa"], {"available": False, "enforced": False, "enforcedAt": None, "aal": None})
        self.assertEqual(me["displayName"], "Dev")
        self.assertEqual(me["preferences"], {"timeZone": "", "locale": "", "alertNewDevice": False})
        with self.assertRaises(AlphaError) as unavailable:
            service(FakeCursor(), verify).enable_mfa("t")
        self.assertEqual(unavailable.exception.status, 503)

    def test_me_reports_enforcement_and_current_session(self):
        cursor = FakeCursor([(None, 1), (("James", 1_799_000_000.0, "Asia/Hong_Kong", "zh-Hant", True), 1)])
        me = service(cursor, verifier("aal2")).me("t")
        self.assertEqual((me["userId"], me["sessionId"], me["mfa"]["enforced"], me["mfa"]["enforcedAt"], me["mfa"]["aal"]), (PRINCIPAL, "session-current-0123456789", True, 1_799_000_000.0, "aal2"))
        self.assertEqual(me["preferences"], {"timeZone": "Asia/Hong_Kong", "locale": "zh-Hant", "alertNewDevice": True})


class SessionsAndProfile(unittest.TestCase):
    def test_revoke_others_spares_the_current_session_and_signs_out_remotely(self):
        identity = FakeIdentity([])
        cursor = FakeCursor([(None, 2), (None, 1)])
        result = service(cursor, verifier(), identity).revoke_other_sessions("t")
        self.assertEqual(result, {"revoked": 2, "refreshRevoked": True, "current": "session-current-0123456789"})
        sql, params = cursor.executed[0]
        self.assertIn("session_id<>%s", sql)
        self.assertEqual(params, (PRINCIPAL, "session-current-0123456789"))
        self.assertEqual((cursor.executed[1][1][2], cursor.executed[1][1][4]), ("session.revoked_others", json.dumps({"count": 2})))
        self.assertEqual(identity.logged_out_others, ["t"])
        with self.assertRaises(AlphaError):
            service(FakeCursor(), verifier(auth_time=0)).revoke_other_sessions("t")

    def test_display_name_is_bounded_and_normalised(self):
        cursor = FakeCursor([(("James Au", "", "", False), 1)])
        saved = service(cursor, verifier()).update_profile("t", {"displayName": "  James   Au "})
        self.assertEqual(saved, {"displayName": "James Au", "preferences": {"timeZone": "", "locale": "", "alertNewDevice": False}})
        sql, params = cursor.executed[0]
        self.assertEqual(params, (PRINCIPAL, "James Au"))
        self.assertIn("display_name=excluded.display_name", sql)
        for bad in (None, 7, "x" * 81, "line\nbreak"):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                service(FakeCursor(), verifier()).update_profile("t", {"displayName": bad})
        with self.assertRaises(AlphaError):
            service(FakeCursor(), verifier()).update_profile("t", {})
        with self.assertRaises(AlphaError):
            service(FakeCursor(), verifier()).update_profile("t", {"unknown": 1})

    def test_preferences_are_validated_and_only_present_keys_change(self):
        cursor = FakeCursor([(("", "Asia/Hong_Kong", "zh-Hant", True), 1)])
        saved = service(cursor, verifier()).update_profile("t", {"timeZone": "Asia/Hong_Kong", "locale": "zh-Hant", "alertNewDevice": True})
        self.assertEqual(saved["preferences"], {"timeZone": "Asia/Hong_Kong", "locale": "zh-Hant", "alertNewDevice": True})
        sql, params = cursor.executed[0]
        self.assertIn("pr_profiles(user_id,time_zone,locale,alert_new_device)", sql)
        self.assertNotIn("display_name=excluded", sql)
        self.assertEqual(params, (PRINCIPAL, "Asia/Hong_Kong", "zh-Hant", True))
        # Clearing is allowed; unknown zones, malformed tags and non-boolean flags are not.
        service(FakeCursor([(("", "", "", False), 1)]), verifier()).update_profile("t", {"timeZone": "", "locale": ""})
        for bad in ({"timeZone": "Mars/Phobos"}, {"timeZone": "Asia/Hong Kong"}, {"timeZone": 5}, {"locale": "english!"}, {"locale": "x" * 17}, {"alertNewDevice": "yes"}):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                service(FakeCursor(), verifier()).update_profile("t", bad)

    def test_leave_workspace_refuses_the_owner(self):
        owner_row = (3, "{}", "owner", True, True, True, True)
        with self.assertRaises(AlphaError) as refused:
            service(FakeCursor([(owner_row, 1)]), verifier()).leave_workspace(WORKSPACE, "t")
        self.assertEqual(refused.exception.status, 409)
        editor_row = (3, "{}", "editor", False, False, False, False)
        cursor = FakeCursor([(editor_row, 1), (None, 1), (None, 1)])
        self.assertEqual(service(cursor, verifier()).leave_workspace(WORKSPACE, "t"), {"workspaceId": WORKSPACE, "status": "left"})
        self.assertIn("SET status='revoked'", cursor.executed[1][0])
        self.assertEqual(cursor.executed[2][1][:3], (WORKSPACE, PRINCIPAL, "member.left"))


class SecurityActivity(unittest.TestCase):
    def test_feed_merges_audit_events_about_me_with_first_sign_ins_newest_first(self):
        audit_rows = [
            ("e3", "member.updated", PRINCIPAL, 300.0, {"role": "admin"}, WORKSPACE, "Studio"),
            ("e2", "mfa.enabled", "", 200.0, {}, None, ""),
            ("e1", "workspace.created", "", 100.0, {"plan": "studio"}, WORKSPACE, "Studio"),
        ]
        session_rows = [("session-phone-0123456789", "Safari", 250.0), ("session-laptop-012345678", "Chrome", 50.0)]
        cursor = FakeCursor([(audit_rows, 3), (session_rows, 2)])
        feed = service(cursor, verifier()).security_events("t", limit=4)["events"]
        self.assertEqual([event["kind"] for event in feed], ["member.updated", "session.started", "mfa.enabled", "workspace.created"])
        self.assertEqual(feed[1], {"id": "session:session-phone-0123456789", "kind": "session.started", "subject": "session-phone-0123456789", "at": 250.0, "meta": {"client": "Safari"}, "workspaceId": None, "workspaceName": ""})
        self.assertEqual((feed[0]["workspaceName"], feed[0]["meta"]["role"]), ("Studio", "admin"))
        sql, params = cursor.executed[0]
        # What I did (actor) and what was done to my memberships (subject) come from one query, bounded by the limit.
        self.assertIn("e.actor=%s AND e.kind=ANY(%s)", sql)
        self.assertIn("e.subject=%s AND e.kind=ANY(%s)", sql)
        self.assertEqual((params[0], params[2], params[4]), (PRINCIPAL, PRINCIPAL, 4))
        self.assertIn("member.updated", params[3])
        self.assertNotIn("channel.connected", params[1])
        self.assertEqual(cursor.executed[1][1], (PRINCIPAL, 4))

    def test_limit_is_bounded(self):
        cursor = FakeCursor([([], 0), ([], 0)])
        service(cursor, verifier()).security_events("t", limit=10_000)
        self.assertEqual(cursor.executed[0][1][4], 100)


class MyInvitations(unittest.TestCase):
    EMAIL = "me@example.invalid"

    def test_unavailable_without_a_confirmed_email(self):
        cursor = FakeCursor()
        self.assertEqual(service(cursor, verifier()).my_invitations("t"), {"invitations": [], "available": False})
        self.assertEqual(cursor.executed, [])
        with self.assertRaises(AlphaError) as refused:
            service(FakeCursor(), verifier()).accept_my_invitation("t", "inv-1")
        self.assertEqual(refused.exception.status, 409)

    def test_lists_pending_invitations_for_my_email_only(self):
        row = ("inv-1", WORKSPACE, "Studio", "editor", {"can_publish": True}, OTHER, "Ada", 100.0, 700.0)
        cursor = FakeCursor([([row], 1)])
        listed = service(cursor, verifier(), email_lookup=lambda principal: self.EMAIL).my_invitations("t")
        self.assertTrue(listed["available"])
        self.assertEqual(listed["invitations"], [{"invitationId": "inv-1", "workspaceId": WORKSPACE, "workspaceName": "Studio", "role": "editor", "permissions": {"can_publish": True}, "invitedBy": {"userId": OTHER, "displayName": "Ada"}, "createdAt": 100.0, "expiresAt": 700.0}])
        sql, params = cursor.executed[0]
        self.assertEqual(params, (self.EMAIL, PRINCIPAL))
        # Pending only, and never for a workspace the person already belongs to.
        for clause in ("i.email=%s", "i.accepted_at IS NULL", "i.revoked_at IS NULL", "i.expires_at>now()", "NOT EXISTS"):
            self.assertIn(clause, sql)

    def test_accept_matches_the_email_and_joins_like_the_link_does(self):
        invitation = ("inv-1", WORKSPACE, "editor", {"can_publish": True})
        cursor = FakeCursor([((1,), 1), (invitation, 1), (None, 1), (None, 0), (None, 1), (None, 1), (None, 1), (None, 1)])
        joined = service(cursor, verifier(), email_lookup=lambda principal: self.EMAIL).accept_my_invitation("t", "inv-1")
        self.assertEqual(joined, {"workspaceId": WORKSPACE, "role": "editor", "can_publish": True, "can_reply": False, "can_moderate": False, "can_manage_connections": False})
        statements = [sql for sql, _ in cursor.executed]
        self.assertIn("pr_auth_throttle", statements[0])
        self.assertIn("i.email=%s", statements[1])
        self.assertEqual(cursor.executed[1][1], ("inv-1", self.EMAIL))
        self.assertIn("INSERT INTO public.pr_memberships", statements[4])
        self.assertIn("SET accepted_by=%s", statements[5])
        self.assertEqual(cursor.executed[6][1][2], "invitation.accepted")

    def test_accept_refuses_someone_elses_or_settled_invitation(self):
        cursor = FakeCursor([((1,), 1), (None, 0)])
        with self.assertRaises(AlphaError) as refused:
            service(cursor, verifier(), email_lookup=lambda principal: self.EMAIL).accept_my_invitation("t", "inv-9")
        self.assertEqual(refused.exception.status, 404)

    def test_decline_revokes_and_audits_against_the_workspace(self):
        cursor = FakeCursor([((WORKSPACE,), 1), (None, 1)])
        result = service(cursor, verifier(), email_lookup=lambda principal: self.EMAIL).decline_my_invitation("t", "inv-1")
        self.assertEqual(result, {"invitationId": "inv-1", "state": "declined"})
        self.assertIn("SET revoked_at=now()", cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1], ("inv-1", self.EMAIL))
        self.assertEqual(cursor.executed[1][1][:3], (WORKSPACE, PRINCIPAL, "invitation.declined"))
        with self.assertRaises(AlphaError):
            service(FakeCursor([(None, 0)]), verifier(), email_lookup=lambda principal: self.EMAIL).decline_my_invitation("t", "inv-1")


class FakeMailer:
    def __init__(self):
        self.calls = []

    def new_device(self, to, device_label, at, profile_url):
        self.calls.append((to, device_label, profile_url))
        return {"sent": True, "kind": "new_device"}


class NewDeviceAlerts(unittest.TestCase):
    def test_mailer_renders_the_alert_with_device_and_profile_link(self):
        from postriff_phase2.email import Mailer, NullTransport
        transport = NullTransport()
        outcome = Mailer(transport, "PostRiff <no-reply@postriff.invalid>", "https://app.example").new_device("me@example.invalid", "Safari on iPhone", 1_800_000_000.0, "https://app.example/app/account/profile")
        self.assertTrue(outcome["sent"])
        mail = transport.sent[0]
        self.assertEqual(mail["to"], "me@example.invalid")
        self.assertIn("sign-in", mail["subject"].lower())
        self.assertIn("Safari on iPhone", mail["text"])
        self.assertIn("https://app.example/app/account/profile", mail["text"])
        self.assertIn("two-factor", mail["text"])

    def alerting(self, cursor):
        svc = service(cursor, verifier(), email_lookup=lambda principal: "me@example.invalid")
        svc.public_base_url = "https://app.example"
        svc.mailer = FakeMailer()
        return svc

    def test_first_sighting_emails_only_when_the_person_opted_in(self):
        # New session, alert on: one email and one audit line naming the session.
        cursor = FakeCursor([((True,), 1), (("James", None, "", "", True), 1), ((True,), 1), (None, 1)])
        svc = self.alerting(cursor)
        svc.me("t", client_label="Safari on iPhone")
        self.assertEqual(svc.mailer.calls, [("me@example.invalid", "Safari on iPhone", "https://app.example/app/account/profile")])
        self.assertIn("RETURNING (xmax = 0)", cursor.executed[0][0])
        self.assertEqual(cursor.executed[3][1][2:4], ("session.alerted", "session-current-0123456789"))
        # New session, alert off: the preference is read and nothing else happens.
        cursor = FakeCursor([((True,), 1), (("James", None, "", "", False), 1), ((False,), 1)])
        svc = self.alerting(cursor)
        svc.me("t", client_label="Safari on iPhone")
        self.assertEqual((svc.mailer.calls, len(cursor.executed)), ([], 3))
        # A session we have seen before never gets as far as the preference.
        cursor = FakeCursor([((False,), 1), (("James", None, "", "", True), 1)])
        svc = self.alerting(cursor)
        svc.me("t", client_label="Safari on iPhone")
        self.assertEqual((svc.mailer.calls, len(cursor.executed)), ([], 2))

    def test_sessions_route_takes_the_same_path(self):
        cursor = FakeCursor([((True,), 1), ([], 0), ((True,), 1), (None, 1)])
        svc = self.alerting(cursor)
        svc.sessions("t", client_label="Chrome")
        self.assertEqual(svc.mailer.calls, [("me@example.invalid", "Chrome", "https://app.example/app/account/profile")])

    def test_no_public_base_url_means_no_alert(self):
        cursor = FakeCursor([((True,), 1), (("James", None, "", "", True), 1)])
        svc = service(cursor, verifier(), email_lookup=lambda principal: "me@example.invalid")
        svc.mailer = FakeMailer()
        svc.me("t", client_label="Chrome")
        self.assertEqual((svc.mailer.calls, len(cursor.executed)), ([], 2))


class ChannelsAndWorkspaces(unittest.TestCase):
    def test_my_channels_spans_workspaces_and_marks_who_may_manage(self):
        now = 1_800_000_000.0
        live = {"id": "c1", "platform": "Threads", "account": "@dev", "accountType": "profile", "configured": True, "identityVerified": True, "capabilityVerified": True, "scopes": ["threads_basic"], "expiresAt": now + 3600, "verifiedAt": now - 10, "evidenceSource": "live_provider", "providerAccountId": "1"}
        expired = {**live, "id": "c2", "platform": "LinkedIn", "account": "Dev", "expiresAt": now - 1}
        placeholder = {"id": "c3", "platform": "X", "account": "", "configured": False}
        rows = [
            (WORKSPACE, "admin", False, False, False, False, "Studio", [live, placeholder]),
            (OTHER, "viewer", False, False, False, False, "", json.dumps([expired])),
        ]
        cursor = FakeCursor([(rows, 2), ([("c1", OTHER, "Ada", now - 10)], 1)])
        result = service(cursor, verifier()).my_channels("t")["channels"]
        self.assertEqual([(c["workspaceName"], c["id"], c["connectionState"], c["canManage"]) for c in result], [("Studio", "c1", "publish_verified", True), ("My workspace", "c2", "token_expired", False)])
        self.assertNotIn("scopes", result[0])
        # The connector comes from the audit trail, so it also covers channels connected before this field existed.
        self.assertEqual(result[0]["connectedBy"], {"userId": OTHER, "displayName": "Ada", "at": now - 10})
        self.assertIsNone(result[1]["connectedBy"])
        self.assertEqual(cursor.executed[1][1], ([WORKSPACE, OTHER],))
        self.assertIn("channel.connected", cursor.executed[1][0])

    def test_workspace_summary_reads_plan_owner_and_role_counts(self):
        summary = workspace_summary("Studio", None, "assist", PRINCIPAL, "James", {"owner": 1, "admin": 2, "editor": 3})
        self.assertEqual(summary["plan"], "trial")
        self.assertEqual(summary["trialPlan"], "assist")
        self.assertEqual(summary["owner"], {"userId": PRINCIPAL, "displayName": "James"})
        self.assertEqual(summary["memberCounts"], {"owner": 1, "admin": 2, "editor": 3, "approver": 0, "viewer": 0})
        paid = workspace_summary("", "studio", "studio", None, None, None)
        self.assertEqual((paid["name"], paid["plan"], paid["owner"], paid["memberCounts"]["owner"]), ("My workspace", "studio", None, 0))

    def test_workspaces_route_carries_the_summary(self):
        row = (WORKSPACE, "owner", True, True, True, True, 1_700_000_000.0, "Studio", None, "studio", PRINCIPAL, "", {"owner": 1})
        cursor = FakeCursor([([row], 1)])
        listed = service(cursor, verifier()).workspaces("t")["workspaces"][0]
        self.assertEqual((listed["workspaceId"], listed["name"], listed["plan"], listed["trialPlan"], listed["memberCounts"]["owner"], listed["membership"]["role"]), (WORKSPACE, "Studio", "trial", "studio", 1, "owner"))


class OwnershipTransfer(unittest.TestCase):
    """hosted.py `transfer_ownership`: owner-only, step-up, target must be an active admin."""
    OWNER_ROW = (1, "{}", "owner", True, True, True, True)

    def test_only_the_owner_can_transfer(self):
        cursor = FakeCursor([((1, "{}", "admin", False, False, False, True), 1)])
        with self.assertRaises(AlphaError) as not_owner:
            service(cursor, verifier()).transfer_ownership(WORKSPACE, "t", OTHER)
        self.assertEqual(not_owner.exception.status, 403)

    def test_cannot_transfer_to_self(self):
        cursor = FakeCursor([(self.OWNER_ROW, 1)])
        with self.assertRaises(AlphaError) as to_self:
            service(cursor, verifier()).transfer_ownership(WORKSPACE, "t", PRINCIPAL)
        self.assertEqual(to_self.exception.status, 409)

    def test_target_must_be_an_active_admin(self):
        cursor = FakeCursor([(self.OWNER_ROW, 1), (None, 0)])
        with self.assertRaises(AlphaError) as missing:
            service(cursor, verifier()).transfer_ownership(WORKSPACE, "t", OTHER)
        self.assertEqual(missing.exception.status, 404)
        cursor = FakeCursor([(self.OWNER_ROW, 1), (("editor",), 1)])
        with self.assertRaises(AlphaError) as not_admin:
            service(cursor, verifier()).transfer_ownership(WORKSPACE, "t", OTHER)
        self.assertEqual(not_admin.exception.status, 409)

    def test_needs_a_fresh_sign_in(self):
        cursor = FakeCursor([(self.OWNER_ROW, 1)])
        with self.assertRaises(AlphaError) as stale:
            service(cursor, verifier(auth_time=1_800_000_000.0 - 3600)).transfer_ownership(WORKSPACE, "t", OTHER)
        self.assertIn("Sign in again", str(stale.exception))

    def test_swaps_roles_atomically_and_audits_it(self):
        cursor = FakeCursor([(self.OWNER_ROW, 1), (("admin",), 1), (None, 1), (None, 1), (None, 1)])
        result = service(cursor, verifier()).transfer_ownership(WORKSPACE, "t", OTHER)
        self.assertEqual(result, {"ownerId": OTHER, "previousOwnerId": PRINCIPAL})
        statements = [sql for sql, _ in cursor.executed]
        self.assertIn("role='owner'", statements[2])
        self.assertEqual(cursor.executed[2][1], (WORKSPACE, OTHER))
        self.assertIn("role='admin'", statements[3])
        self.assertEqual(cursor.executed[3][1], (WORKSPACE, PRINCIPAL))
        self.assertIn("pr_audit_events", statements[4])
        self.assertEqual(cursor.executed[4][1][2], "ownership.transferred")
        self.assertEqual(cursor.executed[4][1][3], OTHER)

    def test_members_route_reports_display_name(self):
        cursor = FakeCursor([(self.OWNER_ROW, 1), ([(PRINCIPAL, "active", "owner", True, True, True, True, 1_700_000_000.0, "James Au")], 1)])
        members = service(cursor, verifier()).members(WORKSPACE, "t")["members"]
        self.assertEqual(members, [{"userId": PRINCIPAL, "status": "active", "you": True, "role": "owner", "can_publish": True, "can_reply": True, "can_moderate": True, "can_manage_connections": True, "updatedAt": 1_700_000_000.0, "displayName": "James Au"}])


class IdentityAdmin(unittest.TestCase):
    def test_verified_factors_and_logout_others_use_the_right_endpoints(self):
        fetched, sent = [], []

        def fetch(method, url, headers):
            fetched.append((method, url, headers))
            return 200, {"id": PRINCIPAL, "factors": [{"id": "f1", "factor_type": "totp", "friendly_name": "Phone", "status": "verified", "secret": "never"}, {"id": "f2", "factor_type": "totp", "status": "unverified"}]}

        def send(method, url, headers, body):
            sent.append((method, url, headers))
            return 204

        admin = SupabaseIdentityAdmin("https://project.supabase.co", "public-key", "service-secret", send=send, fetch=fetch)
        self.assertEqual(admin.verified_factors(PRINCIPAL), [{"id": "f1", "type": "totp", "name": "Phone"}])
        self.assertEqual(fetched[0][1], f"https://project.supabase.co/auth/v1/admin/users/{PRINCIPAL}")
        self.assertTrue(admin.logout_others("user-token"))
        self.assertEqual(sent[0][1], "https://project.supabase.co/auth/v1/logout?scope=others")
        self.assertEqual(sent[0][2]["Authorization"], "Bearer user-token")
        with self.assertRaises(AlphaError):
            admin.verified_factors("not-a-user-id")


if __name__ == "__main__":
    unittest.main()
