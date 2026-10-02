/** Typed client for the proof and strategy routes (`/api/workspaces/{id}/proof`), built on the shared growth-v2 requester. */
import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import type { DecideInput, DecideResult, ProofList, ProofView, RefreshResult, StrategyList } from './proof-types';

function page(params: Record<string, string | null | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  return query.toString();
}

export function createProofApi(getToken: TokenSource) {
  const r = createRequester(getToken);
  return {
    list: (w: string, frequency?: 'weekly' | 'monthly', cursor?: string | null, limit = 10) =>
      r.get<ProofList>(`${ws(w)}/proof/proofs?${page({ frequency, cursor, limit: String(limit) })}`),
    get: (w: string, proofId: string) => r.get<{ proof: ProofView }>(`${ws(w)}/proof/proofs/${seg(proofId)}`),
    /** Owner: recompute a completed period from stored records; appends a revision only when material figures changed. */
    refresh: (w: string, frequency: 'weekly' | 'monthly', periodStart?: string) =>
      r.send<RefreshResult>('POST', `${ws(w)}/proof/refresh`, { frequency, ...(periodStart ? { periodStart } : {}) }),
    strategy: (w: string, status?: string, cursor?: string | null, limit = 25) =>
      r.get<StrategyList>(`${ws(w)}/proof/strategy?${page({ status, cursor, limit: String(limit) })}`),
    decide: (w: string, decisionId: string, body: DecideInput) => r.send<DecideResult>('POST', `${ws(w)}/proof/strategy/${seg(decisionId)}/decide`, body)
  };
}

export type ProofApi = ReturnType<typeof createProofApi>;
