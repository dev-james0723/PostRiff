"""Operation eligibility: a read-only projection over the authorities the application already keeps.

One operation so far, `analytics.read`: showing stored, provider-native owned analytics for one connected account.
Every axis is derived from existing records — the workspace channel, the encrypted credential's granted scopes and
revocation (`pr_encrypted_credentials`), the `analytics` capability row (`pr_channel_capabilities`), the account
deletion marker and stored native observations. Nothing here is a grant authority: no row is written, no provider
is called and nothing is cached between requests.

Unknown is never treated as allowed. The application does not record a platform's own app-review decision, so
`platformApproval` stays 'unknown' and is listed in `unverifiedAxes`; `usableNow` covers only the axes the
application can verify (operator review recorded as Direct, a current grant with the native analytics scopes, no
account deletion). A stored native reading is evidence that a read once succeeded, not that one would succeed now.
"""
from __future__ import annotations

import math

from .contracts import digest
from .growth.metric_schedule import NATIVE_ANALYTICS_SCOPES

SCHEMA_VERSION = "operation-eligibility-v1"
ANALYTICS_READ = "analytics.read"
STALE_SECONDS = 7 * 86400
# The reasons that a minimal repair by the account owner can clear; anything else waits on review or support.
_RECONNECT = ("connection_revoked", "connection_expired", "credential_missing", "credential_revoked",
              "credential_provider_mismatch", "scope_missing")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def analytics_read(workspace_id, connection_id, channel, capability, credential, *, account_deletion, now,
                   latest_reading=None, environment="production"):
    """Pure projection for one connection.

    channel: the workspace channel dict or None; capability: {"level", "evidence"} or None; credential:
    {"provider", "scopes", "revoked"} or None; latest_reading: {"id", "observedAt"} of the newest stored available
    native observation for this connection, or None.
    """
    provider = str((channel or {}).get("platform") or (credential or {}).get("provider") or "").lower()
    required = NATIVE_ANALYTICS_SCOPES.get(provider)
    granted = sorted({s for s in (credential or {}).get("scopes") or [] if isinstance(s, str)})
    reasons = []
    if not required:
        reasons.append("operation_not_supported")
    if channel is None:
        grant = "missing"
        reasons.append("account_not_in_workspace")
    elif account_deletion:
        grant = "revoked"
        reasons.append("account_deletion")
    elif channel.get("revoked"):
        grant = "revoked"
        reasons.append("connection_revoked")
    elif _finite(channel.get("expiresAt")) and channel["expiresAt"] <= now:
        grant = "expired"
        reasons.append("connection_expired")
    elif credential is None:
        grant = "missing"
        reasons.append("credential_missing")
    elif credential.get("revoked"):
        grant = "revoked"
        reasons.append("credential_revoked")
    elif str(credential.get("provider") or "").lower() != provider:
        grant = "missing"
        reasons.append("credential_provider_mismatch")
    elif required and not required <= set(granted):
        grant = "downgraded"
        reasons.append("scope_missing")
    else:
        grant = "valid"
    level = (capability or {}).get("level")
    if level != "Direct":
        reasons.append("capability_not_direct")
    usable = not reasons
    observed = (latest_reading or {}).get("observedAt")
    verified = "passed" if _finite(observed) else "not_run"
    freshness = "unknown" if not _finite(observed) else "fresh" if now - observed <= STALE_SECONDS else "stale"
    if usable:
        repair = "none"
    elif channel is None:
        repair = "select_account"
    elif any(r in _RECONNECT for r in reasons):
        repair = "reconnect"
    else:
        repair = "await_review"
    return {
        "schemaVersion": SCHEMA_VERSION, "workspaceId": workspace_id, "provider": provider or None, "accountId": connection_id,
        "operation": ANALYTICS_READ, "environment": environment,
        "engineering": "runtime_bound" if required else "absent",
        "operatorReview": (level or "absent").lower(),
        "platformApproval": "unknown",
        "userGrant": grant,
        "nativeVerification": verified,
        "dataFreshness": freshness,
        "grantedScopes": granted,
        "requiredScopes": sorted(required or ()),
        "lastVerifiedAt": observed if _finite(observed) else None,
        "evidenceReceiptId": (latest_reading or {}).get("id") if _finite(observed) else None,
        "usableNow": usable,
        "blockedReasons": reasons,
        "unverifiedAxes": ["platformApproval"] + ([] if verified == "passed" else ["nativeVerification"]),
        "repairAction": repair,
    }


def rights_epoch(projections):
    """A digest of the rights axes only. New readings change freshness, never the epoch."""
    keys = ("provider", "operatorReview", "userGrant", "grantedScopes", "usableNow", "blockedReasons")
    return digest({cid: {k: p[k] for k in keys} for cid, p in sorted(projections.items())})


def load_analytics_read(cur, workspace_id, state, now, *, lock=False):
    """{connection_id: projection} for every channel in this workspace, read on the caller's cursor.

    With lock=True the capability and credential rows are held FOR SHARE, so a concurrent disconnect, scope downgrade
    or capability demotion commits either before this read (and is seen) or after the caller's transaction."""
    suffix = " FOR SHARE" if lock else ""
    cur.execute("SELECT connection_id,level,evidence FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability='analytics'" + suffix,
                (workspace_id,))
    capabilities = {r[0]: {"level": r[1], "evidence": r[2]} for r in cur.fetchall()}
    cur.execute("SELECT connection_id,provider,scopes,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s" + suffix,
                (workspace_id,))
    credentials = {r[0]: {"provider": r[1], "scopes": list(r[2] or []), "revoked": bool(r[3])} for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (connection_id) connection_id,id::text,extract(epoch from observed_at)::float8
                   FROM public.pr_metric_observations WHERE workspace_id=%s AND availability='available'
                   ORDER BY connection_id,observed_at DESC,id DESC""", (workspace_id,))
    readings = {r[0]: {"id": r[1], "observedAt": float(r[2])} for r in cur.fetchall()}
    deletion = bool(state.get("accountDeletion"))
    channels = {c.get("id"): c for c in (state.get("phase2") or {}).get("channels") or [] if isinstance(c, dict) and c.get("id")}
    return {cid: analytics_read(workspace_id, cid, channel, capabilities.get(cid), credentials.get(cid), account_deletion=deletion,
                                now=now, latest_reading=readings.get(cid))
            for cid, channel in channels.items()}
