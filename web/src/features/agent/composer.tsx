'use client';

import { forwardRef, useCallback, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { LanguageName } from '@/components/application/language-picker/language-badge';
import { IconWaveSine } from '@tabler/icons-react';
import { Icons } from '@/components/icons';
import { ActionSwapIcon } from '@/components/motion/action-swap';
import { Checkbox } from '@/components/motion/checkbox';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { LocaleTag, ModelOption } from '@/lib/api/types';
import { isImeEvent } from '@/lib/ime';
import { locales } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { AttachmentBar, type AttachmentBarProps } from './attachments/attachment-bar';
import { MentionList, mentionOptions, mentionTextareaProps } from './attachments/mention-list';
import type { PlusView } from './attachments/plus-sheet';
import type { ComposerAttachments } from './attachments/use-composer-attachments';
import { SlashCommandMenu, type SlashPick } from '@/features/rafii-commands/command-menu';
import type { SlashCommand } from '@/lib/agent-runtime/commands';
import { ModelPicker } from './model-picker';
import { DeliveryPlanner, type DeliveryTargetOption } from './delivery-planner';
import { DeliverySummary, type DeliverySummaryRow } from './delivery-summary';
import type { ChannelLanguages } from './use-channel-languages';

/** A conversation turn's message text, mirroring the server's cap (ideas.MAX_TEXT). Unlike the Home quick
 *  start, which seeds a new idea and allows up to 20,000 characters, a turn is a follow-up message. */
export const MESSAGE_MAX = 6000;

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
  /** The concrete model a turn uses (on Auto, the one Auto resolves to): sending needs it to be qualified. */
  model: string;
  /** What the person chose, AUTO_MODEL or an id; the picker shows it. Defaults to `model`. */
  modelSelection?: string;
  /** Offers Auto in the picker: its label and the option it resolves to. */
  autoModel?: { label: string; option: ModelOption | undefined };
  onModel: (id: string) => void;
  reasoning?: string;
  reasoningOptions?: { id: string; detail: string; label?: string }[];
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
  /** Opens the staged Channel × Language planner without introducing a second persistent store. */
  deliveryPlanner: { open: boolean; onOpenChange: (open: boolean) => void; options: readonly DeliveryTargetOption<DraftPlatform>[] };
  /** Chat attachments (chat-context SPEC §11.2): chips, uploads and the `@` list; the bar sits between the text and Delivery Summary. */
  attachments?: ComposerAttachments;
  attachmentBar?: Omit<AttachmentBarProps, 'attachments' | 'requestedView' | 'onRequestedViewHandled'>;
  slash?: { commands?: SlashCommand[]; onPick: (command: SlashCommand, args: string, pick: SlashPick) => void; onDismiss?: () => void };
}

/** "More…" in the `@` list opens the ＋ sheet at the view of its best match. */
const MORE_VIEW: Record<string, PlusView> = { post: 'posts', template: 'templates', source: 'sources', skill: 'skills', connector_item: 'connectors', account: 'accounts', folder: 'accounts', image: 'library', video: 'library' };

/**
 * One composer for Home and every conversation: text, the channels to draft for, each channel's
 * languages, and the model that will write. Channels named inside the message win over the chips
 * (the server parses them); a language named in the message wins for its channels, and the chips
 * show it with an amber dot. The brief's own language never decides a post's language.
 */
export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSubmit, busy, disabled, submitDisabled, placeholder, chips, languages, models, model, modelSelection, autoModel, onModel, reasoning, reasoningOptions, onReasoning, voiceMode = 'neutral', onVoiceMode, voiceAvailable = false, imageGeneration, consent, submitLabel, compact, hint, accountLabel, deliveryPlanner, attachments, attachmentBar, slash },
  ref
) {
  // An unavailable model is never swapped for another paid one: the person chooses again. Send also waits for uploads (SPEC §4.7).
  const canSend = !submitDisabled && (imageGeneration?.enabled || models.some((m) => m.id === model && m.qualified && m.priced !== false)) && !busy && !disabled && value.trim().length > 0 && languages.selection.length > 0 && (!consent || consent.use) && (!imageGeneration?.enabled || imageGeneration.available) && !attachments?.blockers.length;
  const textareaRef = attachments?.textareaRef;
  // The forwarded ref and the attachments' own ref point at the same textarea.
  const setTextarea = useCallback(
    (element: HTMLTextAreaElement | null) => {
      if (typeof ref === 'function') ref(element);
      else if (ref) ref.current = element;
      if (textareaRef) textareaRef.current = element;
    },
    [ref, textareaRef]
  );
  const [moreView, setMoreView] = useState<PlusView | null>(null);
  const [caret, setCaret] = useState(value.length);
  const deliveryPlannerId = useId();
  const composerBox = useRef<HTMLDivElement>(null);
  const mention = attachments?.mention;
  const activeOption = mention?.open ? (mentionOptions(mention.listId, mention.query, mention.items)[mention.active]?.id ?? null) : null;
  const parsed = useMemo(() => locales.parseMessageLanguages(value), [value]);
  // One chip per selected account (two accounts on one platform stay two chips); a platform with no
  // selected account keeps its single platform chip.
  const rows = chips.flatMap((chip) => {
    const items = languages.selection.filter((item) => item.platform === chip.platform);
    return (items.length ? items : [null]).map((selection) => {
      const on = Boolean(selection) || parsed.perPlatform.has(chip.platform);
      const current = languages.languagesOf(selection ?? { platform: chip.platform, languages: null });
      const effective: EffectiveDeliveryLanguage[] = locales
        .effectiveLanguages(chip.platform, current, parsed)
        .map((item) => ({ tag: item.tag, label: locales.displayName(item.tag), fromMessage: item.fromMessage, index: item.fromMessage ? null : current.indexOf(item.tag) }));
      const account = selection?.channelId ? (accountLabel?.(selection.channelId) ?? chip.account) : chip.account;
      const key = selection?.key ?? chip.platform;
      return { chip, on, effective, key, account };
    });
  });
  const activeRows = rows.filter((row) => row.on);
  const summaryRows: DeliverySummaryRow[] = activeRows.map((row) => ({ key: row.key, platform: row.chip.platform, account: row.account, languages: row.effective }));
  const messageLanguages = Object.fromEntries(activeRows.map((row) => [row.key, row.effective.filter((language) => language.fromMessage).map((language) => language.tag)]));
  const reminder = reminderFor(activeRows, languages);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // The `@` list's keys first (Escape closes only the list), then send; never while an IME is composing.
    if (attachments?.textareaProps.onKeyDown(event)) return;
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && canSend && !isImeEvent(event) && !attachments?.ime.composing(event)) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <>
      <div ref={composerBox} className='rafii-composer @container/composer relative flex flex-col rounded-[var(--rafii-radius-card)]' data-tour='composer'>
      {slash ? <SlashCommandMenu commands={slash.commands} value={value} caret={caret} anchorRef={composerBox} onPick={(command, args, pick) => { setCaret(pick.caret); slash.onPick(command, args, pick); }} onDismiss={slash.onDismiss ?? (() => undefined)} /> : null}
      <Textarea
        ref={setTextarea}
        value={value}
        onChange={(event) => { onChange(event.target.value); setCaret(event.target.selectionStart ?? event.target.value.length); }}
        onKeyDown={onKeyDown}
        onInput={(event) => attachments?.textareaProps.onInput(event)}
        onSelect={(event) => { setCaret(event.currentTarget.selectionStart ?? event.currentTarget.value.length); attachments?.textareaProps.onSelect(event); }}
        onCompositionStart={() => attachments?.textareaProps.onCompositionStart()}
        onCompositionEnd={() => attachments?.textareaProps.onCompositionEnd()}
        {...(mention ? mentionTextareaProps(mention.open, mention.listId, activeOption) : {})}
        rows={compact ? 2 : 4}
        maxLength={MESSAGE_MAX}
        disabled={disabled}
        aria-label='Message'
        placeholder={placeholder}
        className='min-h-0 resize-none border-0 bg-transparent px-4 pt-4 text-base shadow-none focus-visible:ring-0 md:text-[15px] dark:bg-transparent'
      />
      {attachments && attachmentBar && attachments.chips.length > 0 && (
        <div className='px-3 pt-1'>
          <AttachmentBar attachments={attachments} {...attachmentBar} part='chips' />
        </div>
      )}
      {attachments && mention && (
        <MentionList
          open={mention.open}
          listId={mention.listId}
          query={mention.query}
          items={mention.items}
          active={mention.active}
          anchor={attachments.textareaRef}
          onActive={mention.setActive}
          onPick={mention.pick}
          onKeep={mention.close}
          onMore={() => {
            setMoreView(MORE_VIEW[mention.items[0]?.kind ?? ''] ?? 'menu');
            mention.close();
          }}
          onClose={mention.close}
        />
      )}
      <DeliverySummary rows={summaryRows} open={deliveryPlanner.open} controls={deliveryPlannerId} disabled={disabled} onOpen={() => deliveryPlanner.onOpenChange(true)} />
      {/* Tools on one line (same height, same material), the single primary action on the right. */}
      <div className='flex items-center gap-2 px-3 pb-2.5'>
        <div data-slot='composer-tools' className='scrollbar-hide relative flex min-w-0 flex-1 items-center gap-2 overflow-x-auto'>
          {attachments && attachmentBar && (
            <AttachmentBar attachments={attachments} {...attachmentBar} part='plus' requestedView={moreView} onRequestedViewHandled={() => setMoreView(null)} />
          )}
          <ModelPicker compact options={models} model={model} value={modelSelection} auto={autoModel} onChoose={onModel} disabled={disabled || busy} reasoning={reasoning} reasoningOptions={reasoningOptions} onReasoning={onReasoning} />
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
        {!consent && hint && !imageGeneration?.enabled && <span className='text-muted-foreground hidden shrink-0 text-xs @min-xl/composer:inline'>{hint}</span>}
        {/* The limit only matters near it. */}
        {value.length > MESSAGE_MAX * 0.8 && (
          <span className='text-muted-foreground shrink-0 text-xs tabular-nums' aria-live='polite'>
            {value.length.toLocaleString()} / {MESSAGE_MAX.toLocaleString()}
          </span>
        )}
        <Button variant='action' size='icon-control' className='shrink-0 rounded-full' disabled={!canSend} onClick={onSubmit} aria-label={submitLabel ?? 'Send'}>
          <ActionSwapIcon value={busy ? 'busy' : 'send'} animation='blur' className='size-4'>
            {busy ? <Icons.spinner className='size-4 animate-spin motion-reduce:animate-none' /> : <Icons.send className='size-4' />}
          </ActionSwapIcon>
        </Button>
      </div>
      {attachments && (attachments.blockerMessage || attachments.readingMessage || attachments.imageGenerationNotice) && (
        <div className='border-border/60 text-muted-foreground border-t px-4 py-2 text-xs'>{attachments.blockerMessage ?? attachments.readingMessage ?? attachments.imageGenerationNotice}</div>
      )}
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
      {!consent && hint && (!compact || imageGeneration?.enabled) && <div className='text-muted-foreground border-border/60 border-t px-4 py-2 text-xs'>{hint}</div>}
      </div>
      <DeliveryPlanner
        id={deliveryPlannerId}
        open={deliveryPlanner.open}
        onOpenChange={deliveryPlanner.onOpenChange}
        selection={languages.selection}
        languages={languages}
        options={deliveryPlanner.options}
        messageLanguages={messageLanguages}
      />
    </>
  );
});

interface EffectiveDeliveryLanguage {
  tag: LocaleTag;
  label: string;
  fromMessage: boolean;
  index: number | null;
}

/** The first language reminder for the selected channels (languages plan §8). Reminders never block sending. */
function reminderFor(rows: { chip: ChannelChip; effective: EffectiveDeliveryLanguage[] }[], languages: ChannelLanguages<DraftPlatform>) {
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
