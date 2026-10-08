"""Signed, opaque Library search cursors (engineering spec §8: stable pagination).

A cursor is `base64url(payload).base64url(HMAC-SHA256(secret, payload))`. The payload carries only a binding digest,
the snapshot time, the offset into the snapshot ranking, an eligibility fingerprint and the query id — never query
text, keys or content. The binding digest covers workspace, actor, query, scope, filters, purpose, modes, similarTo,
index generation, grant revision, normalizer version and ranking version, so a cursor cannot be replayed against a
different request, member, workspace, permission state or index.

Later pages recompute the ranking at the same snapshot: assets created after it are excluded, and segment/embedding
rows created after it are ignored. If the eligible set or the index watermarks moved anyway (a deletion, a correction,
a re-embedding), the fingerprint differs and the caller gets a recoverable 409 `library_cursor_stale` with a refresh
hint instead of silently skipped or duplicated results.

Secret: RAFII_LIBRARY_CURSOR_SECRET. Without it, a random per-process secret is used; a restart or a different
serverless instance then makes old cursors stale, which is the same recoverable refresh.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

from postriff_alpha.domain import AlphaError

from ..contracts import digest

CURSOR_VERSION = 1
MAX_AGE_SECONDS = 3600
MAX_OFFSET = 100_000
_PROCESS_SECRET = secrets.token_bytes(32)
STALE_MESSAGE = "These results changed since the last page. Refresh the search to continue."


class CursorStale(AlphaError):
    """409 with a stable code; `refresh` tells API clients to restart from the first page."""

    def __init__(self, message: str = STALE_MESSAGE):
        super().__init__(message, 409, code="library_cursor_stale")
        self.refresh = True
        self.hint = {"action": "refresh", "reason": "cursor_stale"}


def _secret() -> bytes:
    configured = os.environ.get("RAFII_LIBRARY_CURSOR_SECRET", "")
    return configured.encode() if configured else _PROCESS_SECRET


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def binding(*, workspace_id: str, actor: str, request: dict, index_generation: int, grant_revision: int, normalizer_version: int,
            ranking_version: str) -> str:
    """Digest of everything a later page must share with the first. Limit is excluded (page size may change)."""
    return digest({
        "w": str(workspace_id), "a": str(actor), "q": request.get("query", ""), "s": request.get("scope"), "f": request.get("filters"),
        "p": request.get("purpose"), "m": request.get("modes"), "x": request.get("similarTo"), "g": int(index_generation),
        "r": int(grant_revision), "n": int(normalizer_version), "k": ranking_version, "v": CURSOR_VERSION,
    })[:32]


def fingerprint(keys, *watermarks) -> str:
    """Eligible-set and index watermark digest at the snapshot (order-independent)."""
    h = hashlib.sha256()
    for k in sorted(keys):
        h.update(k.encode())
        h.update(b"\n")
    h.update(json.dumps([int(w) for w in watermarks]).encode())
    return h.hexdigest()[:24]


def encode(*, binding_digest: str, snapshot: float, offset: int, fingerprint_value: str, query_id: str) -> str:
    payload = json.dumps({"v": CURSOR_VERSION, "b": binding_digest, "t": round(float(snapshot), 6), "o": int(offset), "f": fingerprint_value,
                          "q": query_id}, separators=(",", ":"), sort_keys=True).encode()
    body = _b64(payload)
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def decode(token: str, *, binding_digest: str, now: float) -> dict:
    """Verify signature, binding and age. Any failure is the same recoverable stale-cursor refusal."""
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 2000:
        raise CursorStale()
    body, mac = token.split(".")
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, mac):
        raise CursorStale()
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        raise CursorStale() from None
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise CursorStale()
    offset, snapshot = payload.get("o"), payload.get("t")
    if type(offset) is not int or not 0 <= offset <= MAX_OFFSET or not isinstance(snapshot, (int, float)) or isinstance(snapshot, bool):
        raise CursorStale()
    if not isinstance(payload.get("f"), str) or not isinstance(payload.get("q"), str) or len(payload["q"]) > 64:
        raise CursorStale()
    if not hmac.compare_digest(str(payload.get("b")), binding_digest):
        raise CursorStale()
    if float(now) - float(snapshot) > MAX_AGE_SECONDS:
        raise CursorStale("These results are more than an hour old. Refresh the search to continue.")
    return {"snapshot": float(snapshot), "offset": offset, "fingerprint": payload["f"], "queryId": payload["q"]}


def check_fingerprint(state: dict, current: str):
    if not hmac.compare_digest(state["fingerprint"], current):
        raise CursorStale()
