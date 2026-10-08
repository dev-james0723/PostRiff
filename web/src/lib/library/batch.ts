/**
 * Batch actions on selected Library items (UI spec §5, A063): every item gets its own outcome and its own
 * idempotency key, retries reuse that key, and the optimistic view rolls back for anything that did not apply.
 *
 * No '@/' imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

export type BatchStatus = 'pending' | 'applied' | 'skipped' | 'conflict' | 'denied' | 'failed';

export interface BatchOutcome {
  id: string;
  status: BatchStatus;
  message?: string;
  /** Only failures that might succeed unchanged are offered again. Conflicts need a refresh; denials never retry. */
  retryable?: boolean;
}

export interface BatchSummary {
  total: number;
  applied: number;
  skipped: number;
  conflict: number;
  denied: number;
  failed: number;
  pending: number;
  /** Items to send again with the same keys. */
  retryIds: string[];
  /** Items whose optimistic change must be undone on screen. */
  rollbackIds: string[];
  done: boolean;
  label: string;
}

function countWord(count: number, singular: string, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/**
 * One line that never claims more than happened: "3 items updated", or "2 of 4 updated · 1 not allowed · 1 failed".
 * `verb` is the past participle for the action ("updated", "deleted", "added").
 */
export function reduceBatchOutcomes(outcomes: readonly BatchOutcome[], verb = 'updated'): BatchSummary {
  const tally = { applied: 0, skipped: 0, conflict: 0, denied: 0, failed: 0, pending: 0 };
  const retryIds: string[] = [];
  const rollbackIds: string[] = [];
  for (const outcome of outcomes) {
    tally[outcome.status] += 1;
    if (outcome.status === 'failed' && outcome.retryable !== false) retryIds.push(outcome.id);
    if (outcome.status === 'conflict' || outcome.status === 'denied' || outcome.status === 'failed') rollbackIds.push(outcome.id);
  }
  const total = outcomes.length;
  const done = tally.pending === 0;
  let label: string;
  if (total === 0) label = 'Nothing selected';
  else if (tally.applied === total) label = `${countWord(total, 'item')} ${verb}`;
  else {
    const parts = [`${tally.applied} of ${total} ${verb}`];
    if (tally.skipped) parts.push(`${tally.skipped} skipped`);
    if (tally.conflict) parts.push(`${tally.conflict} changed elsewhere`);
    if (tally.denied) parts.push(`${tally.denied} not allowed`);
    if (tally.failed) parts.push(`${tally.failed} failed`);
    if (tally.pending) parts.push(`${tally.pending} in progress`);
    label = parts.join(' · ');
  }
  return { total, ...tally, retryIds, rollbackIds, done, label };
}

/** The server's ActionResult status, per item. A replayed key means the first attempt already applied. */
export function outcomeFromActionResult(id: string, result: { status: string; warnings?: readonly string[]; replayed?: boolean } | null | undefined): BatchOutcome {
  const warning = result?.warnings?.find(Boolean);
  switch (result?.status) {
    case 'applied':
      return { id, status: 'applied', message: result.replayed ? 'Already done' : undefined };
    case 'requires_confirmation':
      return { id, status: 'skipped', message: warning ?? 'Needs your confirmation first', retryable: false };
    case 'conflict':
      return { id, status: 'conflict', message: warning ?? 'Changed elsewhere. Refresh, then try again.', retryable: false };
    case 'denied':
      return { id, status: 'denied', message: warning ?? 'Not allowed for your role or this item.', retryable: false };
    default:
      return { id, status: 'failed', message: warning ?? 'No result came back.', retryable: true };
  }
}

/**
 * An HTTP failure, per item. `operation` matters for 404: a delete whose item is already gone did what was asked
 * (for example, a retry after a lost response), while any other write to a missing item is not allowed.
 */
export function outcomeFromError(id: string, error: { status?: number; code?: string; message?: string } | null | undefined, operation: 'delete' | 'update' = 'update'): BatchOutcome {
  const status = typeof error?.status === 'number' ? error.status : 0;
  const message = error?.message || undefined;
  if (status === 409) return { id, status: 'conflict', message: message ?? 'Changed elsewhere. Refresh, then try again.', retryable: false };
  if (status === 401 || status === 403) return { id, status: 'denied', message: message ?? 'Not allowed for your role or this item.', retryable: false };
  if (status === 404) {
    return operation === 'delete'
      ? { id, status: 'skipped', message: 'Already removed or unavailable', retryable: false }
      : { id, status: 'denied', message: 'This item is unavailable.', retryable: false };
  }
  if (status === 503 && error?.code === 'library_capability_unavailable') return { id, status: 'failed', message: 'Not available in this version yet.', retryable: false };
  if (status === 0 || status === 408 || status === 429 || status >= 500) return { id, status: 'failed', message: message ?? 'The request didn’t finish.', retryable: true };
  return { id, status: 'failed', message: message ?? 'The request was refused.', retryable: false };
}

/** Server rule: 16–120 characters of [A-Za-z0-9_.:-]. */
const KEY_PATTERN = /^[A-Za-z0-9_.:-]{16,120}$/;

export function newIdempotencyKey(prefix: string, random: () => string): string {
  const key = `${prefix}-${random()}`.replace(/[^A-Za-z0-9_.:-]/g, '').slice(0, 120);
  return KEY_PATTERN.test(key) ? key : `${key}${'0'.repeat(Math.max(0, 16 - key.length))}`;
}

/**
 * The idempotency key for one item of one batch run. The first attempt creates it; every retry of the same run
 * gets the same key back, so a succeeded mutation is never applied twice.
 */
export function idempotencyKeyFor(keys: Readonly<Record<string, string>>, runId: string, itemId: string, make: () => string): { key: string; keys: Record<string, string> } {
  const slot = `${runId}:${itemId}`;
  const existing = keys[slot];
  if (existing) return { key: existing, keys: { ...keys } };
  const key = make();
  return { key, keys: { ...keys, [slot]: key } };
}

/** Merge new outcomes into a run's list by item id (a retry replaces that item's earlier outcome). */
export function mergeOutcomes(previous: readonly BatchOutcome[], next: readonly BatchOutcome[]): BatchOutcome[] {
  const byId = new Map(previous.map((outcome) => [outcome.id, outcome]));
  for (const outcome of next) byId.set(outcome.id, outcome);
  return [...byId.values()];
}

export const OUTCOME_TEXT: Record<BatchStatus, string> = {
  pending: 'In progress',
  applied: 'Done',
  skipped: 'Skipped',
  conflict: 'Changed elsewhere',
  denied: 'Not allowed',
  failed: 'Failed'
};
