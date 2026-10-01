'use client';

/**
 * TanStack Query hooks for the first-week journey. One query (the server read model) is the single source of truth;
 * every mutation returns the new read model, which replaces the cached one — the UI never claims a change the server
 * did not return.
 */
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { createFirstWeekApi, type FirstWeekApi } from './first-week';
import type { FirstWeekView } from './first-week-types';
import { shouldRetry } from './request';

export const firstWeekKey = (w: string) => ['growth-v2', w, 'first-week'] as const;

export function useFirstWeekApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createFirstWeekApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useFirstWeek() {
  const { api, w, enabled } = useFirstWeekApi();
  return useQuery({ queryKey: firstWeekKey(w), queryFn: () => api.view(w), enabled, retry: shouldRetry, staleTime: 15_000 });
}

/** A journey mutation: `run(api, w, revision)` returns the new read model. */
export function useFirstWeekAction<T>(run: (api: FirstWeekApi, w: string, revision: number, input: T) => Promise<FirstWeekView>) {
  const { api, w } = useFirstWeekApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: T) => {
      const current = client.getQueryData<FirstWeekView>(firstWeekKey(w));
      return run(api, w, current?.revision ?? 0, input);
    },
    onSuccess: (view) => client.setQueryData(firstWeekKey(w), view),
    onError: () => void client.invalidateQueries({ queryKey: firstWeekKey(w) })
  });
}
