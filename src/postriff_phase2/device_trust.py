"""Rafii Account Protection v2, P1 item 1: the device registry. Tells a new session apart from a new browser.

A browser instance is identified by `__Host-rafii_device`, an opaque random value the server mints after it has
verified the person's identity (host-only, Secure, HttpOnly, SameSite=Lax, no Domain). The cookie is a copyable hint,
never a credential: it proves nothing on its own, it is never trusted because a browser presents it, and it can only
ever make a session look *less* known (a missing or unknown cookie is an unknown browser).

At rest only HMAC-SHA-256(key, "rafii-device/v1|" + user_id + "|" + cookie) is stored, with the key's version. Keys
come from `RAFII_DEVICE_COOKIE_KEYS` ("2:<secret>,1:<old secret>", current key first, each secret at least 32 bytes).
Every configured key is tried on read; a match under an older key is re-hashed under the current one (rotate on
success), so a key can be retired once its devices have been seen again. The hash includes the user id, so one browser
used by two accounts is two unrelated records, and a cookie seen for one person says nothing about another.

Off unless `RAFII_DEVICE_TRUST_V2` is on, a valid key is configured and RAFII_ACCOUNT_PROTECTION_V2_MODE observes. Off
means no statement, no cookie and no header: the legacy behaviour byte for byte.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import re
import secrets

COOKIE = "__Host-rafii_device"
# 400 days, the longest lifetime browsers keep; the value is a hint, so a lost cookie only means "unknown browser".
MAX_AGE = 400 * 24 * 3600
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_ON = ("1", "on", "true")


def enabled(values=None):
    from .coworker import flags
    return str(flags._source(values).get("RAFII_DEVICE_TRUST_V2", "")).strip().lower() in _ON


def keys(values=None):
    """[(version, secret bytes)], current key first; [] (the registry stays off) when any entry is malformed."""
    from .coworker import flags
    raw = str(flags._source(values).get("RAFII_DEVICE_COOKIE_KEYS", "") or "").strip()
    parsed, versions = [], set()
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        version, _, secret = entry.partition(":")
        if not version.isdigit() or not 1 <= int(version) <= 100 or int(version) in versions or len(secret.encode()) < 32:
            return []
        versions.add(int(version))
        parsed.append((int(version), secret.encode()))
    return parsed


def active(values=None):
    from . import account_protection
    return enabled(values) and account_protection.observing(values) and bool(keys(values))


def token_hash(secret, user_id, raw):
    return hmac.new(secret, f"rafii-device/v1|{user_id}|{raw}".encode(), hashlib.sha256).hexdigest()


class RequestDevice:
    """The device cookie of the HTTP request being served, and the new one to issue, if any."""

    def __init__(self, cookie_header, fetch_site):
        self._cookie_header = cookie_header if isinstance(cookie_header, str) else ""
        # Only a browser's own same-origin request may receive a new cookie: server-side callers (the web app's SSR
        # prefetch) cannot pass a Set-Cookie on, and a minted value nobody keeps would be an orphan device.
        self.browser = fetch_site == "same-origin"
        self.issued = None

    def presented(self):
        for part in self._cookie_header[:8192].split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and _TOKEN.fullmatch(value):
                return value
        return None

    def can_register(self):
        return self.issued is not None or self.presented() is not None or self.browser


_REQUEST = contextvars.ContextVar("rafii_device_request", default=None)


def bind(environ):
    return _REQUEST.set(RequestDevice(environ.get("HTTP_COOKIE", ""), environ.get("HTTP_SEC_FETCH_SITE", "")))


def reset(binding):
    _REQUEST.reset(binding)


def current():
    return _REQUEST.get()


def seen_marker():
    """Part of the verifier's per-process seen key: a session first observed without a usable device (an SSR prefetch)
    is observed once more when its browser shows up, so the session is linked to that browser."""
    request = current()
    return "device" if request is not None and request.can_register() and active() else None


def set_cookie_header():
    request = current()
    if request is None or request.issued is None:
        return None
    return ("Set-Cookie", f"{COOKIE}={request.issued}; Max-Age={MAX_AGE}; Path=/; Secure; HttpOnly; SameSite=Lax")


def register(cur, principal, session_id, label=""):
    """{"id", "new"} for the browser of the request being served, recorded for this person; None outside a request or
    when this request has no usable browser cookie and cannot be given one. Runs inside the session's transaction."""
    request = current()
    configured = keys()
    if request is None or not configured:
        return None
    raw = request.issued or request.presented()
    if raw is not None:
        candidates = [(version, token_hash(secret, principal, raw)) for version, secret in configured]
        cur.execute("SELECT id,hmac_key_version,state FROM public.pr_security_devices WHERE user_id=%s AND token_hash = ANY(%s) ORDER BY hmac_key_version DESC LIMIT 1", (principal, [digest for _, digest in candidates]))
        row = cur.fetchone()
        if row and row[2] != "revoked":
            version, digest = candidates[0]
            if int(row[1]) != version:
                cur.execute("UPDATE public.pr_security_devices SET token_hash=%s,hmac_key_version=%s,last_seen_at=now(),updated_at=now() WHERE user_id=%s AND id=%s", (digest, version, principal, row[0]))
            else:
                cur.execute("UPDATE public.pr_security_devices SET last_seen_at=now() WHERE user_id=%s AND id=%s", (principal, row[0]))
            return {"id": str(row[0]), "new": False}
        if row:
            # A revoked browser never comes back under its old token: it gets a new one and a new record.
            raw = None
    if raw is None:
        if not request.browser:
            return None
        raw = request.issued = secrets.token_urlsafe(32)
    version, secret = configured[0]
    cur.execute("INSERT INTO public.pr_security_devices(user_id,token_hash,hmac_key_version,display_label) VALUES(%s,%s,%s,%s) ON CONFLICT(user_id,token_hash) DO UPDATE SET last_seen_at=now() RETURNING id,(xmax = 0)", (principal, token_hash(secret, principal, raw), version, (label or "Unrecognized browser")[:80]))
    device_id, new = cur.fetchone()
    if new:
        record(cur, principal, "device.first_observed", f"device.first_observed:{device_id}", session_id=session_id, device_id=device_id, details={"client": (label or "")[:40]})
    return {"id": str(device_id), "new": bool(new)}


def record(cur, principal, event_type, event_key, *, session_id=None, device_id=None, details=None, risk_level=None):
    """One append-only ledger row; a repeat of the same event key (or a second first sighting) is a no-op."""
    cur.execute("INSERT INTO public.pr_security_login_events(user_id,session_id,device_id,event_type,event_key,details,risk_level) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING", (principal, session_id, device_id, event_type, event_key[:180], json.dumps(details or {}), risk_level))


def observe(cur, principal, session_id, label, fresh):
    """Device link and ledger for a session the caller has just upserted into pr_sessions (same transaction)."""
    device = register(cur, principal, session_id, label)
    device_id = device["id"] if device else None
    cur.execute("INSERT INTO public.pr_session_security(user_id,session_id,device_id) VALUES(%s,%s,%s) ON CONFLICT(user_id,session_id) DO UPDATE SET device_id=coalesce(public.pr_session_security.device_id,excluded.device_id),last_evaluated_at=now()", (principal, session_id, device_id))
    if fresh:
        # A new session on a browser seen before is `session.observed` alone; on a new browser it also has a
        # `device.first_observed` (written by register). `device` is "pending" when the first request carried no
        # browser cookie (an SSR prefetch); the browser's own first request links it later.
        state = "new" if device and device["new"] else "known" if device else "pending"
        record(cur, principal, "session.observed", f"session.observed:{session_id}", session_id=session_id, device_id=device_id, details={"client": (label or "")[:40], "device": state})
    return device
