"""Codex CLI as a content-only route: flags, detection, JSON event parsing, structured output, failure
classification. Uses a fake `codex` executable; never the real CLI."""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.codex_runtime import MODEL_PREFIX, CodexCliRuntime, classify_failure  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("codex-cli 0.154.0"); raise SystemExit(0)
if args[:2] == ["login", "status"]:
    if os.environ.get("FAKE_LOGGED_IN", "1") == "1":
        print("Logged in using ChatGPT"); raise SystemExit(0)
    print("Not logged in", file=sys.stderr); raise SystemExit(1)
mode = os.environ.get("FAKE_MODE", "ok")
assert args[0] == "exec" and "--json" in args and "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only"
schema = json.load(open(args[args.index("--output-schema") + 1]))
assert schema["required"] == ["variants", "warnings"]
prompt = sys.stdin.read()
def out(obj): print(json.dumps(obj), flush=True)
out({"type": "thread.started", "thread_id": "t1"})
out({"type": "turn.started"})
if mode == "auth":
    out({"type": "error", "message": "Unauthorized: not logged in. Run codex login."})
    out({"type": "turn.failed", "error": {"message": "unauthorized"}}); raise SystemExit(1)
if mode == "usage":
    out({"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "You've hit your usage limit."}})
    out({"type": "error", "message": "You've hit your usage limit."})
    out({"type": "turn.failed", "error": {"message": "usage limit"}}); raise SystemExit(1)
data = json.loads(prompt.rsplit("\nINPUT\n", 1)[-1])
variants = [{"platform": d["platform"], "language": d["language"], "text": "Codex draft for " + d["platform"], "sourceIds": [], "unknowns": [], "notes": "Plain opening."} for d in data["destinations"]]
text = json.dumps({"variants": variants, "warnings": []}) if mode != "prose" else "Sorry, here is prose."
out({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": text}})
out({"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 120}})
'''


class Sink:
    def __init__(self):
        self.events, self.completed, self.failed = [], None, None
        self.done = threading.Event()

    def cancelled(self):
        return False

    def emit(self, event):
        self.events.append(event)
        return True

    def complete(self, artifact, usage):
        self.completed = (artifact, usage)
        self.done.set()

    def fail(self, message):
        self.failed = message
        self.done.set()


def request():
    return {"model": MODEL_PREFIX + "default", "idea": "Say something about onboarding.", "tone": "warm", "reasoning": "quick",
            "destinations": [{"platform": "LinkedIn", "language": "English"}, {"platform": "Threads", "language": "English"}],
            "context": {"sources": [], "candidateOnly": False, "excluded": []}, "memory": [], "skills": {"bindings": [], "text": "", "warnings": []}}


class CodexCliRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = Path(self.tmp.name) / "codex"
        self.fake.write_text(FAKE)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp.name, "LANG": "en_US.UTF-8", "TMPDIR": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self, mode="ok", logged_in=True):
        return CodexCliRuntime(executable=str(self.fake), timeout_seconds=20, env={**self.env, "FAKE_MODE": mode, "FAKE_LOGGED_IN": "1" if logged_in else "0"})

    def run_to_end(self, runtime):
        sink = Sink()
        runtime.dispatch("run-1", request(), sink)
        self.assertTrue(sink.done.wait(25))
        return sink

    def test_detection_and_catalog(self):
        info = self.runtime().detect()
        self.assertEqual((info["id"], info["installed"], info["version"], info["authStatus"], info["authMethod"]), ("codex", True, "0.154.0", "ok", "chatgpt"))
        models = self.runtime().list_supported_models()
        self.assertEqual([m["id"] for m in models], [MODEL_PREFIX + "default"])
        self.assertTrue(models[0]["qualified"] and models[0]["route"] == "codex")
        out = self.runtime(logged_in=False)
        self.assertEqual(out.detect()["authStatus"], "missing")
        self.assertIn("codex login", out.detect()["guidance"])
        self.assertFalse(out.list_supported_models()[0]["qualified"])

    def test_argv_is_read_only_ephemeral_and_rejects_unknown_models(self):
        runtime = self.runtime()
        args = runtime.argv("/bin/codex", "default", "/tmp/w")
        self.assertEqual(args[:3], ["/bin/codex", "exec", "--json"])
        for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--sandbox", "--output-schema", "-C"):
            self.assertIn(flag, args)
        self.assertEqual(args[-1], "-")
        self.assertNotIn("-m", args)
        with self.assertRaises(AlphaError):
            runtime.argv("/bin/codex", "gpt-9", "/tmp/w")
        with self.assertRaises(AlphaError):
            CodexCliRuntime.alias_of(MODEL_PREFIX + "o3")

    def test_success_parses_the_final_agent_message_as_the_candidate(self):
        sink = self.run_to_end(self.runtime())
        self.assertIsNone(sink.failed)
        kinds = [e["type"] for e in sink.events]
        self.assertEqual((kinds[0], kinds[-1]), ("progress.updated", "message.completed"))
        self.assertIn("message.delta", kinds)
        artifact, usage = sink.completed
        self.assertEqual([v["text"] for v in artifact["variants"]], ["Codex draft for LinkedIn", "Codex draft for Threads"])
        self.assertIn("Plain opening.", artifact["variants"][0]["warnings"])
        self.assertIn("Written by Codex", artifact["variants"][0]["warnings"][0])
        self.assertEqual((usage["billing"], usage["costUsd"], usage["tokens"]["output_tokens"]), ("subscription", 0, 120))

    def test_usage_limit_is_classified_with_guidance(self):
        sink = self.run_to_end(self.runtime(mode="usage"))
        self.assertIn("usage limit", sink.failed)
        self.assertEqual(classify_failure("Not logged in")[0], "auth")
        self.assertEqual(classify_failure("boom")[0], "failed")

    def test_a_refused_run_flips_readiness_until_a_rescan(self):
        runtime = self.runtime(mode="auth")
        self.assertEqual(runtime.detect()["authStatus"], "ok")
        sink = self.run_to_end(runtime)
        self.assertIn("codex login", sink.failed)
        self.assertEqual(runtime.detect()["authStatus"], "expired")
        self.assertIn("codex login", runtime.detect()["guidance"])
        self.assertFalse(runtime.list_supported_models()[0]["qualified"])
        self.assertEqual(runtime.detect(force=True)["authStatus"], "ok")

    def test_prose_instead_of_schema_fails_closed(self):
        self.assertIn("no structured candidate", self.run_to_end(self.runtime(mode="prose")).failed)

    def test_prompt_carries_policy_input_and_skills(self):
        runtime = self.runtime()
        req = request()
        req["skills"] = {"bindings": [{"id": "postriff-content-craft"}], "text": "## Skill: postriff-content-craft (v1)\nConcrete opening.", "warnings": []}
        system, user = runtime.compose(req)
        self.assertIn("SKILLS", system)
        self.assertIn("Concrete opening.", system)
        self.assertTrue(user.startswith("INPUT\n"))


if __name__ == "__main__":
    unittest.main()
