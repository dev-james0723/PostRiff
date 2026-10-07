"""Agent runtime × founder tenant (CONTRACTS §4): the gate's tenant check, the founder scope helper, the two Managers'
disjoint tool sets, the harness steps for the PRD's example questions and the founder forbidden-effect patterns.

Deterministic and database-free, like tests/test_agent_runtime.py: the Agents SDK's ScriptedModel, fake services.
"""
import asyncio
import json
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agents import RunConfig, Runner  # noqa: E402
from agents.testing import ScriptedModel, assistant_message, function_call  # noqa: E402

from postriff_phase2.agent_runtime_v2 import config, contracts, context as rt_context, domain_tools, manager, tool_adapter  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402
from rafii_control import founder_agent, founder_prompts, founder_tools  # noqa: E402

domain_tools.ensure_registered()
NOW = 1_790_000_000.0
PRINCIPAL = dict(operator=dict(user_id="00000000-0000-0000-0000-000000000001", role="founder", status="active", environment="local", auth_epoch=1,
                               capabilities=["control.read", "copilot.use", "metrics.query", "customers.read", "workspaces.read"]),
                 session=dict(id="s", environment="local", assurance="aal2", auth_epoch=1, revoked_at=None, expires_at=4102444800))
QUESTIONS = {"今個月 AI 成本為甚麼上升？": [("founder_cost_breakdown", {"dimension": "feature", "period": "mtd", "compare": True}), ("founder_attention_list", {"limit": 5})],
             "哪個 plan 的使用成本最高？": [("founder_cost_breakdown", {"dimension": "plan", "period": "mtd"}), ("founder_metric_query", {"metricIds": ["mrr"], "period": "mtd", "groupBy": ["plan"]})],
             "哪些客戶快用完額度？": [("founder_entity_search", {"collection": "workspaces", "search": "", "view": "quota_80"})],
             "今日發布失敗影響了誰？": [("founder_metric_query", {"metricIds": ["publish_outcomes"], "period": "today", "groupBy": ["status"]}), ("founder_attention_list", {"limit": 5})],
             "這張 retention 圖真正代表什麼？": [("founder_chart_explain", {"chartId": "retention"})],
             "先草擬一封付款提醒給我看。": [("founder_draft_message", {"kind": "payment_reminder"})],
             "整理今日最需要我處理的三件事。": [("founder_attention_list", {"limit": 3}), ("founder_source_health", {})]}


class FakeRepository:
    @contextmanager
    def transaction(self, token, workspace_id):
        yield None, ("row",), "owner-1"


class FakeIdeas:
    def _member(self, row):
        return Membership.from_row("owner")

    def _state(self, row):
        return {}


class FakeService:
    def __init__(self):
        self.repository, self.ideas = FakeRepository(), FakeIdeas()


def make_ctx(founder=False, **kw):
    ctx = rt_context.RafiiRunContext(service=FakeService(), workspace_id="ws-one", token="t", principal="owner-1", membership=Membership.from_row("owner"), conversation_id="conv-1",
                                     trace_id=contracts.new_trace_id(), zone="Asia/Hong_Kong", now=lambda: NOW, config=config.RuntimeConfig.from_environment({}), **kw)
    if founder:
        ctx.extra = {"founder": founder_agent.founder_scope_for(PRINCIPAL, "live", None, {}, str(uuid.uuid4()))}
    return ctx


class TenantGateTest(unittest.TestCase):
    def test_scope_helper_reads_only_a_real_founder_scope(self):
        self.assertIsNone(tool_adapter.founder_scope(make_ctx()))
        ctx = make_ctx()
        ctx.extra = {"founder": {}}
        self.assertIsNone(tool_adapter.founder_scope(ctx), "an empty scope is no scope")
        ctx.extra = {"founder": "yes"}
        self.assertIsNone(tool_adapter.founder_scope(ctx), "a scope is a dict set by founder_agent, never a flag")
        founder = make_ctx(founder=True)
        self.assertEqual(tool_adapter.founder_scope(founder)["mode"], "live")
        self.assertEqual(tool_adapter.founder_scope(founder.for_agent("specialist"))["mode"], "live", "a view of the context keeps the scope")

    def test_founder_tools_run_only_in_a_founder_turn_and_workspace_tools_never_do(self):
        customer, founder = make_ctx(), make_ctx(founder=True)
        blocked = tool_adapter.execute(customer, tool_adapter.REGISTRY["founder_source_health"], {})
        self.assertEqual((blocked["ok"], blocked["code"]), (False, "tool_tenant"))
        self.assertEqual(customer.ledger.tool_activity[0]["status"], "blocked")
        blocked = tool_adapter.execute(founder, tool_adapter.REGISTRY["workspace_summary"], {})
        self.assertEqual((blocked["ok"], blocked["code"]), (False, "tool_tenant"))
        self.assertEqual(founder.ledger.tool_activity[0]["status"], "blocked")
        for name in founder_tools.FOUNDER_TOOL_NAMES:
            with self.subTest(tool=name):
                self.assertEqual(tool_adapter.tenant_mismatch(customer, tool_adapter.REGISTRY[name].spec) is not None, True)
                self.assertIsNone(tool_adapter.tenant_mismatch(founder, tool_adapter.REGISTRY[name].spec))
        for name in ("workspace_summary", "draft_edit", "schedule_propose", "campaign_list"):
            with self.subTest(tool=name):
                self.assertIsNotNone(tool_adapter.tenant_mismatch(founder, tool_adapter.REGISTRY[name].spec))
                self.assertIsNone(tool_adapter.tenant_mismatch(customer, tool_adapter.REGISTRY[name].spec))
        # The tenant check comes before the schema and the executor: a founder tool in a customer turn never reads anything.
        self.assertEqual(founder.extra["founder"]["receipts"], [])

    def test_registry_invariants_still_hold_with_the_founder_tools(self):
        for name in founder_tools.FOUNDER_TOOL_NAMES:
            tool = tool_adapter.REGISTRY[name]
            self.assertNotIn(tool.spec.effect, contracts.FORBIDDEN_EFFECTS, name)
            if tool.spec.effect == contracts.PREPARE_EXTERNAL:
                self.assertTrue(tool.spec.approval, name)
            self.assertEqual(tool.schema["type"], "object", name)
        for word in ("publish", "approve", "reply", "delete", "disconnect", "secret", "token", "billing"):
            named = [n for n in tool_adapter.REGISTRY if word in n]
            self.assertFalse([n for n in named if tool_adapter.REGISTRY[n].spec.effect != contracts.READ], word)


class ManagersTest(unittest.TestCase):
    def test_customer_manager_has_no_founder_tools_and_the_founder_manager_only_founder_tools(self):
        customer, _ = manager.build(make_ctx(), model_factory=lambda _w, _n: ScriptedModel([]))
        customer_names = {tool.name for tool in customer.tools}
        self.assertFalse(customer_names & set(founder_tools.FOUNDER_TOOL_NAMES))
        founder, routes = founder_agent.build_manager(make_ctx(founder=True), model_factory=lambda _w, _n: ScriptedModel([]))
        self.assertEqual({tool.name for tool in founder.tools}, set(founder_tools.FOUNDER_TOOL_NAMES))
        self.assertEqual(founder.handoffs, [])
        self.assertNotIn("proposal_apply", {tool.name for tool in founder.tools})
        self.assertFalse([tool.name for tool in founder.tools if tool.name.startswith("ask_")], "no specialists in a founder turn")
        self.assertEqual(routes[0]["agent"], "rafii_founder")
        text = founder.instructions
        for rule in ("receiptId", "Never add up", "Missing data is not zero", "hypothes", "measurable experiment", "Live — the real business data", "Correlation is not causation"):
            self.assertIn(rule, text)

    def test_founder_reply_type_carries_the_four_sections(self):
        reply = founder_prompts.reply_type()(answer="a", speakable="a")
        self.assertEqual((reply.facts, reply.hypotheses, reply.recommendations, reply.unknowns, reply.language), ([], [], [], [], "en"))
        fact_type = type(reply).model_fields["facts"].annotation.__args__[0]
        self.assertEqual(fact_type(text="x", receiptId="r").receiptId, "r")

    def test_scripted_founder_manager_cannot_reach_a_workspace_tool(self):
        ctx = make_ctx(founder=True, request_text="summarise the workspace")
        scripted = ScriptedModel([[function_call("workspace_summary", {}, call_id="c1")],
                                  [assistant_message(json.dumps({"answer": "Nothing read.", "speakable": "Nothing read.", "language": "en", "follow_ups": []}))]])
        agent, _ = founder_agent.build_manager(ctx, model_factory=lambda _w, name: scripted if name == "rafii_founder" else ScriptedModel([]))
        try:
            asyncio.run(Runner.run(agent, founder_agent.assemble(ctx, "summarise the workspace", []), context=ctx, max_turns=4, run_config=RunConfig(tracing_disabled=True)))
        except Exception:  # noqa: BLE001 — the SDK refuses a tool the agent does not have; either way nothing ran
            pass
        self.assertFalse([a for a in ctx.ledger.tool_activity if a["tool"] == "workspace_summary" and a["status"] != "blocked"])

    def test_assemble_labels_the_data_mode_as_data_and_knows_the_page_ids(self):
        ctx = make_ctx(founder=True)
        ctx.extra["founder"]["context"] = {"section": "operations", "incidentId": "incident-1", "chart": {"chartId": "retention", "viewVersion": 1, "queryReceiptId": "r-1", "selection": []},
                                           "outline": [{"role": "heading", "text": "Operations"}]}
        items = founder_agent.assemble(ctx, "<script>hi</script> & more", [{"role": "user", "text": "earlier"}])
        self.assertEqual(items[0], {"role": "user", "content": "earlier"})
        content = items[-1]["content"]
        state = json.loads(content.split('<context kind="APP_STATE">\n')[1].split("\n</context>")[0].replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        self.assertEqual((state["dataMode"], state["surface"], state["founderContext"]["incidentId"], state["screen"]["items"][0]["text"]), ("live", "founder_console", "incident-1", "Operations"))
        self.assertNotIn("outline", state["founderContext"])
        self.assertIn('<request kind="USER_INSTRUCTION" modality="text">\n<script>hi</script> & more\n</request>', content)
        self.assertTrue({"incident-1", "r-1"} <= ctx.ledger.known_ids)


class HarnessStepsTest(unittest.TestCase):
    """founder_step plans the seven PRD questions from the words alone (the RAFII_AGENT_HARNESS reasoning stand-in)."""

    def step(self, text, done=(), outputs=None, context=None):
        app = json.dumps({"dataMode": "demo", "founderContext": context or {}})
        items = [{"role": "user", "content": f'<context kind="APP_STATE">\n{app}\n</context>\n<request kind="USER_INSTRUCTION" modality="text">\n{text}\n</request>'}]
        for index, name in enumerate(done):
            items += [{"type": "function_call", "call_id": f"c{index}", "name": name}, {"type": "function_call_output", "call_id": f"c{index}", "output": (outputs or {}).get(name, "{}")}]
        return founder_agent.founder_step(type("Call", (), {"input": items})())

    @staticmethod
    def called(items):
        return [(item.name, json.loads(item.arguments)) for item in items if getattr(item, "type", None) == "function_call"]

    def test_each_question_plans_its_tools_then_replies_with_receipts(self):
        for text, plan in QUESTIONS.items():
            with self.subTest(question=text):
                done = []
                for name, args in plan:
                    self.assertEqual(self.called(self.step(text, done)), [(name, args)])
                    done.append(name)
                final = self.step(text, done, outputs={done[0]: '{"receiptId": "demo-rafii-admin-demo-v1-1-normal", "rows": []}'})
                self.assertEqual(self.called(final), [])
                reply = json.loads(final[0].content[0].text)
                self.assertEqual(reply["facts"][0]["receiptId"], "demo-rafii-admin-demo-v1-1-normal")
                self.assertTrue(reply["answer"].startswith("Demo data."))
                self.assertTrue(reply["hypotheses"] and reply["recommendations"][0]["success"] and reply["unknowns"])

    def test_publish_failures_read_the_open_publishing_incident(self):
        text = "今日發布失敗影響了誰？"
        done = ["founder_metric_query", "founder_attention_list"]
        items = '{"kind": "TOOL_RESULT", "data": {"items": [{"id": "demo-billing", "title": "Failed payments", "scope": "revenue"}, {"id": "incident-demo-outage-1", "title": "Simulated publishing outage", "scope": "operations"}]}}'
        self.assertEqual(self.called(self.step(text, done, {"founder_attention_list": items})), [("founder_incident_read", {"incidentId": "incident-demo-outage-1"})])
        live = '{"kind": "TOOL_RESULT", "data": {"items": [{"id": "0f0f0f0f-0000-4000-8000-000000000001", "detector": "publish_failure_rate", "scope": "global"}]}}'
        self.assertEqual(self.called(self.step(text, done, {"founder_attention_list": live})), [("founder_incident_read", {"incidentId": "0f0f0f0f-0000-4000-8000-000000000001"})])
        self.assertEqual(self.called(self.step(text, done, {"founder_attention_list": '{"data": {"items": []}}'})), [], "no publishing incident: answer")

    def test_selected_customer_and_chart_flow_into_the_plan(self):
        context = {"selectedEntity": {"collection": "customers", "id": "customer-2"}, "chart": {"chartId": "revenue-trend", "viewVersion": 1, "queryReceiptId": "r"}}
        self.assertEqual(self.called(self.step("先草擬一封付款提醒給我看。", context=context)), [("founder_draft_message", {"kind": "payment_reminder", "customerId": "customer-2"})])
        self.assertEqual(self.called(self.step("explain this chart", context=context)), [("founder_chart_explain", {"chartId": "revenue-trend"})])

    def test_english_forms_plan_the_same_tools(self):
        self.assertEqual(self.called(self.step("Why did AI cost go up this month?"))[0][0], "founder_cost_breakdown")
        self.assertEqual(self.called(self.step("Which plan is the most expensive to serve?"))[0][0], "founder_cost_breakdown")
        self.assertEqual(self.called(self.step("Which customers are about to run out of credits?"))[0][0], "founder_entity_search")
        self.assertEqual(self.called(self.step("What are the three things I most need to handle today?"))[0][0], "founder_attention_list")


class ForbiddenEffectsTest(unittest.TestCase):
    def test_questions_and_drafts_pass_while_effects_trip(self):
        for text in list(QUESTIONS) + ["Why did the refund rate rise last month?", "草擬一封付款提醒畀我睇", "draft a payment reminder for me", "which customers were banned by Stripe?",
                                       "show me the deploy history", "寄俾我看", "how many emails did we send yesterday?"]:
            with self.subTest(text=text):
                self.assertIsNone(founder_prompts.forbidden_effect(text))
        for text, category in (("refund them all now", "refund"), ("幫佢退款", "refund"), ("ban this customer", "ban"), ("封鎖呢個客戶", "ban"), ("delete the customer records", "destructive"),
                               ("刪除客戶資料", "destructive"), ("deploy it to production", "deploy"), ("roll back the release", "deploy"), ("run this SQL for me", "shell_sql"),
                               ("DROP TABLE pr_usage_ledger", "destructive"), ("send the reminder now", "send"), ("email the customers today", "send"), ("即刻寄出", "send"), ("打電話俾客戶", "send")):
            with self.subTest(text=text):
                self.assertEqual(founder_prompts.forbidden_effect(text), category)


if __name__ == "__main__":
    unittest.main()
