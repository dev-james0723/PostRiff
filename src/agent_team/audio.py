"""Bounded free macOS Sinji WAV files from an existing validated report.

Only /usr/bin/say and the already installed Sinji zh_HK voice are used. Text
goes to stdin, never shell/argv. No models, providers, downloads, voice cloning,
playback, upload or delivery occur here. A fingerprint binds report contents;
it is not authentication or authorization to publish them.

Preview reports use the full canonical hash except fingerprint. Versioned
cloud reports use the cloud store's stable hash, excluding exactly generatedAt,
fingerprint, version, supplementOf, and initialGeneratedAt. Output is private
and idempotent by fingerprint. A deterministic sentence excerpt keeps the
audio short; the exact full summary is separately hashed and remains intact.

CLI: python -m agent_team.audio < /exact/existing/report.json
The canonical output directory is fixed. No private summary appears in argv.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import selectors
import stat
import struct
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .events import canonical
from .periods import aware, period


CANONICAL_ROOT = Path.home()/"Documents/James-Agent-Team"
SAY_BINARY = "/usr/bin/say"
VOICE = "Sinji"
LOCALE = "zh_HK"
GENERATOR_VERSION = "macos-sinji-pcm-v2"
CLOUD_METADATA_FIELDS = frozenset({"generatedAt", "fingerprint", "version", "supplementOf", "initialGeneratedAt"})
REPORT_KEYS = frozenset({"schemaVersion", "executionState", "period", "asOf", "generatedAt", "counts",
                         "coverage", "gaps", "projects", "summary", "after17ObservationCount",
                         "lateObservationCount", "evidence", "evidenceCoverage", "screenshots",
                         "actions", "histogram", "fingerprint"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class AudioBlocked(ValueError):
    """Fixed diagnostic codes only; never retain source text or subprocess output."""


@dataclass(frozen=True)
class AudioLimits:
    timeout_seconds: float = 5.0
    max_duration_seconds: int = 45
    max_wav_bytes: int = 2 * 1024 * 1024
    max_summary_chars: int = 800
    max_summary_bytes: int = 2_400
    max_narration_chars: int = 64
    max_report_bytes: int = 256 * 1024

    def validate(self) -> None:
        if (self.timeout_seconds != 5.0 or type(self.max_duration_seconds) is not int
                or not 1 <= self.max_duration_seconds <= 45 or type(self.max_wav_bytes) is not int
                or not 44 <= self.max_wav_bytes <= 2 * 1024 * 1024
                or not 1 <= self.max_summary_chars <= 800 or not 1 <= self.max_summary_bytes <= 2_400
                or not 1 <= self.max_narration_chars <= 64 or not 1_024 <= self.max_report_bytes <= 256 * 1024):
            raise AudioBlocked("audio_bounds_invalid")


@dataclass(frozen=True)
class ValidatedReport:
    fingerprint: str
    fingerprint_policy: str
    report_version: int | None
    period_key: str
    kind: str
    summary_hash: str
    narration_hash: str
    summary_chars: int
    narration: str
    excerpt: bool
    execution_state: str
    delivery_eligible: bool


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _narration(summary: str, max_chars: int) -> str:
    if len(summary) <= max_chars:
        return summary
    stops = [match.end() for match in re.finditer(r"[。！？.!?]", summary[:max_chars])]
    if not stops:
        # Explicit clip marker; never add inferred claims or silently pretend
        # the bounded extract represents the complete summary.
        return summary[:max_chars - 1] + "…"
    return summary[:stops[-1]]


def validate_report(document: Mapping[str, Any], *, now: datetime | str | None = None,
                    limits: AudioLimits | None = None) -> ValidatedReport:
    limits = limits or AudioLimits()
    limits.validate()
    if not isinstance(document, dict):
        raise AudioBlocked("report_object_required")
    acceptance = (document.get("executionMode") == "staging_acceptance"
                  and isinstance(document.get("period"), dict)
                  and document["period"].get("executionMode") == "staging_acceptance")
    allowed = REPORT_KEYS | {"version", "supplementOf", "initialGeneratedAt"}
    if acceptance:
        allowed |= {"executionMode"}
    if set(document) - allowed or not REPORT_KEYS <= set(document):
        raise AudioBlocked("report_fields_not_allowlisted")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise AudioBlocked("report_schema_unsupported")
    if not isinstance(document["executionState"], str) or document["executionState"] not in {"preview", "generated"}:
        raise AudioBlocked("report_execution_state_invalid")
    try:
        raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise AudioBlocked("report_json_invalid") from None
    if len(raw.encode("utf-8")) > limits.max_report_bytes:
        raise AudioBlocked("report_size_limit")
    fingerprint = document["fingerprint"]
    if not isinstance(fingerprint, str) or not _SHA.fullmatch(fingerprint):
        raise AudioBlocked("report_fingerprint_invalid")
    version = document.get("version")
    if "version" in document:
        if type(version) is not int or not 1 <= version <= 9_999:
            raise AudioBlocked("report_version_invalid")
        fingerprint_policy = "cloud_stable_v1"
        stable = {key: value for key, value in document.items() if key not in CLOUD_METADATA_FIELDS}
    else:
        if "supplementOf" in document or "initialGeneratedAt" in document:
            raise AudioBlocked("cloud_version_required")
        fingerprint_policy = "preview_full_v1"
        stable = {key: value for key, value in document.items() if key != "fingerprint"}
    if hashlib.sha256(canonical(stable).encode("utf-8")).hexdigest() != fingerprint:
        raise AudioBlocked("report_fingerprint_mismatch")
    if "supplementOf" in document and (not isinstance(document["supplementOf"], str)
                                         or not _SHA.fullmatch(document["supplementOf"])):
        raise AudioBlocked("report_supplement_invalid")
    try:
        supplied_period = document["period"]
        if supplied_period.get('executionMode') == 'staging_acceptance':
            from .acceptance import document_period
            expected = document_period(document)
        else:
            expected = period(supplied_period["workday"], supplied_period["kind"])
        if supplied_period != expected.as_dict():
            raise AudioBlocked("report_period_mismatch")
        generated = aware(document["generatedAt"])
        as_of = aware(document["asOf"])
        current = aware(now or datetime.now(timezone.utc))
        if generated > current or not expected.start <= as_of <= min(expected.cutoff, generated):
            raise AudioBlocked("report_cutoff_or_timestamp_invalid")
        if "initialGeneratedAt" in document and aware(document["initialGeneratedAt"]) > generated:
            raise AudioBlocked("report_initial_timestamp_invalid")
    except AudioBlocked:
        raise
    except (ValueError, TypeError, KeyError, OverflowError):
        raise AudioBlocked("report_period_or_timestamp_invalid") from None
    summary = document["summary"]
    if (not isinstance(summary, str) or not summary or summary.strip() != summary
            or len(summary) > limits.max_summary_chars or len(summary.encode("utf-8")) > limits.max_summary_bytes
            or any(ord(char) < 32 or ord(char) == 127 for char in summary) or "[[" in summary or "]]" in summary):
        raise AudioBlocked("summary_invalid_or_out_of_bounds")
    narration = _narration(summary, limits.max_narration_chars)
    eligible = (version is not None and document["executionState"] == "generated"
                and (expected.kind == "whole_day" or acceptance)
                and generated >= expected.cutoff and current >= expected.cutoff)
    return ValidatedReport(fingerprint, fingerprint_policy, version, expected.key, expected.kind,
                           _text_hash(summary), _text_hash(narration), len(summary), narration,
                           narration != summary, "generated_local_audio" if eligible else "preview_audio", eligible)


def narration_for_report(document: Mapping[str, Any], *, limits: AudioLimits | None = None) -> str:
    """Pure immutable-report excerpt shared with the cloud upload verifier.

    Verification uses generatedAt as its clock: narration must not change with
    time, and this helper does not grant current delivery eligibility.
    """
    try:
        generated_at = aware(document["generatedAt"])
    except (TypeError, KeyError, ValueError):
        raise AudioBlocked("report_period_or_timestamp_invalid") from None
    return validate_report(document, now=generated_at, limits=limits).narration


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_rate: int
    sample_width: int
    frame_count: int
    duration_seconds: float
    byte_count: int
    sha256: str


def parse_wav(raw: bytes, *, limits: AudioLimits | None = None) -> WavInfo:
    """Strict bounded PCM WAV parser; no external decoder or inference."""
    limits = limits or AudioLimits()
    limits.validate()
    if not isinstance(raw, bytes) or not 44 <= len(raw) <= limits.max_wav_bytes:
        raise AudioBlocked("wav_size_limit")
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE" or struct.unpack_from("<I", raw, 4)[0] + 8 != len(raw):
        raise AudioBlocked("wav_container_invalid")
    position = 12
    fmt, samples = None, None
    chunks = 0
    while position < len(raw):
        chunks += 1
        if chunks > 32 or position + 8 > len(raw):
            raise AudioBlocked("wav_chunks_invalid")
        chunk_id, length = raw[position:position + 4], struct.unpack_from("<I", raw, position + 4)[0]
        position += 8
        end = position + length
        if end > len(raw):
            raise AudioBlocked("wav_chunks_invalid")
        if chunk_id == b"fmt ":
            if fmt is not None or length not in {16, 18}:
                raise AudioBlocked("wav_format_invalid")
            fmt = struct.unpack_from("<HHIIHH", raw, position)
            if length == 18 and struct.unpack_from("<H", raw, position + 16)[0] != 0:
                raise AudioBlocked("wav_format_invalid")
        elif chunk_id == b"data":
            if samples is not None:
                raise AudioBlocked("wav_data_invalid")
            samples = memoryview(raw)[position:end]
        elif chunk_id not in {b"JUNK", b"LIST", b"FLLR", b"fact"}:
            raise AudioBlocked("wav_chunk_unsupported")
        position = end + (length % 2)
        if position > len(raw):
            raise AudioBlocked("wav_chunks_invalid")
    if fmt is None or samples is None:
        raise AudioBlocked("wav_format_or_data_missing")
    encoding, channels, rate, byte_rate, block_align, bits = fmt
    if (encoding, channels, rate, byte_rate, block_align, bits) != (1, 1, 16_000, 32_000, 2, 16):
        raise AudioBlocked("wav_format_not_allowlisted")
    if len(samples) == 0 or len(samples) % block_align:
        raise AudioBlocked("wav_frames_invalid")
    frames = len(samples) // block_align
    duration = frames / rate
    if not 0 < duration <= limits.max_duration_seconds:
        raise AudioBlocked("wav_duration_limit")
    if not any(samples):
        raise AudioBlocked("wav_empty_signal")
    return WavInfo(channels, rate, bits // 8, frames, duration, len(raw), hashlib.sha256(raw).hexdigest())


def validate_wav(raw: bytes) -> dict[str, Any]:
    """Cloud-facing pure validator with duration derived exclusively from bytes."""
    info = parse_wav(raw)
    return {"durationSeconds": info.duration_seconds, "sampleRate": info.sample_rate,
            "channels": info.channels, "sampleWidth": info.sample_width,
            "frames": info.frame_count, "byteCount": info.byte_count, "sha256": info.sha256}


class SayRunner(Protocol):
    execution_state: str

    def run(self, argv: Sequence[str], *, stdin_bytes: bytes, timeout_seconds: float,
            max_wav_bytes: int, output_file: Path) -> None: ...


class LocalSayRunner:
    execution_state = "real_local_macos_tts"

    def run(self, argv: Sequence[str], *, stdin_bytes: bytes, timeout_seconds: float,
            max_wav_bytes: int, output_file: Path) -> None:
        # Voice and binary are fixed by the caller; never load user shell or env.
        process = subprocess.Popen(list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}, umask=0o077)
        selector = selectors.DefaultSelector()
        try:
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            process.stdin.write(stdin_bytes)
            process.stdin.close()
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            deadline, captured_bytes = time.monotonic() + timeout_seconds, 0
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise AudioBlocked("say_timeout")
                if output_file.stat().st_size > max_wav_bytes:
                    raise AudioBlocked("wav_size_limit")
                for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 1_024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        captured_bytes += len(chunk)
                        if captured_bytes > 8_192:
                            raise AudioBlocked("say_diagnostics_limit")
            try:
                exit_code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise AudioBlocked("say_timeout") from None
            if exit_code != 0:
                raise AudioBlocked("say_failed")
        except (OSError, BrokenPipeError):
            raise AudioBlocked("say_unavailable_or_failed") from None
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()


@dataclass(frozen=True)
class AudioReceipt:
    execution_state: str
    synthesis_state: str
    report_fingerprint: str
    fingerprint_policy: str
    report_version: int | None
    period_key: str
    file_path: str
    voice: str
    locale: str
    voice_identity: str
    summary_hash: str
    narration_hash: str
    narration_chars: int
    excerpt: bool
    wav: WavInfo
    reused: bool
    delivery_eligible: bool
    delivery_state: str = "not_delivered"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _private_dir(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise AudioBlocked("audio_path_alias_not_allowed")
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise AudioBlocked("private_audio_directory_required")


def _read_private(path: Path, max_bytes: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise AudioBlocked("private_audio_file_required")
    if info.st_size > max_bytes:
        raise AudioBlocked("audio_file_size_limit")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise AudioBlocked("audio_file_size_limit")
    return raw


def _receipt(report: ValidatedReport, target: Path, wav: WavInfo, *, reused: bool,
             synthesis_state: str) -> AudioReceipt:
    state = report.execution_state if synthesis_state == "real_local_macos_tts" else "synthetic_audio_fixture"
    return AudioReceipt(state, synthesis_state, report.fingerprint, report.fingerprint_policy,
                        report.report_version, report.period_key, str(target), VOICE, LOCALE,
                        "local macOS Sinji voice; no cloned identity", report.summary_hash,
                        report.narration_hash, len(report.narration), report.excerpt, wav, reused,
                        report.delivery_eligible and synthesis_state == "real_local_macos_tts")


def generate_report_audio(document: Mapping[str, Any], *, canonical_root: Path = CANONICAL_ROOT,
                          now: datetime | str | None = None, limits: AudioLimits | None = None,
                          runner: SayRunner | None = None) -> AudioReceipt:
    limits = limits or AudioLimits()
    validated = validate_report(document, now=now, limits=limits)
    root = Path(canonical_root)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise AudioBlocked("canonical_audio_root_required")
    runtime, output = root / ".runtime", root / ".runtime/audio"
    _private_dir(runtime)
    _private_dir(output)
    target = output / (validated.fingerprint + ".wav")
    metadata_path = output / (validated.fingerprint + ".json")
    lock_path = output / (validated.fingerprint + ".lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_fd = os.open(lock_path, flags, 0o600)
    except OSError:
        raise AudioBlocked("private_audio_lock_required") from None
    temporary: Path | None = None
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise AudioBlocked("private_audio_lock_required")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AudioBlocked("audio_generation_in_progress") from None
        identity = {"generatorVersion": GENERATOR_VERSION, "fingerprint": validated.fingerprint,
                    "fingerprintPolicy": validated.fingerprint_policy, "summaryHash": validated.summary_hash,
                    "narrationHash": validated.narration_hash, "voice": VOICE, "locale": LOCALE}
        if target.exists() or target.is_symlink():
            try:
                stored = json.loads(_read_private(metadata_path, 4_096))
                if not isinstance(stored, dict) or any(stored.get(key) != value for key, value in identity.items()):
                    raise AudioBlocked("cached_audio_identity_mismatch")
                wav = parse_wav(_read_private(target, limits.max_wav_bytes), limits=limits)
                if stored.get("wavHash") != wav.sha256:
                    raise AudioBlocked("cached_audio_hash_mismatch")
                synthesis_state = stored.get("synthesisState")
                if synthesis_state not in {"real_local_macos_tts", "synthetic_fixture"}:
                    raise AudioBlocked("cached_audio_provenance_invalid")
                return _receipt(validated, target, wav, reused=True, synthesis_state=synthesis_state)
            except (OSError, ValueError, TypeError) as error:
                if isinstance(error, AudioBlocked):
                    raise
                raise AudioBlocked("cached_audio_invalid") from None
        if metadata_path.exists() or metadata_path.is_symlink():
            raise AudioBlocked("orphaned_audio_receipt")
        fd, name = tempfile.mkstemp(prefix="." + validated.fingerprint + ".", suffix=".wav", dir=output)
        os.close(fd)
        temporary = Path(name)
        argv = (SAY_BINARY, "-v", VOICE, "-r", "175", "--file-format=WAVE",
                "--data-format=LEI16@16000", "--channels=1", "-o", str(temporary), "-f", "-")
        selected_runner = runner or LocalSayRunner()
        synthesis_state = selected_runner.execution_state
        if synthesis_state not in {"real_local_macos_tts", "synthetic_fixture"}:
            raise AudioBlocked("audio_runner_provenance_invalid")
        selected_runner.run(argv, stdin_bytes=(validated.narration + "\n").encode("utf-8"),
                            timeout_seconds=limits.timeout_seconds, max_wav_bytes=limits.max_wav_bytes,
                            output_file=temporary)
        wav = parse_wav(_read_private(temporary, limits.max_wav_bytes), limits=limits)
        # Lock confines all writers using this module. Do not replace a target
        # inserted by any external writer while synthesis was in progress.
        if target.exists() or target.is_symlink() or metadata_path.exists() or metadata_path.is_symlink():
            raise AudioBlocked("audio_output_conflict")
        stored = {**identity, "wavHash": wav.sha256, "synthesisState": synthesis_state,
                  "byteCount": wav.byte_count, "durationSeconds": wav.duration_seconds}
        # Hard link provides no-overwrite publication on the same filesystem.
        os.link(temporary, target, follow_symlinks=False)
        try:
            metadata_fd = os.open(metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(metadata_fd, "w", encoding="utf-8") as stream:
                stream.write(canonical(stored))
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Only this invocation's fresh generated target is removed on a
            # failed commit. Previously completed files are never overwritten.
            target.unlink(missing_ok=True)
            raise
        return _receipt(validated, target, wav, reused=False, synthesis_state=synthesis_state)
    except AudioBlocked:
        raise
    except (OSError, ValueError, TypeError):
        raise AudioBlocked("audio_generation_or_storage_failed") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main() -> int:
    import sys
    try:
        raw = sys.stdin.buffer.read(AudioLimits().max_report_bytes + 1)
        if len(raw) > AudioLimits().max_report_bytes:
            raise AudioBlocked("report_size_limit")
        document = json.loads(raw)
        print(canonical(generate_report_audio(document).as_dict()), flush=True)
        return 0
    except (AudioBlocked, ValueError, TypeError, OSError, RecursionError) as error:
        reason = str(error) if isinstance(error, AudioBlocked) else "audio_report_input_invalid"
        print(canonical({"executionState": "audio_not_generated", "error": reason,
                         "deliveryState": "not_delivered"}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
