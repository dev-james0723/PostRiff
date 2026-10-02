"""G2-OUT agent tools (AC28): typed effects, same permission as the routes, idempotent per run, flag-gated."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import contracts, tool_adapter
from postriff_phase2.agent_runtime_v2.context import EffectLedger
from postriff_phase2.results import agent_tools, service


class FakeResults:
    def __init__(self):
        self.calls = []
        self.seen_keys = set()

    def clock(self):
        return 1_790_870_000.0

    def summary(self, workspace_id, token, start, end):
        self.calls.append(("summary", start, end))
        return {"classes": {"provider_native": None, "first_party_reported": None, "user_declared": {"counts": {"lead": 2}, "money": {}, "reversed": 0,
                                                                                                      "unattributed": 2, "associated": 0}},
                "dataState": "partial", "period": {"open": True}, "clicks": None, "testEvents": 0, "quarantined": 0, "coverage": {}}

    def declare(self, workspace_id, token, payload):
        if token == "viewer":
            raise AlphaError("This action needs the 'edit' permission in this workspace.", 403)
        replayed = payload["idempotencyKey"] in self.seen_keys
        self.seen_keys.add(payload["idempotencyKey"])
        self.calls.append(("declare", payload))
        return {"result": {"id": "r1", "type": payload["type"]}, "replayed": replayed}

    def create_link(self, workspace_id, token, payload):
        self.calls.append(("create_link", payload))
        return {"link": {"id": "l1", "label": "example.org", "url": None, "path": "/api/l/x", "destination": payload["destination"],
                         "campaignRef": None, "status": "active", "windowDays": 30}, "replayed": False}


def context(results, token="editor", run_id="run-1"):
    return SimpleNamespace(service=SimpleNamespace(results=results), workspace_id="w1", token=token, run_id=run_id, trace_id="t1",
                           ledger=EffectLedger())


class AgentToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agent_tools.register()
        agent_tools.register()   # idempotent

    def test_ac28_specs_are_typed_and_identical_for_voice(self):
        specs = {name: tool_adapter.REGISTRY[name].spec for name in ("results_summary", "result_declare", "tracking_link_create")}
        self.assertEqual((specs["results_summary"].effect, specs["results_summary"].permission), (contracts.READ, "read"))
        self.assertEqual((specs["result_declare"].effect, specs["result_declare"].permission), (contracts.MUTATE_REVERSIBLE, "edit"))
        self.assertEqual((specs["tracking_link_create"].effect, specs["tracking_link_create"].permission), (contracts.MUTATE_REVERSIBLE, "edit"))
        self.assertTrue(all(spec.voice and not spec.approval for spec in specs.values()))

    def test_flag_off_answers_feature_disabled(self):
        with patch.object(service, "enabled", return_value=False):
            for name, args in (("results_summary", {}), ("result_declare", {"type": "lead", "occurredAt": "2026-10-01T10:00:00Z"}),
                               ("tracking_link_create", {"destination": "https://example.org/"})):
                self.assertEqual(tool_adapter.REGISTRY[name].executor(context(FakeResults()), args)["code"], "feature_disabled")

    def test_summary_labels_classes_and_never_blends(self):
        results = FakeResults()
        with patch.object(service, "enabled", return_value=True):
            out = tool_adapter.REGISTRY["results_summary"].executor(context(results), {"days": 7})
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["classes"]["user_declared"]["label"], "You reported")
        self.assertEqual(out["data"]["classes"]["provider_native"], {"label": "Platform-reported", "available": False})
        self.assertNotIn("total", out["data"])
        self.assertEqual(results.calls[0][2] - results.calls[0][1], 7 * 86400)

    def test_declare_is_idempotent_per_run_and_records_one_effect(self):
        results = FakeResults()
        ctx = context(results)
        args = {"type": "sale", "occurredAt": "2026-10-01T10:00:00Z", "amountMinor": 12000, "currency": "usd"}
        with patch.object(service, "enabled", return_value=True):
            first = tool_adapter.REGISTRY["result_declare"].executor(ctx, args)
            again = tool_adapter.REGISTRY["result_declare"].executor(ctx, args)
            other_run = tool_adapter.REGISTRY["result_declare"].executor(context(results, run_id="run-2"), args)
        self.assertTrue(first["ok"] and again["ok"] and other_run["ok"])
        self.assertTrue(again["replayed"])
        self.assertFalse(other_run["replayed"])
        self.assertEqual(len(ctx.ledger.changed), 1)
        payload = results.calls[0][1]
        self.assertEqual(payload["amount"], {"minor": 12000, "currency": "usd"})
        self.assertRegex(payload["idempotencyKey"], r"^agent-[0-9a-f]{40}$")

    def test_declare_refusals_are_typed(self):
        results = FakeResults()
        with patch.object(service, "enabled", return_value=True):
            half = tool_adapter.REGISTRY["result_declare"].executor(context(results), {"type": "sale", "occurredAt": "2026-10-01T10:00:00Z", "amountMinor": 5})
            viewer = tool_adapter.REGISTRY["result_declare"].executor(context(results, token="viewer"), {"type": "lead", "occurredAt": "2026-10-01T10:00:00Z"})
        self.assertEqual(half["code"], "tool_input")
        self.assertEqual((viewer["ok"], viewer["code"]), (False, "permission_denied"))

    def test_link_tool_reports_the_saved_link(self):
        results = FakeResults()
        ctx = context(results)
        with patch.object(service, "enabled", return_value=True):
            out = tool_adapter.REGISTRY["tracking_link_create"].executor(ctx, {"destination": "https://example.org/book"})
        self.assertTrue(out["ok"] and out["verified"])
        self.assertEqual(out["link"]["destination"], "https://example.org/book")
        self.assertEqual(ctx.ledger.references[0]["type"], "tracking_link")


if __name__ == "__main__":
    unittest.main()
