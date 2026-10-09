'use client';

import { useCallback, useRef, useState } from 'react';
import { useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys as queryKeys, useAct } from '@/lib/api/hooks';
import type { Asset, Snapshot } from '@/lib/api/types';
import { idempotencyKeyFor, mergeOutcomes, newIdempotencyKey, outcomeFromActionResult, outcomeFromError, reduceBatchOutcomes, type BatchOutcome, type BatchSummary } from '@/lib/library/batch';
import { overrideEnvelope } from '@/lib/library/smart-rules';
import { assetRefFor, normalizeKey } from '@/lib/library/url-state';
import { kindOf } from '@/lib/media/asset-kinds';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryAsset } from '../use-library';
import { isCapabilityUnavailable } from './use-library-search';

/** collection-add/remove edit manual collections; collection-include/exclude are overrides on a smart collection. */
export type BatchKind = 'collection-add' | 'collection-remove' | 'collection-include' | 'collection-exclude' | 'tag-add' | 'delete';

export interface BatchParams {
  collectionId?: string;
  collectionName?: string;
  tag?: string;
  /** The smart collection revision the override was made against (kept so a retry sends the identical request). */
  revision?: number;
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
  'collection-include': 'included',
  'collection-exclude': 'excluded',
  'tag-add': 'tagged',
  delete: 'deleted'
};

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** The person's own tags only. AI-suggested tags are never written back as if someone had chosen them. */
export function userTagsOf(asset: Pick<LibraryAsset, 'tags'>) {
  return asset.tags ?? [];
}

/**
 * Batch actions over the selection (UI spec §5, A063). Items run one at a time and each gets its own outcome. Every
 * item of a run has its own idempotency key, and Retry re-sends only the failed items of the same run with the same
 * keys. Lists are never computed from the page's possibly stale copy: each item is read again right before its write
 * (a document's own record, or the Library list fetched at the start of the run for photos and videos). Tags go through
 * `metadata.update` with the item's key; a manual collection's membership has only the item PATCH, which takes no key
 * but writes the list just read. The optimistic view is rolled back for each item that did not apply.
 */
export function useBatchActions({
  assets,
  manualCollectionIds,
  onAnnounce
}: {
  assets: ReadonlyMap<string, LibraryAsset>;
  /** Manual collections only: the item PATCH edits these, and smart memberships follow their rules. */
  manualCollectionIds: ReadonlySet<string>;
  onAnnounce: (message: string) => void;
}) {
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

  /** The Library list as the server holds it now, by id (photos and videos have no single-item read). */
  const listedNow = useCallback(async () => {
    await client.refetchQueries({ queryKey: ['library-assets', workspaceId] });
    const byId = new Map<string, Asset>();
    for (const [, data] of client.getQueriesData<InfiniteData<{ assets: Asset[] }>>({ queryKey: ['library-assets', workspaceId] })) {
      for (const page of data?.pages ?? []) for (const item of page.assets) byId.set(item.id, item);
    }
    return byId;
  }, [client, workspaceId]);

  /** The item as stored right now: its own record for documents, files and audio; the fresh list otherwise. */
  const readFresh = useCallback(
    async (asset: LibraryAsset, listed: ReadonlyMap<string, Asset> | null): Promise<LibraryAsset | null> => {
      if (kindOf(asset) !== 'image') {
        try {
          return (await api.libraryFile(workspaceId, asset.id)).asset;
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
        }
      }
      // Without a fresh read nothing is written from the page's copy: the item fails and can be retried.
      if (!listed) throw new Error('Couldn’t read this item again before changing it.');
      return listed.get(asset.id) ?? null;
    },
    [api, workspaceId]
  );

  const performOne = useCallback(
    async (kind: BatchKind, asset: LibraryAsset, params: BatchParams, key: string, listed: ReadonlyMap<string, Asset> | null): Promise<BatchOutcome> => {
      const id = asset.id;
      // Smart-collection overrides go through performOverride as one action; never fall through to a delete.
      if (kind === 'collection-include' || kind === 'collection-exclude') return { id, status: 'failed', message: 'Use the collection override.', retryable: false };
      try {
        if (kind === 'collection-add' || kind === 'collection-remove' || kind === 'tag-add') {
          const fresh = await readFresh(asset, listed);
          if (!fresh) return { id, status: 'denied', message: 'This item is no longer available.', retryable: false };
          if (kind === 'tag-add') {
            const tag = (params.tag ?? '').trim();
            const tags = userTagsOf(fresh);
            if (!tag || tags.includes(tag)) return { id, status: 'skipped', message: 'Already has this tag', retryable: false };
            // Revalidated by the server and keyed per item: a retry after a lost answer is answered, not applied twice.
            try {
              const result = await api.libraryAction(workspaceId, {
                actionId: `tag-${normalizeKey(id)}`,
                uiInstanceId: 'library-batch',
                actionType: 'metadata.update',
                targetRefs: [assetRefFor(id)],
                expectedRevision: null,
                idempotencyKey: key,
                payload: { tags: [...tags, tag] }
              });
              return outcomeFromActionResult(id, result);
            } catch (error) {
              // Without the Library intelligence routes, the item PATCH writes the same list just read.
              if (!isCapabilityUnavailable(error)) throw error;
              await api.updateLibraryAsset(workspaceId, id, { tags: [...tags, tag] });
              return { id, status: 'applied' };
            }
          }
          const collectionId = params.collectionId ?? '';
          const current = (fresh.collections ?? []).filter((value) => manualCollectionIds.has(value));
          const member = current.includes(collectionId);
          if (kind === 'collection-add' && member) return { id, status: 'skipped', message: 'Already in this collection', retryable: false };
          if (kind === 'collection-remove' && !member) return { id, status: 'skipped', message: 'Not in this collection', retryable: false };
          const collections = kind === 'collection-add' ? [...current, collectionId] : current.filter((value) => value !== collectionId);
          await api.updateLibraryAsset(workspaceId, id, { collections });
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
    [api, workspaceId, deleteMedia, manualCollectionIds, readFresh]
  );

  /**
   * Include or exclude on a smart collection: one server action for all targets at the revision read just before,
   * with one idempotency key for the run (a retry sends the identical request, so it cannot apply twice).
   */
  const performOverride = useCallback(
    async (kind: 'collection-include' | 'collection-exclude', targets: LibraryAsset[], params: BatchParams, key: string): Promise<{ outcomes: BatchOutcome[]; revision?: number }> => {
      const collectionId = params.collectionId ?? '';
      let revision = params.revision;
      try {
        if (typeof revision !== 'number') revision = (await api.libraryCollection(workspaceId, collectionId)).collection.revision;
        const envelope = overrideEnvelope(collectionId, kind === 'collection-include' ? 'include' : 'exclude', targets.map((asset) => assetRefFor(asset.id)), revision, `override-${Date.now()}`);
        const result = await api.libraryAction(workspaceId, { ...envelope, idempotencyKey: key });
        return { outcomes: targets.map((asset) => outcomeFromActionResult(asset.id, result)), revision };
      } catch (error) {
        return { outcomes: targets.map((asset) => outcomeFromError(asset.id, error instanceof ApiError ? error : { message: error instanceof Error ? error.message : undefined })), revision };
      }
    },
    [api, workspaceId]
  );

  const optimistic = useCallback((kind: BatchKind, asset: LibraryAsset, params: BatchParams): OverlayPatch => {
    if (kind === 'delete') return { hidden: true };
    if (kind === 'tag-add') return { tags: [...new Set([...userTagsOf(asset), params.tag ?? ''])].filter(Boolean) };
    const current = asset.collections ?? [];
    const collectionId = params.collectionId ?? '';
    const joining = kind === 'collection-add' || kind === 'collection-include';
    return { collections: joining ? [...new Set([...current, collectionId])] : current.filter((value) => value !== collectionId) };
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
      if (kind === 'collection-include' || kind === 'collection-exclude') {
        const slot = idempotencyKeyFor(itemKeys.current, runId, '*', () => newIdempotencyKey('lib-override', randomKey));
        itemKeys.current = slot.keys;
        const override = await performOverride(kind, targets, params, slot.key);
        params = { ...params, revision: override.revision };
        outcomes = mergeOutcomes(outcomes, override.outcomes);
        publish(true);
      } else {
        const listed = kind === 'delete' ? null : await listedNow().catch(() => null);
        for (const asset of targets) {
          const slot = idempotencyKeyFor(itemKeys.current, runId, asset.id, () => newIdempotencyKey('lib-batch', randomKey));
          itemKeys.current = slot.keys;
          const outcome = await performOne(kind, asset, params, slot.key, listed);
          outcomes = mergeOutcomes(outcomes, [outcome]);
          publish(true);
        }
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
      if (params.collectionId) await client.invalidateQueries({ queryKey: ['library-collection', workspaceId, params.collectionId] });
      // Fresh server data now carries the applied changes; the overlay is no longer needed for them.
      setOverlay((current) => {
        const next = { ...current };
        for (const asset of targets) if (!summary.rollbackIds.includes(asset.id)) delete next[asset.id];
        return next;
      });
    },
    [assets, client, listedNow, onAnnounce, optimistic, performOne, performOverride, workspaceId]
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
