import type { FounderMode, RecordsQueryInput } from './types';

/**
 * The body for `POST /workspace/{mode}/query` (`workspace.py::query`). Live accepts exactly the five required keys
 * and rejects anything else with VALIDATION_FAILED; Demo may add plan / billing cycle / sort / direction. The page
 * never widens the contract from the browser.
 */
export const RECORDS_PAGE_SIZE = 50;

export function recordsQueryBody(mode: FounderMode, input: RecordsQueryInput): Record<string, unknown> {
  const body: Record<string, unknown> = {
    collection: input.collection,
    search: input.search.slice(0, 160),
    status: input.status || 'all',
    page: Math.max(1, Math.floor(input.page)),
    recordId: input.recordId ?? ''
  };
  if (mode !== 'demo') return body;
  if (input.plan && input.plan !== 'all') body.plan = input.plan;
  if (input.billingCycle && input.billingCycle !== 'all') body.billingCycle = input.billingCycle;
  if (input.sort) {
    body.sort = input.sort;
    body.direction = input.direction ?? 'asc';
  }
  return body;
}

/** Pages a result spans; at least one so the pager always reads "Page 1 of 1". */
export function pageCount(total: number | undefined, pageSize: number | undefined): number {
  if (!total || !pageSize) return 1;
  return Math.max(1, Math.ceil(total / pageSize));
}

/** Demo sort keys the server accepts (`workspace.py`); anything else is dropped before the request. */
export const DEMO_SORTS = new Set(['id', 'name', 'company', 'email', 'status', 'plan', 'amountMinor', 'at', 'createdAt', 'renewsAt', 'creditsUsed', 'quantity']);
