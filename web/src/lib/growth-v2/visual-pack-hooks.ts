'use client';

/**
 * TanStack Query hooks for Visual Packs, keyed `['growth-v2', workspaceId, 'visual-packs', …]`. Every mutation writes
 * the server's read-back into the cache (never an optimistic guess) and a refused write stays an error.
 */
import { useMemo } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { downloadBlob } from '@/lib/download';
import { useWorkspace } from '@/lib/workspace/provider';
import { shouldRetry } from './request';
import { createVisualPackApi } from './visual-pack';
import type { PackAction, PackEditInput, PackSettings, PackView } from './visual-pack-types';

export const visualPackKeys = {
  all: (w: string) => ['growth-v2', w, 'visual-packs'] as const,
  list: (w: string) => ['growth-v2', w, 'visual-packs', 'list'] as const,
  pack: (w: string, id: string) => ['growth-v2', w, 'visual-packs', 'pack', id] as const,
  file: (w: string, href: string) => ['growth-v2', w, 'visual-packs', 'file', href] as const
};

export function useVisualPackApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createVisualPackApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useVisualPacks() {
  const { api, w, enabled } = useVisualPackApi();
  return useInfiniteQuery({
    queryKey: visualPackKeys.list(w),
    queryFn: ({ pageParam }) => api.list(w, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    enabled,
    retry: shouldRetry,
    staleTime: 30_000
  });
}

export function useVisualPack(id: string | null) {
  const { api, w, enabled } = useVisualPackApi();
  return useQuery({ queryKey: visualPackKeys.pack(w, id ?? ''), queryFn: () => api.get(w, id as string), enabled: enabled && Boolean(id), retry: shouldRetry });
}

/** One server-rendered file as a Blob. A slide's bytes never change for its revision, so it is fetched once. */
export function usePackFile(href: string | null) {
  const { api, w, enabled } = useVisualPackApi();
  return useQuery({ queryKey: visualPackKeys.file(w, href ?? ''), queryFn: () => api.file(href as string), enabled: enabled && Boolean(href), staleTime: Infinity, retry: shouldRetry });
}

function useStore() {
  const client = useQueryClient();
  const { w } = useVisualPackApi();
  return (view: PackView) => {
    client.setQueryData(visualPackKeys.pack(w, view.pack.id), view);
    void client.invalidateQueries({ queryKey: visualPackKeys.list(w) });
  };
}

export function usePrepareVisualPack() {
  const { api, w } = useVisualPackApi();
  const store = useStore();
  return useMutation({
    mutationFn: ({ variantId, settings, key }: { variantId: string; settings?: Partial<PackSettings>; key: string }) => api.prepare(w, variantId, settings, key),
    onSuccess: store
  });
}

export function useEditVisualPack(id: string) {
  const { api, w } = useVisualPackApi();
  const store = useStore();
  return useMutation({
    mutationFn: ({ expectedRevision, input, key }: { expectedRevision: number; input: PackEditInput; key: string }) => api.edit(w, id, expectedRevision, input, key),
    onSuccess: store
  });
}

export function usePackAction(id: string) {
  const { api, w } = useVisualPackApi();
  const store = useStore();
  return useMutation({
    mutationFn: ({ action, expectedRevision, confirmed }: { action: PackAction; expectedRevision: number; confirmed?: boolean }) => api.act(w, id, action, expectedRevision, confirmed),
    onSuccess: store
  });
}

/** Downloads the assisted export, then re-reads the pack: the server records the download, the browser doesn't guess it. */
export function useDownloadPack(id: string) {
  const { api, w } = useVisualPackApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ href, filename }: { href: string; filename: string }) => {
      downloadBlob(await api.file(href), filename);
    },
    onSettled: () => client.invalidateQueries({ queryKey: visualPackKeys.pack(w, id) })
  });
}
