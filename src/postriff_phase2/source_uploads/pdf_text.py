"""Bounded text extraction from a text PDF (PRD R-FWR-04), with pypdf (BSD-3-Clause, pinned in requirements.txt).

The parser runs in a child Python process that receives only the PDF bytes and its limits on stdin/argv (no
environment secrets) and is killed at the elapsed-time cap, so a pathological file can't hang or exhaust the worker.
It refuses encrypted files, reads at most `max_pages` pages (or the selected range), measures every selected page's
text, and returns the text only while the total stays within `max_chars`; past that it returns the measured total
and the per-page counts so the person can choose pages. A file whose pages carry (almost) no text is scanned or
image-only: there is no qualified OCR route, so it is `no_text_layer`.

Statuses: ok · encrypted · unreadable · no_text_layer · too_many_pages · over_limit · timeout · parser_unavailable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

MIN_TEXT = 32   # fewer readable characters than this across the selected pages: no usable text layer
_CHILD = r'''
import io, json, re, sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
except Exception:
    pass
params = json.loads(sys.argv[1])
data = sys.stdin.buffer.read(params["maxBytes"] + 1)
def out(value):
    sys.stdout.write(json.dumps(value)); sys.stdout.flush(); sys.exit(0)
try:
    from pypdf import PdfReader
except Exception:
    out({"status": "parser_unavailable"})
if len(data) > params["maxBytes"]:
    out({"status": "unreadable"})
try:
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        out({"status": "encrypted"})
    count = len(reader.pages)
except Exception:
    out({"status": "unreadable"})
first, last = params.get("pages") or (1, count)
if count == 0 or first > count:
    out({"status": "unreadable", "pageCount": count})
last = min(last, count)
if last - first + 1 > params["maxPages"]:
    out({"status": "too_many_pages", "pageCount": count, "maxPages": params["maxPages"]})
control = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
pages, texts, total, failed = [], [], 0, []
for number in range(first, last + 1):
    try:
        text = reader.pages[number - 1].extract_text() or ""
    except Exception:
        text = ""
        failed.append(number)
    text = control.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    pages.append({"page": number, "chars": len(text)})
    texts.append(text)
    total += len(text) + (2 if len(pages) > 1 else 0)
readable = sum(len(re.sub(r"\s+", "", t)) for t in texts)
result = {"pageCount": count, "pages": pages, "selection": [first, last], "totalChars": total, "failedPages": failed[:50]}
if readable < params["minText"]:
    out({"status": "no_text_layer", **result})
if total > params["maxChars"]:
    out({"status": "over_limit", **result})
out({"status": "ok", "text": "\n\n".join(texts), **result})
'''


def available():
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def _child_environment():
    """Only what the interpreter needs to import pypdf: never the function's secrets."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
            "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}


def extract(data, *, max_bytes, max_pages, max_chars, seconds, pages=None):
    """One bounded extraction. `pages` is an inclusive (first, last) selection, 1-based."""
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > max_bytes:
        return {"status": "unreadable"}
    params = {"maxBytes": int(max_bytes), "maxPages": int(max_pages), "maxChars": int(max_chars), "minText": MIN_TEXT,
              "pages": [int(pages[0]), int(pages[1])] if pages else None}
    try:
        done = subprocess.run([sys.executable, "-c", _CHILD, json.dumps(params)], input=bytes(data), capture_output=True,
                              timeout=max(1.0, float(seconds)), env=_child_environment(), check=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except OSError:
        return {"status": "parser_unavailable"}
    if done.returncode != 0 or len(done.stdout) > 2_000_000:
        return {"status": "unreadable"}
    try:
        result = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"status": "unreadable"}
    if not isinstance(result, dict) or result.get("status") not in ("ok", "encrypted", "unreadable", "no_text_layer", "too_many_pages", "over_limit", "parser_unavailable"):
        return {"status": "unreadable"}
    if result["status"] == "ok" and (not isinstance(result.get("text"), str) or len(result["text"]) > max_chars):
        return {"status": "unreadable"}
    return result
