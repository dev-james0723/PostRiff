'use client';

import Link from 'next/link';
import { useState, type ReactNode } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import type { UseQueryResult } from '@tanstack/react-query';
import { NumberTicker } from '@/components/motion/number-ticker';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usd } from '@/lib/api/client';
import type { ChannelView, Member, Membership, ProviderView, Usage } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { cn } from '@/lib/utils';
import { budgetStatusLabel, resetText } from './billing-copy';
import {
  activeMemberCount,
  allowanceTotal,
  connectedAccountCount,
  costGuardState,
  currentTerms,
  meterState,
  planTimeline,
  type MeterMode,
  type MeterState
} from './billing-model';

/**
 * Motion budget (docs/postriff-motion-system.md §5.4): 40ms stagger (`--duration-stagger`) and the
 * whole sequence within 300ms. The four meter bars start 0, 40, 80 and 120ms in, so each draws in
 * 180ms and the last one still lands by 300ms. The cost guard is its own panel and starts at 0.
 */
const STAGGER_S = 0.04;
const SEQUENCE_S = 0.3;
const METER_BARS = 4;
const BAR_S = Math.round((SEQUENCE_S - (METER_BARS - 1) * STAGGER_S) * 1000) / 1000;

function Bar({ fill, warn, index, label, valueText }: { fill: number; warn: boolean; index: number; label: string; valueText: string }) {
  const reduce = useReducedMotion();
  // Only the first draw is staggered; a refetch that changes a value moves the bar at once.
  const [entered, setEntered] = useState(false);
  const delay = entered ? 0 : Math.min(index, METER_BARS - 1) * STAGGER_S;
  return (
    <div
      role='progressbar'
      aria-label={label}
      aria-valuenow={Math.round(fill * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={valueText}
      className='bg-muted h-2 w-full overflow-hidden rounded-full'
    >
      {/* Full-width fill slid in from the left (transform only), so its rounded end keeps its shape. */}
      <motion.div
        className={cn('h-full w-full rounded-full', warn ? 'bg-amber-500' : 'bg-primary')}
        initial={reduce ? false : { x: '-100%' }}
        animate={{ x: `${fill * 100 - 100}%` }}
        transition={reduce ? { duration: 0 } : { duration: BAR_S, ease: EASE_OUT, delay }}
        onAnimationComplete={() => setEntered(true)}
      />
    </div>
  );
}

function Meter({
  label,
  state,
  index,
  onRetry,
  over
}: {
  label: string;
  state: MeterState;
  index: number;
  onRetry?: () => void;
  /** The reminder for a seat-style allowance in use above the plan's number. */
  over?: ReactNode;
}) {
  let reading: ReactNode;
  switch (state.kind) {
    case 'pending':
      reading = <Skeleton className='h-4 w-20' />;
      break;
    case 'unavailable':
      reading = (
        <span className='inline-flex items-center gap-2'>
          <span>Unavailable</span>
          {onRetry && (
            <Button variant='link' size='xs' className='h-auto p-0' onClick={onRetry}>
              Retry
            </Button>
          )}
        </span>
      );
      break;
    case 'not_included':
      reading = <span>Not included in this plan{state.value ? ` · ${state.value.toLocaleString()} in use` : ''}</span>;
      break;
    case 'no_total':
      reading = <span>{state.value.toLocaleString()} · plan total unavailable</span>;
      break;
    case 'measured':
      reading = (
        <span className='inline-flex items-center gap-1'>
          <NumberTicker
            value={state.value}
            locale
            duration={BAR_S}
            stagger={STAGGER_S}
            className={cn(state.warn && 'text-amber-700 dark:text-amber-300')}
          />
          <span>{state.mode === 'remaining' ? `left of ${state.total.toLocaleString()}` : `of ${state.total.toLocaleString()}`}</span>
        </span>
      );
      break;
  }

  return (
    <div className='flex flex-col gap-1.5'>
      <div className='flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-sm'>
        <span>{label}</span>
        <span className='text-muted-foreground tabular-nums'>{reading}</span>
      </div>
      {state.kind === 'pending' && <Skeleton className='h-2 w-full rounded-full' />}
      {state.kind === 'measured' && (
        <Bar
          fill={state.fill}
          warn={state.warn}
          index={index}
          label={label}
          valueText={state.mode === 'remaining' ? `${state.value} left of ${state.total}` : `${state.value} of ${state.total}`}
        />
      )}
      {state.kind === 'measured' && state.over && over}
    </div>
  );
}

function CostGuard({ budget }: { budget: NonNullable<Usage['budget']> }) {
  const guard = costGuardState(budget);
  return (
    <div className='flex flex-col gap-2 rounded-lg border p-3 text-sm' data-tour='billing-cost-guard'>
      <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5'>
        <span className='font-medium'>Model spend this {budget.windowKind}</span>
        <span className='tabular-nums'>
          {usd(budget.spentUsdMicro)} <span className='text-muted-foreground'>of {usd(budget.stopUsdMicro)}</span>
        </span>
      </div>
      {budget.stopUsdMicro > 0 && (
        <Bar
          fill={guard.fill}
          warn={guard.warn}
          index={0}
          label='Model spend against the ceiling'
          valueText={`${usd(guard.committed)} spent or reserved of ${usd(budget.stopUsdMicro)}`}
        />
      )}
      <p className='text-muted-foreground text-xs'>
        Reserved {usd(budget.reservedUsdMicro)} · {budgetStatusLabel(budget.status)}. Requests are refused before the ceiling would be crossed, never
        charged after.
      </p>
    </div>
  );
}

export function Allowances({
  usage,
  channels,
  members,
  isOwner,
  now
}: {
  usage: Usage;
  channels: UseQueryResult<{ channels: ChannelView[]; providers: ProviderView[] }>;
  members: UseQueryResult<{ members: Member[]; membership: Membership }>;
  isOwner: boolean;
  now: number;
}) {
  const terms = currentTerms(usage);
  const ent = usage.entitlement;

  const meters: { label: string; mode: MeterMode; state: MeterState; onRetry?: () => void; over?: ReactNode }[] = [
    {
      label: 'AI writing batches',
      mode: 'remaining',
      state: meterState({ mode: 'remaining', value: ent.writingBatchesRemaining, total: allowanceTotal(terms, 'writingBatches') })
    },
    {
      label: 'Media credits',
      mode: 'remaining',
      state: meterState({ mode: 'remaining', value: ent.mediaCreditsRemaining, total: allowanceTotal(terms, 'mediaCredits') })
    },
    {
      label: 'Connected accounts',
      mode: 'used',
      state: meterState({
        mode: 'used',
        value: channels.data ? connectedAccountCount(channels.data.channels) : null,
        total: ent.connectedAccounts,
        pending: channels.isPending,
        error: channels.isError && !channels.data
      }),
      onRetry: () => void channels.refetch(),
      over: (
        <p className='text-xs text-amber-700 dark:text-amber-300'>
          Above this plan&apos;s {ent.connectedAccounts}. Remove an account or change plan before connecting another.{' '}
          <Link href='/app/channels' className='underline underline-offset-2'>
            Channels
          </Link>
        </p>
      )
    },
    {
      label: 'Members',
      mode: 'used',
      state: meterState({
        mode: 'used',
        value: members.data ? activeMemberCount(members.data.members) : null,
        total: ent.members,
        pending: members.isPending,
        error: members.isError && !members.data
      }),
      onRetry: () => void members.refetch(),
      over: <p className='text-xs text-amber-700 dark:text-amber-300'>Above this plan&apos;s {ent.members}. Existing members stay; new joins require an available seat.</p>
    }
  ];

  return (
    <Card className='lg:col-span-2' data-tour='billing-allowances'>
      <CardHeader>
        <CardDescription>This period</CardDescription>
        <CardTitle>Allowances</CardTitle>
        <CardDescription>{resetText(planTimeline(usage, now), ent.resetsAt)}</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        {meters.map((meter, index) => (
          <Meter key={meter.label} label={meter.label} state={meter.state} index={index} onRetry={meter.onRetry} over={meter.over} />
        ))}
        <div className='flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-sm'>
          <span>Storage</span>
          <span className='text-muted-foreground'>{ent.storageMb.toLocaleString()} MB included · usage is not measured yet</span>
        </div>
        {isOwner && usage.budget && <CostGuard budget={usage.budget} />}
      </CardContent>
      {usage.overage === 'stop' && (
        <CardFooter>
          <p className='text-muted-foreground text-xs'>When an allowance runs out, paid drafting stops and tells you. Nothing is charged silently.</p>
        </CardFooter>
      )}
    </Card>
  );
}
