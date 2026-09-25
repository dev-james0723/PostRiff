'use client';

import { useEffect, useRef } from 'react';
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

export function dimensionsOf(asset: LibraryAsset) {
  return asset.width && asset.height ? `${asset.width}×${asset.height}` : null;
}

export function usageLabel(count: number) {
  return count === 0 ? 'Unused' : `Used in ${count}`;
}

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
}

/**
 * Gallery card anatomy (DNA §13.2, §21.9): the real image in its own colours on top, quiet neutral
 * metadata below, the usage state as monochrome text. Broken media says so instead of rendering a blank.
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
  onPreviewLoaded
}: AssetCardProps) {
  const reduce = useReducedMotion();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  // Thumbnails are the stored renditions (up to 4096 px), so a card fetches only once it is near the viewport.
  const nearView = useInView(ref, { once: true, margin: '240px 0px' });
  const image = useAssetImage(asset.id, nearView);
  const storageMissing = image.storageNotConfigured;
  const loaded = Boolean(image.data);
  useEffect(() => {
    if (storageMissing) onStorageMissing?.();
  }, [storageMissing, onStorageMissing]);
  useEffect(() => {
    if (loaded) onPreviewLoaded?.();
  }, [loaded, onPreviewLoaded]);
  const dims = dimensionsOf(asset);
  const count = uses.length;
  const label = `Image${dims ? ` ${dims}` : ''}, ${count === 0 ? 'not used in a post yet' : `used in ${count} ${count === 1 ? 'post' : 'posts'}`}`;

  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <motion.div
          ref={ref}
          role='listitem'
          data-tour={first ? 'library-card' : undefined}
          aria-busy={deleting || undefined}
          layout={reduce ? false : 'position'}
          initial={reduce ? false : { opacity: 0, scale: 0.98 }}
          animate={{ opacity: deleting ? 0.55 : 1, scale: 1, transition: { duration: 0.24, ease: EASE_OUT } }}
          exit={reduce ? { opacity: 0, transition: { duration: 0.15 } } : { opacity: 0, scale: 0.96, transition: { duration: 0.2, ease: EASE_OUT } }}
          transition={{ layout: SPRING_LAYOUT }}
          className='bg-card text-card-foreground relative flex min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-card)] shadow-[var(--rafii-shadow-glass)]'
        >
          <button
            type='button'
            onClick={onOpen}
            aria-label={label}
            className='focus-visible:ring-ring/50 flex min-w-0 flex-col rounded-[var(--rafii-radius-card)] text-left outline-none focus-visible:ring-3 focus-visible:ring-inset'
          >
            {/* Only the image tilts; the caption stays still. The card clips the corners. */}
            <TiltCard max={6} className='rounded-none'>
              {image.data ? (
                <Image src={image.data} alt='' width={400} height={400} unoptimized className='aspect-square w-full object-cover' />
              ) : image.isError ? (
                <div
                  className={cn(
                    'rafii-quiet text-muted-foreground flex aspect-square w-full flex-col items-center justify-center gap-1 p-2 text-center text-xs',
                    image.canRetry && 'pb-12'
                  )}
                >
                  <Icons.media className='size-5' aria-hidden />
                  Preview unavailable
                </div>
              ) : (
                <Skeleton className='aspect-square w-full rounded-none' />
              )}
            </TiltCard>
            <span className='flex min-w-0 flex-col items-start gap-1.5 p-2.5'>
              <AnimatedBadge
                size='sm'
                status={publishing ? 'loading' : 'neutral'}
                showIcon={count > 0}
                icon={publishing || count === 0 ? undefined : <Icons.check className='size-3' />}
                className={cn(badgeClass(publishing ? 'loading' : 'neutral'), count === 0 && !publishing && 'text-muted-foreground dark:text-muted-foreground')}
                title={publishing ? 'A post using this image is publishing now' : undefined}
              >
                {usageLabel(count)}
              </AnimatedBadge>
              <span className='text-muted-foreground w-full truncate text-xs tabular-nums'>
                {[dims, typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null].filter(Boolean).join(' · ') || 'Size not recorded'}
              </span>
            </span>
          </button>
          {image.canRetry && (
            // Outside the open button (a button cannot hold another), laid over the square image area.
            <div className='pointer-events-none absolute inset-x-0 top-0 flex aspect-square items-end justify-center pb-3'>
              <Button
                size='lg'
                variant='glass'
                className='pointer-events-auto'
                aria-label='Retry loading this preview'
                disabled={image.isFetching}
                onClick={() => void image.refetch()}
              >
                <Icons.refresh className={cn(image.isFetching && 'animate-spin')} aria-hidden />
                Retry
              </Button>
            </div>
          )}
          {deleting && (
            <span className='rafii-elevated absolute top-2 right-2 grid size-7 place-items-center rounded-full' aria-hidden>
              <Icons.spinner className='size-3.5 animate-spin' />
            </span>
          )}
        </motion.div>
      </ContextMenuTrigger>
      <ContextMenuContent ariaLabel='Image actions'>
        <ContextMenuItem onSelect={onOpen}>
          <Icons.eye className='text-muted-foreground size-4' aria-hidden />
          Open
        </ContextMenuItem>
        {canApprove ? (
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
