'use client';

import { useRef, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { IDEA_MAX, type TextareaHandlers } from './idea-composer';

/**
 * Expanded writing space (DNA §11.5): the same text as the composer, with room to think. Edits
 * apply live to the composer's value (one string, no copy to reconcile); the primary action only
 * returns to the composer.
 */
export function ExpandedIdeaDialog({ open, onOpenChange, value, onChange, placeholder, textareaHandlers, chipStrip, mentionList }: { open: boolean; onOpenChange: (open: boolean) => void; value: string; onChange: (value: string) => void; placeholder: string; textareaHandlers?: TextareaHandlers; chipStrip?: ReactNode; mentionList?: ReactNode }) {
  const field = useRef<HTMLTextAreaElement>(null);
  // Chat attachments (chat-context SPEC §4.9 item 8): the same handlers as the composer, a compact chip strip, and the
  // `@` list inside this dialog's popup, where Escape closes only the list.
  const handlers = textareaHandlers;
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='xl' aria-describedby={undefined} initialFocus={field}>
        <RafiiDialogHeader eyebrow='Expanded draft' title='A bigger space to' accent='think.' />
        <RafiiDialogBody className='flex flex-col'>
          <label htmlFor='rafii-idea-expanded' className='sr-only'>
            Expanded writing space
          </label>
          <div className='relative flex flex-col'>
          {mentionList}
          <textarea
            id='rafii-idea-expanded'
            ref={(element) => {
              field.current = element;
              if (element && handlers?.ref) handlers.ref.current = element;
            }}
            aria-label='Expanded writing space'
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => void handlers?.onKeyDown?.(event)}
            onInput={(event) => handlers?.onInput?.(event)}
            onSelect={(event) => handlers?.onSelect?.(event)}
            onCompositionStart={() => handlers?.onCompositionStart?.()}
            onCompositionEnd={() => handlers?.onCompositionEnd?.()}
            onFocus={(event) => {
              if (handlers?.ref) handlers.ref.current = event.currentTarget;
            }}
            {...(handlers?.aria ?? {})}
            maxLength={IDEA_MAX}
            placeholder={placeholder}
            spellCheck
            className='rafii-field rafii-focus min-h-[45dvh] w-full resize-y rounded-[var(--rafii-radius-card)] p-5 text-[18px] leading-[1.75] outline-none md:text-[19px]'
          />
          </div>
          {chipStrip}
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
