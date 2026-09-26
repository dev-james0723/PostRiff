"""Golden set: parse, validate and evaluate the creator-labelled rows (growth Phase 0).

The CSV follows docs/design/growth-phase0/golden-template.csv and LABELING-GUIDE.md: one row per post or draft,
nine dimension columns with levels 1..4 (blank = cannot judge). Levels are loaded as 0..3. The labels are the
creator's; this module never invents, imputes or smooths them.

    python -m postriff_phase2.growth.golden validate FILE   # problems with row numbers, exit 1 on any

`evaluate` compares Post Doctor levels against the labels per dimension, overall and per language group
(Traditional Chinese and English are always reported separately), and fits per-language thresholds with
deterministic k-fold cross-validation.

Assumptions (reversible, documented in CONTRACTS):
- Language groups: zh-HK / zh-TW / zh-MO / zh-Hant* -> "zh-Hant"; en* -> "en"; any other tag is its own group.
- ECE for "level >= strong": `ece_strong_raw` uses the dimension score as the forecast; the acceptance metric
  `ece_cv` is the *calibrated* ECE: an isotonic map score -> P(label >= strong) fitted on the training folds and
  applied to the held-out fold, pooled over folds.
- A language's dimension is accepted (plan targets) when it has >= ACCEPTANCE["min_rows"] scored rows, cross-validated
  kappa >= 0.6 and calibrated ECE <= 0.08. `calibration_profile` records only accepted fits as usable.
- Folds are assigned by sha256(id) so they do not depend on file order.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass

from . import calibration
from .lang import lang_group  # noqa: F401 - re-exported for callers of golden.lang_group
from .post_doctor import PROFILE_VERSION, levels_from_judgment, validate_profile

DIMENSIONS = ("hook", "audience", "novelty", "specificity", "shareability", "conversation", "clarity", "emotion",
              "evidence")
REQUIRED = ("id", "platform", "lang", "kind", "text", *DIMENSIONS)
OPTIONAL = ("better_than", "notes")
PLATFORMS = ("threads", "instagram", "x", "linkedin", "facebook", "youtube", "tiktok", "other")
KINDS = ("post", "draft")
LEVELS = 4
STRONG = 2                       # 0-based index of "strong"
TARGET_ROWS = 200
ACCEPTANCE = {"kappa": 0.6, "ece": 0.08, "min_rows": 30}   # plan v3 Phase 0 targets; min_rows is our floor
LATENCY_TARGET_MS = 1500                                    # plan v3: Post Doctor p95 <= 1.5 s
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class Row:
    line: int                    # 1-based line in the file (header is line 1)
    id: str
    platform: str
    lang: str
    kind: str
    text: str
    labels: dict                 # dimension -> 0..3 or None
    better_than: str | None
    notes: str


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        return header, [(reader.line_num, record) for record in reader]


def parse(path):
    """(rows, problems, warnings). A row with any problem is omitted from rows."""
    header, records = _read(path)
    problems, warnings, rows = [], [], []
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        return [], [(1, f"missing columns: {', '.join(missing)}")], []
    extra = [c for c in header if c not in REQUIRED + OPTIONAL]
    if extra:
        warnings.append((1, f"ignored columns: {', '.join(extra)}"))
    seen = {}
    for line, record in records:
        before = len(problems)
        get = lambda k: (record.get(k) or "").strip()
        rid = get("id")
        if not _ID.match(rid):
            problems.append((line, "id must be 1-64 letters, digits or _ . : -"))
        elif rid in seen:
            problems.append((line, f"duplicate id {rid!r} (first on line {seen[rid]})"))
        else:
            seen[rid] = line
        if get("platform").lower() not in PLATFORMS:
            problems.append((line, f"platform must be one of {', '.join(PLATFORMS)}"))
        if not _LANG.match(get("lang")):
            problems.append((line, "lang must be a BCP 47 tag such as zh-HK or en"))
        if get("kind").lower() not in KINDS:
            problems.append((line, "kind must be post or draft"))
        if not get("text"):
            problems.append((line, "text is empty"))
        labels = {}
        for dim in DIMENSIONS:
            raw = get(dim)
            if raw == "":
                labels[dim] = None
            elif raw in ("1", "2", "3", "4"):
                labels[dim] = int(raw) - 1
            else:
                problems.append((line, f"{dim} must be 1-4 or blank, got {raw!r}"))
        if labels and all(v is None for v in labels.values()) and len(labels) == len(DIMENSIONS):
            problems.append((line, "no dimension labelled"))
        if len(problems) == before:
            rows.append(Row(line, rid, get("platform").lower(), get("lang"), get("kind").lower(), get("text"), labels,
                            get("better_than") or None, get("notes")))
    ids = {r.id for r in rows} | set(seen)
    for row in rows:
        if row.better_than is not None and (row.better_than == row.id or row.better_than not in ids):
            problems.append((row.line, f"better_than {row.better_than!r} is not another row's id"))
    bad = {line for line, _ in problems}
    rows = [r for r in rows if r.line not in bad]
    if len(rows) < TARGET_ROWS:
        warnings.append((0, f"{len(rows)} valid rows; the plan needs about {TARGET_ROWS}"))
    groups = {}
    for r in rows:
        groups[lang_group(r.lang)] = groups.get(lang_group(r.lang), 0) + 1
    for group in ("zh-Hant", "en"):
        if groups.get(group, 0) == 0:
            warnings.append((0, f"no {group} rows; that language cannot be calibrated"))
    return rows, sorted(problems), warnings


def load(path):
    """Valid rows; raises ValueError listing every problem when the file has any."""
    rows, problems, _ = parse(path)
    if problems:
        raise ValueError("; ".join(f"line {line}: {msg}" for line, msg in problems))
    return rows


def _fold(row_id, folds):
    return int(hashlib.sha256(row_id.encode("utf-8")).hexdigest(), 16) % folds


def _kappa(pred, gold):
    if not pred:
        return None
    return calibration.quadratic_weighted_kappa(pred, gold, LEVELS)


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(q * len(ordered)) - 1)
    return ordered[rank]


def _cv(pairs, folds):
    """Cross-validated kappa, calibrated ECE and full-data thresholds for [(row_id, score, label)]."""
    empty = {"n": len(pairs), "thresholds": None, "kappa_fit": None, "kappa_cv": None, "ece_cv": None, "isotonic": None}
    if len(pairs) < folds * 2 or len({label for _, _, label in pairs}) < 2:
        return {**empty, "reason": "too_few"}
    predicted, gold, forecasts, outcomes = [], [], [], []
    for k in range(folds):
        train = [(s, l) for rid, s, l in pairs if _fold(rid, folds) != k]
        test = [(s, l) for rid, s, l in pairs if _fold(rid, folds) == k]
        if not test or len({l for _, l in train}) < 2:
            continue
        fit = calibration.fit_thresholds([s for s, _ in train], [l for _, l in train], LEVELS)
        predicted += [calibration.to_level(s, fit["thresholds"]) for s, _ in test]
        gold += [l for _, l in test]
        iso = calibration.isotonic_fit([s for s, _ in train], [int(l >= STRONG) for _, l in train])
        forecasts += [calibration.isotonic_apply(iso, s) for s, _ in test]
        outcomes += [int(l >= STRONG) for _, l in test]
    full = calibration.fit_thresholds([s for _, s, _ in pairs], [l for _, _, l in pairs], LEVELS)
    # The deployed calibrator: the same isotonic map, fitted on all rows. ece_cv is its cross-validated estimate.
    iso = calibration.isotonic_fit([s for _, s, _ in pairs], [int(l >= STRONG) for _, _, l in pairs])
    return {"n": len(pairs), "thresholds": full["thresholds"], "kappa_fit": full["kappa"], "kappa_cv": _kappa(predicted, gold),
            "ece_cv": calibration.expected_calibration_error(forecasts, outcomes) if forecasts else None, "isotonic": iso,
            "reason": None}


def evaluate(rows, judgments_by_id, qs, *, folds=5):
    """Report dict: per-dimension agreement, calibration and threshold fits; abstention, latency and cost."""
    per_dim = {}
    levels_by_id = {}
    for row in rows:
        judgment = judgments_by_id.get(row.id)
        if judgment is not None:
            levels_by_id[row.id] = {d.id: d for d in levels_from_judgment(qs, judgment)}
    for dim in DIMENSIONS:
        labelled = [r for r in rows if r.labels.get(dim) is not None]
        scored = [(r, levels_by_id[r.id][dim]) for r in labelled if r.id in levels_by_id and dim in levels_by_id[r.id]]
        usable = [(r, d) for r, d in scored if d.level is not None]
        groups = {}
        for r, d in usable:
            groups.setdefault(lang_group(r.lang), []).append((r, d))
        by_lang = {}
        for group, items in sorted(groups.items()):
            by_lang[group] = {
                "n": len(items),
                "kappa": _kappa([d.level for _, d in items], [r.labels[dim] for r, _ in items]),
                "fit": _cv([(r.id, d.score, r.labels[dim]) for r, d in items], folds),
            }
        per_dim[dim] = {
            "labelled": len(labelled),
            "scored": len(usable),
            "abstained": len(scored) - len(usable),
            "missing_judgment": len(labelled) - len(scored),
            "kappa": _kappa([d.level for _, d in usable], [r.labels[dim] for r, _ in usable]),
            "ece_strong_raw": calibration.expected_calibration_error(
                [d.score for _, d in usable], [int(r.labels[dim] >= STRONG) for r, _ in usable]) if usable else None,
            "by_lang": by_lang,
        }
    judged = [judgments_by_id[r.id] for r in rows if r.id in judgments_by_id]
    asked = sum(len(qs.names) for _ in judged)
    usable_answers = sum(1 for j in judged for a in j.answers.values() if not a.abstained)
    fresh = [j for j in judged if not getattr(j, "cached", False)]
    known = [j.cost_usd for j in fresh if j.cost_usd is not None]
    # What the person waited: end-to-end (retries, fallbacks, timeouts included) where the router measured it.
    waits = [j.elapsed_ms if getattr(j, "elapsed_ms", None) is not None else j.latency_ms for j in fresh]
    return {
        "question_set": qs.key,
        "digest": qs.digest,
        "rows": len(rows),
        "judged": len(judged),
        "dimensions": per_dim,
        "question_abstain_rate": None if not asked else round(1 - usable_answers / asked, 4),
        "latency_ms": {"p50": _percentile(waits, 0.5), "p95": _percentile(waits, 0.95)},
        "served_models": sorted({j.model for j in judged if getattr(j, "status", "ok") == "ok"}),
        "cost_usd": {"known": round(sum(known), 6), "unknown_calls": len(fresh) - len(known)},
    }


def calibration_profile(result, *, model, acceptance=None):
    """Post Doctor calibration profile from one model's `evaluate` result.

    Per language group and dimension it records the fitted thresholds, the isotonic calibrator and the evidence,
    and marks the fit `accepted` only when it meets the targets. Post Doctor applies accepted fits only, only in
    their own language, only to judgments from the model that actually served the golden run, and only while the
    question-set digest still matches. `model` is the requested model; the profile records the served one."""
    acceptance = {**ACCEPTANCE, **(acceptance or {})}
    served = result.get("served_models") or []
    if len(served) != 1:
        raise ValueError(f"requested {model} but the golden run was served by {served or 'no model'}; one served model is required")
    languages = {}
    for dim, info in result["dimensions"].items():
        for group, entry in info["by_lang"].items():
            fit = entry["fit"]
            reasons = []
            if fit["reason"] or fit["n"] < acceptance["min_rows"]:
                reasons.append("too_few")
            if fit["kappa_cv"] is None or fit["kappa_cv"] < acceptance["kappa"]:
                reasons.append("kappa_below_target")
            if fit["ece_cv"] is None or fit["ece_cv"] > acceptance["ece"]:
                reasons.append("ece_above_target")
            languages.setdefault(group, {})[dim] = {
                "thresholds": fit["thresholds"], "isotonic": fit.get("isotonic"), "n": fit["n"], "kappa_cv": fit["kappa_cv"],
                "ece_cv": fit["ece_cv"], "accepted": not reasons, "reasons": reasons}
    return {"version": PROFILE_VERSION, "question_set": result["question_set"], "digest": result["digest"], "model": served[0],
            "requested_model": model,
            "acceptance": acceptance, "latency": _latency(result.get("latency_ms")), "languages": languages}


def _latency(measured):
    p95 = (measured or {}).get("p95")
    return {**(measured or {}), "target_p95_ms": LATENCY_TARGET_MS, "met": None if p95 is None else p95 <= LATENCY_TARGET_MS}


def load_profile(path, qs):
    """A profile file for this question set, or ValueError. A digest mismatch means the rubric changed: recalibrate."""
    with open(path, encoding="utf-8") as handle:
        profile = json.load(handle)
    validate_profile(profile, qs)
    return profile


def main(argv=None, out=sys.stdout):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 6 and argv[0] == "profile" and argv[2] == "--model" and argv[4] == "--out":
        with open(argv[1], encoding="utf-8") as handle:
            report = json.load(handle)
        result = (report.get("results") or {}).get(argv[3])
        if result is None:
            print(f"no results for model {argv[3]!r} in {argv[1]}", file=out)
            return 2
        try:
            profile = calibration_profile(result, model=argv[3])
        except ValueError as error:
            print(f"error: {error}", file=out)
            return 2
        with open(argv[5], "w", encoding="utf-8") as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2)
        for group, dims in sorted(profile["languages"].items()):
            accepted = sorted(d for d, e in dims.items() if e["accepted"])
            print(f"{group}: {len(accepted)}/{len(dims)} dimensions meet the targets", file=out)
        return 0
    if len(argv) != 2 or argv[0] != "validate":
        print("usage: python -m postriff_phase2.growth.golden validate FILE\n"
              "       python -m postriff_phase2.growth.golden profile REPORT.json --model MODEL --out PROFILE.json", file=out)
        return 2
    rows, problems, warnings = parse(argv[1])
    for line, message in problems:
        print(f"line {line}: {message}", file=out)
    for line, message in warnings:
        print(f"warning{f' line {line}' if line else ''}: {message}", file=out)
    print(f"{len(rows)} valid rows, {len(problems)} problems", file=out)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
