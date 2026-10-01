"""Versioned product and payment metric definitions shared by Growth and Founder (PRD R-MET-01/02, AC31–AC35).

Every definition here is `proposed_definition_not_activated` until James accepts it; financial ones are never activated
by code. Rows use the Founder Control row shape so the same definition reads the same everywhere. The computations are
pure functions over evidence rows; data access lives with each consumer (operator report here, a Control slice there).

Units are customer workspaces, never people, events or posts. A checkpoint that is not fully observable is unavailable,
never zero; a cohort that is not mature is excluded from the denominator and reported. Status-based operating counts keep
their own name and are never presented as cash-paid facts.
"""
from __future__ import annotations

DEFINITION_VERSION = "v1"
PROPOSED = "proposed_definition_not_activated"
DAY = 86400
QUALIFYING_BILLING_REASONS = ("subscription_create", "subscription_cycle", "subscription_update")
RETENTION_DAYS = (30, 60, 90)
SOURCE_LATENESS = 3 * DAY       # a checkpoint is final only once the newest it could be corrected by has passed

DEFINITIONS = {
    # --- payment (financial: proposal only; activation belongs to James) ---------------------------------------------
    "first_cash_paid_conversion": {
        "kind": "financial", "unit": "workspace", "status": PROPOSED,
        "definition": "Earliest verified, live, positive payment of a recurring subscription invoice (subscription_create/cycle/update) "
                      "allocated to the workspace. Checkout redirects, an active status, zero-due or credit-covered invoices, trials, "
                      "credit top-ups, test-mode or fixture payments and manual status changes never qualify. A later refund or dispute "
                      "never moves this timestamp; it feeds the separately named refund-adjusted measures."},
    "source_paid_conversion": {
        "kind": "financial", "unit": "workspace", "status": PROPOSED, "owner": "founder",
        "definition": "Founder Control's cohort view (reused, not redefined here): eligible new v2 Free workspaces whose full first 30 "
                      "days are observable, converting with a first cash-paid subscription payment inside that window."},
    "legacy_trial_to_paid": {
        "kind": "financial", "unit": "workspace", "status": PROPOSED,
        "definition": "Legacy trial workspaces whose first cash-paid subscription payment falls between the trial start and 30 days "
                      "after the trial ended, among trials whose window is fully observable. Separate population from v2 Free."},
    **{f"cash_paid_retention_d{n}": {
        "kind": "financial", "unit": "workspace", "status": PROPOSED,
        "definition": f"Of workspaces whose first cash-paid payment is at least {n} days old (and whose checkpoint has passed the source "
                      f"watermark), the share with a paid service period covering day {n} after that payment, from historical invoice "
                      "periods — never today's status projected backwards. Free/trial access is not paid coverage; a cancellation with "
                      "an already-paid unexpired period still counts."} for n in RETENTION_DAYS},
    **{f"cash_paid_retention_d{n}_refund_adjusted": {
        "kind": "financial", "unit": "workspace", "status": PROPOSED,
        "definition": f"As cash_paid_retention_d{n}, but a period whose payment was fully refunded or lost in a dispute does not cover."}
       for n in RETENTION_DAYS},
    "subscriptions_by_current_status": {
        "kind": "operational", "unit": "workspace", "status": PROPOSED,
        "definition": "Count of subscription rows by their status today (trial, active, past_due, grace, cancelled, expired). "
                      "An operating view: not conversion, not retention, not cash."},
    # --- product (PRD §12 R-MET-01) -------------------------------------------------------------------------------------
    "first_accepted_draft_at": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                                "definition": "Earliest explicit acceptance of a real canonical draft revision by an authorized member (draft.accepted). Generated or opened is not accepted."},
    "time_to_first_accepted_draft": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                                     "definition": "first_accepted_draft_at minus the workspace's creation time (workspace origin, not account signup)."},
    "first_week_ready": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                         "definition": "At least one first week with a frozen committed scope, valid sources and every non-cancelled committed slot ready for review; partial plans reported separately."},
    "completed_work_week": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                            "definition": "A reviewed week whose committed slots each reached the selected delivery outcome: a verified publication, or an assisted handoff the person confirmed. Subtypes reported separately; not a publication count. Scope basis: the frozen scope (first week) or the non-rejected slots (other weeks), stated per row."},
    "next_week_completion_rate": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                                  "definition": "Of workspaces completing work week N, the share completing week N+1, only for fully observed next weeks. Logins and notifications never qualify."},
    "first_verified_publish_at": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                                  "definition": "First authoritative Queue/provider read-back of an owned post (job state verified). Exports and provider acceptance do not qualify."},
    "qualified_business_results": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                                   "definition": "Customer business results by provenance (provider_native, first_party_reported, user_declared) and type, with the association definition, unmatched and reversed counts visible."},
    "cost_per_accepted_artifact": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                                   "definition": "Verified provider cost of the declared task population (failed and platform-funded attempts included, attributed by reservation lineage) divided by distinct accepted artifacts; unknown cost reported separately; zero accepted artifacts is unavailable."},
    "edit_burden": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                    "definition": "The existing versioned edit-distance measure of approved drafts plus review actions; not proof of quality or of a measured time saving."},
    "brief_to_useful_action": {"kind": "product", "unit": "workspace", "status": PROPOSED,
                               "definition": "Delivered brief items leading to their linked accepted action within seven days. Opens and clicks alone are not success."},
    "notification_noise": {"kind": "product", "unit": "recipient", "status": PROPOSED,
                           "definition": "Mutes, unsubscribes and dismissals over eligible recipients in the window; sent is not delivered."},
}


def row(metric_id, value, *, unit="workspace", data_state, known=None, unknown=None, numerator=None, denominator=None,
        source_watermark=None, sample_count=None, reason=None, dimensions=None, interval=None, fixture=False, collecting_since=None,
        history=None, measures=None, currency=None):
    """One metric row in the shared (Founder Control) shape."""
    assert metric_id in DEFINITIONS, metric_id
    out = {"metricId": metric_id, "definitionVersion": DEFINITION_VERSION, "status": DEFINITIONS[metric_id]["status"], "interval": interval,
           "dimensions": dimensions or {}, "value": value, "unit": unit, "dataState": data_state,
           "coverage": {"known": known, "unknown": unknown, "numerator": numerator, "denominator": denominator},
           "sourceWatermark": source_watermark, "sampleCount": sample_count, "reason": reason, "fixture": bool(fixture)}
    if collecting_since is not None:
        out["collectingSince"] = collecting_since
    if history is not None:
        out["history"] = history
    if measures is not None:
        out["measures"] = measures
    if currency is not None:
        out["currency"] = currency
    return out


# --- payment evidence -------------------------------------------------------------------------------------------------
def qualifying(payment):
    """A live, positive, recurring-subscription invoice payment. `payment` keys: workspaceId, invoiceId, status ('paid'),
    livemode, amountPaid (minor units), subscriptionId, billingReason, paidAt, paymentIntentId, provider."""
    return (payment.get("status") == "paid" and payment.get("livemode") is True and isinstance(payment.get("amountPaid"), int)
            and payment["amountPaid"] > 0 and bool(payment.get("subscriptionId")) and payment.get("billingReason") in QUALIFYING_BILLING_REASONS
            and payment.get("provider", "stripe") != "fixture" and isinstance(payment.get("paidAt"), (int, float)))


def _dedupe(payments):
    """One row per invoice (duplicate notifications collapse); the earliest time wins for the same invoice."""
    seen = {}
    for p in payments:
        key = p.get("invoiceId")
        if key is None:
            continue
        if key not in seen or (p.get("paidAt") or 0) < (seen[key].get("paidAt") or 0):
            seen[key] = p
    return list(seen.values())


def first_cash_paid(payments):
    """The workspace's first qualifying payment {invoiceId, paidAt} or None."""
    candidates = sorted((p for p in _dedupe(payments) if qualifying(p)), key=lambda p: (p["paidAt"], p["invoiceId"]))
    return {"invoiceId": candidates[0]["invoiceId"], "paidAt": candidates[0]["paidAt"]} if candidates else None


def refunded_intents(payments, refunds, disputes):
    """Payment intents whose qualifying payment was fully reversed by succeeded refunds or a dispute that was not
    withdrawn. Partial refunds leave the period paid (reported in measures, not hidden)."""
    paid = {}
    for p in _dedupe(payments):
        if qualifying(p) and p.get("paymentIntentId"):
            paid[p["paymentIntentId"]] = paid.get(p["paymentIntentId"], 0) + p["amountPaid"]
    reversed_amount = {}
    for r in refunds or ():
        if r.get("status") == "succeeded" and r.get("paymentIntentId") in paid:
            reversed_amount[r["paymentIntentId"]] = reversed_amount.get(r["paymentIntentId"], 0) + int(r.get("amount") or 0)
    lost = {d["paymentIntentId"] for d in disputes or () if d.get("paymentIntentId") in paid and not d.get("withdrawn") and d.get("status") == "lost"}
    return {pi for pi, amount in reversed_amount.items() if amount >= paid[pi]} | lost


def covered(payments, checkpoint, *, exclude_intents=frozenset()):
    """True when a qualifying paid invoice's service period [periodStart, periodEnd) contains `checkpoint`."""
    for p in _dedupe(payments):
        if not qualifying(p) or p.get("paymentIntentId") in exclude_intents:
            continue
        start, end = p.get("periodStart"), p.get("periodEnd")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start <= checkpoint < end:
            return True
    return False


def retention(cohort, *, now, watermark, days, refund_adjusted=False):
    """`cohort`: {workspaceId: {"payments": [...], "refunds": [...], "disputes": [...]}}. Immature or unwatermarked
    checkpoints are excluded and counted; a missing period on a payment is unknown, never 'not retained'."""
    metric = f"cash_paid_retention_d{days}" + ("_refund_adjusted" if refund_adjusted else "")
    numerator = denominator = immature = unknown = 0
    for evidence in cohort.values():
        first = first_cash_paid(evidence.get("payments") or [])
        if first is None:
            continue
        checkpoint = first["paidAt"] + days * DAY
        if checkpoint > now or watermark is None or checkpoint > watermark:
            immature += 1
            continue
        payments = evidence.get("payments") or []
        if any(qualifying(p) and not (isinstance(p.get("periodStart"), (int, float)) and isinstance(p.get("periodEnd"), (int, float))) for p in payments):
            unknown += 1
            continue
        exclude = refunded_intents(payments, evidence.get("refunds"), evidence.get("disputes")) if refund_adjusted else frozenset()
        denominator += 1
        numerator += 1 if covered(payments, checkpoint, exclude_intents=exclude) else 0
    state = "unavailable" if denominator == 0 else "partial" if unknown or immature else "available"
    return row(metric, round(numerator / denominator, 4) if denominator else None, data_state=state, known=denominator, unknown=unknown,
               numerator=numerator, denominator=denominator, source_watermark=watermark, sample_count=denominator,
               reason=None if state == "available" else ("no_mature_checkpoints" if denominator == 0 else "immature_or_unknown_excluded"),
               measures={"immatureExcluded": immature, "unknownPeriods": unknown})


def window_conversion(metric_id, cohort, *, now, watermark, window_days=30):
    """`cohort`: {workspaceId: {"startedAt": t, "payments": [...]}}. Only fully observable windows count; a payment
    outside the window is not a conversion for this definition."""
    numerator = denominator = immature = 0
    for evidence in cohort.values():
        start = evidence.get("startedAt")
        if not isinstance(start, (int, float)):
            continue
        end = evidence.get("windowEnd") if isinstance(evidence.get("windowEnd"), (int, float)) else start + window_days * DAY
        if end > now or watermark is None or end > watermark:
            immature += 1
            continue
        denominator += 1
        first = first_cash_paid(evidence.get("payments") or [])
        numerator += 1 if first and start <= first["paidAt"] < end else 0
    state = "unavailable" if denominator == 0 else "partial" if immature else "available"
    return row(metric_id, round(numerator / denominator, 4) if denominator else None, data_state=state, known=denominator, numerator=numerator,
               denominator=denominator, source_watermark=watermark, sample_count=denominator,
               reason=None if state == "available" else ("no_mature_windows" if denominator == 0 else "immature_windows_excluded"),
               measures={"immatureExcluded": immature})


# --- product: completed work week -------------------------------------------------------------------------------------
def week_completion(week, first_week=None):
    """(complete, subtypes) for one week. Committed slots: the frozen first-week scope when this week has one, else the
    non-rejected slots. A slot is delivered by a verified publication or a confirmed, current assisted handoff."""
    scope = (first_week or {}).get("scope") or {}
    handoffs = (first_week or {}).get("handoffs") or {}
    if scope and scope.get("weekId") == week.get("id"):
        committed = [s for s in week.get("slots") or [] if s["id"] in scope.get("slotIds", [])]
        basis = "frozen_scope"
    else:
        committed = [s for s in week.get("slots") or [] if s.get("status") not in ("rejected",)]
        basis = "non_rejected_slots"
    verified = sum(1 for s in committed if s.get("status") == "published")
    assisted = sum(1 for s in committed if s.get("status") != "published" and (handoffs.get(s["id"]) or {}).get("state") == "user_confirmed_used")
    complete = bool(committed) and verified + assisted == len(committed)
    return complete, {"basis": basis, "committed": len(committed), "verified": verified, "assisted": assisted}
