'use client';

import Link from 'next/link';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { cn } from '@/lib/utils';
import { useFounderMode, useMetric, useRecords, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars, TimeSeriesChart } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { metricValue, minor, recordLabel, stateLabel, whenDate } from '../customers/kit/format';
import { FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, PeriodSwitch, QueryState, TileGrid } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { SimpleTable } from '../customers/kit/simple-table';
import { useTabState } from '../customers/kit/tabs';
import type { MetricResult } from '../customers/kit/types';
import { CreditsPanels } from './credits';
import { ForecastPanel } from './forecast';
import { DunningPanel, InvoicesPanel } from './invoices';
import { MrrBridge } from './mrr-bridge';
import { categoryItems, currenciesOf, rowsWith, windowSeries } from './rows';
import { NotedMetricTile } from './tile';

/**
 * Revenue & billing (PRD §5.3, §7.2, CONTRACTS §8.A). Tiles for MRR, delinquent MRR, cash and paid customers sit above
 * real tabs (mrr-bridge · cash · subscriptions · payments · refunds · credits · forecast, from founder-nav), and only the
 * active tab's panels query, so a page load stays within the metrics budget. Every number is a receipted server value
 * in its native currency; a definition that is not instrumented says so, never 0. In Demo the catalog is the candidate
 * v2 catalog and is labelled as not active.
 */
const PERIODS: PeriodKey[] = ['30d', '90d'];
const TABS: Array<{ id: string; label: string }> = [
  { id: 'mrr-bridge', label: 'MRR bridge' },
  { id: 'cash', label: 'Cash' },
  { id: 'subscriptions', label: 'Subscriptions' },
  { id: 'payments', label: 'Payments' },
  { id: 'refunds', label: 'Refunds' },
  { id: 'credits', label: 'Credits' },
  { id: 'forecast', label: 'Forecast' }
];

/** One chart per native currency: amounts in different currencies are never drawn on one axis. */
function PerCurrency({ result, render }: { result: MetricResult; render: (currency: string | null) => ReactNode }) {
  const currencies = currenciesOf(result.rows);
  if (currencies.length <= 1) return <>{render(currencies[0] ?? null)}</>;
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      {currencies.map((currency) => (
        <div key={currency} className='flex min-w-0 flex-col gap-1'>
          <span className='text-muted-foreground text-xs font-medium'>{currency}</span>
          {render(currency)}
        </div>
      ))}
    </div>
  );
}

function MrrTrend({ period }: { period: PeriodKey }) {
  const trend = useMetric({ id: 'mrr', period, groupBy: ['currency', 'window'] });
  return (
    <MetricChartCard query={trend} id='mrr' title='MRR by day' subtitle='Normalized monthly recurring revenue at the end of each day' period={period} unavailableDescription='MRR is drawn from recorded Stripe billing events; paid subscriptions without one are unknown, never their list price.'>
      {(result) => <PerCurrency result={result} render={(currency) => <TimeSeriesChart series={windowSeries(result.rows, null, currency)} kind='line' />} />}
    </MetricChartCard>
  );
}

function CashTab({ period }: { period: PeriodKey }) {
  const cash = useMetric({ id: 'cash_collected', period, groupBy: ['currency', 'payment_type', 'window'] });
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <MetricChartCard query={cash} id='cash_collected' title='Cash collected by day' subtitle='Paid invoices of every plan beside credit top-ups' period={period} unavailableDescription='Cash comes from paid invoices (Stripe webhooks) and funded top-ups; neither has landed in this period.'>
        {(result) => <PerCurrency result={result} render={(currency) => <TimeSeriesChart series={windowSeries(result.rows, 'payment_type', currency)} kind='bar' stacked />} />}
      </MetricChartCard>
      <InvoicesPanel period={period} />
    </div>
  );
}

function SubscriptionsTab({ period }: { period: PeriodKey }) {
  const mode = useFounderMode();
  const evidence = useEvidenceDrawer();
  const planStatus = useMetric({ id: 'subscriptions_by_plan_status', period, groupBy: ['plan', 'status'] });
  const byPlan = useMetric({ id: 'mrr', period, groupBy: ['currency', 'plan'] });
  const subscriptions = useRecords({ collection: 'subscriptions', search: '', status: 'all', page: 1, recordId: '' });
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <PanelGrid>
        <MetricChartCard query={planStatus} id='subscriptions_by_plan_status' title='Subscriptions by plan and status' subtitle='Current snapshot by plan × status' period={period} unavailableDescription='The daily subscription snapshot has not written a day yet.'>
          {(result) => (
            <SimpleTable
              rows={rowsWith(result.rows, ['plan', 'status'])}
              rowKey={(row, index) => `${row.dimensions?.plan}-${row.dimensions?.status}-${index}`}
              caption='Subscriptions by plan and status'
              emptyTitle='No subscription rows measured'
              columns={[
                { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.dimensions?.plan) },
                { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.dimensions?.status)}</StatusChip> },
                { key: 'count', label: 'Subscriptions', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{metricValue(row)}</span> }
              ]}
            />
          )}
        </MetricChartCard>
        <MetricChartCard query={byPlan} id='mrr' title='MRR by plan' subtitle='Where recurring revenue sits today' period={period} unavailableDescription='MRR is drawn from recorded Stripe billing events only.'>
          {(result) => <PerCurrency result={result} render={(currency) => <CategoryBars items={categoryItems(result.rows, 'plan', currency)} unit='currency_minor' currency={currency} />} />}
        </MetricChartCard>
      </PanelGrid>
      <Panel
        title='Subscriptions'
        description={`The first ${subscriptions.data?.data.pageSize ?? 50} subscription records by id. Search and filter them on Customers.`}
        actions={
          <Link href={`/founder/customers?mode=${mode}`} className={cn(buttonVariants({ variant: 'glass', size: 'sm' }))}>
            Open Customers
          </Link>
        }
      >
        <QueryState query={subscriptions} label='subscriptions' isEmpty={(result) => result.data.rows.length === 0} emptyTitle='No subscriptions in this source'>
          {(result) => (
            <SimpleTable
              rows={result.data.rows}
              rowKey={(row) => row.id}
              caption={`Subscriptions · ${mode === 'demo' ? 'fictional sample data' : 'Live records'}`}
              onRowClick={(row) => evidence.open({ receiptId: result.receiptIds?.[0] ?? null, record: row })}
              columns={[
                { key: 'workspace', label: 'Workspace', render: (row) => recordLabel(result.data.workspaces.find((workspace) => workspace.id === row.workspaceId) ?? row) },
                { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.plan) },
                { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.status)}</StatusChip> },
                { key: 'amount', label: 'Price', align: 'right', render: (row) => minor(row.amountMinor as number, row.currency as string) },
                { key: 'renews', label: 'Renews', render: (row) => whenDate(row.renewsAt) }
              ]}
            />
          )}
        </QueryState>
      </Panel>
      {evidence.drawer}
    </div>
  );
}

function PaymentsTab({ period }: { period: PeriodKey }) {
  const failures = useMetric({ id: 'payment_failures', period, groupBy: ['payment_type', 'window'] });
  const delinquent = useMetric({ id: 'delinquent_mrr', period, groupBy: ['currency', 'plan'] });
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <PanelGrid>
        <MetricChartCard query={failures} id='payment_failures' title='Payment failures by day' subtitle='Failed subscription payments and top-ups' period={period} unavailableDescription='Payment failure notices and failed top-ups are the source; none were measured.'>
          {(result) => <TimeSeriesChart series={windowSeries(result.rows, 'payment_type')} kind='bar' stacked emptyTitle='No payment failed in this period' />}
        </MetricChartCard>
        <MetricChartCard query={delinquent} id='delinquent_mrr' title='Delinquent MRR by plan' subtitle='Recurring revenue on past-due subscriptions today' period={period} unavailableDescription='Delinquent MRR is the past-due part of MRR, from recorded Stripe billing events.'>
          {(result) => <PerCurrency result={result} render={(currency) => <CategoryBars items={categoryItems(result.rows, 'plan', currency)} unit='currency_minor' currency={currency} emptyTitle='Nothing is past due' />} />}
        </MetricChartCard>
      </PanelGrid>
      <DunningPanel period={period} />
    </div>
  );
}

function RefundsTab({ period }: { period: PeriodKey }) {
  const refunds = useMetric({ id: 'refunds_disputes', period, groupBy: ['currency', 'category', 'status'] });
  return (
    <MetricChartCard query={refunds} id='refunds_disputes' title='Refunds and disputes' subtitle='Amounts by category and status; a refund never changes MRR' period={period} unavailableDescription='Refund and dispute rows come from Stripe webhook ingestion; none were measured.'>
      {(result) => (
        <SimpleTable
          rows={rowsWith(result.rows, ['category', 'status'])}
          rowKey={(row, index) => `${row.currency ?? 'none'}-${row.dimensions?.category}-${row.dimensions?.status}-${index}`}
          caption='Refunds and disputes by category and status'
          emptyTitle='No refund or dispute in this period'
          columns={[
            { key: 'category', label: 'Category', render: (row) => stateLabel(row.dimensions?.category) },
            { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.dimensions?.status)}</StatusChip> },
            { key: 'amount', label: 'Amount', align: 'right', render: (row) => metricValue(row) }
          ]}
        />
      )}
    </MetricChartCard>
  );
}

export function RevenueView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(PERIODS).withDefault('30d'));
  const [tab, setTab] = useTabState('revenue', 'mrr-bridge');
  useFounderPageContext({ section: 'revenue', period, filters: { tab } });

  const mrr = useTileMetric({ id: 'mrr', period, groupBy: ['currency'] });
  const delinquent = useTileMetric({ id: 'delinquent_mrr', period, groupBy: ['currency'] });
  const cashMtd = useTileMetric({ id: 'cash_collected', period: 'mtd', groupBy: ['currency'] });
  const paidCustomers = useTileMetric({ id: 'paid_customers', period });

  return (
    <FounderPage
      eyebrow='Revenue & billing'
      title='Revenue'
      accent='& billing'
      description={`Why recurring revenue moved, what was collected, who is behind on payment and what credits are outstanding.${mode === 'demo' ? ' Demo prices are the candidate v2 catalog (not active).' : ''} Every number comes from a receipt; anything not collected says so.`}
      actions={
        <>
          <PeriodSwitch value={period} onChange={(value) => void setPeriod(value)} options={PERIODS} />
          <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Summarise revenue and billing for this period: MRR and why it moved, cash collected, payment failures and credits. Cite receipts and say what is not measured.', period })}>
            <Icons.sparkles /> Ask Rafii
          </Button>
        </>
      }
    >
      <TileGrid>
        <NotedMetricTile query={mrr} input={{ id: 'mrr', label: 'MRR', period, href: `/founder/revenue?mode=${mode}&tab=mrr-bridge` }} onAsk={() => ask({ prompt: 'What is MRR now, how is it normalized, and what moved it in this period?', chart: 'mrr', period })} />
        <NotedMetricTile query={delinquent} input={{ id: 'delinquent_mrr', label: 'Delinquent MRR', period, href: `/founder/revenue?mode=${mode}&tab=payments` }} onAsk={() => ask({ prompt: 'Which past-due subscriptions make up delinquent MRR, and who should get a reminder?', chart: 'delinquent_mrr', period })} />
        <MetricTileFromQuery query={cashMtd} input={{ id: 'cash_collected', label: 'Cash collected (MTD)', period: 'mtd', href: `/founder/revenue?mode=${mode}&tab=cash` }} onAsk={() => ask({ prompt: 'Explain cash collected month to date versus the same days last month.', chart: 'cash_collected', period: 'mtd' })} />
        <MetricTileFromQuery query={paidCustomers} input={{ id: 'paid_customers', label: 'Paid customers', period, href: `/founder/customers?mode=${mode}` }} onAsk={() => ask({ prompt: 'How did paid customers change in this period, and who joined or left?', chart: 'paid_customers', period })} />
      </TileGrid>

      <Tabs value={tab} onValueChange={(value) => setTab(String(value))}>
        <div className='relative -mx-1 max-w-full overflow-x-auto px-1 pb-1'>
          <TabsList variant='line' className='w-max'>
            {TABS.map((item) => (
              <TabsTrigger key={item.id} value={item.id} className='text-muted-foreground'>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value='mrr-bridge' className='flex min-w-0 flex-col gap-4 pt-4'>
          <MrrBridge period={period} />
          <MrrTrend period={period} />
        </TabsContent>
        <TabsContent value='cash' className='min-w-0 pt-4'>
          <CashTab period={period} />
        </TabsContent>
        <TabsContent value='subscriptions' className='min-w-0 pt-4'>
          <SubscriptionsTab period={period} />
        </TabsContent>
        <TabsContent value='payments' className='min-w-0 pt-4'>
          <PaymentsTab period={period} />
        </TabsContent>
        <TabsContent value='refunds' className='min-w-0 pt-4'>
          <RefundsTab period={period} />
        </TabsContent>
        <TabsContent value='credits' className='min-w-0 pt-4'>
          <CreditsPanels period={period} />
        </TabsContent>
        <TabsContent value='forecast' className='min-w-0 pt-4'>
          <ForecastPanel />
        </TabsContent>
      </Tabs>
    </FounderPage>
  );
}
