/** Typed client for the opportunity brief routes (`/api/workspaces/{id}/briefs`), built on the shared growth-v2 requester. */
import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import type { BriefActionInput, BriefActionResult, BriefCurrent, BriefHistory } from './briefs-types';

export function createBriefsApi(getToken: TokenSource) {
  const r = createRequester(getToken);
  return {
    /** Composed from stored evidence on the server; the read writes nothing and starts no research. */
    current: (w: string) => r.get<BriefCurrent>(`${ws(w)}/briefs/current`),
    history: (w: string, cursor?: string | null, limit = 25) => {
      const query = new URLSearchParams({ limit: String(limit) });
      if (cursor) query.set('cursor', cursor);
      return r.get<BriefHistory>(`${ws(w)}/briefs/editions?${query.toString()}`);
    },
    act: (w: string, itemId: string, body: BriefActionInput) => r.send<BriefActionResult>('POST', `${ws(w)}/briefs/items/${seg(itemId)}/action`, body)
  };
}

export type BriefsApi = ReturnType<typeof createBriefsApi>;
