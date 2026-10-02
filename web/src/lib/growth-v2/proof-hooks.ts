'use client';

/**
 * TanStack Query hooks for proof revisions and next-week decisions, keyed `['growth-v2', workspaceId, 'proof', …]`.
 * Off deployments answer 404 `feature_disabled` and the views hide themselves. Deciding invalidates the proof, the
 * strategy list and the Weekly plan (the next plan reads accepted decisions).
 */
import { useMemo } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { createProofApi } from './proof';
import { shouldRetry } from './request';
import type { DecideInput } from './proof-types';

export const proofKeys = {
  all: (w: string) => ['growth-v2', w, 'proof'] as const,
  /** Paged (nextCursor) proofs of one frequency. */
  pages: (w: string, frequency: string) => ['growth-v2', w, 'proof', 'pages', frequency] as const,
  one: (w: string, proofId: string) => ['growth-v2', w, 'proof', 'one', proofId] as const,
  strategy: (w: string) => ['growth-v2', w, 'proof', 'strategy'] as const
};

const PAGE_SIZE = 6;

export function useProofApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createProofApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

/** Proofs of one frequency, newest period first, a page at a time: `fetchNextPage` follows the server's nextCursor. */
export function useProofs(frequency: 'weekly' | 'monthly' = 'weekly') {
  const { api, w, enabled } = useProofApi();
  return useInfiniteQuery({
    queryKey: proofKeys.pages(w, frequency),
    queryFn: ({ pageParam }) => api.list(w, frequency, pageParam, PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled,
    retry: shouldRetry,
    staleTime: 60_000
  });
}

/** One proof by id (a proof link may name a period that isn't on the first page, or the other frequency). */
export function useProof(proofId: string | null) {
  const { api, w, enabled } = useProofApi();
  return useQuery({ queryKey: proofKeys.one(w, proofId ?? ''), queryFn: () => api.get(w, proofId as string), enabled: enabled && Boolean(proofId), retry: shouldRetry, staleTime: 60_000 });
}

export function useStrategy(enabledByCaller = true) {
  const { api, w, enabled } = useProofApi();
  return useQuery({ queryKey: proofKeys.strategy(w), queryFn: () => api.strategy(w), enabled: enabled && enabledByCaller, retry: shouldRetry, staleTime: 60_000 });
}

export function useRefreshProof() {
  const { api, w } = useProofApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ frequency, periodStart }: { frequency: 'weekly' | 'monthly'; periodStart?: string }) => api.refresh(w, frequency, periodStart),
    onSettled: () => client.invalidateQueries({ queryKey: proofKeys.all(w) })
  });
}

export function useDecide() {
  const { api, w } = useProofApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ decisionId, body }: { decisionId: string; body: DecideInput }) => api.decide(w, decisionId, body),
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: proofKeys.all(w) });
      await client.invalidateQueries({ queryKey: ['coworker', w, 'weekly'] });
    }
  });
}
