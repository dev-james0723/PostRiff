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
    <span ref={ref} className={cn('bg-muted relative block overflow-hidden', className)}>
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
        render={<Button variant='outline' className={cn('h-10 w-full min-w-0 justify-start gap-2 px-2', className)} />}
      >
        {selected ? (
          <>
            <Thumb asset={selected} className='size-7 shrink-0 rounded-md' />
            <span className='min-w-0 flex-1 truncate text-left'>{describe(selected) || 'Image'}</span>
            <code className='text-muted-foreground hidden font-mono text-xs sm:inline'>{selected.hash.slice(0, 8)}</code>
          </>
        ) : (
          <>
            <span className='bg-muted text-muted-foreground grid size-7 shrink-0 place-items-center rounded-md'>
              <Icons.media className='size-4' aria-hidden />
            </span>
            <span className='text-muted-foreground min-w-0 flex-1 truncate text-left'>{noneLabel}</span>
          </>
        )}
        <Icons.chevronDown className='text-muted-foreground size-4 shrink-0' aria-hidden />
      </PopoverTrigger>
      <PopoverContent align='start' className='w-[min(22rem,calc(100vw-2rem))]'>
        <PopoverHeader>
          <PopoverTitle>Choose an image</PopoverTitle>
          <PopoverDescription>
            {live.length === 0 ? 'The Library has no images yet.' : `${live.length} ${live.length === 1 ? 'image' : 'images'} in the Library`}
          </PopoverDescription>
        </PopoverHeader>
        <div className='-mx-1 grid max-h-72 grid-cols-3 gap-2 overflow-y-auto px-1 py-1'>
          <button
            type='button'
            aria-pressed={value === ''}
            onClick={() => choose('')}
            className={cn(
              'bg-muted text-muted-foreground focus-visible:ring-ring/50 flex aspect-square flex-col items-center justify-center gap-1 rounded-md border text-xs outline-none focus-visible:ring-3',
              value === '' && 'ring-primary ring-2'
            )}
          >
            <Icons.circleX className='size-4' aria-hidden />
            {noneLabel}
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
                  'focus-visible:ring-ring/50 relative aspect-square overflow-hidden rounded-md border outline-none focus-visible:ring-3',
                  active && 'ring-primary ring-2'
                )}
              >
                <Thumb asset={asset} className='size-full' />
                {active && (
                  <span className='bg-primary text-primary-foreground absolute top-1 right-1 grid size-4 place-items-center rounded-full'>
                    <Icons.check className='size-3' aria-hidden />
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {live.length === 0 && (
          <Link href='/app/library' className='text-primary text-xs underline-offset-4 hover:underline'>
            Upload images in the Library
          </Link>
        )}
      </PopoverContent>
    </Popover>
  );
}
