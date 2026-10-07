'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts';
import { Icons } from '@/components/icons';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { ChartContainer, ChartTooltip, type ChartConfig } from '@/components/ui/chart';
import { founderSafeHref } from '@/features/founder/shared';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { useFounderMode, useMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { count, metricValue, minor, ratio, stateLabel, unitFormatter, whenDate } from '../customers/kit/format';
import { MetricChartCard, Panel, QueryState } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { SimpleTable } from '../customers/kit/simple-table';
import type { MetricRow } from '../customers/kit/types';
import { useRevenueMovements } from './hooks';
import { bridgeBars, currenciesOf, historyNote, isMovement, reasonText, shortId, STEP_LABEL } from './rows';
import type { BridgeBar, Movement, MovementRow } from './types';

/**
 * The MRR bridge (PRD §7.2): opening MRR, new · expansion · reactivation · contraction · churn and closing MRR for the
 * period, one native currency at a time. The waterfall is a stacked bar whose transparent base floats each segment;
 * the reconciliation table underneath lists the same server rows, and choosing a segment (bar or row) lists the
 * customers behind it, each linking to Customer 360.
 */

const COLORS: Record<BridgeBar['direction'], string> = { total: 'var(--chart-1)', up: 'var(--chart-2)', down: 'var(--chart-5)' };

function BridgeTooltip({ active, payload, format }: { active?: boolean; payload?: Array<{ payload?: BridgeBar }>; format: (value: number) => string }) {
  const bar = active ? payload?.[0]?.payload : undefined;
  if (!bar) return null;
  return (
    <div className='border-border/50 bg-background grid min-w-[9rem] gap-1 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl'>
      <span className='font-medium'>{bar.label}</span>
      <span className='text-foreground font-mono tabular-nums'>{bar.value === null ? 'Unavailable' : format(bar.value)}</span>
      {bar.customers !== null && <span className='text-muted-foreground'>{count(bar.customers)} customers</span>}
    </div>
  );
}

function Waterfall({ bars, currency, onSelect }: { bars: BridgeBar[]; currency: string | null; onSelect: (movement: Movement) => void }) {
  const format = useMemo(() => unitFormatter('currency_minor', currency), [currency]);
  const config: ChartConfig = { size: { label: 'MRR', color: 'var(--chart-1)' } };
  return (
    <ChartContainer config={config} className='aspect-[16/8] min-h-56 w-full'>
      <BarChart data={bars} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray='3 3' />
        <XAxis dataKey='short' tickLine={false} axisLine={false} interval={0} tickMargin={6} tick={{ fontSize: 11 }} />
        <YAxis tickLine={false} axisLine={false} width={72} tickFormatter={(value: number) => format(value)} />
        <ChartTooltip cursor={{ fill: 'var(--muted)' }} content={<BridgeTooltip format={format} />} />
        <Bar dataKey='base' stackId='bridge' fill='transparent' isAnimationActive={false} />
        <Bar
          dataKey='size'
          stackId='bridge'
          radius={3}
          isAnimationActive={false}
          onClick={(entry: { payload?: BridgeBar }) => {
            const step = entry?.payload?.step;
            if (isMovement(step)) onSelect(step);
          }}
        >
          {bars.map((bar) => (
            <Cell key={bar.step} fill={COLORS[bar.direction]} cursor={isMovement(bar.step) ? 'pointer' : 'default'} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

function ReconciliationTable({ bars, rows, currency, selected, onSelect }: { bars: BridgeBar[]; rows: MetricRow[]; currency: string | null; selected: Movement | null; onSelect: (movement: Movement) => void }) {
  const rowFor = (bar: BridgeBar) => rows.find((row) => row.dimensions?.movement === bar.step && (row.currency ?? row.dimensions?.currency ?? null) === currency) ?? null;
  return (
    <SimpleTable
      rows={bars}
      rowKey={(bar) => bar.step}
      caption={`MRR bridge reconciliation${currency ? ` in ${currency}` : ''}: opening, the five movements and closing`}
      onRowClick={(bar) => {
        if (isMovement(bar.step)) onSelect(bar.step);
      }}
      columns={[
        {
          key: 'step',
          label: 'Step',
          render: (bar) => (
            <span className={cn('flex items-center gap-2', bar.step === selected && 'font-semibold')}>
              <span aria-hidden className='size-2 shrink-0 rounded-full' style={{ background: COLORS[bar.direction] }} />
              {bar.label}
              {isMovement(bar.step) && <span className='sr-only'>(press Enter to list the customers)</span>}
            </span>
          )
        },
        { key: 'customers', label: 'Customers', align: 'right', render: (bar) => (bar.customers === null ? 'Not recorded' : count(bar.customers)) },
        {
          key: 'amount',
          label: 'MRR',
          align: 'right',
          render: (bar) => {
            const row = rowFor(bar);
            return <span className={cn(bar.value === null && 'text-muted-foreground italic')}>{row ? metricValue(row) : 'Unavailable'}</span>;
          }
        },
        { key: 'state', label: 'State', render: (bar) => stateLabel(bar.dataState) }
      ]}
    />
  );
}

function statusChange(row: MovementRow): string {
  const from = row.statusChange.opening ? stateLabel(row.statusChange.opening) : 'none';
  const to = row.statusChange.closing ? stateLabel(row.statusChange.closing) : 'none';
  return from === to ? to : `${from} → ${to}`;
}

/** The customers behind one segment (`GET /revenue/movements`), largest change first, each linking to Customer 360. */
export function MovementList({ period, movement, onClose }: { period: PeriodKey; movement: Movement; onClose: () => void }) {
  const query = useRevenueMovements(period, movement);
  const mode = useFounderMode();
  return (
    <Panel
      title={`${STEP_LABEL[movement]} · customers`}
      description='Net change per customer between the opening and closing MRR, with the billing events in the period.'
      actions={
        <Button variant='glass' size='sm' onClick={onClose}>
          <Icons.close /> Close
        </Button>
      }
    >
      <QueryState query={query} label={`${STEP_LABEL[movement].toLowerCase()} customers`}>
        {(result) => {
          const data = result.data;
          if (data.reason) {
            return <StateMessage kind='unsupported' layout='inline' title='No customer list for this segment' description={[reasonText(data.reason), historyNote(data), data.collectingSince ? `Collecting since ${whenDate(data.collectingSince)}.` : null].filter(Boolean).join(' ')} />;
          }
          return (
            <div className='flex min-w-0 flex-col gap-2'>
              <SimpleTable
                rows={data.rows}
                rowKey={(row) => `${row.customer}-${row.currency ?? 'none'}`}
                caption={`Customers behind ${STEP_LABEL[movement].toLowerCase()} · ${mode === 'demo' ? 'Demo' : 'Live'}`}
                emptyTitle='No customer moved this way in the period'
                columns={[
                  {
                    key: 'customer',
                    label: 'Customer',
                    render: (row) => {
                      const href = founderSafeHref(row.href);
                      return href ? (
                        <Link href={href} className='rafii-focus text-foreground inline-flex items-center gap-1 underline-offset-4 hover:underline'>
                          {shortId(row.customerId ?? row.workspaceId)} <Icons.arrowUpRight className='size-3.5' aria-hidden />
                          <span className='sr-only'>Open Customer 360</span>
                        </Link>
                      ) : (
                        shortId(row.workspaceId ?? row.customer)
                      );
                    }
                  },
                  { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.plan) },
                  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{statusChange(row)}</StatusChip> },
                  { key: 'opening', label: 'Opening', align: 'right', render: (row) => minor(row.openingMrrMinor, row.currency) },
                  { key: 'closing', label: 'Closing', align: 'right', render: (row) => minor(row.closingMrrMinor, row.currency) },
                  { key: 'change', label: 'Change', align: 'right', render: (row) => minor(row.deltaMinor, row.currency) },
                  { key: 'events', label: 'Events in period', render: (row) => (row.events.length ? `${count(row.events.length)}${row.eventsTruncated ? '+' : ''} · last ${stateLabel(row.events[row.events.length - 1]?.type)}` : 'None in period') }
                ]}
              />
              {data.truncated && <p className='text-muted-foreground text-xs'>Showing the first {count(data.limit)} customers by size of change.</p>}
            </div>
          );
        }}
      </QueryState>
    </Panel>
  );
}

export function MrrBridge({ period }: { period: PeriodKey }) {
  const ask = useAsk();
  const mode = useFounderMode();
  const bridge = useMetric({ id: 'mrr_movements', period, groupBy: ['currency', 'movement'] });
  const churn = useMetric({ id: 'logo_churn', period });
  const [picked, setPicked] = useState<string | null>(null);
  const [selected, setSelected] = useState<Movement | null>(null);
  const rows = bridge.data?.rows ?? [];
  const currencies = currenciesOf(rows);
  const currency = picked && currencies.includes(picked) ? picked : (currencies[0] ?? null);
  const first = rows[0];
  const churnRow = churn.data?.rows[0] ?? null;
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <MetricChartCard
        query={bridge}
        id='mrr_movements'
        title='MRR bridge'
        subtitle='Opening MRR, the five movements and closing MRR for the period'
        period={period}
        askPrompt='Explain this MRR bridge: which movements drove the change, which customers are behind the largest ones, and what is not measured.'
        unavailableTitle={first?.reason === 'insufficient_history' ? 'Not enough billing history yet' : undefined}
        unavailableDescription={[reasonText(first?.reason), historyNote(first)].filter(Boolean).join(' ') || 'The bridge is drawn from recorded billing events only; nothing is estimated in its place.'}
      >
        {(result) => {
          const { bars, complete, reconciles } = bridgeBars(result.rows, currency);
          return (
            <div className='flex min-w-0 flex-col gap-3'>
              {currencies.length > 1 && <SegmentedControl label='Currency' size='sm' widths='content' value={currency ?? ''} onChange={(value) => setPicked(value)} options={currencies.map((value) => ({ value, label: value }))} />}
              {complete ? <Waterfall bars={bars} currency={currency} onSelect={setSelected} /> : <StateMessage kind='partial' layout='inline' title='Some steps are not measured' description='The table lists what was measured; no bar is drawn from incomplete steps.' />}
              {complete && !reconciles && <StateMessage kind='partial' layout='inline' title='The steps do not reconcile' description='Opening plus the movements does not equal closing in this answer. Open the receipt and ask Rafii before relying on it.' />}
              <ReconciliationTable bars={bars} rows={result.rows} currency={currency} selected={selected} onSelect={setSelected} />
              <p className='text-muted-foreground text-xs'>Choose a movement to list the customers behind it. Customers whose MRR is unknown at either end are left out and counted in coverage.</p>
            </div>
          );
        }}
      </MetricChartCard>
      {selected && <MovementList period={period} movement={selected} onClose={() => setSelected(null)} />}
      <div className='rafii-quiet flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-[var(--rafii-radius-card)] px-4 py-3 text-sm'>
        <span className='text-muted-foreground'>Paid customer churn</span>
        <span className='flex flex-wrap items-center gap-2'>
          <span className='text-foreground font-semibold tabular-nums'>{churn.isPending ? 'Loading…' : churnRow && typeof churnRow.value === 'number' && churnRow.dataState !== 'unavailable' ? ratio(churnRow.value) : 'Unavailable'}</span>
          {churnRow?.coverage && typeof churnRow.coverage.denominator === 'number' && churnRow.dataState !== 'unavailable' && (
            <span className='text-muted-foreground text-xs'>
              {count(churnRow.coverage.numerator ?? null)} of {count(churnRow.coverage.denominator)} opening paying customers
            </span>
          )}
          {churnRow && churnRow.dataState === 'unavailable' && <span className='text-muted-foreground text-xs'>{reasonText(churnRow.reason) ?? 'Not collected yet.'}</span>}
          {churnRow?.dataState === 'not_applicable' && <span className='text-muted-foreground text-xs'>No paying customers at the start of the period.</span>}
          <Button variant='quiet' size='sm' onClick={() => ask({ prompt: 'Which paying customers churned in this period, and what happened before they left?', chart: 'logo_churn', period })}>
            <Icons.sparkles /> Ask
          </Button>
        </span>
      </div>
      <Link href={`/founder/customers?mode=${mode}&view=payment_risk`} className={cn(buttonVariants({ variant: 'glass', size: 'sm' }), 'self-start')}>
        Customers with payment risk <Icons.chevronRight />
      </Link>
    </div>
  );
}
