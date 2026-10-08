'use client';

import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys as queryKeys, useAct } from '@/lib/api/hooks';
import type { Snapshot } from '@/lib/api/types';
import { idempotencyKeyFor, mergeOutcomes, newIdempotencyKey, outcomeFromError, reduceBatchOutcomes, type BatchOutcome, type BatchSummary } from '@/lib/library/batch';
import { kindOf } from '@/lib/media/asset-kinds';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryAsset } from '../use-library';

export type BatchKind = 'collection-add' | 'collection-remove' | 'tag-add' | 'delete';

export interface BatchParams {
  collectionId?: string;
  collectionName?: string;
  tag?: string;
}

export interface BatchRun {
  runId: string;
  kind: BatchKind;
  params: BatchParams;
  ids: string[];
  outcomes: BatchOutcome[];
  summary: BatchSummary;
  running: boolean;
}

/** What the screen shows before the server answers; undone item by item when that item does not apply. */
export interface OverlayPatch {
  hidden?: boolean;
  collections?: string[];
  tags?: string[];
}

const VERB: Record<BatchKind, string> = {
  'collection-add': 'added',
  'collection-remove': 'removed',
  'tag-add': 'tagged',
  delete: 'deleted'
};

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function tagsOf(asset: LibraryAsset) {
  return asset.tags ?? asset.aiTags ?? [];
}

/**
 * Batch actions over the selection (UI spec §5, A063). Items run one at a time and each gets its own outcome. Every
 * item of a run has its own idempotency key, and Retry re-sends only the failed items of the same run with the same
 * keys. The deterministic routes used here write absolute values (a membership list, a tag list, a deletion), so a
 * repeat cannot apply twice either. The optimistic view is rolled back for each item that did not apply.
 */
export function useBatchActions({ assets, onAnnounce }: { assets: ReadonlyMap<string, LibraryAsset>; onAnnounce: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const act = useAct();
  const [run, setRun] = useState<BatchRun | null>(null);
  const [overlay, setOverlay] = useState<Record<string, OverlayPatch>>({});
  const itemKeys = useRef<Record<string, string>>({});
  const busy = useRef(false);

  const deleteMedia = useCallback(
    async (asset: LibraryAsset) => {
      const attempt = async () => {
        const revision = client.getQueryData<Snapshot>(queryKeys.snapshot(workspaceId))?.revision;
        if (typeof revision !== 'number') throw new ApiError('The workspace is still loading. Try again in a moment.', 409);
        return act.mutateAsync({ revision, action: 'p2_media_delete', payload: { assetId: asset.id } });
      };
      try {
        await attempt();
      } catch (error) {
        // Another change landed between items: read the new revision once and send again.
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        await client.refetchQueries({ queryKey: queryKeys.snapshot(workspaceId), exact: true });
        await attempt();
      }
    },
    [act, client, workspaceId]
  );

  const performOne = useCallback(
    async (kind: BatchKind, asset: LibraryAsset, params: BatchParams, _key: string): Promise<BatchOutcome> => {
      const id = asset.id;
      try {
        if (kind === 'collection-add' || kind === 'collection-remove') {
          const collectionId = params.collectionId ?? '';
          const current = asset.collections ?? [];
          const member = current.includes(collectionId);
          if (kind === 'collection-add' && member) return { id, status: 'skipped', message: 'Already in this collection', retryable: false };
          if (kind === 'collection-remove' && !member) return { id, status: 'skipped', message: 'Not in this collection', retryable: false };
          const collections = kind === 'collection-add' ? [...current, collectionId] : current.filter((value) => value !== collectionId);
          await api.updateLibraryAsset(workspaceId, id, { collections });
          return { id, status: 'applied' };
        }
        if (kind === 'tag-add') {
          const tag = (params.tag ?? '').trim();
          const tags = tagsOf(asset);
          if (!tag || tags.includes(tag)) return { id, status: 'skipped', message: 'Already has this tag', retryable: false };
          await api.updateLibraryAsset(workspaceId, id, { tags: [...tags, tag] });
          return { id, status: 'applied' };
        }
        const assetKind = kindOf(asset);
        if (assetKind === 'document' || assetKind === 'file' || assetKind === 'audio') await api.deleteLibraryFile(workspaceId, id);
        else await deleteMedia(asset);
        return { id, status: 'applied' };
      } catch (error) {
        return outcomeFromError(id, error instanceof ApiError ? error : { message: error instanceof Error ? error.message : undefined }, kind === 'delete' ? 'delete' : 'update');
      }
    },
    [api, workspaceId, deleteMedia]
  );

  const optimistic = useCallback((kind: BatchKind, asset: LibraryAsset, params: BatchParams): OverlayPatch => {
    if (kind === 'delete') return { hidden: true };
    if (kind === 'tag-add') return { tags: [...new Set([...tagsOf(asset), params.tag ?? ''])].filter(Boolean) };
    const current = asset.collections ?? [];
    const collectionId = params.collectionId ?? '';
    return { collections: kind === 'collection-add' ? [...new Set([...current, collectionId])] : current.filter((value) => value !== collectionId) };
  }, []);

  const execute = useCallback(
    async (kind: BatchKind, ids: readonly string[], params: BatchParams, previous?: BatchRun | null) => {
      if (busy.current || ids.length === 0) return;
      busy.current = true;
      const runId = previous?.runId ?? `run-${randomKey()}`;
      const targets = ids.map((id) => assets.get(id)).filter((asset): asset is LibraryAsset => Boolean(asset));
      const missing: BatchOutcome[] = ids.filter((id) => !assets.has(id)).map((id) => ({ id, status: 'denied', message: 'This item is no longer available.', retryable: false }));
      let outcomes = mergeOutcomes(previous?.outcomes ?? [], [...missing, ...targets.map((asset) => ({ id: asset.id, status: 'pending' as const }))]);
      const publish = (running: boolean) =>
        setRun({ runId, kind, params, ids: previous?.ids ?? [...ids], outcomes, summary: reduceBatchOutcomes(outcomes, VERB[kind]), running });
      setOverlay((current) => {
        const next = { ...current };
        for (const asset of targets) next[asset.id] = { ...next[asset.id], ...optimistic(kind, asset, params) };
        return next;
      });
      publish(true);
      for (const asset of targets) {
        const slot = idempotencyKeyFor(itemKeys.current, runId, asset.id, () => newIdempotencyKey('lib-batch', randomKey));
        itemKeys.current = slot.keys;
        const outcome = await performOne(kind, asset, params, slot.key);
        outcomes = mergeOutcomes(outcomes, [outcome]);
        publish(true);
      }
      const summary = reduceBatchOutcomes(outcomes, VERB[kind]);
      // Undo the optimistic change for everything that did not apply (conflict, denied, failed).
      setOverlay((current) => {
        const next = { ...current };
        for (const id of summary.rollbackIds) delete next[id];
        return next;
      });
      publish(false);
      busy.current = false;
      onAnnounce(summary.label);
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] });
      // Fresh server data now carries the applied changes; the overlay is no longer needed for them.
      setOverlay((current) => {
        const next = { ...current };
        for (const asset of targets) if (!summary.rollbackIds.includes(asset.id)) delete next[asset.id];
        return next;
      });
    },
    [assets, client, onAnnounce, optimistic, performOne, workspaceId]
  );

  const retry = useCallback(() => {
    if (!run || run.running || run.summary.retryIds.length === 0) return;
    void execute(run.kind, run.summary.retryIds, run.params, run);
  }, [execute, run]);

  const dismiss = useCallback(() => {
    if (run?.running) return;
    setRun(null);
  }, [run]);

  const apply = useCallback(
    (asset: LibraryAsset): LibraryAsset | null => {
      const patch = overlay[asset.id];
      if (!patch) return asset;
      if (patch.hidden) return null;
      return { ...asset, ...(patch.collections ? { collections: patch.collections } : {}), ...(patch.tags ? { tags: patch.tags } : {}) };
    },
    [overlay]
  );

  return { run, execute, retry, dismiss, apply, running: Boolean(run?.running) };
}
