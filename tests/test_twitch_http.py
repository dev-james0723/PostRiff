"""Mounted HostedApplication Twitch route acceptance with synthetic services.

Every request traverses the real WSGI application, guards and Twitch router. No
provider/network client is allowed. OAuth custody and database authority have
their own native/OAuth/PostgreSQL suites; route mocks do not prove live access.
"""
import io
import json
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.twitch_eventsub import TwitchWebhookError, TwitchWebhookVerifier

from test_twitch_eventsub import CALLBACK, CONNECTION, NOW, TRUST, WS, signed_payload


TOKEN = "synthetic-verified-session-token-20261018"
ORIGIN = "https://rafii.io"
BASE = f"/api/workspaces/{WS}/twitch/{CONNECTION}"
METHODS = ("list_connections", "overview", "read", "preview", "approve", "cancel",
           "reconcile", "secret_access", "webhook")


def invoke(app, path, *, method="GET", payload=None, raw=None, token=TOKEN, guard=True,
           origin=ORIGIN, query="", headers=None, overrides=None):
    raw = json.dumps({} if payload is None else payload).encode() if raw is None else raw
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
        "wsgi.url_scheme": "https", "HTTP_HOST": "rafii.io",
        "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    if token is not None:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    if guard:
        environ["HTTP_X_POSTRIFF_REQUEST"] = "founder-alpha"
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    environ.update(overrides or {})
    result = {}

    def start_response(status, response_headers):
        result.update(status=int(status.split()[0]), headers=dict(response_headers))

    result["raw"] = b"".join(app(environ, start_response))
    if result["headers"].get("Content-Type", "").startswith("application/json"):
        result["body"] = json.loads(result["raw"])
    return result


class TwitchHttpBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.twitch = Mock(spec=METHODS)
        for name in METHODS:
            getattr(self.twitch, name).return_value = {"synthetic": True, "route": name}
        self.twitch.webhook.return_value = (b"", False)
        self.oauth = Mock(spec=("public_base_url", "start", "complete", "disconnect", "verify"))
        self.oauth.public_base_url = ORIGIN
        for name in ("start", "complete", "disconnect", "verify"):
            getattr(self.oauth, name).return_value = {"synthetic": True, "route": name}
        self.service = SimpleNamespace(twitch=self.twitch, oauth=self.oauth)
        self.app = HostedApplication(service=self.service)
        self.egress = self.enterContext(patch("socket.create_connection", side_effect=AssertionError("Network forbidden in HTTP acceptance")))
        self.http = self.enterContext(patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("HTTP forbidden in acceptance")))
        self.enterContext(patch.dict("os.environ", {
            "POSTRIFF_REQUEST_METRICS": "0", "RAFII_ACCOUNT_PROTECTION_V2_MODE": "off",
        }))

    def tearDown(self):
        self.egress.assert_not_called()
        self.http.assert_not_called()

    def verify_public_webhook(self):
        verifier = TwitchWebhookVerifier(clock=lambda: NOW)

        def receive(identifier, headers, raw):
            if identifier != CALLBACK:
                raise AlphaError("Webhook unavailable.", 404, code="twitch_webhook_unavailable")
            try:
                message = verifier.verify(headers, raw, TRUST)
            except TwitchWebhookError:
                raise AlphaError("Webhook authentication failed.", 403,
                                 code="twitch_webhook_authentication_failed") from None
            return message.challenge or b"", False

        self.twitch.webhook.side_effect = receive

    def assert_private_headers(self, result):
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        self.assertEqual(result["headers"]["Referrer-Policy"], "no-referrer")
        self.assertEqual(result["headers"]["X-Content-Type-Options"], "nosniff")
        self.assertIn("X-Request-ID", result["headers"])

    def test_native_collection_and_connection_are_mounted(self):
        result = invoke(self.app, f"/api/workspaces/{WS}/twitch")
        self.assertEqual(result["status"], 200)
        self.twitch.list_connections.assert_called_once_with(WS, TOKEN)
        result = invoke(self.app, BASE)
        self.assertEqual(result["body"]["route"], "overview")
        self.twitch.overview.assert_called_once_with(WS, TOKEN, CONNECTION)
        self.assert_private_headers(result)

    def test_native_read_routes_action_and_payload_without_request_authority(self):
        payload = {"first": 20}
        result = invoke(self.app, BASE + "/read/twitch.poll.get", method="POST", payload=payload)
        self.assertEqual(result["status"], 200)
        self.twitch.read.assert_called_once_with(WS, TOKEN, CONNECTION, "twitch.poll.get", payload)
        self.assert_private_headers(result)

    def test_preview_retains_exact_action_body_for_service_validation(self):
        payload = {"action": "twitch.chat.send", "payload": {"message": "Explicit synthetic consent"}}
        result = invoke(self.app, BASE + "/preview", method="POST", payload=payload)
        self.assertEqual(result["status"], 200)
        self.twitch.preview.assert_called_once_with(WS, TOKEN, CONNECTION, payload)
        self.twitch.approve.assert_not_called()
        self.twitch.read.assert_not_called()

    def test_action_approval_reconciliation_and_secret_access_routes_are_distinct(self):
        payload = {"confirmed": True, "payloadHash": "synthetic-approved-digest"}
        for operation, target in (("approve", "approve"), ("reconcile", "reconcile"),
                                  ("secret-access", "secret_access")):
            with self.subTest(operation=operation):
                self.twitch.reset_mock()
                result = invoke(self.app, BASE + "/actions/action-synthetic/" + operation,
                                method="POST", payload=payload)
                self.assertEqual(result["status"], 200)
                getattr(self.twitch, target).assert_called_once_with(WS, TOKEN, CONNECTION, "action-synthetic", payload)
                self.assertEqual(len(self.twitch.mock_calls), 1)
                self.assert_private_headers(result)

    def test_cancel_and_pause_keep_explicit_pause_flag(self):
        for operation, pause in (("cancel", False), ("pause", True)):
            with self.subTest(operation=operation):
                self.twitch.cancel.reset_mock()
                result = invoke(self.app, BASE + "/actions/action-synthetic/" + operation, method="POST")
                self.assertEqual(result["status"], 200)
                self.twitch.cancel.assert_called_once_with(WS, TOKEN, CONNECTION, "action-synthetic", {}, pause=pause)

    def test_payload_tenant_fields_cannot_change_router_selected_principal(self):
        payload = {"action": "twitch.chat.send", "payload": {"message": "Synthetic"},
                   "workspaceId": "attacker-workspace", "connectionId": "attacker-connection", "token": "attacker"}
        result = invoke(self.app, BASE + "/preview", method="POST", payload=payload)
        self.assertEqual(result["status"], 200)
        # The strict service rejects extra fields; the router never consumes them as authority.
        self.twitch.preview.assert_called_once_with(WS, TOKEN, CONNECTION, payload)

    def test_every_private_native_surface_requires_a_bearer_before_service_dispatch(self):
        routes = [(BASE, "GET"), (f"/api/workspaces/{WS}/twitch", "GET"),
                  (BASE + "/preview", "POST"), (BASE + "/read/twitch.channel.get", "POST")]
        routes += [(BASE + "/actions/action-synthetic/" + action, "POST")
                   for action in ("approve", "cancel", "pause", "reconcile", "secret-access")]
        for path, method in routes:
            with self.subTest(path=path):
                result = invoke(self.app, path, method=method, token=None)
                self.assertEqual(result["status"], 401)
                self.assertEqual(self.twitch.mock_calls, [])

    def test_malformed_or_short_bearers_never_reach_twitch(self):
        for authorization in ("", "Basic synthetic", "Bearer short", "bearer " + TOKEN):
            with self.subTest(authorization=authorization):
                result = invoke(self.app, BASE + "/preview", method="POST",
                                overrides={"HTTP_AUTHORIZATION": authorization})
                self.assertEqual(result["status"], 401)
                self.assertEqual(self.twitch.mock_calls, [])

    def test_native_mutations_require_application_guard(self):
        for suffix in ("preview", "read/twitch.channel.get", "actions/action-synthetic/approve",
                       "actions/action-synthetic/secret-access"):
            with self.subTest(suffix=suffix):
                result = invoke(self.app, BASE + "/" + suffix, method="POST", guard=False)
                self.assertEqual(result["status"], 403)
                self.assertEqual(self.twitch.mock_calls, [])

    def test_cross_origin_mutations_and_reads_are_denied_before_dispatch(self):
        for origin in ("https://evil.example", "https://rafii.io.evil.example", "http://rafii.io", "null"):
            for suffix in ("preview", "read/twitch.channel.get"):
                with self.subTest(origin=origin, suffix=suffix):
                    result = invoke(self.app, BASE + "/" + suffix, method="POST", origin=origin)
                    self.assertEqual(result["status"], 403)
                    self.assertEqual(self.twitch.mock_calls, [])

    def test_proxy_origin_guard_uses_browser_facing_host_and_protocol(self):
        result = invoke(self.app, BASE + "/preview", method="POST", overrides={
            "HTTP_HOST": "private-runtime:8080", "HTTP_X_FORWARDED_HOST": "rafii.io",
            "HTTP_X_FORWARDED_PROTO": "https", "wsgi.url_scheme": "http",
        })
        self.assertEqual(result["status"], 200)
        self.twitch.preview.assert_called_once()

    def test_disallowed_api_token_cannot_bypass_boundary_using_missing_origin_guard(self):
        api_tokens = Mock()
        api_tokens.authorize.side_effect = AlphaError("API token lacks this scope.", 403)
        self.service.repository = SimpleNamespace(api_tokens=api_tokens)
        result = invoke(self.app, BASE + "/preview", method="POST", token="prt_" + "s" * 32,
                        guard=False, origin=None)
        self.assertEqual(result["status"], 403)
        api_tokens.authorize.assert_called_once()
        self.assertEqual(self.twitch.mock_calls, [])

    def test_invalid_json_media_types_and_top_level_shapes_do_not_dispatch(self):
        for raw, content_type, status in ((b"{", "application/json", 400), (b"[]", "application/json", 400),
                                          (b"null", "application/json", 400), (b"{}", "text/plain", 415)):
            with self.subTest(raw=raw, content_type=content_type):
                result = invoke(self.app, BASE + "/preview", method="POST", raw=raw,
                                overrides={"CONTENT_TYPE": content_type})
                self.assertEqual(result["status"], status)
                self.assertEqual(self.twitch.mock_calls, [])

    def test_native_route_does_not_expose_worker_dispatch_or_arbitrary_subpaths(self):
        for suffix in ("execute", "dispatch", "actions/action-synthetic/dispatch", "preview/extra",
                       "read/twitch.channel.get/extra", "actions/action-synthetic/approve/extra"):
            with self.subTest(suffix=suffix):
                result = invoke(self.app, BASE + "/" + suffix, method="POST")
                self.assertEqual(result["status"], 404)
                self.assertEqual(self.twitch.mock_calls, [])

    def test_service_permission_failures_preserve_safe_status_and_code(self):
        self.twitch.preview.side_effect = AlphaError("Workspace access denied.", 403, code="twitch_workspace_forbidden")
        result = invoke(self.app, BASE + "/preview", method="POST")
        self.assertEqual(result["status"], 403)
        self.assertEqual(result["body"]["code"], "twitch_workspace_forbidden")
        self.assert_private_headers(result)

    def test_unexpected_provider_text_and_tokens_never_reach_http_response_or_log(self):
        secret = "synthetic-access-token-DO-NOT-LOG"
        self.twitch.read.side_effect = RuntimeError(secret + " private-viewer-content")
        with self.assertLogs("postriff.request", level="INFO") as logs:
            result = invoke(self.app, BASE + "/read/twitch.channel.get", method="POST", payload={"private": secret})
        self.assertEqual(result["status"], 500)
        self.assertEqual(result["body"]["code"], "internal_error")
        rendered = result["raw"].decode() + "\n".join(logs.output)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("private-viewer-content", rendered)
        self.assertNotIn(TOKEN, rendered)

    def test_public_twitch_oauth_callback_is_mounted_and_only_redirects_to_fixed_origin(self):
        query = urlencode({"state": "synthetic-state", "code": "synthetic-code",
                           "workspaceId": "attacker-workspace", "next": "https://evil.example"})
        result = invoke(self.app, "/api/oauth/twitch/callback", token=None, guard=False, origin=None,
                        query=query, overrides={"HTTP_HOST": "evil.example", "HTTP_X_FORWARDED_HOST": "evil.example"})
        self.assertEqual(result["status"], 302)
        location = urlsplit(result["headers"]["Location"])
        self.assertEqual((location.scheme, location.netloc, location.path), ("https", "rafii.io", "/channels/connect"))
        self.assertEqual(parse_qs(location.query), {"state": ["synthetic-state"], "code": ["synthetic-code"], "provider": ["twitch"]})
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        self.assertEqual(result["headers"]["Referrer-Policy"], "no-referrer")
        self.oauth.complete.assert_not_called()
        self.assertEqual(self.twitch.mock_calls, [])

    def test_oauth_callback_does_not_require_runtime_or_exchange_on_cold_start(self):
        app = HostedApplication()
        app._runtime = Mock(side_effect=AssertionError("Public redirect cannot initialize runtime"))
        with patch.dict("os.environ", {"POSTRIFF_PUBLIC_BASE_URL": ORIGIN}):
            result = invoke(app, "/api/oauth/twitch/callback", token=None, guard=False, query="error=access_denied&state=synthetic-state")
        self.assertEqual(result["status"], 302)
        app._runtime.assert_not_called()
        self.assertEqual(parse_qs(urlsplit(result["headers"]["Location"]).query)["error"], ["access_denied"])

    def test_authenticated_oauth_completion_keeps_url_workspace_and_session_binding(self):
        body = {"state": "synthetic-persisted-state-20261018", "code": "synthetic-one-use-code",
                "workspaceId": "attacker-workspace", "provider": "attacker-provider"}
        result = invoke(self.app, f"/api/workspaces/{WS}/channels/twitch/oauth/complete", method="POST", payload=body)
        self.assertEqual(result["status"], 200)
        self.oauth.complete.assert_called_once_with(WS, TOKEN, "twitch", body["state"], body["code"], None)

    def test_oauth_start_complete_and_disconnect_remain_authenticated(self):
        routes = [(f"/api/workspaces/{WS}/channels/twitch/oauth/{kind}", "POST") for kind in ("start", "complete")]
        routes.append((f"/api/workspaces/{WS}/channels/{CONNECTION}", "DELETE"))
        for path, method in routes:
            with self.subTest(path=path):
                result = invoke(self.app, path, method=method, token=None)
                self.assertEqual(result["status"], 401)
                self.assertEqual(self.oauth.mock_calls, [])

    def test_signed_public_eventsub_challenge_passes_raw_bytes_without_session_or_origin(self):
        self.verify_public_webhook()
        headers, raw = signed_payload(kind="webhook_callback_verification")
        result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK, method="POST", raw=raw,
                        token=None, guard=False, origin=None, headers=headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["raw"], b"synthetic-challenge")
        self.assertEqual(result["headers"]["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        self.assertEqual(result["headers"]["Content-Length"], str(len(result["raw"])))
        call = self.twitch.webhook.call_args
        self.assertEqual((call.args[0], call.args[2]), (CALLBACK, raw))
        self.assertEqual({k.lower(): v for k, v in call.args[1]}, {k.lower(): v for k, v in headers.items()})

    def test_signed_notification_is_204_after_service_returns(self):
        self.verify_public_webhook()
        headers, raw = signed_payload()
        result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK, method="POST", raw=raw,
                        token=None, guard=False, origin=None, headers=headers)
        self.assertEqual(result["status"], 204)
        self.assertEqual(result["raw"], b"")
        self.assertEqual(result["headers"]["Content-Length"], "0")

    def test_duplicate_receipt_acknowledgement_does_not_return_event_content(self):
        self.twitch.webhook.return_value = (b"", True)
        headers, raw = signed_payload()
        result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK, method="POST", raw=raw,
                        token=None, guard=False, headers=headers)
        self.assertEqual(result["status"], 204)
        self.assertEqual(result["raw"], b"")
        self.twitch.preview.assert_not_called()

    def test_forged_missing_and_proxy_joined_signature_headers_are_rejected(self):
        self.verify_public_webhook()
        headers, raw = signed_payload()
        name = "Twitch-Eventsub-Message-Signature"
        variants = [({}, raw), ({**headers, name: "sha256=" + "0" * 64}, raw),
                    ({**headers, name: headers[name] + ", " + headers[name]}, raw),
                    (headers, raw + b" "),
                    ({**headers, "Twitch-Eventsub-Message-Type": "revocation"}, raw)]
        for index, (changed, body) in enumerate(variants):
            with self.subTest(variant=index):
                result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK, method="POST", raw=body,
                                token=None, guard=False, headers=changed)
                self.assertEqual(result["status"], 403)
                self.assertEqual(result["body"]["code"], "twitch_webhook_authentication_failed")

    def test_bad_webhook_length_and_truncated_body_never_reach_service(self):
        headers, raw = signed_payload()
        for length, status in (("nonnumeric", 400), ("0", 413), ("-1", 413), ("262145", 413),
                               (str(len(raw) + 1), 400)):
            with self.subTest(length=length):
                result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK, method="POST", raw=raw,
                                token=None, guard=False, headers=headers, overrides={"CONTENT_LENGTH": length})
                self.assertEqual(result["status"], status)
                self.twitch.webhook.assert_not_called()

    def test_other_public_webhook_methods_or_extra_segments_do_not_dispatch(self):
        for method, suffix in (("GET", ""), ("PUT", ""), ("POST", "/extra")):
            with self.subTest(method=method, suffix=suffix):
                result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK + suffix, method=method)
                self.assertEqual(result["status"], 404)
                self.twitch.webhook.assert_not_called()

    def test_webhook_storage_failure_does_not_send_success_ack_or_leak_payload(self):
        secret = "synthetic-viewer-content-DO-NOT-LOG"
        self.twitch.webhook.side_effect = RuntimeError(secret)
        headers, raw = signed_payload()
        with self.assertLogs("postriff.request", level="INFO") as logs:
            result = invoke(self.app, "/api/twitch/eventsub/" + CALLBACK, method="POST", raw=raw,
                            token=None, guard=False, headers=headers)
        self.assertEqual(result["status"], 500)
        self.assertNotIn(secret, result["raw"].decode() + "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
