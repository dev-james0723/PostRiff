'use client';

import { useEffect, useState } from 'react';
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
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail
} from '@/components/ui/sidebar';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
import { navGroups } from '@/config/nav-config';
import { useFilteredNavGroups } from '@/hooks/use-nav';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAuth } from '@/lib/auth/session';
import { WorkspaceSwitcher } from './workspace-switcher';

function isActivePath(pathname: string, url: string) {
  if (url === '/app') return pathname === '/app';
  return pathname === url || pathname.startsWith(url + '/');
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
  const access = useWorkspaceAccess();
  const groups = useFilteredNavGroups(navGroups);
  const snapshot = useSnapshot();
  // Approvals waiting on someone: the only count the sidebar shows, read from the workspace ledger.
  const counts: Record<string, number> = {
    '/app/queue': (snapshot.data?.state.phase2?.reviews ?? []).filter((r) => r.status === 'needs_review').length
  };

  return (
    <Sidebar collapsible='icon'>
      <SidebarHeader className='group-data-[collapsible=icon]:pt-4'>
        <WorkspaceSwitcher />
      </SidebarHeader>
      <SidebarContent className='overflow-x-hidden'>
        {groups.map((group) => (
          <SidebarGroup key={group.label || 'ungrouped'} className='py-0'>
            {group.label && <SidebarGroupLabel>{group.label}</SidebarGroupLabel>}
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
                              render={<Link href={sub.url} aria-label={sub.title} />}
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
                      render={<Link href={item.url} aria-label={counts[item.url] ? `${item.title}, ${counts[item.url]} waiting for approval` : item.title} />}
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
          </SidebarGroup>
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
                <DropdownMenuGroup>
                  <DropdownMenuLabel className='p-0 font-normal'>
                    <div className='px-1 py-1.5'>
                      <UserAvatarProfile className='h-8 w-8 rounded-lg' showInfo user={user} />
                    </div>
                  </DropdownMenuLabel>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={() => router.push('/app/account/profile')}>
                    <Icons.account className='mr-2 h-4 w-4' />
                    Profile
                  </DropdownMenuItem>
                  {checkAccess(access, { permission: 'owner' }) && (
                    <DropdownMenuItem onClick={() => router.push('/app/account/billing')}>
                      <Icons.creditCard className='mr-2 h-4 w-4' />
                      Usage & plan
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem onClick={() => router.push('/app/account/privacy')}>
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
