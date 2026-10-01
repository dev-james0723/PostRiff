'use client';

import type { ReactNode } from 'react';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { failureOf, useFounderMode, useMetric, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars, CoverageBar, TimeSeriesChart } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { count, ratio, stateLabel, usdMicro, whenDate } from '../customers/kit/format';
import { collectingSince, headlineRow, lastGoodAt } from '../customers/kit/metric';
import { CollectingNote, FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, PeriodSwitch, RetryAction, TileGrid } from '../customers/kit/page-frame';
import { PERIOD_LABEL, type PeriodKey } from '../customers/kit/period';
import { ChartCard } from '../customers/kit/shared';
import { SimpleTable } from '../customers/kit/simple-table';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import type { MetricResult } from '../customers/kit/types';
import {
  attemptCoverage,
  categoryItems,
  forecastHeadline,
  forecastView,
  latencySeries,
  latencyTable,
  ledgerCoverage,
  modelRoutes,
  outcomeTable,
  overall,
  smallSampleDays,
  tokenSeries,
  wholeRows,
  windowSeries,
  type LatencyRow,
  type ModelRoute,
  type OutcomeRow
} from './adapters';
import { ForecastChart } from './forecast-chart';
import { ReconcileQueue } from './reconcile-queue';

/**
 * AI & API cost (PRD §5.3, §7.2; CONTRACTS §8.B): cost by feature, model, provider and plan from the canonical ledger;
 * provider attempts from `pr_ai_call_events` — tokens by type, latency p50 / p95 (never averaged; small samples say n),
 * primary vs fallback and the retry share per model, cost per attempt; cost per useful outcome (its proxy named); the
 * month-end forecast (a scenario, dashed, beside the budget); the coverage of known / estimated / unknown cost; and the
 * reconcile queue. Every number is a server row with its receipt; anything not collected says so, never 0.
 */
const PERIODS: PeriodKey[] = ['7d', '30d', 'mtd'];

type Query = { data?: MetricResult; error: unknown; isPending: boolean; refetch: () => unknown };

function receiptsOf(...queries: Query[]): string[] {
  return queries.map((query) => query.data?.queryReceiptId).filter((id): id is string => typeof id === 'string' && id.length > 0);
}

/** A failed query in the shared grammar: permission or error, with a retry. */
function QueryFailure({ query, label, layout = 'panel' }: { query: Query; label: string; layout?: 'panel' | 'inline' }) {
  const failure = failureOf(query.error);
  return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} layout={layout} title={`Couldn't load ${label}`} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
}

/** "October 2026" for a local `YYYY-MM-DD` month start (a label only). */
function monthName(day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? day : new Intl.DateTimeFormat('en', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date);
}

/** Loading / error / not-collected grammar for cards that join several queries; `children` runs once all answered. */
function JoinedBody({ queries, label, notCollected, title, description, children }: { queries: Query[]; label: string; notCollected: boolean; title: string; description: ReactNode; children: ReactNode }) {
  if (queries.some((query) => query.isPending)) return <StateMessage kind='loading' title={`Loading ${label}…`} />;
  const failed = queries.find((query) => query.error);
  if (failed) return <QueryFailure query={failed} label={label} />;
  if (notCollected) {
    const first = queries[0].data?.rows[0];
    return (
      <StateMessage
        kind='unsupported'
        title={title}
        description={
          <>
            {description} <CollectingNote dataState='unavailable' collectingSince={collectingSince(first)} lastGoodAt={lastGoodAt(first)} reason={first?.reason ?? null} className='mt-1 inline' />
          </>
        }
      />
    );
  }
  return <>{children}</>;
}

function Muted({ children }: { children: ReactNode }) {
  return <span className='text-muted-foreground italic'>{children}</span>;
}

function valueOr(value: number | null, format: (value: number) => string): ReactNode {
  return value === null ? <Muted>Unavailable</Muted> : format(value);
}

function milliseconds(value: number): string {
  return `${count(Math.round(value))} ms`;
}

export function AiCostView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const evidence = useEvidenceDrawer();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(PERIODS).withDefault('30d'));
  const tab = useSectionTab('ai-cost');
  useFounderPageContext({ section: 'ai-cost', period, ...(tab ? { filters: { tab } } : {}) });

  // Budget tiles (each with its comparison window).
  const actual = useTileMetric({ id: 'ai_cost_actual', period });
  const unknown = useTileMetric({ id: 'ai_cost_unknown', period });
  const budget = useTileMetric({ id: 'budget_remaining', period: 'mtd' });
  const opsCost = useTileMetric({ id: 'founder_ops_cost', period });
  const costVsCash = useTileMetric({ id: 'cost_vs_cash', period });
  const attempts = useTileMetric({ id: 'ai_calls', period });
  const perAttempt = useTileMetric({ id: 'ai_cost_per_call', period });

  // Coverage (month to date): ledger cost and attempt cost provenance.
  const ledgerMtd = useMetric({ id: 'ai_cost_actual', period: 'mtd' });
  const basisMtd = useMetric({ id: 'ai_calls', period: 'mtd', groupBy: ['cost_basis'] });

  // Ledger breakdowns.
  const byFeature = useMetric({ id: 'ai_cost_by_feature', period, groupBy: ['window', 'feature'] });
  const byModel = useMetric({ id: 'ai_cost_actual', period, groupBy: ['model'] });
  const byProvider = useMetric({ id: 'ai_cost_actual', period, groupBy: ['provider'] });
  const byPlan = useMetric({ id: 'ai_cost_actual', period, groupBy: ['plan'] });

  // Provider attempts.
  const callsByRoute = useMetric({ id: 'ai_calls', period, groupBy: ['model', 'route'] });
  const ratesByModel = useMetric({ id: 'ai_fallback_retry_rate', period, groupBy: ['model'] });
  const costByModel = useMetric({ id: 'ai_cost_per_call', period, groupBy: ['model'] });
  const tokens = useMetric({ id: 'ai_tokens', period, groupBy: ['window', 'token_type'] });
  const latencyDaily = useMetric({ id: 'ai_latency', period, groupBy: ['window'] });
  const latencyByModel = useMetric({ id: 'ai_latency', period, groupBy: ['model'] });

  // P2: cost per useful outcome and the month-end scenario (always the current month).
  const outcomeByProxy = useMetric({ id: 'cost_per_useful_outcome', period, groupBy: ['outcome_proxy'] });
  const outcomeByPlan = useMetric({ id: 'cost_per_useful_outcome', period, groupBy: ['plan'] });
  const forecastDaily = useMetric({ id: 'ai_cost_forecast', period: 'mtd', groupBy: ['window'] });
  const forecastTotal = useMetric({ id: 'ai_cost_forecast', period: 'mtd' });

  const ledgerParts = ledgerCoverage(headlineRow(ledgerMtd.data, 'ai_cost_actual'));
  const attemptParts = attemptCoverage(basisMtd.data?.rows ?? []);
  const routes = modelRoutes(callsByRoute.data?.rows ?? [], ratesByModel.data?.rows ?? [], costByModel.data?.rows ?? []);
  const routeRows = [...(ratesByModel.data?.rows ?? []), ...(callsByRoute.data?.rows ?? [])];
  const headline = forecastHeadline(headlineRow(forecastTotal.data, 'ai_cost_forecast'));
  const view = forecastView(forecastDaily.data?.rows ?? []);
  const periodLabel = PERIOD_LABEL[period];

  return (
    <FounderPage
      eyebrow='AI & API cost'
      title='AI'
      accent='& API cost'
      description='Where the money goes — per feature, model, plan and provider attempt — what a useful result costs, and how much of it is actually known. Unknown cost stays unknown until it is reconciled.'
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
          <MetricTileFromQuery query={attempts} input={{ id: 'ai_calls', label: 'Provider attempts', period }} onAsk={() => ask({ prompt: 'How many provider attempts did we make this period, how many failed or were rate limited, and which features made them?', chart: 'ai_calls', period })} />
          <MetricTileFromQuery query={perAttempt} input={{ id: 'ai_cost_per_call', label: 'Cost per attempt', period }} onAsk={() => ask({ prompt: 'What does one provider attempt cost on average this period, and which models are the most expensive per attempt?', chart: 'ai_cost_per_call', period })} />
        </TileGrid>
      </TabAnchor>

      <TabAnchor section='ai-cost' tab='coverage' active={tab}>
        <ChartCard
          title='Coverage'
          subtitle='Month to date: cost that is known, estimated from a price table, or still unknown. The bars are the server’s numbers; nothing is estimated here.'
          period={PERIOD_LABEL.mtd}
          receiptIds={receiptsOf(ledgerMtd, basisMtd)}
          dataState={ledgerMtd.data ? ledgerMtd.data.dataState : undefined}
          asOf={ledgerMtd.data?.asOf ?? null}
          definitionId='ai_cost_actual'
          onAsk={() => ask({ prompt: 'How much of this month’s AI cost is known, estimated from price tables or still unknown, and what would close the gap?', chart: 'ai_cost_actual', period: 'mtd' })}
        >
          <div className='flex flex-col gap-5'>
            <div className='flex flex-col gap-2'>
              <h3 className='text-foreground text-sm font-medium'>Ledger cost</h3>
              <p className='text-muted-foreground text-xs'>Settled cost beside the estimate still held for usage whose provider cost is unknown.</p>
              {ledgerMtd.isPending ? (
                <StateMessage kind='loading' layout='inline' title='Loading ledger coverage…' />
              ) : ledgerMtd.error ? (
                <QueryFailure query={ledgerMtd} label='ledger coverage' layout='inline' />
              ) : ledgerParts ? (
                <CoverageBar known={ledgerParts.known} unknown={ledgerParts.unknown} format={usdMicro} />
              ) : (
                <StateMessage kind='unsupported' layout='inline' title='Ledger coverage is not reported for this month' description='The ledger has not returned a settled amount with its unknown estimate (ai_cost_actual).' />
              )}
            </div>
            <div className='flex flex-col gap-2'>
              <h3 className='text-foreground text-sm font-medium'>Provider attempts</h3>
              <p className='text-muted-foreground text-xs'>Attempts whose cost the provider reported (known), that a versioned price table priced when they were recorded (estimated), or that have no cost yet (unknown).</p>
              {basisMtd.isPending ? (
                <StateMessage kind='loading' layout='inline' title='Loading attempt coverage…' />
              ) : basisMtd.error ? (
                <QueryFailure query={basisMtd} label='attempt coverage' layout='inline' />
              ) : attemptParts ? (
                <CoverageBar known={attemptParts.known} estimated={attemptParts.estimated} unknown={attemptParts.unknown} format={(value) => `${count(value)} attempts`} />
              ) : (
                <StateMessage
                  kind='unsupported'
                  layout='inline'
                  title='Attempt costs are not collected yet'
                  description={<CollectingNote dataState='unavailable' collectingSince={collectingSince(basisMtd.data?.rows[0])} reason={basisMtd.data?.rows[0]?.reason ?? null} className='inline' />}
                />
              )}
            </div>
            <p className='text-muted-foreground text-xs'>Unknown rows are settled from the reconcile queue below, with the provider’s own cost and a reference.</p>
          </div>
        </ChartCard>
      </TabAnchor>

      <PanelGrid>
        <TabAnchor section='ai-cost' tab='by-feature' active={tab}>
          <MetricChartCard query={byFeature} id='ai_cost_by_feature' title='Cost by feature' subtitle='Recorded cost per feature per day, stacked' period={period} unavailableDescription='Feature is derived from the ledger idempotency key (business_usage_v2); no measured day yet.'>
            {(result) => <TimeSeriesChart series={windowSeries(result.rows, { dimension: 'feature' })} kind='area' stacked />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='ai-cost' tab='by-plan' active={tab}>
          <MetricChartCard query={byPlan} id='ai_cost_actual' title='Cost by plan' subtitle='Recorded cost grouped by the paying plan' period={period} askPrompt='Which plans lose money on AI cost, and which customers drive it?'>
            {(result) => (
              <SimpleTable
                rows={wholeRows(result.rows).filter((row) => row.dimensions?.plan !== undefined)}
                rowKey={(row, index) => `${row.dimensions?.plan}-${index}`}
                caption='Recorded AI cost by plan'
                emptyTitle='No plan has recorded cost in this period'
                columns={[
                  { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.dimensions?.plan) },
                  { key: 'cost', label: 'Recorded cost', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{row.dataState === 'unavailable' || row.value === null ? 'Unavailable' : usdMicro(row.value)}</span> },
                  { key: 'state', label: 'State', render: (row) => <StatusChip icon={null}>{stateLabel(row.dataState)}</StatusChip> }
                ]}
              />
            )}
          </MetricChartCard>
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='ai-cost' tab='by-model' active={tab}>
        <div className='flex min-w-0 flex-col gap-4'>
          <PanelGrid>
            <MetricChartCard query={byModel} id='ai_cost_actual' title='Cost by model' subtitle='Recorded cost per model' period={period} askPrompt='Which models cost the most this period, and is the primary / fallback mix healthy?'>
              {(result) => <CategoryBars items={categoryItems(result.rows, 'model')} unit='usd_micro' currency='USD' />}
            </MetricChartCard>
            <MetricChartCard query={byProvider} id='ai_cost_actual' title='Cost by provider' subtitle='Recorded cost per provider account' period={period} unavailableDescription='Provider attribution comes from the usage ledger; no settled cost was measured in this period.'>
              {(result) => <CategoryBars items={categoryItems(result.rows, 'provider')} unit='usd_micro' currency='USD' />}
            </MetricChartCard>
          </PanelGrid>
          <ChartCard
            title='Routes per model'
            subtitle='Primary and fallback attempts, the share that was a retry or a fallback, and the recorded cost per attempt.'
            period={periodLabel}
            receiptIds={receiptsOf(ratesByModel, callsByRoute, costByModel)}
            dataState={ratesByModel.data ? overall(ratesByModel.data.rows) : undefined}
            asOf={ratesByModel.data?.asOf ?? null}
            definitionId='ai_fallback_retry_rate'
            onAsk={() => ask({ prompt: 'Which models needed fallbacks or retries this period, how often, and what does an attempt cost on each?', chart: 'ai_fallback_retry_rate', period })}
          >
            <JoinedBody
              queries={[ratesByModel, callsByRoute, costByModel]}
              label='model routes'
              notCollected={routes.length === 0 || overall(routeRows) === 'unavailable'}
              title='Provider attempts are not collected yet'
              description='Each provider attempt (retries and fallbacks included) is recorded as one row once migration 058 is applied; nothing is estimated from the ledger.'
            >
              <SimpleTable<ModelRoute>
                rows={routes}
                rowKey={(row) => row.model}
                caption='Provider attempts per model: primary and fallback routes, retries and cost per attempt'
                columns={[
                  { key: 'model', label: 'Model', render: (row) => <span className='font-mono text-xs'>{row.model}</span> },
                  { key: 'attempts', label: 'Attempts', align: 'right', render: (row) => valueOr(row.attempts, count) },
                  { key: 'primary', label: 'Primary', align: 'right', render: (row) => (row.primary === null && row.noPrimary ? <Muted>None</Muted> : valueOr(row.primary, count)) },
                  { key: 'fallback', label: 'Fallback', align: 'right', render: (row) => valueOr(row.fallback, count) },
                  { key: 'retries', label: 'Retries', align: 'right', render: (row) => valueOr(row.retries, count) },
                  { key: 'share', label: 'Retry or fallback share', align: 'right', render: (row) => valueOr(row.retryShare, ratio) },
                  { key: 'cost', label: 'Cost per attempt', align: 'right', render: (row) => valueOr(row.costPerAttempt, usdMicro) },
                  { key: 'state', label: 'State', render: (row) => <StatusChip icon={null}>{stateLabel(row.dataState)}</StatusChip> }
                ]}
              />
              <p className='text-muted-foreground mt-2 text-xs'>The share is the server’s ratio of attempts that ran on a fallback route or were a retry (attempt number above 1) to all attempts on the model. Retries inside a provider SDK are not visible.</p>
            </JoinedBody>
          </ChartCard>
        </div>
      </TabAnchor>

      <TabAnchor section='ai-cost' tab='reconcile' active={tab}>
        <Panel title='Reconcile queue' description='Usage rows whose provider cost is still unknown. Reconciling records the provider’s own cost with a reference, needs the usage.reconcile capability and a fresh second factor, and writes an audit entry.'>
          <ReconcileQueue onEvidence={evidence.open} />
        </Panel>
      </TabAnchor>

      <PanelGrid>
        <TabAnchor section='ai-cost' tab='tokens' active={tab}>
          <MetricChartCard query={tokens} id='ai_tokens' title='Tokens' subtitle='Input, cached input, output and reasoning per day (text attempts)' period={period} askPrompt='How are our tokens split between input, cached input, output and reasoning, and where could caching save cost?' unavailableDescription='Token counts arrive with pr_ai_call_events (one row per provider attempt, PRD §8.1).'>
            {(result) => (
              <div className='flex flex-col gap-2'>
                <TimeSeriesChart series={tokenSeries(result.rows)} kind='bar' stacked />
                <p className='text-muted-foreground text-xs'>Input counts tokens not served from cache (all input when a provider did not report cached tokens); output excludes reasoning. A type a provider did not report is left out, never counted as zero.</p>
              </div>
            )}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='ai-cost' tab='latency' active={tab}>
          <div className='flex min-w-0 flex-col gap-4'>
            <MetricChartCard query={latencyDaily} id='ai_latency' title='Latency' subtitle='p50 and p95 per day, from that day’s attempts' period={period} askPrompt='Is AI latency getting worse, and which models or features are slow at p95?' unavailableDescription='Latency arrives with pr_ai_call_events. No percentile is estimated from the ledger.'>
              {(result) => {
                const small = smallSampleDays(result.rows);
                return (
                  <div className='flex flex-col gap-2'>
                    <TimeSeriesChart series={latencySeries(result.rows)} kind='line' />
                    <p className='text-muted-foreground text-xs'>Each day’s percentiles come from that day alone; days are never averaged together.{small.length > 0 ? ` Fewer than 30 attempts (small samples): ${small.map((day) => whenDate(`${day}T12:00:00Z`)).join(', ')}.` : ''}</p>
                  </div>
                );
              }}
            </MetricChartCard>
            <MetricChartCard query={latencyByModel} id='ai_latency' title='Latency by model' subtitle='p50 and p95 per model over the period, with the number of attempts behind them' period={period} unavailableDescription='Latency arrives with pr_ai_call_events.'>
              {(result) => (
                <SimpleTable<LatencyRow>
                  rows={latencyTable(result.rows, 'model')}
                  rowKey={(row) => row.key}
                  caption='Latency percentiles per model'
                  emptyTitle='No attempts with a latency in this period'
                  columns={[
                    { key: 'model', label: 'Model', render: (row) => <span className='font-mono text-xs'>{row.label}</span> },
                    { key: 'p50', label: 'p50', align: 'right', render: (row) => valueOr(row.p50, milliseconds) },
                    { key: 'p95', label: 'p95', align: 'right', render: (row) => valueOr(row.p95, milliseconds) },
                    { key: 'n', label: 'Attempts (n)', align: 'right', render: (row) => valueOr(row.n, count) },
                    { key: 'sample', label: 'Sample', render: (row) => (row.small ? <StatusChip status='warning'>Small (n under 30)</StatusChip> : <StatusChip icon={null}>{stateLabel(row.dataState)}</StatusChip>) }
                  ]}
                />
              )}
            </MetricChartCard>
          </div>
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='ai-cost' tab='per-outcome' active={tab}>
        <ChartCard
          title='Cost per useful outcome'
          subtitle='Canonical AI cost of the period (failed and cancelled work included) divided by the useful outcomes of the same workspaces, per outcome proxy.'
          period={periodLabel}
          receiptIds={receiptsOf(outcomeByProxy, outcomeByPlan)}
          dataState={outcomeByProxy.data ? overall(outcomeByProxy.data.rows) : undefined}
          asOf={outcomeByProxy.data?.asOf ?? null}
          definitionId='cost_per_useful_outcome'
          onAsk={() => ask({ prompt: 'What does one useful outcome cost us this period, how does that differ by plan, and how reliable is the outcome proxy?', chart: 'cost_per_useful_outcome', period })}
        >
          <JoinedBody
            queries={[outcomeByProxy, outcomeByPlan]}
            label='cost per useful outcome'
            notCollected={overall(outcomeByProxy.data?.rows ?? []) === 'unavailable'}
            title='Cost per useful outcome is not available'
            description='It needs settled ledger cost and an outcome proxy (Time Back accepted outcomes, or learning approvals and publishes) for the same workspaces.'
          >
            <div className='flex flex-col gap-4'>
              <OutcomeTableView rows={outcomeTable(outcomeByProxy.data?.rows ?? [])} caption='Cost per useful outcome by outcome proxy' first='proxy' />
              <div className='flex flex-col gap-2'>
                <h3 className='text-foreground text-sm font-medium'>By plan ({outcomeTable(outcomeByPlan.data?.rows ?? [])[0]?.proxy ?? 'Time Back accepted outcomes'})</h3>
                <OutcomeTableView rows={outcomeTable(outcomeByPlan.data?.rows ?? [])} caption='Cost per useful outcome by plan' first='plan' />
              </div>
              <p className='text-muted-foreground text-xs'>A proxy, not a usefulness rating: cost and outcomes are matched by period and workspace, not by task. A period with no outcomes is not applicable rather than zero.</p>
            </div>
          </JoinedBody>
        </ChartCard>
      </TabAnchor>

      <TabAnchor section='ai-cost' tab='forecast' active={tab}>
        <ChartCard
          title='Budget vs forecast'
          subtitle='This month’s cumulative AI cost: actual days solid, the scenario projection dashed, the monthly budget as a line.'
          period={PERIOD_LABEL.mtd}
          receiptIds={receiptsOf(forecastTotal, forecastDaily)}
          dataState={forecastTotal.data ? forecastTotal.data.dataState : undefined}
          asOf={forecastTotal.data?.asOf ?? null}
          definitionId='ai_cost_forecast'
          onAsk={() => ask({ prompt: 'Where will AI cost land at the end of this month on the current trend, how does that compare with the budget, and what is driving the slope?', chart: 'ai_cost_forecast', period: 'mtd' })}
        >
          {forecastTotal.isPending || forecastDaily.isPending ? (
            <StateMessage kind='loading' title='Loading the forecast…' />
          ) : forecastTotal.error || forecastDaily.error ? (
            <QueryFailure query={forecastTotal.error ? forecastTotal : forecastDaily} label='the forecast' />
          ) : !headline || headline.total === null ? (
            <StateMessage
              kind='unsupported'
              title={headline?.insufficient ? 'Not enough history for a forecast yet' : 'The forecast is not available'}
              description={
                headline?.insufficient && headline.history
                  ? `The scenario needs ${count(headline.history.requiredDays)} complete days of daily cost; ${count(headline.history.availableDays)} ${headline.history.availableDays === 1 ? 'is' : 'are'} recorded.`
                  : <CollectingNote dataState='unavailable' collectingSince={null} reason={headline?.reason ?? null} className='inline' />
              }
            />
          ) : (
            <div className='flex flex-col gap-4'>
              <dl className='grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4'>
                <Figure label='Month to date (actual)' value={valueOr(headline.mtd, usdMicro)} />
                <Figure label='Projected month end' value={valueOr(headline.total, usdMicro)} note='Scenario' />
                <Figure label='Monthly budget (stop)' value={headline.budget.stop === null ? <Muted>No monthly budget</Muted> : usdMicro(headline.budget.stop)} note={headline.budget.status ? stateLabel(headline.budget.status) : undefined} />
                <Figure label='Trend per day' value={valueOr(headline.slope, usdMicro)} note='Line slope' />
              </dl>
              {view ? <ForecastChart view={view} /> : <StateMessage kind='empty' layout='inline' title='No daily points to draw' />}
              <p className='text-muted-foreground text-xs'>
                Scenario, not a measurement: an ordinary least-squares line through the {headline.history ? count(headline.history.requiredDays) : '56'} complete days before today, extrapolated over the rest of
                {headline.monthStart ? ` ${monthName(headline.monthStart)}` : ' the month'}. It ignores launches, price changes and seasonality.
              </p>
            </div>
          )}
        </ChartCard>
      </TabAnchor>

      <p className='text-muted-foreground text-xs'>Mode: {mode === 'demo' ? 'Demo dataset (synthetic, same metric ids; provider attempts are not simulated)' : 'Live ledger and provider attempts'}.</p>
      {evidence.drawer}
    </FounderPage>
  );
}

function Figure({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className='rafii-quiet flex min-w-0 flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3'>
      <dt className='text-muted-foreground text-xs'>{label}</dt>
      <dd className='text-foreground text-base font-medium tabular-nums break-words'>{value}</dd>
      {note && <dd className='text-muted-foreground text-xs'>{note}</dd>}
    </div>
  );
}

function OutcomeTableView({ rows, caption, first }: { rows: OutcomeRow[]; caption: string; first: 'proxy' | 'plan' }) {
  return (
    <SimpleTable<OutcomeRow>
      rows={rows}
      rowKey={(row) => row.key}
      caption={caption}
      emptyTitle='No outcomes or cost in this period'
      columns={[
        first === 'proxy' ? { key: 'proxy', label: 'Outcome proxy', render: (row) => row.proxy } : { key: 'plan', label: 'Plan', render: (row) => stateLabel(row.plan) },
        { key: 'cost', label: 'AI cost', align: 'right', render: (row) => valueOr(row.cost, usdMicro) },
        { key: 'outcomes', label: 'Useful outcomes', align: 'right', render: (row) => valueOr(row.outcomes, count) },
        { key: 'per', label: 'Cost per outcome', align: 'right', render: (row) => valueOr(row.perOutcome, usdMicro) },
        { key: 'state', label: 'State', render: (row) => <StatusChip icon={null}>{row.reason === 'zero_denominator' ? 'No outcomes' : stateLabel(row.dataState)}</StatusChip> }
      ]}
    />
  );
}
