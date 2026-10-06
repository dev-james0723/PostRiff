"""Synthetic metadata fixtures only: no source logs, Git, gh or models run."""

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from agent_team.evidence_sources import (
    ClaudeMetadataConfig, GitMetadataConfig, MetadataBlocked, MetadataLimits,
    TokenPilotMetadataConfig, read_claude_metadata, read_git_metadata,
    read_token_pilot_metadata,
)

OBSERVED = "2026-10-05T11:00:00Z"
STAMP = "2026-10-05T10:59:00Z"
HEAD = "a" * 40
PRIVATE = "PRIVATE_SENTINEL sk-syntheticprivate123456 /Users/private-account/private-file"


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write(self, path, value, *, jsonl=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "".join(json.dumps(row) + "\n" for row in value) if jsonl else json.dumps(value)
        path.write_text(raw, encoding="utf-8")
        timestamp = datetime.fromisoformat(STAMP.replace("Z", "+00:00")).timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def assert_redacted(self, batch):
        raw = json.dumps(batch.as_dict())
        self.assertNotIn("PRIVATE_SENTINEL", raw)
        self.assertNotIn("sk-synthetic", raw)
        self.assertNotIn(str(self.root), raw)
        self.assertFalse(batch.daily_coverage_complete)
        self.assertEqual(batch.as_dict()["writerOwnership"], "unproven")


class ClaudeMetadataTests(FixtureTests):
    def config(self, rows, **changes):
        path = self.write(self.root / "one-approved.jsonl", rows, jsonl=True)
        return replace(ClaudeMetadataConfig(path, path, self.root, self.root, "approved-project", "session-one"), **changes)

    def row(self, kind, **values):
        return {"type": kind, "sessionId": "session-one", "cwd": str(self.root),
                "timestamp": STAMP, "uuid": "event-" + kind, **values}

    def test_raw_content_tool_reasoning_and_model_are_never_exported(self):
        rows = [self.row("system", subtype="init", apiKey=PRIVATE),
                self.row("progress", data={"type": "bash_progress", "output": PRIVATE, "command": PRIVATE}),
                self.row("user", message={"content": PRIVATE}),
                self.row("assistant", message={"id": "private-message", "model": PRIVATE,
                    "content": [{"type": "thinking", "thinking": PRIVATE}, {"type": "tool_use", "input": PRIVATE}],
                    "usage": {"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 4}})]
        config = self.config(rows)
        before = hashlib.sha256(config.log_path.read_bytes()).hexdigest()
        batch = read_claude_metadata(config, observed_at=OBSERVED)
        self.assertEqual(batch.status, "ok")
        self.assertEqual(len(batch.events), 5)
        self.assertEqual(next(event.payload["count"] for event in batch.events if event.payload["kind"] == "claude_usage_input_tokens"), 12)
        self.assertEqual(before, hashlib.sha256(config.log_path.read_bytes()).hexdigest())
        self.assert_redacted(batch)

    def test_header_binding_is_required_for_missing_cwd_and_exact_session(self):
        header = self.row("system", subtype="init")
        usage = self.row("assistant", message={"usage": {"output_tokens": 8}})
        usage.pop("cwd")
        config = self.config([header, usage])
        self.assertEqual(len(read_claude_metadata(config, observed_at=OBSERVED).events), 2)
        config = self.config([usage])
        batch = read_claude_metadata(config, observed_at=OBSERVED)
        self.assertEqual(batch.events, ())
        self.assertIn("claude_workspace_or_session_mismatch", batch.gaps)
        config = self.config([header, self.row("progress", sessionId="other-session", data={"type": "agent_progress"})])
        self.assertEqual(len(read_claude_metadata(config, observed_at=OBSERVED).events), 1)

    def test_tail_line_event_limits_partial_records_and_duplicates_are_visible(self):
        row = self.row("assistant", message={"id": "same-message", "usage": {"input_tokens": 1, "output_tokens": 2}})
        config = self.config([row, row])
        batch = read_claude_metadata(config, observed_at=OBSERVED)
        self.assertEqual(len(batch.events), 2)
        limited = read_claude_metadata(replace(config, limits=MetadataLimits(max_events=1)), observed_at=OBSERVED)
        self.assertEqual(len(limited.events), 1)
        self.assertIn("event_limit", limited.gaps)
        with config.log_path.open("ab") as stream:
            stream.write(b'{"private":"unfinished')
        batch = read_claude_metadata(config, observed_at=OBSERVED)
        self.assertIn("incomplete_jsonl_tail", batch.gaps)
        self.assertNotIn("unfinished", json.dumps(batch.as_dict()))
        config = self.config([row] * 20, limits=MetadataLimits(max_tail_bytes=256, max_lines=1))
        batch = read_claude_metadata(config, observed_at=OBSERVED)
        self.assertIn("tail_window_only", batch.gaps)
        self.assertLessEqual(batch.scanned, 1)

    def test_paths_missing_sources_schema_drift_and_counter_types_fail_safely(self):
        config = self.config([self.row("assistant", message={"usage": {"input_tokens": True, "output_tokens": -1}})])
        batch = read_claude_metadata(config, observed_at=OBSERVED)
        self.assertEqual(batch.events, ())
        self.assertIn("claude_usage_counter_invalid", batch.gaps)
        self.assertEqual(read_claude_metadata(replace(config, allowed_log_path=self.root / "other"), observed_at=OBSERVED).status, "unavailable")
        config.log_path.unlink()
        self.assertEqual(read_claude_metadata(config, observed_at=OBSERVED).status, "not_connected")
        other = self.write(self.root / "other.jsonl", [self.row("system", subtype="init")], jsonl=True)
        config.log_path.symlink_to(other)
        self.assertEqual(read_claude_metadata(config, observed_at=OBSERVED).gaps, ("path_not_registered",))


class FakeGitRunner:
    def __init__(self, root, *, status=b" M private-file\0", ci=None, deployments=None, fail_gh=False):
        self.root, self.status, self.ci, self.deployments, self.fail_gh = root, status, ci, deployments, fail_gh
        self.calls = []

    def __call__(self, argv, **options):
        self.calls.append((argv, options))
        if argv[0] == "/usr/bin/git":
            if argv[-1] == "--show-toplevel":
                return (str(self.root) + "\n").encode()
            if argv[-1] == "HEAD":
                return (HEAD + "\n").encode()
            if "status" in argv:
                return self.status
            raise AssertionError("unexpected Git operation")
        if self.fail_gh:
            raise MetadataBlocked("cli_timeout")
        endpoint = argv[6]
        if "/actions/runs?" in endpoint:
            return json.dumps(self.ci if self.ci is not None else []).encode()
        if "/statuses?" in endpoint:
            return b"[]"
        if "/deployments?" in endpoint:
            return json.dumps(self.deployments if self.deployments is not None else []).encode()
        raise AssertionError("unexpected remote operation")


class GitMetadataTests(FixtureTests):
    def config(self, **changes):
        return replace(GitMetadataConfig(self.root, self.root, "approved-project"), **changes)

    def test_fixed_read_only_git_snapshot_revision_and_redaction(self):
        runner = FakeGitRunner(self.root)
        batch = read_git_metadata(self.config(), observed_at=OBSERVED, runner=runner)
        again = read_git_metadata(self.config(), observed_at=OBSERVED, runner=FakeGitRunner(self.root))
        self.assertEqual(batch.source_revision, again.source_revision)
        self.assertEqual(batch.events[0].key, again.events[0].key)
        self.assertEqual(batch.metadata["unstagedChanges"], 1)
        self.assertEqual(batch.metadata["headSha"], HEAD)
        self.assertIn("untracked_files_not_scanned", batch.gaps)
        for argv, options in runner.calls:
            self.assertEqual(argv[0], "/usr/bin/git")
            self.assertIn("core.fsmonitor=false", argv)
            self.assertEqual(options["env"]["GIT_OPTIONAL_LOCKS"], "0")
            self.assertNotIn("HOME", options["env"])
            self.assertLessEqual(options["timeout_seconds"], 2)
        self.assert_redacted(batch)

    def test_no_remote_calls_without_explicit_authority_and_exact_root(self):
        runner = FakeGitRunner(self.root)
        batch = read_git_metadata(self.config(ci=True, deployments=True), observed_at=OBSERVED, runner=runner)
        self.assertEqual(len(runner.calls), 3)
        self.assertIn("gh_metadata_not_authorized", batch.gaps)
        runner = FakeGitRunner(self.root)
        batch = read_git_metadata(self.config(registered_root=self.root / "other"), observed_at=OBSERVED, runner=runner)
        self.assertEqual(batch.status, "unavailable")
        self.assertEqual(runner.calls, [])

    def test_ci_and_deployment_metadata_preserve_uncertain_states(self):
        gh = self.root / "approved-gh"
        rows = [{"id": 10, "status": "in_progress", "conclusion": None, "head_sha": HEAD,
                 "updated_at": STAMP, "name": PRIVATE, "html_url": "https://github.com/private?token=secret"},
                {"id": 11, "status": "completed", "conclusion": "success", "head_sha": "b" * 40, "updated_at": STAMP}]
        config = self.config(gh_binary=gh, allowed_gh_binary=gh, repository="approved-owner/project",
                             gh_authorized=True, ci=True, deployments=True)
        runner = FakeGitRunner(self.root, ci=rows, deployments=[{"id": 20, "sha": HEAD, "updated_at": STAMP, "environment": PRIVATE}])
        batch = read_git_metadata(config, observed_at=OBSERVED, runner=runner)
        self.assertEqual(len(batch.events), 3)
        ci = next(event for event in batch.events if event.payload["kind"] == "ci_metadata")
        self.assertEqual(ci.payload["status"], "in_progress")
        self.assertEqual(ci.payload["reportedState"], "conclusion_unknown")
        deployment = next(event for event in batch.events if event.payload["kind"] == "deployment_metadata")
        self.assertEqual(deployment.payload["status"], "status_unknown")
        self.assertIn("gh_ci_record_invalid", batch.gaps)
        self.assertIn("gh_deployment_status_unknown", batch.gaps)
        self.assertFalse(batch.metadata["deploymentReadinessVerified"])
        for argv, _ in runner.calls[3:]:
            self.assertEqual(argv[1:6], ("api", "--hostname", "github.com", "--method", "GET"))
            self.assertNotIn("dispatch", " ".join(argv))
        self.assert_redacted(batch)

    def test_remote_failure_preserves_local_evidence_and_bad_status_fails_closed(self):
        gh = self.root / "approved-gh"
        config = self.config(gh_binary=gh, allowed_gh_binary=gh, repository="owner/repo", gh_authorized=True, ci=True)
        batch = read_git_metadata(config, observed_at=OBSERVED, runner=FakeGitRunner(self.root, fail_gh=True))
        self.assertEqual(len(batch.events), 1)
        self.assertIn("gh_metadata_unavailable", batch.gaps)
        batch = read_git_metadata(self.config(), observed_at=OBSERVED, runner=FakeGitRunner(self.root, status=b"?? private-path\0"))
        self.assertEqual(batch.status, "unavailable")
        self.assertEqual(batch.events, ())
        def secret_error(*args, **kwargs):
            raise MetadataBlocked(PRIVATE)
        batch = read_git_metadata(self.config(), observed_at=OBSERVED, runner=secret_error)
        self.assertEqual(batch.gaps, ("metadata_source_unavailable",))
        self.assert_redacted(batch)


class TokenPilotMetadataTests(FixtureTests):
    def config(self, *, report=None, revision=4):
        self.write(self.root / ".token-pilot/install.json", {"schema_version": 2, "version": "3.8.0", "root": str(self.root), "files": {}, "hooks": PRIVATE})
        self.write(self.root / ".token-pilot/state.json", {"schema_version": 2, "project": str(self.root), "revision": revision,
            "entries": {"one": {"text": PRIVATE}}, "sessions": {"approved-session": {"status": "active", "task": PRIVATE,
            "transcript_path": "/Users/private-account/never-open", "usage_analysis": {"estimated_usage": PRIVATE}}}})
        config = TokenPilotMetadataConfig(self.root, self.root, "approved-project")
        if report is not None:
            name = hashlib.sha256(b"approved-session").hexdigest()[:24] + ".json"
            path = self.write(self.root / ".token-pilot/reports" / name, report)
            config = replace(config, report_path=path, allowed_report_path=path, session_id="approved-session")
        return config

    def test_existing_registered_state_is_read_only_and_budget_remains_unknown(self):
        config = self.config()
        state = self.root / ".token-pilot/state.json"
        before = hashlib.sha256(state.read_bytes()).hexdigest()
        batch = read_token_pilot_metadata(config, observed_at=OBSERVED)
        self.assertEqual(batch.status, "partial")
        self.assertEqual(batch.metadata["stateRevision"], 4)
        self.assertEqual(batch.metadata["sessionStatuses"], {"active": 1})
        self.assertIsNone(batch.metadata["budgetRemainingTokens"])
        self.assertIsNone(batch.metadata["observedIntervalTokens"])
        self.assertIn("budget_unknown", batch.gaps)
        self.assertEqual(before, hashlib.sha256(state.read_bytes()).hexdigest())
        self.assert_redacted(batch)

    def test_only_exact_bound_current_observed_receipt_can_expose_counter(self):
        report = {"version": "3.8.0", "session_id": "approved-session", "memory_revision": 4,
                  "observed_interval_tokens": 24, "receipt": {"with_pilot_measurement": "observed", "actual_tokens": 24}, "task": PRIVATE}
        config = self.config(report=report)
        batch = read_token_pilot_metadata(config, observed_at=OBSERVED)
        self.assertEqual(batch.metadata["observedIntervalTokens"], 24)
        self.assertEqual(len(batch.events), 2)
        self.assert_redacted(batch)
        report["receipt"]["with_pilot_measurement"] = "estimated"
        config = self.config(report=report)
        batch = read_token_pilot_metadata(config, observed_at=OBSERVED)
        self.assertIsNone(batch.metadata["observedIntervalTokens"])
        self.assertIn("token_pilot_usage_receipt_unavailable", batch.gaps)
        report["receipt"]["with_pilot_measurement"] = "observed"
        report["memory_revision"] = 3
        batch = read_token_pilot_metadata(self.config(report=report), observed_at=OBSERVED)
        self.assertEqual(len(batch.events), 1)
        self.assertIsNone(batch.metadata["observedIntervalTokens"])

    def test_missing_registration_foreign_schema_future_and_stale_sources_visible(self):
        config = self.config()
        install = self.root / ".token-pilot/install.json"
        install.unlink()
        self.assertEqual(read_token_pilot_metadata(config, observed_at=OBSERVED).status, "not_connected")
        config = self.config()
        self.write(install, {"schema_version": 99, "root": str(self.root), "version": "3.8.0", "files": {}})
        self.assertEqual(read_token_pilot_metadata(config, observed_at=OBSERVED).gaps, ("token_pilot_registration_unsupported",))
        config = self.config()
        state = self.root / ".token-pilot/state.json"
        os.utime(state, (1, 1))
        batch = read_token_pilot_metadata(config, observed_at=OBSERVED)
        self.assertIn("source_stale", batch.gaps)
        self.assertFalse(batch.bounded_scan_complete)
        future = datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")).timestamp() + 60
        os.utime(state, (future, future))
        batch = read_token_pilot_metadata(config, observed_at=OBSERVED)
        self.assertIn("source_timestamp_unknown_or_future", batch.gaps)
        self.assertIsNone(batch.fresh_at)


if __name__ == "__main__":
    unittest.main()
