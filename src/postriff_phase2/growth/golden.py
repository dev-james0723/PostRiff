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
- ECE for "level >= strong" uses the dimension score (weighted mean of answer probabilities) as the forecast
  and label >= strong as the outcome.
- Folds are assigned by sha256(id) so they do not depend on file order.
"""
from __future__ import annotations

import csv
import hashlib
import math
import re
import sys
from dataclasses import dataclass

from . import calibration
from .post_doctor import levels_from_judgment

DIMENSIONS = ("hook", "audience", "novelty", "specificity", "shareability", "conversation", "clarity", "emotion",
              "evidence")
REQUIRED = ("id", "platform", "lang", "kind", "text", *DIMENSIONS)
OPTIONAL = ("better_than", "notes")
PLATFORMS = ("threads", "instagram", "x", "linkedin", "facebook", "youtube", "tiktok", "other")
KINDS = ("post", "draft")
LEVELS = 4
STRONG = 2                       # 0-based index of "strong"
TARGET_ROWS = 200
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_HANT = ("zh-hk", "zh-tw", "zh-mo")


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


def lang_group(lang):
    tag = (lang or "").strip().lower()
    if tag in _HANT or tag.startswith("zh-hant"):
        return "zh-Hant"
    if tag == "en" or tag.startswith("en-"):
        return "en"
    return lang or "unknown"


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
    """Cross-validated kappa and full-data thresholds for [(row_id, score, label)]."""
    if len(pairs) < folds * 2 or len({label for _, _, label in pairs}) < 2:
        return {"n": len(pairs), "thresholds": None, "kappa_fit": None, "kappa_cv": None, "reason": "too_few"}
    predicted, gold = [], []
    for k in range(folds):
        train = [(s, l) for rid, s, l in pairs if _fold(rid, folds) != k]
        test = [(s, l) for rid, s, l in pairs if _fold(rid, folds) == k]
        if not test or len({l for _, l in train}) < 2:
            continue
        fit = calibration.fit_thresholds([s for s, _ in train], [l for _, l in train], LEVELS)
        predicted += [calibration.to_level(s, fit["thresholds"]) for s, _ in test]
        gold += [l for _, l in test]
    full = calibration.fit_thresholds([s for _, s, _ in pairs], [l for _, _, l in pairs], LEVELS)
    return {"n": len(pairs), "thresholds": full["thresholds"], "kappa_fit": full["kappa"],
            "kappa_cv": _kappa(predicted, gold), "reason": None}


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
            "ece_strong": calibration.expected_calibration_error(
                [d.score for _, d in usable], [int(r.labels[dim] >= STRONG) for r, _ in usable]) if usable else None,
            "by_lang": by_lang,
        }
    judged = [judgments_by_id[r.id] for r in rows if r.id in judgments_by_id]
    asked = sum(len(qs.names) for _ in judged)
    usable_answers = sum(1 for j in judged for a in j.answers.values() if not a.abstained)
    fresh = [j for j in judged if not getattr(j, "cached", False)]
    known = [j.cost_usd for j in fresh if j.cost_usd is not None]
    return {
        "question_set": qs.key,
        "rows": len(rows),
        "judged": len(judged),
        "dimensions": per_dim,
        "question_abstain_rate": None if not asked else round(1 - usable_answers / asked, 4),
        "latency_ms": {"p50": _percentile([j.latency_ms for j in fresh], 0.5),
                       "p95": _percentile([j.latency_ms for j in fresh], 0.95)},
        "cost_usd": {"known": round(sum(known), 6), "unknown_calls": len(fresh) - len(known)},
    }


def main(argv=None, out=sys.stdout):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "validate":
        print("usage: python -m postriff_phase2.growth.golden validate FILE", file=out)
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
