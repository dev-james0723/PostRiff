"""Substack agent dispatch and real editorial service, without SQL/network/model calls."""
import copy
import json
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.permissions import Membership, require
from postriff_phase2.substack_service import HostedSubstackService
from postriff_phase2.agent_runtime_v2 import contracts, substack_tools, tool_adapter
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext


NOW = 1792340000
WORKSPACE = "workspace-a"
SESSION = "interactive-session-a"
PRINCIPAL = "member-a"
CONNECTION = "sc_publication_a"


class Repository:
    """In-memory transaction seam; authorization and editorial code are real."""

    def __init__(self):
        self.revision, self.role, self.active = 1, "owner", True
        self.audit, self.read_count, self.on_get = [], 0, None
        self.state = {"workspace": {"id": WORKSPACE}, "substack": {
            "version": 1, "connections": [{"id": CONNECTION, "mode": "public_feed", "status": "feed_added",
                "publicationUrl": "https://pianoresearch.substack.com", "feedUrl": "https://pianoresearch.substack.com/feed",
                "accountAuthenticated": False, "ownershipVerified": False, "feedConsentVersion": 1}],
            "drafts": [], "queue": [],
        }}

    @contextmanager
    def transaction(self, token, workspace_id):
        if not self.active or token != SESSION or workspace_id != WORKSPACE:
            raise AlphaError("Workspace unavailable.", 403)
        yield None, (self.revision, copy.deepcopy(self.state), self.role, False, False, False, False), PRINCIPAL

    def snapshot(self):
        return {"state": copy.deepcopy(self.state), "revision": self.revision,
                "membership": Membership.from_row(self.role).summary()}

    def get(self, workspace_id, token):
        with self.transaction(token, workspace_id):
            self.read_count += 1
            if self.on_get:
                self.on_get(self)
            return self.snapshot()

    def command(self, workspace_id, token, revision, command, requirement="edit", audit_event=None):
        with self.transaction(token, workspace_id):
            require(Membership.from_row(self.role), requirement)
            if type(revision) is not int or revision != self.revision:
                raise AlphaError("Workspace changed; reload.", 409, code="workspace_revision_conflict")
            changed = command(copy.deepcopy(self.state), PRINCIPAL)
            if audit_event:
                self.audit.append(audit_event(changed))
            self.state = changed
            self.revision += 1
            return self.snapshot()


def context(*, enabled=True, role="owner", modality="text"):
    repository = Repository()
    repository.role = role
    service = SimpleNamespace(repository=repository,
        ideas=SimpleNamespace(_member=lambda row: Membership.from_row(row[2]), _state=lambda row: row[1]))
    service.substack = HostedSubstackService(repository, enabled=enabled, clock=lambda: NOW, feed_fetcher=Mock())
    return RafiiRunContext(service=service, workspace_id=WORKSPACE, token=SESSION, principal=PRINCIPAL,
        membership=Membership.from_row(role), conversation_id="conversation-a", trace_id=contracts.new_trace_id(),
        now=lambda: NOW, modality=modality, request_text="Prepare a Substack draft for my review.")


def save_args(**changes):
    return {"expectedRevision": 1, "connectionId": CONNECTION, "title": "Piano practice",
            "body": "Draft text for human review.", "contentType": "article", "audience": "everyone", **changes}


def invoke(ctx, name, args, scope=None):
    return tool_adapter.execute(ctx, tool_adapter.REGISTRY[name], args,
                                scope=frozenset(scope if scope is not None else [name]))


def data(result):
    return result.get("data", result)


class SubstackAgentRegistrationTests(unittest.TestCase):
    def test_only_three_declared_nonpublishing_tools_are_registered(self):
        names = {name for name in tool_adapter.REGISTRY if name.startswith("substack_")}
        self.assertEqual(names, {"substack_workspace", "substack_draft_get", "substack_draft_save"})
        self.assertEqual(set(substack_tools.MANAGER_SCOPE), names)
        for name in names:
            spec = tool_adapter.REGISTRY[name].spec
            self.assertNotIn(spec.effect, contracts.FORBIDDEN_EFFECTS)
            self.assertIs(spec.voice, False)
            self.assertEqual(spec.since, 3)
        self.assertEqual(tool_adapter.REGISTRY["substack_draft_save"].spec.permission, "edit")

    def test_feature_disabled_refuses_even_directly_registered_tools(self):
        ctx = context(enabled=False)
        for name, args in (("substack_workspace", {}), ("substack_draft_get", {"draftId": "sd_1"}), ("substack_draft_save", save_args())):
            with self.subTest(name=name):
                result = invoke(ctx, name, args)
                self.assertIs(result["ok"], False)
                self.assertEqual(result["code"], "feature_disabled")
        self.assertEqual(ctx.service.repository.revision, 1)
        ctx.service.substack.feed_fetcher.assert_not_called()

    def test_scope_and_voice_boundaries_run_before_mutation(self):
        ctx = context()
        result = invoke(ctx, "substack_draft_save", save_args(), scope=["substack_workspace"])
        self.assertEqual(result["code"], "tool_out_of_scope")
        ctx.modality = "voice"
        result = invoke(ctx, "substack_draft_save", save_args())
        self.assertEqual(result["code"], "voice_not_allowed")
        self.assertEqual(ctx.service.repository.revision, 1)

    def test_model_cannot_supply_tenant_approval_or_session_secrets(self):
        ctx = context()
        for extra in ({"workspaceId": "foreign"}, {"confirmed": True}, {"approved": True},
                      {"providerCookie": "secret"}, {"scheduledFor": "2026-10-20T12:00:00Z"}):
            with self.subTest(extra=extra):
                result = invoke(ctx, "substack_draft_save", save_args(**extra))
                self.assertEqual(result["code"], "tool_input")
        self.assertEqual(ctx.service.repository.revision, 1)


class SubstackAgentDraftTests(unittest.TestCase):
    def test_saved_draft_is_reread_audited_and_has_no_provider_job(self):
        ctx = context()
        result = invoke(ctx, "substack_draft_save", save_args())
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertIs(result["autoPublished"], False)
        section = ctx.service.repository.state["substack"]
        self.assertEqual(len(section["drafts"]), 1)
        self.assertEqual(section["drafts"][0]["status"], "draft")
        self.assertIsNone(section["drafts"][0]["approvedHash"])
        self.assertEqual(section["queue"], [])
        self.assertGreaterEqual(ctx.service.repository.read_count, 2)
        self.assertEqual(ctx.service.repository.audit[0][0], "substack.draft_saved")
        ctx.service.substack.feed_fetcher.assert_not_called()

    def test_exact_replay_is_a_revision_conflict_without_duplicate_drafts(self):
        ctx = context()
        first = invoke(ctx, "substack_draft_save", save_args())
        self.assertTrue(first["verified"])
        repeated = invoke(ctx, "substack_draft_save", save_args())
        self.assertEqual(repeated["code"], "workspace_revision_conflict")
        self.assertEqual(len(ctx.service.repository.state["substack"]["drafts"]), 1)

    def test_foreign_destination_is_not_selected_by_model(self):
        ctx = context()
        result = invoke(ctx, "substack_draft_save", save_args(connectionId="sc_foreign"))
        self.assertEqual(result["code"], "substack_item_unavailable")
        self.assertEqual(ctx.service.repository.revision, 1)

    def test_live_role_loss_and_revoked_membership_stop_the_save(self):
        ctx = context()
        ctx.service.repository.role = "viewer"
        result = invoke(ctx, "substack_draft_save", save_args())
        self.assertIs(result["ok"], False)
        self.assertEqual(ctx.service.repository.revision, 1)
        revoked = context()
        revoked.service.repository.active = False
        result = invoke(revoked, "substack_draft_save", save_args())
        self.assertIs(result["ok"], False)
        self.assertEqual(revoked.service.repository.revision, 1)

    def test_canceled_turn_and_wrong_principal_cannot_save(self):
        ctx = context()
        ctx.cancelled = lambda: True
        result = invoke(ctx, "substack_draft_save", save_args())
        self.assertEqual(result["code"], "run_cancelled")
        wrong = context()
        wrong.principal = "different-principal"
        result = invoke(wrong, "substack_draft_save", save_args())
        self.assertIs(result["ok"], False)
        self.assertEqual(wrong.service.repository.revision, 1)

    def test_readback_mismatch_is_reported_unverified(self):
        ctx = context()
        def race(repository):
            if repository.read_count == 2:
                repository.state["substack"]["drafts"][0]["contentHash"] = "a" * 64
        ctx.service.repository.on_get = race
        result = invoke(ctx, "substack_draft_save", save_args())
        self.assertIs(result["ok"], False)
        self.assertIs(result["verified"], False)
        self.assertEqual(result["code"], "substack_save_unverified")

    def test_long_existing_article_cannot_be_read_or_overwritten_by_agent(self):
        ctx = context()
        saved = ctx.service.substack.save_draft(WORKSPACE, SESSION, save_args(body="x" * 8001))
        draft = saved["drafts"][0]
        result = invoke(ctx, "substack_draft_get", {"draftId": draft["id"]})
        self.assertEqual(result["code"], "substack_draft_too_large_for_agent")
        self.assertNotIn("body", data(result).get("draft", {}))
        result = invoke(ctx, "substack_draft_save", save_args(draftId=draft["id"], expectedRevision=saved["revision"]))
        self.assertEqual(result["code"], "substack_draft_too_large_for_agent")
        self.assertEqual(ctx.service.repository.state["substack"]["drafts"][0]["body"], "x" * 8001)

    def test_complete_small_draft_read_returns_exact_saved_content(self):
        ctx = context()
        saved = ctx.service.substack.save_draft(WORKSPACE, SESSION, save_args())
        expected = saved["drafts"][0]
        result = invoke(ctx, "substack_draft_get", {"draftId": expected["id"]})
        self.assertTrue(result["verified"])
        self.assertEqual(data(result)["draft"]["body"], expected["body"])
        self.assertEqual(data(result)["draft"]["contentHash"], expected["contentHash"])


class SubstackAgentOutputTests(unittest.TestCase):
    def test_workspace_does_not_include_full_article_bodies(self):
        ctx = context()
        ctx.service.substack.save_draft(WORKSPACE, SESSION, save_args(body="PRIVATE_ARTICLE_BODY_MARKER"))
        result = invoke(ctx, "substack_workspace", {})
        self.assertTrue(result["verified"])
        self.assertNotIn("PRIVATE_ARTICLE_BODY_MARKER", json.dumps(result))
        self.assertIs(result["autoPublishingAvailable"], False)

    def test_maximum_workspace_serialized_model_output_stays_bounded(self):
        ctx = context()
        section = ctx.service.repository.state["substack"]
        section["drafts"] = [{"id": f"sd_{i}", "connectionId": CONNECTION, "title": '"' * 300,
                               "contentType": "article", "audience": "everyone", "status": "draft",
                               "contentHash": "a" * 64, "approvedHash": None,
                               "scheduledFor": None, "body": "PRIVATE_ARTICLE_BODY" * 100,
                               "updatedAt": "2026-10-18T12:00:00Z"} for i in range(200)]
        section["connections"] += [{**section["connections"][0], "id": f"sc_{i}",
                                     "publicationUrl": f"https://publication{i}.substack.com"} for i in range(49)]
        result = invoke(ctx, "substack_workspace", {})
        self.assertTrue(result["verified"])
        self.assertLessEqual(len(tool_adapter.model_output(result)), tool_adapter.MAX_TOOL_OUTPUT)
        self.assertNotIn("PRIVATE_ARTICLE_BODY", json.dumps(result))

    def test_json_expansion_cannot_bypass_the_draft_output_limit(self):
        ctx = context()
        saved = ctx.service.substack.save_draft(WORKSPACE, SESSION, save_args(body='"' * 8000))
        result = invoke(ctx, "substack_draft_get", {"draftId": saved["drafts"][0]["id"]})
        self.assertIs(result["verified"], False)
        self.assertEqual(result["code"], "substack_draft_too_large_for_agent")
        self.assertLessEqual(len(tool_adapter.model_output(result)), tool_adapter.MAX_TOOL_OUTPUT)

    def test_multibyte_workspace_metadata_stays_within_byte_budget(self):
        ctx = context()
        section = ctx.service.repository.state["substack"]
        section["drafts"] = [{"id": "sd_" + str(i).zfill(32), "connectionId": CONNECTION,
                               "title": "🎹" * 300, "contentType": "article", "audience": "everyone",
                               "status": "handoff_ready", "contentHash": "a" * 64, "approvedHash": "a" * 64,
                               "scheduledFor": "2026-10-18T12:00:00Z", "updatedAt": "2026-10-18T12:00:00Z",
                               "body": "PRIVATE"} for i in range(200)]
        section["connections"] = [{"id": "sc_" + str(i).zfill(32), "mode": "public_feed",
                                    "publicationUrl": "https://" + str(i).zfill(63) + ".substack.com",
                                    "status": "disconnected", "ownershipVerified": False,
                                    "accountAuthenticated": False, "analyticsConnected": False,
                                    "publishingAuthorized": False} for i in range(50)]
        result = invoke(ctx, "substack_workspace", {})
        self.assertTrue(result["verified"])
        self.assertLessEqual(len(tool_adapter.model_output(result).encode("utf-8")), tool_adapter.MAX_TOOL_OUTPUT)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_paging_never_hides_that_more_drafts_exist(self):
        ctx = context()
        section = ctx.service.repository.state["substack"]
        section["drafts"] = [{"id": f"sd_{i}", "title": "Draft", "body": "PRIVATE", "status": "draft"} for i in range(21)]
        seen, offset = [], 0
        for _ in range(21):
            result = invoke(ctx, "substack_workspace", {"draftOffset": offset})
            self.assertTrue(result["verified"])
            self.assertEqual(result["counts"]["drafts"], 21)
            seen.extend(draft["id"] for draft in result["drafts"])
            if result["nextDraftOffset"] is None:
                break
            self.assertGreater(result["nextDraftOffset"], offset)
            offset = result["nextDraftOffset"]
        self.assertEqual(seen, [f"sd_{i}" for i in range(21)])

    def test_bad_offsets_are_typed_refusals_and_optional_null_never_crashes(self):
        ctx = context()
        for args in ({"draftOffset": -1}, {"draftOffset": 201}, {"draftOffset": True},
                     {"draftOffset": "0"}, {"connectionOffset": -1}, {"connectionOffset": 51}):
            with self.subTest(args=args):
                result = invoke(ctx, "substack_workspace", args)
                self.assertIs(result["ok"], False)
                self.assertEqual(result["code"], "tool_input")
        for args in ({"draftOffset": None}, {"connectionOffset": None}):
            result = invoke(ctx, "substack_workspace", args)
            self.assertTrue(result.get("ok") is True or result.get("code") == "tool_input")


if __name__ == "__main__":
    unittest.main()
