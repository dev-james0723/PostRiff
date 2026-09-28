"""Objective-specific observed outcomes. No model score is an input to success."""
from __future__ import annotations

import statistics

from .scout_evidence import number

METRICS = ("reach", "impressions", "views", "shares", "reposts", "saves", "comments", "replies", "profile_visits", "follows",
           "watch_time", "average_watch_duration", "completion_rate", "replay_rate", "three_second_views")
COHORT = ("account", "provider", "language", "format", "window", "objective", "definition")


def value(row, name):
    metrics = row.get("metrics")
    m = metrics.get(name) if isinstance(metrics, dict) else None
    if not isinstance(m, dict):
        return None
    v = m.get("value")
    return v if m.get("coverage") == "available" and number(v) and v >= 0 and m.get("receipt") and number(m.get("observedAt")) else None


def rate(row, numerator, denominator):
    n, d = value(row, numerator), value(row, denominator)
    return {"value": n / d if n is not None and d is not None and d > 0 else None, "numerator": n,
            "denominator": d, "definition": f"{numerator}/{denominator}", "coverage": "available" if n is not None and d is not None and d > 0 else "unavailable"}


def objective_measure(row):
    objective = row.get("objective")
    if objective == "follower_conversion":
        return rate(row, "follows", "profile_visits")["value"], "follows/profile_visits"
    if objective in ("shareability", "conversation"):
        for metric in (("shares", "reposts", "saves") if objective == "shareability" else ("replies", "comments")):
            for denominator in ("impressions", "reach", "views"):
                r = rate(row, metric, denominator)
                if r["value"] is not None:
                    return r["value"], r["definition"]
        return None, None
    if objective == "reach":
        for metric in ("reach", "impressions", "views"):
            if value(row, metric) is not None:
                return value(row, metric), metric
    # Authority has no universal metric proxy; likes are never a substitute.
    return None, None


def evaluate(row, history):
    current, metric = objective_measure(row)
    out = {"state": "measurement_unavailable", "nextAction": "wait", "metric": metric, "value": current,
           "samples": 0, "baseline": None, "lift": None, "businessReturn": "unmeasured", "causal": False,
           "durableStrategy": False, "evidenceIds": [], "counterEvidenceIds": [], "reason": "Objective outcomes unavailable."}
    if current is None:
        return out
    if row.get("window") == "1h":
        return {**out, "state": "observing", "reason": "One-hour readings are early evidence; wait for a comparable 24h or 7d window."}
    if row.get("window") not in ("24h", "7d"):
        return {**out, "state": "insufficient_data", "reason": "A comparable observation window is required."}
    peers = {}
    for r in history:
        if not isinstance(r, dict):
            continue
        if r.get("id") == row.get("id") or not r.get("id") or any(r.get(k) != row.get(k) or row.get(k) is None for k in COHORT):
            continue
        if not number(r.get("publishedAt")) or not number(row.get("publishedAt")) or not row["publishedAt"] - 90 * 86400 <= r["publishedAt"] < row["publishedAt"]:
            continue
        v, definition = objective_measure(r)
        if v is not None and definition == metric:
            peers[r["id"]] = v
    out["samples"] = len(peers)
    if len(peers) < 5:
        return {**out, "state": "needs_more_data", "reason": "Fewer than five earlier comparable measured posts."}
    baseline = statistics.median(peers.values())
    out.update(baseline=baseline, evidenceIds=[k for k, v in peers.items() if current > v][:20],
               counterEvidenceIds=[k for k, v in peers.items() if current <= v][:20])
    if baseline <= 0:
        return {**out, "state": "insufficient_data", "reason": "Zero baseline; relative lift is undefined."}
    lift = current / baseline
    return {**out, "lift": lift, "state": "double_down_candidate" if lift >= 1.5 else "underperformed" if lift < .75 else "completed",
            "nextAction": "sequel" if lift >= 1.5 else "stop" if lift < .75 else "wait",
            "reason": "Compared with this account's earlier posts of the same platform, language, format, objective, metric definition and window. Not causal; review before acting."}


def from_insights(post, job, plan, window):
    metrics = {}
    for name in METRICS:
        native = "saved" if name == "saves" and post["provider"] == "instagram" else name
        m = post.get("metrics", {}).get(native) or {}
        available = m.get("availability") == "available" and m.get("readOffset") == window
        metrics[name] = {"value": m.get("value") if available else None, "provider": post["provider"], "account": post["connectionId"],
                         "window": window, "definition": f'{post["provider"]}:{post["definitionVersion"]}:{native}', "denominator": None,
                         "coverage": "available" if available else "unavailable", "observedAt": m.get("observedAt"),
                         "receipt": f'job:{job["id"]}:{name}:{window}:{m.get("observedAt")}' if available else None}
    return {"id": job["id"], "account": post["connectionId"], "provider": post["provider"], "language": post["language"],
            "format": post.get("contentTypeId"), "window": window, "objective": plan["primaryObjective"], "definition": post["definitionVersion"],
            "publishedAt": job.get("verifiedAt") or job.get("approvedAt"), "metrics": metrics,
            "opportunityId": plan["opportunityId"], "executionPlanId": plan["id"]}


def refresh(cur, workspace_id, state, now):
    """Read existing append-only metrics and draft/source lineage; never overwrite observations."""
    from .. import insights
    listening = (state.get("coworker") or {}).get("listening") or {}
    sources = {s["id"]: s for s in state.get("sources", [])}
    variants = {v["id"]: v for v in state.get("variants", [])}
    jobs = [j for j in (state.get("phase2") or {}).get("jobs", []) if j.get("state") == "verified"][-120:]
    by_job = {j["id"]: j for j in jobs}
    rows = []
    for window in ("1h", "24h", "7d"):
        posts = insights.summary(cur, workspace_id, jobs, now, basis=window)["posts"]
        for post in posts:
            job = by_job.get(post.get("jobId"))
            if not job:
                continue
            variant = variants.get(job.get("manifest", {}).get("variantId"), {})
            manifest = job.get("manifest", {})
            if "scoutLineage" in manifest:
                plans = [b["executionPlan"] for b in manifest["scoutLineage"]]
            else:  # Legacy published jobs predate frozen lineage.
                plans = [b["executionPlan"] for b in variant.get("scoutLineage", [])]
                plans += [(sources.get(sid, {}).get("origin") or {}).get("executionPlan") for sid in variant.get("sourceIds", [])]
            for binding in manifest.get("trendLineage", []):
                if binding["channel_id"] != manifest.get("channelId") or binding["platform"] != post.get("platform"):
                    continue
                # Free-text creator goals cannot be silently converted into a metric.
                measured = from_insights(post, job, {"primaryObjective": "unmeasured", "opportunityId": binding["opportunity_id"], "id": binding["selection_digest"]}, window)
                measured["trendLineage"] = {k: binding.get(k) for k in ("opportunity_id", "opportunity_revision", "trend_id", "trust_receipt_id", "context_digest", "angle_id", "goal", "selection_digest")}
                if binding.get("exposure_id"):
                    measured["trendLineage"]["exposure_id"] = binding["exposure_id"]
                measured["publication"] = manifest.get("trendPublication")
                rows.append(measured)
            for plan in plans:
                if plan and plan["platform"] == post.get("platform") and plan["account"] == job.get("manifest", {}).get("channelId"):
                    rows.append(from_insights(post, job, plan, window))
                    break
    for op in listening.get("opportunities", []):
        results = [{"jobId": r["id"], "window": r["window"], "executionPlanId": r["executionPlanId"], "metrics": r["metrics"], **evaluate(r, rows)}
                   for r in rows if r["opportunityId"] == op["id"]]
        if results:
            op["outcomes"] = results[-12:]
    return rows


def hypotheses(cur, workspace_id, state, now):
    """Repeated objective evidence enters the existing hypothesis/owner-review system.

    Minimum five posts per arm is inherited from Performance Learning. Account,
    objective, window and metric stay in the identity as well as the cohort.
    Nothing here accepts a hypothesis or mutates writing preferences.
    """
    from ..coworker import performance
    from .scout import key
    jobs = {j["id"]: j for j in (state.get("phase2") or {}).get("jobs", [])}
    rows = []
    for row in refresh(cur, workspace_id, state, now):
        value_, metric = objective_measure(row)
        if row["window"] != "24h" or value_ is None or not row.get("format") or not row.get("language"):
            continue
        observed = [m["observedAt"] for m in row["metrics"].values() if m["coverage"] == "available"]
        rows.append({"jobId": row["id"], "value": value_, "metric": metric, "cohort": {k: row[k] for k in COHORT} | {"metric": metric},
                     "features": performance.features(jobs[row["id"]]), "observedAt": max(observed), "publishedAt": row["publishedAt"]})
    found = performance.hypotheses_from(rows, now)
    for h in found:
        dimension = h["dimension"]
        h["dimension"] = key("scout_" + dimension + "_", h["cohort"])[:40]
        h["metric"] = h["cohort"]["metric"]
        h["statement"] = (f"The {dimension} pattern may support {h['cohort']['objective'].replace('_', ' ')} for this account "
                          f"({h['sample_a']} and {h['sample_b']} comparable posts; {len(h['counter_evidence_ids'])} counterexamples). "
                          "Observed association; review as an experiment, not a causal rule.")
    return found
