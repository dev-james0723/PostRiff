import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export type StateKind = 'empty' | 'loading' | 'error' | 'permission' | 'offline' | 'stale' | 'partial' | 'unsupported' | 'success';

const ICON: Record<StateKind, keyof typeof Icons> = {
  empty: 'circleDashed',
  loading: 'spinner',
  error: 'warning',
  permission: 'lock',
  offline: 'bolt',
  stale: 'clock',
  partial: 'info',
  unsupported: 'slash',
  success: 'check'
};

export interface StateMessageProps {
  kind: StateKind;
  title: ReactNode;
  description?: ReactNode;
  /** One relevant action (Retry, Connect, Clear filters). */
  action?: ReactNode;
  /** A small semantic illustration in place of the icon. */
  media?: ReactNode;
  /** Inline (a row inside a list) or a full quiet panel. */
  layout?: 'panel' | 'inline';
  className?: string;
}

/**
 * The shared state grammar (DNA §20.1): the same surface, spacing and typography for empty,
 * loading, error, permission, offline, stale, partial and unsupported states, with
 * domain-specific wording supplied by the page. Loading keeps stable geometry.
 */
export function StateMessage({ kind, title, description, action, media, layout = 'panel', className }: StateMessageProps) {
  const Icon = Icons[ICON[kind]];
  const live = kind === 'error' || kind === 'permission' ? 'alert' : 'status';
  if (kind === 'loading' && layout === 'panel') {
    return (
      <div role='status' aria-label={typeof title === 'string' ? title : 'Loading'} className={cn('rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-5', className)}>
        <span className='text-muted-foreground flex items-center gap-2 text-sm'>
          <Icons.spinner className='size-4 animate-spin motion-reduce:animate-none' aria-hidden />
          {title}
        </span>
        <Skeleton className='h-4 w-2/3' />
        <Skeleton className='h-4 w-1/2' />
      </div>
    );
  }
  return (
    <div
      role={live}
      className={cn(
        layout === 'panel' ? 'rafii-quiet flex flex-col items-center gap-3 rounded-[var(--rafii-radius-card)] px-5 py-8 text-center' : 'flex items-start gap-3 py-2 text-left',
        className
      )}
    >
      {media ?? (
        <span aria-hidden className={cn('text-muted-foreground flex shrink-0 items-center justify-center rounded-full', layout === 'panel' ? 'rafii-glass size-11' : 'mt-0.5 size-5')}>
          <Icon className={cn(layout === 'panel' ? 'size-5' : 'size-4', kind === 'loading' && 'animate-spin motion-reduce:animate-none')} />
        </span>
      )}
      <div className={cn('flex min-w-0 flex-col gap-1', layout === 'panel' ? 'max-w-md items-center' : 'flex-1')}>
        <p className='text-foreground text-sm font-medium text-balance'>{title}</p>
        {description && <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{description}</p>}
        {action && <div className={cn('mt-2 flex flex-wrap gap-2', layout === 'panel' && 'justify-center')}>{action}</div>}
      </div>
    </div>
  );
}
