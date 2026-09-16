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

/**
 * Filter navigation items (and their children) against the current workspace access.
 */
export function useFilteredNavItems(items: NavItem[]) {
  const access = useWorkspaceAccess();

  return useMemo(() => {
    return items
      .filter((item) => checkAccess(access, item.access))
      .map((item) => {
        if (item.items && item.items.length > 0) {
          return {
            ...item,
            items: item.items.filter((child) => checkAccess(access, child.access))
          };
        }
        return item;
      });
  }, [items, access]);
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
