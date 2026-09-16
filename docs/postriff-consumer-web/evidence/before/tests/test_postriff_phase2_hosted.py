import io
import json
import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_storage import SupabaseStorage
from postriff_phase2.hosted_identity import SupabaseIdentityAdmin, verified_session_id


class FakeService:
    def bootstrap(self, token, plan):
        return {"workspaceId": "w", "token": token, "revision": 1, "state": {"plan": plan}}

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
