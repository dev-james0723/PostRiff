'use client';

import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StateMessage, Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { CapabilityChips } from '@/features/channels/capability-chips';
import type { useChannels } from '@/lib/api/hooks';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import { capabilityLabel } from '@/lib/channels/capabilities';
import { channelBadge, expiringSoon, nowSeconds } from '@/lib/channels/state';
import { formatDate, relativeTime } from '@/lib/time';
import { SettingsSection } from '../settings-section';
import { LoadError } from './load-error';

type ChannelsQuery = ReturnType<typeof useChannels>;

function samePlatform(a: string, b: string) {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** The provider's review of the PostRiff app, in words. It is never shown as a capability level. */
function reviewText(provider: ProviderView | undefined) {
  if (!provider) return 'Provider not set up on this deployment';
  return provider.productionReviewed ? 'Provider review passed' : 'Provider review pending';
}

/** Expiry in words; an expired or expiring grant carries the clock icon as well as the sentence (DNA §4.3). */
function AccessLine({ channel }: { channel: ChannelView }) {
  if (!channel.expiresAt) return <span>No expiry reported</span>;
  const expired = channel.expiresAt <= nowSeconds();
  const attention = expired || expiringSoon(channel);
  return (
    <span className='inline-flex items-center gap-1'>
      {attention && <Icons.clock className='size-3.5 shrink-0' aria-hidden />}
      <span className={attention ? 'text-foreground' : undefined}>
        {expired
          ? `Access expired ${relativeTime(channel.expiresAt)} (${formatDate(channel.expiresAt)})`
          : `Access until ${formatDate(channel.expiresAt)} · ${relativeTime(channel.expiresAt)}`}
      </span>
    </span>
  );
}

function AccountRow({ channel, provider }: { channel: ChannelView; provider: ProviderView | undefined }) {
  const badge = channelBadge(channel);
  return (
    <Surface as='li' material='quiet' radius='card' padding='sm' className='flex flex-col gap-3 p-4'>
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div className='flex min-w-0 items-center gap-2.5'>
          <ChannelIcon platform={channel.platform} name={channel.platform} size='sm' />
          <div className='min-w-0'>
            <p className='text-foreground truncate text-sm font-medium'>{channel.platform}</p>
            <p className='text-muted-foreground truncate text-xs'>
              {channel.account} · {channel.accountType || 'account'}
            </p>
          </div>
        </div>
        <AnimatedBadge size='sm' status={badge.status} contentKey={`${channel.connectionState}:${badge.label}`}>
          {badge.label}
        </AnimatedBadge>
      </div>
      <CapabilityChips capabilities={channel.capabilities} />
      <div className='text-muted-foreground flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs'>
        <AccessLine channel={channel} />
        <span aria-hidden>·</span>
        <span>{reviewText(provider)}</span>
      </div>
    </Surface>
  );
}

function ProvidersList({ providers }: { providers: ProviderView[] }) {
  return (
    <div className='@container flex flex-col gap-2'>
      <div className='px-1'>
        <h3 className='text-foreground text-sm font-medium'>Providers on this deployment</h3>
        <p className='text-muted-foreground text-xs leading-relaxed'>
          Review is the provider&apos;s approval of the PostRiff app. It is separate from what each connected account allows.
        </p>
      </div>
      {providers.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No providers are set up on this deployment.' />
      ) : (
        <ul className='grid gap-2 @lg:grid-cols-2' aria-label='Providers'>
          {providers.map((provider) => {
            const offered = Object.entries(provider.capabilities)
              .filter(([, on]) => on)
              .map(([key]) => capabilityLabel(key));
            return (
              <Surface as='li' key={provider.id} material='quiet' radius='card' padding='sm' className='flex flex-col gap-1.5 p-4'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <span className='text-foreground flex min-w-0 items-center gap-2 text-sm font-medium'>
                    <ChannelIcon platform={provider.platform} name={provider.platform} size='xs' />
                    <span className='truncate'>{provider.platform}</span>
                  </span>
                  <Badge variant='secondary'>{reviewText(provider)}</Badge>
                </div>
                <p className='text-muted-foreground text-xs leading-relaxed'>
                  {offered.length > 0 ? `Can be requested: ${offered.join(', ')}` : 'No capabilities set up for this provider.'}
                </p>
              </Surface>
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
      <Skeleton className='h-28 w-full rounded-[var(--rafii-radius-card)]' />
      <Skeleton className='h-28 w-full rounded-[var(--rafii-radius-card)]' />
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
      <div className='flex flex-col gap-6'>
        {data.channels.length === 0 ? (
          <StateMessage
            kind='empty'
            media={
              <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
                <Icons.broadcast className='size-5' />
              </span>
            }
            title='No accounts connected in this workspace'
            description='Accounts are connected on Channels. Each one then lists what it allows here.'
            action={
              <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
                Open Channels
              </Link>
            }
          />
        ) : (
          <ul className='flex flex-col gap-2' aria-label='Connected accounts'>
            {data.channels.map((channel) => (
              <AccountRow key={channel.id} channel={channel} provider={data.providers.find((provider) => samePlatform(provider.platform, channel.platform))} />
            ))}
          </ul>
        )}
        <ProvidersList providers={data.providers} />
      </div>
    );
  }

  return (
    <SettingsSection
      id='api-accounts'
      title='Connected accounts'
      description='What each account allows, capability by capability. Open a chip to see the evidence and when it was checked.'
      action={
        <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'sm' }) + ' min-h-10 px-3.5'}>
          Open Channels
        </Link>
      }
      material='none'
      data-tour='api-grants'
    >
      {content}
    </SettingsSection>
  );
}
