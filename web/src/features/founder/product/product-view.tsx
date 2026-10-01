'use client';

import Link from 'next/link';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useFounderMode, useMetric, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars, TimeSeriesChart } from '../customers/kit/charts';
import { categoriesFromRows, collectingSince, isMeasured, seriesFromRows } from '../customers/kit/metric';
import { FounderPage, MetricChartCard, MetricTileFromQuery, NotInstrumented, Panel, PanelGrid, PeriodSwitch, TileGrid } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import type { MetricResult } from '../customers/kit/types';

/**
 * Product (PRD §5.3, §7.2): active workspaces, publish outcomes and time back from measured sources; activation,
 * retention and feature adoption are shown as "not instrumented" until the journey events exist (§8.6). An
 * unavailable panel never shows a placeholder funnel or heatmap.
 */
const PERIODS: PeriodKey[] = ['30d', '90d'];

/** A proposed definition's state in words: measured rows render; anything else explains itself. */
function Proposed({ query, title, description, children }: { query: { data?: MetricResult; isPending: boolean }; title: string; description: string; children: (result: MetricResult) => React.ReactNode }) {
  if (query.isPending) return <StateMessage kind='loading' title={`Checking ${title.toLowerCase()}…`} />;
  const result = query.data;
  if (!result || !result.rows.some(isMeasured)) return <NotInstrumented title={`${title} is not instrumented yet`} description={description} since={collectingSince(result?.rows[0])} />;
  return <>{children(result)}</>;
}

export function ProductView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(PERIODS).withDefault('30d'));
  const tab = useSectionTab('product');
  useFounderPageContext({ section: 'product', period });

  const activeTile = useTileMetric({ id: 'active_workspaces', period });
  const publishTile = useTileMetric({ id: 'publish_outcomes', period, filters: [{ dimension: 'status', operator: 'eq', values: ['verified'] }] });
  const timeBackTile = useTileMetric({ id: 'time_back', period });

  const activeSeries = useMetric({ id: 'active_workspaces', period });
  const publishByStatus = useMetric({ id: 'publish_outcomes', period, groupBy: ['status'] });
  const timeBack = useMetric({ id: 'time_back', period });
  const activation = useMetric({ id: 'activation_rate', period: '12w' });
  const retention = useMetric({ id: 'retention_d28', period: '12w' });
  const adoption = useMetric({ id: 'feature_adoption', period, groupBy: ['feature'] });

  return (
    <FounderPage
      eyebrow='Product'
      title='Product'
      description='Who is using Rafii, whether publishing lands, and how much time it gives back. Journey metrics appear only once their events are collected.'
      actions={
        <>
          <PeriodSwitch value={period} onChange={(value) => void setPeriod(value)} options={PERIODS} />
          <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Are customers getting value? Use active workspaces, publish outcomes and time back for this period, and say what is not measured.', period })}>
            <Icons.sparkles /> Ask Rafii
          </Button>
        </>
      }
    >
      <TileGrid>
        <MetricTileFromQuery query={activeTile} input={{ id: 'active_workspaces', label: 'Active workspaces', period, href: `/founder/customers?mode=${mode}` }} onAsk={() => ask({ prompt: 'Which workspaces became active or inactive in this period?', chart: 'active_workspaces', period })} />
        <MetricTileFromQuery query={publishTile} input={{ id: 'publish_outcomes', label: 'Verified publications', period, href: `/founder/operations?mode=${mode}` }} />
        <MetricTileFromQuery query={timeBackTile} input={{ id: 'time_back', label: 'Time back', period }} onAsk={() => ask({ prompt: 'How is time back estimated, and how much of it is measured versus reported?', chart: 'time_back', period })} />
      </TileGrid>

      <PanelGrid>
        <TabAnchor section='product' tab='active' active={tab}>
          <MetricChartCard query={activeSeries} id='active_workspaces' title='Active workspaces' subtitle='Workspaces with a run, event or publish in the bucket' period={period} unavailableDescription='Active workspaces are counted from agent runs, product events and publish events (054 views).'>
            {(result) => <TimeSeriesChart series={seriesFromRows(result.rows)} kind='line' />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='product' tab='publishing' active={tab}>
          <MetricChartCard query={publishByStatus} id='publish_outcomes' title='Publish outcomes' subtitle='Verified · failed · pending, by bucket' period={period} unavailableDescription='Publish outcomes come from the publishing jobs; none were measured in this period.'>
            {(result) => <TimeSeriesChart series={seriesFromRows(result.rows, 'status')} kind='bar' stacked />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='product' tab='time-back' active={tab}>
          <MetricChartCard query={timeBack} id='time_back' title='Time back' subtitle='Estimated seconds saved on completed work' period={period} unavailableDescription='Time back rows (business_time_savings) have not been measured yet. The measured / reported / estimated split follows once the confidence dimension is served.'>
            {(result) => <TimeSeriesChart series={seriesFromRows(result.rows, result.rows.some((row) => row.dimensions?.state) ? 'state' : undefined)} kind='area' stacked />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='product' tab='features' active={tab}>
          <Panel title='Feature adoption' description='Share of eligible active workspaces using each feature.'>
            <Proposed query={adoption} title='Feature adoption' description='Needs the product event taxonomy (pr_product_events, PRD §8.6) with an eligible denominator per feature.'>
              {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'feature')} unit={result.rows[0]?.unit ?? 'ratio'} />}
            </Proposed>
          </Panel>
        </TabAnchor>
      </PanelGrid>

      <PanelGrid>
        <TabAnchor section='product' tab='activation' active={tab}>
          <Panel title='Activation funnel' description='Signup → channel → voice/brand → first draft → approve → publish verified, with median time to value.'>
            <Proposed query={activation} title='Activation' description='The funnel needs journey events for each step (PRD §8.6). No funnel is drawn from partial steps.'>
              {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'cohort')} unit={result.rows[0]?.unit ?? 'ratio'} />}
            </Proposed>
          </Panel>
        </TabAnchor>
        <TabAnchor section='product' tab='retention' active={tab}>
          <Panel title='Retention' description='Weekly cohorts × weeks since first value; immature cells stay grey.'>
            <Proposed query={retention} title='Retention' description='D7 / D28 return needs the first-value event per workspace and 28 days of maturity (PRD §7.1 M21 by cohort).'>
              {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'cohort')} unit={result.rows[0]?.unit ?? 'ratio'} />}
            </Proposed>
          </Panel>
        </TabAnchor>
      </PanelGrid>

      <p className='text-muted-foreground text-xs'>
        Looking for a workspace that stalled? Open{' '}
        <Link href={`/founder/customers?mode=${mode}&view=inactive`} className={cn(buttonVariants({ variant: 'link', size: 'xs' }), 'h-auto p-0 text-xs')}>
          Customers › Inactive 30d
        </Link>
        .
      </p>
    </FounderPage>
  );
}
