"""Deterministic, privately composed motion cards. Rendering never contacts a model."""
from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import time

from postriff_alpha.domain import AlphaError
from . import creative_video_media as media
from .creative_video_media_provider import ProviderError
from .creative_video_models import MODELS, STORYBOARD


def _layout_font(size, text):
    from PIL import ImageFont
    if any(ord(c) > 0x2fff for c in text):
        for path in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                     "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"):
            if Path(path).is_file():
                return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width, lines):
    # Pixel wrapping also works for unbroken CJK text. Limit the printed cue while the project keeps the full direction.
    result, line = [], ""
    for char in " ".join(text.split())[:500]:
        if line and draw.textlength(line + char, font=font) > width:
            result.append(line.rstrip())
            if len(result) == lines:
                result[-1] = result[-1][:-1].rstrip() + "…"
                return result
            line = ""
        line += char
    if line:
        result.append(line.strip())
    return result


def _png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _artwork(prompt, profile):
    from PIL import Image, ImageDraw
    width, height = profile["width"], profile["height"]
    unit = min(width, height)
    pad = unit // 16
    ink = "#dbe9df"
    palette = (("#112c2c", "#92dbac"), ("#1d2336", "#a2bbf5"), ("#302423", "#f4b697"))
    bg, accent = palette[hashlib.sha256(prompt.encode()).digest()[0] % len(palette)]
    board = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(board)
    small = _layout_font(unit // 41, "")
    large = _layout_font(unit // 22, prompt)
    draw.text((pad, pad), "RAFII  /  MOTION STORYBOARD", font=small, fill=accent)
    draw.line((pad, pad * 2, width - pad, pad * 2), fill=accent, width=2)
    lines = _wrap(draw, prompt, large, width - pad * 2, 3)
    for index, line in enumerate(lines):
        draw.text((pad, pad * 2.4 + index * unit / 17), line, font=large, fill=ink)
    stage_y, stage_h = int(height * .49), int(height * .33)
    draw.rounded_rectangle((pad, stage_y, width - pad, stage_y + stage_h), radius=unit // 34,
                           fill="#142125", outline=accent, width=2)
    for i in range(1, 7):
        x = pad + (width - 2 * pad) * i / 7
        draw.line((x, stage_y + 3, x, stage_y + stage_h - 3), fill="#30413f")
    draw.line((pad, stage_y + stage_h / 2, width - pad, stage_y + stage_h / 2), fill="#30413f")
    draw.text((pad, height - pad * 1.6), "BLOCKING STUDY", font=small, fill=ink)
    draw.text((width - pad, height - pad * 1.6), f"{profile['durationMs'] / 1000:.2f} s", font=small, fill=accent, anchor="ra")
    size = min(unit // 5, stage_h * 3 // 4)
    mark = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glyph = ImageDraw.Draw(mark)
    glyph.rounded_rectangle((3, 3, size - 4, size - 4), radius=size // 5, fill=accent)
    glyph.ellipse((size * .25, size * .25, size * .75, size * .75), outline=bg, width=max(2, size // 19))
    return _png(board), _png(mark), pad * 2, width - pad * 2 - size, stage_y + (stage_h - size) // 2


def _render(prompt, profile):
    board, mark, start_x, end_x, y = _artwork(prompt, profile)
    frames = round(profile["durationMs"] * media.FPS / 1000)
    # Only our fixed integers and timing expression enter the graph. User text is rasterized separately.
    motion = f"{start_x}+({end_x}-{start_x})*(1-cos(PI*n/{max(1, frames - 1)}))/2"
    loop = f"loop=loop=-1:size=1:start=0,setpts=N/({media.FPS}*TB)"
    graph = f"[0:v]{loop}[base];[1:v]{loop}[mark];[base][mark]overlay=x='{motion}':y={y}:eval=frame,format=yuv420p[out]"
    with ExitStack() as stack:
        background = media._source(stack, board)
        foreground = media._source(stack, mark)
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="rafii-storyboard-")))
        output = directory / "card.mp4"
        media._cmd("ffmpeg", ["-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-max_alloc", "67108864",
            "-filter_complex_threads", "1", "-threads", "1", "-protocol_whitelist", "pipe",
            "-f", "image2pipe", "-framerate", str(media.FPS), "-c:v", "png", "-i", "pipe:0",
            "-threads", "1", "-protocol_whitelist", "fd", "-f", "image2pipe", "-framerate", str(media.FPS),
            "-c:v", "png", "-fd", str(foreground.fileno()), "-i", "fd:", "-filter_complex", graph, "-map", "[out]",
            "-an", "-frames:v", str(frames), "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", "20",
            "-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(media.MAX_MEDIA_BYTES), "-f", "mp4", str(output)],
            background, time.monotonic() + 35, pass_fds=(foreground.fileno(),))
        if not 0 < output.stat().st_size <= media.MAX_MEDIA_BYTES:
            raise AlphaError("Storyboard exceeded the media size limit.", 413)
        return output.read_bytes()


class StoryboardProvider:
    model = STORYBOARD
    provider = "rafii-local"

    @classmethod
    def from_environment(cls, _env):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe") or importlib.util.find_spec("PIL") is None:
            raise ProviderError("The storyboard worker needs its installed video and image libraries.", status=503,
                                code="creative_video_provider_unavailable")
        return cls()

    @staticmethod
    def _handle(prompt, strategy):
        if (not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt or len(prompt) > 4000
                or strategy.get("model") != STORYBOARD):
            raise AlphaError("The storyboard needs an approved, bounded scene direction.", 422)
        data = json.dumps([strategy["model"], strategy["durationMs"], strategy["aspectRatio"], prompt],
                          ensure_ascii=False, separators=(",", ":"))
        return "storyboard-" + hashlib.sha256(data.encode()).hexdigest()

    def submit(self, *, prompt, duration_ms, aspect_ratio, strategy):
        if strategy["durationMs"] != duration_ms or strategy["aspectRatio"] != aspect_ratio:
            raise AlphaError("Storyboard settings changed. Review a fresh quote.", 409)
        return self._handle(prompt, strategy)

    def poll(self, operation, *, strategy, prompt):
        if operation != self._handle(prompt, strategy):
            raise AlphaError("This storyboard does not match the approved scene.", 409)
        profile = MODELS[STORYBOARD].profile(strategy["durationMs"], strategy["aspectRatio"], "720p", "silent")
        return {"state": "completed", "video": _render(prompt, profile), "costUsdMicro": 0,
                "costSource": "no_external_provider", "mediaKind": "composed"}
