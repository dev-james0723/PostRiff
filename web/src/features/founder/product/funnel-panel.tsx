'use client';

import { useId, useState } from 'react';
import Link from 'next/link';
import type { UseQueryResult } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { founderHref } from '@/config/founder-nav';
import { StatTile, StatusChip } from '@/features/workspace/rafii-parts';
import { failureOf, useFounderMode } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { ReceiptChip } from '../customers/kit/evidence';
import { count, ratio, seconds, stateLabel, whenDate } from '../customers/kit/format';
import { overallState } from '../customers/kit/metric';
import { DataStateChip, RetryAction } from '../customers/kit/page-frame';
import { PERIOD_LABEL, type PeriodKey } from '../customers/kit/period';
import { ChartCard } from '../customers/kit/shared';
import { SimpleTable } from '../customers/kit/simple-table';
import type { MetricResult } from '../customers/kit/types';
import { barWidth, canDrillStuck, funnelSteps, points, reasonText, signedPoints, sourceLabel, statusRow, stepLabel, timeToValue, type FunnelStep, type StuckWorkspace } from './product-data';
import { useFunnelStuck } from './use-funnel-stuck';

/**
 * Activation (PRD §5.3, §7.2; M23 definition v1): the funnel from signup to a verified publish for the period's
 * matured signups, each step's drop-off, the workspaces stuck before a step (`GET /product/funnel/stuck`), and the
 * median time to value with its n. Every count, rate, drop and median is the server's; a step the server could not
 * measure says why instead of drawing a bar.
 */

type MetricQueryState = Pick<UseQueryResult<MetricResult>, 'data' | 'error' | 'isPending' | 'refetch'>;

const WINDOW_DAYS = 14;

function QueryProblem({ query, label }: { query: MetricQueryState; label: string }) {
  if (query.isPending) return <StateMessage kind='loading' title={`Loading ${label}…`} />;
  const failure = failureOf(query.error);
  return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} title={`Couldn't load ${label}`} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
}

/* ---------- median time to value (tile) ---------- */

export function TimeToValueTile({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  if (query.isPending || query.error) return <QueryProblem query={query} label='time to value' />;
  const ttv = timeToValue(query.data);
  const receipt = query.data?.queryReceiptId ?? null;
  const median = ttv?.median ?? null;
  const n = median !== null ? (ttv?.n ?? null) : null;
  const cohort = ttv?.cohort ?? null;
  const p25 = ttv?.p25 ?? null;
  const p75 = ttv?.p75 ?? null;
  const noFirstValue = median !== null ? (ttv?.noFirstValue ?? null) : null;
  const spread = p25 !== null && p75 !== null ? `middle half ${seconds(p25)}–${seconds(p75)}` : null;
  const missing = noFirstValue !== null && noFirstValue > 0 ? `${count(noFirstValue)} without a first value in ${WINDOW_DAYS} days` : null;
  return (
    <StatTile
      label='Median time to value'
      value={median !== null ? seconds(median) : <span className='text-muted-foreground text-sm font-medium'>{reasonText(ttv?.reason ?? 'not_instrumented', ttv?.row ?? null) ?? 'Not measured.'}</span>}
      hint={n !== null ? `n = ${count(n)}${cohort !== null ? ` of ${count(cohort)} matured signups` : ''}` : undefined}
      footer={[`${PERIOD_LABEL[period]} signups`, spread, missing].filter(Boolean).join(' · ')}
      badge={receipt ? <ReceiptChip receiptId={receipt} /> : undefined}
    />
  );
}

/* ---------- funnel ---------- */

function FunnelTable({ steps }: { steps: FunnelStep[] }) {
  return (
    <SimpleTable<FunnelStep>
      rows={steps}
      rowKey={(step) => step.id}
      caption='Activation funnel: rows behind the steps'
      columns={[
        { key: 'step', label: 'Step', render: (step) => step.label },
        { key: 'reached', label: 'Reached', align: 'right', render: (step) => (step.reached !== null ? count(step.reached) : '—') },
        { key: 'of', label: 'Of', align: 'right', render: (step) => (step.of !== null ? count(step.of) : '—') },
        { key: 'rate', label: 'Conversion', align: 'right', render: (step) => (step.rate !== null ? ratio(step.rate) : '—') },
        { key: 'drop', label: 'Change', align: 'right', render: (step) => (step.drop !== null ? signedPoints(-step.drop) : '—') },
        { key: 'stuck', label: 'Stuck', align: 'right', render: (step) => (step.stuck !== null && step.order > 1 ? count(step.stuck) : '—') },
        { key: 'source', label: 'Source', render: (step) => sourceLabel(step.source) ?? '—' },
        { key: 'state', label: 'State', render: (step) => [stateLabel(step.dataState), reasonText(step.reason, step.row)].filter(Boolean).join(' · ') }
      ]}
    />
  );
}

function StepRow({ step, index, open, controls, onToggle }: { step: FunnelStep; index: number; open: boolean; controls: string; onToggle: () => void }) {
  const measured = step.reached !== null;
  const unknown = measured && step.unknown !== null && step.unknown > 0 ? step.unknown : null;
  return (
    <li className='flex min-w-0 flex-col gap-1.5'>
      <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5'>
        <span className='text-foreground text-sm font-medium'>
          {index + 1}. {step.label}
        </span>
        <span className='text-foreground text-sm tabular-nums'>
          {measured ? (index === 0 || step.of === null ? `${count(step.reached)} workspaces` : `${count(step.reached)} of ${count(step.of)}`) : <span className='text-muted-foreground text-xs'>Not measured</span>}
          {measured && step.rate !== null && index > 0 && <span className='text-muted-foreground'> · {ratio(step.rate)}</span>}
        </span>
      </div>
      <div className='bg-muted h-2 w-full overflow-hidden rounded-full' aria-hidden>
        {measured && step.rate !== null && <span className='block h-full rounded-full' style={{ width: barWidth(step.rate), backgroundColor: 'var(--chart-1)' }} />}
      </div>
      <div className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs'>
        {index > 0 && step.drop !== null && <span>{step.drop >= 0 ? `${points(step.drop)} drop from the previous step` : `${points(step.drop)} above the previous step`}</span>}
        {measured && sourceLabel(step.source) && <span>Source: {sourceLabel(step.source)}</span>}
        {unknown !== null && <span>{count(unknown)} not observed by the events</span>}
        {(!measured || step.reason) && <span>{reasonText(step.reason, step.row) ?? 'Not measured.'}</span>}
        {canDrillStuck(step) && (
          <Button variant='glass' size='xs' aria-expanded={open} aria-controls={controls} onClick={onToggle}>
            {open ? 'Hide' : 'Show'} {count(step.stuck)} stuck before this step
          </Button>
        )}
      </div>
    </li>
  );
}

function StuckList({ step }: { step: FunnelStep }) {
  const mode = useFounderMode();
  const { allowed, query } = useFunnelStuck(step.id, step.interval);
  if (!allowed) {
    return <StateMessage kind='permission' layout='inline' title='Stuck workspaces need customer access' description='This list needs the customers, workspaces and metrics read permissions on your operator.' />;
  }
  const envelope = query.data;
  if (query.isPending) return <StateMessage kind='loading' layout='inline' title='Loading stuck workspaces…' />;
  if (query.error || !envelope) {
    const failure = failureOf(query.error);
    return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} layout='inline' title="Couldn't load stuck workspaces" description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
  }
  const data = envelope.data;
  if (data.reason) return <StateMessage kind='unsupported' layout='inline' title='No stuck list for this step' description={reasonText(data.reason) ?? undefined} />;
  const proxied = data.source !== 'taxonomy';
  return (
    <div className='flex min-w-0 flex-col gap-2'>
      <p className='text-muted-foreground text-xs'>
        Reached “{stepLabel(data.previousStep)}” within {count(data.windowDays)} days of signing up, but not “{stepLabel(data.step)}”. Oldest first
        {data.truncated ? `; the first ${count(data.limit)} are shown` : ''}.{proxied ? ' Part of this step comes from a transition proxy, a lower bound, so a few may have reached it unobserved.' : ''}
      </p>
      <SimpleTable<StuckWorkspace>
        rows={data.rows}
        rowKey={(row) => row.workspaceId}
        caption={`Workspaces stuck before ${stepLabel(data.step)}`}
        emptyTitle='No stuck workspaces'
        emptyDescription='Every matured workspace that reached the previous step also reached this one.'
        columns={[
          {
            key: 'workspace',
            label: 'Workspace',
            render: (row) => (
              <Link href={founderHref('customers', mode, { tab: 'workspaces', q: row.workspaceId })} className='text-foreground inline-flex min-h-6 flex-col justify-center underline-offset-4 hover:underline'>
                <span className='font-medium'>{row.name ?? 'Unnamed workspace'}</span>
                <span className='text-muted-foreground text-xs'>{row.workspaceId}</span>
              </Link>
            )
          },
          { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.plan) },
          { key: 'status', label: 'Status', render: (row) => stateLabel(row.status) },
          { key: 'created', label: 'Signed up', render: (row) => <span className='whitespace-nowrap'>{whenDate(row.createdAt)}</span> }
        ]}
      />
      <div className='flex flex-wrap items-center gap-2'>
        <DataStateChip state={envelope.dataState} asOf={envelope.asOf} />
      </div>
    </div>
  );
}

export function FunnelCard({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  const ask = useAsk();
  const listId = useId();
  const [open, setOpen] = useState<string | null>(null);
  const result = query.data;
  const steps = funnelSteps(result?.rows);
  const anchor = steps[0] ?? null;
  const selected = steps.find((step) => step.id === open && canDrillStuck(step)) ?? null;
  const status = steps.length === 0 ? statusRow(result, 'step') : null;
  const immature = anchor?.immature ?? null;
  return (
    <ChartCard
      title='Activation funnel'
      description={`Workspaces that signed up in this period and are at least ${WINDOW_DAYS} days old: who reached each step within ${WINDOW_DAYS} days of signing up.`}
      period={PERIOD_LABEL[period]}
      receiptId={result?.queryReceiptId ?? null}
      definitionId='activation_funnel'
      definition={`Definition v1 (M23). The cohort is every workspace created in the period that is at least ${WINDOW_DAYS} days old; younger ones join once they mature. A step counts when its product event happened within ${WINDOW_DAYS} days of signup. While the product events are new, channel connection, approval and verified publish fall back to transition proxies (channel audit, learning approvals, publish notifications), labelled on each step; a proxy is a lower bound. Steps without a proxy count only the workspaces the events observed for their whole window.`}
      dataState={result ? overallState(result.rows) : undefined}
      asOf={result?.asOf ?? null}
      data={steps.length > 0 ? <FunnelTable steps={steps} /> : undefined}
      onAsk={() => ask({ prompt: 'Where do new workspaces drop out of activation this period, which step loses the most, and what do the stuck workspaces have in common?', chart: 'activation_funnel', period })}
    >
      {query.isPending || query.error ? (
        <QueryProblem query={query} label='the activation funnel' />
      ) : steps.length === 0 ? (
        <StateMessage kind='unsupported' title='The activation funnel is not measured yet' description={reasonText(status?.reason ?? 'not_instrumented', status) ?? undefined} />
      ) : anchor && anchor.reached === 0 ? (
        <StateMessage kind='empty' title='No matured signups in this period' description={`No workspace created in this period is ${WINDOW_DAYS} days old yet${immature ? `; ${count(immature)} will join the funnel as they mature` : ''}.`} />
      ) : (
        <div className='flex min-w-0 flex-col gap-4'>
          {immature !== null && immature > 0 && (
            <p className='text-muted-foreground text-xs'>
              {count(immature)} newer {immature === 1 ? 'signup is' : 'signups are'} not counted until {immature === 1 ? 'it is' : 'they are'} {WINDOW_DAYS} days old.
            </p>
          )}
          <ol className='flex min-w-0 flex-col gap-4' aria-label='Activation steps'>
            {steps.map((step, index) => (
              <StepRow key={step.id} step={step} index={index} open={open === step.id} controls={listId} onToggle={() => setOpen(open === step.id ? null : step.id)} />
            ))}
          </ol>
          {selected && (
            <section id={listId} aria-label={`Workspaces stuck before ${selected.label}`} className='flex min-w-0 flex-col gap-3 border-t pt-4'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <h3 className='text-foreground text-sm font-medium'>Stuck before “{selected.label}”</h3>
                <div className='flex items-center gap-2'>
                  {selected.source !== 'taxonomy' && (
                    <StatusChip status='info' icon={null}>
                      {sourceLabel(selected.source) ?? 'Proxy'}
                    </StatusChip>
                  )}
                  <Button variant='quiet' size='sm' onClick={() => setOpen(null)}>
                    Close
                  </Button>
                </div>
              </div>
              <StuckList step={selected} />
            </section>
          )}
        </div>
      )}
    </ChartCard>
  );
}
