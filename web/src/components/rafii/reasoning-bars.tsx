'use client';

import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

const HEIGHTS = [7, 11, 16, 20];

/**
 * The four-bar reasoning indicator (DNA v8 §15.4). It reinforces a labelled value and never
 * carries it, so it is hidden from assistive technology. `count` is the number of lit bars
 * (0–4); a half step (3.5) lights the fourth bar half-way for the CLI's `xhigh` level. Bars
 * light in a 35ms stagger unless motion is reduced.
 */
export function ReasoningBars({ count, muted = false, className }: { count: number; muted?: boolean; className?: string }) {
  const { reduced } = useMotionPreference();
  return (
    <span aria-hidden data-count={count} className={cn('flex h-5 shrink-0 items-end gap-[3px]', muted ? 'text-muted-foreground' : 'text-foreground', className)}>
      {HEIGHTS.map((height, index) => {
        const lit = count >= index + 1 ? 1 : count > index ? 0.5 : 0;
        return (
          <span
            key={height}
            data-lit={lit || undefined}
            className={cn('block w-1 origin-bottom rounded-[3px] bg-current', !reduced && 'transition-[opacity,transform] duration-[330ms] ease-[var(--rafii-ease-soft)]')}
            style={{ height, opacity: lit === 1 ? 1 : lit === 0.5 ? 0.55 : 0.16, transform: lit ? 'scaleY(1)' : 'scaleY(0.7)', transitionDelay: reduced ? undefined : `${index * 35}ms` }}
          />
        );
      })}
    </span>
  );
}
