'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useCoworkerAttention } from '@/lib/coworker/hooks';
import type { AttentionItem } from '@/lib/coworker/types';
import { safeAppHref } from '@/lib/coworker/safe-href';
import { useRelationshipChange } from '@/lib/growth-v2/relationships-hooks';
import { platformName, replyRouteView, replyStatusLabel } from '@/lib/growth-v2/relationships-model';
import type { FollowUpAttentionContext } from '@/lib/growth-v2/relationships-types';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { currentCopy, currentLang, describeProblem, when, type FollowUpProblem } from './copy';

function contextOf(item: AttentionItem): FollowUpAttentionContext | null {
  const value = (item as AttentionItem & { context?: unknown }).context;
  if (!value || typeof value !== 'object') return null;
  const context = value as Partial<FollowUpAttentionContext>;
  return typeof context.relationshipId === 'string' && typeof context.revision === 'number' ? (context as FollowUpAttentionContext) : null;
}

/**
 * An Undo the attention list keeps showing after the item it belongs to has left the list. `run` restores the reminder
 * once: called again (from the list and its toast both) it answers with that same request, never a second one.
 */
export interface AttentionUndo {
  message: string;
  run: () => Promise<unknown>;
}

/** The first call starts `task`; later calls share its answer. A failed attempt can be tried again. */
export function once(task: () => Promise<unknown>): () => Promise<unknown> {
  let started: Promise<unknown> | null = null;
  return () => {
    started ??= task().catch((error: unknown) => {
      started = null;
      throw error;
    });
    return started;
  };
}

/**
 * A due follow-up in "What needs my attention": the prior exchange, why it is here, one action (open it in the Inbox,
 * where replying keeps its exact approval) and "Not relevant", which quiets this reminder until its due time changes.
 * The item then leaves the list, so its Undo is handed to the list (`onUndoable`), which owns it — the in-place offer
 * and the toast are one Undo, cleared together. A reminder never contacts anyone.
 */
export function FollowUpAttentionItem({ item, onUndoable }: { item: AttentionItem; onUndoable: (undo: AttentionUndo) => void }) {
  const copy = currentCopy();
  const lang = currentLang();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const change = useRelationshipChange();
  const attention = useCoworkerAttention();
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<FollowUpProblem | null>(null);
  const context = contextOf(item);
  const route = replyRouteView(context?.replyRoute, copy);

  async function dismiss() {
    if (!context) return;
    setPending(true);
    setProblem(null);
    try {
      const result = await change((api, w) => api.dismissFollowUp(w, context.relationshipId, context.revision));
      onUndoable({
        message: copy.dismissedToast,
        run: once(() => change((api, w) => api.restoreFollowUp(w, context.relationshipId, result.relationship.revision)))
      });
    } catch (error) {
      setProblem(describeProblem(error, copy));
    } finally {
      setPending(false);
    }
  }

  return (
    <li lang={lang} data-attention-type={item.type} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4'>
      <div className='flex min-w-0 items-start gap-3'>
        <span aria-hidden className='text-muted-foreground mt-0.5 flex shrink-0'>
          <Icons.clock className='size-4' />
        </span>
        <div className='flex min-w-0 flex-col gap-1'>
          {/* In the person's language when the follow-up's context came with the item; otherwise the server's English. */}
          {context ? (
            <>
              <p className='text-foreground text-sm font-medium text-balance'>{copy.followUpWith(context.displayName)}</p>
              <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{copy.attentionWhy}</p>
            </>
          ) : (
            <>
              <p lang='en' className='text-foreground text-sm font-medium text-balance'>{item.title}</p>
              {item.why && <p lang='en' className='text-muted-foreground text-sm leading-relaxed text-pretty'>{item.why}</p>}
            </>
          )}
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
                  ? `@${(entry.author ?? '').replace(/^@/, '') || '—'} · ${platformName(entry.provider, copy.thePlatform)}`
                  : replyStatusLabel(entry.status, copy)}
                {entry.at ? ` · ${relativeTime(entry.at)}` : ''}
              </span>
              <span className='break-words'>{entry.excerpt || '—'}</span>
            </li>
          ))}
        </ol>
      )}
      {problem && (
        <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-sm'>
          <span lang={problem.lang}>{problem.message}</span>
          {problem.conflict && (
            <Button variant='quiet' size='sm' className='min-h-11' onClick={() => { setProblem(null); void attention.refetch(); }}>{copy.reload}</Button>
          )}
        </p>
      )}
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
