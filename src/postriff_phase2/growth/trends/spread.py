"""Evidence-gated spread hypotheses. Caller supplies interpretation; no model call."""
from copy import deepcopy
from .context import bounded, envelope, source_index, supported, timestamp

MECHANISMS = {"practical_utility", "relatability", "identity_expression", "status_aspiration", "surprise", "humor",
              "participation", "information_gap", "debate_outrage", "fear_urgency"}


def project_spread_hypotheses(payload):
    sources, cutoff = source_index(payload, "creative"), timestamp(payload["decision_cutoff"])
    hypotheses = []
    for row in bounded(payload.get("hypotheses", []), 100):
        if row.get("mechanism") not in MECHANISMS or not supported(row, sources, cutoff) or not row.get("alternatives"):
            continue
        if row.get("risk_blocked") is True or row["mechanism"] in payload.get("brand_exclusions", []):
            continue
        hypotheses.append({k: deepcopy(row.get(k)) for k in ("mechanism", "evidence_refs", "alternatives", "contradictions", "uncertainty")})
    return envelope(payload, hypotheses=hypotheses, state="hypotheses" if hypotheses else "unknown",
                    causal_claim=False, origin="unknown", viewer_psychology="unknown")
