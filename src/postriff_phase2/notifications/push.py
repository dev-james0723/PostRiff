"""Web Push transport (adaptive coworker spec §18; architecture lock E2).

RFC 8291 message encryption (aes128gcm) and RFC 8292 VAPID, on the already-pinned `cryptography` library (no
Web Push SDK, matching the repository's "provider over HTTPS, no SDK" convention).

Safety rules:
- only explicit opt-in subscriptions exist (the browser asks; the server never prompts);
- the endpoint is a capability URL: it is stored encrypted (CredentialVault) and must be an https URL on a
  known push service (an allowlist, so a subscription can never make the server call an internal address);
- the payload is minimal: a title, one short line, a same-origin relative deep link and a grouping tag. Never
  draft text, DMs, analytics, credentials or anything secret-bearing; at most 3 KB before encryption;
- 404/410 revokes the subscription; 429 honours Retry-After; nothing retries a permanent failure.

`PushTransport` is the seam for native transports later (APNs/FCM) behind the same NotificationService contract.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import struct
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAX_PAYLOAD = 3072
RECORD_SIZE = 4096
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com", "web.push.apple.com",
              "notify.windows.com", "push.apple.com")
URGENCY = {"critical": "high", "security": "high", "action": "normal", "warning": "normal", "info": "low"}


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    text = str(text or "")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def endpoint_allowed(endpoint):
    parsed = urlparse(endpoint or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and not parsed.username and bool(host) and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def endpoint_hash(endpoint):
    return hashlib.sha256(str(endpoint).encode()).hexdigest()


# --- RFC 8291 -----------------------------------------------------------------------------------------------------------
def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(plaintext, p256dh, auth, *, salt=None, sender_private=None):
    """aes128gcm body for one push message (single record). `p256dh`, `auth` are the subscription's base64url keys."""
    if len(plaintext) > MAX_PAYLOAD:
        raise ValueError("push payload too large")
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    if len(ua_public) != 65 or ua_public[0] != 4 or len(auth_secret) != 16:
        raise ValueError("invalid subscription keys")
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    sender = sender_private or ec.generate_private_key(ec.SECP256R1())
    as_public = sender.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


def decrypt(body, receiver_private, auth):
    """The user-agent side of RFC 8291 (used by tests to prove the encryption round-trips)."""
    salt, record_size, id_len = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_public = body[21:21 + id_len]
    ciphertext = body[21 + id_len:]
    del record_size
    ua_public = receiver_private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    shared = receiver_private.exchange(ec.ECDH(), sender)
    ikm = _hkdf(unb64u(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return plain.rstrip(b"\x00")[:-1]


# --- RFC 8292 VAPID --------------------------------------------------------------------------------------------------------
def generate_vapid_keys():
    """For local development and key rotation only; production keys live in server secrets."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"privateKey": b64u(private), "publicKey": b64u(public)}


class Vapid:
    def __init__(self, private_key_b64, public_key_b64, subject):
        if not subject or not str(subject).startswith(("mailto:", "https://")):
            raise ValueError("VAPID subject must be a mailto: or https: contact")
        value = int.from_bytes(unb64u(private_key_b64), "big")
        self.key = ec.derive_private_key(value, ec.SECP256R1())
        derived = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        if public_key_b64 and unb64u(public_key_b64) != derived:
            raise ValueError("VAPID public key does not match the private key")
        self.public_key = b64u(derived)
        self.subject = subject

    def authorization(self, endpoint, now=None, ttl=12 * 3600):
        parsed = urlparse(endpoint)
        audience = f"{parsed.scheme}://{parsed.netloc}"
        header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        claims = b64u(json.dumps({"aud": audience, "exp": int((now or time.time()) + min(ttl, 24 * 3600)), "sub": self.subject}, separators=(",", ":")).encode())
        signing_input = f"{header}.{claims}".encode()
        r, s = decode_dss_signature(self.key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        token = f"{header}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={self.public_key}"


def vapid_from_environment(values):
    private, public, subject = values.get("POSTRIFF_VAPID_PRIVATE_KEY"), values.get("POSTRIFF_VAPID_PUBLIC_KEY"), values.get("POSTRIFF_VAPID_SUBJECT")
    if not (private and public and subject):
        return None
    return Vapid(private, public, subject)


def payload(title, body, url, tag, category):
    """The only thing a lock screen ever shows. Same-origin relative link, short text, no content."""
    if not isinstance(url, str) or not url.startswith("/app"):
        url = "/app"
    data = {"title": " ".join(str(title or "Rafii").split())[:60], "body": " ".join(str(body or "").split())[:120], "url": url[:300],
            "tag": str(tag or category or "rafii")[:64], "category": str(category or "")[:40]}
    raw = json.dumps(data, ensure_ascii=False).encode()
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("push payload too large")
    return raw


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect from a push service: the VAPID Authorization header must not travel to another URL.
    Returning None makes urllib raise the 3xx as an HTTPError, which is reported as that status."""
    def redirect_request(self, *_args, **_kwargs):
        return None


def raw_post(url, headers, body, timeout=15):
    """HTTPS POST of a binary body (providers.http_transport only sends JSON/form)."""
    if not url.startswith("https://"):
        raise ValueError("push endpoints must be https")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=timeout) as response:
            return {"status": response.status, "headers": {k.lower(): v for k, v in response.headers.items()}}
    except HTTPError as error:
        with error:
            return {"status": error.code, "headers": {k.lower(): v for k, v in (error.headers or {}).items()}}
    except (URLError, TimeoutError, OSError):
        return {"status": None, "headers": {}}


class PushTransport:
    """Interface: send(subscription, payload_bytes, ttl, urgency, topic) -> {state, retryAfter?, providerRef?}."""
    name = "push"

    def send(self, subscription, body, *, ttl=86400, urgency="normal", topic=None):  # pragma: no cover - interface
        raise NotImplementedError


class WebPushTransport(PushTransport):
    name = "webpush"

    def __init__(self, vapid, post=raw_post, clock=time.time):
        self.vapid, self.post, self.clock = vapid, post, clock

    def send(self, subscription, body, *, ttl=86400, urgency="normal", topic=None):
        endpoint = subscription["endpoint"]
        if not endpoint_allowed(endpoint):
            return {"state": "permanent", "detail": "endpoint_not_allowed"}
        encrypted = encrypt(body, subscription["p256dh"], subscription["auth"])
        headers = {"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(int(ttl)),
                   "Urgency": urgency if urgency in ("very-low", "low", "normal", "high") else "normal",
                   "Authorization": self.vapid.authorization(endpoint, self.clock())}
        if topic:
            headers["Topic"] = "".join(ch for ch in str(topic) if ch.isalnum() or ch in "-_")[:32] or "rafii"
        response = self.post(endpoint, headers, encrypted)
        status = response.get("status")
        if status in (200, 201, 202):
            return {"state": "sent", "providerRef": (response.get("headers") or {}).get("location")}
        if status in (404, 410):
            return {"state": "gone", "detail": f"push service returned {status}"}
        if status == 429:
            retry = (response.get("headers") or {}).get("retry-after")
            return {"state": "transient", "detail": "rate limited", "retryAfter": int(retry) if str(retry or "").isdigit() else 60}
        if status in (400, 401, 403):
            return {"state": "config", "detail": f"push service rejected the request ({status})"}
        if status == 413:
            return {"state": "permanent", "detail": "payload too large"}
        if status is None:
            return {"state": "uncertain", "detail": "no response from the push service"}
        return {"state": "transient", "detail": f"push service returned {status}"}


class RecordingPushTransport(PushTransport):
    """Local/test transport: records encrypted messages, sends nothing. Its outcome is never reported as delivered
    to a device; the delivery row says `provider: recording`."""
    name = "recording"

    def __init__(self, outcome="sent"):
        self.sent, self.outcome = [], outcome

    def send(self, subscription, body, *, ttl=86400, urgency="normal", topic=None):
        if not endpoint_allowed(subscription["endpoint"]):
            return {"state": "permanent", "detail": "endpoint_not_allowed"}
        self.sent.append({"endpoint": subscription["endpoint"], "body": body, "ttl": ttl, "urgency": urgency, "topic": topic})
        return {"state": self.outcome, "providerRef": f"recording-{len(self.sent)}"}
