'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { motion, useInView, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger
} from '@/components/motion/context-menu';
import { TiltCard } from '@/components/motion/tilt-card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { AssetUse, LibraryAsset } from './use-library';
import { kindOf } from '@/lib/media/asset-kinds';
import { AssetFileThumbnail, documentPreviewSuffix, isPdfAsset } from './asset-thumbnail';
import { SelectToggle } from './intelligence/select-toggle';

/**
 * The server's own wording when the deployment has no private media storage (`hosted.py` upload_media,
 * delete_media and media). Any other 503, such as "Private storage is temporarily unavailable."
 * (`hosted_storage.py`) or a gateway or restart, is temporary and says nothing about configuration.
 */
const STORAGE_NOT_CONFIGURED = /media storage is not configured|media uploads aren.t available/i;

export function saysStorageNotConfigured(failure: { status: number; message: string; code?: string } | null | undefined) {
  return failure?.status === 503 && (failure.code === 'media_storage_not_configured' || (!failure.code && STORAGE_NOT_CONFIGURED.test(failure.message)));
}

/**
 * The status badge without its coloured chip (DNA §4.3): a quiet monochrome capsule whose words carry the state.
 * A warning or failure keeps its tint but loses the outline. The badge's icon-and-text roll stays.
 */
export function badgeClass(status: AnimatedBadgeStatus) {
  return status === 'warning' || status === 'danger' ? 'border-transparent' : 'border-transparent bg-foreground/[0.06] text-foreground dark:text-foreground';
}

/**
 * The private image bytes as an object URL. The key is shared with the post previews
 * (`components/application/post-preview/use-preview-post.ts`) and the asset picker, so an image is fetched
 * once per session wherever it appears.
 */
export function useAssetImage(assetId: string, enabled = true) {
  const { api, workspaceId } = useWorkspaceApi();
  const query = useQuery({
    queryKey: ['media', workspaceId, assetId],
    queryFn: async () => URL.createObjectURL(await api.media(workspaceId, assetId)),
    staleTime: Infinity,
    // A missing object, or a deployment without media storage, answers the same way straight away; anything else gets one more try.
    retry: (count, error) =>
      count < 1 && !(error instanceof ApiError && (error.status === 404 || saysStorageNotConfigured(error))),
    enabled: enabled && Boolean(workspaceId)
  });
  const failure = query.error instanceof ApiError ? query.error : null;
  return {
    ...query,
    errorStatus: failure?.status ?? null,
    /** The server said this deployment has no private media storage (not just any 503). */
    storageNotConfigured: saysStorageNotConfigured(failure),
    // Only a 404 is final: the bytes are gone. A 503 can pass once storage is reachable or configured again.
    canRetry: query.isError && failure?.status !== 404
  };
}

export async function copyHash(hash: string) {
  try {
    await navigator.clipboard.writeText(hash);
    toast.success('Copied');
  } catch {
    toast.error('Couldn’t copy');
  }
}

/** 42.4 → "0:42"; 125 → "2:05". */
export function formatDuration(seconds: number) {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export function dimensionsOf(asset: LibraryAsset) {
  return asset.width && asset.height ? `${asset.width}×${asset.height}` : null;
}

export function usageLabel(count: number) {
  return count === 0 ? 'Unused' : `Used in ${count}`;
}

export function kindLabel(asset: LibraryAsset) {
  const kind = kindOf(asset);
  return kind === 'video' ? 'Video' : kind === 'audio' ? 'Audio' : kind === 'document' ? 'Document' : kind === 'file' ? 'File' : 'Photo';
}

export function assetTitle(asset: LibraryAsset) {
  return asset.displayTitle?.trim() || asset.originalFilename?.trim() || kindLabel(asset);
}

/** One status at most on a card (UI spec §3): processing beats usage while a file is still being prepared. */
export function cardStatus(asset: LibraryAsset): string | null {
  const kind = kindOf(asset);
  if (kind === 'image' || kind === 'video') return null;
  const processing = asset.processing ?? '';
  if (['pending', 'queued', 'processing'].includes(processing)) return 'Being indexed';
  if (processing === 'failed') return 'Indexing failed';
  if (processing === 'unsupported') return 'Stored privately';
  return null;
}

export type LibraryDensity = 'comfortable' | 'compact';

interface AssetCardProps {
  asset: LibraryAsset;
  uses: AssetUse[];
  publishing: boolean;
  first: boolean;
  canEdit: boolean;
  /** Preparing a post (`p2_review`) needs approve permission, so only approvers are sent to the Queue. */
  canApprove: boolean;
  deleting: boolean;
  onOpen: () => void;
  onDelete: () => void;
  /** Called when the preview request says private media storage is not configured (that 503 message, not any 503). */
  onStorageMissing?: () => void;
  /** Called when the preview loads, which shows storage works and clears an earlier "not configured" alert. */
  onPreviewLoaded?: () => void;
  selected?: boolean;
  /** Something is selected: every card shows its checkbox. */
  selecting?: boolean;
  onSelect?: (selected: boolean, extend: boolean) => void;
  density?: LibraryDensity;
  /** Search context under the caption: why it matched, passages and moments (outside the open button). */
  footer?: ReactNode;
}

/**
 * Gallery card anatomy (DNA §13.2, §21.9; UI spec §3): the real preview in its own colours on top — whole, never
 * cropped — then a readable title, concise metadata and at most one status. Broken media says so instead of
 * rendering a blank.
 */
export function AssetCard({
  asset,
  uses,
  publishing,
  first,
  canEdit,
  canApprove,
  deleting,
  onOpen,
  onDelete,
  onStorageMissing,
  onPreviewLoaded,
  selected = false,
  selecting = false,
  onSelect,
  density = 'comfortable',
  footer
}: AssetCardProps) {
  const reduce = useReducedMotion();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  // Thumbnails are the stored renditions (up to 4096 px), so a card fetches only once it is near the viewport.
  const nearView = useInView(ref, { once: true, margin: '240px 0px' });
  const assetKind = kindOf(asset);
  const mediaAsset = assetKind === 'image' || assetKind === 'video';
  const pdfAsset = isPdfAsset(asset);
  const image = useAssetImage(asset.id, nearView && mediaAsset);
  const storageMissing = mediaAsset && image.storageNotConfigured;
  const loaded = Boolean(image.data);
  useEffect(() => {
    if (storageMissing) onStorageMissing?.();
  }, [storageMissing, onStorageMissing]);
  useEffect(() => {
    if (loaded) onPreviewLoaded?.();
  }, [loaded, onPreviewLoaded]);
  const dims = dimensionsOf(asset);
  const count = uses.length;
  const itemTitle = assetTitle(asset);
  const kindWord = kindLabel(asset);
  const previewLabel = assetKind === 'video' ? ', video thumbnail' : documentPreviewSuffix(asset);
  const status = cardStatus(asset);
  const label = `${kindWord} ${itemTitle}${dims ? `, ${dims}` : ''}${previewLabel}, ${count === 0 ? 'not used in a post yet' : `used in ${count} ${count === 1 ? 'post' : 'posts'}`}${status ? `, ${status.toLowerCase()}` : ''}`;
  const compact = density === 'compact';

  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <motion.div
          ref={ref}
          role='listitem'
          data-tour={first ? 'library-card' : undefined}
          data-library-item={asset.id}
          aria-busy={deleting || undefined}
          layout={reduce ? false : 'position'}
          initial={reduce ? false : { opacity: 0, scale: 0.98 }}
          animate={{ opacity: deleting ? 0.55 : 1, scale: 1, transition: { duration: reduce ? 0 : 0.24, ease: EASE_OUT } }}
          exit={reduce ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, scale: 0.96, transition: { duration: 0.2, ease: EASE_OUT } }}
          transition={{ layout: SPRING_LAYOUT }}
          className={cn(
            'group/asset bg-card text-card-foreground relative flex min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-card)] shadow-[var(--rafii-shadow-glass)]',
            selected && 'ring-foreground ring-offset-background ring-2 ring-offset-2'
          )}
        >
          <button
            type='button'
            onClick={onOpen}
            aria-label={label}
            data-library-open={asset.id}
            className='focus-visible:ring-ring/50 flex min-w-0 flex-col rounded-[var(--rafii-radius-card)] text-left outline-none focus-visible:ring-3 focus-visible:ring-inset'
          >
            {/* Only the preview tilts; the caption stays still. The card clips the corners. */}
            <TiltCard max={6} className='rounded-none'>
              {!mediaAsset ? (
                <AssetFileThumbnail asset={asset} size='gallery' loadPreview={false} />
              ) : image.data ? (
                <div data-library-thumbnail={assetKind === 'video' ? 'video' : 'image'} data-thumbnail-preview={assetKind === 'video' ? 'video-poster' : 'image'} className='rafii-quiet relative'>
                  {/* Letterboxed, not cropped: the whole picture in its own proportions. */}
                  <Image src={image.data} alt='' width={asset.width ?? 400} height={asset.height ?? 400} unoptimized loading='lazy' className='aspect-square w-full object-contain' />
                  {kindOf(asset) === 'video' && (
                    <span className='bg-background/85 text-foreground absolute right-1.5 bottom-1.5 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular-nums'>
                      <Icons.play aria-hidden className='size-3' />
                      {typeof asset.duration === 'number' && asset.duration > 0 ? formatDuration(asset.duration) : 'Video'}
                    </span>
                  )}
                </div>
              ) : image.isError ? (
                <div className={cn('rafii-quiet text-muted-foreground flex aspect-square w-full flex-col items-center justify-center gap-1 p-2 text-center text-xs', image.canRetry && 'pb-12')}>
                  <Icons.media className='size-5' aria-hidden />
                  Preview unavailable
                </div>
              ) : (
                <Skeleton className='aspect-square w-full rounded-none' />
              )}
            </TiltCard>
            <span className={cn('flex min-w-0 flex-col items-start gap-1.5 p-2.5', compact && 'gap-1 p-2')}>
              <span className='w-full truncate text-sm font-medium'>{itemTitle}</span>
              {status ? (
                <span className='text-muted-foreground text-xs'>{status}</span>
              ) : (
                <AnimatedBadge
                  size='sm'
                  status={publishing ? 'loading' : 'neutral'}
                  showIcon={count > 0}
                  icon={publishing || count === 0 ? undefined : <Icons.check className='size-3' />}
                  className={cn(badgeClass(publishing ? 'loading' : 'neutral'), count === 0 && !publishing && 'text-muted-foreground dark:text-muted-foreground', compact && 'hidden sm:inline-flex')}
                  title={publishing ? 'A post using this asset is publishing now' : undefined}
                >
                  {usageLabel(count)}
                </AnimatedBadge>
              )}
              {!compact ? (
                <span className='text-muted-foreground w-full truncate text-xs tabular-nums'>
                  {[assetKind === 'audio' && typeof asset.duration === 'number' && asset.duration > 0 ? formatDuration(asset.duration) : null, dims, typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null].filter(Boolean).join(' · ') || 'Size not recorded'}
                </span>
              ) : null}
            </span>
          </button>
          {footer ? <div className='flex min-w-0 flex-col gap-1.5 px-2.5 pb-2.5'>{footer}</div> : null}
          {pdfAsset && nearView ? (
            <div className='pointer-events-none absolute inset-x-0 top-0 z-10 aspect-square overflow-hidden rounded-t-[var(--rafii-radius-card)]'>
              <AssetFileThumbnail asset={asset} size='gallery' loadPreview />
            </div>
          ) : null}
          {onSelect ? <SelectToggle title={itemTitle} checked={selected} visible={selecting} onChange={onSelect} className='top-1.5 left-1.5' /> : null}
          {image.canRetry && (
            // Outside the open button (a button cannot hold another), laid over the square image area.
            <div className='pointer-events-none absolute inset-x-0 top-0 flex aspect-square items-end justify-center pb-3'>
              <Button size='lg' variant='glass' className='pointer-events-auto' aria-label='Retry loading this preview' disabled={image.isFetching} onClick={() => void image.refetch()}>
                <Icons.refresh className={cn(image.isFetching && 'animate-spin')} aria-hidden />
                Retry
              </Button>
            </div>
          )}
          {deleting && (
            <span className='rafii-elevated absolute top-2 right-2 grid size-7 place-items-center rounded-full' aria-hidden>
              <Icons.spinner className='size-3.5 animate-spin motion-reduce:animate-none' />
            </span>
          )}
        </motion.div>
      </ContextMenuTrigger>
      <ContextMenuContent ariaLabel={`${kindWord} actions`}>
        <ContextMenuItem onSelect={onOpen}>
          <Icons.eye className='text-muted-foreground size-4' aria-hidden />
          Open
        </ContextMenuItem>
        {onSelect ? (
          <ContextMenuItem onSelect={() => onSelect(!selected, false)}>
            <Icons.check className='text-muted-foreground size-4' aria-hidden />
            {selected ? 'Deselect' : 'Select'}
          </ContextMenuItem>
        ) : null}
        {canApprove && mediaAsset ? (
          <ContextMenuItem onSelect={() => router.push(`/app/queue?asset=${encodeURIComponent(asset.id)}`)}>
            <Icons.send className='text-muted-foreground size-4' aria-hidden />
            Use in a post
          </ContextMenuItem>
        ) : canEdit ? (
          <ContextMenuItem onSelect={() => router.push('/app/ideas')}>
            <Icons.sparkles className='text-muted-foreground size-4' aria-hidden />
            Open Ideas
          </ContextMenuItem>
        ) : null}
        <ContextMenuItem onSelect={() => void copyHash(asset.hash)}>
          <Icons.copy className='text-muted-foreground size-4' aria-hidden />
          Copy hash
        </ContextMenuItem>
        {canEdit && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem tone='destructive' disabled={deleting || publishing} onSelect={onDelete}>
              <Icons.trash className='size-4' aria-hidden />
              Delete…
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}
