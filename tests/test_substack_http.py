"""Actual WSGI route/CSRF/token dispatch tests; provider and DB are not live."""
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.api_tokens import route_scope
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication


class DispatchRecorder:
    enabled = True

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name not in {"workspace", "capabilities", "connect", "disconnect", "refresh", "save_draft", "approve", "handoff", "cancel", "delete_draft"}:
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {"operation": name, "revision": 2, "autoPublished": False}
        return call


class SubstackHttpTests(unittest.TestCase):
    def setUp(self):
        self.backend = DispatchRecorder()
        self.app = HostedApplication(service=SimpleNamespace(substack=self.backend))

    def request(self, method, tail, payload=None, **headers):
        raw = json.dumps(payload or {"expectedRevision": 1}).encode()
        env = {"REQUEST_METHOD": method, "PATH_INFO": "/api/workspaces/w/substack/" + tail,
               "HTTP_AUTHORIZATION": "Bearer test-session-authorized-fixture", "HTTP_X_POSTRIFF_REQUEST": "founder-alpha",
               "HTTP_HOST": "rafii.test", "HTTP_ORIGIN": "https://rafii.test", "wsgi.url_scheme": "https",
               "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), **headers}
        captured = []
        body = b"".join(self.app(env, lambda status, response_headers: captured.append((status, response_headers))))
        return int(captured[0][0].split()[0]), json.loads(body)

    def test_workspace_and_capabilities_are_mounted(self):
        for operation in ("workspace", "capabilities"):
            with self.subTest(operation=operation):
                status, body = self.request("GET", operation)
                self.assertEqual(status, 200)
                self.assertEqual(body["operation"], operation)
                self.assertEqual(self.backend.calls[-1][1], ("w", "test-session-authorized-fixture"))

    def test_every_mutation_binds_path_workspace_and_resource(self):
        routes = [("POST", "connections", "connect"), ("POST", "connections/sc_1/disconnect", "disconnect"),
                  ("POST", "connections/sc_1/refresh", "refresh"), ("POST", "drafts", "save_draft"),
                  ("PATCH", "drafts/sd_1", "save_draft"), ("DELETE", "drafts/sd_1", "delete_draft"),
                  ("POST", "drafts/sd_1/approve", "approve"), ("POST", "drafts/sd_1/handoff", "handoff"),
                  ("POST", "drafts/sd_1/cancel", "cancel")]
        for method, path, operation in routes:
            with self.subTest(method=method, path=path):
                payload = {"expectedRevision": 1, "workspaceId": "foreign", "userId": "forged", "contentHash": "a" * 64}
                status, body = self.request(method, path, payload)
                self.assertEqual(status, 201 if path == "drafts" else 200)
                name, args, kwargs = self.backend.calls[-1]
                self.assertEqual((name, args[0], args[1]), (operation, "w", "test-session-authorized-fixture"))
                self.assertIs(body["autoPublished"], False)
                if method == "PATCH":
                    self.assertEqual(kwargs, {"draft_id": "sd_1"})
                elif len(path.split("/")) > 1:
                    self.assertEqual(args[2], path.split("/")[1])

    def test_all_mutation_verbs_require_application_guard(self):
        for method, tail in (("POST", "connections"), ("PATCH", "drafts/sd_1"), ("DELETE", "drafts/sd_1")):
            self.assertEqual(self.request(method, tail, HTTP_X_POSTRIFF_REQUEST="")[0], 403)
        self.assertEqual(self.backend.calls, [])

    def test_cross_origin_mutation_never_reaches_service(self):
        self.assertEqual(self.request("POST", "connections", HTTP_ORIGIN="https://attacker.test")[0], 403)
        self.assertEqual(self.backend.calls, [])

    def test_missing_session_never_reaches_service(self):
        self.assertEqual(self.request("GET", "workspace", HTTP_AUTHORIZATION="")[0], 401)
        self.assertEqual(self.backend.calls, [])

    def test_feature_off_fails_closed(self):
        self.backend.enabled = False
        for method, tail in (("GET", "workspace"), ("POST", "connections"), ("POST", "drafts")):
            status, body = self.request(method, tail)
            self.assertEqual(status, 404)
            self.assertEqual(body["code"], "feature_disabled")
        self.assertEqual(self.backend.calls, [])

    def test_no_publish_oauth_subscriber_or_payment_routes(self):
        for tail in ("publish", "oauth/start", "oauth/callback", "notes", "subscribers/import", "payments", "drafts/sd_1/publish", "drafts/sd_1/schedule"):
            for method in ("GET", "POST"):
                self.assertEqual(self.request(method, tail)[0], 404, (method, tail))
        self.assertEqual(self.backend.calls, [])

    def test_unexpected_method_never_dispatches(self):
        for method, tail in (("GET", "connections"), ("GET", "drafts/sd_1/approve"), ("PUT", "drafts/sd_1"), ("DELETE", "connections/sc_1")):
            self.assertEqual(self.request(method, tail)[0], 404)
        self.assertEqual(self.backend.calls, [])

    def test_json_object_and_content_type_are_required(self):
        self.assertEqual(self.request("POST", "connections", CONTENT_TYPE="text/plain")[0], 415)
        self.assertEqual(self.request("POST", "connections", ["not", "object"])[0], 400)
        self.assertEqual(self.backend.calls, [])

    def test_api_token_read_and_draft_scope_allowlist(self):
        for tail in ("workspace", "capabilities"):
            self.assertEqual(route_scope("GET", ("api/workspaces/w/substack/" + tail).split("/")), "read")
        self.assertEqual(route_scope("POST", "api/workspaces/w/substack/drafts".split("/")), "draft")
        self.assertEqual(route_scope("PATCH", "api/workspaces/w/substack/drafts/sd_1".split("/")), "draft")

    def test_api_tokens_never_gain_connection_approval_handoff_or_external_authority(self):
        for tail in ("connections", "connections/sc_1/disconnect", "connections/sc_1/refresh", "drafts/sd_1/approve", "drafts/sd_1/handoff", "drafts/sd_1/cancel", "publish", "subscribers", "oauth/start", "future"):
            for method in ("GET", "POST", "PATCH", "DELETE"):
                self.assertIsNone(route_scope(method, ("api/workspaces/w/substack/" + tail).split("/")), (method, tail))
        self.assertIsNone(route_scope("DELETE", "api/workspaces/w/substack/drafts/sd_1".split("/")))

    def test_existing_hosted_service_mounts_substack_without_opening_database(self):
        def no_connection():
            raise AssertionError("Composition must not query customer data")
        service = HostedWorkspaceService(no_connection, lambda token: "verified-owner", substack_enabled=True)
        self.assertIs(service.substack.repository, service.repository)
        self.assertIs(service.substack.enabled, True)
        self.assertIs(HostedWorkspaceService(no_connection, lambda token: "verified-owner").substack.enabled, False)


if __name__ == "__main__":
    unittest.main()
