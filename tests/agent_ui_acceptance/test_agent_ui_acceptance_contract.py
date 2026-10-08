"""Lane G — contract-layer negatives against the frozen A seam (no DB, no network, no Agents SDK).

Independent of the lanes: these exercise exactly the code every request passes before any lane runs — request validators,
the UI kill switch and body cap in ui_http, SSE framing with fragmented UTF-8, result constructors that can never claim a
business effect, the parser-seam client (forged/skewed validator answers), migration 102's privacy and uniqueness rules, and
the evidence redaction every G writer uses. Corpus items: NC01, NC03, NC12, NC14, NC15, NC23 (tests/agent_ui_acceptance/corpus.py).
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import ui_contracts as c
from postriff_phase2.agent_runtime_v2 import ui_http, ui_validator

from agent_ui_acceptance import corpus, redaction
from agent_ui_acceptance.sse import SseReader, parse_all

ROOT = Path(__file__).resolve().parents[2]
UUID = "6c1f2f3e-1111-4222-8333-944455556666"
OTHER = "0d6c2b9e-2222-4333-8444-a55566667777"
KEY = "g-acceptance-key-0001"
PRIVILEGE_KEYS = ("principal", "workspaceId", "isFounder", "scope", "role", "verified", "manifest", "effect", "permissionRevision", "approvedRefs",
                  "actionTargets", "proposalDigests", "patchSource", "__proto__", "constructor")


def raises(test, fn, status=None, code=None):
    with test.assertRaises(AlphaError) as caught:
        fn()
    if status is not None:
        test.assertEqual(caught.exception.status, status, str(caught.exception))
    if code is not None:
        test.assertEqual(caught.exception.code, code, str(caught.exception))
    return caught.exception


class Requests(unittest.TestCase):
    BASES = {
        "presentation": (c.validate_presentation_request, {"parentRunId": UUID, "idempotencyKey": KEY}),
        "query": (c.validate_query, {"artifactId": UUID, "bindingId": "drafts_list"}),
        "activation": (c.validate_activation, {"artifactId": UUID, "actionId": "draft_edit", "inputs": {}}),
        "action": (c.validate_action, {"artifactId": UUID, "actionId": "draft_edit", "idempotencyKey": KEY, "activationId": "act_" + "a" * 40}),
        "edit": (c.validate_patch, {"baseRevision": 1, "baseSourceHash": "a" * 64, "instruction": "add a chart", "idempotencyKey": KEY}),
        "state": (c.validate_state_patch, {"expectedStateRevision": 0, "patch": {}}),
        "uiContext": (c.validate_ui_context, {"artifactId": UUID}),
    }

    def test_baselines_are_accepted(self):
        for name, (validate, body) in self.BASES.items():
            with self.subTest(name):
                self.assertIsInstance(validate(dict(body)), dict)

    def test_privilege_keys_refused_everywhere(self):
        """NC01/NC03: a client can never supply its principal, scope, founder status, role, manifest, verified flag or DSL."""
        for name, (validate, body) in self.BASES.items():
            for key in PRIVILEGE_KEYS:
                with self.subTest(route=name, key=key):
                    raises(self, lambda: validate({**body, key: True}), 400, "ui_unknown_field")

    def test_founder_surface_is_not_a_consumer_choice(self):
        raises(self, lambda: c.validate_presentation_request({"parentRunId": UUID, "idempotencyKey": KEY, "surface": "founder"}), 400, "ui_surface")

    def test_ids_are_opaque_server_identifiers(self):
        for bad in ("../" + UUID, UUID + "' or 1=1", "", 7, UUID.upper() + "x", "00000000-0000-0000-0000-00000000000g"):
            with self.subTest(bad=bad):
                raises(self, lambda: c.validate_query({"artifactId": bad, "bindingId": "drafts_list"}), 404)
        # Absent (null) is a missing field, refused before any shape check — still never a lookup.
        raises(self, lambda: c.validate_query({"artifactId": None, "bindingId": "drafts_list"}), 400, "ui_missing_field")
        for bad in ("Query", "drafts list", "x", "a" * 70, "__proto__", "constructor()", "schedule.apply", "DROP TABLE"):
            with self.subTest(binding=bad):
                raises(self, lambda: c.validate_query({"artifactId": UUID, "bindingId": bad}), 404, "ui_binding")
        for bad in ("short", "k" * 81, "has space key 00000", "émoji-key-00000000"):
            with self.subTest(key=bad):
                raises(self, lambda: c.validate_action({"artifactId": UUID, "actionId": "draft_edit", "idempotencyKey": bad,
                                                        "activationId": "act_" + "a" * 40}), 400, "ui_idempotency_key")
        for bad in ("act_short", "nope", "act_" + "a" * 65, "act_" + "a" * 39 + "!"):
            with self.subTest(activation=bad):
                raises(self, lambda: c.validate_action({"artifactId": UUID, "actionId": "draft_edit", "idempotencyKey": KEY, "activationId": bad}), 409,
                       "ui_activation")

    def test_bounds_before_parsing(self):
        """NC14: inputs, depth, instruction and saved state are bounded by the contract before any lane sees them."""
        raises(self, lambda: c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "inputs": {"q": "x" * (c.BOUNDS["inputBytes"] + 1)}}), 413)
        deep = cursor = {}
        for _ in range(c.BOUNDS["inputDepth"] + 2):
            cursor["a"] = {}
            cursor = cursor["a"]
        raises(self, lambda: c.validate_activation({"artifactId": UUID, "actionId": "draft_edit", "inputs": deep}), 400, "ui_input_depth")
        for number in (float("nan"), float("inf"), 2 ** 60):
            with self.subTest(number=number):
                raises(self, lambda: c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "inputs": {"n": number}}), 400, "ui_input_number")
        raises(self, lambda: c.validate_patch({**self.BASES["edit"][1], "instruction": "x" * 2001}), 400, "ui_instruction")
        raises(self, lambda: c.validate_patch({**self.BASES["edit"][1], "instruction": "   "}), 400, "ui_instruction")
        raises(self, lambda: c.validate_state_patch({"expectedStateRevision": 0, "patch": {"f": "x" * c.BOUNDS["stateBytes"]}}), 413, "ui_state_too_large")
        raises(self, lambda: c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "cursor": "c" * 513}), 400, "ui_cursor")
        raises(self, lambda: c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "artifactRevision": -1}), 400, "ui_revision")
        raises(self, lambda: c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "artifactRevision": True}), 400, "ui_revision")

    def test_input_digest_binds_exact_inputs(self):
        a = c.input_digest("draft_edit", {"draftId": "d1", "text": "Hello"})
        self.assertEqual(a, c.input_digest("draft_edit", {"text": "Hello", "draftId": "d1"}))   # key order is not meaning
        self.assertNotEqual(a, c.input_digest("draft_edit", {"draftId": "d1", "text": "Hello "}))
        self.assertNotEqual(a, c.input_digest("draft_rewrite", {"draftId": "d1", "text": "Hello"}))
        self.assertEqual(c.input_digest("x_y", {"n": 1.0}), c.input_digest("x_y", {"n": 1}))


class FakeApp:
    """The two HostedApplication helpers ui_http uses; `_body` refuses to run when the outer cap must have fired first."""

    def __init__(self, body=None, forbid_body=False):
        self.body, self.forbid_body, self.responses = body or {}, forbid_body, []

    def _body(self, environ):
        if self.forbid_body:
            raise AssertionError("the body was parsed although the request should have been refused first")
        return dict(self.body)

    def _json(self, start_response, status, body, extra_headers=None):
        self.responses.append((status, body))
        return [json.dumps(body).encode()]

    def _query_int(self, environ, key, default=0):
        raw = (environ.get("QUERY_STRING") or "").partition(f"{key}=")[2].split("&")[0]
        return int(raw) if raw.isdigit() else default


class FakeCfg:
    def __init__(self, enabled=False, actions=False, edits=False):
        self.flags = {"enabled": enabled, "actions": enabled and actions, "edits": enabled and edits, "canary": False}

    def genui_for(self, workspace_id, founder=False):
        return dict(self.flags)


class FakeRuntime:
    def __init__(self, **flags):
        self.cfg = FakeCfg(**flags)


def route(runtime, method, rest, app=None, environ=None):
    return ui_http.handle(app or FakeApp(), environ or {"CONTENT_LENGTH": "2"}, lambda *a: None, runtime, "dev:" + UUID, method, OTHER, rest)


class KillSwitch(unittest.TestCase):
    """G23 (contract part): with RAFII_GENUI_ENABLED off nothing generates, reads new data or writes — before any body parsing."""

    def test_disabled_refuses_generation_queries_and_actions_before_parsing(self):
        runtime = FakeRuntime(enabled=False)
        for method, rest in (("POST", ["presentations"]), ("POST", ["queries"]), ("POST", ["actions", "activate"]), ("POST", ["actions"]),
                             ("POST", ["presentations", UUID, "edits"])):
            with self.subTest(rest=rest):
                raises(self, lambda: route(runtime, method, rest, FakeApp(forbid_body=True)), 404, "ui_disabled")

    def test_actions_and_edits_have_their_own_switches(self):
        runtime = FakeRuntime(enabled=True, actions=False, edits=False)
        raises(self, lambda: route(runtime, "POST", ["actions", "activate"], FakeApp(forbid_body=True)), 404, "ui_disabled")
        raises(self, lambda: route(runtime, "POST", ["actions"], FakeApp(forbid_body=True)), 404, "ui_disabled")
        raises(self, lambda: route(runtime, "POST", ["presentations", UUID, "edits"], FakeApp(forbid_body=True)), 404, "ui_disabled")

    def test_disabled_still_serves_persisted_artifacts_read_only(self):
        """Old messages keep their native fallback while the switch is off (snapshot/by-message/replay are not generation)."""
        from postriff_phase2.agent_runtime_v2 import ui_store, ui_stream
        runtime = FakeRuntime(enabled=False)
        with mock.patch.object(ui_store, "snapshot_http", return_value={"artifact": None}) as snapshot, \
                mock.patch.object(ui_store, "by_message_http", return_value={"artifacts": []}) as by_message, \
                mock.patch.object(ui_stream, "replay", return_value=[b""]) as replay:
            route(runtime, "GET", ["presentations", UUID])
            route(runtime, "GET", ["messages", UUID])
            route(runtime, "GET", ["presentations", UUID, "events"], environ={"QUERY_STRING": "after=3", "HTTP_LAST_EVENT_ID": f"{UUID}:9"})
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual(by_message.call_count, 1)
        self.assertEqual(replay.call_args.args[-1], 9, "Last-Event-ID wins when it is later than ?after=")

    def test_outer_body_cap_fires_before_json_parsing(self):
        runtime = FakeRuntime(enabled=True, actions=True, edits=True)
        environ = {"CONTENT_LENGTH": str(c.BOUNDS["requestBodyBytes"] + 1)}
        for rest in (["presentations"], ["queries"], ["actions", "activate"], ["actions"]):
            with self.subTest(rest=rest):
                raises(self, lambda: route(runtime, "POST", rest, FakeApp(forbid_body=True), environ), 413, "ui_body_too_large")

    def test_unknown_routes_and_methods_are_404(self):
        runtime = FakeRuntime(enabled=True, actions=True, edits=True)
        for method, rest in (("GET", ["queries"]), ("DELETE", ["presentations", UUID]), ("POST", ["tools", "call"]), ("POST", ["actions", "execute"]),
                             ("GET", ["presentations", "not-a-uuid"]), ("POST", ["mutations"]), ("GET", ["messages", "../etc"])):
            with self.subTest(method=method, rest=rest):
                raises(self, lambda: route(runtime, method, rest, FakeApp(forbid_body=True)), 404)


EVENT_TEXTS = ("progressive 中文 rendering", "Cantonese 廣東話 and 普通话", "emoji 🎹🎶 and ZWJ 👩‍💻", "combining é and ñ", "RTL مرحبا", "plain ascii")


class Framing(unittest.TestCase):
    def events(self):
        out = []
        for seq, text in enumerate(EVENT_TEXTS, start=1):
            kind = "ui.delta" if seq < len(EVENT_TEXTS) else "ui.ready"
            out.append(c.make_event(UUID, OTHER, 1, seq, kind, {"text": text, "offset": seq * 10}))
        return out

    def test_fragmented_utf8_frames(self):
        """NC15: every byte offset of a multi-byte stream (CJK, emoji, ZWJ, RTL) decodes to the same events; no decode error."""
        events = self.events()
        raw = b"".join(c.sse_frame(e) for e in events)
        whole = parse_all(raw)
        self.assertEqual([e["data"] for e in whole.events], events)
        for cut in range(1, len(raw)):
            reader = parse_all(raw, split_at=[cut])
            self.assertEqual(len(reader.events), len(events), cut)
            self.assertEqual(reader.events[-1]["data"]["kind"], "ui.ready")
            self.assertEqual(reader.decode_errors, 0)
        # Three-way splits inside every multi-byte character of one frame.
        frame = c.sse_frame(events[2])
        offsets = [i for i in range(1, len(frame)) if (frame[i] & 0xC0) == 0x80]
        for cut in offsets:
            reader = parse_all(frame, split_at=[cut - 1, cut, cut + 1])
            self.assertEqual(reader.events[0]["data"]["payload"]["text"], EVENT_TEXTS[2])

    def test_frame_shape(self):
        event = c.make_event(UUID, None, 0, 5, "ui.heartbeat", {"note": "line one\nline two"})
        frame = c.sse_frame(event, retry_ms=2000).decode()
        lines = frame.split("\n")
        self.assertEqual(lines[0], "retry: 2000")
        self.assertEqual(lines[1], f"id: {UUID}:5")
        self.assertEqual(lines[2], "event: ui.heartbeat")
        self.assertTrue(lines[3].startswith("data: {"))
        self.assertEqual(frame.count("\ndata: "), 1, "a payload newline must stay inside one JSON data line")
        self.assertTrue(frame.endswith("\n\n"))
        self.assertEqual(c.parse_event_id(f"{UUID}:5"), 5)
        for bad in ("5", f"{UUID}:", f"{UUID}:-1", f"{UUID}:1e3", f"{UUID}:" + "9" * 10, None, 5):
            self.assertIsNone(c.parse_event_id(bad), bad)
        self.assertEqual(dict(c.SSE_HEADERS)["Cache-Control"], "no-store, no-transform")
        self.assertNotIn("Content-Length", dict(c.SSE_HEADERS))

    def test_unknown_event_kinds_cannot_be_framed(self):
        for kind in ("ui.mutation", "action.applied", "run.completed", ""):
            with self.assertRaises(ValueError):
                c.make_event(UUID, None, 0, 1, kind)


class Results(unittest.TestCase):
    def test_prepared_never_verified(self):
        """NC23: only an applied action can be verified; prepared/pending/conflict/rejected/failed cannot pose as success."""
        for outcome in c.ACTION_OUTCOMES:
            if outcome == "applied":
                self.assertTrue(c.action_result("a_b", KEY, outcome, verified=True)["verified"])
                continue
            with self.subTest(outcome=outcome):
                with self.assertRaises(ValueError):
                    c.action_result("a_b", KEY, outcome, verified=True)
                self.assertFalse(c.action_result("a_b", KEY, outcome)["verified"])
        with self.assertRaises(ValueError):
            c.action_result("a_b", KEY, "done")

    def test_unknown_is_never_zero(self):
        for state in ("unavailable", "denied", "loading"):
            result = c.query_result(state, data={"total": 0}, known=None, total=None)
            self.assertIsNone(result["data"], state)
            self.assertIsNone(result["coverage"]["known"])
        partial = c.query_result("partial", data={"rows": []}, known=3, total=None, note="2 platforms have no history")
        self.assertEqual(partial["coverage"], {"known": 3, "total": None, "note": "2 platforms have no history"})
        with self.assertRaises(ValueError):
            c.query_result("zero")

    def test_public_artifact_hides_server_only_and_untrusted_source(self):
        record = {k: None for k in c.PUBLIC_ARTIFACT_KEYS}
        record.update({"artifactId": UUID, "generationState": "streaming", "validationState": "pending", "canonicalSource": "root = RafiiRoot([])",
                       "safeState": None, **{k: "secret-" + k for k in c.SERVER_ONLY_MANIFEST_KEYS}})
        public = c.public_artifact(record)
        self.assertIsNone(public["canonicalSource"], "untrusted/unfinished source is never handed out as canonical")
        self.assertEqual(set(public), set(c.PUBLIC_ARTIFACT_KEYS))
        for key in c.SERVER_ONLY_MANIFEST_KEYS:
            self.assertNotIn(key, public)
        self.assertEqual(public["safeState"], {})
        manifest = c.public_manifest({"manifestId": "m", "bindingVersion": 1, "queries": [{"name": "drafts_list", "constraints": "secret", "sql": "select"}],
                                      "actions": [{"actionId": "draft_edit", "label": "Edit", "effect": "MUTATE_REVERSIBLE", "target": "draft:1",
                                                   "proposalDigest": "d" * 64}], "principal": UUID, "approvedRefs": ["x"]})
        self.assertNotIn("principal", manifest)
        self.assertNotIn("approvedRefs", manifest)
        self.assertNotIn("sql", manifest["queries"][0])
        self.assertNotIn("target", manifest["actions"][0])
        self.assertNotIn("proposalDigest", manifest["actions"][0])

    def test_state_machine(self):
        for state in c.TERMINAL_GENERATION_STATES:
            for nxt in c.GENERATION_STATES:
                self.assertFalse(c.can_transition(state, nxt), (state, nxt))
        raises(self, lambda: c.require_transition("ready", "streaming"), 409, "ui_state_transition")
        self.assertTrue(c.can_transition("validating", "ready"))
        self.assertFalse(c.can_transition("streaming", "ready"), "a stream cannot become ready without validation")
        self.assertFalse(c.can_transition("queued", "ready"))


class Transport:
    def __init__(self, status=200, answer=None, raise_error=None):
        self.status, self.answer, self.raise_error, self.calls = status, answer, raise_error, []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": dict(headers), "timeout": timeout})
        if self.raise_error:
            raise self.raise_error
        return self.status, json.dumps(self.answer).encode() if self.answer is not None else b"not json"


SECRET = "s" * 40
VALUES = {"RAFII_GENUI_VALIDATOR_SECRET": SECRET, "RAFII_GENUI_VALIDATOR_URL": "http://127.0.0.1:4539"}
LIB = "b" * 64
SRC = "root = RafiiRoot([])"


def accepted(source=SRC, **over):
    return {"accepted": True, "canonicalSource": source, "sourceHash": hashlib.sha256(source.encode()).hexdigest(), "statementCount": 1, "queryNames": [],
            "actionIds": [], "componentNames": ["RafiiRoot"], "errors": [], "libraryHash": LIB, "libraryVersion": "0.3.2", **over}


def validate(transport, candidate=SRC, mode="generate", base=None, values=VALUES):
    return ui_validator.validate_and_merge_ui(base, candidate, LIB, mode, policy={"rootName": "RafiiRoot", "allowedComponents": ["RafiiRoot"], "readBindings": [],
                                                                                 "actionIds": []},
                                              scope={"workspaceId": UUID, "artifactId": OTHER, "attemptId": UUID}, transport=transport, values=values,
                                              clock=lambda: 1_790_000_000)


class ValidatorSeam(unittest.TestCase):
    """The Python side of the parser seam trusts nothing it can't re-check (forged/skewed answers, no retries, bounded)."""

    def test_accepts_only_a_self_consistent_answer(self):
        transport = Transport(answer=accepted())
        result = validate(transport)
        self.assertTrue(result["accepted"])
        self.assertEqual(len(transport.calls), 1)

    def test_forged_hash_or_library_skew_is_rejected(self):
        for answer in (accepted(sourceHash="0" * 64), accepted(libraryHash="c" * 64), accepted(canonicalSource=None), accepted(canonicalSource="x" * (c.BOUNDS["sourceBytes"] + 1))):
            with self.subTest(answer={k: (v if not isinstance(v, str) else v[:12]) for k, v in answer.items()}):
                result = validate(Transport(answer=answer))
                self.assertFalse(result["accepted"])
                self.assertIsNone(result["canonicalSource"])

    def test_unavailable_seam_is_never_accepted_and_never_retried(self):
        for transport in (Transport(status=500, answer=accepted()), Transport(status=401, answer={"accepted": True}), Transport(answer=None),
                          Transport(raise_error=TimeoutError()), Transport(raise_error=OSError("refused")), Transport(answer=["accepted"])):
            with self.subTest(status=transport.status, error=type(transport.raise_error).__name__):
                result = validate(transport)
                self.assertFalse(result["accepted"])
                self.assertEqual(result["errors"], ["validation_unavailable"])
                self.assertEqual(len(transport.calls), 1, "no hidden retries")

    def test_refusals_before_any_network(self):
        for values in ({}, {**VALUES, "RAFII_GENUI_VALIDATOR_SECRET": "short"}, {"RAFII_GENUI_VALIDATOR_SECRET": SECRET}):
            transport = Transport(answer=accepted())
            self.assertEqual(validate(transport, values=values)["errors"], ["validation_unavailable"])
            self.assertEqual(transport.calls, [])
        transport = Transport(answer=accepted())
        self.assertEqual(validate(transport, candidate="x" * (c.BOUNDS["sourceBytes"] + 1))["errors"], ["source_too_large"])
        self.assertEqual(validate(transport, candidate="x" * (c.BOUNDS["patchBytes"] + 1), mode="patch", base=SRC)["errors"], ["source_too_large"])
        self.assertEqual(validate(transport, mode="patch", base=None)["errors"], ["missing_base"])
        self.assertEqual(transport.calls, [])
        with self.assertRaises(ValueError):
            validate(transport, mode="execute")

    def test_signature_binds_timestamp_and_body(self):
        transport = Transport(answer=accepted())
        validate(transport)
        call = transport.calls[0]
        stamp = call["headers"]["X-Rafii-Validator-Timestamp"]
        expected = hmac.new(SECRET.encode(), f"v1\n{stamp}\n{hashlib.sha256(call['body']).hexdigest()}".encode(), hashlib.sha256).hexdigest()
        self.assertEqual(call["headers"]["X-Rafii-Validator-Signature"], expected)
        self.assertNotEqual(ui_validator.sign(SECRET, stamp, call["body"] + b" "), expected)
        self.assertEqual(call["url"], "http://127.0.0.1:4539/internal/agent-ui/validate")
        self.assertEqual(call["timeout"], float(c.BOUNDS["validatorTimeoutSeconds"]))
        payload = json.loads(call["body"])
        self.assertEqual(payload["scope"]["artifactId"], OTHER)
        self.assertNotIn(SECRET, call["body"].decode())

    def test_rejections_are_bounded_codes(self):
        result = validate(Transport(answer={"accepted": False, "errors": ["x" * 500] * 50}))
        self.assertFalse(result["accepted"])
        self.assertLessEqual(len(result["errors"]), 20)
        self.assertTrue(all(len(e) <= 120 for e in result["errors"]))

    def test_target_precedence_and_bypass_header(self):
        self.assertEqual(ui_validator.target({"RAFII_WEB_INTERNAL_URL": "http://a/", "RAFII_GENUI_VALIDATOR_URL": "http://b"})[0],
                         "http://a/internal/agent-ui/validate")
        url, headers = ui_validator.target({"VERCEL_URL": "x.vercel.app"})
        self.assertEqual((url, headers), ("https://x.vercel.app/internal/agent-ui/validate", {}))
        _, headers = ui_validator.target({"VERCEL_URL": "x.vercel.app", "VERCEL_AUTOMATION_BYPASS_SECRET": "bypass"})
        self.assertIn("x-vercel-protection-bypass", headers)
        self.assertEqual(ui_validator.target({}), (None, {}))


MIGRATION = ROOT / "migrations/postriff/102_agent_ui_artifacts.sql"
UI_TABLES = ("pr_ui_artifacts", "pr_ui_revisions", "pr_ui_attempts", "pr_ui_events", "pr_ui_actions", "pr_ui_activations")


class Migration(unittest.TestCase):
    """G22 (static part) and the storage privacy rule (R4): additive, service-only, uniqueness in the database."""

    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.code = re.sub(r"--[^\n]*", "", cls.sql).lower()

    def test_additive_only(self):
        for verb in (r"\bdrop\s+(table|column|index|policy|schema|function)", r"\btruncate\b", r"\bdelete\s+from\b", r"\balter\s+table\s+\S+\s+drop\b",
                     r"\bupdate\s+public\.", r"\brename\b"):
            self.assertIsNone(re.search(verb, self.code), verb)
        for table in UI_TABLES:
            self.assertIn(f"create table if not exists public.{table}", self.code)

    def test_service_only_rls_on_every_table(self):
        self.assertIn("enable row level security", self.code)
        self.assertIn("force row level security", self.code)
        self.assertIn("revoke all on public.%i from public, anon, authenticated", self.code)
        self.assertIn("for all to service_role using (true) with check (true)", self.code)
        listed = re.search(r"foreach t in array array\[([^\]]+)\]", self.code).group(1)
        self.assertEqual(sorted(re.findall(r"'([a-z_]+)'", listed)), sorted(UI_TABLES))
        self.assertNotIn("to authenticated", self.code.replace("from public, anon, authenticated", ""))

    def test_uniqueness_lives_in_the_database(self):
        self.assertRegex(self.code, r"create unique index if not exists pr_ui_attempts_one_producer\s+on public\.pr_ui_attempts \(artifact_id, target_revision\)\s+"
                                    r"where state in \('queued','streaming','validating'\)")
        self.assertIn("unique (workspace_id, idempotency_key)", self.code)
        self.assertIn("primary key (workspace_id, idempotency_key)", self.code)
        self.assertIn("unique (workspace_id, parent_run_id, slot)", self.code)
        self.assertIn("primary key (artifact_id, seq)", self.code)
        self.assertIn("primary key (artifact_id, revision)", self.code)

    def test_checks_match_the_contract(self):
        def listed(column):
            match = re.search(column + r"[^\n]*?\n?\s*check \(" + r"[a-z_]+ in \(([^)]*)\)\)", self.code)
            self.assertIsNotNone(match, column)
            return tuple(re.findall(r"'([a-z_.]+)'", match.group(1)))
        self.assertEqual(listed(r"generation_state text not null default 'queued'"), c.GENERATION_STATES)
        self.assertEqual(listed(r"validation_state text not null default 'pending'"), c.VALIDATION_STATES)
        self.assertEqual(listed(r"surface text not null"), c.UI_SURFACES)
        self.assertEqual(listed(r"kind text not null"), c.REVISION_KINDS)
        self.assertIn("provider_attempts between 0 and %d" % c.BOUNDS["providerAttempts"], self.code)
        self.assertIn("octet_length(safe_state::text) <= %d" % c.BOUNDS["stateBytes"], self.code)
        self.assertIn("octet_length(source) <= %d" % c.BOUNDS["sourceBytes"], self.code)
        self.assertIn("octet_length(checkpoint_source) <= %d" % c.BOUNDS["sourceBytes"], self.code)
        for kind in c.EVENT_KINDS:
            self.assertIn(f"'{kind}'", self.code)
        self.assertIn("cost_state in ('none','known','unknown','estimated')", self.code)


class Privacy(unittest.TestCase):
    def test_redaction_scanner(self):
        """NC12 (evidence side): secrets, sessions, signed URLs and DSL never reach a public evidence file."""
        dirty = {"headers": {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"},
                 "note": "key sk-proj-ABCDEFGHIJKLMNOPQRSTUV and https://x.supabase.co/storage/v1/object/sign/b/p?token=abcdefghijk",
                 "log": "root = RafiiRoot([t])\nt = ToolBoundTable(q)", "cookie": "__Host-rafii-control=abcdefghijklmnop",
                 "dsn": "postgresql://postgres:hunter2pass@db.example:6543/postgres", "nested": [{"canonicalSource": "root = RafiiRoot([])"}]}
        kinds = {f["kind"] for f in redaction.scan(dirty)}
        for kind in ("sensitive_key", "openai_key", "signed_url", "supabase_storage", "dsl_source", "dsn_password"):
            self.assertIn(kind, kinds)
        with self.assertRaises(ValueError):
            redaction.assert_clean(dirty)
        clean = {"gate": "G06", "sourceHash": "a" * 64, "statementCount": 12, "auth": "Bearer dev:" + UUID, "note": "zero writes; audit delta 0",
                 "url": "https://postriff-phase2-private.vercel.app/api/health"}
        self.assertEqual(redaction.scan(clean), [])
        self.assertNotIn("hunter2", redaction.scrub_text(dirty["dsn"]))
        self.assertNotIn("RafiiRoot", redaction.scrub_text(dirty["log"]))


class Coverage(unittest.TestCase):
    """Every corpus item names checks that exist (a renamed or deleted check fails here, not silently in the matrix)."""

    def test_every_check_exists(self):
        import importlib
        scenes = (ROOT / "web/tests/agent-ui-e2e/scenes.cjs").read_text(encoding="utf-8")
        declared = set(re.findall(r"scene\('([a-z0-9-]+)'", scenes))
        self.assertEqual(declared, set(corpus.E2E_SCENES), "scenes.cjs declares exactly the corpus scene ids")
        for check in sorted(corpus.corpus_checks()):
            with self.subTest(check=check):
                if check.startswith("e2e:"):
                    self.assertIn(check[4:], declared)
                    continue
                module, cls, method = check.split(".")
                loaded = importlib.import_module(f"agent_ui_acceptance.{module}")
                self.assertTrue(callable(getattr(getattr(loaded, cls), method, None)), check)

    def test_every_gate_and_corpus_item_is_mapped(self):
        self.assertEqual(sorted(corpus.GATES), sorted([f"G{i:02d}" for i in range(1, 26)] + [f"J0{i}" for i in range(1, 10)]))
        self.assertEqual(len(corpus.NEGATIVE_CORPUS), 23)
        for gate in corpus.GATES.values():
            for group in gate["kinds"]:
                self.assertTrue(set(group) <= set(corpus.EVIDENCE_KINDS), group)
        path = ROOT / "docs/design/openui-production-2026-10-08/acceptance.json"
        if not path.exists() and (ROOT / ".jcb-working-tree-proof.txt").exists():
            self.skipTest("JCB snapshots exclude docs/** (inputExcludes); GitHub Actions runs this comparison")
        acceptance = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(g["id"] for g in acceptance["gates"]), sorted(corpus.GATES))


if __name__ == "__main__":
    unittest.main()
