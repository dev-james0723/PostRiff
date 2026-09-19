'use client';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** The part of a TanStack query result a Retry needs. */
export interface Refetchable {
  isFetching: boolean;
  refetch: () => Promise<unknown>;
}

/** A region whose data could not be read: say so plainly and offer a Retry. Never a zero, an Off or an empty list. */
export function Unavailable({ message, query, className }: { message: string; query: Refetchable; className?: string }) {
  return (
    <div role='status' className={cn('flex flex-col items-start gap-2', className)}>
      <p className='text-muted-foreground text-sm'>{message}</p>
      <Button variant='outline' size='xs' disabled={query.isFetching} onClick={() => void query.refetch()}>
        <Icons.refresh className={cn(query.isFetching && 'motion-safe:animate-spin')} /> Retry
      </Button>
    </div>
  );
}

/** Shown beside data that is still on screen after a later refresh failed, so an old copy never passes for the current one. */
export function StaleNotice({ query, className }: { query: Refetchable; className?: string }) {
  return (
    <div role='status' className={cn('text-muted-foreground flex flex-wrap items-center gap-2 text-xs', className)}>
      <span>This is the last copy that loaded; the latest could not be read.</span>
      <Button variant='ghost' size='xs' disabled={query.isFetching} onClick={() => void query.refetch()}>
        <Icons.refresh className={cn(query.isFetching && 'motion-safe:animate-spin')} /> Retry
      </Button>
    </div>
  );
}
