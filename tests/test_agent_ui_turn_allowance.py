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


def open_run(cfg, *, text="Show my drafts", modality="text", delegation_id=None, refuse_first=None, prepare=None):
    service = _Service()
    rt = AgentRuntimeService(service, cfg, model_factory=None, clock=lambda: 0)
    rt._reap_stale_turns = lambda cur, workspace_id: None
    approvals = []
    rt._reservation_approval = lambda cur, ws, principal, revision, cost, route, run_id: (approvals.append(cost) or (None, {}))
    if refuse_first is not None:
        original = service.ledger.reserve
        def reserve(*args, **kwargs):
            if not service.ledger.calls and not getattr(reserve, "refused", False):
                reserve.refused = True
                raise refuse_first
            return original(*args, **kwargs)
        service.ledger.reserve = reserve
    if prepare is not None:
        prepare(rt)
    run_id, reservation = rt._open_run("ws-1", "token", "conv-1", text, modality, "agent:k1", "trace_1", [],
                                       model="rafii-agent", reserve_for="standard_reasoning", delegation_id=delegation_id)
    return service.ledger.calls, reservation, approvals, cfg


def turn_estimate(cfg):
    route = cfg.route("standard_reasoning", reason="test")
    return cfg.estimate_usd_micro(route.model, 24_000, 4_000)


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


class TurnsThatCannotPresent(unittest.TestCase):
    def assert_estimate_only(self, calls, cfg):
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["estimate"], turn_estimate(cfg))
        self.assertNotIn("uiAllowanceUsdMicro", calls[0]["meta"])

    def test_voice_without_a_request_for_a_view(self):
        calls, _r, _a, cfg = open_run(make_cfg(), text="What's on today?", modality="voice")
        self.assert_estimate_only(calls, cfg)

    def test_voice_that_asks_for_a_view_gets_the_allowance(self):
        calls, _r, _a, cfg = open_run(make_cfg(), text="Show my drafts in a table", modality="voice")
        self.assertIn("uiAllowanceUsdMicro", calls[0]["meta"])

    def test_greeting_or_acknowledgement(self):
        for text in ("hi", "thanks", "好的"):
            calls, _r, _a, cfg = open_run(make_cfg(), text=text)
            self.assert_estimate_only(calls, cfg)

    def test_delegated_turn(self):
        calls, _r, _a, cfg = open_run(make_cfg(), delegation_id="d-1")
        self.assert_estimate_only(calls, cfg)

    def test_credit_authorised_turn_keeps_the_managers_own_quote(self):
        def credit(rt):
            rt.reservation_approval = lambda *args: ("authority", {})
        calls, _r, _a, cfg = open_run(make_cfg(), prepare=credit)
        self.assert_estimate_only(calls, cfg)

    def test_founder_turn_with_founder_views_off(self):
        def founder(rt):
            rt.founder = {"namespace": "founder:live"}
        calls, _r, _a, cfg = open_run(make_cfg(RAFII_GENUI_FOUNDER_ENABLED=None), prepare=founder)
        self.assert_estimate_only(calls, cfg)
        calls_on, _r, _a, _cfg = open_run(make_cfg(), prepare=founder)
        self.assertIn("uiAllowanceUsdMicro", calls_on[0]["meta"])

    def test_an_allowance_that_cannot_be_computed_never_refuses_the_turn(self):
        from unittest import mock
        with mock.patch.object(ui_metering, "presentation_allowance", side_effect=RuntimeError("boom")):
            calls, _r, _a, cfg = open_run(make_cfg())
        self.assert_estimate_only(calls, cfg)

    def test_a_budget_stop_on_the_combined_plan_admits_the_turn_alone(self):
        from postriff_alpha.domain import AlphaError
        for error in (AlphaError("stop", 402, code="budget_exhausted"), AlphaError("slow down", 429, code="rate"),
                      AlphaError("cap", 409, code="founder_budget")):
            calls, reservation, approvals, cfg = open_run(make_cfg(), refuse_first=error)
            self.assert_estimate_only(calls, cfg)
            self.assertEqual(approvals, [turn_estimate(cfg) + ui_metering.presentation_allowance(cfg), turn_estimate(cfg)])
            self.assertEqual(reservation["estimateUsdMicro"], turn_estimate(cfg))

    def test_other_refusals_still_refuse_the_turn(self):
        from postriff_alpha.domain import AlphaError
        with self.assertRaises(AlphaError):
            open_run(make_cfg(), refuse_first=AlphaError("conflict", 409, code="other_conflict"))


if __name__ == "__main__":
    unittest.main()
