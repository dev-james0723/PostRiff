'use client';

import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/**
 * A descriptive circle-i explanation, independent from its parent item's selection (DNA §12.4).
 * Pressing it never selects, submits or closes anything else; the description is plain text.
 */
export function InfoTip({ label, title, description, className }: { label: string; title?: ReactNode; description: ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type='button'
            aria-label={label}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
            className={cn('rafii-focus text-muted-foreground hover:text-foreground hover:rafii-quiet flex size-11 shrink-0 items-center justify-center rounded-full transition-colors', className)}
          />
        }
      >
        <Icons.info className='size-4' />
      </TooltipTrigger>
      <TooltipContent side='bottom' className='rafii-elevated max-w-72 rounded-2xl px-3.5 py-3 text-left'>
        {title && <p className='text-foreground mb-1 text-sm font-medium'>{title}</p>}
        <p className='text-muted-foreground text-xs leading-relaxed'>{description}</p>
      </TooltipContent>
    </Tooltip>
  );
}
