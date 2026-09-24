'use client';

import { forwardRef, useMemo, type KeyboardEvent } from 'react';
import { ChannelLanguageChip, type ChipLanguage } from '@/components/application/language-picker/channel-language-chip';
import { LanguageName } from '@/components/application/language-picker/language-badge';
import { Icons } from '@/components/icons';
import { ActionSwapIcon } from '@/components/motion/action-swap';
import { Checkbox } from '@/components/motion/checkbox';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { ModelOption } from '@/lib/api/types';
import { locales } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { ModelPicker } from './model-picker';
import type { ChannelLanguages } from './use-channel-languages';

/** Platforms the drafting runtime can write for today (mirrors `agent_runtime.PLATFORMS`). */
export const DRAFT_PLATFORMS = ['LinkedIn', 'Instagram', 'Threads', 'Xiaohongshu'] as const;
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
  /** Selected channels and each channel's languages (useChannelLanguages). */
  languages: ChannelLanguages<DraftPlatform>;
  /** Every model the deployment can write with, and which one this composer sends. */
  models: ModelOption[];
  model: string;
  onModel: (id: string) => void;
  reasoning?: string;
  reasoningOptions?: { id: string; detail: string }[];
  onReasoning?: (id: string) => void;
  voiceMode?: 'neutral' | 'personalized';
  onVoiceMode?: (mode: 'neutral' | 'personalized') => void;
  voiceAvailable?: boolean;
  imageGeneration?: { enabled: boolean; available: boolean; detail: string; onChange: (enabled: boolean) => void };
  /** First message only: consent to draft from the text, and whether it may be quoted. */
  consent?: { own: boolean; use: boolean; onOwn: (v: boolean) => void; onUse: (v: boolean) => void };
  submitLabel?: string;
  compact?: boolean;
  hint?: string;
}

/**
 * One composer for Home and every conversation: text, the channels to draft for, each channel's
 * languages, and the model that will write. Channels named inside the message win over the chips
 * (the server parses them); a language named in the message wins for its channels, and the chips
 * show it with an amber dot. The brief's own language never decides a post's language.
 */
export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSubmit, busy, disabled, placeholder, chips, languages, models, model, onModel, reasoning, reasoningOptions, onReasoning, voiceMode = 'neutral', onVoiceMode, voiceAvailable = false, imageGeneration, consent, submitLabel, compact, hint },
  ref
) {
  const canSend = !busy && !disabled && value.trim().length > 0 && languages.selection.length > 0 && (!consent || consent.use) && (!imageGeneration?.enabled || imageGeneration.available);
  const parsed = useMemo(() => locales.parseMessageLanguages(value), [value]);
  const rows = chips.map((chip) => {
    const selection = languages.selection.find((item) => item.platform === chip.platform);
    const on = Boolean(selection) || parsed.perPlatform.has(chip.platform);
    const current = languages.languagesOf(selection ?? { platform: chip.platform, languages: null });
    const effective: ChipLanguage[] = locales
      .effectiveLanguages(chip.platform, current, parsed)
      .map((item) => ({ tag: item.tag, fromMessage: item.fromMessage, index: item.fromMessage ? null : current.indexOf(item.tag) }));
    return { chip, on, effective };
  });
  const channelCount = rows.filter((row) => row.on).length;
  const reminder = reminderFor(rows.filter((row) => row.on), languages);

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
          {rows.map(({ chip, on, effective }) => {
            const remembered = languages.settings.channels[chip.platform] ?? [];
            const usual = locales.usualFor(chip.platform);
            const suggestions = [
              ...remembered.map((tag) => ({ tag, reason: 'Last used here' })),
              ...(usual ? [{ tag: usual, reason: `Usual for ${chip.platform}` }] : []),
              ...languages.suggestions
            ].filter((item, i, all) => all.findIndex((other) => other.tag === item.tag) === i);
            return (
              <ChannelLanguageChip
                key={chip.platform}
                platform={chip.platform}
                account={chip.account}
                state={chip.state}
                on={on}
                languages={effective}
                channelCount={channelCount}
                suggestions={suggestions}
                disabled={disabled}
                onToggle={() => languages.toggle(chip.platform)}
                onChange={(index, tag) => (index === null ? languages.add(chip.platform, tag) : languages.change(chip.platform, index, tag))}
                onAdd={(tag) => languages.add(chip.platform, tag)}
                onRemove={(index) => languages.remove(chip.platform, index)}
                onUseEverywhere={(tag) => languages.useEverywhere(tag)}
              />
            );
          })}
          {onVoiceMode && (
            <button
              type='button'
              aria-pressed={voiceMode === 'personalized'}
              disabled={disabled || busy || !voiceAvailable}
              onClick={() => onVoiceMode(voiceMode === 'personalized' ? 'neutral' : 'personalized')}
              title={voiceAvailable ? 'Use only the selected writing samples allowed for this writer' : 'Select writing samples and allow this writer on the Brand page'}
              className={cn('h-7 rounded-lg border px-2.5 text-xs font-medium transition-colors', voiceMode === 'personalized' ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground', !voiceAvailable && 'opacity-50')}
            >
              {voiceMode === 'personalized' ? 'Writing like me' : 'Neutral voice'}
            </button>
          )}
          {imageGeneration && (
            <button
              type='button'
              aria-pressed={imageGeneration.enabled}
              disabled={disabled || busy || !imageGeneration.available}
              onClick={() => imageGeneration.onChange(!imageGeneration.enabled)}
              title={imageGeneration.detail}
              className={cn('h-7 rounded-lg border px-2.5 text-xs font-medium transition-colors', imageGeneration.enabled ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground', !imageGeneration.available && 'opacity-50')}
            >
              <span className='inline-flex items-center gap-1.5'><Icons.media className='size-3.5' />{imageGeneration.enabled ? 'Image on' : 'Generate image'}</span>
            </button>
          )}
        </div>
        <div className='flex items-center gap-2'>
          <ModelPicker options={models} model={model} onChoose={onModel} disabled={disabled || busy} reasoning={reasoning} reasoningOptions={reasoningOptions} onReasoning={onReasoning} />
          <Button size='icon' className='rounded-full' disabled={!canSend} onClick={onSubmit} aria-label={submitLabel ?? 'Send'}>
            <ActionSwapIcon value={busy ? 'busy' : 'send'} animation='blur' className='size-4'>
              {busy ? <Icons.spinner className='size-4 animate-spin' /> : <Icons.send className='size-4' />}
            </ActionSwapIcon>
          </Button>
        </div>
      </div>
      {reminder && (
        <div className='border-border/60 text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1.5 border-t px-4 py-2 text-xs'>
          <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${reminder.tone === 'amber' ? 'bg-amber-500' : 'bg-muted-foreground/50'}`} />
          <span className='inline-flex min-w-0 flex-wrap items-center gap-x-1'>
            {reminder.platform}: <LanguageName language={reminder.tag} className='text-foreground' /> {reminder.text}
          </span>
          {reminder.choices && (
            <span className='inline-flex flex-wrap gap-1'>
              {(['feminine', 'masculine', 'neutral'] as const).map((value) => (
                <button key={value} type='button' onClick={() => languages.setSelfReference(value)} className='ring-foreground/10 hover:bg-muted text-foreground h-6 rounded-md px-2 ring-1'>
                  {value === 'neutral' ? 'Neutral wording' : value === 'feminine' ? 'Feminine' : 'Masculine'}
                </button>
              ))}
            </span>
          )}
          {reminder.more > 0 && <span>{reminder.more} more in the plan.</span>}
        </div>
      )}
      {consent && (
        <div className='border-border/60 flex flex-wrap items-center gap-x-5 gap-y-2 border-t px-4 py-2.5'>
          <Checkbox checked={consent.use} onCheckedChange={consent.onUse} disabled={disabled} label='Use this text to draft with' className='gap-2 [&>button]:size-4 [&>span]:text-xs' />
          <Checkbox checked={consent.own} onCheckedChange={consent.onOwn} disabled={disabled} label='My own writing (may be quoted publicly)' className='gap-2 [&>button]:size-4 [&>span]:text-xs' />
          {hint && <span className='text-muted-foreground ml-auto text-xs'>{hint}</span>}
        </div>
      )}
      {!consent && hint && <div className='text-muted-foreground border-border/60 border-t px-4 py-2 text-xs'>{hint}</div>}
    </div>
  );
});

/** The first language reminder for the selected channels (languages plan §8). Reminders never block sending. */
function reminderFor(rows: { chip: ChannelChip; effective: ChipLanguage[] }[], languages: ChannelLanguages<DraftPlatform>) {
  const found: { platform: string; tag: string; text: string; tone: 'amber' | 'quiet'; choices?: boolean }[] = [];
  for (const { chip, effective } of rows) {
    for (const language of effective) {
      const entry = locales.entry(language.tag);
      if (!entry) continue;
      if (entry.regionless) found.push({ platform: chip.platform, tag: language.tag, text: 'has no region. Pick one so spelling and wording match your readers.', tone: 'amber' });
      else if (!entry.guide) found.push({ platform: chip.platform, tag: language.tag, text: 'isn’t tuned yet. PostRiff still writes it; check the wording before you post.', tone: 'amber' });
      else if (entry.gendered && !languages.settings.selfReference)
        found.push({ platform: chip.platform, tag: language.tag, text: 'shows the writer’s gender in some words. How do you refer to yourself?', tone: 'quiet', choices: true });
    }
  }
  const unique = found.filter((item, i) => found.findIndex((other) => other.tag === item.tag && other.text === item.text) === i);
  return unique.length ? { ...unique[0], more: unique.length - 1 } : null;
}
