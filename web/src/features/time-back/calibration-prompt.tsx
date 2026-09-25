'use client';

import { useId, useState } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { useTimeSavingsCalibration } from '@/lib/api/hooks';
import type { TimeSavingsTaskKind } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { CALIBRATION_CHOICES, LONGER_CHOICES, minutesLabel, TASK } from './time-back-copy';

/**
 * The one calibration question (§13), shown only after the person completed that kind of work, at most once a month
 * per kind (the server decides), always dismissible and never in the way of publishing. "More than 1 hour" asks how
 * much more instead of guessing.
 */
export function CalibrationPrompt({ kind, material = 'quiet', onSettled }: { kind: TimeSavingsTaskKind; material?: 'quiet' | 'elevated'; onSettled?: () => void }) {
  const id = useId();
  const calibrate = useTimeSavingsCalibration();
  const [longer, setLonger] = useState(false);
  const done = { onSuccess: () => onSettled?.() };
  const answer = (minutes: number) => calibrate.mutate({ taskKind: kind, source: 'prompt', manualSeconds: minutes * 60 }, done);

  return (
    <div
      role='group'
      aria-labelledby={`${id}-question`}
      aria-describedby={`${id}-note`}
      data-time-back-prompt={kind}
      className={cn(material === 'elevated' ? 'rafii-elevated shadow-lg' : 'rafii-quiet', 'flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4')}
    >
      <div className='flex items-start justify-between gap-3'>
        <div className='flex min-w-0 flex-col gap-1'>
          <p id={`${id}-question`} className='text-foreground text-sm font-medium text-balance'>
            Before Rafii, about how long would this usually take you?
          </p>
          <p id={`${id}-note`} className='text-muted-foreground text-xs leading-relaxed text-pretty'>
            For {TASK[kind].question}. After three answers, your time back uses your own estimate.
          </p>
        </div>
        <Button variant='ghost' size='icon-control' aria-label='Not now' disabled={calibrate.isPending} onClick={() => calibrate.mutate({ taskKind: kind, source: 'prompt', dismissed: true }, done)}>
          <Icons.close aria-hidden className='size-4' />
        </Button>
      </div>
      <div className='flex flex-wrap gap-2'>
        {(longer ? LONGER_CHOICES : CALIBRATION_CHOICES).map((minutes) => (
          <Button key={minutes} variant='glass' size='control' disabled={calibrate.isPending} onClick={() => answer(minutes)}>
            {minutesLabel(minutes)}
          </Button>
        ))}
        {!longer && (
          <Button variant='glass' size='control' disabled={calibrate.isPending} onClick={() => setLonger(true)}>
            More than 1 hour
          </Button>
        )}
      </div>
      {calibrate.isError && (
        <p role='alert' className='text-foreground text-xs'>
          Couldn’t save that answer. Try again.
        </p>
      )}
    </div>
  );
}
