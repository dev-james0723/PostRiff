"""What an uploaded file really is, and how long a recording runs, without ffmpeg (PRD R-FWR-04).

The declared MIME type is only a hint for the upload URL; these readers decide from the stored bytes, which the caller
has already capped at the upload limit. Each answer is a measured value or a `SniffError` with a stable code:
`mime_mismatch` (the bytes are not what was declared), `unsupported` (a format this release cannot measure: WebM,
an Ogg codec other than Opus/Vorbis), `duration_unreadable` (a supported container whose length can't be read).

Durations: WAV from the `fmt `/`data` chunks; MP4/M4A from `moov`/`mvhd` (shared `mp4_boxes`); MP3 by walking every
frame header (an Xing/VBRI count can be forged, frames can't); Ogg Opus/Vorbis from the last page's granule position.
"""
from __future__ import annotations

import struct

from .. import mp4_boxes

DECLARED = {
    "application/pdf": "pdf", "application/x-pdf": "pdf",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/vnd.wave": "wav",
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mpeg3": "mp3", "audio/x-mpeg-3": "mp3",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a",
    "audio/ogg": "ogg", "audio/opus": "ogg", "application/ogg": "ogg",
}
# Audio people commonly have that this release cannot measure without a decoder: refused before upload.
REFUSED = {"audio/webm": "webm", "video/webm": "webm", "audio/aac": "aac", "audio/x-aac": "aac", "audio/flac": "flac", "audio/x-flac": "flac",
           "audio/amr": "amr", "audio/3gpp": "3gp", "video/mp4": "video", "video/quicktime": "video"}
CANONICAL = {"pdf": "application/pdf", "wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg"}
LABELS = {"pdf": "PDF", "wav": "WAV recording", "mp3": "MP3 recording", "m4a": "M4A recording", "ogg": "Ogg/Opus recording"}
AUDIO = ("wav", "mp3", "m4a", "ogg")
AUDIO_BRANDS = frozenset({b"M4A ", b"M4B ", b"mp42", b"mp41", b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"dash"})
_MPEG1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MPEG2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
OGG_TAIL = 256 * 1024


class SniffError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def declared_type(kind, mime):
    """The format a begin request declares, or a SniffError naming why it can't be accepted."""
    value = mime.strip().lower() if isinstance(mime, str) else ""
    found = DECLARED.get(value)
    if found is None:
        refused = REFUSED.get(value)
        if refused == "webm":
            raise SniffError("unsupported", "WebM recordings can't be measured here yet. Export the recording as M4A, MP3 or WAV, or upload a transcript.")
        if refused == "video":
            raise SniffError("unsupported", "Upload an audio file, not a video. Export the audio as M4A, MP3 or WAV.")
        if refused:
            raise SniffError("unsupported", "This audio format can't be measured here yet. Export it as M4A, MP3 or WAV, or upload a transcript.")
        raise SniffError("unsupported", "Use a PDF, or an M4A, MP3, WAV or Ogg/Opus recording.")
    if (kind == "pdf") != (found == "pdf"):
        raise SniffError("mime_mismatch", "The file type doesn't match what was chosen. Choose the file again.")
    return found


def _audio_brand(head):
    if len(head) < 12 or head[4:8] != b"ftyp":
        return False
    size = struct.unpack(">I", head[:4])[0]
    end = min(len(head), size) if size >= 16 else 12
    brands = [bytes(head[8:12])] + [bytes(head[i:i + 4]) for i in range(16, end - 3, 4)]
    return any(b in AUDIO_BRANDS for b in brands)


def _mp3_frame(data, pos):
    """(frame length, samples per frame, sample rate) for a valid MPEG Layer III header at pos, else None."""
    if pos + 4 > len(data) or data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
        return None
    version, layer = (data[pos + 1] >> 3) & 3, (data[pos + 1] >> 1) & 3
    index, rate_index, padding = data[pos + 2] >> 4, (data[pos + 2] >> 2) & 3, (data[pos + 2] >> 1) & 1
    if version == 1 or layer != 1 or index in (0, 15) or rate_index == 3:
        return None
    rate = _RATES[version][rate_index]
    if version == 3:
        return 144000 * _MPEG1[index] // rate + padding, 1152, rate
    return 72000 * _MPEG2[index] // rate + padding, 576, rate


def _mp3_sync(data, start, end, window=4096):
    """The first offset in [start, start+window) where two consecutive valid frames begin."""
    limit = min(end - 4, start + window)
    pos = start
    while pos <= limit:
        pos = data.find(b"\xff", pos, limit + 1)
        if pos < 0:
            return None
        frame = _mp3_frame(data, pos)
        if frame and pos + frame[0] + 4 <= len(data) and _mp3_frame(data, pos + frame[0]):
            return pos
        pos += 1
    return None


def _id3_end(data):
    if len(data) >= 10 and data[:3] == b"ID3" and all(b < 0x80 for b in data[6:10]):
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        return 10 + size + (10 if data[5] & 0x10 else 0)
    return 0


def detect(data):
    """'pdf' | 'wav' | 'm4a' | 'mp4_other' | 'ogg' | 'webm' | 'mp3' | None, from the leading bytes."""
    head = bytes(data[:4096])
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a" if _audio_brand(head) else "mp4_other"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    start = _id3_end(data)
    if start < len(data) and _mp3_sync(data, start, len(data)) is not None:
        return "mp3"
    return None


def _unreadable(label):
    return SniffError("duration_unreadable", f"Rafii couldn't measure how long this {label} runs, so it can't be transcribed. Export it again as M4A, MP3 or WAV, or upload a transcript.")


def wav_seconds(data):
    pos, fmt, size_found = 12, None, None
    for _ in range(64):
        if pos + 8 > len(data):
            break
        chunk, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = pos + 8
        if chunk == b"fmt " and size >= 16 and body + 16 <= len(data):
            fmt = struct.unpack("<HHIIHH", data[body:body + 16])
        elif chunk == b"data":
            remaining = len(data) - body
            size_found = remaining if size in (0, 0xFFFFFFFF) or size > remaining else size
            break
        pos = body + size + (size & 1)
    if fmt is None or size_found is None:
        raise _unreadable(LABELS["wav"])
    _format, channels, rate, byte_rate, _align, _bits = fmt
    if channels < 1 or not 1000 <= rate <= 384000 or byte_rate <= 0:
        raise _unreadable(LABELS["wav"])
    return size_found / byte_rate


def m4a_seconds(data):
    try:
        walked = mp4_boxes.walk(lambda offset, length: data[offset:offset + length], len(data), max_header_reads=16)
    except mp4_boxes.BoxError:
        raise _unreadable(LABELS["m4a"]) from None
    if not walked["moov"] or walked["moov"][1] > mp4_boxes.MOOV_MAX:
        raise _unreadable(LABELS["m4a"])
    offset, size = walked["moov"]
    parsed = mp4_boxes.parse_moov(data[offset:offset + size])
    if parsed["width"] or parsed["height"]:
        raise SniffError("mime_mismatch", "This file has video in it. Upload an audio file instead (M4A, MP3 or WAV).")
    if not parsed["duration"]:
        raise _unreadable(LABELS["m4a"])
    return float(parsed["duration"])


def mp3_seconds(data):
    end = len(data) - (128 if len(data) >= 128 and data[-128:-125] == b"TAG" else 0)
    first = _mp3_sync(data, _id3_end(data), end)
    if first is None:
        raise SniffError("mime_mismatch", "This file is not an MP3 recording.")
    pos, frames, samples, rate0, covered = first, 0, 0, None, 0
    while pos + 4 <= end:
        frame = _mp3_frame(data, pos)
        if frame is None:
            if data[pos:pos + 8] == b"APETAGEX" or data[pos:pos + 3] == b"TAG" or data[pos:pos + 9] == b"LYRICSBEG":
                break
            resync = _mp3_sync(data, pos + 1, end, window=2048)
            if resync is None:
                break
            pos = resync
            continue
        length, spf, rate = frame
        if pos + length > end:
            break
        if rate0 is None:
            rate0 = rate
        elif rate != rate0:
            raise _unreadable(LABELS["mp3"])
        frames, samples, covered, pos = frames + 1, samples + spf, covered + length, pos + length
    if frames < 2 or covered < 0.9 * (end - first):
        raise _unreadable(LABELS["mp3"])
    return samples / rate0


def _ogg_page(data, pos):
    """(granule, serial, payload offset) for a well-formed Ogg page header at pos, else None."""
    if pos + 27 > len(data) or data[pos:pos + 4] != b"OggS" or data[pos + 4] != 0:
        return None
    granule, serial = struct.unpack("<qI", data[pos + 6:pos + 18])
    segments = data[pos + 26]
    payload = pos + 27 + segments
    if payload > len(data):
        return None
    return granule, serial, payload


def ogg_seconds(data):
    first = _ogg_page(data, 0)
    if first is None:
        raise _unreadable(LABELS["ogg"])
    _granule, serial, payload = first
    packet = data[payload:payload + 19]
    if packet[:8] == b"OpusHead" and len(packet) >= 12:
        rate, skip = 48000, struct.unpack("<H", packet[10:12])[0]
    elif packet[:7] == b"\x01vorbis" and len(packet) >= 16:
        rate, skip = struct.unpack("<I", packet[12:16])[0], 0
    else:
        raise SniffError("unsupported", "This Ogg file uses a codec Rafii can't measure. Export it as M4A, MP3 or WAV, or upload a transcript.")
    if not 1000 <= rate <= 384000:
        raise _unreadable(LABELS["ogg"])
    search, low = len(data), max(0, len(data) - OGG_TAIL)
    while True:
        pos = data.rfind(b"OggS", low, search)
        if pos < 0:
            raise _unreadable(LABELS["ogg"])
        page = _ogg_page(data, pos)
        if page and page[1] == serial and page[0] >= 0:
            seconds = (page[0] - skip) / rate
            if seconds <= 0:
                raise _unreadable(LABELS["ogg"])
            return seconds
        search = pos


def inspect(data, declared):
    """{"type", "seconds"} for bytes that really are the declared format (seconds None for a PDF)."""
    actual = detect(data)
    if actual == "webm":
        raise SniffError("unsupported", "WebM recordings can't be measured here yet. Export the recording as M4A, MP3 or WAV, or upload a transcript.")
    if actual != declared:
        raise SniffError("mime_mismatch", f"This file is not a {LABELS[declared]}. Choose the file again, or export it in that format.")
    if declared == "pdf":
        return {"type": "pdf", "seconds": None}
    seconds = {"wav": wav_seconds, "mp3": mp3_seconds, "m4a": m4a_seconds, "ogg": ogg_seconds}[declared](data)
    return {"type": declared, "seconds": round(float(seconds), 3)}
