'use client';

import Link from 'next/link';
import { NotificationBell } from './notification-bell';
import { Breadcrumbs } from '@/components/breadcrumbs';
import { Icons } from '@/components/icons';
import { LiveIsland } from '@/components/layout/live-island';
import SearchInput, { SearchIconButton } from '@/components/search-input';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { ThemeSelector } from '@/components/themes/theme-selector';
import { buttonVariants } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { HelpMenu } from '@/features/onboarding/help-menu';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { cn } from '@/lib/utils';

export default function Header() {
  const access = useWorkspaceAccess();
  return (
    <header className='bg-background/60 sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-2 backdrop-blur-md md:h-14'>
      <div className='flex items-center gap-2 px-4'>
        <SidebarTrigger className='-ml-1' />
        <Separator orientation='vertical' className='mr-2 h-4 data-vertical:self-center' />
        <Breadcrumbs />
      </div>
      {/* Live publishing status. The track takes only the free space between the breadcrumbs and
          the actions (-mx-1 cancels the extra flex gap, so nothing else moves); the island shows
          when that space fits the pill and expands over the page instead of pushing layout. */}
      <div className='@container/island relative z-10 -mx-1 hidden min-w-0 flex-1 self-stretch md:block'>
        <div className='pointer-events-none absolute inset-x-0 top-2.5 hidden justify-center @[11rem]/island:flex'>
          <LiveIsland />
        </div>
      </div>
      <div className='flex items-center gap-2 px-4'>
        {/* One place to start a post: Home's composer (focused by ?new=1). Ideas captures sources. */}
        {checkAccess(access, { permission: 'edit' }) && (
          <Link aria-label='Create a new draft' href='/app?new=1' className={cn(buttonVariants({ size: 'sm' }), 'gap-1')}>
            <Icons.add className='size-4' />
            <span className='hidden sm:inline'>Create</span>
          </Link>
        )}
        {/* The header keeps to one row at every width: the wide search field and the theme picker
            appear only where they fit beside an open sidebar; below that the search icon opens the
            same ⌘K palette, which also carries the theme actions. */}
        <div className='hidden lg:flex'>
          <SearchInput />
        </div>
        <SearchIconButton />
        <NotificationBell />
        <HelpMenu />
        <div className='hidden sm:block'><ThemeModeToggle /></div>
        <div className='hidden xl:block'>
          <ThemeSelector />
        </div>
      </div>
    </header>
  );
}
