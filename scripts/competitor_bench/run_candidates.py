"""Independent public-method candidate detectors; no competitor internals claimed."""
from math import sqrt, isfinite
from statistics import median, mean, variance

CANDIDATE_VERSIONS = {k: "1" for k in ("robust_mad", "ewma", "cusum", "count_residual", "rate_changes")}


def run_candidates(payload):
    rows = payload.get("observations", [])
    if not isinstance(rows, list) or not 2 <= len(rows) <= 10000:
        raise ValueError("2..10000 normalized observations required")
    for row in rows:
        for field in ("count", "exposure_hours"):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError("finite nonnegative count/exposure required")
        if not row["exposure_hours"]:
            raise ValueError("positive exposure required")
        if int(row["count"]) != row["count"]:
            raise ValueError("count models require integer observations")
        if row.get("complete") is not True or row.get("coverage_epoch") != rows[0].get("coverage_epoch"):
            return {"state": "incomparable", "reason": "outage_or_coverage_change", "candidates": {}, "qualification": "unqualified"}
    rates = [r["count"] / r["exposure_hours"] for r in rows]
    past, current = rates[:-1], rates[-1]
    center = median(past)
    mad = median(abs(v-center) for v in past)
    robust = (current-center)/(1.4826*mad) if mad else None
    alpha = payload.get("alpha", 0.3)
    if not 0 < alpha <= 1:
        raise ValueError("alpha outside (0, 1]")
    level = past[0]
    for value in past[1:]:
        level = alpha*value + (1-alpha)*level
    sigma = sqrt(variance(past)) if len(past) > 1 else 0
    scale = max(sigma, 1.0)
    drift = payload.get("cusum_drift", 0.5)
    threshold = payload.get("cusum_threshold", 5.0)
    if not isfinite(drift) or drift < 0 or not isfinite(threshold) or threshold <= 0:
        raise ValueError("invalid CUSUM parameters")
    positive = negative = 0.0
    warmup = payload.get("cusum_warmup", max(1, min(5, len(rates)//2)))
    if not isinstance(warmup, int) or not 1 <= warmup < len(rates):
        raise ValueError("invalid CUSUM warmup")
    baseline_mean = mean(rates[:warmup])
    cusum_scale = max(sqrt(variance(rates[:warmup])) if warmup > 1 else 0, 1.0)
    cusum_path = []
    for value in rates[warmup:]:
        z = (value-baseline_mean)/cusum_scale
        positive = max(0.0, positive + z-drift)
        negative = min(0.0, negative + z+drift)
        cusum_path.append({"positive": positive, "negative": negative})
    expected_rate = sum(r["count"] for r in rows[:-1])/sum(r["exposure_hours"] for r in rows[:-1])
    expected = expected_rate*rows[-1]["exposure_hours"]
    # Exposure-aware dispersion estimate of baseline Pearson residuals.
    dispersion = sum((r["count"]-expected_rate*r["exposure_hours"])**2/max(expected_rate*r["exposure_hours"], 1e-12)
                     for r in rows[:-1])/max(1, len(past)-1)
    count_model = "negative_binomial" if dispersion > 1.5 else "poisson"
    nb_alpha = max(0.0, (dispersion-1)/max(expected, 1e-12)) if count_model == "negative_binomial" else 0.0
    residual = (rows[-1]["count"]-expected)/sqrt(expected+nb_alpha*expected**2) if expected > 0 else None
    creators = rows[-1].get("creator_counts", {})
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in creators.values()):
        raise ValueError("creator counts must be nonnegative integers")
    creator_total = sum(creators.values())
    if creator_total > rows[-1]["count"]:
        raise ValueError("known creator counts exceed original observations")
    author_coverage = creator_total/rows[-1]["count"] if rows[-1]["count"] else None
    creator_share = max(creators.values())/creator_total if creator_total else None
    candidates = {
        "robust_mad": {"value": robust, "state": "available" if mad else "abstained", "reason": None if mad else "zero_mad_no_division", "threshold": 3.0},
        "ewma": {"value": current-level, "baseline": level, "alpha": alpha, "threshold": 3*scale},
        "cusum": {"value": positive, "negative": negative, "threshold": threshold, "drift": drift, "warmup_count": warmup, "path": cusum_path},
        "count_residual": {"value": residual, "expected": expected, "dispersion": dispersion, "model": count_model, "nb_alpha": nb_alpha,
                           "state": "available" if expected else "abstained", "reason": None if expected else "zero_baseline", "threshold": 3.0},
        "rate_changes": {"value": current, "velocity": current-past[-1], "acceleration": current-2*past[-1]+past[-2] if len(past)>1 else None}}
    return {"state": "implemented", "candidates": candidates, "candidate_versions": CANDIDATE_VERSIONS,
            "largest_known_creator_share": creator_share, "author_coverage": author_coverage,
            "concentration_gate": "blocked" if creator_share and creator_share > 0.35 else "unknown" if author_coverage is None or author_coverage < .8 else "passed",
            "qualification": "unqualified", "units": "observed_count_per_exposure_hour", "proprietary_formula_recovered": False}
