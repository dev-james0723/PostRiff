"""Bounded ISO BMFF / QuickTime box reading for uploaded videos (chat-context SPEC §7.2, §7.3 step 6).

No ffmpeg on the Python runtime: the server reads only the `ftyp` brand, walks top-level box headers with a small
number of range reads to find `moov`, and parses `moov` for duration, frame size and location tags. Odd or truncated
input gives `None` values or raises `BoxError`, never anything else.

Blank rule shared with the browser (`web/src/features/agent/attachments/video-file.ts`): a location or device value is
blank when every byte after its 4-byte header (QuickTime string size+language, or full-box version+flags) is 0x00 or
0x20. For `meta` item values it is the bytes after the `data` box's type and locale words.
"""
from __future__ import annotations

import struct

BRANDS = frozenset({b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"qt  "})
MOOV_MAX = 2 * 1024 * 1024
LOCATION_ATOMS = (b"\xa9xyz", b"loci")
LOCATION_KEYS = ("com.apple.quicktime.location.iso6709",)
CONTAINERS = frozenset({b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"mvex", b"edts"})


class BoxError(ValueError):
    pass


def brand(prefix):
    """The allowed brand of a file whose first bytes are `prefix` (major brand first, then compatible), else None."""
    if not isinstance(prefix, (bytes, bytearray)) or len(prefix) < 12 or prefix[4:8] != b"ftyp":
        return None
    size = struct.unpack(">I", prefix[:4])[0]
    end = min(len(prefix), size) if size >= 16 else 12
    candidates = [bytes(prefix[8:12])] + [bytes(prefix[i:i + 4]) for i in range(16, end - 3, 4)]
    found = next((b for b in candidates if b in BRANDS), None)
    return found.decode("latin-1") if found else None


def _header(data, offset, limit):
    """(type, header_len, box_size) for the box at `offset`; box_size None = runs to `limit`."""
    if offset + 8 > limit:
        raise BoxError("truncated box header")
    size, kind = struct.unpack(">I4s", bytes(data[offset:offset + 8]))
    if size == 1:
        if offset + 16 > limit:
            raise BoxError("truncated large size")
        size = struct.unpack(">Q", bytes(data[offset + 8:offset + 16]))[0]
        header = 16
    elif size == 0:
        return kind, 8, limit - offset
    else:
        header = 8
    if size < header:
        raise BoxError("box smaller than its header")
    return kind, header, size


def walk(read_at, total_bytes, max_header_reads=8):
    """Find the top-level `moov` with at most `max_header_reads` 16-byte reads. `read_at(offset, length) -> bytes`.

    Returns {"boxes": [(type, offset, size)], "moov": (offset, size) | None, "complete": bool}."""
    if not isinstance(total_bytes, int) or total_bytes < 8:
        raise BoxError("file too small")
    boxes, offset, reads = [], 0, 0
    while offset + 8 <= total_bytes:
        if reads >= max_header_reads:
            return {"boxes": boxes, "moov": None, "complete": False}
        head = bytes(read_at(offset, 16) or b"")
        reads += 1
        if len(head) < 8:
            raise BoxError("short read")
        kind, _, size = _header(head, 0, len(head)) if struct.unpack(">I", head[:4])[0] != 0 else (head[4:8], 8, total_bytes - offset)
        if offset + size > total_bytes:
            raise BoxError("box runs past the end of the file")
        boxes.append((kind.decode("latin-1"), offset, size))
        if kind == b"moov":
            return {"boxes": boxes, "moov": (offset, size), "complete": True}
        offset += size
    return {"boxes": boxes, "moov": None, "complete": True}


def _children(data, start, end):
    offset = start
    while offset + 8 <= end:
        kind, header, size = _header(data, offset, end)
        if offset + size > end:
            raise BoxError("child box runs past its parent")
        yield kind, offset + header, offset + size
        offset += size


def _blank(value):
    return all(b in (0x00, 0x20) for b in value)


def _mvhd(data, start, end):
    body = data[start:end]
    if len(body) < 20:
        raise BoxError("short mvhd")
    if body[0] == 1:
        if len(body) < 32:
            raise BoxError("short mvhd v1")
        timescale, duration = struct.unpack(">IQ", bytes(body[20:32]))
        unknown = duration == 0xFFFFFFFFFFFFFFFF
    else:
        timescale, duration = struct.unpack(">II", bytes(body[12:20]))
        unknown = duration == 0xFFFFFFFF
    return timescale, None if unknown or duration == 0 else duration


def _mehd(data, start, end):
    body = data[start:end]
    if len(body) >= 12 and body[0] == 1:
        return struct.unpack(">Q", bytes(body[4:12]))[0]
    if len(body) >= 8:
        return struct.unpack(">I", bytes(body[4:8]))[0]
    return None


def _tkhd(data, start, end):
    body = data[start:end]
    offset = 4 + (32 if body[:1] == b"\x01" else 20) + 8 + 2 + 2 + 2 + 2 + 36
    if len(body) < offset + 8:
        raise BoxError("short tkhd")
    width, height = struct.unpack(">II", bytes(body[offset:offset + 8]))
    return width / 65536, height / 65536


def _meta_location(data, start, end):
    """True when a QuickTime `meta` (keys + ilst) holds a non-blank location key value."""
    if end - start >= 8 and bytes(data[start + 4:start + 8]) != b"hdlr":
        start += 4   # ISO full-box meta carries version and flags first
    keys, values = {}, {}
    for kind, s, e in _children(data, start, end):
        if kind == b"keys" and e - s >= 8:
            count = struct.unpack(">I", bytes(data[s + 4:s + 8]))[0]
            offset = s + 8
            for index in range(1, count + 1):
                if offset + 8 > e:
                    break
                size = struct.unpack(">I", bytes(data[offset:offset + 4]))[0]
                if size < 8 or offset + size > e:
                    break
                keys[index] = bytes(data[offset + 8:offset + size]).decode("utf-8", "replace").lower()
                offset += size
        elif kind == b"ilst":
            for item, is_, ie in _children(data, s, e):
                index = struct.unpack(">I", item)[0]
                for dk, ds, de in _children(data, is_, ie):
                    if dk == b"data" and de - ds >= 8:
                        values[index] = bytes(data[ds + 8:de])
    return any(keys.get(index) in LOCATION_KEYS and not _blank(value) for index, value in values.items())


def parse_moov(data):
    """{"duration", "width", "height", "location_present"} from a `moov` box (with or without its header)."""
    data = memoryview(bytes(data or b""))
    if len(data) > MOOV_MAX:
        raise BoxError("moov over the read budget")
    out = {"duration": None, "width": None, "height": None, "location_present": False}
    if len(data) >= 8 and bytes(data[4:8]) == b"moov":
        _, header, size = _header(data, 0, len(data))
        start, end = header, min(size, len(data))
    else:
        start, end = 0, len(data)
    timescale, duration, fragment = None, None, None
    try:
        stack = [(start, end, b"moov")]
        while stack:
            s, e, parent = stack.pop(0)
            for kind, cs, ce in _children(data, s, e):
                if kind == b"mvhd" and parent == b"moov":
                    timescale, duration = _mvhd(data, cs, ce)
                elif kind == b"mehd":
                    fragment = _mehd(data, cs, ce)
                elif kind == b"tkhd" and out["width"] is None:
                    width, height = _tkhd(data, cs, ce)
                    if width and height:
                        out["width"], out["height"] = round(width), round(height)
                elif kind in LOCATION_ATOMS and parent == b"udta":
                    if not _blank(bytes(data[cs + 4:ce])):
                        out["location_present"] = True
                elif kind == b"meta":
                    if _meta_location(data, cs, ce):
                        out["location_present"] = True
                elif kind in CONTAINERS:
                    stack.append((cs, ce, kind))
    except (BoxError, struct.error, IndexError):
        pass   # keep whatever was read before the damage
    if timescale:
        ticks = duration if duration else fragment
        out["duration"] = round(ticks / timescale, 3) if ticks else None
    return out
