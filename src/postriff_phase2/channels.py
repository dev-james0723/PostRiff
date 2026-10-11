"""Capability taxonomy (architecture §12.1): every capability is classified independently.

Levels: Direct (official API + production app/scopes verified), Assisted (export/hand-off,
no execution claim), Bridge (reviewed device workflow), Unsupported. Catalog presence is
never evidence; a level above Unsupported requires an evidence string and a verified_at.
"""
import math

from postriff_alpha.domain import AlphaError

CAPABILITIES = ("identity", "publish", "schedule", "analytics", "comments_read", "reply", "moderate", "media_types", "webhooks")
LEVELS = ("Direct", "Assisted", "Bridge", "Unsupported")
CONNECTION_STATES = ("disconnected", "identity_known", "scope_missing", "token_expired", "reauthorization_required", "client_binding_missing", "read_verified", "publish_verified")
# connection_state() values the person has to act on (reconnect or grant again); the Channels page's ATTENTION_STATES
# (web/src/lib/channels/state.ts). connectionState is computed for a view, never stored on the channel record.
ATTENTION_STATES = ("token_expired", "reauthorization_required", "scope_missing", "client_binding_missing")


def unsupported_matrix():
    return {name: {"level": "Unsupported", "evidence": "", "verifiedAt": None, "capabilityVersion": 0} for name in CAPABILITIES}


def assisted_matrix(reason="Rafii prepares the post; you publish it."):
    matrix = unsupported_matrix()
    matrix["publish"] = {"level": "Assisted", "evidence": reason, "verifiedAt": None, "capabilityVersion": 0}
    return matrix


def set_level(matrix, capability, level, evidence, verified_at, capability_version):
    if capability not in CAPABILITIES or level not in LEVELS:
        raise AlphaError("Unknown capability or level.", 400)
    if level != "Unsupported" and (not evidence or not verified_at):
        raise AlphaError("A capability level above Unsupported requires evidence and a verification time.", 409)
    matrix[capability] = {"level": level, "evidence": evidence[:400], "verifiedAt": verified_at, "capabilityVersion": capability_version}
    return matrix


def youtube_credential_status(cur, workspace_ids):
    """Secret-free vault facts; an access-token deadline is not a grant deadline."""
    if not workspace_ids:
        return {}
    cur.execute("SELECT workspace_id::text,connection_id,refresh_supported,refresh_ciphertext IS NOT NULL AND refresh_ciphertext<>'',extract(epoch from access_expires_at)::float8,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=ANY(%s::uuid[]) AND provider='youtube'", (list(workspace_ids),))
    return {(workspace, connection): {
        "refreshSupported": bool(supported and present and not revoked),
        # An encrypted refresh retained but intentionally disabled needs new consent;
        # it is not evidence that the customer revoked the Google grant.
        "refreshBindingRequired": bool(present and not supported and not revoked),
        "accessTokenExpiresAt": float(expires) if expires is not None else None,
        "revoked": bool(revoked),
    } for workspace, connection, supported, present, expires, revoked in cur.fetchall()}


def with_youtube_credential_status(channel, status):
    """Overlay current vault facts without changing the persisted channel or inventing grant expiry."""
    if channel.get("platform") != "YouTube":
        return channel
    if status is None:
        return {**channel, "refreshSupported": False}
    return {**channel, **status,
            "expiresAt": status["accessTokenExpiresAt"] if status["accessTokenExpiresAt"] is not None else channel.get("expiresAt"),
            "revoked": bool(channel.get("revoked") or status["revoked"])}


def connection_state(channel, now):
    """Provider-neutral OAuth candidate dimensions (improvement SPEC §5)."""
    if not channel.get("configured"):
        return "disconnected"
    if channel.get("revoked"):
        return "reauthorization_required"
    if not channel.get("identityVerified"):
        return "identity_known" if channel.get("providerAccountId") else "disconnected"
    refreshable_youtube = channel.get("platform") == "YouTube" and channel.get("refreshSupported") is True
    if channel.get("expiresAt", 0) <= now and not refreshable_youtube:
        return "client_binding_missing" if channel.get('refreshBindingRequired') else "token_expired"
    if not channel.get("scopes"):
        return "scope_missing"
    if channel.get("platform") == "Facebook" and channel.get("accountType") != "page":
        return "identity_known"
    if channel.get("capabilityVerified"):
        return "publish_verified"
    return "read_verified"


def customer_view(channel, matrix, now):
    """What the Channels card shows: identity, then one row per capability, never a blended 'Ready'."""
    # A successful identity re-check records channel.verifiedAt. Per-operation
    # evidence keeps its own timestamp and is never renewed by an identity read.
    identity_verified_at = channel.get("verifiedAt")
    if (not channel.get("identityVerified") or channel.get("revoked")
            or channel.get("evidenceSource") != "live_provider"
            or type(identity_verified_at) not in (int, float)
            or not math.isfinite(identity_verified_at) or not 0 < identity_verified_at <= now):
        identity_verified_at = None
    return {
        "id": channel["id"], "platform": channel["platform"], "account": channel["account"], "accountType": channel.get("accountType"),
        "connectionState": connection_state(channel, now),
        "identityVerifiedAt": identity_verified_at,
        "capabilities": {name: matrix.get(name, unsupported_matrix()[name]) for name in CAPABILITIES},
        "evidenceSource": channel.get("evidenceSource", "synthetic"),
        "scopes": list(channel.get("scopes", [])),
        "expiresAt": channel.get("expiresAt"),
        "refreshSupported": channel.get("refreshSupported") is True,
        "refreshBindingRequired": channel.get("refreshBindingRequired") is True,
        "authorizationLane": channel.get("authorizationLane", "standard") if channel.get("platform") == "YouTube" else None,
        "accessTokenExpiresAt": channel.get("accessTokenExpiresAt"),
    }
