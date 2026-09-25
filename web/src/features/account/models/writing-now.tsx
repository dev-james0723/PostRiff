'use client';

import { Icons } from '@/components/icons';
import { TextScramble } from '@/components/motion/text-scramble';
import { StateMessage, Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useUsage } from '@/lib/api/hooks';
import type { AgentInfo, ModelOption } from '@/lib/api/types';
import { shortLabel } from '@/features/agent/use-model';
import { formatNumber } from '@/lib/time';
import { KIND_LABEL, costCopy, routeKind } from './catalog';

/** Writing batches left, read from Usage only when the current writer is metered. */
function BatchesLeft() {
  const usage = useUsage();
  if (usage.isLoading) return <span aria-hidden className='t-skel-pulse bg-muted inline-block h-4 w-24 rounded-md align-middle' />;
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

/**
 * The page's one glass work surface (DNA §21.14): the chosen writer and what it costs. A saved writer
 * that is unavailable stays chosen until the person picks another; nothing is substituted for them.
 */
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
        <StateMessage
          kind='error'
          layout='inline'
          title='Unavailable'
          description='The writer list could not be loaded, so this page cannot say which writer Home will use.'
          action={
            <Button variant='glass' size='sm' className='min-h-9' onClick={onRetry}>
              <Icons.refresh className='size-3.5' /> Retry
            </Button>
          }
        />
      );
    }
    if (!option && saved && options.length > 0) {
      return <StateMessage kind='stale' layout='inline' title={`Your saved writer (${shortLabel(undefined, saved)}) is not offered here`} description='Choose another writer below. Drafting waits until you do; nothing is switched for you.' />;
    }
    if (!option) {
      return <StateMessage kind='empty' layout='inline' title='No writer listed' description='This deployment returned no writers. Drafting cannot start until one is listed.' />;
    }

    const kind = routeKind(option, agents);
    const cost = costCopy(option.costClass);

    return (
      <div className='flex flex-col gap-2'>
        <div className='flex flex-wrap items-center gap-2'>
          <TextScramble text={shortLabel(option, model)} animate={picked} className='text-foreground font-mono text-lg font-semibold break-all' />
          <Badge variant='secondary'>{KIND_LABEL[kind]}</Badge>
          {!option.qualified && <Badge variant='secondary'>Not available</Badge>}
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
        {!option.qualified && <StateMessage kind='unsupported' layout='inline' title={option.detail} description='Choose another writer below. Drafting waits until you do; nothing is switched for you.' />}
        <p className='text-muted-foreground text-xs leading-relaxed'>Used by Home and every conversation. Saved in this browser only, so another browser or device can have a different writer.</p>
      </div>
    );
  };

  return (
    <Surface material='glass' radius='card' padding='md' data-tour='models-current' className='flex flex-col gap-3'>
      <h2 className='rafii-eyebrow'>Writing now</h2>
      {body()}
    </Surface>
  );
}
