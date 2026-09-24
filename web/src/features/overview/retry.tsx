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

/** Refetches the queries that failed. Disabled while a request is already out, so a second press cannot stack. */
export function RetryButton({ queries, className, label = 'Retry', size = 'sm' }: { queries: Refetchable[]; className?: string; label?: string; size?: 'sm' | 'default' | 'control' }) {
  const fetching = queries.some((query) => query.isFetching);
  return (
    <Button
      variant='glass'
      size={size}
      className={cn('w-fit', className)}
      disabled={fetching}
      onClick={() => {
        for (const query of queries) void query.refetch();
      }}
    >
      <Icons.refresh className={cn(fetching && 'motion-safe:animate-spin')} /> {label}
    </Button>
  );
}

/** A section whose data could not be read: say so plainly and offer a Retry, never a zero. */
export function SectionUnavailable({ message, query }: { message: string; query: Refetchable }) {
  return <StateMessage kind='error' layout='inline' title={message} action={<RetryButton queries={[query]} />} />;
}
