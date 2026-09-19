'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button/stateful';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { useFlash } from '@/hooks/use-flash';
import { ApiError } from '@/lib/api/client';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDate, formatDateTime, formatNumber, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { AUDIT_API_LIMIT } from './audit-model';

/** The shape of a day of events, without pretend words. */
export function AuditListSkeleton() {
  return (
    <div className='flex flex-col gap-3' aria-busy>
      <span className='sr-only'>Loading the audit log</span>
      <Skeleton aria-hidden className='h-4 w-48' />
      <div aria-hidden className='divide-y rounded-lg border'>
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className='flex items-center gap-3 px-3 py-3 sm:px-4'>
            <Skeleton className='hidden h-8 w-20 sm:block' />
            <div className='flex flex-1 flex-col gap-1.5'>
              <Skeleton className='h-4 w-3/5' />
              <Skeleton className='h-3 w-2/5' />
            </div>
            <Skeleton className='hidden h-4 w-28 sm:block' />
          </div>
        ))}
      </div>
    </div>
  );
}

export function AuditLoadError({
  error,
  hasData,
  updatedAt,
  onRetry
}: {
  error: unknown;
  hasData: boolean;
  updatedAt: number;
  onRetry: () => Promise<{ isError: boolean }>;
}) {
  const [outcome, flash] = useFlash<'success' | 'error'>();
  const [retrying, setRetrying] = useState(false);
  const message = error instanceof ApiError ? error.message : null;
  return (
    <Alert variant='destructive'>
      <Icons.alertCircle />
      <AlertTitle>{hasData ? 'The audit log could not be refreshed.' : 'The audit log could not be loaded.'}</AlertTitle>
      <AlertDescription className='flex flex-col items-start gap-2'>
        {(message || hasData) && (
          <span>
            {message}
            {hasData && `${message ? ' ' : ''}Showing what was loaded ${relativeTime(updatedAt / 1000)}.`}
          </span>
        )}
        <StatefulButton
          variant='outline'
          size='sm'
          state={retrying ? 'loading' : (outcome ?? 'idle')}
          loadingText='Retrying…'
          successText='Loaded'
          errorText='Try again'
          onClick={async () => {
            setRetrying(true);
            const result = await onRetry();
            setRetrying(false);
            flash(result.isError ? 'error' : 'success');
          }}
        >
          Retry
        </StatefulButton>
      </AlertDescription>
    </Alert>
  );
}

/** Nothing recorded at all. Teaches what fills the log; offers the two general first steps the viewer may take. */
export function AuditEmpty() {
  const access = useWorkspaceAccess();
  const canInvite = checkAccess(access, { permission: 'manage_members' });
  const canConnect = checkAccess(access, { permission: 'manage_connections' });
  return (
    <Empty className='border' data-tour='audit-empty'>
      <EmptyHeader>
        <EmptyMedia variant='icon'>
          <Icons.history />
        </EmptyMedia>
        <EmptyTitle>No events yet</EmptyTitle>
        <EmptyDescription>
          This log fills up as people join, channels are connected, data is exported and privacy choices are made. It records who did what and
          when — never what was written.
        </EmptyDescription>
      </EmptyHeader>
      {(canInvite || canConnect) && (
        <EmptyContent className='flex-row flex-wrap justify-center'>
          {canInvite && (
            <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'outline', size: 'sm' }))}>
              Invite a teammate <LearnMoreChevron />
            </Link>
          )}
          {canConnect && (
            <Link href='/app/channels' className={cn('t-learn', buttonVariants({ variant: 'outline', size: 'sm' }))}>
              Connect a channel <LearnMoreChevron />
            </Link>
          )}
        </EmptyContent>
      )}
    </Empty>
  );
}

export function AuditFilterEmpty({ loaded, onReset }: { loaded: number; onReset: () => void }) {
  return (
    <Empty className='border'>
      <EmptyHeader>
        <EmptyMedia variant='icon'>
          <Icons.search />
        </EmptyMedia>
        <EmptyTitle>No events match these filters</EmptyTitle>
        <EmptyDescription>
          None of the {formatNumber(loaded)} loaded event{loaded === 1 ? '' : 's'} fit this kind and person.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant='outline' size='sm' onClick={onReset}>
          Reset filters
        </Button>
      </EmptyContent>
    </Empty>
  );
}

/**
 * How much of the log is on the page. The API returns the newest events only, with no way to ask for
 * older ones yet: fewer than the limit means this is everything; the limit itself means there may be more.
 */
export function AuditCoverage({ loaded, oldest, showing }: { loaded: number; oldest: number; showing: number }) {
  const capped = loaded >= AUDIT_API_LIMIT;
  const filtered = showing !== loaded;
  return (
    <p data-tour='audit-coverage' className='text-muted-foreground flex items-start gap-2 text-xs'>
      <Icons.info aria-hidden className='mt-px size-3.5 shrink-0' />
      <span>
        {filtered && `Showing ${formatNumber(showing)} of `}
        {capped ? (
          <>
            {filtered ? 'the' : 'Showing the'} newest {formatNumber(loaded)} events, back to{' '}
            <time dateTime={new Date(oldest * 1000).toISOString()}>{formatDateTime(oldest)}</time>. This page cannot load older events yet, so
            counts and filters cover these {formatNumber(loaded)} only.
          </>
        ) : (
          <>
            {filtered ? 'all' : 'All'} {formatNumber(loaded)} event{loaded === 1 ? '' : 's'} in this workspace, since{' '}
            <time dateTime={new Date(oldest * 1000).toISOString()}>{formatDate(oldest)}</time>.
          </>
        )}
      </span>
    </p>
  );
}
