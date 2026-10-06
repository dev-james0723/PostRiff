"""Synthetic fixture coverage; no personal source, network, model, or hook calls."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from agent_team.observers import (
    TYPELESS_HISTORY_V2_SCHEMA,
    TYPELESS_SCHEMA_SIGNATURE,
    ClaudeJsonlObserver,
    LuciObserver,
    SourceObservation,
    TypelessConfig,
    TypelessObserver,
    _run_bounded,
    schema_signature,
)


START = "2026-10-05T10:00:00Z"
END = "2026-10-05T11:00:00Z"
STAMP = "2026-10-05T10:30:00Z"


@contextmanager
def _database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class TypelessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "history.db"
        declarations = []
        for _, name, kind, required, default, primary in TYPELESS_HISTORY_V2_SCHEMA:
            declaration = f'"{name}" {kind}'
            if required:
                declaration += " NOT NULL"
            if default is not None:
                declaration += " DEFAULT " + default
            if primary:
                declaration += " PRIMARY KEY"
            declarations.append(declaration)
        with _database(self.db) as connection:
            connection.execute("CREATE TABLE history_v2 (" + ",".join(declarations) + ")")
        self.config = TypelessConfig(self.db, self.db, "2.8.0", allowed_audio_roots=(self.root,))
        self.observer = TypelessObserver(self.config)

    def insert(self, identity, *, text="synthetic spoken idea", status="pending", updated=STAMP,
               created=STAMP, audio=None, app_version="2.8.0"):
        with _database(self.db) as connection:
            connection.execute(
                "INSERT INTO history_v2 (id,status,refined_text,created_at,updated_at,audio_local_path,app_version) "
                "VALUES (?,?,?,?,?,?,?)", (identity, status, text, created, updated, audio, app_version))

    def poll(self, **kwargs):
        return self.observer.poll(start_at=START, end_at=END, **kwargs)

    def test_exact_schema_hash_and_read_only_source(self):
        self.insert("source-1")
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with _database(self.db) as connection:
            self.assertEqual(schema_signature(connection.execute("PRAGMA table_info(history_v2)").fetchall()),
                             TYPELESS_SCHEMA_SIGNATURE)
        batch = self.poll()
        self.assertEqual(batch.status, "ok")
        self.assertEqual(len(batch.observations), 1)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(self.db) + "-journal").exists())
        self.assertFalse(Path(str(self.db) + "-wal").exists())
        self.assertIsNone(batch.observations[0].text)
        self.assertEqual(batch.observations[0].execution_authority, "none")

    def test_schema_drift_fails_closed(self):
        self.insert("source-1")
        with _database(self.db) as connection:
            connection.execute("ALTER TABLE history_v2 ADD COLUMN unexpected TEXT")
        batch = self.poll()
        self.assertEqual(batch.gaps, ("schema_mismatch",))
        self.assertEqual(batch.observations, ())
        self.assertFalse(batch.complete)

    def test_installed_and_row_version_gates(self):
        self.insert("source-1")
        bad = TypelessObserver(replace(self.config, installed_app_version="9.0.0"))
        self.assertEqual(bad.poll(start_at=START, end_at=END).gaps, ("app_version_mismatch",))
        with _database(self.db) as connection:
            connection.execute("UPDATE history_v2 SET app_version='9.0.0'")
        unknown = self.poll()
        self.assertEqual(unknown.gaps, ("record_app_version_unknown",))
        self.assertEqual(unknown.status, "partial")
        self.assertEqual(unknown.observations, ())
        self.assertIsNotNone(unknown.cursor)

    def test_verified_platform_alias_is_record_provenance(self):
        self.insert("source-1", app_version="mac_2.8.0")
        batch = self.poll()
        self.assertEqual(batch.status, "ok")
        self.assertEqual(batch.observations[0].metadata["app_version"], "mac_2.8.0")
        self.assertEqual(batch.observations[0].metadata["installed_app_version"], "2.8.0")
        self.assertEqual(batch.observations[0].metadata["app_version_provenance"], "history_record")

    def test_pending_completed_and_updated_content_emit_new_version(self):
        self.insert("source-1")
        first = self.poll()
        original = first.observations[0]
        with _database(self.db) as connection:
            connection.execute("UPDATE history_v2 SET status='completed', refined_text=?, updated_at=? WHERE id=?",
                               ("revised synthetic idea", "2026-10-05T10:31:00Z", "source-1"))
        second = self.poll(cursor=first.cursor, seen_versions=[original.dedupe_key])
        self.assertEqual(len(second.observations), 1)
        self.assertNotEqual(second.observations[0].source_version, original.source_version)
        third = self.poll(cursor=second.cursor,
                          seen_versions=[original.dedupe_key, second.observations[0].dedupe_key])
        self.assertEqual(third.observations, ())

    def test_overlap_catches_status_change_without_updated_timestamp(self):
        self.insert("source-1")
        first = self.poll()
        with _database(self.db) as connection:
            connection.execute("UPDATE history_v2 SET status='completed' WHERE id='source-1'")
        second = self.poll(cursor=first.cursor, seen_versions=[first.observations[0].dedupe_key])
        self.assertEqual(second.observations[0].metadata["status"], "completed")

    def test_tied_ids_and_duplicate_overlap_do_not_starve_pagination(self):
        for identity in ("c", "a", "b", "d"):
            self.insert(identity)
        first = self.poll(limit=2)
        self.assertEqual([o.source_id for o in first.observations], ["a", "b"])
        self.assertFalse(first.complete)
        self.assertEqual(first.cursor["scan_source_id"], "b")
        second = self.poll(limit=2, cursor=first.cursor,
                           seen_versions=[o.dedupe_key for o in first.observations])
        self.assertEqual([o.source_id for o in second.observations], ["c", "d"])
        self.assertTrue(second.complete)
        self.assertNotIn("window_end", second.cursor)
        seen = [o.dedupe_key for o in (*first.observations, *second.observations)]
        replay1 = self.poll(limit=2, cursor=second.cursor, seen_versions=seen)
        replay2 = self.poll(limit=2, cursor=replay1.cursor, seen_versions=seen)
        self.assertEqual(replay1.observations + replay2.observations, ())
        self.assertTrue(replay2.complete)

    def test_same_content_different_source_is_not_collapsed(self):
        self.insert("a")
        self.insert("b")
        observations = self.poll().observations
        self.assertEqual(len(observations), 2)
        self.assertNotEqual(observations[0].dedupe_key, observations[1].dedupe_key)

    def test_local_audio_reference_and_opt_in_text_never_enter_cloud(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"fixture audio placeholder")
        self.insert("source-1", text="secret synthetic phrase", audio=str(audio))
        batch = self.poll(include_text=True, max_text_chars=6)
        observation = batch.observations[0]
        self.assertEqual(observation.text, "secret")
        self.assertTrue(observation.local_reference["audio_exists"])
        self.assertEqual(observation.local_reference["audio_path"], str(audio))
        cloud = json.dumps(batch.cloud_projection())
        self.assertNotIn("secret", cloud)
        self.assertNotIn(str(self.root), cloud)
        self.assertNotIn("source-1", cloud)
        self.assertTrue(observation.cloud_projection()["metadata"]["audio_exists"])

    def test_oversized_content_is_a_gap_not_a_prefix_hash(self):
        self.insert("source-1", text="x" * 50)
        observer = TypelessObserver(replace(self.config, max_content_chars=20))
        batch = observer.poll(start_at=START, end_at=END)
        self.assertEqual(batch.observations, ())
        self.assertIn("content_out_of_bounds", batch.gaps)
        self.assertIsNotNone(batch.cursor)

    def test_exact_path_and_time_bounds(self):
        self.insert("source-1")
        wrong = TypelessObserver(replace(self.config, allowed_database_path=self.root / "different.db"))
        self.assertEqual(wrong.poll(start_at=START, end_at=END).gaps, ("path_not_allowlisted",))
        link = self.root / "link.db"
        link.symlink_to(self.db)
        linked = TypelessObserver(replace(self.config, database_path=link, allowed_database_path=link))
        self.assertEqual(linked.poll(start_at=START, end_at=END).gaps, ("path_not_allowlisted",))
        self.assertEqual(self.observer.poll(start_at=START, end_at="2026-10-08T11:00:00Z").gaps,
                         ("window_out_of_bounds",))
        self.assertEqual(self.observer.poll(start_at="2026-10-05T10:00:00", end_at=END).gaps,
                         ("timezone_required",))


class LuciTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shim = self.root / "luci"
        self.shim.write_text("#!/bin/sh\nexit 0\n")
        self.shim.chmod(0o700)
        self.calls = []
        self.entries = [{"captureId": 42, "timestamp": 2_000, "app": "Private App",
                         "windowTitle": "private customer", "browserUrl": "https://invalid/?token=secret",
                         "screenshotPath": str(self.root / "private.jpg"), "displayId": "display-1",
                         "text": "synthetic private screen text"}]

    def runner(self, argv, max_bytes, timeout_seconds):
        self.calls.append((argv, max_bytes, timeout_seconds))
        return 0, json.dumps({"entries": self.entries}).encode(), b""

    def observer(self, **kwargs):
        return LuciObserver(self.shim, self.shim, runner=self.runner, **kwargs)

    def test_exact_usage_command_and_metadata_only_projection(self):
        batch = self.observer().poll(start_ms=1_000, end_ms=3_000)
        self.assertEqual(batch.status, "ok")
        self.assertEqual(self.calls[0][0], [str(self.shim), "usage", "--tr", "1000:3000", "--limit", "20", "--json"])
        self.assertIsNone(batch.observations[0].text)
        cloud = json.dumps(batch.cloud_projection())
        for secret in ("private", "Private App", "token=", str(self.root), "display-1"):
            self.assertNotIn(secret, cloud)

    def test_opt_in_text_does_not_change_source_version(self):
        observer = self.observer()
        plain = observer.poll(start_ms=1_000, end_ms=3_000)
        text = observer.poll(start_ms=1_000, end_ms=3_000, include_text=True, max_text_chars=9)
        self.assertEqual(text.observations[0].text, "synthetic")
        self.assertEqual(plain.observations[0].source_version, text.observations[0].source_version)
        duplicate = observer.poll(start_ms=1_000, end_ms=3_000,
                                  seen_versions=[plain.observations[0].dedupe_key])
        self.assertEqual(duplicate.observations, ())

    def test_unbounded_range_fails_before_invocation(self):
        batch = self.observer().poll(start_ms=1_000, end_ms=100_000_000)
        self.assertEqual(batch.gaps, ("bounds_invalid",))
        self.assertEqual(self.calls, [])

    def test_schema_and_source_window_fail_closed(self):
        self.entries[0]["timestamp"] = 9_000
        self.assertEqual(self.observer().poll(start_ms=1_000, end_ms=3_000).gaps, ("cli_record_invalid",))
        wrong = LuciObserver(self.shim, self.shim,
                             runner=lambda *args: (0, b'{"unknown": []}', b""))
        self.assertEqual(wrong.poll(start_ms=1_000, end_ms=3_000).gaps, ("cli_schema_mismatch",))

    def test_output_cap_and_limit_are_enforced(self):
        observer = LuciObserver(self.shim, self.shim, max_output_bytes=1_024,
                                runner=lambda *args: (0, b"x" * 1_025, b""))
        self.assertEqual(observer.poll(start_ms=1_000, end_ms=3_000).gaps, ("cli_output_out_of_bounds",))
        self.entries = self.entries * 2
        self.assertEqual(self.observer().poll(start_ms=1_000, end_ms=3_000, limit=1).gaps,
                         ("cli_limit_not_honored",))

    def test_exit_failure_does_not_copy_stderr_or_retry(self):
        calls = []
        def fail(*args):
            calls.append(args)
            return 2, b"", b"private path /secret/token"
        batch = LuciObserver(self.shim, self.shim, runner=fail).poll(start_ms=1_000, end_ms=3_000)
        self.assertEqual(batch.gaps, ("cli_query_failed",))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret", json.dumps(batch.as_dict()))

    def test_streaming_runner_kills_oversized_process_output(self):
        script = self.root / "oversize"
        script.write_text("#!/bin/sh\nprintf '%02000d' 0\n")
        script.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "cli_output_out_of_bounds"):
            _run_bounded([str(script)], 1_024, 2)


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "session.jsonl"

    def record(self, identity, role, blocks, *, cwd=None):
        return {"type": role, "uuid": identity, "cwd": str(cwd or self.root),
                "sessionId": "fixture-session", "timestamp": STAMP,
                "message": {"role": role, "content": blocks}}

    def write(self, records, trailing=b""):
        self.log.write_bytes(b"".join(json.dumps(record).encode() + b"\n" for record in records) + trailing)

    def observer(self, **kwargs):
        return ClaudeJsonlObserver(self.log, self.log, self.root, **kwargs)

    def test_text_and_tool_lifecycle_exclude_thinking_and_payload_secrets(self):
        self.write([
            self.record("u", "user", "synthetic user request"),
            self.record("a", "assistant", [{"type": "text", "text": "synthetic reply"},
                       {"type": "thinking", "thinking": "PRIVATE_THINKING"},
                       {"type": "reasoning", "text": "PRIVATE_REASONING"},
                       {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"secret": "PRIVATE_INPUT"}}]),
            self.record("t", "user", [{"type": "tool_result", "tool_use_id": "tool-1",
                       "is_error": True, "content": "PRIVATE_OUTPUT"}]),
        ])
        batch = self.observer().poll()
        self.assertEqual([o.event_type for o in batch.observations],
                         ["message_text", "message_text", "tool_started", "tool_finished"])
        self.assertTrue(batch.observations[-1].metadata["is_error"])
        local = json.dumps(batch.as_dict())
        self.assertNotIn("PRIVATE_", local)
        self.assertTrue(all(o.text is None for o in batch.observations))
        cloud = json.dumps(batch.cloud_projection())
        self.assertNotIn("synthetic", cloud)
        self.assertNotIn(str(self.root), cloud)
        self.assertNotIn("fixture-session", cloud)

    def test_explicit_text_is_bounded_and_source_version_stable(self):
        self.write([self.record("u", "user", "synthetic user request")])
        observer = self.observer(max_text_chars=9)
        plain, with_text = observer.poll(), observer.poll(include_text=True)
        self.assertEqual(with_text.observations[0].text, "synthetic")
        self.assertEqual(plain.observations[0].source_version, with_text.observations[0].source_version)
        self.assertEqual(observer.poll(seen_versions=[plain.observations[0].dedupe_key]).observations, ())

    def test_unregistered_path_and_wrong_workspace_are_not_read_as_matching(self):
        self.write([self.record("u", "user", "synthetic", cwd=self.root / "other")])
        batch = self.observer().poll()
        self.assertEqual(batch.observations, ())
        self.assertIn("cwd_mismatch_or_missing", batch.gaps)
        unregistered = ClaudeJsonlObserver(None, None, self.root).poll()
        self.assertEqual(unregistered.gaps, ("source_not_registered",))
        wrong_path = ClaudeJsonlObserver(self.log, self.root / "other.jsonl", self.root).poll()
        self.assertEqual(wrong_path.gaps, ("path_not_allowlisted",))

    def test_tail_and_line_limits_have_explicit_coverage_gaps(self):
        self.write([self.record(str(i), "user", "x" * 200) for i in range(10)])
        batch = self.observer(max_tail_bytes=1_024, max_lines=1).poll()
        self.assertEqual(len(batch.observations), 1)
        self.assertIn("tail_history_omitted", batch.gaps)
        self.assertIn("line_limit_reached", batch.gaps)
        self.assertFalse(batch.complete)

    def test_incomplete_and_malformed_lines_preserve_valid_evidence(self):
        self.write([self.record("u", "user", "synthetic")], trailing=b"{bad}\n{unfinished")
        batch = self.observer().poll()
        self.assertEqual(len(batch.observations), 1)
        self.assertIn("incomplete_line", batch.gaps)
        self.assertIn("malformed_line", batch.gaps)

    def test_event_limit_is_bounded(self):
        blocks = [{"type": "text", "text": str(i)} for i in range(8)]
        self.write([self.record("a", "assistant", blocks)])
        batch = self.observer(max_events=3).poll()
        self.assertEqual(len(batch.observations), 3)
        self.assertIn("event_limit_reached", batch.gaps)

    def test_projection_rejects_arbitrary_metadata(self):
        observation = SourceObservation("claude_jsonl", "source", "a" * 64, "message_text", STAMP, STAMP,
                                        STAMP, safe_metadata={"secret_path": "/secret", "text_hash": "/secret",
                                                              "role": "system", "tool_id_hash": "b" * 64})
        projection = observation.cloud_projection()
        self.assertEqual(projection["metadata"], {"tool_id_hash": "b" * 64})


if __name__ == "__main__":
    unittest.main()
