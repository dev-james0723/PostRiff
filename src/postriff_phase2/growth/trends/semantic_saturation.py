"""Pure reviewed semantic assignments for five-axis sample saturation.

Caller owns stored authentication, current rights/privacy reads, qualification
reviews, frozen model bindings and the dependency DAG. Pass the exact selected
rows from semantic_admission.load and (optionally) the corresponding adapt result.
This module never loads a store or calls a model. Missing availability abstains.

The source receipt cutoff/window remains fixed. New interpretations are available
only at their actual stored availability and use a separate current decision
cutoff. This is current retrospective description, not historical backtesting.
Language/cohort and native wording are provenance, not extra saturation axes.
Equal topic/claim labels are classification, never evidence of copying or fatigue.
"""
from collections import defaultdict
from copy import deepcopy

from . import context, contracts, semantic_admission

METHOD = "reviewed_semantic_assignments_v1"
TASK = "semantic_label_generate"
MAX_SOURCES = 1000
MAX_SELECTED = 2
MAX_ITEMS = 3
MAX_SPANS = 12
STANCES = {"supports", "opposes", "mixed", "describes"}


def _instant(value):
    try:
        return context.timestamp(value)
    except (TypeError, ValueError):
        return None


def _entry_time(entry, now):
    available, expiry = _instant(entry.get("available_at")), _instant(entry.get("expires_at"))
    if available is None or expiry is None or available > now or expiry <= now or available >= expiry:
        return None
    # Some future producers may additionally expose actual computation time.
    # It must not come from the future; durable availability remains authoritative.
    computed = entry.get("result", {}).get("computed_at")
    if computed is not None:
        computed = _instant(computed)
        if computed is None or computed > now:
            return None
    return available


def _candidate(item, entry, now):
    computed = entry['result'].get('computed_at')
    available = entry.get('available_at', computed)
    expiry = _instant(entry.get('expires_at'))
    current = (_instant(available) is not None and _instant(available) <= now
               and expiry is not None and expiry > now
               and (computed is None or (_instant(computed) is not None and _instant(computed) <= now)))
    return {**deepcopy(item), "task": entry["task"], "model_id": entry["result"]["executed_model"],
            "qualification": "cohort_qualified" if entry["qualified"] is True and current else "unqualified",
            "available_at": available, "computed_at": computed,
            "origin": "unknown", "derivation_kind": "model_interpretation"}


def build_assignments(inputs, selected, *, now, adapted=None):
    """Return exclusive topic/narrative assignments or explicit source abstentions.

    Parent measures using result.decision_cutoff and the ORIGINAL input frame and
    sources, binds both cutoffs and this method into its fingerprint, and preserves
    copy_density's pattern counts/shares. result.copy_groups is intentionally empty:
    semantic copy redundancy must remain null until separately assessed. Do not
    interpret the legacy copy_density default zero as an assessed semantic metric.

    A supplied adapt result must exactly match all candidates derived from the
    selected immutable model outputs. No first-wins annotations/dimensions are used.
    Qualification is an upstream reviewed authority, not an API caller permission.
    """
    current = context.timestamp(now)
    cutoff = context.timestamp(inputs["common"]["decision_cutoff"])
    if current < cutoff:
        raise ValueError("semantic_saturation_future_source_cutoff")
    context.bounded(inputs["common"]["sources"], MAX_SOURCES)
    context.bounded(selected, MAX_SELECTED)
    frame = inputs["frame"]
    start, end = context.timestamp(frame["window_start"]), context.timestamp(frame["window_end"])
    if not start < end <= cutoff or not frame.get("platform") or not frame.get("language"):
        raise ValueError("semantic_saturation_frame_required")
    for entry in selected:
        if not isinstance(entry, dict) or not isinstance(entry.get("result"), dict):
            raise ValueError("semantic_saturation_selection_invalid")
        for item in context.bounded(entry["result"].get("items", []), MAX_ITEMS):
            if not isinstance(item, dict):
                raise ValueError("semantic_saturation_item_invalid")
            context.bounded(item.get("evidence_spans", []), MAX_SPANS)
    # Reuse the real adapter's native span and LLM/creative permission checks.
    # The optional precomputed value saves callers from passing lossy annotations.
    if adapted is None:
        adapted = semantic_admission.adapt(inputs, selected, now)
    if not isinstance(adapted, dict):
        raise ValueError("semantic_saturation_adapted_invalid")
    expected = []
    for entry in selected:
        result = entry["result"]
        if result.get("task") != "trend." + entry.get("task", "") or result.get("status") != "ok":
            raise ValueError("semantic_saturation_result_invalid")
        if not isinstance(result.get("executed_model"), str) or not result["executed_model"]:
            raise ValueError("semantic_saturation_model_required")
        if type(entry.get("qualified")) is not bool:
            raise ValueError("semantic_saturation_review_boolean_required")
        expected.extend(_candidate(item, entry, current) for item in result["items"])
    if contracts.digest(adapted.get("candidates")) != contracts.digest(sorted(expected, key=contracts.canonical)):
        raise ValueError("semantic_saturation_adapted_binding_changed")

    # Denominator eligibility is analysis-only and remains the parent's measured
    # sample; denied semantic rights do not erase lawful numeric observations.
    measured = context.source_index(inputs["common"], originals=True)
    eligible = {sid: s for sid, s in measured.items()
                if start <= context.timestamp(s["event_at"]) < end
                and s["platform"] == frame["platform"] and s.get("language") == frame["language"]
                and _instant(s.get("expires_at")) is not None
                and context.timestamp(s["expires_at"]) > current}
    cohort = {"platform": frame["platform"], "language": frame["language"]}
    choices, reasons = defaultdict(dict), defaultdict(set)
    aliases = defaultdict(list)
    for sid, source in eligible.items():
        aliases[context.canonical_key(source)].append(sid)
    bindings = []
    for entry in selected:
        result = entry["result"]
        bindings.append({"task": entry["task"], "model_id": result["executed_model"],
                         "result_digest": contracts.digest(result), "available_at": entry.get("available_at"),
                         "expires_at": entry.get("expires_at"), "qualified": entry["qualified"]})
        if entry["task"] != TASK or entry["qualified"] is not True:
            continue
        available = _entry_time(entry, current)
        if available is None:
            continue
        for item in result["items"]:
            spans = item["evidence_spans"]
            refs = sorted({span.get("observation_id") for span in spans if isinstance(span.get("observation_id"), str)})
            if not refs or len(refs) != len({span.get("observation_id") for span in spans}):
                continue
            # All evidence, including contextual support, must be current and
            # native-cohort compatible. Do not silently drop a denied supporter.
            valid = True
            for span in spans:
                sid = span.get("observation_id")
                source = measured.get(sid)
                text = inputs["facts"].get(sid, {}).get("text")
                if (source is None or source.get("rights", {}).get("creative") is not True
                        or source["rights"].get("llm") is not True
                        or source.get("platform") != frame["platform"] or source.get("language") != frame["language"]
                        or _instant(source.get("expires_at")) is None
                        or context.timestamp(source["expires_at"]) <= current
                        or not isinstance(text, str) or type(span.get("start")) is not int
                        or type(span.get("end")) is not int
                        or not 0 <= span["start"] < span["end"] <= len(text)
                        or text[span["start"]:span["end"]] != span.get("text")):
                    valid = False
                    break
            if not valid or item.get("language") != frame["language"]:
                continue
            concept, claim, stance = item.get("concept"), item.get("claim"), item.get("stance")
            if not isinstance(concept, str) or not concept.strip() or len(concept) > 600:
                continue
            values = {"topic": {"concept": concept}}
            if isinstance(claim, str) and claim.strip() and len(claim) <= 600 and stance in STANCES:
                values["narrative"] = {"concept": concept, "claim": claim, "stance": stance}
            for sid in refs:
                if sid not in eligible:
                    continue
                key = context.canonical_key(eligible[sid])
                if "narrative" not in values:
                    reasons[(key, "narrative")].add("unknown_claim_or_stance")
                for dimension, meaning in values.items():
                    pattern = contracts.digest([METHOD, dimension, cohort, meaning])
                    slot = choices[(key, dimension)].setdefault(pattern, [])
                    slot.append({"source_id": sid, "dimension": dimension, "pattern_id": pattern,
                                 "native_cohort": deepcopy(cohort), **meaning,
                                 "evidence_refs": refs, "original_spans": deepcopy(spans),
                                 "available_at": contracts.iso(available),
                                 "expires_at": min([inputs["expires_at"], entry["expires_at"]]
                                     + [measured[r]["expires_at"] for r in refs], key=context.timestamp),
                                 "derivation_kind": "model_interpretation", "method_version": METHOD,
                                 "confidence_basis": "Current reviewed model/task/native cohort; exact retained spans.",
                                 "model_id": result["executed_model"], "input_digest": result.get("input_digest")})

    assignments, abstentions = [], []
    for key in sorted(aliases):
        for dimension in ("topic", "narrative"):
            candidates = choices.get((key, dimension), {})
            cause = reasons.get((key, dimension), set())
            if len(candidates) > 1:
                cause = cause | {"conflicting_reviewed_assignments"}
            if len(candidates) != 1 or cause:
                reason = sorted(cause) if cause else ["no_current_reviewed_assignment"]
                abstentions.extend({"source_id": sid, "dimension": dimension, "reasons": reason}
                                   for sid in sorted(aliases[key]))
                continue
            values = next(iter(candidates.values()))
            # Duplicate corroboration is order-independent. Conservatively retain
            # every dependency/expiry; aliases cannot count as additional originals.
            base = deepcopy(min(values, key=contracts.canonical))
            base["evidence_refs"] = sorted({r for value in values for r in value["evidence_refs"]})
            spans = {contracts.canonical(s): s for value in values for s in value["original_spans"]}
            base["original_spans"] = [deepcopy(spans[k]) for k in sorted(spans)]
            base["available_at"] = max((v["available_at"] for v in values), key=context.timestamp)
            base["expires_at"] = min((v["expires_at"] for v in values), key=context.timestamp)
            base["annotation_digests"] = sorted({contracts.digest(v) for v in values})
            assignments.append(base)
    return {"schema_version": "rafii.semantic-saturation.v1", "method_version": METHOD,
            "source_decision_cutoff": inputs["common"]["decision_cutoff"], "decision_cutoff": contracts.iso(current),
            "native_cohort": cohort, "assignments": assignments, "abstentions": abstentions,
            "copy_groups": [], "copy_support": {"topic": "unassessed", "narrative": "unassessed"},
            "annotation_bindings": sorted(bindings, key=contracts.canonical),
            "input_digest": contracts.digest(inputs), "qualification": "unqualified",
            "qualitative_saturation": "unknown", "audience_fatigue": "unknown"}
