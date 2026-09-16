'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Job, Review } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDateTime, relativeTime } from '@/lib/time';

const WAITING = new Set(['scheduled', 'approved', 'claimed']);
const IN_FLIGHT = new Set(['submitting', 'provider_accepted', 'published', 'uncertain']);
const DONE = new Set(['verified']);
const FAILED = new Set(['failed', 'canceled']);

type Filter = 'all' | 'waiting' | 'in-flight' | 'done' | 'failed';

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

function stateTone(state: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (DONE.has(state)) return 'default';
  if (FAILED.has(state)) return 'destructive';
  if (IN_FLIGHT.has(state)) return 'secondary';
  return 'outline';
}

function epochOf(iso: string | undefined) {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

function ReviewCard({ review, revision, canApprove }: { review: Review; revision: number; canApprove: boolean }) {
  const act = useAct();
  const manifest = review.manifest;
  const expired = manifest.expiresAt <= Date.now() / 1000;
  return (
    <Card>
      <CardHeader>
        <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
          {manifest.platform} · {manifest.account}
          <Badge variant={review.status === 'needs_review' ? 'default' : 'outline'}>{review.status.replace(/_/g, ' ')}</Badge>
          {expired && <Badge variant='destructive'>expired</Badge>}
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
          <Button
            disabled={act.isPending || expired}
            onClick={() =>
              act.mutate(
                { revision, action: 'p2_approve', payload: { reviewId: review.id, digest: review.digest, confirmed: true } },
                {
                  onSuccess: () => toast.success('Approved and scheduled.'),
                  onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Approval failed.')
                }
              )
            }
          >
            Approve & schedule
          </Button>
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
  const canApprove = checkAccess(access, { permission: 'approve' });
  const [filter, setFilter] = useState<Filter>('all');

  const reviews = (snapshot.data?.state.phase2?.reviews ?? []).filter((r) => r.status === 'needs_review');
  const jobs = (snapshot.data?.state.phase2?.jobs ?? []).toSorted((a, b) => (epochOf(b.manifest.timing.utc) ?? 0) - (epochOf(a.manifest.timing.utc) ?? 0));
  const visible = jobs.filter((job) => {
    if (filter === 'waiting') return WAITING.has(job.state);
    if (filter === 'in-flight') return IN_FLIGHT.has(job.state);
    if (filter === 'done') return DONE.has(job.state);
    if (filter === 'failed') return FAILED.has(job.state);
    return true;
  });
  const revision = snapshot.data?.revision ?? 0;

  function cancel(job: Job) {
    act.mutate(
      { revision, action: 'p2_cancel', payload: { jobId: job.id } },
      {
        onSuccess: () => toast.success('Cancel requested.'),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not cancel.')
      }
    );
  }

  return (
    <PageContainer pageTitle='Queue' pageDescription='Approvals waiting on you, then everything the worker is handling.' infoContent={infoContent}>
      <div className='flex flex-col gap-8'>
        <section className='flex flex-col gap-3' aria-labelledby='approvals-heading'>
          <h3 id='approvals-heading' className='text-lg font-semibold'>
            Waiting for approval {reviews.length > 0 && <Badge className='ml-1'>{reviews.length}</Badge>}
          </h3>
          {snapshot.isLoading ? (
            <Skeleton className='h-32 w-full' />
          ) : reviews.length === 0 ? (
            <p className='text-muted-foreground text-sm'>Nothing to approve. Prepare a draft for a channel from Ideas or the Pipeline.</p>
          ) : (
            <div className='grid gap-4 xl:grid-cols-2'>
              {reviews.map((review) => (
                <ReviewCard key={review.id} review={review} revision={revision} canApprove={canApprove} />
              ))}
            </div>
          )}
        </section>

        <section className='flex flex-col gap-3' aria-labelledby='jobs-heading'>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <h3 id='jobs-heading' className='text-lg font-semibold'>
              Publishing jobs
            </h3>
            <Tabs value={filter} onValueChange={(value) => setFilter(value as Filter)}>
              <TabsList>
                <TabsTrigger value='all'>All</TabsTrigger>
                <TabsTrigger value='waiting'>Waiting</TabsTrigger>
                <TabsTrigger value='in-flight'>In flight</TabsTrigger>
                <TabsTrigger value='done'>Verified</TabsTrigger>
                <TabsTrigger value='failed'>Failed</TabsTrigger>
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
                  {visible.map((job) => {
                    const last = job.events[job.events.length - 1];
                    return (
                      <TableRow key={job.id}>
                        <TableCell>
                          <Badge variant={stateTone(job.state)}>{job.state.replace(/_/g, ' ')}</Badge>
                        </TableCell>
                        <TableCell>
                          {job.manifest.platform}
                          <span className='text-muted-foreground'> · {job.manifest.account}</span>
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
                            <Button variant='ghost' size='sm' disabled={act.isPending} onClick={() => cancel(job)}>
                              Cancel
                            </Button>
                          )}
                          {job.cancelRequested && <span className='text-muted-foreground text-xs'>cancelling…</span>}
                        </TableCell>
                      </TableRow>
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
