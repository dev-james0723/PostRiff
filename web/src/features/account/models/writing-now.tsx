'use client';

import { Icons } from '@/components/icons';
import { TextScramble } from '@/components/motion/text-scramble';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useUsage } from '@/lib/api/hooks';
import type { AgentInfo, ModelOption } from '@/lib/api/types';
import { shortLabel } from '@/features/agent/use-model';
import { formatNumber } from '@/lib/time';
import { KIND_LABEL, costCopy, routeKind } from './catalog';

/** Writing batches left, read from Usage only when the current writer is metered. */
function BatchesLeft() {
  const usage = useUsage();
  if (usage.isLoading) return <span aria-hidden className='t-skel-pulse bg-muted rounded-md inline-block h-4 w-24 align-middle' />;
  const remaining = usage.data?.entitlement?.writingBatchesRemaining;
  if (typeof remaining !== 'number') return <span>Writing batches left: unavailable</span>;
  return (
    <span>
      {formatNumber(remaining)} writing batch{remaining === 1 ? '' : 'es'} left this period
    </span>
  );
}

export interface WritingNowProps {
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  options: ModelOption[];
  agents: AgentInfo[];
  model: string;
  option: ModelOption | undefined;
  saved: string | null;
  /** True once the person picked a writer on this page, so the label scrambles only then. */
  picked: boolean;
}

export function WritingNow({ loading, error, onRetry, options, agents, model, option, saved, picked }: WritingNowProps) {
  const body = () => {
    if (loading) {
      return (
        <div className='flex flex-col gap-2'>
          <Skeleton className='h-7 w-56' />
          <Skeleton className='h-4 w-72 max-w-full' />
        </div>
      );
    }
    if (error && options.length === 0) {
      return (
        <div className='flex flex-wrap items-center justify-between gap-3'>
          <div className='flex flex-col gap-0.5'>
            <span className='text-lg font-semibold'>Unavailable</span>
            <span className='text-muted-foreground text-sm'>The writer list could not be loaded, so this page cannot say which writer Home will use.</span>
          </div>
          <Button variant='outline' size='sm' onClick={onRetry}>
            <Icons.refresh className='size-3.5' /> Retry
          </Button>
        </div>
      );
    }
    if (!option) {
      return (
        <div className='flex flex-col gap-0.5'>
          <span className='text-lg font-semibold'>No writer listed</span>
          <span className='text-muted-foreground text-sm'>This deployment returned no writers. Drafting cannot start until one is listed.</span>
        </div>
      );
    }

    const kind = routeKind(option, agents);
    const cost = costCopy(option.costClass);
    const savedOption = saved ? options.find((m) => m.id === saved) : undefined;
    const fellBack = Boolean(saved) && saved !== model;

    return (
      <div className='flex flex-col gap-2'>
        <div className='flex flex-wrap items-center gap-2'>
          <TextScramble text={shortLabel(option, model)} animate={picked} className='font-mono text-lg font-semibold break-all' />
          <Badge variant='outline'>{KIND_LABEL[kind]}</Badge>
          {!option.qualified && (
            <Badge variant='outline' className='border-amber-500/40 text-amber-700 dark:text-amber-300'>
              Not available
            </Badge>
          )}
        </div>
        <p className='text-muted-foreground flex flex-wrap gap-x-2 text-sm'>
          <span>{option.costClass === 'none' ? 'No model request · $0' : option.costClass === 'subscription' ? 'Your CLI subscription pays · PostRiff records $0' : cost.line}</span>
          {option.costClass === 'paid' && (
            <>
              <span aria-hidden>·</span>
              <BatchesLeft />
            </>
          )}
        </p>
        {!option.qualified && <p className='text-sm text-amber-700 dark:text-amber-300'>{option.detail}</p>}
        {fellBack && saved && (
          <p className='flex items-start gap-2 text-sm text-amber-700 dark:text-amber-300'>
            <Icons.warning className='mt-0.5 size-4 shrink-0' />
            <span>
              Your saved choice ({shortLabel(savedOption, saved)}) is unavailable here; using {shortLabel(option, model)} instead.{' '}
              {savedOption ? `The server says: ${savedOption.detail}` : 'This deployment does not list it.'}
            </span>
          </p>
        )}
        <p className='text-muted-foreground text-xs'>Used by Home and every conversation. Saved in this browser only, so another browser or device can have a different writer.</p>
      </div>
    );
  };

  return (
    <Card data-tour='models-current'>
      <CardContent className='flex flex-col gap-2'>
        <h2 className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>
          Writing now
        </h2>
        {body()}
      </CardContent>
    </Card>
  );
}
