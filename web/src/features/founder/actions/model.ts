/**
 * Founder actions without React (CONTRACTS §8.F): the routes, the request bodies, input parsing, when an action is
 * available, and the fixed copy for every refusal. The server decides everything that matters (target, current value,
 * effect, revision, expiry); this file only shapes what the founder typed and words what the server answered.
 * `web/tests/founder-actions.test.cjs` loads it as is.
 */
import { count, millicredits, minor, stateLabel, usdMicro, whenDateTime } from '../customers/kit/format';
import type {
  ActionKind,
  ActionPolicies,
  ActiveBlock,
  BlockInput,
  BlockReason,
  CreditReason,
  CreditsInput,
  FactValue,
  Facts,
  FounderAction,
  LiftReason,
  PreviewRequest,
  ReconcileInput,
  RefundInput,
  RefundReason,
  RequestCheck,
  UnblockInput
} from './types';

export const TYPED_BLOCK = 'BLOCK';
export const PREVIEW_MINUTES = 5;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** The server's own patterns (`founder_actions.py`): a provider reference, never prose with an address in it. */
export const EVIDENCE = /^[A-Za-z0-9][A-Za-z0-9 ._:/#=+-]{0,199}$/;
export const APPROVAL_REF = /^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,119}$/;
export const PAYMENT_REF = /^[A-Za-z0-9_]{3,100}$/;
const CURRENCY = /^[a-z]{3}$/;

export const MAX_ACTUAL_USD_MICRO = 100_000_000;
export const MAX_ADJUST_MILLI = 50_000_000;
export const MAX_REFUND_MINOR = 100_000_000;

export const CAPABILITY: Record<ActionKind, string> = {
  reconcile: 'usage.reconcile',
  credits_adjust: 'credits.adjust',
  account_block: 'accounts.block',
  account_unblock: 'accounts.block',
  refund_intent: 'refunds.prepare'
};

export const KIND_LABEL: Record<ActionKind, string> = {
  reconcile: 'Reconcile usage',
  credits_adjust: 'Adjust credits',
  account_block: 'Block account',
  account_unblock: 'Unblock account',
  refund_intent: 'Refund intent'
};

export const STATE_LABEL: Record<string, string> = {
  previewed: 'Previewed',
  confirmed: 'Confirmed, outcome pending',
  executed: 'Executed',
  failed: 'Refused',
  expired: 'Expired'
};

export const BLOCK_REASONS: { value: BlockReason; label: string }[] = [
  { value: 'abuse', label: 'Abuse' },
  { value: 'fraud', label: 'Fraud' },
  { value: 'spam', label: 'Spam' },
  { value: 'security', label: 'Security incident' },
  { value: 'payment', label: 'Payment risk' },
  { value: 'legal', label: 'Legal request' },
  { value: 'other', label: 'Other' }
];

export const LIFT_REASONS: { value: LiftReason; label: string }[] = [
  { value: 'resolved', label: 'Resolved' },
  { value: 'mistake', label: 'Blocked by mistake' },
  { value: 'appeal_granted', label: 'Appeal granted' },
  { value: 'other', label: 'Other' }
];

export const CREDIT_REASONS: { value: CreditReason; label: string }[] = [
  { value: 'goodwill', label: 'Goodwill' },
  { value: 'service_issue', label: 'Service issue' },
  { value: 'billing_correction', label: 'Billing correction' }
];

export const REFUND_REASONS: { value: RefundReason; label: string }[] = [
  { value: 'requested_by_customer', label: 'Requested by the customer' },
  { value: 'duplicate', label: 'Duplicate payment' },
  { value: 'fraudulent', label: 'Fraudulent payment' },
  { value: 'service_issue', label: 'Service issue' },
  { value: 'other', label: 'Other' }
];

export const GRANT_EXPIRY_DAYS = [30, 90, 180, 365] as const;

export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value);
}

/* ---------- routes (http.register_route in founder_actions.py; the client prefixes /api/control/v2) ---------- */

/** Every action write names Live explicitly; Demo never sends one. */
const LIVE = '?mode=live';

function accountPath(targetId: string, verb: 'block' | 'unblock', step: 'preview' | 'confirm'): string {
  return `/actions/accounts/${encodeURIComponent(targetId)}/${verb}/${step}${LIVE}`;
}

const PREVIEW_ROUTE: Record<ActionKind, (targetId: string) => string> = {
  reconcile: () => `/usage/reconcile/preview${LIVE}`,
  credits_adjust: () => `/actions/credits/preview${LIVE}`,
  account_block: (targetId) => accountPath(targetId, 'block', 'preview'),
  account_unblock: (targetId) => accountPath(targetId, 'unblock', 'preview'),
  refund_intent: () => `/actions/refunds/preview${LIVE}`
};

/** A refund intent has no confirm route: execution is not decided. */
const CONFIRM_ROUTE: Record<ActionKind, ((targetId: string) => string) | null> = {
  reconcile: () => `/usage/reconcile/confirm${LIVE}`,
  credits_adjust: () => `/actions/credits/confirm${LIVE}`,
  account_block: (targetId) => accountPath(targetId, 'block', 'confirm'),
  account_unblock: (targetId) => accountPath(targetId, 'unblock', 'confirm'),
  refund_intent: null
};

export function previewPath(kind: ActionKind, targetId = ''): string {
  return PREVIEW_ROUTE[kind](targetId);
}

/** The confirm route for a preview, or null when the action cannot be confirmed from the browser. */
export function confirmPath(action: Pick<FounderAction, 'kind' | 'targetId'>): string | null {
  const route = CONFIRM_ROUTE[action.kind];
  return route ? route(action.targetId) : null;
}

/** The confirm body: the preview id and revision the founder saw, a request id, and the typed word for blocks. */
export function confirmBody(action: Pick<FounderAction, 'kind' | 'previewId' | 'revision'>, requestId: string, typed?: string): Record<string, string> {
  const body: Record<string, string> = { previewId: action.previewId, revision: action.revision, requestId };
  if (action.kind === 'account_block') body.confirmation = typed ?? '';
  return body;
}

export function typedConfirmationOk(kind: ActionKind, typed: string): boolean {
  return kind !== 'account_block' || typed.trim() === TYPED_BLOCK;
}

/* ---------- input parsing (what the founder typed → the integers the server takes) ---------- */

/** A non-negative decimal with at most `digits` decimals, as an integer of 10^-digits units; null when it is not one. */
export function parseDecimal(text: string, digits: number): number | null {
  const match = /^(\d{1,12})(?:\.(\d*))?$/.exec(text.trim());
  if (!match) return null;
  const fraction = match[2] ?? '';
  if (fraction.length > digits) return null;
  const value = Number(match[1]) * 10 ** digits + Number((fraction + '0'.repeat(digits)).slice(0, digits) || '0');
  return Number.isSafeInteger(value) ? value : null;
}

/** "0.0123" US dollars → 12300 micro-dollars. */
export function parseUsdMicro(text: string): number | null {
  const value = parseDecimal(text, 6);
  return value !== null && value <= MAX_ACTUAL_USD_MICRO ? value : null;
}

/** "2.5" credits → 2500 millicredits, in the server's 100-millicredit steps. */
export function parseCreditsMilli(text: string): number | null {
  const value = parseDecimal(text, 1);
  if (value === null) return null;
  const milli = value * 100;
  return milli >= 100 && milli <= MAX_ADJUST_MILLI ? milli : null;
}

/** "12.50" → 1250 minor units (two-decimal currencies). */
export function parseMinor(text: string): number | null {
  const value = parseDecimal(text, 2);
  return value !== null && value >= 1 && value <= MAX_REFUND_MINOR ? value : null;
}

/** A goodwill grant's expiry: the end of the chosen number of days from `now`, as the aware instant the server takes. */
export function grantExpiry(days: number, now: Date): string {
  return new Date(now.getTime() + days * 86_400_000).toISOString();
}

/* ---------- request builders (the dialog adds the request id) ---------- */

function invalid(reason: string): RequestCheck {
  return { ok: false, reason };
}

function ready(path: string, body: PreviewRequest['body']): RequestCheck {
  return { ok: true, request: { path, body } };
}

export function reconcileRequest(input: Partial<ReconcileInput> & { actualText?: string }): RequestCheck {
  if (!isUuid(input.workspaceId) || !isUuid(input.reservationId)) return invalid('This usage row has no workspace or reservation id to reconcile.');
  if (input.outcome !== 'completed' && input.outcome !== 'failed') return invalid('Choose whether the person got the result.');
  const actual = typeof input.actualUsdMicro === 'number' ? input.actualUsdMicro : parseUsdMicro(input.actualText ?? '');
  if (actual === null || !Number.isInteger(actual) || actual < 0 || actual > MAX_ACTUAL_USD_MICRO) return invalid('Enter the provider cost in US dollars, for example 0.0123 (up to six decimals, at most 100).');
  const evidence = (input.evidence ?? '').trim();
  if (!EVIDENCE.test(evidence)) return invalid(BLOCKER_COPY.invalid_evidence);
  return ready(previewPath('reconcile'), { workspaceId: input.workspaceId, reservationId: input.reservationId, outcome: input.outcome, actualUsdMicro: actual, evidence });
}

export function creditsRequest(input: Partial<CreditsInput> & { creditsText?: string }): RequestCheck {
  if (!isUuid(input.workspaceId)) return invalid('Choose the workspace whose credits change.');
  const milli = typeof input.milliCredits === 'number' ? input.milliCredits : parseCreditsMilli(input.creditsText ?? '');
  if (milli === null || milli < 100 || milli > MAX_ADJUST_MILLI || milli % 100 !== 0) return invalid('Enter between 0.1 and 50,000 credits, in steps of 0.1.');
  if (!input.reasonCode || !CREDIT_REASONS.some((reason) => reason.value === input.reasonCode)) return invalid('Choose a reason.');
  if (input.operation === 'grant') {
    if (!input.expiresAt) return invalid('Choose when the granted credits expire.');
    return ready(previewPath('credits_adjust'), { workspaceId: input.workspaceId, operation: 'grant', milliCredits: milli, expiresAt: input.expiresAt, reasonCode: input.reasonCode });
  }
  if (input.operation === 'reverse') {
    const grantId = (input.grantId ?? '').trim();
    if (!isUuid(grantId)) return invalid('Enter the id of the credit grant to take back.');
    return ready(previewPath('credits_adjust'), { workspaceId: input.workspaceId, operation: 'reverse', milliCredits: milli, grantId, reasonCode: input.reasonCode });
  }
  return invalid('Choose whether to grant or take back credits.');
}

export function blockRequest(input: Partial<BlockInput>): RequestCheck {
  if ((input.targetType !== 'user' && input.targetType !== 'workspace') || !isUuid(input.targetId)) return invalid('Choose what to block.');
  if (!input.reasonCode || !BLOCK_REASONS.some((reason) => reason.value === input.reasonCode)) return invalid('Choose a reason.');
  const approval = (input.approvalRef ?? '').trim();
  if (!APPROVAL_REF.test(approval)) return invalid(BLOCKER_COPY.invalid_approval_ref);
  return ready(previewPath('account_block', input.targetId), { targetType: input.targetType, reasonCode: input.reasonCode, approvalRef: approval });
}

export function unblockRequest(input: Partial<UnblockInput>): RequestCheck {
  if ((input.targetType !== 'user' && input.targetType !== 'workspace') || !isUuid(input.targetId)) return invalid('Choose the block to lift.');
  if (!input.reasonCode || !LIFT_REASONS.some((reason) => reason.value === input.reasonCode)) return invalid('Choose why the block is lifted.');
  return ready(previewPath('account_unblock', input.targetId), { targetType: input.targetType, reasonCode: input.reasonCode });
}

export function refundRequest(input: Partial<RefundInput> & { amountText?: string }): RequestCheck {
  if (!isUuid(input.workspaceId)) return invalid('Choose the workspace that paid.');
  const payment = (input.paymentIntentId ?? '').trim();
  if (!PAYMENT_REF.test(payment)) return invalid(BLOCKER_COPY.invalid_payment);
  const amount = typeof input.amountMinor === 'number' ? input.amountMinor : parseMinor(input.amountText ?? '');
  if (amount === null || amount < 1 || amount > MAX_REFUND_MINOR) return invalid('Enter the amount to refund, for example 12.50.');
  const currency = (input.currency ?? '').trim().toLowerCase();
  if (!CURRENCY.test(currency)) return invalid('Enter the three-letter currency of the payment, for example usd.');
  if (!input.reasonCode || !REFUND_REASONS.some((reason) => reason.value === input.reasonCode)) return invalid('Choose a reason.');
  return ready(previewPath('refund_intent'), { workspaceId: input.workspaceId, paymentIntentId: payment, amountMinor: amount, currency, reasonCode: input.reasonCode });
}

/* ---------- availability (why a button is disabled) ---------- */

export interface AvailabilityInput {
  kind: ActionKind;
  mode: 'live' | 'demo';
  /** The capability names the control session granted. */
  capabilities: readonly string[];
  /** `GET /actions` policies, when the operator can read them. */
  policies?: ActionPolicies | null;
}

export const DEMO_REASON = 'Demo is a sandbox: founder actions change Live records only, so they are switched off here.';

/** null when the action can be started, else the one sentence that says why not. */
export function unavailableReason({ kind, mode, capabilities, policies }: AvailabilityInput): string | null {
  if (mode === 'demo') return DEMO_REASON;
  const capability = CAPABILITY[kind];
  if (!capabilities.includes(capability)) return `This operator does not hold the ${capability} capability.`;
  if (kind === 'credits_adjust' && policies?.creditsEnabled === false) return BLOCKER_COPY.credits_not_enabled;
  return null;
}

/** The active block on this person or on one of these workspaces (person first). */
export function activeBlockFor(blocks: readonly ActiveBlock[], userId: string | null, workspaceIds: readonly string[] = []): ActiveBlock | null {
  return blocks.find((block) => userId !== null && block.userId === userId) ?? blocks.find((block) => block.workspaceId !== null && workspaceIds.includes(block.workspaceId)) ?? null;
}

/* ---------- refusals in words ---------- */

/** Fixed copy for every blocker code the action routes answer. A code missing here falls back to its status copy. */
export const BLOCKER_COPY: Record<string, string> = {
  credits_not_enabled: 'Credits are not enabled on this server, so credits cannot be granted or taken back.',
  refund_policy_not_decided: 'The refund policy has not been decided yet, so a refund can only be recorded as an intent. Nothing is sent to the payment provider.',
  workspace_not_on_credit_terms: 'This workspace uses its plan allowance, not credit terms, so its credits cannot be adjusted.',
  credit_policy_inactive: 'This workspace’s credit policy is not active.',
  account_blocks_not_installed: 'Account blocks are not installed yet (migration 062), so nothing can be blocked.',
  payments_not_configured: 'Payment records are not available here yet, so a refund cannot be prepared.',
  ops_workspace_not_configured: 'The founder ops workspace is not configured.',
  preview_expired: `This preview expired after ${PREVIEW_MINUTES} minutes. Preview again to see the current value.`,
  revision_mismatch: 'This is not the latest preview of that action. Preview again.',
  target_changed: 'The record changed after the preview, so nothing was done. Preview again to see the current value.',
  preview_executed: 'This preview was already confirmed and carried out.',
  preview_confirmed: 'This preview is already being confirmed. Retry that confirmation, or preview again.',
  preview_failed: 'This preview was already refused. Preview again.',
  preview_not_found: 'That preview is not available. Preview again.',
  preview_mismatch: 'That preview belongs to a different action or account.',
  request_id_used: 'This request was already used for something else. Preview again.',
  outcome_unknown_retry_same_request: 'The connection dropped before the result came back. Retry the same confirmation: it runs at most once.',
  already_blocked: 'This account is already blocked.',
  not_blocked: 'This account is not blocked.',
  cannot_block_operator: 'Your own founder account cannot be blocked.',
  cannot_block_ops_workspace: 'The founder ops workspace cannot be blocked.',
  too_many_workspaces: 'This person owns more than 100 workspaces. Block the workspaces one at a time.',
  account_not_found: 'That account does not exist in this environment.',
  workspace_not_found: 'That workspace does not exist in this environment.',
  reservation_not_found: 'That usage reservation is not in this workspace.',
  not_waiting_for_reconciliation: 'This usage is no longer waiting for reconciliation.',
  reconcile_refused: 'The ledger refused this reconciliation. Preview again.',
  grant_not_found: 'That credit grant is not in this workspace’s wallet.',
  reversal_exceeds_grant: 'That is more than what is left of the grant.',
  credit_adjustment_refused: 'The credit ledger refused this adjustment. Preview again.',
  payment_not_found: 'That payment is not recorded for this workspace.',
  payment_not_settled: 'That payment has not been settled, so there is nothing to refund.',
  amount_exceeds_refundable: 'That is more than what is left to refund on the payment.',
  currency_mismatch: 'The currency does not match the payment.',
  typed_confirmation_required: `Type ${TYPED_BLOCK} to confirm.`,
  invalid_evidence: 'Add the provider evidence: a request id or reference of up to 200 characters (letters, digits, spaces and . _ : / # = + -).',
  invalid_approval_ref: 'Add an approval reference such as ticket-1042 (letters, digits and . _ : / # -, no spaces).',
  invalid_payment: 'Enter the payment reference, for example pi_3Nf… (letters, digits and underscores).',
  invalid_amount: 'The amount is outside what this action allows.',
  invalid_expiry: 'Granted credits must expire between 1 and 366 days from now.',
  invalid_reason: 'Choose one of the listed reasons.',
  invalid_target: 'That account id is not valid.',
  invalid_operation: 'Choose whether to grant or take back credits.',
  invalid_currency: 'Enter the three-letter currency of the payment, for example usd.',
  invalid_outcome: 'Choose whether the person got the result.',
  invalid_id: 'One of the ids is not valid. Reload and retry.',
  invalid_request_id: 'The request id is not valid. Reload and retry.',
  invalid_preview_id: 'That preview id is not valid. Preview again.',
  invalid_revision: 'The preview revision is not valid. Preview again.',
  invalid_limit: 'The list size is not valid.',
  invalid_kind: 'That action kind is not known.',
  unexpected_fields: 'The request did not match this action. Reload and retry.'
};

export interface ActionFailure {
  title: string;
  description: string;
  /** The founder must sign in again (a second factor from the last five minutes). */
  stepUp: boolean;
  /** Retrying the same confirmation is safe and expected (the outcome is unknown). */
  retrySame: boolean;
  /** The preview cannot be confirmed any more: preview again. */
  previewAgain: boolean;
  code: string | null;
  blocker: string | null;
}

const PREVIEW_AGAIN = new Set(['preview_expired', 'revision_mismatch', 'target_changed', 'preview_failed', 'preview_not_found', 'request_id_used', 'preview_executed']);

/** One founder-facing explanation of a failed action call. Only fixed copy: never a server sentence. */
export function actionFailure(error: unknown, fallback = 'The action could not be completed. Nothing was changed.'): ActionFailure {
  const raw = (error && typeof error === 'object' ? error : {}) as { status?: unknown; code?: unknown; blocker?: unknown; message?: unknown; name?: unknown };
  const status = typeof raw.status === 'number' ? raw.status : 0;
  const code = typeof raw.code === 'string' ? raw.code : null;
  const blocker = typeof raw.blocker === 'string' ? raw.blocker : null;
  // Only the founder client's own error class carries fixed copy; anything else gets the fallback sentence.
  const fixed = raw.name === 'FounderApiError' && typeof raw.message === 'string' && raw.message ? raw.message : fallback;
  const words = blocker && blocker in BLOCKER_COPY ? BLOCKER_COPY[blocker] : null;
  const base = { code, blocker, stepUp: false, retrySame: false, previewAgain: Boolean(blocker && PREVIEW_AGAIN.has(blocker)) };
  if (code === 'STEP_UP_REQUIRED') {
    return { ...base, stepUp: true, title: 'Confirm it is you', description: `Founder actions need a second-factor check from the last ${PREVIEW_MINUTES} minutes. Sign in again, then repeat the action; nothing was changed.` };
  }
  if (code === 'POLICY_DISABLED') return { ...base, title: 'Switched off by policy', description: words ?? 'This action is switched off by policy. Nothing was changed.' };
  if (blocker === 'outcome_unknown_retry_same_request') return { ...base, retrySame: true, title: 'Result unknown', description: words as string };
  if (code === 'STALE_PREVIEW') return { ...base, previewAgain: true, title: 'Preview again', description: words ?? 'The record changed since the preview. Nothing was changed.' };
  if (code === 'IDEMPOTENCY_CONFLICT') return { ...base, previewAgain: true, title: 'Preview again', description: words ?? BLOCKER_COPY.request_id_used };
  if (code === 'VALIDATION_FAILED' || status === 400) return { ...base, title: status === 404 ? 'Not found' : 'Check the details', description: words ?? fixed };
  if (code === 'SCOPE_DENIED' || status === 403) return { ...base, title: 'Not allowed', description: fixed };
  if (status === 429) return { ...base, title: 'Too many actions', description: 'Founder actions are limited to ten a minute. Wait a moment and retry; nothing was changed.' };
  return { ...base, title: 'Could not complete the action', description: words ?? fixed };
}

/* ---------- the server's target / current / effect, in words (display only) ---------- */

export const FACT_LABELS: Record<string, string> = {
  type: 'Kind',
  id: 'Id',
  workspaceId: 'Workspace',
  reservationId: 'Reservation',
  runId: 'Run',
  dimension: 'Dimension',
  provider: 'Provider',
  model: 'Model',
  costState: 'Cost state',
  estimatedUsdMicro: 'Estimated cost',
  since: 'Waiting since',
  runStatus: 'Run status',
  creditsMaximumMilli: 'Credits held',
  chargeBatch: 'Uses a writing allowance',
  outcome: 'Outcome',
  actualUsdMicro: 'Actual provider cost',
  providerCostBookedUsdMicro: 'Provider cost booked',
  budgetHoldReleasedUsdMicro: 'Budget hold released',
  creditsUsedMilli: 'Credits charged',
  creditsReleasedMilli: 'Credits released',
  writingBatchConsumed: 'Writing allowance used',
  customerCharged: 'Customer charged',
  consumerAudit: 'Audit record',
  evidence: 'Provider evidence',
  provided: 'Provided',
  characters: 'Characters',
  deleted: 'Deleted',
  activeMemberships: 'Active memberships',
  ownedWorkspaces: 'Workspaces owned',
  ownerId: 'Owner',
  memberCount: 'Members',
  blocked: 'Blocked',
  blockId: 'Block',
  reasonCode: 'Reason',
  blockedAt: 'Blocked at',
  frozenWorkspaceIds: 'Workspaces frozen',
  thawedWorkspaceIds: 'Workspaces restored',
  approvalRef: 'Approval reference',
  sessionsRefused: 'Sign-ins refused',
  sessionsRestored: 'Sign-ins restored',
  apiTokensRefused: 'API tokens refused',
  publishingAndAutomationsPaused: 'Publishing and automations paused',
  customerCode: 'Error code the customer gets',
  customerMessage: 'What the customer sees',
  reversible: 'Reversible',
  policy: 'Credit policy',
  wallet: 'Wallet now',
  walletAfter: 'Wallet after',
  lots: 'Credit lots',
  lot: 'Grant',
  grantId: 'Grant',
  operation: 'Operation',
  milliCredits: 'Credits',
  expiresAt: 'Expires',
  source: 'Source',
  availableMilliCredits: 'Available',
  heldMilliCredits: 'Held',
  usedMilliCredits: 'Used',
  debtMilliCredits: 'Owed',
  milli: 'Granted',
  used: 'Used',
  held: 'Held',
  reversed: 'Taken back',
  available: 'Available',
  paymentIntentId: 'Payment',
  sourceId: 'Source record',
  livemode: 'Live payment',
  paidMinor: 'Paid',
  refundedMinor: 'Refunded so far',
  refunds: 'Refunds',
  disputed: 'Disputed',
  currency: 'Currency',
  paidAt: 'Paid at',
  intent: 'Intent',
  amountMinor: 'Amount',
  refundableAfterMinor: 'Refundable afterwards',
  executed: 'Executed',
  providerRefundCreated: 'Refund created at the provider',
  customerNotified: 'Customer notified',
  blocker: 'Blocked by',
  entryId: 'Ledger entry',
  duplicate: 'Already applied before',
  state: 'State'
};

/** Values that are codes the server chose (written with spaces), not free text. */
const CODE_KEYS = new Set(['type', 'costState', 'runStatus', 'outcome', 'reasonCode', 'operation', 'source', 'intent', 'state', 'dimension', 'blocker']);
const MILLI_KEYS = new Set(['milli', 'used', 'held', 'reversed', 'available']);

export function factLabel(key: string): string {
  if (key in FACT_LABELS) return FACT_LABELS[key];
  const words = key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replaceAll('_', ' ').toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

/** A scalar (or a list of ids) as text; null for a nested object, which is shown as its own list. */
export function factText(key: string, value: FactValue | undefined, siblings: Facts = {}): string | null {
  if (value === null || value === undefined) return 'Not recorded';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    if (key.endsWith('UsdMicro')) return usdMicro(value);
    if (key.endsWith('MilliCredits') || key.endsWith('Milli') || MILLI_KEYS.has(key)) return millicredits(value);
    if (key.endsWith('Minor')) return minor(value, typeof siblings.currency === 'string' ? siblings.currency.toUpperCase() : 'USD');
    if (key.endsWith('At') || key === 'since') return whenDateTime(value);
    return count(value);
  }
  if (typeof value === 'string') {
    if (key.endsWith('At') || key === 'since') return whenDateTime(value);
    return CODE_KEYS.has(key) ? stateLabel(value) : value;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return 'None';
    if (value.every((item) => typeof item === 'string' || typeof item === 'number')) return value.join(', ');
  }
  return null;
}
