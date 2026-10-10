"""rafii-genui/1 lane D: deterministic eligibility, the authorized projection, the capability manifest and the allowlist
(G05 G06 G07 G14 G21; D-A14 D-A17 D-A19 D-A37).

Pure: no database, no model, no network. The PostgreSQL scenarios (tests/phase2/postgres_agent_ui_*.py) cover the same
rules on real roles and tenants.
"""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.agent_runtime_v2 import ui_capabilities, ui_contracts, ui_domain, ui_projection  # noqa: E402
from postriff_phase2.agent_runtime_v2.ui_domain import shapes  # noqa: E402
from postriff_phase2.agent_runtime_v2.ui_http import UiAuth  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402

ON = {"enabled": True, "actions": True, "edits": True, "canary": False}
WS = "11111111-1111-4111-8111-111111111111"
OTHER_WS = "22222222-2222-4222-8222-222222222222"


def auth(role="owner", *, scope="workspace", workspace=WS, principal="00000000-0000-0000-0000-000000000001", scope_key=""):
    member = Membership.from_row(role)
    return UiAuth(workspace_id=workspace, principal=principal, member=member, role=role, scope=scope, scope_key=scope_key)


def result(tools=(), *, composed="manager", billing="metered", refs=(), approvals=(), changed=(), answer="Here are your drafts.", ui=None, **extra):
    out = {"composedBy": composed, "usage": {"billing": billing, "route": "gpt-x"}, "answerText": answer, "speakableSummary": answer,
           "toolActivity": [{"tool": t, "status": s, "effect": "READ"} for t, s in tools], "references": list(refs), "pendingApprovals": list(approvals),
           "changedEntities": list(changed), "generatedAssets": [], "warnings": [], "language": "en",
           "routes": [{"agent": "rafii_manager", "provider": "openai", "model": "gpt-x"}], **extra}
    if ui is not None:
        out["ui"] = ui
    return out


class EligibilityTest(unittest.TestCase):
    def test_founder_journey_requires_explicit_server_scope_and_verified_read(self):
        founder = result([("founder_cost_breakdown", "verified")])
        for scope in ("workspace", "invalid"):
            self.assertFalse(ui_projection.eligibility(founder, "Show a cost table", "text", flags=ON, scope=scope)["eligible"])
        decided = ui_projection.eligibility(founder, "Why did costs rise?", "text", flags=ON, scope="founder")
        self.assertTrue(decided["eligible"])
        self.assertEqual(decided["journeyIds"], ["J09"])
        self.assertEqual(decided["reason"], "rich_result")
        for status in ("blocked", "failed"):
            blocked = result([("founder_cost_breakdown", status)])
            self.assertFalse(ui_projection.eligibility(blocked, "Show a cost table", "text", flags=ON, scope="founder")["eligible"])
        self.assertFalse(ui_projection.eligibility(founder, "Why did costs rise?", "voice", flags=ON, scope="founder")["eligible"])

    def test_disabled_and_non_manager_turns_never_qualify(self):
        r = result([("calendar_range", "verified")])
        self.assertEqual(ui_projection.eligibility(r, "show my week", "text", flags={"enabled": False})["reason"], "disabled")
        self.assertEqual(ui_projection.eligibility(result([("calendar_range", "verified")], composed="site_agent"), "show my week", "text", flags=ON)["reason"],
                         "not_manager")
        for billing in ("scripted", None, "free"):
            self.assertEqual(ui_projection.eligibility(result([("calendar_range", "verified")], billing=billing), "show my week", "text", flags=ON)["reason"],
                             "not_metered", billing)

    def test_greetings_acknowledgements_and_plain_answers_do_not_invoke_the_presenter(self):
        rich = result([("drafts_list", "verified"), ("calendar_range", "verified")])
        for text in ("hi", "Hello Rafii!", "thanks", "ok", "多謝", "谢谢", "好的", "早晨", "收到"):
            with self.subTest(text=text):
                decided = ui_projection.eligibility(rich, text, "text", flags=ON)
                self.assertFalse(decided["eligible"])
                self.assertEqual(decided["reason"], "greeting")
        plain = result([("help_search", "verified")], refs=[])
        self.assertEqual(ui_projection.eligibility(plain, "How does approval work?", "text", flags=ON)["reason"], "plain_answer")

    def test_explicit_ui_intents_in_three_languages(self):
        drafts = result([("draft_get", "verified")], refs=[{"type": "draft", "id": "v1", "title": "x"}])
        for text in ("Compare my LinkedIn drafts", "show a table of drafts", "filter by platform", "比較呢兩篇草稿", "比较这两篇草稿", "用表格列出草稿"):
            with self.subTest(text=text):
                decided = ui_projection.eligibility(drafts, text, "text", flags=ON)
                self.assertTrue(decided["eligible"])
                self.assertEqual(decided["reason"], "ui_intent")
                self.assertEqual(decided["journeyIds"], ["J01"])
                self.assertEqual(decided["slot"], "main")

    def test_journeys_come_from_verified_structure_not_blocked_tools(self):
        cal = result([("calendar_range", "verified"), ("schedule_propose", "blocked")])
        decided = ui_projection.eligibility(cal, "what's on this week", "text", flags=ON)
        self.assertTrue(decided["eligible"])
        self.assertEqual(decided["journeyIds"], ["J02"])
        blocked = result([("calendar_range", "blocked")])
        self.assertFalse(ui_projection.eligibility(blocked, "what's on this week", "text", flags=ON)["eligible"])
        proposal = result([("schedule_propose", "verified")], approvals=[{"proposalId": "p1", "type": "schedule_draft"}])
        self.assertIn("J02", ui_projection.eligibility(proposal, "schedule it Thursday", "text", flags=ON)["journeyIds"])
        perf = result([("publishing_summary", "verified")])
        self.assertEqual(ui_projection.eligibility(perf, "how did my posts perform last week?", "text", flags=ON)["journeyIds"][0], "J06")

    def test_voice_without_a_visual_ask_does_not_spend_on_a_view(self):
        decided = ui_projection.eligibility(result([("calendar_range", "verified")]), "what's on today", "voice", flags=ON)
        self.assertFalse(decided["eligible"])
        self.assertEqual(decided["reason"], "voice")

    def test_a_question_about_runs_after_a_run_history_read_is_a_collection(self):
        # Run 3 J08-b: "What happened in my last automation runs?" read run history through automation_explain/automation_get,
        # which harvest one automation reference, so the turn was a "single fact" and no view (or "Build interactive view") was
        # offered although J08 shows run history (automation_history → RunHistory). D-A52: it is a collection when the person asks
        # about several runs AND the verified reads covered two or more distinct runs (runIds recorded by the tool gate).
        ref = [{"type": "automation", "id": "t_weekly_tips", "title": "Weekly tips"}]

        def reads(*activities, refs=ref):
            r = result([(tool, status) for tool, status, _ids in activities], refs=refs)
            for entry, (_tool, _status, ids) in zip(r["toolActivity"], activities):
                if ids is not None:
                    entry["runIds"] = list(ids)
            return r

        three = reads(("automation_get", "verified", ["o1", "o2", "o3"]))
        two_explains = reads(("automation_explain", "verified", ["o1"]), ("automation_explain", "verified", ["o2"]))
        # ("show my automation run history" is also a UI intent, so it is eligible either way; test_run_history_wording covers its words.)
        asks = ("What happened in my last automation runs?", "Any problems in the run history?",
                "How did my last 3 runs go?", "睇吓我自動化嘅運行記錄", "我最近幾次自動化發生咩事？", "最近几次运行记录")
        for r in (three, two_explains):
            for text in asks:
                with self.subTest(text=text, tools=[a["tool"] for a in r["toolActivity"]]):
                    decided = ui_projection.eligibility(r, text, "text", flags=ON)
                    self.assertTrue(decided["eligible"], decided)
                    self.assertEqual((decided["reason"], decided["journeyIds"]), ("rich_result", ["J08"]))
        # The words alone never qualify: one run, the same run twice, unverified or blocked reads, another tool, or an older
        # stored result without runIds stay a single fact.
        for r in (reads(("automation_get", "verified", ["o1"])), reads(("automation_explain", "verified", ["o1"]), ("automation_get", "verified", ["o1"])),
                  reads(("automation_get", "unverified", ["o1", "o2"])), reads(("automation_get", "blocked", ["o1", "o2"])),
                  reads(("draft_get", "verified", ["o1", "o2"]), refs=[{"type": "draft", "id": "v1"}]), reads(("automation_get", "verified", None))):
            with self.subTest(activity=r["toolActivity"]):
                self.assertFalse(ui_projection.eligibility(r, "What happened in my last automation runs?", "text", flags=ON)["eligible"])
        # Several runs read, but the person asked about one run, a schedule ("runs" the verb) or declined history: native answer.
        for text in ("Why did my last run fail?", "Why didn't my Tuesday post publish?", "what runs tomorrow?",
                     "My automation runs at 9am, why did nothing publish?", "When does it run next?", "唔使睇歷史", "不用看历史，直接告诉我"):
            with self.subTest(text=text):
                decided = ui_projection.eligibility(three, text, "text", flags=ON)
                self.assertEqual((decided["eligible"], decided["reason"]), (False, "single_fact"), decided)
        # Voice still needs a visual ask.
        self.assertEqual(ui_projection.eligibility(three, "what happened in my last runs", "voice", flags=ON)["reason"], "voice")

    def test_run_history_wording(self):
        for text in ("What happened in my last automation runs?", "show my automation run history", "the past few runs", "recent runs", "my runs",
                     "history of its runs", "run log", "睇吓我自動化嘅運行記錄", "上幾次點樣", "最近几次", "执行记录", "顯示歷史"):
            with self.subTest(text=text):
                self.assertTrue(ui_projection.asks_run_history(text))
        for text in ("Why did my last run fail?", "what runs tomorrow?", "My automation runs at 9am, why did nothing publish?", "It runs daily",
                     "the previous run", "latest run", "唔使睇歷史", "唔好睇歷史", "不用看历史", "不要歷史", "", None):
            with self.subTest(text=text):
                self.assertFalse(ui_projection.asks_run_history(text))

    def test_the_tool_gate_records_which_runs_a_verified_automation_read_covered(self):
        from postriff_phase2.agent_runtime_v2 import config as rt_config, context as rt_context, contracts as rt_contracts, tool_adapter
        from postriff_phase2.permissions import Membership as Member
        get = {"ok": True, "verified": True, "data": {"taskId": "t1", "runs": [{"occurrenceId": "o1"}, {"occurrenceId": "o2"}, {"occurrenceId": "o1"},
                                                                                {"occurrenceId": "bad id!"}, {"occurrenceId": None}, "x"]}}
        self.assertEqual(tool_adapter.run_ids_read("automation_get", get), ["o1", "o2"])
        self.assertEqual(tool_adapter.run_ids_read("automation_explain", {"ok": True, "data": {"automationId": "t1", "runId": "o9"}}), ["o9"])
        self.assertEqual(tool_adapter.run_ids_read("automation_explain", {"ok": True, "data": {"automationId": None, "runId": None}}), [])
        self.assertEqual(tool_adapter.run_ids_read("draft_get", get), [])
        for odd in (None, "x", {"data": None}, {"data": {"runs": "nope"}}, {"data": {"runs": [{"occurrenceId": "o%d" % i} for i in range(40)]}}):
            self.assertLessEqual(len(tool_adapter.run_ids_read("automation_get", odd)), tool_adapter.MAX_RUN_IDS)

        def ctx():
            return rt_context.RafiiRunContext(service=None, workspace_id="ws", token="t", principal="p", membership=Member.from_row("owner"),
                                              conversation_id="c", trace_id=rt_contracts.new_trace_id(), modality="text", zone="Asia/Hong_Kong",
                                              now=lambda: 1_760_000_000.0, config=rt_config.RuntimeConfig.from_environment({}))

        def probe(name, outcome):
            spec = rt_contracts.ToolSpec(name, rt_contracts.READ, "read", "probe")
            return tool_adapter.Tool(spec, {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, lambda _c, _a: outcome, "probe")

        verified = ctx()
        tool_adapter.execute(verified, probe("automation_get", get), {})
        self.assertEqual(verified.ledger.tool_activity[-1]["runIds"], ["o1", "o2"])
        unverified = ctx()
        tool_adapter.execute(unverified, probe("automation_get", {**get, "verified": False}), {})
        self.assertNotIn("runIds", unverified.ledger.tool_activity[-1])
        other = ctx()
        tool_adapter.execute(other, probe("draft_get", get), {})
        self.assertNotIn("runIds", other.ledger.tool_activity[-1])

    def test_odd_input_never_raises(self):
        for odd in (None, "x", 3, {"toolActivity": "nope"}, {"composedBy": "manager", "usage": {"billing": "metered"}, "toolActivity": [None, 1]}):
            self.assertFalse(ui_projection.eligibility(odd, None, None, flags=ON)["eligible"])


class ProjectionTest(unittest.TestCase):
    PRIVATE = "PRIVATE-DRAFT-TEXT-never-to-the-model"

    def test_projection_carries_only_refs_counts_states_and_binding_schemas(self):
        r = result([("draft_get", "verified"), ("campaign_get", "verified")],
                   refs=[{"type": "draft", "id": "v1", "title": self.PRIVATE}, {"type": "campaign", "id": "c1", "title": "Secret goal " + self.PRIVATE}],
                   answer="Your draft says " + self.PRIVATE, ui={"eligible": True, "journeyIds": ["J01", "J05"]})
        projection = ui_projection.project_ui_context(None, auth("editor"), r, "panel", {"references": [{"type": "draft", "id": "v1", "title": self.PRIVATE}]})
        for key in ("manifest_id", "journey_ids", "component_group_ids", "data_bindings", "action_bindings", "allowed_context", "fallback_text", "egress_decision"):
            self.assertIn(key, projection)
        self.assertEqual(projection["journey_ids"], ["J01", "J05"])
        view = ui_projection.presenter_view(projection)
        dumped = json.dumps(view)
        self.assertNotIn(self.PRIVATE, dumped)
        self.assertNotIn("Secret goal", dumped)
        self.assertIn({"type": "draft", "id": "v1"}, view["context"]["refs"])
        self.assertEqual(projection["fallback_text"], r["answerText"], "the native fallback keeps the answer; it is never in presenter_view")
        names = {b["name"] for b in projection["data_bindings"]}
        self.assertIn("drafts_list", names)
        self.assertIn("campaign_detail", names)
        self.assertTrue(all(ui_contracts.valid_name(n) for n in names))
        self.assertEqual(projection["egress_decision"]["allowed"], True)
        self.assertEqual(projection["egress_decision"]["provider"], "openai")

    def test_an_automation_reference_suggests_its_detail_and_run_history(self):
        r = result([("automation_explain", "verified")], refs=[{"type": "automation", "id": "t_weekly_tips", "title": "Weekly tips"}],
                   ui={"eligible": True, "journeyIds": ["J08"]})
        projection = ui_projection.project_ui_context(None, auth("owner"), r, "panel", None)
        suggested = projection["allowed_context"]["suggestedInputs"]
        self.assertIn({"binding": "automation_detail", "inputs": {"automationId": "t_weekly_tips"}}, suggested)
        self.assertIn({"binding": "automation_history", "inputs": {"automationId": "t_weekly_tips"}}, suggested)
        self.assertIn("automation_history", {b["name"] for b in projection["data_bindings"]}, "J08's manifest carries the run-history read")

    def test_unmetered_parent_turn_denies_presenter_egress(self):
        projection = ui_projection.project_ui_context(None, auth(), result([("draft_get", "verified")], billing="scripted", ui={"journeyIds": ["J01"]}), "chat", None)
        self.assertFalse(projection["egress_decision"]["allowed"])
        self.assertIsNone(projection["egress_decision"]["provider"])

    def test_roles_shape_the_offered_controls(self):
        r = result([("draft_get", "verified")], ui={"journeyIds": ["J01", "J02", "J04"]})
        viewer = {a["actionId"] for a in ui_projection.project_ui_context(None, auth("viewer"), r, "chat", None)["action_bindings"]}
        editor = {a["actionId"] for a in ui_projection.project_ui_context(None, auth("editor"), r, "chat", None)["action_bindings"]}
        owner = {a["actionId"] for a in ui_projection.project_ui_context(None, auth("owner"), r, "chat", None)["action_bindings"]}
        self.assertEqual(viewer, set(), "a viewer is offered no write control")
        self.assertIn("draft_edit", editor)
        self.assertNotIn("schedule_prepare", editor, "preparing a post for approval needs approve")
        self.assertNotIn("voice_sample_grant", editor, "a sample's cloud-use grant is an owner decision")
        self.assertIn("schedule_prepare", owner)
        self.assertIn("voice_sample_grant", owner)


class KillSwitchTest(unittest.TestCase):
    def test_actions_flag_off_offers_no_write_control(self):
        r = result([("draft_get", "verified")], ui={"journeyIds": ["J01", "J05"]})
        off = ui_projection.project_ui_context(None, auth("owner"), r, "chat", None, flags={**ON, "actions": False})
        self.assertEqual(off["action_bindings"], [])
        self.assertTrue(off["data_bindings"])
        on = ui_projection.project_ui_context(None, auth("owner"), r, "chat", None, flags=ON)
        self.assertTrue(on["action_bindings"])


class ManifestTest(unittest.TestCase):
    def test_consumer_manifests_never_carry_founder_bindings(self):
        manifest = ui_capabilities.build_manifest(None, auth(), {"journey_ids": ["J01", "J09", "J06"]}, scope="workspace")
        self.assertEqual(manifest["journeyIds"], ["J01", "J06"])
        self.assertFalse(any(q["name"].startswith("founder_") for q in manifest["queries"]))
        founder = ui_capabilities.build_manifest(None, auth(scope="founder", scope_key="founder:live:production"), {"journey_ids": ["J01", "J09"]}, scope="founder")
        self.assertEqual(founder["journeyIds"], ["J09"])
        self.assertTrue(founder["queries"] and all(q["name"].startswith("founder_") for q in founder["queries"]))
        self.assertEqual(founder["actions"], [], "the founder manifest is read-only")
        with self.assertRaises(AlphaError):
            ui_capabilities.build_manifest(None, auth(), {"journey_ids": ["J09"]}, scope="founder")

    def test_public_manifest_drops_every_server_only_key(self):
        manifest = ui_capabilities.build_manifest(None, auth(), {"journey_ids": ["J02"], "allowed_context": {"refs": [{"type": "draft", "id": "v1"}]}})
        for key in ui_contracts.SERVER_ONLY_MANIFEST_KEYS:
            self.assertIn(key, manifest, key)
        public = ui_contracts.public_manifest(manifest)
        dumped = json.dumps(public)
        self.assertNotIn(auth().principal, dumped)
        self.assertNotIn(WS, dumped)
        self.assertNotIn("permissionRevision", dumped)
        self.assertEqual(set(public), {"manifestId", "bindingVersion", "journeyIds", "componentGroups", "queries", "actions", "expiresAt"})

    def test_current_rechecks_scope_expiry_and_role(self):
        manifest = ui_capabilities.build_manifest(None, auth("owner"), {"journey_ids": ["J01", "J02"]})
        same = ui_capabilities.current(None, auth("owner"), manifest)
        self.assertFalse(same["revised"])
        demoted = ui_capabilities.current(None, auth("viewer"), manifest)
        self.assertTrue(demoted["revised"])
        self.assertEqual(demoted["actions"], [])
        self.assertTrue(demoted["queries"], "reads stay; every read is re-authorized anyway")
        with self.assertRaises(AlphaError) as foreign:
            ui_capabilities.current(None, auth(workspace=OTHER_WS), manifest)
        self.assertEqual(foreign.exception.status, 404)
        with self.assertRaises(AlphaError) as other_scope:
            ui_capabilities.current(None, auth(scope="founder", scope_key="founder:live:production"), manifest)
        self.assertEqual(other_scope.exception.status, 404)
        expired = {**manifest, "expiresAt": ui_contracts.now_iso().replace(str(time.gmtime().tm_year), "2000")}
        with self.assertRaises(AlphaError) as gone:
            ui_capabilities.current(None, auth(), expired)
        self.assertEqual(gone.exception.code, "ui_capability_expired")
        with self.assertRaises(AlphaError):
            ui_capabilities.current(None, auth(), {"queries": []})

    def test_a_write_name_is_never_a_query_binding(self):
        manifest = ui_capabilities.build_manifest(None, auth(), {"journey_ids": list(ui_contracts.CONSUMER_JOURNEYS)})
        for name in list(ui_domain.ACTIONS) + ["schedule_propose", "proposal_apply", "draft_create", "constructor", "__proto__"]:
            self.assertIsNone(ui_capabilities.query_binding(manifest, name), name)
        self.assertIsNotNone(ui_capabilities.query_binding(manifest, "drafts_list"))
        self.assertIsNone(ui_capabilities.action_binding(manifest, "drafts_list"))


class AllowlistTest(unittest.TestCase):
    FORBIDDEN_WORDS = ("publish", "send", "delete", "disconnect", "revoke", "buy", "purchase", "secret", "token", "oauth", "approve_post", "reply", "refund", "ban")

    def test_every_action_is_an_allowed_effect_with_an_explicit_requirement(self):
        for action_id, binding in ui_domain.ACTIONS.items():
            with self.subTest(action=action_id):
                self.assertIn(binding.effect, ui_contracts.UI_ACTION_EFFECTS)
                self.assertIn(binding.requirement, ("edit", "approve", "owner", "manage_connections"))
                self.assertEqual(binding.scope, "workspace")
                self.assertFalse(any(word in action_id for word in self.FORBIDDEN_WORDS), action_id)
                self.assertTrue(ui_contracts.valid_name(action_id))
                self.assertFalse(binding.inputs.get("additionalProperties", True))
                if binding.effect == "PREPARE_EXTERNAL":
                    self.assertTrue(binding.prepare_only and binding.requires_confirmation)
                if binding.tool:
                    self.assertTrue(ui_capabilities.tool_ok(binding.tool, scope="workspace", effect=binding.effect), binding.tool)

    def test_every_query_is_read_only_bounded_and_shaped(self):
        for name, binding in ui_domain.QUERIES.items():
            with self.subTest(query=name):
                self.assertTrue(ui_contracts.valid_name(name))
                self.assertIn(name, shapes.SHAPES)
                self.assertFalse(binding.args.get("additionalProperties", True))
                self.assertEqual(binding.requirement, "read")
                if binding.refresh is not None:
                    self.assertGreaterEqual(binding.refresh, ui_contracts.BOUNDS["refreshMinSeconds"])
                if binding.page is not None:
                    self.assertLessEqual(binding.page, ui_contracts.BOUNDS["queryPageMax"])
                self.assertEqual(binding.scope == "founder", binding.journey == "J09")
                if binding.tool:
                    self.assertTrue(ui_capabilities.tool_ok(binding.tool, scope=binding.scope, effect="READ"), binding.tool)
        self.assertFalse(set(ui_domain.QUERIES) & set(ui_domain.ACTIONS))

    def test_every_consumer_journey_has_reads_and_the_catalog_is_complete(self):
        catalog = ui_domain.catalog()
        for journey in ui_contracts.JOURNEYS:
            self.assertTrue(catalog["journeys"][journey]["queries"], journey)
            for entry in catalog["journeys"][journey]["queries"]:
                self.assertEqual(set(entry), {"name", "argsSchema", "dataShape"})
        self.assertEqual(catalog["journeys"]["J09"]["actions"], [])
        json.dumps(catalog)

    def test_inputs_are_validated_exactly(self):
        schema = ui_domain.QUERIES["drafts_list"].args
        self.assertEqual(ui_domain.validate(schema, {"platform": "LinkedIn"}), {"platform": "LinkedIn"})
        for bad in ({"platform": "MySpace"}, {"limit": 500}, {"q": "x" * 121}, {"sql": "select 1"}, {"ids": ["ok"] * 11}, {"limit": True}):
            with self.subTest(bad=bad):
                with self.assertRaises(AlphaError):
                    ui_domain.validate(schema, bad)


if __name__ == "__main__":
    unittest.main()
