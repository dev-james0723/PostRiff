'use client';
/**
 * The drawn part of ToolBoundChart (loaded lazily). Uses the app's shadcn/recharts wrapper and chart tokens; the
 * generated frame scopes `--chart-*` overrides for the dark Rafii panel. Gaps are never connected (unknown ≠ 0) and
 * nothing animates.
 */
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import type { ChartPoint } from './chart';

export interface ChartCanvasProps {
  kind: 'line' | 'bar';
  points: ChartPoint[];
  series: { key: string; label: string; unit?: string }[];
  formatNumber(value: number): string;
}

export default function ChartCanvas(props: ChartCanvasProps) {
  const config: ChartConfig = Object.fromEntries(
    props.series.map((s, index) => [s.key, { label: s.unit ? `${s.label} (${s.unit})` : s.label, color: `var(--chart-${(index % 5) + 1})` }]),
  );
  const axis = { tickLine: false, axisLine: false, tickMargin: 8, minTickGap: 16 } as const;
  const yAxis = <YAxis {...axis} width={48} tickFormatter={(value: number) => props.formatNumber(value)} />;
  return (
    <ChartContainer config={config} className="aspect-auto h-full w-full">
      {props.kind === 'bar' ? (
        <BarChart data={props.points} accessibilityLayer>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="x" {...axis} />
          {yAxis}
          <ChartTooltip content={<ChartTooltipContent />} />
          {props.series.map((s) => (
            <Bar key={s.key} dataKey={s.key} fill={`var(--color-${s.key})`} radius={3} isAnimationActive={false} />
          ))}
        </BarChart>
      ) : (
        <LineChart data={props.points} accessibilityLayer>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="x" {...axis} />
          {yAxis}
          <ChartTooltip content={<ChartTooltipContent />} />
          {props.series.map((s) => (
            <Line
              key={s.key}
              dataKey={s.key}
              type="monotone"
              stroke={`var(--color-${s.key})`}
              strokeWidth={2}
              dot={props.points.length <= 40}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      )}
    </ChartContainer>
  );
}
