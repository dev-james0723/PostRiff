"""Local metadata collector service; no inference, task dispatch, or hook changes.

Reviewed policy and polling configuration are separate, private JSON files at
the exact canonical .runtime paths. Policy registers finite workspace/project
mappings and upload hosts. Config can select only their subset. All private
file paths are fixed; no config field supplies commands or source text.

LaunchAgent argv preview (installation is the coordinator's separate action):
  /absolute/python3 -m agent_team.service
    --policy CANONICAL_ROOT/.runtime/service-policy.json
    --config CANONICAL_ROOT/.runtime/service-config.json
    --daemon

Set the working directory to the installed Python package root. KeepAlive must
use an interval/throttle of at least 300 seconds. This module does not create a
plist, start launchd, change a source, or grant any upload permission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .collector import LUCI_SHIM, TYPELESS_DB, TYPELESS_INFO, collect_once
from .events import Event, Journal, canonical
from .native import collect_codex_metadata
from .periods import aware
from .transport import send_pending
from .audio_bridge import produce_pending


CANONICAL_ROOT = Path.home()/"Documents/James-Agent-Team"
INGRESS_PATH = "/api/internal/james-agent-team/events"
_IDENTITY = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
_HOST = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}")


def _exact_absolute(value: Any) -> Path:
    if not isinstance(value, str) or not value or len(value) > 2_048 or "\x00" in value:
        raise ValueError("exact_absolute_path_required")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "*" in value or "?" in value or "~" in value:
        raise ValueError("exact_absolute_path_required")
    if str(path) != value or path.is_symlink() or path.resolve() != path:
        raise ValueError("path_alias_not_allowed")
    return path


def _fixed_private_path(value: Any, expected: Path, *, existing: bool = False) -> Path:
    path = _exact_absolute(value)
    if path != expected:
        raise ValueError("private_path_not_allowlisted")
    # Existing directories are checked before any journal/token access. A
    # missing runtime can be created by Journal with mode 0700 after validation.
    runtime = expected.parent
    if runtime.exists():
        info = runtime.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("private_runtime_directory_required")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("private_regular_file_required")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("current_owner_required")
    elif existing:
        raise ValueError("private_file_missing")
    return path


def _keys(value: Any, allowed: set[str], required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        raise ValueError("config_fields_not_allowlisted")
    return value


@dataclass(frozen=True)
class NativeRegistration:
    workspace: Path
    project_id: str


@dataclass(frozen=True)
class ServicePolicy:
    canonical_root: Path
    approved_native_projects: tuple[NativeRegistration, ...] = ()
    allowed_upload_hosts: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, canonical_root: Path = CANONICAL_ROOT) -> "ServicePolicy":
        data = _keys(payload, {"version", "canonical_root", "approved_native_projects", "allowed_upload_hosts"},
                     {"version", "canonical_root", "approved_native_projects", "allowed_upload_hosts"})
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("policy_version_unsupported")
        root = _exact_absolute(data["canonical_root"])
        if root != canonical_root:
            raise ValueError("canonical_root_mismatch")
        projects = data["approved_native_projects"]
        if not isinstance(projects, dict) or len(projects) > 8:
            raise ValueError("native_registration_limit")
        registrations: list[NativeRegistration] = []
        for workspace, project_id in projects.items():
            path = _exact_absolute(workspace)
            if not isinstance(project_id, str) or not _IDENTITY.fullmatch(project_id):
                raise ValueError("approved_project_identity_required")
            registrations.append(NativeRegistration(path, project_id))
        hosts = data["allowed_upload_hosts"]
        if (not isinstance(hosts, list) or len(hosts) > 4
                or any(not isinstance(host, str) or not _HOST.fullmatch(host) for host in hosts)
                or len(set(hosts)) != len(hosts)):
            raise ValueError("exact_upload_host_allowlist_required")
        return cls(root, tuple(sorted(registrations, key=lambda item: str(item.workspace))), tuple(hosts))


@dataclass(frozen=True)
class UploadConfig:
    endpoint: str
    token_file: Path
    limit: int = 100


@dataclass(frozen=True)
class ServiceConfig:
    policy: ServicePolicy
    journal_path: Path
    interval_seconds: int = 300
    window_seconds: int = 600
    typeless: bool = True
    luci: bool = False
    native_workspaces: tuple[NativeRegistration, ...] = ()
    upload: UploadConfig | None = None
    audio: bool = False

    def validate(self) -> "ServiceConfig":
        """Recheck even directly constructed configs at every public entry point."""
        payload = {"version": 1, "journal_path": str(self.journal_path),
                   "interval_seconds": self.interval_seconds, "window_seconds": self.window_seconds,
                   "typeless": self.typeless, "luci": self.luci,
                   "audio": self.audio,
                   "native_workspaces": [{"workspace": str(item.workspace), "project_id": item.project_id}
                                         for item in self.native_workspaces],
                   "upload": None if self.upload is None else {
                       "endpoint": self.upload.endpoint, "token_file": str(self.upload.token_file),
                       "limit": self.upload.limit}}
        ServiceConfig.from_mapping(payload, self.policy)
        return self

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], policy: ServicePolicy) -> "ServiceConfig":
        data = _keys(payload, {"version", "journal_path", "interval_seconds", "window_seconds", "audio",
                               "typeless", "luci", "native_workspaces", "upload"},
                     {"version", "journal_path", "interval_seconds", "window_seconds",
                      "typeless", "luci", "native_workspaces", "upload"})
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("config_version_unsupported")
        runtime = policy.canonical_root / ".runtime"
        journal = _fixed_private_path(data["journal_path"], runtime / "journal.sqlite3")
        interval, window = data["interval_seconds"], data["window_seconds"]
        if type(interval) is not int or not 300 <= interval <= 86_400:
            raise ValueError("poll_interval_out_of_bounds")
        if type(window) is not int or not 1 <= window <= 3_600:
            raise ValueError("source_window_out_of_bounds")
        if type(data["typeless"]) is not bool or type(data["luci"]) is not bool:
            raise ValueError("explicit_source_flags_required")
        if type(data.get("audio",False)) is not bool:
            raise ValueError("explicit_audio_flag_required")
        projects = {str(item.workspace): item.project_id for item in policy.approved_native_projects}
        requested = data["native_workspaces"]
        if not isinstance(requested, list) or len(requested) > 8:
            raise ValueError("native_registration_limit")
        selected: list[NativeRegistration] = []
        for item in requested:
            registration = _keys(item, {"workspace", "project_id"}, {"workspace", "project_id"})
            workspace = _exact_absolute(registration["workspace"])
            project_id = registration["project_id"]
            if str(workspace) not in projects or projects[str(workspace)] != project_id:
                raise ValueError("native_workspace_project_not_approved")
            if any(existing.workspace == workspace for existing in selected):
                raise ValueError("duplicate_native_workspace")
            selected.append(NativeRegistration(workspace, project_id))
        upload = None
        if data["upload"] is not None:
            details = _keys(data["upload"], {"endpoint", "token_file", "limit"}, {"endpoint", "token_file", "limit"})
            endpoint = details["endpoint"]
            if not isinstance(endpoint, str) or len(endpoint) > 2_048:
                raise ValueError("dedicated_https_ingress_required")
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query
                    or parsed.fragment or parsed.path != INGRESS_PATH or parsed.hostname not in policy.allowed_upload_hosts
                    or parsed.netloc != parsed.hostname):
                raise ValueError("upload_target_not_allowlisted")
            token = _fixed_private_path(details["token_file"], runtime / "cloud-ingress.token")
            limit = details["limit"]
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("upload_limit_out_of_bounds")
            upload = UploadConfig(endpoint, token, limit)
        if data.get("audio",False) and upload is None:
            raise ValueError("audio_requires_authenticated_upload")
        return cls(policy, journal, interval, window, data["typeless"], data["luci"], tuple(selected), upload, data.get("audio",False))


def _read_private_json(path: Path, expected: Path) -> Mapping[str, Any]:
    registered = _fixed_private_path(str(path), expected, existing=True)
    with registered.open("rb") as stream:
        raw = stream.read(16_385)
    if len(raw) > 16_384:
        raise ValueError("config_file_out_of_bounds")
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_config_field")
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("config_object_required")
    return data


def load_config(config_path: Path, policy_path: Path, *, canonical_root: Path = CANONICAL_ROOT) -> ServiceConfig:
    root = _exact_absolute(str(canonical_root))
    runtime = root / ".runtime"
    policy = ServicePolicy.from_mapping(_read_private_json(policy_path, runtime / "service-policy.json"),
                                        canonical_root=root)
    return ServiceConfig.from_mapping(_read_private_json(config_path, runtime / "service-config.json"), policy)


def _source_connected(source: str, path: Path) -> bool:
    if source == "typeless":
        return TYPELESS_DB.is_file() and TYPELESS_INFO.is_file()
    if source == "luci":
        return LUCI_SHIM.is_file() and os.access(LUCI_SHIM, os.X_OK)
    if source == "native":
        return path.is_dir() and not path.is_symlink()
    return False


@dataclass(frozen=True)
class ServiceDependencies:
    audio: Callable[..., Mapping[str, Any]] = produce_pending
    collect: Callable[..., Mapping[str, Any]] = collect_once
    collect_native: Callable[..., Mapping[str, Any]] = collect_codex_metadata
    send: Callable[..., Mapping[str, Any]] = send_pending
    source_connected: Callable[[str, Path], bool] = _source_connected
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    monotonic: Callable[[], float] = time.monotonic
    wait: Callable[[float], Any] | None = None


def _health(journal: Any, source: str, status: str, gaps: list[str], now: datetime,
            *, project_id: str | None = None, kind: str = "source_coverage") -> bool:
    stamp = aware(now).isoformat()
    payload = {"kind": kind, "sourceStatus": status, "sourceFreshAt": stamp,
               "scanComplete": False, "gaps": gaps[:20], "count": 0}
    revision = hashlib.sha256(canonical([source, stamp, payload, project_id]).encode()).hexdigest()
    event = Event("health", source, revision, stamp, stamp, payload, project_id=project_id)
    try:
        journal.ingest([event])
        return True
    except Exception:
        # Exception strings can contain private paths or credentials. Emit only
        # fixed diagnostics; callers retain the same bounded poll cadence.
        return False


def one_tick(config: ServiceConfig, journal: Any,
             dependencies: ServiceDependencies | None = None) -> dict[str, Any]:
    config.validate()
    deps = dependencies or ServiceDependencies()
    now = aware(deps.wall_clock())
    states: dict[str, str] = {}
    gaps: set[str] = set()
    enabled = {"typeless": config.typeless, "luci": config.luci}
    connected: dict[str, bool] = {}
    for source, selected in enabled.items():
        if not selected:
            continue
        path = TYPELESS_DB if source == "typeless" else LUCI_SHIM
        try:
            connected[source] = deps.source_connected(source, path) is True
        except Exception:
            connected[source] = False
        if not connected[source]:
            states[source] = "not_connected"
            if not _health(journal, source, "not_connected", ["source_not_connected", "bounded_scan_only"], now):
                gaps.add("journal_write_failed")
    if any(connected.values()):
        try:
            result = deps.collect(journal, now, typeless=connected.get("typeless", False),
                                  luci=connected.get("luci", False), window_seconds=config.window_seconds)
            results = result.get("sources", {})
            for source, is_connected in connected.items():
                if is_connected:
                    state = results.get(source, {}).get("status", "unavailable")
                    states[source] = state if state in {"ok", "partial", "unavailable", "not_connected"} else "unavailable"
        except Exception:
            for source, is_connected in connected.items():
                if is_connected:
                    states[source] = "unavailable"
                    if not _health(journal, source, "unavailable", ["source_poll_failed", "bounded_scan_only"], now):
                        gaps.add("journal_write_failed")
    for registration in config.native_workspaces:
        source_ref = "codex:" + hashlib.sha256(str(registration.workspace).encode()).hexdigest()[:24]
        try:
            connected_native = deps.source_connected("native", registration.workspace) is True
        except Exception:
            connected_native = False
        if not connected_native:
            status, source_gaps = "not_connected", ["workspace_not_connected", "bounded_scan_only"]
        else:
            try:
                native = deps.collect_native(journal, str(registration.workspace), project_id=registration.project_id)
                value = native.get("status", "unavailable")
                status = value if value in {"ok", "partial", "unavailable", "not_connected"} else "unavailable"
                source_gaps = ["bounded_scan_only", "writer_ownership_unproven"]
            except Exception:
                status, source_gaps = "unavailable", ["native_poll_failed", "bounded_scan_only"]
        states[source_ref] = status
        if not _health(journal, source_ref, status, source_gaps, now, project_id=registration.project_id):
            gaps.add("journal_write_failed")
    collector_status = "ok" if all(state == "ok" for state in states.values()) else "partial"
    if not _health(journal, "collector_service", collector_status, sorted(gaps), now, kind="collector_heartbeat"):
        gaps.add("journal_write_failed")
    upload_state = "not_configured"
    audio_state = "not_configured"
    if config.upload is not None:
        try:
            upload = config.upload
            _fixed_private_path(str(upload.token_file), config.policy.canonical_root / ".runtime/cloud-ingress.token", existing=True)
            delivery = deps.send(journal, upload.endpoint, upload.token_file, now.isoformat(), limit=upload.limit)
            value = delivery.get("state", "unavailable")
            upload_state = value if value in {"empty", "acknowledged"} else "unavailable"
        except (OSError, ValueError):
            upload_state = "not_connected"
        except Exception:
            upload_state = "unavailable"
        upload_gaps = [] if upload_state in {"empty", "acknowledged"} else ["upload_not_connected_or_failed"]
        if not _health(journal, "cloud_ingress", upload_state, upload_gaps, now):
            gaps.add("journal_write_failed")
        if config.audio and upload_state in {"empty", "acknowledged"}:
            try:
                receipt=deps.audio(upload.endpoint,upload.token_file,config.policy.canonical_root)
                audio_state=receipt["state"] if receipt.get("state") in {"idle","stored"} else "unavailable"
            except Exception:
                audio_state="unavailable"
                gaps.add("audio_generation_or_ingress_failed")
        elif config.audio:
            audio_state="not_connected"
    return {"executionState": "real_local_metadata_collection", "observedAt": now.isoformat(),
            "status": "partial" if (gaps or any(state != "ok" for state in states.values())
                                      or upload_state not in {"not_configured", "empty", "acknowledged"}) else "ok",
            "sources": states, "gaps": sorted(gaps), "dailyCoverageComplete": False,
            "upload": upload_state, "audio":audio_state,"taskDispatch": "not_requested", "inference": "not_requested"}


def run_daemon(config: ServiceConfig, journal: Any, dependencies: ServiceDependencies | None = None,
               *, stop_event: threading.Event | None = None, max_ticks: int | None = None,
               on_tick: Callable[[Mapping[str, Any]], Any] | None = None) -> int:
    """Sequential polls on monotonic deadlines. Overruns skip catch-up bursts."""
    config.validate()
    if max_ticks is not None and (type(max_ticks) is not int or not 1 <= max_ticks <= 10_000):
        raise ValueError("tick_limit_out_of_bounds")
    deps = dependencies or ServiceDependencies()
    stop = stop_event or threading.Event()
    wait = deps.wait or stop.wait
    deadline = deps.monotonic()
    ticks = 0
    while not stop.is_set():
        try:
            result = one_tick(config, journal, deps)
        except Exception:
            result = {"executionState": "collector_tick_failed", "status": "unavailable",
                      "gaps": ["tick_failed"], "dailyCoverageComplete": False}
        if on_tick is not None:
            try:
                on_tick(result)
            except Exception:
                _health(journal, "collector_output", "unavailable", ["output_receipt_failed"],
                        aware(deps.wall_clock()), kind="collector_heartbeat")
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        deadline += config.interval_seconds
        completed_at = deps.monotonic()
        if completed_at >= deadline:
            deadline = completed_at + config.interval_seconds
        while not stop.is_set():
            remaining = deadline - deps.monotonic()
            if remaining <= 0:
                break
            wait(min(remaining, 30.0))
    return ticks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="james-agent-team-service")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--daemon", action="store_true")
    args = parser.parse_args(argv)
    journal = None
    try:
        config = load_config(args.config, args.policy)
        journal = Journal(config.journal_path)
        if args.once:
            print(canonical(one_tick(config, journal)), flush=True)
        else:
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            run_daemon(config, journal, stop_event=stop,
                       on_tick=lambda result: print(canonical(result), flush=True))
        return 0
    except Exception:
        print(canonical({"status": "unavailable", "gaps": ["service_configuration_or_journal_failed"]}), flush=True)
        return 2
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
