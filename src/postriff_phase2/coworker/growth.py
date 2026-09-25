"""Growth instrumentation (adaptive coworker spec §23; architecture lock G1).

These features are a hypothesis about subscription value, not a guarantee. The metrics below are computed from
existing authoritative tables plus `pr_product_events` (ids and counts only, never text) so the hypothesis can be
tested. Experiments assign deterministically (hash bucketing) and log exposure; no variant is hard-coded to win.
"""
from __future__ import annotations

import hashlib
import json
import statistics

EXPERIMENTS = {
    # Positioning A/B (spec §23). Both arms are real copy; which one converts better is what the data decides.
    "positioning_2026_10": {"variants": ("manager_generate", "coworker_prepares"), "weights": (50, 50),
                            "copy": {"manager_generate": "AI social media manager. Generate better posts.",
                                     "coworker_prepares": "Rafii is your AI social coworker. It prepares next week. You review what matters."}},
    "weekly_default_on": {"variants": ("off", "suggested"), "weights": (50, 50), "copy": {}},
}
METRICS = ("time_to_first_approved_post", "weekly_operator_enabled", "weekly_plan_reviewed", "draft_approval_rate", "median_edit_distance",
           "prepared_to_published_rate", "research_to_campaign_rate", "notification_open_rate", "notification_click_rate", "notification_to_action_rate",
           "notification_mute_rate", "notification_unsubscribe_rate", "weekly_return_rate", "automation_retention", "trial_to_paid",
           "paid_retention_30d", "paid_retention_60d", "paid_retention_90d", "accepted_low_edit_per_active_workspace")


def assign(cur, experiment, subject_key, expose=False):
    spec = EXPERIMENTS.get(experiment)
    if spec is None:
        return {"experiment": experiment, "variant": None, "enabled": False}
    cur.execute("SELECT variant FROM public.pr_experiment_assignments WHERE experiment=%s AND subject_key=%s", (experiment, subject_key))
    row = cur.fetchone()
    if row:
        variant = row[0]
    else:
        bucket = int(hashlib.sha256(f"{experiment}:{subject_key}".encode()).hexdigest()[:8], 16) % sum(spec["weights"])
        cumulative, variant = 0, spec["variants"][-1]
        for name, weight in zip(spec["variants"], spec["weights"]):
            cumulative += weight
            if bucket < cumulative:
                variant = name
                break
        cur.execute("INSERT INTO public.pr_experiment_assignments(experiment,subject_key,variant) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (experiment, subject_key, variant))
    if expose:
        cur.execute("UPDATE public.pr_experiment_assignments SET exposed_at=coalesce(exposed_at, now()) WHERE experiment=%s AND subject_key=%s", (experiment, subject_key))
    return {"experiment": experiment, "variant": variant, "enabled": True, "copy": spec["copy"].get(variant)}


def _rate(numerator, denominator):
    return {"value": round(numerator / denominator, 4) if denominator else None, "numerator": numerator, "denominator": denominator,
            "display": f"{numerator}/{denominator}" if denominator else "no data"}


def metrics(cur, workspace_id, state, now):
    """One workspace's metrics (the same definitions run fleet-wide from the analytics script)."""
    jobs = (state.get("phase2") or {}).get("jobs") or []
    reviews = (state.get("phase2") or {}).get("reviews") or []
    created = (state.get("workspace") or {}).get("createdAt")
    approved = sorted(j.get("approvedAt") for j in jobs if j.get("approvedAt"))
    first_approved = approved[0] - created if approved and isinstance(created, (int, float)) else None
    cur.execute("SELECT kind, (features->>'editDistance')::numeric FROM public.pr_learning_events WHERE workspace_id=%s AND kind IN ('draft.approved','draft.rejected') AND created_at > now() - interval '90 days'", (workspace_id,))
    decisions = cur.fetchall()
    approved_n = sum(1 for k, _ in decisions if k == "draft.approved")
    distances = [float(d) for k, d in decisions if k == "draft.approved" and d is not None]
    cur.execute("SELECT event, count(*) FROM public.pr_product_events WHERE workspace_id=%s AND occurred_at > now() - interval '90 days' GROUP BY event", (workspace_id,))
    events = dict(cur.fetchall())
    cur.execute("""SELECT count(*) FILTER (WHERE channel IN ('email','push') AND status IN ('sent','delivered','read','acted')),
                          count(*) FILTER (WHERE read_at IS NOT NULL), count(*) FILTER (WHERE acted_at IS NOT NULL)
                   FROM public.pr_notification_deliveries WHERE workspace_id=%s AND created_at > now() - interval '90 days'""", (workspace_id,))
    delivered, opened, acted = cur.fetchone()
    # Only this workspace's active members: preference rows scoped '*' belong to people, who may belong to other workspaces.
    cur.execute("""SELECT count(DISTINCT p.user_id) FILTER (WHERE p.email_unsubscribed), count(DISTINCT p.user_id) FILTER (WHERE p.muted_until > now()), count(DISTINCT p.user_id)
                   FROM public.pr_notification_preferences p JOIN public.pr_memberships m ON m.user_id=p.user_id AND m.workspace_id=%s AND m.status='active'
                   WHERE p.scope_key IN (%s,'*')""", (workspace_id, workspace_id))
    unsubscribed, muted, with_prefs = cur.fetchone()
    cur.execute("SELECT count(DISTINCT user_id) FROM public.pr_memberships WHERE workspace_id=%s AND status='active'", (workspace_id,))
    members = cur.fetchone()[0] or 1
    cur.execute("SELECT status FROM public.pr_subscriptions WHERE workspace_id=%s", (workspace_id,))
    sub = cur.fetchone()
    weekly = ((state.get("coworker") or {}).get("weekly") or {})
    verified = sum(1 for j in jobs if j.get("state") == "verified")
    prepared = len([r for r in reviews]) + len(jobs)
    low_edit = sum(1 for d in distances if d <= 0.15)
    out = {
        "time_to_first_approved_post": {"seconds": round(first_approved) if first_approved is not None else None},
        "weekly_operator_enabled": {"value": any(r.get("status") == "active" for r in weekly.get("recipes") or [])},
        "weekly_plan_reviewed": {"count": events.get("weekly_plan.reviewed", 0), "ready": events.get("weekly_plan.ready", 0)},
        "draft_approval_rate": _rate(approved_n, len(decisions)),
        "median_edit_distance": {"value": round(statistics.median(distances), 4) if distances else None, "n": len(distances)},
        "prepared_to_published_rate": _rate(verified, prepared),
        "research_to_campaign_rate": _rate(events.get("research.campaign_created", 0), events.get("research.search", 0)),
        "notification_open_rate": _rate(opened, delivered),
        "notification_click_rate": _rate(events.get("notification.clicked", 0), delivered),
        "notification_to_action_rate": _rate(acted, delivered),
        "notification_mute_rate": _rate(muted, members),
        "notification_unsubscribe_rate": _rate(unsubscribed, members),
        "weekly_return_rate": {"note": "fleet-level: active users in week N who return in week N+1 (growth.fleet, scripts/rafii_growth_report.py)"},
        "automation_retention": {"activeRecipes": sum(1 for r in weekly.get("recipes") or [] if r.get("status") == "active")},
        "trial_to_paid": {"subscription": sub[0] if sub else "none", "note": "fleet-level rate by positioning arm: growth.fleet"},
        "paid_retention_30d": {"note": "fleet-level cohort metric: growth.fleet"}, "paid_retention_60d": {"note": "fleet-level cohort metric: growth.fleet"},
        "paid_retention_90d": {"note": "fleet-level cohort metric: growth.fleet"},
        "accepted_low_edit_per_active_workspace": {"value": low_edit, "definition": "approved drafts in 90 days with edit distance ≤ 0.15"},
    }
    return {"workspaceId": workspace_id, "metrics": out, "definitions": list(METRICS), "note": "Evidence for the product hypothesis, not a guarantee. Raw generation volume is deliberately not a metric.",
            "withPreferences": with_prefs}


def fleet(cur):
    """Fleet-level cohort metrics for the growth report (operators only; no per-person data leaves the function)."""
    cur.execute("""SELECT count(*) FILTER (WHERE status='active'), count(*) FILTER (WHERE status IN ('cancelled','expired')), count(*) FILTER (WHERE status='trial'), count(*) FROM public.pr_subscriptions""")
    active, churned, trial, total = cur.fetchone()
    cur.execute("""WITH weeks AS (SELECT DISTINCT user_id, date_trunc('week', occurred_at) AS w FROM public.pr_product_events WHERE user_id IS NOT NULL AND occurred_at > now() - interval '120 days')
                   SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM weeks b WHERE b.user_id=a.user_id AND b.w=a.w + interval '1 week')), count(*) FROM weeks a
                   WHERE a.w < date_trunc('week', now())""")
    returned, base = cur.fetchone()
    # Trial → paid and paid retention, per positioning arm (subject = workspace). A trial counts once it has ended; it
    # converted when its workspace has a non-trial subscription. Retention at N days: of converted workspaces whose
    # trial ended at least N days ago, the share still paying (active, past_due or grace). pr_billing_events has no
    # workspace column, so the trial end is the cohort start; the definition is stated with the numbers.
    cur.execute("""SELECT coalesce(a.variant, 'unassigned'), t.expires_at, s.status
                   FROM public.pr_trials t LEFT JOIN public.pr_subscriptions s ON s.workspace_id = t.workspace_id
                   LEFT JOIN public.pr_experiment_assignments a ON a.experiment = 'positioning_2026_10' AND a.subject_key = t.workspace_id::text
                   WHERE t.workspace_id IS NOT NULL AND t.expires_at < now()""")
    arms = {}
    now_rows = cur.fetchall()
    cur.execute("SELECT extract(epoch from now())")
    now = float(cur.fetchone()[0])
    for variant, expires, status in now_rows:
        arm = arms.setdefault(variant, {"ended": 0, "converted": 0, **{f"d{n}": [0, 0] for n in (30, 60, 90)}})
        arm["ended"] += 1
        converted = status is not None and status != "trial"
        arm["converted"] += 1 if converted else 0
        for n in (30, 60, 90):
            if converted and now - expires.timestamp() >= n * 86400:
                arm[f"d{n}"][1] += 1
                arm[f"d{n}"][0] += 1 if status in ("active", "past_due", "grace") else 0
    by_arm = {variant: {"trial_to_paid": _rate(a["converted"], a["ended"]), **{f"paid_retention_{n}d": _rate(*a[f"d{n}"]) for n in (30, 60, 90)}}
              for variant, a in sorted(arms.items())}
    cur.execute("SELECT variant, count(*), count(exposed_at) FROM public.pr_experiment_assignments WHERE experiment='positioning_2026_10' GROUP BY variant")
    exposure = {v: {"assigned": n, "exposed": e} for v, n, e in cur.fetchall()}
    return {"subscriptions": {"active": active, "churned": churned, "trial": trial, "total": total}, "weekly_return_rate": _rate(returned, base),
            "positioning_2026_10": {"byArm": by_arm, "exposure": exposure,
                                    "definition": "trial end is the cohort start; paid = a non-trial subscription; retained = active, past_due or grace N days after the trial ended"},
            "definitions": json.loads(json.dumps(list(METRICS)))}
