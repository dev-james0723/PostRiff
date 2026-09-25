'use client';

import { useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { useInView } from 'motion/react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import type { Asset } from '@/lib/api/types';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/**
 * Choose a Library image by its thumbnail instead of its hash. The thumbnails use the Library's query key
 * (`['media', workspaceId, assetId]`, also used by the post previews), so an image already seen elsewhere is not
 * downloaded again. `value` is an asset id, or '' for no image.
 */

function describe(asset: Asset) {
  return [asset.width && asset.height ? `${asset.width}×${asset.height}` : null, typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null]
    .filter(Boolean)
    .join(' · ');
}

function Thumb({ asset, className }: { asset: Asset; className?: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const ref = useRef<HTMLSpanElement>(null);
  const nearView = useInView(ref, { once: true, margin: '120px 0px' });
  const image = useQuery({
    queryKey: ['media', workspaceId, asset.id],
    queryFn: async () => URL.createObjectURL(await api.media(workspaceId, asset.id)),
    staleTime: Infinity,
    retry: 1,
    enabled: nearView && Boolean(workspaceId)
  });
  return (
    <span ref={ref} className={cn('rafii-quiet relative block overflow-hidden', className)}>
      {image.data ? (
        <Image src={image.data} alt='' width={160} height={160} unoptimized className='size-full object-cover' />
      ) : image.isError ? (
        <span className='text-muted-foreground grid size-full place-items-center' title='Preview unavailable'>
          <Icons.media className='size-4' aria-hidden />
        </span>
      ) : (
        <Skeleton className='size-full rounded-none' />
      )}
    </span>
  );
}

export interface AssetPickerProps {
  /** Library assets; deleted ones are left out. */
  assets: Asset[];
  value: string;
  onValueChange: (assetId: string) => void;
  id?: string;
  disabled?: boolean;
  className?: string;
  'aria-label'?: string;
  /** Label for the empty choice. */
  noneLabel?: string;
}

/** A tile's selected state sits in a predictable corner, outside the image's meaningful content (DNA §21.9). */
function SelectedMark() {
  return (
    <span aria-hidden className='bg-foreground text-background absolute top-1.5 right-1.5 grid size-5 place-items-center rounded-full'>
      <Icons.check className='size-3' />
    </span>
  );
}

export function AssetPicker({ assets, value, onValueChange, id, disabled, className, noneLabel = 'No image', ...props }: AssetPickerProps) {
  const [open, setOpen] = useState(false);
  const live = assets.filter((asset) => !asset.deleted);
  const selected = live.find((asset) => asset.id === value) ?? null;

  function choose(assetId: string) {
    onValueChange(assetId);
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        id={id}
        disabled={disabled}
        aria-label={props['aria-label']}
        render={<Button variant='glass' size='control' className={cn('w-full min-w-0 justify-start gap-2.5 px-3', className)} />}
      >
        {selected ? (
          <>
            <Thumb asset={selected} className='size-8 shrink-0 rounded-[var(--rafii-radius-micro)]' />
            <span className='min-w-0 flex-1 truncate text-left'>{describe(selected) || 'Image'}</span>
            <code className='text-muted-foreground hidden font-mono text-xs sm:inline'>{selected.hash.slice(0, 8)}</code>
          </>
        ) : (
          <>
            <span className='rafii-quiet text-muted-foreground grid size-8 shrink-0 place-items-center rounded-[var(--rafii-radius-micro)]'>
              <Icons.media className='size-4' aria-hidden />
            </span>
            <span className='text-muted-foreground min-w-0 flex-1 truncate text-left'>{noneLabel}</span>
          </>
        )}
        <Icons.chevronDown className='text-muted-foreground size-4 shrink-0' aria-hidden />
      </PopoverTrigger>
      <PopoverContent align='start' className='rafii-elevated w-[min(22rem,calc(100vw-1.5rem))] gap-3 rounded-[1.375rem] p-4 ring-0'>
        <PopoverHeader>
          <PopoverTitle>Choose an image</PopoverTitle>
          <PopoverDescription>
            {live.length === 0 ? 'No images yet' : `${live.length} ${live.length === 1 ? 'image' : 'images'}`}
          </PopoverDescription>
        </PopoverHeader>
        <div className='-mx-1 grid max-h-72 grid-cols-3 gap-2 overflow-y-auto px-1 py-1'>
          <button
            type='button'
            aria-pressed={value === ''}
            onClick={() => choose('')}
            className={cn(
              'rafii-focus text-muted-foreground relative flex aspect-square flex-col items-center justify-center gap-1 rounded-[var(--rafii-radius-control)] text-xs transition-colors',
              value === '' ? 'rafii-glass-selected text-foreground' : 'rafii-quiet hover:text-foreground'
            )}
          >
            <Icons.circleX className='size-4' aria-hidden />
            {noneLabel}
            {value === '' && <SelectedMark />}
          </button>
          {live.map((asset) => {
            const active = asset.id === value;
            const details = describe(asset);
            return (
              <button
                key={asset.id}
                type='button'
                aria-pressed={active}
                aria-label={`Image${details ? ` ${details}` : ''}, hash starts with ${asset.hash.slice(0, 8)}`}
                title={details || undefined}
                onClick={() => choose(asset.id)}
                className={cn(
                  'rafii-focus relative aspect-square overflow-hidden rounded-[var(--rafii-radius-control)]',
                  active && 'ring-foreground ring-offset-background ring-2 ring-offset-2'
                )}
              >
                <Thumb asset={asset} className='size-full' />
                {active && <SelectedMark />}
              </button>
            );
          })}
        </div>
        {live.length === 0 && (
          <Link href='/app/library' className='rafii-focus text-foreground inline-flex min-h-9 w-fit items-center rounded-md text-xs underline underline-offset-4'>
            Upload images in the Library
          </Link>
        )}
      </PopoverContent>
    </Popover>
  );
}
