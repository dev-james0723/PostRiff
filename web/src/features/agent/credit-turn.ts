import type { PostRiffApi } from '@/lib/api/client';
import type { Run } from '@/lib/api/types';

const RESEND_DELAYS_MS = [1500, 4000];

/** No answer came from the application: a network failure, a client timeout, or a proxy error without the app's code. */
function responseLost(error: unknown) {
  if (!(error instanceof Error)) return false;
  const { status, code } = error as Error & { status?: unknown; code?: unknown };
  if (error.name === 'ApiError' && typeof status === 'number') return [502, 503, 504].includes(status) && !code;
  return error instanceof TypeError || error.name === 'TimeoutError' || error.name === 'AbortError';
}

/**
 * Resends the identical request with the same key after a lost response. The server answers a keyed
 * resend from the original run, so a resend never starts or charges a second task.
 */
async function withResend<T>(call: () => Promise<T>, keyed: boolean, isCurrent: () => boolean): Promise<T | null> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await call();
    } catch (error) {
      if (!keyed || !responseLost(error)) throw error;
      if (attempt >= RESEND_DELAYS_MS.length) throw new Error('No answer from the server. Your request may still be running: open it from your conversations before trying again.', { cause: error });
      await new Promise((resolve) => setTimeout(resolve, RESEND_DELAYS_MS[attempt]));
      if (!isCurrent()) return null;
    }
  }
}

/** The request body a credit quote (and its estimate) binds: writing only, web research off. */
export function creditRequestFor(request: Record<string, unknown>): Record<string, unknown> {
  const payload = structuredClone(request);
  payload.research = false;
  delete payload.idempotencyKey;
  delete payload.creditQuoteId;
  return payload;
}

interface Submission {
  api: Pick<PostRiffApi, 'snapshot' | 'creditQuote' | 'turn'>;
  workspaceId: string;
  conversationId: string;
  request: Record<string, unknown>;
  maxMilliCredits: number | null;
  isCurrent?: () => boolean;
}

/** Approve and submit one immutable follow-up; a lost response is resent with the same key, never re-approved or re-routed. */
export async function submitConversationTurn({ api, workspaceId, conversationId, request, maxMilliCredits, isCurrent = () => true }: Submission): Promise<Run | null> {
  const payload = structuredClone(request);
  if (maxMilliCredits !== null) {
    if (!Number.isSafeInteger(maxMilliCredits) || maxMilliCredits <= 0 || maxMilliCredits > 100_000_000) throw new Error('Choose a valid maximum credit limit.');
    const image = payload.imageGeneration as { enabled?: boolean } | undefined;
    if (payload.research === true || image?.enabled) throw new Error('This credit approval covers writing only.');
    payload.research = false;
    if (!isCurrent()) return null;
    const current = await api.snapshot(workspaceId);
    if (!isCurrent()) return null;
    const quote = await api.creditQuote(workspaceId, { operation: 'turn', conversationId, request: payload, expectedRevision: current.revision, maxMilliCredits });
    if (!isCurrent()) return null;
    payload.creditQuoteId = quote.quoteId;
    payload.expectedRevision = current.revision;
  }
  return isCurrent() ? withResend(() => api.turn(workspaceId, conversationId, payload), typeof payload.idempotencyKey === 'string', isCurrent) : null;
}

interface QuickSubmission {
  api: Pick<PostRiffApi, 'creditQuote' | 'quickStart'>;
  workspaceId: string;
  expectedRevision: number;
  request: Record<string, unknown>;
  maxMilliCredits: number | null;
  isCurrent?: () => boolean;
}

/** Home uses the same server-bound limit while keeping the existing quick-start service. */
export async function submitQuickStart({ api, workspaceId, expectedRevision, request, maxMilliCredits, isCurrent = () => true }: QuickSubmission): Promise<Run | null> {
  const payload = structuredClone(request);
  if (maxMilliCredits !== null) {
    if (!Number.isSafeInteger(maxMilliCredits) || maxMilliCredits <= 0 || maxMilliCredits > 100_000_000) throw new Error('Choose a valid maximum credit limit.');
    const image = payload.imageGeneration as { enabled?: boolean } | undefined;
    if (payload.research === true || image?.enabled) throw new Error('This credit approval covers writing only.');
    payload.research = false;
    if (!isCurrent()) return null;
    const quote = await api.creditQuote(workspaceId, { operation: 'quick-start', request: payload, expectedRevision, maxMilliCredits });
    if (!isCurrent()) return null;
    payload.creditQuoteId = quote.quoteId;
  }
  return isCurrent() ? withResend(() => api.quickStart(workspaceId, expectedRevision, payload), typeof payload.idempotencyKey === 'string', isCurrent) : null;
}
