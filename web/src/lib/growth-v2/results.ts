/**
 * Business results client (G2-OUT): `/api/workspaces/{id}/results/…`, session-only. Every change carries an
 * idempotency key for one user intent (a retry reuses it); changes to an existing connection or link also carry the
 * revision the person saw. A disabled deployment answers 404 `feature_disabled` (see `isFeatureDisabled`).
 */
import type { TokenSource } from '@/lib/api/client';
import { createRequester, seg, ws } from './request';
import type {
  ConnectionAction,
  ConnectionSecret,
  LinkAction,
  ResultConnections,
  ResultDeclaration,
  ResultFilters,
  ResultMutation,
  ResultProducer,
  ResultsPage,
  ResultsSummary,
  TrackingLink,
  TrackingLinkInput,
  TrackingLinks
} from './results-types';

type Keyed = { idempotencyKey: string };
type Revised = Keyed & { expectedRevision: number };

function query(values: object): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if ((typeof value === 'string' && value !== '') || typeof value === 'number') params.set(key, String(value));
  const text = params.toString();
  return text ? `?${text}` : '';
}

export function createResultsApi(getToken: TokenSource) {
  const r = createRequester(getToken);
  const base = (w: string) => `${ws(w)}/results`;
  return {
    summary: (w: string, range: { from?: number; to?: number } = {}) => r.get<ResultsSummary>(`${base(w)}/summary${query(range)}`),
    events: (w: string, filters: ResultFilters & { cursor?: string; limit?: number } = {}) => r.get<ResultsPage>(`${base(w)}/events${query(filters)}`),
    declare: (w: string, body: ResultDeclaration & Keyed) => r.send<ResultMutation>('POST', `${base(w)}/events`, body),
    amend: (w: string, id: string, body: ResultDeclaration & Revised) => r.send<ResultMutation>('POST', `${base(w)}/events/${seg(id)}/amend`, body),
    reverse: (w: string, id: string, body: Revised & { note?: string | null }) => r.send<ResultMutation>('POST', `${base(w)}/events/${seg(id)}/reverse`, body),
    connections: (w: string) => r.get<ResultConnections>(`${base(w)}/connections`),
    createConnection: (w: string, body: Keyed & { label: string; producer: ResultProducer }) => r.send<ConnectionSecret>('POST', `${base(w)}/connections`, body),
    connectionAction: (w: string, id: string, action: ConnectionAction, body: Revised) =>
      r.send<ConnectionSecret>('POST', `${base(w)}/connections/${seg(id)}/${action}`, body),
    links: (w: string, cursor?: string, limit?: number) => r.get<TrackingLinks>(`${base(w)}/links${query({ cursor, limit })}`),
    createLink: (w: string, body: TrackingLinkInput & Keyed) => r.send<{ link: TrackingLink; replayed: boolean }>('POST', `${base(w)}/links`, body),
    linkAction: (w: string, id: string, action: LinkAction, body: Revised) =>
      r.send<{ link: TrackingLink; replayed: boolean }>('POST', `${base(w)}/links/${seg(id)}/${action}`, body)
  };
}

export type ResultsApi = ReturnType<typeof createResultsApi>;
