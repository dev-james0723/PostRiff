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

/** How long a deep link keeps its panel in place while the page above it is still loading. */
const HOLD_MS = 5000;

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
    // Panels above the target may still be loading and grow after this scroll, pushing the target out of view. Until the
    // founder scrolls, types or taps (or HOLD_MS pass), every size change of the page re-aligns the target.
    if (typeof ResizeObserver !== 'function') return;
    let held = true;
    const release = () => {
      held = false;
    };
    const inputs = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const;
    for (const name of inputs) window.addEventListener(name, release, { passive: true, once: true });
    const page = document.getElementById('main-content') ?? document.body;
    let primed = false;   // the observer reports every size once on attach; that is not a change
    const observer = new ResizeObserver(() => {
      if (!primed) {
        primed = true;
        return;
      }
      if (held) element.scrollIntoView({ block: 'start', behavior: 'auto' });
    });
    for (const child of Array.from(page.children)) observer.observe(child);
    const timer = window.setTimeout(() => observer.disconnect(), HOLD_MS);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
      for (const name of inputs) window.removeEventListener(name, release);
    };
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
