'use client';

import type { ReactNode } from 'react';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { InfoTip } from '@/components/rafii';
import { Skeleton } from '@/components/ui/skeleton';
import type { useChannels } from '@/lib/api/hooks';
import type { ChannelView } from '@/lib/api/types';
import { isConnected, publishLevel } from '@/lib/channels/state';
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

function Item({ loading, children }: { loading: boolean; children: ReactNode }) {
  return <span className='flex min-h-11 items-center gap-1.5'>{loading ? <Skeleton className='h-4 w-28' /> : children}</span>;
}

/**
 * One compact status line, each part read from an API that exists today. A part whose request failed
 * says Unavailable; it never turns into a zero. The detail behind each count sits in an info tip.
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
    <section aria-label='Access status' data-tour='api-status' className='text-muted-foreground flex flex-wrap items-center gap-x-5 gap-y-1 px-1 text-sm'>
      <Item loading={channelsLoading}>
        {channelsFailed || !connected ? (
          'Accounts unavailable'
        ) : (
          <>
            <span className='text-foreground font-medium tabular-nums'>{connected.length}</span> connected
            {notConnected > 0 && <span> · {notConnected} disconnected</span>}
            {connected.length > 0 && <InfoTip label='Publish levels' className='-my-2 size-9' description={`Publish: ${publishBreakdown(connected)}`} />}
          </>
        )}
      </Item>
      <Item loading={channelsLoading}>
        {channelsFailed || reviewed === undefined || !providers ? (
          'Platforms unavailable'
        ) : (
          <>
            <span className='text-foreground font-medium tabular-nums'>{reviewed}</span> of {providers.length} {providers.length === 1 ? 'platform' : 'platforms'} approved
            <InfoTip label='About platform approval' className='-my-2 size-9' description="Each platform's review of this app, separate from what each account allows." />
          </>
        )}
      </Item>
      <Item loading={toolsLoading}>
        {toolsFailed || !isolation ? (
          'Tools unavailable'
        ) : (
          <>
            Tools
            <AnimatedBadge size='sm' status={isolation.isolated ? 'success' : 'warning'} contentKey={isolation.isolated ? 'isolated' : 'not-isolated'}>
              {isolation.isolated ? 'Isolated' : 'Not isolated'}
            </AnimatedBadge>
            <AnimatedBadge size='sm' status={isolation.publicInvokeEnabled ? 'info' : 'neutral'} contentKey={isolation.publicInvokeEnabled ? 'invoke-enabled' : 'invoke-blocked'}>
              {isolation.publicInvokeEnabled ? 'Invoke enabled' : 'Invoke blocked'}
            </AnimatedBadge>
          </>
        )}
      </Item>
    </section>
  );
}
