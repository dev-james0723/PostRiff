'use client';
import { useMemo } from 'react';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { usePreferences } from '@/lib/preferences';
import type { NavGroup } from '@/types';
import { language, text } from './model';

/** One Task Center entry shared by the desktop/mobile drawer and command palette. */
export function useTaskNavGroups(groups: NavGroup[]): NavGroup[] {
  const agent = useAgent();
  const { locale } = usePreferences();
  const enabled = !agent.statusError && agent.status?.tasks?.enabled === true;
  return useMemo(() => {
    if (!enabled || groups.some((group) => group.items.some((item) => item.url === '/app/tasks'))) return groups;
    return groups.map((group) => {
      const index = group.items.findIndex((item) => item.url === '/app');
      if (index < 0) return group;
      return { ...group, items: [...group.items.slice(0, index + 1), { title: text('title', language(locale)), url: '/app/tasks', icon: 'listCheck' as const, items: [] }, ...group.items.slice(index + 1)] };
    });
  }, [enabled, groups, locale]);
}
