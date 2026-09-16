import copy
import json
import socket
import unittest
from unittest.mock import patch
import test_postriff_profiles_auth as profile_fixtures
from postriff_alpha.domain import AlphaError, Store
from postriff_alpha import visuals


class ProfileVisualAcceptance(unittest.TestCase):
    setUp = profile_fixtures.AgentAwareAcceptance.setUp
    tearDown = profile_fixtures.AgentAwareAcceptance.tearDown
    guided = profile_fixtures.AgentAwareAcceptance.guided
    def test_graph_list_projection_is_deterministic_and_only_approved(self):
        j = self.guided("hybrid")
        first = j.state["profileVisuals"]
        second = self.store.get(j.id, j.token)["state"]["profileVisuals"]
        self.assertEqual(first, second)
        self.assertEqual(len(first["groups"]), 8)
        self.assertEqual(first["center"]["label"], "The business")
        self.assertEqual({n["id"] for n in first["nodes"]}, {n["id"] for g in first["groups"] for n in g["nodes"]})
        self.assertTrue(all(n["status"] == "approved" for n in first["nodes"]))
        j.act("profile_import", content={"schema": "postriff.personal-voice.v1", "fields": [{"key": "voiceTraits", "value": "UNAPPROVED_AGENT_CLAIM"}]})
        self.assertNotIn("UNAPPROVED_AGENT_CLAIM", json.dumps(j.state["profileVisuals"]))

    def test_art_brief_is_opt_in_and_excludes_private_and_identity_data(self):
        j = self.guided()
        fields = copy.deepcopy(j.state["speaker"]["revisions"][-1]["profile"]["fields"])
        voice = next(f for f in fields if f["key"] == "voiceTraits")
        with self.assertRaises(AlphaError):
            j.act("you_art_scope", fieldIds=[voice["id"]])
        self.assertEqual(j.state["profileVisuals"]["artBrief"]["status"], "insufficient_approved_context")
        j.act("profile_field", fieldId=voice["id"], decision="approved", value="Warm and clear. PRIVATE_NAME example@example.invalid 123 Main Street raw quotation INFP", privacy="public")
        j.act("profile_finish")
        with patch.object(socket.socket, "connect", side_effect=AssertionError("No network")):
            j.act("you_art_scope", fieldIds=[voice["id"]])
            j.act("you_art_refresh")
        brief = j.state["profileVisuals"]["artBrief"]
        self.assertEqual(brief["themes"], ["warmth", "clarity"])
        for marker in ("PRIVATE_NAME", "example@", "Main Street", "quotation", "INFP"):
            self.assertNotIn(marker, json.dumps(brief))
        self.assertIsNone(brief["remoteRequest"])
        self.assertIsNone(brief["provider"])
        j.act("you_art_scope", fieldIds=[])
        self.assertEqual(j.state["profileVisuals"]["artBrief"]["sourceFieldIds"], [])

    def test_art_selection_persists_and_profile_change_cannot_replace_it(self):
        j = self.guided()
        j.act("you_art_refresh")
        selected = copy.deepcopy(j.state["you"]["artwork"])
        j.act("you_identity", value="A fictional community educator")
        j.act("profile_finish")
        self.assertEqual(j.state["you"]["artwork"], selected)
        after = Store(self.store.path).get(j.id, j.token)["state"]
        self.assertEqual(after["you"]["artwork"], selected)
        j.act("you_art_remove")
        self.assertEqual(j.state["you"]["artwork"]["state"], "removed")
        j.act("you_art_refresh")
        self.assertEqual(j.state["you"]["artwork"]["state"], "local_procedural")

    def test_restore_makes_new_revision_retains_history_and_blocks_stale_export(self):
        j = self.guided()
        j.act("source", kind="sample")
        src = j.state["sources"][0]
        j.act("approve_source", sourceId=src["id"], factIds=[f["id"] for f in src["facts"]])
        j.act("source_done")
        j.act("runtime", selected="deterministic-preview")
        j.two().act("save")
        before = copy.deepcopy(j.state["speaker"]["revisions"])
        texts = [v["text"] for v in j.state["variants"]]
        j.act("you_restore_voice", revision=1)
        self.assertEqual(j.state["speaker"]["revisions"][:-1], before)
        self.assertEqual([v["text"] for v in j.state["variants"]], texts)
        with self.assertRaises(AlphaError):
            self.store.export(j.id, j.token)
