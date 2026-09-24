'use client';

import { useCallback, useState, type ReactNode } from 'react';
import Link from 'next/link';
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
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { keys, useAct, useUsage } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT } from '@/lib/ease';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { AssetCard, badgeClass, saysStorageNotConfigured } from './asset-card';
import { AssetDetail } from './asset-detail';
import { ACCEPTED_TYPES, MAX_UPLOAD_BYTES, useLibrary, type LibraryAsset, type LibraryFilter, type LibrarySort } from './use-library';
import { useUploadQueue, type UploadItem, type UploadProgress, type UploadStatus } from './use-upload-queue';

const infoContent = {
  title: 'Library',
  sections: [
    {
      title: 'Private by default',
      description: 'Images live in private storage and are served only to members of this workspace, through the API.'
    },
    {
      title: 'Provenance',
      description: 'Every image is stored with its hash. A post records the exact hash it was approved with, so what publishes is what was reviewed.'
    },
    {
      title: 'What is accepted',
      description:
        'JPEG or PNG, up to 8 MB, 320–4096 px per side and at most 16.7 megapixels. Each image is fully decoded and re-encoded as JPEG with its metadata removed. Video is not accepted in this release.'
    },
    {
      title: 'Used and unused',
      description: 'An image counts as used when a publishing job in any state, or a review waiting for approval, records it.'
    }
  ]
};

const FILTERS: { value: LibraryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'unused', label: 'Unused' },
  { value: 'used', label: 'Used' }
];

const SORT_LABELS: Record<LibrarySort, string> = {
  newest: 'Newest first',
  stored: 'Workspace order',
  largest: 'Largest first'
};

const SKELETON_KEYS = Array.from({ length: 12 }, (_, index) => `skeleton-${index}`);

/* The one inverted commitment (Upload assets, DNA §21.9) on the motion button. */
const ACTION = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-5 text-sm hover:bg-transparent hover:brightness-[1.06]';

function rejectionMessage({ file, errors }: FileRejection) {
  const code = errors[0]?.code;
  if (code === 'file-too-large') return `${file.name} is larger than 8 MB, so it was not added.`;
  if (code === 'file-too-small') return `${file.name} is empty, so it was not added.`;
  if (code === 'file-invalid-type') return `${file.name} is not a JPEG or PNG, so it was not added.`;
  return `${file.name} was not added: ${errors[0]?.message ?? 'it cannot be uploaded'}.`;
}

/** Waiting, reading, sending, uploaded, failed and not sent stay distinct states (DNA §21.9), in words. */
const UPLOAD_BADGE: Record<UploadStatus, { status: AnimatedBadgeStatus; label: string }> = {
  waiting: { status: 'neutral', label: 'waiting' },
  reading: { status: 'loading', label: 'reading' },
  sending: { status: 'loading', label: 'sending' },
  done: { status: 'success', label: 'uploaded' },
  failed: { status: 'danger', label: 'failed' },
  skipped: { status: 'neutral', label: 'not sent' }
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
  const { workspaceId } = useWorkspaceApi();
  const act = useAct();
  const usage = useUsage();
  const upload = useUploadQueue();

  const [filter, setFilter] = useState<LibraryFilter>('all');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [query, setQuery] = useState('');
  const auth = useAuth();
  const library = useLibrary({ filter, sort, query });
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
    accept: ACCEPTED_TYPES,
    maxSize: MAX_UPLOAD_BYTES,
    minSize: 1,
    multiple: true,
    noClick: true,
    noKeyboard: true,
    disabled: !canEdit || library.revision === null,
    onDrop: (accepted, rejected) => {
      for (const rejection of rejected) toast.error(rejectionMessage(rejection));
      upload.enqueue(accepted);
    }
  });

  // The asset stays in state while the sheet closes; it only counts as open while the image still exists.
  const current = detail ? (assets.find((asset) => asset.id === detail.id) ?? detail) : null;
  const detailVisible = detailOpen && detail !== null && assets.some((asset) => asset.id === detail.id);
  const storageMb = usage.data?.entitlement?.storageMb;
  const uploadStorageMissing = saysStorageNotConfigured(upload.blocker);
  const storageMissing = mediaStorageMissing || uploadStorageMissing;

  // The sort is a display choice inside the labelled Filters panel; the default is not a narrowing (DNA §10.5).
  const defaultSort: LibrarySort = library.hasTimestamps ? 'newest' : 'stored';
  const sortActive = library.sort !== defaultSort ? 1 : 0;
  const sortOptions = [...(library.hasTimestamps ? [{ value: 'newest', label: SORT_LABELS.newest }] : []), { value: 'stored', label: SORT_LABELS.stored }, { value: 'largest', label: SORT_LABELS.largest }];

  function openDetail(asset: LibraryAsset) {
    setDetail(asset);
    setDetailOpen(true);
  }

  async function remove(asset: LibraryAsset) {
    const revision = library.revision;
    if (revision === null) return;
    setDeletingIds((ids) => new Set(ids).add(asset.id));
    try {
      await act.mutateAsync({ revision, action: 'p2_media_delete', payload: { assetId: asset.id } });
      toast.success('Image deleted.');
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'The image could not be deleted.');
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
        title='Could not load the library'
        description={snapshot.error instanceof Error ? snapshot.error.message : 'The workspace did not respond.'}
        action={
          <Button variant='glass' size='control' disabled={snapshot.isFetching} onClick={() => void snapshot.refetch()}>
            <Icons.refresh className={cn(snapshot.isFetching && 'animate-spin')} aria-hidden />
            Retry
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
          title='No images yet'
          description='Upload JPEG or PNG, up to 8 MB and 320–4096 px per side. Each image is fully decoded, stripped of metadata and stored with its hash. Attach it when you prepare a post from a draft.'
          action={
            <>
              {canEdit ? (
                <>
                  <Button variant='action' size='control' onClick={openPicker} disabled={library.revision === null}>
                    <Icons.upload aria-hidden />
                    Upload images
                  </Button>
                  <span className='text-muted-foreground self-center text-xs'>or drop files anywhere on this page</span>
                </>
              ) : (
                <span className='text-muted-foreground self-center text-xs'>Ask a workspace editor to add images.</span>
              )}
              <Link href='/app/ideas' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'control' }))}>
                Open Ideas
                <LearnMoreChevron />
              </Link>
            </>
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
          searchPlaceholder='Hash or size, e.g. 1080x1350'
          searchLabel='Search images by hash prefix or dimensions'
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
          filters={
            <FilterPanel count={sortActive} onClear={() => setSort(defaultSort)}>
              <FilterSelect id='library-sort' label='Sort' value={library.sort} onChange={(value) => setSort(value as LibrarySort)} options={sortOptions} />
            </FilterPanel>
          }
          count={
            <span data-tour='library-stats' className='inline-flex items-center gap-1'>
              <DigitSwap value={totals.count} />
              <span>{totals.count === 1 ? 'image' : 'images'} ·</span>
              <span>{formatBytes(totals.bytes)}</span>
              {totals.unknownBytes > 0 && <span>({totals.unknownBytes} without a size)</span>}
            </span>
          }
          summary={<ActiveFilters count={sortActive} summary={SORT_LABELS[library.sort]} onClear={() => setSort(defaultSort)} clearLabel='Reset sort' />}
        />

        {visible.length === 0 ? (
          // No matches is not an empty library (DNA §13.5): say what can be cleared.
          <StateMessage
            kind='empty'
            title={
              normalizedQuery
                ? `No image matches “${normalizedQuery}”`
                : filter === 'unused'
                  ? 'Every image is used in a post'
                  : 'No image is used in a post yet'
            }
            description={normalizedQuery ? 'Search matches the start of a hash, or dimensions such as 1080x1350.' : 'Switch to All to see every image.'}
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
          <div role='list' aria-label='Images' className='grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-6'>
            <AnimatePresence>
              {visible.map((asset, index) => (
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
              ))}
            </AnimatePresence>
          </div>
        )}

        <div className='text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed'>
          {!library.hasTimestamps && (
            <p>Images appear in the order the workspace returns them. Upload times are not recorded yet, so newest first is not offered.</p>
          )}
          <p>“Used” counts publishing jobs in any state and reviews waiting for approval. The workspace keeps its 20 most recent reviews.</p>
          {typeof storageMb === 'number' && <p>Your plan lists {storageMb} MB of storage. Uploads are not measured against it yet.</p>}
        </div>
      </div>
    );
  }

  return (
    <PageContainer
      pageTitle='Library'
      pageDescription='Images for your posts. Private to this workspace; each one is stored with its hash and attached when you prepare a post.'
      infoContent={infoContent}
      pageHeaderAction={uploadButton}
    >
      <div {...getRootProps({ className: 'relative flex min-w-0 flex-1 flex-col gap-4' })}>
        <input {...getInputProps({ 'aria-label': 'Choose JPEG or PNG images to upload' })} />

        {/* Unsupported, offline and refused are different states (DNA §20.1), each with its own reason. */}
        {storageMissing ? (
          <StateMessage
            kind='unsupported'
            title='Private media storage is not configured for this deployment'
            description={`${uploadStorageMissing && upload.blocker ? upload.blocker.message : 'Image previews could not load for this reason.'} Images cannot be uploaded, previewed or deleted until it is.`}
          />
        ) : upload.blocker ? (
          <StateMessage
            kind={upload.blocker.status === 503 ? 'offline' : 'error'}
            title={upload.blocker.status === 503 ? 'Uploads stopped because the workspace was unavailable' : 'The workspace refused the upload'}
            description={`${upload.blocker.message}${upload.blocker.status === 503 ? ' Files that were not sent can be uploaded again.' : ''}`}
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
              {isDragReject ? 'Only JPEG or PNG images can be uploaded' : 'Drop JPEG or PNG · up to 8 MB each'}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

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
            <AlertDialogTitle>Delete this image?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete && library.usesOf(pendingDelete.id).length > 0
                ? `It is used in ${library.usesOf(pendingDelete.id).length} ${library.usesOf(pendingDelete.id).length === 1 ? 'post' : 'posts'}. `
                : ''}
              Its bytes are removed from private storage. Posts that already published keep what the platform received; reviews and scheduled
              posts that use it stop being valid and need a new review.
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
