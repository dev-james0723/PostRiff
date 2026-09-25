'use client';

import { usePathname } from 'next/navigation';
import { useKBar } from 'kbar';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Kbd } from '@/components/ui/kbd';
import { rafiiMenu } from '@/components/auth/form-styles';
import { cn } from '@/lib/utils';
import { SHORTCUTS_EVENT } from '@/components/layout/shortcuts-dialog';
import { tourStore } from './store';
import { pageTourFor } from './tours';

/** The header's help menu: replay the tour, open this page's tips, jump with ⌘K. */
export function HelpMenu() {
  const pathname = usePathname();
  const { query } = useKBar();
  const pageTour = pageTourFor(pathname);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant='ghost' size='icon' aria-label='Help' data-tour='help' />}>
        <Icons.help className='size-[1.2rem]' />
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className={cn(rafiiMenu, 'min-w-60 p-1.5')}>
        <DropdownMenuGroup>
          <DropdownMenuItem className='min-h-10 rounded-[0.625rem]' onClick={() => tourStore.start('welcome')}>
            <Icons.sparkles className='mr-2 size-4' />
            Take the tour
          </DropdownMenuItem>
          {pageTour && (
            <DropdownMenuItem className='min-h-10 rounded-[0.625rem]' onClick={() => tourStore.start(pageTour.id)}>
              <Icons.info className='mr-2 size-4' />
              Tips for {pageTour.title}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem className='min-h-10 rounded-[0.625rem]' onClick={() => query.toggle()}>
            <Icons.search className='mr-2 size-4' />
            Jump to a page
            <span className='ml-auto flex items-center gap-0.5'>
              <Kbd>⌘</Kbd>
              <Kbd>K</Kbd>
            </span>
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuItem className='hidden min-h-10 rounded-[0.625rem] md:flex' onClick={() => window.dispatchEvent(new Event(SHORTCUTS_EVENT))}>
          <Icons.listDetails className='mr-2 size-4' />
          Keyboard shortcuts
          <Kbd className='ml-auto'>?</Kbd>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            className='min-h-10 rounded-[0.625rem]'
            onClick={() => {
              tourStore.reset();
              toast('Tips will show again');
            }}
          >
            <Icons.refresh className='mr-2 size-4' />
            Reset tips
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
