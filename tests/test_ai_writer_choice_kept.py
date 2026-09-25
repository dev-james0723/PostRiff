"""The writer a person chose travels with their request: the source-to-campaign agent tool passes it on, and a
Manager run paused for an approval keeps it when it resumes. Only a request with no choice uses the default."""
import unittest
from contextlib import contextmanager
from unittest import mock


class Ledger:
    def __init__(self):
        self.changed, self.refs = [], []

    def reference(self, *args):
        self.refs.append(args)


def run_tool(writer_model):
    from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter
    from postriff_phase2.coworker import flags
    domain_tools.ensure_registered()

    class Coworker:
        payloads = []

        def source_campaign(self, workspace_id, token, payload):
            self.payloads.append(payload)
            return {"sourceCampaign": {"drafts": [], "campaignId": None, "status": "needs_source", "factPack": {"claims": []}, "brief": {"exclusions": [], "goal": "g"}},
                    "verified": True}

    class Ctx:
        workspace_id, token = "ws", "tok"
        ledger = Ledger()
        service = type("S", (), {"coworker": Coworker()})()

        def remaining(self):
            return None

        @contextmanager
        def workspace(self):
            yield None, None, None, None, {}

    ctx = Ctx()
    ctx.writer_model = writer_model
    saved = flags._values
    flags.attach({"RAFII_RESEARCH_BROKER_ENABLED": "1"})
    try:
        with mock.patch("postriff_phase2.coworker.agent_tools._service", return_value=ctx.service):
            tool_adapter.REGISTRY["source_campaign_create"].executor(ctx, {"format": "text", "text": "A new shop opens on Friday.", "channelIds": ["ch1"]})
    finally:
        flags._values = saved
    return ctx.service.coworker.payloads[-1]


class ChosenWriterTest(unittest.TestCase):
    def test_the_source_campaign_tool_passes_the_chosen_writer(self):
        self.assertEqual(run_tool("deterministic-preview")["model"], "deterministic-preview")
        self.assertEqual(run_tool("openai/gpt-6-sol")["model"], "openai/gpt-6-sol")
        self.assertNotIn("model", run_tool(None), "no choice: the server's default writer decides")

    def test_a_paused_run_stores_the_writer_for_its_resume(self):
        from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService

        class Cursor:
            def __init__(self):
                self.updates = []

            def execute(self, sql, params=None):
                if sql.startswith("UPDATE"):
                    self.updates.append(params)

            def fetchone(self):
                return ({},)

        cur = Cursor()
        runtime = AgentRuntimeService.__new__(AgentRuntimeService)
        runtime.clock = lambda: 1_790_000_000
        runtime._store_pending_run(cur, "ws", "task-1", {"s": 1}, [], writer_model="deterministic-preview")
        import json
        self.assertEqual(json.loads(cur.updates[0][0])["pendingRun"]["writerModel"], "deterministic-preview")


if __name__ == "__main__":
    unittest.main()
