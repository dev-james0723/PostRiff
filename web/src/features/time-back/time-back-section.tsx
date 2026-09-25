'use client';

import { useId, useState } from 'react';
import { Icons } from '@/components/icons';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { useTimeSavings, useTimeSavingsCalibration } from '@/lib/api/hooks';
import type { TimeSavingsBaseline, TimeSavingsConfidence, TimeSavingsRange, TimeSavingsSummary } from '@/lib/api/types';
import { CalibrationPrompt } from './calibration-prompt';
import {
  BASELINE_SOURCE,
  CALIBRATION_CHOICES,
  completedLabel,
  CONFIDENCE,
  formatMinutes,
  HOW_IT_WORKS,
  LONGER_CHOICES,
  minutesLabel,
  RANGE_OPTIONS,
  spokenMinutes,
  TASK,
  taskLine
} from './time-back-copy';

const PROVENANCE_ORDER: TimeSavingsConfidence[] = ['measured', 'personalized', 'estimated'];

/**
 * Time back on Analytics (docs/raffi-time-back/ENGINEERING.md §12): the person's own estimate of work Rafii removed,
 * visually apart from the platform numbers below it and never added to them. Unavailable stays unavailable, and
 * nothing completed yet says so instead of showing "0h".
 */
export function TimeBackSection() {
  const [range, setRange] = useState<TimeSavingsRange>('30d');
  const query = useTimeSavings(range);
  const data = query.data;

  return (
    <Panel
      id='time-back'
      title='Time back'
      titleId='time-back-heading'
      description='Estimated time saved on work you completed with Rafii. Separate from your posts’ platform numbers.'
      className='scroll-mt-24'
      actions={<SegmentedControl label='Time back period' options={RANGE_OPTIONS} value={range} onChange={setRange} size='sm' widths='content' />}
    >
      {query.isPending ? (
        <div className='flex flex-col gap-3' aria-hidden>
          <Skeleton className='h-10 w-40' />
          <Skeleton className='h-4 w-56' />
          <Skeleton className='h-16 w-full' />
        </div>
      ) : query.isError || !data ? (
        <StateMessage
          kind='error'
          layout='inline'
          title='Time back is unavailable right now'
          description='Nothing is shown rather than a guess.'
          action={
            <Button variant='glass' onClick={() => query.refetch()}>
              <Icons.refresh /> Try again
            </Button>
          }
        />
      ) : data.state === 'empty' ? (
        <StateMessage
          kind='empty'
          layout='inline'
          title={range === 'all' ? 'No time back yet' : 'No completed work in this period'}
          description='Time back starts with completed work: a draft you approve for publishing, a post the platform confirms, or an automation you switch on.'
        />
      ) : (
        <Totals data={data} />
      )}
      {/* Keyed by kind: each question starts from its own first set of answers. */}
      {data && data.calibration.due.length > 0 && <CalibrationPrompt key={data.calibration.due[0]} kind={data.calibration.due[0]} />}
      {data && <TypicalTimes baselines={data.calibration.baselines} />}
      <HowItWorks />
    </Panel>
  );
}

function Totals({ data }: { data: TimeSavingsSummary }) {
  const provenance = PROVENANCE_ORDER.filter((level) => data.confidence[level] > 0);
  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-end justify-between gap-x-4 gap-y-2'>
        <p className='flex flex-col gap-0.5'>
          <span className='text-foreground text-4xl font-semibold tracking-[-0.02em] tabular-nums' aria-hidden>
            {formatMinutes(data.totalMinutes)}
          </span>
          <span className='sr-only'>{`${spokenMinutes(data.totalMinutes)} back.`}</span>
          <span className='text-muted-foreground text-sm'>back · {completedLabel(data.completedTasks)}</span>
        </p>
        {data.basis && (
          <StatusChip icon={null} title={CONFIDENCE[data.basis].meaning}>
            {CONFIDENCE[data.basis].badge}
          </StatusChip>
        )}
      </div>
      <ul aria-label='Time back by task' className='flex flex-col gap-3'>
        {data.breakdown.map((item) => {
          const share = data.totalMinutes > 0 ? Math.round((item.minutes / data.totalMinutes) * 100) : 0;
          return (
            <li key={item.taskKind} className='flex flex-col gap-1.5'>
              <div className='flex items-baseline justify-between gap-3 text-sm'>
                <span className='text-foreground min-w-0'>{taskLine(item.taskKind, item.count)}</span>
                <span className='text-foreground shrink-0 font-medium tabular-nums'>
                  <span aria-hidden>{formatMinutes(item.minutes)}</span>
                  <span className='sr-only'>{spokenMinutes(item.minutes)}</span>
                </span>
              </div>
              <div aria-hidden className='bg-foreground/10 h-1.5 w-full overflow-hidden rounded-full'>
                <div className='bg-foreground/70 h-full rounded-full' style={{ width: `${share}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
      {provenance.length > 0 && (
        <p className='text-muted-foreground text-xs leading-relaxed text-pretty'>
          {provenance.map((level) => `${data.confidence[level]} ${CONFIDENCE[level].phrase}`).join(' · ')}
        </p>
      )}
    </div>
  );
}

/** The person's own typical times: an explicit setting beats their answers, which beat Rafii's estimate (§3.1). */
function TypicalTimes({ baselines }: { baselines: TimeSavingsBaseline[] }) {
  const id = useId();
  const calibrate = useTimeSavingsCalibration();
  const choices = [...CALIBRATION_CHOICES, ...LONGER_CHOICES];
  return (
    <Collapsible render={<div className='rafii-quiet rounded-[var(--rafii-radius-card)]' />}>
      <CollapsibleTrigger className='group/times rafii-focus text-foreground flex min-h-12 w-full items-center justify-between gap-2 rounded-[var(--rafii-radius-card)] px-5 py-3 text-left text-sm font-medium'>
        Your typical times
        <Icons.chevronDown aria-hidden className='text-muted-foreground size-4 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/times:rotate-180 motion-reduce:transition-none' />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>
        <div className='flex flex-col gap-3 px-5 pb-5'>
          <p className='text-muted-foreground text-xs leading-relaxed text-pretty'>About how long each task takes you without Rafii. A change applies to work you complete from now on.</p>
          <ul className='flex flex-col gap-3'>
            {baselines.map((baseline) => {
              const selectId = `${id}-${baseline.taskKind}`;
              const current = baseline.source === 'user_override' ? String(Math.round(baseline.seconds / 60)) : '';
              const options = current && !choices.includes(Number(current)) ? [...choices, Number(current)].toSorted((a, b) => a - b) : choices;
              return (
                <li key={baseline.taskKind} className='flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4'>
                  <label htmlFor={selectId} className='text-foreground text-sm'>
                    {TASK[baseline.taskKind].setting}
                    <span className='text-muted-foreground'> · {BASELINE_SOURCE[baseline.source]}</span>
                  </label>
                  <NativeSelect
                    id={selectId}
                    value={current}
                    disabled={calibrate.isPending}
                    onChange={(event) => {
                      const value = event.target.value;
                      calibrate.mutate(
                        value === ''
                          ? { taskKind: baseline.taskKind, source: 'settings_override', clear: true }
                          : { taskKind: baseline.taskKind, source: 'settings_override', manualSeconds: Number(value) * 60 }
                      );
                    }}
                  >
                    <NativeSelectOption value=''>{`Automatic · ${minutesLabel(Math.round(baseline.automaticSeconds / 60))}`}</NativeSelectOption>
                    {options.map((minutes) => (
                      <NativeSelectOption key={minutes} value={String(minutes)}>
                        {minutesLabel(minutes)}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </li>
              );
            })}
          </ul>
          {calibrate.isError && (
            <p role='alert' className='text-foreground text-xs'>
              Couldn’t save that change. Try again.
            </p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function HowItWorks() {
  return (
    <Collapsible render={<div className='rafii-quiet rounded-[var(--rafii-radius-card)]' />}>
      <CollapsibleTrigger className='group/how rafii-focus text-foreground flex min-h-12 w-full items-center justify-between gap-2 rounded-[var(--rafii-radius-card)] px-5 py-3 text-left text-sm font-medium'>
        How is this calculated?
        <Icons.chevronDown aria-hidden className='text-muted-foreground size-4 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/how:rotate-180 motion-reduce:transition-none' />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>
        <ul className='flex flex-col gap-2 px-5 pb-5 text-sm'>
          {HOW_IT_WORKS.map((point) => (
            <li key={point.title}>
              <span className='text-foreground font-medium'>{point.title}</span>
              <span className='text-muted-foreground'> — {point.description}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
