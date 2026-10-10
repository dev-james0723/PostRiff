/**
 * The one client-visible error vocabulary for Rafii's agent permission and task surfaces (rafii-agent-authz/1, CF-2 §13).
 * Twin of src/postriff_phase2/agent_runtime_v2/agent_error_codes.py and tests/fixtures/agent_tasks/contracts/error-codes.json;
 * tests/test_agent_permissions.py and web/tests/agent-permissions.test.cjs keep the three identical. Clients render reason
 * codes through copy keys and never parse an error message.
 */
export const AGENT_ERRORS = {
  agent_permissions_unavailable: 404,
  agent_permissions_changed: 409,
  agent_permissions_copy_stale: 409,
  confirmation_required: 400,
  step_up_required: 403,
  agent_permissions_human_only: 403,
  scope_invalid: 400,
  idempotency_conflict: 409,
  agent_permission_denied: 403,
  agent_permission_revoked: 403,
  approval_unavailable: 404,
  approval_closed: 409,
  approval_expired: 409,
  approval_stale: 409,
  approval_forbidden: 403,
  task_unavailable: 404,
  task_forbidden: 403,
  task_conflict: 409,
  task_terminal: 409,
  task_too_long: 400,
  step_unknown: 404,
  step_closed: 409,
  step_not_retryable: 409,
  retry_budget_exhausted: 409,
  undo_unavailable: 409,
  undo_expired: 409,
  undo_conflict: 409,
  proposal_closed: 409,
  proposal_expired: 409,
  proposal_digest: 409,
  approve_required: 403,
  edit_required: 403,
  owner_required: 403,
  proposal_stale: 409
} as const;

export type AgentErrorCode = keyof typeof AGENT_ERRORS;

/** Non-error result codes inside a tool or turn result (HTTP 200/201). */
export const AGENT_RESULT_CODES = ['needs_confirmation', 'native_only', 'needs_panel_confirmation'] as const;

/** Step and task reason codes: state data shown through copy, never an HTTP code. */
export const STEP_REASON_CODES = {
  blocked: ['permission_revoked', 'permission_missing', 'member_inactive', 'provider_disconnected', 'provider_grant_missing', 'budget', 'budget_ceiling', 'feature_unavailable', 'needs_input', 'needs_conversation', 'step_failed', 'target_changed'],
  terminal: ['dependency_failed', 'approval_expired', 'approval_rejected', 'task_expired', 'task_superseded', 'outcome_unknown', 'runtime_changed', 'cancelled_by_person', 'cancelled_by_revocation']
} as const;

export function isAgentErrorCode(code: unknown): code is AgentErrorCode {
  return typeof code === 'string' && Object.prototype.hasOwnProperty.call(AGENT_ERRORS, code);
}
