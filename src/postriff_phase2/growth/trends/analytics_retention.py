"""Explicit independent retention of content-free, private exposure metadata.

OFF by default. This does not register grants or renew source rights. Operators
must review an exact immutable contract/policy before an authenticated adapter
calls retain_exposure. Separate aggregate roots intentionally have no raw-TTL
DAG edge; privacy_links are checked on EVERY read and reconciled before the
normal retention sweep. Source deletion/revocation can never be waived.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import hashlib
import uuid as uuidlib

from . import contracts, opportunities, retention, revocation
from .store import TrendStorageError, identity_digest, row, rows, trust_lock, utcnow

VERSION = "rafii.private-exposure-retention.v1"
OPERATION = "retain_opportunity_exposure_metadata.v1"
PURPOSE = "private_exposure_outcome_measurement"
CASCADE = "purge_on_source_author_policy_contract_or_workspace_delete_or_revoke"
PERMISSIONS = ("retrieve", "store_metrics", "derive_metrics", "retain_derivatives")
FIELDS = ("workspace_id", "actor_id", "exposure_id", "event_id", "opportunity_id", "opportunity_revision",
          "trust_receipt_id", "context_digest", "recorded_at", "source_expires_at", "eligible_candidate_count",
          "candidates_digest", "measurement", "candidate_scope")


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def _policy_binding(cur, scope, provider, version):
    cur.execute("""SELECT p.*,c.manifest AS contract_manifest,c.operations AS contract_operations,
        c.valid_from AS contract_start,c.expires_at AS contract_end,c.revoked_at AS contract_revoked,
        s.enabled FROM public.pr_trend_source_policies p JOIN public.pr_trend_provider_contracts c
        ON(c.provider_id,c.version)=(p.provider_id,p.provider_contract_version)
        JOIN public.pr_trend_scopes s USING(scope_key)
        WHERE p.scope_key=%s AND p.provider_id=%s AND p.version=%s FOR SHARE OF p,c,s""", (scope, provider, version))
    p = row(cur)
    if not p:
        raise TrendStorageError("analytics_source_policy_missing")
    policy_fields = ("scope_key", "provider_id", "version", "provider_contract_version", "operations", "rights", "readiness",
                     "valid_from", "expires_at", "max_retention_seconds", "manifest")
    binding = {"scope_key": scope, "provider_id": provider, "source_policy_version": version,
               "provider_contract_version": p["provider_contract_version"],
               "policy_digest": contracts.digest({k: p[k] for k in policy_fields}),
               "contract_digest": contracts.digest({k: p[k] for k in ("contract_manifest", "contract_operations", "contract_start", "contract_end")})}
    return p, binding


def _links(cur, exposure):
    cur.execute("""WITH RECURSIVE ancestors(scope_key,node_id) AS (
        SELECT %s::text,%s::uuid UNION SELECT d.input_scope_key,d.input_node_id
        FROM public.pr_trend_dependencies d JOIN ancestors a ON(d.scope_key,d.node_id)=(a.scope_key,a.node_id))
        SELECT DISTINCT o.scope_key,o.provider_id,o.source_identity_digest,o.source_policy_version,
        o.provider_contract_version,CASE WHEN o.author_key IS NULL THEN NULL
        ELSE encode(sha256(convert_to(o.author_key,'UTF8')),'hex') END AS author_digest
        FROM ancestors a JOIN public.pr_trend_observations o
        ON(o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
        ORDER BY o.scope_key,o.provider_id,o.source_identity_digest,o.source_policy_version LIMIT 65""",
        (exposure["scope_key"], exposure["projection_id"]))
    links = rows(cur)
    if not 1 <= len(links) <= 64:
        raise TrendStorageError("analytics_privacy_link_bounds")
    if any(not link["author_digest"] for link in links):
        # Without a durable author link an account-wide erasure could not be
        # resolved once the raw payload expires. Do not guess that it is safe.
        raise TrendStorageError("analytics_author_privacy_unresolved")
    return links


def review_requirements(store, cur, workspace_id, actor_id, exposure_id):
    """Read-only operator preview; it is NOT a review, grant or activation."""
    exposure = _exposure(store, cur, workspace_id, actor_id, exposure_id)
    authorities = {}
    for link in _links(cur, exposure):
        _, binding = _policy_binding(cur, link["scope_key"], link["provider_id"], link["source_policy_version"])
        authorities[contracts.digest(binding)] = binding
    return {"operation": OPERATION, "allowed_fields": sorted(FIELDS),
            "source_authorities": [authorities[k] for k in sorted(authorities)], "reviewed": False}


def _exposure(store, cur, wid, actor, eid):
    exposure = store.get_projection(wid, actor, "exposure", eid, cursor=cur)
    if (not exposure or exposure["scope_key"] != "workspace:" + wid or exposure["validity"] != "valid"
            or not exposure.get("payload") or exposure["payload"].get("actor_id") != actor
            or any(exposure["policy"].get(k) is not True for k in ("derive_metrics", "retain_derivatives"))):
        raise TrendStorageError("analytics_exposure_unavailable")
    store.lock_dependencies(wid, actor, [{"kind": "exposure", "object_id": eid, "revision": exposure["revision"]}], cursor=cur)
    return exposure


def _authority(store, cur, scope, authority, at):
    if not isinstance(authority, dict) or set(authority) != {"provider_id", "policy_version"}:
        raise TrendStorageError("analytics_authority_required")
    p = store._policy(cur, scope, authority["provider_id"], authority["policy_version"], at=at)
    g = p["manifest"].get("analytics_retention")
    required = {"schema_version", "enabled", "permission", "operation", "purpose", "data_class", "survive_raw_ttl",
                "cascade", "reviewed_by", "review_ref", "reviewed_at", "expires_at", "max_retention_seconds",
                "purge_within_seconds", "allowed_fields", "source_authorities"}
    if (not isinstance(g, dict) or set(g) != required or g["schema_version"] != VERSION or g["enabled"] is not True
            or g["permission"] != "allow" or g["operation"] != OPERATION or p["manifest"].get("operation") != OPERATION
            or g["purpose"] != PURPOSE or g["data_class"] != "content_free_exposure_metadata"
            or g["survive_raw_ttl"] is not True or g["cascade"] != CASCADE or g["allowed_fields"] != sorted(FIELDS)
            or not isinstance(g["source_authorities"], list) or not 1 <= len(g["source_authorities"]) <= 64
            or type(g["max_retention_seconds"]) is not int or not 1 <= g["max_retention_seconds"] <= 366*86400
            or type(g["purge_within_seconds"]) is not int or not 1 <= g["purge_within_seconds"] <= 86400):
        raise TrendStorageError("analytics_reviewed_grant_required")
    for key in ("reviewed_by", "review_ref"):
        contracts.bounded_text(g[key], 256)
    if not contracts.instant(g["reviewed_at"]) <= contracts.instant(at) < contracts.instant(g["expires_at"]):
        raise TrendStorageError("analytics_review_not_current")
    cur.execute("SELECT manifest FROM public.pr_trend_provider_contracts WHERE provider_id=%s AND version=%s",
                (p["provider_id"], p["provider_contract_version"]))
    if cur.fetchone()[0].get("analytics_retention") != g:
        raise TrendStorageError("analytics_contract_review_mismatch")
    if any(k not in p["operations"] or k not in p["contract_operations"] or not contracts.permits(p["rights"], k, scope, at) for k in PERMISSIONS):
        raise TrendStorageError("analytics_permission_unavailable")
    # No content/model/sharing grant is needed or inferred for these metadata.
    return p, g


def _privacy_current(store, cur, wid, metadata, links, grant, at):
    if metadata.get("workspace_id") != wid:
        raise TrendStorageError("analytics_workspace_mismatch")
    store._actor(cur, wid, metadata["actor_id"])
    approved = {contracts.digest(b) for b in grant["source_authorities"]}
    actual = set()
    if not isinstance(links, list) or not 1 <= len(links) <= 64:
        raise TrendStorageError("analytics_privacy_link_bounds")
    for link in links:
        if set(link) != {"scope_key", "provider_id", "source_identity_digest", "source_policy_version", "provider_contract_version", "author_digest"}:
            raise TrendStorageError("analytics_privacy_link_invalid")
        p, binding = _policy_binding(cur, link["scope_key"], link["provider_id"], link["source_policy_version"])
        actual.add(contracts.digest(binding))
        for name in ("source_identity_digest", "author_digest"):
            value = link[name]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise TrendStorageError("analytics_privacy_unresolved")
        # Physical content purge deliberately retains this content-free identity
        # anchor. If it is absent, deletion scope cannot be resolved: deny.
        cur.execute("""SELECT 1 FROM public.pr_trend_observations WHERE scope_key=%s AND provider_id=%s
            AND source_identity_digest=%s AND source_policy_version=%s AND provider_contract_version=%s
            AND operation<>'delete' LIMIT 1""", (link["scope_key"], link["provider_id"], link["source_identity_digest"],
                                               link["source_policy_version"], link["provider_contract_version"]))
        if not cur.fetchone():
            raise TrendStorageError("analytics_privacy_anchor_missing")
        if (p["revoked_at"] or p["contract_revoked"] or not p["enabled"] or p["readiness"] != "ready"
                or not contracts.instant(p["valid_from"]) <= contracts.instant(at) < contracts.instant(p["expires_at"])
                or not contracts.instant(p["contract_start"]) <= contracts.instant(at) < contracts.instant(p["contract_end"])
                or link["provider_contract_version"] != p["provider_contract_version"]):
            raise TrendStorageError("analytics_link_revoked")
        if link["scope_key"] != "workspace:" + wid:
            if not link["scope_key"].startswith("shared:"):
                raise TrendStorageError("analytics_foreign_workspace_link")
            cur.execute("""SELECT 1 FROM public.pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s
                AND revoked_at IS NULL AND expires_at>clock_timestamp() AND 'derive_metrics'=ANY(operations)""", (wid, link["scope_key"]))
            if not cur.fetchone():
                raise TrendStorageError("analytics_entitlement_revoked")
        cur.execute("""SELECT 1 FROM public.pr_trend_deletion_tombstones
            WHERE scope_key=%s AND provider_id=%s AND source_identity_digest=%s""",
            (link["scope_key"], link["provider_id"], link["source_identity_digest"]))
        if cur.fetchone():
            raise TrendStorageError("analytics_source_deleted")
        if link["author_digest"]:
            cur.execute("SELECT 1 FROM public.pr_trend_author_tombstones WHERE provider_id=%s AND author_digest=%s",
                        (link["provider_id"], link["author_digest"]))
            if cur.fetchone():
                raise TrendStorageError("analytics_author_deleted")
    if actual != approved:
        raise TrendStorageError("analytics_exact_source_review_mismatch")


def _metadata(payload, wid, actor, expiry):
    for key in ("exposure_id", "event_id", "opportunity_id", "trust_receipt_id"):
        contracts.uuid(payload[key])
    for key in ("opportunity_revision", "eligible_candidate_count"):
        if type(payload.get(key)) is not int or payload[key] < 1:
            raise TrendStorageError("analytics_metadata_invalid")
    if payload["eligible_candidate_count"] > 20 or payload.get("measurement") != "client_reported_view":
        raise TrendStorageError("analytics_metadata_invalid")
    context = payload.get("context_digest")
    if not isinstance(context, str) or len(context) != 64 or any(c not in "0123456789abcdef" for c in context):
        raise TrendStorageError("analytics_metadata_invalid")
    contracts.instant(payload["recorded_at"])
    return {"workspace_id": wid, "actor_id": actor, **{k: payload[k] for k in
        ("exposure_id", "event_id", "opportunity_id", "opportunity_revision", "trust_receipt_id", "context_digest", "recorded_at", "eligible_candidate_count")},
        "source_expires_at": expiry, "candidates_digest": contracts.digest(payload["eligible_candidates"]),
        "measurement": "client_reported_view", "candidate_scope": "returned_page"}


def retain_exposure(store, cur, workspace_id, actor_id, exposure_id, *, authority=None, enabled=False):
    """Parent exposure adapter calls in its authenticated transaction after record().

    Disabled/unknown authority is a no-write result. A rejected write uses a
    savepoint so the existing short-lived exposure remains intact.
    """
    if enabled is not True:
        return {"status": "disabled"}
    try:
        with cur.connection.transaction():
            at = utcnow()
            exposure = _exposure(store, cur, workspace_id, actor_id, exposure_id)
            metadata = _metadata(exposure["payload"], workspace_id, actor_id, exposure["expires_at"])
            links = _links(cur, exposure)
            p, grant = _authority(store, cur, "workspace:" + workspace_id, authority, at)
            _privacy_current(store, cur, workspace_id, metadata, links, grant, at)
            scope = "workspace:" + workspace_id
            grant_digest = contracts.digest(grant)
            object_id = str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, scope + ":" + exposure_id + ":" + grant_digest))
            existing = read_current(store, cur, workspace_id, actor_id, object_id)
            if existing["status"] == "available":
                return {**existing, "existing": True}
            until = min([contracts.instant(at) + timedelta(seconds=min(grant["max_retention_seconds"], p["max_retention_seconds"])),
                         contracts.instant(grant["expires_at"]), contracts.instant(p["expires_at"]), contracts.instant(p["contract_end"])]
                        + [contracts.instant(p["rights"][k]["expires_at"]) for k in PERMISSIONS])
            until = opportunities.iso(until)
            document = {"schema_version": VERSION, "metadata": metadata, "privacy_links": links,
                        "authority": dict(authority), "grant_digest": grant_digest}
            root_id = str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, object_id + ":aggregate"))
            source = "analytics-exposure:" + object_id
            payload = {"dataset_id": scope, "metric_definition": VERSION, "unit": "count", "value": 1,
                       "population": "retained_client_reported_exposure_events", "aggregation_semantics": "one_recorded_view_not_unique_people",
                       "window_start": metadata["recorded_at"], "window_end": opportunities.iso(contracts.instant(metadata["recorded_at"]) + timedelta(microseconds=1)),
                       "analytics": document}
            observation = {"schema_version": contracts.SCHEMA_VERSION, "observation_id": root_id, "scope_key": scope,
                "provider_id": p["provider_id"], "provider_contract_version": p["provider_contract_version"], "source_policy_version": p["version"],
                "source_identity": source, "revision_identity": "1", "revision_sequence": 1, "kind": "aggregate_metric", "operation": "create",
                "event_at": metadata["recorded_at"], "received_at": at, "available_at": at, "time_basis": "provider_observation",
                "coverage_epoch": "analytics:" + grant_digest, "provenance": {"access_method": OPERATION, "review_ref": grant["review_ref"]},
                "retention_until": until, "rights": p["rights"], "deletion_key": object_id, "payload": payload, "payload_digest": contracts.digest(payload)}
            store.put_observation(observation, cursor=cur)
            cutoff = utcnow()
            manifest = store.put_manifest(scope, [{"scope_key": scope, "node_id": root_id}], decision_cutoff=cutoff,
                available_at=cutoff, retention_until=until, recipe={"purpose": PURPOSE, "grant_digest": grant_digest}, cursor=cur)
            artifact = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            store.put_method(OPERATION, artifact[:16], artifact, {"content_free": True, "causal": False}, cursor=cur)
            store.put_projection({"scope_key": scope, "kind": "analytics_exposure", "object_id": object_id, "revision": 1,
                "manifest_id": manifest["manifest_id"], "method_id": OPERATION, "method_version": artifact[:16],
                "decision_cutoff": cutoff, "available_at": cutoff, "retention_until": until, "payload": document}, cursor=cur)
            return {**read_current(store, cur, workspace_id, actor_id, object_id), "existing": False}
    except (TrendStorageError, contracts.ContractError, ValueError, TypeError, KeyError):
        return _unavailable("independent_reviewed_retention_not_available")


def _document_current(store, cur, wid, document, at):
    if (not isinstance(document, dict) or set(document) != {"schema_version", "metadata", "privacy_links", "authority", "grant_digest"}
            or document["schema_version"] != VERSION or set(document["metadata"]) != set(FIELDS)):
        raise TrendStorageError("analytics_metadata_invalid")
    metadata = document["metadata"]
    for key in ("workspace_id", "actor_id", "exposure_id", "event_id", "opportunity_id", "trust_receipt_id"):
        contracts.uuid(metadata[key])
    for key in ("context_digest", "candidates_digest"):
        if not isinstance(metadata[key], str) or len(metadata[key]) != 64 or any(c not in "0123456789abcdef" for c in metadata[key]):
            raise TrendStorageError("analytics_metadata_invalid")
    for key in ("recorded_at", "source_expires_at"):
        contracts.instant(metadata[key])
    if (type(metadata["opportunity_revision"]) is not int or metadata["opportunity_revision"] < 1
            or type(metadata["eligible_candidate_count"]) is not int or not 1 <= metadata["eligible_candidate_count"] <= 20
            or metadata["measurement"] != "client_reported_view" or metadata["candidate_scope"] != "returned_page"):
        raise TrendStorageError("analytics_metadata_invalid")
    p, grant = _authority(store, cur, "workspace:" + wid, document["authority"], at)
    if contracts.digest(grant) != document["grant_digest"]:
        raise TrendStorageError("analytics_grant_changed")
    _privacy_current(store, cur, wid, document["metadata"], document["privacy_links"], grant, at)
    return p, grant


def read_current(store, cur, workspace_id, actor_id, object_id):
    """Typed content-free read, never a raw/general payload redaction bypass."""
    store.authorized_scopes(workspace_id, actor_id, cursor=cur)
    status = store.projection_status(workspace_id, actor_id, "analytics_exposure", object_id, cursor=cur)
    if not status or status["scope_key"] != "workspace:" + workspace_id or status["validity"] != "valid":
        return _unavailable("analytics_expired_revoked_or_missing")
    cur.execute("""SELECT payload FROM public.pr_trend_projections WHERE scope_key=%s AND kind='analytics_exposure'
        AND object_id=%s AND revision=%s""", (status["scope_key"], object_id, status["revision"]))
    document = cur.fetchone()[0]
    try:
        cur.execute("""SELECT o.payload->'analytics' FROM public.pr_trend_projections p
            JOIN public.pr_trend_manifest_inputs i USING(scope_key,manifest_id)
            JOIN public.pr_trend_observations o ON(o.scope_key,o.observation_id)=(i.input_scope_key,i.input_node_id)
            WHERE p.scope_key=%s AND p.kind='analytics_exposure' AND p.object_id=%s AND p.revision=%s
            AND p.method_id=%s AND o.kind='aggregate_metric' AND o.metric_id=%s""",
            (status["scope_key"], object_id, status["revision"], OPERATION, VERSION))
        roots = cur.fetchall()
        if len(roots) != 1 or roots[0][0] != document:
            raise TrendStorageError("analytics_projection_root_mismatch")
        _document_current(store, cur, workspace_id, document, utcnow())
    except (TrendStorageError, contracts.ContractError, ValueError, TypeError, KeyError):
        return _unavailable("analytics_privacy_or_review_unavailable")
    return {"status": "available", "object_id": object_id, "metadata": document["metadata"],
            "analytics_expires_at": status["expires_at"], "source_rights_extended": False,
            "qualification": "retained_metadata_only_not_source_evidence"}


def list_current(store, cur, workspace_id, actor_id, *, limit=100):
    page = store.list_projections(workspace_id, actor_id, kind="analytics_exposure", limit=limit,
        filters={"scope_key": "workspace:" + workspace_id}, cursor=cur)
    found = [read_current(store, cur, workspace_id, actor_id, p["object_id"]) for p in page["items"]]
    return {"items": [p for p in found if p["status"] == "available"], "truncated": bool(page.get("next_key")),
            "scope": "current_permitted_retained_metadata"}


def sweep(store, *, limit=100, after=None, cursor=None):
    """Run BEFORE normal retention cleanup, including when new recording is OFF.

    Invalid privacy links become ordinary durable aggregate source tombstones.
    Existing reverse cascade/sweep physically erases payloads and recipes.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("analytics_sweep_bounds")
    if after is not None:
        if not isinstance(after, (list, tuple)) or len(after) != 3:
            raise ValueError("analytics_sweep_cursor")
        contracts.instant(after[0]); contracts.scope(after[1]); contracts.uuid(after[2])
    with store.transaction(cursor) as cur:
        trust_lock(cur, exclusive=True)
        cur.execute("SELECT reads_ready FROM public.pr_trend_runtime_guard WHERE singleton FOR SHARE")
        guard = cur.fetchone()
        if not guard or guard[0] is not True:
            return {"checked": 0, "suppressed": 0, "deferred": "restore_in_progress", "next_key": after}
        where = " AND (n.retention_until,o.scope_key,o.observation_id)>(%s::timestamptz,%s,%s::uuid)" if after else ""
        cur.execute("""SELECT o.scope_key,o.provider_id,o.source_identity,o.payload,n.retention_until,o.observation_id
            FROM public.pr_trend_observations o
            JOIN public.pr_trend_nodes n ON(n.scope_key,n.node_id)=(o.scope_key,o.observation_id)
            WHERE o.kind='aggregate_metric' AND o.metric_id=%s AND o.purged_at IS NULL""" + where + """
            ORDER BY n.retention_until,o.scope_key,o.observation_id LIMIT %s FOR UPDATE OF o,n SKIP LOCKED""",
            [VERSION] + (list(after) if after else []) + [limit])
        selected = rows(cur)
        suppressed = 0
        for item in selected:
            try:
                if not item["scope_key"].startswith("workspace:"):
                    raise TrendStorageError("analytics_scope_invalid")
                _document_current(store, cur, item["scope_key"].split(":", 1)[1], item["payload"].get("analytics"), utcnow())
            except (TrendStorageError, contracts.ContractError, ValueError, TypeError, KeyError):
                revocation.revoke_source(store, item["scope_key"], item["provider_id"], item["source_identity"],
                    reason_code="analytics_privacy_revoked", purge_deadline=utcnow(), cursor=cur)
                suppressed += 1
        purged = retention.sweep(store, limit=min(1000, limit * 4), cursor=cur)
        return {"checked": len(selected), "suppressed": suppressed, "physical_purge": purged,
                "more_may_remain": len(selected) == limit,
                "next_key": [selected[-1][k] for k in ("retention_until", "scope_key", "observation_id")] if len(selected) == limit else None}
