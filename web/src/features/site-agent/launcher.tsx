'use client';

import { buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';
import { LAUNCHER_ID, PANEL_ID } from './panel';
import { RafiiAvatar } from './rafii-avatar';
import { panelStore, usePanel } from './store';

/** The header entry point to Rafii on every app page (⌘J / Ctrl+J). */
export function SiteAgentLauncher() {
  // Shown either docked/as a sheet (`open`) or as a sheet above another dialog (`above`).
  const open = usePanel((s) => s.open || s.above);
  const busy = usePanel((s) => Object.values(s.busy).some(Boolean));
  return (
    <button
      id={LAUNCHER_ID}
      type='button'
      aria-label={`${open ? 'Close' : 'Ask'} ${siteConfig.name}`}
      aria-expanded={open}
      aria-controls={PANEL_ID}
      aria-keyshortcuts='Meta+J Control+J'
      title={`Ask ${siteConfig.name} (⌘J)`}
      onClick={() => (panelStore.get().above ? panelStore.setAbove(false) : panelStore.toggle())}
      className={cn(buttonVariants({ variant: open ? 'glass' : 'quiet', size: 'sm' }), 'rafii-focus h-9 min-w-9 gap-1.5 px-1.5 sm:px-2', open && 'rafii-glass-selected')}
    >
      <RafiiAvatar size={24} thinking={busy} />
      <span className='hidden text-sm sm:inline'>Ask {siteConfig.name}</span>
    </button>
  );
}
