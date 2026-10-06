"""Dependency-injected service fixtures; no daemons, sources or network are used."""

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from agent_team.service import (
    INGRESS_PATH,
    ServiceConfig,
    ServiceDependencies,
    ServicePolicy,
    load_config,
    one_tick,
    run_daemon,
)


class FakeJournal:
    def __init__(self, *, fail=False):
        self.events = []
        self.fail = fail

    def ingest(self, events):
        if self.fail:
            raise OSError("PRIVATE_ERROR /private/credential")
        self.events.extend(event.cloud() for event in events)
        return len(events)


class FakeClock:
    def __init__(self):
        self.elapsed = 0.0
        self.waits = []

    def monotonic(self):
        return self.elapsed

    def wait(self, duration):
        self.waits.append(duration)
        self.elapsed += duration


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.runtime = self.root / ".runtime"
        self.runtime.mkdir(mode=0o700)
        self.workspace = self.root / "approved-project"
        self.workspace.mkdir()
        self.policy_data = {
            "version": 1,
            "canonical_root": str(self.root),
            "approved_native_projects": {str(self.workspace): "fixture-project"},
            "allowed_upload_hosts": [],
        }
        self.policy = ServicePolicy.from_mapping(self.policy_data, canonical_root=self.root)
        self.config_data = {
            "version": 1,
            "journal_path": str(self.runtime / "journal.sqlite3"),
            "interval_seconds": 300,
            "window_seconds": 600,
            "typeless": True,
            "luci": False,
            "native_workspaces": [],
            "upload": None,
        }
        self.now = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)

    def config(self, **overrides):
        return ServiceConfig.from_mapping({**self.config_data, **overrides}, self.policy)

    def dependencies(self, **overrides):
        def never_send(*args, **kwargs):
            raise AssertionError("upload not configured")
        defaults = {
            "wall_clock": lambda: self.now,
            "source_connected": lambda source, path: True,
            "collect": lambda *args, **kwargs: {"sources": {"typeless": {"status": "ok"}}},
            "collect_native": lambda *args, **kwargs: {"status": "ok"},
            "send": never_send,
        }
        return ServiceDependencies(**{**defaults, **overrides})

    def native_selection(self):
        return [{"workspace": str(self.workspace), "project_id": "fixture-project"}]

    def test_default_windows_and_interval_are_bounded(self):
        config = self.config()
        self.assertEqual(config.interval_seconds, 300)
        self.assertEqual(config.window_seconds, 600)
        for field, bad in (("interval_seconds", 299), ("interval_seconds", True),
                           ("window_seconds", 3_601), ("window_seconds", 0)):
            with self.subTest(field=field, bad=bad):
                with self.assertRaises(ValueError):
                    self.config(**{field: bad})

    def test_audio_requires_explicit_flag_and_authenticated_ingress(self):
        self.assertFalse(self.config().audio)
        with self.assertRaisesRegex(ValueError,'audio_requires_authenticated_upload'):
            self.config(audio=True)
        with self.assertRaisesRegex(ValueError,'explicit_audio_flag_required'):
            self.config(audio='true')

    def test_unknown_commands_and_source_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "config_fields_not_allowlisted"):
            self.config(command="sh -c unsafe")
        with self.assertRaisesRegex(ValueError, "config_fields_not_allowlisted"):
            self.config(source_paths=["/private/elsewhere"])
        with self.assertRaisesRegex(ValueError, "private_path_not_allowlisted"):
            self.config(journal_path=str(self.root / "elsewhere.db"))

    def test_native_workspace_and_project_must_both_match_reviewed_policy(self):
        selected = self.config(native_workspaces=self.native_selection())
        self.assertEqual(selected.native_workspaces[0].project_id, "fixture-project")
        with self.assertRaisesRegex(ValueError, "native_workspace_project_not_approved"):
            self.config(native_workspaces=[{"workspace": str(self.workspace), "project_id": "other-project"}])
        with self.assertRaisesRegex(ValueError, "native_workspace_project_not_approved"):
            self.config(native_workspaces=[{"workspace": str(self.root / "other"), "project_id": "fixture-project"}])
        with self.assertRaisesRegex(ValueError, "duplicate_native_workspace"):
            self.config(native_workspaces=self.native_selection() * 2)

    def test_private_runtime_and_symlink_alias_are_rejected(self):
        self.runtime.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "private_runtime_directory_required"):
            self.config()
        self.runtime.chmod(0o700)
        link = self.root / "alias"
        link.symlink_to(self.workspace, target_is_directory=True)
        bad_policy = {**self.policy_data, "approved_native_projects": {str(link): "fixture-project"}}
        with self.assertRaisesRegex(ValueError, "path_alias_not_allowed"):
            ServicePolicy.from_mapping(bad_policy, canonical_root=self.root)

    def test_private_config_loading_uses_exact_paths_and_size_limit(self):
        policy_file = self.runtime / "service-policy.json"
        config_file = self.runtime / "service-config.json"
        for path, content in ((policy_file, self.policy_data), (config_file, self.config_data)):
            path.write_text(json.dumps(content))
            path.chmod(0o600)
        loaded = load_config(config_file, policy_file, canonical_root=self.root)
        self.assertEqual(loaded.window_seconds, 600)
        config_file.write_bytes(b" " * 16_385)
        with self.assertRaisesRegex(ValueError, "config_file_out_of_bounds"):
            load_config(config_file, policy_file, canonical_root=self.root)

    def test_duplicate_json_config_keys_are_rejected(self):
        policy_file = self.runtime / "service-policy.json"
        config_file = self.runtime / "service-config.json"
        policy_file.write_text(json.dumps(self.policy_data))
        config_file.write_text('{"version": 1, "version": 2}')
        policy_file.chmod(0o600)
        config_file.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "duplicate_config_field"):
            load_config(config_file, policy_file, canonical_root=self.root)

    def test_missing_sources_are_not_connected_without_polling(self):
        calls = []
        deps = self.dependencies(source_connected=lambda *args: False,
                                 collect=lambda *args, **kwargs: calls.append("collect"))
        journal = FakeJournal()
        result = one_tick(self.config(luci=True, native_workspaces=self.native_selection()), journal, deps)
        self.assertEqual(calls, [])
        self.assertEqual(result["sources"]["typeless"], "not_connected")
        self.assertEqual(result["sources"]["luci"], "not_connected")
        self.assertEqual(len(result["sources"]), 3)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any(event["payload"]["kind"] == "collector_heartbeat" for event in journal.events))
        self.assertFalse(result["dailyCoverageComplete"])

    def test_connected_subset_only_and_exact_native_mapping_are_forwarded(self):
        calls = []
        def collect(journal, now, **kwargs):
            calls.append(("collect", kwargs))
            return {"sources": {"luci": {"status": "partial"}}}
        def native(journal, workspace, *, project_id):
            calls.append(("native", workspace, project_id))
            return {"status": "ok", "writerOwnership": "unproven"}
        deps = self.dependencies(collect=collect, collect_native=native,
                                 source_connected=lambda source, path: source != "typeless")
        result = one_tick(self.config(luci=True, native_workspaces=self.native_selection()), FakeJournal(), deps)
        self.assertEqual(calls[0], ("collect", {"typeless": False, "luci": True, "window_seconds": 600}))
        self.assertEqual(calls[1], ("native", str(self.workspace), "fixture-project"))
        self.assertEqual(result["taskDispatch"], "not_requested")
        self.assertEqual(result["inference"], "not_requested")

    def test_source_failures_are_sanitized_and_do_not_block_other_sources(self):
        calls = []
        def fail(*args, **kwargs):
            raise OSError("PRIVATE_ERROR /private/credential raw transcript")
        def native(*args, **kwargs):
            calls.append("native")
            return {"status": "ok"}
        journal = FakeJournal()
        result = one_tick(self.config(native_workspaces=self.native_selection()), journal,
                          self.dependencies(collect=fail, collect_native=native))
        self.assertEqual(calls, ["native"])
        self.assertEqual(result["sources"]["typeless"], "unavailable")
        output = json.dumps([result, journal.events])
        for secret in ("PRIVATE_ERROR", "/private/credential", "raw transcript", str(self.workspace)):
            self.assertNotIn(secret, output)

    def test_journal_failure_does_not_expose_exception_text(self):
        result = one_tick(self.config(), FakeJournal(fail=True), self.dependencies())
        self.assertIn("journal_write_failed", result["gaps"])
        self.assertNotIn("PRIVATE_ERROR", json.dumps(result))

    def test_direct_constructed_config_is_revalidated(self):
        invalid = replace(self.config(), interval_seconds=0)
        with self.assertRaisesRegex(ValueError, "poll_interval_out_of_bounds"):
            one_tick(invalid, FakeJournal(), self.dependencies())
        with self.assertRaisesRegex(ValueError, "poll_interval_out_of_bounds"):
            run_daemon(invalid, FakeJournal(), self.dependencies(), max_ticks=1)

    def upload_config(self):
        self.policy = ServicePolicy.from_mapping({**self.policy_data, "allowed_upload_hosts": ["fixture.example"]},
                                                canonical_root=self.root)
        token = self.runtime / "cloud-ingress.token"
        token.write_text("synthetic fixture; never sent to a real transport")
        token.chmod(0o600)
        return self.config(upload={"endpoint": "https://fixture.example" + INGRESS_PATH,
                                   "token_file": str(token), "limit": 20})

    def test_upload_has_exact_host_token_path_and_no_redirect_or_query_surface(self):
        config = self.upload_config()
        for endpoint in ("http://fixture.example" + INGRESS_PATH,
                         "https://other.example" + INGRESS_PATH,
                         "https://fixture.example:443" + INGRESS_PATH,
                         "https://fixture.example" + INGRESS_PATH + "?token=private",
                         "https://fixture.example/other"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.config(upload={"endpoint": endpoint, "token_file": str(config.upload.token_file), "limit": 20})
        with self.assertRaisesRegex(ValueError, "private_path_not_allowlisted"):
            self.config(upload={"endpoint": config.upload.endpoint,
                                "token_file": str(self.root / "other-token"), "limit": 20})

    def test_explicit_upload_calls_only_injected_send_pending_contract(self):
        calls = []
        def send(journal, endpoint, token_file, delivered_at, *, limit):
            calls.append((endpoint, token_file, delivered_at, limit))
            return {"state": "acknowledged", "count": 1}
        config = self.upload_config()
        journal = FakeJournal()
        result = one_tick(config, journal, self.dependencies(send=send))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], config.upload.endpoint)
        self.assertEqual(calls[0][1], self.runtime / "cloud-ingress.token")
        self.assertEqual(calls[0][3], 20)
        self.assertEqual(result["upload"], "acknowledged")
        self.assertNotIn("synthetic fixture", json.dumps(journal.events))

    def test_missing_upload_token_is_not_connected_without_transport_use(self):
        config = self.upload_config()
        config.upload.token_file.unlink()
        result = one_tick(config, FakeJournal(), self.dependencies())
        self.assertEqual(result["upload"], "not_connected")
        self.assertEqual(result["status"], "partial")

    def test_daemon_uses_monotonic_deadlines_and_no_catch_up_after_overrun(self):
        clock, starts = FakeClock(), []
        def collect(*args, **kwargs):
            starts.append(clock.elapsed)
            clock.elapsed += 650
            return {"sources": {"typeless": {"status": "ok"}}}
        deps = self.dependencies(collect=collect, monotonic=clock.monotonic, wait=clock.wait)
        ticks = run_daemon(self.config(), FakeJournal(), deps, max_ticks=2)
        self.assertEqual(ticks, 2)
        self.assertEqual(starts, [0.0, 950.0])
        self.assertTrue(all(0 < wait <= 30 for wait in clock.waits))
        self.assertEqual(sum(clock.waits), 300)

    def test_repeated_source_failure_still_waits_full_interval(self):
        clock = FakeClock()
        starts = []
        def fail(*args, **kwargs):
            starts.append(clock.elapsed)
            raise ValueError("fixture failure")
        ticks = run_daemon(self.config(), FakeJournal(),
                           self.dependencies(collect=fail, monotonic=clock.monotonic, wait=clock.wait), max_ticks=2)
        self.assertEqual(ticks, 2)
        self.assertEqual(starts, [0.0, 300.0])

    def test_stop_event_ends_wait_without_extra_poll(self):
        stop, clock, receipts = threading.Event(), FakeClock(), []
        def stop_wait(duration):
            clock.wait(duration)
            stop.set()
        deps = self.dependencies(monotonic=clock.monotonic, wait=stop_wait)
        ticks = run_daemon(self.config(), FakeJournal(), deps, stop_event=stop, on_tick=receipts.append)
        self.assertEqual(ticks, 1)
        self.assertEqual(len(receipts), 1)


if __name__ == "__main__":
    unittest.main()
