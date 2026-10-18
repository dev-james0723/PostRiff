"""Original-text persistence: synthetic state only; no model, network or live DB."""
import copy
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_alpha.generation import FixtureAdapter
from postriff_phase2 import creation_capabilities as cc, manual_drafts
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.permissions import classify
from test_postriff_phase2_hosted import invoke

ACTOR = "00000000-0000-0000-0000-000000000001"
WORKSPACE = "00000000-0000-0000-0000-000000000010"
REQUEST = "00000000-0000-4000-8000-000000000020"
NOW = 1_800_000_000.0
TOKEN = "synthetic-session-token-00000000000000"


def state():
    return initial_phase2_state(WORKSPACE, ACTOR, "Member", "studio", NOW, execution="synthetic")


def payload(**changes):
    return {"text": "  Synthetic test only.\r\n原文保留 🎹\n  ", "requestId": REQUEST,
            "destinations": [{"platform": "LinkedIn", "language": "en"}], **changes}


class ManualDrafts(unittest.TestCase):
    def setUp(self):
        self.state = state()
        self.commands = HostedPhase2Commands(clock=lambda: NOW)

    def create(self, body=None, actor=ACTOR):
        return self.commands(self.state, actor, manual_drafts.ACTION, payload() if body is None else body)

    def test_author_text_is_exact_and_existing_research_is_untouched_without_a_writer(self):
        original = {"id": "original-research", "revision": 3, "text": "Existing research draft",
                    "sourceIds": ["research-source"], "needsReview": False,
                    "proposedUpdate": {"text": "Existing proposal"}}
        self.state["variants"].append(original)
        self.state["phase2"]["jobs"].append({"id": "existing-job", "state": "scheduled"})
        self.state["phase2"]["reviews"].append({"id": "existing-review", "status": "needs_review"})
        before = copy.deepcopy(self.state)
        with patch.object(FixtureAdapter, "generate", side_effect=AssertionError("No writer allowed")), \
             patch.object(self.commands.engine, "_apply", side_effect=AssertionError("No generator action")), \
             patch.object(self.commands.engine, "invalidate", side_effect=AssertionError("Do not touch old approvals")):
            self.create()
        self.assertEqual(self.state["variants"][0], original)
        self.assertEqual({k: v for k, v in self.state.items() if k not in ("variants", "savedAt")},
                         {k: v for k, v in before.items() if k not in ("variants", "savedAt")})
        draft = self.state["variants"][-1]
        self.assertNotEqual(draft["id"], original["id"])
        self.assertEqual(draft["text"].encode(), payload()["text"].encode())
        self.assertEqual(draft["revisions"][0]["text"], payload()["text"])
        self.assertEqual(draft["revision"], 1)
        self.assertTrue(draft["needsReview"])
        self.assertEqual(draft["sourceIds"], [])
        self.assertEqual(draft["voiceBindings"], [])
        self.assertEqual(draft["provenance"]["origin"], "author-written")
        self.assertIsNone(draft["provenance"]["model"])
        self.assertNotIn("runId", draft)

    def test_multiple_languages_keep_original_text_without_translation(self):
        self.create(payload(destinations=[{"platform": "LinkedIn", "language": "en"},
                                          {"platform": "Threads", "language": "繁體中文"}]))
        self.assertEqual([v["language"] for v in self.state["variants"]], ["en", "zh-Hant"])
        self.assertEqual([v["text"] for v in self.state["variants"]], [payload()["text"]] * 2)
        self.assertEqual(len({v["id"] for v in self.state["variants"]}), 2)

    def test_retry_reuses_exact_drafts_even_after_author_edits(self):
        self.create()
        self.state["variants"][0]["text"] = "Later author edit must survive a replay"
        before = copy.deepcopy(self.state)
        self.create()
        self.assertEqual(self.state, before)

    def test_same_request_cannot_be_reused_for_other_content_actor_or_destinations(self):
        self.create()
        before = copy.deepcopy(self.state)
        attempts = [(payload(text="Different text"), ACTOR), (payload(), "another-editor"),
                    (payload(destinations=[{"platform": "Threads", "language": "en"}]), ACTOR)]
        for body, actor in attempts:
            with self.subTest(body=body, actor=actor), self.assertRaises(AlphaError) as denied:
                self.create(body, actor)
            self.assertEqual(denied.exception.code, "manual_draft_request_conflict")
            self.assertEqual(self.state, before)

    def test_invalid_text_and_extra_authority_fields_never_change_state(self):
        bad = [payload(text=value) for value in (None, "", " \r\n ", 123, "a\x00b", "a" * 10001, "\ud800")]
        bad += [payload(**{key: value}) for key, value in
                (("variantId", "original"), ("approved", True), ("model", "anything"),
                 ("sourceIds", ["research-source"]), ("jobs", []), ("workspaceId", "foreign"))]
        bad += [payload(requestId=value) for value in (None, "", "not-a-uuid")]
        before = copy.deepcopy(self.state)
        for body in bad:
            with self.subTest(body=body), self.assertRaises(AlphaError):
                self.create(body)
            self.assertEqual(self.state, before)

    def test_destinations_are_bounded_and_nested_authority_is_rejected(self):
        valid = {"platform": "LinkedIn", "language": "en"}
        bad = [None, [], [valid] * 21, [valid, valid], [True], [{**valid, "publish": True}],
               [{**valid, "language": "made-up-language"}], [{**valid, "channelId": 123}],
               [{**valid, "platform": "invented-platform"}]]
        before = copy.deepcopy(self.state)
        for destinations in bad:
            with self.subTest(destinations=destinations), self.assertRaises(AlphaError):
                self.create(payload(destinations=destinations))
            self.assertEqual(self.state, before)

    def test_account_binding_rejects_foreign_revoked_or_wrong_platform_atomically(self):
        self.state["phase2"]["channels"] = [
            {"id": "owned", "platform": "LinkedIn", "account": "Synthetic account", "revoked": False},
            {"id": "revoked", "platform": "LinkedIn", "revoked": True}]
        before = copy.deepcopy(self.state)
        for platform, channel_id in (("LinkedIn", "foreign"), ("LinkedIn", "revoked"), ("Threads", "owned")):
            with self.subTest(platform=platform, channel_id=channel_id), self.assertRaises(AlphaError):
                self.create(payload(destinations=[{"platform": "LinkedIn", "language": "en"},
                                                  {"platform": platform, "language": "en", "channelId": channel_id}]))
            self.assertEqual(self.state, before)
        self.create(payload(destinations=[{"platform": "LinkedIn", "language": "en", "channelId": "owned"}]))
        self.assertEqual(self.state["variants"][0]["channelId"], "owned")

    def test_creation_revision_native_formats_and_discord_rollout_are_enforced(self):
        proj = cc.projection({"RAFII_CREATION_ALL_PLATFORMS_ENABLED": "1"})
        with patch.object(cc, "projection", return_value=proj):
            with self.assertRaises(AlphaError) as stale:
                self.create(payload(capabilityRevision="old-revision"))
            self.assertEqual(stale.exception.code, "schema_revision_mismatch")
            with self.assertRaises(AlphaError):
                self.create(payload(destinations=[{"platform": "LinkedIn", "language": "en", "format": "discord.message"}]))
            row = proj.by_platform["Discord"]
            self.create(payload(capabilityRevision=proj.revision,
                                destinations=[{"platform": "Discord", "language": "en", "format": row["defaultFormat"]}]))
        self.assertEqual(self.state["variants"][0]["platform"], "Discord")
        disabled = cc.projection({"RAFII_CREATION_ALL_PLATFORMS_ENABLED": ""})
        before = copy.deepcopy(self.state)
        with patch.object(cc, "projection", return_value=disabled), self.assertRaises(AlphaError) as blocked:
            self.create(payload(requestId="00000000-0000-4000-8000-000000000021",
                                destinations=[{"platform": "Discord", "language": "en"}]))
        self.assertEqual(blocked.exception.code, "platform_not_enabled")
        self.assertEqual(self.state, before)

    def test_sample_workspace_stays_read_only(self):
        self.state["workspace"]["sample"] = True
        before = copy.deepcopy(self.state)
        with self.assertRaises(AlphaError) as denied:
            self.create()
        self.assertEqual(denied.exception.status, 403)
        self.assertEqual(self.state, before)

    def test_discord_default_format_survives_explicit_review_and_immutable_manifest(self):
        import test_discord_publish_authorization as discord_fixture
        engine, current, channel, original = discord_fixture.fixture()
        original_before = copy.deepcopy(original)
        commands = HostedPhase2Commands(clock=lambda: discord_fixture.NOW)
        proj = cc.projection({"RAFII_CREATION_ALL_PLATFORMS_ENABLED": "1"})
        default_format = proj.by_platform["Discord"]["defaultFormat"]
        body = payload(text="Separate synthetic Discord draft", capabilityRevision=proj.revision,
                       destinations=[{"platform": "Discord", "language": "en", "channelId": channel["id"],
                                      "format": default_format}])
        with patch.object(cc, "projection", return_value=proj):
            with self.assertRaises(AlphaError) as duplicate:
                commands(current, discord_fixture.ACTOR, manual_drafts.ACTION, {
                    **body, "destinations": body["destinations"] + [
                        {"platform": "Discord", "language": "en", "channelId": channel["id"]}]})
            self.assertEqual(duplicate.exception.code, "duplicate_destination")
            commands(current, discord_fixture.ACTOR, manual_drafts.ACTION, body)
        saved = current["variants"][-1]
        self.assertNotIn("format", saved, "Legacy Discord default stays publishable through its existing gate")
        self.assertEqual(original, original_before)
        self.assertEqual(current["phase2"]["jobs"], [])
        self.assertEqual(current["phase2"]["reviews"], [])
        with self.assertRaises(AlphaError):
            discord_fixture.review(engine, current, channel, saved)
        commands(current, discord_fixture.ACTOR, "p2_variant_review", {
            "variantId": saved["id"], "variantRevision": 1, "confirmed": True, "excludedUnknowns": []})
        entry = discord_fixture.review(engine, current, channel, saved)
        manifest = entry["manifest"]
        self.assertTrue(engine.current(current, manifest))
        self.assertEqual(manifest["payload"]["text"], body["text"])
        self.assertEqual(manifest["discord"]["target"]["channelId"], discord_fixture.FIRST)
        self.assertEqual(current["phase2"]["jobs"], [], "An explicit review still does not approve a job")
        self.assertEqual(original, original_before)

    def test_edit_permission_and_exact_workspace_revision_are_still_required(self):
        self.assertEqual(classify(manual_drafts.ACTION), "edit")
        for role in ("owner", "admin", "editor", "approver", "viewer"):
            cursor = Mock()
            repository = PostgresWorkspaceRepository(None, lambda _: ACTOR, self.commands)

            @contextmanager
            def transaction(token, workspace_id):
                yield cursor, [7, self.state, role, False, False, False, False], ACTOR

            repository.transaction = transaction
            if role in ("approver", "viewer"):
                with self.subTest(role=role), self.assertRaises(AlphaError) as denied:
                    repository.mutate(WORKSPACE, TOKEN, 7, manual_drafts.ACTION, payload())
                self.assertEqual(denied.exception.status, 403)
                cursor.execute.assert_not_called()
            else:
                for revision in (6, 8, True, "7", None):
                    with self.subTest(role=role, revision=revision), self.assertRaises(AlphaError) as stale:
                        repository.mutate(WORKSPACE, TOKEN, revision, manual_drafts.ACTION, payload())
                    self.assertEqual(stale.exception.code, "workspace_revision_conflict")
                self.assertFalse(cursor.execute.called)
                saved = repository.mutate(WORKSPACE, TOKEN, 7, manual_drafts.ACTION, payload())
                self.assertEqual(saved["revision"], 8)
                self.assertEqual(saved["state"]["variants"][-1]["text"], payload()["text"])
                audit_args = next(c.args[1] for c in cursor.execute.call_args_list if "pr_audit_events" in c.args[0])
                self.assertEqual(audit_args[2], "draft.manual_saved")
                self.assertNotIn(payload()["text"], json.dumps(audit_args))

    def test_http_action_uses_normal_guard_and_never_the_retired_writer(self):
        service = SimpleNamespace(mutate=Mock(return_value={"revision": 8, "state": {"variants": []}}))
        app = HostedApplication(service, None)
        path = f"/api/workspaces/{WORKSPACE}/actions"
        body = {"action": manual_drafts.ACTION, "expectedRevision": 7, "payload": payload()}
        headers = {"Authorization": "Bearer " + TOKEN, "X-PostRiff-Request": "founder-alpha"}
        status, _, _ = invoke(app, "POST", path, body, headers)
        self.assertEqual(status, 200)
        service.mutate.assert_called_once_with(WORKSPACE, TOKEN, 7, manual_drafts.ACTION, payload())
        service.mutate.reset_mock()
        status, _, _ = invoke(app, "POST", path, body, {"Authorization": "Bearer " + TOKEN})
        self.assertEqual(status, 403)
        service.mutate.assert_not_called()
        status, _, _ = invoke(app, "POST", path, body, {"X-PostRiff-Request": "founder-alpha"})
        self.assertEqual(status, 401)
        service.mutate.assert_not_called()

    def test_manual_save_requires_review_and_the_existing_manifest_remains_current(self):
        from test_postriff_phase2 import Phase2Acceptance
        fixture = Phase2Acceptance()
        fixture.setUp()
        try:
            fixture.enqueue()
            current = copy.deepcopy(fixture.j.state)
            channel = current["phase2"]["channels"][-1]
            old_job = copy.deepcopy(current["phase2"]["jobs"][0])
            body = payload(text="Exact synthetic text", destinations=[
                {"platform": "LinkedIn", "language": "en", "channelId": channel["id"]}])
            self.commands(current, ACTOR, manual_drafts.ACTION, body)
            draft = current["variants"][-1]
            review = {"channelId": channel["id"], "variantId": draft["id"],
                      "localTime": datetime.fromtimestamp(NOW + 120, timezone.utc).replace(tzinfo=None).isoformat(),
                      "timeZone": "UTC", "acknowledgedWarnings": []}
            with self.assertRaises(AlphaError):
                self.commands.engine.build_manifest(current, review, ACTOR)
            self.commands(current, ACTOR, "p2_variant_review", {"variantId": draft["id"], "variantRevision": 1,
                          "confirmed": True, "excludedUnknowns": []})
            manifest = self.commands.engine.build_manifest(current, review, ACTOR)
            self.assertTrue(self.commands.engine.current(current, manifest))
            self.assertEqual(manifest["payload"]["text"], body["text"])
            self.assertEqual(current["phase2"]["jobs"], [old_job])
            self.assertTrue(self.commands.engine.current(current, old_job["manifest"]))
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
