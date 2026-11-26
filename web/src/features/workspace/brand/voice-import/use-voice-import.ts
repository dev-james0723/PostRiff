'use client';

/**
 * Query hooks over the voice import routes, keyed per workspace. The list route is also the server gate: it answers
 * 404 while voice import is switched off, and every surface built on `useVoiceImports` then renders nothing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys, useAct, useSnapshot } from '@/lib/api/hooks';
import { createVoiceImportApi, voiceImportUnavailable } from '@/lib/api/voice-import';
import { useAuth } from '@/lib/auth/session';
import { anyImportActive } from '@/lib/voice-import/coverage';
import type { VoicePost } from '@/lib/voice-import/types';
import { useWorkspace } from '@/lib/workspace/provider';
import type { BrainAction } from '../brain-types';

export interface PostFilter {
  provider?: string;
  accountKey?: string;
  status?: string;
}

export const voiceImportKeys = {
  view: (w: string) => ['voice-imports', w] as const,
  posts: (w: string, filter: PostFilter = {}) => ['voice-imports', w, 'posts', filter.provider ?? '', filter.accountKey ?? '', filter.status ?? ''] as const
};

const clientAnswer = (error: unknown) => error instanceof ApiError && error.status >= 400 && error.status < 500;

export function useVoiceImportApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createVoiceImportApi(getToken), [getToken]);
  return { api, w: workspaceId ?? '', enabled: Boolean(workspaceId) };
}

/** Runs, coverage and routes. While a run or an AI reading is active and `poll` is set, the receipt refreshes every five seconds. */
export function useVoiceImports(options: { poll?: boolean; enabled?: boolean } = {}) {
  const { api, w, enabled } = useVoiceImportApi();
  const query = useQuery({
    queryKey: voiceImportKeys.view(w),
    queryFn: () => api.list(w),
    enabled: enabled && options.enabled !== false,
    retry: (failures, error) => !clientAnswer(error) && failures < 2,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchInterval: (current) =>
      options.poll && !current.state.error && (anyImportActive(current.state.data) || ['queued', 'running'].includes(current.state.data?.analysis?.status ?? '')) ? 5_000 : false,
    refetchIntervalInBackground: false
  });
  return { query, view: query.data, unavailable: voiceImportUnavailable(query.error) };
}

export function useInvalidateVoiceImports() {
  const client = useQueryClient();
  const { w } = useVoiceImportApi();
  return useCallback(() => client.invalidateQueries({ queryKey: voiceImportKeys.view(w) }), [client, w]);
}

/** A page of up to 50 posts with excerpts, and the next page on demand. Excerpts stay in this query cache and go nowhere else. */
export function useVoicePosts(filter: PostFilter, enabled = true) {
  const { api, w, enabled: ready } = useVoiceImportApi();
  return useInfiniteQuery({
    queryKey: voiceImportKeys.posts(w, filter),
    queryFn: ({ pageParam }) => api.posts(w, { ...filter, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor || undefined,
    enabled: ready && enabled,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false
  });
}

/** Pages read on their own before the person is asked whether to look further back. */
const EVIDENCE_PAGES = 6;

/**
 * The posts a trait cites, by id. The posts route has no id filter, so pages are read 50 at a time until the cited
 * posts are found, the list ends, or six pages have been read; "look further back" then reads six more.
 */
export function useEvidencePosts(ids: string[], enabled: boolean) {
  const query = useVoicePosts({}, enabled);
  const [budget, setBudget] = useState(EVIDENCE_PAGES);
  const pages = query.data?.pages.length ?? 0;
  const index = useMemo(() => {
    const found = new Map<string, VoicePost>();
    for (const page of query.data?.pages ?? []) for (const post of page.posts ?? []) found.set(post.id, post);
    return found;
  }, [query.data]);
  const missing = ids.filter((id) => !index.has(id)).length;
  const { hasNextPage, isFetching, isError, fetchNextPage } = query;
  useEffect(() => {
    if (enabled && missing > 0 && hasNextPage && !isFetching && !isError && pages < budget) void fetchNextPage();
  }, [enabled, missing, hasNextPage, isFetching, isError, pages, budget, fetchNextPage]);
  return {
    posts: ids.map((id) => index.get(id)).filter((post): post is VoicePost => post !== undefined),
    missing,
    searching: isFetching || (enabled && query.isPending),
    /** More pages exist but the automatic budget is used: the person decides whether to keep reading. */
    paused: missing > 0 && hasNextPage && !isFetching && pages >= budget,
    lookFurther: () => setBudget((current) => current + EVIDENCE_PAGES),
    failed: isError
  };
}

/**
 * A workspace action for surfaces without Brand Brain's runner (the Channels sheet): one at a time, with a request
 * id, and a fresh snapshot after a conflict so the next attempt starts from the current revision.
 */
export function useWorkspaceAction(): { run: BrainAction; busy: boolean; error: string } {
  const snapshot = useSnapshot();
  const act = useAct();
  const client = useQueryClient();
  const { w } = useVoiceImportApi();
  const [error, setError] = useState('');
  const running = useRef(false);
  const revision = snapshot.data?.revision;
  const mutate = act.mutateAsync;
  const run = useCallback<BrainAction>(
    async (action, payload) => {
      if (running.current || revision === undefined) return false;
      running.current = true;
      setError('');
      try {
        await mutate({ revision, action, payload: { ...payload, requestId: crypto.randomUUID() } });
        return true;
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 409) await client.invalidateQueries({ queryKey: keys.snapshot(w) });
        setError(failure instanceof Error ? failure.message : '');
        return false;
      } finally {
        running.current = false;
      }
    },
    [client, mutate, revision, w]
  );
  return { run, busy: act.isPending || snapshot.isPending, error };
}
