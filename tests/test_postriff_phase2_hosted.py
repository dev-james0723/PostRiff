import io
import json
import base64
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import Mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_storage import SupabaseStorage
from postriff_phase2.hosted_identity import SupabaseIdentityAdmin, verified_auth_time, verified_session_id
from postriff_phase2.hosted_app import client_address, client_label
from postriff_phase2.permissions import Membership, classify, require_action, validate_grant, STEP_UP_ACTIONS


class FakeService:
    def bootstrap(self, token, plan, client=None, client_label=""):
        return {"workspaceId": "w", "token": token, "revision": 1, "state": {"plan": plan}, "client": client, "label": client_label}

    def workspaces(self, token):
        return {"workspaces": [{"workspaceId": "w", "membership": {"role": "owner"}}]}

    def members(self, workspace_id, token):
        return {"members": [{"userId": "u", "role": "owner", "you": True}], "membership": {"role": "owner"}}

    def update_member(self, workspace_id, token, user_id, role, flags):
        return {"userId": user_id, "role": role, **flags}

    def remove_member(self, workspace_id, token, user_id):
        return {"userId": user_id, "status": "revoked"}

    def invite(self, workspace_id, token, email, role, flags):
        if role == "owner":
            raise AlphaError("Choose admin, editor, approver, or viewer.")
        return {"invitationId": "inv", "token": "raw-once", "role": role, "expiresAt": 1.0}

    def invitations(self, workspace_id, token):
        return {"invitations": [{"invitationId": "inv", "state": "pending"}]}

    def revoke_invitation(self, workspace_id, token, invitation_id):
        return {"invitationId": invitation_id, "state": "revoked"}

    def accept_invitation(self, token, raw, client=None):
        if raw == "throttled":
            raise AlphaError("Too many attempts. Wait a minute and try again.", 429)
        return {"workspaceId": "w", "role": "editor"}

    def sessions(self, token, client_label=""):
        return {"sessions": [{"sessionId": "s" * 20, "current": True}]}

    def revoke_session(self, token, session_id):
        return {"sessionId": session_id, "revoked": True}

    def audit_events(self, workspace_id, token):
        return {"events": []}

    def run_reminders(self):
        return {"sent": 0, "skipped": 0}

    def billing_checkout(self, workspace_id, token, plan_terms_id, success_path=None, cancel_path=None):
        if plan_terms_id == "studio-v1":
            raise AlphaError("This plan is not yet available for purchase.", 409)
        return {"url": "https://checkout.stripe.test/s", "sessionId": "cs_test", "plan": plan_terms_id, "success": success_path, "cancel": cancel_path}

    def billing_portal(self, workspace_id, token, return_path=None):
        if return_path == "/nowhere":
            raise AlphaError("No billing account yet. Start a subscription first.", 409)
        return {"url": "https://billing.stripe.test/p", "return": return_path}

    def get(self, workspace_id, token):
        return {"workspace": workspace_id, "tokenSeen": bool(token)}

    def logout(self, token):
        return {"signedOut": bool(token), "sessionDenied": True}

    def export_profile(self, workspace_id, token):
        return b"PK-profile"

    def delete_account(self, workspace_id, token, confirmation):
        return {"deleted": confirmation == "DELETE", "workspaceId": workspace_id, "tokenSeen": bool(token)}


class FakeWorker:
    def tick(self):
        return {"processed": 0, "execution": "hosted-worker", "externalExecution": False}


def invoke(app, method, path, body=None, headers=None):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
        "wsgi.url_scheme": "https",
        "HTTP_HOST": "postriff.example",
        "HTTP_ORIGIN": "https://postriff.example",
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}
    response = b"".join(app(environ, lambda status, values: captured.update(status=status, headers=dict(values))))
    return int(captured["status"].split()[0]), captured["headers"], json.loads(response) if captured["headers"]["Content-Type"].startswith("application/json") else response


class HostedPhase2Acceptance(unittest.TestCase):
    def test_hosted_command_engine_reuses_state_logic_and_blocks_backend_shortcuts(self):
        commands = HostedPhase2Commands(clock=lambda: 1_800_000_000)
        state = initial_phase2_state("00000000-0000-0000-0000-000000000010", "00000000-0000-0000-0000-000000000001", "Member", "studio", 1_800_000_000, execution="hosted-candidate")
        changed = commands(state, state["account"]["userId"], "mode", {"mode": "personal"})
        self.assertEqual(changed["brandHub"]["mode"], "personal")
        for action in ("p2_media_upload", "p2_channel_verify", "p2_delete_account", "p2_art_generate"):
            with self.subTest(action=action), self.assertRaises(AlphaError):
                commands(changed, changed["account"]["userId"], action, {})

    def test_media_edits_use_live_membership_and_samples_stay_read_only(self):
        commands = HostedPhase2Commands(clock=lambda: 1_800_000_000)
        creator = "00000000-0000-0000-0000-000000000001"
        editor = "00000000-0000-0000-0000-000000000002"
        workspace = "00000000-0000-0000-0000-000000000010"
        asset = {"id": "asset", "objectName": "image", "deleted": False}
        for role in ("owner", "admin", "editor", "viewer"):
            with self.subTest(role=role):
                state = initial_phase2_state(workspace, creator, "Member", "studio", 1_800_000_000, execution="synthetic")
                repository = PostgresWorkspaceRepository(None, lambda token: editor)
                @contextmanager
                def transaction(token, workspace_id):
                    yield Mock(), [1, state, role, False, False, False, False], editor
                repository.transaction = transaction
                operations = (
                    lambda current, actor: commands.add_asset(current, actor, asset),
                    lambda current, actor: commands.prepare_asset_delete(current, actor, "asset"),
                    lambda current, actor: commands.finish_asset_delete(current, actor, "asset"),
                )
                if role == "viewer":
                    state["phase2"]["assets"] = [dict(asset)]
                    for operation in operations:
                        with self.assertRaises(AlphaError) as denied:
                            repository.command(workspace, "synthetic", 1, operation)
                        self.assertEqual(denied.exception.status, 403)
                    continue
                for operation in operations:
                    state = repository.command(workspace, "synthetic", 1, operation)["state"]
                self.assertTrue(state["phase2"]["assets"][0]["deleted"])
                self.assertNotIn("objectName", state["phase2"]["assets"][0])
                state["workspace"]["sample"] = True
                for operation in operations:
                    with self.assertRaises(AlphaError) as denied:
                        repository.command(workspace, "synthetic", 1, operation)
                    self.assertEqual(denied.exception.code, "sample_read_only")

    def test_storage_descriptors_are_private_immutable_and_bounded(self):
        calls = []

        def send(method, url, headers, body):
            calls.append((method, url, headers, body))
            if "/sign/" in url:
                return 200, {}, json.dumps({"signedURL": "/storage/v1/object/sign/postriff-private/signed-token"}).encode()
            return 201 if method == "POST" else 204, {}, b""

        storage = SupabaseStorage("https://project.supabase.co", "s" * 32, send=send)
        wid = "00000000-0000-0000-0000-000000000010"
        name = "a" * 32 + "-" + "b" * 64 + ".jpg"
        path = storage.put_immutable(wid, "media", name, b"jpeg")
        self.assertEqual(path, f"{wid}/media/{name}")
        self.assertEqual(calls[0][2]["x-upsert"], "false")
        self.assertNotIn("s" * 32, calls[0][1])
        signed = storage.signed_url(wid, "media", name, 120)
        self.assertTrue(signed.startswith("https://project.supabase.co/storage/v1/object/sign/"))
        with self.assertRaises(AlphaError):
            storage.signed_url(wid, "media", name, 3600)

    def test_error_codes_preserve_status_and_message(self):
        class FailingService(FakeService):
            def get(self, workspace_id, token):
                raise AlphaError("Copy may change.", 409, code="workspace_revision_conflict")

        app = HostedApplication(FailingService(), FakeWorker(), {}, "c" * 24)
        status, _, body = invoke(app, "GET", "/api/workspaces/w", headers={"Authorization": "Bearer " + "t" * 32})
        self.assertEqual(status, 409)
        self.assertEqual(body, {"error": "Copy may change.", "code": "workspace_revision_conflict"})
        self.assertEqual(AlphaError("Old caller", 403).code, "permission_denied")
        self.assertEqual(AlphaError("Unrelated conflict", 409).code, "conflict")

    def test_wsgi_auth_origin_and_cron_boundaries(self):
        app = HostedApplication(FakeService(), FakeWorker(), {"projectUrl": "https://project.supabase.co", "publishableKey": "public", "flow": "pkce"}, "c" * 24)
        status, _, health = invoke(app, "GET", "/api/health")
        self.assertEqual((status, health["configured"]), (200, True))
        status, _, _ = invoke(app, "POST", "/api/auth/verify", {"plan": "studio"}, {"Authorization": "Bearer " + "t" * 32})
        self.assertEqual(status, 403)
        status, _, created = invoke(app, "POST", "/api/auth/verify", {"plan": "assist"}, {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"})
        self.assertEqual((status, created["state"]["plan"]), (201, "assist"))
        self.assertNotIn("token", created)
        status, _, _ = invoke(app, "GET", "/api/cron/worker", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)
        status, _, result = invoke(app, "GET", "/api/cron/worker", headers={"Authorization": "Bearer " + "c" * 24})
        self.assertEqual((status, result["externalExecution"]), (200, False))

    def test_wsgi_hosted_lifecycle_routes_require_verified_mutations(self):
        app = HostedApplication(FakeService(), FakeWorker(), {"projectUrl": "https://project.supabase.co", "publishableKey": "public", "flow": "pkce"}, "c" * 24)
        auth = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"}
        status, _, result = invoke(app, "POST", "/api/auth/logout", {}, auth)
        self.assertEqual((status, result["signedOut"], result["sessionDenied"]), (200, True, True))
        status, _, profile = invoke(app, "GET", "/api/workspaces/w/profile-export", headers=auth)
        self.assertEqual((status, profile), (200, b"PK-profile"))
        status, _, deleted = invoke(app, "DELETE", "/api/workspaces/w/account", {"confirmation": "DELETE"}, auth)
        self.assertEqual((status, deleted["deleted"]), (200, True))

    def test_permission_matrix_matches_architecture_roles(self):
        owner = Membership("owner")
        admin = Membership("admin")
        editor = Membership("editor")
        approver = Membership("approver")
        viewer = Membership("viewer")
        publishing_editor = Membership("editor", {"can_publish": True})
        flagged_viewer = Membership("viewer", {"can_publish": True, "can_manage_connections": True})
        self.assertTrue(all(owner.allows(k) for k in ("read", "edit", "approve", "reply", "moderate", "manage_connections", "manage_members", "owner")))
        self.assertEqual([admin.allows(k) for k in ("edit", "approve", "manage_connections", "manage_members", "owner")], [True, False, True, True, False])
        self.assertEqual([editor.allows(k) for k in ("read", "edit", "approve", "manage_connections", "manage_members")], [True, True, False, False, False])
        self.assertEqual([approver.allows(k) for k in ("read", "edit", "approve")], [True, False, True])
        self.assertEqual([viewer.allows(k) for k in ("read", "edit", "approve")], [True, False, False])
        self.assertTrue(publishing_editor.allows("approve"))
        # Flags never elevate a viewer.
        self.assertFalse(flagged_viewer.allows("approve") or flagged_viewer.allows("manage_connections"))
        self.assertEqual(classify("p2_approve"), "approve")
        self.assertEqual(classify("p2_channel_disconnect"), "manage_connections")
        self.assertEqual(classify("variant_edit"), "edit")
        self.assertIn("p2_channel_disconnect", STEP_UP_ACTIONS)
        with self.assertRaises(AlphaError):
            require_action(editor, "p2_approve")
        with self.assertRaises(AlphaError):
            classify("")

    def test_grants_cannot_escalate_beyond_granter(self):
        owner, admin = Membership("owner"), Membership("admin", {"can_publish": False})
        self.assertEqual(validate_grant("approver", {"can_publish": True}, owner)["can_publish"], True)
        with self.assertRaises(AlphaError):
            validate_grant("owner", {}, owner)
        with self.assertRaises(AlphaError):
            validate_grant("editor", {"can_publish": True}, admin)
        with self.assertRaises(AlphaError):
            validate_grant("editor", {"can_publish": "yes"}, owner)
        with self.assertRaises(AlphaError):
            validate_grant("editor", {"can_fly": True}, owner)

    def test_verified_auth_time_is_stale_when_missing(self):
        def token(payload):
            encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
            return "header." + encoded + ".signature"
        principal = "00000000-0000-0000-0000-000000000001"
        self.assertEqual(verified_auth_time(token({"sub": principal, "iat": 1_800_000_000}), principal), 1_800_000_000.0)
        self.assertEqual(verified_auth_time(token({"sub": principal}), principal), 0)
        with self.assertRaises(AlphaError):
            verified_auth_time(token({"sub": "other", "iat": 1}), principal)

    def test_client_address_and_label_are_bounded(self):
        self.assertEqual(client_address({"HTTP_X_FORWARDED_FOR": "203.0.113.5, 10.0.0.1", "REMOTE_ADDR": "10.0.0.2"}), "203.0.113.5")
        self.assertEqual(client_address({"REMOTE_ADDR": "10.0.0.2"}), "10.0.0.2")
        self.assertIsNone(client_address({}))
        self.assertEqual(client_label({"HTTP_USER_AGENT": "Mozilla/5.0 (secret token)"}), "Mozilla")
        self.assertEqual(client_label({}), "unknown")
        self.assertLessEqual(len(client_label({"HTTP_USER_AGENT": "x" * 500})), 40)

    def test_wsgi_membership_invitation_session_routes(self):
        app = HostedApplication(FakeService(), FakeWorker(), {"projectUrl": "https://project.supabase.co", "publishableKey": "public", "flow": "pkce"}, "c" * 24)
        auth = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha", "X-Forwarded-For": "203.0.113.5"}
        status, _, created = invoke(app, "POST", "/api/auth/verify", {"plan": "studio"}, {**auth, "User-Agent": "PostRiffPWA/1.0"})
        self.assertEqual((status, created["client"], created["label"]), (201, "203.0.113.5", "PostRiffPWA"))
        status, _, listed = invoke(app, "GET", "/api/workspaces", headers=auth)
        self.assertEqual((status, listed["workspaces"][0]["workspaceId"]), (200, "w"))
        status, _, members = invoke(app, "GET", "/api/workspaces/w/members", headers=auth)
        self.assertEqual((status, members["members"][0]["you"]), (200, True))
        status, _, updated = invoke(app, "PATCH", "/api/workspaces/w/members/u2", {"role": "approver", "permissions": {"can_publish": True}}, auth)
        self.assertEqual((status, updated["role"], updated["can_publish"]), (200, "approver", True))
        status, _, removed = invoke(app, "DELETE", "/api/workspaces/w/members/u2", {}, auth)
        self.assertEqual((status, removed["status"]), (200, "revoked"))
        status, _, invited = invoke(app, "POST", "/api/workspaces/w/invitations", {"email": "a@b.co", "role": "editor"}, auth)
        self.assertEqual((status, invited["token"]), (201, "raw-once"))
        status, _, _ = invoke(app, "POST", "/api/workspaces/w/invitations", {"email": "a@b.co", "role": "owner"}, auth)
        self.assertEqual(status, 400)
        status, _, pending = invoke(app, "GET", "/api/workspaces/w/invitations", headers=auth)
        self.assertEqual((status, pending["invitations"][0]["state"]), (200, "pending"))
        status, _, revoked = invoke(app, "DELETE", "/api/workspaces/w/invitations/inv", {}, auth)
        self.assertEqual((status, revoked["state"]), (200, "revoked"))
        status, _, accepted = invoke(app, "POST", "/api/invitations/accept", {"token": "x" * 40}, auth)
        self.assertEqual((status, accepted["role"]), (200, "editor"))
        status, _, _ = invoke(app, "POST", "/api/invitations/accept", {"token": "throttled"}, auth)
        self.assertEqual(status, 429)
        status, _, sessions = invoke(app, "GET", "/api/auth/sessions", headers=auth)
        self.assertEqual((status, sessions["sessions"][0]["current"]), (200, True))
        status, _, gone = invoke(app, "DELETE", "/api/auth/sessions/" + "s" * 20, {}, auth)
        self.assertEqual((status, gone["revoked"]), (200, True))
        status, _, events = invoke(app, "GET", "/api/workspaces/w/audit", headers=auth)
        self.assertEqual((status, events["events"]), (200, []))
        # Mutating routes still require the application guard header.
        status, _, _ = invoke(app, "POST", "/api/workspaces/w/invitations", {"email": "a@b.co", "role": "editor"}, {"Authorization": "Bearer " + "t" * 32})
        self.assertEqual(status, 403)

    def test_verified_session_id_is_bound_to_verified_subject(self):
        def token(payload):
            encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
            return "header." + encoded + ".signature"
        principal = "00000000-0000-0000-0000-000000000001"
        self.assertEqual(verified_session_id(token({"sub": principal, "session_id": "session-1234567890"}), principal), "session-1234567890")
        with self.assertRaises(AlphaError):
            verified_session_id(token({"sub": "00000000-0000-0000-0000-000000000002", "session_id": "session-1234567890"}), principal)

    def test_identity_admin_never_places_service_key_in_url(self):
        calls = []
        admin = SupabaseIdentityAdmin("https://project.supabase.co", "public-key", "service-secret", send=lambda method, url, headers, body: calls.append((method, url, headers, body)) or 204)
        self.assertTrue(admin.logout("user-access-token"))
        self.assertTrue(admin.delete_user("00000000-0000-0000-0000-000000000001"))
        self.assertNotIn("service-secret", json.dumps([(method, url) for method, url, _, _ in calls]))
        self.assertEqual(calls[1][2]["Authorization"], "Bearer service-secret")


if __name__ == "__main__":
    unittest.main()


class AcceptUpdateFromIdeas(unittest.TestCase):
    def test_accept_update_works_for_hosted_candidates_without_a_local_run(self):
        """Ideas candidates carry a pr_agent_runs id; accepting their proposed update must not require a local run entry."""
        from postriff_phase2.hosted import HostedPhase2Commands
        state = initial_phase2_state("w", "u", "Member", "studio", 1.0, execution="hosted-candidate")
        state["speaker"]["revisions"].append({"revision": 1, "profile": {"tone": "warm", "writingExample": "", "observations": [], "unknowns": [], "preferences": []}, "approvedAt": "now", "reason": "test"})
        state["speaker"]["activeRevision"] = 1
        state["variants"].append({"id": "v1", "revision": 1, "platform": "Threads", "language": "English", "text": "old", "openings": [], "sourceIds": [], "warnings": [], "unknowns": [], "voiceRevision": None, "briefRevision": state["brief"]["revision"], "runId": "hosted-run-not-local", "speakerId": state["speaker"]["id"], "customized": False, "needsReview": True, "blockedByRetraction": False, "selectedOpening": 0, "localPreferences": {}, "revisions": [{"revision": 1, "text": "old", "origin": "ideas-candidate"}],
                                  "proposedUpdate": {"text": "new", "openings": [], "sourceIds": [], "warnings": [], "unknowns": [], "voiceRevision": 1, "briefRevision": state["brief"]["revision"], "runId": "hosted-run-not-local", "baseVariantRevision": 1}})
        saved = HostedPhase2Commands()(state, "u", "accept_update", {"variantId": "v1"})
        variant = saved["variants"][0]
        self.assertEqual((variant["text"], variant["voiceRevision"], variant["revision"], variant["needsReview"], variant["proposedUpdate"]), ("new", 1, 2, False, None))

