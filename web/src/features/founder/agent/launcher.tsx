'use client';

import { buttonVariants } from '@/components/ui/button';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { cn } from '@/lib/utils';
import { LAUNCHER_ID, PANEL_ID } from './panel';
import { founderPanelStore, useFounderPanel } from './store';

/** The header entry point to Founder Rafii (⌘J / Ctrl+J). */
export function FounderPanelLauncher() {
  const open = useFounderPanel((s) => s.open || s.above);
  const busy = useFounderPanel((s) => Object.values(s.busy).some(Boolean));
  return (
    <button
      id={LAUNCHER_ID}
      type='button'
      aria-label={`${open ? 'Close' : 'Ask'} Rafii`}
      aria-expanded={open}
      aria-controls={PANEL_ID}
      aria-keyshortcuts='Meta+J Control+J'
      title='Ask Rafii (⌘J)'
      onClick={() => (founderPanelStore.get().above ? founderPanelStore.setAbove(false) : founderPanelStore.toggle())}
      className={cn(buttonVariants({ variant: open ? 'glass' : 'quiet', size: 'sm' }), 'rafii-focus h-9 min-w-9 gap-1.5 px-1.5 sm:px-2', open && 'rafii-glass-selected')}
    >
      <RafiiAvatar size={24} thinking={busy} />
      <span className='hidden text-sm sm:inline'>Ask Rafii</span>
    </button>
  );
}
