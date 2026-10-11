"""Synthetic OpenUI provenance fence: no provider, browser or database calls.

The stream harness replaces transport/storage/manifest boundaries, while these
tests use the real parent SQL, classifier, admission and replay paths.
"""
import copy
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import ui_capabilities, ui_contracts as contracts, ui_http, ui_projection, ui_stream
from postriff_phase2.youtube import agent_context
from test_agent_ui_stream import Base as _StreamBase, KEY as PRESENTATION_KEY
from test_agent_ui_stream_fakes import OTHER, OTHER_TOKEN, OTHER_WS, TOKEN, WS, Started, parse, usage_final

REAL_PROJECT = ui_projection.project_ui_context
FLAGS = {"enabled": True, "actions": True, "edits": True}


def contexts():
    return {
        "tagged": {agent_context.KEY: [agent_context.source(WS, "youtube:synthetic", "UC" + "e" * 22, "synthetic-generation", time.time())]},
        "legacy": {"facts": [{"kind": "youtube_native_analytics", "evidence": {"connectionId": "youtube:synthetic", "channelId": "UC" + "e" * 22}}]},
        "removed": {agent_context.REMOVED: True},
        "empty_tag": {agent_context.KEY: []},
        "malformed_tag": {agent_context.KEY: "malformed-server-marker"},
        "false_removed": {agent_context.REMOVED: False},
    }


class YouTubeOpenUIFence(_StreamBase):
    def state(self):
        return copy.deepcopy({"artifacts": self.db.artifacts, "attempts": self.db.attempts, "revisions": self.db.revisions,
                              "events": self.db.events, "ledger": self.db.ledger, "creates": self.store.creates,
                              "reserves": self.db.reserve_calls, "settles": self.db.settle_calls,
                              "approvals": self.runtime.approvals, "providerCalls": self.transport.calls})

    def rejected(self, call, *, code="ui_not_eligible", status=409):
        before = self.state()
        with self.assertRaises(AlphaError) as raised:
            call()
        self.assertEqual((raised.exception.status, raised.exception.code), (status, code))
        self.assertEqual(self.state(), before, "rejection must precede persistence, reservations, settlements and provider dispatch")

    def edit(self, artifact_id, *, key="youtube-fence-edit-0001", token=TOKEN):
        head = self.db.artifacts[artifact_id]
        request = contracts.validate_patch({"baseRevision": head["revision"], "baseSourceHash": head["sourceHash"],
                                            "instruction": "Show the drafts as a table", "idempotencyKey": key})
        return ui_stream.create_edit(self.runtime, {}, Started(), WS, token, artifact_id, request)

    def test_classifier_and_projection_reject_machine_context_before_manifest(self):
        ordinary = {"composedBy": "manager", "usage": {"billing": "metered"}, "toolActivity": [{"tool": "draft_get", "status": "verified"}],
                    "ui": {"eligible": True, "journeyIds": ["J01"]}, "answerText": "synthetic native answer"}
        for name, marker in contexts().items():
            with self.subTest(name=name):
                value = {**ordinary, **marker}
                self.assertFalse(ui_projection.eligibility(value, "show a table", "text", flags=FLAGS)["eligible"])
                self.assertTrue(ui_projection.has_youtube_context({"agent": value}))
                with mock.patch.object(ui_capabilities, "build_manifest") as manifest:
                    self.rejected(lambda: REAL_PROJECT(None, None, value, "chat", {}, flags=FLAGS))
                    manifest.assert_not_called()
        for value in ({**ordinary, "answerText": "I typed youtubeProviderContext and my YouTube views"},
                      {**ordinary, "facts": [{"kind": "youtube_native_analytics", "evidence": {"channelId": "user-entered"}}]},
                      {**ordinary, "facts": [{"kind": "user_note", "evidence": {"connectionId": "x", "channelId": "y"}}]}):
            self.assertFalse(ui_projection.has_youtube_context(value), "freeform text and ambiguous/user facts are not provenance")
            self.assertTrue(ui_projection.eligibility(value, "show a table", "text", flags=FLAGS)["eligible"])

    def test_create_blocks_cached_eligible_parent_before_sweep_plan_or_claim(self):
        for name, marker in contexts().items():
            with self.subTest(name=name):
                parent = self.db.add_parent()
                self.db.runs[parent]["result"].update(marker)
                with mock.patch.object(ui_stream, "_sweep") as sweep, mock.patch.object(ui_stream.ui_presenter, "build_plan") as plan:
                    self.rejected(lambda: self.post(parent))
                    sweep.assert_not_called()
                    plan.assert_not_called()

    def test_existing_attempt_retry_edit_and_replay_recheck_current_parent(self):
        parent, artifact_id = self.ready_artifact()
        original = copy.deepcopy(self.db.runs[parent]["result"])
        edit_key = "youtube-fence-existing-edit"
        self.drain(self.edit(artifact_id, key=edit_key))
        attempt_id = self.db.artifacts[artifact_id]["currentAttemptId"]
        for name, marker in contexts().items():
            with self.subTest(name=name):
                self.db.runs[parent]["result"] = {**copy.deepcopy(original), **marker}
                with mock.patch.object(ui_stream, "_sweep") as sweep, mock.patch.object(ui_stream.ui_presenter, "build_plan") as plan:
                    self.rejected(lambda: self.post(parent, key=PRESENTATION_KEY))
                    self.rejected(lambda: self.post(parent, key="youtube-fence-retry-0001", retryOfAttemptId=attempt_id))
                    self.rejected(lambda: self.edit(artifact_id))
                    self.rejected(lambda: self.edit(artifact_id, key=edit_key))
                    self.rejected(lambda: ui_stream.replay(self.runtime, {}, Started(), WS, TOKEN, artifact_id, 0))
                    # A shared-workspace reader also cannot replay a removed parent.
                    self.rejected(lambda: ui_stream.replay(self.runtime, {}, Started(), WS, OTHER_TOKEN, artifact_id, 0))
                    sweep.assert_not_called()
                    plan.assert_not_called()

    def test_ordinary_create_edit_shared_replay_and_cancellation_remain_available(self):
        parent, artifact_id = self.ready_artifact()
        edited = parse(self.drain(self.edit(artifact_id)))
        self.assertEqual(edited[-1]["kind"], "ui.ready")
        self.assertEqual(edited[-1]["payload"]["revision"], 2)
        calls = len(self.transport.calls)
        replayed = parse(b"".join(ui_stream.replay(self.runtime, {}, Started(), WS, OTHER_TOKEN, artifact_id, 0)))
        self.assertTrue(replayed)
        self.assertEqual(len(self.transport.calls), calls)
        self.db.runs[parent]["result"][agent_context.REMOVED] = True
        canceled = ui_stream.cancel_http(self.runtime, WS, TOKEN, artifact_id)
        self.assertFalse(canceled["canceled"], "finished presentation cancellation stays accessible for a removed parent")

    def test_foreign_parent_artifact_actor_and_server_scope_cannot_be_spoofed(self):
        foreign = self.db.add_parent(workspace=OTHER_WS, actor=OTHER)
        self.rejected(lambda: self.post(foreign), code="ui_parent_run", status=404)
        second_actor = self.db.add_parent(actor=OTHER)
        self.rejected(lambda: self.post(second_actor), code="ui_forbidden", status=403)
        founder = self.db.add_parent(run_key="agent:founder:operator:production:synthetic")
        self.rejected(lambda: self.post(founder), code="ui_parent_run", status=404)
        parent, artifact_id = self.ready_artifact()
        self.rejected(lambda: self.edit(artifact_id, token=OTHER_TOKEN), code="ui_forbidden", status=403)
        self.db.runs[parent]["workspaceId"] = OTHER_WS
        self.rejected(lambda: self.edit(artifact_id), code="ui_parent_run", status=404)
        self.rejected(lambda: ui_stream.replay(self.runtime, {}, Started(), WS, TOKEN, artifact_id, 0), code="ui_parent_run", status=404)
        with ui_http.ui_transaction(self.runtime, TOKEN, WS) as (cur, auth):
            before = list(self.db.statements)
            self.rejected(lambda: ui_stream._assert_parent_context(cur, auth, OTHER_WS, parent), code="ui_parent_run", status=404)
            self.assertEqual(self.db.statements, before, "an auth/workspace mismatch fails before reading the foreign parent")

    def admitted(self):
        parent = self.db.add_parent()
        request = contracts.validate_presentation_request({"parentRunId": parent, "idempotencyKey": PRESENTATION_KEY})
        admitted = ui_stream._start_presentation(self.runtime, ui_stream._consumer_tx(self.runtime, TOKEN, WS), WS, request,
                                               started=time.monotonic(), request_id=None)
        self.assertEqual(admitted[0], "produce")
        return parent, admitted[1]

    def test_parent_changed_after_admission_blocks_prebuilt_dispatch_and_raw_writes(self):
        parent, producer = self.admitted()
        self.db.runs[parent]["result"][agent_context.REMOVED] = True
        self.rejected(producer._presenter_items)
        self.rejected(lambda: producer._append("ui.delta", {"append": "synthetic derived source"}))
        self.rejected(lambda: producer._checkpoint("synthetic derived source", 24))
        self.assertEqual(self.transport.calls, [])
        producer._close_db()

    def assert_late_finalization_blocked(self, mode):
        parent, producer = self.admitted()
        self.db.runs[parent]["result"][agent_context.REMOVED] = True
        creates, reserves = len(self.store.creates), len(self.db.reserve_calls)
        usage = {**usage_final(), "dispatched": False, "known": True}
        frames = (producer._ready("derived", {"canonicalSource": "derived"}, usage) if mode == "ready"
                  else producer._repair("derived", ["parse_rejected"], usage))
        list(frames)
        self.assertEqual(len(self.store.creates), creates)
        self.assertEqual(len(self.db.reserve_calls), reserves)
        self.assertEqual(self.db.revisions, {})
        self.assertFalse(any(e["kind"] in ("ui.delta", "ui.ready") for e in self.db.events))
        self.assertNotIn("derived", str(self.db.events))
        self.assertEqual(self.transport.calls, [])
        producer._close_db()

    def test_late_ready_does_not_persist_derived_source(self):
        self.assert_late_finalization_blocked("ready")

    def test_late_repair_does_not_resend_derived_source(self):
        self.assert_late_finalization_blocked("repair")

    def test_replay_tail_stops_when_parent_is_removed(self):
        parent, producer = self.admitted()
        artifact_id = producer.artifact["artifactId"]
        def remove(_):
            self.db.runs[parent]["result"][agent_context.REMOVED] = True
        with mock.patch.object(ui_stream, "_sleep", side_effect=remove):
            events = parse(b"".join(ui_stream.replay(self.runtime, {}, Started(), WS, TOKEN, artifact_id, 0)))
        self.assertEqual([event["kind"] for event in events], ["ui.started"])
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.db.revisions, {})


if __name__ == "__main__":
    unittest.main()
