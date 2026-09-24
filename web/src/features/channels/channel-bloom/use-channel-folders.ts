'use client';

/**
 * Saved folder transactions (Rafii v9 §4): every change goes through the workspace's single
 * mutation channel (`api.act` → `p2_folder_save | p2_folder_delete | p2_folder_move`) with the
 * snapshot's expected revision. A 409 (someone else changed the workspace) refetches the snapshot
 * and retries once; any other error is thrown as an `ApiError` for the caller to show inline,
 * with nothing lost on the client. Requests are serialized so rapid actions settle on the last one.
 *
 * Saving a folder never touches destinations, languages or any other setting: the server returns
 * the whole snapshot and the cache is replaced with it, so every page sees the same folders.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys, useSnapshot } from '@/lib/api/hooks';
import type { ChannelFolder, Snapshot } from '@/lib/api/types';
import { copyName, type FolderInput } from '@/lib/channels/folders';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function foldersOf(snapshot: Snapshot | undefined | null): ChannelFolder[] {
  return snapshot?.state?.phase2?.channelFolders ?? [];
}

export interface FolderSaveResult {
  folder: ChannelFolder;
  /** The workspace's folders after the save, for callers that decide what to show before props catch up. */
  folders: ChannelFolder[];
}

export function useChannelFolders() {
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const folders = useMemo(() => foldersOf(snapshot.data), [snapshot.data]);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const [pending, setPending] = useState(0);

  const act = useCallback(
    async (action: string, payload: Record<string, unknown>): Promise<Snapshot> => {
      const attempt = async (retry: boolean): Promise<Snapshot> => {
        const current = client.getQueryData<Snapshot>(keys.snapshot(workspaceId));
        try {
          const after = await api.act(workspaceId, current?.revision ?? 0, action, payload);
          client.setQueryData(keys.snapshot(workspaceId), after);
          return after;
        } catch (error) {
          if (retry && error instanceof ApiError && error.status === 409) {
            await client.refetchQueries({ queryKey: keys.snapshot(workspaceId) });
            return attempt(false);
          }
          throw error;
        }
      };
      const run = queue.current.then(
        () => attempt(true),
        () => attempt(true)
      );
      queue.current = run.catch(() => {});
      setPending((n) => n + 1);
      try {
        return await run;
      } finally {
        setPending((n) => n - 1);
      }
    },
    [api, client, workspaceId]
  );

  /** Create (no id) or edit. Resolves with the saved record from the server's snapshot. */
  const save = useCallback(
    async (input: FolderInput): Promise<FolderSaveResult> => {
      const after = await act('p2_folder_save', {
        ...(input.id ? { id: input.id } : {}),
        name: input.name,
        symbol: input.symbol ?? 'folder',
        pinned: input.pinned === true,
        accountIds: input.accountIds
      });
      const list = foldersOf(after);
      const wanted = input.name.trim().toLocaleLowerCase();
      const folder = (input.id ? list.find((f) => f.id === input.id) : undefined) ?? list.find((f) => f.name.toLocaleLowerCase() === wanted);
      if (!folder) throw new ApiError('The folder was saved but the workspace did not return it. Reload to see it.', 500);
      return { folder, folders: list };
    },
    [act]
  );

  const remove = useCallback(async (id: string): Promise<ChannelFolder[]> => foldersOf(await act('p2_folder_delete', { id })), [act]);

  const move = useCallback(async (id: string, delta: -1 | 1): Promise<ChannelFolder[]> => foldersOf(await act('p2_folder_move', { id, delta })), [act]);

  const pin = useCallback((folder: ChannelFolder, pinned: boolean) => save({ id: folder.id, name: folder.name, symbol: folder.symbol, pinned, accountIds: folder.accountIds }), [save]);

  const duplicate = useCallback(
    (folder: ChannelFolder) => {
      const current = foldersOf(client.getQueryData<Snapshot>(keys.snapshot(workspaceId)));
      return save({ name: copyName(folder.name, current), symbol: folder.symbol, pinned: false, accountIds: folder.accountIds });
    },
    [client, save, workspaceId]
  );

  return { folders, loading: snapshot.isLoading, busy: pending > 0, save, remove, move, pin, duplicate };
}

export type ChannelFoldersApi = ReturnType<typeof useChannelFolders>;

/** The sentence to show when a folder action fails; `ApiError` messages are already plain words. */
export function folderErrorMessage(error: unknown, fallback = 'The folder could not be saved. Nothing was changed.'): string {
  return error instanceof ApiError ? error.message : fallback;
}
