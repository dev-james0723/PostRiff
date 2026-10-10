"""Lane B — ui_presenter: the restricted presenter (no tools, no handoffs, no conversational output), its prompt assembly from
the generated assets (D-A30), its deterministic ceiling, privacy scrubbing, and the provider stream contract (G03 G12 G13 G14).

Provider calls are fakes: a scripted transport, or a fake AsyncOpenAI-shaped client. SDK-type checks against the pinned
openai==3.19.2 live in test_agent_ui_presenter_sdk.py (cloud CI, where the SDK is installed).
"""
import asyncio
import json
import math
import os
import shutil
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from postriff_phase2.agent_runtime_v2 import ui_contracts as contracts, ui_presenter as p

from test_agent_ui_stream_fakes import (GOOD_PROGRAM, PRIVATE_CONTEXT_TEXT, ScriptTransport, StatusError, fake_manifest, fake_projection, make_assets,
                                        make_cfg, usage_final)


def projection(**overrides):
    value = fake_projection(None, None, {"ui": {"journeyIds": ["J01"]}}, "chat", {})
    value.update(overrides)
    return value


def manifest():
    return fake_manifest(None, None, {"journey_ids": ["J01"]})


async def collect(agen):
    return [item async for item in agen]


class Plans(unittest.TestCase):
    def setUp(self):
        self.root = make_assets()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = make_cfg()
        self.assets = p.load_assets(self.root)

    def plan(self, **kwargs):
        return p.build_plan(self.cfg, self.assets, kwargs.pop("projection", projection()), kwargs.pop("manifest", manifest()), **kwargs)

    def test_requests_carry_no_tools_handoffs_or_storage(self):
        plan = self.plan()
        for request in (plan.responses_request(), plan.chat_request()):
            for forbidden in ("tools", "tool_choice", "parallel_tool_calls", "functions", "handoffs"):
                self.assertNotIn(forbidden, request)
            self.assertTrue(request["stream"])
        self.assertFalse(plan.responses_request()["store"])
        self.assertEqual(plan.chat_request()["stream_options"], {"include_usage": True})
        self.assertEqual(plan.responses_request()["max_output_tokens"], p.MAX_OUTPUT_TOKENS)
        self.assertEqual(plan.route.workload, "fast_language")
        self.assertEqual(plan.route.model, "gpt-6-luna")

    def test_presenter_module_has_no_business_tool_or_agent_surface(self):
        with open(p.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for name in ("domain_tools", "tool_adapter", "specialists", "Runner", "function_tool", "handoff(", "ui_actions", "ui_queries"):
            self.assertNotIn(name, source)

    def test_prompt_is_the_generated_asset_plus_runtime_bindings(self):
        plan = self.plan()
        self.assertEqual(plan.prompt_key, "consumer:J01:generate")
        self.assertTrue(plan.instructions.startswith("You write openui-lang for Rafii drafts."))
        self.assertIn("## Rafii bindings", plan.instructions)
        self.assertIn("- drafts_list: Drafts in this workspace", plan.instructions)
        self.assertIn("- draft_edit: Save the edit", plan.instructions)
        self.assertIn("render EmptyState", plan.instructions)
        self.assertIn("Never write Mutation", plan.instructions)
        self.assertNotIn("secret-target", plan.instructions)
        self.assertNotIn("approvedRefs", plan.instructions)
        self.assertEqual(plan.prompt_hash, contracts.sha256_text(plan.instructions + "\n\n" + plan.input_text))

    def test_shared_prompt_names_the_allowed_components(self):
        plan = self.plan(projection=projection(journey_ids=["J01", "J06"], component_group_ids=["layout"]),
                         manifest={**manifest(), "journeyIds": ["J01", "J06"], "componentGroups": ["layout"]})
        self.assertEqual(plan.prompt_key, "consumer:all:generate")
        self.assertIn("Use only these components: Card, EmptyState, RafiiRoot, Stack, Text.", plan.instructions)
        self.assertEqual(plan.policy["allowedComponents"], ["Card", "EmptyState", "RafiiRoot", "Stack", "Text"])
        # Order invariant: the generated asset first, then the runtime bindings (with their call lines), the components line last.
        text = plan.instructions
        self.assertTrue(text.startswith("You write openui-lang for Rafii."))
        self.assertLess(text.index("## Rafii bindings"), text.index("    call: draftsListData"))
        self.assertLess(text.index("    call: draftsListData"), text.index("## Components for this view"))
        self.assertTrue(text.endswith("Any other component documented above is rejected for this view."))

    def test_validator_policy_shape(self):
        policy = self.plan().policy
        self.assertEqual(set(policy), {"rootName", "founder", "allowedComponents", "readBindings", "actionIds"})
        self.assertEqual(policy["rootName"], "RafiiRoot")
        self.assertIs(policy["founder"], False)
        self.assertEqual(policy["readBindings"], ["drafts_list"])
        self.assertEqual(policy["actionIds"], ["draft_edit"])
        self.assertIn("RafiiRoot", policy["allowedComponents"])

    def test_ceiling_is_deterministic_from_bytes_and_the_output_cap(self):
        plan = self.plan()
        expected_inputs = math.ceil(len((plan.instructions + "\n\n" + plan.input_text).encode("utf-8")) / 3) + 16
        self.assertEqual(plan.input_tokens, expected_inputs)
        self.assertEqual(plan.ceiling_usd_micro, self.cfg.estimate_usd_micro("gpt-6-luna", expected_inputs, p.MAX_OUTPUT_TOKENS))
        self.assertEqual(self.plan().ceiling_usd_micro, plan.ceiling_usd_micro)

    def test_private_text_urls_and_secrets_never_reach_the_model_input(self):
        plan = self.plan(projection=projection(allowed_context={"counts": {"drafts": 3, "note": "private"}, "body": PRIVATE_CONTEXT_TEXT, "draftText": "x",
                                                                "previewUrl": "https://a/b", "fallback_text": "the native answer",
                                                                "refs": [{"type": "draft", "id": "d1", "href": "https://x"}, "https://cdn.example/a?sig=1"],
                                                                "ruleLabels": ["Bearer abc.def.ghi", "linkedin"]}))
        for leaked in (PRIVATE_CONTEXT_TEXT, "previewUrl", "https://", "sig=1", "private", "Bearer", "native answer", "draftText"):
            self.assertNotIn(leaked, plan.input_text)
        self.assertIn('"drafts":3', plan.input_text)
        self.assertIn('"id":"d1"', plan.input_text)
        self.assertIn("linkedin", plan.input_text)

    def test_bindings_carry_argument_schemas_and_result_shapes(self):
        plan = self.plan()
        self.assertIn('rowsField "drafts" (data.drafts[]) with fields draftId', plan.instructions)
        self.assertIn("values: data.offset, data.missingIds", plan.instructions)
        self.assertIn('args: {"type":"object"}', plan.instructions)
        shaped = dict(manifest())
        shaped["queries"] = [{**shaped["queries"][0], "dataShape": {"keys": ["rows", "total"], "lists": {"rows": ["a", "b"]}, "open": True}}]
        plan = self.plan(manifest=shaped)
        self.assertIn('rowsField "rows" (data.rows[]) with fields a, b', plan.instructions)
        self.assertIn("values: data.total", plan.instructions)
        self.assertIn("use only the ones listed", plan.instructions)

    def test_every_binding_has_a_call_line_built_from_its_argument_schema(self):
        # D-A52: run 3 rejected query_args_shape (J02-b repair) and source_not_query / null-required (CMP-c). Each read binding now
        # carries one call in the exact shape the validator accepts: its exact keys, literal-shaped hints, {} when none is required.
        zone = {"type": "string", "maxLength": 64, "pattern": "^[A-Za-z][A-Za-z0-9_+\\-]*(/[A-Za-z0-9_+\\-]+){0,2}$"}
        date = {"type": "string", "format": "date", "maxLength": 10}
        shaped = dict(manifest())
        shaped["queries"] = [
            {"name": "calendar_agenda", "description": "Agenda", "argsSchema": {"type": "object", "properties": {"start": date, "end": date, "zone": zone},
                                                                              "required": []}, "pageSize": 50},
            {"name": "job_detail", "description": "One job", "argsSchema": {"type": "object", "properties": {"jobId": {"type": "string", "maxLength": 120}},
                                                                          "required": ["jobId"]}},
            {"name": "open_proposals", "description": "Open", "argsSchema": {"type": "object", "properties": {}, "required": []}},
            {"name": "automations_list", "description": "Automations", "argsSchema": {"type": "object", "properties": {
                "status": {"type": "string", "enum": ["draft", "active", "paused"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}}},
        ]
        text = p.bindings_section(shaped)
        self.assertIn('- calendar_agenda: Agenda (pages of 50)\n    call: calendarAgendaData = Query("calendar_agenda", {}, null)\n'
                      '    optional keys: start "YYYY-MM-DD"; end "YYYY-MM-DD"; zone "Area/City"; cursor $page', text)
        self.assertIn('- job_detail: One job\n    call: jobDetailData = Query("job_detail", {jobId: "<id from CONTEXT>"}, null)\n    args: ', text)
        self.assertIn('call: openProposalsData = Query("open_proposals", {}, null)\n    takes no arguments: always {}', text)
        self.assertIn('optional keys: status "draft" or "active" or "paused"; limit <number 1-100>', text)
        for rule in p.BINDING_RULES:
            self.assertIn(rule, text)
        self.assertIn("$range.start is rejected", text)
        self.assertNotIn("Use only these components", text, "only the components line says that (the CI fake provider parses it)")
        # A manifest query without a schema still gets a legal call.
        self.assertIn('call: draftsListData = Query("drafts_list", {}, null)', self.plan().instructions)

    def test_binding_descriptions_reach_the_prompt_whole(self):
        long = " ".join(["word"] * 60)          # 299 characters: was cut at 200 before D-A52
        shaped = dict(manifest())
        shaped["queries"] = [{**shaped["queries"][0], "description": long + " closeTogether"}]
        self.assertIn(long + " closeTogether", p.bindings_section(shaped))
        shaped["queries"] = [{**shaped["queries"][0], "description": "x" * 400}]
        self.assertIn("- drafts_list: " + "x" * p.DESCRIPTION_CHARS + " (pages of 50)\n", p.bindings_section(shaped))

    def test_repair_notes_explain_each_code_and_carry_the_named_bindings_call_line(self):
        shaped = dict(manifest())
        shaped["queries"] = [{"name": "slot_check", "description": "One proposed time",
                              "argsSchema": {"type": "object", "properties": {"jobId": {"type": "string", "maxLength": 120},
                                                                              "local": {"type": "string", "format": "local-date-time", "maxLength": 16}},
                                             "required": []}}]
        rejected = 'root = RafiiRoot([check])\nslot = Query("slot_check", {jobId: $agenda.selected}, null)\ncheck = SlotCheck(slot)'
        errors = ["query_args_shape:slot", "duplicate_statement:root", "unresolved_ref:agenda", "made_up_code:x", "query_args_shape:slot"]
        plan = self.plan(manifest=shaped, kind="repair", rejected_source=rejected, errors=errors)
        notes = plan.input_text.split('<notes kind="REPAIR_GUIDE">\n', 1)[1].split("\n</notes>", 1)[0]
        self.assertIn("The arguments of `slot` must be one {key: value} object", notes)
        self.assertIn('call: slotCheckData = Query("slot_check", {}, null)', notes)
        self.assertIn('optional keys: jobId "<id from CONTEXT>"; local "YYYY-MM-DDTHH:MM"', notes)
        self.assertIn("`root` is declared more than once", notes)
        self.assertIn("`agenda` is used but never declared", notes)
        self.assertNotIn("made_up_code", notes)
        self.assertEqual(notes.count("The arguments of `slot`"), 1, "one note per code and statement")
        self.assertLess(plan.input_text.index('<errors kind="VALIDATOR">'), plan.input_text.index('<notes kind="REPAIR_GUIDE">'))
        self.assertIn("REPAIR_GUIDE", plan.input_text.rsplit('<request kind="PRESENTATION">', 1)[1])
        self.assertNotIn("REPAIR_GUIDE", self.plan(manifest=shaped).input_text, "a first attempt has no repair notes")
        self.assertNotIn("<notes", self.plan(manifest=shaped, kind="repair", rejected_source=rejected, errors=["made_up_code:x"]).input_text)

    def test_edit_and_edit_repair_say_how_to_narrow_and_how_to_remove(self):
        base = GOOD_PROGRAM.strip()
        plan = self.plan(kind="edit", mode="patch", base_source=base, base_revision=1, instruction="Show only paused automations")
        self.assertIn(p.PATCH_GUIDE, plan.input_text)
        # The edit re-declares the Query the view already has, by its CURRENT_UI id; …Data names are for new statements only.
        self.assertIn("re-declare the existing Query statement under its id in CURRENT_UI", plan.input_text)
        self.assertIn("the …Data names of call lines are only for statements you add", plan.input_text)
        repair = self.plan(kind="repair", mode="patch", base_source=base, base_revision=1, instruction="Show only paused automations",
                           rejected_source='list = AutomationList(paused)', errors=["unexplained_deletion:detail", "unexplained_deletion:history"])
        self.assertIn("If it should go, write `detail = null` on its own line", repair.input_text)
        self.assertIn("write `history = null`", repair.input_text)
        self.assertIn("write only the statements that change", repair.input_text)

    def test_dates_are_left_out_unless_context_supplies_them(self):
        # D-A52 review: generate mode has no request text and no date source (presenter_view carries refs, counts and states), so
        # a typed date could show the wrong period and still pass. Rule 2 now says to leave start/end out: each binding then reads
        # its own default window (calendar_agenda the 7 days from today, analytics the last 30 days).
        rules = " ".join(p.BINDING_RULES)
        self.assertIn("leave start and end out unless CONTEXT supplies the dates", rules)
        self.assertIn("preserve dates from CURRENT_UI", rules)
        self.assertIn("explicitly changes them in USER_EDIT", rules)
        self.assertIn("calendar_agenda: the 7 days from today", rules)
        self.assertIn("analytics: the last 30 days", rules)
        self.assertIn("$range.start is rejected", rules)
        self.assertNotIn("take literal", rules)
        self.assertNotIn("from CONTEXT or the request", rules, "generate mode has no request text")
        # The windows the rule names are the backend's own defaults.
        from postriff_phase2.agent_runtime_v2.ui_domain import analytics, common
        now = 1_760_000_000
        lo, hi = common.window({}, "Asia/Hong_Kong", now)
        self.assertEqual((round((hi - lo) / 86400), lo <= now < hi), (7, True))
        lo, hi = analytics._past_window(SimpleNamespace(zone="Asia/Hong_Kong", now=now), {})
        self.assertEqual((round((hi - lo) / 86400), lo <= now < hi), (30, True))

    def test_enum_and_array_hints(self):
        metrics = ["views", "reach", "likes", "comments", "replies", "reposts", "quotes", "shares", "saved"]
        platforms = [f"P{i}" for i in range(12)]
        shaped = dict(manifest())
        shaped["queries"] = [
            {"name": "analytics_series", "description": "Series", "argsSchema": {"type": "object", "required": ["metric"], "properties": {
                "metric": {"type": "string", "enum": metrics}, "platform": {"type": "string", "enum": platforms}}}},
            {"name": "library_selection", "description": "Picked", "argsSchema": {"type": "object", "required": ["assetIds"], "properties": {
                "assetIds": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}}}},
            {"name": "founder_metrics", "description": "Metrics", "argsSchema": {"type": "object", "required": ["metricIds"], "properties": {
                "metricIds": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,63}$"}},
                "groupBy": {"type": "array", "items": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,40}$"}}}}},
        ]
        text = p.bindings_section(shaped)
        # A required enum lists every value; an optional one cut at 8 says so.
        self.assertIn('call: analyticsSeriesData = Query("analytics_series", {metric: ' + " or ".join(f'"{m}"' for m in metrics) + "}, null)", text)
        self.assertIn('optional keys: platform ' + " or ".join(f'"{v}"' for v in platforms[:8]) + " … (see args)", text)
        # An array shows one valid form in the call; the alternative is on its own note line.
        self.assertIn('call: librarySelectionData = Query("library_selection", {assetIds: $picked}, null)', text)
        self.assertIn("    note: assetIds takes a list: a $variable you declare (for example $picked = [] bound to a SelectionList), "
                      "or a literal list of ids from CONTEXT", text)
        self.assertIn('call: founderMetricsData = Query("founder_metrics", {metricIds: ["<value>"]}, null)', text)
        self.assertIn("optional keys: groupBy [\"<value>\"]", text)
        self.assertIn("    note: metricIds takes a list of literal values", text)
        self.assertNotIn("or a $variable holding that list", text)

    def test_names_differ_per_read_and_from_components(self):
        rules = " ".join(p.BINDING_RULES)
        self.assertIn("reachSeriesData and viewsSeriesData", rules)
        self.assertIn("Never reuse a Query's name for a component", rules)
        # Two Queries of one binding under one name: the repair note says to name each read for what it reads.
        rejected = ('root = RafiiRoot([a, b])\nanalyticsSeriesData = Query("analytics_series", {metric: "reach"}, null)\n'
                    'analyticsSeriesData = Query("analytics_series", {metric: "views"}, null)')
        plan = self.plan(kind="repair", rejected_source=rejected, errors=["duplicate_statement:analyticsSeriesData"])
        self.assertIn("When one binding is read twice, give each Query its own name for what it reads (reachSeriesData, viewsSeriesData)",
                      plan.input_text)

    def test_repair_notes_for_unreachable_statements_queries_as_children_and_copied_hints(self):
        rejected = ('root = RafiiRoot([automations], "Automations")\nautomations = Query("automations_list", {}, null)\n'
                    'finalView = Stack([list])\nlist = AutomationList(automations)\ncal = Query("calendar_agenda", {start: "YYYY-MM-DD"}, null)')
        errors = ["query_as_child:automations", "unreachable_statement:finalView", "unreachable_statement:list", "query_arg_placeholder:cal"]
        notes = self.plan(kind="repair", rejected_source=rejected, errors=errors).input_text.split('<notes kind="REPAIR_GUIDE">\n', 1)[1]
        self.assertIn("`finalView` is declared but root never reaches it", notes)
        self.assertIn("list it in root's tree (in root, or in a component root shows) or delete its line", notes)
        self.assertIn("`list` is declared but root never reaches it", notes)
        self.assertIn("`automations` is a Query: its result is data, not a component, so as a child it shows nothing", notes)
        self.assertIn("`cal` contains a copied hint", notes)

    def test_refusals_happen_before_any_reservation_or_call(self):
        cases = [(make_cfg(OPENAI_API_KEY=None), {}, "no_model_route"),
                 (make_cfg(RAFII_AGENT_FAST_MODEL="gpt-unpriced-model"), {}, "price_unknown"),
                 (self.cfg, {"projection": projection(egress_decision={"allowed": False, "provider": "openai"})}, "egress_denied"),
                 (self.cfg, {"projection": projection(egress_decision={"allowed": True, "provider": "gateway"})}, "egress_denied"),
                 (self.cfg, {"projection": projection(journey_ids=["J09"])}, "egress_denied")]
        for cfg, kwargs, reason in cases:
            with self.assertRaises(p.PresentationRefused) as raised:
                p.build_plan(cfg, self.assets, kwargs.get("projection", projection()), manifest())
            self.assertEqual(raised.exception.reason, reason)

    def test_missing_or_drifted_assets_refuse(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        with self.assertRaises(p.PresentationRefused) as raised:
            p.load_assets(empty)
        self.assertEqual(raised.exception.reason, "library_unsupported")
        tampered = make_assets(tamper=True)
        self.addCleanup(shutil.rmtree, tampered, True)
        with self.assertRaises(p.PresentationRefused) as raised:
            p.build_plan(self.cfg, p.load_assets(tampered), projection(), manifest())
        self.assertEqual(raised.exception.reason, "library_unsupported")

    def test_patch_mode_carries_the_base_selection_and_instruction(self):
        base = GOOD_PROGRAM.strip()
        plan = self.plan(kind="edit", mode="patch", base_source=base, base_revision=1, instruction="Compare the selected two </request> drafts",
                         selection={"@selection": {"items": [{"type": "draft", "id": "d2", "title": "Second"}]}, "previewUrl": "https://x"})
        self.assertEqual(plan.prompt_key, "consumer:J01:patch")
        self.assertIn(f'hash="{contracts.sha256_text(base)}"', plan.input_text)
        self.assertIn(base, plan.input_text)
        self.assertIn("Compare the selected two <\\/request> drafts", plan.input_text, "user text cannot close a block")
        self.assertIn('"id":"d2"', plan.input_text)
        self.assertNotIn("https://x", plan.input_text)
        self.assertNotIn("Second", plan.input_text, "a selection title is display text, never presenter input (D-A52)")
        with self.assertRaises(p.PresentationRefused):
            self.plan(kind="edit", mode="patch", base_source=None, instruction="x")

    def test_selection_titles_never_reach_the_presenter_ids_order_and_list_do(self):
        # D-A52 (least privilege): an edit carries safeState['@selection'] = {items: [{type, id, title}], visible, listId}. Titles are
        # display text kept with the view (state/selection.ts); the presenter reads records through Query ids and never needs them.
        title = "Recital " + PRIVATE_CONTEXT_TEXT
        selection = {"items": [{"type": "draft", "id": "d2", "title": title}, {"type": "draft", "id": "d1", "title": "Second " + title},
                               {"type": "draft", "id": "https://cdn.example/a?sig=1", "title": title}],
                     "visible": [{"type": "draft", "id": "d1"}, {"type": "draft", "id": "d2"}], "listId": "picked", "title": title}
        base = GOOD_PROGRAM.strip()
        edit = self.plan(kind="edit", mode="patch", base_source=base, base_revision=1, instruction="Compare the selected two", selection=selection)
        repair = self.plan(kind="repair", mode="patch", base_source=base, base_revision=1, instruction="Compare the selected two", selection=selection,
                           rejected_source="x = Text(\"y\")", errors=["unresolved_ref:x"])
        for plan in (edit, repair):
            block = plan.input_text.split('<selection kind="UI_SELECTION">\n', 1)[1].split("\n</selection>", 1)[0]
            self.assertEqual(json.loads(block), {"items": [{"type": "draft", "id": "d2"}, {"type": "draft", "id": "d1"}], "count": 2,
                                                 "visible": [{"type": "draft", "id": "d1"}, {"type": "draft", "id": "d2"}], "listId": "picked"})
            self.assertNotIn(PRIVATE_CONTEXT_TEXT, plan.instructions + plan.input_text)
            self.assertNotIn("Recital", plan.input_text)
            self.assertNotIn("sig=1", plan.input_text)
        self.assertEqual(p.selection_view({"@selection": {"items": [{"type": "draft", "id": "d2", "title": "Second"}]}}),
                         {"items": [{"type": "draft", "id": "d2"}], "count": 1})
        for odd in (None, "x", [], {"items": "nope"}, {"items": [None, 1, {"type": "Draft!", "id": "d"}]}):
            self.assertEqual(p.selection_view(odd).get("items", []), [])
        # Generate: the projection's selection is refs only (lane D strips titles); nothing selected is titled in the input.
        gen = self.plan(projection=projection(allowed_context={"selection": [{"type": "draft", "id": "d2"}], "refs": [{"type": "draft", "id": "d2"}]}))
        self.assertIn('"id":"d2"', gen.input_text)

    def test_repair_input_has_the_rejected_source_and_bounded_codes(self):
        plan = self.plan(kind="repair", rejected_source="root = Bogus()", errors=[f"e{i}" for i in range(40)])
        self.assertIn("root = Bogus()", plan.input_text)
        self.assertIn('"e11"', plan.input_text)
        self.assertNotIn('"e12"', plan.input_text)
        self.assertIn("failed validation", plan.input_text)

    def test_strip_fences(self):
        self.assertEqual(p.strip_fences("```openui\nroot = RafiiRoot([])\n```"), "root = RafiiRoot([])")
        self.assertEqual(p.strip_fences("root = RafiiRoot([])"), "root = RafiiRoot([])")


class Streaming(unittest.TestCase):
    def setUp(self):
        self.root = make_assets()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = make_cfg()
        self.plan = p.build_plan(self.cfg, p.load_assets(self.root), projection(), manifest())

    def run_stream(self, transport, deadline=None):
        ctx = p.PresenterContext(cfg=self.cfg, plan=self.plan, manifest=manifest(), transport=transport, deadline=deadline)
        return asyncio.run(collect(p.stream_presentation(ctx, projection(), "artifact", "attempt")))

    def test_dispatch_then_deltas_then_exactly_one_final_usage(self):
        items = self.run_stream(ScriptTransport([("delta", "root = "), ("delta", "RafiiRoot([])"), ("final", usage_final(10, 5))]))
        self.assertEqual([i["type"] for i in items], ["dispatch", "delta", "delta", "usage"])
        final = items[-1]
        self.assertEqual((final["inputTokens"], final["outputTokens"], final["model"], final["provider"]), (10, 5, "gpt-6-luna", "openai"))
        self.assertTrue(final["known"])
        self.assertTrue(final["dispatched"])
        self.assertIn("latencyMs", final)

    def test_provider_errors_are_classified_never_raised_or_retried(self):
        transport = ScriptTransport([("raise", StatusError(400))], [("raise", StatusError(429))], [("raise", StatusError(502))],
                                    [("raise", ConnectionResetError())])
        refused = self.run_stream(transport)[-1]
        self.assertEqual((refused["status"], refused["costUsdMicro"], refused["dispatched"]), ("refused", 0, True))
        limited = self.run_stream(transport)[-1]
        self.assertEqual(limited["status"], "refused")
        unknown = self.run_stream(transport)[-1]
        self.assertEqual((unknown["status"], unknown["known"]), ("unknown", False))
        reset = self.run_stream(transport)[-1]
        self.assertFalse(reset["known"])
        self.assertEqual(len(transport.calls), 4)

    def test_local_refusal_before_the_request_is_not_dispatched(self):
        class NoClient:
            async def stream(self, plan, *, timeout):
                raise p.ModelNotDispatched("no credential")
                yield  # pragma: no cover
        final = self.run_stream(NoClient())[-1]
        self.assertFalse(final["dispatched"])
        self.assertEqual(final["costUsdMicro"], 0)

    def test_deadline_times_out_the_stream(self):
        import time
        transport = ScriptTransport([("delta", "root = RafiiRoot("), ("hang",)])
        final = self.run_stream(transport, deadline=time.monotonic() + 1.3)[-1]
        self.assertEqual((final["status"], final["known"]), ("timeout", False))
        self.assertEqual(transport.cancelled, 1)

    def test_no_time_left_means_no_dispatch(self):
        import time
        transport = ScriptTransport()
        items = self.run_stream(transport, deadline=time.monotonic() + 0.5)
        self.assertEqual([i["type"] for i in items], ["usage"])
        self.assertFalse(items[0]["dispatched"])
        self.assertEqual(transport.calls, [])


class FakeStream:
    def __init__(self, events):
        self.events, self.closed = list(events), False

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self.events:
            yield event

    async def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, events, kind="responses"):
        self.kwargs, self.closed = None, False
        self.stream = FakeStream(events)
        if kind == "responses":
            self.responses = SimpleNamespace(create=self._create)
        else:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return self.stream

    async def close(self):
        self.closed = True


class Transport(unittest.TestCase):
    def setUp(self):
        root = make_assets()
        self.addCleanup(shutil.rmtree, root, True)
        self.assets = p.load_assets(root)

    def stream(self, cfg, client):
        plan = p.build_plan(cfg, self.assets, projection(egress_decision=None), manifest())
        transport = p.OpenAIStreamTransport(cfg, plan.route, client_factory=lambda timeout: client)
        return plan, asyncio.run(collect(transport.stream(plan, timeout=30)))

    def test_responses_stream_yields_text_deltas_and_final_usage_then_closes(self):
        usage = SimpleNamespace(input_tokens=900, output_tokens=120, input_tokens_details=SimpleNamespace(cached_tokens=100),
                                output_tokens_details=SimpleNamespace(reasoning_tokens=20))
        events = [SimpleNamespace(type="response.created"), SimpleNamespace(type="response.output_text.delta", delta="root = "),
                  SimpleNamespace(type="response.reasoning_summary_text.delta", delta="hidden"),
                  SimpleNamespace(type="response.output_text.delta", delta="RafiiRoot([])"),
                  SimpleNamespace(type="response.completed", response=SimpleNamespace(id="resp_1", usage=usage, incomplete_details=None))]
        client = FakeClient(events)
        plan, items = self.stream(make_cfg(), client)
        self.assertEqual(items[:2], [("delta", "root = "), ("delta", "RafiiRoot([])")])
        final = items[-1][1]
        self.assertEqual((final["status"], final["known"], final["inputTokens"], final["outputTokens"], final["cachedTokens"], final["reasoningTokens"],
                          final["requestId"]), ("ok", True, 900, 120, 100, 20, "resp_1"))
        self.assertEqual(client.kwargs, plan.responses_request())
        self.assertTrue(client.stream.closed and client.closed)

    def test_incomplete_and_missing_usage(self):
        usage = SimpleNamespace(input_tokens=900, output_tokens=16000, input_tokens_details=None, output_tokens_details=None)
        events = [SimpleNamespace(type="response.output_text.delta", delta="root = RafiiRoot(["),
                  SimpleNamespace(type="response.incomplete", response=SimpleNamespace(id="r", usage=usage, incomplete_details=SimpleNamespace(reason="max_output_tokens")))]
        _, items = self.stream(make_cfg(), FakeClient(events))
        self.assertEqual((items[-1][1]["status"], items[-1][1]["finishReason"]), ("incomplete", "max_output_tokens"))
        _, items = self.stream(make_cfg(), FakeClient([SimpleNamespace(type="response.output_text.delta", delta="x")]))
        self.assertEqual((items[-1][1]["status"], items[-1][1]["known"]), ("unknown", False), "a stream that ends without usage is unknown")

    def test_gateway_chat_stream_reads_the_final_usage_chunk(self):
        cfg = make_cfg(OPENAI_API_KEY=None, AI_GATEWAY_API_KEY="gw-test-not-real")
        chunks = [SimpleNamespace(id="c1", choices=[SimpleNamespace(delta=SimpleNamespace(content="root = "), finish_reason=None)], usage=None),
                  SimpleNamespace(id="c1", choices=[SimpleNamespace(delta=SimpleNamespace(content="RafiiRoot([])"), finish_reason="stop")], usage=None),
                  SimpleNamespace(id="c1", choices=[], usage=SimpleNamespace(prompt_tokens=700, completion_tokens=40, prompt_tokens_details=None,
                                                                              completion_tokens_details=None))]
        client = FakeClient(chunks, kind="chat")
        plan, items = self.stream(cfg, client)
        self.assertEqual(plan.route.model, "openai/gpt-6-luna")
        self.assertEqual([i for i in items if i[0] == "delta"], [("delta", "root = "), ("delta", "RafiiRoot([])")])
        self.assertEqual((items[-1][1]["inputTokens"], items[-1][1]["outputTokens"], items[-1][1]["known"]), (700, 40, True))
        self.assertEqual(client.kwargs, plan.chat_request())
        self.assertNotIn("tools", client.kwargs)

    def test_presenter_client_has_no_hidden_retries(self):
        created = {}

        class AsyncOpenAI:
            def __init__(self, **kwargs):
                created.update(kwargs)
        fake = types.ModuleType("openai")
        fake.AsyncOpenAI = AsyncOpenAI
        cfg = make_cfg()
        plan = p.build_plan(cfg, self.assets, projection(), manifest())
        with mock.patch.dict(sys.modules, {"openai": fake}):
            p.OpenAIStreamTransport(cfg, plan.route).make_client(42.0)
        self.assertEqual(created["max_retries"], 0)
        self.assertEqual(created["timeout"], 42.0)
        self.assertEqual(created["base_url"], cfg.base_url)


if __name__ == "__main__":
    unittest.main()
