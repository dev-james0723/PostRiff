"""Versioned contextual priors remain distinct from private observed outcomes."""
from copy import deepcopy
from .context import bounded, envelope, source_index, supported, timestamp


def resolve_prior(payload):
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    cohort = payload["cohort"]
    shared, private = [], []
    for row in bounded(payload.get("priors", []), 1000):
        if not supported(row, sources, cutoff) or row.get("drifted") is True:
            continue
        if any(row.get(k) != cohort.get(k) for k in ("platform", "format", "language", "niche", "period")):
            continue
        if row.get("qualification") != "qualified":
            continue
        if row.get("workspace_id") is not None:
            if row["workspace_id"] != payload["workspace_id"] or row.get("basis") != "actual_published_outcomes":
                continue
            private.append(deepcopy(row))
        else:
            shared.append(deepcopy(row))
    return envelope(payload, cohort=deepcopy(cohort), shared_priors=shared, private_adjustments=private,
                    historical_fit="supported" if private else "unknown", effective_basis="private_outcomes" if private else "shared_hypothesis" if shared else "unknown",
                    conflict=bool(shared and private and {r.get("finding") for r in shared} != {r.get("finding") for r in private}),
                    permanent_voice_changed=False)
