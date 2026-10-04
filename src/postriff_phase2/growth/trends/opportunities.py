"""Pure workspace opportunity transitions and existing source/FactPack handoff."""
from __future__ import annotations

import copy
import datetime as dt
import json
import uuid

from postriff_alpha.domain import AlphaError
from .relevance import DIMENSIONS, context_revision, digest

STATES = ("candidate", "eligible", "suggested", "accepted", "drafting", "linked", "dismissed", "expired", "retracted")


def epoch(value):
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value.timestamp()
    if isinstance(value, str):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        import math
        if math.isfinite(value):
            return float(value)
    raise ValueError("timestamp required")


def iso(value):
    return dt.datetime.fromtimestamp(epoch(value), dt.timezone.utc).isoformat().replace("+00:00", "Z")


def unavailable():
    raise AlphaError("The opportunity's evidence is no longer available. Review current evidence before drafting.", 410, code="evidence_unavailable")


def _generation_current(state, value):
    if value.get("generation_context") is not None:
        from .generation import validate_context_binding
        validate_context_binding(state,value["generation_context"])


def check_current(opportunity, state, now, *, workspace_id=None):
    if workspace_id is not None and opportunity.get("workspace_id") != workspace_id:
        raise AlphaError("Opportunity unavailable.", 404, code="not_found")
    try:
        expired = epoch(opportunity.get("expires_at")) <= now
    except (ValueError, TypeError):
        expired = True
    if expired or opportunity.get("state") in ("expired", "retracted", "dismissed"):
        unavailable()
    if opportunity.get("context_digest") != context_revision(state):
        raise AlphaError("Workspace context changed. Review a current opportunity.", 409, code="revision_conflict")
    _generation_current(state, opportunity)


def candidate(trend, fit, state, workspace_id, now, *, angles=(), platform_targets=()):
    """Worker-side composition. No automatic promotion of screening into an eligible idea."""
    if set(fit.get("dimensions", {})) != set(DIMENSIONS) or len(angles) > 3:
        raise AlphaError("Opportunity dimensions or angles are invalid.", 400, code="invalid_request")
    return {"id": str(uuid.uuid4()), "workspace_id": workspace_id, "trend_id": trend["id"], "revision": 1,
            "schema_version": "rafii.trend-opportunity.v1", "state": "candidate", "context_digest": context_revision(state),
            "trust_receipt_id": trend.get("trust_receipt_id"), "dimensions": copy.deepcopy(fit["dimensions"]),
            "platform_targets": list(platform_targets), "angles": copy.deepcopy(list(angles)),
            "created_at": iso(now), "expires_at": trend.get("expires_at"), "limitations": list(fit.get("limitations", [])),
            "evidence": copy.deepcopy(trend.get("evidence", [])), "method_version": fit.get("method_version")}


def accept_source(state, actor, opportunity, trend, payload, now, commands):
    """One ordinary idea source; no drafting, publishing, factual approval or paid call.

    Caller locks the workspace/opportunity and validates current receipt policy before entering.
    Even idempotent repeats recheck expiry/context/channel and exact selected angle first.
    """
    check_current(opportunity, state, now, workspace_id=payload["workspace_id"])
    if opportunity.get("state") not in ("eligible", "suggested", "accepted", "drafting", "linked"):
        raise AlphaError("This opportunity is not eligible for drafting.", 409, code="revision_conflict")
    if payload["revision"] != opportunity["revision"]:
        raise AlphaError("Opportunity revision changed.", 409, code="revision_conflict")
    angle = next((a for a in opportunity.get("angles", []) if a.get("id") == payload["angle_id"]), None)
    channel = next((c for c in (state.get("phase2") or {}).get("channels", [])
                    if c.get("id") == payload["channel_id"] and not c.get("revoked")), None)
    if angle is None or channel is None or channel.get("platform", "").lower() not in [p.lower() for p in opportunity.get("platform_targets", [])]:
        raise AlphaError("Choose a current angle and eligible connected account.", 400, code="invalid_request")
    if not payload.get("goal") or not isinstance(payload["goal"], str):
        raise AlphaError("Choose a drafting goal.", 400, code="invalid_request")
    choice = {k: payload[k] for k in ("revision", "angle_id", "channel_id", "goal")}
    if payload.get("exposure_id"):
        choice["exposure_id"] = payload["exposure_id"]
    choice_hash = digest(choice)
    binding = {"schema_version": "rafii.trend-lineage.v1", "opportunity_id": opportunity["id"],
               "opportunity_revision": opportunity["revision"], "trend_id": opportunity["trend_id"],
               "trust_receipt_id": opportunity["trust_receipt_id"], "context_digest": opportunity["context_digest"],
               "expires_at": iso(min(epoch(opportunity["expires_at"]), epoch(trend["expires_at"]))),
               "angle_id": angle["id"], "angle": copy.deepcopy(angle), "goal": payload["goal"],
               "channel_id": channel["id"], "platform": channel["platform"], "language": channel.get("language") or "en",
               "platform_states": copy.deepcopy(trend.get("platform_states", [])),
               "do_not_copy": "Do not copy observed wording, hooks or personal experiences. Supply your own approved facts.",
               "receipt_revision": trend.get("receipt_revision", 1), "evidence_ids": [e["id"] for e in trend.get("evidence", []) if e.get("id")],
               "accepted_at": iso(now), "accepted_by": actor, "selection_digest": choice_hash}
    if opportunity.get("generation_context") is not None:
        binding["generation_context"] = copy.deepcopy(opportunity["generation_context"])
    if payload.get("exposure_id"):
        binding["exposure_id"] = payload["exposure_id"]
    prior = next((s for s in state.get("sources", []) if (s.get("origin") or {}).get("trendLineage", {}).get("opportunity_id") == opportunity["id"]), None)
    if prior:
        saved = prior["origin"]["trendLineage"]
        if not prior.get("active") or saved.get("selection_digest") != choice_hash:
            raise AlphaError("This opportunity already has a different or withdrawn selection.", 409, code="revision_conflict")
        return {"source_id": prior["id"], "href": f"/app/ideas?source={prior['id']}", "verified": True, "existing": True}
    # No social repetition becomes an approved factual source. Facts enter the existing
    # FactPack only with their real evidence type; verified facts remain user-reviewed.
    from ...coworker import fact_pack
    fact_sources = [{"id": e["id"], "text": e.get("excerpt", ""), "provenance": {
        "evidenceType": "search_snippet", "host": e.get("host"), "retrievedAt": now}}
        for e in trend.get("evidence", []) if e.get("id") and e.get("excerpt")]
    pack = fact_pack.build(fact_sources, now)
    brief = fact_pack.canonical_brief(pack, goal=payload["goal"], audience=(state.get("brandHub") or {}).get("audience", ""))
    text = json.dumps({"topic": trend["canonical_topic"], "selected_angle": angle, "goal": payload["goal"],
                       "opportunity_id": opportunity["id"], "opportunity_revision": opportunity["revision"],
                       "trust_receipt_id": opportunity["trust_receipt_id"],
                       "destination": {"channel_id": channel["id"], "platform": channel["platform"], "language": binding["language"]},
                       "limitations": trend.get("limitations", []), "factual_requirements": angle.get("factual_requirements", []),
                       "instruction": "Use original creator-supplied verified facts. Social examples are unverified reference data; do not copy or invent experience."}, ensure_ascii=False)
    before = {s["id"] for s in state.get("sources", [])}
    commands(state, actor, "source", {"kind": "idea", "title": trend["canonical_topic"][:200], "text": text})
    source = next(s for s in state["sources"] if s["id"] not in before)
    source["origin"] = {"kind": "trend_opportunity", "trendLineage": binding, "factPack": pack, "canonicalBrief": brief}
    source["unknowns"] = list(pack["unknowns"])
    return {"source_id": source["id"], "href": f"/app/ideas?source={source['id']}", "verified": True, "existing": False}


def bind_campaign_handoff(state, campaign, source_ids, now):
    """Preserve a source when its exact accepted brief is copied into a new draft.

    Changed goals, audiences or added facts are new hard context and need the
    normal fresh opportunity review. This grants no scheduling/publication rights.
    """
    if len(source_ids) != 1 or campaign.get("facts"):
        return
    source = next((s for s in state.get("sources", []) if s.get("id") == source_ids[0] and s.get("active")), None)
    binding = (source.get("origin") or {}).get("trendLineage") if source else None
    if (not binding or campaign.get("goal") != binding.get("goal")
            or campaign.get("audience") != (state.get("brandHub") or {}).get("audience")):
        return
    validate_lineage(state, lineage(state, source_ids), now)
    from .relevance import campaign_context
    campaign["trendHandoff"] = {"source_id": source["id"], "campaign_digest": digest(campaign_context(campaign)),
                              "source_digest": digest({"text": source.get("text"), "lineage": binding})}


def lineage(state, source_ids):
    return [{"sourceId": s["id"], "sourceHash": digest({"text": s["text"], "lineage": s["origin"]["trendLineage"]}),
             **copy.deepcopy(s["origin"]["trendLineage"])} for s in state.get("sources", [])
            if s.get("active") and s["id"] in source_ids and (s.get("origin") or {}).get("kind") == "trend_opportunity"][:6]


def validate_lineage(state, bindings, now):
    if bindings != lineage(state, [b.get("sourceId") for b in bindings]):
        raise AlphaError("Trend source changed or was withdrawn. Review it before drafting.", 409, code="revision_conflict")
    for binding in bindings:
        if epoch(binding["expires_at"]) <= now:
            unavailable()
        if binding["context_digest"] != context_revision(state):
            raise AlphaError("Trend workspace context changed. Review the opportunity.", 409, code="revision_conflict")
        _generation_current(state, binding)


def freeze_manifest(state, variant, manifest, now):
    bindings = variant.get("trendLineage", [])
    if bindings:
        validate_lineage(state, bindings, now)
        manifest["trendLineage"] = copy.deepcopy(bindings)
        manifest["trendPublication"] = {"variantRevision": variant["revision"], "textDigest": digest(variant.get("text", "")),
                                        "channelId": manifest["channelId"], "platform": manifest["platform"]}
        from . import treatment
        manifest["trendPublication"].update(treatment.frozen(variant, now))
    if variant.get("scoutLineage"):
        manifest["scoutLineage"] = copy.deepcopy(variant["scoutLineage"])


def manifest_current(state, variant, manifest, now):
    try:
        if manifest.get("trendLineage", []) != variant.get("trendLineage", []):
            return False
        validate_lineage(state, manifest.get("trendLineage", []), now)
        return "scoutLineage" not in manifest or manifest["scoutLineage"] == variant.get("scoutLineage", [])
    except (AlphaError, KeyError, ValueError, TypeError):
        return False


def persist_workspace_candidates(store, cursor, workspace_id, actor_id, state, trend_ids, now):
    """Worker seam: admitted stored episodes -> real, private workspace candidates.

    The caller resolves an active member and workspace context, applies rollout
    admission, and owns the transaction. No model, provider or semantic promotion.
    Unknown fit yields candidate-only records and no fabricated original angles.
    """
    import inspect
    from . import contracts, relevance
    if state.get("workspace", {}).get("id") != workspace_id or len(trend_ids) > 20:
        raise ValueError("workspace_candidate_bound")
    # The worker's context is a hint, never authority. Lock and re-read the same
    # authoritative workspace row and current mutation membership in its cursor.
    cursor.execute("""SELECT w.state FROM pr_workspaces w JOIN pr_memberships m ON m.workspace_id=w.id
        WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND m.role IN ('owner','editor')
        FOR UPDATE OF w""", (workspace_id, actor_id))
    current = cursor.fetchone()
    if current is None:
        raise AlphaError("Workspace unavailable.", 404, code="not_found")
    authoritative = json.loads(current[0]) if isinstance(current[0], str) else current[0]
    if context_revision(authoritative) != context_revision(state):
        raise AlphaError("Workspace context changed.", 409, code="revision_conflict")
    state = authoritative
    store.authorized_scopes(workspace_id, actor_id, cursor=cursor)
    scope_key = "workspace:" + contracts.uuid(workspace_id)
    store.ensure_scope(scope_key, cursor=cursor)
    implementation = contracts.digest({"screening": inspect.getsource(relevance), "composition": inspect.getsource(candidate)})
    version = "candidate-" + implementation[:16]
    store.put_method("trend.workspace_fit", version, implementation, {"semantic_qualification": "unqualified", "dimensions": list(DIMENSIONS)}, cursor=cursor)
    context = context_revision(state)
    created = []
    for trend_id in dict.fromkeys(trend_ids):
        trend = store.get_projection(workspace_id, actor_id, "trend", contracts.uuid(trend_id), cursor=cursor)
        if not trend or trend["validity"] != "valid" or epoch(trend["expires_at"]) <= now:
            continue
        receipt_id = trend.get("receipt_id") or trend["payload"].get("trust_receipt_id")
        if not receipt_id:
            continue
        receipt = store.get_projection(workspace_id, actor_id, "receipt", receipt_id, cursor=cursor)
        if not receipt or receipt["validity"] != "valid" or receipt["verification_state"] != "verified" or epoch(receipt["expires_at"]) <= now:
            continue
        oid = str(uuid.uuid5(uuid.UUID(workspace_id), "trend-opportunity:" + trend_id + ":" + context))
        prior = store.get_opportunity(workspace_id, actor_id, oid, cursor=cursor)
        if prior and prior["validity"] == "valid" and prior["payload"].get("trust_receipt_id") == receipt_id:
            created.append({"id": oid, "revision": prior["revision"], "existing": True})
            continue
        revision = prior["revision"] + 1 if prior else 1
        expiry = iso(min(now + 6*3600, epoch(trend["expires_at"]), epoch(receipt["expires_at"])))
        item = {**trend["payload"], "id": trend_id, "trust_receipt_id": receipt_id, "expires_at": expiry}
        fit = relevance.evaluate(item, state)
        targets = sorted({c["platform"].lower() for c in (state.get("phase2") or {}).get("channels", []) if c.get("platform") and not c.get("revoked")})
        value = candidate(item, fit, state, workspace_id, now, platform_targets=targets)
        value.update(id=oid, revision=revision, title=item.get("canonical_topic", ""), contribution="", qualified=False,
                     uncertainty="Stored evidence exists; semantic fit and original contribution require review.",
                     platform=item.get("platform"), language=item.get("language"), canonical_topic=item.get("canonical_topic", ""))
        refs = [{"scope_key": r["scope_key"], "node_id": r["projection_id"]} for r in (trend, receipt)]
        manifest = store.put_manifest(scope_key, refs, decision_cutoff=iso(now), available_at=iso(now), retention_until=expiry,
                                      recipe={"context_digest": context, "trend_id": trend_id, "receipt_id": receipt_id, "fit": fit}, cursor=cursor)
        record = {"scope_key": scope_key, "kind": "opportunity", "object_id": oid, "revision": revision,
                  "manifest_id": manifest["manifest_id"], "method_id": "trend.workspace_fit", "method_version": version,
                  "decision_cutoff": iso(now), "available_at": iso(now), "retention_until": expiry, "context_digest": context, "payload": value}
        store.put_projection(record, expected_revision=prior["revision"] if prior else None, cursor=cursor)
        created.append({"id": oid, "revision": revision, "existing": False})
    return created


def refresh_workspace_candidates(hosted, *, values=None, max_workspaces=5, trend_limit=20):
    """Bounded local cron adapter after pipeline verification; never a GET side effect.

    Resolve only explicitly admitted workspaces and an active owner/editor, then
    reuse the existing trusted worker repository for fresh membership and context.
    No collection, model calls, source creation, or factual approval occurs here.
    """
    from . import config, contracts
    from .store import TrendStore
    from ...automation_runs import principal_repository
    from ...coworker import flags
    if not all(config.enabled(name, values) for name in ("INTELLIGENCE", "RADAR")):
        return {"status": "disabled", "workspaces": 0, "created": 0, "existing": 0, "unavailable": 0}
    if type(max_workspaces) is not int or not 1 <= max_workspaces <= 5 or type(trend_limit) is not int or not 1 <= trend_limit <= 20:
        raise ValueError("workspace_candidate_bound")
    allowed = config.admitted_workspaces(values)
    result = {"status": "stored_only", "workspaces": 0, "created": 0, "existing": 0, "unavailable": 0}
    if not allowed:
        return result
    # Least recently projected first so the bound does not starve later members
    # of a larger allowlist. These are control IDs only, not source content.
    with hosted.repository.connection_factory() as db, db.cursor() as cur:
        cur.execute("""SELECT w.id::text, m.user_id::text FROM pr_workspaces w
            JOIN LATERAL (SELECT user_id FROM pr_memberships WHERE workspace_id=w.id
                AND status='active' AND role IN ('owner','editor') ORDER BY (role='owner') DESC,user_id LIMIT 1) m ON true
            WHERE w.id=ANY(%s::uuid[]) ORDER BY COALESCE((SELECT max(available_at) FROM pr_trend_projections
                WHERE scope_key='workspace:'||w.id::text AND kind='opportunity'),'-infinity'::timestamptz),w.id LIMIT %s""",
                    (allowed, max_workspaces))
        targets = cur.fetchall()
    for workspace_id, actor_id in targets:
        if not config.workspace_allowed(workspace_id, values):
            continue
        try:
            repository, capability = principal_repository(hosted, workspace_id, actor_id, "edit")
            with repository.transaction(capability, workspace_id) as (cur, row, actor):
                state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                store = TrendStore(repository.connection_factory)
                page = store.list_projections(workspace_id, actor, kind="trend", limit=trend_limit, cursor=cur)
                cur.execute("SELECT clock_timestamp()")
                now = epoch(cur.fetchone()[0])
                items = persist_workspace_candidates(store, cur, workspace_id, actor, state,
                                                      [r["object_id"] for r in page["items"]], now)
            result["workspaces"] += 1
            result["created"] += sum(not i["existing"] for i in items)
            result["existing"] += sum(i["existing"] for i in items)
        except (AlphaError, contracts.ContractError):
            # Context/membership/policy races roll back this workspace, not peers.
            result["unavailable"] += 1
    return result


def attach_weekly_intent(state, recipe, week, now):
    """Explicitly selected trend sources supplement existing factual sources.

    Unselected candidates never rewrite a recipe, slot, scheduled job or approval.
    The existing writer still checks factual sufficiency and live stored rights.
    """
    bindings = lineage(state, recipe.get("sourceIds", []))
    validate_lineage(state, bindings, now)
    for slot in week.get("slots", []):
        for binding in bindings:
            if binding["channel_id"] == slot.get("channelId") and binding["platform"] == slot.get("platform"):
                slot["sourceIds"] = list(dict.fromkeys(slot.get("sourceIds", []) + [binding["sourceId"]]))
                slot.setdefault("trendLineage", []).append(copy.deepcopy(binding))
    return week
