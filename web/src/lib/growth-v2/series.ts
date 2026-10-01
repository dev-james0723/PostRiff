/**
 * Browser client for the Signature Series routes (`/api/workspaces/{w}/series/…`, src/postriff_phase2/series/http.py).
 * Session-only, through the program's shared requester. Every change carries the series revision it was made against
 * and one idempotency key per user intent (a retry of the same intent reuses it), so a double click or a reconnect
 * never applies a change twice and a stale screen gets `revision_conflict` instead of overwriting newer work.
 */
import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import type {
  CandidatePost,
  CandidateSource,
  CandidatesPage,
  ClaimAction,
  CreateSeriesInput,
  DecisionKind,
  DecisionLevel,
  DraftCheck,
  SeriesDetail,
  SeriesMutation,
  SeriesPage,
  SeriesStatus
} from './series-types';

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === false) continue;
    search.set(key, value === true ? '1' : String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export function createSeriesApi(getToken: TokenSource) {
  const request = createRequester(getToken);
  const base = (w: string) => `${ws(w)}/series`;
  const one = (w: string, id: string) => `${base(w)}/${seg(id)}`;
  const episode = (w: string, id: string, episodeId: string) => `${one(w, id)}/episodes/${seg(episodeId)}`;
  const change = (path: string, revision: number, key: string, body: Record<string, unknown> = {}) =>
    request.send<SeriesMutation>('POST', path, { ...body, expectedRevision: revision, idempotencyKey: key });
  return {
    list: (w: string, options: { cursor?: string | null; limit?: number; archived?: boolean } = {}) =>
      request.get<SeriesPage>(`${base(w)}${query({ limit: options.limit ?? 25, cursor: options.cursor, archived: options.archived })}`),
    get: (w: string, id: string) => request.get<SeriesDetail>(one(w, id)),
    posts: (w: string, options: { cursor?: string | null; minAgeDays?: number } = {}) =>
      request.get<CandidatesPage<CandidatePost>>(`${base(w)}/candidates${query({ kind: 'post', cursor: options.cursor, minAgeDays: options.minAgeDays })}`),
    sources: (w: string, options: { cursor?: string | null } = {}) =>
      request.get<CandidatesPage<CandidateSource>>(`${base(w)}/candidates${query({ kind: 'source', cursor: options.cursor })}`),
    create: (w: string, input: CreateSeriesInput, key: string) => request.send<SeriesMutation>('POST', base(w), { ...input, idempotencyKey: key }),
    plan: (w: string, id: string, revision: number, count: number, key: string) => change(`${one(w, id)}/plan`, revision, key, { count }),
    setStatus: (w: string, id: string, revision: number, status: SeriesStatus, key: string) => change(`${one(w, id)}/status`, revision, key, { status }),
    decide: (w: string, id: string, episodeId: string, revision: number, decision: DecisionKind, level: DecisionLevel, key: string) =>
      change(`${episode(w, id, episodeId)}/angle`, revision, key, { decision, level }),
    approve: (w: string, id: string, episodeId: string, revision: number, key: string) => change(`${episode(w, id, episodeId)}/approve`, revision, key),
    checkDraft: (w: string, id: string, episodeId: string, variantId: string) =>
      request.get<DraftCheck>(`${episode(w, id, episodeId)}/drafts/${seg(variantId)}/check`),
    link: (w: string, id: string, episodeId: string, revision: number, variantId: string, acknowledgedWarnings: string[], key: string) =>
      change(`${episode(w, id, episodeId)}/drafts`, revision, key, { variantId, acknowledgedWarnings }),
    unlink: (w: string, id: string, episodeId: string, revision: number, variantId: string, key: string) =>
      change(`${episode(w, id, episodeId)}/drafts/${seg(variantId)}/unlink`, revision, key),
    linkAsset: (w: string, id: string, episodeId: string, revision: number, assetId: string, key: string) =>
      change(`${episode(w, id, episodeId)}/assets`, revision, key, { assetId }),
    unlinkAsset: (w: string, id: string, episodeId: string, revision: number, assetId: string, key: string) =>
      change(`${episode(w, id, episodeId)}/assets/${seg(assetId)}/unlink`, revision, key),
    claim: (w: string, id: string, claimId: string, revision: number, action: ClaimAction, key: string) =>
      change(`${one(w, id)}/claims/${seg(claimId)}`, revision, key, action),
    revoke: (w: string, id: string, decisionId: string, revision: number, key: string) => change(`${one(w, id)}/decisions/${seg(decisionId)}/revoke`, revision, key)
  };
}

export type SeriesApi = ReturnType<typeof createSeriesApi>;
