'use client';

import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { LevelBadge } from '@/components/app/level-badge';
import { CollectionRow, StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { useChannels } from '@/lib/api/hooks';
import type { ChannelView } from '@/lib/api/types';
import { channelBadge, expiringSoon, isConnected, nowSeconds, publishLevel, sortForAttention } from '@/lib/channels/state';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { SectionUnavailable } from './retry';

export interface PublishCounts {
  direct: number;
  assisted: number;
  /** The API calls the desktop companion level `Bridge`; people see it as Local. */
  local: number;
  connected: number;
}

/** Publish levels across the accounts still connected; a card the person disconnected counts for nothing. */
export function publishCounts(channels: readonly ChannelView[]): PublishCounts {
  const counts: PublishCounts = { direct: 0, assisted: 0, local: 0, connected: 0 };
  for (const channel of channels) {
    if (!isConnected(channel)) continue;
    counts.connected += 1;
    const level = publishLevel(channel);
    if (level === 'Direct') counts.direct += 1;
    else if (level === 'Assisted') counts.assisted += 1;
    else if (level === 'Bridge') counts.local += 1;
  }
  return counts;
}

/** Access dates straight from the API: expired, or ending within the week. Nothing when the API gave no date. */
function expiryHint(channel: ChannelView, now: number) {
  if (!channel.expiresAt) return null;
  if (channel.connectionState === 'token_expired') return `Access expired ${relativeTime(channel.expiresAt, now)}`;
  if (expiringSoon(channel, now)) return `Access ends ${relativeTime(channel.expiresAt, now)}`;
  return null;
}

/** What each connection can really do today: its connection state and its publish level, never a blended "Connected". */
export function ChannelsCard({ className }: { className?: string }) {
  const channels = useChannels();
  const now = nowSeconds();
  const list = channels.data?.channels ?? [];
  const counts = publishCounts(list);
  const ready = Boolean(channels.data) && !channels.isError;

  return (
    <Panel
      data-tour='overview-channels'
      className={className}
      title='Channels'
      titleId='overview-channels-heading'
      description={
        <>
          What each connection can really do today.
          {ready && counts.connected > 0 && (
            <span className='text-foreground mt-1 block text-xs font-medium tabular-nums'>
              Publish: {counts.direct} Direct · {counts.assisted} Assisted · {counts.local} Local
            </span>
          )}
        </>
      }
      footer={
        <Link href='/app/channels' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'default' }), '-ml-2.5 w-fit')}>
          {ready && list.length === 0 ? 'Connect a channel' : 'Manage channels'} <LearnMoreChevron />
        </Link>
      }
    >
      {channels.isError ? (
        <SectionUnavailable message='Channels are unavailable right now.' query={channels} />
      ) : !channels.data ? (
        <Skeleton className='h-24 w-full rounded-[var(--rafii-radius-control)]' />
      ) : list.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No channels connected yet.' description='Connecting an account lets you schedule and publish.' />
      ) : (
        <ul className='flex flex-col gap-2'>
          {sortForAttention(list, now).map((channel) => {
            const badge = channelBadge(channel, now);
            const hint = expiryHint(channel, now);
            return (
              <CollectionRow
                key={channel.id}
                as='li'
                className='flex-wrap py-3'
                leading={<ChannelIcon platform={channel.platform} name={channel.platform} />}
                title={channel.platform}
                meta={
                  <>
                    <span className='block truncate'>{channel.account}</span>
                    {hint && <span className={cn('mt-0.5 block', channel.connectionState === 'token_expired' && 'text-foreground')}>{hint}</span>}
                  </>
                }
                actions={
                  <span className='flex flex-wrap items-center gap-1.5'>
                    <StatusChip status={badge.status}>{badge.label}</StatusChip>
                    <span className='text-muted-foreground text-xs'>publish</span>
                    <LevelBadge level={channel.capabilities.publish?.level} />
                  </span>
                }
              />
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
