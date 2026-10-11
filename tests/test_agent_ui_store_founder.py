"""Lane F: the founder Generative UI routes (/api/control/v2/agent/ui/*, A-DECISIONS D-A22) with the store and stream faked.

What is pinned: scope and surface are server decisions (a client naming them is refused), the data mode comes from the run or
artifact itself, founder idempotency keys are namespaced, the founder transport drains the stream into one JSON answer and
polls durable events, reads keep working with the feature off while new presentations and queries are refused, and there is no
action route. The real store behaviour under these routes is covered by tests/phase2/postgres_agent_ui_store.py (F-S16).
"""
import contextlib
import unittest

try:
    from rafii_control import founder_agent, founder_agent_ui as ui
    from rafii_control.auth import ControlError
    from postriff_alpha.domain import AlphaError
    from postriff_phase2.agent_runtime_v2 import ui_contracts as contracts, ui_http, ui_store, ui_stream, ui_queries
    AVAILABLE = True
except ImportError:          # the founder runtime imports the Agents SDK; cloud CI installs it
    AVAILABLE = False

ART = "22222222-2222-4222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
MSG = "55555555-5555-4555-8555-555555555555"
OPS = "66666666-6666-4666-8666-666666666666"
OPERATOR = "77777777-7777-4777-8777-777777777777"


class Cursor:
    def __init__(self, rows):
        self.rows, self.last = rows, None

    def execute(self, sql, params=()):
        self.last = (sql, params)

    def fetchone(self):
        sql = self.last[0]
        for needle, row in self.rows.items():
            if needle in sql:
                return row
        return None


class Recorder:
    """Patches module attributes for one test and records the calls."""

    def __init__(self, test):
        self.calls, self._undo = [], []
        test.addCleanup(self.restore)

    def patch(self, owner, name, value):
        self._undo.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def restore(self):
        for owner, name, value in reversed(self._undo):
            setattr(owner, name, value)


def frames(*events):
    return [contracts.sse_frame(e) for e in events]


@unittest.skipUnless(AVAILABLE, "rafii_control founder runtime needs the Agents SDK (cloud CI)")
class FounderRoutes(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder(self)
        self.flags = {"enabled": True, "actions": False, "edits": True}
        self.rows = {"FROM public.pr_ui_artifacts": ("founder", "founder:live:production", OPERATOR), "FROM public.pr_messages": (RUN,)}
        test = self

        class FakeScope:
            def __init__(self, consumer, principal, control, request_id, mode):
                self.mode, self.ops, self.capability, self.environment, self.operator = mode, OPS, object(), "production", OPERATOR
                self.namespace = f"founder:{mode}:production"
                self.runtime = type("Runtime", (), {"founder": {"namespace": self.namespace}})()
                test.rec.calls.append(("scope", mode))

            def flags(self):
                return test.flags

            @contextlib.contextmanager
            def transaction(self):
                yield Cursor(test.rows), None, OPERATOR

        self.rec.patch(ui, "_Scope", FakeScope)
        self.rec.patch(founder_agent, "_founder_run", lambda cur, ops, run_id, operator: ("live", "production") if run_id == RUN else None)
        self.rec.patch(ui_store, "snapshot_http", lambda runtime, w, token, a: {"artifact": {"artifactId": a}, "scope": runtime.founder["namespace"]})
        self.rec.patch(ui_store, "by_message_http", lambda runtime, w, token, m: {"messageId": m, "artifacts": []})

    def call(self, method, path, body=None, query=None):
        return ui.handle(object(), {"operator": {"user_id": OPERATOR}, "session": {"environment": "production"}}, method, path, body or {}, query or {}, "req-1",
                         control=object())

    def test_presentation_is_namespaced_founder_and_drained(self):
        seen = {}

        def create(runtime, environ, start_response, workspace_id, token, request):
            seen.update(request=request, workspace=workspace_id, founder=environ.get("rafii.founder"))
            start = contracts.make_event(ART, RUN, 0, 1, "ui.started", {})
            ready = contracts.make_event(ART, RUN, 1, 3, "ui.ready", {"sourceHash": "a" * 64})
            raw = b"".join(frames(start, ready))
            return [raw[:7], raw[7:40], raw[40:]]                       # frames split across chunks
        self.rec.patch(ui_stream, "create_presentation", create)
        out = self.call("POST", "/agent/ui/presentations", {"parentRunId": RUN, "idempotencyKey": "k" * 24})
        request = seen["request"]
        self.assertEqual(request["surface"], "founder")
        self.assertEqual(request["idempotencyKey"], ui.scoped_key("founder:live:production", "k" * 24))
        self.assertTrue(contracts.valid_idempotency_key(request["idempotencyKey"]))
        self.assertEqual(seen["workspace"], OPS)
        self.assertEqual(out["outcome"]["terminal"]["kind"], "ui.ready")
        self.assertEqual(out["outcome"]["artifactId"], ART)
        self.assertEqual(out["view"]["scope"], "founder:live:production")
        self.assertEqual(out["_dataState"], "not_applicable")

    def test_client_cannot_name_scope_or_surface(self):
        for field in ("isFounder", "scope", "surface", "mode", "scopeKey"):
            with self.assertRaises(ControlError) as raised:
                self.call("POST", "/agent/ui/presentations", {"parentRunId": RUN, "idempotencyKey": "k" * 24, field: True})
            self.assertEqual(raised.exception.code, "VALIDATION_FAILED")

    def test_unknown_run_or_other_environment_is_404(self):
        with self.assertRaises(ControlError) as raised:
            self.call("POST", "/agent/ui/presentations", {"parentRunId": "88888888-8888-4888-8888-888888888888", "idempotencyKey": "k" * 24})
        self.assertEqual(raised.exception.status, 404)
        self.rows["FROM public.pr_ui_artifacts"] = ("founder", "founder:live:staging", OPERATOR)
        with self.assertRaises(ControlError) as raised:
            self.call("GET", f"/agent/ui/presentations/{ART}")
        self.assertEqual(raised.exception.status, 404)
        self.rows["FROM public.pr_ui_artifacts"] = ("workspace", "", OPERATOR)              # a consumer view is never served here
        with self.assertRaises(ControlError) as raised:
            self.call("GET", f"/agent/ui/presentations/{ART}")
        self.assertEqual(raised.exception.status, 404)
        self.rows["FROM public.pr_ui_artifacts"] = ("founder", "founder:live:production", "99999999-9999-4999-8999-999999999999")
        with self.assertRaises(ControlError):
            self.call("GET", f"/agent/ui/presentations/{ART}")                               # another operator's view

    def test_mode_comes_from_the_artifact(self):
        self.rows["FROM public.pr_ui_artifacts"] = ("founder", "founder:demo:production", OPERATOR)
        out = self.call("GET", f"/agent/ui/presentations/{ART}")
        self.assertEqual(out["scope"], "founder:demo:production")
        self.assertIn(("scope", "demo"), self.rec.calls)

    def test_disabled_refuses_new_work_but_reads_still_serve(self):
        self.flags = {"enabled": False}
        with self.assertRaises(ControlError) as raised:
            self.call("POST", "/agent/ui/presentations", {"parentRunId": RUN, "idempotencyKey": "k" * 24})
        self.assertEqual((raised.exception.code, getattr(raised.exception, "blocker", None)), ("POLICY_DISABLED", "genui_disabled"))
        with self.assertRaises(ControlError):
            self.call("POST", "/agent/ui/queries", {"artifactId": ART, "artifactRevision": 1, "bindingId": "mrr_summary", "inputs": {}})
        self.assertEqual(self.call("GET", f"/agent/ui/presentations/{ART}")["artifact"]["artifactId"], ART)
        self.assertEqual(self.call("GET", f"/agent/ui/messages/{MSG}")["messageId"], MSG)

    def test_events_poll_durable_replay_only(self):
        seen = {}

        @contextlib.contextmanager
        def transaction(runtime, token, workspace_id, need="read"):
            seen["need"] = need
            yield object(), object()
        self.rec.patch(ui_http, "ui_transaction", transaction)
        self.rec.patch(ui_store, "replay_view", lambda cur, auth, a, after, limit=None: {"events": [], "cursor": after, "done": True})
        out = self.call("GET", f"/agent/ui/presentations/{ART}/events", query={"after": ["7"]})
        self.assertEqual((out["cursor"], seen["need"]), (7, "read"))
        with self.assertRaises(ControlError):
            self.call("GET", f"/agent/ui/presentations/{ART}/events", query={"after": ["-1"]})
        with self.assertRaises(ControlError):
            self.call("GET", f"/agent/ui/presentations/{ART}/events", query={"after": ["x"]})

    def test_no_action_routes_and_unknown_paths(self):
        for method, path in (("POST", "/agent/ui/actions"), ("POST", "/agent/ui/actions/activate"), ("GET", "/agent/ui/"), ("DELETE", f"/agent/ui/presentations/{ART}")):
            with self.assertRaises(ControlError, msg=path) as raised:
                self.call(method, path, {})
            self.assertEqual(raised.exception.status, 404)

    def test_state_conflict_is_stale_preview(self):
        def conflict(*_args):
            raise ui_store.StateConflict({"stateRevision": 3, "safeState": {}})
        self.rec.patch(ui_store, "persist_state_http", conflict)
        with self.assertRaises(ControlError) as raised:
            self.call("POST", f"/agent/ui/presentations/{ART}/state", {"expectedStateRevision": 1, "patch": {"$period": "7d"}})
        self.assertEqual((raised.exception.code, raised.exception.status), ("STALE_PREVIEW", 409))

    def test_store_refusals_map_to_control_codes(self):
        def refuse(*_args):
            raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
        self.rec.patch(ui_store, "snapshot_http", refuse)
        with self.assertRaises(ControlError) as raised:
            self.call("GET", f"/agent/ui/presentations/{ART}")
        self.assertEqual(raised.exception.status, 404)

    def test_queries_reach_the_query_binding_in_founder_scope(self):
        seen = {}

        def query(runtime, workspace_id, token, request):
            seen.update(request=request, scope=runtime.founder["namespace"])
            return contracts.query_result("available", {"rows": []}, as_of="2026-10-08T00:00:00Z")
        self.rec.patch(ui_queries, "query_http", query)
        out = self.call("POST", "/agent/ui/queries", {"artifactId": ART, "artifactRevision": 1, "bindingId": "mrr_summary", "inputs": {}})
        self.assertEqual((out["state"], out["_dataState"], seen["scope"]), ("available", "measured", "founder:live:production"))


class Drain(unittest.TestCase):
    @unittest.skipUnless(AVAILABLE, "rafii_control founder runtime needs the Agents SDK (cloud CI)")
    def test_drain_closes_and_keeps_the_terminal_event(self):
        closed = []

        class Stream(list):
            def close(self):
                closed.append(True)
        failed = contracts.make_event(ART, RUN, 0, 4, "ui.failed", {"reason": "provider_timeout"})
        out = ui.drain(Stream([b": comment\n\n", contracts.sse_frame(failed)]))
        self.assertEqual(out["terminal"], {"kind": "ui.failed", "reason": "provider_timeout", "seq": 4})
        self.assertEqual(closed, [True])

    @unittest.skipUnless(AVAILABLE, "rafii_control founder runtime needs the Agents SDK (cloud CI)")
    def test_scoped_keys_differ_by_namespace(self):
        live, demo = ui.scoped_key("founder:live:production", "k" * 24), ui.scoped_key("founder:demo:production", "k" * 24)
        self.assertNotEqual(live, demo)
        self.assertTrue(live.startswith("fdr_") and contracts.valid_idempotency_key(live))


if __name__ == "__main__":
    unittest.main()
