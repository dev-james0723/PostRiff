'use client';

import { deriveAttention } from '@/lib/attention';

import { useEffect, useState, type MouseEvent } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Icons } from '@/components/icons';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  useSidebar
} from '@/components/ui/sidebar';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
import { navGroups } from '@/config/nav-config';
import { useCoworkerNavGroups } from '@/features/coworker/nav';
import { useFilteredNavGroups } from '@/hooks/use-nav';
import { useNavGroups } from '@/hooks/use-nav-groups';
import { useSnapshot } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import type { NavGroup } from '@/types';
import { WorkspaceSwitcher } from './workspace-switcher';

function isActivePath(pathname: string, url: string) {
  if (url === '/app') return pathname === '/app';
  return pathname === url || pathname.startsWith(url + '/');
}

/** The group whose item (or sub-item) matches the current route; it must never be folded shut. */
function activeGroupLabel(groups: NavGroup[], pathname: string) {
  const match = groups.find((group) =>
    group.items.some(
      (item) => isActivePath(pathname, item.url) || (item.items ?? []).some((sub) => isActivePath(pathname, sub.url))
    )
  );
  return match?.label ?? null;
}

/**
 * One sidebar section (Create, Distribute, …). The header is a tinted band with borders so the
 * sections read as blocks, and a button that folds the section; the choice is remembered per
 * browser. In icon mode the header hides and the section stays open so its icons stay reachable.
 */
function NavGroupSection({
  label,
  open,
  onOpenChange,
  iconMode,
  children
}: {
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  iconMode: boolean;
  children: React.ReactNode;
}) {
  if (!label) return <SidebarGroup className='py-0'>{children}</SidebarGroup>;
  return (
    <Collapsible open={iconMode || open} onOpenChange={onOpenChange} render={<SidebarGroup className='p-0' />}>
      <CollapsibleTrigger
        className='group/navgroup border-sidebar-border bg-sidebar-accent/50 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-sidebar-ring data-panel-open:border-b-sidebar-border flex h-8 w-full shrink-0 items-center justify-between border-y border-b-transparent px-4 text-[11px] font-semibold tracking-[0.08em] uppercase outline-hidden transition-[margin,opacity,background-color] duration-200 ease-linear focus-visible:ring-2 group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0'
        tabIndex={iconMode ? -1 : 0}
        aria-hidden={iconMode || undefined}
      >
        <span>{label}</span>
        <Icons.chevronDown
          aria-hidden
          className='size-3.5 -rotate-90 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/navgroup:rotate-0 motion-reduce:transition-none'
        />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>
        <div className='p-2'>{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * A live count on a nav row (transitions.dev notification badge): it slides onto
 * the row and pops when the count appears, and shrinks away when it reaches zero.
 * The last count stays painted while the dot closes.
 */
function NavCount({ count }: { count: number }) {
  const [shown, setShown] = useState(count);
  useEffect(() => {
    if (count > 0) setShown(count);
  }, [count]);
  return (
    <SidebarMenuBadge aria-hidden data-open={count > 0} className='t-badge'>
      <span className='t-badge-dot bg-primary text-primary-foreground min-w-5 rounded-md px-1 text-center text-[11px] leading-5 font-semibold tabular-nums'>
        {count > 0 ? count : shown}
      </span>
    </SidebarMenuBadge>
  );
}

export default function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, signOut } = useAuth();
  const groups = useFilteredNavGroups(useCoworkerNavGroups(navGroups));
  const snapshot = useSnapshot();
  const { state: sidebarState, isMobile, setOpen: setSidebarOpen, setOpenMobile } = useSidebar();
  // Choosing a page closes the menu on every device: the phone sheet, and the desktop sidebar back to its icon rail.
  const closeMenu = () => (isMobile ? setOpenMobile(false) : setSidebarOpen(false));
  const closeAfterPick = (event: MouseEvent) => {
    // A new-tab click (modifier key or another button) leaves the menu where it is.
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    closeMenu();
  };
  // Icon rail: headers hide and every section stays open, otherwise the icons would vanish with it.
  const iconMode = sidebarState === 'collapsed' && !isMobile;
  const { isOpen, setOpen } = useNavGroups(activeGroupLabel(groups, pathname));
  // Approvals waiting on someone: the only count the sidebar shows, read from the workspace ledger.
  const counts: Record<string, number> = {
    '/app/queue': deriveAttention({ snapshot, channels: { isError: false }, usage: { isError: false }, now: Date.now() / 1000 }).approvals
  };

  return (
    <Sidebar collapsible='icon'>
      <SidebarHeader className='group-data-[collapsible=icon]:pt-4'>
        <WorkspaceSwitcher />
      </SidebarHeader>
      <SidebarContent className='overflow-x-hidden'>
        {groups.map((group) => (
          <NavGroupSection
            key={group.label || 'ungrouped'}
            label={group.label}
            open={isOpen(group.label)}
            onOpenChange={(open) => setOpen(group.label, open)}
            iconMode={iconMode}
          >
            <SidebarMenu>
              {group.items.map((item) => {
                const Icon = item.icon ? Icons[item.icon] : Icons.logo;
                const active = isActivePath(pathname, item.url);
                return item.items && item.items.length > 0 ? (
                  <Collapsible key={item.title} defaultOpen={active} render={<SidebarMenuItem />}>
                    <CollapsibleTrigger
                      render={<SidebarMenuButton tooltip={item.title} isActive={active} className='group/collapsible' />}
                    >
                      <Icon />
                      <span>{item.title}</span>
                      <Icons.chevronRight className='ml-auto transition-transform duration-200 group-data-panel-open/collapsible:rotate-90' />
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <SidebarMenuSub>
                        {item.items.map((sub) => (
                          <SidebarMenuSubItem key={sub.title}>
                            <SidebarMenuSubButton
                              render={<Link href={sub.url} aria-label={sub.title} onClick={closeAfterPick} />}
                              isActive={isActivePath(pathname, sub.url)}
                            >
                              <span>{sub.title}</span>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        ))}
                      </SidebarMenuSub>
                    </CollapsibleContent>
                  </Collapsible>
                ) : (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      render={<Link href={item.url} aria-label={counts[item.url] ? `${item.title}, ${counts[item.url]} waiting for approval` : item.title} onClick={closeAfterPick} />}
                      tooltip={item.title}
                      isActive={active}
                    >
                      <Icon />
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                    {item.url in counts && <NavCount count={counts[item.url]} />}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </NavGroupSection>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <SidebarMenuButton
                    size='lg'
                    className='data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground'
                  />
                }
              >
                <UserAvatarProfile className='h-8 w-8 rounded-lg' showInfo user={user} />
                <Icons.chevronsDown className='ml-auto size-4' />
              </DropdownMenuTrigger>
              <DropdownMenuContent className='w-(--anchor-width) min-w-56 rounded-lg' side='bottom' align='end' sideOffset={4}>
                {/* The trigger already shows who is signed in; the menu repeats it only on the icon rail, where the trigger is just the avatar. */}
                {iconMode && (
                  <>
                    <DropdownMenuGroup>
                      <DropdownMenuLabel className='p-0 font-normal'>
                        <div className='px-1 py-1.5'>
                          <UserAvatarProfile className='h-8 w-8 rounded-lg' showInfo user={user} />
                        </div>
                      </DropdownMenuLabel>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                  </>
                )}
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={() => { closeMenu(); router.push('/app/account/profile'); }}>
                    <Icons.account className='mr-2 h-4 w-4' />
                    Profile
                  </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => { closeMenu(); router.push('/app/account/billing'); }}>
                      <Icons.creditCard className='mr-2 h-4 w-4' />
                      Usage & plan
                    </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => { closeMenu(); router.push('/app/account/privacy'); }}>
                    <Icons.shieldCheck className='mr-2 h-4 w-4' />
                    Privacy & data
                  </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={() => {
                      void signOut().then(() => router.replace('/auth/sign-in'));
                    }}
                  >
                    <Icons.logout aria-hidden className='mr-2 h-4 w-4' />
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
