"""D-A47: where generated views are on, the turn's admission plan also covers its presentation chain. The turn reserves its
own estimate plus the presentation allowance in ONE reservation under the same credit authority, and the view then draws only
on that portion, so a Manager turn that settles above its own estimate no longer leaves the view without room (seen in
production 2026-10-09: turn 112,163 µ$ of an 88,000 µ$ estimate → presentation refused 'budget')."""
import contextlib
import unittest

from postriff_phase2.agent_runtime_v2 import ui_metering
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService

from test_agent_ui_stream_fakes import make_cfg


class _Cursor:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return ("run-1",)


class _Repo:
    def __init__(self):
        self.cur = _Cursor()

    @contextlib.contextmanager
    def transaction(self, token, workspace_id):
        yield self.cur, (7,), "member-1"


class _Ideas:
    def _append_message(self, *args, **kwargs):
        pass

    def _insert_event(self, *args, **kwargs):
        pass


class _Ledger:
    def __init__(self):
        self.calls = []

    def reserve(self, cur, workspace_id, member_id, dimension, estimate, key, **kw):
        self.calls.append({"estimate": estimate, "key": key, **kw})
        return {"reservationId": "res-1"}


class _Service:
    def __init__(self):
        self.repository, self.ideas, self.ledger = _Repo(), _Ideas(), _Ledger()


def open_run(cfg):
    service = _Service()
    rt = AgentRuntimeService(service, cfg, model_factory=None, clock=lambda: 0)
    rt._reap_stale_turns = lambda cur, workspace_id: None
    approvals = []
    rt._reservation_approval = lambda cur, ws, principal, revision, cost, route, run_id: (approvals.append(cost) or (None, {}))
    run_id, reservation = rt._open_run("ws-1", "token", "conv-1", "Show my drafts", "text", "agent:k1", "trace_1", [],
                                       model="rafii-agent", reserve_for="standard_reasoning")
    return service.ledger.calls, reservation, approvals, cfg


class TurnAllowance(unittest.TestCase):
    def test_genui_turn_reserves_estimate_plus_presentation_allowance_once(self):
        calls, reservation, approvals, cfg = open_run(make_cfg())
        route = cfg.route("standard_reasoning", reason="test")
        estimate = cfg.estimate_usd_micro(route.model, 24_000, 4_000)
        allowance = ui_metering.presentation_allowance(cfg)
        self.assertIsInstance(allowance, int)
        self.assertGreater(allowance, 0)
        self.assertEqual(len(calls), 1, "one reservation covers the whole admission plan")
        self.assertEqual(calls[0]["key"], "agent:run-1")
        self.assertEqual(calls[0]["estimate"], estimate + allowance)
        self.assertEqual(calls[0]["meta"]["uiAllowanceUsdMicro"], str(allowance))
        self.assertEqual(approvals, [estimate + allowance], "the credit authority approves the combined plan")
        self.assertEqual(reservation["estimateUsdMicro"], estimate, "follow-up chips still fit inside the turn's own share")

    def test_turn_without_generated_views_reserves_only_its_estimate(self):
        calls, reservation, approvals, cfg = open_run(make_cfg(RAFII_GENUI_ENABLED=None))
        route = cfg.route("standard_reasoning", reason="test")
        estimate = cfg.estimate_usd_micro(route.model, 24_000, 4_000)
        self.assertEqual(calls[0]["estimate"], estimate)
        self.assertNotIn("uiAllowanceUsdMicro", calls[0]["meta"])
        self.assertEqual(approvals, [estimate])

    def test_canary_workspace_outside_the_allowlist_reserves_only_its_estimate(self):
        calls, _reservation, _approvals, cfg = open_run(make_cfg(RAFII_GENUI_WORKSPACES="some-other-workspace"))
        self.assertNotIn("uiAllowanceUsdMicro", calls[0]["meta"])

    def test_allowance_covers_an_initial_attempt_and_its_repair_at_worst_case_input(self):
        cfg = make_cfg()
        from postriff_phase2.agent_runtime_v2.ui_presenter import MAX_OUTPUT_TOKENS, WORKLOAD
        route = cfg.route(WORKLOAD, reason="test")
        one = cfg.estimate_usd_micro(route.model, -(-ui_metering.ALLOWANCE_PROMPT_BYTES // 3) + 16, MAX_OUTPUT_TOKENS)
        self.assertEqual(ui_metering.presentation_allowance(cfg), 2 * one)


if __name__ == "__main__":
    unittest.main()
