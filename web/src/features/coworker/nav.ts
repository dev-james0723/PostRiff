'use client';

import { useMemo } from 'react';
import { useCoworkerFlag, useCoworkerStatus } from '@/lib/coworker/hooks';
import { flagsFrom, radarEnabled } from '@/features/trends/hooks';
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

export const TRENDS_NAV_ITEM: NavItem = { title: 'Trends', url: '/app/trends', icon: 'trendingUp', items: [] };

/** A future legacy Radar integration gets one primary slot, never two independent engines. */
export function withTrends(groups: NavGroup[]): NavGroup[] {
  let added = false;
  const mapped = groups.map(group => ({ ...group, items: group.items.flatMap(item => {
    if (item.url === '/app/radar' || item.url === '/app/trends') { if (added) return []; added = true; return [TRENDS_NAV_ITEM]; }
    return [item];
  }) }));
  if (added) return mapped;
  return mapped.map(group => {
    const at = group.items.findIndex(item => item.url === '/app/ideas');
    if (added || at < 0) return group;
    added = true;
    return { ...group, items: [...group.items.slice(0, at + 1), TRENDS_NAV_ITEM, ...group.items.slice(at + 1)] };
  });
}

/** Navigation groups plus Weekly while `RAFII_WEEKLY_OPERATOR_ENABLED` is on (stable identity for memoised filters). */
export function useCoworkerNavGroups(groups: NavGroup[]): NavGroup[] {
  const weekly = useCoworkerFlag('RAFII_WEEKLY_OPERATOR_ENABLED');
  const status = useCoworkerStatus();
  const trends = !status.isError && radarEnabled(flagsFrom(status.data?.flags));
  return useMemo(() => { const base = weekly ? withWeekly(groups) : groups; return trends ? withTrends(base) : base; }, [groups, weekly, trends]);
}
