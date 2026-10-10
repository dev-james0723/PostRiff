"""The one client-visible error vocabulary for the agent permission and task surfaces (rafii-agent-authz/1, CF-2 §13).

CF-2 §13 is the only table: CF-3 (the task engine) uses these codes too and defines none of its own (correction 16). The
fixture tests/fixtures/agent_tasks/contracts/error-codes.json holds the same table, and the TypeScript twin
web/src/lib/agent-permissions/error-codes.ts is checked against it (tests/test_agent_permissions_contract.py), so the
browser, the server and the task engine can never drift apart.

The draft codes permission_revoked, permission_missing, agent_approval_closed, agent_approval_expired,
agent_approval_digest and agent_approval_stale are retired as error codes; permission_revoked and permission_missing
survive only as step reason codes (state data, never an HTTP `code`).
"""
from __future__ import annotations

# §13.1 Errors: code -> HTTP status ("tool result" codes travel inside a 200 tool result as well).
ERRORS = {
    "agent_permissions_unavailable": 404,
    "agent_permissions_changed": 409,
    "agent_permissions_copy_stale": 409,
    "confirmation_required": 400,
    "step_up_required": 403,
    "agent_permissions_human_only": 403,
    "scope_invalid": 400,
    "idempotency_conflict": 409,
    "agent_permission_denied": 403,
    "agent_permission_revoked": 403,
    "approval_unavailable": 404,
    "approval_closed": 409,
    "approval_expired": 409,
    "approval_stale": 409,
    "approval_forbidden": 403,
    "task_unavailable": 404,
    "task_forbidden": 403,
    "task_conflict": 409,
    "task_terminal": 409,
    "task_too_long": 400,
    "step_unknown": 404,
    "step_closed": 409,
    "step_not_retryable": 409,
    "retry_budget_exhausted": 409,
    "undo_unavailable": 409,
    "undo_expired": 409,
    "undo_conflict": 409,
    "proposal_closed": 409,
    "proposal_expired": 409,
    "proposal_stale": 409,
    "proposal_digest": 409,
    "approve_required": 403,
    "edit_required": 403,
    "owner_required": 403,
}

# §13.2 Non-error result codes (tool and turn results, HTTP 200/201).
RESULTS = ("needs_confirmation", "native_only", "needs_panel_confirmation")

# §13.3 Step and task reason codes (state data, never an HTTP `code`).
STEP_BLOCKED = ("permission_revoked", "permission_missing", "member_inactive", "provider_disconnected", "provider_grant_missing", "budget",
                "budget_ceiling", "feature_unavailable", "needs_input", "needs_conversation", "step_failed", "target_changed")
STEP_TERMINAL = ("dependency_failed", "approval_expired", "approval_rejected", "task_expired", "task_superseded", "outcome_unknown",
                 "runtime_changed", "cancelled_by_person", "cancelled_by_revocation")

RETIRED = ("permission_revoked", "permission_missing", "agent_approval_closed", "agent_approval_expired", "agent_approval_digest",
           "agent_approval_stale")


def status(code: str) -> int:
    """The HTTP status of a client-visible error code. An unknown code is a programming error, never a silent 400."""
    return ERRORS[code]


def table() -> dict:
    """The table as the fixture stores it."""
    return {"version": 1, "source": "CF-2 §13", "errors": dict(ERRORS), "results": list(RESULTS),
            "stepReasons": {"blocked": list(STEP_BLOCKED), "terminal": list(STEP_TERMINAL)}, "retired": list(RETIRED)}
