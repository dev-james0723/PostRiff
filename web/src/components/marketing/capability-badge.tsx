import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Per-channel capability levels. The colour semantics are shared across the
 * whole product (marketing, channel matrix, calendar, queue, analytics):
 *   Direct = green · Assisted = amber · Local = blue · Unsupported = grey
 */
export type CapabilityLevel = 'direct' | 'assisted' | 'local' | 'unsupported';

export const CAPABILITY_LEVELS: Record<CapabilityLevel, { label: string; description: string }> = {
  direct: {
    label: 'Direct',
    description: 'Rafii publishes through the provider API after you approve.'
  },
  assisted: {
    label: 'Assisted',
    description: 'Rafii prepares the post; a reviewed connector or you completes the final step.'
  },
  local: {
    label: 'Local',
    description: 'Runs through the desktop companion on your own machine and login.'
  },
  unsupported: {
    label: 'Unsupported',
    description: 'Not available yet.'
  }
};

const LEVEL_CLASSES: Record<CapabilityLevel, string> = {
  direct:
    'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-300',
  assisted:
    'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-300',
  local:
    'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:border-sky-400/30 dark:bg-sky-400/10 dark:text-sky-300',
  unsupported: 'border-border bg-muted text-muted-foreground'
};

const DOT_CLASSES: Record<CapabilityLevel, string> = {
  direct: 'bg-emerald-500 dark:bg-emerald-400',
  assisted: 'bg-amber-500 dark:bg-amber-400',
  local: 'bg-sky-500 dark:bg-sky-400',
  unsupported: 'bg-muted-foreground/50'
};

/** Utility for consumers that need only the dot colour (tables, legends). */
export function capabilityDotClass(level: CapabilityLevel) {
  return DOT_CLASSES[level];
}

interface CapabilityBadgeProps extends React.ComponentProps<'span'> {
  level: CapabilityLevel;
  /** Override the visible label (for example "Assisted · review pending"). */
  label?: string;
  size?: 'sm' | 'md';
}

export function CapabilityBadge({
  level,
  label,
  size = 'sm',
  className,
  ...props
}: CapabilityBadgeProps) {
  const meta = CAPABILITY_LEVELS[level];
  return (
    <span
      title={meta.description}
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border font-medium whitespace-nowrap',
        size === 'sm' ? 'h-5 px-2 text-[11px]' : 'h-6 px-2.5 text-xs',
        LEVEL_CLASSES[level],
        className
      )}
      {...props}
    >
      <span aria-hidden className={cn('size-1.5 rounded-full', DOT_CLASSES[level])} />
      {label ?? meta.label}
    </span>
  );
}
