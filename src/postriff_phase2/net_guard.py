"""Public HTTPS guard and pinned transport for customer-selected provider hosts."""
import ipaddress
import http.client
import json
import re
import socket
import ssl
import time
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from functools import wraps
from threading import BoundedSemaphore
from urllib.parse import urlencode, urlsplit
from postriff_alpha.domain import AlphaError

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".invalid", ".test", ".example", ".onion")
_REQUEST_DEADLINE = ContextVar('public_provider_request_deadline', default=None)
_SYSTEM_RESOLVER = socket.getaddrinfo
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix='public-provider-dns')
_DNS_SLOTS = BoundedSemaphore(8)


@contextmanager
def request_deadline(seconds):
    if type(seconds) not in (int, float) or not 0 < seconds <= 20:
        raise ValueError('Use a bounded request deadline.')
    existing = _REQUEST_DEADLINE.get()
    until = time.monotonic() + seconds
    token = _REQUEST_DEADLINE.set(min(existing, until) if existing is not None else until)
    try:
        yield
    finally:
        _REQUEST_DEADLINE.reset(token)


def _request_remaining():
    until = _REQUEST_DEADLINE.get()
    remaining = 20 if until is None else min(20, until - time.monotonic())
    if remaining <= 0:
        raise AlphaError('The instance verification window ended. Try again later.', 503)
    return remaining


def _public_answers(resolver, host):
    if resolver is not _SYSTEM_RESOLVER:
        return resolver(host, 443, type=socket.SOCK_STREAM)  # Explicit injected test transport.
    slots = _DNS_SLOTS
    if not slots.acquire(blocking=False):
        raise AlphaError('Instance DNS verification is busy. Try again later.', 503)
    try:
        future = _DNS_EXECUTOR.submit(resolver, host, 443, type=socket.SOCK_STREAM)
    except Exception:
        slots.release()
        raise
    # Running OS calls cannot be interrupted. Keep their capacity reserved
    # until they actually finish; do not create unbounded replacement threads.
    future.add_done_callback(lambda _future: slots.release())
    try:
        return future.result(timeout=min(5, _request_remaining()))
    except FutureTimeout as error:
        future.cancel()
        raise AlphaError('Instance DNS verification timed out. Try again later.', 503) from error


def _bounded_public_transport(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        with request_deadline(20):
            return function(*args, **kwargs)
    return bounded


def public_host(value, *, message="Enter a server name such as mastodon.social."):
    """A bare public DNS name, lower-cased. Accepts a pasted https:// URL or an @user@host address."""
    host = (value or "").strip().lower() if isinstance(value, str) else ""
    if host.startswith("https://"):
        host = host[len("https://"):]
    host = host.split("/", 1)[0].rsplit("@", 1)[-1].rstrip(".")
    if not host or len(host) > 253 or "." not in host or ":" in host:
        raise AlphaError(message, 400)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AlphaError(message, 400)
    labels = host.split(".")
    if not all(_LABEL.match(label) for label in labels) or labels[-1].isdigit():
        raise AlphaError(message, 400)
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise AlphaError(message, 400)
    return host


def assert_public(host, resolver=socket.getaddrinfo):
    try:
        answers = _public_answers(resolver, host)
    except (OSError, UnicodeError) as error:
        raise AlphaError("That server can't be reached.", 400) from error
    if not answers:
        raise AlphaError("That server can't be reached.", 400)
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (ValueError, IndexError, TypeError) as error:
            raise AlphaError("That server address isn't allowed.", 400) from error
        if not address.is_global or address.is_multicast:
            raise AlphaError("That server address isn't allowed.", 400)
    return host


def public_https_url(url, resolver=socket.getaddrinfo):
    """An https URL on a public host, default port, no credentials; returned unchanged."""
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        port = parts.port if parts else None
    except ValueError:
        parts, port = None, None
    if not parts or parts.scheme != "https" or not parts.hostname or parts.username or parts.password or port not in (None, 443):
        raise AlphaError("The provider returned an address Rafii can't use.", 502)
    assert_public(public_host(parts.hostname, message="The provider returned an address Rafii can't use."), resolver)
    return url


@_bounded_public_transport
def pinned_public_json_transport(method, url, headers=None, form=None, body=None, data=None,
                                 *, resolver=socket.getaddrinfo):
    """HTTPS request to a public address resolved once, with TLS verified for the original host.

    This avoids the validation/connect DNS race for user-selected Pixelfed instances.
    Redirects are returned as responses and never followed. No credentials go to a new host.
    """
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        port = parts.port if parts else None
    except ValueError:
        parts, port = None, None
    if (not parts or parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or port not in (None, 443) or parts.fragment):
        raise AlphaError("The instance address is not allowed.", 400)
    host = public_host(parts.hostname)
    try:
        answers = _public_answers(resolver, host)
    except (OSError, UnicodeError) as error:
        raise AlphaError("That server can't be reached.", 400) from error
    addresses = []
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (ValueError, IndexError, TypeError) as error:
            raise AlphaError("That server address isn't allowed.", 400) from error
        if not address.is_global or address.is_multicast:
            raise AlphaError("That server address isn't allowed.", 400)
        addresses.append(str(address))
    if not addresses:
        raise AlphaError("That server can't be reached.", 400)
    raw_upload = data
    payload = (data if data is not None else urlencode(form).encode() if form is not None
               else json.dumps(body).encode() if body is not None else None)
    request_headers = {"Accept": "application/json", **(headers or {})}
    if raw_upload is not None and not any(key.lower() == "content-type" for key in request_headers):
        raise AlphaError("An upload needs a content type.", 500)
    if form is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        request_headers["Content-Type"] = "application/json"
    conn = http.client.HTTPSConnection(host, timeout=_request_remaining(), context=ssl.create_default_context())
    response = None
    try:
        # HTTPSConnection.request will use this already connected socket, so no second DNS lookup occurs.
        raw_socket = socket.create_connection((addresses[0], 443), timeout=_request_remaining())
        try:
            raw_socket.settimeout(_request_remaining())
            conn.sock = conn._context.wrap_socket(raw_socket, server_hostname=host)
        except Exception:
            raw_socket.close()
            raise
        conn.sock.settimeout(_request_remaining())
        conn.request(method, (parts.path or "/") + ("?" + parts.query if parts.query else ""),
                     body=payload, headers=request_headers)
        conn.sock.settimeout(_request_remaining())
        wire_socket = conn.sock
        response = conn.getresponse()
        chunks, received = [], 0
        while received <= 262144:
            if wire_socket is not None:
                wire_socket.settimeout(_request_remaining())
            else:
                _request_remaining()
            chunk = response.read1(min(8192, 262145 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        raw = b''.join(chunks)
        if len(raw) > 262144:
            raise AlphaError("Provider response limit exceeded.", 502)
        content_type = response.getheader("content-type", "").split(";", 1)[0].strip().lower()
        if raw and content_type not in ("application/json", "application/problem+json"):
            raise AlphaError("The instance returned an unsupported response.", 502)
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError as error:
            raise AlphaError("The instance returned invalid JSON.", 502) from error
        return {"status": response.status, "headers": {k.lower(): v for k, v in response.getheaders()}, "body": parsed}
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
        raise AlphaError("The instance is temporarily unreachable.", 503) from error
    finally:
        if response is not None:
            response.close()
        conn.close()
