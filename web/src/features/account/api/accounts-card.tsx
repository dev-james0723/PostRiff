'use client';

import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { CapabilityChips } from '@/features/channels/capability-chips';
import type { useChannels } from '@/lib/api/hooks';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import { capabilityLabel } from '@/lib/channels/capabilities';
import { channelBadge, expiringSoon, nowSeconds } from '@/lib/channels/state';
import { EASE_OUT } from '@/lib/ease';
import { formatDate, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { LoadError } from './load-error';

type ChannelsQuery = ReturnType<typeof useChannels>;

/**
 * Row entrance: 40ms stagger, and rows after the fourth start with the fourth. The last row starts at
 * 3 x 40ms = 120ms and runs 150ms (the --duration-quick token), so the whole entrance ends by 270ms,
 * inside the motion system's 300ms total.
 */
const STAGGER_SECONDS = 0.04;
const STAGGER_CAP = 3;
const ROW_ENTER_SECONDS = 0.15;

function samePlatform(a: string, b: string) {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** The provider's review of the PostRiff app, in words. It is never shown as a capability level. */
function reviewText(provider: ProviderView | undefined) {
  if (!provider) return 'Provider not set up on this deployment';
  return provider.productionReviewed ? 'Provider review passed' : 'Provider review pending';
}

function AccessLine({ channel }: { channel: ChannelView }) {
  if (!channel.expiresAt) return <span>No expiry reported</span>;
  const expired = channel.expiresAt <= nowSeconds();
  return (
    <span className={cn((expired || expiringSoon(channel)) && 'text-amber-700 dark:text-amber-300')}>
      {expired
        ? `Access expired ${relativeTime(channel.expiresAt)} (${formatDate(channel.expiresAt)})`
        : `Access until ${formatDate(channel.expiresAt)} · ${relativeTime(channel.expiresAt)}`}
    </span>
  );
}

function AccountRow({ channel, provider, index }: { channel: ChannelView; provider: ProviderView | undefined; index: number }) {
  const reduce = useReducedMotion();
  const badge = channelBadge(channel);
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: ROW_ENTER_SECONDS, ease: EASE_OUT, delay: Math.min(index, STAGGER_CAP) * STAGGER_SECONDS }}
      className='flex flex-col gap-3 rounded-lg border p-3'
    >
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div className='flex min-w-0 items-center gap-2'>
          <ChannelIcon platform={channel.platform} name={channel.platform} size='sm' />
          <div className='min-w-0'>
            <p className='truncate text-sm font-medium'>{channel.platform}</p>
            <p className='text-muted-foreground truncate text-xs'>
              {channel.account} · {channel.accountType || 'account'}
            </p>
          </div>
        </div>
        <AnimatedBadge
          size='sm'
          status={badge.status}
          contentKey={`${channel.connectionState}:${badge.label}`}
        >
          {badge.label}
        </AnimatedBadge>
      </div>
      <CapabilityChips capabilities={channel.capabilities} />
      <div className='text-muted-foreground flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs'>
        <AccessLine channel={channel} />
        <span aria-hidden>·</span>
        <span>{reviewText(provider)}</span>
      </div>
    </motion.li>
  );
}

function ProvidersList({ providers }: { providers: ProviderView[] }) {
  return (
    <div className='@container flex flex-col gap-2'>
      <div>
        <h3 className='text-sm font-medium'>Providers on this deployment</h3>
        <p className='text-muted-foreground text-xs'>
          Review is the provider&apos;s approval of the PostRiff app. It is separate from what each connected account allows.
        </p>
      </div>
      {providers.length === 0 ? (
        <p className='text-muted-foreground text-sm'>No providers are set up on this deployment.</p>
      ) : (
        <ul className='grid gap-2 @lg:grid-cols-2' aria-label='Providers'>
          {providers.map((provider) => {
            const offered = Object.entries(provider.capabilities)
              .filter(([, on]) => on)
              .map(([key]) => capabilityLabel(key));
            return (
              <li key={provider.id} className='flex flex-col gap-1.5 rounded-lg border p-3'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <span className='flex min-w-0 items-center gap-2 text-sm font-medium'>
                    <ChannelIcon platform={provider.platform} name={provider.platform} size='xs' />
                    <span className='truncate'>{provider.platform}</span>
                  </span>
                  <Badge variant='outline'>{reviewText(provider)}</Badge>
                </div>
                <p className='text-muted-foreground text-xs'>
                  {offered.length > 0 ? `Can be requested: ${offered.join(', ')}` : 'No capabilities set up for this provider.'}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function AccountsSkeleton() {
  return (
    <div className='flex flex-col gap-3' aria-hidden>
      <Skeleton className='h-28 w-full' />
      <Skeleton className='h-28 w-full' />
    </div>
  );
}

/**
 * Every connected account with its verified level per capability, and the providers this deployment
 * offers with their review status stated on its own. Managing an account stays on Channels.
 */
export function AccountsCard({ channels }: { channels: ChannelsQuery }) {
  const data = channels.data;

  let content;
  if (channels.isPending) {
    content = <AccountsSkeleton />;
  } else if (channels.isError && !data) {
    content = (
      <LoadError
        title='Accounts could not be loaded.'
        error={channels.error}
        retrying={channels.isFetching}
        onRetry={() => void channels.refetch()}
      />
    );
  } else if (data) {
    content = (
      <div className='flex flex-col gap-4'>
        {data.channels.length === 0 ? (
          <Empty className='border py-8'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <Icons.broadcast />
              </EmptyMedia>
              <EmptyTitle>No accounts connected in this workspace</EmptyTitle>
              <EmptyDescription>Accounts are connected on Channels. Each one then lists what it allows here.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Link href='/app/channels' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
                Open Channels
              </Link>
            </EmptyContent>
          </Empty>
        ) : (
          <ul className='flex flex-col gap-2' aria-label='Connected accounts'>
            {data.channels.map((channel, index) => (
              <AccountRow
                key={channel.id}
                channel={channel}
                index={index}
                provider={data.providers.find((provider) => samePlatform(provider.platform, channel.platform))}
              />
            ))}
          </ul>
        )}
        <Separator />
        <ProvidersList providers={data.providers} />
      </div>
    );
  }

  return (
    <Card data-tour='api-grants'>
      <CardHeader>
        <CardTitle>Connected accounts</CardTitle>
        <CardDescription>
          What each account allows, capability by capability. Open a chip to see the evidence and when it was checked.
        </CardDescription>
        <CardAction>
          <Link href='/app/channels' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            Open Channels
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}
