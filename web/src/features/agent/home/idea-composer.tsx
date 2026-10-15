'use client';

import { forwardRef, useCallback, useId, useRef, useState, type FocusEvent, type FormEvent, type KeyboardEvent, type ReactNode, type RefObject, type SyntheticEvent } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { isImeEvent } from '@/lib/ime';
import { cn } from '@/lib/utils';
import { SlashCommandMenu, type SlashPick } from '@/features/rafii-commands/command-menu';
import type { SlashCommand } from '@/lib/agent-runtime/commands';

export const IDEA_MAX = 20000;

export interface CreationPodPart {
  /** Leading visual (taxonomy minis, account stack). */
  visual: ReactNode;
  label: ReactNode;
  detail?: ReactNode;
  ariaLabel: string;
  onOpen: () => void;
  open?: boolean;
  disabled?: boolean;
}

/**
 * Chat attachments' textarea handlers (chat-context SPEC §4.3, §11.2), composed with the composer's own: the attachment
 * handler runs first and `onKeyDown` returns true when it took the key. Never spread over the composer's ⌘+Enter.
 */
export interface TextareaHandlers {
  ref?: RefObject<HTMLTextAreaElement | null>;
  onInput?: (event: FormEvent<HTMLTextAreaElement>) => void;
  onSelect?: (event: SyntheticEvent<HTMLTextAreaElement>) => void;
  onCompositionStart?: () => void;
  onCompositionEnd?: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean;
  composing?: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean;
  aria?: Record<string, string | undefined>;
}

export interface IdeaComposerProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
  busy?: boolean;
  /** Topline: draft identity + expand affordance. */
  onExpand: () => void;
  /** Editor bottom row: Context Pocket trigger and the neutral sample. */
  contextCount: number;
  onOpenContext: () => void;
  onTryIdea?: () => void;
  /** Extra controls in the editor bottom row (image generation toggle, learning intent). */
  extras?: ReactNode;
  /** Creation pod: WHAT (content type) and WHERE (channels). */
  contentType: CreationPodPart;
  channels: CreationPodPart;
  /** The three independent settings (Language / Model / Writing Voice). */
  settings: ReactNode;
  generate: { label: string; count: number; disabled: boolean; onClick: () => void; help: string };
  /** Consent row (first message): kept exactly as the existing composer renders it. */
  consent?: ReactNode;
  /** Reminder rows (language notes) rendered under the pod. */
  notes?: ReactNode;
  /** Native format per selected destination (creation facet), under the settings. */
  formats?: ReactNode;
  className?: string;
  /** Chat attachments: the chip strip under the text, the ＋ button in the Context row, and the textarea handlers. */
  attachmentsRow?: ReactNode;
  addButton?: ReactNode;
  textareaHandlers?: TextareaHandlers;
  /** Shared `/` command menu; Home decides whether a picked command runs locally or through Agent Runtime V2. */
  slash?: { onPick: (command: SlashCommand, args: string, pick: SlashPick) => void; onDismiss?: () => void };
}

/**
 * The v9 creative composer (DNA §15.1, §21.1): draft identity → serif idea input → context and
 * source actions → content type + channels → Language | Model | Writing Voice → one generate
 * action → assurance. Every control is wired by the caller; this surface owns only the layout.
 */
export const IdeaComposer = forwardRef<HTMLTextAreaElement, IdeaComposerProps>(function IdeaComposer(
  { value, onChange, placeholder, disabled, busy, onExpand, contextCount, onOpenContext, onTryIdea, extras, contentType, channels, settings, generate, consent, notes, formats, className, attachmentsRow, addButton, textareaHandlers, slash },
  ref
) {
  const helpId = useId();
  const handlers = textareaHandlers;
  const attachmentsRef = handlers?.ref;
  const [caret, setCaret] = useState(value.length);
  const composerBox = useRef<HTMLElement>(null);
  // The forwarded ref and the attachments' ref point at the same textarea.
  const setTextarea = useCallback(
    (element: HTMLTextAreaElement | null) => {
      if (typeof ref === 'function') ref(element);
      else if (ref) ref.current = element;
      if (attachmentsRef && element) attachmentsRef.current = element;
    },
    [ref, attachmentsRef]
  );
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (handlers?.onKeyDown?.(event)) return;
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !generate.disabled && !isImeEvent(event) && !handlers?.composing?.(event)) {
      event.preventDefault();
      generate.onClick();
    }
  }
  return (
    <section ref={composerBox} aria-label='Create a social draft' data-tour='composer' className={cn('rafii-composer relative flex flex-col rounded-[var(--rafii-radius-composer)] px-5 pt-5 pb-4 md:px-[26px] md:pt-[27px] md:pb-[18px]', className)}>
      {slash ? <SlashCommandMenu value={value} caret={caret} anchorRef={composerBox} onPick={(command, args, pick) => { setCaret(pick.caret); slash.onPick(command, args, pick); }} onDismiss={slash.onDismiss ?? (() => undefined)} /> : null}
      <div className='text-muted-foreground flex min-h-9 items-center justify-end gap-3'>
        <button type='button' onClick={onExpand} disabled={disabled} aria-label='Expand writing space' className='rafii-focus hover:text-foreground inline-flex min-h-10 items-center gap-1.5 rounded-md text-xs font-medium'>
          Expand
          <Icons.arrowUpRight className='size-3.5' />
        </button>
      </div>
      <textarea
        ref={setTextarea}
        value={value}
        onChange={(event) => { onChange(event.target.value); setCaret(event.target.selectionStart ?? event.target.value.length); }}
        onKeyDown={onKeyDown}
        onInput={(event) => handlers?.onInput?.(event)}
        onSelect={(event) => { setCaret(event.currentTarget.selectionStart ?? event.currentTarget.value.length); handlers?.onSelect?.(event); }}
        onCompositionStart={() => handlers?.onCompositionStart?.()}
        onCompositionEnd={() => handlers?.onCompositionEnd?.()}
        onFocus={(event: FocusEvent<HTMLTextAreaElement>) => {
          // The `@` list inserts into whichever field (composer or Expand) was focused last.
          if (attachmentsRef) attachmentsRef.current = event.currentTarget;
        }}
        {...(handlers?.aria ?? {})}
        maxLength={IDEA_MAX}
        disabled={disabled}
        aria-label='Message'
        aria-describedby={helpId}
        data-tour='composer-idea'
        placeholder={placeholder}
        spellCheck
        className='rafii-serif placeholder:text-muted-foreground/80 mt-3 min-h-[170px] w-full resize-none bg-transparent text-[25px] leading-[1.45] tracking-[-0.02em] outline-none disabled:opacity-60 md:mt-4 md:min-h-[190px] md:text-[26px]'
      />
      {attachmentsRow}
      <div className='mt-1 mb-4 flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1'>
        <button type='button' onClick={onOpenContext} disabled={disabled} aria-haspopup='dialog' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-3 rounded-md text-sm'>
          <span aria-hidden className='relative block h-6 w-7 [perspective:100px]'>
            <span className='bg-foreground/60 absolute top-0.5 left-1 h-4 w-4 -rotate-[9deg] rounded-[2px]' />
            <span className='bg-foreground/40 absolute top-0.5 left-2 h-4 w-4 rotate-[9deg] rounded-[2px]' />
            <span className='rafii-glass-selected absolute inset-x-0 top-2 bottom-0 rounded-[3px_3px_5px_5px]' />
          </span>
          Context
          <span className='rafii-quiet text-muted-foreground rounded-md px-1.5 py-0.5 text-[11px] tabular-nums'>{contextCount}</span>
        </button>
        {addButton}
        <div className='flex flex-wrap items-center gap-2'>
          {extras}
          {value.length === 0 && onTryIdea && (
            <button type='button' onClick={onTryIdea} disabled={disabled} className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-xs font-medium'>
              Try an idea
              <Icons.arrowUpRight className='size-3.5' />
            </button>
          )}
          {/* The limit only matters near it. */}
          {value.length > IDEA_MAX * 0.8 && (
            <span className='text-muted-foreground text-xs tabular-nums' aria-live='polite'>
              {value.length.toLocaleString()} / {IDEA_MAX.toLocaleString()}
            </span>
          )}
        </div>
      </div>
      <div className='pt-3'>
        {/* The two pods stack on narrow phones so their labels stay whole instead of truncating. */}
        <div role='group' aria-label='Creation controls' className='rafii-glass flex flex-col items-stretch rounded-[21px] p-[5px] min-[440px]:h-[65px] min-[440px]:flex-row md:h-[72px]'>
          {[contentType, channels].map((part, index) => (
            <button
              key={index}
              type='button'
              onClick={part.onOpen}
              disabled={disabled || part.disabled}
              aria-haspopup='dialog'
              aria-expanded={part.open ?? false}
              aria-label={part.ariaLabel}
              data-tour={index === 1 ? 'composer-channels' : undefined}
              className={cn('rafii-focus hover:rafii-quiet aria-expanded:rafii-quiet flex min-h-14 min-w-0 flex-1 items-center gap-2.5 rounded-[14px] px-2.5 text-left transition-colors min-[440px]:min-h-0 md:gap-3 md:px-3', index === 1 && 'min-[440px]:flex-[1.15]')}
            >
              <span className='flex shrink-0 items-center'>{part.visual}</span>
              <span className='flex min-w-0 flex-col gap-0.5'>
                <span className='text-foreground truncate text-[13px] font-medium'>{part.label}</span>
                {part.detail && <span className='text-muted-foreground truncate text-xs'>{part.detail}</span>}
              </span>
              <Icons.chevronDown aria-hidden className='text-muted-foreground ml-auto size-3.5 shrink-0' />
            </button>
          ))}
        </div>
        <div className='mt-2.5 mb-[19px]' data-tour='composer-settings'>{settings}</div>
        {formats}
        {notes}
        <Button variant='action' size='hero' data-tour='composer-generate' disabled={generate.disabled} aria-describedby={helpId} onClick={generate.onClick} className='w-full justify-start text-left'>
          <Icons.sparkles className={cn(busy && 'animate-spin motion-reduce:animate-none')} />
          <span className='flex-1 truncate'>{generate.label}</span>
          {generate.count > 0 && !busy && <span className='bg-background/15 text-inherit flex size-6 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums'>{generate.count}</span>}
          <Icons.arrowRight className='size-4' />
        </Button>
        <p id={helpId} className='text-muted-foreground mt-3 min-h-4 text-center text-xs'>
          {generate.help}
        </p>
      </div>
      {consent}
    </section>
  );
});
