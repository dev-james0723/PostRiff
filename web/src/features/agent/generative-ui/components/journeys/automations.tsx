'use client';
/**
 * J08 — Automations and workspace recovery (lane E): every live automation with its schedule, zone and next run, one
 * automation's plan and upcoming occurrences, its run history (cost known or unknown, never zero), connected accounts with
 * their verified levels and in-app recovery, the step-by-step guides, and a form that PREPARES a change.
 *
 * Nothing here activates, pauses, approves, disconnects or reconnects. A change is a digest-bound proposal on a new
 * message, applied only on its native card; reconnecting happens on the Accounts page.
 */
import { z } from 'zod';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { formatInstant, formatMicroMoney } from '../../journeys/format';
import { useBound, useJourneyEnvironment, useSelectionRecorder } from '../../journeys/runtime';
import { GuardedAction, Missing, Pill, QueryFrame, SelectToggle } from './shared';
import type { JourneyRendererProps } from './types';

const ID = /^[A-Za-z0-9_.:-]{1,120}$/;

function NextRun({ run, zone }: { run: { atUtc?: string | null; local?: string | null; timeZone?: string | null } | null | undefined; zone: string }) {
  const { copy, locale } = useJourneyEnvironment();
  if (!run || (!run.atUtc && !run.local)) return <span className='text-muted-foreground'>{copy.automations.noNextRun}</span>;
  return <span className='tabular-nums'>{formatInstant(run.atUtc, run.timeZone ?? zone, locale, run.local)}</span>;
}

export function AutomationList({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const selection = useBound<string>(`${statementId ?? 'automations'}Selected`, props.selected);
  const selected = typeof selection.value === 'string' && selection.value ? selection.value : null;
  const record = useSelectionRecorder(statementId ?? 'automations');
  return (
    <QueryFrame value={props.data} binding='automations_list' label={copy.automations.listTitle} title={copy.automations.listTitle}>
      {(data) => (
        <ul className='flex flex-col divide-y divide-border rounded-[var(--rafii-radius-card)] border'>
          {data.automations.map((a) => {
            const isSelected = selected === a.automationId;
            return (
              <li key={a.ref} className={cn('flex items-start gap-3 p-2.5', isSelected && 'bg-muted/40')}>
                <SelectToggle
                  selected={isSelected}
                  label={a.name}
                  onToggle={() => {
                    selection.set(isSelected ? '' : a.automationId);
                    record(isSelected ? [] : [{ type: 'automation', id: a.automationId, title: a.name }], data.automations.map((x) => ({ type: 'automation', id: x.automationId })));
                  }}
                />
                <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                  <span className='flex flex-wrap items-center gap-2 text-sm'>
                    <span className='font-medium'>{a.name}</span>
                    {a.status ? <Pill tone={a.status === 'active' ? 'good' : a.status === 'paused' ? 'waiting' : 'muted'}>{copy.automations.status[a.status] ?? a.status}</Pill> : null}
                  </span>
                  <span className='text-muted-foreground text-xs'>{[a.schedule, a.timeZone].filter(Boolean).join(' · ')}</span>
                  <span className='text-xs'>
                    {copy.automations.nextRun}: <NextRun run={a.nextRun} zone={a.timeZone} />
                  </span>
                  {a.platforms.length ? <span className='text-muted-foreground text-xs'>{a.platforms.filter(Boolean).join(', ')}</span> : null}
                  {a.policy ? <span className='text-muted-foreground text-xs'>{copy.automations.policy[a.policy] ?? a.policy}</span> : null}
                  {a.status === 'paused' && a.pausedReason ? (
                    <span className='text-muted-foreground text-xs'>
                      {copy.automations.paused}: {a.pausedReason}
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </QueryFrame>
  );
}

export function AutomationDetail({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='automation_detail' label={copy.automations.detailTitle}>
      {(a) => (
        <article className='flex flex-col gap-2 rounded-[var(--rafii-radius-card)] border p-3'>
          <h4 className='flex flex-wrap items-center gap-2 text-sm font-semibold'>
            {a.name ?? <Missing />}
            {a.status ? <Pill tone={a.status === 'active' ? 'good' : 'muted'}>{copy.automations.status[a.status] ?? a.status}</Pill> : null}
          </h4>
          <p className='text-muted-foreground text-xs'>{[a.scheduleText, `${copy.common.timeZone}: ${a.timeZone}`].filter(Boolean).join(' · ')}</p>
          {a.upcoming.length ? (
            <div className='text-xs'>
              <p className='font-semibold'>{copy.automations.upcoming}</p>
              <ul className='tabular-nums'>
                {a.upcoming.map((u, i) => (
                  <li key={u.atUtc ?? i}>{formatInstant(u.atUtc, a.timeZone, locale, u.local)}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className='text-muted-foreground text-xs'>{copy.automations.noNextRun}</p>
          )}
          {a.needs && a.needs.length ? (
            <div className='text-xs'>
              <p className='font-semibold'>{copy.automations.needs}</p>
              <ul className='text-muted-foreground list-disc pl-5'>
                {a.needs.map((n, i) => (
                  <li key={i}>{typeof n === 'string' ? n : typeof n.label === 'string' ? n.label : typeof n.text === 'string' ? n.text : JSON.stringify(n).slice(0, 120)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {a.pausedReason ? (
            <p className='text-muted-foreground text-xs'>
              {copy.automations.paused}: {a.pausedReason}
            </p>
          ) : null}
          {a.href ? (
            <a className='rafii-focus text-primary text-xs underline-offset-4 hover:underline' href={a.href}>
              {copy.common.open}
            </a>
          ) : null}
        </article>
      )}
    </QueryFrame>
  );
}

export function RunHistory({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='automation_history' label={copy.automations.historyTitle} title={copy.automations.historyTitle}>
      {(data) => (
        <ul className='flex flex-col gap-1.5 text-sm'>
          {data.runs.map((run) => (
            <li key={run.ref} className='flex flex-col gap-0.5 rounded-md border p-2'>
              <span className='flex flex-wrap items-center gap-2'>
                <span className='tabular-nums'>{formatInstant(run.scheduledUtc, run.timeZone, locale, run.scheduledLocal) ?? <Missing word='noDate' />}</span>
                <Pill tone={run.status === 'completed' ? 'good' : run.attention ? 'attention' : 'muted'}>{copy.automations.runStatus[run.status] ?? run.status.replaceAll('_', ' ')}</Pill>
                {run.attention ? <Pill tone='attention'>{copy.automations.attention}</Pill> : null}
                <span className='text-muted-foreground text-xs'>
                  {copy.automations.cost}:{' '}
                  {run.cost.state === 'known' ? formatMicroMoney(run.cost.usdMicro, 'USD', locale) ?? copy.automations.costUnknown : copy.automations.costUnknown}
                </span>
              </span>
              {run.items.length ? (
                <ul className='text-muted-foreground text-xs'>
                  {run.items.map((item, i) => (
                    <li key={i}>
                      {[item.platform, item.state?.replaceAll('_', ' '), item.reason].filter(Boolean).join(' · ')}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </QueryFrame>
  );
}

export function ConnectionHealth({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='connections_status' label={copy.automations.connectionsTitle} title={copy.automations.connectionsTitle}>
      {(data) => (
        <div className='flex flex-col gap-2'>
          <ul className='flex flex-col gap-1.5 text-sm'>
            {data.accounts.map((a) => (
              <li key={a.ref} className='flex flex-col gap-0.5 rounded-md border p-2'>
                <span className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{[a.platform, a.account].filter(Boolean).join(' · ')}</span>
                  {a.needsReconnect ? <Pill tone='attention'>{copy.automations.needsReconnect}</Pill> : null}
                  {a.demo ? <Pill tone='muted'>{copy.common.demo}</Pill> : null}
                  {typeof a.canPublish === 'boolean' ? <Pill tone={a.canPublish ? 'good' : 'muted'}>{a.canPublish ? copy.automations.canPublish : copy.automations.cannotPublish}</Pill> : null}
                </span>
                {a.levels ? (
                  <span className='text-muted-foreground text-xs'>
                    {Object.entries(a.levels)
                      .filter(([, level]) => level)
                      .map(([name, level]) => `${name.replaceAll('_', ' ')}: ${level}`)
                      .join(' · ')}
                  </span>
                ) : null}
                {!a.canPublish && a.publishReason ? <span className='text-muted-foreground text-xs'>{a.publishReason}</span> : null}
              </li>
            ))}
          </ul>
          {data.attention.state === 'unavailable' ? <p className='text-muted-foreground text-xs'>{copy.automations.attentionUnavailable}</p> : null}
          {data.attention.items.length ? (
            <ul className='flex flex-col gap-1 text-xs'>
              {data.attention.items.map((item, i) => (
                <li key={i} className='flex flex-wrap items-center gap-2'>
                  {item.severity ? <Pill tone={item.severity === 'critical' ? 'attention' : 'waiting'}>{item.severity}</Pill> : null}
                  {item.href ? (
                    <a className='rafii-focus text-primary underline-offset-4 hover:underline' href={item.href}>
                      {item.title ?? item.kind}
                    </a>
                  ) : (
                    <span>{item.title ?? item.kind}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          {data.accounts.some((a) => a.needsReconnect) && data.recovery?.href ? (
            <a className='rafii-focus text-primary text-xs underline-offset-4 hover:underline' href={data.recovery.href}>
              {copy.automations.reconnect}
            </a>
          ) : null}
        </div>
      )}
    </QueryFrame>
  );
}

export function RecoveryGuides({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='recovery_guides' label={copy.automations.guidesTitle} title={copy.automations.guidesTitle}>
      {(data) => (
        <ul className='flex flex-col gap-1.5 text-sm'>
          {data.guides.map((g) => (
            <li key={g.guideId} className='flex flex-col gap-0.5'>
              {g.href && g.canOpen !== false ? (
                <a className='rafii-focus text-primary font-medium underline-offset-4 hover:underline' href={g.href}>
                  {g.title ?? g.guideId}
                </a>
              ) : (
                <span className='font-medium'>{g.title ?? g.guideId}</span>
              )}
              {g.summary ? <span className='text-muted-foreground text-xs'>{g.summary}</span> : null}
              {g.canOpen === false && g.reason ? <span className='text-muted-foreground text-xs'>{g.reason}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </QueryFrame>
  );
}

const changeProps = z.object({ actionId: z.literal('automation_change_prepare'), name: z.string().regex(/^[A-Za-z][A-Za-z0-9_]{0,39}$/) });

export function AutomationChangeForm({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = changeProps.safeParse(props);
  const name = literal.success ? literal.data.name : 'change';
  const automation = useBound<string>(`${statementId ?? name}Automation`, props.automation);
  const request = useBound<string>(name, undefined);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  const automationId = typeof automation.value === 'string' && ID.test(automation.value) ? automation.value : null;
  const text = typeof request.value === 'string' ? request.value : '';
  const ready = Boolean(automationId) && text.trim().length >= 3 && text.length <= 400;
  const fieldId = `${statementId ?? name}-request`;
  return (
    <section aria-label={copy.automations.changeTitle} className='flex flex-col gap-2'>
      <h3 className='text-sm font-semibold'>{copy.automations.changeTitle}</h3>
      <label className='flex flex-col gap-1 text-xs' htmlFor={fieldId}>
        {copy.automations.changeLabel}
        <Textarea id={fieldId} rows={3} maxLength={400} value={text} dir='auto' onChange={(e) => request.set(e.target.value)} />
      </label>
      <p className='text-muted-foreground text-xs'>{copy.automations.changeHint}</p>
      <GuardedAction
        actionId={literal.data.actionId}
        controlId={statementId}
        ready={ready}
        notReadyHint={automationId ? undefined : copy.automations.pickAutomation}
        inputs={ready && automationId ? { automationId, request: text.trim() } : null}
      />
    </section>
  );
}
