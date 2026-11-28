"""Create an original diagnostic reference and editable video examples with zero provider calls.

Run from the repository root with PYTHONPATH=src and an empty output folder.
Dependencies are the project's Pillow and host FFmpeg/FFprobe.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version
# The existing scripts/postriff_phase2.py entry point shares the package name.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.creative_video_media import FPS, analyze_reference, render_composition


WIDTH, HEIGHT = 216, 384
SCENE_FRAMES = (30, 36, 30)
REFERENCE = {
    "name": "Field interval", "series": "DESK OBJECTS", "light": "#e4d9c9", "dark": "#252525",
    "accent": "#da4826", "copy": ("Start a minute.", "Set your pace.", "Make some space."),
}
ORIGINAL = {
    "name": "Orbit dial", "series": "STUDIO STUDIES", "light": "#e8ebdc", "dark": "#1b3632",
    "accent": "#dd743a", "copy": ("A turn to begin.", "Time in motion.", "Find your tempo."),
}


def frame(style, shot, index, alternate=False):
    phase = index / (SCENE_FRAMES[shot] - 1)
    night = shot == 1 or alternate
    bg, ink = (style["dark"], style["light"]) if night else (style["light"], style["dark"])
    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image)
    small = ImageFont.load_default(size=8)
    large = ImageFont.load_default(size=23)
    draw.line((15, 34, WIDTH - 15, 34), fill=ink)
    draw.text((15, 18), style["series"], font=small, fill=ink)
    draw.text((WIDTH - 15, 18), f"{shot + 1} / 3", font=small, fill=ink, anchor="ra")
    draw.text((15, 51), style["name"], font=large, fill=ink)
    draw.text((16, 81), style["copy"][shot], font=small, fill=ink)
    radius = (81, 134, 62)[shot]
    cx = WIDTH // 2 + (int(26 * math.sin(phase * math.pi)) if shot == 1 else 0)
    cy = (209, 240, 198)[shot]
    if alternate:
        radius = 70
        cx += int(14 * math.cos(phase * math.pi))
    draw.ellipse((cx - radius + 5, cy - radius + 7, cx + radius + 5, cy + radius + 7),
                 outline=style["accent"], width=2)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=ink, width=4)
    # The marked dial and independent hand move every frame. All geometry,
    # type placement, measurements and graphics are authored for this fixture.
    for k in range(48):
        angle = k * math.tau / 48 + (.12 * phase if shot == 1 else 0)
        inner = radius - (14 if k % 4 == 0 else 9)
        outer = radius - 5
        draw.line((cx + inner * math.sin(angle), cy - inner * math.cos(angle),
                   cx + outer * math.sin(angle), cy - outer * math.cos(angle)),
                  fill=ink, width=2 if k % 4 == 0 else 1)
    angle = (-135 + phase * (147 if alternate else 105) + 55 * shot) * math.pi / 180
    tip = cx + (radius - 22) * math.sin(angle), cy - (radius - 22) * math.cos(angle)
    draw.line((cx, cy, *tip), fill=style["accent"], width=5)
    draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=ink)
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=bg)
    draw.line((15, 340, WIDTH - 15, 340), fill=ink)
    draw.text((15, 350), "A MOTION STUDY", fill=ink, font=small)
    return image


def encode(style, shots, output, *, alternate=False):
    with tempfile.TemporaryFile() as pixels:
        for shot in shots:
            for i in range(SCENE_FRAMES[shot]):
                pixels.write(frame(style, shot, i, alternate=alternate).tobytes())
        pixels.seek(0)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "pipe:0",
            "-f", "lavfi", "-i", f"sine=frequency={220 + 110 * shots[0]}:sample_rate=48000",
            "-t", str(sum(SCENE_FRAMES[n] for n in shots) / FPS),
            "-map_metadata", "-1", "-c:v", "libx264", "-threads", "1", "-crf", "17",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output)],
            stdin=pixels, check=True, timeout=30)


def decoded_frames(raw):
    with tempfile.NamedTemporaryFile(suffix=".mp4") as source:
        source.write(raw)
        source.flush()
        checks = subprocess.check_output(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", source.name, "-map", "0:v:0", "-f", "framemd5", "-"], timeout=30)
    return [line.rsplit(b",", 1)[-1].strip() for line in checks.splitlines() if line and not line.startswith(b"#")]


def generate(output):
    reference = output / "reference.mp4"
    encode(REFERENCE, [0, 1, 2], reference)
    started = time.monotonic()
    analysis = analyze_reference(reference.read_bytes())
    analysis_time = time.monotonic() - started
    if [s["startMs"] for s in analysis["scenes"]] != [0, 1250, 2750]:
        raise RuntimeError("The detector did not recover the two authored cuts.")
    clips = {}
    edits = []
    for shot, count in enumerate(SCENE_FRAMES):
        key = f"original-{shot + 1}"
        path = output / (key + ".mp4")
        encode(ORIGINAL, [shot], path)
        clips[key] = path.read_bytes()
        edits.append({"sceneId": f"scene-{shot + 1}", "clipId": key, "durationMs": round(count * 1000 / FPS),
                      "caption": ORIGINAL["copy"][shot]})
    t = time.monotonic()
    version1, receipt1 = render_composition(edits, clips)
    v1_time = time.monotonic() - t
    (output / "original-cut.mp4").write_bytes(version1)
    new_clip = output / "revised-intro.mp4"
    encode(ORIGINAL, [0], new_clip, alternate=True)
    revised = [dict(s) for s in edits]
    revised[0].update(clipId="revised-intro", caption="Start with one turn.")
    revised_clips = {"revised-intro": new_clip.read_bytes(), **{k: v for k, v in clips.items() if k != "original-1"}}
    t = time.monotonic()
    version2, receipt2 = render_composition(revised, revised_clips)
    v2_time = time.monotonic() - t
    (output / "revised-cut.mp4").write_bytes(version2)
    hashes1, hashes2 = decoded_frames(version1), decoded_frames(version2)
    if (hashes1[:30] == hashes2[:30] or hashes1[30:] != hashes2[30:] or
            len(hashes1) != sum(SCENE_FRAMES) or len(hashes2) != sum(SCENE_FRAMES) or
            receipt1["scenes"][1:] != receipt2["scenes"][1:]):
        raise RuntimeError("The targeted edit did not preserve the rest of the timeline.")
    for raw, expected in ((version1, receipt1), (version2, receipt2)):
        captions = analyze_reference(raw)["measured"]["embeddedCaptions"]
        if captions["cues"] != [{"startMs": s["startMs"], "endMs": s["endMs"]} for s in expected["scenes"]]:
            raise RuntimeError("An exported caption missed its planned scene.")

    def write_json(name, data):
        (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    write_json("timeline.json", {"aspectRatio": "9:16", "clips": {path.stem: path.name for path in sorted(output.glob("*.mp4"))
        if (path.stem.startswith("original-") and path.stem != "original-cut") or path.stem == "revised-intro"},
        "versions": [edits, revised]})
    write_json("reference-analysis.json", analysis)
    write_json("render-receipt.json", {
        "scope": "Offline analysis, editing and rendering with original procedural footage and synthesized test tones.",
        "generator": "scripts/creative_video_media_example.py", "aiProviderRequests": 0, "providerSpendUsd": 0,
        "humanCreativeAcceptance": "not performed", "costPerAcceptedCreative": None, "liveGenerationLatencySeconds": None,
        "python": platform.python_version(), "pillow": pillow_version,
        "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        "seconds": {"referenceAnalysis": round(analysis_time, 4), "firstRender": round(v1_time, 4), "revisedRender": round(v2_time, 4)},
        "decodedFramesCompared": len(hashes1), "unchangedTailFrames": len(hashes1[30:]),
        "firstExport": receipt1, "revisedExport": receipt2, "artifacts": {path.name: {
            "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(output.glob("*.mp4"))}})
    print(f"Verified {len(hashes1)} frames, both caption timelines and {len(hashes1[30:])} unchanged tail frames.")


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary)
        generate(staged)
        for existing in output.iterdir():
            candidate = staged / existing.name
            if (existing.is_symlink() or not existing.is_file() or not candidate.is_file()
                    or existing.read_bytes() != candidate.read_bytes()):
                raise SystemExit("Choose an empty folder to preserve the existing example.")
        for path in staged.iterdir():
            target = output / path.name
            if not target.exists():
                with target.open("xb") as out:
                    out.write(path.read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Empty destination for fixtures, editable timeline, exports and receipts.")
    main(parser.parse_args().output)
