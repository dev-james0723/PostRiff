'use client';

import { Fragment, useEffect, useRef, type ReactNode } from 'react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, useInView, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger
} from '@/components/motion/context-menu';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { EASE_OUT } from '@/lib/ease';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { AssetUse, LibraryAsset } from './use-library';
import { kindOf } from '@/lib/media/asset-kinds';
import { AssetFileThumbnail, documentPreviewSuffix } from './asset-thumbnail';
import { GalleryMediaPreview } from './gallery-media-preview';
import { SelectToggle } from './intelligence/select-toggle';
import { Control, IconControl } from './ui/controls';

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

/**
 * One status at most on a card (UI spec §3; redesign §5), in the order that matters: a file still being prepared or
 * needing attention, then a publishing post, then real use. "Unused" and "Stored privately" are the defaults (every item is
 * private; usage is a filter) and are not shown; the details keep the processing state.
 */
/** A document the server could not read: the file is stored, its text and page preview are not available yet. */
export const FAILED_STATUS = 'Couldn’t read this file';

export function cardStatus(asset: LibraryAsset, count = 0, publishing = false): string | null {
  const kind = kindOf(asset);
  const processing = asset.processing ?? '';
  if (kind !== 'image' && kind !== 'video') {
    if (['pending', 'queued', 'processing'].includes(processing)) return 'Processing';
    if (processing === 'failed') return FAILED_STATUS;
  }
  if (publishing) return 'Publishing';
  if (count > 0) return `Used in ${count} ${count === 1 ? 'post' : 'posts'}`;
  return null;
}

/** The one metadata line: type, then size or duration (never both diagnostic fields and tags). */
export function cardMeta(asset: LibraryAsset): string {
  const kind = kindOf(asset);
  const extension = (asset.extension || asset.originalFilename?.split('.').pop() || '').toUpperCase();
  const type = kind === 'document' || kind === 'file' ? extension || kindLabel(asset) : kindLabel(asset);
  const duration = (kind === 'audio' || kind === 'video') && typeof asset.duration === 'number' && asset.duration > 0 ? formatDuration(asset.duration) : null;
  const dims = kind === 'image' ? dimensionsOf(asset) : null;
  const size = typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null;
  return [type, duration ?? dims ?? size].filter(Boolean).join(' · ');
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
  /** Exclude this item from the smart collection being viewed (an override, undoable from the collection). */
  onExclude?: () => void;
  /** This item is open in the inspector. */
  inspected?: boolean;
  /** Search context under the caption: why it matched, passages and moments (outside the open button). */
  footer?: ReactNode;
}

export type AssetCardActionProps = Pick<AssetCardProps, 'asset' | 'canEdit' | 'canApprove' | 'deleting' | 'publishing' | 'onOpen' | 'onDelete' | 'onExclude' | 'selected' | 'onSelect'>;

interface CardAction {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
  separated?: boolean;
}

/** The item's actions, in one order for the context menu and the More menu: common first, Delete last and apart. */
export function useCardActions({ asset, canEdit, canApprove, deleting, publishing, onOpen, onDelete, onExclude, selected = false, onSelect }: AssetCardActionProps): CardAction[] {
  const router = useRouter();
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const mediaAsset = kindOf(asset) === 'image' || kindOf(asset) === 'video';
  async function retry() {
    try {
      await api.retryLibraryFile(workspaceId, asset.id);
      toast.success('Reading the file again');
    } catch (error) {
      toast.error('Couldn’t retry this file', { description: error instanceof Error ? error.message : undefined });
    } finally {
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
    }
  }
  const actions: CardAction[] = [{ key: 'open', label: 'Open', icon: <Icons.eye aria-hidden />, onSelect: onOpen }];
  if (canEdit && !mediaAsset && asset.processing === 'failed') actions.push({ key: 'retry', label: 'Try reading again', icon: <Icons.refresh aria-hidden />, onSelect: () => void retry() });
  if (onSelect) actions.push({ key: 'select', label: selected ? 'Deselect' : 'Select', icon: <Icons.check aria-hidden />, onSelect: () => onSelect(!selected, false) });
  if (canApprove && mediaAsset) actions.push({ key: 'post', label: 'Use in a post', icon: <Icons.send aria-hidden />, onSelect: () => router.push(`/app/queue?asset=${encodeURIComponent(asset.id)}`) });
  else if (canEdit) actions.push({ key: 'ideas', label: 'Open Ideas', icon: <Icons.sparkles aria-hidden />, onSelect: () => router.push('/app/ideas') });
  if (onExclude) actions.push({ key: 'exclude', label: 'Exclude from this collection', icon: <Icons.minus aria-hidden />, onSelect: onExclude });
  actions.push({ key: 'hash', label: 'Copy hash', icon: <Icons.copy aria-hidden />, onSelect: () => void copyHash(asset.hash) });
  if (canEdit) actions.push({ key: 'delete', label: 'Delete…', icon: <Icons.trash aria-hidden />, onSelect: onDelete, destructive: true, disabled: deleting || publishing, separated: true });
  return actions;
}

export function AssetContextItems({ actions }: { actions: CardAction[] }) {
  return (
    <>
      {actions.map((action) => (
        <Fragment key={action.key}>
          {action.separated ? <ContextMenuSeparator /> : null}
          <ContextMenuItem tone={action.destructive ? 'destructive' : 'default'} disabled={action.disabled} onSelect={action.onSelect}>
            <span className={cn('size-4 [&_svg]:size-4', !action.destructive && 'text-muted-foreground')}>{action.icon}</span>
            {action.label}
          </ContextMenuItem>
        </Fragment>
      ))}
    </>
  );
}

/** The visible More button: the same actions as the context menu, reachable by touch and keyboard (never hover-only). */
export function AssetMoreMenu({ title, actions, className }: { title: string; actions: CardAction[]; className?: string }) {
  return (
    <DropdownMenu>
      {/* Small frosted glass over any picture; the invisible ::after keeps a full finger-sized target. */}
      <DropdownMenuTrigger render={<IconControl label={`More actions for ${title}`} size='sm' tooltip={false} className={cn("bg-background/40 hover:bg-background/65 data-[popup-open]:bg-background/70 text-foreground relative size-6 rounded-full shadow-none ring-1 ring-white/15 backdrop-blur-md backdrop-saturate-150 after:absolute after:-inset-2.5 after:content-[''] pointer-coarse:size-7", className)} />}>
        <Icons.moreHorizontal aria-hidden className='size-3.5' />
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='rafii-elevated min-w-48 rounded-[var(--rafii-radius-card)] p-1'>
        {actions.map((action) => (
          <Fragment key={action.key}>
            {action.separated ? <DropdownMenuSeparator /> : null}
            <DropdownMenuItem variant={action.destructive ? 'destructive' : 'default'} disabled={action.disabled} className='min-h-9 gap-2.5 px-2.5 pointer-coarse:min-h-11' onClick={action.onSelect}>
              <span className={cn('size-4 [&_svg]:size-4', !action.destructive && 'text-muted-foreground')}>{action.icon}</span>
              {action.label}
            </DropdownMenuItem>
          </Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The quiet single status line under a title. */
export function CardStatusLine({ status, publishing }: { status: string | null; publishing: boolean }) {
  if (!status) return null;
  const attention = status === FAILED_STATUS;
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1 text-xs', attention ? 'text-destructive' : 'text-muted-foreground')}>
      {publishing || status === 'Processing' ? <Icons.spinner aria-hidden className='size-3 animate-spin motion-reduce:animate-none' /> : attention ? <Icons.warning aria-hidden className='size-3' /> : status.startsWith('Used') ? <Icons.check aria-hidden className='size-3' /> : null}
      <span className='truncate'>{status}</span>
    </span>
  );
}

/**
 * Gallery card anatomy (UI spec §3; redesign §5): the real preview on a neutral tile — whole, never cropped for photos
 * and video — then a one-line title, one metadata line and at most one status. Selection top-left, More top-right.
 * Broken media says so instead of rendering a blank.
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
  onExclude,
  inspected = false,
  footer
}: AssetCardProps) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  // Thumbnails are the stored renditions (up to 4096 px), so a card fetches only once it is near the viewport.
  const nearView = useInView(ref, { once: true, margin: '240px 0px' });
  const assetKind = kindOf(asset);
  const mediaAsset = assetKind === 'image' || assetKind === 'video';
  const inlineMedia = assetKind === 'audio' || assetKind === 'video';
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
  const status = cardStatus(asset, count, publishing);
  const label = `${kindWord} ${itemTitle}${dims ? `, ${dims}` : ''}${previewLabel}, ${count === 0 ? 'not used in a post yet' : `used in ${count} ${count === 1 ? 'post' : 'posts'}`}${status && !status.startsWith('Used') ? `, ${status.toLowerCase()}` : ''}`;
  const compact = density === 'compact';
  const actions = useCardActions({ asset, canEdit, canApprove, deleting, publishing, onOpen, onDelete, onExclude, selected, onSelect });

  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <motion.div
          ref={ref}
          role='listitem'
          data-tour={first ? 'library-card' : undefined}
          data-library-item={asset.id}
          data-inspected={inspected || undefined}
          aria-busy={deleting || undefined}
          initial={reduce ? false : { opacity: 0 }}
          animate={{ opacity: deleting ? 0.55 : 1, transition: { duration: reduce ? 0 : 0.18, ease: EASE_OUT } }}
          exit={{ opacity: 0, transition: { duration: reduce ? 0 : 0.12, ease: EASE_OUT } }}
          style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 280px' }}
          className={cn(
            'group/asset bg-card text-card-foreground relative flex min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-card)] ring-1 transition-shadow duration-150',
            selected ? 'ring-foreground ring-2' : inspected ? 'ring-foreground/45 ring-2' : 'ring-foreground/[0.08] hover:ring-foreground/[0.16]'
          )}
        >
          {inlineMedia ? <GalleryMediaPreview key={asset.id} asset={asset} video={assetKind === 'video'} posterUrl={image.data} enabled={nearView} /> : null}
          <button
            type='button'
            // In selection mode a tap toggles the item (as in Photos); Open stays in the More menu.
            onClick={selecting && onSelect ? () => onSelect(!selected, false) : onOpen}
            aria-pressed={selecting && onSelect ? selected : undefined}
            aria-label={label}
            data-library-open={asset.id}
            className='focus-visible:ring-ring/50 flex min-w-0 flex-col text-left outline-none focus-visible:ring-3 focus-visible:ring-inset'
          >
            {!inlineMedia ? (
              !mediaAsset ? (
                <AssetFileThumbnail asset={asset} size='gallery' loadPreview={nearView} />
              ) : image.data ? (
                <div data-library-thumbnail='image' data-thumbnail-preview='image' className='bg-foreground/[0.035] relative'>
                  {/* Letterboxed, not cropped: the whole picture in its own proportions. */}
                  <Image src={image.data} alt='' width={asset.width ?? 400} height={asset.height ?? 400} unoptimized loading='lazy' className='aspect-[4/3] w-full object-contain' />
                </div>
              ) : image.isError ? (
                <div className={cn('bg-foreground/[0.035] text-muted-foreground flex aspect-[4/3] w-full flex-col items-center justify-center gap-1 p-2 text-center text-xs', image.canRetry && 'pb-12')}>
                  <Icons.media className='size-5' aria-hidden />
                  Preview unavailable
                </div>
              ) : (
                <Skeleton className='aspect-[4/3] w-full rounded-none' />
              )
            ) : null}
            <span className={cn('flex min-w-0 flex-col items-start gap-0.5 px-3 pt-2.5 pb-3', compact && 'px-2.5 pt-2 pb-2.5')}>
              <span className='w-full truncate text-sm font-medium' title={itemTitle}>
                {itemTitle}
              </span>
              {!compact ? <span className='text-muted-foreground w-full truncate text-xs tabular-nums'>{cardMeta(asset)}</span> : null}
              <CardStatusLine status={status} publishing={publishing} />
            </span>
          </button>
          {footer ? <div className='flex min-w-0 flex-col gap-1.5 px-3 pb-3'>{footer}</div> : null}
          {onSelect ? <SelectToggle title={itemTitle} checked={selected} visible={selecting} onChange={onSelect} className='top-2 left-2' /> : null}
          <div className={cn('absolute top-2 right-2 z-20 transition-opacity duration-150', 'opacity-0 group-hover/asset:opacity-100 group-focus-within/asset:opacity-100 has-[[data-popup-open]]:opacity-100 pointer-coarse:opacity-100', selecting && 'opacity-100')}>
            <AssetMoreMenu title={itemTitle} actions={actions} />
          </div>
          {image.canRetry && !inlineMedia && (
            // Outside the open button (a button cannot hold another), laid over the image area.
            <div className='pointer-events-none absolute inset-x-0 top-0 flex aspect-[4/3] items-end justify-center pb-3'>
              <Control tone='secondary' size='sm' className='pointer-events-auto' aria-label='Retry loading this preview' disabled={image.isFetching} icon={<Icons.refresh className={cn(image.isFetching && 'animate-spin')} aria-hidden />} onClick={() => void image.refetch()}>
                Retry
              </Control>
            </div>
          )}
          {deleting && (
            <span className='bg-background/90 absolute top-2 right-12 grid size-8 place-items-center rounded-full' aria-hidden>
              <Icons.spinner className='size-3.5 animate-spin motion-reduce:animate-none' />
            </span>
          )}
        </motion.div>
      </ContextMenuTrigger>
      <ContextMenuContent ariaLabel={`${kindWord} actions`}>
        <AssetContextItems actions={actions} />
      </ContextMenuContent>
    </ContextMenu>
  );
}
