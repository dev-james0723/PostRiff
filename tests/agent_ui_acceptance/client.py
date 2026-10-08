"""Minimal HTTP client for acceptance checks (stdlib only): JSON calls, true incremental SSE reads, aborted requests.

Streaming uses `http.client` and `read1`, so a chunk is observed when the server flushes it (G04) and a check can close the
socket at a chosen point (client gone, aborted response after commit). Credentials travel only in headers, never in URLs.
"""
from __future__ import annotations

import http.client
import json
import socket
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .sse import SseReader

GUARD = {"X-PostRiff-Request": "founder-alpha"}


def new_key(prefix="g") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass
class Response:
    status: int
    headers: dict
    raw: bytes
    elapsed_ms: float = 0.0

    def json(self):
        try:
            return json.loads(self.raw.decode("utf-8")) if self.raw else None
        except ValueError:
            return None

    @property
    def code(self):
        body = self.json()
        return body.get("code") if isinstance(body, dict) else None

    def text(self, limit=400):
        return self.raw[:limit].decode("utf-8", "replace")


@dataclass
class Stream:
    status: int
    headers: dict
    reader: SseReader
    conn: object
    response: object
    started: float
    ended: float | None = None
    closed_early: bool = False
    terminal: dict | None = None
    error: str | None = None
    first_byte_at: float | None = None
    body_if_json: bytes | None = None
    events: list = field(default_factory=list)

    def iter_events(self, *, until=None, max_seconds=90.0, chunk=4096):
        """Yield events as they arrive; stops at a terminal ui.* event, EOF, `until(event)` or the deadline."""
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            try:
                data = self.response.read1(chunk)
            except (socket.timeout, TimeoutError):
                continue
            except (OSError, http.client.HTTPException) as error:
                self.error = type(error).__name__
                break
            if not data:
                self.events.extend(self.reader.close())
                self.ended = time.monotonic()
                break
            if self.first_byte_at is None:
                self.first_byte_at = time.monotonic()
            for event in self.reader.feed(data):
                self.events.append(event)
                yield event
                kind = event.get("event")
                if kind in ("ui.ready", "ui.failed", "ui.canceled", "ui.interrupted"):
                    self.terminal = event
                if until and until(event):
                    return
                if self.terminal is not None:
                    return

    def drain(self, **kw) -> list:
        return list(self.iter_events(**kw))

    def close(self):
        """Hang up (the client is gone). The server notices on its next write."""
        if self.ended is None:
            self.closed_early = True
        try:
            sock = getattr(self.conn, "sock", None)
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass


class Api:
    def __init__(self, base: str, *, timeout: float = 120.0, extra_headers: dict | None = None):
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("base must be an http(s) origin")
        self.base = base.rstrip("/")
        self.scheme, self.host, self.port = parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})

    def _conn(self, timeout):
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=timeout)

    def _headers(self, token, body, headers):
        out = {"Accept": "application/json", **GUARD, **self.extra_headers}
        if token:
            out["Authorization"] = f"Bearer {token}"
        if body is not None:
            out["Content-Type"] = "application/json"
        out.update(headers or {})
        return out

    @staticmethod
    def _encode(body):
        if body is None:
            return None
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def request(self, method, path, token=None, body=None, headers=None, timeout=None) -> Response:
        payload = self._encode(body)
        conn = self._conn(timeout or self.timeout)
        started = time.monotonic()
        try:
            conn.request(method, path, body=payload, headers=self._headers(token, payload, headers))
            response = conn.getresponse()
            raw = response.read()
            return Response(response.status, {k.lower(): v for k, v in response.getheaders()}, raw, round((time.monotonic() - started) * 1000, 2))
        finally:
            conn.close()

    def stream(self, method, path, token=None, body=None, headers=None, timeout=15.0) -> Stream:
        """Open a request and return before reading the body. Non-SSE answers (JSON errors) are read whole."""
        payload = self._encode(body)
        conn = self._conn(timeout)
        started = time.monotonic()
        conn.request(method, path, body=payload, headers=self._headers(token, payload, {"Accept": "text/event-stream", **(headers or {})}))
        response = conn.getresponse()
        heads = {k.lower(): v for k, v in response.getheaders()}
        stream = Stream(response.status, heads, SseReader(), conn, response, started)
        if not heads.get("content-type", "").startswith("text/event-stream"):
            stream.body_if_json = response.read()
            stream.ended = time.monotonic()
            conn.close()
        return stream

    def abort_after_send(self, method, path, token=None, body=None, headers=None, wait=0.0) -> None:
        """Send a complete request, then hang up without reading the answer (aborted response after commit)."""
        payload = self._encode(body)
        conn = self._conn(10)
        conn.request(method, path, body=payload, headers=self._headers(token, payload, headers))
        if wait:
            time.sleep(wait)
        try:
            conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        conn.close()
