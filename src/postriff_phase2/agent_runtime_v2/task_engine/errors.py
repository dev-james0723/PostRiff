"""The one client-visible error vocabulary of the agent permission and task surfaces (CF-2 §13; CF-3 §2 correction 16).

`ERRORS` mirrors the frozen table in CF-2 §13.1 row for row; `tests/fixtures/agent_tasks/contracts/error-codes.json` is the
fixture both languages are checked against. Step and task `reason_code` values (§13.3) are state data, never an HTTP
`code`. Messages are short, person-facing and reveal nothing about another member's use of a key or another workspace.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

# code -> (HTTP status, default message)
ERRORS: dict[str, tuple[int, str]] = {
    "agent_permissions_unavailable": (404, "Rafii's permissions aren't available in this workspace."),
    "agent_permissions_changed": (409, "Your Rafii permissions changed. Review them and try again."),
    "agent_permissions_copy_stale": (409, "This permissions screen is out of date. Reload it and try again."),
    "confirmation_required": (400, "Confirm that you want to give Rafii more access."),
    "step_up_required": (403, "Sign in again to confirm this."),
    "agent_permissions_human_only": (403, "Only you can change what Rafii may do, from your own account."),
    "scope_invalid": (400, "That permission isn't available."),
    "idempotency_conflict": (409, "This request key was already used for a different request. Start a new request."),
    "agent_permission_denied": (403, "Rafii isn't allowed to do this in this workspace."),
    "agent_permission_revoked": (403, "Rafii is no longer allowed to do this, so nothing more was done."),
    "approval_unavailable": (404, "That approval is unavailable."),
    "approval_closed": (409, "That approval was already decided."),
    "approval_expired": (409, "That approval expired, so nothing was done."),
    "approval_stale": (409, "What you approved has changed. Review it again."),
    "approval_forbidden": (403, "You can't decide this approval."),
    "task_unavailable": (404, "Task unavailable."),
    "task_forbidden": (403, "You can't do that with this task."),
    "task_conflict": (409, "The task changed while this request ran. Reload it and try again."),
    "task_terminal": (409, "This task has already finished."),
    "task_too_long": (400, "A task holds at most 12 steps."),
    "step_unknown": (404, "That step is not part of this task."),
    "step_closed": (409, "That step has already finished."),
    "step_not_retryable": (409, "That step can't be retried."),
    "retry_budget_exhausted": (409, "This step has been retried as many times as allowed."),
    "undo_unavailable": (409, "There is nothing to undo for this step."),
    "undo_expired": (409, "It's too late to undo this step."),
    "undo_conflict": (409, "This changed after Rafii edited it, so nothing was undone."),
    "proposal_closed": (409, "That proposal was already decided."),
    "proposal_expired": (409, "That proposal expired."),
    "proposal_stale": (409, "That proposal is out of date."),
}

# Non-error result codes (CF-2 §13.2): tool and turn results with HTTP 200/201.
RESULT_CODES = ("needs_confirmation", "native_only", "needs_panel_confirmation")

# Step and task reason codes (CF-2 §13.3), plus the engine's own budget reason (CF-3 §9.3).
BLOCKED_REASONS = ("permission_revoked", "permission_missing", "member_inactive", "provider_disconnected", "provider_grant_missing", "budget",
                   "budget_ceiling", "feature_unavailable", "needs_input", "needs_conversation", "step_failed", "target_changed")
TERMINAL_REASONS = ("dependency_failed", "approval_expired", "approval_rejected", "task_expired", "task_superseded", "outcome_unknown",
                    "runtime_changed", "cancelled_by_person", "cancelled_by_revocation", "retry_budget_exhausted")
REASON_CODES = BLOCKED_REASONS + TERMINAL_REASONS


def error(code: str, message: str | None = None) -> AlphaError:
    """An AlphaError for one frozen code. Unknown codes are a programming error, never sent to a client."""
    status, default = ERRORS[code]
    return AlphaError(message or default, status, code=code)


def public_table() -> list[dict]:
    """The table as the contract fixture stores it (sorted by code)."""
    return [{"code": code, "http": status} for code, (status, _message) in sorted(ERRORS.items())]
