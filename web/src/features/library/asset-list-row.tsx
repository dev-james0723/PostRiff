'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { motion, useInView, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger
} from '@/components/motion/context-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { kindOf } from '@/lib/media/asset-kinds';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import type { AssetUse, LibraryAsset } from './use-library';
import { assetTitle, badgeClass, cardStatus, copyHash, dimensionsOf, formatDuration, kindLabel, useAssetImage, usageLabel, type LibraryDensity } from './asset-card';
import { AssetFileThumbnail, documentPreviewSuffix } from './asset-thumbnail';
import { GalleryMediaPreview } from './gallery-media-preview';
import { SelectToggle } from './intelligence/select-toggle';

export interface AssetListRowProps {
  asset: LibraryAsset;
  uses: AssetUse[];
  publishing: boolean;
  first: boolean;
  canEdit: boolean;
  canApprove: boolean;
  deleting: boolean;
  onOpen: () => void;
  onDelete: () => void;
  onStorageMissing?: () => void;
  onPreviewLoaded?: () => void;
  selected?: boolean;
  selecting?: boolean;
  onSelect?: (selected: boolean, extend: boolean) => void;
  density?: LibraryDensity;
  onExclude?: () => void;
  footer?: ReactNode;
}

export function libraryAssetTitle(asset: LibraryAsset) {
  return assetTitle(asset);
}

export function AssetListRow({
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
  footer
}: AssetListRowProps) {
  const reduce = useReducedMotion();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const nearView = useInView(ref, { once: true, margin: '240px 0px' });
  const assetKind = kindOf(asset);
  const mediaAsset = assetKind === 'image' || assetKind === 'video';
  const preview = useAssetImage(asset.id, nearView && mediaAsset);
  const video = assetKind === 'video';
  const title = assetTitle(asset);
  const dims = dimensionsOf(asset);
  const count = uses.length;
  const kindWord = kindLabel(asset);
  const status = cardStatus(asset);
  const compact = density === 'compact';

  useEffect(() => {
    if (preview.storageNotConfigured) onStorageMissing?.();
  }, [preview.storageNotConfigured, onStorageMissing]);
  useEffect(() => {
    if (preview.data) onPreviewLoaded?.();
  }, [preview.data, onPreviewLoaded]);

  const meta = [
    (video || assetKind === 'audio') && typeof asset.duration === 'number' && asset.duration > 0 ? formatDuration(asset.duration) : null,
    dims,
    typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null,
    asset.mime || null
  ].filter(Boolean).join(' · ');

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
          initial={reduce ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: deleting ? 0.55 : 1, y: 0, transition: { duration: reduce ? 0 : 0.2, ease: EASE_OUT } }}
          exit={reduce ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, y: -4, transition: { duration: 0.15, ease: EASE_OUT } }}
          transition={{ layout: SPRING_LAYOUT }}
          className={cn(
            'group/asset bg-card text-card-foreground relative overflow-hidden rounded-[var(--rafii-radius-card)] shadow-[var(--rafii-shadow-glass)]',
            selected && 'ring-foreground ring-2 ring-inset'
          )}
        >
          <button
            type='button'
            onClick={onOpen}
            data-library-open={asset.id}
            aria-label={`${kindWord} ${title}${video ? ', video thumbnail' : documentPreviewSuffix(asset)}, ${count ? `used in ${count} ${count === 1 ? 'post' : 'posts'}` : 'not used yet'}${status ? `, ${status.toLowerCase()}` : ''}`}
            className={cn(
              'focus-visible:ring-ring/50 flex w-full min-w-0 items-center gap-3 py-2.5 pr-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset',
              onSelect ? 'pl-14' : 'pl-3',
              compact ? 'min-h-14 py-1.5' : 'min-h-[76px]'
            )}
          >
            <span
              data-library-thumbnail={video ? 'video' : assetKind === 'image' ? 'image' : undefined}
              data-thumbnail-preview={video ? 'video-poster' : assetKind === 'image' ? 'image' : undefined}
              className={cn('rafii-quiet relative flex shrink-0 items-center justify-center overflow-hidden rounded-[var(--rafii-radius-control)]', compact ? 'size-10' : 'size-14')}
            >
              {!mediaAsset ? (
                <AssetFileThumbnail asset={asset} size='row' loadPreview={nearView} />
              ) : preview.data ? (
                <Image src={preview.data} alt='' fill unoptimized sizes='56px' className='object-contain' />
              ) : preview.isError ? (
                video ? <Icons.video className='text-muted-foreground size-5' aria-hidden /> : <Icons.media className='text-muted-foreground size-5' aria-hidden />
              ) : (
                <Skeleton className='size-full rounded-none' />
              )}
              {video ? <Icons.play className='rafii-glass absolute size-5 rounded-full p-1' aria-hidden /> : null}
            </span>
            <span className='flex min-w-0 flex-1 flex-col gap-1'>
              <span className='truncate text-sm font-medium'>{title}</span>
              {status ? <span className='text-muted-foreground text-xs'>{status}</span> : null}
              {!compact && asset.aiSummary ? <span className='text-muted-foreground line-clamp-1 text-xs'>{asset.aiSummary}</span> : null}
              {!compact ? <span className='text-muted-foreground truncate text-xs tabular-nums'>{meta || 'Metadata not recorded'}</span> : null}
            </span>
            <AnimatedBadge
              size='sm'
              status={publishing ? 'loading' : 'neutral'}
              showIcon={count > 0}
              icon={publishing || count === 0 ? undefined : <Icons.check className='size-3' />}
              className={cn('shrink-0', badgeClass(publishing ? 'loading' : 'neutral'), count === 0 && !publishing && 'text-muted-foreground dark:text-muted-foreground')}
            >
              {publishing ? 'Publishing' : usageLabel(count)}
            </AnimatedBadge>
          </button>
          {assetKind === 'audio' || video ? <div className={cn('pr-3 pb-3', onSelect ? 'pl-14' : 'pl-3')}><GalleryMediaPreview key={asset.id} asset={asset} video={video} posterUrl={preview.data} compact enabled={nearView} /></div> : null}
          {footer ? <div className={cn('flex min-w-0 flex-col gap-1.5 pr-3 pb-2.5', onSelect ? 'pl-14' : 'pl-3')}>{footer}</div> : null}
          {onSelect ? <SelectToggle title={title} checked={selected} visible={selecting} onChange={onSelect} className={cn('left-1.5', compact ? 'top-1.5' : 'top-4')} /> : null}
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
        {onExclude ? (
          <ContextMenuItem onSelect={onExclude}>
            <Icons.minus className='text-muted-foreground size-4' aria-hidden />
            Exclude from this collection
          </ContextMenuItem>
        ) : null}
        <ContextMenuItem onSelect={() => void copyHash(asset.hash)}>
          <Icons.copy className='text-muted-foreground size-4' aria-hidden />
          Copy hash
        </ContextMenuItem>
        {canEdit ? (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem tone='destructive' disabled={deleting || publishing} onSelect={onDelete}>
              <Icons.trash className='size-4' aria-hidden />
              Delete…
            </ContextMenuItem>
          </>
        ) : null}
      </ContextMenuContent>
    </ContextMenu>
  );
}
