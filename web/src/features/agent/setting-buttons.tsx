'use client';

import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { IconCpu, IconWaveSine, IconWorld } from '@tabler/icons-react';
import { cn } from '@/lib/utils';

export interface SettingButtonProps extends Omit<ComponentPropsWithoutRef<'button'>, 'value' | 'children'> {
  icon: ReactNode;
  /** "Language", "Model", "Writing Voice". */
  kicker: string;
  /** The current value, summarised; it wraps rather than shrinking. */
  value: ReactNode;
  /** Whether the dialog this button opens is open right now. */
  expanded?: boolean;
  /** Id of the dialog it controls, when that dialog is in the DOM. */
  controls?: string;
  /** `dialog` (default) for a button that opens a dialog; `none` for one that acts in place (pass `aria-pressed` yourself). */
  popup?: 'dialog' | 'none';
}

/**
 * One glass setting button of the composer (DNA v8 §15.1; prototype `.glass-setting-button`):
 * icon, kicker and the current value. Values wrap and stay readable (12px minimum, never the
 * prototype's 9–10px); the surface is borderless glass with a visible focus outline.
 */
export function SettingButton({ icon, kicker, value, expanded = false, controls, popup = 'dialog', className, type = 'button', ...props }: SettingButtonProps) {
  const dialog = popup === 'dialog';
  return (
    <button
      type={type}
      aria-haspopup={dialog ? 'dialog' : undefined}
      aria-expanded={dialog ? expanded : undefined}
      aria-controls={dialog && expanded ? controls : undefined}
      className={cn(
        'rafii-glass hover:rafii-glass-selected aria-expanded:rafii-glass-selected aria-pressed:rafii-glass-selected rafii-focus flex min-h-20 min-w-0 flex-col items-start justify-start gap-1 rounded-[var(--rafii-radius-card)] px-2.5 py-3 text-left min-[400px]:px-3.5 transition-[transform,background-color,box-shadow] duration-200 ease-[var(--rafii-ease-ui)] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 motion-reduce:active:scale-100',
        className
      )}
      {...props}
    >
      <span aria-hidden className='text-muted-foreground mb-0.5 flex [&>svg]:size-[17px]'>
        {icon}
      </span>
      <span className='text-foreground text-[13px] leading-tight font-medium'>{kicker}</span>
      {/* Long values (model names) hyphenate at syllables before breaking, never mid-word at random. */}
      <span className='text-muted-foreground w-full text-xs leading-snug break-words hyphens-auto'>{value}</span>
    </button>
  );
}

export interface SettingSummary {
  value: ReactNode;
  onClick: () => void;
  expanded?: boolean;
  disabled?: boolean;
  controls?: string;
  title?: string;
}

export interface SettingButtonsProps {
  language: SettingSummary;
  model: SettingSummary;
  /** Writing Voice opens a dialog by default; with `popup: 'none'` it toggles in place and `pressed` marks the state. */
  voice: SettingSummary & { popup?: 'dialog' | 'none'; pressed?: boolean };
  label?: string;
  className?: string;
}

/** The composer's three settings, side by side; one column on the narrowest phones (≤374px). */
export function SettingButtons({ language, model, voice, label = 'Draft settings', className }: SettingButtonsProps) {
  return (
    <div role='group' aria-label={label} className={cn('grid grid-cols-1 gap-2 min-[375px]:grid-cols-3', className)}>
      <SettingButton icon={<IconWorld />} kicker='Language' value={language.value} expanded={language.expanded} controls={language.controls} disabled={language.disabled} title={language.title} onClick={language.onClick} />
      <SettingButton icon={<IconCpu />} kicker='Model' value={model.value} expanded={model.expanded} controls={model.controls} disabled={model.disabled} title={model.title} onClick={model.onClick} />
      <SettingButton
        icon={<IconWaveSine />}
        kicker='Writing Voice'
        value={voice.value}
        popup={voice.popup}
        expanded={voice.expanded}
        controls={voice.controls}
        aria-pressed={voice.popup === 'none' ? Boolean(voice.pressed) : undefined}
        disabled={voice.disabled}
        title={voice.title}
        onClick={voice.onClick}
      />
    </div>
  );
}
