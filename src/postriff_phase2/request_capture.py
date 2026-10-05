"""Opt-in, fail-closed evidence at the writer's final HTTP handoff.

Nothing here logs plaintext, credentials or body hashes. The default context is
inactive. Independent retention consent does not grant model egress permission.
Receipts attest the identified application boundary, not an upstream provider's
internal request. Expiry denies live access; database backups are not crypto-erased.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import re
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAX_BODY_BYTES = 512 * 1024
CONSENT_VERSION = "rafii-exact-request-v1"
DOMAIN = b"rafii-model-request-capture-v1\x00"
_ACTIVE = contextvars.ContextVar("rafii_request_capture", default=None)
_SAFE_HEADERS = frozenset({"content-type", "x-request-id", "request-id", "x-vercel-id", "x-vercel-ai-gateway-generation-id"})


class AuditCaptureBlocked(Exception):
    """This physical attempt has not dispatched; never fall back to uncaptured I/O."""


class AuditCaptureOutcomeUnknown(Exception):
    """A dispatched attempt cannot be fully evidenced; do not retry it."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _b64(value):
    return base64.b64encode(value).decode("ascii")


def _unb64(value):
    return base64.b64decode(value, validate=True)


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _uuid(value):
    return str(uuid.UUID(str(value)))


def _public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def verify_receipt(receipt, public_key):
    """Offline public-key verification; callers must independently trust this key."""
    if receipt.get("schema") != "rafii-request-capture-v1":
        raise AuditCaptureBlocked("Capture receipt schema is unavailable.")
    try:
        payload = _unb64(receipt["signed_payload_base64"])
        if not payload.startswith(DOMAIN):
            raise ValueError("signature domain")
        manifest = json.loads(payload[len(DOMAIN):])
        if manifest != receipt["manifest"] or payload != DOMAIN + _canonical(manifest):
            raise ValueError("manifest mismatch")
        Ed25519PublicKey.from_public_bytes(public_key).verify(_unb64(receipt["signature"]), payload)
    except (InvalidSignature, ValueError, TypeError, KeyError) as error:
        raise AuditCaptureBlocked("Capture signature verification failed.") from error
    return manifest


def _receipt_digest(receipt):
    return hashlib.sha256(_unb64(receipt["signed_payload_base64"]) + _unb64(receipt["signature"])).hexdigest()


@dataclass(frozen=True)
class CaptureScope:
    workspace_id: str
    actor_id: str
    run_id: str
    grant_id: str
    server_nonce: str
    route: str
    reservation_id: str | None = None

    def payload(self):
        return {"workspace_id": _uuid(self.workspace_id), "actor_id": _uuid(self.actor_id),
                "run_id": _uuid(self.run_id), "grant_id": _uuid(self.grant_id),
                "server_nonce": self.server_nonce, "route": self.route,
                "reservation_id": _uuid(self.reservation_id) if self.reservation_id else None}


@contextmanager
def capture_scope(service, scope):
    """Bind only a server-verified actor and the atomically bound normal run."""
    token = _ACTIVE.set((service, scope))
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active():
    return _ACTIVE.get() is not None


def prepare_request(body_bytes, *, method, url, timeout, model, logical_call_id, workload, attempt_no):
    bound = _ACTIVE.get()
    if bound is None:
        raise AuditCaptureBlocked("Capture scope is not active.")
    service, scope = bound
    try:
        return service.prepare(scope, body_bytes, method=method, url=url, timeout=timeout, model=model,
                               logical_call_id=logical_call_id, workload=workload, attempt_no=attempt_no)
    except AuditCaptureBlocked:
        raise
    except Exception as error:
        raise AuditCaptureBlocked("Capture preparation failed before dispatch.") from error


class PostgresCaptureRepository:
    """Use a narrow NOLOGIN/NOBYPASSRLS capability, never broad table access.

    The existing trusted backend connection may SET ROLE; every operation checks
    the effective role and calls only the private constrained function. Browsers
    receive no schema/table/function grants. No DSN or keys are logged.
    """
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def call(self, action, payload, *, cursor=None):
        if cursor is not None:
            return self._call(cursor, action, payload)
        try:
            with self.connection_factory() as connection:
                with connection.cursor() as cur:
                    result = self._call(cur, action, payload)
            return result  # context exit has committed before returning
        except AuditCaptureBlocked:
            raise
        except Exception as error:
            raise AuditCaptureBlocked("Private capture storage is unavailable.") from error

    @staticmethod
    def _call(cur, action, payload):
        # A savepoint permits restoration even if the function rejects a grant.
        cur.execute("SELECT current_user")
        original_role = cur.fetchone()[0]
        cur.execute("SAVEPOINT rafii_capture_capability")
        try:
            cur.execute("SET LOCAL ROLE pr_capture_runtime")
            cur.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            role = cur.fetchone()
            if not role or role[0] != "pr_capture_runtime" or role[1] or role[2]:
                raise AuditCaptureBlocked("Restricted capture capability is unavailable.")
            cur.execute("SELECT audit_private.capture_operation(%s,%s::jsonb)", (action, json.dumps(payload, allow_nan=False)))
            result = cur.fetchone()[0]
            # SET ROLE is transaction-local; RESET ROLE restores the backend login.
            cur.execute('SET LOCAL ROLE "' + original_role.replace('"', '""') + '"')
            cur.execute("RELEASE SAVEPOINT rafii_capture_capability")
            return json.loads(result) if isinstance(result, str) else result
        except Exception as error:
            cur.execute("ROLLBACK TO SAVEPOINT rafii_capture_capability")
            cur.execute("RELEASE SAVEPOINT rafii_capture_capability")
            if isinstance(error, AuditCaptureBlocked):
                raise
            raise AuditCaptureBlocked("Capture scope or persistence check failed.") from error


class CaptureService:
    def __init__(self, repository, encryption_key, signing_key, key_id, deployment_sha, allowlisted_workspace):
        if len(encryption_key) != 32 or len(signing_key) != 32 or hmac.compare_digest(encryption_key, signing_key):
            raise ValueError("Distinct 32-byte audit encryption and signing keys are required.")
        if not re.fullmatch(r"[0-9a-f]{40}", deployment_sha):
            raise ValueError("Capture requires the deployed source SHA.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", key_id):
            raise ValueError("Invalid audit key reference.")
        self.repository = repository
        self._encryption_key = encryption_key
        self._signer = Ed25519PrivateKey.from_private_bytes(signing_key)
        self.key_id = key_id
        self.deployment_sha = deployment_sha
        self.allowlisted_workspace = _uuid(allowlisted_workspace)
        self.public_key = _public(self._signer)

    def _allowed(self, workspace_id):
        if _uuid(workspace_id) != self.allowlisted_workspace:
            raise AuditCaptureBlocked("Workspace is not enabled for private audit capture.")

    def _signed(self, manifest):
        payload = DOMAIN + _canonical(manifest)
        return {"schema": "rafii-request-capture-v1", "manifest": manifest,
                "signed_payload_base64": _b64(payload), "signature": _b64(self._signer.sign(payload)),
                "public_key": _b64(self.public_key), "key_id": self.key_id}

    def _key(self, grant_id, server_nonce):
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=server_nonce.encode("ascii"),
                    info=DOMAIN + grant_id.encode("ascii")).derive(self._encryption_key)

    def _seal(self, plaintext, scope, manifest, kind):
        nonce = secrets.token_bytes(12)
        aad = _canonical({"kind": kind, "manifest": manifest})
        return {"ciphertext": _b64(AESGCM(self._key(scope.grant_id, scope.server_nonce)).encrypt(nonce, plaintext, aad)),
                "nonce": _b64(nonce), "key_id": self.key_id, "kind": kind}

    def _open(self, sealed, scope, manifest):
        if sealed["key_id"] != self.key_id:
            raise AuditCaptureBlocked("Capture decryption key is unavailable.")
        try:
            return AESGCM(self._key(scope.grant_id, scope.server_nonce)).decrypt(
                _unb64(sealed["nonce"]), _unb64(sealed["ciphertext"]), _canonical({"kind": sealed["kind"], "manifest": manifest}))
        except (InvalidTag, ValueError, KeyError) as error:
            raise AuditCaptureBlocked("Capture body integrity verification failed.") from error

    def create_grant(self, *, workspace_id, actor_id, route, reader_ids, confirmed, consent_version=CONSENT_VERSION, ttl_seconds=3600):
        self._allowed(workspace_id)
        if confirmed is not True or consent_version != CONSENT_VERSION or not (1 <= ttl_seconds <= 3600):
            raise AuditCaptureBlocked("Explicit bounded audit-retention consent is required.")
        if [_uuid(value) for value in reader_ids] != [_uuid(actor_id)]:
            raise AuditCaptureBlocked("This audit capability permits only the consenting actor as reader.")
        _endpoint(route)
        return self.repository.call("create", {"id": str(uuid.uuid4()), "workspace_id": _uuid(workspace_id),
            "actor_id": _uuid(actor_id), "route": route, "reader_ids": reader_ids,
            "server_nonce": secrets.token_urlsafe(32), "consent_version": consent_version,
            "confirmed": True, "ttl_seconds": ttl_seconds, "capture_mode": "encrypted_exact_body"})

    def bind_grant(self, cur, *, grant_id, server_nonce, workspace_id, actor_id, run_id, idempotency_key):
        self._allowed(workspace_id)
        return self.repository.call("bind", {"grant_id": _uuid(grant_id), "server_nonce": server_nonce,
            "workspace_id": _uuid(workspace_id), "actor_id": _uuid(actor_id), "run_id": _uuid(run_id),
            "idempotency_key": idempotency_key}, cursor=cur)

    def prepare(self, scope, body_bytes, *, method, url, timeout, model, logical_call_id, workload, attempt_no):
        self._allowed(scope.workspace_id)
        _endpoint(url)
        if url != scope.route or method != "POST" or not isinstance(body_bytes, bytes) or len(body_bytes) > MAX_BODY_BYTES:
            raise AuditCaptureBlocked("Capture requires the approved route and a bounded immutable POST body.")
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
            if not isinstance(parsed, dict) or parsed.get("model") != model or not isinstance(parsed.get("messages"), list):
                raise ValueError("unsupported request")
            _no_credentials(body_bytes)
        except (ValueError, UnicodeError) as error:
            raise AuditCaptureBlocked("Capture request is unsupported or contains credentials.") from error
        grant = self.repository.call("grant", scope.payload())
        capture_id = str(uuid.uuid4())
        manifest = {"kind": "prepared", "physical_attempt_id": capture_id, **scope.payload(),
            "server_nonce": scope.server_nonce, "created_at": _stamp(), "expires_at": grant["expires_at"],
            "consent_version": grant["consent_version"], "capture_mode": "encrypted_exact_body",
            "policy_epoch": grant["policy_epoch"], "workspace_revision": grant["workspace_revision"],
            "reader_ids": grant["reader_ids"], "deployment_sha": self.deployment_sha, "key_id": self.key_id,
            "body_sha256": hashlib.sha256(body_bytes).hexdigest(), "body_bytes": len(body_bytes),
            "method": method, "endpoint": url, "content_type": "application/json", "model": model,
            "logical_call_id": _uuid(logical_call_id), "workload": str(workload), "attempt_no": int(attempt_no),
            "hop_index": 0, "parent_attempt_id": None, "timeout_seconds": timeout,
            "serializer": "python.json.dumps-default.utf8.v1", "redirects": "disabled", "transport_retries": 0,
            "credential_reference": "binding_unavailable", "trust_boundary": "application_http_request_handoff"}
        receipt = self._signed(manifest)
        sealed = self._seal(body_bytes, scope, manifest, "request")
        record = {"capture_id": capture_id, "prepared": receipt, "request": sealed}
        returned = self.repository.call("prepare", {**scope.payload(), "record": record})
        if returned != record:
            raise AuditCaptureBlocked("Durable capture read-back differs from prepared evidence.")
        verified = verify_receipt(returned["prepared"], self.public_key)
        if not hmac.compare_digest(self._open(returned["request"], scope, verified), body_bytes):
            raise AuditCaptureBlocked("Durable capture body differs from transport body.")
        return CaptureHandle(self, scope, record)

    def read_capture(self, *, capture_id, workspace_id, reader_id, grant_nonce):
        self._allowed(workspace_id)
        record = self.repository.call("read", {"capture_id": _uuid(capture_id), "workspace_id": _uuid(workspace_id),
            "actor_id": _uuid(reader_id), "server_nonce": grant_nonce})
        prepared = verify_receipt(record["prepared"], self.public_key)
        scope = CaptureScope(prepared["workspace_id"], prepared["actor_id"], prepared["run_id"], prepared["grant_id"], grant_nonce, prepared["route"], prepared.get("reservation_id"))
        body = self._open(record["request"], scope, prepared)
        if hashlib.sha256(body).hexdigest() != prepared["body_sha256"] or len(body) != prepared["body_bytes"]:
            raise AuditCaptureBlocked("Captured request does not match its signed receipt.")
        result = {"capture_id": capture_id, "prepared": record["prepared"], "request_base64": _b64(body),
                  "request": record["request"], "state": record.get("state", "prepared"),
                  "network_started": record.get("network_started"), "outcome": record.get("outcome"),
                  "response": record.get("response"), "retention": "Live access only; no backup crypto-erasure claim."}
        if record.get("network_started"):
            started = verify_receipt(record["network_started"], self.public_key)
            if started["prepared_sha256"] != _receipt_digest(record["prepared"]):
                raise AuditCaptureBlocked("Dispatch receipt is not linked to this request.")
        if record.get("outcome"):
            outcome = verify_receipt(record["outcome"], self.public_key)
            if outcome["prepared_sha256"] != _receipt_digest(record["prepared"]):
                raise AuditCaptureBlocked("Outcome receipt is not linked to this request.")
            if record.get("response"):
                response = self._open(record["response"], scope, outcome)
                if hashlib.sha256(response).hexdigest() != outcome["response_sha256"] or len(response) != outcome["response_bytes"]:
                    raise AuditCaptureBlocked("Captured response does not match its signed receipt.")
                result["response_base64"] = _b64(response)
        return result

    def list_captures(self, *, grant_id, workspace_id, reader_id, grant_nonce):
        self._allowed(workspace_id)
        return self.repository.call("list", {"grant_id": _uuid(grant_id), "workspace_id": _uuid(workspace_id), "actor_id": _uuid(reader_id), "server_nonce": grant_nonce})

    def revoke_grant(self, *, grant_id, workspace_id, actor_id, server_nonce):
        self._allowed(workspace_id)
        return self.repository.call("revoke", {"grant_id": _uuid(grant_id), "workspace_id": _uuid(workspace_id), "actor_id": _uuid(actor_id), "server_nonce": server_nonce})

    def revoke_workspace(self, cur, *, workspace_id, actor_id):
        self._allowed(workspace_id)
        return self.repository.call("revoke_workspace", {"workspace_id": _uuid(workspace_id), "actor_id": _uuid(actor_id)}, cursor=cur)

    def purge_expired(self):
        return self.repository.call("purge", {})


class CaptureHandle:
    def __init__(self, service, scope, record):
        self.service, self.scope, self.record = service, scope, record
        self.physical_attempt_id = record["capture_id"]
        self._started = False
        self._finished = False

    def _manifest(self, kind):
        return {"kind": kind, "physical_attempt_id": self.physical_attempt_id,
            "prepared_sha256": _receipt_digest(self.record["prepared"]),
            "at": _stamp(), "deployment_sha": self.service.deployment_sha}

    def authorize_dispatch(self):
        if self._started:
            raise AuditCaptureBlocked("Physical dispatch capability is single-use.")
        receipt = self.service._signed(self._manifest("network_started"))
        self.service.repository.call("start", {**self.scope.payload(), "capture_id": self.physical_attempt_id, "receipt": receipt})
        self._started = True

    def record_response(self, raw_bytes, status, safe_headers):
        try:
            return self._record_response(raw_bytes, status, safe_headers)
        except AuditCaptureOutcomeUnknown:
            raise
        except Exception as error:
            raise AuditCaptureOutcomeUnknown("Dispatched response could not be fully evidenced.") from error

    def _record_response(self, raw_bytes, status, safe_headers):
        if not self._started or self._finished:
            raise AuditCaptureOutcomeUnknown("Response has no unique active dispatch.")
        if not isinstance(raw_bytes, bytes) or len(raw_bytes) > MAX_BODY_BYTES:
            self.record_failure("response_over_limit")
            raise AuditCaptureOutcomeUnknown("Complete response exceeded the private capture limit.")
        headers = {str(k).lower(): str(v) for k, v in safe_headers.items() if str(k).lower() in _SAFE_HEADERS}
        if any(len(value) > 4096 for value in headers.values()):
            self.record_failure("response_identifier_over_limit")
            raise AuditCaptureOutcomeUnknown("Complete response identifier exceeded the capture limit.")
        try:
            parsed = json.loads(raw_bytes)
        except (ValueError, UnicodeError):
            parsed = {}
        parsed = parsed if isinstance(parsed, dict) else {}
        provider_meta = parsed.get("providerMetadata", parsed.get("provider_metadata", {}))
        gateway = provider_meta.get("gateway", {}) if isinstance(provider_meta, dict) else {}
        manifest = {**self._manifest("response_observed"), "http_status": int(status),
            "response_sha256": hashlib.sha256(raw_bytes).hexdigest(), "response_bytes": len(raw_bytes),
            "response_complete": True, "headers": headers, "endpoint_request_id": headers.get("x-request-id", headers.get("request-id")),
            "endpoint_response_id": _safe_id(parsed.get("id")), "gateway_generation_id": _safe_id(gateway.get("generationId")) if isinstance(gateway, dict) else None,
            "response_model": _safe_id(parsed.get("model")), "usage": _usage(parsed.get("usage")), "gateway_metadata": _gateway(gateway),
            "upstream_request_id": None, "upstream_provider": _gateway(gateway).get("routing", {}).get("finalProvider"),
            "upstream_provider_source": "providerMetadata.gateway.routing.finalProvider" if _gateway(gateway).get("routing", {}).get("finalProvider") else None,
            "dispatch_boundary": "response_observed_from_exact_local_http_handoff", "provider_body_digest_attested": False}
        receipt = self.service._signed(manifest)
        sealed = self.service._seal(raw_bytes, self.scope, manifest, "response")
        try:
            self.service.repository.call("outcome", {**self.scope.payload(), "capture_id": self.physical_attempt_id, "receipt": receipt, "response": sealed})
        except Exception as error:
            raise AuditCaptureOutcomeUnknown("Dispatched response could not be durably captured.") from error
        self._finished = True

    def record_failure(self, error_type):
        if not self._started or self._finished:
            return
        # Caller supplies an exception class/enum, never exception text or body.
        if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", str(error_type)):
            error_type = "transport_unknown"
        try:
            receipt = self.service._signed({**self._manifest("dispatch_unknown"), "error_type": error_type})
            self.service.repository.call("outcome", {**self.scope.payload(), "capture_id": self.physical_attempt_id, "receipt": receipt})
        except Exception as error:
            raise AuditCaptureOutcomeUnknown("Dispatched attempt outcome is unknown.") from error
        self._finished = True


def _endpoint(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AuditCaptureBlocked("Audit route must be HTTPS without URL credentials or query parameters.")


def _no_credentials(body):
    # Exact originals must not be redacted and then labelled exact. Reject known
    # credential/signed-URL forms before retaining or dispatching an audit body.
    text = body.decode("utf-8")
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9_.-]{20,}|[?&](?:X-Amz-Signature|X-Goog-Signature|access_token|token|signature)=", text, re.I):
        raise ValueError("credential-bearing body")


def _safe_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,199}", value) else None


def _cost(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
        return str(parsed) if parsed.is_finite() and parsed >= 0 else None
    except InvalidOperation:
        return None


def _usage(value):
    if not isinstance(value, dict):
        return {}
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
    result = {k: value[k] for k in keys if type(value.get(k)) is int and value[k] >= 0}
    for key, allowed in (("prompt_tokens_details", ("cached_tokens",)), ("completion_tokens_details", ("reasoning_tokens",)),
                         ("input_tokens_details", ("cached_tokens",)), ("output_tokens_details", ("reasoning_tokens",))):
        detail = value.get(key)
        if isinstance(detail, dict):
            result[key] = {k: detail[k] for k in allowed if type(detail.get(k)) is int and detail[k] >= 0}
    if _cost(value.get("cost")) is not None:
        result["cost"] = _cost(value["cost"])
    return result


def _gateway(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    if _safe_id(value.get("generationId")):
        result["generationId"] = value["generationId"]
    if _cost(value.get("cost")) is not None:
        result["cost"] = _cost(value["cost"])
    routing = value.get("routing")
    if isinstance(routing, dict) and _safe_id(routing.get("finalProvider")):
        result["routing"] = {"finalProvider": routing["finalProvider"]}
    return result
