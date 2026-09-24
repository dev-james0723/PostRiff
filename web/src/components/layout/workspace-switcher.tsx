'use client';

import { rafiiMenu } from '@/components/auth/form-styles';
import { Icons } from '@/components/icons';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from '@/components/ui/sidebar';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import { useSnapshot } from '@/lib/api/hooks';
import { useWorkspace } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';

function shortId(id: string) {
  return id.slice(0, 8);
}

/** The rail's workspace lens (DNA §8.2): the current workspace and role, a glass menu to switch. */
export function WorkspaceSwitcher() {
  const { isMobile, state } = useSidebar();
  const { workspaces, workspaceId, membership, switchTo } = useWorkspace();
  const snapshot = useSnapshot();
  const name = snapshot.data?.state.workspace?.name || 'My workspace';
  const collapsed = state === 'collapsed';

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                size='lg'
                className='data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground rounded-[var(--rafii-radius-control)]'
              />
            }
          >
            <div className='rafii-action flex aspect-square size-8 shrink-0 items-center justify-center rounded-[0.625rem]'>
              <Icons.workspace className='size-4' />
            </div>
            <div
              className={cn(
                'grid flex-1 text-left text-sm leading-tight transition-all duration-200 ease-in-out',
                collapsed ? 'invisible max-w-0 overflow-hidden opacity-0' : 'visible max-w-full opacity-100'
              )}
            >
              <span className='truncate font-medium'>{name}</span>
              <span className='text-muted-foreground truncate text-xs'>
                {membership ? ROLE_LABELS[membership.role] : 'Workspace'}
              </span>
            </div>
            <Icons.chevronsUpDown
              className={cn(
                'ml-auto transition-all duration-200 ease-in-out',
                collapsed ? 'invisible max-w-0 opacity-0' : 'visible max-w-full opacity-100'
              )}
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className={cn(rafiiMenu, 'w-(--anchor-width) min-w-60 p-1.5')}
            align='start'
            side={isMobile ? 'bottom' : 'right'}
            sideOffset={4}
          >
            <DropdownMenuGroup>
              <DropdownMenuLabel className='rafii-eyebrow px-2 py-1.5'>Workspaces</DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuGroup>
              {workspaces.map((item) => {
                const active = item.workspaceId === workspaceId;
                return (
                  <DropdownMenuItem
                    key={item.workspaceId}
                    onClick={() => switchTo(item.workspaceId)}
                    className={cn('min-h-10 gap-2 rounded-[0.625rem] p-2', active && 'rafii-lens')}
                  >
                    <div className='rafii-quiet flex size-6 shrink-0 items-center justify-center overflow-hidden rounded-md'>
                      <Icons.workspace className='size-3.5 shrink-0' />
                    </div>
                    <span className='flex-1 truncate'>
                      {active ? name : item.name || `Workspace ${shortId(item.workspaceId)}`}
                    </span>
                    <span className='text-muted-foreground text-xs'>{ROLE_LABELS[item.membership.role]}</span>
                    {active && <Icons.check className='ml-1 size-4' />}
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuGroup>
            <DropdownMenuSeparator className='bg-transparent' />
            <DropdownMenuGroup>
              <DropdownMenuLabel className='text-muted-foreground px-2 pt-0 pb-1.5 text-xs font-normal'>
                You join other workspaces by invitation.
              </DropdownMenuLabel>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
