'use client';

import { useId, useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { FounderSaveButton } from '@/features/founder/motion/founder-motion';
import { Band, FIELD_CLASS, SelectField, StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { failureOf, useBriefingSchedules, useCapability, useCreateBriefingSchedule, useDeleteBriefingSchedule } from '../customers/kit/api';
import { clockToMinutes, whenDateTime } from '../customers/kit/format';
import { QueryState } from '../customers/kit/page-frame';
import { resolvedTimeZone } from '../customers/kit/period';
import { SimpleTable } from '../customers/kit/simple-table';
import type { BriefingSchedule, BriefingScheduleInput } from '../customers/kit/types';

/**
 * Briefing schedules (CONTRACTS §5 `founder_briefing_schedules`): list, create and delete. The cron claims an
 * occurrence, composes a report and plans a contact; with live delivery off the report is still written and can be
 * read on Overview › Reports. Weekly replaces daily on the same day (server rule), so the page says so.
 */
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function weekdaysLabel(days: number[]): string {
  if (!days || days.length === 0) return 'Every day';
  return days.map((day) => WEEKDAYS[(day + 6) % 7] ?? String(day)).join(', ');
}

/** The schedule to create, or the first validation message; the server validates again. */
export function scheduleFromDraft(draft: { kind: 'daily' | 'weekly'; localTime: string; weekdays: number[]; timeZone: string; enabled: boolean }): { schedule: BriefingScheduleInput } | { error: string } {
  if (clockToMinutes(draft.localTime) === null) return { error: 'Local time must be HH:MM.' };
  if (!draft.timeZone.trim()) return { error: 'A time zone is required.' };
  if (draft.kind === 'weekly' && draft.weekdays.length === 0) return { error: 'Pick at least one weekday for a weekly briefing.' };
  return { schedule: { kind: draft.kind, localTime: draft.localTime, weekdays: draft.kind === 'weekly' ? [...draft.weekdays].toSorted((a, b) => a - b) : [], timeZone: draft.timeZone.trim(), enabled: draft.enabled } };
}

export function BriefingSchedules() {
  const schedules = useBriefingSchedules();
  const create = useCreateBriefingSchedule();
  const remove = useDeleteBriefingSchedule();
  const canSettings = useCapability('control.settings');
  const [kind, setKind] = useState<'daily' | 'weekly'>('daily');
  const [localTime, setLocalTime] = useState('08:00');
  const [weekdays, setWeekdays] = useState<number[]>([1]);
  const [timeZone, setTimeZone] = useState(resolvedTimeZone());
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const ids = useId();
  const currentSchedule = scheduleFromDraft({ kind, localTime, weekdays, timeZone, enabled });
  const unchangedSavedSchedule = 'schedule' in currentSchedule && JSON.stringify(create.variables) === JSON.stringify(currentSchedule.schedule);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next = scheduleFromDraft({ kind, localTime, weekdays, timeZone, enabled });
    if ('error' in next) {
      setError(next.error);
      return;
    }
    setError(null);
    try {
      await create.mutateAsync(next.schedule);
      toast.success('Briefing schedule added.');
    } catch (cause) {
      setError(failureOf(cause).message ?? 'The schedule could not be saved.');
    }
  }

  async function destroy(schedule: BriefingSchedule) {
    try {
      await remove.mutateAsync(schedule.id);
      toast.success('Schedule removed.');
    } catch (cause) {
      toast.error(failureOf(cause).message ?? 'The schedule could not be removed.');
    }
  }

  return (
    <div className='flex flex-col gap-5'>
      <QueryState query={schedules} label='briefing schedules' isEmpty={(result) => result.schedules.length === 0} emptyTitle='No briefing schedules' emptyDescription='Add a daily or weekly briefing below. Reports are written even while live delivery is off.'>
        {(result) => (
          <SimpleTable<BriefingSchedule>
            rows={result.schedules}
            rowKey={(row) => row.id}
            caption='Briefing schedules'
            columns={[
              { key: 'kind', label: 'Briefing', render: (row) => (row.kind === 'weekly' ? 'Weekly' : 'Daily') },
              { key: 'time', label: 'Local time', render: (row) => `${row.localTime} ${row.timeZone}` },
              { key: 'days', label: 'Days', render: (row) => (row.kind === 'weekly' ? weekdaysLabel(row.weekdays) : 'Every day') },
              { key: 'enabled', label: 'State', render: (row) => <StatusChip status={row.enabled ? 'success' : 'neutral'}>{row.enabled ? 'Enabled' : 'Paused'}</StatusChip> },
              { key: 'next', label: 'Next', render: (row) => whenDateTime(row.nextAt) },
              {
                key: 'actions',
                label: <span className='sr-only'>Actions</span>,
                align: 'right',
                render: (row) => (
                  <Button variant='quiet' size='sm' disabled={!canSettings || remove.isPending} onClick={() => void destroy(row)} aria-label={`Remove ${row.kind} briefing at ${row.localTime}`}>
                    <Icons.trash /> Remove
                  </Button>
                )
              }
            ]}
          />
        )}
      </QueryState>

      <Band as='section' aria-labelledby='new-schedule'>
        <h3 id='new-schedule' className='text-foreground text-sm font-medium'>
          Add a briefing
        </h3>
        <form onSubmit={(event) => void submit(event)} className='grid gap-4 sm:grid-cols-2'>
          <SelectField label='Kind' value={kind} onChange={(event) => setKind(event.target.value as 'daily' | 'weekly')}>
            <option value='daily'>Daily</option>
            <option value='weekly'>Weekly</option>
          </SelectField>
          <div className='flex min-w-0 flex-col gap-2 text-sm'>
            <Label htmlFor={`${ids}-time`} className='text-foreground font-medium'>
              Local time
            </Label>
            <Input id={`${ids}-time`} type='time' value={localTime} onChange={(event) => setLocalTime(event.target.value)} className={FIELD_CLASS} />
          </div>
          <div className='flex min-w-0 flex-col gap-2 text-sm'>
            <Label htmlFor={`${ids}-zone`} className='text-foreground font-medium'>
              Time zone
            </Label>
            <Input id={`${ids}-zone`} value={timeZone} onChange={(event) => setTimeZone(event.target.value)} className={FIELD_CLASS} autoComplete='off' />
          </div>
          <div className='flex items-center justify-between gap-3 sm:self-end'>
            <span className='text-foreground text-sm font-medium'>Enabled</span>
            <Switch checked={enabled} onCheckedChange={(next) => setEnabled(Boolean(next))} />
          </div>
          {kind === 'weekly' && (
            <fieldset className='flex flex-col gap-2 sm:col-span-2'>
              <legend className='text-foreground text-sm font-medium'>Weekdays</legend>
              <div className='flex flex-wrap gap-2'>
                {WEEKDAYS.map((label, index) => {
                  const day = index + 1;
                  const checked = weekdays.includes(day);
                  return (
                    <label key={label} className={cn('rafii-quiet flex items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm', checked && 'rafii-glass-selected')}>
                      <input type='checkbox' aria-label={label} checked={checked} onChange={(change) => setWeekdays(change.target.checked ? [...weekdays, day] : weekdays.filter((item) => item !== day))} className='accent-foreground size-4' />
                      {label}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}
          {error && (
            <div className='sm:col-span-2'>
              <StateMessage kind='error' layout='inline' title={error} />
            </div>
          )}
          <div className='flex flex-wrap items-center gap-3 sm:col-span-2'>
            <FounderSaveButton state={create.isPending ? 'saving' : create.isError || error ? 'error' : create.isSuccess && unchangedSavedSchedule ? 'saved' : 'idle'} disabled={!canSettings} title={canSettings ? undefined : 'Needs the control.settings capability and a step-up.'}>
              Add schedule
            </FounderSaveButton>
            <span className='text-muted-foreground text-xs'>A weekly briefing replaces the daily one on its day. Occurrences more than 15 minutes late are marked missed, never dialled late.</span>
          </div>
        </form>
      </Band>
    </div>
  );
}