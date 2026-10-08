"""Lane D — server-created capability manifest (spec §6.1). Built from explicit per-journey allowlists filtered by ToolSpec
tenant/effect; never by iterating the global tool registry.

Frozen entry points:
- build_manifest(cur, auth, projection, *, scope='workspace') -> dict (server record incl. SERVER_ONLY_MANIFEST_KEYS)
- query_binding(manifest, name) -> dict | None ; action_binding(manifest, action_id) -> dict | None
- current(cur, auth, manifest) -> dict  (re-check permission revision / expiry before every query, action, refresh, replay)

A manifest limits authority; it never grants any. It names which bindings and controls one artifact may use. Every
request still re-authenticates, re-reads membership and passes the binding's own requirement class against the member
as they are *now*. `current()` raises when the capability expired or belongs to another scope, and returns a view whose
action list is narrowed to what the current role allows (a demoted editor sees no write controls; a member who left the
workspace never gets here because `ui_transaction` refuses them first).

Also here: `load_artifact(cur, auth, artifact_id)`, the one place lane D reads `pr_ui_artifacts` (F owns the writes). A
foreign, unknown or other-scope id is the same 404, so ids cannot be probed.
"""
from __future__ import annotations

import datetime as dt
import json
import time

from postriff_alpha.domain import AlphaError

from . import ui_contracts, ui_domain
from .ui_domain import common

QUERY_TTL_SECONDS = 30 * 86400        # read bindings of a conversation's views; every call is still re-authorized
ACTION_TTL_SECONDS = 24 * 3600        # write controls expire with the proposal TTL; afterwards ask Rafii again
MANIFEST_VERSION = 1


def _unavailable() -> AlphaError:
    return AlphaError("That view is unavailable.", 404, code="ui_artifact")


def _now() -> float:
    return time.time()


def permission_revision(member) -> str:
    """A digest of the member's role and flags: a change between issue and use narrows the capability."""
    summary = member.summary() if hasattr(member, "summary") else {}
    return ui_contracts.sha256_text(ui_contracts.canonical_json({"role": getattr(member, "role", None), "summary": summary}, max_depth=None))


def _allows(member, requirement: str) -> bool:
    try:
        return bool(member.allows(requirement))
    except Exception:  # noqa: BLE001 — an unknown requirement fails closed
        return False


# Effects of the existing tools lane D's bindings wrap. A binding is kept only when the live spec (if loaded) agrees.
KNOWN_TOOLS = {"draft_edit": ("workspace", "MUTATE_REVERSIBLE"), "schedule_propose": ("workspace", "PREPARE_EXTERNAL"),
               "automation_change_propose": ("workspace", "MUTATE_REVERSIBLE"), "campaign_link": ("workspace", "MUTATE_REVERSIBLE"),
               "campaign_unlink": ("workspace", "MUTATE_REVERSIBLE"), "relationships": ("workspace", "READ"), "pending_approvals": ("workspace", "READ"),
               "campaign_items": ("workspace", "READ"), "memory_context": ("workspace", "READ"), "web_research": ("workspace", "READ"),
               "founder_metric_query": ("founder", "READ"), "founder_cost_breakdown": ("founder", "READ"), "founder_attention_list": ("founder", "READ"),
               "founder_incident_read": ("founder", "READ"), "founder_source_health": ("founder", "READ"), "founder_entity_search": ("founder", "READ"),
               "founder_entity_lookup": ("founder", "READ"), "founder_chart_explain": ("founder", "READ")}


def tool_ok(name: str | None, *, scope: str, effect: str) -> bool:
    """When a binding wraps an existing tool, that tool's own spec must agree with the binding's tenant and effect. The
    lookup is by explicit name; nothing iterates a registry."""
    if not name:
        return True
    if "." in name:
        from ..site_agent import tools as site_tools
        tool = site_tools.CATALOG.get(name)
        return tool is not None and scope == "workspace" and (tool["effect"] == "read") == (effect == "READ")
    expected = KNOWN_TOOLS.get(name)
    if expected is None or expected != (scope, effect):
        return False
    from . import tool_adapter
    tool = tool_adapter.REGISTRY.get(name)
    if tool is None:
        return True   # not registered in this process (e.g. founder tools outside the control mount): name-checked above
    tenant = "founder" if tool.spec.tenant == tool_adapter.FOUNDER_TENANT else "workspace"
    return tenant == scope and tool.spec.effect == effect


def _journeys(projection: dict, scope: str) -> list[str]:
    allowed = ui_contracts.FOUNDER_JOURNEYS if scope == "founder" else ui_contracts.CONSUMER_JOURNEYS
    raw = projection.get("journey_ids") or projection.get("journeyIds") or []
    return [j for j in dict.fromkeys(raw) if j in allowed]


def build_manifest(cur, auth, projection, *, scope='workspace', flags=None):
    """The server record for one artifact: per-journey allowlisted query bindings and the action controls this member's
    role allows, with the server-only metadata (principal, scope, permission revision, egress, approved refs, query
    constraints, action targets, expiry). Never contains tokens, signed URLs or private text."""
    _ = cur
    if scope not in ui_domain.SCOPES or scope != (getattr(auth, "scope", None) or "workspace"):
        raise _unavailable()
    projection = projection or {}
    journeys = _journeys(projection, scope)
    issued = _now()
    queries, constraints = [], {}
    for journey in journeys:
        for name in ui_domain.JOURNEY_QUERIES.get(journey, []):
            binding = ui_domain.QUERIES[name]
            if binding.scope != scope or not tool_ok(binding.tool, scope=scope, effect="READ") or not _allows(auth.member, binding.requirement):
                continue
            queries.append(ui_domain.public_query(binding))
            constraints[name] = {"requirement": binding.requirement, "pageMax": ui_contracts.BOUNDS["queryPageMax"],
                                 "windowDays": ui_contracts.BOUNDS["queryWindowDays"], "search": binding.search}
    actions, targets = [], {}
    # With the actions kill switch off (flags from RuntimeConfig.genui_for), the presenter is offered no write control at all;
    # the action routes refuse independently either way.
    if scope == "workspace" and (flags is None or flags.get("actions")):
        for journey in journeys:
            for action_id in ui_domain.JOURNEY_ACTIONS.get(journey, []):
                binding = ui_domain.ACTIONS[action_id]
                if not tool_ok(binding.tool, scope=scope, effect=binding.effect) or not _allows(auth.member, binding.requirement):
                    continue   # never offered to a role that can't use it; the native page explains why
                actions.append(ui_domain.public_action(binding))
                targets[action_id] = {"requirement": binding.requirement, "effect": binding.effect, "prepareOnly": binding.prepare_only,
                                      "expiresAt": common.iso(issued + ACTION_TTL_SECONDS)}
    source = {"journeys": journeys, "queries": [q["name"] for q in queries], "actions": [a["actionId"] for a in actions], "scope": scope,
              "principal": auth.principal, "workspace": auth.workspace_id, "issued": issued}
    manifest_id = "mf_" + ui_contracts.sha256_text(ui_contracts.canonical_json(source, max_depth=None))[:32]
    groups = list(dict.fromkeys(projection.get("component_group_ids") or projection.get("componentGroups") or []))
    return {"manifestId": manifest_id, "version": MANIFEST_VERSION, "bindingVersion": 1, "journeyIds": journeys, "componentGroups": groups,
            "queries": queries, "actions": actions, "expiresAt": common.iso(issued + QUERY_TTL_SECONDS),
            # --- server-only (ui_contracts.SERVER_ONLY_MANIFEST_KEYS); public_manifest() never copies these ---
            "principal": auth.principal, "scope": scope, "scopeKey": getattr(auth, "scope_key", "") or "", "workspaceId": auth.workspace_id,
            "role": getattr(auth.member, "role", None) or getattr(auth, "role", "") or "", "permissionRevision": permission_revision(auth.member),
            "egress": dict(projection.get("egress_decision") or {}), "approvedRefs": list((projection.get("allowed_context") or {}).get("refs") or [])[:60],
            "queryConstraints": constraints, "actionTargets": targets, "proposalDigests": {}, "issuedAt": issued}


def query_binding(manifest, name):
    """The manifest's entry for a read binding with its catalog record; None when the manifest doesn't carry it."""
    if not isinstance(manifest, dict) or not ui_contracts.valid_name(name):
        return None
    if not any(isinstance(q, dict) and q.get("name") == name for q in manifest.get("queries") or []):
        return None
    binding = ui_domain.QUERIES.get(name)
    if binding is None or binding.scope != (manifest.get("scope") or "workspace"):
        return None
    return {"name": name, "binding": binding, "constraints": (manifest.get("queryConstraints") or {}).get(name) or {}}


def action_binding(manifest, action_id):
    if not isinstance(manifest, dict) or not ui_contracts.valid_name(action_id) or (manifest.get("scope") or "workspace") != "workspace":
        return None
    if not any(isinstance(a, dict) and a.get("actionId") == action_id for a in manifest.get("actions") or []):
        return None
    binding = ui_domain.ACTIONS.get(action_id)
    target = (manifest.get("actionTargets") or {}).get(action_id)
    if binding is None or target is None:
        return None
    return {"actionId": action_id, "binding": binding, "target": target}


def _epoch(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def current(cur, auth, manifest):
    """Re-check a stored manifest against the caller as they are now. 404 for another scope/workspace, 410 when the
    capability expired; otherwise the effective manifest: queries and actions narrowed to what the current role allows,
    actions past their own expiry removed, and `revised` set when the role changed since issue."""
    _ = cur
    if not isinstance(manifest, dict) or not manifest.get("manifestId"):
        raise _unavailable()
    scope = manifest.get("scope") or "workspace"
    if scope != (getattr(auth, "scope", None) or "workspace") or str(manifest.get("workspaceId") or "") != str(auth.workspace_id) \
            or (manifest.get("scopeKey") or "") != (getattr(auth, "scope_key", "") or ""):
        raise _unavailable()
    expires = _epoch(manifest.get("expiresAt"))
    now = _now()
    if expires is None or expires <= now:
        raise AlphaError("This view's live data has expired. Ask Rafii again for a fresh view.", 410, code="ui_capability_expired")
    revised = manifest.get("permissionRevision") != permission_revision(auth.member)
    actions, targets = [], {}
    for entry in manifest.get("actions") or []:
        action_id = entry.get("actionId") if isinstance(entry, dict) else None
        binding = ui_domain.ACTIONS.get(action_id or "")
        target = (manifest.get("actionTargets") or {}).get(action_id or "")
        if binding is None or target is None or not _allows(auth.member, binding.requirement) or (_epoch(target.get("expiresAt")) or 0) <= now:
            continue
        actions.append(entry)
        targets[action_id] = target
    queries = [q for q in manifest.get("queries") or [] if isinstance(q, dict) and q.get("name") in ui_domain.QUERIES
               and _allows(auth.member, ui_domain.QUERIES[q["name"]].requirement)]
    return {**manifest, "queries": queries, "actions": actions, "actionTargets": targets, "revised": revised}


# --- the persisted artifact a request names -----------------------------------------------------------------------------
ARTIFACT_COLUMNS = ("id", "workspace_id", "scope", "scope_key", "conversation_id", "parent_run_id", "message_id", "actor", "surface", "journey_ids", "revision",
                    "source_hash", "generation_state", "validation_state", "manifest", "manifest_id", "binding_version", "safe_state", "state_revision",
                    "library_hash")
_TEXT = ("id", "workspace_id", "conversation_id", "parent_run_id", "message_id", "actor")


def load_artifact(cur, auth, artifact_id):
    """(artifact record, stored manifest) for an artifact in the caller's scope; the same 404 for foreign, unknown,
    founder-on-consumer and consumer-on-founder ids. A consumer artifact whose parent run is a founder run is refused
    too: the ops workspace is an ordinary workspace, and its founder runs never surface on consumer routes."""
    if not ui_contracts.valid_uuid(artifact_id):
        raise _unavailable()
    scope = getattr(auth, "scope", None) or "workspace"
    cols = ",".join(f"a.{c}::text" if c in _TEXT else f"a.{c}" for c in ARTIFACT_COLUMNS)
    cur.execute(f"SELECT {cols},r.idempotency_key FROM public.pr_ui_artifacts a JOIN public.pr_agent_runs r ON r.id=a.parent_run_id AND r.workspace_id=a.workspace_id "
                "WHERE a.id=%s AND a.workspace_id=%s AND a.scope=%s AND a.scope_key=%s", (artifact_id, auth.workspace_id, scope, getattr(auth, "scope_key", "") or ""))
    row = cur.fetchone()
    if not row:
        raise _unavailable()
    record = dict(zip(ARTIFACT_COLUMNS, row[:len(ARTIFACT_COLUMNS)]))
    run_key = row[len(ARTIFACT_COLUMNS)] or ""
    if run_key.startswith("agent:founder:") != (scope == "founder"):
        raise _unavailable()
    for key in ("manifest", "safe_state"):
        if isinstance(record.get(key), str):
            record[key] = json.loads(record[key])
    record["manifest"] = record["manifest"] if isinstance(record.get("manifest"), dict) else {}
    return record, record["manifest"]


def require_accepted(artifact: dict, requested_revision: int) -> None:
    """Queries and actions need a server-accepted revision. A query may name an older accepted revision of the same
    artifact; nothing may name one that does not exist yet."""
    current_revision = int(artifact.get("revision") or 0)
    if current_revision < 1 or not artifact.get("source_hash"):
        raise AlphaError("This view isn't ready yet.", 409, code="ui_not_accepted")
    if requested_revision < 1 or requested_revision > current_revision:
        raise AlphaError("That version of this view is unavailable.", 409, code="ui_revision")
