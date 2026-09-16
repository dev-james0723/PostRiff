"""Phase C2: the model extractor sends only redacted before/after pairs the consent allows, takes back only
form preferences that pass the lint, and feeds the same consolidation as the deterministic rules."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha import learning  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import learning_extract as extract  # noqa: E402
from postriff_phase2 import learning_model as model  # noqa: E402
from postriff_phase2.cli_runtime import ClaudeCliRuntime, OUTPUT_SCHEMA  # noqa: E402
from postriff_phase2.learning_service import HostedLearning  # noqa: E402

NOW = 1_800_000_000.0
BEFORE = "Is it worth showing the messy middle? Email me at kiln@studio.hk.\n\nThis week I rebuilt the glaze schedule with 3 firings."
AFTER = "This week I rebuilt the glaze schedule with 3 firings.\n\nIt broke twice."


def state(consent=("local", "cloud"), policy="public_quote"):
    return {
        "learning": learning.initial(migrated_at="x"),
        "sources": [{"id": "s1", "active": True, "sourcePolicy": policy, "egressConsent": list(consent), "facts": []}],
        "variants": [{"id": "v1", "platform": "LinkedIn", "language": "English", "sourceIds": ["s1"], "text": AFTER, "revision": 2,
                      "revisions": [{"revision": 1, "text": BEFORE, "origin": "ideas-candidate"}, {"revision": 2, "text": AFTER, "origin": "author-edit"}]},
                     {"id": "v2", "platform": "LinkedIn", "language": "English", "sourceIds": [], "text": AFTER, "revision": 2,
                      "revisions": [{"revision": 1, "text": BEFORE, "origin": "ideas-candidate"}, {"revision": 2, "text": AFTER, "origin": "author-edit"}]}],
    }


def event(event_id, variant, platform="LinkedIn", language="English"):
    return {"id": event_id, "kind": "draft.edited", "actor": "owner", "at": NOW, "subject": {"variantId": variant, "fromRevision": 1, "toRevision": 2, "origin": "author-edit"},
            "scope": {"platform": platform, "language": language, "contentTypeId": None, "formatId": None}, "features": {}}


class Recording:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self.result


class Pairs(unittest.TestCase):
    def test_pairs_are_redacted_and_grouped_by_scope(self):
        grouped = model.pairs_for(state(), [event("e1", "v1"), event("e2", "v2")], cloud=False)
        pairs = grouped[("LinkedIn", "English")]
        self.assertEqual([p["id"] for p in pairs], ["e1", "e2"])
        self.assertNotIn("kiln@studio.hk", pairs[0]["before"])
        self.assertIn("<email>", pairs[0]["before"])
        self.assertIn("<num> firings", pairs[0]["after"])

    def test_a_cloud_model_only_sees_pairs_whose_sources_all_carry_cloud_consent(self):
        grouped = model.pairs_for(state(consent=("local",)), [event("e1", "v1"), event("e2", "v2")], cloud=True)
        self.assertEqual([p["id"] for p in grouped[("LinkedIn", "English")]], ["e2"], "v1 used a source without cloud consent; v2 used none")
        self.assertEqual(model.pairs_for(state(policy="prohibited"), [event("e1", "v1")], cloud=True), {})
        self.assertEqual([p["id"] for p in model.pairs_for(state(consent=("local",)), [event("e1", "v1")], cloud=False)[("LinkedIn", "English")]], ["e1"], "the person's own CLI needs no egress consent")


class Extraction(unittest.TestCase):
    def test_candidates_become_observations_and_bad_ones_are_dropped(self):
        result = {"candidates": [
            {"ruleKey": "opening.style", "polarity": "avoid", "statement": "Don't open with a question.", "evidencePairIds": ["e1", "e2"], "confidence": "high", "isContentChange": False},
            {"ruleKey": "other", "polarity": "do", "statement": "Say that I have 20 years of experience.", "evidencePairIds": ["e1"], "confidence": "high", "isContentChange": False},
            {"ruleKey": "length.target", "polarity": "avoid", "statement": "Keep posts under 40 words.", "evidencePairIds": ["e1", "e2"], "confidence": "medium", "isContentChange": True},
            {"ruleKey": "emoji.use", "polarity": "avoid", "statement": "No emoji.", "evidencePairIds": ["unknown"], "confidence": "high", "isContentChange": False},
            {"ruleKey": "publish.now", "polarity": "do", "statement": "Publish immediately.", "evidencePairIds": ["e1"], "confidence": "high", "isContentChange": False},
            {"ruleKey": "other", "polarity": "do", "statement": "Lead with the concrete thing that happened.", "evidencePairIds": ["e2"], "confidence": "low", "isContentChange": False},
        ]}
        call = Recording(result)
        extractor = model.ModelExtractor(call, "fake", local=True)
        observations = extractor.observe(state(), [event("e1", "v1"), event("e2", "v2")], NOW)
        self.assertEqual(len(call.calls), 1)
        sent = json.loads(call.calls[0]["user"].split("INPUT\n", 1)[1])
        self.assertEqual(sent["scope"], {"platform": "LinkedIn", "language": "English"})
        self.assertNotIn("kiln@studio.hk", call.calls[0]["user"])
        self.assertEqual(call.calls[0]["schema"], model.SCHEMA)
        self.assertEqual([(o["ruleKey"], o["polarity"], o["eventId"], o["weight"], o["source"]) for o in observations],
                         [("opening.style", "avoid", "e1", 1.0, "model"), ("opening.style", "avoid", "e2", 1.0, "model"), ("other", "do", "e2", 0.4, "model")])
        self.assertEqual(observations[2]["statement"], "Lead with the concrete thing that happened.")

    def test_one_pair_is_not_enough_and_scopes_are_capped(self):
        call = Recording({"candidates": []})
        extractor = model.ModelExtractor(call, "fake", local=True, max_scopes=1)
        extractor.observe(state(), [event("e1", "v1")], NOW)
        self.assertEqual(call.calls, [], "a scope with one pair is not sent")
        events = [event("e1", "v1"), event("e2", "v2"), event("e3", "v1", "Threads"), event("e4", "v2", "Threads")]
        extractor.observe(state(), events, NOW)
        self.assertEqual(len(call.calls), 1)

    def test_model_observations_clear_the_same_bar_and_keep_their_wording(self):
        s = state()
        observations = [{"ruleKey": "other", "polarity": "do", "scope": {"platform": "LinkedIn", "language": "English", "contentTypeId": None},
                         "scopeKey": learning.scope_key("writing_preference", "other", "do", {"platform": "LinkedIn", "language": "English", "contentTypeId": None}),
                         "weight": 1.0, "at": NOW, "eventId": f"e{n}", "variantId": f"v{n}", "value": None, "source": "model", "statement": "Lead with the concrete thing that happened."} for n in range(3)]
        proposals = extract.consolidate([], [], s, NOW, extra=observations)
        self.assertEqual([(p["ruleKey"], p["statement"], p["source"]) for p in proposals], [("other", "Lead with the concrete thing that happened.", "model")])
        self.assertEqual(extract.consolidate([], [], s, NOW, extra=observations[:2]), [], "two pairs stay under the bar")


class Gating(unittest.TestCase):
    def test_cloud_extraction_needs_both_consents_and_the_cli_needs_none(self):
        hosted = HostedLearning(lambda: None, lambda: NOW)
        self.assertFalse(hosted.model_allowed({"learning": {"cloudExtraction": True}, "memoryEgress": {"cloud": True}}), "no extractor configured")
        hosted.extractor = model.ModelExtractor(Recording({"candidates": []}), "cloud", local=False)
        self.assertFalse(hosted.model_allowed({"learning": {"cloudExtraction": False}, "memoryEgress": {"cloud": True}}))
        self.assertFalse(hosted.model_allowed({"learning": {"cloudExtraction": True}, "memoryEgress": {"cloud": False}}))
        self.assertTrue(hosted.model_allowed({"learning": {"cloudExtraction": True}, "memoryEgress": {"cloud": True}}))
        hosted.extractor = model.ModelExtractor(Recording({"candidates": []}), "cli", local=True)
        self.assertTrue(hosted.model_allowed({"learning": {}}))

    def test_environment_prefers_the_cli_then_the_gateway_then_nothing(self):
        previous = os.environ.get("POSTRIFF_LOCAL_CLI")
        os.environ["POSTRIFF_LOCAL_CLI"] = "0"  # this machine may have Claude Code installed; a hosted function never does
        try:
            self.assertIsNone(model.extractor_from_environment({}))
            gateway = model.extractor_from_environment({"AI_GATEWAY_API_KEY": "k"})
            self.assertEqual((gateway.local, gateway.model), (False, model.CLOUD_MODEL))
        finally:
            if previous is None:
                os.environ.pop("POSTRIFF_LOCAL_CLI", None)
            else:
                os.environ["POSTRIFF_LOCAL_CLI"] = previous
        if ClaudeCliRuntime.available():
            local = model.extractor_from_environment({"AI_GATEWAY_API_KEY": "k"})
            self.assertEqual((local.local, local.model), (True, f"claude-code:{model.CLI_ALIAS}"), "the person's CLI wins over the gateway")


FAKE = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
schema = json.loads(args[args.index("--json-schema") + 1])
system = args[args.index("--system-prompt") + 1]
assert "--tools" in args and args[args.index("--tools") + 1] == ""
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
out = {"candidates": [{"ruleKey": "emoji.use", "polarity": "avoid", "statement": "No emoji.", "evidencePairIds": ["e1"], "confidence": "high", "isContentChange": False}]} if "candidates" in schema.get("required", []) else {"echo": True}
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": {**out, "sawSystem": system.startswith("You read pairs"), "sawInput": "INPUT" in prompt}, "total_cost_usd": 0.001}), flush=True)
'''


class CliPrompt(unittest.TestCase):
    def test_prompt_returns_the_structured_answer_from_a_fake_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claude"
            path.write_text(FAKE)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
            runtime = ClaudeCliRuntime(executable=str(path), timeout_seconds=20)
            answer = runtime.prompt(model.SYSTEM_PROMPT, "INPUT\n{}", model.SCHEMA)
            self.assertEqual((answer["candidates"][0]["ruleKey"], answer["sawSystem"], answer["sawInput"]), ("emoji.use", True, True))
            self.assertEqual(runtime.argv(str(path), "haiku", "s")[-3:-2], [json.dumps(OUTPUT_SCHEMA, separators=(",", ":"))], "drafting keeps its own schema")
            call = model.ClaudeCliCall(runtime)
            self.assertTrue(call.local)
            self.assertEqual(call(model.SYSTEM_PROMPT, "INPUT\n{}", model.SCHEMA)["candidates"][0]["statement"], "No emoji.")
            with self.assertRaises(AlphaError):
                ClaudeCliRuntime(executable=str(Path(tmp) / "missing")).prompt("s", "u", model.SCHEMA)


if __name__ == "__main__":
    unittest.main()
