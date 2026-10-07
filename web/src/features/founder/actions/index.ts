/**
 * Founder actions (CONTRACTS §8.F) for the founder pages:
 * - `ConfirmActionDialog`: the shared preview → effect → confirm dialog.
 * - `CustomerActions`: block / lift, adjust credits, prepare a refund intent (Customer 360).
 * - `useReconcileAction`: the reconcile flow for the AI cost page's queue (slice B).
 * - `FounderActionsLog`: the Advanced › Actions tab.
 */
export { ConfirmActionDialog, type ConfirmActionDialogProps } from './confirm-action-dialog';
export { CustomerActions } from './customer-actions';
export { AdjustCreditsDialog, BlockAccountDialog, RefundIntentDialog, UnblockAccountDialog, type WorkspaceChoice } from './account-dialogs';
export { ReconcileDialog, useReconcileAction, type ReconcileAction, type ReconcileTarget } from './reconcile-action';
export { FounderActionsLog } from './actions-log';
export { useFounderActions } from './api';
export { actionFailure, unavailableReason, BLOCKER_COPY, DEMO_REASON } from './model';
export type { ActionKind, ActionsList, ActiveBlock, FounderAction } from './types';
