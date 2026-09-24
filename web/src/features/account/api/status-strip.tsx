'use client';

import { AnimatedBadge } from '@/components/motion/animated-badge';
import type { useChannels } from '@/lib/api/hooks';
import type { ChannelView } from '@/lib/api/types';
import { isConnected, publishLevel } from '@/lib/channels/state';
import { StatTile } from '../settings-section';
import type { ToolRegistryState } from './tool-registry';

type ChannelsQuery = ReturnType<typeof useChannels>;

const PUBLISH_LEVELS = [
  { level: 'Direct', label: 'Direct' },
  { level: 'Assisted', label: 'Assisted' },
  { level: 'Bridge', label: 'Local' },
  { level: 'Unsupported', label: 'Unsupported' }
] as const;

/**
 * Publish level per connected account, counted from each account's own capability row (no row counts
 * as Unsupported). Callers pass connected accounts only, so a disconnected record never adds a level.
 */
function publishBreakdown(connected: ChannelView[]) {
  return PUBLISH_LEVELS.map(({ level, label }) => {
    const count = connected.filter((channel) => publishLevel(channel) === level).length;
    return `${count} ${label}`;
  }).join(' · ');
}

/**
 * Three quiet tiles, each read from an API that exists today. A tile whose request failed or cannot be
 * made says Unavailable; it never turns into a zero. Columns follow the strip's own width (a
 * container query), so the tiles stay readable when the sidebars are open.
 */
export function StatusStrip({ channels, tools }: { channels: ChannelsQuery; tools: ToolRegistryState }) {
  const accounts = channels.data?.channels;
  // The Channels page's own rule: records the API still lists but that are disconnected are not counted.
  const connected = accounts?.filter((channel) => isConnected(channel));
  const notConnected = accounts && connected ? accounts.length - connected.length : 0;
  const providers = channels.data?.providers;
  const reviewed = providers?.filter((provider) => provider.productionReviewed).length;
  const channelsLoading = channels.isPending && channels.fetchStatus !== 'idle';
  const channelsFailed = channels.isError && !channels.data;

  const isolation = tools.query.data?.isolation;
  const toolsLoading = tools.available && tools.query.isPending;
  const toolsFailed = !tools.available || (tools.query.isError && !tools.query.data);

  return (
    <section aria-label='Access status' data-tour='api-status' className='@container'>
      <div className='grid grid-cols-1 gap-3 @2xl:grid-cols-3'>
        <StatTile
          label='Connected accounts'
          loading={channelsLoading}
          value={channelsFailed || !connected ? 'Unavailable' : connected.length}
          hint={!channelsFailed && notConnected > 0 ? `${notConnected} more listed but disconnected` : undefined}
          footer={
            channelsFailed
              ? 'Accounts could not be loaded.'
              : connected && connected.length > 0
                ? `Publish: ${publishBreakdown(connected)}`
                : connected
                  ? 'Connect accounts on Channels.'
                  : undefined
          }
        />
        <StatTile
          label='Providers that passed review'
          loading={channelsLoading}
          value={channelsFailed || reviewed === undefined ? 'Unavailable' : reviewed}
          hint={
            providers
              ? providers.length === 0
                ? 'No providers set up on this deployment'
                : `of ${providers.length} ${providers.length === 1 ? 'provider' : 'providers'} on this deployment`
              : undefined
          }
          footer={providers ? "A provider's review of PostRiff, separate from each account's levels." : undefined}
        />
        <StatTile
          label='Tool runner'
          loading={toolsLoading}
          value={toolsFailed || !isolation ? 'Unavailable' : isolation.isolated ? 'Isolated' : 'Not isolated'}
          footer={
            !tools.available ? (
              'This page cannot read the tool registry yet.'
            ) : tools.query.isError && !tools.query.data ? (
              'The tool registry could not be loaded.'
            ) : isolation ? (
              <span className='flex flex-wrap items-center gap-2'>
                <AnimatedBadge
                  size='sm'
                  status={isolation.publicInvokeEnabled ? 'info' : 'neutral'}
                  contentKey={isolation.publicInvokeEnabled ? 'invoke-enabled' : 'invoke-blocked'}
                >
                  {isolation.publicInvokeEnabled ? 'Invoke enabled' : 'Invoke blocked'}
                </AnimatedBadge>
                <span className='font-mono text-xs'>runner: {isolation.runner}</span>
              </span>
            ) : undefined
          }
        />
      </div>
    </section>
  );
}
