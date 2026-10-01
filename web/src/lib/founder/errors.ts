/**
 * Fixed public copy for the founder admin (`/api/control/v2/*`). The control API answers every failure with a
 * `code` and a request id and never a provider message; the browser shows one of the sentences below and never
 * the server's own text (ported from `control-web/errors.mjs`, extended for the founder routes in CONTRACTS §3).
 */

/** The session cookie the control boundary sets on exchange; the proxy and the founder layout gate on its presence. */
export const CONTROL_COOKIE = '__Host-rafii-control';
export const FOUNDER_HOME = '/founder';
export const FOUNDER_SIGN_IN_PATH = '/founder/sign-in';

const BY_CODE: Record<string, string> = {
  RATE_LIMITED: 'Identity source is rate limited. Wait before retrying.',
  WORKSPACE_CONFIGURATION_REQUIRED: 'Required database setup is incomplete. Live access must be qualified before records can be shown.', // copy-audit: allow — founder-only control error
  WORKSPACE_ACCESS_REQUIRED: 'The database connection cannot read the required records. Review secure access configuration and retry.', // copy-audit: allow — founder-only control error
  POLICY_DISABLED: 'This action is switched off by policy. Nothing was sent or dialled.',
  CSRF_REQUIRED: 'Your session needs a fresh page. Reload and retry.',
  CSRF_INVALID: 'Your session needs a fresh page. Reload and retry.',
  STEP_UP_REQUIRED: 'This change needs a fresh second-factor check. Sign in again to continue.',
  REVISION_CONFLICT: 'This record changed since you loaded it. Reload and retry the same action.'
};

const BY_STATUS: Record<number, string> = {
  400: 'The request could not be verified. Reload and retry.',
  401: 'Authentication could not be verified. Sign in again.',
  403: 'This operator does not have permission for this view.',
  404: 'That record is not available in this environment.',
  409: 'This record changed since you loaded it. Reload and retry the same action.',
  429: 'Too many requests. Wait a moment and retry.',
  503: 'Control source is unavailable. Retry when it recovers; Live values have not been substituted.'
};

export const FOUNDER_ERROR_FALLBACK = 'Control request could not be completed. Review its evidence and retry.';

/** The one sentence shown for a failed control request; `code` wins over `status`, and unknown input gets the fallback. */
export function founderErrorMessage(status: number, code?: string | null): string {
  if (code && code in BY_CODE) return BY_CODE[code];
  return BY_STATUS[status] ?? FOUNDER_ERROR_FALLBACK;
}

export class FounderApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;
  /** Present on 409 POLICY_DISABLED answers (for example `ops_workspace_not_configured`). */
  blocker?: string;
  constructor(message: string, status: number, code?: string, requestId?: string, blocker?: string) {
    super(message);
    this.name = 'FounderApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.blocker = blocker;
  }
}

export function isFounderApiError(error: unknown): error is FounderApiError {
  return error instanceof FounderApiError;
}

/** A failed query's one-line copy for `StateMessage`; never a raw `Error.message` from anything but our own class. */
export function describeFounderError(error: unknown): string {
  if (error instanceof FounderApiError) return error.message;
  return FOUNDER_ERROR_FALLBACK;
}
