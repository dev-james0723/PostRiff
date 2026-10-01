'use client';

/**
 * TanStack Query hooks over the Signature Series routes, keyed `['growth-v2', workspaceId, 'series', …]`. A deployment
 * with the feature off answers 404 `feature_disabled`; `seriesOff(query)` lets a surface hide itself. A change writes the
 * re-read series into the cache only after the server answered (never an optimistic success), and one idempotency key
 * is minted per intent and reused if the same intent is retried.
 */
import { useMemo } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { idempotencyKey, isFeatureDisabled, shouldRetry } from './request';
import { createSeriesApi, type SeriesApi } from './series';
import type { CandidatePost, CandidateSource, CandidatesPage, ClaimAction, CreateSeriesInput, DecisionKind, DecisionLevel, SeriesDetail, SeriesMutation, SeriesStatus } from './series-types';

export const seriesKeys = {
  all: (w: string) => ['growth-v2', w, 'series'] as const,
  list: (w: string, archived: boolean) => ['growth-v2', w, 'series', 'list', archived] as const,
  detail: (w: string, id: string) => ['growth-v2', w, 'series', 'detail', id] as const,
  posts: (w: string, minAgeDays: number) => ['growth-v2', w, 'series', 'candidates', 'post', minAgeDays] as const,
  sources: (w: string) => ['growth-v2', w, 'series', 'candidates', 'source'] as const,
  check: (w: string, id: string, episodeId: string, variantId: string) => ['growth-v2', w, 'series', 'check', id, episodeId, variantId] as const
};

export function useSeriesApi(): { api: SeriesApi; w: string; enabled: boolean } {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createSeriesApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

/** True when the query failed only because this deployment has Signature Series switched off. */
export function seriesOff(query: Pick<UseQueryResult, 'error'>): boolean {
  return isFeatureDisabled(query.error);
}

export function useSeriesList(archived = false) {
  const { api, w, enabled } = useSeriesApi();
  return useInfiniteQuery({
    queryKey: seriesKeys.list(w, archived),
    queryFn: ({ pageParam }) => api.list(w, { cursor: pageParam, archived }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled,
    retry: shouldRetry
  });
}

export function useSeries(id: string | null) {
  const { api, w, enabled } = useSeriesApi();
  return useQuery({ queryKey: seriesKeys.detail(w, id ?? ''), queryFn: () => api.get(w, id as string), enabled: enabled && Boolean(id), retry: shouldRetry });
}

export function useSeriesCandidates(kind: 'post' | 'source', minAgeDays: number, enabled: boolean) {
  const { api, w, enabled: ready } = useSeriesApi();
  return useInfiniteQuery({
    queryKey: kind === 'post' ? seriesKeys.posts(w, minAgeDays) : seriesKeys.sources(w),
    queryFn: ({ pageParam }): Promise<CandidatesPage<CandidatePost | CandidateSource>> =>
      kind === 'post' ? api.posts(w, { cursor: pageParam, minAgeDays }) : api.sources(w, { cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: ready && enabled,
    retry: shouldRetry
  });
}

export function useDraftCheck(seriesId: string, episodeId: string, variantId: string | null) {
  const { api, w, enabled } = useSeriesApi();
  return useQuery({
    queryKey: seriesKeys.check(w, seriesId, episodeId, variantId ?? ''),
    queryFn: () => api.checkDraft(w, seriesId, episodeId, variantId as string),
    enabled: enabled && Boolean(variantId),
    retry: shouldRetry,
    staleTime: 0
  });
}

/** One user intent against one series. `revision` is the series revision the person was looking at. */
export type SeriesChange =
  | { kind: 'create'; input: CreateSeriesInput }
  | { kind: 'plan'; id: string; revision: number; count: number }
  | { kind: 'status'; id: string; revision: number; status: SeriesStatus }
  | { kind: 'decide'; id: string; revision: number; episodeId: string; decision: DecisionKind; level: DecisionLevel }
  | { kind: 'approve'; id: string; revision: number; episodeId: string }
  | { kind: 'link'; id: string; revision: number; episodeId: string; variantId: string; acknowledgedWarnings: string[] }
  | { kind: 'unlink'; id: string; revision: number; episodeId: string; variantId: string }
  | { kind: 'linkAsset'; id: string; revision: number; episodeId: string; assetId: string }
  | { kind: 'unlinkAsset'; id: string; revision: number; episodeId: string; assetId: string }
  | { kind: 'claim'; id: string; revision: number; claimId: string; action: ClaimAction }
  | { kind: 'revoke'; id: string; revision: number; decisionId: string };

function run(api: SeriesApi, w: string, change: SeriesChange, key: string): Promise<SeriesMutation> {
  switch (change.kind) {
    case 'create':
      return api.create(w, change.input, key);
    case 'plan':
      return api.plan(w, change.id, change.revision, change.count, key);
    case 'status':
      return api.setStatus(w, change.id, change.revision, change.status, key);
    case 'decide':
      return api.decide(w, change.id, change.episodeId, change.revision, change.decision, change.level, key);
    case 'approve':
      return api.approve(w, change.id, change.episodeId, change.revision, key);
    case 'link':
      return api.link(w, change.id, change.episodeId, change.revision, change.variantId, change.acknowledgedWarnings, key);
    case 'unlink':
      return api.unlink(w, change.id, change.episodeId, change.revision, change.variantId, key);
    case 'linkAsset':
      return api.linkAsset(w, change.id, change.episodeId, change.revision, change.assetId, key);
    case 'unlinkAsset':
      return api.unlinkAsset(w, change.id, change.episodeId, change.revision, change.assetId, key);
    case 'claim':
      return api.claim(w, change.id, change.claimId, change.revision, change.action, key);
    case 'revoke':
      return api.revoke(w, change.id, change.decisionId, change.revision, key);
  }
}

/** The key one intent keeps across retries: the same change object, the same key. */
const keysByIntent = new WeakMap<SeriesChange, string>();

export function useSeriesChange() {
  const client = useQueryClient();
  const { api, w } = useSeriesApi();
  return useMutation({
    mutationFn: (change: SeriesChange) => {
      let key = keysByIntent.get(change);
      if (!key) {
        key = idempotencyKey(`series-${change.kind}`);
        keysByIntent.set(change, key);
      }
      return run(api, w, change, key);
    },
    onSuccess: (data) => {
      const detail: SeriesDetail = { series: data.series, canEdit: data.canEdit, isOwner: data.isOwner };
      client.setQueryData(seriesKeys.detail(w, data.series.id), detail);
      void client.invalidateQueries({ queryKey: seriesKeys.all(w), predicate: (query) => query.queryKey[3] !== 'detail' });
    }
  });
}
