'use client';

import { useMemo } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { StateMessage } from '@/components/rafii';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { cn } from '@/lib/utils';
import { tickDate, unitFormatter } from './format';
import type { CategoryItem, Series } from './metric';

/**
 * Recharts compositions over `components/ui/chart.tsx` for the domain pages (PRD §7.2). Every point is a server
 * row; a missing bucket is a gap (`null`), never a zero. Colours come from the `--chart-n` tokens only.
 */

const PALETTE = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)'];

function colorAt(index: number) {
  return PALETTE[index % PALETTE.length];
}

function seriesConfig(series: Series): ChartConfig {
  return Object.fromEntries(series.series.map((descriptor, index) => [descriptor.key, { label: descriptor.label, color: colorAt(index) }]));
}

function TooltipRow({ label, value }: { label: string; value: string }) {
  return (
    <div className='flex w-full items-center justify-between gap-3'>
      <span className='text-muted-foreground'>{label}</span>
      <span className='text-foreground font-mono font-medium tabular-nums'>{value}</span>
    </div>
  );
}

export interface TimeSeriesChartProps {
  series: Series;
  kind?: 'area' | 'line' | 'bar';
  stacked?: boolean;
  /** Monthly buckets print month names on the axis. */
  monthly?: boolean;
  className?: string;
  emptyTitle?: string;
}

export function TimeSeriesChart({ series, kind = 'line', stacked = false, monthly = false, className, emptyTitle = 'No measured buckets in this period' }: TimeSeriesChartProps) {
  const config = useMemo(() => seriesConfig(series), [series]);
  const format = useMemo(() => unitFormatter(series.unit, series.currency), [series.unit, series.currency]);
  if (series.points.length === 0 || series.series.every((descriptor) => descriptor.measured === 0)) {
    return <StateMessage kind='empty' layout='inline' title={emptyTitle} description='Buckets the source has not measured are left blank rather than drawn as zero.' />;
  }
  const axis = (
    <>
      <CartesianGrid vertical={false} strokeDasharray='3 3' />
      <XAxis dataKey='t' tickLine={false} axisLine={false} minTickGap={24} tickFormatter={(value: string) => tickDate(value, monthly)} />
      <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={(value: number) => format(value)} />
      <ChartTooltip
        cursor={{ strokeDasharray: '3 3' }}
        content={<ChartTooltipContent labelFormatter={(label) => tickDate(String(label), monthly)} formatter={(value, name) => <TooltipRow label={String(config[String(name)]?.label ?? name)} value={typeof value === 'number' ? format(value) : 'Unavailable'} />} />}
      />
      {series.series.length > 1 && <ChartLegend content={<ChartLegendContent />} />}
    </>
  );
  const stackId = stacked ? 'stack' : undefined;
  return (
    <ChartContainer config={config} className={cn('aspect-[16/7] min-h-48 w-full', className)}>
      {kind === 'area' ? (
        <AreaChart data={series.points} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
          {axis}
          {series.series.map((descriptor) => (
            <Area key={descriptor.key} dataKey={descriptor.key} type='monotone' stackId={stackId} stroke={`var(--color-${descriptor.key})`} fill={`var(--color-${descriptor.key})`} fillOpacity={0.18} connectNulls={false} isAnimationActive={false} />
          ))}
        </AreaChart>
      ) : kind === 'bar' ? (
        <BarChart data={series.points} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
          {axis}
          {series.series.map((descriptor) => (
            <Bar key={descriptor.key} dataKey={descriptor.key} stackId={stackId} fill={`var(--color-${descriptor.key})`} radius={stacked ? 0 : 4} isAnimationActive={false} />
          ))}
        </BarChart>
      ) : (
        <LineChart data={series.points} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
          {axis}
          {series.series.map((descriptor) => (
            <Line key={descriptor.key} dataKey={descriptor.key} type='monotone' stroke={`var(--color-${descriptor.key})`} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          ))}
        </LineChart>
      )}
    </ChartContainer>
  );
}

export interface CategoryBarsProps {
  items: CategoryItem[];
  unit: string;
  currency?: string | null;
  className?: string;
  emptyTitle?: string;
}

/** Horizontal bars for whole-interval rows grouped by one dimension; unmeasured categories are listed, not drawn. */
export function CategoryBars({ items, unit, currency, className, emptyTitle = 'Nothing measured for this breakdown' }: CategoryBarsProps) {
  const format = useMemo(() => unitFormatter(unit, currency), [unit, currency]);
  const measured = items.filter((item) => item.value !== null);
  const unmeasured = items.filter((item) => item.value === null);
  const config: ChartConfig = { value: { label: 'Value', color: 'var(--chart-1)' } };
  if (measured.length === 0) {
    return <StateMessage kind='empty' layout='inline' title={emptyTitle} description={unmeasured.length ? `${unmeasured.length} ${unmeasured.length === 1 ? 'category is' : 'categories are'} not measured yet.` : undefined} />;
  }
  const height = Math.max(120, measured.length * 32 + 24);
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <ChartContainer config={config} className='w-full' style={{ height }} initialDimension={{ width: 320, height }}>
        <BarChart data={measured} layout='vertical' margin={{ left: 0, right: 16, top: 4, bottom: 4 }}>
          <CartesianGrid horizontal={false} strokeDasharray='3 3' />
          <XAxis type='number' tickLine={false} axisLine={false} tickFormatter={(value: number) => format(value)} />
          <YAxis type='category' dataKey='label' tickLine={false} axisLine={false} width={120} tickFormatter={(value: string) => value.replaceAll('_', ' ')} />
          <ChartTooltip cursor={{ fill: 'var(--muted)' }} content={<ChartTooltipContent hideLabel formatter={(value, _name, item) => <TooltipRow label={String((item?.payload as CategoryItem | undefined)?.label ?? '')} value={typeof value === 'number' ? format(value) : 'Unavailable'} />} />} />
          <Bar dataKey='value' fill='var(--color-value)' radius={4} isAnimationActive={false} />
        </BarChart>
      </ChartContainer>
      {unmeasured.length > 0 && (
        <p className='text-muted-foreground text-xs'>
          Not measured: {unmeasured.map((item) => item.label.replaceAll('_', ' ')).join(', ')}.
        </p>
      )}
    </div>
  );
}

export interface CoverageBarProps {
  known: number;
  unknown: number;
  estimated?: number;
  format: (value: number) => string;
  className?: string;
}

/** One bar for known / estimated / unknown cost (PRD §7.2). Widths are geometry; the labels are the server numbers. */
export function CoverageBar({ known, unknown, estimated = 0, format, className }: CoverageBarProps) {
  const total = known + unknown + estimated;
  const width = (part: number) => (total > 0 ? `${(part / total) * 100}%` : '0%');
  const parts = [
    { label: 'Known', value: known, className: 'bg-foreground' },
    { label: 'Estimated', value: estimated, className: 'bg-foreground/45' },
    { label: 'Unknown', value: unknown, className: 'bg-foreground/15' }
  ].filter((part) => part.label !== 'Estimated' || part.value > 0);
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div role='img' aria-label={parts.map((part) => `${part.label} ${format(part.value)}`).join(', ')} className='bg-muted flex h-3 w-full overflow-hidden rounded-full'>
        {parts.map((part) => (
          <span key={part.label} className={cn('h-full', part.className)} style={{ width: width(part.value) }} />
        ))}
      </div>
      <dl className='flex flex-wrap gap-x-4 gap-y-1 text-xs'>
        {parts.map((part) => (
          <div key={part.label} className='flex items-center gap-1.5'>
            <span aria-hidden className={cn('size-2 rounded-full', part.className)} />
            <dt className='text-muted-foreground'>{part.label}</dt>
            <dd className='text-foreground font-medium tabular-nums'>{format(part.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
