'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { SegmentedControl, StateMessage, Surface } from '@/components/rafii';
import { PageHeader } from '@/components/rafii/page-header';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import type { AssetRef, Locator, LibraryFilters as SearchFilters, LibraryScope } from '@/lib/api/library-intelligence-types';
import { putSignedUpload } from '@/lib/api/upload';
import { keys, useAct } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT } from '@/lib/ease';
import { bottomClearance } from '@/lib/library/layout';
import { MAX_SELECTED, assetRefFor, normalizeKey, reconcileSelection, scrollKey, statusBucket, type LibraryKindParam, type LibrarySortParam } from '@/lib/library/url-state';
import { libraryGates, removedNotice, restoreLibraryState } from '@/lib/library/source-pack';
import { countLabel, coverageLabel, hitTotalLabel, processingLabel, scopeLabel, storageNotice, totalLabel, type ScopeKind } from '@/lib/library/wording';
import { kindOf } from '@/lib/media/asset-kinds';
import { useNowPlaying } from '@/lib/media/now-playing';
import { formatBytes } from '@/lib/time';
import { STATUS } from '@/lib/status-labels';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { blankLocation, checkDuration, checkVideoFile, extractFrames, readVideoMetadata } from '../agent/attachments/video-file';
import { AssetCard, assetTitle, badgeClass, saysStorageNotConfigured } from './asset-card';
import { AssetListRow } from './asset-list-row';
import { AssetDetail } from './asset-detail';
import { useLibraryCollections } from './library-organizer';
import { MAX_PICK_BYTES, useLibrary, type LibraryAsset } from './use-library';
import { useUploadQueue, type UploadItem, type UploadProgress, type UploadStatus } from './use-upload-queue';
import { AddMenu } from './intelligence/add-menu';
import { AnimatedCount } from './intelligence/animated-count';
import { BatchBar, type SelectedItem } from './intelligence/batch-bar';
import { CollectionRail } from './intelligence/collection-rail';
import { KIND_OPTIONS, LibraryFilters, LibrarySearchField, LibraryViewSwitch } from './intelligence/library-toolbar';
import { AskLibraryPanel } from './intelligence/ask-library';
import { SmartCollectionPanel } from './intelligence/smart-collections';
import { SourcePackFlow, type PackRequest } from './intelligence/source-pack-flow';
import { SuggestionsPanel } from './intelligence/suggestions-panel';
import { HitDetails, resolveHitAsset } from './intelligence/search-results';
import { useBatchActions } from './intelligence/use-batch-actions';
import { groupHits, useLibraryIntelligence, useLibrarySearch } from './intelligence/use-library-search';
import { useLibraryUrlState } from './intelligence/use-library-url-state';
import { Control, controlClass } from './ui/controls';

const infoContent = {
  title: 'Library',
  sections: [
    {
      title: 'Private',
      description: 'Only members of this workspace can see these assets.'
    },
    {
      title: 'What you approve is what publishes',
      description: 'Each asset is stored with a fingerprint (hash), and a post publishes exactly the media it was approved with.'
    },
    {
      title: 'Current upload paths',
      description: 'Add photos, MP4/MOV videos, audio, PDF, Office documents, text and other files, paste a public link, or write a quick note. Documents are indexed in the background. All files remain private to this workspace.'
    },
    {
      title: 'Used',
      description: 'Used by a scheduled or published post, or one waiting for review. Only the 20 most recent reviews count.'
    }
  ]
};

const VIDEO_UPLOAD_MIMES = new Set(['video/mp4', 'video/quicktime']);
const VIDEO_UPLOAD_EXTENSIONS = new Set(['mp4', 'mov', 'm4v']);

const SKELETON_KEYS = Array.from({ length: 8 }, (_, index) => `skeleton-${index}`);

/* Rail | results | inspector (redesign §3). The rail narrows to its icon column while the inspector is docked below 1600 px. */
const LAYOUT = {
  wide: 'lg:grid-cols-[13.5rem_minmax(0,1fr)]',
  narrow: 'lg:grid-cols-[3.25rem_minmax(0,1fr)]'
} as const;
const INSPECTOR_LAYOUT = {
  wide: 'xl:grid-cols-[13.5rem_minmax(0,1fr)_23rem]',
  narrow: 'xl:grid-cols-[3.25rem_minmax(0,1fr)_23rem]'
} as const;

/* Grid geometry per density. Comfortable keeps two columns on a 390 px phone so the first item shows in full. */
const GRID: Record<'comfortable' | 'compact', string> = {
  comfortable: 'grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 xl:grid-cols-4 2xl:grid-cols-5',
  compact: 'grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-8'
};

function rejectionMessage({ file, errors }: FileRejection) {
  const code = errors[0]?.code;
  if (code === 'file-too-large') return `${file.name} is over 50 MB`;
  if (code === 'file-too-small') return `${file.name} is empty`;
  if (code === 'file-invalid-type') return `${file.name} isn’t a photo`;
  return `Couldn’t add ${file.name}`;
}

/** Waiting, reading, sending, uploaded, failed and not sent stay distinct states (DNA §21.9), in words. */
const UPLOAD_BADGE: Record<UploadStatus, { status: AnimatedBadgeStatus; label: string }> = {
  waiting: { status: 'neutral', label: 'Waiting' },
  reading: { status: 'loading', label: 'Reading' },
  sending: { status: 'loading', label: 'Uploading' },
  done: { status: 'success', label: 'Uploaded' },
  failed: { status: 'danger', label: STATUS.failed },
  skipped: { status: 'neutral', label: 'Not sent' }
};

function uploadingText(progress: UploadProgress | null) {
  if (!progress || progress.total === 0) return 'Uploading…';
  return `Uploading ${Math.min(progress.finished + 1, progress.total)} of ${progress.total}…`;
}

function UploadTray({ items, progress, onDismiss }: { items: UploadItem[]; progress: UploadProgress | null; onDismiss: () => void }) {
  const done = items.filter((item) => item.status === 'done').length;
  return (
    <Surface as='section' material='quiet' radius='card' padding='none' aria-labelledby='library-uploads'>
      <div className='flex min-h-12 items-center justify-between gap-2 px-4 py-1.5'>
        <h3 id='library-uploads' aria-live='polite' className='text-sm font-medium'>
          {progress ? uploadingText(progress) : `${done} of ${items.length} uploaded`}
        </h3>
        {!progress && (
          <Control tone='ghost' size='sm' onClick={onDismiss}>
            Dismiss
          </Control>
        )}
      </div>
      <ul className='flex max-h-60 flex-col gap-0.5 overflow-y-auto px-2 pb-2'>
        {items.map((item) => {
          const badge = UPLOAD_BADGE[item.status];
          return (
            <li key={item.key} className='flex min-h-11 items-center gap-3 rounded-[var(--rafii-radius-control)] px-2 py-1.5'>
              <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                <span className='truncate text-sm'>{item.name}</span>
                <span className={cn('text-xs', item.status === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>
                  {formatBytes(item.bytes)}
                  {item.message ? ` · ${item.message}` : ''}
                </span>
              </div>
              <AnimatedBadge size='sm' status={badge.status} showIcon={item.status !== 'waiting' && item.status !== 'skipped'} className={badgeClass(badge.status)}>
                {badge.label}
              </AnimatedBadge>
            </li>
          );
        })}
      </ul>
    </Surface>
  );
}

/** Loading keeps the loaded geometry (DNA §20.1). */
function ResultsSkeleton({ density }: { density: 'comfortable' | 'compact' }) {
  return (
    <div className={GRID[density]} role='status' aria-busy='true' aria-label='Loading the library'>
      {SKELETON_KEYS.map((key) => (
        <Skeleton key={key} className='aspect-[4/5] w-full rounded-[var(--rafii-radius-card)]' />
      ))}
    </div>
  );
}

/** One polite live region for the page: search, upload and batch results, without repeating itself. */
function useAnnouncer() {
  const [message, setMessage] = useState('');
  const last = useRef({ text: '', at: 0 });
  const announce = useCallback((text: string) => {
    const now = Date.now();
    if (!text || (text === last.current.text && now - last.current.at < 4000)) return;
    last.current = { text, at: now };
    setMessage('');
    window.requestAnimationFrame(() => setMessage(text));
  }, []);
  return [message, announce] as const;
}

/** True from this viewport width: the rail sits beside the results from 1024 px, the inspector docks from 1280 px. */
function useMinWidth(px: number) {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const query = window.matchMedia(`(min-width: ${px}px)`);
    const update = () => setMatches(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, [px]);
  return matches;
}

const RAIL_KEY = 'rafii-library-rail-collapsed';

function readRailCollapsed() {
  try {
    return window.localStorage.getItem(RAIL_KEY) === '1';
  } catch {
    return false;
  }
}

export function LibraryView() {
  // The address carries the Library's state (nuqs); the boundary keeps the first render static-safe.
  return (
    <Suspense fallback={null}>
      <LibraryPage />
    </Suspense>
  );
}

function LibraryPage() {
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const isOwner = access.role === 'owner';
  const reduce = useReducedMotion();
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const act = useAct();
  const upload = useUploadQueue();
  const auth = useAuth();
  const isMobile = useIsMobile();
  const wide = useMinWidth(1024);
  const docked = useMinWidth(1280);
  const ultraWide = useMinWidth(1600);
  const { state: url, update, commit } = useLibraryUrlState();
  const intel = useLibraryIntelligence();
  // What this environment switched on (GET …/status): entry points that are off are hidden or explained.
  const gates = libraryGates(intel.flags, intel.reachable);
  const collections = useLibraryCollections();
  const [announcement, announce] = useAnnouncer();

  /* --- query, scope and search --------------------------------------------------------------------------------- */

  // The field answers every keystroke; the address follows a moment later (and never carries a link or token).
  const [query, setQuery] = useState(url.q);
  useEffect(() => {
    const timer = window.setTimeout(() => update({ q: query }), 300);
    return () => window.clearTimeout(timer);
  }, [query, update]);

  // Back from a draft: the source pack's saved Library state (query, scope, filters, sort, view, selection and open
  // item), with items that became inaccessible already left out by the server and explained without naming them.
  const latestUrl = useRef(url);
  useEffect(() => {
    latestUrl.current = url;
  });
  const restoredPack = useRef('');
  useEffect(() => {
    const packId = url.pack;
    if (!packId || restoredPack.current === packId) return;
    if (!intel.reachable) {
      if (intel.status.isFetched) update({ pack: '' });
      return;
    }
    restoredPack.current = packId;
    let cancelled = false;
    void api
      .librarySourcePack(workspaceId, packId)
      .then((pack) => {
        if (cancelled) return;
        const patch = restoreLibraryState(pack.returnTo, latestUrl.current);
        if (typeof patch.q === 'string') setQuery(patch.q);
        update({ ...patch, pack: '' });
        const notice = removedNotice(pack.returnToRemoved);
        if (notice) toast.info(notice);
      })
      .catch(() => {
        if (!cancelled) update({ pack: '' });
      });
    return () => {
      cancelled = true;
    };
  }, [url.pack, intel.reachable, intel.status.isFetched, api, workspaceId, update]);

  const collectionList = useMemo(() => collections.data?.collections ?? [], [collections.data]);
  const activeCollection = url.collection ? (collectionList.find((collection) => collection.id === url.collection) ?? null) : null;
  const selection = url.sel;
  const scopeKind: ScopeKind = url.scope === 'selection' && selection.length ? 'selection' : url.collection ? 'collection' : 'workspace';
  const scope = { kind: scopeKind, collectionName: activeCollection?.name ?? null, selectedCount: selection.length };
  // The scopes that exist right now: the whole Library, the open collection, the selection.
  const scopeOptions: ScopeKind[] = ['workspace', ...(url.collection ? (['collection'] as const) : []), ...(selection.length ? (['selection'] as const) : [])];
  const searchScope: LibraryScope = useMemo(
    () =>
      scopeKind === 'selection'
        ? { kind: 'selection', assetRefs: selection.map(assetRefFor) }
        : scopeKind === 'collection'
          ? { kind: 'collection', collectionId: normalizeKey(url.collection) }
          : { kind: 'workspace' },
    [scopeKind, selection, url.collection]
  );
  const searchFilters: SearchFilters = useMemo(
    () => ({
      ...(url.kind !== 'all' ? { kinds: [url.kind] } : {}),
      ...(url.tag ? { tags: [url.tag] } : {}),
      ...(url.use !== 'all' ? { usage: url.use } : {})
    }),
    [url.kind, url.tag, url.use]
  );
  const search = useLibrarySearch({ enabled: intel.retrieval, query, scope: searchScope, filters: searchFilters });
  // Intelligent results while that search answers; the deterministic Library otherwise, always.
  const intelligent = search.active && !search.failed;

  const library = useLibrary({
    filter: url.use,
    kindFilter: url.kind,
    sort: url.sort,
    query: intelligent ? '' : query,
    tag: url.tag,
    collection: scopeKind === 'collection' ? url.collection : '',
    status: url.status,
    onlyIds: scopeKind === 'selection' ? selection : null
  });
  const { snapshot, assets } = library;
  const assetsById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);

  /* --- batch, overlay and selection ---------------------------------------------------------------------------- */

  const manualCollectionIds = useMemo(() => new Set(collectionList.filter((collection) => collection.kind !== 'smart').map((collection) => collection.id)), [collectionList]);
  const batch = useBatchActions({ assets: assetsById, manualCollectionIds, onAnnounce: announce });
  const applyOverlay = batch.apply;
  const shown = useMemo(
    () =>
      library.visible
        .map((asset) => applyOverlay(asset))
        .filter((asset): asset is LibraryAsset => asset !== null)
        .filter((asset) => scopeKind !== 'collection' || Boolean(asset.collections?.includes(url.collection))),
    [library.visible, applyOverlay, scopeKind, url.collection]
  );
  const groups = useMemo(() => groupHits(search.hits), [search.hits]);
  const hitItems = useMemo(
    () =>
      groups
        .map((group) => ({ group, asset: applyOverlay(resolveHitAsset(group, library.byKey)) }))
        .filter((entry): entry is { group: (typeof groups)[number]; asset: LibraryAsset } => entry.asset !== null)
        // Status is applied to the matches the same way as to the browsed Library.
        .filter((entry) => url.status === 'all' || statusBucket(entry.asset.processing) === url.status),
    [groups, library.byKey, applyOverlay, url.status]
  );
  const orderedIds = intelligent ? hitItems.map((entry) => entry.asset.id) : shown.map((asset) => asset.id);
  const selectedSet = useMemo(() => new Set(selection), [selection]);
  const lastToggled = useRef<string | null>(null);

  const setSelection = useCallback(
    (ids: string[]) => {
      if (ids.length > MAX_SELECTED) announce(`Up to ${MAX_SELECTED} items can be selected at once.`);
      update({ sel: ids.slice(0, MAX_SELECTED), ...(ids.length === 0 && url.scope === 'selection' ? { scope: 'all' as const } : {}) });
    },
    [announce, update, url.scope]
  );

  const toggle = useCallback(
    (id: string, on: boolean, extend: boolean) => {
      const next = new Set(selection);
      const anchor = lastToggled.current;
      if (extend && anchor && orderedIds.includes(anchor) && orderedIds.includes(id)) {
        const [from, to] = [orderedIds.indexOf(anchor), orderedIds.indexOf(id)].toSorted((a, b) => a - b);
        for (const value of orderedIds.slice(from, to + 1)) {
          if (on) next.add(value);
          else next.delete(value);
        }
      } else if (on) next.add(id);
      else next.delete(id);
      lastToggled.current = id;
      setSelection([...next]);
    },
    [orderedIds, selection, setSelection]
  );

  // Items that are gone (deleted elsewhere, or access withdrawn) leave the selection with a generic notice. Only the
  // whole, unfiltered list can tell: a filter or a collection hides items without them being gone.
  const unfiltered = !query.trim() && url.kind === 'all' && !url.tag && scopeKind === 'workspace';
  useEffect(() => {
    if (!library.complete || snapshot.isPending || selection.length === 0 || intelligent || !unfiltered || library.normalized.isFetching) return;
    const { kept, dropped } = reconcileSelection(selection, assets.map((asset) => asset.id), true);
    if (dropped > 0) {
      setSelection(kept);
      toast.info('Some selected items are no longer available, so they were removed from your selection.');
    }
  }, [library.complete, library.normalized.isFetching, snapshot.isPending, selection, assets, intelligent, unfiltered, setSelection]);

  // After a delete run, the deleted items simply leave the selection.
  const lastRun = batch.run;
  useEffect(() => {
    if (!lastRun || lastRun.running || lastRun.kind !== 'delete') return;
    const gone = new Set(lastRun.outcomes.filter((outcome) => outcome.status === 'applied' || outcome.status === 'skipped').map((outcome) => outcome.id));
    if (selection.some((id) => gone.has(id))) setSelection(selection.filter((id) => !gone.has(id)));
  }, [lastRun, selection, setSelection]);

  /* --- detail ----------------------------------------------------------------------------------------------------- */

  const [detailAsset, setDetailAsset] = useState<LibraryAsset | null>(null);
  const [focusLocator, setFocusLocator] = useState<Locator | null>(null);
  const phase2Assets = snapshot.data?.state.phase2?.assets;
  // The item opened in this visit, or one named by the address (a deep link or a return from a draft).
  const known = detailAsset && url.asset && normalizeKey(detailAsset.id) === normalizeKey(url.asset) ? detailAsset : null;
  const fromLists = url.asset && !known ? (library.byKey.get(normalizeKey(url.asset)) ?? phase2Assets?.find((asset) => asset.id === url.asset) ?? null) : null;
  // Not on the loaded pages: ask for that one item. Media always arrive with the snapshot, so this is for files.
  const deepLink = useQuery({
    queryKey: ['library-file-detail', workspaceId, url.asset],
    queryFn: () => api.libraryFile(workspaceId, url.asset),
    enabled: Boolean(workspaceId && url.asset && !known && !fromLists && !snapshot.isPending && !library.normalized.isPending),
    retry: false
  });
  const resolvedDetail = known ?? fromLists ?? deepLink.data?.asset ?? null;
  useEffect(() => {
    if (resolvedDetail && resolvedDetail !== detailAsset) setDetailAsset(resolvedDetail);
  }, [resolvedDetail, detailAsset]);
  // Gone or no longer permitted: close it and say so without naming it.
  const detailGone = Boolean(url.asset) && !resolvedDetail && deepLink.isError && deepLink.error instanceof ApiError && [403, 404].includes(deepLink.error.status);
  useEffect(() => {
    if (!detailGone) return;
    update({ asset: '' });
    toast.info('That item is no longer available.');
  }, [detailGone, update]);
  const current = detailAsset ? (assetsById.get(detailAsset.id) ?? detailAsset) : null;
  // Stays open while another item (a related version, a suggestion) is being fetched into the same panel.
  const detailOpen = Boolean(url.asset) && current !== null;

  const openDetail = useCallback(
    (asset: LibraryAsset, locator: Locator | null = null) => {
      setDetailAsset(asset);
      setFocusLocator(locator);
      update({ asset: asset.id });
    },
    [update]
  );

  /** Playback only ever starts from a press on a result: never on opening anything. */
  const playFrom = useCallback(
    async (asset: LibraryAsset, startMs: number) => {
      try {
        const kind = kindOf(asset);
        const { url: mediaUrl } = kind === 'video' ? await api.mediaUrl(workspaceId, asset.id) : await api.libraryFileUrl(workspaceId, asset.id);
        useNowPlaying.getState().open({ kind: kind === 'video' ? 'video' : 'audio', workspaceId, assetId: asset.id, title: assetTitle(asset), url: mediaUrl, startAt: startMs / 1000 });
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Playback unavailable');
      }
    },
    [api, workspaceId]
  );

  /* --- single delete ---------------------------------------------------------------------------------------------- */

  const [pendingDelete, setPendingDelete] = useState<LibraryAsset | null>(null);
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(() => new Set());

  async function remove(asset: LibraryAsset) {
    const revision = library.revision;
    if (revision === null) return;
    setDeletingIds((ids) => new Set(ids).add(asset.id));
    try {
      const assetKind = kindOf(asset);
      if (assetKind === 'document' || assetKind === 'file' || assetKind === 'audio') {
        await api.deleteLibraryFile(workspaceId, asset.id);
      } else {
        await act.mutateAsync({ revision, action: 'p2_media_delete', payload: { assetId: asset.id } });
      }
      if (url.asset && normalizeKey(url.asset) === normalizeKey(asset.id)) update({ asset: '' });
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      // The card leaves the grid; the announcement says so once.
      announce(`${assetTitle(asset)} deleted.`);
    } catch (error) {
      toast.error('Couldn’t delete this asset', { description: error instanceof ApiError ? error.message : undefined });
      if (error instanceof ApiError && error.status === 409) {
        void client.refetchQueries({ queryKey: keys.snapshot(workspaceId), exact: true });
      }
    } finally {
      setDeletingIds((ids) => {
        const next = new Set(ids);
        next.delete(asset.id);
        return next;
      });
    }
  }

  /* --- uploads (the image compatibility path, documents and videos stay as they were) ---------------------------- */

  const pendingFile = useRef<{ file: File; assetId: string; put: boolean; video?: { frames: { at: number; data: string }[]; locationCleared: boolean } } | null>(null);
  const [fileFailure, setFileFailure] = useState<string | null>(null);
  const [fileProgress, setFileProgress] = useState('');
  const [uploadingFile, setUploadingFile] = useState(false);
  const filePicker = useRef<HTMLInputElement>(null);
  /**
   * A preview request was answered "Private media storage is not configured." The latest answer wins: a preview
   * that loads afterwards clears it. Other 503s (storage briefly unreachable, a restart) keep Retry on the card instead.
   */
  const [mediaStorageMissing, setMediaStorageMissing] = useState(false);
  const markStorageMissing = useCallback(() => setMediaStorageMissing(true), []);
  const markPreviewLoaded = useCallback(() => setMediaStorageMissing(false), []);

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    maxSize: 50 * 1024 * 1024,
    minSize: 1,
    multiple: true,
    noClick: true,
    noKeyboard: true,
    disabled: !canEdit || library.revision === null,
    onDrop: (accepted, rejected) => {
      for (const rejection of rejected) toast.error(rejectionMessage(rejection));
      void uploadFiles(accepted);
    }
  });

  const uploadStorageMissing = saysStorageNotConfigured(upload.blocker);
  const storageMissing = mediaStorageMissing || uploadStorageMissing;

  async function uploadLibraryFile(file: File) {
    if (!canEdit) return;
    if (!file.size || file.size > 50 * 1024 * 1024) {
      toast.error('Choose a file up to 50 MB');
      return;
    }
    setUploadingFile(true);
    setFileFailure(null);
    setFileProgress(`Preparing ${file.name}…`);
    try {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
      if (VIDEO_UPLOAD_MIMES.has(file.type.toLowerCase()) || VIDEO_UPLOAD_EXTENSIONS.has(extension)) {
        await uploadLibraryVideo(file);
        return;
      }
      const fallbackMime: Record<string, string> = {
        wav: 'audio/wav', mp3: 'audio/mpeg', m4a: 'audio/mp4', ogg: 'audio/ogg', oga: 'audio/ogg', flac: 'audio/flac', aac: 'audio/aac', webm: 'audio/webm',
        txt: 'text/plain', md: 'text/markdown', markdown: 'text/markdown', html: 'text/html', htm: 'text/html',
        json: 'application/json', csv: 'text/csv', pdf: 'application/pdf',
        docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
      };
      const mime = fallbackMime[extension] ?? 'application/octet-stream';
      let pending = pendingFile.current;
      if (!pending || pending.file !== file) {
        const ticket = await api.beginLibraryFile(workspaceId, { filename: file.name, mime, bytes: file.size });
        pending = { file, assetId: ticket.upload.assetId, put: false };
        pendingFile.current = pending;
        await putSignedUpload(ticket.upload.url, file, { 'Content-Type': ticket.upload.mime }, (fraction) => setFileProgress(`${file.name} · ${Math.round(fraction * 100)}%`));
        pending.put = true;
      }
      if (!pending.put) throw new Error('Remove this pending upload and choose the file again.');
      setFileProgress(`Verifying ${file.name}…`);
      const result = await api.commitLibraryFile(workspaceId, pending.assetId);
      pendingFile.current = null;
      if (result.status === 'failed') throw new Error(result.asset.extractionError || 'The original file was saved, but text extraction failed. Retry from its details.');
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      toast.success('File saved. Complex documents are indexed in the background.');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not add this file';
      setFileFailure(message);
      toast.error('Couldn’t add this file', { description: message });
    } finally {
      setUploadingFile(false);
      setFileProgress('');
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      if (filePicker.current) filePicker.current.value = '';
    }
  }

  async function uploadLibraryVideo(file: File) {
    let pending = pendingFile.current;
    if (!pending || pending.file !== file) {
      const policy = { maxBytes: 50_000_000, maxSeconds: 180 };
      const checked = await checkVideoFile(file, policy);
      if (!checked.ok || !checked.mime) throw new Error(checked.message || 'Choose an MP4 or MOV video');
      const metadata = await readVideoMetadata(file);
      const tooLong = checkDuration(metadata?.duration ?? null, policy);
      if (tooLong) throw new Error(tooLong);
      const blanked = await blankLocation(file);
      const frames = await extractFrames(blanked.blob);
      const encoded = await Promise.all(
        frames.map(async (frame) => ({
          at: frame.at,
          data: await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] ?? ''), { once: true });
            reader.addEventListener('error', () => reject(new Error('Could not prepare preview')), { once: true });
            reader.readAsDataURL(frame.blob);
          })
        }))
      );
      const ticket = await api.beginVideoUpload(workspaceId, { mime: checked.mime, bytes: blanked.blob.size, duration: metadata?.duration ?? null, width: metadata?.width ?? null, height: metadata?.height ?? null });
      pending = { file, assetId: ticket.upload.assetId, put: false, video: { frames: encoded, locationCleared: blanked.locationCleared } };
      pendingFile.current = pending;
      await putSignedUpload(ticket.upload.uploadUrl, blanked.blob, ticket.upload.headers, (fraction) => setFileProgress(`${file.name} · ${Math.round(fraction * 100)}%`));
      pending.put = true;
    }
    if (!pending.put || !pending.video) throw new Error('Remove this pending upload and choose the video again.');
    setFileProgress(`Verifying ${file.name}…`);
    await api.commitVideoUpload(workspaceId, pending.assetId, pending.video);
    await api.updateLibraryAsset(workspaceId, pending.assetId, { title: file.name });
    pendingFile.current = null;
    await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    toast.success('Video added to Library');
  }

  async function uploadFiles(files: File[]) {
    if (uploadingFile) return;
    // Photos keep the compatibility path (HEIC and other formats become JPEG in the browser first).
    const photos = files.filter((file) => file.type.startsWith('image/'));
    for (const file of photos.filter((photo) => photo.size > MAX_PICK_BYTES)) toast.error(`${file.name} is over 30 MB`);
    upload.enqueue(photos.filter((photo) => photo.size <= MAX_PICK_BYTES));
    for (const file of files.filter((item) => !item.type.startsWith('image/'))) {
      await uploadLibraryFile(file);
      if (pendingFile.current) break;
    }
  }

  // A finished photo batch is announced once (the tray keeps the per-file detail).
  const uploadResult = upload.progress === null ? upload.resultLabel : '';
  useEffect(() => {
    if (uploadResult) announce(uploadResult);
  }, [uploadResult, announce]);

  /* --- layout state ----------------------------------------------------------------------------------------------- */

  const [railCollapsed, setRailCollapsed] = useState(false);
  useEffect(() => setRailCollapsed(readRailCollapsed()), []);
  // "Show collections" while the inspector has narrowed the rail keeps it open for this visit (the person's choice wins).
  const [railPinned, setRailPinned] = useState(false);
  const collapseRail = useCallback((value: boolean) => {
    setRailCollapsed(value);
    setRailPinned(!value);
    try {
      window.localStorage.setItem(RAIL_KEY, value ? '1' : '0');
    } catch {
      /* storage blocked: the rail simply opens next time */
    }
  }, []);

  // The inspector docks beside the results from 1280 px (non-modal); below that it is a sheet, on phones a drawer.
  const dockedOpen = docked && !isMobile && detailOpen;
  const railNarrow = wide && (railCollapsed || (dockedOpen && !ultraWide && !railPinned));

  // "/" focuses the search from anywhere on the page (not while typing elsewhere).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      const field = document.querySelector<HTMLInputElement>('input[name="library-search"]');
      if (!field) return;
      event.preventDefault();
      field.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const track = useNowPlaying((state) => state.track);
  const playerExpanded = useNowPlaying((state) => state.expanded);
  const clearance = bottomClearance({ mobile: isMobile, playerOpen: Boolean(track), playerExpanded: playerExpanded && track?.kind !== 'audio' });

  // Return to the same place: the scroll position is kept per view for this browser tab.
  const viewKey = scrollKey(workspaceId, { ...url, q: query });
  useEffect(() => {
    let frame = 0;
    const save = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        try {
          window.sessionStorage.setItem(viewKey, String(Math.round(window.scrollY)));
        } catch {
          /* storage blocked: no restore */
        }
      });
    };
    window.addEventListener('scroll', save, { passive: true });
    return () => {
      window.removeEventListener('scroll', save);
      window.cancelAnimationFrame(frame);
    };
  }, [viewKey]);
  const restoredScroll = useRef(false);
  const resultCount = intelligent ? hitItems.length : shown.length;
  useEffect(() => {
    if (restoredScroll.current || snapshot.isPending || resultCount === 0) return;
    restoredScroll.current = true;
    let saved = 0;
    try {
      saved = Number(window.sessionStorage.getItem(viewKey) ?? 0);
    } catch {
      saved = 0;
    }
    if (saved > 0) window.requestAnimationFrame(() => window.scrollTo({ top: saved }));
  }, [snapshot.isPending, resultCount, viewKey]);

  // Keyboard: Escape clears the selection, Ctrl/Cmd+A selects every shown item, while focus is in the results.
  const resultsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = resultsRef.current;
    if (!node) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input[type="search"], input[type="text"], textarea')) return;
      if (event.key === 'Escape' && selection.length) {
        event.preventDefault();
        setSelection([]);
        announce('Selection cleared.');
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a' && orderedIds.length) {
        event.preventDefault();
        setSelection([...new Set([...selection, ...orderedIds])]);
      }
    };
    node.addEventListener('keydown', onKey);
    return () => node.removeEventListener('keydown', onKey);
  }, [selection, orderedIds, setSelection, announce]);

  // Settled result counts are announced once per query, never while results are still arriving.
  const settling = intelligent ? search.loading : library.normalized.isFetching;
  const settledCount = intelligent ? hitItems.length : shown.length;
  const settledMessage = !query.trim() || settling ? '' : settledCount === 0 ? `No items match “${query.trim()}”.` : `${countLabel(settledCount, 'matching item')} for “${query.trim()}”${intelligent && search.nextCursor ? ', more available' : ''}.`;
  useEffect(() => {
    if (settledMessage) announce(settledMessage);
  }, [settledMessage, announce]);

  /* --- render ------------------------------------------------------------------------------------------------------ */

  const activeSmart = scopeKind === 'collection' && activeCollection?.kind === 'smart';
  // Ask only where the service answers and its search is on; otherwise the Library stays on its results.
  const asking = url.panel === 'ask' && gates.ask.enabled;
  const askOff = url.panel === 'ask' && intel.reachable && !gates.ask.enabled ? gates.ask.reason : null;
  const llm = intel.status.data?.providers?.llm;
  const summariesAvailable = typeof llm?.available === 'boolean' ? llm.available : null;
  const sortOptions: LibrarySortParam[] = [...(library.hasTimestamps ? (['newest'] as const) : []), 'stored', 'largest'];
  const exactCounts = library.complete && !intelligent;
  const kindCounts = intelligent ? (search.facets?.kinds as Partial<Record<LibraryKindParam, number>> | undefined) ?? null : exactCounts ? library.kindCounts : null;
  const notice = library.storage ? storageNotice(library.storage.usedBytes, library.storage.limitBytes) : null;
  const filtersActive = url.kind !== 'all' || Boolean(url.tag) || url.use !== 'all' || url.status !== 'all' || scopeKind !== 'workspace';
  const normalizedQuery = query.trim();
  const density = url.density;

  const facetTotal = search.facets?.kinds ? Object.values(search.facets.kinds).reduce((sum, value) => sum + (typeof value === 'number' ? value : 0), 0) : null;
  const statusLine: ReactNode = intelligent ? (
    <span className='flex flex-col gap-0.5'>
      <span>{search.loading && !hitItems.length ? 'Searching…' : (hitTotalLabel(search.totalHits) ?? totalLabel({ total: facetTotal, loaded: hitItems.length, complete: !search.nextCursor, singular: 'matching item' }))}</span>
      {search.coverage ? <span>{coverageLabel(search.coverage)}</span> : null}
    </span>
  ) : (
    <span className='flex flex-wrap items-center gap-x-1'>
      {exactCounts && url.use === 'all' && scopeKind !== 'selection' ? (
        <AnimatedCount value={library.serverTotal ?? shown.length} />
      ) : (
        <span>{totalLabel({ total: url.use === 'all' && scopeKind !== 'selection' ? library.serverTotal : null, loaded: shown.length, complete: library.complete })}</span>
      )}
      {processingLabel(library.processingCount) ? <span>· {processingLabel(library.processingCount)}{library.complete ? '' : ' (of those loaded)'}</span> : null}
    </span>
  );

  const selectedItems: SelectedItem[] = selection.map((id) => {
    const asset = assetsById.get(id) ?? library.byKey.get(normalizeKey(id)) ?? null;
    return { id, asset, title: asset ? assetTitle(asset) : 'An item not loaded on this page', ref: assetRefFor(id) };
  });
  const selectedUsed = selectedItems.filter((item) => item.asset && library.usesOf(item.asset.id).length > 0).length;

  // One source-pack flow for the page: from the selection (batch bar) or from one item ("Use in draft"). It keeps the
  // Library state of this moment, which the draft carries and hands back.
  const [packRequest, setPackRequest] = useState<PackRequest | null>(null);
  const packCount = useRef(0);
  const askForPack = (origin: PackRequest['origin'], refs: PackRequest['refs'], titles: string[]) => {
    packCount.current += 1;
    setPackRequest({ id: packCount.current, origin, refs, titles, state: { ...url, q: query } });
  };

  const cardProps = (asset: LibraryAsset, index: number, footer?: ReactNode) => ({
    asset,
    uses: library.usesOf(asset.id),
    publishing: library.isPublishing(asset.id),
    first: index === 0,
    canEdit,
    canApprove,
    deleting: deletingIds.has(asset.id),
    onOpen: () => openDetail(asset),
    onDelete: () => setPendingDelete(asset),
    onStorageMissing: markStorageMissing,
    onPreviewLoaded: markPreviewLoaded,
    selected: selectedSet.has(asset.id),
    selecting: selection.length > 0,
    onSelect: (on: boolean, extend: boolean) => toggle(asset.id, on, extend),
    density,
    onExclude: activeSmart && canEdit ? () => void batch.execute('collection-exclude', [asset.id], { collectionId: url.collection, collectionName: activeCollection?.name }) : undefined,
    inspected: Boolean(url.asset) && normalizeKey(url.asset) === normalizeKey(asset.id),
    footer
  });

  const renderItems = (items: { asset: LibraryAsset; footer?: ReactNode }[]) => (
    <div role='list' aria-label='Library items' className={url.mode === 'gallery' ? GRID[density] : cn('flex flex-col', density === 'compact' ? 'gap-1.5' : 'gap-2')}>
      <AnimatePresence initial={false}>
        {items.map(({ asset, footer }, index) =>
          url.mode === 'gallery' ? <AssetCard key={asset.id} {...cardProps(asset, index, footer)} /> : <AssetListRow key={asset.id} {...cardProps(asset, index, footer)} />
        )}
      </AnimatePresence>
    </div>
  );

  let content: ReactNode;
  if (snapshot.isPending) {
    content = <ResultsSkeleton density={density} />;
  } else if (snapshot.isError && !snapshot.data) {
    content = (
      <StateMessage
        kind='error'
        title='Couldn’t load the library'
        description={snapshot.error instanceof Error ? snapshot.error.message : undefined}
        action={
          <Control tone='secondary' disabled={snapshot.isFetching} onClick={() => void snapshot.refetch()}>
            <Icons.refresh className={cn(snapshot.isFetching && 'animate-spin')} aria-hidden />
            Try again
          </Control>
        }
      />
    );
  } else if (assets.length === 0 && !normalizedQuery && !filtersActive && library.complete) {
    content = (
      <motion.div key='empty' data-tour='library-empty' initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reduce ? 0 : 0.2, ease: EASE_OUT }} className='flex flex-1 flex-col'>
        <StateMessage
          kind='empty'
          media={
            <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 shrink-0 items-center justify-center rounded-full'>
              <Icons.media className='size-5' />
            </span>
          }
          title='No assets yet'
          description={canEdit ? 'Add photos, videos, audio, documents or files to your Library.' : 'Only editors can add assets.'}
          action={
            canEdit ? (
              <Control tone='secondary' onClick={() => filePicker.current?.click()} disabled={library.revision === null || uploadingFile}>
                <Icons.upload aria-hidden />
                Choose assets
              </Control>
            ) : undefined
          }
        />
      </motion.div>
    );
  } else if (intelligent) {
    content = (
      <div className='flex flex-col gap-3'>
        {search.warnings.length ? <StateMessage kind='partial' layout='inline' title={search.warnings[0]} /> : null}
        {search.loading && hitItems.length === 0 ? (
          <ResultsSkeleton density={density} />
        ) : hitItems.length === 0 ? (
          <StateMessage
            kind='empty'
            title={`No item matches “${normalizedQuery}” in ${scopeKind === 'workspace' ? 'your Library' : scopeKind === 'collection' ? 'this collection' : 'the selected items'}`}
            description={search.coverage && search.coverage.pendingAssetCount > 0 ? `${search.coverage.pendingAssetCount} ${search.coverage.pendingAssetCount === 1 ? 'item is' : 'items are'} still being indexed and may match later.` : undefined}
            action={
              <div className='flex flex-wrap justify-center gap-2'>
                <Control tone='secondary' onClick={() => setQuery('')}>
                  Clear search
                </Control>
                {scopeKind !== 'workspace' ? (
                  <Control tone='ghost' onClick={() => update({ collection: '', scope: 'all' })}>
                    Search entire Library
                  </Control>
                ) : null}
              </div>
            }
          />
        ) : (
          renderItems(
            hitItems.map(({ group, asset }) => ({
              asset,
              footer: <HitDetails group={group} onOpenAt={(locator) => openDetail(asset, locator)} onPlayFrom={kindOf(asset) === 'audio' || kindOf(asset) === 'video' ? (startMs) => void playFrom(asset, startMs) : undefined} />
            }))
          )
        )}
        {search.nextCursor ? (
          <Control tone='secondary' className='self-center' disabled={search.loadingMore} onClick={search.loadMore}>
            {search.loadingMore ? 'Loading…' : 'Show more results'}
          </Control>
        ) : null}
      </div>
    );
  } else if (shown.length === 0) {
    // No matches is not an empty library (DNA §13.5): say what can be cleared.
    content = (
      <StateMessage
        kind='empty'
        title={
          normalizedQuery
            ? `No asset matches “${normalizedQuery}”`
            : scopeKind === 'collection'
              ? 'This collection is empty'
              : url.kind !== 'all'
                ? `No ${KIND_OPTIONS.find((option) => option.value === url.kind)?.label.toLowerCase() ?? 'items'} match these filters`
                : url.status === 'processing'
                  ? 'Nothing is processing'
                  : url.status === 'attention'
                    ? 'Nothing needs attention'
                    : url.status === 'ready'
                      ? 'No ready items match these filters'
                      : url.use === 'unused'
                  ? 'Every asset is used in a post'
                  : url.use === 'used'
                    ? 'No asset is used in a post yet'
                    : 'No assets match these filters'
        }
        action={
          <Control
            tone='secondary'
            onClick={() => {
              if (normalizedQuery) setQuery('');
              else update({ use: 'all', kind: 'all', status: 'all', tag: '', collection: '', scope: 'all' });
            }}
          >
            {normalizedQuery ? 'Clear search' : 'Show all'}
          </Control>
        }
      />
    );
  } else {
    content = renderItems(shown.map((asset) => ({ asset })));
  }

  const detailProps = {
    asset: current,
    open: detailOpen,
    onOpenChange: (open: boolean) => {
      if (!open) update({ asset: '' });
    },
    uses: current ? library.usesOf(current.id) : [],
    publishing: current ? library.isPublishing(current.id) : false,
    canEdit,
    canApprove,
    isOwner,
    deleting: current ? deletingIds.has(current.id) : false,
    currentUserId: auth.user?.id ?? null,
    platforms: library.platforms,
    onDelete: setPendingDelete,
    intelligence: intel.reachable,
    focusLocator,
    onAnnounce: announce,
    onOpenAsset: (assetId: string) => {
      setFocusLocator(null);
      update({ asset: assetId });
    },
    onUseInDraft:
      canEdit && gates.packs.enabled
        ? (asset: LibraryAsset, ref: AssetRef) => {
            askForPack('detail', [ref], [assetTitle(asset)]);
            // The open item travels in the pack's return state, so coming back opens it again.
            update({ asset: '' });
          }
        : undefined,
    voiceEnabled: gates.voice.enabled,
    voiceNote: gates.voice.reason
  };

  const headerActions = canEdit ? (
    <AddMenu
      disabled={library.revision === null}
      busy={uploadingFile || upload.uploading}
      busyLabel={uploadingFile ? 'Adding a file…' : uploadingText(upload.progress)}
      onUploadFiles={() => filePicker.current?.click()}
      storage={library.storage ?? null}
      onAdded={announce}
    />
  ) : undefined;

  return (
    <PageContainer infoContent={infoContent}>
      <div data-library-page='' className='contents'>
      {/* Title and the one primary Add on one row at every width (redesign §3). */}
      <PageHeader title='Library' infoContent={infoContent} actions={headerActions} className='flex-row flex-wrap items-center justify-between gap-3 md:items-center' />
      <div {...getRootProps({ className: 'relative flex min-w-0 flex-1 flex-col gap-4' })}>
        <input {...getInputProps({ 'aria-label': 'Drop assets into Library' })} />
        <input
          ref={filePicker}
          type='file'
          className='sr-only'
          multiple
          aria-label='Choose assets to add to Library'
          onChange={(event) => {
            const files = [...(event.currentTarget.files ?? [])];
            if (files.length) void uploadFiles(files);
          }}
        />
        <p role='status' aria-live='polite' aria-atomic='true' className='sr-only'>
          {announcement}
        </p>

        <div className={cn('grid min-w-0 items-start gap-3 lg:gap-x-6', LAYOUT[railNarrow ? 'narrow' : 'wide'], dockedOpen && INSPECTOR_LAYOUT[railNarrow ? 'narrow' : 'wide'])}>
          <div className='min-w-0 lg:col-start-2 lg:row-start-1'>
            <LibrarySearchField
              value={query}
              onChange={setQuery}
              scope={scope}
              scopeOptions={scopeOptions}
              onScope={(kind) => update(kind === 'workspace' ? { collection: '', scope: 'all' } : kind === 'selection' ? { scope: 'selection' } : { scope: 'all' })}
              searching={intelligent && search.loading}
              aside={
                gates.ask.enabled ? (
                  <SegmentedControl
                    label='Library mode'
                    size='sm'
                    widths='content'
                    value={url.panel}
                    onChange={(value) => update({ panel: value })}
                    options={[
                      { value: 'search', label: 'Search' },
                      { value: 'ask', label: 'Ask' }
                    ]}
                  />
                ) : undefined
              }
            />
          </div>

          <CollectionRail
            className='lg:col-start-1 lg:row-span-4 lg:row-start-1 lg:self-start'
            active={url.collection}
            onSelect={(collectionId) => update({ collection: collectionId, scope: collectionId ? 'collection' : 'all' })}
            canEdit={canEdit}
            collapsed={railNarrow}
            onCollapsedChange={collapseRail}
            storage={library.storage ?? null}
            smartCollections={intel.reachable}
            onAnnounce={announce}
          />

          <div className='min-w-0 lg:col-start-2 lg:row-start-2'>
            <LibraryFilters
              use={url.use}
              onUse={(value) => update({ use: value })}
              counts={exactCounts ? library.counts : null}
              kind={url.kind}
              onKind={(value) => update({ kind: value })}
              kindCounts={kindCounts}
              status={url.status}
              onStatus={(value) => update({ status: value })}
              statusCounts={exactCounts ? library.statusCounts : null}
              tag={url.tag}
              onTag={(value) => update({ tag: value })}
              tags={library.tags}
              sort={library.sort}
              onSort={(value) => update({ sort: value })}
              sortOptions={sortOptions}
              searching={intelligent}
              onClear={() => update({ use: 'all', kind: 'all', status: 'all', tag: '' })}
              summary={statusLine}
              view={<LibraryViewSwitch mode={url.mode} onMode={(value) => update({ mode: value })} density={density} onDensity={(value) => update({ density: value })} />}
            />
          </div>

          <div ref={resultsRef} className='flex min-w-0 flex-col gap-4 lg:col-start-2 lg:row-start-3'>
            {uploadingFile ? (
              <p role='status' className='text-muted-foreground text-sm'>
                {fileProgress}
              </p>
            ) : null}
            {fileFailure ? (
              <StateMessage
                kind='error'
                layout='inline'
                title='Upload needs attention'
                description={fileFailure}
                action={
                  pendingFile.current ? (
                    <div className='flex gap-2'>
                      <Control tone='secondary' size='sm' onClick={() => void uploadLibraryFile(pendingFile.current!.file)}>
                        Retry
                      </Control>
                      <Control
                        tone='ghost'
                        size='sm'
                        onClick={() => {
                          const pending = pendingFile.current;
                          if (pending)
                            void (pending.video ? api.abortVideoUpload(workspaceId, pending.assetId) : api.deleteLibraryFile(workspaceId, pending.assetId))
                              .then(() => {
                                pendingFile.current = null;
                                setFileFailure(null);
                                void client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
                              })
                              .catch((e) => toast.error(e instanceof Error ? e.message : 'Could not remove upload'));
                        }}
                      >
                        Remove pending upload
                      </Control>
                    </div>
                  ) : undefined
                }
              />
            ) : null}
            {notice?.warning ? <StateMessage kind={notice.level === 'full' ? 'error' : 'partial'} layout='inline' title={notice.warning} /> : null}
            {library.normalized.isError ? (
              <StateMessage
                kind='error'
                layout='inline'
                title='Documents could not be loaded'
                description='Your media remains available. Retry to load the full Library.'
                action={
                  <Control tone='secondary' size='sm' onClick={() => void library.normalized.refetch()}>
                    Retry Library
                  </Control>
                }
              />
            ) : null}
            {search.failed && normalizedQuery ? <StateMessage kind='partial' layout='inline' title='Showing name and text matches' description='The Library search service didn’t answer, so these results come from the basic search.' /> : null}
            {/* Unsupported, offline and refused are different states (DNA §20.1), each with its own reason. */}
            {storageMissing ? (
              <StateMessage kind='unsupported' layout='inline' title='Media uploads aren’t available yet.' />
            ) : upload.blocker ? (
              <StateMessage kind={upload.blocker.status === 503 ? 'offline' : 'error'} title='Couldn’t upload' description={upload.blocker.status === 503 ? 'Files that weren’t sent can be uploaded again.' : upload.blocker.message} />
            ) : null}

            <AnimatePresence initial={false}>
              {upload.items.length > 0 && (
                <motion.div
                  key='uploads'
                  initial={reduce ? { opacity: 0 } : { opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: reduce ? 0 : 0.2, ease: EASE_OUT } }}
                  exit={{ opacity: 0, transition: { duration: reduce ? 0 : 0.15, ease: EASE_OUT } }}
                >
                  <UploadTray items={upload.items} progress={upload.progress} onDismiss={upload.dismiss} />
                </motion.div>
              )}
            </AnimatePresence>

            {!asking ? (
              <SuggestionsPanel
                enabled={intel.reachable}
                canEdit={canEdit}
                onOpen={(assetId) => {
                  setFocusLocator(null);
                  update({ asset: assetId });
                }}
                onAnnounce={announce}
              />
            ) : null}

            {askOff ? <StateMessage kind='unsupported' layout='inline' title={askOff} /> : null}

            {activeSmart ? <SmartCollectionPanel collectionId={url.collection} canEdit={canEdit} enabled={intel.reachable} onAnnounce={announce} /> : null}

            {asking ? (
              <AskLibraryPanel
                scope={searchScope}
                scopeDescription={scope}
                canEdit={canEdit}
                isOwner={isOwner}
                enabled={intel.reachable}
                summariesAvailable={summariesAvailable}
                onAnnounce={announce}
              />
            ) : null}

            {/* Asking never discards the search: the results stay mounted, only hidden. */}
            <div hidden={asking} className='flex min-w-0 flex-col gap-4'>
              {content}
            </div>

            {!asking && !intelligent && library.normalized.hasNextPage ? (
              <Control tone='secondary' className='self-center' disabled={library.normalized.isFetchingNextPage} onClick={() => void library.normalized.fetchNextPage()}>
                Load more assets
              </Control>
            ) : null}

            <BatchBar
              selected={selectedItems}
              collections={collectionList}
              activeCollection={scopeKind === 'collection' && activeCollection ? activeCollection : null}
              canEdit={canEdit}
              usedCount={selectedUsed}
              run={batch.run}
              onRun={(kind, ids, params) => void batch.execute(kind, ids, params)}
              onRetry={batch.retry}
              onDismissRun={batch.dismiss}
              onSelectAll={() => setSelection([...new Set([...selection, ...orderedIds])])}
              onClear={() => setSelection([])}
              canSelectMore={orderedIds.some((id) => !selectedSet.has(id))}
              searchWithin={scopeKind === 'selection'}
              onSearchWithin={(on) => update({ scope: on ? 'selection' : url.collection ? 'collection' : 'all' })}
              onBuildPack={
                canEdit && gates.packs.enabled
                  ? () =>
                      askForPack(
                        'batch',
                        selectedItems.map((item) => item.ref),
                        selectedItems.map((item) => item.title)
                      )
                  : null
              }
              packNote={gates.recommendations.reason}
              stickyBottom={clearance.stickyBottom}
            />
          </div>

          {dockedOpen ? (
            <div className='hidden min-w-0 self-stretch xl:col-start-3 xl:row-span-4 xl:row-start-1 xl:block'>
              <AssetDetail docked {...detailProps} />
            </div>
          ) : null}
        </div>

        <AnimatePresence>
          {isDragActive && (
            <motion.div
              key='drop'
              aria-hidden
              initial={{ opacity: 0 }}
              animate={{ opacity: 1, transition: { duration: reduce ? 0 : 0.15, ease: EASE_OUT } }}
              exit={{ opacity: 0, transition: { duration: reduce ? 0 : 0.08, ease: EASE_OUT } }}
              className={cn(
                'rafii-elevated pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-[var(--rafii-radius-card)] text-sm font-medium outline-2 outline-dashed -outline-offset-[12px]',
                isDragReject ? 'outline-destructive text-destructive' : 'outline-foreground/50 text-foreground'
              )}
            >
              <Icons.upload className='size-6' />
              {isDragReject ? 'This file is empty or over the upload limit' : 'Drop photos, videos, audio or documents · files up to 50 MB'}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Room for the Now Playing bar above the tab bar, so it never covers the last result or action. */}
      <div aria-hidden data-library-bottom-clearance='' style={{ height: clearance.spacer }} />

      </div>

      {!dockedOpen ? <AssetDetail {...detailProps} /> : null}

      <SourcePackFlow
        request={packRequest}
        onClose={() => setPackRequest(null)}
        currentScope={{ scope: searchScope, label: scopeLabel(scope) }}
        gates={gates}
        titleOf={(assetId) => {
          const asset = library.byKey.get(normalizeKey(assetId));
          return asset ? assetTitle(asset) : null;
        }}
        onAnnounce={announce}
        onLeave={(packId) => {
          // Leaving now: this visit doesn't restore its own pack; the return visit does.
          restoredPack.current = packId;
          return commit({ pack: packId });
        }}
      />

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 md:p-6'>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this asset?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete && library.usesOf(pendingDelete.id).length > 0 ? `Used in ${library.usesOf(pendingDelete.id).length} ${library.usesOf(pendingDelete.id).length === 1 ? 'post' : 'posts'}. ` : ''}
              This permanently deletes the stored media. Scheduled posts using it will need a new review; published posts aren’t affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel variant='glass' className={controlClass({ tone: 'secondary' })}>
              Keep
            </AlertDialogCancel>
            <AlertDialogAction
              variant='destructive'
              className={controlClass({ tone: 'danger' })}
              onClick={() => {
                if (pendingDelete) void remove(pendingDelete);
                setPendingDelete(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}
