"""Rafii PDF intake: bounded bytes, actual parse/page limit and active-content rejection.

LinkedIn accepts more Office formats and up to 100 MB. This initial Rafii intake
deliberately accepts PDFs up to 8 MiB; other formats are not claimed implemented.
"""
import base64
import hashlib
import io
import json
import subprocess
import sys
import os
from pathlib import Path
from postriff_alpha.domain import AlphaError, uid


def decode_pdf(payload):
    try: raw = base64.b64decode(payload.get("data", ""), validate=True)
    except (TypeError, ValueError) as error: raise AlphaError("Supply valid PDF bytes.", 400) from error
    if not 1 <= len(raw) <= 8*1024*1024 or not raw.startswith(b"%PDF-"):
        raise AlphaError("Rafii accepts a PDF up to 8 MiB.", 400)
    try:
        result = _validate(raw, 'pdf')
        pages = json.loads(result.stdout)['pages']
    except (subprocess.SubprocessError, ValueError, KeyError) as error:
        raise AlphaError("Use a valid, unencrypted PDF with 1–300 pages and no active content; validation is bounded to eight seconds.", 400) from error
    digest = hashlib.sha256(raw).hexdigest()
    return {"id": uid(), "hash": digest, "sourceHash": digest, "mime": "application/pdf", "bytes": len(raw),
            "pages": pages, "processing": "validated", "decoder": "pypdf-6.19.0", "deleted": False,
            "data": base64.b64encode(raw).decode()}


def _pdf(raw):
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 300:
            raise ValueError("encrypted or invalid page count")
        root = reader.trailer["/Root"]
        if any(key in root for key in ("/OpenAction", "/AA")) or any(key in root.get("/Names", {}) for key in ("/JavaScript", "/EmbeddedFiles")):
            raise ValueError("active content")
        for page in reader.pages:
            if "/AA" in page: raise ValueError("active content")
            for annotation in page.get('/Annots', []):
                obj = annotation.get_object()
                if '/AA' in obj or ('/A' in obj and obj['/A'].get('/S') not in ('/URI', '/GoTo')):
                    raise ValueError('active annotation')
            page.get_contents()  # parse the stream reference; do not extract private text
        pages = len(reader.pages)
    except Exception as error:
        raise ValueError('Invalid PDF') from error
    return {'pages': pages}


def decode_gif(payload):
    try:
        raw = base64.b64decode(payload.get('data', ''), validate=True)
        if not 1 <= len(raw) <= 8*1024*1024 or raw[:6] not in (b'GIF87a', b'GIF89a'): raise ValueError('GIF bytes')
        result = _validate(raw, 'gif')
        info = json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError, TypeError) as error:
        raise AlphaError('Use a valid GIF up to 8 MiB, 300 frames and 120 million decoded pixels.', 400) from error
    hashed = hashlib.sha256(raw).hexdigest()
    return {'id': uid(), 'hash': hashed, 'sourceHash': hashed, 'mime': 'image/gif', 'bytes': len(raw), 'processing': 'decoded',
            'decoder': 'pillow-original-gif', 'deleted': False, 'data': base64.b64encode(raw).decode(), **info}


def _gif(raw):
    from PIL import Image
    image = Image.open(io.BytesIO(raw))
    width, height = image.size
    frames, milliseconds = image.n_frames, 0
    if image.format != 'GIF' or not 1 <= frames <= 300 or not 1 <= width <= 4096 or not 1 <= height <= 4096 or width*height*frames > 120_000_000:
        raise ValueError('GIF dimensions/frames')
    for index in range(frames):
        image.seek(index);image.load()
        milliseconds += max(0, min(int(image.info.get('duration', 0)), 60000))
    return {'width': width, 'height': height, 'frames': frames, 'duration': milliseconds/1000}


def _validate(raw, mode):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    return subprocess.run([sys.executable, '-m', 'postriff_phase2.social_documents', mode], input=raw, capture_output=True, timeout=8, check=True, env=env)


if __name__ == '__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    if sys.platform != 'darwin': resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
    raw = sys.stdin.buffer.read(8*1024*1024+1)
    print(json.dumps(_pdf(raw) if sys.argv[1] == 'pdf' else _gif(raw)))
