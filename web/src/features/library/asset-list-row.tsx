'use client';

import { useEffect, useRef } from 'react';
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
import { badgeClass, copyHash, dimensionsOf, formatDuration, useAssetImage, usageLabel } from './asset-card';
import { AssetFileThumbnail } from './asset-thumbnail';

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
}

export function libraryAssetTitle(asset: LibraryAsset) {
  const kind = kindOf(asset);
  return asset.displayTitle?.trim() || asset.originalFilename?.trim() || (kind === 'video' ? 'Video' : kind === 'audio' ? 'Audio' : kind === 'document' ? 'Document' : kind === 'file' ? 'File' : 'Photo');
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
  onPreviewLoaded
}: AssetListRowProps) {
  const reduce = useReducedMotion();
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const nearView = useInView(ref, { once: true, margin: '240px 0px' });
  const assetKind = kindOf(asset);
  const mediaAsset = assetKind === 'image' || assetKind === 'video';
  const pdfAsset = assetKind === 'document' && (asset.extension?.toLowerCase() === 'pdf' || asset.originalFilename?.toLowerCase().endsWith('.pdf'));
  const preview = useAssetImage(asset.id, nearView && mediaAsset);
  const video = assetKind === 'video';
  const title = libraryAssetTitle(asset);
  const dims = dimensionsOf(asset);
  const count = uses.length;
  const kindLabel = assetKind === 'video' ? 'Video' : assetKind === 'audio' ? 'Audio' : assetKind === 'document' ? 'Document' : assetKind === 'file' ? 'File' : 'Photo';

  useEffect(() => {
    if (preview.storageNotConfigured) onStorageMissing?.();
  }, [preview.storageNotConfigured, onStorageMissing]);
  useEffect(() => {
    if (preview.data) onPreviewLoaded?.();
  }, [preview.data, onPreviewLoaded]);

  const meta = [
    video && typeof asset.duration === 'number' && asset.duration > 0 ? formatDuration(asset.duration) : null,
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
          aria-busy={deleting || undefined}
          layout={reduce ? false : 'position'}
          initial={reduce ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: deleting ? 0.55 : 1, y: 0, transition: { duration: 0.2, ease: EASE_OUT } }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, y: -4, transition: { duration: 0.15, ease: EASE_OUT } }}
          transition={{ layout: SPRING_LAYOUT }}
          className='bg-card text-card-foreground relative overflow-hidden rounded-[var(--rafii-radius-card)] shadow-[var(--rafii-shadow-glass)]'
        >
          <button
            type='button'
            onClick={onOpen}
            aria-label={`${kindLabel} ${title}${video ? ', video thumbnail' : pdfAsset || (assetKind === 'document' && ['doc', 'docx', 'odt', 'rtf'].includes((asset.extension || '').toLowerCase())) ? ', first-page preview' : assetKind === 'document' ? `, ${asset.extension?.toUpperCase() || 'document'} preview` : ''}, ${count ? `used in ${count} ${count === 1 ? 'post' : 'posts'}` : 'not used yet'}`}
            className='focus-visible:ring-ring/50 flex min-h-[76px] w-full min-w-0 items-center gap-3 px-3 py-2.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset'
          >
            <span data-library-thumbnail={video ? 'video' : assetKind === 'image' ? 'image' : undefined} data-thumbnail-preview={video ? 'video-poster' : assetKind === 'image' ? 'image' : undefined} className='rafii-quiet relative flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-[var(--rafii-radius-control)]'>
              {!mediaAsset ? (
                <AssetFileThumbnail asset={asset} size='row' loadPreview={nearView} />
              ) : preview.data ? (
                <Image src={preview.data} alt='' fill unoptimized sizes='56px' className='object-cover' />
              ) : preview.isError ? (
                video ? <Icons.video className='text-muted-foreground size-5' aria-hidden /> : <Icons.media className='text-muted-foreground size-5' aria-hidden />
              ) : (
                <Skeleton className='size-full rounded-none' />
              )}
              {video ? <Icons.play className='rafii-glass absolute size-5 rounded-full p-1' aria-hidden /> : null}
            </span>
            <span className='flex min-w-0 flex-1 flex-col gap-1'>
              <span className='truncate text-sm font-medium'>{title}</span>
              {!mediaAsset ? <span className='text-muted-foreground text-xs'>{asset.processing === 'unsupported' ? 'Stored privately' : (asset.processing ?? 'unknown').replaceAll('_', ' ')}</span> : null}
              {asset.aiSummary ? <span className='text-muted-foreground line-clamp-1 text-xs'>{asset.aiSummary}</span> : null}
              <span className='text-muted-foreground truncate text-xs tabular-nums'>{meta || 'Metadata not recorded'}</span>
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
        </motion.div>
      </ContextMenuTrigger>
      <ContextMenuContent ariaLabel={`${kindLabel} actions`}>
        <ContextMenuItem onSelect={onOpen}>
          <Icons.eye className='text-muted-foreground size-4' aria-hidden />
          Open
        </ContextMenuItem>
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
