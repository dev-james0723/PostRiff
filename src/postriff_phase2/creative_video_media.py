"""Bounded byte-in/byte-out video processing for Rafii's private creative worker.

The caller resolves and authorizes workspace assets. No filename, remote address,
executable, decoder option or filter expression is accepted from a project.
"""
from __future__ import annotations

from array import array
from contextlib import ExitStack
from fractions import Fraction
import hashlib
import html
import json
import math
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time

from postriff_alpha.domain import AlphaError
from . import mp4_boxes
from .growth.trends.media_runtime import MediaRuntimeError, _run

MAX_MEDIA_BYTES = 64 * 1024 * 1024
MAX_DURATION_MS = 90_000
MAX_SCENES = 32
MIN_SCENE_MS = 42
MAX_SCENE_MS = 8_000
FPS = 24
SAMPLE_FPS = 8
SAMPLE_WIDTH = 32
SAMPLE_HEIGHT = 18
AUDIO_RATE = 48_000
SIZES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}


def _error(message, code="creative_video_media_invalid", status=422):
    raise AlphaError(message, status, code=code)


def _cmd(binary, args, stream, deadline, limit=256 * 1024, pass_fds=()):
    executable = shutil.which(binary)
    if not executable:
        _error("This video worker needs FFmpeg and FFprobe.", "creative_video_worker_unavailable", 503)
    try:
        return _run([executable, *args], stream, deadline=deadline, output_cap=limit, pass_fds=pass_fds)[0]
    except MediaRuntimeError as error:
        if str(error) == "media_processing_deadline":
            _error("The video exceeded the worker time limit.", "creative_video_time_limit", 422)
        _error("The video could not be processed within the supported media limits.")


def _bytes(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_MEDIA_BYTES:
        _error("Use a video of up to 64 MiB.", "creative_video_size_limit", 413)
    if mp4_boxes.brand(raw[:1024]) is None:
        _error("Use a self-contained MP4 or MOV video.", "creative_video_format", 415)
    return raw


def _input(fd=0):
    # Only the inherited, seekable descriptor is readable. Disable QuickTime
    # data references explicitly even if the system's decoder defaults change.
    return ["-protocol_whitelist", "fd,pipe", "-format_whitelist", "mov", "-f", "mov",
            "-enable_drefs", "0", "-use_absolute_path", "0", "-max_streams", "12",
            "-probesize", "2097152", "-analyzeduration", "5000000", "-fd", str(fd), "-i", "fd:"]


def _source(stack, data):
    stream = stack.enter_context(tempfile.TemporaryFile())
    stream.write(data)
    stream.seek(0)
    return stream


def _decode():
    return ["-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-max_alloc", "67108864",
            "-filter_threads", "1", "-threads", "1", "-max_pixels", "8847360", *_input()]


def _probe(stream, deadline, *, count=False):
    args = ["-v", "error", "-max_alloc", "67108864", "-threads", "1", "-max_pixels", "8847360",
            *_input(), "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,start_time,duration,avg_frame_rate,"
            "r_frame_rate,nb_frames,nb_read_frames,channels,sample_rate:"
            "stream_side_data=rotation:stream_disposition=attached_pic", "-of", "json"]
    if count:
        args += ["-count_frames"]
    raw = _cmd("ffprobe", args, stream, deadline, 64 * 1024)
    try:
        streams = json.loads(raw)["streams"]
        video = next(s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic"))
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        width, height = video["width"], video["height"]
        # Zero-origin assets only. A positive audio start is honored by the
        # resampler. A trailing audio track does not extend the visual timeline.
        duration = Fraction(video["duration"])
        fps = Fraction(video["avg_frame_rate"])
        if not fps:
            fps = Fraction(video["r_frame_rate"])
        if (not 0 < duration <= MAX_DURATION_MS / 1000 or not 0 < fps <= 120 or
                not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > 8_847_360 or
                abs(float(video.get("start_time", 0))) > .05 or
                (audio and (int(audio["channels"]) > 8 or int(audio["sample_rate"]) > 192_000))):
            _error("Use a zero-start video up to 90 seconds, 4K and 120 frames per second.")
        rotation = next((float(d["rotation"]) for d in video.get("side_data_list", []) if "rotation" in d), 0)
        if int(rotation) % 180 == 90:
            width, height = height, width
        caption = next((s for s in streams if s.get("codec_name") == "mov_text"), None)
        return {"width": width, "height": height, "durationMs": round(duration * 1000), "fps": round(float(fps), 5),
                "hasAudio": audio is not None, "videoIndex": video["index"], "audioIndex": audio["index"] if audio else None,
                "audioDurationMs": round(Fraction(audio["duration"]) * 1000) if audio and audio.get("duration") else None,
                "videoCodec": video["codec_name"], "frameCount": int(video.get("nb_read_frames") or video.get("nb_frames") or 0),
                "captionTrack": caption is not None, "captionIndex": caption["index"] if caption else None}
    except (StopIteration, KeyError, ValueError, ArithmeticError, TypeError, OverflowError) as error:
        raise AlphaError("The video has no supported visual timeline.", 422, code="creative_video_media_invalid") from error


def _pixels(rgb):
    stride = SAMPLE_WIDTH * SAMPLE_HEIGHT * 3
    if not rgb or len(rgb) % stride:
        _error("No complete video frame was decoded.")
    frames = []
    previous = None
    center = [y * SAMPLE_WIDTH + x for y in range(SAMPLE_HEIGHT // 4, SAMPLE_HEIGHT * 3 // 4)
              for x in range(SAMPLE_WIDTH // 4, SAMPLE_WIDTH * 3 // 4)]
    for offset in range(0, len(rgb), stride):
        frame = rgb[offset:offset + stride]
        color = tuple(sum(frame[c::3]) / (stride // 3) for c in range(3))
        luma = [.2126 * r + .7152 * g + .0722 * b for r, g, b in zip(frame[::3], frame[1::3], frame[2::3])]
        center_sum = sum(luma[i] for i in center)
        change = sum(abs(a - b) for a, b in zip(frame, previous)) / (stride * 255) if previous else 0.
        frames.append((color, sum(luma) / (len(luma) * 255), center_sum / (len(center) * 255),
                       (sum(luma) - center_sum) / ((len(luma) - len(center)) * 255), change))
        previous = frame
    return frames


def _audio_levels(pcm, start, end):
    if pcm is None or start >= len(pcm):
        return {"audioRms": None, "audioPeak": None, "quietFraction": None}
    segment = pcm[start:end]
    if not segment:
        return {"audioRms": None, "audioPeak": None, "quietFraction": None}
    # Quiet fraction counts near-silent 50ms windows, rather than the zero
    # crossings of a loud waveform.
    window_peaks = [max(map(abs, segment[i:i + 400])) for i in range(0, len(segment), 400)]
    return {"audioRms": round(math.sqrt(sum(v * v for v in segment) / len(segment)) / 32768, 4),
            "audioPeak": round(max(window_peaks) / 32768, 4),
            "quietFraction": round(sum(v < 328 for v in window_peaks) / len(window_peaks), 4)}


def _audio_rhythm(pcm, duration_ms):
    """Locate loudness rises in decoded 8 kHz mono PCM. No words or audio are retained."""
    window_ms = 20
    samples_per_window = window_ms * 8
    sample_count = min(len(pcm), duration_ms * 8) if pcm is not None else 0
    result = {"method": "loudness-rise-v1", "state": "no_audio_track" if pcm is None else "unavailable",
              "resolutionMs": window_ms, "analyzedDurationMs": sample_count // samples_per_window * window_ms,
              "onsetMs": [], "medianSpacingMs": None}
    if sample_count < 2 * samples_per_window:
        return result
    previous = None
    onsets = result["onsetMs"]
    for offset in range(0, sample_count - samples_per_window + 1, samples_per_window):
        window = pcm[offset:offset + samples_per_window]
        rms = math.sqrt(sum(v * v for v in window) / samples_per_window) / 32768
        at = offset // 8
        # Require both a relative rise and an absolute change above quiet noise.
        # Adjacent rising windows usually describe the same acoustic attack.
        if (previous is not None and rms >= 1.8 * previous and rms - previous >= .025
                and (not onsets or at - onsets[-1] >= 100)):
            onsets.append(at)
        previous = rms
    result["state"] = "measured"
    if len(onsets) >= 3:
        result["medianSpacingMs"] = round(statistics.median(b - a for a, b in zip(onsets, onsets[1:])))
    return result


def _caption_timing(stream, probe, deadline):
    """Measure embedded timed-text samples without reading or storing their words."""
    if not probe["captionTrack"]:
        return {"state": "no_embedded_track", "cues": []}
    raw = _cmd("ffprobe", ["-v", "error", "-max_alloc", "67108864", *_input(),
               "-select_streams", str(probe["captionIndex"]), "-read_intervals", "%+#513", "-show_packets",
               "-show_entries", "packet=pts_time,duration_time,size", "-of", "json"], stream, deadline, 128 * 1024)
    try:
        packets = json.loads(raw).get("packets", [])
        cues = []
        for packet in packets[:512]:
            if int(packet["size"]) <= 2:
                continue  # Empty mov_text sample between visible cues.
            start = max(0, round(Fraction(packet["pts_time"]) * 1000))
            end = min(probe["durationMs"], start + round(Fraction(packet["duration_time"]) * 1000))
            if start < end:
                cues.append({"startMs": start, "endMs": end})
        return {"state": "partial" if len(packets) > 512 else "measured", "cues": cues}
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return {"state": "timing_unavailable", "cues": []}


def analyze_reference(raw: bytes, *, count_frames=False, include_audio_rhythm=True) -> dict:
    """Measure an authorized reference. Candidate cuts have 125ms sampling resolution."""
    _bytes(raw)
    deadline = time.monotonic() + 60
    with ExitStack() as stack:
        stream = _source(stack, raw)
        probe = _probe(stream, deadline, count=count_frames)
        captions = _caption_timing(stream, probe, deadline)
        duration = probe["durationMs"]
        rate = SAMPLE_FPS
        pixels = _cmd("ffmpeg", [*_decode(), "-map", f"0:{probe['videoIndex']}", "-an", "-t", f"{duration / 1000:.3f}",
            "-vf", f"fps={rate}:start_time=0:round=up,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area,format=rgb24",
            "-threads", "1", "-f", "rawvideo", "pipe:1"], stream, deadline,
            (MAX_DURATION_MS * rate // 1000 + 1) * SAMPLE_WIDTH * SAMPLE_HEIGHT * 3)
        frames = _pixels(pixels)
        pcm = None
        if probe["hasAudio"]:
            audio = _cmd("ffmpeg", [*_decode(), "-map", f"0:{probe['audioIndex']}", "-vn",
                "-af", "aresample=8000:async=1:first_pts=0", "-ac", "1", "-t", f"{duration / 1000:.3f}",
                "-f", "s16le", "pipe:1"], stream, deadline, MAX_DURATION_MS * 16 + 16000)
            pcm = array("h")
            pcm.frombytes(audio)
            if sys.byteorder != "little":
                pcm.byteswap()

    starts = [0]
    for i, frame in enumerate(frames[1:], 1):
        # Strong RGB differences nominate a hard cut. The spacing threshold
        # suppresses neighboring detections in flashes and short dissolves.
        if frame[4] >= .20 and i - starts[-1] >= 2 and duration - i * 125 >= 125:
            starts.append(i)
    scenes = []
    for n, index in enumerate(starts):
        following = starts[n + 1] if n + 1 < len(starts) else len(frames)
        start = index * 1000 // rate
        end = starts[n + 1] * 1000 // rate if n + 1 < len(starts) else duration
        shot = frames[index:following]
        size = len(shot)
        motion = sum(frame[4] for frame in shot[1:]) / max(1, size - 1)
        measured = {"meanRgb": [round(sum(frame[0][c] for frame in shot) / size) for c in range(3)],
                    "meanLuma": round(sum(f[1] for f in shot) / size, 4),
                    "centerLuma": round(sum(f[2] for f in shot) / size, 4),
                    "edgeLuma": round(sum(f[3] for f in shot) / size, 4),
                    "embeddedCaptionCues": sum(c["startMs"] < end and c["endMs"] > start for c in captions["cues"]),
                    "meanFrameChange": round(motion, 4), "openingCutScore": round(shot[0][4], 4),
                    **_audio_levels(pcm, start * 8, end * 8)}
        length = end - start
        pacing = "quick" if length < 1750 else "steady" if length < 4000 else "lingering"
        light = "dark" if measured["meanLuma"] < .3 else "bright" if measured["meanLuma"] > .7 else "mid-toned"
        motion_note = "little visible change" if motion < .025 else "visible change between sampled frames"
        audio_note = ("The clip has no audio track." if not probe["hasAudio"] else
                      "The sampled audio is mostly quiet." if (measured["quietFraction"] or 0) > .6 else
                      "A soundtrack is present.")
        note = f"A {pacing}, {light} shot with {motion_note}. {audio_note}"
        scenes.append({"startMs": start, "endMs": end, "durationMs": length, "measurements": measured,
                       "pacing": pacing, "interpretation": note})
    return {**{k: probe[k] for k in ("width", "height", "fps", "durationMs", "hasAudio", "captionTrack")},
            **({"decodedFrameCount": probe["frameCount"]} if count_frames else {}),
            "sha256": hashlib.sha256(raw).hexdigest(), "scenes": scenes,
            "measured": {"method": "rafii-rgb-audio-v1", "sampleIntervalMs": 125, "sampledFrameCount": len(frames),
                         "hasChangingFrames": any(f[4] > .001 for f in frames), "audioSampleRateHz": 8000 if pcm is not None else None,
                         "embeddedCaptions": captions,
                         **({"audioRhythm": _audio_rhythm(pcm, duration)} if include_audio_rhythm else {})},
            "inferences": ["Hard-cut candidates are estimates from consecutive sampled frames.",
                           "Pacing and lighting descriptions refer to relative duration, mean color and frame change."],
            "unavailable": ["Hook wording, speech, typography, product identity, camera direction and narrative intent require review.",
                            "Audience retention, conversion and other performance metrics require measured platform data."]}


def _frame_count(ms):
    return (ms * FPS + 500) // 1000


def picture_frame(raw, index):
    """Return one full-resolution PNG from the picture track of a saved MP4."""
    _bytes(raw)
    if type(index) is not int or not 0 <= index < _frame_count(MAX_DURATION_MS):
        _error("Choose a frame inside the saved video.")
    with ExitStack() as stack:
        stream = _source(stack, raw)
        png = _cmd("ffmpeg", [*_decode(), "-map", "0:v:0", "-an", "-sn", "-vf", f"select=eq(n\\,{index})",
                   "-frames:v", "1", "-map_metadata", "-1", "-c:v", "png", "-threads", "1",
                   "-f", "image2pipe", "pipe:1"], stream, time.monotonic() + 30, 6 * 1024 * 1024)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        _error("The requested frame is outside the saved video.")
    return png


def _srt_time(frames):
    ms = round(frames * 1000 / FPS)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _timeline(scenes, clips):
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES or not isinstance(clips, dict):
        _error("Choose between one and 32 scenes.")
    total, frame_start, seen, timeline = 0, 0, set(), []
    for scene in scenes:
        if not isinstance(scene, dict):
            _error("Each scene needs its own clip and duration.")
        sid, cid = scene.get("sceneId"), scene.get("clipId")
        if not isinstance(sid, str) or not 1 <= len(sid) <= 128 or sid in seen:
            _error("Use a unique ID for every scene.")
        if not isinstance(cid, str) or not 1 <= len(cid) <= 128 or cid not in clips:
            _error("A scene needs an available clip.", "creative_video_clip_missing", 409)
        length, trim, caption = scene.get("durationMs"), scene.get("trimStartMs", 0), scene.get("caption", "")
        if (type(length) is not int or not MIN_SCENE_MS <= length <= MAX_SCENE_MS
                or type(trim) is not int or not 0 <= trim < MAX_DURATION_MS):
            _error("Each scene needs a valid trim and a duration from 42 milliseconds to 8 seconds.")
        if not isinstance(caption, str) or len(caption) > 280 or any(ord(c) < 32 and c not in "\n\r\t" for c in caption):
            _error("Use a plain-text caption of up to 280 characters.")
        seen.add(sid)
        total += length
        if total > MAX_DURATION_MS:
            _error("Keep the timeline within 90 seconds.")
        frame_end = _frame_count(total)
        timeline.append({"sceneId": sid, "clipId": cid, "trimStartMs": trim, "caption": " ".join(caption.split()),
                         "startFrame": frame_start, "frameCount": frame_end - frame_start,
                         "startMs": round(frame_start * 1000 / FPS), "endMs": round(frame_end * 1000 / FPS)})
        frame_start = frame_end
    if set(clips) != {s["clipId"] for s in timeline}:
        _error("The supplied clips do not match the timeline.")
    if sum(len(_bytes(raw)) for raw in clips.values()) > 128 * 1024 * 1024:
        _error("The total size of the scene clips exceeds 128 MiB.", "creative_video_size_limit", 413)
    return timeline


def render_composition(scenes: list[dict], clips: dict[str, bytes], *, aspect_ratio="9:16") -> tuple[bytes, dict]:
    """Compose private clips on a 24fps timeline. Captions are a selectable MP4 timed-text track."""
    if not isinstance(aspect_ratio, str) or aspect_ratio not in SIZES:
        _error("Choose a vertical, landscape or square video.")
    timeline = _timeline(scenes, clips)
    width, height = SIZES[aspect_ratio]
    deadline = time.monotonic() + 180
    with ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="rafii-composition-")))
        sources = {key: _source(stack, raw) for key, raw in clips.items()}
        probes = {key: _probe(handle, deadline) for key, handle in sources.items()}
        has_audio = any(info["hasAudio"] for info in probes.values())
        video = stack.enter_context(tempfile.TemporaryFile())
        audio = stack.enter_context(tempfile.TemporaryFile())
        caption_lines = []
        for scene in timeline:
            cid = scene["clipId"]
            stream, info = sources[cid], probes[cid]
            frames = scene["frameCount"]
            first = _frame_count(scene["trimStartMs"])
            if first + frames > _frame_count(info["durationMs"]):
                _error("A scene runs past the end of its clip. Shorten its duration or trim.")
            scene["clipSha256"] = hashlib.sha256(clips[cid]).hexdigest()
            # Encoded Annex B scenes join without container padding or AAC
            # priming at cuts. Only this program creates the elementary stream.
            filters = (f"fps={FPS}:start_time=0:round=near,trim=start_frame={first}:end_frame={first + frames},"
                       f"setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease:"
                       f"force_divisible_by=2:reset_sar=1,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
            chunk = _cmd("ffmpeg", [*_decode(), "-map", f"0:{info['videoIndex']}", "-an", "-vf", filters,
                "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", "21", "-bf", "0",
                "-f", "h264", "pipe:1"], stream, deadline, MAX_MEDIA_BYTES - video.tell())
            if not chunk:
                _error("No frames were decoded for a scene.")
            video.write(chunk)
            if has_audio:
                # Each video frame owns exactly 2,000 stereo audio samples.
                expected_bytes = frames * (AUDIO_RATE // FPS) * 4
                pcm = b""
                if info["hasAudio"]:
                    offset = first * (AUDIO_RATE // FPS)
                    filters = (f"aresample={AUDIO_RATE}:async=1:first_pts=0,"
                               f"atrim=start_sample={offset}:end_sample={offset + expected_bytes // 4}")
                    pcm = _cmd("ffmpeg", [*_decode(), "-map", f"0:{info['audioIndex']}", "-vn", "-af", filters,
                        "-ar", str(AUDIO_RATE), "-ac", "2", "-f", "s16le", "pipe:1"], stream, deadline, expected_bytes)
                audio.write(pcm.ljust(expected_bytes, b"\x00"))
            if scene["caption"]:
                start = scene["startFrame"]
                caption_lines.append(f"{len(caption_lines) + 1}\n{_srt_time(start)} --> {_srt_time(start + frames)}\n"
                                     f"{html.escape(scene['caption'])}\n")
        video.seek(0)
        audio.seek(0)
        args = ["-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-max_alloc", "67108864",
                "-protocol_whitelist", "fd", "-f", "h264", "-framerate", str(FPS), "-fd", "0", "-i", "fd:"]
        # Raw H.264 timestamps may drift by one tick as a demuxer accumulates
        # rounded frame durations. Assign each encoded frame its exact slot.
        timestamps = f"setts=pts=N/({FPS}*TB):dts=N/({FPS}*TB):duration=1/({FPS}*TB)"
        passed, maps, codecs = [], ["-map", "0:v:0"], ["-c:v", "copy", "-bsf:v", timestamps, "-video_track_timescale", "24000"]
        if has_audio:
            passed.append(audio.fileno())
            args += ["-protocol_whitelist", "fd", "-f", "s16le", "-ar", str(AUDIO_RATE), "-ac", "2",
                     "-fd", str(audio.fileno()), "-i", "fd:"]
            maps += ["-map", "1:a:0"]
            codecs += ["-c:a", "aac", "-b:a", "128k", "-threads:a", "1"]
        if caption_lines:
            captions = _source(stack, ("\n".join(caption_lines) + "\n").encode())
            passed.append(captions.fileno())
            args += ["-protocol_whitelist", "fd", "-f", "srt", "-fd", str(captions.fileno()), "-i", "fd:"]
            maps += ["-map", f"{len(passed)}:s:0"]
            codecs += ["-c:s", "mov_text", "-disposition:s:0", "default"]
        output = directory / "composition.mp4"
        _cmd("ffmpeg", [*args, *maps, *codecs, "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart",
                        "-fs", str(MAX_MEDIA_BYTES), "-f", "mp4", str(output)], video, deadline, pass_fds=tuple(passed))
        if not 0 < output.stat().st_size <= MAX_MEDIA_BYTES:
            _error("The export exceeded the worker size limit.", "creative_video_size_limit", 413)
        with output.open("rb") as final:
            info = _probe(final, deadline, count=True)
            expected = sum(s["frameCount"] for s in timeline)
            ms = round(expected * 1000 / FPS)
            if (info["frameCount"] != expected or info["videoCodec"] != "h264" or info["width"] != width
                    or info["height"] != height or abs(info["durationMs"] - ms) > 1 or info["fps"] != FPS
                    or info["hasAudio"] != has_audio or (has_audio and abs((info["audioDurationMs"] or 0) - ms) > 24)
                    or info["captionTrack"] != bool(caption_lines)):
                _error("The exported stream does not match the approved timeline.", "creative_video_export_mismatch")
            timing = _cmd("ffprobe", ["-v", "error", *_input(), "-select_streams", "v:0", "-show_packets",
                          "-show_entries", "packet=pts,duration:stream=time_base", "-of", "json"], final, deadline, 512 * 1024)
            timing = json.loads(timing)
            packets = timing["packets"]
            if (timing["streams"][0]["time_base"] != "1/24000" or len(packets) != expected or
                    any(p.get("pts") != i * 1000 or p.get("duration") != 1000 for i, p in enumerate(packets))):
                _error("The export failed the frame timing check.", "creative_video_export_mismatch")
            cues = _caption_timing(final, info, deadline)["cues"]
            if cues != [{"startMs": s["startMs"], "endMs": s["endMs"]} for s in timeline if s["caption"]]:
                _error("The exported captions do not match their scenes.", "creative_video_export_mismatch")
            if has_audio:
                _cmd("ffmpeg", [*_decode(), "-map", "0:a:0", "-vn", "-f", "null", "-"], final, deadline)
            final.seek(0)
            raw = final.read()
    return raw, {**{key: info[key] for key in ("width", "height", "durationMs", "fps", "frameCount", "hasAudio", "audioDurationMs", "captionTrack")},
                 "mime": "video/mp4", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                 "aspectRatio": aspect_ratio, "scenes": timeline, "renderer": "rafii-composition-v1"}
