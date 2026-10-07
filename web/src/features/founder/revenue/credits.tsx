'use client';

import { cn } from '@/lib/utils';
import { useMetric } from '../customers/kit/api';
import { CategoryBars } from '../customers/kit/charts';
import { count, metricValue, stateLabel } from '../customers/kit/format';
import { MetricChartCard, PanelGrid } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { SimpleTable } from '../customers/kit/simple-table';
import { categoryItems, rowsWith } from './rows';

/**
 * Credits (PRD §7.1 M09): grants by source, consumption by task type and the wallet's available balance by plan, all
 * from the credit ledger. While credits are switched off the ledger has no credit rows, so each card says
 * "not collected" instead of drawing zeros. Credits are a liability, not revenue.
 */

const OFF = 'Credits are switched off in this environment (no credit entries in the usage ledger), so there is nothing to show yet.';

export function CreditsPanels({ period }: { period: PeriodKey }) {
  const grants = useMetric({ id: 'credit_grants', period, groupBy: ['grant_source'] });
  const consumption = useMetric({ id: 'credit_consumption', period, groupBy: ['task_type'] });
  const available = useMetric({ id: 'credit_available', period, groupBy: ['plan'] });
  return (
    <PanelGrid>
      <MetricChartCard query={grants} id='credit_grants' title='Credits granted' subtitle='By source: subscription, purchase, goodwill' period={period} unavailableDescription={OFF}>
        {(result) => <CategoryBars items={categoryItems(result.rows, 'grant_source')} unit='millicredits' />}
      </MetricChartCard>
      <MetricChartCard query={consumption} id='credit_consumption' title='Credits consumed' subtitle='Settled tasks by type; a reservation is not consumption' period={period} unavailableDescription={OFF}>
        {(result) => <CategoryBars items={categoryItems(result.rows, 'task_type')} unit='millicredits' />}
      </MetricChartCard>
      <MetricChartCard query={available} id='credit_available' title='Credits available' subtitle='Wallet balance by plan after holds, expiry and debt' period={period} unavailableDescription={OFF}>
        {(result) => (
          <SimpleTable
            rows={rowsWith(result.rows, ['plan'])}
            rowKey={(row, index) => `${row.dimensions?.plan ?? 'none'}-${index}`}
            caption='Available credits by plan'
            emptyTitle='No wallet has credits'
            columns={[
              { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.dimensions?.plan) },
              { key: 'available', label: 'Available', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{metricValue(row)}</span> },
              { key: 'held', label: 'Held', align: 'right', render: (row) => metricValue({ value: (row.measures as { heldMilliCredits?: number } | undefined)?.heldMilliCredits ?? null, unit: 'millicredits', dataState: row.dataState }) },
              { key: 'workspaces', label: 'Workspaces', align: 'right', render: (row) => count(row.coverage?.known ?? null) }
            ]}
          />
        )}
      </MetricChartCard>
    </PanelGrid>
  );
}
