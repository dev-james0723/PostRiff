"""Rafii agent permissions (rafii-agent-authz/1, CF-2): the pure decision, presets, the legacy baseline, the E1 tool gate in
off / shadow / enforce, step-up and the approval evidence rules. Deterministic; no database, no model, no network.

The store's SQL (receipts, grants, revoke, reminder, membership end, account-deletion erase, idempotency 409, two
workspaces) runs on a disposable PostgreSQL in tests/phase2/postgres_agent_permissions.py (CI only).
"""
import copy
import hashlib
import json
import logging
import re
import sys
import unittest
from types import SimpleNamespace
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError, initial_state  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402
from postriff_phase2.agent_runtime_v2 import (agent_error_codes, agent_permissions as ap, authz, config, contracts,  # noqa: E402
                                              context as rt_context, domain_tools, tool_adapter)
from postriff_phase2 import hosted_identity  # noqa: E402

domain_tools.ensure_registered()
NOW = 1_790_000_000.0
WS, OTHER_WS, ME = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "owner-1"
OWNER, EDITOR, VIEWER, APPROVER = (Membership.from_row(r) for r in ("owner", "editor", "viewer", "approver"))
# migrations/postriff/109_agent_permissions.sql must stay byte-identical to the frozen CF-2 proposal
# (docs/design/rafii-agent-os/migrations/109_agent_permissions.sql on the contracts branch, PR #160).
FROZEN_109_SHA256 = "927b88451d57b270a0d766f9626384a0e41dfe7b62f027de47710d32b24fee48"
# Capabilities added after the freeze (CF-1 §7: since > 1). They are never part of LEGACY_BASELINE_V1.
POST_FREEZE = {"tool.library_browse"}


def cap(name, **kw):
    """A capability built from a registered tool, with fields overridden for a scenario."""
    base = authz.capability_for(tool_adapter.REGISTRY[name].spec)
    values = {f: getattr(base, f) for f in authz.Capability.__dataclass_fields__}
    values.update(kw)
    return authz.Capability(**values)


def surface_of(c):
    return authz.Surface("manager", c.name, "proposal" if c.approval else "none")


def grants(preset="recommended", scopes=None, *, spend=None, epoch=1, **kw):
    if preset == "legacy":
        return ap.legacy(WS, ME, **kw)
    # Custom starts from Recommended, as the settings page does; overrides then narrow or change it.
    base = ap.preset_scopes(preset if preset in ap.PRESETS else "recommended")
    return ap.from_scopes(WS, ME, {**base, **(scopes or {})}, preset=preset, spend=spend or ap.PRESETS.get(preset, {}).get("spend_confirmation", "all"),
                          user_epoch=epoch, **kw)


def decide(c, g, *, member=OWNER, actor=None, state=None, view=None, target=None, now=NOW, surface=None):
    return authz.decide(c, surface=surface or surface_of(c), member=member, grants=g, state=state or {}, actor=actor or authz.Actor("agent", ME, "hi"),
                        provider_view=view, target=target, now=now)


class ModeConfigTest(unittest.TestCase):
    def test_dark_by_default_and_fail_closed_activation(self):
        self.assertEqual(config.RuntimeConfig.from_environment({}).permissions_for(WS), "off")
        env = {"RAFII_AGENT_PERMISSIONS_ENABLED": "1", "RAFII_AGENT_PERMISSIONS_WORKSPACES": WS.upper()}
        cfg = config.RuntimeConfig.from_environment(env)
        self.assertEqual((cfg.permissions_for(WS), cfg.permissions_for(OTHER_WS)), ("shadow", "off"))
        self.assertEqual(config.RuntimeConfig.from_environment({"RAFII_AGENT_PERMISSIONS_ENABLED": "1"}).permissions_for(WS), "off")
        cfg = config.RuntimeConfig.from_environment({**env, "RAFII_AGENT_PERMISSIONS_ENFORCED": "1"})
        self.assertEqual(cfg.permissions_for(WS), "shadow", "task engine missing")
        cfg.task_engine_for = lambda ws: "on"
        self.assertEqual(cfg.permissions_for(WS), "shadow", "enforcement adapters incomplete")
        with mock.patch.object(authz, "ENFORCEMENT_POINTS", set(authz.REQUIRED_ENFORCEMENT_POINTS)):
            self.assertEqual(cfg.permissions_for(WS), "enforce")
            cfg.flags["RAFII_GENUI_ENABLED"] = True
            self.assertEqual(cfg.permissions_for(WS), "shadow", "no verified current-release receipt provider")
            cfg.release_sha = "a" * 40
            cfg.permissions_gate_reader = lambda workspace, sha: workspace == WS and sha == "a" * 40
            self.assertEqual(cfg.permissions_for(WS), "enforce")
            cfg.release_sha = "b" * 40
            self.assertEqual(cfg.permissions_for(WS), "shadow", "a stale receipt cannot authorize another release")

    def test_task_engine_canonical_switches_are_fail_closed(self):
        flags = {"RAFII_AGENT_V2_ENABLED": "1", "RAFII_TASK_ENGINE_ENABLED": "1", "RAFII_TASK_ENGINE_WORKSPACES": WS}
        self.assertEqual(config.RuntimeConfig.from_environment(flags).task_engine_for(WS), "shadow")
        cfg = config.RuntimeConfig.from_environment({**flags, "RAFII_TASK_ENGINE_AUTHORITATIVE": "1"})
        self.assertEqual((cfg.task_engine_for(WS), cfg.task_engine_for(OTHER_WS)), ("on", "off"))
        self.assertFalse(cfg.task_engine_background_for(WS))
        for off in ({}, {"RAFII_AGENT_TASKS_ENABLED": "1", "RAFII_AGENT_TASKS_AUTHORITATIVE": "1"},
                    {**flags, "RAFII_AGENT_V2_ENABLED": "0"}, {**flags, "RAFII_TASK_ENGINE_WORKSPACES": ""}):
            self.assertEqual(config.RuntimeConfig.from_environment(off).task_engine_for(WS), "off")

    def test_permissions_do_not_change_genui_contract_flags(self):
        from postriff_phase2.agent_runtime_v2 import ui_contracts
        self.assertFalse(set(ui_contracts.FLAGS) & {"RAFII_AGENT_PERMISSIONS_ENABLED", "RAFII_AGENT_PERMISSIONS_ENFORCED"})
        self.assertEqual(authz.mode_for(object(), WS), "off")


class BaselineTest(unittest.TestCase):
    def test_frozen_baseline_is_everything_reachable_at_the_freeze(self):
        frozen = set(authz.LEGACY_BASELINE_V1)
        now = set(authz.compute_baseline())
        self.assertEqual(now - frozen - POST_FREEZE, set(), "a capability joined without a classification (INV-3): add it with since > 1")
        self.assertEqual(frozen - now, set(), "a capability in the frozen baseline disappeared")
        self.assertFalse(POST_FREEZE & frozen)
        self.assertEqual(len([c for c in frozen if c.startswith("ui.action.") or (c.startswith("tool.") and c[5:] in ("draft_edit", "schedule_propose"))]) > 0, True)
        self.assertEqual(json.loads(authz.BASELINE_FILE.read_text())["catalogueGeneration"], authz.CATALOGUE_GENERATION)

    def test_legacy_confirmations_are_equal_on_every_registered_surface(self):
        legacy = grants("legacy")
        ended = ap.legacy(WS, ME, ended=True)
        equivalent = ap.from_scopes(WS, ME, ap.preset_scopes("legacy_equivalent"), preset="custom", baseline="legacy_v1", spend="none")
        for c in authz.catalogue():
            if c.capability_id not in authz.LEGACY_BASELINE_V1:
                continue
            for surface in authz.capability_surfaces(c):
                d = decide(c, legacy, surface=surface)
                self.assertEqual(d.required, surface.legacy_confirmation, (c.capability_id, surface.name))
                for g in (ended, equivalent):
                    other = decide(c, g, surface=surface)
                    self.assertEqual((other.outcome, other.required), (d.outcome, d.required), (c.capability_id, surface.name, g))
        late = cap("help_search", capability_id="tool.library_browse", since=2)
        self.assertEqual(decide(late, legacy).reason, "not_in_baseline")

    def test_legacy_role_rules_are_unchanged(self):
        for c in authz.catalogue():
            if c.kind == "native_only" or c.capability_id not in authz.LEGACY_BASELINE_V1:
                continue
            for surface in authz.capability_surfaces(c):
                result = decide(c, grants("legacy"), member=VIEWER, surface=surface)
                if not VIEWER.allows(c.permission):
                    self.assertEqual(result.reason, "role", c.capability_id)


class DecideTest(unittest.TestCase):
    def test_membership_role_and_unknown_inputs_fail_closed(self):
        c = cap("draft_edit")
        self.assertEqual(decide(c, grants(), member=None).reason, "membership_missing")
        self.assertEqual(decide(c, None).reason, "permissions_changed")
        # Role escalation: a viewer may save Full, but the role still clips every edit (decide step b).
        self.assertEqual(decide(c, grants("full"), member=VIEWER).reason, "role")
        self.assertEqual(decide(cap("schedule_propose"), grants("full"), member=EDITOR).reason, "role", "scheduling still needs the approve class")
        self.assertEqual(decide(cap("schedule_propose"), grants("full"), member=APPROVER).outcome, "allow")

    def test_ask_assist_and_categories(self):
        c = cap("draft_edit")
        self.assertEqual(decide(c, grants()).outcome, "allow")
        ask = grants("custom", {"category:create_edit": "ask"})
        d = decide(c, ask)
        self.assertEqual((d.outcome, d.reason, d.required), ("confirm", "needs_confirmation", "native"))
        self.assertEqual(decide(c, grants("custom", {"category:create_edit": "off"})).reason, "category_off")
        self.assertEqual(decide(c, grants("custom", {"capability:tool.draft_edit": "off"})).reason, "capability_off")
        only = ap.from_scopes(WS, ME, {"capability:tool.draft_edit": "assist", "domain:content": True}, preset="custom")
        self.assertEqual(decide(c, only).outcome, "allow", "one capability can be granted while its category is off")
        self.assertEqual(decide(c, ap.from_scopes(WS, ME, {"capability:tool.draft_edit": "assist"}, preset="custom")).reason, "domain_off")

    def test_r2_keeps_its_proposal_and_full_never_lowers_it(self):
        for preset in ("recommended", "full"):
            for name in ("schedule_propose", "automation_change_propose", "proposal_apply"):
                d = decide(cap(name), grants(preset))
                self.assertEqual(d.required, "proposal", (preset, name))
        # Recommended asks for automations; the proposal tool still only prepares a proposal a person applies.
        self.assertEqual(decide(cap("schedule_propose"), grants("recommended")).outcome, "allow")

    def test_r3_and_native_only(self):
        r3 = cap("draft_edit", risk="R3", confirmation="approval_step_up")
        d = decide(r3, grants("full"))
        self.assertEqual((d.outcome, d.reason, d.required), ("step_up", "needs_step_up", "approval_step_up"))
        fresh = authz.Actor("agent", ME, "", {"stepUp": {"at": NOW - 100}})
        stale = authz.Actor("agent", ME, "", {"stepUp": {"at": NOW - 301}})
        self.assertEqual(decide(r3, grants("full"), actor=fresh).outcome, "allow")
        self.assertEqual(decide(r3, grants("full"), actor=stale).outcome, "step_up")
        native = cap("help_search", kind="native_only", risk="R3", confirmation="approval_step_up")
        self.assertEqual(decide(native, grants("full"), actor=fresh).reason, "native_only")

    def test_spend_floor_and_credit_quote(self):
        c = cap("draft_create")
        self.assertEqual(c.cost, "text_credits")
        self.assertEqual(decide(c, grants("recommended")).outcome, "confirm")
        self.assertEqual(decide(c, grants("full")).outcome, "allow")
        self.assertEqual(decide(c, grants("custom", spend="media")).outcome, "allow")
        self.assertEqual(decide(cap("image_generate"), grants("custom", spend="media")).outcome, "confirm")
        quote = {"requestDigest": "d" * 64, "expiresAt": NOW + 60}
        ok = authz.Actor("agent", ME, "", {"creditQuote": quote, "requestDigest": "d" * 64})
        self.assertEqual(decide(c, grants("recommended"), actor=ok).outcome, "allow", "a credit quote for the same request is the spend confirmation")
        for bad in ({**quote, "expiresAt": NOW - 1}, {**quote, "used": True}, {**quote, "requestDigest": "e" * 64}):
            self.assertEqual(decide(c, grants("recommended"), actor=authz.Actor("agent", ME, "", {"creditQuote": bad, "requestDigest": "d" * 64})).outcome, "confirm")
        # A credit quote never stands in for an Ask confirmation.
        ask = grants("custom", {"category:create_edit": "ask"})
        self.assertEqual(decide(c, ask, actor=ok).outcome, "confirm")

    def test_new_capabilities_ask_once_and_ceilings_narrow(self):
        late = cap("draft_edit", since=authz.CATALOGUE_GENERATION + 1)
        self.assertEqual(decide(late, grants("full")).required, "native")
        self.assertEqual(decide(cap("help_search", since=authz.CATALOGUE_GENERATION + 1), grants("full")).outcome, "allow", "R0 is not floored")
        c = cap("draft_edit")
        self.assertEqual(decide(c, grants("full", ceiling={"create_edit": "off"})).reason, "workspace_ceiling")
        self.assertEqual(decide(c, grants("full", ceiling={"create_edit": "ask"})).outcome, "confirm")
        self.assertEqual(decide(c, grants("legacy", ceiling={"create_edit": "off"})).reason, "workspace_ceiling", "a ceiling also narrows legacy people")

    def test_workspace_consent_readers(self):
        c = cap("memory_context", consents=("memory_cloud",))
        self.assertEqual(decide(c, grants(), state={}).reason, "workspace_consent")
        state = initial_state("ws")
        state["memoryEgress"] = {"cloud": True}
        from postriff_phase2 import memory
        if memory.egress(state).get("cloud") is True:
            self.assertEqual(decide(c, grants(), state=state).outcome, "allow")
        self.assertEqual(decide(cap("memory_context", consents=("no_such_reader",)), grants()).reason, "workspace_consent", "an unknown consent denies")

    def test_provider_grants(self):
        scope = authz.ProviderScope("YouTube", ("analytics",), lane="agentic")
        c = cap("youtube_analytics_summary", provider_scopes=(scope,))
        view = lambda **ch: authz.ProviderView(({"id": "yt", "platform": "YouTube", "connectionState": "read_verified", "scopes": ["analytics"],
                                                 "capabilities": {}, "authorizationLane": "agentic", **ch},))
        self.assertEqual(decide(c, grants(), view=authz.ProviderView()).reason, "provider_not_connected")
        self.assertEqual(decide(c, grants(), view=None).reason, "provider_not_connected")
        self.assertEqual(decide(c, grants(), view=view(connectionState="token_expired")).reason, "provider_reauth_required")
        self.assertEqual(decide(c, grants(), view=view(scopes=[])).reason, "provider_scope_missing")
        self.assertEqual(decide(c, grants(), view=view(authorizationLane="standard")).reason, "provider_lane_mismatch")
        self.assertEqual(decide(c, grants(), view=view()).outcome, "allow")
        self.assertEqual(decide(c, grants(), view=view(), target={"channelId": "someone-else"}).reason, "provider_not_connected")
        unsupported = cap("youtube_analytics_summary", provider_scopes=(authz.ProviderScope("YouTube", (), capability="analytics"),))
        self.assertEqual(decide(unsupported, grants(), view=view(capabilities={"analytics": {"level": "Unsupported"}})).reason, "provider_capability_unsupported")

    def test_explicit_request_counts_only_the_current_human_message(self):
        c = cap("youtube_plan_context", explicit_request=True)
        self.assertEqual(decide(c, grants()).reason, "explicit_request_required", "no matcher: denied")
        with mock.patch.dict(authz.EXPLICIT_REQUEST, {c.capability_id: lambda text: "youtube" in text.lower()}):
            self.assertEqual(decide(c, grants(), actor=authz.Actor("agent", ME, "Plan my YouTube week")).outcome, "allow")
            for resumed in ("", "(approved)"):   # cron, continuation, resume after approval
                self.assertEqual(decide(c, grants(), actor=authz.Actor("agent", ME, resumed)).reason, "explicit_request_required")

    def test_founder_tenant_bypasses_consumer_grants(self):
        self.assertEqual(decide(cap("help_search", tenant="founder"), grants("none")).reason, "founder_tenant")

    def test_confirmation_never_drops_below_the_surface(self):
        """INV-10 / A1: for every tool, every preset and a narrowed Custom, required >= the surface's legacy confirmation."""
        rank = authz.CONFIRMATIONS.index
        presets = [grants("legacy"), grants("none"), grants("recommended"), grants("full"),
                   grants("custom", {"category:create_edit": "ask", "domain:analytics": False})]
        for c in authz.catalogue():
            for surface in (surface_of(c), authz.Surface("genui_action", c.name, "native"), authz.Surface("site_agent", c.name, "proposal")):
                for g in presets:
                    d = decide(c, g, surface=surface)
                    if d.outcome != "deny":
                        self.assertGreaterEqual(rank(d.required), rank(surface.legacy_confirmation), (c.capability_id, surface.name, g.preset))


class ApprovalEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.cap = cap("draft_edit", risk="R1")
        self.ask = grants("custom", {"category:create_edit": "ask"})
        self.record = {"state": "approved", "consumedAt": None, "capabilityId": "tool.draft_edit", "digest": "a" * 64, "requestedFor": ME, "expiresAt": NOW + 600}

    def actor(self, record, digest="a" * 64, principal=ME):
        return authz.Actor("approval", principal, "", {"approval": record, "digest": digest})

    def test_a_valid_approval_allows_exactly_once(self):
        self.assertEqual(decide(self.cap, self.ask, actor=self.actor(self.record)).outcome, "allow")

    def test_replayed_expired_drifted_or_foreign_approvals_are_refused(self):
        refused = {
            "replayed": self.actor({**self.record, "state": "consumed", "consumedAt": NOW - 5}),
            "consumed_flag": self.actor({**self.record, "consumedAt": NOW - 5}),
            "expired": self.actor({**self.record, "expiresAt": NOW - 1}),
            "rejected": self.actor({**self.record, "state": "rejected"}),
            "revoked": self.actor({**self.record, "state": "revoked"}),
            "digest_drift": self.actor(self.record, digest="b" * 64),
            "other_capability": self.actor({**self.record, "capabilityId": "tool.campaign_link"}),
            "other_person": self.actor(self.record, principal="someone-else"),
            "no_record": self.actor(None),
        }
        for name, actor in refused.items():
            self.assertEqual(decide(self.cap, self.ask, actor=actor).outcome, "confirm", name)

    def test_autopilot_is_bounded(self):
        eligible = cap("draft_edit", autopilot_eligible=True)
        policy = ap.AutopilotPolicy("p1", frozenset({"tool.draft_edit"}), {"campaignIds": ["c1"]}, {"actionsPerDay": 2}, {"actionsToday": 0}, NOW + 3600)
        g = grants("recommended", autopilot=(policy,))
        robot = authz.Actor("autopilot", ME)
        self.assertEqual(decide(eligible, g, actor=robot, target={"campaignId": "c1"}).policy_id, "p1")
        self.assertEqual(decide(eligible, g, actor=robot, target={"campaignId": "c2"}).reason, "autopilot_not_covered")
        self.assertEqual(decide(eligible, g, actor=robot).reason, "autopilot_not_covered", "an unnamed target is outside the scope")
        spent = ap.AutopilotPolicy("p1", policy.capability_ids, policy.constraints, policy.limits, {"actionsToday": 2}, policy.expires_at)
        self.assertEqual(decide(eligible, grants("recommended", autopilot=(spent,)), actor=robot, target={"campaignId": "c1"}).reason, "autopilot_limit")
        expired = ap.AutopilotPolicy("p1", policy.capability_ids, policy.constraints, policy.limits, {}, NOW - 1)
        self.assertEqual(decide(eligible, grants("recommended", autopilot=(expired,)), actor=robot, target={"campaignId": "c1"}).reason, "autopilot_not_covered")
        self.assertEqual(decide(cap("draft_edit"), g, actor=robot, target={"campaignId": "c1"}).reason, "autopilot_not_covered", "not eligible")
        ask = grants("custom", {"category:create_edit": "ask"}, autopilot=(policy,))
        self.assertEqual(decide(eligible, ask, actor=robot, target={"campaignId": "c1"}).reason, "autopilot_not_covered", "autopilot needs Assist")
        self.assertEqual(decide(eligible, grants("legacy"), actor=robot, target={"campaignId": "c1"}).reason, "autopilot_not_covered")
        r2 = cap("schedule_propose", autopilot_eligible=True)
        policy2 = ap.AutopilotPolicy("p2", frozenset({r2.capability_id}), {}, {}, {}, NOW + 3600)
        g2 = grants("full", autopilot=(policy2,))
        self.assertEqual(decide(r2, g2, actor=robot).outcome, "approve", "R2 never runs without a per-action approval")
        approval = {"state": "approved", "capabilityId": r2.capability_id, "digest": "a" * 64, "requestedFor": ME, "expiresAt": NOW + 60}
        self.assertEqual(decide(r2, g2, actor=authz.Actor("autopilot", ME, "", {"approval": approval, "digest": "a" * 64})).outcome, "allow")
        r3 = cap("draft_edit", risk="R3", confirmation="approval_step_up", autopilot_eligible=True)
        self.assertEqual(decide(r3, grants("full"), actor=robot).outcome, "deny")


class GrantsAndPresetsTest(unittest.TestCase):
    def test_recommended_full_and_none_literals(self):
        rec = ap.PRESETS["recommended"]["categories"]
        self.assertEqual({k for k, v in rec.items() if v == "assist"}, {"read_analyze", "navigate_interact", "create_edit"})
        self.assertEqual({k for k, v in rec.items() if v == "ask"}, set(authz.CATEGORIES) - {"read_analyze", "navigate_interact", "create_edit"})
        self.assertEqual(ap.PRESETS["recommended"]["spend_confirmation"], "all")   # SD-1 frozen default
        self.assertTrue(ap.PRESETS["full"]["step_up"])
        self.assertEqual(set(ap.PRESETS["full"]["categories"].values()), {"assist"})
        self.assertNotIn("public", ap.ALL_DOMAINS)
        self.assertNotIn("manage_connected_services", ap.LEGACY_EQUIVALENT["categories"])
        self.assertEqual(ap.LEGACY_EQUIVALENT["baseline"], "legacy_v1")

    def test_token_changes_with_the_basis_and_is_compared_for_equality_only(self):
        a = grants(epoch=3)
        self.assertEqual(a.token(), grants(epoch=3).token())
        self.assertRegex(a.token(), r"^[0-9a-f]{64}$")
        for b in (grants(epoch=4), grants("full", epoch=3), ap.legacy(WS, ME, user_epoch=3), ap.legacy(WS, ME, user_epoch=3, ended=True),
                  grants(epoch=3, workspace_epoch=1)):
            self.assertTrue(authz.token_changed(a.token(), b.token()))
        self.assertFalse(authz.token_changed(a.token(), a.token()))
        self.assertNotEqual(ap.legacy(WS, ME).token(), ap.legacy(WS, ME, user_epoch=2, ended=True).token(), "an ended row never looks like never-chosen")

    def test_manager_reach_expansion_is_a_widening_and_none_narrows(self):
        legacy = grants("legacy")
        for preset in ("recommended", "full"):
            diff = ap.catalogue_diff(legacy, grants(preset), member=OWNER, state={}, now=NOW)
            self.assertTrue({"tool.campaign_link", "tool.campaign_unlink", "tool.draft_edit"} & diff.widened, preset)
        none = ap.catalogue_diff(legacy, grants("none"), member=OWNER, state={}, now=NOW)
        self.assertTrue(none.denied_now and not none.widened)
        self.assertNotIn("tool.help_search", none.denied_now, "help and navigation stay available under Off")
        loose = ap.catalogue_diff(grants("recommended"), grants("full"), member=OWNER, state={}, now=NOW)
        self.assertTrue(loose.spend_looser)
        self.assertIn("tool.draft_create", loose.widened, "dropping the spend confirmation lowers the effective confirmation")

    def test_revoke_from_legacy_never_widens(self):
        """A2 / correction 5: every single-scope revoke a legacy person can make adds nothing and lowers no confirmation."""
        legacy = grants("legacy")
        base = ap.preset_scopes("legacy_equivalent")
        scopes = [k for k in base] + [f"capability:{c.capability_id}" for c in authz.catalogue()]
        for scope in scopes:
            after = dict(base)
            if scope.startswith("capability:"):
                after[scope] = "off"
            else:
                after.pop(scope, None)
            g = ap.from_scopes(WS, ME, after, preset="custom", baseline="legacy_v1", spend="none")
            diff = ap.catalogue_diff(legacy, g, member=OWNER, state={}, now=NOW)
            self.assertEqual((diff.widened, diff.spend_looser), (frozenset(), False), scope)
        equivalent = ap.from_scopes(WS, ME, base, preset="custom", baseline="legacy_v1", spend="none")
        self.assertEqual(ap.catalogue_diff(legacy, equivalent, member=OWNER, state={}, now=NOW).denied_now, frozenset(), "LEGACY_EQUIVALENT is today")

    def test_step_up_rules(self):
        legacy = grants("legacy")
        self.assertTrue(ap.needs_step_up(legacy, "full", ap.preset_scopes("full")))
        self.assertFalse(ap.needs_step_up(legacy, "recommended", ap.preset_scopes("recommended")))
        for category in ap.SENSITIVE_ASSIST:
            self.assertTrue(ap.needs_step_up(grants(), "custom", {**ap.preset_scopes("recommended"), f"category:{category}": "assist"}), category)
        self.assertTrue(ap.needs_step_up(grants(), "custom", {**ap.preset_scopes("recommended"), "capability:tool.schedule_propose": "assist"}))
        self.assertFalse(ap.needs_step_up(grants(), "custom", {**ap.preset_scopes("recommended"), "category:create_edit": "ask"}))

    def test_put_validation(self):
        body = {"preset": "custom", "scopes": {"category:create_edit": "ask"}, "expectedEpoch": 0, "consentVersion": ap.CONSENT_VERSION,
                "copyDigest": ap.COPY_DIGEST, "idempotencyKey": "k" * 20}
        self.assertEqual(ap.validate_put(body)["scopes"], {"category:create_edit": "ask"})
        bad = [{"source": "genui"}, {"scopes": {"capability:tool.no_such": "assist"}}, {"scopes": {"category:publish_everything": "assist"}},
               {"scopes": {"domain:public": True}}, {"scopes": {"domain:library": "yes"}}, {"preset": "recommended"}, {"preset": "root"},
               {"preset": "full", "scopes": {}, "spendConfirmation": "all"}]
        for change in bad:
            with self.assertRaises(authz.AuthzError, msg=change) as caught:
                ap.validate_put({**body, **change})
            self.assertEqual(caught.exception.code, "scope_invalid", change)
        for change in ({"idempotencyKey": "short"}, {"expectedEpoch": -1}, {"expectedEpoch": "0"}, {"extra": 1}, {"confirmed": "yes"}):
            with self.assertRaises(AlphaError, msg=change):
                ap.validate_put({**body, **change})

    def test_custom_starts_from_recommended_for_a_legacy_person(self):
        preset, scopes, spend = ap.target_of(grants("legacy"), {"preset": "custom", "scopes": {"domain:library": False, "category:create_edit": "ask"}, "spend": None})
        self.assertEqual(preset, "custom")
        self.assertNotIn("domain:library", scopes)
        self.assertEqual(scopes["category:create_edit"], "ask")
        self.assertEqual(scopes["category:read_analyze"], "assist")
        self.assertEqual(spend, "all")

    def test_fingerprint_binds_the_person_and_the_body(self):
        body = {"preset": "recommended", "expectedEpoch": 0, "idempotencyKey": "k" * 20}
        self.assertEqual(ap.fingerprint(ME, body), ap.fingerprint(ME, {**body, "idempotencyKey": "z" * 20}))
        self.assertNotEqual(ap.fingerprint(ME, body), ap.fingerprint("someone-else", body))
        self.assertNotEqual(ap.fingerprint(ME, body), ap.fingerprint(ME, {**body, "preset": "full"}))

    def test_step_verdict_mapping(self):
        c = cap("draft_edit")
        d = decide(c, grants("custom", {"category:create_edit": "ask"}))
        self.assertEqual((authz.step_verdict(d).verdict, authz.step_verdict(d).approval_kind), ("approve", "agent_action"))
        denied = decide(c, grants("custom", {"capability:tool.draft_edit": "off"}))
        self.assertEqual(authz.step_verdict(denied, earlier_token=denied.token).reason_code, "permission_missing")
        self.assertEqual(authz.step_verdict(denied, earlier_token="0" * 64).reason_code, "permission_revoked")
        self.assertEqual(authz.step_verdict(decide(c, grants(), member=None)).reason_code, "member_inactive")
        for d in (denied, decide(c, grants(), member=None)):
            self.assertIn(authz.step_verdict(d).reason_code, agent_error_codes.STEP_BLOCKED)


# --- the E1 gate in off / shadow / enforce ------------------------------------------------------------------------------------
def _workspace_state():
    state = initial_state(WS)
    state["phase2"] = {"channels": [], "jobs": [], "reviews": [], "assets": []}
    state["variants"] = [{"id": "d1", "platform": "Instagram", "language": "en", "channelId": "ig", "text": "Slow practice builds fast hands.", "revision": 1}]
    state["raffi"] = {"campaignPlanning": {"campaigns": [{"id": "c1", "goal": "Autumn launch", "audience": "Adult learners", "status": "draft", "items": []}],
                                           "recurringTasks": [], "occurrences": []}}
    return state


STATE = _workspace_state()   # one fixed state (initial_state draws random ids), copied into every fake workspace


def workspace_state():
    return copy.deepcopy(STATE)


class Repo:
    def __init__(self, role="owner", workspace=WS):
        self.state, self.revision, self.role, self.workspace = workspace_state(), 1, role, workspace
        self.commands, self.transactions = [], 0

    @contextmanager
    def transaction(self, token, workspace_id):
        if workspace_id != self.workspace:
            raise AlphaError("Workspace unavailable.", 403)
        self.transactions += 1
        yield None, ("row",), ME

    def get(self, workspace_id, token):
        return {"revision": self.revision, "state": copy.deepcopy(self.state), "membership": {"role": self.role}}

    def command(self, workspace_id, token, revision, fn, requirement="edit", audit_event=None, after=None, step_up=False):
        if not Membership.from_row(self.role).allows(requirement):
            raise AlphaError("Your role can't do this.", 403)
        self.state = fn(copy.deepcopy(self.state), ME)
        self.revision += 1
        self.commands.append({"requirement": requirement})
        return {"revision": self.revision, "state": self.state}


class Ideas:
    def __init__(self, repo):
        self.repo = repo

    def _member(self, row):
        return Membership.from_row(self.repo.role)

    def _state(self, row):
        return copy.deepcopy(self.repo.state)


class Commands:
    def __call__(self, state, actor, action, payload):
        from postriff_phase2 import campaigns
        campaigns.apply_action(state, action, payload, actor, NOW)
        return state


class Service:
    def __init__(self, role="owner"):
        self.repository = Repo(role)
        self.ideas = Ideas(self.repository)
        self.commands = Commands()
        self.assets = None


def ctx_for(mode="off", *, workspace=WS, role="owner", request_text="Link the draft", service=None, listed=WS):
    service = service or Service(role)
    # Isolate the E1 adapter, independently of the separate production activation tests.
    cfg = config.RuntimeConfig.from_environment({})
    cfg.permissions_for = lambda w: mode if listed == "*" or w == listed else "off"
    return rt_context.RafiiRunContext(service=service, workspace_id=workspace, token="t" * 40, principal=ME, membership=Membership.from_row(role),
                                      conversation_id="conv-1", trace_id=contracts.new_trace_id(), now=lambda: NOW,
                                      config=cfg, request_text=request_text)



CALLS = [("campaign_items", {"campaignId": "c1"}), ("campaign_link", {"campaignId": "c1", "draftIds": ["d1"]}), ("help_search", {"query": "how do I schedule"}),
         ("campaign_unlink", {"campaignId": "c1", "draftIds": ["d1"]}), ("campaign_link", {"campaignId": "nope", "draftIds": ["d1"]})]


def run(ctx):
    out = []
    for name, args in CALLS:
        result = tool_adapter.execute(ctx, tool_adapter.REGISTRY[name], args, agent="campaign" if name.startswith("campaign") else None)
        out.append(json.loads(json.dumps(result, default=str)))
    activity = [{k: v for k, v in a.items() if k != "latencyMs"} for a in ctx.ledger.tool_activity]
    return out, activity, ctx.service.repository.commands, copy.deepcopy(ctx.service.repository.state), list(ctx.ledger.changed)


class ToolGateTest(unittest.TestCase):
    def test_off_reads_nothing(self):
        with mock.patch.object(authz, "evaluate_tool", side_effect=AssertionError("evaluated in off mode")), \
                mock.patch.object(ap, "load", side_effect=AssertionError("grants read in off mode")):
            outputs, *_ = run(ctx_for("off"))
            # Listed workspace, mode off; and a mode on but this workspace not listed: both are off.
            run(ctx_for("off", listed=WS))
            run(ctx_for("enforce", listed=OTHER_WS))
        self.assertTrue(all("agent_permission" not in json.dumps(o) for o in outputs))

    def test_shadow_changes_nothing_golden(self):
        """Shadow mode computes every decision, even would-denies, and the turn is byte-for-byte the off-mode turn."""
        golden = run(ctx_for("off"))
        nothing = ap.from_scopes(WS, ME, {}, preset="none")
        with mock.patch.object(ap, "load", return_value=nothing), self.assertLogs("postriff.agent_runtime", logging.INFO) as logs:
            shadow = run(ctx_for("shadow"))
        self.assertEqual(shadow, golden)
        events = [json.loads(line.split(":", 2)[2]) for line in logs.output if "agent.authz" in line]
        self.assertTrue(any(e["event"] == "agent.authz.shadow" and e["wouldOutcome"] == "deny" and e["capabilityId"] == "tool.campaign_link" for e in events))
        self.assertTrue(all("token" not in e and "t" * 40 not in json.dumps(e) for e in events), "no session token in logs")
        with mock.patch.object(ap, "load", side_effect=RuntimeError("store down")):
            self.assertEqual(run(ctx_for("shadow")), golden, "a failing evaluation in shadow mode changes nothing")
        # Legacy people under shadow: zero would-deny lines for today's tools (the canary requirement).
        with mock.patch.object(ap, "load", return_value=ap.legacy(WS, ME)), self.assertLogs("postriff.agent_runtime", logging.INFO) as logs:
            logging.getLogger("postriff.agent_runtime").info("marker")
            self.assertEqual(run(ctx_for("shadow")), golden)
        self.assertFalse([line for line in logs.output if '"wouldOutcome": "deny"' in line])

    def test_enforce_denies_before_the_executor(self):
        nothing = ap.from_scopes(WS, ME, {}, preset="none")
        ctx = ctx_for("enforce")
        with mock.patch.object(ap, "load", return_value=nothing):
            out = tool_adapter.execute(ctx, tool_adapter.REGISTRY["campaign_link"], {"campaignId": "c1", "draftIds": ["d1"]}, agent="campaign")
            helped = tool_adapter.execute(ctx, tool_adapter.REGISTRY["help_search"], {"query": "schedule"})
        self.assertEqual((out["ok"], out["code"], out["reason"], out["settingsHref"]), (False, "agent_permission_denied", "category_off", "/app/account/agent"))
        self.assertEqual(ctx.service.repository.commands, [], "nothing changed")
        self.assertEqual(ctx.ledger.tool_activity[0]["status"], "blocked")
        self.assertNotEqual(helped.get("code"), "agent_permission_denied", "help stays available under Off")
        with mock.patch.object(ap, "load", return_value=ap.legacy(WS, ME)):
            self.assertEqual(run(ctx_for("enforce")), run(ctx_for("off")), "enforce with no choice on record is today's behaviour")

    def test_enforce_asks_for_confirmation_under_ask(self):
        ask = grants("custom", {"category:create_edit": "ask"})
        ctx = ctx_for("enforce")
        with mock.patch.object(ap, "load", return_value=ask):
            out = tool_adapter.execute(ctx, tool_adapter.REGISTRY["campaign_link"], {"campaignId": "c1", "draftIds": ["d1"]}, agent="campaign")
        self.assertEqual((out["code"], out["needsUser"], out["approvalId"]), ("needs_confirmation", True, None))
        self.assertEqual(ctx.service.repository.commands, [])
        requested = []
        with mock.patch.object(ap, "load", return_value=ask), mock.patch.object(authz, "APPROVAL_REQUESTER", [lambda *a: requested.append(a) or {"approvalId": "ap1", "expiresAt": NOW + 60}]):
            out = tool_adapter.execute(ctx_for("enforce"), tool_adapter.REGISTRY["campaign_link"], {"campaignId": "c1", "draftIds": ["d1"]}, agent="campaign")
        self.assertEqual(out["approvalId"], "ap1")
        self.assertEqual(len(requested), 1)

    def test_revocation_applies_to_the_next_tool_call_and_to_resumed_jobs(self):
        state = {"grants": grants("recommended", epoch=1)}
        ctx = ctx_for("enforce")
        with mock.patch.object(ap, "load", side_effect=lambda *a, **k: state["grants"]):
            first = tool_adapter.execute(ctx, tool_adapter.REGISTRY["campaign_link"], {"campaignId": "c1", "draftIds": ["d1"]}, agent="campaign")
            self.assertTrue(first["ok"], first)
            state["grants"] = grants("custom", {"capability:tool.campaign_unlink": "off"}, epoch=2)
            second = tool_adapter.execute(ctx, tool_adapter.REGISTRY["campaign_unlink"], {"campaignId": "c1", "draftIds": ["d1"]}, agent="campaign")
            self.assertEqual((second["code"], second["reason"]), ("agent_permission_denied", "capability_off"))
            # A run resumed after an approval builds a fresh context (request_text "(approved)") and re-reads the grants.
            resumed = ctx_for("enforce", service=ctx.service, request_text="(approved)")
            again = tool_adapter.execute(resumed, tool_adapter.REGISTRY["campaign_unlink"], {"campaignId": "c1", "draftIds": ["d1"]}, agent="campaign")
            self.assertEqual(again["code"], "agent_permission_denied")
        self.assertEqual(len(ctx.service.repository.commands), 1, "only the call made before the revoke changed anything")

    def test_cross_workspace_and_missing_membership(self):
        # Not listed: off. A request bound to another workspace cannot read this one's grants (the transaction refuses).
        other = ctx_for("enforce", workspace=OTHER_WS)
        with mock.patch.object(authz, "evaluate_tool", side_effect=AssertionError("evaluated")):
            self.assertNotIn("agent_permission", json.dumps(tool_adapter.execute(other, tool_adapter.REGISTRY["help_search"], {"query": "x"})))
        foreign = ctx_for("enforce", workspace=OTHER_WS, listed="*")
        out = tool_adapter.execute(foreign, tool_adapter.REGISTRY["campaign_items"], {"campaignId": "c1"}, agent="campaign")
        self.assertEqual((out["code"], out["reason"]), ("agent_permission_denied", "membership_missing"))
        nobody = ctx_for("enforce")
        nobody.membership = None
        out = tool_adapter.execute(nobody, tool_adapter.REGISTRY["campaign_items"], {"campaignId": "c1"}, agent="campaign")
        self.assertEqual(out["reason"], "membership_missing", "enforce: no membership is a deny (INV-2)")

    def test_grant_writes_refuse_inside_a_tool(self):
        seen = {}

        def probe(ctx, args):
            seen["in_tool"] = authz.IN_TOOL.get()
            try:
                authz.human_only("t" * 40)
            except authz.AuthzError as error:
                seen["code"] = error.code
            return {"ok": True}

        spec = contracts.ToolSpec("permission_probe", contracts.READ, "read", "probe")
        tool = tool_adapter.Tool(spec, {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, probe, "probe")
        tool_adapter.execute(ctx_for("off"), tool, {})
        self.assertEqual(seen, {"in_tool": True, "code": "agent_permissions_human_only"})
        self.assertFalse(authz.IN_TOOL.get())
        authz.human_only("t" * 40)   # outside a tool, from a session token: allowed
        with self.assertRaises(authz.AuthzError):
            authz.human_only("prt_" + "a" * 48)   # an API token never writes grants


class StepUpTest(unittest.TestCase):
    class Verify:
        def __init__(self, method_time=None, aal="aal1"):
            if method_time is not None:
                self.method_time = lambda token, principal: method_time
            self.aal = lambda token, principal: aal

    class Repository:
        def __init__(self, verify, fresh=True):
            self.verify_session, self.fresh = verify, fresh

        def assert_fresh(self, token, principal):
            if not self.fresh:
                raise AlphaError("Sign in again to confirm this sensitive action.", 403, code="step_up_required")

    def test_fresh_sign_in_within_five_minutes(self):
        proof = authz.require_step_up(self.Repository(self.Verify(("password", NOW - 30), "aal2")), "t" * 40, ME, now=NOW)
        self.assertEqual(proof, {"method": "password", "at": NOW - 30, "aal": "aal2"})

    def test_stale_refreshed_or_missing_proof_is_refused(self):
        for repo in (self.Repository(self.Verify(("password", NOW - 301))), self.Repository(self.Verify((None, 0))), self.Repository(self.Verify()),
                     self.Repository(self.Verify(("password", NOW - 10)), fresh=False), self.Repository(self.Verify(("otp", NOW + 600)))):
            with self.assertRaises(authz.AuthzError) as caught:
                authz.require_step_up(repo, "t" * 40, ME, now=NOW)
            self.assertEqual(caught.exception.code, "step_up_required")
            self.assertEqual(caught.exception.body()["stepUp"], {"required": True, "reason": "agent_permissions", "maxAgeSeconds": 300})

    def test_amr_method_time_ignores_iat(self):
        import base64
        def jwt(payload):
            raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
            return f"h.{raw}.s"
        token = jwt({"sub": ME, "iat": NOW, "amr": [{"method": "password", "timestamp": NOW - 900}, {"method": "totp", "timestamp": NOW - 20}]})
        self.assertEqual(hosted_identity.verified_method_time(token, ME), ("totp", NOW - 20))
        self.assertEqual(hosted_identity.verified_method_time(jwt({"sub": ME, "iat": NOW}), ME), (None, 0), "a refreshed token's iat is not a sign-in")


class TaskStepGateTest(unittest.TestCase):
    def evaluate(self, mode, *, kind="tool", capability="tool.draft_edit", member=OWNER, task_extra=None, step_extra=None, actor_kind="agent"):
        cur = mock.Mock()
        cur.fetchone.return_value = ({},)
        task = {"workspaceId": WS, "createdBy": ME, "authzToken": "a" * 64, **(task_extra or {})}
        step = {"kind": kind, "capabilityId": capability, **(step_extra or {})}
        with mock.patch.object(authz, "_step_member", return_value=member):
            return authz.decide_for_step(cur, task, step, actor=authz.Actor(actor_kind, ME), now=NOW,
                                         config=SimpleNamespace(permissions_for=lambda ws: mode))

    def test_shadow_equals_off_even_when_grants_deny_or_fail(self):
        with mock.patch.object(ap, "load", side_effect=AssertionError("off read grants")):
            legacy = self.evaluate("off")
        for effect in (None, RuntimeError("unavailable")):
            with mock.patch.object(ap, "load", return_value=grants("none"), side_effect=effect):
                self.assertEqual(self.evaluate("shadow"), legacy)
        with mock.patch.object(ap, "load", return_value=grants("none")):
            self.assertEqual(self.evaluate("enforce").verdict, "deny")

    def test_only_external_cron_observer_survives_inactive_creator(self):
        step = {"observesExternal": True, "delegateType": "publish_job"}
        with mock.patch.object(ap, "load", side_effect=AssertionError("observer read grants")):
            self.assertEqual(self.evaluate("enforce", kind="delegate", member=None, actor_kind="cron", step_extra=step).verdict, "observe")
            self.assertEqual(self.evaluate("enforce", kind="delegate", member=None, actor_kind="agent", step_extra=step).verdict, "deny")
            self.assertEqual(self.evaluate("enforce", kind="delegate", member=None, actor_kind="cron", step_extra={**step, "observesExternal": False}).verdict, "deny")
            self.assertEqual(self.evaluate("enforce", kind="delegate", actor_kind="cron", step_extra=step).verdict, "allow")
            self.assertEqual(self.evaluate("enforce", kind="delegate", actor_kind="cron", step_extra=step, task_extra={"cancelRequestedAt": NOW}).verdict, "observe")

    def test_step_reloads_grants_and_preserves_proposal_floor(self):
        with mock.patch.object(ap, "load", side_effect=[grants("recommended"), grants("none")]) as reader:
            self.assertEqual(self.evaluate("enforce").verdict, "allow")
            self.assertEqual(self.evaluate("enforce").verdict, "deny")
            self.assertEqual(reader.call_count, 2)
        with mock.patch.object(ap, "load", return_value=grants("full")):
            verdict = self.evaluate("enforce", capability="tool.schedule_propose")
            self.assertEqual(verdict.required_permission, "approve")
            self.assertEqual(verdict.approver_policy, "role_approve")
        self.assertEqual(self.evaluate("enforce", capability="tool.unknown").verdict, "deny")


class ContextGateTest(unittest.TestCase):
    def test_actual_registry_and_only_allow_reads(self):
        args = dict(cur=object(), state={}, workspace_id=WS, principal=ME, member=OWNER, now=NOW)
        off = SimpleNamespace(permissions_for=lambda w: "off")
        with mock.patch.object(ap, "load", side_effect=AssertionError("off read grants")):
            self.assertEqual(authz.context_gate("context.screen_outline", config=off, **args), "allow")
        for mode in ("shadow", "enforce"):
            cfg = SimpleNamespace(permissions_for=lambda w, mode=mode: mode)
            with mock.patch.object(ap, "load", return_value=grants("none")):
                self.assertEqual(authz.context_gate("context.screen_outline", config=cfg, **args), "allow" if mode == "shadow" else "deny")
            with mock.patch.object(ap, "load", return_value=grants("legacy")):
                self.assertEqual(authz.context_gate("context.screen_outline", config=cfg, **args), "allow")
            with mock.patch.object(ap, "load", side_effect=RuntimeError("store unavailable")):
                self.assertEqual(authz.context_gate("context.screen_outline", config=cfg, **args), "allow" if mode == "shadow" else "deny")
            self.assertEqual(authz.context_gate("context.unknown", config=cfg, **args), "allow" if mode == "shadow" else "deny")
        cfg = SimpleNamespace(permissions_for=lambda w: "enforce")
        for outcome in ("confirm", "approve", "step_up", "deny"):
            with mock.patch.object(ap, "load", return_value=grants()), mock.patch.object(authz, "decide", return_value=SimpleNamespace(outcome=outcome, reason="test")):
                self.assertEqual(authz.context_gate("context.screen_outline", config=cfg, **args), "deny", outcome)


class ContractTest(unittest.TestCase):
    def test_migration_109_is_the_frozen_proposal(self):
        sql = (ROOT / "migrations/postriff/109_agent_permissions.sql").read_bytes()
        self.assertEqual(hashlib.sha256(sql).hexdigest(), FROZEN_109_SHA256)
        frozen = ROOT / "docs/design/rafii-agent-os/migrations/109_agent_permissions.sql"
        if frozen.exists():
            self.assertEqual(sql, frozen.read_bytes())
        harness = (ROOT / "tests/phase2/rls.sql").read_text()
        self.assertIn("migrations/postriff/109_agent_permissions.sql", harness)

    def test_one_error_vocabulary(self):
        fixture = json.loads((ROOT / "tests/fixtures/agent_tasks/contracts/error-codes.json").read_text())
        self.assertEqual(fixture, agent_error_codes.table())
        self.assertFalse(set(agent_error_codes.RETIRED) & set(agent_error_codes.ERRORS))
        ts = (ROOT / "web/src/lib/agent-permissions/error-codes.ts").read_text()
        errors = dict(re.findall(r"^\s+(\w+): (\d{3}),?$", ts.split("export const AGENT_ERRORS")[1].split("} as const")[0], re.M))
        self.assertEqual({k: int(v) for k, v in errors.items()}, agent_error_codes.ERRORS)
        results = re.findall(r"'(\w+)'", ts.split("export const AGENT_RESULT_CODES")[1].split(";")[0])
        self.assertEqual(tuple(results), agent_error_codes.RESULTS)
        cf2 = ROOT / "docs/design/rafii-agent-os/CF-2-authz-consent.md"
        if cf2.exists():   # once the contracts PR is merged: the table there is the source
            table = cf2.read_text().split("### 13.1 Errors")[1].split("### 13.2")[0]
            self.assertEqual({code for line in table.splitlines() if line.startswith("| `") for code in re.findall(r"`(\w+)`", line.split(" | ")[0])}, set(agent_error_codes.ERRORS))
        self.assertTrue(set(authz.REASON_CODES) >= {"role", "category_off", "membership_missing", "permissions_changed"})

    def test_every_membership_end_path_ends_agent_permissions(self):
        """A6: each UPDATE that sets a membership to revoked runs on_membership_ended in the same function."""
        found = 0
        for path in (ROOT / "src").rglob("*.py"):
            text = path.read_text()
            for match in re.finditer(r"UPDATE public\.pr_memberships SET status='revoked'", text):
                found += 1
                body = text[match.start():match.start() + 900]
                self.assertIn("agent_permissions.on_membership_ended(", body, f"{path.name}: membership end without on_membership_ended")
        self.assertGreaterEqual(found, 2)
        deletion = (ROOT / "src/postriff_phase2/account_deletion.py").read_text()
        self.assertLess(deletion.index("agent_permissions.erase_workspace(cur, workspace_id)"), deletion.index("DELETE FROM public.pr_memberships"))

    def test_copy_has_every_key_the_contract_names(self):
        for key in ("consentVersion", "categories", "domains", "presets", "spend", "revoke", "notRecallable", "reminder"):
            self.assertIn(key, ap.COPY)
        self.assertEqual(set(ap.COPY["categories"]), set(authz.CATEGORIES))
        self.assertEqual(set(ap.COPY["domains"]), set(ap.ALL_DOMAINS))
        self.assertEqual(ap.COPY["consentVersion"], ap.CONSENT_VERSION)
        self.assertRegex(ap.COPY_DIGEST, r"^[0-9a-f]{64}$")

    def test_authz_error_bodies(self):
        error = authz.AuthzError("x", "agent_permissions_changed", extra={"current": {"epoch": 3}})
        self.assertEqual((error.status, error.body()), (409, {"error": "x", "code": "agent_permissions_changed", "current": {"epoch": 3}}))


if __name__ == "__main__":
    unittest.main()
