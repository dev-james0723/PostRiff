import type { PostRiffApi } from '@/lib/api/client';

export const formatMediaCredits = (milli: number) => (milli / 1000).toLocaleString('en-US', { maximumFractionDigits: 1, minimumFractionDigits: 1 });

/** The visible maximum, never a silently promoted typical estimate, authorizes this single read. */
export async function readWithCredit({ api, workspaceId, assetId, idempotencyKey, approvalRequired, approvedMaxMilliCredits, paidUnavailable = false, isCurrent = () => true, onAuthorized, resume, polls = 0, wait = async () => {} }: {
  api: Pick<PostRiffApi, 'creditEstimate' | 'creditQuote' | 'mediaNotes'>;
  workspaceId: string;
  assetId: string;
  idempotencyKey: string;
  approvalRequired: boolean;
  approvedMaxMilliCredits?: number | null;
  paidUnavailable?: boolean;
  isCurrent?: () => boolean;
  onAuthorized?: (body: MediaReadRequest) => void;
  resume?: MediaReadRequest;
  polls?: number;
  wait?: () => Promise<void>;
}) {
  if (resume) {
    if (resume.assetId !== assetId || resume.idempotencyKey !== idempotencyKey) throw new Error('The pending read belongs to another attachment.');
    return isCurrent() ? api.mediaNotes(workspaceId, resume) : null;
  }
  let creditQuoteId: string | undefined;
  if (approvalRequired) {
    const request = { operation: 'media-notes' as const, request: { assetId } };
    const estimate = await api.creditEstimate(workspaceId, request);
    if (!isCurrent()) return null;
    if (!estimate.cached) {
      if (paidUnavailable) throw new Error('Paid photo and video reading is unavailable on Free. Cached notes and manual references remain available.');
      if (!Number.isSafeInteger(approvedMaxMilliCredits) || (approvedMaxMilliCredits ?? 0) <= 0 || (approvedMaxMilliCredits ?? 0) > 100_000_000) throw new Error('Review and approve the maximum credits before reading.');
      if (!Number.isSafeInteger(estimate.ceilingMilliCredits) || estimate.ceilingMilliCredits <= 0 || estimate.ceilingMilliCredits > approvedMaxMilliCredits!) throw new Error('The fresh estimate exceeds your approved maximum. Review the new limit before reading.');
      const quote = await api.creditQuote(workspaceId, { ...request, maxMilliCredits: approvedMaxMilliCredits!, expectedRevision: estimate.stateRevision });
      if (!isCurrent()) return null;
      creditQuoteId = quote.quoteId;
    }
  }
  const body = { assetId, idempotencyKey, ...(creditQuoteId ? { creditQuoteId } : {}) };
  if (!isCurrent()) return null;
  onAuthorized?.(body);
  for (let poll = 0; ; poll++) {
    if (!isCurrent()) return null;
    const result = await api.mediaNotes(workspaceId, body);
    if (result.status !== 'reading' || poll >= polls) return result;
    await wait();
  }
}
export type MediaReadRequest = { assetId: string; idempotencyKey: string; creditQuoteId?: string };
