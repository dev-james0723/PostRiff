"""Bounded sampled-count forecasts and replayable, fail-closed qualification.

This module performs local arithmetic only. The caller owns evidence provenance,
current rights adaptation and reviewed preregistration; hashes bind content, not
the authenticity of those external attestations.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from statistics import mean
import random
from .context import bounded, digest, envelope, finite, source_index, stored_projection, supported, timestamp

VERSION = "forecast_v2"
CANDIDATE = "local_linear_count"
FEATURE_VERSION = "stable_sample_bins_v1"
MAX_RESIDUALS = 512
MAX_ROLLING_WORK = 1_000_000
PREREGISTERED_FIELDS = ("preregistered_at", "holdout_opened_at", "target_digest", "method_digest",
                       "evaluation_plan_digest", "primary_loss", "min_episodes", "min_pairs", "coverage_tolerance")


def preregistration_digest(gate):
    """Content binding for the caller's separately reviewed preregistration."""
    return digest({k: gate[k] for k in PREREGISTERED_FIELDS})


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("integer outside forecast bound")
    return value


def _bundle(payload):
    return {"version": VERSION, "feature_version": FEATURE_VERSION,
            "methods": {"last_value": "1", "seasonal_naive": "1", CANDIDATE: "1"},
            "seasonal_period": _integer(payload.get("seasonal_period", 24), 1, 168),
            "trend_window": _integer(payload.get("trend_window", 24), 6, 168),
            "embargo_hours": finite(payload.get("embargo_hours", 0), minimum=0),
            "residual_window": {"last_value": 10_000, "seasonal_naive": 10_000, CANDIDATE: MAX_RESIDUALS}}


def _seal(result, field):
    result[field] = digest({k: v for k, v in result.items() if k != field})
    return result


def _intact(result, field):
    return result.get(field) == digest({k: v for k, v in result.items() if k != field})


def _recipe(payload):
    """Bounded reproducibility inputs; never copy source text into the artifact."""
    keys = ("scope_key", "decision_cutoff", "target", "history", "fixture", "target_start",
            "seasonal_period", "trend_window", "embargo_hours", "structural_break",
            "excluded_training_episode_ids", "holdout_episode_ids", "holdout_group_ids", "origins")
    result = deepcopy({k: payload[k] for k in keys if k in payload})
    if "history" in result:
        result["history"] = sorted(bounded(result["history"]), key=lambda r: (timestamp(r["window_start"]), digest(r)))
    for key in ("holdout_episode_ids", "excluded_training_episode_ids", "holdout_group_ids"):
        if key in result:
            result[key] = sorted(set(bounded(result[key], 1000)))
    if "origins" in result:
        result["origins"] = sorted(timestamp(o).isoformat() for o in bounded(result["origins"], 1000))
    return result


def _quantile(values, q):
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low)


def _target(payload):
    target = payload["target"]
    if target.get("population") != "observed_sample" or not all(target.get(k) for k in ("frame_id", "cohort", "metric_definition")):
        raise ValueError("explicit observed-sample target/frame/cohort required")
    horizon = target.get("horizon_steps")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 168:
        raise ValueError("horizon_steps outside bound")
    finite(target["bin_hours"], minimum=0.001)
    if finite(target.get("supported_horizon_hours", 0), minimum=0) < horizon * target["bin_hours"]:
        raise ValueError("horizon exceeds measurement/retention support")
    return target


def _history(payload, training_cutoff):
    target = _target(payload)
    sources = source_index({**payload, "decision_cutoff": training_cutoff.isoformat()})
    rows, keys = [], set()
    for row in bounded(payload.get("history", [])):
        if (row.get("frame_id") != target["frame_id"] or row.get("metric_definition") != target["metric_definition"]
                or row.get("cohort", target["cohort"]) != target["cohort"]
                or row.get("feature_version", FEATURE_VERSION) != FEATURE_VERSION
                or row.get("complete") is not True or row.get("coverage") != "stable"
                or row.get("episode_id") in payload.get("excluded_training_episode_ids", [])
                or (row.get("group_id") is not None and row["group_id"] in payload.get("holdout_group_ids", []))
                or not supported(row, sources, training_cutoff)):
            continue
        start, end = timestamp(row["window_start"]), timestamp(row["window_end"])
        if end > training_cutoff or end - start != timedelta(hours=target["bin_hours"]):
            continue
        key = (start, end)
        if key in keys:
            raise ValueError("duplicate forecast bin")
        keys.add(key)
        finite(row["value"], minimum=0)
        rows.append(row)
    return sorted(rows, key=lambda r: timestamp(r["window_end"]))


def _predict(payload, methods):
    target = _target(payload)
    issued = timestamp(payload["decision_cutoff"])
    target_start = timestamp(payload.get("target_start", payload["decision_cutoff"]))
    if target_start < issued:
        raise ValueError("forecast target cannot precede issuance")
    embargo = finite(payload.get("embargo_hours", 0), minimum=0)
    train_cutoff = issued - timedelta(hours=embargo)
    rows = _history(payload, train_cutoff)
    h = target["horizon_steps"]
    bundle = _bundle(payload)
    period = bundle["seasonal_period"]
    values = [r["value"] for r in rows]
    contiguous = all(timestamp(a["window_end"]) == timestamp(b["window_start"]) for a, b in zip(rows, rows[1:]))
    gap = (target_start - timestamp(rows[-1]["window_end"])).total_seconds() / (3600 * target["bin_hours"]) if rows else 0
    if gap != int(gap):
        raise ValueError("issuance must align with the declared sampling grid")
    gap = int(gap)
    predictions = []
    for method in methods:
        minimum = {"last_value": 1, "seasonal_naive": period, CANDIDATE: 6}[method]
        if len(values) < minimum or not contiguous or (method == CANDIDATE and gap > 168) or payload.get("structural_break") is True:
            predictions.append({"method": method, "state": "unavailable", "point": None, "quantiles": None,
                                "reason": "insufficient_or_discontinuous_training"})
            continue
        def point_at(sequence):
            if method == "last_value":
                return sequence[-1] * h
            if method == "seasonal_naive":
                return sum(sequence[-period + ((gap+i) % period)] for i in range(h))
            # OLS on a fixed trailing window, clipped to nonnegative counts.
            # No holdout-selected hyperparameters or future residuals enter here.
            sequence = sequence[-bundle["trend_window"]:]
            n = len(sequence)
            center = (n - 1) / 2
            average = mean(sequence)
            slope = sum((i-center)*(v-average) for i, v in enumerate(sequence)) / sum((i-center)**2 for i in range(n))
            return sum(max(0.0, average + slope * (n + gap + i - center)) for i in range(h))
        point = point_at(values)
        stop = len(values)-gap-h+1
        window = max(period, bundle["trend_window"])
        residuals = [sum(values[i+gap:i+gap+h]) - point_at(values[max(0, i-window):i])
                     for i in range(max(minimum, stop-bundle["residual_window"][method]), stop)]
        quantiles = {str(q): max(0.0, point + _quantile(residuals, q)) for q in (0.1, 0.5, 0.9)} if len(residuals) >= 5 else None
        predictions.append({"method": method, "state": "experimental", "point": point, "quantiles": quantiles,
                            "interval_basis": "past_rolling_residuals" if quantiles else "insufficient_past_residuals",
                            "residual_count": len(residuals)})
    result = envelope(payload, method_version=VERSION, method_bundle=bundle, target=deepcopy(target), issued_at=payload["decision_cutoff"],
                    target_start=target_start.isoformat(),
                    horizon_end=(target_start+timedelta(hours=h*target["bin_hours"])).isoformat(),
                    training_cutoff=train_cutoff.isoformat(), embargo_hours=embargo,
                    training_input_digest=digest(rows), predictions=predictions,
                    evidence_refs=sorted({ref for row in rows for ref in row["evidence_refs"]}),
                    coverage="stable" if rows and contiguous else "unavailable",
                    structural_break=payload.get("structural_break") is True,
                    fixture=payload.get("fixture", True),
                    forecast_wording_enabled=False, qualification="unqualified", execution_state="offline")
    return _seal(result, "prediction_digest")


def predict_baselines(payload):
    """Compatibility API: exactly the two simple baselines."""
    return _predict(payload, ("last_value", "seasonal_naive"))


def predict_candidates(payload):
    """Two baselines plus executable bounded local-linear count regression."""
    result = _predict(payload, ("last_value", "seasonal_naive", CANDIDATE))
    result["prediction_recipe"] = _recipe({**payload, "history": _history(payload, timestamp(result["training_cutoff"]))})
    return _seal(result, "prediction_digest")


def evaluate_forecasts(payload):
    """Evaluate explicit forecast/outcome pairs; late/missing/revoked targets censor."""
    cutoff = timestamp(payload["decision_cutoff"])
    target = _target(payload)
    sources = source_index(payload)
    groups, censored, seen, retained_refs, labels = defaultdict(list), 0, set(), set(), {}
    pairs = sorted(bounded(payload.get("pairs", [])), key=lambda r: (r["prediction_id"], r["method"]))
    for row in pairs:
        key = (row["prediction_id"], row["method"])
        if key in seen:
            raise ValueError("duplicate forecast evaluation pair")
        seen.add(key)
        issued, train = timestamp(row["issued_at"]), timestamp(row["training_cutoff"])
        if train > issued - timedelta(hours=finite(row.get("embargo_hours", 0), minimum=0)):
            raise ValueError("training violates embargo")
        if issued > cutoff:
            raise ValueError("future forecast issuance")
        start = timestamp(row.get("target_start", row["issued_at"]))
        if (row.get("frame_id") != target["frame_id"] or start < issued
                or timestamp(row["horizon_end"]) - start != timedelta(hours=target["bin_hours"]*target["horizon_steps"])
                or row.get("cohort", target["cohort"]) != target["cohort"]
                or row.get("metric_definition", target["metric_definition"]) != target["metric_definition"]):
            raise ValueError("forecast target/frame/horizon mismatch")
        outcome = row.get("outcome") or {}
        label = digest({"outcome": outcome, "episode_id": row["episode_id"], "issued_at": row["issued_at"],
                        "training_cutoff": row["training_cutoff"], "target_start": start.isoformat(), "horizon_end": row["horizon_end"]})
        if row["prediction_id"] in labels and labels[row["prediction_id"]] != label:
            raise ValueError("paired forecasts disagree on outcome or episode")
        labels[row["prediction_id"]] = label
        if (not supported(outcome, sources, cutoff) or outcome.get("complete") is not True
                or timestamp(row["horizon_end"]) > cutoff or outcome.get("value") is None
                or outcome.get("frame_id") != row.get("frame_id")
                or outcome.get("cohort", target["cohort"]) != target["cohort"]
                or outcome.get("metric_definition", target["metric_definition"]) != target["metric_definition"]
                or timestamp(outcome["available_at"]) < timestamp(row["horizon_end"])):
            censored += 1
            continue
        y, point = finite(outcome["value"], minimum=0), finite(row["point"], minimum=0)
        retained_refs.update(outcome["evidence_refs"])
        loss = {"prediction_id": row["prediction_id"], "episode_id": row["episode_id"], "absolute_error": abs(y-point)}
        quantiles = row.get("quantiles")
        if quantiles:
            ordered = sorted((finite(float(q)), finite(v, minimum=0)) for q, v in quantiles.items())
            if len({q for q, _ in ordered}) != len(ordered) or any(not 0 < q < 1 for q, _ in ordered) or any(a[1] > b[1] for a, b in zip(ordered, ordered[1:])):
                raise ValueError("invalid or crossing quantiles")
            loss["quantile_loss"] = {str(q): max(q*(y-v), (q-1)*(y-v)) for q, v in ordered}
            if "0.1" in quantiles and "0.9" in quantiles:
                lo, hi = quantiles["0.1"], quantiles["0.9"]
                loss["interval_covered"], loss["interval_width"] = int(lo <= y <= hi), hi-lo
        groups[row["method"]].append(loss)
    metrics = {}
    for method, rows in groups.items():
        interval_rows = [r for r in rows if "interval_covered" in r]
        levels = sorted({q for r in rows for q in r.get("quantile_loss", {})})
        metrics[method] = {"count": len(rows), "mae": mean(r["absolute_error"] for r in rows),
                           "quantile_loss": {q: mean(r["quantile_loss"][q] for r in rows if q in r.get("quantile_loss", {})) for q in levels},
                           "interval_count": len(interval_rows),
                           "interval_coverage": mean(r["interval_covered"] for r in interval_rows) if interval_rows else None,
                           "sharpness": mean(r["interval_width"] for r in interval_rows) if interval_rows else None,
                           "nominal_coverage": 0.8}
    return _seal(envelope(payload, method_version=VERSION, metrics=metrics, losses=dict(groups), censored_count=censored,
                    qualification="unqualified", fixture=payload.get("fixture", True),
                    target_digest=digest(target), evidence_refs=sorted(retained_refs), dataset_digest=digest(pairs)), "report_digest")


def rolling_origin_evaluate(payload):
    target = _target(payload)
    cutoff = timestamp(payload["decision_cutoff"])
    holdout = set(bounded(payload.get("holdout_episode_ids", []), 1000))
    if not holdout or any(not isinstance(e, str) or not e for e in holdout):
        raise ValueError("explicit episode-separated holdout required")
    sources = source_index(payload)
    history = sorted(bounded(payload.get("history", [])), key=lambda r: timestamp(r["window_start"]))
    holdout_groups = set(bounded(payload.get("holdout_group_ids", []), 1000))
    if any(not isinstance(g, str) or not g for g in holdout_groups):
        raise ValueError("invalid holdout group")
    if any("group_id" in r for r in history) and (not holdout_groups or any(not r.get("group_id") for r in history)):
        raise ValueError("explicit complete group labels and held-out groups required")
    raw_origins = sorted(timestamp(o).isoformat() for o in bounded(payload.get("origins", []), 1000))
    if len(set(raw_origins)) != len(raw_origins) or len(raw_origins)*len(history) > MAX_ROLLING_WORK:
        raise ValueError("duplicate origins or rolling work bound exceeded")
    excluded = sorted(holdout | set(bounded(payload.get("excluded_training_episode_ids", []), 1000)))
    pairs, origins = [], []
    for raw_origin in raw_origins:
        origin = timestamp(raw_origin)
        if origin > cutoff:
            raise ValueError("future rolling origin")
        prediction = _predict({**payload, "decision_cutoff": raw_origin, "target_start": raw_origin,
                               "excluded_training_episode_ids": excluded}, ("last_value", "seasonal_naive", CANDIDATE))
        end = origin + timedelta(hours=target["bin_hours"] * target["horizon_steps"])
        future = [r for r in history if origin <= timestamp(r["window_start"]) and timestamp(r["window_end"]) <= end]
        complete = (len(future) == target["horizon_steps"] and all(r.get("episode_id") in holdout and
                    r.get("complete") is True and r.get("coverage") == "stable" and supported(r, sources, cutoff)
                    and r.get("frame_id") == target["frame_id"] and r.get("metric_definition") == target["metric_definition"]
                    and r.get("cohort", target["cohort"]) == target["cohort"]
                    and (not holdout_groups or r.get("group_id") in holdout_groups)
                    and r.get("feature_version", FEATURE_VERSION) == FEATURE_VERSION for r in future)
                    and len({r.get("episode_id") for r in future}) == 1
                    and all(timestamp(r["window_start"]) == origin + timedelta(hours=i*target["bin_hours"])
                            and timestamp(r["window_end"]) == origin + timedelta(hours=(i+1)*target["bin_hours"])
                            and timestamp(r["available_at"]) >= timestamp(r["window_end"]) for i, r in enumerate(future)))
        refs = sorted({ref for r in future for ref in r.get("evidence_refs", [])})
        outcome = {"complete": complete, "frame_id": target["frame_id"], "cohort": target["cohort"],
                   "metric_definition": target["metric_definition"], "value": sum(finite(r["value"], minimum=0) for r in future) if complete else None,
                   "available_at": max([r["available_at"] for r in future], key=timestamp) if future else raw_origin, "evidence_refs": refs}
        origins.append(prediction)
        for p in prediction["predictions"]:
            if p["point"] is None:
                continue
            pairs.append({**p, "prediction_id": raw_origin, "episode_id": future[0]["episode_id"] if future else "unknown",
                          "issued_at": raw_origin, "training_cutoff": prediction["training_cutoff"],
                          "embargo_hours": prediction["embargo_hours"], "frame_id": target["frame_id"], "horizon_end": end.isoformat(), "outcome": outcome})
    result = evaluate_forecasts({**payload, "pairs": pairs})
    result["origins"] = origins
    result["holdout_episode_ids"] = sorted(holdout)
    result["method_bundle"] = _bundle(payload)
    result["evaluation_recipe"] = _recipe(payload)
    result["cohort_labels_explicit"] = bool(history) and all(r.get("cohort") == target["cohort"] for r in history)
    result["evaluation_plan_digest"] = digest({"origins": raw_origins, "holdout_episode_ids": sorted(holdout),
                                              "holdout_group_ids": sorted(holdout_groups),
                                              "excluded_training_episode_ids": excluded,
                                              "target": target, "method_bundle": _bundle(payload)})
    result["evidence_refs"] = sorted(set(result["evidence_refs"]) | {r for o in origins for r in o["evidence_refs"]})
    return _seal(result, "report_digest")


def qualify_forecast(payload):
    """Replay a frozen evaluation, then apply caller-reviewed promotion gates.

Arbitrary manually supplied pair scores remain useful diagnostics, but cannot
qualify a method. Current source support is checked even for historical reports.
"""
    report, gate = payload.get("report", {}), payload.get("gate", {})
    reasons = []
    target = _target(payload)
    cutoff = timestamp(payload["decision_cutoff"])
    required = ("preregistered_at", "holdout_opened_at", "dataset_digest", "target_digest", "primary_loss", "min_episodes",
                "min_pairs", "coverage_tolerance", "reviewer", "operator_approved", "rights_verified", "reproducible",
                "method_digest", "evaluation_plan_digest", "report_digest", "preregistration_digest")
    if any(k not in gate for k in required):
        return envelope(payload, state="unqualified", reasons=["incomplete_preregistered_gate"], forecast_wording_enabled=False)
    if report.get("fixture") is not False:
        reasons.append("fixture_not_qualification")
    current_sources = source_index(payload)
    if not report.get("evidence_refs") or not set(report["evidence_refs"]) <= current_sources.keys():
        reasons.append("source_support_unavailable")
    if payload.get("enabled", True) is not True or payload.get("method_withdrawn") is True:
        reasons.append("method_or_feature_disabled")
    if not _intact(report, "report_digest") or gate["report_digest"] != report.get("report_digest"):
        reasons.append("evaluation_integrity_mismatch")
    if gate["preregistration_digest"] != preregistration_digest(gate):
        reasons.append("preregistration_binding_mismatch")
    if report.get("cohort_labels_explicit") is not True:
        reasons.append("explicit_cohort_labels_required")
    if not (timestamp(gate["preregistered_at"]) < timestamp(gate["holdout_opened_at"]) <= cutoff):
        reasons.append("preregistration_timing_invalid")
    if (gate["dataset_digest"] != report.get("dataset_digest") or gate["target_digest"] != digest(target)
            or report.get("target_digest") != digest(target) or report.get("scope_key") != payload["scope_key"]
            or timestamp(report["decision_cutoff"]) > cutoff):
        reasons.append("qualification_scope_mismatch")
    if (gate["primary_loss"] != "mae" or not isinstance(gate["reviewer"], str) or not gate["reviewer"].strip()
            or any(gate[k] is not True for k in ("operator_approved", "rights_verified", "reproducible"))):
        reasons.append("approval_rights_or_loss_gate")
    _integer(gate["min_episodes"], 2, 1000)
    _integer(gate["min_pairs"], 2, 1000)
    if not 0 <= finite(gate["coverage_tolerance"]) < 0.8:
        raise ValueError("invalid qualification minimums")
    bundle = _bundle(payload)
    candidate = payload.get("candidate_method", CANDIDATE)
    if (candidate != CANDIDATE or report.get("method_version") != VERSION
            or report.get("method_bundle") != bundle or gate["method_digest"] != digest(bundle)
            or gate["evaluation_plan_digest"] != report.get("evaluation_plan_digest")):
        reasons.append("qualification_method_mismatch")
    recipe = report.get("evaluation_recipe")
    replay = None
    if not isinstance(recipe, dict):
        reasons.append("executable_evaluation_required")
    elif not reasons:
        try:
            replay = rolling_origin_evaluate({**recipe, "sources": list(current_sources.values())})
            if replay["report_digest"] != report["report_digest"]:
                reasons.append("evaluation_replay_mismatch")
            opened = timestamp(gate["holdout_opened_at"])
            if not replay["origins"] or any(timestamp(o["issued_at"]) < opened for o in replay["origins"]):
                reasons.append("preregistration_timing_invalid")
        except (ValueError, TypeError, KeyError, OverflowError):
            reasons.append("evaluation_replay_unavailable")
    if reasons:
        return envelope(payload, method_version=VERSION, state="unqualified", reasons=sorted(set(reasons)), forecast_wording_enabled=False)
    losses = replay.get("losses", {})
    if any(not losses.get(m) for m in (candidate, "last_value", "seasonal_naive")):
        reasons.append("candidate_or_simple_baseline_missing")
        return envelope(payload, state="unqualified", reasons=reasons, forecast_wording_enabled=False)
    tables = {m: {r["prediction_id"]: r for r in losses[m]} for m in (candidate, "last_value", "seasonal_naive")}
    shared = set.intersection(*(set(t) for t in tables.values()))
    baseline = min(("last_value", "seasonal_naive"), key=lambda m: mean(tables[m][i]["absolute_error"] for i in shared)) if shared else "last_value"
    blocks = defaultdict(list)
    for i in sorted(shared):
        row = tables[candidate][i]
        blocks[row["episode_id"]].append(tables[baseline][i]["absolute_error"] - row["absolute_error"])
    interval = None
    if len(shared) < gate["min_pairs"] or len(blocks) < gate["min_episodes"]:
        reasons.append("insufficient_paired_episode_sample")
    else:
        units, draws, rng = [blocks[k] for k in sorted(blocks)], [], random.Random(0)
        for _ in range(1000):
            draws.append(mean(v for _ in units for v in rng.choice(units)))
        interval = {"lower": _quantile(draws, 0.025), "upper": _quantile(draws, 0.975),
                    "method": "paired_episode_block_bootstrap", "confidence_level": 0.95, "draws": 1000, "seed": 0}
        if interval["lower"] <= 0:
            reasons.append("improvement_interval_not_positive")
    candidate_rows = [tables[candidate][i] for i in sorted(shared)]
    interval_rows = [r for r in candidate_rows if "interval_covered" in r]
    if len(interval_rows) != len(candidate_rows) or not interval_rows or abs(mean(r["interval_covered"] for r in interval_rows) - 0.8) > gate["coverage_tolerance"]:
        reasons.append("interval_calibration_failed")
    return _seal(envelope(payload, method_version=VERSION, state="qualified" if not reasons else "unqualified", reasons=reasons,
                    candidate_method=candidate, method_bundle=bundle, target=deepcopy(target),
                    report_digest=report["report_digest"], dataset_digest=report["dataset_digest"],
                    evaluation_cutoff=report["decision_cutoff"], gate=deepcopy(gate), gate_digest=digest(gate),
                    evidence_refs=report["evidence_refs"], metrics=replay["metrics"],
                    paired_count=len(shared), episode_count=len(blocks), better_simple_baseline=baseline,
                    improvement_interval=interval, forecast_wording_enabled=not reasons), "qualification_digest")


def to_stored_projection(result, *, qualification_payload=None):
    """Recheck current evidence and replay before exposing qualified predictions.

The owner still binds this fragment to its receipt, manifest, method artifact,
retention and read-time policy graph. Never accept a cached `state=qualified`.
"""
    def unavailable(reason):
        return {**stored_projection("forecast", {"state": "unavailable", "reason": reason,
                 "predictions": [], "forecast_wording_enabled": False}), "method_version": VERSION}

    if qualification_payload is None:
        return unavailable("qualified_forecast_projection_required")
    try:
        current = qualification_payload
        qualified = qualify_forecast(current)
        if qualified["state"] != "qualified":
            return unavailable("qualification_failed")
        now = timestamp(current["decision_cutoff"])
        if (not _intact(result, "prediction_digest") or result.get("fixture") is not False
                or result.get("method_version") != VERSION or result.get("method_bundle") != qualified["method_bundle"]
                or result.get("scope_key") != qualified["scope_key"] or result.get("target") != qualified["target"]
                or not timestamp(qualified["evaluation_cutoff"]) <= timestamp(result["issued_at"]) <= now < timestamp(result["horizon_end"])):
            return unavailable("prediction_binding_mismatch")
        current_sources = source_index(current)
        if not result.get("evidence_refs") or not set(result["evidence_refs"]) <= current_sources.keys():
            return unavailable("source_support_unavailable")
        if any(r.get("cohort") != result["target"]["cohort"] for r in result["prediction_recipe"]["history"]):
            return unavailable("explicit_cohort_labels_required")
        if any(s.get("expires_at") and timestamp(s["expires_at"]) < timestamp(result["horizon_end"])
               for s in [s for ref, s in current_sources.items() if ref in result["evidence_refs"]]
               + result["prediction_recipe"]["history"]):
            return unavailable("horizon_exceeds_current_retention")
        replay = predict_candidates({**result["prediction_recipe"], "sources": list(current_sources.values())})
        if replay["prediction_digest"] != result["prediction_digest"]:
            return unavailable("prediction_replay_mismatch")
        chosen = next(p for p in replay["predictions"] if p["method"] == qualified["candidate_method"])
        if chosen["point"] is None or not chosen["quantiles"] or result["structural_break"] or result["coverage"] != "stable":
            return unavailable("prediction_support_unavailable")
    except (ValueError, TypeError, KeyError, OverflowError, StopIteration):
        return unavailable("qualification_or_prediction_invalid")
    wire = {k: deepcopy(result[k]) for k in ("scope_key", "target", "method_bundle", "issued_at", "training_cutoff",
            "target_start", "horizon_end", "embargo_hours", "coverage", "structural_break", "training_input_digest", "prediction_digest")}
    wire.update(state="qualified", forecast_wording_enabled=True,
                predictions=[{**chosen, "state": "qualified"}], uncertainty="predictive_interval",
                qualification={k: deepcopy(qualified[k]) for k in ("qualification_digest", "report_digest", "dataset_digest",
                    "evaluation_cutoff", "gate", "gate_digest", "paired_count", "episode_count", "better_simple_baseline", "improvement_interval", "metrics")})
    return {**stored_projection("forecast", wire), "method_version": VERSION}
