import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import type { ContinuationImport, FirstWeekView, HandoffState } from './first-week-types';

/** Typed client for `/api/workspaces/{id}/first-week/…`. Every mutation carries the journey revision it was read at. */
export function createFirstWeekApi(getToken: TokenSource) {
  const r = createRequester(getToken);
  const base = (w: string) => `${ws(w)}/first-week`;
  return {
    view: (w: string) => r.get<FirstWeekView>(base(w)),
    importContinuation: (w: string, body: { idempotencyKey: string; consent: true; platform: string; language: string; items: { kind: string; text: string }[] }) =>
      r.send<ContinuationImport>('POST', `${base(w)}/continuations`, body),
    start: (w: string, body: { idempotencyKey: string; consent: true; text: string; platform: string; language: string }) =>
      r.send<ContinuationImport>('POST', `${base(w)}/start`, body),
    setContext: (w: string, body: { purpose: string; audience: string; mode?: string; subject?: string; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/context`, body),
    accept: (w: string, body: { variantId: string; variantRevision: number; expectedRevision: number }) => r.send<FirstWeekView>('POST', `${base(w)}/accept`, body),
    plan: (w: string, body: { platform?: string; channelId?: string | null; postsPerWeek: number; timeZone: string; language?: string; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/plan`, body),
    scope: (w: string, body: { slotIds: string[]; reason?: string; expectedRevision: number }) => r.send<FirstWeekView>('POST', `${base(w)}/scope`, body),
    draft: (w: string, body: { confirmed: true; maxCredits?: number; expectedRevision: number }) =>
      r.send<{ prepare: { advanced: boolean; drafted: number; draftedSlotIds: string[] }; journey: FirstWeekView }>('POST', `${base(w)}/draft`, body, 150_000),
    write: (w: string, slotId: string, body: { weekId: string; text: string; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/slots/${seg(slotId)}/write`, body),
    handoff: (w: string, slotId: string, body: { weekId: string; action: HandoffState | 'undo'; expectedRevision: number }) =>
      r.send<FirstWeekView>('POST', `${base(w)}/slots/${seg(slotId)}/handoff`, body)
  };
}

export type FirstWeekApi = ReturnType<typeof createFirstWeekApi>;
