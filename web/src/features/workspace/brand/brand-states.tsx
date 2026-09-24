'use client';

import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTime } from '@/lib/time';
import { CardSkeleton, RetryButton, errorMessage, type Refetchable } from './brand-parts';

/** The page layout in placeholder form while the snapshot loads, so nothing jumps when it arrives. */
export function BrandSkeleton() {
  return (
    <div role='status' aria-label='Loading brand and voice' className='flex flex-col gap-4 md:gap-5'>
      <Surface material='glass' className='flex flex-col gap-4'>
        <Skeleton className='h-7 w-44 rounded-full' />
        <Skeleton className='h-4 w-full max-w-prose' />
        <div className='grid grid-cols-2 gap-4 sm:grid-cols-4'>
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className='flex flex-col gap-1.5'>
              <Skeleton className='h-3 w-24' />
              <Skeleton className='h-6 w-10' />
            </div>
          ))}
        </div>
      </Surface>
      <div className='grid gap-4 md:gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'>
        <div className='flex min-w-0 flex-col gap-4 md:gap-5'>
          <CardSkeleton lines={5} />
          <CardSkeleton lines={4} />
        </div>
        <div className='flex min-w-0 flex-col gap-4 md:gap-5'>
          <CardSkeleton lines={3} />
          <CardSkeleton lines={3} />
        </div>
      </div>
    </div>
  );
}

/** Nothing could be read: say so, show the server's reason when there is one, and offer a retry. */
export function BrandLoadError({ query }: { query: Refetchable }) {
  const detail = errorMessage(query.error);
  return (
    <StateMessage
      kind='error'
      title='This workspace could not be loaded'
      description={detail ?? 'The voice and brand context are unavailable right now.'}
      action={
        <Button variant='glass' size='control' disabled={query.isFetching} onClick={() => void query.refetch()}>
          <Icons.refresh className={query.isFetching ? 'motion-safe:animate-spin' : undefined} /> Try again
        </Button>
      }
    />
  );
}

/** A later refresh failed: keep what loaded, and say how old it is. */
export function BrandStaleNotice({ query, updatedAt }: { query: Refetchable; updatedAt: number }) {
  return (
    <StateMessage
      kind='stale'
      layout='inline'
      className='rafii-quiet rounded-[var(--rafii-radius-card)] px-4 py-3'
      title={`Showing what loaded at ${formatDateTime(updatedAt / 1000)}`}
      description={errorMessage(query.error) ?? 'The latest workspace state could not be read.'}
      action={<RetryButton query={query} />}
    />
  );
}
