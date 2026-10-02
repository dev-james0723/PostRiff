'use client';

/**
 * TanStack Query hooks for relationship follow-ups, keyed `['growth-v2', workspaceId, 'relationships', …]`. A deployment
 * with the feature off answers 404 `feature_disabled`; `followUpsOff(query)` lets a view hide itself instead of showing
 * an error. Every change stores the server's read-back and refreshes lists and Attention; nothing is shown as saved
 * unless the server returned it.
 */
import { useCallback, useMemo } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { coworkerKeys } from '@/lib/coworker/hooks';
import { useWorkspace } from '@/lib/workspace/provider';
import { isFeatureDisabled, shouldRetry } from './request';
import { createRelationshipsApi, type RelationshipsApi } from './relationships';
import type { RelationshipFilters, RelationshipWrite } from './relationships-types';

export const relationshipKeys = {
  all: (w: string) => ['growth-v2', w, 'relationships'] as const,
  list: (w: string, filters: RelationshipFilters) => ['growth-v2', w, 'relationships', 'list', filters] as const,
  /** Every loaded page of a list (refetched together, so a change never collapses it back to the first page). */
  pages: (w: string, filters: Omit<RelationshipFilters, 'cursor'>) => ['growth-v2', w, 'relationships', 'list', 'pages', filters] as const,
  detail: (w: string, id: string) => ['growth-v2', w, 'relationships', 'detail', id] as const
};

export function useRelationshipsApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createRelationshipsApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

/** True when the query failed only because this deployment has follow-ups switched off. */
export function followUpsOff(query: { error: unknown }): boolean {
  return isFeatureDisabled(query.error);
}

export function useRelationshipList(filters: RelationshipFilters, options: { enabled?: boolean } = {}) {
  const { api, w, enabled } = useRelationshipsApi();
  return useQuery({
    queryKey: relationshipKeys.list(w, filters),
    queryFn: () => api.list(w, filters),
    enabled: enabled && options.enabled !== false,
    retry: shouldRetry,
    staleTime: 15_000
  });
}

/**
 * A list read page by page ("Load more"). After any change the loaded pages refetch together from the first, so the list
 * stays as long as the person made it and every row is current (a closed follow-up leaves, a moved due time reorders).
 */
export function useRelationshipPages(filters: Omit<RelationshipFilters, 'cursor'>) {
  const { api, w, enabled } = useRelationshipsApi();
  return useInfiniteQuery({
    queryKey: relationshipKeys.pages(w, filters),
    queryFn: ({ pageParam }) => api.list(w, pageParam ? { ...filters, cursor: pageParam } : filters),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled,
    retry: shouldRetry,
    staleTime: 15_000
  });
}

export function useRelationship(id: string | null | undefined) {
  const { api, w, enabled } = useRelationshipsApi();
  return useQuery({
    queryKey: relationshipKeys.detail(w, id ?? ''),
    queryFn: () => api.detail(w, id as string),
    enabled: enabled && Boolean(id),
    retry: shouldRetry
  });
}

/**
 * Run one change and keep the server's read-back. Returns the write, so a caller can offer Undo with the new revision.
 * Errors propagate unchanged (the caller shows them; a failed write never becomes a success message).
 */
export function useRelationshipChange() {
  const { api, w } = useRelationshipsApi();
  const client = useQueryClient();
  return useCallback(
    async (run: (api: RelationshipsApi, w: string) => Promise<RelationshipWrite>) => {
      const result = await run(api, w);
      client.setQueryData(relationshipKeys.detail(w, result.relationship.id), result);
      void client.invalidateQueries({ queryKey: relationshipKeys.all(w), predicate: (query) => query.queryKey[3] === 'list' });
      void client.invalidateQueries({ queryKey: coworkerKeys.attention(w) });
      return result;
    },
    [api, w, client]
  );
}

/** After a conflict or a refusal, re-read what the server holds now. */
export function useRelationshipRefresh() {
  const { w } = useRelationshipsApi();
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries({ queryKey: relationshipKeys.all(w) }), [client, w]);
}
