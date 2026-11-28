"""Explicit local analysis of reference speech timing. No recognized wording leaves this worker."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from threading import BoundedSemaphore
import time
import wave

from postriff_alpha.domain import AlphaError
from . import creative_video_media as media
from .growth.trends.media_runtime import MediaRuntimeError, _run, parse_transcript

MODEL_SHA256 = '317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1'
MODEL_BYTES = 874188075
MAX_ANALYSIS_MS = 15000
SPEECH_SLOT = BoundedSemaphore(1)
_TIMED = re.compile(r'^\[(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)$')


def _segments(raw, duration_ms):
    cues = []
    for line in raw.decode('utf-8').splitlines():
        if not line.strip():
            continue
        match = _TIMED.fullmatch(line.strip())
        if not match:
            raise ValueError('Unrecognized local ASR output')
        start, end, words = match.groups()
        if (not words or (words.startswith('[') and words.endswith(']'))
                or not any(c.isalnum() for c in words)):
            continue
        # Preserve no text, token IDs, speaker identifiers or phonetic data in the result.
        cues.append(f'{start} --> {end}\ncue')
    if not cues:
        return []
    try:
        result = parse_transcript('\n\n'.join(cues).encode(), format='srt', duration_seconds=duration_ms/1000,
                                  max_tokens=65536)
    except MediaRuntimeError as error:
        raise ValueError('Invalid local ASR offsets') from error
    return [{'startMs':round(c['start_seconds']*1000), 'endMs':round(c['end_seconds']*1000)} for c in result['items']]


def speech_timing(raw, analysis, language, model_path):
    report = {'state':'unavailable', 'method':'whisper.cpp', 'model':'large-v3-turbo-q8_0', 'language':language,
              'timingKind':'estimated_segments', 'analyzedDurationMs':0, 'segments':[]}
    if not analysis.get('hasAudio'):
        return {**report, 'state':'no_audio_track'}
    if language not in ('en','zh','auto') or not isinstance(model_path, str) or not Path(model_path).is_absolute():
        return {**report, 'reason':'model_unavailable'}
    executable = shutil.which('whisper-cli')
    if not executable:
        return {**report, 'reason':'worker_unavailable'}
    if not SPEECH_SLOT.acquire(blocking=False):
        return {**report, 'reason':'worker_busy'}
    try:
        with ExitStack() as stack:
            # Only a pinned operator-selected local file may enter the model loader.
            model = stack.enter_context(os.fdopen(os.open(model_path, os.O_RDONLY | os.O_NONBLOCK), 'rb'))
            info = os.fstat(model.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != MODEL_BYTES:
                return {**report, 'reason':'model_unavailable'}
            deadline = time.monotonic() + 50
            if hashlib.file_digest(model, 'sha256').hexdigest() != MODEL_SHA256:
                return {**report, 'reason':'model_unavailable'}
            model.seek(0)
            duration = min(MAX_ANALYSIS_MS, analysis['durationMs'])
            source = media._source(stack, raw)
            pcm = media._cmd('ffmpeg', [*media._decode(), '-map','0:a:0','-vn','-sn','-dn',
                             '-af','aresample=16000:async=1:first_pts=0','-ac','1','-t',f'{duration/1000:.3f}',
                             '-f','s16le','pipe:1'], source, deadline, duration * 32 + 32)
            duration = min(duration, len(pcm) // 32)
            if not duration:
                return {**report, 'reason':'no_decodable_audio'}
            if not any(pcm):
                return {**report, 'state':'measured', 'analyzedDurationMs':duration}
            wav = stack.enter_context(tempfile.TemporaryFile())
            with wave.open(wav, 'wb') as writer:
                writer.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                writer.writeframes(pcm[:duration*32])
            output, _ = _run([executable, '-m', f'/dev/fd/{model.fileno()}', '-f', f'/dev/fd/{wav.fileno()}',
                              '-l', language, '-ng', '-t', '4', '-p', '1'], wav, deadline=deadline,
                             output_cap=65536, pass_fds=(model.fileno(),wav.fileno()))
            return {**report, 'state':'measured', 'analyzedDurationMs':duration,
                    'segments':_segments(output,duration)}
    except OSError:
        return {**report, 'reason':'model_unavailable'}
    except (ValueError, AlphaError, MediaRuntimeError):
        return {**report, 'reason':'analysis_unavailable'}
    finally:
        SPEECH_SLOT.release()
