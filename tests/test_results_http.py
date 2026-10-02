"""G2-OUT routes through the real hosted application dispatcher (flag gate, public vs session routes, body cap)."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.results import service, signing
from postriff_phase2.results.service import Delivery

WID = "6f1c0f5e-7b0c-4c39-a4a5-6b8c2b0c9d11"
TOKEN = "Bearer " + "s" * 40


class Unreadable(io.RawIOBase):
    def read(self, *_):
        raise AssertionError("the body must not be read")


class FakeResults:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, args))
            if name == "ingest":
                return Delivery(200, {"receiptId": "r1", "status": "accepted", "attribution": "unattributed"}, [("X-Test", "1")])
            if name == "redirect":
                return None if args[0] == "UnknownSlug0001" else "https://example.org/?rafii_ref=" + args[0] + ".20261001"
            if name in ("declare", "create_link"):
                return {"replayed": args[2].get("replay", False)}
            return {"ok": name}
        return record


def call(app, method, path, body=None, headers=None, query=""):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "CONTENT_TYPE": "application/json", "HTTP_HOST": "app.example.org", "wsgi.url_scheme": "https", **(headers or {})}
    seen = {}

    def start_response(status, response_headers, exc_info=None):
        seen["status"], seen["headers"] = int(status.split()[0]), dict(response_headers)

    payload = b"".join(app(environ, start_response))
    return seen["status"], seen["headers"], payload


class ResultsRoutesTest(unittest.TestCase):
    def setUp(self):
        self.results = FakeResults()
        self.app = HostedApplication(service=SimpleNamespace(results=self.results), public_auth={})
        self.guard = {"HTTP_AUTHORIZATION": TOKEN, "HTTP_X_POSTRIFF_REQUEST": "founder-alpha", "HTTP_ORIGIN": "https://app.example.org"}

    def test_flag_off_hides_every_route(self):
        with patch.object(service, "enabled", return_value=False):
            status, _, body = call(self.app, "GET", f"/api/workspaces/{WID}/results/summary", headers=self.guard)
            self.assertEqual((status, json.loads(body)["code"]), (404, "feature_disabled"))
            status, _, body = call(self.app, "POST", "/api/results/webhook/" + WID, body={"eventId": "e"})
            self.assertEqual((status, json.loads(body)["code"]), (404, "feature_disabled"))
            status, headers, _ = call(self.app, "GET", "/api/l/AbCdEfGhIj0123456789abcd")
            self.assertEqual(status, 404)
            self.assertNotIn("Location", headers)
        self.assertEqual(self.results.calls, [])

    def test_ac17_body_cap_is_checked_before_reading(self):
        with patch.object(service, "enabled", return_value=True):
            environ_headers = {"CONTENT_LENGTH": str(signing.MAX_BODY_BYTES + 1)}
            raw = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/results/webhook/" + WID, "QUERY_STRING": "", "wsgi.input": Unreadable(),
                   **environ_headers}
            seen = {}
            body = b"".join(self.app(raw, lambda status, headers, exc=None: seen.update(status=int(status.split()[0]))))
            self.assertEqual((seen["status"], json.loads(body)["code"]), (413, "result_body_too_large"))
        self.assertEqual(self.results.calls, [])

    def test_webhook_needs_no_session_or_origin_and_passes_exact_bytes(self):
        with patch.object(service, "enabled", return_value=True):
            status, headers, body = call(self.app, "POST", "/api/results/webhook/" + WID, body={"eventId": "e1"},
                                         headers={"HTTP_X_RAFII_SIGNATURE": "t=1,v1=" + "a" * 64, "HTTP_ORIGIN": "https://elsewhere.example"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Test"], "1")
        name, (connection_id, header, raw) = self.results.calls[0]
        self.assertEqual((name, connection_id, header, raw), ("ingest", WID, "t=1,v1=" + "a" * 64, b'{"eventId": "e1"}'))
        self.assertEqual(json.loads(body), {"receiptId": "r1", "status": "accepted", "attribution": "unattributed"})

    def test_webhook_other_methods_and_paths(self):
        with patch.object(service, "enabled", return_value=True):
            self.assertEqual(call(self.app, "GET", "/api/results/webhook/" + WID)[0], 404)
            self.assertEqual(call(self.app, "POST", "/api/results/webhook/" + WID + "/x", body={})[0], 404)
        self.assertEqual(self.results.calls, [])

    def test_ac19_redirect_is_302_to_the_stored_destination_only(self):
        with patch.object(service, "enabled", return_value=True):
            status, headers, _ = call(self.app, "GET", "/api/l/AbCdEfGhIj0123456789abcd", headers={"HTTP_USER_AGENT": "Mozilla/5.0"})
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], "https://example.org/?rafii_ref=AbCdEfGhIj0123456789abcd.20261001")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(call(self.app, "GET", "/api/l/UnknownSlug0001")[0], 404)
            self.assertEqual(call(self.app, "POST", "/api/l/AbCdEfGhIj0123456789abcd", body={})[0], 404)
            # The destination never comes from the request.
            status, headers, _ = call(self.app, "GET", "/api/l/AbCdEfGhIj0123456789abcd", query="to=https://evil.example")
            self.assertEqual(headers["Location"], "https://example.org/?rafii_ref=AbCdEfGhIj0123456789abcd.20261001")

    def test_session_routes_dispatch_and_keep_the_origin_guard(self):
        with patch.object(service, "enabled", return_value=True):
            status, _, _ = call(self.app, "GET", f"/api/workspaces/{WID}/results/summary", headers=self.guard, query="from=100&to=200")
            self.assertEqual(status, 200)
            self.assertEqual(self.results.calls[-1], ("summary", (WID, "s" * 40, 100.0, 200.0)))
            self.assertEqual(call(self.app, "POST", f"/api/workspaces/{WID}/results/events", body={"type": "lead"}, headers=self.guard)[0], 201)
            self.assertEqual(call(self.app, "POST", f"/api/workspaces/{WID}/results/events", body={"replay": True}, headers=self.guard)[0], 200)
            for path, name in (("events/abc/amend", "amend"), ("events/abc/reverse", "reverse"), ("connections/abc/rotate", "connection_action"),
                               ("links/abc/disable", "link_action")):
                self.assertEqual(call(self.app, "POST", f"/api/workspaces/{WID}/results/{path}", body={}, headers=self.guard)[0], 200, path)
                self.assertEqual(self.results.calls[-1][0], name)
            self.assertEqual(call(self.app, "GET", f"/api/workspaces/{WID}/results/nothing", headers=self.guard)[0], 404)
            self.assertEqual(call(self.app, "GET", f"/api/workspaces/{WID}/results/summary", headers=self.guard, query="from=x")[0], 400)
            # A mutation without the application guard never reaches the service.
            before = len(self.results.calls)
            no_guard = {"HTTP_AUTHORIZATION": TOKEN}
            self.assertEqual(call(self.app, "POST", f"/api/workspaces/{WID}/results/events", body={"type": "lead"}, headers=no_guard)[0], 403)
            self.assertEqual(len(self.results.calls), before)


if __name__ == "__main__":
    unittest.main()
