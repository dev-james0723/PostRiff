"""Rafii ThinkingOps: deterministic semantic telemetry, never model prose or chain-of-thought."""
import unittest

from postriff_phase2.agent_runtime_v2 import config, context as rt_context, thinking_state


class Enabled:
    def enabled(self, name):
        return name == "RAFII_AGENT_THINKING_STATES_ENABLED"


class ThinkingStateTest(unittest.TestCase):
    def test_runtime_config_registers_the_backend_rollout_flag(self):
        cfg = config.RuntimeConfig.from_environment({"RAFII_AGENT_THINKING_STATES_ENABLED": "1"})
        self.assertTrue(cfg.enabled("RAFII_AGENT_THINKING_STATES_ENABLED"))
        self.assertTrue(cfg.public()["flags"]["RAFII_AGENT_THINKING_STATES_ENABLED"])

    def test_all_ten_ops_are_fixed_and_unknown_is_refused(self):
        self.assertEqual(
            thinking_state.OPS,
            frozenset({"working", "searching", "solving", "listening", "connecting", "weaving", "composing", "breathing", "shaping", "acting"}),
        )
        for op in thinking_state.OPS:
            self.assertEqual(thinking_state.validate_op(op), op)
        with self.assertRaises(ValueError):
            thinking_state.validate_op("publishing")

    def test_tool_mapping_is_semantic_and_proposals_are_not_actions(self):
        self.assertEqual(thinking_state.tool_op("web_research"), "searching")
        self.assertEqual(thinking_state.tool_op("draft_create"), "composing")
        self.assertEqual(thinking_state.tool_op("image_generate"), "shaping")
        self.assertEqual(thinking_state.tool_op("draft_edit"), "acting")
        self.assertEqual(thinking_state.tool_op("campaign_link"), "acting")
        self.assertEqual(thinking_state.tool_op("schedule_propose"), "solving")
        self.assertEqual(thinking_state.tool_op("automation_change_propose"), "solving")
        self.assertNotEqual(thinking_state.tool_op("proposal_apply"), "acting")
        self.assertIsNone(thinking_state.tool_op("unknown_future_tool"))

    def test_specialists_have_stable_product_states(self):
        self.assertEqual(thinking_state.specialist_op("research"), "searching")
        self.assertEqual(thinking_state.specialist_op("content"), "composing")
        self.assertEqual(thinking_state.specialist_op("creative"), "shaping")
        for name in ("brand_intelligence", "campaign", "publishing_ops", "analytics", "workspace_history"):
            self.assertEqual(thinking_state.specialist_op(name), "solving")

    def test_weaving_requires_two_distinct_evidence_channels(self):
        self.assertEqual(thinking_state.model_op("rafii_manager", []), ("solving", "manager"))
        one = [{"tool": "web_research", "agent": "research", "status": "verified"}]
        self.assertEqual(thinking_state.model_op("rafii_manager", one), ("solving", "manager"))
        two = one + [{"tool": "draft_get", "effect": "READ"}]
        # draft_get is intentionally unmapped, so this still is only one semantic evidence channel.
        self.assertEqual(thinking_state.model_op("rafii_manager", two), ("solving", "manager"))
        two.append({"tool": "draft_create", "agent": "content", "status": "verified"})
        self.assertEqual(thinking_state.model_op("rafii_manager", two), ("weaving", "manager_synthesis"))

    def test_failed_or_blocked_tools_do_not_create_weaving_evidence(self):
        activity = [
            {"tool": "web_research", "specialist": "research", "status": "verified"},
            {"tool": "draft_create", "specialist": "content", "status": "failed"},
            {"tool": "image_generate", "specialist": "creative", "status": "blocked"},
        ]
        self.assertEqual(thinking_state.model_op("rafii_manager", activity), ("solving", "manager"))
        activity[1]["status"] = "verified"
        self.assertEqual(thinking_state.model_op("rafii_manager", activity), ("weaving", "manager_synthesis"))

    def test_event_contains_only_fixed_semantic_metadata(self):
        item = thinking_state.event("searching", "tool", "web_research")
        self.assertEqual(
            item,
            {
                "type": "progress.updated",
                "stage": "agent_state",
                "thinkingOp": "searching",
                "thinkingSource": "tool",
                "reasonCode": "web_research",
            },
        )
        blob = repr(item)
        for forbidden in ("prompt", "arguments", "https://", "/Users/", "token", "secret", "user text"):
            self.assertNotIn(forbidden, blob.lower())

    def test_run_wide_dedupe_and_cap_are_shared_by_specialist_views(self):
        sent = []
        ctx = rt_context.RafiiRunContext(
            service=None,
            workspace_id="ws",
            token="session",
            principal="person",
            membership=None,
            conversation_id="conversation",
            trace_id="trace_00000000000000000000000000000000",
            config=Enabled(),
            thinking_emit=sent.append,
        )
        ctx.thinking("working", "run", "run_open")
        ctx.for_agent("research").thinking("searching", "specialist", "research")
        # Same op from another shallow context is deduped because the mutable tracker is shared.
        ctx.for_agent("research").thinking("searching", "specialist", "research")
        self.assertEqual([event["thinkingOp"] for event in sent], ["working", "searching"])

        for index in range(80):
            if index % 2:
                ctx.for_agent("research").thinking("solving", "model", "manager")
            else:
                ctx.for_agent("content").thinking("weaving", "model", "manager_synthesis")
        self.assertEqual(len(sent), 32)

    def test_telemetry_failure_never_escapes(self):
        def broken(_event):
            raise RuntimeError("telemetry down")

        ctx = rt_context.RafiiRunContext(
            service=None,
            workspace_id="ws",
            token="session",
            principal="person",
            membership=None,
            conversation_id="conversation",
            trace_id="trace_00000000000000000000000000000000",
            config=Enabled(),
            thinking_emit=broken,
        )
        ctx.thinking("working", "run", "run_open")
        self.assertEqual(ctx.thinking_tracker["count"], 0)


if __name__ == "__main__":
    unittest.main()
