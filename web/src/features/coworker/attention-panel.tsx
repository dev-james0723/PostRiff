'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { Panel } from '@/features/workspace/rafii-parts';
import { isFeatureDisabled } from '@/lib/coworker/api';
import { useCoworkerAttention } from '@/lib/coworker/hooks';
import { safeAppHref } from '@/lib/coworker/safe-href';
import { cn } from '@/lib/utils';
import { eventLabel } from './notifications/labels';

const ACTION: Record<string, string> = {
  'publish.failed': 'Open the post',
  'publish.uncertain': 'Check the post',
  'channel.reconnect_required': 'Reconnect',
  'billing.payment_failed': 'Update payment',
  'campaign.approval_required': 'Review and approve',
  'campaign.blocked': 'See what’s needed',
  'campaign.week_ready': 'Review next week',
  'campaign.drafts_ready': 'Review drafts',
  'asset.review_required': 'Review the image',
  'budget.threshold_reached': 'See usage',
  'billing.trial_ending': 'Choose a plan',
  'engagement.needs_attention': 'Open Inbox',
  'learning.preference_proposed': 'Review the preference',
  'opportunity.detected': 'See the opportunity'
};

/** The server falls back to the event name as a title ("Campaign week ready"); say it in words instead. */
function titleOf(item: { type: string; title: string }) {
  const generated = item.type.replace('.', ' ').replace(/_/g, ' ').toLowerCase();
  return !item.title || item.title.toLowerCase() === generated ? eventLabel(item.type) : item.title;
}

/**
 * “What needs my attention?” (coworker spec §12, §19): Rafii's ordered list from the workspace's authoritative
 * state, each item with why it matters and one link. Hidden when the deployment has no coworker routes; nothing
 * is shown while there is nothing to do (the Overview's own panel already says “All clear”).
 */
export function CoworkerAttention({ className }: { className?: string }) {
  const attention = useCoworkerAttention();
  if (attention.isPending || isFeatureDisabled(attention.error)) return null;
  if (attention.isError && !attention.data) {
    return (
      <Panel className={className} title='What needs my attention' titleId='coworker-attention-heading'>
        <StateMessage kind='partial' layout='inline' title='Rafii’s list is unavailable right now.' description='Approvals and connections above are still read directly from the workspace.' />
      </Panel>
    );
  }
  const items = attention.data?.items ?? [];
  if (items.length === 0) return null;
  const urgent = attention.data?.counts.urgent ?? 0;
  return (
    <Panel
      className={className}
      title='What needs my attention'
      titleId='coworker-attention-heading'
      description={urgent > 0 ? `${urgent} urgent, then the rest in order. Rafii orders these by fixed rules, not by guesswork.` : 'In order of what matters most. Rafii orders these by fixed rules, not by guesswork.'}
    >
      <ol aria-labelledby='coworker-attention-heading' className='flex flex-col gap-2'>
        {items.slice(0, 8).map((item) => (
          <li key={item.id} data-attention-type={item.type} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4 sm:flex-row sm:items-center sm:justify-between'>
            <div className='flex min-w-0 items-start gap-3'>
              <span aria-hidden className={cn('mt-0.5 flex shrink-0', item.urgent ? 'text-foreground' : 'text-muted-foreground')}>
                {item.urgent ? <Icons.warning className='size-4' /> : <Icons.info className='size-4' />}
              </span>
              <div className='flex min-w-0 flex-col gap-1'>
                <p className='text-foreground text-sm font-medium text-balance'>
                  {item.urgent && <span className='mr-1.5 text-xs font-semibold tracking-wide uppercase'>Urgent ·</span>}
                  {titleOf(item)}
                </p>
                {item.why && <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{item.why}</p>}
                {item.detail && <p className='text-muted-foreground text-xs leading-relaxed'>{item.detail}</p>}
              </div>
            </div>
            <Link href={safeAppHref(item.href)} className={cn(buttonVariants({ variant: 'glass', size: 'default' }), 'min-h-11 w-fit shrink-0 px-3')}>
              {ACTION[item.type] ?? 'Open'}
            </Link>
          </li>
        ))}
      </ol>
      {items.length > 8 && <p className='text-muted-foreground text-xs'>{items.length - 8} more lower-priority items.</p>}
    </Panel>
  );
}
