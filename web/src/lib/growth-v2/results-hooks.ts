'use client';

/**
 * TanStack Query hooks over the business-results routes, keyed `['growth-v2', workspaceId, 'results', …]`. Lists are
 * cursor pages (25 per page). A change invalidates the results keys only after the server answered; a failed write is
 * never shown as done.
 */
import { useCallback, useEffect, useMemo } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { shouldRetry } from './request';
import { createResultsApi } from './results';
import type { ConnectionAction, LinkAction, ResultDeclaration, ResultFilters, ResultProducer, TrackingLinkInput } from './results-types';

export const resultsKeys = {
  all: (w: string) => ['growth-v2', w, 'results'] as const,
  summary: (w: string, days: number | 'all') => ['growth-v2', w, 'results', 'summary', days] as const,
  events: (w: string, filters: ResultFilters) => ['growth-v2', w, 'results', 'events', filters] as const,
  connections: (w: string) => ['growth-v2', w, 'results', 'connections'] as const,
  links: (w: string) => ['growth-v2', w, 'results', 'links'] as const,
  linkChoices: (w: string) => ['growth-v2', w, 'results', 'links', 'choices'] as const
};

/** "All time" starts at the earliest instant the server accepts for a result. */
const ALL_TIME_FROM = 946_684_800;
/** A picker loads link pages of 50 one after another up to this many (a workspace has at most 200 active links). */
const LINK_CHOICE_PAGES = 10;

export function useResultsApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createResultsApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

/**
 * The current period always ends at the server's "now" (no `to` is sent), so whether it is still open, and the state it
 * reads as, never depends on this device's clock or the request's latency.
 */
export function useResultsSummary(days: number | 'all') {
  const { api, w, enabled } = useResultsApi();
  return useQuery({
    queryKey: resultsKeys.summary(w, days),
    queryFn: () => api.summary(w, { from: days === 'all' ? ALL_TIME_FROM : Date.now() / 1000 - days * 86_400 }),
    enabled,
    staleTime: 60_000,
    retry: shouldRetry
  });
}

/** Re-read every results view (after the server refused a stale choice, e.g. a result that was reversed meanwhile). */
export function useResultsRefresh() {
  const { w } = useResultsApi();
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries({ queryKey: resultsKeys.all(w) }), [client, w]);
}

export function useResultsLedger(filters: ResultFilters, on = true) {
  const { api, w, enabled } = useResultsApi();
  return useInfiniteQuery({
    queryKey: resultsKeys.events(w, filters),
    queryFn: ({ pageParam }) => api.events(w, { ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled: enabled && on,
    retry: shouldRetry
  });
}

export function useResultConnections(on = true) {
  const { api, w, enabled } = useResultsApi();
  return useQuery({ queryKey: resultsKeys.connections(w), queryFn: () => api.connections(w), enabled: enabled && on, retry: shouldRetry });
}

export function useTrackingLinks(on = true) {
  const { api, w, enabled } = useResultsApi();
  return useInfiniteQuery({
    queryKey: resultsKeys.links(w),
    queryFn: ({ pageParam }) => api.links(w, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled: enabled && on,
    retry: shouldRetry
  });
}

/**
 * Every link a result can be tied to, for a picker: pages of 50 loaded one after another (bounded), so the choice is not
 * cut off at the first page.
 */
export function useTrackingLinkChoices(on = true) {
  const { api, w, enabled } = useResultsApi();
  const query = useInfiniteQuery({
    queryKey: resultsKeys.linkChoices(w),
    queryFn: ({ pageParam }) => api.links(w, pageParam, 50),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled: enabled && on,
    retry: shouldRetry
  });
  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = query;
  const loaded = query.data?.pages.length ?? 0;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError && loaded < LINK_CHOICE_PAGES) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, isError, loaded, fetchNextPage]);
  return query;
}

function useResultsMutation<V, R>(run: (api: ReturnType<typeof createResultsApi>, w: string, vars: V) => Promise<R>, options: { secret?: boolean } = {}) {
  const { api, w } = useResultsApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: V) => run(api, w, vars),
    // An answer that can carry a connection secret is dropped from the mutation cache as soon as its dialog lets go.
    ...(options.secret ? { gcTime: 0 } : {}),
    onSuccess: () => client.invalidateQueries({ queryKey: resultsKeys.all(w) }),
    // A refusal because what is shown is out of date (409: changed meanwhile, or already in that state; 404: gone) reloads it,
    // so the next attempt starts from what the server holds now.
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) void client.invalidateQueries({ queryKey: resultsKeys.all(w) });
    }
  });
}

export const useDeclareResult = () =>
  useResultsMutation((api, w, vars: ResultDeclaration & { idempotencyKey: string }) => api.declare(w, vars));

export const useAmendResult = () =>
  useResultsMutation((api, w, vars: { id: string; body: ResultDeclaration & { idempotencyKey: string; expectedRevision: number } }) =>
    api.amend(w, vars.id, vars.body)
  );

export const useReverseResult = () =>
  useResultsMutation((api, w, vars: { id: string; body: { idempotencyKey: string; expectedRevision: number; note?: string | null } }) =>
    api.reverse(w, vars.id, vars.body)
  );

export const useCreateConnection = () =>
  useResultsMutation((api, w, vars: { idempotencyKey: string; label: string; producer: ResultProducer }) => api.createConnection(w, vars), { secret: true });

export const useConnectionAction = () =>
  useResultsMutation(
    (api, w, vars: { id: string; action: ConnectionAction; idempotencyKey: string; expectedRevision: number }) =>
      api.connectionAction(w, vars.id, vars.action, { idempotencyKey: vars.idempotencyKey, expectedRevision: vars.expectedRevision }),
    { secret: true }
  );

export const useCreateLink = () => useResultsMutation((api, w, vars: TrackingLinkInput & { idempotencyKey: string }) => api.createLink(w, vars));

export const useLinkAction = () =>
  useResultsMutation((api, w, vars: { id: string; action: LinkAction; idempotencyKey: string; expectedRevision: number }) =>
    api.linkAction(w, vars.id, vars.action, { idempotencyKey: vars.idempotencyKey, expectedRevision: vars.expectedRevision })
  );
