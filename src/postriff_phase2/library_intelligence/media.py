"""Audio, video and image media facts: real waveform peaks, header durations, dimensions, transcription and saved
moments (engineering spec §7 Audio/Video; T03, A017–A022).

Waveform peaks are computed from decoded samples only (`build_waveform` is a pure function over them). WAV decodes
with the standard `wave` module; other codecs need ffmpeg, which this module detects and never requires (Vercel's
Python runtime has none). Without a decoder the state is honest: a real header duration with no peaks is `partial`,
nothing at all is `unsupported` — never hash-seeded bars. Durations come from real headers: WAV, ISO-BMFF `moov`
(mp4_boxes), FLAC STREAMINFO, Ogg granule positions, or ffprobe when present.

ffmpeg/ffprobe run as killable children with CPU/memory limits, a scrubbed environment, `-protocol_whitelist file`
and a forced demuxer, so a playlist or reference file cannot be probed into fetching anything.

Transcription goes through `providers.transcribe` (cloud `asr`). Speakers are anonymous; nothing infers identity.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import uuid
import wave
from array import array

from postriff_alpha.domain import AlphaError

from .. import mp4_boxes
from . import contracts as c
from . import policy, versions
from .providers import MAX_AUDIO_BYTES, ProviderUnavailable, Providers
from .segments import (anonymous_speakers, bounds, code_switch_note, detect_language, job_attr, job_raw, outcome, register_processors,
                       writable, add_user_segment)

DEFAULT_BUCKETS = 1000
MAX_BROWSER_PEAKS = 2000
MAX_DURATION_MS = 86_400_000
PREVIEW_VERSION = "preview-1"
TRANSCRIBE_VERSION = "asr-1"
TRANSCRIPT_EXTRACTOR = "asr"
FFMPEG_TIMEOUT = 60
FFMPEG_MEMORY = 1024 * 1024 * 1024
MAX_PCM_BYTES = 400 * 1024 * 1024
MEDIA_KEYS = ("durationMs", "durationSource", "width", "height", "orientation", "pages", "slides", "sheets", "sheetNames", "textLength",
              "ocrNeededPages", "ocrReasons", "peaks", "peaksSource", "peaksDurationMs")
CARD_MEDIA = ("durationMs", "width", "height", "pages", "slides", "peaks", "peaksSource")
# Containers the transcription endpoint accepts as uploaded.
ASR_EXTENSIONS = ("wav", "mp3", "m4a", "ogg", "oga", "flac", "webm", "mp4", "mpeg", "mpga")
DEMUXERS = {"wav": "wav", "mp3": "mp3", "m4a": "mov", "mp4": "mov", "mov": "mov", "m4v": "mov", "ogg": "ogg", "oga": "ogg", "opus": "ogg",
            "flac": "flac", "aac": "aac", "webm": "matroska"}
MP4_EXTENSIONS = ("mp4", "m4a", "mov", "m4v")


# --- waveform ---------------------------------------------------------------------------------------------------------
def build_waveform(samples, buckets: int = DEFAULT_BUCKETS, *, full_scale: float = 1.0) -> list[float]:
    """Peak absolute amplitude per bucket, relative to full scale, in [0, 1]. Pure: the same samples always give the
    same peaks, different signals give correspondingly different peaks, and no samples give no peaks."""
    n = len(samples)
    if not n or buckets <= 0:
        return []
    if not full_scale or full_scale <= 0:
        raise ValueError("full_scale must be positive")
    buckets = min(int(buckets), n)
    out = []
    for i in range(buckets):
        chunk = samples[i * n // buckets:(i + 1) * n // buckets]
        peak = max(abs(max(chunk)), abs(min(chunk))) / full_scale
        out.append(round(min(1.0, float(peak)), 4))
    return out


class PeakAccumulator:
    """Streaming peaks with bounded memory: per-window maxima that coarsen (pairwise max) when they exceed `cap`.
    The final reduction is exact over windows because the max of maxima is the max."""

    def __init__(self, full_scale: float, window: int = 1, cap: int = 65536):
        self.full_scale, self.window, self.cap = full_scale, window, cap
        self.values: list = []
        self.pending = None
        self.samples = 0

    def add(self, samples):
        if not len(samples):
            return
        self.samples += len(samples)
        buf = samples if self.pending is None or not len(self.pending) else self.pending + samples
        full = len(buf) // self.window * self.window
        for start in range(0, full, self.window):
            chunk = buf[start:start + self.window]
            self.values.append(max(abs(max(chunk)), abs(min(chunk))))
        self.pending = buf[full:]
        while len(self.values) > self.cap:
            pairs = [max(a, b) for a, b in zip(self.values[0::2], self.values[1::2])]
            if len(self.values) % 2:
                pairs.append(self.values[-1])
            self.values, self.window = pairs, self.window * 2

    def finish(self, buckets: int) -> list[float]:
        values = list(self.values)
        if self.pending is not None and len(self.pending):
            values.append(max(abs(max(self.pending)), abs(min(self.pending))))
        return build_waveform(values, buckets, full_scale=self.full_scale)


_SIGNED8 = bytes(((x - 128) & 0xFF) for x in range(256))


def _pcm(data: bytes, width: int):
    """Little-endian PCM bytes -> (array of ints, full scale)."""
    data = data[:len(data) // width * width]
    if width == 1:
        return array("b", data.translate(_SIGNED8)), 128
    if width == 2:
        samples = array("h", data)
    elif width == 3:
        joined = bytearray(len(data) // 3 * 2)
        joined[0::2], joined[1::2] = data[1::3], data[2::3]
        samples = array("h", bytes(joined))
    else:
        samples = array("i", data)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples, (32768 if width in (2, 3) else 2147483648)


def wav_waveform(raw: bytes, buckets: int = DEFAULT_BUCKETS) -> dict:
    """Decode PCM WAV with the standard library and return {durationMs, peaks, sampleRate, channels}."""
    with wave.open(io.BytesIO(raw), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        if channels < 1 or rate < 1 or width not in (1, 2, 3, 4):
            raise ValueError("unsupported WAV layout")
        accumulator, frames = None, 0
        while True:
            data = w.readframes(65536)
            if not data:
                break
            samples, scale = _pcm(data, width)
            accumulator = accumulator or PeakAccumulator(scale)
            accumulator.add(samples)
            frames += len(data) // (width * channels)
    if not frames or accumulator is None:
        raise ValueError("no audio frames")
    return {"durationMs": round(frames * 1000 / rate), "peaks": accumulator.finish(buckets), "sampleRate": rate, "channels": channels}


# --- header durations -------------------------------------------------------------------------------------------------
def mp4_info(raw: bytes) -> dict | None:
    try:
        found = mp4_boxes.walk(lambda offset, length: raw[offset:offset + length], len(raw), max_header_reads=16)
        if not found.get("moov"):
            return None
        offset, size = found["moov"]
        if size > mp4_boxes.MOOV_MAX:
            return None
        info = mp4_boxes.parse_moov(raw[offset:offset + size])
    except (mp4_boxes.BoxError, struct.error, ValueError):
        return None
    out = {}
    if info.get("duration"):
        out["durationMs"] = int(round(info["duration"] * 1000))
    if info.get("width") and info.get("height"):
        out.update(width=int(info["width"]), height=int(info["height"]))
    return out or None


def _flac_duration(raw: bytes):
    if raw[:4] != b"fLaC" or len(raw) < 42:
        return None
    offset = 4
    for _ in range(64):
        if offset + 4 > len(raw):
            return None
        header = raw[offset]
        length = int.from_bytes(raw[offset + 1:offset + 4], "big")
        if header & 0x7F == 0 and length >= 18:
            packed = int.from_bytes(raw[offset + 4 + 10:offset + 4 + 18], "big")
            rate, total = packed >> 44, packed & ((1 << 36) - 1)
            return round(total * 1000 / rate) if rate and total else None
        if header & 0x80:
            return None
        offset += 4 + length
    return None


def _ogg_duration(raw: bytes):
    if raw[:4] != b"OggS" or len(raw) < 28:
        return None
    segments = raw[26]
    payload_start = 27 + segments
    payload = raw[payload_start:payload_start + sum(raw[27:27 + segments])]
    if payload.startswith(b"OpusHead") and len(payload) >= 12:
        rate, skip = 48000, int.from_bytes(payload[10:12], "little")
    elif payload.startswith(b"\x01vorbis") and len(payload) >= 16:
        rate, skip = int.from_bytes(payload[12:16], "little"), 0
    else:
        return None
    index = len(raw)
    for _ in range(64):
        index = raw.rfind(b"OggS", 0, index)
        if index < 0:
            return None
        if raw[index + 4:index + 5] == b"\0" and index + 14 <= len(raw):
            granule = int.from_bytes(raw[index + 6:index + 14], "little", signed=True)
            if granule > skip and rate:
                return round((granule - skip) * 1000 / rate)
    return None


def probe_duration(raw: bytes, ext: str):
    """(durationMs, source) from real container headers, or ffprobe when available; None when unknown."""
    ext = str(ext or "").lower()
    try:
        if ext == "wav":
            with wave.open(io.BytesIO(raw), "rb") as w:
                if w.getframerate() > 0 and w.getnframes() > 0:
                    return round(w.getnframes() * 1000 / w.getframerate()), "wav_header"
        elif ext == "flac":
            value = _flac_duration(raw)
            if value:
                return value, "flac_streaminfo"
        elif ext in ("ogg", "oga", "opus"):
            value = _ogg_duration(raw)
            if value:
                return value, "ogg_granule"
        elif ext in MP4_EXTENSIONS:
            info = mp4_info(raw)
            if info and info.get("durationMs"):
                return info["durationMs"], "mp4_moov"
    except (wave.Error, EOFError, ValueError, IndexError):
        pass
    value = ffprobe_duration(raw, ext)
    return (value, "ffprobe") if value else None


# --- ffmpeg (optional, sandboxed) ---------------------------------------------------------------------------------------
def ffmpeg_path():
    """Resolved at call time so a runtime without ffmpeg (Vercel) simply reports it as unavailable."""
    return shutil.which("ffmpeg")


def _ffprobe_path():
    binary = ffmpeg_path()
    if not binary:
        return None
    sibling = os.path.join(os.path.dirname(binary), "ffprobe")
    return sibling if os.path.isfile(sibling) and os.access(sibling, os.X_OK) else None


def _tool_env() -> dict:
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


def _limit_child():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (FFMPEG_TIMEOUT, FFMPEG_TIMEOUT))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (FFMPEG_MEMORY, FFMPEG_MEMORY))
        except (ValueError, OSError):
            pass
    except ImportError:
        pass


def _run_tool(argv, path, timeout):
    """Stream a tool's stdout in chunks with a wall-clock kill switch and an output cap."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_tool_env(),
                               cwd=os.path.dirname(path), preexec_fn=_limit_child if os.name == "posix" else None)
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    total = 0
    try:
        while True:
            chunk = process.stdout.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_PCM_BYTES:
                raise ValueError("decoder output over the safe limit")
            yield chunk
        if process.wait(timeout=5) != 0:
            raise ValueError("decoder failed")
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.stdout.close()


def _with_temp(raw: bytes, build, runner, timeout):
    with tempfile.TemporaryDirectory(prefix="library-media-") as directory:
        path = os.path.join(directory, "input")
        with open(path, "wb") as handle:
            handle.write(raw)
        result = runner(build(path), path, timeout)
        chunks = [result] if isinstance(result, (bytes, bytearray)) else list(result or [])
    return b"".join(chunks)


def ffmpeg_peaks(raw: bytes, ext: str, buckets: int = DEFAULT_BUCKETS, *, runner=None, binary=None) -> list[float] | None:
    """Decode the first audio stream to mono 16-bit PCM with ffmpeg and return real peaks, or None."""
    demuxer = DEMUXERS.get(str(ext or "").lower())
    binary = binary or ffmpeg_path()
    if not demuxer or not binary:
        return None

    def build(path):
        return [binary, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file", "-f", demuxer, "-i", path, "-vn", "-sn", "-dn",
                "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]

    try:
        pcm = _with_temp(raw, build, runner or _run_tool, FFMPEG_TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if len(pcm) < 2:
        return None
    samples = array("h", pcm[:len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    accumulator = PeakAccumulator(32768)
    accumulator.add(samples)
    return accumulator.finish(buckets)


def ffprobe_duration(raw: bytes, ext: str, *, runner=None):
    demuxer, binary = DEMUXERS.get(str(ext or "").lower()), _ffprobe_path()
    if not demuxer or not binary:
        return None

    def build(path):
        return [binary, "-v", "error", "-protocol_whitelist", "file", "-f", demuxer, "-show_entries", "format=duration", "-of", "json", path]

    try:
        data = json.loads(_with_temp(raw, build, runner or _run_tool, 20) or b"{}")
        seconds = float((data.get("format") or {}).get("duration"))
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    return int(round(seconds * 1000)) if math.isfinite(seconds) and 0 < seconds * 1000 <= MAX_DURATION_MS else None


def ffmpeg_audio_flac(raw: bytes, ext: str, *, runner=None) -> bytes | None:
    """Extract a container's first audio stream as 16 kHz mono FLAC for transcription, when ffmpeg exists."""
    demuxer, binary = DEMUXERS.get(str(ext or "").lower()), ffmpeg_path()
    if not demuxer or not binary:
        return None

    def build(path):
        return [binary, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file", "-f", demuxer, "-i", path, "-vn", "-sn", "-dn",
                "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "flac", "-f", "flac", "pipe:1"]

    try:
        out = _with_temp(raw, build, runner or _run_tool, FFMPEG_TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out if out.startswith(b"fLaC") else None


def video_frames(raw: bytes, ext: str, duration_ms: int | None, count: int = 4, *, runner=None) -> list[tuple[int, bytes]]:
    """Up to `count` evenly spaced JPEG frames [(atMs, jpeg)] when ffmpeg exists; [] otherwise (bounded analysis)."""
    demuxer, binary = DEMUXERS.get(str(ext or "").lower()), ffmpeg_path()
    if not demuxer or not binary or not duration_ms:
        return []
    frames = []
    for i in range(count):
        at = int(duration_ms * (i + 0.5) / count)

        def build(path, at=at):
            return [binary, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file", "-f", demuxer, "-ss", f"{at / 1000:.3f}",
                    "-i", path, "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]

        try:
            jpeg = _with_temp(raw, build, runner or _run_tool, 20)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if jpeg.startswith(b"\xff\xd8"):
            frames.append((at, jpeg))
    return frames


# --- images -------------------------------------------------------------------------------------------------------------
def orientation(width: int, height: int) -> str:
    if abs(width - height) <= 0.03 * max(width, height):
        return "square"
    return "landscape" if width > height else "portrait"


def image_info(raw: bytes) -> dict:
    """Displayed dimensions (EXIF orientation applied) from the image header; no full decode, no metadata kept."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
        if width < 1 or height < 1 or width * height > 200_000_000:
            raise ValueError("implausible image size")
        try:
            if image.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
        except Exception:  # noqa: BLE001 - unreadable EXIF keeps the stored orientation
            pass
    return {"width": int(width), "height": int(height), "orientation": orientation(width, height)}


# --- preview processor -------------------------------------------------------------------------------------------------
NO_DECODER = "This server has no decoder for this audio format; the original stays playable and downloadable, and the browser can supply decoded peaks."


def preview(version: dict, raw: bytes, buckets: int = DEFAULT_BUCKETS) -> dict:
    kind, ext = version.get("kind"), str(version.get("extension") or "").lower()
    if kind == "image":
        try:
            return outcome("ready", media=image_info(raw), extractor="preview", extractor_version=PREVIEW_VERSION)
        except Exception:  # noqa: BLE001 - any decoder refusal is the same honest state
            return outcome("unsupported", error="undecodable", detail="This image could not be decoded.", extractor="preview",
                           extractor_version=PREVIEW_VERSION)
    if kind == "video":
        media = dict(mp4_info(raw) or {}) if ext in MP4_EXTENSIONS else {}
        if media.get("durationMs"):
            media["durationSource"] = "mp4_moov"
        else:
            probed = ffprobe_duration(raw, ext)
            if probed:
                media.update(durationMs=probed, durationSource="ffprobe")
        if media.get("width") and media.get("height"):
            media["orientation"] = orientation(media["width"], media["height"])
        state = "ready" if media.get("durationMs") else "partial" if media else "unsupported"
        return outcome(state, media=media, detail=None if state == "ready" else "The video's length could not be read from its header.",
                       error=None if state == "ready" else "duration_unknown", extractor="preview", extractor_version=PREVIEW_VERSION)
    if kind != "audio":
        return outcome("unsupported", error="not_applicable", detail="Previews here cover images, audio and video.")
    media = {}
    if ext == "wav":
        try:
            decoded = wav_waveform(raw, buckets)
            return outcome("ready", media={"durationMs": decoded["durationMs"], "durationSource": "wav_header", "peaks": decoded["peaks"],
                                           "peaksSource": "server_decoded"}, extractor="preview", extractor_version=PREVIEW_VERSION)
        except (wave.Error, EOFError, ValueError, struct.error):
            pass  # e.g. floating-point WAV: try the general decoder below
    probed = probe_duration(raw, ext)
    if probed:
        media.update(durationMs=probed[0], durationSource=probed[1])
    peaks = ffmpeg_peaks(raw, ext, buckets)
    if peaks:
        media.update(peaks=peaks, peaksSource="server_decoded")
    if media.get("durationMs") and peaks:
        return outcome("ready", media=media, extractor="preview", extractor_version=PREVIEW_VERSION)
    if media:
        return outcome("partial", media=media, error="decoder_unavailable", detail=NO_DECODER, extractor="preview", extractor_version=PREVIEW_VERSION)
    return outcome("unsupported", error="decoder_unavailable", detail=NO_DECODER, extractor="preview", extractor_version=PREVIEW_VERSION)


def preview_processor_run(job) -> dict:
    version = job_attr(job, "version")
    media = version.get("media") or {}
    if version.get("legacy") and ((version.get("kind") == "video" and media.get("durationMs")) or (version.get("kind") == "image" and media.get("width"))):
        # Legacy photos/videos already carry verified dimensions/duration from their upload pipeline.
        extra = {"orientation": orientation(media["width"], media["height"])} if media.get("width") and media.get("height") else {}
        return outcome("ready", media=extra, extractor="preview", extractor_version=PREVIEW_VERSION)
    return preview(version, job_raw(job))


PREVIEW = {"name": "library.preview", "capability": "preview", "version": PREVIEW_VERSION, "location": "local", "category": "extract",
           "applies": lambda version: version.get("kind") in ("image", "audio", "video"), "estimate": lambda job: None, "run": preview_processor_run}


def write_media(cur, workspace_id, version: dict, patch: dict) -> bool:
    """Merge allowlisted media facts into `pr_library_assets.media`. Legacy photos/videos keep theirs in workspace JSON."""
    patch = {k: v for k, v in (patch or {}).items() if k in MEDIA_KEYS}
    if not patch or version.get("legacy"):
        return False
    cur.execute("UPDATE public.pr_library_assets SET media=media||%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id=%s",
                (json.dumps(patch), workspace_id, uuid.UUID(hex=version["versionId"])))
    return bool(cur.rowcount)


def card_media(media: dict) -> dict:
    return {k: media[k] for k in CARD_MEDIA if k in (media or {})}


def _stored_media(ctx, version) -> dict:
    media = dict(version.get("media") or {})
    if not version.get("legacy"):
        ctx.cur.execute("SELECT media FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s", (ctx.workspace_id, uuid.UUID(hex=version["versionId"])))
        row = ctx.cur.fetchone()
        if row and isinstance(row[0], dict):
            media.update(row[0])
    return media


def waveform_http(ctx, request):
    """POST .../assets/{key}/waveform {sha256, durationMs, peaks}: peaks the browser decoded from the real recording.
    Stored as `browser_decoded`; server-decoded peaks are never replaced by browser ones."""
    writable(ctx)
    version = versions.get(ctx, request["params"]["key"])
    policy.require(policy.authorize_source(ctx, version, "browse"))
    body = request.get("body")
    if not isinstance(body, dict) or set(body) != {"sha256", "durationMs", "peaks"}:
        c.fail("Send sha256, durationMs and peaks.")
    if version.get("kind") not in ("audio", "video"):
        raise AlphaError("Waveforms belong to audio or video.", 422, code="library_waveform_unsupported")
    sha = body["sha256"]
    if not isinstance(sha, str) or not c.SHA256.fullmatch(sha):
        c.fail("Use the recording's content hash.")
    if version.get("sha256") and sha != version["sha256"]:
        raise AlphaError("This recording changed. Refresh before saving its waveform.", 409, code="library_version_mismatch")
    peaks = body["peaks"]
    if (not isinstance(peaks, list) or not 1 <= len(peaks) <= MAX_BROWSER_PEAKS
            or any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in peaks)):
        c.fail(f"Send 1 to {MAX_BROWSER_PEAKS} peaks between 0 and 1.")
    duration = body["durationMs"]
    if type(duration) is not int or not 1 <= duration <= MAX_DURATION_MS:
        c.fail("Send the decoded duration in milliseconds.")
    stored = _stored_media(ctx, version)
    # Only a duration read from the recording itself bounds the browser's claim; an earlier browser value does not.
    known = stored.get("durationMs") if type(stored.get("durationMs")) is int and stored.get("durationSource") != "browser_decoded" else None
    if known and abs(duration - known) > max(250, known * 0.02):
        raise AlphaError("The decoded length doesn't match this recording.", 422, code="library_waveform_mismatch")
    if stored.get("peaksSource") == "server_decoded":
        return {"assetRef": versions.ref(version), "kept": "server_decoded", "media": card_media(stored)}
    if version.get("legacy"):
        raise AlphaError("Waveforms for this video can't be saved yet.", 422, code="library_waveform_unsupported")
    patch = {"peaks": [round(float(p), 4) for p in peaks], "peaksSource": "browser_decoded", "peaksDurationMs": duration}
    if not known:
        patch.update(durationMs=duration, durationSource="browser_decoded")
    write_media(ctx.cur, ctx.workspace_id, version, patch)
    return {"assetRef": versions.ref(version), "kept": None, "media": card_media({**stored, **patch})}


# --- moments --------------------------------------------------------------------------------------------------------------
def save_moment_action(ctx, envelope: dict, targets: list[dict]) -> dict:
    """moment.save {startMs, endMs, label?}: a person's own in-bounds interval on one audio/video version."""
    writable(ctx)
    if len(targets) != 1:
        c.fail("Save a moment on one recording at a time.")
    version = targets[0]
    if version.get("kind") not in ("audio", "video"):
        raise AlphaError("Moments belong to audio or video.", 422, code="library_moment_unsupported")
    policy.require(policy.authorize_source(ctx, version, "browse"))
    payload = envelope.get("payload") or {}
    if not set(payload) <= {"startMs", "endMs", "label"}:
        c.fail("Send a start, an end and an optional label.")
    label = payload.get("label")
    if label is not None and (not isinstance(label, str) or len(label.strip()) > 120 or any(ord(ch) < 32 for ch in label)):
        c.fail("Use a label of at most 120 characters.")
    duration = bounds(ctx.cur, ctx.workspace_id, version)["duration_ms"]
    if not duration:
        raise AlphaError("This recording's length isn't known yet, so the moment can't be checked.", 409, code="library_duration_unknown")
    loc = c.locator({"kind": "time", "startMs": payload.get("startMs"), "endMs": payload.get("endMs")}, duration_ms=duration)
    text = (label or "").strip() or f"Moment {c.locator_label(loc)}"
    segment = add_user_segment(ctx, version, kind="moment", text=text, locator=loc)
    return c.action_result("applied", result={"assetRef": versions.ref(version), "segment": segment})


# --- transcription ------------------------------------------------------------------------------------------------------
def transcript_items(value: dict, duration_ms: int | None = None) -> list[dict]:
    """Timed transcript segments from a provider result (startMs/endMs, or start/end seconds). Each segment gets its
    own language label; speakers become anonymous labels and any provider-supplied name is dropped."""
    items = []
    for s in (value or {}).get("segments") or []:
        if len(items) >= 5000 or not isinstance(s, dict):
            break
        try:
            if "startMs" in s:
                start, end = int(s["startMs"]), int(s["endMs"])
            else:
                start, end = int(round(float(s["start"]) * 1000)), int(round(float(s["end"]) * 1000))
        except (KeyError, TypeError, ValueError):
            continue
        text = " ".join(str(s.get("text") or "").split())[:20000]
        if not text or start < 0 or end <= start:
            continue
        if duration_ms:
            if start >= duration_ms:
                continue
            if end > duration_ms:
                if end - duration_ms > 1000:
                    continue
                end = duration_ms
        info = detect_language(text)
        note = "Automatic transcript, not reviewed" + (f"; {code_switch_note(info)}" if info["codeSwitched"] else "")
        item = {"kind": "transcript", "origin": "transcript", "text": text, "locator": {"kind": "time", "startMs": start, "endMs": end},
                "language": info["language"], "uncertainty": note}
        if s.get("speaker") is not None:
            item["speaker"] = s["speaker"]
        items.append(item)
    return anonymous_speakers(items)


def _minutes(version: dict) -> float:
    duration = (version.get("media") or {}).get("durationMs")
    if type(duration) is int and duration > 0:
        return duration / 60000
    return max(1.0, int(version.get("bytes") or 0) / 16000 / 60)  # ~128 kbps upper-bound guess for reservation only


def _transcribe_estimate(job):
    return job_attr(job, "providers").estimate("asr", units=_minutes(job_attr(job, "version")))


def transcribe_processor_run(job) -> dict:
    version, providers = job_attr(job, "version"), job_attr(job, "providers")
    common = {"extractor": TRANSCRIPT_EXTRACTOR, "extractor_version": TRANSCRIBE_VERSION}
    if version.get("kind") not in ("audio", "video"):
        return outcome("unsupported", error="not_applicable", detail="Only audio and video are transcribed.", **common)
    if int(version.get("bytes") or 0) > MAX_AUDIO_BYTES:
        return outcome("unsupported", error="media_too_large", detail="Recordings over 25 MB need their audio extracted before transcription; "
                       "the original stays playable and downloadable.", **common)
    try:
        providers.require("asr")
    except ProviderUnavailable as error:
        return outcome("unsupported", error="provider_unavailable", detail=f"Automatic transcription is not set up: {error.reason}.", **common)
    ext = str(version.get("extension") or "").lower()
    raw, filename, mime = job_raw(job), version.get("filename") or f"audio.{ext}", version.get("mime") or "application/octet-stream"
    if ext not in ASR_EXTENSIONS:
        converted = ffmpeg_audio_flac(raw, ext)
        if converted is None:
            return outcome("unsupported", error="format_unsupported", detail="This recording's format needs audio extraction, which isn't available here.",
                           **common)
        raw, filename, mime = converted, filename.rsplit(".", 1)[0] + ".flac", "audio/flac"
        if len(raw) > MAX_AUDIO_BYTES:
            return outcome("unsupported", error="media_too_large", detail="The extracted audio is larger than the transcription provider accepts.", **common)
    try:
        result = providers.transcribe(raw, filename, mime)
    except ProviderUnavailable as error:
        return outcome("unsupported", error="provider_unavailable", detail=f"Automatic transcription is not set up: {error.reason}.", **common)
    except AlphaError as error:
        return outcome("failed", error=(error.code or "provider_failed").replace("library_", ""), detail=str(error),
                       retryable=error.status >= 500 or error.code in ("library_provider_rate_limited", "library_provider_timeout"), **common)
    value = result.value if isinstance(result.value, dict) else {}
    known = (version.get("media") or {}).get("durationMs")
    duration = known if type(known) is int and known > 0 else value.get("durationMs") if type(value.get("durationMs")) is int else None
    items = transcript_items(value, duration)
    media = {} if known else ({"durationMs": duration, "durationSource": "asr_provider"} if duration else {})
    offered = len([s for s in value.get("segments") or [] if isinstance(s, dict)])
    state = "partial" if len(items) < offered else "ready"
    detail = None if items else "No speech was recognised in this recording."
    if state == "partial":
        detail = f"{offered - len(items)} transcript segment(s) were outside the recording and were not kept."
    return outcome(state, segments=items, media=media, provider=result.receipt(), detail=detail, extractor=TRANSCRIPT_EXTRACTOR,
                   extractor_version=f"{TRANSCRIBE_VERSION}:{result.model}"[:80])


TRANSCRIBE = {"name": "library.transcribe", "capability": "transcribe", "version": TRANSCRIBE_VERSION, "location": "cloud", "category": "asr",
              "applies": lambda version: version.get("kind") in ("audio", "video"), "estimate": _transcribe_estimate, "run": transcribe_processor_run}
PROCESSORS = [PREVIEW, TRANSCRIBE]


# --- in-request helpers ------------------------------------------------------------------------------------------------------
def default_providers(ctx):
    intelligence = getattr(getattr(ctx, "service", None), "library_intelligence", None)
    return getattr(intelligence, "providers", None) or Providers()


class LocalJob:
    """A JobContext stand-in for in-request helpers (same attributes as worker A's)."""

    def __init__(self, ctx, version, raw, providers):
        self.workspace_id, self.actor, self.version, self.providers = ctx.workspace_id, ctx.actor, version, providers
        self.now, self.consent_revision, self.processor = ctx.now, policy.revisions(ctx)["grantRevision"], None
        self._ctx, self._raw = ctx, raw

    def raw(self):
        if self._raw is None:
            self._raw = read_original(self._ctx, self.version)
        return self._raw


def transcribe_asset(ctx, ref: dict, *, raw: bytes | None = None, providers=None) -> dict:
    """transcribe_asset(ctx, ref) -> TimedSegments (T03). Without a cloud `asr` grant: `blocked_permission`, no call."""
    version = versions.resolve(ctx, ref)
    decision = policy.authorize_processing(ctx, version, "cloud", "asr")
    if not decision.allowed:
        return outcome("blocked_permission", error=decision.reason, detail=policy.message(decision.reason), extractor=TRANSCRIPT_EXTRACTOR,
                       extractor_version=TRANSCRIBE_VERSION)
    return transcribe_processor_run(LocalJob(ctx, version, raw, providers or default_providers(ctx)))


def read_original(ctx, version: dict) -> bytes:
    """Bounded private-storage read of one version's original, verified against its recorded identity."""
    service = getattr(ctx, "service", None)
    storage = getattr(getattr(service, "library", None), "storage", None) or getattr(getattr(service, "assets", None), "storage", None)
    if storage is None:
        raise AlphaError("Private storage isn't configured.", 503, code="library_storage_not_configured")
    if not version.get("legacy"):
        ctx.cur.execute("SELECT object_name,bytes,mime,etag FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s",
                        (ctx.workspace_id, uuid.UUID(hex=version["versionId"])))
        row = ctx.cur.fetchone()
        if not row:
            raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
        raw = storage.get_bounded(ctx.workspace_id, "file", row[0], int(row[1]))
        if version.get("sha256") and hashlib.sha256(raw).hexdigest() != version["sha256"]:
            raise AlphaError("This file changed in storage.", 409, code="library_version_mismatch")
        return raw
    asset = next((a for a in (ctx.state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and a.get("id") == version["versionId"]), None)
    if not asset or not asset.get("objectName"):
        raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
    if version.get("kind") == "video":
        return storage.get_verified_video(ctx.workspace_id, asset["objectName"], expected_bytes=int(asset.get("bytes") or 0),
                                          expected_mime=asset.get("mime"), expected_etag=asset.get("etag"))
    return storage.get(ctx.workspace_id, "media", asset["objectName"])


register_processors(PROCESSORS)
