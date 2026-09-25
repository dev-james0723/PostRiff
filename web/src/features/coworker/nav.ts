'use client';

import { useMemo } from 'react';
import { useCoworkerFlag } from '@/lib/coworker/hooks';
import type { NavGroup, NavItem } from '@/types';

export const WEEKLY_NAV_ITEM: NavItem = { title: 'Weekly', url: '/app/weekly', icon: 'listCheck', items: [], access: { permission: 'edit' } };

/** The groups with Weekly after Calendar in Create, when the deployment has the weekly operator on. */
export function withWeekly(groups: NavGroup[]): NavGroup[] {
  if (groups.some((group) => group.items.some((item) => item.url === WEEKLY_NAV_ITEM.url))) return groups;
  return groups.map((group) => {
    const at = group.items.findIndex((item) => item.url === '/app/calendar');
    if (at < 0) return group;
    return { ...group, items: [...group.items.slice(0, at + 1), WEEKLY_NAV_ITEM, ...group.items.slice(at + 1)] };
  });
}

/** Navigation groups plus Weekly while `RAFII_WEEKLY_OPERATOR_ENABLED` is on (stable identity for memoised filters). */
export function useCoworkerNavGroups(groups: NavGroup[]): NavGroup[] {
  const weekly = useCoworkerFlag('RAFII_WEEKLY_OPERATOR_ENABLED');
  return useMemo(() => (weekly ? withWeekly(groups) : groups), [groups, weekly]);
}
