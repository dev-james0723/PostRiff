"""Offline transport contract tests; recording sockets are not real dispatch evidence."""
import io
import json
import unittest
import uuid
from email.message import Message
from unittest.mock import patch

from postriff_phase2 import model_runtime as runtime, request_capture


class Response(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = self.code = status
        self.reason = "offline-test"
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["x-request-id"] = "req_offline"
        self.headers["Set-Cookie"] = "private-cookie"
        self.headers["Authorization"] = "private-token"
        if 300 <= status < 400:
            self.headers["Location"] = "https://other.invalid/should-never-be-called"

    def info(self):
        return self.headers


class Handle:
    def __init__(self, order, *, authorize_error=None, response_error=None):
        self.physical_attempt_id = str(uuid.uuid4())
        self.order = order
        self.authorize_error = authorize_error
        self.response_error = response_error
        self.responses = []
        self.failures = []

    def authorize_dispatch(self):
        self.order.append("authorize")
        if self.authorize_error:
            raise self.authorize_error

    def record_response(self, raw, status, headers):
        self.order.append("outcome")
        if self.response_error:
            raise self.response_error
        self.responses.append((raw, status, headers))

    def record_failure(self, error_type):
        self.order.append("unknown")
        self.failures.append(error_type)


class CapturedTransport(unittest.TestCase):
    def setUp(self):
        self.order, self.prepared, self.sent, self.handles = [], [], [], []
        self.authorize_error = self.response_error = self.network_error = self.prepare_error = None
        self.raw = json.dumps({"id": "response_offline", "model": "provider/test", "choices": [{"message": {"content": "draft"}}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                               "providerMetadata": {"gateway": {"generationId": "generation_offline", "cost": 0.00001,
                                                                "routing": {"finalProvider": "openai"}}}}).encode()
        self.status = 200
        self.patches = [patch.object(request_capture, "active", return_value=True),
                        patch.object(request_capture, "prepare_request", side_effect=self.prepare),
                        patch.object(runtime.http.client.HTTPSConnection, "request", self.send),
                        patch.object(runtime.http.client.HTTPSConnection, "getresponse", lambda _connection: Response(self.raw, self.status))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.runtime = runtime.ServerModelRuntime("credential-must-never-be-captured", model="openai/gpt-4.1-mini")

    def prepare(self, raw, **metadata):
        self.order.append("prepare")
        self.prepared.append((raw, metadata))
        if self.prepare_error:
            raise self.prepare_error
        handle = Handle(self.order, authorize_error=self.authorize_error, response_error=self.response_error)
        self.handles.append(handle)
        return handle

    def send(self, method, selector, body, headers, *, encode_chunked=False):
        self.order.append("handoff")
        self.sent.append((method, selector, body, headers, encode_chunked))
        if self.network_error:
            raise self.network_error

    def call(self, progress=None, **kwargs):
        return self.runtime._call([{"role": "system", "content": "規則"}, {"role": "user", "content": "idea"},
                                   {"role": "assistant", "content": "previous"}, {"role": "user", "content": "revise"}],
                                  self.runtime.model, progress, attempt=("draft", 1), **kwargs)

    def test_exact_serializer_bytes_order_options_and_same_object_reach_handoff(self):
        progress = {"dispatched": False}
        with patch.object(runtime, "meter_attempt") as meter:
            content, usage = self.call(progress, max_tokens=123)
        raw, metadata = self.prepared[0]
        body = json.loads(raw)
        self.assertIs(raw, self.sent[0][2])
        self.assertEqual(raw, json.dumps(body).encode())
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
        self.assertEqual(body["max_tokens"], 123)
        self.assertEqual(body["providerOptions"], {"gateway": {"only": ["openai"]}})
        self.assertEqual(self.order, ["prepare", "authorize", "handoff", "outcome"])
        self.assertTrue(progress["dispatched"])
        self.assertEqual(metadata["url"], runtime.DEFAULT_ENDPOINT)
        self.assertEqual(self.handles[0].responses[0][0], self.raw)
        self.assertEqual(self.handles[0].responses[0][2]["x-request-id"], "req_offline")
        self.assertNotIn("set-cookie", self.handles[0].responses[0][2])
        self.assertNotIn("authorization", self.handles[0].responses[0][2])
        self.assertNotIn("credential-must-never-be-captured", repr(self.prepared) + repr(self.handles[0].responses))
        self.assertEqual(meter.call_args.kwargs["physical_attempt_id"], self.handles[0].physical_attempt_id)
        self.assertEqual((content, usage["gatewayCost"]), ("draft", 0.00001))
        self.assertIsNone(runtime._CAPTURE_CALL.get())

    def test_each_logical_call_has_a_new_physical_identity_even_for_identical_body(self):
        self.call()
        self.call()
        self.assertEqual(self.prepared[0][0], self.prepared[1][0])
        self.assertNotEqual(self.handles[0].physical_attempt_id, self.handles[1].physical_attempt_id)
        self.assertNotEqual(self.prepared[0][1]["logical_call_id"], self.prepared[1][1]["logical_call_id"])

    def test_prepare_and_authorize_failures_are_known_zero_and_never_metered(self):
        for step in ("prepare_error", "authorize_error"):
            with self.subTest(step=step):
                setattr(self, step, request_capture.AuditCaptureBlocked("offline refusal"))
                progress = {"dispatched": False}
                with patch.object(runtime, "meter_attempt") as meter, self.assertRaises(request_capture.AuditCaptureBlocked):
                    self.call(progress)
                self.assertFalse(progress["dispatched"])
                meter.assert_not_called()
                self.assertEqual(self.sent, [])
                setattr(self, step, None)

    def test_timeout_and_connection_reset_have_one_handoff_unknown_and_no_retry(self):
        for error in (TimeoutError("private details"), ConnectionResetError("private details")):
            with self.subTest(error=type(error).__name__):
                self.network_error = error
                before = len(self.sent)
                progress = {"dispatched": False}
                with self.assertRaises(request_capture.AuditCaptureOutcomeUnknown) as failed:
                    self.call(progress)
                self.assertTrue(progress["dispatched"])
                self.assertEqual(len(self.sent), before + 1)
                self.assertEqual(self.handles[-1].failures, ["URLError"])
                self.assertNotIn("private details", str(failed.exception))

    def test_all_redirects_and_server_error_are_captured_without_second_post(self):
        for status in (301, 302, 303, 307, 308, 500, 503):
            with self.subTest(status=status):
                self.status = status
                before = len(self.sent)
                with self.assertRaises((runtime._Rejected, runtime._Unknown)):
                    self.call()
                self.assertEqual(len(self.sent), before + 1)
                self.assertEqual(self.handles[-1].responses[0][1], status)

    def test_response_persistence_failure_never_returns_draft_or_retries(self):
        self.response_error = request_capture.AuditCaptureOutcomeUnknown("offline unavailable")
        with self.assertRaises(request_capture.AuditCaptureOutcomeUnknown):
            self.call()
        self.assertEqual(len(self.sent), 1)

    def test_response_expiry_failure_is_unknown_after_dispatch(self):
        self.response_error = request_capture.AuditCaptureBlocked("offline expiry")
        with self.assertRaises(request_capture.AuditCaptureOutcomeUnknown):
            self.call()
        self.assertEqual(len(self.sent), 1)

    def test_oversize_response_is_not_truncated_into_a_pass(self):
        self.raw = b"x" * (runtime._CAPTURE_RESPONSE_CAP + 1)
        with self.assertRaises(request_capture.AuditCaptureOutcomeUnknown):
            self.call()
        self.assertEqual(self.handles[0].responses, [])
        self.assertEqual(self.handles[0].failures, ["response_limit_exceeded"])

    def test_unsupported_transport_helper_and_secret_target_never_dispatch(self):
        self.runtime.transport = lambda *args, **kwargs: self.fail("custom transport dispatched")
        with self.assertRaises(request_capture.AuditCaptureBlocked):
            self.call()
        with self.assertRaises(request_capture.AuditCaptureBlocked):
            runtime.model_transport("POST", runtime.DEFAULT_ENDPOINT, body={})
        self.runtime.transport = runtime.model_transport
        self.runtime.endpoint += "?key=credential"
        with self.assertRaises(request_capture.AuditCaptureBlocked):
            self.call()
        self.assertEqual(self.sent, [])

    def test_run_preflight_failure_releases_known_zero(self):
        self.prepare_error = request_capture.AuditCaptureBlocked("offline refusal")
        with self.assertRaises(runtime.ProviderFailure) as failed:
            self.runtime.start_turn({"context": {"providerClass": "cloud", "sources": [], "excluded": [], "candidateOnly": False},
                                     "idea": "A public piano lesson", "destinations": [{"platform": "Threads", "language": "English"}]}, lambda _: None)
        self.assertFalse(failed.exception.dispatched)
        self.assertEqual(failed.exception.cost_usd, 0.0)
        self.assertEqual(self.sent, [])

    def test_blocked_revision_keeps_first_answer_cost_and_never_resends(self):
        payload = json.loads(self.raw)
        payload["choices"][0]["message"]["content"] = json.dumps({"variants": [{"platform": "Threads", "language": "English",
                                                                                "text": "A public piano lesson.", "sourceIds": [],
                                                                                "unknowns": [], "warnings": []}]})
        self.raw = json.dumps(payload).encode()
        original = self.prepare

        def prepare_then_block(raw, **metadata):
            if self.prepared:
                raise request_capture.AuditCaptureBlocked("offline expired before revision")
            return original(raw, **metadata)

        with patch.object(request_capture, "prepare_request", side_effect=prepare_then_block):
            with self.assertRaises(runtime.ProviderFailure) as failed:
                self.runtime.start_turn({"context": {"providerClass": "cloud", "sources": [], "excluded": [], "candidateOnly": False},
                                         "idea": "A public piano lesson", "reasoning": "deep",
                                         "destinations": [{"platform": "Threads", "language": "English"}]}, lambda _: None)
        self.assertTrue(failed.exception.dispatched)
        self.assertEqual(failed.exception.cost_usd, 0.00001)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
