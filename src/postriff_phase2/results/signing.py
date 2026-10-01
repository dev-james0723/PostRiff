"""The signed first-party result contract (PRD R-OUT-03): one documented scheme for an approved, user-controlled
form or booking producer.

Header ``X-Rafii-Signature: t=<unix seconds>,v1=<hex>[,v1=<hex>…]``. Each v1 is HMAC-SHA256 over the exact bytes
``<t>.<raw body>`` with the connection's secret. The delivery timestamp ``t`` is distinct from when the reported event
happened (``occurredAt`` in the body). A producer that is rotating its key may send one v1 per key; the receiver
accepts the delivery when any v1 matches any of the connection's active secrets (the current one, or the previous one
inside its grace period). Secrets are compared in constant time and never echoed.

Everything here is a pure function: no I/O, no clock of its own, no logging of the body or the secret.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

SCHEME = "rafii-results-v1"
REPLAY_WINDOW_SECONDS = 300          # PRD proposed default: five minutes either side of the delivery timestamp
MAX_BODY_BYTES = 16 * 1024           # one event per delivery; anything larger is refused before parsing
MAX_SIGNATURES = 4
SECRET_PREFIX = "rfs_"
_HEADER_PART = re.compile(r"^(t|v1)=([A-Za-z0-9]{1,128})$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SignatureError(Exception):
    """The delivery is not authentic or not fresh. ``code`` is a stable, content-free reason."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def new_secret():
    """A fresh connection secret, shown to the person once and stored only encrypted."""
    return SECRET_PREFIX + secrets.token_hex(32)


def secret_fingerprint(secret):
    """A short, non-reversible label so the UI can say which key is active without revealing it."""
    return hashlib.sha256(("fingerprint:" + secret).encode()).hexdigest()[:12]


def sign(secret, timestamp, body):
    """The producer side (used by the documented test producer): the header value for ``body`` at ``timestamp``."""
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError("body must be the exact bytes that will be sent")
    digest = hmac.new(secret.encode(), str(int(timestamp)).encode() + b"." + bytes(body), hashlib.sha256).hexdigest()
    return f"t={int(timestamp)},v1={digest}"


def parse_header(value):
    """``t=…,v1=…`` → (timestamp, [hex digests]). Raises SignatureError on anything malformed."""
    if not isinstance(value, str) or not value or len(value) > 600:
        raise SignatureError("signature_missing")
    timestamp, digests = None, []
    for part in value.split(","):
        match = _HEADER_PART.match(part.strip())
        if not match:
            raise SignatureError("signature_malformed")
        name, item = match.groups()
        if name == "t":
            if timestamp is not None or not item.isdigit() or len(item) > 12:
                raise SignatureError("signature_malformed")
            timestamp = int(item)
        else:
            if not _HEX64.match(item):
                raise SignatureError("signature_malformed")
            digests.append(item)
    if timestamp is None or not digests or len(digests) > MAX_SIGNATURES:
        raise SignatureError("signature_malformed")
    return timestamp, digests


def verify(header, body, secrets_, now, *, window=REPLAY_WINDOW_SECONDS):
    """Authenticate one delivery. ``secrets_`` are the connection's currently accepted secrets (current first).
    Returns ``{"timestamp": t, "keyIndex": i}`` naming which secret matched (0 = current). Raises SignatureError."""
    if not isinstance(body, (bytes, bytearray)):
        raise SignatureError("body_unavailable")
    if len(body) > MAX_BODY_BYTES:
        raise SignatureError("body_too_large")
    timestamp, digests = parse_header(header)
    if abs(float(now) - timestamp) > window:
        raise SignatureError("timestamp_outside_window")
    message = str(timestamp).encode() + b"." + bytes(body)
    usable = [s for s in secrets_ or () if isinstance(s, str) and s]
    if not usable:
        raise SignatureError("connection_has_no_secret")
    for index, secret in enumerate(usable):
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        # Compare against every supplied digest so timing does not reveal which one matched.
        matched = False
        for digest in digests:
            matched = hmac.compare_digest(expected, digest) or matched
        if matched:
            return {"timestamp": timestamp, "keyIndex": index}
    raise SignatureError("signature_mismatch")


def event_digest(event):
    """The identity of a reported event's content, over its normalized fields (not the raw bytes, so a producer that
    re-serializes the same event is still an exact replay). A conflicting payload for the same event id has a different
    digest and is quarantined instead of silently replacing the first one."""
    import json
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
