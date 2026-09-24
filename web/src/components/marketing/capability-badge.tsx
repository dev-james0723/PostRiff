import * as React from 'react';
import { Icons, type Icon } from '@/components/icons';
import { cn } from '@/lib/utils';

/**
 * Per-channel capability levels, shared across the product (marketing, channel matrix, inbox,
 * connect sheet). Rafii chrome is monochrome (DNA §2.2, §4.3): the level is carried by a glyph
 * and its text, never by an ad hoc colour, so it reads the same in both themes and on glass.
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

/** One glyph per level: done by Rafii · finished by you · on your machine · not offered. */
const LEVEL_ICONS: Record<CapabilityLevel, Icon> = {
  direct: Icons.check,
  assisted: Icons.userPen,
  local: Icons.laptop,
  unsupported: Icons.slash
};

const LEVEL_CLASSES: Record<CapabilityLevel, string> = {
  direct: 'rafii-quiet text-foreground',
  assisted: 'rafii-quiet text-foreground',
  local: 'rafii-quiet text-foreground',
  unsupported: 'rafii-quiet text-muted-foreground'
};

/** Monochrome tones for consumers that draw only a mark beside their own label (tables, legends). */
const DOT_CLASSES: Record<CapabilityLevel, string> = {
  direct: 'bg-foreground',
  assisted: 'bg-foreground/60',
  local: 'bg-foreground/40',
  unsupported: 'bg-muted-foreground/40'
};

/** Utility for consumers that need only the mark (tables, legends). */
export function capabilityDotClass(level: CapabilityLevel) {
  return DOT_CLASSES[level];
}

/** The level's glyph, for rows that carry the label themselves. */
export function CapabilityIcon({ level, className }: { level: CapabilityLevel; className?: string }) {
  const Glyph = LEVEL_ICONS[level];
  return <Glyph aria-hidden className={cn('size-3.5 shrink-0', className)} />;
}

interface CapabilityBadgeProps extends React.ComponentProps<'span'> {
  level: CapabilityLevel;
  /** Override the visible label (for example "Assisted · review pending"). */
  label?: string;
  size?: 'sm' | 'md';
}

export function CapabilityBadge({ level, label, size = 'sm', className, ...props }: CapabilityBadgeProps) {
  const meta = CAPABILITY_LEVELS[level];
  return (
    <span
      title={meta.description}
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full font-medium whitespace-nowrap',
        size === 'sm' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-[13px]',
        LEVEL_CLASSES[level],
        className
      )}
      {...props}
    >
      <CapabilityIcon level={level} className={size === 'sm' ? 'size-3' : 'size-3.5'} />
      {label ?? meta.label}
    </span>
  );
}
