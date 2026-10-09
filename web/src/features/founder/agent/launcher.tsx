'use client';

import { motion, useReducedMotion } from 'motion/react';
import { buttonVariants } from '@/components/ui/button';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { cn } from '@/lib/utils';
import { LAUNCHER_ID, PANEL_ID } from './panel';
import { founderPanelStore, useFounderPanel } from './store';

/** The header entry point to Founder Rafii (⌘J / Ctrl+J). */
export function FounderPanelLauncher() {
  const open = useFounderPanel((s) => s.open || s.above);
  const busy = useFounderPanel((s) => Object.values(s.busy).some(Boolean));
  const reduce = useReducedMotion();
  return (
    <motion.button
      layout
      initial={false}
      transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 330, damping: 34 }}
      id={LAUNCHER_ID}
      type='button'
      aria-label={busy ? 'Rafii is working. Open agent.' : `${open ? 'Close' : 'Ask'} Rafii`}
      aria-expanded={open}
      aria-controls={PANEL_ID}
      aria-keyshortcuts='Meta+J Control+J'
      title='Ask Rafii (⌘J)'
      onClick={() => (founderPanelStore.get().above ? founderPanelStore.setAbove(false) : founderPanelStore.toggle())}
      className={cn(buttonVariants({ variant: open ? 'glass' : 'quiet', size: 'sm' }), 'rafii-focus h-11 min-w-11 gap-1.5 rounded-full px-2 sm:px-3', open && 'rafii-glass-selected', busy && 'bg-foreground text-background hover:bg-foreground/90')}
    >
      <RafiiAvatar size={24} thinking={busy} />
      <span className='hidden max-w-32 truncate text-sm sm:inline'>{busy ? 'Rafii · Working…' : 'Ask Rafii'}</span>
    </motion.button>
  );
}
