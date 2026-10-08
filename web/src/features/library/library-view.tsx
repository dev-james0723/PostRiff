'use client';

import { useCallback, useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { DigitSwap } from '@/components/motion/digit-swap';
import { ActiveFilters, FilterPanel, FilterSelect, SegmentedControl, StateMessage, Surface, Workbar } from '@/components/rafii';
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
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { putSignedUpload } from '@/lib/api/upload';
import { keys, useAct } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT } from '@/lib/ease';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { CollectionManager, useLibraryCollections } from './library-organizer';
import { blankLocation, checkDuration, checkVideoFile, extractFrames, readVideoMetadata } from '../agent/attachments/video-file';
import { kindOf } from '@/lib/media/asset-kinds';
import { STATUS } from '@/lib/status-labels';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { AssetCard, badgeClass, saysStorageNotConfigured } from './asset-card';
import { AssetListRow } from './asset-list-row';
import { AssetDetail } from './asset-detail';
import { MAX_PICK_BYTES, useLibrary, type LibraryAsset, type LibraryFilter, type LibraryKindFilter, type LibrarySort } from './use-library';
import { useUploadQueue, type UploadItem, type UploadProgress, type UploadStatus } from './use-upload-queue';

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
      description: 'Add photos, MP4/MOV videos, audio, PDF, Office documents, text and other files. Documents are indexed in the background. All files remain private to this workspace.'
    },
    {
      title: 'Used',
      description: 'Used by a scheduled or published post, or one waiting for review. Only the 20 most recent reviews count.'
    }
  ]
};

const FILTERS: { value: LibraryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'unused', label: 'Unused' },
  { value: 'used', label: 'Used' }
];

const VIDEO_UPLOAD_MIMES = new Set(['video/mp4', 'video/quicktime']);
const VIDEO_UPLOAD_EXTENSIONS = new Set(['mp4', 'mov', 'm4v']);

const SORT_LABELS: Record<LibrarySort, string> = {
  newest: 'Newest first',
  stored: 'Workspace order',
  largest: 'Largest first'
};

const KIND_LABELS: Record<LibraryKindFilter, string> = {
  all: 'All assets',
  image: 'Photos',
  video: 'Videos',
  audio: 'Audio',
  document: 'Documents',
  file: 'Files'
};

type LibraryViewMode = 'gallery' | 'list';

const SKELETON_KEYS = Array.from({ length: 12 }, (_, index) => `skeleton-${index}`);

/* The one inverted commitment (Upload assets, DNA §21.9) on the motion button. */
const ACTION = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-5 text-sm hover:bg-transparent hover:brightness-[1.06]';

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
          <Button variant='quiet' size='lg' onClick={onDismiss}>
            Dismiss
          </Button>
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

/** Loading keeps the loaded geometry (DNA §20.1): the workbar's shape, then the grid. */
function LibrarySkeleton() {
  return (
    <div className='flex flex-col gap-4' role='status' aria-busy='true' aria-label='Loading the library'>
      <div className='flex flex-col gap-2 md:flex-row md:items-center'>
        <Skeleton className='h-11 w-full rounded-[var(--rafii-radius-control)] md:flex-1' />
        <Skeleton className='h-11 w-full rounded-[var(--rafii-radius-segment)] md:w-64' />
        <Skeleton className='h-12 w-full rounded-[var(--rafii-radius-control)] md:w-28' />
      </div>
      <div className='grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-6'>
        {SKELETON_KEYS.map((key) => (
          <Skeleton key={key} className='aspect-[4/5] w-full rounded-[var(--rafii-radius-card)]' />
        ))}
      </div>
    </div>
  );
}

export function LibraryView() {
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const reduce = useReducedMotion();
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const act = useAct();
  const upload = useUploadQueue();

  const [filter, setFilter] = useState<LibraryFilter>('all');
  const [kindFilter, setKindFilter] = useState<LibraryKindFilter>('all');
  const [view, setView] = useState<LibraryViewMode>('gallery');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('');
  const [collection, setCollection] = useState('');
  const collections = useLibraryCollections();
  const pendingFile = useRef<{ file: File; assetId: string; put: boolean; video?: { frames: { at: number; data: string }[]; locationCleared: boolean } } | null>(null);
  const [fileFailure, setFileFailure] = useState<string | null>(null);
  const [fileProgress, setFileProgress] = useState('');
  const [uploadingFile, setUploadingFile] = useState(false);
  const filePicker = useRef<HTMLInputElement>(null);
  const auth = useAuth();
  const library = useLibrary({ filter, kindFilter, sort, query, tag, collection });
  const { snapshot, assets, visible, counts, totals } = library;

  const [detail, setDetail] = useState<LibraryAsset | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<LibraryAsset | null>(null);
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(() => new Set());
  /**
   * A preview request was answered "Private media storage is not configured." The latest answer wins: a preview
   * that loads afterwards clears it. Other 503s (storage briefly unreachable, a restart) keep Retry on the card instead.
   */
  const [mediaStorageMissing, setMediaStorageMissing] = useState(false);
  const markStorageMissing = useCallback(() => setMediaStorageMissing(true), []);
  const markPreviewLoaded = useCallback(() => setMediaStorageMissing(false), []);

  const { getRootProps, getInputProps, isDragActive, isDragReject, open: openPicker } = useDropzone({
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

  // The asset stays in state while the sheet closes; it only counts as open while the image still exists.
  const current = detail ? (assets.find((asset) => asset.id === detail.id) ?? detail) : null;
  const detailVisible = detailOpen && detail !== null && assets.some((asset) => asset.id === detail.id);
  const uploadStorageMissing = saysStorageNotConfigured(upload.blocker);
  const storageMissing = mediaStorageMissing || uploadStorageMissing;

  // The sort is a display choice inside the labelled Filters panel; the default is not a narrowing (DNA §10.5).
  const defaultSort: LibrarySort = library.hasTimestamps ? 'newest' : 'stored';
  const sortActive = library.sort !== defaultSort ? 1 : 0;
  const kindActive = kindFilter === 'all' ? 0 : 1;
  const filterCount = sortActive + kindActive + (tag ? 1 : 0) + (collection ? 1 : 0);
  const sortOptions = [...(library.hasTimestamps ? [{ value: 'newest', label: SORT_LABELS.newest }] : []), { value: 'stored', label: SORT_LABELS.stored }, { value: 'largest', label: SORT_LABELS.largest }];
  const activeFilterSummary = [
    kindActive ? KIND_LABELS[kindFilter] : null,
    sortActive ? SORT_LABELS[library.sort] : null
  ].filter(Boolean).join(' · ');

  function openDetail(asset: LibraryAsset) {
    setDetail(asset);
    setDetailOpen(true);
  }

  async function remove(asset: LibraryAsset) {
    const revision = library.revision;
    if (revision === null) return;
    setDeletingIds((ids) => new Set(ids).add(asset.id));
    try {
      const assetKind = kindOf(asset);
      if (assetKind === 'document' || assetKind === 'file' || assetKind === 'audio') {
        await api.deleteLibraryFile(workspaceId, asset.id);
        await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
      } else {
        await act.mutateAsync({ revision, action: 'p2_media_delete', payload: { assetId: asset.id } });
      }
      // The card leaves the grid, so success needs no toast.
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
      const encoded = await Promise.all(frames.map(async (frame) => ({ at: frame.at, data: await new Promise<string>((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1] ?? ''); reader.onerror = () => reject(new Error('Could not prepare preview')); reader.readAsDataURL(frame.blob);
      }) })));
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
    const photos = files.filter((file) => file.type.startsWith('image/'));
    for (const file of photos.filter((photo) => photo.size > MAX_PICK_BYTES)) toast.error(`${file.name} is over 30 MB`);
    upload.enqueue(photos.filter((photo) => photo.size <= MAX_PICK_BYTES));
    for (const file of files.filter((item) => !item.type.startsWith('image/'))) {
      await uploadLibraryFile(file);
      if (pendingFile.current) break;
    }
  }

  const uploadButton = canEdit ? (
    <StatefulButton
      data-tour='library-upload'
      className={ACTION}
      state={upload.buttonState}
      icon={<Icons.upload className='size-4' />}
      loadingText={uploadingText(upload.progress)}
      successText={upload.resultLabel || 'Uploaded'}
      errorText={upload.resultLabel || 'Upload failed'}
      // Each upload sends the snapshot revision, so the button waits until the snapshot has loaded.
      disabled={library.revision === null}
      onClick={openPicker}
    >
      Upload images
    </StatefulButton>
  ) : undefined;

  let content: ReactNode;
  if (snapshot.isPending) {
    content = <LibrarySkeleton />;
  } else if (snapshot.isError && !snapshot.data) {
    content = (
      <StateMessage
        kind='error'
        title='Couldn’t load the library'
        description={snapshot.error instanceof Error ? snapshot.error.message : undefined}
        action={
          <Button variant='glass' size='control' disabled={snapshot.isFetching} onClick={() => void snapshot.refetch()}>
            <Icons.refresh className={cn(snapshot.isFetching && 'animate-spin')} aria-hidden />
            Try again
          </Button>
        }
      />
    );
  } else if (assets.length === 0) {
    content = (
      <motion.div
        key='empty'
        data-tour='library-empty'
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.2, ease: EASE_OUT }}
        className='flex flex-1 flex-col'
      >
        <StateMessage
          kind='empty'
          media={
            <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 shrink-0 items-center justify-center rounded-full'>
              <Icons.media className='size-5' />
            </span>
          }
          title='No assets yet'
          description={canEdit ? 'Upload a photo here. Videos added from Rafii chat also appear in this Library.' : 'Only editors can add media.'}
          action={
            canEdit ? (
              <Button variant='action' size='control' onClick={openPicker} disabled={library.revision === null} title='Or drop JPEG or PNG files anywhere on this page'>
                <Icons.upload aria-hidden />
                Upload images
              </Button>
            ) : undefined
          }
        />
      </motion.div>
    );
  } else {
    const normalizedQuery = query.trim();
    content = (
      <div className='flex flex-col gap-4'>
        {/* WHAT (use filter) → FIND (search) → VIEW (sort, inside Filters); the Gallery is the one representation this collection has. */}
        <Workbar
          search={query}
          onSearch={setQuery}
          searchPlaceholder='Search titles, tags and extracted text'
          searchLabel='Search Library assets by title, filename, summary, tag, hash or dimensions'
          tabs={
            <div data-tour='library-filter' className='sm:w-fit'>
              <SegmentedControl
                label='Filter images by use'
                value={filter}
                onChange={setFilter}
                options={FILTERS.map((option) => ({
                  value: option.value,
                  label: (
                    <>
                      {option.label}
                      <DigitSwap value={counts[option.value]} className='text-muted-foreground text-xs' />
                    </>
                  )
                }))}
              />
            </div>
          }
          view={
            <SegmentedControl
              label='Library view'
              value={view}
              onChange={(value) => setView(value as LibraryViewMode)}
              options={[
                { value: 'gallery', label: 'Gallery' },
                { value: 'list', label: 'List' }
              ]}
            />
          }
          filters={
            <FilterPanel
              count={filterCount}
              onClear={() => {
                setKindFilter('all');
                setSort(defaultSort);
                setTag('');
                setCollection('');
              }}
            >
              <FilterSelect
                id='library-kind'
                label='Type'
                value={kindFilter}
                onChange={(value) => setKindFilter(value as LibraryKindFilter)}
                options={[
                  { value: 'all', label: `${KIND_LABELS.all} (${library.kindCounts.all})` },
                  { value: 'image', label: `${KIND_LABELS.image} (${library.kindCounts.image})` },
                  { value: 'video', label: `${KIND_LABELS.video} (${library.kindCounts.video})` },
                  { value: 'audio', label: `${KIND_LABELS.audio} (${library.kindCounts.audio})` },
                  { value: 'document', label: `${KIND_LABELS.document} (${library.kindCounts.document})` },
                  { value: 'file', label: `${KIND_LABELS.file} (${library.kindCounts.file})` }
                ]}
              />
              <FilterSelect id='library-tag' label='Tag' value={tag} onChange={setTag} options={[{ value: '', label: 'All tags' }, ...library.tags.map((t) => ({ value: t, label: t }))]} />
              <FilterSelect id='library-collection' label='Collection' value={collection} onChange={setCollection} options={[{ value: '', label: 'All collections' }, ...(collections.data?.collections ?? []).map((c) => ({ value: c.id, label: c.name }))]} />
              <FilterSelect id='library-sort' label='Sort' value={library.sort} onChange={(value) => setSort(value as LibrarySort)} options={sortOptions} />
            </FilterPanel>
          }
          count={
            <span data-tour='library-stats' className='inline-flex items-center gap-1'>
              <DigitSwap value={totals.count} />
              <span>{totals.count === 1 ? 'asset' : 'assets'}</span>
              <span className='hidden md:inline' title={totals.unknownBytes > 0 ? `${totals.unknownBytes} without a size` : undefined}>
                · {formatBytes(totals.bytes)}
              </span>
            </span>
          }
          summary={
            <ActiveFilters
              count={filterCount}
              summary={activeFilterSummary}
              onClear={() => {
                setKindFilter('all');
                setSort(defaultSort);
                setTag('');
                setCollection('');
              }}
              clearLabel='Clear filters'
            />
          }
        />

        {visible.length === 0 ? (
          // No matches is not an empty library (DNA §13.5): say what can be cleared.
          <StateMessage
            kind='empty'
            title={
              normalizedQuery
                ? `No asset matches “${normalizedQuery}”`
                : kindFilter !== 'all'
                  ? `No ${kindFilter === 'image' ? 'photos' : kindFilter === 'video' ? 'videos' : kindFilter === 'audio' ? 'audio files' : kindFilter === 'document' ? 'documents' : 'files'} match these filters`
                  : filter === 'unused'
                    ? 'Every asset is used in a post'
                    : 'No asset is used in a post yet'
            }
            action={
              <Button
                variant='glass'
                size='control'
                onClick={() => {
                  if (normalizedQuery) setQuery('');
                  else setFilter('all');
                }}
              >
                {normalizedQuery ? 'Clear search' : 'Show all'}
              </Button>
            }
          />
        ) : (
          <div
            role='list'
            aria-label='Library assets'
            className={cn(
              view === 'gallery'
                ? 'grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-6'
                : 'flex flex-col gap-2'
            )}
          >
            <AnimatePresence>
              {visible.map((asset, index) =>
                view === 'gallery' ? (
                  <AssetCard
                    key={asset.id}
                    asset={asset}
                    uses={library.usesOf(asset.id)}
                    publishing={library.isPublishing(asset.id)}
                    first={index === 0}
                    canEdit={canEdit}
                    canApprove={canApprove}
                    deleting={deletingIds.has(asset.id)}
                    onOpen={() => openDetail(asset)}
                    onDelete={() => setPendingDelete(asset)}
                    onStorageMissing={markStorageMissing}
                    onPreviewLoaded={markPreviewLoaded}
                  />
                ) : (
                  <AssetListRow
                    key={asset.id}
                    asset={asset}
                    uses={library.usesOf(asset.id)}
                    publishing={library.isPublishing(asset.id)}
                    first={index === 0}
                    canEdit={canEdit}
                    canApprove={canApprove}
                    deleting={deletingIds.has(asset.id)}
                    onOpen={() => openDetail(asset)}
                    onDelete={() => setPendingDelete(asset)}
                    onStorageMissing={markStorageMissing}
                    onPreviewLoaded={markPreviewLoaded}
                  />
                )
              )}
            </AnimatePresence>
          </div>
        )}

      </div>
    );
  }

  const headerActions = canEdit ? (
    <div className='flex flex-wrap items-center gap-2'>
      <Button variant='glass' size='control' disabled={uploadingFile} onClick={() => filePicker.current?.click()}>
        {uploadingFile ? <Icons.spinner className='animate-spin' aria-hidden /> : <Icons.upload aria-hidden />}
        {uploadingFile ? 'Adding assets…' : 'Add assets'}
      </Button>
      {uploadButton}
    </div>
  ) : undefined;

  return (
    <PageContainer
      pageTitle='Library'
      infoContent={infoContent}
      pageHeaderAction={headerActions}
    >
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

        {uploadingFile ? <p role='status' className='text-muted-foreground text-sm'>{fileProgress}</p> : null}
        {fileFailure ? <StateMessage kind='error' layout='inline' title='Upload needs attention' description={fileFailure} action={pendingFile.current ? <div className='flex gap-2'><Button variant='glass' onClick={() => void uploadLibraryFile(pendingFile.current!.file)}>Retry</Button><Button variant='quiet' onClick={() => { const pending = pendingFile.current; if (pending) void (pending.video ? api.abortVideoUpload(workspaceId, pending.assetId) : api.deleteLibraryFile(workspaceId, pending.assetId)).then(() => { pendingFile.current = null; setFileFailure(null); void client.invalidateQueries({ queryKey: ['library-assets', workspaceId] }); }).catch((e) => toast.error(e instanceof Error ? e.message : 'Could not remove upload')); }}>Remove pending upload</Button></div> : undefined} /> : null}
        <CollectionManager canEdit={canEdit} />
        {library.storage ? <p className='text-muted-foreground text-xs'>{formatBytes(library.storage.usedBytes)} of {formatBytes(library.storage.limitBytes)} workspace storage used</p> : null}
        {library.normalized.isError ? <StateMessage kind='error' layout='inline' title='Documents could not be loaded' description='Your media remains available. Retry to load the full Library.' action={<Button variant='glass' onClick={() => void library.normalized.refetch()}>Retry Library</Button>} /> : null}
        {/* Unsupported, offline and refused are different states (DNA §20.1), each with its own reason. */}
        {storageMissing ? (
          <StateMessage kind='unsupported' layout='inline' title='Media uploads aren’t available yet.' />
        ) : upload.blocker ? (
          <StateMessage
            kind={upload.blocker.status === 503 ? 'offline' : 'error'}
            title='Couldn’t upload'
            description={upload.blocker.status === 503 ? 'Files that weren’t sent can be uploaded again.' : upload.blocker.message}
          />
        ) : null}

        <AnimatePresence initial={false}>
          {upload.items.length > 0 && (
            <motion.div
              key='uploads'
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0, transition: { duration: 0.2, ease: EASE_OUT } }}
              exit={{ opacity: 0, transition: { duration: 0.15, ease: EASE_OUT } }}
            >
              <UploadTray items={upload.items} progress={upload.progress} onDismiss={upload.dismiss} />
            </motion.div>
          )}
        </AnimatePresence>

        {content}

        <AnimatePresence>
          {isDragActive && (
            <motion.div
              key='drop'
              aria-hidden
              initial={{ opacity: 0 }}
              animate={{ opacity: 1, transition: { duration: 0.15, ease: EASE_OUT } }}
              exit={{ opacity: 0, transition: { duration: 0.08, ease: EASE_OUT } }}
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

      {library.normalized.hasNextPage ? <Button variant='glass' disabled={library.normalized.isFetchingNextPage} onClick={() => void library.normalized.fetchNextPage()}>Load more assets</Button> : null}
      <AssetDetail
        asset={current}
        open={detailVisible}
        onOpenChange={setDetailOpen}
        uses={current ? library.usesOf(current.id) : []}
        publishing={current ? library.isPublishing(current.id) : false}
        canEdit={canEdit}
        canApprove={canApprove}
        deleting={current ? deletingIds.has(current.id) : false}
        currentUserId={auth.user?.id ?? null}
        platforms={library.platforms}
        onDelete={setPendingDelete}
      />

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 md:p-6'>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this asset?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete && library.usesOf(pendingDelete.id).length > 0
                ? `Used in ${library.usesOf(pendingDelete.id).length} ${library.usesOf(pendingDelete.id).length === 1 ? 'post' : 'posts'}. `
                : ''}
              This permanently deletes the stored media. Scheduled posts using it will need a new review; published posts aren’t affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel variant='glass' size='control'>Keep</AlertDialogCancel>
            <AlertDialogAction
              variant='destructive'
              size='control'
              className='rounded-[var(--rafii-radius-control)]'
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
