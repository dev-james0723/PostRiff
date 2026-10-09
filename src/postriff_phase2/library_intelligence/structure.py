"""Structural document extraction with real locators (engineering spec §4, §5 Locator, §7 Documents; T03, A013–A015).

PDF pages become `page` segments ({kind:'page', page, section?}) with the outline title as section; pages with no
reliable text layer (image-only or garbled) are listed in `media.ocrNeededPages` and are never given invented text.
DOCX paragraphs and table rows become `text` segments whose offsets point into the extracted text; Word has no
trustworthy pagination, so no page number is ever produced for Office files. XLSX rows become `sheet` segments with
the workbook's real sheet names and cell references; formulas are never evaluated (cached values only). PPTX slides
follow the presentation's `sldIdLst` order, not file names. Plain text, Markdown, HTML, JSON and CSV become
paragraph-bounded `text` segments.

Complex formats run in a child process (`extract_isolated`) with CPU, memory and file-size limits, a scrubbed
environment (no credentials) and Python sockets disabled, mirroring `library_extract.extract_isolated`. Office
packages pass the same archive guards as `library_extract._office` (2,000 parts, 100 MiB expanded, 100x ratio above
1 MiB, no traversal, no macro or executable parts) plus macro-enabled content types and XML entity declarations.
"""
from __future__ import annotations

import base64
import csv
import html
import io
import json
import os
import posixpath
import re
import subprocess
import sys
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from postriff_alpha.domain import AlphaError

from .. import library_extract

VERSION = "structure-1"
SUPPORTED = ("pdf", "docx", "xlsx", "pptx", "txt", "md", "markdown", "html", "htm", "json", "csv")
INLINE = ("txt", "md", "markdown", "html", "htm", "json", "csv")
FAMILY = {"txt": "text", "md": "text", "markdown": "text", "htm": "html"}
MAX_FILE_BYTES = library_extract.MAX_FILE_BYTES
MAX_TEXT = library_extract.MAX_TEXT
MAX_PAGES = 300
MAX_PART = 50 * 1024 * 1024
MAX_ROWS = 10000
MAX_CELLS = 200
SEGMENT_CHARS = 2000
MAX_OCR_PAGES = 20
CHILD_CPU_SECONDS, CHILD_MEMORY, CHILD_TIMEOUT = 20, 768 * 1024 * 1024, 40
SRC = str(Path(__file__).resolve().parents[2])

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CELL = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")


def unsafe(message: str):
    raise AlphaError(message, 422, code="library_unsafe_document")


def unreadable(message: str):
    raise AlphaError(message, 422, code="library_unreadable_document")


# --- text quality ------------------------------------------------------------------------------------------------------
def text_quality(text: str) -> str:
    """'empty', 'ok' or 'garbled'. Garbled text layers (unmapped glyph codes, private-use or replacement characters,
    `(cid:N)` runs) are never accepted silently as the page's content."""
    visible = [ch for ch in str(text or "") if not ch.isspace()]
    if len(visible) < 3:
        return "empty"
    if len(re.findall(r"\(cid:\d+\)", text)) >= 3:
        return "garbled"
    bad = sum(1 for ch in visible if unicodedata.category(ch) in ("Cc", "Co", "Cn", "Cs") or ch == "�")
    letters = sum(1 for ch in visible if ch.isalnum())
    if bad / len(visible) > 0.1 or letters / len(visible) < 0.3:
        return "garbled"
    return "ok"


def _spans(text: str, limit: int = SEGMENT_CHARS) -> list[tuple[int, int]]:
    """Split `text` into trimmed spans of at most `limit` characters at paragraph, line or sentence boundaries."""
    spans, start, n = [], 0, len(text)
    while start < n:
        end = min(n, start + limit)
        if end < n:
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind("\n"))
            if cut < limit // 3:
                cut = max(window.rfind(". "), window.rfind("。"), window.rfind("! "), window.rfind("? "), window.rfind(" "))
            if cut >= limit // 3:
                end = start + cut + 1
        a, b = start, end
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            spans.append((a, b))
        start = end
    return spans


def _paragraph_segments(text: str, kind: str = "text") -> list[dict]:
    """Paragraphs separated by blank lines; long paragraphs split further. Offsets index into `text`."""
    out = []
    for match in re.finditer(r"(?:[^\n]|\n(?![ \t]*\n))+", text):
        block_start = match.start()
        for a, b in _spans(match.group(0)):
            out.append({"kind": kind, "text": text[block_start + a:block_start + b],
                        "locator": {"kind": "text", "start": block_start + a, "end": block_start + b}})
    return out


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


# --- plain formats --------------------------------------------------------------------------------------------------
class _HTML(HTMLParser):
    SKIP = ("script", "style", "noscript", "template", "iframe", "object", "embed", "svg", "math")
    BLOCK = ("p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section", "article", "blockquote", "pre",
             "header", "footer", "main", "aside", "nav", "figure", "figcaption", "dd", "dt", "dl")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.out = 0, []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP:
            self.skip += 1
        elif not self.skip and tag in self.BLOCK:
            self.out.append("\n\n")
        elif not self.skip and tag == "br":
            self.out.append("\n")
        elif not self.skip and tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif not self.skip and tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _clean_lines(text: str) -> str:
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip(" |") for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _decode(raw: bytes, label: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        unreadable(f"This {label} file must be UTF-8.")


def _plain(raw: bytes, ext: str) -> dict:
    if ext in ("txt", "md", "markdown"):
        text = _normalize_text(_decode(raw, "text"))
    elif ext in ("html", "htm"):
        parser = _HTML()
        try:
            parser.feed(_decode(raw, "HTML"))
            parser.close()
        except (ValueError, AssertionError):
            unreadable("This HTML file could not be read.")
        text = _clean_lines(html.unescape("".join(parser.out)))
    elif ext == "json":
        try:
            value = json.loads(_decode(raw, "JSON"))
        except (ValueError, RecursionError):
            unreadable("This JSON file is invalid.")
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        rows = []
        try:
            for n, row in enumerate(csv.reader(io.StringIO(_decode(raw, "CSV")))):
                if n >= MAX_ROWS:
                    break
                rows.append(" | ".join(cell[:2000] for cell in row[:MAX_CELLS]))
        except csv.Error:
            unreadable("This CSV file is invalid.")
        text = "\n".join(rows)
    truncated = len(text) > MAX_TEXT
    text = text[:MAX_TEXT]
    return _result(_paragraph_segments(text), {"textLength": len(text)}, text=text, truncated=truncated)


def _result(segments, media, *, text=None, truncated=False, needed=None, detail=None) -> dict:
    notes = []
    if truncated:
        notes.append(f"Only the first {MAX_TEXT:,} characters were indexed.")
    if needed:
        notes.append(f"Page{'s' if len(needed) > 1 else ''} {', '.join(map(str, needed))} "
                     f"{'have' if len(needed) > 1 else 'has'} no reliable text layer and need{'' if len(needed) > 1 else 's'} OCR.")
    if detail:
        notes.append(detail)
    if not segments and not needed:
        notes.append("No text was found in this file.")
    return {"state": "partial" if truncated or needed else "ready", "segments": segments, "media": media, "text": text,
            "detail": " ".join(notes) or None}


# --- PDF -----------------------------------------------------------------------------------------------------------------
def _resources_have_images(resources, depth=0) -> bool:
    try:
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        xobjects = resources.get("/XObject") if resources else None
        xobjects = xobjects.get_object() if xobjects is not None else {}
        for name in list(xobjects)[:200]:
            obj = xobjects[name].get_object()
            subtype = obj.get("/Subtype")
            if subtype == "/Image":
                return True
            if subtype == "/Form" and depth < 3 and _resources_have_images(obj.get("/Resources"), depth + 1):
                return True
    except Exception:  # noqa: BLE001 - damaged resource dictionaries mean "no detectable image"
        return False
    return False


def _outline_sections(reader, count: int) -> dict:
    starts, seen = [], [0]

    def walk(items, depth):
        for item in items:
            if seen[0] > 500 or depth > 8:
                return
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            seen[0] += 1
            try:
                page = reader.get_destination_page_number(item)
                title = " ".join(str(item.title or "").split())[:200]
            except Exception:  # noqa: BLE001
                continue
            if title and isinstance(page, int) and 0 <= page < count:
                starts.append((page, depth, seen[0], title))

    try:
        walk(reader.outline, 0)
    except Exception:  # noqa: BLE001 - a broken outline only loses section labels
        return {}
    starts.sort()
    sections, current, i = {}, None, 0
    for page in range(count):
        while i < len(starts) and starts[i][0] <= page:
            current = starts[i][3]
            i += 1
        if current:
            sections[page] = current
    return sections


def _pdf_reader(raw: bytes):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            unreadable("Password-protected PDFs are not supported.")
        count = len(reader.pages)
    except AlphaError:
        raise
    except Exception:  # noqa: BLE001 - every parser failure is the same honest state
        unreadable("This PDF could not be read safely.")
    if count > MAX_PAGES:
        unreadable(f"This PDF has more than {MAX_PAGES} pages.")
    return reader, count


def _pdf(raw: bytes) -> dict:
    reader, count = _pdf_reader(raw)
    sections = _outline_sections(reader, count)
    segments, needed, reasons, total, truncated = [], [], {}, 0, False
    for index in range(count):
        number = index + 1
        page = reader.pages[index]
        try:
            text = _normalize_text(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            text = ""
        quality = text_quality(text)
        locator = {"kind": "page", "page": number, **({"section": sections[index]} if index in sections else {})}
        if quality == "ok":
            spans = _spans(text)
            for a, b in spans:
                loc = dict(locator) if len(spans) == 1 else {**locator, "textStart": a, "textEnd": b}
                segments.append({"kind": "page", "text": text[a:b], "locator": loc})
            total += len(text)
        elif quality == "garbled":
            needed.append(number)
            reasons[str(number)] = "garbled"
            readable = re.sub(r"[^\w\s.,;:!?'\"()\-–—]", " ", text)
            if len(re.findall(r"\w{3,}", readable)) >= 3:
                kept = " ".join(readable.split())[:SEGMENT_CHARS]
                segments.append({"kind": "page", "text": kept, "locator": locator, "uncertainty": "Text layer looks garbled; OCR suggested"})
        elif _resources_have_images(page.get("/Resources")):
            needed.append(number)
            reasons[str(number)] = "image_only"
        if total >= MAX_TEXT:
            truncated = number < count
            break
    media = {"pages": count, "ocrNeededPages": needed, "ocrReasons": reasons}
    return _result(segments, media, truncated=truncated, needed=needed)


def _jpeg(image, max_edge: int = 1600) -> bytes:
    from PIL import Image
    image = image.convert("L") if image.mode in ("1", "L", "LA", "I", "I;16", "F") else image.convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def pdf_page_images(raw: bytes, pages: list[int], max_edge: int = 1600) -> dict:
    """{page_number: jpeg_bytes} for the largest embedded image on each requested page (scanned pages are one image).
    Pages without an embedded image are absent: they would need a page renderer, which is not available here."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 60_000_000
    reader, count = _pdf_reader(raw)
    out = {}
    for number in list(dict.fromkeys(p for p in pages if type(p) is int))[:MAX_OCR_PAGES]:
        if not 1 <= number <= count:
            continue
        best = None
        try:
            for n, image in enumerate(reader.pages[number - 1].images):
                if n >= 20:
                    break
                pil = image.image
                if pil is not None and (best is None or pil.width * pil.height > best.width * best.height):
                    best = pil
        except Exception:  # noqa: BLE001 - an undecodable image leaves the page unresolved
            best = None
        if best is not None:
            out[number] = _jpeg(best, max_edge)
    return out


# --- OOXML -----------------------------------------------------------------------------------------------------------------
def open_ooxml(raw: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError, ValueError):
        unreadable("This Office document is damaged or unsupported.")
    infos = archive.infolist()
    if len(infos) > 2000:
        archive.close()
        unsafe("This Office document contains too many parts.")
    total = 0
    for info in infos:
        name = info.filename
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or "\\" in name or "\x00" in name:
            archive.close()
            unsafe("This Office document contains an unsafe path.")
        total += info.file_size
        if total > 100 * 1024 * 1024 or (info.file_size > 1024 * 1024 and info.file_size > max(1, info.compress_size) * 100):
            archive.close()
            unsafe("This Office document expands beyond the safe limit.")
        if name.lower().endswith(("vbaproject.bin", "vbadata.xml", ".exe", ".js", ".vbs", ".dll", ".bat", ".cmd", ".ps1", ".scr")):
            archive.close()
            unsafe("Macro or executable Office content is not accepted.")
    types = _read(archive, "[Content_Types].xml", required=False) or b""
    if re.search(rb"(?i)vbaproject|macroenabled|vnd\.ms-office\.activex", types):
        archive.close()
        unsafe("Macro-enabled Office content is not accepted.")
    return archive


def _read(archive, name, *, required=True):
    try:
        info = archive.getinfo(name)
    except KeyError:
        if required:
            unreadable("This Office document is missing a required part.")
        return None
    with archive.open(info) as handle:
        data = handle.read(MAX_PART + 1)
    if len(data) > MAX_PART:
        unsafe("This Office document part is too large.")
    return data


def _xml(archive, name, *, required=True):
    data = _read(archive, name, required=required)
    if data is None:
        return None
    # OOXML parts are UTF-8. Anything else (UTF-16/32 BOMs, NUL-interleaved text) could hide a DOCTYPE from the byte check.
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or data[:4] in (b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00") or b"\x00" in data[:4096]:
        unsafe("Office document parts must be UTF-8 XML.")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.I) or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", data.decode("utf-8", "ignore"), re.I):
        unsafe("Office documents with XML entity declarations are not accepted.")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        unreadable("This Office document is damaged.")


def _rels(archive, rels_name: str, base: str) -> dict:
    root = _xml(archive, rels_name, required=False)
    out = {}
    if root is None:
        return out
    for rel in root.iter(f"{PKG}Relationship"):
        if rel.get("TargetMode") == "External":
            continue  # never fetched
        target = rel.get("Target") or ""
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
        if path.startswith("..") or path.startswith("/"):
            continue
        out[rel.get("Id")] = path
    return out


def _run_text(paragraph) -> str:
    out = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == f"{W}t" and node.text:
            out.append(node.text)
        elif tag == f"{W}tab":
            out.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
    return "".join(out)


def _docx(archive) -> dict:
    root = _xml(archive, "word/document.xml")
    body = root.find(f"{W}body")
    lines = []

    def visit(element):
        for child in list(element):
            if child.tag == f"{W}p":
                lines.append(_run_text(child).strip())
            elif child.tag == f"{W}tbl":
                for row in child.findall(f"{W}tr"):
                    cells = [" ".join(_run_text(p).strip() for p in cell.iter(f"{W}p")).strip() for cell in row.findall(f"{W}tc")]
                    lines.append(" | ".join(cells).strip(" |"))
            elif child.tag in (f"{W}sdt", f"{W}sdtContent", f"{W}customXml", f"{W}smartTag"):
                visit(child)
            if sum(len(x) for x in lines) > MAX_TEXT:
                return

    if body is not None:
        visit(body)
    text, segments, offset = "", [], 0
    for n, line in enumerate(lines):
        if n:
            offset += 1
        for a, b in _spans(line) if line else []:
            segments.append({"kind": "text", "text": line[a:b], "locator": {"kind": "text", "start": offset + a, "end": offset + b}})
        offset += len(line)
    text = "\n".join(lines)
    truncated = len(text) > MAX_TEXT
    if truncated:
        text = text[:MAX_TEXT]
        segments = [s for s in segments if s["locator"]["end"] <= MAX_TEXT]
    return _result(segments, {"textLength": len(text)}, text=text, truncated=truncated)


def _column(letters: str) -> int:
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value


def _letters(number: int) -> str:
    out = ""
    while number:
        number, rem = divmod(number - 1, 26)
        out = chr(65 + rem) + out
    return out


def _cell_value(cell, shared) -> str:
    kind = cell.get("t")
    v = cell.find(f"{S}v")
    raw = v.text if v is not None and v.text is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "inlineStr":
        node = cell.find(f"{S}is")
        return "".join(t.text or "" for t in node.iter(f"{S}t")) if node is not None else ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE" if raw == "0" else raw
    return raw  # n, str (cached formula result), e, d — formulas themselves are never read or evaluated


def _xlsx(archive) -> dict:
    workbook = _xml(archive, "xl/workbook.xml")
    rels = _rels(archive, "xl/_rels/workbook.xml.rels", "xl")
    shared = []
    strings = _xml(archive, "xl/sharedStrings.xml", required=False)
    if strings is not None:
        for item in strings.iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in item.iter(f"{S}t")))
            if len(shared) > 1_000_000:
                unsafe("This workbook has too many shared strings.")
    names, segments, rows_seen, size, truncated = [], [], 0, 0, False
    for sheet in workbook.iter(f"{S}sheet"):
        name = (sheet.get("name") or "").strip()[:120]
        path = rels.get(sheet.get(f"{R}id"))
        if not name or not path:
            continue
        names.append(name)
        root = _xml(archive, path, required=False)
        if root is None:
            continue
        row_number = 0
        for row in root.iter(f"{S}row"):
            try:
                row_number = int(row.get("r") or row_number + 1)
            except ValueError:
                row_number += 1
            column = 0
            refs, values = [], []
            for cell in row.findall(f"{S}c")[:MAX_CELLS]:
                match = CELL.match(cell.get("r") or "")
                if match:
                    column = _column(match.group(1))
                    ref = match.group(0)
                else:
                    column += 1
                    ref = f"{_letters(column)}{row_number}"
                    if not CELL.match(ref):
                        continue
                value = " ".join(_cell_value(cell, shared).split())[:2000]
                if value:
                    refs.append(ref)
                    values.append(value)
            if not values:
                continue
            rows_seen += 1
            if rows_seen > MAX_ROWS or size > MAX_TEXT:
                truncated = True
                break
            text = " | ".join(values)[:SEGMENT_CHARS * 2]
            size += len(text)
            cell_range = refs[0] if len(refs) == 1 else f"{refs[0]}:{refs[-1]}"
            segments.append({"kind": "sheet", "text": text, "locator": {"kind": "sheet", "sheetName": name, "cellRange": cell_range}})
        if truncated:
            break
    return _result(segments, {"sheets": len(names), "sheetNames": names[:50]}, truncated=truncated)


def _pptx(archive) -> dict:
    presentation = _xml(archive, "ppt/presentation.xml")
    rels = _rels(archive, "ppt/_rels/presentation.xml.rels", "ppt")
    order = [rels.get(slide.get(f"{R}id")) for slide in presentation.iter(f"{P}sldId")]
    segments, size = [], 0
    for number, path in enumerate(order, 1):
        root = _xml(archive, path, required=False) if path else None
        if root is None:
            continue
        paragraphs = ["".join(t.text or "" for t in p.iter(f"{A}t")).strip() for p in root.iter(f"{A}p")]
        text = "\n".join(x for x in paragraphs if x)[:SEGMENT_CHARS * 4]
        if text:
            size += len(text)
            segments.append({"kind": "slide", "text": text, "locator": {"kind": "slide", "slide": number}})
        if size > MAX_TEXT:
            return _result(segments, {"slides": len(order)}, truncated=True)
    return _result(segments, {"slides": len(order)})


def extract_structure(raw: bytes, ext: str) -> dict:
    """Pure structural extraction (run it through `extract_isolated` for untrusted complex files)."""
    if not isinstance(raw, (bytes, bytearray)) or not raw or len(raw) > MAX_FILE_BYTES:
        unreadable("The file is empty or too large.")
    ext = str(ext or "").lower()
    if ext not in SUPPORTED:
        return {"state": "unsupported", "segments": [], "media": {}, "text": None, "detail": "This file type has no structural extractor."}
    if ext in INLINE:
        return _plain(bytes(raw), ext)
    if ext == "pdf":
        return _pdf(bytes(raw))
    archive = open_ooxml(bytes(raw))
    try:
        return {"docx": _docx, "xlsx": _xlsx, "pptx": _pptx}[ext](archive)
    finally:
        archive.close()


def extractor_name(ext: str) -> str:
    ext = str(ext or "").lower()
    return "structure-" + FAMILY.get(ext, ext)


def failed(error: AlphaError) -> dict:
    code = {"library_unsafe_document": "rejected_unsafe", "library_unreadable_document": "unreadable"}.get(getattr(error, "code", None), "unreadable")
    return {"state": "failed", "segments": [], "annotations": [], "embeddings": [], "media": {}, "provider": None, "errorCode": code,
            "detail": str(error)[:300], "retryable": False, "extractor": None, "extractorVersion": VERSION, "replaceFields": []}


def _outcome(result: dict, ext: str) -> dict:
    return {"state": result["state"], "segments": result["segments"], "annotations": [], "embeddings": [], "media": result["media"], "provider": None,
            "errorCode": None, "detail": result.get("detail"), "retryable": False, "extractor": extractor_name(ext), "extractorVersion": VERSION,
            "replaceFields": []}


# --- sandboxed child ---------------------------------------------------------------------------------------------------------
def _child_env() -> dict:
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": SRC, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0"}


def _run_child(args: list[str], raw: bytes, timeout: int = CHILD_TIMEOUT) -> dict:
    try:
        result = subprocess.run([sys.executable, "-s", "-m", "postriff_phase2.library_intelligence.structure", *args], input=raw,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=_child_env(), cwd=SRC, check=False)
    except subprocess.TimeoutExpired:
        raise AlphaError("This document exceeded the safe extraction time.", 422, code="library_limits_exceeded") from None
    if result.returncode != 0 or len(result.stdout) > 12 * MAX_TEXT:
        raise AlphaError("This document exceeded safe extraction limits or could not be read.", 422, code="library_limits_exceeded")
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise AlphaError("This document could not be read safely.", 422, code="library_unreadable_document") from None
    if data.get("error"):
        raise AlphaError(str(data["error"])[:300], 422, code=str(data.get("code") or "library_unreadable_document"))
    return data


def extract_isolated(raw: bytes, ext: str) -> dict:
    """Outcome-shaped result of `extract_structure` run in the sandboxed child. Refusals are honest failures."""
    ext = str(ext or "").lower()
    if ext not in SUPPORTED:
        return {**_outcome({"state": "unsupported", "segments": [], "media": {}, "detail": "This file type has no structural extractor."}, ext),
                "extractor": None}
    try:
        data = _run_child([ext], raw)
    except AlphaError as error:
        out = failed(error)
        if error.code == "library_limits_exceeded":
            out["errorCode"] = "limits_exceeded"
        return out
    return _outcome(data, ext)


def page_images(raw: bytes, pages: list[int]) -> dict:
    """Embedded page images for OCR, decoded in the sandboxed child. {page: jpeg bytes}."""
    data = _run_child(["--pdf-images", json.dumps([p for p in pages if type(p) is int][:MAX_OCR_PAGES])], raw)
    return {int(k): base64.b64decode(v) for k, v in (data.get("images") or {}).items()}


def network_selftest() -> dict:
    """Run the sandbox and report which protections took effect (acceptance evidence for A015)."""
    return _run_child(["--selftest"], b"selftest")


def _sandbox() -> dict:
    applied = {}
    try:
        import resource
        for name, value in (("cpu", CHILD_CPU_SECONDS), ("memory", CHILD_MEMORY), ("fileSize", 0)):
            limit = {"cpu": resource.RLIMIT_CPU, "memory": resource.RLIMIT_AS, "fileSize": resource.RLIMIT_FSIZE}[name]
            try:
                resource.setrlimit(limit, (value, value))
                applied[name] = True
            except (ValueError, OSError):
                applied[name] = False
        if not applied.get("memory"):
            try:
                resource.setrlimit(resource.RLIMIT_DATA, (CHILD_MEMORY, CHILD_MEMORY))
                applied["memory"] = True
            except (ValueError, OSError, AttributeError):
                pass
    except ImportError:
        pass
    import socket

    def blocked(*_args, **_kwargs):
        raise OSError("network access is disabled in the extraction sandbox")

    for name in ("socket", "create_connection", "getaddrinfo", "socketpair", "fromfd", "create_server"):
        if hasattr(socket, name):
            setattr(socket, name, blocked)
    return applied


def _child_main(argv: list[str]) -> dict:
    applied = _sandbox()
    raw = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
    mode = argv[0] if argv else ""
    if mode == "--selftest":
        import resource
        import socket
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=1)
            blocked = False
        except OSError as error:
            blocked = "disabled" in str(error)
        return {"socketBlocked": blocked, "cpuLimited": resource.getrlimit(resource.RLIMIT_CPU)[0] == CHILD_CPU_SECONDS,
                "memoryLimited": bool(applied.get("memory")), "fileSizeLimited": bool(applied.get("fileSize")), "environment": sorted(os.environ)}
    if mode == "--pdf-images":
        pages = json.loads(argv[1]) if len(argv) > 1 else []
        images = pdf_page_images(raw, pages)
        return {"images": {str(k): base64.b64encode(v).decode() for k, v in images.items()}}
    return extract_structure(raw, mode)




# --- processor -------------------------------------------------------------------------------------------------------------
def _applies(version: dict) -> bool:
    return version.get("kind") == "document" and str(version.get("extension") or "").lower() in SUPPORTED


def _with_languages(result: dict) -> dict:
    from .segments import detect_language
    for item in result["segments"]:
        item.setdefault("language", detect_language(item["text"])["language"])
    return result


def extract_raw(version: dict, raw: bytes) -> dict:
    """Outcome for one version's bytes: inline formats in-process (as library_assets does), complex ones sandboxed."""
    ext = str(version.get("extension") or "").lower()
    if not _applies(version):
        from .segments import outcome
        return outcome("unsupported", error="not_applicable", detail="This file type has no structural extractor.")
    if ext in INLINE:
        try:
            return _with_languages(_outcome(extract_structure(raw, ext), ext))
        except AlphaError as error:
            return failed(error)
    return _with_languages(extract_isolated(raw, ext))


def _run(job) -> dict:
    from .segments import job_attr, job_raw
    return extract_raw(job_attr(job, "version"), job_raw(job))


PROCESSOR = {"name": "library.structure", "capability": "extract", "version": VERSION, "location": "local", "category": "extract",
             "applies": _applies, "estimate": lambda job: None, "run": _run}
PROCESSORS = [PROCESSOR]


def extract_segments(ctx, ref: dict, *, raw: bytes | None = None) -> dict:
    """extract_segments(ctx, ref) -> SegmentBatch (implementation plan T03). Checks the local-processing decision for
    this version, reads the verified original when `raw` is not supplied, and returns the Outcome without writing."""
    from . import policy, versions
    from .segments import outcome
    version = versions.resolve(ctx, ref)
    decision = policy.authorize_processing(ctx, version, "local", "extract")
    if not decision.allowed:
        return outcome("blocked_permission", error=decision.reason, detail=policy.message(decision.reason))
    if raw is None:
        from .media import read_original
        raw = read_original(ctx, version)
    return extract_raw(version, raw)


if __name__ != "__main__":
    from .segments import register_processors
    register_processors(PROCESSORS)

if __name__ == "__main__":
    try:
        payload = _child_main(sys.argv[1:])
    except AlphaError as error:
        payload = {"error": str(error)[:300], "code": getattr(error, "code", None)}
    except Exception:  # noqa: BLE001 - the parent only learns that the file could not be read safely
        payload = {"error": "This document could not be read safely.", "code": "library_unreadable_document"}
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
