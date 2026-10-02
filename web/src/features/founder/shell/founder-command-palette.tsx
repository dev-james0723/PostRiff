'use client';

import { useMemo, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { KBarAnimator, KBarPortal, KBarPositioner, KBarProvider, KBarSearch, useRegisterActions, type Action } from 'kbar';
import { motion } from 'motion/react';
import { Icons } from '@/components/icons';
import RenderResults from '@/components/kbar/render-result';
import { Kbd } from '@/components/ui/kbd';
import { FOUNDER_NAV_GROUPS, FOUNDER_SECTIONS, founderHref } from '@/config/founder-nav';
import { founderPanelStore } from '@/features/founder/agent/store';
import { useFounderSession } from './founder-session';

/**
 * ⌘K for the founder admin: every section, the data-mode switch, Ask Rafii and sign out. The palette's frame and
 * result rows are the app's own (`components/kbar`); only the actions differ, and none of them read workspace data.
 */
function FounderActions() {
  const router = useRouter();
  const { mode, setMode, signOut } = useFounderSession();
  const actions = useMemo<Action[]>(() => {
    const navigation = FOUNDER_NAV_GROUPS.flatMap((group) =>
      group.items.map((id) => {
        const section = FOUNDER_SECTIONS[id];
        return {
          id: `founder-${id}`,
          name: section.title,
          shortcut: section.shortcut,
          keywords: `${section.title} ${section.question}`.toLowerCase(),
          section: group.label,
          subtitle: section.question,
          perform: () => router.push(founderHref(id, mode))
        } satisfies Action;
      })
    );
    return [
      ...navigation,
      { id: 'founder-mode', name: mode === 'demo' ? 'Switch to Live data' : 'Switch to Demo data', keywords: 'mode demo live data', section: 'Data', perform: () => setMode(mode === 'demo' ? 'live' : 'demo') },
      { id: 'founder-ask', name: 'Ask Rafii', shortcut: ['⌘', 'J'], keywords: 'rafii ask chat agent', section: 'Rafii', perform: () => founderPanelStore.setOpen(true) },
      { id: 'founder-sign-out', name: 'Sign out', keywords: 'sign out logout', section: 'Session', perform: () => void signOut() }
    ];
  }, [mode, router, setMode, signOut]);
  useRegisterActions(actions, [actions]);
  return null;
}

export function FounderCommandPalette({ children }: { children: ReactNode }) {
  return (
    <KBarProvider>
      <FounderActions />
      <KBarPortal>
        <KBarPositioner className='rafii-scrim fixed inset-0 z-99999 flex items-start! justify-center p-4! pt-[14vh]!'>
          <KBarAnimator className='rafii-elevated text-foreground relative mx-auto w-full max-w-[600px] overflow-hidden rounded-[var(--rafii-radius-dialog)]'>
            <motion.div data-founder-motion='01' layout initial={{ opacity: 0, y: -8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.98 }} transition={{ duration: 0.18 }}>
            <div className='sticky top-0 z-10 flex items-center gap-3 px-5 pt-4 pb-3'>
              <Icons.search aria-hidden className='text-muted-foreground size-4 shrink-0' />
              <KBarSearch defaultPlaceholder='Jump to a page or action…' className='placeholder:text-muted-foreground min-w-0 flex-1 border-none bg-transparent py-1.5 text-base outline-hidden focus:ring-0 focus:outline-hidden md:text-sm' />
            </div>
            <div className='h-[400px] pb-1'>
              <RenderResults />
            </div>
            <div className='text-muted-foreground flex items-center gap-3 px-5 pt-2 pb-3 text-xs'>
              <span className='flex items-center gap-1'>
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> navigate
              </span>
              <span className='flex items-center gap-1'>
                <Kbd>↵</Kbd> open
              </span>
              <span className='flex items-center gap-1'>
                <Kbd>esc</Kbd> close
              </span>
            </div>
            </motion.div>
          </KBarAnimator>
        </KBarPositioner>
      </KBarPortal>
      {children}
    </KBarProvider>
  );
}