"""rafii-ui-plan/1: the Adaptive UI Planner (default OFF; shadow or canary-active).

Pure: no database, no model, no network. Checks that the planner (1) never makes a turn eligible that the deterministic
baseline vetoes for safety (disabled, not Manager, not metered, YouTube context, greeting, voice without a view request,
founder data outside founder scope), (2) picks a response form from the fixed set, (3) only declares interactions from the
fixed per-form table and no business action without the actions flag, (4) is wired through service.ui_handoff behind its
own flags with a fail-closed workspace allowlist, and (5) does no worse than the baseline on the labelled corpus.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.append(str(ROOT / "scripts"))   # appended: scripts/postriff_phase2.py must not shadow the package

from postriff_phase2.agent_runtime_v2 import config, service, ui_planner, ui_projection  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "agent_ui" / "planner_cases_v1.json"
ON = {"enabled": True, "actions": True, "edits": True, "canary": False}
WS = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def turn(case: dict) -> dict:
    out = {"composedBy": case.get("composed", "manager"), "usage": {"billing": case.get("billing", "metered"), "route": "gpt-x"},
           "answerText": "native answer", "toolActivity": [{"tool": t, "status": s, "effect": "READ", **({"runIds": case["runIds"]} if case.get("runIds") else {})}
                                                           for t, s in case.get("tools") or []],
           "references": [{"type": k, "id": i} for k, i in case.get("refs") or []],
           "pendingApprovals": [{"type": t, "proposalId": f"prop-{n}"} for n, t in enumerate(case.get("approvals") or [])],
           "changedEntities": [], "generatedAssets": [], "warnings": [], "language": "en",
           "routes": [{"agent": "rafii_manager", "provider": "openai", "model": "gpt-x"}]}
    if case.get("founder"):
        out["founder"] = {"mode": "live"}
    if case.get("youtube"):
        out["agent"] = {"youtubeProviderContext": {}}
    return out


def plan_case(case: dict, flags=ON) -> dict:
    return ui_planner.plan(turn(case), case["text"], case.get("modality", "text"), flags=flags, scope=case.get("scope", "workspace"),
                           context={"followsArtifact": bool(case.get("followsArtifact"))})


class PlannerSafety(unittest.TestCase):
    def test_hard_vetoes_are_never_overridden(self):
        cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            base = ui_projection.eligibility(turn(case), case["text"], case.get("modality", "text"), flags=ON, scope=case.get("scope", "workspace"))
            plan = plan_case(case)
            if base["reason"] in ui_planner.HARD_VETOES:
                self.assertFalse(plan["eligible"], case["id"])
                self.assertEqual(plan["form"], "text", case["id"])
                self.assertEqual(plan["reason"], base["reason"], case["id"])

    def test_disabled_flags_stay_native(self):
        case = {"text": "Why did my automation fail?", "tools": [["automation_get", "verified"]], "runIds": ["r1"]}
        self.assertFalse(plan_case(case, flags={"enabled": False})["eligible"])

    def test_upgrades_require_a_verified_read(self):
        for status in ("unverified", "blocked", "failed"):
            case = {"text": "Why did my automation fail?", "tools": [["automation_get", status]], "runIds": ["r1"]}
            self.assertFalse(plan_case(case)["eligible"], status)
            case = {"text": "Which posts need attention?", "tools": [["attention_summary", status]]}
            self.assertFalse(plan_case(case)["eligible"], status)

    def test_upgrades_never_happen_in_voice_or_founder_scope(self):
        case = {"text": "Why did my automation fail?", "tools": [["automation_get", "verified"]], "runIds": ["r1"], "modality": "voice"}
        self.assertFalse(plan_case(case)["eligible"])
        case = {"scope": "founder", "founder": True, "text": "Why did my automation fail?", "tools": [["automation_get", "verified"]], "runIds": ["r1"]}
        self.assertFalse(plan_case(case)["eligible"])

    def test_form_and_interactions_come_from_fixed_tables(self):
        for case in json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]:
            plan = plan_case(case)
            self.assertIn(plan["form"], ui_planner.FORMS, case["id"])
            self.assertEqual(plan["eligible"], plan["form"] != "text", case["id"])
            table = ui_planner.INTERACTIONS[plan["form"]]
            self.assertTrue(set(plan["interactions"]["local"]) <= set(table["local"]), case["id"])
            self.assertTrue(set(plan["interactions"]["reads"]) <= set(table["reads"]), case["id"])
            self.assertTrue(set(plan["interactions"]["actions"]) <= set(table["actions"]), case["id"])
            for key in ("baseline", "delta", "disclosure", "journeyIds", "version"):
                self.assertIn(key, plan, case["id"])

    def test_no_business_action_without_actions_flag(self):
        case = {"text": "Schedule this draft for Friday 9am", "tools": [["schedule_propose", "verified"]], "approvals": ["schedule_draft"]}
        self.assertTrue(plan_case(case)["interactions"]["actions"])
        self.assertEqual(plan_case(case, flags={**ON, "actions": False})["interactions"]["actions"], [])

    def test_plan_carries_no_private_text(self):
        case = {"text": "Compare Instagram and TikTok — my secret launch codename is Falcon", "tools": [["publishing_summary", "verified"], ["calendar_range", "failed"]]}
        blob = json.dumps(plan_case(case))
        self.assertNotIn("Falcon", blob)
        self.assertNotIn("native answer", blob)
        self.assertEqual(plan_case(case)["disclosure"]["unavailableTools"], ["calendar_range"])

    def test_odd_input_never_raises(self):
        for value in (None, "x", [], {"toolActivity": "nope"}, {"composedBy": "manager", "usage": {"billing": "metered"}, "toolActivity": [None, 3]}):
            plan = ui_planner.plan(value, None, None, flags=ON)
            self.assertFalse(plan["eligible"])


class PlannerReviewRegressions(unittest.TestCase):
    """Independent review 2026-10-14 (P1 1-5, P2 6/7/9): each input below produced a wrong view decision before the fix."""

    def check(self, text, tools, *, eligible, form=None, runs=None, follows=False):
        case = {"text": text, "tools": tools, "runIds": runs or [], "followsArtifact": follows}
        plan = plan_case(case)
        self.assertEqual(plan["eligible"], eligible, f"{text!r}: {plan['reason']}")
        if form:
            self.assertEqual(plan["form"], form, text)

    def test_count_questions_are_never_upgraded(self):
        self.check("How many posts need attention?", [["attention_summary", "verified"]], eligible=False)
        self.check("Is my automation broken?", [["automation_get", "verified"]], eligible=False, runs=["r1"])
        self.check("When did it fail?", [["automation_get", "verified"]], eligible=False, runs=["r1"])

    def test_attention_upgrade_needs_an_attention_request(self):
        self.check("Write me a caption for tomorrow", [["attention_summary", "verified"]], eligible=False)

    def test_refinement_words_are_anchored(self):
        self.check("Now publish it", [["draft_get", "verified"]], eligible=False, follows=True)
        self.check("I only want a short caption", [["draft_get", "verified"]], eligible=False, follows=True)
        self.check("Only the ones for Instagram", [["draft_get", "verified"]], eligible=True, follows=True)

    def test_explicit_chart_is_not_a_decline(self):
        self.check("Show my reach in a line chart", [["publishing_summary", "verified"]], eligible=True, form="chart")
        self.check("幫我寫一句caption，介紹我嘅新曲", [["content_search", "verified"]], eligible=True)
        self.check("用一句話講我今個星期嘅安排", [["calendar_range", "verified"]], eligible=False)

    def test_breakdown_questions_keep_their_view(self):
        self.check("How many views did each platform get last week?", [["publishing_summary", "verified"]], eligible=True)

    def test_diagnosis_needs_a_failure_signal(self):
        self.check("I didn't like that caption, rewrite it", [["automation_get", "verified"]], eligible=False, runs=["r1"])
        self.check("why", [["job_get", "verified"]], eligible=False)
        self.check("What went wrong with yesterday's publish?", [["job_get", "verified"]], eligible=True, form="recovery")
        self.check("Why didn't my post go out?", [["job_get", "verified"]], eligible=True, form="recovery")

    def test_upgrade_journey_survives_a_full_journey_list(self):
        turn_ = turn({"text": "x", "tools": [["draft_get", "verified"], ["calendar_range", "verified"], ["library_search", "verified"], ["automation_get", "verified"]],
                      "runIds": ["r1"]})
        plan = ui_planner.plan(turn_, "Why did my automation fail?", "text", flags=ON)
        if plan["eligible"]:
            self.assertIn("J08", plan["journeyIds"])
            self.assertLessEqual(len(plan["journeyIds"]), ui_projection.MAX_JOURNEYS)

    def test_lone_x_is_not_a_platform(self):
        case = {"text": "Show my 3 x posts performance on Instagram", "tools": [["publishing_summary", "verified"]]}
        self.assertNotEqual(plan_case(case)["form"], "comparison")


class PlannerToolForm(unittest.TestCase):
    """J10 interactive tools: the only upgrade that needs no data read, behind RAFII_GENUI_TOOLS_ENABLED (flags["tools"])."""
    TOOLS = {**ON, "tools": True}
    ASKS = ("Build an interactive calculator for splitting a restaurant bill",
            "Can you make me a tip calculator?",
            "Create a unit converter for kilometres and miles",
            "make a loan estimator with an interest rate slider",
            "Build me a quick tool to compare two pricing options",
            "I need a countdown planner for my album launch",
            "Make a 5-question quiz about music theory",
            "整個計算機幫我計下每人要俾幾多",
            "幫我做個互動工具計算分帳",
            "做个计算器，算一下每个月要存多少",
            "帮我做一个单位换算器")
    PLAIN = ("What does engagement rate mean?", "How do I use the calculator on my phone?", "Which tool should I use to plan posts?",
             "Is a calculator better than a spreadsheet?", "計算機點樣用？", "做咩工具最好？", "Tell me about my week")

    def test_tool_requests_without_data_reads_become_a_j10_tool(self):
        for text in self.ASKS:
            for tools in ([], [["ui_guide", "verified"]], [["help_search", "verified"]]):
                with self.subTest(text=text, tools=tools):
                    plan = plan_case({"text": text, "tools": tools}, flags=self.TOOLS)
                    self.assertEqual((plan["eligible"], plan["form"], plan["reason"], plan["journeyIds"]), (True, "tool", "tool", ["J10"]))
                    self.assertEqual(plan["interactions"]["reads"], [])
                    self.assertEqual(plan["interactions"]["actions"], [])
                    self.assertFalse(plan["disclosure"]["asOfRequired"])

    def test_plain_questions_stay_text(self):
        for text in self.PLAIN:
            with self.subTest(text=text):
                plan = plan_case({"text": text}, flags=self.TOOLS)
                self.assertEqual((plan["eligible"], plan["form"]), (False, "text"))
                self.assertNotIn("J10", plan["journeyIds"])

    def test_any_workspace_read_rules_out_a_tool(self):
        text = "Build an interactive calculator for splitting a restaurant bill"
        for tools in ([["calendar_range", "verified"]], [["publishing_summary", "unverified"]], [["draft_get", "failed"]],
                      [["web_research", "verified"]], [["ui_guide", "verified"], ["memory_context", "verified"]], [["weather_now", "verified"]]):
            with self.subTest(tools=tools):
                plan = plan_case({"text": text, "tools": tools}, flags=self.TOOLS)
                self.assertNotEqual(plan["form"], "tool")
                self.assertNotIn("J10", plan["journeyIds"])
        for extra in ({"refs": [["draft", "d1"]]}, {"approvals": ["schedule_draft"]}):
            plan = plan_case({"text": text, **extra}, flags=self.TOOLS)
            self.assertNotIn("J10", plan["journeyIds"], extra)

    def test_tools_need_their_flag_text_modality_and_workspace_scope(self):
        text = "Build an interactive calculator for splitting a restaurant bill"
        self.assertEqual(plan_case({"text": text})["form"], "text", "flag off (default): plain text, production unchanged")
        self.assertFalse(plan_case({"text": text}, flags={**self.TOOLS, "enabled": False})["eligible"])
        for modality in ("voice", "image"):
            self.assertFalse(plan_case({"text": text, "modality": modality}, flags=self.TOOLS)["eligible"], modality)
        self.assertNotEqual(plan_case({"text": text, "scope": "founder", "founder": True}, flags=self.TOOLS)["form"], "tool")
        for veto in ({"composed": "site_agent"}, {"billing": "free"}, {"youtube": True}):
            self.assertFalse(plan_case({"text": text, **veto}, flags=self.TOOLS)["eligible"], veto)
        self.assertFalse(plan_case({"text": "Just tell me, no widgets: build a tip calculator"}, flags=self.TOOLS)["eligible"])

    def test_tool_plan_carries_no_request_text(self):
        plan = plan_case({"text": "Build a tip calculator for my Falcon launch dinner"}, flags=self.TOOLS)
        self.assertEqual(plan["form"], "tool")
        self.assertNotIn("Falcon", json.dumps(plan))

    def test_wiring_records_a_bounded_brief_only_when_active_and_flagged(self):
        env = {"RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_ACTIVE": "1",
               "RAFII_GENUI_PLANNER_WORKSPACES": WS}
        text = "Build an interactive calculator for splitting a restaurant bill\x00 " + "x" * 900
        case = {"text": text}
        off = service.ui_handoff(config.RuntimeConfig.from_environment(env), WS, turn(case), text, "text")
        self.assertEqual((off["eligible"], off["plan"]["form"]), (False, "text"))
        self.assertNotIn("toolBrief", off)
        cfg = config.RuntimeConfig.from_environment({**env, "RAFII_GENUI_TOOLS_ENABLED": "1"})
        self.assertNotIn("RAFII_GENUI_TOOLS_ENABLED", cfg.public()["flags"])
        self.assertFalse(cfg.genui_tools_for(WS, founder=True))
        self.assertNotIn("tools", cfg.genui_for(WS), "the public status shape (genui_for) is unchanged")
        on = service.ui_handoff(cfg, WS, turn(case), text, "text")
        self.assertEqual((on["eligible"], on["reason"], on["journeyIds"], on["plan"]["form"]), (True, "tool", ["J10"], "tool"))
        self.assertEqual(len(on["toolBrief"]), ui_projection.TOOL_BRIEF_CHARS)
        self.assertTrue(on["toolBrief"].startswith("Build an interactive calculator"))
        self.assertNotIn("\x00", on["toolBrief"])
        shadow = service.ui_handoff(config.RuntimeConfig.from_environment({**env, "RAFII_GENUI_TOOLS_ENABLED": "1", "RAFII_GENUI_PLANNER_ACTIVE": ""}),
                                    WS, turn(case), text, "text")
        self.assertEqual((shadow["eligible"], shadow["plan"]["form"]), (False, "tool"))
        self.assertNotIn("toolBrief", shadow, "shadow mode records the plan only")
        other = service.ui_handoff(cfg, OTHER, turn(case), text, "text")
        self.assertNotIn("toolBrief", other, "unlisted workspace: planner off")
        self.assertFalse(other["eligible"])

    def test_verify_line_accepts_the_tool_form(self):
        from postriff_phase2 import agent_observability as obs
        self.assertEqual(obs.clean({"uiPlan": "active:tool:upgrade"})[0], {"uiPlan": "active:tool:upgrade"})


class PlannerCorpus(unittest.TestCase):
    def test_every_labelled_case(self):
        failures = []
        for case in json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]:
            plan = plan_case(case)
            want = case["expect"]
            if (plan["eligible"], plan["form"]) != (want["eligible"], want["form"]):
                failures.append(f'{case["id"]}: got {plan["eligible"]}/{plan["form"]} ({plan["reason"]}), want {want["eligible"]}/{want["form"]}')
        self.assertEqual(failures, [])

    def test_planner_beats_baseline_on_both_error_kinds(self):
        import agent_ui_planner_eval
        report = agent_ui_planner_eval.evaluate(CORPUS)
        self.assertLessEqual(report["planner"]["inappropriateWidgets"], report["baseline"]["inappropriateWidgets"])
        self.assertLessEqual(report["planner"]["missedWidgets"], report["baseline"]["missedWidgets"])
        self.assertEqual(report["planner"]["safetyVetoOverrides"], 0)
        self.assertEqual(report["cases"], 37)

    def test_holdout_no_worse_than_baseline(self):
        # Held-out cases never tuned against; the planner is NOT required to get all of them (2026-10-14 first run: 13/15 forms).
        import agent_ui_planner_eval
        report = agent_ui_planner_eval.evaluate(CORPUS.with_name("planner_cases_holdout_v1.json"))
        self.assertLessEqual(report["planner"]["inappropriateWidgets"], report["baseline"]["inappropriateWidgets"])
        self.assertLessEqual(report["planner"]["missedWidgets"], report["baseline"]["missedWidgets"])
        self.assertEqual(report["planner"]["safetyVetoOverrides"], 0)


class PlannerWiring(unittest.TestCase):
    ENV = {"RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1"}
    FAIL = {"text": "Why did my Monday automation fail?", "tools": [["automation_get", "verified"]], "runIds": ["r1"], "refs": [["automation", "auto-1"]]}

    def test_default_off_keeps_the_baseline_exactly(self):
        cfg = config.RuntimeConfig.from_environment(self.ENV)
        self.assertEqual(cfg.genui_planner_for(WS), "off")
        decided = service.ui_handoff(cfg, WS, turn(self.FAIL), self.FAIL["text"], "text")
        self.assertEqual(set(decided), {"eligible", "slot", "reason", "journeyIds"})
        self.assertFalse(decided["eligible"])

    def test_allowlist_fails_closed(self):
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1"})
        self.assertEqual(cfg.genui_planner_for(WS), "off")
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_WORKSPACES": WS})
        self.assertEqual((cfg.genui_planner_for(WS), cfg.genui_planner_for(OTHER)), ("shadow", "off"))
        cfg = config.RuntimeConfig.from_environment({"RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_WORKSPACES": WS})
        self.assertEqual(cfg.genui_planner_for(WS), "off")   # GenUI itself off → planner off

    def test_public_status_contract_is_unchanged(self):
        # Regression (Depot cc7jjnr8g1): listing the planner switches in /status broke test_context_lens's pinned golden.
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_ACTIVE": "1"})
        self.assertFalse([k for k in cfg.public()["flags"] if k.startswith("RAFII_GENUI_PLANNER_")])

    def test_shadow_records_plan_without_changing_the_decision(self):
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_WORKSPACES": WS})
        decided = service.ui_handoff(cfg, WS, turn(self.FAIL), self.FAIL["text"], "text")
        self.assertFalse(decided["eligible"])
        self.assertEqual(decided["plan"]["mode"], "shadow")
        self.assertEqual((decided["plan"]["eligible"], decided["plan"]["form"], decided["plan"]["delta"]), (True, "recovery", "upgrade"))

    def test_active_applies_the_plan_only_for_listed_workspaces(self):
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_ACTIVE": "1",
                                                     "RAFII_GENUI_PLANNER_WORKSPACES": WS})
        decided = service.ui_handoff(cfg, WS, turn(self.FAIL), self.FAIL["text"], "text")
        self.assertEqual((decided["eligible"], decided["reason"], decided["plan"]["mode"]), (True, "diagnosis", "active"))
        self.assertEqual(decided["journeyIds"], ["J08"])
        other = service.ui_handoff(cfg, OTHER, turn(self.FAIL), self.FAIL["text"], "text")
        self.assertNotIn("plan", other)
        self.assertFalse(other["eligible"])

    def test_follow_up_needs_a_server_resolved_view(self):
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_ACTIVE": "1",
                                                     "RAFII_GENUI_PLANNER_WORKSPACES": WS})
        case = {"text": "Only the ones for Instagram", "tools": [["draft_get", "verified"]], "refs": [["draft", "draft-1"]]}
        # A client-sent uiContext id that did not re-resolve (stale/foreign) leaves ui_selection None: no follow-up upgrade.
        self.assertFalse(service.ui_handoff(cfg, WS, turn(case), case["text"], "text", ui_selection=None)["eligible"])
        resolved = service.ui_handoff(cfg, WS, turn(case), case["text"], "text", ui_selection={"references": [], "note": ""})
        self.assertEqual((resolved["eligible"], resolved["reason"]), (True, "follow_up"))

    def test_planner_failure_falls_back_to_baseline(self):
        cfg = config.RuntimeConfig.from_environment({**self.ENV, "RAFII_GENUI_PLANNER_ENABLED": "1", "RAFII_GENUI_PLANNER_ACTIVE": "1",
                                                     "RAFII_GENUI_PLANNER_WORKSPACES": WS})
        original = ui_planner.plan
        ui_planner.plan = lambda *a, **k: 1 / 0
        try:
            decided = service.ui_handoff(cfg, WS, turn(self.FAIL), self.FAIL["text"], "text")
        finally:
            ui_planner.plan = original
        self.assertEqual(set(decided), {"eligible", "slot", "reason", "journeyIds"})
        self.assertFalse(decided["eligible"])


class PlannerLayoutHint(unittest.TestCase):
    """Active mode only: the planner's form reaches the presenter as context.layout (enum values from fixed tables)."""

    def plan(self, **over):
        return {"version": ui_planner.VERSION, "mode": "active", "form": "recovery", "eligible": True, "reason": "diagnosis",
                "journeyIds": ["J08"], "interactions": {"local": ["expand_item"], "reads": ["refresh"], "actions": ["propose_retry"]}, **over}

    def test_active_plan_becomes_a_validated_hint(self):
        hint = ui_projection.layout_hint({"eligible": True, "plan": self.plan()})
        self.assertEqual(hint, {"form": "recovery", "local": ["expand_item"], "reads": ["refresh"], "actions": ["propose_retry"]})

    def test_shadow_text_tampered_or_missing_plans_give_no_hint(self):
        for handoff in ({"plan": self.plan(mode="shadow")}, {"plan": self.plan(form="text")}, {"plan": self.plan(form="<script>")},
                        {"plan": "x"}, {}, None, {"plan": self.plan(interactions={"local": ["rm -rf"], "reads": [], "actions": ["publish_now"]})}):
            hint = ui_projection.layout_hint(handoff)
            if hint is not None:   # a tampered interaction list is filtered to the fixed table, never passed through
                self.assertEqual((hint["local"], hint["actions"]), ([], []))
            else:
                self.assertIsNone(hint)
        self.assertIsNone(ui_projection.layout_hint({"plan": self.plan(form="<script>")}))

    def test_presenter_view_carries_layout_only_when_present(self):
        projection = {"journey_ids": ["J08"], "component_group_ids": [], "allowed_context": {"refs": [], "language": "en"}}
        self.assertNotIn("layout", ui_projection.presenter_view(projection)["context"])
        projection["allowed_context"]["layout"] = ui_projection.layout_hint({"plan": self.plan()})
        self.assertEqual(ui_projection.presenter_view(projection)["context"]["layout"]["form"], "recovery")


class PlannerTelemetry(unittest.TestCase):
    def test_verify_line_carries_only_the_plan_enums(self):
        from postriff_phase2 import agent_observability as obs
        plan = {"mode": "shadow", "form": "recovery", "delta": "upgrade", "reason": "diagnosis"}
        summary = obs.outcome_summary({"ui": {"eligible": False, "reason": "single_fact", "plan": plan}}, {}, "completed")
        self.assertEqual(summary["uiPlan"], "shadow:recovery:upgrade")
        self.assertIsNone(obs.outcome_summary({"ui": {"eligible": False, "reason": "single_fact"}}, {}, "completed")["uiPlan"])
        self.assertEqual(obs.clean({"uiPlan": "shadow:recovery:upgrade"})[0], {"uiPlan": "shadow:recovery:upgrade"})
        self.assertEqual(obs.clean({"uiPlan": "shadow:<secret>:upgrade"}), ({}, 1))


if __name__ == "__main__":
    unittest.main()
