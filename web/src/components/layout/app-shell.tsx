'use client';

import type { WorkspaceBootstrap } from '@/lib/workspace/bootstrap';
import { Suspense } from 'react';
import KBar from '@/components/kbar';
import { InfoSidebar } from '@/components/layout/info-sidebar';
import { InfobarProvider } from '@/components/ui/infobar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { AuthProvider } from '@/lib/auth/session';
import { PreferencesProvider } from '@/lib/preferences';
import { WorkspaceProvider } from '@/lib/workspace/provider';
import { AppGate } from './app-gate';
import AppSidebar from './app-sidebar';
import Header from './header';
import { MobileTabBar } from './mobile-tab-bar';
import { ShortcutsDialog } from './shortcuts-dialog';

/**
 * Client shell for /app/*: session → workspace → gate → sidebar + Cmd+K +
 * header + contextual info sidebar. Server work (cookie for the sidebar
 * state, metadata) stays in `src/app/app/layout.tsx`.
 */
export function AppShell({ defaultOpen, children, initial }: { defaultOpen: boolean; children: React.ReactNode; initial?: WorkspaceBootstrap | null }) {
  return (
    <AuthProvider initial={initial}>
      <WorkspaceProvider initial={initial}>
        <Suspense fallback={null}>
          <AppGate>
            <PreferencesProvider>
            <KBar>
              <SidebarProvider defaultOpen={defaultOpen}>
                <a
                  href='#main-content'
                  className='bg-background ring-ring sr-only rounded-md px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:absolute focus:top-2 focus:start-2 focus:z-50 focus:ring-2'
                >
                  Skip to content
                </a>
                <AppSidebar />
                <SidebarInset id='main-content' tabIndex={-1} className='relative isolate min-w-0 scroll-mt-16 pb-[calc(4.25rem+env(safe-area-inset-bottom))] md:pb-0'>
                  <div aria-hidden data-extent='viewport' className='rafii-ambient' />
                  <Header />
                  <InfobarProvider defaultOpen={false}>
                    {children}
                    <InfoSidebar side='right' />
                  </InfobarProvider>
                </SidebarInset>
                <MobileTabBar />
                <ShortcutsDialog />
              </SidebarProvider>
            </KBar>
            </PreferencesProvider>
          </AppGate>
        </Suspense>
      </WorkspaceProvider>
    </AuthProvider>
  );
}
