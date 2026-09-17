'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { ChannelIcon } from '@/components/channel-icon';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { languageLabel, textAttributes, textLength } from '@/lib/locales';

/** Per-platform text limits mirrored from `contracts.py` LIMITS; the API is the authority. */
const LIMITS: Record<string, number> = { LinkedIn: 3000, Instagram: 2200, Threads: 500, Xiaohongshu: 1000 };

/**
 * Edit a draft's text in place (`variant_edit`). The edit bumps the variant revision, so any
 * earlier review of it is void — the Schedule step always re-reads the exact text.
 */
export function EditDraftDialog({ variantId, open, onOpenChange }: { variantId: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const variant = snapshot.data?.state.variants?.find((v) => v.id === variantId);
  const [text, setText] = useState(variant?.proposedUpdate?.text ?? variant?.text ?? '');
  const limit = variant ? LIMITS[variant.platform] : undefined;
  const over = limit !== undefined && textLength(text) > limit;
  const dirty = variant !== undefined && text !== variant.text;

  async function save() {
    if (!variant || !snapshot.data) return;
    try {
      let revision = snapshot.data.revision;
      let current = variant;
      // A regenerated version waiting for acceptance becomes the draft first, so the edit applies to it.
      if (current.proposedUpdate && current.proposedUpdate.voiceRevision === snapshot.data.state.speaker?.activeRevision) {
        const accepted = await act.mutateAsync({ revision, action: 'accept_update', payload: { variantId: current.id } });
        revision = accepted.revision;
        current = accepted.state.variants?.find((v) => v.id === current.id) ?? current;
      }
      await act.mutateAsync({ revision, action: 'variant_edit', payload: { variantId: current.id, variantRevision: current.revision, text } });
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
            Edit draft{variant ? ` · ${variant.platform} · ${languageLabel(variant.language)}` : ''}
          </DialogTitle>
          <DialogDescription>Your words, your call. Edits stay in the draft history; PostRiff learns from how you edit only through preferences you accept on the Memory page.</DialogDescription>
        </DialogHeader>
        {variant ? (
          <>
            <Textarea {...textAttributes(variant.language)} value={text} onChange={(e) => setText(e.target.value)} rows={12} className='min-h-48 text-sm [unicode-bidi:plaintext]' aria-label='Draft text' autoFocus />
            <p className={over ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
              {textLength(text)}
              {limit !== undefined ? ` / ${limit} characters for ${variant.platform}` : ' characters'}
              {variant.customized && ' · previously edited'}
            </p>
          </>
        ) : (
          <p className='text-muted-foreground text-sm'>This draft is no longer in the workspace.</p>
        )}
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)} disabled={act.isPending}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!variant || !dirty || over || !text.trim() || act.isPending}>
            {act.isPending ? 'Saving…' : 'Save draft'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
