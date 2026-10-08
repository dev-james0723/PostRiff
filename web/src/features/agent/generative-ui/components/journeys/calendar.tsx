'use client';
/**
 * J02 — Calendar and publishing operations (lane E): agenda by day with exact instants and zones, the publishing queue,
 * a read-only time check, a form that PREPARES a schedule proposal, and the proposals waiting in this conversation.
 *
 * Nothing here schedules, approves or publishes. `schedule_prepare` goes through the original `schedule_propose` path
 * and writes a proposal card into the conversation; applying or dismissing it happens only on that native card
 * (`agent/approvals/decide`). Status words come from the stored state: "Published" only for posts the queue reports as
 * published, and unknown states are shown as unknown, never folded into "Scheduled".
 */
import { useId } from 'react';
import { z } from 'zod';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { formatCalendarDate, formatInstant } from '../../journeys/format';
import { useBound, useJourneyEnvironment } from '../../journeys/runtime';
import type { AgendaEntry, QueueItem } from '../../journeys/views';
import { CountValue, GuardedAction, Missing, Pill, QueryFrame, SelectToggle, type Tone } from './shared';
import type { JourneyRendererProps } from './types';

const STATUS_TONE: Record<string, Tone> = {
  scheduled: 'good',
  awaiting_approval: 'waiting',
  in_flight: 'waiting',
  failed_held_uncertain: 'attention',
  published: 'good',
  verified: 'good',
  planned: 'muted',
  unknown: 'muted',
};
const LOCAL = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;
const titleProps = z.object({ title: z.string().max(120).optional() });

function StatusPill({ status }: { status: string }) {
  const { copy } = useJourneyEnvironment();
  return <Pill tone={STATUS_TONE[status] ?? 'muted'}>{copy.calendar.statusLabel[status] ?? copy.calendar.statusLabel.unknown}</Pill>;
}

function dayOf(entry: AgendaEntry): string | null {
  return entry.local && /^\d{4}-\d{2}-\d{2}/.test(entry.local) ? entry.local.slice(0, 10) : null;
}

export function CalendarAgenda({ props, statementId }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  const literal = titleProps.safeParse(props);
  const selection = useBound<string>(`${statementId ?? 'agenda'}Selected`, props.selected);
  const selected = typeof selection.value === 'string' ? selection.value : null;
  return (
    <QueryFrame value={props.data} binding='calendar_agenda' label={copy.calendar.title} title={literal.success ? literal.data.title : null}>
      {(data) => {
        const groups = new Map<string, AgendaEntry[]>();
        for (const entry of data.entries) {
          const day = dayOf(entry) ?? '';
          groups.set(day, [...(groups.get(day) ?? []), entry]);
        }
        const close = data.derived?.closeTogether;
        const closeIds = new Set((close?.pairs ?? []).flatMap((p) => [p.first, p.second]));
        return (
          <div className='flex flex-col gap-3'>
            <p className='text-muted-foreground text-xs'>
              {formatCalendarDate(data.range.start, locale)} – {formatCalendarDate(data.range.end, locale)} · {copy.common.timeZone}: {data.range.timeZone}
            </p>
            {data.statusCounts ? (
              <ul className='flex flex-wrap gap-2 text-xs' aria-label={copy.calendar.status}>
                {Object.entries(data.statusCounts).map(([status, n]) => (
                  <li key={status} className='flex items-center gap-1'>
                    <StatusPill status={status} /> <span className='tabular-nums'>{n}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {data.unknownStates && data.unknownStates.length > 0 ? <p className='text-muted-foreground text-xs'>{copy.calendar.unknownStates}</p> : null}
            {[...groups.entries()].map(([day, entries]) => (
              <div key={day || 'undated'} className='flex flex-col gap-1.5'>
                <h4 className='text-xs font-semibold'>{formatCalendarDate(day, locale) ?? copy.common.noDate}</h4>
                <ul className='flex flex-col divide-y divide-border rounded-[var(--rafii-radius-card)] border'>
                  {entries.map((entry) => {
                    const selectable = entry.kind === 'job';
                    const isSelected = selectable && selected === entry.id;
                    return (
                      <li key={entry.ref} className={cn('flex items-start gap-3 p-2.5', isSelected && 'bg-muted/40')}>
                        {selectable ? (
                          <SelectToggle
                            selected={isSelected}
                            label={`${entry.platform ?? ''} ${entry.local ?? ''}`.trim() || entry.id}
                            onToggle={() => selection.set(isSelected ? '' : entry.id)}
                          />
                        ) : (
                          <span className='size-5 shrink-0' aria-hidden />
                        )}
                        <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                          <span className='flex flex-wrap items-center gap-2 text-sm'>
                            <span className='tabular-nums font-medium'>{formatInstant(entry.atUtc, entry.timeZone, locale, entry.local) ?? <Missing word='noDate' />}</span>
                            <StatusPill status={entry.status} />
                            {entry.fromAutomation ? <Pill tone='muted'>{copy.drafts.fromAutomation}</Pill> : null}
                          </span>
                          <span className='text-muted-foreground text-xs'>
                            {[entry.platform, entry.account].filter(Boolean).join(' · ')}
                            {entry.jobZone && entry.jobZone !== entry.timeZone && entry.jobLocal
                              ? ` · ${copy.calendar.jobZone}: ${entry.jobLocal.replace('T', ' ')} ${entry.jobZone}`
                              : ''}
                          </span>
                          {entry.title || entry.excerpt ? <span className='text-sm break-words'>{entry.title || entry.excerpt}</span> : null}
                          {closeIds.has(entry.id) && close ? <span className='text-amber-700 dark:text-amber-300 text-xs'>{close.rule}</span> : null}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
            {data.derived?.emptyDays && data.derived.emptyDays.days.length > 0 ? (
              <p className='text-muted-foreground text-xs'>
                {copy.calendar.emptyDays}: {data.derived.emptyDays.days.map((d) => formatCalendarDate(d, locale)).join(', ')} ({copy.common.rule}: {data.derived.emptyDays.rule})
              </p>
            ) : null}
            {selected ? <p className='text-muted-foreground text-xs'>{copy.common.selectionHint}</p> : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

function QueueList({ title, items, empty }: { title: string; items: QueueItem[]; empty: string }) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <div className='flex flex-col gap-1'>
      <h4 className='text-xs font-semibold'>{title}</h4>
      {items.length === 0 ? (
        <p className='text-muted-foreground text-xs'>{empty}</p>
      ) : (
        <ul className='flex flex-col gap-1 text-sm'>
          {items.map((item) => (
            <li key={item.ref} className='flex flex-col gap-0.5 rounded-md border p-2'>
              <span className='flex flex-wrap items-center gap-2'>
                <span className='font-medium'>{item.title ?? item.state ?? copy.common.unknown}</span>
                {item.demo ? <Pill tone='muted'>{copy.common.demo}</Pill> : null}
                {item.verified ? <Pill tone='good'>{copy.common.verified}</Pill> : null}
              </span>
              <span className='text-muted-foreground text-xs'>
                {[item.platform, item.account, formatInstant(item.atUtc, item.timeZone, locale, item.publishAt)].filter(Boolean).join(' · ')}
              </span>
              {item.meaning ? <span className='text-muted-foreground text-xs'>{item.meaning}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function QueueStatus({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='queue_status' label={copy.calendar.queueTitle} title={copy.calendar.queueTitle}>
      {(data) => (
        <div className='flex flex-col gap-3'>
          <dl className='grid grid-cols-2 gap-2 text-xs @[28rem]:grid-cols-4'>
            <div>
              <dt className='text-muted-foreground'>{copy.calendar.waitingApproval}</dt>
              <dd className='text-base font-semibold tabular-nums'>{data.totals.waitingApproval}</dd>
            </div>
            <div>
              <dt className='text-muted-foreground'>{copy.calendar.upcoming}</dt>
              <dd className='text-base font-semibold tabular-nums'>{data.totals.upcoming}</dd>
            </div>
            <div>
              <dt className='text-muted-foreground'>{copy.calendar.attention}</dt>
              <dd className='text-base font-semibold tabular-nums'>{data.totals.attention}</dd>
            </div>
            <div>
              <dt className='text-muted-foreground'>{copy.calendar.draftsUnscheduled}</dt>
              <dd className='text-base font-semibold'>
                <CountValue value={data.draftsUnscheduled ?? null} />
              </dd>
            </div>
          </dl>
          {data.unknownStates && data.unknownStates.length > 0 ? <p className='text-muted-foreground text-xs'>{copy.calendar.unknownStates}</p> : null}
          <div className='flex flex-col gap-1'>
            <h4 className='text-xs font-semibold'>{copy.calendar.waitingApproval}</h4>
            {data.waitingApproval.length === 0 ? (
              <p className='text-muted-foreground text-xs'>{copy.common.none}</p>
            ) : (
              <ul className='flex flex-col gap-1 text-sm'>
                {data.waitingApproval.map((review) => (
                  <li key={review.ref} className='flex flex-wrap items-center gap-2 rounded-md border p-2'>
                    <span>{[review.platform, review.account].filter(Boolean).join(' · ') || <Missing />}</span>
                    <span className='text-muted-foreground text-xs'>{formatInstant(review.atUtc, review.timeZone, locale, review.local) ?? copy.common.noDate}</span>
                    {review.expired ? <Pill tone='attention'>{copy.calendar.expired}</Pill> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <QueueList title={copy.calendar.attention} items={data.attention} empty={copy.common.none} />
          <QueueList title={copy.calendar.upcoming} items={data.upcoming} empty={copy.common.none} />
          {data.href ? (
            <a className='rafii-focus text-primary text-xs underline-offset-4 hover:underline' href={data.href}>
              {copy.common.open} {copy.calendar.queueTitle}
            </a>
          ) : null}
        </div>
      )}
    </QueryFrame>
  );
}

export function SlotCheck({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='slot_check' label={copy.calendar.slotTitle} title={copy.calendar.slotTitle}>
      {(slot) => (
        <div className='flex flex-col gap-1.5 text-sm' role='status'>
          <p className='flex flex-wrap items-center gap-2'>
            <Pill tone={slot.valid ? 'good' : 'attention'}>{slot.valid ? copy.calendar.slotValid : copy.calendar.slotInvalid}</Pill>
            <span className='tabular-nums'>
              {formatInstant(slot.atUtc, slot.timeZone, locale, slot.local)}
            </span>
            {slot.account ? <span className='text-muted-foreground text-xs'>{[slot.platform, slot.account].filter(Boolean).join(' · ')}</span> : null}
          </p>
          {slot.problems.map((problem) => (
            <p key={problem.code} className='text-destructive text-xs'>
              {problem.message}
            </p>
          ))}
          {slot.collisions.length > 0 ? (
            <div className='text-xs'>
              <p className='font-medium'>{copy.calendar.collisions(slot.collisions.length)}</p>
              <ul className='text-muted-foreground'>
                {slot.collisions.map((c) => (
                  <li key={c.ref}>
                    {c.local ? c.local.replace('T', ' ') : copy.common.noDate} · {c.minutesApart} min{c.status ? ` · ${c.status}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className='text-muted-foreground text-xs'>{copy.calendar.noCollisions}</p>
          )}
          <p className='text-muted-foreground text-xs'>
            {copy.common.rule}: {slot.rule}
          </p>
        </div>
      )}
    </QueryFrame>
  );
}

const rescheduleProps = z.object({ actionId: z.literal('schedule_prepare'), target: z.enum(['job', 'draft']) });

function validZone(zone: string): boolean {
  if (!/^[A-Za-z][A-Za-z0-9_+\-]*(\/[A-Za-z0-9_+\-]+){0,2}$/.test(zone)) return false;
  try {
    new Intl.DateTimeFormat('en', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

export function RescheduleForm({ props, statementId }: JourneyRendererProps) {
  const { copy, timeZone } = useJourneyEnvironment();
  const literal = rescheduleProps.safeParse(props);
  const base = statementId ?? 'reschedule';
  const target = useBound<string>(`${base}Target`, props.targetId);
  const when = useBound<string>(`${base}When`, props.when);
  const zone = useBound<string>(`${base}Zone`, props.zone);
  const date = useBound<string>(`${base}Date`, undefined);
  const time = useBound<string>(`${base}Time`, undefined);
  const ids = useId();
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  const whenValue = typeof when.value === 'string' && LOCAL.test(when.value) ? when.value : '';
  const dateValue = typeof date.value === 'string' ? date.value : whenValue.slice(0, 10);
  const timeValue = typeof time.value === 'string' ? time.value : whenValue.slice(11, 16);
  const zoneValue = typeof zone.value === 'string' && zone.value ? zone.value : timeZone;
  const targetId = typeof target.value === 'string' && target.value ? target.value : null;
  const update = (nextDate: string, nextTime: string) => {
    const local = `${nextDate}T${nextTime}`;
    if (LOCAL.test(local)) when.set(local);
  };
  const ready = Boolean(targetId) && LOCAL.test(`${dateValue}T${timeValue}`) && validZone(zoneValue);
  const key = literal.data.target === 'job' ? 'jobId' : 'draftId';
  return (
    <section aria-label={copy.calendar.rescheduleTitle} className='flex flex-col gap-2'>
      <h3 className='text-sm font-semibold'>{copy.calendar.rescheduleTitle}</h3>
      <div className='grid grid-cols-1 gap-2 @[24rem]:grid-cols-3'>
        <label className='flex flex-col gap-1 text-xs' htmlFor={`${ids}-date`}>
          {copy.calendar.date}
          <Input
            id={`${ids}-date`}
            type='date'
            value={dateValue}
            onChange={(event) => {
              date.set(event.target.value);
              update(event.target.value, timeValue);
            }}
          />
        </label>
        <label className='flex flex-col gap-1 text-xs' htmlFor={`${ids}-time`}>
          {copy.calendar.time}
          <Input
            id={`${ids}-time`}
            type='time'
            value={timeValue}
            onChange={(event) => {
              time.set(event.target.value);
              update(dateValue, event.target.value);
            }}
          />
        </label>
        <label className='flex flex-col gap-1 text-xs' htmlFor={`${ids}-zone`}>
          {copy.common.timeZone}
          <Input id={`${ids}-zone`} value={zoneValue} spellCheck={false} onChange={(event) => zone.set(event.target.value.trim())} aria-invalid={!validZone(zoneValue) || undefined} />
        </label>
      </div>
      <p className='text-muted-foreground text-xs'>{copy.calendar.prepareHint}</p>
      <GuardedAction
        actionId={literal.data.actionId}
        controlId={statementId}
        ready={ready}
        notReadyHint={targetId ? undefined : copy.calendar.pickTarget}
        inputs={ready && targetId ? { [key]: targetId, local: `${dateValue}T${timeValue}`, zone: zoneValue } : null}
      />
    </section>
  );
}

export function ProposalList({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <QueryFrame
      value={props.data}
      binding='open_proposals'
      label={copy.calendar.proposalsTitle}
      title={copy.calendar.proposalsTitle}
      empty={() => <p className='text-muted-foreground text-xs'>{copy.common.none}</p>}
    >
      {(data) => (
        <div className='flex flex-col gap-2'>
          <ul className='flex flex-col gap-1.5'>
            {data.proposals.map((proposal) => (
              <li key={proposal.proposalId} className='flex flex-col gap-0.5 rounded-md border p-2 text-sm'>
                <Pill tone='waiting'>{copy.common.prepared}</Pill>
                <ul className='flex flex-col'>
                  {proposal.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                {proposal.expiresAt ? (
                  <span className='text-muted-foreground text-xs'>
                    {copy.calendar.proposalExpires}: {formatInstant(proposal.expiresAt, timeZone, locale)}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          <p className='text-muted-foreground text-xs'>{copy.calendar.applyOnCard}</p>
        </div>
      )}
    </QueryFrame>
  );
}
