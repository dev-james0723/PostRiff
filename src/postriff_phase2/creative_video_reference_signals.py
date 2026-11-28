"""Offline, word-free observations from representative frames of an authorized reference."""
from __future__ import annotations

import csv
import io
import math
import re
import shutil
import statistics
import tempfile
import time
from contextlib import ExitStack

from postriff_alpha.domain import AlphaError
from . import creative_video_media as media
from .growth.trends.media_runtime import MediaRuntimeError, _run

EDGE = 768
MIN_CONFIDENCE = 60
CTA = re.compile(r"\b(shop now|buy now|learn more|sign up|get started|book now|order now|subscribe|tap to)\b")


def _targets(analysis):
    scenes = analysis["scenes"]
    if not scenes:
        return []
    if len(scenes) == 1:
        positions = [(0, .1), (0, .5), (0, .9)]
    else:
        positions = [(i, .5) for i in sorted({0, len(scenes) // 2, len(scenes) - 1})]
    interval = max(1, math.ceil(1000 / analysis["fps"]))
    targets = []
    for index, fraction in positions:
        start, end = scenes[index]["startMs"], scenes[index]["endMs"]
        target = max(start, min(start + round((end - start) * fraction), end - interval))
        if (index, target) not in targets:
            targets.append((index, target))
    return targets


def _frame(source, target_ms, deadline, *, color=False, edge=EDGE):
    # Capture one encoder PTS from the same frame as the image. Both
    # outputs use inherited descriptors. No path or filter comes from the project.
    with tempfile.TemporaryFile() as stamp:
        args = ["-ss", f"{target_ms / 1000:.3f}", *media._decode(), "-copyts", "-map", "0:V:0",
                "-an", "-sn", "-dn", "-vf", f"scale={edge}:{edge}:force_original_aspect_ratio=decrease:"
                f"force_divisible_by=2:reset_sar=1,format={'rgb24' if color else 'gray'}", "-frames:v", "1", "-fps_mode", "passthrough",
                "-enc_time_base", "demux", "-stats_enc_pre", f"pipe:{stamp.fileno()}", "-stats_enc_pre_fmt", "{t}",
                "-threads", "1", "-c:v", "ppm" if color else "pgm", "-f", "image2pipe", "pipe:1"]
        channels = 3 if color else 1
        image = media._cmd("ffmpeg", args, source, deadline, edge * edge * channels + 128, pass_fds=(stamp.fileno(),))
        stamp.seek(0)
        pts = stamp.read(64)
    header = re.match((b"P6" if color else b"P5") + rb"\s+(\d{1,3})\s+(\d{1,3})\s+255\n", image)
    if not header or not pts:
        raise ValueError("frame_missing")
    width, height = map(int, header.groups())
    if not (0 < width <= edge and 0 < height <= edge and len(image) - header.end() == width * height * channels):
        raise ValueError("frame_invalid")
    return image, round(float(pts) * 1000), width, height


def _measure(tsv, width, height):
    confidences, centers, heights = [], [], []
    lines = {}
    rows = csv.DictReader(io.StringIO(tsv.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE)
    fields = {"level", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text"}
    if not fields.issubset(rows.fieldnames or ()):
        raise ValueError("ocr_format_unavailable")
    page_seen = False
    for row in rows:
        if row["level"] == "1":
            page_seen = int(row["width"]) == width and int(row["height"]) == height
        if row["level"] != "5":
            continue
        word, confidence = row["text"].strip(), float(row["conf"])
        left, top, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        if not (MIN_CONFIDENCE <= confidence <= 100 and word and 0 <= left < left + w <= width
                and 0 <= top < top + h <= height):
            continue
        line = (row["block_num"], row["par_num"], row["line_num"])
        lines.setdefault(line, []).append(word.casefold())
        if any(ch.isalnum() for ch in word):
            confidences.append(confidence)
            centers.append((top + h / 2) / height)
            heights.append(100 * h / height)
    if not page_seen:
        raise ValueError("ocr_page_unavailable")
    clues = []
    for words in lines.values():
        if any("?" in word for word in words) and "question" not in clues:
            clues.append("question")
        if CTA.search(" ".join(words)) and "call_to_action" not in clues:
            clues.append("call_to_action")
    region = None
    if centers:
        median = statistics.median(centers)
        region = "upper" if median < 1 / 3 else "lower" if median >= 2 / 3 else "middle"
    # OCR strings and bounding boxes are intentionally short-lived in this worker.
    return {"wordCount": len(confidences),
            "meanConfidence": round(statistics.mean(confidences), 1) if confidences else None,
            "verticalRegion": region, "medianWordHeightPct": round(statistics.median(heights), 1) if heights else None,
            "interpretiveClues": clues}


def reference_signals(raw: bytes, analysis: dict) -> dict:
    """Sample up to three frames once at intake; absence of detections is scoped to those frames."""
    media._bytes(raw)
    report = {"state": "unavailable", "method": "tesseract-tsv-v1", "language": "eng",
              "minimumWordConfidence": MIN_CONFIDENCE, "frames": []}
    executable = shutil.which("tesseract")
    if not executable or not shutil.which("ffmpeg"):
        return {**report, "reason": "runtime_unavailable"}
    deadline = time.monotonic() + 15
    try:
        with ExitStack() as stack:
            empty = stack.enter_context(tempfile.TemporaryFile())
            languages, _ = _run([executable, "--list-langs"], empty, deadline=min(deadline, time.monotonic() + 2),
                                output_cap=16 * 1024)
            if b"eng" not in languages.splitlines():
                return {**report, "reason": "english_data_unavailable"}
            source = media._source(stack, raw)
            targets = _targets(analysis)
            missed = False
            for scene_index, target in targets:
                try:
                    frame_deadline = min(deadline, time.monotonic() + 5)
                    image, timestamp, width, height = _frame(source, target, frame_deadline)
                    scene = analysis["scenes"][scene_index]
                    if not scene["startMs"] <= timestamp < scene["endMs"]:
                        raise ValueError("outside_sampled_scene")
                    if any(item["timeMs"] == timestamp for item in report["frames"]):
                        continue
                    with tempfile.TemporaryFile() as pixels:
                        pixels.write(image)
                        tsv, _ = _run([executable, "stdin", "stdout", "-l", "eng", "--psm", "11", "tsv"],
                                      pixels, deadline=frame_deadline, output_cap=64 * 1024)
                    measurements = _measure(tsv, width, height)
                    report["frames"].append({"sceneIndex": scene_index, "timeMs": timestamp, **measurements})
                except (AlphaError, MediaRuntimeError, OSError, ValueError, KeyError, TypeError, csv.Error, OverflowError):
                    missed = True
    except (MediaRuntimeError, OSError):
        return {**report, "reason": "runtime_unavailable"}
    if not report["frames"]:
        return {**report, "reason": "samples_unavailable"}
    if missed:
        return {**report, "state": "partial", "reason": "samples_unavailable"}
    return {**report, "state": "measured"}
