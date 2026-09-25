'use client';

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
  const variant = snapshot.data?.state.variants?.find((v) => v.id === variantId);
  const [text, setText] = useState(variant?.text ?? '');
  const notes = variant ? limitNotes({channel: resolveChannelSlug(undefined, variant.platform), channelName: variant.platform, account: '', text, media: [], publishAt: new Date(), timeZone: 'UTC'}) : [];
  const dirty = variant !== undefined && (text !== variant.text || variant.rejected === true);

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
      <DialogContent className={DIALOG}>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            {variant && <ChannelIcon platform={variant.platform} name={variant.platform} size='sm' />}
            Edit draft{variant ? ` · ${variant.platform} · ${languageLabel(variant.language)}` : ''}
          </DialogTitle>
          <DialogDescription className='sr-only'>Edit the text of this draft.</DialogDescription>
        </DialogHeader>
        {variant ? (
          <>
            <Textarea {...textAttributes(variant.language)} value={text} onChange={(e) => setText(e.target.value)} rows={12} className={EDITOR} aria-label='Draft text' autoFocus />
            {notes.map((note, index) => <p key={index} className={note.tone === 'problem' ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>{note.text}</p>)}
            {notes.length === 0 && <p className='text-muted-foreground text-xs tabular-nums'>{Array.from(text).length} characters</p>}

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
