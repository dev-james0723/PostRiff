'use client';

import { motion, useReducedMotion } from 'motion/react';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { SPRING_PRESS } from '@/lib/ease';
import { locales } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { LanguageName } from './language-badge';
import { LanguagePicker } from './language-picker';

export interface ChipLanguage {
  tag: string;
  /** Named in the message: it wins for this draft and is not remembered. */
  fromMessage: boolean;
  /** Position in the channel's own languages; null when the message supplied it. */
  index: number | null;
}

interface ChannelLanguageChipProps {
  platform: string;
  account?: string;
  state?: string;
  on: boolean;
  languages: ChipLanguage[];
  channelCount: number;
  suggestions: { tag: string; reason: string }[];
  disabled?: boolean;
  onToggle: () => void;
  onChange: (index: number | null, tag: string) => void;
  onAdd: (tag: string) => void;
  onRemove: (index: number) => void;
  onUseEverywhere: (tag: string) => void;
}

/** One channel in the composer: its mark and name, then one button per language, then + (languages plan §4.1, §4.5). */
export function ChannelLanguageChip({ platform, account, state, on, languages, channelCount, suggestions, disabled, onToggle, onChange, onAdd, onRemove, onUseEverywhere }: ChannelLanguageChipProps) {
  const reduce = useReducedMotion();
  const ready = state === 'Ready for posting';
  const own = languages.filter((l) => !l.fromMessage).length;

  return (
    <div className={cn('inline-flex max-w-full flex-wrap items-stretch overflow-hidden rounded-lg border text-xs', on ? 'bg-secondary text-secondary-foreground border-transparent' : 'border-border bg-background text-muted-foreground')}>
      <motion.button
        type='button'
        aria-pressed={on}
        disabled={disabled}
        onClick={onToggle}
        title={account ? `${account} · ${state ?? 'connected'}` : 'No account connected yet · drafts only'}
        whileTap={reduce || disabled ? undefined : { scale: 0.96 }}
        transition={SPRING_PRESS}
        className={cn('inline-flex h-7 items-center gap-1.5 pr-2.5 pl-1.5 font-medium transition-colors', !on && 'hover:text-foreground')}
      >
        <span className={cn('relative inline-flex', !on && 'opacity-60 grayscale')}>
          <ChannelIcon platform={platform} size='xs' />
          <span aria-hidden className={cn('ring-secondary absolute -right-0.5 -bottom-0.5 size-1.5 rounded-full ring-2', !on && 'ring-background', account ? (ready ? 'bg-emerald-500' : 'bg-amber-500') : 'bg-muted-foreground/50')} />
        </span>
        {platform}
      </motion.button>
      {on &&
        languages.map((language, k) => {
          const entry = locales.entry(language.tag);
          const actions = [
            ...(channelCount > 1 ? [{ label: <>Use <LanguageName language={language.tag} /> on all {channelCount} channels</>, onClick: () => onUseEverywhere(language.tag) }] : []),
            ...(language.index !== null && own > 1 ? [{ label: `Remove from ${platform}`, onClick: () => onRemove(language.index as number), quiet: true }] : [])
          ];
          return (
            <LanguagePicker
              key={`${language.tag}-${k}`}
              title={`Language for ${platform}`}
              selected={[language.tag]}
              suggestions={suggestions}
              actions={actions}
              disabled={disabled}
              onPick={(tag) => onChange(language.index, tag)}
              trigger={
                <button
                  type='button'
                  aria-label={`${platform} language${languages.length > 1 ? ` ${k + 1} of ${languages.length}` : ''}: ${entry?.english ?? language.tag}${language.fromMessage ? ', named in your message' : ''}. Change`}
                  className='border-foreground/10 hover:bg-foreground/5 data-[popup-open]:bg-foreground/5 inline-flex h-7 min-w-0 items-center gap-1 border-l px-2 text-foreground'
                >
                  {language.fromMessage && <span aria-hidden className='size-1.5 shrink-0 rounded-full bg-amber-500' />}
                  <LanguageName language={language.tag} className='max-w-[15ch]' />
                  <Icons.chevronDown className='text-muted-foreground size-3 shrink-0' />
                </button>
              }
            />
          );
        })}
      {on && (
        <LanguagePicker
          title={`Add a language for ${platform}`}
          selected={languages.map((l) => l.tag)}
          suggestions={suggestions}
          disabled={disabled}
          onPick={(tag) => onAdd(tag)}
          trigger={
            <button
              type='button'
              aria-label={`Add another language for ${platform}`}
              title='Add another language'
              className='border-foreground/10 text-muted-foreground hover:text-foreground hover:bg-foreground/5 data-[popup-open]:bg-foreground/5 inline-flex h-7 items-center border-l px-2'
            >
              <Icons.add className='size-3.5' />
            </button>
          }
        />
      )}
    </div>
  );
}
