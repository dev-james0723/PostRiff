'use client';

import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Icons, type Icon } from '@/components/icons';
import { RAFII_EASE, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

/** The six status roles the queue and the calendar already speak (`jobBadge().status`, `KIND_META.status`). */
export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'loading';

/* A distinct glyph per role, so success and failure never come down to a grey dot (DNA §4.3). */
const ICON: Record<StatusTone, Icon> = {
  neutral: Icons.circleDashed,
  info: Icons.clock,
  success: Icons.circleCheck,
  warning: Icons.warning,
  danger: Icons.circleX,
  loading: Icons.spinner
};

/*
 * Monochrome by rule (DNA §2.2, §4.3): the icon and the label carry the state; the material only decides how much
 * light the chip catches. `danger` uses the one approved semantic tint token; there is no amber/emerald token yet.
 */
const TONE: Record<StatusTone, string> = {
  neutral: 'rafii-quiet text-muted-foreground',
  info: 'rafii-quiet text-foreground',
  success: 'rafii-quiet text-foreground',
  warning: 'rafii-lens text-foreground',
  danger: 'rafii-quiet text-destructive',
  loading: 'rafii-quiet text-foreground'
};

const SIZE = {
  sm: 'min-h-6 gap-1 px-2 text-xs [&_svg]:size-3',
  md: 'min-h-8 gap-1.5 px-3 text-[13px] [&_svg]:size-3.5'
} as const;

export interface StatusChipProps extends Omit<ComponentPropsWithoutRef<'span'>, 'children'> {
  tone?: StatusTone;
  size?: keyof typeof SIZE;
  children?: ReactNode;
  /** Replaces the tone's glyph. */
  icon?: ReactNode;
  showIcon?: boolean;
  /** A soft pulse on the glyph while something is genuinely in progress; stops under reduced motion. */
  pulse?: boolean;
  /** Replays the label roll when the text itself is reused for a different state. */
  contentKey?: string | number;
}

/**
 * A status label in the monochrome system: glyph + text on a quiet or lens material. The label rolls when the state
 * changes (the meaningful motion `AnimatedBadge` had) and stays put under the shared motion preference.
 */
export function StatusChip({ tone = 'neutral', size = 'sm', children, icon, showIcon = true, pulse = false, contentKey, className, ...rest }: StatusChipProps) {
  const { reduced } = useMotionPreference();
  const Glyph = ICON[tone];
  const key = contentKey ?? (typeof children === 'string' || typeof children === 'number' ? children : tone);
  return (
    <span
      className={cn('relative inline-flex shrink-0 items-center rounded-full font-medium whitespace-nowrap tabular-nums transition-colors duration-200', TONE[tone], SIZE[size], className)}
      {...rest}
    >
      {showIcon && (
        <span aria-hidden className={cn('rafii-decorative-motion inline-flex shrink-0 items-center justify-center', pulse && 'animate-pulse motion-reduce:animate-none')}>
          {icon ?? <Glyph className={cn(tone === 'loading' && 'animate-spin motion-reduce:animate-none')} />}
        </span>
      )}
      {children != null && (
        <span className='relative inline-flex overflow-hidden'>
          <AnimatePresence mode='popLayout' initial={false}>
            <motion.span
              key={String(key)}
              initial={reduced ? false : { opacity: 0, y: '70%' }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduced ? undefined : { opacity: 0, y: '-70%' }}
              transition={{ duration: 0.22, ease: RAFII_EASE.soft }}
              className='inline-block'
            >
              {children}
            </motion.span>
          </AnimatePresence>
        </span>
      )}
    </span>
  );
}
