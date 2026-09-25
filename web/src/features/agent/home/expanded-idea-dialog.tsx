'use client';

import { useRef } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { IDEA_MAX } from './idea-composer';

/**
 * Expanded writing space (DNA §11.5): the same text as the composer, with room to think. Edits
 * apply live to the composer's value (one string, no copy to reconcile); the primary action only
 * returns to the composer.
 */
export function ExpandedIdeaDialog({ open, onOpenChange, value, onChange, placeholder }: { open: boolean; onOpenChange: (open: boolean) => void; value: string; onChange: (value: string) => void; placeholder: string }) {
  const field = useRef<HTMLTextAreaElement>(null);
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='xl' aria-describedby={undefined} initialFocus={field}>
        <RafiiDialogHeader eyebrow='Expanded draft' title='A bigger space to' accent='think.' />
        <RafiiDialogBody className='flex flex-col'>
          <label htmlFor='rafii-idea-expanded' className='sr-only'>
            Expanded writing space
          </label>
          <textarea
            id='rafii-idea-expanded'
            ref={field}
            aria-label='Expanded writing space'
            value={value}
            onChange={(event) => onChange(event.target.value)}
            maxLength={IDEA_MAX}
            placeholder={placeholder}
            spellCheck
            className='rafii-field rafii-focus min-h-[45dvh] w-full resize-y rounded-[var(--rafii-radius-card)] p-5 text-[18px] leading-[1.75] outline-none md:text-[19px]'
          />
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row items-center justify-between'>
          <span className='text-muted-foreground text-xs tabular-nums'>
            {value.length.toLocaleString()} / {IDEA_MAX.toLocaleString()}
          </span>
          <Button variant='action' size='control' onClick={() => onOpenChange(false)}>
            Done
            <Icons.check />
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
