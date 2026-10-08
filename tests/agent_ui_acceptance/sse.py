"""Incremental `text/event-stream` reader for acceptance checks (stdlib only; also used by scripts/agent_ui_live.py).

Bytes arrive in arbitrary network chunks: a frame or a UTF-8 character can be split anywhere. The reader decodes with an
incremental UTF-8 decoder (never per chunk), keeps a partial line buffer, and yields complete events only. It records the
monotonic arrival time of every chunk and of every completed event, so a check can prove frames arrived *before* the
response ended (G04) instead of trusting a buffered body.
"""
from __future__ import annotations

import codecs
import json
import time


class SseReader:
    def __init__(self, clock=time.monotonic):
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._buffer = ""
        self._fields: dict = {}
        self._data: list[str] = []
        self.clock = clock
        self.chunks: list[dict] = []        # {"at": monotonic, "bytes": n}
        self.events: list[dict] = []        # {"id", "event", "data" (parsed JSON or raw), "at", "raw"}
        self.comments = 0
        self.decode_errors = 0
        self.raw_tail = b""                 # last bytes of the previous chunk (split-character detection)
        self.splits_inside_character = 0

    def feed(self, chunk: bytes) -> list[dict]:
        at = self.clock()
        self.chunks.append({"at": at, "bytes": len(chunk)})
        if chunk and self.raw_tail and (chunk[0] & 0xC0) == 0x80:
            self.splits_inside_character += 1   # this read began inside a multi-byte character
        self.raw_tail = chunk[-4:] if chunk else self.raw_tail
        try:
            text = self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError:
            self.decode_errors += 1
            raise
        self._buffer += text
        out = []
        while True:
            cut = self._buffer.find("\n")
            if cut < 0:
                break
            line, self._buffer = self._buffer[:cut].rstrip("\r"), self._buffer[cut + 1:]
            event = self._line(line, at)
            if event is not None:
                out.append(event)
        return out

    def split_inside_character(self) -> bool:
        """True when at least one network read started in the middle of a UTF-8 character (the G04 split was observed)."""
        return self.splits_inside_character > 0

    def close(self) -> list[dict]:
        tail = self._decoder.decode(b"", final=True)
        self._buffer += tail
        out = []
        if self._buffer:
            event = self._line(self._buffer, self.clock())
            self._buffer = ""
            if event is not None:
                out.append(event)
        event = self._line("", self.clock())
        if event is not None:
            out.append(event)
        return out

    def _line(self, line: str, at: float):
        if line == "":
            if not self._data and not self._fields:
                return None
            raw = "\n".join(self._data)
            try:
                data = json.loads(raw) if raw else None
            except ValueError:
                data = raw
            event = {"id": self._fields.get("id"), "event": self._fields.get("event", "message"), "data": data, "at": at, "raw": raw,
                     "retry": self._fields.get("retry")}
            self._fields, self._data = {}, []
            self.events.append(event)
            return event
        if line.startswith(":"):
            self.comments += 1
            return None
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data.append(value)
        elif name in ("id", "event", "retry"):
            self._fields[name] = value
        return None


def parse_all(raw: bytes, split_at=None) -> SseReader:
    """Parse a complete body, optionally re-chunked at the given byte offsets (fragmentation tests)."""
    reader = SseReader()
    cuts = sorted(set(int(c) for c in (split_at or ()) if 0 < int(c) < len(raw)))
    start = 0
    for cut in cuts + [len(raw)]:
        reader.feed(raw[start:cut])
        start = cut
    reader.close()
    return reader
