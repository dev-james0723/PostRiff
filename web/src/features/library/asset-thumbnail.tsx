'use client';

import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { Asset } from '@/lib/api/types';
import { kindOf } from '@/lib/media/asset-kinds';

export type AssetThumbnailSize = 'gallery' | 'row' | 'detail';

const SIZE_CLASS: Record<AssetThumbnailSize, string> = {
  gallery: 'aspect-square w-full',
  row: 'size-14 shrink-0',
  detail: 'mx-auto aspect-[3/4] max-h-[50vh] w-full max-w-sm'
};

function extensionOf(asset: Asset) {
  return (asset.extension || asset.originalFilename?.split('.').pop() || 'file').toLowerCase();
}

function previewText(asset: Asset) {
  const text = (asset.extractedText || asset.aiSummary || '').replace(/\s+/g, ' ').trim();
  return text.length > 240 ? `${text.slice(0, 237).trimEnd()}…` : text;
}

function DocumentCover({ asset, size }: { asset: Asset; size: AssetThumbnailSize }) {
  const extension = extensionOf(asset);
  const summary = previewText(asset);
  const markdown = extension === 'md' || extension === 'markdown';
  const spreadsheet = ['csv', 'xls', 'xlsx', 'ods'].includes(extension);
  const presentation = ['ppt', 'pptx', 'odp'].includes(extension);
  const label = extension === 'pdf' ? 'PDF · FIRST PAGE' :
    ['doc', 'docx', 'odt', 'rtf'].includes(extension) ? 'DOCUMENT · OPENING CONTENT' :
      spreadsheet ? 'SHEET PREVIEW' : presentation ? 'SLIDE PREVIEW' : markdown ? 'MARKDOWN' :
        ['txt', 'text'].includes(extension) ? 'TEXT PREVIEW' : `${extension.toUpperCase()} FILE`;
  const Icon = spreadsheet ? Icons.fileTypeXls :
    ['doc', 'docx', 'odt', 'rtf'].includes(extension) ? Icons.fileTypeDoc :
      markdown ? Icons.code : extension === 'pdf' ? Icons.fileTypePdf : Icons.page;

  return (
    <div aria-hidden='true' data-library-thumbnail={extension} data-thumbnail-preview={summary ? 'opening-content' : 'format-cover'} className={cn('rafii-quiet relative flex items-center justify-center overflow-hidden p-3', SIZE_CLASS[size])}>
      {spreadsheet ? (
        <div className='absolute inset-0 grid grid-cols-4 grid-rows-5 opacity-40' aria-hidden>
          {Array.from({ length: 20 }, (_, index) => <span key={index} className='border-foreground/15 border-r border-b' />)}
        </div>
      ) : null}
      {presentation ? <div className='absolute inset-3 rounded-lg bg-gradient-to-br from-violet-500/15 via-sky-400/10 to-transparent' aria-hidden /> : null}
      <div className={cn(
        'rafii-elevated relative flex h-[88%] w-[76%] min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-control)] p-3 shadow-sm',
        size === 'row' && 'h-[84%] w-[78%] rounded-[5px] p-1.5',
        size === 'detail' && 'p-5'
      )}>
        <div className='mb-2 flex min-w-0 items-center justify-between gap-1'>
          <Icon className={cn('text-muted-foreground size-4 shrink-0', size === 'row' && 'size-3')} aria-hidden />
          <span className={cn('text-muted-foreground truncate text-[8px] font-semibold tracking-[0.12em]', size === 'row' && 'text-[5px]', size === 'detail' && 'text-[10px]')}>
            {label}
          </span>
        </div>
        {summary ? (
          <p className={cn(
            'text-foreground/75 line-clamp-5 overflow-hidden text-[8px] leading-[1.45]',
            markdown && 'font-mono',
            size === 'row' && 'line-clamp-4 text-[4px] leading-[1.35]',
            size === 'detail' && 'line-clamp-[14] text-xs leading-relaxed'
          )}>
            {summary}
          </p>
        ) : (
          <div className='text-muted-foreground flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-center'>
            <Icon className={cn('size-6 opacity-70', size === 'row' && 'size-3.5', size === 'detail' && 'size-10')} aria-hidden />
            <span className={cn('text-[8px] leading-tight', size === 'row' && 'text-[5px]', size === 'detail' && 'text-xs')}>
              {['pending', 'queued', 'processing'].includes(asset.processing || '') ? 'Preparing preview' : 'Private workspace file'}
            </span>
          </div>
        )}
        <div className={cn('mt-auto flex flex-col gap-1 pt-2', size === 'row' && 'gap-0.5 pt-1')}>
          {[0, 1, 2].map((line) => <span key={line} className={cn('bg-foreground/10 h-px w-full', line === 2 && 'w-2/3')} />)}
        </div>
      </div>
      {size !== 'row' ? (
        <span className='rafii-glass absolute right-2 bottom-2 rounded-full px-2 py-1 text-[9px] font-medium'>
          {extension.toUpperCase()}
        </span>
      ) : null}
    </div>
  );
}

/* oxlint-disable react/iframe-missing-sandbox -- The signed PDF is on private storage's separate origin; Chrome's viewer needs scripts and its own origin storage, while access to Rafii remains cross-origin. */
function PrivatePdfFrame({ pageUrl }: { pageUrl: string }) {
  return (
    <iframe
      title='First page PDF thumbnail'
      src={pageUrl}
      tabIndex={-1}
      loading='lazy'
      referrerPolicy='no-referrer'
      sandbox='allow-scripts allow-same-origin'
      className='pointer-events-none absolute inset-0 h-full w-full border-0 bg-white'
    />
  );
}
/* oxlint-enable react/iframe-missing-sandbox */

function PdfFirstPage({ asset, size, enabled }: { asset: Asset; size: AssetThumbnailSize; enabled: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const query = useQuery({
    queryKey: ['library-pdf-preview-url', workspaceId, asset.id],
    queryFn: async () => (await api.libraryFileUrl(workspaceId, asset.id)).url,
    enabled: Boolean(workspaceId) && enabled && !['pending', 'queued', 'processing'].includes(asset.processing || ''),
    staleTime: 3 * 60_000,
    refetchInterval: enabled ? 4 * 60_000 : false,
    retry: 1
  });

  if (!query.data) return <DocumentCover asset={asset} size={size} />;
  const pageUrl = `${query.data.split('#')[0]}#page=1&view=Fit&toolbar=0&navpanes=0`;
  return (
    <div aria-hidden='true' data-library-thumbnail='pdf' data-thumbnail-preview='first-page' className={cn('rafii-quiet relative overflow-hidden bg-white', SIZE_CLASS[size])}>
      <PrivatePdfFrame pageUrl={pageUrl} />
      <span className='rafii-glass absolute right-2 bottom-2 rounded-full px-2 py-1 text-[9px] font-medium'>PDF · PAGE 1</span>
    </div>
  );
}

function AudioCover({ asset, size }: { asset: Asset; size: AssetThumbnailSize }) {
  const extension = extensionOf(asset).toUpperCase();
  const seed = (asset.hash || asset.id || extension).split('').reduce((total, character) => total + character.charCodeAt(0), 0);
  return (
    <div aria-hidden='true' data-library-thumbnail={extension.toLowerCase()} data-thumbnail-preview='audio-cover' className={cn('rafii-quiet relative flex flex-col items-center justify-center gap-3 overflow-hidden p-3', SIZE_CLASS[size])}>
      <div className='rafii-glass absolute inset-x-0 top-1/2 h-px' />
      <div className='relative flex h-12 items-center gap-1' aria-hidden>
        {Array.from({ length: size === 'row' ? 9 : 17 }, (_, index) => {
          const height = 10 + ((seed + index * 17) % 32);
          return <span key={index} className='bg-foreground/55 w-[3px] rounded-full' style={{ height }} />;
        })}
      </div>
      <span className={cn('rafii-elevated relative grid size-9 place-items-center rounded-full', size === 'row' && 'size-6')}>
        <Icons.music className={cn('text-muted-foreground size-4', size === 'row' && 'size-3')} aria-hidden />
      </span>
      {size !== 'row' ? <span className='rafii-glass absolute right-2 bottom-2 rounded-full px-2 py-1 text-[9px] font-medium'>{extension}</span> : null}
    </div>
  );
}

function GenericFileCover({ asset, size }: { asset: Asset; size: AssetThumbnailSize }) {
  const extension = extensionOf(asset).toUpperCase();
  return (
    <div aria-hidden='true' data-library-thumbnail={extension.toLowerCase()} data-thumbnail-preview='format-cover' className={cn('rafii-quiet relative flex flex-col items-center justify-center gap-2 overflow-hidden p-3', SIZE_CLASS[size])}>
      <Icons.page className={cn('text-muted-foreground size-8', size === 'row' && 'size-5', size === 'detail' && 'size-12')} aria-hidden />
      <span className={cn('text-foreground text-[10px] font-semibold tracking-[0.12em]', size === 'row' && 'text-[7px]', size === 'detail' && 'text-sm')}>
        {extension.slice(0, 10)}
      </span>
      <span className='text-muted-foreground text-[9px]'>{asset.mime || 'Private file'}</span>
    </div>
  );
}

/** At-a-glance private preview surfaces shared by the gallery, list, and detail panel. */
export function AssetFileThumbnail({ asset, size = 'gallery', loadPreview = true }: { asset: Asset; size?: AssetThumbnailSize; loadPreview?: boolean }) {
  const kind = kindOf(asset);
  if (kind === 'audio') return <AudioCover asset={asset} size={size} />;
  if (kind === 'document' && extensionOf(asset) === 'pdf') return <PdfFirstPage asset={asset} size={size} enabled={loadPreview} />;
  if (kind === 'document') return <DocumentCover asset={asset} size={size} />;
  return <GenericFileCover asset={asset} size={size} />;
}
