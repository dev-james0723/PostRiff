"""Claude Code as a content-only route (agent chat design §4.2): flags, environment, stream parsing,
structured output → artifact, failure classification, timeout, cancellation. Uses a fake `claude`
executable; never the real CLI."""
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import cli_runtime  # noqa: E402
from postriff_phase2.cli_runtime import ClaudeCliRuntime, MODEL_PREFIX, OUTPUT_SCHEMA, normalize_output, classify_failure, restricted_environment  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("9.9.9 (Claude Code)"); raise SystemExit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.environ.get("FAKE_LOGGED_IN", "1") == "1", "authMethod": "claude.ai"})); raise SystemExit(0)
mode = os.environ.get("FAKE_MODE", "ok")
prompt = sys.stdin.read()
def out(obj): print(json.dumps(obj), flush=True)
out({"type": "system", "subtype": "init", "model": "fake", "tools": [], "mcp_servers": [], "permissionMode": "dontAsk", "session_id": "s"})
if mode == "hang":
    time.sleep(30); raise SystemExit(0)
if mode == "retry":
    out({"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 3})
for piece in ("Hello ", "from ", "the fake ", "model."):
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}})
if mode == "auth":
    out({"type": "result", "subtype": "success", "is_error": True, "structured_output": None, "result": "Failed to authenticate. API Error: 401 OAuth access token has expired.", "total_cost_usd": 0, "duration_ms": 5})
    raise SystemExit(1)
if mode == "noschema":
    out({"type": "result", "subtype": "success", "is_error": False, "structured_output": None, "result": "prose", "total_cost_usd": 0.01, "duration_ms": 5}); raise SystemExit(0)
schema_index = args.index("--json-schema") + 1
schema = json.loads(args[schema_index])
assert schema["required"] == ["variants", "warnings"]
data = json.loads(prompt.split("INPUT", 1)[1])
variants = [{"platform": d["platform"], "language": d["language"], "text": ("Draft for " + d["platform"] + ". ") * (60 if mode == "long" else 1), "sourceIds": ["src-1", "not-allowed"], "unknowns": ["Launch date"], "notes": "Opened with the fact."} for d in data["destinations"]]
if mode == "missing":
    variants = variants[:1]
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}})
out({"type": "result", "subtype": "success", "is_error": False, "structured_output": {"variants": variants, "warnings": ["No external source was supplied."]}, "total_cost_usd": 0.0123, "duration_ms": 1200, "num_turns": 1, "usage": {"output_tokens": 42}})
'''


class Sink:
    def __init__(self, cancel_after=None):
        self.events, self.completed, self.failed, self.cancel_after = [], None, None, cancel_after
        self.done = threading.Event()

    def cancelled(self):
        return self.cancel_after is not None and len(self.events) >= self.cancel_after

    def emit(self, event):
        self.events.append(event)
        return True

    def complete(self, artifact, usage):
        self.completed = (artifact, usage)
        self.done.set()

    def fail(self, message):
        self.failed = message
        self.done.set()


def request(destinations=None):
    return {"model": MODEL_PREFIX + "sonnet", "idea": "Say something about onboarding.", "tone": "warm", "reasoning": "quick",
            "destinations": destinations or [{"platform": "LinkedIn", "language": "English"}, {"platform": "Threads", "language": "English"}],
            "context": {"sources": [{"id": "src-1", "title": "Own note", "policy": "public_quote", "facts": [{"id": "f1", "text": "We shipped onboarding v2."}]}], "candidateOnly": False, "excluded": []},
            "memory": [{"name": "VOICE.md", "body": "# Voice\nWarm, specific."}]}


class ClaudeCliRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = Path(self.tmp.name) / "claude"
        self.fake.write_text(FAKE)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp.name, "LANG": "en_US.UTF-8", "TMPDIR": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self, mode="ok", timeout=20, logged_in=True):
        env = {**self.env, "FAKE_MODE": mode, "FAKE_LOGGED_IN": "1" if logged_in else "0"}
        return ClaudeCliRuntime(executable=str(self.fake), timeout_seconds=timeout, budget_usd=0.25, env=env)

    def run_to_end(self, runtime, req=None, sink=None):
        sink = sink or Sink()
        runtime.dispatch("run-1", req or request(), sink)
        self.assertTrue(sink.done.wait(25), "run did not finish")
        return sink

    def test_environment_never_carries_keys_or_nested_session_markers(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        os.environ["CLAUDECODE"] = "1"
        try:
            env = restricted_environment()
        finally:
            del os.environ["ANTHROPIC_API_KEY"], os.environ["CLAUDECODE"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertTrue(set(env) <= {"HOME", "PATH", "LANG", "USER", "TMPDIR"})

    def test_argv_is_content_only_and_rejects_unknown_models(self):
        runtime = self.runtime()
        args = runtime.argv("/bin/claude", "sonnet", "SYSTEM")
        joined = " ".join(args)
        for flag in ("-p", "--output-format stream-json", "--include-partial-messages", "--tools ", "--setting-sources ", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--permission-mode dontAsk", "--max-budget-usd 0.25", "--json-schema", "--model sonnet"):
            self.assertIn(flag, joined)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertNotIn("--model", runtime.argv("/bin/claude", "default", "SYSTEM"))
        for bad in ("gpt-5", "sonnet;rm -rf /", "--dangerously-skip-permissions"):
            with self.assertRaises(AlphaError):
                runtime.argv("/bin/claude", bad, "SYSTEM")
        with self.assertRaises(AlphaError):
            runtime.alias_of(MODEL_PREFIX + "gpt")
        self.assertEqual(runtime.alias_of(None), "default")

    def test_detection_and_catalog(self):
        runtime = self.runtime()
        info = runtime.detect()
        self.assertEqual((info["installed"], info["version"], info["authStatus"], info["authMethod"]), (True, "9.9.9", "ok", "claude.ai"))
        self.assertNotIn("email", info)
        models = runtime.list_supported_models()
        self.assertEqual([m["id"] for m in models][:2], [MODEL_PREFIX + "default", MODEL_PREFIX + "fable"])
        self.assertTrue(all(m["qualified"] and m["costClass"] == "subscription" for m in models))
        signed_out = self.runtime(logged_in=False)
        self.assertEqual(signed_out.detect()["authStatus"], "missing")
        self.assertTrue(all(not m["qualified"] for m in signed_out.list_supported_models()))
        self.assertIn("claude auth login", signed_out.detect()["guidance"])
        self.assertFalse(ClaudeCliRuntime(executable=str(Path(self.tmp.name) / "missing"), env=self.env).detect()["installed"])

    def test_prompt_treats_memory_and_sources_as_data(self):
        system, user = self.runtime().compose(request())
        self.assertIn("MEMORY FILES", system)
        self.assertIn("Warm, specific.", system)
        self.assertTrue(user.startswith("INPUT\n"))
        payload = json.loads(user.split("INPUT\n", 1)[1])
        self.assertEqual(payload["approvedSources"][0]["facts"][0]["text"], "We shipped onboarding v2.")
        self.assertEqual(payload["destinations"][0]["characterLimit"], 3000)

    def test_successful_run_streams_then_completes_with_normalized_artifact(self):
        sink = self.run_to_end(self.runtime())
        kinds = [e["type"] for e in sink.events]
        self.assertEqual(kinds[0], "progress.updated")
        self.assertIn("message.delta", kinds)
        self.assertEqual(kinds[-1], "message.completed")
        self.assertEqual("".join(e["text"] for e in sink.events if e["type"] == "message.delta"), "Hello from the fake model.")
        artifact, usage = sink.completed
        self.assertEqual([v["platform"] for v in artifact["variants"]], ["LinkedIn", "Threads"])
        variant = artifact["variants"][0]
        self.assertEqual(variant["sourceIds"], ["src-1"])  # unknown ids dropped
        self.assertEqual(variant["unknowns"], ["Launch date"])
        self.assertIn("Written by Claude Code", variant["warnings"][0])
        self.assertIn("Opened with the fact.", variant["warnings"])
        self.assertIn("No external source was supplied.", variant["warnings"])
        self.assertEqual((usage["provenance"], usage["billing"], usage["costUsd"], usage["cliCostUsd"], usage["modelRequests"]), ("reported_by_cli", "subscription", 0, 0.0123, 1))
        self.assertIsNone(sink.failed)

    def test_over_limit_text_is_flagged_not_truncated(self):
        artifact, _ = self.run_to_end(self.runtime(mode="long")).completed
        threads = artifact["variants"][1]
        self.assertGreater(len(threads["text"]), 500)
        self.assertTrue(any("exceeds the Threads limit of 500" in w for w in threads["warnings"]))

    def test_missing_destination_and_missing_schema_fail_closed(self):
        self.assertIn("no Threads · English candidate", self.run_to_end(self.runtime(mode="missing")).failed)
        self.assertIn("no structured candidate", self.run_to_end(self.runtime(mode="noschema")).failed)

    def test_auth_failure_is_classified_with_guidance(self):
        sink = self.run_to_end(self.runtime(mode="auth"))
        self.assertIn("claude auth login", sink.failed)

    def test_a_refused_run_flips_readiness_until_a_rescan_or_a_good_run(self):
        runtime = self.runtime(mode="auth")
        self.assertEqual(runtime.detect()["authStatus"], "ok", "auth status alone cannot see an expired token")
        self.run_to_end(runtime)
        probe = runtime.detect()
        self.assertEqual(probe["authStatus"], "expired")
        self.assertIn("claude auth login", probe["guidance"])
        self.assertFalse(runtime.list_supported_models()[0]["qualified"])
        self.assertEqual(runtime.detect(force=True)["authStatus"], "ok", "a rescan gives the stored sign-in another chance")
        self.run_to_end(runtime)
        self.assertEqual(runtime.detect()["authStatus"], "expired")
        runtime.env["FAKE_MODE"] = "ok"
        self.run_to_end(runtime)
        self.assertEqual(runtime.detect()["authStatus"], "ok", "a completed run clears the flag")
        self.assertEqual(classify_failure("budget exceeded")[0], "budget")
        self.assertEqual(classify_failure("something else")[0], "failed")

    def test_retry_notice_is_surfaced(self):
        sink = self.run_to_end(self.runtime(mode="retry"))
        self.assertTrue(any(e["type"] == "warning.created" and "retried" in e["message"] for e in sink.events))

    def test_timeout_stops_a_silent_process(self):
        started = time.monotonic()
        sink = self.run_to_end(self.runtime(mode="hang", timeout=2))
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn("time limit", sink.failed)

    def test_cancellation_terminates_the_run(self):
        sink = self.run_to_end(self.runtime(mode="hang", timeout=10), sink=Sink(cancel_after=1))
        self.assertIn("Cancelled", sink.failed)

    def test_normalize_requires_every_destination_and_bounds_fields(self):
        with self.assertRaises(AlphaError):
            normalize_output({"variants": []}, request())
        artifact = normalize_output({"variants": [{"platform": "LinkedIn", "language": "English", "text": " x ", "sourceIds": ["src-1"], "unknowns": ["a"] * 20, "notes": ""}], "warnings": []}, request([{"platform": "LinkedIn", "language": "English"}]))
        self.assertEqual(len(artifact["variants"][0]["unknowns"]), 10)
        self.assertEqual(json.loads(json.dumps(OUTPUT_SCHEMA))["additionalProperties"], False)

    def test_availability_respects_kill_switch(self):
        os.environ[cli_runtime.ENABLE_ENV] = "0"
        try:
            self.assertFalse(ClaudeCliRuntime.available())
        finally:
            del os.environ[cli_runtime.ENABLE_ENV]


if __name__ == "__main__":
    unittest.main()
