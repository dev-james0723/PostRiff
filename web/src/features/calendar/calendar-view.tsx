'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { fromDate, isToday, parseDate, today, type CalendarDate } from '@internationalized/date';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { Calendar, useLocalTimeZone } from '@/components/application/calendar/calendar';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import {
  EVENT_COLORS,
  type CalendarDetailsContext,
  type CalendarEvent,
  type CalendarEventColor
} from '@/components/application/calendar/config';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import PageContainer from '@/components/layout/page-container';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { useSnapshot } from '@/lib/api/hooks';
import type { Manifest } from '@/lib/api/types';
import { cn } from '@/lib/utils';

type Kind = 'review' | 'waiting' | 'in-flight' | 'verified' | 'failed' | 'canceled';

interface Post {
  kind: Kind;
  platform: string;
  account: string;
  text: string;
  at: Date;
  /** The zone the time was approved in. */
  approvedZone: string;
  cancelRequested: boolean;
  manifest: Manifest;
}

const KIND_META: Record<Kind, { label: string; color: CalendarEventColor; status: AnimatedBadgeStatus }> = {
  review: { label: 'Needs approval', color: 'yellow', status: 'warning' },
  waiting: { label: 'Scheduled', color: 'blue', status: 'info' },
  'in-flight': { label: 'Publishing', color: 'indigo', status: 'loading' },
  verified: { label: 'Published', color: 'green', status: 'success' },
  failed: { label: 'Failed', color: 'red', status: 'danger' },
  canceled: { label: 'Canceled', color: 'gray', status: 'neutral' }
};

const VIEWS = ['month', 'week', 'day'] as const;

const NOUN = { one: 'post', other: 'posts' };

const infoContent = {
  title: 'Calendar',
  sections: [
    {
      title: 'What shows here',
      description: 'Reviews waiting for approval and every publishing job, placed at its approved time in your time zone.'
    },
    {
      title: 'Month, week and day',
      description: 'Month shows the shape of the month; week and day place each post on the hour it goes out. Choose a date or "+N more" to open that day.'
    },
    {
      title: 'Moving a post',
      description: 'Timing is part of the exact approval. To change it, prepare the draft again with the new time from the Pipeline or Queue.'
    }
  ]
};

function kindOf(state: string): Kind {
  if (state === 'verified') return 'verified';
  if (state === 'failed') return 'failed';
  if (state === 'canceled') return 'canceled';
  if (['submitting', 'provider_accepted', 'published', 'uncertain'].includes(state)) return 'in-flight';
  return 'waiting';
}

function parseDay(value: string | null): CalendarDate | null {
  if (!value) return null;
  try {
    return parseDate(value);
  } catch {
    return null;
  }
}

function zoneTime(at: Date, zone: string) {
  try {
    return new Intl.DateTimeFormat('en', { timeStyle: 'short', timeZone: zone }).format(at);
  } catch {
    return null;
  }
}

function PostDetails({ event, context, timeZone }: { event: CalendarEvent<Post>; context: CalendarDetailsContext; timeZone: string }) {
  const post = event.data;
  if (!post) return null;
  const meta = KIND_META[post.kind];
  const when = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(post.at);
  const approvedElsewhere = post.approvedZone && post.approvedZone !== timeZone ? zoneTime(post.at, post.approvedZone) : null;
  const final = post.kind === 'verified' || post.kind === 'failed' || post.kind === 'canceled';

  const details = (
    <div className={cn('flex min-w-0 flex-col gap-2', context === 'popover' && 'w-72 shrink-0')}>
      <div className='flex items-center justify-between gap-2'>
        <span className='flex min-w-0 items-center gap-2 font-medium'>
          <ChannelIcon platform={post.platform} name={post.platform} size='xs' />
          <span className='truncate'>{post.platform}</span>
        </span>
        <AnimatedBadge size='sm' status={meta.status}>
          {meta.label}
        </AnimatedBadge>
      </div>
      <p className='text-muted-foreground text-xs'>
        {post.account} · {when}
        {approvedElsewhere && ` (${approvedElsewhere} ${post.approvedZone})`}
      </p>
      {post.cancelRequested && !final && <p className='text-muted-foreground text-xs'>Cancel requested</p>}
      <p className={cn('text-xs whitespace-pre-line', context === 'popover' ? 'line-clamp-5' : 'line-clamp-3')}>{post.text}</p>
      {context === 'popover' && (
        <Link href='/app/queue' className={cn('t-learn self-start', buttonVariants({ variant: 'ghost', size: 'sm' }), '-ml-2.5')}>
          Open the queue <LearnMoreChevron />
        </Link>
      )}
    </div>
  );

  if (context !== 'popover') return details;
  return (
    <div className='flex max-h-[calc(var(--available-height,100vh)-1rem)] flex-col gap-4 overflow-y-auto sm:flex-row sm:items-start'>
      {details}
      <ManifestPreview manifest={post.manifest} timeZone={timeZone} className='border-t pt-3 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-4' />
    </div>
  );
}

export function CalendarView() {
  const snapshot = useSnapshot();
  const timeZone = useLocalTimeZone();
  const [params, setParams] = useQueryStates({
    view: parseAsStringLiteral(VIEWS).withDefault('month'),
    date: parseAsString
  });

  const focusedDate = useMemo(
    () => (timeZone ? (parseDay(params.date) ?? today(timeZone)) : null),
    [params.date, timeZone]
  );

  const events = useMemo<CalendarEvent<Post>[]>(() => {
    const phase2 = snapshot.data?.state.phase2;
    if (!phase2 || !timeZone) return [];
    const out: CalendarEvent<Post>[] = [];
    const add = (id: string, kind: Kind, manifest: Manifest, cancelRequested = false) => {
      const at = new Date(manifest.timing.utc);
      if (Number.isNaN(at.getTime())) return;
      const firstLine = manifest.payload.text.split('\n').find((line) => line.trim())?.trim();
      out.push({
        id,
        title: firstLine || `${manifest.platform} post`,
        start: fromDate(at, timeZone),
        color: KIND_META[kind].color,
        status: `${manifest.platform}, ${KIND_META[kind].label}`,
        icon: <ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />,
        data: {
          kind,
          platform: manifest.platform,
          account: manifest.account,
          text: manifest.payload.text,
          at,
          approvedZone: manifest.timing.timeZone,
          cancelRequested,
          manifest
        }
      });
    };
    for (const review of phase2.reviews) {
      if (review.status === 'needs_review') add(`r-${review.id}`, 'review', review.manifest);
    }
    for (const job of phase2.jobs) add(`j-${job.id}`, kindOf(job.state), job.manifest, job.cancelRequested);
    return out;
  }, [snapshot.data, timeZone]);

  return (
    <PageContainer pageTitle='Calendar' pageDescription='Approved and pending publications at their exact times.' infoContent={infoContent}>
      {snapshot.isPending || !timeZone || !focusedDate ? (
        <Skeleton className='h-[40rem] w-full rounded-xl' />
      ) : (
        <div className='flex flex-col gap-3'>
          <Calendar
            events={events}
            view={params.view}
            onViewChange={(view) => void setParams({ view: view === 'month' ? null : view })}
            focusedDate={focusedDate}
            // Today stays out of the address, so a bookmarked calendar always opens on the current day.
            onFocusedDateChange={(date) => void setParams({ date: isToday(date, timeZone) ? null : date.toString() })}
            timeZone={timeZone}
            noun={NOUN}
            headerAction={
              <Link href='/app' className={buttonVariants()}>
                <Icons.add />
                New post
              </Link>
            }
            renderEventDetails={(event, context) => <PostDetails event={event} context={context} timeZone={timeZone} />}
            dayPanelFooter={
              <Link href='/app/queue' className={cn('t-learn self-start', buttonVariants({ variant: 'ghost', size: 'sm' }), '-ml-2.5')}>
                Open the queue <LearnMoreChevron />
              </Link>
            }
          />
          <ul aria-label='Legend' className='text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs'>
            {(Object.keys(KIND_META) as Kind[]).map((kind) => (
              <li key={kind} className='flex items-center gap-1.5'>
                <span aria-hidden className={cn('size-2 rounded-full', EVENT_COLORS[KIND_META[kind].color].dot)} />
                {KIND_META[kind].label}
              </li>
            ))}
          </ul>
        </div>
      )}
    </PageContainer>
  );
}
