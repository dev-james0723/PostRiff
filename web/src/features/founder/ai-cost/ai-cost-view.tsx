'use client';

import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useFounderMode, useMetric, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars, CoverageBar, TimeSeriesChart } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { metricValue, stateLabel, unitFormatter } from '../customers/kit/format';
import { categoriesFromRows, headlineRow, knownUnknown, seriesFromRows, wholeIntervalRows } from '../customers/kit/metric';
import { FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, PeriodSwitch, TileGrid } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { SimpleTable } from '../customers/kit/simple-table';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import { ReconcileQueue } from './reconcile-queue';

/**
 * AI & API cost (PRD §5.3, §7.2; this round's focus): cost by feature as a stacked area, model and route bars,
 * the known / unknown coverage bar, budget and ops-cost tiles, the reconcile queue and cost by plan. Unknown cost
 * is shown as unknown — never folded into a total — and tokens / latency wait for `pr_ai_call_events` (§8.1).
 */
const PERIODS: PeriodKey[] = ['7d', '30d', 'mtd'];

export function AiCostView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const evidence = useEvidenceDrawer();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(PERIODS).withDefault('30d'));
  const tab = useSectionTab('ai-cost');
  useFounderPageContext({ section: 'ai-cost', period });

  const actual = useTileMetric({ id: 'ai_cost_actual', period });
  const unknown = useTileMetric({ id: 'ai_cost_unknown', period });
  const budget = useTileMetric({ id: 'budget_remaining', period: 'mtd' });
  const opsCost = useTileMetric({ id: 'founder_ops_cost', period });
  const costVsCash = useTileMetric({ id: 'cost_vs_cash', period });

  const byFeature = useMetric({ id: 'ai_cost_by_feature', period, groupBy: ['feature'] });
  const byModel = useMetric({ id: 'ai_cost_actual', period, groupBy: ['model'] });
  const byRoute = useMetric({ id: 'ai_cost_actual', period, groupBy: ['route'] });
  const byPlan = useMetric({ id: 'ai_cost_actual', period, groupBy: ['plan'] });
  const coverage = useMetric({ id: 'ai_cost_actual', period: 'mtd' });

  const coverageRow = headlineRow(coverage.data, 'ai_cost_actual');
  const parts = knownUnknown(coverageRow);
  const money = unitFormatter(coverageRow?.unit ?? 'usd_micro', coverageRow?.currency);

  return (
    <FounderPage
      eyebrow='AI & API cost'
      title='AI'
      accent='& API cost'
      description='Where the money goes, per feature and per model, and how much of it is actually known. Unknown cost stays unknown until it is reconciled.'
      actions={
        <>
          <PeriodSwitch value={period} onChange={(value) => void setPeriod(value)} options={PERIODS} />
          <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Break down AI and API cost for this period by feature and model, flag anomalies against the previous period, and list what is still unknown.', period })}>
            <Icons.sparkles /> Ask Rafii
          </Button>
        </>
      }
    >
      <TabAnchor section='ai-cost' tab='budget' active={tab}>
      <TileGrid>
        <MetricTileFromQuery query={actual} input={{ id: 'ai_cost_actual', label: 'AI cost (recorded)', period }} onAsk={() => ask({ prompt: 'Explain the recorded AI cost for this period and its change versus the previous period.', chart: 'ai_cost_actual', period })} />
        <MetricTileFromQuery query={unknown} input={{ id: 'ai_cost_unknown', label: 'Unknown cost (estimated)', period }} onAsk={() => ask({ prompt: 'Which usage rows still have unknown cost, and what would reconcile them?', chart: 'ai_cost_unknown', period })} />
        <MetricTileFromQuery query={budget} input={{ id: 'budget_remaining', label: 'Budget remaining (month)', period: 'mtd' }} />
        <MetricTileFromQuery query={opsCost} input={{ id: 'founder_ops_cost', label: 'Founder ops cost', period }} onAsk={() => ask({ prompt: 'How much did my own founder tooling (ops workspace, test and demo workspaces) cost this period?', chart: 'founder_ops_cost', period })} />
        <MetricTileFromQuery query={costVsCash} input={{ id: 'cost_vs_cash', label: 'Cost vs cash', period }} onAsk={() => ask({ prompt: 'How does recorded AI cost compare with cash collected this period (gross-margin proxy)?', chart: 'cost_vs_cash', period })} />
      </TileGrid>
      </TabAnchor>

      <TabAnchor section='ai-cost' tab='coverage' active={tab}>
      <Panel title='Coverage' description='Known provider cost versus cost still unknown, month to date. The bar is the server’s two numbers; nothing is estimated here.'>
        {coverage.isPending ? (
          <StateMessage kind='loading' layout='inline' title='Loading coverage…' />
        ) : parts ? (
          <CoverageBar known={parts.known} unknown={parts.unknown} format={money} />
        ) : (
          <StateMessage kind='unsupported' layout='inline' title='Coverage is not reported for this period' description='The adapter has not returned a known / unknown split (coverage on ai_cost_actual). The reconcile queue below lists the rows without a recorded cost.' />
        )}
      </Panel>
      </TabAnchor>

      <PanelGrid>
        <TabAnchor section='ai-cost' tab='by-feature' active={tab}>
          <MetricChartCard query={byFeature} id='ai_cost_by_feature' title='Cost by feature' subtitle='Recorded cost per feature, stacked by bucket' period={period} unavailableDescription='Feature is derived from the ledger idempotency key (business_usage_v2); no measured buckets yet.'>
            {(result) => <TimeSeriesChart series={seriesFromRows(result.rows, 'feature')} kind='area' stacked />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='ai-cost' tab='by-model' active={tab}>
          <MetricChartCard query={byModel} id='ai_cost_actual' title='Cost by model' subtitle='Recorded cost per model' period={period} askPrompt='Which models cost the most this period, and is the primary / fallback mix healthy?'>
            {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'model')} unit={result.rows[0]?.unit ?? 'usd_micro'} currency={result.rows[0]?.currency} />}
          </MetricChartCard>
        </TabAnchor>
        <MetricChartCard query={byRoute} id='ai_cost_actual' title='Cost by route' subtitle='Recorded cost per provider route' period={period} unavailableDescription='Route attribution needs the ledger attribution sidecar (PRD §8.2). Fallback and retry ratios follow with pr_ai_call_events.'>
          {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'route')} unit={result.rows[0]?.unit ?? 'usd_micro'} currency={result.rows[0]?.currency} />}
        </MetricChartCard>
        <TabAnchor section='ai-cost' tab='by-plan' active={tab}>
        <MetricChartCard query={byPlan} id='ai_cost_actual' title='Cost by plan' subtitle='Recorded cost grouped by the paying plan' period={period} askPrompt='Which plans lose money on AI cost, and which customers drive it?'>
          {(result) => (
            <div className='flex flex-col gap-2'>
              <SimpleTable
                rows={wholeIntervalRows(result.rows).filter((row) => row.dimensions?.plan !== undefined)}
                rowKey={(row, index) => `${row.dimensions?.plan}-${index}`}
                caption='Recorded AI cost by plan'
                columns={[
                  { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.dimensions?.plan) },
                  { key: 'cost', label: 'Recorded cost', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{metricValue(row)}</span> },
                  { key: 'state', label: 'State', render: (row) => <StatusChip icon={null}>{stateLabel(row.dataState)}</StatusChip> }
                ]}
              />
              <p className='text-muted-foreground text-xs'>Per-customer cost needs a workspace dimension on the ledger rollup (P1); until then open a customer’s Usage tab.</p>
            </div>
          )}
        </MetricChartCard>
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='ai-cost' tab='reconcile' active={tab}>
      <Panel title='Reconcile queue' description='Usage rows whose provider cost is still unknown. Reconciling writes an audit entry and needs a step-up (P1).'>
        <ReconcileQueue onEvidence={evidence.open} />
      </Panel>
      </TabAnchor>

      <PanelGrid>
        <Panel title='Tokens' description='Input · cached · output per bucket.'>
          <StateMessage kind='unsupported' layout='inline' title='Token counts are not collected yet' description='They arrive with pr_ai_call_events (one row per provider attempt, PRD §8.1).' />
        </Panel>
        <Panel title='Latency' description='p50 / p95 per route, never averaged.'>
          <StateMessage kind='unsupported' layout='inline' title='Latency is not collected yet' description='Same source as tokens (pr_ai_call_events). No percentile is estimated from the ledger.' />
        </Panel>
      </PanelGrid>
      <p className='text-muted-foreground text-xs'>Mode: {mode === 'demo' ? 'Demo dataset (synthetic, same metric ids)' : 'Live ledger'}.</p>
      {evidence.drawer}
    </FounderPage>
  );
}
