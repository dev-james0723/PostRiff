"""Ephemeral color thumbnails for the detected shots in an authorized reference."""
import base64
import io
import time
from contextlib import ExitStack

from postriff_alpha.domain import AlphaError
from . import creative_video_media as media
from .creative_video_reference_signals import _frame


PAGE_SIZE = 4


def windows(analysis, page):
    shots = analysis.get("scenes") or []
    if type(page) is not int or page < 0 or page * PAGE_SIZE >= len(shots):
        raise AlphaError("Choose an available page of reference shots.", 404)
    result = []
    first = page * PAGE_SIZE
    for index, shot in enumerate(shots[first:first + PAGE_SIZE], first):
        start, end = shot.get("startMs"), shot.get("endMs")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= media.MAX_DURATION_MS or
                end > analysis.get("durationMs", 0)):
            raise AlphaError("The saved shot timing is unavailable.", 409)
        result.append({"shotIndex": index, "startMs": start, "endMs": end})
    return result, len(shots)


def picture(source, start, end, deadline):
    from PIL import Image

    # Accurate seeking returns the next decoded picture. Retry at the shot start if a short/VFR
    # shot's midpoint would land in its neighbor. Only attribute a picture with an observed in-shot PTS.
    for target in dict.fromkeys(((start + end) // 2, start)):
        try:
            ppm, pts, width, height = _frame(source, target, deadline, color=True, edge=320)
        except ValueError:
            continue
        if start <= pts < end:
            output = io.BytesIO()
            with Image.open(io.BytesIO(ppm)) as image:
                image.save(output, format="JPEG", quality=79)
            return {"timeMs": pts, "width": width, "height": height,
                    "jpeg": base64.b64encode(output.getvalue()).decode("ascii")}
    return {"timeMs": None, "jpeg": None}


def decode(raw, shots):
    if not 1 <= len(shots) <= PAGE_SIZE:
        raise AlphaError("Choose a single page of reference shots.", 422)
    media._bytes(raw)
    deadline = time.monotonic() + 15
    with ExitStack() as stack:
        stream = media._source(stack, raw)
        return [{**shot, **picture(stream, shot["startMs"], shot["endMs"], deadline)} for shot in shots]
