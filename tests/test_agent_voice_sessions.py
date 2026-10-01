"""Browser Live admission and settlement regressions: real module, fake DB/provider, no network."""
import copy
import io
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import config, live
from postriff_phase2.permissions import Membership

PRIVATE = "private-provider-message-and-user-history"
REQUEST_ID = "f" * 32
PROVIDER_REQUEST_ID = "req_" + "a" * 32


class Cursor:
    def __init__(self):
        self.artifact = None
        self.status = None
        self.one = None

    def execute(self, sql, params=None):
        self.one = None
        if sql.startswith(("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ")):
            pass
        elif sql.startswith("SELECT agent_style"):
            self.one = ({},)
        elif sql.startswith("SELECT display_name,locale"):
            self.one = ("James", "en")
        elif sql.startswith("SELECT count(*)"):
            self.one = (0,)
        elif sql.startswith("INSERT INTO public.pr_agent_runs"):
            self.artifact, self.status, self.one = json.loads(params[-1]), "running", ("voice-run",)
        elif sql.startswith("SELECT artifact,idempotency_key"):
            self.one = (copy.deepcopy(self.artifact), "voice:fixture", "owner")
        elif sql.startswith("UPDATE public.pr_agent_runs"):
            self.artifact = json.loads(params[0])
            if "status=%s" in sql:
                self.status = params[1]
        elif sql.startswith("SELECT id::text,artifact") or sql.startswith("SELECT role,body"):
            pass
        else:
            raise AssertionError("Unexpected SQL in voice fixture: " + sql)

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []


class Fixture:
    def __init__(self, transport):
        self.cursor, self.settlements, self.events, self.reservations = Cursor(), [], [], []
        self.clock = 1000.0

        @contextmanager
        def transaction(_token, _workspace):
            yield self.cursor, (), "owner"

        def reserve(*_args, **kwargs):
            self.reservations.append(kwargs)
            return {"reservationId": "reservation"}

        def settle(_cur, _workspace, reservation, state, cost):
            self.settlements.append((reservation, state, cost))

        service = SimpleNamespace(
            repository=SimpleNamespace(transaction=transaction),
            ideas=SimpleNamespace(_member=lambda _: Membership.from_row("owner"), _conversation=lambda *_: None,
                                  _insert_event=lambda *_args: self.events.append(_args[-1])),
            ledger=SimpleNamespace(reserve=reserve, settle=settle))
        cfg = config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "sk-offline-private-placeholder", "RAFII_VOICE_ENABLED": "1",  # pragma: allowlist secret -- synthetic fixture, fake provider only
                                                     "RAFII_AGENT_V2_ENABLED": "1"})
        runtime = SimpleNamespace(service=service, cfg=cfg, clock=lambda: self.clock)
        self.voice = live.VoiceSessions(runtime, transport=transport)

    def start(self, request_id=REQUEST_ID):
        return self.voice.start("workspace", "offline-session", {"sdp": "v=0\r\no=- fixture offer\r\n", "conversationId": "conversation"},
                                request_id=request_id)


def successful_response():
    return {"status": 201, "body": {"session": {"id": "live-fixture"}, "transport": {"type": "webrtc", "sdp": "v=0\r\no=- answer\r\n"}}}


class VoiceAdmissionTests(unittest.TestCase):
    def test_known_refusals_keep_safe_reason_and_release_reserved_spend_at_zero(self):
        for status, code in ((400, "live_rejected"), (401, "live_auth"), (403, "live_forbidden"), (404, "live_rejected"), (429, "live_rejected")):
            with self.subTest(status=status):
                response = {"status": status, "providerRequestId": PROVIDER_REQUEST_ID,
                            "body": {"error": {"code": "model_not_found", "type": "invalid_request_error", "param": "session.model", "message": PRIVATE}}}
                fixture = Fixture(lambda *_args, **_kwargs: response)
                with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
                    fixture.start()
                self.assertEqual((raised.exception.status, raised.exception.code), (502, code))
                self.assertEqual(fixture.settlements, [("reservation", "completed", 0)])
                self.assertEqual(fixture.cursor.status, "failed")
                diagnostic = fixture.cursor.artifact["voice"]["failureDiagnostic"]
                self.assertEqual((diagnostic["upstreamStatus"], diagnostic["errorCode"], diagnostic["errorParam"]),
                                 (status, "model_not_found", "session.model"))
                self.assertEqual((diagnostic["requestId"], diagnostic["providerRequestId"]), (REQUEST_ID, PROVIDER_REQUEST_ID))
                self.assertNotIn(PRIVATE, str(raised.exception) + json.dumps(fixture.cursor.artifact) + " ".join(captured.output))
                self.assertNotIn("sk-offline", " ".join(captured.output))

    def test_429_uses_exact_safe_provider_code_before_suggesting_retry_or_billing(self):
        for provider_code, expected, message in (
            ("credit_balance_exhausted", "live_quota", "billing"),
            ("project_spend_limit_exceeded", "live_quota", "billing"),
            ("organization_usage_limit_exceeded", "live_quota", "billing"),
            ("rate_limit_exceeded", "live_busy", "Try again later"),
            ("slow_down", "live_busy", "Try again later"),
            (None, "live_rejected", "keep typing"),
        ):
            with self.subTest(provider_code=provider_code):
                response = {"status": 429, "body": {"error": {"code": provider_code, "message": PRIVATE}}}
                fixture = Fixture(lambda *_args, **_kwargs: response)
                with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
                    fixture.start()
                self.assertEqual((raised.exception.status, raised.exception.code), (502, expected))
                self.assertIn(message, str(raised.exception))
                self.assertEqual(fixture.settlements, [("reservation", "completed", 0)])
                self.assertNotIn(PRIVATE, str(raised.exception) + " ".join(captured.output))
                if provider_code:
                    self.assertEqual(fixture.cursor.artifact["voice"]["failureDiagnostic"]["errorCode"], provider_code)

    def test_server_failure_keeps_usage_unknown(self):
        fixture = Fixture(lambda *_args, **_kwargs: {"status": 503, "body": {"error": {"code": "server_error"}}})
        with self.assertLogs("rafii.voice", level="WARNING"), self.assertRaises(AlphaError):
            fixture.start()
        self.assertEqual(fixture.settlements, [("reservation", "unknown", None)])
        self.assertIsNone(fixture.cursor.artifact["voice"]["usageSeconds"])

    def test_unexpected_transport_error_also_closes_and_never_exposes_its_message(self):
        def broken(*_args, **_kwargs):
            raise RuntimeError(PRIVATE)
        fixture = Fixture(broken)
        with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
            fixture.start()
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "live_error"))
        self.assertEqual(fixture.settlements, [("reservation", "unknown", None)])
        self.assertEqual(fixture.cursor.status, "failed")
        self.assertNotIn(PRIVATE, str(raised.exception) + " ".join(captured.output))

    def test_malformed_success_and_transport_shapes_close_instead_of_orphaning_session(self):
        invalid = [None, [], "bad", {"status": []}, {"status": True}, {"status": 200, "body": {}},
                   {"status": 201, "body": []}, {"status": 201, "body": {"session": [PRIVATE], "transport": {"sdp": "v=0"}}},
                   {"status": 201, "body": {"session": {"id": "live"}, "transport": [PRIVATE]}},
                   {"status": 201, "body": {"session": {"id": ""}, "transport": {"sdp": "v=0"}}},
                   {"status": 201, "body": {"session": {"id": "live"}, "transport": {"sdp": ""}}}]
        for response in invalid:
            with self.subTest(response=response):
                fixture = Fixture(lambda *_args, **_kwargs: response)
                with self.assertLogs("rafii.voice", level="WARNING"), self.assertRaises(AlphaError) as raised:
                    fixture.start()
                self.assertEqual((raised.exception.status, raised.exception.code), (502, "live_rejected"))
                self.assertEqual((fixture.cursor.status, fixture.cursor.artifact["voice"]["state"]), ("failed", "failed"))
                self.assertEqual(fixture.settlements, [("reservation", "unknown", None)])

    def test_diagnostics_drop_private_fields_unknown_values_and_untrusted_request_ids(self):
        response = {"status": 400, "providerRequestId": "sk-private-placeholder",
                    "body": {"sdp": PRIVATE, "history": PRIVATE, "error": {"code": {"secret": PRIVATE}, "type": PRIVATE, "param": PRIVATE, "message": PRIVATE}}}
        fixture = Fixture(lambda *_args, **_kwargs: response)
        with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError):
            fixture.start(request_id=PRIVATE)
        diagnostic = fixture.cursor.artifact["voice"]["failureDiagnostic"]
        self.assertEqual({diagnostic[k] for k in ("errorCode", "errorType", "errorParam")}, {"other"})
        self.assertNotIn("requestId", diagnostic)
        self.assertNotIn("providerRequestId", diagnostic)
        output = json.dumps(diagnostic) + " ".join(captured.output)
        self.assertNotIn(PRIVATE, output)
        self.assertNotIn("sk-private", output)

    def test_provider_request_ids_accept_only_opaque_hex_shape(self):
        self.assertEqual(live.creation_diagnostic(provider_request_id=PROVIDER_REQUEST_ID)["providerRequestId"], PROVIDER_REQUEST_ID)
        invalid = ["req_james_au_phone_14155550111", "req_" + "g" * 32, "req_" + "A" * 32,
                   "req_" + "a" * 31, "req_" + "a" * 33, PROVIDER_REQUEST_ID + "\n", PRIVATE, None, [PRIVATE]]
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                self.assertNotIn("providerRequestId", live.creation_diagnostic(provider_request_id=value))

    def test_configuration_failure_after_reservation_closes_with_unknown_usage(self):
        calls = []
        fixture = Fixture(lambda *_args, **_kwargs: calls.append("provider"))
        original = RuntimeError(PRIVATE)
        with patch.object(live, "session_config", side_effect=original), self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
            fixture.start()
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "live_error"))
        self.assertIs(raised.exception.__cause__, original)
        self.assertEqual(calls, [])
        self.assertEqual(fixture.settlements, [("reservation", "unknown", None)])
        self.assertEqual(fixture.cursor.status, "failed")
        self.assertEqual(fixture.cursor.artifact["voice"]["failureDiagnostic"]["phase"], "live_config")
        self.assertNotIn(PRIVATE, str(raised.exception) + " ".join(captured.output))

    def test_persistence_failure_after_admission_closes_with_unknown_usage(self):
        fixture = Fixture(lambda *_args, **_kwargs: successful_response())
        original = RuntimeError(PRIVATE)
        # The original failure happens after the live row save; allow the later failed event to persist.
        def persist_event(*args):
            if args[-1].get("type") == "run.started":
                raise original
            fixture.events.append(args[-1])
        fixture.voice.service.ideas._insert_event = persist_event
        with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
            fixture.start()
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "live_error"))
        self.assertIs(raised.exception.__cause__, original)
        self.assertEqual(fixture.settlements, [("reservation", "unknown", None)])
        self.assertEqual(fixture.cursor.status, "failed")
        self.assertEqual(fixture.cursor.artifact["voice"]["failureDiagnostic"]["upstreamStatus"], 201)
        self.assertEqual(fixture.cursor.artifact["voice"]["failureDiagnostic"]["phase"], "live_persist")
        self.assertNotIn(PRIVATE, str(raised.exception) + " ".join(captured.output))

    def test_admitted_persistence_and_cleanup_failure_retains_original_cause_and_safe_log(self):
        fixture = Fixture(lambda *_args, **_kwargs: successful_response())
        transaction = fixture.voice.service.repository.transaction
        calls = []
        original = RuntimeError(PRIVATE)
        @contextmanager
        def unavailable_after_admission(*args):
            calls.append("transaction")
            if len(calls) == 2:
                raise original
            if len(calls) == 3:
                raise ValueError("private-cleanup-failure")
            with transaction(*args) as value:
                yield value
        fixture.voice.service.repository.transaction = unavailable_after_admission
        with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
            fixture.start()
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "live_error"))
        self.assertIs(raised.exception.__cause__, original)
        self.assertEqual(len(calls), 3)
        self.assertEqual(fixture.settlements, [])  # unavailable DB cannot honestly record settlement
        output = " ".join(captured.output)
        self.assertIn("rafii.voice.start.cleanup.failed", output)
        self.assertIn('"upstreamStatus": 201', output)
        self.assertNotIn(PRIVATE, str(raised.exception) + output)
        self.assertNotIn("private-cleanup-failure", output)

    def test_cleanup_failure_preserves_original_safe_error_and_does_not_retry(self):
        original = AlphaError("The voice service did not answer.", 503, code="live_unreachable")
        fixture = Fixture(lambda *_args, **_kwargs: (_ for _ in ()).throw(original))
        transaction = fixture.voice.service.repository.transaction
        calls = []
        @contextmanager
        def unavailable_after_reservation(*args):
            calls.append("transaction")
            if len(calls) > 1:
                raise RuntimeError(PRIVATE)
            with transaction(*args) as value:
                yield value
        fixture.voice.service.repository.transaction = unavailable_after_reservation
        with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
            fixture.start()
        self.assertIs(raised.exception, original)
        self.assertEqual(len(calls), 2)
        self.assertIn("rafii.voice.start.cleanup.failed", " ".join(captured.output))
        self.assertNotIn(PRIVATE, str(raised.exception) + " ".join(captured.output))

    def test_ordinary_end_preserves_server_clock_billing_and_is_idempotent(self):
        fixture = Fixture(lambda *_args, **_kwargs: successful_response())
        started = fixture.start()
        fixture.clock += 10
        first = fixture.voice.end("workspace", "offline-session", started["voiceSessionId"], {"reason": "user_ended", "usageSeconds": 0})
        second = fixture.voice.end("workspace", "offline-session", started["voiceSessionId"], {"reason": "error", "usageSeconds": 900})
        self.assertEqual(first["usageSeconds"], 25)
        self.assertEqual(fixture.settlements, [("reservation", "completed", 20834)])
        self.assertEqual(second["note"], "Already ended.")
        self.assertEqual(fixture.cursor.artifact["voice"]["reason"], "user_ended")


class VoiceTransportTests(unittest.TestCase):
    def invoke(self, status, raw):
        headers = {"x-request-id": PROVIDER_REQUEST_ID}
        if status >= 400:
            error = HTTPError(live.LIVE_ENDPOINT, status, PRIVATE, headers, io.BytesIO(raw))
            opener = SimpleNamespace(open=lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
        else:
            response = SimpleNamespace(status=status, headers=headers, read=lambda _: raw)
            class Open:
                def __enter__(self): return response
                def __exit__(self, *_): return False
            opener = SimpleNamespace(open=lambda *_args, **_kwargs: Open())
        with patch("urllib.request.build_opener", return_value=opener):
            return live.live_transport("POST", live.LIVE_ENDPOINT, headers={"Authorization": "Bearer offline-placeholder"}, body={})

    def test_http_error_preserves_status_and_provider_correlation_for_safe_classification(self):
        result = self.invoke(403, json.dumps({"error": {"code": "permission_denied", "param": "session.model", "message": PRIVATE}}).encode())
        self.assertEqual(result["status"], 403)
        self.assertEqual(result["providerRequestId"], PROVIDER_REQUEST_ID)

    def test_unreadable_refusal_is_known_zero_but_unreadable_success_is_unknown(self):
        for status, expected in ((401, ("completed", 0)), (201, ("unknown", None)), (500, ("unknown", None))):
            with self.subTest(status=status):
                fixture = Fixture(lambda *_args, **_kwargs: self.invoke(status, b"<html>private-provider-message-and-user-history</html>"))
                with self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
                    fixture.start()
                self.assertEqual((raised.exception.status, raised.exception.code), (502, "live_unreadable"))
                self.assertEqual(fixture.settlements, [("reservation", *expected)])
                self.assertEqual(fixture.cursor.artifact["voice"]["failureDiagnostic"]["upstreamStatus"], status)
                self.assertNotIn(PRIVATE, " ".join(captured.output))

    def test_network_failure_closes_session_with_unknown_usage(self):
        opener = SimpleNamespace(open=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError(PRIVATE)))
        fixture = Fixture(live.live_transport)
        with patch("urllib.request.build_opener", return_value=opener), self.assertLogs("rafii.voice", level="WARNING") as captured, self.assertRaises(AlphaError) as raised:
            fixture.start()
        self.assertEqual((raised.exception.status, raised.exception.code), (503, "live_unreachable"))
        self.assertEqual(fixture.settlements, [("reservation", "unknown", None)])
        self.assertNotIn(PRIVATE, " ".join(captured.output))


if __name__ == "__main__":
    unittest.main()
