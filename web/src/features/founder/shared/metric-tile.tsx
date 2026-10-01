'use client';

import { useId } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { NumberTicker } from '@/components/motion/number-ticker';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { Coverage, DataState, SeriesPoint } from '@/lib/founder/types';
import { cn } from '@/lib/utils';
import { formatComparisonPeriod, formatDelta, formatMetricValue } from './format';
import { ReceiptChip } from './receipt-chip';
import { founderSafeHref } from './safe-href';
import { CollectingSince, Unavailable } from './state-fallbacks';

/**
 * One metric tile (PRD §5.2 B): value, delta, a sparkline, the coverage dot, its page and "Ask Rafii". A metric that
 * is not measured shows "collecting since" or the word Unavailable, never a zero; the sparkline draws the server's
 * points as given (a `null` is a gap). Props are flat so a page can spread a `PulseTile` or a metric-row adapter.
 */

const COVERAGE_TONE: Record<string, string> = {
  measured: 'bg-foreground',
  partial: 'bg-foreground/45',
  stale: 'bg-foreground/45',
  unavailable: 'bg-destructive',
  suppressed: 'bg-destructive',
  collecting: 'bg-foreground/25',
  synthetic: 'bg-foreground/60',
  demo: 'bg-foreground/60'
};

function coverageLabel(dataState: DataState, coverage?: Coverage | null): string {
  if (coverage && typeof coverage.known === 'number' && typeof coverage.unknown === 'number') {
    const total = coverage.known + coverage.unknown;
    const share = total > 0 ? Math.round((coverage.known / total) * 100) : null;
    return share === null ? `${dataState} · coverage not reported` : `${dataState} · ${share}% of rows have a known value`;
  }
  return String(dataState);
}

export function CoverageDot({ dataState, coverage, className }: { dataState: DataState; coverage?: Coverage | null; className?: string }) {
  const label = coverageLabel(dataState, coverage);
  return (
    <Tooltip>
      <TooltipTrigger render={<button type='button' aria-label={`Coverage: ${label}`} className={cn('rafii-focus inline-flex size-4 cursor-help items-center justify-center rounded-full', className)} />}>
        <span aria-hidden className={cn('size-2 rounded-full', COVERAGE_TONE[dataState] ?? 'bg-foreground/45')} />
      </TooltipTrigger>
      <TooltipContent side='bottom'>{label}</TooltipContent>
    </Tooltip>
  );
}

export type SparklineInput = ReadonlyArray<number | null> | ReadonlyArray<SeriesPoint> | null | undefined;

function sparkValues(input: SparklineInput): Array<number | null> {
  if (!input) return [];
  return input.map((point) => {
    const value = typeof point === 'number' || point === null ? point : point?.value;
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  });
}

/** A plain polyline of the given points; gaps (null values) break the line rather than reading as zero. */
export function Sparkline({ points, className, height = 28, width = 96 }: { points: SparklineInput; className?: string; height?: number; width?: number }) {
  const id = useId();
  const values = sparkValues(points);
  const measured = values.filter((value): value is number => value !== null);
  if (measured.length < 2) return <span aria-hidden className={cn('block', className)} style={{ height, width }} />;
  const min = Math.min(...measured);
  const max = Math.max(...measured);
  const span = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const segments: string[] = [];
  let current: string[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (current.length) segments.push(current.join(' '));
      current = [];
      return;
    }
    current.push(`${(index * step).toFixed(1)},${(height - 2 - ((value - min) / span) * (height - 4)).toFixed(1)}`);
  });
  if (current.length) segments.push(current.join(' '));
  return (
    <svg aria-hidden className={cn('block overflow-visible text-foreground/70', className)} width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {segments.map((segment, index) => (
        <polyline key={`${id}-${index}`} points={segment} fill='none' stroke='currentColor' strokeWidth={1.5} strokeLinejoin='round' strokeLinecap='round' vectorEffect='non-scaling-stroke' />
      ))}
    </svg>
  );
}

export interface MetricTileProps {
  id: string;
  label: string;
  value: number | null;
  unit: string;
  currency?: string | null;
  delta?: number | null;
  deltaPeriod?: string | null;
  sparkline?: SparklineInput;
  dataState: DataState;
  coverage?: Coverage | null;
  href?: string | null;
  receiptId?: string | null;
  collectingSince?: string | null;
  definition?: string | null;
  /** The window the value covers ("Last 30 days"), shown with the label so a tile carries its period even without a delta (PRD §3.4). */
  periodLabel?: string | null;
  /** "Ask Rafii" about this tile; omitted, the button is not shown. */
  onAsk?: () => void;
  className?: string;
}

export function MetricTile({ id, label, value, unit, currency, delta, deltaPeriod, sparkline, dataState, coverage, href, receiptId, collectingSince, definition, periodLabel, onAsk, className }: MetricTileProps) {
  const ready = dataState === 'measured' || dataState === 'partial' || dataState === 'stale' || dataState === 'synthetic' || dataState === 'demo';
  const shown = ready && value !== null && value !== undefined;
  const change = shown ? formatDelta(delta, unit, currency) : null;
  const safeHref = founderSafeHref(href);
  const numeric = shown && (unit === 'count' || unit === '') && typeof value === 'number';
  return (
    <div data-tile={id} className={cn('rafii-quiet flex min-w-0 flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4', className)}>
      <div className='flex items-start justify-between gap-2'>
        <span className='flex min-w-0 flex-col'>
          <span className='text-muted-foreground min-w-0 truncate text-xs font-medium' title={definition ?? undefined}>
            {label}
          </span>
          {periodLabel && <span className='text-muted-foreground truncate text-[11px]'>{periodLabel}</span>}
        </span>
        <CoverageDot dataState={dataState} coverage={coverage} className='-mt-0.5 -mr-1' />
      </div>
      <div className='flex items-end justify-between gap-3'>
        <span className='text-foreground text-2xl font-semibold tracking-[-0.02em] tabular-nums'>
          {!shown ? (
            dataState === 'collecting' || collectingSince ? <CollectingSince since={collectingSince} className='text-muted-foreground text-sm font-medium' /> : <Unavailable reason={dataState === 'suppressed' ? 'withheld by policy' : 'source not qualified'} className='text-muted-foreground text-sm font-medium' />
          ) : numeric ? (
            <NumberTicker value={value as number} locale />
          ) : (
            formatMetricValue(value, unit, currency)
          )}
        </span>
        {shown && <Sparkline points={sparkline} className='shrink-0' />}
      </div>
      <div className='flex min-h-5 items-center justify-between gap-2 text-xs'>
        {change ? (
          <span className={cn('flex items-center gap-1 tabular-nums', change.direction === 'flat' ? 'text-muted-foreground' : 'text-foreground')}>
            {change.direction === 'up' && <Icons.trendingUp className='size-3.5' aria-hidden />}
            {change.direction === 'down' && <Icons.trendingDown className='size-3.5' aria-hidden />}
            {change.text}
            {deltaPeriod && <span className='text-muted-foreground'>{formatComparisonPeriod(deltaPeriod)}</span>}
          </span>
        ) : (
          <span className='text-muted-foreground'>{shown ? 'No comparison period' : ' '}</span>
        )}
        <span className='flex shrink-0 items-center gap-1'>
          {receiptId && <ReceiptChip receiptId={receiptId} label='Receipt' className='h-6' />}
          {onAsk && (
            <button type='button' onClick={onAsk} aria-label={`Ask Rafii about ${label}`} className='rafii-focus text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full'>
              <Icons.sparkles className='size-3.5' aria-hidden />
            </button>
          )}
          {safeHref && (
            <Link href={safeHref} aria-label={`Open ${label}`} className='rafii-focus text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full'>
              <Icons.arrowUpRight className='size-3.5' aria-hidden />
            </Link>
          )}
        </span>
      </div>
    </div>
  );
}
