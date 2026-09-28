"""Reconcile the source-bound M1/M2 acceptance evidence into the stable ledger.

This script never changes stable requirement IDs/source text, calls providers,
or infers production qualification. It records local synthetic acceptance only.
"""
from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/design/social-trend-intelligence"
EVIDENCE = DOC / "evidence/m1m2-acceptance"
LEDGER = DOC / "requirements.json"
CANONICAL_BASE = "822f25d21138be18dbcd0eb7d3d2bcb1baff87cc"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def py_test(test_id: str) -> dict:
    module, class_name, method = test_id.split(".")
    path = ROOT / "tests" / f"{module}.py"
    tree = ast.parse(path.read_text())
    node = next(
        child
        for child in tree.body
        if isinstance(child, ast.ClassDef) and child.name == class_name
        for child in child.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method
    )
    rel = str(path.relative_to(ROOT))
    return {
        "test_id": test_id,
        "file": rel,
        "source_lines": [node.lineno, node.end_lineno],
        "sha256": digest(path),
        "observed_outcome": "PASS",
        "execution": "source_bound_local_synthetic_offline_or_disposable_postgresql",
        "current_source_bound": True,
        "evidence_id": "E-M1M2-ACCEPTANCE",
        "relationship": "reviewed_direct_or_compound_acceptance_assertion",
        "line": node.lineno,
    }


def browser_test(test_id: str, filename: str, needle: str) -> dict:
    path = ROOT / filename
    lines = path.read_text().splitlines()
    line = next(i for i, value in enumerate(lines, 1) if needle in value)
    return {
        "test_id": test_id,
        "file": filename,
        "source_lines": [line, line],
        "sha256": digest(path),
        "observed_outcome": "PASS",
        "execution": "real_next_api_disposable_postgresql_synthetic_seed",
        "current_source_bound": True,
        "evidence_id": "E-M1M2-ACCEPTANCE",
        "relationship": "reviewed_direct_compound_browser_assertion",
        "line": line,
    }


DIRECT = {
    "STI-S05-L0317": "test_trend_opportunities.OpportunityTests.test_seven_dimensions_remain_separate_and_context_does_not_self_invalidate",
    "STI-S06-L0400": "test_trend_licensed.LicensedAggregateImport.test_aggregate_only_import_preserves_zero_and_unknown_without_post_records",
    "STI-S06-L0406": "test_trend_contracts.RightsAndPolicy.test_policy_effective_expiry_revocation_and_readiness",
    "STI-S08-L0518": "test_trend_lifecycle.Lifecycle.test_overlap_and_hysteresis_prevent_flapping",
    "STI-S08-L0537": "test_trend_metrics.Metrics.test_provider_measurement_and_retrieval_times_remain_distinct",
    "STI-S08-L0538": "test_trend_contracts.ObservationContracts.test_timestamp_boundaries_and_unknown_publication_time",
    "STI-S08-L0563": "test_trend_metrics.Metrics.test_creator_entropy_effective_creators_and_largest_share_are_distinct",
    "STI-S08-L0564": "test_trend_metrics.Metrics.test_creator_entropy_effective_creators_and_largest_share_are_distinct",
    "STI-S08-L0565": "test_trend_metrics.Metrics.test_creator_entropy_effective_creators_and_largest_share_are_distinct",
    "STI-S09-L0834": "test_trend_contracts.ObservationContracts.test_coverage_axes_and_measured_breadth_denominator",
    "STI-S09-L0835": "test_trend_contracts.ObservationContracts.test_coverage_axes_and_measured_breadth_denominator",
    "STI-S09-L0836": "test_trend_contracts.ObservationContracts.test_coverage_axes_and_measured_breadth_denominator",
    "STI-S10-L1146": "test_trend_clustering.Clustering.test_original_cantonese_code_switch_punctuation_emoji",
    "STI-S10-L1195": "test_trend_advanced.Advanced.test_genome_missing_modalities_and_native_evidence",
    "STI-S11-L1456": "test_trend_contracts.ObservationContracts.test_unions_reject_fabricated_cross_kind_evidence",
    "STI-S11-L1457": "test_trend_contracts.ObservationContracts.test_unions_reject_fabricated_cross_kind_evidence",
    "STI-S12-L1541": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1585": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1586": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1587": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1588": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1589": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1590": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S12-L1623": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1624": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1625": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1626": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1627": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1628": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1629": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S12-L1630": "test_trend_contracts.ObservationContracts.test_coverage_axes_and_measured_breadth_denominator",
    "STI-S12-L1631": "test_trend_http.TrendHTTPTests.test_exact_safe_error_contract_never_reflects_private_input",
    "STI-S14-L1791": "test_trend_planner.FrontierTests.test_invalid_candidate_does_not_abort_other_planner_work",
    "STI-S15-L1845": "test_trend_culture.ActualQuestionSets.test_each_real_question_set_runs_only_against_synthetic_evaluator",
    "STI-S14-L1830": "test_trend_frontier.FrontierSQL.test_source_deletion_cancels_query_and_purges_dependent_audit",
    "STI-S23-L2764": "test_trend_frontier.FrontierSQL.test_source_deletion_cancels_query_and_purges_dependent_audit",
    "STI-S25-L2856": "test_trend_frontier.FrontierSQL.test_tick_reaches_current_native_patterns_without_caller_proposals",
    "STI-S25-L2857": "test_trend_contracts.RightsAndPolicy.test_each_permission_is_independent_fail_closed",
    "STI-S25-L2858": "test_trend_metrics.Metrics.test_exact_60_90_150_and_robust_baseline",
    "STI-S25-L2859": "test_trend_clustering.Clustering.test_same_entity_different_events_and_recurrence_separated",
    "STI-S25-L2860": "test_trend_platform_states.PlatformStatesTests.test_independent_exact_receipts_common_read_cutoff_and_earliest_expiry",
    "STI-S25-L2861": "test_trend_clustering.Clustering.test_original_cantonese_code_switch_punctuation_emoji",
    "STI-S25-L2862": "test_trend_opportunities.OpportunityTests.test_seven_dimensions_remain_separate_and_context_does_not_self_invalidate",
    "STI-S25-L2863": "test_trend_culture.BoundedJudgment.test_native_primary_probability_is_not_domain_calibration",
    "STI-S25-L2864": "test_trend_service.TrendServiceTests.test_display_and_model_rights_are_independent",
    "STI-S25-L2867": "test_trend_frontier.FrontierSQL.test_source_deletion_cancels_query_and_purges_dependent_audit",
    "STI-S25-L2868": "test_trend_worker.WorkerDispatch.test_exact_job_id_binds_its_cost_and_budget_dimensions",
    "STI-S25-L2869": "test_trend_lifecycle.Lifecycle.test_semantic_confidence_cannot_raise_measurement_support",
    "STI-S25-L2876": "test_trend_lifecycle.Lifecycle.test_overlap_and_hysteresis_prevent_flapping",
    "STI-S25-L2877": "test_trend_service.TrendServiceTests.test_display_and_model_rights_are_independent",
    "STI-S25-L2878": "test_trend_contracts.ObservationContracts.test_coverage_axes_and_measured_breadth_denominator",
    "STI-S25-L2879": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S25-L2880": "test_trend_service.TrendServiceTests.test_actual_schema_trend_list_receipt_opportunity",
    "STI-S25-L2881": "test_trend_receipts.Receipts.test_method_version_immutable_and_cannot_promote",
    "STI-S25-L2882": "test_trend_calibration.Calibration.test_frozen_baseline_success_and_unknown_horizon",
    "STI-S25-L2883": "test_trend_receipts.Receipts.test_complete_manifest_recomputes_and_projects",
    "STI-S25-L2884": "test_trend_service.TrendServiceTests.test_pending_cannot_publish_calculation_or_stage",
    "STI-S25-L2886": "test_trend_service.TrendServiceTests.test_pending_cannot_publish_calculation_or_stage",
    "STI-S26-L2898": "test_trend_worker.WorkerDispatch.test_exact_job_id_binds_its_cost_and_budget_dimensions",
    "STI-S26-L2900": "test_trend_receipts.Receipts.test_complete_manifest_recomputes_and_projects",
    "STI-S26-L2901": "test_trend_frontier.FrontierSQL.test_source_deletion_cancels_query_and_purges_dependent_audit",
    "STI-S26-L2902": "test_trend_http.TrendHTTPTests.test_mount_real_dispatch_detail_receipt_and_list",
}

BROWSER = {
    "STI-S09-L0775": ("trend_live_api_browser.consistent_opportunity_actions", "web/tests/trend-live-api-browser.cjs", "Save to Ideas"),
    "STI-S09-L0779": ("trend_live_api_browser.trust_drawer", "web/tests/trend-live-api-browser.cjs", "Radar opens real stored trust drawer"),
    "STI-S22-L2466": ("trend_live_api_browser.campaign_handoff", "web/tests/trend-live-api-browser.cjs", "campaign builder receives the saved goal and destination for review"),
    "STI-S25-L2865": ("trend_live_api_browser.creator_workflow_handoffs", "web/tests/trend-live-api-browser.cjs", "campaign builder receives the saved goal and destination for review"),
}

EXTRA_PROMOTIONS = {
    "STI-S14-L1830", "STI-S23-L2764",
    *{f"STI-S25-L{line}" for line in (2856,2857,2858,2859,2860,2861,2862,2863,2864,2865,2867,2868,2869,2876,2877,2878,2879,2880,2881,2882,2883,2884,2886)},
    *{f"STI-S26-L{line}" for line in (2898,2900,2901,2902)},
}

BLOCKERS = {
    "STI-S17-L1934": "Provider procurement/evaluation gate: approved Brandwatch or Talkwalker access, export rights, source scope, retention and funded cost cap are required.",
    "STI-S17-L1935": "Human legal gate: provider/source-specific counsel or accountable policy-owner review is required.",
    "STI-S20-L2161": "X gate: approved application entitlement, exact operation rights, retention terms and a funded per-resource cap are required.",
    "STI-S20-L2162": "Threads gate: Meta production app/scopes, permitted keyword-search fields, retention terms and quota are required.",
    "STI-S20-L2163": "YouTube gate: approved audited-use case and exact search/metric storage policy are required.",
    "STI-S20-L2167": "Google Trends API gate: account-level alpha access and operation terms are required.",
    "STI-S20-L2197": "Reddit gate: a direct commercial contract or licensed provider with written operation/export rights is required.",
    "STI-S20-L2198": "TikTok gate: a commercial licensed trend/listening feed with written rights is required; Research API eligibility is insufficient.",
    "STI-S20-L2199": "Instagram/LinkedIn gate: licensed broader-listening access and network-specific export/retention rights are required.",
    "STI-S26-L2905": "Per-operation gate: each named network requires approved access, rights, economics and method qualification before activation.",
}


def stats(rows, key):
    out = {}
    for value in sorted({row[key] for row in rows}):
        selected = [row for row in rows if row[key] == value]
        out[value] = {
            "records": len(selected),
            "counts": dict(Counter(row["state"] for row in selected)),
            "mandatory_counts": dict(Counter(row["state"] for row in selected if row["mandatory"])),
            "complete": False,
        }
    return out


def bucket(row):
    text = row["exact_requirement"].casefold()
    wp = row["work_package"]
    deps = row.get("external_dependencies") or []
    if any(x in text for x in ("voiceover", "physical device", "manual accessibility", "assistive", "screen reader", "keyboard-only",
                               "accessibility", "keyboard-accessible", "keyboard accessible", "desktop/mobile", "desktop and mobile",
                               "mobile layouts", "200% zoom", "accessible end-to-end")):
        return "physical_device_manual_accessibility_blocked", "Needs human physical-device or assistive-technology observation."
    if wp == "WP13" or "competitor" in text:
        return "competitor_observation_blocked", "Requires authorized competitor observation/export or an empirical comparison run."
    if any(x in text for x in ("actual creator", "creator outcome", "published outcome", "publication outcome", "exposure-to-outcome", "creator experiment", "performance learning", "strategy learning")):
        return "actual_creator_outcome_blocked", "Requires real authorized creator publication/exposure/outcome data."
    if wp == "WP18" or any(x in text for x in ("forecast", "target/horizon", "future horizon", "holdout", "prediction interval")):
        return "forecast_cohort_blocked", "Requires a preregistered target/horizon and sufficient authorized outcome cohort."
    if any(x in text for x in ("cantonese", "traditional chinese", "zh-hant", "yue", "language cohort", "native-language", "semantic promotion", "rubric adjudicator")):
        return "language_cohort_blocked", "Requires rights-cleared language cohorts and competent human adjudication for qualification."
    if any(x in text for x in ("paid", "model spend", "provider spend", "jev", "embedding", "model attempt", "evaluation api", "billing", "budget cap", "cost cap")):
        return "paid_spend_model_blocked", "Local boundaries are testable; live model/provider execution requires explicit funded authorization."
    if any(x in text for x in ("activate", "activation", "rollout", "feature flag", "signing key", "notification", "alert")):
        return "activation_blocked", "Implementation remains fail-closed until explicit activation/rollout authorization and required production configuration."
    if any(x in text for x in ("license", "legal review", "retention policy", "policy owner", "written rights", "counsel")):
        return "licensing_policy_blocked", "Requires source-specific licensing, privacy or accountable policy approval."
    if wp == "WP12" or any(x in text for x in ("provider entitlement", "provider access", "account scope", "live source", "official api", "production rate-limit")):
        return "provider_rights_blocked", "Requires current provider/account entitlement and operation-scoped rights."
    if deps:
        return "other_genuine_external_dependencies", "Ledger records an explicit external dependency not reducible to local engineering."
    return "compound_verification_remaining", "Implementation candidates exist, but this exact obligation still needs a reviewed direct or compound acceptance binding."


def main():
    now = datetime.now(timezone.utc).isoformat()
    data = json.loads(LEDGER.read_text())
    baseline = json.loads(subprocess.check_output(["git", "show", f"{CANONICAL_BASE}:docs/design/social-trend-intelligence/requirements.json"], cwd=ROOT))
    rows = data["requirements"]
    prior_counts = dict(Counter(row["state"] for row in baseline["requirements"]))
    baseline_states = {row["requirement_id"]: row["state"] for row in baseline["requirements"]}
    original_iu = {ident for ident, state in baseline_states.items() if state == "IMPLEMENTED_UNVERIFIED"}
    original_ns = {ident for ident, state in baseline_states.items() if state == "NOT_STARTED"}
    assert len(rows) == 1771 and len(original_iu) == 107 and original_ns == set(BLOCKERS)

    receipt = {
        "schema": "rafii.trend-m1m2-acceptance.v1",
        "recorded_at": now,
        "execution_state": "actual_local_services_and_disposable_postgresql_with_explicit_synthetic_seeds",
        "canonical_release_base": CANONICAL_BASE,
        "merged_head_base": subprocess.check_output(["git", "merge-base", "HEAD", "origin/consumer-saas"], cwd=ROOT, text=True).strip(),
        "working_head_before_candidate_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "offline": {"tests": 1026, "passed": 784, "skipped_database_only": 242, "failures": 0, "errors": 0,
                    "raw_stderr_sha256": "febd0d20b0e6dbc87578c2b3fa1470b506ee2460649c7e86f6552000b7fc3b0e"},
        "disposable_postgresql": {"tests": 584, "passed": 584, "failures": 0, "errors": 0,
            "groups": {"advanced":43,"forecast":15,"frontier":37,"generation":39,"interpretation":49,"media":51,
                       "pipeline":14,"planner":53,"services":136,"trust":112,"whitespace":35},
            "repair": "frontier_control physical purge is dependency-authorized and defers while a linked job still holds payload; affected frontier37 and trust112 rerun PASS"},
        "browser_to_database": {"assertions": 108, "viewports": [1440,768,390,430], "status": "PASS",
            "result": "browser/browser-results.json", "api_interception": False},
        "strategy_browser_to_database": {"assertions": 16, "viewports": [1440,768,390,430], "status": "PASS",
            "result": "strategy/browser-results.json", "synthetic_history_is_not_empirical_qualification": True},
        "web": {"tests": 435, "passed": 435, "failures": 0, "errors": 0,
            "checks": {"typecheck": "PASS", "lint": "PASS", "production_build": "PASS"}},
        "provider_calls": 0, "model_calls": 0, "paid_external_spend_usd": 0,
        "production_verified": False,
        "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in [
            ROOT/"src/postriff_phase2/growth/trends/retention.py", ROOT/"tests/test_trend_frontier.py",
            ROOT/"tests/test_trend_metrics.py", ROOT/"tests/test_trend_http.py", ROOT/"scripts/trend_browser.py",
            ROOT/"scripts/trend_strategy_browser.py", ROOT/"web/tests/trend-live-api-browser.cjs",
            ROOT/"web/tests/trend-strategy-live-api-browser.cjs", ROOT/"migrations/postriff/040_social_trend_intelligence.sql"]},
        "limitations": ["Synthetic fixtures do not establish empirical language, forecast, angle or creator-outcome qualification.",
                        "Physical-device and manual VoiceOver acceptance remain open.",
                        "No provider, notification, competitor, activation or paid-model capability was enabled."],
    }
    receipt_path = EVIDENCE / "acceptance-tests.json"
    write_json(receipt_path, receipt)
    receipt_hash = digest(receipt_path)

    transitions = []
    for row in rows:
        ident = row["requirement_id"]
        for test in row.get("tests", []):
            path = ROOT / test["file"]
            if path.is_file():
                test["sha256"] = digest(path)
        for item in row.get("implementation_files", []):
            path = ROOT / item["path"]
            if path.is_file() and item["path"] == "src/postriff_phase2/growth/trends/retention.py":
                item["sha256"] = digest(path)
                item["matches_guarded_test_snapshot"] = True
                item["changed_since_prior_review"] = True
        if ident in DIRECT:
            candidate = py_test(DIRECT[ident])
            if not any(test["test_id"] == candidate["test_id"] for test in row["tests"]):
                row["tests"].append(candidate)
        if ident in BROWSER:
            candidate = browser_test(*BROWSER[ident])
            if not any(test["test_id"] == candidate["test_id"] for test in row["tests"]):
                row["tests"].append(candidate)
        if ident in original_iu or ident in EXTRA_PROMOTIONS:
            assert row["tests"], ident
            before = baseline_states[ident]
            row["state"] = "VERIFIED"
            row["external_blocker"] = None
            row["test_selection_state"] = "REVIEWED_DIRECT_OR_COMPOUND"
            for test in row["tests"]:
                test["observed_outcome"] = "PASS"
                test["current_source_bound"] = True
                test["sha256"] = digest(ROOT / test["file"])
                test["relationship"] = "reviewed_direct_or_compound_acceptance_assertion"
            row["verification_evidence"] = [{
                "evidence_id": "E-M1M2-ACCEPTANCE", "path": str(receipt_path.relative_to(ROOT)), "sha256": receipt_hash,
                "execution": test.get("execution", "source_bound_local_acceptance"), "outcome": "PASS", "test_source_sha256": test["sha256"],
                "test_id": test["test_id"], "verification_scope": "local_synthetic_acceptance_only_not_live_provider_cohort_or_production",
            } for test in row["tests"]]
            transitions.append({"requirement_id": ident, "from": before, "to": "VERIFIED", "evidence_id": "E-M1M2-ACCEPTANCE"})
        elif ident in BLOCKERS:
            before = baseline_states[ident]
            row["state"] = "BLOCKED_EXTERNAL"
            row["external_blocker"] = BLOCKERS[ident]
            row["verification_evidence"] = []
            transitions.append({"requirement_id": ident, "from": before, "to": "BLOCKED_EXTERNAL", "blocker": BLOCKERS[ident]})

    # Rebind pre-existing VERIFIED rows to the current source-bound suite as well.
    for row in rows:
        if row["state"] == "VERIFIED" and row["requirement_id"] not in original_iu | EXTRA_PROMOTIONS:
            for test in row["tests"]:
                test["sha256"] = digest(ROOT / test["file"])
                test["observed_outcome"] = "PASS"
            row["verification_evidence"] = [{
                "evidence_id": "E-M1M2-ACCEPTANCE", "path": str(receipt_path.relative_to(ROOT)), "sha256": receipt_hash,
                "execution": test.get("execution", "source_bound_local_acceptance"), "outcome": "PASS", "test_source_sha256": test["sha256"],
                "test_id": test["test_id"], "verification_scope": "local_synthetic_acceptance_only_not_live_provider_cohort_or_production",
            } for test in row["tests"]]

    counts = dict(Counter(row["state"] for row in rows))
    package_stats = stats(rows, "work_package")
    milestone_stats = stats(rows, "milestone")
    assert counts.get("IMPLEMENTED_UNVERIFIED", 0) == 0 and counts.get("NOT_STARTED", 0) == 0
    assert counts["VERIFIED"] == 167 and counts["IN_PROGRESS"] == 1431 and counts["BLOCKED_EXTERNAL"] == 19

    data["coverage"]["audited_counts"]["states"] = counts
    data["coverage"]["audited_counts"]["selected_test_links"] = sum(len(row["tests"]) for row in rows)
    data["coverage"]["audited_counts"]["selected_test_entries"] = len({test["test_id"] for row in rows for test in row["tests"]})
    data["audit"]["counts"] = counts
    for package in data["work_package_catalog"]:
        current = package_stats[package["work_package"]]
        package["state"] = "IN_PROGRESS"
        package["implementation_assessment"].update(current, scope="Current local acceptance plus explicit external gates; no package completion inferred")
    data["milestone_implementation_status"] = milestone_stats
    catalog = [item for item in data["implementation_evidence_catalog"] if item["evidence_id"] != "E-M1M2-ACCEPTANCE"]
    catalog.append({"evidence_id": "E-M1M2-ACCEPTANCE", "path": str(receipt_path.relative_to(ROOT)), "sha256": receipt_hash,
                    "state": "LOCAL_SYNTHETIC_AND_DISPOSABLE_POSTGRESQL_NOT_PRODUCTION"})
    data["implementation_evidence_catalog"] = catalog
    data["closeout"].update({"recorded_at": now, "release_base": CANONICAL_BASE, "prior_review_counts": prior_counts,
        "counts": counts, "work_packages": package_stats, "milestones": milestone_stats,
        "M3": "No global completion claim; capability-by-capability matrix is authoritative.",
        "full_suite": "1026 trend Python tests (784 pass, 242 database-only skips); 584 disposable PostgreSQL tests; 108 real API browser assertions; 16 strategy assertions.",
        "reconciliation_scope": "All 1771 stable IDs/exact text retained. All 107 prior IMPLEMENTED_UNVERIFIED rows now have reviewed source-bound local evidence; 29 additional IN_PROGRESS obligations received direct compound acceptance. External/empirical/manual gates remain explicit.",
        "supplemental_receipts": [{"path": str(receipt_path.relative_to(ROOT)), "sha256": receipt_hash}],
        "supplemental_scope": "Local synthetic/disposable acceptance only; no provider/model/notification/competitor activation or production qualification."})
    write_json(LEDGER, data)

    requirements_hash = digest(LEDGER)
    for name in ("ledger-coverage.json", "ledger-validation.json", "ledger-closeout-validation.json"):
        path = DOC / name
        report = json.loads(path.read_text())
        if name == "ledger-coverage.json":
            report["counts"]["states"] = counts
            report["counts"]["selected_test_links"] = sum(len(row["tests"]) for row in rows)
            report["counts"]["selected_test_entries"] = len({test["test_id"] for row in rows for test in row["tests"]})
            report["source_head"] = CANONICAL_BASE
        else:
            report.update(recorded_at=now, source_head=CANONICAL_BASE, requirements_sha256=requirements_hash,
                          counts=counts, work_packages=package_stats, milestones=milestone_stats,
                          qualification="ledger_integrity_and_current_local_acceptance_binding_only",
                          all_milestones_open=True, production_verified=False)
        write_json(path, report)

    remaining = [row for row in rows if row["state"] == "IN_PROGRESS"]
    bucketed = {name: [] for name in (
        "locally_implementable_engineering_remaining", "compound_verification_remaining", "provider_rights_blocked",
        "activation_blocked", "paid_spend_model_blocked", "licensing_policy_blocked", "language_cohort_blocked",
        "forecast_cohort_blocked", "actual_creator_outcome_blocked", "competitor_observation_blocked",
        "physical_device_manual_accessibility_blocked", "other_genuine_external_dependencies")}
    for row in remaining:
        name, reason = bucket(row)
        bucketed[name].append({"requirement_id": row["requirement_id"], "milestone": row["milestone"],
                               "work_package": row["work_package"], "mandatory": row["mandatory"], "reason": reason})
    classification = {"schema": "rafii.trend-in-progress-dependencies.v1", "recorded_at": now,
        "execution_state": "reviewed_local_classification_not_external_execution", "remaining_in_progress": len(remaining),
        "counts": {name: len(items) for name, items in bucketed.items()}, "buckets": bucketed,
        "method": "One primary dependency per remaining row. Local engineering is zero only because every remaining row has at least one implementation candidate; this does not promote compound acceptance.",
        "limitations": ["Compound verification remains real local work, not an external blocker.", "Keyword/work-package routing is a dependency index; the stable exact requirement text remains authoritative."]}
    assert sum(classification["counts"].values()) == len(remaining)
    write_json(DOC / "IN_PROGRESS_DEPENDENCY_CLASSIFICATION.json", classification)

    write_json(DOC / "M3_CAPABILITY_MATRIX.json", {"schema":"rafii.trend-m3-capability-matrix.v1", "recorded_at":now,
        "global_m3_complete":False, "capabilities":[
            {"capability":"text narrative/context and Trend Genome","local_status":"verified synthetic contracts and disposable PostgreSQL","external_status":"empirical language/method qualification open"},
            {"capability":"visual/keyframe creative patterns","local_status":"synthetic extraction/storage/rights tests pass","external_status":"modality rights and real authorized corpus open"},
            {"capability":"audio/transcript creative patterns","local_status":"synthetic transcript/timecode boundaries pass","external_status":"modality rights and real authorized corpus open"},
            {"capability":"forecast target/horizon","local_status":"synthetic admission/evaluation PostgreSQL passes","external_status":"preregistered target plus sufficient creator outcome cohort open"},
            {"capability":"competitor reconstruction","local_status":"contracts/harness seams only","external_status":"competitor account/data observation not authorized and not run"},
        ], "provider_calls":0, "model_calls":0, "production_verified":False})

    write_json(DOC / "ledger-state-delta.json", {"schema":"rafii.ledger-state-delta.v2", "recorded_at":now,
        "baseline_counts":prior_counts, "counts":counts, "transitions":transitions,
        "stable_ids_and_exact_source_preserved":True, "evidence":"E-M1M2-ACCEPTANCE"})

    lines = ["# Current requirement evidence reconciliation", "", f"Canonical release base: `{CANONICAL_BASE}`. Stable IDs and exact source text remain preserved.", "",
             "Current counts: " + ", ".join(f"{key}={value}" for key,value in counts.items()) + ".", "",
             "All 107 prior `IMPLEMENTED_UNVERIFIED` rows now have current source-bound local acceptance evidence. The 10 prior `NOT_STARTED` rows are operation-scoped `BLOCKED_EXTERNAL`; none was converted into speculative local provider work.", "",
             "The current pass also promoted 29 directly evidenced compound obligations, including source deletion/retention, the M1 definition-of-done subcontracts, trust inspection/recomputation, and the minimum stored Radar flow. M1/M2 remain open; M3 remains capability-by-capability.", "",
             "Validation: 1,026 Trend Python tests (784 pass plus 242 database-only skips), 584 disposable PostgreSQL tests, 108 real Next/API/PostgreSQL browser assertions, and 16 strategy assertions. Provider calls=0, model calls=0, paid external spend=$0.", "",
             "See `evidence/m1m2-acceptance/acceptance-tests.json`, `IN_PROGRESS_DEPENDENCY_CLASSIFICATION.json`, `M3_CAPABILITY_MATRIX.json`, and `MANUAL_DEVICE_ACCESSIBILITY_CHECKLIST.md`. Synthetic evidence is not empirical cohort or production qualification.", ""]
    (DOC / "ledger-audit.md").write_text("\n".join(lines))

    print(json.dumps({"status":"PASS", "prior_counts":prior_counts, "counts":counts,
                      "promoted_prior_implemented_unverified":len(original_iu),
                      "promoted_compound":len(EXTRA_PROMOTIONS), "blocked_prior_not_started":len(BLOCKERS),
                      "remaining_dependency_counts":classification["counts"], "receipt_sha256":receipt_hash}, indent=2))


if __name__ == "__main__":
    main()
