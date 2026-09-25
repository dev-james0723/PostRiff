'use client';

import { forwardRef, useId, type KeyboardEvent, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

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
  className?: string;
}

/**
 * The v9 creative composer (DNA §15.1, §21.1): draft identity → serif idea input → context and
 * source actions → content type + channels → Language | Model | Writing Voice → one generate
 * action → assurance. Every control is wired by the caller; this surface owns only the layout.
 */
export const IdeaComposer = forwardRef<HTMLTextAreaElement, IdeaComposerProps>(function IdeaComposer(
  { value, onChange, placeholder, disabled, busy, onExpand, contextCount, onOpenContext, onTryIdea, extras, contentType, channels, settings, generate, consent, notes, className },
  ref
) {
  const helpId = useId();
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !generate.disabled) {
      event.preventDefault();
      generate.onClick();
    }
  }
  return (
    <section aria-label='Create a social draft' data-tour='composer' className={cn('rafii-composer flex flex-col rounded-[var(--rafii-radius-composer)] px-5 pt-5 pb-4 md:px-[26px] md:pt-[27px] md:pb-[18px]', className)}>
      <div className='text-muted-foreground flex min-h-9 items-center justify-end gap-3'>
        <button type='button' onClick={onExpand} disabled={disabled} aria-label='Expand writing space' className='rafii-focus hover:text-foreground inline-flex min-h-10 items-center gap-1.5 rounded-md text-xs font-medium'>
          Expand
          <Icons.arrowUpRight className='size-3.5' />
        </button>
      </div>
      <textarea
        ref={ref}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        maxLength={IDEA_MAX}
        disabled={disabled}
        aria-label='Message'
        aria-describedby={helpId}
        placeholder={placeholder}
        spellCheck
        className='rafii-serif placeholder:text-muted-foreground/80 mt-3 min-h-[170px] w-full resize-none bg-transparent text-[25px] leading-[1.45] tracking-[-0.02em] outline-none disabled:opacity-60 md:mt-4 md:min-h-[190px] md:text-[26px]'
      />
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
        <div className='mt-2.5 mb-[19px]'>{settings}</div>
        {notes}
        <Button variant='action' size='hero' disabled={generate.disabled} aria-describedby={helpId} onClick={generate.onClick} className='w-full justify-start text-left'>
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
