'use client';

import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from 'recharts';
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { tickDate, usdMicro } from '../customers/kit/format';
import type { ForecastView } from './adapters';

/**
 * Budget vs forecast (PRD §7.2): the month's cumulative AI cost — actual days as a solid line, the scenario projection
 * dashed — with the global monthly budget as a reference line. Every point is a server row; nothing is projected here.
 */
const CONFIG: ChartConfig = {
  actual: { label: 'Actual (cumulative)', color: 'var(--chart-1)' },
  projection: { label: 'Scenario projection', color: 'var(--chart-2)' }
};

export function ForecastChart({ view }: { view: ForecastView }) {
  const budget = view.budget.stop;
  return (
    <ChartContainer config={CONFIG} className='aspect-[16/7] min-h-48 w-full'>
      <LineChart data={view.points} margin={{ left: 0, right: 12, top: 12, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray='3 3' />
        <XAxis dataKey='t' tickLine={false} axisLine={false} minTickGap={24} tickFormatter={(value: string) => tickDate(value)} />
        <YAxis tickLine={false} axisLine={false} width={72} tickFormatter={(value: number) => usdMicro(value)} />
        <ChartTooltip
          cursor={{ strokeDasharray: '3 3' }}
          content={
            <ChartTooltipContent
              labelFormatter={(label) => tickDate(String(label))}
              formatter={(value, name) => (
                <div className='flex w-full items-center justify-between gap-3'>
                  <span className='text-muted-foreground'>{String(CONFIG[String(name)]?.label ?? name)}</span>
                  <span className='text-foreground font-mono font-medium tabular-nums'>{typeof value === 'number' ? usdMicro(value) : 'Unavailable'}</span>
                </div>
              )}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        {budget !== null && (
          <ReferenceLine
            y={budget}
            ifOverflow='extendDomain'
            stroke='var(--muted-foreground)'
            strokeDasharray='2 4'
            label={{ value: `Monthly budget ${usdMicro(budget)}`, position: 'insideTopLeft', fill: 'var(--muted-foreground)', fontSize: 11 }}
          />
        )}
        <Line dataKey='actual' type='monotone' stroke='var(--color-actual)' strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        <Line dataKey='projection' type='monotone' stroke='var(--color-projection)' strokeWidth={2} strokeDasharray='6 4' dot={false} connectNulls={false} isAnimationActive={false} />
      </LineChart>
    </ChartContainer>
  );
}
