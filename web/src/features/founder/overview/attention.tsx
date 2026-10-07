'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { formatRelative } from '@/features/founder/shared/format';
import { founderSafeHref } from '@/features/founder/shared/safe-href';
import { describeFounderError } from '@/lib/founder/errors';
import type { AttentionAction, AttentionSeverity, NormalizedAttentionItem } from '@/lib/founder/types';
import { cn } from '@/lib/utils';

/**
 * Attention (PRD §5.2 C): at most five rule-generated decisions with severity, scope, duration and one next step
 * each. Explain and Draft reminder open Rafii with the item's context; Open follows the item's founder link; Ack
 * acknowledges one exact incident version through the API and never marks anything resolved. Items arrive
 * normalised (`lib/founder/attention.ts`): every action is an object and an ack always names incident + version.
 */

type AttentionItem = NormalizedAttentionItem;

/** Demo incidents belong to the Demo dataset; the server refuses a Demo ack rather than writing it to the live store. */
export const DEMO_ACK_REASON = 'Demo incidents are acknowledged through the Demo workspace, not the live store';

const SEVERITY: Record<AttentionSeverity, { icon: keyof typeof Icons; status: 'danger' | 'warning' | 'info'; label: string }> = {
  critical: { icon: 'alertCircle', status: 'danger', label: 'Critical' },
  warning: { icon: 'warning', status: 'warning', label: 'Warning' },
  info: { icon: 'info', status: 'info', label: 'Info' }
};

export type AskAttention = (item: AttentionItem, action: AttentionAction) => void;

function ActionButton({ item, action, onAsk, onAck, busy, demo }: { item: AttentionItem; action: AttentionAction; onAsk: AskAttention; onAck: (action: AttentionAction) => void; busy: boolean; demo: boolean }) {
  if (action.kind === 'open') {
    const href = founderSafeHref(action.href ?? item.href);
    return href ? (
      <Link href={href} className={cn(buttonVariants({ variant: 'glass', size: 'sm' }), 'gap-1.5')}>
        {action.label}
        <Icons.arrowRight className='size-3.5' aria-hidden />
      </Link>
    ) : null;
  }
  if (action.kind === 'ack') {
    const bound = typeof action.incidentId === 'string' && typeof action.version === 'number';
    return (
      <Button type='button' variant='glass' size='sm' disabled={busy || !bound || demo} title={demo ? DEMO_ACK_REASON : bound ? `Acknowledge version ${action.version}` : 'This incident has no version to acknowledge'} onClick={() => onAck(action)} className='gap-1.5'>
        <Icons.check className='size-3.5' aria-hidden /> {action.label}
      </Button>
    );
  }
  return (
    <Button type='button' variant='glass' size='sm' onClick={() => onAsk(item, action)} className='gap-1.5'>
      <Icons.sparkles className='size-3.5' aria-hidden /> {action.label}
    </Button>
  );
}

function AttentionRow({ item, onAsk }: { item: AttentionItem; onAsk: AskAttention }) {
  const { api, mode, environment } = useFounderSession();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const ack = useMutation({
    mutationFn: (action: AttentionAction) => {
      if (typeof action.incidentId !== 'string' || typeof action.version !== 'number') throw new Error('This incident has no version to acknowledge.');
      return api.ackIncident(action.incidentId, action.version, mode);
    },
    onMutate: () => setError(null),
    onError: (failure) => setError(describeFounderError(failure)),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['founder', mode, environment ?? 'unknown'] })
  });
  const severity = SEVERITY[item.severity] ?? SEVERITY.info;
  const Icon = Icons[severity.icon];
  const href = founderSafeHref(item.href);
  return (
    <li data-attention-id={item.id} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4'>
      <div className='flex items-start gap-3'>
        <span aria-hidden className={cn('mt-0.5 flex shrink-0 items-center', item.severity === 'info' ? 'text-muted-foreground' : 'text-foreground')}>
          <Icon className='size-4' />
        </span>
        <div className='flex min-w-0 flex-1 flex-col gap-1'>
          <p className='text-foreground text-sm font-medium text-balance'>
            <span className='sr-only'>{severity.label}: </span>
            {href ? (
              <Link href={href} className='rafii-focus rounded-sm hover:underline'>
                {item.title}
              </Link>
            ) : (
              item.title
            )}
          </p>
          <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs'>
            <StatusChip status={severity.status} className='h-6 px-2 text-[11px]'>
              {severity.label}
            </StatusChip>
            <span>{item.scope}</span>
            {typeof item.count === 'number' && <span className='tabular-nums'>· {item.count.toLocaleString()} affected</span>}
            {item.since && <span>· since {formatRelative(item.since)}</span>}
          </p>
        </div>
      </div>
      {item.actions.length > 0 && (
        <div className='flex flex-wrap gap-2'>
          {item.actions.map((action) => (
            <ActionButton key={action.id} item={item} action={action} onAsk={onAsk} onAck={(target) => ack.mutate(target)} busy={ack.isPending} demo={mode === 'demo'} />
          ))}
        </div>
      )}
      {error && (
        <p role='alert' className='text-destructive text-xs'>
          {error}
        </p>
      )}
    </li>
  );
}

export function AttentionPanel({ items, onAsk, className }: { items: AttentionItem[]; onAsk: AskAttention; className?: string }) {
  return (
    <Panel className={className} title='Needs your attention' titleId='founder-attention-heading' description='Open incidents, cost anomalies, payment failures, quota exhaustion and stale sources, from rules, not a score.' data-tour='founder-attention'>
      {items.length === 0 ? (
        <StateMessage kind='success' layout='inline' title='All clear' description='No rule has fired. Stale sources would be listed here first.' />
      ) : (
        <ul className='flex flex-col gap-2' aria-label='Needs your attention'>
          {items.slice(0, 5).map((item) => (
            <AttentionRow key={item.id} item={item} onAsk={onAsk} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
