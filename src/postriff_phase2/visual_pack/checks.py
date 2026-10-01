"""Deterministic checks for the six-slide 1080×1350 carousel (PRD R-VIS-01/02).

Everything here is measured, never estimated: text is wrapped with the bundled font's own advances (CJK may break
between characters, Latin words stay whole, a word wider than the line is broken with a hyphen and reported), glyph
coverage comes from the font's cmap, overflow is the measured excess at the smallest allowed size (text is never
shrunk below a fixed minimum), and a rendered file is re-opened to prove its format, size and integrity.
"""
from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata

from ..coworker.creative import PLATFORM_SPECS
from . import fonts

FORMAT = "carousel_6_1080x1350"
SLIDES = 6
WIDTH, HEIGHT = 1080, 1350
ROLES = ("hook", "point", "point", "point", "point", "close")   # layout follows position, so slide 1 always works alone
MAX_CHARS = {"hook": 140, "point": 320, "close": 180}
CAPTION_MAX = 2200
ALT_MAX = 1000


def _safe_insets():
    """The strictest inset of every 1080×1350 carousel destination Rafii plans for (Instagram, LinkedIn, Threads), so
    the same files are safe wherever the person posts them."""
    specs = {platform: spec for (platform, fmt), spec in PLATFORM_SPECS.items() if fmt == "carousel" and spec["size"] == [WIDTH, HEIGHT]}

    def inset(side, length):
        return math.ceil(round(max(spec["safe"][side] for spec in specs.values()) * length, 6))
    return {"top": inset("top", HEIGHT), "bottom": inset("bottom", HEIGHT), "sides": inset("sides", WIDTH), "platforms": sorted(specs)}


SAFE = _safe_insets()
SAFE_BOX = (SAFE["sides"], SAFE["top"], WIDTH - SAFE["sides"], HEIGHT - SAFE["bottom"])   # x0, y0, x1, y1 (exclusive)

# Rafii's own monochrome language plus its one violet (web/src/styles/rafii.css); contrast is tested, not assumed.
PALETTES = {
    "rafii_light": {"label": "Light", "background": "#FCFCFC", "text": "#000000", "muted": "#626262", "accent": "#000000"},
    "rafii_dark": {"label": "Dark", "background": "#000000", "text": "#FFFFFF", "muted": "#A1A1A1", "accent": "#FFFFFF"},
    "rafii_violet": {"label": "Violet", "background": "#0D0C14", "text": "#F8F6FF", "muted": "#B9B2C9", "accent": "#B647EF"},
    "rafii_paper": {"label": "Paper", "background": "#F0F0F0", "text": "#000000", "muted": "#626262", "accent": "#7A30D7"},
}
DEFAULT_SETTINGS = {"palette": "rafii_light", "weight": "regular"}

# Typography per layout: start size, fixed minimum (never smaller), line height, step.
TYPE = {"hook": {"size": 88, "min": 64, "leading": 1.24}, "point": {"size": 72, "min": 44, "leading": 1.36},
        "close": {"size": 72, "min": 52, "leading": 1.3}}
STEP = 4
COUNTER_SIZE = 30

# Kinsoku: characters that may not begin a line, and ones that may not end one.
NO_START = set("、。，．・：；？！ー’”）〕］｝〉》」』】〙〗〟｠»‼⁇⁈⁉…‥％,.:;!?)]}%ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々〻゛゜ゝゞヽヾ")
NO_END = set("（〔［｛〈《「『【〘〖〝｟«‘“([{")
GLUE = set("—…‥")   # runs of these stay together (“——”, “……”)
_INVISIBLE = {0x200B, 0x200C, 0x200D, 0x2060, 0xFE0E, 0xFE0F, 0xFEFF}


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (0x2E80 <= code <= 0x2FDF or 0x3000 <= code <= 0x30FF or 0x3100 <= code <= 0x31FF or 0x3200 <= code <= 0x9FFF
            or 0xA960 <= code <= 0xA97F or 0xAC00 <= code <= 0xD7FF or 0xF900 <= code <= 0xFAFF or 0xFE30 <= code <= 0xFE4F
            or 0xFF00 <= code <= 0xFFEF or 0x20000 <= code <= 0x3FFFF)


def normalize_text(value, limit) -> str:
    """NFC, Unix newlines, tabs as spaces, no other control characters, at most one blank line in a row."""
    if not isinstance(value, str):
        raise ValueError("text must be a string")
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch) != "Cc")
    text = re.sub(r"[  ]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        raise ValueError(f"text longer than {limit} characters")
    return text


def missing_glyphs(text: str, weight: str) -> list[dict]:
    """Every distinct non-space character the font cannot draw, in order of first appearance."""
    seen, out = set(), []
    for ch in text:
        if ch in seen or ch == "\n" or ch == " ":
            continue
        seen.add(ch)
        if not fonts.covers(weight, ord(ch)):
            name = unicodedata.name(ch, "")
            out.append({"char": ch, "codePoint": f"U+{ord(ch):04X}", "name": name.title() if name else None,
                        "invisible": ord(ch) in _INVISIBLE or unicodedata.category(ch) in ("Cf", "Mn")})
    return out


# --- wrapping ------------------------------------------------------------------------------------------------

def _atoms(paragraph: str) -> list[tuple[str, bool]]:
    """Unbreakable pieces of one paragraph with whether a space separated each from the previous one. CJK characters
    (and dash/ellipsis runs) are pieces of their own; Latin words, numbers and their punctuation stay whole; kinsoku
    then glues closing punctuation to what precedes it and opening punctuation to what follows."""
    raw, word, gap = [], "", False
    for ch in paragraph:
        if ch.isspace():
            if word:
                raw.append((word, gap))
                word = ""
            gap = True
            continue
        if is_cjk(ch) or ch in GLUE:
            if word:
                raw.append((word, gap))
                word, gap = "", False
            raw.append((ch, gap))
            gap = False
            continue
        word += ch
        if ch == "-" and len(word) > 1:   # a hyphenated word may break after its own hyphen
            raw.append((word, gap))
            word, gap = "", False
    if word:
        raw.append((word, gap))
    atoms: list[list] = []
    for text, spaced in raw:
        # A dash or ellipsis run stays with what it follows (a line never starts with an orphaned “——”).
        if atoms and not spaced and (text[0] in NO_START or text[0] in GLUE or atoms[-1][0][-1] in NO_END):
            atoms[-1][0] += text
        else:
            atoms.append([text, spaced])
    return [(text, spaced) for text, spaced in atoms]


def _split_long(atom: str, font, width: float):
    """A piece wider than the line: as many characters as fit (with a hyphen between two Latin letters), then the rest."""
    for cut in range(len(atom) - 1, 0, -1):
        head, tail = atom[:cut], atom[cut:]
        hyphen = head[-1].isalnum() and tail[0].isalnum() and not is_cjk(head[-1]) and not is_cjk(tail[0])
        if font.getlength(head + ("-" if hyphen else "")) <= width:
            return head + ("-" if hyphen else ""), tail, hyphen
    return atom[:1], atom[1:], False


def wrap(text: str, font, width: float):
    """Greedy measured wrapping. Returns (lines, broken words)."""
    lines, broken = [], []
    for paragraph in text.split("\n"):
        line = ""
        for atom, spaced in _atoms(paragraph):
            candidate = line + (" " if spaced and line else "") + atom
            if font.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            rest = atom
            while font.getlength(rest) > width:
                head, rest, hyphen = _split_long(rest, font, width)
                lines.append(head)
                if atom not in broken:
                    broken.append(atom)
            line = rest
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return lines, broken


def block_height(font, count: int, leading: float) -> int:
    ascent, descent = font.getmetrics()
    return 0 if count == 0 else (count - 1) * line_step(font, leading) + ascent + descent


def line_step(font, leading: float) -> int:
    return int(round(font.size * leading))


def fit(text: str, role: str, weight: str, box_width: int, box_height: int, *, max_size=None):
    """The largest size from the role's start size down to its fixed minimum at which the measured block fits.
    Returns a layout, or a `needs_shorter_copy` finding with the measured excess at the minimum size."""
    spec = TYPE[role]
    start = min(spec["size"], max_size or spec["size"])
    size = start
    while True:
        font = fonts.font(weight, size)
        lines, broken = wrap(text, font, box_width)
        height = block_height(font, len(lines), spec["leading"])
        widest = max((font.getlength(line) for line in lines), default=0)
        if height <= box_height and widest <= box_width:
            return {"fits": True, "size": size, "lines": lines, "height": height, "broken": broken, "leading": spec["leading"]}
        if size - STEP < spec["min"]:
            break
        size -= STEP
    step = line_step(font, spec["leading"])
    excess_lines = max(0, -(-(height - box_height) // step)) if height > box_height else 0
    chars = len(text.replace("\n", ""))
    keep = int(chars * box_height / height) if height else chars
    return {"fits": False, "size": size, "lines": lines, "height": height, "broken": broken, "leading": spec["leading"],
            "finding": {"code": "needs_shorter_copy", "excessPx": max(0, height - box_height), "excessLines": excess_lines,
                        "minimumSize": spec["min"], "suggestedMaxChars": max(1, keep - 2)}}


# --- palettes ---------------------------------------------------------------------------------------------------

def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def settings(value) -> dict:
    """Pack-level visual settings: one of the fixed palettes and one of the two bundled weights."""
    value = value if isinstance(value, dict) else {}
    out = dict(DEFAULT_SETTINGS)
    if "palette" in value:
        if value["palette"] not in PALETTES:
            raise ValueError("unknown palette")
        out["palette"] = value["palette"]
    if "weight" in value:
        if value["weight"] not in fonts.WEIGHTS:
            raise ValueError("unknown weight")
        out["weight"] = value["weight"]
    return out


# --- files ------------------------------------------------------------------------------------------------------

def verify_png(raw: bytes) -> dict:
    """Re-open the bytes: a complete PNG of exactly 1080×1350 RGB. Returns its hashes; raises ValueError otherwise."""
    from PIL import Image
    if not isinstance(raw, bytes) or not raw.startswith(b"\x89PNG\r\n\x1a\n") or not raw.endswith(b"IEND\xaeB`\x82"):
        raise ValueError("not a complete PNG")
    with Image.open(io.BytesIO(raw)) as probe:
        probe.verify()
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if image.format != "PNG" or image.size != (WIDTH, HEIGHT) or image.mode != "RGB":
            raise ValueError(f"unexpected image {image.format} {image.size} {image.mode}")
        pixels = hashlib.sha256(image.tobytes()).hexdigest()
    return {"width": WIDTH, "height": HEIGHT, "mime": "image/png", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "pixelSha256": pixels}


def inside_safe_area(box) -> bool:
    if box is None:
        return True
    x0, y0, x1, y1 = box
    return x0 >= SAFE_BOX[0] and y0 >= SAFE_BOX[1] and x1 <= SAFE_BOX[2] and y1 <= SAFE_BOX[3]
