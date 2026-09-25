'use client';

import { useState, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { isoToEpoch } from './voice-model';

/** The part of a TanStack query result a Retry needs. */
export interface Refetchable {
  isFetching: boolean;
  error?: unknown;
  refetch: () => Promise<unknown>;
}

export function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : null;
}

/** Refetches a failed query. Disabled while a request is out, so a second press cannot stack. */
export function RetryButton({ query, label = 'Retry' }: { query: Refetchable; label?: string }) {
  return (
    <Button variant='glass' size='sm' className='w-fit' disabled={query.isFetching} onClick={() => void query.refetch()}>
      <Icons.refresh className={cn(query.isFetching && 'motion-safe:animate-spin')} /> {label}
    </Button>
  );
}

/** A section whose data could not be read: say so plainly and offer a Retry, never a zero. */
export function SectionUnavailable({ message, query }: { message: string; query?: Refetchable }) {
  const detail = query ? errorMessage(query.error) : null;
  return <StateMessage kind='error' layout='inline' title={message} description={detail ?? undefined} action={query ? <RetryButton query={query} /> : undefined} />;
}

/** A panel-shaped placeholder while the snapshot loads. */
export function CardSkeleton({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <Surface material='quiet' className={cn('flex flex-col gap-4', className)} aria-busy='true'>
      <div className='flex flex-col gap-2'>
        <Skeleton className='h-5 w-32' />
        <Skeleton className='h-4 w-3/4' />
      </div>
      <div className='flex flex-col gap-2'>
        {Array.from({ length: lines }, (_, index) => (
          <Skeleton key={index} className={cn('h-4', index % 2 ? 'w-2/3' : 'w-full')} />
        ))}
      </div>
    </Surface>
  );
}

/** A date from an ISO string, with the full time on hover. Unreadable dates say so. */
export function ApprovedDate({ iso }: { iso: string | undefined | null }) {
  const epoch = isoToEpoch(iso);
  if (!epoch) return <span>date unknown</span>;
  return (
    <time dateTime={iso ?? undefined} title={formatDateTime(epoch)}>
      {formatDate(epoch)}
    </time>
  );
}

/** Long text clamped to a few lines with a toggle; short text renders as is. */
export function ExpandableText({ text, lines = 4, className, as = 'p' }: { text: string; lines?: 3 | 4 | 6; className?: string; as?: 'p' | 'blockquote' }) {
  const [open, setOpen] = useState(false);
  // Roughly a line of 90 characters at panel width; short text never gets a toggle.
  const long = text.length > lines * 90 || text.split('\n').length > lines;
  const clamp = lines === 3 ? 'line-clamp-3' : lines === 6 ? 'line-clamp-6' : 'line-clamp-4';
  const Tag = as;
  return (
    <div className='flex min-w-0 flex-col items-start gap-1'>
      <Tag className={cn('min-w-0 break-words whitespace-pre-wrap', !open && long && clamp, className)}>{text}</Tag>
      {long && (
        <Button variant='link' size='xs' className='text-foreground h-auto px-0' aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? 'Show less' : 'Show all'}
        </Button>
      )}
    </div>
  );
}

/** One label/value row in a definition list. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className='grid min-w-0 gap-1 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3'>
      <dt className='text-muted-foreground text-xs sm:pt-0.5'>{label}</dt>
      <dd className='text-foreground min-w-0 text-sm'>{children}</dd>
    </div>
  );
}

export function NotSet({ children = 'Not set' }: { children?: ReactNode }) {
  return <span className='text-muted-foreground'>{children}</span>;
}

/** A small caption label above a group of values inside a panel. */
export function Caption({ children }: { children: ReactNode }) {
  return <span className='text-muted-foreground text-xs font-medium'>{children}</span>;
}
