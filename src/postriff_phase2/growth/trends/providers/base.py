"""Bounded acquisition contracts and safe transport shared by admitted adapters."""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from ..contracts import ContractError, SCHEMA_VERSION, canonical, digest, instant, iso, validate_observation
from ..policy import SourcePolicy


@dataclass(frozen=True)
class Batch:
    observations: tuple[dict, ...] = ()
    cursor: dict | None = None
    completeness: str = "partial"
    health: str = "available"
    reason_code: str | None = None
    markers: tuple[dict, ...] = ()
    bytes_received: int = 0
    terminal_page: bool = False
    cost_microusd: int | None = None
    quarantined: tuple[dict, ...] = ()


def observation(*, policy: SourcePolicy, source_identity: str, revision_identity: str, sequence: int,
                kind: str, operation: str, payload: dict, event_at: str | None, received_at: str,
                available_at: str, coverage_epoch: str, contract_version: str, access_method: str,
                deletion_key: str | None = None) -> dict:
    expiry = min(instant(policy.expires_at), instant(available_at) + timedelta(seconds=policy.retention_seconds),
                 *(instant(grant["expires_at"]) for grant in policy.rights.values()))
    key = canonical([policy.scope_key, policy.provider_id, source_identity, revision_identity])
    row = {"schema_version": SCHEMA_VERSION, "observation_id": str(uuid5(NAMESPACE_URL, key)),
           "scope_key": policy.scope_key, "provider_id": policy.provider_id,
           "provider_contract_version": contract_version, "source_policy_version": policy.version,
           "source_identity": source_identity, "revision_identity": revision_identity,
           "revision_sequence": sequence, "operation": operation, "kind": kind,
           "event_at": event_at, "received_at": received_at, "available_at": available_at,
           "time_basis": "provider_event" if event_at else "retrieval", "coverage_epoch": coverage_epoch,
           "provenance": {"access_method": access_method, "policy_ref": policy.review_ref},
           "retention_until": iso(expiry), "rights": policy.rights, "deletion_key": deletion_key or source_identity,
           "payload": payload, "payload_digest": digest(payload)}
    return validate_observation(row)


def safe_url(url: str, *, allowed_hosts: frozenset[str] | None = None, resolve: bool = True) -> str:
    """Validate every remote fetch target. Redirects are separately refused by the transport."""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not parsed.hostname:
            raise ContractError("unsafe_url")
        host = parsed.hostname.lower().rstrip(".")
        if allowed_hosts is not None and host not in allowed_hosts:
            raise ContractError("unapproved_source_host")
        if host in ("localhost", "metadata.google.internal") or host.endswith((".localhost", ".local", ".internal")):
            raise ContractError("unsafe_url")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)] if resolve else []
        if any(not address.is_global for address in addresses):
            raise ContractError("unsafe_url")
        return urllib.parse.urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    except (ValueError, OSError) as exc:
        raise ContractError("unsafe_url") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ContractError("provider_redirect_refused")


class JsonTransport:
    """Only fixed operator-approved provider hosts; no arbitrary page reader or retry chain."""
    def __init__(self, allowed_hosts: frozenset[str]):
        if not allowed_hosts:
            raise ContractError("provider_host_required")
        self.allowed_hosts = allowed_hosts

    def get(self, url: str, *, max_bytes: int, timeout: int, headers: dict | None = None):
        url = safe_url(url, allowed_hosts=self.allowed_hosts)
        request = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ContractError("provider_response_too_large")
            try:
                return json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ContractError("invalid_number"))), dict(response.headers), len(data)
            except (ValueError, UnicodeError) as exc:
                raise ContractError("provider_invalid_json") from exc


def failure(status: int | None, *, retry_after: int | None = None) -> dict:
    code = {401: "access_pending", 403: "rights_suspended", 402: "budget_paused", 429: "rate_limited"}.get(status)
    terminal = status in (400, 404, 413, 422)
    return {"state": code or ("unsupported" if terminal else "health_degraded"),
            "retryable": status == 429 or (not terminal and status not in (401, 402, 403)),
            "retry_after_seconds": max(0, min(retry_after, 86400)) if type(retry_after) is int else None,
            "coverage": "gap", "count": None}
