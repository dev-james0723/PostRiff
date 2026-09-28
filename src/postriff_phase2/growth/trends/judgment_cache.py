"""Rights/context-bound cache envelope, independent of a native model's probabilities."""
from __future__ import annotations

import copy
from .contracts import digest, instant


def cache_identity(*, scope_key, input_digest, source_revisions, question_digest, requested_model,
                   policy_digest, context_revision, method_version, calibration_ref=None):
    return digest({"scope": scope_key, "input": input_digest, "sources": sorted(source_revisions),
                   "question": question_digest, "requested_model": requested_model, "policy": policy_digest,
                   "context": context_revision, "method": method_version, "calibration": calibration_ref})


def envelope(key, result, *, scope_key, expires_at, dependency_ids, context_revision, policy_digest):
    if result.get("status") != "ok" or result.get("invalid") or not result.get("executed_model"):
        return None
    return {"key": key, "scope_key": scope_key, "result": copy.deepcopy(result), "expires_at": expires_at,
            "dependency_ids": sorted(set(dependency_ids)), "context_revision": context_revision,
            "policy_digest": policy_digest, "calibration_state": result.get("calibration_state", "unqualified")}


def read(value, *, at, scope_key, context_revision, policy_digest, revoked_ids, membership_current):
    if not value or not membership_current or value["scope_key"] != scope_key:
        return None
    if (instant(at) >= instant(value["expires_at"]) or value["context_revision"] != context_revision
            or value["policy_digest"] != policy_digest or set(value["dependency_ids"]) & set(revoked_ids)):
        return None
    return {**copy.deepcopy(value["result"]), "cached": True, "new_provider_attempts": 0}
