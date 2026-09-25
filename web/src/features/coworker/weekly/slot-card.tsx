'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { errorMessage } from '@/lib/coworker/api';
import type { useSlotAction } from '@/lib/coworker/hooks';
import { queueDraftHref } from '@/lib/coworker/safe-href';
import type { Slot, SlotAction } from '@/lib/coworker/types';
import { cn } from '@/lib/utils';
import { humanize, isStalled, plainFindings, slotStatus, timeLabel } from '../present';
import { ToneChip } from '../parts';

const ACCEPTABLE = new Set(['ready', 'needs_revision', 'needs_asset']);
const REDOABLE = new Set(['ready', 'needs_revision', 'needs_asset', 'needs_input']);
const SKIPPABLE = new Set(['planned', 'ready', 'needs_revision', 'needs_asset', 'needs_input', 'needs_source', 'channel_unavailable', 'drafted']);

/**
 * One planned post as a task: where and when, its state in words, the draft, what the checks found in plain
 * language, and the actions that fit its state. Accept hands the draft to Queue → Drafts; it is not scheduled.
 */
export function SlotCard({ slot, weekState, canEdit, action, highlight }: { slot: Slot; weekState?: string; canEdit: boolean; action: ReturnType<typeof useSlotAction>; highlight?: boolean }) {
  const stalled = isStalled(slot.status, weekState);
  const base = slotStatus(slot.status);
  const meta = stalled ? { ...base, label: 'Not drafted', tone: 'attention' as const, icon: 'pause', hint: 'Rafii can’t draft this while the rest of the week is in review. Skip it, or write it in Ideas.' } : base;
  const findings = plainFindings(slot.quality, slot.platform);
  const blocking = findings.filter((f) => f.blocking);
  const advisory = findings.filter((f) => !f.blocking);
  const [answer, setAnswer] = useState('');
  const [confirmAccept, setConfirmAccept] = useState(false);
  // Focus follows the in-place swap: into the confirmation when it opens, back to Accept when it closes.
  const acceptRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  useEffect(() => {
    if (confirmAccept) confirmRef.current?.focus();
    else if (wasConfirming.current) acceptRef.current?.focus();
    wasConfirming.current = confirmAccept;
  }, [confirmAccept]);
  const [next, setNext] = useState<string | null>(null);
  const answerId = useId();
  const busy = action.isPending && action.variables?.slotId === slot.id;
  const titleId = `slot-${slot.id}-title`;
  const where = [slot.platform, slot.account].filter(Boolean).join(' · ');
  const time = timeLabel(slot.localTime);

  async function run(kind: SlotAction, body: { answer?: string; reason?: string } = {}) {
    try {
      const result = await action.mutateAsync({ slotId: slot.id, action: kind, ...body });
      if (!result.verified) {
        toast.warning('Rafii could not confirm that change. Refresh to see this post’s state.');
        return;
      }
      if (kind === 'accept') {
        setNext(result.next ?? 'Open Queue → Drafts to confirm, review and approve this post.');
        toast.success('Accepted. It is in Queue → Drafts; nothing is scheduled until it is approved there.');
      } else if (kind === 'answer') {
        setAnswer('');
        if (isStalled(result.slot.status, result.week.state)) toast.warning('Answer saved, but Rafii can’t draft this post while the rest of the week is in review. Skip it, or write it in Ideas.');
        else toast.success('Thanks. Rafii drafts this post the next time the week is prepared.');
      } else if (kind === 'redo') {
        toast.success('Rafii will redraft this post the next time the week is prepared.');
      } else if (kind === 'skip') {
        toast.success('Skipped. It is no longer part of this week.');
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setConfirmAccept(false);
    }
  }

  function submitAnswer(event: FormEvent) {
    event.preventDefault();
    if (!answer.trim()) return;
    void run('answer', { answer: answer.trim() });
  }

  const draftText = slot.draft?.text?.trim();
  const plan = slot.creative?.plans?.[0];
  const missing = slot.creative?.missingAssets?.[0];

  return (
    <article
      id={`slot-${slot.id}`}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-slot-status={slot.status}
      className={cn('rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4 outline-none md:p-5', highlight && 'ring-foreground/40 ring-2')}
    >
      <header className='flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between'>
        <div className='flex min-w-0 flex-col gap-0.5'>
          <h4 id={titleId} className='text-foreground text-sm font-medium'>
            {where || 'Account'}
            {time && <span className='text-muted-foreground font-normal'> · {time}</span>}
          </h4>
          <p className='text-muted-foreground text-xs'>
            {humanize(slot.contentType)} · {slot.language} · for “{slot.goal}”
          </p>
        </div>
        <ToneChip tone={meta.tone} icon={meta.icon} className='self-start'>
          {meta.label}
        </ToneChip>
      </header>

      {meta.hint && slot.status !== 'needs_input' && meta.group !== 'handed' && !next && <p className='text-muted-foreground text-sm leading-relaxed'>{slot.reason && meta.group === 'blocked' ? slot.reason : meta.hint}</p>}

      {slot.status === 'needs_input' && (
        <form onSubmit={submitAnswer} className='flex flex-col gap-2'>
          <label htmlFor={answerId} className='text-foreground text-sm font-medium'>
            {slot.question ?? 'Rafii needs a short answer before it can write this post.'}
          </label>
          {slot.reason && <p className='text-muted-foreground text-xs'>{slot.reason}</p>}
          {canEdit ? (
            <>
              <Textarea id={answerId} value={answer} maxLength={600} rows={2} onChange={(e) => setAnswer(e.target.value)} className={TEXTAREA_CLASS} placeholder='One or two sentences is enough.' />
              <div className='flex flex-wrap gap-2'>
                <Button type='submit' variant='action' size='control' disabled={busy || !answer.trim()}>
                  {busy && action.variables?.action === 'answer' ? 'Sending…' : 'Send answer'}
                </Button>
              </div>
            </>
          ) : (
            <p className='text-muted-foreground text-xs'>Someone who can edit this workspace can answer.</p>
          )}
        </form>
      )}

      {slot.status === 'needs_source' && (
        <Link href='/app/library' className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'w-fit')}>
          Add a source in Library
        </Link>
      )}

      {stalled && (
        <Link href='/app/ideas?new=1' className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'w-fit')}>
          Write it in Ideas
        </Link>
      )}

      {slot.status === 'channel_unavailable' && (
        <Link href='/app/channels' className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'w-fit')}>
          Open Channels
        </Link>
      )}

      {draftText && (
        <div className='bg-background/40 rounded-[var(--rafii-radius-control)] p-3'>
          <p className='text-muted-foreground mb-1 text-xs font-medium'>Draft</p>
          <p className='text-foreground text-sm leading-relaxed whitespace-pre-wrap'>{draftText}</p>
        </div>
      )}

      {slot.status === 'needs_asset' && plan && (
        <div className='flex flex-col gap-1 text-sm'>
          <p className='text-foreground font-medium'>Creative brief</p>
          <p className='text-muted-foreground leading-relaxed'>
            {[plan.format && humanize(plan.format), plan.ratio, plan.size].filter(Boolean).join(' · ')}
            {plan.message ? ` — ${plan.message}` : ''}
          </p>
          {(missing?.why || plan.sourceWhy) && <p className='text-muted-foreground text-xs'>{missing?.why ?? plan.sourceWhy}</p>}
          {plan.altText?.draft && <p className='text-muted-foreground text-xs'>Alt text to start from: {plan.altText.draft}</p>}
          <Link href='/app/library' className='rafii-focus text-foreground w-fit rounded-sm text-xs underline underline-offset-4'>
            Add or generate an image in Library
          </Link>
        </div>
      )}

      {findings.length > 0 && (
        <div className='flex flex-col gap-1.5'>
          <p className='text-foreground text-xs font-medium'>What the checks found</p>
          <ul className='flex flex-col gap-1'>
            {[...blocking, ...advisory].map((f, index) => (
              <li key={`${f.kind}-${index}`} className='flex items-start gap-2 text-sm'>
                <span aria-hidden className='mt-0.5 shrink-0'>
                  {f.blocking ? <Icons.warning className='text-foreground size-4' /> : <Icons.info className='text-muted-foreground size-4' />}
                </span>
                <span className='min-w-0'>
                  <span className={f.blocking ? 'text-foreground' : 'text-muted-foreground'}>
                    {f.blocking && <span className='sr-only'>Must fix: </span>}
                    {f.text}
                  </span>
                  {f.detail && <span className='text-muted-foreground block text-xs break-words'>{f.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
          {advisory.length > 0 && blocking.length === 0 && <p className='text-muted-foreground text-xs'>These are notes, not blockers.</p>}
        </div>
      )}

      {(next || meta.group === 'handed') && (
        <p className='text-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm' role={next ? 'status' : undefined}>
          {next ?? meta.hint}
          {slot.variantId && (
            <Link href={queueDraftHref(slot.variantId)} className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
              Open in Queue → Drafts
            </Link>
          )}
        </p>
      )}

      {canEdit && (ACCEPTABLE.has(slot.status) || REDOABLE.has(slot.status) || SKIPPABLE.has(slot.status)) && (
        <div className='flex flex-wrap items-center gap-2 pt-1'>
          {ACCEPTABLE.has(slot.status) && slot.variantId && !confirmAccept && (
            <Button ref={acceptRef} variant='action' size='control' disabled={busy} onClick={() => (blocking.length > 0 ? setConfirmAccept(true) : void run('accept'))}>
              {busy && action.variables?.action === 'accept' ? 'Accepting…' : 'Accept'}
            </Button>
          )}
          {confirmAccept && (
            <span className='flex flex-wrap items-center gap-2' role='group' aria-label='Confirm accepting a post that needs revision'>
              <span id={`${titleId}-warn`} role='alert' className='text-foreground text-sm'>
                The meaning check found something. Accept and fix it in Queue?
              </span>
              <Button ref={confirmRef} variant='action' size='control' disabled={busy} onClick={() => void run('accept')} aria-describedby={`${titleId}-warn`}>
                Accept anyway
              </Button>
              <Button variant='glass' size='control' disabled={busy} onClick={() => setConfirmAccept(false)}>
                Cancel
              </Button>
            </span>
          )}
          {REDOABLE.has(slot.status) && (slot.status !== 'needs_input' || Boolean(slot.reason)) && (
            <Button variant='glass' size='control' disabled={busy} onClick={() => void run('redo')}>
              {busy && action.variables?.action === 'redo' ? 'Redoing…' : slot.status === 'needs_input' ? 'Try again' : 'Redo'}
            </Button>
          )}
          {SKIPPABLE.has(slot.status) && (
            <Button variant='quiet' size='control' disabled={busy} onClick={() => void run('skip', { reason: 'Skipped' })}>
              Skip
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
