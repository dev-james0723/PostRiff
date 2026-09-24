/**
 * The content lifecycle of an automation run: the TypeScript twin of `src/postriff_phase2/lifecycle.py`.
 * Both sides read the same vectors (`tests/fixtures/automation_lifecycle.json`), so the app shows exactly the state
 * the server enforces.
 *
 * A run first researches and drafts (its stage); each destination then becomes an item that moves through review,
 * approval, scheduling and publishing. The server alone moves items. Nothing here moves an item: `canMove` only
 * says whether a move is allowed, and silence never approves anything.
 *
 * No runtime imports, so node:test can load this file with the same transpile loader as `schedule.test.cjs`.
 */
import type { AutomationItemState, AutomationRunStage } from '@/lib/api/types';

export const RUN_STAGES = ['planned', 'researching', 'drafting', 'drafted', 'skipped', 'source_unavailable', 'failed'] as const satisfies readonly AutomationRunStage[];
export const RUN_TERMINAL = ['skipped', 'source_unavailable', 'failed'] as const satisfies readonly AutomationRunStage[];
export const ITEM_STATES = [
  'ready_for_review',
  'needs_revision',
  'approved',
  'scheduled',
  'publishing',
  'published',
  'rejected',
  'skipped',
  'failed',
  'platform_disconnected',
  'approval_expired'
] as const satisfies readonly AutomationItemState[];
export const ITEM_TERMINAL = ['published', 'rejected', 'approval_expired', 'failed', 'skipped'] as const satisfies readonly AutomationItemState[];

export const TRANSITIONS: Record<AutomationItemState, readonly AutomationItemState[]> = {
  ready_for_review: ['approved', 'rejected', 'needs_revision', 'approval_expired', 'platform_disconnected', 'skipped'],
  needs_revision: ['ready_for_review', 'rejected', 'approval_expired', 'skipped'],
  approved: ['scheduled', 'ready_for_review', 'approval_expired', 'platform_disconnected', 'failed', 'skipped'],
  scheduled: ['publishing', 'published', 'failed', 'platform_disconnected', 'skipped'],
  publishing: ['published', 'failed'],
  platform_disconnected: ['approved', 'ready_for_review', 'approval_expired', 'failed', 'skipped'],
  published: [],
  rejected: [],
  approval_expired: [],
  failed: [],
  skipped: []
};

/** What a drafted run shows: the most active item wins, then problems, then settled outcomes. */
export const PRIORITY = [
  'publishing',
  'scheduled',
  'approved',
  'ready_for_review',
  'needs_revision',
  'platform_disconnected',
  'failed',
  'approval_expired',
  'published',
  'rejected',
  'skipped'
] as const satisfies readonly AutomationItemState[];
export const ATTENTION = ['needs_revision', 'platform_disconnected', 'failed', 'approval_expired'] as const satisfies readonly AutomationItemState[];

/** Plain words for every state, shown in the app and in Raffi's explanations. */
export const LABELS: Record<AutomationRunStage | AutomationItemState, string> = {
  planned: 'Planned',
  researching: 'Researching',
  drafting: 'Drafting',
  drafted: 'Drafted',
  skipped: 'Skipped',
  source_unavailable: 'Source unavailable',
  failed: 'Failed',
  ready_for_review: 'Ready for review',
  needs_revision: 'Changes requested',
  approved: 'Approved',
  scheduled: 'Scheduled',
  publishing: 'Publishing',
  published: 'Published',
  rejected: 'Rejected',
  platform_disconnected: 'Account disconnected',
  approval_expired: 'Approval expired'
};

/** Publishing job states (`store.py` / `hosted_worker.py`) → item state. `held` depends on the channel (`jobItemState`). */
export const JOB_ITEM: Record<string, AutomationItemState> = {
  approved: 'scheduled',
  scheduled: 'scheduled',
  claimed: 'scheduled',
  submitting: 'publishing',
  processing: 'publishing',
  provider_accepted: 'publishing',
  published: 'publishing',
  uncertain: 'publishing',
  verified: 'published',
  failed: 'failed',
  canceled: 'skipped'
};

/** The run and item fields the rules read; a full `RecurringOccurrence` / `RunItem` fits. */
export interface LifecycleItem {
  state?: string | null;
  publishAt?: number | null;
  jobId?: string | null;
}
export interface LifecycleRun {
  lifecycle?: string | null;
  state?: string | null;
  items?: LifecycleItem[] | null;
}

const has = <T extends string>(list: readonly T[], value: unknown): value is T => typeof value === 'string' && (list as readonly string[]).includes(value);

export function canMove(current: string, target: string): boolean {
  return has(ITEM_STATES, current) && TRANSITIONS[current].includes(target as AutomationItemState);
}

/** The item state a job implies. A held job is a disconnected account when its channel is not ready, else failed. */
export function jobItemState(jobState: string, channelReady: boolean): AutomationItemState | null {
  if (jobState === 'held') return channelReady ? 'failed' : 'platform_disconnected';
  return JOB_ITEM[jobState] ?? null;
}

/** What the run shows: its generation stage until drafted, then the items' combined state. */
export function status(run: LifecycleRun): string {
  const stage = run.lifecycle || 'planned';
  if (stage !== 'drafted') return stage;
  const states = (run.items ?? []).map((item) => item.state);
  return PRIORITY.find((state) => states.includes(state)) ?? 'drafted';
}

/** Whether the person has something to look at: a problem, or a draft waiting for approval before it can post. */
export function attention(run: LifecycleRun): boolean {
  if (run.lifecycle === 'source_unavailable' || run.lifecycle === 'failed') return true;
  return (run.items ?? []).some((item) => has(ATTENTION, item.state) || (item.state === 'ready_for_review' && Boolean(item.publishAt)));
}

/** The 018 projection's check-constrained state: the generation stage, never a publishing state. */
export function projected(run: LifecycleRun): string {
  const stage = run.lifecycle;
  if (stage == null) return run.state ?? 'pending';
  if (stage === 'planned') return 'pending';
  if (stage === 'researching' || stage === 'drafting') return 'running';
  if (stage === 'drafted') return 'completed';
  if (stage === 'skipped') return 'cancelled';
  return 'failed';
}

export function label(state: string): string {
  return Object.hasOwn(LABELS, state) ? LABELS[state as keyof typeof LABELS] : String(state).replaceAll('_', ' ');
}

export function isTerminal(state: string): boolean {
  return has(ITEM_TERMINAL, state);
}

/** The status-chip roles (`StatusTone`) for each state: in progress spins, problems warn, failures are red. */
export type LifecycleTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'loading';
const TONES: Record<string, LifecycleTone> = {
  planned: 'neutral',
  researching: 'loading',
  drafting: 'loading',
  drafted: 'neutral',
  skipped: 'neutral',
  source_unavailable: 'warning',
  failed: 'danger',
  ready_for_review: 'info',
  needs_revision: 'warning',
  approved: 'success',
  scheduled: 'info',
  publishing: 'loading',
  published: 'success',
  rejected: 'neutral',
  platform_disconnected: 'warning',
  approval_expired: 'warning'
};

export function tone(state: string): LifecycleTone {
  return Object.hasOwn(TONES, state) ? TONES[state] : 'neutral';
}

/** Whether a person with approval rights can decide on an item now (`raffi_run_decide` rules). */
export function decisionsFor(item: LifecycleItem): { approve: boolean; revise: boolean; reject: boolean } {
  // Mirrors campaigns._decide: nothing for a post already handed to the publishing queue; an approval can be
  // withdrawn (changes or reject) until then.
  if (item.jobId) return { approve: false, revise: false, reject: false };
  const open = item.state === 'ready_for_review' || item.state === 'needs_revision';
  const withdrawable = open || item.state === 'approved' || item.state === 'platform_disconnected';
  return { approve: open || item.state === 'platform_disconnected', revise: withdrawable, reject: withdrawable };
}
