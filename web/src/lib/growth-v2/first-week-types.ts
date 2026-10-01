/** First Week Ready read model (`GET /api/workspaces/{id}/first-week`, `first_week/service.py view`). */

export type FirstWeekStep = 'source' | 'context' | 'accept' | 'plan' | 'scope' | 'review' | 'deliver' | 'complete';
export type BillingMode = 'free_preview' | 'managed_credits' | 'legacy_allowances';
export type HandoffState = 'export_ready' | 'user_confirmed_used';
export type SlotNextAction =
  | 'answer'
  | 'write_or_upgrade'
  | 'draft'
  | 'review'
  | 'connect_account'
  | 'approve_in_queue'
  | 'wait_for_publish'
  | 'done'
  | 'confirm_used'
  | null;

export interface FirstWeekSlot {
  id: string;
  day: string | null;
  localTime: string | null;
  timeZone: string | null;
  platform: string;
  language: string;
  channelId: string | null;
  status: string;
  reason: string | null;
  question: string | null;
  publishBlocker: 'channel_not_connected' | null;
  costState: 'requires_upgrade' | 'over_limit' | 'insufficient_credits' | null;
  needsAsset: boolean;
  sourceIds: string[];
  contentType: string | null;
  committed: boolean;
  variantId: string | null;
  draft: { text: string; revision: number; needsReview: boolean; origin: string | null } | null;
  handoff: { state: HandoffState; at: number; variantRevision: number; stale?: boolean } | null;
  nextAction: SlotNextAction;
}

export interface FirstWeekView {
  enabled: boolean;
  revision: number;
  step: FirstWeekStep;
  billingMode: BillingMode;
  missingContext: ('purpose' | 'audience')[];
  context: { purpose: string | null; audience: string | null; mode: string | null };
  source: { id: string; origin: string | null } | null;
  draft: { variantId: string; revision: number; text: string; platform: string; language: string; accepted: boolean; acceptedRevision: number | null } | null;
  week: { id: string; weekOf: string; state: string; blockedReason: string | null } | null;
  scope: { slotIds: string[]; scopeRevision: number; frozenAt: number; changes: { at: number; reason: string }[] } | null;
  slots: FirstWeekSlot[];
  delivered: number;
  committed: number;
  complete: boolean;
  queueHref: string;
  channelConnected: boolean;
  notes: string[];
}

export interface ContinuationImport {
  sourceId: string;
  variantIds: Partial<Record<'original' | 'edited', string>>;
  draftVariantId: string;
  replayed: boolean;
  journey: FirstWeekView;
}
