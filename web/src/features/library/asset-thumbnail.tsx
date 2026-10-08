'use client';

import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { Asset } from '@/lib/api/types';
import { kindOf } from '@/lib/media/asset-kinds';
import { documentCoverLabel, peaksToBars } from '@/lib/library/wording';

export type AssetThumbnailSize = 'gallery' | 'row' | 'detail';

const SIZE_CLASS: Record<AssetThumbnailSize, string> = {
  gallery: 'aspect-square w-full',
  row: 'size-14 shrink-0',
  detail: 'mx-auto aspect-[3/4] max-h-[50vh] w-full max-w-sm'
};

const PENDING = ['pending', 'queued', 'processing'];

function extensionOf(asset: Asset) {
  return (asset.extension || asset.originalFilename?.split('.').pop() || 'file').toLowerCase();
}

function clip(text: string) {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > 240 ? `${flat.slice(0, 237).trimEnd()}…` : flat;
}

/** What the cover shows, and where it came from: the file's own extracted text, or an AI summary said as such. */
function previewText(asset: Asset) {
  const extracted = clip(asset.extractedText || '');
  if (extracted) return { text: extracted, source: 'extracted' as const };
  const summary = clip(asset.aiSummary || '');
  return summary ? { text: summary, source: 'summary' as const } : { text: '', source: 'none' as const };
}

export function isPdfAsset(asset: Asset) {
  return kindOf(asset) === 'document' && extensionOf(asset) === 'pdf';
}

/**
 * The phrase a card's accessible name uses for its preview. A PDF's cover is a real render of page 1 once the file is
 * processed; every other document cover is built from extracted text and says so (A016).
 */
export function documentPreviewSuffix(asset: Asset) {
  if (kindOf(asset) !== 'document') return '';
  if (isPdfAsset(asset) && !PENDING.includes(asset.processing || '')) return ', first-page preview';
  const preview = previewText(asset);
  if (preview.source === 'extracted') return ', extracted text preview';
  if (preview.source === 'summary') return ', AI summary preview';
  return `, ${extensionOf(asset).toUpperCase()} file`;
}

/**
 * An extracted-text cover. It is labelled as extracted text: it is not a picture of the document's first page, slide
 * or sheet, so it never claims to be one. No decorative grids or fake text lines.
 */
function DocumentCover({ asset, size }: { asset: Asset; size: AssetThumbnailSize }) {
  const extension = extensionOf(asset);
  const preview = previewText(asset);
  const markdown = extension === 'md' || extension === 'markdown';
  const spreadsheet = ['csv', 'xls', 'xlsx', 'ods'].includes(extension);
  const label = documentCoverLabel({ extension, hasExtractedText: preview.source === 'extracted', hasSummary: preview.source === 'summary', genuineRendition: false });
  const Icon = spreadsheet ? Icons.fileTypeXls : ['doc', 'docx', 'odt', 'rtf'].includes(extension) ? Icons.fileTypeDoc : markdown ? Icons.code : extension === 'pdf' ? Icons.fileTypePdf : Icons.page;

  return (
    <div
      aria-hidden='true'
      data-library-thumbnail={extension}
      data-thumbnail-preview={preview.source === 'extracted' ? 'extracted-text' : preview.source === 'summary' ? 'ai-summary' : 'format-cover'}
      className={cn('rafii-quiet relative flex items-center justify-center overflow-hidden p-3', SIZE_CLASS[size])}
    >
      <div
        className={cn(
          'rafii-elevated relative flex h-[88%] w-[80%] min-w-0 flex-col overflow-hidden rounded-[var(--rafii-radius-control)] p-3 shadow-sm',
          size === 'row' && 'h-[84%] w-[80%] rounded-[5px] p-1.5',
          size === 'detail' && 'p-5'
        )}
      >
        <div className='mb-2 flex min-w-0 items-center gap-1.5'>
          <Icon className={cn('text-muted-foreground size-4 shrink-0', size === 'row' && 'size-3')} aria-hidden />
          <span className={cn('text-muted-foreground truncate text-[9px] font-semibold tracking-[0.06em] uppercase', size === 'row' && 'hidden', size === 'detail' && 'text-[11px]')}>{label}</span>
        </div>
        {preview.text ? (
          <p
            className={cn(
              'text-foreground/75 line-clamp-6 overflow-hidden text-[9px] leading-[1.45]',
              markdown && 'font-mono',
              preview.source === 'summary' && 'italic',
              size === 'row' && 'line-clamp-4 text-[4px] leading-[1.35]',
              size === 'detail' && 'line-clamp-[14] text-xs leading-relaxed'
            )}
          >
            {preview.text}
          </p>
        ) : (
          <div className='text-muted-foreground flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-center'>
            <Icon className={cn('size-6 opacity-70', size === 'row' && 'size-3.5', size === 'detail' && 'size-10')} aria-hidden />
            <span className={cn('text-[9px] leading-tight', size === 'row' && 'hidden', size === 'detail' && 'text-xs')}>
              {PENDING.includes(asset.processing || '') ? 'Preparing preview' : 'No text preview'}
            </span>
          </div>
        )}
      </div>
      {size !== 'row' ? <span className='rafii-glass absolute right-2 bottom-2 rounded-full px-2 py-1 text-[9px] font-medium'>{markdown ? 'MARKDOWN' : extension.toUpperCase()}</span> : null}
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

/** A real render of the PDF's first page (the browser's own viewer on the private signed file), so it may say so. */
function PdfFirstPage({ asset, size, enabled }: { asset: Asset; size: AssetThumbnailSize; enabled: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const query = useQuery({
    queryKey: ['library-pdf-preview-url', workspaceId, asset.id],
    queryFn: async () => (await api.libraryFileUrl(workspaceId, asset.id)).url,
    enabled: Boolean(workspaceId) && enabled && !PENDING.includes(asset.processing || ''),
    staleTime: 3 * 60_000,
    refetchInterval: enabled ? 4 * 60_000 : false,
    retry: 1
  });

  if (!query.data) return <DocumentCover asset={asset} size={size} />;
  const pageUrl = `${query.data.split('#')[0]}#page=1&view=Fit&toolbar=0&navpanes=0`;
  return (
    <div aria-hidden='true' data-library-thumbnail='pdf' data-thumbnail-preview='first-page' className={cn('rafii-quiet relative overflow-hidden bg-white', SIZE_CLASS[size])}>
      <PrivatePdfFrame pageUrl={pageUrl} />
      {size !== 'row' ? <span className='rafii-glass absolute right-2 bottom-2 rounded-full px-2 py-1 text-[9px] font-medium'>PDF · FIRST PAGE</span> : null}
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
      data-thumbnail-preview={bars ? 'audio-waveform' : 'audio-symbol'}
      className={cn('rafii-quiet relative flex flex-col items-center justify-center gap-3 overflow-hidden p-3', SIZE_CLASS[size], size === 'detail' && 'aspect-[16/7]')}
    >
      {bars ? (
        <div className={cn('flex w-full items-center justify-center gap-[2px]', size === 'row' ? 'h-8' : size === 'detail' ? 'h-24' : 'h-16')}>
          {bars.map((height, index) => (
            <span key={index} className='bg-foreground/60 w-full max-w-[4px] min-w-[1px] rounded-full' style={{ height: `${Math.max(6, Math.round(height * 100))}%` }} />
          ))}
        </div>
      ) : (
        <span className={cn('rafii-elevated relative grid size-12 place-items-center rounded-full', size === 'row' && 'size-7', size === 'detail' && 'size-16')}>
          <Icons.music className={cn('text-muted-foreground size-5', size === 'row' && 'size-3.5', size === 'detail' && 'size-7')} aria-hidden />
        </span>
      )}
      {size !== 'row' ? <span className='rafii-glass absolute right-2 bottom-2 rounded-full px-2 py-1 text-[9px] font-medium'>{extension}</span> : null}
    </div>
  );
}

/** Stored, not understood: filename and type, and nothing that claims to know what is inside. */
function GenericFileCover({ asset, size }: { asset: Asset; size: AssetThumbnailSize }) {
  const extension = extensionOf(asset).toUpperCase();
  return (
    <div aria-hidden='true' data-library-thumbnail={extension.toLowerCase()} data-thumbnail-preview='format-cover' className={cn('rafii-quiet relative flex flex-col items-center justify-center gap-2 overflow-hidden p-3', SIZE_CLASS[size])}>
      <Icons.page className={cn('text-muted-foreground size-8', size === 'row' && 'size-5', size === 'detail' && 'size-12')} aria-hidden />
      <span className={cn('text-foreground text-[10px] font-semibold tracking-[0.12em]', size === 'row' && 'text-[7px]', size === 'detail' && 'text-sm')}>{extension.slice(0, 10)}</span>
      {size !== 'row' ? <span className='text-muted-foreground max-w-full truncate px-2 text-[9px]'>{asset.originalFilename || asset.mime || 'Private file'}</span> : null}
    </div>
  );
}

/** At-a-glance private preview surfaces shared by the gallery, list, and detail panel. */
export function AssetFileThumbnail({ asset, size = 'gallery', loadPreview = true, peaks }: { asset: Asset; size?: AssetThumbnailSize; loadPreview?: boolean; peaks?: readonly number[] | null }) {
  const kind = kindOf(asset);
  if (kind === 'audio') return <AudioCover asset={asset} size={size} peaks={peaks} />;
  if (kind === 'document' && extensionOf(asset) === 'pdf') return <PdfFirstPage asset={asset} size={size} enabled={loadPreview} />;
  if (kind === 'document') return <DocumentCover asset={asset} size={size} />;
  return <GenericFileCover asset={asset} size={size} />;
}
