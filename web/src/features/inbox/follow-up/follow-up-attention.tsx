'use client';

import Link from 'next/link';
import { useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { AttentionItem } from '@/lib/coworker/types';
import { safeAppHref } from '@/lib/coworker/safe-href';
import { errorCode, errorMessage } from '@/lib/growth-v2/request';
import { useRelationshipChange } from '@/lib/growth-v2/relationships-hooks';
import { isConflict, platformName, replyRouteView } from '@/lib/growth-v2/relationships-model';
import type { FollowUpAttentionContext } from '@/lib/growth-v2/relationships-types';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { replyStatusView } from '../model';
import { currentCopy, when } from './copy';

function contextOf(item: AttentionItem): FollowUpAttentionContext | null {
  const value = (item as AttentionItem & { context?: unknown }).context;
  if (!value || typeof value !== 'object') return null;
  const context = value as Partial<FollowUpAttentionContext>;
  return typeof context.relationshipId === 'string' && typeof context.revision === 'number' ? (context as FollowUpAttentionContext) : null;
}

/**
 * A due follow-up in "What needs my attention": the prior exchange, why it is here, one action (open it in the Inbox,
 * where replying keeps its exact approval) and "Not relevant", which quiets this reminder until its due time changes
 * (Undo restores it). A reminder never contacts anyone.
 */
export function FollowUpAttentionItem({ item }: { item: AttentionItem }) {
  const copy = currentCopy();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const change = useRelationshipChange();
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const context = contextOf(item);
  const route = replyRouteView(context?.replyRoute, copy);

  async function dismiss() {
    if (!context) return;
    setPending(true);
    setProblem(null);
    try {
      const result = await change((api, w) => api.dismissFollowUp(w, context.relationshipId, context.revision));
      toast(copy.dismissedToast, {
        action: {
          label: copy.undo,
          onClick: () => void change((api, w) => api.restoreFollowUp(w, context.relationshipId, result.relationship.revision)).catch((error) => toast.error(errorMessage(error, copy.failed)))
        }
      });
    } catch (error) {
      setProblem(isConflict(errorCode(error)) ? copy.conflict : errorMessage(error, copy.failed));
    } finally {
      setPending(false);
    }
  }

  return (
    <li data-attention-type={item.type} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4'>
      <div className='flex min-w-0 items-start gap-3'>
        <span aria-hidden className='text-muted-foreground mt-0.5 flex shrink-0'>
          <Icons.clock className='size-4' />
        </span>
        <div className='flex min-w-0 flex-col gap-1'>
          <p className='text-foreground text-sm font-medium text-balance'>{item.title}</p>
          {item.why && <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{item.why}</p>}
          {context?.nextAction && <p className='text-sm break-words'>{copy.nextAction}: {context.nextAction}</p>}
          {context?.due && <p className='text-muted-foreground text-xs'>{copy.due}: {when(context.due.at, context.due.timeZone)} ({context.due.timeZone})</p>}
        </div>
      </div>
      {context && context.exchange.length > 0 && (
        <ol aria-label={copy.linkedConversations} className='flex flex-col gap-1.5 text-sm'>
          {context.exchange.map((entry, index) => (
            <li key={`${entry.direction}-${index}`} className={cn('rounded-[var(--rafii-radius-control)] px-3 py-2', entry.direction === 'inbound' ? 'rafii-glass' : 'bg-foreground/5')}>
              <span className='text-muted-foreground block text-xs'>
                {entry.direction === 'inbound'
                  ? `@${(entry.author ?? '').replace(/^@/, '') || '—'} · ${platformName(entry.provider)}`
                  : replyStatusView(entry.status ?? 'draft').label}
                {entry.at ? ` · ${relativeTime(entry.at)}` : ''}
              </span>
              <span className='break-words'>{entry.excerpt || '—'}</span>
            </li>
          ))}
        </ol>
      )}
      {problem && <p role='alert' className='text-destructive text-sm'>{problem}</p>}
      <div className='flex flex-wrap items-center gap-2'>
        <Link href={safeAppHref(item.href)} className={cn(buttonVariants({ variant: 'glass', size: 'default' }), 'min-h-11 w-fit shrink-0 px-3')}>
          {copy.section}
        </Link>
        {canEdit && context && (
          <Button variant='quiet' size='sm' className='min-h-11' disabled={pending} onClick={() => void dismiss()}>
            {copy.notRelevant}
          </Button>
        )}
        {route.kind === 'assisted' && <span className='text-muted-foreground text-xs'>{route.hint}</span>}
      </div>
    </li>
  );
}
