"""Bounded metadata evidence from exact registrations; no task authority.

Public entry points are ``read_claude_metadata``, ``read_git_metadata`` and
``read_token_pilot_metadata``. Each returns EvidenceBatch. The caller may use
``journal.ingest(batch.events)`` and separately record ``batch.gaps`` as health
coverage. No journal, source, registry, hooks, Git or remote state is written.
``source_revision`` hashes selected metadata, not transcript/memory bodies.
Event revisions include observation time for current-state Git snapshots;
otherwise an unchanged timestamped source record has an unchanged Event key.

All returned objects, including as_dict(), are safe metadata projections: no
raw session IDs, local paths, branch names, workflow names, URLs, prompts,
thinking, tools' input/output, model names, credentials or memory text. Paths
and identities in configs are local inputs only. Registration must come from
the caller's approved exact map; path existence is not authorization.

Claude reads a bounded first line and tail of one exact JSONL. It recognizes
system/init headers, fixed system/progress categories and numeric assistant
or result usage only. Numeric usage events are samples per message/counter,
not summable invoices or task-completion proof. Unsupported schemas fail
visibly. Missing cwd is accepted only after an in-file verified init header.

Git status covers tracked paths only, with fsmonitor, hooks, global/system
config, optional locks and submodule recursion disabled. Optional gh calls
require gh_authorized=True, an exact executable, an explicit owner/repo, and
fixed GET endpoints for existing CI/deployments; no dispatch or authentication
setup. The runner is injectable for synthetic tests. No CLI is called at import.

Token Pilot uses existing .token-pilot/install.json + state.json (schema 2).
There is no authoritative remaining-token budget in that schema: budget stays
unknown. An optional exact existing per-session report may expose an already
observed count; estimates, costs, transcript paths and usage_analysis are never
followed or evaluated. A bounded scan is never daily/task coverage or recovery
ownership proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .events import Event, canonical

_IDENTITY = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_PROGRESS = frozenset({"agent_progress", "bash_progress", "hook_progress"})
_SYSTEM = frozenset({"init", "turn_duration", "compact_boundary", "stop_hook_summary"})
_CI_STATUS = frozenset({"queued", "in_progress", "completed", "requested", "waiting", "pending"})
_CI_CONCLUSION = frozenset({"success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required", "stale"})
_DEPLOYMENT_STATUS = frozenset({"error", "failure", "inactive", "pending", "queued", "in_progress", "success"})
_SESSION_STATUS = frozenset({"active", "completed", "blocked", "paused", "stale"})
_USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
_ERROR_CODES = frozenset({"timezone_required", "metadata_bounds_invalid", "path_not_registered", "source_missing",
    "regular_source_required", "registered_project_required", "duplicate_json_fields", "non_finite_json",
    "metadata_object_required", "metadata_json_invalid", "source_size_limit", "source_changed_during_read",
    "session_registration_invalid", "command_bounds_invalid", "cli_missing", "cli_timeout", "cli_output_limit",
    "cli_diagnostics_limit", "cli_failed", "cli_total_deadline", "git_config_not_allowlisted",
    "exact_git_root_required", "git_head_unknown", "git_status_schema_invalid",
    "token_pilot_registration_unsupported", "token_pilot_state_unsupported"})


class MetadataBlocked(ValueError):
    """Fixed codes only. Source strings and CLI diagnostics never reach errors."""


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _utc(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise MetadataBlocked("timezone_required")
    return dt.astimezone(timezone.utc)


def _iso(value: str | datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _stamp(value: Any, observed: str) -> str | None:
    try:
        stamp = _iso(value)
        return stamp if _utc(stamp) <= _utc(observed) else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class MetadataLimits:
    max_file_bytes: int = 1_048_576
    max_tail_bytes: int = 131_072
    max_line_bytes: int = 16_384
    max_lines: int = 100
    max_events: int = 100
    freshness_seconds: int = 600
    command_timeout_seconds: float = 2.0
    total_command_seconds: float = 5.0
    max_command_bytes: int = 131_072

    def validate(self) -> None:
        bounds = ((self.max_file_bytes, 1_024, 1_048_576), (self.max_tail_bytes, 256, 262_144),
                  (self.max_line_bytes, 128, 65_536), (self.max_lines, 1, 200),
                  (self.max_events, 1, 200), (self.freshness_seconds, 1, 86_400),
                  (self.max_command_bytes, 1_024, 262_144))
        if any(type(v) is not int or not low <= v <= high for v, low, high in bounds):
            raise MetadataBlocked("metadata_bounds_invalid")
        if (type(self.command_timeout_seconds) not in (int, float)
                or type(self.total_command_seconds) not in (int, float)
                or not (0 < self.command_timeout_seconds <= 2 and 0 < self.total_command_seconds <= 5)):
            raise MetadataBlocked("metadata_bounds_invalid")


@dataclass(frozen=True)
class EvidenceBatch:
    source: str
    status: str
    events: tuple[Event, ...] = ()
    gaps: tuple[str, ...] = ()
    fresh_at: str | None = None
    source_revision: str | None = None
    scanned: int = 0
    bounded_scan_complete: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    daily_coverage_complete: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "status": self.status,
                "events": [event.cloud() for event in self.events], "gaps": list(self.gaps),
                "freshAt": self.fresh_at, "sourceRevision": self.source_revision,
                "scanned": self.scanned, "boundedScanComplete": self.bounded_scan_complete,
                "dailyCoverageComplete": False, "metadata": dict(self.metadata),
                "executionState": "read_only_metadata", "writerOwnership": "unproven"}

    cloud_projection = as_dict


def _blocked(source: str, error: BaseException) -> EvidenceBatch:
    code = str(error) if isinstance(error, MetadataBlocked) and str(error) in _ERROR_CODES else "metadata_source_unavailable"
    missing = code in {"source_missing", "cli_missing"}
    return EvidenceBatch(source, "not_connected" if missing else "unavailable", gaps=(code,))


def _root(path: Path, registered: Path) -> Path:
    actual, allowed = Path(path), Path(registered)
    if (not actual.is_absolute() or actual != allowed or actual.resolve() != actual
            or allowed.resolve() != allowed):
        raise MetadataBlocked("path_not_registered")
    if not actual.is_dir():
        raise MetadataBlocked("source_missing")
    return actual


def _file(path: Path, allowed: Path) -> Path:
    actual, registered = Path(path), Path(allowed)
    if not actual.is_absolute() or actual != registered or actual.resolve() != actual:
        raise MetadataBlocked("path_not_registered")
    try:
        info = actual.lstat()
    except FileNotFoundError:
        raise MetadataBlocked("source_missing") from None
    if not stat.S_ISREG(info.st_mode):
        raise MetadataBlocked("regular_source_required")
    return actual


def _project(value: str) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise MetadataBlocked("registered_project_required")
    return value


def _object(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise MetadataBlocked("duplicate_json_fields")
            out[key] = value
        return out
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(MetadataBlocked("non_finite_json")))
        if not isinstance(value, dict):
            raise MetadataBlocked("metadata_object_required")
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise MetadataBlocked("metadata_json_invalid") from None


def _read_file(path: Path, cap: int, *, tail: bool = False, header_cap: int = 0):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise MetadataBlocked("regular_source_required")
        if not tail and before.st_size > cap:
            raise MetadataBlocked("source_size_limit")
        header = stream.readline(header_cap + 1) if header_cap else b""
        if len(header) > header_cap:
            header = b""
        offset = max(0, before.st_size - cap) if tail else 0
        stream.seek(offset)
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
        fingerprint = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if fingerprint(before) != fingerprint(after) or fingerprint(after) != fingerprint(current):
            raise MetadataBlocked("source_changed_during_read")
        if len(raw) > cap:
            raise MetadataBlocked("source_size_limit")
        return raw, header, offset, before


def _fresh(info, observed: str, limits: MetadataLimits, gaps: set[str]) -> str | None:
    stamp = _stamp(datetime.fromtimestamp(info.st_mtime, timezone.utc), observed)
    if stamp is None:
        gaps.add("source_timestamp_unknown_or_future")
    elif (_utc(observed) - _utc(stamp)).total_seconds() > limits.freshness_seconds:
        gaps.add("source_stale")
    return stamp


def _event(source: str, identity: Any, revision: Any, happened: str, observed: str,
           payload: dict[str, Any], project: str) -> Event:
    return Event(source, _hash(identity), _hash(revision), happened, observed, payload,
                 project_id=project).validate()


@dataclass(frozen=True)
class ClaudeMetadataConfig:
    log_path: Path
    allowed_log_path: Path
    workspace: Path
    registered_workspace: Path
    project_id: str
    session_id: str | None = None
    limits: MetadataLimits = field(default_factory=MetadataLimits)


def read_claude_metadata(config: ClaudeMetadataConfig, *, observed_at: str | datetime | None = None) -> EvidenceBatch:
    """One bounded metadata-only tail; journal Event keys de-duplicate overlaps."""
    source = "claude"
    try:
        limits = config.limits
        limits.validate()
        observed = _iso(observed_at or datetime.now(timezone.utc))
        root = _root(config.workspace, config.registered_workspace)
        project = _project(config.project_id)
        path = _file(config.log_path, config.allowed_log_path)
        if config.session_id is not None and (not isinstance(config.session_id, str) or not 1 <= len(config.session_id) <= 256):
            raise MetadataBlocked("session_registration_invalid")
        raw, header, offset, info = _read_file(path, limits.max_tail_bytes, tail=True, header_cap=limits.max_line_bytes)
        gaps: set[str] = set()
        fresh = _fresh(info, observed, limits, gaps)
        file_identity = _hash([str(path), info.st_dev, info.st_ino])
        source_revision = _hash([file_identity, info.st_size, info.st_mtime_ns])
        binding = None
        if header:
            try:
                row = _object(header)
                sid = row.get("session_id", row.get("sessionId"))
                if (row.get("type") == "system" and row.get("subtype") == "init"
                        and row.get("cwd") == str(root) and isinstance(sid, str) and 1 <= len(sid) <= 256
                        and (config.session_id is None or config.session_id == sid)):
                    binding = sid
            except MetadataBlocked:
                gaps.add("claude_header_invalid")
        if offset:
            raw = raw.split(b"\n", 1)[1] if b"\n" in raw else b""
            gaps.add("tail_window_only")
        lines = raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            lines.pop()
            gaps.add("incomplete_jsonl_tail")
        if len(lines) > limits.max_lines:
            lines = lines[-limits.max_lines:]
            gaps.add("line_limit")
        events: list[Event] = []
        keys: set[str] = set()
        selected: list[Any] = []
        for index, line in enumerate(lines):
            if len(line) > limits.max_line_bytes:
                gaps.add("record_size_limit")
                continue
            try:
                row = _object(line)
            except MetadataBlocked:
                gaps.add("claude_record_invalid")
                continue
            sid = row.get("session_id", row.get("sessionId"))
            if not isinstance(sid, str) or not 1 <= len(sid) <= 256:
                gaps.add("claude_session_missing")
                continue
            if ((config.session_id is not None and sid != config.session_id)
                    or (row.get("cwd") != str(root) and not ("cwd" not in row and binding == sid))):
                gaps.add("claude_workspace_or_session_mismatch")
                continue
            stamp = _stamp(row.get("timestamp"), observed)
            source_stamp = stamp or fresh
            if stamp is None:
                gaps.add("claude_record_timestamp_unknown")
                stamp = fresh or observed
            kind = row.get("type")
            if not isinstance(kind, str):
                gaps.add("claude_record_type_unsupported")
                continue
            message = row.get("message") if isinstance(row.get("message"), dict) else {}
            event_id = row.get("uuid") or message.get("id")
            # Position fallback is local-file metadata only. No body hash.
            identity = [file_identity, _hash(sid), _hash(event_id) if isinstance(event_id, str) and len(event_id) <= 256 else [offset, index]]
            payloads = []
            if kind == "system" and isinstance(row.get("subtype"), str) and row["subtype"] in _SYSTEM:
                subtype = row["subtype"]
                payloads.append({"kind": "claude_header" if subtype == "init" else "claude_progress_metadata",
                                 "reportedState": subtype + "_observed"})
                if subtype == "init":
                    binding = sid
            elif kind == "progress":
                data = row.get("data")
                if isinstance(data, dict) and isinstance(data.get("type"), str) and data["type"] in _PROGRESS:
                    payloads.append({"kind": "claude_progress_metadata", "reportedState": data["type"] + "_observed"})
                else:
                    gaps.add("claude_progress_schema_unsupported")
            elif kind not in {"assistant", "user", "result", "system"}:
                gaps.add("claude_record_type_unsupported")
            elif kind == "system":
                gaps.add("claude_system_schema_unsupported")
            usage = message.get("usage") if kind == "assistant" else row.get("usage") if kind == "result" else None
            if usage is not None:
                if not isinstance(usage, dict):
                    gaps.add("claude_usage_schema_unsupported")
                else:
                    for counter in _USAGE_FIELDS:
                        value = usage.get(counter)
                        if value is None:
                            continue
                        if type(value) is not int or not 0 <= value <= 1_000_000_000:
                            gaps.add("claude_usage_counter_invalid")
                            continue
                        payloads.append({"kind": "claude_usage_" + counter, "count": value,
                                         "reportedState": "recorded_counter_sample"})
            for payload in payloads:
                payload["origin"] = "read_only_jsonl_metadata"
                if source_stamp is not None:
                    payload["sourceFreshAt"] = source_stamp
                event = _event(source, [identity, payload["kind"]], [identity, stamp, payload], stamp, observed, payload, project)
                if event.key in keys:
                    continue
                if len(events) >= limits.max_events:
                    gaps.add("event_limit")
                    break
                keys.add(event.key)
                events.append(event)
                selected.append([event.source_id, event.revision])
        if not events:
            gaps.add("no_supported_claude_metadata")
        return EvidenceBatch(source, "partial" if gaps else "ok", tuple(events), tuple(sorted(gaps)),
                             fresh, source_revision, len(lines), not gaps,
                             {"selectedRecords": len(events), "contentExported": False,
                              "usageSemantics": "counter_samples_not_invoice", "selectedRevision": _hash(selected)})
    except (MetadataBlocked, OSError, ValueError, TypeError, OverflowError) as error:
        return _blocked(source, error)


CommandRunner = Callable[..., bytes]


def run_metadata_command(argv: Sequence[str], *, cwd: Path, timeout_seconds: float,
                         max_bytes: int, env: Mapping[str, str]) -> bytes:
    """Fixed adapter argv only; bounded pipes, no shell, no diagnostic export."""
    if not (0 < timeout_seconds <= 2 and 1_024 <= max_bytes <= 262_144):
        raise MetadataBlocked("command_bounds_invalid")
    try:
        process = subprocess.Popen(list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    except FileNotFoundError:
        raise MetadataBlocked("cli_missing") from None
    selector = selectors.DefaultSelector()
    deadline, output, diagnostic_bytes = time.monotonic() + timeout_seconds, bytearray(), 0
    try:
        for pipe, label in ((process.stdout, "out"), (process.stderr, "err")):
            selector.register(pipe, selectors.EVENT_READ, label)
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise MetadataBlocked("cli_timeout")
            for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 4_096)
                if not chunk:
                    selector.unregister(key.fileobj)
                elif key.data == "out":
                    output.extend(chunk)
                    if len(output) > max_bytes:
                        raise MetadataBlocked("cli_output_limit")
                else:
                    diagnostic_bytes += len(chunk)
                    if diagnostic_bytes > 8_192:
                        raise MetadataBlocked("cli_diagnostics_limit")
        try:
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise MetadataBlocked("cli_timeout") from None
        if code:
            raise MetadataBlocked("cli_failed")
        return bytes(output)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        for pipe in (process.stdout, process.stderr):
            pipe.close()


@dataclass(frozen=True)
class GitMetadataConfig:
    root: Path
    registered_root: Path
    project_id: str
    git_binary: Path = Path("/usr/bin/git")
    gh_binary: Path | None = None
    allowed_gh_binary: Path | None = None
    repository: str | None = None
    gh_authorized: bool = False
    ci: bool = False
    deployments: bool = False
    remote_limit: int = 2
    limits: MetadataLimits = field(default_factory=MetadataLimits)


def read_git_metadata(config: GitMetadataConfig, *, observed_at: str | datetime | None = None,
                      runner: CommandRunner = run_metadata_command) -> EvidenceBatch:
    source = "git"
    try:
        limits = config.limits
        limits.validate()
        root = _root(config.root, config.registered_root)
        project = _project(config.project_id)
        observed = _iso(observed_at or datetime.now(timezone.utc))
        if config.git_binary != Path("/usr/bin/git") or type(config.remote_limit) is not int or not 1 <= config.remote_limit <= 5:
            raise MetadataBlocked("git_config_not_allowlisted")
        for flag in (config.gh_authorized, config.ci, config.deployments):
            if type(flag) is not bool:
                raise MetadataBlocked("git_config_not_allowlisted")
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "GIT_OPTIONAL_LOCKS": "0",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1"}
        prefix = [str(config.git_binary), "--no-optional-locks", "-c", "core.fsmonitor=false",
                  "-c", "core.untrackedCache=false", "-c", "core.hooksPath=" + os.devnull, "-C", str(root)]
        deadline = time.monotonic() + limits.total_command_seconds

        def command(argv, command_env=env):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MetadataBlocked("cli_total_deadline")
            result = runner(tuple(argv), cwd=root, timeout_seconds=min(limits.command_timeout_seconds, remaining),
                            max_bytes=limits.max_command_bytes, env=command_env)
            if not isinstance(result, bytes) or len(result) > limits.max_command_bytes:
                raise MetadataBlocked("cli_output_limit")
            return result

        top = command(prefix + ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
        if top != str(root):
            raise MetadataBlocked("exact_git_root_required")
        head = command(prefix + ["rev-parse", "--verify", "HEAD"]).decode("ascii").strip()
        if not _SHA.fullmatch(head):
            raise MetadataBlocked("git_head_unknown")
        raw_status = command(prefix + ["status", "--porcelain=v1", "-z", "--untracked-files=no",
                                        "--ignore-submodules=all", "--no-renames"])
        entries = raw_status.split(b"\0")
        if entries[-1] != b"":
            raise MetadataBlocked("git_status_schema_invalid")
        counts = {"trackedChanges": 0, "stagedChanges": 0, "unstagedChanges": 0, "conflicts": 0}
        for entry in entries[:-1]:
            if len(entry) < 4 or entry[2:3] != b" " or entry[:2].strip(b" MADRCUT?!"):
                raise MetadataBlocked("git_status_schema_invalid")
            x, y = entry[:1], entry[1:2]
            if b"?" in entry[:2] or b"!" in entry[:2] or b"R" in entry[:2] or b"C" in entry[:2]:
                raise MetadataBlocked("git_status_schema_invalid")
            counts["trackedChanges"] += 1
            counts["stagedChanges"] += x != b" "
            counts["unstagedChanges"] += y != b" "
            counts["conflicts"] += entry[:2] in {b"DD", b"AU", b"UD", b"UA", b"DU", b"AA", b"UU"}
        revision = _hash([head, counts, hashlib.sha256(raw_status).hexdigest()])
        events = [_event(source, [str(root), "snapshot"], [revision, observed], observed, observed,
                         {"kind": "git_metadata_snapshot", "sha": head, "count": counts["trackedChanges"],
                          "state": "tracked_dirty" if counts["trackedChanges"] else "tracked_clean",
                          "sourceFreshAt": observed, "origin": "read_only_tracked_git_status"}, project)]
        gaps = {"untracked_files_not_scanned", "submodules_not_scanned"}
        remote_count = 0
        if config.ci or config.deployments:
            if not config.gh_authorized:
                gaps.add("gh_metadata_not_authorized")
            else:
                try:
                    if (config.gh_binary is None or config.allowed_gh_binary is None
                            or config.gh_binary != config.allowed_gh_binary or not config.gh_binary.is_absolute()
                            or config.gh_binary.resolve() != config.gh_binary
                            or not isinstance(config.repository, str) or not _REPOSITORY.fullmatch(config.repository)
                            or any(part in {".", ".."} for part in config.repository.split("/"))):
                        raise MetadataBlocked("gh_registration_invalid")
                    gh_env = {"PATH": "/usr/bin:/bin", "LANG": "C", "HOME": str(Path.home()),
                              "GH_PROMPT_DISABLED": "1", "GH_PAGER": "cat"}

                    def api(endpoint, jq):
                        raw = command([str(config.gh_binary), "api", "--hostname", "github.com", "--method", "GET",
                                       endpoint, "--jq", jq], gh_env)
                        try:
                            return json.loads(raw)
                        except (ValueError, UnicodeError, RecursionError):
                            raise MetadataBlocked("gh_metadata_schema_invalid") from None

                    base = "repos/" + config.repository
                    if config.ci:
                        rows = api(base + "/actions/runs?per_page=" + str(config.remote_limit) + "&head_sha=" + head,
                                   "[.workflow_runs[] | {id,status,conclusion,head_sha,updated_at}]")
                        if not isinstance(rows, list) or len(rows) > config.remote_limit:
                            raise MetadataBlocked("gh_ci_schema_invalid")
                        if len(rows) == config.remote_limit:
                            gaps.add("gh_ci_page_limit")
                        for row in rows:
                            if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0
                                    or row.get("head_sha") != head or row.get("status") not in _CI_STATUS
                                    or row.get("conclusion") is not None and row["conclusion"] not in _CI_CONCLUSION):
                                gaps.add("gh_ci_record_invalid")
                                continue
                            stamp = _stamp(row.get("updated_at"), observed)
                            if stamp is None:
                                gaps.add("gh_ci_timestamp_unknown")
                                continue
                            payload = {"kind": "ci_metadata", "sha": head, "status": row["status"],
                                       "reportedState": row["conclusion"] or "conclusion_unknown",
                                       "sourceFreshAt": stamp, "origin": "existing_github_ci_get"}
                            events.append(_event(source, [config.repository, "ci", row["id"]], [row["id"], payload], stamp, observed, payload, project))
                            remote_count += 1
                    if config.deployments:
                        rows = api(base + "/deployments?per_page=" + str(config.remote_limit) + "&sha=" + head,
                                   "[.[] | {id,sha,updated_at}]")
                        if not isinstance(rows, list) or len(rows) > config.remote_limit:
                            raise MetadataBlocked("gh_deployment_schema_invalid")
                        if len(rows) == config.remote_limit:
                            gaps.add("gh_deployment_page_limit")
                        for row in rows:
                            if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0 or row.get("sha") != head:
                                gaps.add("gh_deployment_record_invalid")
                                continue
                            statuses = api(base + "/deployments/" + str(row["id"]) + "/statuses?per_page=1",
                                           "[.[] | {state,created_at,updated_at}]")
                            state, stamp = "status_unknown", _stamp(row.get("updated_at"), observed)
                            if isinstance(statuses, list) and len(statuses) == 1 and isinstance(statuses[0], dict):
                                status = statuses[0]
                                if status.get("state") in _DEPLOYMENT_STATUS:
                                    state = status["state"]
                                    stamp = _stamp(status.get("updated_at") or status.get("created_at"), observed)
                            if state == "status_unknown":
                                gaps.add("gh_deployment_status_unknown")
                            if stamp is None:
                                gaps.add("gh_deployment_timestamp_unknown")
                                continue
                            payload = {"kind": "deployment_metadata", "sha": head, "deploymentId": str(row["id"]),
                                       "status": state, "sourceFreshAt": stamp, "origin": "existing_github_deployment_get"}
                            events.append(_event(source, [config.repository, "deployment", row["id"]], [row["id"], payload], stamp, observed, payload, project))
                            remote_count += 1
                except (MetadataBlocked, OSError, ValueError, TypeError, KeyError):
                    gaps.add("gh_metadata_unavailable")
        if len(events) > limits.max_events:
            events = events[:limits.max_events]
            gaps.add("event_limit")
        source_revision = _hash([revision, [[event.source_id, event.revision] for event in events[1:]]])
        return EvidenceBatch(source, "partial", tuple(events), tuple(sorted(gaps)), observed, source_revision,
                             counts["trackedChanges"] + remote_count, False,
                             {**counts, "headSha": head, "remoteRecords": remote_count,
                              "completionVerified": False, "deploymentReadinessVerified": False})
    except (MetadataBlocked, OSError, ValueError, TypeError, OverflowError) as error:
        return _blocked(source, error)


@dataclass(frozen=True)
class TokenPilotMetadataConfig:
    root: Path
    registered_root: Path
    project_id: str
    session_id: str | None = None
    report_path: Path | None = None
    allowed_report_path: Path | None = None
    supported_versions: tuple[str, ...] = ("3.8.0",)
    limits: MetadataLimits = field(default_factory=MetadataLimits)


def read_token_pilot_metadata(config: TokenPilotMetadataConfig, *, observed_at: str | datetime | None = None) -> EvidenceBatch:
    source = "token_pilot"
    try:
        limits = config.limits
        limits.validate()
        root = _root(config.root, config.registered_root)
        project = _project(config.project_id)
        observed = _iso(observed_at or datetime.now(timezone.utc))
        install = _file(root / ".token-pilot/install.json", root / ".token-pilot/install.json")
        state_file = _file(root / ".token-pilot/state.json", root / ".token-pilot/state.json")
        install_raw, _, _, _ = _read_file(install, min(limits.max_file_bytes, 65_536))
        raw, _, _, info = _read_file(state_file, limits.max_file_bytes)
        registration, state = _object(install_raw), _object(raw)
        if (type(registration.get("schema_version")) is not int or registration["schema_version"] != 2
                or registration.get("root") != str(root) or registration.get("version") not in config.supported_versions
                or not isinstance(registration.get("files"), dict)):
            raise MetadataBlocked("token_pilot_registration_unsupported")
        if (type(state.get("schema_version")) is not int or state["schema_version"] != 2
                or state.get("project") != str(root) or type(state.get("revision")) is not int
                or not 0 <= state["revision"] <= 1_000_000_000 or not isinstance(state.get("entries"), dict)
                or len(state["entries"]) > 256 or not isinstance(state.get("sessions"), dict)
                or len(state["sessions"]) > 128):
            raise MetadataBlocked("token_pilot_state_unsupported")
        gaps = {"budget_unknown", "recorded_state_not_live_writer_proof"}
        fresh = _fresh(info, observed, limits, gaps)
        statuses: dict[str, int] = {}
        for session in state["sessions"].values():
            status = session.get("status") if isinstance(session, dict) else None
            status = status if isinstance(status, str) and status in _SESSION_STATUS else "unknown"
            statuses[status] = statuses.get(status, 0) + 1
        metadata = {"registered": True, "stateRevision": state["revision"], "entryCount": len(state["entries"]),
                    "sessionCount": len(state["sessions"]), "sessionStatuses": dict(sorted(statuses.items())),
                    "budgetRemainingTokens": None, "observedIntervalTokens": None, "tokenMeasurement": "unknown",
                    "hookTrustVerified": False, "tasksRead": False}
        revision = _hash([registration["version"], metadata, info.st_mtime_ns])
        stamp = fresh or observed
        state_payload = {"kind": "token_pilot_registered_state", "scopeVersion": state["revision"],
                         "count": len(state["sessions"]), "total": len(state["entries"]),
                         "status": "registered_state_observed", "origin": "existing_token_pilot_state"}
        if fresh is not None:
            state_payload["sourceFreshAt"] = fresh
        events = [_event(source, [str(root), "registered_state"], [revision, stamp], stamp, observed,
                         state_payload, project)]
        if config.report_path is not None:
            try:
                if (config.allowed_report_path is None or config.session_id is None
                        or not isinstance(config.session_id, str) or not _IDENTITY.fullmatch(config.session_id)
                        or config.report_path != root / ".token-pilot/reports" / (hashlib.sha256(config.session_id.encode()).hexdigest()[:24] + ".json")):
                    raise MetadataBlocked("token_pilot_report_not_registered")
                path = _file(config.report_path, config.allowed_report_path)
                report_raw, _, _, report_info = _read_file(path, min(limits.max_file_bytes, 65_536))
                report = _object(report_raw)
                receipt = report.get("receipt")
                if (report.get("version") not in config.supported_versions or report.get("session_id") != config.session_id
                        or config.session_id not in state["sessions"] or report.get("memory_revision") != state["revision"]
                        or not isinstance(receipt, dict)):
                    raise MetadataBlocked("token_pilot_report_binding_unknown")
                value = report.get("observed_interval_tokens")
                if (type(value) is not int or not 0 <= value <= 1_000_000_000
                        or receipt.get("with_pilot_measurement") != "observed"
                        or type(receipt.get("actual_tokens")) is not int or receipt["actual_tokens"] != value):
                    raise MetadataBlocked("token_pilot_observed_usage_unknown")
                report_fresh = _fresh(report_info, observed, limits, gaps)
                metadata.update(observedIntervalTokens=value, tokenMeasurement="recorded_observed_interval")
                payload = {"kind": "token_pilot_observed_interval_tokens", "count": value,
                           "status": "recorded_observed_counter",
                           "origin": "existing_token_pilot_report_not_invoice"}
                if report_fresh is not None:
                    payload["sourceFreshAt"] = report_fresh
                events.append(_event(source, [str(root), config.session_id, "observed_interval"],
                                     [state["revision"], report_fresh or observed, payload], report_fresh or observed, observed, payload, project))
            except (MetadataBlocked, OSError, ValueError, TypeError):
                gaps.add("token_pilot_usage_receipt_unavailable")
        if len(events) > limits.max_events:
            events = events[:limits.max_events]
            gaps.add("event_limit")
        return EvidenceBatch(source, "partial", tuple(events), tuple(sorted(gaps)), fresh,
                             _hash([revision, metadata]), len(state["sessions"]), False, metadata)
    except (MetadataBlocked, OSError, ValueError, TypeError, OverflowError) as error:
        return _blocked(source, error)
