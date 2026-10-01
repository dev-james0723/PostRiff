'use client';

import { Icons } from '@/components/icons';
import { TextScramble } from '@/components/motion/text-scramble';
import { StateMessage, Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useUsage } from '@/lib/api/hooks';
import type { AgentInfo, ModelOption } from '@/lib/api/types';
import { writingAllowance, type WritingAllowance } from '@/lib/billing/mode';
import type { BillingCopy } from '@/lib/billing/mode-copy';
import { modelName, shortLabel } from '@/features/agent/use-model';
import { useBillingCopy, useCopyLocale } from '@/features/billing/use-copy-locale';
import { formatNumber } from '@/lib/time';
import { KIND_LABEL, costCopy, routeKind } from './catalog';

/**
 * What a metered writer draws on, shown only when the current writer is metered and read by billing mode:
 * writing batches left (legacy), managed credits left (Creator), or that Free includes no managed writing.
 */
function AllowanceLeft({ allowance, copy }: { allowance: WritingAllowance; copy: BillingCopy['work'] }) {
  switch (allowance.kind) {
    case 'loading':
      return <span aria-hidden className='t-skel-pulse bg-muted inline-block h-4 w-24 rounded-md align-middle' />;
    case 'batches':
      return (
        <span>
          {formatNumber(allowance.remaining)} writing batch{allowance.remaining === 1 ? '' : 'es'} left
        </span>
      );
    case 'credits':
      return <span>{copy.creditsLeft(formatNumber(allowance.available))}</span>;
    case 'free':
      return <span>{copy.freeNoManaged}</span>;
    default:
      return null;
  }
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
  /** Set when the person follows Auto: whose default `model` is, and why the workspace's was not used. */
  auto?: { source: 'workspace' | 'deployment'; note: string | null } | null;
}

/**
 * The page's one glass work surface (DNA §21.14): the chosen writer and what it costs. A saved writer
 * that is unavailable stays chosen until the person picks another; nothing is substituted for them.
 */
export function WritingNow({ loading, error, onRetry, options, agents, model, option, saved, picked, auto }: WritingNowProps) {
  const allowance = writingAllowance(useUsage());
  const locale = useCopyLocale();
  const workCopy = useBillingCopy().work;
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
          title='Couldn’t load writers'
          action={
            <Button variant='glass' size='sm' className='min-h-9' onClick={onRetry}>
              <Icons.refresh className='size-3.5' /> Retry
            </Button>
          }
        />
      );
    }
    if (!option && saved && options.length > 0) {
      return <StateMessage kind='stale' layout='inline' title={`${shortLabel(undefined, saved)} isn’t available`} description='Drafting waits until you choose another writer below. Nothing is switched for you.' />;
    }
    if (!option) {
      return <StateMessage kind='empty' layout='inline' title='No writer available' description='Drafting can’t start until one is. Try Check again.' />;
    }

    const kind = routeKind(option, agents);
    const cost = costCopy(option.costClass, allowance, locale);

    return (
      <div className='flex flex-col gap-2'>
        <div className='flex flex-wrap items-center gap-2'>
          <TextScramble text={auto ? `Auto · ${modelName(option, model)}` : shortLabel(option, model)} animate={picked} className='text-foreground font-mono text-lg font-semibold break-all' />
          <Badge variant='secondary'>{KIND_LABEL[kind]}</Badge>
          {!option.qualified && <Badge variant='secondary'>Not available</Badge>}
        </div>
        {auto && (
          <p className='text-muted-foreground text-sm'>
            {auto.source === 'workspace' ? 'The workspace default, set by an owner.' : 'Rafii’s default writer: this workspace has no default of its own.'}
            {auto.note ? ` ${auto.note}` : ''}
          </p>
        )}
        <p className='text-muted-foreground flex flex-wrap gap-x-2 text-sm'>
          <span>{option.costClass === 'none' ? 'Free' : option.costClass === 'subscription' ? 'Paid by your CLI subscription' : cost.line}</span>
          {option.costClass === 'paid' && <AllowanceLeft allowance={allowance} copy={workCopy} />}
        </p>
        {!option.qualified && <StateMessage kind='unsupported' layout='inline' title={option.detail} description='Drafting waits until you choose another writer below. Nothing is switched for you.' />}
        <p className='text-muted-foreground text-xs leading-relaxed'>Your pick is saved in this browser. Auto follows the workspace default.</p>
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
