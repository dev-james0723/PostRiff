/**
 * Payloads of the founder action routes (`src/rafii_control/founder_actions.py`, CONTRACTS §8.F). Local to this folder
 * by agreement with the coordinator; every value is shown as the server sent it.
 */

export type ActionKind = 'reconcile' | 'credits_adjust' | 'account_block' | 'account_unblock' | 'refund_intent';
export type ActionState = 'previewed' | 'confirmed' | 'executed' | 'failed' | 'expired';
export type ActionTargetType = 'reservation' | 'workspace' | 'user' | 'payment';

export type FactValue = string | number | boolean | null | FactValue[] | { [key: string]: FactValue };
export type Facts = { [key: string]: FactValue };

/** `public_action(row)`: the request row as the founder sees it. Never the stored parameters. */
export interface FounderAction {
  previewId: string;
  kind: ActionKind;
  state: ActionState;
  revision: string;
  targetType: ActionTargetType;
  targetId: string;
  workspaceId: string | null;
  target: Facts | null;
  current: Facts | null;
  effect: Facts | null;
  result: Facts | null;
  errorCode: string | null;
  blocker: string | null;
  execution: { allowed: boolean; blocker: string | null };
  confirm: { method: 'POST'; path: string; expiresAt: string | null; requires: string[]; typedConfirmation: string | null } | null;
  createdAt: string | null;
  expiresAt: string | null;
  confirmedAt: string | null;
  finishedAt: string | null;
}

/** Every preview and confirm answers `{action, replayed}` inside the control envelope. */
export interface ActionResponse {
  action: FounderAction;
  replayed: boolean;
}

export interface ActiveBlock {
  blockId: string;
  userId: string | null;
  workspaceId: string | null;
  reasonCode: string;
  blockedAt: string;
}

export interface ActionPolicies {
  /** null: the server could not tell (no consumer runtime here); the preview then answers for itself. */
  creditsEnabled: boolean | null;
  refundExecution: { allowed: boolean; blocker: string };
}

/** `GET /actions` (audit.read). Demo answers an empty, labelled list. */
export interface ActionsList {
  mode: 'live' | 'demo';
  actions: FounderAction[];
  truncated?: boolean;
  limit?: number;
  actionsState?: 'measured' | 'not_installed';
  activeBlocks: ActiveBlock[];
  activeBlocksState?: 'measured' | 'not_installed';
  policies?: ActionPolicies;
  reason?: string;
}

export type BlockReason = 'abuse' | 'fraud' | 'spam' | 'security' | 'payment' | 'legal' | 'other';
export type LiftReason = 'resolved' | 'mistake' | 'appeal_granted' | 'other';
export type CreditReason = 'goodwill' | 'service_issue' | 'billing_correction';
export type RefundReason = 'duplicate' | 'fraudulent' | 'requested_by_customer' | 'service_issue' | 'other';

export interface ReconcileInput {
  workspaceId: string;
  reservationId: string;
  outcome: 'completed' | 'failed';
  actualUsdMicro: number;
  evidence: string;
}

export interface CreditsInput {
  workspaceId: string;
  operation: 'grant' | 'reverse';
  milliCredits: number;
  reasonCode: CreditReason;
  /** Grants only: an aware ISO instant 1–366 days ahead (goodwill credit always expires). */
  expiresAt?: string;
  /** Reversals only. */
  grantId?: string;
}

export interface BlockInput {
  targetType: 'user' | 'workspace';
  targetId: string;
  reasonCode: BlockReason;
  approvalRef: string;
}

export interface UnblockInput {
  targetType: 'user' | 'workspace';
  targetId: string;
  reasonCode: LiftReason;
}

export interface RefundInput {
  workspaceId: string;
  paymentIntentId: string;
  amountMinor: number;
  currency: string;
  reasonCode: RefundReason;
}

/** What a dialog sends for a preview: the route (without `/api/control/v2`) and the body without its request id. */
export interface PreviewRequest {
  path: string;
  body: Record<string, string | number>;
}

export type RequestCheck = { ok: true; request: PreviewRequest } | { ok: false; reason: string };
