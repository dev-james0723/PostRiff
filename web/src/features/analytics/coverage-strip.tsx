'use client';

import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';
import { LevelBadge } from '@/components/app/level-badge';
import { ChannelIcon } from '@/components/channel-icon';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tooltip } from '@/components/motion/tooltip';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime } from '@/lib/time';
import {
  ALL_CONNECTIONS,
  capabilitySummary,
  enableAnalyticsHref,
  notOfferedSentence,
  type ConnectionCoverage,
  type Coverage
} from './coverage';

/** 40ms per item, capped so the whole strip has settled within 300ms. */
export const STAGGER = 0.04;
export const STAGGER_CAP = 0.26;
export const ENTER_DURATION = 0.25;

function ChipTooltip({ connection }: { connection: ConnectionCoverage }) {
  const unread = connection.verifiedJobs.filter((job) => !connection.readJobIds.has(job.id)).length;
  return (
    <span className='flex flex-col gap-1 text-left'>
      <span>{capabilitySummary(connection)}</span>
      <span className='opacity-70'>
        {connection.verifiedAt
          ? `Analytics level verified ${formatDateTime(connection.verifiedAt)}`
          : 'No analytics verification recorded for this account'}
      </span>
      <span className='opacity-70'>
        {connection.posts.length} {connection.posts.length === 1 ? 'post' : 'posts'} with a reading
        · {unread} verified {unread === 1 ? 'post' : 'posts'} without one
      </span>
    </span>
  );
}

/**
 * One chip per connected account: the account, its analytics level straight from the
 * capability matrix, and how many of its verified posts have a reading. The chips are
 * the tabs that filter the posts below.
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
  const reduce = useReducedMotion();
  if (loading) {
    return (
      <div data-tour='analytics-coverage' className='flex gap-2'>
        <Skeleton className='h-9 w-16' />
        <Skeleton className='h-9 w-44' />
      </div>
    );
  }
  const totalPosts =
    coverage.connections.reduce((n, c) => n + c.posts.length, 0) + coverage.unmatchedPosts.length;
  const enableable = coverage.connections.filter((c) => c.providerOffersAnalytics && !c.direct);
  const notOffered = coverage.connections.filter((c) => !c.providerOffersAnalytics);
  return (
    <div data-tour='analytics-coverage' className='flex min-w-0 flex-col gap-2'>
      <Tabs
        value={value}
        onValueChange={(next) => onValueChange(String(next))}
        className='min-w-0 max-w-full'
      >
        <TabsList
          aria-label='Filter posts by account'
          className='scrollbar-hide h-auto max-w-full snap-x justify-start overflow-x-auto group-data-horizontal/tabs:h-auto'
        >
          <TabsTrigger value={ALL_CONNECTIONS} className='h-auto snap-start gap-1.5 px-3 py-1.5'>
            All
            <DigitSwap value={totalPosts} className='text-xs opacity-75' />
          </TabsTrigger>
          {coverage.connections.map((connection, index) => (
            <motion.div
              key={connection.id}
              className='snap-start'
              initial={reduce ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={
                reduce
                  ? { duration: 0 }
                  : {
                      duration: ENTER_DURATION,
                      delay: Math.min(index * STAGGER, STAGGER_CAP),
                      ease: EASE_OUT
                    }
              }
            >
              <Tooltip content={<ChipTooltip connection={connection} />} side='bottom'>
                <TabsTrigger value={connection.id} className='h-auto gap-2 px-2.5 py-1.5'>
                  <ChannelIcon platform={connection.platform} name={connection.platform} />
                  <span className='max-w-40 truncate'>{connection.account}</span>
                  <LevelBadge level={connection.level} />
                  <DigitSwap value={connection.posts.length} className='text-xs opacity-75' />
                </TabsTrigger>
              </Tooltip>
            </motion.div>
          ))}
        </TabsList>
      </Tabs>
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
                <Link
                  href={enableAnalyticsHref(connection.providerId)}
                  className='t-learn text-primary inline-flex items-center gap-0.5 hover:underline'
                >
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
      {coverage.usesPlatformFallback && (
        <p className='text-muted-foreground text-xs'>
          Posts are matched to accounts by platform in this reading; the API did not name the
          connection.
        </p>
      )}
    </div>
  );
}
