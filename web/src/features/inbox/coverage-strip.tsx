'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { levelKey } from '@/components/app/level-badge';
import { Button } from '@/components/ui/button';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import type { Capability, ChannelView, ProviderView } from '@/lib/api/types';
import { CAPABILITY_CHIPS } from '@/lib/channels/capabilities';
import { channelBadge, isVerified } from '@/lib/channels/state';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { InboxLevelBadge } from './level-badge';
import { commentsReadFor, evidenceSentence, providerFor } from './model';

/** The two capabilities the Inbox depends on, in the Channels page's words. */
const INBOX_CAPABILITIES = CAPABILITY_CHIPS.filter((chip) => chip.key === 'comments_read' || chip.key === 'reply');

function Evidence({
  label,
  meaning,
  capability,
  sentence
}: {
  label: string;
  meaning: string;
  capability: Capability | undefined;
  sentence: string;
}) {
  return (
    <div className='flex flex-col gap-2 text-left'>
      <div className='flex items-center justify-between gap-2'>
        <span className='font-medium'>{label}</span>
        <InboxLevelBadge level={capability?.level ?? 'Unsupported'} />
      </div>
      <p className='text-muted-foreground text-xs'>{meaning}</p>
      <p className='text-xs'>{sentence}</p>
      <p className='text-muted-foreground text-[11px]'>
        Verified: {capability?.verifiedAt ? formatDateTime(capability.verifiedAt) : 'not verified yet'}
      </p>
    </div>
  );
}

/** One capability on one account: its level, with the evidence on hover, focus or tap. */
function LevelChip({
  channel,
  chip,
  provider,
  canHover
}: {
  channel: ChannelView;
  chip: (typeof INBOX_CAPABILITIES)[number];
  provider: ProviderView | null;
  canHover: boolean;
}) {
  const capability = channel.capabilities[chip.key];
  const level = capability?.level ?? 'Unsupported';
  const sentence = evidenceSentence(capability, provider?.capabilities[chip.key], channel.platform);
  const ariaLabel = `${chip.label} for ${channel.account}: ${level}. Show evidence`;
  const triggerClass = cn(
    'inline-flex h-7 items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap outline-none transition-colors',
    'focus-visible:ring-ring/50 focus-visible:ring-2',
    levelKey(level) === 'unsupported' ? 'bg-muted text-muted-foreground hover:text-foreground' : 'bg-card hover:bg-accent'
  );
  const face: ReactNode = (
    <>
      {chip.label}
      <InboxLevelBadge level={level} />
    </>
  );
  const content = <Evidence label={chip.label} meaning={chip.meaning} capability={capability} sentence={sentence} />;
  return canHover ? (
    <HoverCard>
      <HoverCardTrigger render={<button type='button' aria-label={ariaLabel} />} delay={80} closeDelay={100} className={triggerClass}>
        {face}
      </HoverCardTrigger>
      <HoverCardContent align='start' className='w-72'>
        {content}
      </HoverCardContent>
    </HoverCard>
  ) : (
    <Popover>
      <PopoverTrigger aria-label={ariaLabel} className={triggerClass}>
        {face}
      </PopoverTrigger>
      <PopoverContent align='start' className='w-72'>
        {content}
      </PopoverContent>
    </Popover>
  );
}

/**
 * Which accounts feed the Inbox: per account, the comments and reply capabilities with their own
 * levels and evidence from `GET /channels`. Never a blended "connected" tick.
 */
export function CoverageStrip({
  channels,
  providers,
  isPending,
  error,
  onRetry
}: {
  channels: ChannelView[] | undefined;
  providers: ProviderView[] | undefined;
  isPending: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  const canHover = useHoverCapable();
  let body: ReactNode;
  if (isPending) {
    body = (
      <>
        <Skeleton className='h-10 w-72 max-w-full rounded-lg' />
        <Skeleton className='h-10 w-60 max-w-full rounded-lg' />
      </>
    );
  } else if (!channels) {
    body = (
      <div role='alert' className='text-muted-foreground flex flex-wrap items-center gap-2 text-sm'>
        <Icons.warning className='size-4 text-amber-600 dark:text-amber-400' />
        <span>Account coverage unavailable{error instanceof ApiError ? `: ${error.message}` : '.'}</span>
        <Button variant='outline' size='sm' onClick={onRetry}>
          <Icons.refresh className='size-3.5' />
          Retry
        </Button>
      </div>
    );
  } else if (channels.length === 0) {
    body = (
      <p className='text-muted-foreground text-sm'>
        No account is connected yet.{' '}
        <Link href='/app/channels' className='text-foreground underline underline-offset-2'>
          Connect an account
        </Link>
      </p>
    );
  } else {
    body = channels.map((channel) => {
      const provider = providerFor(channel.platform, providers);
      const badge = isVerified(channel) ? null : channelBadge(channel);
      return (
        <li key={channel.id} className='bg-card flex max-w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 rounded-lg border px-2.5 py-1.5'>
          <span className='flex min-w-0 items-center gap-1.5 text-sm font-medium'>
            <ChannelIcon platform={channel.platform} name={channel.platform} size='xs' />
            <span className='truncate'>{channel.account}</span>
            <span className='text-muted-foreground sr-only sm:not-sr-only sm:text-xs sm:font-normal'>{channel.platform}</span>
          </span>
          <span className='flex flex-wrap items-center gap-1.5'>
            {INBOX_CAPABILITIES.map((chip) => (
              <LevelChip key={chip.key} channel={channel} chip={chip} provider={provider} canHover={canHover} />
            ))}
          </span>
          {badge && (
            <span className={cn('text-xs', badge.status === 'warning' ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground')}>{badge.label}</span>
          )}
          {channel.capabilities.comments_read?.level === 'Direct' && !commentsReadFor(channel.platform, providers) && (
            <span className='text-muted-foreground text-xs'>{channel.platform} comments are not read in this release</span>
          )}
        </li>
      );
    });
  }

  return (
    <section aria-label='Accounts that feed this inbox' data-tour='inbox-coverage' className='flex flex-col gap-2'>
      <div className='flex items-center justify-between gap-2'>
        <h2 className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>Accounts feeding this inbox</h2>
        {channels && channels.length > 0 && (
          <Link href='/app/channels' className='t-learn text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5 text-xs'>
            Manage channels
            <LearnMoreChevron />
          </Link>
        )}
      </div>
      {isPending || !channels || channels.length === 0 ? (
        <div className='flex flex-wrap gap-2'>{body}</div>
      ) : (
        <ul className='flex flex-wrap gap-2'>{body}</ul>
      )}
    </section>
  );
}
