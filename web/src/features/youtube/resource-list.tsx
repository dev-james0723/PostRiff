'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import type { YouTubeData, YouTubeResource } from '@/lib/youtube/types';
import { cn } from '@/lib/utils';
import { youtubeThumbnailUrls } from './resource-thumbnails';

type ResourceType = 'video' | 'playlist';

function Thumbnail({ urls, resourceType }: { urls: string[]; resourceType: ResourceType }) {
  const [index, setIndex] = useState(0);
  const src = urls[index];
  const Icon = resourceType === 'playlist' ? Icons.folder : Icons.video;

  return (
    <span
      aria-hidden='true'
      data-youtube-thumbnail={src ? 'image' : 'fallback'}
      className='bg-muted relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-md'
    >
      {src ? (
        // Keep the provider's native image and URL; no image proxy or guessed YouTube URL.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={src}
          src={src}
          alt=''
          width={320}
          height={180}
          loading='lazy'
          decoding='async'
          referrerPolicy='no-referrer'
          className='absolute inset-0 size-full object-contain'
          onError={() => setIndex(index + 1)}
        />
      ) : (
        <span className='text-muted-foreground flex flex-col items-center gap-1 px-1 text-center text-[10px]'>
          <Icon className='size-5' />
          <span>No thumbnail</span>
        </span>
      )}
    </span>
  );
}

export function YouTubeResourceList({
  data,
  resourceType,
  select,
  isSelected,
  getIdentifier,
  disabled = false
}: {
  data?: YouTubeData;
  resourceType: ResourceType;
  select: (item: YouTubeResource) => void;
  /** The caller owns canonical IDs and decides which resource is selected. */
  isSelected?: (item: YouTubeResource) => boolean;
  /** Resolve the displayed/actionable ID; an unavailable ID disables the row. */
  getIdentifier?: (item: YouTubeResource) => string | undefined;
  disabled?: boolean;
}) {
  return (
    <ul
      aria-label={resourceType === 'playlist' ? 'Playlists and podcasts' : 'Videos and Shorts'}
      data-youtube-resource-list={resourceType}
      className='grid min-w-0 gap-2'
    >
      {data?.items?.map((item) => {
        const urls = youtubeThumbnailUrls(item);
        const identifier = getIdentifier ? getIdentifier(item) : item.id;
        const selected = Boolean(identifier) && isSelected?.(item) === true;
        const title = item.snippet?.title?.trim() || item.id;
        // Shorts share the video resource; thumbnail shape is not a format classification.
        const typeLabel = resourceType === 'playlist'
          ? item.status?.podcastStatus === 'enabled' ? 'Podcast' : 'Playlist'
          : 'Video';

        return (
          <li key={item.id} className='min-w-0'>
            <button
              type='button'
              aria-pressed={selected}
              disabled={disabled || !identifier}
              data-youtube-resource-id={item.id}
              data-youtube-selection-id={identifier}
              onClick={() => select(item)}
              className={cn(
                'rafii-focus grid w-full min-w-0 grid-cols-[6rem_minmax(0,1fr)] items-start gap-3 rounded-md border p-2.5 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 sm:grid-cols-[7rem_minmax(0,1fr)]',
                selected ? 'border-primary bg-muted/60' : 'hover:bg-muted'
              )}
            >
              <Thumbnail key={JSON.stringify(urls)} urls={urls} resourceType={resourceType} />
              <span className='grid min-w-0 gap-1'>
                <span className='line-clamp-2 font-medium leading-5 [overflow-wrap:anywhere]'>
                  {title}
                </span>
                <span className='flex flex-wrap items-center gap-x-2 gap-y-1 text-xs'>
                  <span className='text-muted-foreground'>{typeLabel}</span>
                  {item.status?.privacyStatus && (
                    <span className='text-muted-foreground capitalize'>
                      {item.status.privacyStatus}
                    </span>
                  )}
                  {selected && (
                    <span className='text-primary inline-flex items-center gap-1 font-medium'>
                      <Icons.check aria-hidden='true' className='size-3.5' />
                      Selected
                    </span>
                  )}
                </span>
                <span className='text-muted-foreground break-all text-xs'>
                  {identifier ? `ID: ${identifier}` : `${typeLabel} ID unavailable`}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
