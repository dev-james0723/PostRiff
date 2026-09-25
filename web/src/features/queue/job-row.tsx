'use client';

import type { MouseEvent, ReactNode } from 'react';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { JobCancelHold } from '@/components/jobs/job-cancel-hold';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { TableCell, TableRow } from '@/components/ui/table';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import {
  canCancel,
  countdown,
  epochOf,
  isSynthetic,
  MAX_ATTEMPTS,
  stateNote,
  WAITING,
  type QueueJob
} from './job-state';
import { jobStatus } from './job-status';
import { StatusChip } from './status-chip';

export interface JobRowProps {
  job: QueueJob;
  layout: 'table' | 'card';
  nowSeconds: number;
  canApprove: boolean;
  /** A cancel is on its way to the server; every hold button waits for it. */
  cancelPending: boolean;
  /** Changes after a failed cancel, so a hold button stuck mid-press remounts. */
  holdEpoch: number;
  /** Tour anchors go on the first row and on the first row that can be cancelled. */
  tourRow?: boolean;
  tourCancel?: boolean;
  onCancel: (job: QueueJob) => void;
  onOpen: (jobId: string) => void;
}

export function JobStateBadge({ job }: { job: QueueJob }) {
  const badge = jobStatus(job);
  return (
    <StatusChip tone={badge.status} pulse={badge.pulse} title={badge.title}>
      {badge.label}
    </StatusChip>
  );
}

export function FixtureBadge() {
  return (
    <StatusChip tone='neutral' showIcon={false} title='Test post; nothing reaches a real account'>
      Test
    </StatusChip>
  );
}

/** A worker's explanation beside a state: icon + text in the monochrome system (DNA §20.4), never a tinted line. */
export function JobNote({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span className={cn('text-muted-foreground flex items-start gap-1.5 text-xs', className)} title={title}>
      <Icons.warning aria-hidden className='mt-0.5 size-3 shrink-0' />
      <span className='min-w-0'>{children}</span>
    </span>
  );
}

/**
 * The reason under a state. A failed post leads with what happened; the worker's own words stay one hover (or one
 * open of its details) away instead of being the headline.
 */
function StateNote({ job, note, className }: { job: QueueJob; note: string; className?: string }) {
  if (job.state === 'failed') {
    return (
      <JobNote className={className} title={note}>
        Couldn’t publish this post
        <span className='sr-only'>: {note}</span>
      </JobNote>
    );
  }
  return (
    <JobNote className={className} title={note}>
      {note}
    </JobNote>
  );
}

function Destination({ job }: { job: QueueJob }) {
  return (
    <span className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1'>
      <ChannelIcon platform={job.manifest.platform} name={job.manifest.platform} size='xs' />
      <span>{job.manifest.platform}</span>
      <span className='text-muted-foreground min-w-0 truncate'>· {job.manifest.account}</span>
      {isSynthetic(job) && <FixtureBadge />}
    </span>
  );
}

/** One representation of when: relative by default (a countdown while it waits), the exact time in the tooltip. */
function Scheduled({ job, nowSeconds }: { job: QueueJob; nowSeconds: number }) {
  const at = epochOf(job.manifest.timing.utc);
  // A waiting job counts down to its time, then reads "due" until the worker changes its state.
  const when = WAITING.has(job.state) && at !== null ? (countdown(at, nowSeconds) ?? 'due') : relativeTime(at, nowSeconds);
  const exact = formatDateTime(at);
  return (
    <time className='whitespace-nowrap tabular-nums' dateTime={at ? new Date(at * 1000).toISOString() : undefined} title={exact}>
      {when}
      <span className='sr-only'> ({exact})</span>
    </time>
  );
}

/** An unconfirmed job's reconciliation checks, which are not attempts: the attempt limit counts submissions only. */
function checksLabel(job: QueueJob) {
  const checks = job.checks ?? 0;
  return job.state === 'uncertain' && checks > 0 ? `${checks} check${checks === 1 ? '' : 's'}` : null;
}

function Actions({ job, canApprove, cancelPending, holdEpoch, tourCancel, onCancel, onOpen, layout }: JobRowProps) {
  return (
    <span className={cn('flex items-center gap-2', layout === 'table' ? 'justify-end' : 'justify-between')}>
      <span className='flex items-center gap-1'>
        <Popover>
          <PopoverTrigger render={<Button variant='quiet' size='icon-control' />} aria-label={`Preview the ${job.manifest.platform} post`} title='Preview'>
            <Icons.eye />
          </PopoverTrigger>
          <PopoverContent align={layout === 'table' ? 'end' : 'start'} className='rafii-elevated w-auto max-w-[calc(100vw-1rem)] rounded-[1.375rem] p-3 shadow-none ring-0'>
            <div className='max-h-[calc(var(--available-height,100vh)-1.5rem)] overflow-y-auto'>
              <ManifestPreview manifest={job.manifest} />
            </div>
          </PopoverContent>
        </Popover>
        <Button
          variant='quiet'
          size='icon-control'
          aria-label={`Open details for the ${job.manifest.platform} post`}
          title='Details'
          onClick={() => onOpen(job.id)}
        >
          <Icons.history />
        </Button>
      </span>
      {/* A fixed slot keeps the preview buttons in one column whether or not a row can still be cancelled; the shared
          hold button keeps its gesture and gets the 44px target here (DNA §23.1). */}
      {canApprove && (
        <span className='flex w-[7rem] justify-end [&_button]:min-h-11'>
          {canCancel(job) && (
            <JobCancelHold key={`cancel-${job.id}`} job={job} allowed={canApprove} pending={cancelPending} epoch={holdEpoch} onCancel={onCancel} tour={tourCancel ? 'queue-cancel' : undefined} />
          )}
        </span>
      )}
    </span>
  );
}

/** A click on the row itself (not on its buttons, and not inside a popover portalled out of it) opens the receipt. */
function openFromRow(event: MouseEvent<HTMLElement>, open: () => void) {
  const target = event.target as HTMLElement;
  if (!event.currentTarget.contains(target)) return;
  if (target.closest('button, a, input, [role="button"]')) return;
  open();
}

/**
 * One publishing job, as a table row (wide lists) or a quiet card (narrow ones). Same data, same actions; rows
 * arrive without an entrance stagger (DNA §18: no choreography on long lists).
 */
export function JobRow(props: JobRowProps) {
  const { job, layout, nowSeconds, tourRow, onOpen } = props;
  const note = stateNote(job);
  const last = job.events.at(-1);
  // A held job's note is usually its last event's message; the event line then names the state instead of repeating it.
  const lastLine = last ? `${last.message === note ? last.state.replace(/_/g, ' ') : last.message} · ${relativeTime(last.at, nowSeconds)}` : null;
  const attempts = `${job.attempts.length} / ${MAX_ATTEMPTS}`;
  const checks = checksLabel(job);

  if (layout === 'card') {
    return (
      // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- the receipt button in the card is the keyboard path
      <li
        data-tour={tourRow ? 'queue-job-row' : undefined}
        onClick={(event) => openFromRow(event, () => onOpen(job.id))}
        className='rafii-quiet flex cursor-pointer flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4 text-sm'
      >
        <div className='flex min-w-0 flex-wrap items-center gap-2'>
          <JobStateBadge job={job} />
          <Destination job={job} />
        </div>
        <div className='text-muted-foreground flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs'>
          <Scheduled job={job} nowSeconds={nowSeconds} />
          {job.attempts.length > 1 && (
            <span className='hidden tabular-nums md:inline'>
              Attempts {attempts}
              {checks && ` · ${checks}`}
            </span>
          )}
        </div>
        {note && <StateNote job={job} note={note} />}
        {lastLine && (
          <p className='text-muted-foreground hidden truncate text-xs md:block' title={last?.message}>
            {lastLine}
          </p>
        )}
        <Actions {...props} />
      </li>
    );
  }

  return (
    <TableRow
      data-tour={tourRow ? 'queue-job-row' : undefined}
      onClick={(event) => openFromRow(event, () => onOpen(job.id))}
      className='hover:bg-foreground/[0.04] cursor-pointer border-0'
    >
      <TableCell className='px-4 py-3 align-top'>
        <span className='flex max-w-[14rem] flex-col items-start gap-1'>
          <JobStateBadge job={job} />
          {note && <StateNote job={job} note={note} className='line-clamp-2 whitespace-normal' />}
        </span>
      </TableCell>
      <TableCell className='px-3 py-3 align-top'>
        <Destination job={job} />
      </TableCell>
      <TableCell className='px-3 py-3 align-top'>
        <Scheduled job={job} nowSeconds={nowSeconds} />
      </TableCell>
      <TableCell className='px-3 py-3 align-top tabular-nums'>
        <span className='flex flex-col'>
          {attempts}
          {checks && <span className='text-muted-foreground text-xs whitespace-nowrap'>{checks}</span>}
        </span>
      </TableCell>
      <TableCell className='text-muted-foreground hidden max-w-[14rem] truncate px-3 py-3 align-top text-xs @min-[66rem]:table-cell' title={last?.message}>
        {lastLine ?? '—'}
      </TableCell>
      <TableCell className='px-4 py-2 text-right align-top'>
        <Actions {...props} />
      </TableCell>
    </TableRow>
  );
}
