'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { useFlash } from '@/hooks/use-flash';
import { ApiError } from '@/lib/api/client';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDate, formatDateTime, formatNumber, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { AUDIT_API_LIMIT } from './audit-model';

/** The log while it loads: stable geometry, no pretend words. */
export function AuditListSkeleton() {
  return <StateMessage kind='loading' title='Loading the audit log…' />;
}

export function AuditLoadError({ error, hasData, updatedAt, onRetry }: { error: unknown; hasData: boolean; updatedAt: number; onRetry: () => Promise<{ isError: boolean }> }) {
  const [outcome, flash] = useFlash<'success' | 'error'>();
  const [retrying, setRetrying] = useState(false);
  const message = error instanceof ApiError ? error.message : null;
  const description = [message, hasData ? `Showing what was loaded ${relativeTime(updatedAt / 1000)}.` : null].filter(Boolean).join(' ');
  return (
    <StateMessage
      kind={hasData ? 'stale' : 'error'}
      layout={hasData ? 'inline' : 'panel'}
      className={hasData ? 'rafii-quiet rounded-[var(--rafii-radius-card)] px-4 py-3' : undefined}
      title={hasData ? 'Couldn’t refresh the audit log.' : 'Couldn’t load the audit log.'}
      description={description || undefined}
      action={
        <Button
          variant='glass'
          size='default'
          disabled={retrying}
          aria-busy={retrying || undefined}
          onClick={async () => {
            setRetrying(true);
            const result = await onRetry();
            setRetrying(false);
            flash(result.isError ? 'error' : 'success');
          }}
        >
          {retrying ? (
            <>
              <Icons.spinner className='motion-safe:animate-spin' /> Retrying…
            </>
          ) : outcome === 'success' ? (
            <>
              <Icons.check /> Loaded
            </>
          ) : outcome === 'error' ? (
            'Try again'
          ) : (
            <>
              <Icons.refresh /> Retry
            </>
          )}
        </Button>
      }
    />
  );
}

/** Nothing recorded at all. Teaches what fills the log; offers the two general first steps the viewer may take. */
export function AuditEmpty() {
  const access = useWorkspaceAccess();
  const canInvite = checkAccess(access, { permission: 'manage_members' });
  const canConnect = checkAccess(access, { permission: 'manage_connections' });
  return (
    <div data-tour='audit-empty'>
      <StateMessage
        kind='empty'
        title='No events yet'
        action={
          canInvite || canConnect ? (
            <>
              {canInvite && (
                <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'glass', size: 'default' }))}>
                  Invite a teammate <LearnMoreChevron />
                </Link>
              )}
              {canConnect && (
                <Link href='/app/channels' className={cn('t-learn', buttonVariants({ variant: 'glass', size: 'default' }))}>
                  Connect a channel <LearnMoreChevron />
                </Link>
              )}
            </>
          ) : undefined
        }
      />
    </div>
  );
}

export function AuditFilterEmpty({ onReset }: { loaded: number; onReset: () => void }) {
  return (
    <StateMessage
      kind='empty'
      title='No events match these filters'
      action={
        <Button variant='glass' size='default' onClick={onReset}>
          Reset filters
        </Button>
      }
    />
  );
}

/**
 * How much of the log is on the page. The API returns the newest events only, with no way to ask for
 * older ones yet: fewer than the limit means this is everything; the limit itself means there may be more.
 */
export function AuditCoverage({ loaded, oldest, showing }: { loaded: number; oldest: number; showing: number }) {
  const capped = loaded >= AUDIT_API_LIMIT;
  const filtered = showing !== loaded;
  const iso = new Date(oldest * 1000).toISOString();
  return (
    <p data-tour='audit-coverage' className='text-muted-foreground flex items-start gap-2 text-xs'>
      <Icons.info aria-hidden className='mt-px size-3.5 shrink-0' />
      <span>
        Showing {filtered ? `${formatNumber(showing)} of ` : ''}
        {capped ? 'the newest ' : filtered ? '' : 'all '}
        {formatNumber(loaded)} event{loaded === 1 ? '' : 's'} since{' '}
        <time dateTime={iso} title={formatDateTime(oldest)}>
          {formatDate(oldest)}
        </time>
        .{capped ? ' Older events aren’t loaded.' : ''}
      </span>
    </p>
  );
}
