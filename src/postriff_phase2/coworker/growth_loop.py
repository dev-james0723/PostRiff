"""Goal, experiment and proof adapters over the existing workspace aggregate.

No model calls, publishing or identity learning. Commands use CoworkerService's
permission/revision/audit transaction. Provider measurements use insights;
experiments use performance's like-for-like +24h observations and features.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import statistics
from datetime import datetime, timedelta, timezone

from postriff_alpha.domain import AlphaError
from .. import insights
from . import performance, weekly_operator

WEEK = 7 * 86400
GOAL_METRICS = {
    "consistency": ("verified_posts",), "views_or_reach": ("views", "reach"),
    "engagement": ("likes", "comments", "replies", "shares", "saved"),
    "follower_growth": ("followers",), "leads": ("leads",),
    "newsletter_subscribers": ("subscribers",), "sales_or_conversions": ("conversions",),
    "authority": ("mentions",),
}
TRANSITIONS = {"candidate": ("proposed", "dismissed"), "proposed": ("accepted", "dismissed", "rejected", "expired"),
               "accepted": ("preparing", "cancelled"), "preparing": ("running", "cancelled"),
               "running": ("measuring", "cancelled", "invalidated"),
               "measuring": ("complete", "insufficient_data", "invalidated"),
               "complete": (), "insufficient_data": (), "invalidated": (), "expired": (),
               "dismissed": (), "rejected": (), "cancelled": ()}
LIMITATIONS = ["Observational evidence; causal=false.", "Other changes, audience mix and seasonality may explain the difference.",
               "Only verified posts in the same account, language, content type and metric definition are compared at +24h."]


def view(state):
    return (state.get("coworker") or {}).get("growthLoop") or {"goals": [], "experiments": [], "proofs": []}


def root(state):
    value = state.setdefault("coworker", {}).setdefault("growthLoop", {})
    for name in ("goals", "experiments", "proofs"):
        value.setdefault(name, [])
    return value


def active_goal(state):
    return next((g for g in view(state)["goals"] if g["status"] == "active"), None)


def verified_at(job):
    stamps = [e.get("at") for e in job.get("events") or [] if e.get("state") == "verified" and isinstance(e.get("at"), (int, float))]
    verification = job.get("verification") or {}
    return verification.get("at") if isinstance(verification, dict) and verification.get("at") else job.get("verifiedAt") or (min(stamps) if stamps else None)


def number(value, name, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise AlphaError(f"{name} must be a finite non-negative number.", 400)
    return value


def key(payload):
    value = payload.get("idempotencyKey")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value):
        raise AlphaError("An idempotency key of 8–80 letters, numbers, underscores or hyphens is required.", 400)
    return value


def stamp(value, name):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp() if len(value) == 10 else datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        raise AlphaError(f"Choose a valid {name} date.", 400) from None


def _id(prefix, workspace_id, request_key):
    return prefix + hashlib.sha256(f"{workspace_id}:{request_key}".encode()).hexdigest()[:20]


def create_goal(state, workspace_id, payload, actor, now):
    kind = payload.get("goalType")
    metric = payload.get("primaryMetric")
    if kind not in GOAL_METRICS or metric not in GOAL_METRICS[kind]:
        raise AlphaError("Choose a supported goal and its native metric.", 400)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise AlphaError("Give the goal a name of at most 120 characters.", 400)
    baseline = number(payload.get("baselineValue"), "Baseline", optional=True)
    target = number(payload.get("targetValue"), "Target")
    target_at = stamp(payload.get("targetAt"), "target")
    if target_at <= now or baseline is not None and target <= baseline:
        raise AlphaError("Choose a future target above the baseline.", 400)
    channel_id = payload.get("channelId")
    channels = (state.get("phase2") or {}).get("channels") or []
    channel = next((c for c in channels if c["id"] == channel_id and not c.get("revoked")), None)
    if channel_id and channel is None:
        raise AlphaError("Choose an account from this workspace.", 400)
    if metric != "verified_posts" and channel is None:
        raise AlphaError("Choose one account; different platforms' numbers are never added together.", 400)
    secondary = payload.get("secondaryIndicators") or []
    if not isinstance(secondary, list) or len(secondary) > 5 or any(s not in sum((list(v) for v in GOAL_METRICS.values()), []) for s in secondary):
        raise AlphaError("Choose at most five secondary indicators.", 400)
    goal_id = _id("gg_", workspace_id, key(payload))
    data = {"name": name.strip(), "goalType": kind, "primaryMetric": metric, "baselineValue": baseline, "targetValue": target,
            "targetAt": target_at, "channelId": channel_id or None, "platform": channel.get("platform") if channel else None,
            "secondaryIndicators": secondary}
    existing = next((g for g in view(state)["goals"] if g["id"] == goal_id), None)
    if existing:
        if any(existing[k] != v for k, v in data.items()):
            raise AlphaError("This request key already belongs to a different goal.", 409)
        return existing
    if active_goal(state):
        raise AlphaError("Pause or archive the current primary goal before creating another.", 409)
    goals = root(state)["goals"]
    if len(goals) >= 40:
        raise AlphaError("This workspace has reached its goal history limit.", 409)
    goal = {**data, "id": goal_id, "workspaceId": workspace_id, "baselineAt": now if baseline is not None else None,
            "baselineSource": "user_declared" if baseline is not None else "unavailable", "createdBy": actor,
            "createdAt": now, "updatedAt": now, "status": "active"}
    goals.append(goal)
    return goal


def goal_progress(goal, posts, state, now):
    result = copy.deepcopy(goal)
    metric = goal["primaryMetric"]
    jobs = [j for j in (state.get("phase2") or {}).get("jobs") or [] if j.get("state") == "verified" and j.get("providerReference")]
    def in_scope(job):
        return not goal.get("channelId") or (job.get("manifest") or {}).get("channelId") == goal["channelId"]
    jobs = [j for j in jobs if in_scope(j) and goal["createdAt"] <= (verified_at(j) or 0) <= now]
    if metric == "verified_posts":
        current, at, status, measured = len(jobs), now, "available", len(jobs)
        definition = "Verified published posts since this goal was created (failed or unverified jobs excluded)."
        reason = "Application verified publishing receipts; this is a post count, not an external audience metric."
        source = "verified_publish_receipts"
    else:
        provider = str(goal.get("platform") or "").lower()
        supported = metric in insights.INSIGHT_METRICS.get(provider, ())
        scoped = [p for p in posts if p.get("provider") == provider and p.get("connectionId") == goal.get("channelId") and p.get("jobId") in {j["id"] for j in jobs}]
        readings = [(p["metrics"].get(metric) or {}) for p in scoped]
        values = [r for r in readings if r.get("value") is not None and r.get("availability") == "available" and r.get("observedAt", 0) <= now]
        measured = len(values)
        current = sum(r["value"] for r in values) if values else None
        at = max((r["observedAt"] for r in values), default=None)
        status = "available" if supported and measured and measured == len(jobs) else "partial" if measured else "unavailable"
        definition = f"Sum of {provider} native {metric}, definition {insights.DEFINITION_VERSION}, latest readings of verified posts since goal creation; not unique people."
        reason = f"{measured} of {len(jobs)} verified posts have a {metric} reading." if supported else f"Rafii does not have provider coverage for account {metric}. No estimated value is substituted."
        source = provider if supported else None
    result.update({"currentValue": current, "currentValueAt": at, "coverage": {"status": status, "reason": reason, "measured": measured, "eligible": len(jobs)},
                   "providerMetricDefinition": definition, "confidence": "provider_reported" if source and metric != "verified_posts" else "verified" if source else "unavailable",
                   "source": source, "change": current - goal["baselineValue"] if current is not None and goal["baselineValue"] is not None else None,
                   "nextAction": {"label": "Review this week's plan", "href": "/app/weekly"} if status == "available" else {"label": "Check account metric coverage", "href": "/app/channels"}})
    # The current metric is an increment since activation, plus a user-declared starting baseline.
    if current is not None and goal["baselineValue"] is not None:
        result["currentValue"] = goal["baselineValue"] + current
        result["change"] = current
    if goal["status"] == "active" and status == "available" and result["currentValue"] is not None and result["currentValue"] >= goal["targetValue"]:
        result["displayStatus"] = "achieved"
    else:
        result["displayStatus"] = goal["status"]
    return result


def planning_context(state, slot, now=None):
    """Scoped data only; recipe goals/constraints always remain authoritative."""
    now = now or datetime.now(timezone.utc).timestamp()
    goal = active_goal(state)
    if goal and goal.get("channelId") and goal["channelId"] != slot.get("channelId"):
        goal = None
    preferences = []
    for experiment in view(state)["experiments"]:
        cohort = experiment["cohort"]
        if (experiment.get("decision") == "applied" and experiment["status"] == "complete" and experiment["expiresAt"] > now
                and cohort.get("connectionId") == slot.get("channelId") and cohort.get("provider") == str(slot.get("platform") or "").lower()
                and cohort.get("language") == slot.get("language") and cohort.get("contentTypeId") == slot.get("contentType")):
            preferences.append({"experimentId": experiment["id"], "dimension": experiment["dimension"], "preferredFactor": experiment["result"].get("supportedFactor"), "causal": False})
    context = {"goal": {k: goal.get(k) for k in ("id", "name", "goalType", "primaryMetric", "targetValue", "targetAt")} if goal else None,
               "approvedStrategyPreferences": preferences[:5], "constraints": "Recipe goals and user constraints win. Review and Queue approval remain required."}
    from .. import proof
    if proof.enabled():   # RAFII Product Growth R-PROOF-02: accepted next-week decisions planned onto this slot, still in effect
        from ..proof import strategy
        context["strategyDecisions"] = strategy.for_slot(state, slot, {p["experimentId"] for p in preferences})
    return context


def transition(experiment, target, actor, now):
    if target == experiment["status"]:
        return experiment
    if target not in TRANSITIONS.get(experiment["status"], ()):
        raise AlphaError("This experiment cannot make that transition.", 409)
    experiment["status"] = target
    experiment["updatedAt"] = now
    experiment["history"].append({"status": target, "at": now, "actor": actor})
    return experiment


def measure(experiment, rows, now):
    if now < experiment["endAt"]:
        raise AlphaError("Wait until the observation window ends; no early winner is claimed.", 409)
    def same_cohort(row):
        observed = row.get("cohort") or {}
        return (all(observed.get(key) == value for key, value in experiment["cohort"].items())
                and observed.get("account", observed.get("connectionId")) == observed.get("connectionId")
                and observed.get("window", insights.COMPARISON_BASIS) == insights.COMPARISON_BASIS)

    eligible = [r for r in rows if same_cohort(r) and r.get("metric") == experiment["metric"]
                and experiment["startedAt"] <= (r.get("publishedAt") or 0) < experiment["endAt"]
                and r.get("jobId") not in experiment["sourcePostIds"] and r.get("observedAt", now + 1) <= now]
    # Avoid duplicate receipts and explicitly retain asymmetric/missing samples.
    eligible = list({r["jobId"]: r for r in eligible}.values())
    a = [r for r in eligible if r["features"].get(experiment["dimension"]) == experiment["variantFactor"] and r["value"] is not None]
    b = [r for r in eligible if r["features"].get(experiment["dimension"]) == experiment["controlFactor"] and r["value"] is not None]
    result = {"samples": {"variant": len(a), "control": len(b)}, "minimumPerArm": experiment["minimumPerArm"], "causal": False,
              "missing": len([r for r in eligible if r["value"] is None]), "statistic": "median", "limitations": list(LIMITATIONS),
              "evidenceIds": [], "counterEvidenceIds": [], "supportedFactor": None,
              "observations": [{"jobId": r["jobId"], "value": r["value"], "observedAt": r["observedAt"], "factor": r["features"].get(experiment["dimension"])} for r in eligible]}
    if len(a) < experiment["minimumPerArm"] or len(b) < experiment["minimumPerArm"]:
        return "insufficient_data", {**result, "interpretation": "Insufficient comparable measured posts; no planning preference can be applied."}
    ma, mb = statistics.median(r["value"] for r in a), statistics.median(r["value"] for r in b)
    effect = (ma - mb) / max(ma, mb) if max(ma, mb) > 0 else 0
    if abs(effect) >= performance.MIN_RELATIVE and result["missing"] == 0:
        result["supportedFactor"] = experiment["variantFactor"] if effect > 0 else experiment["controlFactor"]
    stronger, weaker = (a, b) if ma > mb else (b, a)
    threshold = statistics.median(r["value"] for r in weaker)
    result.update({"medianVariant": ma, "medianControl": mb, "relativeDifference": effect,
                   "evidenceIds": [r["jobId"] for r in stronger if r["value"] > threshold],
                   "counterEvidenceIds": [r["jobId"] for r in stronger if r["value"] <= threshold],
                   "interpretation": "Comparable medians differ; this is evidence for this account, not proof of a cause." if result["supportedFactor"] else "Inconclusive or asymmetric data. Keep this as a hypothesis."})
    return "complete", result


def period(now, frequency):
    today = datetime.fromtimestamp(now, timezone.utc)
    if frequency == "weekly":
        end = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=7)
    else:
        end = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = (end - timedelta(days=1)).replace(day=1)
    return start.timestamp(), end.timestamp()


def proof_counts(state, start, end):
    """Completed/accepted outcomes, not unused drafts or optimistic slot labels."""
    phase = state.get("phase2") or {}
    jobs = phase.get("jobs") or []
    published = [j for j in jobs if j.get("state") == "verified" and j.get("providerReference") and start <= (verified_at(j) or 0) < end]
    reviews = [r for r in phase.get("reviews") or [] if r.get("state") == "approved" and start <= (r.get("approvedAt") or r.get("createdAt") or 0) < end]
    weeks = weekly_operator.view(state)["weeks"]
    prepared = {s["variantId"] for w in weeks for s in w.get("slots") or [] if s.get("variantId") and s.get("status") not in ("rejected", "failed") and s.get("acceptedAt") and start <= s["acceptedAt"] < end}
    approved = {r.get("variantId") for r in reviews if r.get("variantId")}
    approved |= {j.get("variantId") or (j.get("manifest") or {}).get("variantId") for j in jobs if j.get("approvedAt") and start <= j["approvedAt"] < end and j.get("state") not in ("failed", "cancelled")}
    approved.discard(None)
    planning = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    campaigns = [c for c in planning.get("campaigns") or [] if start <= c.get("createdAt", 0) < end]
    experiments = [e for e in view(state)["experiments"] if start <= e.get("updatedAt", 0) < end and e["status"] == "complete"]
    next_prepared = {s["variantId"] for w in weeks
                     if datetime.fromtimestamp(end, timezone.utc).date().isoformat() <= w.get("weekOf", "") < datetime.fromtimestamp(end + WEEK, timezone.utc).date().isoformat()
                     for s in w.get("slots") or [] if s.get("variantId") and s.get("acceptedAt") and s.get("status") not in ("rejected", "failed")}
    return {"preparedPosts": len(prepared | approved), "approvedPosts": len(approved), "verifiedPublishedPosts": len(published), "campaigns": len(campaigns),
            "completedExperiments": len(experiments), "runningExperiments": sum(e["status"] in ("running", "measuring") for e in view(state)["experiments"]),
            "nextWeekPrepared": len(next_prepared), "evidence": {"jobIds": [j["id"] for j in published], "variantIds": sorted(prepared | approved),
                                                                  "campaignIds": [c["id"] for c in campaigns], "experimentIds": [e["id"] for e in experiments]}}


class GrowthLoop:
    """Thin service adapter: all writes go through the existing coworker command."""
    def __init__(self, coworker):
        self.service = coworker

    def _posts(self, cur, workspace_id, state, now):
        # Provider/storage read failures cannot masquerade as an audience zero.
        cur.execute("SAVEPOINT growth_metric_read")
        try:
            posts = insights.summary(cur, workspace_id, (state.get("phase2") or {}).get("jobs") or [], now)["posts"]
            cur.execute("RELEASE SAVEPOINT growth_metric_read")
            return posts
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT growth_metric_read")
            return []

    def _event(self, cur, workspace_id, principal, event, record_id):
        from .service import _event
        _event(cur, workspace_id, principal, event, {"recordId": record_id}, f"{event}:{record_id}:{principal}")

    def _save(self, workspace_id, token, mutate, event, record_id):
        def after(cur, state, principal):
            actual_event = event
            if event == "growth_experiment.completed":
                experiment = next(e for e in view(state)["experiments"] if e["id"] == record_id)
                if experiment["status"] != "complete":
                    actual_event = "growth_experiment.measured"
            self._event(cur, workspace_id, principal, actual_event, record_id)
        item, _ = self.service._command(workspace_id, token, mutate, "owner", event, record_id, after=after)
        saved = self.service._state(workspace_id, token)
        stored = next((r for name in ("goals", "experiments", "proofs") for r in view(saved)[name] if r["id"] == item["id"]), None)
        return {"record": stored, "verified": stored == item}

    def summary(self, workspace_id, token):
        now = self.service.clock()
        with self.service.repository.transaction(token, workspace_id) as (cur, row, _principal):
            state = self.service.hosted.ideas._state(row)
            posts = self._posts(cur, workspace_id, state, now)
            goals = [goal_progress(g, posts, state, now) for g in view(state)["goals"]]
            weekly = weekly_operator.view(state)
            return {"goal": next((g for g in goals if g["status"] == "active"), goals[-1] if goals else None), "goals": goals,
                    "experiments": view(state)["experiments"], "proofs": view(state)["proofs"],
                    "weekly": {"activeRecipes": sum(r.get("status") == "active" for r in weekly["recipes"]),
                               "nextAction": "Review the weekly plan" if weekly["weeks"] else "Set up Weekly Operator", "href": "/app/weekly"},
                    "metricOptions": GOAL_METRICS}

    def create_goal(self, workspace_id, token, payload):
        record_id = _id("gg_", workspace_id, key(payload))
        return self._save(workspace_id, token, lambda s, p: create_goal(s, workspace_id, payload, p, self.service.clock()), "growth_goal.created", record_id)

    def goal_status(self, workspace_id, token, record_id, payload):
        status = payload.get("status")
        if status not in ("active", "paused", "achieved", "archived"):
            raise AlphaError("Choose active, paused, achieved or archived.", 400)
        def change(state, actor):
            goal = next((g for g in view(state)["goals"] if g["id"] == record_id), None)
            if goal is None:
                raise AlphaError("Goal not found in this workspace.", 404)
            if status == "active" and any(g["id"] != record_id and g["status"] == "active" for g in view(state)["goals"]):
                raise AlphaError("Only one primary goal can be active.", 409)
            goal.update({"status": status, "updatedAt": self.service.clock(), "decidedBy": actor})
            return goal
        return self._save(workspace_id, token, change, "growth_goal.status_changed", record_id)

    def propose(self, workspace_id, token, payload):
        request_key = key(payload)
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            from ..permissions import require
            require(self.service.hosted.ideas._member(row), "owner")
            cur.execute("""SELECT revision,cohort,metric,dimension,arm_a,arm_b,statement,extract(epoch from expires_at),evidence_ids,counter_evidence_ids
                           FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND id::text=%s AND causal=false AND status IN ('candidate','experiment','supported')""", (workspace_id, str(payload.get("hypothesisId") or "")))
            h = cur.fetchone()
            if h is None:
                raise AlphaError("An eligible hypothesis is required in this workspace.", 404)
        now = self.service.clock()
        if float(h[7]) <= now:
            raise AlphaError("This hypothesis has expired. Collect fresh evidence first.", 409)
        cohort = h[1]
        if not cohort.get("connectionId") or not cohort.get("language") or not cohort.get("contentTypeId"):
            raise AlphaError("This hypothesis lacks account, language or content-type coverage. Refresh performance evidence before testing it.", 409)
        minimum = payload.get("minimumPerArm", performance.MIN_ARM)
        days = payload.get("windowDays", 14)
        if type(minimum) is not int or not performance.MIN_ARM <= minimum <= 100 or type(days) is not int or not 7 <= days <= 60:
            raise AlphaError("Use 5–100 posts per arm and a 7–60 day observation window.", 400)
        record_id = _id("ge_", workspace_id, request_key)
        def change(state, actor):
            existing = next((e for e in view(state)["experiments"] if e["id"] == record_id), None)
            if existing:
                if existing["hypothesisId"] != payload["hypothesisId"] or existing["minimumPerArm"] != minimum or existing["windowDays"] != days:
                    raise AlphaError("This request key belongs to another experiment design.", 409)
                return existing
            if len(root(state)["experiments"]) >= 80:
                raise AlphaError("This workspace has reached its experiment history limit.", 409)
            item = {"id": record_id, "workspaceId": workspace_id, "hypothesisId": payload["hypothesisId"], "hypothesisRevision": h[0],
                    "cohort": cohort, "metric": h[2], "dimension": h[3], "variantFactor": h[4], "controlFactor": h[5], "statement": h[6],
                    "minimumPerArm": minimum, "windowDays": days, "createdAt": now, "updatedAt": now, "expiresAt": float(h[7]),
                    "status": "candidate", "decision": None, "owner": actor, "sourcePostIds": list(set((h[8] or []) + (h[9] or []))),
                    "generatedVariantIds": [], "publishingJobIds": [], "result": None, "causal": False, "limitations": list(LIMITATIONS),
                    "history": [{"status": "candidate", "at": now, "actor": actor}]}
            transition(item, "proposed", actor, now)
            root(state)["experiments"].append(item)
            return item
        return self._save(workspace_id, token, change, "growth_experiment.proposed", record_id)

    def experiment_action(self, workspace_id, token, record_id, payload):
        action = payload.get("action")
        now = self.service.clock()
        rows = None
        if action == "measure":
            with self.service.repository.transaction(token, workspace_id) as (cur, row, _p):
                rows = performance.observations(cur, workspace_id, self.service.hosted.ideas._state(row), now)
                # A legacy reading of unknown age cannot support a prospective result.
                jobs = {j["id"]: j for j in (self.service.hosted.ideas._state(row).get("phase2") or {}).get("jobs") or []}
                for observation in rows:
                    observation["publishedAt"] = verified_at(jobs.get(observation["jobId"], {}))
                    if observation.get("readOffset") != insights.COMPARISON_BASIS:
                        observation["value"] = None
        targets = {"accept": "accepted", "prepare": "preparing", "start": "running", "dismiss": "dismissed", "reject": "rejected", "cancel": "cancelled", "invalidate": "invalidated", "expire": "expired"}
        def change(state, actor):
            experiment = next((e for e in view(state)["experiments"] if e["id"] == record_id), None)
            if experiment is None:
                raise AlphaError("Experiment not found in this workspace.", 404)
            if action == "measure":
                if experiment["status"] in ("complete", "insufficient_data"):
                    return experiment
                if experiment["status"] not in ("running", "measuring"):
                    raise AlphaError("Start the approved experiment before measuring.", 409)
                status, result = measure(experiment, rows, now)
                transition(experiment, "measuring", actor, now)
                experiment["result"] = result
                experiment["publishingJobIds"] = [r["jobId"] for r in result["observations"]]
                transition(experiment, status, actor, now)
            elif action in ("apply", "keep", "reject_result", "revoke"):
                if experiment["status"] != "complete":
                    raise AlphaError("Only completed measurements support a result decision.", 409)
                if action == "apply" and (not experiment["result"].get("supportedFactor") or experiment["expiresAt"] <= now):
                    raise AlphaError("An inconclusive or expired result cannot become a planning preference.", 409)
                experiment.update({"decision": {"apply": "applied", "keep": "hypothesis_only", "reject_result": "rejected", "revoke": "revoked"}[action], "decidedBy": actor, "decidedAt": now})
            elif action == "not_now":
                if experiment["status"] != "proposed":
                    raise AlphaError("Only a proposed experiment can be deferred.", 409)
                experiment["deferredUntil"] = now + WEEK
            elif action in targets:
                if action == "start" and experiment["status"] != "running":
                    if experiment["expiresAt"] <= now:
                        raise AlphaError("This experiment design has expired.", 409)
                    experiment["startedAt"] = now
                    experiment["endAt"] = now + experiment["windowDays"] * 86400
                transition(experiment, targets[action], actor, now)
            else:
                raise AlphaError("Choose a supported experiment action.", 400)
            experiment["updatedAt"] = now
            return experiment
        event = "growth_experiment." + {"start": "started", "measure": "completed", "apply": "applied", "dismiss": "dismissed"}.get(action, str(action))
        return self._save(workspace_id, token, change, event, record_id)

    def generate_proof(self, workspace_id, token, frequency="weekly"):
        if frequency not in ("weekly", "monthly"):
            raise AlphaError("Choose a weekly or monthly recap.", 400)
        now = self.service.clock()
        start, end = period(now, frequency)
        record_id = _id("gp_", workspace_id, f"{frequency}:{int(start)}")
        with self.service.repository.transaction(token, workspace_id) as (cur, row, _p):
            state = self.service.hosted.ideas._state(row)
            existing = next((p for p in view(state)["proofs"] if p["id"] == record_id), None)
            if existing:
                return {"record": existing, "verified": True}
            counts = proof_counts(state, start, end)
            cur.execute("SAVEPOINT growth_proof_time_back")
            try:
                cur.execute("SELECT confidence,count(*),coalesce(sum(saved_seconds),0) FROM public.pr_time_savings_ledger WHERE workspace_id=%s AND occurred_at>=to_timestamp(%s) AND occurred_at<to_timestamp(%s) GROUP BY confidence", (workspace_id, start, end))
                time_back = {"coverage": "available", "byConfidence": [{"confidence": level, "outcomes": n, "savedSeconds": int(seconds)} for level, n, seconds in cur.fetchall()], "scope": "workspace"}
                cur.execute("RELEASE SAVEPOINT growth_proof_time_back")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT growth_proof_time_back")
                time_back = {"coverage": "unavailable", "byConfidence": [], "reason": "Time Back data could not be read."}
            cur.execute("SELECT count(DISTINCT thread_id) FROM public.pr_reply_drafts WHERE workspace_id=%s AND status='verified' AND updated_at>=to_timestamp(%s) AND updated_at<to_timestamp(%s)", (workspace_id, start, end))
            counts["engagementHandled"] = cur.fetchone()[0]
            # The existing listening "act" is only a decision/deep-link. Count it
            # as value only when lineage reaches an accepted artifact or campaign.
            accepted_ids = set(counts["evidence"]["variantIds"])
            campaign_ids = {c["id"] for c in (((state.get("raffi") or {}).get("campaignPlanning") or {}).get("campaigns") or [])}
            counts["opportunitiesActedOn"] = sum(o.get("status") == "acted" and start <= o.get("decidedAt", 0) < end
                                                  and (o.get("variantId") in accepted_ids or o.get("campaignId") in campaign_ids)
                                                  for o in ((state.get("coworker") or {}).get("listening") or {}).get("opportunities") or [])
            posts = self._posts(cur, workspace_id, state, now)
            goal = active_goal(state)
            goal_snapshot = goal_progress(goal, [p for p in posts if p["freshness"]["observedAt"] < end], state, end) if goal and goal["createdAt"] < end else None
            learning = {"coverage": "insufficient_history", "approvalRate": None, "medianEditDistance": None, "priorApprovalRate": None,
                        "priorMedianEditDistance": None, "acceptedPreferenceLearnings": 0, "definition": "Approved / (approved + rejected) decisions; median edit distance of approved drafts in each completed period."}
            if frequency == "monthly":
                prior_start, _ = period(start, "monthly")
                cur.execute("SELECT kind,features->>'editDistance',extract(epoch from created_at) FROM public.pr_learning_events WHERE workspace_id=%s AND kind IN ('draft.approved','draft.rejected') AND created_at>=to_timestamp(%s) AND created_at<to_timestamp(%s)", (workspace_id, prior_start, end))
                decisions = cur.fetchall()
                current = [r for r in decisions if float(r[2]) >= start]
                previous = [r for r in decisions if float(r[2]) < start]
                def measured(rows):
                    approved = [r for r in rows if r[0] == "draft.approved"]
                    distances = [float(r[1]) for r in approved if r[1] is not None and math.isfinite(float(r[1]))]
                    return len(approved) / len(rows) if len(rows) >= 3 else None, statistics.median(distances) if len(distances) >= 3 else None
                rate, edits = measured(current)
                prior_rate, prior_edits = measured(previous)
                cur.execute("SELECT count(*) FROM public.pr_memory_proposals WHERE workspace_id=%s AND status IN ('remembered','edited') AND decided_at>=to_timestamp(%s) AND decided_at<to_timestamp(%s)", (workspace_id, start, end))
                learning.update({"approvalRate": rate, "medianEditDistance": edits, "priorApprovalRate": prior_rate, "priorMedianEditDistance": prior_edits,
                                 "acceptedPreferenceLearnings": cur.fetchone()[0], "sampleSizes": {"current": len(current), "prior": len(previous)},
                                 "coverage": "sufficient" if all(v is not None for v in (rate, edits, prior_rate, prior_edits)) else "insufficient_history"})
        item = {"id": record_id, "workspaceId": workspace_id, "frequency": frequency, "periodStart": start, "periodEnd": end, "generatedAt": now,
                "counts": counts, "timeBack": time_back, "goal": goal_snapshot, "href": f"/app/analytics?proof={record_id}",
                "historyCoverage": "sufficient" if frequency == "weekly" else learning["coverage"], "learningSummary": learning,
                "limitations": ["Prepared means accepted into the weekly plan or approved. Unused drafts and failed publishes are excluded.", "Performance trends require comparable covered periods; no modeled trend is shown."]}
        def change(state, actor):
            proofs = root(state)["proofs"]
            existing = next((p for p in proofs if p["id"] == record_id), None)
            if existing:
                return existing
            if len(proofs) >= 64:
                proofs.pop(0)
            proofs.append(item)
            return item
        return self._save(workspace_id, token, change, f"{frequency}_proof.generated", record_id)

    def cron(self, max_workspaces=10, deadline=None):
        """Existing owner capability and notification preferences; no new send mechanism."""
        import time
        from ..automation_runs import principal_repository
        if not getattr(self.service.hosted, "notifications", None) or not self.service.hosted.notifications.enabled():
            return {"status": "disabled"}
        with self.service.hosted.connection_factory() as db, db.cursor() as cur:
            _start, due_end = period(self.service.clock(), "weekly")
            cur.execute("""SELECT DISTINCT ON (w.id) w.id::text,m.user_id::text FROM public.pr_workspaces w
                           JOIN public.pr_memberships m ON m.workspace_id=w.id AND m.role='owner' AND m.status='active'
                           WHERE NOT w.state ? 'accountDeletion' AND w.state->'coworker'->'growthLoop' IS NOT NULL
                           AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(w.state->'coworker'->'growthLoop'->'proofs','[]'::jsonb)) p
                                           WHERE p->>'frequency'='weekly' AND (p->>'periodEnd')::numeric=%s)
                           ORDER BY w.id,m.user_id LIMIT %s""", (due_end, max_workspaces))
            workspaces = list(dict(cur.fetchall()).items())
        generated, failed = 0, 0
        for workspace_id, actor in workspaces:
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                repository, capability = principal_repository(self.service.hosted, workspace_id, actor, "owner")
                service = copy.copy(self.service)
                service.hosted = copy.copy(self.service.hosted)
                service.hosted.repository = repository
                loop = GrowthLoop(service)
                state = service._state(workspace_id, capability)
                activations = [g["createdAt"] for name in ("goals", "experiments") for g in view(state)[name]]
                if not activations or min(activations) >= due_end:
                    continue  # don't send empty recaps about periods before activation
                loop.generate_proof(workspace_id, capability)
                if min(activations) < period(self.service.clock(), "monthly")[1]:
                    loop.generate_proof(workspace_id, capability, "monthly")
                generated += 1
            except Exception:
                failed += 1
        return {"workspaces": generated, "failed": failed}

    def proof_action(self, workspace_id, token, record_id, action):
        if action not in ("opened", "acted"):
            raise AlphaError("Choose opened or acted.", 400)
        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            state = self.service.hosted.ideas._state(row)
            proof = next((p for p in view(state)["proofs"] if p["id"] == record_id), None)
            if proof is None:
                raise AlphaError("Recap not found in this workspace.", 404)
            event = f"{proof['frequency']}_proof.{action}"
            self._event(cur, workspace_id, principal, event, record_id)
            cur.execute("SELECT 1 FROM public.pr_product_events WHERE workspace_id=%s AND user_id=%s AND event=%s AND dedupe_key=%s", (workspace_id, principal, event, f"{event}:{record_id}:{principal}"))
            return {"verified": cur.fetchone() is not None, "href": "/app/weekly" if action == "acted" else proof["href"]}
