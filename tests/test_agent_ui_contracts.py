"""rafii-genui/1 shared contract: Python side matches the frozen fixture, validators refuse privilege-bearing input, the
public artifact never leaks server-only manifest data, and presentation state can never claim a business effect."""
import json
import os
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import config, service, ui_contracts as c

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(ROOT, "fixtures", "agent_ui", "contracts")
UUID = "6c1f2f3e-1111-4222-8333-944455556666"


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


class ContractDrift(unittest.TestCase):
    def test_manifest_matches_frozen_fixture(self):
        self.assertEqual(c.contract_manifest(), fixture("contract-manifest.json"))

    def test_contract_hash_is_recorded(self):
        self.assertEqual(c.contract_hash(), fixture("vectors.json")["contractHash"])

    def test_canonical_and_digest_vectors(self):
        vectors = fixture("vectors.json")
        for case in vectors["canonical"]:
            self.assertEqual(c.canonical_json(case["value"]), case["canonical"])
        for case in vectors["digests"]:
            self.assertEqual(c.input_digest(case["actionId"], case["inputs"]), case["digest"])
        mine, frozen = c.sse_frame(vectors["sseFrame"]["event"]).decode().split("\n"), vectors["sseFrame"]["frame"].split("\n")
        self.assertEqual(mine[:2], frozen[:2])
        self.assertEqual(json.loads(mine[2][len("data: "):]), json.loads(frozen[2][len("data: "):]))
        self.assertEqual(mine[3:], frozen[3:])


class Validators(unittest.TestCase):
    def test_unknown_or_privilege_keys_are_refused(self):
        for body in ({"artifactId": UUID, "bindingId": "drafts_list", "principal": UUID},
                     {"artifactId": UUID, "bindingId": "drafts_list", "isFounder": True},
                     {"artifactId": UUID, "bindingId": "drafts_list", "workspaceId": UUID}):
            with self.assertRaises(AlphaError) as raised:
                c.validate_query(body)
            self.assertEqual(raised.exception.code, "ui_unknown_field")

    def test_action_requires_activation_and_key(self):
        with self.assertRaises(AlphaError):
            c.validate_action({"artifactId": UUID, "actionId": "draft_edit", "idempotencyKey": "k" * 20})
        with self.assertRaises(AlphaError) as raised:
            c.validate_action({"artifactId": UUID, "actionId": "draft_edit", "idempotencyKey": "k" * 20, "activationId": "nope"})
        self.assertEqual(raised.exception.status, 409)
        ok = c.validate_action({"artifactId": UUID, "actionId": "draft_edit", "idempotencyKey": "k" * 20, "activationId": c.new_activation_id(),
                                "inputs": {"text": "x"}})
        self.assertEqual(ok["inputs"], {"text": "x"})

    def test_names_cannot_be_components_or_code(self):
        for name in ("Filter", "Query", "drafts list", "x", "a" * 70, "__proto__", "constructor()"):
            self.assertFalse(c.valid_name(name), name)
        self.assertTrue(c.valid_name("drafts_list"))

    def test_input_bounds(self):
        with self.assertRaises(AlphaError) as raised:
            c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "inputs": {"q": "x" * (17 * 1024)}})
        self.assertEqual(raised.exception.status, 413)
        deep = {}
        cursor = deep
        for _ in range(12):
            cursor["a"] = {}
            cursor = cursor["a"]
        with self.assertRaises(AlphaError):
            c.validate_query({"artifactId": UUID, "bindingId": "drafts_list", "inputs": deep})

    def test_server_data_may_nest_deeper_than_client_inputs(self):
        deep = {}
        cursor = deep
        for _ in range(20):
            cursor["a"] = {}
            cursor = cursor["a"]
        with self.assertRaises(AlphaError):
            c.canonical_json(deep)
        self.assertTrue(c.canonical_json(deep, max_depth=None).startswith('{"a":'))

    def test_browser_edit_carries_instruction_not_dsl(self):
        with self.assertRaises(AlphaError) as raised:
            c.validate_patch({"baseRevision": 1, "baseSourceHash": "a" * 64, "instruction": "add a chart", "idempotencyKey": "k" * 20,
                              "patchSource": "root = RafiiRoot([])"})
        self.assertEqual(raised.exception.code, "ui_unknown_field")

    def test_presentation_request(self):
        req = c.validate_presentation_request({"parentRunId": UUID, "idempotencyKey": "k" * 20})
        self.assertEqual((req["slot"], req["surface"]), ("main", "chat"))
        with self.assertRaises(AlphaError):
            c.validate_presentation_request({"parentRunId": UUID, "idempotencyKey": "k" * 20, "surface": "founder"})


class PresentationIsNotBusinessState(unittest.TestCase):
    def test_ready_cannot_set_business_verified(self):
        with self.assertRaises(ValueError):
            c.action_result("schedule_propose", "k" * 20, "prepared", verified=True)
        self.assertFalse(c.action_result("schedule_propose", "k" * 20, "prepared")["verified"])
        self.assertTrue(c.action_result("draft_edit", "k" * 20, "applied", verified=True)["verified"])

    def test_public_artifact_hides_server_only_manifest_and_untrusted_source(self):
        record = {"artifactId": UUID, "conversationId": UUID, "messageId": None, "runId": UUID, "revision": 0, "generationAttemptId": UUID,
                  "generationState": "streaming", "validationState": "pending", "canonicalSource": "root = RafiiRoot([])", "principal": UUID,
                  "manifest": {"principal": UUID, "actionTargets": {"x": 1}}, "safeState": None}
        public = c.public_artifact(record)
        self.assertEqual(set(public), set(c.PUBLIC_ARTIFACT_KEYS))
        self.assertIsNone(public["canonicalSource"])
        self.assertNotIn("principal", json.dumps(public))

    def test_unknown_is_not_zero(self):
        result = c.query_result("unavailable", data=0, note="Not connected")
        self.assertIsNone(result["data"])
        self.assertIsNone(result["coverage"]["known"])

    def test_state_machine(self):
        self.assertTrue(c.can_transition("streaming", "validating"))
        self.assertFalse(c.can_transition("ready", "streaming"))
        with self.assertRaises(AlphaError):
            c.require_transition("failed", "ready")


class LegacyAndKillSwitch(unittest.TestCase):
    def test_founder_handoff_uses_founder_flag_and_never_infers_privilege_from_result(self):
        env = {"RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_WORKSPACES": UUID}
        result = {"composedBy": "manager", "usage": {"billing": "metered"}, "founder": {"mode": "live"},
                  "toolActivity": [{"tool": "founder_cost_breakdown", "status": "verified"}]}
        cfg = config.RuntimeConfig.from_environment(env)
        self.assertFalse(service.ui_handoff(cfg, UUID, result, "Show costs", "text", scope="founder")["eligible"])
        cfg = config.RuntimeConfig.from_environment({**env, "RAFII_GENUI_FOUNDER_ENABLED": "1"})
        self.assertFalse(service.ui_handoff(cfg, UUID, result, "Show costs", "text")["eligible"])
        decided = service.ui_handoff(cfg, UUID, result, "Show costs", "text", scope="founder")
        self.assertEqual((decided["eligible"], decided["journeyIds"]), (True, ["J09"]))
        self.assertFalse(service.ui_handoff(cfg, "7d2f2f3e-1111-4222-8333-944455556666", result, "Show costs", "text", scope="founder")["eligible"])

    def test_legacy_answer_without_artifact_stays_native(self):
        cfg = config.RuntimeConfig.from_environment({})
        self.assertEqual(service.ui_handoff(cfg, UUID, {"answerText": "hi"}, "hi", "text")["eligible"], False)
        self.assertEqual(cfg.genui_for(UUID)["enabled"], False)
        self.assertEqual(service.ui_turn_context(cfg, None, UUID, UUID, None, {"artifactId": UUID}), (None, None))

    def test_canary_allowlist_narrows(self):
        cfg = config.RuntimeConfig.from_environment({"RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_ACTIONS_ENABLED": "1",
                                                     "RAFII_GENUI_WORKSPACES": UUID.upper()})
        self.assertTrue(cfg.genui_for(UUID)["actions"])
        self.assertFalse(cfg.genui_for("7d2f2f3e-1111-4222-8333-944455556666")["enabled"])
        self.assertFalse(cfg.genui_for(UUID, founder=True)["enabled"])

    def test_malformed_ui_context_never_fails_a_turn(self):
        cfg = config.RuntimeConfig.from_environment({"RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_V2_ENABLED": "1"})
        self.assertEqual(service.ui_turn_context(cfg, None, UUID, UUID, None, {"artifactId": "x", "evil": 1}), (None, None))
        self.assertIsNone(service.voice_choice({"voiceMode": 5, "voiceSourceIds": "x"}))


class Framing(unittest.TestCase):
    def test_event_ids_round_trip(self):
        self.assertEqual(c.parse_event_id(c.event_id(UUID, 42)), 42)
        self.assertIsNone(c.parse_event_id("garbage"))
        frame = c.sse_frame(c.make_event(UUID, None, 0, 1, "ui.heartbeat")).decode()
        self.assertTrue(frame.endswith("\n\n"))
        self.assertEqual(frame.count("\ndata: "), 1)
        with self.assertRaises(ValueError):
            c.make_event(UUID, None, 0, 1, "ui.executed")


if __name__ == "__main__":
    unittest.main()
