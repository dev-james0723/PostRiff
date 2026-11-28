"""Local Studio's byte-in/byte-out adapter to Rafii's native video engine."""
from __future__ import annotations

import base64
import binascii
from contextlib import ExitStack
import hashlib
from importlib.util import find_spec
import json
from pathlib import Path
import re
import signal
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2 import creative_video_contact_sheet as sheet
from postriff_phase2 import creative_video_media as media
from postriff_phase2.creative_video_blueprint import adapt, text_field
from postriff_phase2.creative_video_media import MAX_SCENES, analyze_reference, render_composition
from postriff_phase2.creative_video_reference_signals import _frame, reference_signals

SAMPLE_DIR = ROOT / "docs/creative-intelligence/examples/timer-study"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 45 * 1024 * 1024
UPLOAD_ID = re.compile(r"upload-[0-9a-f]{64}")
# These are the only filesystem assets the local worker accepts. A project
# supplies identifiers. It cannot nominate an input path or a remote source.
SAMPLE_CLIPS = {
    "original-1": (SAMPLE_DIR / "original-1.mp4", "A turn to begin", 1250),
    "original-2": (SAMPLE_DIR / "original-2.mp4", "Time in motion", 1500),
    "original-3": (SAMPLE_DIR / "original-3.mp4", "Find your tempo", 1250),
    "revised-intro": (SAMPLE_DIR / "revised-intro.mp4", "Alternate opening", 1250),
}


def sample_reference():
    return (SAMPLE_DIR / "reference.mp4").read_bytes()


def sample_clip(clip_id):
    if not isinstance(clip_id, str) or clip_id not in SAMPLE_CLIPS:
        raise AlphaError("Choose a production clip from the sample library.", 404)
    return SAMPLE_CLIPS[clip_id][0].read_bytes()


def sample_timeline():
    saved = json.loads((SAMPLE_DIR / "timeline.json").read_text())
    purposes = ("Opening hook", "Demonstration", "Call to action")
    scenes = [
        {**scene, "name": SAMPLE_CLIPS[scene["clipId"]][1], "purpose": purpose,
         "direction": "", "trimStartMs": 0}
        for scene, purpose in zip(saved["versions"][0], purposes)
    ]
    clips = [{"clipId": key, "name": name, "durationMs": duration}
             for key, (_, name, duration) in SAMPLE_CLIPS.items()]
    return {"name": "Timer study", "title": "Timer study", "aspectRatio": saved["aspectRatio"],
            "clips": clips, "scenes": scenes}


def decoded_file(encoded):
    if not isinstance(encoded, str) or not encoded:
        raise AlphaError("Choose a media file.")
    if len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
        raise AlphaError("Use a file of up to 16 MiB.", 413)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise AlphaError("Choose a readable media file.") from None
    if not 0 < len(data) <= MAX_FILE_BYTES:
        raise AlphaError("Use a file of up to 16 MiB.", 413)
    return data


def selected_reference(body):
    return decoded_file(body["file"]) if "file" in body else sample_reference()


def analyze(raw):
    measured = analyze_reference(raw)
    measured["overlaySignals"] = reference_signals(raw, measured)
    return measured


def ffmpeg_thumbnails(raw, shots):
    """Use the same bounded frame reader when Finder's Python lacks Pillow."""
    frames = []
    deadline = time.monotonic() + 15
    with ExitStack() as stack:
        source = media._source(stack, raw)
        for shot in shots:
            start, end = shot["startMs"], shot["endMs"]
            image = {"timeMs": None, "jpeg": None}
            for target in dict.fromkeys(((start + end) // 2, start)):
                try:
                    ppm, pts, width, height = _frame(source, target, deadline, color=True, edge=320)
                except ValueError:
                    continue
                if start <= pts < end:
                    jpeg = media._cmd("ffmpeg", ["-nostdin", "-v", "error", "-xerror", "-max_alloc", "67108864",
                        "-protocol_whitelist", "fd", "-f", "image2pipe", "-c:v", "ppm",
                        "-fd", "0", "-i", "fd:", "-frames:v", "1", "-c:v", "mjpeg", "-threads", "1",
                        "-q:v", "4", "-f", "image2pipe", "pipe:1"], media._source(stack, ppm), deadline, 256 * 1024)
                    image = {"timeMs": pts, "width": width, "height": height, "jpeg": base64.b64encode(jpeg).decode("ascii")}
                    break
            frames.append({**shot, **image})
    return frames


def overview_windows(raw, page):
    """Divide the visual timeline into up to eight windows, including uncut footage."""
    media._bytes(raw)
    deadline = time.monotonic() + 15
    with ExitStack() as stack:
        source = media._source(stack, raw)
        probe = media._probe(source, deadline)
        # Decode up to eight real pictures. Long/high-resolution clips need no
        # full frame count. Container estimates and duplicated CFR frames would
        # overstate the useful samples for short or variable-rate footage.
        frames = media._cmd("ffmpeg", [*media._decode(), "-map", f"0:{probe['videoIndex']}",
            "-an", "-sn", "-dn", "-vf", "scale=1:1,format=gray", "-fps_mode", "passthrough",
            "-frames:v", "8", "-c:v", "rawvideo", "-threads", "1", "-f", "rawvideo", "pipe:1"],
            source, deadline, 8)
    duration = probe["durationMs"]
    count = min(len(frames), duration)
    if count == 0:
        raise AlphaError("There were no video frames to inspect.", 422)
    first = page * sheet.PAGE_SIZE
    if first >= count:
        raise AlphaError("Choose an available page of overview samples.", 404)
    return [{"intervalIndex": i, "startMs": duration*i//count, "endMs": duration*(i+1)//count}
            for i in range(first, min(first + sheet.PAGE_SIZE, count))], count


def reference_frames(body):
    raw = selected_reference(body)
    digest = hashlib.sha256(raw).hexdigest()
    if body.get("referenceSha256") != digest:
        raise AlphaError("Analyze and relink the same reference before viewing its shots.", 409)
    page = body.get("page")
    if type(page) is not int or page < 0:
        raise AlphaError("Choose an available page of reference shots.", 404)
    coverage = body.get("coverage", "scenes")
    if coverage == "scenes":
        # Measure times again from the authorized bytes. Saved project
        # metadata and indices from the browser cannot request arbitrary frames.
        analysis = analyze_reference(raw, include_audio_rhythm=False)
        shots, total = sheet.windows(analysis, page)
    elif coverage == "intervals":
        shots, total = overview_windows(raw, page)
    else:
        raise AlphaError("Choose shot boundaries or evenly spaced overview samples.")
    frames = sheet.decode(raw, shots) if find_spec("PIL") else ffmpeg_thumbnails(raw, shots)
    return {"referenceSha256": digest, "page": page, "pageCount": (total + sheet.PAGE_SIZE - 1) // sheet.PAGE_SIZE,
            "coverage": coverage, "totalSamples": total, **({"totalShots": total} if coverage == "scenes" else {}),
            "frames": frames}


def blueprint(body):
    brief = text_field(body.get("brief"), "creative brief", 1200)
    # These fields have campaign scope in the local editor. Only the
    # authenticated workspace can resolve an approved Brand Brain revision.
    context = {key: text_field(body.get(key, ""), key, limit, empty=True)
               for key, limit in (("brand", 120), ("subject", 120), ("audience", 160))}
    raw = selected_reference(body)
    if "referenceSha256" in body and body["referenceSha256"] != hashlib.sha256(raw).hexdigest():
        raise AlphaError("The selected reference changed. Analyze it again.", 409)
    measured = analyze(raw)
    scenes = adapt({"brief": brief}, measured, context)
    return {"referenceSha256": measured["sha256"], "scenes": [
        {**shot, "name": shot["purpose"], "trimStartMs": 0} for shot in scenes
    ]}


def decode_soundtrack(data):
    """Decode a single local audio stream and measure its actual sample count."""
    if data[4:8] == b"ftyp":
        options = media._input()
    else:
        # Restrict probing to these self-contained audio containers. No
        # playlist, external URL or unrecognized demuxer can be opened.
        options = ["-protocol_whitelist", "fd", "-format_whitelist", "mp3,aac,wav",
                   "-probesize", "2097152", "-analyzeduration", "5000000",
                   "-max_streams", "4", "-fd", "0", "-i", "fd:"]
    deadline = time.monotonic() + 15
    with ExitStack() as stack:
        stream = media._source(stack, data)
        raw = media._cmd("ffprobe", ["-v", "error", "-max_alloc", "67108864", *options,
            "-show_entries", "stream=codec_name,codec_type,channels,sample_rate:stream_disposition=attached_pic",
            "-of", "json"], stream, deadline, 16384)
        entries = json.loads(raw).get("streams", [])
        tracks = [s for s in entries if s.get("codec_type") == "audio"]
        covers = [s for s in entries if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic")]
        codecs = ("aac", "mp3", "pcm_u8", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le")
        if (len(tracks) != 1 or len(tracks) + len(covers) != len(entries) or tracks[0].get("codec_name") not in codecs
                or not 1 <= tracks[0].get("channels", 0) <= 8 or not 0 < int(tracks[0].get("sample_rate", 0)) <= 192000):
            raise AlphaError("Choose a single audio track in MP3, AAC or PCM WAV format.", 415)
        # An extra millisecond distinguishes an overlong input even when its
        # declared duration is missing or inaccurate (e.g. VBR or raw AAC).
        limit = media.MAX_DURATION_MS * media.AUDIO_RATE // 1000 * 4
        pcm = media._cmd("ffmpeg", ["-nostdin", "-v", "error", "-xerror", "-max_alloc", "67108864",
            "-threads", "1", *options, "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", "90.001",
            "-ar", str(media.AUDIO_RATE), "-ac", "2", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
            stream, deadline, limit + 256)
    if not 0 < len(pcm) <= limit:
        raise AlphaError("Choose audio up to 90 seconds long.", 422)
    duration = round(len(pcm) * 1000 / (4 * media.AUDIO_RATE))
    return pcm, {"audioId": "audio-" + hashlib.sha256(data).hexdigest(), "durationMs": duration}


def replace_soundtrack(video, receipt, pcm, audio_info):
    # The verified cut's picture and timed text packets pass through untouched.
    # Each 24fps picture frame corresponds to exactly 2,000 stereo samples.
    length = receipt["frameCount"] * (media.AUDIO_RATE // media.FPS) * 4
    deadline = time.monotonic() + 25
    with ExitStack() as stack:
        source = media._source(stack, video)
        audio = media._source(stack, pcm[:length].ljust(length, b"\0"))
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="rafii-studio-audio-")))
        output = directory / "soundtrack.mp4"
        args = ["-nostdin", "-v", "error", "-xerror", "-max_alloc", "67108864", *media._input(),
                "-protocol_whitelist", "fd", "-f", "s16le", "-ar", str(media.AUDIO_RATE), "-ac", "2",
                "-fd", str(audio.fileno()), "-i", "fd:", "-map", "0:v:0", "-map", "1:a:0", "-map", "0:s?",
                "-c:v", "copy", "-video_track_timescale", "24000", "-c:s", "copy", "-c:a", "aac", "-b:a", "128k",
                "-threads:a", "1", "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart",
                "-fs", str(media.MAX_MEDIA_BYTES), "-f", "mp4", str(output)]
        media._cmd("ffmpeg", args, source, deadline, pass_fds=(audio.fileno(),))
        if not 0 < output.stat().st_size <= media.MAX_MEDIA_BYTES:
            raise AlphaError("The soundtrack export exceeds the worker size limit.", 413)
        with output.open("rb") as saved:
            info = media._probe(saved, deadline, count=True)
            cues = media._caption_timing(saved, info, deadline)["cues"]
            expected = [{"startMs": s["startMs"], "endMs": s["endMs"]} for s in receipt["scenes"] if s["caption"]]
            if (any(info[key] != receipt[key] for key in ("frameCount", "durationMs", "width", "height", "fps", "captionTrack"))
                    or not info["audioDurationMs"] or abs(info["audioDurationMs"] - info["durationMs"]) > 2
                    or cues != expected):
                raise AlphaError("The soundtrack export did not match the edit timeline.", 422)
            saved.seek(0)
            result = saved.read()
    return result, {**receipt, "hasAudio": True, "audioDurationMs": info["audioDurationMs"],
                    "soundtrack": audio_info, "bytes": len(result), "sha256": hashlib.sha256(result).hexdigest()}


def render_timeline(scenes, *, uploads=None, aspect_ratio="9:16"):
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise AlphaError("Choose between one and 32 scenes.")
    provided = {} if uploads is None else uploads
    if not isinstance(provided, dict) or len(provided) > len(scenes):
        raise AlphaError("Supply only the footage used by this cut.")
    clip_ids = set()
    for scene in scenes:
        clip_id = scene.get("clipId") if isinstance(scene, dict) else None
        if not isinstance(clip_id, str) or (clip_id not in SAMPLE_CLIPS and not UPLOAD_ID.fullmatch(clip_id)):
            raise AlphaError("Assign authorized production footage to each scene.", 409)
        clip_ids.add(clip_id)
    if set(provided) != clip_ids.difference(SAMPLE_CLIPS):
        raise AlphaError("Relink the footage used in this cut.", 409)
    total = 0
    for key, data in provided.items():
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_FILE_BYTES:
            raise AlphaError("Each production file must be within 16 MiB.", 413)
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise AlphaError("Use up to 32 MiB of imported footage in a single cut.", 413)
        if key != "upload-" + hashlib.sha256(data).hexdigest():
            raise AlphaError("The relinked video does not match its original file.", 409)
    clips = {**provided, **{key: sample_clip(key) for key in clip_ids.intersection(SAMPLE_CLIPS)}}
    return render_composition(scenes, clips, aspect_ratio=aspect_ratio)


def dispatch(body):
    if not isinstance(body, dict):
        raise AlphaError("Supply a Studio request.")
    action = body.get("action")
    if action == "sample":
        return sample_timeline()
    if action == "analyze":
        return analyze(selected_reference(body))
    if action == "reference-frames":
        return reference_frames(body)
    if action == "inspect":
        info = analyze_reference(decoded_file(body.get("file")))
        return {"clipId": "upload-" + info["sha256"], "durationMs": info["durationMs"]}
    if action == "inspect-audio":
        _, info = decode_soundtrack(decoded_file(body.get("file")))
        return info
    if action == "blueprint":
        return blueprint(body)
    if action == "render":
        supplied = body.get("uploads", {})
        if not isinstance(supplied, dict) or len(supplied) > MAX_SCENES:
            raise AlphaError("Supply only the footage used by this cut.")
        uploads = {key: decoded_file(value) for key, value in supplied.items()}
        soundtrack = None
        if "soundtrack" in body:
            soundtrack = body["soundtrack"]
            if not isinstance(soundtrack, dict) or set(soundtrack) != {"audioId", "file"}:
                raise AlphaError("Relink an authorized soundtrack.")
            data = decoded_file(soundtrack["file"])
            if len(data) + sum(map(len, uploads.values())) > MAX_UPLOAD_BYTES:
                raise AlphaError("Use up to 32 MiB of imported media in a single cut.", 413)
            if soundtrack["audioId"] != "audio-" + hashlib.sha256(data).hexdigest():
                raise AlphaError("The relinked soundtrack does not match the project's audio file.", 409)
            pcm, audio_info = decode_soundtrack(data)
        raw, receipt = render_timeline(body.get("scenes"), uploads=uploads, aspect_ratio=body.get("aspectRatio", "9:16"))
        if soundtrack is not None:
            raw, _ = replace_soundtrack(raw, receipt, pcm, audio_info)
        return raw
    raise AlphaError("Choose a supported Studio action.")


def main():
    try:
        request = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(request) > MAX_REQUEST_BYTES:
            raise AlphaError("This cut exceeds the local request size limit.", 413)
        try:
            body = json.loads(request)
        except (ValueError, RecursionError):
            raise AlphaError("Supply a valid Studio request.") from None
        result = dispatch(body)
        sys.stdout.buffer.write(result if isinstance(result, bytes) else json.dumps(result).encode())
        return 0
    except AlphaError as error:
        print(json.dumps({"code": error.code, "message": str(error), "status": error.status}), file=sys.stderr)
    except OSError:
        print(json.dumps({"code": "studio_media_unavailable", "message": "The local media worker is unavailable.",
                          "status": 503}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    def terminate(signum, _frame):
        # Unwind the native worker's subprocess and temporary-file managers.
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())
