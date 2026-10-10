"""Agent capability registry (rafii-agent-authz/1, CF-1): golden tests for "no behaviour change".

Three kinds of check:
1. Today's behaviour, read from the live code WITHOUT the registry (tool specs, the SDK bindings the Manager and specialists
   get, the grounded site agent's catalog, the GenUI bindings and their throttles) equals the frozen fixture
   `tests/fixtures/agent_permissions/capability_golden_v1.json`. A change to any tool's effect, role, approval,
   confirmation, scope or limit fails here first.
2. The registry reports exactly that behaviour (per capability and per surface binding, correction 6), and its own policy
   (risk, category, cost, data grants, retry, ...) equals the fixture, so no capability vanishes, appears or changes class
   silently. LEGACY_BASELINE_V1 equals `legacy_baseline_v1.json`.
3. Nothing is dispatchable without a declared registry entry, lint is clean, INV-6/INV-9/INV-10 hold, and the public
   catalogue carries en + zh-Hant titles and no internal scope names.

All in-process and deterministic: no database, network or model.
"""
import json
from collections import Counter
from dataclasses import replace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2.agent_runtime_v2 import capability_registry as registry, contracts, domain_tools, manager, specialists, tool_adapter  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "agent_permissions"
GOLDEN = FIXTURES / "capability_golden_v1.json"
BASELINE = FIXTURES / "legacy_baseline_v1.json"

try:
    import agents  # noqa: F401
    HAVE_SDK = True
except ImportError:  # the SDK is pinned in requirements.txt; CI always has it
    HAVE_SDK = False


def _sources():
    registry.ensure()          # imports every registering module exactly as a runtime turn does
    from postriff_phase2.agent_runtime_v2 import commands, ui_actions, ui_domain, ui_queries
    from postriff_phase2.site_agent import tools as site_tools
    return commands, site_tools, ui_actions, ui_domain, ui_queries


def live_snapshot() -> dict:
    """Today's behaviour, read from the code paths themselves (never from capability_registry)."""
    commands, site_tools, ui_actions, ui_domain, ui_queries = _sources()
    tools = {name: {"effect": t.spec.effect, "permission": t.spec.permission, "approval": t.spec.approval, "voice": t.spec.voice,
                    "idempotent": t.spec.idempotent, "audit": t.spec.audit, "tenant": t.spec.tenant}
             for name, t in sorted(tool_adapter.REGISTRY.items())}
    manager_names = specialists.available(manager.MANAGER_TOOLS + specialists.EXTRA_SCOPES.get("rafii_manager", []) + ["library_browse"])
    specialist_names = {key: sorted(specialists.available(list(spec["tools"]) + specialists.EXTRA_SCOPES.get(key, [])))
                        for key, spec in sorted(specialists.SPECIALISTS.items())}
    import inspect
    import re
    direct = sorted(set(re.findall(r'REGISTRY\["([a-z][a-z0-9_]*)"\]', inspect.getsource(commands))))
    site = {tool_id: {"effect": d["effect"], "requirement": site_tools.REQUIREMENT.get(tool_id, "read"), "adaptedAs": tool_adapter.site_tool_name(tool_id)}
            for tool_id, d in sorted(site_tools.CATALOG.items())}
    actions = {aid: {"journey": b.journey, "effect": b.effect, "requirement": b.requirement, "requiresConfirmation": b.requires_confirmation,
                     "prepareOnly": b.prepare_only, "twoPhase": b.two_phase, "dedupe": b.dedupe, "tool": b.tool, "scope": b.scope}
               for aid, b in sorted(ui_domain.ACTIONS.items())}
    queries = {name: {"journey": b.journey, "scope": b.scope, "requirement": b.requirement, "tool": b.tool, "refresh": b.refresh, "page": b.page}
               for name, b in sorted(ui_domain.QUERIES.items())}
    return {"tools": tools, "manager": sorted(manager_names), "specialists": specialist_names, "commandsDirect": direct, "siteAgent": site,
            "genuiActions": actions, "genuiQueries": queries,
            "limits": {"siteToolsPerTurn": site_tools.MAX_TOOLS_PER_TURN, "genuiActivationsPerMinute": ui_actions.ACTIVATIONS_PER_MINUTE,
                       "genuiQueriesPerMinute": ui_queries.QUERY_LIMIT_PER_MINUTE, "maxToolOutput": tool_adapter.MAX_TOOL_OUTPUT}}


def live_confirmation(surface: str, ref: str, snapshot: dict) -> str:
    """What the surface asks today, from the live snapshot (correction 6 table, CF-1 §6)."""
    if surface in ("manager", "specialist", "commands_direct"):
        return "proposal" if snapshot["tools"][ref]["approval"] else "none"
    if surface == "site_agent":
        if ref in registry.SITE_PROPOSALS:
            return "proposal"
        return "proposal" if snapshot["siteAgent"][ref]["effect"] == "workspace_mutation" else "none"
    if surface == "genui_action":
        action = snapshot["genuiActions"][ref]
        return "proposal" if action["prepareOnly"] else ("native" if action["requiresConfirmation"] else "none")
    return "none"


_POLICY = ("kind", "version", "category", "risk", "confirmation", "permission", "tenant", "effect", "approval", "cost", "paid", "consents",
           "timeout_seconds", "idempotency", "retry_class", "max_attempts", "background_eligible", "evidence", "verification", "compensation",
           "inverse", "autopilot_eligible", "explicit_request", "client_requirement", "since", "route_id", "feature_flag", "reauth_seconds",
           "auth_state", "resource_scope", "audit", "voice", "idempotent")


def registry_snapshot() -> dict:
    caps = registry.ensure()
    out = {}
    for capability_id, cap in sorted(caps.items()):
        entry = {key: getattr(cap, key) for key in _POLICY}
        entry["consents"] = list(cap.consents)
        entry["data_grants"] = None if cap.data_grants is None else list(cap.data_grants)
        entry["provider_scopes"] = [{"provider": s.provider, "scopes": list(s.scopes), "lane": s.lane, "capability": s.capability} for s in cap.provider_scopes]
        entry["limits"] = cap.limits.public()
        out[capability_id] = entry
    bindings = [{"surface": b.surface, "binding": b.binding_ref, "capabilityId": b.capability_id, "legacyConfirmation": b.legacy_confirmation,
                 "legacyLimits": b.legacy_limits.public(), "legacyTimeoutSeconds": b.legacy_timeout_seconds} for b in registry.bindings()]
    return {"capabilities": out, "bindings": bindings}


def golden_document() -> dict:
    """The fixture's full content (regenerate only for an intended, reviewed change of behaviour or policy)."""
    snapshot = registry_snapshot()
    return {"contract": registry.CONTRACT, "catalogueGeneration": contracts.CATALOGUE_GENERATION, "base": "origin/consumer-saas de4e5907",
            "note": "Today's behaviour (live) and the registry's view of it. Regenerate only for an intended, reviewed change.",
            "counts": {"registryTools": len(tool_adapter.REGISTRY), "capabilities": len(snapshot["capabilities"]), "bindings": len(snapshot["bindings"])},
            "live": live_snapshot(), **snapshot}


class Fixtures(unittest.TestCase):
    """(1) and (2): live behaviour and the registry both equal the frozen fixture."""

    @classmethod
    def setUpClass(cls):
        domain_tools.ensure_registered()
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.live = live_snapshot()

    def test_todays_behaviour_is_unchanged(self):
        for key in ("tools", "manager", "specialists", "commandsDirect", "siteAgent", "genuiActions", "genuiQueries", "limits"):
            actual = self.live[key]
            if key == "tools":
                actual = {name: value for name, value in actual.items() if name != "library_browse"}
            elif key == "manager":
                actual = [name for name in actual if name != "library_browse"]
            self.assertEqual(actual, self.golden["live"][key], f"today's {key} changed")
        self.assertEqual(len(tool_adapter.REGISTRY), self.golden["counts"]["registryTools"] + 1, "only the declared post-freeze Library tool was added")

    def test_registry_policy_is_frozen(self):
        snapshot = registry_snapshot()
        self.assertEqual(snapshot["capabilities"].pop("tool.library_browse")["since"], 2)
        snapshot["bindings"] = [b for b in snapshot["bindings"] if b["capabilityId"] != "tool.library_browse"]
        self.assertEqual(sorted(snapshot["capabilities"]), sorted(self.golden["capabilities"]), "no capability vanishes or appears")
        for capability_id, entry in snapshot["capabilities"].items():
            expected = self.golden["capabilities"][capability_id]
            if capability_id == "tool.draft_edit":
                # CF3 adds the atomic receipt and conditional revision restore; legacy authority stays frozen.
                expected = {**expected, "version": 2, "idempotency": "receipt_tx", "retry_class": "auto", "max_attempts": 3,
                            "compensation": "inverse", "inverse": "tool.draft_edit"}
            self.assertEqual(entry, expected, capability_id)
        self.assertEqual(snapshot["bindings"], self.golden["bindings"])

    def test_legacy_baseline_v1_is_frozen(self):
        frozen = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(sorted(registry.legacy_baseline_v1()), frozen["capabilities"])
        caps = registry.ensure()
        self.assertTrue(all(caps[c].since == 1 for c in frozen["capabilities"]))
        self.assertFalse(any(caps[c].kind == "native_only" for c in frozen["capabilities"]))
        expected = {c for c, cap in caps.items() if cap.tenant == "workspace" and cap.since == 1 and cap.kind != "native_only"}
        self.assertEqual(set(frozen["capabilities"]), expected, "every consumer kind is frozen; founder bypass is separate")
        self.assertEqual(dict(Counter(caps[c].kind for c in expected)), frozen["countsByKind"])
        self.assertEqual(frozen["countsByKind"], {"tool": 97, "ui_action": 12, "ui_query": 16, "context": 5})
        self.assertEqual(set(registry.CONTEXT_CAPABILITIES), {"context.page_summary", "context.screen_outline", "context.memory_layers",
                                                            "context.attention", "context.connections"})
        self.assertLessEqual(set(registry.CONTEXT_CAPABILITIES), expected)
        # All 17 actions and 45 queries resolve: seven founder queries bypass consumer grants rather than entering the baseline.
        self.assertEqual(len(self.live["genuiActions"]), 17)
        self.assertEqual(len(self.live["genuiQueries"]), 45)
        for cap in [registry.for_action(a) for a in self.live["genuiActions"]] + [registry.for_query(q) for q in self.live["genuiQueries"]]:
            self.assertEqual(cap.capability_id in expected, cap.tenant == "workspace", cap.capability_id)
        self.assertEqual(len(self.live["siteAgent"]), 37)
        for tool_id in self.live["siteAgent"]:
            self.assertIn(registry.site_capability(tool_id), expected)
        sdk_names = set(self.live["manager"]) | {n for names in self.live["specialists"].values() for n in names}
        self.assertLessEqual({registry.for_tool(n).capability_id for n in sdk_names if n != "library_browse"}, expected)

    def test_post_freeze_tool_never_joins_legacy(self):
        # #152 registers this shape only when it is integrated; the explicit since-2 declaration is mandatory.
        spec = contracts.ToolSpec("library_browse", contracts.READ, "read", "Library metadata", voice=False,
                                  data_grants=("library",), since=2)
        original = tool_adapter.REGISTRY.get(spec.name)
        tool_adapter.REGISTRY[spec.name] = tool_adapter.Tool(spec, {}, lambda ctx, args: {}, "Browse Library")
        try:
            self.assertEqual(registry.for_tool(spec.name).since, 2)
            self.assertNotIn("tool.library_browse", registry.legacy_baseline_v1())
        finally:
            if original is None:
                tool_adapter.REGISTRY.pop(spec.name, None)
            else:
                tool_adapter.REGISTRY[spec.name] = original


class RegistryMatchesToday(unittest.TestCase):
    """(2) per capability and per surface: the registry never misreports today's effect, role, confirmation or limits."""

    @classmethod
    def setUpClass(cls):
        cls.live = live_snapshot()
        cls.caps = registry.ensure()

    def test_every_tool_capability_mirrors_its_spec(self):
        for name, spec in self.live["tools"].items():
            cap = registry.for_tool(name)
            self.assertEqual(cap.capability_id, f"tool.{name}")
            for key in ("effect", "permission", "approval", "voice", "idempotent", "audit", "tenant"):
                self.assertEqual(getattr(cap, key), spec[key], f"{name}.{key}")
            self.assertEqual(cap.input_schema, tool_adapter.REGISTRY[name].schema)

    def test_surface_reach_is_todays(self):
        self.assertEqual(sorted(b.binding_ref for b in registry.bindings() if b.surface == "manager"), self.live["manager"])
        union = sorted({n for names in self.live["specialists"].values() for n in names})
        self.assertEqual(sorted(b.binding_ref for b in registry.bindings() if b.surface == "specialist"), union)
        self.assertEqual(sorted(b.binding_ref for b in registry.bindings() if b.surface == "commands_direct"), self.live["commandsDirect"])
        site = sorted(b.binding_ref for b in registry.bindings() if b.surface == "site_agent")
        self.assertEqual(site, sorted(list(self.live["siteAgent"]) + list(registry.SITE_PROPOSALS)))
        self.assertEqual(sorted(b.binding_ref for b in registry.bindings() if b.surface == "genui_action"), sorted(self.live["genuiActions"]))
        self.assertEqual(sorted(b.binding_ref for b in registry.bindings() if b.surface == "genui_query"), sorted(self.live["genuiQueries"]))
        self.assertEqual(registry.reach("manager"), frozenset(f"tool.{n}" for n in self.live["manager"]))

    def test_legacy_confirmation_per_surface(self):
        """Correction 6: the same capability asks differently on different surfaces, exactly as today."""
        for b in registry.bindings():
            self.assertEqual(b.legacy_confirmation, live_confirmation(b.surface, b.binding_ref, self.live), f"{b.surface}:{b.binding_ref}")
        self.assertEqual(registry.surface("manager", "draft_edit").legacy_confirmation, "none")
        self.assertEqual(registry.surface("genui_action", "draft_edit").legacy_confirmation, "native")
        self.assertEqual(registry.surface("genui_action", "draft_edit").capability_id, registry.surface("manager", "draft_edit").capability_id)
        self.assertEqual(registry.surface("genui_action", "schedule_prepare").legacy_confirmation, "proposal")
        self.assertEqual(registry.surface("genui_action", "campaign_link").legacy_confirmation, "none")
        self.assertEqual(registry.surface("site_agent", "automation.patch_propose").capability_id, "site.automation_patch_propose")

    def test_legacy_confirmation_is_exact_for_every_baseline_surface(self):
        baseline = registry.legacy_baseline_v1()
        seen = set()
        for binding in registry.bindings():
            if binding.capability_id not in baseline:
                continue
            expected = live_confirmation(binding.surface, binding.binding_ref, self.live)
            cap = registry.get(binding.capability_id)
            self.assertEqual(binding.required(cap.confirmation), expected, f"{binding.surface}:{binding.binding_ref}")
            seen.add(binding.surface)
        self.assertEqual(seen, set(contracts.SURFACES))

    def test_site_id_rule_and_exact_executor_are_frozen(self):
        _commands, site_tools, _a, _u, _q = _sources()
        adapted = []
        for tool_id in site_tools.CATALOG:
            cap_id = registry.site_capability(tool_id)
            self.assertEqual(cap_id, registry.surface("site_agent", tool_id).capability_id)
            self.assertEqual(cap_id, registry.for_tool(tool_id).capability_id)
            if cap_id.startswith("tool."):
                adapted.append(tool_id)
                self.assertEqual(cap_id, "tool." + tool_id.replace(".", "_"))
        self.assertEqual(len(adapted), 36)
        self.assertEqual(registry.site_capability("automation.patch_propose"), "site.automation_patch_propose")
        with self.assertRaises(LookupError):
            registry.site_capability("not.a_site_tool")

    def test_role_requirement_per_surface(self):
        for tool_id, site in self.live["siteAgent"].items():
            self.assertEqual(registry.for_tool(tool_id).permission, site["requirement"], tool_id)
        for action_id, action in self.live["genuiActions"].items():
            self.assertEqual(registry.for_action(action_id).permission, action["requirement"], action_id)
            self.assertEqual(registry.for_action(action_id).effect, action["effect"], action_id)
        for name, query in self.live["genuiQueries"].items():
            self.assertEqual(registry.for_query(name).permission, query["requirement"], name)
            self.assertEqual(registry.for_query(name).tenant, "founder" if query["scope"] == "founder" else "workspace", name)

    def test_limits_are_the_surfaces_own(self):
        limits = self.live["limits"]
        for b in registry.bindings():
            expected = {"site_agent": {"perTurn": limits["siteToolsPerTurn"]} if b.binding_ref in self.live["siteAgent"] else {},
                        "genui_action": {"perMinute": limits["genuiActivationsPerMinute"]},
                        "genui_query": {"perMinute": limits["genuiQueriesPerMinute"]}}.get(b.surface, {})
            self.assertEqual({k: v for k, v in b.legacy_limits.public().items() if v is not None}, expected, f"{b.surface}:{b.binding_ref}")
        self.assertTrue(all(cap.limits == contracts.Limits() for cap in self.caps.values()), "no per-capability limit exists yet")

    @unittest.skipUnless(HAVE_SDK, "openai-agents is pinned in requirements.txt")
    def test_sdk_bindings_read_the_registry_timeout(self):
        names = specialists.available(manager.MANAGER_TOOLS + specialists.EXTRA_SCOPES.get("rafii_manager", []))
        names += [n for key, spec in specialists.SPECIALISTS.items() for n in specialists.available(list(spec["tools"]) + specialists.EXTRA_SCOPES.get(key, []))]
        for function_tool in tool_adapter.sdk_tools(list(dict.fromkeys(names))):
            self.assertEqual(function_tool.timeout_seconds, 150.0, function_tool.name)
            self.assertEqual(function_tool.timeout_seconds, registry.for_tool(function_tool.name).timeout_seconds)
            binding = registry.surface("manager" if function_tool.name in self.live["manager"] else "specialist", function_tool.name)
            self.assertEqual(binding.legacy_timeout_seconds, 150.0)
            self.assertEqual(callable(function_tool.needs_approval), function_tool.name == "proposal_apply", function_tool.name)


class NoUndeclaredDispatch(unittest.TestCase):
    """(3) a test fails if anything is dispatchable without a declared registry entry."""

    def test_lint_is_clean(self):
        self.assertEqual(registry.lint(), [])

    def test_every_dispatchable_resolves_to_a_declared_entry(self):
        _commands, site_tools, _a, ui_domain, _q = _sources()
        for name in tool_adapter.REGISTRY:
            cap = registry.for_tool(name)
            self.assertIn("data_grants", cap.declared, f"{name} is dispatchable without a declaration")
        for tool_id in site_tools.CATALOG:
            self.assertIsNotNone(registry.for_tool(tool_id))
        for action_id in ui_domain.ACTIONS:
            self.assertIn("data_grants", registry.for_action(action_id).declared, action_id)
        for name in ui_domain.QUERIES:
            self.assertIn("data_grants", registry.for_query(name).declared, name)
        for capability_id in registry.CONTEXT_CAPABILITIES:
            self.assertEqual(registry.surface("context", capability_id).capability_id, capability_id)

    def test_an_undeclared_tool_fails_lint(self):
        spec = contracts.ToolSpec("capability_probe_undeclared", contracts.CREATE_DRAFT, "edit", "probe")
        tool_adapter.REGISTRY[spec.name] = tool_adapter.Tool(spec, {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                                                            lambda ctx, args: {"ok": True}, "probe")
        try:
            problems = registry.lint()
            self.assertTrue(any("capability_probe_undeclared: dispatchable but undeclared" in p for p in problems), problems)
            self.assertTrue(any("capability_probe_undeclared: workspace tool without data_grants" in p for p in problems), problems)
            self.assertTrue(any("capability_probe_undeclared: non-READ capability must declare" in p for p in problems), problems)
        finally:
            tool_adapter.REGISTRY.pop(spec.name, None)
        self.assertEqual(registry.lint(), [])

    def test_wrong_site_executor_is_not_mistaken_for_an_adapter(self):
        registry.ensure()
        original = tool_adapter.REGISTRY["help_search"]
        for executor in (lambda ctx, args: {}, tool_adapter._site_executor("help.get")):
            tool_adapter.REGISTRY["help_search"] = replace(original, executor=executor)
            try:
                self.assertTrue(any("help.search: adapter does not run" in p for p in registry.lint()))
            finally:
                tool_adapter.REGISTRY["help_search"] = original
        self.assertEqual(registry.lint(), [])

    def test_unknown_ids_fail_closed(self):
        self.assertIsNone(registry.get("tool.no_such_tool"))
        for call in (lambda: registry.for_tool("no_such_tool"), lambda: registry.for_action("no_such_action"),
                     lambda: registry.for_query("no_such_query"), lambda: registry.surface("manager", "no_such_tool"),
                     lambda: registry.surface("genui_action", "draft_get"), lambda: registry.reach("no_such_surface")):
            with self.assertRaises(LookupError):
                call()


class Invariants(unittest.TestCase):

    def test_inv10_confirmation_never_drops(self):
        for b in registry.bindings():
            for decided in contracts.CONFIRMATIONS:
                required = b.required(decided)
                self.assertGreaterEqual(contracts.CONFIRMATIONS.index(required), contracts.CONFIRMATIONS.index(b.legacy_confirmation))
                self.assertGreaterEqual(contracts.CONFIRMATIONS.index(required), contracts.CONFIRMATIONS.index(decided))
        self.assertEqual(contracts.max_confirmation("native", "none"), "native")
        self.assertEqual(contracts.max_confirmation("proposal", "native"), "proposal")
        self.assertEqual(contracts.max_confirmation("none", "unknown"), "approval_step_up", "an unknown value fails closed")

    def test_manager_expansion_only_after_an_explicit_choice(self):
        class Grants:
            def __init__(self, source, baseline, preset):
                self.source, self.baseline, self.preset = source, baseline, preset
        today = registry.reach("manager")
        self.assertEqual(registry.reach("manager", None), today)
        self.assertEqual(registry.reach("manager", Grants("legacy", "legacy_v1", "legacy")), today)
        # correction 5: a legacy person's first revoke materializes LEGACY_EQUIVALENT, which keeps baseline 'legacy_v1'
        self.assertEqual(registry.reach("manager", Grants("explicit", "legacy_v1", "custom")), today)
        self.assertEqual(registry.reach("manager", Grants("explicit", None, "none")), today)
        for preset in ("recommended", "full", "custom"):
            self.assertEqual(registry.reach("manager", Grants("explicit", None, preset)), today | registry.MANAGER_EXPANSION_V1)
        for surface_name in contracts.SURFACES:
            self.assertEqual(registry.reach(surface_name, Grants("explicit", "legacy_v1", "custom")), registry.reach(surface_name),
                             f"revoke-from-legacy never widens {surface_name}")

    def test_inv9_new_fields_never_enter_the_tool_digest(self):
        from postriff_phase2 import skill_registry
        schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": [], "additionalProperties": False}
        plain = contracts.ToolSpec("digest_probe", contracts.READ, "read", "probe")
        rich = contracts.ToolSpec("digest_probe", contracts.READ, "read", "probe", category="read_analyze", data_grants=("content",), risk="R0",
                                  cost="free", limits=contracts.Limits(per_minute=5), timeout_seconds=20.0, background_eligible=True, since=2)
        digest = lambda spec: skill_registry.tool_digest("digest_probe", {"digest_probe": tool_adapter.Tool(spec, schema, lambda c, a: {}, "probe")})
        self.assertEqual(digest(plain), digest(rich))

    def test_inv6_genui_contract_unchanged(self):
        from postriff_phase2.agent_runtime_v2 import ui_contracts, ui_domain
        vectors = json.loads((ROOT / "tests" / "fixtures" / "agent_ui" / "contracts" / "vectors.json").read_text(encoding="utf-8"))
        self.assertEqual(ui_contracts.contract_hash(), vectors["contractHash"])
        for binding in ui_domain.ACTIONS.values():
            self.assertEqual(set(ui_domain.public_action(binding)), {"actionId", "label", "effect", "requiresConfirmation", "inputSchema", "summary"})
        for binding in ui_domain.QUERIES.values():
            self.assertEqual(set(ui_domain.public_query(binding)), {"name", "description", "argsSchema", "refreshMinSeconds", "pageSize", "dataShape"})

    def test_founder_tenant_isolation(self):
        for cap in registry.ensure().values():
            if cap.tenant == "founder":
                self.assertEqual(cap.auth_state, "founder_principal")
                self.assertNotIn(cap.capability_id, registry.reach("manager"))
                self.assertFalse(any(b.surface in ("manager", "specialist", "site_agent", "genui_action") for b in registry.bindings(cap.capability_id)))

    def test_r3_is_native_only(self):
        for cap in registry.ensure().values():
            if cap.risk == "R3":
                self.assertEqual(cap.kind, "native_only")
                self.assertEqual(cap.reauth_seconds, contracts.R3_REAUTH_SECONDS)
                self.assertEqual(cap.confirmation, "approval_step_up")
                self.assertEqual(registry.bindings(cap.capability_id), [], "nothing executes a native-only capability")
            else:
                self.assertNotIn(cap.effect, contracts.FORBIDDEN_EFFECTS)

    def test_consents_only_where_the_executor_refuses_first(self):
        for capability_id, cap in registry.ensure().items():
            self.assertLessEqual(set(cap.consents), set(registry.VERIFIED_CONSENT_PRECHECKS.get(capability_id, ())), capability_id)
        self.assertEqual(registry.for_tool("memory_context").consents, (), "memory_context filters; it never refuses")
        self.assertEqual(registry.for_tool("brand_summary").consents, (), "R0 filters memory; filtering never adds a consent-denial gate")
        self.assertEqual(registry.for_tool("image_generate").consents, (), "only reference images leave, so it never refuses up front")

    def test_youtube_provider_scope_matches_the_executor(self):
        from postriff_phase2.youtube import model
        scope = registry.for_tool("youtube_analytics_summary").provider_scopes
        self.assertEqual(scope, (contracts.ProviderScope("YouTube", (model.READ, model.ANALYTICS), lane="agentic", capability="analytics"),))
        self.assertTrue(registry.for_tool("youtube_analytics_summary").explicit_request)


class ToolSpecFields(unittest.TestCase):

    def test_positional_construction_and_defaults(self):
        spec = contracts.ToolSpec("probe_read", contracts.READ, "read", "A probe.", True, False, True, None, "workspace")
        self.assertEqual((spec.capability_id, spec.capability_version, spec.cost, spec.timeout_seconds, spec.since), (None, 1, "free", 150.0, 1))
        policy = contracts.derive_policy(spec)
        self.assertEqual((policy["capability_id"], policy["category"], policy["risk"], policy["confirmation"], policy["idempotency"],
                          policy["retry_class"], policy["max_attempts"], policy["evidence"]),
                         ("tool.probe_read", "read_analyze", "R0", "none", "read", "auto", 3, "trace"))

    def test_derivation_table(self):
        derive = lambda *a, **k: contracts.derive_policy(contracts.ToolSpec("p", *a, **k))
        write = derive(contracts.CREATE_DRAFT, "edit", "x")
        self.assertEqual((write["category"], write["risk"], write["idempotency"], write["retry_class"], write["max_attempts"], write["compensation"]),
                         ("create_edit", "R1", "none", "never", 1, "manual"))
        paid = derive(contracts.CREATE_DRAFT, "edit", "x", cost="text_credits", idempotency="native_key")
        self.assertEqual((paid["retry_class"], paid["max_attempts"], paid["paid"]), ("manual", 1, True))
        free = derive(contracts.MUTATE_REVERSIBLE, "edit", "x", idempotency="receipt_tx")
        self.assertEqual((free["retry_class"], free["max_attempts"]), ("auto", 3))
        prepare = derive(contracts.PREPARE_EXTERNAL, "approve", "x", approval=True)
        self.assertEqual((prepare["category"], prepare["risk"], prepare["confirmation"], prepare["idempotency"], prepare["retry_class"]),
                         ("execute_automations", "R2", "proposal", "native_key", "manual"))
        proposal = derive(contracts.MUTATE_REVERSIBLE, "edit", "x", approval=True)
        self.assertEqual(proposal["risk"], "R2")

    def test_invalid_values_and_combinations_are_refused(self):
        bad = [dict(risk="R3"), dict(category="nope"), dict(cost="gold"), dict(data_grants=("nope",)), dict(consents=("nope",)),
               dict(data_grants=["content"]), dict(risk="R2", confirmation="none"), dict(inverse="tool.x"), dict(autopilot_eligible=True),
               dict(background_eligible=True, effect=contracts.CREATE_DRAFT), dict(idempotency="none", retry_class="auto", effect=contracts.CREATE_DRAFT),
               dict(max_attempts=9), dict(timeout_seconds=151.0), dict(timeout_seconds=0)]
        for kwargs in bad:
            effect = kwargs.pop("effect", contracts.READ)
            with self.assertRaises(ValueError, msg=str(kwargs)):
                contracts.ToolSpec("probe", effect, "read", "x", **kwargs)
        with self.assertRaises(ValueError):
            contracts.Limits(per_minute=0)
        contracts.ToolSpec("probe", contracts.READ, "read", "x", background_eligible=True, data_grants=("public",))
        contracts.ToolSpec("probe", contracts.MUTATE_REVERSIBLE, "edit", "x", idempotency="receipt_tx", compensation="inverse", inverse="tool.other")

    def test_public_gains_the_capability_fields(self):
        view = tool_adapter.REGISTRY["image_generate"].spec.public()
        self.assertEqual({k: view[k] for k in ("capabilityId", "capabilityVersion", "category", "risk", "confirmation", "cost", "dataGrants")},
                         {"capabilityId": "tool.image_generate", "capabilityVersion": 1, "category": "create_edit", "risk": "R1", "confirmation": "none",
                          "cost": "media_credits", "dataGrants": ["content"]})


class PublicCatalogue(unittest.TestCase):
    """CF-1 §11: what the permissions UI (lane B1) reads."""

    @classmethod
    def setUpClass(cls):
        cls.entries = registry.public_catalogue()

    def test_one_entry_per_consumer_capability(self):
        consumer = sorted(c for c, cap in registry.ensure().items() if cap.tenant != "founder")
        self.assertEqual([e["capabilityId"] for e in self.entries], consumer)
        self.assertEqual(registry.catalogue_digest(), registry.catalogue_digest())
        json.dumps(self.entries)

    def test_human_titles_in_english_and_traditional_chinese(self):
        for entry in self.entries:
            title = entry["title"] or {}
            self.assertTrue(title.get("en", "").strip() and title.get("zh-Hant", "").strip(), entry["capabilityId"])
            self.assertNotIn("_", title["en"], entry["capabilityId"])
            self.assertTrue(any("一" <= ch <= "鿿" for ch in title["zh-Hant"]), entry["capabilityId"])
        youtube = next(e for e in self.entries if e["capabilityId"] == "tool.youtube_analytics_summary")
        self.assertTrue(youtube["providerScopes"][0]["title"]["zh-Hant"])

    def test_no_internal_scope_names_schemas_or_prompts(self):
        text = json.dumps(self.entries, ensure_ascii=False)
        for forbidden in ("googleapis", "https://", "auth/", "rafii_manager", "brand_intelligence", "publishing_ops", "workspace_history",
                          "inputSchema", "input_schema", "description", "executor", "agent_runtime_v2", "\"scopes\""):
            self.assertNotIn(forbidden, text)
        keys = {"capabilityId", "version", "kind", "category", "risk", "confirmation", "cost", "dataGrants", "consents", "providerScopes", "requirement",
                "surfaces", "legacyConfirmation", "nativeOnly", "routeId", "reauthSeconds", "baseline", "since", "explicitRequest", "titleKey", "title"}
        for entry in self.entries:
            self.assertEqual(set(entry), keys)
            for scope in entry["providerScopes"]:
                self.assertEqual(set(scope), {"provider", "title"})

    def test_per_surface_legacy_confirmation_is_published(self):
        draft_edit = next(e for e in self.entries if e["capabilityId"] == "tool.draft_edit")
        self.assertEqual(draft_edit["legacyConfirmation"], {"genui_action": "native", "manager": "none"})
        self.assertEqual(draft_edit["confirmation"], "none", "the policy floor is not the surface's confirmation")
        for entry in self.entries:
            self.assertEqual(sorted(entry["legacyConfirmation"]), entry["surfaces"])

    def test_native_only_routes_and_reauth(self):
        native = [e for e in self.entries if e["nativeOnly"]]
        self.assertEqual(len(native), len(registry.NATIVE_ONLY))
        web = json.loads((ROOT / "web" / "src" / "lib" / "site-agent" / "route-manifest.json").read_text(encoding="utf-8"))
        routes = {r["id"] for r in web["routes"]}
        for entry in native:
            self.assertIn(entry["routeId"], routes)
            self.assertEqual(entry["reauthSeconds"], 300)
            self.assertFalse(entry["baseline"])
            self.assertEqual(entry["surfaces"], [])


class RunContextSeams(unittest.TestCase):
    """X11: the CF-2/CF-3 context fields exist and default to today's behaviour."""

    def test_defaults_are_absent(self):
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        ctx = RafiiRunContext(service=None, workspace_id="w", token="t", principal="p", membership=None, conversation_id="c", trace_id="trace_" + "0" * 32)
        self.assertEqual((ctx.grants, ctx.active_capability, ctx.authz_actor, ctx.authz_evidence, ctx.authz_mode, ctx.step_binding),
                         (None, None, None, None, "off", None))
        self.assertIsNone(ctx.effect_key({"x": 1}))
        self.assertIsNone(ctx.for_agent("content").effect_key())

    def test_effect_key_format(self):
        task = "0f" * 16
        self.assertEqual(contracts.effect_key({"taskId": task, "stepKey": "s1", "generation": 2, "kind": "tool"}), f"tsk:{task}:s1:g2")
        inside = contracts.effect_key({"taskId": task, "stepKey": "s1", "generation": 2, "kind": "model"}, "tool.draft_edit", {"draftId": "d1"})
        self.assertRegex(inside, rf"^tsk:{task}:s1:g2:[0-9a-f]{{16}}$")
        self.assertEqual(inside, contracts.effect_key({"taskId": task, "stepKey": "s1", "generation": 2, "kind": "model"}, "tool.draft_edit", {"draftId": "d1"}))
        self.assertNotEqual(inside, contracts.effect_key({"taskId": task, "stepKey": "s1", "generation": 2, "kind": "model"}, "tool.draft_edit", {"draftId": "d2"}))
        with self.assertRaises(ValueError):
            contracts.effect_key({"taskId": "nope", "stepKey": "s1", "generation": 0})
        self.assertEqual(len(contracts.input_digest("tool.x", {"a": 1})), 64)


if __name__ == "__main__":
    unittest.main()
