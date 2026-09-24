'use client';

import Link from 'next/link';
import { LevelBadge } from '@/components/app/level-badge';
import { ChannelIcon } from '@/components/channel-icon';
import { DigitSwap } from '@/components/motion/digit-swap';
import { SegmentedControl, type SegmentOption } from '@/components/rafii';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTime } from '@/lib/time';
import { ALL_CONNECTIONS, capabilitySummary, enableAnalyticsHref, notOfferedSentence, type ConnectionCoverage, type Coverage } from './coverage';

/** The one-line explanation each account segment carries as its title: level, verification and reading coverage. */
function segmentTitle(connection: ConnectionCoverage) {
  const unread = connection.verifiedJobs.filter((job) => !connection.readJobIds.has(job.id)).length;
  return [
    capabilitySummary(connection),
    connection.verifiedAt ? `Analytics level verified ${formatDateTime(connection.verifiedAt)}.` : 'No analytics verification recorded for this account.',
    `${connection.posts.length} ${connection.posts.length === 1 ? 'post' : 'posts'} with a reading · ${unread} verified ${unread === 1 ? 'post' : 'posts'} without one.`
  ].join(' ');
}

/**
 * The account scope (WHAT): one segment per connected account with its analytics level straight
 * from the capability matrix and how many of its verified posts have a reading. The segments
 * filter the posts below; the view never mutates anything.
 */
export function CoverageStrip({
  coverage,
  value,
  onValueChange,
  loading,
  canManage,
  showNotes = true
}: {
  coverage: Coverage;
  value: string;
  onValueChange: (value: string) => void;
  loading?: boolean;
  /** Whether this person may change connections; others are told who can. */
  canManage: boolean;
  /** Off while the "no account reports analytics" empty state lists the same next steps. */
  showNotes?: boolean;
}) {
  if (loading) {
    return (
      <div data-tour='analytics-coverage' className='flex gap-2'>
        <Skeleton className='h-11 w-20 rounded-[var(--rafii-radius-segment)]' />
        <Skeleton className='h-11 w-48 rounded-[var(--rafii-radius-segment)]' />
      </div>
    );
  }
  const totalPosts = coverage.connections.reduce((n, c) => n + c.posts.length, 0) + coverage.unmatchedPosts.length;
  const enableable = coverage.connections.filter((c) => c.providerOffersAnalytics && !c.direct);
  const notOffered = coverage.connections.filter((c) => !c.providerOffersAnalytics);
  const options: SegmentOption<string>[] = [
    {
      value: ALL_CONNECTIONS,
      ariaLabel: `All accounts, ${totalPosts} ${totalPosts === 1 ? 'post' : 'posts'} with a reading`,
      label: (
        <span className='inline-flex items-center gap-1.5'>
          All
          <DigitSwap value={totalPosts} className='text-muted-foreground text-xs tabular-nums' />
        </span>
      )
    },
    ...coverage.connections.map((connection) => ({
      value: connection.id,
      title: segmentTitle(connection),
      ariaLabel: `${connection.platform} ${connection.account}, ${connection.level}, ${connection.posts.length} ${connection.posts.length === 1 ? 'post' : 'posts'} with a reading`,
      label: (
        <span className='inline-flex items-center gap-2'>
          <ChannelIcon platform={connection.platform} name={connection.platform} />
          <span className='max-w-40 truncate'>{connection.account}</span>
          <LevelBadge level={connection.level} />
          <DigitSwap value={connection.posts.length} className='text-muted-foreground text-xs tabular-nums' />
        </span>
      )
    }))
  ];
  return (
    <div data-tour='analytics-coverage' className='flex min-w-0 flex-col gap-2'>
      <div className='scrollbar-hide -mx-1 max-w-full overflow-x-auto px-1 pb-1'>
        <SegmentedControl options={options} value={value} onChange={onValueChange} label='Filter posts by account' widths='content' size='md' className='min-w-max' />
      </div>
      {showNotes && (enableable.length > 0 || notOffered.length > 0) && (
        <ul className='text-muted-foreground flex flex-col gap-1 text-xs'>
          {notOffered.map((connection) => (
            <li key={connection.id} className='flex flex-wrap items-center gap-x-1.5'>
              <ChannelIcon platform={connection.platform} name={connection.platform} size='xs' />
              <span className='text-foreground'>{connection.account}</span>
              <span>· {notOfferedSentence(connection.platform)}</span>
            </li>
          ))}
          {enableable.map((connection) => (
            <li key={connection.id} className='flex flex-wrap items-center gap-x-1.5'>
              <ChannelIcon platform={connection.platform} name={connection.platform} size='xs' />
              <span className='text-foreground'>{connection.account}</span>
              <span>· Analytics not granted.</span>
              {canManage ? (
                <Link href={enableAnalyticsHref(connection.providerId)} className='t-learn rafii-focus text-foreground inline-flex items-center gap-0.5 rounded-md underline underline-offset-4'>
                  Enable analytics
                  <LearnMoreChevron />
                </Link>
              ) : (
                <span>Ask an owner or admin to enable it.</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {coverage.usesPlatformFallback && <p className='text-muted-foreground text-xs'>Posts are matched to accounts by platform in this reading; the API did not name the connection.</p>}
    </div>
  );
}
