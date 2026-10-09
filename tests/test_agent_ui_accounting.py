"""Lane B — ui_metering: one reservation per physical presenter attempt inside the parent turn's combined plan, settled exactly
once; unknown is never zero; refusals reserve nothing (G13, A-DECISIONS D-A23, D-A39). Ledger and SQL are faithful fakes here;
tests/phase2/postgres_agent_ui_stream.py runs the same SQL against the real Ledger on PostgreSQL.
"""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import ai_call_events
from postriff_phase2.agent_runtime_v2 import ui_metering as m

from test_agent_ui_stream_fakes import ME, WS, FakeCursor, FakeDB, FakeRuntime, make_assets, make_cfg, uid


def auth():
    return SimpleNamespace(workspace_id=WS, principal=ME, workspace_revision=7)


class Accounting(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.runtime = FakeRuntime(self.db, make_cfg(), None, make_assets())
        self.cur = FakeCursor(self.db)
        self.calls = []
        for patch in (mock.patch.object(ai_call_events, "write_attempts", lambda base, attempts, **kw: self.calls.extend({**base, **a} for a in attempts) or len(attempts)),
                      mock.patch.dict(os.environ, {"POSTRIFF_AI_PAUSED": ""})):
            patch.start()
            self.addCleanup(patch.stop)
        self.route = self.runtime.cfg.route("fast_language", reason="test")

    def attempt(self, parent, kind="generate"):
        artifact_id, attempt_id = uid(), uid()
        self.db.artifacts[artifact_id] = {"artifactId": artifact_id, "workspaceId": WS, "runId": parent, "actor": ME}
        self.db.attempts[attempt_id] = {"attemptId": attempt_id, "artifactId": artifact_id, "workspaceId": WS, "kind": kind, "reservationId": None,
                                        "providerAttempts": 0, "usage": {}, "costUsdMicro": None, "costState": "none", "state": "streaming"}
        return {"artifactId": artifact_id, "runId": parent}, {"attemptId": attempt_id, "kind": kind}

    def plan(self, ceiling, chain=m.PRESENTATION_CHAIN):
        return SimpleNamespace(route=self.route, ceiling_usd_micro=ceiling, chain=chain, prompt_hash="a" * 64)

    def test_key_run_meta_and_attempt_column(self):
        parent = self.db.add_parent()
        artifact, attempt = self.attempt(parent)
        reservation = m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(9_000))
        row = self.db.ui_reservations()[0]
        self.assertEqual(row["key"], f"agent:{parent}:ui:{attempt['attemptId']}")
        self.assertEqual(row["runId"], parent)
        self.assertEqual(row["estimate"], 9_000)
        self.assertEqual((row["meta"]["via"], row["meta"]["chain"], row["meta"]["attemptId"]), ("rafii_agent_ui", "presentation", attempt["attemptId"]))
        self.assertEqual(self.db.reserve_calls[0]["model"], "gpt-6-luna")
        self.assertEqual(self.db.attempts[attempt["attemptId"]]["reservationId"], reservation["reservationId"])
        self.assertEqual(self.db.attempts[attempt["attemptId"]]["providerAttempts"], 1)
        self.assertEqual(reservation["room"], 88_000 - 30_000)

    def test_combined_plan_counts_earlier_attempts_at_actual_or_full_hold(self):
        parent = self.db.add_parent(ceiling=88_000, spent=30_000)
        for _ in range(2):
            artifact, attempt = self.attempt(parent)
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(20_000))
        first, second = self.db.ui_reservations()
        self.runtime.service.ledger.settle(self.cur, WS, first["id"], "completed", 1_000)      # settled: its actual
        self.runtime.service.ledger.settle(self.cur, WS, second["id"], "unknown")              # unknown: the whole hold stays counted
        plan = m.allowance(self.cur, WS, parent)
        self.assertEqual(plan["room"], 88_000 - 30_000 - 1_000 - 20_000)
        artifact, attempt = self.attempt(parent)
        with self.assertRaises(AlphaError) as raised:
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(40_000))
        self.assertEqual((raised.exception.status, raised.exception.code), (402, "ui_budget"))
        self.assertEqual(len(self.db.ui_reservations()), 2, "a refusal reserves nothing")

    def test_explicit_edit_has_its_own_allowance_shared_only_with_its_repair(self):
        parent = self.db.add_parent(ceiling=10_000, spent=9_500)
        artifact, attempt = self.attempt(parent, "edit")
        chain = m.chain_for("edit", attempt["attemptId"])
        m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(8_000, chain))
        artifact2, repair = self.attempt(parent, "repair")
        with self.assertRaises(AlphaError):
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact, repair, self.plan(8_000, chain))
        self.assertEqual(m.allowance(self.cur, WS, parent, chain)["room"], 2_000)
        self.assertEqual(m.chain_for("repair", attempt["attemptId"]), chain)
        self.assertEqual(m.chain_for("generate"), m.PRESENTATION_CHAIN)
        self.assertEqual(m.chain_for("retry"), m.PRESENTATION_CHAIN)

    def test_turn_with_a_presentation_allowance_gives_the_view_exactly_that_portion(self):
        # Production 2026-10-09: the Manager settled 112,163 µ$ of its 88,000 µ$ estimate; with the D-A47 allowance the view's room
        # is its own reserved portion, not what the Manager left over.
        parent = self.db.add_parent(ceiling=88_000 + 40_000, spent=112_163, ui_allowance=40_000)
        artifact, attempt = self.attempt(parent)
        first = m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(9_000))
        self.assertEqual(first["room"], 40_000)
        self.runtime.service.ledger.settle(self.cur, WS, self.db.ui_reservations()[0]["id"], "completed", 925)
        artifact2, repair = self.attempt(parent, "repair")
        second = m.reserve_attempt(self.runtime, self.cur, auth(), artifact2, repair, self.plan(9_100))
        self.assertEqual(second["room"], 40_000 - 925)
        plan = m.allowance(self.cur, WS, parent)
        self.assertEqual((plan["allowance"], plan["room"]), (40_000, 40_000 - 925 - 9_100), "an open hold counts in full")
        artifact3, third = self.attempt(parent, "retry")
        with self.assertRaises(AlphaError) as raised:
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact3, third, self.plan(40_000))
        self.assertEqual(raised.exception.code, "ui_budget", "the chain never exceeds its reserved portion")
        # An unknown parent spend still refuses the view (unknown is never zero), allowance or not.
        parent_unknown = self.db.add_parent(ceiling=128_000, spent_state="unknown", ui_allowance=40_000)
        artifact4, attempt4 = self.attempt(parent_unknown)
        with self.assertRaises(AlphaError) as unknown:
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact4, attempt4, self.plan(9_000))
        self.assertEqual(unknown.exception.code, "ui_budget_unknown")
        # An explicit edit keeps the per-request allowance of the turn's own estimate: the presentation portion is not added.
        _artifact5, edit = self.attempt(parent, "edit")
        chain = m.chain_for("edit", edit["attemptId"])
        self.assertEqual(m.allowance(self.cur, WS, parent, chain)["room"], 88_000)

    def test_turn_without_an_allowance_keeps_the_original_combined_rule(self):
        parent = self.db.add_parent(ceiling=88_000, spent=112_163)
        artifact, attempt = self.attempt(parent)
        with self.assertRaises(AlphaError) as raised:
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(9_000))
        self.assertEqual(raised.exception.code, "ui_budget")
        self.assertNotIn("allowance", m.allowance(self.cur, WS, parent))

    def test_unmetered_or_unknown_parent_has_no_room(self):
        for kwargs in ({"ceiling": None}, {"spent_state": "unknown"}, {"spent_state": "held"}):
            parent = self.db.add_parent(**kwargs)
            artifact, attempt = self.attempt(parent)
            with self.assertRaises(AlphaError) as raised:
                m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(1_000))
            self.assertEqual(raised.exception.code, "ui_budget_unknown")
            self.assertEqual(m.reason_for(raised.exception), "budget")
        self.assertEqual(self.db.ui_reservations(), [])

    def test_paused_or_unpriced_refuse_without_a_hold(self):
        parent = self.db.add_parent()
        artifact, attempt = self.attempt(parent)
        with mock.patch.dict(os.environ, {"POSTRIFF_AI_PAUSED": "1"}):
            with self.assertRaises(AlphaError) as raised:
                m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(1_000))
        self.assertEqual(m.reason_for(raised.exception), "disabled")
        with self.assertRaises(AlphaError) as raised:
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(None))
        self.assertEqual(m.reason_for(raised.exception), "price_unknown")
        self.assertEqual(self.db.reserve_calls, [])

    def test_ledger_refusals_propagate(self):
        parent = self.db.add_parent()
        artifact, attempt = self.attempt(parent)
        self.db.reserve_error = AlphaError("Confirm this task credit limit before generating.", 402)
        with self.assertRaises(AlphaError) as raised:
            m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(1_000))
        self.assertEqual(m.reason_for(raised.exception), "budget")
        self.assertIsNone(self.db.attempts[attempt["attemptId"]]["reservationId"])

    def reserved(self):
        parent = self.db.add_parent()
        artifact, attempt = self.attempt(parent)
        reservation = m.reserve_attempt(self.runtime, self.cur, auth(), artifact, attempt, self.plan(9_000))
        return attempt, reservation["reservationId"]

    def test_known_usage_settles_completed_once_and_records_one_attempt(self):
        attempt, rid = self.reserved()
        usage = {"status": "ok", "known": True, "dispatched": True, "inputTokens": 1000, "outputTokens": 200, "model": "gpt-6-luna", "provider": "openai",
                 "requestId": "resp_x", "latencyMs": 900, "text": "must never be stored"}
        first = m.settle_attempt(self.runtime, self.cur, auth(), attempt, usage)
        second = m.settle_attempt(self.runtime, self.cur, auth(), attempt, usage)
        cost = self.runtime.cfg.estimate_usd_micro("gpt-6-luna", 1000, 200)
        self.assertEqual((first["outcome"], first["costUsdMicro"], first["costState"]), ("completed", cost, "known"))
        self.assertEqual(second["ledger"], "actual")
        settles = self.db.settlements_for(rid)
        self.assertEqual([(s["costState"], s["actual"]) for s in settles], [("actual", cost)], "exactly one terminal settlement")
        row = self.db.attempts[attempt["attemptId"]]
        self.assertEqual((row["costUsdMicro"], row["costState"]), (cost, "known"))
        self.assertNotIn("text", row["usage"])
        self.assertEqual(self.calls[0]["physical_attempt_id"], f"{attempt['attemptId']}:p1")
        self.assertEqual((self.calls[0]["workload"], self.calls[0]["feature"], self.calls[0]["status"]), ("ui_presenter", "agent", "ok"))
        self.assertEqual(self.calls[0]["cost_usd_micro"], cost)

    def test_unknown_usage_keeps_the_hold(self):
        attempt, rid = self.reserved()
        result = m.settle_attempt(self.runtime, self.cur, auth(), attempt, {"status": "cancelled", "known": False, "dispatched": True, "model": "gpt-6-luna"})
        self.assertEqual((result["outcome"], result["costUsdMicro"], result["costState"]), ("unknown", None, "unknown"))
        self.assertEqual([s["costState"] for s in self.db.settlements_for(rid)], ["estimated_unknown"])
        self.assertEqual(self.calls[0]["status"], "cancelled")
        self.assertNotIn("cost_usd_micro", self.calls[0])

    def test_not_dispatched_is_released_at_zero_without_an_attempt_row(self):
        attempt, rid = self.reserved()
        m.settle_attempt(self.runtime, self.cur, auth(), attempt, {"status": "failed", "known": True, "dispatched": False, "costUsdMicro": 0})
        self.assertEqual([(s["costState"], s["actual"]) for s in self.db.settlements_for(rid)], [("released", 0)])
        self.assertEqual(self.calls, [])

    def test_refused_by_the_provider_is_released_and_recorded(self):
        attempt, rid = self.reserved()
        m.settle_attempt(self.runtime, self.cur, auth(), attempt, {"status": "refused", "known": True, "dispatched": True, "httpStatus": 400, "model": "gpt-6-luna"})
        self.assertEqual([(s["costState"], s["actual"]) for s in self.db.settlements_for(rid)], [("released", 0)])
        self.assertEqual((self.calls[0]["status"], self.calls[0]["cost_usd_micro"], self.calls[0]["http_status"]), ("failed", 0, 400))

    def test_unpriced_known_usage_is_unknown_not_zero(self):
        attempt, rid = self.reserved()
        result = m.settle_attempt(self.runtime, self.cur, auth(), attempt, {"status": "ok", "known": True, "dispatched": True, "inputTokens": 5, "outputTokens": 5,
                                                                            "model": "gpt-unpriced-model"})
        self.assertEqual(result["costState"], "unknown")
        self.assertEqual([s["costState"] for s in self.db.settlements_for(rid)], ["estimated_unknown"])

    def test_reaper_path_settles_unknown_without_runtime_or_auth(self):
        attempt, rid = self.reserved()
        with mock.patch.object(m, "_ledger", lambda runtime: self.runtime.service.ledger):
            result = m.settle_attempt(None, self.cur, None, {**attempt, "workspaceId": WS}, {"costState": "unknown"})
        self.assertEqual(result["costState"], "unknown")
        self.assertEqual([s["costState"] for s in self.db.settlements_for(rid)], ["estimated_unknown"])

    def test_orphaned_holds_of_terminal_attempts_are_booked_unknown(self):
        attempt, rid = self.reserved()
        row = self.db.attempts[attempt["attemptId"]]
        row["state"], row["finishedLongAgo"] = "canceled", True
        self.assertEqual(m.settle_orphans(self.runtime, self.cur, WS), 1)
        self.assertEqual([s["costState"] for s in self.db.settlements_for(rid)], ["estimated_unknown"])
        self.assertEqual(row["costState"], "unknown")
        self.assertEqual(m.settle_orphans(self.runtime, self.cur, WS), 0)

    def test_cron_sweep_books_orphans_and_skips_a_busy_workspace(self):
        attempt, rid = self.reserved()
        row = self.db.attempts[attempt["attemptId"]]
        row["state"], row["finishedLongAgo"] = "canceled", True
        from test_agent_ui_stream_fakes import FakeConn
        self.db.busy_workspaces = {WS}

        class Factory:
            def __init__(inner):
                inner.conn = FakeConn(self.db)

            def __call__(inner):
                return inner

            def __enter__(inner):
                return inner.conn

            def __exit__(inner, *exc):
                return False
        self.assertEqual(m.sweep_orphans(Factory(), ledger=self.runtime.service.ledger), {"settledUnknown": 0, "providerRequests": 0})
        self.db.busy_workspaces = set()
        self.assertEqual(m.sweep_orphans(Factory(), ledger=self.runtime.service.ledger), {"settledUnknown": 1, "providerRequests": 0})
        self.assertEqual([s["costState"] for s in self.db.settlements_for(rid)], ["estimated_unknown"])

    def test_outcome_table(self):
        cfg = self.runtime.cfg
        self.assertEqual(m.outcome_of(cfg, {"costState": "unknown", "known": True, "inputTokens": 1, "outputTokens": 1, "model": "gpt-6-luna"})[0], "unknown")
        self.assertEqual(m.outcome_of(cfg, {"dispatched": False})[:2], ("failed", 0))
        self.assertEqual(m.outcome_of(cfg, {"status": "refused", "dispatched": True})[:2], ("failed", 0))
        self.assertEqual(m.outcome_of(cfg, {"status": "ok", "known": True, "dispatched": True, "costUsdMicro": 77})[:2], ("completed", 77))
        self.assertEqual(m.outcome_of(cfg, {"status": "timeout", "known": False, "dispatched": True})[0], "unknown")
        self.assertEqual(m.outcome_of(cfg, {})[0], "unknown")


if __name__ == "__main__":
    unittest.main()
