'use client';

/**
 * TanStack Query hooks over the business-results routes, keyed `['growth-v2', workspaceId, 'results', …]`. Lists are
 * cursor pages (25 per page). A change invalidates the results keys only after the server answered; a failed write is
 * never shown as done.
 */
import { useMemo } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  links: (w: string) => ['growth-v2', w, 'results', 'links'] as const
};

/** "All time" starts at the earliest instant the server accepts for a result. */
const ALL_TIME_FROM = 946_684_800;

export function useResultsApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createResultsApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useResultsSummary(days: number | 'all') {
  const { api, w, enabled } = useResultsApi();
  return useQuery({
    queryKey: resultsKeys.summary(w, days),
    queryFn: () => {
      const to = Date.now() / 1000;
      return api.summary(w, { from: days === 'all' ? ALL_TIME_FROM : to - days * 86_400, to });
    },
    enabled,
    staleTime: 60_000,
    retry: shouldRetry
  });
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

function useResultsMutation<V, R>(run: (api: ReturnType<typeof createResultsApi>, w: string, vars: V) => Promise<R>) {
  const { api, w } = useResultsApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: V) => run(api, w, vars),
    onSuccess: () => client.invalidateQueries({ queryKey: resultsKeys.all(w) })
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
  useResultsMutation((api, w, vars: { idempotencyKey: string; label: string; producer: ResultProducer }) => api.createConnection(w, vars));

export const useConnectionAction = () =>
  useResultsMutation((api, w, vars: { id: string; action: ConnectionAction; idempotencyKey: string; expectedRevision: number }) =>
    api.connectionAction(w, vars.id, vars.action, { idempotencyKey: vars.idempotencyKey, expectedRevision: vars.expectedRevision })
  );

export const useCreateLink = () => useResultsMutation((api, w, vars: TrackingLinkInput & { idempotencyKey: string }) => api.createLink(w, vars));

export const useLinkAction = () =>
  useResultsMutation((api, w, vars: { id: string; action: LinkAction; idempotencyKey: string; expectedRevision: number }) =>
    api.linkAction(w, vars.id, vars.action, { idempotencyKey: vars.idempotencyKey, expectedRevision: vars.expectedRevision })
  );
