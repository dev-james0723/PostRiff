'use client';

import Link from 'next/link';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { founderHref } from '@/config/founder-nav';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { cn } from '@/lib/utils';
import { useFounderMode, useMetric, useTileMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { FounderPage, MetricTileFromQuery, PanelGrid, PeriodSwitch, TileGrid } from '../customers/kit/page-frame';
import type { PeriodKey } from '../customers/kit/period';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import { FunnelCard, TimeToValueTile } from './funnel-panel';
import { ActiveWorkspacesCard, AdoptionCard, CorrelationsCard, PublishingCard, RetentionCard, TimeBackCard } from './product-panels';

/**
 * Product (PRD §5.3, §7.2; CONTRACTS §8.C): whether people get value and which features are really reused. The
 * activation funnel (M23 v1) with each step's drop-off and the workspaces stuck before it, median time to value with
 * its n, feature adoption over eligible workspaces, the weekly retention heatmap (unfinished weeks grey), time back by
 * confidence (measured / personalized / estimated, never merged) and the retention correlations, labelled a hypothesis.
 * Every query asks only for its catalog's allowed dimensions; every number is the server's, with its receipt.
 */
const PERIODS: PeriodKey[] = ['30d', '90d'];
/** Retention cohorts span 12 weeks (PRD §7.2). */
const RETENTION_PERIOD: PeriodKey = '12w';
/** Correlations compare signups at least 8 weeks old, so they look back over six months of signups. */
const CORRELATION_PERIOD: PeriodKey = '6m';

export function ProductView() {
  const mode = useFounderMode();
  const ask = useAsk();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(PERIODS).withDefault('30d'));
  const tab = useSectionTab('product');
  useFounderPageContext({ section: 'product', period, ...(tab ? { filters: { tab } } : {}) });

  const activeTile = useTileMetric({ id: 'active_workspaces', period });
  const publishTile = useTileMetric({ id: 'publish_outcomes', period, filters: [{ dimension: 'status', operator: 'eq', values: ['verified'] }] });
  const funnel = useMetric({ id: 'activation_funnel', period, groupBy: ['step'] });
  const timeToValue = useMetric({ id: 'time_to_value', period });
  const adoption = useMetric({ id: 'feature_adoption', period, groupBy: ['feature'] });
  const timeBack = useMetric({ id: 'time_back', period, groupBy: ['confidence'] });
  const timeBackDaily = useMetric({ id: 'time_back', period, groupBy: ['confidence', 'window'] });
  const retention = useMetric({ id: 'retention_weekly', period: RETENTION_PERIOD, groupBy: ['cohort', 'week'] });
  const correlations = useMetric({ id: 'retention_correlations', period: CORRELATION_PERIOD, groupBy: ['feature'] });
  const activeDaily = useMetric({ id: 'active_workspaces', period, groupBy: ['window'] });
  const publishDaily = useMetric({ id: 'publish_outcomes', period, groupBy: ['status', 'window'] });

  return (
    <FounderPage
      eyebrow='Product'
      title='Product'
      description='Whether people get value from Rafii and which features they really reuse: activation, time to value, adoption, retention and time back, each with its sample and source.'
      actions={
        <>
          <PeriodSwitch value={period} onChange={(value) => void setPeriod(value)} options={PERIODS} />
          <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Are new workspaces getting value? Use the activation funnel, time to value, feature adoption and time back for this period, and say what is not measured.', period })}>
            <Icons.sparkles /> Ask Rafii
          </Button>
        </>
      }
    >
      <TileGrid>
        <MetricTileFromQuery query={activeTile} input={{ id: 'active_workspaces', label: 'Active workspaces', period, href: founderHref('customers', mode, { tab: 'workspaces' }) }} onAsk={() => ask({ prompt: 'Which workspaces became active or inactive in this period?', chart: 'active_workspaces', period })} />
        <MetricTileFromQuery query={publishTile} input={{ id: 'publish_outcomes', label: 'Verified publications', period, href: founderHref('operations', mode, { tab: 'publishing' }) }} />
        <TimeToValueTile query={timeToValue} period={period} />
      </TileGrid>

      <TabAnchor section='product' tab='activation' active={tab}>
        <FunnelCard query={funnel} period={period} />
      </TabAnchor>

      <PanelGrid>
        <TabAnchor section='product' tab='features' active={tab}>
          <AdoptionCard query={adoption} period={period} />
        </TabAnchor>
        <TabAnchor section='product' tab='time-back' active={tab}>
          <TimeBackCard totals={timeBack} daily={timeBackDaily} period={period} />
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='product' tab='retention' active={tab}>
        <RetentionCard query={retention} period={RETENTION_PERIOD} />
      </TabAnchor>

      <TabAnchor section='product' tab='correlations' active={tab}>
        <CorrelationsCard query={correlations} period={CORRELATION_PERIOD} />
      </TabAnchor>

      <PanelGrid>
        <TabAnchor section='product' tab='active' active={tab}>
          <ActiveWorkspacesCard query={activeDaily} period={period} />
        </TabAnchor>
        <TabAnchor section='product' tab='publishing' active={tab}>
          <PublishingCard query={publishDaily} period={period} />
        </TabAnchor>
      </PanelGrid>

      <p className='text-muted-foreground text-xs'>
        Looking for workspaces that stalled? Open{' '}
        <Link href={founderHref('customers', mode, { view: 'inactive_30d' })} className={cn(buttonVariants({ variant: 'link', size: 'xs' }), 'h-auto p-0 text-xs')}>
          Customers › Inactive 30d
        </Link>{' '}
        or a funnel step’s stuck list above.
      </p>
    </FounderPage>
  );
}
