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
        "trial_to_paid": {"subscriptionStatus": sub[0] if sub else "none", "note": "Current status only, not a payment. Cash-paid conversion is fleet-level: legacy_trial_to_paid (metric_definitions v1)."},
        "paid_retention_30d": {"note": "Fleet-level cash_paid_retention_d30 from payment history (metric_definitions v1)."},
        "paid_retention_60d": {"note": "Fleet-level cash_paid_retention_d60 from payment history (metric_definitions v1)."},
        "paid_retention_90d": {"note": "Fleet-level cash_paid_retention_d90 from payment history (metric_definitions v1)."},
        "accepted_low_edit_per_active_workspace": {"value": low_edit, "definition": "approved drafts in 90 days with edit distance ≤ 0.15"},
    }
    return {"workspaceId": workspace_id, "metrics": out, "definitions": list(METRICS), "note": "Evidence for the product hypothesis, not a guarantee. Raw generation volume is deliberately not a metric.",
            "withPreferences": with_prefs}


def _payment_evidence(cur):
    """Cash payment evidence per workspace, never a status: the Founder P1 invoice history when that table exists, else the
    credit-plan invoice grants (legacy-plan invoices are not recorded there, so coverage is partial). Refunds and disputes
    are keyed by payment intent."""
    cur.execute("SELECT to_regclass('public.pr_invoices') IS NOT NULL, to_regclass('public.pr_credit_subscription_grants') IS NOT NULL, "
                "to_regclass('public.pr_credit_refunds') IS NOT NULL, to_regclass('public.pr_credit_disputes') IS NOT NULL")
    invoices, grants, refunds_table, disputes_table = cur.fetchone()
    if invoices:
        source = "pr_invoices"
        cur.execute("SELECT workspace_id::text,invoice_id,provider,status,livemode,amount_paid,subscription_id,billing_reason,extract(epoch from event_at),"
                    "payment_intent_id,extract(epoch from period_start),extract(epoch from period_end) FROM public.pr_invoices WHERE workspace_id IS NOT NULL")
    elif grants:
        source = "pr_credit_subscription_grants"
        cur.execute("SELECT workspace_id::text,invoice_id,'stripe','paid',livemode,amount_cents,subscription_id,billing_reason,extract(epoch from recorded_at),"
                    "payment_intent_id,period_start,period_end FROM public.pr_credit_subscription_grants")
    else:
        return None, {}, {}
    by_workspace, by_intent = {}, {}
    for wid, invoice, provider, status, live, amount, sub, reason, at, intent, start, end in cur.fetchall():
        payment = {"workspaceId": wid, "invoiceId": invoice, "provider": provider, "status": status, "livemode": bool(live),
                   "amountPaid": int(amount) if amount is not None else None, "subscriptionId": sub, "billingReason": reason,
                   "paidAt": float(at) if at is not None else None, "paymentIntentId": intent,
                   "periodStart": float(start) if start is not None else None, "periodEnd": float(end) if end is not None else None}
        by_workspace.setdefault(wid, {"payments": [], "refunds": [], "disputes": []})["payments"].append(payment)
        if intent:
            by_intent[intent] = wid
    if refunds_table:
        cur.execute("SELECT payment_intent_id,amount_cents,status FROM public.pr_credit_refunds")
        for intent, amount, status in cur.fetchall():
            if intent in by_intent:
                by_workspace[by_intent[intent]]["refunds"].append({"paymentIntentId": intent, "amount": int(amount), "status": status})
    if disputes_table:
        cur.execute("SELECT payment_intent_id,status,withdrawn FROM public.pr_credit_disputes")
        for intent, status, withdrawn in cur.fetchall():
            if intent in by_intent:
                by_workspace[by_intent[intent]]["disputes"].append({"paymentIntentId": intent, "status": status, "withdrawn": bool(withdrawn)})
    return source, by_workspace, by_intent


def _mark_partial(value, reason):
    """Incomplete evidence coverage is added to whatever else limits a row; no reason replaces another."""
    if not reason or value["dataState"] == "unavailable":
        return
    value["dataState"] = "partial"
    value["reason"] = ",".join(r for r in (value.get("reason"), reason) if r)


def fleet(cur):
    """Fleet-level cohort metrics for the operator growth report (no per-person data leaves the function).

    Conversion and retention are cash-paid facts from payment history under the shared, versioned definitions in
    `metric_definitions` (PRD R-MET-02). The old status-based numbers are kept only as an operating view under their own
    name: a non-trial status is not a payment, and today's status says nothing about day 30/60/90."""
    from .. import metric_definitions as md
    cur.execute("SELECT extract(epoch from now())")
    now = float(cur.fetchone()[0])
    watermark = now - md.SOURCE_LATENESS
    cur.execute("""SELECT count(*) FILTER (WHERE status='active'), count(*) FILTER (WHERE status IN ('cancelled','expired')), count(*) FILTER (WHERE status='trial'),
                          count(*) FILTER (WHERE status='past_due'), count(*) FILTER (WHERE status='grace'), count(*) FROM public.pr_subscriptions WHERE provider<>'fixture'""")
    active, churned, trial, past_due, grace, total = cur.fetchone()
    cur.execute("""WITH weeks AS (SELECT DISTINCT user_id, date_trunc('week', occurred_at) AS w FROM public.pr_product_events WHERE user_id IS NOT NULL AND occurred_at > now() - interval '120 days')
                   SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM weeks b WHERE b.user_id=a.user_id AND b.w=a.w + interval '1 week')), count(*) FROM weeks a
                   WHERE a.w < date_trunc('week', now())""")
    returned, base = cur.fetchone()
    source, evidence, _ = _payment_evidence(cur)
    cur.execute("SELECT count(*) FROM public.pr_subscriptions s JOIN public.pr_plan_terms p ON p.id=s.plan_terms_id "
                "WHERE s.provider<>'fixture' AND s.status IN ('active','past_due','grace','cancelled','expired') AND coalesce(p.entitlements->>'creditPolicy','')=''")
    legacy_paid_rows = cur.fetchone()[0]
    partial_reason = None if source == "pr_invoices" else ("legacy_plan_invoices_not_recorded" if legacy_paid_rows else "credit_plan_grants_only")
    # Legacy trial cohorts by positioning arm (subject = workspace): window from the trial start to 30 days after it ended.
    cur.execute("""SELECT coalesce(a.variant, 'unassigned'), t.workspace_id::text, extract(epoch from t.expires_at)
                   FROM public.pr_trials t LEFT JOIN public.pr_experiment_assignments a ON a.experiment = 'positioning_2026_10' AND a.subject_key = t.workspace_id::text
                   WHERE t.workspace_id IS NOT NULL""")
    arms = {}
    for variant, wid, expires in cur.fetchall():
        entry = {**evidence.get(wid, {"payments": [], "refunds": [], "disputes": []}), "startedAt": float(expires) - 14 * md.DAY, "windowEnd": float(expires) + 30 * md.DAY}
        arms.setdefault(variant, {})[wid] = entry
    by_arm = {}
    for variant, cohort in sorted(arms.items()):
        rows = {"legacy_trial_to_paid": md.window_conversion("legacy_trial_to_paid", cohort, now=now, watermark=watermark)}
        for n in md.RETENTION_DAYS:
            rows[f"cash_paid_retention_d{n}"] = md.retention(cohort, now=now, watermark=watermark, days=n)
            rows[f"cash_paid_retention_d{n}_refund_adjusted"] = md.retention(cohort, now=now, watermark=watermark, days=n, refund_adjusted=True)
        for value in rows.values():
            value["dimensions"] = {"positioningArm": variant}
            _mark_partial(value, partial_reason)
        by_arm[variant] = rows
    # v2 Free cohort (Free bootstrap never creates a trial): the Founder-owned source_paid_conversion definition, 30 days.
    cur.execute("SELECT w.id::text, extract(epoch from w.created_at) FROM public.pr_workspaces w WHERE NOT EXISTS (SELECT 1 FROM public.pr_trials t WHERE t.workspace_id=w.id) "
                "AND EXISTS (SELECT 1 FROM public.pr_entitlements e WHERE e.workspace_id=w.id) AND NOT w.state ? 'accountDeletion'")
    free = {wid: {**evidence.get(wid, {"payments": []}), "startedAt": float(created)} for wid, created in cur.fetchall()}
    free_row = md.window_conversion("source_paid_conversion", free, now=now, watermark=watermark)
    free_row["dimensions"] = {"cohort": "v2_free_bootstrap"}
    _mark_partial(free_row, partial_reason)
    cur.execute("SELECT variant, count(*), count(exposed_at) FROM public.pr_experiment_assignments WHERE experiment='positioning_2026_10' GROUP BY variant")
    exposure = {v: {"assigned": n, "exposed": e} for v, n, e in cur.fetchall()}
    status_row = md.row("subscriptions_by_current_status", total, data_state="available", known=total, sample_count=total,
                        measures={"active": active, "pastDue": past_due, "grace": grace, "trial": trial, "cancelledOrExpired": churned})
    return {"subscriptions": {"active": active, "churned": churned, "trial": trial, "pastDue": past_due, "grace": grace, "total": total,
                              "label": "Subscriptions by current status (operating view; not conversion, retention or cash)"},
            "subscriptionsByCurrentStatus": status_row,
            "weekly_return_rate": {**_rate(returned, base), "label": "Weekly active return: people with any product event in week N who return in week N+1. "
                                                                       "Not completed work; see next_week_completion_rate."},
            "positioning_2026_10": {"byArm": by_arm, "exposure": exposure,
                                    "definition": "legacy_trial_to_paid and cash_paid_retention_d30/60/90 (and refund-adjusted) from payment history "
                                                  "(metric_definitions v1, proposed_definition_not_activated); no status is treated as payment."},
            "sourcePaidConversion": free_row,
            "paymentEvidence": {"source": source, "coverage": partial_reason or "complete", "sourceWatermark": watermark,
                                "note": "Workspace classifications (internal/test/demo) are applied in Founder Control; this operator report excludes only fixture providers and test-mode payments."},
            "definitions": json.loads(json.dumps(list(METRICS))),
            "metricDefinitions": {k: {"status": v["status"], "unit": v["unit"], "definitionVersion": md.DEFINITION_VERSION} for k, v in md.DEFINITIONS.items()}}
