'use client';

import type { MouseEvent } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icons } from '@/components/icons';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarRail, useSidebar } from '@/components/ui/sidebar';
import { FOUNDER_NAV_GROUPS, FOUNDER_SECTIONS, founderHref, isActiveFounderPath } from '@/config/founder-nav';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { useFounderSession } from './founder-session';

const ENVIRONMENT_LABEL: Record<string, string> = { local: 'Local', staging: 'Staging', production: 'Production' };

/**
 * The founder sidebar: the eight sections in three groups, the environment badge in the footer (an environment is
 * where this runs; Demo is a data mode and lives in the header), and sign out. Links keep `?mode=demo` when it is on.
 */
export function FounderSidebar() {
  const pathname = usePathname() ?? '/founder';
  const { mode, environment, sessionStatus, signOut } = useFounderSession();
  const { isMobile, setOpen, setOpenMobile, state } = useSidebar();
  const iconMode = state === 'collapsed' && !isMobile;
  const closeAfterPick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (isMobile) setOpenMobile(false);
    else setOpen(false);
  };
  return (
    <Sidebar collapsible='icon'>
      <SidebarHeader className='group-data-[collapsible=icon]:pt-4'>
        <Link href={founderHref('overview', mode)} onClick={closeAfterPick} className='rafii-focus flex min-h-10 items-center gap-2 rounded-lg px-2' aria-label='Rafii Founder, Overview'>
          <span className='bg-foreground text-background flex size-7 shrink-0 items-center justify-center rounded-lg text-xs font-semibold'>R</span>
          <span className='flex min-w-0 flex-col leading-tight group-data-[collapsible=icon]:hidden'>
            <span className='text-sm font-semibold'>Rafii</span>
            <span className='text-muted-foreground text-[11px]'>Founder admin</span>
          </span>
        </Link>
      </SidebarHeader>
      <SidebarContent className='overflow-x-hidden'>
        {FOUNDER_NAV_GROUPS.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarMenu>
              {group.items.map((id) => {
                const section = FOUNDER_SECTIONS[id];
                const Icon = Icons[section.icon];
                const active = isActiveFounderPath(pathname, section.url);
                return (
                  <SidebarMenuItem key={id}>
                    <SidebarMenuButton render={<Link href={founderHref(id, mode)} aria-label={section.title} onClick={closeAfterPick} />} tooltip={section.title} isActive={active}>
                      <Icon />
                      <span>{section.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger render={<SidebarMenuButton size='lg' aria-label='Founder session' className='data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground' />}>
                <span className='rafii-glass flex size-8 shrink-0 items-center justify-center rounded-lg'>
                  <Icons.shieldCheck className='size-4' aria-hidden />
                </span>
                <span className={cn('flex min-w-0 flex-1 flex-col text-left leading-tight', iconMode && 'hidden')}>
                  <span className='truncate text-sm font-medium'>Founder session</span>
                  <span className='text-muted-foreground truncate text-[11px]'>{sessionStatus === 'ready' ? 'Verified · second factor shown' : sessionStatus === 'loading' ? 'Verifying…' : 'Could not verify'}</span>
                </span>
                {!iconMode && <StatusChip icon={null} className='h-6 shrink-0 px-2 text-[11px]' title='Environment'>{environment ? ENVIRONMENT_LABEL[environment] ?? environment : '…'}</StatusChip>}
              </DropdownMenuTrigger>
              <DropdownMenuContent className='w-(--anchor-width) min-w-56 rounded-lg' side='top' align='end' sideOffset={4}>
                <DropdownMenuItem onClick={() => void signOut()}>
                  <Icons.logout aria-hidden className='mr-2 size-4' />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
