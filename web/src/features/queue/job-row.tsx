'use client';

import type { MouseEvent } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { JobCancelHold } from '@/components/jobs/job-cancel-hold';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { TableCell, TableRow } from '@/components/ui/table';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import {
  canCancel,
  countdown,
  epochOf,
  isSynthetic,
  jobBadge,
  MAX_ATTEMPTS,
  stateNote,
  WAITING,
  type QueueJob
} from './job-state';

const MotionTableRow = motion.create(TableRow);

/** `--duration-stagger` (40ms). */
const STAGGER_S = 0.04;
const ROW_ENTER_S = 0.18;
/** 3 steps × 40ms + 180ms = 300ms, the cap for a whole entrance. */
const ROW_STAGGER_STEPS = 3;

export interface JobRowProps {
  job: QueueJob;
  layout: 'table' | 'card';
  index: number;
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
  const badge = jobBadge(job);
  return (
    <AnimatedBadge size='sm' status={badge.status} pulse={badge.pulse} title={badge.title}>
      {badge.label}
    </AnimatedBadge>
  );
}

export function FixtureBadge() {
  return (
    <AnimatedBadge size='sm' status='neutral' showIcon={false} title='Synthetic provider; nothing reaches a real account'>
      Fixture
    </AnimatedBadge>
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

function Scheduled({ job, nowSeconds }: { job: QueueJob; nowSeconds: number }) {
  const at = epochOf(job.manifest.timing.utc);
  // A waiting job counts down to its time, then reads "due" until the worker changes its state.
  const left = WAITING.has(job.state) && at !== null ? (countdown(at, nowSeconds) ?? 'due') : null;
  return (
    <span className='flex flex-col'>
      <span className='whitespace-nowrap'>{formatDateTime(at)}</span>
      {left && (
        <span aria-hidden className='text-muted-foreground text-xs tabular-nums'>
          {left}
        </span>
      )}
    </span>
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
          <PopoverTrigger render={<Button variant='ghost' size='icon-sm' />} aria-label={`Preview the ${job.manifest.platform} post`} title='Preview in the app'>
            <Icons.eye />
          </PopoverTrigger>
          <PopoverContent align={layout === 'table' ? 'end' : 'start'} className='w-auto max-w-[calc(100vw-1rem)]'>
            <div className='max-h-[calc(var(--available-height,100vh)-1.5rem)] overflow-y-auto'>
              <ManifestPreview manifest={job.manifest} />
            </div>
          </PopoverContent>
        </Popover>
        <Button
          variant='ghost'
          size='icon-sm'
          aria-label={`Open the receipt for the ${job.manifest.platform} post`}
          title='Timeline, attempts and what the provider confirmed'
          onClick={() => onOpen(job.id)}
        >
          <Icons.history />
        </Button>
      </span>
      {/* A fixed slot keeps the preview buttons in one column whether or not a row can still be cancelled. */}
      {canApprove && (
        <span className='flex w-[7rem] justify-end'>
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

/** One publishing job, as a table row (md and up) or a card (below md). Same data, same actions. */
export function JobRow(props: JobRowProps) {
  const { job, layout, index, nowSeconds, tourRow, onOpen } = props;
  const reduce = useReducedMotion();
  const note = stateNote(job);
  const last = job.events.at(-1);
  // A held job's note is usually its last event's message; the event line then names the state instead of repeating it.
  const lastLine = last ? `${last.message === note ? last.state.replace(/_/g, ' ') : last.message} · ${relativeTime(last.at, nowSeconds)}` : null;
  const attempts = `${job.attempts.length} / ${MAX_ATTEMPTS}`;
  const checks = checksLabel(job);
  // Motion rule (docs/postriff-motion-system.md §5): 40ms stagger, whole entrance within 300ms. Rows past the
  // fourth start with it, so a long list never takes longer to appear.
  const enter = {
    initial: reduce ? false : ({ opacity: 0, y: 4 } as const),
    animate: { opacity: 1, y: 0 },
    transition: { duration: ROW_ENTER_S, ease: EASE_OUT, delay: Math.min(index, ROW_STAGGER_STEPS) * STAGGER_S }
  };

  if (layout === 'card') {
    return (
      // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- the receipt button in the card is the keyboard path
      <motion.li
        {...enter}
        data-tour={tourRow ? 'queue-job-row' : undefined}
        onClick={(event) => openFromRow(event, () => onOpen(job.id))}
        className='bg-card flex cursor-pointer flex-col gap-2 rounded-lg border p-3 text-sm'
      >
        <div className='flex min-w-0 flex-wrap items-center gap-2'>
          <JobStateBadge job={job} />
          <Destination job={job} />
        </div>
        <div className='text-muted-foreground flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs'>
          <Scheduled job={job} nowSeconds={nowSeconds} />
          <span className='tabular-nums'>
            Attempts {attempts}
            {checks && ` · ${checks}`}
          </span>
        </div>
        {note && <p className='text-xs text-amber-700 dark:text-amber-300'>{note}</p>}
        <p className='text-muted-foreground truncate text-xs' title={last?.message}>
          {lastLine ?? 'No events recorded'}
        </p>
        <Actions {...props} />
      </motion.li>
    );
  }

  return (
    <MotionTableRow {...enter} data-tour={tourRow ? 'queue-job-row' : undefined} onClick={(event) => openFromRow(event, () => onOpen(job.id))} className='cursor-pointer'>
      <TableCell className='align-top'>
        <span className='flex max-w-[14rem] flex-col items-start gap-1'>
          <JobStateBadge job={job} />
          {note && (
            <span className='line-clamp-2 text-xs whitespace-normal text-amber-700 dark:text-amber-300' title={note}>
              {note}
            </span>
          )}
        </span>
      </TableCell>
      <TableCell className='align-top'>
        <Destination job={job} />
      </TableCell>
      <TableCell className='align-top'>
        <Scheduled job={job} nowSeconds={nowSeconds} />
      </TableCell>
      <TableCell className='align-top tabular-nums'>
        <span className='flex flex-col'>
          {attempts}
          {checks && <span className='text-muted-foreground text-xs whitespace-nowrap'>{checks}</span>}
        </span>
      </TableCell>
      <TableCell className='hidden max-w-[10rem] truncate align-top font-mono text-xs @min-[76rem]:table-cell' title={job.providerReference}>
        {job.providerReference || job.providerConfirmed || '—'}
      </TableCell>
      <TableCell className='text-muted-foreground hidden max-w-[14rem] truncate align-top text-xs @min-[66rem]:table-cell' title={last?.message}>
        {lastLine ?? '—'}
      </TableCell>
      <TableCell className='text-right align-top'>
        <Actions {...props} />
      </TableCell>
    </MotionTableRow>
  );
}
