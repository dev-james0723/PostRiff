"""Bounded LOCAL supplied-media extraction; no retrieval/model/embedding clients.

Durable seam: persist the JSON job control, then call MediaRuntime.execute outside
the DB transaction with separately resolved local files and a fresh authorization
callback. Persist result.manifest + result.artifacts only after rechecking its
source bindings in the caller's commit transaction. Every derived blob inherits
the source deletion/retention DAG. Neither an eligibility flag nor a local file
is authorization. All model/cohort qualification remains unavailable here.

FFmpeg requires the seekable fd protocol. Inputs use inherited descriptor0;
only fd/pipe protocols and self-contained container demuxers are allowed. No
source path, URL, filter, executable or arbitrary command comes from job JSON.
"""
from array import array
from copy import deepcopy
from fractions import Fraction
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zlib

from . import config, contracts
from .media_extraction import MODALITIES

SCHEMA = 'trend.local-media-job.v1'
METHOD = 'local_fd_media_v1'
LIMITS = {'max_bytes': 64 * 1024 * 1024, 'max_output_bytes': 8 * 1024 * 1024,
          'max_tokens': 65536, 'max_processing_seconds': 60,
          'max_cost_micro_usd': 10**9, 'max_frames': 12}
FORMATS = 'mov,matroska,webm,wav,ogg,flac'
WIDTH, HEIGHT, AUDIO_RATE = 160, 90, 8000
BASE_RIGHTS = ('retrieve', 'store_raw', 'derive_metrics', 'retain_derivatives')
HEX = re.compile(r'[0-9a-f]{64}')


class MediaRuntimeError(contracts.ContractError):
    """Content-free stable failure code suitable for job accounting."""


@dataclass(frozen=True)
class MediaResult:
    manifest: dict
    artifacts: dict[str, bytes]


def _fail(code):
    raise MediaRuntimeError(code)


def _frame_time(logs, requested, duration, previous=None):
    """Resolve native PTS exactly; showinfo's pts_time is display-rounded."""
    bases = re.findall(rb'\bconfig in time_base:\s*(-?\d+)/(\d+)', logs)
    points = re.findall(rb'\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:', logs)
    if len(bases) != 1 or not points or int(bases[0][0]) <= 0 or int(bases[0][1]) <= 0:
        _fail('media_frame_timecode_invalid')
    actual = int(points[0]) * Fraction(int(bases[0][0]), int(bases[0][1]))
    if not 0 <= requested <= actual < duration or (previous is not None and actual < previous):
        _fail('media_frame_timecode_invalid')
    return actual


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        _fail('media_integer_bound')
    return value


def _hash(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        _fail('media_digest_required')
    return value


def _utcnow():
    return contracts.iso(datetime.now(timezone.utc))


def validate_job(job):
    fields = {'schema_version', 'job_id', 'workspace_id', 'actor_id', 'scope_key',
              'decision_cutoff', 'expires_at', 'limits', 'clips'}
    if not isinstance(job, dict) or set(job) != fields or job['schema_version'] != SCHEMA:
        _fail('media_job_contract')
    for key in ('job_id', 'workspace_id', 'actor_id'):
        if contracts.uuid(job[key]) != job[key]:
            _fail('media_id_required')
    if job['scope_key'] != 'workspace:' + job['workspace_id']:
        _fail('media_workspace_scope_required')
    contracts.instant(job['decision_cutoff']); contracts.instant(job['expires_at'])
    limits = job['limits']
    if not isinstance(limits, dict) or set(limits) != set(LIMITS):
        _fail('media_explicit_caps_required')
    for key, ceiling in LIMITS.items():
        if key == 'max_processing_seconds':
            if not 0 < contracts.finite(limits[key]) <= ceiling:
                _fail('media_processing_bound')
        else:
            _integer(limits[key], 0, ceiling)
    clips = job['clips']
    if not isinstance(clips, list) or not 1 <= len(clips) <= 2:
        _fail('media_clip_bound')
    seen, frames = set(), 0
    for clip in clips:
        if not isinstance(clip, dict) or set(clip) != {'clip_id', 'source_id', 'source_scope', 'source_revision',
                'source_digest', 'media_sha256', 'caption_sha256', 'language', 'modalities', 'frame_count'}:
            _fail('media_clip_contract')
        for key in ('clip_id', 'source_id'):
            if contracts.uuid(clip[key]) != clip[key]:
                _fail('media_id_required')
        if clip['clip_id'] in seen:
            _fail('media_duplicate_clip')
        seen.add(clip['clip_id'])
        contracts.scope(clip['source_scope'])
        if clip['source_scope'].startswith('workspace:') and clip['source_scope'] != job['scope_key']:
            _fail('media_foreign_workspace')
        _integer(clip['source_revision'], 1, 2**63 - 1)
        for key in ('source_digest', 'media_sha256'):
            _hash(clip[key])
        if clip['caption_sha256'] is not None:
            _hash(clip['caption_sha256'])
        if not isinstance(clip['language'], str) or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', clip['language']):
            _fail('media_language_required')
        modalities = clip['modalities']
        if (not isinstance(modalities, list) or not 1 <= len(modalities) <= len(MODALITIES)
                or not all(isinstance(m, str) for m in modalities)
                or len(set(modalities)) != len(modalities) or set(modalities) - set(MODALITIES)):
            _fail('media_modality_contract')
        frames += _integer(clip['frame_count'], 0, 12)
        if ('visual' not in modalities and clip['frame_count']) or ('visual' in modalities and not clip['frame_count']):
            _fail('media_frame_request')
    if frames > limits['max_frames']:
        _fail('media_frame_bound')
    return deepcopy(job)


def _modality_grants(value):
    if not isinstance(value, dict) or set(value) != set(MODALITIES):
        _fail('media_explicit_modality_grants_required')
    for grant in value.values():
        contracts.validate_rights({'retrieve': grant})


def _safe_open(root, relative):
    """Walk descriptors, never follow symlinks, reject devices/FIFOs/hardlinks."""
    if not isinstance(relative, str) or '\\' in relative or '\x00' in relative:
        _fail('media_relative_path_required')
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(x in ('', '.', '..') for x in relative.split('/')):
        _fail('media_relative_path_required')
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        _fail('media_absolute_root_required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    child = None
    try:
        for component in (*root.parts[1:], *path.parts[:-1]):
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(child)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail('media_regular_private_file_required')
        result = os.fdopen(child, 'rb'); child = None
        return result
    except OSError:
        _fail('media_path_unavailable')
    finally:
        if child is not None:
            os.close(child)
        os.close(fd)


def _run(argv, source, *, deadline, output_cap):
    """Bound memory/time, kill our child group on failure, never expose stderr."""
    source.seek(0)
    if time.monotonic() >= deadline:
        _fail('media_processing_deadline')
    try:
        process = subprocess.Popen(argv, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=True, start_new_session=True,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    except OSError:
        _fail('media_executable_unavailable')
    buffers = {'out': bytearray(), 'err': bytearray()}
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'out')
            selector.register(process.stderr, selectors.EVENT_READ, 'err')
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _fail('media_processing_deadline')
                for key, _ in selector.select(min(remaining, .1)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj); continue
                    target = buffers[key.data]
                    if len(target) + len(data) > (output_cap if key.data == 'out' else 128 * 1024):
                        _fail('media_decoder_output_bound')
                    target.extend(data)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _fail('media_processing_deadline')
            if process.wait(timeout=remaining):
                _fail('media_decoder_failed')
        return bytes(buffers['out']), bytes(buffers['err'])
    except subprocess.TimeoutExpired:
        _fail('media_processing_deadline')
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # Child can exit between poll and group termination.
            process.wait()
        process.stdout.close(); process.stderr.close()


def parse_transcript(raw, *, format, duration_seconds, max_tokens):
    """Parse supplied UTF-8 SRT/WebVTT; retain original words and cue times."""
    if format not in ('srt', 'vtt') or not isinstance(raw, bytes):
        _fail('media_caption_format')
    _integer(max_tokens, 0, LIMITS['max_tokens'])
    if not 0 < contracts.finite(duration_seconds) <= 90:
        _fail('media_caption_duration_bound')
    if len(raw) > max_tokens:
        _fail('media_token_bound')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        _fail('media_caption_utf8_required')
    if '\x00' in text:
        _fail('media_caption_invalid')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if format == 'vtt':
        if not text.startswith('WEBVTT\n'):
            _fail('media_vtt_header')
        text = text[len('WEBVTT\n'):]
    def seconds(value):
        match = re.fullmatch(r'(?:(\d{2}):)?([0-5]\d):([0-5]\d)[.,](\d{3})', value)
        if not match:
            _fail('media_caption_timecode')
        h, m, s, ms = match.groups()
        return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    cues, quality = [], []
    for block in re.split(r'\n[ \t]*\n', text.strip('\n')):
        if not block:
            continue
        lines = block.split('\n')
        if format == 'vtt' and (lines[0] == 'NOTE' or lines[0].startswith('NOTE ')):
            continue
        if '-->' not in lines[0]:
            lines = lines[1:]
        if len(lines) < 2 or len(cues) >= 512:
            _fail('media_caption_cue_bound')
        timing = re.fullmatch(r'(\S+)\s+-->\s+(\S+)(?:[ \t]+[^\n]*)?', lines[0])
        if not timing:
            _fail('media_caption_timecode')
        start, end = map(seconds, timing.groups())
        if not 0 <= start < end <= duration_seconds or (cues and start < cues[-1]['start_seconds']):
            _fail('media_caption_time_bound')
        if cues and start < cues[-1]['end_seconds'] and 'overlapping_cues' not in quality:
            quality.append('overlapping_cues')
        native = '\n'.join(lines[1:])
        if not native.strip():
            _fail('media_caption_empty_cue')
        cues.append({'start_seconds': start, 'end_seconds': end, 'text': native,
                     'original_timecode': lines[0], 'derivation_kind': 'deterministic_extraction'})
    if not cues:
        _fail('media_caption_empty')
    return {'state': 'available', 'items': cues, 'quality': 'supplied_caption_unverified',
            'quality_flags': quality, 'translated': False, 'asr_performed': False,
            'text_token_upper_bound': len(raw), 'token_budget_basis': 'UTF-8 bytes; no tokenizer/model invoked'}


def _png(gray):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    scanlines = b''.join(b'\0' + gray[i:i + WIDTH] for i in range(0, len(gray), WIDTH))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))


class MediaRuntime:
    def __init__(self, allowed_root, *, values=None, ffmpeg=None, ffprobe=None, temp_root=None, clock=_utcnow):
        self.root, self.values, self.temp_root, self.clock = Path(allowed_root), values, temp_root, clock
        # These are trusted host configuration, never fields in a durable job.
        self.ffmpeg = ffmpeg if ffmpeg is not None else shutil.which('ffmpeg')
        self.ffprobe = ffprobe if ffprobe is not None else shutil.which('ffprobe')

    def execute(self, job, supplied_files, *, authorize):
        job = validate_job(job)
        if not config.workspace_allowed(job['workspace_id'], self.values) or not all(
                config.enabled(name, self.values) for name in ('RADAR', 'TRUST_RECEIPTS', 'MULTIMODAL')):
            return MediaResult({'state': 'disabled', 'clips': [], 'model_calls': 0, 'provider_calls': 0}, {})
        if not callable(authorize):
            _fail('media_current_authorizer_required')
        if not isinstance(supplied_files, dict) or set(supplied_files) != {c['clip_id'] for c in job['clips']}:
            _fail('media_supplied_files_required')
        limits = job['limits']; started = time.monotonic(); deadline = started + limits['max_processing_seconds']
        artifacts, clips, provenance, admitted_modalities, executables = {}, [], [], {}, {}
        usage = {'input_bytes': 0, 'artifact_bytes': 0, 'text_token_upper_bound': 0,
                 'model_tokens': 0, 'cost_micro_usd': 0, 'model_calls': 0, 'provider_calls': 0, 'frames': 0}
        expiry = job['expires_at']

        def check_current(clip):
            nonlocal expiry, deadline
            if not config.workspace_allowed(job['workspace_id'], self.values) or not all(
                    config.enabled(name, self.values) for name in ('RADAR', 'TRUST_RECEIPTS', 'MULTIMODAL')):
                _fail('media_disabled_during_execution')
            now = self.clock(); at = contracts.instant(now)
            if time.monotonic() >= deadline:
                _fail('media_processing_deadline')
            if at >= contracts.instant(job['expires_at']) or contracts.instant(job['decision_cutoff']) > at:
                _fail('media_job_expired_or_future')
            snapshot = authorize(deepcopy(job))
            # Authorization may perform a fresh database transaction. Its
            # timestamp must be judged against the time after it returns.
            now = self.clock(); at = contracts.instant(now)
            if time.monotonic() >= deadline:
                _fail('media_processing_deadline')
            if at >= contracts.instant(job['expires_at']) or contracts.instant(job['decision_cutoff']) > at:
                _fail('media_job_expired_or_future')
            if (not isinstance(snapshot, dict) or snapshot.get('authorized') is not True
                    or any(snapshot.get(k) != job[k] for k in ('workspace_id', 'actor_id'))):
                _fail('media_authorization_denied')
            checked = contracts.instant(snapshot['checked_at']); valid = contracts.instant(snapshot['valid_until'])
            if not checked <= at < valid or (at - checked).total_seconds() > 5:
                _fail('media_current_snapshot_required')
            if not isinstance(snapshot.get('authorized_source_scopes'), list):
                _fail('media_authorization_snapshot_invalid')
            source = snapshot.get('sources', {}).get(clip['source_id'], {})
            if (source.get('deleted') is not False or source.get('scope_key') != clip['source_scope']
                    or type(source.get('revision')) is not int or source.get('revision') != clip['source_revision']
                    or source.get('payload_digest') != clip['source_digest']
                    or source.get('scope_key') not in snapshot.get('authorized_source_scopes', [])):
                _fail('media_source_binding_unavailable')
            if (contracts.instant(source['available_at']) > contracts.instant(job['decision_cutoff'])
                    or contracts.instant(source['retention_until']) <= at):
                _fail('media_source_expired_or_future')
            bindings = source['media_bindings']
            if (not isinstance(bindings, list) or not 1 <= len(bindings) <= 100
                    or {'media_sha256': clip['media_sha256'], 'caption_sha256': clip['caption_sha256']} not in bindings):
                _fail('media_source_attachment_binding_unavailable')
            rights = [contracts.validate_rights(source[k]) for k in ('rights', 'policy_rights')]
            if any(set(r) != set(contracts.PERMISSIONS) for r in rights):
                _fail('media_explicit_operation_grants_required')
            for key in ('modality_rights', 'policy_modality_rights'):
                _modality_grants(source[key])
            needed = BASE_RIGHTS + (('share_across_workspaces',) if clip['source_scope'].startswith('shared:') else ())
            if not all(contracts.permits(r, op, clip['source_scope'], now) for r in rights for op in needed):
                _fail('media_current_right_not_permitted')
            allowed = {m: all(contracts.permits({'retrieve': source[k][m]}, 'retrieve', clip['source_scope'], now)
                             for k in ('modality_rights', 'policy_modality_rights')) for m in MODALITIES}
            original = admitted_modalities.setdefault(clip['clip_id'], allowed.copy())
            if any(original[m] and not allowed[m] for m in clip['modalities']):
                _fail('media_modality_revoked_during_execution')
            expiries = [expiry, source['retention_until'], snapshot['valid_until']]
            expiries += [r[op]['expires_at'] for r in rights for op in needed]
            expiries += [source[k][m]['expires_at'] for k in ('modality_rights', 'policy_modality_rights')
                         for m in clip['modalities'] if allowed[m]]
            expiry = min(expiries, key=contracts.instant)
            deadline = min(deadline, time.monotonic() + (contracts.instant(expiry) - at).total_seconds())
            return source, allowed

        def current(clip):
            try:
                result = check_current(clip)
                if not config.workspace_allowed(job['workspace_id'], self.values) or not all(
                        config.enabled(name, self.values) for name in ('RADAR', 'TRUST_RECEIPTS', 'MULTIMODAL')):
                    _fail('media_disabled_during_execution')
                return result
            except (KeyError, TypeError, AttributeError):
                _fail('media_authorization_snapshot_invalid')

        def read_file(relative, expected):
            remaining = limits['max_bytes'] - usage['input_bytes']
            with _safe_open(self.root, relative) as opened:
                if not 0 < os.fstat(opened.fileno()).st_size <= remaining:
                    _fail('media_input_byte_bound')
                data = opened.read(remaining + 1)
            if len(data) > remaining:
                _fail('media_input_byte_bound')
            if hashlib.sha256(data).hexdigest() != expected:
                _fail('media_input_digest_mismatch')
            usage['input_bytes'] += len(data)
            return data

        def invoke(executable, args, stream, clip, output_cap):
            current(clip)
            if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
                _fail('media_executable_unavailable')
            name = 'ffprobe' if executable == self.ffprobe else 'ffmpeg'
            try:
                # Host-installed executable identity, not a claim to attest all
                # dynamically linked libraries or qualify a semantic model.
                with open(executable, 'rb') as binary:
                    info = os.fstat(binary.fileno())
                    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                    previous = executables.get(name)
                    if previous and identity != previous['identity']:
                        _fail('media_executable_changed')
                    if not previous:
                        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 128 * 1024 * 1024:
                            _fail('media_executable_bound')
                        digest = hashlib.sha256()
                        size = 0
                        while data := binary.read(65536):
                            size += len(data)
                            if size > info.st_size or time.monotonic() >= deadline:
                                _fail('media_executable_bound')
                            digest.update(data)
                        if size != info.st_size:
                            _fail('media_executable_changed')
                        executables[name] = {'identity': identity, 'sha256': digest.hexdigest(), 'byte_length': size}
            except OSError:
                _fail('media_executable_unavailable')
            return _run([str(executable), *args], stream, deadline=deadline, output_cap=output_cap)

        input_options = ['-protocol_whitelist', 'fd,pipe', '-format_whitelist', FORMATS,
                         '-probesize', '1048576', '-analyzeduration', '3000000', '-fd', '0', '-i', 'fd:']
        with tempfile.TemporaryDirectory(prefix='rafii-media-', dir=self.temp_root) as directory:
            os.chmod(directory, 0o700)
            for clip in job['clips']:
                source, allowed = current(clip)
                files = supplied_files[clip['clip_id']]
                if not isinstance(files, dict) or set(files) - {'media', 'transcript', 'transcript_format'} or 'media' not in files:
                    _fail('media_supplied_file_contract')
                if bool(files.get('transcript')) != bool(clip['caption_sha256']):
                    _fail('media_caption_binding_required')
                missing = lambda reason: {'state': 'unavailable', 'reason': reason, 'items': []}
                out = {'clip_id': clip['clip_id'], 'source_id': clip['source_id'], 'language': clip['language'],
                       'language_basis': 'supplied_annotation_unverified',
                       'media_sha256': clip['media_sha256'], 'modalities': {m: missing('not_requested') for m in MODALITIES},
                       'asr': missing('asr_model_and_language_cohort_unavailable'),
                       'ocr': missing('ocr_model_and_language_cohort_unavailable'),
                       'semantic_qualification': 'unqualified', 'full_video_understanding': False}
                for m in clip['modalities']:
                    out['modalities'][m] = missing('extractor_unavailable' if allowed[m] else 'current_modality_right_not_permitted')
                provenance.append({'source_scope': clip['source_scope'], 'source_id': clip['source_id'],
                    'source_revision': clip['source_revision'], 'source_digest': clip['source_digest'],
                    'media_sha256': clip['media_sha256'], 'caption_sha256': clip['caption_sha256']})
                if not any(allowed[m] and m != 'ocr' for m in clip['modalities']):
                    out['metadata'] = missing('no_available_authorized_local_extractor'); clips.append(out); continue
                if not self.ffprobe:
                    out['metadata'] = missing('ffprobe_unavailable'); clips.append(out); continue
                raw = read_file(files['media'], clip['media_sha256'])
                # Only self-contained supported signatures; never HLS/concat/SVG.
                if not (raw[:4] == b'RIFF' and raw[8:12] == b'WAVE' or raw[4:8] == b'ftyp'
                        or raw[:4] in (b'\x1aE\xdf\xa3', b'OggS', b'fLaC')):
                    _fail('media_container_not_admitted')
                with tempfile.TemporaryFile(dir=directory) as stream:
                    stream.write(raw); del raw; stream.flush()
                    stdout, _ = invoke(self.ffprobe, ['-v', 'error', '-max_alloc', '67108864', *input_options,
                        '-show_entries', 'format=duration,format_name:stream=index,codec_type,codec_name,width,height,sample_rate,channels,start_time',
                        '-of', 'json'], stream, clip, 65536)
                    try:
                        probe = json.loads(stdout); duration = float(probe['format']['duration']); streams = probe['streams']
                        if not math.isfinite(duration) or not 0 < duration <= 90 or not 1 <= len(streams) <= 8:
                            _fail('media_duration_or_stream_bound')
                        for s in streams:
                            offset = float(s.get('start_time', 0))
                            if not math.isfinite(offset) or abs(offset) > .001:
                                _fail('media_nonzero_timeline_unavailable')
                            if s['codec_type'] == 'video' and not (0 < s['width'] <= 4096 and 0 < s['height'] <= 4096 and s['width'] * s['height'] <= 8_294_400):
                                _fail('media_resolution_bound')
                            if s['codec_type'] == 'audio' and not 1 <= s['channels'] <= 8:
                                _fail('media_channel_bound')
                    except MediaRuntimeError:
                        raise
                    except (KeyError, TypeError, ValueError, OverflowError):
                        _fail('media_probe_invalid')
                    out['metadata'] = {'state': 'available', 'duration_seconds': duration, 'streams': streams,
                                       'container': probe['format']['format_name'], 'derivation_kind': 'deterministic_extraction'}
                    if 'transcript' in clip['modalities'] and allowed['transcript'] and files.get('transcript'):
                        current(clip)
                        caption = read_file(files['transcript'], clip['caption_sha256'])
                        parsed = parse_transcript(caption, format=files.get('transcript_format'), duration_seconds=duration,
                                                  max_tokens=limits['max_tokens'] - usage['text_token_upper_bound'])
                        usage['text_token_upper_bound'] += parsed['text_token_upper_bound']
                        out['modalities']['transcript'] = parsed
                    decode = ['-hide_banner', '-nostdin', '-max_alloc', '67108864', '-threads', '1', *input_options]
                    types = {s['codec_type'] for s in streams}
                    if 'visual' in clip['modalities'] and allowed['visual'] and self.ffmpeg and 'video' in types:
                        frames = []
                        previous_time = None
                        for n in range(clip['frame_count']):
                            requested = n * Fraction(str(duration)) / clip['frame_count']
                            at = float(requested)
                            video_filter = f'select=gte(t\\,{requested.numerator}/{requested.denominator}),scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=gray,showinfo'
                            pixels, logs = invoke(self.ffmpeg, [*decode, '-v', 'info', '-map', '0:v:0', '-an',
                                '-vf', video_filter, '-frames:v', '1', '-fps_mode', 'passthrough', '-threads', '1',
                                '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], stream, clip, WIDTH * HEIGHT)
                            if len(pixels) != WIDTH * HEIGHT:
                                _fail('media_frame_decode_unavailable')
                            previous_time = _frame_time(logs, requested, Fraction(str(duration)), previous_time)
                            actual = float(previous_time)
                            image = _png(pixels); identity = hashlib.sha256(image).hexdigest()
                            usage['artifact_bytes'] += 0 if identity in artifacts else len(image)
                            if usage['artifact_bytes'] > limits['max_output_bytes']:
                                _fail('media_output_byte_bound')
                            artifacts[identity] = image; usage['frames'] += 1
                            frames.append({'frame_id': identity, 'at_seconds': actual, 'requested_at_seconds': at,
                                'mime_type': 'image/png', 'width': WIDTH, 'height': HEIGHT, 'evidence_refs': [clip['source_id']],
                                'derivation_kind': 'deterministic_extraction', 'quality': 'bounded_grayscale_sample_no_semantic_inspection'})
                        out['modalities']['visual'] = {'state': 'available', 'items': frames, 'sampling': 'evenly_requested_first_frame_at_or_after',
                                                       'semantic_findings': [], 'quality': 'measured_frame_samples_only'}
                    if 'audio' in clip['modalities'] and allowed['audio'] and self.ffmpeg and 'audio' in types:
                        pcm, _ = invoke(self.ffmpeg, [*decode, '-v', 'error', '-map', '0:a:0', '-vn', '-t', str(duration),
                            '-ac', '1', '-ar', str(AUDIO_RATE), '-f', 's16le', 'pipe:1'], stream, clip, 90 * AUDIO_RATE * 2)
                        if not pcm or len(pcm) % 2:
                            _fail('media_audio_decode_unavailable')
                        samples = array('h', pcm)
                        if sys.byteorder != 'little': samples.byteswap()
                        descriptor = {'sample_count': len(samples), 'sample_rate_hz': AUDIO_RATE,
                            'decoded_duration_seconds': len(samples) / AUDIO_RATE,
                            'peak_amplitude': max(abs(x) for x in samples) / 32768,
                            'rms_amplitude': math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768,
                            'clipped_sample_fraction': sum(abs(x) >= 32767 for x in samples) / len(samples)}
                        out['modalities']['audio'] = {'state': 'available', 'items': [{'start_seconds': 0, 'end_seconds': min(duration, len(samples) / AUDIO_RATE),
                            'descriptor': descriptor, 'evidence_refs': [clip['source_id']], 'derivation_kind': 'deterministic_extraction'}],
                            'quality': 'resampled_mono_8khz_amplitude_only', 'semantic_findings': []}
                current(clip)
                clips.append(out)
            # Authorization changes or expiry while decoding discard the entire
            # job. No partial artifacts escape, even if previous clips succeeded.
            for clip in job['clips']:
                current(clip)
        usage['processing_seconds'] = time.monotonic() - started
        manifest = {'schema_version': 'trend.local-media-result.v1', 'state': 'extracted' if any('duration_seconds' in c.get('metadata', {}) for c in clips) else 'unavailable',
            'job_id': job['job_id'], 'workspace_id': job['workspace_id'], 'scope_key': job['scope_key'],
            'input_digest': contracts.digest(job), 'decision_cutoff': job['decision_cutoff'], 'computed_at': self.clock(),
            'expires_at': expiry, 'clips': clips, 'dependencies': provenance, 'usage': usage,
            'method': {'version': METHOD, 'artifact_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'executables': {name: {k: v for k, v in entry.items() if k != 'identity'} for name, entry in executables.items()},
                       'lineage_basis': 'runtime source and invoked executable bytes; dynamic libraries not attested'},
            'qualification': 'unqualified', 'full_video_understanding': False, 'media_downloaded': False,
            'model_execution': 'unavailable_no_qualified_model_or_cohort', 'embedding_execution': 'not_requested',
            'deletion': {'temporary_copies_removed': True, 'supplied_files_deleted': False,
                         'artifacts_require_source_deletion_dag': True, 'read_time_rights_recheck_required': True}}
        usage['output_bytes'] = 0
        for _ in range(3):
            usage['output_bytes'] = usage['artifact_bytes'] + len(contracts.canonical(manifest).encode())
        if usage['output_bytes'] > limits['max_output_bytes']:
            _fail('media_output_byte_bound')
        return MediaResult(manifest, artifacts)
