'use client';

import Link from 'next/link';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useFounderMode, useMetric, useRecords, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars, TimeSeriesChart } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { metricValue, minor, recordLabel, stateLabel, whenDate } from '../customers/kit/format';
import { categoriesFromRows, seriesFromRows, wholeIntervalRows } from '../customers/kit/metric';
import { FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, PeriodSwitch, QueryState, TileGrid } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { SimpleTable } from '../customers/kit/simple-table';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import type { MetricRow } from '../customers/kit/types';

/**
 * Revenue & billing (PRD §5.3, §7.2): paid customers and cash as tiles, cash by month, the plan × status table,
 * payment failures and refunds / disputes, plus the first page of subscriptions. MRR has no activated definition
 * yet, so its tile says "collecting since" (or "not activated") rather than a number; the MRR bridge is P1.
 * `?tab=` (mrr-bridge · cash · subscriptions · payments · refunds, from founder-nav) lands on the matching panel.
 */
const PERIODS: PeriodKey[] = ['30d', '90d'];

function PlanStatusTable({ rows }: { rows: MetricRow[] }) {
  const whole = wholeIntervalRows(rows).filter((row) => row.dimensions?.plan !== undefined);
  return (
    <SimpleTable
      rows={whole}
      rowKey={(row, index) => `${row.dimensions?.plan}-${row.dimensions?.status}-${index}`}
      caption='Subscriptions by plan and status'
      emptyTitle='No subscription rows measured'
      columns={[
        { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.dimensions?.plan) },
        { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.dimensions?.status)}</StatusChip> },
        { key: 'count', label: 'Subscriptions', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{metricValue(row)}</span> }
      ]}
    />
  );
}

export function RevenueView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const evidence = useEvidenceDrawer();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(PERIODS).withDefault('30d'));
  const tab = useSectionTab('revenue');
  useFounderPageContext({ section: 'revenue', period });

  const paidCustomers = useTileMetric({ id: 'paid_customers', period });
  const paidWorkspaces = useTileMetric({ id: 'paid_workspaces', period });
  const cashMtd = useTileMetric({ id: 'cash_collected', period: 'mtd' });
  const mrr = useTileMetric({ id: 'mrr', period });
  const failuresTile = useTileMetric({ id: 'payment_failures', period });

  const cashByMonth = useMetric({ id: 'cash_collected', period: '6m', groupBy: ['payment_type'] });
  const planStatus = useMetric({ id: 'subscriptions_by_plan_status', period, groupBy: ['plan', 'status'] });
  const failures = useMetric({ id: 'payment_failures', period, groupBy: ['reason'] });
  const refunds = useMetric({ id: 'refunds_disputes', period, groupBy: ['status'] });
  const subscriptions = useRecords({ collection: 'subscriptions', search: '', status: 'all', page: 1, recordId: '' });

  return (
    <FounderPage
      eyebrow='Revenue & billing'
      title='Revenue'
      accent='& billing'
      description='What was collected, which plans people are on, and where payments are failing. Every number comes from a receipt; definitions that are not activated say so.'
      actions={
        <>
          <PeriodSwitch value={period} onChange={(value) => void setPeriod(value)} options={PERIODS} />
          <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Summarise revenue and billing for this period: cash collected, plan mix, payment failures and refunds. Cite receipts and say what is not measured.', period })}>
            <Icons.sparkles /> Ask Rafii
          </Button>
        </>
      }
    >
      <TileGrid>
        <MetricTileFromQuery query={paidCustomers} input={{ id: 'paid_customers', label: 'Paid customers', period, href: `/founder/customers?mode=${mode}` }} onAsk={() => ask({ prompt: 'How did paid customers change in this period, and who joined or left?', chart: 'paid_customers', period })} />
        <MetricTileFromQuery query={paidWorkspaces} input={{ id: 'paid_workspaces', label: 'Paid workspaces', period, href: `/founder/customers?mode=${mode}` }} />
        <MetricTileFromQuery query={cashMtd} input={{ id: 'cash_collected', label: 'Cash collected (MTD)', period: 'mtd' }} onAsk={() => ask({ prompt: 'Explain cash collected month to date versus the same days last month.', chart: 'cash_collected', period: 'mtd' })} />
        <MetricTileFromQuery query={mrr} input={{ id: 'mrr', label: 'MRR', period }} onAsk={() => ask({ prompt: 'Why is MRR not measurable yet, and what would make it so?', chart: 'mrr', period })} />
        <MetricTileFromQuery query={failuresTile} input={{ id: 'payment_failures', label: 'Payment failures', period, href: `/founder/customers?mode=${mode}&view=payment_risk` }} />
      </TileGrid>

      <PanelGrid>
        <TabAnchor section='revenue' tab='cash' active={tab}>
          <MetricChartCard query={cashByMonth} id='cash_collected' title='Cash by month' subtitle='Invoices vs top-ups, six months' period='6m' unavailableDescription='Cash collected is measured from Stripe payment events (054 views); nothing has landed yet.'>
            {(result) => <TimeSeriesChart series={seriesFromRows(result.rows, 'payment_type')} kind='bar' stacked monthly />}
          </MetricChartCard>
        </TabAnchor>
        <MetricChartCard query={planStatus} id='subscriptions_by_plan_status' title='Subscriptions by plan and status' subtitle='Current snapshot by plan × status' period={period} unavailableDescription='The daily subscription snapshot (pr_subscription_snapshots) has not written a day yet.'>
          {(result) => (
            <div className='flex flex-col gap-3'>
              <PlanStatusTable rows={result.rows} />
              <Link href={`/founder/customers?mode=${mode}&view=payment_risk`} className={cn(buttonVariants({ variant: 'glass', size: 'sm' }), 'self-start')}>
                Customers with payment risk <Icons.chevronRight />
              </Link>
            </div>
          )}
        </MetricChartCard>
        <TabAnchor section='revenue' tab='payments' active={tab}>
          <MetricChartCard query={failures} id='payment_failures' title='Payment failures' subtitle='Failed payment notices by reason' period={period} unavailableDescription='Payment failure notices (pr_notifications, kind payment_failed) are the source; none were measured.'>
            {(result) => {
              const series = seriesFromRows(result.rows, 'reason');
              return series.points.length > 0 ? <TimeSeriesChart series={series} kind='bar' stacked /> : <CategoryBars items={categoriesFromRows(result.rows, 'reason')} unit={result.rows[0]?.unit ?? 'count'} />;
            }}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='revenue' tab='refunds' active={tab}>
          <MetricChartCard query={refunds} id='refunds_disputes' title='Refunds and disputes' subtitle='Amounts by status' period={period} unavailableDescription='Refund and dispute rows come from Stripe webhook ingestion (business_refunds / business_disputes); none were measured.'>
            {(result) => (
              <SimpleTable
                rows={wholeIntervalRows(result.rows)}
                rowKey={(row, index) => `${row.dimensions?.status ?? 'all'}-${index}`}
                caption='Refunds and disputes by status'
                emptyTitle='No refund or dispute rows'
                columns={[
                  { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.dimensions?.status ?? 'all')}</StatusChip> },
                  { key: 'amount', label: 'Amount', align: 'right', render: (row) => metricValue(row) }
                ]}
              />
            )}
          </MetricChartCard>
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='revenue' tab='mrr-bridge' active={tab}>
        <Panel title='MRR bridge' description='New · expansion · contraction · churn · reactivation — the only revenue chart that explains why MRR moved.'>
          <StateMessage kind='unsupported' layout='inline' title='The MRR bridge is not activated in this release' description='Its definitions (mrr_new, mrr_expansion, mrr_contraction, mrr_churn, mrr_reactivation) are proposed and need the subscription snapshot history (P1). Nothing is estimated in its place.' />
        </Panel>
      </TabAnchor>

      <TabAnchor section='revenue' tab='subscriptions' active={tab}>
      <Panel title='Subscriptions' description={`The first ${subscriptions.data?.data.pageSize ?? 50} subscription records by id. Search and filter them on Customers.`} actions={<Link href={`/founder/customers?mode=${mode}`} className={cn(buttonVariants({ variant: 'glass', size: 'sm' }))}>Open Customers</Link>}>
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
                { key: 'amount', label: 'Amount', align: 'right', render: (row) => minor(row.amountMinor as number, row.currency as string) },
                { key: 'renews', label: 'Renews', render: (row) => whenDate(row.renewsAt) }
              ]}
            />
          )}
        </QueryState>
      </Panel>
      </TabAnchor>
      {evidence.drawer}
    </FounderPage>
  );
}
