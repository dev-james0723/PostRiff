'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
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
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { keys, useAct, useUsage } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAuth } from '@/lib/auth/session';
import { EASE_OUT } from '@/lib/ease';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { AssetCard, saysStorageNotConfigured } from './asset-card';
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

/** The stagger covers the first eight cards (35 ms apart, 280 ms at most); later cards arrive with the eighth. */
const STAGGER = 0.035;
const STAGGER_CAP = 8;
const SKELETON_KEYS = Array.from({ length: 12 }, (_, index) => `skeleton-${index}`);

function rejectionMessage({ file, errors }: FileRejection) {
  const code = errors[0]?.code;
  if (code === 'file-too-large') return `${file.name} is larger than 8 MB, so it was not added.`;
  if (code === 'file-too-small') return `${file.name} is empty, so it was not added.`;
  if (code === 'file-invalid-type') return `${file.name} is not a JPEG or PNG, so it was not added.`;
  return `${file.name} was not added: ${errors[0]?.message ?? 'it cannot be uploaded'}.`;
}

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
    <section aria-labelledby='library-uploads' className='bg-card rounded-lg border'>
      <div className='flex items-center justify-between gap-2 border-b px-3 py-2'>
        <h3 id='library-uploads' aria-live='polite' className='text-sm font-medium'>
          {progress ? uploadingText(progress) : `${done} of ${items.length} uploaded`}
        </h3>
        {!progress && (
          <Button variant='ghost' size='xs' onClick={onDismiss}>
            Dismiss
          </Button>
        )}
      </div>
      <ul className='max-h-60 divide-y overflow-y-auto'>
        {items.map((item) => {
          const badge = UPLOAD_BADGE[item.status];
          return (
            <li key={item.key} className='flex items-center gap-3 px-3 py-2'>
              <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                <span className='truncate text-sm'>{item.name}</span>
                <span className={cn('text-xs', item.status === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>
                  {formatBytes(item.bytes)}
                  {item.message ? ` · ${item.message}` : ''}
                </span>
              </div>
              <AnimatedBadge size='sm' status={badge.status} showIcon={item.status !== 'waiting' && item.status !== 'skipped'}>
                {badge.label}
              </AnimatedBadge>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function LibrarySkeleton() {
  return (
    <div className='flex flex-col gap-4' aria-busy='true' aria-label='Loading the library'>
      <div className='flex flex-wrap items-center gap-2'>
        <Skeleton className='h-8 w-full md:w-64' />
        <Skeleton className='h-9 w-full sm:w-56' />
        <Skeleton className='h-7 w-44 sm:ml-auto' />
      </div>
      <div className='grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-6'>
        {SKELETON_KEYS.map((key) => (
          <Skeleton key={key} className='aspect-square w-full rounded-lg' />
        ))}
      </div>
    </div>
  );
}

export function LibraryView() {
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const auth = useAuth();
  const reduce = useReducedMotion();
  const client = useQueryClient();
  const { workspaceId } = useWorkspaceApi();
  const act = useAct();
  const usage = useUsage();
  const upload = useUploadQueue();

  const [filter, setFilter] = useState<LibraryFilter>('all');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [query, setQuery] = useState('');
  const library = useLibrary({ filter, sort, query });
  const { snapshot, assets, visible, counts, totals } = library;

  const [detail, setDetail] = useState<LibraryAsset | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<LibraryAsset | null>(null);
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(() => new Set());
  const [revealed, setRevealed] = useState(false);
  /**
   * A preview request was answered "Private media storage is not configured." The latest answer wins: a preview
   * that loads afterwards clears it. Other 503s (storage briefly unreachable, a restart) keep Retry on the card instead.
   */
  const [mediaStorageMissing, setMediaStorageMissing] = useState(false);
  const markStorageMissing = useCallback(() => setMediaStorageMissing(true), []);
  const markPreviewLoaded = useCallback(() => setMediaStorageMissing(false), []);

  // Once the first cards have staggered in, later arrivals (an upload, a filter change) enter without delay.
  useEffect(() => {
    if (revealed || assets.length === 0) return;
    const timer = setTimeout(() => setRevealed(true), 600);
    return () => clearTimeout(timer);
  }, [assets.length, revealed]);

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
  const creatorOnly = canEdit && Boolean(auth.user?.id) && Boolean(library.stateOwnerId) && auth.user?.id !== library.stateOwnerId;

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
      <Alert variant='destructive'>
        <Icons.alertCircle aria-hidden />
        <AlertTitle>Could not load the library</AlertTitle>
        <AlertDescription className='flex flex-col items-start gap-2'>
          <span>{snapshot.error instanceof Error ? snapshot.error.message : 'The workspace did not respond.'}</span>
          <Button size='sm' variant='outline' disabled={snapshot.isFetching} onClick={() => void snapshot.refetch()}>
            <Icons.refresh className={cn(snapshot.isFetching && 'animate-spin')} aria-hidden />
            Retry
          </Button>
        </AlertDescription>
      </Alert>
    );
  } else if (assets.length === 0) {
    content = (
      <motion.div
        key='empty'
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.2, ease: EASE_OUT }}
        className='flex flex-1 flex-col'
      >
        <Empty className='border' data-tour='library-empty'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.media />
            </EmptyMedia>
            <EmptyTitle>No images yet</EmptyTitle>
            <EmptyDescription>
              Upload JPEG or PNG, up to 8 MB and 320–4096 px per side. Each image is fully decoded, stripped of metadata and stored with its hash.
              Attach it when you prepare a post from a draft.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            {canEdit ? (
              <>
                <Button onClick={openPicker} disabled={library.revision === null}>
                  <Icons.upload aria-hidden />
                  Upload images
                </Button>
                <span className='text-muted-foreground text-xs'>or drop files anywhere on this page</span>
              </>
            ) : (
              <span className='text-muted-foreground text-xs'>Ask a workspace editor to add images.</span>
            )}
            <Link href='/app/ideas' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }))}>
              Open Ideas
              <LearnMoreChevron />
            </Link>
          </EmptyContent>
        </Empty>
      </motion.div>
    );
  } else {
    const normalizedQuery = query.trim();
    content = (
      <div className='flex flex-col gap-4'>
        <div className='flex flex-wrap items-center gap-2'>
          <InputGroup className='w-full md:w-64'>
            <InputGroupAddon>
              <Icons.search aria-hidden />
            </InputGroupAddon>
            <InputGroupInput
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder='Hash or size, e.g. 1080x1350'
              aria-label='Search images by hash prefix or dimensions'
              spellCheck={false}
            />
            {query && (
              <InputGroupAddon align='inline-end'>
                <InputGroupButton size='icon-xs' aria-label='Clear search' onClick={() => setQuery('')}>
                  <Icons.close aria-hidden />
                </InputGroupButton>
              </InputGroupAddon>
            )}
          </InputGroup>
          <Tabs value={filter} onValueChange={(value) => setFilter(value as LibraryFilter)} variant='segment' className='w-full sm:w-auto'>
            <TabsList aria-label='Filter images by use' data-tour='library-filter' className='flex w-full border sm:inline-flex sm:w-auto'>
              {FILTERS.map((option) => (
                <TabsTrigger key={option.value} value={option.value} wrapperClassName='flex-1 sm:flex-none' className='w-full gap-1.5'>
                  {option.label}
                  <DigitSwap value={counts[option.value]} className='text-xs opacity-75' />
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className='flex w-full flex-wrap items-center justify-between gap-2 sm:ml-auto sm:w-auto sm:justify-end'>
            <Select value={library.sort} onValueChange={(value) => setSort(value as LibrarySort)}>
              <SelectTrigger size='sm' aria-label='Sort images'>
                <SelectValue>{SORT_LABELS[library.sort]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {library.hasTimestamps && <SelectItem value='newest'>{SORT_LABELS.newest}</SelectItem>}
                <SelectItem value='stored'>{SORT_LABELS.stored}</SelectItem>
                <SelectItem value='largest'>{SORT_LABELS.largest}</SelectItem>
              </SelectContent>
            </Select>
            <span data-tour='library-stats' className='text-muted-foreground inline-flex items-center gap-1 text-sm tabular-nums'>
              <DigitSwap value={totals.count} />
              <span>{totals.count === 1 ? 'image' : 'images'} ·</span>
              <span>{formatBytes(totals.bytes)}</span>
              {totals.unknownBytes > 0 && <span>({totals.unknownBytes} without a size)</span>}
            </span>
          </div>
        </div>

        {visible.length === 0 ? (
          <Empty className='border py-10'>
            <EmptyHeader>
              <EmptyTitle>
                {normalizedQuery
                  ? `No image matches “${normalizedQuery}”`
                  : filter === 'unused'
                    ? 'Every image is used in a post'
                    : 'No image is used in a post yet'}
              </EmptyTitle>
              <EmptyDescription>
                {normalizedQuery ? 'Search matches the start of a hash, or dimensions such as 1080x1350.' : 'Switch to All to see every image.'}
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button
                variant='ghost'
                size='sm'
                onClick={() => {
                  if (normalizedQuery) setQuery('');
                  else setFilter('all');
                }}
              >
                {normalizedQuery ? 'Clear search' : 'Show all'}
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <div role='list' aria-label='Images' className='grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-6'>
            <AnimatePresence>
              {visible.map((asset, index) => (
                <AssetCard
                  key={asset.id}
                  asset={asset}
                  uses={library.usesOf(asset.id)}
                  publishing={library.isPublishing(asset.id)}
                  delay={revealed || reduce ? 0 : Math.min(index, STAGGER_CAP) * STAGGER}
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

        <div className='text-muted-foreground flex flex-col gap-1 text-xs'>
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

        {creatorOnly && (
          <Alert>
            <Icons.info aria-hidden />
            <AlertTitle>Uploads and deletes work only for the workspace creator right now</AlertTitle>
            <AlertDescription>
              The server checks whether you created this workspace instead of checking your edit permission, so it refuses image uploads and
              deletes from other members until that is fixed.
            </AlertDescription>
          </Alert>
        )}

        {storageMissing ? (
          <Alert variant='destructive'>
            <Icons.alertCircle aria-hidden />
            <AlertTitle>Private media storage is not configured for this deployment</AlertTitle>
            <AlertDescription>
              {uploadStorageMissing && upload.blocker ? upload.blocker.message : 'Image previews could not load for this reason.'} Images
              cannot be uploaded, previewed or deleted until it is.
            </AlertDescription>
          </Alert>
        ) : upload.blocker ? (
          <Alert variant='destructive'>
            <Icons.alertCircle aria-hidden />
            <AlertTitle>
              {upload.blocker.status === 503 ? 'Uploads stopped because the workspace was unavailable' : 'The workspace refused the upload'}
            </AlertTitle>
            <AlertDescription>
              {upload.blocker.message}
              {upload.blocker.status === 503 ? ' Files that were not sent can be uploaded again.' : ''}
            </AlertDescription>
          </Alert>
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
                'bg-background/85 pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed text-sm font-medium',
                isDragReject ? 'border-destructive text-destructive' : 'border-primary text-foreground'
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
        <AlertDialogContent>
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
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction
              variant='destructive'
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
