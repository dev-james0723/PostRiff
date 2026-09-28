"""Stored, private recommendation measurement for existing Performance/Weekly reads.

No provider/model calls, writes during report(), causal estimates or strategy adoption.
The caller supplies an authenticated transaction and TrendStore. Workspace state is
loaded here, not accepted from a request body. All trend inputs pass current rights.
"""
from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy

from . import contracts, opportunities
from .exposures import creator_baseline
from ...coworker import performance
from ...insights import INSIGHT_METRICS

VERSION = "rafii.trend-learning.v1"
WINDOWS = {"1h": 3600, "24h": 86400, "7d": 604800}
OBJECTIVES = {"reach", "shareability", "conversation", "follower_conversion", "custom_metric"}


def _stamp(value):
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    try:
        return opportunities.epoch(value)
    except (ValueError, TypeError, AttributeError):
        return None


def record_metric_choice(state, actor_id, payload, now):
    """Existing explicit workspace command may persist this choice; never parse goals.

    Caller must authorize the actor's edit and persist state in its normal command
    transaction. A choice applies only to future publications of this selection.
    """
    required = {"selection_digest", "channel_id", "provider", "metric", "definition_version", "window", "objective"}
    if not isinstance(payload, dict) or set(payload) - required - {"denominator_metric"} or not required <= set(payload):
        raise ValueError("invalid_metric_choice")
    provider = payload["provider"]
    native = INSIGHT_METRICS.get(provider, ())
    if (payload["metric"] not in native or payload.get("denominator_metric") not in (None, *native)
            or payload["window"] not in WINDOWS or payload["objective"] not in OBJECTIVES
            or payload.get("denominator_metric") == payload["metric"]
            or not isinstance(payload["definition_version"], str) or not 1 <= len(payload["definition_version"]) <= 100):
        raise ValueError("invalid_metric_choice")
    sources = [s for s in state.get("sources", []) if s.get("active")]
    bindings = [(s.get("origin") or {}).get("trendLineage", {}) for s in sources]
    if not any(b.get("selection_digest") == payload["selection_digest"] and b.get("channel_id") == payload["channel_id"] for b in bindings):
        raise ValueError("selection_unavailable")
    if not any(c.get("id") == payload["channel_id"] and str(c.get("platform", "")).lower() == provider and not c.get("revoked")
               for c in (state.get("phase2") or {}).get("channels", [])):
        raise ValueError("account_unavailable")
    choice = {**deepcopy(payload), "confirmed": True, "selected_by": actor_id, "selected_at": opportunities.iso(now)}
    choice["id"] = contracts.digest(choice)
    root = state.setdefault("coworker", {}).setdefault("trendLearning", {})
    root["metricChoices"] = (root.get("metricChoices", []) + [choice])[-100:]
    return deepcopy(choice)


def _valid(row, now):
    return bool(row and row.get("validity") == "valid" and isinstance(row.get("payload"), dict)
                and (_stamp(row.get("expires_at")) or 0) > now
                and all(row.get("policy", {}).get(k) is True for k in ("derive_metrics", "retain_derivatives")))


def _choice(state, binding, manifest, published_at, window):
    choices = ((state.get("coworker") or {}).get("trendLearning") or {}).get("metricChoices", [])
    valid = []
    for c in choices[-100:]:
        if (not isinstance(c, dict) or c.get("confirmed") is not True or not c.get("selected_by")
                or c.get("selection_digest") != binding.get("selection_digest") or c.get("channel_id") != manifest.get("channelId")
                or c.get("provider") != str(manifest.get("platform", "")).lower() or c.get("window") != window
                or c.get("objective") not in OBJECTIVES or not c.get("definition_version")
                or not 0 < (_stamp(c.get("selected_at")) or 0) <= published_at):
            continue
        native = INSIGHT_METRICS.get(c["provider"], ())
        if c.get("metric") not in native or c.get("denominator_metric") not in (None, *native) or c.get("metric") == c.get("denominator_metric"):
            continue
        valid.append(c)
    return max(valid, key=lambda c: (_stamp(c["selected_at"]), c.get("id", ""))) if valid else None


def _metric(cur, wid, job, choice, now, published_at):
    names = [choice["metric"]] + ([choice["denominator_metric"]] if choice.get("denominator_metric") else [])
    # Read the exact job/account/provider/post and definition. Never substitute a
    # later corrected post or a different native counter/offset. Knowledge cutoff
    # applies to both provider observation time and local ingestion time.
    cur.execute("""SELECT DISTINCT ON (metric) metric,value,unit,availability,
        extract(epoch from observed_at),extract(epoch from ingested_at),id::text
        FROM public.pr_metric_observations WHERE workspace_id=%s AND job_id=%s
        AND connection_id=%s AND provider=%s AND provider_post_id=%s
        AND definition_version=%s AND read_offset=%s AND metric=ANY(%s)
        AND observed_at<=to_timestamp(%s) AND ingested_at<=to_timestamp(%s)
        AND observed_at>=to_timestamp(%s)
        ORDER BY metric,observed_at DESC,ingested_at DESC,id DESC""",
        (wid, job["id"], choice["channel_id"], choice["provider"], job["providerReference"],
         choice["definition_version"], choice["window"], names, now, now, published_at + WINDOWS[choice["window"]]))
    rows = {r[0]: r for r in cur.fetchall()}
    if any(n not in rows for n in names):
        return {"state": "delayed", "value": None, "reason": "native_observation_not_yet_available"}
    if any(rows[n][3] != "available" for n in names):
        return {"state": "unavailable", "value": None, "reason": "native_metric_unavailable"}
    values = [float(rows[n][1]) for n in names]
    if any(not math.isfinite(v) or v < 0 for v in values) or any(rows[n][2] != "count" for n in names):
        return {"state": "unavailable", "value": None, "reason": "incompatible_native_measurement"}
    if len(values) == 2 and values[1] == 0:
        return {"state": "unavailable", "value": None, "reason": "zero_denominator"}
    return {"state": "measured", "value": values[0] / values[1] if len(values) == 2 else values[0],
            "native_values": dict(zip(names, values)), "unit": "ratio" if len(names) == 2 else "count",
            "observed_at": max(float(rows[n][4]) for n in names),
            "available_at": max(float(rows[n][5]) for n in names), "metric_receipts": [rows[n][6] for n in names]}


def _publication(cur, wid, state, binding, accepted, job, now, window):
    manifest = job.get("manifest", {})
    frozen = manifest.get("trendPublication", {})
    published_at = _stamp(job.get("verifiedAt"))
    out = {"job_id": job.get("id"), "state": "unpublished", "value": None, "treatment_state": "unknown", "causal": False}
    if job.get("state") != "verified" or not job.get("providerReference") or not published_at or published_at > now:
        return out
    if not 0 < (_stamp(accepted.get("accepted_at")) or 0) <= published_at:
        return {**out, "state": "invalid_publication_chronology"}
    text = performance._text(job)
    if (type(frozen.get("variantRevision")) is not int or frozen["variantRevision"] < 1
            or frozen.get("textDigest") != contracts.digest(text)
            or frozen.get("channelId") != manifest.get("channelId") or frozen.get("platform") != manifest.get("platform")
            or binding.get("channel_id") != manifest.get("channelId")
            or str(binding.get("platform", "")).lower() != str(manifest.get("platform", "")).lower()):
        return {**out, "state": "invalid_published_revision"}
    out.update(publication={"variant_revision": frozen["variantRevision"], "text_digest": frozen["textDigest"],
                            "platform_post_id": job["providerReference"], "published_at": published_at},
               angle_id=binding.get("angle_id"), selection_digest=binding.get("selection_digest"))
    # Preserve the actual frozen angle, not the current editable draft. A matching
    # ID alone does not prove that the user kept the recommendation's meaning.
    if (binding.get("angle_id") != accepted.get("angle_id") or binding.get("selection_digest") != accepted.get("selection_digest")
            or frozen.get("treatmentChanged") is True):
        out["treatment_state"] = "changed"
    elif frozen.get("treatmentChanged") is False:
        out["treatment_state"] = "unchanged"
    choice = _choice(state, binding, manifest, published_at, window)
    if choice is None:
        return {**out, "state": "objective_unselected"}
    out["objective_choice_id"] = choice["id"]
    out["metric"] = "/".join([choice["metric"]] + ([choice["denominator_metric"]] if choice.get("denominator_metric") else []))
    out["cohort"] = {"account": manifest["channelId"], "provider": choice["provider"],
                     "language": manifest.get("payload", {}).get("language"), "format": manifest.get("contentType", {}).get("id"),
                     "window": window, "objective": choice["objective"], "definition": choice["definition_version"], "metric": out["metric"]}
    if not any(c.get("id") == choice["channel_id"] and not c.get("revoked") and str(c.get("platform", "")).lower() == choice["provider"]
               for c in (state.get("phase2") or {}).get("channels", [])):
        return {**out, "state": "account_unavailable"}
    if published_at + WINDOWS[window] > now:
        return {**out, "state": "pending_horizon"}
    out.update(_metric(cur, wid, job, choice, now, published_at))
    out["features"] = performance.features(job)
    out["paid_promotion"] = manifest.get("paidPromotion")
    return out


def report(cur, workspace_id, actor_id, now, *, store, window="24h", limit=100):
    """Return a bounded current-rights report for existing Performance/Weekly reads.

    `denominator` covers retained, currently permitted client-reported views in
    the returned page, not people or all historical recommendations. Missing or
    withheld exposures never become zero-engagement observations.
    """
    if window not in WINDOWS or type(limit) is not int or not 1 <= limit <= 100 or not _stamp(now):
        raise ValueError("invalid_learning_bounds")
    store.authorized_scopes(workspace_id, actor_id, cursor=cur)
    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
    found = cur.fetchone()
    if not found:
        raise ValueError("workspace_unavailable")
    state = found[0]
    page = store.list_projections(workspace_id, actor_id, kind="exposure", limit=limit,
        filters={"scope_key": "workspace:" + workspace_id}, as_of=opportunities.iso(now), cursor=cur)
    # Long-horizon metadata have a separately reviewed purpose grant and privacy
    # cascade. Only this typed reader can admit them; a generic projection read
    # would miss source/author tombstones after raw payload expiry.
    from . import analytics_retention
    retained = analytics_retention.list_current(store, cur, workspace_id, actor_id, limit=limit)
    entries = {p["object_id"]: p for p in page["items"]}
    for item in retained["items"]:
        metadata = item["metadata"]
        if (_stamp(metadata["recorded_at"]) or now + 1) <= now < (_stamp(item["analytics_expires_at"]) or 0):
            entries[metadata["exposure_id"]] = {"object_id": metadata["exposure_id"], "payload": metadata, "independent_analytics": True}
    selected = sorted(entries.values(), key=lambda p: ((p.get("payload") or {}).get("recorded_at", ""), p["object_id"]), reverse=True)[:limit]
    cur.execute("""SELECT object_id::text,revision,decision,actor_id::text,result,extract(epoch from created_at)
        FROM public.pr_trend_opportunity_decisions WHERE workspace_id=%s AND created_at<=to_timestamp(%s)
        ORDER BY created_at DESC,idempotency_key DESC LIMIT 201""", (workspace_id, now))
    decisions = cur.fetchall()
    truncated_decisions = len(decisions) > 200
    decisions = decisions[:200]
    sources = {s["id"]: s for s in state.get("sources", []) if s.get("active")}
    jobs = ((state.get("phase2") or {}).get("jobs") or [])[-120:]
    native_counts = Counter((str(j.get("manifest", {}).get("platform", "")).lower(),
                             j.get("manifest", {}).get("channelId"), j.get("providerReference"))
                            for j in jobs if j.get("state") == "verified" and j.get("providerReference"))
    safe = {}
    def current(oid, revision):
        key = (oid, revision)
        if key not in safe:
            safe[key] = store.get_projection(workspace_id, actor_id, "opportunity", oid, revision=revision, cursor=cur)
            if _valid(safe[key], now):
                rid = safe[key]["payload"].get("trust_receipt_id")
                receipt = store.get_projection(workspace_id, actor_id, "receipt", rid, cursor=cur) if rid else None
                if not _valid(receipt, now) or receipt.get("verification_state") != "verified":
                    safe[key] = None
        return safe[key] if _valid(safe[key], now) and safe[key]["scope_key"] == "workspace:" + workspace_id else None
    exposures, totals, ignored = [], Counter(), Counter()
    linked_decisions = set()
    for row in selected:
        p = row.get("payload") or {}
        independent = row.get("independent_analytics") is True
        if (not independent and not _valid(row, now)) or p.get("workspace_id") != workspace_id or p.get("exposure_id") != row["object_id"]:
            ignored["current_rights_or_shape"] += 1
            continue
        if not independent:
            op = current(p["opportunity_id"], p["opportunity_revision"])
            if (not op or p.get("trust_receipt_id") != op["payload"].get("trust_receipt_id")
                    or p.get("context_digest") != op["payload"].get("context_digest")):
                ignored["opportunity_unavailable"] += 1
                continue
        matches = [d for d in decisions if d[0] == p["opportunity_id"] and d[1] == p["opportunity_revision"]
                   and d[3] == p.get("actor_id") and d[4].get("exposure_id") == p["exposure_id"]
                   and float(d[5]) >= (_stamp(p.get("recorded_at")) or now)]
        kinds = {d[2] for d in matches}
        decision = ("accepted" if kinds == {"accept"} else "dismissed" if kinds == {"dismiss"} else "unknown" if kinds else "unaccepted")
        event = {"exposure_id": p["exposure_id"], "opportunity_id": p["opportunity_id"], "opportunity_revision": p["opportunity_revision"],
                 "measurement": p.get("measurement"), "eligible_candidate_count": p.get("eligible_candidate_count"),
                 "candidate_scope": "returned_page", "decision": decision, "outcomes": [],
                 "retention_basis": "independent_reviewed_metadata" if independent else "current_source_dependencies",
                 "source_rights_extended": False}
        totals[decision] += 1
        linked_decisions.update((d[0], d[1], d[2], d[3], str(d[5])) for d in matches)
        if decision == "accepted":
            result = matches[0][4]
            source = sources.get(result.get("source_id"), {})
            accepted = (source.get("origin") or {}).get("trendLineage", {})
            if (accepted.get("exposure_id") != p["exposure_id"] or accepted.get("opportunity_id") != p["opportunity_id"]
                    or accepted.get("opportunity_revision") != p["opportunity_revision"]
                    or accepted.get("trust_receipt_id") != p["trust_receipt_id"]
                    or accepted.get("context_digest") != p.get("context_digest")):
                event["publication_coverage"] = "accepted_source_unavailable"
            else:
                for job in jobs:
                    job_manifest = job.get("manifest") or {}
                    bindings = job_manifest.get("trendLineage", [])
                    for b in bindings[:20]:
                        if (b.get("exposure_id") == p["exposure_id"] and b.get("opportunity_id") == p["opportunity_id"]
                                and b.get("opportunity_revision") == p["opportunity_revision"]
                                and b.get("trust_receipt_id") == p["trust_receipt_id"]):
                            native_key = (str(job_manifest.get("platform", "")).lower(), job_manifest.get("channelId"), job.get("providerReference"))
                            if native_counts[native_key] > 1:
                                outcome = {"job_id": job.get("id"), "state": "ambiguous_native_publication", "value": None, "treatment_state": "unknown"}
                            else:
                                outcome = _publication(cur, workspace_id, state, b, accepted, job, now, window)
                                if len(bindings) > 1:
                                    outcome["treatment_state"] = "unknown"
                                    outcome["attribution"] = "multiple_recommendations_in_one_publication"
                            event["outcomes"].append(outcome)
                            break
                event["publication_coverage"] = "observed_jobs" if event["outcomes"] else "not_published"
        exposures.append(event)
    # Decisions with no recorded view remain outside the acceptance denominator.
    unlinked = Counter()
    for d in decisions:
        if (d[0], d[1], d[2], d[3], str(d[5])) not in linked_decisions and current(d[0], d[1]):
            unlinked["accepted_without_exposure" if d[2] == "accept" else "dismissed_without_exposure" if d[2] == "dismiss" else "unknown_without_exposure"] += 1
    outcomes = [o for e in exposures for o in e["outcomes"]]
    measured = list({(o["job_id"], contracts.digest(o["cohort"])): o for o in outcomes if o["state"] == "measured"}.values())
    for target in measured:
        cohort = target["cohort"]
        if not all(cohort.get(k) for k in ("account", "provider", "language", "format", "definition")):
            target["baseline"] = {"count": 0, "median": None, "mad": None, "state": "unknown", "reason": "incomplete_comparison_cohort"}
            continue
        target_time = target["publication"]["published_at"]
        peers = []
        for o in measured:
            if (o["job_id"] == target["job_id"] or o["cohort"] != cohort or o["publication"]["published_at"] >= target_time
                    or o["observed_at"] > target_time or o["available_at"] > target_time or o.get("paid_promotion") is not False):
                continue
            peers.append({"workspace_id": workspace_id, "post_id": o["job_id"], "account_id": cohort["account"],
                "platform": cohort["provider"], "format": cohort["format"], "language": cohort["language"],
                "horizon_hours": WINDOWS[window] / 3600, "metric_definition": contracts.digest(cohort), "value": o["value"],
                "verified_published": True, "rights": {"analysis": True}, "complete": True, "paid_promotion": False,
                "observed_at": opportunities.iso(o["observed_at"]), "available_at": opportunities.iso(o["available_at"]),
                "event_at": opportunities.iso(o["publication"]["published_at"])})
        baseline = creator_baseline({"workspace_id": workspace_id, "scope_key": "workspace:" + workspace_id, "decision_cutoff": opportunities.iso(target_time),
            "target": {"post_id": target["job_id"], "account_id": cohort["account"], "platform": cohort["provider"],
                       "format": cohort["format"], "language": cohort["language"], "horizon_hours": WINDOWS[window] / 3600,
                       "metric_definition": contracts.digest(cohort)}, "outcomes": peers})
        target["baseline"] = {k: baseline[k] for k in ("count", "median", "mad", "state", "confounders")}
    return {"schema_version": VERSION, "as_of": opportunities.iso(now), "window": window,
        "denominator": {"exposures": len(exposures), **{k: totals[k] for k in ("accepted", "dismissed", "unaccepted", "unknown")},
                        **{k: unlinked[k] for k in ("accepted_without_exposure", "dismissed_without_exposure", "unknown_without_exposure")}},
        "coverage": {"exposure_page_truncated": bool(page.get("next_key")) or retained["truncated"] or len(entries) > limit,
                     "independent_analytics_views": sum(e["retention_basis"] == "independent_reviewed_metadata" for e in exposures),
                     "decisions_truncated": truncated_decisions,
                     "job_history_truncated": len(((state.get("phase2") or {}).get("jobs") or [])) > 120,
                     "suppressed_in_page": dict(ignored), "scope": "current_permitted_retained_client_views",
                     "historical_denominator_complete": False},
        "outcome_states": dict(Counter(o["state"] for o in outcomes)), "exposures": exposures,
        "causal": False, "durable_strategy": False, "limitations": [
            "Client reports measure views, not unique people; candidate sets cover returned pages only.",
            "Long-horizon views require independently reviewed metadata rights and current privacy checks; raw content rights are never extended.",
            "Without that grant, expired source-dependent views are suppressed and 24h/7d denominator coverage may be incomplete.",
            "Unaccepted, missing and unavailable outcomes are not zero engagement. No causal or power claim.",
            "A matching angle ID does not prove unchanged meaning; treatment is unknown without a frozen assessment.",
            "Baselines use earlier available measured posts in this bounded retained sample; promotion must be explicitly absent."]}


def hypotheses(descriptor, now):
    """Adapt permitted measured unchanged publications into existing hypothesis logic.

    Return candidates for Performance.refresh's existing persistence/adoption flow;
    this function neither persists nor accepts them and creates no new learner.
    """
    rows, seen = [], set()
    for e in descriptor.get("exposures", []):
        for o in e.get("outcomes", []):
            if (o.get("state") != "measured" or o.get("treatment_state") != "unchanged" or o.get("paid_promotion") is not False
                    or o["job_id"] in seen or not all(o["cohort"].get(k) for k in ("account", "provider", "language", "format", "definition"))):
                continue
            seen.add(o["job_id"])
            rows.append({"jobId": o["job_id"], "value": o["value"], "metric": o["metric"], "cohort": o["cohort"],
                         "features": o["features"], "observedAt": o["observed_at"], "publishedAt": o["publication"]["published_at"]})
    found = performance.hypotheses_from(rows, now)
    for h in found:
        dimension = h["dimension"]
        h["dimension"] = "trend_" + contracts.digest([dimension, h["cohort"]])[:32]
        h["metric"] = h["cohort"]["metric"]
        h["statement"] = (f"The {dimension} pattern may be associated with {h['metric']} in this account's adopted trend posts "
                          f"({h['sample_a']} and {h['sample_b']} posts). Selection-limited descriptive evidence, not causal uplift.")
    return found


def current_hypotheses(cur, workspace_id, descriptor, now):
    """Revalidate saved trend interpretations against today's permitted evidence.

    A persisted candidate is not permission to retain or display its conclusion.
    Reuse the existing learner and require the stored support to match the current
    report; cohort changes, revoked sources, missing metrics and flag-off reads
    therefore fail closed without changing owner decisions or learning history.
    """
    if descriptor is None:
        return {}
    fields = ('platform', 'dimension', 'cohort', 'statement', 'metric', 'arm_a',
              'arm_b', 'sample_a', 'sample_b', 'effect', 'evidence_ids', 'counter_evidence_ids')
    def signature(h):
        value = {key: h[key] for key in fields}
        value['effect'] = float(value['effect']) if value['effect'] is not None else None
        for key in ('evidence_ids', 'counter_evidence_ids'):
            value[key] = sorted(value[key] or [])
        return contracts.digest(value)
    supported = {signature(h) for h in hypotheses(descriptor, now)}
    if not supported:
        return {}
    cur.execute("""SELECT id::text, platform, dimension, cohort, statement, metric, arm_a, arm_b,
                          sample_a, sample_b, effect, evidence_ids, counter_evidence_ids
                   FROM pr_strategy_hypotheses WHERE workspace_id=%s AND left(dimension,6)='trend_'
                     AND causal=false AND expires_at>to_timestamp(%s)""", (workspace_id, now))
    return {r[0]: digest for r in cur.fetchall()
            if (digest := signature(dict(zip(fields, r[1:])))) in supported}
