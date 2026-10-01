'use client';

import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { failureOf } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { TimeSeriesChart } from '../customers/kit/charts';
import { count, ratio, seconds, stateLabel } from '../customers/kit/format';
import { overallState } from '../customers/kit/metric';
import { MetricChartCard, RetryAction } from '../customers/kit/page-frame';
import { PERIOD_LABEL, type PeriodKey } from '../customers/kit/period';
import { ChartCard } from '../customers/kit/shared';
import { SimpleTable } from '../customers/kit/simple-table';
import type { MetricResult } from '../customers/kit/types';
import {
  CONFIDENCE_HINT,
  adoptionItems,
  barWidth,
  cellOpacity,
  confidenceColor,
  correlationItems,
  eligibleWorkspaces,
  reasonText,
  retentionGrid,
  signedPoints,
  sourceLabel,
  statusRow,
  timeBackSeries,
  timeBackTotals,
  windowSeries,
  type AdoptionItem,
  type ConfidenceTotal,
  type CorrelationItem,
  type RetentionCell
} from './product-data';

/**
 * The Product page's panels beside the funnel (PRD §5.3, §7.2): feature adoption over eligible workspaces, time back by
 * confidence (three colours, never added together), the weekly retention heatmap (grey cells have not finished), the
 * retention correlations labelled as a hypothesis, and the daily activity and publishing charts. Values, shares,
 * denominators and differences are the server's; bar widths and swatch strength are geometry from those values.
 */

type MetricQueryState = Pick<UseQueryResult<MetricResult>, 'data' | 'error' | 'isPending' | 'refetch'>;

/** Loading, error and "the server could not break this down" states, shared by the custom panels. */
function PanelBody({ query, label, status, unavailableTitle, children }: { query: MetricQueryState; label: string; status: ReturnType<typeof statusRow>; unavailableTitle: string; children: () => ReactNode }) {
  if (query.isPending) return <StateMessage kind='loading' title={`Loading ${label}…`} />;
  if (query.error || !query.data) {
    const failure = failureOf(query.error);
    return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} title={`Couldn't load ${label}`} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
  }
  if (status) return <StateMessage kind='unsupported' title={unavailableTitle} description={reasonText(status.reason ?? 'not_instrumented', status) ?? undefined} />;
  return <>{children()}</>;
}

/* ---------- feature adoption ---------- */

function AdoptionTable({ items }: { items: AdoptionItem[] }) {
  return (
    <SimpleTable<AdoptionItem>
      rows={items}
      rowKey={(item) => item.feature}
      caption='Feature adoption: rows behind the bars'
      columns={[
        { key: 'feature', label: 'Feature', render: (item) => item.label },
        { key: 'adopters', label: 'Used it', align: 'right', render: (item) => (item.adopters !== null ? count(item.adopters) : '—') },
        { key: 'eligible', label: 'Eligible', align: 'right', render: (item) => (item.eligible !== null ? count(item.eligible) : '—') },
        { key: 'share', label: 'Share', align: 'right', render: (item) => (item.share !== null ? ratio(item.share) : '—') },
        { key: 'state', label: 'State', render: (item) => [stateLabel(item.dataState), reasonText(item.reason, item.row)].filter(Boolean).join(' · ') }
      ]}
    />
  );
}

export function AdoptionCard({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  const ask = useAsk();
  const result = query.data;
  const items = adoptionItems(result?.rows);
  const eligible = eligibleWorkspaces(items);
  return (
    <ChartCard
      title='Feature adoption'
      description='Share of eligible workspaces (active in the period) that used each feature at least once.'
      period={PERIOD_LABEL[period]}
      receiptId={result?.queryReceiptId ?? null}
      definitionId='feature_adoption'
      definition='Eligible workspaces are those with a completed run, product event or publish in the period (activity v1), excluding internal, test and demo workspaces. A feature counts once per workspace. While product events are new, review and publishing also count their transition proxies, labelled on the row.'
      dataState={result ? overallState(result.rows) : undefined}
      asOf={result?.asOf ?? null}
      data={items.length > 0 ? <AdoptionTable items={items} /> : undefined}
      onAsk={() => ask({ prompt: 'Which features do eligible workspaces actually reuse this period, and which ones are rarely touched?', chart: 'feature_adoption', period })}
    >
      <PanelBody query={query} label='feature adoption' status={items.length === 0 ? statusRow(result, 'feature') : null} unavailableTitle='Feature adoption is not measured yet'>
        {() =>
          items.length === 0 ? (
            <StateMessage kind='empty' title='No features reported' />
          ) : (
            <div className='flex min-w-0 flex-col gap-3'>
              {eligible !== null && <p className='text-muted-foreground text-xs'>Eligible: {count(eligible)} active workspaces.</p>}
              <ul className='flex min-w-0 flex-col gap-3' aria-label='Feature adoption by feature'>
                {items.map((item) => (
                  <li key={item.feature} className='flex min-w-0 flex-col gap-1'>
                    <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5'>
                      <span className='text-foreground text-sm'>{item.label}</span>
                      {item.share !== null ? (
                        <span className='text-foreground text-sm tabular-nums'>
                          {ratio(item.share)}
                          <span className='text-muted-foreground text-xs'>
                            {' '}
                            · {count(item.adopters)} of {count(item.eligible)}
                          </span>
                        </span>
                      ) : (
                        <span className='text-muted-foreground text-xs'>{reasonText(item.reason, item.row) ?? 'Not measured.'}</span>
                      )}
                    </div>
                    {item.share !== null && (
                      <div className='bg-muted h-1.5 w-full overflow-hidden rounded-full' aria-hidden>
                        <span className='block h-full rounded-full' style={{ width: barWidth(item.share), backgroundColor: 'var(--chart-2)' }} />
                      </div>
                    )}
                    {item.share !== null && item.dataState !== 'measured' && (
                      <span className='text-muted-foreground text-xs'>{[sourceLabel(item.source), reasonText(item.reason, item.row)].filter(Boolean).join(' · ')}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )
        }
      </PanelBody>
    </ChartCard>
  );
}

/* ---------- time back by confidence ---------- */

function TimeBackTable({ totals }: { totals: ConfidenceTotal[] }) {
  return (
    <SimpleTable<ConfidenceTotal>
      rows={totals}
      rowKey={(item) => item.confidence}
      caption='Time back by confidence: one row each, never added together'
      columns={[
        { key: 'confidence', label: 'Confidence', render: (item) => item.label },
        { key: 'seconds', label: 'Time back', align: 'right', render: (item) => (item.seconds !== null ? seconds(item.seconds) : '—') },
        { key: 'tasks', label: 'Tasks', align: 'right', render: (item) => (item.tasks !== null ? count(item.tasks) : '—') },
        { key: 'state', label: 'State', render: (item) => (item.dataState ? [stateLabel(item.dataState), reasonText(item.reason)].filter(Boolean).join(' · ') : 'No tasks recorded') }
      ]}
    />
  );
}

export function TimeBackCard({ totals, daily, period }: { totals: MetricQueryState; daily: MetricQueryState; period: PeriodKey }) {
  const ask = useAsk();
  const result = totals.data;
  const items = timeBackTotals(result?.rows);
  const status = statusRow(result, 'confidence');
  const series = timeBackSeries(daily.data?.rows);
  const receipts = [result?.queryReceiptId, daily.data?.queryReceiptId].filter((id): id is string => typeof id === 'string' && id.length > 0);
  return (
    <ChartCard
      title='Time back'
      description='Time Rafii gave back on completed work, by how it was measured. Measured, personalized and estimated time are kept apart and never added together.'
      period={PERIOD_LABEL[period]}
      receiptIds={receipts}
      definitionId='time_back'
      definition='M24. Measured: active time recorded on the task. Personalized: the person’s own baseline for that kind of task. Estimated: Rafii’s default baseline. Each is a separate total; there is no combined figure.'
      dataState={result ? overallState(result.rows) : undefined}
      asOf={result?.asOf ?? null}
      data={status ? undefined : <TimeBackTable totals={items} />}
      onAsk={() => ask({ prompt: 'How much time did Rafii give back this period, how much of it is measured rather than estimated, and which tasks drive it?', chart: 'time_back', period })}
    >
      <PanelBody query={totals} label='time back' status={status} unavailableTitle='Time back is not measured yet'>
        {() => (
          <div className='flex min-w-0 flex-col gap-4'>
            <dl className='grid min-w-0 gap-2 sm:grid-cols-3'>
              {items.map((item) => (
                <div key={item.confidence} className='rafii-quiet flex min-w-0 flex-col gap-0.5 rounded-[var(--rafii-radius-control)] p-3'>
                  <dt className='text-muted-foreground flex items-center gap-1.5 text-xs font-medium'>
                    <span aria-hidden className='size-2 shrink-0 rounded-full' style={{ backgroundColor: confidenceColor(item.confidence) }} />
                    {item.label}
                  </dt>
                  <dd className='text-foreground text-lg font-semibold tabular-nums'>{item.seconds !== null ? seconds(item.seconds) : <span className='text-muted-foreground text-sm font-normal'>{item.dataState ? (reasonText(item.reason) ?? 'Not measured') : 'None recorded'}</span>}</dd>
                  <dd className='text-muted-foreground text-xs'>
                    {item.tasks !== null ? `${count(item.tasks)} ${item.tasks === 1 ? 'task' : 'tasks'} · ` : ''}
                    {CONFIDENCE_HINT[item.confidence]}
                  </dd>
                </div>
              ))}
            </dl>
            {daily.isPending ? (
              <StateMessage kind='loading' layout='inline' title='Loading daily time back…' />
            ) : daily.error ? (
              <StateMessage kind={failureOf(daily.error).status === 403 ? 'permission' : 'error'} layout='inline' title="Couldn't load daily time back" description={failureOf(daily.error).message} action={<RetryAction onRetry={() => void daily.refetch()} />} />
            ) : (
              <TimeSeriesChart series={series} kind='bar' emptyTitle='No daily time back in this period' />
            )}
          </div>
        )}
      </PanelBody>
    </ChartCard>
  );
}

/* ---------- weekly retention heatmap ---------- */

function RetentionCellView({ cell }: { cell: RetentionCell | undefined }) {
  if (!cell || !cell.matured) {
    return (
      <div className='flex min-w-12 flex-col items-center gap-0.5'>
        <span aria-hidden className='bg-muted block h-3 w-full rounded-sm' />
        <span className='text-muted-foreground text-[11px]' aria-hidden>
          —
        </span>
        <span className='sr-only'>{cell ? 'Not finished yet' : 'No row'}</span>
      </div>
    );
  }
  if (cell.share === null) {
    return (
      <div className='flex min-w-12 flex-col items-center gap-0.5'>
        <span aria-hidden className='bg-muted block h-3 w-full rounded-sm' />
        <span className='text-muted-foreground text-[11px]'>{stateLabel(cell.reason ?? cell.dataState)}</span>
      </div>
    );
  }
  return (
    <div className='flex min-w-12 flex-col items-center gap-0.5'>
      <span aria-hidden className='block h-3 w-full rounded-sm' style={{ backgroundColor: 'var(--chart-1)', opacity: cellOpacity(cell.share) }} />
      <span className='text-foreground text-[11px] font-medium tabular-nums'>{ratio(cell.share)}</span>
      <span className='text-muted-foreground text-[10px] tabular-nums'>
        {count(cell.retained)}/{count(cell.size)}
      </span>
    </div>
  );
}

export function RetentionCard({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  const ask = useAsk();
  const result = query.data;
  const grid = retentionGrid(result?.rows);
  return (
    <ChartCard
      title='Weekly retention'
      description='Each row is a signup week; each column a week since signup. A cell is the share of that cohort active in that week, with active / cohort size. Grey cells have not finished yet.'
      period={PERIOD_LABEL[period]}
      receiptId={result?.queryReceiptId ?? null}
      definitionId='retention_weekly'
      definition='A workspace is active in a week when it has a completed run, product event or publish that week (activity v1). Cohorts are local signup weeks; a cell is reported only once its week has ended. The heatmap needs 8 weeks of history before it is shown.'
      dataState={result ? overallState(result.rows) : undefined}
      asOf={result?.asOf ?? null}
      onAsk={() => ask({ prompt: 'How do recent signup cohorts retain week by week, and which cohort stands out?', chart: 'retention_weekly', period })}
    >
      <PanelBody query={query} label='weekly retention' status={grid.cohorts.length === 0 ? statusRow(result, 'cohort') : null} unavailableTitle='Weekly retention is not available yet'>
        {() =>
          grid.cohorts.length === 0 ? (
            <StateMessage kind='empty' title='No signups in this period' description='Retention cohorts appear once workspaces sign up.' />
          ) : (
            <Table aria-label='Weekly retention by signup cohort' className='w-max min-w-full'>
              <caption className='sr-only'>Weekly retention by signup cohort: share of each cohort active in each week since signup, with active and cohort counts. Weeks that have not finished are marked.</caption>
              <TableHeader>
                <TableRow className='hover:bg-transparent'>
                  <TableHead scope='col' className='whitespace-nowrap'>
                    Signup week
                  </TableHead>
                  <TableHead scope='col' className='text-right whitespace-nowrap'>
                    Signups
                  </TableHead>
                  {grid.weeks.map((week) => (
                    <TableHead key={week} scope='col' className='px-1 text-center whitespace-nowrap'>
                      <span aria-hidden>W{week}</span>
                      <span className='sr-only'>Week {week}</span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {grid.cohorts.map((cohort) => (
                  <TableRow key={cohort.cohort} className='hover:bg-transparent'>
                    <TableHead scope='row' className='font-normal whitespace-nowrap'>
                      {cohort.label}
                    </TableHead>
                    <TableCell className='text-right tabular-nums'>{cohort.size !== null ? count(cohort.size) : '—'}</TableCell>
                    {grid.weeks.map((week) => (
                      <TableCell key={week} className='px-1 py-1.5'>
                        <RetentionCellView cell={cohort.cells.find((cell) => cell.week === week)} />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )
        }
      </PanelBody>
    </ChartCard>
  );
}

/* ---------- retention correlations (hypothesis) ---------- */

function retainedText(retained: number | null, of: number | null, share: number | null): string {
  if (retained === null || of === null || share === null) return '—';
  return `${ratio(share)} · ${count(retained)} of ${count(of)}`;
}

export function CorrelationsCard({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  const ask = useAsk();
  const result = query.data;
  const items = correlationItems(result?.rows);
  return (
    <ChartCard
      eyebrow='Hypothesis'
      title='Retention and feature use'
      description='Signups from this period that are at least 8 weeks old: the share still active in weeks 4–7, for workspaces that used a feature in their first 14 days against those that did not. A correlation to look into, not a cause.'
      period={PERIOD_LABEL[period]}
      receiptId={result?.queryReceiptId ?? null}
      definitionId='retention_correlations'
      definition='P2 hypothesis. Retained = active (completed run, product event or publish) between day 28 and day 56 after signup. Adopters used the feature within 14 days of signup. Each group needs at least 10 workspaces or the row is withheld. Workspaces that adopt features may differ in other ways, so a difference here is a question, not an effect.'
      dataState={result ? overallState(result.rows) : undefined}
      asOf={result?.asOf ?? null}
      actions={
        <StatusChip status='info' icon={null} className='h-6 px-2 text-[11px]'>
          Hypothesis
        </StatusChip>
      }
      onAsk={() => ask({ prompt: 'Which features go with better retention among matured cohorts, and what else could explain the difference? Treat it as a hypothesis.', chart: 'retention_correlations', period })}
    >
      <PanelBody query={query} label='retention correlations' status={items.length === 0 ? statusRow(result, 'feature') : null} unavailableTitle='Retention correlations are not available yet'>
        {() => (
          <SimpleTable<CorrelationItem>
            rows={items}
            rowKey={(item) => item.feature}
            caption='Retention among feature adopters and non-adopters (hypothesis)'
            emptyTitle='No features reported'
            columns={[
              { key: 'feature', label: 'Feature', render: (item) => item.label },
              { key: 'adopters', label: 'Used it: retained', align: 'right', render: (item) => <span className='whitespace-nowrap'>{retainedText(item.adoptersRetained, item.adopters, item.adopterShare)}</span> },
              { key: 'others', label: 'Did not: retained', align: 'right', render: (item) => <span className='whitespace-nowrap'>{retainedText(item.nonAdoptersRetained, item.nonAdopters, item.nonAdopterShare)}</span> },
              { key: 'difference', label: 'Difference', align: 'right', render: (item) => <span className={cn('whitespace-nowrap', item.difference === null && 'text-muted-foreground')}>{signedPoints(item.difference) ?? '—'}</span> },
              { key: 'note', label: 'Note', render: (item) => <span className='text-muted-foreground block min-w-40 text-xs whitespace-normal'>{item.adopterShare !== null ? (item.dataState === 'measured' ? 'Correlation, not cause' : (reasonText(item.reason, item.row) ?? stateLabel(item.dataState))) : (reasonText(item.reason, item.row) ?? 'Not measured.')}</span> }
            ]}
          />
        )}
      </PanelBody>
    </ChartCard>
  );
}

/* ---------- daily activity and publishing ---------- */

export function ActiveWorkspacesCard({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  return (
    <MetricChartCard query={query} id='active_workspaces' title='Active workspaces' subtitle='Workspaces with a completed run, product event or publish, per day' period={period} unavailableDescription='Active workspaces are counted from agent runs, product events and publish events.'>
      {(result) => <TimeSeriesChart series={windowSeries(result.rows, { label: 'Active workspaces' })} kind='bar' />}
    </MetricChartCard>
  );
}

export function PublishingCard({ query, period }: { query: MetricQueryState; period: PeriodKey }) {
  return (
    <MetricChartCard query={query} id='publish_outcomes' title='Publish outcomes' subtitle='Verified, failed and uncertain publications per day' period={period} unavailableDescription='Publish outcomes come from the publishing jobs; none were measured in this period.'>
      {(result) => <TimeSeriesChart series={windowSeries(result.rows, { by: 'status', order: ['verified', 'failed', 'uncertain'] })} kind='bar' stacked />}
    </MetricChartCard>
  );
}
