"""Decode uploaded bytes; never trust the extension or browser MIME."""
import base64
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from postriff_alpha.domain import AlphaError, uid


def _source(payload):
    try:
        raw = base64.b64decode(payload.get("data", ""), validate=True)
    except (ValueError, TypeError) as e:
        raise AlphaError("Supply a valid image file.") from e
    if not 1 <= len(raw) <= 8*1024*1024:
        raise AlphaError("Images must be at most 8 MB.")
    if not (raw.startswith(b'\xff\xd8\xff') or raw.startswith(b'\x89PNG\r\n\x1a\n')):
        raise AlphaError("Use JPEG or PNG image bytes; playlists, documents and remote references are not accepted.")
    return raw


def _decode_ffmpeg(raw):
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise AlphaError("validation_unavailable: ffmpeg and ffprobe are required for the local media decoder.")
    with tempfile.TemporaryDirectory(prefix="postriff-media-") as directory:
        path = Path(directory)/"input"
        path.write_bytes(raw)
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, timeout=10, check=True)
            streams = json.loads(probe.stdout)["streams"]
            if len(streams) != 1:
                raise ValueError()
            stream = streams[0]
            codec = stream.get("codec_name")
            width, height = stream["width"], stream["height"]
            if codec not in ("mjpeg", "png") or not 320 <= width <= 4096 or not 320 <= height <= 4096 or width*height > 16_777_216:
                raise AlphaError("Use a JPEG or PNG image, 320–4096 pixels per side. Video is unavailable in this release.")
            # Full decode, including corrupt/truncated file detection. Do not preserve metadata.
            output = Path(directory)/"rendition.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-protocol_whitelist", "file", "-i", str(path), "-frames:v", "1", "-map_metadata", "-1", "-q:v", "2", str(output)], capture_output=True, timeout=15, check=True)
            rendition = output.read_bytes()
        except (subprocess.SubprocessError, ValueError, KeyError) as e:
            raise AlphaError("The image could not be fully decoded. Choose a valid JPEG or PNG.") from e
    return rendition, width, height, "ffmpeg"


def _decode_pillow(raw):
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as error:
        raise AlphaError("validation_unavailable: install the pinned Pillow dependency for hosted media decoding.") from error
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("JPEG", "PNG") or getattr(image, "n_frames", 1) != 1:
                raise ValueError("unsupported image container")
            width, height = image.size
            if not 320 <= width <= 4096 or not 320 <= height <= 4096 or width * height > 16_777_216:
                raise AlphaError("Use a JPEG or PNG image, 320–4096 pixels per side. Video is unavailable in this release.")
            image.load()  # Full decode catches truncated/corrupt input before storage.
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True, exif=b"")
            rendition = output.getvalue()
    except AlphaError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise AlphaError("The image could not be fully decoded. Choose a valid JPEG or PNG.") from error
    return rendition, width, height, "pillow"


def decode_upload(payload, decoder="auto"):
    raw = _source(payload)
    if decoder == "pillow":
        rendition, width, height, processing = _decode_pillow(raw)
    elif decoder == "ffmpeg" or decoder == "auto" and shutil.which("ffprobe") and shutil.which("ffmpeg"):
        rendition, width, height, processing = _decode_ffmpeg(raw)
    elif decoder == "auto":
        rendition, width, height, processing = _decode_pillow(raw)
    else:
        raise ValueError("Unknown media decoder.")
    return {"id": uid(), "sourceHash": hashlib.sha256(raw).hexdigest(), "hash": hashlib.sha256(rendition).hexdigest(), "bytes": len(rendition), "width": width, "height": height, "mime": "image/jpeg", "duration": 0, "processing": "decoded", "decoder": processing, "data": base64.b64encode(rendition).decode(), "deleted": False}
