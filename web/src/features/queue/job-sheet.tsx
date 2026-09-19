'use client';

import { useState, type CSSProperties, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { JobCancelHold } from '@/components/jobs/job-cancel-hold';
import { Button } from '@/components/ui/button';
import { Drawer, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle } from '@/components/ui/drawer';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useMe } from '@/lib/api/hooks';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { FixtureBadge, JobStateBadge } from './job-row';
import {
  canCancel,
  DONE,
  ENDED,
  epochOf,
  HELD,
  isSynthetic,
  MAX_ATTEMPTS,
  PUBLISHING,
  stateStatus,
  stateWords,
  workerNote,
  type QueueJob
} from './job-state';
import { useWide } from './use-wide';

/**
 * Timeline rows that take part in the entrance stagger; later rows are simply there. The library's 500ms line reveal
 * is shortened here so the whole entrance stays within the 300ms cap (motion system §5): 2 × 40ms + 220ms.
 */
const STAGGERED_ROWS = 3;
const TIMELINE_STAGGER_STYLE = { '--stagger-dur': '220ms' } as CSSProperties;

export interface JobSheetProps {
  /** `?job=` from the URL; the sheet is open while it is set and the snapshot has loaded. */
  jobId: string | null;
  jobs: QueueJob[];
  ready: boolean;
  nowSeconds: number;
  canApprove: boolean;
  canSchedule: boolean;
  cancelPending: boolean;
  holdEpoch: number;
  onClose: () => void;
  onCancel: (job: QueueJob) => void;
  onPrepareAgain: (variantId: string) => void;
  /** False when the job's draft was deleted or blocked by a retraction. */
  draftAvailable: (variantId: string) => boolean;
}

function Row({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className='grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 py-1.5'>
      <dt className='text-muted-foreground text-xs'>{label}</dt>
      <dd className={cn('min-w-0 text-sm break-words', mono && 'font-mono text-xs')}>{children}</dd>
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  return (
    <Button
      variant='ghost'
      size='icon-xs'
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          toast.success(`${label} copied.`);
        } catch {
          toast.error('Could not copy.');
        }
      }}
    >
      <Icons.copy />
    </Button>
  );
}

function Heading({ children }: { children: ReactNode }) {
  return <h3 className='text-xs font-medium tracking-wide uppercase'>{children}</h3>;
}

function Approved({ job, jobs }: { job: QueueJob; jobs: QueueJob[] }) {
  const { manifest } = job;
  const together = job.scheduleId ? jobs.filter((other) => other.id !== job.id && other.scheduleId === job.scheduleId).length : 0;
  return (
    <section className='flex flex-col gap-3'>
      <Heading>What was approved</Heading>
      <div className='flex flex-col gap-4'>
        <ManifestPreview manifest={manifest} scale={0.6} />
        <dl className='divide-y'>
          <Row label='Time'>
            {manifest.timing.local.replace('T', ' ')} ({manifest.timing.timeZone})
            <span className='text-muted-foreground block text-xs'>{formatDateTime(epochOf(manifest.timing.utc))} in your time</span>
          </Row>
          <Row label='Language'>{manifest.payload.language}</Row>
          <Row label='Media'>{manifest.media.length === 0 ? 'Text only' : `${manifest.media.length} attached`}</Row>
          {job.approvalDigest && (
            <Row label='Approval digest' mono>
              <span className='flex items-start gap-1'>
                <span className='min-w-0 break-all'>{job.approvalDigest}</span>
                <CopyButton value={job.approvalDigest} label='Approval digest' />
              </span>
            </Row>
          )}
          {together > 0 && (
            <Row label='Schedule'>
              Approved together with {together} other post{together === 1 ? '' : 's'}; each keeps its own state.
            </Row>
          )}
        </dl>
      </div>
    </section>
  );
}

function Timeline({ job }: { job: QueueJob }) {
  return (
    <section className='flex flex-col gap-2'>
      <Heading>Timeline</Heading>
      {job.events.length === 0 ? (
        <p className='text-muted-foreground text-sm'>No events recorded.</p>
      ) : (
        <ol className='flex flex-col' style={TIMELINE_STAGGER_STYLE}>
          {job.events.map((event, index) => (
            <li
              // Events are append-only, so their position is a stable identity.
              // oxlint-disable-next-line react/no-array-index-key
              key={index}
              className={cn('grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 border-l py-2 pl-3', index < STAGGERED_ROWS && 't-stagger-line')}
              style={index < STAGGERED_ROWS ? ({ '--stagger-i': index } as CSSProperties) : undefined}
            >
              <span className='flex flex-wrap items-center gap-2'>
                <AnimatedBadge size='sm' status={stateStatus(event.state)} pulse={false}>
                  {stateWords(event.state)}
                </AnimatedBadge>
                <time className='text-muted-foreground text-xs tabular-nums' dateTime={new Date(event.at * 1000).toISOString()}>
                  {formatDateTime(event.at)}
                </time>
              </span>
              {event.execution && <span className='text-muted-foreground text-right text-xs'>{event.execution.replace(/-/g, ' ')}</span>}
              <p className='col-span-2 text-sm'>{event.message}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Attempts({ job }: { job: QueueJob }) {
  // Only a claimed or submitting job has an attempt under way; an unconfirmed one is being reconciled instead.
  const running = PUBLISHING.has(job.state) || job.state === 'claimed';
  return (
    <section className='flex flex-col gap-2'>
      <Heading>
        Attempts · {job.attempts.length} of {MAX_ATTEMPTS}
      </Heading>
      {job.attempts.length === 0 ? (
        <p className='text-muted-foreground text-sm'>The worker has not started this job.</p>
      ) : (
        <ul className='flex flex-col gap-1 text-sm'>
          {job.attempts.map((attempt, index) => {
            const isLast = index === job.attempts.length - 1;
            return (
              <li key={attempt.number} className='flex flex-wrap gap-x-2'>
                <span className='font-medium'>#{attempt.number}</span>
                <span>started {formatDateTime(attempt.startedAt)}</span>
                <span className='text-muted-foreground'>
                  {attempt.endedAt ? `ended ${formatDateTime(attempt.endedAt)}` : isLast && running ? 'still running' : 'no end recorded'}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Provider({ job, nowSeconds }: { job: QueueJob; nowSeconds: number }) {
  const settled = DONE.has(job.state) || ENDED.has(job.state) || HELD.has(job.state);
  const note = workerNote(job);
  return (
    <section className='flex flex-col gap-2'>
      <Heading>Provider</Heading>
      <dl className='divide-y'>
        <Row label='Reference' mono>
          {job.providerReference ? (
            <span className='flex items-start gap-1'>
              <span className='min-w-0 break-all'>{job.providerReference}</span>
              <CopyButton value={job.providerReference} label='Provider reference' />
            </span>
          ) : (
            <span className='text-muted-foreground font-sans text-sm'>None yet</span>
          )}
        </Row>
        <Row label='Provider said'>{job.providerConfirmed || <span className='text-muted-foreground'>Nothing yet</span>}</Row>
        <Row label='Verification'>
          {job.verification ? `${job.verification.method.replace(/_/g, ' ')} · ${formatDateTime(job.verification.at)}` : <span className='text-muted-foreground'>Not verified</span>}
        </Row>
        {typeof job.checks === 'number' && job.checks > 0 && <Row label='Checks'>{job.checks} reconciliation check{job.checks === 1 ? '' : 's'}</Row>}
        {!settled && typeof job.nextAt === 'number' && job.nextAt > 0 && (
          <Row label='Next look'>
            {formatDateTime(job.nextAt)} · {relativeTime(job.nextAt, nowSeconds)}
          </Row>
        )}
      </dl>
      {job.url && (
        <a href={job.url} target='_blank' rel='noreferrer' className='text-primary inline-flex items-center gap-1 text-sm hover:underline'>
          Open post <Icons.externalLink className='size-3.5' />
        </a>
      )}
      {note && (
        <p className='bg-muted/60 rounded-md border px-3 py-2 text-sm'>
          <span className='text-muted-foreground block text-xs'>Last worker note</span>
          {note}
        </p>
      )}
    </section>
  );
}

function ApprovedBy({ job }: { job: QueueJob }) {
  const me = useMe();
  if (!job.approvedAt && !job.approvedBy) return null;
  // `/members` has no display names, so a teammate stays "a teammate" rather than a raw id.
  const who = !job.approvedBy || !me.data ? 'Approved' : job.approvedBy === me.data.userId ? 'Approved by you' : 'Approved by a teammate';
  return (
    <p className='text-muted-foreground text-xs'>
      {who}
      {job.approvedAt ? ` · ${formatDateTime(job.approvedAt)}` : ''}
    </p>
  );
}

function FooterActions({ job, canApprove, canSchedule, cancelPending, holdEpoch, onCancel, onPrepareAgain, draftAvailable }: JobSheetProps & { job: QueueJob }) {
  const prepare = canSchedule && (HELD.has(job.state) || job.state === 'failed');
  const cancel = canApprove && canCancel(job);
  if (!prepare && !cancel) return null;
  const available = draftAvailable(job.manifest.variantId);
  return (
    <div className='flex flex-wrap items-center gap-2'>
      {prepare && (
        <Button
          variant='outline'
          size='sm'
          disabled={!available}
          title={available ? 'Prepare a new review of the same draft' : 'This draft is no longer available'}
          onClick={() => onPrepareAgain(job.manifest.variantId)}
        >
          <Icons.refresh />
          Prepare again
        </Button>
      )}
      {cancel && (
        <JobCancelHold key={`cancel-${job.id}`} job={job} allowed={canApprove} pending={cancelPending} epoch={holdEpoch} onCancel={onCancel} />
      )}
    </div>
  );
}

/** The full receipt of one job: what was approved, every event, every attempt, and what the provider confirmed. */
export function JobSheet(props: JobSheetProps) {
  const { jobId, jobs, ready, nowSeconds, onClose } = props;
  const wide = useWide();
  const open = ready && jobId !== null;
  const found = jobId ? (jobs.find((job) => job.id === jobId) ?? null) : null;
  // The last job shown stays on screen while the panel closes.
  const [kept, setKept] = useState<QueueJob | null>(found);
  if (found && found !== kept) setKept(found);
  const job = jobId ? found : kept;

  const title = job ? (
    <span className='flex flex-wrap items-center gap-2'>
      <ChannelIcon platform={job.manifest.platform} name={job.manifest.platform} />
      {job.manifest.platform} · {job.manifest.account}
    </span>
  ) : (
    'Job not found'
  );
  const description = job ? (
    <span className='flex flex-wrap items-center gap-2'>
      <JobStateBadge job={job} />
      {isSynthetic(job) && <FixtureBadge />}
    </span>
  ) : (
    'This job is not in the workspace. It may belong to another workspace, or the link is out of date.'
  );
  const body = job ? (
    <div className='flex flex-col gap-5'>
      <Approved job={job} jobs={jobs} />
      <Separator />
      <Timeline job={job} />
      <Separator />
      <Attempts job={job} />
      <Separator />
      <Provider job={job} nowSeconds={nowSeconds} />
    </div>
  ) : null;
  const footer = job ? (
    <>
      <ApprovedBy job={job} />
      <FooterActions {...props} job={job} />
    </>
  ) : (
    <Button variant='outline' size='sm' className='self-start' onClick={onClose}>
      Close
    </Button>
  );
  const onOpenChange = (next: boolean) => {
    if (!next) onClose();
  };

  if (!wide) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange}>
        <DrawerContent>
          <DrawerHeader className='text-left group-data-[swipe-axis=y]/drawer-popup:text-left'>
            <DrawerTitle>{title}</DrawerTitle>
            <DrawerDescription>{description}</DrawerDescription>
          </DrawerHeader>
          {body && <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain p-4'>{body}</div>}
          <DrawerFooter className='border-t pt-4'>{footer}</DrawerFooter>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side='right' className='gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-lg'>
        <SheetHeader className='border-b pr-12'>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        {body && <div className='min-h-0 flex-1 overflow-y-auto p-4'>{body}</div>}
        <SheetFooter className='border-t'>{footer}</SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
