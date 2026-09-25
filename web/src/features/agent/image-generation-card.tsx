'use client';

import { ImageGeneration } from 'img-fx';
import { useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { Skeleton } from '@/components/ui/skeleton';
import type { GeneratedImage } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { useAssetImage } from '@/features/library/asset-card';

interface ImageGenerationCardProps {
  image?: GeneratedImage | null;
  running?: boolean;
  className?: string;
}

/**
 * The shared Ideas media state. With no image URL, img-fx stays in its churning
 * shader phase; when the private candidate arrives, the same surface dissolves
 * into it. The stored image remains the accessible, non-WebGL fallback.
 */
export function ImageGenerationCard({ image, running = false, className }: ImageGenerationCardProps) {
  const reduce = useReducedMotion();
  const asset = useAssetImage(image?.id ?? '', Boolean(image?.id));
  const images = asset.data ? [asset.data] : [];
  const label = running ? 'Generating image…' : asset.isLoading ? 'Loading image…' : image ? 'Generated image' : 'Preparing…';

  return (
    <figure className={cn('w-full max-w-[420px]', className)} aria-label={label} aria-busy={running || asset.isLoading}>
      <ImageGeneration
        preset='pixels-organic'
        images={images}
        autoReveal={images.length > 0 && !reduce}
        paused={Boolean(reduce)}
        revealDelayRange={[0.1, 0.25]}
        revealHoldMs={8000}
        revealFadeOutMs={500}
        borderRadius={18}
        className='w-full'
      >
        <div className='bg-muted relative aspect-square w-full overflow-hidden rounded-[18px] ring-1 ring-black/8 dark:ring-white/10'>
          {asset.data ? (
            // Private media is fetched with the signed-in API client and cached as a blob URL.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={asset.data} alt={image?.alt ?? 'Generated image'} className='size-full object-cover' />
          ) : (
            <Skeleton className='absolute inset-0 size-full rounded-none' />
          )}
          <div className='pointer-events-none absolute inset-x-3 bottom-3 z-20 flex items-center gap-2 rounded-full bg-black/65 px-3 py-2 text-xs font-medium text-white shadow-lg backdrop-blur-md'>
            {running ? <Icons.spinner className='size-3.5 animate-spin' /> : <Icons.media className='size-3.5' />}
            <span>{label}</span>
          </div>
        </div>
      </ImageGeneration>
      {asset.isError && <figcaption className='text-foreground mt-2 text-xs font-medium'>Saved, but the preview couldn’t load.</figcaption>}
    </figure>
  );
}
