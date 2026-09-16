'use client';

import Link from 'next/link';
import { Breadcrumbs } from '@/components/breadcrumbs';
import { Icons } from '@/components/icons';
import SearchInput from '@/components/search-input';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { ThemeSelector } from '@/components/themes/theme-selector';
import { buttonVariants } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { SidebarTrigger } from '@/components/ui/sidebar';
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
      <div className='flex items-center gap-2 px-4'>
        {checkAccess(access, { permission: 'edit' }) && (
          <Link href='/app/ideas?new=1' className={cn(buttonVariants({ size: 'sm' }), 'gap-1')}>
            <Icons.add className='size-4' />
            <span className='hidden sm:inline'>Create</span>
          </Link>
        )}
        <div className='hidden md:flex'>
          <SearchInput />
        </div>
        <ThemeModeToggle />
        <div className='hidden sm:block'>
          <ThemeSelector />
        </div>
      </div>
    </header>
  );
}
