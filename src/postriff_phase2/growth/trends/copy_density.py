"""Five independent sample dimensions; assignment confidence is never prevalence."""
from collections import Counter, defaultdict
from copy import deepcopy
import random
from .context import bounded, canonical_key, creator_key, digest, envelope, source_index, stored_projection, supported, timestamp

DIMENSIONS = ("topic", "narrative", "hook", "format", "creator")


def _interval(rows, pattern, seed):
    if len(rows) > 1000:
        return None  # Larger bootstrap jobs require separate explicit admission.
    groups = defaultdict(list)
    for row in rows:
        if row[1] is None:
            return None
        groups[row[1]].append(row[0])
    if len(groups) < 2:
        return None
    rng, units, draws = random.Random(seed), list(groups.values()), []
    for _ in range(200):
        sample = [p for _ in units for p in rng.choice(units)]
        draws.append(sample.count(pattern) / len(sample))
    draws.sort()
    return {"lower": draws[4], "upper": draws[194], "method": "creator_block_percentile_200", "level": 0.95}


def measure_saturation(payload):
    measured = source_index(payload, originals=True)
    creative = source_index(payload, "creative", originals=True)
    cutoff = timestamp(payload["decision_cutoff"])
    frame = payload["frame"]
    for field in ("frame_id", "platform", "language", "window_start", "window_end", "acquisition_policy", "classifier_version"):
        if not frame.get(field):
            raise ValueError("missing frame field: " + field)
    start, end = timestamp(frame["window_start"]), timestamp(frame["window_end"])
    if start >= end or end > cutoff:
        raise ValueError("invalid sampling window")
    originals, by_id = {}, {}
    for sid, row in measured.items():
        if not start <= timestamp(row["event_at"]) < end or row["platform"] != frame["platform"] or row.get("language") != frame["language"]:
            continue
        key = canonical_key(row)
        by_id[sid] = key
        originals.setdefault(key, row)
    n = len(originals)
    assignments = {d: {} for d in DIMENSIONS}
    for row in bounded(payload.get("assignments", [])):
        d, sid = row.get("dimension"), row.get("source_id")
        if d not in DIMENSIONS[:-1] or sid not in by_id or not supported(row, creative, cutoff):
            continue
        if sid not in row["evidence_refs"] or not isinstance(row.get("pattern_id"), str) or not row["pattern_id"]:
            continue
        key = by_id[sid]
        if key in assignments[d] and assignments[d][key] != row["pattern_id"]:
            raise ValueError("conflicting exclusive dimension assignments")
        assignments[d][key] = row["pattern_id"]
    for key, row in originals.items():
        if creator_key(row):
            assignments["creator"][key] = creator_key(row)
    results = {}
    creators = {creator_key(r) for r in originals.values() if creator_key(r)}
    for d in DIMENSIONS:
        values = assignments[d]
        counts = Counter(values.values())
        classified = len(values)
        coverage = classified / n if n else None
        groups, used = [], set()
        for group in bounded(payload.get("copy_groups", [])):
            if group.get("dimension") != d or not supported(group, creative, cutoff):
                continue
            keys = {by_id[r] for r in group.get("member_ids", []) if r in by_id and by_id[r] in values}
            if used & keys:
                raise ValueError("copy groups must be disjoint within a dimension")
            used |= keys
            groups.append(keys)
        # A group is positive copy evidence. An explicit complete comparison
        # may prove zero; absence of groups alone says nothing about copying.
        comparison = payload.get('copy_comparisons', {}).get(d, {})
        compared = {by_id[r] for r in comparison.get('member_ids', []) if r in by_id and by_id[r] in values}
        assessed = bool(groups) or (comparison.get('complete') is True
            and supported(comparison, creative, cutoff) and compared == set(values) and bool(values))
        redundant = sum(max(len(g) - 1, 0) for g in groups) if assessed else None
        patterns = []
        for pattern, count in sorted(counts.items()):
            members = [k for k, value in values.items() if value == pattern]
            rows = [(p, creator_key(originals[k])) for k, p in values.items()]
            patterns.append({"pattern_id": list(pattern) if isinstance(pattern, tuple) else pattern,
                             "count": count, "classified_share": count / classified,
                             "unique_creator_support": len({creator_key(originals[k]) for k in members if creator_key(originals[k])}),
                             "interval": _interval(rows, pattern, payload.get("bootstrap_seed", 0))})
        floor = n >= 50 and coverage is not None and coverage >= 0.8 and len(creators) >= 20
        results[d] = {"eligible_count": n, "classified_count": classified, "unclassified_count": n - classified,
                      "classification_coverage": coverage, "patterns": patterns, "redundant_count": redundant,
                      "redundancy_ratio": redundant / classified if classified and assessed else None,
                      "copy_support": "assessed" if assessed else "unassessed",
                      "evidence_floor_met": floor, "qualitative_label": None,
                      "null_reason": "qualitative_method_unqualified" if floor else "insufficient_sample_or_coverage"}
    creator_counts = Counter(assignments["creator"].values())
    known = sum(creator_counts.values())
    results["creator"].update({"known_author_count": known, "author_coverage": known / n if n else None,
                              "largest_creator_share": max(creator_counts.values()) / known if known else None,
                              "effective_creator_count": known ** 2 / sum(c * c for c in creator_counts.values()) if known else None})
    return envelope(payload, frame=deepcopy(frame), comparison_epoch=digest({k: v for k, v in frame.items() if k not in {"window_start", "window_end"}}),
                    dimensions=results, measurement_state="available", creative_state="available" if creative else "unavailable",
                    audience_fatigue="unknown", qualification="unqualified", pooled_platform_estimate=False)


def to_stored_projection(result):
    """Canonical saturationSchema; each metric names its own denominator/formula."""
    dimensions, frame = [], result["frame"]
    for name, row in result["dimensions"].items():
        value = row["largest_creator_share"] if name == "creator" else row["redundancy_ratio"]
        denominator = "known_author_observations" if name == "creator" else "classified_original_observations"
        definition = "creator_concentration" if name == "creator" else name + "_copy_redundancy"
        metric = {"value": value, "unit": "ratio", "definition_id": definition, "definition_version": "2",
                  "window": {"start": frame["window_start"], "end": frame["window_end"]}, "baseline_ref": None,
                  "denominator": denominator, "null_reason": ("copy_support_unassessed" if row['classified_count'] and name != 'creator'
                    and row.get('copy_support') == 'unassessed' else "no_classified_observations") if value is None else None}
        dimensions.append({"dimension": name, "assessment": None, "frame": frame["frame_id"],
                           "eligible": row["eligible_count"], "classified": row["classified_count"], "metric": metric,
                           "interval": None, "method": "deterministic_assignment_counts_v1",
                           "sample_details": {"unclassified_count":row['unclassified_count'],
                               "classification_coverage":row['classification_coverage'],
                               "total_patterns":len(row['patterns']),"patterns_truncated":len(row['patterns'])>20,
                               "patterns":deepcopy(row['patterns'][:20]),"copy_support":row['copy_support'],
                               "redundant_count":row['redundant_count'],
                               "creator":{k:row[k] for k in ('known_author_count','author_coverage','largest_creator_share','effective_creator_count')} if name=='creator' else None},
                           "uncertainty": "Sample only; classification coverage=" + str(row["classification_coverage"]) + "; no fatigue qualification."})
    return stored_projection("saturation", {"dimensions": dimensions})
