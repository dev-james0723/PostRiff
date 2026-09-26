'use client';

/**
 * The Library view inside the ＋ sheet (chat-context SPEC §4.2, §11.6): staged multi-select, then "Add {n}". Only ready
 * photos and videos are offered; video tiles show the poster and the length. Selection respects what the message can
 * still take (4 photos and videos, one video), so Add never adds something the composer would refuse.
 */
import { useMemo, useState } from 'react';

import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii/state-message';
import { Button } from '@/components/ui/button';
import type { Asset } from '@/lib/api/types';
import { isLibraryAsset, isReady, kindOf } from '@/lib/media/asset-kinds';
import { cn } from '@/lib/utils';
import { formatDuration, useAssetImage } from '@/features/library/asset-card';

function Tile({
  asset,
  selected,
  disabled,
  onToggle
}: {
  asset: Asset;
  selected: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const image = useAssetImage(asset.id);
  const video = kindOf(asset) === 'video';
  return (
    <button
      type='button'
      aria-pressed={selected}
      aria-label={`${video ? 'Video' : 'Photo'}${video && asset.duration ? `, ${formatDuration(asset.duration)}` : ''}`}
      disabled={disabled && !selected}
      onClick={onToggle}
      className={cn(
        'rafii-focus bg-foreground/[0.04] relative aspect-square overflow-hidden rounded-lg disabled:opacity-40',
        selected && 'ring-foreground ring-2 ring-offset-2 ring-offset-[var(--background)]'
      )}
    >
      {image.data ? (
        // A private object URL from the media route (the poster for a video); next/image cannot optimise it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={image.data} alt='' className='size-full object-cover' />
      ) : (
        <span aria-hidden className='flex size-full items-center justify-center'>
          {video ? (
            <Icons.video className='text-muted-foreground size-6' />
          ) : (
            <Icons.media className='text-muted-foreground size-6' />
          )}
        </span>
      )}
      {video && asset.duration ? (
        <span className='bg-background/80 text-foreground absolute right-1.5 bottom-1.5 rounded-full px-1.5 py-0.5 text-[11px] tabular-nums'>
          {formatDuration(asset.duration)}
        </span>
      ) : null}
      {selected ? (
        <span
          aria-hidden
          className='bg-foreground text-background absolute top-1.5 right-1.5 flex size-5 items-center justify-center rounded-full'
        >
          <Icons.check className='size-3.5' />
        </span>
      ) : null}
    </button>
  );
}

export interface LibraryGridProps {
  assets: readonly Asset[] | undefined;
  /** How many photos and videos the message can still take, and whether it already has a video. */
  room: number;
  hasVideo: boolean;
  onAdd: (assets: Asset[]) => void;
  onUpload: () => void;
}

export function LibraryGrid({ assets, room, hasVideo, onAdd, onUpload }: LibraryGridProps) {
  const ready = useMemo(
    () =>
      [...(assets ?? [])].filter((asset) => isLibraryAsset(asset) && isReady(asset)).toReversed(),
    [assets]
  );
  const [picked, setPicked] = useState<string[]>([]);
  const chosen = ready.filter((asset) => picked.includes(asset.id));
  const videoChosen = hasVideo || chosen.some((asset) => kindOf(asset) === 'video');

  if (!ready.length) {
    return (
      <StateMessage
        kind='empty'
        title='No photos or videos yet.'
        action={
          <Button variant='outline' onClick={onUpload}>
            Upload
          </Button>
        }
      />
    );
  }

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-3'>
      <div className='grid min-h-0 grid-cols-3 gap-2 overflow-y-auto p-1 sm:grid-cols-4'>
        {ready.map((asset) => {
          const selected = picked.includes(asset.id);
          const full = chosen.length >= room || (kindOf(asset) === 'video' && videoChosen);
          return (
            <Tile
              key={asset.id}
              asset={asset}
              selected={selected}
              disabled={full}
              onToggle={() =>
                setPicked((current) =>
                  selected ? current.filter((id) => id !== asset.id) : [...current, asset.id]
                )
              }
            />
          );
        })}
      </div>
      <Button className='self-end' disabled={!chosen.length} onClick={() => onAdd(chosen)}>
        {chosen.length ? `Add ${chosen.length}` : 'Add'}
      </Button>
    </div>
  );
}
