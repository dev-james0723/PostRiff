'use client';

import Image from 'next/image';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { PanelButton as Button } from './ui/controls';
import { cn } from '@/lib/utils';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { Asset } from '@/lib/api/types';
import { kindOf } from '@/lib/media/asset-kinds';
import { peaksToBars } from '@/lib/library/wording';

export type AssetThumbnailSize = 'gallery' | 'row' | 'detail';
const SIZE_CLASS: Record<AssetThumbnailSize, string> = {
  gallery: 'aspect-[4/3] w-full',
  row: 'size-14 shrink-0',
  detail: 'mx-auto aspect-[3/4] max-h-[50vh] w-full max-w-sm'
};
const DOCUMENT_FORMATS = new Set(['pdf','docx','xlsx','pptx','doc','xls','ppt','odt','ods','odp','rtf','txt','md','markdown','html','htm','csv','json']);
const PREVIEW_READY = ['ready', 'unsupported'];
const extensionOf = (asset: Asset) => (asset.extension || asset.originalFilename?.split('.').pop() || 'file').toLowerCase();

/**
 * The phrase a card's accessible name uses for its preview, matching what the thumbnail renders (A016): a source-page
 * raster once the file is processed, a preparing state before that, and nothing extra for other kinds.
 */
export function documentPreviewSuffix(asset: Asset) {
  if (!DOCUMENT_FORMATS.has(extensionOf(asset))) return '';
  if (PREVIEW_READY.includes(asset.processing || '')) return ', first-page preview';
  if (asset.processing === 'failed') return `, ${extensionOf(asset).toUpperCase()} file, no preview`;
  return `, ${extensionOf(asset).toUpperCase()} file, preview being prepared`;
}

function FileFallback({ asset, size, preparing = false, failed = false }: { asset: Asset; size: AssetThumbnailSize; preparing?: boolean; failed?: boolean }) {
  return (
    <div data-library-thumbnail={extensionOf(asset)} data-thumbnail-preview={preparing ? 'preparing' : 'unavailable'} className={cn('bg-foreground/[0.035] relative flex flex-col items-center justify-center gap-1.5 overflow-hidden p-2', SIZE_CLASS[size])}>
      <Icons.page className={cn('text-muted-foreground size-6', size === 'row' && 'size-4')} aria-hidden />
      <span className={cn('text-muted-foreground text-center text-xs', size === 'row' && 'sr-only')}>{preparing ? 'Preparing preview' : failed ? 'No preview' : 'Preview unavailable'}</span>
      {size !== 'row' ? <span className='text-muted-foreground text-[10px] font-medium tracking-wide'>{extensionOf(asset).toUpperCase()}</span> : null}
    </div>
  );
}

function DocumentFirstPage({ asset, size, enabled }: { asset: Asset; size: AssetThumbnailSize; enabled: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [imageFailed, setImageFailed] = useState(false);
  const ready = PREVIEW_READY.includes(asset.processing || '');
  // A file the server could not read never gets a page preview: say so instead of "Preparing" forever.
  const failed = asset.processing === 'failed';
  const query = useQuery({
    queryKey: ['library-source-page', workspaceId, asset.id, asset.hash],
    queryFn: async () => {
      const result = await api.libraryPreviewUrl(workspaceId, asset.id);
      setImageFailed(false);
      return result.url;
    },
    enabled: Boolean(workspaceId) && enabled && ready,
    staleTime: 3 * 60_000,
    refetchInterval: enabled && ready ? 4 * 60_000 : false,
    retry: (count, error) => count < (error instanceof ApiError && [409,429].includes(error.status) ? 32 : 1),
    retryDelay: 3000
  });
  if (!query.data || imageFailed) return (
    <div className='relative'>
      <FileFallback asset={asset} size={size} failed={failed} preparing={!failed && (!ready || query.isFetching || !enabled)} />
      {enabled && ready && (query.isError || imageFailed) && size === 'detail' ? (
        <Button variant='outline' size='sm' className='absolute bottom-3 left-1/2 -translate-x-1/2' onClick={() => void query.refetch()}>Retry preview</Button>
      ) : null}
    </div>
  );
  return (
    <div data-library-thumbnail={extensionOf(asset)} data-thumbnail-preview='first-page-raster' className={cn('relative overflow-hidden bg-white', SIZE_CLASS[size])}>
      {/* A tile shows the top of the real page at a legible scale; the detail shows the whole page. */}
      <Image src={query.data} alt={`First page of ${asset.originalFilename || 'document'}`} width={1000} height={1400} unoptimized onError={() => setImageFailed(true)} className={cn('h-full w-full object-top', size === 'detail' ? 'object-contain' : 'object-cover')} />
    </div>
  );
}

/**
 * Audio. With real amplitude peaks (the understanding card's `media.peaks`) it draws them; without, a neutral audio
 * symbol that does not look like an analysed timeline. Nothing here is generated from the file's hash or id.
 */
function AudioCover({ asset, size, peaks }: { asset: Asset; size: AssetThumbnailSize; peaks?: readonly number[] | null }) {
  const extension = extensionOf(asset).toUpperCase();
  const bars = peaksToBars(peaks, size === 'row' ? 12 : size === 'detail' ? 64 : 32);
  return (
    <div
      aria-hidden='true'
      data-library-thumbnail={extension.toLowerCase()}
      data-thumbnail-preview={bars ? 'audio-waveform' : 'audio-file'}
      className={cn('bg-foreground/[0.035] relative flex flex-col items-center justify-center gap-3 overflow-hidden p-3', SIZE_CLASS[size], size === 'detail' && 'aspect-[16/7]')}
    >
      {bars ? (
        <div className={cn('flex w-full items-center justify-center gap-[2px]', size === 'row' ? 'h-8' : size === 'detail' ? 'h-24' : 'h-16')}>
          {bars.map((height, index) => (
            <span key={index} className='bg-foreground/60 w-full max-w-[4px] min-w-[1px] rounded-full' style={{ height: `${Math.max(6, Math.round(height * 100))}%` }} />
          ))}
        </div>
      ) : (
        <Icons.music className={cn('text-muted-foreground size-7', size === 'row' && 'size-4', size === 'detail' && 'size-10')} aria-hidden />
      )}
      {size !== 'row' ? <span className='text-muted-foreground text-[10px]'>{extension}</span> : null}
    </div>
  );
}

/** Real source-page JPEGs shared across gallery, list and details; audio draws decoded peaks when it has them. */
export function AssetFileThumbnail({ asset, size = 'gallery', loadPreview = true, peaks }: { asset: Asset; size?: AssetThumbnailSize; loadPreview?: boolean; peaks?: readonly number[] | null }) {
  if (DOCUMENT_FORMATS.has(extensionOf(asset))) return <DocumentFirstPage key={asset.id} asset={asset} size={size} enabled={loadPreview} />;
  if (kindOf(asset) === 'audio') return <AudioCover asset={asset} size={size} peaks={peaks} />;
  return <FileFallback asset={asset} size={size} />;
}
