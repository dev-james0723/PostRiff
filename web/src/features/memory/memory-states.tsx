'use client';

import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
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
    <StateMessage
      kind='error'
      layout='inline'
      title={message}
      className={className}
      action={
        <Button variant='glass' size='sm' disabled={query.isFetching} onClick={() => void query.refetch()}>
          <Icons.refresh className={cn(query.isFetching && 'motion-safe:animate-spin')} /> Retry
        </Button>
      }
    />
  );
}

/** Shown beside data that is still on screen after a later refresh failed, so an old copy never passes for the current one. */
export function StaleNotice({ query, className }: { query: Refetchable; className?: string }) {
  return (
    <StateMessage
      kind='stale'
      layout='inline'
      title='This is the last copy that loaded; the latest could not be read.'
      className={className}
      action={
        <Button variant='quiet' size='sm' disabled={query.isFetching} onClick={() => void query.refetch()}>
          <Icons.refresh className={cn(query.isFetching && 'motion-safe:animate-spin')} /> Retry
        </Button>
      }
    />
  );
}
