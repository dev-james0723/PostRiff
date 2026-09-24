'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { levelKey } from '@/components/app/level-badge';
import { StateMessage, Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { POPOVER_ELEVATED } from '@/features/channels/rafii-materials';
import { ApiError } from '@/lib/api/client';
import type { Capability, ChannelView, ProviderView } from '@/lib/api/types';
import { CAPABILITY_CHIPS } from '@/lib/channels/capabilities';
import { channelBadge, isVerified, type ChannelBadge } from '@/lib/channels/state';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { InboxLevelBadge } from './level-badge';
import { commentsReadFor, evidenceSentence, providerFor } from './model';

/** The two capabilities the Inbox depends on, in the Channels page's words. */
const INBOX_CAPABILITIES = CAPABILITY_CHIPS.filter((chip) => chip.key === 'comments_read' || chip.key === 'reply');

/** A connection state as monochrome icon + text (DNA §4.3): the words carry the state, not a colour. */
export function ConnectionNote({ badge, className }: { badge: ChannelBadge; className?: string }) {
  const Icon = badge.status === 'warning' ? Icons.warning : badge.status === 'success' ? Icons.check : Icons.circleDashed;
  return (
    <span className={cn('text-muted-foreground inline-flex items-center gap-1 text-xs', className)}>
      <Icon className='size-3.5 shrink-0' aria-hidden />
      {badge.label}
    </span>
  );
}

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
        <span className='text-foreground font-medium'>{label}</span>
        <InboxLevelBadge level={capability?.level ?? 'Unsupported'} />
      </div>
      <p className='text-muted-foreground text-xs leading-relaxed'>{meaning}</p>
      <p className='text-foreground text-xs leading-relaxed'>{sentence}</p>
      <p className='text-muted-foreground text-xs'>Verified: {capability?.verifiedAt ? formatDateTime(capability.verifiedAt) : 'not verified yet'}</p>
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
    'rafii-focus inline-flex min-h-9 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap transition-colors',
    'bg-foreground/5 hover:bg-foreground/10',
    levelKey(level) === 'unsupported' ? 'text-muted-foreground hover:text-foreground' : 'text-foreground'
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
      <HoverCardContent align='start' className={cn(POPOVER_ELEVATED, 'w-72')}>
        {content}
      </HoverCardContent>
    </HoverCard>
  ) : (
    <Popover>
      <PopoverTrigger aria-label={ariaLabel} className={triggerClass}>
        {face}
      </PopoverTrigger>
      <PopoverContent align='start' className={cn(POPOVER_ELEVATED, 'w-72')}>
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
    body = <StateMessage kind='loading' layout='inline' title='Loading accounts…' />;
  } else if (!channels) {
    body = (
      <StateMessage
        kind='error'
        layout='inline'
        title={`Account coverage unavailable${error instanceof ApiError ? `: ${error.message}` : '.'}`}
        action={
          <Button variant='glass' size='control' onClick={onRetry}>
            <Icons.refresh className='size-4' />
            Retry
          </Button>
        }
      />
    );
  } else if (channels.length === 0) {
    body = (
      <StateMessage
        kind='empty'
        layout='inline'
        title='No account is connected yet.'
        action={
          <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
            Connect an account
          </Link>
        }
      />
    );
  } else {
    body = channels.map((channel) => {
      const provider = providerFor(channel.platform, providers);
      const badge = isVerified(channel) ? null : channelBadge(channel);
      return (
        <Surface as='li' key={channel.id} material='quiet' radius='control' padding='none' className='flex max-w-full min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1.5 px-3 py-2'>
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
          {badge && <ConnectionNote badge={badge} />}
          {channel.capabilities.comments_read?.level === 'Direct' && !commentsReadFor(channel.platform, providers) && (
            <span className='text-muted-foreground text-xs'>{channel.platform} comments are not read in this release</span>
          )}
        </Surface>
      );
    });
  }

  return (
    <section aria-label='Accounts that feed this inbox' data-tour='inbox-coverage' className='flex flex-col gap-2'>
      <div className='flex items-center justify-between gap-2'>
        <h2 className='rafii-eyebrow'>Accounts feeding this inbox</h2>
        {channels && channels.length > 0 && (
          <Link
            href='/app/channels'
            className='t-learn rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-8 items-center gap-0.5 rounded-md text-xs'
          >
            Manage channels
            <LearnMoreChevron />
          </Link>
        )}
      </div>
      {isPending || !channels || channels.length === 0 ? <div className='flex flex-wrap gap-2'>{body}</div> : <ul className='flex flex-wrap gap-2'>{body}</ul>}
    </section>
  );
}
