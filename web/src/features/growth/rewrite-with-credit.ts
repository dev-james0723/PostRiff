import type { CreditEstimate, PostDoctorRewriteRequest } from '@/lib/api/types';
import type { createApi } from '@/lib/api/client';

type RewriteApi = Pick<ReturnType<typeof createApi>, 'creditEstimate' | 'creditQuote' | 'postDoctorRewrite'>;
export interface RewriteApproval { request: PostDoctorRewriteRequest; estimate: CreditEstimate }
export class RewriteReviewChanged extends Error {
  constructor(public approval: RewriteApproval) {
    super('The rewrite plan or revision changed. Review the fresh maximum and approve again.');
  }
}
export async function prepareRewrite(api: RewriteApi, workspaceId: string, request: PostDoctorRewriteRequest): Promise<RewriteApproval> {
  const frozen = structuredClone(request);
  const estimate = await api.creditEstimate(workspaceId, { operation: 'post-doctor-rewrite', request: frozen });
  if (estimate.operation !== 'post-doctor-rewrite' || estimate.estimateKind !== 'maximum' || !Number.isSafeInteger(estimate.stateRevision)
    || !Number.isSafeInteger(estimate.ceilingMilliCredits) || estimate.ceilingMilliCredits < 0
    || !Number.isSafeInteger(estimate.availableMilliCredits) || estimate.availableMilliCredits < 0
    || (estimate.cached ? estimate.ceilingMilliCredits !== 0 || estimate.estimateMilliCredits !== 0 : estimate.basis !== 'approved_growth_rewrite_ceiling' || estimate.ceilingMilliCredits <= 0)) {
    throw new Error('A qualified maximum estimate and current revision are required for this rewrite.');
  }
  return { request: frozen, estimate };
}
const binding = (estimate: CreditEstimate) => JSON.stringify([estimate.stateRevision, estimate.ceilingMilliCredits, estimate.model, estimate.provider, estimate.policy, estimate.basis, estimate.estimateKind]);

/** Re-estimate before quoting. A changed binding cannot inherit the previous approval. */
export async function submitApprovedRewrite(api: RewriteApi, workspaceId: string, approval: RewriteApproval, maximum: number | null, onQuoted?: (body: PostDoctorRewriteRequest) => void) {
  if (approval.estimate.cached) return api.postDoctorRewrite(workspaceId, approval.request);
  if (maximum === null || !Number.isSafeInteger(maximum) || maximum < approval.estimate.ceilingMilliCredits) throw new Error('Explicitly approve at least the displayed rewrite maximum.');
  const fresh = await prepareRewrite(api, workspaceId, approval.request);
  if (fresh.estimate.cached) return api.postDoctorRewrite(workspaceId, fresh.request);
  if (binding(fresh.estimate) !== binding(approval.estimate)) throw new RewriteReviewChanged(fresh);
  if (maximum > fresh.estimate.availableMilliCredits) throw new Error('Your approved maximum exceeds the available credits.');
  const expectedRevision = fresh.estimate.stateRevision!;
  const quote = await api.creditQuote(workspaceId, { operation: 'post-doctor-rewrite', request: fresh.request, expectedRevision, maxMilliCredits: maximum });
  if (quote.maxMilliCredits !== maximum) throw new Error('The returned quote does not match your approved maximum. Review again.');
  const body = { ...fresh.request, creditQuoteId: quote.quoteId, expectedRevision };
  onQuoted?.(body);
  return api.postDoctorRewrite(workspaceId, body);
}
