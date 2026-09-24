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
  /** Visible name when it is not the platform alone (an account chip: "LinkedIn · Dev Member"). */
  label?: string;
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
export function ChannelLanguageChip({ platform, label, account, state, on, languages, channelCount, suggestions, disabled, onToggle, onChange, onAdd, onRemove, onUseEverywhere }: ChannelLanguageChipProps) {
  const name = label ?? platform;
  const reduce = useReducedMotion();
  const ready = state === 'Ready for posting';
  const own = languages.filter((l) => !l.fromMessage).length;

  return (
    // One pill per destination (DNA §10): a single height, glass when drafting, quiet when off; segments never wrap.
    <div className={cn('inline-flex h-10 shrink-0 items-stretch overflow-hidden rounded-full text-xs whitespace-nowrap sm:h-9', on ? 'rafii-glass text-foreground' : 'rafii-quiet text-muted-foreground')}>
      <motion.button
        type='button'
        aria-pressed={on}
        disabled={disabled}
        onClick={onToggle}
        title={account ? `${account} · ${state ?? 'connected'}` : 'No account connected yet · drafts only'}
        whileTap={reduce || disabled ? undefined : { scale: 0.96 }}
        transition={SPRING_PRESS}
        className={cn('rafii-focus inline-flex items-center gap-2 rounded-full pr-3 pl-2 font-medium transition-colors', !on && 'hover:text-foreground')}
      >
        <span className={cn('relative inline-flex', !on && 'opacity-60 grayscale')}>
          <ChannelIcon platform={platform} size='xs' />
          {/* Readiness in the monochrome palette: filled = ready for posting, hollow = connected but needs setup. */}
          <span aria-hidden className={cn('ring-secondary absolute -right-0.5 -bottom-0.5 size-1.5 rounded-full ring-2', !on && 'ring-background', account ? (ready ? 'bg-foreground' : 'bg-background shadow-[inset_0_0_0_1px_var(--foreground)]') : 'bg-muted-foreground/50')} />
        </span>
        {name}
        {!on && <Icons.add aria-hidden className='-mr-0.5 size-3.5' />}
      </motion.button>
      {on &&
        languages.map((language, k) => {
          const entry = locales.entry(language.tag);
          const actions = [
            ...(channelCount > 1 ? [{ label: <>Use <LanguageName language={language.tag} /> on all {channelCount} channels</>, onClick: () => onUseEverywhere(language.tag) }] : []),
            ...(language.index !== null && own > 1 ? [{ label: `Remove from ${name}`, onClick: () => onRemove(language.index as number), quiet: true }] : [])
          ];
          return (
            <LanguagePicker
              key={`${language.tag}-${k}`}
              title={`Language for ${name}`}
              selected={[language.tag]}
              suggestions={suggestions}
              actions={actions}
              disabled={disabled}
              onPick={(tag) => onChange(language.index, tag)}
              trigger={
                <button
                  type='button'
                  aria-label={`${name} language${languages.length > 1 ? ` ${k + 1} of ${languages.length}` : ''}: ${entry?.english ?? language.tag}${language.fromMessage ? ', named in your message' : ''}. Change`}
                  className='rafii-focus border-foreground/10 hover:bg-foreground/5 data-[popup-open]:bg-foreground/5 inline-flex min-w-0 items-center gap-1 border-l px-2.5 text-foreground'
                >
                  {language.fromMessage && <span aria-hidden className='size-1.5 shrink-0 rounded-full shadow-[inset_0_0_0_1.5px_var(--foreground)]' />}
                  <LanguageName language={language.tag} className='max-w-[15ch]' />
                  <Icons.chevronDown className='text-muted-foreground size-3 shrink-0' />
                </button>
              }
            />
          );
        })}
      {on && (
        <LanguagePicker
          title={`Add a language for ${name}`}
          selected={languages.map((l) => l.tag)}
          suggestions={suggestions}
          disabled={disabled}
          onPick={(tag) => onAdd(tag)}
          trigger={
            <button
              type='button'
              aria-label={`Add another language for ${name}`}
              title='Add another language'
              className='rafii-focus border-foreground/10 text-muted-foreground hover:text-foreground hover:bg-foreground/5 data-[popup-open]:bg-foreground/5 inline-flex items-center rounded-r-full border-l pr-3 pl-2'
            >
              <Icons.add className='size-3.5' />
            </button>
          }
        />
      )}
    </div>
  );
}
