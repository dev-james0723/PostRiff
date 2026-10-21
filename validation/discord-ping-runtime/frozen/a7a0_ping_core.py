"""Stateless Discord Ed25519 PING-only verifier.

This is a separately reviewed narrow overlay derived from Rafii PR #216.
It intentionally DOES NOT import postriff_alpha, postriff_phase2, SQLite,
Postgres, or any outbound HTTP client. See SOURCE_PROVENANCE.json.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Mapping
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_BODY_BYTES = 65536
_ALLOWED_TIMESTAMP = re.compile(r"[0-9]{10,12}\Z", flags=re.ASCII)
_ALLOWED_SIGNATURE = re.compile(r"[0-9a-fA-F]{128}\Z", flags=re.ASCII)
_ALLOWED_APP = re.compile(r"[0-9]{5,25}\Z", flags=re.ASCII)
_ALLOWED_PUBLIC = re.compile(r"[0-9a-fA-F]{64}\Z", flags=re.ASCII)
_ALLOWED_HOST = re.compile(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}\Z", flags=re.ASCII)


class Reject(Exception):
    """Only a sanitized numeric HTTP status leaves this verifier."""
    def __init__(self, status: int = 401):
        self.status = status
        super().__init__(f"Request rejected ({status})")


@dataclass(frozen=True)
class Settings:
    application_id: str
    public_key_hex: str
    expected_origin: str

    def __post_init__(self):
        if not isinstance(self.application_id, str) or not _ALLOWED_APP.fullmatch(self.application_id):
            raise Reject(503)
        if not isinstance(self.public_key_hex, str) or not _ALLOWED_PUBLIC.fullmatch(self.public_key_hex):
            raise Reject(503)
        if not isinstance(self.expected_origin, str):
            raise Reject(503)
        try:
            uri = urlsplit(self.expected_origin)
            host = uri.hostname
            # The origin is a pinned exact authority, never taken from an HTTP
            # Host / forwarded-host supplied by a remote caller.
            if (uri.scheme != 'https' or not host or not _ALLOWED_HOST.fullmatch(host)
                    or host != host.lower() or uri.netloc != host or uri.path
                    or uri.query or uri.fragment or uri.username or uri.password
                    or uri.port is not None or '\\' in self.expected_origin):
                raise Reject(503)
            labels = host.split('.')
            if (len(labels) < 2 or any(not 1 <= len(label) <= 63 or
                    label.startswith('-') or label.endswith('-') for label in labels)):
                raise Reject(503)
        except (ValueError, AttributeError):
            raise Reject(503) from None


def settings_from_env(env: Mapping[str, str]) -> Settings:
    """Compare two *process-owned* deployment identifiers; never request headers.

    VERCEL_URL is platform-provided. Missing fields, aliases or a wrong
    generated deployment hostname fail closed before signature parsing.
    """
    try:
        config = Settings(
            application_id=env['RAFII_A7A0_APPLICATION_ID'],
            public_key_hex=env['RAFII_A7A0_PUBLIC_KEY_HEX'],
            expected_origin=env['RAFII_A7A0_EXPECTED_ORIGIN'],
        )
        actual = env['VERCEL_URL']
        # Accept the exact generated DNS name, not a client-controlled Host.
        if not isinstance(actual, str) or config.expected_origin != 'https://' + actual:
            raise Reject(503)
        return config
    except (KeyError, TypeError, ValueError):
        raise Reject(503) from None


def _object_no_duplicates(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError('non-finite JSON constant')


def verify_ping(raw: bytes, timestamp: str, signature: str, config: Settings, *, now=None) -> dict:
    """Exactly the signed type-1 PING subprotocol, with no database or network.

    This verifier DOES NOT implement Discord useful slash command handling,
    replay claims, draft/user-link readback or any side-effecting operations.
    """
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BODY_BYTES:
        # Match the PR #216 raw-interaction verifier (401 on an invalid raw
        # payload). The HTTP edge already returns 413 before this layer for
        # an oversized declared Content-Length.
        raise Reject(401)
    if (not isinstance(timestamp, str) or not _ALLOWED_TIMESTAMP.fullmatch(timestamp)
            or not isinstance(signature, str) or not _ALLOWED_SIGNATURE.fullmatch(signature)):
        raise Reject(401)
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > 300:
        raise Reject(401)
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(config.public_key_hex))
        key.verify(bytes.fromhex(signature), timestamp.encode('ascii') + raw)
        # Discord's HTTP JSON body is UTF-8. Do not accept json.loads(bytes)
        # autodetection of UTF-16/UTF-32 or a BOM, even with a valid signature.
        packet = json.loads(raw.decode('utf-8', errors='strict'),
                            object_pairs_hook=_object_no_duplicates,
                            parse_constant=_reject_constant)
    except (InvalidSignature, ValueError, UnicodeError, RecursionError, OverflowError, TypeError):
        raise Reject(401) from None
    if not isinstance(packet, dict) or packet.get('application_id') != config.application_id:
        raise Reject(401)
    if type(packet.get('type')) is not int:
        raise Reject(401)
    if packet['type'] != 1:
        # Do not call a full Rafii handler even if a future environment field
        # accidentally claims the command has been qualified.
        raise Reject(503)
    return {'type': 1}
