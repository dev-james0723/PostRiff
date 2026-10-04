'use client';

import { useKBar } from 'kbar';
import { Icons } from '@/components/icons';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { FounderPanelLauncher } from '@/features/founder/agent/launcher';
import { FounderNotificationBell } from '@/features/notifications/founder-notification-bell';
import { ModePill } from '@/features/founder/shared/mode-pill';
import { FounderBreadcrumbs } from './founder-breadcrumbs';
import { useFounderSession } from './founder-session';

/** The founder top bar: menu, breadcrumbs, ⌘K search, the Live/Demo pill, Ask Rafii, theme and sign out. */
export function FounderHeader() {
  const { query } = useKBar();
  const { mode, setMode, signOut } = useFounderSession();
  return (
    <header className='rafii-panel sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-2 max-[320px]:h-auto max-[320px]:flex-wrap max-[320px]:py-2 md:h-[3.75rem]'>
      <div className='flex min-w-0 flex-1 items-center gap-2 px-3 max-[320px]:basis-full sm:px-4 md:max-lg:gap-1'>
        <SidebarTrigger className='-ml-1' />
        <Separator orientation='vertical' className='mr-2 h-4 md:max-lg:mr-1 data-vertical:self-center' />
        <FounderBreadcrumbs />
      </div>
      <div className='flex shrink-0 items-center gap-1.5 px-3 max-[320px]:w-full max-[320px]:min-w-0 max-[320px]:flex-wrap sm:gap-2 sm:px-4'>
        <Button type='button' variant='ghost' size='icon' onClick={query.toggle} aria-label='Search pages and actions' aria-keyshortcuts='Meta+K Control+K' title='Search (⌘K)'>
          <Icons.search className='size-[1.2rem]' />
        </Button>
        <ModePill mode={mode} onChange={setMode} />
        <FounderPanelLauncher />
        <FounderNotificationBell />
        <div className='hidden sm:block'>
          <ThemeModeToggle />
        </div>
        <Button type='button' variant='ghost' size='icon' onClick={() => void signOut()} aria-label='Sign out' title='Sign out' className='hidden md:inline-flex'>
          <Icons.logout className='size-[1.2rem]' />
        </Button>
      </div>
    </header>
  );
}
