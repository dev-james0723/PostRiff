"""Bounded, local-only source adapters; source text is evidence, never authority.

All adapters return ``ObservationBatch``. Persist its ``cursor`` and observation
``dedupe_key`` values in the caller's local event ledger. ``as_dict()`` retains
local references and any explicitly requested text; use ``cloud_projection()``
for the separate metadata-only projection. The latter excludes raw source IDs,
text, paths, app/window names, URLs, and arbitrary source metadata.

Typeless is a custom SQLite adapter, not an official export API. Its configured
database path, exact schema signature and independently observed app version
must match before reading records. Overlap pages have a frozen end and an
explicit continuation, so duplicate overlap rows cannot starve fresh updates.
Claude JSONL is optional and accepts exactly one registered log and workspace.
No adapter writes a source, exports audio, installs hooks, or executes content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from .luci_context import APP_KINDS, SIGNALS, classify


TYPELESS_HISTORY_V2_SCHEMA = (
    (0, "id", "TEXT", 1, None, 1),
    (1, "user_id", "TEXT", 0, None, 0),
    (2, "status", "TEXT", 0, None, 0),
    (3, "mode", "TEXT", 0, "'voice_transcript'", 0),
    (4, "refined_text", "TEXT", 0, None, 0),
    (5, "duration", "REAL", 0, None, 0),
    (6, "created_at", "TEXT", 0, None, 0),
    (7, "updated_at", "TEXT", 0, None, 0),
    (8, "audio_local_path", "TEXT", 0, None, 0),
    (9, "audio_metadata", "TEXT", 0, None, 0),
    (10, "app_version", "TEXT", 1, "'0.0.0'", 0),
    (11, "mic_device", "TEXT", 0, None, 0),
    (12, "mic_device_info", "BLOB", 0, None, 0),
    (13, "client_metadata", "BLOB", 0, None, 0),
    (14, "mode_meta", "BLOB", 0, None, 0),
    (15, "debug_info", "TEXT", 0, None, 0),
    (16, "audio_context", "TEXT", 0, None, 0),
    (17, "server_updated_at", "INTEGER", 0, None, 0),
    (18, "sync_status", "TEXT", 1, "'pending_upload'", 0),
    (19, "sync_attempt_count", "INTEGER", 1, "0", 0),
    (20, "synced_from_cloud", "INTEGER", 1, "false", 0),
)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def schema_signature(rows: Sequence[Sequence[Any]]) -> str:
    """Hash all PRAGMA table_info columns, including defaults and PK position."""
    normalized = [(int(r[0]), str(r[1]), str(r[2]).upper(), int(r[3]), r[4], int(r[5])) for r in rows]
    return _digest(normalized)


TYPELESS_SCHEMA_SIGNATURE = schema_signature(TYPELESS_HISTORY_V2_SCHEMA)


def _utc(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone_required")
    return dt.astimezone(timezone.utc)


def _iso(value: str | datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _optional_iso(value: Any) -> str | None:
    try:
        return _iso(value) if isinstance(value, (str, datetime)) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


def _registered_file(path: Path, allowed_path: Path) -> Path:
    """Exact lexical registration plus symlink rejection; never scan a parent."""
    actual = Path(os.path.abspath(path.expanduser()))
    allowed = Path(os.path.abspath(allowed_path.expanduser()))
    if actual != allowed or actual.is_symlink():
        raise ValueError("path_not_allowlisted")
    if not actual.is_file():
        raise ValueError("source_missing")
    return actual


@dataclass(frozen=True)
class SourceObservation:
    source: str
    source_id: str
    source_version: str
    event_type: str
    occurred_at: str | None
    updated_at: str | None
    observed_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    local_reference: Mapping[str, Any] = field(default_factory=dict)
    safe_metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    text: str | None = None
    untrusted: bool = True
    execution_authority: str = "none"

    @property
    def dedupe_key(self) -> str:
        return _digest([self.source, self.source_id, self.source_version])

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["dedupe_key"] = self.dedupe_key
        return result

    def cloud_projection(self) -> dict[str, Any]:
        """Only adapter-selected numeric/boolean/digest and finite context enums."""
        allowed = {"text_length", "text_hash", "audio_exists", "has_app", "app_hash",
                   "has_screenshot", "display_hash", "is_error", "tool_name_hash",
                   "tool_id_hash", "session_hash", "role", "text_truncated", "app_kind", "context_signal"}
        safe: dict[str, Any] = {}
        for key, value in self.safe_metadata.items():
            if key not in allowed:
                continue
            if isinstance(value, (bool, int)):
                safe[key] = value
            elif key.endswith("_hash") and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
                safe[key] = value
            elif key == "role" and value in ("user", "assistant"):
                safe[key] = value
            elif self.source == 'luci' and isinstance(value, str) and ((key == 'app_kind' and value in APP_KINDS)
                                            or (key == 'context_signal' and value in SIGNALS)):
                safe[key] = value
        return {"source": self.source, "source_ref": _digest([self.source, self.source_id]),
                "source_version": self.source_version, "event_type": self.event_type,
                "occurred_at": self.occurred_at, "updated_at": self.updated_at,
                "observed_at": self.observed_at, "metadata": safe,
                "untrusted": True, "execution_authority": "none"}


@dataclass(frozen=True)
class ObservationBatch:
    status: str
    observations: tuple[SourceObservation, ...] = ()
    cursor: Mapping[str, Any] | None = None
    gaps: tuple[str, ...] = ()
    scanned: int = 0
    complete: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "observations": [o.as_dict() for o in self.observations],
                "cursor": dict(self.cursor) if self.cursor else None,
                "gaps": list(self.gaps), "scanned": self.scanned, "complete": self.complete}

    def cloud_projection(self) -> dict[str, Any]:
        return {"status": self.status, "observations": [o.cloud_projection() for o in self.observations],
                "gaps": list(self.gaps), "scanned": self.scanned, "complete": self.complete}


def _unavailable(reason: str, cursor: Mapping[str, Any] | None = None) -> ObservationBatch:
    return ObservationBatch("unavailable", cursor=cursor, gaps=(reason,), complete=False)


def _seen(keys: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for index, key in enumerate(keys):
        if index >= 20_000 or not isinstance(key, str) or len(key) > 128:
            raise ValueError("dedupe_input_out_of_bounds")
        result.add(key)
    return result


@dataclass(frozen=True)
class TypelessConfig:
    database_path: Path
    allowed_database_path: Path
    installed_app_version: str
    expected_schema_signature: str = TYPELESS_SCHEMA_SIGNATURE
    allowed_app_versions: tuple[str, ...] = ("2.8.0",)
    # Independently verified installed version is separate from history row
    # provenance. mac_2.8.0 was observed in a bounded metadata-only live query.
    allowed_record_app_versions: tuple[str, ...] = ("2.8.0", "mac_2.8.0")
    allowed_audio_roots: tuple[Path, ...] = ()
    overlap_seconds: int = 300
    max_window_seconds: int = 86_400
    max_content_chars: int = 32_768
    query_timeout_seconds: float = 2.0


class TypelessObserver:
    def __init__(self, config: TypelessConfig):
        self.config = config

    def poll(self, *, start_at: str | datetime, end_at: str | datetime,
             cursor: Mapping[str, Any] | None = None, seen_versions: Iterable[str] = (),
             include_text: bool = False, max_text_chars: int = 2_000,
             limit: int = 50) -> ObservationBatch:
        """Read one bounded overlap page. Continue returned cursors until complete.

        Cursor keys: updated_at/source_id are the high watermark; window_start,
        window_end, scan_updated_at/scan_source_id exist only during pagination.
        End is frozen during pagination. A completed poll starts a new overlap
        window on the next invocation. Late updates older than the configured
        overlap require an explicit bounded backfill; no complete-history claim
        is made. Unknown/oversized rows produce a visible coverage gap.
        """
        cfg = self.config
        connection: sqlite3.Connection | None = None
        try:
            if cfg.installed_app_version not in cfg.allowed_app_versions:
                return _unavailable("app_version_mismatch", cursor)
            if not (1 <= limit <= 500 and 0 <= cfg.overlap_seconds <= 3_600
                    and 1 <= cfg.max_content_chars <= 131_072 and 1 <= max_text_chars <= 8_000
                    and 0 < cfg.query_timeout_seconds <= 5):
                raise ValueError("bounds_invalid")
            start, end = _utc(start_at), _utc(end_at)
            if not (0 < (end - start).total_seconds() <= cfg.max_window_seconds <= 172_800):
                raise ValueError("window_out_of_bounds")
            seen = _seen(seen_versions)
            db = _registered_file(Path(cfg.database_path), Path(cfg.allowed_database_path))
            high_at, high_id = None, ""
            scan_at, scan_id = None, ""
            window_start, window_end = start, end
            if cursor:
                high_at = _utc(cursor["updated_at"])
                high_id = str(cursor["source_id"])
                if len(high_id) > 256 or high_at > end:
                    raise ValueError("cursor_invalid")
                if cursor.get("window_end"):
                    window_start = _utc(cursor["window_start"])
                    window_end = _utc(cursor["window_end"])
                    scan_at = _utc(cursor["scan_updated_at"])
                    scan_id = str(cursor["scan_source_id"])
                    if not (start <= window_start <= scan_at <= window_end <= end) or len(scan_id) > 256:
                        raise ValueError("cursor_invalid")
                else:
                    window_start = max(start, high_at - timedelta(seconds=cfg.overlap_seconds))
            connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1)
            connection.execute("PRAGMA query_only=ON")
            if schema_signature(connection.execute("PRAGMA table_info(history_v2)").fetchall()) != cfg.expected_schema_signature:
                return _unavailable("schema_mismatch", cursor)
            deadline = time.monotonic() + cfg.query_timeout_seconds
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1_000)
            timestamp = "julianday(COALESCE(updated_at,created_at))"
            where = f"{timestamp} >= julianday(?) AND {timestamp} <= julianday(?)"
            params: list[Any] = [_iso(window_start), _iso(window_end)]
            if scan_at:
                where += f" AND ({timestamp} > julianday(?) OR ({timestamp} = julianday(?) AND id > ?))"
                params += [_iso(scan_at), _iso(scan_at), scan_id]
            # Oversized content is never materialized in Python or silently hashed
            # as though a prefix represented the complete source text.
            sql = f"""SELECT id,status,mode,
                     CASE WHEN length(COALESCE(refined_text,'')) <= ? THEN refined_text END,
                     length(COALESCE(refined_text,'')),created_at,updated_at,
                     substr(audio_local_path,1,4097),app_version,server_updated_at,
                     sync_status,synced_from_cloud
                     FROM history_v2 WHERE {where}
                     ORDER BY {timestamp},id LIMIT ?"""
            rows = connection.execute(sql, [cfg.max_content_chars, *params, limit + 1]).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            observations: list[SourceObservation] = []
            gaps: set[str] = set()
            observed_at = _now()
            next_high_at, next_high_id = high_at, high_id
            last_at, last_id = None, ""
            for row in rows:
                (source_id, status, mode, content, content_length, created_at, updated_at,
                 audio_path, app_version, server_updated_at, sync_status, synced) = row
                record_at = _optional_iso(updated_at or created_at)
                if record_at is None or not isinstance(source_id, str) or len(source_id) > 256:
                    # Invalid IDs cannot serve as a safe pagination checkpoint.
                    return _unavailable("record_identity_or_timestamp_invalid", cursor)
                record_dt = _utc(record_at)
                last_at, last_id = record_at, source_id
                if next_high_at is None or (record_dt, source_id) > (next_high_at, next_high_id):
                    next_high_at, next_high_id = record_dt, source_id
                if app_version not in cfg.allowed_record_app_versions:
                    # Never widen version support from arbitrary private rows.
                    # Keep the scan checkpoint and a visible gap for bounded
                    # backfill after that provenance version is verified.
                    gaps.add("record_app_version_unknown")
                    continue
                if content_length > cfg.max_content_chars:
                    gaps.add("content_out_of_bounds")
                    continue
                content = content or ""
                content_hash = _digest(content)
                audio_ref, audio_exists, audio_gap = self._audio_reference(audio_path)
                if audio_gap:
                    gaps.add(audio_gap)
                # IDs and full-content hashes distinguish sources; status/time
                # participate in versions so pending -> completed is observable.
                metadata = {"status": str(status or "")[:64], "mode": str(mode or "")[:64],
                            "text_hash": content_hash, "text_length": content_length,
                            "app_version": app_version, "app_version_provenance": "history_record",
                            "installed_app_version": cfg.installed_app_version,
                            "sync_status": str(sync_status or "")[:64],
                            "synced_from_cloud": bool(synced), "server_updated_at": server_updated_at,
                            "audio_exists": audio_exists, "text_truncated": include_text and content_length > max_text_chars}
                version = _digest([source_id, status, mode, content_hash, created_at, updated_at,
                                   app_version, server_updated_at, sync_status, bool(synced)])
                item = SourceObservation("typeless", source_id, version, "history_record",
                                         _optional_iso(created_at), record_at, observed_at, metadata,
                                         {"database_path": str(db), "table": "history_v2", "record_id": source_id,
                                          "audio_path": audio_ref, "audio_exists": audio_exists},
                                         {"text_hash": content_hash, "text_length": content_length,
                                          "audio_exists": audio_exists,
                                          "text_truncated": include_text and content_length > max_text_chars},
                                         content[:max_text_chars] if include_text else None)
                if item.dedupe_key not in seen:
                    observations.append(item)
            result_cursor: dict[str, Any] | None = dict(cursor) if cursor else None
            if next_high_at is not None:
                result_cursor = {"updated_at": _iso(next_high_at), "source_id": next_high_id}
                if has_more:
                    result_cursor.update(window_start=_iso(window_start), window_end=_iso(window_end),
                                         scan_updated_at=last_at, scan_source_id=last_id)
            if has_more:
                gaps.add("page_remaining")
            return ObservationBatch("partial" if gaps else "ok", tuple(observations), result_cursor,
                                    tuple(sorted(gaps)), len(rows), not has_more)
        except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
            allowed = {"path_not_allowlisted", "source_missing", "timezone_required", "bounds_invalid",
                       "window_out_of_bounds", "cursor_invalid", "dedupe_input_out_of_bounds"}
            reason = str(exc) if str(exc) in allowed else "input_invalid"
            return _unavailable(reason, cursor)
        except sqlite3.Error:
            return _unavailable("database_query_failed", cursor)
        finally:
            if connection is not None:
                connection.close()

    def _audio_reference(self, raw: Any) -> tuple[str | None, bool, str | None]:
        if not raw:
            return None, False, None
        if not isinstance(raw, str) or len(raw) > 4_096 or "\x00" in raw:
            return None, False, "audio_reference_invalid"
        path = Path(raw).expanduser()
        roots = self.config.allowed_audio_roots
        if not path.is_absolute() or not roots or not any(path.resolve().is_relative_to(Path(r).resolve()) for r in roots):
            return None, False, "audio_reference_not_allowlisted"
        return str(path), path.is_file(), None


def _run_bounded(argv: Sequence[str], max_bytes: int, timeout_seconds: float) -> tuple[int, bytes, bytes]:
    """Capture a bounded subprocess without shell, unlimited communicate, or retries."""
    process = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False)
    stdout, stderr = bytearray(), bytearray()
    selector = selectors.DefaultSelector()
    try:
        assert process.stdout is not None and process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        deadline = time.monotonic() + timeout_seconds
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise ValueError("cli_timeout")
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 4_096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                key.data.extend(chunk)
                if len(stdout) + len(stderr) > max_bytes:
                    raise ValueError("cli_output_out_of_bounds")
        return process.wait(timeout=max(0.001, deadline - time.monotonic())), bytes(stdout), bytes(stderr)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


class LuciObserver:
    """Only LUCI usage --tr <fromMs>:<toMs> --limit <n> --json is permitted."""
    def __init__(self, shim_path: Path, allowed_shim_path: Path, *,
                 runner: Callable[[Sequence[str], int, float], tuple[int, bytes, bytes]] = _run_bounded,
                 max_output_bytes: int = 262_144, timeout_seconds: float = 25):
        self.shim_path, self.allowed_shim_path = Path(shim_path), Path(allowed_shim_path)
        self.runner, self.max_output_bytes, self.timeout_seconds = runner, max_output_bytes, timeout_seconds

    def poll(self, *, start_ms: int, end_ms: int, limit: int = 20,
             seen_versions: Iterable[str] = (), include_text: bool = False,
             max_text_chars: int = 2_000) -> ObservationBatch:
        try:
            if (type(start_ms) is not int or type(end_ms) is not int
                    or not (0 <= start_ms < end_ms and end_ms - start_ms <= 86_400_000)
                    or not 1 <= limit <= 100 or not 1 <= max_text_chars <= 8_000
                    or not 1_024 <= self.max_output_bytes <= 524_288
                    or not 0 < self.timeout_seconds <= 30):
                raise ValueError("bounds_invalid")
            shim = _registered_file(self.shim_path, self.allowed_shim_path)
            if not os.access(shim, os.X_OK):
                raise ValueError("shim_not_executable")
            seen = _seen(seen_versions)
            argv = [str(shim), "usage", "--tr", f"{start_ms}:{end_ms}", "--limit", str(limit), "--json"]
            code, stdout, stderr = self.runner(argv, self.max_output_bytes, self.timeout_seconds)
            if len(stdout) + len(stderr) > self.max_output_bytes:
                raise ValueError("cli_output_out_of_bounds")
            if code != 0:
                return _unavailable("cli_query_failed")
            payload = json.loads(stdout)
            if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
                raise ValueError("cli_schema_mismatch")
            entries = payload["entries"]
            if len(entries) > limit:
                raise ValueError("cli_limit_not_honored")
            observations: list[SourceObservation] = []
            gaps: set[str] = set()
            observed_at = _now()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("cli_schema_mismatch")
                source_id, captured_at = entry.get("captureId"), entry.get("timestamp")
                if (not isinstance(source_id, (str, int)) or isinstance(source_id, bool)
                        or len(str(source_id)) > 256 or type(captured_at) is not int
                        or not start_ms <= captured_at <= end_ms):
                    raise ValueError("cli_record_invalid")
                content = entry.get("text") or ""
                app = entry.get("app")
                display = entry.get("displayId")
                screenshot = entry.get("screenshotPath")
                if not isinstance(content, str) or (app is not None and not isinstance(app, str)):
                    raise ValueError("cli_record_invalid")
                screenshot_ref = screenshot if isinstance(screenshot, str) and len(screenshot) <= 4_096 and "\x00" not in screenshot else None
                timestamp = _iso(datetime.fromtimestamp(captured_at / 1_000, timezone.utc))
                metadata = {"text_hash": _digest(content), "text_length": len(content),
                            "has_app": bool(app), "app_hash": _digest(app) if app else None,
                            "has_screenshot": bool(screenshot_ref), "display_hash": _digest(display) if display else None,
                            "text_truncated": include_text and len(content) > max_text_chars}
                metadata.update(classify(app, content))
                version = _digest([str(source_id), captured_at,
                                   {k: v for k, v in metadata.items() if k != "text_truncated"}])
                item = SourceObservation("luci", str(source_id), version, "capture", timestamp,
                                         timestamp, observed_at, metadata,
                                         {"capture_id": source_id, "screenshot_path": screenshot_ref}, metadata,
                                         content[:max_text_chars] if include_text else None)
                if item.dedupe_key not in seen:
                    observations.append(item)
            if len(entries) == limit:
                gaps.add("source_limit_reached")
            return ObservationBatch("partial" if gaps else "ok", tuple(observations),
                                    gaps=tuple(sorted(gaps)), scanned=len(entries), complete=not gaps)
        except (ValueError, TypeError, OverflowError, OSError, RecursionError, subprocess.SubprocessError) as exc:
            allowed = {"path_not_allowlisted", "source_missing", "bounds_invalid", "shim_not_executable",
                       "dedupe_input_out_of_bounds", "cli_timeout", "cli_output_out_of_bounds",
                       "cli_schema_mismatch", "cli_limit_not_honored", "cli_record_invalid"}
            return _unavailable(str(exc) if str(exc) in allowed else "cli_read_failed")


class ClaudeJsonlObserver:
    """Optional read-only exact-path tail. Thinking and tool payloads are discarded."""
    def __init__(self, log_path: Path | None, allowed_log_path: Path | None,
                 expected_cwd: Path, *, max_tail_bytes: int = 262_144, max_lines: int = 200,
                 max_text_chars: int = 2_000, max_events: int = 500):
        self.log_path = Path(log_path) if log_path is not None else None
        self.allowed_log_path = Path(allowed_log_path) if allowed_log_path is not None else None
        self.expected_cwd = Path(expected_cwd).resolve()
        self.max_tail_bytes, self.max_lines, self.max_text_chars = max_tail_bytes, max_lines, max_text_chars
        self.max_events = max_events

    def poll(self, *, include_text: bool = False, seen_versions: Iterable[str] = ()) -> ObservationBatch:
        if self.log_path is None or self.allowed_log_path is None:
            return _unavailable("source_not_registered")
        try:
            if not (1_024 <= self.max_tail_bytes <= 524_288 and 1 <= self.max_lines <= 500
                    and 1 <= self.max_text_chars <= 8_000 and 1 <= self.max_events <= 1_000):
                raise ValueError("bounds_invalid")
            path = _registered_file(self.log_path, self.allowed_log_path)
            seen = _seen(seen_versions)
            gaps: set[str] = set()
            with path.open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                offset = max(0, size - self.max_tail_bytes)
                stream.seek(offset)
                data = stream.read(self.max_tail_bytes)
            if offset:
                gaps.add("tail_history_omitted")
                # Seeking can land inside UTF-8 or JSON; discard that partial row.
                cut = data.find(b"\n")
                if cut < 0:
                    return _unavailable("line_out_of_bounds")
                offset += cut + 1
                data = data[cut + 1:]
            if data and not data.endswith(b"\n"):
                gaps.add("incomplete_line")
                data = data[:data.rfind(b"\n") + 1] if b"\n" in data else b""
            lines = data.splitlines(keepends=True)
            if len(lines) > self.max_lines:
                gaps.add("line_limit_reached")
                offset += sum(len(line) for line in lines[:-self.max_lines])
                lines = lines[-self.max_lines:]
            observations: list[SourceObservation] = []
            observed_at = _now()
            for raw in lines:
                line_offset = offset
                offset += len(raw)
                try:
                    record = json.loads(raw)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    gaps.add("malformed_line")
                    continue
                if not isinstance(record, dict):
                    gaps.add("malformed_line")
                    continue
                cwd = record.get("cwd")
                if not isinstance(cwd, str) or Path(cwd).resolve() != self.expected_cwd:
                    gaps.add("cwd_mismatch_or_missing")
                    continue
                record_type = record.get("type")
                if record_type not in ("user", "assistant"):
                    continue
                message = record.get("message")
                if not isinstance(message, dict):
                    gaps.add("message_schema_mismatch")
                    continue
                role = message.get("role", record_type)
                if role != record_type:
                    gaps.add("message_schema_mismatch")
                    continue
                content = message.get("content", [])
                blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
                if not isinstance(blocks, list):
                    gaps.add("message_schema_mismatch")
                    continue
                session = record.get("sessionId")
                event_id = record.get("uuid")
                if not isinstance(session, str) or len(session) > 256:
                    gaps.add("session_missing_or_invalid")
                    continue
                if not isinstance(event_id, str) or len(event_id) > 256:
                    event_id = f"offset:{line_offset}"
                timestamp = _optional_iso(record.get("timestamp"))
                if timestamp is None:
                    gaps.add("timestamp_missing_or_invalid")
                    continue
                for index, block in enumerate(blocks):
                    if len(observations) >= self.max_events:
                        gaps.add("event_limit_reached")
                        break
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    text: str | None = None
                    metadata: dict[str, Any] = {"role": role, "session_hash": _digest(session)}
                    if block_type == "text" and isinstance(block.get("text"), str):
                        original = block["text"]
                        metadata.update(text_hash=_digest(original), text_length=len(original),
                                        text_truncated=include_text and len(original) > self.max_text_chars)
                        text = original[:self.max_text_chars] if include_text else None
                        event_type = "message_text"
                    elif block_type == "tool_use":
                        name, tool_id = block.get("name"), block.get("id")
                        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name)
                                or not isinstance(tool_id, str) or len(tool_id) > 256):
                            gaps.add("tool_metadata_invalid")
                            continue
                        metadata.update(tool_name_hash=_digest(name), tool_id_hash=_digest(tool_id))
                        event_type = "tool_started"
                    elif block_type == "tool_result":
                        tool_id = block.get("tool_use_id")
                        if not isinstance(tool_id, str) or len(tool_id) > 256:
                            gaps.add("tool_metadata_invalid")
                            continue
                        metadata.update(tool_id_hash=_digest(tool_id), is_error=block.get("is_error") is True)
                        event_type = "tool_finished"
                    else:
                        # Includes thinking, reasoning, encrypted thinking, image,
                        # tool inputs/results, attachments and arbitrary payloads.
                        continue
                    source_id = f"{session}:{event_id}:{index}"
                    version = _digest([source_id, event_type, timestamp,
                                       {k: v for k, v in metadata.items() if k != "text_truncated"}])
                    item = SourceObservation("claude_jsonl", source_id, version, event_type, timestamp,
                                             timestamp, observed_at, metadata,
                                             {"log_path": str(path), "line_offset": line_offset,
                                              "session_id": session, "event_id": event_id}, metadata, text)
                    if item.dedupe_key not in seen:
                        observations.append(item)
            return ObservationBatch("partial" if gaps else "ok", tuple(observations),
                                    gaps=tuple(sorted(gaps)), scanned=len(lines), complete=not gaps)
        except (ValueError, TypeError, OSError, OverflowError) as exc:
            allowed = {"path_not_allowlisted", "source_missing", "bounds_invalid", "dedupe_input_out_of_bounds"}
            return _unavailable(str(exc) if str(exc) in allowed else "log_read_failed")
