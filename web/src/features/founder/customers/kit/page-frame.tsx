'use client';

import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { PageHeader, SegmentedControl, StateMessage, type SegmentOption } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import type { InfobarContent } from '@/components/ui/infobar';
import { Panel } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { failureOf } from './api';
import { useAsk } from './ask';
import { metricValue, stateLabel, tickDate, whenDate } from './format';
import { bucketOf, collectingSince, headlineRow, lastGoodAt, otherDimensions, overallState, tileFromResult, type TileData, type TileInput } from './metric';
import { PERIOD_LABEL, PERIOD_SHORT, type PeriodKey } from './period';
import { ChartCard, DataStateChip as SharedDataStateChip, MetricTile } from './shared';
import { SimpleTable } from './simple-table';
import type { DataState, MetricResult, MetricRow } from './types';

/**
 * The page frame every domain section shares: identity block, period switch, tile row and stacked panels
 * (mobile first, two columns from `md`). Non-measured states always go through `StateMessage`; a tile that is not
 * measured says "collecting since <date>" or why it is not collected, and never renders 0.
 */

export function FounderPage({ eyebrow, title, accent, description, actions, infoContent, children, className }: { eyebrow?: ReactNode; title: ReactNode; accent?: ReactNode; description?: ReactNode; actions?: ReactNode; infoContent?: InfobarContent; children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-5 md:gap-6', className)}>
      <PageHeader eyebrow={eyebrow} title={title} accent={accent} description={description} actions={actions} infoContent={infoContent} />
      {children}
    </div>
  );
}

export function PeriodSwitch({ value, onChange, options, label = 'Period' }: { value: PeriodKey; onChange: (value: PeriodKey) => void; options: PeriodKey[]; label?: string }) {
  const segments: SegmentOption<PeriodKey>[] = options.map((key) => ({ value: key, label: PERIOD_SHORT[key] }));
  return <SegmentedControl options={segments} value={value} onChange={onChange} label={label} size='sm' widths='content' />;
}

/** Tiles: one column on phones, two on small screens, four from `xl`. */
export function TileGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('grid gap-3 sm:grid-cols-2 xl:grid-cols-4', className)}>{children}</div>;
}

/** Panels: stacked on phones, two columns from `md`. */
export function PanelGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('grid gap-4 md:grid-cols-2', className)}>{children}</div>;
}

export { Panel };

/** The shared chip, tolerant of a state that is not known yet (a query still loading). */
export function DataStateChip({ state, asOf, className }: { state: DataState | string | undefined; asOf?: string | null; className?: string }) {
  return <SharedDataStateChip state={state ?? 'unknown'} asOf={asOf} className={className} />;
}

export function RetryAction({ onRetry }: { onRetry: () => void }) {
  return (
    <Button variant='glass' size='default' onClick={onRetry}>
      <Icons.refresh /> Try again
    </Button>
  );
}

type QueryLike<T> = Pick<UseQueryResult<T>, 'data' | 'error' | 'isPending' | 'refetch'>;

/**
 * Renders a query's loading and error states with the shared grammar and hands the data to `children` otherwise.
 * `isEmpty` lets a page say what "nothing" means for it instead of showing an empty table.
 */
export function QueryState<T>({ query, label, isEmpty, emptyTitle, emptyDescription, emptyAction, layout = 'panel', children }: { query: QueryLike<T>; label: string; isEmpty?: (data: T) => boolean; emptyTitle?: ReactNode; emptyDescription?: ReactNode; emptyAction?: ReactNode; layout?: 'panel' | 'inline'; children: (data: T) => ReactNode }) {
  if (query.isPending) return <StateMessage kind='loading' layout={layout} title={`Loading ${label}…`} />;
  if (query.error) {
    const failure = failureOf(query.error);
    return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} layout={layout} title={`Couldn't load ${label}`} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
  }
  if (query.data === undefined) return <StateMessage kind='empty' layout={layout} title={`No ${label} yet`} />;
  if (isEmpty?.(query.data)) return <StateMessage kind='empty' layout={layout} title={emptyTitle ?? `No ${label} yet`} description={emptyDescription} action={emptyAction} />;
  return <>{children(query.data)}</>;
}

/** The honest line under a chart that is not measured: when collection started, the last good read for a stale source, or why there is nothing. */
export function CollectingNote({ dataState, collectingSince, lastGoodAt = null, reason, className }: { dataState: DataState; collectingSince: string | null; lastGoodAt?: string | null; reason: string | null; className?: string }) {
  if (dataState === 'measured') return null;
  const text =
    dataState === 'synthetic' || dataState === 'demo'
      ? 'Demo data.'
      : dataState === 'stale'
        ? `Stale — last good ${lastGoodAt ? whenDate(lastGoodAt) : 'time unknown'}.`
        : dataState === 'partial'
          ? 'Partially measured.'
          : collectingSince
            ? `Collecting since ${whenDate(collectingSince)}.`
            : reason === 'definition_not_activated'
              ? 'Not activated yet.'
              : 'Not collected yet.';
  return (
    <span className={cn('text-muted-foreground block text-xs', className)} role='status'>
      {text}
      {reason && dataState !== 'synthetic' && reason !== 'definition_not_activated' && <span className='ml-1'>({reason.replaceAll('_', ' ')})</span>}
    </span>
  );
}

/**
 * A MetricTile fed by one metric query. The tile itself shows "collecting since" or Unavailable for anything not
 * measured, the receipt chip and its own Ask button; this wrapper only adds the loading / error grammar.
 */
export function MetricTileFromQuery({ query, input, onAsk }: { query: QueryLike<MetricResult>; input: TileInput; onAsk?: (tile: TileData) => void }) {
  if (query.isPending) return <StateMessage kind='loading' title={`Loading ${input.label}…`} />;
  if (query.error) {
    const failure = failureOf(query.error);
    return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} title={input.label} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
  }
  const tile = tileFromResult(query.data, input);
  return (
    <MetricTile
      id={tile.id}
      label={tile.label}
      value={tile.value}
      unit={tile.unit}
      currency={tile.currency}
      delta={tile.delta}
      deltaPeriod={tile.deltaPeriod}
      sparkline={tile.sparkline}
      dataState={tile.dataState}
      coverage={tile.coverage}
      href={tile.href ?? null}
      receiptId={tile.receiptId}
      collectingSince={tile.collectingSince}
      periodLabel={periodLabelFor(input.period)}
      definition={tile.reason ? `Not measured: ${tile.reason.replaceAll('_', ' ')}` : null}
      onAsk={onAsk ? () => onAsk(tile) : undefined}
    />
  );
}

/** "Last 30 days" for a known period key; any other period string is shown as given. */
export function periodLabelFor(period: string): string {
  return period in PERIOD_LABEL ? PERIOD_LABEL[period as PeriodKey] : period;
}

/** A panel for a capability the product has not instrumented yet; says so instead of drawing an empty chart. */
export function NotInstrumented({ title, description, since }: { title: ReactNode; description: ReactNode; since?: string | null }) {
  return <StateMessage kind='unsupported' title={title} description={<>{description}{since ? ` Collecting since ${whenDate(since)}.` : ''}</>} />;
}

/** The rows behind a chart, for ChartCard's "View data": bucket, dimensions, value and state — exactly as returned. */
export function MetricRowsTable({ rows, caption }: { rows: readonly MetricRow[]; caption: string }) {
  return (
    <SimpleTable<MetricRow>
      rows={rows}
      rowKey={(row, index) => `${bucketOf(row) ?? 'whole'}-${JSON.stringify(otherDimensions(row))}-${index}`}
      caption={caption}
      emptyTitle='No rows'
      columns={[
        { key: 'bucket', label: 'Bucket', render: (row) => { const bucket = bucketOf(row); return bucket ? tickDate(bucket) : 'Whole interval'; } },
        { key: 'dimensions', label: 'Dimensions', render: (row) => { const dims = Object.entries(otherDimensions(row)); return dims.length ? dims.map(([key, value]) => `${key}: ${stateLabel(value)}`).join(' · ') : '—'; } },
        { key: 'value', label: 'Value', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{metricValue(row)}</span> },
        { key: 'state', label: 'State', render: (row) => stateLabel(row.dataState) }
      ]}
    />
  );
}

/**
 * A ChartCard over one metric query: the card keeps its Ask / View data / Definition / receipt affordances in every
 * state, and the body is the shared grammar for loading, error, "not collected" and the chart itself. `children`
 * only runs when at least one row is measured, so no chart is ever drawn from nothing.
 */
export function MetricChartCard({ query, id, title, subtitle, period, askPrompt, unavailableTitle, unavailableDescription, children }: { query: QueryLike<MetricResult>; id: string; title: string; subtitle?: string; period: PeriodKey; askPrompt?: string; unavailableTitle?: ReactNode; unavailableDescription?: ReactNode; children: (result: MetricResult) => ReactNode }) {
  const ask = useAsk();
  const result = query.data;
  const state = overallState(result?.rows);
  const first = result?.rows[0];
  const headline = headlineRow(result, id);
  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      receiptId={result?.queryReceiptId ?? null}
      definitionId={id}
      period={PERIOD_LABEL[period]}
      dataState={result ? state : undefined}
      asOf={result?.asOf ?? null}
      coverage={headline?.coverage ?? null}
      data={result && result.rows.length > 0 ? <MetricRowsTable rows={result.rows} caption={`${title}: rows behind the chart`} /> : undefined}
      onAsk={() => ask({ prompt: askPrompt ?? `Explain the "${title}" chart for ${PERIOD_LABEL[period].toLowerCase()}: what changed, what is uncertain, and what I should do next.`, chart: id, period })}
    >
      {query.isPending ? (
        <StateMessage kind='loading' title={`Loading ${title.toLowerCase()}…`} />
      ) : query.error ? (
        (() => {
          const failure = failureOf(query.error);
          return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} title={`Couldn't load ${title.toLowerCase()}`} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
        })()
      ) : !result || result.rows.length === 0 || state === 'unavailable' ? (
        <StateMessage kind='unsupported' title={unavailableTitle ?? `${title} is not collected yet`} description={<>{unavailableDescription ?? 'The source has not produced a measured row for this definition.'} <CollectingNote dataState='unavailable' collectingSince={collectingSince(first)} lastGoodAt={lastGoodAt(first)} reason={first?.reason ?? null} className='mt-1 inline' /></>} />
      ) : (
        <div className='flex flex-col gap-2'>
          {state !== 'measured' && <CollectingNote dataState={state} collectingSince={collectingSince(first)} lastGoodAt={lastGoodAt(first)} reason={first?.reason ?? null} />}
          {children(result)}
        </div>
      )}
    </ChartCard>
  );
}
