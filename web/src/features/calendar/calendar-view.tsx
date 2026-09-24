'use client';

import { useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { fromDate, isToday, parseDate, toCalendarDate, today, type CalendarDate } from '@internationalized/date';
import { parseAsArrayOf, parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { Calendar, useLocalTimeZone } from '@/components/application/calendar/calendar';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import {
  DEFAULT_FIRST_DAY_OF_WEEK,
  DEFAULT_LOCALE,
  type CalendarDetailsContext,
  type CalendarEvent
} from '@/components/application/calendar/config';
import { visibleRange } from '@/components/application/calendar/utils';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import PageContainer from '@/components/layout/page-container';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { LoadingButton } from '@/components/ui/loading-button';
import { Skeleton } from '@/components/ui/skeleton';
import { ScheduleDialog } from '@/features/queue/schedule-dialog';
import { StatusChip } from '@/features/queue/status-chip';
import { ApiError } from '@/lib/api/client';
import { useSnapshot } from '@/lib/api/hooks';
import type { Job, Manifest } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { cn } from '@/lib/utils';
import { CalendarFilters, type ChannelOption } from './calendar-filters';
import { jobKind, KIND_META, KINDS, reviewExpired, reviewKind, type Kind } from './calendar-kinds';
import { useLiveSnapshotRefresh, useMinWidth, useNowSeconds } from './use-calendar-live';

interface Post {
  kind: Kind;
  platform: string;
  account: string;
  /** Which account filter the post belongs to (`ChannelOption.key`). */
  channelKey: string;
  text: string;
  at: Date;
  /** The zone the time was approved in. */
  approvedZone: string;
  cancelRequested: boolean;
  manifest: Manifest;
  job?: Job;
}

const VIEWS = ['month', 'week', 'day'] as const;

const NOUN = { one: 'post', other: 'posts' };

/** Kinds that will not go out as they are: the way forward is a new review of the draft. */
const NEEDS_NEW_REVIEW = new Set<Kind>(['expired', 'stale', 'held', 'failed']);

const FINAL = new Set<Kind>(['verified', 'failed', 'canceled']);

const infoContent = {
  title: 'Calendar',
  sections: [
    {
      title: 'What shows here',
      description:
        'Reviews and publishing jobs, each at its approved time in your time zone. A review that expired or went out of date, and a job the worker held, stay visible with their own state, so nothing disappears quietly.'
    },
    {
      title: 'States and filters',
      description:
        'Each entry names its state beside its title. The chips above the calendar count the posts in the period on screen; choose one to show only those, and the address keeps the filter for a bookmark.'
    },
    {
      title: 'Month, week and day',
      description: 'Month shows the shape of the month; week and day place each post on the hour it goes out. Choose a date or "+N more" to open that day.'
    },
    {
      title: 'Moving a post',
      description: 'Timing is part of the exact approval. To change it, prepare the draft again with the new time from Queue → Drafts.'
    }
  ]
};

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

/** Why an entry stands where it does, from the snapshot's own words where it has them. */
function StatusNotes({ post, timeZone, context }: { post: Post; timeZone: string; context: CalendarDetailsContext }) {
  const clamp = context === 'list' && 'line-clamp-2';
  const lastEvent = post.job?.events?.at(-1);
  const notes: ReactNode[] = [];

  if (post.kind === 'expired') {
    const closed = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(new Date(post.manifest.expiresAt * 1000));
    notes.push(`Not approved in time: its approval window closed on ${closed}, so it will not go out. Schedule the draft again for a new time.`);
  }
  if (post.kind === 'stale') {
    notes.push(
      'Something it was checked against changed after it was prepared (the draft, the account, the voice profile or a source), so it can no longer be approved. Schedule the draft again.'
    );
  }
  if ((['held', 'failed', 'in-flight', 'processing', 'accepted', 'uncertain', 'unknown'].includes(post.kind)) && lastEvent?.message) notes.push(lastEvent.message);
  // `nextAction` is written after a worker attempt; a job held later by an approval check keeps the older
  // wording, so held jobs rely on the message written with the hold itself.
  if ((['failed', 'in-flight', 'processing', 'accepted', 'uncertain'].includes(post.kind)) && post.job?.nextAction) {
    notes.push(
      <>
        <span className='text-foreground font-medium'>Next:</span> {post.job.nextAction}
      </>
    );
  }
  if (post.kind === 'assisted') notes.push('Finish the handoff in the destination app. Opening the app does not confirm publication.');
  if (post.kind === 'manual') notes.push('This is your report of completion; it has not been verified by the provider API.');
  if (post.manifest.execution === 'synthetic') notes.push('Local fixture only; no real publication was performed.');
  if (post.kind === 'uncertain') notes.push('Check the platform and the queue receipt. Do not publish again while the result is unconfirmed.');
  if (post.kind === 'unknown') notes.push('Automatic progress cannot be confirmed. Open the queue receipt for the latest events.');
  if (post.kind === 'held') notes.push('Resolve the reason above, then prepare a new exact review from Queue → Drafts.');
  if (post.kind === 'verified' && post.job?.providerReference) {
    notes.push(
      <>
        Receipt: <span className='font-mono break-all'>{post.job.providerReference}</span>
      </>
    );
  }
  if (post.cancelRequested && !FINAL.has(post.kind)) notes.push('Cancel requested');

  if (notes.length === 0) return null;
  return (
    <div className='text-muted-foreground flex flex-col gap-1 text-xs'>
      {notes.map((note, index) => (
        <p key={index} className={cn(clamp)}>
          {note}
        </p>
      ))}
    </div>
  );
}

function PostDetails({ event, context, timeZone, wide }: { event: CalendarEvent<Post>; context: CalendarDetailsContext; timeZone: string; wide: boolean }) {
  const post = event.data;
  if (!post) return null;
  const meta = KIND_META[post.kind];
  const when = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(post.at);
  // The approving zone's clock, only when it reads differently from this one (another name for the same offset adds nothing).
  const approvedTime = post.approvedZone && post.approvedZone !== timeZone ? zoneTime(post.at, post.approvedZone) : null;
  const approvedElsewhere = approvedTime && approvedTime !== zoneTime(post.at, timeZone) ? approvedTime : null;
  const next = NEEDS_NEW_REVIEW.has(post.kind) ? { href: '/app/queue?view=drafts', label: 'Open drafts' } : { href: post.job ? `/app/queue?job=${encodeURIComponent(post.job.id)}` : '/app/queue', label: 'Open the queue' };

  const details = (
    <div className={cn('flex min-w-0 flex-col gap-2', context === 'popover' && 'w-72 max-w-full shrink-0')}>
      <div className='flex items-center justify-between gap-2'>
        <span className='flex min-w-0 items-center gap-2 font-medium'>
          <ChannelIcon platform={post.platform} name={post.platform} size='xs' />
          <span className='truncate'>{post.platform}</span>
        </span>
        <StatusChip tone={meta.status} contentKey={post.kind}>
          {meta.label}
        </StatusChip>
      </div>
      <p className='text-muted-foreground text-xs'>
        {post.account} · {when}
        {approvedElsewhere && ` (${approvedElsewhere} ${post.approvedZone})`}
      </p>
      <StatusNotes post={post} timeZone={timeZone} context={context} />
      <p className={cn('text-xs whitespace-pre-line', context === 'popover' ? 'line-clamp-5' : 'line-clamp-3')}>{post.text}</p>
      {context === 'popover' && (
        <Link
          href={next.href}
          className={cn(
            't-learn',
            buttonVariants({ variant: 'quiet', size: 'sm' }),
            // A full-width 44px touch target on phones; the quiet "learn more" link beside the preview on wider screens.
            'rafii-quiet h-11 w-full justify-center text-xs sm:-ml-2.5 sm:h-8 sm:w-auto sm:self-start sm:bg-transparent'
          )}
        >
          {next.label} <LearnMoreChevron />
        </Link>
      )}
    </div>
  );

  if (context !== 'popover') return details;
  return (
    <div className='flex max-h-[calc(var(--available-height,100vh)-1rem)] flex-col gap-4 overflow-y-auto sm:flex-row sm:items-start'>
      {details}
      <ManifestPreview
        manifest={post.manifest}
        timeZone={timeZone}
        scale={wide ? undefined : 0.5}
        className='pt-3 sm:pt-0 sm:pl-4'
      />
    </div>
  );
}

/** The calendar's outline while the snapshot loads: the chip row, the header and a month of quiet cells. */
function CalendarSkeleton() {
  return (
    <div aria-busy='true' className='flex flex-col gap-4'>
      <span className='sr-only'>Loading the calendar</span>
      <div className='flex gap-1.5 p-1'>
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className='h-9 w-24 rounded-full' />
        ))}
      </div>
      <div className='flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between'>
        <div className='flex items-center gap-3'>
          <Skeleton className='hidden size-14 rounded-[var(--rafii-radius-control)] sm:block' />
          <div className='flex flex-col gap-2'>
            <Skeleton className='h-5 w-40' />
            <Skeleton className='h-4 w-56' />
          </div>
        </div>
        <Skeleton className='h-11 w-full max-w-md rounded-[var(--rafii-radius-segment)]' />
      </div>
      <div className='grid grid-cols-7 gap-1'>
        {Array.from({ length: 35 }, (_, index) => (
          <div key={index} className='rafii-quiet min-h-[5.5rem] rounded-[0.625rem] p-1.5 md:min-h-[8.5rem] md:p-2'>
            <Skeleton className='size-7 rounded-full' />
          </div>
        ))}
      </div>
    </div>
  );
}

function errorMessage(error: unknown) {
  return error instanceof ApiError && error.message ? error.message : 'The workspace could not be read.';
}

export function CalendarView() {
  const snapshot = useSnapshot();
  const timeZone = useLocalTimeZone();
  const nowSeconds = useNowSeconds();
  const wide = useMinWidth(640);
  const access = useWorkspaceAccess();
  // Preparing a review is an approve-class action on the server (`permissions.py`).
  const canSchedule = checkAccess(access, { permission: 'approve' });
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canConnect = checkAccess(access, { permission: 'manage_connections' });
  const [scheduling, setScheduling] = useState(false);
  const [params, setParams] = useQueryStates({
    view: parseAsStringLiteral(VIEWS).withDefault('month'),
    date: parseAsString,
    kind: parseAsArrayOf(parseAsStringLiteral(KINDS)),
    channel: parseAsArrayOf(parseAsString)
  });

  const phase2 = snapshot.data?.state.phase2;
  const live = useLiveSnapshotRefresh(phase2?.jobs, nowSeconds);

  const focusedDate = useMemo(
    () => (timeZone ? (parseDay(params.date) ?? today(timeZone)) : null),
    [params.date, timeZone]
  );

  // Only the set of expired reviews feeds the events, so the 30 second clock does not rebuild the calendar.
  const expiredKey =
    phase2 && nowSeconds !== null
      ? phase2.reviews
          .filter((review) => reviewExpired(review, nowSeconds))
          .map((review) => review.id)
          .join(',')
      : null;

  const channels = useMemo(() => phase2?.channels ?? [], [phase2]);

  const allEvents = useMemo<CalendarEvent<Post>[]>(() => {
    if (!phase2 || !timeZone || expiredKey === null) return [];
    const expired = new Set(expiredKey.split(','));
    const out: CalendarEvent<Post>[] = [];
    const add = (id: string, kind: Kind, manifest: Manifest, job?: Job) => {
      const at = new Date(manifest.timing.utc);
      if (Number.isNaN(at.getTime())) return;
      const firstLine = manifest.payload.text.split('\n').find((line) => line.trim())?.trim();
      const channel =
        channels.find((item) => item.id === manifest.channelId) ??
        channels.find((item) => item.platform === manifest.platform && item.account === manifest.account);
      out.push({
        id,
        title: firstLine || `${manifest.platform} post`,
        start: fromDate(at, timeZone),
        tone: KIND_META[kind].tone,
        status: `${manifest.platform}, ${KIND_META[kind].label}`,
        icon: <ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />,
        data: {
          kind,
          platform: manifest.platform,
          account: manifest.account,
          channelKey: channel?.id ?? manifest.channelId ?? `${manifest.platform}:${manifest.account}`,
          text: manifest.payload.text,
          at,
          approvedZone: manifest.timing.timeZone,
          cancelRequested: job?.cancelRequested ?? false,
          manifest,
          job
        }
      });
    };
    for (const review of phase2.reviews) {
      const kind = reviewKind(review, expired.has(review.id));
      if (kind) add(`r-${review.id}`, kind, review.manifest);
    }
    for (const job of phase2.jobs) add(`j-${job.id}`, jobKind(job.state), job.manifest, job);
    return out;
  }, [phase2, channels, timeZone, expiredKey]);

  // Every connected account, then any account a post went out through that is no longer listed.
  const channelOptions = useMemo<ChannelOption[]>(() => {
    const options: ChannelOption[] = channels.map((channel) => ({ key: channel.id, platform: channel.platform, account: channel.account }));
    const seen = new Set(options.map((option) => option.key));
    for (const event of allEvents) {
      const post = event.data;
      if (!post || seen.has(post.channelKey)) continue;
      seen.add(post.channelKey);
      options.push({ key: post.channelKey, platform: post.platform, account: post.account });
    }
    return options;
  }, [channels, allEvents]);

  // A filter that hides nothing, or names only values that no longer exist, is no filter.
  const kindParam = new Set(params.kind ?? []);
  const selectedKinds = kindParam.size > 0 && kindParam.size < KINDS.length ? KINDS.filter((kind) => kindParam.has(kind)) : null;
  const channelParam = new Set(params.channel ?? []);
  const knownChannels = channelOptions.map((option) => option.key).filter((key) => channelParam.has(key));
  const selectedChannels = knownChannels.length > 0 && knownChannels.length < channelOptions.length ? knownChannels : null;
  const kindFilter = selectedKinds?.join(',') ?? '';
  const channelFilter = selectedChannels?.join(',') ?? '';

  const events = useMemo(() => {
    const kinds = kindFilter ? new Set(kindFilter.split(',')) : null;
    const keys = channelFilter ? new Set(channelFilter.split(',')) : null;
    return allEvents.filter((event) => event.data && (!kinds || kinds.has(event.data.kind)) && (!keys || keys.has(event.data.channelKey)));
  }, [allEvents, kindFilter, channelFilter]);

  const loading = snapshot.isPending || !timeZone || !focusedDate || nowSeconds === null;
  const fatalError = snapshot.isError && !snapshot.data;

  function goToDay(day: CalendarDate) {
    if (!timeZone) return;
    void setParams({ date: isToday(day, timeZone) ? null : day.toString() });
  }

  const retry = (
    <LoadingButton variant='glass' size='control' className='h-11' loading={snapshot.isFetching} loadingLabel='Trying again…' onClick={() => void snapshot.refetch()}>
      Try again
    </LoadingButton>
  );

  // The page's one dominant action (DNA §9.2), rendered once the calendar has loaded; the empty state below offers
  // the missing prerequisite (drafts, an account) rather than repeating it (DNA §9.3).
  const scheduleAction = canSchedule ? (
    <Button variant='action' size='control' data-tour='calendar-schedule' onClick={() => setScheduling(true)}>
      <Icons.add />
      Schedule a draft
    </Button>
  ) : canEdit ? (
    <Link href='/app' data-tour='calendar-schedule' className={buttonVariants({ variant: 'action', size: 'control' })}>
      <Icons.add />
      New post
    </Link>
  ) : undefined;

  function body() {
    if (fatalError) {
      return <StateMessage kind='error' title='Couldn’t load your schedule' description={errorMessage(snapshot.error)} action={retry} />;
    }
    if (loading || !timeZone || !focusedDate) return <CalendarSkeleton />;

    const range = visibleRange(params.view, focusedDate, DEFAULT_LOCALE, DEFAULT_FIRST_DAY_OF_WEEK);
    const inRange = (event: CalendarEvent<Post>) => {
      const day = toCalendarDate(event.start);
      return day.compare(range.start) >= 0 && day.compare(range.end) <= 0;
    };

    // Counts are faceted: statuses count within the chosen accounts and accounts within the chosen statuses.
    const kindCounts = Object.fromEntries(KINDS.map((kind) => [kind, 0])) as Record<Kind, number>;
    const channelCounts = new Map<string, number>();
    for (const event of allEvents) {
      const post = event.data;
      if (!post || !inRange(event)) continue;
      if (!selectedChannels || selectedChannels.includes(post.channelKey)) kindCounts[post.kind] += 1;
      if (!selectedKinds || selectedKinds.includes(post.kind)) channelCounts.set(post.channelKey, (channelCounts.get(post.channelKey) ?? 0) + 1);
    }

    const filtering = selectedKinds !== null || selectedChannels !== null;
    const unitPhrase = params.view === 'day' ? 'on this day' : `in this ${params.view}`;
    let periodNote: ReactNode = null;
    if (allEvents.length > 0 && !events.some(inRange)) {
      const sorted = events.toSorted((a, b) => a.start.compare(b.start));
      const after = sorted.find((event) => toCalendarDate(event.start).compare(range.end) > 0);
      const target = after ?? sorted.findLast((event) => toCalendarDate(event.start).compare(range.start) < 0);
      const label = target
        ? new Intl.DateTimeFormat('en', {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            year: target.start.year === focusedDate.year ? undefined : 'numeric',
            timeZone
          }).format(target.start.toDate())
        : null;
      periodNote = (
        <span className='flex flex-wrap items-center gap-x-2'>
          {events.length === 0 ? 'No posts match these filters.' : filtering ? `Nothing ${unitPhrase} matches the filters.` : `Nothing ${unitPhrase}.`}
          {target && label && (
            <Button variant='link' size='xs' className='text-foreground h-auto px-0 text-xs' onClick={() => goToDay(toCalendarDate(target.start))}>
              {after ? 'Next post' : 'Latest post'}: {label}
              {after ? <Icons.arrowRight /> : null}
            </Button>
          )}
        </span>
      );
    }

    const variantsCount = snapshot.data?.state.variants?.length ?? 0;

    return (
      <div className='flex flex-col gap-4' data-tour='calendar-grid'>
        {snapshot.isError && (
          <StateMessage
            kind='stale'
            title='Couldn’t refresh your schedule'
            description={
              <>
                {errorMessage(snapshot.error)} The calendar shows what loaded at{' '}
                {new Intl.DateTimeFormat('en', { timeStyle: 'short', timeZone }).format(snapshot.dataUpdatedAt)}.
              </>
            }
            action={retry}
          />
        )}

        {allEvents.length === 0 ? (
          <StateMessage
            kind='empty'
            media={
              <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 shrink-0 items-center justify-center rounded-full'>
                <Icons.calendar className='size-5' />
              </span>
            }
            title='Nothing scheduled yet'
            description={
              <>
                Draft something in Ideas, then schedule it for an account at an exact time. It appears here at that time, in your time zone, and publishes only after you approve it.
                {channels.length === 0 && ' No accounts are connected yet.'}
              </>
            }
            action={
              variantsCount === 0 || channels.length === 0 ? (
                <>
                  {variantsCount === 0 && canEdit && (
                    <Link href='/app/ideas' className={buttonVariants({ variant: scheduleAction ? 'glass' : 'action', size: 'control' })}>
                      Go to Ideas
                    </Link>
                  )}
                  {channels.length === 0 && canConnect && (
                    <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
                      Connect a channel
                    </Link>
                  )}
                </>
              ) : undefined
            }
          />
        ) : (
          <CalendarFilters
            unit={params.view}
            kindCounts={kindCounts}
            selectedKinds={selectedKinds}
            onKindsChange={(next) => void setParams({ kind: next })}
            channels={channelOptions.map((option) => ({ ...option, count: channelCounts.get(option.key) ?? 0 }))}
            selectedChannels={selectedChannels}
            onChannelsChange={(next) => void setParams({ channel: next })}
            onReset={() => void setParams({ kind: null, channel: null })}
            live={live}
            periodNote={periodNote}
          />
        )}

        <Calendar
          events={events}
          view={params.view}
          onViewChange={(view) => void setParams({ view: view === 'month' ? null : view })}
          focusedDate={focusedDate}
          // Today stays out of the address, so a bookmarked calendar always opens on the current day.
          onFocusedDateChange={goToDay}
          timeZone={timeZone}
          noun={NOUN}
          renderEventDetails={(event, context) => <PostDetails event={event} context={context} timeZone={timeZone} wide={wide} />}
          dayPanelFooter={
            <Link href='/app/queue' className={cn('t-learn self-start', buttonVariants({ variant: 'quiet', size: 'sm' }), '-ml-2.5 h-8 text-xs')}>
              Open the queue <LearnMoreChevron />
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <PageContainer
      pageTitle='Calendar'
      pageDescription='Approved and pending publications at their exact times, in your time zone.'
      infoContent={infoContent}
      pageHeaderAction={!fatalError && !loading ? scheduleAction : undefined}
    >
      {canSchedule && <ScheduleDialog open={scheduling} onOpenChange={setScheduling} />}
      {body()}
    </PageContainer>
  );
}
