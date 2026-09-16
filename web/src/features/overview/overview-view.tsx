'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StatCard } from '@/components/app/stat-card';
import { LevelBadge } from '@/components/app/level-badge';
import { GettingStarted } from './getting-started';
import { ChannelIcon } from '@/components/channel-icon';
import { HeatCalendar } from '@/components/charts/heat-calendar';
import { addDays, GAP, mondayOf, PITCH, startOfDay } from '@/components/charts/heat-calendar/utils';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { useAudit, useChannels, useSnapshot, useUsage } from '@/lib/api/hooks';
import type { Job } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { daysUntil, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';

const PRE_FLIGHT = new Set(['scheduled', 'approved', 'claimed']);
const IN_FLIGHT = new Set(['submitting', 'provider_accepted', 'uncertain']);
const DONE = new Set(['published', 'verified']);
const NEEDS_RECONNECT = new Set(['token_expired', 'reauthorization_required', 'scope_missing']);

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
    }
  ]
};

interface Attention {
  /** Stable across count changes, so an entry updates in place instead of leaving and re-entering. */
  id: string;
  tone: 'warning' | 'info';
  title: string;
  description: string;
  href: string;
  action: string;
}

const DAY_MS = 86_400_000;
const MIN_WEEKS = 8;
const MAX_WEEKS = 26;

/**
 * Provider-confirmed posts per UTC day, dated by the verification receipt (or the job's last event)
 * and bucketed against the calendar's own grid start. As many weeks as fit the card at full cell
 * size, up to half a year. `jobs` is null when the snapshot could not be read.
 */
function PublishingActivity({ jobs, pending }: { jobs: Job[] | null; pending: boolean }) {
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
    <Card className='lg:col-span-7'>
      <CardHeader>
        <CardTitle>Publishing activity</CardTitle>
        <CardDescription>
          {!activity
            ? 'Posts the provider confirmed, by day.'
            : activity.total === 0
              ? 'Posts the provider confirmed, by day. None in this range yet; each confirmed post fills its day.'
              : `Posts the provider confirmed, by day: ${activity.total} in this range. Hover a day; click two days to total the span.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div ref={measureRef} className='w-full'>
          {unavailable ? (
            <p className='text-muted-foreground text-sm'>Publishing activity is unavailable right now.</p>
          ) : !activity ? (
            <Skeleton className='h-44 w-full' />
          ) : (
            <HeatCalendar
              unit='posts'
              weeks={activity.weeks}
              maxCount={activity.maxCount}
              values={activity.values}
              endDate={activity.end}
              color='var(--primary)'
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function OverviewView() {
  const snapshot = useSnapshot();
  const usage = useUsage();
  const channels = useChannels();
  const audit = useAudit();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  const now = Date.now() / 1000;

  const jobs = snapshot.data?.state.phase2?.jobs ?? [];
  const reviews = snapshot.data?.state.phase2?.reviews ?? [];
  const scheduled = jobs.filter((j) => PRE_FLIGHT.has(j.state) || IN_FLIGHT.has(j.state)).length;
  const publishedRecently = jobs.filter((j) => {
    if (!DONE.has(j.state)) return false;
    const at = j.verification?.at ?? j.events[j.events.length - 1]?.at ?? 0;
    return at > now - 30 * 86400;
  }).length;
  const needsReview = reviews.filter((r) => r.status === 'needs_review').length;

  const connected = channels.data?.channels ?? [];
  const providers = channels.data?.providers ?? [];
  const directPublish = connected.filter((c) => c.capabilities.publish?.level === 'Direct').length;

  const entitlement = usage.data?.entitlement;
  const subscription = usage.data?.subscription;
  const lifecycle = usage.data?.lifecycle;
  const trialDays = subscription?.status === 'trial' ? daysUntil(entitlement?.resetsAt) : null;

  const attention: Attention[] = [];
  if (!snapshot.isLoading && snapshot.data && !snapshot.data.state.speaker?.activeRevision) {
    attention.push({
      id: 'voice',
      tone: 'info',
      title: 'Set up your voice',
      description: 'Two minutes: what you are building, who it is for, and a tone. Drafts can only be scheduled against an active voice profile.',
      href: '/app/workspace/brand',
      action: 'Set up'
    });
  }
  if (lifecycle?.status === 'past_due') {
    attention.push({
      id: 'past-due',
      tone: 'warning',
      title: 'Payment failed',
      description: 'Publishing stays on during the grace period. Update your payment method to keep it that way.',
      href: '/app/account/billing',
      action: 'Fix billing'
    });
  }
  for (const channel of connected) {
    if (NEEDS_RECONNECT.has(channel.connectionState)) {
      attention.push({
        id: `reconnect-${channel.id}`,
        tone: 'warning',
        title: `Reconnect ${channel.platform}`,
        description: `${channel.account}: ${channel.connectionState.replace(/_/g, ' ')}. Scheduled posts for this account will wait.`,
        href: '/app/channels',
        action: 'Open channels'
      });
    }
  }
  if (needsReview > 0) {
    attention.push({
      id: 'approvals',
      tone: 'info',
      title: `${needsReview} draft${needsReview === 1 ? '' : 's'} waiting for approval`,
      description: 'Nothing publishes until you approve the exact text, media and time.',
      href: '/app/queue',
      action: 'Review now'
    });
  }
  if (trialDays !== null && trialDays <= 5) {
    attention.push({
      id: 'trial',
      tone: 'info',
      title: trialDays > 0 ? `Trial ends in ${trialDays} day${trialDays === 1 ? '' : 's'}` : 'Trial has ended',
      description: 'Your drafts stay readable and exportable either way. Choose a plan to keep publishing.',
      href: '/app/account/billing',
      action: 'See plans'
    });
  }
  const unreviewed = providers.filter((p) => !p.productionReviewed && connected.some((c) => c.platform === p.platform));
  if (unreviewed.length) {
    attention.push({
      id: 'export-only',
      tone: 'info',
      title: `${unreviewed.map((p) => p.platform).join(', ')}: publish is export-only for now`,
      description: 'Provider review is in progress. Until it passes, PostRiff prepares each post and you complete the final step.',
      href: '/app/channels',
      action: 'Details'
    });
  }
  if (!channels.isLoading && connected.length === 0) {
    attention.push({
      id: 'first-channel',
      tone: 'info',
      title: 'Connect your first channel',
      description: 'Drafts can be written and exported now; connecting an account lets you schedule and publish.',
      href: '/app/channels',
      action: 'Connect'
    });
  }

  const events = audit.data?.events ?? [];
  const canEdit = checkAccess(access, { permission: 'edit' });

  return (
    <PageContainer
      pageTitle='Overview'
      pageDescription='What is scheduled, what needs you, and how much of your plan is left.'
      infoContent={infoContent}
      pageHeaderAction={
        canEdit ? (
          <Link href='/app/ideas?new=1' className={buttonVariants()}>
            <Icons.sparkles className='size-4' /> New idea
          </Link>
        ) : undefined
      }
    >
      <div className='flex flex-1 flex-col gap-4'>
        <GettingStarted />
        <div className='*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs md:grid-cols-2 lg:grid-cols-4'>
          <StatCard
            label='Scheduled'
            value={scheduled}
            loading={snapshot.isLoading}
            hint={scheduled ? 'Waiting for the approved time' : 'Nothing in the queue'}
            footer='Approved posts the worker will publish'
          />
          <StatCard
            label='Published · 30 days'
            value={publishedRecently}
            loading={snapshot.isLoading}
            hint={publishedRecently ? 'Confirmed by the provider' : 'No publications yet'}
            footer='Only receipts the provider confirmed count'
          />
          <StatCard
            label='Writing batches left'
            value={entitlement ? entitlement.writingBatchesRemaining : '—'}
            loading={usage.isLoading}
            badge={subscription ? subscription.label : undefined}
            hint={
              entitlement?.resetsAt
                ? `Resets ${relativeTime(entitlement.resetsAt, now)}`
                : 'Stops at the limit, never overcharges'
            }
            footer={usage.data?.overage === 'stop' ? 'Overage: stop — nothing is charged silently' : undefined}
          />
          <StatCard
            label='Connected channels'
            value={connected.length}
            loading={channels.isLoading}
            hint={
              connected.length
                ? `${directPublish} direct · ${connected.length - directPublish} assisted`
                : 'Connect an account to schedule'
            }
            footer={entitlement ? `Plan allows ${entitlement.connectedAccounts}` : undefined}
          />
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-7'>
          <Card className='lg:col-span-4'>
            <CardHeader>
              <CardTitle>Needs your attention</CardTitle>
              <CardDescription>Things only you can decide. Empty is good.</CardDescription>
            </CardHeader>
            <CardContent className='relative flex flex-col gap-3'>
              {snapshot.isLoading || channels.isLoading ? (
                <>
                  <Skeleton className='h-16 w-full' />
                  <Skeleton className='h-16 w-full' />
                </>
              ) : (
                // Entries arriving or resolved while the page is open slide in and out; the rest glide into place.
                <AnimatePresence initial={false} mode='popLayout'>
                  {attention.length === 0 ? (
                    <motion.div
                      key='all-clear'
                      initial={reduce ? false : { opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={reduce ? { duration: 0 } : { duration: 0.2, ease: EASE_OUT }}
                    >
                      <Empty className='border-0 py-8'>
                        <EmptyHeader>
                          <EmptyMedia variant='icon'>
                            <Icons.circleCheck />
                          </EmptyMedia>
                          <EmptyTitle>All clear</EmptyTitle>
                          <EmptyDescription>No approvals waiting and every connection is healthy.</EmptyDescription>
                        </EmptyHeader>
                      </Empty>
                    </motion.div>
                  ) : (
                    attention.map((item) => (
                      <motion.div
                        key={item.id}
                        layout={reduce ? false : 'position'}
                        initial={reduce ? false : { opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={reduce ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, y: -4, transition: { duration: 0.16, ease: EASE_OUT } }}
                        transition={reduce ? { duration: 0 } : { opacity: { duration: 0.2, ease: EASE_OUT }, y: SPRING_LAYOUT, layout: SPRING_LAYOUT }}
                      >
                        <Alert variant={item.tone === 'warning' ? 'destructive' : 'default'}>
                          {item.tone === 'warning' ? <Icons.warning className='size-4' /> : <Icons.info className='size-4' />}
                          <AlertTitle>{item.title}</AlertTitle>
                          <AlertDescription className='flex flex-col gap-2'>
                            <span>{item.description}</span>
                            <Link href={item.href} className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'w-fit')}>
                              {item.action}
                            </Link>
                          </AlertDescription>
                        </Alert>
                      </motion.div>
                    ))
                  )}
                </AnimatePresence>
              )}
            </CardContent>
          </Card>

          <Card className='lg:col-span-3'>
            <CardHeader>
              <CardTitle>Channels</CardTitle>
              <CardDescription>What each connection can really do today.</CardDescription>
            </CardHeader>
            <CardContent className='flex flex-col gap-3'>
              {channels.isLoading ? (
                <Skeleton className='h-24 w-full' />
              ) : connected.length === 0 ? (
                <p className='text-muted-foreground text-sm'>No channels connected yet.</p>
              ) : (
                connected.map((channel) => (
                  <div key={channel.id} className='flex items-center justify-between gap-3 rounded-lg border p-3'>
                    <div className='flex min-w-0 items-center gap-2'>
                      <ChannelIcon platform={channel.platform} name={channel.platform} />
                      <div className='min-w-0'>
                      <p className='truncate text-sm font-medium'>{channel.platform}</p>
                      <p className='text-muted-foreground truncate text-xs'>{channel.account}</p>
                      </div>
                    </div>
                    <div className='flex shrink-0 items-center gap-1.5'>
                      <span className='text-muted-foreground text-xs'>publish</span>
                      <LevelBadge level={channel.capabilities.publish?.level} />
                    </div>
                  </div>
                ))
              )}
              <Link href='/app/channels' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), 'w-fit')}>
                Manage channels <LearnMoreChevron />
              </Link>
            </CardContent>
          </Card>

          <PublishingActivity jobs={snapshot.data ? jobs : null} pending={snapshot.isPending} />

          <Card className='lg:col-span-7'>
            <CardHeader>
              <CardTitle>Recent activity</CardTitle>
              <CardDescription>Content-free audit trail of what happened in this workspace.</CardDescription>
            </CardHeader>
            <CardContent>
              {audit.isLoading ? (
                <Skeleton className='h-32 w-full' />
              ) : events.length === 0 ? (
                <p className='text-muted-foreground text-sm'>No activity recorded yet.</p>
              ) : (
                <ul className='divide-y'>
                  {events.slice(0, 8).map((event, index) => (
                    <li key={`${event.kind}-${event.at}-${index}`} className='flex items-center justify-between gap-3 py-2 text-sm'>
                      <span className='font-medium'>{event.kind.replace(/[._]/g, ' ')}</span>
                      <span className='text-muted-foreground text-xs'>{relativeTime(event.at, now)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <Link href='/app/workspace/audit' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), 'mt-2 w-fit')}>
                Full audit log <LearnMoreChevron />
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  );
}
