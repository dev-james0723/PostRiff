'use client';

/**
 * TanStack Query hooks for the opportunity brief. Keys follow the growth-v2 convention
 * `['growth-v2', workspaceId, 'briefs', …]`. A deployment with the brief off answers 404 `feature_disabled`;
 * callers hide the card on `isFeatureDisabled(query.error)`. A mutation is reported as done only when the server
 * read it back (`verified`).
 */
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { keys as apiKeys } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { coworkerKeys } from '@/lib/coworker/hooks';
import { useWorkspace } from '@/lib/workspace/provider';
import { createBriefsApi } from './briefs';
import { briefRefreshScopes, type BriefRefreshScope } from './briefs-present';
import { shouldRetry } from './request';
import type { BriefActionInput } from './briefs-types';

export const briefKeys = {
  all: (w: string) => ['growth-v2', w, 'briefs'] as const,
  current: (w: string) => ['growth-v2', w, 'briefs', 'current'] as const,
  history: (w: string) => ['growth-v2', w, 'briefs', 'history'] as const
};

/** The queries behind each scope a brief action can change (see `briefRefreshScopes`). The trend pools are every
 *  `['trends', w, 'opportunities', …]` query (Weekly's pool preview included); Radar's saved ideas live in its scans. */
const SCOPE_KEYS: Record<BriefRefreshScope, (w: string) => readonly unknown[]> = {
  snapshot: (w) => apiKeys.snapshot(w),
  trendPool: (w) => ['trends', w, 'opportunities'],
  listening: (w) => coworkerKeys.listening(w),
  radar: (w) => ['radar-scans', w]
};

export function useBriefsApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createBriefsApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useBrief() {
  const { api, w, enabled } = useBriefsApi();
  return useQuery({ queryKey: briefKeys.current(w), queryFn: () => api.current(w), enabled, retry: shouldRetry, staleTime: 60_000 });
}

export function useBriefAction() {
  const { api, w } = useBriefsApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, body }: { itemId: string; body: BriefActionInput }) => api.act(w, itemId, body),
    // Awaited, so the saved idea is in the snapshot before the "Open the idea" link is offered.
    onSuccess: (result, { body }) =>
      Promise.all(briefRefreshScopes(body.action, Boolean(result.outcome)).map((scope) => client.invalidateQueries({ queryKey: SCOPE_KEYS[scope](w) }))),
    onSettled: () => client.invalidateQueries({ queryKey: briefKeys.all(w) })
  });
}
