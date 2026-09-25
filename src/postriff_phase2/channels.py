"""Capability taxonomy (architecture §12.1): every capability is classified independently.

Levels: Direct (official API + production app/scopes verified), Assisted (export/hand-off,
no execution claim), Bridge (reviewed device workflow), Unsupported. Catalog presence is
never evidence; a level above Unsupported requires an evidence string and a verified_at.
"""
from postriff_alpha.domain import AlphaError

CAPABILITIES = ("identity", "publish", "schedule", "analytics", "comments_read", "reply", "moderate", "media_types", "webhooks")
LEVELS = ("Direct", "Assisted", "Bridge", "Unsupported")
CONNECTION_STATES = ("disconnected", "identity_known", "scope_missing", "token_expired", "reauthorization_required", "read_verified", "publish_verified")


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


def connection_state(channel, now):
    """Provider-neutral OAuth candidate dimensions (improvement SPEC §5)."""
    if not channel.get("configured"):
        return "disconnected"
    if channel.get("revoked"):
        return "reauthorization_required"
    if not channel.get("identityVerified"):
        return "identity_known" if channel.get("providerAccountId") else "disconnected"
    if channel.get("expiresAt", 0) <= now:
        return "token_expired"
    if not channel.get("scopes"):
        return "scope_missing"
    if channel.get("capabilityVerified"):
        return "publish_verified"
    return "read_verified"


def customer_view(channel, matrix, now):
    """What the Channels card shows: identity, then one row per capability, never a blended 'Ready'."""
    return {
        "id": channel["id"], "platform": channel["platform"], "account": channel["account"], "accountType": channel.get("accountType"),
        "connectionState": connection_state(channel, now),
        "capabilities": {name: matrix.get(name, unsupported_matrix()[name]) for name in CAPABILITIES},
        "evidenceSource": channel.get("evidenceSource", "synthetic"),
        "scopes": list(channel.get("scopes", [])),
        "expiresAt": channel.get("expiresAt"),
    }
