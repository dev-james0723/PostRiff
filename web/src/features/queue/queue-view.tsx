'use client';

import { Suspense, useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion } from 'motion/react';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { ReviewApproveButton } from '@/components/jobs/review-approve-button';
import { StatefulButton } from '@/components/motion/button';
import { DigitSwap } from '@/components/motion/digit-swap';
import { ActiveFilters, CollectionRow, SegmentedControl, StateMessage, Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Table, TableBody, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { keys, useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Manifest } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { useMotionPreference } from '@/lib/rafii/motion';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useFlash } from '@/hooks/use-flash';
import { languageLabel } from '@/lib/locales';
import { reportActionError } from './action-error';
import { APPROVE_MANY_LIMIT, ApproveManyDialog } from './approve-many-dialog';
import { FixtureBadge, JobNote, JobRow, JobStateBadge } from './job-row';
import { JobDetailSheet } from '@/components/jobs/job-detail-sheet';
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
import { DraftsPanel, useDraftCount } from '@/features/pipeline/drafts-panel';
import { StatusChip } from './status-chip';
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
 * Motion rule (docs/postriff-motion-system.md §5): an approved card leaves at once; the toast and the new row under
 * Publishing jobs carry the outcome. Cards arrive with one short fade, without a stagger (DNA §18).
 */
const REVIEW_ENTER_S = 0.22;
const REVIEW_EXIT = { opacity: 0, transition: { duration: 0.15, ease: EASE_OUT } };

const infoContent = {
  title: 'Drafts, approvals and the queue',
  sections: [
    {
      title: 'Drafts',
      description:
        'The Drafts tab holds every draft that is not scheduled yet: from Home, conversations and automations. Schedule… picks the account and time and prepares the exact post for approval. Set-aside drafts stay at the bottom of the list; editing one brings it back.'
    },
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

/** A section title with its real count beside it (DNA §21.4). */
function SectionHeading({ id, children, count }: { id: string; children: ReactNode; count?: number }) {
  return (
    <h2 id={id} className='text-foreground flex flex-wrap items-center gap-2 text-lg font-medium tracking-tight'>
      {children}
      {count !== undefined && count > 0 && (
        <span className='rafii-quiet text-foreground inline-flex min-h-6 items-center rounded-full px-2.5 text-sm tabular-nums'>
          <DigitSwap value={count} />
        </span>
      )}
    </h2>
  );
}

/** One review as a glass work surface: the frozen details beside the phone, one commit action underneath. */
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
  const manifest = review.manifest;
  const expired = manifest.expiresAt <= nowSeconds;
  // Still approvable for an hour after its time (`expiresAt`); the worker then publishes at its next run.
  const timePassed = !expired && (epochOf(manifest.timing.utc) ?? Infinity) < nowSeconds;
  const needsReview = review.status === 'needs_review';
  const footnote = expired
    ? 'The review window closed; prepare it again from the draft.'
    : timePassed
      ? 'The approved time has passed; approving now publishes at the worker’s next run.'
      : 'Approves exactly this text, media, account and time.';
  return (
    <Surface material='glass' radius='card' padding='none' className='flex h-full flex-col' data-tour={tour ? 'queue-review-card' : undefined}>
      {/* The phone shows exactly what the approval covers, drawn in the destination app, beside the frozen details. */}
      <div className='grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_auto]'>
        <div className='flex min-w-0 flex-col gap-3'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='flex min-w-0 items-center gap-2 text-base font-medium'>
              <ChannelIcon platform={manifest.platform} name={manifest.platform} />
              <span className='truncate'>
                {manifest.platform} · {manifest.account}
              </span>
            </span>
            <StatusChip tone={needsReview ? 'warning' : 'neutral'} pulse={needsReview && !expired}>
              {review.status.replace(/_/g, ' ')}
            </StatusChip>
            {expired && <StatusChip tone='danger'>expired</StatusChip>}
            {manifest.execution === 'synthetic' && <FixtureBadge />}
          </div>
          <p className='text-muted-foreground text-xs'>
            {manifest.timing.local.replace('T', ' ')} ({manifest.timing.timeZone}) · {languageLabel(manifest.payload.language)} · {manifest.media.length} media ·{' '}
            <span className='font-mono'>{review.digest.slice(0, 12)}…</span>
          </p>
          <p className='line-clamp-[12] text-sm whitespace-pre-wrap'>{manifest.payload.text}</p>
          {manifest.voiceRevision === null && <JobNote>This draft has no approved voice profile. Review its wording carefully before approving.</JobNote>}
        </div>
        <div data-tour={tour ? 'queue-review-phone' : undefined} className='md:pl-2'>
          <ManifestPreview manifest={manifest} scale={0.5} />
        </div>
      </div>
      {canApprove && needsReview && (
        <div className='mt-auto flex flex-wrap items-center gap-3 px-5 pb-5'>
          {/* The shared approve button keeps its verified-receipt logic; the wrapper gives it the 48px commit height (DNA §10.1). */}
          <span className='inline-flex [&_button]:h-12 [&_button]:rounded-[var(--rafii-radius-control)] [&_button]:px-4'>
            <ReviewApproveButton review={review} revision={revision} allowed={canApprove} nowSeconds={nowSeconds} onReload={onReload} onOpenJob={onOpenJob} />
          </span>
          {timePassed ? (
            <JobNote>
              {footnote}
              {!expired && twin && ' Another review here is the same post; approving either one schedules it once.'}
            </JobNote>
          ) : (
            <span className='text-muted-foreground text-xs'>
              {footnote}
              {!expired && twin && ' Another review here is the same post; approving either one schedules it once.'}
            </span>
          )}
        </div>
      )}
    </Surface>
  );
}

/** A quiet, labelled disclosure for the reviews that need no approval any more. */
function ReviewDisclosure({ group, summary, detail, children }: { group: string; summary: ReactNode; detail: ReactNode; children: ReactNode }) {
  return (
    <Collapsible className='flex flex-col gap-2'>
      <CollapsibleTrigger
        className={cn(
          'rafii-quiet rafii-focus hover:rafii-glass flex min-h-11 w-full items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-4 py-2 text-left text-sm transition-colors',
          `group/${group}`
        )}
      >
        <span>
          {summary}
          <span className='text-muted-foreground'> · {detail}</span>
        </span>
        <Icons.chevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground size-4 shrink-0 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) motion-reduce:transition-none',
            `group-data-panel-open/${group}:rotate-180`
          )}
        />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>{children}</CollapsibleContent>
    </Collapsible>
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
    <ReviewDisclosure
      group='stale'
      summary={`${reviews.length} review${reviews.length === 1 ? '' : 's'} went stale`}
      detail='the draft, voice, account or sources changed after they were prepared'
    >
      <ul className='flex flex-col gap-1.5'>
        {reviews.map((review) => {
          const { manifest } = review;
          const available = draftAvailable(manifest.variantId);
          const text = manifest.payload.text.trim();
          return (
            <CollectionRow
              as='li'
              key={review.id}
              className='flex-wrap'
              leading={<ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />}
              title={
                <span className='flex min-w-0 flex-wrap items-center gap-x-2'>
                  <span className='truncate'>
                    {manifest.platform} · {manifest.account}
                  </span>
                  <span className='text-muted-foreground text-xs font-normal'>{manifest.timing.local.replace('T', ' ')}</span>
                </span>
              }
              meta={
                <span className='truncate'>
                  {text.slice(0, 60)}
                  {text.length > 60 ? '…' : ''}
                </span>
              }
              actions={
                canSchedule && (
                  <Button
                    variant='glass'
                    size='control'
                    className='h-11 px-3.5 text-[13px]'
                    disabled={!available}
                    title={available ? 'Prepare a new review of the same draft' : 'This draft is no longer available'}
                    onClick={() => onPrepareAgain(manifest.variantId)}
                  >
                    Prepare again
                  </Button>
                )
              }
            />
          );
        })}
      </ul>
    </ReviewDisclosure>
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
    <ReviewDisclosure
      group='dupes'
      summary={`${reviews.length} review${reviews.length === 1 ? ' is' : 's are'} already a job`}
      detail='the same post, account and time was approved before, so approving again schedules nothing'
    >
      <ul className='flex flex-col gap-1.5'>
        {reviews.map((review) => {
          const { manifest } = review;
          const job = jobByKey.get(manifest.idempotencyKey);
          if (!job) return null;
          const ended = ENDED.has(job.state);
          return (
            <CollectionRow
              as='li'
              key={review.id}
              className='flex-wrap'
              leading={<ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />}
              title={
                <span className='flex min-w-0 flex-wrap items-center gap-x-2'>
                  <span className='truncate'>
                    {manifest.platform} · {manifest.account}
                  </span>
                  <span className='text-muted-foreground text-xs font-normal'>{manifest.timing.local.replace('T', ' ')}</span>
                </span>
              }
              meta={ended ? 'That job has ended. To post this draft again, prepare a review for a different time.' : undefined}
              state={<JobStateBadge job={job} />}
              actions={
                <Button variant='glass' size='control' className='h-11 px-3.5 text-[13px]' onClick={() => onOpenJob(job.id)}>
                  Open job
                </Button>
              }
            />
          );
        })}
      </ul>
    </ReviewDisclosure>
  );
}

function LoadError({ error, hasData, updatedAt, onRetry }: { error: unknown; hasData: boolean; updatedAt: number; onRetry: () => Promise<{ isError: boolean }> }) {
  const [outcome, flash] = useFlash<'success' | 'error'>();
  const [retrying, setRetrying] = useState(false);
  return (
    <StateMessage
      kind={hasData ? 'stale' : 'error'}
      title={hasData ? 'The queue could not be refreshed.' : 'The queue could not be loaded.'}
      description={
        <>
          {errorMessage(error, '')}
          {hasData && ` Showing what was loaded ${relativeTime(updatedAt / 1000)}.`}
        </>
      }
      action={
        <StatefulButton
          variant='secondary'
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
      }
    />
  );
}

/** The first-run teaching block: what belongs here and the one action that starts it (DNA §20.1). */
function FirstRun({ canSchedule, hasDrafts, hasReadyAccount, onSchedule }: { canSchedule: boolean; hasDrafts: boolean; hasReadyAccount: boolean; onSchedule: () => void }) {
  const steps = [
    { title: 'Schedule a draft', text: 'Pick a draft, an account and an exact time.' },
    { title: 'Approve it here', text: 'Approve the exact text, media and time.' },
    { title: 'The worker publishes', text: 'At that time, and it records what the provider confirmed.' }
  ];
  return (
    <Surface material='quiet' radius='card' padding='lg' className='flex flex-col items-center gap-5 text-center' data-tour='queue-approvals'>
      <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 shrink-0 items-center justify-center rounded-full'>
        <Icons.listDetails className='size-5' />
      </span>
      <div className='flex max-w-md flex-col gap-1'>
        <h2 className='text-foreground text-base font-medium text-balance'>Nothing publishes on its own</h2>
        <p className='text-muted-foreground text-sm leading-relaxed'>Every post goes through the same three steps.</p>
      </div>
      <ol className='grid w-full max-w-2xl gap-3 text-left sm:grid-cols-3'>
        {steps.map((step, index) => (
          <li key={step.title} className='rafii-glass flex gap-3 rounded-[var(--rafii-radius-control)] p-4 sm:flex-col sm:gap-2'>
            <span className='rafii-quiet text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-xs tabular-nums'>{index + 1}</span>
            <span className='flex flex-col gap-0.5'>
              <span className='text-sm font-medium'>{step.title}</span>
              <span className='text-muted-foreground text-xs leading-relaxed'>{step.text}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className='flex flex-wrap justify-center gap-2'>
        {canSchedule && (
          <Button variant='action' size='control' onClick={onSchedule}>
            Schedule a draft
          </Button>
        )}
        {!hasDrafts && (
          <Link href='/app/ideas' className={buttonVariants({ variant: canSchedule ? 'glass' : 'action', size: 'control' })}>
            Draft something in Ideas
          </Link>
        )}
      </div>
      {!hasReadyAccount && (
        <p className='text-muted-foreground text-xs'>
          Connect and verify an account first; a review can only be prepared for an account that is ready for posting.{' '}
          <Link href='/app/channels' className='text-foreground underline underline-offset-2'>
            Open Channels
          </Link>
        </p>
      )}
    </Surface>
  );
}

const QUEUE_VIEWS = ['queue', 'drafts'] as const;

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
  const { reduced } = useMotionPreference();
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
  const draftCount = useDraftCount();
  const [params, setParams] = useQueryStates(
    {
      filter: parseAsStringLiteral(FILTER_VALUES).withDefault('all'),
      // Drafts not yet scheduled (the Pipeline board's drafts column, folded into Queue in Rafii v9).
      view: parseAsStringLiteral(QUEUE_VIEWS).withDefault('queue'),
      job: parseAsString,
      asset: parseAsString,
      channel: parseAsString
    },
    { history: 'replace', scroll: false }
  );
  // A new key per opening, so "Prepare again" preselects its draft in a fresh dialog.
  const [scheduling, setScheduling] = useState<{ open: boolean; variantId: string | null; assetId?: string; key: number }>({ open: false, variantId: null, key: 0 });
  useEffect(() => {
    if (!params.asset || !snapshot.data || !access.hasWorkspace) return;
    const assetId = params.asset;
    if (canSchedule && snapshot.data.state.phase2?.assets.some((asset) => asset.id === assetId && !asset.deleted)) {
      setScheduling((previous) => ({ open: true, variantId: null, assetId, key: previous.key + 1 }));
    } else {
      toast.error(canSchedule ? 'This image is no longer available.' : 'Preparing a post requires approval permission.');
    }
    void setParams({ asset: null });
  }, [params.asset, snapshot.data, access.hasWorkspace, canSchedule, setParams]);
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

  // Counts only from a loaded snapshot: while loading there is no number to show, not a zero.
  const filterOptions = FILTERS.map((option) => ({
    value: option.value,
    label: (
      <>
        {option.label}
        {loaded && <DigitSwap value={jobs.filter((job) => matchesFilter(job.state, option.value)).length} className='text-muted-foreground text-xs' />}
      </>
    )
  }));

  return (
    <PageContainer
      pageTitle='Queue'
      pageDescription='Drafts waiting to be scheduled, approvals waiting on you, then everything the worker is handling.'
      infoContent={infoContent}
      pageHeaderAction={
        canSchedule ? (
          <Button variant='action' size='control' data-tour='queue-schedule' onClick={() => openSchedule()}>
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
        assetId={scheduling.assetId}
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
      <JobDetailSheet
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
        <div data-tour='queue-tabs' className='relative scrollbar-hide max-w-full min-w-0 overflow-x-auto py-0.5'>
          <SegmentedControl
            label='Queue view'
            pattern='tabs'
            value={params.view}
            onChange={(value) => void setParams({ view: value, job: null })}
            widths='content'
            options={[
              { value: 'queue', label: 'Queue', title: 'Approvals waiting on you, then everything the worker is handling' },
              {
                value: 'drafts',
                title: 'Drafts that are not scheduled yet',
                label: (
                  <>
                    Drafts
                    {draftCount !== null && <DigitSwap value={draftCount} className='text-muted-foreground text-xs' />}
                  </>
                )
              }
            ]}
          />
        </div>
        {params.view === 'drafts' ? (
          <DraftsPanel />
        ) : (
        <>
        {sample ? (
          <StateMessage kind='unsupported' layout='inline' title='Sample workspaces are read-only.' description='Nothing here can be scheduled, approved or cancelled.' />
        ) : (
          !canApprove &&
          canEdit && (
            <StateMessage
              kind='permission'
              layout='inline'
              title='Scheduling, approving and cancelling posts is for the owner, approvers and members who can approve publications.'
            />
          )
        )}
        {snapshot.isError && (
          <LoadError error={snapshot.error} hasData={loaded} updatedAt={snapshot.dataUpdatedAt} onRetry={() => snapshot.refetch()} />
        )}

        {channelId && loaded && (
          <ActiveFilters
            count={1}
            summary={
              channelFilter ? (
                <span className='inline-flex items-center gap-1.5 align-middle'>
                  <ChannelIcon platform={channelFilter.platform} name={channelFilter.platform} size='xs' />
                  Showing {channelFilter.platform} · {channelFilter.account}
                </span>
              ) : (
                'Showing one account that is no longer in this workspace'
              )
            }
            onClear={() => void setParams({ channel: null })}
            clearLabel='Show all accounts'
          />
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
              <section className='flex flex-col gap-4' aria-labelledby='approvals-heading' data-tour='queue-approvals'>
                <div className='flex flex-wrap items-center justify-between gap-3'>
                  <SectionHeading id='approvals-heading' count={reviews.length}>
                    Waiting for approval
                  </SectionHeading>
                  {/* The batch action only exists while there is a batch to confirm; the dialog lists exactly what it sends. */}
                  {approvable.length >= 2 && (
                    <Button variant='glass' size='control' onClick={() => setBatch({ open: true, reviews: approvable.slice(0, APPROVE_MANY_LIMIT) })}>
                      <Icons.checks />
                      {approvable.length > APPROVE_MANY_LIMIT ? `Approve the first ${APPROVE_MANY_LIMIT}` : `Approve all ${approvable.length}`}
                    </Button>
                  )}
                </div>
                {loading ? (
                  <StateMessage kind='loading' title='Loading the reviews waiting for you' />
                ) : (
                  <AnimatePresence mode='wait' initial={false}>
                    {reviews.length === 0 ? (
                      <motion.div key='none' initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.18, ease: EASE_OUT }}>
                        <StateMessage
                          kind='empty'
                          title={channelId ? 'Nothing from this account is waiting for approval.' : 'Nothing to approve.'}
                          description={channelId ? undefined : 'Use “Schedule a draft” to prepare one for a channel and time.'}
                        />
                      </motion.div>
                    ) : (
                      <motion.div key='reviews' exit={REVIEW_EXIT} className='grid gap-4 min-[1400px]:grid-cols-2'>
                        <AnimatePresence>
                          {reviews.map((review, index) => (
                            <motion.div
                              key={review.id}
                              layout={reduced ? false : 'position'}
                              initial={reduced ? false : { opacity: 0, y: 8 }}
                              animate={{ opacity: 1, y: 0, transition: { duration: REVIEW_ENTER_S, ease: EASE_OUT } }}
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

              <section className='flex flex-col gap-4' aria-labelledby='jobs-heading' data-tour='queue-list'>
                <div className='flex flex-col gap-3'>
                  <div className='flex flex-col gap-0.5'>
                    <SectionHeading id='jobs-heading'>Publishing jobs</SectionHeading>
                    {loaded && (
                      <p className='text-muted-foreground text-xs'>
                        {workerActivity === null ? 'No worker events recorded yet' : `Latest worker event on a job · ${relativeTime(workerActivity, nowSeconds)}`}
                      </p>
                    )}
                  </div>
                  {/* The counts widen the segments: on a narrow screen the group scrolls sideways instead of pushing the page wider. */}
                  <div data-tour='queue-filters' className='relative scrollbar-hide -mx-1 max-w-full overflow-x-auto px-1 py-0.5'>
                    <SegmentedControl
                      options={filterOptions}
                      value={params.filter}
                      onChange={(value) => void setParams({ filter: value })}
                      pattern='tabs'
                      panelIds={FILTERS.map(() => 'queue-jobs-list')}
                      label='Filter jobs'
                      widths='content'
                      className='[&_button]:gap-1.5'
                    />
                  </div>
                </div>
                <div ref={listRef} id='queue-jobs-list' role='tabpanel' aria-labelledby='jobs-heading' className='@container min-w-0'>
                  {loading ? (
                    <StateMessage kind='loading' title='Loading publishing jobs' />
                  ) : visible.length === 0 ? (
                    <StateMessage kind='empty' title={params.filter === 'all' ? 'No jobs yet' : `No ${filterLabel.label.toLowerCase()} jobs`} description={filterLabel.empty} />
                  ) : asTable ? (
                    <Surface material='quiet' radius='card' padding='none' className='relative overflow-x-auto'>
                      <Table>
                        <TableHeader className='[&_tr]:border-0'>
                          <TableRow className='border-0 hover:bg-transparent'>
                            <TableHead className='rafii-eyebrow text-muted-foreground h-11 px-4'>State</TableHead>
                            <TableHead className='rafii-eyebrow text-muted-foreground h-11 px-3'>Destination</TableHead>
                            <TableHead className='rafii-eyebrow text-muted-foreground h-11 px-3'>Scheduled</TableHead>
                            <TableHead className='rafii-eyebrow text-muted-foreground h-11 px-3'>Attempts</TableHead>
                            <TableHead className='rafii-eyebrow text-muted-foreground hidden h-11 px-3 @min-[76rem]:table-cell'>Provider</TableHead>
                            <TableHead className='rafii-eyebrow text-muted-foreground hidden h-11 px-3 @min-[66rem]:table-cell'>Last event</TableHead>
                            <TableHead className='h-11 px-4'>
                              <span className='sr-only'>Actions</span>
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {visible.map((job, index) => (
                            <JobRow key={job.id} job={job} layout='table' tourRow={index === 0} tourCancel={job.id === firstCancellable} {...rowProps} />
                          ))}
                        </TableBody>
                      </Table>
                    </Surface>
                  ) : (
                    <ul className='flex flex-col gap-2'>
                      {visible.map((job, index) => (
                        <JobRow key={job.id} job={job} layout='card' tourRow={index === 0} tourCancel={job.id === firstCancellable} {...rowProps} />
                      ))}
                    </ul>
                  )}
                </div>
              </section>
            </>
          )
        )}
        </>
        )}
      </div>
    </PageContainer>
  );
}
