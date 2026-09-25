'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { GettingStarted } from './getting-started';
import { CoworkerAttention } from '@/features/coworker/attention-panel';
import { HeatCalendar } from '@/components/charts/heat-calendar';
import { addDays, GAP, mondayOf, PITCH, startOfDay } from '@/components/charts/heat-calendar/utils';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Panel, StatTile, StatusChip } from '@/features/workspace/rafii-parts';
import { useChannels, useSnapshot, useUsage } from '@/lib/api/hooks';
import type { Job } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { deriveAttention, type AttentionItem, type AttentionSource } from '@/lib/attention';
import { ChannelsCard, publishCounts } from './channels-card';
import { NextUp } from './next-up';
import { RecentActivity } from './recent-activity';
import { RetryButton, type Refetchable } from './retry';
import { whoCanAct } from './who-can-act';

import { WAITING as PRE_FLIGHT, IN_FLIGHT, DONE } from '@/lib/jobs';

const infoContent = {
  title: 'How the overview counts',
  sections: [
    {
      title: 'Honest numbers only',
      description:
        'Every figure here comes from your workspace ledger and publishing receipts. “Unavailable” is never shown as zero.'
    },
    {
      title: 'Direct · Assisted · Local',
      description:
        'Direct publishes through a reviewed provider API. Assisted means PostRiff prepares the post and you (or the desktop companion) finish it. Local runs through the companion on your own machine.'
    },
    {
      title: 'Nothing publishes without you',
      description: 'Scheduled items only leave the queue after an exact approval of the text, media and time.'
    },
    {
      title: 'What Next up counts',
      description:
        'Only approved jobs with a time the worker can read appear there, in your time zone. Drafts waiting for approval are listed under attention instead.'
    }
  ]
};

const SOURCE_NAMES: Record<AttentionSource, string> = {
  workspace: 'the workspace',
  channels: 'channels',
  plan: 'your plan'
};

/** "a", "a and b", "a, b and c". */
function listOf(names: string[]) {
  return names.length < 2 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}

const DAY_MS = 86_400_000;
const MIN_WEEKS = 8;
const MAX_WEEKS = 26;

/**
 * Provider-confirmed posts per UTC day, dated by the verification receipt (or the job's last event)
 * and bucketed against the calendar's own grid start. As many weeks as fit the panel at full cell
 * size, up to half a year. `jobs` is null when the snapshot could not be read.
 */
function PublishingActivity({ jobs, pending, className }: { jobs: Job[] | null; pending: boolean; className?: string }) {
  const measureRef = useRef<HTMLDivElement>(null);
  const [weeks, setWeeks] = useState<number | null>(null);
  // Read after mount, like the calendar's own "today", so the server and client render the same markup.
  const [today, setToday] = useState<Date | null>(null);

  useEffect(() => {
    const el = measureRef.current;
    if (!el) return;
    setToday(startOfDay(new Date()));
    const measure = () => setWeeks(Math.min(MAX_WEEKS, Math.max(MIN_WEEKS, Math.floor((el.clientWidth + GAP) / PITCH))));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const activity = useMemo(() => {
    if (!jobs || weeks === null || today === null) return null;
    const start = addDays(mondayOf(today), -(weeks - 1) * 7);
    const lastDay = Math.round((today.getTime() - start.getTime()) / DAY_MS);
    const counts = Array.from({ length: weeks }, () => [0, 0, 0, 0, 0, 0, 0]);
    let total = 0;
    for (const job of jobs) {
      if (!DONE.has(job.state)) continue;
      const at = job.verification?.at ?? job.events[job.events.length - 1]?.at;
      if (!at) continue;
      const day = Math.floor((at * 1000 - start.getTime()) / DAY_MS);
      if (day < 0 || day > lastDay) continue;
      counts[Math.floor(day / 7)][day % 7] += 1;
      total += 1;
    }
    // A cell reads round(intensity × maxCount), so count / maxCount gives back the exact count.
    const maxCount = Math.max(1, ...counts.flat());
    return { weeks, end: today, total, maxCount, values: counts.map((week) => week.map((count) => count / maxCount)) };
  }, [jobs, weeks, today]);

  const unavailable = !pending && jobs === null;

  return (
    <Panel
      className={className}
      title='Publishing activity'
      titleId='overview-activity-heading'
      description={
        !activity
          ? 'Posts the provider confirmed, by day.'
          : activity.total === 0
            ? 'Posts the provider confirmed, by day. None in this range yet; each confirmed post fills its day.'
            : `Posts the provider confirmed, by day: ${activity.total} in this range. Hover a day; click two days to total the span.`
      }
    >
      <div ref={measureRef} className='w-full'>
        {unavailable ? (
          <StateMessage kind='error' layout='inline' title='Publishing activity is unavailable right now.' />
        ) : !activity ? (
          <Skeleton className='h-44 w-full rounded-[var(--rafii-radius-control)]' />
        ) : (
          <HeatCalendar unit='posts' weeks={activity.weeks} maxCount={activity.maxCount} values={activity.values} endDate={activity.end} color='var(--foreground)' />
        )}
      </div>
    </Panel>
  );
}

/** A stat whose query failed: the word, never a zero, and a Retry where the footer would be. */
function unavailableStat(message: string, query: Refetchable) {
  return {
    value: 'Unavailable',
    hint: <span className='text-muted-foreground font-normal'>{message}</span>,
    footer: <RetryButton queries={[query]} />
  };
}

/** One attention item as an object: what, why, who can act, and its one action (DNA §21.17). */
function AttentionRow({ item, canAct }: { item: AttentionItem; canAct: boolean | null }) {
  const who = whoCanAct(item);
  return (
    <div role='listitem' data-attention-id={item.id} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4'>
      <div className='flex items-start gap-3'>
        <span aria-hidden className={cn('mt-0.5 flex shrink-0 items-center', item.tone === 'warning' ? 'text-foreground' : 'text-muted-foreground')}>
          {item.tone === 'warning' ? <Icons.warning className='size-4' /> : <Icons.info className='size-4' />}
        </span>
        <div className='flex min-w-0 flex-1 flex-col gap-1'>
          <p className='text-foreground text-sm font-medium text-balance'>
            {item.tone === 'warning' && <span className='sr-only'>Needs attention: </span>}
            {item.title}
          </p>
          <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{item.description}</p>
          {who && (
            <p className='text-muted-foreground text-xs'>
              Needs {who.label}
              {canAct === null ? '' : canAct ? ' · you can do this' : ' · ask an owner or admin'}
            </p>
          )}
        </div>
      </div>
      <Link href={item.href} className={cn(buttonVariants({ variant: 'glass', size: 'default' }), 'w-fit')}>
        {item.action}
      </Link>
    </div>
  );
}

export function OverviewView() {
  const snapshot = useSnapshot();
  const usage = useUsage();
  const channels = useChannels();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  const now = Date.now() / 1000;

  const jobs = snapshot.data?.state.phase2?.jobs ?? [];
  const waiting = jobs.filter((j) => PRE_FLIGHT.has(j.state)).length;
  const sending = jobs.filter((j) => IN_FLIGHT.has(j.state)).length;
  const scheduled = waiting + sending;
  let verified = 0;
  for (const job of jobs) {
    if (!DONE.has(job.state)) continue;
    const at = job.verification?.at ?? job.events[job.events.length - 1]?.at ?? 0;
    if (at <= now - 30 * 86400) continue;
    verified += 1;
  }
  const publishedRecently = verified;

  const counts = publishCounts(channels.data?.channels ?? []);

  const entitlement = usage.data?.entitlement;
  const subscription = usage.data?.subscription;

  const attention = deriveAttention({ snapshot, channels, usage, now });
  const failedQueries = [snapshot.isError ? snapshot : null, channels.isError ? channels : null, usage.isError ? usage : null].filter(
    (query): query is NonNullable<typeof query> => query !== null
  );

  const canEdit = checkAccess(access, { permission: 'edit' });
  // Sample workspaces refuse every change on the API (`hosted.py`), so creation says so up front.
  const sample = snapshot.data?.state.workspace?.sample === true;

  const scheduledStat = snapshot.isError
    ? unavailableStat('Could not read the workspace', snapshot)
    : {
        value: scheduled,
        hint: scheduled ? `${waiting} waiting · ${sending} sending now` : 'Nothing in the queue',
        footer: 'Approved posts the worker will publish'
      };
  const publishedStat = snapshot.isError
    ? unavailableStat('Could not read the workspace', snapshot)
    : {
        value: publishedRecently,
        hint: publishedRecently ? `${verified} verified` : 'No verified publications yet',
        footer: 'Confirmed by the provider; unverified jobs remain in sending'
      };
  const batchesStat = usage.isError
    ? unavailableStat('Could not read your plan', usage)
    : {
        value: entitlement ? entitlement.writingBatchesRemaining : '—',
        hint: entitlement?.resetsAt ? `Resets ${relativeTime(entitlement.resetsAt, now)}` : 'Stops at the limit, never overcharges',
        footer: usage.data?.overage === 'stop' ? 'Overage: stop — nothing is charged silently' : undefined
      };
  const channelsStat = channels.isError
    ? unavailableStat('Could not read channels', channels)
    : {
        value: counts.connected,
        hint: counts.connected ? `${counts.direct} Direct · ${counts.assisted} Assisted · ${counts.local} Local` : 'Connect an account to schedule',
        footer: entitlement ? `Plan allows ${entitlement.connectedAccounts}` : undefined
      };

  const newIdea = !canEdit ? undefined : sample ? (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button variant='action' size='control' focusableWhenDisabled disabled className='aria-disabled:opacity-50'>
            <Icons.sparkles className='size-4' /> New idea
          </Button>
        }
      />
      <TooltipContent>Sample workspace is read-only</TooltipContent>
    </Tooltip>
  ) : (
    <Link href='/app/ideas?new=1' data-tour='overview-new-idea' className={buttonVariants({ variant: 'action', size: 'control' })}>
      <Icons.sparkles className='size-4' /> New idea
    </Link>
  );

  const attentionPending = snapshot.isPending || channels.isPending;
  const allClear = attention.items.length === 0 && attention.unavailable.length === 0;
  const enter = reduce ? false : { opacity: 0, y: 8 };
  const exit = reduce ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, y: -4, transition: { duration: 0.16, ease: EASE_OUT } };
  const move = reduce ? { duration: 0 } : { opacity: { duration: 0.2, ease: EASE_OUT }, y: SPRING_LAYOUT, layout: SPRING_LAYOUT };

  return (
    <PageContainer pageTitle='Overview' pageDescription='What is scheduled, what needs you, and how much of your plan is left.' infoContent={infoContent} pageHeaderAction={newIdea}>
      <div className='flex flex-1 flex-col gap-4 md:gap-5'>
        <GettingStarted />
        <CoworkerAttention />
        <div data-tour='overview-stats' className='grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-4 lg:grid-cols-4'>
          <StatTile label='Scheduled' loading={snapshot.isPending} {...scheduledStat} />
          <StatTile label='Published · 30 days' loading={snapshot.isPending} {...publishedStat} />
          <StatTile
            label='Writing batches left'
            loading={usage.isPending}
            badge={!usage.isError && subscription ? <StatusChip icon={null}>{subscription.label}</StatusChip> : undefined}
            {...batchesStat}
          />
          <StatTile label='Connected channels' loading={channels.isPending} {...channelsStat} />
        </div>

        <div className='grid grid-cols-1 gap-4 md:gap-5 lg:grid-cols-7'>
          <NextUp className='lg:col-span-4' />

          <Panel data-tour='overview-attention' className='lg:col-span-3' title='Needs your attention' titleId='overview-attention-heading' description='Things only you can decide. Empty is good.'>
            {attentionPending ? (
              <StateMessage kind='loading' title='Checking what needs you…' />
            ) : (
              // Entries arriving or resolved while the page is open slide in and out; the rest glide into place.
              <div role='list' aria-label='Needs your attention' className='relative flex flex-col gap-2'>
                <AnimatePresence initial={false} mode='popLayout'>
                  {allClear ? (
                    <motion.div key='all-clear' role='listitem' initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={reduce ? { duration: 0 } : { duration: 0.2, ease: EASE_OUT }}>
                      <StateMessage kind='success' title='All clear' description='No approvals waiting and every connection is healthy.' />
                    </motion.div>
                  ) : (
                    [
                      attention.unavailable.length > 0 && (
                        <motion.div key='unavailable' role='listitem' layout={reduce ? false : 'position'} initial={enter} animate={{ opacity: 1, y: 0 }} exit={exit} transition={move}>
                          <div data-attention-id='unavailable' className='rafii-quiet rounded-[var(--rafii-radius-control)] px-4 py-3'>
                            <StateMessage
                              kind='partial'
                              layout='inline'
                              title='Could not read part of the workspace'
                              description={`Some reminders may be missing: ${listOf(attention.unavailable.map((source) => SOURCE_NAMES[source]))} could not be read.`}
                              action={<RetryButton queries={failedQueries} />}
                            />
                          </div>
                        </motion.div>
                      ),
                      ...attention.items.map((item) => {
                        const who = whoCanAct(item);
                        return (
                          <motion.div key={item.id} layout={reduce ? false : 'position'} initial={enter} animate={{ opacity: 1, y: 0 }} exit={exit} transition={move}>
                            <AttentionRow item={item} canAct={who ? checkAccess(access, { permission: who.permission }) : null} />
                          </motion.div>
                        );
                      })
                    ]
                  )}
                </AnimatePresence>
              </div>
            )}
          </Panel>

          <PublishingActivity className='lg:col-span-4' jobs={snapshot.data && !snapshot.isError ? jobs : null} pending={snapshot.isPending} />

          <ChannelsCard className='lg:col-span-3' />

          <RecentActivity className='lg:col-span-7' />
        </div>
      </div>
    </PageContainer>
  );
}
