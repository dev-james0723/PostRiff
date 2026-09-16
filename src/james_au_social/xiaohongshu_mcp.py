"""Secret-blind supervisor for the pinned local Xiaohongshu browser driver.

The supervisor may start the reviewed binaries, make allowlisted identity
checks, and submit an immutable image-note payload supplied by Studio's
managed publishing boundary. It never returns the MCP bearer token, cookie
bytes, xsec values, or raw provider responses.
"""
from __future__ import annotations

import hashlib
import base64
import binascii
import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import httpx

from .studio import StudioError, _no_symlinks


class XiaohongshuMcpSupervisor:
    VERSION = "v2.5.0+studio-rednote.1"
    UPSTREAM_VERSION = "v2.5.0"
    UPSTREAM_COMMIT = "6583124dfda92312b6bc19a042a6acfae63fe498"
    REDNOTE_PATCH_COMMIT = "b4cd95a55909c2d4ebed14013affe4258926191c"
    COMMIT = "9f073e1bc31cdd5a6a304e8f09e7978b542f4d02"
    SITE = "rednote"
    PORT = 18060
    KEYCHAIN_SERVICE = "James Au Studio Xiaohongshu MCP"
    KEYCHAIN_ACCOUNT = "local-service"
    SERVER_SHA256 = "3701f03de645de319b881ed55e8e85cf14897db9bbf3d35478934bebb5209ced"
    LOGIN_SHA256 = "803c32f0cf8d7741e384b92c9e2f8dbe205593572db04ed102d24261e103daee"
    DOCKER_CONTEXT = "colima-james-au-xhs-amd64"
    CONTAINER_NAME = "james-au-xhs-mcp"
    CONTAINER_IMAGE = (
        "xpzouying/xiaohongshu-mcp@"
        "sha256:88e2603f324f567e0a254ed7a1e24d632a16eccc30e84ef3fb887e34a03d0fe3"
    )
    CONTAINER_COOKIE_PATH = "/app/data/cookies.json"
    CONTAINER_READ_PATHS = frozenset((
        "/health", "/api/v1/login/status", "/api/v1/login/qrcode", "/api/v1/user/me",
    ))
    PUBLISH_PATH = "/api/v1/publish"
    ALLOWED_OPERATIONS = (
        "check_login_status", "current_user_identity", "publish_image_note",
        "publish_video_note", "schedule_image_note", "schedule_video_note",
    )
    DISABLED_OPERATIONS = (
        "comments", "replies", "likes", "favorites", "follows",
        "notification_writes", "product_binding", "account_switching",
        "cookie_reset", "unbound_uploads", "bulk_publish",
    )

    def __init__(self, connections_root: Path):
        self.root = Path(connections_root) / "xiaohongshu-mcp"
        self.driver_root = self.root / "driver" / self.VERSION
        self.session_root = self.root / "session"
        self.runtime_home = self.root / "runtime-home"
        self.server_binary = self.driver_root / "xiaohongshu-mcp-darwin-arm64"
        self.login_binary = self.driver_root / "xiaohongshu-login-darwin-arm64"
        self.cookies_path = self.session_root / "cookies-rednote.json"
        self.route_record = self.root / "route-state.json"
        self.blocker_record = self.root / "driver-blocker.json"
        self.child: subprocess.Popen | None = None
        self.login_child: subprocess.Popen | None = None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _secure_file(path: Path, expected_hash: str, *, executable: bool) -> bool:
        try:
            _no_symlinks(path.parent)
            if path.is_symlink():
                return False
            info = path.stat()
            expected_mode = 0o700 if executable else 0o600
            return (stat.S_ISREG(info.st_mode) and info.st_mode & 0o777 == expected_mode
                    and XiaohongshuMcpSupervisor._sha256(path) == expected_hash)
        except OSError:
            return False

    def _ensure_private_directories(self):
        _no_symlinks(self.root)
        for path in (self.root, self.driver_root, self.session_root, self.runtime_home):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.is_symlink():
                raise StudioError("xiaohongshu_driver_invalid", "The local Xiaohongshu driver directory is invalid.", 500)
            path.chmod(0o700)

    def _keychain_token(self) -> str | None:
        security = shutil.which("security")
        if not security:
            return None
        try:
            result = subprocess.run(
                [security, "find-generic-password", "-a", self.KEYCHAIN_ACCOUNT,
                 "-s", self.KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        token = result.stdout.rstrip("\n") if result.returncode == 0 else ""
        return token if re.fullmatch(r"[0-9a-f]{64}", token) else None

    def _environment(self, *, include_token: bool) -> dict[str, str]:
        self._ensure_private_directories()
        environment = {
            key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ
        }
        environment["HOME"] = str(self.runtime_home)
        environment["COOKIES_PATH"] = str(self.cookies_path)
        if include_token:
            token = self._keychain_token()
            if token is None:
                raise StudioError("xiaohongshu_auth_unavailable", "The protected Xiaohongshu MCP service token is unavailable.", 503)
            environment["AUTH_TOKEN"] = token
        return environment

    def _server_installed(self) -> bool:
        return self._secure_file(self.server_binary, self.SERVER_SHA256, executable=True)

    def _login_installed(self) -> bool:
        return self._secure_file(self.login_binary, self.LOGIN_SHA256, executable=True)

    def _docker_binary(self) -> str | None:
        return shutil.which("docker")

    def _container_command(self, *args: str) -> list[str] | None:
        docker = self._docker_binary()
        if docker is None:
            return None
        return [docker, "--context", self.DOCKER_CONTEXT, *args]

    def _container_installed(self) -> bool:
        if not self.blocker_record.is_file() or self.blocker_record.is_symlink():
            return False
        command = self._container_command(
            "inspect", "--format", "{{.Config.Image}}", self.CONTAINER_NAME,
        )
        if command is None:
            return False
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=4, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == self.CONTAINER_IMAGE

    def _container_running(self) -> bool:
        command = self._container_command(
            "inspect", "--format", "{{.State.Running}}", self.CONTAINER_NAME,
        )
        if command is None:
            return False
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=4, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _container_app_running(self) -> bool:
        if not self._container_running():
            return False
        command = self._container_command(
            "exec", self.CONTAINER_NAME, "sh", "-c", "pgrep -x app >/dev/null",
        )
        if command is None:
            return False
        try:
            result = subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=4, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def _start_container_app(self):
        if self._container_app_running():
            return
        command = self._container_command(
            "exec", "-d", "-e", "AUTH_TOKEN",
            "-e", f"COOKIES_PATH={self.CONTAINER_COOKIE_PATH}",
            self.CONTAINER_NAME, "/app/app",
        )
        if command is None:
            return
        token = self._keychain_token()
        if token is None:
            raise StudioError(
                "xiaohongshu_auth_unavailable",
                "The protected Xiaohongshu MCP service token is unavailable.", 503,
            )
        environment = {
            key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ
        }
        environment["AUTH_TOKEN"] = token
        try:
            result = subprocess.run(
                command, env=environment, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=8, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        if result.returncode != 0:
            return
        for _ in range(80):
            if self._container_app_running():
                return
            time.sleep(0.05)

    def _container_session_stored(self) -> bool:
        if not self._container_running():
            return False
        command = self._container_command(
            "exec", self.CONTAINER_NAME, "sh", "-c",
            "test -f /app/data/cookies.json && stat -c '%a %s' /app/data/cookies.json",
        )
        if command is None:
            return False
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=4, check=False,
            )
            fields = result.stdout.strip().split() if result.returncode == 0 else []
            mode, size = (fields[0], int(fields[1])) if len(fields) == 2 else ("", 0)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return False
        return mode == "600" and 256 < size <= 1024 * 1024

    def _harden_container_session(self):
        if not self._container_running():
            return
        command = self._container_command(
            "exec", self.CONTAINER_NAME, "sh", "-c",
            "test -f /app/data/cookies.json && chmod 600 /app/data/cookies.json",
        )
        if command is None:
            return
        try:
            subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=4, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return

    def _harden_native_session(self):
        try:
            _no_symlinks(self.cookies_path.parent)
            descriptor = os.open(
                self.cookies_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
        except OSError:
            return
        try:
            info = os.fstat(descriptor)
            if stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 1024 * 1024:
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)

    def _container_request(self, path: str):
        if path not in self.CONTAINER_READ_PATHS:
            raise StudioError(
                "xiaohongshu_operation_blocked",
                "That Xiaohongshu MCP operation is not allowlisted.", 403,
            )
        if not self._container_running():
            raise StudioError(
                "xiaohongshu_driver_unavailable",
                "The isolated Xiaohongshu MCP container is unavailable.", 503,
            )
        token = self._keychain_token()
        if token is None:
            raise StudioError(
                "xiaohongshu_auth_unavailable",
                "The protected Xiaohongshu MCP service token is unavailable.", 503,
            )
        command = self._container_command(
            "exec", "-i", self.CONTAINER_NAME, "curl", "--config", "-",
        )
        if command is None:
            raise StudioError(
                "xiaohongshu_driver_unavailable",
                "The isolated Xiaohongshu MCP container is unavailable.", 503,
            )
        configuration = (
            f'url = "http://127.0.0.1:{self.PORT}{path}"\n'
            f'header = "Authorization: Bearer {token}"\n'
            'request = "GET"\nconnect-timeout = 5\nmax-time = 45\n'
            'fail-with-body\nsilent\nshow-error\n'
        )
        try:
            result = subprocess.run(
                command, input=configuration, capture_output=True, text=True,
                timeout=50, check=False,
            )
            if result.returncode != 0:
                raise StudioError(
                    "xiaohongshu_session_unverified",
                    "The Xiaohongshu browser session could not be verified.", 409,
                )
            return json.loads(result.stdout)
        except StudioError:
            raise
        except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
            raise StudioError(
                "xiaohongshu_session_unverified",
                "The Xiaohongshu browser session could not be verified.", 409,
            ) from None

    def _session_stored(self) -> bool:
        if self._container_installed():
            return self._container_session_stored()
        try:
            if self.cookies_path.is_symlink():
                return False
            info = self.cookies_path.stat()
            return stat.S_ISREG(info.st_mode) and info.st_mode & 0o777 == 0o600 and 0 < info.st_size <= 1024 * 1024
        except OSError:
            return False

    def _running(self) -> bool:
        return (self._container_app_running()
                or (self.child is not None and self.child.poll() is None))

    def start(self):
        if self._running():
            return
        if self._container_installed():
            if not self._container_running():
                command = self._container_command("start", self.CONTAINER_NAME)
                if command is not None:
                    try:
                        subprocess.run(
                            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=15, check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        return
            if self._container_running():
                self._start_container_app()
            return
        if self.blocker_record.is_file() and not self.blocker_record.is_symlink():
            return
        if not self._server_installed() or not self._login_installed():
            return
        environment = self._environment(include_token=True)
        self.child = subprocess.Popen(
            [str(self.server_binary), "-port", f"127.0.0.1:{self.PORT}",
             "-headless=true", "-site", self.SITE],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=self.runtime_home, env=environment,
        )
        for _ in range(80):
            if self.child.poll() is not None:
                self.child = None
                return
            try:
                with httpx.Client(trust_env=False, timeout=0.5) as client:
                    if client.get(f"http://127.0.0.1:{self.PORT}/health").status_code == 200:
                        return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)

    def begin_private_login(self):
        if self._container_installed():
            if not self._container_app_running():
                raise StudioError(
                    "xiaohongshu_driver_unavailable",
                    "The isolated Xiaohongshu MCP service is unavailable.", 503,
                )
            response = self._request("/api/v1/login/qrcode")
            try:
                data = response["data"]
                logged_in = data["is_logged_in"] is True
                image = data.get("img", "")
                timeout = data["timeout"]
            except (KeyError, TypeError):
                raise StudioError(
                    "xiaohongshu_login_unavailable",
                    "The private Xiaohongshu login QR could not be prepared.", 409,
                ) from None
            if logged_in:
                return {
                    "state": "private_handoff", "qrImage": None,
                    "expiresInSeconds": 0,
                    "resumePhrase": "Xiaohongshu private login complete",
                    "publishing": False,
                }
            match = re.fullmatch(
                r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", image,
            )
            try:
                image_bytes = base64.b64decode(match.group(1), validate=True) if match else b""
            except (binascii.Error, ValueError):
                image_bytes = b""
            if not image_bytes or len(image_bytes) > 1024 * 1024 or timeout != "4m0s":
                raise StudioError(
                    "xiaohongshu_login_unavailable",
                    "The private Xiaohongshu login QR could not be prepared.", 409,
                )
            return {
                "state": "private_handoff", "qrImage": image,
                "expiresInSeconds": 240,
                "resumePhrase": "Xiaohongshu private login complete",
                "publishing": False,
            }
        if not self._login_installed():
            raise StudioError("xiaohongshu_driver_unavailable", "The reviewed Xiaohongshu login helper is unavailable.", 503)
        if self.login_child is not None and self.login_child.poll() is None:
            raise StudioError("xiaohongshu_login_pending", "The private Xiaohongshu login window is already open.", 409)
        self.login_child = subprocess.Popen(
            [str(self.login_binary), "-site", self.SITE], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=self.runtime_home, env=self._environment(include_token=False),
        )
        return {
            "state": "private_handoff",
            "resumePhrase": "Xiaohongshu private login complete",
            "publishing": False,
        }

    def _request(self, path: str):
        if self._container_installed():
            return self._container_request(path)
        if not self._running():
            raise StudioError("xiaohongshu_driver_unavailable", "The local Xiaohongshu MCP service is unavailable.", 503)
        token = self._keychain_token()
        if token is None:
            raise StudioError("xiaohongshu_auth_unavailable", "The protected Xiaohongshu MCP service token is unavailable.", 503)
        try:
            with httpx.Client(trust_env=False, timeout=45) as client:
                response = client.get(
                    f"http://127.0.0.1:{self.PORT}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code != 200:
                raise StudioError("xiaohongshu_session_unverified", "The Xiaohongshu browser session could not be verified.", 409)
            return response.json()
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError("xiaohongshu_session_unverified", "The Xiaohongshu browser session could not be verified.", 409) from None

    def publish_image_note(self, payload: dict):
        """Submit a Studio-reviewed image note without exposing secret material."""
        if not isinstance(payload, dict) or set(payload) != {
            "title", "content", "images", "tags", "is_original", "visibility",
        }:
            raise StudioError("xiaohongshu_publish_manifest_invalid", "The Xiaohongshu publish manifest is invalid.", 422)
        if (not isinstance(payload["title"], str) or not payload["title"].strip()
                or not isinstance(payload["content"], str) or not payload["content"].strip()
                or not isinstance(payload["images"], list) or len(payload["images"]) != 1
                or not isinstance(payload["images"][0], str)
                or not isinstance(payload["tags"], list) or payload["tags"]
                or payload["is_original"] is not True
                or payload["visibility"] != "公开可见"):
            raise StudioError("xiaohongshu_publish_manifest_invalid", "The Xiaohongshu publish manifest is invalid.", 422)
        # The current container bridge is deliberately read-only. Its transport
        # cannot safely carry a separately bounded JSON body. Studio's reviewed
        # native loopback driver sends JSON through httpx, keeping the bearer out
        # of process arguments and logs.
        if self._container_installed():
            raise StudioError(
                "xiaohongshu_native_publish_required",
                "The managed Xiaohongshu publish bridge requires the reviewed native loopback driver.",
                503,
            )
        if not self._running():
            raise StudioError("xiaohongshu_driver_unavailable", "The local Xiaohongshu MCP service is unavailable.", 503)
        token = self._keychain_token()
        if token is None:
            raise StudioError("xiaohongshu_auth_unavailable", "The protected Xiaohongshu MCP service token is unavailable.", 503)
        try:
            with httpx.Client(trust_env=False, timeout=120) as client:
                response = client.post(
                    f"http://127.0.0.1:{self.PORT}{self.PUBLISH_PATH}", json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code != 200:
                raise StudioError(
                    "xiaohongshu_publish_unresolved",
                    "The Xiaohongshu driver did not confirm publication. Reconcile the profile before retrying.",
                    409,
                )
            value = response.json()
            data = value.get("data") if isinstance(value, dict) else None
            if (value.get("success") is not True or not isinstance(data, dict)
                    or data.get("title") != payload["title"]
                    or data.get("content") != payload["content"]
                    or data.get("images") != 1):
                raise StudioError(
                    "xiaohongshu_publish_unresolved",
                    "The Xiaohongshu driver did not return bounded publication evidence. Reconcile the profile before retrying.",
                    409,
                )
            return {"accepted": True}
        except StudioError:
            raise
        except (httpx.HTTPError, ValueError):
            raise StudioError(
                "xiaohongshu_publish_unresolved",
                "The Xiaohongshu publish attempt could not be confirmed. Reconcile the profile before retrying.",
                409,
            ) from None

    def verify_published_title(self, title: str) -> bool:
        """Check the current user's bounded feed list without returning feed tokens."""
        current = self._request("/api/v1/user/me")
        try:
            feeds = current["data"]["data"].get("feeds", [])
        except (KeyError, TypeError):
            return False
        if not isinstance(feeds, list) or len(feeds) > 100:
            return False
        for feed in feeds:
            try:
                display_title = feed["noteCard"]["displayTitle"]
            except (KeyError, TypeError):
                continue
            if display_title == title:
                return True
        return False

    def verify_identity(self, *, expected_rednote_id: str, expected_nickname: str):
        if self._container_installed():
            self._harden_container_session()
        else:
            self._harden_native_session()
        if not self._session_stored():
            raise StudioError("xiaohongshu_session_missing", "Complete the private Xiaohongshu login first.", 409)
        login = self._request("/api/v1/login/status")
        if not isinstance(login, dict) or login.get("success") is not True or login.get("data", {}).get("is_logged_in") is not True:
            raise StudioError("xiaohongshu_session_unverified", "The Xiaohongshu browser session is not signed in.", 409)
        current = self._request("/api/v1/user/me")
        try:
            basic = current["data"]["data"]["userBasicInfo"]
            actual_rednote_id = basic["redId"]
            actual_nickname = basic["nickname"]
        except (KeyError, TypeError):
            raise StudioError("xiaohongshu_identity_unresolved", "The signed-in Xiaohongshu identity could not be verified.", 409) from None
        if actual_rednote_id != expected_rednote_id or actual_nickname != expected_nickname:
            raise StudioError("identity_mismatch", "The signed-in Xiaohongshu account does not match the approved identity.", 409)
        record = {
            "state": "authenticated_route_test_required",
            "provider": "xpzouying/xiaohongshu-mcp",
            "version": self.VERSION,
            "commit": self.COMMIT,
            "upstreamVersion": self.UPSTREAM_VERSION,
            "upstreamCommit": self.UPSTREAM_COMMIT,
            "rednotePatchCommit": self.REDNOTE_PATCH_COMMIT,
            "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "identitySignals": ["post_auth_current_user_rednote_id", "post_auth_current_user_nickname"],
            "publishReady": False,
        }
        if self.route_record.is_symlink():
            raise StudioError("xiaohongshu_route_record_invalid", "The Xiaohongshu route record is invalid.", 500)
        descriptor = os.open(
            self.route_record,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(record, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        self.route_record.chmod(0o600)
        return record

    def status(self):
        container_installed = self._container_installed()
        native_installed = self._server_installed() and self._login_installed()
        installed = container_installed or native_installed
        running = self._running()
        if native_installed and not container_installed:
            self._harden_native_session()
        session_stored = self._session_stored()
        native_blocked = self.blocker_record.is_file() and not self.blocker_record.is_symlink()
        authenticated = False
        route_state = "private_login_required" if installed and running else "driver_stopped"
        if self.route_record.is_file() and not self.route_record.is_symlink():
            try:
                record = json.loads(self.route_record.read_text(encoding="utf-8"))
                authenticated = record.get("state") == "authenticated_route_test_required"
            except (OSError, ValueError, json.JSONDecodeError):
                authenticated = False
        if authenticated:
            route_state = "authenticated_route_test_required"
        elif session_stored:
            route_state = "authentication_verification_required"
        return {
            "driverInstalled": installed,
            "driverRunning": running,
            "driverVersion": self.VERSION if installed else None,
            "route": "browser" if installed else None,
            "routeDriver": (
                "local_mcp_browser_container" if container_installed
                else "local_mcp_browser_rednote" if installed else None
            ),
            "routeState": route_state,
            "serviceAuthenticated": self._keychain_token() is not None,
            "loopbackOnly": True if running else None,
            "noHostPort": True if container_installed else None,
            "executionMode": "isolated_container" if container_installed else "native_binary",
            "serviceBoundary": (
                "docker_socket_and_bearer" if container_installed else "loopback_bearer"
            ),
            "sessionStored": session_stored,
            "sessionOpaque": True,
            "allowedOperations": list(self.ALLOWED_OPERATIONS),
            "disabledOperations": list(self.DISABLED_OPERATIONS),
            "mutationsLocked": True,
            "driverBlocked": native_blocked and not container_installed,
            "blockerCode": "browser_runtime_integrity_failure" if native_blocked and not container_installed else None,
            "nativeBlockerCode": "browser_runtime_integrity_failure" if native_blocked else None,
        }

    def shutdown(self):
        for name in ("login_child", "child"):
            child = getattr(self, name)
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            setattr(self, name, None)
