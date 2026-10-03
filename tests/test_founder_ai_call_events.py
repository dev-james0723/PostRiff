"""Founder Admin §8.B write points: one pr_ai_call_events row per provider attempt, recorded with a fake connection, and a
failing or missing table never breaking (or retrying inside) the customer's request."""
import asyncio
import json
import logging
import os
import re
import sys
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2 import ai_call_events, image_runtime, learning_model, model_runtime  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config as agent_config, creative, live, manager  # noqa: E402
from postriff_phase2.agent_runtime_v2.context import EffectLedger, RafiiRunContext  # noqa: E402
from postriff_phase2.growth.usage import MemoryUsageSink, PostgresUsageSink, UsageEvent  # noqa: E402
from postriff_phase2.phone import billing as phone_billing  # noqa: E402

WORKSPACE, USER, RUN, RESERVATION = (str(uuid.uuid4()) for _ in range(4))
MIGRATION = ROOT / "migrations/postriff/058_founder_ai_usage.sql"


class UndefinedTable(Exception):
    """Named like psycopg.errors.UndefinedTable: migration 058 not applied yet."""


class CheckViolation(Exception):
    pass


class FakeDB:
    """A psycopg-shaped connection: cursors, nested transaction() savepoints, commit. Statements are logged; the rows of each
    INSERT INTO pr_ai_call_events are decoded so tests can read them; a statement containing `fail_on` raises `error`."""

    def __init__(self, fail_on=None, error=None, savepoints=True):
        self.log, self.pending, self.committed = [], [], []
        self.fail_on, self.error, self.commits = fail_on, error or UndefinedTable("relation does not exist"), 0
        if not savepoints:
            self.transaction = None

    def cursor(self):
        return FakeCursor(self)

    @contextmanager
    def transaction(self):  # noqa: F811 - replaced by None for a driver without nested transactions
        mark = len(self.pending)
        self.log.append("SAVEPOINT")
        try:
            yield
        except BaseException:
            del self.pending[mark:]
            self.log.append("ROLLBACK TO SAVEPOINT")
            raise
        self.log.append("RELEASE SAVEPOINT")

    def commit(self):
        self.commits += 1
        self.committed.extend(self.pending)
        self.pending = []

    def __enter__(self):
        return self

    def __exit__(self, kind, *_):
        if kind is None:
            self.commit()
        return False

    def calls(self):
        return [row for table, row in self.committed if table == "pr_ai_call_events"]

    def statements(self, needle):
        return [entry for entry in self.log if isinstance(entry, tuple) and needle in entry[0]]


class FakeCursor:
    def __init__(self, db):
        self.db, self.connection, self.rowcount = db, db, -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.db.log.append((sql, params))
        if self.db.fail_on and self.db.fail_on in sql:
            raise self.db.error
        if sql.startswith("SAVEPOINT") or sql.startswith("RELEASE"):
            return
        if sql.startswith("ROLLBACK TO SAVEPOINT"):
            return
        if sql.startswith("INSERT INTO public.pr_ai_call_events"):
            width = len(ai_call_events.COLUMNS)
            rows = [dict(zip(ai_call_events.COLUMNS, params[i:i + width])) for i in range(0, len(params), width)]
            self.db.pending.extend(("pr_ai_call_events", row) for row in rows)
            self.rowcount = len(rows)
        elif sql.startswith("INSERT INTO public.pr_ai_call_settlements"):
            self.db.pending.append(("pr_ai_call_settlements", list(params)))
        elif sql.startswith("INSERT INTO public."):
            self.db.pending.append((sql.split("(")[0].split(".")[1], params))


class Base(unittest.TestCase):
    def setUp(self):
        ai_call_events._STATE.update(disabled_until=0.0, logged=False)
        self.addCleanup(ai_call_events._STATE.update, disabled_until=0.0, logged=False)


class RowsAndWriting(Base):
    def test_build_bounds_every_value_and_never_records_content(self):
        row = ai_call_events.build({"workspace_id": WORKSPACE, "feature": "writer", "run_id": RUN},
                                   {"provider": "gateway", "model": "anthropic/claude-sonnet-5", "status": "weird", "http_status": 99, "latency_ms": 12.6,
                                    "input_tokens": -1, "output_tokens": 50, "cost_usd_micro": 7, "cost_source": "invented", "route": "sideways",
                                    "provider_request_id": "gen 123 <script>", "workload": "Draft", "attempt_no": 0, "audio_seconds": float("inf")})
        self.assertEqual(row["provider"], "vercel-ai-gateway")
        self.assertEqual((row["status"], row["http_status"], row["latency_ms"], row["route"]), ("unknown", None, 13, "primary"))
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["attempt_no"], row["workload"], row["audio_seconds"]), (None, 50, 1, None, None))
        self.assertEqual((row["cost_usd_micro"], row["cost_source"], row["price_version"]), (None, "unknown", None), "a cost without a valid source is unknown")
        self.assertIsNone(row["provider_request_id"], "only opaque ids are kept")
        self.assertEqual(set(row), set(ai_call_events.COLUMNS))
        self.assertRegex(row["dedupe_key"], r"^[0-9a-f]{64}$")
        table = ai_call_events.build({}, {"cost_usd_micro": 5, "cost_source": "table:" + ai_call_events.AGENT_V2})
        self.assertEqual(table["price_version"], ai_call_events.AGENT_V2)
        self.assertEqual(table["feature"], "other")

    def test_dedupe_is_stable_for_an_identified_attempt_and_unique_otherwise(self):
        base = {"workspace_id": WORKSPACE, "feature": "phone", "run_id": RUN}
        one = ai_call_events.build(base, {"physical_attempt_id": "phone-live:abc"})
        self.assertEqual(one["dedupe_key"], ai_call_events.build(base, {"physical_attempt_id": "phone-live:abc", "cost_usd_micro": 9, "cost_source": "provider"})["dedupe_key"])
        self.assertNotEqual(ai_call_events.build(base, {})["dedupe_key"], ai_call_events.build(base, {})["dedupe_key"])

    def test_exempt_users_are_recorded_and_flagged(self):
        with mock.patch.dict(os.environ, {"RAFII_AI_UNLIMITED_USER_IDS": USER}):
            self.assertTrue(ai_call_events.build({"user_id": USER, "feature": "agent"}, {})["ai_usage_exempt"])
        self.assertFalse(ai_call_events.build({"user_id": USER, "feature": "agent"}, {})["ai_usage_exempt"])

    def test_write_joins_the_callers_transaction_under_a_savepoint(self):
        db = FakeDB()
        with db as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO public.pr_usage_ledger(x) VALUES(%s)", (1,))
            written = ai_call_events.write_attempts({"workspace_id": WORKSPACE, "feature": "agent"}, [{"model": "gpt-6-sol", "status": "ok"}], cursor=cur)
        self.assertEqual(written, 1)
        self.assertEqual([table for table, _ in db.committed], ["pr_usage_ledger", "pr_ai_call_events", 'pr_audit_events'])
        self.assertEqual(json.loads(db.committed[-1][1][2])['state'], 'recorded')
        self.assertEqual(db.log[1], "SAVEPOINT")

    def test_missing_table_leaves_the_callers_writes_committed_and_backs_off_for_ten_minutes(self):
        db = FakeDB(fail_on="INSERT INTO public.pr_ai_call_events")
        logger = logging.getLogger("postriff.ai_call_events")
        with self.assertLogs(logger, "WARNING") as logged:
            with db as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO public.pr_usage_ledger(x) VALUES(%s)", (1,))
                self.assertEqual(ai_call_events.write_attempts({"workspace_id": WORKSPACE, "feature": "agent"}, [{"status": "ok"}], cursor=cur), 0)
                cur.execute("INSERT INTO public.pr_agent_runs(x) VALUES(%s)", (2,))
        self.assertEqual([table for table, _ in db.committed], ["pr_usage_ledger", 'pr_audit_events', "pr_agent_runs"], "domain writes and durable gap commit")
        self.assertEqual(json.loads(db.committed[1][1][2])['errorClass'], 'UndefinedTable')
        self.assertIn("ROLLBACK TO SAVEPOINT", db.log)
        self.assertEqual(len(logged.records), 1)
        self.assertIn("UndefinedTable", logged.output[0])
        self.assertNotIn("relation", logged.output[0], "exception class only, never the message")
        self.assertFalse(ai_call_events.installed())
        before = len(db.log)
        with mock.patch.object(logger, "warning") as again:
            with db as conn, conn.cursor() as cur:
                self.assertEqual(ai_call_events.write_attempts({"feature": "agent"}, [{"status": "ok"}], cursor=cur), 0)
        self.assertFalse(any(isinstance(entry, tuple) and 'INSERT INTO public.pr_ai_call_events' in entry[0] for entry in db.log[before:]))
        self.assertEqual(json.loads(db.committed[-1][1][2])['state'], 'suspended')
        again.assert_not_called()
        with mock.patch.object(ai_call_events.time, "monotonic", return_value=time.monotonic() + ai_call_events.BACKOFF_SECONDS + 1):
            self.assertTrue(ai_call_events.installed(), "re-checked after ten minutes")

    def test_driver_without_nested_transactions_uses_explicit_savepoints(self):
        db = FakeDB(fail_on="INSERT INTO public.pr_ai_call_events", error=CheckViolation("bad"), savepoints=False)
        cur = db.cursor()
        cur.execute("INSERT INTO public.pr_usage_ledger(x) VALUES(%s)", (1,))
        with self.assertLogs("postriff.ai_call_events", "WARNING"):
            self.assertEqual(ai_call_events.write_attempts({"feature": "agent"}, [{"status": "ok"}], cursor=cur), 0)
        sql = [entry[0] for entry in db.log if isinstance(entry, tuple)]
        self.assertIn(f"ROLLBACK TO SAVEPOINT {ai_call_events.SAVEPOINT}", sql)
        self.assertTrue(ai_call_events.installed(), "an ordinary failure is not a missing table")

    def test_late_cost_settles_in_the_sidecar(self):
        db = FakeDB()
        with db as conn, conn.cursor() as cur:
            ai_call_events.write_attempts({"workspace_id": WORKSPACE, "feature": "phone"}, [{"physical_attempt_id": "phone-live:1", "status": "unknown"}], cursor=cur)
            ai_call_events.write_attempts({"workspace_id": WORKSPACE, "feature": "phone"},
                                          [{"physical_attempt_id": "phone-live:1", "status": "ok", "cost_usd_micro": 900, "cost_source": "table:x", "audio_seconds": 75}], cursor=cur)
        settlements = db.statements("pr_ai_call_settlements")
        self.assertEqual(len(settlements), 1, "only the costed write tries a settlement")
        self.assertIn("WHERE e.cost_usd_micro IS NULL", settlements[0][0])
        self.assertEqual(settlements[0][1][1:], [900, "table:x", 75.0])

    def test_scope_collects_attempts_and_writes_once_even_on_failure(self):
        db = FakeDB()
        with self.assertRaises(RuntimeError):
            with ai_call_events.scope(feature="image", workspace_id=WORKSPACE, user_id=USER, run_id=RUN, connect=lambda: db):
                ai_call_events.attempt(model="m", status="ok")
                ai_call_events.attempt(model="m", status="failed")
                raise RuntimeError("the run failed")
        self.assertEqual(len(db.statements("INSERT INTO public.pr_ai_call_events")), 1)
        self.assertEqual([row["status"] for row in db.calls()], ["ok", "failed"])
        self.assertEqual({row["feature"] for row in db.calls()}, {"image"})
        self.assertTrue(db.statements("statement_timeout"), "its own connection is time-bounded")
        ai_call_events.attempt(model="m", status="ok")   # outside a scope: nothing, no error
        self.assertFalse(ai_call_events.active())

    def test_scope_with_a_broken_connection_never_raises(self):
        def broken():
            raise OSError("connect failed")
        with self.assertLogs("postriff.ai_call_events", "WARNING") as logged:
            with ai_call_events.scope(feature="writer", workspace_id=WORKSPACE, connect=broken):
                ai_call_events.attempt(model="m", status="ok")
        self.assertIn("OSError", logged.output[0])
        self.assertTrue(ai_call_events.installed())


def context():
    return {"schema": "postriff.context.v1", "operation": "draft", "providerClass": "cloud", "policyEpoch": "e1", "candidateOnly": False,
            "sources": [{"id": "s1", "policy": "public_quote", "candidateOnly": False, "hash": "h", "facts": [{"id": "f1", "sourceId": "s1", "text": "Seed swap on Saturday.", "locator": ""}]}],
            "excluded": []}


GOOD = [{"platform": "LinkedIn", "language": "English", "text": "Saturday: seed swap.", "sourceIds": ["s1"], "unknowns": [], "warnings": []}]
DESTS = [{"platform": "LinkedIn", "language": "English"}]


def completion(usage, status=200):
    return {"status": status, "body": {"id": "gen-123", "choices": [{"message": {"content": json.dumps({"variants": GOOD})}}], "usage": usage}}


class Recording:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, method, url, headers=None, body=None):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class Sink:
    """Shaped like ideas.RunSink (the attributes ai_call_events.sink_scope reads)."""

    def __init__(self, db):
        self.workspace_id, self.run_id = WORKSPACE, RUN
        self.outcome = {"reservationId": RESERVATION, "actor": USER}
        self.service = SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda: db))
        self.events = []

    def emit(self, event):
        self.events.append(event)


class WriterWritePoint(Base):
    def test_each_attempt_of_a_writer_run_is_one_row(self):
        db = FakeDB()
        transport = Recording([{"status": 429, "body": {}}, completion({"prompt_tokens": 2000, "completion_tokens": 500, "prompt_tokens_details": {"cached_tokens": 300},
                                                                        "completion_tokens_details": {"reasoning_tokens": 40}})])
        runtime = model_runtime.ServerModelRuntime("k", transport=transport)
        runtime.sleep = lambda _seconds: None
        result = runtime.start_turn({"context": context(), "idea": "x", "destinations": DESTS}, Sink(db).emit)
        self.assertEqual(result["usage"]["modelRequests"], 2)
        rows = db.calls()
        self.assertEqual([(row["status"], row["attempt_no"], row["workload"]) for row in rows], [("rate_limited", 1, "draft"), ("ok", 2, "draft")])
        refused, answered = rows
        self.assertEqual((refused["cost_usd_micro"], refused["cost_source"], refused["http_status"]), (0, "provider", 429))
        self.assertEqual((answered["workspace_id"], answered["user_id"], answered["run_id"], answered["reservation_id"], answered["feature"]),
                         (WORKSPACE, USER, RUN, RESERVATION, "writer"))
        self.assertEqual((answered["input_tokens"], answered["cached_input_tokens"], answered["output_tokens"], answered["reasoning_tokens"]), (2000, 300, 500, 40))
        self.assertEqual((answered["cost_usd_micro"], answered["cost_source"], answered["price_version"]), (9000, "table:" + model_runtime.DEFAULT_PRICES_VERSION,
                                                                                                             model_runtime.DEFAULT_PRICES_VERSION))
        self.assertEqual((answered["provider"], answered["provider_request_id"], answered["model"]), ("vercel-ai-gateway", "gen-123", "anthropic/claude-sonnet-5"))
        self.assertEqual(len(db.statements("INSERT INTO public.pr_ai_call_events")), 1, "one write per run, when it ends")

    def test_gateway_cost_and_failed_runs_are_recorded(self):
        db = FakeDB()
        transport = Recording([completion({"prompt_tokens": 10, "completion_tokens": 10, "cost": 0.0042}), ])
        model_runtime.ServerModelRuntime("k", transport=transport).start_turn({"context": context(), "idea": "x", "destinations": DESTS}, Sink(db).emit)
        self.assertEqual((db.calls()[0]["cost_usd_micro"], db.calls()[0]["cost_source"]), (4200, "gateway"))
        db = FakeDB()
        transport = Recording([{"status": 503, "body": {}}])
        with self.assertRaises(model_runtime.ProviderFailure):
            model_runtime.ServerModelRuntime("k", transport=transport).start_turn({"context": context(), "idea": "x", "destinations": DESTS}, Sink(db).emit)
        self.assertEqual([(row["status"], row["http_status"], row["cost_usd_micro"]) for row in db.calls()], [("unknown", 503, None)])

    def test_a_failing_table_never_changes_the_run(self):
        db = FakeDB(fail_on="INSERT INTO public.pr_ai_call_events")
        transport = Recording([completion({"prompt_tokens": 10, "completion_tokens": 10})])
        with self.assertLogs("postriff.ai_call_events", "WARNING"):
            result = model_runtime.ServerModelRuntime("k", transport=transport).start_turn({"context": context(), "idea": "x", "destinations": DESTS}, Sink(db).emit)
        self.assertEqual(len(result["artifact"]["variants"]), 1)
        self.assertEqual(db.calls(), [])

    def test_outside_a_run_sink_nothing_is_recorded_here(self):
        """Growth and voice analysis call _call directly: their usage sink records them, so nothing is noted twice."""
        transport = Recording([completion({"prompt_tokens": 10, "completion_tokens": 10})])
        runtime = model_runtime.ServerModelRuntime("k", transport=transport)
        content, usage = runtime._call([{"role": "user", "content": "x"}], runtime.model)
        self.assertEqual(usage["prompt_tokens"], 10)
        self.assertFalse(ai_call_events.active())

    def test_the_real_run_sink_exposes_what_the_scope_reads(self):
        from postriff_phase2.ideas import RunSink
        db = FakeDB()
        service = SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda: db))
        sink = RunSink(service, WORKSPACE, str(uuid.uuid4()), RUN, {"reservationId": RESERVATION, "actor": USER})
        with ai_call_events.sink_scope(sink.emit, feature="writer") as current:
            self.assertEqual(current.base, {"workspace_id": WORKSPACE, "user_id": USER, "feature": "writer", "run_id": RUN, "reservation_id": RESERVATION})
        with ai_call_events.sink_scope(lambda event: None, feature="writer") as nothing:
            self.assertIsNone(nothing)


class ImageAndLearningWritePoints(Base):
    def test_image_attempt_in_the_callers_scope(self):
        import base64
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
        ok = {"status": 200, "body": {"data": [{"b64_json": base64.b64encode(png).decode()}], "usage": {"cost": 0.04},
                                      "providerMetadata": {"gateway": {"generationId": "gen-img-1"}}}}
        db = FakeDB()
        runtime = image_runtime.GatewayImageRuntime("k", transport=lambda *a, **k: ok)
        with ai_call_events.scope(feature="image", workspace_id=WORKSPACE, user_id=USER, run_id=RUN, reservation_id=RESERVATION, connect=lambda: db):
            runtime.generate("a garden at dawn")
        [row] = db.calls()
        self.assertEqual((row["feature"], row["workload"], row["images"], row["status"], row["http_status"]), ("image", "image_generation", 1, "ok", 200))
        self.assertEqual((row["cost_usd_micro"], row["cost_source"], row["provider_request_id"]), (40000, "gateway", "gen-img-1"))
        db = FakeDB()
        busy = image_runtime.GatewayImageRuntime("k", transport=lambda *a, **k: {"status": 429, "body": {}})
        with ai_call_events.scope(feature="image", workspace_id=WORKSPACE, connect=lambda: db):
            with self.assertRaises(image_runtime.ImageGenerationError):
                busy.generate("x")
        self.assertEqual([(r["status"], r["cost_usd_micro"], r["images"]) for r in db.calls()], [("rate_limited", 0, 0)])
        with self.assertRaises(Exception):
            busy.generate("")   # refused before sending: no attempt, no scope needed

    def test_learning_extraction_attempt(self):
        answer = {"status": 200, "body": {"choices": [{"message": {"content": json.dumps({"candidates": []})}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}}
        db = FakeDB()
        call = learning_model.GatewayCall("k", transport=lambda *a, **k: answer)
        with ai_call_events.scope(feature="learning", workspace_id=WORKSPACE, connect=lambda: db):
            call("system", "user", {"type": "object"})
        [row] = db.calls()
        self.assertEqual((row["feature"], row["workload"], row["status"], row["input_tokens"], row["output_tokens"]), ("learning", "structured", "ok", 1000, 100))
        self.assertEqual((row["cost_usd_micro"], row["cost_source"]), (1500, "table:" + model_runtime.DEFAULT_PRICES_VERSION))


class Usage:
    def __init__(self, i, o, cached=None, reasoning=None):
        self.input_tokens, self.output_tokens = i, o
        self.input_tokens_details = SimpleNamespace(cached_tokens=cached)
        self.output_tokens_details = SimpleNamespace(reasoning_tokens=reasoning)


class FakeModel:
    def __init__(self, error=None):
        self.error = error

    async def get_response(self, *args, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(usage=Usage(1200, 300, cached=200, reasoning=50), response_id="resp_1", request_id="req_1")


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__("provider said no")
        self.status_code = status_code


class AgentWritePoints(Base):
    def cfg(self):
        return agent_config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "x"})

    def ctx(self):
        return RafiiRunContext(service=None, workspace_id=WORKSPACE, token="synthetic-session", principal=USER,
                               membership=None, conversation_id=RUN, run_id=RUN, trace_id="trace_abc", config=self.cfg())

    def test_metered_spans_and_failures_become_rows_at_settle(self):
        ctx = self.ctx()
        route = {"provider": "openai", "model": "gpt-6-sol"}
        ok = manager.metered(FakeModel(), ctx, agent="rafii_manager", workload="standard_reasoning", route=route)
        busy = manager.metered(FakeModel(StatusError(429)), ctx, agent="content", workload="fast_language", route={"provider": "openai", "model": "gpt-6-luna"})
        asyncio.run(ok.get_response())
        with self.assertRaises(StatusError):
            asyncio.run(busy.get_response())
        self.assertEqual(ctx.ledger.model_requests, 2, "both the answered request and the refused provider attempt are counted")
        self.assertEqual(len(ctx.ledger.spans), 1, "the failed attempt never becomes a priced answered span")
        self.assertEqual(ctx.ledger.calls[0]["status"], "rate_limited")
        db = FakeDB()
        with db as conn, conn.cursor() as cur:
            self.assertEqual(manager.record_calls(cur, ctx, {"reservationId": RESERVATION}), 2)
        span_row, failed_row = db.calls()
        self.assertEqual((span_row["feature"], span_row["workspace_id"], span_row["user_id"], span_row["run_id"], span_row["reservation_id"]),
                         ("agent", WORKSPACE, USER, RUN, RESERVATION))
        self.assertEqual((span_row["input_tokens"], span_row["cached_input_tokens"], span_row["output_tokens"], span_row["reasoning_tokens"]), (1200, 200, 300, 50))
        self.assertEqual((span_row["cost_usd_micro"], span_row["cost_source"]), (ctx.config.estimate_usd_micro("gpt-6-sol", 1200, 300), "table:" + ai_call_events.AGENT_V2))
        self.assertEqual((span_row["provider"], span_row["provider_request_id"], span_row["physical_attempt_id"]), ("openai", "req_1", "trace_abc:s0"))
        self.assertEqual((failed_row["status"], failed_row["http_status"], failed_row["cost_usd_micro"], failed_row["model"]), ("rate_limited", 429, 0, "gpt-6-luna"))
        with db as conn, conn.cursor() as cur:
            manager.record_calls(cur, ctx, {"reservationId": RESERVATION})
        self.assertEqual(len({row["dedupe_key"] for row in db.calls()}), 2, "recording the same turn again is the same rows")

    def test_failure_statuses(self):
        self.assertEqual(manager.failure_status(asyncio.CancelledError()), ("cancelled", None))
        self.assertEqual(manager.failure_status(StatusError(500)), ("unknown", 500))
        self.assertEqual(manager.failure_status(StatusError(400)), ("failed", 400))
        self.assertEqual(manager.failure_status(TimeoutError()), ("timeout", None))

    def test_record_calls_survives_a_failing_cursor_and_a_missing_one(self):
        ctx = self.ctx()
        ctx.ledger.spans.append({"span": "generation", "agent": "vision", "workload": "vision", "model": "gpt-6-sol", "inputTokens": 10, "outputTokens": 5, "latencyMs": 9})
        db = FakeDB(fail_on="INSERT INTO public.pr_ai_call_events")
        with self.assertLogs("postriff.ai_call_events", "WARNING"):
            with db as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO public.pr_usage_ledger(x) VALUES(%s)", (1,))
                self.assertEqual(manager.record_calls(cur, ctx, None), 0)
        self.assertEqual([table for table, _ in db.committed], ["pr_usage_ledger", 'pr_audit_events'])
        self.assertEqual(manager.record_calls(None, ctx, None), 0)

    def test_follow_up_chips_span_and_unknown_outcome(self):
        db = FakeDB()
        span = {"span": "generation", "agent": "follow_ups", "workload": "fast_language", "model": "gpt-6-luna", "inputTokens": 900, "outputTokens": 120, "latencyMs": 400,
                "estimated": True}
        with db as conn, conn.cursor() as cur:
            manager.record_span(cur, self.cfg(), span, workspace_id=WORKSPACE, user_id=USER, run_id=RUN, reservation={"reservationId": RESERVATION}, trace_id="t1")
        [row] = db.calls()
        self.assertEqual((row["status"], row["input_tokens"], row["cost_usd_micro"], row["provider"]), ("unknown", None, None, "openai"))

    def test_creative_image_attempts(self):
        ctx = self.ctx()
        studio = creative.ImageStudio(ctx.config)
        creative._note_image_call(ctx, studio, "quality", {"reservationId": RESERVATION}, started=time.time(), began=time.monotonic(),
                                  result={"model": "gpt-image-2.5-sunburst", "provider": "openai", "usage": {"inputTokens": 50, "outputTokens": 10}, "latencyMs": 9000,
                                          "providerRef": {"responseId": "resp_img"}})
        creative._note_image_call(ctx, studio, "fast", {"reservationId": RESERVATION}, started=time.time(), began=time.monotonic(),
                                  error=creative.CreativeError("busy", 429, code="provider_busy"))
        creative._note_image_call(ctx, studio, "fast", None, started=time.time(), began=time.monotonic(),
                                  error=creative.CreativeError("no route", 503, code="route_unavailable"))
        self.assertEqual(len(ctx.ledger.calls), 2, "a request refused before sending is no attempt")
        db = FakeDB()
        with db as conn, conn.cursor() as cur:
            manager.record_calls(cur, ctx, {"reservationId": str(uuid.uuid4())})
        made, busy = db.calls()
        self.assertEqual((made["feature"], made["workload"], made["images"], made["reservation_id"]), ("image", "image_quality", 1, RESERVATION))
        self.assertEqual((made["cost_usd_micro"], made["cost_source"]), (agent_config.DEFAULT_IMAGE_ESTIMATE_USD_MICRO["image_quality"], "table:" + ai_call_events.MEDIA_CONSTANTS))
        self.assertEqual((busy["status"], busy["cost_usd_micro"], busy["images"]), ("rate_limited", 0, 0))


class VoicePhoneAndGrowthWritePoints(Base):
    def test_voice_session_settle(self):
        db = FakeDB()
        cfg = agent_config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "x"})
        session = str(uuid.uuid4())
        with db as conn, conn.cursor() as cur:
            live.record_session(cur, cfg, WORKSPACE, USER, session, {"connectedAt": 1_790_000_000.0, "liveSessionId": "sess_1", "reservationId": RESERVATION},
                                status="ok", seconds=135.0, cost=112500)
        [row] = db.calls()
        self.assertEqual((row["feature"], row["workload"], row["provider"], row["model"]), ("voice", "voice_front_end", "openai", "gpt-live-1"))
        self.assertEqual((row["audio_seconds"], row["cost_usd_micro"], row["cost_source"], row["provider_request_id"]), (135.0, 112500, "table:" + ai_call_events.MEDIA_CONSTANTS, "sess_1"))
        self.assertEqual((row["run_id"], row["reservation_id"]), (session, RESERVATION))
        db = FakeDB()
        with db as conn, conn.cursor() as cur:
            live.record_session(cur, cfg, WORKSPACE, USER, session, {}, status=live.SESSION_FAILURES["live_busy"], seconds=0, cost=0, http_status=429)
        self.assertEqual([(r["status"], r["cost_usd_micro"], r["cost_source"], r["http_status"]) for r in db.calls()], [("rate_limited", 0, "provider", 429)])

    def phone(self):
        cfg = agent_config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "x"})
        ledger = SimpleNamespace(settled=[], settle=lambda cur, wid, reservation, outcome, cost: ledger.settled.append((reservation, outcome, cost)))
        return SimpleNamespace(agent=lambda: SimpleNamespace(cfg=cfg), hosted=SimpleNamespace(ledger=ledger)), ledger

    def test_phone_live_settle_records_once_and_settles_late_cost(self):
        phone, ledger = self.phone()
        call = {"id": str(uuid.uuid4()), "workspace_id": WORKSPACE, "user_id": USER, "voice_run_id": RUN, "live_reservation_id": RESERVATION,
                "telephony_reservation_id": str(uuid.uuid4()), "answered_at": 1_790_000_000.0}

        class Cur(FakeCursor):
            def fetchall(self):
                return [(RESERVATION, 50_000)]

        db = FakeDB()
        cur = Cur(db)
        phone_billing.settle(phone, cur, call, "live", "unknown", None)
        phone_billing.settle(phone, cur, call, "telephony", "completed", 3000)
        phone_billing.settle(phone, cur, call, "live", "completed", 75_000, audio_seconds=90)
        db.commit()
        rows = db.calls()
        self.assertEqual(len(rows), 2, "telephony is not an AI attempt")
        self.assertEqual(rows[0]["dedupe_key"], rows[1]["dedupe_key"], "the same call's audio is one attempt (the late cost settles)")
        self.assertEqual((rows[0]["status"], rows[0]["cost_usd_micro"], rows[0]["feature"]), ("unknown", None, "phone"))
        self.assertEqual((rows[1]["cost_usd_micro"], rows[1]["audio_seconds"]), (75_000, 90.0))
        self.assertEqual(len(db.statements("pr_ai_call_settlements")), 1)
        self.assertEqual([entry[1] for entry in ledger.settled], ["unknown", "completed", "completed"], "the ledger settles exactly as before")
        phone_billing.settle(phone, cur, {**call, "id": str(uuid.uuid4())}, "live", "completed", 0)
        self.assertEqual(len(db.statements("INSERT INTO public.pr_ai_call_events")), 2, "no audio is no attempt")

    def test_growth_sink_records_both_tables_and_survives_a_missing_one(self):
        db = FakeDB()
        cur = db.cursor()
        event = UsageEvent(task="radar.triage", model="typesafe-ai/jev", route="primary", status="ok", latency_ms=5, cost_usd=0.0000042, cost_source="gateway",
                           workspace_id=WORKSPACE, generation_id="gen-9", input_tokens=20, output_tokens=3)
        PostgresUsageSink(cur).record(event)
        db.commit()
        [row] = db.calls()
        self.assertEqual((row["feature"], row["workload"], row["provider"], row["cost_usd_micro"], row["cost_source"], row["provider_request_id"]),
                         ("radar", "radar.triage", "vercel-ai-gateway", 5, "gateway", "gen-9"))
        self.assertIn("pr_model_usage_events", [table for table, _ in db.committed])
        db = FakeDB(fail_on="INSERT INTO public.pr_ai_call_events")
        cur = db.cursor()
        with self.assertLogs("postriff.ai_call_events", "WARNING"):
            PostgresUsageSink(cur).record(UsageEvent(task="trend.culture_classify", model="m", route="primary", status="rate_limited", latency_ms=3))
        db.commit()
        self.assertEqual([table for table, _ in db.committed], ['pr_audit_events', "pr_model_usage_events"])

    def test_memory_sink_numbers_retries_without_changing_equality(self):
        sink = MemoryUsageSink()
        first = UsageEvent(task="postdoctor.judge", model="j", route="primary", status="rate_limited", latency_ms=5, subject="a" * 64)
        second = UsageEvent(task="postdoctor.judge", model="j", route="primary", status="ok", latency_ms=5, subject="a" * 64)
        fallback = UsageEvent(task="postdoctor.judge", model="f", route="fallback", status="ok", latency_ms=5, subject="a" * 64)
        other = UsageEvent(task="postdoctor.judge", model="j", route="primary", status="ok", latency_ms=5, subject="b" * 64)
        for event in (first, second, fallback, other):
            sink.record(event)
        self.assertEqual([event.attempt_no for event in sink.events], [1, 2, 1, 1])
        self.assertEqual(sink.events, [first, second, fallback, other])


class CallSiteScopes(Base):
    """Feature entry points that call a provider outside the writer and Agent runs attribute their attempts with a scope."""
    SITES = (("src/postriff_phase2/ideas.py", "self.image_runtime.generate(", "image"),
             ("src/postriff_phase2/learning_service.py", "model.observe(", "learning"),
             ("src/postriff_phase2/reply_writer.py", "call(system, user, SCHEMA)", "reply"),
             ("src/postriff_phase2/voice_ai.py", "runtime.analyze_voice(", "voice"),
             ("src/postriff_phase2/media_notes.py", "self.reader.read(", "notes"),
             ("src/postriff_phase2/site_agent/service.py", "call(prompts.SYSTEM_PROMPT", "site_agent"))

    def test_each_entry_point_calls_its_provider_inside_a_scope(self):
        import ast
        for path, call, feature in self.SITES:
            with self.subTest(path=path):
                source = (ROOT / path).read_text()
                found = set()
                for node in ast.walk(ast.parse(source)):
                    if not isinstance(node, ast.With):
                        continue
                    for item in node.items:
                        expr = item.context_expr
                        if isinstance(expr, ast.Call) and ast.get_source_segment(source, expr.func) == "ai_call_events.scope":
                            inner = [sub for stmt in node.body for sub in ast.walk(stmt) if isinstance(sub, ast.Call)]
                            if any(ast.get_source_segment(source, sub).startswith(call) for sub in inner):
                                found |= {kw.value.value for kw in expr.keywords if kw.arg == "feature" and isinstance(kw.value, ast.Constant)}
                self.assertEqual(found, {feature})

    def capture(self):
        captured = []
        return captured, mock.patch.object(ai_call_events, "write", side_effect=lambda rows, **_: captured.extend(rows) or len(rows))

    def test_reply_drafting_attempt_is_attributed(self):
        from postriff_phase2 import reply_writer
        from test_reply_writer import PATCHES, managed, service
        for patch in PATCHES:
            patch.start()
            self.addCleanup(patch.stop)
        answer = {"status": 200, "body": {"choices": [{"message": {"content": json.dumps({"reply": "Yes, entry is free.", "needs": [], "language": "en"})}}],
                                          "usage": {"prompt_tokens": 100, "completion_tokens": 20}}}
        call = learning_model.GatewayCall("k", model="openai/gpt-6-sol", transport=lambda *a, **k: answer, drafting=True)
        captured, patched = self.capture()
        with patched:
            written = reply_writer.write(service(managed()), WORKSPACE, "tok", "th1", call=call)
        self.assertEqual(written["costUsdMicro"], 400)
        [row] = captured
        self.assertEqual((row["feature"], row["workspace_id"], row["workload"], row["status"], row["cost_usd_micro"]), ("reply", WORKSPACE, "drafting", "ok", 400))

    def test_media_reader_attempts(self):
        from postriff_phase2 import media_notes
        from test_media_notes import Transport, cfg
        captured, patched = self.capture()
        with patched:
            with ai_call_events.scope(feature="notes", workspace_id=WORKSPACE, reservation_id=RESERVATION):
                media_notes.MediaReader(cfg(), Transport(), enabled=True).read([(b"jpegbytes", "image/jpeg")], "photo")
            with ai_call_events.scope(feature="notes", workspace_id=WORKSPACE):
                with self.assertRaises(creative.CreativeError):
                    media_notes.MediaReader(cfg(), Transport(status=429, body={}), enabled=True).read([(b"x", "image/jpeg")], "photo")
        read, busy = captured
        self.assertEqual((read["feature"], read["workload"], read["status"], read["http_status"], read["provider"], read["model"]), ("notes", "vision", "ok", 200, "openai", "gpt-6-sol"))
        self.assertEqual((read["input_tokens"], read["output_tokens"], read["cost_usd_micro"], read["cost_source"]), (1500, 350, 6500, "table:" + ai_call_events.AGENT_V2))
        self.assertEqual(read["reservation_id"], RESERVATION)
        self.assertEqual((busy["status"], busy["http_status"], busy["cost_usd_micro"]), ("rate_limited", 429, 0))


class PriceSeed(unittest.TestCase):
    """The 058 seed must equal the constants the code prices with today (a price table is never edited after the fact)."""

    def seed(self):
        sql = MIGRATION.read_text()
        return {name: json.loads(body) for name, body in re.findall(r"\('([a-z0-9.-]+)','2026-09-24T00:00:00Z',(?:'[^']*'|null),'[^']*',\s*'(\{.*?\})'::jsonb\)", sql, re.S)}

    def test_seed_matches_code(self):
        from postriff_phase2.agent_runtime_v2 import config
        seed = self.seed()
        self.assertEqual(set(seed), set(ai_call_events.PRICE_VERSIONS))
        self.assertEqual(model_runtime.DEFAULT_PRICES_VERSION, ai_call_events.GATEWAY_LIST)
        self.assertEqual({k: (v["input"], v["output"]) for k, v in seed[ai_call_events.GATEWAY_LIST]["models"].items()}, model_runtime.DEFAULT_PRICES)
        self.assertEqual({k: (v["input"], v["output"]) for k, v in seed[ai_call_events.AGENT_V2]["models"].items()}, config.DEFAULT_PRICES)
        media = seed[ai_call_events.MEDIA_CONSTANTS]
        self.assertEqual({k: media["images"][k]["usdMicroPerImage"] for k in config.DEFAULT_IMAGE_ESTIMATE_USD_MICRO}, config.DEFAULT_IMAGE_ESTIMATE_USD_MICRO)
        self.assertEqual(media["images"][image_runtime.DEFAULT_MODEL]["usdMicroPerImage"], image_runtime.DEFAULT_ESTIMATE_USD_MICRO)
        self.assertEqual(media["voice"]["usdMicroPerMinute"], config.DEFAULT_LIVE_USD_MICRO_PER_MINUTE)
        pricing = json.loads((ROOT / "docs/launch-20260923/pricing-2026-09-24.json").read_text())
        self.assertEqual(seed[ai_call_events.CUSTOMER_PRICING]["creditsPerProviderUsd"], pricing["creditsPerProviderUsd"])
        self.assertEqual(seed[ai_call_events.CUSTOMER_PRICING]["creditPolicy"], pricing["creditPolicy"])

    def test_migration_is_public_only_and_never_grants_role_membership(self):
        sql = "\n".join(line.split("--", 1)[0] for line in MIGRATION.read_text().lower().splitlines())
        self.assertNotIn("rafii_control", sql)
        self.assertNotRegex(sql, r"grant\s+[a-z_]+\s+to\s+current_user")
        self.assertNotIn("createrole", sql)


if __name__ == "__main__":
    unittest.main()
