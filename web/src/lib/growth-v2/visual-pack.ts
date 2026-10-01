/**
 * Visual Pack client (`/api/workspaces/{w}/visual-packs/…`), on the shared growth-v2 requester. Mutations carry an
 * idempotency key per user intent and the revision the person is looking at; replays return the existing result.
 */
import type { TokenSource } from '@/lib/api/client';
import { createRequester, idempotencyKey, seg, ws } from './request';
import type { PackAction, PackEditInput, PackList, PackSettings, PackView } from './visual-pack-types';

const RENDER_TIMEOUT_MS = 60_000;

export function createVisualPackApi(getToken: TokenSource) {
  const request = createRequester(getToken);
  const base = (w: string) => `${ws(w)}/visual-packs`;
  return {
    list: (w: string, cursor?: string | null) => request.get<PackList>(`${base(w)}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`),
    get: (w: string, id: string) => request.get<PackView>(`${base(w)}/${seg(id)}`),
    prepare: (w: string, variantId: string, settings?: Partial<PackSettings>, key = idempotencyKey('vp-prepare')) =>
      request.send<PackView>('POST', base(w), { idempotencyKey: key, variantId, ...(settings ? { settings } : {}) }),
    edit: (w: string, id: string, expectedRevision: number, input: PackEditInput, key = idempotencyKey('vp-edit')) =>
      request.send<PackView>('POST', `${base(w)}/${seg(id)}/revisions`, { idempotencyKey: key, expectedRevision, ...input }),
    act: (w: string, id: string, action: PackAction, expectedRevision: number, confirmed?: boolean) =>
      request.send<PackView>('POST', `${base(w)}/${seg(id)}/${action}`, { expectedRevision, ...(confirmed ? { confirmed: true } : {}) }, RENDER_TIMEOUT_MS),
    /** A server-rendered slide or the export zip; `href` comes from the server's own read-back. */
    file: (href: string) => request.blob(href)
  };
}

export type VisualPackApi = ReturnType<typeof createVisualPackApi>;
