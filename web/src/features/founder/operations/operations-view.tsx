'use client';

import { parseAsString, useQueryState } from 'nuqs';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { cn } from '@/lib/utils';
import { failureOf, useAcknowledgeIncident, useCapability, useFounderMode, useIncidents, useMetric, useSourceHealth } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars, TimeSeriesChart } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { metricValue, stateLabel, whenDateTime } from '../customers/kit/format';
import { categoriesFromRows, seriesFromRows, wholeIntervalRows } from '../customers/kit/metric';
import { DataStateChip, FounderPage, MetricChartCard, MetricTileFromQuery, Panel, PanelGrid, QueryState, TileGrid } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import type { Incident, SourceHealthRow } from '../customers/kit/types';
import { IncidentList, IncidentTimeline, incidentTitle } from './incidents';

/**
 * Operations (PRD §5.3, §7.2): incidents with a version-checked Ack and a timeline, publishing success by
 * provider, notification delivery by status, phone calls by state, cron heartbeat and source health. The 7-day
 * default is the operations window; nothing here estimates an SLO. `?tab=` (incidents · health · publishing ·
 * notifications · calls · connections) lands on the matching panel; `?incident=` selects one and tells Rafii.
 */
const DEMO_ACK_REASON = 'Demo incidents are acknowledged through the Demo workspace, not the live store';
export function sourceId(row: SourceHealthRow): string {
  return row.sourceId ?? row.source_id ?? 'unknown';
}

export function sourceState(state: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (state === 'measured' || state === 'ok' || state === 'healthy') return 'success';
  if (state === 'stale' || state === 'partial' || state === 'degraded') return 'warning';
  if (state === 'failed' || state === 'error' || state === 'silent') return 'danger';
  return 'neutral';
}

export function SourceHealthList({ rows, compact = false }: { rows: SourceHealthRow[]; compact?: boolean }) {
  if (rows.length === 0) return <StateMessage kind='empty' layout='inline' title='No sources reported' />;
  return (
    <ul className={cn('grid gap-2', compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 xl:grid-cols-3')} aria-label='Source health'>
      {rows.map((row) => (
        <li key={sourceId(row)} className='rafii-quiet flex items-start justify-between gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2'>
          <span className='flex min-w-0 flex-col'>
            <span className='text-foreground text-sm font-medium'>{stateLabel(sourceId(row))}</span>
            <span className='text-muted-foreground text-xs'>Last good {whenDateTime(row.lastGoodAt ?? row.watermark)}{row.reasonCode || row.reason ? ` · ${stateLabel(row.reasonCode ?? row.reason)}` : ''}</span>
          </span>
          <StatusChip status={sourceState(row.state)} tone={sourceState(row.state) === 'success' ? 'neutral' : 'attention'}>
            {stateLabel(row.state)}
          </StatusChip>
        </li>
      ))}
    </ul>
  );
}

export function OperationsView() {
  const ask = useAsk();
  const mode = useFounderMode();
  const evidence = useEvidenceDrawer();
  const [selectedId, setSelectedId] = useQueryState('incident', parseAsString.withOptions({ history: 'push', clearOnDefault: true }));
  const tab = useSectionTab('operations');
  useFounderPageContext({ section: 'operations', incidentId: selectedId, period: '7d' });
  const incidents = useIncidents();
  const ack = useAcknowledgeIncident();
  const canAck = useCapability('incidents.ack') && mode !== 'demo';
  const ackDisabledReason = mode === 'demo' ? DEMO_ACK_REASON : undefined;
  const heartbeat = useMetric({ id: 'cron_heartbeat', period: '7d' });
  const publishing = useMetric({ id: 'publish_outcomes', period: '7d', groupBy: ['platform', 'status'] });
  const delivery = useMetric({ id: 'notification_delivery', period: '7d', groupBy: ['status'] });
  const calls = useMetric({ id: 'phone_calls', period: '7d', groupBy: ['state'] });
  const sources = useSourceHealth();

  const list = incidents.data?.incidents ?? [];
  const selected = list.find((incident) => incident.id === selectedId) ?? null;

  async function acknowledge(incident: Incident) {
    try {
      await ack.mutateAsync({ id: incident.id, version: incident.version });
      toast.success(`Acknowledged: ${incidentTitle(incident)}.`);
    } catch (error) {
      const failure = failureOf(error);
      toast.error(failure.code === 'VERSION_CONFLICT' || failure.status === 409 ? 'This incident changed since it was listed. It has been refreshed; review and acknowledge again.' : failure.message ?? 'Acknowledgement could not be confirmed.');
    }
  }

  return (
    <FounderPage
      eyebrow='Operations'
      title='Operations'
      description='What broke, how many people it touched, for how long, and whether it has recovered. Acknowledging an incident records who saw it and stops the escalation plan.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: selected ? `Explain incident ${selected.id}: what the detector saw, who is affected, and what I should do next.` : 'What is unhealthy in operations right now, and what needs my decision?', incidentId: selected?.id, period: '7d' })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <PanelGrid className='md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'>
        <TabAnchor section='operations' tab='incidents' active={tab}>
          <Panel title='Incidents' description='Detector episodes in this environment, open first.' actions={incidents.data && <DataStateChip state={incidents.data.dataState} />}>
            <QueryState query={incidents} label='incidents'>{(result) => <IncidentList incidents={result.incidents} selectedId={selectedId} onSelect={(id) => void setSelectedId(id)} onAck={(incident) => void acknowledge(incident)} acking={ack.isPending ? ack.variables?.id ?? null : null} canAck={canAck} ackDisabledReason={ackDisabledReason} />}</QueryState>
          </Panel>
        </TabAnchor>
        <Panel title='Timeline' description={selected ? incidentTitle(selected) : 'Pick an incident to follow its events.'} actions={selected?.receiptIds?.[0] && <Button variant='quiet' size='xs' onClick={() => evidence.open({ receiptId: selected.receiptIds![0], record: selected as unknown as Record<string, unknown> })}><Icons.listDetails className='size-3' /> Evidence</Button>}>
          <IncidentTimeline incident={selected} />
        </Panel>
      </PanelGrid>

      <TileGrid>
        <MetricTileFromQuery query={heartbeat} input={{ id: 'cron_heartbeat', label: 'Cron heartbeat', period: '7d' }} onAsk={() => ask({ prompt: 'Is the worker tick running on schedule? Show the heartbeat gaps in the last 7 days.', chart: 'cron_heartbeat', period: '7d' })} />
      </TileGrid>

      <PanelGrid>
        <TabAnchor section='operations' tab='publishing' active={tab}>
        <MetricChartCard query={publishing} id='publish_outcomes' title='Publishing by platform' subtitle='Outcomes per platform and status, 7 days' period='7d' unavailableDescription='Publishing outcomes come from the publishing jobs; none were measured in the last 7 days.'>
          {(result) => (
            <SimpleTable
              rows={wholeIntervalRows(result.rows).filter((row) => row.dimensions?.platform !== undefined)}
              rowKey={(row, index) => `${row.dimensions?.platform}-${row.dimensions?.status}-${index}`}
              caption='Publish outcomes by platform and status'
              columns={[
                { key: 'platform', label: 'Platform', render: (row) => stateLabel(row.dimensions?.platform) },
                { key: 'status', label: 'Status', render: (row) => <StatusChip icon={null}>{stateLabel(row.dimensions?.status)}</StatusChip> },
                { key: 'count', label: 'Publications', align: 'right', render: (row) => <span className={cn(row.dataState !== 'measured' && 'text-muted-foreground italic')}>{metricValue(row)}</span> }
              ]}
            />
          )}
        </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='operations' tab='notifications' active={tab}>
        <MetricChartCard query={delivery} id='notification_delivery' title='Notification delivery' subtitle='Deliveries by status, 7 days' period='7d' unavailableDescription='Delivery rows (business_notification_deliveries) were not measured in the last 7 days.'>
          {(result) => {
            const series = seriesFromRows(result.rows, 'status');
            return series.points.length > 0 ? <TimeSeriesChart series={series} kind='bar' stacked /> : <CategoryBars items={categoriesFromRows(result.rows, 'status')} unit={result.rows[0]?.unit ?? 'count'} />;
          }}
        </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='operations' tab='calls' active={tab}>
        <MetricChartCard query={calls} id='phone_calls' title='Phone calls' subtitle='Calls by state, 7 days (real calls stay off)' period='7d' unavailableDescription='No phone call rows (business_phone_calls) were measured. Live delivery is disabled in this release, so only fake-provider or test rows can appear.'>
          {(result) => <CategoryBars items={categoriesFromRows(result.rows, 'state')} unit={result.rows[0]?.unit ?? 'count'} />}
        </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='operations' tab='health' active={tab}>
        <Panel title='Source health' description='Last-good time per source. A silent source is never read as "all quiet".' actions={sources.data && <DataStateChip state={sources.data.dataState} />}>
          <QueryState query={sources} label='source health' isEmpty={(result) => result.sources.length === 0} emptyTitle='No sources reported'>{(result) => <SourceHealthList rows={result.sources} compact />}</QueryState>
        </Panel>
        </TabAnchor>
      </PanelGrid>

      <TabAnchor section='operations' tab='connections' active={tab}>
      <Panel title='Connection matrix' description='Provider × capability health across workspaces (ok · expiring · expired · blocked).'>
        <StateMessage kind='unsupported' layout='inline' title='The connection matrix is not collected yet' description='It needs the per-connection capability view (M29, P1). Reconnect flows stay in each customer workspace.' />
      </Panel>
      </TabAnchor>
      {evidence.drawer}
    </FounderPage>
  );
}
