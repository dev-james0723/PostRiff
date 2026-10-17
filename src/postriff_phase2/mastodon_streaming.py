"""Explicit foreground SSE windows; no private-content persistence or model egress."""
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from .mastodon_protocol import ID
from .net_guard import public_host

MAX_BYTES = 262144
MAX_EVENTS = 64


def bound_origin(instance, advertised):
    """Freeze only this issuer's origin or a child hostname, never arbitrary hosts."""
    try:
        value = urlsplit(advertised)
        host = public_host(value.hostname)
        if (value.scheme not in ('https', 'wss') or value.username or value.password or value.port is not None
                or value.path not in ('', '/') or value.query or value.fragment
                or not (host == instance or host.endswith('.' + instance))): return None
        return 'https://' + host
    except (TypeError, ValueError, AlphaError):
        return None


def project(event, value):
    # Private status text belongs only in the requesting member's ephemeral UI.
    # No account biography, image URL, token or arbitrary nested server field.
    if event == 'delete':
        identifier = str(value)
        return {'event': event, 'id': identifier} if ID.fullmatch(identifier) else None
    if event not in ('update', 'status.update', 'notification') or not isinstance(value, dict): return None
    if not ID.fullmatch(str(value.get('id', ''))): return None
    result = {'event': event, 'id': str(value['id'])}
    status = value.get('status') if event == 'notification' else value
    if event == 'notification':
        kind = value.get('type')
        if kind not in ('mention', 'status', 'reblog', 'follow', 'follow_request', 'favourite', 'poll', 'update', 'admin.sign_up', 'admin.report'): return None
        result['type'] = kind
    if isinstance(status, dict) and ID.fullmatch(str(status.get('id', ''))):
        result['postId'] = str(status['id'])
        if status.get('visibility') in ('public', 'unlisted', 'private', 'direct'):
            result['visibility'] = status['visibility']
        text = status.get('content')
        if isinstance(text, str): result['excerpt'] = html.unescape(re.sub(r'<[^>]+>', '', text))[:1000]
    return result


def parse_events(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES: raise AlphaError('Streaming response limit exceeded.', 502)
    try: text = raw.decode('utf-8')
    except UnicodeError: raise AlphaError('Invalid streaming encoding.', 502) from None
    rows, kind, data = [], '', []
    # A partial last event has no delimiter and cannot be treated as accepted.
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')[:-1]:
        if not line:
            if kind and data:
                try: value = json.loads('\n'.join(data))
                except (ValueError, RecursionError): value = None
                item = project(kind, value)
                if item: rows.append(item)
                if len(rows) >= MAX_EVENTS: break
            kind, data = '', []
        elif line.startswith('event:'): kind = line[6:].lstrip(' ')
        elif line.startswith('data:'): data.append(line[5:].lstrip(' '))
    return rows


def pinned_window(origin, access_token, *, resolver=socket.getaddrinfo, seconds=3):
    """Connect once to validated public DNS answers, original TLS host, no redirects."""
    if type(seconds) not in (int, float) or not 0 < seconds <= 3: raise AlphaError('Use a bounded streaming window.', 400)
    if not isinstance(access_token, str) or not 1 <= len(access_token) <= 16384 or any(c.isspace() or ord(c) < 32 for c in access_token):
        raise AlphaError('This streaming connection needs fresh authorization.', 409)
    parsed = urlsplit(origin)
    host = public_host(parsed.hostname)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port is not None
            or parsed.path or parsed.query or parsed.fragment): raise AlphaError('Invalid streaming origin.', 400)
    deadline = time.monotonic() + seconds
    from .net_guard import _public_answers, request_deadline
    try:
        with request_deadline(seconds):
            answers = _public_answers(resolver, host)
    except OSError: raise AlphaError('Streaming DNS is unavailable.', 503) from None
    addresses = []
    for answer in answers:
        try: address = ipaddress.ip_address(answer[4][0])
        except (ValueError, TypeError, IndexError): raise AlphaError('Invalid streaming address.', 502) from None
        if not address.is_global or address.is_multicast: raise AlphaError('Streaming address is not public.', 502)
        addresses.append(str(address))
    if not addresses: raise AlphaError('Streaming DNS is unavailable.', 503)
    connection = http.client.HTTPSConnection(host, timeout=seconds, context=ssl.create_default_context())
    chunks, total, response = [], 0, None
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0: raise TimeoutError('Window complete')
        return value
    try:
        raw_socket = socket.create_connection((addresses[0], 443), timeout=remaining())
        try:
            raw_socket.settimeout(remaining())
            connection.sock = connection._context.wrap_socket(raw_socket, server_hostname=host)
        except Exception: raw_socket.close(); raise
        connection.sock.settimeout(remaining())
        connection.request('GET', '/api/v1/streaming/user', headers={'Accept': 'text/event-stream', 'Authorization': 'Bearer ' + access_token})
        connection.sock.settimeout(remaining())
        wire_socket = connection.sock
        response = connection.getresponse()
        if response.status != 200:
            return {'status': response.status, 'events': [], 'retryAfter': response.getheader('Retry-After')}
        if response.getheader('Content-Type', '').split(';', 1)[0].strip().lower() != 'text/event-stream':
            raise AlphaError('This endpoint did not expose compatible server-sent events.', 502)
        try:
            while total <= MAX_BYTES:
                wire_socket.settimeout(remaining())
                chunk = response.read1(min(8192, MAX_BYTES + 1 - total))
                if not chunk: break
                chunks.append(chunk); total += len(chunk)
        except TimeoutError:
            pass  # Headers proved an SSE connection; only fully received events are returned.
        if total > MAX_BYTES: raise AlphaError('Streaming response limit exceeded.', 502)
        return {'status': 200, 'events': parse_events(b''.join(chunks)), 'windowSeconds': seconds}
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise AlphaError('This server streaming endpoint is temporarily unavailable.', 503) from None
    finally:
        if response is not None: response.close()
        connection.close()


def read_window(provider, session):
    frozen = session.get('capabilities')
    frozen = frozen if isinstance(frozen, dict) else {}
    origin = bound_origin(session['instance'], frozen.get('streamingUrl'))
    if not origin:
        return {'state': 'unsupported', 'events': [], 'reason': 'No issuer-bound streaming origin was saved at connection. Reconnect or use bounded notifications reads.'}
    transport = getattr(provider, 'streaming_transport', None)
    result = transport(origin, session['at']) if transport else pinned_window(origin, session['at'], resolver=provider.resolver)
    if result.get('status') == 200:
        return {'state': 'connected_window', 'events': result.get('events', [])[:MAX_EVENTS], 'windowSeconds': 3,
                'coverage': 'Foreground live window only; events may be missed between windows. Read notifications to backfill.',
                'retention': 'Not persisted and not sent to AI or analytics.'}
    return {'state': 'unsupported' if result.get('status') in (404, 410) else 'limited' if result.get('status') == 429 else 'unavailable',
            'events': [], 'retryAfter': result.get('retryAfter'), 'reason': 'No compatible stream was confirmed; use bounded account reads.'}
