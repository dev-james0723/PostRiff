"""Bounded semantic evaluator through the existing JEV routing and usage ledger."""
from __future__ import annotations

from pathlib import Path
from ..judgments import JudgmentService
from ..questions import load, estimate_tokens
from .contracts import ContractError, digest

TASK_NAMES = ("cluster_merge_check", "semantic_label_check", "culture_classify", "workspace_fit", "originality",
              "execution_risk", "narrative_stance", "genome_support", "spread_mechanism", "whitespace_support",
              "draft_diagnostic", "platform_fit")


def evaluate(router, task: str, pack: dict, *, workspace_id: str | None, authorized: bool,
             reserved_microusd: int, qualification: dict | None = None) -> dict:
    if task not in TASK_NAMES:
        raise ContractError("unknown_trend_evaluation_task")
    if not authorized or type(reserved_microusd) is not int or reserved_microusd <= 0:
        raise ContractError("bounded_model_authorization_required")
    if (estimate_tokens(pack) > 8000 or not pack.get("input_digest") or pack.get("evidence_is_untrusted_data") is not True
            or pack['input_digest'] != digest({k: v for k, v in pack.items() if k != 'input_digest'})):
        raise ContractError("invalid_model_evidence_pack")
    if workspace_id and pack.get("scope_key") != "workspace:" + workspace_id:
        raise ContractError("model_workspace_scope_mismatch")
    if workspace_id is None and not str(pack.get('scope_key', '')).startswith('shared:'):
        raise ContractError('model_workspace_scope_mismatch')
    qs = load(Path(__file__).parents[1] / "question_sets" / f"trend_{task}.v1.json")
    judge = JudgmentService(router.evaluator("trend." + task))
    result = judge.judge(qs, pack, subject=digest(pack), scope="personal:"+workspace_id if workspace_id else "shared",
                         model="typesafe-ai/jev", workspace_id=workspace_id)
    # Native probability is explicitly distinct from empirical task/cohort calibration.
    calibrated = bool(qualification and qualification.get("state") == "qualified"
                      and qualification.get("model") == result.model
                      and qualification.get("question_digest") == qs.digest
                      and bool(pack.get('cohort')) and qualification.get("cohort") == pack.get("cohort")
                      and qualification.get("artifact_ref"))
    answers = {name: {"value": answer.value if not answer.abstained else None,
                      "abstained": answer.abstained, "type": answer.type}
               for name, answer in result.answers.items()}
    return {"status": result.status if not result.invalid else "abstained", "answers": answers,
            "invalid": list(result.invalid), "evaluation_kind": "native_evaluation" if result.route == "primary" else "fallback_evaluation",
            "executed_model": result.model, "route": result.route, "question_set": qs.key, "question_digest": qs.digest,
            "input_digest": pack["input_digest"], "domain_calibration_ref": qualification["artifact_ref"] if calibrated else None,
            "calibration_state": "qualified" if calibrated else "unqualified", "cohort": pack.get("cohort"),
            "cost_usd": result.cost_usd, "cost_source": result.cost_source, "attempt_count": len(result.attempts),
            "cached": result.cached, "interpretation_only": True}
