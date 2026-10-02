'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { InfoSidebar } from '@/components/layout/info-sidebar';
import { founderPanelStore } from '@/features/founder/agent/store';
import { FounderMotionRoot } from '@/features/founder/motion/founder-motion-root';
import type { FounderAskRequest } from '@/features/founder/sections';
import { registrationFromAsk } from './section-page';
import { InfobarProvider } from '@/components/ui/infobar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { FounderPanelAbove, FounderPanelDock, FounderPanelHotkeys, FounderPanelOverlay } from '@/features/founder/agent/panel';
import { DemoBanner } from '@/features/founder/shared/demo-banner';
import { EvidenceDrawer } from '@/features/founder/shared/evidence-drawer';
import { FounderCommandPalette } from './founder-command-palette';
import { makeFounderQueryClient } from './founder-query-client';
import { FounderHeader } from './founder-header';
import { FounderSessionProvider } from './founder-session';
import { FounderSidebar } from './founder-sidebar';
import { FounderTabBar } from './founder-tab-bar';

/** The event name the domain pages' `dispatchAsk` uses when no `onAsk` was passed (`features/founder/customers/kit/ask.tsx`). */
const FOUNDER_ASK_EVENT = 'rafii:founder-ask';

/** Any page can hand Rafii a question by event; the panel opens with the words and the page's context. */
function FounderAskBridge() {
  useEffect(() => {
    const onAsk = (event: Event) => {
      const request = (event as CustomEvent<FounderAskRequest>).detail;
      if (!request || typeof request.prompt !== 'string') return;
      founderPanelStore.ask(request.prompt, registrationFromAsk(request));
    };
    window.addEventListener(FOUNDER_ASK_EVENT, onAsk);
    return () => window.removeEventListener(FOUNDER_ASK_EVENT, onAsk);
  }, []);
  return null;
}

/**
 * Client shell for `/founder/*` (CONTRACTS §6): founder session → ⌘K → sidebar + header + Demo banner + the page's
 * info rail, with Founder Rafii docked or as a sheet, the phone tab bar and the evidence drawer. The server layout
 * (`app/founder/layout.tsx`) already turned away a browser without the control cookie; the session read here is what
 * proves the cookie is still good.
 */
export function FounderShell({ defaultOpen, children }: { defaultOpen: boolean; children: ReactNode }) {
  const [queryClient] = useState(makeFounderQueryClient);
  return (
    <FounderMotionRoot>
    <QueryClientProvider client={queryClient}>
    <FounderSessionProvider>
      <FounderCommandPalette>
        <SidebarProvider defaultOpen={defaultOpen}>
          <a href='#main-content' className='bg-background ring-ring sr-only rounded-md px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:absolute focus:top-2 focus:start-2 focus:z-50 focus:ring-2'>
            Skip to content
          </a>
          <FounderSidebar />
          <SidebarInset id='main-content' tabIndex={-1} className='relative isolate min-w-0 scroll-mt-16 pb-[calc(4.25rem+env(safe-area-inset-bottom))] md:pb-0'>
            <div aria-hidden data-extent='viewport' className='rafii-ambient' />
            <FounderHeader />
            <DemoBanner />
            <InfobarProvider defaultOpen={false}>
              {children}
              <InfoSidebar side='right' />
            </InfobarProvider>
          </SidebarInset>
          <FounderPanelDock />
          <FounderPanelOverlay />
          <FounderPanelAbove />
          <FounderPanelHotkeys />
          <FounderTabBar />
          <EvidenceDrawer />
          <FounderAskBridge />
        </SidebarProvider>
      </FounderCommandPalette>
    </FounderSessionProvider>
    </QueryClientProvider>
    </FounderMotionRoot>
  );
}