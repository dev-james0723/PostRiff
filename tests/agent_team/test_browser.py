"""Pure isolated-browser planning and synthetic IPC; no browser launches."""

import base64
import hashlib
import struct
import unittest
import zlib
from dataclasses import replace

from agent_team.browser import (
    BrowserBlocked,
    CaptureRequest,
    EndpointEvidence,
    PAGE_STATE_EXPRESSION,
    PNG_SIGNATURE,
    RuntimeEvidence,
    capture_page,
    chrome_command_preview,
    create_manifest,
    daemon_command_preview,
    parse_devtools_active_port,
    probe_health,
)


SHA = hashlib.sha256(b"approved agent-only browser capture scope").hexdigest()


def manifest():
    return create_manifest(mission_id="mission-browser", instance_id="jat-observation-1",
                           authorization_ref="proposal/isolated-agent-profile", authorization_sha256=SHA,
                           scope_version="v1", agent_root="/registered/work/agent-team-browser",
                           allowed_origins=("https://example.com", "http://127.0.0.1:8765"))


def runtime(m=None):
    m = m or manifest()
    return RuntimeEvidence(m.fingerprint, m.profile_dir, m.unix_socket, 71, "chrome-start-identity", 72,
                           "daemon-start-identity", True, True, True, 100, "controller/exact-owned-processes")


def png_fixture():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b"")


class FakeTransport:
    def __init__(self, *, connected=True, daemon_pid=72, browser_kind="cdp", origin="https://example.com",
                 ready="complete", screenshot=None, failure_method=None):
        self.calls = []
        self.connected = connected
        self.daemon_pid = daemon_pid
        self.browser_kind = browser_kind
        self.origin = origin
        self.ready = ready
        self.screenshot = png_fixture() if screenshot is None else screenshot
        self.failure_method = failure_method

    def request(self, manifest, payload, *, timeout):
        self.calls.append((manifest.unix_socket, payload, timeout))
        if payload.get("meta") == "ping":
            return {"pong": True, "pid": self.daemon_pid, "browser_kind": self.browser_kind}
        if payload.get("meta") == "connection_status":
            return {"target_id": "DAEMON-OWNED-TARGET"} if self.connected else {"error": "cdp_disconnected"}
        method = payload["method"]
        if method == self.failure_method:
            return {"error": "Connection lost; sensitive error body must never reach a receipt"}
        result = {}
        if method == "Target.createTarget":
            result = {"targetId": "REQUEST-OWNED-TARGET"}
        elif method == "Target.attachToTarget":
            result = {"sessionId": "EXACT-REQUEST-SESSION"}
        elif method == "Runtime.evaluate":
            result = {"result": {"value": {"origin": self.origin, "path": "/", "ready": self.ready}}}
        elif method == "Page.captureScreenshot":
            result = {"data": base64.b64encode(self.screenshot).decode()}
        return {"result": result}


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.manifest = manifest()
        self.runtime = runtime(self.manifest)
        self.request = CaptureRequest("capture-1", "https://example.com/controlled")

    def capture(self, transport=None, request=None, runtime_evidence=None):
        return capture_page(self.manifest, runtime_evidence or self.runtime, transport or FakeTransport(),
                            request or self.request, clock=lambda: 100.0, pause=lambda _: None)

    def test_manifest_uses_separate_agent_profile_home_and_short_socket(self):
        m = self.manifest
        self.assertIn("/profiles/jat-observation-1", m.profile_dir)
        self.assertNotIn("Google/Chrome", m.profile_dir)
        self.assertNotIn(".config/browser-harness", m.harness_home)
        self.assertEqual(m.unix_socket, m.runtime_dir + "/bu.sock")
        self.assertLessEqual(len(m.unix_socket.encode()), 103)
        self.assertEqual(m.execution_state, "isolated_launch_candidate")

    def test_default_namespace_and_foreign_profile_are_rejected(self):
        for changed in (replace(self.manifest, instance_id="default"),
                        replace(self.manifest, profile_dir="/Users/test/Library/Application Support/Google/Chrome"),
                        replace(self.manifest, unix_socket="/Users/test/.config/browser-harness/runtime/bu-default.sock"),
                        replace(self.manifest, runtime_dir="/private/tmp/jat-bh-another-owner", unix_socket="/private/tmp/jat-bh-another-owner/bu.sock")):
            with self.subTest(changed=changed), self.assertRaises(BrowserBlocked):
                changed.validate()

    def test_plain_headless_command_never_uses_open_or_personal_profile(self):
        preview = chrome_command_preview(self.manifest)
        self.assertEqual(preview.argv[0], self.manifest.chrome_binary)
        self.assertIn("--headless=new", preview.argv)
        self.assertIn("--remote-debugging-port=0", preview.argv)
        self.assertIn("--remote-debugging-address=127.0.0.1", preview.argv)
        self.assertIn("--user-data-dir=" + self.manifest.profile_dir, preview.argv)
        self.assertIn("--disable-background-networking", preview.argv)
        self.assertFalse(preview.execute_allowed)
        self.assertNotIn("--no-sandbox", preview.argv)
        self.assertNotIn("open", preview.argv)

    def test_daemon_environment_cannot_inherit_cloud_or_default_browser(self):
        endpoint = EndpointEvidence(self.manifest.fingerprint, self.manifest.profile_dir, 71, "chrome-start-identity",
                                    41235, True, True, 100, "controller/agent-profile-port")
        preview = daemon_command_preview(self.manifest, endpoint, now=100)
        env = dict(preview.environment)
        self.assertEqual(preview.argv, (self.manifest.python_binary, "-B", "-m", "browser_harness.daemon"))
        self.assertEqual(env["BU_CDP_URL"], "http://127.0.0.1:41235")
        self.assertEqual(env["BU_CDP_WS"], "")
        self.assertEqual(env["BU_BROWSER_ID"], "")
        self.assertEqual(env["BU_API_KEY"], "")
        self.assertEqual(env["BU_NAME"], self.manifest.instance_id)
        self.assertEqual(env["BH_RUNTIME_DIR"], self.manifest.runtime_dir)
        self.assertEqual(env["BH_HOME"], self.manifest.harness_home)
        self.assertEqual(env["BH_TMP_DIR"], self.manifest.tmp_dir)
        self.assertEqual(env["ORC_AUTO_APPROVE_CHROME_REMOTE_DEBUGGING"], "0")
        self.assertEqual(env["BH_TAB_MARKER"], "0")
        self.assertFalse(preview.execute_allowed)

    def test_daemon_preview_requires_positive_fresh_agent_profile_proof(self):
        endpoint = EndpointEvidence(self.manifest.fingerprint, self.manifest.profile_dir, 71, "chrome-start-identity",
                                    41235, True, True, 100, "controller/agent-profile-port")
        cases = (replace(endpoint, identity_verified=False), replace(endpoint, agent_only_profile_verified=False),
                 replace(endpoint, chrome_pid=0), replace(endpoint, chrome_process_start=""),
                 replace(endpoint, profile_dir="/private/personal-profile"), replace(endpoint, observed_at=1),
                 replace(endpoint, port=0), replace(endpoint, port=65536))
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(BrowserBlocked):
                daemon_command_preview(self.manifest, changed, now=100)

    def test_ephemeral_port_record_must_belong_to_this_profile(self):
        port = parse_devtools_active_port(self.manifest, profile_dir=self.manifest.profile_dir,
                                         contents="41235\n/devtools/browser/agent-test-id\n")
        self.assertEqual(port, 41235)
        for contents in ("0\n/devtools/browser/test", "41235\nwss://private-browser", "41235\n/devtools/browser/test\nextra"):
            with self.subTest(contents=contents), self.assertRaises(BrowserBlocked):
                parse_devtools_active_port(self.manifest, profile_dir=self.manifest.profile_dir, contents=contents)
        with self.assertRaisesRegex(BrowserBlocked, "devtools_profile_scope_mismatch"):
            parse_devtools_active_port(self.manifest, profile_dir="/personal/profile", contents="41235\n/devtools/browser/test")

    def test_health_distinguishes_live_daemon_from_lost_browser(self):
        transport = FakeTransport(connected=False)
        health = probe_health(self.manifest, self.runtime, transport, now=100)
        self.assertFalse(health.healthy)
        self.assertEqual(health.error, "isolated_cdp_disconnected")
        self.assertEqual(health.request_count, 2)
        self.assertEqual([call[1] for call in transport.calls], [{"meta": "ping"}, {"meta": "connection_status"}])

    def test_wrong_owner_or_default_local_browser_cannot_capture(self):
        for transport in (FakeTransport(daemon_pid=999), FakeTransport(browser_kind="local"), FakeTransport(browser_kind="cloud")):
            with self.subTest(transport=transport):
                page = self.capture(transport)
                self.assertEqual(page.receipt.error, "isolated_daemon_identity_mismatch")
                self.assertIsNone(page.png)
                self.assertEqual(len(transport.calls), 1)

    def test_stale_identity_or_unverified_isolation_makes_no_ipc_call(self):
        for changed in (replace(self.runtime, observed_at=1), replace(self.runtime, identity_verified=False),
                        replace(self.runtime, no_symlink_aliases_verified=False), replace(self.runtime, unix_socket="/shared/default.sock")):
            transport = FakeTransport()
            page = self.capture(transport, runtime_evidence=changed)
            self.assertIsNone(page.png)
            self.assertEqual(transport.calls, [])

    def test_background_capture_returns_timestamps_hash_and_png_only(self):
        transport = FakeTransport()
        page = self.capture(transport)
        self.assertEqual(page.receipt.state, "captured")
        self.assertEqual(page.png, png_fixture())
        self.assertEqual(page.receipt.png_sha256, hashlib.sha256(page.png).hexdigest())
        self.assertEqual((page.receipt.width, page.receipt.height), (1, 1))
        self.assertEqual(page.receipt.requested_at, 100)
        self.assertEqual(page.receipt.captured_at, 100)
        self.assertEqual(page.receipt.finished_at, 100)
        self.assertTrue(page.receipt.background_requested)
        self.assertFalse(page.receipt.focus_activation_sent)
        self.assertFalse(page.receipt.focus_untouched_verified)
        self.assertFalse(page.receipt.uploaded)
        payloads = [call[1] for call in transport.calls]
        self.assertIn({"method": "Target.createTarget", "params": {"url": "about:blank", "background": True}}, payloads)
        self.assertNotIn("Target.activateTarget", [p.get("method") for p in payloads])
        for payload in payloads:
            if payload.get("method") in {"Page.enable", "Page.navigate", "Runtime.evaluate", "Page.captureScreenshot"}:
                self.assertEqual(payload["session_id"], "EXACT-REQUEST-SESSION")
        self.assertEqual(payloads[-1], {"method": "Target.closeTarget", "params": {"targetId": "REQUEST-OWNED-TARGET"}})
        self.assertEqual({call[0] for call in transport.calls}, {self.manifest.unix_socket})

    def test_redirect_outside_authorized_origin_prevents_screenshot(self):
        transport = FakeTransport(origin="https://private.example")
        page = self.capture(transport)
        self.assertEqual(page.receipt.error, "redirect_origin_not_authorized")
        self.assertIsNone(page.receipt.origin)
        self.assertIsNone(page.png)
        self.assertNotIn("Page.captureScreenshot", [c[1].get("method") for c in transport.calls])

    def test_readiness_has_finite_checks_and_closes_only_owned_target(self):
        transport = FakeTransport(ready="loading")
        page = self.capture(transport, replace(self.request, max_state_checks=2))
        self.assertEqual(page.receipt.error, "page_not_ready_within_bound")
        self.assertEqual(sum(c[1].get("method") == "Runtime.evaluate" for c in transport.calls), 2)
        self.assertEqual(transport.calls[-1][1]["params"], {"targetId": "REQUEST-OWNED-TARGET"})

    def test_private_capture_and_unsupported_origin_are_rejected_before_ipc(self):
        for changed in (replace(self.request, data_class="private"), replace(self.request, url="https://private.example"),
                        replace(self.request, url="file:///private/contents"), replace(self.request, url="https://user:password@example.com/")):
            transport = FakeTransport()
            with self.subTest(changed=changed), self.assertRaises(BrowserBlocked):
                self.capture(transport, changed)
            self.assertEqual(transport.calls, [])

    def test_errors_are_metadata_without_raw_browser_error_contents(self):
        page = self.capture(FakeTransport(failure_method="Page.captureScreenshot"))
        self.assertEqual(page.receipt.error, "isolated_browser_operation_failed")
        self.assertNotIn("sensitive", str(page.receipt))
        self.assertIsNone(page.png)

    def test_non_png_and_large_dimensions_are_rejected(self):
        page = self.capture(FakeTransport(screenshot=b"not a png"))
        self.assertEqual(page.receipt.error, "screenshot_png_invalid")
        bad = png_fixture()[:16] + struct.pack(">II", 10000, 10000) + png_fixture()[24:]
        page = self.capture(FakeTransport(screenshot=bad))
        self.assertEqual(page.receipt.error, "screenshot_dimensions_exceed_bound")
        self.assertIsNone(page.png)
        truncated = png_fixture()[:-12]
        page = self.capture(FakeTransport(screenshot=truncated))
        self.assertEqual(page.receipt.error, "screenshot_png_invalid")
        corrupted = png_fixture()[:-1] + bytes([png_fixture()[-1] ^ 1])
        page = self.capture(FakeTransport(screenshot=corrupted))
        self.assertEqual(page.receipt.error, "screenshot_png_invalid")

    def test_only_fixed_readiness_expression_is_used(self):
        transport = FakeTransport()
        self.capture(transport)
        evaluations = [c[1] for c in transport.calls if c[1].get("method") == "Runtime.evaluate"]
        self.assertEqual(evaluations[0]["params"], {"expression": PAGE_STATE_EXPRESSION, "returnByValue": True})


if __name__ == "__main__":
    unittest.main()
