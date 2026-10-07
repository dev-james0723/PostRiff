'use client';

import { useMemo, useState } from 'react';
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { ChartCard } from '@/features/founder/shared';
import { failureOf, useMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { count, minor, tickDate, unitFormatter, whenDate } from '../customers/kit/format';
import { RetryAction } from '../customers/kit/page-frame';
import { useMrrForecast } from './hooks';
import { currenciesOf, forecastPoints, historyNote, reasonText } from './rows';

/**
 * MRR forecast (PRD §10.3, P2): the last 90 days of measured MRR as a solid line and the server's least-squares
 * scenario for the next 30 days as a dashed one. The method, fit window and slope are the server's measures; the line
 * is a scenario to discuss, not a prediction, and the page says so. Before 56 daily snapshots exist the card shows how
 * much history is still missing.
 */

const CONFIG: ChartConfig = { actual: { label: 'MRR (measured)', color: 'var(--chart-1)' }, scenario: { label: 'Scenario (linear)', color: 'var(--chart-3)' } };

export function ForecastPanel() {
  const ask = useAsk();
  const actual = useMetric({ id: 'mrr', period: '90d', groupBy: ['currency', 'window'] });
  const forecast = useMrrForecast(30);
  const [picked, setPicked] = useState<string | null>(null);
  const scenarioRows = useMemo(() => forecast.data?.rows ?? [], [forecast.data]);
  const actualRows = useMemo(() => actual.data?.rows ?? [], [actual.data]);
  const currencies = currenciesOf([...scenarioRows, ...actualRows]);
  const currency = picked && currencies.includes(picked) ? picked : (currencies[0] ?? null);
  const format = useMemo(() => unitFormatter('currency_minor', currency), [currency]);
  const points = useMemo(() => forecastPoints(actualRows, scenarioRows, currency), [actualRows, scenarioRows, currency]);
  const scenario = scenarioRows.find((row) => (row.currency ?? row.dimensions?.currency ?? null) === currency) ?? scenarioRows[0] ?? null;
  const measures = (scenario?.measures ?? {}) as { basis?: string; method?: string; fitDays?: number; slopePerDayMinor?: number; lastActualMinor?: number; lastActualDay?: string; catalogLabel?: string };
  const drawable = scenario !== null && typeof scenario.value === 'number' && scenario.dataState !== 'unavailable';
  return (
    <ChartCard
      title='MRR forecast'
      subtitle='Measured MRR for 90 days and a linear scenario for the next 30'
      eyebrow='Scenario'
      definitionId='mrr_forecast'
      receiptIds={[actual.data?.queryReceiptId, forecast.data?.queryReceiptId].filter((id): id is string => typeof id === 'string')}
      dataState={forecast.data ? (drawable ? scenario!.dataState : 'unavailable') : undefined}
      asOf={forecast.data?.asOf ?? null}
      onAsk={() => ask({ prompt: 'Explain the MRR forecast scenario: what the linear fit assumes, how much history it uses, and what would change it.', chart: 'mrr_forecast' })}
      footer={
        drawable ? (
          <p className='text-muted-foreground text-xs'>
            Scenario, not a prediction: an ordinary least-squares line through the last {count(measures.fitDays ?? null)} daily MRR snapshots
            {typeof measures.slopePerDayMinor === 'number' ? ` (slope ${minor(measures.slopePerDayMinor, currency)} per day)` : ''}
            {measures.lastActualDay ? `, last snapshot ${whenDate(measures.lastActualDay)}` : ''}. It ignores seasonality, price changes and churn shocks.
            {measures.catalogLabel ? ` ${measures.catalogLabel}.` : ''}
          </p>
        ) : null
      }
    >
      {forecast.isPending || actual.isPending ? (
        <StateMessage kind='loading' title='Loading the forecast…' />
      ) : forecast.error ? (
        <StateMessage kind='error' title="Couldn't load the forecast" description={failureOf(forecast.error).message} action={<RetryAction onRetry={() => void forecast.refetch()} />} />
      ) : !drawable ? (
        <StateMessage
          kind='unsupported'
          title={scenario?.reason === 'insufficient_history' ? 'Not enough daily snapshots yet' : 'No forecast yet'}
          description={[historyNote(scenario, 'daily MRR snapshots'), reasonText(scenario?.reason), scenario?.collectingSince ? `Collecting since ${whenDate(scenario.collectingSince)}.` : null].filter(Boolean).join(' ') || 'The scenario needs 56 days of measured MRR snapshots.'}
        />
      ) : (
        <div className='flex min-w-0 flex-col gap-3'>
          {currencies.length > 1 && <SegmentedControl label='Currency' size='sm' widths='content' value={currency ?? ''} onChange={(value) => setPicked(value)} options={currencies.map((value) => ({ value, label: value }))} />}
          <ChartContainer config={CONFIG} className='aspect-[16/7] min-h-48 w-full'>
            <LineChart data={points} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid vertical={false} strokeDasharray='3 3' />
              <XAxis dataKey='t' tickLine={false} axisLine={false} minTickGap={24} tickFormatter={(value: string) => tickDate(value)} />
              <YAxis tickLine={false} axisLine={false} width={72} tickFormatter={(value: number) => format(value)} />
              <ChartTooltip cursor={{ strokeDasharray: '3 3' }} content={<ChartTooltipContent labelFormatter={(label) => tickDate(String(label))} formatter={(value, name) => `${CONFIG[String(name)]?.label ?? name}: ${typeof value === 'number' ? format(value) : 'Unavailable'}`} />} />
              <ChartLegend content={<ChartLegendContent />} />
              <Line dataKey='actual' type='monotone' stroke='var(--color-actual)' strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
              <Line dataKey='scenario' type='monotone' stroke='var(--color-scenario)' strokeWidth={2} strokeDasharray='6 4' dot={false} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          </ChartContainer>
          {actual.error && <StateMessage kind='partial' layout='inline' title='Measured MRR could not be loaded' description='Only the scenario line is drawn.' />}
        </div>
      )}
    </ChartCard>
  );
}
