"""Founder Rafii (CONTRACTS §4): tools, scope, the seven PRD example questions, drafts that wait, namespaces, and turn().

Deterministic: the founder Manager is the Agents SDK ScriptedModel driven by founder_agent.founder_step (the QA harness
path), the Demo dataset is the coordinator's own seed with a scenario applied, Live reads go through the real QueryService
on an in-memory receipt store, and turn() runs on a fake PostgreSQL cursor that keeps runs, conversations and messages in
dicts. No network, no paid call, no database server.
"""
import asyncio
import copy
import json
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents import RunConfig, Runner
    from agents.testing import ScriptedModel, function_call
except ModuleNotFoundError as exc:  # the separate Control job installs no model SDK (requirements-control.txt); the consumer job runs these
    raise unittest.SkipTest(f"Founder Rafii tests need the consumer requirements ({exc.name} missing)") from exc

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import answer_policy, config, contracts, context as rt_context, domain_tools, tool_adapter
from postriff_phase2.permissions import Membership
from rafii_control import demo_dataset, founder_agent, founder_prompts, founder_tools
from rafii_control.auth import ControlError
from rafii_control.founder_preview_scenarios import apply_scenario
from rafii_control.intelligence import Catalog, QueryService
from rafii_control.workspace import WorkspaceService

domain_tools.ensure_registered()
ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2"
OPERATOR = "00000000-0000-0000-0000-000000000001"
OPS = "20000000-0000-4000-8000-000000000002"
NOW = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc).timestamp()
SCENARIO_AT = "2026-10-01T13:00:00Z"
QUESTIONS = (("今個月 AI 成本為甚麼上升？", ["founder_cost_breakdown", "founder_attention_list"]),
             ("哪個 plan 的使用成本最高？", ["founder_cost_breakdown", "founder_metric_query"]),
             ("哪些客戶快用完額度？", ["founder_entity_search"]),
             ("今日發布失敗影響了誰？", ["founder_metric_query", "founder_attention_list", "founder_incident_read"]),
             ("這張 retention 圖真正代表什麼？", ["founder_chart_explain"]),
             ("先草擬一封付款提醒給我看。", ["founder_draft_message"]),
             ("整理今日最需要我處理的三件事。", ["founder_attention_list", "founder_source_health"]))


def principal(**changes):
    value = dict(operator=dict(user_id=OPERATOR, role="founder", status="active", environment="local", auth_epoch=1,
                               capabilities=["control.read", "copilot.use", "metrics.query", "customers.read", "workspaces.read"]),
                 session=dict(id=str(uuid.uuid4()), environment="local", assurance="aal2", auth_epoch=1, revoked_at=None, expires_at=4102444800))
    for path, new in changes.items():
        section, key = path.split(".")
        value[section][key] = new
    return value


class ReadStore:
    environment = "local"

    def __init__(self):
        self.receipts = []

    def read(self, kind, identifier=None):
        return []

    def receipt(self, receipt):
        self.receipts.append(receipt)


class Control:
    """What founder_agent reads from the control application: `.queries` and `.workspace`."""

    def __init__(self, data=None, queries=None):
        self.queries = queries
        self.workspace = None
        if data is not None:
            self.workspace = WorkspaceService(None)
            self.workspace.demo = lambda principal_, action=None: data


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


def founder_ctx(mode, control, context=None, request_text=""):
    ctx = rt_context.RafiiRunContext(service=FakeService(), workspace_id=OPS, token="t", principal="owner-1", membership=Membership.from_row("owner"), conversation_id="conv-1",
                                     trace_id=contracts.new_trace_id(), zone="Asia/Hong_Kong", now=lambda: NOW, config=config.RuntimeConfig.from_environment({}), request_text=request_text)
    ctx.extra = {"founder": founder_agent.founder_scope_for(principal(), mode, control, context or {}, str(uuid.uuid4()))}
    return ctx


def run_tool(ctx, name, args):
    return tool_adapter.execute(ctx, tool_adapter.REGISTRY[name], args, scope=founder_tools.FOUNDER_SCOPE)


class Scenarios:
    outage = payment = None

    @classmethod
    def load(cls):
        if cls.outage is None:
            cls.outage = demo_dataset.sample_data()
            apply_scenario(cls.outage, "outage", now=SCENARIO_AT)
            cls.payment = demo_dataset.sample_data()
            apply_scenario(cls.payment, "payment_failure", now=SCENARIO_AT)


class ToolRegistryTests(unittest.TestCase):
    def test_thirteen_founder_tools_with_the_contract_effects(self):
        expected = {"founder_metric_query": contracts.READ, "founder_chart_explain": contracts.READ, "founder_entity_lookup": contracts.READ, "founder_entity_search": contracts.READ,
                    "founder_attention_list": contracts.READ, "founder_cost_breakdown": contracts.READ, "founder_incident_read": contracts.READ, "founder_source_health": contracts.READ,
                    "founder_draft_message": contracts.CREATE_DRAFT, "founder_reminder_prepare": contracts.PREPARE_EXTERNAL, "founder_report_prepare": contracts.PREPARE_EXTERNAL,
                    "founder_incident_ack": contracts.MUTATE_REVERSIBLE, "founder_navigate": contracts.READ}
        self.assertEqual(set(founder_tools.FOUNDER_TOOL_NAMES), set(expected))
        for name, effect in expected.items():
            spec = tool_adapter.REGISTRY[name].spec
            self.assertEqual((spec.tenant, spec.effect), ("founder", effect), name)
            self.assertEqual(spec.permission, "read" if effect == contracts.READ else "edit", name)
            self.assertEqual(spec.approval, effect == contracts.PREPARE_EXTERNAL, name)
            self.assertNotIn(spec.effect, contracts.FORBIDDEN_EFFECTS)
        for word in ("refund", "ban", "delete", "deploy", "shell", "sql", "send", "email", "push", "call"):
            self.assertFalse([n for n in founder_tools.FOUNDER_TOOL_NAMES if word in n], word)


class FounderToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Scenarios.load()

    def demo_ctx(self, data=None, context=None, text=""):
        return founder_ctx("demo", Control(data or Scenarios.outage), context, text)

    def test_demo_tools_answer_from_the_dataset_with_its_receipt(self):
        ctx = self.demo_ctx()
        receipt = demo_dataset.receipt(Scenarios.outage)["id"]
        cost = run_tool(ctx, "founder_cost_breakdown", {"dimension": "plan", "period": "mtd", "compare": True})
        self.assertTrue(cost["ok"])
        self.assertEqual(cost["current"]["receiptId"], receipt)
        self.assertEqual({r["dimensions"]["plan"] for r in cost["current"]["rows"]}, {"Starter", "Creator", "Studio"})
        self.assertEqual(cost["previous"]["dataState"], "unavailable", "Demo has one period; the previous one is unavailable, not zero")
        self.assertIsNone(cost["current"]["rows"][0]["actualUsdMicro"])
        quota = run_tool(ctx, "founder_entity_search", {"collection": "workspaces", "search": "", "view": "quota_80"})
        self.assertTrue(quota["ok"] and quota["rows"] and all(r["quotaUsedPercent"] >= 80 for r in quota["rows"]))
        self.assertLessEqual(len(quota["rows"]), 50)
        self.assertFalse(any("email" in r for r in quota["rows"]), "safe metadata only")
        failures = run_tool(ctx, "founder_metric_query", {"metricIds": ["publish_outcomes"], "period": "today", "groupBy": ["workspace"]})
        affected = [r["dimensions"]["workspace"] for r in failures["rows"]]
        incident = Scenarios.outage["incidents"][0]
        self.assertEqual(affected, incident["affectedWorkspaceIds"])
        self.assertEqual({r["receiptId"] for r in ctx.extra["founder"]["receipts"]}, {receipt})
        self.assertIn(receipt.lower(), ctx.ledger.known_ids)
        self.assertTrue(all(link["href"].startswith("/founder/") for link in ctx.extra["founder"]["links"]))

    def test_chart_explain_states_missing_denominator_instead_of_inventing_one(self):
        ctx = self.demo_ctx()
        unknown = run_tool(ctx, "founder_chart_explain", {"chartId": "retention"})
        self.assertEqual((unknown["ok"], unknown["dataState"], unknown["maturedDenominator"], unknown["cohortSize"]), (True, "not_applicable", None, None))
        self.assertTrue(unknown["unknowns"])
        known = run_tool(ctx, "founder_chart_explain", {"chartId": "plan-distribution"})
        self.assertEqual([r["subscribers"] for r in known["rows"]], [4500, 4000, 1500])

    def test_attention_list_ranks_the_incident_first_and_honours_limit(self):
        ctx = self.demo_ctx()
        found = run_tool(ctx, "founder_attention_list", {"limit": 3})
        self.assertEqual(len(found["items"]), 3)
        self.assertEqual(found["items"][0]["id"], Scenarios.outage["incidents"][0]["id"])
        # Structured like the Live overview; a Demo incident is never acknowledged, so there is no ack action.
        self.assertEqual([action["kind"] for action in found["items"][0]["actions"]], ["explain", "open"])
        incident = run_tool(ctx, "founder_incident_read", {"incidentId": found["items"][0]["id"]})
        self.assertEqual(incident["incident"]["state"], "open")
        self.assertNotIn("affectedRecords", incident["incident"], "affected records stay behind the entity lookup")

    def test_draft_message_is_text_only_for_a_named_recipient_class(self):
        ctx = self.demo_ctx(Scenarios.payment, text="先草擬一封付款提醒給我看。")
        draft = run_tool(ctx, "founder_draft_message", {"kind": "payment_reminder"})
        self.assertEqual((draft["ok"], draft["verified"], draft["persisted"], draft["delivery"], draft["recipientClass"]), (True, False, False, "none", "customer owner"))
        self.assertEqual(draft["recipient"]["name"], "Leo Martins")
        self.assertIn("付款提醒", draft["subject"])
        self.assertEqual(draft["placeholders"], [])
        self.assertEqual(ctx.ledger.changed, [])
        self.assertEqual(ctx.ledger.proposals, [])
        self.assertEqual(ctx.extra["founder"]["drafts"][0]["type"], "message")
        unknown = run_tool(self.demo_ctx(), "founder_draft_message", {"kind": "payment_reminder", "customerId": "customer-404404"})
        self.assertIn("customer name", unknown["placeholders"])

    def test_reminder_and_report_stop_at_a_draft_that_needs_confirmation(self):
        ctx = self.demo_ctx()
        reminder = run_tool(ctx, "founder_reminder_prepare", {"title": "Review AI cost", "dueLocal": "2026-10-02T09:00", "timeZone": "America/Indiana/Indianapolis"})
        self.assertEqual((reminder["ok"], reminder["verified"], reminder["needsUser"], reminder["draft"]["state"]), (True, False, True, "draft"))
        self.assertEqual(reminder["draft"]["dueAt"], "2026-10-02T13:00:00+00:00")
        self.assertFalse(reminder["draft"]["confirm"]["external"])
        report = run_tool(ctx, "founder_report_prepare", {"kind": "daily"})
        self.assertEqual((report["ok"], report["verified"], report["needsUser"], report["draft"]["state"]), (True, False, True, "draft"))
        self.assertEqual(ctx.ledger.changed, [])
        self.assertEqual(ctx.ledger.proposals, [])
        self.assertEqual([w["code"] for w in ctx.ledger.warnings], ["founder_confirmation_required"])
        self.assertEqual([a["status"] for a in ctx.ledger.tool_activity], ["unverified", "unverified"])
        bad = run_tool(ctx, "founder_reminder_prepare", {"title": "x", "dueLocal": "2026-13-40T09:00"})
        self.assertEqual((bad["ok"], bad["code"]), (False, "tool_input"))
        ack = run_tool(ctx, "founder_incident_ack", {"incidentId": Scenarios.outage["incidents"][0]["id"], "version": 1})
        self.assertEqual((ack["ok"], ack["code"]), (False, "demo_read_only"))

    def test_live_reads_go_through_query_service_receipts_and_never_fall_back_to_demo(self):
        store = ReadStore()
        control = Control(Scenarios.outage, QueryService(store, Catalog()))
        ctx = founder_ctx("live", control)
        # CAC stays a proposed, native-currency definition (PRD §7.1), so it exercises both the currency grouping and "unavailable, never zero".
        found = run_tool(ctx, "founder_metric_query", {"metricIds": ["cac"], "period": "mtd", "groupBy": ["source"]})
        self.assertTrue(found["ok"])
        self.assertEqual(found["source"], "live")
        self.assertEqual(len(store.receipts), 1)
        self.assertEqual(found["receiptId"], store.receipts[0]["id"])
        self.assertEqual(store.receipts[0]["normalizedQuery"]["groupBy"], ["source", "currency"], "native-currency metrics are grouped by currency")
        self.assertIsNone(found["rows"][0]["value"], "a definition that is not activated is unavailable, never zero")
        self.assertEqual(found["dataState"], "unavailable")
        self.assertIn(found["receiptId"].lower(), ctx.ledger.known_ids)
        self.assertEqual(ctx.extra["founder"]["receipts"][0]["source"], "live")
        quota = run_tool(ctx, "founder_entity_search", {"collection": "workspaces", "search": "", "view": "quota_80"})
        self.assertEqual((quota["ok"], quota["code"]), (False, "view_not_instrumented"))
        bare = founder_ctx("live", Control())
        cost = run_tool(bare, "founder_cost_breakdown", {"dimension": "plan", "period": "mtd"})
        self.assertEqual((cost["ok"], cost["code"]), (False, "metrics_unavailable"))
        self.assertFalse(bare.extra["founder"]["receipts"], "no Demo receipt ever backs a Live answer")
        if founder_tools.adapter("live_metrics", "overview", 3) is None:
            attention = run_tool(bare, "founder_attention_list", {"limit": 3})
            self.assertEqual(attention["code"], "attention_unavailable")

    def test_demo_reads_through_the_real_query_service_and_overview(self):
        """The landed adapters' call shapes: QueryService.metric_query(mode='demo', demo_data=...) and live_metrics.overview(..., queries)."""
        store = ReadStore()

        class DemoQueries(QueryService):
            def demo_data(self, principal_):
                return Scenarios.outage
        ctx = founder_ctx("demo", Control(Scenarios.outage, DemoQueries(store, Catalog())))
        cost = run_tool(ctx, "founder_cost_breakdown", {"dimension": "plan", "period": "mtd"})
        self.assertTrue(cost["ok"], cost)
        self.assertEqual((cost["current"]["source"], cost["current"]["executionState"]), ("demo", "demo_dataset"))
        self.assertEqual(store.receipts[-1]["id"], cost["current"]["receiptId"])
        self.assertTrue(all(r["metricId"] == "ai_cost_actual" for r in cost["current"]["rows"]))
        refused = run_tool(ctx, "founder_cost_breakdown", {"dimension": "workspace", "period": "mtd"})
        self.assertEqual(refused["code"], "dimension_not_instrumented")
        health = run_tool(ctx, "founder_source_health", {})
        self.assertTrue(health["ok"] and health["sources"] and health["receiptId"] == store.receipts[-1]["id"])
        if founder_tools.adapter("live_metrics", "overview", 4) is not None:
            attention = run_tool(ctx, "founder_attention_list", {"limit": 3})
            self.assertTrue(attention["ok"], attention)
            self.assertEqual(attention["listedBy"], "live_metrics.overview")
            self.assertTrue(attention["receiptIds"])
        self.assertTrue(all(r["source"] == "demo" for r in ctx.extra["founder"]["receipts"]), "a Demo turn's receipts are Demo receipts")

    def test_navigate_links_only_console_sections(self):
        ctx = self.demo_ctx(text="帶我去 AI cost 頁")
        found = run_tool(ctx, "founder_navigate", {"section": "ai-cost", "auto": True})
        self.assertEqual((found["href"], found["opensNow"]), ("/founder/ai-cost?mode=demo", True))
        self.assertEqual(ctx.ledger.client_blocks()[0]["type"], "navigation_card")
        with self.assertRaises(AlphaError):
            founder_tools.console_href("admin")

    def test_entity_links_use_the_parameters_each_page_reads(self):
        wid, cid = "11111111-2222-4333-8444-555555555555", "cus_demo_1"
        self.assertEqual(founder_tools.entity_href("customers", cid, "demo"), f"/founder/customers?record={cid}&mode=demo")
        self.assertEqual(founder_tools.entity_href("workspaces", wid), f"/founder/customers?tab=workspaces&q={wid}")
        self.assertEqual(founder_tools.entity_href("incidents", "inc-1"), "/founder/operations?tab=incidents&incident=inc-1")
        self.assertEqual(founder_tools.entity_href("invoices", "in_1"), "/founder/revenue?tab=payments")
        self.assertEqual(founder_tools.entity_href("tickets", "t1"), "/founder/support?tab=inbox")
        self.assertEqual(founder_tools.entity_href("unknown", "x"), "/founder")
        ctx = self.demo_ctx(text="open that workspace")
        found = run_tool(ctx, "founder_navigate", {"section": "overview", "entityCollection": "workspaces", "entityId": wid})
        self.assertEqual(found["href"], f"/founder/customers?tab=workspaces&q={wid}&mode=demo", "an entity opens on its own page")
        found = run_tool(ctx, "founder_navigate", {"section": "overview", "incidentId": "inc-2"})
        self.assertEqual(found["href"], "/founder/operations?tab=incidents&incident=inc-2&mode=demo")


class HarnessManagerTests(unittest.TestCase):
    """The scripted founder Manager plans the seven PRD example questions and cites receipts (the RAFII_AGENT_HARNESS path)."""

    @classmethod
    def setUpClass(cls):
        Scenarios.load()

    def run_turn(self, text, mode="demo", context=None, factory=None):
        ctx = founder_ctx(mode, Control(Scenarios.payment if "付款" in text else Scenarios.outage), context, text)
        agent, routes = founder_agent.build_manager(ctx, model_factory=factory or founder_agent.founder_model_factory())
        items = founder_agent.assemble(ctx, text, [])
        result = asyncio.run(Runner.run(agent, items, context=ctx, max_turns=10, run_config=RunConfig(tracing_disabled=True)))
        return ctx, result, routes

    def test_seven_example_questions_call_the_expected_tools_and_cite_receipts(self):
        for text, expected in QUESTIONS:
            with self.subTest(question=text):
                ctx, result, routes = self.run_turn(text)
                called = [a["tool"] for a in ctx.ledger.tool_activity]
                self.assertEqual(called, expected)
                self.assertTrue(all(a["status"] in ("verified", "unverified") for a in ctx.ledger.tool_activity), ctx.ledger.tool_activity)
                reply = result.final_output
                self.assertIsNone(answer_policy.check(reply.answer, ctx.ledger))
                self.assertIn("Demo", reply.answer)
                receipts = {r["receiptId"] for r in ctx.extra["founder"]["receipts"]}
                self.assertTrue(receipts)
                self.assertTrue(reply.facts and all(f.receiptId in receipts for f in reply.facts))
                section = founder_agent.founder_section(ctx, reply, ctx.extra["founder"])
                self.assertEqual(section["receiptIds"], sorted(receipts) if len(receipts) > 1 else list(receipts))
                self.assertEqual(len(section["facts"]), len(reply.facts))
                self.assertTrue(section["hypotheses"] and section["recommendations"][0]["metric"] and section["unknowns"])
                self.assertEqual(routes[0]["agent"], founder_prompts.AGENT_NAME)

    def test_publish_failures_link_the_affected_workspaces(self):
        ctx, _result, _ = self.run_turn("今日發布失敗影響了誰？")
        lookup = next(a for a in ctx.ledger.tool_activity if a["tool"] == "founder_incident_read")
        self.assertEqual(lookup["status"], "verified")
        incident = Scenarios.outage["incidents"][0]
        self.assertTrue({l["id"] for l in ctx.extra["founder"]["links"] if l["type"] == "workspace"} >= set(incident["affectedWorkspaceIds"]))

    def test_facts_without_a_receipt_from_this_turn_are_dropped(self):
        ctx, result, _ = self.run_turn("整理今日最需要我處理的三件事。")
        reply = result.final_output
        forged = copy.deepcopy(reply)
        forged.facts.append(type(reply.facts[0])(text="Revenue doubled.", receiptId=str(uuid.uuid4())))
        forged.facts.append(type(reply.facts[0])(text="Cost is 12,000 USD.", receiptId=None))
        section = founder_agent.founder_section(ctx, forged, ctx.extra["founder"])
        self.assertEqual(len(section["facts"]), len(reply.facts))
        self.assertEqual(section["factsDropped"], 2)
        self.assertIn("had no receipt", section["unknowns"][-1])

    def test_founder_manager_refuses_workspace_tools_and_forbidden_requests(self):
        scripted = ScriptedModel([[function_call("workspace_summary", {}, call_id="c1")], [function_call("founder_source_health", {}, call_id="c2")]])
        factory = lambda _w, name: scripted if name == founder_prompts.AGENT_NAME else ScriptedModel([])  # noqa: E731
        try:
            ctx, _result, _ = self.run_turn("summarise the workspace", factory=factory)
        except Exception:  # noqa: BLE001 — the SDK refuses a tool the agent does not have; either way nothing ran
            ctx = None
        if ctx is not None:
            self.assertFalse([a for a in ctx.ledger.tool_activity if a["tool"] == "workspace_summary" and a["status"] != "blocked"])
        ctx = founder_ctx("demo", Control(Scenarios.outage), None, "refund them all now")
        agent, _ = founder_agent.build_manager(ctx, model_factory=founder_agent.founder_model_factory())
        from agents.exceptions import InputGuardrailTripwireTriggered
        with self.assertRaises(InputGuardrailTripwireTriggered):
            asyncio.run(Runner.run(agent, founder_agent.assemble(ctx, "refund them all now", []), context=ctx, max_turns=4, run_config=RunConfig(tracing_disabled=True)))
        self.assertEqual(ctx.ledger.guardrail_trips[0]["reason"], "refund")
        self.assertEqual(ctx.ledger.tool_activity, [])


class FakeDatabase:
    """Runs, conversations, messages and events in dicts behind a cursor that answers the runtime's fixed SQL."""

    def __init__(self):
        self.runs, self.conversations, self.messages, self.events, self.sql = {}, {}, [], [], []


class FakeCursor:
    def __init__(self, db):
        self.db, self.rows = db, []

    def execute(self, sql, params=()):
        db, text = self.db, " ".join(sql.split())
        db.sql.append(text)
        self.rows = []
        if text.startswith("INSERT INTO public.pr_conversations"):
            ident = str(uuid.uuid4())
            db.conversations[ident] = {"workspace_id": params[0], "created_by": params[1], "title": params[2]}
            self.rows = [(ident,)]
        elif text.startswith("SELECT title FROM public.pr_conversations"):
            found = db.conversations.get(params[0])
            self.rows = [(found["title"],)] if found and found["workspace_id"] == params[1] else []
        elif "FROM public.pr_conversations WHERE id::text=%s AND workspace_id=%s FOR UPDATE" in text:
            found = db.conversations.get(params[0])
            self.rows = [(params[0], found["title"], found["created_by"], NOW, NOW, False)] if found and found["workspace_id"] == params[1] else []
        elif text.startswith("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s"):
            self.rows = [(rid,) for rid, run in db.runs.items() if run["workspace_id"] == params[0] and run["key"] == params[1]]
        elif text.startswith("INSERT INTO public.pr_agent_runs"):
            ident = str(uuid.uuid4())
            db.runs[ident] = {"conversation_id": params[0], "workspace_id": params[1], "actor": params[2], "status": "running", "key": params[7], "artifact": None}
            self.rows = [(ident,)]
        elif text.startswith("SELECT status,conversation_id::text,artifact FROM public.pr_agent_runs"):
            run = db.runs.get(params[0])
            self.rows = [(run["status"], run["conversation_id"], run["artifact"])] if run else []
        elif text.startswith("SELECT status,conversation_id::text,idempotency_key,actor::text FROM public.pr_agent_runs"):
            run = db.runs.get(params[0])
            self.rows = [(run["status"], run["conversation_id"], run["key"], run["actor"])] if run else []
        elif text.startswith("SELECT idempotency_key,actor::text FROM public.pr_agent_runs"):
            run = db.runs.get(params[0])
            self.rows = [(run["key"], run["actor"])] if run else []
        elif text.startswith("SELECT status FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s"):
            self.rows = [(db.runs[params[0]]["status"],)] if params[0] in db.runs else []
        elif text.startswith("UPDATE public.pr_agent_runs SET status=%s,artifact=%s::jsonb"):
            db.runs[params[4]].update(status=params[0], artifact=json.loads(params[1]))
        elif text.startswith("UPDATE public.pr_agent_runs SET status='cancelled'"):
            db.runs[params[0]]["status"] = "cancelled"
        elif text.startswith("SELECT id::text FROM public.pr_messages WHERE run_id::text=%s"):
            self.rows = [(m["id"],) for m in db.messages if m["run_id"] == params[0] and m["role"] == "assistant"][-1:]
        elif text.startswith("SELECT role,body FROM public.pr_messages"):
            self.rows = [(m["role"], m["body"]) for m in db.messages if m["conversation_id"] == params[0]][::-1][:params[2]]
        elif text.startswith("UPDATE public.pr_messages SET body"):
            for message in db.messages:
                if message["id"] == params[1]:
                    message["body"] = json.loads(params[0])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class DatabaseRepository:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def transaction(self, token, workspace_id):
        yield FakeCursor(self.db), (workspace_id, "{}", "owner", False, False, False, False), OPERATOR


class DatabaseIdeas:
    def __init__(self, db):
        self.db = db

    def _member(self, row):
        return Membership.from_row(*row[2:7])

    def _state(self, row):
        return {}

    def _conversation(self, cur, workspace_id, conversation_id):
        found = self.db.conversations.get(conversation_id)
        if not found or found["workspace_id"] != workspace_id:
            raise AlphaError("Conversation unavailable.", 404)
        return {"conversationId": conversation_id, "title": found["title"]}

    def _append_message(self, cur, workspace_id, conversation_id, role, body, run_id=None):
        message = {"id": str(uuid.uuid4()), "conversation_id": conversation_id, "workspace_id": workspace_id, "role": role, "body": body, "run_id": run_id}
        self.db.messages.append(message)
        return {"messageId": message["id"], "seq": len(self.db.messages), "role": role, "body": body}

    def _insert_event(self, cur, workspace_id, run_id, event):
        self.db.events.append({"run_id": run_id, **event})


class DatabaseService:
    def __init__(self, db):
        self.repository, self.ideas, self.clock = DatabaseRepository(db), DatabaseIdeas(db), (lambda: NOW)


class TurnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Scenarios.load()

    def setUp(self):
        self.db = FakeDatabase()
        self.service = DatabaseService(self.db)
        self.values = {founder_agent.OPS_WORKSPACE_ENV: OPS}
        self.control = Control(Scenarios.outage)

    def turn(self, body, who="founder", values=None):
        return founder_agent.turn(self.service, principal() if who == "founder" else who, body, str(uuid.uuid4()), control=self.control,
                                  values=self.values if values is None else values, model_factory=founder_agent.founder_model_factory())

    def test_unconfigured_ops_workspace_is_a_policy_blocker_before_any_read(self):
        with self.assertRaises(founder_agent.PolicyDisabled) as caught:
            self.turn({"message": "hi", "mode": "demo"}, values={})
        self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.blocker), ("POLICY_DISABLED", 409, "ops_workspace_not_configured"))
        self.assertEqual(self.db.sql, [])

    def test_only_an_aal2_founder_with_copilot_use_reaches_a_turn(self):
        for changes, code in ((dict(**{"operator.role": "workspace_admin"}), "FOUNDER_REQUIRED"), (dict(**{"session.assurance": "aal1"}), "STEP_UP_REQUIRED"),
                              (dict(**{"operator.capabilities": ["control.read", "metrics.query"]}), "SCOPE_DENIED"), (dict(**{"session.environment": "staging"}), "AUTH_REQUIRED"),
                              (dict(**{"session.revoked_at": 1.0}), "AUTH_REQUIRED"), (dict(**{"operator.status": "revoked"}), "FOUNDER_REQUIRED")):
            with self.subTest(changes=changes), self.assertRaises(ControlError) as caught:
                self.turn({"message": "hi", "mode": "demo"}, who=principal(**changes))
            self.assertEqual(caught.exception.code, code)
        for bearer in (None, "customer-bearer-token", {"workspaceId": OPS, "token": "x"}):
            with self.subTest(bearer=bearer), self.assertRaises(ControlError) as caught:
                self.turn({"message": "hi", "mode": "demo"}, who=bearer)
            self.assertEqual(caught.exception.code, "AUTH_REQUIRED")
        self.assertEqual(self.db.runs, {})

    def test_turn_body_is_strict(self):
        for body in ({"message": "hi"}, {"message": "hi", "mode": "test"}, {"message": "hi", "mode": "demo", "sql": "x"}, {"message": "", "mode": "demo"},
                     {"message": "hi", "mode": "demo", "conversationId": "not-a-uuid"}, {"message": "hi", "mode": "demo", "pageContext": {"section": "admin"}},
                     {"message": "hi", "mode": "demo", "pageContext": {"selectedEntity": {"collection": "customers", "id": "x; drop"}}},
                     {"message": "hi", "mode": "demo", "pageContext": {"route": "/app/queue"}}):
            with self.subTest(body=body), self.assertRaises(ControlError) as caught:
                self.turn(body)
            self.assertEqual(caught.exception.code, "VALIDATION_FAILED")

    def test_demo_turn_runs_on_the_ops_workspace_with_namespaced_key_conversation_and_founder_section(self):
        out = self.turn({"message": "整理今日最需要我處理的三件事。", "mode": "demo", "idempotencyKey": "k-1", "pageContext": {"section": "overview"}})
        self.assertEqual((out["status"], out["mode"], out["environment"], out["namespace"]), ("completed", "demo", "local", "founder:demo:local"))
        run = self.db.runs[out["runId"]]
        self.assertEqual((run["key"], run["workspace_id"], run["actor"]), ("agent:founder:demo:local:k-1", OPS, OPERATOR))
        self.assertTrue(self.db.conversations[out["conversationId"]]["title"].startswith("[founder:demo:local] "))
        founder = out["result"]["founder"]
        self.assertEqual((founder["mode"], founder["namespace"], founder["composedBy"]), ("demo", "founder:demo:local", "manager"))
        self.assertEqual(founder["receiptIds"], [demo_dataset.receipt(Scenarios.outage)["id"]])
        self.assertTrue(founder["facts"] and founder["facts"][0]["receiptId"] == founder["receiptIds"][0])
        self.assertEqual([a["tool"] for a in out["result"]["toolActivity"]], ["founder_attention_list", "founder_source_health"])
        self.assertIn("Demo", out["result"]["answerText"])
        blocks = self.db.messages[-1]["body"]["siteAgent"]["blocks"]
        self.assertIn("Receipts", [b.get("title") for b in blocks if b["type"] == "result_list"])
        self.assertEqual(run["artifact"]["trace"]["founder"]["namespace"], "founder:demo:local")
        again = self.turn({"message": "整理今日最需要我處理的三件事。", "mode": "demo", "idempotencyKey": "k-1"})
        self.assertEqual(again["runId"], out["runId"], "the same key replays the stored turn")
        self.assertEqual(len(self.db.runs), 1)

    def test_demo_and_live_conversations_never_mix(self):
        demo = self.turn({"message": "哪些客戶快用完額度？", "mode": "demo"})
        with self.assertRaises(ControlError) as caught:
            self.turn({"message": "哪些客戶快用完額度？", "mode": "live", "conversationId": demo["conversationId"]})
        self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_UNAVAILABLE", 404))
        self.assertEqual(len(self.db.runs), 1, "nothing ran on the wrong namespace")
        live = self.turn({"message": "哪些客戶快用完額度？", "mode": "live"})
        self.assertNotEqual(live["conversationId"], demo["conversationId"])
        self.assertTrue(self.db.conversations[live["conversationId"]]["title"].startswith("[founder:live:local] "))
        self.assertEqual(live["result"]["founder"]["mode"], "live")
        self.assertEqual(live["result"]["founder"]["receiptIds"], [], "Live never borrows the Demo receipt")
        self.assertEqual(live["result"]["toolActivity"][0]["code"], "view_not_instrumented")
        self.assertNotEqual(conversation := founder_agent.conversation_namespace("demo", "local"), founder_agent.conversation_namespace("live", "local"))
        self.assertEqual(founder_agent.namespace_of_title(f"[{conversation}] hello"), conversation)
        self.assertIsNone(founder_agent.namespace_of_title("hello [founder:demo:local]"))
        state = founder_agent.conversation_state(self.service, principal(), live["conversationId"], mode="live", values=self.values)
        self.assertEqual((state["mode"], state["namespace"], state["pendingApprovals"]), ("live", "founder:live:local", []))
        with self.assertRaises(ControlError):
            founder_agent.conversation_state(self.service, principal(), live["conversationId"], mode="demo", values=self.values)
        inferred = founder_agent.conversation_state(self.service, principal(), demo["conversationId"], values=self.values)
        self.assertEqual((inferred["mode"], inferred["namespace"], inferred["_dataState"]), ("demo", "founder:demo:local", "not_applicable"))

    def test_stored_and_cancel_see_only_this_founders_founder_runs(self):
        out = self.turn({"message": "這張 retention 圖真正代表什麼？", "mode": "demo"})
        found = founder_agent.run(self.service, principal(), out["runId"], str(uuid.uuid4()), values=self.values)
        self.assertEqual((found["runId"], found["mode"], found["result"]["founder"]["mode"], found["_dataState"]), (out["runId"], "demo", "demo", "synthetic"))
        self.assertEqual(found["_receiptIds"], out["_receiptIds"])
        self.assertIs(founder_agent.stored, founder_agent.run)
        done = founder_agent.cancel(self.service, principal(), out["runId"], values=self.values)
        self.assertEqual(done["status"], "completed")
        self.db.runs["11111111-1111-4111-8111-111111111111"] = {"conversation_id": out["conversationId"], "workspace_id": OPS, "actor": OPERATOR, "status": "completed",
                                                                 "key": "agent:customer-key", "artifact": {"result": {"answerText": "customer"}}}
        for operation in (founder_agent.stored, founder_agent.cancel):
            with self.subTest(operation=operation.__name__), self.assertRaises(ControlError) as caught:
                operation(self.service, principal(), "11111111-1111-4111-8111-111111111111", values=self.values)
            self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(ControlError):
            founder_agent.stored(self.service, principal(), "not-a-run", values=self.values)

    def test_forbidden_request_is_refused_deterministically_without_tools(self):
        out = self.turn({"message": "refund them all now", "mode": "demo"})
        self.assertEqual(out["result"]["composedBy"], "deterministic")
        self.assertEqual(out["result"]["toolActivity"], [])
        self.assertIn("can't do that", out["result"]["answerText"])
        self.assertEqual(self.db.runs[out["runId"]]["artifact"]["trace"]["fallback"], "guardrail_input")


class FounderPanelContextTests(unittest.TestCase):
    """The panel's real turn body (web/src/lib/founder/page-context.ts): presentational keys, nulls, singular entity types."""

    def test_the_panels_context_shape_is_accepted_and_normalised(self):
        from rafii_control.founder_agent import founder_context, validate_turn
        context = {"route": "/founder/customers", "section": "customers", "mode": "demo", "environment": "local",
                   "selectedEntity": {"type": "customer", "id": "customer-3"}, "chart": {"chartId": "paid_customers", "viewVersion": 1},
                   "period": None, "filters": {"plan": "Studio", "page": 2, "risk": True, "views": ["a", "b"]}, "incidentId": None,
                   "uiCapabilities": ["navigate", "open_evidence"]}
        out = founder_context(context)
        self.assertEqual(out["selectedEntity"], {"collection": "customers", "id": "customer-3"})
        self.assertEqual(out["chart"]["queryReceiptId"], None)
        self.assertEqual(out["filters"], {"plan": "Studio", "page": "2", "risk": "true", "views": "a,b"})
        self.assertNotIn("period", out)
        self.assertNotIn("mode", out)
        turn = validate_turn({"message": "hi", "mode": "demo", "idempotencyKey": "k-panel-1", "conversationId": None, "modality": "text",
                              "pageContext": context, "timeZone": "America/Indiana/Indianapolis"})
        self.assertEqual(turn["pageContext"]["section"], "customers")

    def test_an_attention_item_carries_no_entity_and_bad_values_are_still_refused(self):
        from rafii_control.founder_agent import founder_context
        self.assertNotIn("selectedEntity", founder_context({"section": "overview", "selectedEntity": {"type": "attention", "id": "payment_failures_7d"}}))
        for bad in ({"mode": "live-ish"}, {"environment": "prod"}, {"uiCapabilities": ["shell"]}, {"selectedEntity": {"type": "customer", "id": "x; drop"}},
                    {"filters": {"plan": {"nested": 1}}}, {"chart": {"chartId": "c", "viewVersion": "1"}}, {"unknown": 1}):
            with self.subTest(bad=bad), self.assertRaises(ControlError):
                founder_context(bad)

if __name__ == "__main__":
    unittest.main()

