'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { LevelBadge } from '@/components/app/level-badge';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel } from '@/features/workspace/rafii-parts';
import { useChannels, useSnapshot } from '@/lib/api/hooks';
import type { ChannelView } from '@/lib/api/types';
import { publishLevel } from '@/lib/channels/state';
import { useTimeZone } from '@/lib/preferences';
import { timeDefaults } from '@/lib/time';
import { STATUS } from '@/lib/status-labels';
import { cn } from '@/lib/utils';
import { countdown, countSending, readStatus, readWeek, TICK_MS, type NextPost, type StripDay } from './queue-status';
import { SectionUnavailable } from './retry';

const DAY_MS = 86_400_000;
/** Distinct channel marks a day cell has room for; the count badge carries the total. */
const MAX_MARKS = 3;

/** "Thu 14:30" inside the coming week; the date joins once a weekday alone would be ambiguous. */
function formatSlot(at: number, now: number, timeZone: string) {
  const options: Intl.DateTimeFormatOptions =
    at - now < 6 * DAY_MS ? { weekday: 'short', hour: 'numeric', minute: '2-digit' } : { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };
  return new Intl.DateTimeFormat(timeDefaults().locale, { ...options, timeZone }).format(at);
}

/** The connection a job goes out through: its `channelId` when the API wrote one, else platform and account. */
function channelFor(next: NextPost, channels: readonly ChannelView[]) {
  return (
    (next.channelId ? channels.find((channel) => channel.id === next.channelId) : undefined) ??
    channels.find((channel) => channel.platform === next.platform && channel.account === next.account)
  );
}

function DayCell({ day, today }: { day: StripDay; today: boolean }) {
  const { locale } = timeDefaults();
  // `day.date` is UTC midnight of a calendar date already resolved in the viewer's zone.
  const weekday = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(day.date);
  const dayOfMonth = new Intl.DateTimeFormat(locale, { day: 'numeric', timeZone: 'UTC' }).format(day.date);
  const spoken = new Intl.DateTimeFormat(locale, { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(day.date);
  const total = day.waiting.length + day.sending.length;
  const platforms = [...new Set([...day.sending, ...day.waiting].map((job) => job.platform))];
  const parts = [day.waiting.length ? `${day.waiting.length} approved` : null, day.sending.length ? `${day.sending.length} sending` : null, day.failed ? `${day.failed} failed` : null].filter(Boolean);

  return (
    <Link
      href={`/app/calendar?view=day&date=${day.key}`}
      aria-label={`${today ? 'Today, ' : ''}${spoken}: ${parts.length ? parts.join(', ') : 'nothing scheduled'}. Open in Calendar.`}
      aria-current={today ? 'date' : undefined}
      className={cn(
        'rafii-focus relative flex h-full min-h-24 w-full flex-col items-center gap-1 rounded-[var(--rafii-radius-control)] px-1 py-2 text-center transition-colors',
        today ? 'rafii-glass-selected' : 'rafii-quiet hover:rafii-glass'
      )}
    >
      <span className={cn('text-xs leading-none', today ? 'text-foreground font-medium' : 'text-muted-foreground')}>{today ? 'Today' : weekday}</span>
      <span className='text-foreground text-sm leading-tight font-medium tabular-nums'>{dayOfMonth}</span>
      {total > 0 ? (
        <AnimatedBadge size='sm' showIcon={false} status='info' pulse={day.sending.length > 0} contentKey={total} className='h-5 px-1.5'>
          {total}
        </AnimatedBadge>
      ) : (
        <span aria-hidden className='text-muted-foreground flex h-5 items-center text-xs'>
          —
        </span>
      )}
      <span aria-hidden className='flex h-4 items-center -space-x-1'>
        {platforms.slice(0, MAX_MARKS).map((platform) => (
          <ChannelIcon key={platform} platform={platform} name={platform} size='xs' className='ring-background ring-1' />
        ))}
      </span>
      {day.failed > 0 && <span aria-hidden className='bg-destructive absolute top-1.5 right-1.5 size-1.5 rounded-full' />}
    </Link>
  );
}

/**
 * The next approved slot and the coming seven days, in the viewer's zone. Only approved jobs with a
 * timing the worker can read appear; drafts still waiting for approval are listed under attention.
 */
export function NextUp({ className }: { className?: string }) {
  const snapshot = useSnapshot();
  const channels = useChannels();
  const timeZone = useTimeZone();
  // Read after mount so the server and client render the same markup; reset whenever new data lands.
  const [now, setNow] = useState<number | null>(null);
  const updatedAt = snapshot.dataUpdatedAt;
  useEffect(() => {
    setNow(Date.now());
  }, [updatedAt]);

  const phase2 = snapshot.data?.state.phase2;
  const ready = Boolean(snapshot.data) && now !== null;
  const status = useMemo(() => (ready && now !== null ? readStatus(phase2, now) : null), [ready, phase2, now]);
  const sending = useMemo(() => countSending(phase2), [phase2]);
  const week = useMemo(() => (ready && now !== null ? readWeek(phase2, now, timeZone) : null), [ready, phase2, now, timeZone]);

  // The countdown only moves while there is something to count down to.
  const ticking = Boolean(status?.next) || sending > 0;
  useEffect(() => {
    if (!ticking) return;
    const id = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, [ticking]);

  const next = status?.next ?? null;
  const nextChannel = next && channels.data && !channels.isError ? channelFor(next, channels.data.channels) : undefined;

  return (
    <Panel
      data-tour='overview-next-up'
      className={className}
      title='Next up'
      titleId='overview-next-up-heading'
      actions={
        <Link href='/app/calendar' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'default' }))}>
          Calendar <LearnMoreChevron />
        </Link>
      }
    >
      {snapshot.isError ? (
        <SectionUnavailable message='Couldn’t load what’s next.' query={snapshot} />
      ) : !status || !week || now === null ? (
        <>
          <Skeleton className='h-12 w-full rounded-[var(--rafii-radius-control)]' />
          <Skeleton className='h-24 w-full rounded-[var(--rafii-radius-control)]' />
        </>
      ) : (
        <>
          {next ? (
            <div className='rafii-glass flex min-w-0 items-center gap-3 rounded-[var(--rafii-radius-control)] p-3.5'>
              <ChannelIcon platform={next.platform} name={next.platform} size='md' />
              <div className='min-w-0 flex-1'>
                <p className='text-foreground truncate text-sm font-medium'>
                  {next.platform} · {next.account}
                </p>
                <p className='text-muted-foreground text-xs'>
                  <time dateTime={new Date(next.at).toISOString()} title={timeZone.replace(/_/g, ' ')}>
                    {formatSlot(next.at, now, timeZone)}
                  </time>
                  <span className='tabular-nums'> · {countdown(next.at - now)}</span>
                </p>
              </div>
              {nextChannel && (
                <div className='hidden shrink-0 items-center sm:flex'>
                  <LevelBadge level={publishLevel(nextChannel)} />
                </div>
              )}
            </div>
          ) : (
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <p className='text-foreground text-sm font-medium'>Nothing scheduled</p>
              <Link href='/app/queue' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'default' }))}>
                Open Queue <LearnMoreChevron />
              </Link>
            </div>
          )}

          {(sending > 0 || status.failed > 0) && (
            <div className='flex flex-wrap gap-2'>
              {sending > 0 && (
                <AnimatedBadge size='sm' status='info' pulse contentKey={sending}>
                  {sending} {STATUS.publishing.toLowerCase()}
                </AnimatedBadge>
              )}
              {status.failed > 0 && (
                <Link href='/app/queue' className='rafii-focus rounded-full'>
                  <AnimatedBadge size='sm' status='danger' contentKey={status.failed}>
                    {status.failed} {STATUS.failed.toLowerCase()}
                    <span className='sr-only'> in the last 24 hours</span>
                  </AnimatedBadge>
                </Link>
              )}
            </div>
          )}

          <ul aria-label='The next seven days' className='relative -mx-1 flex snap-x gap-2 overflow-x-auto px-1 pt-0.5 pb-1 sm:grid sm:grid-cols-7 sm:overflow-visible'>
            {week.map((day, index) => (
              <li key={day.key} className='min-w-14 shrink-0 snap-start sm:min-w-0'>
                <DayCell day={day} today={index === 0} />
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
