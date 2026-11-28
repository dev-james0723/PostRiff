"""Local output-decoder readiness and passive health observations from existing provider requests."""
from functools import lru_cache
import os
from pathlib import Path
import shutil
import time
from threading import Lock

from postriff_alpha.domain import AlphaError
from . import creative_video_media as media


@lru_cache(maxsize=4)
def _decode_probe(executables, minute):
    """Cache by actual executable identity and minute, including bounded temporary failures."""
    # Original synthetic MP4: six 16×16 black H.264 frames and 250 ms of silent AAC.
    # Exercise the same fd-only demuxer, decoding and scaling used to verify a user's output.
    deadline = time.monotonic() + 3
    try:
        with Path(__file__).with_name("creative_video_decoder_probe.mp4").open("rb") as source:
            info = media._probe(source, deadline, count=True)
            if (info["videoCodec"], info["frameCount"], info["hasAudio"]) != ("h264", 6, True):
                return False
            media._cmd("ffmpeg", [*media._decode(), "-map", "0:v:0", "-map", "0:a:0",
                "-vf", "fps=8,scale=32:18:flags=area,format=rgb24", "-af", "aresample=8000",
                "-f", "null", "-"], source, deadline)
        return True
    except (AlphaError, OSError):
        return False


def output_decoder_ready():
    fingerprints = []
    for tool in ("ffmpeg", "ffprobe"):
        binary = shutil.which(tool)
        if not binary:
            return False
        try:
            stat = os.stat(binary)
        except OSError:
            return False
        fingerprints.append((binary, stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size))
    return _decode_probe(tuple(fingerprints), int(time.monotonic() // 60))


class WorkerHealth:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._items = {}
        self._lock = Lock()

    def observe(self, scope, status):
        if scope is None:
            return
        now = self.clock()
        with self._lock:
            if status == 429 or status == 503:
                self._items[scope] = (now + 30, now)
            elif status in (None, 500, 502, 504):
                open_until, previous = self._items.get(scope, (0, None))
                if previous is not None and now - previous <= 60:
                    open_until = now + 30
                self._items[scope] = (open_until, now)
            elif status in (200, 201, 202, 204):
                # A successful same-operation poll is useful evidence after a hold, but does not lift a live throttle.
                if self._items.get(scope, (0, 0))[0] <= now:
                    self._items.pop(scope, None)
            if len(self._items) > 128:
                self._items = {key: entry for key, entry in self._items.items() if now - entry[1] <= 60}

    def on_hold(self, scope):
        with self._lock:
            return self._items.get(scope, (0, 0))[0] > self.clock()


worker_health = WorkerHealth()
