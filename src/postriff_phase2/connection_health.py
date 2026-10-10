"""Connection Health Center (P1.4, contract `rafii-connection-health/1`): one truthful reading per platform and account.

What it answers for an ordinary member: is each account connected, authorized, syncing, ready, limited, expired, blocked
or unsupported; which permissions are missing (as capabilities, with the raw scope names kept behind a disclosure); when
Rafii last read data successfully and how old that data is; which publishing and analytics paths actually work; and what
Rafii's agent may do on its own (lane B1's permissions API when its flag is on, otherwise today's behaviour).

Rules this module keeps:
- **Off unless enabled.** `RAFII_CONNECTION_HEALTH_ENABLED` must be on *and* the workspace listed in
  `RAFII_CONNECTION_HEALTH_WORKSPACES` (empty = no workspace; `*` must be written explicitly). With the deployment flag
  off the HTTP route is not matched at all, so the request falls through to the same 404 every unknown route returns,
  and the Channels response is returned unchanged (`annotate_channels`).
- **Reuse, never re-derive authority.** The account rows come from `OAuthService.channels` (the Channels page's own
  reading: `channels.customer_view`, the YouTube vault overlay from #138, `connection_readiness`, the provider
  catalogue). Nothing here grants, refreshes, verifies or revokes anything, and no platform is called: every fact is
  Rafii's last stored record (`liveChecked: false`).
- **No false ready.** `ready` needs a valid grant *and* publishing *and* analytics both actually working for this
  account. A connected account whose stored capability rows still say Direct is reported `unavailable` on every line
  once its access expired, was revoked or is blocked; a capability whose scopes are no longer in the grant is
  `not_granted` whatever its row says.
- **One workspace.** Every SQL statement filters by `workspace_id` *and* the connection ids of that workspace. Connection
  ids are `sha256(provider:account)` and so repeat across workspaces that connected the same account.
- **Reconnect only through the existing OAuth flows.** The payload says which provider and account a reconnect targets
  and which capabilities are missing; the browser opens the existing Connect sheet (its `reconnectCapability` picks
  what to ask for again), which starts the provider's own OAuth (`POST …/channels/{provider}/oauth/start`,
  `manage_connections` checked on the server). Reconnect is offered only to members who hold `manage_connections`.
"""
from __future__ import annotations

import json
import os
import uuid

from postriff_alpha.domain import AlphaError

CONTRACT = "rafii-connection-health/1"
FLAG = "RAFII_CONNECTION_HEALTH_ENABLED"
WORKSPACES = "RAFII_CONNECTION_HEALTH_WORKSPACES"
HREF = "/app/channels/health"
PERMISSIONS_HREF = "/app/account/agent"

# Account and platform states, most urgent first (the platform summary takes the first one any account has).
STATES = ("expired", "blocked", "connected", "syncing", "limited", "authorized", "ready", "not_connected", "unsupported")
# What one capability line can say about this account (publishing, analytics, past posts, comments).
LINE_STATUSES = ("available", "on_request", "private_only", "assisted", "not_collected", "awaiting_review", "not_enabled",
                 "not_granted", "not_offered", "unavailable")
USABLE = frozenset(("available", "on_request", "private_only", "assisted"))
# Every reason code an account can carry; the browser has words for each (web/src/lib/channels/health-copy.json).
REASONS = ("platform_unavailable", "operator_paused", "youtube_policy_unavailable", "youtube_policy_review", "access_expired",
           "access_revoked", "reconnect_required", "account_only", "no_permissions", "access_expiring", "sync_running", "sync_failed",
           "publishing_off", "demo_account")
LINES = (("publishing", "publish"), ("analytics", "analytics"), ("history", "posts_read"), ("comments", "comments_read"))
# The capabilities a person can ask a platform for (oauth.start), in the Connect sheet's order.
GRANTABLE = ("publish", "analytics", "comments_read", "reply", "posts_read")

# channels.connection_state() values that carry a usable grant (web: state.ts VERIFIED_STATES). The attention states
# (token_expired, reauthorization_required, scope_missing, client_binding_missing; PR #158's channels.ATTENTION_STATES)
# map to expired / connected below.
VERIFIED = frozenset(("publish_verified", "read_verified"))
DISCONNECTED_EVIDENCE = "Disconnected by the customer."   # OAuthService.disconnect writes it on every capability row
EXPIRING_SOON_SECONDS = 7 * 86400                           # web/src/lib/channels/state.ts EXPIRING_SOON_SECONDS
RECENT_SECONDS = 2 * 86400                                  # data newer than this reads as "recent"

# Rafii reads post analytics in the background only for these (insights.INSIGHT_METRICS, growth/metric_schedule.py).
COLLECTED_ANALYTICS = {"Threads": "threads", "Instagram": "instagram"}

# Lane B1's GET payload (CF-2 §16): only these values pass through, anything else is dropped.
AUTONOMY_MODES = ("shadow", "enforce")
AUTONOMY_PRESETS = ("legacy", "none", "recommended", "full", "custom")
AUTONOMY_CATEGORIES = ("read_analyze", "navigate_interact", "create_edit", "manage_settings", "manage_connected_services", "execute_automations")
AUTONOMY_CATEGORY_MODES = ("ask", "assist")
AUTONOMY_EFFECTIVE = ("on", "asks", "off", "clipped", "unavailable")


# --- flags ------------------------------------------------------------------------------------------------------------
def _on(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def deployment_enabled(env=None) -> bool:
    return _on((os.environ if env is None else env).get(FLAG))


def listed_workspaces(env=None) -> frozenset:
    raw = str((os.environ if env is None else env).get(WORKSPACES) or "")
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def workspace_enabled(workspace_id, env=None) -> bool:
    """Server-enforced admission. An empty list admits nobody; `*` must be explicit."""
    if not deployment_enabled(env):
        return False
    listed = listed_workspaces(env)
    return "*" in listed or str(workspace_id or "").strip().lower() in listed


def environment(service):
    """The flag source: tests inject `service.connection_health_env`; the deployment reads its process environment."""
    injected = getattr(service, "connection_health_env", None)
    return injected if isinstance(injected, dict) else os.environ


def annotate_channels(payload, workspace_id, env=None):
    """The Channels response, plus where the Health Center lives when this workspace may open it. Unchanged otherwise."""
    if not workspace_enabled(workspace_id, env) or not isinstance(payload, dict):
        return payload
    return {**payload, "connectionHealth": {"available": True, "href": HREF}}


def unavailable():
    """Exactly what an unknown hosted route answers, so a workspace outside the list cannot tell the route exists."""
    return AlphaError("This hosted route is unavailable.", 404)


# --- pure mapping -----------------------------------------------------------------------------------------------------
def _scopes_held(platform, granted, required):
    if not required:
        return True
    if platform == "YouTube":
        from .youtube.model import has_scopes
        return has_scopes(granted, required)
    return set(required) <= set(granted)


def required_scopes(adapter, adapter_class, capability):
    """The scopes this capability needs, from the mounted adapter (LinkedIn's posts_read depends on its instance), else
    the adapter class. Empty when Rafii asks for nothing."""
    if adapter is not None:
        try:
            return list(adapter.capability_scopes(capability) or [])
        except Exception:  # noqa: BLE001 - unknown requirements must not become a grant
            return None
    scopes = getattr(adapter_class, "SCOPES", None) or {}
    return list(scopes.get(capability) or [])


def offered(provider, capability) -> bool:
    return bool(((provider or {}).get("capabilities") or {}).get(capability))


def _level(view, capability):
    return (((view.get("capabilities") or {}).get(capability)) or {}).get("level") or "Unsupported"


def _evidence(view, capability):
    value = (((view.get("capabilities") or {}).get(capability)) or {}).get("evidence")
    return value if isinstance(value, str) else ""


def disconnected_by_customer(view) -> bool:
    if view.get("connectionState") != "reauthorization_required":
        return False
    return any(isinstance(row, dict) and row.get("evidence") == DISCONNECTED_EVIDENCE for row in (view.get("capabilities") or {}).values())


def missing_permissions(view, provider, adapter, adapter_class):
    """Offered capabilities whose scopes this grant lacks: [{capability, scopes}], scopes only for the disclosure."""
    platform, granted = view.get("platform"), list(view.get("scopes") or [])
    out = []
    for capability in GRANTABLE:
        if not offered(provider, capability):
            continue
        required = required_scopes(adapter, adapter_class, capability)
        if not required or _scopes_held(platform, granted, required):
            continue
        if platform == "YouTube":
            missing = [scope for scope in required if not _scopes_held(platform, granted, [scope])]
        else:
            missing = sorted(set(required) - set(granted))
        out.append({"capability": capability, "scopes": missing})
    return out


def _granted(view, provider, adapter, adapter_class, capability):
    """True when the current grant holds this capability's scopes. Unknown requirements (no adapter class) never count."""
    required = required_scopes(adapter, adapter_class, capability)
    if required is None:
        return False
    if not required:
        return adapter is not None or adapter_class is not None
    return _scopes_held(view.get("platform"), view.get("scopes") or [], required)


def _awaiting_review(view, provider, capability):
    """The grant is there but the platform has not approved Rafii for it: the server's own evidence words, the readiness
    reading, or a catalogue entry that is not production-reviewed. Without any of these Rafii does not guess a reason."""
    evidence = _evidence(view, capability)
    readiness = (view.get("socialReadiness") or {}).get("publishing") if capability == "publish" else None
    return (evidence.startswith("Waiting for") or "hasn't approved" in evidence
            or readiness == "PUBLISHING_AWAITING_PROVIDER_REVIEW" or (provider or {}).get("productionReviewed") is False)


def publishing_line(view, provider, adapter, adapter_class):
    platform = view.get("platform")
    level = _level(view, "publish")
    held = _granted(view, provider, adapter, adapter_class, "publish")
    if level == "Direct" and held:
        if platform == "YouTube" and _level(view, "schedule") != "Direct":
            return {"status": "private_only"}   # public uploads wait for Google's audit (youtube.model.project_public_gate)
        return {"status": "available"}
    if not offered(provider, "publish"):
        return {"status": "assisted"} if level in ("Assisted", "Bridge") else {"status": "not_offered"}
    if not held:
        # Assisted still works without the grant: Rafii prepares the post and you publish it yourself.
        return {"status": "assisted", "grant": "publish"} if level in ("Assisted", "Bridge") else {"status": "not_granted", "grant": "publish"}
    if level in ("Assisted", "Bridge"):
        # You still finish the last step yourself; say why Rafii does not post directly when the server knows.
        return {"status": "assisted", **({"detail": "awaiting_review"} if _awaiting_review(view, provider, "publish") else {})}
    return {"status": "awaiting_review"} if _awaiting_review(view, provider, "publish") else {"status": "not_enabled"}


def analytics_line(view, provider, adapter, adapter_class, collection):
    platform = view.get("platform")
    if not offered(provider, "analytics"):
        return {"status": "not_offered"}
    if not _granted(view, provider, adapter, adapter_class, "analytics"):
        return {"status": "not_granted", "grant": "analytics"}
    if _level(view, "analytics") != "Direct":
        return {"status": "awaiting_review"} if _awaiting_review(view, provider, "analytics") else {"status": "not_enabled"}
    if platform == "YouTube":
        return {"status": "on_request"}     # creator reports are read when you open YouTube in Rafii, never in the background
    if platform in COLLECTED_ANALYTICS and collection.get(COLLECTED_ANALYTICS[platform]):
        return {"status": "available"}
    checklist = (provider or {}).get("readinessChecklist")
    if isinstance(checklist, dict) and checklist.get("analyticsPermission") is False:
        # The operator has not recorded the platform's approval of Rafii's analytics access (Instagram: Meta's review).
        return {"status": "awaiting_review"}
    return {"status": "not_collected"}


def history_line(view, provider, adapter, adapter_class):
    """Reading this account's own past posts when you choose them (Read my posts; `connection_readiness` history)."""
    if not offered(provider, "posts_read"):
        return {"status": "not_offered"}
    if view.get("platform") == "YouTube":
        # The channel's own videos are listed when you open YouTube in Rafii; there is no background import.
        if not _granted(view, provider, adapter, adapter_class, "posts_read"):
            return {"status": "not_granted", "grant": "posts_read"}
        # YouTube creator reads exist only where the deployment enabled them (youtube.model.capability_matrix).
        return {"status": "on_request"} if getattr(adapter, "creator_enabled", False) else {"status": "not_enabled"}
    readiness = (view.get("socialReadiness") or {}).get("history")
    if readiness == "HISTORICAL_IMPORT_AVAILABLE":
        return {"status": "on_request"}
    if readiness == "HISTORICAL_IMPORT_AWAITING_PROVIDER_APPROVAL":
        return {"status": "awaiting_review"}
    return {"status": "not_granted", "grant": "posts_read"}


def comments_line(view, provider, adapter, adapter_class):
    if not offered(provider, "comments_read"):
        return {"status": "not_offered"}
    if not _granted(view, provider, adapter, adapter_class, "comments_read"):
        return {"status": "not_granted", "grant": "comments_read"}
    if _level(view, "comments_read") != "Direct":
        return {"status": "awaiting_review"} if _awaiting_review(view, provider, "comments_read") else {"status": "not_enabled"}
    if view.get("platform") == "YouTube":
        return {"status": "on_request"}
    return {"status": "available"} if (provider or {}).get("commentsReadImplemented") else {"status": "not_collected"}


def inactive_lines(provider, status):
    """Every line for an account that cannot be used as it stands: stored rows may still say Direct after access ended."""
    return {name: ({"status": status, **({"grant": key} if status == "not_granted" else {})} if offered(provider, key) else {"status": "not_offered"})
            for name, key in LINES}


def access(view, now):
    """Token lifetime as the Channels card reads it: refreshable grants renew; an expiry within a week is called out."""
    state = view.get("connectionState")
    expires = view.get("expiresAt") if isinstance(view.get("expiresAt"), (int, float)) else None
    renews = view.get("refreshSupported") is True and state in VERIFIED
    if view.get("refreshBindingRequired") is True or state == "client_binding_missing":
        status = "reconnect_required"
    elif state == "token_expired":
        status = "expired"
    elif state == "reauthorization_required":
        status = "revoked"
    elif state in VERIFIED and not renews and expires is not None and 0 < expires - now < EXPIRING_SOON_SECONDS:
        status = "expiring"
    elif state in VERIFIED or state in ("identity_known", "scope_missing"):
        status = "active"
    else:
        status = "none"
    return {"status": status, "expiresAt": expires if not renews else None, "renewsAutomatically": renews}


def _sync(facts, collectable, now):
    """Last successful read, a newer failure, an import in progress, and how old the newest data is."""
    if facts is None:
        return ({"status": "unknown", "lastSuccessAt": None, "lastSuccessKind": None, "lastProblemAt": None},
                {"latestDataAt": None, "ageSeconds": None, "band": "unknown"})
    successes = [(at, kind) for at, kind in ((facts.get("analyticsAt"), "analytics"), (facts.get("readAt"), "analytics"),
                                             (facts.get("importDoneAt"), "history_import")) if isinstance(at, (int, float))]
    last_at, last_kind = max(successes) if successes else (None, None)
    problem = facts.get("problemAt") if isinstance(facts.get("problemAt"), (int, float)) else None
    if problem is not None and last_at is not None and problem <= last_at:
        problem = None
    if facts.get("importRunning"):
        status = "running"
    elif problem is not None:
        status = "failed"
    elif last_at is not None:
        status = "idle"
    else:
        status = "never" if collectable else "not_applicable"
    latest = facts.get("latestDataAt") if isinstance(facts.get("latestDataAt"), (int, float)) else None
    age = max(0.0, now - latest) if latest is not None else None
    band = "none" if latest is None else "recent" if age <= RECENT_SECONDS else "older"
    return ({"status": status, "lastSuccessAt": last_at, "lastSuccessKind": last_kind, "lastProblemAt": problem},
            {"latestDataAt": latest, "ageSeconds": age, "band": band})


def _provider_block(provider):
    if not provider or not provider.get("configured"):
        return "platform_unavailable"
    if provider.get("executionPaused"):
        return "operator_paused"
    if provider.get("connectReady") is False:
        return "platform_unavailable"
    return None


def reconnect_target(view, provider, can_manage, missing):
    """Where a reconnect or a missing grant sends the person: the existing Connect sheet for this provider and account.
    Which capability a plain reconnect asks for again is the browser's `reconnectCapability` (state.ts), from `capabilities`."""
    if not provider or not provider.get("id"):
        return {"available": False, "reason": "platform_unavailable"}
    block = _provider_block(provider)
    if block:
        return {"available": False, "reason": block}
    if not can_manage:
        return {"available": False, "reason": "manage_required"}
    grants = {entry["capability"] for entry in missing}
    return {"available": True, "providerId": provider["id"], "channelId": view.get("id"), "account": view.get("account"),
            "grants": [name for name in GRANTABLE if name in grants]}


def account_health(view, provider, *, adapter=None, adapter_class=None, facts=None, collection=None, history_enabled=False,
                   can_manage=False, youtube_policy=None, publishing_live=False, now):
    """One account's truthful reading. `view` is a Channels row (customer_view + socialReadiness); `provider` its
    catalogue entry; `facts` the sync facts for this workspace and connection, or None when they could not be read."""
    collection = collection or {}
    state_name = view.get("connectionState")
    missing = missing_permissions(view, provider, adapter, adapter_class)
    reasons = []
    block = _provider_block(provider)
    if view.get("platform") == "YouTube" and isinstance(youtube_policy, dict) and youtube_policy.get("requiredForConnection"):
        if not youtube_policy.get("ready"):
            block = block or "youtube_policy_unavailable"
        elif not youtube_policy.get("accepted"):
            reasons.append("youtube_policy_review")
    lifetime = access(view, now)
    if block:
        state, reasons = "blocked", [block, *reasons]
    elif lifetime["status"] in ("expired", "revoked", "reconnect_required"):
        state = "expired"
        reasons.insert(0, {"expired": "access_expired", "revoked": "access_revoked", "reconnect_required": "reconnect_required"}[lifetime["status"]])
    elif state_name == "identity_known":
        state = "connected"
        reasons.insert(0, "account_only")
    elif state_name == "scope_missing":
        state = "connected"
        reasons.insert(0, "no_permissions")
    elif state_name not in VERIFIED:
        state = "not_connected"
    elif not any(_granted(view, provider, adapter, adapter_class, key) for key in GRANTABLE if offered(provider, key)):
        # A valid grant that holds nothing beyond the account itself (the "Account only" choice).
        state = "connected"
        reasons.insert(0, "account_only")
    else:
        state = None
    if state is None or (state == "connected" and state_name in VERIFIED):
        lines = {"publishing": publishing_line(view, provider, adapter, adapter_class),
                 "analytics": analytics_line(view, provider, adapter, adapter_class, collection),
                 "history": history_line(view, provider, adapter, adapter_class),
                 "comments": comments_line(view, provider, adapter, adapter_class)}
        # A working grant is not a working publisher (capabilities.publish_route): this deployment must carry live
        # transport, and a demo record never publishes anywhere.
        demo = view.get("evidenceSource", "synthetic") == "synthetic"
        if lines["publishing"]["status"] in ("available", "private_only") and (demo or not publishing_live):
            lines["publishing"] = {"status": "not_enabled"}
            reasons.append("demo_account" if demo else "publishing_off")
    else:
        lines = inactive_lines(provider, "not_granted" if state == "connected" else "unavailable")
    collectable = lines["analytics"]["status"] == "available" or (history_enabled and view.get("platform") in COLLECTED_ANALYTICS
                                                                 and lines["analytics"]["status"] in ("available", "not_collected"))
    sync, freshness = _sync(facts, collectable, now)
    if state is None:
        if sync["status"] == "running":
            state = "syncing"
            reasons.append("sync_running")
        elif (sync["status"] != "failed" and "youtube_policy_review" not in reasons
              and lines["publishing"]["status"] == "available" and lines["analytics"]["status"] in ("available", "on_request")):
            state = "ready"
        elif any(line["status"] in USABLE for line in lines.values()):
            state = "limited"
        else:
            state = "authorized"
        if sync["status"] == "failed":
            reasons.append("sync_failed")
    if lifetime["status"] == "expiring":
        reasons.append("access_expiring")
    identity = ((view.get("capabilities") or {}).get("identity")) or {}
    verified_at = identity.get("verifiedAt") if isinstance(identity.get("verifiedAt"), (int, float)) else None
    return {
        "channelId": view.get("id"), "platform": view.get("platform"), "account": view.get("account"),
        "accountType": view.get("accountType"), "connectionState": state_name, "state": state, "reasons": reasons,
        "attention": state in ("expired", "blocked") or bool(set(reasons) & {"no_permissions", "access_expiring", "sync_failed", "youtube_policy_review"}),
        "lines": lines, "missingPermissions": missing, "access": lifetime, "lastVerifiedAt": verified_at,
        "sync": sync, "freshness": freshness,
        "authorizationLane": view.get("authorizationLane") if view.get("platform") == "YouTube" else None,
        "capabilities": {name: {"level": row.get("level")} for name, row in (view.get("capabilities") or {}).items() if isinstance(row, dict)},
        "reconnect": reconnect_target(view, provider, can_manage, missing),
        "pictureDigest": view.get("pictureDigest"),
    }


def platform_state(provider, accounts):
    """A platform's summary: its most urgent account, or whether it can be connected here at all."""
    if accounts:
        return min((a["state"] for a in accounts), key=STATES.index)
    if not provider or not provider.get("configured") or provider.get("connectReady") is False:
        return "unsupported"
    if provider.get("executionPaused"):
        return "blocked"
    return "not_connected"


def build(channels_payload, *, adapters, facts, collection, history_enabled, can_manage, youtube_policy, autonomy, now,
          publishing_live=False):
    """The whole Health Center payload from the Channels reading plus this workspace's sync facts."""
    from .providers import adapter_class_for_platform
    providers = [p for p in (channels_payload.get("providers") or []) if isinstance(p, dict) and p.get("platform")]
    by_platform = {p["platform"]: p for p in providers}
    grouped = {}
    for view in channels_payload.get("channels") or []:
        if not isinstance(view, dict) or disconnected_by_customer(view):
            continue
        provider = by_platform.get(view.get("platform"))
        adapter = adapters.get(provider["id"]) if provider and provider.get("id") else None
        grouped.setdefault(view.get("platform"), []).append(account_health(
            view, provider, adapter=adapter, adapter_class=adapter_class_for_platform(view.get("platform")),
            facts=facts.get(view.get("id")) if facts is not None else None, collection=collection,
            history_enabled=history_enabled, can_manage=can_manage, youtube_policy=youtube_policy,
            publishing_live=publishing_live, now=now))
    platforms = []
    for name in list(by_platform) + [p for p in grouped if p not in by_platform]:
        provider = by_platform.get(name)
        accounts = sorted(grouped.get(name, []), key=lambda a: (STATES.index(a["state"]), str(a.get("account") or "")))
        platforms.append({"platform": name, "providerId": (provider or {}).get("id"), "state": platform_state(provider, accounts),
                          "connectable": bool(provider and provider.get("configured") and provider.get("connectReady") is not False and not provider.get("executionPaused")),
                          "reviewed": bool((provider or {}).get("productionReviewed")), "accounts": accounts})
    platforms.sort(key=lambda p: (0 if p["accounts"] else 1, STATES.index(p["state"]), p["platform"]))
    counts = {state: 0 for state in STATES}
    for platform in platforms:
        for account in platform["accounts"]:
            counts[account["state"]] += 1
    return {"contract": CONTRACT, "generatedAt": now, "liveChecked": False, "evidence": "stored_records",
            "canManage": bool(can_manage), "counts": counts,
            "attention": sum(1 for p in platforms for a in p["accounts"] if a["attention"]),
            "platforms": platforms, "autonomy": autonomy}


# --- agent autonomy (lane B1, read-only) ------------------------------------------------------------------------------
def permissions_mode(workspace_id, env, service=None):
    """Lane B1's own gate (`RuntimeConfig.permissions_for`, CF-2 §15). Until B1 merges it does not exist: 'off'."""
    from .agent_runtime_v2.config import RuntimeConfig
    config = getattr(service, "agent_permissions_config", None)
    if config is None:
        config = getattr(getattr(service, "agent_runtime", None), "cfg", None)
    if config is None:
        config = RuntimeConfig.from_environment(env)
    reader = getattr(config, "permissions_for", None)
    if not callable(reader):
        return "off"
    mode = reader(workspace_id)
    return mode if mode in AUTONOMY_MODES else "off"


def summarize_permissions(payload, mode):
    """B1's GET body (CF-2 §16) reduced to allowlisted values; anything unexpected becomes 'unavailable', never 'off'."""
    if not isinstance(payload, dict) or payload.get("available") is not True:
        return {"source": "unavailable", "mode": mode, "href": None}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    categories = []
    for row in payload.get("categories") or []:
        if not isinstance(row, dict) or row.get("id") not in AUTONOMY_CATEGORIES:
            continue
        effective = row.get("effective") if isinstance(row.get("effective"), dict) else {}
        categories.append({"id": row["id"], "mode": row.get("mode") if row.get("mode") in AUTONOMY_CATEGORY_MODES else None,
                           "effective": effective.get("state") if effective.get("state") in AUTONOMY_EFFECTIVE else "unavailable"})
    return {"source": "agent_permissions", "mode": mode, "preset": state.get("preset") if state.get("preset") in AUTONOMY_PRESETS else None,
            "needsChoice": state.get("needsChoice") is True, "categories": categories, "href": PERMISSIONS_HREF}


def autonomy_summary(cur, workspace_id, principal, membership, state, now, env, service=None):
    try:
        mode = permissions_mode(workspace_id, env, service)
    except Exception:  # noqa: BLE001 - an unreadable runtime configuration is reported as unknown, never as "off"
        return {"source": "unavailable", "mode": None, "href": None}
    if mode == "off":
        return {"source": "todays_behaviour", "mode": "off", "href": None}
    def read(cur_):
        from .agent_runtime_v2 import agent_permissions
        return agent_permissions.view(cur_, workspace_id, principal, membership, state, mode=mode, now=now)
    return summarize_permissions(_guarded(cur, read), mode)


# --- facts (one workspace) --------------------------------------------------------------------------------------------
def _guarded(cur, action):
    """Run one read in a savepoint: a missing table or a failed read becomes None (unknown), never an empty answer."""
    mark = "connection_health_" + uuid.uuid4().hex[:8]
    try:
        cur.execute(f"SAVEPOINT {mark}")
    except Exception:  # noqa: BLE001 - the transaction is already unusable
        return None
    try:
        result = action(cur)
    except Exception:  # noqa: BLE001 - see docstring
        cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
        cur.execute(f"RELEASE SAVEPOINT {mark}")
        return None
    cur.execute(f"RELEASE SAVEPOINT {mark}")
    return result


OBSERVATIONS_SQL = ("SELECT connection_id,extract(epoch from max(ingested_at)),extract(epoch from max(observed_at)) "
                    "FROM public.pr_metric_observations WHERE workspace_id=%s AND connection_id=ANY(%s) AND availability='available' "
                    "GROUP BY connection_id")
READS_SQL = ("SELECT connection_id,extract(epoch from max(observed_at) FILTER (WHERE status='done')),"
             "extract(epoch from max(updated_at) FILTER (WHERE status IN ('dead','unavailable'))) "
             "FROM public.pr_metric_reads WHERE workspace_id=%s AND connection_id=ANY(%s) GROUP BY connection_id")
IMPORTS_SQL = ("SELECT DISTINCT ON (connection_id) connection_id,status,extract(epoch from updated_at) "
               "FROM public.pr_history_imports WHERE workspace_id=%s AND connection_id=ANY(%s) "
               "ORDER BY connection_id,created_at DESC")


def _epoch(value):
    return float(value) if value is not None else None


def sync_facts(cur, workspace_id, connection_ids):
    """{connection_id: facts} for this workspace only, or None when the facts could not be read at all."""
    ids = sorted({str(c) for c in connection_ids if c})
    facts = {c: {} for c in ids}
    if not ids:
        return facts

    def observations(cur_):
        cur_.execute(OBSERVATIONS_SQL, (workspace_id, ids))
        return cur_.fetchall()

    def reads(cur_):
        cur_.execute(READS_SQL, (workspace_id, ids))
        return cur_.fetchall()

    def imports(cur_):
        cur_.execute(IMPORTS_SQL, (workspace_id, ids))
        return cur_.fetchall()

    rows = {name: _guarded(cur, fn) for name, fn in (("observations", observations), ("reads", reads), ("imports", imports))}
    if any(value is None for value in rows.values()):
        return None   # part of the picture is missing: report "unknown", never a partial answer as if complete
    for connection_id, ingested, observed in rows["observations"] or []:
        if connection_id in facts:
            facts[connection_id].update(analyticsAt=_epoch(ingested), latestDataAt=_epoch(ingested))
    for connection_id, done, failed in rows["reads"] or []:
        if connection_id in facts:
            facts[connection_id].update(readAt=_epoch(done), problemAt=_epoch(failed))
    for connection_id, status, updated in rows["imports"] or []:
        if connection_id not in facts:
            continue
        entry = facts[connection_id]
        if status in ("pending", "running"):
            entry["importRunning"] = True
        elif status == "done":
            entry["importDoneAt"] = _epoch(updated)
            entry["latestDataAt"] = max(v for v in (entry.get("latestDataAt"), _epoch(updated)) if v is not None)
        elif status == "failed":
            entry["problemAt"] = max(v for v in (entry.get("problemAt"), _epoch(updated)) if v is not None)
    return facts


# --- service ----------------------------------------------------------------------------------------------------------
class ConnectionHealth:
    """`GET /api/workspaces/{w}/connection-health`: session reads only; any active member, like the Channels list."""

    def __init__(self, service, env=None):
        self.service = service
        self.env = environment(service) if env is None else env

    def _collection(self, workspace_id):
        reads = getattr(self.service, "metric_reads", None)
        if reads is None or not reads.workspace_allowed(workspace_id):
            return {}
        return {provider: bool(reads.provider_allowed(provider)) for provider in COLLECTED_ANALYTICS.values()}

    def _youtube_policy(self, workspace_id, token, payload):
        if not any(isinstance(v, dict) and v.get("platform") == "YouTube" for v in payload.get("channels") or []):
            return None
        policy = getattr(self.service.oauth, "youtube_policy", None)
        if policy is None:
            return None
        try:
            status = policy.status(workspace_id, token)
        except AlphaError:
            return None
        return {key: status.get(key) is True for key in ("ready", "requiredForConnection", "accepted")}

    def read(self, workspace_id, token):
        from .api_tokens import is_api_token
        from .hosted import _membership
        if is_api_token(token):
            raise AlphaError("Sign in to see connection health.", 403, code="token_scope_denied")
        oauth = self.service.oauth
        # Membership first (403 "Workspace unavailable." for anyone else), so the list itself is never probed.
        payload = oauth.channels(workspace_id, token)
        if not workspace_enabled(workspace_id, self.env):
            raise unavailable()
        ids = [v.get("id") for v in payload.get("channels") or [] if isinstance(v, dict)]
        now = oauth.clock()
        youtube_policy = self._youtube_policy(workspace_id, token, payload)
        with oauth.repository.transaction(token, workspace_id) as (cur, row, principal):
            membership = _membership(row)
            facts = sync_facts(cur, workspace_id, ids)
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1] if isinstance(row[1], dict) else {}
            autonomy = autonomy_summary(cur, workspace_id, principal, membership, state, now, self.env, self.service)
        return build(payload, adapters=dict(oauth.providers or {}), facts=facts, collection=self._collection(workspace_id),
                     history_enabled=getattr(self.service, "history_import", None) is not None,
                     can_manage=membership.allows("manage_connections"), youtube_policy=youtube_policy,
                     autonomy=autonomy, now=now, publishing_live=getattr(self.service, "publishing_live", False) is True)
