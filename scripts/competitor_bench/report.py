"""Executable offline research report. No API, account login or live collector."""
from argparse import ArgumentParser
from pathlib import Path
import json

try:
    from .import_observations import validate_manifest, import_observations
    from .run_candidates import run_candidates
except ImportError:  # python scripts/competitor_bench/report.py ...
    from import_observations import validate_manifest, import_observations
    from run_candidates import run_candidates


def compare_behavior(payload):
    rankings = payload.get("candidate_rankings", {})
    observed = payload.get("observed_ranking", [])
    if not observed:
        return {"state": "NOT_RUN", "agreement": {}, "non_identifiability": []}
    if len(set(observed)) != len(observed):
        raise ValueError("duplicate observed ranking member")
    agreement, signatures = {}, {}
    for name, ranking in rankings.items():
        if len(set(ranking)) != len(ranking):
            raise ValueError("duplicate candidate ranking member")
        shared = [x for x in ranking if x in observed]
        concordant = discordant = 0
        for i, left in enumerate(shared):
            for right in shared[i+1:]:
                if observed.index(left) < observed.index(right):
                    concordant += 1
                else:
                    discordant += 1
        pairs = concordant+discordant
        agreement[name] = {"overlap_count": len(shared), "overlap_fraction": len(shared)/len(observed),
                           "kendall_tau": (concordant-discordant)/pairs if pairs else None}
        if len(shared) >= 2:
            signatures.setdefault(tuple(shared), []).append(name)
    return {"state": "observed_agreement", "agreement": agreement,
            "non_identifiability": [v for v in signatures.values() if len(v)>1],
            "decision_rule": "independent_outcomes_not_competitor_agreement", "proprietary_formula_recovered": False}


def run_report(payload):
    manifest = validate_manifest(payload["manifest"])
    imported = import_observations(payload)
    candidates = [{"case_id": case["case_id"], "result": run_candidates(case)} for case in payload.get("synthetic_cases", [])]
    # Ranking comparisons require imported, comparable observations; a supplied rank alone is not evidence.
    comparison = compare_behavior(payload.get("comparison", {})) if imported["state"] == "observed" and all(r["comparable"] for r in imported["observations"]) else {"state": "NOT_RUN", "agreement": {}, "non_identifiability": []}
    columns = {"published": "source_ledger_only" if payload.get("published_sources") else "NOT_RUN",
               "observed": imported["state"], "hypothesized": "independent_candidate_methods",
               "implemented": "offline_candidates" if candidates else "NOT_RUN", "validated": "NOT_RUN", "not_run": ["live_collection", "independent_user_outcomes", "production_qualification"]}
    lines = ["# Competitor capability benchmark", "", f"Run: {manifest['run_id']}", "",
             "| published | observed | hypothesized | implemented | validated | not_run |",
             "|---|---|---|---|---|---|", "| " + " | ".join(str(v) for v in columns.values()) + " |", "",
             "All candidate cases below are synthetic offline checks, not qualified implementations.",
             "Missing size definitions, refresh times or coverage make product rows incomparable.",
             "Observable agreement cannot recover proprietary algorithms or establish outcome quality.", ""]
    for result in candidates:
        lines.append(f"- {result['case_id']}: {result['result']['state']}")
    if comparison.get("non_identifiability"):
        lines.extend(["", "Non-identifiable candidates: " + json.dumps(comparison["non_identifiability"])])
    return {"manifest": manifest, "observations": imported, "candidate_results": candidates,
            "comparison": comparison, "evidence_classes": columns, "report_markdown": "\n".join(lines)+"\n"}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_report(json.loads(args.input.read_text()))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, key in (("manifest.json", "manifest"), ("observations.json", "observations"),
                      ("candidate-results.json", "candidate_results"), ("matched-comparison.json", "comparison")):
        (args.output_dir/name).write_text(json.dumps(result[key], indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    (args.output_dir/"report.md").write_text(result["report_markdown"])
    print(json.dumps({"state": "offline_report_written", "product_observations": result["observations"]["state"], "qualified": False}))


if __name__ == "__main__":
    main()
