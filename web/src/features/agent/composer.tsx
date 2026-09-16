'use client';

import { forwardRef, type KeyboardEvent } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ModelOption } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { ModelPicker } from './model-picker';

export type Language = 'English' | '繁體中文';

/** Platforms the drafting runtime can write for today (mirrors `agent_runtime.DESTINATIONS`). */
export const DRAFT_PLATFORMS = ['LinkedIn', 'Instagram', 'Threads'] as const;
export type DraftPlatform = (typeof DRAFT_PLATFORMS)[number];

export interface ChannelChip {
  platform: DraftPlatform;
  /** Connected account label, when one exists. */
  account?: string;
  /** Provider-reported readiness for the connected account. */
  state?: string;
}

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy?: boolean;
  disabled?: boolean;
  placeholder: string;
  chips: ChannelChip[];
  selected: DraftPlatform[];
  onToggle: (platform: DraftPlatform) => void;
  language: Language;
  onLanguage: (language: Language) => void;
  /** Every model the deployment can write with, and which one this composer sends. */
  models: ModelOption[];
  model: string;
  onModel: (id: string) => void;
  /** First message only: consent to draft from the text, and whether it may be quoted. */
  consent?: { own: boolean; use: boolean; onOwn: (v: boolean) => void; onUse: (v: boolean) => void };
  submitLabel?: string;
  compact?: boolean;
  hint?: string;
}

/**
 * One composer for Home and every conversation: text, the channels to draft for, the
 * language, and the model that will write. Channels named inside the message win over the
 * chips (the server parses them); the chips are the default when nothing is named.
 */
export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSubmit, busy, disabled, placeholder, chips, selected, onToggle, language, onLanguage, models, model, onModel, consent, submitLabel, compact, hint },
  ref
) {
  const canSend = !busy && !disabled && value.trim().length > 0 && selected.length > 0 && (!consent || consent.use);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && canSend) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <div className='bg-card ring-foreground/10 flex flex-col rounded-xl shadow-xs ring-1'>
      <Textarea
        ref={ref}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        rows={compact ? 2 : 4}
        maxLength={20000}
        disabled={disabled}
        aria-label='Message'
        placeholder={placeholder}
        className='min-h-0 resize-none border-0 bg-transparent px-4 pt-4 text-[15px] shadow-none focus-visible:ring-0 dark:bg-transparent'
      />
      <div className='flex flex-wrap items-center justify-between gap-2 px-3 pt-1 pb-3'>
        <div className='flex flex-wrap items-center gap-1.5'>
          <span className='text-muted-foreground mr-1 text-xs'>Draft for</span>
          {chips.map((chip) => {
            const on = selected.includes(chip.platform);
            const ready = chip.state === 'Ready for posting';
            return (
              <button
                key={chip.platform}
                type='button'
                aria-pressed={on}
                disabled={disabled}
                onClick={() => onToggle(chip.platform)}
                title={chip.account ? `${chip.account} · ${chip.state ?? 'connected'}` : 'No account connected yet · drafts only'}
                className={cn(
                  'inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors',
                  on ? 'border-transparent bg-secondary text-secondary-foreground' : 'border-border bg-background text-muted-foreground hover:text-foreground'
                )}
              >
                <span aria-hidden className={cn('size-1.5 rounded-full', chip.account ? (ready ? 'bg-emerald-500' : 'bg-amber-500') : 'bg-muted-foreground/40')} />
                {chip.platform}
              </button>
            );
          })}
          <span className='bg-border mx-1 h-4 w-px' />
          <div className='bg-muted flex rounded-lg p-0.5' role='radiogroup' aria-label='Language'>
            {(['English', '繁體中文'] as Language[]).map((item) => (
              <button
                key={item}
                type='button'
                role='radio'
                aria-checked={language === item}
                disabled={disabled}
                onClick={() => onLanguage(item)}
                className={cn('h-6 rounded-md px-2 text-xs font-medium', language === item ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground')}
              >
                {item === 'English' ? 'EN' : '繁中'}
              </button>
            ))}
          </div>
        </div>
        <div className='flex items-center gap-2'>
          <ModelPicker options={models} model={model} onChoose={onModel} disabled={disabled} />
          <Button size='icon' className='rounded-full' disabled={!canSend} onClick={onSubmit} aria-label={submitLabel ?? 'Send'}>
            {busy ? <Icons.spinner className='size-4 animate-spin' /> : <Icons.send className='size-4' />}
          </Button>
        </div>
      </div>
      {consent && (
        <div className='border-border/60 flex flex-wrap items-center gap-x-5 gap-y-2 border-t px-4 py-2.5'>
          <Label className='flex items-center gap-2 text-xs font-normal'>
            <Checkbox checked={consent.use} onCheckedChange={(v) => consent.onUse(v === true)} disabled={disabled} />
            Use this text to draft with
          </Label>
          <Label className='flex items-center gap-2 text-xs font-normal'>
            <Checkbox checked={consent.own} onCheckedChange={(v) => consent.onOwn(v === true)} disabled={disabled} />
            My own writing (may be quoted publicly)
          </Label>
          {hint && <span className='text-muted-foreground ml-auto text-xs'>{hint}</span>}
        </div>
      )}
      {!consent && hint && <div className='text-muted-foreground border-border/60 border-t px-4 py-2 text-xs'>{hint}</div>}
    </div>
  );
});
