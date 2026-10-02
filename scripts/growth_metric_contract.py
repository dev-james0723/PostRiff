"""Generate the Founder Control catalog rows for this program's metric definitions (DECISIONS D-025).

    PYTHONPATH=src python scripts/growth_metric_contract.py            # rewrite the contract file
    PYTHONPATH=src python scripts/growth_metric_contract.py --check    # exit 1 if the file is stale

The rows use Founder Control's proposed-row shape and only vocabulary its `catalogs/metrics.json` already uses (grain,
unit, currency policy, zero denominator, refresh target, dimensions), so they can be appended to that file unchanged.
They belong in `catalogs/metrics.json`, never `metrics.d/` (the loader accepts only activated rows there). The text of
each definition comes from `postriff_phase2.metric_definitions`, the same source the Growth operator report uses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))   # scripts/postriff_phase2.py would otherwise shadow the package
from postriff_phase2 import metric_definitions as definitions  # noqa: E402

OUT = ROOT / "docs/design/rafii-product-growth/contracts/founder-metrics-growth.json"
SOURCES = {
    "financial": "billing projection (pr_invoices when present, else verified credit-plan grants) + refunds/disputes by payment intent",
    "operational": "subscription transitions",
    "product": "workspace state + pr_product_events (growth_events taxonomy) + pr_usage_ledger (business_usage_v2) lineage",
}
# id: (grain, unit, money?) in Founder Control's existing vocabulary.
SHAPE = {
    "first_cash_paid_conversion": ("signup cohort", "ratio", False),
    "legacy_trial_to_paid": ("signup cohort", "ratio", False),
    "cash_paid_retention_d30": ("opening paid cohort", "ratio", False),
    "cash_paid_retention_d60": ("opening paid cohort", "ratio", False),
    "cash_paid_retention_d90": ("opening paid cohort", "ratio", False),
    "cash_paid_retention_d30_refund_adjusted": ("opening paid cohort", "ratio", False),
    "cash_paid_retention_d60_refund_adjusted": ("opening paid cohort", "ratio", False),
    "cash_paid_retention_d90_refund_adjusted": ("opening paid cohort", "ratio", False),
    "subscriptions_by_current_status": ("subscription snapshot", "count", False),
    "first_accepted_draft_at": ("occurrence", "count", False),
    "time_to_first_accepted_draft": ("signup cohort", "seconds_distribution", False),
    "first_week_ready": ("workspace interval", "count", False),
    "completed_work_week": ("workspace interval", "count", False),
    "next_week_completion_rate": ("workspace interval", "ratio", False),
    "first_verified_publish_at": ("occurrence", "count", False),
    "qualified_business_results": ("workspace interval", "count", True),
    "cost_per_accepted_artifact": ("workspace interval", "usd_micro", False),
    "edit_burden": ("workspace interval", "ratio", False),
    "brief_to_useful_action": ("workspace interval", "ratio", False),
    "notification_noise": ("workspace interval", "ratio", False),
}
DIMENSIONS = {"financial": ["cohort", "plan"], "operational": ["plan", "status"], "product": []}
EXCLUSIONS = ["synthetic", "test", "internal_founder_activity"]


def rows():
    out = []
    for metric_id, spec in definitions.DEFINITIONS.items():
        if spec.get("owner") == "founder":
            continue   # Founder Control already defines it (source_paid_conversion); referenced, never redefined
        grain, unit, money = SHAPE[metric_id]
        out.append({
            "id": metric_id, "version": 1, "title": metric_id.replace("_", " ").capitalize(), "grain": grain, "unit": unit,
            "definition": spec["definition"], "source_contract": SOURCES[spec["kind"]],
            "allowed_dimensions": (["currency"] if money else []) + DIMENSIONS[spec["kind"]],
            "query_template_ref": f"growth/{metric_id}/v1", "default_exclusions": EXCLUSIONS,
            "data_state_required": True, "currency_policy": "native_currency_separate" if money else "not_applicable",
            "zero_denominator": "unavailable" if unit in ("ratio", "usd_micro") else "not_applicable",   # usd_micro here is per artifact
            "refresh_target": "hourly_or_source_cadence",
            "limitations": "Computed by postriff_phase2.metric_definitions (v1, shared with the Growth operator report). Immature or "
                           "unwatermarked checkpoints are excluded and counted; coverage gaps stay partial with every reason listed; "
                           "fixture and test-mode payments never qualify.",
            "status": definitions.PROPOSED,
        })
    return out


def render():
    return json.dumps(rows(), indent=1, ensure_ascii=False) + "\n"


def main(argv):
    text = render()
    if "--check" in argv:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        print(json.dumps({"contract": str(OUT.name), "stale": stale}))
        return 1 if stale else 0
    OUT.write_text(text, encoding="utf-8")
    print(json.dumps({"contract": str(OUT.name), "rows": len(rows())}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
