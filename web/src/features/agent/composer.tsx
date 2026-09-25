'use client';

import { forwardRef, useMemo, type KeyboardEvent } from 'react';
import { ChannelLanguageChip, type ChipLanguage } from '@/components/application/language-picker/channel-language-chip';
import { LanguageName } from '@/components/application/language-picker/language-badge';
import { IconWaveSine } from '@tabler/icons-react';
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

/** Platforms the drafting runtime can write for today (mirrors `agent_runtime.PLATFORMS`). X is draftable but never
 *  publishable: PostRiff has no X publisher, so X drafts are copied and posted by hand. */
export const DRAFT_PLATFORMS = ['LinkedIn', 'Instagram', 'Threads', 'Xiaohongshu', 'X'] as const;
export type DraftPlatform = (typeof DRAFT_PLATFORMS)[number];

/** Tool pills in the compact composer: one height, one radius, disabled states with their reason in the title. */
const TOOL = 'rafii-focus inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-xs font-medium whitespace-nowrap transition-colors disabled:opacity-50 sm:h-9';
/** In a narrow composer (phones, the conversation column) secondary tools are round icon buttons, label kept for screen readers. */
const ICON_ON_PHONES = '@max-xl/composer:w-10 @max-xl/composer:justify-center @max-xl/composer:px-0';

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
  /** A caller-side block such as an invalid credit limit; the send button stays disabled. */
  submitDisabled?: boolean;
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
  /** The connected account's name for a selection item's `channelId` (account-level chips). */
  accountLabel?: (channelId: string) => string | undefined;
}

/**
 * One composer for Home and every conversation: text, the channels to draft for, each channel's
 * languages, and the model that will write. Channels named inside the message win over the chips
 * (the server parses them); a language named in the message wins for its channels, and the chips
 * show it with an amber dot. The brief's own language never decides a post's language.
 */
export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSubmit, busy, disabled, submitDisabled, placeholder, chips, languages, models, model, onModel, reasoning, reasoningOptions, onReasoning, voiceMode = 'neutral', onVoiceMode, voiceAvailable = false, imageGeneration, consent, submitLabel, compact, hint, accountLabel },
  ref
) {
  // An unavailable model is never swapped for another paid one: the person chooses again.
  const canSend = !submitDisabled && models.some((m) => m.id === model && m.qualified) && !busy && !disabled && value.trim().length > 0 && languages.selection.length > 0 && (!consent || consent.use) && (!imageGeneration?.enabled || imageGeneration.available);
  const parsed = useMemo(() => locales.parseMessageLanguages(value), [value]);
  // One chip per selected account (two accounts on one platform stay two chips); a platform with no
  // selected account keeps its single platform chip.
  const rows = chips.flatMap((chip) => {
    const items = languages.selection.filter((item) => item.platform === chip.platform);
    return (items.length ? items : [null]).map((selection) => {
      const on = Boolean(selection) || parsed.perPlatform.has(chip.platform);
      const current = languages.languagesOf(selection ?? { platform: chip.platform, languages: null });
      const effective: ChipLanguage[] = locales
        .effectiveLanguages(chip.platform, current, parsed)
        .map((item) => ({ tag: item.tag, fromMessage: item.fromMessage, index: item.fromMessage ? null : current.indexOf(item.tag) }));
      const account = selection?.channelId ? (accountLabel?.(selection.channelId) ?? chip.account) : chip.account;
      const key = selection?.key ?? chip.platform;
      const label = selection?.channelId && items.length > 1 ? `${chip.platform} · ${account ?? 'account'}` : undefined;
      return { chip, on, effective, key, account, label, target: selection?.channelId ? { platform: chip.platform, channelId: selection.channelId } : chip.platform };
    });
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
    <div className='rafii-composer @container/composer flex flex-col rounded-[var(--rafii-radius-card)]' data-tour='composer'>
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
        className='min-h-0 resize-none border-0 bg-transparent px-4 pt-4 text-base shadow-none focus-visible:ring-0 md:text-[15px] dark:bg-transparent'
      />
      {/* Destinations: one row of uniform pills that scrolls sideways instead of wrapping into ragged lines. */}
      <div role='group' aria-label='Draft for' className='scrollbar-hide relative flex items-center gap-2 overflow-x-auto px-3 pt-1 pr-10 pb-2 [mask-image:linear-gradient(to_right,#000_calc(100%-2.5rem),transparent)]'>
        <span className='text-muted-foreground shrink-0 pl-1 text-xs'>Draft for</span>
        {rows.map(({ chip, on, effective, key, account, label, target }) => {
          const remembered = languages.settings.channels[chip.platform] ?? [];
          const usual = locales.usualFor(chip.platform);
          const suggestions = [
            ...remembered.map((tag) => ({ tag, reason: 'Last used here' })),
            ...(usual ? [{ tag: usual, reason: `Usual for ${chip.platform}` }] : []),
            ...languages.suggestions
          ].filter((item, i, all) => all.findIndex((other) => other.tag === item.tag) === i);
          return (
            <ChannelLanguageChip
              key={key}
              platform={chip.platform}
              label={label}
              account={account}
              state={chip.state}
              on={on}
              languages={effective}
              channelCount={channelCount}
              suggestions={suggestions}
              disabled={disabled}
              onToggle={() => languages.toggle(target)}
              onChange={(index, tag) => (index === null ? languages.add(key, tag) : languages.change(key, index, tag))}
              onAdd={(tag) => languages.add(key, tag)}
              onRemove={(index) => languages.remove(key, index)}
              onUseEverywhere={(tag) => languages.useEverywhere(tag)}
            />
          );
        })}
      </div>
      {/* Tools on one line (same height, same material), the single primary action on the right. */}
      <div className='flex items-center gap-2 px-3 pb-3'>
        <div className='scrollbar-hide relative flex min-w-0 flex-1 items-center gap-2 overflow-x-auto'>
          <ModelPicker compact options={models} model={model} onChoose={onModel} disabled={disabled || busy} reasoning={reasoning} reasoningOptions={reasoningOptions} onReasoning={onReasoning} />
          {onVoiceMode && (
            <button
              type='button'
              aria-pressed={voiceMode === 'personalized'}
              disabled={disabled || busy || !voiceAvailable}
              onClick={() => onVoiceMode(voiceMode === 'personalized' ? 'neutral' : 'personalized')}
              title={voiceAvailable ? 'Uses only samples you approved for this model' : 'Approve writing samples on the Brand page first'}
              className={cn(TOOL, ICON_ON_PHONES, voiceMode === 'personalized' ? 'rafii-glass-selected text-foreground' : 'rafii-glass text-muted-foreground hover:text-foreground')}
            >
              <IconWaveSine aria-hidden className='size-4' />
              <span className='@max-xl/composer:sr-only'>{voiceMode === 'personalized' ? 'Writing like me' : 'Neutral voice'}</span>
            </button>
          )}
          {imageGeneration && (
            <button
              type='button'
              aria-pressed={imageGeneration.enabled}
              disabled={disabled || busy || !imageGeneration.available}
              onClick={() => imageGeneration.onChange(!imageGeneration.enabled)}
              title={imageGeneration.detail}
              className={cn(TOOL, ICON_ON_PHONES, imageGeneration.enabled ? 'rafii-glass-selected text-foreground' : 'rafii-glass text-muted-foreground hover:text-foreground')}
            >
              <Icons.media aria-hidden className='size-4' />
              <span className='@max-xl/composer:sr-only'>{imageGeneration.enabled ? 'Image on' : 'Generate image'}</span>
            </button>
          )}
        </div>
        <Button variant='action' size='icon-control' className='shrink-0 rounded-full' disabled={!canSend} onClick={onSubmit} aria-label={submitLabel ?? 'Send'}>
          <ActionSwapIcon value={busy ? 'busy' : 'send'} animation='blur' className='size-4'>
            {busy ? <Icons.spinner className='size-4 animate-spin motion-reduce:animate-none' /> : <Icons.send className='size-4' />}
          </ActionSwapIcon>
        </Button>
      </div>
      {reminder && (
        <div className='border-border/60 text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1.5 border-t px-4 py-2 text-xs'>
          {reminder.tone === 'amber' ? <Icons.info aria-hidden className='text-foreground size-3.5 shrink-0' /> : <span aria-hidden className='bg-muted-foreground/50 size-1.5 shrink-0 rounded-full' />}
          <span className='inline-flex min-w-0 flex-wrap items-center gap-x-1'>
            {reminder.platform}: <LanguageName language={reminder.tag} className='text-foreground' /> {reminder.text}
          </span>
          {reminder.choices && (
            <span className='inline-flex flex-wrap gap-1'>
              {(['feminine', 'masculine', 'neutral'] as const).map((value) => (
                <button key={value} type='button' onClick={() => languages.setSelfReference(value)} className='rafii-glass rafii-focus text-foreground min-h-8 rounded-[var(--rafii-radius-control)] px-2.5'>
                  {value === 'neutral' ? 'Neutral wording' : value === 'feminine' ? 'Feminine' : 'Masculine'}
                </button>
              ))}
            </span>
          )}
          {reminder.more > 0 && <span>+{reminder.more} more</span>}
        </div>
      )}
      {consent && (
        <div className='border-border/60 flex flex-wrap items-center gap-x-5 gap-y-2 border-t px-4 py-2.5'>
          <Checkbox checked={consent.use} onCheckedChange={consent.onUse} disabled={disabled} label='Use this text to draft with' className='gap-2 [&>button]:size-4 [&>span]:text-xs' />
          <Checkbox checked={consent.own} onCheckedChange={consent.onOwn} disabled={disabled} label='Allow public quotes from my own writing' className='gap-2 [&>button]:size-4 [&>span]:text-xs' />
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
      if (entry.regionless) found.push({ platform: chip.platform, tag: language.tag, text: 'has no region. Pick one.', tone: 'amber' });
      else if (!entry.guide) found.push({ platform: chip.platform, tag: language.tag, text: 'isn’t tuned yet. Check the wording.', tone: 'amber' });
      else if (entry.gendered && !languages.settings.selfReference)
        found.push({ platform: chip.platform, tag: language.tag, text: 'uses gendered words. How do you refer to yourself?', tone: 'quiet', choices: true });
    }
  }
  const unique = found.filter((item, i) => found.findIndex((other) => other.tag === item.tag && other.text === item.text) === i);
  return unique.length ? { ...unique[0], more: unique.length - 1 } : null;
}
