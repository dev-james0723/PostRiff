'use client';

import { useMemo } from 'react';
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { ChartCard } from '@/features/founder/shared/chart-card';
import { formatMetricValue, formatTick } from '@/features/founder/shared/format';
import { StateFallback } from '@/features/founder/shared/state-fallbacks';
import type { OverviewTrend } from '@/lib/founder/types';

/**
 * One Overview trend (PRD §5.2 E): two server series on one time axis, drawn only where a bucket was measured (a
 * missing bucket is a gap, never a zero). Points are pivoted by bucket start for Recharts; nothing is summed.
 */

const PALETTE = ['var(--chart-1, var(--foreground))', 'var(--chart-2, color-mix(in oklch, var(--foreground) 45%, transparent))', 'var(--chart-3, var(--primary))'];

type Row = { t: string } & Record<string, number | string | null>;

/** The trend's series as a list; a payload without one (an older server) draws nothing rather than throwing. */
function seriesOf(trend: OverviewTrend | null | undefined): OverviewTrend['series'] {
  return trend && Array.isArray(trend.series) ? trend.series : [];
}

function pivot(trend: OverviewTrend): Row[] {
  const byTime = new Map<string, Row>();
  for (const series of seriesOf(trend)) {
    for (const point of series.points ?? []) {
      let row = byTime.get(point.t);
      if (!row) {
        row = { t: point.t };
        byTime.set(point.t, row);
      }
      row[series.id] = typeof point.value === 'number' && Number.isFinite(point.value) ? point.value : null;
    }
  }
  return [...byTime.values()].toSorted((a, b) => a.t.localeCompare(b.t));
}

export function TrendChart({ trend, title, onAsk, period, onPeriodChange, periods, className }: { trend: OverviewTrend | null; title: string; onAsk: () => void; period: string; onPeriodChange: (period: string) => void; periods: readonly string[]; className?: string }) {
  const rows = useMemo(() => (trend ? pivot(trend) : []), [trend]);
  const list = seriesOf(trend);
  const config = useMemo<ChartConfig>(() => Object.fromEntries(list.map((series, index) => [series.id, { label: series.label, color: PALETTE[index % PALETTE.length] }])), [list]);
  const measured = rows.some((row) => Object.entries(row).some(([key, value]) => key !== 't' && typeof value === 'number'));
  const first = list[0];
  const format = (value: number) => formatMetricValue(value, first?.unit ?? trend?.unit ?? 'count', first?.currency ?? trend?.currency);
  const definition = trend?.definition ?? 'Both lines are server-computed metrics over the same period; a gap is a bucket the source did not measure.';
  const receiptIds = trend?.receiptIds?.length ? trend.receiptIds : trend?.receiptId ? [trend.receiptId] : [];
  return (
    <ChartCard title={trend?.title ?? title} className={className} period={period} periods={periods} onPeriodChange={onPeriodChange} onAsk={onAsk} receiptIds={receiptIds} dataState={trend?.dataState} coverage={trend?.coverage} definition={definition}>
      {!trend ? (
        <StateFallback kind='unavailable' layout='inline' title='Not available in this environment' description='The sources behind this trend are not qualified here yet.' />
      ) : !measured ? (
        <StateFallback kind={trend.dataState === 'collecting' ? 'empty' : 'partial'} layout='inline' title={trend.dataState === 'collecting' ? 'Collecting; nothing measured yet' : 'No measured buckets in this period'} description='Buckets the source has not measured are left blank rather than drawn as zero.' />
      ) : (
        <ChartContainer config={config} className='aspect-[16/7] min-h-44 w-full'>
          <LineChart data={rows} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey='t' tickLine={false} axisLine={false} minTickGap={24} tickFormatter={(value: string) => formatTick(value)} />
            <YAxis tickLine={false} axisLine={false} width={64} tickFormatter={(value: number) => format(value)} />
            <ChartTooltip content={<ChartTooltipContent labelFormatter={(value) => formatTick(String(value))} formatter={(value, name) => <span className='flex w-full items-center justify-between gap-3'><span className='text-muted-foreground'>{config[String(name)]?.label ?? String(name)}</span><span className='text-foreground font-mono font-medium tabular-nums'>{typeof value === 'number' ? format(value) : 'Unavailable'}</span></span>} />} />
            <ChartLegend content={<ChartLegendContent />} />
            {list.map((series) => (
              <Line key={series.id} dataKey={series.id} type='monotone' stroke={`var(--color-${series.id})`} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ChartContainer>
      )}
    </ChartCard>
  );
}
