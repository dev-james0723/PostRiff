'use client';

import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useSnapshot } from '@/lib/api/hooks';
import { IN_FLIGHT } from '@/lib/jobs';
import type { Asset, Job, Manifest, Review } from '@/lib/api/types';
import { isLibraryAsset, kindOf } from '@/lib/media/asset-kinds';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { normalizeKey } from '@/lib/library/url-state';

/**
 * Everything the Library reads, derived from the workspace snapshot: the live images in a stated order,
 * which prepared posts used each one, and whether a post using it is publishing right now.
 */

export type LibraryAsset = Asset;

/** The server's limits (`media.py` `_source` and `_decode_pillow`). The client checks type and size only. */
export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
/** Photos are fitted in the browser first (`fitForUpload`: HEIC and others become JPEG), so a pick may be larger. */
export const MAX_PICK_BYTES = 30 * 1024 * 1024;
export const ACCEPTED_TYPES = { 'image/jpeg': ['.jpg', '.jpeg'], 'image/png': ['.png'], 'image/heic': ['.heic'], 'image/heif': ['.heif'], 'image/webp': ['.webp'] };

export interface AssetUse {
  kind: 'review' | 'job';
  id: string;
  platform: string;
  account: string;
  /** The review status or job state exactly as recorded. */
  state: string;
  timing: Manifest['timing'];
  cancelRequested: boolean;
  inFlight: boolean;
}

export type LibraryFilter = 'all' | 'unused' | 'used';
export type LibraryKindFilter = 'all' | 'image' | 'video' | 'audio' | 'document' | 'file';
/** `newest` is offered only when assets carry an upload time; `stored` is the order the API returns. */
export type LibrarySort = 'newest' | 'stored' | 'largest';

const EMPTY_USES: AssetUse[] = [];

function mediaIds(manifest: Manifest) {
  return new Set((manifest.media ?? []).map((media) => media.id));
}

/**
 * One entry per prepared post that references an image. Jobs count in every state (the manifest recorded the
 * image even if the post was later cancelled). Reviews count while they wait for approval; an approved review
 * is already its job, and a stale review is not a post anyone can approve.
 */
function buildUsage(reviews: Review[], jobs: Job[]) {
  const usage = new Map<string, AssetUse[]>();
  const add = (assetId: string, use: AssetUse) => {
    const list = usage.get(assetId);
    if (list) list.push(use);
    else usage.set(assetId, [use]);
  };
  const jobKeys = new Set<string>();
  for (const job of jobs) {
    const approvalDigest = job.approvalDigest;
    if (approvalDigest) jobKeys.add(approvalDigest);
    if (job.manifest.idempotencyKey) jobKeys.add(job.manifest.idempotencyKey);
    for (const id of mediaIds(job.manifest)) {
      add(id, {
        kind: 'job',
        id: job.id,
        platform: job.manifest.platform,
        account: job.manifest.account,
        state: job.state,
        timing: job.manifest.timing,
        cancelRequested: job.cancelRequested,
        inFlight: IN_FLIGHT.has(job.state)
      });
    }
  }
  for (const review of reviews) {
    if (review.status !== 'needs_review') continue;
    if (jobKeys.has(review.digest) || jobKeys.has(review.manifest.idempotencyKey)) continue;
    for (const id of mediaIds(review.manifest)) {
      add(id, {
        kind: 'review',
        id: review.id,
        platform: review.manifest.platform,
        account: review.manifest.account,
        state: review.status,
        timing: review.manifest.timing,
        cancelRequested: false,
        inFlight: false
      });
    }
  }
  return usage;
}

function matchesQuery(asset: LibraryAsset, query: string) {
  if (!query) return true;
  const text = [
    asset.displayTitle,
    asset.originalFilename,
    asset.aiSummary,
    ...(asset.aiTags ?? [])
  ]
    .filter((value): value is string => typeof value === 'string')
    .join(' ')
    .toLowerCase();
  if (text.includes(query)) return true;
  if (asset.hash?.toLowerCase().startsWith(query)) return true;
  if (asset.sourceHash?.toLowerCase().startsWith(query)) return true;
  if (asset.width && asset.height) {
    const dims = query.replace(/\s+/g, '').replace(/[x*]/g, '×');
    return `${asset.width}×${asset.height}`.includes(dims);
  }
  return false;
}

export function useLibrary({
  filter,
  kindFilter,
  sort,
  query,
  tag = '',
  collection = '',
  onlyIds = null
}: {
  filter: LibraryFilter;
  kindFilter: LibraryKindFilter;
  sort: LibrarySort;
  query: string;
  tag?: string;
  collection?: string;
  /** "Selected N items" scope without the intelligence search: only these ids (stable, from the address). */
  onlyIds?: readonly string[] | null;
}) {
  const snapshot = useSnapshot();
  const phase2 = snapshot.data?.state.phase2;
  const { api, workspaceId } = useWorkspaceApi();
  const normalizedQuery = query.trim().toLowerCase();
  const normalized = useInfiniteQuery({
    queryKey: ['library-assets', workspaceId, normalizedQuery, kindFilter, tag, collection, sort],
    queryFn: ({ pageParam }) => api.library(workspaceId, normalizedQuery, 200, pageParam, { kind: kindFilter, tag, collection, sort }),
    initialPageParam: 0,
    getNextPageParam: (page) => page.nextOffset ?? undefined,
    refetchInterval: (q) => q.state.data?.pages.some((p) => p.assets.some((a) => ["pending", "queued", "processing"].includes(a.processing ?? ""))) ? 3_000 : false,
    enabled: Boolean(workspaceId) && !snapshot.isPending,
    staleTime: 15_000
  });

  const derived = useMemo(() => {
    // The normalized endpoint merges legacy photos/videos with document/file rows. During rollout or a temporary
    // endpoint failure, the existing snapshot remains a truthful media-only fallback.
    const source = normalized.data?.pages.flatMap((p) => p.assets) ?? phase2?.assets ?? [];
    const live = source.filter(isLibraryAsset);
    const usage = buildUsage(phase2?.reviews ?? [], phase2?.jobs ?? []);
    const hasTimestamps = live.some((asset) => typeof asset.createdAt === 'number');
    const used = live.filter((asset) => usage.has(asset.id)).length;
    const knownBytes = live.filter((asset) => typeof asset.bytes === 'number');
    // Connected accounts, one entry per platform, for the image rules in the detail.
    const platforms = [...new Set((phase2?.channels ?? []).map((channel) => channel.platform))];
    return {
      live,
      byKey: new Map(live.map((asset) => [normalizeKey(asset.id), asset])),
      usage,
      platforms,
      hasTimestamps,
      counts: { all: live.length, used, unused: live.length - used },
      kindCounts: {
        all: live.length,
        image: live.filter((asset) => kindOf(asset) === 'image').length,
        video: live.filter((asset) => kindOf(asset) === 'video').length,
        audio: live.filter((asset) => kindOf(asset) === 'audio').length,
        document: live.filter((asset) => kindOf(asset) === 'document').length,
        file: live.filter((asset) => kindOf(asset) === 'file').length
      },
      totals: {
        count: live.length,
        bytes: knownBytes.reduce((sum, asset) => sum + (asset.bytes ?? 0), 0),
        unknownBytes: live.length - knownBytes.length
      }
    };
  }, [phase2, normalized.data]);

  // `newest` without timestamps would be a guess, so it falls back to the stored order.
  const effectiveSort: LibrarySort = sort === 'newest' && !derived.hasTimestamps ? 'stored' : sort;
  const backendSearch = Boolean(normalized.data && normalizedQuery);
  const onlyKey = onlyIds ? onlyIds.join(',') : null;
  const only = useMemo(() => (onlyKey === null ? null : new Set(onlyKey.split(',').filter(Boolean).map(normalizeKey))), [onlyKey]);

  const visible = useMemo(() => {
    const filtered = derived.live.filter((asset) => {
      const used = derived.usage.has(asset.id);
      if (filter === 'used' && !used) return false;
      if (filter === 'unused' && used) return false;
      if (kindFilter !== 'all' && kindOf(asset) !== kindFilter) return false;
      if (tag && !(asset.tags ?? asset.aiTags ?? []).includes(tag)) return false;
      if (collection && !asset.collections?.includes(collection)) return false;
      if (only && !only.has(normalizeKey(asset.id))) return false;
      return backendSearch || matchesQuery(asset, normalizedQuery);
    });
    if (effectiveSort === 'stored') return filtered;
    const order = new Map(derived.live.map((asset, index) => [asset.id, index]));
    const stable = (a: LibraryAsset, b: LibraryAsset) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0);
    return filtered.toSorted((a, b) => {
      const key = effectiveSort === 'newest' ? [a.createdAt, b.createdAt] : [a.bytes, b.bytes];
      const [left, right] = key;
      if (typeof left !== 'number' && typeof right !== 'number') return stable(a, b);
      if (typeof left !== 'number') return 1;
      if (typeof right !== 'number') return -1;
      return right - left || stable(a, b);
    });
  }, [derived, filter, kindFilter, normalizedQuery, backendSearch, effectiveSort, tag, collection, only]);

  const firstPage = normalized.data?.pages[0] as unknown as { total?: unknown } | undefined;
  // Every page is here (or the media-only snapshot fallback, which is the whole set): counts over it are totals.
  const complete = normalized.data ? !normalized.hasNextPage : !normalized.isPending;
  return {
    snapshot,
    normalized,
    complete,
    /** A total the server stated for this filter, when the list route provides one. */
    serverTotal: typeof firstPage?.total === 'number' ? firstPage.total : null,
    /** Loaded items still being extracted or indexed. */
    processingCount: derived.live.filter((asset) => ['pending', 'queued', 'processing'].includes(asset.processing ?? '')).length,
    /** Loaded items by their dash-free key (search hits and the address use that form). */
    byKey: derived.byKey,
    revision: snapshot.data?.revision ?? null,
    assets: derived.live,
    visible,
    counts: derived.counts,
    kindCounts: derived.kindCounts,
    totals: derived.totals,
    tags: [...new Set(derived.live.flatMap((a) => a.tags ?? a.aiTags ?? []))].toSorted(),
    storage: normalized.data?.pages[0]?.storage,
    hasTimestamps: derived.hasTimestamps,
    platforms: derived.platforms,
    sort: effectiveSort,
    usesOf: (assetId: string) => derived.usage.get(assetId) ?? EMPTY_USES,
    isPublishing: (assetId: string) => (derived.usage.get(assetId) ?? EMPTY_USES).some((use) => use.inFlight)
  };
}

export type Library = ReturnType<typeof useLibrary>;
