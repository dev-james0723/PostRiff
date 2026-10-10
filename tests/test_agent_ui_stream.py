"""Lane B — ui_stream: real presentation streaming, replay, cancel, edits and the G04 probe (G03 G04 G12 G13 G17).

Every provider is a scripted fake (no paid call). Storage, projection, manifest and validator are lane F/D/C contracts replaced by
faithful fakes (tests/test_agent_ui_stream_fakes.py); the SQL B issues itself runs on PostgreSQL in
tests/phase2/postgres_agent_ui_stream.py.
"""
import codecs
import json
import logging
import os
import unittest
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import ai_call_events
from postriff_phase2.agent_runtime_v2 import ui_capabilities, ui_contracts as contracts, ui_projection, ui_store, ui_stream, ui_validator

from test_agent_ui_stream_fakes import (GOOD_PROGRAM, ME, OTHER_TOKEN, PRIVATE_CONTEXT_TEXT, TOKEN, WS, FakeDB, FakeRuntime, FakeStore, FakeValidator,
                                        ScriptTransport, Started, StatusError, fake_current, fake_manifest, fake_projection, frame_ids, make_assets, make_cfg,
                                        parse, program_in_pieces, usage_final)

KEY = "presentation-key-0001"
FOUNDER_NAMESPACE = "founder:operator:production"
REAL_PROJECTION, REAL_MANIFEST = ui_projection.project_ui_context, ui_capabilities.build_manifest


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.store = FakeStore(self.db)
        self.validator = FakeValidator()
        self.transport = ScriptTransport()
        self.runtime = FakeRuntime(self.db, make_cfg(), self.transport, make_assets())
        self.ready_checks = []
        original_append = self.store.append_event

        def append(conn_or_cur, artifact_id, attempt_id, revision, kind, payload):
            if kind == "ui.ready":
                art = self.db.artifacts[artifact_id]
                attempt = self.db.attempts[attempt_id]
                self.ready_checks.append({"revision": art["revision"], "validated": len(self.validator.calls),
                                          "settled": bool(attempt["reservationId"] and self.db.settlements_for(attempt["reservationId"]))})
            return original_append(conn_or_cur, artifact_id, attempt_id, revision, kind, payload)
        self.store.append_event = append
        patches = [mock.patch.object(ui_store, name, getattr(self.store, name)) for name in
                   ("create_or_resume_artifact", "append_event", "checkpoint", "commit_ui_revision", "finish_attempt", "events_after", "reap_expired")]
        patches += [mock.patch.object(ui_projection, "project_ui_context", fake_projection), mock.patch.object(ui_capabilities, "build_manifest", fake_manifest),
                    mock.patch.object(ui_capabilities, "current", fake_current), mock.patch.object(ui_validator, "validate_and_merge_ui", self.validator),
                    mock.patch.object(ai_call_events, "write_attempts", self._record_calls), mock.patch.object(ui_stream, "_throttle", self._throttle),
                    mock.patch.object(ui_stream, "HEARTBEAT_SECONDS", 30.0), mock.patch.object(ui_stream, "CANCEL_POLL_SECONDS", 0.05),
                    mock.patch.object(ui_stream, "REPLAY_TAIL_SECONDS", 0.3), mock.patch.object(ui_stream, "REPLAY_POLL_SECONDS", 0.02),
                    mock.patch.object(ui_stream, "FLUSH_SECONDS", 0.0), mock.patch.dict(os.environ, {"POSTRIFF_AI_PAUSED": ""})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.throttled = []

    def _record_calls(self, base, attempts, *, cursor=None, connect=None, scope_id=None):
        self.db.call_events.extend({**base, **a} for a in attempts)
        return len(attempts)

    def _throttle(self, cur, scope, limit, window):
        self.throttled.append((scope, limit, window))
        if len(self.throttled) > limit:
            raise AlphaError("Too many attempts.", 429)

    def post(self, parent, key=KEY, token=TOKEN, **extra):
        request = contracts.validate_presentation_request({"parentRunId": parent, "idempotencyKey": key, **extra})
        started = Started()
        iterable = ui_stream.create_presentation(self.runtime, {"postriff.request_id": "f" * 32}, started, WS, token, request)
        return started, iterable

    def drain(self, iterable) -> bytes:
        try:
            return b"".join(iterable)
        finally:
            iterable.close()

    def run_one(self, parent, **extra):
        started, iterable = self.post(parent, **extra)
        data = self.drain(iterable)
        return started, data, parse(data)

    def ready_artifact(self):
        parent = self.db.add_parent()
        _, _, events = self.run_one(parent)
        self.assertEqual(events[-1]["kind"], "ui.ready")
        return parent, events[-1]["artifactId"]


class Generation(Base):
    def test_streams_progressively_then_ready_only_after_validation_persistence_and_settlement(self):
        self.transport.scripts.append(program_in_pieces() + [("final", usage_final())])
        parent = self.db.add_parent()
        started, data, events = self.run_one(parent)
        self.assertEqual(started.status, "200 OK")
        self.assertIn(("Content-Type", "text/event-stream; charset=utf-8"), started.headers)
        self.assertFalse(any(h[0].lower() == "content-length" for h in started.headers))
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds[0], "ui.started")
        self.assertEqual(kinds[-1], "ui.ready")
        deltas = [e for e in events if e["kind"] == "ui.delta"]
        self.assertGreater(len(deltas), 1, "source must arrive in several frames, not one buffered body")
        self.assertEqual("".join(d["payload"]["append"] for d in deltas), GOOD_PROGRAM)
        offsets = [d["payload"]["offset"] for d in deltas]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(offsets[-1] + len(deltas[-1]["payload"]["append"].encode()), len(GOOD_PROGRAM.encode()))
        seqs = [e["seq"] for e in events]
        self.assertEqual(seqs, sorted(set(seqs)))
        self.assertEqual(frame_ids(data)[0], f"{events[0]['artifactId']}:{events[0]['seq']}")
        self.assertEqual(self.ready_checks, [{"revision": 1, "validated": 1, "settled": True}])
        ready = events[-1]["payload"]
        self.assertEqual(ready["revision"], 1)
        self.assertEqual(ready["sourceHash"], contracts.sha256_text(GOOD_PROGRAM.strip()))
        self.assertEqual(ready["canonicalSource"], GOOD_PROGRAM.strip())
        self.assertEqual(len(self.transport.calls), 1)

    def test_validator_gets_manifest_policy_and_scope(self):
        parent = self.db.add_parent()
        self.run_one(parent)
        call = self.validator.calls[0]
        self.assertEqual(call["mode"], "generate")
        self.assertIsNone(call["base"])
        self.assertEqual(call["policy"]["rootName"], "RafiiRoot")
        self.assertFalse(call["policy"]["founder"])
        self.assertEqual(call["policy"]["readBindings"], ["drafts_list"])
        self.assertEqual(call["policy"]["actionIds"], ["draft_edit"])
        self.assertIn("ToolBoundTable", call["policy"]["allowedComponents"])
        self.assertNotIn("ToolBoundChart", call["policy"]["allowedComponents"], "only the journey's groups")
        self.assertEqual(set(call["scope"]), {"workspaceId", "artifactId", "attemptId"})

    def test_actions_kill_switch_keeps_write_controls_out_of_the_prompt_and_policy(self):
        self.runtime.cfg = make_cfg(RAFII_GENUI_ACTIONS_ENABLED=None)
        _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[0]["payload"]["manifest"]["actions"], [])
        self.assertEqual(self.validator.calls[-1]["policy"]["actionIds"], [])
        self.assertNotIn("- draft_edit:", self.transport.calls[-1]["plan"].instructions)
        self.assertEqual(events[-1]["kind"], "ui.ready", "reads still work while writes are switched off")

    def test_real_manifest_honours_the_actions_kill_switch(self):
        with mock.patch.object(ui_projection, "project_ui_context", REAL_PROJECTION), mock.patch.object(ui_capabilities, "build_manifest", REAL_MANIFEST):
            self.runtime.ui_assets_dir = None
            self.runtime.cfg = make_cfg(RAFII_GENUI_ACTIONS_ENABLED=None)
            _, _, off = self.run_one(self.db.add_parent())
            self.runtime.cfg = make_cfg()
            _, _, on = self.run_one(self.db.add_parent(), key="presentation-key-actions-on")
        self.assertEqual(off[0]["payload"]["manifest"]["actions"], [])
        self.assertEqual(self.validator.calls[0]["policy"]["actionIds"], [])
        self.assertTrue(on[0]["payload"]["manifest"]["actions"], "J01 offers its write controls when actions are on")
        self.assertTrue(self.validator.calls[1]["policy"]["actionIds"])

    def test_started_frame_and_stream_carry_no_private_data(self):
        parent = self.db.add_parent()
        _, data, events = self.run_one(parent)
        started = events[0]["payload"]
        self.assertEqual(started["manifest"], contracts.public_manifest(fake_manifest(None, None, {"journey_ids": ["J01"]})))
        text = data.decode("utf-8")
        for secret in (PRIVATE_CONTEXT_TEXT, "secret-target", "token=secret", ME, "approvedRefs"):
            self.assertNotIn(secret, text)
        plan = self.transport.calls[0]["plan"]
        self.assertNotIn(PRIVATE_CONTEXT_TEXT, plan.instructions + plan.input_text)
        self.assertNotIn("token=secret", plan.input_text)

    def test_reservation_uses_parent_run_key_and_settles_once_with_known_usage(self):
        parent = self.db.add_parent()
        self.run_one(parent)
        reservations = self.db.ui_reservations()
        self.assertEqual(len(reservations), 1)
        attempt = next(iter(self.db.attempts.values()))
        self.assertEqual(reservations[0]["key"], f"agent:{parent}:ui:{attempt['attemptId']}")
        self.assertEqual(reservations[0]["runId"], parent)
        self.assertEqual(reservations[0]["meta"]["via"], "rafii_agent_ui")
        settles = self.db.settlements_for(reservations[0]["id"])
        self.assertEqual(len(settles), 1)
        expected = self.runtime.cfg.estimate_usd_micro("gpt-6-luna", 1200, 300)
        self.assertEqual((settles[0]["costState"], settles[0]["actual"]), ("actual", expected))
        self.assertEqual(len(self.db.call_events), 1)
        self.assertEqual(self.db.call_events[0]["workload"], "ui_presenter")
        self.assertEqual(self.db.call_events[0]["physical_attempt_id"], f"{attempt['attemptId']}:p1")
        self.assertEqual(attempt["costState"], "known")
        self.assertEqual(self.runtime.approvals[0][2], parent, "the parent turn's credit-authority path is inherited")

    def test_duplicate_idempotency_key_replays_and_never_dispatches_again(self):
        parent = self.db.add_parent()
        _, _, first = self.run_one(parent)
        _, data, second = self.run_one(parent)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(second[-1]["kind"], "ui.ready")
        self.assertEqual(second[-1]["seq"], first[-1]["seq"])
        self.assertEqual(len(self.db.ui_reservations()), 1)

    def test_second_producer_for_the_same_view_attaches_instead_of_dispatching(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("sleep", 0.4), ("delta", 'a = Text("x")\n'), ("final", usage_final())])
        parent = self.db.add_parent()
        _, first = self.post(parent, key="first-tab-key-000001")
        next(first)          # ui.started
        next(first)          # the first delta: the attempt is live
        _, second = self.post(parent, key="second-tab-key-00001")
        replayed = parse(self.drain(second))
        self.assertEqual(replayed[0]["kind"], "ui.started")
        self.assertEqual(len(self.transport.calls), 1, "one producer per artifact revision")
        rest = parse(self.drain(first))
        self.assertEqual(rest[-1]["kind"], "ui.ready")
        self.assertEqual(len(self.db.ui_reservations()), 1)


class NoGeneration(Base):
    def assertNoSpend(self):
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.db.ui_reservations(), [])

    def test_plain_text_or_greeting_turn_never_reaches_the_presenter(self):
        parent = self.db.add_parent(eligible=False)
        with self.assertRaises(AlphaError) as raised:
            self.post(parent)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, "ui_not_eligible"))
        self.assertNoSpend()
        self.assertEqual(self.db.artifacts, {})

    def test_fallback_or_unmetered_turns_are_not_eligible(self):
        for kwargs in ({"composed": "site_agent"}, {"composed": "deterministic"}, {"billing": "scripted"}, {"status": "running"}):
            parent = self.db.add_parent(**kwargs)
            with self.assertRaises(AlphaError):
                self.post(parent)
        self.assertNoSpend()

    def test_passive_reopen_of_an_old_answer_does_not_generate(self):
        parent = self.db.add_parent(age=ui_stream.FRESH_SECONDS + 1)
        with self.assertRaises(AlphaError) as raised:
            self.post(parent)
        self.assertEqual(raised.exception.code, "ui_not_eligible")
        self.assertNoSpend()

    def test_another_member_cannot_start_or_spend_on_someone_elses_turn(self):
        parent = self.db.add_parent()
        with self.assertRaises(AlphaError) as raised:
            self.post(parent, token=OTHER_TOKEN)
        self.assertEqual(raised.exception.status, 403)
        self.assertNoSpend()

    def test_unavailable_route_is_a_persisted_native_fallback_without_a_call(self):
        self.runtime.cfg = make_cfg(OPENAI_API_KEY=None)
        parent = self.db.add_parent()
        _, _, events = self.run_one(parent)
        self.assertEqual([e["kind"] for e in events], ["ui.failed"])
        self.assertEqual(events[0]["payload"]["reason"], "no_model_route")
        self.assertEqual(events[0]["payload"]["fallback"], "native")
        self.assertNoSpend()
        _, _, again = self.run_one(parent)
        self.assertEqual([e["kind"] for e in again], ["ui.failed"], "a reload replays the refusal, never retries")
        self.assertNoSpend()

    def test_missing_price_refuses_before_any_call(self):
        self.runtime.cfg = make_cfg(RAFII_AGENT_FAST_MODEL="gpt-unpriced-model")
        parent = self.db.add_parent()
        _, _, events = self.run_one(parent)
        self.assertEqual(events[-1]["payload"]["reason"], "price_unknown")
        self.assertNoSpend()

    def test_combined_turn_budget_denial(self):
        parent = self.db.add_parent(ceiling=88_000, spent=86_000)
        _, _, events = self.run_one(parent)
        self.assertEqual(events[-1]["payload"]["reason"], "budget")
        self.assertNoSpend()

    def test_unknown_parent_spend_has_no_room(self):
        parent = self.db.add_parent(spent_state="unknown")
        _, _, events = self.run_one(parent)
        self.assertEqual(events[-1]["payload"]["reason"], "budget")
        self.assertNoSpend()

    def test_ledger_refusal_and_operator_pause(self):
        self.db.reserve_error = AlphaError("over the limit", 402)
        _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["payload"]["reason"], "budget")
        self.db.reserve_error = None
        with mock.patch.dict(os.environ, {"POSTRIFF_AI_PAUSED": "1"}):
            _, _, events = self.run_one(self.db.add_parent(), key="presentation-key-paused")
        self.assertEqual(events[-1]["payload"]["reason"], "disabled")
        self.assertEqual(self.transport.calls, [])

    def test_egress_denied_projection(self):
        def denied(*args, **kwargs):
            projection = fake_projection(*args, **kwargs)
            projection["egress_decision"] = {"allowed": False, "provider": "openai", "reason": "memory_local_only"}
            return projection
        with mock.patch.object(ui_projection, "project_ui_context", denied):
            _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["payload"]["reason"], "egress_denied")
        self.assertNoSpend()


class Failures(Base):
    def only_reservation(self):
        reservations = self.db.ui_reservations()
        self.assertEqual(len(reservations), 1)
        return reservations[0]

    def test_cut_stream_without_usage_keeps_the_hold_as_unknown(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("final", {"status": "unknown", "known": False})])
        _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual((events[-1]["kind"], events[-1]["payload"]["reason"]), ("ui.failed", "provider_error"))
        settles = self.db.settlements_for(self.only_reservation()["id"])
        self.assertEqual([s["costState"] for s in settles], ["estimated_unknown"], "unknown keeps the hold; never zero")

    def test_provider_5xx_is_unknown_and_4xx_is_released_without_retry(self):
        self.transport.scripts.append([("raise", StatusError(503))])
        _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["payload"]["reason"], "provider_error")
        first = self.db.ui_reservations()[0]
        self.assertEqual([s["costState"] for s in self.db.settlements_for(first["id"])], ["estimated_unknown"])
        self.transport.scripts.append([("raise", StatusError(400))])
        _, _, events = self.run_one(self.db.add_parent(), key="presentation-key-0002")
        second = self.db.ui_reservations()[1]
        self.assertEqual([(s["costState"], s["actual"]) for s in self.db.settlements_for(second["id"])], [("released", 0)])
        self.assertEqual(len(self.transport.calls), 2, "one physical request per attempt: no hidden retry")

    def test_generation_timeout(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("hang",)])
        with mock.patch.object(ui_stream, "GENERATION_SECONDS", 1.4):
            _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual((events[-1]["kind"], events[-1]["payload"]["reason"]), ("ui.failed", "provider_timeout"))
        self.assertEqual([s["costState"] for s in self.db.settlements_for(self.only_reservation()["id"])], ["estimated_unknown"])
        self.assertEqual(self.transport.cancelled, 1)

    def test_cancel_mid_stream_settles_once_and_keeps_the_business_answer(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("hang",)])
        parent = self.db.add_parent()
        answer = json.dumps(self.db.runs[parent]["result"], sort_keys=True)
        _, stream = self.post(parent)
        first = parse(next(stream) + next(stream))
        artifact_id = first[0]["artifactId"]
        result = ui_stream.cancel_http(self.runtime, WS, TOKEN, artifact_id)
        self.assertTrue(result["canceled"])
        self.assertEqual(result["businessResult"], "unchanged")
        rest = parse(self.drain(stream))
        self.assertEqual([e["kind"] for e in rest], ["ui.canceled"])
        self.assertEqual(self.db.kinds(artifact_id).count("ui.canceled"), 1, "one terminal event")
        settles = self.db.settlements_for(self.only_reservation()["id"])
        self.assertEqual([s["costState"] for s in settles], ["estimated_unknown"])
        self.assertEqual(self.transport.cancelled, 1)
        self.assertEqual(json.dumps(self.db.runs[parent]["result"], sort_keys=True), answer)
        again = ui_stream.cancel_http(self.runtime, WS, TOKEN, artifact_id)
        self.assertFalse(again["canceled"])

    def test_client_disconnect_interrupts_and_settles_once(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("hang",)])
        _, stream = self.post(self.db.add_parent())
        events = parse(next(stream) + next(stream))
        with self.assertLogs("postriff.agent_ui", level="INFO") as logs:
            stream.close()                    # the WSGI server calls close() when the client is gone (GeneratorExit)
        attempt = next(iter(self.db.attempts.values()))
        self.assertEqual((attempt["state"], attempt["reason"]), ("interrupted", "client_gone"))
        self.assertEqual(self.db.kinds(events[0]["artifactId"])[-1], "ui.interrupted")
        self.assertEqual([s["costState"] for s in self.db.settlements_for(self.only_reservation()["id"])], ["estimated_unknown"])
        self.assertEqual(self.transport.cancelled, 1)
        record = json.loads(next(line for line in logs.output if "request.stream_closed" in line).split(":", 2)[2])
        self.assertEqual(set(record), {"event", "route", "outcome", "durationMs", "frames", "bytes", "providerAttempts", "requestId"})
        self.assertEqual(record["outcome"], "client_gone")

    def test_close_before_the_first_frame_releases_an_undispatched_hold(self):
        _, stream = self.post(self.db.add_parent())
        stream.close()
        attempt = next(iter(self.db.attempts.values()))
        self.assertEqual(attempt["state"], "interrupted")
        self.assertEqual([(s["costState"], s["actual"]) for s in self.db.settlements_for(self.only_reservation()["id"])], [("released", 0)])
        self.assertEqual(self.transport.calls, [])

    def test_exactly_one_repair_then_repair_exhausted(self):
        self.validator.verdicts = ["reject", "reject"]
        _, _, events = self.run_one(self.db.add_parent())
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds.count("ui.started"), 2)
        self.assertEqual((kinds[-1], events[-1]["payload"]["reason"]), ("ui.failed", "repair_exhausted"))
        repair_started = [e for e in events if e["kind"] == "ui.started"][1]["payload"]
        self.assertEqual(repair_started["kind"], "repair")
        self.assertIsNotNone(repair_started["retryOf"])
        self.assertEqual(len(self.transport.calls), 2)
        self.assertEqual(self.transport.calls[1]["plan"].kind, "repair")
        self.assertIn("component_denied:Bogus", self.transport.calls[1]["plan"].input_text)
        reservations = self.db.ui_reservations()
        self.assertEqual(len(reservations), 2, "the repair is separately reserved")
        for reservation in reservations:
            self.assertEqual(len(self.db.settlements_for(reservation["id"])), 1)
        states = sorted((a["kind"], a["state"], a["reason"]) for a in self.db.attempts.values())
        self.assertEqual(states, [("generate", "failed", "parse_rejected"), ("repair", "failed", "repair_exhausted")])

    def test_repair_can_succeed(self):
        self.validator.verdicts = ["reject", "accept"]
        with self.assertLogs("postriff.agent_ui", level="INFO") as logs:
            _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["kind"], "ui.ready")
        self.assertEqual(events[-1]["payload"]["providerAttempts"], 2)
        # The first-pass rejection is measurable: code prefixes and counts only, never the statement ids or names behind them.
        rejected = [json.loads(r.getMessage()) for r in logs.records if '"genui.validation_rejected"' in r.getMessage()]
        self.assertEqual([(r["kind"], r["codes"]) for r in rejected], [("generate", {"component_denied": 1, "unresolved_ref": 1})])
        self.assertNotIn("Bogus", " ".join(logs.output))

    def test_rejection_log_is_a_fixed_vocabulary(self):
        from postriff_phase2.agent_runtime_v2 import ui_stream as stream
        with self.assertLogs("postriff.agent_ui", level="INFO") as logs:
            stream._log_rejected("generate", ["type-mismatch:title", "missing-required:root", "unresolved_ref:x", "mydraftsecret", "source_not_query:s1"])
        record = json.loads(logs.records[-1].getMessage())
        self.assertEqual(set(record), {"event", "kind", "codes", "errorCount"})
        self.assertEqual(record["codes"], {"missing-required": 1, "other": 1, "source_not_query": 1, "type-mismatch": 1, "unresolved_ref": 1})
        self.assertEqual((record["kind"], record["errorCount"]), ("generate", 5))
        for leaked in ("title", "root", "mydraftsecret", "s1"):
            self.assertNotIn(leaked, json.dumps(record["codes"]) + record["kind"])

    def test_every_validator_code_is_in_the_log_vocabulary(self):
        # D-A48/D-A52: a code validate.ts can emit never logs as "other"; the D-A52 codes are counted by name and get a repair note.
        import os
        import re as _re
        from postriff_phase2.agent_runtime_v2 import ui_presenter, ui_stream as stream
        path = os.path.join(os.path.dirname(__file__), "..", "web", "src", "lib", "agent-runtime", "ui-parser", "validate.ts")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        emitted = set(_re.findall(r"errors\.push\([`']([a-z_-]+)[:`']", source)) | set(_re.findall(r"rejected\(\[['`]([a-z_-]+)['`]\]", source))
        self.assertTrue({"unreachable_statement", "query_as_child", "query_arg_placeholder"} <= emitted, emitted)
        self.assertEqual(sorted(emitted - stream.REJECTION_CODES), [])
        with self.assertLogs("postriff.agent_ui", level="INFO") as logs:
            stream._log_rejected("generate", ["query_as_child:automations", *[f"unreachable_statement:s{i}" for i in range(5)], "query_arg_placeholder:cal"])
        self.assertEqual(json.loads(logs.records[-1].getMessage())["codes"], {"query_arg_placeholder": 1, "query_as_child": 1, "unreachable_statement": 5})
        for code in ("unreachable_statement", "query_as_child", "query_arg_placeholder"):
            self.assertNotIn(code, stream.NOT_REPAIRABLE, "a first-pass failure that goes to the one automatic repair")
            self.assertIn(code, ui_presenter._REPAIR_GUIDE)

    def test_repair_is_budget_checked(self):
        self.validator.verdicts = ["reject"]
        self.transport.scripts.append([("delta", GOOD_PROGRAM), ("final", usage_final(1200, 16_000))])   # the first attempt costs ~8.1k
        parent = self.db.add_parent(ceiling=88_000, spent=76_000)    # 12k of room: the first attempt fits, its repair no longer does
        _, _, events = self.run_one(parent)
        self.assertEqual((events[-1]["kind"], events[-1]["payload"]["reason"]), ("ui.failed", "budget"))
        self.assertEqual(len(self.transport.calls), 1)

    def test_database_failure_mid_stream_ends_in_a_terminal_frame_and_settles(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("sleep", 0.2), ("delta", "a = x\n"), ("final", usage_final())])
        original = self.store.append_event
        calls = {"n": 0}

        def flaky(conn_or_cur, artifact_id, attempt_id, revision, kind, payload):
            if kind == "ui.delta":
                calls["n"] += 1
                if calls["n"] == 2:
                    raise ConnectionError("database went away")
            return original(conn_or_cur, artifact_id, attempt_id, revision, kind, payload)
        with mock.patch.object(ui_store, "append_event", flaky):
            _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual((events[-1]["kind"], events[-1]["payload"]["reason"]), ("ui.failed", "internal_error"))
        self.assertEqual(len(self.db.settlements_for(self.only_reservation()["id"])), 1)
        self.assertEqual(next(iter(self.db.attempts.values()))["state"], "failed")

    def test_no_time_left_is_a_timeout_without_dispatch(self):
        with mock.patch.object(ui_stream, "GENERATION_SECONDS", 0.5):
            _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["payload"]["reason"], "provider_timeout")
        self.assertEqual(self.transport.calls, [])
        self.assertEqual([(s["costState"], s["actual"]) for s in self.db.settlements_for(self.only_reservation()["id"])], [("released", 0)])

    def test_library_skew_and_other_unfixable_codes_are_terminal_without_a_repair(self):
        cases = {"errors:library_unsupported": "library_unsupported", "errors:contract_mismatch": "library_unsupported",
                 "errors:missing_base": "revision_conflict", "errors:source_too_large": "source_too_large",
                 "errors:unresolved_ref,library_unsupported": "library_unsupported", "errors:bad_request": "validation_unavailable",
                 "errors:unauthorized": "validation_unavailable", "errors:validation_unavailable": "validation_unavailable"}
        for n, (verdict, reason) in enumerate(cases.items()):
            with self.subTest(verdict=verdict):
                self.validator.verdicts = [verdict]
                calls, reservations = len(self.transport.calls), len(self.db.ui_reservations())
                _, _, events = self.run_one(self.db.add_parent(), key=f"presentation-skew-{n:06d}")
                self.assertEqual((events[-1]["kind"], events[-1]["payload"]["reason"]), ("ui.failed", reason))
                self.assertEqual([e["kind"] for e in events].count("ui.started"), 1, "no repair attempt")
                self.assertEqual(len(self.transport.calls), calls + 1, "no second paid presenter call")
                self.assertEqual(len(self.db.ui_reservations()), reservations + 1, "no second reservation")
                self.assertEqual(len(self.db.settlements_for(self.db.ui_reservations()[-1]["id"])), 1, "the first attempt settles once")

    def test_validator_unavailable_is_not_repaired(self):
        self.validator.verdicts = ["unavailable"]
        _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["payload"]["reason"], "validation_unavailable")
        self.assertEqual(len(self.transport.calls), 1)

    def test_oversized_source_stops_the_stream(self):
        with mock.patch.dict(contracts.BOUNDS, {"sourceBytes": 64}):
            self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("delta", "x" * 100), ("hang",)])
            _, _, events = self.run_one(self.db.add_parent())
        self.assertEqual(events[-1]["payload"]["reason"], "source_too_large")
        self.assertEqual(self.transport.cancelled, 1)

    def test_heartbeat_after_silence_reuses_the_last_seq_and_is_not_persisted(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("sleep", 0.45), ('delta', 'a = Text("x")\n'), ("final", usage_final())])
        with mock.patch.object(ui_stream, "HEARTBEAT_SECONDS", 0.12):
            _, data, events = self.run_one(self.db.add_parent())
        beats = [e for e in events if e["kind"] == "ui.heartbeat"]
        self.assertGreaterEqual(len(beats), 2)
        previous = [e for e in events if e["kind"] == "ui.delta"][0]
        self.assertEqual(beats[0]["seq"], previous["seq"])
        self.assertNotIn("ui.heartbeat", self.db.kinds())
        self.assertEqual(events[-1]["kind"], "ui.ready")


class Edits(Base):
    def edit(self, artifact_id, base_revision, base_hash, key="edit-key-000000000001", instruction="Add a chart of the drafts by platform"):
        request = contracts.validate_patch({"baseRevision": base_revision, "baseSourceHash": base_hash, "instruction": instruction, "idempotencyKey": key})
        started = Started()
        return ui_stream.create_edit(self.runtime, {}, started, WS, TOKEN, artifact_id, request)

    def test_stale_base_is_409_before_any_spend(self):
        _, artifact_id = self.ready_artifact()
        calls, reservations = len(self.transport.calls), len(self.db.ui_reservations())
        with self.assertRaises(AlphaError) as raised:
            self.edit(artifact_id, 1, "0" * 64)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, "ui_revision_conflict"))
        with self.assertRaises(AlphaError):
            self.edit(artifact_id, 2, self.db.artifacts[artifact_id]["sourceHash"])
        self.assertEqual((len(self.transport.calls), len(self.db.ui_reservations())), (calls, reservations))

    def test_edit_patches_the_current_revision_and_is_separately_metered(self):
        _, artifact_id = self.ready_artifact()
        base_hash = self.db.artifacts[artifact_id]["sourceHash"]
        self.transport.scripts.append([("delta", 'chart = ToolBoundChart("drafts_list", {})\n'), ("final", usage_final(800, 120))])
        events = parse(self.drain(self.edit(artifact_id, 1, base_hash)))
        self.assertEqual(events[-1]["kind"], "ui.ready")
        self.assertEqual(events[-1]["payload"]["revision"], 2)
        call = self.validator.calls[-1]
        self.assertEqual(call["mode"], "patch")
        self.assertEqual(call["base"], GOOD_PROGRAM.strip())
        plan = self.transport.calls[-1]["plan"]
        self.assertEqual((plan.kind, plan.mode), ("edit", "patch"))
        self.assertIn("Add a chart", plan.input_text)
        edit_reservation = self.db.ui_reservations()[-1]
        self.assertTrue(edit_reservation["meta"]["chain"].startswith("edit:"))
        self.assertEqual(self.db.revisions[(artifact_id, 1)], GOOD_PROGRAM.strip(), "the previous revision stays recoverable")

    def test_edit_while_another_attempt_is_live_is_refused(self):
        _, artifact_id = self.ready_artifact()
        base_hash = self.db.artifacts[artifact_id]["sourceHash"]
        self.transport.scripts.append([("delta", "x = Text(\"a\")\n"), ("hang",)])
        stream = self.edit(artifact_id, 1, base_hash)
        next(stream)
        with self.assertRaises(AlphaError) as raised:
            self.edit(artifact_id, 1, base_hash, key="edit-key-000000000002")
        self.assertEqual(raised.exception.code, "ui_busy")
        stream.close()


class Replay(Base):
    def test_replay_never_dispatches_and_honours_after(self):
        _, artifact_id = self.ready_artifact()
        calls = len(self.transport.calls)
        started = Started()
        everything = parse(b"".join(ui_stream.replay(self.runtime, {}, started, WS, TOKEN, artifact_id, 0)))
        later = parse(b"".join(ui_stream.replay(self.runtime, {}, Started(), WS, TOKEN, artifact_id, everything[0]["seq"])))
        self.assertEqual(started.status, "200 OK")
        self.assertEqual([e["seq"] for e in later], [e["seq"] for e in everything[1:]])
        self.assertEqual(len(self.transport.calls), calls)

    def test_replay_of_a_foreign_artifact_is_404(self):
        _, artifact_id = self.ready_artifact()
        self.db.artifacts[artifact_id]["workspaceId"] = "00000000-0000-4000-8000-000000000000"
        with self.assertRaises(AlphaError) as raised:
            ui_stream.replay(self.runtime, {}, Started(), WS, TOKEN, artifact_id, 0)
        self.assertEqual(raised.exception.status, 404)

    def test_replay_tails_a_live_attempt_with_heartbeats_then_closes(self):
        self.transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("hang",)])
        _, producer = self.post(self.db.add_parent())
        artifact_id = parse(next(producer) + next(producer))[0]["artifactId"]     # started + first delta: the producer has dispatched
        with mock.patch.object(ui_stream, "HEARTBEAT_SECONDS", 0.1):
            data = b"".join(ui_stream.replay(self.runtime, {}, Started(), WS, TOKEN, artifact_id, 0))
        events = parse(data)
        self.assertEqual(events[0]["kind"], "ui.started")
        self.assertTrue(any(e["kind"] == "ui.heartbeat" for e in events))
        self.assertEqual(len(self.transport.calls), 1)
        producer.close()


class Founder(Base):
    """J09 on the founder route family: the founder runtime's namespace makes ui_transaction yield founder-scope auth; the
    real lane D projection and manifest are used (not fakes); the real generated founder library and prompts are used."""

    def setUp(self):
        super().setUp()
        for patch in (mock.patch.object(ui_projection, "project_ui_context", REAL_PROJECTION), mock.patch.object(ui_capabilities, "build_manifest", REAL_MANIFEST)):
            patch.start()
            self.addCleanup(patch.stop)
        self.runtime.ui_assets_dir = None               # the real generated assets (consumer + founder libraries)

    def founder_parent(self):
        run_id = self.db.add_parent(journeys=("J09",), run_key=f"agent:{FOUNDER_NAMESPACE}:" + "k" * 12)
        self.db.runs[run_id]["result"]["routes"] = [{"agent": "rafii_founder_manager", "provider": "openai", "model": "gpt-6-sol"}]
        self.db.runs[run_id]["result"]["founder"] = True
        return run_id

    def founder_post(self, runtime, parent, key="founder-key-000000001"):
        request = {"parentRunId": parent, "slot": "main", "surface": "founder", "idempotencyKey": key, "retryOfAttemptId": None, "conversationId": None}
        return ui_stream.create_presentation(runtime, {}, Started(), WS, TOKEN, request)

    def test_founder_presentation_is_ready_with_a_founder_manifest_and_library(self):
        self.runtime.founder = {"namespace": FOUNDER_NAMESPACE}
        events = parse(self.drain(self.founder_post(self.runtime, self.founder_parent())))
        self.assertEqual([events[0]["kind"], events[-1]["kind"]], ["ui.started", "ui.ready"])
        self.assertEqual(events[0]["payload"]["library"], "founder")
        self.assertEqual(events[0]["payload"]["manifest"]["actions"], [], "founder views are read-only")
        stored = self.db.artifacts[events[0]["artifactId"]]["manifest"]
        self.assertEqual((stored["scope"], stored["scopeKey"]), ("founder", FOUNDER_NAMESPACE))
        self.assertTrue(stored["queries"], "the founder manifest carries J09 read bindings")
        self.assertTrue(self.validator.calls[-1]["policy"]["founder"])
        self.assertNotIn("ActionButton", self.validator.calls[-1]["policy"]["allowedComponents"])
        plan = self.transport.calls[-1]["plan"]
        self.assertEqual((plan.library, plan.prompt_key), ("founder", "founder:J09:generate"))

    def test_consumer_auth_cannot_present_a_founder_run_and_vice_versa(self):
        founder_run = self.founder_parent()
        with self.assertRaises(AlphaError) as raised:
            self.founder_post(self.runtime, founder_run)                 # consumer runtime (no founder namespace)
        self.assertEqual(raised.exception.status, 404)
        with self.assertRaises(AlphaError) as raised:
            self.post(founder_run)
        self.assertEqual(raised.exception.status, 404)
        self.runtime.founder = {"namespace": FOUNDER_NAMESPACE}
        with self.assertRaises(AlphaError) as raised:
            self.founder_post(self.runtime, self.db.add_parent(), key="founder-key-000000002")   # a consumer run under founder auth
        self.assertEqual(raised.exception.status, 404)
        other_namespace = self.db.add_parent(journeys=("J09",), run_key="agent:founder:operator:staging:" + "k" * 12)
        with self.assertRaises(AlphaError) as raised:
            self.founder_post(self.runtime, other_namespace, key="founder-key-000000003")         # another founder namespace
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.transport.calls, [])

    def test_founder_artifact_is_404_to_consumer_cancel_and_edit(self):
        self.runtime.founder = {"namespace": FOUNDER_NAMESPACE}
        events = parse(self.drain(self.founder_post(self.runtime, self.founder_parent())))
        artifact_id = events[0]["artifactId"]
        self.db.artifacts[artifact_id].update(scope="founder", scopeKey=FOUNDER_NAMESPACE)    # what lane F stores for founder scope
        consumer = FakeRuntime(self.db, self.runtime.cfg, self.transport, None)
        with self.assertRaises(AlphaError) as raised:
            ui_stream.cancel_http(consumer, WS, TOKEN, artifact_id)
        self.assertEqual(raised.exception.status, 404)
        request = contracts.validate_patch({"baseRevision": 1, "baseSourceHash": self.db.artifacts[artifact_id]["sourceHash"], "instruction": "Add revenue",
                                            "idempotencyKey": "founder-edit-0000000001"}, founder=True)
        with self.assertRaises(AlphaError) as raised:
            ui_stream.create_edit(consumer, {}, Started(), WS, TOKEN, artifact_id, request)
        self.assertEqual(raised.exception.status, 404)
        self.assertFalse(ui_stream.cancel_http(self.runtime, WS, TOKEN, artifact_id)["canceled"], "the founder route reaches its own artifact")


class Probe(Base):
    def test_probe_frames_are_spaced_fragment_utf8_and_cost_nothing(self):
        slept = []
        with mock.patch.object(ui_stream, "_sleep", slept.append):
            started = Started()
            chunks = list(ui_stream.probe(self.runtime, {}, started, WS, TOKEN))
        self.assertEqual(started.status, "200 OK")
        self.assertIn(ui_stream.PROBE_GAP_SECONDS, slept)
        self.assertEqual(slept.count(ui_stream.PROBE_GAP_SECONDS), 3)
        broken = [i for i, c in enumerate(chunks) if not _decodes(c)]
        self.assertEqual(len(broken), 2, "one multi-byte character is split across exactly two writes")
        self.assertEqual(broken[1], broken[0] + 1)
        self.assertTrue(_decodes(chunks[broken[0]] + chunks[broken[1]]))
        decoder = codecs.getincrementaldecoder("utf-8")()
        text = "".join(decoder.decode(c) for c in chunks) + decoder.decode(b"", final=True)
        events = parse(text.encode("utf-8"))
        self.assertEqual([e["kind"] for e in events], ["ui.started", "ui.delta", "ui.delta", "ui.ready"])
        stamps = [e["payload"]["serverMonotonicNs"] for e in events]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(events[1]["payload"]["append"], ui_stream.PROBE_TEXT)
        self.assertEqual(events[3]["payload"]["sourceHash"], contracts.sha256_text(events[1]["payload"]["append"] + events[2]["payload"]["append"]))
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.db.ui_reservations(), [])
        self.assertEqual(self.throttled[0][0], f"ui-probe:{ME}")

    def test_probe_requires_a_member_and_is_throttled(self):
        with self.assertRaises(AlphaError) as raised:
            ui_stream.probe(self.runtime, {}, Started(), "00000000-0000-4000-8000-000000000000", TOKEN)
        self.assertEqual(raised.exception.status, 403)
        with mock.patch.object(ui_stream, "_sleep", lambda s: None):
            for _ in range(ui_stream.PROBE_LIMIT_PER_MINUTE):
                list(ui_stream.probe(self.runtime, {}, Started(), WS, TOKEN))
            with self.assertRaises(AlphaError) as raised:
                ui_stream.probe(self.runtime, {}, Started(), WS, TOKEN)
        self.assertEqual(raised.exception.status, 429)


def _decodes(chunk: bytes) -> bool:
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


logging.getLogger("postriff.agent_ui").setLevel(logging.INFO)

if __name__ == "__main__":
    unittest.main()
