/**
 * Browser client for relationship follow-ups (`/api/workspaces/{w}/relationships`). Built on the program's shared
 * requester (guard header, bearer session, `{error, code}` errors); session-only. Changes carry the revision the
 * person last read, creates an idempotency key, so a retried request never makes a second record.
 */
import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import { relationshipQuery } from './relationships-model';
import type {
  RelationshipCreateInput,
  RelationshipEditInput,
  RelationshipFilters,
  RelationshipList,
  RelationshipState,
  RelationshipWrite
} from './relationships-types';

export type RelationshipAction =
  | 'transition'
  | 'reopen'
  | 'snooze'
  | 'unsnooze'
  | 'assign'
  | 'threads'
  | 'notes'
  | 'dismiss-followup'
  | 'restore-followup'
  | 'dismiss-suggestion';

export function createRelationshipsApi(getToken: TokenSource) {
  const request = createRequester(getToken);
  const base = (w: string) => `${ws(w)}/relationships`;
  const one = (w: string, id: string) => `${base(w)}/${seg(id)}`;
  const act = (w: string, id: string, action: RelationshipAction, body: Record<string, unknown>) =>
    request.send<RelationshipWrite>('POST', `${one(w, id)}/${action}`, body);
  return {
    list: (w: string, filters: RelationshipFilters = {}) => request.get<RelationshipList>(`${base(w)}${relationshipQuery(filters)}`),
    detail: (w: string, id: string) => request.get<RelationshipWrite>(one(w, id)),
    create: (w: string, body: RelationshipCreateInput) => request.send<RelationshipWrite>('POST', base(w), body),
    update: (w: string, id: string, revision: number, body: RelationshipEditInput) =>
      request.send<RelationshipWrite>('PATCH', one(w, id), { ...body, expectedRevision: revision }),
    transition: (w: string, id: string, revision: number, to: RelationshipState, extra: { wonResultId?: string; suggestionKey?: string } = {}) =>
      act(w, id, 'transition', { to, ...extra, expectedRevision: revision }),
    reopen: (w: string, id: string, revision: number) => act(w, id, 'reopen', { expectedRevision: revision }),
    snooze: (w: string, id: string, revision: number, until: number) => act(w, id, 'snooze', { until, expectedRevision: revision }),
    unsnooze: (w: string, id: string, revision: number) => act(w, id, 'unsnooze', { expectedRevision: revision }),
    assign: (w: string, id: string, revision: number, ownerId: string | null) => act(w, id, 'assign', { ownerId, expectedRevision: revision }),
    linkThread: (w: string, id: string, revision: number, threadId: string) => act(w, id, 'threads', { threadId, expectedRevision: revision }),
    unlinkThread: (w: string, id: string, revision: number, threadId: string) =>
      request.send<RelationshipWrite>('DELETE', `${one(w, id)}/threads/${seg(threadId)}`, { expectedRevision: revision }),
    addNote: (w: string, id: string, revision: number, text: string) => act(w, id, 'notes', { text, expectedRevision: revision }),
    removeNote: (w: string, id: string, revision: number, noteId: string) =>
      request.send<RelationshipWrite>('DELETE', `${one(w, id)}/notes/${seg(noteId)}`, { expectedRevision: revision }),
    dismissFollowUp: (w: string, id: string, revision: number) => act(w, id, 'dismiss-followup', { expectedRevision: revision }),
    restoreFollowUp: (w: string, id: string, revision: number) => act(w, id, 'restore-followup', { expectedRevision: revision }),
    dismissSuggestion: (w: string, id: string, revision: number, key: string) => act(w, id, 'dismiss-suggestion', { key, expectedRevision: revision })
  };
}

export type RelationshipsApi = ReturnType<typeof createRelationshipsApi>;
