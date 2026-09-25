'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import type { Usage } from '@/lib/api/types';
import type { ChannelCounts } from '@/lib/channels/state';
import { cn } from '@/lib/utils';

function Stat({ value, label, icon, className }: { value: number; label: string; icon?: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-baseline gap-1', className)}>
      {icon}
      <DigitSwap value={value} className='text-foreground font-medium tabular-nums' />
      <span>{label}</span>
    </span>
  );
}

function Dot() {
  return (
    <span aria-hidden className='text-muted-foreground/60'>
      ·
    </span>
  );
}

/**
 * One line of real numbers: accounts (against the plan limit when `/usage` answered) and, only when
 * non-zero, how many need attention. Direct and Assisted counts live on the filter tabs, so they are
 * not repeated here. While usage is loading or failed the limit is absent rather than a guessed zero.
 * Monochrome: attention is carried by the count, its icon and the words (DNA §4.3).
 */
export function ChannelsSummary({
  counts,
  providersCount,
  usage,
  ...rest
}: {
  counts: ChannelCounts;
  providersCount: number;
  /** `undefined` while loading or on error: the quota segment is then hidden. */
  usage: Usage | undefined;
  'data-tour'?: string;
}) {
  const limit = usage?.entitlement.connectedAccounts;
  const atLimit = typeof limit === 'number' && limit > 0 && counts.connected >= limit;

  if (counts.connected === 0) {
    return (
      <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm' {...rest}>
        <Stat value={providersCount} label={providersCount === 1 ? 'platform available' : 'platforms available'} />
      </p>
    );
  }

  return (
    <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm' {...rest}>
      {typeof limit === 'number' ? (
        <span className='inline-flex items-baseline gap-1'>
          <DigitSwap value={counts.connected} className='text-foreground font-medium tabular-nums' />
          <span>of {limit} accounts</span>
        </span>
      ) : (
        <Stat value={counts.connected} label='connected' />
      )}
      {atLimit && (
        <>
          <Dot />
          <Link href='/app/account/billing' className='rafii-focus text-foreground rounded-sm underline underline-offset-2'>
            Upgrade for more
          </Link>
        </>
      )}
      {counts.attention > 0 && (
        <>
          <Dot />
          <Stat
            value={counts.attention}
            label={counts.attention === 1 ? 'needs attention' : 'need attention'}
            icon={<Icons.warning className='size-3.5 self-center' aria-hidden />}
            className='text-foreground'
          />
        </>
      )}
    </p>
  );
}
