'use client';

import { cn } from '@/lib/utils';

/**
 * Rafii's face: the approved character art (web/public/raffi, cut from the owner's character sheet). Decorative
 * next to the name, so the image itself is hidden from assistive tech. `thinking` adds a quiet ring that
 * reduced motion turns into a static outline. The animated idle loop replaces the still here once it exists.
 */
export function RafiiAvatar({ size = 28, thinking = false, variant = 'face', className }: { size?: number; thinking?: boolean; variant?: 'face' | 'full'; className?: string }) {
  const source = variant === 'full' ? (size > 128 ? '/raffi/full-512.png' : '/raffi/full-256.png') : size > 64 ? '/raffi/avatar-256.png' : '/raffi/avatar-128.png';
  return (
    <span
      aria-hidden
      data-thinking={thinking || undefined}
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden',
        variant === 'face' && 'rafii-glass rounded-full',
        thinking && 'ring-foreground/25 ring-2 motion-safe:animate-pulse',
        className
      )}
      style={{ width: size, height: size }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- a small static asset; next/image adds nothing here */}
      <img src={source} alt='' width={size} height={size} draggable={false} className='size-full object-contain select-none' />
    </span>
  );
}
