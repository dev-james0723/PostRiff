'use client';

import Link from 'next/link';
import { parseAsString, useQueryState } from 'nuqs';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { cn } from '@/lib/utils';
import { failureOf, useAcknowledgeIncident, useCapability, useFounderMode, useIncidents, useMetric } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { CategoryBars } from '../customers/kit/charts';
import { useEvidenceDrawer } from '../customers/kit/evidence';
import { DataStateChip, FounderPage, MetricChartCard, Panel, PanelGrid, QueryState } from '../customers/kit/page-frame';
import { TabAnchor, useSectionTab } from '../customers/kit/tabs';
import { useIncidentDetail } from './hooks';
import { IncidentList, IncidentSwimlane, IncidentTimeline, incidentTitle } from './incidents';
import { byDimension, opsSpec, type OpsIncident } from './ops-model';
import { ConnectionMatrixTable, DeliveryTable, PublishOutcomesTable, QueueTable, RouteHealthTable, SloBurnView, SourceHealthItems } from './panels';

/**
 * Operations (PRD §5.3, §7.2; CONTRACTS §8.D): what broke, whom it touched, for how long, and whether it recovered.
 * Incidents as a swimlane by detector with the list (Ack in Live only; Demo incidents are simulated and have none) and
 * one incident's timeline; source health; API error rate and p50/p95 by route with the burn against a PROPOSED 99.5%
 * SLO; job queues from the per-minute snapshots; the provider × capability connection matrix; publishing by platform;
 * notification delivery; calls. Every number is a receipted server row; nothing is computed here. `?tab=` (incidents ·
 * health · api · jobs · connections · publishing · notifications · calls) lands on its panel; `?incident=` selects one.
 */
const PERIOD = '7d' as const;

export function OperationsView() {
  const ask = useAsk();
  const mode = useFounderMode();
  const live = mode === 'live';
  const evidence = useEvidenceDrawer();
  const [selectedId, setSelectedId] = useQueryState('incident', parseAsString.withOptions({ history: 'push', clearOnDefault: true }));
  const tab = useSectionTab('operations');
  useFounderPageContext({ section: 'operations', incidentId: selectedId, period: PERIOD });
  const incidents = useIncidents();
  const ack = useAcknowledgeIncident();
  const canAck = useCapability('incidents.ack');
  const list: OpsIncident[] = incidents.data?.incidents ?? [];
  const selected = list.find((incident) => incident.id === selectedId) ?? null;
  // Live list rows carry no events; the detail read adds the server timeline. Demo rows already hold theirs.
  const detail = useIncidentDetail(selected?.id ?? null, live);
  const shown = live && detail.data?.data.incident?.id === selected?.id ? (detail.data?.data.incident ?? selected) : selected;

  const sources = useMetric(opsSpec('sourceHealth', PERIOD));
  const errors = useMetric(opsSpec('apiErrors', PERIOD));
  const latency = useMetric(opsSpec('apiLatency', PERIOD));
  const burn = useMetric(opsSpec('sloBurn', PERIOD));
  const queues = useMetric(opsSpec('queues', PERIOD));
  const connections = useMetric(opsSpec('connections', PERIOD));
  const publishRate = useMetric(opsSpec('publishRate', PERIOD));
  const outcomes = useMetric(opsSpec('publishOutcomes', PERIOD));
  const delivery = useMetric(opsSpec('delivery', PERIOD));
  const calls = useMetric(opsSpec('calls', PERIOD));
  const notSimulated = 'The Demo dataset does not simulate this telemetry; Live shows it once the source records rows.';

  async function acknowledge(incident: OpsIncident & { version: number }) {
    try {
      await ack.mutateAsync({ id: incident.id, version: incident.version });
      toast.success(`Acknowledged: ${incidentTitle(incident)}.`);
    } catch (error) {
      const failure = failureOf(error);
      toast.error(failure.code === 'STALE_PREVIEW' || failure.status === 409 ? 'This incident changed since it was listed. It has been refreshed; review and acknowledge again.' : (failure.message ?? 'Acknowledgement could not be confirmed.'));
    }
  }

  return (
    <FounderPage
      eyebrow='Operations'
      title='Operations'
      description='What broke, how many people it touched, for how long, and whether it has recovered. Acknowledging an incident records who saw it and stops the escalation plan.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: selected ? `Explain incident ${selected.id}: what the detector saw, who is affected, and what I should do next.` : 'What is unhealthy in operations right now, and what needs my decision?', incidentId: selected?.id, period: PERIOD })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <PanelGrid className='md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'>
        <TabAnchor section='operations' tab='incidents' active={tab}>
          <Panel
            title='Incidents'
            description={live ? 'Detector episodes in this environment over the last 7 days, by detector; open episodes first in the list.' : 'Simulated Demo episodes. Demo incidents have no acknowledgement; Ack exists in Live only.'}
            actions={incidents.data && <DataStateChip state={incidents.data.dataState} />}
          >
            <QueryState query={incidents} label='incidents'>
              {(result) => (
                <div className='flex flex-col gap-4'>
                  <IncidentSwimlane incidents={result.incidents} selectedId={selectedId} now={incidents.dataUpdatedAt} />
                  <IncidentList incidents={result.incidents} selectedId={selectedId} onSelect={(id) => void setSelectedId(id)} onAck={(incident) => void acknowledge(incident)} acking={ack.isPending ? (ack.variables?.id ?? null) : null} ackable={live} canAck={canAck} />
                </div>
              )}
            </QueryState>
          </Panel>
        </TabAnchor>
        <Panel
          title='Timeline'
          description={shown ? incidentTitle(shown) : 'Pick an incident to follow its events.'}
          actions={
            shown && (
              <Button variant='quiet' size='xs' onClick={() => evidence.open({ receiptId: incidents.data?.receiptIds?.[0] ?? null, record: shown as unknown as Record<string, unknown> })}>
                <Icons.listDetails className='size-3' /> Evidence
              </Button>
            )
          }
        >
          {live && selected && detail.isPending ? <StateMessage kind='loading' layout='inline' title='Loading the timeline…' /> : <IncidentTimeline incident={shown} />}
          {live && detail.error ? <p className='text-muted-foreground text-xs'>The full timeline could not be loaded; the lifecycle stamps above come from the list.</p> : null}
        </Panel>
      </PanelGrid>

      <TabAnchor section='operations' tab='health' active={tab}>
        <Panel
          title='Source health'
          description='Every probed source and its last good read. A silent source is never read as "all quiet".'
          actions={
            <Link href={`/founder/advanced?mode=${mode}&tab=data-health`} className={cn(buttonVariants({ variant: 'quiet', size: 'xs' }))}>
              Data health <Icons.chevronRight />
            </Link>
          }
        >
          <QueryState query={sources} label='source health'>
            {(result) => <SourceHealthItems rows={result.rows} compact />}
          </QueryState>
        </Panel>
      </TabAnchor>

      <TabAnchor section='operations' tab='api' active={tab}>
        <MetricChartCard query={errors} id='api_error_rate' title='API health by route' subtitle='5xx rate and p50 / p95 per route pattern, 7 days' period={PERIOD} unavailableDescription={live ? 'Request metrics start with the first flush after the request hook ships (migration 060).' : notSimulated}>
          {(result) => <RouteHealthTable errors={result.rows} latency={latency.data?.rows ?? []} />}
        </MetricChartCard>
      </TabAnchor>
      <MetricChartCard query={burn} id='slo_burn' title='Error budget burn' subtitle='Proposed 99.5% SLO, not approved · 5m / 30m / 1h / 6h windows' period={PERIOD} unavailableDescription={live ? 'Burn needs request metrics and publish outcomes in the last six hours.' : notSimulated}>
        {(result) => <SloBurnView rows={result.rows} />}
      </MetricChartCard>

      <TabAnchor section='operations' tab='jobs' active={tab}>
        <MetricChartCard query={queues} id='queue_health' title='Jobs and queues' subtitle='Overdue, stuck and failed work per minute snapshot: 7-day peak and latest reading' period={PERIOD} unavailableDescription={live ? 'The founder cron stores one operational snapshot per minute once migration 060 is applied.' : notSimulated}>
          {(result) => <QueueTable rows={result.rows} />}
        </MetricChartCard>
      </TabAnchor>

      <TabAnchor section='operations' tab='connections' active={tab}>
        <MetricChartCard query={connections} id='connection_health' title='Connection matrix' subtitle='Provider × capability across customer workspaces, as of the hourly refresh' period={PERIOD} unavailableDescription={live ? 'The hourly connection refresh has not recorded a connected channel yet.' : notSimulated}>
          {(result) => <ConnectionMatrixTable rows={result.rows} />}
        </MetricChartCard>
      </TabAnchor>

      <TabAnchor section='operations' tab='publishing' active={tab}>
        <PanelGrid>
          <MetricChartCard query={publishRate} id='publish_by_provider' title='Publishing success by platform' subtitle='Verified ÷ all outcomes per platform, 7 days' period={PERIOD} unavailableDescription={live ? 'Publish outcomes are recorded while notifications v2 is on; none were measured in the last 7 days.' : notSimulated}>
            {(result) => <CategoryBars items={byDimension(result.rows, 'provider')} unit='ratio' emptyTitle='No platform measured in this period' />}
          </MetricChartCard>
          <MetricChartCard query={outcomes} id='publish_outcomes' title='Publish outcomes' subtitle='Verified, failed and uncertain per platform, 7 days' period={PERIOD} unavailableDescription={live ? 'Publish outcomes are recorded while notifications v2 is on; none were measured in the last 7 days.' : notSimulated}>
            {(result) => <PublishOutcomesTable rows={result.rows} />}
          </MetricChartCard>
        </PanelGrid>
      </TabAnchor>

      <PanelGrid>
        <TabAnchor section='operations' tab='notifications' active={tab}>
          <MetricChartCard query={delivery} id='notification_delivery' title='Notification delivery' subtitle='Deliveries by channel and status, 7 days' period={PERIOD} unavailableDescription='Delivery rows were not measured in the last 7 days.'>
            {(result) => <DeliveryTable rows={result.rows} />}
          </MetricChartCard>
        </TabAnchor>
        <TabAnchor section='operations' tab='calls' active={tab}>
          <MetricChartCard query={calls} id='phone_calls' title='Phone calls' subtitle='Calls by state, 7 days (real calls stay off)' period={PERIOD} unavailableDescription='No phone call rows were measured. Live delivery is disabled in this release, so only fake-provider or test rows can appear.'>
            {(result) => <CategoryBars items={byDimension(result.rows, 'state')} unit='count' emptyTitle='No call measured in this period' />}
          </MetricChartCard>
        </TabAnchor>
      </PanelGrid>
      {evidence.drawer}
    </FounderPage>
  );
}
