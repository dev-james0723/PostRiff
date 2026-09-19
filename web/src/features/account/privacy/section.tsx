'use client';

import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { cn } from '@/lib/utils';

/** The part of a TanStack query result a Retry needs. */
export interface Refetchable {
  isFetching: boolean;
  error: unknown;
  refetch: () => Promise<unknown>;
}

/** The API's own sentence when it sent one, a plain fallback otherwise. */
export function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export function PrivacySection({
  id,
  title,
  description,
  action,
  children,
  className,
  ...rest
}: {
  id: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  'data-tour'?: string;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className={cn('flex min-w-0 flex-col gap-3', className)} {...rest}>
      <div className='flex flex-wrap items-end justify-between gap-x-4 gap-y-1'>
        <div className='flex min-w-0 flex-col gap-0.5'>
          <h3 id={`${id}-heading`} className='text-lg font-semibold'>
            {title}
          </h3>
          {description && <p className='text-muted-foreground text-sm'>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Refetches a query that failed. Disabled while a request is out, so a second press cannot stack. */
export function RetryButton({ query, label = 'Retry', className }: { query: Refetchable; label?: string; className?: string }) {
  return (
    <Button variant='outline' size='xs' className={cn('w-fit', className)} disabled={query.isFetching} onClick={() => void query.refetch()}>
      <Icons.refresh className={cn(query.isFetching && 'motion-safe:animate-spin')} /> {label}
    </Button>
  );
}

/** A part of the page whose data could not be read: the reason, and a Retry. Never a zero. */
export function Unavailable({ query, fallback, className }: { query: Refetchable; fallback: string; className?: string }) {
  return (
    <div role='status' className={cn('flex flex-wrap items-center gap-x-3 gap-y-2', className)}>
      <p className='text-muted-foreground text-sm'>{errorMessage(query.error, fallback)}</p>
      <RetryButton query={query} />
    </div>
  );
}
