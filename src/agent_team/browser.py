"""Isolated Browser Harness candidate: command previews and bounded observation.

No function launches, ensures, restarts, or discovers a browser/daemon. The root
controller must authorize and start one fresh agent-only Chrome/profile, then
one named installed Browser Harness daemon. Never use the shared default daemon.
Transport operations only address the manifest's Unix socket and approved page.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import stat
import struct
import time
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path, PurePath
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit


CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BH_PYTHON = str(Path.home()/'.local/share/jev-ultrafast/.venv/bin/python')
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PAGE_STATE_EXPRESSION = "({origin:location.origin,path:location.pathname,ready:document.readyState})"
_NAME = re.compile(r"jat-[a-z0-9][a-z0-9-]{0,39}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class BrowserBlocked(ValueError):
    pass


def _absolute(path: str) -> None:
    if not isinstance(path, str) or "\0" in path or not PurePath(path).is_absolute() or os.path.normpath(path) != path:
        raise BrowserBlocked("canonical_absolute_path_required")


def _text(value: str, label: str, limit: int = 2048) -> None:
    if not isinstance(value, str) or not value.strip() or "\0" in value or len(value) > limit:
        raise BrowserBlocked(f"invalid_{label}")


def _sha(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BrowserBlocked("authorization_hash_required")


def _origin(url: str) -> str:
    if not isinstance(url, str) or len(url) > 4096 or any(c in url for c in ("\0", "\r", "\n")):
        raise BrowserBlocked("invalid_page_url")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise BrowserBlocked("invalid_page_url") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise BrowserBlocked("http_origin_without_credentials_required")
    hostname = parsed.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = 80 if parsed.scheme == "http" else 443
    return f"{parsed.scheme}://{hostname}" + (f":{port}" if port and port != default_port else "")


@dataclass(frozen=True)
class BrowserManifest:
    mission_id: str
    instance_id: str
    authorization_ref: str
    authorization_sha256: str
    scope_version: str
    agent_root: str
    profile_dir: str
    harness_home: str
    runtime_dir: str
    tmp_dir: str
    workspace_dir: str
    capture_dir: str
    unix_socket: str
    allowed_origins: tuple[str, ...]
    chrome_binary: str = CHROME_BINARY
    python_binary: str = BH_PYTHON
    max_lifetime_seconds: int = 120
    max_capture_bytes: int = 6 * 1024 * 1024
    execution_state: str = "isolated_launch_candidate"

    def validate(self) -> None:
        for name in ("mission_id", "authorization_ref", "scope_version"):
            _text(getattr(self, name), name)
        if not _NAME.fullmatch(self.instance_id):
            raise BrowserBlocked("explicit_agent_namespace_required")
        _sha(self.authorization_sha256)
        for name in ("agent_root", "profile_dir", "harness_home", "runtime_dir", "tmp_dir", "workspace_dir",
                     "capture_dir", "unix_socket", "chrome_binary", "python_binary"):
            _absolute(getattr(self, name))
        if not self.agent_root.endswith("/agent-team-browser"):
            raise BrowserBlocked("dedicated_agent_root_required")
        expected = {
            "profile_dir": f"{self.agent_root}/profiles/{self.instance_id}",
            "harness_home": f"{self.agent_root}/harness/{self.instance_id}",
            "tmp_dir": f"{self.agent_root}/tmp/{self.instance_id}",
            "workspace_dir": f"{self.agent_root}/workspace/{self.instance_id}",
            "capture_dir": f"{self.agent_root}/captures/{self.instance_id}",
        }
        if any(getattr(self, name) != value for name, value in expected.items()):
            raise BrowserBlocked("agent_path_scope_mismatch")
        token = hashlib.sha256(f"{self.mission_id}\0{self.instance_id}\0{self.agent_root}".encode()).hexdigest()[:20]
        if self.runtime_dir != f"/private/tmp/jat-bh-{token}" or self.unix_socket != f"{self.runtime_dir}/bu.sock":
            raise BrowserBlocked("isolated_unix_runtime_required")
        # macOS AF_UNIX sun_path is 104 bytes including its terminating NUL.
        if len(os.fsencode(self.unix_socket)) > 103:
            raise BrowserBlocked("unix_socket_path_too_long")
        if not self.allowed_origins or len(set(self.allowed_origins)) != len(self.allowed_origins):
            raise BrowserBlocked("exact_origin_allowlist_required")
        for origin in self.allowed_origins:
            if _origin(origin) != origin or urlsplit(origin).path or urlsplit(origin).query or urlsplit(origin).fragment:
                raise BrowserBlocked("exact_origin_allowlist_required")
        if type(self.max_lifetime_seconds) is not int or not 1 <= self.max_lifetime_seconds <= 120:
            raise BrowserBlocked("bounded_browser_lifetime_required")
        if type(self.max_capture_bytes) is not int or not 1 <= self.max_capture_bytes <= 6 * 1024 * 1024:
            raise BrowserBlocked("bounded_capture_size_required")

    @property
    def fingerprint(self) -> str:
        self.validate()
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_manifest(*, mission_id: str, instance_id: str, authorization_ref: str,
                    authorization_sha256: str, scope_version: str, agent_root: str,
                    allowed_origins: tuple[str, ...], chrome_binary: str = CHROME_BINARY,
                    python_binary: str = BH_PYTHON) -> BrowserManifest:
    """Pure argument/path construction; directory creation is root-owned."""
    token = hashlib.sha256(f"{mission_id}\0{instance_id}\0{agent_root}".encode()).hexdigest()[:20]
    runtime = f"/private/tmp/jat-bh-{token}"
    manifest = BrowserManifest(mission_id, instance_id, authorization_ref, authorization_sha256, scope_version,
                               agent_root, f"{agent_root}/profiles/{instance_id}", f"{agent_root}/harness/{instance_id}",
                               runtime, f"{agent_root}/tmp/{instance_id}", f"{agent_root}/workspace/{instance_id}",
                               f"{agent_root}/captures/{instance_id}", f"{runtime}/bu.sock", allowed_origins,
                               chrome_binary, python_binary)
    manifest.validate()
    return manifest


@dataclass(frozen=True)
class CommandPreview:
    argv: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...]
    execution_state: str = "preview_only"
    execute_allowed: bool = False


def _environment(manifest: BrowserManifest) -> dict[str, str]:
    # Deliberately do not inherit process.env, credentials, default BU_NAME,
    # debugging endpoints, personal Browser Harness homes, or auto-approval.
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "TMPDIR": manifest.tmp_dir,
            "BH_HOME": manifest.harness_home, "BROWSER_HARNESS_HOME": manifest.harness_home,
            "BH_CONFIG_DIR": manifest.harness_home, "BH_RUNTIME_DIR": manifest.runtime_dir,
            "BH_TMP_DIR": manifest.tmp_dir, "BH_AGENT_WORKSPACE": manifest.workspace_dir,
            "BH_RUNTIME_DIR_SHARED": "0", "BH_TMP_DIR_SHARED": "0", "BU_NAME": manifest.instance_id,
            "BU_CDP_WS": "", "BU_BROWSER_ID": "", "BU_API_KEY": "", "BH_TAB_MARKER": "0",
            "BH_DOMAIN_SKILLS": "0", "BH_UPDATE_CHECK": "0", "BH_OPEN_LIVE_URL": "0", "DO_NOT_TRACK": "1",
            "ORC_AUTO_APPROVE_CHROME_REMOTE_DEBUGGING": "0"}


def chrome_command_preview(manifest: BrowserManifest) -> CommandPreview:
    manifest.validate()
    argv = (manifest.chrome_binary, "--headless=new", "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0", f"--user-data-dir={manifest.profile_dir}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking", "--disable-sync", "--disable-extensions",
            "--mute-audio", "--window-size=1280,800", "about:blank")
    return CommandPreview(argv, manifest.agent_root, tuple(sorted(_environment(manifest).items())))


@dataclass(frozen=True)
class EndpointEvidence:
    manifest_sha256: str
    profile_dir: str
    chrome_pid: int
    chrome_process_start: str
    port: int
    identity_verified: bool
    agent_only_profile_verified: bool
    observed_at: float
    evidence_ref: str


def daemon_command_preview(manifest: BrowserManifest, endpoint: EndpointEvidence, *, now: float) -> CommandPreview:
    manifest.validate()
    if endpoint.manifest_sha256 != manifest.fingerprint or endpoint.profile_dir != manifest.profile_dir:
        raise BrowserBlocked("endpoint_profile_identity_mismatch")
    if type(endpoint.chrome_pid) is not int or endpoint.chrome_pid < 1 or not endpoint.chrome_process_start:
        raise BrowserBlocked("positive_chrome_process_identity_required")
    if endpoint.identity_verified is not True or endpoint.agent_only_profile_verified is not True or not endpoint.evidence_ref:
        raise BrowserBlocked("positive_agent_profile_proof_required")
    if not 0 <= now - endpoint.observed_at <= 30:
        raise BrowserBlocked("endpoint_evidence_stale")
    if type(endpoint.port) is not int or not 1 <= endpoint.port <= 65535:
        raise BrowserBlocked("invalid_loopback_debugging_port")
    env = _environment(manifest)
    env["BU_CDP_URL"] = f"http://127.0.0.1:{endpoint.port}"
    return CommandPreview((manifest.python_binary, "-B", "-m", "browser_harness.daemon"), manifest.agent_root,
                          tuple(sorted(env.items())))


def parse_devtools_active_port(manifest: BrowserManifest, *, profile_dir: str, contents: str) -> int:
    """Parse only the root-launched profile's small DevToolsActivePort record."""
    manifest.validate()
    if profile_dir != manifest.profile_dir or len(contents.encode()) > 512:
        raise BrowserBlocked("devtools_profile_scope_mismatch")
    lines = contents.splitlines()
    if len(lines) != 2 or not lines[0].isdigit() or not re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]{1,128}", lines[1]):
        raise BrowserBlocked("invalid_devtools_port_record")
    port = int(lines[0])
    if not 1 <= port <= 65535:
        raise BrowserBlocked("invalid_loopback_debugging_port")
    return port


@dataclass(frozen=True)
class RuntimeEvidence:
    manifest_sha256: str
    profile_dir: str
    unix_socket: str
    chrome_pid: int
    chrome_process_start: str
    daemon_pid: int
    daemon_process_start: str
    identity_verified: bool
    agent_only_profile_verified: bool
    no_symlink_aliases_verified: bool
    observed_at: float
    evidence_ref: str


def _validate_runtime(manifest: BrowserManifest, runtime: RuntimeEvidence, now: float) -> None:
    manifest.validate()
    if (runtime.manifest_sha256, runtime.profile_dir, runtime.unix_socket) != (
            manifest.fingerprint, manifest.profile_dir, manifest.unix_socket):
        raise BrowserBlocked("runtime_scope_mismatch")
    if any(type(pid) is not int or pid < 1 for pid in (runtime.chrome_pid, runtime.daemon_pid)) or not runtime.chrome_process_start or not runtime.daemon_process_start:
        raise BrowserBlocked("positive_runtime_process_identity_required")
    if runtime.identity_verified is not True or runtime.agent_only_profile_verified is not True or runtime.no_symlink_aliases_verified is not True or not runtime.evidence_ref:
        raise BrowserBlocked("isolated_runtime_proof_required")
    if not 0 <= now - runtime.observed_at <= 30:
        raise BrowserBlocked("runtime_evidence_stale")


class BrowserTransport(Protocol):
    def request(self, manifest: BrowserManifest, payload: Mapping[str, object], *, timeout: float) -> Mapping[str, object]: ...


def _validate_payload(manifest: BrowserManifest, payload: Mapping[str, object]) -> None:
    if "meta" in payload:
        if set(payload) != {"meta"} or payload["meta"] not in {"ping", "connection_status"}:
            raise BrowserBlocked("browser_admin_action_not_allowed")
        return
    allowed = {"Target.createTarget", "Target.attachToTarget", "Target.closeTarget", "Page.navigate", "Page.enable",
               "Runtime.evaluate", "Page.captureScreenshot"}
    method = payload.get("method")
    if method not in allowed or set(payload) - {"method", "params", "session_id"}:
        raise BrowserBlocked("unsupported_browser_observation_method")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise BrowserBlocked("invalid_browser_request")
    if method == "Target.createTarget" and params != {"url": "about:blank", "background": True}:
        raise BrowserBlocked("background_blank_target_required")
    if method == "Runtime.evaluate" and params != {"expression": PAGE_STATE_EXPRESSION, "returnByValue": True}:
        raise BrowserBlocked("arbitrary_script_not_allowed")
    if method == "Page.captureScreenshot" and params != {"format": "png", "captureBeyondViewport": False}:
        raise BrowserBlocked("bounded_viewport_png_required")
    if method == "Page.enable" and params:
        raise BrowserBlocked("invalid_browser_request")
    if method == "Target.attachToTarget" and (set(params) != {"targetId", "flatten"} or params.get("flatten") is not True
                                               or not _ID.fullmatch(str(params.get("targetId", "")))):
        raise BrowserBlocked("exact_owned_target_required")
    if method == "Target.closeTarget" and (set(params) != {"targetId"} or not _ID.fullmatch(str(params.get("targetId", "")))):
        raise BrowserBlocked("exact_owned_target_required")
    if method == "Page.navigate" and (set(params) != {"url"} or _origin(params.get("url")) not in manifest.allowed_origins):
        raise BrowserBlocked("page_origin_not_authorized")
    if method in {"Page.navigate", "Page.enable", "Runtime.evaluate", "Page.captureScreenshot"} and not _ID.fullmatch(str(payload.get("session_id", ""))):
        raise BrowserBlocked("exact_owned_page_session_required")


class UnixHarnessTransport:
    """Explicit bounded IPC only. Construction/import creates no runtime files."""

    def request(self, manifest: BrowserManifest, payload: Mapping[str, object], *, timeout: float) -> Mapping[str, object]:
        manifest.validate()
        _validate_payload(manifest, payload)
        if not 0 < timeout <= 15:
            raise BrowserBlocked("bounded_ipc_timeout_required")
        endpoint = Path(manifest.unix_socket)
        try:
            info = endpoint.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BrowserBlocked("private_owned_unix_socket_required")
            if str(endpoint.resolve()) != manifest.unix_socket:
                raise BrowserBlocked("socket_symlink_alias_not_allowed")
            raw = json.dumps(dict(payload), separators=(",", ":"), allow_nan=False).encode() + b"\n"
            if len(raw) > 8192:
                raise BrowserBlocked("ipc_request_too_large")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(timeout)
                channel.connect(manifest.unix_socket)
                channel.sendall(raw)
                parts = bytearray()
                max_reply = (manifest.max_capture_bytes * 4 // 3) + 65536
                deadline = time.monotonic() + timeout
                while not parts.endswith(b"\n"):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BrowserBlocked("browser_ipc_timeout")
                    channel.settimeout(remaining)
                    part = channel.recv(min(65536, max_reply + 1 - len(parts)))
                    if not part:
                        break
                    parts.extend(part)
                    if len(parts) > max_reply:
                        raise BrowserBlocked("ipc_reply_too_large")
            result = json.loads(parts)
            if not isinstance(result, dict):
                raise BrowserBlocked("invalid_ipc_reply")
            return result
        except BrowserBlocked:
            raise
        except TimeoutError as exc:
            raise BrowserBlocked("browser_ipc_timeout") from exc
        except (OSError, ValueError) as exc:
            raise BrowserBlocked("browser_ipc_unavailable") from exc


@dataclass(frozen=True)
class BrowserHealth:
    mission_id: str
    instance_id: str
    observed_at: float
    healthy: bool
    daemon_pid: int | None
    error: str | None
    request_count: int


def probe_health(manifest: BrowserManifest, runtime: RuntimeEvidence, transport: BrowserTransport,
                 *, now: float) -> BrowserHealth:
    count = 0
    try:
        _validate_runtime(manifest, runtime, now)
        count += 1
        ping = transport.request(manifest, {"meta": "ping"}, timeout=1)
        if ping.get("pong") is not True or ping.get("pid") != runtime.daemon_pid or ping.get("browser_kind") != "cdp":
            raise BrowserBlocked("isolated_daemon_identity_mismatch")
        count += 1
        state = transport.request(manifest, {"meta": "connection_status"}, timeout=2)
        if state.get("error") or not _ID.fullmatch(str(state.get("target_id", ""))):
            raise BrowserBlocked("isolated_cdp_disconnected")
        return BrowserHealth(manifest.mission_id, manifest.instance_id, now, True, runtime.daemon_pid, None, count)
    except BrowserBlocked as exc:
        return BrowserHealth(manifest.mission_id, manifest.instance_id, now, False, None, str(exc), count)


@dataclass(frozen=True)
class CaptureRequest:
    request_id: str
    url: str
    data_class: str = "controlled_test"
    max_state_checks: int = 10
    timeout_seconds: float = 10


@dataclass(frozen=True)
class CaptureReceipt:
    mission_id: str
    instance_id: str
    manifest_sha256: str
    request_id: str
    requested_at: float
    captured_at: float | None
    finished_at: float
    state: str
    origin: str | None
    request_count: int
    error: str | None
    target_id: str | None
    png_sha256: str | None
    png_bytes: int
    width: int | None
    height: int | None
    background_requested: bool = True
    focus_activation_sent: bool = False
    focus_untouched_verified: bool = False
    uploaded: bool = False


@dataclass(frozen=True)
class CapturedPage:
    receipt: CaptureReceipt
    png: bytes | None


def _validate_png_chunks(png: bytes) -> None:
    cursor = len(PNG_SIGNATURE)
    has_data = False
    first = True
    while cursor + 12 <= len(png):
        length = struct.unpack(">I", png[cursor:cursor + 4])[0]
        kind = png[cursor + 4:cursor + 8]
        end = cursor + 12 + length
        if end > len(png) or not re.fullmatch(b"[A-Za-z]{4}", kind):
            raise BrowserBlocked("screenshot_png_invalid")
        data = png[cursor + 8:cursor + 8 + length]
        crc = struct.unpack(">I", png[cursor + 8 + length:end])[0]
        if crc != zlib.crc32(kind + data) & 0xffffffff:
            raise BrowserBlocked("screenshot_png_invalid")
        if first and (kind != b"IHDR" or length != 13):
            raise BrowserBlocked("screenshot_png_invalid")
        first = False
        has_data = has_data or kind == b"IDAT"
        if kind == b"IEND":
            if length != 0 or end != len(png) or not has_data:
                raise BrowserBlocked("screenshot_png_invalid")
            return
        cursor = end
    raise BrowserBlocked("screenshot_png_invalid")


def capture_page(manifest: BrowserManifest, runtime: RuntimeEvidence, transport: BrowserTransport,
                 request: CaptureRequest, *, clock: Callable[[], float] = time.time,
                 pause: Callable[[float], None] = time.sleep) -> CapturedPage:
    """Capture one background target, returning PNG bytes to the root controller.

    No default tab enumeration, focus activation, raw page text, credentials,
    model calls, uploads, or arbitrary JavaScript. OS foreground parity requires
    separate before/after evidence; the receipt never invents that verification.
    """
    manifest.validate()
    if not _ID.fullmatch(request.request_id) or request.data_class not in {"public", "controlled_test"}:
        raise BrowserBlocked("bounded_public_or_controlled_capture_required")
    if _origin(request.url) not in manifest.allowed_origins:
        raise BrowserBlocked("page_origin_not_authorized")
    if type(request.max_state_checks) is not int or not 1 <= request.max_state_checks <= 10 or not 0 < request.timeout_seconds <= 15:
        raise BrowserBlocked("bounded_capture_request_required")
    requested_at = clock()
    deadline = requested_at + request.timeout_seconds
    health = probe_health(manifest, runtime, transport, now=requested_at)
    count = health.request_count
    target_id = None
    current_origin = None
    png = None
    width = height = None
    captured_at = None
    error = health.error

    def send(method: str, params: dict, session_id: str | None = None) -> Mapping[str, object]:
        nonlocal count
        remaining = deadline - clock()
        if remaining <= 0:
            raise BrowserBlocked("capture_deadline_exceeded")
        payload = {"method": method, "params": params}
        if session_id is not None:
            payload["session_id"] = session_id
        _validate_payload(manifest, payload)
        count += 1
        reply = transport.request(manifest, payload, timeout=min(remaining, 2))
        if reply.get("error"):
            raise BrowserBlocked("isolated_browser_operation_failed")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise BrowserBlocked("invalid_browser_result")
        return result

    if health.healthy:
        try:
            target = send("Target.createTarget", {"url": "about:blank", "background": True})
            target_id = target.get("targetId")
            if not isinstance(target_id, str) or not _ID.fullmatch(target_id):
                target_id = None
                raise BrowserBlocked("invalid_owned_target_id")
            attached = send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
            session_id = attached.get("sessionId")
            if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
                raise BrowserBlocked("invalid_owned_session_id")
            send("Page.enable", {}, session_id)
            navigation = send("Page.navigate", {"url": request.url}, session_id)
            if navigation.get("errorText") or navigation.get("isDownload"):
                raise BrowserBlocked("navigation_failed_or_download")
            ready = False
            for index in range(request.max_state_checks):
                evaluated = send("Runtime.evaluate", {"expression": PAGE_STATE_EXPRESSION, "returnByValue": True}, session_id)
                value = evaluated.get("result", {}).get("value") if isinstance(evaluated.get("result"), dict) else None
                if not isinstance(value, dict) or evaluated.get("exceptionDetails"):
                    raise BrowserBlocked("page_state_unavailable")
                current_origin = value.get("origin")
                if current_origin == "null" and value.get("path") == "blank":
                    pass  # Initial about:blank may precede committed navigation.
                elif current_origin not in manifest.allowed_origins:
                    current_origin = None
                    raise BrowserBlocked("redirect_origin_not_authorized")
                elif value.get("ready") == "complete":
                    ready = True
                    break
                if index < request.max_state_checks - 1:
                    pause(min(0.1, max(0, deadline - clock())))
            if not ready:
                raise BrowserBlocked("page_not_ready_within_bound")
            screenshot = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, session_id)
            encoded = screenshot.get("data")
            if not isinstance(encoded, str) or len(encoded) > ((manifest.max_capture_bytes + 2) // 3) * 4:
                raise BrowserBlocked("screenshot_payload_size_invalid")
            try:
                png = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise BrowserBlocked("screenshot_encoding_invalid") from exc
            if len(png) > manifest.max_capture_bytes or len(png) < 24 or not png.startswith(PNG_SIGNATURE) or png[12:16] != b"IHDR":
                png = None
                raise BrowserBlocked("screenshot_png_invalid")
            width, height = struct.unpack(">II", png[16:24])
            if not 1 <= width <= 4096 or not 1 <= height <= 4096 or width * height > 4_000_000:
                png = None
                raise BrowserBlocked("screenshot_dimensions_exceed_bound")
            _validate_png_chunks(png)
            captured_at = clock()
            error = None
        except BrowserBlocked as exc:
            error = str(exc)
            png = None
        finally:
            # Close only this request's newly created target. Never shutdown the
            # daemon, its original target, or any other browser/profile.
            if target_id is not None:
                try:
                    send("Target.closeTarget", {"targetId": target_id})
                except BrowserBlocked:
                    error = error or "owned_target_cleanup_unverified"
    finished_at = clock()
    receipt = CaptureReceipt(manifest.mission_id, manifest.instance_id, manifest.fingerprint, request.request_id,
                             requested_at, captured_at, finished_at, "captured" if png is not None else "failed",
                             current_origin, count, error, target_id, hashlib.sha256(png).hexdigest() if png else None,
                             len(png) if png else 0, width if png else None, height if png else None)
    return CapturedPage(receipt, png)
