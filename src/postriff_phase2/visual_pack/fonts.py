"""The two bundled Noto Sans TC weights (SIL OFL 1.1, see fonts/OFL.txt and fonts/fonts.json).

A font is opened from its path, never copied into Python memory per size, with Pillow's BASIC layout so wrapping and
pixels do not depend on whether libraqm happens to be installed. Coverage comes from the font's own `cmap` (format 12
preferred, format 4 otherwise), parsed here: a character the cmap does not map would render as `.notdef` (tofu), so the
checks report it instead of drawing it.
"""
from __future__ import annotations

import bisect
import functools
import hashlib
import json
import struct
from pathlib import Path

DIRECTORY = Path(__file__).with_name("fonts")
WEIGHTS = ("regular", "bold")


@functools.lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((DIRECTORY / "fonts.json").read_text(encoding="utf-8"))


def _entry(weight: str) -> dict:
    if weight not in WEIGHTS:
        raise ValueError(f"unknown weight {weight!r}")
    return next(item for item in manifest()["fonts"] if item["weight"] == weight)


@functools.lru_cache(maxsize=2)
def path(weight: str) -> Path:
    """The font file, after checking it is byte-for-byte the recorded one (a swapped file changes every hash)."""
    entry = _entry(weight)
    file = DIRECTORY / entry["file"]
    sha = hashlib.sha256()
    with file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    if sha.hexdigest() != entry["sha256"]:
        raise RuntimeError(f"bundled font {entry['file']} does not match fonts.json")
    return file


def sha256(weight: str) -> str:
    return _entry(weight)["sha256"]


@functools.lru_cache(maxsize=64)
def font(weight: str, size: int):
    from PIL import ImageFont
    if type(size) is not int or not 8 <= size <= 400:
        raise ValueError("font size out of range")
    return ImageFont.truetype(str(path(weight)), size, layout_engine=ImageFont.Layout.BASIC)


def _tables(handle) -> dict:
    head = handle.read(12)
    if head[:4] not in (b"OTTO", b"\x00\x01\x00\x00", b"true"):
        raise ValueError("not an OpenType font")
    count = struct.unpack(">H", head[4:6])[0]
    records = handle.read(16 * count)
    return {records[i:i + 4].decode("latin-1"): struct.unpack(">II", records[i + 8:i + 16]) for i in range(0, 16 * count, 16)}


def _ranges(file: Path) -> list[tuple[int, int]]:
    """Mapped code point ranges [(start, end)] from the best Unicode cmap subtable."""
    with file.open("rb") as handle:
        offset, length = _tables(handle)["cmap"]
        handle.seek(offset)
        table = handle.read(length)
    count = struct.unpack(">H", table[2:4])[0]
    subtables = {}
    for i in range(count):
        platform, encoding, sub = struct.unpack(">HHI", table[4 + 8 * i:12 + 8 * i])
        subtables[(platform, encoding)] = sub
    for key in ((3, 10), (0, 6), (0, 4)):
        if key in subtables and struct.unpack(">H", table[subtables[key]:subtables[key] + 2])[0] == 12:
            start = subtables[key]
            groups = struct.unpack(">I", table[start + 12:start + 16])[0]
            ranges = []
            for g in range(groups):
                low, high, glyph = struct.unpack(">III", table[start + 16 + 12 * g:start + 28 + 12 * g])
                if glyph == 0:
                    low += 1   # a group starting at glyph 0 maps its first code point to .notdef
                if low <= high:
                    ranges.append((low, high))
            return _merged(ranges)
    for key in ((3, 1), (0, 3)):
        if key in subtables and struct.unpack(">H", table[subtables[key]:subtables[key] + 2])[0] == 4:
            return _merged(_format4(table, subtables[key]))
    raise ValueError("font has no Unicode cmap")


def _format4(table: bytes, start: int) -> list[tuple[int, int]]:
    segments = struct.unpack(">H", table[start + 6:start + 8])[0] // 2
    ends_at = start + 14
    starts_at = ends_at + 2 * segments + 2
    deltas_at = starts_at + 2 * segments
    offsets_at = deltas_at + 2 * segments
    ranges = []
    for s in range(segments):
        end = struct.unpack(">H", table[ends_at + 2 * s:ends_at + 2 * s + 2])[0]
        first = struct.unpack(">H", table[starts_at + 2 * s:starts_at + 2 * s + 2])[0]
        delta = struct.unpack(">h", table[deltas_at + 2 * s:deltas_at + 2 * s + 2])[0]
        range_offset = struct.unpack(">H", table[offsets_at + 2 * s:offsets_at + 2 * s + 2])[0]
        for code in range(first, end + 1):
            if code == 0xFFFF:
                continue
            if range_offset == 0:
                glyph = (code + delta) & 0xFFFF
            else:
                at = offsets_at + 2 * s + range_offset + 2 * (code - first)
                glyph = struct.unpack(">H", table[at:at + 2])[0]
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            if glyph:
                ranges.append((code, code))
    return ranges


def _merged(ranges):
    out = []
    for low, high in sorted(ranges):
        if out and low <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], high))
        else:
            out.append((low, high))
    return out


@functools.lru_cache(maxsize=2)
def _coverage(weight: str):
    ranges = _ranges(path(weight))
    return [low for low, _ in ranges], [high for _, high in ranges]


def covers(weight: str, code_point: int) -> bool:
    lows, highs = _coverage(weight)
    at = bisect.bisect_right(lows, code_point) - 1
    return at >= 0 and code_point <= highs[at]


def coverage_count(weight: str) -> int:
    lows, highs = _coverage(weight)
    return sum(high - low + 1 for low, high in zip(lows, highs))
