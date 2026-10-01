'use client';

import { Component, useCallback, useId, type ErrorInfo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import PageContainer from '@/components/layout/page-container';
import { SegmentedControl } from '@/components/rafii';
import { founderPanelStore } from '@/features/founder/agent/store';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { DataStateChip, QueryBoundary, StateFallback } from '@/features/founder/shared/state-fallbacks';
import { founderKeys } from '@/lib/founder/api';
import { normalizeAttentionItem } from '@/lib/founder/attention';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { OVERVIEW_PERIODS, type AttentionAction, type NormalizedAttentionItem, type Overview, type OverviewPeriod, type PulseTile } from '@/lib/founder/types';
import { AttentionPanel } from './attention';
import { DataHealthStrip } from './data-health';
import { FollowUpsPanel, ReportsPanel } from './follow-ups';
import { PulseRow } from './pulse-row';
import { TodayBrief } from './today-brief';
import { TrendChart } from './trend-chart';

/**
 * Founder Overview (PRD §5.2): Today brief → Pulse row → Attention (left) with Data health and two trends (right),
 * and Follow-ups / Reports tabs beside Today. One `GET /overview` call per mode and period; every number on the page
 * is a server value with its receipt.
 */

const TABS = ['today', 'follow-ups', 'reports'] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = { today: 'Today', 'follow-ups': 'Follow-ups', reports: 'Reports' };

/**
 * One failing panel (a payload the page did not expect) must not blank the whole Today tab: the boundary shows the
 * error state in its place and the rest of the founder admin keeps working. Keyed by period so a new answer retries.
 */
class TodayBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Founder overview failed to render', error, info.componentStack);
  }
  render() {
    return this.state.failed ? <StateFallback kind='error' title='Today could not be drawn' description='One of the Overview panels failed to render. The records are unchanged; reload, or open a section from the sidebar.' /> : this.props.children;
  }
}

const infoContent = {
  title: 'How the Overview reads',
  sections: [
    { title: 'Real numbers only', description: 'Every tile and line is a server value with a receipt. A metric that is not ready says since when it has been collecting; nothing is shown as zero when it is unknown.' },
    { title: 'Demo is a data mode', description: 'Demo shows a fictional dataset in this same environment. Emails, calls and account changes stay off in both modes.' },
    { title: 'Attention', description: 'Items come from rules (open incident, cost anomaly, payment failures, quota, stale source), never from a health score.' }
  ]
};

export function OverviewView() {
  const { api, mode, environment } = useFounderSession();
  const [period, setPeriod] = useQueryState('period', parseAsStringLiteral(OVERVIEW_PERIODS).withDefault('30d'));
  const [tab, setTab] = useQueryState('tab', parseAsStringLiteral(TABS).withDefault('today'));
  const panelBase = useId();
  useFounderPageContext({ section: 'overview', period });
  const envKey = environment ?? 'unknown';
  const query = useQuery({
    queryKey: founderKeys.overview(mode, envKey, period),
    queryFn: ({ signal }) => api.overview(mode, period, { signal }),
    retry: false,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000
  });

  const askAboutToday = useCallback(() => founderPanelStore.ask('Give me today’s brief: what changed, what is under pressure, any anomaly, and what I should decide. Cite receipts.', { section: 'overview', period }), [period]);
  const askTile = useCallback((tile: PulseTile) => founderPanelStore.ask(`Explain ${tile.label} for the last ${period}: what moved it, how complete the data is, and what it cannot tell me.`, { section: 'overview', period, chart: { chartId: tile.id, viewVersion: 1, queryReceiptId: tile.receiptId ?? null } }), [period]);
  const askAttention = useCallback((item: NormalizedAttentionItem, action: AttentionAction) => {
    const prompt = action.prompt ?? (action.kind === 'draft_reminder' ? `Prepare a reminder about "${item.title}" for me to confirm.` : `Explain "${item.title}": who is affected, what is known, what is unknown, and what happens next.`);
    founderPanelStore.ask(prompt, { section: 'overview', period, incidentId: action.incidentId ?? null, selectedEntity: { type: 'attention', id: item.id } });
  }, [period]);
  const askTrend = useCallback((trend: Overview['trends'][keyof Overview['trends']], fallback: string) => () => founderPanelStore.ask(`Explain the "${trend?.title ?? fallback}" chart for the last ${period}: what the lines show, their coverage, and what would be a measurable next step.`, { section: 'overview', period, chart: trend ? { chartId: trend.id, viewVersion: 1, queryReceiptId: trend.receiptId ?? null } : null }), [period]);

  const periodControl = <SegmentedControl<OverviewPeriod> label='Period' size='sm' widths='content' value={period} onChange={(next) => void setPeriod(next)} options={OVERVIEW_PERIODS.map((value) => ({ value, label: value }))} />;
  const tabs = <SegmentedControl<Tab> label='Overview view' pattern='tabs' size='sm' widths='content' value={tab} onChange={(next) => void setTab(next)} options={TABS.map((value) => ({ value, label: TAB_LABEL[value] }))} panelIds={TABS.map((value) => `${panelBase}-${value}`)} />;

  return (
    <PageContainer pageTitle='Overview' pageEyebrow='Founder' pageDescription='What changed, what needs you, and your next step.' infoContent={infoContent} pageHeaderAction={<div className='flex flex-wrap items-center gap-2'>{tabs}{tab === 'today' && periodControl}</div>}>
      {tab === 'follow-ups' ? (
        <div id={`${panelBase}-follow-ups`} role='tabpanel'>
          <FollowUpsPanel />
        </div>
      ) : tab === 'reports' ? (
        <div id={`${panelBase}-reports`} role='tabpanel'>
          <ReportsPanel />
        </div>
      ) : (
        <div id={`${panelBase}-today`} role='tabpanel' className='flex min-w-0 flex-1 flex-col gap-4 md:gap-5'>
          <QueryBoundary query={query} loadingTitle='Reading today’s records…'>
            {(envelope) => {
              const overview = envelope.data;
              const attention = (overview.attention ?? []).map(normalizeAttentionItem);
              return (
                <TodayBoundary key={`${mode}-${period}-${envelope.requestId}`}>
                  <TodayBrief brief={overview.brief} mode={mode} onAsk={askAboutToday} />
                  <PulseRow tiles={overview.pulse ?? []} onAsk={askTile} />
                  <div className='grid grid-cols-1 gap-4 md:gap-5 lg:grid-cols-12'>
                    <AttentionPanel className='lg:col-span-7' items={attention} onAsk={askAttention} />
                    <div className='flex flex-col gap-4 md:gap-5 lg:col-span-5'>
                      <DataHealthStrip sources={overview.sourceHealth ?? []} mode={mode} />
                      <TrendChart title='Revenue vs AI cost' trend={overview.trends?.revenueVsCost ?? null} period={period} periods={OVERVIEW_PERIODS} onPeriodChange={(next) => void setPeriod(next as OverviewPeriod)} onAsk={askTrend(overview.trends?.revenueVsCost ?? null, 'Revenue vs AI cost')} />
                      <TrendChart title='Active workspaces vs publishing verified' trend={overview.trends?.activeVsPublish ?? null} period={period} periods={OVERVIEW_PERIODS} onPeriodChange={(next) => void setPeriod(next as OverviewPeriod)} onAsk={askTrend(overview.trends?.activeVsPublish ?? null, 'Active workspaces vs publishing verified')} />
                    </div>
                  </div>
                  <p className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
                    <DataStateChip state={envelope.dataState} asOf={envelope.asOf} />
                    <span>
                      {mode === 'demo' ? 'Fictional dataset; delivery off.' : 'Live records from this environment.'} Request {envelope.requestId.slice(0, 8)}
                    </span>
                  </p>
                </TodayBoundary>
              );
            }}
          </QueryBoundary>
        </div>
      )}
    </PageContainer>
  );
}
