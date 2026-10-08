"""Python side of the trusted OpenUI parser seam (A-owned; spec §2.4, 02-CONTRACTS §3 `validate_and_merge_ui`).

The official parser runs in Node (`@openuidev/lang-core`), not in this Python function. Python posts the candidate source
to the web service's precise internal route `POST /internal/agent-ui/validate` (web/src/app/internal/agent-ui/validate/
route.ts), signed with HMAC-SHA256 over a timestamp and the body hash using the server-only `RAFII_GENUI_VALIDATOR_SECRET`.
The route parses and applies policy only: no rendering, network, queries or tool execution.

Target, in order: RAFII_WEB_INTERNAL_URL (Vercel service binding to postriff_web), RAFII_GENUI_VALIDATOR_URL (explicit, e.g.
local dev), then the deployment's own https://VERCEL_URL with `x-vercel-protection-bypass` when the automation bypass secret is
configured. No retries: a timeout, non-200, bad signature config or an inconsistent answer is "not accepted" and the caller
keeps the native fallback. The result is trusted only after Python re-checks the canonical hash and library identity.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.request

from . import ui_contracts as contracts

ROUTE = "internal/agent-ui/validate"
SECRET_ENV = "RAFII_GENUI_VALIDATOR_SECRET"
KEY_ID = "v1"


def _rejected(code: str) -> dict:
    return {"accepted": False, "canonicalSource": None, "sourceHash": None, "statementCount": 0, "queryNames": [], "actionIds": [],
            "componentNames": [], "stateNames": [], "formNames": [], "errors": [code], "libraryHash": None, "libraryVersion": None}


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    return hmac.new(secret.encode("utf-8"), f"{KEY_ID}\n{timestamp}\n{digest}".encode("utf-8"), hashlib.sha256).hexdigest()


def target(values=None) -> tuple[str | None, dict]:
    values = os.environ if values is None else values
    headers = {}
    base = (values.get("RAFII_WEB_INTERNAL_URL") or values.get("RAFII_GENUI_VALIDATOR_URL") or "").strip()
    if not base and values.get("VERCEL_URL"):
        base = "https://" + values["VERCEL_URL"].strip()
        bypass = values.get("VERCEL_AUTOMATION_BYPASS_SECRET")
        if bypass:
            headers["x-vercel-protection-bypass"] = bypass
    if not base:
        return None, headers
    return base.rstrip("/") + "/" + ROUTE, headers


def _default_transport(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    context = ssl.create_default_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 — fixed internal route
            return response.status, response.read(512 * 1024)
    except urllib.error.HTTPError as error:
        return error.code, b""


def validate_and_merge_ui(base_source: str | None, candidate_source: str, library_hash: str, mode: str, *, policy: dict, scope: dict,
                          transport=None, values=None, clock=time.time) -> dict:
    """UiValidationResult for exactly this source/library/manifest. `policy` carries the manifest's allowed components, read
    binding names and action ids; `scope` carries {workspaceId, artifactId, attemptId} so the request is bound to one run."""
    if mode not in ("generate", "patch"):
        raise ValueError("mode must be generate or patch")
    limit = contracts.BOUNDS["patchBytes"] if mode == "patch" else contracts.BOUNDS["sourceBytes"]
    if not isinstance(candidate_source, str) or len(candidate_source.encode("utf-8")) > limit:
        return _rejected("source_too_large")
    if mode == "patch" and not base_source:
        return _rejected("missing_base")
    values = os.environ if values is None else values
    secret = values.get(SECRET_ENV)
    url, extra = target(values)
    if not secret or len(secret) < 32 or not url:
        return _rejected("validation_unavailable")
    payload = {"v": KEY_ID, "contractVersion": contracts.CONTRACT_VERSION, "mode": mode, "baseSource": base_source, "candidateSource": candidate_source,
               "libraryHash": library_hash, "policy": policy, "scope": scope}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > contracts.BOUNDS["requestBodyBytes"]:
        return _rejected("source_too_large")
    stamp = str(int(clock()))
    headers = {"Content-Type": "application/json", "X-Rafii-Validator-Key": KEY_ID, "X-Rafii-Validator-Timestamp": stamp,
               "X-Rafii-Validator-Signature": sign(secret, stamp, body), **extra}
    try:
        status, raw = (transport or _default_transport)(url, body, headers, float(contracts.BOUNDS["validatorTimeoutSeconds"]))
    except (OSError, ValueError, TimeoutError):
        return _rejected("validation_unavailable")
    if status != 200:
        return _rejected("validation_unavailable")
    try:
        answer = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _rejected("validation_unavailable")
    if not isinstance(answer, dict):
        return _rejected("validation_unavailable")
    if not answer.get("accepted"):
        errors = [str(e)[:120] for e in (answer.get("errors") or [])][:20] or ["parse_rejected"]
        return {**_rejected(errors[0]), "errors": errors}
    canonical = answer.get("canonicalSource")
    if not isinstance(canonical, str) or len(canonical.encode("utf-8")) > contracts.BOUNDS["sourceBytes"]:
        return _rejected("source_too_large")
    if answer.get("sourceHash") != contracts.sha256_text(canonical) or answer.get("libraryHash") != library_hash:
        # The seam answered for a different source or library build (version skew): never accept it.
        return _rejected("validation_unavailable")
    return {"accepted": True, "canonicalSource": canonical, "sourceHash": answer["sourceHash"],
            "statementCount": int(answer.get("statementCount") or 0), "queryNames": [str(q) for q in answer.get("queryNames") or []][:100],
            "actionIds": [str(a) for a in answer.get("actionIds") or []][:100], "componentNames": [str(c) for c in answer.get("componentNames") or []][:200],
            # Declared reactive `$vars` and Form names of the canonical source (official parser), the only UI state fields ui_store persists.
            "stateNames": [str(s)[:64] for s in answer.get("stateNames") or [] if isinstance(s, str)][:200],
            "formNames": [str(f)[:64] for f in answer.get("formNames") or [] if isinstance(f, str)][:100],
            "errors": [], "libraryHash": library_hash, "libraryVersion": answer.get("libraryVersion")}
