'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import Image from 'next/image';
import { motion, useInView, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@/components/motion/context-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { EASE_OUT } from '@/lib/ease';
import { kindOf } from '@/lib/media/asset-kinds';
import { cn } from '@/lib/utils';
import type { AssetUse, LibraryAsset } from './use-library';
import { AssetContextItems, AssetMoreMenu, CardStatusLine, assetTitle, cardMeta, cardStatus, dimensionsOf, kindLabel, useAssetImage, useCardActions, type LibraryDensity } from './asset-card';
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
  inspected?: boolean;
  footer?: ReactNode;
}

export function libraryAssetTitle(asset: LibraryAsset) {
  return assetTitle(asset);
}

/**
 * The list form of the same card (redesign §5): preview, title, one metadata line, one status, More — the parts and
 * actions are shared with the gallery card, so the two views never disagree. Audio and video keep a slim inline player
 * under the row.
 */
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
  inspected = false,
  footer
}: AssetListRowProps) {
  const reduce = useReducedMotion();
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
  const status = cardStatus(asset, count, publishing);
  const compact = density === 'compact';
  const actions = useCardActions({ asset, canEdit, canApprove, deleting, publishing, onOpen, onDelete, onExclude, selected, onSelect });

  useEffect(() => {
    if (preview.storageNotConfigured) onStorageMissing?.();
  }, [preview.storageNotConfigured, onStorageMissing]);
  useEffect(() => {
    if (preview.data) onPreviewLoaded?.();
  }, [preview.data, onPreviewLoaded]);

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
          className={cn(
            'group/asset bg-card text-card-foreground relative overflow-hidden rounded-[var(--rafii-radius-card)] ring-1 transition-shadow duration-150',
            selected ? 'ring-foreground ring-2' : inspected ? 'ring-foreground/45 ring-2' : 'ring-foreground/[0.08] hover:ring-foreground/[0.16]'
          )}
        >
          <button
            type='button'
            onClick={onOpen}
            data-library-open={asset.id}
            aria-label={`${kindWord} ${title}${video ? ', video thumbnail' : documentPreviewSuffix(asset)}, ${count ? `used in ${count} ${count === 1 ? 'post' : 'posts'}` : 'not used yet'}${status && !status.startsWith('Used') ? `, ${status.toLowerCase()}` : ''}`}
            className={cn(
              'focus-visible:ring-ring/50 flex w-full min-w-0 items-center gap-3 pr-12 pl-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset',
              compact ? 'min-h-12 py-1.5' : 'min-h-16 py-2'
            )}
          >
            <span
              data-library-thumbnail={video ? 'video' : assetKind === 'image' ? 'image' : undefined}
              data-thumbnail-preview={video ? 'video-poster' : assetKind === 'image' ? 'image' : undefined}
              className={cn('bg-foreground/[0.035] relative flex shrink-0 items-center justify-center overflow-hidden rounded-[var(--rafii-radius-control)]', compact ? 'size-9' : 'size-12')}
            >
              {!mediaAsset ? (
                <AssetFileThumbnail asset={asset} size='row' loadPreview={nearView} />
              ) : preview.data ? (
                <Image src={preview.data} alt='' fill unoptimized sizes='48px' className='object-contain' />
              ) : preview.isError ? (
                video ? <Icons.video className='text-muted-foreground size-5' aria-hidden /> : <Icons.media className='text-muted-foreground size-5' aria-hidden />
              ) : (
                <Skeleton className='size-full rounded-none' />
              )}
              {video ? <Icons.play className='bg-background/85 absolute size-5 rounded-full p-1' aria-hidden /> : null}
            </span>
            <span className='flex min-w-0 flex-1 flex-col gap-0.5'>
              <span className='truncate text-sm font-medium' title={title}>
                {title}
              </span>
              {!compact ? <span className='text-muted-foreground truncate text-xs tabular-nums'>{[cardMeta(asset), dims && assetKind === 'video' ? dims : null].filter(Boolean).join(' · ')}</span> : null}
            </span>
            <span className='hidden shrink-0 sm:block'>
              <CardStatusLine status={status} publishing={publishing} />
            </span>
          </button>
          {assetKind === 'audio' || video ? <div className='px-3 pb-2'><GalleryMediaPreview key={asset.id} asset={asset} video={video} posterUrl={preview.data} compact enabled={nearView} /></div> : null}
          {footer ? <div className='flex min-w-0 flex-col gap-1.5 px-3 pb-2.5'>{footer}</div> : null}
          {/* Over the thumbnail's corner, so the row keeps no empty gutter for it. */}
          {onSelect ? <SelectToggle title={title} checked={selected} visible={selecting} onChange={onSelect} className={cn('left-1.5', compact ? 'top-1' : 'top-1.5')} /> : null}
          <div className={cn('absolute right-2 z-20 transition-opacity duration-150', compact ? 'top-2' : 'top-4', 'opacity-0 group-hover/asset:opacity-100 group-focus-within/asset:opacity-100 has-[[data-popup-open]]:opacity-100 pointer-coarse:opacity-100', selecting && 'opacity-100')}>
            <AssetMoreMenu title={title} actions={actions} />
          </div>
        </motion.div>
      </ContextMenuTrigger>
      <ContextMenuContent ariaLabel={`${kindWord} actions`}>
        <AssetContextItems actions={actions} />
      </ContextMenuContent>
    </ContextMenu>
  );
}
