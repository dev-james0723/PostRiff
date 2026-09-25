'use client';

import { HoldActionButton } from '@/components/motion/hold-action-button';
import type { Job } from '@/lib/api/types';
import { canCancel, HOLD_CANCEL_CLASS, HOLD_CANCEL_FILL, HOLD_CANCEL_WAVE } from '@/lib/jobs';

/** One gesture and state guard for every cancel entry point. The API rechecks permission. */
export function JobCancelHold({ job, allowed, pending, epoch, onCancel, tour }: {
  job: Job; allowed: boolean; pending: boolean; epoch: number;
  onCancel: (job: Job) => void; tour?: string;
}) {
  if (!allowed || !canCancel(job)) return null;
  return <HoldActionButton key={`${job.id}-${epoch}`} type='horizontal' holdDuration={900}
    holdingLabel='Keep holding…' completeLabel='Cancelling…' disabled={pending}
    onHoldComplete={() => onCancel(job)} aria-label={`Hold to cancel ${job.manifest.platform} post`}
    title='Hold to cancel (or hold Space). A post already sent can’t be recalled.'
    className={HOLD_CANCEL_CLASS} fillClassName={HOLD_CANCEL_FILL} waveClassName={HOLD_CANCEL_WAVE}
    labelClassName='text-xs' data-tour={tour}>Hold to cancel</HoldActionButton>;
}
