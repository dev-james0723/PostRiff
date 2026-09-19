'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { keys, useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Manifest } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useFlash } from '@/hooks/use-flash';
import { reportActionError } from './action-error';
import { APPROVE_MANY_LIMIT, ApproveManyDialog } from './approve-many-dialog';
import { JobRow, JobStateBadge } from './job-row';
import { JobSheet } from './job-sheet';
import {
  canCancel,
  ENDED,
  epochOf,
  FILTER_VALUES,
  FILTERS,
  isLive,
  latestWorkerActivity,
  matchesFilter,
  type QueueJob,
  type QueueReview
} from './job-state';
import { ScheduleDialog } from './schedule-dialog';
import { useElementWidth, useWide } from './use-wide';

/** How often the snapshot refreshes while a job is with the provider or about to be picked up. */
const LIVE_REFRESH_MS = 15_000;
/** Countdowns, "time passed" and relative times re-read the clock this often (the live island's tick). */
const TICK_MS = 30_000;
/**
 * Below this list width the jobs render as cards: state, destination, time, attempts and the actions need about this
 * much, and a narrower table would hide the actions behind a sideways scroll. Last event and Provider join the table
 * at wider list widths (the container queries on those columns).
 */
const TABLE_MIN_WIDTH = 832;

/**
 * Motion rule (docs/postriff-motion-system.md §5): 40ms stagger, a whole entrance within 300ms, and a close faster than
 * the open. Cards past the third start with it: 2 × 40ms + 220ms. An approved card leaves at once; the toast and the
 * new row under Publishing jobs carry the outcome.
 */
const REVIEW_ENTER_S = 0.22;
const REVIEW_STAGGER_S = 0.04;
const REVIEW_STAGGER_STEPS = 2;
const REVIEW_EXIT = { opacity: 0, transition: { duration: 0.15, ease: EASE_OUT } };

const infoContent = {
  title: 'Approvals and the queue',
  sections: [
    {
      title: 'Exact approvals',
      description:
        'A review freezes the text, media, account and time into a manifest with a digest. Approving that digest is the only way a post enters the queue. The same draft prepared twice for the same account and time is the same post: once one review is approved, the other schedules nothing.'
    },
    {
      title: 'Who does what',
      description:
        'Preparing a review, approving it and cancelling a job need the approve permission. When a draft has a newer version waiting or unknown details to confirm, someone who can edit drafts does that first.'
    },
    {
      title: 'Job states',
      description:
        'Waiting → in flight → verified. “Uncertain” means the provider did not confirm; PostRiff reconciles before it ever retries, so nothing is posted twice.'
    },
    {
      title: 'Cancel',
      description:
        'Hold to cancel a waiting or held job before the provider has it. Once a post is submitted, a cancel cannot recall it; the job is reconciled instead.'
    },
    {
      title: 'Held',
      description:
        'A job is held when something changed after approval: the approver’s permission, the draft, the account’s connection, the plan, or the approval window closed. Nothing publishes from a held job, but it counts toward the account’s daily limit until it is cancelled. Prepare the draft again for a new review.'
    },
    {
      title: 'Receipts',
      description: 'Open any job for its timeline, every attempt and exactly what the provider confirmed.'
    }
  ]
};

function errorMessage(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback;
}

/** The clock the page reads, never behind the snapshot it shows. */
function useNow(dataUpdatedAt: number) {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setTick(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, []);
  return Math.max(tick, dataUpdatedAt);
}

function ReviewCard({
  review,
  revision,
  canApprove,
  nowSeconds,
  tour,
  twin,
  onReload,
  onOpenJob
}: {
  review: QueueReview;
  revision: number;
  canApprove: boolean;
  nowSeconds: number;
  tour: boolean;
  /** Another waiting review freezes exactly the same post (same idempotency key); only one job can come of the two. */
  twin: boolean;
  onReload: () => void;
  onOpenJob: (jobId: string) => void;
}) {
  const act = useAct();
  const [outcome, flashOutcome] = useFlash<'success' | 'error'>();
  const manifest = review.manifest;
  const expired = manifest.expiresAt <= nowSeconds;
  // Still approvable for an hour after its time (`expiresAt`); the worker then publishes at its next run.
  const timePassed = !expired && (epochOf(manifest.timing.utc) ?? Infinity) < nowSeconds;
  const needsReview = review.status === 'needs_review';
  return (
    <Card className='h-full' data-tour={tour ? 'queue-review-card' : undefined}>
      {/* The phone shows exactly what the approval covers, drawn in the destination app, beside the frozen details. */}
      <div className='grid gap-(--card-spacing) md:grid-cols-[minmax(0,1fr)_auto]'>
        <div className='flex min-w-0 flex-col gap-(--card-spacing)'>
          <CardHeader>
            <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
              <ChannelIcon platform={manifest.platform} name={manifest.platform} />
              {manifest.platform} · {manifest.account}
              <AnimatedBadge size='sm' status={needsReview ? 'warning' : 'neutral'} pulse={needsReview && !expired}>
                {review.status.replace(/_/g, ' ')}
              </AnimatedBadge>
              {expired && (
                <AnimatedBadge size='sm' status='danger'>
                  expired
                </AnimatedBadge>
              )}
              {manifest.execution === 'synthetic' && (
                <AnimatedBadge size='sm' status='neutral' showIcon={false} title='Synthetic provider; nothing reaches a real account'>
                  Fixture
                </AnimatedBadge>
              )}
            </CardTitle>
            <CardDescription>
              {manifest.timing.local.replace('T', ' ')} ({manifest.timing.timeZone}) · {manifest.payload.language} · {manifest.media.length} media ·{' '}
              <span className='font-mono'>{review.digest.slice(0, 12)}…</span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className='line-clamp-[12] text-sm whitespace-pre-wrap'>{manifest.payload.text}</p>
          </CardContent>
        </div>
        <div
          data-tour={tour ? 'queue-review-phone' : undefined}
          className='mx-(--card-spacing) border-t pt-(--card-spacing) md:mx-0 md:border-t-0 md:border-l md:px-(--card-spacing) md:pt-0'
        >
          <ManifestPreview manifest={manifest} scale={0.5} />
        </div>
      </div>
      {canApprove && needsReview && (
        <CardFooter className='flex flex-wrap items-center gap-3'>
          <StatefulButton
            state={act.isPending ? 'loading' : (outcome ?? 'idle')}
            loadingText='Approving…'
            successText='Scheduled'
            errorText='Try again'
            disabled={expired}
            // Approved: the card is on its way out. It keeps full opacity so "Scheduled" reads, but takes no second click.
            aria-disabled={outcome === 'success' || undefined}
            onClick={() => {
              if (outcome === 'success') return;
              act.mutate(
                { revision, action: 'p2_approve', payload: { reviewId: review.id, digest: review.digest, confirmed: true } },
                {
                  // Say "scheduled" only when the server's answer shows it: this review approved and its job there.
                  onSuccess: (next) => {
                    const phase = next.state.phase2;
                    const approved = phase?.reviews.find((r) => r.id === review.id)?.status === 'approved';
                    const job = phase?.jobs.find((j) => j.manifest.idempotencyKey === manifest.idempotencyKey);
                    if (approved && job) {
                      toast.success('Approved and scheduled.');
                      flashOutcome('success');
                    } else if (job) {
                      toast.info('This exact post was already a job, so nothing new was scheduled.', {
                        action: { label: 'Open job', onClick: () => onOpenJob(job.id) }
                      });
                    } else {
                      toast.error('The approval was answered, but no job appeared. Reload the queue to check.', {
                        action: { label: 'Reload', onClick: onReload }
                      });
                      flashOutcome('error');
                    }
                  },
                  onError: (err) => {
                    reportActionError(err, 'Approval failed.', onReload);
                    flashOutcome('error');
                  }
                }
              );
            }}
          >
            Approve & schedule
          </StatefulButton>
          <span className={cn('text-xs', timePassed ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>
            {expired
              ? 'The review window closed; prepare it again from the draft.'
              : timePassed
                ? 'The approved time has passed; approving now publishes at the worker’s next run.'
                : 'Approves exactly this text, media, account and time.'}
            {!expired && twin && ' Another review here is the same post; approving either one schedules it once.'}
          </span>
        </CardFooter>
      )}
    </Card>
  );
}

/** Reviews that stopped matching their draft, voice, account or sources. The server keeps no reason, so none is guessed. */
function StaleReviews({
  reviews,
  canSchedule,
  draftAvailable,
  onPrepareAgain
}: {
  reviews: QueueReview[];
  canSchedule: boolean;
  draftAvailable: (variantId: string) => boolean;
  onPrepareAgain: (variantId: string) => void;
}) {
  if (reviews.length === 0) return null;
  return (
    <Collapsible className='rounded-lg border'>
      <CollapsibleTrigger className='group/stale hover:bg-muted/50 flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50'>
        <span>
          {reviews.length} review{reviews.length === 1 ? '' : 's'} went stale
          <span className='text-muted-foreground'> · the draft, voice, account or sources changed after they were prepared</span>
        </span>
        <Icons.chevronDown
          aria-hidden
          className='text-muted-foreground size-4 shrink-0 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/stale:rotate-180 motion-reduce:transition-none'
        />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>
        <ul className='flex flex-col divide-y border-t'>
          {reviews.map((review) => {
            const { manifest } = review;
            const available = draftAvailable(manifest.variantId);
            const text = manifest.payload.text.trim();
            return (
              <li key={review.id} className='flex flex-col gap-2 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between'>
                <span className='flex min-w-0 flex-col gap-0.5'>
                  <span className='flex min-w-0 items-center gap-2'>
                    <ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />
                    <span className='truncate'>
                      {manifest.platform} · {manifest.account}
                    </span>
                    <span className='text-muted-foreground shrink-0 text-xs'>{manifest.timing.local.replace('T', ' ')}</span>
                  </span>
                  <span className='text-muted-foreground truncate text-xs'>
                    {text.slice(0, 60)}
                    {text.length > 60 ? '…' : ''}
                  </span>
                </span>
                {canSchedule && (
                  <Button
                    variant='outline'
                    size='sm'
                    className='self-start sm:self-auto'
                    disabled={!available}
                    title={available ? 'Prepare a new review of the same draft' : 'This draft is no longer available'}
                    onClick={() => onPrepareAgain(manifest.variantId)}
                  >
                    Prepare again
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * Reviews whose exact post is already a job. The manifest carries nothing unique, so the same draft prepared twice for
 * the same account and time has the same idempotency key, and `store.py` approve answers the second approval without
 * scheduling anything (the review keeps waiting). They are listed here instead of offering an approval that does nothing.
 */
function AlreadyJobs({
  reviews,
  jobByKey,
  onOpenJob
}: {
  reviews: QueueReview[];
  jobByKey: Map<string, QueueJob>;
  onOpenJob: (jobId: string) => void;
}) {
  if (reviews.length === 0) return null;
  return (
    <Collapsible className='rounded-lg border'>
      <CollapsibleTrigger className='group/dupes hover:bg-muted/50 flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50'>
        <span>
          {reviews.length} review{reviews.length === 1 ? ' is' : 's are'} already a job
          <span className='text-muted-foreground'> · the same post, account and time was approved before, so approving again schedules nothing</span>
        </span>
        <Icons.chevronDown
          aria-hidden
          className='text-muted-foreground size-4 shrink-0 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/dupes:rotate-180 motion-reduce:transition-none'
        />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>
        <ul className='flex flex-col divide-y border-t'>
          {reviews.map((review) => {
            const { manifest } = review;
            const job = jobByKey.get(manifest.idempotencyKey);
            if (!job) return null;
            const ended = ENDED.has(job.state);
            return (
              <li key={review.id} className='flex flex-col gap-2 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between'>
                <span className='flex min-w-0 flex-col gap-0.5'>
                  <span className='flex min-w-0 flex-wrap items-center gap-2'>
                    <ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />
                    <span className='truncate'>
                      {manifest.platform} · {manifest.account}
                    </span>
                    <span className='text-muted-foreground shrink-0 text-xs'>{manifest.timing.local.replace('T', ' ')}</span>
                    <JobStateBadge job={job} />
                  </span>
                  {ended && (
                    <span className='text-muted-foreground text-xs'>
                      That job has ended. To post this draft again, prepare a review for a different time.
                    </span>
                  )}
                </span>
                <Button variant='outline' size='sm' className='self-start sm:self-auto' onClick={() => onOpenJob(job.id)}>
                  Open job
                </Button>
              </li>
            );
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function LoadError({ error, hasData, updatedAt, onRetry }: { error: unknown; hasData: boolean; updatedAt: number; onRetry: () => Promise<{ isError: boolean }> }) {
  const [outcome, flash] = useFlash<'success' | 'error'>();
  const [retrying, setRetrying] = useState(false);
  return (
    <Alert variant='destructive' className='flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'>
      <div className='flex flex-col gap-0.5'>
        <AlertTitle>{hasData ? 'The queue could not be refreshed.' : 'The queue could not be loaded.'}</AlertTitle>
        <AlertDescription>
          {errorMessage(error, '')}
          {hasData && ` Showing what was loaded ${relativeTime(updatedAt / 1000)}.`}
        </AlertDescription>
      </div>
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
    </Alert>
  );
}

function FirstRun({ canSchedule, hasDrafts, hasReadyAccount, onSchedule }: { canSchedule: boolean; hasDrafts: boolean; hasReadyAccount: boolean; onSchedule: () => void }) {
  const steps = [
    { title: 'Schedule a draft', text: 'Pick a draft, an account and an exact time.' },
    { title: 'Approve it here', text: 'Approve the exact text, media and time.' },
    { title: 'The worker publishes', text: 'At that time, and it records what the provider confirmed.' }
  ];
  return (
    <Empty className='border' data-tour='queue-approvals'>
      <EmptyHeader>
        <EmptyMedia variant='icon'>
          <Icons.listDetails />
        </EmptyMedia>
        <EmptyTitle>Nothing publishes on its own</EmptyTitle>
        <EmptyDescription>Every post goes through the same three steps.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent className='max-w-2xl gap-4'>
        <ol className='grid w-full gap-3 text-left sm:grid-cols-3'>
          {steps.map((step, index) => (
            <li key={step.title} className='bg-muted/40 flex gap-3 rounded-lg border p-3 sm:flex-col sm:gap-1.5'>
              <span className='bg-background text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full border text-xs tabular-nums'>{index + 1}</span>
              <span className='flex flex-col gap-0.5'>
                <span className='font-medium'>{step.title}</span>
                <span className='text-muted-foreground text-xs'>{step.text}</span>
              </span>
            </li>
          ))}
        </ol>
        <div className='flex flex-wrap justify-center gap-2'>
          {canSchedule && <Button onClick={onSchedule}>Schedule a draft</Button>}
          {!hasDrafts && (
            <Link href='/app/ideas' className={buttonVariants({ variant: 'outline' })}>
              Draft something in Ideas
            </Link>
          )}
        </div>
        {!hasReadyAccount && (
          <p className='text-muted-foreground text-xs'>
            Connect and verify an account first; a review can only be prepared for an account that is ready for posting.{' '}
            <Link href='/app/channels' className='underline underline-offset-2'>
              Open Channels
            </Link>
          </p>
        )}
      </EmptyContent>
    </Empty>
  );
}

export function QueueView() {
  // `?filter=`, `?job=` and `?channel=` live in the URL, which needs a suspense boundary above the reader.
  return (
    <Suspense fallback={null}>
      <Queue />
    </Suspense>
  );
}

function Queue() {
  const snapshot = useSnapshot();
  const act = useAct();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  const client = useQueryClient();
  const { workspaceId } = useWorkspaceApi();
  const wide = useWide();
  const [listRef, listWidth] = useElementWidth<HTMLDivElement>();
  const asTable = (listWidth ?? (wide ? TABLE_MIN_WIDTH : 0)) >= TABLE_MIN_WIDTH;
  // Sample workspaces refuse every command (`hosted.py`), so they offer none.
  const sample = Boolean(snapshot.data?.state.workspace?.sample);
  const canApprove = checkAccess(access, { permission: 'approve' }) && !sample;
  const canEdit = checkAccess(access, { permission: 'edit' });
  // Preparing a review (`p2_review`) is in the server's approve class, with approving and cancelling
  // (`permissions.py` ACTION_CLASSES), so an editor without it is not offered a button the server refuses.
  const canSchedule = canApprove;
  const [params, setParams] = useQueryStates(
    {
      filter: parseAsStringLiteral(FILTER_VALUES).withDefault('all'),
      job: parseAsString,
      channel: parseAsString
    },
    { history: 'replace', scroll: false }
  );
  // A new key per opening, so "Prepare again" preselects its draft in a fresh dialog.
  const [scheduling, setScheduling] = useState<{ open: boolean; variantId: string | null; key: number }>({ open: false, variantId: null, key: 0 });
  // The batch is frozen when the dialog opens: the confirmation lists exactly what will be sent.
  const [batch, setBatch] = useState<{ open: boolean; reviews: QueueReview[] }>({ open: false, reviews: [] });
  // A hold button goes disabled mid-press while its cancel is pending, so its release can go unheard. After a failed
  // cancel the buttons remount instead of staying stuck on "Cancelling…"; a successful one takes the button away.
  const [holdEpoch, setHoldEpoch] = useState(0);
  const now = useNow(snapshot.dataUpdatedAt);
  const nowSeconds = now / 1000;

  // No snapshot and no error yet. A disabled or failed query is not "loading".
  const loading = snapshot.isPending && snapshot.isFetching;
  const loaded = Boolean(snapshot.data);
  const phase2 = snapshot.data?.state.phase2;
  const variants = snapshot.data?.state.variants ?? [];
  const channelId = params.channel;
  const inChannel = (manifest: Manifest) => !channelId || manifest.channelId === channelId;

  const allReviews: QueueReview[] = phase2?.reviews ?? [];
  const allJobs: QueueJob[] = phase2?.jobs ?? [];
  // Keyed by the manifest's idempotency key: a review whose key is already a job cannot schedule anything new.
  const jobByKey = new Map(allJobs.map((job) => [job.manifest.idempotencyKey, job] as const));
  const waitingReviews = allReviews.filter((r) => r.status === 'needs_review' && inChannel(r.manifest));
  const reviews = waitingReviews.filter((r) => !jobByKey.has(r.manifest.idempotencyKey));
  const alreadyJobs = waitingReviews.filter((r) => jobByKey.has(r.manifest.idempotencyKey));
  // The first waiting review of each post, and how many wait for it: reviews of the same post are twins.
  const firstOfPost = new Map<string, string>();
  const reviewsOfPost = new Map<string, number>();
  for (const review of reviews) {
    const key = review.manifest.idempotencyKey;
    if (!firstOfPost.has(key)) firstOfPost.set(key, review.id);
    reviewsOfPost.set(key, (reviewsOfPost.get(key) ?? 0) + 1);
  }
  const staleReviews = allReviews.filter((r) => r.status === 'stale' && inChannel(r.manifest));
  const jobs = allJobs
    .filter((job) => inChannel(job.manifest))
    .toSorted((a, b) => (epochOf(b.manifest.timing.utc) ?? 0) - (epochOf(a.manifest.timing.utc) ?? 0));
  const visible = jobs.filter((job) => matchesFilter(job.state, params.filter));
  const revision = snapshot.data?.revision ?? 0;
  const filterLabel = FILTERS.find((option) => option.value === params.filter) ?? FILTERS[0];
  const workerActivity = latestWorkerActivity(allJobs);
  const firstCancellable = visible.find(canCancel)?.id;

  // One review per post: approving twins together would promise two posts and schedule one.
  const approvable = canApprove
    ? reviews
        .filter((r) => r.manifest.expiresAt > nowSeconds && firstOfPost.get(r.manifest.idempotencyKey) === r.id)
        .toSorted((a, b) => (epochOf(a.manifest.timing.utc) ?? 0) - (epochOf(b.manifest.timing.utc) ?? 0))
    : [];

  const channels = phase2?.channels ?? [];
  const channelFilter = channelId
    ? (channels.find((c) => c.id === channelId) ??
      [...allJobs, ...allReviews].map((item) => item.manifest).find((m) => m.channelId === channelId) ??
      null)
    : null;
  const firstRun = loaded && !channelId && allJobs.length === 0 && !allReviews.some((r) => r.status === 'needs_review' || r.status === 'stale');

  // Live refresh: only while a job is with the provider or the worker picks one up within two minutes.
  const live = isLive(allJobs, nowSeconds);
  useEffect(() => {
    if (!live || !workspaceId) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'hidden' || client.isMutating() > 0) return;
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [live, client, workspaceId]);

  const reload = () => void snapshot.refetch();
  // The drafts the schedule dialog can preselect: still there, not blocked by a retraction, and written with the
  // active voice profile (or with a waiting update that is).
  const activeVoice = snapshot.data?.state.speaker?.activeRevision ?? null;
  const draftAvailable = (variantId: string) =>
    variants.some(
      (v) => v.id === variantId && !v.blockedByRetraction && (v.voiceRevision === activeVoice || v.proposedUpdate?.voiceRevision === activeVoice)
    );
  const openSchedule = (variantId: string | null = null) => setScheduling((s) => ({ open: true, variantId, key: s.key + 1 }));
  const openJob = (jobId: string) => void setParams({ job: jobId });

  function cancel(job: QueueJob) {
    act.mutate(
      { revision, action: 'p2_cancel', payload: { jobId: job.id } },
      {
        onSuccess: () => toast.success('Cancel requested.'),
        onError: (err) => {
          reportActionError(err, 'Could not cancel.', reload);
          setHoldEpoch((epoch) => epoch + 1);
        }
      }
    );
  }

  const rowProps = {
    nowSeconds,
    canApprove,
    cancelPending: act.isPending,
    holdEpoch,
    onCancel: cancel,
    onOpen: openJob
  };

  return (
    <PageContainer
      pageTitle='Queue'
      pageDescription='Approvals waiting on you, then everything the worker is handling.'
      infoContent={infoContent}
      pageHeaderAction={
        canSchedule ? (
          <Button data-tour='queue-schedule' onClick={() => openSchedule()}>
            <Icons.calendar />
            Schedule a draft
          </Button>
        ) : undefined
      }
    >
      <ScheduleDialog
        key={scheduling.key}
        open={scheduling.open}
        onOpenChange={(open) => setScheduling((s) => ({ ...s, open }))}
        variantId={scheduling.variantId}
      />
      <ApproveManyDialog
        open={batch.open}
        onOpenChange={(open) => setBatch((b) => ({ ...b, open }))}
        reviews={batch.reviews}
        jobs={allJobs}
        revision={revision}
        nowSeconds={nowSeconds}
        onReload={reload}
      />
      <JobSheet
        jobId={params.job}
        jobs={allJobs}
        ready={loaded}
        nowSeconds={nowSeconds}
        canApprove={canApprove}
        canSchedule={canSchedule}
        cancelPending={act.isPending}
        holdEpoch={holdEpoch}
        onClose={() => void setParams({ job: null })}
        onCancel={cancel}
        onPrepareAgain={(variantId) => {
          void setParams({ job: null });
          openSchedule(variantId);
        }}
        draftAvailable={draftAvailable}
      />

      <div className='flex flex-col gap-8'>
        {sample ? (
          <p className='text-muted-foreground -mb-4 text-sm'>Sample workspaces are read-only: nothing here can be scheduled, approved or cancelled.</p>
        ) : (
          !canApprove &&
          canEdit && (
            <p className='text-muted-foreground -mb-4 text-sm'>
              Scheduling, approving and cancelling posts is for the owner, approvers and members who can approve publications.
            </p>
          )
        )}
        {snapshot.isError && (
          <LoadError error={snapshot.error} hasData={loaded} updatedAt={snapshot.dataUpdatedAt} onRetry={() => snapshot.refetch()} />
        )}

        {channelId && loaded && (
          <div className='bg-muted/40 -mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm'>
            <span className='flex min-w-0 items-center gap-2'>
              {channelFilter ? (
                <>
                  <ChannelIcon platform={channelFilter.platform} name={channelFilter.platform} size='xs' />
                  <span className='truncate'>
                    Showing {channelFilter.platform} · {channelFilter.account}
                  </span>
                </>
              ) : (
                <span>Showing one account that is no longer in this workspace</span>
              )}
            </span>
            <Button variant='ghost' size='sm' onClick={() => void setParams({ channel: null })}>
              Show all accounts
            </Button>
          </div>
        )}

        {firstRun ? (
          // One teaching block instead of two small empty states; it carries both tour anchors of the sections it replaces.
          <section aria-label='How the queue works' data-tour='queue-list'>
            <FirstRun
              canSchedule={canSchedule}
              hasDrafts={variants.length > 0}
              hasReadyAccount={channels.some((c) => c.displayState === 'Ready for posting')}
              onSchedule={() => openSchedule()}
            />
          </section>
        ) : (
          (loading || loaded) && (
            <>
              <section className='flex flex-col gap-3' aria-labelledby='approvals-heading' data-tour='queue-approvals'>
                <div className='flex flex-wrap items-center justify-between gap-3'>
                  <h3 id='approvals-heading' className='text-lg font-semibold'>
                    Waiting for approval{' '}
                    {reviews.length > 0 && (
                      <Badge className='ml-1'>
                        <DigitSwap value={reviews.length} />
                      </Badge>
                    )}
                  </h3>
                  {approvable.length >= 2 && (
                    <Button variant='outline' size='sm' onClick={() => setBatch({ open: true, reviews: approvable.slice(0, APPROVE_MANY_LIMIT) })}>
                      {approvable.length > APPROVE_MANY_LIMIT ? `Approve the first ${APPROVE_MANY_LIMIT}` : `Approve all ${approvable.length}`}
                    </Button>
                  )}
                </div>
                {loading ? (
                  <Skeleton className='h-32 w-full' />
                ) : (
                  <AnimatePresence mode='wait' initial={false}>
                    {reviews.length === 0 ? (
                      <motion.p
                        key='none'
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ duration: 0.18, ease: EASE_OUT }}
                        className='text-muted-foreground text-sm'
                      >
                        {channelId
                          ? 'Nothing from this account is waiting for approval.'
                          : 'Nothing to approve. Use “Schedule a draft” to prepare one for a channel and time.'}
                      </motion.p>
                    ) : (
                      <motion.div key='reviews' exit={REVIEW_EXIT} className='grid gap-4 min-[1400px]:grid-cols-2'>
                        <AnimatePresence>
                          {reviews.map((review, index) => (
                            <motion.div
                              key={review.id}
                              layout={reduce ? false : 'position'}
                              initial={reduce ? false : { opacity: 0, y: 8 }}
                              animate={{
                                opacity: 1,
                                y: 0,
                                transition: { duration: REVIEW_ENTER_S, ease: EASE_OUT, delay: Math.min(index, REVIEW_STAGGER_STEPS) * REVIEW_STAGGER_S }
                              }}
                              exit={REVIEW_EXIT}
                              transition={{ layout: SPRING_LAYOUT }}
                            >
                              <ReviewCard
                                review={review}
                                revision={revision}
                                canApprove={canApprove}
                                nowSeconds={nowSeconds}
                                tour={index === 0}
                                twin={(reviewsOfPost.get(review.manifest.idempotencyKey) ?? 0) > 1}
                                onReload={reload}
                                onOpenJob={openJob}
                              />
                            </motion.div>
                          ))}
                        </AnimatePresence>
                      </motion.div>
                    )}
                  </AnimatePresence>
                )}
                <AlreadyJobs reviews={alreadyJobs} jobByKey={jobByKey} onOpenJob={openJob} />
                <StaleReviews reviews={staleReviews} canSchedule={canSchedule} draftAvailable={draftAvailable} onPrepareAgain={(variantId) => openSchedule(variantId)} />
              </section>

              <section className='flex flex-col gap-3' aria-labelledby='jobs-heading' data-tour='queue-list'>
                <div className='flex flex-wrap items-center justify-between gap-3'>
                  <div className='flex flex-col'>
                    <h3 id='jobs-heading' className='text-lg font-semibold'>
                      Publishing jobs
                    </h3>
                    {loaded && (
                      <p className='text-muted-foreground text-xs'>
                        {workerActivity === null ? 'No worker events recorded yet' : `Latest worker event on a job · ${relativeTime(workerActivity, nowSeconds)}`}
                      </p>
                    )}
                  </div>
                  {/* The counts widen the tabs: on a narrow screen the list scrolls sideways instead of pushing the page wider. */}
                  <Tabs value={params.filter} onValueChange={(value) => void setParams({ filter: value as (typeof FILTER_VALUES)[number] })} variant='pill' className='min-w-0 max-w-full'>
                    <TabsList aria-label='Filter jobs' data-tour='queue-filters' className='scrollbar-hide max-w-full overflow-x-auto border'>
                      {FILTERS.map((option) => (
                        <TabsTrigger key={option.value} value={option.value} className='gap-1.5 px-3 py-1'>
                          {option.label}
                          {/* Counts only from a loaded snapshot: while loading there is no number to show, not a zero. */}
                          {loaded && <DigitSwap value={jobs.filter((job) => matchesFilter(job.state, option.value)).length} className='text-xs opacity-75' />}
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </Tabs>
                </div>
                <div ref={listRef} className='@container min-w-0'>
                {loading ? (
                  <Skeleton className='h-48 w-full' />
                ) : visible.length === 0 ? (
                  <Empty className='border'>
                    <EmptyHeader>
                      <EmptyMedia variant='icon'>
                        <Icons.listDetails />
                      </EmptyMedia>
                      <EmptyTitle>{params.filter === 'all' ? 'No jobs yet' : `No ${filterLabel.label.toLowerCase()} jobs`}</EmptyTitle>
                      <EmptyDescription>{filterLabel.empty}</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : asTable ? (
                  <div className='overflow-x-auto rounded-lg border'>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>State</TableHead>
                          <TableHead>Destination</TableHead>
                          <TableHead>Scheduled</TableHead>
                          <TableHead>Attempts</TableHead>
                          <TableHead className='hidden @min-[76rem]:table-cell'>Provider</TableHead>
                          <TableHead className='hidden @min-[66rem]:table-cell'>Last event</TableHead>
                          <TableHead>
                            <span className='sr-only'>Actions</span>
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {visible.map((job, index) => (
                          <JobRow key={job.id} job={job} layout='table' index={index} tourRow={index === 0} tourCancel={job.id === firstCancellable} {...rowProps} />
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <ul className='flex flex-col gap-2'>
                    {visible.map((job, index) => (
                      <JobRow key={job.id} job={job} layout='card' index={index} tourRow={index === 0} tourCancel={job.id === firstCancellable} {...rowProps} />
                    ))}
                  </ul>
                )}
                </div>
              </section>
            </>
          )
        )}
      </div>
    </PageContainer>
  );
}
