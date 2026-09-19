'use client';

import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { LevelBadge } from '@/components/app/level-badge';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
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
    <Card data-tour='overview-channels' className={className}>
      <CardHeader>
        <CardTitle>Channels</CardTitle>
        <CardDescription>
          What each connection can really do today.
          {ready && counts.connected > 0 && (
            <span className='text-foreground mt-1 block text-xs font-medium tabular-nums'>
              Publish: {counts.direct} Direct · {counts.assisted} Assisted · {counts.local} Local
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className='@container flex flex-col gap-3'>
        {channels.isError ? (
          <SectionUnavailable message='Channels are unavailable right now.' query={channels} />
        ) : !channels.data ? (
          <Skeleton className='h-24 w-full' />
        ) : list.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No channels connected yet.</p>
        ) : (
          <ul className='flex flex-col gap-2'>
            {sortForAttention(list, now).map((channel) => {
              const badge = channelBadge(channel, now);
              const hint = expiryHint(channel, now);
              return (
                <li key={channel.id} className='flex flex-col gap-2 rounded-lg border p-3'>
                  <div className='flex flex-col gap-2 @sm:flex-row @sm:items-center @sm:justify-between'>
                    <div className='flex min-w-0 items-center gap-2'>
                      <ChannelIcon platform={channel.platform} name={channel.platform} />
                      <div className='min-w-0'>
                        <p className='truncate text-sm font-medium'>{channel.platform}</p>
                        <p className='text-muted-foreground truncate text-xs'>{channel.account}</p>
                      </div>
                    </div>
                    <div className='flex shrink-0 flex-wrap items-center gap-1.5'>
                      <AnimatedBadge size='sm' status={badge.status} contentKey={channel.connectionState}>
                        {badge.label}
                      </AnimatedBadge>
                      <span className='text-muted-foreground text-xs'>publish</span>
                      <LevelBadge level={channel.capabilities.publish?.level} />
                    </div>
                  </div>
                  {hint && (
                    <p className={cn('text-xs', channel.connectionState === 'token_expired' ? 'text-destructive' : 'text-muted-foreground')}>
                      {hint}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <Link href='/app/channels' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), 'w-fit')}>
          {ready && list.length === 0 ? 'Connect a channel' : 'Manage channels'} <LearnMoreChevron />
        </Link>
      </CardContent>
    </Card>
  );
}
