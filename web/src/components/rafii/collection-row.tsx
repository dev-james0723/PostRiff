import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/**
 * List row anatomy (DNA §13.3): leading mark | title + tags | state | separate action slot.
 * The row's own selection control and its info/overflow actions are different hit targets.
 */
export function CollectionRow({ leading, title, meta, state, actions, selected, className, as: Component = 'div', ...props }: { leading?: ReactNode; title: ReactNode; meta?: ReactNode; state?: ReactNode; actions?: ReactNode; selected?: boolean; className?: string; as?: 'div' | 'li' | 'article' } & Omit<React.HTMLAttributes<HTMLElement>, 'title'>) {
  return (
    <Component
      data-selected={selected ? 'true' : undefined}
      className={cn('flex min-h-14 items-center gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 transition-colors', selected ? 'rafii-glass-selected' : 'rafii-quiet', className)}
      {...props}
    >
      {leading && <span className='flex shrink-0 items-center'>{leading}</span>}
      {/* A 12rem basis: in a wrapping row the state and actions move to the next line before the text
          column is squeezed to a word per line (phones). */}
      <span className='flex min-w-0 flex-[1_1_12rem] flex-col gap-0.5'>
        <span className='text-foreground text-sm font-medium'>{title}</span>
        {meta && <span className='text-muted-foreground text-xs'>{meta}</span>}
      </span>
      {/* State and actions never exceed the row: on a phone they wrap onto their own line and wrap inside it. */}
      {state && <span className='text-muted-foreground max-w-full shrink-0 text-xs'>{state}</span>}
      {actions && <span className='flex max-w-full shrink-0 flex-wrap items-center gap-1'>{actions}</span>}
    </Component>
  );
}
