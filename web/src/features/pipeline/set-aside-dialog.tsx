'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { StatefulButton } from '@/components/motion/button';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/client';
import { keys, useAct, useSnapshot } from '@/lib/api/hooks';
import { useWorkspace } from '@/lib/workspace/provider';
import { useFlash } from '@/hooks/use-flash';
import type { PipelineJob, PipelineVariant } from './board';
import { FAILED, stateWords } from './job-state';

/** `FEEDBACK_REASONS` in `src/postriff_phase2/store.py`, with plain labels. */
export const SET_ASIDE_REASONS: { id: string; label: string }[] = [
  { id: 'wrong_facts', label: 'The facts are wrong' },
  { id: 'not_my_voice', label: 'It does not sound right' },
  { id: 'too_long', label: 'Too long' },
  { id: 'too_short', label: 'Too short' },
  { id: 'wrong_angle', label: 'Wrong angle' },
  { id: 'wrong_language', label: 'Wrong language' },
  { id: 'other', label: 'Something else' }
];

export const reasonLabel = (id: string) => SET_ASIDE_REASONS.find((r) => r.id === id)?.label ?? id.replace(/_/g, ' ');

const NOTE_LIMIT = 200;

/* Elevated glass dialog on the existing primitive (DNA §12.2); borderless field; one inverted commitment. */
const DIALOG = 'rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 sm:max-w-md md:p-6';
const FIELD = 'rafii-field rounded-[var(--rafii-radius-control)] border-0 bg-(--rafii-surface-field) dark:bg-(--rafii-surface-field) px-4 py-3 text-base leading-relaxed md:text-sm';
const ACTION = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-5 text-sm hover:bg-transparent hover:brightness-[1.06]';

/**
 * "Don't use this draft" without deleting it (`p2_variant_feedback`). The draft moves to the "Set aside" group
 * under Drafts and cannot be scheduled until someone edits it.
 */
export function SetAsideDialog({ variantId, open, onOpenChange }: { variantId: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const client = useQueryClient();
  const { workspaceId } = useWorkspace();
  const [outcome, flash] = useFlash<'success' | 'error'>(900);
  const [reasons, setReasons] = useState<string[]>([]);
  const [note, setNote] = useState('');
  const variant = snapshot.data?.state.variants?.find((v) => v.id === variantId) as PipelineVariant | undefined;
  const jobs = (snapshot.data?.state.phase2?.jobs ?? []) as PipelineJob[];
  // The API refuses while a job for this draft is waiting, held, publishing or published (409).
  const blocking = variant ? jobs.find((job) => job.manifest.variantId === variant.id && !FAILED.has(job.state)) : undefined;

  function toggle(id: string, checked: boolean) {
    setReasons((current) => (checked ? [...current.filter((r) => r !== id), id] : current.filter((r) => r !== id)));
  }

  function submit() {
    if (!variant || !snapshot.data) return;
    act.mutate(
      {
        revision: snapshot.data.revision,
        action: 'p2_variant_feedback',
        // Sent in list order, so the same choice always reads the same.
        payload: { variantId: variant.id, variantRevision: variant.revision, reasons: SET_ASIDE_REASONS.map((r) => r.id).filter((id) => reasons.includes(id)), note: note.trim() }
      },
      {
        onSuccess: () => {
          flash('success');
          toast.success('Draft set aside. Edit it to use it again.');
          onOpenChange(false);
        },
        onError: (err) => {
          flash('error');
          toast.error(err instanceof ApiError ? err.message : 'The draft could not be set aside.');
          // "This draft changed" or "Workspace changed": read the workspace again so the dialog shows what is true now.
          if (err instanceof ApiError && err.status === 409 && workspaceId) void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        }
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG}>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            {variant && <ChannelIcon platform={variant.platform} name={variant.platform} size='sm' />}
            Set this draft aside?
          </DialogTitle>
          <DialogDescription>
            It stays in the “Set aside” group under Drafts and cannot be scheduled until someone edits it. Nothing is deleted. PostRiff learns from this only through
            preferences you accept on the Memory page.
          </DialogDescription>
        </DialogHeader>
        {!variant ? (
          <p className='text-muted-foreground text-sm'>This draft is no longer in the workspace.</p>
        ) : (
          <div className='flex flex-col gap-4'>
            <p className='rafii-quiet text-muted-foreground line-clamp-4 rounded-[var(--rafii-radius-control)] px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap'>{variant.proposedUpdate?.text ?? variant.text}</p>
            {blocking && (
              <StateMessage
                kind='unsupported'
                layout='inline'
                title={`A job for this draft is ${stateWords(blocking.state)}.`}
                description='Cancel it in the Queue first; a draft that is scheduled or published cannot be set aside.'
              />
            )}
            <fieldset className='flex flex-col gap-1'>
              <legend className='mb-1 text-sm font-medium'>Why not this one?</legend>
              {SET_ASIDE_REASONS.map((reason) => (
                <Label key={reason.id} className='flex min-h-11 items-center gap-3 text-sm font-normal'>
                  <Checkbox checked={reasons.includes(reason.id)} onCheckedChange={(checked) => toggle(reason.id, checked === true)} />
                  {reason.label}
                </Label>
              ))}
            </fieldset>
            <div className='flex flex-col gap-2'>
              <Label htmlFor='set-aside-note'>Note (optional)</Label>
              <Textarea id='set-aside-note' value={note} onChange={(e) => setNote(e.target.value.slice(0, NOTE_LIMIT))} maxLength={NOTE_LIMIT} rows={2} className={FIELD} />
              <p className='text-muted-foreground text-xs tabular-nums'>
                {note.length} / {NOTE_LIMIT}
              </p>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant='glass' size='control' onClick={() => onOpenChange(false)} disabled={act.isPending}>
            Cancel
          </Button>
          <StatefulButton
            className={ACTION}
            state={act.isPending ? 'loading' : (outcome ?? 'idle')}
            loadingText='Setting aside…'
            successText='Set aside'
            errorText='Try again'
            disabled={!variant || Boolean(blocking) || reasons.length === 0}
            onClick={submit}
          >
            Set aside
          </StatefulButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
