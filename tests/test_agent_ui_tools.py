"""rafii-genui/1 J10 "Interactive tool": contracts, the empty manifest, local-only validation and the toolBrief egress gate.

Pure: no database, no model, no network (the trusted-validator seam is a fake transport). What it proves:
- J10 is a consumer journey with zero queries and zero actions, never founder and never combined with a data journey;
- the presenter plan for J10 is local-only (`policy.localOnly`), and the Python client refuses an accepted answer that still
  names a query or an action (a seam that ignored the policy);
- the person's request text (`toolBrief`) reaches presenter input ONLY for J10 + RAFII_GENUI_TOOLS_ENABLED + a turn that read
  no workspace data, bounded to 600 characters with URL/secret-looking words removed; every other journey still never sees it.

    PYTHONPATH=src:tests python -m unittest tests.test_agent_ui_tools
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config, ui_capabilities, ui_contracts, ui_domain, ui_presenter, ui_projection, ui_validator  # noqa: E402
from postriff_phase2.agent_runtime_v2.ui_http import UiAuth  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402

WS = "11111111-1111-4111-8111-111111111111"
TOOLS_ON = {"enabled": True, "actions": True, "edits": True, "canary": False, "tools": True}
TOOLS_OFF = {**TOOLS_ON, "tools": False}
REQUEST = "Build an interactive calculator for splitting a restaurant bill between 4 people with a 15% tip"
SECRET = "my bank PIN is 0000 and the launch codename is Falcon"


def auth(role="owner"):
    return UiAuth(workspace_id=WS, principal="00000000-0000-0000-0000-000000000001", member=Membership.from_row(role), role=role,
                  scope="workspace", scope_key="")


def turn(tools=(), *, brief=REQUEST, journeys=("J10",), **extra):
    """A finished, metered Manager turn whose active planner chose the J10 tool form (service.ui_handoff output)."""
    out = {"composedBy": "manager", "usage": {"billing": "metered", "route": "gpt-x"}, "answerText": "Here is your calculator. " + SECRET,
           "toolActivity": [{"tool": t, "status": s, "effect": "READ"} for t, s in tools], "references": [], "pendingApprovals": [],
           "changedEntities": [], "generatedAssets": [], "warnings": [], "language": "en",
           "routes": [{"agent": "rafii_manager", "provider": "openai", "model": "gpt-x"}],
           "ui": {"eligible": True, "slot": "main", "reason": "tool", "journeyIds": list(journeys), **({"toolBrief": brief} if brief is not None else {})}}
    out.update(extra)
    return out


class Contracts(unittest.TestCase):
    def test_j10_is_a_consumer_tool_journey(self):
        self.assertIn("J10", ui_contracts.JOURNEYS)
        self.assertIn("J10", ui_contracts.CONSUMER_JOURNEYS)
        self.assertNotIn("J10", ui_contracts.FOUNDER_JOURNEYS)
        self.assertEqual(ui_contracts.TOOL_JOURNEYS, ("J10",))
        self.assertNotIn("J09", ui_contracts.CONSUMER_JOURNEYS)
        self.assertEqual(ui_contracts.contract_manifest()["journeys"][-1], "J10")

    def test_j10_manifest_has_no_queries_and_no_actions(self):
        self.assertEqual((ui_domain.JOURNEY_QUERIES["J10"], ui_domain.JOURNEY_ACTIONS["J10"]), ([], []))
        manifest = ui_capabilities.build_manifest(None, auth(), {"journey_ids": ["J10"]}, scope="workspace", flags=TOOLS_ON)
        self.assertEqual((manifest["journeyIds"], manifest["queries"], manifest["actions"]), (["J10"], [], []))
        self.assertEqual(manifest["actionTargets"], {})
        self.assertEqual(manifest["queryConstraints"], {})

    def test_j10_never_joins_a_data_journey_and_never_founder_scope(self):
        manifest = ui_capabilities.build_manifest(None, auth(), {"journey_ids": ["J10", "J01"]}, scope="workspace")
        self.assertEqual(manifest["journeyIds"], ["J01"])
        self.assertTrue(manifest["queries"])
        founder = UiAuth(workspace_id=WS, principal="p", member=Membership.from_row("owner"), role="owner", scope="founder",
                         scope_key="founder:live:production")
        self.assertEqual(ui_capabilities.build_manifest(None, founder, {"journey_ids": ["J10"]}, scope="founder")["journeyIds"], [])

    def test_tools_flag_defaults_off_and_stays_out_of_public_status(self):
        base = {"RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1"}
        self.assertFalse(config.RuntimeConfig.from_environment(base).genui_tools_for(WS))
        for value in ("", "0", "false", "maybe"):
            self.assertFalse(config.RuntimeConfig.from_environment({**base, "RAFII_GENUI_TOOLS_ENABLED": value}).genui_tools_for(WS), value)
        on = config.RuntimeConfig.from_environment({**base, "RAFII_GENUI_TOOLS_ENABLED": "1"})
        self.assertTrue(on.genui_tools_for(WS))
        self.assertFalse(on.genui_tools_for(WS, founder=True))
        self.assertFalse(config.RuntimeConfig.from_environment({"RAFII_GENUI_TOOLS_ENABLED": "1"}).genui_tools_for(WS), "GenUI off → tools off")
        self.assertFalse(config.RuntimeConfig.from_environment({**base, "RAFII_GENUI_TOOLS_ENABLED": "1", "RAFII_GENUI_WORKSPACES": "someone-else"})
                         .genui_tools_for(WS), "outside the GenUI canary → tools off")
        self.assertNotIn("RAFII_GENUI_TOOLS_ENABLED", on.public()["flags"])
        self.assertNotIn("tools", on.genui_for(WS), "the /status genui shape is unchanged")


class NoDataPredicate(unittest.TestCase):
    def test_only_help_and_navigation_tools_count_as_no_data(self):
        self.assertTrue(ui_projection.reads_no_workspace_data(turn()))
        self.assertTrue(ui_projection.reads_no_workspace_data(turn([("ui_guide", "verified"), ("help_search", "verified")])))
        for tools in ([("calendar_range", "verified")], [("draft_get", "failed")], [("web_research", "blocked")], [("weather_now", "verified")]):
            self.assertFalse(ui_projection.reads_no_workspace_data(turn(tools)), tools)
        for key, value in (("references", [{"type": "draft", "id": "d1"}]), ("pendingApprovals", [{"type": "x"}]), ("generatedAssets", [{"id": "a"}]),
                           ("libraryIds", ["a" * 32]), ("research", {"state": "available"}), ("founder", {"mode": "live"}),
                           ("changedEntities", [{"type": "draft", "id": "d"}])):
            self.assertFalse(ui_projection.reads_no_workspace_data(turn(**{key: value})), key)
        for odd in (None, [], "x", {"toolActivity": "nope"}, {"toolActivity": [None]}):
            self.assertFalse(ui_projection.reads_no_workspace_data(odd), odd)


class ToolBriefEgress(unittest.TestCase):
    def project(self, result, flags=TOOLS_ON):
        return ui_projection.project_ui_context(None, auth(), result, "chat", {}, flags=flags)

    def test_brief_reaches_presenter_input_only_with_every_gate(self):
        projection = self.project(turn())
        self.assertEqual(projection["journey_ids"], ["J10"])
        self.assertEqual(projection["allowed_context"]["toolBrief"], REQUEST)
        self.assertEqual((projection["data_bindings"], projection["action_bindings"]), ([], []))
        view = ui_projection.presenter_view(projection, tools_enabled=True)
        self.assertEqual(view["context"]["toolBrief"], REQUEST)
        # Default (and every caller that does not opt in): the brief is dropped.
        self.assertNotIn("toolBrief", ui_projection.presenter_view(projection)["context"])
        self.assertNotIn("toolBrief", ui_projection.presenter_view(projection, tools_enabled=False)["context"])
        # The native answer never reaches the presenter, J10 or not.
        self.assertNotIn(SECRET, json.dumps(view))

    def test_brief_is_never_added_for_data_journeys(self):
        data = turn([("calendar_range", "verified")], journeys=("J02",), brief=REQUEST + " " + SECRET)
        projection = self.project(data)
        self.assertNotIn("toolBrief", projection["allowed_context"])
        view = ui_projection.presenter_view({**projection, "allowed_context": {**projection["allowed_context"], "toolBrief": SECRET}}, tools_enabled=True)
        self.assertNotIn("toolBrief", view["context"], "presenter_view drops a brief on any non-J10 view, even if one were injected")
        self.assertNotIn(SECRET, json.dumps(view))

    def test_j10_view_is_refused_unless_flag_and_no_data_read(self):
        for result, flags in ((turn(), TOOLS_OFF), (turn(), None), (turn([("calendar_range", "verified")]), TOOLS_ON),
                              (turn(references=[{"type": "draft", "id": "d1"}]), TOOLS_ON), (turn(journeys=("J10", "J01")), TOOLS_ON)):
            with self.assertRaises(AlphaError) as refused:
                ui_projection.project_ui_context(None, auth(), result, "chat", {}, flags=flags)
            self.assertEqual(refused.exception.code, "ui_not_eligible")

    def test_brief_is_bounded_and_scrubbed(self):
        long = "Make a loan estimator. " + "y" * 2000
        self.assertEqual(len(self.project(turn(brief=long))["allowed_context"]["toolBrief"]), ui_projection.TOOL_BRIEF_CHARS)
        self.assertNotIn("\x07", ui_projection.tool_brief("tip\x07 calculator"))
        self.assertEqual(ui_projection.tool_brief(None), "")
        projection = self.project(turn(brief="Build a converter like https://example.com/x?token=abc and Bearer sk-abcdefghijklmnop please"))
        context = ui_presenter.presenter_context(projection, tools=True)["context"]
        self.assertEqual(context["toolBrief"], "Build a converter like and please")
        self.assertNotIn("toolBrief", ui_presenter.presenter_context(projection, tools=False)["context"])
        self.assertNotIn("toolBrief", ui_presenter.presenter_context(self.project(turn(brief=None)), tools=True)["context"])


class LocalOnlyPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_agent_ui_stream_fakes import make_cfg
        cls.make_cfg = staticmethod(make_cfg)
        cls.assets = ui_presenter.load_assets()

    def plan(self, cfg, result=None, flags=TOOLS_ON):
        projection = ui_projection.project_ui_context(None, auth(), result or turn(), "chat", {}, flags=flags)
        return ui_presenter.build_plan(cfg, self.assets, projection, projection["manifest"])

    def test_plan_is_local_only_and_carries_the_brief_only_with_the_flag(self):
        on = self.plan(self.make_cfg(RAFII_GENUI_TOOLS_ENABLED="1"))
        self.assertEqual(on.prompt_key, "consumer:J10:generate")
        self.assertIs(on.policy["localOnly"], True)
        self.assertEqual((on.policy["readBindings"], on.policy["actionIds"]), ([], []))
        self.assertIn(REQUEST, on.input_text)
        self.assertIn("CONTEXT.toolBrief", on.input_text)
        self.assertNotIn(SECRET, on.instructions + on.input_text)
        # The deployment flag is re-checked when the plan is built (e.g. an edit after the switch went off): no brief.
        off = self.plan(self.make_cfg())
        self.assertNotIn(REQUEST, off.input_text)
        self.assertIs(off.policy["localOnly"], True)

    def test_egress_stays_on_the_parent_turns_provider(self):
        result = turn(routes=[{"agent": "rafii_manager", "provider": "gateway", "model": "gpt-x"}])
        with self.assertRaises(ui_presenter.PresentationRefused) as refused:
            self.plan(self.make_cfg(RAFII_GENUI_TOOLS_ENABLED="1"), result)
        self.assertEqual(refused.exception.reason, "egress_denied")


class ValidatorDefense(unittest.TestCase):
    SECRET_ENV = {"RAFII_GENUI_VALIDATOR_SECRET": "s" * 40, "RAFII_GENUI_VALIDATOR_URL": "http://validator.test"}

    def answer(self, **over):
        source = 'root = RafiiRoot([r])\n$n = 2\nr = Readout("Double", $n * 2)'
        body = {"accepted": True, "canonicalSource": source, "sourceHash": ui_contracts.sha256_text(source), "statementCount": 3, "queryNames": [],
                "actionIds": [], "componentNames": ["RafiiRoot", "Readout"], "stateNames": ["$n"], "formNames": [], "errors": [], "libraryHash": "h" * 64,
                "libraryVersion": "rafii-components/1.1.0", **over}
        return lambda url, body_bytes, headers, timeout: (200, json.dumps(body).encode())

    def validate(self, transport, policy):
        return ui_validator.validate_and_merge_ui(None, "root = RafiiRoot([])", "h" * 64, "generate", policy=policy, scope={}, transport=transport,
                                                 values=self.SECRET_ENV)

    def test_a_local_only_answer_naming_a_query_or_action_is_refused(self):
        policy = {"rootName": "RafiiRoot", "allowedComponents": ["RafiiRoot", "Readout"], "readBindings": [], "actionIds": [], "localOnly": True}
        self.assertTrue(self.validate(self.answer(), policy)["accepted"])
        for over in ({"queryNames": ["drafts_list"]}, {"actionIds": ["draft_rewrite"]}):
            result = self.validate(self.answer(**over), policy)
            self.assertFalse(result["accepted"], over)
            self.assertEqual(result["errors"], ["local_only_violation"])
        self.assertTrue(self.validate(self.answer(queryNames=["drafts_list"]), {**policy, "localOnly": False})["accepted"], "data views unchanged")


if __name__ == "__main__":
    unittest.main()
