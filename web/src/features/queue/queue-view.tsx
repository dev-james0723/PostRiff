'use client';

import { useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { DigitSwap } from '@/components/motion/digit-swap';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Job, Review } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { ScheduleDialog } from './schedule-dialog';
import { useFlash } from '@/hooks/use-flash';

const WAITING = new Set(['scheduled', 'approved', 'claimed']);
const IN_FLIGHT = new Set(['submitting', 'provider_accepted', 'published', 'uncertain']);
const DONE = new Set(['verified']);
const FAILED = new Set(['failed', 'canceled']);

type Filter = 'all' | 'waiting' | 'in-flight' | 'done' | 'failed';

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'waiting', label: 'Waiting' },
  { value: 'in-flight', label: 'In flight' },
  { value: 'done', label: 'Verified' },
  { value: 'failed', label: 'Failed' }
];

// Sized for a table cell, with the corner radius of the app's small buttons.
const HOLD_CANCEL_CLASS = 'h-7 min-w-0 bg-secondary px-3 text-secondary-foreground [--hold-radius:min(var(--radius-md),12px)]';
// An opaque destructive tint for both the fill and its liquid edge, so the two meet without a seam.
const HOLD_CANCEL_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const HOLD_CANCEL_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';

// A card leaving the approvals list stays long enough to show how its approval ended.
const REVIEW_EXIT = { opacity: 0, transition: { duration: 0.22, ease: EASE_OUT, delay: 0.6 } };

const MotionTableRow = motion.create(TableRow);

const infoContent = {
  title: 'Approvals and the queue',
  sections: [
    {
      title: 'Exact approvals',
      description:
        'A review freezes the text, media, account and time into a manifest with a digest. Approving that digest is the only way a post enters the queue.'
    },
    {
      title: 'Job states',
      description:
        'Waiting → in flight → verified. “Uncertain” means the provider did not confirm; PostRiff reconciles before it ever retries, so nothing is posted twice.'
    },
    { title: 'Cancel', description: 'Waiting jobs can be cancelled until the worker claims them.' }
  ]
};

function stateStatus(state: string): AnimatedBadgeStatus {
  if (WAITING.has(state)) return 'info';
  if (IN_FLIGHT.has(state)) return 'loading';
  if (DONE.has(state)) return 'success';
  if (state === 'failed') return 'danger';
  return 'neutral';
}

function matchesFilter(state: string, filter: Filter) {
  if (filter === 'waiting') return WAITING.has(state);
  if (filter === 'in-flight') return IN_FLIGHT.has(state);
  if (filter === 'done') return DONE.has(state);
  if (filter === 'failed') return FAILED.has(state);
  return true;
}

function epochOf(iso: string | undefined) {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

function ReviewCard({ review, revision, canApprove }: { review: Review; revision: number; canApprove: boolean }) {
  const act = useAct();
  const [outcome, flashOutcome] = useFlash<'success' | 'error'>();
  const manifest = review.manifest;
  const expired = manifest.expiresAt <= Date.now() / 1000;
  const needsReview = review.status === 'needs_review';
  return (
    <Card className='h-full'>
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
        </CardTitle>
        <CardDescription>
          {manifest.timing.local} ({manifest.timing.timeZone}) · {manifest.payload.language} · {manifest.media.length} media ·{' '}
          <span className='font-mono'>{review.digest.slice(0, 12)}…</span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className='line-clamp-6 text-sm whitespace-pre-wrap'>{manifest.payload.text}</p>
      </CardContent>
      {canApprove && review.status === 'needs_review' && (
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
                  onSuccess: () => {
                    toast.success('Approved and scheduled.');
                    flashOutcome('success');
                  },
                  onError: (err) => {
                    toast.error(err instanceof ApiError ? err.message : 'Approval failed.');
                    flashOutcome('error');
                  }
                }
              );
            }}
          >
            Approve & schedule
          </StatefulButton>
          <span className='text-muted-foreground text-xs'>
            {expired ? 'The review window closed; prepare it again from the draft.' : 'Approves exactly this text, media, account and time.'}
          </span>
        </CardFooter>
      )}
    </Card>
  );
}

export function QueueView() {
  const snapshot = useSnapshot();
  const act = useAct();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  const canApprove = checkAccess(access, { permission: 'approve' });
  const [filter, setFilter] = useState<Filter>('all');
  const [scheduling, setScheduling] = useState(false);
  // A hold button goes disabled mid-press while its cancel is pending, so its release can go unheard. After a failed
  // cancel the buttons remount instead of staying stuck on "Cancelling…"; a successful one takes the button away.
  const [holdEpoch, setHoldEpoch] = useState(0);

  const reviews = (snapshot.data?.state.phase2?.reviews ?? []).filter((r) => r.status === 'needs_review');
  const jobs = (snapshot.data?.state.phase2?.jobs ?? []).toSorted((a, b) => (epochOf(b.manifest.timing.utc) ?? 0) - (epochOf(a.manifest.timing.utc) ?? 0));
  const visible = jobs.filter((job) => matchesFilter(job.state, filter));
  const revision = snapshot.data?.revision ?? 0;

  function cancel(job: Job) {
    act.mutate(
      { revision, action: 'p2_cancel', payload: { jobId: job.id } },
      {
        onSuccess: () => toast.success('Cancel requested.'),
        onError: (err) => {
          toast.error(err instanceof ApiError ? err.message : 'Could not cancel.');
          setHoldEpoch((epoch) => epoch + 1);
        }
      }
    );
  }

  return (
    <PageContainer
      pageTitle='Queue'
      pageDescription='Approvals waiting on you, then everything the worker is handling.'
      infoContent={infoContent}
      pageHeaderAction={
        canApprove || checkAccess(access, { permission: 'edit' }) ? (
          <Button onClick={() => setScheduling(true)}>Schedule a draft</Button>
        ) : undefined
      }
    >
      <ScheduleDialog open={scheduling} onOpenChange={setScheduling} />
      <div className='flex flex-col gap-8'>
        <section className='flex flex-col gap-3' aria-labelledby='approvals-heading'>
          <h3 id='approvals-heading' className='text-lg font-semibold'>
            Waiting for approval{' '}
            {reviews.length > 0 && (
              <Badge className='ml-1'>
                <DigitSwap value={reviews.length} />
              </Badge>
            )}
          </h3>
          {snapshot.isLoading ? (
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
                  Nothing to approve. Use “Schedule a draft” to prepare one for a channel and time.
                </motion.p>
              ) : (
                <motion.div key='reviews' exit={REVIEW_EXIT} className='grid gap-4 xl:grid-cols-2'>
                  <AnimatePresence>
                    {reviews.map((review, index) => (
                      <motion.div
                        key={review.id}
                        layout={reduce ? false : 'position'}
                        initial={reduce ? false : { opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0, transition: { duration: 0.28, ease: EASE_OUT, delay: Math.min(index, 6) * 0.05 } }}
                        exit={REVIEW_EXIT}
                        transition={{ layout: SPRING_LAYOUT }}
                      >
                        <ReviewCard review={review} revision={revision} canApprove={canApprove} />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </motion.div>
              )}
            </AnimatePresence>
          )}
        </section>

        <section className='flex flex-col gap-3' aria-labelledby='jobs-heading'>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <h3 id='jobs-heading' className='text-lg font-semibold'>
              Publishing jobs
            </h3>
            {/* The counts widen the tabs: on a narrow screen the list scrolls sideways instead of pushing the page wider. */}
            <Tabs value={filter} onValueChange={(value) => setFilter(value as Filter)} variant='pill' className='min-w-0 max-w-full'>
              <TabsList aria-label='Filter jobs' className='scrollbar-hide max-w-full overflow-x-auto border'>
                {FILTERS.map((option) => (
                  <TabsTrigger key={option.value} value={option.value} className='gap-1.5 px-3 py-1'>
                    {option.label}
                    <DigitSwap value={jobs.filter((job) => matchesFilter(job.state, option.value)).length} className='text-xs opacity-75' />
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>
          {snapshot.isLoading ? (
            <Skeleton className='h-48 w-full' />
          ) : visible.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <Icons.listDetails />
                </EmptyMedia>
                <EmptyTitle>No jobs here</EmptyTitle>
                <EmptyDescription>Approved posts appear as jobs the worker executes at the approved time.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className='overflow-x-auto rounded-lg border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>State</TableHead>
                    <TableHead>Destination</TableHead>
                    <TableHead>Scheduled</TableHead>
                    <TableHead>Attempts</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Last event</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visible.map((job, index) => {
                    const last = job.events[job.events.length - 1];
                    const stateLabel = job.state.replace(/_/g, ' ');
                    // The cancel flag outlives the cancel: a job that already ended shows how it ended, not "cancelling".
                    const cancelling = job.cancelRequested && !DONE.has(job.state) && !FAILED.has(job.state);
                    return (
                      <MotionTableRow
                        key={job.id}
                        initial={reduce ? false : { opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.24, ease: EASE_OUT, delay: Math.min(index, 10) * 0.03 }}
                      >
                        <TableCell>
                          <AnimatedBadge
                            size='sm'
                            status={cancelling ? 'loading' : stateStatus(job.state)}
                            title={cancelling ? `Cancel requested while ${stateLabel}` : undefined}
                          >
                            {cancelling ? 'cancelling' : stateLabel}
                          </AnimatedBadge>
                        </TableCell>
                        <TableCell>
                          <span className='flex items-center gap-2'>
                            <ChannelIcon platform={job.manifest.platform} name={job.manifest.platform} size='xs' />
                            {job.manifest.platform}
                            <span className='text-muted-foreground'>· {job.manifest.account}</span>
                          </span>
                        </TableCell>
                        <TableCell className='whitespace-nowrap'>{formatDateTime(epochOf(job.manifest.timing.utc))}</TableCell>
                        <TableCell>{job.attempts.length}</TableCell>
                        <TableCell className='max-w-[10rem] truncate font-mono text-xs' title={job.providerReference}>
                          {job.providerReference || job.providerConfirmed || '—'}
                        </TableCell>
                        <TableCell className='text-muted-foreground max-w-[16rem] truncate text-xs' title={last?.message}>
                          {last ? `${last.message} · ${relativeTime(last.at)}` : '—'}
                        </TableCell>
                        <TableCell className='text-right'>
                          {canApprove && WAITING.has(job.state) && !job.cancelRequested && (
                            <HoldActionButton
                              key={holdEpoch}
                              type='horizontal'
                              holdDuration={900}
                              holdingLabel='Keep holding…'
                              completeLabel='Cancelling…'
                              disabled={act.isPending}
                              onHoldComplete={() => cancel(job)}
                              aria-label={`Hold to cancel ${job.manifest.platform} post`}
                              title='Press and hold (or hold Space) to cancel this post before it is submitted.'
                              className={HOLD_CANCEL_CLASS}
                              fillClassName={HOLD_CANCEL_FILL}
                              waveClassName={HOLD_CANCEL_WAVE}
                              labelClassName='text-xs'
                            >
                              Hold to cancel
                            </HoldActionButton>
                          )}
                        </TableCell>
                      </MotionTableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </div>
    </PageContainer>
  );
}
