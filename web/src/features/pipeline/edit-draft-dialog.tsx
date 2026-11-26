'use client';

import { OpportunityLabPanel } from '@/features/trends/lab-panel';
import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { limitNotes } from '@/components/application/post-preview/limits';
import { ChannelIcon, resolveChannelSlug } from '@/components/channel-icon';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { languageLabel, textAttributes } from '@/lib/locales';
import { workflowKey } from '@/lib/time-back/active-time';
import { useActiveWorkTimer } from '@/lib/time-back/use-active-work-timer';
import { PostDoctorPanel } from '@/features/growth/post-doctor-panel';
import { relocateSelection, type TextRange } from './tone-edit-contract';
import { ToneEditPanel } from './tone-edit-panel';

/* Elevated glass dialog on the existing primitive (DNA §12.2); the editor is a readable, regular 15–16px surface (DNA §21.2). */
const DIALOG = 'rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 sm:max-w-xl md:p-6';
const EDITOR = 'rafii-field min-h-48 rounded-[var(--rafii-radius-control)] border-0 bg-(--rafii-surface-field) dark:bg-(--rafii-surface-field) px-4 py-3 text-base leading-relaxed md:text-[15px] [unicode-bidi:plaintext]';

/**
 * Edit a draft's text in place (`variant_edit`). The edit bumps the variant revision, so any
 * earlier review of it is void — the Schedule step always re-reads the exact text.
 */
export function EditDraftDialog({ variantId, open, onOpenChange }: { variantId: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const snapshot = useSnapshot();
  const act = useAct();
  // Time back: editing this draft is part of its work; measured only while the dialog is open.
  useActiveWorkTimer({ workflowKey: workflowKey('variant', variantId), taskKind: 'draft', enabled: open });
  const variant = snapshot.data?.state.variants?.find((v) => v.id === variantId);
  const [text, setText] = useState(variant?.text ?? '');
  const notes = variant ? limitNotes({channel: resolveChannelSlug(undefined, variant.platform), channelName: variant.platform, account: '', text, media: [], publishAt: new Date(), timeZone: 'UTC'}) : [];
  const dirty = variant !== undefined && (text !== variant.text || variant.rejected === true);
  // The textarea's selection (UTF-16 offsets) with the text it was read from: once the text is anything else, the
  // offsets name nothing and a tone or polish edit applies to the whole draft.
  const [picked, setPicked] = useState<(TextRange & { of: string }) | null>(null);
  const selection = picked && picked.of === text ? picked : null;

  function notePick(target: HTMLTextAreaElement, shown: string) {
    const { selectionStart: start, selectionEnd: end } = target;
    // A stored CRLF reads back from a textarea as LF, so the offsets count only while both hold the same text.
    setPicked(start === end || target.value !== shown ? null : { start, end, of: shown });
  }

  /** Saves the text and stays open, for an edit that works on the saved revision (`ToneEditPanel`). */
  async function persist() {
    if (!variant || !snapshot.data) throw new Error('This draft is gone.');
    const saved = await act.mutateAsync({ revision: snapshot.data.revision, action: 'variant_edit', payload: { variantId: variant.id, variantRevision: variant.revision, text } });
    const stored = saved.state.variants?.find((item) => item.id === variant.id);
    if (!stored) throw new Error('The saved draft is unavailable. Reload before continuing.');
    // The server trims the ends: the editor shows what was stored, and the selection follows its passage.
    const moved = selection ? relocateSelection(text, selection, stored.text) : null;
    setPicked(moved ? { ...moved, of: stored.text } : null);
    setText(stored.text);
    return { variant: stored, revision: saved.revision };
  }

  async function save() {
    if (!variant || !snapshot.data) return;
    try {
      await act.mutateAsync({ revision: snapshot.data.revision, action: 'variant_edit', payload: { variantId: variant.id, variantRevision: variant.revision, text } });
      toast.success('Draft saved');
      onOpenChange(false);
    } catch (err) {
      toast.error('Couldn’t save the draft', { description: err instanceof ApiError ? err.message : undefined });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG} max-h-[90dvh] overflow-y-auto`}>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            {variant && <ChannelIcon platform={variant.platform} name={variant.platform} size='sm' />}
            Edit draft{variant ? ` · ${variant.platform} · ${languageLabel(variant.language)}` : ''}
          </DialogTitle>
          <DialogDescription className='sr-only'>Edit the text of this draft.</DialogDescription>
        </DialogHeader>
        {variant ? (
          <>
            <Textarea {...textAttributes(variant.language)} value={text} onChange={(e) => { setText(e.target.value); notePick(e.target, e.target.value); }} onSelect={(e) => notePick(e.currentTarget, text)} rows={12} className={EDITOR} aria-label='Draft text' autoFocus />
            {notes.map((note, index) => <p key={index} className={note.tone === 'problem' ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>{note.text}</p>)}
            {notes.length === 0 && <p className='text-muted-foreground text-xs tabular-nums'>{Array.from(text).length} characters</p>}
            {/* Keyed inside by draft and revision; renders nothing while the server has one-click edits off. */}
            <ToneEditPanel variant={variant} text={text} selection={selection} save={persist} onText={setText} />
            <PostDoctorPanel key={`${variant.id}:${variant.revision}`} variant={variant} dirty={dirty} onAccepted={setText} />
            <OpportunityLabPanel draft={{ id: variant.id, revision: variant.revision, platform: variant.platform, text, dirty }} onApply={async edit => {
              if (!snapshot.data || dirty || variant.revision !== edit.expected_revision) throw new Error('The draft changed. Save and check again.');
              // `appliedFrom`: the Lab wrote this text, so it is not counted as the person's own edit for learning.
              const saved = await act.mutateAsync({ revision: snapshot.data.revision, action: 'variant_edit', payload: { variantId: variant.id, variantRevision: edit.expected_revision, text: edit.text, appliedFrom: 'opportunity_lab' } });
              const savedVariant = saved.state.variants?.find((item) => item.id === variant.id);
              if (!savedVariant) throw new Error('The saved draft is unavailable. Reload before continuing.');
              setText(savedVariant.text);
              toast.success('Suggested edit saved. Review the new draft revision before scheduling.');
            }} />

          </>
        ) : (
          <p className='text-muted-foreground text-sm'>This draft is gone.</p>
        )}
        <DialogFooter>
          <Button variant='glass' size='control' onClick={() => onOpenChange(false)} disabled={act.isPending}>
            Cancel
          </Button>
          <Button variant='action' size='control' onClick={() => void save()} disabled={!variant || !dirty || !text.trim() || act.isPending}>
            {act.isPending ? 'Saving…' : 'Save draft'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
