"""Bounded, in-app-only trend alerts through the existing notification outbox.

Worker hook::

    sweep(store, workspace_id=..., actor_id=..., opportunity_ids=[...],
          values=flags, now=epoch_seconds, limit=20, cursor=transaction_cursor)

Call with server-selected saved opportunity IDs. The transaction re-reads watches,
workspace context, current membership, projections and verified receipts. Source
rights come exclusively from TrendStore; this module creates no policy grants.
Watch creation with notification_policy=in_app is the workspace's explicit opt-in.
Existing planner preferences still determine each member's in-app delivery.

The existing delivery worker calls delivery_eligibility before any retry. Encoded
entity IDs bind exact watch/opportunity revisions and receipt ID without persisting
source text. No provider, model, transport, publisher or alternate delivery queue.
"""
from __future__ import annotations

import json
import time

from postriff_alpha.domain import AlphaError
from ...coworker import flags
from ...notifications import planner, store as notification_store
from ... import feature_enrollment
from . import admission, config, contracts, opportunities
from .store import trust_lock

ENTITY_TYPE = "trend_opportunity"
EVENT_TYPE = "opportunity.detected"
TITLE = "A watched trend has an update to review"
HREF = "/app/trends"
COOLDOWN_SECONDS = 6 * 3600
WORKSPACE_LIMIT = 2
WINDOW_SECONDS = 24 * 3600
MAX_CANDIDATES = 100
SCAN_PROVIDER = "rafii.local.notifications"
SCAN_PARTITION = "workspace-scan-v1"


class Ineligible(ValueError):
    """Stable, non-sensitive reason. Never contains source text or a policy body."""


def _flags_on(values):
    return (flags.enabled("RAFII_NOTIFICATIONS_V2_ENABLED", values)
            and all(config.enabled(name, values) for name in ("RADAR", "TRUST_RECEIPTS", "NOTIFICATIONS")))


def _enabled(workspace_id, values, cur=None):
    """In-app watch alerts follow read admission; nothing here is external egress.

    The reviewed allowlist admits without a query. An active self-serve enrollment
    admits only with a cursor (and only while the cohort switch is on). External
    delivery is refused separately in delivery_eligibility for every workspace.
    """
    if not _flags_on(values):
        return False
    if config.workspace_allowed(workspace_id, values):
        return True
    return cur is not None and admission.admitted(cur, workspace_id, values)


def href(trend_id):
    """Deep link that reopens the watched trend (the UUID carries no content).

    The notification store redacts digit runs that look like phone numbers, and a
    dashed UUID can contain one. The compact 32-hex form can only be redacted when
    it is all digits; that (about 1 in 3 million) case falls back to the page.
    """
    compact = contracts.uuid(trend_id).replace("-", "")
    return HREF if compact.isdigit() else HREF + "?trend=" + compact


def _binding(watch_id, watch_revision, opportunity_id, opportunity_revision, receipt_id):
    ids = [contracts.uuid(value) for value in (watch_id, opportunity_id, receipt_id)]
    if any(type(v) is not int or not 1 <= v <= 2**53-1 for v in (watch_revision, opportunity_revision)):
        raise Ineligible("invalid_revision")
    return f"{ids[0]}:{watch_revision}:{ids[1]}:{opportunity_revision}:{ids[2]}"


def _decode(value):
    parts = value.split(":") if isinstance(value, str) else []
    if len(parts) != 5 or len(value) > 200 or not parts[1].isdigit() or not parts[3].isdigit():
        raise Ineligible("invalid_binding")
    if value != _binding(parts[0], int(parts[1]), parts[2], int(parts[3]), parts[4]):
        raise Ineligible("invalid_binding")
    return parts[0], int(parts[1]), parts[2], int(parts[3]), parts[4]


def _workspace(cur, workspace_id):
    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE", (workspace_id,))
    found = cur.fetchone()
    state = found[0] if found else None
    if not isinstance(state, dict) or state.get("accountDeletion") or (state.get("workspace") or {}).get("sample"):
        raise Ineligible("workspace_unavailable")
    return state


def _watch(cur, workspace_id, watch_id, now):
    cur.execute("""SELECT w.watch_id::text,w.revision,w.enabled,w.payload,w.created_by::text,w.created_at
                   FROM public.pr_trend_watches w WHERE w.workspace_id=%s AND w.watch_id=%s FOR SHARE""",
                (workspace_id, watch_id))
    row = cur.fetchone()
    if not row or row[2] is not True:
        raise Ineligible("watch_disabled_or_missing")
    payload = row[3]
    if (not isinstance(payload, dict) or payload.get("notification_policy") != "in_app"
            or payload.get("threshold") not in {"stage_change", "coverage_change"}
            or not isinstance(payload.get("platforms"), list) or not payload["platforms"]
            or opportunities.epoch(row[5]) > now):
        raise Ineligible("watch_not_opted_in")
    # A persisted watch never outlives its creator's current edit membership.
    cur.execute("""SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
                   WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active'
                   AND m.role IN ('owner','editor') AND p.deleted_at IS NULL FOR SHARE OF m,p""",
                (workspace_id, row[4]))
    if not cur.fetchone():
        raise Ineligible("watch_creator_membership_lost")
    return {"watch_id": row[0], "revision": row[1], "payload": payload, "created_at": opportunities.epoch(row[5])}


def _verified(row, now, *, scope_key=None, require_verified=True):
    states = {"verified"} if require_verified else {"verified", "pending"}
    if (not row or row.get("validity") != "valid" or row.get("verification_state") not in states
            or not isinstance(row.get("payload"), dict)
            or (scope_key is not None and row.get("scope_key") != scope_key)
            or opportunities.epoch(row["expires_at"]) <= now or opportunities.epoch(row["available_at"]) > now
            or any(row.get("policy", {}).get(key) is not True for key in ("derive_metrics", "retain_derivatives"))):
        raise Ineligible("projection_or_rights_unavailable")
    return row


def _current(store, cur, workspace_id, actor_id, watch, opportunity_id, now, *, revision=None, receipt_id=None):
    opportunity = store.get_opportunity(workspace_id, actor_id, opportunity_id, cursor=cur)
    # Cross-scope receipt FKs are intentionally absent. Their authenticated
    # receipt projection and explicit manifest inputs supply verification below.
    opportunity = _verified(opportunity, now, scope_key="workspace:" + workspace_id,
                            require_verified=bool((opportunity or {}).get("receipt_id")))
    if revision is not None and opportunity["revision"] != revision:
        raise Ineligible("opportunity_revision_changed")
    payload = opportunity["payload"]
    if payload.get("state") not in {"eligible", "suggested"} or payload.get("qualified") is not True:
        raise Ineligible("opportunity_not_eligible")
    if payload.get("trend_id") != watch["payload"]["trend_id"]:
        raise Ineligible("watch_trend_mismatch")
    platforms = set(watch["payload"]["platforms"]) & set(payload.get("platform_targets", []))
    if not platforms:
        raise Ineligible("watch_platform_mismatch")
    state = _workspace(cur, workspace_id)
    opportunities.check_current({**payload, "workspace_id": workspace_id, "expires_at": opportunity["expires_at"]},
                                state, now, workspace_id=workspace_id)
    receipt_id = receipt_id or payload.get("trust_receipt_id")
    typed_receipt = opportunity.get("receipt_id")
    if (not receipt_id or payload.get("trust_receipt_id") != receipt_id
            or (typed_receipt is not None and str(typed_receipt) != receipt_id)):
        raise Ineligible("receipt_binding_changed")
    trend = _verified(store.get_projection(workspace_id, actor_id, "trend", payload["trend_id"], cursor=cur), now)
    if str(trend.get("receipt_id")) != receipt_id:
        raise Ineligible("trend_receipt_changed")
    receipt = _verified(store.get_projection(workspace_id, actor_id, "receipt", receipt_id, cursor=cur), now)
    if receipt["payload"].get("trend_id") != payload["trend_id"]:
        raise Ineligible("receipt_trend_mismatch")
    store.lock_dependencies(workspace_id, actor_id,
        [{"kind": "opportunity", "object_id": opportunity_id, "revision": opportunity["revision"]},
         {"kind": "trend", "object_id": payload["trend_id"], "revision": trend["revision"]},
         {"kind": "receipt", "object_id": receipt_id, "revision": receipt["revision"]}], cursor=cur)
    cur.execute("""SELECT manifest_id::text FROM public.pr_trend_projections
                   WHERE scope_key=%s AND projection_id=%s AND kind='opportunity'""",
                (opportunity["scope_key"], opportunity["projection_id"]))
    saved = cur.fetchone()
    if not saved:
        raise Ineligible("opportunity_manifest_unavailable")
    manifest = store.get_manifest(opportunity["scope_key"], saved[0], cursor=cur)
    inputs = {(i["scope_key"], str(i["node_id"])) for i in manifest.get("inputs", [])}
    if not all((r["scope_key"], str(r["projection_id"])) in inputs for r in (trend, receipt)):
        raise Ineligible("opportunity_manifest_binding_changed")
    return opportunity, trend, receipt, platforms


def _platform_view(row, platform):
    payload = row["payload"]
    return next((r for r in payload.get("platform_states", []) if r.get("platform") == platform),
                payload if payload.get("platform") == platform else None)


def _transition(store, cur, workspace_id, actor_id, watch, trend, platforms, now):
    if trend["revision"] <= 1 or opportunities.epoch(trend["available_at"]) < watch["created_at"]:
        raise Ineligible("no_post_watch_transition")
    previous = store.get_projection(workspace_id, actor_id, "trend", trend["object_id"], revision=trend["revision"]-1, cursor=cur)
    previous = _verified(previous, now)
    if previous["scope_key"] != trend["scope_key"] or previous.get("method_bundle") != trend.get("method_bundle"):
        raise Ineligible("comparison_changed")
    threshold = watch["payload"]["threshold"]
    for platform in sorted(platforms):
        before, after = _platform_view(previous, platform), _platform_view(trend, platform)
        if before is None or after is None:
            continue
        a, b = before.get("coverage", {}), after.get("coverage", {})
        if threshold == "stage_change":
            if (any(c.get("availability") != "available" or c.get("completeness") != "complete_within_scope" for c in (a, b))
                    or not a.get("coverage_epoch") or a.get("coverage_epoch") != b.get("coverage_epoch")):
                continue  # An outage or a changed query cannot masquerade as decline.
            ia, ib = before.get("inferred", {}), after.get("inferred", {})
            old, new = ia.get("stage"), ib.get("stage")
            if (old not in contracts.STAGES or new not in contracts.STAGES
                    or any(i.get("data_state") != "qualified" for i in (ia, ib))):
                continue
        else:
            fields = ("availability", "completeness", "coverage_epoch")
            if any(k not in a or k not in b for k in fields):
                continue
            old, new = [a[k] for k in fields], [b[k] for k in fields]
        if old != new:
            return {"trend_id": trend["object_id"], "episode_id": trend["payload"].get("episode_id", trend["object_id"]),
                    "platform": platform, "threshold": threshold, "from": old, "to": new, "revision": trend["revision"]}
    raise Ineligible("no_matching_transition")


def sweep(store, *, workspace_id, actor_id, opportunity_ids, values=None, now=None, limit=20, cursor=None):
    """Bounded transactional outbox scan; supplied IDs are re-read, never trusted data."""
    workspace_id, actor_id = contracts.uuid(workspace_id), contracts.uuid(actor_id)
    now = opportunities.epoch(now if now is not None else time.time())
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES or not isinstance(opportunity_ids, (list, tuple)) or len(opportunity_ids) > MAX_CANDIDATES:
        raise ValueError("invalid_sweep_bound")
    ids = list(dict.fromkeys(contracts.uuid(i) for i in opportunity_ids))
    result = {"checked": 0, "created": 0, "duplicates": 0, "skipped": {}, "remaining_opportunity_ids": ids[limit:], "execution_state": "in_app_outbox_only"}
    if not _flags_on(values):
        result["skipped"]["feature_disabled"] = len(ids)
        return result
    with store.transaction(cursor) as cur:
        if not _enabled(workspace_id, values, cur):
            result["skipped"]["feature_disabled"] = len(ids)
            return result
        trust_lock(cur)
        # Serialize dedupe/cooldown admission across workers in the existing DB transaction.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("trend-notifications|" + workspace_id,))
        watches = store.list_watches(workspace_id, actor_id, cursor=cur)
        for opportunity_id in ids[:limit]:
            result["checked"] += 1
            candidate = store.get_opportunity(workspace_id, actor_id, opportunity_id, cursor=cur)
            trend_id = (candidate or {}).get("payload", {}) or {}
            matching = [w for w in watches if w.get("enabled") is True and w.get("payload", {}).get("trend_id") == trend_id.get("trend_id")]
            if not matching:
                result["skipped"]["no_active_watch"] = result["skipped"].get("no_active_watch", 0) + 1
                continue
            for saved in sorted(matching, key=lambda w: str(w["watch_id"])):
                try:
                    watch = _watch(cur, workspace_id, str(saved["watch_id"]), now)
                    opportunity, trend, receipt, platforms = _current(store, cur, workspace_id, actor_id, watch, opportunity_id, now)
                    if watch["payload"]["threshold"] == "stage_change" and not config.enabled("STAGE_CLAIMS", values):
                        raise Ineligible("stage_claims_disabled")
                    transition = _transition(store, cur, workspace_id, actor_id, watch, trend, platforms, now)
                    key = "trend-alert-v1:" + contracts.digest(transition)
                    group = "trend-topic-v1:" + contracts.digest({"trend_id": transition["trend_id"]})
                    cur.execute("SELECT 1 FROM public.pr_notification_events WHERE scope_key=%s AND dedupe_key=%s", (workspace_id, key))
                    if cur.fetchone():
                        result["duplicates"] += 1
                        break
                    cur.execute("""SELECT count(*),count(*) FILTER (WHERE grouping_key=%s AND occurred_at>to_timestamp(%s))
                                   FROM public.pr_notification_events WHERE workspace_id=%s AND entity_type='trend_opportunity'
                                   AND occurred_at>to_timestamp(%s)""", (group, now-COOLDOWN_SECONDS, workspace_id, now-WINDOW_SECONDS))
                    count, recent = cur.fetchone()
                    if count >= WORKSPACE_LIMIT or recent:
                        raise Ineligible("workspace_rate_limit" if count >= WORKSPACE_LIMIT else "topic_cooldown")
                    binding = _binding(watch["watch_id"], watch["revision"], opportunity_id, opportunity["revision"], str(receipt["object_id"]))
                    emitted = notification_store.emit(cur, workspace_id=workspace_id, event_type=EVENT_TYPE,
                        dedupe_key=key, grouping_key=group, entity_type=ENTITY_TYPE, entity_id=binding,
                        payload={"title": TITLE, "href": href(transition["trend_id"])}, actor=actor_id, now=now, occurred_at=now,
                        expires_at=min(opportunities.epoch(r["expires_at"]) for r in (opportunity, trend, receipt)),
                        email_available=False, push_enabled=False, channel_filter={"in_app"})
                    result["created"] += int(emitted["created"])
                    result["duplicates"] += int(not emitted["created"])
                    break
                except (Ineligible, contracts.ContractError, AlphaError, KeyError, TypeError, ValueError) as error:
                    reason = str(error) if isinstance(error, Ineligible) else "current_evidence_unavailable"
                    result["skipped"][reason] = result["skipped"].get(reason, 0) + 1
    return result


def delivery_eligibility(store, *, cursor, workspace_id, actor_id, entity_id, now=None, values=None, channel="in_app"):
    """Current read/rights check for an existing trend event; no enqueue or transport."""
    try:
        workspace_id, actor_id = contracts.uuid(workspace_id), contracts.uuid(actor_id)
        now = opportunities.epoch(now if now is not None else time.time())
        if not _enabled(workspace_id, values, cursor):
            raise Ineligible("feature_disabled")
        trust_lock(cursor)
        watch_id, watch_revision, opportunity_id, revision, receipt_id = _decode(entity_id)
        watch = _watch(cursor, workspace_id, watch_id, now)
        if watch["revision"] != watch_revision:
            raise Ineligible("watch_revision_changed")
        if watch["payload"]["threshold"] == "stage_change" and not config.enabled("STAGE_CLAIMS", values):
            raise Ineligible("stage_claims_disabled")
        _current(store, cursor, workspace_id, actor_id, watch, opportunity_id, now, revision=revision, receipt_id=receipt_id)
        if channel != "in_app":
            raise Ineligible("trend_external_channel_not_authorized")
        prefs = planner.effective_preferences(notification_store.preference_rows(cursor, actor_id), workspace_id, "opportunities")
        if prefs.get("in_app", True) is False:
            raise Ineligible("in_app_off")
        return {"eligible": True, "reason": None}
    except (Ineligible, contracts.ContractError, AlphaError, KeyError, TypeError, ValueError) as error:
        return {"eligible": False, "reason": str(error) if isinstance(error, Ineligible) else "current_evidence_unavailable"}


def tick(store, values=None, limit=20):
    """Server-selected scan of at most two workspaces and ``limit`` opportunities.

    Uses the reserved local namespace in the existing 040 provider-cursor table.
    This metadata creates no provider contract, source policy or dispatch job.
    The general notification detector watermark and workspace revisions are untouched.
    Each catalogue cycle freezes its available-at cutoff. Keyset progress moves
    past every examined ID, including ineligible ones, then wraps for rechecks.
    Least-recently-scanned workspaces rotate even when their page emits nothing.
    The cursor and existing outbox emission commit in the same transaction.
    A global try-lock prevents overlapping ticks; sweep still owns admission.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("invalid_tick_bound")
    source = flags._source(values)
    result = {"status": "disabled", "workspaces": 0, "checked": 0, "created": 0,
              "duplicates": 0, "skipped": {}, "partial_workspaces": 0,
              "execution_state": "in_app_outbox_only"}
    try:
        allowed = sorted({contracts.uuid(v.strip()) for v in str(source.get("RAFII_TREND_WORKSPACE_ALLOWLIST", "")).split(",") if v.strip()})
    except ValueError:
        allowed = []
    allowed = [wid for wid in allowed if _enabled(wid, source)]
    # Enrolled workspaces get in-app watch alerts too, but only while the cohort
    # switch is on; a closed cohort with no allowlist still has zero DB effects.
    self_serve = (_flags_on(source) and config.enabled("INTELLIGENCE", source)
                  and feature_enrollment.self_serve_open(admission.FEATURE, source))
    if not allowed and not self_serve:
        return result  # Disabled means zero DB effects, including scan bookkeeping.
    now = opportunities.epoch(time.time())
    with store.transaction() as cur:
        if self_serve:
            allowed = sorted(set(allowed) | set(feature_enrollment.admitted_workspaces(cur, admission.FEATURE, source)))
            if not allowed:
                return result
        trust_lock(cur)
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('trend-notifications-tick-v1',0))")
        if not cur.fetchone()[0]:
            return {**result, "status": "busy"}
        cur.execute("""SELECT w.id::text,actor.created_by::text
            FROM public.pr_workspaces w
            LEFT JOIN public.pr_trend_provider_cursors scan
              ON scan.scope_key='workspace:'||w.id::text
              AND scan.provider_id=%s AND scan.partition_key=%s
            JOIN LATERAL (
                SELECT watch.created_by FROM public.pr_trend_watches watch
                JOIN public.pr_memberships m ON m.workspace_id=watch.workspace_id AND m.user_id=watch.created_by
                JOIN public.pr_profiles profile ON profile.user_id=m.user_id
                WHERE watch.workspace_id=w.id AND watch.enabled
                  AND watch.payload->>'notification_policy'='in_app'
                  AND watch.payload->>'threshold' IN ('stage_change','coverage_change')
                  AND m.status='active' AND m.role IN ('owner','editor') AND profile.deleted_at IS NULL
                ORDER BY watch.created_at,watch.watch_id LIMIT 1
            ) actor ON true
            WHERE w.id=ANY(%s::uuid[]) AND NOT w.state ? 'accountDeletion'
              AND coalesce(w.state->'workspace'->>'sample','false')<>'true'
            ORDER BY scan.updated_at NULLS FIRST,w.id
            LIMIT %s""", (SCAN_PROVIDER, SCAN_PARTITION, allowed, min(2, limit)))
        selected = cur.fetchall()
        result["status"] = "ok"
        remaining = limit
        for index, (workspace_id, actor_id) in enumerate(selected):
            _workspace(cur, workspace_id)
            scope_key = store.ensure_scope("workspace:" + workspace_id, cursor=cur)
            cur.execute("""INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key)
                           VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""", (scope_key, SCAN_PROVIDER, SCAN_PARTITION))
            cur.execute("""SELECT generation,cursor_value FROM public.pr_trend_provider_cursors
                           WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE""",
                        (scope_key, SCAN_PROVIDER, SCAN_PARTITION))
            generation, saved = cur.fetchone()
            after, cutoff = None, now
            if isinstance(saved, dict) and saved.get("after_object_id"):
                try:
                    after = contracts.uuid(saved["after_object_id"])
                    cutoff = min(now, opportunities.epoch(saved["cycle_cutoff"]))
                except (KeyError, ValueError, TypeError):
                    after, cutoff = None, now
            quota = max(1, remaining // (len(selected)-index))
            cur.execute("""SELECT p.object_id::text FROM public.pr_trend_projections p
                WHERE p.scope_key=%s AND p.kind='opportunity' AND p.available_at<=to_timestamp(%s)
                  AND p.retention_until>to_timestamp(%s)
                  AND (%s::uuid IS NULL OR p.object_id>%s::uuid)
                  AND NOT EXISTS (SELECT 1 FROM public.pr_trend_projections newer
                    WHERE (newer.scope_key,newer.kind,newer.object_id)=(p.scope_key,p.kind,p.object_id)
                      AND newer.revision>p.revision AND newer.available_at<=to_timestamp(%s))
                  AND EXISTS (SELECT 1 FROM public.pr_trend_watches watch
                    JOIN public.pr_memberships m ON m.workspace_id=watch.workspace_id AND m.user_id=watch.created_by
                    JOIN public.pr_profiles profile ON profile.user_id=m.user_id
                    WHERE watch.workspace_id=%s AND watch.enabled
                      AND watch.payload->>'notification_policy'='in_app'
                      AND watch.payload->>'threshold' IN ('stage_change','coverage_change')
                      AND watch.payload->>'trend_id'=p.payload->>'trend_id'
                      AND m.status='active' AND m.role IN ('owner','editor') AND profile.deleted_at IS NULL)
                ORDER BY p.object_id LIMIT %s""",
                ("workspace:" + workspace_id, cutoff, now, after, after, now, workspace_id, quota+1))
            found = [r[0] for r in cur.fetchall()]
            ids, more = found[:quota], len(found) > quota
            cur.execute("SAVEPOINT trend_notification_page")
            try:
                outcome = sweep(store, workspace_id=workspace_id, actor_id=actor_id,
                                opportunity_ids=ids, values=source, now=now, limit=quota, cursor=cur)
            except Exception:  # A failed page rolls back its effects and rotates for bounded retry.
                cur.execute("ROLLBACK TO SAVEPOINT trend_notification_page")
                outcome = {"checked": len(ids), "created": 0, "duplicates": 0,
                           "skipped": {"page_unavailable": 1}}
                result["status"] = "partial"
            finally:
                cur.execute("RELEASE SAVEPOINT trend_notification_page")
            for key in ("checked", "created", "duplicates"):
                result[key] += outcome[key]
            for reason, count in outcome["skipped"].items():
                result["skipped"][reason] = result["skipped"].get(reason, 0) + count
            checkpoint = {"cycle_cutoff": opportunities.iso(cutoff),
                          "after_object_id": ids[-1] if more else None,
                          "scanned_at": opportunities.iso(now)}
            cur.execute("""UPDATE public.pr_trend_provider_cursors
                           SET generation=generation+1,cursor_value=%s::jsonb,coverage_state=%s,updated_at=clock_timestamp()
                           WHERE scope_key=%s AND provider_id=%s AND partition_key=%s AND generation=%s
                           RETURNING generation""",
                        (json.dumps(checkpoint), "gap" if "page_unavailable" in outcome["skipped"] else "partial" if more else "complete",
                         scope_key, SCAN_PROVIDER, SCAN_PARTITION, generation))
            advanced = cur.fetchone()
            if not advanced or advanced[0] != generation + 1:
                raise contracts.ContractError("notification_cursor_generation_conflict")
            result["workspaces"] += 1
            result["partial_workspaces"] += int(more)
            remaining -= len(ids)
        if result["partial_workspaces"]:
            result["status"] = "partial"
    return result
