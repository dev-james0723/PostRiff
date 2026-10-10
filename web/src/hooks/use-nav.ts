'use client';

/**
 * Client-side navigation filtering.
 *
 * Reads the workspace access context (see `@/lib/auth/access`) and hides
 * items whose `access` requirements are not met. This is UX only: the API
 * enforces permissions on every request.
 */

import { useMemo } from 'react';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { NavGroup, NavItem } from '@/types';
import { useAgentPermissions } from '@/features/account/agent/use-agent-permissions';
import { permissionsUiEnabled } from '@/lib/agent-permissions/model';

/**
 * Filter navigation items (and their children) against the current workspace access.
 */
export function useFilteredNavItems(items: NavItem[]) {
  const access = useWorkspaceAccess();
  const permissionQuery = useAgentPermissions({ enabled: permissionsUiEnabled() });
  const permissionsVisible = permissionsUiEnabled() && Boolean(permissionQuery.data);

  return useMemo(() => {
    return items
      .filter((item) => checkAccess(access, item.access) && (item.url !== '/app/account/agent' || permissionsVisible))
      .map((item) => {
        if (item.items && item.items.length > 0) {
          return {
            ...item,
            items: item.items.filter((child) => checkAccess(access, child.access))
          };
        }
        return item;
      });
  }, [items, access, permissionsVisible]);
}

/**
 * Filter navigation groups; groups left with no visible items are removed.
 */
export function useFilteredNavGroups(groups: NavGroup[]) {
  const allItems = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const filteredItems = useFilteredNavItems(allItems);

  return useMemo(() => {
    const visible = new Set(filteredItems.map((item) => item.title));
    return groups
      .map((group) => ({
        ...group,
        items: filteredItems.filter((item) =>
          group.items.some((gi) => gi.title === item.title && visible.has(gi.title))
        )
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, filteredItems]);
}
