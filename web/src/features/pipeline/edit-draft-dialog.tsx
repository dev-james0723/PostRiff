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
      toast.success('Draft updated. Schedule it to review the exact text.');
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The draft could not be saved.');
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            {variant && <ChannelIcon platform={variant.platform} name={variant.platform} size='sm' />}
            Edit draft{variant ? ` · ${variant.platform} · ${variant.language}` : ''}
          </DialogTitle>
          <DialogDescription>Your words, your call. Edits stay in the draft history; PostRiff learns from how you edit only through preferences you accept on the Memory page.</DialogDescription>
        </DialogHeader>
        {variant ? (
          <>
            <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} className='min-h-48 text-sm' aria-label='Draft text' autoFocus />
            {notes.map((note, index) => <p key={index} className={note.tone === 'problem' ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>{note.text}</p>)}
            {notes.length === 0 && <p className='text-muted-foreground text-xs'>{Array.from(text).length} characters</p>}

          </>
        ) : (
          <p className='text-muted-foreground text-sm'>This draft is no longer in the workspace.</p>
        )}
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)} disabled={act.isPending}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!variant || !dirty || !text.trim() || act.isPending}>
            {act.isPending ? 'Saving…' : 'Save draft'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
