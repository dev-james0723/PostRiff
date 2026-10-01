'use client';

import { useEffect, type ReactNode } from 'react';
import { parseAsString, useQueryState } from 'nuqs';
import { FOUNDER_SECTIONS, type FounderSectionId } from '@/config/founder-nav';
import { cn } from '@/lib/utils';
import { resolveTab, tabAnchorId } from './tab-ids';

/**
 * `?tab=` deep links for the domain pages. `FOUNDER_SECTIONS[section].tabs` (config/founder-nav.ts) is the one list of
 * ids a page answers to; the Overview, the server's attention hrefs and the retired `/control/*` redirects use those ids
 * or one of the aliases in `tab-ids.ts`. A page with real tabs selects the resolved one; a page of stacked panels
 * scrolls the matching `TabAnchor` into view and outlines it. An unknown value resolves to nothing (the page top),
 * never silently to another tab.
 */
export { TAB_ALIASES, resolveTab, tabAnchorId } from './tab-ids';

/** The resolved `?tab=` of a stacked-panel page; the matching anchor is scrolled into view when it changes. */
export function useSectionTab(section: FounderSectionId): string | null {
  const [raw] = useQueryState('tab', parseAsString);
  const tab = resolveTab(raw, FOUNDER_SECTIONS[section].tabs);
  useEffect(() => {
    if (!tab) return;
    const element = document.getElementById(tabAnchorId(section, tab));
    if (!element) return;
    const reduce = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    element.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });
  }, [section, tab]);
  return tab;
}

/** The address a page with real tabs keeps: the resolved tab (or its default) and a setter that clears the default. */
export function useTabState(section: FounderSectionId, fallback: string): [string, (next: string) => void] {
  const [raw, setRaw] = useQueryState('tab', parseAsString.withOptions({ history: 'replace' }));
  const tabs = FOUNDER_SECTIONS[section].tabs;
  const tab = resolveTab(raw, tabs) ?? fallback;
  return [tab, (next) => void setRaw(next === fallback ? null : next)];
}

/** Wraps one panel so a `?tab=` link can land on it; the active one is outlined. Children fill the wrapper (grid cells stay even). */
export function TabAnchor({ section, tab, active, children, className }: { section: FounderSectionId; tab: string; active: string | null; children: ReactNode; className?: string }) {
  return (
    <div id={tabAnchorId(section, tab)} data-tab={tab} className={cn('flex min-w-0 scroll-mt-24 flex-col rounded-[var(--rafii-radius-card)] [&>*]:flex-1', active === tab && 'ring-1 ring-foreground/30', className)}>
      {children}
    </div>
  );
}
