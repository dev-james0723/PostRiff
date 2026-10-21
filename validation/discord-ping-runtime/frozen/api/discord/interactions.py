"""Vercel Python 3.12 A7a-0: one signed Discord PING endpoint, and nothing else.

Source-bound adapter/overlay, NOT deployed and NOT merged into Rafii.
"""
from http.server import BaseHTTPRequestHandler
import json
import os

from a7a0_ping_core import MAX_BODY_BYTES, Reject, settings_from_env, verify_ping

_ROUTE = '/api/discord/interactions'
_RESPONSE = b'{"type":1}'


class handler(BaseHTTPRequestHandler):
    server_version = 'Ping-only'
    sys_version = ''

    # Silence inherited request logging, especially user/authorization data.
    def log_message(self, fmt, *args):
        return

    def log_request(self, code='-', size='-'):
        return

    def _write(self, status: int, payload: bytes | None = None):
        if payload is None:
            payload = b'{}'
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def _not_available(self):
        self._write(405 if self.path == _ROUTE else 404)

    def do_GET(self):
        self._not_available()

    def do_HEAD(self):
        self._not_available()

    def do_OPTIONS(self):
        self._not_available()

    def do_PUT(self):
        self._not_available()

    def do_PATCH(self):
        self._not_available()

    def do_DELETE(self):
        self._not_available()

    def do_TRACE(self):
        self._not_available()

    def do_CONNECT(self):
        self._not_available()

    def do_POST(self):
        if self.path != _ROUTE:
            self._write(404)
            return
        try:
            if self.headers.get('Transfer-Encoding') is not None:
                raise Reject(400)
            if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                raise Reject(415)
            sizes = self.headers.get_all('Content-Length') or []
            if len(sizes) != 1:
                raise Reject(400)
            token = sizes[0]
            if not isinstance(token, str) or not token.isascii() or not token.isdecimal() or len(token) > 5:
                raise Reject(400)
            length = int(token)
            if not 1 <= length <= MAX_BODY_BYTES:
                raise Reject(413)
            # Environment only. NEVER Host/X-Forwarded-Host. CDN HTTPS must be
            # independently attested on the future, explicitly approved host.
            config = settings_from_env(os.environ)
            timestamps = self.headers.get_all('X-Signature-Timestamp') or []
            signatures = self.headers.get_all('X-Signature-Ed25519') or []
            if len(timestamps) != 1 or len(signatures) != 1:
                raise Reject(401)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise Reject(400)
            result = verify_ping(raw, timestamps[0], signatures[0], config)
            if result != {'type': 1}:
                raise Reject(503)
            self._write(200, _RESPONSE)
        except Reject as exc:
            self._write(exc.status)
        except (OSError, ValueError, TypeError):
            # Never expose details from runtime, headers, parsing or signature.
            self._write(400)
