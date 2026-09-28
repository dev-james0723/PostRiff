"""Small rights-filtered model state; models cannot write measurement fields."""
from __future__ import annotations

import copy
from ..questions import estimate_tokens
from ...coworker.research_broker import injection_flags
from .contracts import ContractError, digest, instant, permits, scope
from .culture import extract

VERSION = "trend-evidence-pack-v1"


def build(observations: list[dict], *, scope_key: str, cutoff: str, at: str, receipt: dict,
          policies: dict, workspace_context: dict | None = None, candidate: dict | None = None) -> dict:
    scope(scope_key); instant(cutoff); instant(at)
    if workspace_context and not scope_key.startswith("workspace:"):
        raise ContractError("private_context_cannot_enter_shared_pack")
    if receipt.get("verification_state", (receipt.get("verification") or {}).get("state")) != "verified":
        raise ContractError("verified_receipt_required")
    if receipt.get('scope_key') != scope_key or not receipt.get('digest', receipt.get('receipt_digest')):
        raise ContractError('receipt_scope_digest_required')
    selected, excluded, authors, seen = [], [], set(), set()
    for row in sorted(observations, key=lambda r: (r["available_at"], r["observation_id"])):
        policy = policies.get(row["source_policy_version"])
        valid = (row["scope_key"] == scope_key and instant(row["available_at"]) <= instant(cutoff)
                 and instant(row["retention_until"]) > instant(at) and row["operation"] != "delete"
                 and permits(row["rights"], "llm_process", scope_key, at) and policy is not None
                 and policy.provider_id == row['provider_id'] and policy.scope_key == scope_key
                 and policy.valid(at) and permits(policy.rights, "llm_process", scope_key, at))
        identity = (row['provider_id'], row['source_identity'])
        if not valid or len(selected) >= 12 or identity in seen:
            excluded.append(row["observation_id"]); continue
        seen.add(identity)
        text = row["payload"].get("text", "")
        if not text:
            excluded.append(row["observation_id"]); continue
        author = row["payload"].get("author_key")
        if author and author in authors:
            excluded.append(row["observation_id"]); continue
        if author:
            authors.add(author)
        selected.append({"observation_id": row["observation_id"], "revision": row["revision_identity"],
                         "text": text[:800], "text_truncated": len(text) > 800,
                         "language": row["payload"].get("language", "und"),
                         "spans": extract(text[:800])["spans"],
                         "injection_flags": [x["rule"] for x in injection_flags(text)],
                         "source_policy_version": row["source_policy_version"]})
    pack = {"schema_version": VERSION, "scope_key": scope_key, "decision_cutoff": cutoff,
            "evidence_is_untrusted_data": True, "evidence": selected, "excluded_ids": excluded,
            "sampling_strategy": "stable_first_diverse_creator_max12", "selected_count": len(selected),
            "excluded_count": len(excluded), "receipt_digest": receipt.get("digest", receipt.get("receipt_digest")),
            "coverage": copy.deepcopy(receipt.get("coverage", {})), "candidate": copy.deepcopy(candidate or {}),
            "workspace_context": copy.deepcopy(workspace_context or {})}
    if estimate_tokens(pack) > 8000:
        raise ContractError("model_pack_token_limit")
    pack["input_digest"] = digest(pack)
    return pack
